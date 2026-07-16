"""Promotoi ship-gate PASS -WC-refit stagingista data/-juureen (#100).

refresh_wc_model kirjoittaa PASS-refitin staging-kansioon
(data/_refit_candidate/) eikä enää suoraan trackattuihin tiedostoihin →
työpuu pysyy puhtaana kunnes tämä skripti ajetaan (eksplisiittinen
hyväksyntä: Ville lokaalisti tai wc-knockout-refresh.yml:n PASS-askel CI:ssä).

Aja repojuuresta: python -m scripts.promote_wc_refit
Exit: 0 = promotoitu (git-ohjeet tulostettu), 1 = staging puuttuu/vajaa.
"""
from __future__ import annotations

import json
import shutil
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import config

DATA_FILES = ["international_results.csv", "elo_ratings.csv", "wc_model.json"]
STAGING_DIR = config.WC_REFIT_STAGING_DIR
STAGING_META = "_refit_meta.json"


def main() -> int:
    if not STAGING_DIR.exists():
        print(f"EI PROMOTOITAVAA: {STAGING_DIR} puuttuu — aja ensin "
              "python -m scripts.refresh_wc_model (ship-gate PASS luo stagingin).")
        return 1
    missing = [n for n in DATA_FILES if not (STAGING_DIR / n).exists()]
    if missing:
        print(f"STAGING VAJAA ({missing}) — ei promotoida. Poista {STAGING_DIR} "
              "ja aja refresh uudelleen.")
        return 1

    meta_path = STAGING_DIR / STAGING_META
    if meta_path.exists():
        with open(meta_path, encoding="utf-8") as f:
            m = json.load(f)
        fit = m.get("fit_meta", {})
        print(f"Promotoidaan refit: staged_at={m.get('staged_at', '?')}, "
              f"treeniottelut={fit.get('n_train_matches', '?')}, "
              f"maat={fit.get('n_teams', '?')}")
        print(f"  gate: {m.get('gate', {})}")

    for name in DATA_FILES:
        shutil.copy2(STAGING_DIR / name, config.DATA_DIR / name)
        print(f"  {name} -> data/")
    shutil.rmtree(STAGING_DIR)

    print("PROMOTOITU. Seuraavaksi (Villen päätös / CI:n PASS-askel):")
    print("  git add data/international_results.csv data/elo_ratings.csv data/wc_model.json")
    print('  git commit -m "data: WC-mallin virkistys (gate PASS)"')
    print("  git push   <- Render auto-deployaa mainista")
    return 0


if __name__ == "__main__":
    sys.exit(main())
