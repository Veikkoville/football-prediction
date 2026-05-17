"""
Diagnoosiskripti: mitä WC-dataa football-data.org tarjoaa free-tierissä?

Aja:
  cd C:\\Users\\vvsaa\\Documents\\football-prediction
  python scripts/test_wc_data.py

Tulos kertoo:
  1. Mitä WC-vuosia API tarjoaa
  2. Kuinka monta ottelua per vuosi (FINISHED, SCHEDULED, IN_PLAY)
  3. Esimerkkiottelut
  4. Joukkueet WC 2026:ssa (jos saatavilla)

Tämän perusteella päätämme strategian: käytetäänkö WC-historiadataa
suoraan DC-koulutukseen vai tarvitaanko fusion (WC + kvalifioinnit +
Nations League).
"""

from __future__ import annotations
import os
import sys
from pathlib import Path

# Lisää projektin juuri Python-polkuun
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import requests

# Lue avain ENV:stä tai .env-tiedostosta — älä koskaan hardcoodaa fallbackia.
# Aiempi hardcoded-arvo vuoti DEPLOY.md:hen ja julkiseen GitHub-repoon (16.5.2026).
# Vaihdettu env-only-lukuun 17.5.2026.
def _load_api_key() -> str | None:
    key = os.environ.get("FOOTBALL_DATA_API_KEY")
    if key:
        return key.strip()
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line.startswith("FOOTBALL_DATA_API_KEY"):
                _, _, v = line.partition("=")
                return v.strip().strip('"\'')
    return None


API_KEY = _load_api_key()
BASE = "https://api.football-data.org/v4"
HEADERS = {"X-Auth-Token": API_KEY or ""}


def check_year(year: int):
    """Hae yhden vuoden WC-data ja raportoi."""
    url = f"{BASE}/competitions/WC/matches?season={year}"
    print(f"\n=== WC season {year} ===")
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code == 403:
            print(f"  HTTP 403: ei pääsyä tähän vuoteen (free tier rajoitus)")
            return
        if r.status_code != 200:
            print(f"  HTTP {r.status_code}: {r.text[:200]}")
            return
        data = r.json()
        matches = data.get("matches", [])
        print(f"  Total matches: {len(matches)}")
        if not matches:
            return

        # Statukset
        statuses = {}
        for m in matches:
            s = m.get("status", "?")
            statuses[s] = statuses.get(s, 0) + 1
        print(f"  By status: {statuses}")

        # 3 esimerkkiottelua
        print(f"  Example matches:")
        for m in matches[:3]:
            home = (m.get("homeTeam") or {}).get("name", "?")
            away = (m.get("awayTeam") or {}).get("name", "?")
            score = m.get("score", {}).get("fullTime", {})
            h, a = score.get("home"), score.get("away")
            score_str = f"{h}-{a}" if h is not None else "vs"
            date = m.get("utcDate", "?")[:10]
            print(f"    {date}: {home} {score_str} {away} [{m.get('status')}]")

    except Exception as e:
        print(f"  ERROR: {type(e).__name__}: {e}")


def check_teams_in_wc(year: int):
    """Hae WC-joukkueet."""
    url = f"{BASE}/competitions/WC/teams?season={year}"
    print(f"\n=== WC {year} teams ===")
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            print(f"  HTTP {r.status_code}: {r.text[:200]}")
            return
        data = r.json()
        teams = data.get("teams", [])
        print(f"  Total teams: {len(teams)}")
        if teams:
            print(f"  First 10:")
            for t in teams[:10]:
                print(f"    - {t.get('name')} (id: {t.get('id')})")
    except Exception as e:
        print(f"  ERROR: {type(e).__name__}: {e}")


def main():
    if not API_KEY:
        print("FOOTBALL_DATA_API_KEY puuttuu — tarkista .env")
        sys.exit(1)

    print(f"Käytetään API-avainta: {API_KEY[:8]}...{API_KEY[-4:]}")
    print(f"Endpoint: {BASE}")

    # Testaa useita vuosia
    for year in [2018, 2022, 2026]:
        check_year(year)

    # Testaa joukkueet
    check_teams_in_wc(2026)
    check_teams_in_wc(2022)

    print("\n=== Suositus ===")
    print("Jos WC 2026:lla on SCHEDULED-otteluita + joukkuelista → ennustus mahdollista")
    print("Jos WC 2022:lla on FINISHED-otteluita → mallin koulutus mahdollista")
    print("Jos kumpikin: → MMP-toteutus suoraviivainen 1-2 päivässä")


if __name__ == "__main__":
    main()
