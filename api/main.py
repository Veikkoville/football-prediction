"""
GoalIQ Backend API — FastAPI-pohjainen REST-rajapinta.

Korvaa Streamlitin käyttöliittymän JSON-API:lla jota mobiili-app
(React Native) ja muut clientit voivat kutsua.

Käynnistys lokaalisti:
    uvicorn api.main:app --reload --port 8000

Sitten avaa selain:
    http://localhost:8000          → tervehdys
    http://localhost:8000/docs     → automaattinen Swagger-dokumentaatio
    http://localhost:8000/api/leagues → JSON-lista saatavilla olevista liigoista
"""

from __future__ import annotations

import copy
import json
import os
import random
import re
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal, Optional

# Lisää projektin juuri Python-polkuun jotta `src.*` -importit toimivat
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
import stripe
from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator

import config
from src.data.loader import lataa_otteludata
from src.models.dixon_coles import DixonColesModel, apply_match_adjustments

import requests

# Edge-sprint P0: admin-portti + PREMIUM_ENFORCE-maskit (default off — kun
# flagi on pois, is_premium_request palauttaa aina True eika mikaan muutu).
from api.premium import (
    FREE_PREMIUM_UNTIL_DEFAULT, free_premium_window_active,
    is_premium_request, mask_plan_payload, mask_xp_payload, xp_pool_rows,
    premium_enforce_on, require_admin,
)

