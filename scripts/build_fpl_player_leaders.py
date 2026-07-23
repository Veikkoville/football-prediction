"""Nightly-cache #124 xG leaders + #125 DefCon tracker -datalle.

Hakee FPL bootstrap + element-summaryt (levyvälimuisti src/data/fpl_api.py:n
kautta — valmiin kauden summaryt eivät vanhene) ja kirjoittaa per-pelaaja
viimeisimmät pelatut ottelut → data/fpl_player_leaders.json. Endpointit
/api/fantasy/xg-leaders + /api/fantasy/defcon-leaders rankkaavat tästä
(src/models/fpl_leaders.py) — ei laskentaa pyynnössä.

DATA-RAJOITUKSET ENSILUOKKAISENA (Villen vaatimus 17.7):
  - basis_season = bootstrapin servaama kausi. Nyt (ennen 26/27-avausta) se on
    2025/26 → meta.is_prev_season_basis=True + pakollinen basis_label.
  - Kun FPL avaa 26/27:n: basis vaihtuu automaattisesti. Pelaajille joilla
    < MIN_CURRENT_GAMES (3) pelattua 26/27-ottelua käytetään EDELLISEN
    committatun snapshotin 25/26-rivejä (per-pelaaja basis-kenttä kertoo
    lähteen) — 25/26-baseline kunnes todellista kauden dataa on tarpeeksi.
  - Pelaaja ilman yhtään pelattua ottelua kummassakaan → ei listalla
    (frontend: "No data yet") — EI arvauksia.

Fail-safe: sanity gate FAIL → exit 2 → EI committia (vanha data jää voimaan),
sama konventio kuin muut FPL-builderit.
"""
from __future__ import annotations

import datetime as _dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data.fpl_api import (fetch_bootstrap, fetch_all_summaries,
                              season_key_from_bootstrap)
from src.models.fpl_leaders import LEADERS_PATH, MIN_CURRENT_GAMES

POS_NAME = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}
RECENT_KEEP = 10          # rivejä per pelaaja → window 3-10 endpointissa
TARGET_SEASON = "2026/27"  # kausi jota kohti ollaan menossa (label-logiikka)
SANITY_MIN_PLAYERS = 200
SANITY_MAX_XG_PG = 2.5    # kukaan ei tuota >2.5 xG/game kestävästi


def season_label(key: str) -> str:
    """"2526" → "2025/26"."""
    return f"20{key[:2]}/{key[2:]}"


def _player_rows(boot: dict, summaries: dict, season: str,
                 keep_empty: bool) -> list[dict]:
    """Rakenna per-pelaaja-rivit bootstrap+summary-datasta. keep_empty=True
    jättää 0 pelatun ottelun pelaajat mukaan stubina (recent_games=[]) —
    kausivaihto-merge voi täyttää ne edellisen snapshotin riveillä."""
    teams = {t["id"]: t["short_name"] for t in boot["teams"]}
    players = []
    for e in boot["elements"]:
        pos = POS_NAME.get(e["element_type"])
        if pos is None:
            continue
        history = summaries.get(e["id"]) or []
        played = [r for r in history if (r.get("minutes") or 0) > 0]
        played.sort(key=lambda r: (r.get("round") or 0, r.get("kickoff_time") or ""))
        recent = played[-RECENT_KEEP:]
        if not recent and not keep_empty:
            continue  # ei pelattuja otteluita → ei listalle (No data yet)
        rows = []
        for r in recent:
            cbit = ((r.get("clearances_blocks_interceptions") or 0)
                    + (r.get("tackles") or 0))
            cbirt = cbit + (r.get("recoveries") or 0)
            rows.append({
                "round": r.get("round"),
                "opp": teams.get(r.get("opponent_team"), ""),
                "venue": "H" if r.get("was_home") else "A",
                "minutes": r.get("minutes") or 0,
                "xg": float(r.get("expected_goals") or 0.0),
                "xa": float(r.get("expected_assists") or 0.0),
                "xgi": float(r.get("expected_goal_involvements") or 0.0),
                # dc = FPL:n defensive_contribution-kenttä (== CBIT DEF:lle,
                # CBIRT MID/FWD:lle; empiirisesti verifioitu 100 %) — fallback
                # laskettuun arvoon jos kenttä puuttuu.
                "dc": int(r.get("defensive_contribution")
                          if r.get("defensive_contribution") is not None
                          else (cbit if pos == "DEF" else cbirt)),
            })
        players.append({
            "id": e["id"],
            # code = FPL:n kausien yli pysyvä pelaajakoodi — kausivaihto-
            # mergen avain (element-id:t NOLLAUTUVAT kausivaihdossa, joten
            # id-mappaus sekoittaisi eri pelaajien historiat).
            "code": e.get("code"),
            "web_name": e["web_name"],
            "team_short": teams.get(e["team"], ""),
            "pos": pos,
            "price": (e.get("now_cost") or 0) / 10.0,
            "owned_pct": float(e.get("selected_by_percent") or 0.0),
            "games_total": len(played),
            "basis": season,
            "recent_games": rows,
        })
    return players


