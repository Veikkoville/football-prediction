"""Portit jäädytetyn rungon FPL-vientiin.

Tämä on repon ainoa skripti joka KIRJOITTAA Villen oikeaan FPL-joukkueeseen,
eikä lähetystä voi perua deadlinen jälkeen. Siksi portit painottuvat siihen
mikä menisi hiljaa väärin: kokoonpanon paikkanumerointiin (FPL tulkitsee
position 1 = aloittava maalivahti, 12 = varamaalivahti) ja kapteenilippuihin.
Väärä paikkanumero ei tuota virhettä — se vain penkittää väärän pelaajan.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "fpl_submit_squad", ROOT / "scripts" / "fpl_submit_squad.py")
sub = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sub)


def _p(pid, pos, name=None, price=50):
    return {"id": pid, "web_name": name or f"P{pid}", "team_short": "XXX",
            "pos": pos, "club": "X", "price": price, "xp": 1.0}


def _freeze(captain=2, vice=3):
    """1 MV + 4 PUO + 4 KES + 2 HYÖ aloittavina, penkillä MV + 3 kenttäpelaajaa."""
    xi = ([_p(1, 1)]
          + [_p(i, 2) for i in (2, 3, 4, 5)]
          + [_p(i, 3) for i in (6, 7, 8, 9)]
          + [_p(i, 4) for i in (10, 11)])
    bench = [_p(12, 1), _p(13, 2), _p(14, 3), _p(15, 4)]
    return {"meta": {"gw": 1}, "captain": captain, "vice_captain": vice,
            "xi": xi, "bench": bench}


# --------------------------------------------------------------------------
# Paikkanumerointi — tämä on se joka menee hiljaa väärin
# --------------------------------------------------------------------------

def test_position_one_is_the_starting_keeper():
    picks, _ = sub.build_positions(_freeze())
    assert picks[0]["element"] == 1 and picks[0]["position"] == 1


def test_position_twelve_is_the_bench_keeper():
    """FPL:n autosub odottaa varamaalivahdin paikassa 12. Jos kenttäpelaaja
    päätyy sinne, maalivahdin autosub ei laukea koko kierroksella."""
    picks, _ = sub.build_positions(_freeze())
    assert picks[11]["element"] == 12 and picks[11]["position"] == 12


def test_starting_eleven_occupies_positions_one_to_eleven():
    picks, _ = sub.build_positions(_freeze())
    starters = {pk["element"] for pk in picks if pk["position"] <= 11}
    assert starters == set(range(1, 12))


def test_bench_order_from_the_freeze_is_preserved():
    """Penkkijärjestys on autosub-prioriteetti, ja `order_bench` on jo
    ratkaissut sen jäädytyksessä. Uudelleenjärjestäminen täällä tarkoittaisi
    että viety rivi EI ole se joka jäädytettiin."""
    picks, _ = sub.build_positions(_freeze())
    assert [pk["element"] for pk in picks[12:]] == [13, 14, 15]


def test_every_player_gets_a_unique_position():
    picks, _ = sub.build_positions(_freeze())
    assert sorted(pk["position"] for pk in picks) == list(range(1, 16))


# --------------------------------------------------------------------------
# Kapteenit
# --------------------------------------------------------------------------

def test_exactly_one_captain_and_one_vice():
    picks, _ = sub.build_positions(_freeze(captain=2, vice=3))
    assert [pk["element"] for pk in picks if pk["is_captain"]] == [2]
    assert [pk["element"] for pk in picks if pk["is_vice_captain"]] == [3]


def test_captain_on_the_bench_is_rejected():
    """Penkillä oleva kapteeni on hiljainen pistetappio: tuplaus ei laukea."""
    with pytest.raises(SystemExit):
        sub.build_positions(_freeze(captain=13))


def test_same_player_as_captain_and_vice_is_rejected():
    with pytest.raises(SystemExit):
        sub.build_positions(_freeze(captain=2, vice=2))


# --------------------------------------------------------------------------
# Rungon muoto
# --------------------------------------------------------------------------

def test_two_keepers_in_the_eleven_is_rejected():
    f = _freeze()
    f["xi"][1] = _p(2, 1)
    with pytest.raises(SystemExit):
        sub.build_positions(f)


def test_no_keeper_on_the_bench_is_rejected():
    f = _freeze()
    f["bench"][0] = _p(12, 2)
    with pytest.raises(SystemExit):
        sub.build_positions(f)


def test_short_squad_is_rejected():
    f = _freeze()
    f["bench"] = f["bench"][:3]
    with pytest.raises(SystemExit):
        sub.build_positions(f)


def test_missing_freeze_refuses_instead_of_improvising():
    """Jos jäädytystä ei ole, riviä EI saa rakentaa lennosta: koko julkinen
    väite on 'jäädytetty ennen deadlinea, todistettavissa git-historiasta'."""
    with pytest.raises(SystemExit) as e:
        sub.load_freeze(9999)
    assert "puuttuu" in str(e.value)
