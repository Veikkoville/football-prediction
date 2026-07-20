"""PL-seura -> MM-2026-kuormituskartta (#142 OSA A).

Kaikki 48 maata: FD-squadit (26 pelaajaa/maa) -> FPL bootstrap-static
-nimimatchaus -> per PL-seura: WC-pelaajat + otteluexposure + syvin vaihe.

REHELLISYYSHUOMIO (raportoitava aina tuotoksen mukana): per-pelaaja-
TURNAUSMINUUTTEJA ei ole ohjelmallisesti saatavilla ilmaisista lahteista
(FD-tier ei anna lineups/subs WC:lle; FotMob-API bot-blokattu) -> tama
kartta kayttaa promptin fallbackia "otteluiden lkm x vaihe":
exposure = sum(pelaajan maan FINISHED-ottelut). Se YLIARVIOI penkkipelaajien
kuorman (Crystal Palace -opetus: painota minuutteja, ala paalukua) ->
kerroinmitoitus tehdaan konservatiivisesti ja ristiintarkistetaan CoS:n
selaimella keraamaan 8 maan minuuttikartoitukseen (prompti par.4).

FPL bootstrap on ajanhetken totuus (pre-flip = 25/26-rosterit; siirtoikkuna
muuttaa seuroja) -> aja uudelleen ~15.8 ennen GW1:ta.

Ajo:  python -m scripts.build_wc2026_club_load
Ulos: data/wc2026_club_load.csv (gitignored, kuten muut data-artefaktit)
"""
from __future__ import annotations

import csv
import sys
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402
from scripts.accuracy_pipeline import _fetch_wc_matches  # noqa: E402
from scripts.build_fpl_phase0 import map_name  # noqa: E402
from src.data.football_data_org import BASE, _api_key, _await_rate_limit  # noqa: E402

OUT_PATH = config.DATA_DIR / "wc2026_club_load.csv"

STAGE_ORDER = [
    "GROUP_STAGE", "LAST_32", "LAST_16", "QUARTER_FINALS",
    "SEMI_FINALS", "THIRD_PLACE", "FINAL",
]


def _norm(s: str) -> str:
    """Aksentiton lowercase-avain nimimatchaukseen."""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(s.lower().replace("-", " ").replace(".", " ").split())


def fetch_wc_squads() -> list[dict]:
    api_key = _api_key()
    if not api_key:
        raise SystemExit("FOOTBALL_DATA_API_KEY puuttuu")
    _await_rate_limit()
    r = requests.get(
        f"{BASE}/competitions/WC/teams?season=2026",
        headers={"X-Auth-Token": api_key},
        timeout=30,
    )
    r.raise_for_status()
    return r.json().get("teams", [])


def country_loads(matches: list[dict]) -> tuple[dict, dict]:
    """Maa -> (FINISHED-ottelumaara, syvin vaihe)."""
    played: dict[str, int] = defaultdict(int)
    deepest: dict[str, int] = defaultdict(int)
    for m in matches:
        if m.get("status") != "FINISHED":
            continue
        stage_i = STAGE_ORDER.index(m.get("stage")) if m.get("stage") in STAGE_ORDER else 0
        for side in ("homeTeam", "awayTeam"):
            name = (m.get(side) or {}).get("name")
            if not name:
                continue
            played[name] += 1
            deepest[name] = max(deepest[name], stage_i)
    return dict(played), dict(deepest)


def fetch_fpl_players() -> tuple[list[dict], dict[int, str]]:
    r = requests.get(
        "https://fantasy.premierleague.com/api/bootstrap-static/", timeout=30,
        headers={"User-Agent": "Mozilla/5.0"},
    )
    r.raise_for_status()
    d = r.json()
    teams = {t["id"]: t["name"] for t in d["teams"]}
    return d["elements"], teams