def build() -> dict:
    boot = fetch_bootstrap()
    season = season_label(season_key_from_bootstrap(boot))
    players = _player_rows(boot, fetch_all_summaries(boot), season,
                           keep_empty=(season == TARGET_SEASON))

    # Kausivaihto-merge: jos basis on jo target-kausi mutta pelaajalla on alle
    # MIN_CURRENT_GAMES pelattua ottelua → käytä edellisen snapshotin
    # edelliskauden riviä (basis-kenttä säilyy 2025/26 → rehellinen label).
    # Mappaus element CODElla (pysyvä kausien yli) — EI id:llä (nollautuu).
    if season == TARGET_SEASON and LEADERS_PATH.exists():
        try:
            prev = json.loads(LEADERS_PATH.read_text(encoding="utf-8"))
            prev_by_code = {p["code"]: p for p in prev.get("players", [])
                            if p.get("basis") != TARGET_SEASON and p.get("code")}
        except Exception:
            prev_by_code = {}
        merged = []
        for p in players:
            if p["games_total"] < MIN_CURRENT_GAMES and p.get("code") in prev_by_code:
                merged.append(prev_by_code[p["code"]])
            else:
                merged.append(p)
        players = merged
    # Stubit joille ei löytynyt edelliskauden riviä → pois (No data yet).
    players = [p for p in players if p["recent_games"]]
    return _package(season, players)


def build_from_cache_2526() -> dict:
    """Kertaluontoinen kausivaihtoajo (--freeze-prev-2526): rakenna snapshot
    lokaalista 25/26-levycachesta (vanha bootstrap + summary_2526/). MIKSI:
    26/27-flipin (23.7.2026) jälkeen 25/26-per-ottelu-data ei ole enää
    haettavissa API:sta, ja aiemmin committoidusta snapshotista puuttuvat
    code-kentät joita kausivaihto-merge tarvitsee. VAIN levycache — ei
    verkkohakuja."""
    cache = Path(__file__).resolve().parent.parent / "data" / "raw" / "fpl"
    boot = json.loads((cache / "bootstrap_static.json").read_text(encoding="utf-8"))
    if not boot["events"][0]["deadline_time"].startswith("2025-"):
        raise SystemExit(
            "VIRHE: bootstrap-cache ei ole 25/26-kautta (ylikirjoitettu jo "
            "26/27:llä) — freeze ei mahdollinen tällä koneella.")
    summaries: dict[int, list[dict]] = {}
    missing = 0
    for e in boot["elements"]:
        p = cache / "summary_2526" / f"element_{e['id']}.json"
        if p.exists():
            summaries[e["id"]] = json.loads(
                p.read_text(encoding="utf-8")).get("history", [])
        else:
            missing += 1
    if missing:
        raise SystemExit(f"VIRHE: {missing} summary-tiedostoa puuttuu cachesta.")
    season = season_label(season_key_from_bootstrap(boot))
    players = _player_rows(boot, summaries, season, keep_empty=False)
    return _package(season, players)


