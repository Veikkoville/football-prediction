"""Portit club-best-kortille ja korttien datalahteelle.

TAUSTA (14.8). Kortit lukivat julkista /api/fantasy/xp-endpointia, joka on
premium-portin takana maskattu top-10-teaseriksi (10 rivia 507:sta). Kortit
siis rakennettiin myyntipinnasta eika omasta datasta. `value`-kortti oli
sen takia systemaattisesti vaara — vastine asuu halvoissa pelaajissa jotka
maski poistaa maaritelman nojalla — ja `club-best` naytti 10 seuraa 20:sta.

Kumpikaan ei nakynyt virheena: typistetty lista on uskottava vastaus. Siksi
portit alla eivat testaa "tuleeko dataa" vaan "tuleeko KAIKKI data" ja
"kieltaytyyko generaattori maskatusta".
"""
from __future__ import annotations

import importlib.util
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "gen_share_card", ROOT / "scripts" / "gen_share_card.py")
gsc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gsc)


def _pl(pid, name, club, pos, xp, price=5.0, basis="pl_history"):
    return {"id": pid, "web_name": name, "team_short": club, "pos": pos,
            "price": price, "xp_horizon_total": xp, "data_basis": basis,
            "gameweeks": [{"gw": i} for i in range(1, 7)]}


def _payload(players):
    return {"meta": {}, "players": players}


def _args(pos="DEF"):
    return types.SimpleNamespace(pos=pos, top=10, min_mins=400)


def _run(monkeypatch, players, pos="DEF"):
    monkeypatch.setattr(gsc, "_xp_payload", lambda: _payload(players))
    return gsc.card_club_best(_args(pos))


# --------------------------------------------------------------------------
# Kattavuus — otsikko lupaa "every club"
# --------------------------------------------------------------------------

def test_every_club_appears_even_without_a_regular_starter(monkeypatch):
    """EI MINUUTTILATTIAA. Aiempi 60 xmins -lattia tuotti hyokkaajakortin
    jossa oli 10 seuraa 20:sta samalla kun otsikko lupasi 'every club'."""
    players = [_pl(i, f"P{i}", f"C{i}", "DEF", 3.0 + i) for i in range(20)]
    spec = _run(monkeypatch, players)
    assert len(spec["rows"]) == 20
    assert {r["tag"] for r in spec["rows"]} == {f"C{i}" for i in range(20)}


def test_rows_are_sorted_by_projection_descending(monkeypatch):
    players = [_pl(1, "A", "AAA", "DEF", 10.0), _pl(2, "B", "BBB", "DEF", 30.0),
               _pl(3, "C", "CCC", "DEF", 20.0)]
    spec = _run(monkeypatch, players)
    assert [r["name"] for r in spec["rows"]] == ["B", "C", "A"]
    assert [r["rank"] for r in spec["rows"]] == [1, 2, 3]


def test_only_the_requested_position_is_included(monkeypatch):
    players = [_pl(1, "Keeper", "AAA", "GKP", 40.0), _pl(2, "Back", "AAA", "DEF", 10.0)]
    spec = _run(monkeypatch, players)
    assert [r["name"] for r in spec["rows"]] == ["Back"]


def test_position_is_required(monkeypatch):
    monkeypatch.setattr(gsc, "_xp_payload", lambda: _payload([]))
    with pytest.raises(SystemExit):
        gsc.card_club_best(_args(pos=None))


# --------------------------------------------------------------------------
# Ero seuran kakkoseen — kortin oma kulma
# --------------------------------------------------------------------------

def test_gap_is_against_the_same_club_not_the_league(monkeypatch):
    """Kulma on 'onko tama seuran ainoa vaihtoehto'. Jos ero laskettaisiin
    listan seuraavaan riviin, se olisi eri kysymys eika kertoisi mitaan
    seuran syvyydesta."""
    players = [_pl(1, "Star", "AAA", "DEF", 30.0), _pl(2, "Sub", "AAA", "DEF", 20.0),
               _pl(3, "Other", "BBB", "DEF", 29.0)]
    spec = _run(monkeypatch, players)
    top = next(r for r in spec["rows"] if r["tag"] == "AAA")
    assert top["mid"] == "+10.0 vs next"


def test_identical_prior_values_say_tied_not_plus_zero(monkeypatch):
    """Nousijaseuroilla hintapriorin tasot ovat identtisia. '+0.0 vs next'
    lukisi mitatuksi eroksi joka sattui olemaan nolla."""
    players = [_pl(1, "A", "AAA", "DEF", 7.8, basis="no_history"),
               _pl(2, "B", "AAA", "DEF", 7.8, basis="no_history")]
    spec = _run(monkeypatch, players)
    assert spec["rows"][0]["mid"] == "tied with next"


def test_single_player_club_says_only_option(monkeypatch):
    players = [_pl(1, "Solo", "AAA", "DEF", 12.0)]
    assert _run(monkeypatch, players)["rows"][0]["mid"] == "only option"


# --------------------------------------------------------------------------
# Rehellisyysliput
# --------------------------------------------------------------------------

def test_players_without_pl_minutes_are_flagged(monkeypatch):
    players = [_pl(1, "Known", "AAA", "DEF", 20.0),
               _pl(2, "Unknown", "BBB", "DEF", 8.0, basis="no_history")]
    spec = _run(monkeypatch, players)
    flags = {r["name"]: r["badges"] for r in spec["rows"]}
    assert flags["Unknown"] == ["?"] and flags["Known"] == []


def test_the_flag_is_explained_and_counted_in_the_footer(monkeypatch):
    """Merkki ilman selitysta on koriste. Lukumaara kertoo lisaksi kuinka
    iso osa kortista on prioria eika mallia."""
    players = [_pl(1, "Known", "AAA", "DEF", 20.0),
               _pl(2, "Unknown", "BBB", "DEF", 8.0, basis="no_history")]
    foot = _run(monkeypatch, players)["footNote2"]
    assert "no Premier League minutes" in foot and "1 of 2" in foot


def test_footer_omits_the_flag_note_when_nothing_is_flagged(monkeypatch):
    """NEGATIIVINEN KONTROLLI: selitys ei saa olla aina paalla, muuten
    edellinen testi lapaisisi ilman etta merkkia lasketaan lainkaan."""
    players = [_pl(1, "Known", "AAA", "DEF", 20.0)]
    assert "price prior" not in _run(monkeypatch, players)["footNote2"]


# --------------------------------------------------------------------------
# Tarkistettavuus — vaite tarvitsee reitin
# --------------------------------------------------------------------------

def test_footer_does_not_point_at_the_masked_free_surface(monkeypatch):
    """goaliq.app/fpl renderoi listansa MASKATUSTA top-10:sta, joten 17 rivia
    20:sta ei olisi tarkistettavissa siella minne alatunniste ohjaa. Reitin
    on osoitettava julkiseen projektiotiedostoon."""
    players = [_pl(i, f"P{i}", f"C{i}", "DEF", 3.0 + i) for i in range(20)]
    foot = _run(monkeypatch, players)["footNote"]
    assert "goaliq.app/fpl" not in foot
    assert "github.com/veikkoville/football-prediction" in foot


# --------------------------------------------------------------------------
# Datalahde
# --------------------------------------------------------------------------

def test_shipped_artifact_carries_the_full_pool():
    """Repon artefaktin on oltava koko pooli eika teaser. Jos tama putoaa
    kymmeneen, jokainen kortti on hiljaa vaara."""
    data = gsc._xp_payload()
    assert len(data.get("players") or []) > 100
    assert not data.get("meta", {}).get("masked")
