"""#77b — h2h-rivien pakkapelikäsittely: näyttöscore ilman pakkoja + penalties-lippu.

Ankkuritapaus: PSG-Arsenal CL-finaali 30.5.2026 (FD fullTime 5-4 = 1-1 + pakat
4-3) -> h2h-rivin pitää näyttää 1-1 + penalties: true + penalty_winner: home.
"""
from __future__ import annotations

import pandas as pd
import pytest

from api.main import _h2h_item


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


def test_wc_h2h_has_penalties_field_false(client):
    """WC-polku (martj42): kenttä mukana muodon vuoksi, aina false (ei dataa)."""
    r = client.post("/api/predict-wc", json={
        "home_team": "Argentina", "away_team": "France",
        "leagues": ["INT-World Cup"], "seasons": ["2018", "2022"],
    })
    assert r.status_code == 200
    h2h = r.json()["h2h"]
    assert h2h, "Argentina-France h2h puuttuu"
    assert all(m["penalties"] is False for m in h2h)
