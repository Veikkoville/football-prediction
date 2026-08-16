"""AFF-ATTRIB (11.8.2026): affiliate-koodin pysyva leima tilaukseen.

Miksi tama on olemassa: Ville lupasi Rowanille 30 % provision "for as long as
they stay subscribed". Kuponki `Wna8u6uO` on `duration: once`, joten alennus
IRTOAA tilaukselta ensimmaisen laskun jalkeen, eika Stripe enaa kerro etta juuri
tama uusiutuva tilaus tuli ROWAN-koodista. Ilman leimaa uusiutumisten laskenta
olisi kasin tehtava tasmays vanhoista laskuista — eli se joka unohtuu, ja se
huomattaisiin vasta kun kumppani kysyy miksi hanen maksunsa on liian pieni.

Leima kirjoitetaan `checkout.session.completed`-hetkella, koska se on ainoa
hetki jolloin yhteys on luettavissa.

Negatiivinen kontrolli on tassa pakollinen eika kohteliaisuus: ilman sita
testit lapaisisivat myos toteutuksella joka leimaa JOKAISEN tilauksen, jolloin
jokainen orgaaninen ostaja nayttaisi Rowanin tuomalta ja provisio laskettaisiin
liian suureksi.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time

SECRET = "whsec_test"


def _signed(payload: dict, secret: str = SECRET) -> tuple[bytes, str]:
    payload = {"id": "evt_test", "object": "event", "api_version": "2024-06-20",
               "created": int(time.time()), **payload}
    payload["data"]["object"].setdefault("object", "checkout.session")
    body = json.dumps(payload).encode()
    ts = int(time.time())
    sig = hmac.new(secret.encode(), f"{ts}.".encode() + body,
                   hashlib.sha256).hexdigest()
    return body, f"t={ts},v1={sig}"


def _session(**extra) -> dict:
    base = {
        "client_reference_id": "user-123",
        "metadata": {"plan": "season", "source": "pro-web"},
        "customer": "cus_x",
        "subscription": "sub_test",
        "payment_status": "paid",
    }
    base.update(extra)
    return {"type": "checkout.session.completed", "data": {"object": base}}


def _harness(monkeypatch):
    """Mockaa Supabase + Stripe-kirjoitukset, palauta leimauskutsujen lista."""
    import api.main as m
    monkeypatch.setattr(m, "STRIPE_WEB_WEBHOOK_SECRET", SECRET)
    monkeypatch.setattr(m, "_upsert_web_subscription",
                        lambda fields, match=None: True)
    monkeypatch.setattr(m, "_update_profile", lambda uid, fields: True)
    stamps: list[tuple[str, str]] = []
    # 16.8: leimaus kirjaa myos LAHTEEN ("promo" / "ref"). Talteen otetaan
    # kaikki kolme, jotta testi nakee jos lahde katoaa tai menee vaarin -
    # ilman sita `check_affiliate_attribution.py` ei voi erottaa ref-leimoja
    # kuponkilunastuksista ja menee punaiseksi oikeasta toiminnasta.
    monkeypatch.setattr(
        m, "_stamp_affiliate",
        lambda sub_id, code, source: stamps.append((sub_id, code, source)) or True)
    return stamps


def test_promo_code_expanded_object_is_stamped(client, monkeypatch):
    """Laajennettu promokoodi sessiossa -> leima."""
    stamps = _harness(monkeypatch)
    body, sig = _signed(_session(discounts=[
        {"promotion_code": {"id": "promo_1", "code": "ROWAN"}}]))
    r = client.post("/api/webhook/stripe-web", content=body,
                    headers={"stripe-signature": sig})
    assert r.status_code == 200
    assert stamps == [("sub_test", "ROWAN", "promo")]


def test_promo_code_as_id_is_resolved_and_stamped(client, monkeypatch):
    """Pelkka ID (`promo_...`) -> haetaan Stripesta ja leimataan.

    Tama on se polku joka rikkoutuisi hiljaa jos oletettaisiin etta payload on
    aina laajennettu: leima jaisi pois eika mikaan huutaisi.
    """
    import api.main as m
    stamps = _harness(monkeypatch)
    monkeypatch.setattr(m.stripe.PromotionCode, "retrieve",
                        staticmethod(lambda pid: {"id": pid, "code": "ROWAN"}))
    body, sig = _signed(_session(discounts=[{"promotion_code": "promo_1U3IGp"}]))
    r = client.post("/api/webhook/stripe-web", content=body,
                    headers={"stripe-signature": sig})
    assert r.status_code == 200
    assert stamps == [("sub_test", "ROWAN", "promo")]


def test_falls_back_to_subscription_discount(client, monkeypatch):
    """Sessiossa ei discountsia -> luetaan tilauksen oma discount.

    Webhookin payload ei ole aina laajennettu, mutta tilauksella alennus on
    talla hetkella viela kiinni.
    """
    import api.main as m
    stamps = _harness(monkeypatch)
    monkeypatch.setattr(m.stripe.Subscription, "retrieve",
                        staticmethod(lambda sid: {
                            "id": sid,
                            "discount": {"promotion_code": {"code": "ROWAN"}}}))
    body, sig = _signed(_session())
    r = client.post("/api/webhook/stripe-web", content=body,
                    headers={"stripe-signature": sig})
    assert r.status_code == 200
    assert stamps == [("sub_test", "ROWAN", "promo")]


def test_organic_purchase_is_not_stamped(client, monkeypatch):
    """NEGATIIVINEN KONTROLLI: ilman koodia ei leimaa.

    Ilman tata testia lapaisisi toteutus joka leimaa kaikki tilaukset, jolloin
    jokainen orgaaninen ostaja laskettaisiin kumppanin ansioksi.
    """
    import api.main as m
    stamps = _harness(monkeypatch)
    monkeypatch.setattr(m.stripe.Subscription, "retrieve",
                        staticmethod(lambda sid: {"id": sid, "discount": None}))
    body, sig = _signed(_session())
    r = client.post("/api/webhook/stripe-web", content=body,
                    headers={"stripe-signature": sig})
    assert r.status_code == 200
    assert stamps == []


def test_stamping_failure_does_not_break_fulfillment(client, monkeypatch):
    """Stripen virhe leimauksessa ei saa estaa premiumin aktivointia.

    Asiakas on jo maksanut. Puuttuva leima on korjattavissa jalkikateen
    ensimmaiselta laskulta, menetetty premium ei ole.
    """
    import api.main as m
    monkeypatch.setattr(m, "STRIPE_WEB_WEBHOOK_SECRET", SECRET)
    monkeypatch.setattr(m, "_upsert_web_subscription",
                        lambda fields, match=None: True)
    profiles: list[dict] = []
    monkeypatch.setattr(m, "_update_profile",
                        lambda uid, fields: profiles.append(fields) or True)

    def _boom(*a, **kw):
        raise RuntimeError("Stripe alhaalla")

    monkeypatch.setattr(m.stripe.Subscription, "modify", staticmethod(_boom))
    body, sig = _signed(_session(discounts=[
        {"promotion_code": {"id": "promo_1", "code": "ROWAN"}}]))
    r = client.post("/api/webhook/stripe-web", content=body,
                    headers={"stripe-signature": sig})
    assert r.status_code == 200
    assert profiles and profiles[0].get("is_premium") is True


def test_no_subscription_id_is_skipped(client, monkeypatch):
    """Kertaosto ilman tilausta ei yrita leimata (eika kaadu)."""
    stamps = _harness(monkeypatch)
    body, sig = _signed(_session(subscription=None))
    r = client.post("/api/webhook/stripe-web", content=body,
                    headers={"stripe-signature": sig})
    assert r.status_code == 200
    assert stamps == []
