"""Portti: Championshipin, Eredivisien ja Primeira Ligan nimikartat.

TAUSTA (15.8.2026, Villen toimeksianto). Championship alkoi 14.8 ja La Liga
15.8. Kolme liigaa oli mobiilin liigavalitsimessa mutta EI track recordissa
lainkaan: ENG-Championship, NED-Eredivisie ja POR-Primeira Liga.

Lisays ei ole pelkka kolme rivia, koska FD:n ottelunimi ja mallin joukkuenimi
eivat kohtaa naissa liigoissa. Mittasin 15.8 live-/api/fixtures-nimet
live-/api/teams-listaa vasten samalla resolve_domestic_name()-funktiolla jota
putki kayttaa: big-5 ja BSA resolvoituivat taysin, nama kolme eivat.

Tama testi lukitsee mittauksen. Se ei kysy verkosta mitaan — joukkuelistat
ovat tassa sellaisina kuin tuotanto ne 15.8 palautti, jolloin testi kertoo
tasmalleen milta pohjalta overridet on kirjoitettu.

MIKSI PORTIN ARVOINEN: puuttuva override ohittaa ottelun varoituksella, mika
on nakyvaa. VAARA override on hiljainen — se logaa julkiseen track recordiin
oikean nakoisen ennusteen VAARALLE joukkueelle, eika mikaan huuda.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.accuracy_pipeline as ap  # noqa: E402
from scripts.accuracy_pipeline import (  # noqa: E402
    DOMESTIC_COMPETITIONS,
    resolve_domestic_name,
)

# FD:n TODELLISET osallistujat 15.8.2026 (/api/fixtures, 45 vrk ikkuna).
# Kiintea lista tarkoituksella: portti ei saa lukea samaa konfiguraatiota jota
# se tarkistaa. Tiedosto on UTF-8 (nimissa on aksentteja, esim. 'CS Maritimo'
# ja 'Vitoria SC') — se kirjoitettiin ohjelmallisesti eika konsolin lapi, koska
# konsoliputki mankeloi ne.
FD_PARTICIPANTS: dict[str, list[str]] = json.loads(
    (Path(__file__).parent / "fixtures" / "fd_participants_2026-08-15.json")
    .read_text(encoding="utf-8")
)

# Mallin joukkuenimet 15.8.2026 tuotannosta (/api/teams).
MODEL_TEAMS = {
    "ELC": [
        "Birmingham", "Blackburn", "Bristol City", "Charlton", "Coventry",
        "Derby", "Hull", "Ipswich", "Leicester", "Middlesbrough", "Millwall",
        "Norwich", "Oxford", "Portsmouth", "Preston", "QPR", "Sheffield United",
        "Sheffield Weds", "Southampton", "Stoke", "Swansea", "Watford",
        "West Brom", "Wrexham",
    ],
    "DED": [
        "AZ Alkmaar", "Ajax", "Cambuur", "Den Haag", "Excelsior", "Feyenoord",
        "For Sittard", "Go Ahead Eagles", "Groningen", "Heerenveen", "Heracles",
        "NAC Breda", "Nijmegen", "PSV Eindhoven", "Sparta Rotterdam", "Telstar",
        "Twente", "Utrecht", "Volendam", "Willem II", "Zwolle",
    ],
    "PPL": [
        "AVS", "Academico Viseu", "Alverca", "Arouca", "Benfica", "Casa Pia",
        "Estoril", "Estrela", "Famalicao", "Gil Vicente", "Guimaraes",
        "Maritimo", "Moreirense", "Nacional", "Porto", "Rio Ave", "Santa Clara",
        "Sp Braga", "Sp Lisbon", "Tondela",
    ],
}

# ELC:n kuusi nimea joille EI OLE mallinimea johon osoittaa: nousseet
# League Onesta tai pudonneet PL:sta 26/27:aan, eika E1-dataa kaudelta 2627
# ollut viela julkaistu (football-data.co.uk palautti 300, mitattu 15.8).
# Nama ohitetaan varoituksella. Jos joku "korjaa" ne overrideilla, se osoittaa
# vaaraan joukkueeseen — siksi ne ovat tassa nimeltä.
ELC_KNOWN_UNRESOLVED = [
    "Bolton Wanderers FC", "Burnley FC", "Cardiff City FC",
    "Lincoln City FC", "West Ham United FC", "Wolverhampton Wanderers FC",
]


@pytest.mark.parametrize("code,league", [
    ("ELC", "ENG-Championship"),
    ("DED", "NED-Eredivisie"),
    ("PPL", "POR-Primeira Liga"),
])
def test_the_three_leagues_are_registered(code, league):
    assert code in DOMESTIC_COMPETITIONS, f"{code} puuttuu track recordista"
    assert DOMESTIC_COMPETITIONS[code]["league"] == league


@pytest.mark.parametrize("code", ["ELC", "DED", "PPL"])
def test_every_override_points_at_a_real_model_team(code):
    """Override joka osoittaa olemattomaan nimeen palauttaa None — ottelu
    ohittuisi hiljaa, ja rivi nayttaisi silti oikein konfiguroidulta."""
    teams = MODEL_TEAMS[code]
    for fd_name, model_name in DOMESTIC_COMPETITIONS[code]["overrides"].items():
        assert model_name in teams, (
            f"{code}: override '{fd_name}' -> '{model_name}', jota ei ole "
            f"mallin joukkueissa")


@pytest.mark.parametrize("code", ["ELC", "DED", "PPL"])
def test_every_override_is_actually_needed(code):
    """Ilman overridea normalisointi ei osu — muuten rivi on turhaa painolastia
    joka teeskentelee mittausta."""
    teams = MODEL_TEAMS[code]
    for fd_name, model_name in DOMESTIC_COMPETITIONS[code]["overrides"].items():
        without = resolve_domestic_name(fd_name, teams, {})
        assert without != model_name, (
            f"{code}: '{fd_name}' resolvoituu ilman overridea -> rivi on turha")


@pytest.mark.parametrize("code", ["ELC", "DED", "PPL"])
def test_every_fd_participant_resolves_or_is_a_known_gap(code):
    """POSITIIVINEN KONTROLLI koko liigalle.

    🔴 Kirjoitin taman ensin niin etta se iteroi OVERRIDE-KONFIGURAATIOTA. Ajoin
    negatiivisen kontrollin — poistin QPR-overriden — ja portti pysyi vihreana:
    poistettu nimi ei ollut enaa konfiguraatiossa, joten mitaan ei tarkistettu.
    Portti mittasi itseaan. Siksi lahde on nyt KIINTEA mitattu osallistujalista
    (tests/fixtures/fd_participants_2026-08-15.json, /api/fixtures 15.8), jota
    overriden poistaminen ei voi kutistaa.
    """
    teams = MODEL_TEAMS[code]
    cfg = DOMESTIC_COMPETITIONS[code]
    ov = cfg["overrides"]
    known = set(ELC_KNOWN_UNRESOLVED) if code == "ELC" else set()
    participants = FD_PARTICIPANTS[cfg["league"]]
    assert len(participants) >= 18, f"{code}: osallistujalista naytti vajaalta"
    for fd_name in participants:
        got = resolve_domestic_name(fd_name, teams, ov)
        if fd_name in known:
            assert got is None, (
                f"{code}: '{fd_name}' oli tunnettu aukko mutta resolvoituu nyt "
                f"-> '{got}'. Jos malli on saanut sille dataa, poista se "
                f"ELC_KNOWN_UNRESOLVED-listalta.")
        else:
            assert got is not None, (
                f"{code}: '{fd_name}' ei resolvoidu malliin — ottelut joissa se "
                f"pelaa putoavat track recordista hiljaa")


@pytest.mark.parametrize("code", ["ELC", "DED", "PPL"])
def test_no_override_maps_a_name_onto_itself(code):
    """Naissa kolmessa identiteettirivi kertoisi etta kirjoittaja ei mitannut.

    KOSKEE VAIN naita kolmea. Kirjoitin taman ensin kaikille kilpailuille ja se
    kaatui BSA:n riviin 'Sport Recife' -> 'Sport Recife'. Mittasin sen: nimi
    resolvoituu ilman overridea, mutta niin resolvoituu myos FD:n toinen muoto
    'Sport Club do Recife' — identiteettirivi on siis tahallinen ankkuri sille
    ETTA kumpi muoto valitaan, ei sekaannus. Portin premissi oli vaara, ei
    BSA:n konfiguraatio.
    """
    for fd_name, model_name in DOMESTIC_COMPETITIONS[code]["overrides"].items():
        assert fd_name != model_name, f"{code}: no-op override '{fd_name}'"


# ---------------------------------------------------------------------------
# 429-uusinta
# ---------------------------------------------------------------------------
# MITATTU VIKA (ajo 31871111836, 15.8.2026): kolmen liigan lisays nosti
# kilpailumaaran 7 -> 10 ja FD:n minuuttiraja alkoi osua. DED sai 429:n ja
# PUTOSI POIS KOKONAAN — lokissa ei ollut LOG[DED]-rivia lainkaan, vain yksi
# varoitus 245 muun varoituksen seassa. Yhden liigan hiljainen katoaminen
# track recordista on juuri se mita talta putkelta ei saa tapahtua.


class _Resp:
    def __init__(self, status_code, text="", payload=None):
        self.status_code = status_code
        self.text = text
        self._payload = payload or {}

    def json(self):
        return self._payload


@pytest.fixture
def _no_sleep(monkeypatch):
    import src.data.football_data_org as fdo
    monkeypatch.setattr(ap.time, "sleep", lambda s: None)
    monkeypatch.setattr(fdo, "_await_rate_limit", lambda: None)
    monkeypatch.setattr(fdo, "_api_key", lambda: "test-key")


def test_429_is_retried_and_succeeds(_no_sleep, monkeypatch):
    import requests
    calls = []

    def fake_get(url, **kw):
        calls.append(url)
        if len(calls) < 3:
            return _Resp(429, '{"message":"You reached your request limit. '
                              'Wait 1 seconds.","errorCode":429}')
        return _Resp(200, payload={"matches": [{"id": 1}]})

    monkeypatch.setattr(requests, "get", fake_get)
    got = ap._fetch_matches("DED")
    assert got == [{"id": 1}], "429 piti uusia, ei pudottaa liigaa"
    assert len(calls) == 3


def test_429_gives_up_after_bounded_retries(_no_sleep, monkeypatch):
    """Rikkinainen kiintio ei saa jumittaa ajoa loputtomiin."""
    import requests
    calls = []

    def fake_get(url, **kw):
        calls.append(url)
        return _Resp(429, "Wait 1 seconds")

    monkeypatch.setattr(requests, "get", fake_get)
    assert ap._fetch_matches("DED") is None
    assert len(calls) == 4, f"yrityksia oli {len(calls)}, odotettu 4"


def test_non_429_error_is_not_retried(_no_sleep, monkeypatch):
    """403/404 ei parane odottamalla — uusinta olisi vain hukkakutsuja."""
    import requests
    calls = []

    def fake_get(url, **kw):
        calls.append(url)
        return _Resp(403, "forbidden")

    monkeypatch.setattr(requests, "get", fake_get)
    assert ap._fetch_matches("DED") is None
    assert len(calls) == 1
