"""FPL ↔ Understat -matsayksen portti (STATS-ZONE vaihe 2, 8.8.2026).

Nimivariantit tassa ovat AITOJA 25/26-datasta. Ne ovat regressiotesti sille,
etta tikapuiden loysemmat askeleet toimivat — ja etta ne eivat toimi liikaa:
`test_loose_key_needs_minutes` on tama testitiedoston tarkein rivi. Ilman
minuuttivahvistusta pelkka etunimi "Gabriel" matsasi Martinellin (1065 min)
vaaraan Gabrieliin (2748 min), eli sivulle olisi tullut vaarat laukausluvut
oikean pelaajan nimen viereen.
"""
from __future__ import annotations

import pytest

from src.models.fpl_understat_match import UnderstatIndex, match_all, tokens


def u(uid, name, mins, sh=10):
    return {"uid": str(uid), "name": name, "mins": mins, "sh": sh}


def e(pid, first, second, web, mins):
    return {"id": pid, "first_name": first, "second_name": second,
            "web_name": web, "minutes": mins}


ROWS = [
    u(1, "Erling Haaland", 2979),
    u(2, "Matthew Cash", 3040),
    u(3, "Joshua King", 1300),
    u(4, "Iyenoma Destiny Udogie", 1350),
    u(5, "Yehor Yarmolyuk", 2660),
    u(6, "Amad Diallo Traore", 2341),
    u(7, "Yeremi Pino", 2134),
    u(8, "Ferdi Kadioglu", 3150),
    u(9, "Alisson", 2350),
    u(10, "Martin Odegaard", 1370),
    u(11, "Gabriel", 2748),
    u(12, "Gabriel Martinelli Silva", 1080),
    u(13, "Emile Smith Rowe", 1920),
]


@pytest.mark.parametrize("element,expected", [
    (e(1, "Erling", "Haaland", "Haaland", 2953), "Erling Haaland"),
    (e(2, "Matty", "Cash", "Cash", 3016), "Matthew Cash"),
    (e(3, "Josh", "King", "King", 1290), "Joshua King"),
    (e(4, "Destiny", "Udogie", "Udogie", 1335), "Iyenoma Destiny Udogie"),
    (e(5, "Yehor", "Yarmoliuk", "Yarmoliuk", 2652), "Yehor Yarmolyuk"),
    (e(6, "Amad", "Diallo", "Amad", 2339), "Amad Diallo Traore"),
    (e(7, "Yéremy", "Pino Santos", "Yeremy", 2074), "Yeremi Pino"),
    (e(8, "Ferdi", "Kadıoğlu", "F.Kadıoğlu", 3130), "Ferdi Kadioglu"),
    (e(9, "Alisson", "Becker", "A.Becker", 2340), "Alisson"),
    (e(10, "Martin", "Ødegaard", "Ødegaard", 1363), "Martin Odegaard"),
    (e(13, "Emile", "Smith Rowe", "Smith Rowe", 1909), "Emile Smith Rowe"),
])
def test_real_world_name_variants(element, expected):
    hit, how = UnderstatIndex(ROWS).match(element)
    assert hit is not None, f"ei osumaa ({how})"
    assert hit["name"] == expected


def test_loose_key_needs_minutes():
    """Kahdella pelaajalla on sama etunimi ja eri minuutit: loysa avain ei saa
    ratkaista, ja minuuttien on pakko olla mukana paatoksessa."""
    idx = UnderstatIndex(ROWS)
    martinelli = e(12, "Gabriel", "Martinelli Silva", "Martinelli", 1065)
    hit, _ = idx.match(martinelli)
    assert hit is not None
    assert hit["name"] == "Gabriel Martinelli Silva", "matsasi vaaraan Gabrieliin"

    gabriel = e(11, "Gabriel", "dos Santos Magalhaes", "Gabriel", 2750)
    hit2, _ = idx.match(gabriel)
    assert hit2 is not None and hit2["name"] == "Gabriel"


def test_unknown_player_returns_none():
    hit, how = UnderstatIndex(ROWS).match(
        e(99, "Testi", "Pelaaja", "Pelaaja", 900))
    assert hit is None and how == "none"


def test_tokens_handle_diacritics_and_special_letters():
    assert tokens("Kadıoğlu") == ["kadioglu"]
    assert tokens("Ødegaard") == ["odegaard"]
    assert tokens("Aït-Nouri") == ["ait", "nouri"]
    assert tokens("O'Brien") == ["obrien"]


def test_match_all_reports_coverage_and_suspects():
    elements = [
        e(1, "Erling", "Haaland", "Haaland", 2953),
        e(99, "Testi", "Pelaaja", "Pelaaja", 900),
    ]
    r = match_all(elements, ROWS, min_minutes=450)
    assert r["considered"] == 2
    assert r["matched"] == 1
    assert r["coverage"] == 0.5
    assert r["misses"] == ["Pelaaja"]
    assert r["suspect"] == []
