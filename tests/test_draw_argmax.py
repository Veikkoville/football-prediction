"""Lukitsee draw-käyttäytymisen (kaverin havainto 12.6.2026, todettu ei-bugiksi).

Malli TUOTTAA tasapelin todennäköisimpänä lopputuloksena matalan xG:n
tasaväkipareille (skannaus 12.6.: 24/7436 paria, max P(X)=0.3665), ja
frontendin valintakaava (PredictScreen.tsx:332-337) valitsee X:n aidosti.

HUOM: ankkuripari Ecuador-Morocco on 9.7.2026 QF-virkistetyn data/wc_model.json:in
tila (skannaus 9.7.: 44/18915 paria draw-argmax; tämä pari P(X)=0.3781 vs
max(P(1),P(2))=0.3242, marginaali ~0.054 = skannauksen suurin). Edellinen ankkuri
Tunisia-Congo DR kääntyi virkistyksessä (marginaali oli vain ~0.009). Jos
WC-datavirkistys kääntää tämänkin parin, valitse uusi draw-argmax-pari
skannaamalla (ks. STATE 12.6.) — älä poista testiä: se vahtii että X voi
ylipäätään valikoitua.
"""
from __future__ import annotations

ANCHOR = {"home_team": "Ecuador", "away_team": "Morocco",
          "leagues": ["INT-World Cup"], "seasons": ["2018", "2022"]}


def _frontend_pick(p_home: float, p_draw: float, p_away: float) -> str:
    """PredictScreen.tsx:332-337 winner-kaava 1:1 (>= -tie-breakit mukaan)."""
    if p_home >= max(p_draw, p_away):
        return "1"
    if p_away >= p_draw:
        return "2"
    return "X"


def test_model_produces_draw_argmax_for_anchor_pair(client):
    """(1) Tunisia-Congo DR neutraalina: P(X) on korkein kolmesta."""
    r = client.post("/api/predict-wc", json=ANCHOR)
    assert r.status_code == 200
    b = r.json()
    assert b["p_draw"] > b["p_home_win"] and b["p_draw"] > b["p_away_win"], (
        f"draw ei enää argmax ankkuriparille: 1={b['p_home_win']} "
        f"X={b['p_draw']} 2={b['p_away_win']} — jos WC-data virkistyi, "
        "skannaa uusi draw-argmax-pari (ks. moduulin docstring)")


def test_frontend_formula_picks_x_for_anchor_pair(client):
    """(2) Frontendin valintakaava valitsee X:n tälle inputille."""
    b = client.post("/api/predict-wc", json=ANCHOR).json()
    assert _frontend_pick(b["p_home_win"], b["p_draw"], b["p_away_win"]) == "X"


def test_frontend_formula_argmax_branches():
    """Kaavan kaikki haarat: X valikoituu kun se on aidosti suurin."""
    assert _frontend_pick(0.50, 0.30, 0.20) == "1"
    assert _frontend_pick(0.20, 0.30, 0.50) == "2"
    assert _frontend_pick(0.30, 0.40, 0.30) == "X"
    assert _frontend_pick(0.34, 0.33, 0.33) == "1"   # tie-break: koti
    assert _frontend_pick(0.30, 0.35, 0.35) == "2"   # tie-break: vieras ennen X:ää
