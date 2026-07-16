"""GoalIQ Pro web-webhookin (/api/webhook/stripe-web) testit.

Ei verkkoa: Supabase-REST mockataan, Stripe-signeeraus testataan aidolla
construct_eventilla (secret tunnetaan testissä).
"""
from __future__ import annotations

import json
import time

import stripe


def _signed(payload: dict, secret: str) -> tuple[bytes, str]:
    # Stripen construct_event vaatii täyden event-rungon ("object"-kentät).
    payload = {"id": "evt_test", "object": "event", "api_version": "2024-06-20",
               "created": int(time.time()), **payload}
    payload["data"]["object"].setdefault("object", "checkout.session")
    body = json.dumps(payload).encode()
    ts = int(time.time())
    import hashlib
    import hmac
    sig = hmac.new(secret.encode(), f"{ts}.".encode() + body,
                   hashlib.sha256).hexdigest()
    return body, f"t={ts},v1={sig}"


def test_unconfigured_returns_200_warning(client, monkeypatch):
    import api.main as m
    monkeypatch.setattr(m, "STRIPE_WEB_WEBHOOK_SECRET", "")
    r = client.post("/api/webhook/stripe-web", content=b"{}")
    assert r.status_code == 200
    assert "not configured" in r.json().get("warning", "")


def test_bad_signature_400(client, monkeypatch):
    import api.main as m
    monkeypatch.setattr(m, "STRIPE_WEB_WEBHOOK_SECRET", "whsec_test")
    r = client.post("/api/webhook/stripe-web", content=b"{}",
                    headers={"stripe-signature": "t=1,v1=feik"})
    assert r.status_code == 400


def test_checkout_completed_upserts_subscription(client, monkeypatch):
    import api.main as m
    secret = "whsec_test"
    monkeypatch.setattr(m, "STRIPE_WEB_WEBHOOK_SECRET", secret)
    calls: list[tuple[dict, dict | None]] = []
    monkeypatch.setattr(m, "_upsert_web_subscription",
                        lambda fields, match=None: calls.append((fields, match)) or True)
    payload = {
        "type": "checkout.session.completed",
        "data": {"object": {
            "client_reference_id": "user-123",
            "metadata": {"plan": "season", "source": "pro-web"},
            "customer": "cus_x", "subscription": "sub_test",
            "payment_status": "paid",
        }},
    }
    body, sig = _signed(payload, secret)
    r = client.post("/api/webhook/stripe-web", content=body,
                    headers={"stripe-signature": sig})
    assert r.status_code == 200
    assert len(calls) == 1
    fields, match = calls[0]
    assert match is None
    assert fields["user_id"] == "user-123"
    assert fields["plan"] == "season"
    assert fields["status"] == "active"
    # Recurring-kausi (#5): period_endin tuo subscription.updated, ei checkout
    assert fields["current_period_end"] is None
    assert fields["stripe_subscription_id"] == "sub_test"


def test_checkout_without_subscription_falls_back_to_season_end(client, monkeypatch):
    import api.main as m
    secret = "whsec_test"
    monkeypatch.setattr(m, "STRIPE_WEB_WEBHOOK_SECRET", secret)
    calls: list[tuple[dict, dict | None]] = []
    monkeypatch.setattr(m, "_upsert_web_subscription",
                        lambda fields, match=None: calls.append((fields, match)) or True)
    payload = {
        "type": "checkout.session.completed",
        "data": {"object": {
            "client_reference_id": "user-123",
            "metadata": {"plan": "season"},
            "customer": "cus_x", "subscription": None,
            "payment_status": "paid",
        }},
    }
    body, sig = _signed(payload, secret)
    r = client.post("/api/webhook/stripe-web", content=body,
                    headers={"stripe-signature": sig})
    assert r.status_code == 200
    assert calls[0][0]["current_period_end"].endswith("06-30T23:59:59+00:00")


def test_subscription_deleted_marks_cancelled(client, monkeypatch):
    import api.main as m
    secret = "whsec_test"
    monkeypatch.setattr(m, "STRIPE_WEB_WEBHOOK_SECRET", secret)
    calls: list[tuple[dict, dict | None]] = []
    monkeypatch.setattr(m, "_upsert_web_subscription",
                        lambda fields, match=None: calls.append((fields, match)) or True)
    payload = {"type": "customer.subscription.deleted",
               "data": {"object": {"id": "sub_x", "status": "canceled"}}}
    body, sig = _signed(payload, secret)
    r = client.post("/api/webhook/stripe-web", content=body,
                    headers={"stripe-signature": sig})
    assert r.status_code == 200
    assert calls[0][0]["status"] == "cancelled"
    assert calls[0][1] == {"stripe_subscription_id": "sub_x"}


