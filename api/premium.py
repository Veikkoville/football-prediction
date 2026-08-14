"""Edge-sprint P0: admin-token-portti + Supabase-JWT premium-check + maskit.

Kaikki enforcement on PREMIUM_ENFORCE-env-flagin takana (default "off"):
kun off, is_premium_request() palauttaa AINA True -> yksikaan nykyinen
klientti ei muutu (regressiotestattu: /api/fantasy/xp byte-identtinen).

Premium-check (kun PREMIUM_ENFORCE=on):
  1. Authorization: Bearer <supabase access token> -header.
  2. Token verifioidaan Supabasen /auth/v1/user-endpointilla (sama kuvio
     kuin main.py:n _verify_supabase_token / _get_supabase_user — projektissa
     EI ole SUPABASE_JWT_SECRET-kaytantoa, kaytetaan user-endpoint-hakua).
  3. profiles.is_premium == true TAI web_subscriptions.status='active'
     (current_period_end NULL tai tulevaisuudessa) -> premium.
  4. Verkkovirhe premium-lookupissa -> fail-open (True): maksava kayttaja ei
     koskaan menetä dataa transientin Supabase-hairion takia (sama linja kuin
     _web_subscription_active main.py:ssa).

Tulokset cachetetaan 5 min tokenin sha256-avaimella (ei tokenia muistiin
selkotekstina; Render = 1 prosessi -> in-memory riittaa).
"""
from __future__ import annotations

import hashlib
import os
import threading
import time
from datetime import datetime, timezone

import requests
from fastapi import HTTPException, Request

_SUPABASE_TIMEOUT = 10
_PREMIUM_CACHE_TTL = 300.0
_PREMIUM_CACHE_MAX = 500
_PREMIUM_CACHE: dict[str, tuple[float, bool]] = {}
_PREMIUM_CACHE_LOCK = threading.Lock()

# Maskiparametrit (dokumentoitu cos-reports/edge-sprint/contract-api.md).
FREE_XP_TEASER_N = 10        # /api/fantasy/xp + xp.csv: top-N riveja freelle
FREE_PLAN_GWS = 1            # /api/fantasy/plan: montako GW:ta freelle
FREE_CHIP_WINDOWS = 3        # /api/fantasy/chip-ev: montako ikkunaa freelle
FREE_PLAN_CHAINS = 1         # /api/fantasy/plan-chains: montako ketjua freelle
FREE_EDGE_CAPTAINS = 2       # /api/fantasy/edge: kapteeniriveja freelle
FREE_EDGE_DIFFERENTIALS = 2
FREE_EDGE_TEMPLATE_RISKS = 1


def _env(name: str) -> str:
    return (os.getenv(name) or "").strip()


def premium_enforce_on() -> bool:
    """PREMIUM_ENFORCE=on/1/true/yes -> enforcement paalla. Default off."""
    return _env("PREMIUM_ENFORCE").lower() in ("on", "1", "true", "yes")


# ---------------------------------------------------------------------------
# Admin-portti (/api/admin/clear-cache)
# ---------------------------------------------------------------------------

def require_admin(request: Request) -> None:
    """X-Admin-Token-header verrataan ADMIN_TOKEN-enviin.

    ADMIN_TOKEN puuttuu ymparistosta -> 403 AINA (fail-closed: endpoint on
    kaytannossa pois paalta kunnes env on asetettu Renderiin).
    """
    admin_token = _env("ADMIN_TOKEN")
    if not admin_token:
        raise HTTPException(status_code=403,
                            detail="Admin endpoint is disabled "
                                   "(ADMIN_TOKEN not configured).")
    provided = (request.headers.get("x-admin-token") or "").strip()
    # Vakiaikainen vertailu (timing-side-channel-hygienia).
    import hmac
    if not provided or not hmac.compare_digest(provided, admin_token):
        raise HTTPException(status_code=403, detail="Invalid admin token.")


