"""Jaadyta edellisen kauden minuutti- ja starttihistoria pelaajan CODE:lla.

MIKSI: pre-season-priori (`minutes_model(..., n_last=None)`) ennustaa uuden
kauden GW1-minuutit PAATTYNEEN kauden per-GW-historiasta. Sita ei voi validoida
kauden sisaisella walk-forwardilla, koska sellainen ei koskaan ylita kesataukoa
- ja kesatauko on juuri se mekanismi jota priorin vaimennuskerroin saatelee.
Puoliintuma 10 valittiin 9.8.2026 HARKINTANA (kauden sisainen proxy suositti
4:aa, mutta proxy ei nae kesataukoa). Harkinta on nyt mitattavissa.

FPL:n oma API ei tarjoa paattyneita kausia, joten lahde on yhteisoarkisto
(vaastav/Fantasy-Premier-League), joka on FPL:n omien gw-dumppien kopio.

IDENTITEETTI: avain on `code`, EI `id`. FPL:n element-id:t nollautuvat joka
kausi (todennettu 9.8.2026: id-mappays kattoi 269/400 pelaajaa ja loput olisivat
nayttaneet tyhjaa ILMAN virhetta). `code` on pysyva pelaajatunniste.

Ajo:  python -m scripts.build_fpl_prev_season_minutes --season 2425
Tuottaa committoitavan `data/fpl_prev_season_minutes_<kausi>.json`:n
(raakadata on gitignoratussa data/raw/fpl/season_<kausi>/ eika elaisi CI:ssa).
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config

SCHEMA_VERSION = 1


def build(season: str) -> dict:
    src = config.RAW_DATA_DIR / "fpl" / f"season_{season}"
    if not src.is_dir():
        raise SystemExit(
            f"Raakadata puuttuu: {src}\n"
            f"Hae ensin gw1..gw38.csv + players_raw.csv kauden {season} "
            f"arkistosta.")

    # element-id -> code (vain talle kaudelle) + staattiset kentat
    meta: dict[int, dict] = {}
    with (src / "players_raw.csv").open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            meta[int(row["id"])] = {
                "code": int(row["code"]),
                "pos": int(row["element_type"]),
                "web_name": row.get("web_name") or "",
            }
    if not meta:
        raise SystemExit("players_raw.csv oli tyhja")

    rounds_by_code: dict[int, dict[int, list[int]]] = defaultdict(dict)
    seen_rounds: set[int] = set()
    unmapped = 0
    for gw in range(1, 39):
        p = src / f"gw{gw}.csv"
        if not p.exists():
            continue
        with p.open(encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                el = int(row["element"])
                m = meta.get(el)
                if m is None:
                    unmapped += 1
                    continue
                rnd = int(row["round"])
                seen_rounds.add(rnd)
                mins = int(row["minutes"] or 0)
                starts = int(row.get("starts") or 0)
                pts = int(row.get("total_points") or 0)
                # Tuplaviikko: sama pelaaja, sama kierros, kaksi ottelua ->
                # summataan, kuten element-summary tekee.
                cur = rounds_by_code[m["code"]].get(rnd)
                if cur is None:
                    rounds_by_code[m["code"]][rnd] = [mins, starts, pts]
                else:
                    cur[0] += mins
                    cur[1] += starts
                    cur[2] += pts

    if unmapped:
        print(f"VAROITUS: {unmapped} riville ei loytynyt element-id:ta "
              f"players_raw.csv:sta")

    players = {}
    for el, m in meta.items():
        rr = rounds_by_code.get(m["code"])
        if not rr:
            continue
        if not any(v[0] > 0 for v in rr.values()):
            continue  # ei yhtaan pelattua minuuttia -> ei prioria
        players[str(m["code"])] = {
            "web_name": m["web_name"],
            "pos": m["pos"],
            # {kierros: [minuutit, startit, pisteet]}
            "rounds": {str(k): v for k, v in sorted(rr.items())},
        }

    return {
        "schema_version": SCHEMA_VERSION,
        "season": season,
        "key": "FPL player code (pysyva; element-id nollautuu kausittain)",
        "n_players": len(players),
        "n_rounds": len(seen_rounds),
        "players": players,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", default="2425")
    args = ap.parse_args()

    doc = build(args.season)
    out = (config.PROJECT_ROOT / "data"
           / f"fpl_prev_season_minutes_{args.season}.json")
    out.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")),
                   encoding="utf-8")
    size_kb = out.stat().st_size / 1024
    print(f"{out.name}: {doc['n_players']} pelaajaa, {doc['n_rounds']} "
          f"kierrosta, {size_kb:.0f} kt")

    # Sanity: taysi kausi on 38 kierrosta, ja jokaisella pelaajalla pitaa olla
    # vahintaan yksi kierros. Hiljainen puolikas kausi tekisi priorista
    # systemaattisesti liian pienen.
    if doc["n_rounds"] != 38:
        print(f"VAROITUS: kierroksia {doc['n_rounds']}, odotettu 38")
    return 0


if __name__ == "__main__":
    sys.exit(main())
