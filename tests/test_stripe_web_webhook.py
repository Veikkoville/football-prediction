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
            "customer": "cus_x", "subscription": None,
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
    assert fields["current_period_end"].endswith("06-30T23:59:59+00:00")


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