def main() -> int:
    fetched_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    matches = _fetch_wc_matches()
    if matches is None:
        raise SystemExit("FD-ottelut ei saatavilla")
    played, deepest = country_loads(matches)
    squads = fetch_wc_squads()
    elements, fpl_teams = fetch_fpl_players()

    # FPL-indeksi: normalisoitu koko nimi + web_name -> pelaaja
    by_full: dict[str, list[dict]] = defaultdict(list)
    by_last: dict[str, list[dict]] = defaultdict(list)
    for e in elements:
        full = _norm(f"{e['first_name']} {e['second_name']}")
        by_full[full].append(e)
        toks = _norm(e["second_name"]).split()
        if toks:
            by_last[toks[-1]].append(e)

    rows = []          # (country, player, club, country_matches, stage)
    ambiguous = []
    n_wc_players = 0
    for team in squads:
        country = team.get("name")
        n_matches = played.get(country, 0)
        stage_i = deepest.get(country, 0)
        for p in team.get("squad") or []:
            n_wc_players += 1
            pname = _norm(p.get("name") or "")
            if not pname:
                continue
            cands = by_full.get(pname, [])
            if not cands:
                # token-osajoukko: FD "Bruno Fernandes" vs FPL koko nimi
                toks = set(pname.split())
                last = pname.split()[-1]
                cands = [
                    e for e in by_last.get(last, [])
                    if toks <= set(_norm(f"{e['first_name']} {e['second_name']}").split())
                    or set(_norm(f"{e['first_name']} {e['second_name']}").split()) <= toks
                ]
            if len(cands) > 1:
                ambiguous.append((country, p.get("name"),
                                  [f"{e['first_name']} {e['second_name']}" for e in cands]))
                continue
            if len(cands) == 1:
                e = cands[0]
                club = map_name(fpl_teams[e["team"]])
                rows.append({
                    "country": country,
                    "player": p.get("name"),
                    "club": club,
                    "country_matches": n_matches,
                    "deepest_stage": STAGE_ORDER[stage_i],
                    "stage_i": stage_i,
                })

    # Aggregoi seuroittain
    clubs: dict[str, dict] = {}
    for r_ in rows:
        c = clubs.setdefault(r_["club"], {
            "club": r_["club"], "players": 0, "match_exposure": 0,
            "deepest_stage_i": 0, "player_list": [],
        })
        c["players"] += 1
        c["match_exposure"] += r_["country_matches"]
        c["deepest_stage_i"] = max(c["deepest_stage_i"], r_["stage_i"])
        c["player_list"].append(f"{r_['player']} ({r_['country']} {r_['country_matches']})")

    out = sorted(clubs.values(), key=lambda c: -c["match_exposure"])
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["club", "players", "match_exposure", "deepest_stage",
                    "players_detail", "fetched_at", "basis"])
        for c in out:
            w.writerow([
                c["club"], c["players"], c["match_exposure"],
                STAGE_ORDER[c["deepest_stage_i"]],
                "; ".join(c["player_list"]), fetched_at,
                "squad-presence x country FINISHED matches (EI minuutteja)",
            ])

    print(f"WC-pelaajia squadeissa: {n_wc_players} | PL-matchattuja: {len(rows)} "
          f"| seuroja kartalla: {len(out)} | ambiguous: {len(ambiguous)}")
    for a in ambiguous:
        print(f"  AMBIGUOUS: {a[0]} {a[1]} -> {a[2]}")
    print(f"\nTOP-8 kuormitetuinta (match-exposure, EI minuutteja):")
    for c in out[:8]:
        print(f"  {c['club']:22s} players={c['players']:2d} exposure={c['match_exposure']:3d} "
              f"deepest={STAGE_ORDER[c['deepest_stage_i']]}")
    print(f"\nBOTTOM-5 kevyinta (kartalla olevista):")
    for c in out[-5:]:
        print(f"  {c['club']:22s} players={c['players']:2d} exposure={c['match_exposure']:3d}")
    print(f"\nKirjoitettu: {OUT_PATH} (fetched_at={fetched_at})")
    print("HUOM: exposure = squad-presence-proxy, EI minuutteja -> ala mitoita")
    print("aggressiivisia kertoimia taman varaan (ks. docstring).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