def _package(season: str, players: list[dict]) -> dict:
    is_prev = season != TARGET_SEASON or all(
        p.get("basis") != TARGET_SEASON for p in players)
    basis_label = (
        f"Based on {season} · updates as the new season plays"
        if season != TARGET_SEASON else
        "Mixed basis: players with under 3 games this season show last "
        "season's data (per-row basis field)."
        if any(p.get("basis") != TARGET_SEASON for p in players) else
        "This season's data."
    )

    return {
        "meta": {
            "available": True,
            "generated_at": _dt.datetime.now(_dt.timezone.utc)
                .strftime("%Y-%m-%dT%H:%M:%S"),
            "basis_season": season,
            "target_season": TARGET_SEASON,
            "is_prev_season_basis": is_prev,
            "basis_label": basis_label,
            "recent_keep": RECENT_KEEP,
            "min_current_games": MIN_CURRENT_GAMES,
            "n_players": len(players),
            "source": "FPL official API (bootstrap + element-summary)",
            "defcon_rule_verified": (
                "2026-07-17: premierleague.com 25/26 rules (DEF 10 CBIT / "
                "MID+FWD 12 CBIRT, 2 pts, capped per match) + bootstrap "
                "game_config.scoring + empirical field check 100%"),
        },
        "players": players,
    }


def sanity(data: dict) -> list[str]:
    fails = []
    n = len(data["players"])
    if n < SANITY_MIN_PLAYERS:
        fails.append(f"players {n} < {SANITY_MIN_PLAYERS}")
    for p in data["players"]:
        recent = p["recent_games"][-5:]
        if not recent:
            continue
        xg_pg = sum(g["xg"] for g in recent) / len(recent)
        if xg_pg > SANITY_MAX_XG_PG:
            fails.append(f"{p['web_name']} xg/game {xg_pg:.2f} epäuskottava")
        for g in recent:
            if g["dc"] < 0 or g["dc"] > 60:
                fails.append(f"{p['web_name']} dc {g['dc']} out of range")
    return fails[:10]


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--freeze-prev-2526", action="store_true",
                    help="Rakenna snapshot lokaalista 25/26-cachesta "
                         "(kertaluontoinen kausivaihtoajo, lisää code-kentät)")
    args = ap.parse_args(argv)

    if args.freeze_prev_2526:
        data = build_from_cache_2526()
    else:
        boot = fetch_bootstrap()
        season = season_label(season_key_from_bootstrap(boot))
        # Kausivaihto-guard: kohdekausi ilman yhtään pelattua GW:tä →
        # edellinen (25/26-basis, rehellisesti labeloitu) snapshot jää
        # voimaan EIKÄ haeta 841 tyhjää element-summarya turhaan.
        if season == TARGET_SEASON and not any(
                ev.get("finished") for ev in boot.get("events", [])):
            print(f"PRE-SEASON ({season}, 0 pelattua GW:tä) — {LEADERS_PATH.name} "
                  f"jää ennalleen (edelliskauden basis, label rehellinen).")
            return 0
        data = build()
    fails = sanity(data)
    if fails:
        print("SANITY FAIL — dataa EI kirjoiteta:")
        for f in fails:
            print(f"  - {f}")
        return 2
    LEADERS_PATH.write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8")
    m = data["meta"]
    print("=" * 64)
    print("FPL PLAYER LEADERS BUILD OK")
    print("=" * 64)
    print(f"  players       : {m['n_players']}")
    print(f"  basis_season  : {m['basis_season']} (prev-basis: {m['is_prev_season_basis']})")
    print(f"  label         : {m['basis_label']}")
    print(f"  out           : {LEADERS_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
