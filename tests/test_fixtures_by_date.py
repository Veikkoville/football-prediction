"""Paivanakyma ei saa koskaan lahtea upstreamiin (16.8.2026).

Villen pyynto: appin tuleviin otteluihin nakyma jossa nakyy KAIKKI samana
paivana pelattavat ottelut, ei yhta liigaa kerrallaan.

🔴 Naiivi toteutus hakisi jokaisen liigan erikseen pyyntopolulla: yksi
sivunavaus = ~14 ulospain lahtevaa kutsua. football-data.orgin ilmaiskiintio
on ~10/min per avain, joten se ei olisi hidas vaan RIKKI. Sama kaava tuotti
16.8 aamulla 429-ryopyn ja 38 sekunnin jumin, ja korjaus oli siirtaa KAIKKI
haku taustalle. Tama endpoint ei saa purkaa sita paatosta.

Portti mittaa siksi kahta asiaa:
  1. vastaus kootaan valimuistista (oikeat rivit oikealta paivalta)
  2. mikaan pyyntopolun haara EI kutsu upstream-hakua

Kohta 2 on se joka merkitsee. Ilman sita testi lapaisisi myos toteutuksella
joka hakee verkosta aina kun valimuistista puuttuu jotain - eli tasan silloin
kun se on vaarallisinta.
"""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

import api.main as m

CODE_A, CODE_B = "PL", "PD"


def _match(utc: str, home: str, away: str, md: int = 1) -> dict:
    return {
        "utcDate": utc,
        "homeTeam": {"name": home, "shortName": home[:3].upper()},
        "awayTeam": {"name": away, "shortName": away[:3].upper()},
        "matchday": md,
    }


@pytest.fixture
def client(monkeypatch):
    m._FD_HTTP_CACHE.clear()
    now = time.time()
    m._FD_HTTP_CACHE[f"fixtures:{CODE_A}:35"] = (now, {"matches": [
        _match("2026-08-21T19:00:00Z", "Arsenal", "Chelsea"),
        _match("2026-08-22T14:00:00Z", "Spurs", "Everton"),
        # Vastustaja viela ratkeamatta -> ei saa paatya listaan.
        {"utcDate": "2026-08-21T17:00:00Z", "homeTeam": {"name": None},
         "awayTeam": {"name": "TBD"}, "matchday": 1},
    ]})
    m._FD_HTTP_CACHE[f"fixtures:{CODE_B}:35"] = (now, {"matches": [
        _match("2026-08-21T16:30:00Z", "Real Madrid", "Sevilla"),
    ]})
    yield TestClient(m.app)
    m._FD_HTTP_CACHE.clear()


def test_returns_every_league_playing_that_day(client):
    r = client.get("/api/fixtures/by-date", params={"date": "2026-08-21"})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2, "molempien liigojen ottelu pitaa nakya"
    names = [g["code"] for g in body["leagues"]]
    assert set(names) == {CODE_A, CODE_B}


def test_leagues_are_ordered_by_first_kickoff(client):
    body = client.get("/api/fixtures/by-date",
                      params={"date": "2026-08-21"}).json()
    # Real Madrid 16:30 alkaa ennen Arsenalia 19:00.
    assert body["leagues"][0]["code"] == CODE_B


def test_other_days_are_not_leaked_in(client):
    body = client.get("/api/fixtures/by-date",
                      params={"date": "2026-08-22"}).json()
    assert body["total"] == 1
    assert body["leagues"][0]["fixtures"][0]["home_team"] == "Spurs"


def test_unresolved_opponent_is_skipped(client):
    body = client.get("/api/fixtures/by-date",
                      params={"date": "2026-08-21"}).json()
    teams = [f["home_team"] for g in body["leagues"] for f in g["fixtures"]]
    assert None not in teams and "TBD" not in teams


def test_empty_day_is_not_an_error(client):
    r = client.get("/api/fixtures/by-date", params={"date": "2026-09-30"})
    assert r.status_code == 200
    assert r.json()["total"] == 0


def test_coverage_separates_no_matches_from_not_known_yet(client):
    """Tyhja paiva ja lammittamaton valimuisti nayttavat samalta ilman
    tata lukua, ja klientti kertoisi kayttajalle "ei otteluita" silloinkin
    kun oikea vastaus on "ei viela tiedossa"."""
    body = client.get("/api/fixtures/by-date",
                      params={"date": "2026-09-30"}).json()
    assert body["leagues_covered"] == 2
    assert body["leagues_known"] >= 2

    m._FD_HTTP_CACHE.clear()
    cold = client.get("/api/fixtures/by-date",
                      params={"date": "2026-08-21"}).json()
    assert cold["leagues_covered"] == 0, (
        "kylma valimuisti pitaa erottua tyhjasta paivasta")


def test_bad_date_is_rejected(client):
    assert client.get("/api/fixtures/by-date",
                      params={"date": "21.8.2026"}).status_code == 400


def test_request_path_never_calls_upstream(client, monkeypatch):
    """🔴 Taman portin koko pointti.

    Laskuri eika poikkeus: `_fd_get_cached` nielee poikkeuksia omissa
    haaroissaan, joten raise-pohjainen vahti voisi lapaista vaikka kutsu
    tapahtuisi (sama vikaluokka kuin fail-open-nielaisee-mutaatiotestin).
    """
    calls = {"n": 0}

    def _boom(*a, **kw):
        calls["n"] += 1
        return {}, False

    monkeypatch.setattr(m, "_fd_get_cached", _boom)
    monkeypatch.setattr(m, "_fd_fetch_once",
                        lambda *a, **kw: calls.__setitem__("n", calls["n"] + 1))
    monkeypatch.setattr(m, "_fd_kick_refresh",
                        lambda *a, **kw: calls.__setitem__("n", calls["n"] + 1))

    r = client.get("/api/fixtures/by-date", params={"date": "2026-08-21"})
    assert r.status_code == 200
    assert r.json()["total"] == 2, "vastaus pitaa yha koostua valimuistista"
    assert calls["n"] == 0, (
        "paivanakyma kutsui upstream-hakua pyyntopolulla. Yksi sivunavaus "
        "= ~14 kutsua, ja FD:n kiintio on ~10/min -> 429 ja jumi.")
