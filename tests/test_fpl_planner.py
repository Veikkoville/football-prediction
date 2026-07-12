"""#35 planner-suiten testit: FT/hit-matematiikka, laillisuus, baseline-gate,
captain-picker, differentials, compare. Hermeettinen (jaettu mock-fixture
test_fpl_rate_team-moduulista, monkeypatch rt-moduuliin jonka läpi planner käy)."""
from __future__ import annotations

import pytest

import src.models.fpl_planner as pl
import src.models.fpl_rate_team as rt
from tests.test_fpl_rate_team import (  # noqa: F401 — _mock_fpl-fixture käyttöön
    FAKE_BOOTSTRAP, POOL_BOOT, SQUAD_IDS, _mock_fpl,
)

# Heikko runko: huonoimmat MID:t (20-24) + huonoimmat DEF:t → plannerilla
# on aitoja upgradeja tehtävänä. (Pool: GKP 1-4, DEF 5-14, MID 15-24, FWD 25-30)
WEAK_SQUAD = [3, 4, 10, 11, 12, 13, 14, 20, 21, 22, 23, 24, 28, 29, 30]


def test_plan_structure_and_baseline_gate():
    out = pl.plan_transfers(entry=424242, horizon=3)
    assert [p["gw"] for p in out["plan"]] == [1, 2, 3]
    assert out["totals"]["plan_xp"] >= out["totals"]["baseline_xp_no_transfers"]
    assert out["totals"]["net_gain"] >= 0
    assert "not a global optimum" in out["meta"]["heuristic"]


def test_plan_best_squad_rolls_transfers():
    # SQUAD_IDS = poolin parhaat per positio → ei mielekkäitä siirtoja → roll
    out = pl.plan_transfers(players=SQUAD_IDS, horizon=3, bank=0.0)
    assert all(p["roll_transfer"] for p in out["plan"])
    assert out["totals"]["hits_taken"] == 0
    # FT-carry: 1 → 2 → 3 (katto 5)
    assert [p["free_transfers_left"] for p in out["plan"]] == [1, 2, 3]


def test_plan_weak_squad_makes_legal_upgrades():
    out = pl.plan_transfers(players=WEAK_SQUAD, horizon=3, bank=10.0, ft=1)
    moves = [m for p in out["plan"] for m in p["transfers"]]
    assert moves, "heikolle rungolle pitää löytyä upgradeja"
    assert out["totals"]["net_gain"] > 0
    # Simuloi suunnitelma: laillisuus + budjetti joka askeleella
    prices = {e["id"]: e["now_cost"] for e in POOL_BOOT}
    clubs_of = {e["id"]: e["team"] for e in POOL_BOOT}
    pos_of = {e["id"]: e["element_type"] for e in POOL_BOOT}
    squad = list(WEAK_SQUAD)
    bank = 100  # 10.0m kymmenyksinä
    for p in out["plan"]:
        for m in p["transfers"]:
            out_id, in_id = m["out"]["id"], m["in"]["id"]
            assert out_id in squad and in_id not in squad
            assert pos_of[out_id] == pos_of[in_id]
            bank += prices[out_id] - prices[in_id]
            assert bank >= 0, "budjetti ei saa mennä miinukselle"
            squad.remove(out_id)
            squad.append(in_id)
            counts = {}
            for sid in squad:
                counts[clubs_of[sid]] = counts.get(clubs_of[sid], 0) + 1
            assert all(v <= rt.MAX_PER_CLUB for v in counts.values())
    # Kiintiöt säilyvät (siirrot positio-samoja)
    from collections import Counter
    assert Counter(pos_of[i] for i in squad) == Counter(
        pos_of[i] for i in WEAK_SQUAD)


def test_plan_hit_math_ft_zero():
    # ft=0 → jokainen siirto maksaa 4; siirto tehdään vain jos gain-4 >= MIN_GAIN
    out = pl.plan_transfers(players=WEAK_SQUAD, horizon=2, bank=10.0, ft=0)
    gw1 = out["plan"][0]
    for m in gw1["transfers"]:
        assert m["hit"] == pl.HIT_COST
        assert m["gain_xp_remaining"] - m["hit"] >= pl.MIN_GAIN_PER_TRANSFER
    assert out["totals"]["hits_taken"] == sum(
        1 for p in out["plan"] for m in p["transfers"] if m["hit"] > 0)


