"""#77b/#16b — h2h-rivien pakkapelikäsittely: näyttöscore ilman pakkoja + penalties-lippu.

Ankkuritapaus #77b: PSG-Arsenal CL-finaali 30.5.2026 (FD fullTime 5-4 = 1-1 + pakat
4-3) -> h2h-rivin pitää näyttää 1-1 + penalties: true + penalty_winner: home.

Ankkuritapaus #16b: WC-polku (martj42, ei disp-saraketta) -> reg+ET-tasapeli joka
ratkesi pakoilla luetaan vendoroidusta shootouts.csv:stä. Argentina-France 2022-
finaali (reg 3-3, Argentina voitti pakoilla) -> penalties: true + penalty_winner +
summary kirjaa Argentina-voiton EIKÄ tasapeliä.
"""
from __future__ import annotations

import pandas as pd
import pytest

from api.main import _h2h_item, _h2h_summary, _shootout_winner


def _row(**kw):
    base = dict(date=pd.Timestamp("2026-05-30"), home_team="A", away_team="B")
    base.update(kw)
    return pd.Series(base)


def test_h2h_item_penalty_shootout():
    """fullTime sis. pakat, disp = reg+ET -> disp näytetään + penalties true."""
    item = _h2h_item(_row(home_score=5, away_score=4,
                          home_score_disp=1, away_score_disp=1))
    assert item["home_score"] == 1 and item["away_score"] == 1
    assert item["penalties"] is True
    assert item["penalty_winner"] == "home"


def test_h2h_item_penalty_winner_away():
    item = _h2h_item(_row(home_score=4, away_score=5,
                          home_score_disp=1, away_score_disp=1))
    assert item["penalties"] is True and item["penalty_winner"] == "away"


def test_h2h_item_normal_match_with_disp():
    """Ei-pakkapeli: disp == fullTime -> penalties false, ei winner-kenttää."""
    item = _h2h_item(_row(home_score=2, away_score=1,
                          home_score_disp=2, away_score_disp=1))
    assert item["home_score"] == 2 and item["away_score"] == 1
    assert item["penalties"] is False
    assert "penalty_winner" not in item


def test_h2h_item_source_without_disp_columns():
    """understat-PL / martj42-WC: ei disp-sarakkeita -> fullTime + false."""
    item = _h2h_item(_row(home_score=3, away_score=3))
    assert item["home_score"] == 3 and item["away_score"] == 3
    assert item["penalties"] is False


def test_h2h_item_nan_disp_falls_back():
    """Sekadata (concat eri lähteistä): NaN-disp -> fallback fullTimeen."""
    item = _h2h_item(_row(home_score=2, away_score=0,
                          home_score_disp=float("nan"), away_score_disp=float("nan")))
    assert item["home_score"] == 2 and item["away_score"] == 0
    assert item["penalties"] is False


@pytest.mark.slow
def test_psg_arsenal_cl_final_via_api(client):
    """End-to-end: CL-finaali 30.5.2026 näkyy 1-1 (pens, home) eikä 5-4."""
    r = client.post("/api/predict", json={
        "home_team": "Paris Saint-Germain FC", "away_team": "Arsenal FC",
        "leagues": ["INT-Champions League"], "seasons": ["2425", "2526"],
    })
    assert r.status_code == 200
    rows = [m for m in r.json()["h2h"] if m["date"] == "2026-05-30"]
    assert rows, "CL-finaali 30.5.2026 puuttuu h2h-listalta"
    m = rows[0]
    assert (m["home_score"], m["away_score"]) == (1, 1), f"odotettu 1-1, saatiin {m}"
    assert m["penalties"] is True
    assert m["penalty_winner"] == "home"  # PSG voitti pakoilla 4-3


# --- #16b: vendoroitu shootouts-lookup (WC-polku) ---------------------------

_LOOKUP = {("2022-12-18", frozenset({"Argentina", "France"})): "Argentina"}


