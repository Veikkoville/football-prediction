"""SQUAD-SIGNALS-WATCH vaihe A: laukaisimet 1-4.

Speksin luku 5 vaatii nimenomaan negatiivisen kontrollin: "testi joka syottaa
muuttumattoman bootstrapin ja odottaa NOLLA liputusta. Ilman sita vahti voi
liputtaa kaiken ja nayttaa valppaalta."
"""
from __future__ import annotations

from src.models.squad_signals import (
    CHANCE_CONFLICT_THRESHOLD,
    Snapshot,
    TRIGGER_CHANCE_CONFLICT,
    TRIGGER_NEW_PLAYER,
    TRIGGER_SET_PIECE,
    TRIGGER_STATUS,
    TRIGGER_TRANSFER,
    diff_signals,
    summarise,
    team_name_map,
)


def _el(pid=1, name="Raya", team=1, status="a", news_added=None,
        chance=None, cost=60, pens=None, fk=None, corners=None):
    return {
        "id": pid, "web_name": name, "team": team, "status": status,
        "news": "", "news_added": news_added,
        "chance_of_playing_next_round": chance, "now_cost": cost,
        "penalties_order": pens, "direct_freekicks_order": fk,
        "corners_and_indirect_freekicks_order": corners,
    }


def _boot(elements, teams=None):
    return {
        "elements": elements,
        "teams": teams or [{"id": 1, "short_name": "ARS"},
                           {"id": 2, "short_name": "CHE"}],
    }


def _snap(elements, when="2026-08-16"):
    return Snapshot.from_bootstrap(_boot(elements), when)


def _proj(rows):
    return {"players": rows}


# --- 🔴 negatiivinen kontrolli (speksin luku 5) ---------------------------

def test_unchanged_bootstrap_produces_zero_flags():
    els = [_el(1, "Raya"), _el(2, "Saka", chance=100, pens=2),
           _el(3, "Palmer", team=2, pens=1, fk=1, corners=1)]
    prev = _snap(els, "2026-08-15")
    curr = _snap(els, "2026-08-16")
    assert diff_signals(prev, curr) == []


def test_first_run_flags_nothing():
    """Ensimmainen ajo ei ole muutos. Jos se liputtaisi koko rosterin, vahti
    nayttaisi valppaalta ja olisi pelkkaa kohinaa."""
    curr = _snap([_el(1), _el(2, "Saka"), _el(3, "Palmer")])
    assert diff_signals(None, curr) == []


# --- laukaisin 1: saatavuus ----------------------------------------------

def test_status_change_is_flagged():
    prev = _snap([_el(2, "Saka", status="a")])
    curr = _snap([_el(2, "Saka", status="i")])
    flags = diff_signals(prev, curr)
    assert [f.trigger for f in flags] == [TRIGGER_STATUS]
    assert (flags[0].before, flags[0].after) == ("a", "i")


def test_new_news_flagged_even_when_status_unchanged():
    """Status voi pysya samana kun uutinen tarkentuu ("knock" -> "out 3
    weeks"). Pelkka status-vahti menettaisi sen."""
    prev = _snap([_el(2, "Saka", status="d", news_added="2026-08-10T09:00:00Z")])
    curr = _snap([_el(2, "Saka", status="d", news_added="2026-08-16T09:00:00Z")])
    flags = diff_signals(prev, curr)
    assert len(flags) == 1 and flags[0].field == "news_added"


# --- laukaisin 2: erimielisyys FPL:n kanssa -------------------------------

def test_chance_change_without_disagreement_is_not_flagged():
    """Pelkka muutos ei riita. FPL heiluttaa lukua rutiinilla, ja ilman
    erimielisyysehtoa tama olisi vahdin aanekkain ja hyodyttomin laukaisin."""
    prev = _snap([_el(2, "Saka", chance=75)])
    curr = _snap([_el(2, "Saka", chance=100)])
    proj = _proj([{"id": 2, "predicted_starts": 95.0, "owned_pct": 30.0}])
    assert diff_signals(prev, curr, proj) == []


def test_chance_change_with_disagreement_is_flagged():
    """Kinsky-tapaus 14.8: FPL 100 %, meilla 0.38."""
    prev = _snap([_el(2, "Kinsky", chance=None)])
    curr = _snap([_el(2, "Kinsky", chance=100)])
    proj = _proj([{"id": 2, "predicted_starts": 38.0, "owned_pct": 19.5}])
    flags = diff_signals(prev, curr, proj)
    assert [f.trigger for f in flags] == [TRIGGER_CHANCE_CONFLICT]
    assert flags[0].our_p_start == 0.38
    assert flags[0].owned_pct == 19.5


