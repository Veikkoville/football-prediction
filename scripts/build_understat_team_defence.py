"""Joukkuetason puolustusprofiili laukausdatasta (STATS-ZONE lisa, 8.8.2026).

Vastaa kysymykseen jota puhdas CS-% ei vastaa: **millaisia paikkoja tama
puolustus paastaa?** Kaksi joukkuetta voi paastaa yhta monta laukausta, mutta
toinen paastaa ne boksin keskelta ja paalla, toinen kaukaa laidalta.

FPL-hyoty: puolustaja- ja maalivahtivalinta. Korkea paalaukausmaara vastaan
tarkoittaa etta erikoistilanteet ovat riski; keskiboksin paikat kertovat
avoimen pelin heikkoudesta.

Tuottaa `data/understat_team_defence_<kausi>.json`:n samasta levyvalimuistista
kuin `build_understat_shots.py` (`data/raw/understat/match_*.json`) — raakaa
JSONia, EI soccerdatan `read_shot_events()`:a (se hukkaa shotType-arvot Head ja
OtherBodyPart, mitattu 8.8: 1824 NA-rivia).

Vyohykkeet normalisoidussa kentassa (x = pituus kohti maalia, y = leveys):
  six      x >= 0.945           ja |y - 0.5| <= 0.132   (5,5 m alue)
  central  x >= 0.843           ja |y - 0.5| <= 0.132   (boksi, keskikaista)
  wide     x >= 0.843           ja |y - 0.5| >  0.132   (boksi, laitakaistat)
  edge     0.75 <= x < 0.843                            (boksin suu)
  far      x < 0.75                                     (kaukolaukaukset)
Rangaistuspotkut lasketaan omaan sarakkeeseensa EIKA vyohykkeisiin: ne eivat
kerro puolustuksen rakenteesta mitaan.

Ajo: python -m scripts.build_understat_team_defence [--season 2526]
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from scripts.build_fpl_phase0 import map_name
from scripts.build_understat_shots import (HIGH_VALUE_XG, LEAGUE_ID,
                                           load_season_match_ids)
from src.data.fpl_api import fetch_bootstrap

BOX_X = 0.843
SIX_X = 0.945
CENTRAL_HALF_WIDTH = 0.132   # 18 m leveydesta puolet 68 m kentalla
EDGE_X = 0.75

SANITY_MIN_TEAMS = 15   # 20 miinus nousijat joilla ei ole PL-dataa
SANITY_MIN_MATCHES = 30


def zone(x: float, y: float) -> str:
    central = abs(y - 0.5) <= CENTRAL_HALF_WIDTH
    if x >= SIX_X and central:
        return "six"
    if x >= BOX_X:
        return "central" if central else "wide"
    if x >= EDGE_X:
        return "edge"
    return "far"


def build(season: str) -> dict:
    acc: dict[str, dict] = defaultdict(lambda: {
        "matches": 0, "shots": 0, "xg": 0.0, "head": 0, "hvc": 0,
        "sp_xg": 0.0, "pens": 0,
        "six": 0, "central": 0, "wide": 0, "edge": 0, "far": 0,
    })
    read = missing = 0
    for mid in load_season_match_ids(season):
        path = config.RAW_DATA_DIR / "understat" / f"match_{mid}.json"
        if not path.exists():
            missing += 1
            continue
        read += 1
        blob = json.loads(path.read_text(encoding="utf-8"))
        shots = blob.get("shots", {})
        # Kotijoukkueen laukaukset ovat vieraan PAASTAMIA ja painvastoin.
        for side, conceding in (("h", "a_team"), ("a", "h_team")):
            rows = shots.get(side, [])
            if not rows:
                continue
            team = rows[0].get(conceding)
            if not team:
                continue
            a = acc[team]
            for s in rows:
                if s.get("result") == "OwnGoal":
                    continue
                xg = float(s.get("xG") or 0.0)
                situation = s.get("situation") or ""
                a["shots"] += 1
                a["xg"] += xg
                if xg >= HIGH_VALUE_XG:
                    a["hvc"] += 1
                if s.get("shotType") == "Head":
                    a["head"] += 1
                if situation == "Penalty":
                    a["pens"] += 1
                    continue     # ei vyohykkeisiin
                if situation in {"FromCorner", "SetPiece", "DirectFreekick"}:
                    a["sp_xg"] += xg
                a[zone(float(s.get("X") or 0.0), float(s.get("Y") or 0.0))] += 1
        for team_key in ("h_team", "a_team"):
            for side in ("h", "a"):
                rows = shots.get(side, [])
                if rows:
                    break
        # ottelumaara: molemmille joukkueille yksi
        h = shots.get("h") or shots.get("a") or []
        if h:
            acc[h[0]["h_team"]]["matches"] += 1
            acc[h[0]["a_team"]]["matches"] += 1

    # KENTTA JOKA PUUTTUI (Villen havainto 8.8): basis on 25/26, mutta sivu
    # otsikoi itsensa Premier League -taulukoksi. Ilman tata suodatusta se
    # listasi kolme PUDONNUTTA joukkuetta (Burnley, West Ham, Wolves) ja
    # jatti kolme NOUSSUTTA pois (Coventry, Hull, Ipswich) — ja markkinointi-
    # kulmaksi oli valikoitumassa Championship-joukkueen luku.
    # Auktoriteetti sille kuka on liigassa on FPL:n oma joukkuelista.
    current = {map_name(t["name"]) for t in fetch_bootstrap()["teams"]}
    with_data = set(acc)

    rows = []
    for team, a in acc.items():
        if team not in current:
            continue
        m = max(a["matches"], 1)
        rows.append({
            "team": team,
            "matches": a["matches"],
            "shots_pm": round(a["shots"] / m, 2),
            "xg_pm": round(a["xg"] / m, 3),
            "head_pm": round(a["head"] / m, 2),
            "hvc_pm": round(a["hvc"] / m, 2),
            "sp_xg_pm": round(a["sp_xg"] / m, 3),
            "six_pm": round(a["six"] / m, 2),
            "central_pm": round(a["central"] / m, 2),
            "wide_pm": round(a["wide"] / m, 2),
            "edge_pm": round(a["edge"] / m, 2),
            "far_pm": round(a["far"] / m, 2),
            "pens": a["pens"],
            "box_share": round(
                100.0 * (a["six"] + a["central"] + a["wide"])
                / max(a["shots"] - a["pens"], 1), 1),
        })
    rows.sort(key=lambda r: r["xg_pm"])
    promoted = sorted(current - with_data)
    relegated = sorted(with_data - current)
    return {
        "meta": {
            "available": True,
            "season": f"20{season[:2]}/{season[2:]}",
            "promoted_no_data": promoted,
            "relegated_excluded": relegated,
            "n_current_teams": len(current),
            "generated_at": _dt.datetime.now().isoformat(timespec="seconds"),
            "source": "Understat shot-level data (own xG model, NOT Opta)",
            "matches_read": read,
            "matches_missing": missing,
            "n_teams": len(rows),
            "zones": {
                "six": f"x >= {SIX_X}, central band",
                "central": f"x >= {BOX_X}, central band (|y-0.5| <= {CENTRAL_HALF_WIDTH})",
                "wide": f"x >= {BOX_X}, outside central band",
                "edge": f"{EDGE_X} <= x < {BOX_X}",
                "far": f"x < {EDGE_X}",
            },
            "note": (
                "Penalties are counted separately and excluded from the zone "
                "columns: they say nothing about defensive shape. Everything "
                "is per match. Own goals are not counted as shots."
            ),
        },
        "teams": rows,
    }


def sanity(data: dict) -> list[str]:
    fails = []
    meta, rows = data["meta"], data["teams"]
    covered = len(rows) + len(meta.get("promoted_no_data") or [])
    if covered != meta.get("n_current_teams"):
        fails.append(
            f"katettu {covered} != liigan {meta.get('n_current_teams')} "
            "joukkuetta (rivit + nousijat ei tasmaa)")
    for r in rows:
        if r["team"] in (meta.get("relegated_excluded") or []):
            fails.append(f"{r['team']} on pudonnut mutta on yha taulukossa")
            break
    if len(rows) < SANITY_MIN_TEAMS:
        fails.append(f"vain {len(rows)} joukkuetta")
    if meta["matches_missing"]:
        fails.append(f"{meta['matches_missing']} ottelua puuttuu valimuistista")
    for r in rows:
        if r["matches"] < SANITY_MIN_MATCHES:
            fails.append(f"{r['team']}: vain {r['matches']} ottelua")
            break
        zones = (r["six_pm"] + r["central_pm"] + r["wide_pm"] + r["edge_pm"]
                 + r["far_pm"])
        if abs(zones - (r["shots_pm"] - r["pens"] / max(r["matches"], 1))) > 0.02:
            fails.append(f"{r['team']}: vyohykesumma {zones} != laukaukset")
            break
        if not 0 <= r["box_share"] <= 100:
            fails.append(f"{r['team']}: box_share {r['box_share']}")
            break
        if r["head_pm"] > r["shots_pm"]:
            fails.append(f"{r['team']}: paita enemman kuin laukauksia")
            break
    return fails


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", default="2526")
    args = ap.parse_args(argv)
    data = build(args.season)
    fails = sanity(data)
    if fails:
        print("SANITY FAIL — dataa EI kirjoiteta:")
        for f in fails:
            print(f"  - {f}")
        return 2
    out = config.DATA_DIR / f"understat_team_defence_{args.season}.json"
    out.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    m = data["meta"]
    print("=" * 64)
    print("TEAM DEFENCE PROFILE OK")
    print("=" * 64)
    print(f"  season  : {m['season']}")
    print(f"  matches : {m['matches_read']} luettu, {m['matches_missing']} puuttuu")
    print(f"  teams   : {m['n_teams']}")
    print(f"  out     : {out} ({out.stat().st_size / 1024:.0f} kB)")
    print()
    print("  Parhaat (xG paastetty / ottelu):")
    for r in data["teams"][:5]:
        print(f"    {r['team']:<22} xG {r['xg_pm']:.2f}  paita {r['head_pm']:.2f}"
              f"  keskiboksi {r['central_pm']:.2f}  boksiosuus {r['box_share']:.0f} %")
    return 0


if __name__ == "__main__":
    sys.exit(main())
