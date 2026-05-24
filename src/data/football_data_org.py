"""
football-data.org API -loader UEFA-turnauksille.

Vaatii ilmaisen API-avaimen rekisterointi:
  https://www.football-data.org/client/register

API-avain tallennetaan projektin juuressa olevaan .env-tiedostoon:
  FOOTBALL_DATA_API_KEY=oma_avaimesi

Ilmaisen tier:n rajat:
  - 10 pyyntoa minuutissa
  - Edellinen + nykyinen kausi
  - Mukana mm. Champions League, Europa League, Conference League, Top-5
"""

from __future__ import annotations
import os
import threading
from datetime import datetime
from pathlib import Path
import json
import time
import pandas as pd
import requests

import config

CACHE_DIR = config.RAW_DATA_DIR / "football-data-org"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# #69: Käynnissä olevien turnausten datalle (esim. WC 2026) tarvitaan
# uudelleenhakua jotta uudet joukkueet + tulokset päivittyvät malliin
# turnauksen edetessä. Levypohjainen cache on Renderillä efemeerinen ja
# muuttumaton instanssin elinkaaren aikana → in-memory TTL-cache vain
# turnauskoodeille jonka kausi vastaa kuluvaa vuotta. Domestic-liigat
# ja menneet turnauskaudet (WC 2018, 2022) säilyttävät levycachen
# pysyvänä (niiden data ei muutu).
TOURNAMENT_TTL_SEC = 6 * 3600  # 6 h
_LIVE_TOURNAMENT_CODES = {"WC", "EC"}
_TOURNAMENT_MEM_CACHE: dict[tuple[str, str], tuple[float, dict]] = {}

# #71: rate-limit aikaleima — sleep vain peräkkäisten API-kutsujen välissä,
# ei cache-hitillä. Aiempi `time.sleep(7)` ehdoton-per-kausi `lataa()`-tasolla
# nielei 14 s joka kutsussa myös kun data tuli levyltä. football-data.org
# rajoittaa 10 pyyntöä/min → 6.5 s väli antaa varmuusmarginaalin.
#
# Lukko on välttämätön: warmup-daemon-thread (api/main.py) ja FastAPIn
# pyyntö-säikeet voivat osua _await_rate_limit:iin yhtä aikaa. Ilman lukkoa
# read+sleep+write ei ole atominen → kaksi säiettä voi lukea saman
# aikaleiman, molemmat sleeppaa lyhyemmin kuin tulisi → 10/min raja rikkoutuu
# ja kohdataan HTTP 429.
_FDORG_MIN_INTERVAL_SEC = 6.5
_FDORG_LAST_CALL_AT: list[float] = [0.0]
_FDORG_RATE_LIMIT_LOCK = threading.Lock()


def _await_rate_limit() -> None:
    """Odota tarvittaessa jotta edellisestä API-kutsusta on >= 6.5 s.

    Lukon alla luettu + sleepattu + päivitetty atomisesti, jotta rinnakkaiset
    säikeet eivät pääse rikkomaan 10/min rate-limitiä (#71).
    """
    with _FDORG_RATE_LIMIT_LOCK:
        elapsed = time.time() - _FDORG_LAST_CALL_AT[0]
        if 0 < elapsed < _FDORG_MIN_INTERVAL_SEC:
            time.sleep(_FDORG_MIN_INTERVAL_SEC - elapsed)
        _FDORG_LAST_CALL_AT[0] = time.time()

# Liiga -> football-data.org -kilpailukoodi
COMPETITION_CODES = {
    "INT-Champions League": "CL",
    "INT-Europa League": "EL",
    "INT-Conference League": "ECL",
    "INT-European Championship": "EC",
    "INT-World Cup": "WC",
    "ENG-Premier League-FD": "PL",   # vaihtoehto Understat-Top-5:lle (esim. testiin)
    "GER-Bundesliga-FD": "BL1",
    "ESP-La Liga-FD": "PD",
    "ITA-Serie A-FD": "SA",
    "FRA-Ligue 1-FD": "FL1",
}

BASE = "https://api.football-data.org/v4"


def _api_key() -> str | None:
    """
    Hae API-avain. Etsintajärjestys:
      1. Ymparistomuuttuja FOOTBALL_DATA_API_KEY (toimii kaikkialla)
      2. .env-tiedosto projektin juuressa (lokaalit kehitykseen)
      3. Streamlit secrets st.secrets["FOOTBALL_DATA_API_KEY"] (Streamlit Cloud)
    """
    # 1. Ymparistomuuttuja
    key = os.environ.get("FOOTBALL_DATA_API_KEY")
    if key:
        return key.strip()
    # 2. .env-tiedosto projektin juuressa
    env_path = config.PROJECT_ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line.startswith("FOOTBALL_DATA_API_KEY"):
                _, _, v = line.partition("=")
                return v.strip().strip('"\'')
    # 3. Streamlit secrets (vain pilvessa)
    try:
        import streamlit as st
        v = st.secrets.get("FOOTBALL_DATA_API_KEY")
        if v:
            return str(v).strip()
    except Exception:
        pass
    return None


# Free tier kilpailut — nama toimivat ilmaisella avaimella
FREE_TIER = {"CL", "PL", "BL1", "PD", "FL1", "SA", "ELC", "DED",
             "PPL", "EC", "WC", "BSA", "CLI"}


def _is_live_tournament(code: str, kausi: str) -> bool:
    """True jos koodi on käynnissä-oleva turnaus ja kausi-vuosi == kuluva vuosi."""
    if code not in _LIVE_TOURNAMENT_CODES:
        return False
    try:
        year = int(kausi)
    except (TypeError, ValueError):
        return False
    return year == datetime.utcnow().year


