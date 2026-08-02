"""
PL:n kotietu-kalibraation walk-forward-backtest (2.8.2026).

Kysymys: BSA:ssa malli ennusti keskimaarin koti 48 % / tasuri 24 %, toteuma
23 % / 46 % (n=26, Brier 0.698 > uniform 0.667). Onko sama kotietu-ylikalibraatio
olemassa PL:ssa, jonka 380 ennustetta alkavat gradautua julkisesti 21.8.2026?

Replikoi TUOTANNON polun tasmalleen:
  /api/predict -> _fit_malli() -> DixonColesModel(per_team_home_adv=True).fit(
      lataa_otteludata([liiga], current_season_pair()),
      decay=0.0035, l2_attack_defence=2.0)
  -> taydenna_nousijat() -> dc.predict_1x2()
Ei kalibraatiokerrosta, ei LGB-ensemblea (verifioitu api/main.py:1507-1540).

Walk-forward: ennusta kauden 25/26 jokainen ottelu mallilla joka on sovitettu
VAIN sita edeltavalla datalla (treeni-ikkuna = 24/25 + kuluva kausi siihen asti).
Refit viikoittain = realistinen kadenssi.
"""
from __future__ import annotations

import sys
import json
import argparse
import numpy as np
import pandas as pd

sys.path.insert(0, r"C:\users\vvsaa\documents\football-prediction")

from src.data.loader import lataa_otteludata
from src.models.dixon_coles import DixonColesModel
from src.models.promoted_baseline import taydenna_nousijat

PROD_DECAY = 0.0035
PROD_L2 = 2.0


def fit_prod(train: pd.DataFrame, decay: float, l2: float,
             per_team_home_adv: bool, liigat, kaudet) -> DixonColesModel:
    dc = DixonColesModel(per_team_home_adv=per_team_home_adv).fit(
        train,
        home_team_col="home_team", away_team_col="away_team",
        home_goals_col="home_score", away_goals_col="away_score",
        decay=decay, date_col="date",
        l2_attack_defence=l2,
        shrink_defence_to_mean=False,
    )
    try:
        taydenna_nousijat(dc, tuple(liigat), tuple(kaudet))
    except Exception as e:
        print(f"  [promoted] ohitettu: {type(e).__name__}: {e}")
    return dc


def walk_forward(df: pd.DataFrame, test_season: str, decay: float, l2: float,
                 per_team_home_adv: bool, liigat, kaudet,
                 refit_days: int = 7) -> pd.DataFrame:
    df = df.sort_values("date").reset_index(drop=True)
    test_idx = df.index[df["season"] == test_season]
    if len(test_idx) == 0:
        raise SystemExit(f"Ei otteluita kaudelle {test_season}")

    rows = []
    dc = None
    last_fit = None
    skipped = 0

    for i in test_idx:
        m = df.iloc[i]
        train = df.iloc[:i]
        if len(train) < 100:
            continue
        if dc is None or last_fit is None or (m["date"] - last_fit).days >= refit_days:
            dc = fit_prod(train, decay, l2, per_team_home_adv, liigat, kaudet)
            last_fit = m["date"]
        try:
            p = dc.predict_1x2(m["home_team"], m["away_team"])
        except ValueError:
            skipped += 1
            continue
        h, a = int(m["home_score"]), int(m["away_score"])
        rows.append({
            "date": m["date"], "home_team": m["home_team"], "away_team": m["away_team"],
            "home_score": h, "away_score": a,
            "p_home": p["home"], "p_draw": p["draw"], "p_away": p["away"],
            "actual": 0 if h > a else (1 if h == a else 2),
        })
    if skipped:
        print(f"  ohitettu tuntemattoman joukkueen takia: {skipped}")
    return pd.DataFrame(rows)


