"""FPL Phase 1 xP -testit: loader-fallback, endpointin muoto, kaavan sanityt.

Ei verkkoa, ei mallifittiä — builderin/backtestin verkko- ja fit-polut
ajetaan vain oikeissa joboissa. Domestic-malliin ei kosketa.
"""
from __future__ import annotations

import json

import pytest

from src.models import fpl_xp as xp


# ---------------------------------------------------------------------------
# Loader (peili: test_fpl_phase0)
# ---------------------------------------------------------------------------
def test_load_xp_missing_file_returns_empty(tmp_path):
    data = xp.load_xp(tmp_path / "ei-ole.json")
    assert data["meta"]["available"] is False
    assert data["players"] == []


def test_load_xp_corrupt_file_returns_empty(tmp_path):
    p = tmp_path / "rikki.json"
    p.write_text("{ei json", encoding="utf-8")
    assert xp.load_xp(p)["meta"]["available"] is False


def test_load_xp_reads_valid_file(tmp_path):
    payload = {
        "meta": {"available": True, "next_gameweek": 1},
        "players": [{"id": 1, "web_name": "Testaaja", "gameweeks": []}],
    }
    p = tmp_path / "ok.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    assert xp.load_xp(p) == payload


# ---------------------------------------------------------------------------
# #143: data_basis — estimaatin datapohja-luokka (puhdas emissio)
# ---------------------------------------------------------------------------
def test_data_basis_no_history():
    assert xp.data_basis({"mins": 0}) == xp.DATA_BASIS_NONE


def test_data_basis_limited_history():
    assert xp.data_basis({"mins": 200.0}) == xp.DATA_BASIS_LIMITED


def test_data_basis_threshold_boundary():
    # Raja on M_PRIOR_ATTACK (_shrink90:n 50 %-piste): alle = priori dominoi.
    assert xp.data_basis({"mins": xp.M_PRIOR_ATTACK - 1}) == xp.DATA_BASIS_LIMITED
    assert xp.data_basis({"mins": xp.M_PRIOR_ATTACK}) == xp.DATA_BASIS_FULL


def test_data_basis_full_history():
    assert xp.data_basis({"mins": 3000.0}) == xp.DATA_BASIS_FULL


def test_data_basis_defensive_inputs():
    # Puuttuva/None-mins ei saa kaataa; palautusarvo aina tunnettu luokka.
    assert xp.data_basis({}) == xp.DATA_BASIS_NONE
    assert xp.data_basis({"mins": None}) == xp.DATA_BASIS_NONE
    for acc in ({}, {"mins": None}, {"mins": 0}, {"mins": 10}, {"mins": 5000}):
        assert xp.data_basis(acc) in xp.DATA_BASIS_VALUES


# ---------------------------------------------------------------------------
# #151: 26/27 BPS-oikaisu (bonus-historian uudelleenjako)
# ---------------------------------------------------------------------------
def test_bps_2627_delta_cbi_only():
    # 12 CBI: vanha 12//2=6 BPS, uusi 12//3=4 -> delta -2. Ei pilkkutorjuntoja.
    assert xp.bps_2627_delta({"clearances_blocks_interceptions": 12}) == -2
    # 5 CBI: vanha 2, uusi 1 -> -1.
    assert xp.bps_2627_delta({"clearances_blocks_interceptions": 5}) == -1
    # 0-2 CBI: molemmilla 0 tai sama floor -> 0 / -1 rajat.
    assert xp.bps_2627_delta({"clearances_blocks_interceptions": 0}) == 0
    assert xp.bps_2627_delta({"clearances_blocks_interceptions": 2}) == -1


def test_bps_2627_delta_penalty_save():
    assert xp.bps_2627_delta({"penalties_saved": 1}) == -1
    assert xp.bps_2627_delta({"penalties_saved": 2,
                              "clearances_blocks_interceptions": 6}) == -3


