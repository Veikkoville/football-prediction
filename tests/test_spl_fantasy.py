"""SPL-fantasy-testit: league-parametri, RSL-pisteytyksen ydin, minuuttimalli.

Ei verkkoa, ei mallifittiä (sama linja kuin test_fpl_phase0). Endpoint-testit
nojaavat repoon committattuihin data/spl_*-projektioihin — jos ne puuttuvat,
loaderin available=False-runko EI saa muuttua 500:ksi.
"""
from __future__ import annotations

import math

import pytest

from scripts.build_spl_phase0 import MODEL_TO_SHORT, SHORT_TO_MODEL
from src.models import spl_xp as sx


# ---------------------------------------------------------------------------
# league-parametri: oletus fpl ennallaan, spl servaa, tuntematon 404
# ---------------------------------------------------------------------------
def test_fantasy_default_league_unchanged(client):
    r = client.get("/api/fantasy")
    assert r.status_code == 200
    # FPL-tuote — SPL-liigatunniste EI saa vuotaa oletusvastaukseen.
    assert r.json()["meta"].get("league") != "SAU-Saudi Pro League"


def test_fantasy_spl_league_serves(client):
    r = client.get("/api/fantasy?league=spl")
    assert r.status_code == 200
    meta = r.json()["meta"]
    # Committattu projektio → SPL-tunniste; puuttuva tiedosto → available=False.
    if meta.get("available"):
        assert meta["league"] == "SAU-Saudi Pro League"


def test_fantasy_unknown_league_404(client):
    assert client.get("/api/fantasy?league=elite").status_code == 404
    assert client.get("/api/fantasy/xp?league=elite").status_code == 404


def test_fantasy_xp_spl_serves_and_etag_has_league(client):
    r = client.get("/api/fantasy/xp?league=spl")
    assert r.status_code == 200
    assert '"xp-spl-' in r.headers.get("etag", "")
    r2 = client.get("/api/fantasy/xp")
    assert '"xp-fpl-' in r2.headers.get("etag", "")


# ---------------------------------------------------------------------------
# Joukkuemappaus
# ---------------------------------------------------------------------------
def test_short_map_is_bijective_18_teams():
    assert len(SHORT_TO_MODEL) == 18
    assert len(MODEL_TO_SHORT) == 18  # ei duplikaattinimiä


# ---------------------------------------------------------------------------
# e_floor-approksimaatio
# ---------------------------------------------------------------------------
def test_e_floor_zero_rate_is_zero():
    assert sx.e_floor(0.0, 3) == 0.0


def test_e_floor_below_half_threshold_is_zero():
    # keskim. 0.5 tapahtumaa, kynnys 3 → floor käytännössä aina 0
    assert sx.e_floor(0.5, 3) == 0.0


def test_e_floor_less_than_linear():
    # approksimaatio ei saa ylittää lineaarista E[X]/n-ylärajaa
    assert sx.e_floor(6.0, 3) < 6.0 / 3


# ---------------------------------------------------------------------------
# RSL-pisteytys: GK-päästetyt joka maalista ensimmäisen jälkeen
# ---------------------------------------------------------------------------
def test_expected_conceded_gk_after_first():
    # P(2 maalia) = 1 → GK-sakko täsmälleen 1 (toinen maali)
    assert sx.expected_conceded_gk([0.0, 0.0, 1.0]) == pytest.approx(1.0)
    # P(1 maali) = 1 → ei sakkoa
    assert sx.expected_conceded_gk([0.0, 1.0]) == pytest.approx(0.0)


def test_expected_conceded_def_every_two():
    assert sx.expected_conceded_def([0.0, 0.0, 1.0]) == pytest.approx(1.0)
    assert sx.expected_conceded_def([0.0, 1.0]) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# xp_components: RSL-erot FPL:ään
# ---------------------------------------------------------------------------
def _rates(**over):
    base = {f"{k}90": 0.0 for k in sx.AGG_KEYS}
    base.update(over)
    return base


def _ctx(cs=0.3):
    return {"goal_mult": 1.0, "cs_prob": cs,
            "conceded_dist": [0.4, 0.35, 0.15, 0.07, 0.03], "opp_goal_mult": 1.0}


def test_mid_goal_worth_5_and_def_goal_6():
    r = _rates(goals90=1.0)
    mid = sx.xp_components(3, r, 90.0, 1.0, 0.0, _ctx())
    dfd = sx.xp_components(2, r, 90.0, 1.0, 0.0, _ctx())
    assert mid["goals"] == pytest.approx(5.0)
    assert dfd["goals"] == pytest.approx(6.0)


def test_mid_clean_sheet_worth_1():
    comp = sx.xp_components(3, _rates(), 90.0, 1.0, 0.0, _ctx(cs=1.0))
    assert comp["clean_sheet"] == pytest.approx(1.0)


def test_gk_saves_every_two():
    comp = sx.xp_components(1, _rates(saves90=4.0), 90.0, 1.0, 0.0, _ctx())
    assert comp["saves"] == pytest.approx(2.0)  # 4 torjuntaa → 2 pistettä


def test_fwd_no_clean_sheet_points():
    comp = sx.xp_components(4, _rates(), 90.0, 1.0, 0.0, _ctx(cs=1.0))
    assert comp["clean_sheet"] == 0.0


def test_components_sum_to_total():
    r = _rates(goals90=0.5, assists90=0.3, saves90=3.0, yc90=0.2,
               tackles90=2.5, passes90=45.0, bonus90=0.4)
    comp = sx.xp_components(1, r, 90.0, 1.0, 0.0, _ctx())
    assert comp["total"] == pytest.approx(
        sum(v for k, v in comp.items() if k != "total"))
    assert math.isfinite(comp["total"])


# ---------------------------------------------------------------------------
# Minuuttimalli aggregaateista
# ---------------------------------------------------------------------------
def test_minutes_model_full_season_high_start():
    mm = sx.minutes_model_from_aggregates(34 * 86.0)
    assert mm["p_start"] == pytest.approx(0.95)
    assert mm["minutes_confidence"] == "med"


def test_minutes_model_zero_minutes():
    mm = sx.minutes_model_from_aggregates(0.0)
    assert mm["p_start"] == 0.0
    assert mm["xmins"] == 0.0
    assert mm["minutes_confidence"] == "low"


def test_minutes_model_monotone_in_minutes():
    xs = [sx.minutes_model_from_aggregates(m)["xmins"]
          for m in (0, 500, 1500, 2500)]
    assert xs == sorted(xs)


def test_scale_minutes_zero_availability():
    mm = sx.scale_minutes(sx.minutes_model_from_aggregates(2500.0), 0.0)
    assert mm["p_start"] == 0.0
    assert mm["xmins"] == 0.0


def test_availability_factor():
    assert sx.availability_factor("a", None) == 1.0
    assert sx.availability_factor("d", 75) == 0.75
    assert sx.availability_factor("i", None) == 0.0
