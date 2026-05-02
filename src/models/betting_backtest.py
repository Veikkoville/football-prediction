"""Vetokerroin-ROI backtest historiallisilla Bet365 / Pinnacle -kertoimilla."""

from __future__ import annotations
import numpy as np
import pandas as pd

from src.models.dixon_coles import DixonColesModel


def aja_vetokerroin_roi(
    matches: pd.DataFrame,
    min_train_size: int = 380,
    refit_every_days: int = 14,
    decay: float = 0.0065,
    value_threshold: float = 0.05,
    kelly_kerroin: float = 0.25,
    panostustyyli: str = "kelly",  # "kelly" tai "flat"
    odds_lahde: str = "odds_home",  # B365 = odds_home, Pinnacle = ps_home
    progress_callback=None,
) -> pd.DataFrame:
    """
    Walk-forward simulaatio: olisiko malli tehnyt rahaa historiallisilla kertoimilla?

    Logiikka:
      - Joka ottelulle ennusta 1X2 (vain edellinen data)
      - Vertaa Bet365/Pinnacle-kertoimiin
      - Jos value > value_threshold ja Kelly > 0, panosta
      - Talleta voitto/tappio per veto

    Palauttaa DataFramen jossa rivit per panostus.
    """
    df = matches.dropna(subset=["home_score", "away_score"]).copy()
    df["date"] = pd.to_datetime(df["date"])

    # Valitse kerroinsarakkeet
    if odds_lahde == "ps_home":
        oc = ["ps_home", "ps_draw", "ps_away"]
    else:
        oc = ["odds_home", "odds_draw", "odds_away"]

    # Vain rivit joilla on kertoimet
    df = df.dropna(subset=oc).copy()
    df = df.sort_values("date").reset_index(drop=True)

    if len(df) <= min_train_size:
        return pd.DataFrame()

    rivit = []
    last_fit_date = None
    dc = None

    for i in range(min_train_size, len(df)):
        ottelu = df.iloc[i]
        train = df.iloc[:i]

        if (dc is None or last_fit_date is None
                or (ottelu["date"] - last_fit_date).days >= refit_every_days):
            dc = DixonColesModel().fit(
                train, decay=decay, date_col="date",
            )
            last_fit_date = ottelu["date"]

        try:
            p = dc.predict_1x2(ottelu["home_team"], ottelu["away_team"])
        except ValueError:
            continue

        # Markkinakertoimet
        odds = {
            "home": float(ottelu[oc[0]]),
            "draw": float(ottelu[oc[1]]),
            "away": float(ottelu[oc[2]]),
        }
        # Toteuma
        h_g, a_g = int(ottelu["home_score"]), int(ottelu["away_score"])
        actual = "home" if h_g > a_g else ("draw" if h_g == a_g else "away")

        # Etsi value-vedot
        for valinta in ["home", "draw", "away"]:
            value = p[valinta] * odds[valinta] - 1.0
            if value <= value_threshold:
                continue
            # Kelly-fraktio
            b = odds[valinta] - 1.0
            f_kelly = (b * p[valinta] - (1 - p[valinta])) / b
            if f_kelly <= 0:
                continue
            panos = kelly_kerroin * f_kelly if panostustyyli == "kelly" else 1.0
            voitti = (valinta == actual)
            tuotto = panos * (odds[valinta] - 1.0) if voitti else -panos
            rivit.append({
                "date": ottelu["date"],
                "home_team": ottelu["home_team"],
                "away_team": ottelu["away_team"],
                "tulos": f"{h_g}-{a_g}",
                "valinta": valinta,
                "kerroin": odds[valinta],
                "mallin_p": p[valinta],
                "value": value,
                "kelly_fraktio": f_kelly,
                "panos": panos,
                "tuotto": tuotto,
                "voitti": voitti,
            })

        if progress_callback is not None:
            progress_callback(i - min_train_size + 1, len(df) - min_train_size)

    return pd.DataFrame(rivit)


def laske_roi_metriikat(panostukset: pd.DataFrame) -> dict:
    if panostukset.empty:
        return {"n_panoksia": 0, "voittoprosentti": 0.0, "kokonaistuotto": 0.0,
                "kokonaispanos": 0.0, "roi_pct": 0.0,
                "max_drawdown": 0.0}
    n = len(panostukset)
    voitot = panostukset["voitti"].sum()
    voittop = voitot / n
    kok_panos = panostukset["panos"].sum()
    kok_tuotto = panostukset["tuotto"].sum()
    roi = kok_tuotto / kok_panos * 100 if kok_panos > 0 else 0.0
    kum_tuotto = panostukset["tuotto"].cumsum()
    drawdown = (kum_tuotto - kum_tuotto.cummax()).min()
    return {
        "n_panoksia": int(n),
        "voittoprosentti": float(voittop * 100),
        "kokonaispanos": float(kok_panos),
        "kokonaistuotto": float(kok_tuotto),
        "roi_pct": float(roi),
        "max_drawdown": float(drawdown),
    }
