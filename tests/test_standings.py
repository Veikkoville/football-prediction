"""/api/standings: WC-grouped (#19) + domestic-regressio.

FD-kutsu mockataan (monkeypatch requests.get api.main-nimiavaruudessa) →
testit ajavat offline ja deterministisesti. Domestic-testi on golden-tyylinen:
odotettu output on käsin johdettu VANHASTA litistyslogiikasta ennen #19-
refaktorointia (max|diff|=0 eli täysi ==-vertailu).
"""
from __future__ import annotations

import json


def _fd_row(pos, name, short, played, won, draw, lost, gf, ga, form="W"):
    return {
        "position": pos,
        "team": {"name": name, "shortName": short, "crest": f"https://crests.test/{short}.png"},
        "playedGames": played,
        "won": won,
        "draw": draw,
        "lost": lost,
        "goalsFor": gf,
        "goalsAgainst": ga,
        "goalDifference": gf - ga,
        "points": won * 3 + draw,
        "form": form,
    }


class _FakeResp:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


# FD:n lohkomoodi (ilman season-paramia, verifioitu 12.6.2026): 12 TOTAL-
# elementtiä group-nimillä. Testidata: 2 lohkoa + HOME-elementti joka EI saa
# päätyä outputtiin.
WC_GROUPED_PAYLOAD = {
    "standings": [
        {
            "stage": "ALL", "type": "TOTAL", "group": "Group A",
            "table": [
                _fd_row(1, "Mexico", "Mexico", 1, 1, 0, 0, 2, 0),
                _fd_row(2, "South Korea", "South Korea", 1, 1, 0, 0, 2, 1),
                _fd_row(3, "Czechia", "Czechia", 1, 0, 0, 1, 1, 2, form="L"),
                _fd_row(4, "South Africa", "South Africa", 1, 0, 0, 1, 0, 2, form="L"),
            ],
        },
        {
            "stage": "ALL", "type": "TOTAL", "group": "Group B",
            "table": [
                _fd_row(1, "Bosnia-Herzegovina", "Bosnia-H.", 0, 0, 0, 0, 0, 0, form=None),
                _fd_row(1, "Canada", "Canada", 0, 0, 0, 0, 0, 0, form=None),
            ],
        },
        {"stage": "ALL", "type": "HOME", "group": "Group A", "table": []},
    ]
}

# FD:n domestic-muoto: TOTAL/HOME/AWAY ilman groupia.
DOMESTIC_PAYLOAD = {
    "standings": [
        {
            "stage": "REGULAR_SEASON", "type": "TOTAL", "group": None,
            "table": [
                _fd_row(1, "Arsenal FC", "Arsenal", 38, 28, 6, 4, 91, 29),
                _fd_row(2, "Liverpool FC", "Liverpool", 38, 25, 9, 4, 86, 41),
            ],
        },
        {"stage": "REGULAR_SEASON", "type": "HOME", "group": None, "table": []},
        {"stage": "REGULAR_SEASON", "type": "AWAY", "group": None, "table": []},
    ]
}

# Golden: VANHAN koodipolun output DOMESTIC_PAYLOADille (johdettu käsin
# litistyslogiikasta ennen #19:ää). Ei form-kenttää, ei groups-avainta.
DOMESTIC_GOLDEN = {
    "league": "ENG-Premier League",
    "season": "2526",
    "rows": [
        {
            "position": 1, "team_name": "Arsenal FC", "team_short_name": "Arsenal",
            "team_crest": "https://crests.test/Arsenal.png", "played_games": 38,
            "won": 28, "draw": 6, "lost": 4, "goals_for": 91, "goals_against": 29,
            "goal_difference": 62, "points": 90,
        },
        {
            "position": 2, "team_name": "Liverpool FC", "team_short_name": "Liverpool",
            "team_crest": "https://crests.test/Liverpool.png", "played_games": 38,
            "won": 25, "draw": 9, "lost": 4, "goals_for": 86, "goals_against": 41,
            "goal_difference": 45, "points": 84,
        },
    ],
}


