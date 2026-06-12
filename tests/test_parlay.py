"""POST /api/parlay -testit: kontrakti, validointirajat, tulon oikeellisuus.

Nopeat testit käyttävät WC-legejä (esirakennettu malli, ei fittiä) → CI-kelpoisia.
Domestic-leg-testi on @slow (vaatii lokaalin football-data-datan).
"""
from __future__ import annotations

import time

import pytest

WC = {"leagues": ["INT-World Cup"], "seasons": ["2018", "2022"]}


def _wc_leg(home, away, pick):
    return {"home_team": home, "away_team": away, "pick": pick, **WC}


LEGS_3 = [
    _wc_leg("Brazil", "France", "1"),
    _wc_leg("Mexico", "South Africa", "1"),
    _wc_leg("Tunisia", "Congo DR", "X"),
]


def test_contract_fields_and_echo(client):
    r = client.post("/api/parlay", json={"legs": LEGS_3})
    assert r.status_code == 200
    b = r.json()
    assert set(b) == {"legs", "n_legs", "combined_probability",
                      "assumes_independence", "note", "disclaimer"}
    assert b["n_legs"] == 3 and len(b["legs"]) == 3
    assert b["assumes_independence"] is True
    assert "independent" in b["note"]
    assert b["disclaimer"] == "Model prediction, not betting advice."
    for leg, sent in zip(b["legs"], LEGS_3):
        assert leg["home_team"] == sent["home_team"]
        assert leg["pick"] == sent["pick"]
        assert set(leg) == {"home_team", "away_team", "leagues", "pick",
                            "p_home_win", "p_draw", "p_away_win", "pick_probability"}
        assert leg["p_home_win"] + leg["p_draw"] + leg["p_away_win"] == pytest.approx(1.0, abs=2e-4)


def test_no_gambling_vocabulary_in_response(client):
    """Gambling-turvallinen linja: ei odds/betting/stake-sanastoa outputissa."""
    r = client.post("/api/parlay", json={"legs": LEGS_3})
    text = r.text.lower()
    for word in ("odds", "stake", "payout", "wager"):
        assert word not in text, f"kielletty sanasto vastauksessa: {word!r}"
    # disclaimerin "not betting advice" on ainoa sallittu betting-esiintymä
    assert text.count("betting") == 1


def test_combined_is_product_of_leg_probabilities(client):
    """Tulon oikeellisuus käsinlaskettuna: combined == round(prod(pick_p), 6),
    ja pick_probability poimii oikean kentän (1->home, X->draw, 2->away)."""
    r = client.post("/api/parlay", json={"legs": LEGS_3})
    b = r.json()
    prod = 1.0
    key = {"1": "p_home_win", "X": "p_draw", "2": "p_away_win"}
    for leg in b["legs"]:
        assert leg["pick_probability"] == leg[key[leg["pick"]]]
        prod *= leg["pick_probability"]
    assert b["combined_probability"] == round(prod, 6)


def test_legs_match_predict_wc_endpoint(client):
    """Parlay-legin 1X2 == /api/predict-wc:n 1X2 samalle parille (sama malli,
    sama neutralointi, sama pyöristys)."""
    single = client.post("/api/predict-wc", json={
        "home_team": "Brazil", "away_team": "France", **WC}).json()
    parlay = client.post("/api/parlay", json={"legs": LEGS_3}).json()
    leg = parlay["legs"][0]
    assert leg["p_home_win"] == single["p_home_win"]
    assert leg["p_draw"] == single["p_draw"]
    assert leg["p_away_win"] == single["p_away_win"]


@pytest.mark.parametrize("n,expected", [(1, 422), (2, 200), (5, 200), (6, 422)])
def test_leg_count_bounds(client, n, expected):
    pairs = [("Brazil", "France"), ("Mexico", "South Africa"),
             ("Tunisia", "Congo DR"), ("Spain", "Iran"),
             ("England", "Haiti"), ("Argentina", "Norway")]
    legs = [_wc_leg(h, a, "1") for h, a in pairs[:n]]
    r = client.post("/api/parlay", json={"legs": legs})
    assert r.status_code == expected, f"n={n}: {r.text[:200]}"


def test_invalid_pick_rejected(client):
    legs = [_wc_leg("Brazil", "France", "home"), _wc_leg("Spain", "Iran", "1")]
    assert client.post("/api/parlay", json={"legs": legs}).status_code == 422


def test_duplicate_match_rejected(client):
    legs = [_wc_leg("Brazil", "France", "1"), _wc_leg("Brazil", "France", "X")]
    r = client.post("/api/parlay", json={"legs": legs})
    assert r.status_code == 422
    assert "Duplicate" in r.text


def test_unknown_team_404_with_leg_index(client):
    legs = [_wc_leg("Brazil", "France", "1"), _wc_leg("Finland", "Spain", "1")]
    r = client.post("/api/parlay", json={"legs": legs})
    assert r.status_code == 404
    assert "Leg 2" in r.json()["detail"]


def test_warm_latency_5_legs(client):
    """Lämmin 5-leg-parlay pysyy reilusti alle sekunnin (Render 0.5 vCPU
    -marginaali; lokaalisti ~ms-luokkaa)."""
    legs = [_wc_leg(h, a, "1") for h, a in [
        ("Brazil", "France"), ("Mexico", "South Africa"), ("Tunisia", "Congo DR"),
        ("Spain", "Iran"), ("England", "Haiti")]]
    client.post("/api/parlay", json={"legs": legs})  # lämmitys
    t0 = time.perf_counter()
    r = client.post("/api/parlay", json={"legs": legs})
    elapsed = time.perf_counter() - t0
    assert r.status_code == 200
    assert elapsed < 1.0, f"lämmin 5-leg-parlay kesti {elapsed:.2f}s"
    print(f"\n5-leg warm latency: {elapsed*1000:.0f} ms")


@pytest.mark.slow
def test_domestic_and_mixed_parlay(client):
    """Domestic + WC sekaisin: legit täsmäävät /api/predictin arvoihin."""
    dom = {"home_team": "Arsenal", "away_team": "Liverpool",
           "leagues": ["ENG-Premier League"], "seasons": ["2425", "2526"]}
    single = client.post("/api/predict", json=dom).json()
    legs = [{**dom, "pick": "1"}, _wc_leg("Brazil", "France", "2")]
    r = client.post("/api/parlay", json={"legs": legs})
    assert r.status_code == 200
    b = r.json()
    assert b["legs"][0]["p_home_win"] == single["p_home_win"]
    assert b["legs"][0]["p_draw"] == single["p_draw"]
    assert b["legs"][0]["pick_probability"] == single["p_home_win"]
    assert b["combined_probability"] == round(
        b["legs"][0]["pick_probability"] * b["legs"][1]["pick_probability"], 6)