def tournament_last_refresh() -> float:
    """#69: paras (uusin) muistissa-olevan turnausdatan haku-aikaleima."""
    if not _TOURNAMENT_MEM_CACHE:
        return 0.0
    return max(ts for ts, _ in _TOURNAMENT_MEM_CACHE.values())


def _fetch_from_api(code: str, kausi: str, api_key: str) -> dict:
    if code not in FREE_TIER:
        return {"_error": (
            f"Kilpailu {code} ei sisally ilmaiseen tier:iin. "
            f"Tier One -tilaus (€10/kk) avaa Europa Leaguen ja Conference Leaguen."
        )}
    _await_rate_limit()
    url = f"{BASE}/competitions/{code}/matches?season={kausi}"
    headers = {"X-Auth-Token": api_key}
    try:
        r = requests.get(url, headers=headers, timeout=20)
        if r.status_code == 429:
            time.sleep(8)
            with _FDORG_RATE_LIMIT_LOCK:
                _FDORG_LAST_CALL_AT[0] = time.time()
            r = requests.get(url, headers=headers, timeout=20)
        if r.status_code == 403:
            return {"_error": (
                "HTTP 403: API-avain ei salli tata kilpailua. "
                "Tarkista tilaustasi football-data.org:ssa."
            )}
        if r.status_code != 200:
            return {"_error": f"HTTP {r.status_code}: {r.text[:200]}"}
        return r.json()
    except Exception as e:
        return {"_error": f"{type(e).__name__}: {e}"}


def _hae_kausi(code: str, kausi: str, api_key: str) -> dict | None:
    cache = CACHE_DIR / f"{code}_{kausi}.json"

    if _is_live_tournament(code, kausi):
        now = time.time()
        entry = _TOURNAMENT_MEM_CACHE.get((code, kausi))
        if entry and (now - entry[0]) < TOURNAMENT_TTL_SEC:
            return entry[1]
        data = _fetch_from_api(code, kausi, api_key)
        if isinstance(data, dict) and "_error" not in data:
            _TOURNAMENT_MEM_CACHE[(code, kausi)] = (now, data)
            try:
                cache.write_text(json.dumps(data), encoding="utf-8")
            except Exception:
                pass
            return data
        # API epäonnistui → levyfallback → vanha muistissa-oleva → virhe
        if cache.exists() and cache.stat().st_size > 100:
            try:
                return json.loads(cache.read_text(encoding="utf-8"))
            except Exception:
                pass
        if entry:
            return entry[1]
        return data

    # Ei-live (domestic-liigat, menneet turnauskaudet) — levycache pysyvä.
    if cache.exists() and cache.stat().st_size > 100:
        try:
            return json.loads(cache.read_text(encoding="utf-8"))
        except Exception:
            pass
    data = _fetch_from_api(code, kausi, api_key)
    if isinstance(data, dict) and "_error" not in data:
        try:
            cache.write_text(json.dumps(data), encoding="utf-8")
        except Exception:
            pass
    return data


def _kausi_to_year(kausi: str) -> str:
    """'2425' -> '2024' (alkuvuosi)."""
    if len(kausi) == 4:
        return "20" + kausi[:2]
    if len(kausi) == 2:
        return "20" + kausi
    return kausi


def _parse_matches(data: dict, liiga: str, kausi: str) -> pd.DataFrame:
    """Muunna API:n vastaus DataFrameksi."""
    if not data or "matches" not in data:
        return pd.DataFrame()
    rivit = []
    for m in data["matches"]:
        if m.get("status") != "FINISHED":
            continue
        score = m.get("score", {}).get("fullTime", {})
        h = score.get("home")
        a = score.get("away")
        if h is None or a is None:
            continue
        # Pakota tz-naive (poista UTC-merkinta) yhteneva muu data
        d = pd.to_datetime(m.get("utcDate"), errors="coerce", utc=True)
        if pd.notna(d):
            d = d.tz_convert("UTC").tz_localize(None)
        rivit.append({
            "date": d,
            "home_team": (m.get("homeTeam") or {}).get("name", "?"),
            "away_team": (m.get("awayTeam") or {}).get("name", "?"),
            "home_score": int(h), "away_score": int(a),
            "league": liiga, "season": kausi,
            "home_xg": pd.NA, "away_xg": pd.NA,
            "lahde": "football-data.org",
        })
    if not rivit:
        return pd.DataFrame()
    return pd.DataFrame(rivit).dropna(subset=["date"])


def lataa(liiga: str, kaudet: list[str]) -> pd.DataFrame:
    api_key = _api_key()
    if not api_key:
        return pd.DataFrame()
    if liiga not in COMPETITION_CODES:
        return pd.DataFrame()
    code = COMPETITION_CODES[liiga]
    palaset = []
    for k in kaudet:
        year = _kausi_to_year(k)
        # #71: rate-limit-sleep on siirretty _fetch_from_api:n alkuun
        # (_await_rate_limit). Cache-hit ei enää aiheuta sleeppejä.
        data = _hae_kausi(code, year, api_key)
        if data and "_error" not in data:
            df = _parse_matches(data, liiga, k)
            if not df.empty:
                palaset.append(df)
    return pd.concat(palaset, ignore_index=True) if palaset else pd.DataFrame()


def api_key_kunnossa() -> bool:
    return _api_key() is not None


def tuetut_liigat() -> list[str]:
    return sorted(COMPETITION_CODES.keys())
