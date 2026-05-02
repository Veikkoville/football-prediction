"""Optuna-pohjainen LightGBM-hyperparametrien optimointi."""

from __future__ import annotations
import numpy as np
import pandas as pd


def tune_lgbm_1x2(
    X_train: pd.DataFrame, y_train: pd.Series,
    X_valid: pd.DataFrame, y_valid: pd.Series,
    n_trials: int = 30,
    timeout_s: int = 120,
) -> dict:
    """
    Etsi optimaaliset LightGBM-hyperparametrit Tree-structured
    Parzen Estimator -menetelmalla. Minimoidaan validointi log loss.

    Palauttaa parhaat parametrit dict:na.
    """
    import lightgbm as lgb
    from sklearn.metrics import log_loss
    try:
        import optuna
    except ImportError:
        raise ImportError(
            "Optuna ei asennettuna. Aja: pip install optuna"
        )

    def objective(trial):
        params = {
            "objective": "multiclass",
            "num_class": 3,
            "verbose": -1,
            "metric": "multi_logloss",
            "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.1, log=True),
            "num_leaves": trial.suggest_int("num_leaves", 7, 63),
            "max_depth": trial.suggest_int("max_depth", 3, 10),
            "min_data_in_leaf": trial.suggest_int("min_data_in_leaf", 5, 100),
            "feature_fraction": trial.suggest_float("feature_fraction", 0.5, 1.0),
            "bagging_fraction": trial.suggest_float("bagging_fraction", 0.5, 1.0),
            "bagging_freq": trial.suggest_int("bagging_freq", 1, 10),
            "lambda_l1": trial.suggest_float("lambda_l1", 0.0, 1.0),
            "lambda_l2": trial.suggest_float("lambda_l2", 0.0, 1.0),
        }
        train_set = lgb.Dataset(X_train, label=y_train)
        val_set = lgb.Dataset(X_valid, label=y_valid, reference=train_set)
        booster = lgb.train(
            params, train_set,
            num_boost_round=500,
            valid_sets=[val_set],
            valid_names=["valid"],
            callbacks=[lgb.early_stopping(stopping_rounds=20, verbose=False),
                       lgb.log_evaluation(period=0)],
        )
        preds = booster.predict(X_valid)
        return log_loss(y_valid, preds)

    optuna.logging.set_verbosity(optuna.logging.WARNING)
    sampler = optuna.samplers.TPESampler(seed=42)
    study = optuna.create_study(direction="minimize", sampler=sampler)
    study.optimize(objective, n_trials=n_trials, timeout=timeout_s, show_progress_bar=False)
    return study.best_params
