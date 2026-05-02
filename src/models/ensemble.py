"""
Ensemble: Dixon-Coles + LightGBM yhdistetty 1X2-ennuste.

Yksinkertainen painotettu keskiarvo. Painot voi optimoida validointijoukolla,
mutta 50/50 on yllättävän hyvä lähtötaso (Wisdom of Crowds).
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def yhdista_1x2(
    p_dixon: dict[str, float],
    p_lgbm: np.ndarray,
    paino_dixon: float = 0.5,
) -> dict[str, float]:
    """
    Yhdista Dixon-Colesin ja LightGBMin 1X2-todennakoisyydet.

    `p_dixon` on dict {"home", "draw", "away"} → todennäköisyys.
    `p_lgbm` on numpy-array [p_home, p_draw, p_away] (LightGBMin ulosto).
    `paino_dixon` ∈ [0, 1]: paino Dixon-Colesille (loput LightGBMille).
    """
    paino_lgbm = 1.0 - paino_dixon
    home = paino_dixon * p_dixon["home"] + paino_lgbm * float(p_lgbm[0])
    draw = paino_dixon * p_dixon["draw"] + paino_lgbm * float(p_lgbm[1])
    away = paino_dixon * p_dixon["away"] + paino_lgbm * float(p_lgbm[2])
    # Normalisoi numeerisen virheen varalta
    s = home + draw + away
    return {"home": home / s, "draw": draw / s, "away": away / s}


def rakenna_lgbm_features(
    ottelutaso: pd.DataFrame,
    home_team: str,
    away_team: str,
    feature_cols: list[str],
) -> pd.DataFrame | None:
    """
    Hae viimeinen rivi joukkueparista LightGBM-ennustetta varten.

    Jos joukkueet ovat pelanneet `ottelutaso`-DataFramessa, palautetaan
    yhden rivin DataFrame piirteistä. Muuten None — silloin ei voi tehdä
    LGB-ennustetta tälle parille.
    """
    paari = ottelutaso[
        (ottelutaso["home_team"] == home_team) & (ottelutaso["away_team"] == away_team)
    ]
    if paari.empty:
        # Käytä yleisimpiä rolling-arvoja (joukkueen viimeiset arvot eri ottelusta)
        return None
    return paari.tail(1)[feature_cols].copy()


def optimoi_paino_walk_forward(
    treenidata: pd.DataFrame,
    decay: float = 0.0035,
    bayes_shrinkage: float = 2.0,
    n_folds: int = 6,
    min_train_size: int = 300,
    progress_callback=None,
) -> tuple[float, dict[float, float], int]:
    """
    Etsi optimaalinen ensemble-paino walk-forward-CV:lla.

    Jakaa datan N foldiin temporaalisesti, sovittaa DC + LGB jokaisessa
    foldissa edeltavalla datalla ja kerää OOS-ennusteet. Etsii painon
    [0, 1] joka minimoi yhdistetyn log-lossin.

    Palauttaa: (paras_paino, log_loss_per_paino, n_oos_ennusteita)
    """
    from sklearn.metrics import log_loss
    from src.models.dixon_coles import DixonColesModel
    from src.models.outcome_model import opeta_1x2
    from src.features.team_features import (
        laajenna_per_joukkue, rolling_keskiarvo,
        yhdista_ottelutasolle, lisaa_1x2,
    )

    df = treenidata.dropna(subset=["home_score", "away_score"]).copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)

    if len(df) < min_train_size + 50:
        raise ValueError(
            f"Liian vahan dataa walk-forwardiin "
            f"(tarvitaan vahintaan {min_train_size + 50}, sain {len(df)})."
        )

    test_alue = df.iloc[min_train_size:].reset_index(drop=True)
    fold_size = max(20, len(test_alue) // n_folds)

    all_p_dc: list[list[float]] = []
    all_p_lgb: list[list[float]] = []
    all_y: list[int] = []

    for fold_idx in range(n_folds):
        if progress_callback:
            progress_callback(fold_idx, n_folds)

        fold_start = fold_idx * fold_size
        fold_end = (fold_idx + 1) * fold_size
        last_train_idx = min_train_size + fold_start
        train = df.iloc[:last_train_idx]
        test = test_alue.iloc[fold_start:fold_end]

        if len(train) < min_train_size or len(test) == 0:
            continue

        # Sovita DC tahan foldiin
        try:
            dc = DixonColesModel().fit(
                train, decay=decay, date_col="date",
                l2_attack_defence=bayes_shrinkage,
            )
        except Exception:
            continue

        # Sovita LGB Understat-osasta
        train_us = train[train["home_xg"].notna()]
        if len(train_us) < 100:
            continue

        try:
            joukkue_ottelu = laajenna_per_joukkue(train_us)
            joukkue_ottelu["xg_for"] = np.where(
                joukkue_ottelu["is_home"] == 1,
                joukkue_ottelu["home_xg"], joukkue_ottelu["away_xg"])
            joukkue_ottelu["xg_against"] = np.where(
                joukkue_ottelu["is_home"] == 1,
                joukkue_ottelu["away_xg"], joukkue_ottelu["home_xg"])
            piirteet = ["goals_for", "goals_against", "xg_for", "xg_against"]
            joukkue_ottelu = rolling_keskiarvo(joukkue_ottelu, piirteet, ikkuna=5)
            rolling_cols = [f"{p}_rolling5" for p in piirteet]
            ottelutaso = yhdista_ottelutasolle(joukkue_ottelu, rolling_cols)
            ottelutaso = lisaa_1x2(ottelutaso)
            feature_cols = [c for c in ottelutaso.columns if "rolling5" in c]
            ot_train = ottelutaso.dropna(subset=feature_cols)
            if len(ot_train) < 50:
                continue
            lgb_model = opeta_1x2(
                ot_train[feature_cols], ot_train["result_1x2"], num_boost_round=200,
            )
            viimeisimmat = (
                joukkue_ottelu.dropna(subset=rolling_cols)
                .sort_values("date").groupby("team")
                .tail(1)[["team"] + rolling_cols].set_index("team")
            )
        except Exception:
            continue

        # OOS-ennusteet test-otteluille
        for _, row in test.iterrows():
            koti, vieras = row["home_team"], row["away_team"]
            if koti not in dc.attack or vieras not in dc.attack:
                continue
            if koti not in viimeisimmat.index or vieras not in viimeisimmat.index:
                continue

            try:
                p_dc_dict = dc.predict_1x2(koti, vieras)
                p_dc = [p_dc_dict["home"], p_dc_dict["draw"], p_dc_dict["away"]]

                h = viimeisimmat.loc[koti].add_prefix("home_")
                a = viimeisimmat.loc[vieras].add_prefix("away_")
                rivi_lgb = pd.concat([h, a]).to_frame().T
                if not all(c in rivi_lgb.columns for c in feature_cols):
                    continue
                p_lgb_arr = lgb_model.predict(rivi_lgb[feature_cols])[0]
                p_lgb = [float(p_lgb_arr[0]), float(p_lgb_arr[1]), float(p_lgb_arr[2])]
            except Exception:
                continue

            h_g, a_g = int(row["home_score"]), int(row["away_score"])
            if h_g > a_g:
                y = 0
            elif h_g == a_g:
                y = 1
            else:
                y = 2

            all_p_dc.append(p_dc)
            all_p_lgb.append(p_lgb)
            all_y.append(y)

    if progress_callback:
        progress_callback(n_folds, n_folds)

    if len(all_y) < 20:
        raise ValueError(
            f"Liian vahan OOS-ennusteita ({len(all_y)}). Kokeile pienempaa "
            f"min_train_size:a tai laajempaa datasettia."
        )

    p_dc_arr = np.array(all_p_dc)
    p_lgb_arr = np.array(all_p_lgb)
    y_arr = np.array(all_y)

    painot = np.arange(0.0, 1.01, 0.05)
    log_lossit: dict[float, float] = {}
    for w in painot:
        p_ens = w * p_dc_arr + (1.0 - w) * p_lgb_arr
        s = p_ens.sum(axis=1, keepdims=True)
        p_ens = p_ens / np.where(s > 0, s, 1.0)
        ll = log_loss(y_arr, p_ens, labels=[0, 1, 2])
        log_lossit[round(float(w), 2)] = float(ll)

    paras_paino = min(log_lossit, key=log_lossit.get)
    return float(paras_paino), log_lossit, len(all_y)
