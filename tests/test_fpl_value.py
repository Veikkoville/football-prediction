"""FPL value/consistency + GK rotation pairs -testit (#114).

Synteettinen pooli/phase0 monkeypatchilla — ei verkkoa, ei oikeaa dataa.
"""
from __future__ import annotations

import pytest

from src.models import fpl_value as fv


def _pool_player(pid, name, short, etype, price_tenths, xph, gw_xps,
                 predicted_starts=90.0, xmins=90.0, owned=10.0):
    return {
        "id": pid, "web_name": name, "team_short": short,
        "element_type": etype, "club": 1, "price": price_tenths,
        "owned_pct": owned, "xp_per_gw": xph / max(len(gw_xps), 1),
        "xp_horizon_total": xph,
        "gameweeks": [{"gw": i + 1, "xp": x} for i, x in enumerate(gw_xps)],
        "xmins": xmins, "predicted_starts": predicted_starts,
        "minutes_confidence": "high", "components": None, "components_gw": None,
    }


def _ctx(pool):
    xp_data = {"meta": {"available": True, "season": "2026/27",
                        "next_gameweek": 1, "horizon_gw": 6,
                        "generated_at": "2026-07-17T00:00:00Z"},
               "players": []}
    return xp_data, {}, pool, {p["id"]: p for p in pool}


def test_value_list_math_and_order(monkeypatch):
    pool = [
        # 30 xP / 6.0M = 5.0 — tasainen kalenteri
        _pool_player(1, "Steady", "AAA", 3, 60, 30.0, [5, 5, 5, 5, 5, 5]),
        # 30 xP / 10.0M = 3.0 — heiluva kalenteri
        _pool_player(2, "Swingy", "BBB", 4, 100, 30.0, [1, 9, 1, 9, 1, 9]),
        # 12 xP / 4.0M = 3.0 — sama value kuin Swingy (järjestys stabiili)
        _pool_player(3, "Budget", "CCC", 2, 40, 12.0, [2, 2, 2, 2, 2, 2]),
    ]
    monkeypatch.setattr(fv, "build_context", lambda: _ctx(pool))
    out = fv.value_list(top_n=2)
    assert [r["web_name"] for r in out["players"]][0] == "Steady"
    top = out["players"][0]
    assert top["value"] == pytest.approx(5.0)
    assert top["price"] == 6.0
    assert top["fixture_swing"] == 0.0
    assert top["swing_label"] == "steady"
    assert len(out["players"]) == 2                       # top_n leikkaa
    assert "schedule volatility" in out["meta"]["note"]   # rehellisyyscaption

    monkeypatch.setattr(fv, "build_context",
                        lambda: _ctx([pool[1]]))
    swingy = fv.value_list()["players"][0]
    assert swingy["fixture_swing"] == 4.0                 # pstdev([1,9]*3)
    assert swingy["swing_label"] == "swingy"


def test_value_list_skips_zero_price(monkeypatch):
    pool = [_pool_player(1, "Free", "AAA", 3, 0, 10.0, [2, 2])]
    monkeypatch.setattr(fv, "build_context", lambda: _ctx(pool))
    assert fv.value_list()["players"] == []


def _phase0(teams):
    return {"meta": {"available": True, "next_gameweek": 1, "horizon_gw": 2},
            "teams": teams}


def test_gk_rotation_pairs_picks_best_per_gw(monkeypatch):
    pool = [
        _pool_player(11, "KeeperA", "ARS", 1, 55, 10.0, [5, 5]),
        _pool_player(12, "BackupA", "ARS", 1, 40, 2.0, [1, 1],
                     predicted_starts=5.0, xmins=10.0),   # ei valikoidu
        _pool_player(13, "KeeperB", "MCI", 1, 50, 9.0, [4, 5]),
        _pool_player(14, "KeeperC", "TOT", 1, 45, 8.0, [4, 4]),
        _pool_player(20, "Outfield", "ARS", 3, 80, 20.0, [3, 3]),
    ]
    teams = [
        {"short": "ARS", "fixtures": [{"gw": 1, "cs_pct": 60.0},
                                       {"gw": 2, "cs_pct": 30.0}]},
        {"short": "MCI", "fixtures": [{"gw": 1, "cs_pct": 20.0},
                                       {"gw": 2, "cs_pct": 50.0}]},
        {"short": "TOT", "fixtures": [{"gw": 1, "cs_pct": 25.0},
                                       {"gw": 2, "cs_pct": 25.0}]},
    ]
    monkeypatch.setattr(fv, "build_context", lambda: _ctx(pool))
    monkeypatch.setattr(fv, "load_phase0", lambda: _phase0(teams))
    out = fv.gk_rotation_pairs(top_n=3)
    best = out["pairs"][0]
    # ARS+MCI: gw1 max(60,20)=60 (ARS), gw2 max(30,50)=50 (MCI) → avg 55
    assert {best["gk_a"]["team_short"], best["gk_b"]["team_short"]} == {"ARS", "MCI"}
    assert best["avg_best_cs_pct"] == pytest.approx(55.0)
    assert best["combined_price"] == pytest.approx(10.5)
    assert best["gk_a"]["web_name"] in ("KeeperA", "KeeperB")   # ei BackupA
    assert [s["team_short"] for s in best["gw_split"]] == ["ARS", "MCI"]


