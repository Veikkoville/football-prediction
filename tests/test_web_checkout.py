"""GoalIQ Pro SPA -checkoutin (/api/web/checkout, QUEUE #14) testit.

Ei verkkoa: Supabase-auth ja Stripe Checkout mockataan. Testaa auth-portin,
plan-validoinnin, origin-allowlistin ja session-parametrien muodon
(metadata identtinen Streamlit-billingin kanssa -> webhook-fulfillment toimii).
"""
from __future__ import annotations

import stripe


def _configure(monkeypatch):
    import api.main as m
    monkeypatch.setattr(stripe, "api_key", "sk_test_x")
    monkeypatch.setattr(m, "STRIPE_PRICE_MONTHLY_ID", "price_monthly_test")
    monkeypatch.setattr(m, "STRIPE_PRICE_SEASON_ID", "price_season_test")


def test_unknown_plan_422(client):
    r = client.post("/api/web/checkout", json={"plan": "lifetime"})
    assert r.status_code == 422


def test_stripe_unconfigured_500(client, monkeypatch):
    monkeypatch.setattr(stripe, "api_key", "")
    r = client.post("/api/web/checkout", json={"plan": "season"})
    assert r.status_code == 500
    assert "Stripe not configured" in r.json()["detail"]


def test_price_missing_500(client, monkeypatch):
    import api.main as m
    monkeypatch.setattr(stripe, "api_key", "sk_test_x")
    monkeypatch.setattr(m, "STRIPE_PRICE_SEASON_ID", "")
    r = client.post("/api/web/checkout", json={"plan": "season"})
    assert r.status_code == 500
    assert "STRIPE_PRICE_SEASON_ID" in r.json()["detail"]


def test_invalid_token_401(client, monkeypatch):
    import api.main as m
    _configure(monkeypatch)
    monkeypatch.setattr(m, "_get_supabase_user", lambda token: None)
    r = client.post("/api/web/checkout", json={"plan": "season"},
                    headers={"Authorization": "Bearer feik"})
    assert r.status_code == 401


def test_creates_session_with_streamlit_parity_metadata(client, monkeypatch):
    import api.main as m
    _configure(monkeypatch)
    monkeypatch.setattr(
        m, "_get_supabase_user",
        lambda token: {"id": "user-123", "email": "test@example.com"}
        if token == "valid" else None)
    created: dict = {}

    def fake_create(**kwargs):
        created.update(kwargs)
        return type("S", (), {"url": "https://checkout.stripe.com/test"})()

    monkeypatch.setattr(stripe.checkout.Session, "create",
                        staticmethod(fake_create))
    r = client.post(
        "/api/web/checkout",
        json={"plan": "season", "origin": "https://pro-next.goaliq.app"},
        headers={"Authorization": "Bearer valid"})
    assert r.status_code == 200
    assert r.json()["url"] == "https://checkout.stripe.com/test"
    # Webhook-fulfillment nojaa naihin (sama muoto kuin web/pro/billing.py)
    assert created["client_reference_id"] == "user-123"
    assert created["metadata"] == {"user_id": "user-123", "plan": "season",
                                   "source": "pro-web"}
    assert created["mode"] == "subscription"
    assert created["line_items"] == [{"price": "price_season_test",
                                      "quantity": 1}]
    assert created["success_url"].startswith(
        "https://pro-next.goaliq.app/?checkout=success")
    assert created["cancel_url"] == "https://pro-next.goaliq.app/?checkout=cancelled"


def test_origin_allowlist_blocks_open_redirect():
    from api.main import _web_checkout_base_url
    assert _web_checkout_base_url("https://pro.goaliq.app") == "https://pro.goaliq.app"
    assert _web_checkout_base_url("https://pro-next.goaliq.app/") == "https://pro-next.goaliq.app"
    assert _web_checkout_base_url("https://pro-spa-abc.pages.dev") == "https://pro-spa-abc.pages.dev"
    # Avoin redirect estetty -> oletusorigin
    assert _web_checkout_base_url("https://evil.example.com") == "https://pro.goaliq.app"
    assert _web_checkout_base_url("https://evil.com/#.pages.dev") == "https://pro.goaliq.app"
    assert _web_checkout_base_url("") == "https://pro.goaliq.app"
