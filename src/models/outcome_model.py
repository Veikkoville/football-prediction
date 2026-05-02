"""
Gradient Boosting -malli ottelutulokselle (1X2) ja Over/Under -markkinalle.

Vaihtoehtoinen lähestymistapa Dixon-Colesille: käytetään rolling-form
-piirteitä (xG-keskiarvot jne.) ja annetaan LightGBM:n löytää
epälineaariset yhteydet.

Hyödyt:
  - Hyväksyy rikkaita piirteitä (PPDA, hallinta, lepopäivät, ...)
  - Käsittelee NaN-arvoja natiivisti

Haitat:
  - Tarvitsee enemmän dataa kuin Poisson
  - Vähemmän tulkittava

Käytä molempia ja vertaa! Markkinan mestarit usein **ensembloivat** Poissonin
ja gradient boostingin.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import log_loss


def opeta_1x2(
    X: pd.DataFrame,
    y: pd.Series,
    val_X: pd.DataFrame | None = None,
    val_y: pd.Series | None = None,
    params: dict | None = None,
    num_boost_round: int = 500,
):
    """
    Opeta LightGBM-malli 1X2-luokitteluun.

    `y` arvot: 0 = koti, 1 = tasapeli, 2 = vieras.
    """
    import lightgbm as lgb

    # Optuna-tuned parametrit (PL 2223+2324+2425+2526 = 4 kautta, 50 trialia, 240s)
    oletus = {
        "objective": "multiclass",
        "num_class": 3,
        "learning_rate": 0.03737805455830732,
        "num_leaves": 13,
        "max_depth": 10,
        "min_data_in_leaf": 79,
        "feature_fraction": 0.5984471153710615,
        "bagging_fraction": 0.6731445472824136,
        "bagging_freq": 4,
        "lambda_l1": 0.06080841965365072,
        "lambda_l2": 0.6226717376701515,
        "verbose": -1,
        "metric": "multi_logloss",
    }
    if params:
        oletus.update(params)

    train_set = lgb.Dataset(X, label=y)
    valid_sets = [train_set]
    valid_names = ["train"]
    if val_X is not None:
        val_set = lgb.Dataset(val_X, label=val_y, reference=train_set)
        valid_sets.append(val_set)
        valid_names.append("valid")

    callbacks = [lgb.log_evaluation(period=0)]
    if val_X is not None:
        callbacks.append(lgb.early_stopping(stopping_rounds=30, verbose=False))

    model = lgb.train(
        oletus,
        train_set,
        num_boost_round=num_boost_round,
        valid_sets=valid_sets,
        valid_names=valid_names,
        callbacks=callbacks,
    )
    return model


def opeta_over_under(
    X: pd.DataFrame,
    total_goals: pd.Series,
    line: float = 2.5,
    val_X: pd.DataFrame | None = None,
    val_total_goals: pd.Series | None = None,
    params: dict | None = None,
    num_boost_round: int = 500,
):
    """Opeta binäärinen luokitin Over/Under N maalia."""
    import lightgbm as lgb

    y = (total_goals > line).astype(int)
    val_y = None if val_total_goals is None else (val_total_goals > line).astype(int)

    oletus = {
        "objective": "binary",
        "learning_rate": 0.05,
        "num_leaves": 31,
        "metric": "binary_logloss",
        "verbose": -1,
    }
    if params:
        oletus.update(params)

    train_set = lgb.Dataset(X, label=y)
    valid_sets = [train_set]
    valid_names = ["train"]
    if val_X is not None:
        val_set = lgb.Dataset(val_X, label=val_y, reference=train_set)
        valid_sets.append(val_set)
        valid_names.append("valid")

    callbacks = [lgb.log_evaluation(period=0)]
    if val_X is not None:
        callbacks.append(lgb.early_stopping(stopping_rounds=30, verbose=False))

    model = lgb.train(
        oletus,
        train_set,
        num_boost_round=num_boost_round,
        valid_sets=valid_sets,
        valid_names=valid_names,
        callbacks=callbacks,
    )
    return model


def arvioi_kalibrointi(
    todennakoisyydet: np.ndarray,
    todelliset: np.ndarray,
    n_bins: int = 10,
) -> pd.DataFrame:
    """
    Reliability-diagrammin data: ennustetut vs. toteutuneet osuudet.

    Hyvin kalibroitu malli: ennustettu 60% → todellinen ~60%.
    """
    df = pd.DataFrame({"p": todennakoisyydet, "y": todelliset})
    df["bin"] = pd.cut(df["p"], np.linspace(0, 1, n_bins + 1), include_lowest=True)
    grouped = df.groupby("bin", observed=True).agg(
        ennustettu=("p", "mean"),
        toteutunut=("y", "mean"),
        n=("y", "count"),
    ).reset_index(drop=True)
    return grouped