def test_gk_rotation_pairs_phase0_unavailable(monkeypatch):
    pool = [_pool_player(11, "KeeperA", "ARS", 1, 55, 10.0, [5, 5])]
    monkeypatch.setattr(fv, "build_context", lambda: _ctx(pool))
    monkeypatch.setattr(fv, "load_phase0",
                        lambda: {"meta": {"available": False}, "teams": []})
    out = fv.gk_rotation_pairs()
    assert out["meta"]["available"] is False
    assert out["pairs"] == []


def test_value_endpoint_shape(client, monkeypatch):
    from src.models import fpl_value as module
    pool = [
        _pool_player(1, "Steady", "AAA", 3, 60, 30.0, [5, 5, 5]),
        _pool_player(11, "KeeperA", "ARS", 1, 55, 10.0, [5, 5]),
        _pool_player(13, "KeeperB", "MCI", 1, 50, 9.0, [4, 5]),
    ]
    teams = [
        {"short": "ARS", "fixtures": [{"gw": 1, "cs_pct": 60.0}]},
        {"short": "MCI", "fixtures": [{"gw": 1, "cs_pct": 20.0}]},
    ]
    monkeypatch.setattr(module, "build_context", lambda: _ctx(pool))
    monkeypatch.setattr(module, "load_phase0", lambda: _phase0(teams))
    r = client.get("/api/fantasy/value?top_n=5&pairs_n=3")
    assert r.status_code == 200
    b = r.json()
    for key in ("meta", "players", "gk"):
        assert key in b
    assert b["meta"]["available"] is True
    assert b["players"][0]["value"] > 0
    assert b["gk"]["pairs"][0]["avg_best_cs_pct"] == pytest.approx(60.0)


def test_gk_meta_horizon_kertoo_cs_kattavuuden_ei_tiedoston_metaa(monkeypatch):
    """29.7 (Villen havainto tuotannosta): payload vaitti horizon_gw=38 mutta
    gw_split oli 6 kierrosta.

    Juurisyy: meta luki phase0-TIEDOSTON horizon_gw:n, joka on koko
    fixture-aineiston kattavuus. Pari lasketaan kuitenkin vain kierroksista
    joilla MOLEMMILLA seuroilla on cs_pct, eli lahihorisontista.

    Miksi vanhat testit eivat nahneet tata: niiden `_phase0`-fixture asettaa
    horizon_gw=2 ja CS-data kattaa nimenomaan 2 kierrosta, joten vaara ja oikea
    arvo ovat identtiset eika kontrolli erottele. Tassa ne on tarkoituksella
    eriytetty: tiedosto vaittaa 38, CS-dataa on 2.
    """
    pool = [
        _pool_player(11, "KeeperA", "ARS", 1, 55, 10.0, [5, 5]),
        _pool_player(13, "KeeperB", "MCI", 1, 50, 9.0, [4, 5]),
    ]
    teams = [
        {"short": "ARS", "fixtures": [{"gw": 1, "cs_pct": 60.0},
                                      {"gw": 2, "cs_pct": 30.0}]},
        {"short": "MCI", "fixtures": [{"gw": 1, "cs_pct": 20.0},
                                      {"gw": 2, "cs_pct": 50.0}]},
    ]
    phase0 = {"meta": {"available": True, "next_gameweek": 1,
                       "horizon_gw": 38, "horizon_max": 38},
              "teams": teams}
    monkeypatch.setattr(fv, "build_context", lambda: _ctx(pool))
    monkeypatch.setattr(fv, "load_phase0", lambda: phase0)

    out = fv.gk_rotation_pairs(top_n=3)
    split = out["pairs"][0]["gw_split"]
    assert len(split) == 2, "testin oletus: CS-dataa on kahdelta kierrokselta"
    assert out["meta"]["horizon_gw"] == 2, (
        "horizon_gw kertoo mita vastauksessa on, ei mita tiedoston metassa "
        f"lukee (sai {out['meta']['horizon_gw']}, gw_split on {len(split)})"
    )


