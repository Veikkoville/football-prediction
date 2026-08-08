"""Understatin laukaustaso → per-pelaaja-aggregaatti (STATS-ZONE vaihe 2, 8.8.2026).

Tuottaa `data/understat_player_shots_<kausi>.json`:n jonka `build_fpl_stats.py`
liittää FPL-riveihin. Nama ovat metriikat joita FPL:n oma API EI anna:
laukausmaarat, laukaukset boksista, npxG, paalaukaukset ja erikoistilanne-xG.

**Luetaan levyvalimuistista, ei verkosta.** `data/raw/understat/match_*.json`
on soccerdatan cache-muoto (rosters + shots). Raakaa JSONia luetaan
tarkoituksella soccerdatan `read_shot_events()`:n sijaan: sen kategorinen
normalisointi **hukkaa dataa** — 8.8. mitattu 25/26 PL:sta, `body_part` sai
vain Left/Right Foot ja 1824 riviä NA:ta (paat + muut osumakohdat katosivat),
ja `situation`-arvo Penalty puuttui kokonaan. Raakakentat `shotType` ja
`situation` ovat ehjia.

**Paattynyt kausi on staattinen** → artefakti rakennetaan kerran ja
committataan, samoin kuin `fpl_prev_baselines_2526.json`. CI ei siis hae
380 ottelusivua joka yo (eika GH-runnerin IP:ta altisteta estoille).
Kesken kauden: aja uudelleen kun uusia otteluita on pelattu.

Ajo: python -m scripts.build_understat_shots [--season 2526]
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

CACHE_DIR = config.RAW_DATA_DIR / "understat"
LEAGUE_ID = 1  # Understat: 1 = EPL

# Rangaistusalue normalisoiduissa koordinaateissa. Understat skaalaa
# hyokkayssuunnan pituudelle 0-1 ja leveydelle 0-1.
#   pituus: 16.5 m / 105 m = 0.157 maaliviivalta -> x >= 0.843
#   leveys: (68 - 40.32) / 2 / 68 = 0.2035 kummaltakin laidalta
# Verifioitu rangaistuspotkuilla: niiden pitaa osua boksiin 100-prosenttisesti.
BOX_X = 0.843
BOX_Y_MIN, BOX_Y_MAX = 0.2035, 0.7965

# Oma kynnys "iso paikka" -vastineelle. Optan big chance on manuaalinen
# maaritelma jota meilla ei ole, joten kaytamme lapinakyvaa xG-rajaa ja
# omaa nimea. ALA kutsu tata big chanceksi missaan copyssa.
HIGH_VALUE_XG = 0.30

ON_TARGET = {"Goal", "SavedShot"}
SET_PIECE_SITUATIONS = {"FromCorner", "SetPiece", "DirectFreekick"}

SANITY_MIN_PLAYERS = 200
SANITY_MIN_SHOTS = 5000


def season_dir_key(season: str) -> str:
    """"2526" → Understatin kausiavain "2025"."""
    return f"20{season[:2]}"


def load_season_players(season: str) -> list[dict]:
    path = CACHE_DIR / f"league_{LEAGUE_ID}_season_{season_dir_key(season)}.json"
    if not path.exists():
        raise SystemExit(f"Understat-kausitaulu puuttuu: {path}")
    return json.loads(path.read_text(encoding="utf-8"))["players"]


def load_season_match_ids(season: str) -> list[int]:
    path = CACHE_DIR / f"league_{LEAGUE_ID}_season_{season_dir_key(season)}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    return [int(m["id"]) for m in data["dates"] if m.get("isResult")]


def aggregate_shots(match_ids: list[int]) -> tuple[dict[str, dict], int, int]:
    """player_id → laukausaggregaatti. Palauttaa myos luetut/puuttuvat."""
    acc: dict[str, dict] = defaultdict(lambda: {
        "sh": 0, "sot": 0, "box": 0, "head": 0,
        "npxg": 0.0, "spxg": 0.0, "hvc": 0, "pens": 0,
    })
    read = missing = 0
    for mid in match_ids:
        path = CACHE_DIR / f"match_{mid}.json"
        if not path.exists():
            missing += 1
            continue
        read += 1
        blob = json.loads(path.read_text(encoding="utf-8"))
        for side in ("h", "a"):
            for s in blob.get("shots", {}).get(side, []):
                pid = str(s.get("player_id"))
                if not pid or pid == "None":
                    continue
                xg = float(s.get("xG") or 0.0)
                situation = s.get("situation") or ""
                result = s.get("result") or ""
                a = acc[pid]
                # Oma maali ei ole pelaajan laukaus tassa mielessa: Understat
                # kirjaa sen laukaisijalle, mutta se vaaristaisi osumatarkkuutta.
                if result == "OwnGoal":
                    continue
                a["sh"] += 1
                if result in ON_TARGET:
                    a["sot"] += 1
                x = float(s.get("X") or 0.0)
                y = float(s.get("Y") or 0.0)
                if x >= BOX_X and BOX_Y_MIN <= y <= BOX_Y_MAX:
                    a["box"] += 1
                if s.get("shotType") == "Head":
                    a["head"] += 1
                if situation == "Penalty":
                    a["pens"] += 1
                else:
                    a["npxg"] += xg
                if situation in SET_PIECE_SITUATIONS:
                    a["spxg"] += xg
                if xg >= HIGH_VALUE_XG:
                    a["hvc"] += 1
    return acc, read, missing


def build(season: str) -> dict:
    players = load_season_players(season)
    match_ids = load_season_match_ids(season)
    acc, read, missing = aggregate_shots(match_ids)
    rows = []
    for p in players:
        pid = str(p["id"])
        a = acc.get(pid, {})
        rows.append({
            "uid": pid,
            "name": p["player_name"],
            "team": p["team_title"],
            "mins": int(p["time"]),
            "games": int(p["games"]),
            # kausitaulusta (ei laukausdatasta)
            "kp": int(p["key_passes"]),
            "xgchain": round(float(p["xGChain"]), 2),
            "xgbuildup": round(float(p["xGBuildup"]), 2),
            # laukaustasolta
            "sh": a.get("sh", 0),
            "sot": a.get("sot", 0),
            "box": a.get("box", 0),
            "head": a.get("head", 0),
            "hvc": a.get("hvc", 0),
            "npxg": round(a.get("npxg", 0.0), 2),
            "spxg": round(a.get("spxg", 0.0), 2),
        })
    rows.sort(key=lambda r: -r["sh"])
    return {
        "meta": {
            "available": True,
            "season": f"20{season[:2]}/{season[2:]}",
            "generated_at": _dt.datetime.now().isoformat(timespec="seconds"),
            "source": "Understat shot-level data (own xG model, NOT Opta)",
            "matches_read": read,
            "matches_missing": missing,
            "n_players": len(rows),
            "total_shots": sum(r["sh"] for r in rows),
            "box_definition": (
                f"x >= {BOX_X}, {BOX_Y_MIN} <= y <= {BOX_Y_MAX} "
                "(penalty area in Understat normalised pitch coordinates)"
            ),
            "high_value_threshold": HIGH_VALUE_XG,
            "note": (
                "Understat runs its own xG model, so these numbers do not match "
                "Opta's and must never be labelled as Opta. Penalties are "
                "excluded from npxG. Own goals are not counted as shots."
            ),
        },
        "players": rows,
    }


def sanity(data: dict) -> list[str]:
    fails = []
    meta, rows = data["meta"], data["players"]
    if len(rows) < SANITY_MIN_PLAYERS:
        fails.append(f"vain {len(rows)} pelaajaa")
    if meta["total_shots"] < SANITY_MIN_SHOTS:
        fails.append(f"vain {meta['total_shots']} laukausta")
    if meta["matches_missing"]:
        fails.append(f"{meta['matches_missing']} ottelua puuttuu valimuistista")
    for r in rows:
        if r["sot"] > r["sh"]:
            fails.append(f"{r['name']}: SoT {r['sot']} > laukaukset {r['sh']}")
            break
        if r["box"] > r["sh"]:
            fails.append(f"{r['name']}: boksilaukaukset > laukaukset")
            break
        if r["head"] > r["sh"]:
            fails.append(f"{r['name']}: paalaukaukset > laukaukset")
            break
        if r["sh"] and r["npxg"] / r["sh"] > 0.75:
            fails.append(f"{r['name']}: npxG/laukaus {r['npxg'] / r['sh']:.2f}")
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
    out = config.DATA_DIR / f"understat_player_shots_{args.season}.json"
    out.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    m = data["meta"]
    print("=" * 64)
    print("UNDERSTAT SHOT AGGREGATE OK")
    print("=" * 64)
    print(f"  season   : {m['season']}")
    print(f"  matches  : {m['matches_read']} luettu, {m['matches_missing']} puuttuu")
    print(f"  players  : {m['n_players']}")
    print(f"  shots    : {m['total_shots']}")
    print(f"  out      : {out} ({out.stat().st_size / 1024:.0f} kB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
