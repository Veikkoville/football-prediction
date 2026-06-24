"""#103 — track-record-gap backfill: 8 MD2-lohko-ottelua (22.–24.6.2026).

TAUSTA
------
Seed (cmd_seed, scripts/accuracy_pipeline.py) parsii VAIN WC-hubin track-record-
taulun (rivit joilla on JO tulos). Hub julkaistiin 22.6 (commit d5a86ad) → taulu
kattoi 40 ottelua, viimeinen reconciloitu = New Zealand–Egypt (seed-039).

Samaan hub-HTML:ään sisältyy "Upcoming: Matchday 3 & remaining group games"
-osio, jossa on 32 ottelun GENUINE pre-match-jakaumat (Home/Draw/Away%),
JÄÄDYTETTY 22.6 ennen kickoffeja. 8 näistä pelattiin 22.–24.6 mutta jäivät pois
recordista, koska:
  - track-record-taulussa ei vielä ollut niiden tulosta seed-hetkellä, JA
  - accuracy-log.yml (pilvi-workflow) aktivoituu vasta 24.6 ja nappaa vain
    TULEVAT (kickoff > now) ottelut → jo pelatut eivät tule mukaan.

INTEGRITEETTI
-------------
Pre-match-pick + win% otetaan hub-upcoming-osiosta (aito, julkaistu pre-match,
ei mallin jälkiajoa — täyttää #103-vaatimuksen). FT-tulos haetaan football-
data.org:sta (sama lähde kuin reconcile). EI kutsuta wc_prematch_prediction()
— mallia EI ajeta jälkikäteen.

MUOTO
-----
Tallennetaan SAMASSA muodossa kuin 40 seed-riviä: vain voittajan p (p_draw=None,
häviäjän p=None) → rivit pysyvät 1X2/decisive-metriikassa mutta pois Brier/
kalibraatiosta, identtisesti seed-kohortin kanssa (ei harhaanjohtavaa 8-rivin
täysjakauma-osajoukkoa). predicted_winner = hub-suosikki (argmax, korostettu rivi).

EI auto-pushia — Ville pushaa (CLAUDE.md / accuracy_pipeline-konventio).

Aja:  .venv/Scripts/python.exe -m scripts.backfill_md2_gap
"""

from __future__ import annotations

import re
import sys
import urllib.request
import json
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.models import accuracy as acc

# Hub-upcoming-osion GENUINE pre-match-pickit (world-cup-2026-predictions.html,
# commit d5a86ad, 22.6.2026). (home, away, p_home%, p_draw%, p_away%).
HUB_UPCOMING = [
    ("Argentina", "Austria",     65.4, 23.3, 11.3),
    ("France",    "Iraq",        79.2, 15.3,  5.4),
    ("Norway",    "Senegal",     47.5, 28.4, 24.1),
    ("Jordan",    "Algeria",     27.4, 29.1, 43.6),
    ("Portugal",  "Uzbekistan",  70.3, 20.6,  9.1),
    ("England",   "Ghana",       82.6, 13.2,  4.2),
    ("Panama",    "Croatia",     14.9, 24.2, 61.0),
    ("Colombia",  "Congo DR",    72.7, 19.9,  7.4),
]


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def _fd_finished_by_pair() -> dict:
    """Hae WC-FINISHED-ottelut FD:stä → {(home,away): (date, hs, as_)}."""
    key = re.search(
        r"FOOTBALL_DATA_API_KEY\s*=\s*(\S+)", (ROOT / ".env").read_text()
    ).group(1).strip()
    url = "https://api.football-data.org/v4/competitions/WC/matches?season=2026"
    req = urllib.request.Request(url, headers={"X-Auth-Token": key})
    matches = json.load(urllib.request.urlopen(req, timeout=25))["matches"]
    out = {}
    for m in matches:
        if m.get("status") != "FINISHED":
            continue
        h = (m.get("homeTeam") or {}).get("name")
        a = (m.get("awayTeam") or {}).get("name")
        ft = (m.get("score") or {}).get("fullTime") or {}
        if h and a and ft.get("home") is not None:
            out[(h, a)] = (m["utcDate"][:10], int(ft["home"]), int(ft["away"]))
    return out


def main() -> int:
    log = acc.load_log()
    fd = _fd_finished_by_pair()

    added = 0
    for home, away, ph, pd_, pa in HUB_UPCOMING:
        res = fd.get((home, away)) or fd.get((away, home))
        if res is None:
            print(f"OHITUS: {home}–{away} ei FD-FINISHED-tulosta — jätetään gap.")
            continue
        date, hs, as_ = res
        # voittaja = hub-suosikki (argmax). draw-suosikkia ei näillä 8:lla esiinny.
        if ph >= pa and ph >= pd_:
            winner, p_home, p_away = "home", round(ph / 100.0, 4), None
        elif pa >= ph and pa >= pd_:
            winner, p_home, p_away = "away", None, round(pa / 100.0, 4)
        else:
            print(f"OHITUS: {home}–{away} suosikki = draw — ei seed-yhteensopiva.")
            continue
        entry = {
            "match_id": f"hubup-{_slug(home)}-{_slug(away)}",
            "source": "wc_hub_upcoming_backfill",
            "competition": "WC",
            "date": date,
            "home_team": home,
            "away_team": away,
            "p_home": p_home,
            "p_draw": None,
            "p_away": p_away,
            "xg_home": None,
            "xg_away": None,
            "most_likely_score": None,
            "predicted_winner": winner,
            "logged_at": None,
            "result": None,
        }
        if acc.upsert_prediction(log, entry):
            acc.set_result(log, entry["match_id"], hs, as_)
            added += 1
            print(f"BACKFILL: {home} {hs}-{as_} {away} | pick={winner} → "
                  f"{'HIT' if log['predictions'][-1]['result']['hit_1x2'] else 'MISS'}")

    acc.save_log(log)
    agg = acc.recompute_and_save(log)
    at = agg["all_time"]
    print(f"\nLISÄTTY: {added} riviä. Logissa nyt {len(log['predictions'])}.")
    print(f"AGG: n={at['n']} | 1X2 {at['pct_1x2']} ({at['correct_1x2']}/{at['n']}) | "
          f"decisive {at['pct_decisive']} ({at['decisive_correct']}/{at['decisive_n']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