# ---------------------------------------------------------------------------
# 5.8: vauhti ja minuutit erikseen (kausiprojektiomittauksen (b)-puolikas)
# ---------------------------------------------------------------------------

def test_xp_per_90_separates_rate_from_minutes(monkeypatch):
    """Kaksi pelaajaa, SAMA xP/GW, eri minuutit → eri vauhti.

    Tama on koko muutoksen syy: yhdistetty xP/GW ei erota pelaajaa joka on
    hyva 45 minuuttia pelaajasta joka on keskinkertainen 90. Jos per-90 ei
    erota naita, kentta ei kerro mitaan uutta ja muutos on turha.
    """
    pool = [
        # 12 xP / 6 GW = 2.0 xP/GW taysilla minuuteilla → 2.0 xP/90
        _pool_player(1, "FullGame", "AAA", 3, 60, 12.0, [2] * 6, xmins=90.0),
        # sama 2.0 xP/GW mutta puolikkailla minuuteilla → 4.0 xP/90
        _pool_player(2, "HalfGame", "BBB", 3, 60, 12.0, [2] * 6, xmins=45.0),
    ]
    monkeypatch.setattr(fv, "build_context", lambda: _ctx(pool))
    rows = {r["web_name"]: r for r in fv.value_list()["players"]}

    assert rows["FullGame"]["xp_per_90"] == pytest.approx(2.0)
    assert rows["HalfGame"]["xp_per_90"] == pytest.approx(4.0)
    assert rows["FullGame"]["xmins"] == 90.0
    assert rows["HalfGame"]["xmins"] == 45.0
    # value ja xP-summa ovat identtiset — ero nakyy VAIN uusissa kentissa
    assert rows["FullGame"]["value"] == rows["HalfGame"]["value"]
    assert rows["FullGame"]["xp_per_90"] != rows["HalfGame"]["xp_per_90"], (
        "jos nama ovat samat, per-90 on johdettu xp_horizon_totalista eika "
        "minuuteista, ja koko kentta on kosmetiikkaa"
    )


def test_xp_per_90_is_none_below_floor_not_zero(monkeypatch):
    """Alle minuuttikynnyksen: None, EI 0.0 eika rajaton luku.

    0.0 lukisi "ei tuota pisteita", mika on eri vaite kuin "emme tieda".
    Kohinan julkaiseminen tarkkana lukuna on juuri se vikaluokka jota tama
    muutos korjaa.
    """
    below = fv.PER90_MIN_XMINS - 0.1
    pool = [
        _pool_player(1, "Fringe", "AAA", 3, 45, 1.2, [0.2] * 6, xmins=below),
        _pool_player(2, "AtFloor", "BBB", 3, 45, 6.0, [1.0] * 6,
                     xmins=fv.PER90_MIN_XMINS),
    ]
    monkeypatch.setattr(fv, "build_context", lambda: _ctx(pool))
    rows = {r["web_name"]: r for r in fv.value_list()["players"]}

    assert rows["Fringe"]["xp_per_90"] is None
    assert rows["Fringe"]["xmins"] == round(below, 1), (
        "minuutit nakyvat silti — juuri ne kertovat miksi vauhtia ei ole"
    )
    # kynnys on inklusiivinen: tasan kynnyksella luku annetaan
    assert rows["AtFloor"]["xp_per_90"] == pytest.approx(6.0)


def test_value_note_says_rate_and_minutes_are_separate():
    """Rehellisyyscaption kulkee payloadissa (sama kaava kuin swing-note).

    Ilman tata kentta on kaksi lukua ilman lukuohjetta, ja "korkea vauhti
    pienilla minuuteilla" luetaan loydoksi eika riskiksi.
    """
    assert "separately" in fv.VALUE_NOTE
    assert "bench risk" in fv.VALUE_NOTE