# ---------------------------------------------------------------------------
# Supabase-JWT-plumbing + premium-lookup
# ---------------------------------------------------------------------------

def _bearer_token(request: Request) -> str:
    auth = request.headers.get("authorization", "")
    return auth[7:].strip() if auth.lower().startswith("bearer ") else ""


def _supabase_headers(bearer: str) -> dict:
    key = _env("SUPABASE_SERVICE_ROLE_KEY")
    return {"apikey": key, "Authorization": f"Bearer {bearer}"}


def _verify_token_user_id(token: str) -> str | None:
    """Supabase /auth/v1/user kayttajan omalla tokenilla -> user_id / None.
    Sama mekanismi kuin api.main._verify_supabase_token (ei importata sielta,
    jottei synny circular importtia — main importaa taman moduulin)."""
    url = _env("SUPABASE_URL")
    if not url or not _env("SUPABASE_SERVICE_ROLE_KEY") or not token:
        return None
    resp = requests.get(f"{url}/auth/v1/user",
                        headers=_supabase_headers(token),
                        timeout=_SUPABASE_TIMEOUT)
    if resp.status_code != 200:
        return None
    return (resp.json() or {}).get("id") or None


def _profile_is_premium(user_id: str) -> bool:
    url = _env("SUPABASE_URL")
    key = _env("SUPABASE_SERVICE_ROLE_KEY")
    rows = requests.get(
        f"{url}/rest/v1/profiles?id=eq.{user_id}&select=is_premium",
        headers={"apikey": key, "Authorization": f"Bearer {key}"},
        timeout=_SUPABASE_TIMEOUT,
    ).json()
    return bool(rows and isinstance(rows, list) and rows[0].get("is_premium"))


def _web_subscription_active(user_id: str) -> bool:
    """Sama semantiikka kuin api.main._web_subscription_active: status=active
    ja current_period_end NULL tai tulevaisuudessa."""
    url = _env("SUPABASE_URL")
    key = _env("SUPABASE_SERVICE_ROLE_KEY")
    rows = requests.get(
        f"{url}/rest/v1/web_subscriptions?user_id=eq.{user_id}"
        f"&status=eq.active&select=current_period_end",
        headers={"apikey": key, "Authorization": f"Bearer {key}"},
        timeout=_SUPABASE_TIMEOUT,
    ).json()
    for r in rows if isinstance(rows, list) else []:
        end = r.get("current_period_end")
        if end is None:
            return True
        try:
            if datetime.fromisoformat(end) > datetime.now(timezone.utc):
                return True
        except ValueError:
            return True
    return False


def is_premium_request(request: Request) -> bool:
    """True jos kutsuja saa premium-payloadin.

    PREMIUM_ENFORCE=off -> aina True (nykytila; ei riko yhtaan klienttia).
    Enforcement paalla: Bearer-token -> Supabase-verify -> profiles.is_premium
    TAI aktiivinen web_subscriptions-rivi. Ei tokenia / invalid -> False.
    Supabase-verkkovirhe -> True (fail-open, ks. moduulidocstring).
    """
    if not premium_enforce_on():
        return True
    token = _bearer_token(request)
    if not token:
        return False

    cache_key = hashlib.sha256(token.encode()).hexdigest()
    now = time.time()
    with _PREMIUM_CACHE_LOCK:
        hit = _PREMIUM_CACHE.get(cache_key)
        if hit and now - hit[0] < _PREMIUM_CACHE_TTL:
            return hit[1]

    try:
        user_id = _verify_token_user_id(token)
        if not user_id:
            result = False
        else:
            result = _profile_is_premium(user_id) or \
                _web_subscription_active(user_id)
    except Exception as e:
        # Fail-open: transientti Supabase-hairio ei saa maskata maksavan
        # kayttajan dataa. Vaara-True on itsekorjautuva (TTL 5 min).
        print(f"[premium] lookup EXCEPTION (fail-open): {e}")
        return True

    with _PREMIUM_CACHE_LOCK:
        if len(_PREMIUM_CACHE) >= _PREMIUM_CACHE_MAX:
            _PREMIUM_CACHE.clear()  # karkea mutta riittava (500 tokenia)
        _PREMIUM_CACHE[cache_key] = (now, result)
    return result