def metrics(bt: pd.DataFrame) -> dict:
    y = bt["actual"].values
    p = np.clip(bt[["p_home", "p_draw", "p_away"]].values, 1e-10, 1 - 1e-10)
    pred = p.argmax(axis=1)
    onehot = np.eye(3)[y]
    uniform = np.full_like(p, 1 / 3)
    return {
        "n": int(len(bt)),
        "acc": float((pred == y).mean()),
        "brier": float(np.mean(np.sum((p - onehot) ** 2, axis=1))),
        "brier_uniform": float(np.mean(np.sum((uniform - onehot) ** 2, axis=1))),
        "logloss": float(-np.mean(np.log(p[np.arange(len(y)), y]))),
        # Kotietu-diagnostiikka: ennustettu vs toteutunut osuus per luokka
        "pred_home": float(p[:, 0].mean()), "act_home": float((y == 0).mean()),
        "pred_draw": float(p[:, 1].mean()), "act_draw": float((y == 1).mean()),
        "pred_away": float(p[:, 2].mean()), "act_away": float((y == 2).mean()),
        "pick_home_share": float((pred == 0).mean()),
        "pick_draw_share": float((pred == 1).mean()),
    }


def fmt(label: str, m: dict) -> str:
    return (
        f"{label:<22} n={m['n']:>3}  acc={m['acc']:.3f}  brier={m['brier']:.4f} "
        f"(uniform {m['brier_uniform']:.4f})  logloss={m['logloss']:.4f}\n"
        f"{'':<22} koti  ennustettu {m['pred_home']:.3f} / toteuma {m['act_home']:.3f}"
        f"   tasuri {m['pred_draw']:.3f} / {m['act_draw']:.3f}"
        f"   vieras {m['pred_away']:.3f} / {m['act_away']:.3f}\n"
        f"{'':<22} kotipickeja {m['pick_home_share']:.1%}, tasuripickeja {m['pick_draw_share']:.1%}"
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--league", default="ENG-Premier League")
    ap.add_argument("--seasons", default="2425,2526")
    ap.add_argument("--test-season", default="2526")
    ap.add_argument("--decays", default=str(PROD_DECAY))
    ap.add_argument("--no-per-team-home-adv", action="store_true")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    liigat = [args.league]
    kaudet = args.seasons.split(",")
    df = lataa_otteludata(liigat, kaudet)
    df["date"] = pd.to_datetime(df["date"])
    print(f"{args.league}: {len(df)} ottelua, kaudet {sorted(df['season'].unique())}")

    results = {}
    for decay in [float(d) for d in args.decays.split(",")]:
        half_life = np.log(2) / decay if decay > 0 else float("inf")
        label = f"decay={decay:.4f}"
        print(f"\n=== {label} (puoliintumisaika {half_life:.0f} pv) ===")
        bt = walk_forward(df, args.test_season, decay, PROD_L2,
                          not args.no_per_team_home_adv, liigat, kaudet)
        m = metrics(bt)
        results[label] = m
        print(fmt(label, m))

        # Kuukausierittely: nakyyko drift kauden alussa
        bt["kk"] = bt["date"].dt.to_period("M").astype(str)
        print(f"\n  {'kk':<9}{'n':>4}{'acc':>7}{'brier':>8}{'p_home':>9}{'act_home':>10}")
        for kk, g in bt.groupby("kk"):
            if len(g) < 5:
                continue
            gm = metrics(g)
            print(f"  {kk:<9}{gm['n']:>4}{gm['acc']:>7.3f}{gm['brier']:>8.4f}"
                  f"{gm['pred_home']:>9.3f}{gm['act_home']:>10.3f}")

        if args.out:
            bt.to_csv(f"{args.out}_{decay:.4f}.csv", index=False)

    if len(results) > 1:
        print("\n=== YHTEENVETO ===")
        for label, m in results.items():
            print(f"{label:<18} acc={m['acc']:.3f} brier={m['brier']:.4f} "
                  f"logloss={m['logloss']:.4f} p_home={m['pred_home']:.3f} "
                  f"(toteuma {m['act_home']:.3f})")

    if args.out:
        with open(f"{args.out}_summary.json", "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)


if __name__ == "__main__":
    main()
