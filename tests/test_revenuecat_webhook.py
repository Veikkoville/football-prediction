"""#51-auditin aukko: RC-webhookin AKTIVOINTIPOLKU + alias-resoluutio + auth.

Provisiointipolku on Hub-2,0-tahden #1-valituksen ydin (maksaja ei saa premiumia)
-> nyt yksikkotestattu. Supabase-kirjoitus mockataan (_update_profile).
"""
from __future__ import annotations

import pytest

import api.main as m


@pytest.fixture(autouse=True)
def _auth(monkeypatch):
    monkeypatch.setattr(m, "REVENUECAT_WEBHOOK_AUTH", "rc-secret")
    yield


def _post(client, event, auth="rc-secret"):
    return client.post("/api/revenuecat/webhook", json={"event": event},
                       headers={"authorization": auth})


def test_unconfigured_returns_200_warning(client, monkeypatch):
    monkeypatch.setattr(m, "REVENUECAT_WEBHOOK_AUTH", "")
    r = client.post("/api/revenuecat/webhook", json={"event": {}})
    assert r.status_code == 200 and "not configured" in r.json()["warning"]


def test_bad_auth_401(client):
    r = _post(client, {"type": "INITIAL_PURCHASE", "app_user_id": "u1"},
              auth="vaara")
    assert r.status_code == 401


@pytest.mark.parametrize("etype", ["INITIAL_PURCHASE", "RENEWAL",
                                   "UNCANCELLATION", "PRODUCT_CHANGE",
                                   "NON_RENEWING_PURCHASE"])
def test_activation_events_set_premium_true(client, monkeypatch, etype):
    calls = []
    monkeypatch.setattr(m, "_update_profile",
                        lambda uid, fields: calls.append((uid, fields)) or True)
    r = _post(client, {"type": etype, "app_user_id": "user-abc"})
    assert r.status_code == 200
    assert calls and calls[0][0] == "user-abc"
    assert calls[0][1]["is_premium"] is True


def test_alias_resolution_prefers_non_anonymous(client, monkeypatch):
    # EXPIRATION kantaa usein anonyymin original-id:n -> ei-anonyymi aliaksista
    calls = []
    monkeypatch.setattr(m, "_update_profile",
                        lambda uid, fields: calls.append((uid, fields)) or True)
    r = _post(client, {"type": "INITIAL_PURCHASE",
                       "app_user_id": "$RCAnonymousID:xyz",
                       "original_app_user_id": "$RCAnonymousID:xyz",
                       "aliases": ["$RCAnonymousID:xyz", "supa-uid-1"]})
    assert r.status_code == 200
    assert calls and calls[0][0] == "supa-uid-1"


def test_all_anonymous_skips_without_write(client, monkeypatch):
    calls = []
    monkeypatch.setattr(m, "_update_profile",
                        lambda uid, fields: calls.append((uid, fields)) or True)
    r = _post(client, {"type": "INITIAL_PURCHASE",
                       "app_user_id": "$RCAnonymousID:only"})
    assert r.status_code == 200 and calls == []


def test_cancellation_keeps_premium_flags_cancel(client, monkeypatch):
    calls = []
    monkeypatch.setattr(m, "_update_profile",
                        lambda uid, fields: calls.append((uid, fields)) or True)
    r = _post(client, {"type": "CANCELLATION", "app_user_id": "user-abc"})
    assert r.status_code == 200
    assert calls, "CANCELLATION kirjoittaa cancel-lipun"
    fields = calls[0][1]
    assert fields.get("is_premium") is not False
    assert fields.get("subscription_cancel_at_period_end") is True