# ---------------------------------------------------------------------------
# Maskit olemassa oleville endpointeille. Suunnitteluperiaate: maski on
# TYPISTYS, ei null-korvaus — kaikki jaljelle jaavat rivit ovat taysia ja
# tyypit sailyvat (mobiili renderoi esim. player.xp_per_gw.toFixed(1);
# null kaataisi, typistetty lista ei). Lisataan vain additiivinen
# meta.masked-lippu jota vanhat klientit eivat lue.
# ---------------------------------------------------------------------------

def mask_xp_payload(payload: dict) -> dict:
    """/api/fantasy/xp freelle: top-N pelaajaa xp_horizon_total-jarjestyksessa.
    Rivit ovat taysia (teaser) -> vanha renderointi ei kaadu."""
    players = list(payload.get("players") or [])
    players.sort(key=lambda p: float(p.get("xp_horizon_total") or 0.0),
                 reverse=True)
    meta = dict(payload.get("meta") or {})
    meta["masked"] = True
    meta["mask"] = (f"top {FREE_XP_TEASER_N} of {len(players)} players "
                    "(free preview - GoalIQ Premium unlocks the full list)")
    out = dict(payload)
    out["meta"] = meta
    out["players"] = players[:FREE_XP_TEASER_N]
    return out


# Kevyen valitsinpoolin kentat. TAHAN EI LISATA xP-kenttia: pooli menee myos
# maskatussa vastauksessa, ja arvojen lisaaminen myisi premium-ytimen
# ilmaiseksi. Sama linjaus kuin xP-teaserissa jo on: nimet nakyvat, arvot eivat.
XP_POOL_FIELDS = ("id", "web_name", "pos", "team_short", "price")


def xp_pool_rows(players: list[dict]) -> list[dict]:
    """Kevyt pelaajapooli draft-valitsimelle (14.8).

    MIKSI: 11.8 lisatty maski typistaa /api/fantasy/xp:n free-kayttajalle
    kymmeneen riviin. Mitattu 14.8 tuotannosta: ne kymmenen olivat MID 4 /
    DEF 4 / FWD 2 / GKP 0. Draft vaatii 2 GKP + 5 DEF + 5 MID + 3 FWD, joten
    maalivahtislotin lista oli tyhja ja lahetysnappi pysyi ikuisesti
    disabloituna — seka mobiilissa etta webissa, koska molemmat hakevat
    poolinsa samasta kutsusta. Backend vastasi 200 ja tsc oli vihrea: rikki
    oli tyhja lista eika virhe, joten yksikaan portti ei nahnyt sita.

    Maskia EI pureta — sen syy on patea. Valitsin saa oman listansa jossa on
    vain julkista FPL-bootstrap-tietoa (nimi, positio, seura, hinta) kaikille
    pelaajille, eika yhtaan mallin tuottamaa lukua.
    """
    out: list[dict] = []
    for p in players:
        if p.get("id") is None:
            continue
        out.append({k: p.get(k) for k in XP_POOL_FIELDS})
    return out


def mask_plan_payload(payload: dict) -> dict:
    """/api/fantasy/plan freelle: vain ensimmaisen GW:n suunnitelma-askel.
    plan[0] on taysi rivi -> renderointi (lista-iterointi) ei kaadu."""
    meta = dict(payload.get("meta") or {})
    meta["masked"] = True
    meta["mask"] = (f"first {FREE_PLAN_GWS} of {len(payload.get('plan') or [])}"
                    " gameweeks (free preview)")
    out = dict(payload)
    out["meta"] = meta
    out["plan"] = list(payload.get("plan") or [])[:FREE_PLAN_GWS]
    return out
