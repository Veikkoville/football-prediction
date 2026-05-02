"""xG-pohjainen Over/Under classifier — erillinen LightGBM-binaariluokitin."""

from __future__ import annotations
import numpy as np
import pandas as pd

from src.features.team_features import (
    laajenna_per_joukkue, rolling_keskiarvo,
    yhdista_ottelutasolle, lisaa_total_goals,
)


def opeta_totals_classifier(
    matches: pd.DataFrame,
    line: float = 2.5,
    home_xg_col: str = "home_xg",
    away_xg_col: str = "away_xg",
):
    """
    Opeta LightGBM-binaariluokitin: yli vai alle line maalia.

    Kayttaa rolling xG-piirteita. Palauttaa (booster, feature_cols, viimeisimmat).
    """
    import lightgbm as lgb

    df = matches.dropna(subset=["home_score", "away_score", home_xg_col, away_xg_col]).copy()
    if len(df) < 100:
        return None, None, None

    jo = laajenna_per_joukkue(df)
    jo["xg_for"] = np.where(jo["is_home"] == 1, jo[home_xg_col], jo[away_xg_col])
    jo["xg_against"] = np.where(jo["is_home"] == 1, jo[away_xg_col], jo[home_xg_col])
    piirteet = ["goals_for", "goals_against", "xg_for", "xg_against"]
    jo = rolling_keskiarvo(jo, piirteet, ikkuna=5)
    rolling_cols = [f"{p}_rolling5" for p in piirteet]
    ott = yhdista_ottelutasolle(jo, rolling_cols)
    ott = lisaa_total_goals(ott)

    fc = [c for c in ott.columns if "rolling5" in c]
    train = ott.dropna(subset=fc)
    if len(train) < 100:
        return None, None, None

    y = (train["total_goals"] > line).astype(int)

    params = {
        "objective": "binary",
        "metric": "binary_logloss",
        "learning_rate": 0.04,
        "num_leaves": 15,
        "max_depth": 5,
        "min_data_in_leaf": 30,
        "feature_fraction": 0.8,
        "bagging_fraction": 0.8,
        "bagging_freq": 5,
        "lambda_l2": 0.3,
        "verbose": -1,
    }
    booster = lgb.train(
        params, lgb.Dataset(train[fc], label=y),
        num_boost_round=300,
    )
    viimeisimmat = (
        jo.dropna(subset=rolling_cols).sort_values("date")
        .groupby("team").tail(1)[["team"] + rolling_cols].set_index("team")
    )
    return booster, fc, viimeisimmat


def ennusta_totals(
    booster, feature_cols, viimeisimmat,
    home_team: str, away_team: str,
) -> float | None:
    """Palauttaa P(yli line). None jos joukkueita ei loydy."""
    if booster is None or viimeisimmat is None:
        return None
    if home_team not in viimeisimmat.index or away_team not in viimeisimmat.index:
        return None
    h = viimeisimmat.loc[home_team].add_prefix("home_")
    a = viimeisimmat.loc[away_team].add_prefix("away_")
    rivi = pd.concat([h, a]).to_frame().T
    if not all(c in rivi.columns for c in feature_cols):
        return None
    return float(booster.predict(rivi[feature_cols])[0])
