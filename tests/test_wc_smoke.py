"""predict-wc smoke: summat, 48 maan saatavuus, neutraali-venue-symmetria.

Korvaa manuaalisen käänteispari-verifioinnin (CLAUDE.md sääntö 2, #61).
Käyttää esirakennettua data/wc_model.json:ia — ei fittiä, nopea.
"""
from __future__ import annotations

import pytest

from src.data.wc_teams import WC2026_TEAMS

TOL = 1e-9


def _predict(client, home, away):
    r = client.post("/api/predict-wc", json={
        "home_team": home, "away_team": away,
        "leagues": ["INT-World Cup"], "seasons": ["2018", "2022"],
    })
    return r


def test_probabilities_sum_to_one(client):
    r = _predict(client, "Mexico", "South Africa")
    assert r.status_code == 200
    b = r.json()
    assert b["p_home_win"] + b["p_draw"] + b["p_away_win"] == pytest.approx(1.0, abs=TOL)
    assert b["p_over_2_5"] + b["p_under_2_5"] == pytest.approx(1.0, abs=TOL)
    assert b["p_btts_yes"] + b["p_btts_no"] == pytest.approx(1.0, abs=TOL)
    assert all(0.0 <= b[k] <= 1.0 for k in
               ("p_home_win", "p_draw", "p_away_win"))


@pytest.mark.parametrize("team", WC2026_TEAMS)
def test_all_48_teams_have_model_data(client, team):
    """Jokainen mallissa nyt oleva WC-maa -> 200, ei 404 (sekundaarivahti)."""
    opponent = "Brazil" if team != "Brazil" else "Argentina"
    r = _predict(client, team, opponent)
    assert r.status_code == 200, f"{team}: HTTP {r.status_code} {r.text[:200]}"


def test_neutral_venue_symmetry(client):
    """Brazil<->France: home/away-vaihto -> peilatut numerot (neutraali venue)."""
    a = _predict(client, "Brazil", "France").json()
    b = _predict(client, "France", "Brazil").json()
    assert a["p_home_win"] == pytest.approx(b["p_away_win"], abs=TOL)
    assert a["p_away_win"] == pytest.approx(b["p_home_win"], abs=TOL)
    assert a["p_draw"] == pytest.approx(b["p_draw"], abs=TOL)
    assert a["expected_goals_home"] == pytest.approx(b["expected_goals_away"], abs=TOL)
    assert a["expected_goals_away"] == pytest.approx(b["expected_goals_home"], abs=TOL)
    assert a["p_over_2_5"] == pytest.approx(b["p_over_2_5"], abs=TOL)
    assert a["p_btts_yes"] == pytest.approx(b["p_btts_yes"], abs=TOL)
    # top_scores peilautuu: "2-1" <-> "1-2" samalla todennäköisyydellä.
    # Sama matriisi transposattuna -> top-N-joukot identtiset peilattuina.
    assert a["top_scores"] and b["top_scores"]
    def _mirror(score: str) -> str:
        h, sep, w = score.partition("-")
        assert sep, f"odottamaton score-formaatti: {score!r}"
        return f"{w}-{h}"
    mirror = {_mirror(s["score"]): s["probability"] for s in b["top_scores"]}
    for s in a["top_scores"]:
        assert s["score"] in mirror, f"{s['score']} puuttuu peilatusta top-listasta"
        assert s["probability"] == pytest.approx(mirror[s["score"]], abs=TOL)


def test_alias_input_resolves_in_endpoint(client):
    """Endpoint hyväksyy variantit (Korea Republic -> South Korea)."""
    r = _predict(client, "Korea Republic", "Türkiye")
    assert r.status_code == 200


def test_non_wc_team_404(client):
    r = _predict(client, "Finland", "Brazil")
    assert r.status_code == 404


def test_wrong_league_400(client):
    r = client.post("/api/predict-wc", json={
        "home_team": "Brazil", "away_team": "France",
        "leagues": ["ENG-Premier League"], "seasons": ["2018"],
    })
    assert r.status_code == 400
