"""Generoi/päivitä domestic golden-master TIETOISESTI.

1. Snapshottaa /api/predict-caset lokaalista koodista (in-process TestClient).
2. Ristiintarkistaa TUOTANTOA (goaliq-api.onrender.com) vasten.
3. Kirjoittaa goldenin VAIN jos lokaali == tuotanto bit-exact.
   Ero -> raportti + exit 1, goldenia ei kirjoiteta (--force ohittaa, käytä
   vain kun ero on selitetty, esim. juuri deployattu tietoinen mallimuutos).

Aja repojuuresta: python -m tests.update_golden [--force]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from scripts.regression_predict import CASES, NUMERIC_FIELDS, snapshot as prod_snapshot

GOLDEN_PATH = Path(__file__).parent / "golden" / "domestic_predict_golden.json"
PROD_BASE = "https://goaliq-api.onrender.com"


def local_snapshot() -> dict:
    from fastapi.testclient import TestClient
    from api.main import app
    client = TestClient(app)
    out = {}
    for league, seasons, home, away in CASES:
        r = client.post("/api/predict", json={
            "home_team": home, "away_team": away,
            "leagues": [league], "seasons": seasons,
        })
        key = f"{league}|{home}-{away}"
        if r.status_code != 200:
            out[key] = {"_error": f"HTTP {r.status_code}: {r.text[:200]}"}
            continue
        body = r.json()
        rec = {k: body.get(k) for k in NUMERIC_FIELDS}
        rec["top_scores"] = [[s["score"], s["probability"]]
                             for s in body.get("top_scores", [])]
        out[key] = json.loads(json.dumps(rec))
    return out


def compare(local: dict, prod: dict) -> tuple[float, int]:
    max_diff, n_mismatch = 0.0, 0
    for k in sorted(set(local) | set(prod)):
        lv, pv = local.get(k), prod.get(k)
        if lv == pv:
            continue
        if isinstance(lv, dict) and isinstance(pv, dict):
            for field in set(lv) | set(pv):
                a, b = lv.get(field), pv.get(field)
                if isinstance(a, (int, float)) and isinstance(b, (int, float)):
                    d = abs(a - b)
                    if d > 0:
                        max_diff = max(max_diff, d)
                        print(f"  DIFF {k} {field}: lokaali={a!r} prod={b!r} |d|={d}")
                elif a != b:
                    n_mismatch += 1
                    print(f"  DIFF {k} {field}: lokaali={a!r} prod={b!r}")
        else:
            n_mismatch += 1
            print(f"  DIFF {k}: lokaali={lv!r} prod={pv!r}")
    return max_diff, n_mismatch


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--force", action="store_true",
                   help="kirjoita golden vaikka tuotanto eroaisi (selitetty ero)")
    args = p.parse_args()

    print("Lokaali snapshot (in-process, fittaa domestic-mallit on-demand)...")
    local = local_snapshot()
    errors = [k for k, v in local.items() if "_error" in v]
    if errors:
        print(f"VIRHE: lokaalit caset epäonnistuivat: {errors}")
        return 2

    print(f"Tuotanto-snapshot ({PROD_BASE})...")
    prod = prod_snapshot(PROD_BASE)
    # prod-snapshot tallentaa top_scores tuplina -> normalisoi JSONiksi
    prod = json.loads(json.dumps(prod))

    print("\nVertailu lokaali vs tuotanto:")
    max_diff, n_mismatch = compare(local, prod)
    print(f"  max|diff|={max_diff}, non-numeric mismatches={n_mismatch}")

    if (max_diff != 0.0 or n_mismatch) and not args.force:
        print("\nSTOP: lokaali != tuotanto — goldenia EI kirjoitettu.")
        print("Selvitä ero ennen tallennusta (tai --force jos ero on tietoinen).")
        return 1

    GOLDEN_PATH.parent.mkdir(exist_ok=True)
    with open(GOLDEN_PATH, "w", encoding="utf-8") as f:
        json.dump(local, f, indent=1, ensure_ascii=False)
    print(f"\nGolden kirjoitettu: {GOLDEN_PATH} ({len(local)} casea)"
          + (" [--force]" if args.force and (max_diff or n_mismatch) else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
