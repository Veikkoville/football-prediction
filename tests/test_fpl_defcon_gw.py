# -*- coding: utf-8 -*-
"""Per-GW DefCon -matriisin builderin ydin (scripts/build_fpl_defcon_gw.py).

Testataan puhdasta matrix_players-funktiota synteettisella datalla:
  - kynnykset positioittain (DEF 10 / MID+FWD 12), GKP pois
  - nykykauden attribuutit voittavat (hinta/seura tulee 26/27-bootstrapista)
  - rivittomat pelaajat pois (No data yet, ei arvauksia)
  - jarjestys dc_points laskevasti
Negatiivinen kontrolli: DEF-kynnyksen nosto 10->12 PUDOTTAA hitit — jos ei
pudota, testi ei mittaa kynnysta lainkaan.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.build_fpl_defcon_gw import matrix_players, sanity  # noqa: E402
from src.models.fpl_leaders import DEFCON_THRESHOLD  # noqa: E402

TEAMS = {1: "ARS", 2: "MCI"}


def _elem(eid, code, name, etype, team=1, cost=50):
    return {"id": eid, "code": code, "web_name": name, "element_type": etype,
            "team": team, "now_cost": cost, "selected_by_percent": "5.0"}


def _rows(*dcs):
    return [[i + 1, "OPP", "H", 90, dc] for i, dc in enumerate(dcs)]


def test_thresholds_per_position():
    els = [
        _elem(1, 101, "Def", 2),   # DEF: kynnys 10
        _elem(2, 102, "Mid", 3),   # MID: kynnys 12
    ]
    rows = {101: _rows(9, 10, 11), 102: _rows(11, 12, 13)}
    out = {p["web_name"]: p for p in matrix_players(els, TEAMS, rows)}
    assert out["Def"]["hits"] == 2 and out["Def"]["dc_points"] == 4
    assert out["Mid"]["hits"] == 2
    assert out["Def"]["threshold"] == 10 and out["Mid"]["threshold"] == 12


def test_negative_control_threshold_matters():
    """Kontrolli: DEF-kynnys 12:ksi -> hitit putoavat. Jos tama menee lapi
    muuttamattomana, testi ei mittaa kynnysta."""
    els = [_elem(1, 101, "Def", 2)]
    rows = {101: _rows(10, 11)}
    base = matrix_players(els, TEAMS, rows)[0]["hits"]
    orig = DEFCON_THRESHOLD["DEF"]
    try:
        DEFCON_THRESHOLD["DEF"] = 12
        raised = matrix_players(els, TEAMS, rows)[0]["hits"]
    finally:
        DEFCON_THRESHOLD["DEF"] = orig
    assert base == 2 and raised == 0


def test_gkp_and_rowless_excluded_current_attrs_win():
    els = [
        _elem(1, 101, "Keeper", 1),          # GKP -> pois vaikka riveja olisi
        _elem(2, 102, "NoData", 2),          # ei riveja -> pois
        _elem(3, 103, "Moved", 2, team=2, cost=60),  # 26/27-seura + hinta
    ]
    rows = {101: _rows(15), 103: _rows(10)}
    out = matrix_players(els, TEAMS, rows)
    assert [p["web_name"] for p in out] == ["Moved"]
    assert out[0]["team_short"] == "MCI" and out[0]["price"] == 6.0
    assert out[0]["basis"] == "2025/26"


def test_sort_by_dc_points_desc():
    els = [_elem(1, 101, "Low", 2), _elem(2, 102, "High", 2)]
    rows = {101: _rows(10), 102: _rows(10, 10, 10)}
    out = matrix_players(els, TEAMS, rows)
    assert [p["web_name"] for p in out] == ["High", "Low"]


def test_sanity_catches_broken_data():
    els = [_elem(1, 101, "Def", 2)]
    rows = {101: _rows(9)}  # 0 hittia koko datassa
    data = {"players": matrix_players(els, TEAMS, rows)}
    fails = sanity(data)
    assert any("pelaajia" in f for f in fails)          # alle minimin
    assert any("hittia" in f for f in fails)            # ei yhtaan hittia