def test_checkout_completed_also_sets_profile_premium(client, monkeypatch):
    """Cross-platform (#7): web-osto avaa mobiilipremiumin (profiles)."""
    import api.main as m
    secret = "whsec_test"
    monkeypatch.setattr(m, "STRIPE_WEB_WEBHOOK_SECRET", secret)
    monkeypatch.setattr(m, "_upsert_web_subscription", lambda *a, **k: True)
    profile_calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(m, "_update_profile",
                        lambda uid, fields: profile_calls.append((uid, fields)) or True)
    payload = {"type": "checkout.session.completed",
               "data": {"object": {"client_reference_id": "user-123",
                                   "metadata": {"plan": "season"},
                                   "customer": "cus_x", "subscription": "sub_x",
                                   "payment_status": "paid"}}}
    body, sig = _signed(payload, secret)
    r = client.post("/api/webhook/stripe-web", content=body,
                    headers={"stripe-signature": sig})
    assert r.status_code == 200
    assert profile_calls and profile_calls[0][0] == "user-123"
    assert profile_calls[0][1]["is_premium"] is True


def test_web_deleted_no_clobber_when_mobile_active(client, monkeypatch):
    """🔒 NO-CLOBBER: web-peruutus EI nollaa premiumia jos mobiili aktiivinen."""
    import api.main as m
    secret = "whsec_test"
    monkeypatch.setattr(m, "STRIPE_WEB_WEBHOOK_SECRET", secret)
    monkeypatch.setattr(m, "_upsert_web_subscription", lambda *a, **k: True)
    monkeypatch.setattr(m, "_get_web_subscription",
                        lambda f, v: {"user_id": "user-123",
                                      "current_period_end": "2026-08-01T00:00:00+00:00"})
    monkeypatch.setattr(m, "_web_subscription_active", lambda uid: False)
    monkeypatch.setattr(m, "_mobile_possibly_active", lambda uid, we: True)
    profile_calls: list = []
    monkeypatch.setattr(m, "_update_profile",
                        lambda uid, fields: profile_calls.append((uid, fields)) or True)
    payload = {"type": "customer.subscription.deleted",
               "data": {"object": {"id": "sub_x", "status": "canceled"}}}
    body, sig = _signed(payload, secret)
    r = client.post("/api/webhook/stripe-web", content=body,
                    headers={"stripe-signature": sig})
    assert r.status_code == 200
    assert profile_calls == []  # is_premium EI nollattu


def test_web_deleted_clears_premium_when_no_other_source(client, monkeypatch):
    import api.main as m
    secret = "whsec_test"
    monkeypatch.setattr(m, "STRIPE_WEB_WEBHOOK_SECRET", secret)
    monkeypatch.setattr(m, "_upsert_web_subscription", lambda *a, **k: True)
    monkeypatch.setattr(m, "_get_web_subscription",
                        lambda f, v: {"user_id": "user-123",
                                      "current_period_end": None})
    monkeypatch.setattr(m, "_web_subscription_active", lambda uid: False)
    monkeypatch.setattr(m, "_mobile_possibly_active", lambda uid, we: False)
    profile_calls: list = []
    monkeypatch.setattr(m, "_update_profile",
                        lambda uid, fields: profile_calls.append((uid, fields)) or True)
    payload = {"type": "customer.subscription.deleted",
               "data": {"object": {"id": "sub_x", "status": "canceled"}}}
    body, sig = _signed(payload, secret)
    client.post("/api/webhook/stripe-web", content=body,
                headers={"stripe-signature": sig})
    assert profile_calls and profile_calls[0][1]["is_premium"] is False


def test_rc_expiration_no_clobber_when_web_active(client, monkeypatch):
    """🔒 NO-CLOBBER: RC EXPIRATION ei nollaa premiumia jos web-sub aktiivinen."""
    import api.main as m
    monkeypatch.setattr(m, "REVENUECAT_WEBHOOK_AUTH", "rc-secret")
    monkeypatch.setattr(m, "_web_subscription_active", lambda uid: True)
    profile_calls: list = []
    monkeypatch.setattr(m, "_update_profile",
                        lambda uid, fields: profile_calls.append((uid, fields)) or True)
    r = client.post("/api/revenuecat/webhook",
                    json={"event": {"type": "EXPIRATION",
                                    "app_user_id": "user-123"}},
                    headers={"Authorization": "rc-secret"})
    assert r.status_code == 200
    assert all(f.get("is_premium") is not False for _, f in profile_calls)


def test_rc_expiration_clears_premium_when_no_web(client, monkeypatch):
    import api.main as m
    monkeypatch.setattr(m, "REVENUECAT_WEBHOOK_AUTH", "rc-secret")
    monkeypatch.setattr(m, "_web_subscription_active", lambda uid: False)
    profile_calls: list = []
    monkeypatch.setattr(m, "_update_profile",
                        lambda uid, fields: profile_calls.append((uid, fields)) or True)
    r = client.post("/api/revenuecat/webhook",
                    json={"event": {"type": "EXPIRATION",
                                    "app_user_id": "user-123"}},
                    headers={"Authorization": "rc-secret"})
    assert r.status_code == 200
    assert profile_calls and profile_calls[0][1]["is_premium"] is False


# --- #101 guest checkout: tili provisioidaan maksun jälkeen ---


