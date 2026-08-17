"""Mittaa kannattaako xG-painotus ottelumallissa (walk-forward).

Tausta (QUEUE MODEL-XG-WEIGHT, 17.8.2026): tuotannon `/api/predict` sovittaa
Dixon-Colesin PELKKIIN MAALEIHIN — `xg_weight` jaa oletukseen 0.0, vaikka
`DixonColesModel.fit` tukee xG-painotettua likelihoodia ja xG-data on repossa
jokaisella top-5-liigan ottelulla. Paremmuutta ei ollut mitattu kertaakaan,
koska `walk_forward_dixon_coles` ei ottanut xG-parametreja vastaan lainkaan
(lisatty samassa committissa).

Menetelma
---------
- Walk-forward per liiga erikseen (joukkueet eivat ristea liigojen yli).
- Fit-parametrit = TUOTANNON parametrit (`api/main.py:975`): decay 0.0035,
  l2_attack_defence 2.0, per_team_home_adv True, shrink_defence_to_mean False.
  Ainoa muuttuja on `xg_weight`, jotta ero on luettavissa sille eika
  sivuparametrille.
- Metriikat lasketaan POOLATUSTA ennustejoukosta, koska jokainen xg_weight
  ennustaa taysin saman ottelujoukon (sama data, sama min_train_size) —
  vertailu on siis parittainen.

Tulos kirjataan myos jos xG HAVIAA. Vrt. 8.8: laukausvolyymi testattiin ja
havisi, ja se tulos oli yhta arvokas kuin voitto olisi ollut.

Ajo:
    .venv/Scripts/python.exe scripts/backtest_xg_weight.py
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
from src.data.loader import lataa_otteludata  # noqa: E402
from src.models.backtest import (  # noqa: E402
    laske_metriikat,
    walk_forward_dixon_coles,
)

# Understat-liigat = ainoat joilla on ottelutason xG.
LEAGUES = [
    "ENG-Premier League",
    "ESP-La Liga",
    "GER-Bundesliga",
    "ITA-Serie A",
    "FRA-Ligue 1",
]
SEASONS = ["2324", "2425", "2526"]
WEIGHTS = [0.0, 0.5, 0.7]

# Tuotannon fit-parametrit (api/main.py:1039 defaultit).
PROD_DECAY = 0.0035
PROD_L2 = 2.0
PROD_PER_TEAM_HOME_ADV = True
PROD_SHRINK_DEFENCE = False

OUT_PATH = config.PROJECT_ROOT / "logs" / "xg_weight_backtest.json"


def aja_yksi(df: pd.DataFrame, xg_weight: float) -> pd.DataFrame:
    """Walk-forward kaikille liigoille yhdella xg_weightilla."""
    palat = []
    for liiga in sorted(df["league"].unique()):
        osa = df[df["league"] == liiga].copy()
        tulos = walk_forward_dixon_coles(
            osa,
            date_col="date",
            min_train_size=100,
            refit_every_days=7,
            decay=PROD_DECAY,
            l2_attack_defence=PROD_L2,
            per_team_home_adv=PROD_PER_TEAM_HOME_ADV,
            shrink_defence_to_mean=PROD_SHRINK_DEFENCE,
            home_xg_col="home_xg" if xg_weight > 0 else None,
            away_xg_col="away_xg" if xg_weight > 0 else None,
            xg_weight=xg_weight,
        )
        if not tulos.empty:
            tulos["league"] = liiga
            palat.append(tulos)
    return pd.concat(palat, ignore_index=True) if palat else pd.DataFrame()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--leagues", nargs="*", default=LEAGUES)
    ap.add_argument("--seasons", nargs="*", default=SEASONS)
    ap.add_argument("--weights", nargs="*", type=float, default=WEIGHTS)
    args = ap.parse_args()

    logging.disable(logging.INFO)
    print(f"Haetaan data: {len(args.leagues)} liigaa, kaudet {args.seasons}")
    df = lataa_otteludata(args.leagues, args.seasons)
    df = df[df["home_xg"].notna() & df["away_xg"].notna()].copy()
    print(f"  {len(df)} ottelua joilla xG (kaikki liigat)")

    tulokset: dict[str, dict] = {}
    ennusteet: dict[float, pd.DataFrame] = {}
    for w in args.weights:
        t0 = time.time()
        bt = aja_yksi(df, w)
        kesto = time.time() - t0
        m = laske_metriikat(bt)
        m["kesto_s"] = round(kesto, 1)
        m["per_league"] = {
            liiga: laske_metriikat(bt[bt["league"] == liiga])
            for liiga in sorted(bt["league"].unique())
        }
        # Konvergenssi: xG-termi vie optimoijan alueille joilla lam*mu ylivuotaa
        # (mitattu 17.8: 0 varoitusta baselinella, 9 kun xg_weight=0.5).
        # `fit` ottaa `result.x`:n riippumatta onnistumisesta, joten hajonnut
        # sovitus paatyisi tulokseen hiljaa ilman tata lukua.
        if "fit_converged" in bt.columns:
            ei_konv = int((~bt["fit_converged"]).sum())
            m["rivit_ei_konvergoituneesta_fitista"] = ei_konv
            m["konvergenssi_osuus"] = round(1.0 - ei_konv / max(len(bt), 1), 4)
        tulokset[str(w)] = m
        ennusteet[w] = bt
        print(f"xg_weight={w}: n={m['n']} log_loss={m['log_loss']:.5f} "
              f"brier={m['brier']:.5f} acc={m['accuracy']:.4f} ({kesto:.0f} s)"
              + (f" [EI-KONVERGOITUNEITA RIVEJA: {m['rivit_ei_konvergoituneesta_fitista']}]"
                 if m.get("rivit_ei_konvergoituneesta_fitista") else ""))

    # Parittainen vertailu baselineen (0.0). Sama ottelujoukko -> ero on aito.
    if 0.0 in ennusteet:
        base = ennusteet[0.0]
        for w, bt in ennusteet.items():
            if w == 0.0:
                continue
            yhteinen = base.merge(
                bt, on=["date", "home_team", "away_team"], suffixes=("_b", "_x"))
            if yhteinen.empty:
                continue
            y = yhteinen["actual_1x2_b"].values
            pb = np.clip(yhteinen[["p_home_b", "p_draw_b", "p_away_b"]].values, 1e-10, 1)
            px = np.clip(yhteinen[["p_home_x", "p_draw_x", "p_away_x"]].values, 1e-10, 1)
            ll_b = -np.log(pb[np.arange(len(y)), y])
            ll_x = -np.log(px[np.arange(len(y)), y])
            d = ll_x - ll_b
            # Parittainen t-tyylinen keskivirhe: onko ero erotettavissa nollasta.
            se = d.std(ddof=1) / np.sqrt(len(d))
            tulokset[str(w)]["vs_baseline"] = {
                "n_pari": int(len(d)),
                "log_loss_delta": float(d.mean()),
                "se": float(se),
                "t": float(d.mean() / se) if se > 0 else float("nan"),
                "parempi": bool(d.mean() < 0),
            }
            print(f"  {w} vs 0.0: delta_log_loss={d.mean():+.5f} "
                  f"(se {se:.5f}, t {d.mean()/se:+.2f}, n={len(d)})")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps({
        "leagues": args.leagues,
        "seasons": args.seasons,
        "fit": {
            "decay": PROD_DECAY,
            "l2_attack_defence": PROD_L2,
            "per_team_home_adv": PROD_PER_TEAM_HOME_ADV,
            "shrink_defence_to_mean": PROD_SHRINK_DEFENCE,
        },
        "tulokset": tulokset,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nKirjoitettu: {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