# Stripe-konfiguraatio (Render env varseista)
stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_PRICE_ID = os.getenv("STRIPE_PRICE_ID", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
# GoalIQ Pro (web/pro) -Checkoutin OMA webhook-endpoint-secret — eri kuin
# mobiilin STRIPE_WEBHOOK_SECRET (Stripe-dashboardissa 2 eri endpointtia).
STRIPE_WEB_WEBHOOK_SECRET = os.getenv("STRIPE_WEB_WEBHOOK_SECRET", "")
# GoalIQ Pro -webin hinnat (QUEUE #14: SPA ei voi pitää salaisuuksia →
# checkout-session luodaan täällä). SAMAT env-nimet kuin goaliq-pro-web-
# Streamlit-palvelussa → arvot voi kopioida sellaisenaan API-serviceen.
STRIPE_PRICE_MONTHLY_ID = os.getenv("STRIPE_PRICE_MONTHLY_ID", "")
STRIPE_PRICE_SEASON_ID = os.getenv("STRIPE_PRICE_SEASON_ID", "")
# Sallitut SPA-originit success/cancel-redirecteille (avoin redirect estetty:
# origin validoidaan tätä listaa vasten). Laajenna envillä tarvittaessa.
WEB_CHECKOUT_ORIGINS = [
    o.strip().rstrip("/")
    for o in os.getenv(
        "WEB_CHECKOUT_ORIGINS",
        "https://pro.goaliq.app,https://pro-next.goaliq.app,http://localhost:4173,http://localhost:5173",
    ).split(",")
    if o.strip()
]

# RevenueCat (Google Play Billing) -webhookin jaettu salaisuus. Arvo on sama
# merkkijono joka asetetaan RevenueCat-dashboardin webhook-asetuksiin
# (Authorization header value) — RevenueCat lahettaa sen sellaisenaan
# Authorization-headerissa. Tyhja => webhook ei kasittele (ei luvattomia
# is_premium-kirjoituksia).
REVENUECAT_WEBHOOK_AUTH = os.getenv("REVENUECAT_WEBHOOK_AUTH", "")

# Supabase-konfiguraatio webhook-päivityksiä varten.
# SUPABASE_SERVICE_ROLE_KEY on backend-only-key (ei saa koskaan vuotaa frontille);
# se ohittaa Row Level Securityn, jotta webhook voi päivittää profiilin.
SUPABASE_URL = os.getenv("SUPABASE_URL", "")  # esim. https://xxxx.supabase.co
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")


def _update_profile(user_id: str, fields: dict) -> bool:
    """
    Geneerinen Supabase profiles -paivitys. fields = sarakkeet jotka asetetaan.
    Palauttaa True jos onnistui, False jos epaonnistui (logaa virheen).
    """
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        print(f"[Supabase] WARNING: missing env vars, cannot update user_id={user_id}")
        return False

    url = f"{SUPABASE_URL}/rest/v1/profiles?id=eq.{user_id}"
    headers = {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }
    try:
        resp = requests.patch(url, json=fields, headers=headers, timeout=10)
        if resp.status_code in (200, 204):
            print(f"[Supabase] Updated user_id={user_id} fields={fields}")
            return True
        print(
            f"[Supabase] FAILED status={resp.status_code} body={resp.text[:200]} "
            f"user_id={user_id}"
        )
        return False
    except Exception as e:
        print(f"[Supabase] EXCEPTION user_id={user_id}: {e}")
        return False


def _update_profile_premium(user_id: str, is_premium: bool) -> bool:
    """Yksinkertaistettu wrapper vain is_premium -kentalle."""
    return _update_profile(user_id, {"is_premium": is_premium})


def _stamp_premium_source(user_id: str, source: str) -> bool:
    """WEB-SUB-SYNC (13.8): premium-lahteen leima profiiliin.

    source: 'stripe_web' | 'revenuecat' ('comp' asetetaan vain kasin/SQL:lla
    — koodipolkua compille ei ole olemassa tarkoituksella).

    ERILLINEN kutsu tarkoituksella, EI osana is_premium-PATCHia: PATCH on
    atominen, ja jos premium_source-saraketta ei ole viela migratoitu,
    yhdistetty kutsu kaataisi myos premium-aktivoinnin. Leima ei koskaan
    saa estaa premiumin avausta — epaonnistuminen jaa lokiin ja
    seuraava webhook-event yrittaa uudelleen.
    """
    return _update_profile(user_id, {"premium_source": source})


def _web_subscription_active(user_id: str) -> bool:
    """Onko käyttäjällä aktiivinen WEB-tilaus (web_subscriptions).

    NO-CLOBBER-synkan (web-v1 #7) ydin: mobiilipolut (RC EXPIRATION,
    mobiili-Stripen deleted) EIVÄT saa nollata profiles.is_premiumia jos
    web-tilaus on voimassa. current_period_end NULL = aktiivinen (period
    täyttyy subscription.updated-eventissä).
    """
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        return False
    url = (f"{SUPABASE_URL}/rest/v1/web_subscriptions"
           f"?user_id=eq.{user_id}&status=eq.active"
           f"&select=current_period_end")
    headers = {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
    }
    try:
        rows = requests.get(url, headers=headers, timeout=10).json()
        for r in rows if isinstance(rows, list) else []:
            end = r.get("current_period_end")
            if end is None:
                return True
            try:
                if datetime.fromisoformat(end) > datetime.now(timezone.utc):
                    return True
            except ValueError:
                return True  # epäselvä timestamp -> älä nollaa premiumia
        return False
    except Exception as e:
        # Verkkovirhe: fail-safe premiumin SÄILYTTÄMISEN suuntaan (parempi
        # että churnannut saa hetken ekstraa kuin että maksava menettää).
        print(f"[Supabase] web_subscription_active EXCEPTION: {e}")
        return True


def _get_web_subscription(match_field: str, match_value: str) -> dict | None:
    """Hae web-tilausrivi (esim. stripe_subscription_id:llä -> user_id)."""
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        return None
    url = (f"{SUPABASE_URL}/rest/v1/web_subscriptions"
           f"?{match_field}=eq.{match_value}&select=*&limit=1")
    headers = {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
    }
    try:
        rows = requests.get(url, headers=headers, timeout=10).json()
        return rows[0] if isinstance(rows, list) and rows else None
    except Exception:
        return None


def _mobile_possibly_active(user_id: str, web_period_end: str | None) -> bool:
    """Heuristiikka: onko käyttäjällä todennäköisesti aktiivinen MOBIILI-
    tilaus (RC/Play/App Store)? profiles.subscription_current_period_end
    tulevaisuudessa JA eri kuin web-subin period_end → toinen lähde elää.
    Käytetään VAIN web-peruutuksen no-clobber-guardina; RC-renewal
    re-assertoi is_premium=True kuukausittain joten väärä True tässä on
    itsekorjautuva, väärä False veisi maksavalta premiumin."""
    end = _get_profile_period_end(user_id)
    if not end:
        return False
    try:
        if datetime.fromisoformat(end) <= datetime.now(timezone.utc):
            return False
    except ValueError:
        return True
    return end != web_period_end


def _get_profile_period_end(user_id: str) -> str | None:
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        return None
    url = (f"{SUPABASE_URL}/rest/v1/profiles?id=eq.{user_id}"
           f"&select=subscription_current_period_end")
    headers = {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
    }
    try:
        rows = requests.get(url, headers=headers, timeout=10).json()
        return rows[0].get("subscription_current_period_end") if rows else None
    except Exception:
        return None


def _upsert_web_subscription(fields: dict, match: dict | None = None) -> bool:
    """GoalIQ Pro (web/pro) -tilausten kirjaus web_subscriptions-tauluun.

    match=None → upsert user_id-avaimella (checkout.completed).
    match={"stripe_subscription_id": ...} → PATCH olemassa olevaan riviin
    (subscription.updated/deleted, joissa user_id ei ole payloadissa).
    Sama service-role-REST-kuvio kuin _update_profile.
    """
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        print("[Supabase] WARNING: missing env vars, cannot write web_subscriptions")
        return False
    headers = {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal,resolution=merge-duplicates",
    }
    try:
        if match:
            key, val = next(iter(match.items()))
            url = f"{SUPABASE_URL}/rest/v1/web_subscriptions?{key}=eq.{val}"
            resp = requests.patch(url, json=fields, headers=headers, timeout=10)
        else:
            url = f"{SUPABASE_URL}/rest/v1/web_subscriptions?on_conflict=user_id"
            resp = requests.post(url, json=fields, headers=headers, timeout=10)
        if resp.status_code in (200, 201, 204):
            print(f"[Supabase] web_subscriptions ok fields={list(fields)}")
            return True
        print(f"[Supabase] web_subscriptions FAILED status={resp.status_code} "
              f"body={resp.text[:200]}")
        return False
    except Exception as e:
        print(f"[Supabase] web_subscriptions EXCEPTION: {e}")
        return False


def _stripe_field(obj, key, default=None):
    """Kentta joko Stripe-objektista TAI tavallisesta dictista.

    🔴 MITATTU TUOTANNOSTA 16.8. `stripe`-kirjaston 15.x-sarjassa
    `Subscription`, `PromotionCode` ja `metadata` EIVAT ole dict-alaluokkia
    eika niilla ole `.get()`-metodia: `sub.get("discount")` heittaa
    `AttributeError: get`. Webhookin oma payload sen sijaan on
    `json.loads`-dict, jossa `.get` toimii - eli sama koodirivi kasittelee
    kahta eri tyyppia sen mukaan tuliko arvo eventista vai API-haulla.

    Ero ei nakynyt testeissa, koska jokainen testikaksoisolento oli dict.
    Se nakyi tuotannossa kahdella tavalla: affiliate-raportin Stripe-puoli
    palautti hiljaa `sources_ok.stripe = false`, ja
    `_affiliate_code_from_session` heitti poikkeuksen KESKELLA
    web-checkoutin fulfillmentia (tilausrivi kirjoitettu, `is_premium`
    kirjoittamatta).
    """
    if obj is None:
        return default
    if isinstance(obj, dict):
        value = obj.get(key, default)
    else:
        try:
            value = obj[key]
        except Exception:
            value = getattr(obj, key, default)
    # Eksplisiittinen None kohdellaan puuttuvana molemmilla poluilla: Stripe
    # palauttaa `discount: null` yhta usein kuin jattaa kentan pois, ja
    # kutsupaikat ketjuttavat naita (`_stripe_field(discount, ...)`).
    return default if value is None else value


def _promo_code_string(promo) -> Optional[str]:
    """Promokoodi-viitteestä sen näkyvä merkkijono (esim. "ROWAN").

    Webhookin payload voi kantaa promokoodin joko laajennettuna objektina tai
    pelkkänä ID:nä (`promo_...`) riippuen siitä miten sessio luotiin. Kumpikin
    tapaus on käsiteltävä, koska väärä oletus näkyy vasta tuotannossa
    puuttuvana leimana — eikä silloin ole enää mitään mistä leimata.
    """
    if isinstance(promo, str):
        if not promo.startswith("promo_"):
            return None
        try:
            obj = stripe.PromotionCode.retrieve(promo)
            return _stripe_field(obj, "code") or None
        except Exception as e:
            print(f"[affiliate] PromotionCode.retrieve epäonnistui {promo}: {e}")
            return None
    # Laajennettu viite: webhookin payloadissa dict, API-haussa StripeObject.
    return _stripe_field(promo, "code") or None


def _affiliate_code_from_session(obj: dict) -> Optional[tuple[str, str]]:
    """Checkout-sessiosta luettu affiliate-koodi JA sen lahde.

    Palauttaa `(koodi, lahde)` jossa lahde on "promo" tai "ref".

    🔴 LAHDE ON PAKKO TALLENTAA LEIMAUSHETKELLA. Leima naytti aiemmin
    samalta kummastakin polusta, eika sita voi paatella jalkikateen:
    kupongit ovat `duration: once`, joten alennus irtoaa ensimmaisen laskun
    jalkeen eika tilauksesta enaa nae kaytettiinko koodia. Ilman lahdetta
    kirjoitettu leima jaa pysyvasti tulkinnanvaraiseksi, ja GW19:n payout
    perustuisi arvaukseen.

    Konkreettinen seuraus jos tama unohtuu: `check_affiliate_attribution.py`
    vertaa leimoja Stripen `times_redeemed`-laskuriin ja kutsuu tilaa
    `stamped > redeemed` MAHDOTTOMAKSI. Ref-polku tuottaa tasan sellaisia
    leimoja - lunastusta ei tapahdu - joten ensimmainen ref-attribuoitu
    maksu tekisi vahdista punaisen tilanteessa jossa kaikki toimi oikein.
    Vaara halytys on pahempi kuin puuttuva: se opettaa lakkaamaan lukemasta
    vahtia juuri ennen kuin provisioita aletaan maksaa.

    AFF-ATTRIB (11.8): affiliate-kupongit ovat `duration: once`, joten alennus
    IRTOAA tilaukselta ensimmäisen laskun jälkeen eikä Stripe enää kerro että
    juuri tämä uusiutuva tilaus tuli affiliate-koodista. Provisio on kuitenkin
    luvattu "for as long as they stay subscribed", joten yhteys on tallennettava
    pysyvästi. `checkout.session.completed` on se ainoa hetki jolloin se on
    luettavissa: se laukeaa heti ensimmäisen maksun jälkeen, jolloin discount on
    vielä kiinni sekä sessiossa että tilauksessa.

    Kaksi polkua, koska webhookin payload ei ole aina laajennettu:
      1. session.discounts[].promotion_code
      2. fallback: tilauksen oma discount samalla hetkellä
    """
    for d in (obj.get("discounts") or []):
        if not isinstance(d, dict):
            continue
        code = _promo_code_string(d.get("promotion_code"))
        if code:
            return code, "promo"

    # 🔴 EI aikaista returnia taalla. Ref-fallback (kohta 3) on VIIMEINEN
    # sana kaikilla poluilla, myos silloin kun tilausta ei ole tai sen haku
    # kaatuu. Ensimmainen versio palautti tassa Nonen ja ref jai lukematta -
    # portti nappasi sen.
    sub_id = obj.get("subscription")
    if sub_id and isinstance(sub_id, str):
        try:
            sub = stripe.Subscription.retrieve(sub_id)
        except Exception as e:
            print(f"[affiliate] Subscription.retrieve epäonnistui {sub_id}: {e}")
            sub = None
        # 🔴 EI `sub.get(...)`: `stripe.Subscription` ei ole dict eika sillä
        # ole `.get`-metodia (ks. `_stripe_field`). Tama rivi heitti
        # `AttributeError`in KESKELLA fulfillmentia, kutsupaikassa jossa ei
        # ole try-lohkoa - eli web_subscriptions oli jo kirjoitettu mutta
        # `profiles.is_premium` ei, ja guest-ostaja jai ilman magic linkkia.
        discount = _stripe_field(sub, "discount") or {}
        code = _promo_code_string(_stripe_field(discount, "promotion_code"))
        if code:
            return code, "promo"

    # 3. REF-FALLBACK (16.8). Kaksi ensimmäistä polkua lukevat KÄYTETYN
    #    promokoodin, eli ne toimivat vain jos asiakas maksoi alennuksella.
    #
    #    GW1-GW3 ilmaisikkuna rikkoi tämän: luojan katsoja tulee ikkunan
    #    aikana, luo ilmaisen tilin, käyttää tuotetta neljä viikkoa ja maksaa
    #    12.9. jälkeen TÄYTTÄ HINTAA ilman koodia. Molemmat polut palauttavat
    #    silloin None, ja luoja jää ilman provisiota vaikka toi asiakkaan.
    #    Provisio on luvattu "for as long as they keep the subscription"
    #    (DM 12.8), joten se lupaus ei saa katketa siihen että tarjosimme
    #    tuotetta ilmaiseksi.
    #
    #    Ref matkustaa checkout-session metadatassa: SPA poimii `?ref=` ja
    #    säilöö sen selaimeen, ja lähettää sen checkout-kutsussa. Ei uutta
    #    kantasaraketta, joten ei migraatiota tuotantoon.
    meta = obj.get("metadata") or {}
    if isinstance(meta, dict):
        ref = _clean_affiliate_ref(meta.get("ref"))
        if ref:
            return ref, "ref"

    # 4. TILIN REF (16.8, Villen havainto: "kaikkihan avaa sen x:sta suoraan").
    #
    #    Kohta 3 nojaa selaimeen sailottuun refiin, ja X avaa linkit omassa
    #    sisaisessa selaimessaan jonka muisti on eri kuin Safarin tai
    #    Chromen. Katsoja klikkaa X:ssa, ref tallentuu siihen webviewiin, ja
    #    nelja viikkoa myohemmin han maksaa oikealla selaimella -> kohta 3
    #    palauttaa Nonen. Se on luojaliikenteen TAVALLISIN polku, ei
    #    reunatapaus.
    #
    #    Rekisteroityessa ref kirjoitetaan tilin metadataan, ja tili kulkee
    #    laitteesta toiseen. Tama on siksi kestavin naista neljasta.
    uid = obj.get("client_reference_id")
    if uid and isinstance(uid, str):
        ref = _account_affiliate_ref(uid)
        if ref:
            return ref, "ref"
    return None


def _account_user_metadata(user_id: str) -> Optional[dict]:
    """Tilin `raw_user_meta_data` Supabasen admin-API:sta.

    None = EI TIETOA (config puuttuu, verkkovirhe, tuntematon tili) — eri
    asia kuin `{}` joka tarkoittaa "tili on, metadata on tyhja". Kutsujan on
    erotettava nama: creator-raportti nayttaisi muuten verkkovirheen
    "et ole luoja" -viestina.
    """
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY or not user_id:
        return None
    key = SUPABASE_SERVICE_ROLE_KEY
    try:
        r = requests.get(
            f"{SUPABASE_URL}/auth/v1/admin/users/{user_id}",
            headers={"apikey": key, "Authorization": f"Bearer {key}"},
            timeout=10)
        if r.status_code != 200:
            return None
        return (r.json() or {}).get("user_metadata") or {}
    except Exception as e:
        print(f"[affiliate] tilin metadata-haku epaonnistui {user_id}: "
              f"{type(e).__name__}: {e}")
        return None


def _account_affiliate_ref(user_id: str) -> Optional[str]:
    """Tilin metadataan rekisteroityessa kirjattu luojan ref.

    Fail-soft: attribuution puuttuminen ei saa kaataa fulfillmentia.
    Asiakas on jo maksanut ja premium on aktivoitava.
    """
    meta = _account_user_metadata(user_id)
    if meta is None:
        return None
    return _clean_affiliate_ref(meta.get("ref"))


def _account_creator_code(user_id: str) -> Optional[str]:
    """Luojan OMA koodi tilin metadatassa (`creator_code`).

    Eri kentta kuin `ref`: `ref` kertoo KENEN kautta tama tili tuli, ja
    `creator_code` kertoo etta tama tili SAA nahda yhden koodin luvut. Sama
    ihminen voi olla molempia (luoja joka tuli toisen luojan linkista), joten
    kenttien yhdistaminen antaisi hanelle paasyn vaaran koodin lukuihin.
    """
    meta = _account_user_metadata(user_id)
    if meta is None:
        return None
    return _clean_affiliate_ref(meta.get("creator_code"))


# Sallitut merkit affiliate-refissä. Arvo päätyy Stripe-metadataan ja
# payout-täsmäytykseen, joten se normalisoidaan tiukasti eikä luoteta
# siihen mitä URLissa sattui olemaan.
_REF_RE = re.compile(r"^[A-Z0-9_-]{2,32}$")


def _clean_affiliate_ref(value) -> Optional[str]:
    """Normalisoi ja validoi affiliate-ref. Kelvoton -> None."""
    if not isinstance(value, str):
        return None
    v = value.strip().upper()
    return v if _REF_RE.match(v) else None


def _stamp_affiliate(subscription_id: str, code: str, source: str) -> bool:
    """Leimaa affiliate-koodi tilauksen metadataan (pysyvä, ei vanhene).

    Tilauksen metadata säilyy vaikka alennus irtoaa, joten uusiutumislaskut
    kuuluvat leimattuun tilaukseen ja payout on yksi kysely eikä käsintäsmäys.

    Fail-soft tarkoituksella: leiman epäonnistuminen EI saa kaataa
    fulfillmentia. Asiakas on jo maksanut ja premium on aktivoitava; puuttuva
    leima on korjattavissa jälkikäteen ensimmäiseltä laskulta, menetetty
    premium ei ole.
    """
    try:
        stripe.Subscription.modify(
            subscription_id,
            metadata={"affiliate": code, "affiliate_source": source})
        print(f"[affiliate] leimattu {subscription_id} <- {code} ({source})")
        return True
    except Exception as e:
        print(f"[affiliate] leimaus EPÄONNISTUI {subscription_id} <- {code}: {e}")
        return False


def _provision_supabase_user(email: str) -> Optional[str]:
    """Luo (tai löydä) Supabase-käyttäjä emaililla — #101 account-after-payment.

    Guest-checkoutissa maksu tapahtuu ENNEN tiliä: Stripe kerää emailin,
    webhook kutsuu tätä. Luonti admin-API:lla email_confirm=True (maksettu
    email = riittävä todiste omistuksesta tässä kontekstissa; ilman tätä
    magic-link-verify kaatuisi vahvistamattomaan emailiin). Jos email on jo
    rekisteröity, id haetaan generate_linkillä (EI lähetä mailia) →
    entitlement laskeutuu olemassa olevalle tilille.
    """
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY or not email:
        print("[Supabase] provision: missing config or email")
        return None
    headers = {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
    }
    try:
        resp = requests.post(
            f"{SUPABASE_URL}/auth/v1/admin/users",
            json={"email": email, "email_confirm": True},
            headers=headers, timeout=10,
        )
        if resp.status_code in (200, 201):
            uid = (resp.json() or {}).get("id")
            print(f"[Supabase] provisioned NEW user for guest checkout id={uid}")
            return uid or None
        # 422/400 = email jo rekisteröity → hae id generate_linkillä
        # (admin-endpoint, palauttaa user-objektin, EI lähetä sähköpostia)
        resp2 = requests.post(
            f"{SUPABASE_URL}/auth/v1/admin/generate_link",
            json={"type": "magiclink", "email": email},
            headers=headers, timeout=10,
        )
        if resp2.status_code == 200:
            data = resp2.json() or {}
            uid = (data.get("user") or {}).get("id") or data.get("id")
            print(f"[Supabase] guest checkout matched EXISTING user id={uid}")
            return uid or None
        print(f"[Supabase] provision FAILED create={resp.status_code} "
              f"lookup={resp2.status_code} body={resp2.text[:200]}")
        return None
    except Exception as e:
        print(f"[Supabase] provision EXCEPTION: {e}")
        return None


def _send_magic_link(email: str, redirect_to: str = "https://pro.goaliq.app") -> bool:
    """Lähetä kirjautumislinkki (magic link) Supabasen kautta — #101.

    /auth/v1/otp lähettää magic-link-mailin projektin SMTP:llä.
    create_user=False: käyttäjä on jo provisioitu (_provision_supabase_user).
    redirect_to:n pitää olla Supabase-auth-allowlistissa (GO-checklist).
    Epäonnistuminen EI kaada fulfillmentia — premium on jo aktivoitu,
    käyttäjä pääsee sisään myös LoginBoxin sign-in-link-polulla.
    """
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY or not email:
        return False
    try:
        resp = requests.post(
            f"{SUPABASE_URL}/auth/v1/otp?redirect_to={requests.utils.quote(redirect_to, safe='')}",
            json={"email": email, "create_user": False},
            headers={
                "apikey": SUPABASE_SERVICE_ROLE_KEY,
                "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
                "Content-Type": "application/json",
            },
            timeout=10,
        )
        ok = resp.status_code in (200, 204)
        print(f"[Supabase] magic link {'sent' if ok else 'FAILED'} "
              f"status={resp.status_code}"
              + ("" if ok else f" body={resp.text[:200]}"))
        return ok
    except Exception as e:
        print(f"[Supabase] magic link EXCEPTION: {e}")
        return False


def _bearer_from_request(request: Request) -> str:
    """`Authorization: Bearer <token>` -> token, muuten "" ."""
    auth = request.headers.get("authorization", "")
    return auth[7:].strip() if auth.lower().startswith("bearer ") else ""


def _verify_supabase_token(access_token: str) -> Optional[str]:
    """
    Vahvista Supabase-kayttajan access_token ja palauta hanen auth-id:nsa.

    Kutsuu Supabasen /auth/v1/user-endpointia kayttajan omalla tokenilla
    (service-role apikey + Bearer = kayttajan token). Supabase vahvistaa
    allekirjoituksen + voimassaolon ja palauttaa kayttajan. Palauttaa user_id:n
    tai None jos token on virheellinen/vanhentunut tai config puuttuu.
    """
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY or not access_token:
        return None
    try:
        resp = requests.get(
            f"{SUPABASE_URL}/auth/v1/user",
            headers={
                "apikey": SUPABASE_SERVICE_ROLE_KEY,
                "Authorization": f"Bearer {access_token}",
            },
            timeout=10,
        )
        if resp.status_code != 200:
            print(f"[delete-account] token verify failed status={resp.status_code}")
            return None
        user_id = (resp.json() or {}).get("id")
        return user_id or None
    except Exception as e:
        print(f"[delete-account] token verify EXCEPTION: {e}")
        return None


def _get_supabase_user(access_token: str) -> Optional[dict]:
    """Vahvista Supabase-token ja palauta {id, email} (QUEUE #14 web-checkout).

    Sama mekanismi kuin _verify_supabase_token, mutta palauttaa myös emailin
    (Stripe-kuitti). None jos token virheellinen/vanhentunut tai config puuttuu.
    """
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY or not access_token:
        return None
    try:
        resp = requests.get(
            f"{SUPABASE_URL}/auth/v1/user",
            headers={
                "apikey": SUPABASE_SERVICE_ROLE_KEY,
                "Authorization": f"Bearer {access_token}",
            },
            timeout=10,
        )
        if resp.status_code != 200:
            print(f"[web-checkout] token verify failed status={resp.status_code}")
            return None
        data = resp.json() or {}
        if not data.get("id"):
            return None
        return {"id": data["id"], "email": data.get("email")}
    except Exception as e:
        print(f"[web-checkout] token verify EXCEPTION: {e}")
        return None


def _delete_supabase_user(user_id: str) -> bool:
    """
    Poista kayttaja + hanen datansa pysyvasti (5.1.1(v) in-app account deletion).

    Jarjestys: predictions-rivit -> profiles-rivi -> auth.users-rivi
    (admin-API). Service-role-key ohittaa RLS:n. Palauttaa True jos auth-user
    saatiin poistettua (datapoistot logataan mutta eivat blokkaa).
    """
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        print(f"[delete-account] missing env vars, cannot delete user_id={user_id}")
        return False

    headers = {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
    }
    # 1) Kayttajan ennusteet (best-effort — ei blokkaa auth-poistoa).
    try:
        requests.delete(
            f"{SUPABASE_URL}/rest/v1/predictions?user_id=eq.{user_id}",
            headers=headers, timeout=10,
        )
    except Exception as e:
        print(f"[delete-account] predictions delete EXCEPTION user_id={user_id}: {e}")
    # 2) Profiili.
    try:
        requests.delete(
            f"{SUPABASE_URL}/rest/v1/profiles?id=eq.{user_id}",
            headers=headers, timeout=10,
        )
    except Exception as e:
        print(f"[delete-account] profile delete EXCEPTION user_id={user_id}: {e}")
    # 3) Auth-kayttaja (admin-API) — talla poisto on lopullinen.
    try:
        resp = requests.delete(
            f"{SUPABASE_URL}/auth/v1/admin/users/{user_id}",
            headers=headers, timeout=10,
        )
        if resp.status_code in (200, 204):
            print(f"[delete-account] deleted user_id={user_id}")
            return True
        print(
            f"[delete-account] auth delete FAILED status={resp.status_code} "
            f"body={resp.text[:200]} user_id={user_id}"
        )
        return False
    except Exception as e:
        print(f"[delete-account] auth delete EXCEPTION user_id={user_id}: {e}")
        return False


# ---------------------------------------------------------------------------
# FastAPI -instanssi
# ---------------------------------------------------------------------------
app = FastAPI(
    title="GoalIQ API",
    description="Football match predictions from a statistical model (Dixon-Coles)",
    version="0.1.0",
)

# CORS (#109): eksplisiittinen origin-lista wildcardin tilalle.
# Selain-originit enumeroitu koodista: pro.goaliq.app (SPA, config.ts) +
# goaliq.app (index-countdown- ja career-fetchit; fpl/predictions eivät
# fetchaa). Mobiili on natiivi client (ei Origin-headeria → CORS ei koske),
# Stripe/RC-webhookit server-to-server → eivät koske. localhost = SPA-dev
# (vite dev 5173 / preview 4173) joka osoittaa prod-APIin oletuksena.
# Samalla poistui allow_credentials+wildcard-epäkoherenssi (selain ei
# koskaan lähettänyt credentiaaleja "*":lle). *.pages.dev-previewt EIVÄT
# listalla — lisää tarvittaessa tähän eksplisiittisesti.
CORS_ALLOWED_ORIGINS = [
    "https://goaliq.app",
    "https://www.goaliq.app",
    "https://pro.goaliq.app",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:4173",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # 28.7: PAKOLLINEN custom-headereille. Selain EI anna JS:n lukea muuta kuin
    # CORS-safelisted-headereita cross-originissa, vaikka palvelin lähettäisi ne.
    # pro.goaliq.app -> api.goaliq.app on cross-origin, joten ilman tätä
    # X-GoalIQ-Error-Code oli olemassa vastauksessa mutta näkymätön klientille,
    # ja PI-16:n haara jäi laukeamatta HILJAA: käyttäjä näki yhä punaisen
    # virhelaatikon. Todettu katsomalla livesivua, ei koodia lukemalla.
    expose_headers=["X-GoalIQ-Error-Code"],
)

# Edge-sprint: uudet fantasy-endpointit (chip-ev, plan-chains, league, h2h,
# edge, xp.csv) omassa moduulissa — main.py:n olemassa olevat polut eivat
# muutu. Importti tassa (ei tiedoston alussa) jotta app + CORS ovat valmiit.
from api.fantasy_edge import router as _fantasy_edge_router  # noqa: E402
app.include_router(_fantasy_edge_router)


# ---------------------------------------------------------------------------
# Mallin välimuisti — sovitetaan kerran liiga+kausi-yhdistelmälle
# ---------------------------------------------------------------------------
_MODEL_CACHE: dict[tuple, DixonColesModel] = {}
# #69: turnauskoodia (WC/EC) sisältävät avaimet tarvitsevat refit:n kun
# uusi turnausdata on saatavilla. Tallennetaan fit-aikaleima ja refit:taan
# jos loaderin turnausdataa on haettu sen jälkeen uudelleen.
_MODEL_FITTED_AT: dict[tuple, float] = {}
# #72: stale-while-revalidate. Kun #69:n TTL umpeutuu, palautetaan vanha
# malli ja triggataan tausta-refit. _REFIT_IN_PROGRESS estaa tuplarefit
# samalle avaimelle. _MODEL_LOCK suojaa _MODEL_CACHE / _MODEL_FITTED_AT /
# _REFIT_IN_PROGRESS check-then-set -sekvenssit (warmup-thread,
# tausta-refit-thread ja pyyntö-säikeet ajaa rinnakkain).
_REFIT_IN_PROGRESS: set[tuple] = set()
_MODEL_LOCK = threading.Lock()

# #71: DataFrame-välimuisti — /api/predict kutsuu lataa_otteludata kahdesti
# per request (mallia varten + H2H/form-trend-laskuun). Understat-loaderin
# read_schedule() voi tehdä HTTP-kutsuja → PL:n /api/predict warm-aika oli
# 44 s vaikka malli oli cachetettu. Cache ohitetaan turnauskaudille jotta
# #69:n TTL-logiikka pysyy ehjänä (loader hoitaa turnausten freshnessin).
# Lukko: warmup-thread + pyyntö-säikeet voivat ajaa rinnakkain → double-
# checked locking estää tuplakirjoituksen pitämättä lukkoa hidastavan
# lataa_otteludata-kutsun ajan.
_DATA_CACHE: dict[tuple, pd.DataFrame] = {}
_DATA_CACHE_LOCK = threading.Lock()


def _lataa_otteludata_cached(liigat, kaudet) -> pd.DataFrame:
    """Muistissa-oleva DataFrame-cache lataa_otteludata-kutsuille.

    Domestic-liigoille pysyvä prosessin keston ajan (data ei muutu). Turnaus-
    liigoille (WC/EC live-kaudella) ohittaa cachen ja kutsuu loaderia joka
    soveltaa #69:n TTL-logiikkaa.
    """
    if _liigat_sisaltavat_turnauksen(tuple(liigat)):
        return lataa_otteludata(list(liigat), list(kaudet))
    key = (tuple(liigat), tuple(kaudet))
    with _DATA_CACHE_LOCK:
        df = _DATA_CACHE.get(key)
    if df is not None:
        return df
    # Cache miss → lataa lukon ulkopuolella (voi viedä sekunteja).
    new_df = lataa_otteludata(list(liigat), list(kaudet))
    with _DATA_CACHE_LOCK:
        existing = _DATA_CACHE.get(key)
        if existing is not None:
            # Toinen säie ehti välissä — palautetaan sama instance kaikille.
            return existing
        _DATA_CACHE[key] = new_df
        return new_df


# ---------------------------------------------------------------------------
# Lämmitys käynnistyksessä — sovittaa kaikkien tarjottujen liigojen mallit
# taustalla jotta ensimmäinen /api/teams + /api/predict on nopea.
#
# Aiemmin warmup koski vain PL:ää → muut 5 liigaa (PD, BL1, SA, FL1, CL)
# fitattiin lazy ensimmäisellä /api/teams-kutsulla → mobiili näki "server took
# too long" -timeoutin (#71). Sarjallinen jotta CPU ei ylikuormiu ja
# football-data.org rate-limit (6.5 s väli) säilyy alle 10/min rajan.
# #72: WC lisattiin viimeiseksi jotta launch-paivan domestic-liigaliikenne
# saa CPU:n ensin. WC-fit on 30 s -luokkaa, joten sen jattaminen lazyksi
# blokkasi mobiili-WC-tabin ensimmaisen klikkauksen.
# ---------------------------------------------------------------------------
# Kausi-ikkuna resolvoidaan dynaamisesti (config.current_season_pair):
# elo-touko-sääntö → 1.8. alkaen warmup + endpoint-defaultit siirtyvät uuteen
# kauteen ilman koodimuutosta. Prosessin käynnistyshetki määrää warmup-avaimet
# (Render restarttaa deployssa); per-pyyntö-defaultit resolvoidaan pyynnössä.
_DOMESTIC_SEASONS: tuple[str, ...] = tuple(config.current_season_pair())

WARMUP_LEAGUES: list[tuple[tuple[str, ...], tuple[str, ...]]] = [
    (("ENG-Premier League",),    _DOMESTIC_SEASONS),
    (("ESP-La Liga-FD",),        _DOMESTIC_SEASONS),
    (("GER-Bundesliga-FD",),     _DOMESTIC_SEASONS),
    (("ITA-Serie A-FD",),        _DOMESTIC_SEASONS),
    (("FRA-Ligue 1-FD",),        _DOMESTIC_SEASONS),
    (("INT-Champions League",),  _DOMESTIC_SEASONS),
    # 28.7: neljä puuttuvaa. Villen havainto: "hitaus ei oo korjaantunu kun
    # vaihtaa leaguee predict any matchissa". Syy oli tämä lista, ei klientti.
    # Webin valitsin tarjoaa 10 liigaa (sama kuratoitu lista kuin mobiililla),
    # mutta warmup kattoi vain 6 → nämä neljä fitattiin lazy ensimmäisellä
    # /api/teams-kutsulla ja käyttäjä odotti. Mitattu Primeira Liga 6,5 s.
    #
    # Sama vika kuin #71 (silloin warmup kattoi vain PL:n), joten korjaus on
    # sama: lisää lista tänne kun valitsin kasvaa. Sarjallinen ajo säilyy,
    # joten CPU ei ylikuormiu eikä FD:n rate-limit rikkoudu.
    (("ENG-Championship",),      _DOMESTIC_SEASONS),
    (("NED-Eredivisie",),        _DOMESTIC_SEASONS),
    (("POR-Primeira Liga",),     _DOMESTIC_SEASONS),
    (("BRA-Serie A",),           _DOMESTIC_SEASONS),
]

# #79: WC-mallin fit-parametrit (kanoninen lähde = international_results).
# PredictWCRequest käyttää näitä defaultteina (vain dokumentaatio/compat — serving
# lataa esirakennetun JSON-mallin, ei fittaa näillä ajossa).
from src.data.international_results import WC_FIT_DECAY, WC_FIT_BAYES


# Kuinka usein warmup-säie tarkistaa onko kausi-ikkuna vaihtunut alta.
# 30 min: flippi tapahtuu vuorokauden vaihteessa, joten pahin viive on 30 min
# yöllä — mutta ilman tätä viive on "seuraavaan restarttiin asti", joka voi
# olla päiviä.
_SEASON_RECHECK_SEC = 1800


@app.on_event("startup")
def _warmup_default_models():
    def _fit_seasons(kaudet: tuple[str, ...]) -> None:
        for (liigat, _vanha) in WARMUP_LEAGUES:
            try:
                t0 = time.time()
                _saa_malli(liigat, kaudet)
                print(f"[Warmup] {liigat[0]} {kaudet} ready in {time.time()-t0:.1f}s")
            except Exception as e:
                print(f"[Warmup] {liigat[0]} {kaudet} failed: {type(e).__name__}: {e}")

    # FD-cachen lammitin omassa saikeessaan: se ei saa viivyttaa
    # mallien warmupia eika toisin pain. Daemon -> ei esta sammutusta.
    threading.Thread(target=_fd_warm_loop, daemon=True,
                     name="fd-warm").start()
    print("[fd-warm] lammitin kaynnistetty")

    def _fit_all():
        warmed = tuple(config.current_season_pair())
        _fit_seasons(warmed)
        # #79: WC-malli on ESIRAKENNETTU (data/wc_model.json) — Render Starter ei
        # jaksa fitata "any"-mallia ajossa. Esiladataan lru-cacheen (instant);
        # ei fittiä, ei livelock-riskiä.
        try:
            from src.data.international_results import load_wc_model
            t0 = time.time()
            dc = load_wc_model()
            print(f"[Warmup] WC model (prebuilt) loaded: {len(dc.teams_)} teams "
                  f"in {time.time()-t0:.2f}s")
        except Exception as e:
            print(f"[Warmup] WC prebuilt model load failed: {type(e).__name__}: {e}")

        # --------------------------------------------------------------
        # KAUSIFLIPPI-VAHTI (27.7)
        #
        # Ongelma jonka tämä korjaa: `_DOMESTIC_SEASONS` lasketaan MODUULIN
        # latauksessa eli prosessin käynnistyshetkellä, mutta klientit
        # resolvoivat kauden joka pyynnössä (mobiili lib/season.ts, sääntö
        # kuukausi >= 8). Elokuun 1. päivänä appi alkaa lähettää uutta paria,
        # ja jos prosessi on käynnistetty ennen sitä, warmup on lämmittänyt
        # VANHAN parin → jokainen ensimmäinen predict per liiga maksaa täyden
        # synkronisen fitin.
        #
        # Hinta mitattu 27.7. tuotantoa vasten: lämmittämätön kausipari =
        # 63 s, lämmitetty = 0,1 s. Appin predict-timeout on 90 s, eli se
        # mahtuisi juuri ja juuri — mutta kuudella liigalla se olisi surkea
        # 1.8., ja aiemmin tämä oli kiinni siitä restarttaako Render
        # sattumalta oikeaan aikaan (päivittäinen deploy ajaa vain jos
        # data/** muuttui 24 h:ssa → ei taattu).
        #
        # Vahti EI fittaa mitään turhaan: se herää, vertaa paria, ja nukkuu
        # takaisin jos mikään ei muuttunut.
        # --------------------------------------------------------------
        while True:
            time.sleep(_SEASON_RECHECK_SEC)
            try:
                nyt = tuple(config.current_season_pair())
            except Exception as e:
                print(f"[Warmup] kausitarkistus epaonnistui: {type(e).__name__}: {e}")
                continue
            if nyt == warmed:
                continue
            print(f"[Warmup] KAUSIFLIPPI {warmed} -> {nyt}; lammitetaan uusi pari")
            _fit_seasons(nyt)
            warmed = nyt

    threading.Thread(target=_fit_all, daemon=True).start()


def _liigat_sisaltavat_turnauksen(liigat: tuple[str, ...]) -> bool:
    """#69: True jos jokin liiga mappautuu live-turnauskoodiin (WC/EC)."""
    from src.data.football_data_org import COMPETITION_CODES, _LIVE_TOURNAMENT_CODES
    for liiga in liigat:
        if COMPETITION_CODES.get(liiga) in _LIVE_TOURNAMENT_CODES:
            return True
    return False


def _malli_vanhentunut(key: tuple, liigat: tuple[str, ...]) -> bool:
    """
    #69: invalidoi cached DC-malli jos avaimessa on turnauskoodi (WC/EC)
    ja malli on TTL:n verran vanha. Refit kutsuu loaderia → loader-TTL
    laukeaa rinnakkain → API-haku tuoreelle datalle.

    Domestic-only avaimille palauttaa aina False → /api/predict ei saa
    lisälatenssia kuin yhden cheap dict-lookupin verran.
    """
    if not _liigat_sisaltavat_turnauksen(liigat):
        return False
    from src.data.football_data_org import TOURNAMENT_TTL_SEC
    fitted_at = _MODEL_FITTED_AT.get(key, 0.0)
    return (time.time() - fitted_at) >= TOURNAMENT_TTL_SEC


def _fit_malli(liigat: tuple[str, ...], kaudet: tuple[str, ...],
               decay: float, bayes_shrinkage: float,
               per_team_home_adv: bool,
               shrink_defence_to_mean: bool) -> DixonColesModel:
    """Sovita DixonColesModel annetuilla parametreilla. Heittaa HTTPException."""
    df = _lataa_otteludata_cached(list(liigat), list(kaudet))
    if df.empty:
        raise HTTPException(
            status_code=404,
            detail=f"No match data found for leagues={liigat}, seasons={kaudet}",
        )
    # #79: kansainvälinen WC-data tuo "tournament"-sarakkeen → kilpailu-paino.
    # Domestic-datassa saraketta ei ole → fit_kwargs tyhjä → bittitarkasti ennallaan.
    fit_kwargs: dict = {}
    if "tournament" in df.columns:
        from src.data.international_results import (
            COMPETITION_WEIGHTS,
            DEFAULT_COMPETITION_WEIGHT,
        )
        fit_kwargs = dict(
            competition_col="tournament",
            competition_weights=COMPETITION_WEIGHTS,
            default_competition_weight=DEFAULT_COMPETITION_WEIGHT,
        )
    try:
        dc = DixonColesModel(per_team_home_adv=per_team_home_adv).fit(
            df,
            home_team_col="home_team", away_team_col="away_team",
            home_goals_col="home_score", away_goals_col="away_score",
            decay=decay, date_col="date",
            l2_attack_defence=bayes_shrinkage,
            shrink_defence_to_mean=shrink_defence_to_mean,
            # 17.8 (Villen GO): xG-painotettu likelihood. Arvo tulee configista,
            # jotta /api/predict ja FPL-putki eivat voi ajautua erilleen.
            # Inertti liigoille joilla ei ole xG-dataa (guard fitissa).
            home_xg_col=config.DIXON_COLES_XG_COLS[0],
            away_xg_col=config.DIXON_COLES_XG_COLS[1],
            xg_weight=config.DIXON_COLES_XG_WEIGHT,
            **fit_kwargs,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Model fit failed: {e}")

    # 27.7 GW1-VALMIUS: täydennä kauden nousijat joilla ei ole yhtään ottelua.
    #
    # Ilman tätä /api/predict palauttaa 404:n Coventrylle, Hullille ja
    # Ipswichille 1.8. alkaen (treeni-ikkuna 2526+2627, Understatissa ei
    # 2627-dataa) → GW1:ssä 21.8. jopa 3/10 ottelua per kierros ilman
    # ennustetta, juuri liikennepiikin hetkellä.
    #
    # FITIN JÄLKEEN tarkoituksella: injektio lisää avaimia vain joukkueille
    # joita mallissa ei ole eikä kosketa yhdenkään olemassa olevan joukkueen
    # estimaattia → domestic-regressio pysyy bittitarkkana. Sama jaettu
    # funktio kuin FPL-putkessa (build_fpl_phase0 / build_fpl_cs_fdr), joten
    # /api/predict ja CS%/FDR ovat samaa mieltä nousijoista — aiemmin logiikka
    # oli kopioituna kahteen generaattoriin eikä predictissä lainkaan.
    try:
        from src.models.promoted_baseline import taydenna_nousijat
        info = taydenna_nousijat(dc, liigat, kaudet)
        if info.get("applied_to"):
            print(f"[Promoted] baseline -> {info['applied_to']} "
                  f"(att={info.get('attack')}, def={info.get('defence')})")
    except Exception as e:
        # Ei saa KOSKAAN kaataa fittiä: ilman täydennystä malli on täsmälleen
        # se mikä se oli ennen tätä muutosta.
        print(f"[Promoted] baseline ohitettu: {type(e).__name__}: {e}")

    return dc


def _taustarefit(key: tuple, liigat: tuple[str, ...], kaudet: tuple[str, ...],
                  decay: float, bayes_shrinkage: float,
                  per_team_home_adv: bool,
                  shrink_defence_to_mean: bool) -> None:
    """#72: refit:taa mallin taustasaikeessa, vapauttaa _REFIT_IN_PROGRESS-lipun.

    Pyynnot tarjoillaan vanhalla cachetetulla mallilla kunnes uusi valmis.
    Virheet logataan mutta ei propagoida — pyyntotie pysyy ehjana ja
    seuraava TTL-tarkistus yrittaa uudelleen.
    """
    try:
        dc = _fit_malli(liigat, kaudet, decay, bayes_shrinkage,
                        per_team_home_adv, shrink_defence_to_mean)
        with _MODEL_LOCK:
            _MODEL_CACHE[key] = dc
            _MODEL_FITTED_AT[key] = time.time()
        print(f"[Refit] {liigat[0]} ready")
    except Exception as e:
        print(f"[Refit] {liigat[0]} failed: {type(e).__name__}: {e}")
    finally:
        with _MODEL_LOCK:
            _REFIT_IN_PROGRESS.discard(key)


def _saa_malli(liigat: tuple[str, ...], kaudet: tuple[str, ...],
               decay: float = 0.0035, bayes_shrinkage: float = 2.0,
               per_team_home_adv: bool = True,
               shrink_defence_to_mean: bool = False) -> DixonColesModel:
    """
    Hae cached DC-malli tai sovita uusi jos ei välimuistissa.

    #72: turnausmalleille (WC/EC) #69:n TTL-tarkistus on stale-while-
    revalidate — vanhentunut malli palautetaan heti, ja tausta-saie
    refit:taa uudella datalla. Yksikaan pyynto ei blokkaudu 30 s fitin
    taakse. Cold-cold (ei cachea ollenkaan) sovittaa synkronisesti —
    warmup-saie estaa taman kaytannossa.

    per_team_home_adv
        False = älä sovita joukkuekohtaisia kotietu-parametreja (n kpl).
        WC-malli (`/api/predict-wc`) nollaa kotiedun joka tapauksessa, joten
        näiden sovittaminen on n hukkaparametria pienelle WC-datalle (#61).
    shrink_defence_to_mean
        True = shrinkkaa puolustuksen joukkue-eroja, ei maalitasoa (#61).
        Estää bayes_shrinkagea deflatoimasta ennustettuja maaleja.
    """
    key = (liigat, kaudet, round(decay, 4), round(bayes_shrinkage, 2),
           per_team_home_adv, shrink_defence_to_mean)

    # Lukon alla: peek cache + arvioi tuoreus. _malli_vanhentunut lukee
    # _MODEL_FITTED_AT:ia, joten se kuuluu kriittiseen alueeseen.
    with _MODEL_LOCK:
        cached = _MODEL_CACHE.get(key)
        stale = cached is not None and _malli_vanhentunut(key, liigat)

    if cached is not None and not stale:
        return cached

    if cached is not None and stale:
        # Stale-while-revalidate: kaynnista tausta-refit vain jos ei jo kaynnissa.
        with _MODEL_LOCK:
            start_thread = key not in _REFIT_IN_PROGRESS
            if start_thread:
                _REFIT_IN_PROGRESS.add(key)
        if start_thread:
            threading.Thread(
                target=_taustarefit,
                args=(key, liigat, kaudet, decay, bayes_shrinkage,
                      per_team_home_adv, shrink_defence_to_mean),
                daemon=True,
            ).start()
        return cached

    # Cold-cold: ei cachea ollenkaan -> synk fit. Warmup hoitaa taman
    # kaytannossa Renderissa; lazy-tie on jaljella vain epatavallisille
    # liiga+kausi-yhdistelmille (esim. /api/team -kutsuille muille kuin
    # warmup-listalle).
    dc = _fit_malli(liigat, kaudet, decay, bayes_shrinkage,
                    per_team_home_adv, shrink_defence_to_mean)
    with _MODEL_LOCK:
        _MODEL_CACHE[key] = dc
        _MODEL_FITTED_AT[key] = time.time()
    return dc


# ---------------------------------------------------------------------------
# Pydantic-mallit (request/response -tyypit)
# ---------------------------------------------------------------------------
class PredictionRequest(BaseModel):
    """Prediction request."""
    home_team: str = Field(..., description="Home team name", examples=["Arsenal"])
    away_team: str = Field(..., description="Away team name", examples=["Liverpool"])
    leagues: list[str] = Field(
        default=["ENG-Premier League"],
        description="Leagues to use for training the model",
    )
    seasons: list[str] = Field(
        default_factory=config.current_season_pair,
        description="Seasons (YYMM format). Default: edellinen + aktiivinen kausi.",
    )
    decay: float = Field(default=0.0035, ge=0.0, le=0.020,
                          description="Time-decay weight (0=no decay)")
    bayes_shrinkage: float = Field(default=2.0, ge=0.0, le=10.0,
                                    description="Bayes shrinkage strength")
    # Manuaaliset säädöt (kaikki valinnaisia)
    home_injury_pct: float = Field(default=0.0, ge=-30.0, le=0.0)
    away_injury_pct: float = Field(default=0.0, ge=-30.0, le=0.0)
    home_motivation_pct: float = Field(default=0.0, ge=-15.0, le=15.0)
    away_motivation_pct: float = Field(default=0.0, ge=-15.0, le=15.0)
    is_derby: bool = Field(default=False)
    # T6: todennakoisimpien tulosten maara (5 free, 10 premium)
    top_n: int = Field(default=5, ge=1, le=10,
                       description="Number of most-likely scorelines to return")


class PredictWCRequest(BaseModel):
    """World Cup prediction request: international sides, not clubs.

    Seasons are given as four digit years, for example ["2018", "2022", "2026"].
    """
    # Sisainen huomio (ei vuoda openapi.jsoniin, koska tama on kommentti eika
    # docstring): nelinumeroiset vuodet normalisoidaan sisaisesti kaksinumeroisiksi
    # loader-yhteensopivuuden vuoksi. football_data_org._kausi_to_year tulkitsee
    # "2018" -> "2020", joten ne on muunnettava "18", "22", "26" ennen lahetysta.
    # Datalahde: football-data.org / ML Pack Light -tier (avaa "10 seasons of
    # history" -> WC 2018 ja 2022 FINISHED-ottelut).
    home_team: str = Field(..., description="Home team (e.g., 'Argentina')",
                            examples=["Argentina"])
    away_team: str = Field(..., description="Away team (e.g., 'France')",
                            examples=["France"])
    leagues: list[str] = Field(
        default=["INT-World Cup"],
        description="Leave as the default. This endpoint supports only this code.",
    )
    seasons: list[str] = Field(
        default=["2018", "2022", "2026"],
        description="WC-kaudet (4-digit years).",
    )
    # WC-otteluissa ei perinteistä kotietua. decay=0 (#61): WC-dataa on vain
    # ~128 ottelua kahdelta turnaukselta — aikapainotus pudottaisi efektiivisen
    # otoskoon ~75:een (WC 2018 paino ~0.2), mikä pahentaa yliparametrisointia.
    # decay=0 → ESS 128, eikä WC 2018:n dataa heitetä hukkaan.
    decay: float = Field(default=WC_FIT_DECAY, ge=0.0, le=0.020)
    # #79: WC-malli treenataan nyt tuoreesta maaotteludatasta (martj42, ~2000
    # ottelua) eikä vain WC 2018/22 (~128) → decay/shrinkage virittää vaiheen 5
    # backtest. Arvot tulevat WC_FIT_DECAY/WC_FIT_BAYES-vakioista (sama kuin
    # warmup → cache-avain täsmää).
    bayes_shrinkage: float = Field(default=WC_FIT_BAYES, ge=0.0, le=10.0)
    # Manuaaliset säädöt — samat kuin /api/predict
    home_injury_pct: float = Field(default=0.0, ge=-30.0, le=0.0)
    away_injury_pct: float = Field(default=0.0, ge=-30.0, le=0.0)
    home_motivation_pct: float = Field(default=0.0, ge=-15.0, le=15.0)
    away_motivation_pct: float = Field(default=0.0, ge=-15.0, le=15.0)
    is_derby: bool = Field(default=False)


class PredictionResponse(BaseModel):
    """Ennustevastaus 1X2, O/U 2.5, BTTS."""
    home_team: str
    away_team: str
    expected_goals_home: float
    expected_goals_away: float
    p_home_win: float
    p_draw: float
    p_away_win: float
    fair_odds_home: float
    fair_odds_draw: float
    fair_odds_away: float
    p_over_2_5: float
    p_under_2_5: float
    p_btts_yes: float
    p_btts_no: float
    top_scores: list[dict]  # [{score: "2-1", probability: 0.087}, ...]
    # T5: viimeiset 5 keskinaista kohtaamista (vain /api/predict — /api/predict-wc
    # tayttaa kentan tyhjana koska WC-otteluissa parit harvoin toistuvat)
    h2h: list[dict] = Field(default_factory=list)
    # T7: premium-visualisoinnit (vain /api/predict). h2h_summary = W/D/L-jakauma
    # kaikista ladatun kausi-ikkunan keskinaisista kohtaamisista. form_trend =
    # kummankin joukkueen viimeisimmat ottelut momentum-kayraa varten.
    h2h_summary: dict = Field(default_factory=dict)
    form_trend: dict = Field(default_factory=dict)
    # 9.8.2026: luokitukset sovitetaan TULOKSIIN eivatka nae siirtoikkunaa
    # (aikavaimennus half-life ~198 pv -> GW6:ssa uusi kausi on 25 % fitin
    # painosta). Suora korjaus yritettiin ja se ei validoitunut, joten mallia
    # ei saadeta — sen sijaan kerrotaan milloin luku nojaa vanhentuneeseen
    # tietoon. {"home": {...}, "away": {...}} tai tyhja jos dataa ei ole.
    data_confidence: dict = Field(default_factory=dict)


_TEAM_CONFIDENCE_UNSET = object()
_team_confidence_cache: object = _TEAM_CONFIDENCE_UNSET


def _load_team_confidence() -> dict[str, dict]:
    """model_team -> luottamustiedot. Luetaan kerran prosessin elinaikana.

    Puuttuva tiedosto ei ole virhe: kentta jaa tyhjaksi ja UI ei nayta mitaan.
    Fail-safe on tarkoituksellinen — lippu on lisatieto, ei ehto vastaukselle.
    """
    global _team_confidence_cache
    if _team_confidence_cache is _TEAM_CONFIDENCE_UNSET:
        try:
            doc = json.loads(
                (PROJECT_ROOT / "data" / "team_confidence.json")
                .read_text(encoding="utf-8"))
            _team_confidence_cache = {t["model_team"]: t for t in doc["teams"]}
        except Exception:
            _team_confidence_cache = {}
    return _team_confidence_cache  # type: ignore[return-value]


def _data_confidence(home: str, away: str) -> dict:
    """Kerro kummankin joukkueen osalta milloin luokitus nojaa vanhaan tietoon."""
    conf = _load_team_confidence()
    out = {}
    for role, team in (("home", home), ("away", away)):
        t = conf.get(team)
        if not t:
            continue
        out[role] = {
            "team": team,
            "minutes_churn_pct": t.get("minutes_churn_pct"),
            "flag": t.get("flag"),
            "note": t.get("note"),
        }
    return out


class TeamsResponse(BaseModel):
    leagues: list[str]
    seasons: list[str]
    teams: list[str]
    n_matches: int


# ---------------------------------------------------------------------------
# ENDPOINT: tervehdys
# ---------------------------------------------------------------------------
@app.get("/", description="Health check. Returns the commit that is actually running, so you can tell which build is live.")
def root():
    """Health check.

    🔴 `commit` LISATTIIN 15.8.2026 KOSKA "ONKO SE LIVENA" EI OLLUT
    VASTATTAVISSA. Deployasin maksupolun korjauksen ja huomasin etten voi
    todistaa mika commit ajossa on: deploy-hookin vihrea kertoo etta hook
    laukesi, ei etta uusi koodi vastaa. Sama vikaluokka kuin aiemmin kirjattu
    Renderin "Save only", joka nayttaa tallennetulta muttei ota mitaan
    kayttoon — ja sama korjaus: tee tila LUETTAVAKSI.

    `RENDER_GIT_COMMIT` tulee Renderin ymparistosta automaattisesti. Paikallisesti
    se puuttuu, jolloin kentta on null eika valehtele.
    """
    return {
        "service": "GoalIQ API",
        "version": "0.1.0",
        "commit": os.getenv("RENDER_GIT_COMMIT") or None,
        "status": "ok",
        "docs": "/docs",
        "endpoints": ["/api/leagues", "/api/teams", "/api/predict"],
    }


# ---------------------------------------------------------------------------
# ENDPOINT: saatavat liigat
# ---------------------------------------------------------------------------
@app.get("/api/leagues")
def list_leagues():
    """Lista kaikista liigoista joita malli tukee."""
    return {
        "top5_xg_leagues": [
            "ENG-Premier League", "ESP-La Liga", "GER-Bundesliga",
            "ITA-Serie A", "FRA-Ligue 1",
        ],
        "other_leagues": [
            "ENG-Championship", "ENG-League One", "ENG-League Two",
            "ESP-La Liga 2", "GER-2. Bundesliga", "ITA-Serie B", "FRA-Ligue 2",
            "POR-Primeira Liga", "NED-Eredivisie", "BEL-Pro League",
            "SCO-Premiership", "TUR-Super Lig",
            "FIN-Veikkausliiga", "SWE-Allsvenskan", "NOR-Eliteserien", "DEN-Superliga",
        ],
        "uefa_tournaments": [
            "INT-Champions League", "INT-Europa League", "INT-Conference League",
        ],
        "available_seasons": config.seasons_since("2122"),
        # Selitykset mobiilia varten — joukkueiden valinta liigan mukaan
        "league_presets": {
            "ENG-Premier League": {
                "label": "Premier League",
                "icon": "⚽",
                "seasons": config.current_season_pair(),
            },
        },
        "coming_soon": [
            {
                "code": "INT-World Cup",
                "label": "World Cup 2026",
                "icon": "🏆",
                "available_from": "2026-06-11",
                "note": "World Cup predictions launching when the tournament starts on June 11, 2026.",
            },
        ],
    }


# ---------------------------------------------------------------------------
# ENDPOINT: joukkueet liigassa
# ---------------------------------------------------------------------------
@app.get("/api/teams", response_model=TeamsResponse,
         description="Teams the model knows about for a given league and season.")
def list_teams(
    leagues: list[str] = Query(default=["ENG-Premier League"]),
    seasons: list[str] | None = Query(default=None,
        description="Default: edellinen + aktiivinen kausi (dynaaminen)"),
):
    """Lista joukkueista jotka mallissa esiintyvät annetussa liiga+kausi-yhdistelmässä."""
    if seasons is None:
        seasons = config.current_season_pair()
    # #79: WC-lista on 48 WC2026-maata — palautetaan suoraan ILMAN mallin fittausta
    # (Render Starter ei jaksa fitata "any"-mallia ajossa; malli on esirakennettu).
    if leagues == ["INT-World Cup"]:
        from src.data.wc_teams import WC2026_TEAMS
        return TeamsResponse(
            leagues=leagues, seasons=seasons,
            teams=sorted(WC2026_TEAMS), n_matches=len(WC2026_TEAMS),
        )
    dc = _saa_malli(tuple(leagues), tuple(seasons))
    n = 0
    try:
        # Mallin opetuksessa käytetty data — heuristinen arvio
        n = len(dc.attack)
    except Exception:
        pass
    # Kausiflippi 1.8.2026: treeni-ikkunassa on edellisen kauden pudonneet
    # (kokonainen kausi dataa), mutta valitsimen ei pidä tarjota niitä
    # aktiivisella kaudella. Suodatus koskee VAIN tätä listaa — /api/predict
    # hyväksyy pudonneet yhä (H2H, eksplisiittiset kausipyynnöt). Tuntematon
    # kausi → tyhjä joukko → käytös ennallaan (esim. seasons=['2425','2526']).
    from src.models.promoted_baseline import (
        nousijat_aktiiviselta_kaudelta,
        pudonneet_aktiiviselta_kaudelta,
    )
    pois = pudonneet_aktiiviselta_kaudelta(tuple(leagues), tuple(seasons))
    # Nousijat elävät fitin jälkeisessä injektiossa (taydenna_nousijat →
    # dc.attack), eivät treenidatan teams_-listassa — ilman unionia valitsin
    # näytti 17 joukkuetta 1.8. flipissä (havaittu tuotannosta). attack-vartio
    # takaa ettei listata joukkuetta jolle /api/predict palauttaisi 404.
    lisaa = nousijat_aktiiviselta_kaudelta(tuple(leagues), tuple(seasons))
    teams = sorted(
        {t for t in dc.teams_ if t not in pois}
        | {t for t in lisaa if t in dc.attack}
    )
    return TeamsResponse(
        leagues=leagues,
        seasons=seasons,
        teams=teams,
        n_matches=n,
    )


# ---------------------------------------------------------------------------
# ENDPOINT: liiga-taulukko (T3)
# ---------------------------------------------------------------------------

# Frontend lähettää PredictScreenistä "ENG-Premier League" (Understat-pohjaista
# data-koodia DC-mallin koulutukseen), mutta football-data.org -pohjaiset
# endpointit (/api/standings, /api/fixtures) tarvitsevat -FD-suffiksin
# saadakseen kilpailukoodin "PL". Muut liigat tulevat frontendiltä jo
# "X-Y-FD"-muodossa.
# 28.7: laajennettu kattamaan koko Top-5. Mitattu: /api/fixtures palautti 404:n
# La Ligalle, Bundesliigalle, Serie A:lle ja Ligue 1:lle, koska alias oli vain
# Valioliigalle. Mobiili ei paljastanut tata, koska se lahettaa -FD-koodit
# valmiiksi (lib/leagues.ts) - mutta /api/leagues palauttaa nimet ILMAN
# -FD-suffiksia, joten kuka tahansa uusi klientti joka kayttaa sita listaa
# osuu 404:aan. Korjaus tehdaan palvelimelle eika klientille, jotta kumpikaan
# pinta ei voi ajautua eroon: -FD-koodi kulkee taman lapi muuttumattomana.
FD_LEAGUE_ALIASES = {
    "ENG-Premier League": "ENG-Premier League-FD",
    "ESP-La Liga": "ESP-La Liga-FD",
    "GER-Bundesliga": "GER-Bundesliga-FD",
    "ITA-Serie A": "ITA-Serie A-FD",
    "FRA-Ligue 1": "FRA-Ligue 1-FD",
}


def _fd_standings_row(row: dict) -> dict:
    """FD:n table-rivi → API:n rivi. Jaettu domestic- ja WC-polun kesken —
    domestic-output pysyy bittitarkasti ennallaan (samat avaimet, sama järjestys)."""
    return {
        "position": row["position"],
        "team_name": row["team"]["name"],
        "team_short_name": row["team"].get("shortName"),
        "team_crest": row["team"].get("crest"),
        "played_games": row["playedGames"],
        "won": row["won"],
        "draw": row["draw"],
        "lost": row["lost"],
        "goals_for": row["goalsFor"],
        "goals_against": row["goalsAgainst"],
        "goal_difference": row["goalDifference"],
        "points": row["points"],
    }


# ---------------------------------------------------------------------------
# #49: /api/standings + /api/fixtures FD-kutsujen jaettu TTL-cache + 429-kovennus.
# Juurisyy: endpointit olivat cachettomia + ilman backoffia → liigatabien nopea
# selaus (12 + #25b:n 4 uutta liigaa) ylitti FD:n rate-limitin → käyttäjälle
# "Too many requests" (#32-auditin ennustama riski). Cache absorboi selauksen
# (koko käyttäjäkanta = max ~1 FD-kutsu / liiga / TTL-ikkuna), backoff
# self-healaa yksittäisen 429:n ja stale-fallback serveeraa viimeisimmän
# onnistuneen vastauksen mieluummin kuin virheen. Vastauksen MUOTO ei muutu
# (vain additiivinen "stale": true virhetilassa).
# ---------------------------------------------------------------------------
_FD_HTTP_CACHE: dict[str, tuple[float, dict]] = {}
_FD_HTTP_LOCKS: dict[str, threading.Lock] = {}
_FD_HTTP_LOCKS_GUARD = threading.Lock()
# 🔴 UUDELLEENSUUNNITELTU 16.8 ILLALLA, KOSKA EDELLINEN VERSIO OLI PAHEMPI
# KUIN VIKA JOTA SE KORJASI.
#
# Aamun versio lisasi rinnakkaisuusportin ja NELJA uusintaa jitteroidyllä
# backoffilla KAYTTAJAN PYYNNON POLKUUN. Se poisti 429-virheet, mutta muutti
# ne pitkaksi odotukseksi: mitattu 16.8 illalla `/api/standings` = **38,2 s**
# samaan aikaan kun `/api/teams` ja `/api/fixtures` olivat 0,12 s. Appin
# timeout on 60 s, joten kayttaja ei nahnyt virhetta vaan jumin. Villen sanat:
# "ei noi standingsit lataudu", "lagii koko paska". Molemmat olivat minun
# aiheuttamiani.
#
# PERIAATE JOSTA EI POIKETA: **kayttajan pyynto ei koskaan odota upstreamia.**
#   - tuore cache      -> palauta heti
#   - vanhentunut cache -> palauta HETI ja virkista TAUSTALLA
#   - ei cachea        -> yksi yritys lyhyella timeoutilla, EI uusintaketjua
# Uusinnat ja backoff kuuluvat taustasaikeeseen, eivat pyyntopolkuun.
_FD_HTTP_CACHE: dict[str, tuple[float, dict]] = {}
_FD_HTTP_LOCKS: dict[str, threading.Lock] = {}
_FD_HTTP_LOCKS_GUARD = threading.Lock()
_FD_BG_INFLIGHT: set[str] = set()
_FD_BG_GUARD = threading.Lock()

# Standings sai saman pitkan TTL:n kuin fixtures. 10 min tarkoitti etta
# jokainen avaus >10 min edellisesta oli kylma, ja liikennetta on ~65
# latausta/vrk. Sarjataulukko ei muutu 45 minuutissa merkittavasti, ja
# ottelupaivana taustavirkistys hoitaa tuoreuden ilman etta kukaan odottaa.
FD_HTTP_TTL_SEC = 2700          # 45 min
FD_FIXTURES_TTL_SEC = 2700      # 45 min

# Kayttajan pyynnon KOVA KATTO upstreamia kohti. Nama ovat pieniä
# tarkoituksella: jos FD ei vastaa taman sisalla, oikea vastaus on stale tai
# nopea virhe, ei odotus.
FD_FG_TIMEOUT_SEC = 6.0         # yksi HTTP-yritys
FD_FG_GATE_WAIT_SEC = 2.0       # portin odotus
FD_HTTP_MAX_CONCURRENT = 4
_FD_HTTP_GATE = threading.Semaphore(FD_HTTP_MAX_CONCURRENT)

# Taustavirkistys saa yrittaa pidempaan, koska kukaan ei odota sita.
FD_BG_TIMEOUT_SEC = 15.0
FD_BG_MAX_ATTEMPTS = 3
FD_HTTP_429_BACKOFF_SEC = 2.0

_FD_WAIT_HINT_RE = re.compile(r"[Ww]ait\s+(\d+)\s*second", re.ASCII)


def _fd_429_sleep_sec(body: str, attempt: int) -> float:
    """FD kertoo 429-bodyssa kauanko odottaa ("Wait 2 seconds"). Luetaan se
    vihje ja lisataan JITTER, jottei rinnakkaiset saikeet herää samalla
    sekunnilla. Kaytetaan VAIN taustasaikeessa."""
    hinted = 0.0
    m = _FD_WAIT_HINT_RE.search(body or "")
    if m:
        try:
            hinted = float(m.group(1))
        except ValueError:
            hinted = 0.0
    base = max(hinted, FD_HTTP_429_BACKOFF_SEC * (attempt + 1))
    return min(base, 20.0) + random.uniform(0.2, 1.5)


def _fd_fetch_once(url: str, api_key: str, timeout: float) -> dict | None:
    """Yksi HTTP-yritys. None = ei onnistunut (soittaja paattaa mita tekee)."""
    try:
        r = requests.get(url, headers={"X-Auth-Token": api_key}, timeout=timeout)
    except Exception as e:
        print(f"[fd] {type(e).__name__}: {e}")
        return None
    if r.status_code == 200:
        try:
            return r.json()
        except Exception:
            return None
    print(f"[fd] HTTP {r.status_code}: {r.text[:120]}")
    return None


def _fd_refresh_bg(url: str, api_key: str, key: str) -> None:
    """Taustavirkistys. Tassa saa uusia ja odottaa; kukaan ei ole jonossa."""
    try:
        for attempt in range(FD_BG_MAX_ATTEMPTS):
            if not _FD_HTTP_GATE.acquire(timeout=FD_BG_TIMEOUT_SEC):
                return
            try:
                data = _fd_fetch_once(url, api_key, FD_BG_TIMEOUT_SEC)
            finally:
                _FD_HTTP_GATE.release()
            if data is not None:
                _FD_HTTP_CACHE[key] = (time.time(), data)
                return
            if attempt < FD_BG_MAX_ATTEMPTS - 1:
                time.sleep(_fd_429_sleep_sec("", attempt))
    finally:
        with _FD_BG_GUARD:
            _FD_BG_INFLIGHT.discard(key)


def _fd_kick_refresh(url: str, api_key: str, key: str) -> None:
    """Kaynnistaa taustavirkistyksen kerran per avain."""
    with _FD_BG_GUARD:
        if key in _FD_BG_INFLIGHT:
            return
        _FD_BG_INFLIGHT.add(key)
    threading.Thread(target=_fd_refresh_bg, args=(url, api_key, key),
                     daemon=True).start()


def _fd_get_cached(url: str, api_key: str,
                   ttl_sec: int = FD_HTTP_TTL_SEC,
                   cache_key: str | None = None) -> tuple[dict, bool]:
    """Palauttaa (data, stale).

    `cache_key` erottaa cache-avaimen URLista, koska fixtures-URL sisaltaa
    kuluvan paivan paivamaarat ja vaihtuu joka vuorokausi. Ilman vakaata
    avainta stale-fallback ei voisi auttaa koskaan.
    """
    key = cache_key or url
    hit = _FD_HTTP_CACHE.get(key)

    if hit and time.time() - hit[0] < ttl_sec:
        return hit[1], False

    if hit:
        # 🔴 EI ODOTETA. Vanha taulukko heti + virkistys taustalla. Tama on
        # se rivi joka poistaa 38 sekunnin jumin.
        _fd_kick_refresh(url, api_key, key)
        return hit[1], True

    # Ei mitaan cachessa: yksi lyhyt yritys. EI uusintaketjua pyyntopolussa.
    if not _FD_HTTP_GATE.acquire(timeout=FD_FG_GATE_WAIT_SEC):
        raise HTTPException(
            status_code=503,
            detail="football-data.org busy, try again shortly")
    try:
        data = _fd_fetch_once(url, api_key, FD_FG_TIMEOUT_SEC)
    finally:
        _FD_HTTP_GATE.release()
    if data is not None:
        _FD_HTTP_CACHE[key] = (time.time(), data)
        return data, False

    # 🔴 Kylma polku ei saa jaada tyhjaksi. Ensimmainen versio tasta
    # korjauksesta poisti odotuksen mutta ei laittanut mitaan tilalle:
    # jos upstream oli juuri silla hetkella tukossa, kayttaja sai 503:n
    # eika mikaan yrittanyt uudelleen. Mitattu 16.8 iltana: Eredivisie,
    # Ligue 1 ja Primeira palauttivat 503:n peraakkain, koska niilla ei
    # ollut cache-riviä ja Renderin IP oli hetkellisesti rajoitettu.
    # Taustahaku tekee uusinnat, joten seuraava napautus onnistuu.
    _fd_kick_refresh(url, api_key, key)
    raise HTTPException(
        status_code=503,
        detail="football-data.org did not answer in time. Refreshing in the "
               "background, try again in a moment.")


# ---------------------------------------------------------------------------
# FD-CACHEN LAMMITIN (16.8 ilta)
#
# Kaikki kaytto nojaa nyt siihen etta cachessa on jotain: tuore osuma
# palautuu heti, vanhentunut palautuu heti ja virkistyy taustalla, ja VAIN
# tyhja avain voi tuottaa kayttajalle virheen. Lammitin tekee tyhjasta
# avaimesta harvinaisen.
#
# Tahdistus on tarkoituksellinen: FD:n ilmaistaso on pyyntoa/minuutissa, ja
# 16.8 mitattiin etta rajan ylitys estaa KOKO avaimen hetkeksi. Lammitin ei
# saa olla se joka aiheuttaa saman ongelman jota se korjaa.
FD_WARM_INTERVAL_SEC = 7.0      # kutsujen vali
FD_WARM_ROUND_SEC = 2400        # kierros ~40 min valein


def _fd_warm_targets() -> list[tuple[str, str, str]]:
    """(url, cache_key, nimi) kaikille pinnoille joita kayttaja avaa."""
    from src.data.football_data_org import (
        FIXTURE_STANDINGS_CODES, _LIVE_TOURNAMENT_CODES, _kausi_to_year)
    from datetime import date, timedelta

    season = config.current_season()
    out: list[tuple[str, str, str]] = []
    today = date.today()
    for league, code in FIXTURE_STANDINGS_CODES.items():
        if code in _LIVE_TOURNAMENT_CODES:
            url = f"https://api.football-data.org/v4/competitions/{code}/standings"
        else:
            url = (f"https://api.football-data.org/v4/competitions/{code}"
                   f"/standings?season={_kausi_to_year(season)}")
        out.append((url, f"standings:{code}:{season}", f"{league} standings"))
        for days in (7, 35):
            to = today + timedelta(days=days)
            out.append((
                f"https://api.football-data.org/v4/competitions/{code}/matches"
                f"?status=SCHEDULED,TIMED&dateFrom={today.isoformat()}"
                f"&dateTo={to.isoformat()}",
                f"fixtures:{code}:{days}", f"{league} fixtures {days}d"))
    return out


def _fd_warm_loop() -> None:
    from src.data.football_data_org import _api_key
    while True:
        key = _api_key()
        if not key:
            time.sleep(FD_WARM_ROUND_SEC)
            continue
        warmed = failed = 0
        for url, ck, name in _fd_warm_targets():
            hit = _FD_HTTP_CACHE.get(ck)
            # Vain tyhja tai selvasti vanhentunut haetaan: lammitin ei
            # kilpaile kayttajan kanssa samasta minuuttikiintiosta.
            if hit and time.time() - hit[0] < FD_HTTP_TTL_SEC * 0.8:
                continue
            data = _fd_fetch_once(url, key, FD_BG_TIMEOUT_SEC)
            if data is not None:
                _FD_HTTP_CACHE[ck] = (time.time(), data)
                warmed += 1
            else:
                failed += 1
            time.sleep(FD_WARM_INTERVAL_SEC)
        if warmed or failed:
            print(f"[fd-warm] {warmed} lammitetty, {failed} epaonnistui, "
                  f"{len(_FD_HTTP_CACHE)} avainta cachessa")
        time.sleep(FD_WARM_ROUND_SEC)


@app.get("/api/standings",
         description="League table from football-data.org. Tournaments return group stages instead of one flat table.")
def league_standings(
    league: str = Query(..., description="Liiga-koodi (esim. 'ENG-Premier League' tai 'ESP-La Liga-FD')"),
    season: str | None = Query(default=None, description="Season in YYMM form, for example '2526'. Defaults to the active season. Tournaments ignore it."),
):
    """
    Liigan tabletti suoraan football-data.org:n /competitions/{id}/standings:ista.

    Returns (domestic):
      - rows: lista riveistä järjestyksessä sijan mukaan
        (position, team_name, team_short_name, team_crest, played_games,
         won, draw, lost, goals_for, goals_against, goal_difference, points)

    Returns (turnaus, esim. INT-World Cup, #19):
      - groups: [{group: "Group A", rows: [rivi + form]}] — FD palauttaa
        lohkoitetun standingsin VAIN ilman season-paramia (verifioitu 12.6.:
        ?season=2026 antaa litteän 48 maan taulukon group=null, ?season=2025
        404:n). Siksi turnaushaara kutsuu FD:tä ilman seasonia.
    """
    from src.data.football_data_org import (
        FIXTURE_STANDINGS_CODES,
        _LIVE_TOURNAMENT_CODES,
        _api_key,
        _kausi_to_year,
    )

    if season is None:
        season = config.current_season()
    league_for_fd = FD_LEAGUE_ALIASES.get(league, league)
    code = FIXTURE_STANDINGS_CODES.get(league_for_fd)
    if not code:
        raise HTTPException(
            status_code=404,
            detail=f"League '{league}' not supported by football-data.org. "
                   f"Supported: {sorted(FIXTURE_STANDINGS_CODES.keys())}",
        )

    api_key = _api_key()
    if not api_key:
        raise HTTPException(
            status_code=500,
            detail="FOOTBALL_DATA_API_KEY not configured on server",
        )

    # Turnaushaara (#19): WC/EC → lohkoitettu standings ilman season-paramia.
    is_tournament = code in _LIVE_TOURNAMENT_CODES
    if is_tournament:
        url = f"https://api.football-data.org/v4/competitions/{code}/standings"
    else:
        year = _kausi_to_year(season)
        url = f"https://api.football-data.org/v4/competitions/{code}/standings?season={year}"
    # 16.8: vakaa cache-avain myos standingsille. URL sisaltaa season-vuoden,
    # joka on vakaa, mutta turnaushaara ja aliakset tekevat URLista
    # tarpeettoman herkan - avain on liiga + kausi.
    data, fd_stale = _fd_get_cached(
        url, api_key, cache_key=f"standings:{code}:{season}")

    if is_tournament:
        # Kaikki TOTAL-elementit = lohkot (group: "Group A"… kun FD on
        # lohkomoodissa; jos FD palauttaisi litteän group=null -muodon,
        # groups jää [{group: None, ...}] → frontend fallbackaa staattiseen).
        groups = [
            {
                "group": s.get("group"),
                "rows": [
                    {**_fd_standings_row(row), "form": row.get("form")}
                    for row in s.get("table", [])
                ],
            }
            for s in data.get("standings", [])
            if s.get("type") == "TOTAL" and s.get("group")
        ]
        return {"league": league, "season": None, "groups": groups,
                **({"stale": True} if fd_stale else {})}

    total = next(
        (s for s in data.get("standings", []) if s.get("type") == "TOTAL"),
        None,
    )
    if not total:
        return {"league": league, "season": season, "rows": [],
                **({"stale": True} if fd_stale else {})}

    return {
        "league": league,
        "season": season,
        "rows": [_fd_standings_row(row) for row in total["table"]],
        **({"stale": True} if fd_stale else {}),
    }


# ---------------------------------------------------------------------------
# ENDPOINT: joukkue-detail (T1)
# ---------------------------------------------------------------------------
@app.get("/api/team/{team_name}",
         description="Team detail from the data the model trains on: last five matches, form, and home and away averages.")
def team_detail(
    team_name: str,
    leagues: list[str] = Query(default=["ENG-Premier League"]),
    seasons: list[str] | None = Query(default=None,
        description="Default: edellinen + aktiivinen kausi (dynaaminen)"),
):
    """
    Joukkueen detail-tiedot DC-mallin koulutusdatasta.

    Käyttää samaa lataa_otteludata-funktiota kuin /api/predict — palauttaa
    cachetetun ottelut-DataFramen liiga+kausi-yhdistelmälle.

    Returns:
      - last_5_matches: 5 viimeisintä ottelua (date, home/away, score, location)
      - form: list of 5 chars ("W"|"D"|"L"), uusin ensin
      - home_stats: kotiotteluiden avg goals for/against + matches_played
      - away_stats: vierasotteluiden avg goals for/against + matches_played
      - total_matches: kokonaisottelumäärä joukkueelle datasetissä
    """
    if seasons is None:
        seasons = config.current_season_pair()
    df = _lataa_otteludata_cached(list(leagues), list(seasons))
    if df.empty:
        raise HTTPException(
            status_code=404,
            detail=f"No match data for leagues={leagues} seasons={seasons}",
        )

    home_matches = df[df["home_team"] == team_name].sort_values("date", ascending=False)
    away_matches = df[df["away_team"] == team_name].sort_values("date", ascending=False)
    all_matches = pd.concat([home_matches, away_matches]).sort_values("date", ascending=False)

    if all_matches.empty:
        raise HTTPException(
            status_code=404,
            detail=f"Team '{team_name}' not found in dataset for "
                   f"leagues={leagues} seasons={seasons}. "
                   f"Use /api/teams to list available teams.",
        )

    last_5_records = all_matches.head(5).to_dict("records")
    last_5_clean = [
        {
            "date": str(m["date"])[:10],
            "home_team": m["home_team"],
            "away_team": m["away_team"],
            "home_score": int(m["home_score"]),
            "away_score": int(m["away_score"]),
            "location": "home" if m["home_team"] == team_name else "away",
        }
        for m in last_5_records
    ]

    def _result(m, team):
        h, a = int(m["home_score"]), int(m["away_score"])
        is_home = m["home_team"] == team
        if h == a:
            return "D"
        if (is_home and h > a) or (not is_home and a > h):
            return "W"
        return "L"

    form = [_result(m, team_name) for m in last_5_records]

    def _venue_stats(matches, is_home: bool):
        if matches.empty:
            return None
        goals_for_col = "home_score" if is_home else "away_score"
        goals_against_col = "away_score" if is_home else "home_score"
        return {
            "avg_goals_for": round(float(matches[goals_for_col].mean()), 2),
            "avg_goals_against": round(float(matches[goals_against_col].mean()), 2),
            "matches_played": int(len(matches)),
        }

    return {
        "team_name": team_name,
        "leagues": leagues,
        "seasons": seasons,
        "last_5_matches": last_5_clean,
        "form": form,
        "home_stats": _venue_stats(home_matches, True),
        "away_stats": _venue_stats(away_matches, False),
        "total_matches": int(len(all_matches)),
    }


# ---------------------------------------------------------------------------
# ENDPOINT: tulevat ottelut (T4)
# ---------------------------------------------------------------------------
@app.get("/api/fixtures",
         description="Upcoming fixtures for a league, from today up to `days` ahead. An empty list at the end of a season is normal and not an error.")
def upcoming_fixtures(
    league: str = Query(..., description="Liiga-koodi (esim. 'ENG-Premier League' tai 'ESP-La Liga-FD')"),
    days: int = Query(default=7, ge=1, le=60, description="How many days ahead to fetch (tournaments use a wider window)"),
):
    """
    Tulevat ottelut football-data.org:n /competitions/{id}/matches:ista.

    Hakee SCHEDULED + TIMED -statuksen ottelut tästä päivästä `days` päivää
    eteenpäin. Huom: kauden loppupuolella (touko-kesäkuu) lista voi olla tyhjä
    jos liiga on jo pelannut kautensa loppuun — se ei ole virhe.

    Returns:
      - league, days: echo
      - fixtures: lista otteluita aikajärjestyksessä (date, datetime,
        home_team, away_team, home_team_short_name, away_team_short_name,
        matchday)
    """
    from datetime import datetime, timedelta, timezone
    from src.data.football_data_org import FIXTURE_STANDINGS_CODES, _api_key

    league_for_fd = FD_LEAGUE_ALIASES.get(league, league)
    code = FIXTURE_STANDINGS_CODES.get(league_for_fd)
    if not code:
        raise HTTPException(
            status_code=404,
            detail=f"League '{league}' not supported by football-data.org. "
                   f"Supported: {sorted(FIXTURE_STANDINGS_CODES.keys())}",
        )

    api_key = _api_key()
    if not api_key:
        raise HTTPException(
            status_code=500,
            detail="FOOTBALL_DATA_API_KEY not configured on server",
        )

    today = datetime.now(timezone.utc).date()
    date_to = today + timedelta(days=days)
    url = (
        f"https://api.football-data.org/v4/competitions/{code}/matches"
        f"?status=SCHEDULED,TIMED"
        f"&dateFrom={today.isoformat()}&dateTo={date_to.isoformat()}"
    )
    # #49: TTL-cache + 429-backoff + stale-fallback (ei suoraa FD-kutsua)
    # 16.8: fixtureille oma pidempi TTL — ks. FD_FIXTURES_TTL_SEC — ja VAKAA
    # cache-avain, koska URLin dateFrom/dateTo vaihtuu joka vuorokausi.
    data, fd_stale = _fd_get_cached(
        url, api_key, ttl_sec=FD_FIXTURES_TTL_SEC,
        cache_key=f"fixtures:{code}:{days}")
    fixtures = []
    for m in data.get("matches", []):
        home = m.get("homeTeam") or {}
        away = m.get("awayTeam") or {}
        # Ohita ottelut joista vastustaja ei ole vielä ratkennut (yleistä
        # CL-karsinnoissa: homeTeam/awayTeam name on tällöin None)
        if not home.get("name") or not away.get("name"):
            continue
        fixtures.append({
            "date": (m.get("utcDate") or "")[:10],
            "datetime": m.get("utcDate"),
            "home_team": home.get("name"),
            "away_team": away.get("name"),
            "home_team_short_name": home.get("shortName"),
            "away_team_short_name": away.get("shortName"),
            "matchday": m.get("matchday"),
        })

    fixtures.sort(key=lambda f: f["datetime"] or "")
    return {"league": league, "days": days, "fixtures": fixtures,
            **({"stale": True} if fd_stale else {})}


# ---------------------------------------------------------------------------
# ENDPOINT: kaikki ottelut yhtena paivana, yli liigojen
# ---------------------------------------------------------------------------
@app.get("/api/fixtures/by-date")
def fixtures_by_date(
    date: str = Query(..., description="UTC-paiva YYYY-MM-DD"),
):
    """Kaikki ottelut annettuna UTC-paivana, ryhmiteltyna liigoittain.

    🔴 EI TEE YHTAAN UPSTREAM-KUTSUA. Lukee vain sen mita lammitin on jo
    hakenut (`fixtures:{code}:35`, kaikille liigoille, 35 vrk eteenpain).

    Tama on suunnittelupaatos eika optimointi. Naiivi toteutus hakisi
    jokaisen liigan erikseen pyyntopolulla, eli yksi sivunavaus = ~14
    ulospain lahtevaa kutsua. football-data.orgin ilmaiskiintio on ~10/min
    per avain, joten se ei ole hidas vaan RIKKI: 16.8 aamulla sama kaava
    tuotti 429-ryopyn ja 38 sekunnin jumin kayttajalle. Kayttajan pyynto ei
    odota upstreamia, piste.

    Seuraus jonka on nakyttava vastauksessa: paiva jota lammitin ei ole
    ehtinyt kattaa palauttaa tyhjan listan, ei virhetta. `covered` kertoo
    kuinka monta liigaa oli valimuistissa, jotta klientti voi erottaa
    "ei otteluita" tilasta "ei viela tiedossa".
    """
    from datetime import datetime as _dt
    from src.data.football_data_org import FIXTURE_STANDINGS_CODES

    try:
        want = _dt.strptime(date, "%Y-%m-%d").date().isoformat()
    except ValueError:
        raise HTTPException(status_code=400,
                            detail="date must be YYYY-MM-DD")

    # Kaanteinen kartta koodista liigan nimeen: cache-avaimessa on koodi,
    # mutta klientti puhuu liiganimilla (sama sanasto kuin /api/fixtures).
    code_to_league: dict[str, str] = {}
    for league_name, code in FIXTURE_STANDINGS_CODES.items():
        code_to_league.setdefault(code, league_name)

    leagues: list[dict] = []
    covered = 0
    total = 0
    for code, league_name in sorted(code_to_league.items(),
                                    key=lambda kv: kv[1]):
        hit = _FD_HTTP_CACHE.get(f"fixtures:{code}:35")
        if not hit:
            continue
        covered += 1
        rows = []
        for m in (hit[1] or {}).get("matches", []):
            if (m.get("utcDate") or "")[:10] != want:
                continue
            home = m.get("homeTeam") or {}
            away = m.get("awayTeam") or {}
            # Sama ohitus kuin /api/fixtures: CL-karsinnoissa vastustaja voi
            # olla viela ratkeamatta, jolloin nimi on None.
            if not home.get("name") or not away.get("name"):
                continue
            rows.append({
                "date": want,
                "datetime": m.get("utcDate"),
                "home_team": home.get("name"),
                "away_team": away.get("name"),
                "home_team_short_name": home.get("shortName"),
                "away_team_short_name": away.get("shortName"),
                "matchday": m.get("matchday"),
            })
        if not rows:
            continue
        rows.sort(key=lambda f: f["datetime"] or "")
        total += len(rows)
        leagues.append({"league": league_name, "code": code,
                        "fixtures": rows})

    # Liigat aikajarjestykseen paivan sisalla: ensin alkava liiga ylos.
    leagues.sort(key=lambda g: g["fixtures"][0]["datetime"] or "")
    return {
        "date": want,
        "leagues": leagues,
        "total": total,
        "leagues_covered": covered,
        "leagues_known": len(code_to_league),
    }


# ---------------------------------------------------------------------------
# T7-apufunktiot: premium-H2H-jakauma + joukkueen muoto-trendi
# ---------------------------------------------------------------------------
def _h2h_summary(h2h_all: pd.DataFrame, home_team: str, away_team: str) -> dict:
    """
    Keskinaisten kohtaamisten voitto/tasapeli/haviö-jakauma (T7 premium).

    'Kaikista' tarkoittaa ladatun kausi-ikkunan sisalta — vastaus EI vaita
    olevansa taydellinen historia. total_matches kertoo todellisen maaran
    jota frontend kayttaa rehellisessa labelissa ("All N meetings").
    """
    if h2h_all.empty:
        return {"total_matches": 0, "home_team_wins": 0, "draws": 0, "away_team_wins": 0}

    home_wins = away_wins = draws = 0
    for _, m in h2h_all.iterrows():
        h, a = int(m["home_score"]), int(m["away_score"])
        if h == a:
            draws += 1
            continue
        winner = m["home_team"] if h > a else m["away_team"]
        if winner == home_team:
            home_wins += 1
        elif winner == away_team:
            away_wins += 1
    return {
        "total_matches": int(len(h2h_all)),
        "home_team_wins": home_wins,
        "draws": draws,
        "away_team_wins": away_wins,
    }


def _h2h_item(m) -> dict:
    """Yksi h2h-rivi API-vastaukseen (#77b).

    Näyttöscore = reg + jatkoaika ILMAN rangaistuspotkuja (*_disp, jonka
    FD-loader johtaa duration == PENALTY_SHOOTOUT -kentästä). FD summaa
    shootoutin fullTimeen (esim. CL-finaali 30.5.2026 fullTime 5-4 = 1-1 +
    pakat 4-3), joten fullTime != disp <=> PENALTY_SHOOTOUT — additiivinen
    penalties-lippu on durationista johdettu, ei heuristiikka.

    Lähteissä ilman disp-sarakkeita (understat-PL, martj42-WC) penalties jää
    Falseksi: pakkatietoa ei ole datassa (WC-puutteen korjaus = shootouts.csv-
    vendorointi, ks. #77-raportti 12.6.).
    """
    h_full, a_full = int(m["home_score"]), int(m["away_score"])
    hd = m.get("home_score_disp")
    ad = m.get("away_score_disp")
    h_disp = h_full if hd is None or pd.isna(hd) else int(hd)
    a_disp = a_full if ad is None or pd.isna(ad) else int(ad)
    item = {
        "date": str(m["date"])[:10],
        "home_team": m["home_team"],
        "away_team": m["away_team"],
        "home_score": h_disp,
        "away_score": a_disp,
        "penalties": (h_full, a_full) != (h_disp, a_disp),
    }
    if item["penalties"]:
        # Shootoutissa fullTime ei voi olla tasan -> voittaja vertailusta.
        item["penalty_winner"] = "home" if h_full > a_full else "away"
    return item


def _team_recent_form(df: pd.DataFrame, team: str, n: int = 8) -> list[dict]:
    """
    Joukkueen n viimeisinta ottelua momentum-visualisointia varten (T7).

    Palautetaan aikajarjestyksessa (vanhin ensin) jotta frontend piirtaa
    tuloskayran luonnollisesti vasemmalta oikealle. Yhden joukkueen otteluita
    on ladatussa 2 kauden datassa runsaasti (~75) — toisin kuin H2H-paria,
    joten muoto-trendi on taysin katettu nykydatalla.
    """
    matches = df[
        (df["home_team"] == team) | (df["away_team"] == team)
    ].sort_values("date", ascending=False).head(n)

    out = []
    for _, m in matches.iterrows():
        is_home = m["home_team"] == team
        scored = int(m["home_score"] if is_home else m["away_score"])
        conceded = int(m["away_score"] if is_home else m["home_score"])
        if scored > conceded:
            result, points = "W", 3
        elif scored == conceded:
            result, points = "D", 1
        else:
            result, points = "L", 0
        out.append({
            "date": str(m["date"])[:10],
            "opponent": m["away_team"] if is_home else m["home_team"],
            "location": "home" if is_home else "away",
            "scored": scored,
            "conceded": conceded,
            "result": result,
            "points": points,
        })
    out.reverse()  # vanhin ensin
    return out


# ---------------------------------------------------------------------------
# ENDPOINT: ennuste
# ---------------------------------------------------------------------------
@app.post("/api/predict", response_model=PredictionResponse)
def predict(req: PredictionRequest):
    """Tee 1X2, O/U 2.5, BTTS -ennuste annetulle ottelulle."""
    dc = _saa_malli(
        tuple(req.leagues), tuple(req.seasons),
        decay=req.decay, bayes_shrinkage=req.bayes_shrinkage,
    )

    if req.home_team not in dc.attack:
        raise HTTPException(
            status_code=404,
            detail=f"Home team '{req.home_team}' not found in model. "
                   f"Use /api/teams to list available teams.",
        )
    if req.away_team not in dc.attack:
        raise HTTPException(
            status_code=404,
            detail=f"Away team '{req.away_team}' not found in model.",
        )

    # Manuaaliset säädöt → multiplier
    saadot = apply_match_adjustments(
        home_injury_pct=req.home_injury_pct,
        away_injury_pct=req.away_injury_pct,
        home_motivation_pct=req.home_motivation_pct,
        away_motivation_pct=req.away_motivation_pct,
        is_derby=req.is_derby,
    )

    # Ennusteet
    lam, mu = dc.expected_goals(req.home_team, req.away_team, adjustments=saadot)
    p_1x2 = dc.predict_1x2(req.home_team, req.away_team, adjustments=saadot)
    p_ou = dc.predict_over_under(req.home_team, req.away_team, line=2.5, adjustments=saadot)
    p_btts = dc.predict_btts(req.home_team, req.away_team, adjustments=saadot)
    top = dc.todennakoisin_tulos(req.home_team, req.away_team, top_n=req.top_n, adjustments=saadot)

    # T5: 5 viimeista keskinaista kohtaamista (molemmat venue-jarjestykset).
    # #71: lataa_otteludata-tason DataFrame-cache eliminoi tuplakutsun cold-
    # latauskustannuksen. Domestic-liigoille pysyva, turnausliigoille
    # ohitettu (#69:n TTL-logiikka).
    df = _lataa_otteludata_cached(list(req.leagues), list(req.seasons))
    h2h_all = df[
        ((df["home_team"] == req.home_team) & (df["away_team"] == req.away_team))
        | ((df["home_team"] == req.away_team) & (df["away_team"] == req.home_team))
    ].sort_values("date", ascending=False)
    # #77b: rivit _h2h_item-helperilla -> nayttoscore ilman pakkoja (CL-
    # shootoutit eivat enaa nayta fullTime 5-4 vaan 1-1 + penalties-lippu).
    h2h = [_h2h_item(m) for _, m in h2h_all.head(5).iterrows()]

    # T7: premium-visualisoinnit — H2H-jakauma + kummankin joukkueen muoto.
    # Kaytetaan jo ladattua df:aa, ei lisalatauskustannuksia.
    # HUOM: summary lasketaan fullTimesta -> pakkapelivoittaja kirjautuu
    # voitoksi (FD-lahteet); h2h-rivin "(pens)"-merkinta selittaa eron.
    h2h_summary = _h2h_summary(h2h_all, req.home_team, req.away_team)
    form_trend = {
        "home_team": _team_recent_form(df, req.home_team),
        "away_team": _team_recent_form(df, req.away_team),
    }

    return PredictionResponse(
        home_team=req.home_team,
        away_team=req.away_team,
        expected_goals_home=round(float(lam), 3),
        expected_goals_away=round(float(mu), 3),
        p_home_win=round(p_1x2["home"], 4),
        p_draw=round(p_1x2["draw"], 4),
        p_away_win=round(p_1x2["away"], 4),
        fair_odds_home=round(1.0 / max(p_1x2["home"], 0.001), 2),
        fair_odds_draw=round(1.0 / max(p_1x2["draw"], 0.001), 2),
        fair_odds_away=round(1.0 / max(p_1x2["away"], 0.001), 2),
        p_over_2_5=round(p_ou["over"], 4),
        p_under_2_5=round(p_ou["under"], 4),
        p_btts_yes=round(p_btts["btts_yes"], 4),
        p_btts_no=round(p_btts["btts_no"], 4),
        top_scores=[{"score": s, "probability": round(p, 4)} for s, p in top],
        h2h=h2h,
        h2h_summary=h2h_summary,
        form_trend=form_trend,
        # Vain seurajoukkueille: /api/predict-wc jattaa taman tyhjaksi, koska
        # maajoukkueilla ei ole siirtoikkunaa eika seurakauden vaihtuvuutta.
        data_confidence=_data_confidence(req.home_team, req.away_team),
    )


# ---------------------------------------------------------------------------
# WC-endpoint — kansainväliset joukkueet
# ---------------------------------------------------------------------------
def _wc_seasons_to_loader_format(seasons: list[str]) -> list[str]:
    """
    Muunna 4-digit WC-vuodet ('2018', '2022', '2026') 2-digit-formaattiin
    ('18', '22', '26'), jonka football_data_org._kausi_to_year tulkitsee
    oikein vuosiksi 2018, 2022, 2026.

    Tämä kerros suojaa muita endpointteja: emme muuta loaderin
    _kausi_to_year-funktiota, joka tällä hetkellä on suunniteltu
    seurakausi-formaatille '2425' → '2024'.
    """
    out = []
    for s in seasons:
        s = s.strip()
        if len(s) == 4 and s.startswith("20"):
            out.append(s[2:])  # '2018' → '18'
        elif len(s) == 2:
            out.append(s)
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid WC season '{s}'. Use 4-digit year like '2018'.",
            )
    return out


@app.post("/api/predict-wc", response_model=PredictionResponse,
          description="1X2, over/under 2.5 and both teams to score for international sides, from a prebuilt Dixon-Coles model fitted on national team results.")
def predict_wc(req: PredictWCRequest):
    """
    Tee 1X2, O/U 2.5, BTTS -ennuste kansainvälisten joukkueiden välille.

    #79: datalähde = martj42 maaotteludata (kaikkien 48 WC-maan tuoreet ottelut).
    Malli on ESIRAKENNETTU (data/wc_model.json) ja ladataan ajossa — Render
    Starter ei jaksa fitata "any"-mallia (195 maata) ajossa ilman timeoutia.
    H2H/form-trend ladataan martj42-datasta (cachetettu CSV-suodatus).
    """
    if req.leagues != ["INT-World Cup"]:
        raise HTTPException(
            status_code=400,
            detail="WC endpoint supports only leagues=['INT-World Cup']. "
                   "Use /api/predict for other leagues.",
        )

    # #79: resolvoi joukkuenimet FD-kanoniseen muotoon (frontend voi lähettää
    # FD-, martj42- tai varianttinimiä). resolve_wc_name palauttaa None jos ei
    # WC2026-maa → 404. Mallin sisäiset nimet + H2H-data ovat kanonisia.
    from src.data.wc_teams import resolve_wc_name
    home_canon = resolve_wc_name(req.home_team)
    away_canon = resolve_wc_name(req.away_team)
    if home_canon is None:
        raise HTTPException(
            status_code=404,
            detail=f"Home team '{req.home_team}' is not a World Cup 2026 team.",
        )
    if away_canon is None:
        raise HTTPException(
            status_code=404,
            detail=f"Away team '{req.away_team}' is not a World Cup 2026 team.",
        )

    loader_seasons = _wc_seasons_to_loader_format(req.seasons)

    # #79: lataa esirakennettu WC-malli (ei fittiä ajossa). JSON-lataus on
    # lru-cachetettu → ~ms. req.decay/req.bayes_shrinkage jätetään huomiotta
    # (malli on rakennettu WC_FIT_DECAY/WC_FIT_BAYES-arvoilla offline).
    from src.data.international_results import load_wc_model
    try:
        dc_cached = load_wc_model()
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"WC model unavailable: {type(e).__name__}",
        )

    # WC-otteluita pelataan neutraalilla maalla (Qatar 2022, USA/CAN/MEX 2026).
    # DC-malli oppii datasta globaalin kotiedun (home_advantage = γ) koska data
    # on kirjattu home/away-rakenteena.
    #
    # #61 (2b-1): neutralointi ei ole home_advantage=0 vaan PUOLET kotiedusta
    # molemmille. Mallissa lam saa kotiboostin γ, mu ei saa mitään → pelkkä
    # nollaus ennustaisi BOLEMMAT joukkueet vierasvauhtia (kokonaistaso
    # deflatoituu ~exp(γ/2)). Oikea neutraali = kotidatan ja vierasdatan
    # geometrinen keskiarvo: molemmat saavat γ/2.
    #
    # γ/2 viedään defence-parametriin, koska defence esiintyy SEKÄ lam:ssa
    # (defence[away]) ETTÄ mu:ssa (defence[home]) → boost osuu molempiin.
    # Shallow-kopio: defence-dict KORVATAAN uudella, alkuperäinen cache säilyy.
    dc = copy.copy(dc_cached)
    half_home_adv = dc_cached.home_advantage / 2.0
    dc.defence = {t: v + half_home_adv for t, v in dc_cached.defence.items()}
    dc.home_advantage = 0.0
    dc.home_advantage_per_team = {t: 0.0 for t in dc.teams_}

    # Sekundaarivahti: maa on validi WC-maa mutta sillä ei ole dataa ikkunassa
    # (käytännössä ei tapahdu — min ~22-38 ottelua/maa). Kanoniset nimet.
    if home_canon not in dc.attack:
        raise HTTPException(
            status_code=404,
            detail=f"No recent international data for '{req.home_team}'.",
        )
    if away_canon not in dc.attack:
        raise HTTPException(
            status_code=404,
            detail=f"No recent international data for '{req.away_team}'.",
        )

    saadot = apply_match_adjustments(
        home_injury_pct=req.home_injury_pct,
        away_injury_pct=req.away_injury_pct,
        home_motivation_pct=req.home_motivation_pct,
        away_motivation_pct=req.away_motivation_pct,
        is_derby=req.is_derby,
    )

    lam, mu = dc.expected_goals(home_canon, away_canon, adjustments=saadot)
    p_1x2 = dc.predict_1x2(home_canon, away_canon, adjustments=saadot)
    p_ou = dc.predict_over_under(home_canon, away_canon, line=2.5, adjustments=saadot)
    p_btts = dc.predict_btts(home_canon, away_canon, adjustments=saadot)
    top = dc.todennakoisin_tulos(home_canon, away_canon, top_n=5, adjustments=saadot)

    # T5/T7 (#25): H2H + form-trend WC-historiadatasta (sama WC-loader jota malli
    # kayttaa). Mirror domestic /api/predict -polusta — _h2h_summary +
    # _team_recent_form ovat geneerisia (df + nimet). df ladataan loader_seasons-
    # formaatissa (#69:n turnaus-TTL hoitaa cachen).
    df = _lataa_otteludata_cached(list(req.leagues), loader_seasons)
    h2h_all = df[
        ((df["home_team"] == home_canon) & (df["away_team"] == away_canon))
        | ((df["home_team"] == away_canon) & (df["away_team"] == home_canon))
    ].sort_values("date", ascending=False)
    # #25/#77b: rivit _h2h_item-helperilla (näyttöscore ilman pakkoja +
    # penalties-lippu). martj42-datassa ei ole disp-/shootout-sarakkeita ->
    # penalties jää aina Falseksi tällä polulla.
    h2h = [_h2h_item(m) for _, m in h2h_all.head(5).iterrows()]
    # HUOM (#77, todettu 12.6.): martj42-scoret ovat reg + jatkoaika ILMAN
    # pakkoja -> summary kirjaa pakkapelivoitot TASAPELEIKSI (esim. Argentina-
    # France 2022 = draw). Tunnettu rajoite; faktinen korjaus vaatisi martj42
    # shootouts.csv:n vendoroinnin (h2h-only lookup, Villen päätös).
    h2h_summary = _h2h_summary(h2h_all, home_canon, away_canon)
    form_trend = {
        "home_team": _team_recent_form(df, home_canon),
        "away_team": _team_recent_form(df, away_canon),
    }

    return PredictionResponse(
        home_team=req.home_team,
        away_team=req.away_team,
        expected_goals_home=round(float(lam), 3),
        expected_goals_away=round(float(mu), 3),
        p_home_win=round(p_1x2["home"], 4),
        p_draw=round(p_1x2["draw"], 4),
        p_away_win=round(p_1x2["away"], 4),
        fair_odds_home=round(1.0 / max(p_1x2["home"], 0.001), 2),
        fair_odds_draw=round(1.0 / max(p_1x2["draw"], 0.001), 2),
        fair_odds_away=round(1.0 / max(p_1x2["away"], 0.001), 2),
        p_over_2_5=round(p_ou["over"], 4),
        p_under_2_5=round(p_ou["under"], 4),
        p_btts_yes=round(p_btts["btts_yes"], 4),
        p_btts_no=round(p_btts["btts_no"], 4),
        top_scores=[{"score": s, "probability": round(p, 4)} for s, p in top],
        h2h=h2h,
        h2h_summary=h2h_summary,
        form_trend=form_trend,
    )


