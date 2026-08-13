"""Redirect- ja Div-vartija footballdata-loaderille (13.8.2026).

Tausta: football-data.co.uk 301-ohjaa puuttuvat kausitiedostot lähimpään
olemassa olevaan nimeen (mitattu: 2627/E0.csv → EC.csv = Conference,
2627/SP1.csv → P1.csv = Portugalin liiga). Seurattu redirect treenasi
PL-mallin Conference-datalla → Aldershot ym. tuotannon joukkuevalitsimessa
12.8 illalla, aina kun Understat kaatui ja fallback laukesi.

Hermeettinen: requests.get mockataan src.data.footballdata-namespacessa,
CACHE_DIR ohjataan tmp_pathiin.
"""
from __future__ import annotations

import pytest

import src.data.footballdata as fd


E0_CSV = (
    "Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG\n"
    "E0,08/08/2026,15:00,Arsenal,Chelsea,2,1\n"
    "E0,09/08/2026,17:30,Liverpool,Everton,1,1\n"
)

EC_CSV = (
    "Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG\n"
    "EC,08/08/2026,15:00,Aldershot,Boston,1,3\n"
    "EC,08/08/2026,15:00,Boreham Wood,Tamworth,3,3\n"
)

# Vanha formaatti ilman Div-saraketta — vartija ei saa hylätä tätä.
DIVITON_CSV = (
    "Date,Time,HomeTeam,AwayTeam,FTHG,FTAG\n"
    "08/08/2026,15:00,Arsenal,Chelsea,2,1\n"
)


class _Resp:
    def __init__(self, status: int, content: bytes = b"", location: str | None = None):
        self.status_code = status
        self.content = content
        self.headers = {"Location": location} if location else {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise fd.requests.exceptions.HTTPError(f"HTTP {self.status_code}")


@pytest.fixture
def cache_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(fd, "CACHE_DIR", tmp_path)
    return tmp_path


def _mock_get(monkeypatch, resp: _Resp):
    calls = {"n": 0}

    def fake_get(url, timeout=None, allow_redirects=True):
        calls["n"] += 1
        calls["allow_redirects"] = allow_redirects
        return resp

    monkeypatch.setattr(fd.requests, "get", fake_get)
    return calls


def test_redirect_hylataan_eika_cachea_kirjoiteta(monkeypatch, cache_dir):
    """301 → EC.csv EI saa tuottaa dataa: puuttuva kausitiedosto = tyhjä."""
    calls = _mock_get(monkeypatch, _Resp(
        301, location="https://www.football-data.co.uk/mmz4281/2627/EC.csv"))
    df = fd.lataa_mainstream("ENG-Premier League", "2627")
    assert df.empty
    assert calls["n"] == 1
    assert calls["allow_redirects"] is False, "redirectiä ei saa seurata"
    assert list(cache_dir.iterdir()) == [], "väärää sisältöä ei saa cacheen"


def test_300_multiple_choices_hylataan(monkeypatch, cache_dir):
    """E1/D1/I1-tyyliset 300-vastaukset (ei Location-headeria) → tyhjä."""
    _mock_get(monkeypatch, _Resp(300))
    df = fd.lataa_mainstream("ENG-Championship", "2627")
    assert df.empty


def test_myrkyttynyt_cache_hylataan_ja_poistetaan(monkeypatch, cache_dir):
    """Levyllä oleva väärän sarjan cache (ennen korjausta ladattu EC-sisältö
    PL-nimellä) hylätään Div-vartijalla ja tiedosto siivotaan pois."""
    poisoned = cache_dir / "ENG_Premier_League_2627.csv"
    poisoned.write_text(EC_CSV, encoding="latin-1")
    calls = _mock_get(monkeypatch, _Resp(500))  # verkkoon ei saa olla tarvetta
    df = fd.lataa_mainstream("ENG-Premier League", "2627")
    assert df.empty
    assert calls["n"] == 0, "cache-osuma — verkkokutsua ei kuulu tehdä"
    assert not poisoned.exists(), "myrkyttynyt cache pitää poistaa"


def test_oikea_tiedosto_lapaisee(monkeypatch, cache_dir):
    """Negatiivinen kontrolli: aito E0-sisältö latautuu kuten ennenkin."""
    _mock_get(monkeypatch, _Resp(200, content=E0_CSV.encode("latin-1")))
    df = fd.lataa_mainstream("ENG-Premier League", "2526")
    assert len(df) == 2
    assert set(df["league"]) == {"ENG-Premier League"}
    assert set(df["home_team"]) == {"Arsenal", "Liverpool"}
    assert (cache_dir / "ENG_Premier_League_2526.csv").exists()


def test_diviton_vanha_formaatti_hyvaksytaan(monkeypatch, cache_dir):
    """Ilman Div-saraketta vartija ei saa laueta (vanhat kausitiedostot)."""
    _mock_get(monkeypatch, _Resp(200, content=DIVITON_CSV.encode("latin-1")))
    df = fd.lataa_mainstream("ENG-Premier League", "2223")
    assert len(df) == 1