def test_plan_hold_verdict_best_squad_holds():
    # #63: paras runko -> 0 siirtoa -> eksplisiittinen hold-verdikti
    out = pl.plan_transfers(players=SQUAD_IDS, horizon=3, bank=0.0)
    hv = out["hold_verdict"]
    assert hv["verdict"] == "hold"
    assert hv["transfers_planned"] == 0
    assert hv["best_move_gain_xp"] is None
    assert hv["horizon_gws"] == 3
    assert hv["threshold_xp"] == rt.HOLD_THRESHOLD_XP
    assert "holding" in hv["message"].lower()


def test_plan_hold_verdict_weak_squad_transfers():
    # #63: heikko runko -> transfer-verdikti, netto = totals.net_gain (hitit jo
    # vähennetty) ja ylittää kynnyksen
    out = pl.plan_transfers(players=WEAK_SQUAD, horizon=3, bank=10.0, ft=1)
    hv = out["hold_verdict"]
    assert hv["verdict"] == "transfer"
    assert hv["transfers_planned"] > 0
    assert hv["best_move_gain_xp"] == out["totals"]["net_gain"]
    assert hv["best_move_gain_xp"] >= rt.HOLD_THRESHOLD_XP
    assert "Recommended" in hv["message"]


def test_plan_param_validation():
    with pytest.raises(rt.RateTeamError):
        pl.plan_transfers(players=SQUAD_IDS, horizon=1)
    with pytest.raises(rt.RateTeamError):
        pl.plan_transfers(players=SQUAD_IDS, horizon=3, ft=99)


def test_captain_picker_top3_and_differential():
    out = pl.captain_picker(entry=424242)
    top3 = out["top3"]
    assert len(top3) == 3
    assert top3[0]["gw_xp"] >= top3[1]["gw_xp"] >= top3[2]["gw_xp"]
    assert top3[0]["gap_to_top"] == 0.0 and top3[2]["gap_to_top"] >= 0
    # top1 = FWD 25 (5.8, EO 40); differential = EO <= 10, eri kuin top1
    assert top3[0]["id"] == 25
    d = out["differential"]
    assert d is not None and d["owned_pct"] <= pl.CAPTAIN_DIFFERENTIAL_EO
    assert d["id"] != top3[0]["id"]


def test_differential_finder_filters():
    out = pl.differential_finder(max_ownership=10.0)
    assert out["players"], "EO 5 % -pelaajia pitää löytyä"
    assert all(p["owned_pct"] <= 10.0 for p in out["players"])
    xs = [p["xp_horizon_total"] for p in out["players"]]
    assert xs == sorted(xs, reverse=True)
    only_mid = pl.differential_finder(max_ownership=10.0, pos="MID")
    assert only_mid["players"] and all(p["pos"] == "MID"
                                       for p in only_mid["players"])
    with pytest.raises(rt.RateTeamError):
        pl.differential_finder(pos="XYZ")


def test_compare_players_verdict():
    out = pl.compare_players([15, 24])  # paras MID vs huonoin MID
    assert len(out["players"]) == 2
    assert out["verdict"]["pick"]["id"] == 15
    assert out["verdict"]["margin_xp_horizon"] > 0
    with pytest.raises(rt.RateTeamError):
        pl.compare_players([15])
    with pytest.raises(rt.RateTeamError):
        pl.compare_players([15, 15])
    with pytest.raises(rt.RateTeamError) as e:
        pl.compare_players([15, 99999])
    assert e.value.status_code == 404


# ---------------------------------------------------------------------------
# Endpoint-smoket
# ---------------------------------------------------------------------------

def test_endpoint_plan(client):
    r = client.get("/api/fantasy/plan?entry=424242&horizon=3")
    assert r.status_code == 200
    assert r.json()["totals"]["net_gain"] >= 0
    assert r.headers["cache-control"] == "no-store"


def test_endpoint_captain(client):
    r = client.get("/api/fantasy/captain?entry=424242")
    assert r.status_code == 200 and len(r.json()["top3"]) == 3


def test_endpoint_differentials(client):
    r = client.get("/api/fantasy/differentials?max_ownership=10")
    assert r.status_code == 200 and r.json()["players"]


def test_endpoint_compare(client):
    r = client.get("/api/fantasy/compare?players=15,24")
    assert r.status_code == 200
    assert r.json()["verdict"]["pick"]["id"] == 15
    r = client.get("/api/fantasy/compare?players=15,abc")
    assert r.status_code == 400