# ---------------------------------------------------------------------------
# ENDPOINT: parlay — P(kaikki valinnat oikein) tulona (vC23, premium-UI)
#
# Gambling-turvallinen linja: EI kertoimia, EI "odds"/"betting"-sanastoa —
# vain "model-implied probability that all N predictions are correct".
# Riippumattomuusoletus sanotaan vastauksessa eksplisiittisesti.
#
# Reuse ilman tuplafittiä: domestic-leg osuu _saa_malli-cacheen (warmup
# esifittaa 6 liigaa) ja WC-leg lru-cachettuun load_wc_model():iin. Leg laskee
# VAIN predict_1x2:n — ei H2H/form/top_scores-kuormaa. predict()/predict_wc()
# -funktioihin ei kosketa (domestic bit-exact, regressiosuite vahtii).
# ---------------------------------------------------------------------------
class ParlayLeg(BaseModel):
    """One parlay leg: a match and the 1/X/2 pick for it."""
    home_team: str = Field(..., examples=["Arsenal"])
    away_team: str = Field(..., examples=["Liverpool"])
    leagues: list[str] = Field(default=["ENG-Premier League"])
    seasons: list[str] = Field(default_factory=config.current_season_pair)
    pick: Literal["1", "X", "2"] = Field(
        ..., description="1 = home win, X = draw, 2 = away win")


