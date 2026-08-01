# -*- coding: utf-8 -*-
"""Etusivun (index.html) generoitujen lohkojen portit — scripts/build_fpl_page.py.

Kattaa "Live model projections" -taulukon: rivit tulevat xP-datasta ja
liputetut pelaajat rajataan pois. Negatiivinen kontrolli varmistaa etta portit
oikeasti suodattavat (ilman sita testi ei mittaisi mitaan).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# ---------------------------------------------------------------------------
# 1.8.2026: etusivun "Live model projections" -taulukko generoidaan datasta.
# Aiemmin kovakoodattu 24.7. ajosta samalla kun alaviite lupasi "refreshed
# daily". Karkirivilla oli pelaaja jonka FPL oli liputtanut loukkaantuneeksi.
# ---------------------------------------------------------------------------
def _xp_player(name, xp, status="a", chance=None, basis="pl_history"):
    return {"web_name": name, "team_short": "TST", "pos": "MID", "price": 6.0,
            "owned_pct": 5.0, "xp_horizon_total": xp, "status": status,
            "chance_next": chance, "data_basis": basis}


def test_xp_table_excludes_flagged_players():
    from scripts.build_fpl_page import xp_table_rows
    xp = {"meta": {"horizon_gw": 6}, "players": [
        _xp_player("Injured", 40.0, status="i", chance=0),
        _xp_player("Doubtful", 39.0, status="d", chance=25),
        _xp_player("Promoted", 38.0, basis="no_history"),
        _xp_player("Fit", 30.0),
    ]}
    html = xp_table_rows(xp, n=4)
    assert "Fit" in html
    # Negatiivinen kontrolli: jos portit eivat toimi, korkeamman xP:n nimet
    # nousevat karkeen ja etusivu suosittelee pelaajaa jota ei voi pelauttaa.
    for name in ("Injured", "Doubtful", "Promoted"):
        assert name not in html, f"{name} paasi etusivun taulukkoon"


def test_xp_table_foot_states_horizon_not_daily_promise():
    from scripts.build_fpl_page import xp_table_rows
    html = xp_table_rows({"meta": {"horizon_gw": 6},
                          "players": [_xp_player("Fit", 30.0)]}, n=1)
    assert "next 6 gameweeks" in html
    assert "refreshed daily" not in html
