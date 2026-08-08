"""STATS-ZONE (8.8): builderin sanity-gate + sivun sarakesopimus.

Nama testit ovat portteja kahdelle vikaluokalle jotka ovat osuneet ennenkin:
  1. rikkinainen data paasee ulos (sanity-gate ei kiinnita) — vrt. golden-vahti
  2. sarakelista ja sen labelit/skaalaussaannot erkanevat hiljaa toisistaan
"""
from __future__ import annotations

import copy

import pytest

from scripts.build_fpl_stats import COLS, sanity
from scripts.build_fpl_longtail import (STATS_GROUPS, STATS_INT, STATS_LABELS,
                                        STATS_RATEABLE)

IDX = {c: i for i, c in enumerate(COLS)}


def _row(**over) -> list:
    """Terve rivi, jota yksittaiset testit rikkovat kohdennetusti."""
    base = {
        "id": 1, "name": "Test", "team": "ARS", "pos": "MID", "price": 6.0,
        "own": 10.0, "status": "a", "mins": 1800, "starts": 20,
        "g": 5, "xg": 4.5, "threat": 100.0,
        "a": 4, "xa": 3.5, "xgi": 8.0, "creativity": 200.0,
        "tkl": 30, "cbi": 20, "rec": 80, "dc": 130,
        "cs": 5, "gc": 20, "xgc": 18.5, "saves": 0,
        "pts": 120, "ppg": 4.0, "bps": 400, "bonus": 8, "ict": 150.0,
        "yc": 3, "rc": 0, "pen": 0, "cor": 0, "fk": 0,
        # vaihe 2: Understat-sarakkeet (None = pelaajaa ei matsattu)
        "sh": 40, "sot": 15, "box": 25, "head": 5, "hvc": 6,
        "npxg": 4.2, "spxg": 0.8, "kp": 30, "xgchain": 8.0, "xgbuildup": 3.0,
    }
    base.update(over)
    return [base[c] for c in COLS]


def _data(rows: list[list]) -> dict:
    return {
        "meta": {"available": True, "basis_label": "Based on 2025/26",
                 "cols": COLS},
        "players": rows,
    }


def _healthy(n: int = 250) -> dict:
    return _data([_row(id=i, name=f"P{i}") for i in range(n)])


def test_healthy_data_passes():
    assert sanity(_healthy()) == []


def test_too_few_players_fails():
    assert sanity(_healthy(50))


@pytest.mark.parametrize("field,value", [
    ("mins", 9999),          # kausi ei voi olla nain pitka
    ("mins", 0),             # 0 minuuttia ei kuulu listalle lainkaan
    ("starts", 99),
    ("rec", -5),             # negatiivinen kertyma
])
def test_out_of_range_values_fail(field, value):
    d = _healthy()
    d["players"][0][IDX[field]] = value
    assert sanity(d), f"{field}={value} olisi pitanyt kiinnittaa"


def test_absurd_rate_fails():
    """3.0 xG/90 kestavasti ei ole olemassa — rikkinainen minuuttikentta."""
    d = _healthy()
    d["players"][0][IDX["xg"]] = 60.0
    assert sanity(d)


def test_xgi_must_match_xg_plus_xa():
    d = _healthy()
    d["players"][0][IDX["xgi"]] = 99.0
    assert sanity(d)


def test_missing_basis_label_fails():
    """Data-rajoitus on ensiluokkainen: rivi ei saa esiintya ilman kauden
    kertovaa labelia (sama saanto kuin fpl_player_leaders)."""
    d = _healthy()
    d["meta"]["basis_label"] = ""
    assert sanity(d)


def test_duplicate_id_fails():
    d = _healthy()
    d["players"][1] = copy.deepcopy(d["players"][0])
    assert sanity(d)


def test_row_length_must_match_cols():
    d = _healthy()
    d["players"][0] = d["players"][0] + [1]
    assert sanity(d)


# --- sivun sarakesopimus ---------------------------------------------------

def _group_cols() -> set[str]:
    return {c for _, _, cols in STATS_GROUPS for c in cols}


def test_every_group_column_exists_in_data():
    missing = _group_cols() - set(COLS)
    assert not missing, f"sivu nayttaisi saraketta jota datassa ei ole: {missing}"


def test_every_group_column_has_a_label():
    missing = _group_cols() - set(STATS_LABELS)
    assert not missing, f"sarake ilman otsikkoa: {missing}"


def test_rateable_and_int_columns_exist():
    assert not (STATS_RATEABLE - set(COLS))
    assert not (STATS_INT - set(COLS))


def test_shot_columns_cannot_exceed_shots():
    """SoT, boksilaukaukset ja paalaukaukset ovat laukausten osajoukkoja."""
    for col in ("sot", "box", "head"):
        d = _healthy()
        d["players"][0][IDX[col]] = d["players"][0][IDX["sh"]] + 1
        assert sanity(d), f"{col} > sh olisi pitanyt kiinnittaa"


def test_missing_shot_data_is_allowed_as_none():
    """Matsaamaton pelaaja saa tyhjan solun, ei nollaa — eika se kaada porttia."""
    d = _healthy()
    for col in ("sh", "sot", "box", "head", "hvc", "npxg", "spxg", "kp",
                "xgchain", "xgbuildup"):
        d["players"][0][IDX[col]] = None
    assert sanity(d) == []


def test_low_match_coverage_blocks_shot_columns():
    d = _healthy()
    d["meta"]["shots_available"] = True
    d["meta"]["shots_match_coverage"] = 0.90
    assert sanity(d), "alle 97 %:n matsayksen olisi pitanyt kaataa portti"
    d["meta"]["shots_match_coverage"] = 0.99
    assert sanity(d) == []


def test_orders_and_ratios_are_not_scaled():
    """pen/cor/fk ovat sijalukuja ja ppg on jo suhdeluku — per 90 ei saa
    skaalata niita. Ilman tata testia 'ensimmainen pilkunpotkaisija' voisi
    nayttaa arvon 0.05."""
    for k in ("pen", "cor", "fk", "ppg"):
        assert k not in STATS_RATEABLE
