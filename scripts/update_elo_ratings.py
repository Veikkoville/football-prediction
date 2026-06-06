"""#79 — vendoroi World Football Elo -snapshot → data/elo_ratings.csv (CC: eloratings.net).

Ankkuroi WC-mallin attack/defence cross-confederation-uskottavaan skaalaan (Japani-
tyyppinen heikon konfederaation karsintainflaatio pois). EI live-pullia ajossa.

Aja datan virkistyksen yhteydessä:
    python -m scripts.update_elo_ratings
"""
from __future__ import annotations

import csv
import sys
import urllib.request

import config

WORLD_URL = "http://eloratings.net/World.tsv"   # rank, rank, code, elo, ...
TEAMS_URL = "http://eloratings.net/en.teams.tsv"  # code \t name
DEST = config.DATA_DIR / "elo_ratings.csv"


def _fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "goaliq-update/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8")


def main() -> None:
    code_to_name = {}
    for line in _fetch(TEAMS_URL).splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            code_to_name[parts[0].strip()] = parts[1].strip()

    rows = []
    for line in _fetch(WORLD_URL).splitlines():
        parts = line.split("\t")
        if len(parts) < 4:
            continue
        code = parts[2].strip()
        try:
            elo = int(parts[3].strip())
        except ValueError:
            continue
        name = code_to_name.get(code, code)
        rows.append((code, name, elo))

    if len(rows) < 100:
        raise SystemExit(f"Unexpected Elo payload ({len(rows)} rows) — aborting.")

    with open(DEST, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["code", "name", "elo"])
        w.writerows(rows)
    print(f"Saved {DEST} ({len(rows)} teams). Top: "
          f"{', '.join(f'{n} {e}' for _, n, e in rows[:3])}")
    print("Next: python -m scripts.build_wc_model && git add data/ && commit + deploy")


if __name__ == "__main__":
    main()
