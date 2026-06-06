"""#79 — esirakenna WC-malli offline → data/wc_model.json.

Render Starterin ~0.5 vCPU ei jaksa fitata "any"-mallia (195 maata / 302 param
SLSQP) ajossa ilman timeoutia (todennettu: predict-wc HTTP=000 @ 90-150s). Malli
fitataan tässä offline (deterministinen, ~14s) ja predict-wc lataa valmiin JSONin.

Aja AINA datan virkistyksen jälkeen:
    python -m scripts.update_international_results
    python -m scripts.build_wc_model
    git add data/international_results.csv data/wc_model.json && commit + deploy
"""
from __future__ import annotations

import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from src.data.international_results import (
    lataa, save_wc_model,
    COMPETITION_WEIGHTS, DEFAULT_COMPETITION_WEIGHT,
    DEFAULT_WINDOW_START, DEFAULT_INCLUDE, WC_FIT_DECAY, WC_FIT_BAYES,
    WC_MODEL_PATH,
)
from src.models.dixon_coles import DixonColesModel


def main() -> int:
    df = lataa(window_start=DEFAULT_WINDOW_START, include=DEFAULT_INCLUDE)
    print(f"Treenidata: {len(df)} ottelua, "
          f"{len(set(df['home_team']) | set(df['away_team']))} maata "
          f"(window={DEFAULT_WINDOW_START}, include={DEFAULT_INCLUDE})")
    t0 = time.time()
    dc = DixonColesModel(per_team_home_adv=False).fit(
        df, decay=WC_FIT_DECAY, date_col="date",
        l2_attack_defence=WC_FIT_BAYES, shrink_defence_to_mean=True,
        competition_col="tournament", competition_weights=COMPETITION_WEIGHTS,
        default_competition_weight=DEFAULT_COMPETITION_WEIGHT,
    )
    el = time.time() - t0
    meta = {
        "source": "martj42/international_results (CC0)",
        "window_start": DEFAULT_WINDOW_START,
        "include": DEFAULT_INCLUDE,
        "decay": WC_FIT_DECAY,
        "bayes_shrinkage": WC_FIT_BAYES,
        "n_train_matches": len(df),
        "n_teams": len(dc.teams_),
        "fit_seconds": round(el, 2),
    }
    save_wc_model(dc, meta)
    print(f"Fit {el:.1f}s → tallennettu {WC_MODEL_PATH}")
    print(f"meta: {meta}")
    # Sanity
    import copy
    d = copy.copy(dc); h = dc.home_advantage / 2.0
    d.defence = {t: v + h for t, v in dc.defence.items()}
    d.home_advantage = 0.0
    d.home_advantage_per_team = {t: 0.0 for t in dc.teams_}
    for hh, aa in [("Brazil", "South Korea"), ("Argentina", "Curaçao")]:
        p = d.predict_1x2(hh, aa)
        print(f"  sanity {hh} vs {aa}: 1={p['home']:.2f} X={p['draw']:.2f} 2={p['away']:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