class ParlayRequest(BaseModel):
    legs: list[ParlayLeg] = Field(..., min_length=2, max_length=5)

    @field_validator("legs")
    @classmethod
    def _no_duplicate_matches(cls, v: list[ParlayLeg]) -> list[ParlayLeg]:
        # Sama ottelu kahdesti rikkoisi riippumattomuustulon (p*p != p).
        seen = set()
        for leg in v:
            key = (leg.home_team, leg.away_team, tuple(leg.leagues))
            if key in seen:
                raise ValueError(
                    f"Duplicate match in parlay: {leg.home_team} vs {leg.away_team}")
            seen.add(key)
        return v


class ParlayLegResult(BaseModel):
    home_team: str
    away_team: str
    leagues: list[str]
    pick: str
    p_home_win: float
    p_draw: float
    p_away_win: float
    pick_probability: float


class ParlayResponse(BaseModel):
    legs: list[ParlayLegResult]
    n_legs: int
    # Tulo pyöristetyistä per-leg-arvoista (4 dp) → näytetyistä luvuista
    # laskettavissa käsin. 6 dp riittää 5 legille (min ~1e-5-tasoa).
    combined_probability: float
    assumes_independence: bool = True
    note: str
    disclaimer: str


def _parlay_leg_1x2(leg: ParlayLeg, idx: int) -> dict:
    """Palauta legin 1X2-jakauma lämpimästä mallista. HTTPException jos
    joukkue/malli puuttuu — virheviesti kantaa leg-numeron (1-pohjainen)."""
    if leg.leagues == ["INT-World Cup"]:
        from src.data.wc_teams import resolve_wc_name
        from src.data.international_results import load_wc_model
        home = resolve_wc_name(leg.home_team)
        away = resolve_wc_name(leg.away_team)
        if home is None:
            raise HTTPException(
                status_code=404,
                detail=f"Leg {idx + 1}: '{leg.home_team}' is not a World Cup 2026 team.")
        if away is None:
            raise HTTPException(
                status_code=404,
                detail=f"Leg {idx + 1}: '{leg.away_team}' is not a World Cup 2026 team.")
        try:
            dc_cached = load_wc_model()
        except Exception as e:
            raise HTTPException(
                status_code=503,
                detail=f"WC model unavailable: {type(e).__name__}")
        # #61 (2b-1): neutraali venue = γ/2 molemmille defenceen — sama
        # neutralointi kuin predict_wc():ssä (kopio, jotta sitä ei kosketa).
        dc = copy.copy(dc_cached)
        half = dc_cached.home_advantage / 2.0
        dc.defence = {t: v + half for t, v in dc_cached.defence.items()}
        dc.home_advantage = 0.0
        dc.home_advantage_per_team = {t: 0.0 for t in dc.teams_}
        if home not in dc.attack or away not in dc.attack:
            raise HTTPException(
                status_code=404,
                detail=f"Leg {idx + 1}: no recent international data for this pair.")
        return dc.predict_1x2(home, away)

    dc = _saa_malli(tuple(leg.leagues), tuple(leg.seasons))
    if leg.home_team not in dc.attack:
        raise HTTPException(
            status_code=404,
            detail=f"Leg {idx + 1}: home team '{leg.home_team}' not found in model. "
                   f"Use /api/teams to list available teams.")
    if leg.away_team not in dc.attack:
        raise HTTPException(
            status_code=404,
            detail=f"Leg {idx + 1}: away team '{leg.away_team}' not found in model.")
    return dc.predict_1x2(leg.home_team, leg.away_team)


