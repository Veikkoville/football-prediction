"""FPL Phase 1b -kontekstikerroksen testit: nousijabuusti, yliajot, xmins.

Ei verkkoa, ei mallifittiä — puhtaat funktiot.
"""
from __future__ import annotations

import pytest

from src.models import fpl_context as fc


FIXTURES = [
    {"gameweek": 1, "home": "Hull", "away": "Manchester United"},
    {"gameweek": 1, "home": "Ipswich", "away": "Sunderland"},
    {"gameweek": 2, "home": "Coventry", "away": "Hull"},
    {"gameweek": 2, "home": "Manchester United", "away": "Arsenal"},
    {"gameweek": 5, "home": "Hull", "away": "Everton"},
]
PROMOTED = {"Hull", "Ipswich", "Coventry"}


def _cfg(overrides=None):
    return fc.build_context(PROMOTED, FIXTURES, overrides)


# ---------------------------------------------------------------------------
# Nousija-koti-avaus-buusti
# ---------------------------------------------------------------------------
def test_first_home_gw():
    fh = fc.first_home_gw(FIXTURES)
    assert fh["Hull"] == 1
    assert fh["Coventry"] == 2
    assert fh["Manchester United"] == 2


def test_promoted_home_opener_boosted():
    adj, notes = fc.fixture_adjustments("Hull", "Manchester United", 1, _cfg())
    assert adj["home_factor"] == pytest.approx(fc.PROMOTED_HOME_OPENER_ATT_BOOST)
    assert adj["away_factor"] == 1.0
    assert any("promoted-home-opener" in n for n in notes)


def test_promoted_second_home_game_not_boosted():
    # Hullin 2. kotipeli (GW5) — ei buustia
    adj, _ = fc.fixture_adjustments("Hull", "Everton", 5, _cfg())
    assert adj is None


def test_promoted_away_not_boosted():
    # Hull vieraissa Coventryn koti-avauksessa: vain Coventry saa buustin
    adj, _ = fc.fixture_adjustments("Coventry", "Hull", 2, _cfg())
    assert adj["home_factor"] == pytest.approx(fc.PROMOTED_HOME_OPENER_ATT_BOOST)
    assert adj["away_factor"] == 1.0


def test_non_promoted_home_opener_not_boosted():
    adj, _ = fc.fixture_adjustments("Manchester United", "Arsenal", 2, _cfg())
    assert adj is None


def test_no_cfg_returns_raw():
    adj, notes = fc.fixture_adjustments("Hull", "Manchester United", 1, None)
    assert adj is None and notes == []


def test_promoted_teams_set_difference():
    assert fc.promoted_teams({"A", "B", "C"}, {"A", "B", "X"}) == {"C"}


# ---------------------------------------------------------------------------
# Manuaaliset yliajot
# ---------------------------------------------------------------------------
def _row(**kw):
    base = {"scope": "manual", "team": "", "opponent": None, "venue": None,
            "gw_from": None, "gw_to": None, "attack_mult": 1.0,
            "defence_mult": 1.0, "xmins_mult": 1.0, "note": ""}
    base.update(kw)
    return base


def test_override_attack_mult_applies_to_own_lambda():
    ov = [_row(team="Everton", venue="H", attack_mult=1.2)]
    adj, _ = fc.fixture_adjustments("Everton", "Arsenal", 10, _cfg(ov))
    assert adj["home_factor"] == pytest.approx(1.2)
    assert adj["away_factor"] == 1.0


def test_override_defence_mult_applies_to_opponent_lambda():
    # Evertonin puolustus vuotaa -> VASTUSTAJAN maaliodotus ylös
    ov = [_row(team="Everton", defence_mult=1.15)]
    adj, _ = fc.fixture_adjustments("Everton", "Arsenal", 10, _cfg(ov))
    assert adj["away_factor"] == pytest.approx(1.15)
    assert adj["home_factor"] == 1.0


