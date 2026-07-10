"""#55 career-endpoint-testit: summary-matematiikka, kesävälitilan dedup,
esikausi-degradaatio (EI blank/virhe), teaser-poisjättö, endpoint-smoke.

Hermeettinen: FPL-API (rt._fetch_fpl) ja rate_team mockataan — ei verkkoa.
"""
from __future__ import annotations

import pytest

import src.models.fpl_career as fc
import src.models.fpl_rate_team as rt

ENTRY_ROOT = {
    "id": 424242, "player_first_name": "Ville", "player_last_name": "Test",
    "name": "Test XI", "joined_time": "2023-07-21T10:00:00Z",
}

PAST = [
    {"season_name": "2023/24", "total_points": 2001, "rank": 500000},
    {"season_name": "2024/25", "total_points": 2210, "rank": 120000},
    {"season_name": "2025/26", "total_points": 1381, "rank": 11775271},
]

# Kesävälitila: 25/26 on SEKÄ currentissa (38 GW) ETTÄ pastissa.
CURRENT_FULL = [
    {"event": g, "points": 30 + (g % 7), "total_points": 0,
     "overall_rank": 1_000_000 - g * 1000,
     "event_transfers_cost": 4 if g in (10, 20) else 0,
     "points_on_bench": 2}
    for g in range(1, 39)
]
CURRENT_FULL[-1]["total_points"] = 1381  # matchaa past[-1] → finished-dedup

CHIPS = [{"name": "wildcard", "time": "x", "event": 12},
         {"name": "bboost", "time": "x", "event": 30}]

FAKE_TEASER_RATING = {
    "meta": {"gw": 1, "rating_method": "vs_optimal_budget_team"},
    "rating": {"team_xp_gw": 52.2, "team_xp_horizon": 304.3,
               "percentile": 89.4},
}


def _mock_fpl(monkeypatch, root=ENTRY_ROOT, past=PAST, current=CURRENT_FULL,
              chips=CHIPS, bootstrap=None, teaser="ok"):
    def fake_fetch(path):
        if path == "/entry/424242/":
            return root
        if path == "/entry/424242/history/":
            return {"past": past, "current": current, "chips": chips}
        if path == "/bootstrap-static/":
            if bootstrap is None:
                raise rt.RateTeamError(503, "no bootstrap in this test")
            return bootstrap
        raise rt.RateTeamError(404, "Not found on the FPL API.")

    monkeypatch.setattr(rt, "_fetch_fpl", fake_fetch)
    if teaser == "ok":
        monkeypatch.setattr(rt, "rate_team",
                            lambda entry=None, **kw: FAKE_TEASER_RATING)
    else:
        def boom(entry=None, **kw):
            raise rt.RateTeamError(404, "no picks")
        monkeypatch.setattr(rt, "rate_team", boom)
    rt._FPL_CACHE.clear()


# ---------------------------------------------------------------------------
# Kesävälitila: finished current == past[-1] → EI tuplalaskentaa
# ---------------------------------------------------------------------------

def test_summer_dedup_and_summary(monkeypatch):
    _mock_fpl(monkeypatch)
    out = fc.career(424242)
    assert out["manager"]["name"] == "Ville Test"
    assert out["manager"]["team_name"] == "Test XI"
    assert out["summary"]["since"] == 2023
    assert len(out["past_seasons"]) == 3
    # Dedup: 25/26 on pastissa → all_time = pelkkä past-summa, seasons = 3
    assert out["summary"]["all_time_points"] == 2001 + 2210 + 1381
    assert out["summary"]["seasons_played"] == 3
    assert out["summary"]["best_season"]["season"] == "2024/25"
    assert out["summary"]["best_rank"] == 120000
    lat = out["latest_season"]
    assert lat["available"] and lat["finished"]
    assert lat["season"] == "2025/26"
    assert lat["total_points"] == 1381
    assert lat["total_hits"] == 8
    assert lat["bench_points"] == 76
    assert lat["best_gw"]["points"] == 36 and lat["worst_gw"]["points"] == 30
    assert [c["gw"] for c in lat["chips_used"]] == [12, 30]
    assert len(lat["gws"]) == 38


