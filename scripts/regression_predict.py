"""
Regressiotesti /api/predict-vastaukselle.

Aja kahdesti (eri git-tilassa) ja vertaa JSON-snapshotteja kentittäin.
Käyttö:
    python -m scripts.regression_predict --base http://localhost:8765 --out before.json
    # ... vaihda git-tila + restartoi uvicorn ...
    python -m scripts.regression_predict --base http://localhost:8765 --out after.json
    python -m scripts.regression_predict --compare before.json after.json
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from typing import Any


CASES = [
    ("ENG-Premier League",   ["2425", "2526"], "Arsenal",                  "Liverpool"),
    ("ENG-Premier League",   ["2425", "2526"], "Manchester City",          "Tottenham"),
    ("ESP-La Liga-FD",       ["2425", "2526"], "Real Madrid CF",           "FC Barcelona"),
    ("GER-Bundesliga-FD",    ["2425", "2526"], "FC Bayern München",        "Borussia Dortmund"),
    ("ITA-Serie A-FD",       ["2425", "2526"], "FC Internazionale Milano", "AC Milan"),
    ("FRA-Ligue 1-FD",       ["2425", "2526"], "Paris Saint-Germain FC",   "Olympique de Marseille"),
    ("INT-Champions League", ["2425", "2526"], "Real Madrid CF",           "FC Bayern München"),
]

NUMERIC_FIELDS = [
    "expected_goals_home", "expected_goals_away",
    "p_home_win", "p_draw", "p_away_win",
    "fair_odds_home", "fair_odds_draw", "fair_odds_away",
    "p_over_2_5", "p_under_2_5",
    "p_btts_yes", "p_btts_no",
]


def _post(url: str, payload: dict, timeout: float = 180.0):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def snapshot(base: str) -> dict:
    out = {}
    for league, seasons, home, away in CASES:
        payload = {"home_team": home, "away_team": away,
                   "leagues": [league], "seasons": seasons}
        try:
            resp = _post(f"{base}/api/predict", payload)
        except Exception as e:
            out[f"{league}|{home}-{away}"] = {"_error": str(e)}
            continue
        rec = {k: resp.get(k) for k in NUMERIC_FIELDS}
        rec["top_scores"] = [(s["score"], s["probability"]) for s in resp.get("top_scores", [])]
        out[f"{league}|{home}-{away}"] = rec
    return out


def compare(before_path: str, after_path: str) -> int:
    with open(before_path, "r", encoding="utf-8") as f:
        before = json.load(f)
    with open(after_path, "r", encoding="utf-8") as f:
        after = json.load(f)
    keys = sorted(set(before) | set(after))
    max_diff = 0.0
    n_mismatch = 0
    for k in keys:
        b = before.get(k)
        a = after.get(k)
        if b != a:
            # Etsi suurin lukuero kenttäkohtaisesti
            row_max = 0.0
            if isinstance(b, dict) and isinstance(a, dict):
                for field in set(b) | set(a):
                    bv = b.get(field)
                    av = a.get(field)
                    if isinstance(bv, (int, float)) and isinstance(av, (int, float)):
                        d = abs(bv - av)
                        if d > row_max:
                            row_max = d
                    elif bv != av:
                        n_mismatch += 1
                        print(f"  DIFF {k} field={field}: before={bv!r} after={av!r}")
            if row_max > max_diff:
                max_diff = row_max
                print(f"  numeric max|diff| @ {k} = {row_max}")
    print(f"\nOverall max|diff| over numeric fields = {max_diff}")
    print(f"Non-numeric mismatches = {n_mismatch}")
    return 0 if (max_diff == 0.0 and n_mismatch == 0) else 1


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--base", default="http://localhost:8765")
    p.add_argument("--out")
    p.add_argument("--compare", nargs=2)
    args = p.parse_args()

    if args.compare:
        sys.exit(compare(args.compare[0], args.compare[1]))

    snap = snapshot(args.base)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(snap, f, indent=2, ensure_ascii=False)
        print(f"Saved snapshot to {args.out}")
    else:
        print(json.dumps(snap, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