def test_override_gw_range_filter():
    ov = [_row(team="Everton", attack_mult=1.5, gw_from=1, gw_to=3)]
    adj_in, _ = fc.fixture_adjustments("Everton", "Arsenal", 2, _cfg(ov))
    adj_out, _ = fc.fixture_adjustments("Everton", "Arsenal", 4, _cfg(ov))
    assert adj_in["home_factor"] == pytest.approx(1.5)
    assert adj_out is None


def test_override_opponent_and_venue_filter():
    ov = [_row(team="Everton", opponent="Arsenal", venue="A", attack_mult=1.3)]
    adj_match, _ = fc.fixture_adjustments("Arsenal", "Everton", 10, _cfg(ov))
    assert adj_match["away_factor"] == pytest.approx(1.3)
    adj_wrong_venue, _ = fc.fixture_adjustments("Everton", "Arsenal", 10, _cfg(ov))
    assert adj_wrong_venue is None


def test_override_stacks_with_promoted_boost():
    ov = [_row(team="Hull", venue="H", attack_mult=1.1)]
    adj, _ = fc.fixture_adjustments("Hull", "Manchester United", 1, _cfg(ov))
    assert adj["home_factor"] == pytest.approx(
        fc.PROMOTED_HOME_OPENER_ATT_BOOST * 1.1)


# ---------------------------------------------------------------------------
# xMins-kerroin (MM-väsymys)
# ---------------------------------------------------------------------------
def test_xmins_multiplier_team_gw_range():
    ov = [_row(scope="wc_fatigue", team="Manchester City", xmins_mult=0.9,
               gw_from=1, gw_to=3)]
    cfg = _cfg(ov)
    assert fc.xmins_multiplier("Manchester City", 2, cfg) == pytest.approx(0.9)
    assert fc.xmins_multiplier("Manchester City", 4, cfg) == 1.0
    assert fc.xmins_multiplier("Arsenal", 2, cfg) == 1.0


def test_xmins_multiplier_requires_blank_opponent_venue():
    # xmins-rivi jolla opponent/venue-suodatin EI saa osua (fixture-kohtainen
    # minuuttikerroin ei ole tuettu semantiikka)
    ov = [_row(team="Manchester City", opponent="Arsenal", xmins_mult=0.5)]
    assert fc.xmins_multiplier("Manchester City", 2, _cfg(ov)) == 1.0


# ---------------------------------------------------------------------------
# CSV-parsinta
# ---------------------------------------------------------------------------
def test_load_overrides_missing_file(tmp_path):
    assert fc.load_overrides(tmp_path / "ei-ole.csv") == []


def test_load_overrides_parses_and_skips_comments(tmp_path):
    p = tmp_path / "ov.csv"
    p.write_text(
        "# kommentti\n"
        "scope,team,opponent,venue,gw_from,gw_to,attack_mult,defence_mult,xmins_mult,note\n"
        "wc_fatigue,Manchester City,,,1,3,0.92,1.05,0.90,testi\n"
        "manual,Hull,Manchester United,H,1,1,1.15,,,avaus\n",
        encoding="utf-8")
    rows = fc.load_overrides(p)
    assert len(rows) == 2
    assert rows[0]["scope"] == "wc_fatigue"
    assert rows[0]["xmins_mult"] == pytest.approx(0.90)
    assert rows[1]["venue"] == "H"
    assert rows[1]["defence_mult"] == 1.0  # tyhjä -> neutraali


def test_load_overrides_skips_bad_row(tmp_path):
    p = tmp_path / "ov.csv"
    p.write_text(
        "scope,team,opponent,venue,gw_from,gw_to,attack_mult,defence_mult,xmins_mult,note\n"
        "manual,Everton,,,EI-NUMERO,,1.1,,,rikki\n"
        "manual,Everton,,,,,1.2,,,ok\n",
        encoding="utf-8")
    rows = fc.load_overrides(p)
    assert len(rows) == 1
    assert rows[0]["attack_mult"] == pytest.approx(1.2)


def test_repo_overrides_template_parses():
    # Repoon committattu template ei saa kaataa parseria (vain header + kommentit)
    rows = fc.load_overrides(fc.OVERRIDES_PATH)
    assert isinstance(rows, list)
