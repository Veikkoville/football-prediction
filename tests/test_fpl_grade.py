"""Beat the model V1 — grade_one-testit (puhdas logiikka, ei IO:ta).

Hakijat syötetään funktioina, joten testit eivät kosketa verkkoa. Jokainen
grade_note-polku katetaan, ja kapteenikaava verifioidaan luvuilla joissa
väärä kaava (ilman tuplaa / väärä pelaaja) tuottaa ERI tuloksen — pooli jossa
kaikki arvot ovat samoja ei erottelisi mitään (28.7. mock-pooliopetus).
"""
from __future__ import annotations

from src.models.fpl_grade import (
    NOTE_KIND_NOT_GRADED,
    NOTE_NO_ENTRY,
    NOTE_OK,
    NOTE_PICKS_UNAVAILABLE,
    NOTE_PLAYER_MISSING,
    grade_one,
)

# Eri pisteet joka pelaajalla -> kaavavirheet näkyvät (ei homogeeninen pooli).
LIVE = {1: 12.0, 2: 3.0, 3: 7.0, 4: 0.0, 5: 9.0}

def _no_captain(_entry: int) -> int | None:
    raise AssertionError("fetch_captain ei saa ajaa tässä testissä")

def _no_transfers(_entry: int):
    raise AssertionError("fetch_transfers ei saa ajaa tässä testissä")


def test_captain_followed_tuplaa_pisteet():
    m, u, note = grade_one(
        "captain", {"id": 1}, {"id": 1}, True, LIVE, None,
        _no_captain, _no_transfers)
    assert (m, u, note) == (24.0, 24.0, NOTE_OK)  # 12 x 2, EI 12


def test_captain_deviated_lukee_toteutuneen_kapteenin():
    m, u, note = grade_one(
        "captain", {"id": 1}, {"deviated": True}, False, LIVE, 555,
        lambda e: 3, _no_transfers)
    assert (m, u, note) == (24.0, 14.0, NOTE_OK)  # malli 12x2, käyttäjä 7x2


def test_captain_deviated_ilman_entrya_ei_arvata():
    m, u, note = grade_one(
        "captain", {"id": 1}, {"deviated": True}, False, LIVE, None,
        _no_captain, _no_transfers)
    assert m == 24.0 and u is None and note == NOTE_NO_ENTRY


def test_captain_picks_ei_saatavilla():
    m, u, note = grade_one(
        "captain", {"id": 1}, {"deviated": True}, False, LIVE, 555,
        lambda e: None, _no_transfers)
    assert m == 24.0 and u is None and note == NOTE_PICKS_UNAVAILABLE


def test_captain_malli_puuttuu_livesta():
    m, u, note = grade_one(
        "captain", {"id": 999}, {"id": 999}, True, LIVE, None,
        _no_captain, _no_transfers)
    assert (m, u) == (None, None) and note == NOTE_PLAYER_MISSING


def test_transfer_followed_on_in_miinus_out():
    m, u, note = grade_one(
        "transfer", {"in_id": 5, "out_id": 2}, {"in_id": 5, "out_id": 2},
        True, LIVE, None, _no_captain, _no_transfers)
    assert (m, u, note) == (6.0, 6.0, NOTE_OK)  # 9 - 3, suunta merkitsee


def test_transfer_deviated_hold_on_nolla():
    # Käyttäjä ei tehnyt siirtoa -> vertailukohta 0.0, EI None: "pidin
    # joukkueen" on päätös jolla on tulos.
    m, u, note = grade_one(
        "transfer", {"in_id": 5, "out_id": 2}, {"deviated": True},
        False, LIVE, 555, _no_captain, lambda e: [])
    assert (m, u, note) == (6.0, 0.0, NOTE_OK)


def test_transfer_deviated_omat_siirrot_summataan():
    m, u, note = grade_one(
        "transfer", {"in_id": 5, "out_id": 2}, {"deviated": True},
        False, LIVE, 555, _no_captain,
        lambda e: [(1, 4), (3, 2)])  # (12-0) + (7-3) = 16
    assert (m, u, note) == (6.0, 16.0, NOTE_OK)


def test_tuntematon_kind_merkitaan_notella():
    m, u, note = grade_one(
        "chip", {"chip": "wildcard"}, {"chip": "wildcard"}, True, LIVE, None,
        _no_captain, _no_transfers)
    assert (m, u) == (None, None) and note == NOTE_KIND_NOT_GRADED


def test_negatiivinen_kontrolli_kaava_erottaa_tuplauksen():
    """Jos kapteenitupla poistettaisiin (x2 -> x1), tämän on kaaduttava.
    LIVE-pisteet on valittu niin että 12.0 != 24.0 — homogeeninen pooli
    (esim. kaikki 0) päästäisi rikotun kaavan läpi."""
    m, _u, _ = grade_one(
        "captain", {"id": 1}, {"id": 1}, True, LIVE, None,
        _no_captain, _no_transfers)
    assert m != LIVE[1], "tupla puuttuu: model_points == raa'at pisteet"
