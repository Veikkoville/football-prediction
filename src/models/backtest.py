"""
Walk-forward -backtest Dixon-Coles -mallille.

Idea: jokaiselle ottelulle (jaoteltuna viikoittain) sovita malli VAIN
ottelua edeltävällä datalla, ennusta tulos, talleta ennusteet rinnan
toteutuneen tuloksen kanssa. Lopussa voidaan laskea log loss, accuracy,
Brier score ja kalibrointidata.

Tämä on hidas — Dixon-Coles sovittuu jokaiselle viikolle erikseen — mutta
tulos on rehellinen "olisivatko ennusteet olleet hyödyllisiä reaaliajassa".
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.models.dixon_coles import DixonColesModel


def walk_forward_dixon_coles(
    matches: pd.DataFrame,
    home_team_col: str = "home_team",
    away_team_col: str = "away_team",
    home_goals_col: str = "home_score",
    away_goals_col: str = "away_score",
    date_col: str = "date",
    min_train_size: int = 100,
    refit_every_days: int = 7,
    decay: float = 0.0065,
    progress_callback=None,
) -> pd.DataFrame:
    """
    Aja walk-forward -backtest.

    Parametrit
    ----------
    min_train_size : int
        Vähimmäismäärä otteluita ennen kuin aloitetaan ennustaminen.
    refit_every_days : int
        Sovita malli uudelleen näin monen päivän välein
        (joka päivä = liian hidas, viikon välein on hyvä kompromissi).
    progress_callback : callable, optional
        Kutsutaan etenemispalkkia varten: cb(current, total).

    Palauttaa DataFramen, jossa jokaiselle ennustetulle ottelulle:
      ``date``, ``home_team``, ``away_team``, ``home_score``, ``away_score``,
      ``p_home``, ``p_draw``, ``p_away``, ``actual_1x2``.
    """
    df = matches.dropna(subset=[home_goals_col, away_goals_col]).copy()
    df[date_col] = pd.to_datetime(df[date_col])
    df = df.sort_values(date_col).reset_index(drop=True)

    rivit = []
    last_fit_date = None
    malli = None

    for i in range(min_train_size, len(df)):
        ottelu = df.iloc[i]
        train = df.iloc[:i]

        # Sovita malli vain refit_every_days välein nopeuden vuoksi
        if (
            malli is None
            or last_fit_date is None
            or (ottelu[date_col] - last_fit_date).days >= refit_every_days
        ):
            malli = DixonColesModel().fit(
                train,
                home_team_col=home_team_col,
                away_team_col=away_team_col,
                home_goals_col=home_goals_col,
                away_goals_col=away_goals_col,
                decay=decay,
                date_col=date_col,
            )
            last_fit_date = ottelu[date_col]

        # Ennusta jos molemmat joukkueet ovat datassa
        try:
            p = malli.predict_1x2(ottelu[home_team_col], ottelu[away_team_col])
        except ValueError:
            continue  # Tuntematon joukkue (uusi nousija)

        h_g = int(ottelu[home_goals_col])
        a_g = int(ottelu[away_goals_col])
        actual = 0 if h_g > a_g else (1 if h_g == a_g else 2)

        rivit.append({
            "date": ottelu[date_col],
            "home_team": ottelu[home_team_col],
            "away_team": ottelu[away_team_col],
            "home_score": h_g,
            "away_score": a_g,
            "p_home": p["home"],
            "p_draw": p["draw"],
            "p_away": p["away"],
            "actual_1x2": actual,
        })

        if progress_callback is not None:
            progress_callback(i - min_train_size + 1, len(df) - min_train_size)

    return pd.DataFrame(rivit)


def laske_metriikat(backtest: pd.DataFrame) -> dict:
    """Log loss, accuracy ja Brier score backtestin tuloksista."""
    if backtest.empty:
        return {"log_loss": float("nan"), "accuracy": float("nan"), "brier": float("nan"), "n": 0}

    y = backtest["actual_1x2"].values
    p = backtest[["p_home", "p_draw", "p_away"]].values
    p = np.clip(p, 1e-10, 1 - 1e-10)

    # Log loss
    log_loss = -np.mean(np.log(p[np.arange(len(y)), y]))

    # Accuracy
    pred = p.argmax(axis=1)
    accuracy = (pred == y).mean()

    # Multi-class Brier
    one_hot = np.eye(3)[y]
    brier = np.mean(np.sum((p - one_hot) ** 2, axis=1))

    return {
        "log_loss": float(log_loss),
        "accuracy": float(accuracy),
        "brier": float(brier),
        "n": int(len(backtest)),
    }


def kalibrointi_data(backtest: pd.DataFrame, n_bins: int = 10) -> pd.DataFrame:
    """
    Reliability-diagrammin data: ennustetut vs. toteutuneet osuudet.

    Yhdistetään kaikki kolme luokkaa (1, X, 2) yhdeksi data-aineistoksi.
    """
    if backtest.empty:
        return pd.DataFrame(columns=["bin_mid", "ennustettu", "toteutunut", "n"])

    p_array = backtest[["p_home", "p_draw", "p_away"]].values.flatten()
    y = backtest["actual_1x2"].values
    one_hot = np.eye(3)[y].flatten()

    df = pd.DataFrame({"p": p_array, "y": one_hot})
    df["bin"] = pd.cut(df["p"], np.linspace(0, 1, n_bins + 1), include_lowest=True)
    grouped = (
        df.groupby("bin", observed=True)
        .agg(ennustettu=("p", "mean"), toteutunut=("y", "mean"), n=("y", "count"))
        .reset_index(drop=True)
    )
    grouped["bin_mid"] = grouped["ennustettu"]
    return grouped


def walk_forward_ensemble(
    matches: pd.DataFrame,
    home_team_col: str = "home_team",
    away_team_col: str = "away_team",
    home_goals_col: str = "home_score",
    away_goals_col: str = "away_score",
    home_xg_col: str = "home_xg",
    away_xg_col: str = "away_xg",
    date_col: str = "date",
    min_train_size: int = 380,
    refit_every_days: int = 14,
    decay: float = 0.0065,
    paino_dixon: float = 0.5,
    progress_callback=None,
) -> pd.DataFrame:
    """
    Walk-forward Ensemble (Dixon-Coles + LightGBM).

    Refit-pisteissa sovittaa molemmat mallit. Ennustaa ottelut painotettuna keskiarvona.
    Vaatii xG-piirteet (home_xg, away_xg) — toimii Understat-datalla.
    """
    from src.models.dixon_coles import DixonColesModel
    from src.models.outcome_model import opeta_1x2
    from src.models.ensemble import yhdista_1x2
    from src.features.team_features import (
        laajenna_per_joukkue, rolling_keskiarvo,
        yhdista_ottelutasolle, lisaa_1x2,
    )
    import numpy as np

    df = matches.dropna(subset=[home_goals_col, away_goals_col]).copy()
    df[date_col] = pd.to_datetime(df[date_col])
    df = df.sort_values(date_col).reset_index(drop=True)

    rivit = []
    last_fit_date = None
    dc = None
    lgb = None
    feature_cols = None
    viimeisimmat = None

    def _kouluta_lgb(train_df):
        try:
            jo = laajenna_per_joukkue(train_df)
            jo["xg_for"] = np.where(jo["is_home"] == 1, jo[home_xg_col], jo[away_xg_col])
            jo["xg_against"] = np.where(jo["is_home"] == 1, jo[away_xg_col], jo[home_xg_col])
            piirteet = ["goals_for", "goals_against", "xg_for", "xg_against"]
            jo = rolling_keskiarvo(jo, piirteet, ikkuna=5)
            rolling_cols = [f"{p}_rolling5" for p in piirteet]
            ott = yhdista_ottelutasolle(jo, rolling_cols)
            ott = lisaa_1x2(ott)
            fc = [c for c in ott.columns if "rolling5" in c]
            tr = ott.dropna(subset=fc)
            if len(tr) < 100:
                return None, None, None
            m = opeta_1x2(tr[fc], tr["result_1x2"], num_boost_round=200)
            vm = (jo.dropna(subset=rolling_cols).sort_values("date")
                    .groupby("team").tail(1)[["team"] + rolling_cols].set_index("team"))
            return m, fc, vm
        except Exception:
            return None, None, None

    for i in range(min_train_size, len(df)):
        ottelu = df.iloc[i]
        train = df.iloc[:i]

        if (
            dc is None or last_fit_date is None
            or (ottelu[date_col] - last_fit_date).days >= refit_every_days
        ):
            dc = DixonColesModel().fit(
                train, home_team_col=home_team_col, away_team_col=away_team_col,
                home_goals_col=home_goals_col, away_goals_col=away_goals_col,
                decay=decay, date_col=date_col,
            )
            us = train[train[home_xg_col].notna()].copy()
            if len(us) >= 100:
                lgb, feature_cols, viimeisimmat = _kouluta_lgb(us)
            last_fit_date = ottelu[date_col]

        try:
            p_dc = dc.predict_1x2(ottelu[home_team_col], ottelu[away_team_col])
        except ValueError:
            continue

        # Ensemble jos LGB:lla on rivit kummallekin joukkueelle
        p_kaytetty = p_dc
        if lgb is not None and viimeisimmat is not None:
            koti, vieras = ottelu[home_team_col], ottelu[away_team_col]
            if koti in viimeisimmat.index and vieras in viimeisimmat.index:
                h_row = viimeisimmat.loc[koti].add_prefix("home_")
                a_row = viimeisimmat.loc[vieras].add_prefix("away_")
                rivi = pd.concat([h_row, a_row]).to_frame().T
                if all(c in rivi.columns for c in feature_cols):
                    p_lgb = lgb.predict(rivi[feature_cols])[0]
                    p_kaytetty = yhdista_1x2(p_dc, p_lgb, paino_dixon=paino_dixon)

        h_g = int(ottelu[home_goals_col])
        a_g = int(ottelu[away_goals_col])
        actual = 0 if h_g > a_g else (1 if h_g == a_g else 2)

        rivit.append({
            "date": ottelu[date_col],
            "home_team": ottelu[home_team_col],
            "away_team": ottelu[away_team_col],
            "home_score": h_g, "away_score": a_g,
            "p_home": p_kaytetty["home"],
            "p_draw": p_kaytetty["draw"],
            "p_away": p_kaytetty["away"],
            "actual_1x2": actual,
        })

        if progress_callback is not None:
            progress_callback(i - min_train_size + 1, len(df) - min_train_size)

    return pd.DataFrame(rivit)
