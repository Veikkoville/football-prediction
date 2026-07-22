"""#155 fit-checker -testit: laillisuus, lukitus, delta, validoinnit.

Hermeettinen: uudelleenkäyttää test_fpl_rate_team-fixturet (sama mock-pooli,
sama monkeypatch-kohde rt-moduulissa — fpl_fit lukee poolin build_contextin
kautta).
"""
from __future__ import annotations

import pytest

import src.models.fpl_rate_team as rt
import src.models.fpl_fit as ff
from src.models.fpl_fit import fit_squad
from tests.test_fpl_rate_team import FAKE_BOOTSTRAP, FAKE_XP


@pytest.fixture(autouse=True)
def _mock_fpl(monkeypatch):
    def fake_fetch(path):
        if path == "/bootstrap-static/":
            return FAKE_BOOTSTRAP
        raise rt.RateTeamError(404, "Not found on the FPL API.")

    monkeypatch.setattr(rt, "_fetch_fpl", fake_fetch)
    monkeypatch.setattr(rt, "load_xp", lambda: FAKE_XP)
    rt._OPTIMAL_XP_CACHE.clear()
    rt._FPL_CACHE.clear()
    ff._FREE_OPTIMUM_CACHE.clear()
    yield
    rt._OPTIMAL_XP_CACHE.clear()
    rt._FPL_CACHE.clear()
    ff._FREE_OPTIMUM_CACHE.clear()


def _assert_legal_squad(out):
    squad = out["xi"] + out["bench"]
    assert len(out["xi"]) == 11
    assert len(out["bench"]) == 4
    # Runkokiintiöt tasan 2/5/5/3
    by_pos = {}
    for p in squad:
        by_pos[p["pos"]] = by_pos.get(p["pos"], 0) + 1
    assert by_pos == {"GKP": 2, "DEF": 5, "MID": 5, "FWD": 3}
    # Max 3 / klubi
    clubs = {}
    for p in squad:
        clubs[p["team_short"]] = clubs.get(p["team_short"], 0) + 1
    assert max(clubs.values()) <= 3
    # Budjetti
    assert out["meta"]["squad_cost"] <= out["meta"]["budget_cap"]
    # Ei duplikaatteja
    ids = [p["id"] for p in squad]
    assert len(ids) == len(set(ids))


def test_fit_locks_suboptimal_player_and_reports_cost():
    # id 30 = heikoin FWD (xp 3.8/GW) — ei mahtuisi vapaaseen optimiin
    out = fit_squad([30])
    _assert_legal_squad(out)
    assert 30 in [p["id"] for p in out["xi"]]
    assert out["totals"]["delta_xp"] < 0
    assert "costs" in out["message"]
    assert out["totals"]["optimal_xp_horizon"] > 0


def test_fit_top_players_costs_nothing():
    # 25 (paras FWD) + 15 (paras MID) kuuluvat vapaaseen optimiin →
    # lukitseminen ei maksa mitään (sama ahne polku molemmin puolin).
    out = fit_squad([25, 15])
    _assert_legal_squad(out)
    xi_ids = [p["id"] for p in out["xi"]]
    assert 25 in xi_ids and 15 in xi_ids
    assert out["totals"]["delta_xp"] >= -0.01


def test_fit_three_locked_all_in_xi():
    out = fit_squad([30, 24, 14])  # heikoin FWD + heikoin MID + heikoin DEF
    _assert_legal_squad(out)
    xi_ids = [p["id"] for p in out["xi"]]
    for pid in (30, 24, 14):
        assert pid in xi_ids
    assert out["totals"]["delta_xp"] < 0


@pytest.mark.parametrize("locked,status", [
    ([], 400),
    ([1, 2, 3, 4], 400),
    ([15, 15], 400),
    ([99999], 404),
    ([1, 2], 400),  # kaksi maalivahtia — XI:ssä on yksi
])
def test_fit_validation_errors(locked, status):
    with pytest.raises(rt.RateTeamError) as e:
        fit_squad(locked)
    assert e.value.status_code == status


def test_fit_response_shape():
    out = fit_squad([25])
    assert set(out) == {"meta", "locked", "xi", "bench", "totals", "message"}
    assert out["meta"]["horizon_gw"] == 6
    p = out["xi"][0]
    assert set(p) == {"id", "web_name", "team_short", "pos", "price",
                      "xp_horizon_total", "xp_per_gw"}
    assert out["locked"][0]["id"] == 25
