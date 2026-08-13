"""WEB-SUB-SYNC (13.8.2026): web_subscriptions pysyy Stripen tahdissa.

Tausta (Supabase-RO:n 1. ajo 12.8): webhook loi rivin
checkout.session.completed:ssa mutta rivi ei koskaan paivittynyt
(updated_at = created_at kaikilla, 5.8 paattynyt monthly nakyi yha
"active"). Kasittelijat subscription.updated/deleted OLIVAT olemassa —
juurisyy on etta dashboardin webhook-tilaus ei laheta niita eventteja.
Namat testit naulaavat kasittelijoiden kayttaytymisen, jotta kun eventit
alkavat saapua, ne tekevat oikean asian.

premium_source-leima: ERILLINEN _update_profile-kutsu tarkoituksella —
jos saraketta ei ole viela migratoitu, leiman kaatuminen EI saa estaa
is_premium-aktivointia (testattu erikseen).

Sama HMAC-allekirjoituskuvio kuin test_affiliate_attribution.py:ssa.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time

import pytest
from fastapi.testclient import TestClient

import api.main as m

SECRET = "whsec_test"


def _signed(payload: dict, secret: str = SECRET) -> tuple[bytes, str]:
    payload = {"id": "evt_test", "object": "event", "api_version": "2024-06-20",
               "created": int(time.time()), **payload}
    body = json.dumps(payload).encode()
    ts = int(time.time())
    sig = hmac.new(secret.encode(), f"{ts}.".encode() + body,
                   hashlib.sha256).hexdigest()
    return body, f"t={ts},v1={sig}"


class Harness:
    def __init__(self):
        self.upserts: list[tuple[dict, dict | None]] = []
        self.profile_updates: list[tuple[str, dict]] = []
        self.rows: dict[str, dict] = {}


@pytest.fixture
def h(monkeypatch) -> Harness:
    hh = Harness()
    monkeypatch.setattr(m, "STRIPE_WEB_WEBHOOK_SECRET", SECRET)
    monkeypatch.setattr(
        m, "_upsert_web_subscription",
        lambda fields, match=None: hh.upserts.append((fields, match)) or True)
    monkeypatch.setattr(
        m, "_update_profile",
        lambda uid, fields: hh.profile_updates.append((uid, fields)) or True)
    monkeypatch.setattr(
        m, "_get_web_subscription",
        lambda field, value: hh.rows.get(value))
    return hh


def _post(payload: dict):
    body, sig = _signed(payload)
    return TestClient(m.app).post(
        "/api/webhook/stripe-web", content=body,
        headers={"stripe-signature": sig})


def test_subscription_updated_paivittaa_statuksen_ja_period_endin(h):
    h.rows["sub_live1"] = {"user_id": "user-42"}
    r = _post({"type": "customer.subscription.updated",
               "data": {"object": {"id": "sub_live1", "status": "active",
                                   "current_period_end": 1789430400}}})
    assert r.status_code == 200
    fields, match = h.upserts[0]
    assert match == {"stripe_subscription_id": "sub_live1"}
    assert fields["status"] == "active"
    assert fields["current_period_end"].startswith("2026-09-")
    # Cross-platform: profiili pysyy tuoreena JA saa lahdeleiman.
    assert ("user-42", {"premium_source": "stripe_web"}) in h.profile_updates


def test_subscription_updated_past_due_ei_koske_profiiliin(h):
    h.rows["sub_live1"] = {"user_id": "user-42"}
    r = _post({"type": "customer.subscription.updated",
               "data": {"object": {"id": "sub_live1", "status": "past_due"}}})
    assert r.status_code == 200
    fields, _ = h.upserts[0]
    assert fields["status"] == "past_due"
    assert h.profile_updates == [], "past_due ei saa avata premiumia"


def test_subscription_deleted_flippaa_statuksen(h):
    h.rows["sub_live1"] = {"user_id": "user-42", "current_period_end": None}
    monkeypatch_active = getattr(m, "_web_subscription_active")
    try:
        m._web_subscription_active = lambda uid: False
        m._mobile_possibly_active = lambda uid, end: False
        r = _post({"type": "customer.subscription.deleted",
                   "data": {"object": {"id": "sub_live1"}}})
    finally:
        m._web_subscription_active = monkeypatch_active
    assert r.status_code == 200
    fields, match = h.upserts[0]
    assert fields == {"status": "cancelled"}
    assert match == {"stripe_subscription_id": "sub_live1"}
    # Ei muita aktiivisia lahteita -> premium alas.
    assert any(f.get("is_premium") is False for _, f in h.profile_updates)


def test_negatiivinen_kontrolli_tuntematon_sub_id(h):
    """Event tuntemattomalla sub-id:lla (esim. mobiili-Stripen vanha tilaus)
    EI saa kirjoittaa profiiliin mitaan — ja vastaus on silti 200 ettei
    Stripe jaa retry-looppiin."""
    r = _post({"type": "customer.subscription.updated",
               "data": {"object": {"id": "sub_UNKNOWN", "status": "active",
                                   "current_period_end": 1789430400}}})
    assert r.status_code == 200
    # Upsert kohdistuu sub-id:lla (PATCH ei osu yhteenkaan riviin = no-op
    # kannassa), mutta profiilia EI paivitetta koska rivia ei loydy.
    assert h.profile_updates == []


def test_checkout_completed_leimaa_lahteen_erillisena_kutsuna(h):
    r = _post({"type": "checkout.session.completed",
               "data": {"object": {"object": "checkout.session",
                                   "client_reference_id": "user-77",
                                   "metadata": {"plan": "season"},
                                   "customer": "cus_x",
                                   "subscription": "sub_new",
                                   "total_details": {}}}})
    assert r.status_code == 200
    stamps = [(u, f) for u, f in h.profile_updates if "premium_source" in f]
    assert stamps == [("user-77", {"premium_source": "stripe_web"})]
    # Leima on ERILLINEN kutsu: is_premium-aktivointi ei kanna premium_sourcea
    # (atominen PATCH kaatuisi kokonaan jos saraketta ei viela ole).
    activations = [f for _, f in h.profile_updates if f.get("is_premium")]
    assert activations and all("premium_source" not in f for f in activations)


def test_leiman_kaatuminen_ei_esta_premiumin_avausta(monkeypatch):
    """Migraatiota ei viela ajettu -> premium_source-PATCH failaa. Premiumin
    aktivoinnin on silti tapahduttava (fulfillment ei saa riippua leimasta)."""
    monkeypatch.setattr(m, "STRIPE_WEB_WEBHOOK_SECRET", SECRET)
    monkeypatch.setattr(m, "_upsert_web_subscription",
                        lambda fields, match=None: True)
    calls: list[tuple[str, dict]] = []

    def update(uid, fields):
        calls.append((uid, fields))
        return "premium_source" not in fields  # leima failaa, muut onnistuvat

    monkeypatch.setattr(m, "_update_profile", update)
    r = _post({"type": "checkout.session.completed",
               "data": {"object": {"object": "checkout.session",
                                   "client_reference_id": "user-88",
                                   "metadata": {"plan": "season"},
                                   "customer": "cus_x",
                                   "subscription": "sub_new2",
                                   "total_details": {}}}})
    assert r.status_code == 200
    assert any(f.get("is_premium") for _, f in calls), \
        "premium-aktivoinnin on onnistuttava vaikka leima failaa"


def test_revenuecat_aktivointi_leimaa_revenuecat(monkeypatch):
    monkeypatch.setattr(m, "REVENUECAT_WEBHOOK_AUTH", "rc-secret")
    updates: list[tuple[str, dict]] = []
    monkeypatch.setattr(m, "_update_profile",
                        lambda uid, fields: updates.append((uid, fields)) or True)
    r = TestClient(m.app).post(
        "/api/revenuecat/webhook",
        json={"event": {"type": "INITIAL_PURCHASE", "app_user_id": "user-99",
                        "expiration_at_ms": 1789430400000}},
        headers={"authorization": "rc-secret"})
    assert r.status_code == 200
    assert ("user-99", {"premium_source": "revenuecat"}) in updates