@app.post("/api/parlay", response_model=ParlayResponse,
          description="Model-implied probability that every selected result comes in. It assumes the matches are independent, and the response says so.")
def parlay(req: ParlayRequest):
    """
    Model-implied probability that all N predictions are correct.

    2-5 ottelua, kullekin käyttäjän 1/X/2-valinta → per-leg P(valittu
    lopputulos) + kumulatiivinen tulo. Olettaa ottelut riippumattomiksi
    (assumes_independence: true) — sanottu rehellisesti vastauksessa.
    """
    pick_key = {"1": "home", "X": "draw", "2": "away"}
    results: list[ParlayLegResult] = []
    combined = 1.0
    for i, leg in enumerate(req.legs):
        p = _parlay_leg_1x2(leg, i)
        ph, pd_, pa = round(p["home"], 4), round(p["draw"], 4), round(p["away"], 4)
        pick_p = {"1": ph, "X": pd_, "2": pa}[leg.pick]
        combined *= pick_p
        results.append(ParlayLegResult(
            home_team=leg.home_team, away_team=leg.away_team,
            leagues=leg.leagues, pick=leg.pick,
            p_home_win=ph, p_draw=pd_, p_away_win=pa,
            pick_probability=pick_p,
        ))
    return ParlayResponse(
        legs=results,
        n_legs=len(results),
        combined_probability=round(combined, 6),
        assumes_independence=True,
        note="Combined probability assumes each match is independent.",
        disclaimer="Model prediction, not betting advice.",
    )


# ---------------------------------------------------------------------------
# ENDPOINT: tyhjennä mallin välimuisti (debug-tarkoitukseen)
# ---------------------------------------------------------------------------
@app.post("/api/admin/clear-cache",
          description="Clear the model cache and force a refit. Requires an admin token.")
def clear_cache(request: Request):
    """Tyhjennä mallin välimuisti — pakottaa uudelleen-sovituksen.

    Edge-sprint P0 (turva): vaatii X-Admin-Token-headerin joka verrataan
    ADMIN_TOKEN-enviin. Env puuttuu -> 403 aina (endpoint pois paalta
    kunnes token on konfiguroitu Renderiin)."""
    require_admin(request)
    from src.data.football_data_org import _TOURNAMENT_MEM_CACHE
    with _MODEL_LOCK:
        n = len(_MODEL_CACHE)
        _MODEL_CACHE.clear()
        _MODEL_FITTED_AT.clear()
        _REFIT_IN_PROGRESS.clear()
    cleared_tournament = len(_TOURNAMENT_MEM_CACHE)
    _TOURNAMENT_MEM_CACHE.clear()
    with _DATA_CACHE_LOCK:
        cleared_data = len(_DATA_CACHE)
        _DATA_CACHE.clear()
    return {
        "cleared_models": n,
        "cleared_tournament_data": cleared_tournament,
        "cleared_match_data": cleared_data,
    }


# ---------------------------------------------------------------------------
# Affiliate-laskenta (jaettu admin-raportin ja luojan oman nakyman kesken)
# ---------------------------------------------------------------------------
AFFILIATE_CAVEAT = (
    "signups is a floor, not a measurement: the ref is read from the "
    "browser at sign-up, so a click in one browser and a sign-up in "
    "another is not counted, and the mobile app does not write a ref "
    "at all. stamped counts subscriptions carrying the code, and "
    "commission is 30 percent of every payment they make, so stamped is "
    "a count of subscriptions and not a euro figure."
)

# Laskenta kayttaa koko tililistan sivutuksen JA Stripen tilauslistauksen, eli
# se on kallein reitti mita meilla on. Luojanakyma on sivu jonka ihminen
# lataa uudelleen kun mikaan ei liiku, joten ilman valimuistia yksi kartynyt
# selain riittaisi tekemaan siita jatkuvan taustakuorman.
_AFFILIATE_TALLY_TTL = 60.0
_AFFILIATE_TALLY_CACHE: dict[str, tuple[float, dict]] = {}
_AFFILIATE_TALLY_LOCK = threading.Lock()