def test_bps_2627_delta_defensive_inputs():
    assert xp.bps_2627_delta({}) == 0
    assert xp.bps_2627_delta({"clearances_blocks_interceptions": None,
                              "penalties_saved": None}) == 0


def test_allocate_bonus_plain_top3():
    assert xp.allocate_bonus([30, 25, 20, 10]) == [3, 2, 1, 0]


def test_allocate_bonus_tie_for_first():
    # Tasoissa 1.: molemmat 3, seuraava 1 (2 pistettä ei jaeta).
    assert xp.allocate_bonus([30, 30, 20, 10]) == [3, 3, 1, 0]


def test_allocate_bonus_tie_for_second():
    # Tasoissa 2.: 1. saa 3, tasoissa olevat 2, 1 pistettä ei jaeta.
    assert xp.allocate_bonus([30, 25, 25, 10]) == [3, 2, 2, 0]


def test_allocate_bonus_tie_for_third():
    assert xp.allocate_bonus([30, 25, 20, 20, 10]) == [3, 2, 1, 1, 0]


def test_allocate_bonus_short_lists():
    assert xp.allocate_bonus([]) == []
    assert xp.allocate_bonus([10]) == [3]
    assert xp.allocate_bonus([10, 5]) == [3, 2]


def test_adjust_summaries_reallocates_and_is_pure():
    # Ottelu 1: A (CB, bps 30 josta iso CBI-osuus) vs B (bps 29, ei CBI:tä).
    # Vanha jako: A=3, B=2. 26/27: A:n 12 CBI -> -2 BPS -> A 28 < B 29 -> flip.
    row_a = {"fixture": 1, "minutes": 90, "bps": 30, "bonus": 3,
             "clearances_blocks_interceptions": 12}
    row_b = {"fixture": 1, "minutes": 90, "bps": 29, "bonus": 2,
             "clearances_blocks_interceptions": 0}
    row_c = {"fixture": 1, "minutes": 90, "bps": 10, "bonus": 1,
             "clearances_blocks_interceptions": 0}
    summaries = {101: [dict(row_a)], 102: [dict(row_b)], 103: [dict(row_c)]}
    out = xp.adjust_summaries_bps_2627(summaries)
    assert out[102][0]["bonus"] == 3   # nousi
    assert out[101][0]["bonus"] == 2   # laski
    assert out[103][0]["bonus"] == 1   # ennallaan
    # Puhtaus: syöte ei mutatoitunut.
    assert summaries[101][0]["bonus"] == 3
    assert summaries[102][0]["bonus"] == 2


def test_adjust_summaries_zero_minutes_excluded():
    # 0 min pelannut ei osallistu jakoon eikä saa bonusta.
    summaries = {
        1: [{"fixture": 7, "minutes": 0, "bps": 50, "bonus": 0}],
        2: [{"fixture": 7, "minutes": 90, "bps": 10, "bonus": 3}],
    }
    out = xp.adjust_summaries_bps_2627(summaries)
    assert out[1][0]["bonus"] == 0
    assert out[2][0]["bonus"] == 3


def test_adjust_summaries_total_bonus_conserved_no_ties():
    # Ilman tasapelejä ottelun bonuspotti pysyy 3+2+1:nä.
    summaries = {i: [{"fixture": 5, "minutes": 90, "bps": 40 - 2 * i, "bonus": 0,
                      "clearances_blocks_interceptions": 0}]
                 for i in range(1, 8)}
    out = xp.adjust_summaries_bps_2627(summaries)
    total = sum(out[i][0]["bonus"] for i in range(1, 8))
    assert total == 6


# ---------------------------------------------------------------------------
# Endpoint (TestClient conftestista)
# ---------------------------------------------------------------------------
def test_fantasy_xp_endpoint_shape(client):
    r = client.get("/api/fantasy/xp")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-store"
    data = r.json()
    assert "meta" in data and "players" in data
    assert isinstance(data["players"], list)


