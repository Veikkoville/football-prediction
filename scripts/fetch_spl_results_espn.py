"""
SPL-tulosten haku ESPN:n julkisesta APIsta → vendoroitu CSV.

Saudi Pro League -tulokset DC-priorifittiä varten (SPL-fantasy Phase 0).
FBref/soccerdata EI toimi: FBref palauttaa 403:n kaikilla klienteillä
(curl/cloudscraper/tls_requests, testattu 7.8.2026), eikä soccerdatan
league_dict tunne Saudi-liigaa. football-data.co.uk ei kata Saudi-Arabiaa.
ESPN:n site.api.espn.com sen sijaan tarjoilee ksa.1-scoreboardin ilman
avainta, englanninkielisillä joukkuenimillä ja lopputuloksilla.

Konventio kuten data/international_results.csv (WC-malli): vendoroitu
staattinen snapshot repossa, EI live-pullia tuotantoajossa. Kauden mittaan
uudet tulokset tulevat SPL-fantasy-APIn /api/fixtures/-feedistä (finished-
ottelut skoreineen) — tämä skripti ajetaan vain kun historia-ikkunaa
päivitetään.

Ajo:  python -m scripts.fetch_spl_results_espn
Ulos: data/spl_results.csv (date, season, home_team, away_team,
      home_score, away_score)

Sanity-portit ennen kirjoitusta (fail-safe kuten WC-refresh G2):
  - per kausi täsmälleen 18 joukkuetta
  - per kausi <= 306 ottelua (18 joukkueen kaksinkertainen sarja),
    ja valmiiden osuus raportoidaan
  - ei duplikaatteja (date+home+away)
Portin kaatuessa CSV:tä EI kirjoiteta, exit 2.
"""

from __future__ import annotations

import csv
import sys
import time
from pathlib import Path

# ESPN 403:aa sekä python-requestsin että tls_requestsin (testattu 7.8.2026,
# molemmat selain-UA:lla) — mutta curl samaan URLiin saa aina 200. Ero on
# klientin sormenjäljessä (curl täällä HTTP/1.1-only). Kertaluonteiselle
# vendorointihaulle subprocess-curl on toistettavin reitti; curl.exe kuuluu
# Windows 10+:aan ja kaikkiin CI-imageihin.
import json as _json
import subprocess

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config

ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer/ksa.1/scoreboard"
OUT_PATH = config.PROJECT_ROOT / "data" / "spl_results.csv"

# Kaudet ja niiden ESPN-slugit (season.slug event-payloadissa) — slugilla
# suodatetaan pois mahdolliset muut kilpailut samalta scoreboard-päivältä.
SEASONS = {
    "2425": ("2024-25-saudi-pro-league", ["2024-08", "2025-06"]),
    "2526": ("2025-26-saudi-pro-league", ["2025-08", "2026-06"]),
}


def _month_ranges(first: str, last: str) -> list[str]:
    """['2024-08', '2025-06'] → ['20240801-20240831', ..., '20250601-20250630']."""
    y, m = (int(x) for x in first.split("-"))
    ly, lm = (int(x) for x in last.split("-"))
    out = []
    while (y, m) <= (ly, lm):
        # 31 kelpaa aina ylärajaksi: ESPN tulkitsee rangen päivämäärärajauksena
        out.append(f"{y}{m:02d}01-{y}{m:02d}31")
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def fetch_season(tunnus: str, slug: str, ikkuna: list[str]) -> list[dict]:
    rivit = []
    nahdyt: set[str] = set()  # "01-31" päivävälin ylivuoto duplikoi kuunvaihteen
    for rng in _month_ranges(*ikkuna):
        p = subprocess.run(
            ["curl", "-s", "--max-time", "60", "--retry", "4",
             "--retry-all-errors", "--retry-delay", "2", "--compressed",
             f"{ESPN_BASE}?dates={rng}&limit=400"],
            capture_output=True, timeout=300,
        )
        if p.returncode != 0 or not p.stdout:
            raise RuntimeError(f"curl epäonnistui ({rng}): rc={p.returncode}")
        data = _json.loads(p.stdout)
        for e in data.get("events", []):
            if (e.get("season") or {}).get("slug") != slug:
                continue
            if e["id"] in nahdyt:
                continue
            nahdyt.add(e["id"])
            st = ((e.get("status") or {}).get("type") or {})
            if not st.get("completed"):
                continue
            comp = e["competitions"][0]
            koti = viesas = None
            for c in comp["competitors"]:
                if c["homeAway"] == "home":
                    koti = c
                elif c["homeAway"] == "away":
                    viesas = c
            if not koti or not viesas:
                continue
            rivit.append({
                "date": e["date"][:10],
                "season": tunnus,
                "home_team": koti["team"]["displayName"],
                "away_team": viesas["team"]["displayName"],
                "home_score": int(koti["score"]),
                "away_score": int(viesas["score"]),
            })
        time.sleep(0.5)  # kohtelias tahti, ~22 kutsua yhteensä
    return rivit


def main() -> int:
    kaikki: list[dict] = []
    for tunnus, (slug, ikkuna) in SEASONS.items():
        rivit = fetch_season(tunnus, slug, ikkuna)
        joukkueet = {r["home_team"] for r in rivit} | {r["away_team"] for r in rivit}
        print(f"{tunnus}: {len(rivit)} valmista ottelua, {len(joukkueet)} joukkuetta")
        if len(joukkueet) != 18:
            print(f"SANITY FAIL: {tunnus} joukkuemäärä {len(joukkueet)} != 18 — CSV:tä ei kirjoiteta")
            for j in sorted(joukkueet):
                print("  ", j)
            return 2
        if len(rivit) > 306:
            print(f"SANITY FAIL: {tunnus} ottelumäärä {len(rivit)} > 306 — CSV:tä ei kirjoiteta")
            return 2
        kaikki.extend(rivit)

    avaimet = [(r["date"], r["home_team"], r["away_team"]) for r in kaikki]
    if len(avaimet) != len(set(avaimet)):
        print("SANITY FAIL: duplikaattiotteluita — CSV:tä ei kirjoiteta")
        return 2

    kaikki.sort(key=lambda r: (r["season"], r["date"], r["home_team"]))
    with open(OUT_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=[
            "date", "season", "home_team", "away_team", "home_score", "away_score",
        ])
        w.writeheader()
        w.writerows(kaikki)
    print(f"OK: {len(kaikki)} ottelua → {OUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