def _affiliate_tally(only: Optional[str] = None, fresh: bool = False) -> dict:
    """Per koodi: `signups` (Supabase) + `stamped` (Stripe).

    `only` rajaa TULOKSEN yhteen koodiin. Se ei tee hausta halvempaa (koko
    tililista on kaytava lapi joka tapauksessa), mutta se estaa toisen luojan
    lukujen paatymisen samaan vastausolioon jota luojanakyma kasittelee.

    🔴 EPAONNISTUNUTTA HAKUA EI CACHETA. Jos Supabase on nurin, tulos on
    "0 signupia" — ja 60 sekunnin cache jaadyttaisi sen nollan nakymaan joka
    kertoo luojalle ettei kukaan ole tullut. Lahdeliput kulkevat vastauksessa
    mukana, ja kutsujan on luettava ne.
    """
    key = only or "*"
    now = time.time()
    if not fresh:
        with _AFFILIATE_TALLY_LOCK:
            hit = _AFFILIATE_TALLY_CACHE.get(key)
            if hit and now - hit[0] < _AFFILIATE_TALLY_TTL:
                return hit[1]

    out: dict[str, dict] = {}
    if only:
        out[only] = {"signups": 0, "stamped": 0}

    def _bucket(code: str) -> Optional[dict]:
        """None = tama koodi ei kuulu vastaukseen (`only`-rajaus)."""
        if only and code != only:
            return None
        return out.setdefault(code, {"signups": 0, "stamped": 0})

    # 1) Rekisteroityneet tilit Supabasen admin-API:sta. Sivutetaan, koska
    #    oletus on 50 kayttajaa/sivu ja hiljainen katkaisu antaisi liian
    #    pienen luvun juuri silloin kun kayttajia alkaa olla.
    supa_ok = False
    total_users = 0
    if SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY:
        headers = {
            "apikey": SUPABASE_SERVICE_ROLE_KEY,
            "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        }
        page = 1
        try:
            while page <= 40:  # 40 x 200 = 8000 tilia, katto ettei jumita
                r = requests.get(
                    f"{SUPABASE_URL}/auth/v1/admin/users",
                    params={"page": page, "per_page": 200},
                    headers=headers, timeout=15,
                )
                if r.status_code != 200:
                    # 🔴 EI `break` ilman lipun laskua. Ensimmainen versio
                    # asetti `supa_ok = True` silmukan JALKEEN, joten 401
                    # (avaimen rotaatio), 429 tai 500 tuotti "signups: 0,
                    # supabase: true" - eli tasan sen valheellisen nollan
                    # jonka koko null-erottelu on rakennettu estamaan.
                    print("[affiliate-report] Supabase-sivu "
                          f"{page} -> HTTP {r.status_code}")
                    raise RuntimeError(f"supabase HTTP {r.status_code}")
                users = (r.json() or {}).get("users") or []
                if not users:
                    break
                total_users += len(users)
                for u in users:
                    ref = _clean_affiliate_ref(
                        (u.get("user_metadata") or {}).get("ref"))
                    bucket = _bucket(ref) if ref else None
                    if bucket is not None:
                        bucket["signups"] += 1
                if len(users) < 200:
                    break
                page += 1
            else:
                # Sivutuskatto tayteen: lista jatkuu mutta lopetimme kesken,
                # eli luku on vaillinainen. Sekin on "ei tietoa" eika luku.
                raise RuntimeError("supabase pagination cap reached")
            supa_ok = True
        except Exception as e:
            print(f"[affiliate-report] Supabase-haku epaonnistui: {e}")

    # 2) Leimatut tilaukset Stripesta.
    stripe_ok = False
    try:
        subs = stripe.Subscription.list(limit=100, status="all")
        for s in subs.auto_paging_iter():
            # `s` on StripeObject eika dict: `.get` heittaisi (ks. _stripe_field).
            meta = _stripe_field(s, "metadata")
            code = _clean_affiliate_ref(_stripe_field(meta, "affiliate"))
            bucket = _bucket(code) if code else None
            if bucket is not None:
                bucket["stamped"] += 1
                bucket.setdefault("statuses", {})
                st = _stripe_field(s, "status") or "unknown"
                bucket["statuses"][st] = bucket["statuses"].get(st, 0) + 1
        stripe_ok = True
    except Exception as e:
        print(f"[affiliate-report] Stripe-haku epaonnistui: {e}")

    result = {
        "codes": out,
        "total_accounts_scanned": total_users,
        "sources_ok": {"supabase": supa_ok, "stripe": stripe_ok},
    }
    if supa_ok and stripe_ok:
        with _AFFILIATE_TALLY_LOCK:
            _AFFILIATE_TALLY_CACHE[key] = (now, result)
    return result


# ---------------------------------------------------------------------------
# ENDPOINT: affiliate-raportti (admin)
# ---------------------------------------------------------------------------
@app.get("/api/admin/affiliate-report")
def affiliate_report(request: Request):
    """Per luojakoodi: rekisteroityneet tilit + leimatut tilaukset.

    🔴 MIKSI. Wolfy kysyi 16.8: "how would i know if someone has come from me
    or not? Will it show on my account?" Vastaus oli EI: attribuutio elaa
    Stripen tilausmetadatassa, luojilla ei ole tilia meilla, eika mitaan
    luojanakymaa ole. Lupasimme kolmelle luojalle 30 % provision ja annoimme
    heille linkin, mutta emme mitaan tapaa nahda tuloksia - eika Villellakaan
    ollut muuta keinoa kuin selata Stripea kasin.

    Kaksi lukua, ja ne mittaavat ERI asioita:

      signups  = tilit joilla raw_user_meta_data.ref == koodi. Syntyy
                 rekisteroitymishetkella. Ilmaisen ikkunan aikana TAMA on
                 ainoa luku joka liikkuu, koska kukaan ei maksa.
      stamped  = Stripe-tilaukset joilla metadata.affiliate == koodi. Tama on
                 se luku josta provisio lasketaan.

    🔴 signups on SYSTEMAATTISESTI ALAKANTTIIN eika sita saa esittaa
    "linkin klikkauksina". Ref luetaan selaimen localStoragesta
    rekisteroitymishetkella, joten jos joku klikkaa X:n webviewissa ja luo
    tilin Chromessa, han ei nay tassa lainkaan vaikka tuli luojalta. Luku on
    siis alaraja, ei mittaus. Sama koskee mobiilia: appin signUp ei kirjoita
    refia ollenkaan.

    ADMIN_TOKEN-portin takana kuten muutkin admin-reitit.
    """
    require_admin(request)
    fresh = (request.query_params.get("fresh") or "").lower() in ("1", "true", "yes")
    tally = _affiliate_tally(fresh=fresh)
    return {
        "codes": tally["codes"],
        "total_accounts_scanned": tally["total_accounts_scanned"],
        "sources_ok": tally["sources_ok"],
        "caveat": AFFILIATE_CAVEAT,
    }


# ---------------------------------------------------------------------------
# ENDPOINT: ilmaisikkunan seuranta (admin)
# ---------------------------------------------------------------------------
# Ikkuna avattiin tuotantoon 16.8.2026. Paiva on kovakoodattu tarkoituksella:
# se on HISTORIAN kirjaus eika konfiguraatio, ja jos se olisi env, sen
# siirtaminen muuttaisi jalkikateen sita mita "ikkunan aikana" tarkoittaa.
FREE_WINDOW_OPENED = "2026-08-16"


def _supabase_users() -> Optional[list[dict]]:
    """Kaikki tilit Supabasen admin-API:sta, tai None jos haku ei onnistunut.

    🔴 None EI OLE tyhja lista. Sama oppi kuin `_affiliate_tally`ssa:
    epaonnistunut haku nayttaisi "nolla kayttajaa" ja se on vaite eika
    lukuvirhe. Sivutuskaton tayttyminen on myos "ei tietoa", koska luku
    olisi silloin vaillinainen.
    """
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        return None
    headers = {"apikey": SUPABASE_SERVICE_ROLE_KEY,
               "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}"}
    out: list[dict] = []
    try:
        for page in range(1, 41):  # 40 x 200 = 8000 tilia
            r = requests.get(f"{SUPABASE_URL}/auth/v1/admin/users",
                             params={"page": page, "per_page": 200},
                             headers=headers, timeout=15)
            if r.status_code != 200:
                print(f"[free-window] Supabase sivu {page} -> {r.status_code}")
                return None
            users = (r.json() or {}).get("users") or []
            out.extend(users)
            if len(users) < 200:
                return out
        return None  # katto tayteen: luku olisi vaillinainen
    except Exception as e:
        print(f"[free-window] Supabase-haku epaonnistui: {e}")
        return None


def _paid_user_ids(user_ids: list[str]) -> Optional[dict[str, set[str]]]:
    """Ketka annetuista tileista maksavat, ja mita kautta.

    Palauttaa {"web": {...}, "app": {...}} tai None jos haku epaonnistui.
    `app` = `profiles.is_premium` ILMAN web-tilausta, eli store-osto.

    🔴 MIKSI NAMA EROTELLAAN. Luojan provisio maksetaan vain sivulla
    tehdyista ostoista: store-ostot eivat kulje meidan checkoutimme kautta
    eika niissa ole mitaan mista attribuution voisi lukea. Jos ne
    laskettaisiin samaan lukuun, raportti nayttaisi luojalle tuloa jota
    han ei saa, ja meille konversion joka ei ole hanen ansiotaan
    laskutettavissa. Ero on siis rahaa eika kosmetiikkaa.
    """
    if not user_ids or not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        return {"web": set(), "app": set()}
    key = SUPABASE_SERVICE_ROLE_KEY
    headers = {"apikey": key, "Authorization": f"Bearer {key}"}
    web: set[str] = set()
    prem: set[str] = set()
    try:
        # PostgREST `in.()` menee URLiin, joten lista pilkotaan. 100 id:ta
        # per kutsu pitaa URLin selvasti alle palvelinten rajojen.
        for i in range(0, len(user_ids), 100):
            chunk = user_ids[i:i + 100]
            ids = ",".join(chunk)
            r = requests.get(
                f"{SUPABASE_URL}/rest/v1/web_subscriptions"
                f"?user_id=in.({ids})&select=user_id,status",
                headers=headers, timeout=20)
            if r.status_code != 200:
                print(f"[cohort] web_subscriptions -> {r.status_code}")
                return None
            for row in r.json() or []:
                if row.get("user_id"):
                    web.add(row["user_id"])
            r2 = requests.get(
                f"{SUPABASE_URL}/rest/v1/profiles"
                f"?id=in.({ids})&is_premium=is.true&select=id",
                headers=headers, timeout=20)
            if r2.status_code != 200:
                print(f"[cohort] profiles -> {r2.status_code}")
                return None
            for row in r2.json() or []:
                if row.get("id"):
                    prem.add(row["id"])
        return {"web": web, "app": prem - web}
    except Exception as e:
        print(f"[cohort] haku epaonnistui: {e}")
        return None


@app.get("/api/admin/affiliate-cohort")
def affiliate_cohort(request: Request):
    """Luojan linkista tullut tili -> ostiko han myohemmin. (admin)

    🔴 MIKSI TAMA ON ERI RAPORTTI KUIN `affiliate-report`. Siella `signups`
    ja `stamped` ovat kaksi ERI POPULAATIOTA eivatka sama joukko kahdessa
    vaiheessa: ihminen voi olla `stamped`issa olematta koskaan
    `signups`issa (nappaili koodin checkoutissa ilman etta ref-tagia
    koskaan kirjoitettiin) ja painvastoin. Niiden jakaminen keskenaan
    antaisi konversioprosentin joka ei tarkoita mitaan.

    Tama laskee sen ketjun jota ilmaisikkuna varten tarvitaan: tili jolla
    ON luojan ref, ja onko sama tili sittemmin maksanut.

    Store-ostot eritellaan omaksi luvukseen. Ne EIVAT ole luojalle
    maksettavia (ehdot: web-maksut), mutta ne kertovat paljonko konversiota
    valuu attribuution ulkopuolelle.
    """
    require_admin(request)
    users = _supabase_users()
    if users is None:
        raise HTTPException(status_code=503,
                            detail="Could not read the account list just now. "
                                   "This is not zero accounts.")

    by_code: dict[str, list[str]] = {}
    for u in users:
        ref = _clean_affiliate_ref((u.get("user_metadata") or {}).get("ref"))
        if ref and u.get("id"):
            by_code.setdefault(ref, []).append(u["id"])

    everyone = [uid for ids in by_code.values() for uid in ids]
    paid = _paid_user_ids(everyone)
    if paid is None:
        raise HTTPException(status_code=503,
                            detail="Could not read subscriptions just now. "
                                   "This is not zero paid accounts.")

    codes = {}
    for code, ids in sorted(by_code.items()):
        w = sum(1 for i in ids if i in paid["web"])
        a = sum(1 for i in ids if i in paid["app"])
        codes[code] = {
            "signups": len(ids),
            "signups_paid_on_web": w,
            "signups_paid_in_app_only": a,
            # Konversio lasketaan VAIN sivumaksuista, koska vain ne ovat
            # attribuoitavissa ja vain niista maksetaan provisio.
            "conversion_pct": round(100 * w / len(ids), 1) if ids else None,
        }

    return {
        "window": {"opened": FREE_WINDOW_OPENED,
                   "ends_utc": FREE_PREMIUM_UNTIL_DEFAULT,
                   "active": free_premium_window_active()},
        "codes": codes,
        "caveat": (
            "This is the sign-up cohort, not the same thing as the stamped "
            "count in the affiliate report: a reader who typed the code at "
            "checkout without ever carrying the tag is not in here. "
            "signups_paid_in_app_only is not payable to the creator, because "
            "store purchases do not go through our checkout and carry no "
            "attribution. Nobody is expected to appear in the paid columns "
            "before the free window closes."
        ),
    }


@app.get("/api/admin/free-window-report",
         description="Accounts created during the free window, measured against the daily median of the fourteen days before it. Requires an admin token.")
def free_window_report(request: Request):
    """Montako tilia on luotu ilmaisikkunan aikana, ja palasiko kukaan.

    🔴 MITA TAMA MITTAA JA MITA EI. Ikkuna ei kirjoita mitaan: se on puhdas
    lukuoperaatio kolmessa portissa eika `is_premium`-lippua kaanneta.
    Siksi "lunastusta" ei ole olemassa tapahtumana jota voisi laskea.
    Lahin mitattava asia on TILIN LUONTI, koska tilin tekeminen on ainoa
    asia jonka premiumin saaminen taman ikkunan aikana vaatii.

    `returned` on paras kaytettavissa oleva merkki siita etta joku myos
    KAYTTI sita: hän kirjautui uudelleen luontinsa jalkeen. Se ei ole
    todiste premium-nakymän avaamisesta - sita emme logita per kayttaja
    emmeka ala logittamaan, koska se olisi uusi henkilotietovirta yhden
    luvun vuoksi.

    Vertailukohta on `baseline_per_day`: ikkunaa EDELTAVIEN 14 vuorokauden
    mediaani. Ilman sita "4 tilia tanaan" ei kerro yhtaan mitaan.
    """
    require_admin(request)
    users = _supabase_users()
    if users is None:
        raise HTTPException(status_code=503,
                            detail="Could not read the account list just now. "
                                   "This is not zero accounts.")

    daily: dict[str, int] = {}
    for u in users:
        day = (u.get("created_at") or "")[:10]
        if day:
            daily[day] = daily.get(day, 0) + 1

    opened = FREE_WINDOW_OPENED
    since = [u for u in users if (u.get("created_at") or "") >= opened]
    returned = [u for u in since
                if u.get("last_sign_in_at")
                and u["last_sign_in_at"] > (u.get("created_at") or "")]

    # Baseline: 14 vrk ennen ikkunaa. Nollapaivat lasketaan mukaan, koska
    # niiden pudottaminen nostaisi vertailutasoa ja piilottaisi nousun.
    start = (datetime.fromisoformat(opened) - timedelta(days=14)).date()
    end = datetime.fromisoformat(opened).date()
    before = []
    d = start
    while d < end:
        before.append(daily.get(d.isoformat(), 0))
        d += timedelta(days=1)
    before.sort()
    n = len(before)
    baseline = (before[n // 2] if n % 2 else (before[n // 2 - 1] + before[n // 2]) / 2) if n else None

    return {
        "window": {
            "opened": opened,
            "ends_utc": FREE_PREMIUM_UNTIL_DEFAULT,
            "active": free_premium_window_active(),
        },
        "total_accounts": len(users),
        "accounts_since_window": len(since),
        "returned_since_window": len(returned),
        "with_creator_ref": sum(
            1 for u in since if (u.get("user_metadata") or {}).get("ref")),
        "baseline_per_day_before_window": baseline,
        "daily": dict(sorted(daily.items())[-30:]),
        "caveat": (
            "The window writes nothing, so there is no claim event to count. "
            "accounts_since_window counts sign-ups, which is the only thing "
            "getting premium requires right now. returned_since_window is a "
            "proxy for actually using it: the account signed in again after "
            "it was created. Neither number proves a premium view was opened."
        ),
    }


# ---------------------------------------------------------------------------
# ENDPOINT: luojan oma raportti (luojan omalla tokenilla)
# ---------------------------------------------------------------------------
@app.get("/api/creator/report")
def creator_report(request: Request):
    """Yhden luojakoodin luvut sille tilille jolle koodi on annettu.

    🔴 MIKSI TAMA ON ERI ENDPOINT KUIN ADMIN-RAPORTTI. Wolfy kysyi 16.8:
    "how would i know if someone has come from me or not? Will it show on my
    account?" Vastaus oli EI. Admin-raportti vastaa samaan kysymykseen mutta
    palauttaa KAIKKI koodit, eli sita ei voi antaa yhdellekaan luojalle:
    yksi luoja nakisi toisen luojan luvut. Tama reitti lukee koodin
    KUTSUJAN OMASTA tilista, joten kutsuja ei voi valita mita katsoo.

    Paasyn ehto on `raw_user_meta_data.creator_code`, joka asetetaan kasin
    (POST /api/admin/creator-code). Ei uutta saraketta eika migraatiota.

    EI KOSKAAN asiakkaiden sahkoposteja, nimia eika yksittaisia tilauksia -
    vain summia. Luojalle riittaa "montako", eika meilla ole oikeutta antaa
    asiakkaan henkilotietoja kolmannelle osapuolelle.

    🔴 LUKU VOI OLLA `null`, EIKA SE OLE SAMA KUIN NOLLA. Jos Supabase- tai
    Stripe-haku epaonnistuu, palautamme null emmeka 0:aa. Nolla on vaite
    ("kukaan ei tullut"), null on rehellinen ("emme saaneet luettua").
    """
    token = _bearer_from_request(request)
    user_id = _verify_supabase_token(token) if token else None
    if not user_id:
        raise HTTPException(status_code=401, detail="Sign in to view this page.")

    code = _account_creator_code(user_id)
    if not code:
        raise HTTPException(
            status_code=403,
            detail="This account is not linked to a creator code. Email "
                   "hello@goaliq.app and we will link it.")

    tally = _affiliate_tally(only=code)
    counts = tally["codes"].get(code) or {}
    supa_ok = tally["sources_ok"]["supabase"]
    stripe_ok = tally["sources_ok"]["stripe"]

    return {
        "code": code,
        # null = lukua ei saatu luettua. Klientti EI saa renderoida sita 0:na.
        "signups": (counts.get("signups", 0) if supa_ok else None),
        "stamped": (counts.get("stamped", 0) if stripe_ok else None),
        "statuses": (counts.get("statuses") or {}) if stripe_ok else None,
        "sources_ok": tally["sources_ok"],
        "commission_pct": 30,
        # Ikkunan aikana kukaan ei maksa, eli `stamped` EI VOI liikkua ennen
        # tata paivaa. Ilman tata riviä nolla nayttaisi epaonnistumiselta.
        "free_window": {
            "active": free_premium_window_active(),
            "ends_utc": FREE_PREMIUM_UNTIL_DEFAULT,
        },
        "caveat": AFFILIATE_CAVEAT,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# ENDPOINT: luojakoodin kytkeminen tiliin (admin)
# ---------------------------------------------------------------------------
class CreatorCodeRequest(BaseModel):
    email: str
    # null / "" = irrota koodi tililta (luoja lopettaa, ks. creators.html
    # "Either of us can stop").
    code: Optional[str] = None


@app.post("/api/admin/creator-code")
def set_creator_code(req: CreatorCodeRequest, request: Request):
    """Kytke luojakoodi tiliin sahkopostin perusteella (ADMIN_TOKEN).

    Ilman tata koodin asettaminen olisi kasityota Supabasen dashboardissa,
    ja `raw_user_meta_data`n kasin editointi ylikirjoittaa herkasti `ref`in -
    eli luojan oma attribuutio katoaisi sina hetkena kun hanet tehdaan
    luojaksi. Tama polku LUKEE metadatan, muuttaa yhden avaimen ja kirjoittaa
    kokonaisuuden takaisin.
    """
    require_admin(request)
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        raise HTTPException(status_code=503, detail="Supabase is not configured.")

    email = (req.email or "").strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail="email is required")
    code = _clean_affiliate_ref(req.code) if req.code else None
    if req.code and not code:
        raise HTTPException(
            status_code=400,
            detail="code must be 2-32 chars of A-Z, 0-9, _ or - (it is "
                   "uppercased and must match the Stripe promotion code)")

    key = SUPABASE_SERVICE_ROLE_KEY
    headers = {"apikey": key, "Authorization": f"Bearer {key}",
               "Content-Type": "application/json"}

    user = None
    page = 1
    while page <= 40:
        r = requests.get(f"{SUPABASE_URL}/auth/v1/admin/users",
                         params={"page": page, "per_page": 200},
                         headers=headers, timeout=15)
        if r.status_code != 200:
            raise HTTPException(status_code=502,
                                detail=f"Supabase lookup failed ({r.status_code})")
        users = (r.json() or {}).get("users") or []
        if not users:
            break
        for u in users:
            if (u.get("email") or "").strip().lower() == email:
                user = u
                break
        if user or len(users) < 200:
            break
        page += 1

    if not user:
        raise HTTPException(
            status_code=404,
            detail="No account with that email. The creator has to create an "
                   "account at pro.goaliq.app first.")

    meta = dict(user.get("user_metadata") or {})
    previous = _clean_affiliate_ref(meta.get("creator_code"))
    if code:
        meta["creator_code"] = code
    else:
        meta.pop("creator_code", None)

    r2 = requests.put(f"{SUPABASE_URL}/auth/v1/admin/users/{user['id']}",
                      json={"user_metadata": meta}, headers=headers, timeout=15)
    if r2.status_code not in (200, 201):
        raise HTTPException(status_code=502,
                            detail=f"Supabase update failed ({r2.status_code}): "
                                   f"{r2.text[:200]}")
    _AFFILIATE_TALLY_CACHE.clear()
    print(f"[creator] {email} creator_code {previous!r} -> {code!r}")
    return {"email": email, "user_id": user["id"],
            "creator_code": code, "previous": previous,
            # Ref-kentta on eri asia; palautetaan todisteeksi ettei se katosi.
            "ref": _clean_affiliate_ref(meta.get("ref"))}


# ---------------------------------------------------------------------------
# ENDPOINT: Beat the model — päätösten gradaus (admin-eräajo)
# ---------------------------------------------------------------------------
@app.post("/api/admin/grade-decisions",
          description="Grade locked predictions from finished gameweeks. Idempotent. Requires an admin token.")
def grade_decisions(request: Request):
    """Gradaa lukitut päätökset valmiilta kierroksilta (Beat the model V1).

    Määrittely: goaliq-app/cos-reports/beat-the-model-maarittely-2026-07-29.md.
    Kutsutaan fpl-data-refresh-workflowista päivittäin; idempotentti, koska
    gradatut rivit ohitetaan (graded_at is null -haku) ja trigger estää
    uudelleengradauksen. Klientti ei koskaan gradaa itseään — tämä ajaa
    service-roolilla ja on ADMIN_TOKEN-portin takana kuten clear-cache.
    """
    require_admin(request)
    from src.models.fpl_grade import (
        NOTE_NO_ENTRY, fetch_live_points, finished_gws, grade_one,
        make_picks_fetchers,
    )

    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        raise HTTPException(status_code=503, detail="Supabase env missing")
    sb_headers = {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }

    done = finished_gws()
    if not done:
        return {"graded": 0, "skipped": 0, "gws": []}

    # Gradaamattomat päätökset valmiilta kierroksilta. PostgREST in-lista.
    gw_list = ",".join(str(g) for g in sorted(done))
    rows = requests.get(
        f"{SUPABASE_URL}/rest/v1/fpl_decisions"
        f"?graded_at=is.null&gw=in.({gw_list})"
        f"&select=id,user_id,gw,kind,model_choice,user_choice,followed",
        headers=sb_headers, timeout=30,
    ).json()
    if not isinstance(rows, list) or not rows:
        return {"graded": 0, "skipped": 0, "gws": sorted(done)}

    # entry-ID:t kerralla (poikkeamien gradaus tarvitsee ne).
    user_ids = sorted({r["user_id"] for r in rows})
    entry_by_user: dict[str, int] = {}
    for i in range(0, len(user_ids), 100):
        chunk = ",".join(user_ids[i:i + 100])
        prof = requests.get(
            f"{SUPABASE_URL}/rest/v1/profiles?id=in.({chunk})"
            f"&select=id,fpl_entry_id",
            headers=sb_headers, timeout=30,
        ).json()
        for p in prof if isinstance(prof, list) else []:
            if isinstance(p.get("fpl_entry_id"), int):
                entry_by_user[p["id"]] = p["fpl_entry_id"]

    graded = skipped = 0
    live_by_gw: dict[int, dict] = {}
    fetchers_by_gw: dict[int, tuple] = {}
    now_iso = datetime.now(timezone.utc).isoformat()
    for r in rows:
        gw = r["gw"]
        if gw not in live_by_gw:
            live_by_gw[gw] = fetch_live_points(gw)
            fetchers_by_gw[gw] = make_picks_fetchers(gw)
        fetch_captain, fetch_transfers = fetchers_by_gw[gw]
        model_pts, user_pts, note = grade_one(
            r["kind"], r.get("model_choice") or {}, r.get("user_choice") or {},
            bool(r["followed"]), live_by_gw[gw],
            entry_by_user.get(r["user_id"]), fetch_captain, fetch_transfers,
        )
        patch = requests.patch(
            f"{SUPABASE_URL}/rest/v1/fpl_decisions?id=eq.{r['id']}",
            headers=sb_headers, timeout=15,
            json={"graded_at": now_iso, "model_points": model_pts,
                  "user_points": user_pts, "grade_note": note},
        )
        if patch.status_code in (200, 204):
            graded += 1
        else:
            skipped += 1
            print(f"[grade] FAILED id={r['id']} status={patch.status_code} "
                  f"body={patch.text[:150]}")
    return {"graded": graded, "skipped": skipped, "gws": sorted(done)}


# ---------------------------------------------------------------------------
# ENDPOINT: PUSH-NOTIF — toimituskohteet + tokenin siivous (admin-eräajo)
# ---------------------------------------------------------------------------
# Spec: goaliq-app/cos-reports/push-notif-spec-2026-08-13.md (vaiheet b+c).
#
# MIKSI TÄMÄ ON OLEMASSA: scripts/push_dispatch.py ajetaan GitHub-runnerilla
# (se tarvitsee repon, koska idempotenssimarkkeri committoidaan). Vaihtoehto
# olisi ollut viedä SUPABASE_SERVICE_ROLE_KEY GitHub-secretiksi — koko kannan
# kirjoitusoikeus CI:hin, jotta voidaan lukea yksi taulu. Render pitää avainta
# jo hallussaan ja ADMIN_TOKEN on jo repo-secret, joten liitos tehdään täällä
# ja runner saa vain sen mitä lähetys vaatii. Sama kaava kuin grade-decisions.
class PushTokenDeleteRequest(BaseModel):
    token: str = Field(min_length=10, max_length=255)


@app.get("/api/admin/push-targets",
         description="Push tokens with premium flag and watchlist attached. Requires an admin token.")
def push_targets(request: Request):
    """Push-tokenit premium-lipulla ja watchlistilla liitettynä.

    Liitos tehdään täällä eikä runnerilla, jotta runner ei näe profiles-
    taulua lainkaan (se sisältää is_premium- ja fpl_entry_id-kentät koko
    käyttäjäkunnasta).
    """
    require_admin(request)
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        raise HTTPException(status_code=503, detail="Supabase env missing")
    sb_headers = {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
    }
    rows = requests.get(
        f"{SUPABASE_URL}/rest/v1/push_tokens"
        f"?select=expo_token,user_id,platform,locale,"
        f"opted_in_deadline,opted_in_price,opted_in_picks",
        headers=sb_headers, timeout=30,
    ).json()
    if not isinstance(rows, list):
        return {"targets": [], "n": 0}

    # Premium + watchlist vain niille riveille joilla on tili. Anon-laitteet
    # saavat pelkän ilmaisen deadline-kanavan (migraation otsikkokommentti).
    user_ids = sorted({r["user_id"] for r in rows if r.get("user_id")})
    premium: set[str] = set()
    watchlists: dict[str, list] = {}
    for i in range(0, len(user_ids), 100):
        ids = ",".join(f'"{u}"' for u in user_ids[i:i + 100])
        prof = requests.get(
            f"{SUPABASE_URL}/rest/v1/profiles?id=in.({ids})"
            f"&select=id,is_premium,fpl_prefs",
            headers=sb_headers, timeout=30,
        ).json()
        for p in prof if isinstance(prof, list) else []:
            if p.get("is_premium"):
                premium.add(str(p["id"]))
            prefs = p.get("fpl_prefs") or {}
            wl = prefs.get("watchlist") if isinstance(prefs, dict) else None
            if isinstance(wl, list):
                watchlists[str(p["id"])] = wl

    targets = []
    for r in rows:
        uid = str(r["user_id"]) if r.get("user_id") else None
        targets.append({
            **r,
            "is_premium": bool(uid and uid in premium),
            "watchlist": watchlists.get(uid or "", []),
        })
    return {"targets": targets, "n": len(targets)}


@app.post("/api/admin/push-token-delete",
          description="Delete a push token that Expo reported as unregistered. Idempotent. Requires an admin token.")
def push_token_delete(req: PushTokenDeleteRequest, request: Request):
    """Poista token (Expon DeviceNotRegistered). Idempotentti.

    Hiljainen siivous: appin poistanut laite palauttaa DeviceNotRegisteredin
    ikuisesti, ja siivoamaton taulu kasvaisi kuolleista tokeneista joille
    lähetetään joka kierros.
    """
    require_admin(request)
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        raise HTTPException(status_code=503, detail="Supabase env missing")
    resp = requests.delete(
        f"{SUPABASE_URL}/rest/v1/push_tokens",
        params={"expo_token": f"eq.{req.token}"},
        headers={"apikey": SUPABASE_SERVICE_ROLE_KEY,
                 "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
                 "Prefer": "return=minimal"},
        timeout=15,
    )
    return {"deleted": resp.status_code in (200, 204)}


# ---------------------------------------------------------------------------
# STRIPE: Checkout-session ja webhook
# ---------------------------------------------------------------------------

def _auto_promo_discount() -> list[dict] | None:
    """Esitaytetty tarjouskoodi Checkoutiin, tai None.

    🔴 MITATTU VIKA 15.8. Landing myi "€17.50 first year, enter EARLY30 at
    checkout", mutta Checkout avautui 25,00 euroon ja alennus vaati etta
    kayttaja klikkaa "Anna tarjouskoodi" ja kirjoittaa koodin itse. Luvattu
    hinta ei siis ollut se joka nakyy maksuhetkella.

    RATKAISU EI OLLUT TAMA MEKANISMI. Esitaytto olisi sulkenut
    `allow_promotion_codes`in, ja luojakoodit (DAZ, WOLFY, ROWAN) syotetaan
    kasin — se olisi katkaissut kumppanien attribuution hiljaa. Villen paatos
    oli poistaa EARLY30 kaikilta pinnoilta, jolloin ristiriita katosi
    poistamalla LUPAUS eika alennusta esitayttamalla. Koodin `times_redeemed`
    oli 0, eli se ei ollut tuottanut yhtaan kauppaa.

    Mekanismi jaa tanne kaytettavaksi jos joskus halutaan kampanja jossa
    linkki kantaa koodin. Asettamattomana se on inertti.

    Se osuu tasan siihen kohtaan jossa pudotus on mitattu: 8 web-checkoutia,
    0 kauppaa, ja 5/6 poistui ENNEN sahkopostikentan tayttamista. Hinta on
    ensimmainen asia jonka he nakivat.

    ARVO TULEE YMPARISTOSTA, ei koodista: `STRIPE_AUTO_PROMO_CODE` on Stripen
    promotion_code-ID (`promo_...`). Asettamaton -> entinen kaytos
    (`allow_promotion_codes=True`), eli muutos ei voi rikkoa mitaan ennen kuin
    joku tietoisesti kytkee sen paalle. `discounts` ja
    `allow_promotion_codes` ovat Stripessa toisensa poissulkevia.
    """
    code = (os.environ.get("STRIPE_AUTO_PROMO_CODE") or "").strip()
    if not code.startswith("promo_"):
        return None
    return [{"promotion_code": code}]


class CheckoutRequest(BaseModel):
    """Request for creating a Stripe Checkout session."""
    user_id: str = Field(..., description="Supabase user UUID")
    email: str = Field(..., description="User email. Stripe sends the receipt here.")


class CheckoutResponse(BaseModel):
    checkout_url: str
    session_id: str


@app.post("/api/checkout", response_model=CheckoutResponse,
          description="Create a Stripe Checkout session for a premium subscription started in the mobile app.")
def create_checkout_session(req: CheckoutRequest):
    """
    Luo Stripe Checkout Session premium-tilaukselle.

    Mobiili-app kutsuu tätä → saa `checkout_url`:n → avaa selaimessa →
    kayttaja maksaa → Stripe lahettaa webhook:in joka päivittää
    Supabase profiles.is_premium = true.
    """
    if not stripe.api_key:
        raise HTTPException(
            status_code=500,
            detail="Stripe not configured (STRIPE_SECRET_KEY missing)",
        )
    if not STRIPE_PRICE_ID:
        raise HTTPException(
            status_code=500,
            detail="Stripe price not configured (STRIPE_PRICE_ID missing)",
        )

    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            payment_method_types=["card"],
            line_items=[{
                "price": STRIPE_PRICE_ID,
                "quantity": 1,
            }],
            customer_email=req.email,
            client_reference_id=req.user_id,  # Webhook käyttää tätä identifiointiin
            metadata={"user_id": req.user_id},
            # Kopioi user_id myös tilauksen metadataan, jotta cancel-eventti
            # tietää kenen premium poistetaan
            subscription_data={"metadata": {"user_id": req.user_id}},
            # Deep linkit takaisin mobiili-appiin
            success_url="goaliq://payment-success?session_id={CHECKOUT_SESSION_ID}",
            cancel_url="goaliq://payment-cancel",
            # 14.8 ATTRIBUUTIOAUKKO: tama endpoint on kuollut (vain docstring-viite),
            # mutta se hyvaksyi promokoodeja JA sen webhook (/api/webhook/stripe,
            # rivi ~2543) ei kutsu _stamp_affiliatea koskaan. Jos joku olisi
            # paatynyt tanne, luojan koodi olisi antanut 30 % alennuksen mutta
            # provisio olisi jaanyt kirjaamatta hiljaa — pahempi kuin ettei koodi
            # toimi lainkaan. Leimaus elaa vain /api/webhook/stripe-webissa.
            allow_promotion_codes=False,
        )
        return CheckoutResponse(
            checkout_url=session.url or "",
            session_id=session.id,
        )
    except stripe.error.StripeError as e:
        raise HTTPException(status_code=400, detail=f"Stripe error: {e.user_message or str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal error: {e}")


class PortalRequest(BaseModel):
    email: str = Field(..., description="User email, used to find the Stripe customer.")


class PortalResponse(BaseModel):
    portal_url: str


@app.post("/api/customer-portal", response_model=PortalResponse,
          description="Create a Stripe Customer Portal session where a subscriber can cancel, update a card or read invoices.")
def create_portal_session(req: PortalRequest):
    """
    Luo Stripe Customer Portal -session jossa kayttaja voi peruuttaa
    tilauksen, paivittaa kortin tai nahda laskut.

    Customer haetaan emailin perusteella (yksinkertaisin lahestymistapa MVP:lle —
    myohemmin voi tallentaa stripe_customer_id Supabaseen).
    """
    if not stripe.api_key:
        raise HTTPException(status_code=500, detail="Stripe not configured")

    try:
        # Etsi Stripe-customer emailin perusteella
        customers = stripe.Customer.list(email=req.email, limit=1)
        if not customers.data:
            raise HTTPException(
                status_code=404,
                detail=f"No Stripe customer found for {req.email}",
            )
        customer_id = customers.data[0].id

        # Luo portal-session
        session = stripe.billing_portal.Session.create(
            customer=customer_id,
            return_url="goaliq://subscription-managed",
        )
        return PortalResponse(portal_url=session.url)
    except stripe.error.StripeError as e:
        raise HTTPException(
            status_code=400,
            detail=f"Stripe error: {e.user_message or str(e)}",
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal error: {e}")


class WebCheckoutRequest(BaseModel):
    """Checkout request from the GoalIQ Pro web app."""
    plan: str = Field(..., description="'monthly' tai 'season'")
    origin: str = Field(
        "", description="SPA:n origin success/cancel-redirecteille "
                        "(validoidaan allowlistia vasten)")
    # 16.8: luojan ref (?ref=DAZ). Kulkee checkout-session metadataan, jotta
    # affiliate-attribuutio toimii myos silloin kun asiakas EI kayta koodia -
    # esim. kun han tuli GW1-GW3 ilmaisikkunan aikana ja maksaa vasta 12.9.
    # jalkeen taytta hintaa. Ks. _affiliate_code_from_session kohta 3.
    ref: str = Field("", description="Luojan ref-tunnus, esim. 'DAZ'")

    @field_validator("plan")
    @classmethod
    def _plan_known(cls, v: str) -> str:
        if v not in ("monthly", "season"):
            raise ValueError("plan must be 'monthly' or 'season'")
        return v


class WebCheckoutResponse(BaseModel):
    url: str


def _web_checkout_base_url(origin: str) -> str:
    """Validoi SPA-origin avointa redirectiä vastaan.

    Sallittu: WEB_CHECKOUT_ORIGINS-lista + https://*.pages.dev
    (Cloudflare Pages per-branch previewt). Muu → oletusorigin.
    """
    o = (origin or "").rstrip("/")
    if o in WEB_CHECKOUT_ORIGINS:
        return o
    if o.startswith("https://") and o.endswith(".pages.dev") and "/" not in o[8:]:
        return o
    return "https://pro.goaliq.app"


@app.post("/api/web/checkout", response_model=WebCheckoutResponse,
          description="Create a Stripe Checkout session for a signed-in web user. Identity comes from the Supabase token, never from the request body.")
def create_web_checkout_session(
    req: WebCheckoutRequest, request: Request
) -> WebCheckoutResponse:
    """GoalIQ Pro SPA (pro.goaliq.app, QUEUE #14) — Stripe Checkout -session.

    Staattinen SPA ei voi pitää STRIPE_SECRET_KEY:tä → session luodaan täällä.
    Auth = Supabase-JWT (Authorization: Bearer) → user_id + email varmistetaan
    Supabasesta, EI luoteta clientin lähettämiin arvoihin. Fulfillment =
    olemassa oleva webhook /api/webhook/stripe-web (metadata-muoto identtinen
    Streamlit-billingin kanssa: user_id + plan + source).
    """
    if not stripe.api_key:
        raise HTTPException(
            status_code=500,
            detail="Stripe not configured (STRIPE_SECRET_KEY missing)")
    price_id = (STRIPE_PRICE_SEASON_ID if req.plan == "season"
                else STRIPE_PRICE_MONTHLY_ID)
    if not price_id:
        raise HTTPException(
            status_code=500,
            detail=f"Stripe price not configured for plan '{req.plan}' "
                   f"(STRIPE_PRICE_{'SEASON' if req.plan == 'season' else 'MONTHLY'}_ID missing)")

    auth_header = request.headers.get("authorization", "")
    token = auth_header[7:] if auth_header.lower().startswith("bearer ") else ""
    supa_user = _get_supabase_user(token)
    if not supa_user:
        raise HTTPException(status_code=401, detail="Invalid or expired session")

    base = _web_checkout_base_url(req.origin)
    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            customer_email=supa_user.get("email"),
            client_reference_id=supa_user["id"],
            metadata={"user_id": supa_user["id"], "plan": req.plan,
                      "source": "pro-web",
                      **({"ref": ref} if (ref := _clean_affiliate_ref(req.ref))
                         else {})},
            success_url=f"{base}/?checkout=success&session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{base}/?checkout=cancelled",
            # Esitaytetty alennus jos ympäristö antaa sen, muuten kayttaja
            # syottaa koodin itse (entinen kaytos). Ks. _auto_promo_discount.
            **({"discounts": promo} if (promo := _auto_promo_discount())
               else {"allow_promotion_codes": True}),
        )
        return WebCheckoutResponse(url=session.url or "")
    except stripe.error.StripeError as e:
        raise HTTPException(status_code=400,
                            detail=f"Stripe error: {e.user_message or str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal error: {e}")


# #101: guest checkout -kevyt rate limit (per IP, in-memory). Estää botti-
# spämmin luomasta rajattomasti Stripe-sessioita auth-vapaalla endpointilla.
# Render = 1 prosessi → in-memory riittää; restart nollaa (harmiton).
_GUEST_CHECKOUT_HITS: dict[str, list[float]] = {}
_GUEST_CHECKOUT_LIMIT = 10       # sessioita / IP / tunti
_GUEST_CHECKOUT_WINDOW = 3600.0


def _guest_checkout_rate_ok(ip: str) -> bool:
    now = time.time()
    hits = [t for t in _GUEST_CHECKOUT_HITS.get(ip, [])
            if now - t < _GUEST_CHECKOUT_WINDOW]
    if len(hits) >= _GUEST_CHECKOUT_LIMIT:
        _GUEST_CHECKOUT_HITS[ip] = hits
        return False
    hits.append(now)
    _GUEST_CHECKOUT_HITS[ip] = hits
    return True


@app.post("/api/web/checkout/guest", response_model=WebCheckoutResponse,
          description="Create a Stripe Checkout session without an account. Stripe collects the email, and the account is created after payment.")
def create_guest_checkout_session(
    req: WebCheckoutRequest, request: Request
) -> WebCheckoutResponse:
    """#101 — suora osto ILMAN tiliä (konversiovuodon fix).

    Ei authia: Stripe Checkout kerää emailin + maksun yhdessä näkymässä.
    Tili provisioidaan maksun JÄLKEEN webhookissa (/api/webhook/stripe-web,
    metadata.source='pro-web-guest' → _provision_supabase_user + magic link).
    Kirjautuneen käyttäjän polku pysyy /api/web/checkout:issa (client_
    reference_id linkittää oston suoraan tiliin) — SPA valitsee endpointin.
    """
    if not stripe.api_key:
        raise HTTPException(
            status_code=500,
            detail="Stripe not configured (STRIPE_SECRET_KEY missing)")
    price_id = (STRIPE_PRICE_SEASON_ID if req.plan == "season"
                else STRIPE_PRICE_MONTHLY_ID)
    if not price_id:
        raise HTTPException(
            status_code=500,
            detail=f"Stripe price not configured for plan '{req.plan}' "
                   f"(STRIPE_PRICE_{'SEASON' if req.plan == 'season' else 'MONTHLY'}_ID missing)")

    client_ip = (request.client.host if request.client else "") or "unknown"
    if not _guest_checkout_rate_ok(client_ip):
        raise HTTPException(status_code=429,
                            detail="Too many checkout attempts, try again later")

    base = _web_checkout_base_url(req.origin)
    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            # EI customer_email/client_reference_id — Stripe kerää emailin,
            # webhook provisioi tilin sillä (account-after-payment).
            metadata={"plan": req.plan, "source": "pro-web-guest",
                      **({"ref": ref} if (ref := _clean_affiliate_ref(req.ref))
                         else {})},
            success_url=f"{base}/?checkout=success&guest=1&session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{base}/?checkout=cancelled",
            allow_promotion_codes=True,
        )
        return WebCheckoutResponse(url=session.url or "")
    except stripe.error.StripeError as e:
        raise HTTPException(status_code=400,
                            detail=f"Stripe error: {e.user_message or str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal error: {e}")


def _kasittele_stripe_tapahtuma(event: dict) -> None:
    """Stripe-webhookin KASITTELY, erotettu vastauspolulta (15.8.2026).

    🔴 MIKSI TAVALLINEN `def` EIKA `async def`. `_update_profile` kayttaa
    `requests.patch`-kutsua, joka on ESTAVA, ja se ajettiin aiemmin suoraan
    `async def`-endpointin sisalla 10 sekunnin timeoutilla. Se ei hidastanut
    vain webhookia vaan pysaytti koko tapahtumasilmukan KAIKILTA kayttajilta
    siksi ajaksi. Tavallisena funktiona Starlette ajaa taman saikeessa, joten
    esto ei koske silmukkaa.

    🔴 MITA TAMA MAKSAA, sanottuna suoraan. Kuittaus lahtee Stripelle ENNEN
    kuin Supabase on kirjoitettu. Jos kirjoitus epaonnistuu, Stripe ei yrita
    uudelleen, koska sanoimme jo 200. Vaihtokauppa on tietoinen: hidas vastaus
    saa Stripen merkitsemaan webhookin epaonnistuneeksi ja lopulta poistamaan
    sen kaytosta, ja se olisi hiljaisempi ja pahempi vika kuin yksittainen
    menetetty tapahtuma. Epaonnistuminen logataan nakyvasti, ja Stripen
    dashboardista tapahtuman voi toistaa kasin.
    """
    try:
        event_type = event["type"]
        obj = event["data"]["object"]

        if event_type == "checkout.session.completed":
            # Maksu onnistui — aktivoi premium ja nollaa cancel-tiedot
            user_id = obj.get("client_reference_id") or obj.get("metadata", {}).get("user_id")
            if user_id:
                print(f"[Stripe webhook] checkout.session.completed user_id={user_id}")
                _update_profile(user_id, {
                    "is_premium": True,
                    "subscription_cancel_at_period_end": False,
                    # current_period_end asetetaan kun subscription.updated saapuu
                })
            else:
                print(f"[Stripe webhook] checkout.session.completed but no user_id in payload")

        elif event_type == "customer.subscription.updated":
            # Subscription muuttui — esim. kayttaja peruutti, mutta access on
            # voimassa current_period_end -paivaan asti
            user_id = obj.get("metadata", {}).get("user_id")
            if user_id:
                from datetime import datetime, timezone

                # Stripe API:n eri versiot tallentavat cancel-tiedot eri tavoin:
                # - Vanhempi: cancel_at_period_end (boolean) + current_period_end juuressa
                # - Uudempi (2026+): cancel_at (timestamp) + current_period_end items[0]:ssa
                cancel_at_end_bool = obj.get("cancel_at_period_end", False)
                cancel_at_ts = obj.get("cancel_at")  # uudempi: timestamp tai None
                is_canceled = bool(cancel_at_end_bool) or bool(cancel_at_ts)

                # period_end: kokeile juurikenttaa, sitten cancel_at-timestampia,
                # viimeiseksi items[0].current_period_end (uudempi API)
                period_end_ts = obj.get("current_period_end") or cancel_at_ts
                if not period_end_ts:
                    items = obj.get("items") or {}
                    items_data = items.get("data") if isinstance(items, dict) else None
                    if items_data:
                        period_end_ts = items_data[0].get("current_period_end")

                period_end_iso = None
                if period_end_ts:
                    period_end_iso = datetime.fromtimestamp(
                        period_end_ts, tz=timezone.utc
                    ).isoformat()
                print(
                    f"[Stripe webhook] subscription.updated user_id={user_id} "
                    f"is_canceled={is_canceled} (bool={cancel_at_end_bool} ts={cancel_at_ts}) "
                    f"period_end={period_end_iso}"
                )
                _update_profile(user_id, {
                    "subscription_cancel_at_period_end": is_canceled,
                    "subscription_current_period_end": period_end_iso,
                })
            else:
                print(f"[Stripe webhook] subscription.updated no user_id sub_id={obj.get('id')}")

        elif event_type == "customer.subscription.deleted":
            # Tilaus peruttu/loppui — paivita is_premium=false
            user_id = obj.get("metadata", {}).get("user_id")
            if user_id:
                print(f"[Stripe webhook] subscription.deleted user_id={user_id}")
                # 🔒 NO-CLOBBER (#7): aktiivinen WEB-tilaus pitää premiumin.
                if _web_subscription_active(user_id):
                    print(f"[Stripe webhook] web-sub aktiivinen user_id={user_id} "
                          f"— is_premium säilyy (no-clobber)")
                else:
                    _update_profile(user_id, {
                        "is_premium": False,
                        "subscription_cancel_at_period_end": False,
                        "subscription_current_period_end": None,
                    })
            else:
                print(f"[Stripe webhook] subscription.deleted no user_id in metadata sub_id={obj.get('id')}")

        else:
            print(f"[Stripe webhook] ignored event_type={event_type}")
    except Exception as e:  # noqa: BLE001
        # Nakyvasti lokiin: kuittaus on jo lahtenyt, joten tama on ainoa jalki
        # siita etta tapahtuma jai kasittelematta.
        print(f"[Stripe webhook] KASITTELY EPAONNISTUI "
              f"type={event.get('type')} virhe={e!r}")


@app.post("/api/webhook/stripe")
async def stripe_webhook(request: Request, background_tasks: BackgroundTasks):
    """Vastaanottaa Stripen webhookit.

    Allekirjoituksen tarkistus on SYNKRONINEN eika sita saa siirtaa taustalle:
    se on turvaportti, ja vaarin allekirjoitettuun pyyntoon on vastattava
    400:lla. Vasta sen jalkeen kasittely siirtyy taustatehtavaan, jotta
    kuittaus lahtee Stripelle heti eika vasta Supabase-kirjoituksen jalkeen.
    """
    if not STRIPE_WEBHOOK_SECRET:
        # Secret ei viela konfiguroitu -> 200 OK jottei Stripe jaa retry-looppiin.
        return {"received": True, "warning": "STRIPE_WEBHOOK_SECRET not configured"}

    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    try:
        stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    event = json.loads(payload)
    background_tasks.add_task(_kasittele_stripe_tapahtuma, event)
    return {"received": True}


@app.post("/api/revenuecat/webhook",
          description="RevenueCat webhook for Google Play subscriptions.")
async def revenuecat_webhook(request: Request):
    """
    Vastaanottaa RevenueCat-webhookit (Google Play Billing). Paivittaa
    Supabase profiles.is_premium app_user_id:n (= Supabase auth user id)
    perusteella.

    Eventit:
      INITIAL_PURCHASE / RENEWAL / UNCANCELLATION / PRODUCT_CHANGE /
      NON_RENEWING_PURCHASE -> is_premium=True (access voimassa)
      CANCELLATION -> is_premium pysyy True, mutta merkitaan
        cancel_at_period_end=True (auto-renew pois; access jatkuu
        expiration-paivaan asti). Lopullinen access-poisto tulee
        EXPIRATION-eventissa.
      EXPIRATION -> is_premium=False (access paattyi)

    Autentikointi: RevenueCat lahettaa dashboardiin asetetun salaisuuden
    Authorization-headerissa. REVENUECAT_WEBHOOK_AUTH-env-muuttuja on
    pakollinen — jos puuttuu, webhook ei kirjoita mitaan.
    """
    if not REVENUECAT_WEBHOOK_AUTH:
        # Ei konfiguroitu — palauta 200 ettei RevenueCat retry-loopaa, mutta
        # ALA kirjoita Supabaseen (turvallinen oletus).
        return {"received": True, "warning": "REVENUECAT_WEBHOOK_AUTH not configured"}

    auth_header = request.headers.get("authorization", "")
    if auth_header != REVENUECAT_WEBHOOK_AUTH:
        raise HTTPException(status_code=401, detail="Invalid authorization")

    payload = await request.body()
    try:
        data = json.loads(payload)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid payload")

    event = data.get("event", {}) or {}
    event_type = event.get("type", "")

    # Resolvoi Supabase-auth-id alias-joukosta. Osto saattoi tapahtua anonyymilla
    # id:lla ennen logIn:ia → RevenueCat aliasoi anonyymin + Supabase-id:n samaan
    # subscriberiin. Webhook-eventin app_user_id voi olla kumpi tahansa: erityisesti
    # EXPIRATION kantaa usein original_app_user_id:n (= anonyymin), jolloin pelkka
    # app_user_id:n lukeminen skippasi downgraden vaarin. Kay lapi kaikki kandidaatit
    # (app_user_id, original_app_user_id, aliases) ja valitse ensimmainen ei-anonyymi.
    candidate_ids = [
        event.get("app_user_id") or "",
        event.get("original_app_user_id") or "",
        *(event.get("aliases") or []),
    ]
    user_id = next(
        (cid for cid in candidate_ids if cid and not cid.startswith("$RCAnonymousID:")),
        "",
    )

    # Ei yhtaan ei-anonyymia Supabase-id:ta → ei voida paivittaa profiilia.
    if not user_id:
        print(
            f"[RevenueCat webhook] skip event_type={event_type} "
            f"candidates={candidate_ids!r}"
        )
        return {"received": True}

    # expiration_at_ms = milloin access paattyy (renewal-/cancel-tieto).
    from datetime import datetime, timezone

    expiration_ms = event.get("expiration_at_ms")
    period_end_iso = None
    if expiration_ms:
        try:
            period_end_iso = datetime.fromtimestamp(
                int(expiration_ms) / 1000, tz=timezone.utc
            ).isoformat()
        except (ValueError, OSError, OverflowError):
            period_end_iso = None

    active_events = {
        "INITIAL_PURCHASE",
        "RENEWAL",
        "UNCANCELLATION",
        "PRODUCT_CHANGE",
        "NON_RENEWING_PURCHASE",
    }

    if event_type in active_events:
        print(f"[RevenueCat webhook] {event_type} user_id={user_id} period_end={period_end_iso}")
        _update_profile(user_id, {
            "is_premium": True,
            "subscription_cancel_at_period_end": False,
            "subscription_current_period_end": period_end_iso,
        })
        _stamp_premium_source(user_id, "revenuecat")
    elif event_type == "CANCELLATION":
        # Auto-renew pois paalta; access jatkuu expiration-paivaan asti.
        cancel_reason = event.get("cancel_reason", "")
        print(
            f"[RevenueCat webhook] CANCELLATION user_id={user_id} "
            f"reason={cancel_reason} period_end={period_end_iso}"
        )
        _update_profile(user_id, {
            "is_premium": True,
            "subscription_cancel_at_period_end": True,
            "subscription_current_period_end": period_end_iso,
        })
    elif event_type == "EXPIRATION":
        print(f"[RevenueCat webhook] EXPIRATION user_id={user_id}")
        # 🔒 NO-CLOBBER (#7): mobiilitilauksen päättyminen EI saa nollata
        # premiumia jos käyttäjällä on aktiivinen WEB-tilaus.
        if _web_subscription_active(user_id):
            print(f"[RevenueCat webhook] web-sub aktiivinen user_id={user_id} "
                  f"— is_premium säilyy (no-clobber)")
            _update_profile(user_id, {
                "subscription_cancel_at_period_end": False,
            })
        else:
            _update_profile(user_id, {
                "is_premium": False,
                "subscription_cancel_at_period_end": False,
                "subscription_current_period_end": None,
            })
    else:
        # BILLING_ISSUE, TEST, TRANSFER ym. — ei muutosta is_premiumiin.
        print(f"[RevenueCat webhook] ignored event_type={event_type} user_id={user_id}")

    return {"received": True}


@app.post("/api/delete-account")
async def delete_account(request: Request):
    """
    In-app tilin poisto (App Store 5.1.1(v) / Google Play). Kayttaja poistaa
    tilinsa + datansa itse appista ILMAN sahkopostia tai asiakaspalvelua.

    Autentikointi: kayttaja lahettaa oman Supabase-access-tokeninsa
    Authorization: Bearer -headerissa. Backend vahvistaa tokenin Supabasella
    ja poistaa VAIN tokenin omistaman kayttajan (ei voi poistaa muita).

    Vastaukset:
      200 {"deleted": true}  -> tili + data poistettu
      401                    -> token puuttuu / virheellinen / vanhentunut
      500                    -> poisto epaonnistui (config/Supabase-virhe)
    """
    auth_header = request.headers.get("authorization", "")
    token = auth_header[7:].strip() if auth_header.lower().startswith("bearer ") else ""
    if not token:
        raise HTTPException(status_code=401, detail="Missing bearer token")

    user_id = _verify_supabase_token(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    if not _delete_supabase_user(user_id):
        raise HTTPException(status_code=500, detail="Account deletion failed")

    return {"deleted": True}


@app.get("/api/revenuecat-config")
def revenuecat_config():
    """Diagnostiikka: onko RevenueCat-webhook konfiguroitu (ei paljasta arvoja)."""
    return {
        "webhook_auth_set": bool(REVENUECAT_WEBHOOK_AUTH),
        "supabase_url_set": bool(SUPABASE_URL),
        "supabase_service_role_key_set": bool(SUPABASE_SERVICE_ROLE_KEY),
    }


@app.get("/api/accuracy",
         description="The public accuracy record. Every prediction is logged before kick-off and graded once the match has been played, misses included.")
def model_accuracy(
    response: Response,
    include: str | None = Query(default=None, pattern="^(pending)$"),
):
    """Mallin verifioitava tarkkuus-track-record (#100).

    Palauttaa committatun aggregaatin (data/accuracy.json) — rolling N +
    all-time 1X2 %, exact-score %, kalibraatio, Brier, n + viimeisimmät
    ottelut rehellistä missit-näyttöä varten. Aggregaatti rakennetaan
    LOKAALISTI ajastetulla putkella (scripts/accuracy_pipeline.py) joka
    logaa pre-match-ennusteet ja reconciloi FT-tulokset; tämä endpoint vain
    lukee tiedoston (ei laskentaa pyynnössä). Jos tiedostoa ei ole vielä
    committattu → n=0-runko.

    Gambling-turvallinen: pelkkä mallin osumatarkkuus, EI vedonlyönti-ROI:ta.
    """
    from src.models.accuracy import load_aggregate, pending_rows
    # #103: ei välimuistitusta. Track record päivittyy palvelinpäästä (cron → main
    # → Render), ja mobiili (lib/api.ts fetchAccuracy) hakee bare-URL:n ilman
    # cache-bustia oletus-fetch-cachella → CDN/edge/OS/RN-HTTP-cache voi tarjota
    # vanhentunutta snapshotia (oire: stale n=48 ~17 h). no-store estää kaikki
    # välimuistitasot, korjaus tulee voimaan ilman app-buildia.
    response.headers["Cache-Control"] = "no-store"
    agg = load_aggregate()
    # #131: additiivinen pending-rivilista (?include=pending) mobiilin
    # "logged, awaiting result" -lohkoon (#129-web-pariteetti). Oletusvastaus
    # ennallaan → vanhat klientit eivät muutu; headline/by_competition
    # lasketaan edelleen vain gradatuista.
    if include == "pending":
        agg = {**agg, "pending_predictions": pending_rows()}
    return agg


@app.post("/api/webhook/stripe-web",
          description="Stripe webhook for checkouts made on the web.")
async def stripe_web_webhook(request: Request):
    """GoalIQ Pro (web/pro, pro.goaliq.app) -Checkoutin webhook.

    Kirjaa web-tilaukset Supabasen web_subscriptions-tauluun (EI kosketa
    mobiilin profiles.is_premium-polkuun — web-billing on erillinen tuote).
    Streamlit-appi tekee saman merkinnän myös success-redirect-verifyllä →
    tämä on idempotentti varmistuspolku (upsert per user_id).

    Sama konventio kuin /api/webhook/stripe: secret puuttuu → 200 + warning
    (Stripe ei jää retry-looppiin ennen kuin env on konfiguroitu).
    """
    from datetime import datetime, timezone

    if not STRIPE_WEB_WEBHOOK_SECRET:
        return {"received": True, "warning": "STRIPE_WEB_WEBHOOK_SECRET not configured"}

    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")
    try:
        stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEB_WEBHOOK_SECRET)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    event = json.loads(payload)
    event_type = event["type"]
    obj = event["data"]["object"]

    if event_type == "checkout.session.completed":
        metadata = obj.get("metadata") or {}
        user_id = obj.get("client_reference_id") or metadata.get("user_id")
        guest_email: str | None = None
        if not user_id and metadata.get("source") == "pro-web-guest":
            # #101 account-after-payment: guest maksoi ilman tiliä → provisioi
            # Supabase-käyttäjä Checkoutin keräämällä emaililla. Magic link
            # lähetetään fulfillmentin LOPUKSI (premium ehtii aktivoitua
            # ennen kuin käyttäjä klikkaa linkkiä).
            guest_email = ((obj.get("customer_details") or {}).get("email")
                           or obj.get("customer_email"))
            if guest_email:
                user_id = _provision_supabase_user(guest_email)
            if not user_id:
                # Maksu tuli mutta tiliä ei syntynyt → ÄLÄ palauta virhettä
                # (Stripe retryaa samaa eventtiä → provisiointi voi onnistua
                # seuraavalla yrityksellä vain jos palautetaan non-2xx).
                # Transientti Supabase-häiriö on todennäköisin syy → 500 =
                # Stripe retry exponential backoffilla on oikea toipumispolku.
                print(f"[Stripe web] GUEST provisiointi epäonnistui "
                      f"email={'set' if guest_email else 'MISSING'} — 500 → Stripe retry")
                raise HTTPException(status_code=500,
                                    detail="guest provisioning failed")
        if not user_id:
            print("[Stripe web] checkout.completed ilman user_id-referenssiä — ohitetaan")
            return {"received": True}
        plan = metadata.get("plan", "season")
        if obj.get("subscription"):
            # Molemmat planit recurring (kausi = 25 e/vuosi yearly, Villen
            # tarkennus 5.7) -> customer.subscription.updated tuo
            # current_period_endin, checkoutissa ei arvata.
            period_end = None
        else:
            # Defensiivinen fallback jos subscription-id puuttuu: kauden
            # loppu (30.6.) ostohetkestä.
            today = datetime.now(timezone.utc).date()
            year = today.year + 1 if today.month >= 7 else today.year
            period_end = f"{year}-06-30T23:59:59+00:00"
        _upsert_web_subscription({
            "user_id": user_id,
            "plan": plan,
            "status": "active",
            "current_period_end": period_end,
            "stripe_customer_id": obj.get("customer"),
            "stripe_subscription_id": obj.get("subscription"),
        })
        # AFF-ATTRIB (11.8): leimaa affiliate-koodi tilaukseen NYT, koska
        # `duration: once` -alennus irtoaa ensimmäisen laskun jälkeen. Tehdään
        # fulfillmentin jälkeen ja fail-softina: leima ei koskaan saa estää
        # premiumin aktivointia.
        if obj.get("subscription"):
            _affiliate = _affiliate_code_from_session(obj)
            if _affiliate:
                _code, _source = _affiliate
                _stamp_affiliate(obj["subscription"], _code, _source)
        # Cross-platform (#7): web-tilaus avaa myös MOBIILIAPPIN premiumin —
        # appi gateaa profiles.is_premium-kentällä ensisijaisesti.
        profile_fields = {"is_premium": True,
                          "subscription_cancel_at_period_end": False}
        if period_end:
            profile_fields["subscription_current_period_end"] = period_end
        _update_profile(user_id, profile_fields)
        _stamp_premium_source(user_id, "stripe_web")
        # #101: guest sai tilin → kirjautumislinkki mailiin (premium on jo
        # aktivoitu yllä → linkin klikkaus laskeutuu suoraan avattuun tilaan).
        if guest_email:
            _send_magic_link(guest_email)
    elif event_type == "customer.subscription.updated":
        # Vain web-tilausrivit päivittyvät (match stripe_subscription_id:llä —
        # mobiilin vanhat Stripe-subit eivät ole web_subscriptions-taulussa).
        # Uusissa Stripe-API-versioissa current_period_end on itemeillä.
        _items = (obj.get("items") or {}).get("data") or [{}]
        period_end = obj.get("current_period_end") or _items[0].get("current_period_end")
        period_end_iso = (datetime.fromtimestamp(period_end, timezone.utc).isoformat()
                          if period_end else None)
        fields = {"status": "active" if obj.get("status") == "active" else obj.get("status", "past_due")}
        if period_end_iso:
            fields["current_period_end"] = period_end_iso
        _upsert_web_subscription(fields, match={"stripe_subscription_id": obj["id"]})
        # Cross-platform: aktiivinen web-sub pitää profiles-premiumin tuoreena.
        if fields["status"] == "active":
            row = _get_web_subscription("stripe_subscription_id", obj["id"])
            if row and row.get("user_id"):
                pf = {"is_premium": True}
                if period_end_iso:
                    pf["subscription_current_period_end"] = period_end_iso
                _update_profile(row["user_id"], pf)
                _stamp_premium_source(row["user_id"], "stripe_web")
    elif event_type == "customer.subscription.deleted":
        _upsert_web_subscription({"status": "cancelled"},
                                 match={"stripe_subscription_id": obj["id"]})
        # 🔒 NO-CLOBBER: is_premium=False VAIN jos toisessa lähteessä (mobiili)
        # ei ole aktiivista tilausta. Mobiili-aktiivisuuden heuristiikka:
        # profiles.subscription_current_period_end on tulevaisuudessa JA eri
        # kuin tämän web-subin period_end (RC-renewal re-assertoi Truen joka
        # tapauksessa kuukausittain → virhe tähän suuntaan itsekorjautuva).
        row = _get_web_subscription("stripe_subscription_id", obj["id"])
        uid = (row or {}).get("user_id")
        if uid:
            if _web_subscription_active(uid):
                print(f"[Stripe web] deleted mutta toinen web-sub aktiivinen "
                      f"user_id={uid} — is_premium säilyy")
            elif _mobile_possibly_active(uid, (row or {}).get("current_period_end")):
                print(f"[Stripe web] deleted mutta mobiilitilaus näyttää "
                      f"aktiiviselta user_id={uid} — NO-CLOBBER, is_premium säilyy")
            else:
                _update_profile(uid, {
                    "is_premium": False,
                    "subscription_cancel_at_period_end": False,
                    "subscription_current_period_end": None,
                })
    else:
        # WEB-SUB-SYNC (13.8): nakyva jalki jokaisesta ohitetusta eventista.
        # Dashboard-tilaus ratkaisee mita tanne SAAPUU, ja tama rivi on ainoa
        # tapa nahda Render-lokista etta esim. subscription.updated alkoi
        # oikeasti tulla perille konfiguraatiomuutoksen jalkeen.
        print(f"[Stripe web] ohitettu event_type={event_type} (ei kasittelijaa)")

    return {"received": True}


@app.get("/api/fantasy",
         description="Clean sheet probability and a model based fixture difficulty rating for every Premier League club.")
def fantasy_phase0(
    response: Response,
    horizon: str = Query(
        default="6",
        description="How many gameweeks teams[].fixtures covers: 1-38, or 'all'.",
    ),
    league: str = Query(
        default="fpl",
        description="Fantasy-liiga: 'fpl' (oletus) tai 'spl' (Saudi Pro League).",
    ),
):
    """FPL Phase 0 — clean sheet -% + mallipohjainen FDR per PL-joukkue/GW (free-tier).

    Palauttaa committatun projektion (data/fpl_projections_phase0.json).
    Projektio rakennetaan ajastetulla refresh-jobilla
    (scripts/build_fpl_phase0.py, sanity-gaten takana) — tämä endpoint vain
    lukee tiedoston, EI laskentaa pyynnössä (Render 0.5 vCPU -budjetti).
    Jos tiedostoa ei ole vielä committattu → available=False-runko.

    Sama no-store-perustelu kuin /api/accuracy (#103): refresh päivittyy
    palvelinpäästä, välimuistitasot eivät saa tarjota stalea snapshotia.

    27.7 HORISONTTI (kontrakti:
    goaliq-app/cos-reports/horizon-extension-contract-2026-07-27.md):
    tiedosto sisältää koko kauden; tämä rajaa sen pyydettyyn pituuteen.

    OLETUS 6 = TÄSMÄLLEEN NYKYINEN VASTAUS. Vanha klientti ei lähetä
    parametria eikä siis näe muutosta — laajennus on opt-in.

    `fixtures[]` (ticker) EI kasva horizonin mukana: se on payloadin raskain
    lohko (per ottelu xG + 1X2 + CS molemmille suunnille) eikä planneri
    tarvitse sitä kaukoviikoille. Ilman tätä rajausta `horizon=all` olisi
    ~800 kB; nyt se on murto-osa siitä.
    """
    from src.models.fpl_phase0 import PHASE0_PATHS, load_phase0
    response.headers["Cache-Control"] = "no-store"
    # SPL-laajennos (7.8): league-avain valitsee committatun projektion.
    # Oletus 'fpl' = täsmälleen entinen vastaus; tuntematon avain = 404
    # (EI hiljaista FPL-fallbackia — väärä liiga näyttäisi oikealta datalta).
    lg = (league or "fpl").strip().lower()
    if lg not in PHASE0_PATHS:
        raise HTTPException(status_code=404, detail=f"Unknown fantasy league '{league}'.")
    data = load_phase0(PHASE0_PATHS[lg])

    teams = data.get("teams")
    meta = data.get("meta")
    if not isinstance(teams, list) or not isinstance(meta, dict):
        return data  # available=False-runko tms. → ei rajausta

    next_gw = meta.get("next_gameweek")
    if next_gw is None:
        return data

    # Rajaus: 'all' = koko tiedosto, muuten 1-38 (clamp, ei 422 — kyseessä on
    # näkymän pituus eikä semanttinen virhe, ja vanhat klientit eivät saa
    # kaatua tuntemattomaan arvoon).
    raw = (horizon or "").strip().lower()
    if raw in ("all", "max", "full"):
        span = meta.get("horizon_max") or 38
    else:
        try:
            span = int(raw)
        except (TypeError, ValueError):
            span = 6
        span = max(1, min(38, span))

    gw_cut = next_gw + span - 1
    out_teams = []
    for t in teams:
        fx = [f for f in t.get("fixtures", []) if f.get("gw", 0) <= gw_cut]
        out_teams.append({**t, "fixtures": fx})

    # horizon_gw kertoo mitä TÄSSÄ vastauksessa on, ei mitä tiedostossa on.
    span_actual = max(
        (f["gw"] for t in out_teams for f in t["fixtures"]), default=next_gw - 1
    ) - next_gw + 1
    return {
        **data,
        "meta": {**meta, "horizon_gw": max(0, span_actual)},
        "teams": out_teams,
    }


@app.get("/api/fantasy/xp",
         description="Expected points per player per gameweek. Callers without premium get a capped list.")
def fantasy_xp(
    request: Request,
    response: Response,
    league: str = Query(
        default="fpl",
        description="Fantasy-liiga: 'fpl' (oletus) tai 'spl' (Saudi Pro League).",
    ),
    lang: str = Query(
        default="en",
        # Tuntematon arvo putoaa hiljaa englantiin: kieli ei ole resurssin
        # olemassaolo, joten 404 olisi vaara vastaus (vrt. `league`).
        description=(
            "Language for the WHY explanations: 'en' (default), 'es' or 'pt'. "
            "An unknown value falls back to English."
        ),
    ),
):
    """FPL Phase 1 — xP (expected points) per pelaaja per GW (premium-ydin).

    Palauttaa committatun projektion (data/fpl_xp_projections.json).
    Projektio rakennetaan ajastetulla refresh-jobilla (scripts/build_fpl_xp.py,
    sanity-gaten + walk-forward-ship-gaten takana) — tämä endpoint vain lukee
    tiedoston, EI laskentaa pyynnössä (Render 0.5 vCPU -budjetti).
    Jos tiedostoa ei ole committattu → available=False-runko.

    Premium-portitus hoidetaan frontendissä (backend palauttaa datan) —
    sama malli kuin /api/fantasy.

    26.7 PERF — POIKKEUS no-store-linjaan (vrt. /api/accuracy #103): tämä on
    ainoa iso payload (555 kB raakana, ~60 kB br) ja se haettiin uudelleen
    JOKA sivulatauksella, vaikka projektio päivittyy 3 h välein. Nyt:
      - `private` + `Vary: Authorization` — vastaus riippuu Bearer-tokenista
        (mask_xp_payload), joten jaettu välimuisti ei saa tallentaa sitä.
        `private` kieltää CDN/proxyn, `Vary` suojaa loputkin.
      - `max-age=300` — 5 min ikkunassa ei verkkokutsua lainkaan. Data on
        3 h vanhaa joka tapauksessa, joten viive ei tuo uutta epätarkkuutta.
        Saatavuuslippujen (Garner-case) kannalta 5 min on siedettävä; hard
        reload ohittaa välimuistin.
      - ETag `generated_at` + mask-tila → sen jälkeen ehdollinen pyyntö
        vastaa 304:llä eikä 60 kB:tä siirretä uudelleen.
    Mobiili (fetchXp) ja SPA hyötyvät molemmat ilman klienttimuutosta.
    """
    from src.models.fpl_xp import (
        WHY_DEFAULT_LANG, WHY_LANGS, XP_PATHS, attach_why, load_xp, why_stamp,
    )
    # SPL-laajennos (7.8): sama sopimus kuin /api/fantasy — oletus 'fpl' =
    # entinen vastaus, tuntematon avain = 404, ei hiljaista fallbackia.
    lg = (league or "fpl").strip().lower()
    if lg not in XP_PATHS:
        raise HTTPException(status_code=404, detail=f"Unknown fantasy league '{league}'.")
    payload = load_xp(XP_PATHS[lg])
    # Talteen ENNEN maskausta: kevyt valitsinpooli rakennetaan koko listasta.
    full_players = list(payload.get("players") or [])
    # Edge-sprint P0c: PREMIUM_ENFORCE=on + ei-premium -> typistetty teaser
    # (top-10 taysia riveja, meta.masked=true). Flagi off (default) -> tama
    # haara ei koskaan aja ja vastaus on bittitarkasti ennallaan.
    masked = False
    # SPL = TÄYSIN ILMAINEN (Villen linjaus 7.8): hankintakiila FPL-premiumiin
    # — RSL-analytiikkakenttä on tyhjä ja maksupotentiaali pieni, arvo on
    # huomiossa; "free, not paid to promote" on myös etiikkakehyksen puhtain
    # muoto. Premium-flippi = poista lg-ehto tästä (yksi rivi).
    if lg != "spl" and payload.get("players") and not is_premium_request(request):
        payload = mask_xp_payload(payload)
        masked = True
    # WHY-THIS-PICK (14.8): selitys on premium-ominaisuus, joten se liitetään
    # VAIN maskaamattomaan vastaukseen. Maskattu teaser näyttää 10 täyttä
    # riviä; selityksen antaminen niille myisi featuren ilmaiseksi juuri sillä
    # pinnalla jolla se on tarkoitus myydä. SPL on kokonaan ilmainen eikä
    # kanna selityksiä (Villen 7.8 linjaus), joten se rajataan pois nimeltä.
    # WHY-LOKAALI (14.8): maksumuuri lupaa es/pt-lokaaleilla selityksen
    # ostajan omalla kielella. Tuntematon kieli putoaa englantiin hiljaa —
    # `league` on resurssi (tuntematon = 404), kieli on esitysmuoto.
    wl = (lang or WHY_DEFAULT_LANG).strip().lower()[:2]
    if wl not in WHY_LANGS:
        wl = WHY_DEFAULT_LANG
    why_tag = ""
    if lg == "fpl" and not masked:
        payload = attach_why(payload, lang=wl)
        why_tag = why_stamp()
    # FREE-DRAFT-POOL (14.8): draft rater ja fit checker tarvitsevat KAIKKI
    # pelaajat valitsimeensa, myos maalivahdit. Maskattu teaser (10 rivia)
    # ei sisaltanyt yhtaan maalivahtia -> ilmainen draft rater oli rikki
    # molemmilla pinnoilla. Pooli menee mukaan aina, jotta klientilla on yksi
    # koodipolku eivatka pinnat voi eriytya; se ei sisalla yhtaan xP-arvoa.
    payload = dict(payload)
    payload["pool"] = xp_pool_rows(full_players)
    # ETag erottaa maskatun ja täyden vastauksen: ilman mask-bittiä free-
    # käyttäjän 304 voisi validoida premium-rivit selaimen välimuistista.
    generated = str(payload.get("meta", {}).get("generated_at") or "0")
    # 5.8: SKEEMAVERSIO ETagiin. `generated_at` muuttuu vain kun projektio
    # ajetaan uusiksi, joten serve-timessa lisätty kenttä (xp_per_90) EI
    # invalidoi mitään: ehdollinen pyyntö validoisi vanhan vastauksen 304:llä
    # ja klientti näyttäisi uuden sarakkeen tyhjänä. Se luetaan rikkinäiseksi
    # ominaisuudeksi, ei vanhaksi välimuistiksi. Löytyi kuvasta, ei portista.
    # Nosta tätä aina kun rivin kenttäjoukko muuttuu ilman uutta projektiota.
    # 14.8 s3: `why` on serve-time-kenttä omasta tiedostostaan, joten sen
    # päivittyminen EI liikuta `generated_at`ia — ilman versionostoa ehdollinen
    # pyyntö validoisi vanhan vastauksen 304:llä ja selitys jäisi näkymättä.
    # 14.8 s4: `pool` on serve-time-kentta ilman uutta projektiota. Ilman
    # versionostoa free-kayttajan ehdollinen pyynto validoisi vanhan
    # vastauksen 304:lla ja valitsin jaisi tyhjaksi juuri niille joilla
    # vastaus on jo valimuistissa — eli niille jotka ovat kayneet sivulla.
    # 14.8 s5: pooliin lisattiin status + news (ilmainen watchlist tarvitsee
    # saatavuuslipun). Sama peruste kuin s4:lla — ilman nostoa rivi jaisi
    # ilman lippua tasan niille joilla vastaus on jo valimuistissa.
    # 14.8 s6: `why` sai `lang`-kentan (toteutunut kieli). Serve-time-kentta
    # ilman uutta projektiota -> ilman nostoa ehdollinen pyynto validoisi
    # vanhan vastauksen 304:lla ja kentta jaisi puuttumaan tasan niilta
    # joilla vastaus on jo valimuistissa.
    schema = "s6"
    # Liiga-avain ETagiin: ilman sitä fpl- ja spl-vastaukset voisivat
    # 304-validoitua ristiin samasta selainvälimuistista (sama URL-polku,
    # eri query) — sama vikaluokka kuin mask-bitin puuttuminen olisi.
    etag = 'W/"xp-{}-{}-{}-{}{}"'.format(
        lg, generated, "m" if masked else "f", schema,
        # KIELI ON OLTAVA ETagissa. Ilman sita es-kayttajan ehdollinen pyynto
        # validoituisi englanninkielisesta valimuistista ja han saisi
        # englantia — eli tasan sen vian jota tama commit korjaa, mutta
        # hiljaa ja vain valimuistin lampoisilla klienteilla.
        f"-{why_tag}-{wl}" if why_tag else "")
    cache_control = "private, max-age=300"
    inm = request.headers.get("if-none-match", "")
    if etag in [t.strip() for t in inm.split(",")]:
        return Response(
            status_code=304,
            headers={
                "ETag": etag,
                "Cache-Control": cache_control,
                "Vary": "Authorization",
            },
        )
    response.headers["Cache-Control"] = cache_control
    response.headers["ETag"] = etag
    response.headers["Vary"] = "Authorization"
    return payload


@app.get("/api/fantasy/price-watch",
         description="Price change forecast for FPL players, rising and falling.")
def fantasy_price_watch(response: Response):
    """FPL price watch (#43) — hinnanmuutosennuste (rising/falling) per pelaaja.

    Palauttaa committatun ennusteen (data/fpl_price_watch.json). Rakennetaan
    päivittäisellä fpl-data-refresh-cronilla (scripts/build_fpl_price_watch.py,
    sanity-gaten takana) — endpoint vain lukee tiedoston, EI laskentaa
    pyynnössä. Estimaatti, ei virallinen (disclaimer metassa). no-store kuten
    muut fantasy-endpointit.
    """
    from src.models.fpl_price_watch import load_price_watch
    response.headers["Cache-Control"] = "no-store"
    payload = load_price_watch()
    # 30.7 tarkkuusloki: julkinen gradaus payloadin kylkeen. Vain *_soon on
    # väite; säännöt lokin metassa. Puuttuva/tyhjä loki → ei accuracy-kenttää
    # (ei nollalla mainostamista).
    try:
        import json as _json
        acc_path = config.PROJECT_ROOT / "data" / "fpl_price_accuracy.json"
        if acc_path.exists():
            acc = _json.loads(acc_path.read_text(encoding="utf-8"))
            days = acc.get("days") or []
            if days:
                sp = sum(d["rise_soon_pred"] + d["fall_soon_pred"] for d in days)
                sh = sum(d["rise_soon_hits"] + d["fall_soon_hits"] for d in days)
                payload["accuracy"] = {
                    "days_graded": len(days),
                    "soon_predictions": sp,
                    "soon_hits": sh,
                    "soon_precision_pct": round(100.0 * sh / sp, 1) if sp else None,
                    "last_graded_at": days[-1]["graded_at"],
                    "rules": acc.get("meta", {}).get("rules"),
                }
    except Exception:
        pass  # loki ei saa kaataa price watchia
    return payload


@app.get("/api/fantasy/rate-team",
         description="Rate an FPL squad from its public entry ID and suggest transfers.")
def fantasy_rate_team(
    response: Response,
    entry: int | None = Query(default=None, description="Julkinen FPL entry-ID"),
    gw: int | None = Query(default=None, ge=1, le=38),
    players: str | None = Query(
        default=None,
        description="Pre-season fallback: 15 FPL element IDs, comma separated"),
    captain: int | None = Query(default=None),
    bank: float | None = Query(default=None, ge=0, le=100,
                               description="Pankki miljoonina (manual-moodi)"),
    ft: int = Query(default=1, ge=0, le=5,
                    description="Vapaat siirrot (#63: 0 -> hold_verdict "
                                "laskee -4 hitin siirron nettoon)"),
):
    """FPL rate-my-team (#34): tuo joukkue julkisella entry-ID:llä (tai 15
    pelaaja-ID:llä ennen kautta) → xP-pohjainen tiimiarvio (percentiili vs
    satunnaisotos laillisia budjettijoukkueita) + kapteeni- ja siirtosuositukset.
    #63: transfers.hold_verdict = eksplisiittinen hold/transfer-kanta
    (hit-tietoinen netto vs 2.0 xP -kynnys).

    Lukee saman committatun xP-projektion kuin /api/fantasy/xp (ei laskentaa
    mallipolulla); FPL-haut cachetetaan 10 min. Ei kirjautumista/salasanoja.
    """
    from src.models.fpl_rate_team import RateTeamError, rate_team
    response.headers["Cache-Control"] = "no-store"
    player_ids: list[int] | None = None
    if players:
        try:
            player_ids = [int(x) for x in players.split(",") if x.strip()]
        except ValueError:
            raise HTTPException(status_code=400,
                                detail="players must be comma-separated integers")
    if not player_ids and entry is None:
        raise HTTPException(status_code=400,
                            detail="Provide either entry or players.")
    try:
        return rate_team(entry=entry, gw=gw, players=player_ids,
                         captain=captain, bank=bank, ft=ft)
    except RateTeamError as e:
        raise _http_from_rate_team_error(e)


def _http_from_rate_team_error(e) -> HTTPException:
    """RateTeamError -> HTTPException, koneluettava `code` headeriin.

    28.7: `code` mukaan vastaukseen ADDITIIVISESTI. `detail` sailyy
    merkkijonona, joten jo julkaistut klientit (mobiili 1.0.3, SPA) lukevat
    sen ennallaan; uudet osaavat haarautua koodilla ilman virheviestin
    merkkijonovertailua.

    PI-16b (28.7): tama oli aiemmin inline VAIN rate-teamissa, joten planner,
    kapteenirankkeri ja plan-chains pudottivat koodin hiljaa -> niiden UI ei
    voinut erottaa "vaara ID:ta" ja "FPL ei ole viela julkaissut kokoonpanoja"
    toisistaan, ja koko esikausi nayttyi umpikujana. Yksi paikka, kaikki
    joukkuepohjaiset tyokalut.
    """
    if getattr(e, "code", None):
        return HTTPException(
            status_code=e.status_code,
            detail=e.detail,
            headers={"X-GoalIQ-Error-Code": e.code},
        )
    return HTTPException(status_code=e.status_code, detail=e.detail)


def _parse_id_csv(raw: str, label: str) -> list[int]:
    try:
        return [int(x) for x in raw.split(",") if x.strip()]
    except ValueError:
        raise HTTPException(status_code=400,
                            detail=f"{label} must be comma-separated integers")


@app.get("/api/fantasy/fit",
         description="Lock one to three players and get the best squad that still fits the budget and the FPL squad rules, plus the gap to the model own pick.")
def fantasy_fit(
    response: Response,
    locked: str = Query(..., description="One to three FPL element IDs, comma separated"),
):
    """#155 Fit checker: lukitse 1-3 pakkopelaajaa → paras laillinen runko
    niiden ympärille (horisontti-xP, sama ahne heuristiikka kuin #50-optimi)
    + delta vs mallin vapaa optimibudjettijoukkue. Ei entry-ID:tä, ei
    kirjautumista (PI-13: toimii go-live-hetkellä). Lukee committatun
    projektion, ei laskentaa mallipolulla."""
    from src.models.fpl_fit import fit_squad
    from src.models.fpl_rate_team import RateTeamError
    response.headers["Cache-Control"] = "no-store"
    try:
        return fit_squad(_parse_id_csv(locked, "locked"))
    except RateTeamError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)