# ---------------------------------------------------------------------------
# Minuuttimalli
# ---------------------------------------------------------------------------
def test_minutes_form_full_starter():
    mins = {r: 90 for r in range(1, 11)}
    xmins, p60, p1 = xp.minutes_form(mins, list(range(1, 11)))
    assert xmins == pytest.approx(90.0)
    assert p60 == pytest.approx(1.0)
    assert p1 == pytest.approx(0.0)


def test_minutes_form_no_history():
    assert xp.minutes_form({}, []) == (0.0, 0.0, 0.0)


def test_minutes_form_benched_recently_decays():
    # Pelasi 90 min kierrokset 1-3, penkillä (0 min) kierrokset 4-5:
    # recency-painotus painaa xMinsin alle puoleen.
    mins = {1: 90, 2: 90, 3: 90, 4: 0, 5: 0}
    xmins, p60, _ = xp.minutes_form(mins, [1, 2, 3, 4, 5])
    assert xmins < 45.0
    assert p60 < 0.5


def test_minutes_form_full_window_uniform():
    # n_last=None (pre-season): koko kausi tasapainoin — lopun rotaatio
    # ei romahduta xMinsiä. 33x90 + 5x20 -> keskiarvo ~80.8, ei ~30.
    mins = {r: 90 for r in range(1, 34)}
    mins.update({r: 20 for r in range(34, 39)})
    rounds = list(range(1, 39))
    xmins_all, p60_all, _ = xp.minutes_form(mins, rounds, n_last=None)
    xmins_l5, _, _ = xp.minutes_form(mins, rounds, n_last=5)
    assert xmins_all == pytest.approx((33 * 90 + 5 * 20) / 38)
    assert p60_all == pytest.approx(33 / 38)
    assert xmins_l5 == pytest.approx(20.0)


def test_minutes_form_missing_round_counts_as_zero():
    # Kierros ilman riviä (esim. loukkaantunut) = 0 min, ei kaadu.
    mins = {1: 90}
    xmins, _, _ = xp.minutes_form(mins, [1, 2, 3, 4, 5])
    assert 0.0 < xmins < 20.0


# ---------------------------------------------------------------------------
# Vauhdit + shrinkage
# ---------------------------------------------------------------------------
def _acc(**kw):
    base = {"mins": 0.0, "xg": 0.0, "xa": 0.0, "saves": 0.0,
            "yc": 0.0, "bonus": 0.0, "n60": 0, "dc_hits": 0}
    base.update(kw)
    return base


PRIORS = {p: {"xg90": 0.2, "xa90": 0.1, "saves90": 0.0, "yc90": 0.15,
              "bonus90": 0.1, "dc_freq": 0.2} for p in xp.POS_NAME}


def test_player_rates_zero_minutes_returns_prior():
    rates = xp.player_rates(_acc(), 4, PRIORS)
    assert rates["xg90"] == pytest.approx(0.2)
    assert rates["dc_freq"] == pytest.approx(0.2)


def test_player_rates_large_sample_dominates_prior():
    # 3000 min ja 30 xG (0.9/90) >> priori 0.2 -> vauhti lähellä havaittua.
    rates = xp.player_rates(_acc(mins=3000.0, xg=30.0), 4, PRIORS)
    assert rates["xg90"] > 0.75


def test_accumulate_history_parses_string_xg():
    rows = [{"minutes": 90, "expected_goals": "0.85", "expected_assists": "0.10",
             "saves": 0, "yellow_cards": 1, "bonus": 2}]
    acc = xp.accumulate_history(rows)
    assert acc["xg"] == pytest.approx(0.85)
    assert acc["n60"] == 1
    assert acc["yc"] == 1


def test_dc_hit_thresholds():
    assert xp.dc_hit({"defensive_contribution": 10}, 2) is True   # DEF: CBIT >= 10
    assert xp.dc_hit({"defensive_contribution": 9}, 2) is False
    assert xp.dc_hit({"defensive_contribution": 12}, 3) is True   # MID: CBIRT >= 12
    assert xp.dc_hit({"defensive_contribution": 11}, 3) is False
    assert xp.dc_hit({"defensive_contribution": 99}, 1) is False  # GKP: ei DC-pisteitä