def test_threshold_calibration_keeps_routine_rotation_quiet():
    """Kynnys on kalibroitu tunnettuihin tapauksiin eika valittu pyoreana
    lukuna. Tavallinen rotaatioepavarmuus ei saa liputtua."""
    prev = _snap([_el(2, "Rotator", chance=None)])
    curr = _snap([_el(2, "Rotator", chance=75)])
    proj = _proj([{"id": 2, "predicted_starts": 50.0, "owned_pct": 5.0}])
    assert abs(0.75 - 0.50) < CHANCE_CONFLICT_THRESHOLD
    assert diff_signals(prev, curr, proj) == []


def test_chance_conflict_needs_our_number():
    """Ilman omaa lukua ei ole erimielisyytta, joten ei liputusta - muuten
    jokainen projektiosta puuttuva pelaaja olisi jatkuva liputus."""
    prev = _snap([_el(2, "Tuntematon", chance=None)])
    curr = _snap([_el(2, "Tuntematon", chance=100)])
    assert diff_signals(prev, curr, _proj([])) == []


# --- laukaisin 3: erikoistilanteet ---------------------------------------

def test_set_piece_order_change_is_flagged_without_ownership_filter():
    """Jokainen liike on suoraan pisteita, joten tassa EI ole
    omistuskynnysta - myos 0,1 %:n omistuksella oleva uusi pilkkuvuoro on
    juuri se mita halutaan tietaa ennen muita."""
    prev = _snap([_el(3, "Palmer", team=2, pens=2)])
    curr = _snap([_el(3, "Palmer", team=2, pens=1)])
    proj = _proj([{"id": 3, "predicted_starts": 80.0, "owned_pct": 0.1}])
    flags = diff_signals(prev, curr, proj)
    assert [f.trigger for f in flags] == [TRIGGER_SET_PIECE]
    assert flags[0].field == "penalties_order"
    assert (flags[0].before, flags[0].after) == (2, 1)


def test_all_three_set_piece_fields_are_watched():
    prev = _snap([_el(3, "Palmer", team=2, pens=1, fk=1, corners=1)])
    curr = _snap([_el(3, "Palmer", team=2, pens=1, fk=2, corners=3)])
    fields = {f.field for f in diff_signals(prev, curr)}
    assert fields == {"direct_freekicks_order",
                      "corners_and_indirect_freekicks_order"}


# --- laukaisin 4: siirrot -------------------------------------------------

def test_team_change_is_flagged_with_readable_team_names():
    prev = _snap([_el(4, "Mover", team=1)])
    curr = _snap([_el(4, "Mover", team=2)])
    names = team_name_map(_boot([]))
    flags = diff_signals(prev, curr, None, names)
    assert [f.trigger for f in flags] == [TRIGGER_TRANSFER]
    assert (flags[0].before, flags[0].after) == ("ARS", "CHE")


def test_new_player_is_flagged_once_and_not_as_status_change():
    prev = _snap([_el(1, "Raya")])
    curr = _snap([_el(1, "Raya"), _el(9, "Uusi", team=2, status="a")])
    flags = diff_signals(prev, curr)
    assert [f.trigger for f in flags] == [TRIGGER_NEW_PLAYER]


# --- jarjestys ja yhteenveto ---------------------------------------------

def test_flags_are_sorted_by_ownership_first():
    """Raportin lukija katsoo ylimmat rivit. Omistus on se mika ratkaisee
    kuinka monta ihmista muutos koskee."""
    prev = _snap([_el(1, "Pieni", status="a"), _el(2, "Iso", status="a")])
    curr = _snap([_el(1, "Pieni", status="i"), _el(2, "Iso", status="i")])
    proj = _proj([{"id": 1, "predicted_starts": 50.0, "owned_pct": 0.4},
                  {"id": 2, "predicted_starts": 50.0, "owned_pct": 42.0}])
    flags = diff_signals(prev, curr, proj)
    assert [f.web_name for f in flags] == ["Iso", "Pieni"]


def test_summarise_counts_by_trigger():
    prev = _snap([_el(1, "A", status="a"), _el(2, "B", team=1)])
    curr = _snap([_el(1, "A", status="i"), _el(2, "B", team=2)])
    assert summarise(diff_signals(prev, curr)) == {
        TRIGGER_STATUS: 1, TRIGGER_TRANSFER: 1}


# --- lumikuvan kierratys --------------------------------------------------

def test_snapshot_roundtrip_is_lossless_for_watched_fields():
    """Lumikuva kirjoitetaan levylle ja luetaan seuraavana paivana. Jos
    kierratys havittaa kentan, vahti liputtaisi sen joka paiva uudelleen."""
    els = [_el(1, "Raya", chance=75, pens=1, fk=2, corners=3,
               news_added="2026-08-16T09:00:00Z")]
    snap = _snap(els)
    back = Snapshot.from_dict(snap.as_dict())
    assert diff_signals(snap, back) == []
    assert back.taken_at == snap.taken_at