def _wc_row(home, away, hs, aws, date="2022-12-18"):
    """martj42-tyylinen rivi: reg+ET-score, EI disp-saraketta."""
    return pd.Series(dict(date=pd.Timestamp(date), home_team=home, away_team=away,
                          home_score=hs, away_score=aws))


def test_shootout_winner_orientation_independent():
    """Lookup täsmää joukkuepariin kummassakin home/away-järjestyksessä."""
    assert _shootout_winner(_wc_row("Argentina", "France", 3, 3), _LOOKUP) == "home"
    assert _shootout_winner(_wc_row("France", "Argentina", 3, 3), _LOOKUP) == "away"


def test_shootout_winner_none_without_lookup():
    """Ei lookupia (domestic) -> None, ei pakkapeli-kirjausta."""
    assert _shootout_winner(_wc_row("Argentina", "France", 3, 3), None) is None
    assert _shootout_winner(_wc_row("Argentina", "France", 3, 3), {}) is None


def test_h2h_item_shootout_lookup_marks_penalties():
    """martj42-tasapeli + osuma lookupissa -> penalties true + penalty_winner."""
    item = _h2h_item(_wc_row("Argentina", "France", 3, 3), _LOOKUP)
    assert (item["home_score"], item["away_score"]) == (3, 3)
    assert item["penalties"] is True
    assert item["penalty_winner"] == "home"


def test_h2h_item_shootout_lookup_no_match_stays_false():
    """Tasapeli ilman lookup-osumaa -> penalties false (esim. ryhmävaihe-draw)."""
    item = _h2h_item(_wc_row("Argentina", "France", 1, 1, date="2050-01-01"), _LOOKUP)
    assert item["penalties"] is False
    assert "penalty_winner" not in item


def test_h2h_item_non_draw_ignores_lookup():
    """Ei-tasapeli ei koskaan kysy lookupia (pakat vain tasapelistä)."""
    item = _h2h_item(_wc_row("Argentina", "France", 2, 1), _LOOKUP)
    assert item["penalties"] is False and "penalty_winner" not in item


def test_h2h_summary_shootout_counts_winner_not_draw():
    """#16b: pakkapelivoitto kirjautuu voittajalle eikä tasapeliksi."""
    h2h_all = pd.DataFrame([_wc_row("Argentina", "France", 3, 3).to_dict()])
    # Ilman lookupia (vanha käytös): tasapeli.
    old = _h2h_summary(h2h_all, "Argentina", "France")
    assert old["draws"] == 1 and old["home_team_wins"] == 0
    # Lookupilla (#16b): Argentina-voitto.
    fixed = _h2h_summary(h2h_all, "Argentina", "France", _LOOKUP)
    assert fixed["home_team_wins"] == 1 and fixed["draws"] == 0
    assert fixed["total_matches"] == 1


@pytest.mark.slow
def test_wc_h2h_argentina_france_2022_penalty_via_api(client):
    """End-to-end WC: 2022-finaali 3-3 näkyy penalties=true + Argentina-voitto."""
    r = client.post("/api/predict-wc", json={
        "home_team": "Argentina", "away_team": "France",
        "leagues": ["INT-World Cup"], "seasons": ["2018", "2022"],
    })
    assert r.status_code == 200
    data = r.json()
    rows = [m for m in data["h2h"] if m["date"] == "2022-12-18"]
    assert rows, "Argentina-France 2022-finaali puuttuu h2h-listalta"
    m = rows[0]
    assert (m["home_score"], m["away_score"]) == (3, 3)
    assert m["penalties"] is True
    assert m["penalty_winner"] == "home"  # Argentina (koti) voitti pakoilla 4-2
    # summary: pakkapelivoitto Argentinalle, ei tasapeliksi.
    s = data["h2h_summary"]
    assert s["home_team_wins"] >= 1 and s["draws"] == 0
