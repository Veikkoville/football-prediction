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


# ---------------------------------------------------------------------------
# #226-DC (1.8.2026): hit raten nimittaja = startit, ei pelatut ottelut.
# Taustaa: Premier Leaguen oma julkaisu laskee luvun starteista; me laskimme
# pelatuista, jolloin vaihdosta tulleet cameot laimensivat prosenttia ja
# julkinen lukumme erosi virallisesta (Wieffer 42,3 % vs 47,8 %).
# ---------------------------------------------------------------------------
def _rows_st(*pairs):
    """Rivit start-lipulla: (dc, started) -> [gw, opp, venue, min, dc, start]."""
    return [[i + 1, "OPP", "H", 90 if st else 20, dc, 1 if st else 0]
            for i, (dc, st) in enumerate(pairs)]


def test_hit_rate_uses_starts_not_appearances():
    els = [_elem(1, 101, "Def", 2)]
    # 4 starttia (2 osumaa) + 2 vaihtoa joissa ei osumaa.
    rows = {101: _rows_st((11, 1), (10, 1), (5, 1), (4, 1), (2, 0), (3, 0))}
    p = matrix_players(els, TEAMS, rows)[0]
    assert p["games"] == 6 and p["starts"] == 4
    assert p["hits"] == 2 and p["start_hits"] == 2
    assert p["hit_rate"] == 0.5              # 2/4 startista
    assert p["hit_rate_games"] == round(2 / 6, 3)   # vanha luku talteen
    # DefCon-pisteet kertyvat myos vaihdosta -> nimittaja muuttui, ei pisteet.
    assert p["dc_points"] == 4


def test_negative_control_cameo_would_dilute_rate():
    """Kontrolli: jos nimittaja olisi yha pelatut ottelut, luku olisi eri.
    Jos tama menee lapi ilman erotusta, testi ei mittaa nimittajaa lainkaan."""
    els = [_elem(1, 101, "Def", 2)]
    rows = {101: _rows_st((11, 1), (11, 1), (0, 0), (0, 0))}
    p = matrix_players(els, TEAMS, rows)[0]
    assert p["hit_rate"] == 1.0               # 2/2 starttia
    assert p["hit_rate_games"] == 0.5         # 2/4 pelattua
    assert p["hit_rate"] != p["hit_rate_games"]


def test_start_flag_is_sixth_field_old_indexes_intact():
    els = [_elem(1, 101, "Def", 2)]
    rows = {101: _rows_st((11, 1))}
    p = matrix_players(els, TEAMS, rows)[0]
    gw, opp, venue, mins, dc, start = p["per_gw"][0]
    assert (gw, opp, venue, dc, start) == (1, "OPP", "H", 11, 1) and mins == 90


def test_pos_change_exposes_official_basis():
    """Positio maaraa kynnyksen. Kun se vaihtuu kausien valilla, otsikkoluku
    lasketaan KULUVAN position kynnyksella (ennustaa 26/27-tuottoa) mutta rivi
    kantaa myos basis-position luvun = se jonka FPL julkaisee."""
    els = [_elem(1, 101, "Wieffer", 2)]        # nyt DEF (kynnys 10)
    rows = {101: _rows_st((11, 1), (11, 1), (13, 1), (9, 1))}
    p = matrix_players(els, TEAMS, rows, {101: "MID"})[0]   # oli MID (12)
    assert p["pos_changed"] is True and p["basis_pos"] == "MID"
    assert p["hit_rate"] == 0.75               # 3/4 kynnyksella 10
    assert p["hit_rate_basis_pos"] == 0.25     # 1/4 kynnyksella 12
    # Sama pelaaja ilman positiomuutosta ei saa ylimaaraista kenttaa.
    q = matrix_players(els, TEAMS, rows, {101: "DEF"})[0]
    assert q["pos_changed"] is False and "hit_rate_basis_pos" not in q


def test_sanity_catches_incoherent_starts():
    els = [_elem(1, 101, "Def", 2)]
    rows = {101: _rows_st((11, 1), (11, 0))}
    players = matrix_players(els, TEAMS, rows)
    players[0]["starts"] = 99                  # startteja enemman kuin otteluita
    fails = sanity({"players": players})
    assert any("epakoherentit" in f for f in fails)