# ---------------------------------------------------------------------------
# xP-komponentit
# ---------------------------------------------------------------------------
CTX = {"goal_mult": 1.0, "cs_prob": 0.5,
       "conceded_dist": [0.5, 0.3, 0.15, 0.05], "opp_goal_mult": 1.0}


def _rates(**kw):
    base = {"xg90": 0.0, "xa90": 0.0, "saves90": 0.0, "yc90": 0.0,
            "bonus90": 0.0, "dc_freq": 0.0}
    base.update(kw)
    return base


def test_xp_appearance_points():
    comp = xp.xp_components(4, _rates(), 90.0, 1.0, 0.0, CTX)
    assert comp["appearance"] == pytest.approx(2.0)
    comp = xp.xp_components(4, _rates(), 30.0, 0.0, 1.0, CTX)
    assert comp["appearance"] == pytest.approx(1.0)


def test_xp_goal_points_by_position():
    # Sama E[maalit]=0.5: FWD 4 p/maali, MID 5, DEF 6, GKP 10 (25/26-sääntö).
    for pos, pts in ((4, 4), (3, 5), (2, 6), (1, 10)):
        comp = xp.xp_components(pos, _rates(xg90=0.5), 90.0, 1.0, 0.0, CTX)
        assert comp["goals"] == pytest.approx(0.5 * pts)


def test_xp_clean_sheet_only_gk_def_mid():
    for pos, pts in ((1, 4), (2, 4), (3, 1), (4, 0)):
        comp = xp.xp_components(pos, _rates(), 90.0, 1.0, 0.0, CTX)
        assert comp["clean_sheet"] == pytest.approx(0.5 * pts)


def test_xp_conceded_penalty_negative_for_def():
    # E[floor(k/2)] = 0.15*1 + 0.05*1 = 0.20 -> -0.20 DEF:lle täydellä pelillä
    comp = xp.xp_components(2, _rates(), 90.0, 1.0, 0.0, CTX)
    assert comp["conceded"] == pytest.approx(-0.20)
    comp_fwd = xp.xp_components(4, _rates(), 90.0, 1.0, 0.0, CTX)
    assert comp_fwd["conceded"] == 0.0


def test_xp_saves_only_gk():
    comp = xp.xp_components(1, _rates(saves90=3.0), 90.0, 1.0, 0.0, CTX)
    assert comp["saves"] == pytest.approx(1.0)
    assert xp.xp_components(2, _rates(saves90=3.0), 90.0, 1.0, 0.0, CTX)["saves"] == 0.0


def test_xp_goal_mult_scales_attack():
    easy = dict(CTX, goal_mult=1.5)
    hard = dict(CTX, goal_mult=0.6)
    c_easy = xp.xp_components(4, _rates(xg90=0.5), 90.0, 1.0, 0.0, easy)
    c_hard = xp.xp_components(4, _rates(xg90=0.5), 90.0, 1.0, 0.0, hard)
    assert c_easy["goals"] > c_hard["goals"]


def test_xp_total_is_component_sum():
    comp = xp.xp_components(3, _rates(xg90=0.3, xa90=0.2, yc90=0.2, bonus90=0.5,
                                      dc_freq=0.3), 90.0, 0.9, 0.1, CTX)
    assert comp["total"] == pytest.approx(
        sum(v for k, v in comp.items() if k != "total"))


def test_expected_conceded_penalty():
    # P(2)=1 -> floor(2/2)=1 piste menetetty
    assert xp.expected_conceded_penalty([0.0, 0.0, 1.0]) == pytest.approx(1.0)
    # P(3)=1 -> floor(3/2)=1
    assert xp.expected_conceded_penalty([0.0, 0.0, 0.0, 1.0]) == pytest.approx(1.0)
    # P(0)=1 -> 0
    assert xp.expected_conceded_penalty([1.0]) == 0.0
