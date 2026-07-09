"""#49 standings/fixtures 429-kovennus: TTL-cache, backoff, stale-fallback.

Hermeettinen: requests.get mockataan api.main-namespacessa; FD-avain feikataan.
"""
from __future__ import annotations

import pytest

import api.main as m


def _row(pos=1, name="Arsenal"):
    return {"position": pos, "team": {"name": name, "shortName": name[:3],
                                      "crest": None},
            "playedGames": 1, "won": 1, "draw": 0, "lost": 0,
            "goalsFor": 2, "goalsAgainst": 0, "goalDifference": 2, "points": 3}


STANDINGS_BODY = {"standings": [{"type": "TOTAL", "table": [_row()]}]}
FIXTURES_BODY = {"matches": [{"utcDate": "2026-08-21T19:00:00Z",
                              "homeTeam": {"name": "Arsenal", "shortName": "ARS"},
                              "awayTeam": {"name": "Coventry", "shortName": "COV"},
                              "matchday": 1}]}


class _Resp:
    def __init__(self, status, body=None, text=""):
        self.status_code = status
        self._body = body or {}
        self.text = text

    def json(self):
        return self._body


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    m._FD_HTTP_CACHE.clear()
    m._FD_HTTP_LOCKS.clear()
    import src.data.football_data_org as fdo
    monkeypatch.setattr(fdo, "_api_key", lambda: "test-key")
    monkeypatch.setattr(m.time, "sleep", lambda s: None)  # backoff heti
    yield
    m._FD_HTTP_CACHE.clear()
    m._FD_HTTP_LOCKS.clear()


def _mock_get(monkeypatch, responses):
    """responses: lista _Resp per FD-kutsu (kulutetaan järjestyksessä);
    viimeinen jää voimaan. Palauttaa kutsulaskurin."""
    calls = {"n": 0}

    def fake_get(url, headers=None, timeout=None):
        calls["n"] += 1
        i = min(calls["n"] - 1, len(responses) - 1)
        return responses[i]

    monkeypatch.setattr(m.requests, "get", fake_get)
    return calls


def test_standings_cached_second_call_no_upstream(client, monkeypatch):
    calls = _mock_get(monkeypatch, [_Resp(200, STANDINGS_BODY)])
    r1 = client.get("/api/standings?league=ENG-Premier League-FD")
    r2 = client.get("/api/standings?league=ENG-Premier League-FD")
    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.json() == r2.json()
    assert "stale" not in r1.json()
    assert calls["n"] == 1, "toinen kutsu pitää tulla cachesta"


def test_rapid_league_browse_no_user_429(client, monkeypatch):
    # Nopea selaus: sama liigasetti kahdesti → FD-kutsuja vain 1/liiga
    calls = _mock_get(monkeypatch, [_Resp(200, STANDINGS_BODY)])
    leagues = ["ENG-Premier League-FD", "GER-Bundesliga-FD", "ESP-La Liga-FD",
               "ITA-Serie A-FD", "FRA-Ligue 1-FD", "ENG-Championship",
               "NED-Eredivisie", "POR-Primeira Liga", "BRA-Serie A"]
    for _ in range(2):
        for lg in leagues:
            assert client.get(f"/api/standings?league={lg}").status_code == 200
    assert calls["n"] == len(leagues)


def test_429_backoff_then_success(client, monkeypatch):
    calls = _mock_get(monkeypatch, [_Resp(429, text="Too many requests"),
                                    _Resp(200, STANDINGS_BODY)])
    r = client.get("/api/standings?league=ENG-Premier League-FD")
    assert r.status_code == 200
    assert calls["n"] == 2, "429 → backoff → uusinta"
    assert "stale" not in r.json()


def test_persistent_429_serves_stale_after_ttl(client, monkeypatch):
    calls = _mock_get(monkeypatch, [_Resp(200, STANDINGS_BODY),
                                    _Resp(429, text="Too many requests")])
    r1 = client.get("/api/standings?league=ENG-Premier League-FD")
    assert r1.status_code == 200
    # Vanhennetaan cache käsin (TTL ohi) → seuraava FD-haku failaa 429 ×2
    for k in list(m._FD_HTTP_CACHE):
        ts, data = m._FD_HTTP_CACHE[k]
        m._FD_HTTP_CACHE[k] = (ts - m.FD_HTTP_TTL_SEC - 1, data)
    r2 = client.get("/api/standings?league=ENG-Premier League-FD")
    assert r2.status_code == 200, "stale-fallback, EI käyttäjävirhettä"
    assert r2.json().get("stale") is True
    assert r2.json()["rows"] == r1.json()["rows"]


def test_persistent_429_without_cache_is_handled_error(client, monkeypatch):
    _mock_get(monkeypatch, [_Resp(429, text="Too many requests")])
    r = client.get("/api/standings?league=ENG-Premier League-FD")
    assert r.status_code == 429
    assert "429" in r.json()["detail"]


def test_fixtures_share_cache_and_stale_flag(client, monkeypatch):
    calls = _mock_get(monkeypatch, [_Resp(200, FIXTURES_BODY)])
    r1 = client.get("/api/fixtures?league=ENG-Premier League-FD&days=7")
    r2 = client.get("/api/fixtures?league=ENG-Premier League-FD&days=7")
    assert r1.status_code == 200 and calls["n"] == 1
    assert r1.json()["fixtures"][0]["home_team"] == "Arsenal"
    assert "stale" not in r1.json()
    assert r2.json() == r1.json()


def test_response_shape_unchanged(client, monkeypatch):
    _mock_get(monkeypatch, [_Resp(200, STANDINGS_BODY)])
    r = client.get("/api/standings?league=ENG-Premier League-FD")
    body = r.json()
    assert set(body.keys()) == {"league", "season", "rows"}
    assert set(body["rows"][0].keys()) == {
        "position", "team_name", "team_short_name", "team_crest",
        "played_games", "won", "draw", "lost", "goals_for", "goals_against",
        "goal_difference", "points"}
