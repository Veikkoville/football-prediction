"""
SofaScore — live-otteluseuranta.

SofaScorella ei ole virallista avointa APIa, ja `soccerdata` käyttää
epävirallista reittiä. Käytä **vain henkilökohtaiseen kokeiluun** ja
älä pommita palvelinta — pidä kysely-väli rauhallisena (>= 30 s).

Tässä moduulissa on kaksi reittiä:
  1. `soccerdata.Sofascore` (helppo, mutta riippuvainen kirjaston ylläpidosta)
  2. Suora HTTP-pyyntö julkiselle "api/v1/sport/football/events/live" -reitille
     (yksinkertaisempi vaihtoehto live-tilanteen pollaukseen)
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Iterable

import pandas as pd
import requests

# Useita HTTP-clienteja — SofaScoren Cloudflare-suojaus on aggressiivinen
# joten kokeillaan eri lahestymistavoilla peratysti.

# 1. tls_requests: kiertaa TLS-fingerprint-tunnistuksen. Tehokkain Cloudflarea
#    vastaan. Asennettu soccerdatan riippuvuutena.
try:
    import tls_requests as _tls_req
    _TLS_CLIENT = _tls_req.Client()
except Exception:
    _TLS_CLIENT = None

# 2. cloudscraper: ratkaisee Cloudflaren JavaScript-haasteet
try:
    import cloudscraper
    _SCRAPER = cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "windows", "mobile": False}
    )
except ImportError:
    _SCRAPER = None


# ---------------------------------------------------------------------------
# Vaihtoehto 1: soccerdata-kirjasto
# ---------------------------------------------------------------------------
def lataa_otteludata(
    leagues: Iterable[str],
    seasons: Iterable[str],
    cache_dir: Path | None = None,
) -> pd.DataFrame:
    """Hae menneitä otteluita SofaScoresta soccerdatan kautta."""
    import soccerdata as sd

    ss = sd.Sofascore(
        leagues=list(leagues),
        seasons=list(seasons),
        data_dir=cache_dir,
    )
    return ss.read_schedule().reset_index()


# ---------------------------------------------------------------------------
# Vaihtoehto 2: Live-pollaus suoraan HTTP:llä
# ---------------------------------------------------------------------------
LIVE_URL = "https://api.sofascore.com/api/v1/sport/football/events/live"

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9,fi;q=0.8",
    "Referer": "https://www.sofascore.com/",
    "Origin": "https://www.sofascore.com",
    "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124", "Not.A/Brand";v="99"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
}


def _hae(url: str, timeout: int = 10):
    """
    Yhteinen GET-funktio. Kokeilee jarjestyksessa:
      1) tls_requests (TLS-fingerprint -kierto, tehokkain Cloudflaren ohitus)
      2) cloudscraper (JavaScript-haasteen ratkaisu)
      3) vanilla requests (epatodennakoinen, mutta varmuuden vuoksi)
    """
    virheet = []

    # 1. tls_requests
    if _TLS_CLIENT is not None:
        try:
            r = _TLS_CLIENT.get(url, headers=DEFAULT_HEADERS, timeout=timeout)
            if r.status_code == 200:
                return r
            virheet.append(f"tls_requests: HTTP {r.status_code}")
        except Exception as e:
            virheet.append(f"tls_requests: {type(e).__name__}: {e}")

    # 2. cloudscraper
    if _SCRAPER is not None:
        try:
            r = _SCRAPER.get(url, headers=DEFAULT_HEADERS, timeout=timeout)
            if r.status_code == 200:
                return r
            virheet.append(f"cloudscraper: HTTP {r.status_code}")
        except Exception as e:
            virheet.append(f"cloudscraper: {type(e).__name__}: {e}")

    # 3. vanilla requests
    try:
        r = requests.get(url, headers=DEFAULT_HEADERS, timeout=timeout)
        if r.status_code == 200:
            return r
        virheet.append(f"requests: HTTP {r.status_code}")
    except Exception as e:
        virheet.append(f"requests: {type(e).__name__}: {e}")

    raise RuntimeError(
        "Kaikki HTTP-clientit epaonnistuivat:\n  - " + "\n  - ".join(virheet)
    )


def hae_live_ottelut(timeout: int = 10) -> list[dict]:
    """
    Hae kaikki tällä hetkellä käynnissä olevat jalkapallo-ottelut.

    Palauttaa listan dict-objekteja, joissa mm. ottelun id, joukkueet,
    tilanne (status), tulos, minuutti.

    Esimerkki:
        >>> ottelut = hae_live_ottelut()
        >>> for o in ottelut[:3]:
        ...     print(o["homeTeam"]["name"], o["awayScore"]["display"])
    """
    r = _hae(LIVE_URL, timeout=timeout)
    data = r.json()
    return data.get("events", [])


def parsi_live_ottelut(events: list[dict]) -> pd.DataFrame:
    """Muunna `hae_live_ottelut`-tuotos siistiksi DataFrameksi."""
    rivit = []
    for e in events:
        rivit.append({
            "match_id": e.get("id"),
            "tournament": (e.get("tournament") or {}).get("name"),
            "country": ((e.get("tournament") or {}).get("category") or {}).get("name"),
            "home_team": (e.get("homeTeam") or {}).get("name"),
            "away_team": (e.get("awayTeam") or {}).get("name"),
            "home_score": (e.get("homeScore") or {}).get("display"),
            "away_score": (e.get("awayScore") or {}).get("display"),
            "status": (e.get("status") or {}).get("description"),
            "minute": ((e.get("time") or {}).get("currentPeriodStartTimestamp")),
            "start_time": e.get("startTimestamp"),
        })
    return pd.DataFrame(rivit)


def hae_ottelun_tilastot(match_id: int, timeout: int = 10) -> dict:
    """
    Hae yhden ottelun live-tilastot (laukaukset, kulmat, kortit, hallinta).

    Palauttaa raaka JSON-vastauksen — siisti tarpeen mukaan.
    """
    url = f"https://api.sofascore.com/api/v1/event/{match_id}/statistics"
    r = _hae(url, timeout=timeout)
    return r.json()


# ---------------------------------------------------------------------------
# Pollaus-iteraattori
# ---------------------------------------------------------------------------
def pollaa_live(interval_sekuntia: int = 60, kierroksia: int | None = None):
    """
    Generaattori joka palauttaa live-ottelut DataFramena tasaisin väliajoin.

    Esimerkki notebookissa::

        from src.data.sofascore import pollaa_live
        for snapshot in pollaa_live(interval_sekuntia=60, kierroksia=5):
            display(snapshot.head())

    Parametrit
    ----------
    interval_sekuntia : int
        Kuinka pitkä tauko kahden pyynnön välillä. **Älä laita alle 30**,
        muuten saatat saada blokin.
    kierroksia : int | None
        Kuinka monta kertaa pollataan. ``None`` = ikuisesti
        (keskeytä Ctrl+C).
    """
    if interval_sekuntia < 30:
        raise ValueError(
            "Liian tiheä pollaus — käytä vähintään 30 sekunnin väliä."
        )
    n = 0
    while kierroksia is None or n < kierroksia:
        events = hae_live_ottelut()
        yield parsi_live_ottelut(events)
        n += 1
        if kierroksia is None or n < kierroksia:
            time.sleep(interval_sekuntia)
