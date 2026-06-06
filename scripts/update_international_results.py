"""Virkistä vendoroitu martj42/international_results -snapshot (#79).

Lataa results.csv GitHubista (CC0) → data/international_results.csv.
EI ajeta serving-polussa — manuaalinen virkistys + redeploy.

Käyttö:
    python -m scripts.update_international_results
"""
from __future__ import annotations

import urllib.request

import config

URL = "https://raw.githubusercontent.com/martj42/international_results/master/results.csv"
DEST = config.DATA_DIR / "international_results.csv"


def main() -> None:
    print(f"Downloading {URL} ...")
    req = urllib.request.Request(URL, headers={"User-Agent": "goaliq-update/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read()
    if not data or b"home_team" not in data[:200]:
        raise SystemExit("Unexpected payload — header 'home_team' not found, aborting.")
    DEST.write_bytes(data)
    n_lines = data.count(b"\n")
    print(f"Saved {DEST} ({len(data):,} bytes, ~{n_lines:,} rows).")
    print("Next: git add data/international_results.csv && commit + redeploy.")


if __name__ == "__main__":
    main()