@app.get("/api/fantasy/model-squad",
         description="The squad the model would pick, used to prefill the comparison slot. Same source as the fit checker, so the numbers cannot drift apart.")
def fantasy_model_squad(response: Response):
    """1.8: Joukkue 2 -vertailuslotin "mallin runko" -esitäyttö (mobiili+web).
    Palauttaa SAMAN vapaan optimirungon jota rate-teamin benchmark, fit checker
    ja /fpl/model-xi käyttävät (free_optimum → yksi optimoija, luvut eivät voi
    eriytyä; ks. fpl_fit-docstring 29.7). Lukee committatun projektion, ei
    laskentaa mallipolulla. Ei entry-ID:tä, ei kirjautumista."""
    from src.models.fpl_rate_team import (
        POS_NAME, RateTeamError, build_context, free_optimum)
    response.headers["Cache-Control"] = "no-store"
    try:
        xp_data, _bootstrap, pool, _pool_by_id = build_context()
        free = free_optimum(pool, str(xp_data["meta"].get("generated_at")))
        if not free["xi"] or len(free["bench"]) != 4:
            raise HTTPException(status_code=503,
                                detail="Model squad unavailable.")
        def _out(p: dict) -> dict:
            return {"id": p["id"], "web_name": p["web_name"],
                    "team_short": p["team_short"],
                    "pos": POS_NAME[p["element_type"]]}
        return {
            "meta": {
                "generated_at": xp_data["meta"].get("generated_at"),
                "horizon_gw": xp_data["meta"].get("horizon_gw"),
                "next_gameweek": xp_data["meta"].get("next_gameweek"),
                "xi_xp_horizon": round(free["xi_xp"], 2),
                "optimal_proven": bool(free["proven"]),
            },
            "players": [_out(p) for p in list(free["xi"]) + list(free["bench"])],
        }
    except RateTeamError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)