def test_in_progress_season_counts_once(monkeypatch):
    # Kesken kauden: current EI matchaa pastia → lasketaan mukaan kerran.
    cur = CURRENT_FULL[:10]
    cur = [dict(g) for g in cur]
    cur[-1]["total_points"] = 333
    cur[-1]["overall_rank"] = 250000
    _mock_fpl(monkeypatch, current=cur)
    out = fc.career(424242)
    lat = out["latest_season"]
    assert lat["available"] and not lat["finished"] and lat["season"] is None
    assert out["summary"]["all_time_points"] == 2001 + 2210 + 1381 + 333
    assert out["summary"]["seasons_played"] == 4
    assert out["summary"]["best_rank"] == 120000  # 250k ei ohita


# ---------------------------------------------------------------------------
# Esikausi-degradaatio: current tyhjä → past + summary silti, EI virhettä
# ---------------------------------------------------------------------------

def test_preseason_graceful_empty_current(monkeypatch):
    boot = {"events": [
        {"id": 1, "is_next": True, "deadline_time": "2026-08-21T17:15:00Z"}]}
    _mock_fpl(monkeypatch, current=[], chips=[], bootstrap=boot, teaser="fail")
    out = fc.career(424242)
    assert len(out["past_seasons"]) == 3
    assert out["summary"]["all_time_points"] == 2001 + 2210 + 1381
    lat = out["latest_season"]
    assert lat["available"] is False
    assert "2026-08-21" in lat["note"] and "GW1" in lat["note"]
    # Teaser failaa → jätetään POIS, ei placeholderia
    assert "model_teaser" not in out


def test_preseason_note_survives_bootstrap_failure(monkeypatch):
    _mock_fpl(monkeypatch, current=[], chips=[], bootstrap=None, teaser="fail")
    out = fc.career(424242)  # bootstrap 503 EI kaada vastausta
    assert out["latest_season"]["available"] is False
    assert out["latest_season"]["note"]


def test_brand_new_entry_no_history(monkeypatch):
    _mock_fpl(monkeypatch, past=[], current=[], chips=[], teaser="fail")
    out = fc.career(424242)
    assert out["past_seasons"] == []
    assert out["summary"]["seasons_played"] == 0
    assert out["summary"]["all_time_points"] == 0
    assert out["summary"]["best_season"] is None
    assert out["summary"]["since"] == 2023  # joined_time-fallback
    assert out["latest_season"]["available"] is False


# ---------------------------------------------------------------------------
# Teaser + virhepolut
# ---------------------------------------------------------------------------

def test_model_teaser_present_when_squad_importable(monkeypatch):
    _mock_fpl(monkeypatch)
    out = fc.career(424242)
    t = out["model_teaser"]
    assert t["team_xp_gw"] == 52.2 and t["percentile"] == 89.4
    assert t["rating_method"] == "vs_optimal_budget_team"  # #50, EI random


def test_unknown_entry_404(monkeypatch):
    _mock_fpl(monkeypatch)
    with pytest.raises(fc.RateTeamError) as e:
        fc.career(999999)
    assert e.value.status_code == 404
    assert "999999" in e.value.detail


# ---------------------------------------------------------------------------
# Endpoint-smoke (TestClient)
# ---------------------------------------------------------------------------

def test_endpoint_career(client, monkeypatch):
    _mock_fpl(monkeypatch)
    r = client.get("/api/fantasy/career?entry=424242")
    assert r.status_code == 200
    b = r.json()
    assert b["manager"]["name"] == "Ville Test"
    assert b["summary"]["seasons_played"] == 3
    assert r.headers["cache-control"] == "no-store"


def test_endpoint_career_requires_entry(client):
    r = client.get("/api/fantasy/career")
    assert r.status_code == 422  # FastAPI: pakollinen query-param puuttuu


def test_endpoint_career_unknown_entry(client, monkeypatch):
    _mock_fpl(monkeypatch)
    r = client.get("/api/fantasy/career?entry=999999")
    assert r.status_code == 404
