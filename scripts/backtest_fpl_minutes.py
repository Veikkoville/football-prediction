"""#33: Ennustettujen minuuttien walk-forward-backtest 25/26.

Vertaa UUSI minutes_model (probabilistinen start%×xMins, last-6 recency)
vs BASELINE = nykyinen tuotantopolku minutes_form (last-5 recency, p60
starttiproxynä). Sama ship-gate-henki kuin xP-backtestissä: julkaistaan
vain jos parannus baselineen.

Metriikat per GW-kierros k (7..38, jotta molemmilla on täysi ikkuna):
  - xMins MAE: ennustettu vs toteutunut minuutit (cap 90/kierros molemmissa)
  - p_start Brier: P(start) vs toteutunut aloitus (starts >= 1)
Arviointipooli = pelaajat joilla >= 1 min viimeisen 6 kierroksen ikkunassa
ennen k:ta (aktiivinen pooli — talvella seurasta lähteneiden ikuiset nollat
eivät inflatoi kumpaakaan mallia).

HUOM: syvyys-korjaus + saatavuus-gate + ruuhka ovat TUOTANTOpuolen
konservatiivisia portteja (historiallista status/chance-dataa ei ole) —
backtest mittaa ydinmallin (ehdollinen rakenne + recency) baselinea vasten.

Aja repojuuresta: python -m scripts.backtest_fpl_minutes
Read-only: ei kirjoita tuotantodataa.
"""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import numpy as np

from src.data import fpl_api
from src.models import fpl_xp as xp

FIRST_GW = 7
LAST_GW = 38
ACTIVE_WINDOW = 6  # pooli: >=1 min tässä ikkunassa ennen kohde-GW:tä


def main() -> int:
    print("[1/3] FPL-data (bootstrap + element-historiat, välimuisti)...")
    boot = fpl_api.fetch_bootstrap()
    summaries = fpl_api.fetch_all_summaries(boot)
    print(f"      {len(boot['elements'])} pelaajaa")

    mins_by_round: dict[int, dict[int, float]] = {}
    starts_by_round: dict[int, dict[int, int]] = {}
    for e in boot["elements"]:
        pid = e["id"]
        mr: dict[int, float] = defaultdict(float)
        sr: dict[int, int] = defaultdict(int)
        for r in summaries.get(pid, []):
            if r.get("round") is not None:
                mr[r["round"]] += r.get("minutes", 0) or 0
                sr[r["round"]] += r.get("starts", 0) or 0
        mins_by_round[pid] = dict(mr)
        starts_by_round[pid] = dict(sr)
    all_rounds = sorted({rnd for mr in mins_by_round.values() for rnd in mr})

    print(f"[2/3] Walk-forward GW{FIRST_GW}-{LAST_GW}...")
    err_new: list[float] = []
    err_base: list[float] = []
    brier_new: list[float] = []
    brier_base: list[float] = []
    n_rows = 0
    for k in range(FIRST_GW, LAST_GW + 1):
        rounds_before = [r for r in all_rounds if r < k]
        if len(rounds_before) < ACTIVE_WINDOW:
            continue
        window = rounds_before[-ACTIVE_WINDOW:]
        for e in boot["elements"]:
            pid = e["id"]
            mr = mins_by_round[pid]
            if not any(mr.get(r, 0) >= 1 for r in window):
                continue  # ei aktiivinen — ulos poolista
            actual_min = min(float(mr.get(k, 0.0)), 90.0)
            actual_start = 1.0 if (starts_by_round[pid].get(k, 0) or 0) >= 1 else 0.0

            mm = xp.minutes_model(mr, starts_by_round[pid], rounds_before,
                                  n_last=xp.START_WINDOW)
            xm_b, p60_b, _ = xp.minutes_form(mr, rounds_before, n_last=5)

            err_new.append(abs(mm["xmins"] - actual_min))
            err_base.append(abs(xm_b - actual_min))
            brier_new.append((mm["p_start"] - actual_start) ** 2)
            brier_base.append((p60_b - actual_start) ** 2)
            n_rows += 1

    print("[3/3] Tulokset")
    mae_new, mae_base = float(np.mean(err_new)), float(np.mean(err_base))
    br_new, br_base = float(np.mean(brier_new)), float(np.mean(brier_base))
    print("=" * 64)
    print(f"n = {n_rows} pelaaja-GW-riviä (aktiivipooli, GW{FIRST_GW}-{LAST_GW})")
    print(f"xMins MAE:     uusi {mae_new:.3f}  vs baseline {mae_base:.3f}  "
          f"(delta {mae_new - mae_base:+.3f}, {'PAREMPI' if mae_new < mae_base else 'EI parannusta'})")
    print(f"p_start Brier: uusi {br_new:.4f} vs baseline(p60-proxy) {br_base:.4f}  "
          f"(delta {br_new - br_base:+.4f}, {'PAREMPI' if br_new < br_base else 'EI parannusta'})")
    gate = mae_new <= mae_base and br_new <= br_base
    print(f"\nSHIP-GATE: {'PASS' if gate else 'FAIL'} "
          f"(vaatii: MAE uusi <= baseline JA Brier uusi <= baseline)")
    return 0 if gate else 2


if __name__ == "__main__":
    sys.exit(main())