def test_guest_checkout_provisions_user_and_sends_magic_link(client, monkeypatch):
    import api.main as m
    secret = "whsec_test"
    monkeypatch.setattr(m, "STRIPE_WEB_WEBHOOK_SECRET", secret)
    provisioned: list[str] = []
    monkeypatch.setattr(m, "_provision_supabase_user",
                        lambda email: provisioned.append(email) or "new-user-1")
    sub_calls: list[tuple[dict, dict | None]] = []
    monkeypatch.setattr(m, "_upsert_web_subscription",
                        lambda fields, match=None: sub_calls.append((fields, match)) or True)
    profile_calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(m, "_update_profile",
                        lambda uid, fields: profile_calls.append((uid, fields)) or True)
    links: list[str] = []
    monkeypatch.setattr(m, "_send_magic_link",
                        lambda email, redirect_to="https://pro.goaliq.app":
                        links.append(email) or True)
    payload = {
        "type": "checkout.session.completed",
        "data": {"object": {
            # EI client_reference_id:tä — guest maksoi ilman tiliä
            "metadata": {"plan": "monthly", "source": "pro-web-guest"},
            "customer_details": {"email": "buyer@example.com"},
            "customer": "cus_g", "subscription": "sub_guest",
            "payment_status": "paid",
        }},
    }
    body, sig = _signed(payload, secret)
    r = client.post("/api/webhook/stripe-web", content=body,
                    headers={"stripe-signature": sig})
    assert r.status_code == 200
    assert provisioned == ["buyer@example.com"]
    # Fulfillment laskeutuu provisioidulle tilille
    assert sub_calls and sub_calls[0][0]["user_id"] == "new-user-1"
    assert sub_calls[0][0]["plan"] == "monthly"
    assert profile_calls and profile_calls[0][0] == "new-user-1"
    assert profile_calls[0][1]["is_premium"] is True
    # Kirjautumislinkki lähtee fulfillmentin JÄLKEEN (premium jo aktiivinen)
    assert links == ["buyer@example.com"]


def test_guest_checkout_provisioning_failure_returns_500_for_retry(client, monkeypatch):
    """Transientti Supabase-häiriö → 500 → Stripe retryaa eventin."""
    import api.main as m
    secret = "whsec_test"
    monkeypatch.setattr(m, "STRIPE_WEB_WEBHOOK_SECRET", secret)
    monkeypatch.setattr(m, "_provision_supabase_user", lambda email: None)
    sub_calls: list = []
    monkeypatch.setattr(m, "_upsert_web_subscription",
                        lambda *a, **k: sub_calls.append(a) or True)
    payload = {
        "type": "checkout.session.completed",
        "data": {"object": {
            "metadata": {"plan": "season", "source": "pro-web-guest"},
            "customer_details": {"email": "buyer@example.com"},
            "customer": "cus_g", "subscription": "sub_guest",
            "payment_status": "paid",
        }},
    }
    body, sig = _signed(payload, secret)
    r = client.post("/api/webhook/stripe-web", content=body,
                    headers={"stripe-signature": sig})
    assert r.status_code == 500
    assert sub_calls == []  # fulfillment EI ajettu ilman tiliä


def test_guest_magic_link_failure_does_not_fail_fulfillment(client, monkeypatch):
    """Mailin lähetysvirhe EI saa kaataa webhookia — premium on jo aktivoitu
    ja käyttäjä pääsee sisään LoginBoxin sign-in-link-polulla."""
    import api.main as m
    secret = "whsec_test"
    monkeypatch.setattr(m, "STRIPE_WEB_WEBHOOK_SECRET", secret)
    monkeypatch.setattr(m, "_provision_supabase_user", lambda email: "new-user-2")
    monkeypatch.setattr(m, "_upsert_web_subscription", lambda *a, **k: True)
    monkeypatch.setattr(m, "_update_profile", lambda *a, **k: True)
    monkeypatch.setattr(m, "_send_magic_link",
                        lambda email, redirect_to="https://pro.goaliq.app": False)
    payload = {
        "type": "checkout.session.completed",
        "data": {"object": {
            "metadata": {"plan": "season", "source": "pro-web-guest"},
            "customer_details": {"email": "buyer2@example.com"},
            "customer": "cus_g2", "subscription": "sub_g2",
            "payment_status": "paid",
        }},
    }
    body, sig = _signed(payload, secret)
    r = client.post("/api/webhook/stripe-web", content=body,
                    headers={"stripe-signature": sig})
    assert r.status_code == 200


def test_checkout_without_user_ref_is_ignored(client, monkeypatch):
    import api.main as m
    secret = "whsec_test"
    monkeypatch.setattr(m, "STRIPE_WEB_WEBHOOK_SECRET", secret)
    calls = []
    monkeypatch.setattr(m, "_upsert_web_subscription",
                        lambda fields, match=None: calls.append(fields) or True)
    payload = {"type": "checkout.session.completed",
               "data": {"object": {"metadata": {}, "payment_status": "paid"}}}
    body, sig = _signed(payload, secret)
    r = client.post("/api/webhook/stripe-web", content=body,
                    headers={"stripe-signature": sig})
    assert r.status_code == 200
    assert calls == []
