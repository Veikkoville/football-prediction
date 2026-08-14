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


def _pl(pid, name, club, pos, xp, price=5.0, basis="pl_history",
        conf="high", xmins=85.0):
    return {"id": pid, "web_name": name, "team_short": club, "pos": pos,
            "price": price, "xp_horizon_total": xp, "data_basis": basis,
            "minutes_confidence": conf, "xmins": xmins,
            "gameweeks": [{"gw": i} for i in range(1, 7)]}


def _payload(players):
    return {"meta": {"generated_at": "2026-08-14T21:35:58", "next_gameweek": 1},
            "players": players}


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


def test_prior_tie_and_measured_tie_do_not_share_words(monkeypatch):
    """Kaksi taysin eri asiaa ei saa saada samoja sanoja. Nousijaseuran kolmen
    tasan identtinen luku tarkoittaa ettei mallilla ole tietoa erottaa heita;
    mitattu 0,02 pisteen ero on aito ja kiinnostava."""
    prior = [_pl(1, "A", "AAA", "DEF", 7.8, basis="no_history"),
             _pl(2, "B", "AAA", "DEF", 7.8, basis="no_history")]
    assert _run(monkeypatch, prior)["rows"][0]["mid"] == "no data to separate"
    measured = [_pl(1, "A", "AAA", "DEF", 18.42), _pl(2, "B", "AAA", "DEF", 18.40)]
    assert _run(monkeypatch, measured)["rows"][0]["mid"] == "tied with next"


def test_single_projected_row_does_not_claim_the_club_has_one_player(monkeypatch):
    """EI "only option". Koodi tietaa vain ettei PROJEKTIOSSA ole toista
    rivia — 80 pelaajaa suodattuu min_xp_total-rajalla ja loukkaantuneet ovat
    excluded-listalla. Liverpoolilla oli toinen hyokkaaja (Ekitike, vamma),
    joten "only option" olisi ollut julkisesti epatosi."""
    players = [_pl(1, "Solo", "AAA", "DEF", 12.0)]
    assert _run(monkeypatch, players)["rows"][0]["mid"] == "no 2nd projected"


# --------------------------------------------------------------------------
# Rehellisyysliput
# --------------------------------------------------------------------------

def test_players_without_pl_minutes_are_flagged(monkeypatch):
    players = [_pl(1, "Known", "AAA", "DEF", 20.0),
               _pl(2, "Unknown", "BBB", "DEF", 8.0, basis="no_history")]
    spec = _run(monkeypatch, players)
    flags = {r["name"]: r["badges"] for r in spec["rows"]}
    assert flags["Unknown"] == ["?"] and flags["Known"] == []


def test_thin_sample_is_not_flagged_as_having_no_minutes(monkeypatch):
    """🔴 REGRESSIO 14.8. Ehto oli `!= "pl_history"`, jolloin myos
    `limited_history` sai merkin — ja alatunniste vaittaa merkitysta rivista
    "no Premier League games yet". Trafford (LEE) on limited_history ja
    hanella on 360 PL-minuuttia MEIDAN OMASSA tiedostossamme. Kortti olisi
    julkaissut asiavirheen jonka lukija voi kumota tasan silla tiedostolla
    johon alatunniste ohjaa."""
    players = [_pl(1, "Trafford", "LEE", "GKP", 7.1, basis="limited_history")]
    assert _run(monkeypatch, players, pos="GKP")["rows"][0]["badges"] == []


def test_the_flag_is_explained_and_counted_in_the_footer(monkeypatch):
    """Merkki ilman selitysta on koriste. Lukumaara kertoo lisaksi kuinka
    iso osa kortista on prioria eika mallia."""
    players = [_pl(1, "Known", "AAA", "DEF", 20.0),
               _pl(2, "Unknown", "BBB", "DEF", 8.0, basis="no_history")]
    foot = _run(monkeypatch, players)["footNote2"]
    assert "no Premier League games yet" in foot and "1 of 2" in foot
    # "price prior" on mallijargonia julkisessa copyssa.
    assert "prior" not in foot


def test_footer_omits_the_flag_note_when_nothing_is_flagged(monkeypatch):
    """NEGATIIVINEN KONTROLLI: selitys ei saa olla aina paalla, muuten
    edellinen testi lapaisisi ilman etta merkkia lasketaan lainkaan."""
    players = [_pl(1, "Known", "AAA", "DEF", 20.0)]
    assert "no Premier League" not in _run(monkeypatch, players)["footNote2"]


# --------------------------------------------------------------------------
# Tarkistettavuus — vaite tarvitsee reitin
# --------------------------------------------------------------------------

def test_footer_does_not_point_at_the_masked_free_surface(monkeypatch):
    """goaliq.app/fpl renderoi listansa MASKATUSTA top-10:sta, joten 17 rivia
    20:sta ei olisi tarkistettavissa siella minne alatunniste ohjaa. Reitin
    on osoitettava julkiseen projektiotiedostoon."""
    players = [_pl(i, f"P{i}", f"C{i}", "DEF", 3.0 + i) for i in range(20)]
    foot = _run(monkeypatch, players)["footNote"]
    # Kohde on OMA sivunsa, ei /fpl-etusivu (maskattu top-10) eika raaka JSON
    # (reitti vastaa 200 mutta 1,3 MB tiedosto ei ole tarkistus vaan este).
    assert "goaliq.app/fpl/club-best" in foot
    assert ".json" not in foot
    assert not foot.rstrip().endswith("goaliq.app/fpl")


def test_subtitle_carries_the_data_date_and_the_gameweek_window(monkeypatch):
    """Lahdetiedosto paivittyy useita kertoja paivassa (14.8: nelja
    refresh-committia). Ilman paivaysta lukija nakee huomenna eri luvut eika
    kortilla ole mitaan joka selittaisi eron — se on tarkistettavuusaukko."""
    players = [_pl(1, "A", "AAA", "DEF", 20.0)]
    sub = _run(monkeypatch, players)["subtitle"]
    assert "as of 14 Aug" in sub and "GW1-6" in sub


def test_uncertain_minutes_are_shown_next_to_the_price(monkeypatch):
    """Villen saanto 14.8: luottamusindikaattori lukujen mukana. `?` EI kata
    tata tapausta — pelaajalla voi olla tayi PL-historia ja silti epavarmat
    minuutit (tyoparijako). Alisson oli tasmalleen se rivi."""
    players = [_pl(1, "Sure", "AAA", "GKP", 20.0),
               _pl(2, "Shared", "BBB", "GKP", 17.1, conf="med", xmins=72.0)]
    got = {r["name"]: r["team"] for r in _run(monkeypatch, players, pos="GKP")["rows"]}
    assert got["Shared"] == "5.0m · 72 min"
    assert got["Sure"] == "5.0m"


# --------------------------------------------------------------------------
# Datalahde
# --------------------------------------------------------------------------

def test_shipped_artifact_carries_the_full_pool():
    """Repon artefaktin on oltava koko pooli eika teaser. Jos tama putoaa
    kymmeneen, jokainen kortti on hiljaa vaara."""
    data = gsc._xp_payload()
    assert len(data.get("players") or []) > 100
    assert not data.get("meta", {}).get("masked")