@app.get("/api/fantasy/model-race",
         description="Season race: the model locked squad against yours. The model figures are graded from FPL own scores, not recomputed on request.")
def fantasy_model_race(
    request: Request,
    response: Response,
    entry: int | None = Query(default=None, ge=1, le=99_999_999,
                              description="Julkinen FPL entry-ID (valinnainen)"),
):
    """Beat the Model V2 — Season race: mallin lukittu rivi vs sinun kautesi.

    Mallin luvut tulevat committatusta lokista (data/model_squad_gw_scores.json),
    joka on gradattu FPL:n omista pisteistä riville jonka git-historia todistaa
    lukituksi ennen deadlinea. Tämä endpoint EI laske pisteitä pyynnössä.

    FREE: kumulatiivinen ero + kierrosrivit (kilpailu on silmukan palkinto,
    V1-linjaus säilyy). PREMIUM: erittely siitä MISSÄ ero syntyi
    (kapteenivalinta, penkkipisteet, autosubit, siirtokustannukset).

    Esikausi: ennen ensimmäistä gradausta available=False + selite siitä
    milloin luvut tulevat — EI blank eikä arvattua nollaa (Hub-oppi #52).
    """
    import json as _json

    from src.models.fpl_model_race import build_race
    from src.models.fpl_rate_team import RateTeamError

    response.headers["Cache-Control"] = "no-store"
    log = None
    path = PROJECT_ROOT / "data" / "model_squad_gw_scores.json"
    if path.exists():
        try:
            log = _json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            log = None

    history = None
    if entry is not None:
        import src.models.fpl_rate_team as _rt
        try:
            history = _rt._fetch_fpl(f"/entry/{entry}/history/")
        except RateTeamError as e:
            if e.status_code == 404:
                raise HTTPException(
                    status_code=404,
                    detail=f"FPL entry {entry} was not found. Check the ID "
                           "(it is the number in your FPL points-page URL).")
            raise HTTPException(status_code=e.status_code, detail=e.detail)

    return build_race(log, history, premium=is_premium_request(request))


@app.get("/api/fantasy/plan",
         description="Transfer plan across several gameweeks for an existing squad. A documented heuristic rather than a global optimum.")
def fantasy_plan(
    request: Request,
    response: Response,
    entry: int | None = Query(default=None),
    gw: int | None = Query(default=None, ge=1, le=38),
    players: str | None = Query(default=None),
    bank: float | None = Query(default=None, ge=0, le=100),
    horizon: int = Query(default=3, ge=2, le=6),
    ft: int = Query(default=1, ge=0, le=5),
):
    """FPL transfer planner (#35): monen GW:n siirtosuunnitelma olemassa olevan
    xP-projektion päällä (greedy + jäljellä olevan horisontin arvo, hit -4,
    FT-carry max 5 — dokumentoitu heuristiikka, ei globaali optimi)."""
    from src.models.fpl_planner import plan_transfers
    from src.models.fpl_rate_team import RateTeamError
    response.headers["Cache-Control"] = "no-store"
    player_ids = _parse_id_csv(players, "players") if players else None
    try:
        payload = plan_transfers(entry=entry, gw=gw, players=player_ids,
                                 bank=bank, horizon=horizon, ft=ft)
    except RateTeamError as e:
        raise _http_from_rate_team_error(e)
    # Edge-sprint P0c: enforcement paalla ei-premium saa vain 1. GW:n askeleen
    # (taysi rivi -> renderointi ei kaadu). Default off -> ennallaan.
    if not is_premium_request(request):
        payload = mask_plan_payload(payload)
    return payload


@app.get("/api/fantasy/captain",
         description="Captain picks: the top three in your XI by gameweek expected points, plus a differential option.")
def fantasy_captain(
    request: Request,
    response: Response,
    entry: int | None = Query(default=None),
    gw: int | None = Query(default=None, ge=1, le=38),
    players: str | None = Query(default=None),
):
    """FPL captain-picker (#35): XI:n top-3 GW-xP:llä + differential-kapteeni
    (EO ≤ 10 %)."""
    from src.models.fpl_planner import captain_picker
    from src.models.fpl_rate_team import RateTeamError
    response.headers["Cache-Control"] = "no-store"
    player_ids = _parse_id_csv(players, "players") if players else None
    try:
        payload = captain_picker(entry=entry, gw=gw, players=player_ids)
    except RateTeamError as e:
        raise _http_from_rate_team_error(e)
    # Edge-sprint (additiivinen, defensiivinen): jos xP-projektio tuo
    # e_bonus/set_pieces-kentat (contract-data.md), liitetaan ne captain-
    # riveihin. Kenttien puuttuessa vastaus on tasmalleen ennallaan.
    try:
        from src.models.fpl_xp import load_xp
        extras = {p.get("id"): p for p in (load_xp().get("players") or [])
                  if p.get("e_bonus") is not None
                  or p.get("set_pieces") is not None}
        if extras:
            rows = list(payload.get("top3") or [])
            if payload.get("differential"):
                rows.append(payload["differential"])
            for row in rows:
                src = extras.get(row.get("id"))
                if not src:
                    continue
                if src.get("e_bonus") is not None:
                    row["e_bonus"] = src["e_bonus"]
                if src.get("set_pieces") is not None:
                    row["set_pieces"] = src["set_pieces"]
    except Exception:
        pass  # enrichment ei koskaan kaada peruspayloadia
    # 15.8: maskaus VASTA enrichmentin jalkeen, jotta free-rivi saa samat
    # e_bonus/set_pieces-kentat kuin premium — maski koskee rivien MAARAA,
    # ei niiden sisaltoa.
    if not is_premium_request(request):
        from api.premium import mask_captain_payload
        payload = mask_captain_payload(payload)
    return payload


@app.get("/api/fantasy/differentials")
def fantasy_differentials(
    response: Response,
    max_ownership: float = Query(default=10.0, gt=0, le=100),
    pos: str | None = Query(default=None),
):
    """FPL differential finder (#35): matala EO × korkea xP (FPL-API ownership
    + xP-projektio)."""
    from src.models.fpl_planner import differential_finder
    from src.models.fpl_rate_team import RateTeamError
    response.headers["Cache-Control"] = "no-store"
    try:
        return differential_finder(max_ownership=max_ownership, pos=pos)
    except RateTeamError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)


@app.get("/api/fantasy/value",
         description="Expected points per million, fixture swing, and the best pair of goalkeepers to rotate.")
def fantasy_value(
    response: Response,
    top_n: int = Query(default=20, ge=1, le=100),
    pairs_n: int = Query(default=10, ge=1, le=50),
):
    """FPL value/consistency + GK rotation pairs (#114): xP/£-ranking +
    fixture-swing + paras 2-vahdin CS%-rotaatio. Rakentuu xP-projektion ja
    phase0-CS%:n päälle — ei uutta dataputkea."""
    from src.models.fpl_rate_team import RateTeamError
    from src.models.fpl_value import value_and_gk
    response.headers["Cache-Control"] = "no-store"
    try:
        return value_and_gk(top_n_value=top_n, top_n_pairs=pairs_n)
    except RateTeamError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)


@app.get("/api/fantasy/xg-leaders",
         description="Top xG scorers over a rolling window. The response names the season the numbers come from.")
def fantasy_xg_leaders(
    response: Response,
    window: int = Query(default=5, ge=3, le=10),
    pos: str | None = Query(default=None, pattern="^(GKP|DEF|MID|FWD)$"),
    # 26.7: katto 100 -> 1000. Klientti tarjoaa nyt joukkue- ja
    # sijaintisuodattimet (pariteetti /fpl/xg-leaders-sivun kanssa), ja 100
    # rivilla joukkuesuodatin antaisi 3-5 pelaajaa per klubi eli olisi
    # kaytannossa hyodyton. Rankkaus on valmiiksi cachessa, ei laskentaa.
    top_n: int = Query(default=20, ge=1, le=1000),
):
    """#124: top xG-tekijät rolling-windowilla (FPLWolfy-ehdotus). Rankkaa
    committatusta nightly-cachesta (data/fpl_player_leaders.json) — meta
    kantaa basis-kauden + labelin (esikausi = 25/26-data, ei arvauksia)."""
    from src.models.fpl_leaders import load_leaders, rank_xg_leaders
    from src.models.fpl_rate_team import RateTeamError
    response.headers["Cache-Control"] = "no-store"
    try:
        return rank_xg_leaders(load_leaders(), window=window, pos=pos,
                               top_n=top_n)
    except RateTeamError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)


@app.get("/api/fantasy/defcon-leaders",
         description="Defensive contribution leaders: actions per game, hit rate and points over a rolling window.")
def fantasy_defcon_leaders(
    response: Response,
    window: int = Query(default=5, ge=3, le=10),
    pos: str | None = Query(default=None, pattern="^(DEF|MID|FWD)$"),
    top_n: int = Query(default=20, ge=1, le=400),
    basis: str = Query(default="recent", pattern="^(recent|season)$"),
):
    """#125: DefCon-tracker (FPLWolfy-ehdotus): DefCon-actionit/game +
    hit-rate % + pisteet rolling-windowilla. Kynnykset DEF 10 CBIT /
    MID+FWD 12 CBIRT (verifioitu virallisista säännöistä + datasta).

    basis=season (30.7, Villen idea): koko basis-kauden ranking per-GW-
    matriisin kausisummista — window ohitetaan. Esikaudella tämä on
    vakain basis (38 pelin hit-rate vs mielivaltainen viimeiset-N-häntä).
    top_n-katto nostettu 400:aan samalla (lista oli kova 20 → "vain 20
    pelaajaa" -havainto; matriisissa on 373 pelaajaa)."""
    from src.models.fpl_leaders import (load_defcon_gw, load_leaders,
                                        rank_defcon_leaders,
                                        rank_defcon_season)
    from src.models.fpl_rate_team import RateTeamError
    response.headers["Cache-Control"] = "no-store"
    try:
        if basis == "season":
            return rank_defcon_season(load_defcon_gw(), pos=pos, top_n=top_n)
        return rank_defcon_leaders(load_leaders(), window=window, pos=pos,
                                   top_n=top_n)
    except RateTeamError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)


@app.get("/api/fantasy/defcon-gw",
         description="Defensive contribution gameweek by gameweek for the season.")
def fantasy_defcon_gw(request: Request, response: Response):
    """Per-GW DefCon -matriisi (30.7): koko 25/26-kauden kierroskohtaiset
    DefCon-rivit nykykauden pelaajille (code-mappaus arkistoon). Builderi
    scripts/build_fpl_defcon_gw.py kirjoittaa tiedoston sanity-gaten takana —
    tämä endpoint vain lukee sen (Render 0.5 vCPU -budjetti).

    Meta kantaa mitatun vastustajaefektin (korrelaatio +0.026): frontend
    näyttää sen suoraan eikä myy fixture-kontekstia signaalina jota oma
    mittaus ei löydä. Payload ~240 kB → ETag + tunnin public-cache (data
    muuttuu vain kun builderi ajetaan, ei auth-riippuvaa sisältöä)."""
    from src.models.fpl_leaders import load_defcon_gw
    from src.models.fpl_rate_team import RateTeamError
    try:
        payload = load_defcon_gw()
    except RateTeamError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    generated = str(payload.get("meta", {}).get("generated_at") or "0")
    etag = 'W/"dcgw-{}"'.format(generated)
    cache_control = "public, max-age=3600"
    inm = request.headers.get("if-none-match", "")
    if etag in [t.strip() for t in inm.split(",")]:
        return Response(status_code=304, headers={
            "ETag": etag, "Cache-Control": cache_control})
    response.headers["Cache-Control"] = cache_control
    response.headers["ETag"] = etag
    return payload


@app.get("/api/fantasy/defcon-live")
def fantasy_defcon_live(
    response: Response,
    entry: int | None = Query(default=None, ge=1, le=99_999_999,
                              description="FPL entry ID (oma joukkue)"),
    ids: str | None = Query(default=None,
                            description="Vaihtoehto entrylle: pilkkulista element-ID:ita"),
):
    """DefCon-live (2.8): oman joukkueen defensive contribution KESKEN kierroksen.

    Ainoa live-pinta tuotteessa. FPL:n virallinen appi vei live-rankit 20.-21.7.
    featurepudotuksessa, mutta DefCon-kertyma on yha aukko: uusi pistesaanto,
    vaikea seurata ottelun aikana, ja meilla on jo koko DefCon-datamalli.

    Toisin kuin muut fantasy-endpointit tama EI lue committattua JSONia vaan
    hakee FPL:n live-feedin (60 s TTL prosessissa). Sama `defensive_contribution`
    -kentta kuin historiallisessa putkessa -> nakymat eivat voi olla eri mielta.

    Kierrosten valissa ja esikaudella: available=false + note, ei virhetta.
    """
    from src.models.fpl_defcon_live import load_defcon_live
    from src.models.fpl_rate_team import RateTeamError

    id_list: list[int] | None = None
    if ids:
        try:
            id_list = [int(x) for x in ids.split(",") if x.strip()][:20]
        except ValueError:
            raise HTTPException(status_code=400, detail="ids must be integers")
    if entry is None and not id_list:
        raise HTTPException(status_code=400, detail="Give either entry or ids.")

    response.headers["Cache-Control"] = "no-store"
    try:
        return load_defcon_live(entry_id=entry, ids=id_list)
    except RateTeamError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    except requests.RequestException as e:
        # Ylavirran katko ei saa nayttaa meidan bugilta.
        raise HTTPException(status_code=502, detail=f"FPL feed unavailable: {e}")


@app.get("/api/fantasy/compare")
def fantasy_compare(
    response: Response,
    players: str = Query(..., description="Two to four FPL element IDs, comma separated"),
):
    """FPL pelaajavertailu (#35): 2-4 pelaajan xP-komponenttierittely +
    hinta/EO/predicted minutes + suora kanta xP-erolla."""
    from src.models.fpl_planner import compare_players
    from src.models.fpl_rate_team import RateTeamError
    response.headers["Cache-Control"] = "no-store"
    try:
        return compare_players(_parse_id_csv(players, "players"))
    except RateTeamError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)


@app.get("/api/fantasy/career",
         description="Season by season FPL history for a public entry ID. Free, no paywall.")
def fantasy_career(
    response: Response,
    entry: int = Query(..., description="Julkinen FPL entry-ID"),
):
    """FPL career / season review (#55): urahistoria jakokorttia varten
    julkisella entry-ID:llä (past_seasons + summary + viimeisimmän kauden
    GW-erittely + GoalIQ-malliteaser #50-opti-baselinella).

    ILMAINEN, ei paywallia (jakelu-feature). FPL-haut kulkevat #34:n jaetun
    10 min TTL-cachen + #52-stale-fallbackin läpi. Esikaudella current on
    tyhjä → latest_season palautuu available=False + selite (past_seasons +
    summary palautuvat silti — EI blank/virhe). no-store kuten muut
    fantasy-endpointit.
    """
    from src.models.fpl_career import RateTeamError, career
    response.headers["Cache-Control"] = "no-store"
    try:
        return career(entry=entry)
    except RateTeamError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)


@app.get("/api/debug/seasons",
         description="Debug: the season formats the data source recognises for a league.")
def debug_seasons(league: str = Query(default="INT-World Cup")):
    """
    Listaa kaikki seasonit jotka soccerdata FBref tunnistaa annetulle liigalle.
    Auttaa selvittämään oikean season-formaatin.
    """
    try:
        import soccerdata as sd
        # available_leagues() palauttaa kaikki tuetut liigat
        all_leagues = sd.FBref.available_leagues()
        # Yritä luoda FBref-instanssi pelkalla liigalla -> tuottaa virheen jossa
        # season-vaatimukset näkyvät
        result = {"league": league, "league_valid": league in all_leagues}
        # Haetaan saatavilla olevat seasonit suoraan
        try:
            # Kokeile tehdä instanssi ilman seasonia — antaa default-listan
            inst = sd.FBref(leagues=[league])
            # _selected_seasons sisältää seasonit jotka instanssi tunnistaa
            seasons = inst.seasons if hasattr(inst, "seasons") else None
            if seasons is None and hasattr(inst, "_selected_seasons"):
                seasons = inst._selected_seasons
            result["available_seasons_default"] = list(seasons) if seasons else "?"
        except Exception as e:
            result["seasons_error"] = f"{type(e).__name__}: {str(e)[:300]}"
        return result
    except Exception as e:
        return {"error": f"{type(e).__name__}: {str(e)[:500]}"}


@app.get("/api/debug/load",
         description="Debug: try to load match data and return the exact error from each source.")
def debug_load(
    leagues: list[str] = Query(default=["INT-World Cup"]),
    seasons: list[str] = Query(default=["2022"]),
):
    """
    Debug-endpoint: yritä ladata otteludata ja palauta tarkat virheviestit
    per datalähde. Auttaa selvittämään miksi joku liiga ei toimi.
    """
    from src.data.loader import lataa_otteludata_yksityiskohtaisesti
    tulos = lataa_otteludata_yksityiskohtaisesti(leagues, seasons)
    return {
        "requested_leagues": leagues,
        "requested_seasons": seasons,
        "rows_loaded": int(len(tulos.data)),
        "successes_per_league": tulos.onnistui,
        "errors_per_league": tulos.virheet,
        "sample_columns": list(tulos.data.columns) if not tulos.data.empty else [],
    }


@app.get("/api/stripe-config",
         description="Diagnostics: whether Stripe is configured. Never returns keys.")
def stripe_config():
    """Diagnostiikka: tarkista että Stripe on konfiguroitu (älä paljasta avaimia)."""
    return {
        "secret_key_set": bool(stripe.api_key),
        "price_id_set": bool(STRIPE_PRICE_ID),
        "webhook_secret_set": bool(STRIPE_WEBHOOK_SECRET),
        "supabase_url_set": bool(SUPABASE_URL),
        "supabase_service_role_key_set": bool(SUPABASE_SERVICE_ROLE_KEY),
        # 11.8: PREMIUM_ENFORCE-tila jouduttiin päättelemään /api/fantasy/xp:n
        # payloadin koosta, eikä se päättely erota kolmea eri syytä toisistaan
        # (arvo väärin / deploy kesken / vastaus välimuistista). Luetaan samasta
        # funktiosta jota gate itse käyttää — ei uusintatoteutusta, koska silloin
        # diagnostiikka voisi olla eri mieltä kuin portti.
        # Ei paljasta salaisuutta: bool + raakamerkkijonon pituus, jolla näkee
        # onko kentässä esim. lainausmerkit ("on" = 4) ilman että arvo vuotaa.
        "premium_enforce": premium_enforce_on(),
        "premium_enforce_raw_len": len((os.getenv("PREMIUM_ENFORCE") or "").strip()),
    }