def _patch_fd(monkeypatch, payload, calls):
    import api.main as api_main

    def fake_get(url, headers=None, timeout=None):
        calls.append(url)
        return _FakeResp(payload)

    monkeypatch.setattr(api_main.requests, "get", fake_get)
    # Endpoint vaatii avaimen → dummy riittää koska verkkoa ei kutsuta.
    monkeypatch.setenv("FOOTBALL_DATA_API_KEY", "test-key")


def test_wc_standings_grouped(client, monkeypatch):
    """WC (#19): groups-rakenne, kaikki TOTAL-lohkot, rivit + form, EI season-paramia."""
    calls: list[str] = []
    _patch_fd(monkeypatch, WC_GROUPED_PAYLOAD, calls)

    r = client.get("/api/standings", params={"league": "INT-World Cup"})
    assert r.status_code == 200
    body = r.json()

    # FD-kutsu ilman season-paramia (season-param → litteä/404, ks. docstring)
    assert len(calls) == 1
    assert calls[0] == "https://api.football-data.org/v4/competitions/WC/standings"

    assert body["league"] == "INT-World Cup"
    assert body["season"] is None
    assert [g["group"] for g in body["groups"]] == ["Group A", "Group B"]

    ga = body["groups"][0]["rows"]
    assert len(ga) == 4
    mexico = ga[0]
    assert mexico == {
        "position": 1, "team_name": "Mexico", "team_short_name": "Mexico",
        "team_crest": "https://crests.test/Mexico.png", "played_games": 1,
        "won": 1, "draw": 0, "lost": 0, "goals_for": 2, "goals_against": 0,
        "goal_difference": 2, "points": 3, "form": "W",
    }
    # Pelaamaton lohko: 0-rivit ovat validia dataa (ei virhe)
    gb = body["groups"][1]["rows"]
    assert all(row["points"] == 0 and row["played_games"] == 0 for row in gb)


def test_domestic_standings_unchanged(client, monkeypatch):
    """Domestic-regressio: output == golden (max|diff|=0), season-param mukana."""
    calls: list[str] = []
    _patch_fd(monkeypatch, DOMESTIC_PAYLOAD, calls)

    r = client.get(
        "/api/standings",
        params={"league": "ENG-Premier League", "season": "2526"},
    )
    assert r.status_code == 200

    assert len(calls) == 1
    assert calls[0] == "https://api.football-data.org/v4/competitions/PL/standings?season=2025"

    # Bittitarkka vertailu JSON-round-tripin jälkeen (sama normalisointi kuin
    # test_domestic_golden.py)
    assert json.loads(json.dumps(r.json())) == json.loads(json.dumps(DOMESTIC_GOLDEN))


def test_domestic_standings_no_total(client, monkeypatch):
    """Domestic ilman TOTAL-elementtiä → tyhjä rows (vanha käytös ennallaan)."""
    calls: list[str] = []
    _patch_fd(monkeypatch, {"standings": []}, calls)

    r = client.get(
        "/api/standings",
        params={"league": "ENG-Premier League", "season": "2526"},
    )
    assert r.status_code == 200
    assert r.json() == {"league": "ENG-Premier League", "season": "2526", "rows": []}


# ---------------------------------------------------------------------------
# #25: free-tier-lisäliigat fixtures/standings-mappauksessa
# ---------------------------------------------------------------------------
def test_fixture_standings_codes_extend_without_touching_loader_codes():
    """ELC/DED/PPL/BSA saavat fixtures+standings-koodit, mutta EIVÄT saa
    ilmestyä COMPETITION_CODES:iin — se flippaisi loaderin historialähteen
    FD.orgiin ja vaihtaisi mallin joukkuenimet (ks. kommentti moduulissa)."""
    from src.data.football_data_org import COMPETITION_CODES, FIXTURE_STANDINGS_CODES

    extra = {
        "ENG-Championship": "ELC",
        "NED-Eredivisie": "DED",
        "POR-Primeira Liga": "PPL",
        "BRA-Serie A": "BSA",
    }
    for liiga, code in extra.items():
        assert FIXTURE_STANDINGS_CODES[liiga] == code
        assert liiga not in COMPETITION_CODES  # loader-lähde ei muutu
    # vanhat mappaukset säilyvät sellaisenaan
    for liiga, code in COMPETITION_CODES.items():
        assert FIXTURE_STANDINGS_CODES[liiga] == code
