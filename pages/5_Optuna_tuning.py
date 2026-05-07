"""LightGBM-hyperparametrien automaattinen optimointi Optunan avulla."""

from __future__ import annotations
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np
import pandas as pd
import streamlit as st

import config
from src.data.loader import lataa_otteludata
from src.features.team_features import (
    laajenna_per_joukkue, rolling_keskiarvo, yhdista_ottelutasolle, lisaa_1x2,
)
from src.models.optuna_tune import tune_lgbm_1x2

st.set_page_config(page_title="Optuna tuning", page_icon="🔧", layout="wide")
st.title("🔧 LightGBM hyperparameter optimization")
st.caption(
    "Optuna searches for the best hyperparameters by minimizing validation log loss. "
    "Run this once when you want extra performance — use the resulting parameters "
    "on the Ensemble page."
)

st.sidebar.header("Data selection")
liigat = st.sidebar.multiselect(
    "Leagues (Top-5 only — xG required)",
    options=["ENG-Premier League", "ESP-La Liga", "GER-Bundesliga", "ITA-Serie A", "FRA-Ligue 1"],
    default=["ENG-Premier League"],
)
kaudet = st.sidebar.multiselect(
    "Seasons", options=["2122", "2223", "2324", "2425", "2526"],
    default=["2324", "2425"],
)
n_trials = st.sidebar.slider("Optuna trials", 10, 100, 30, 5,
                             help="More = better result but slower.")
timeout_s = st.sidebar.slider("Timeout (seconds)", 30, 600, 120, 30)

if not liigat or not kaudet:
    st.warning("Select league + season.")
    st.stop()

if st.button("▶️ Run Optuna tuning", type="primary"):
    with st.spinner("Loading data..."):
        treenidata = lataa_otteludata(list(liigat), list(kaudet))
        treenidata = treenidata[treenidata["home_xg"].notna()].copy()
        if treenidata.empty:
            st.error("No xG data — Optuna only works for Understat leagues.")
            st.stop()

    with st.spinner("Building features..."):
        joukkue_ottelu = laajenna_per_joukkue(treenidata)
        joukkue_ottelu["xg_for"] = np.where(
            joukkue_ottelu["is_home"] == 1, joukkue_ottelu["home_xg"], joukkue_ottelu["away_xg"])
        joukkue_ottelu["xg_against"] = np.where(
            joukkue_ottelu["is_home"] == 1, joukkue_ottelu["away_xg"], joukkue_ottelu["home_xg"])
        piirteet = ["goals_for", "goals_against", "xg_for", "xg_against"]
        joukkue_ottelu = rolling_keskiarvo(joukkue_ottelu, piirteet, ikkuna=5)
        rolling_cols = [f"{p}_rolling5" for p in piirteet]
        ottelutaso = yhdista_ottelutasolle(joukkue_ottelu, rolling_cols)
        ottelutaso = lisaa_1x2(ottelutaso)
        feature_cols = [c for c in ottelutaso.columns if "rolling5" in c]
        data = ottelutaso.dropna(subset=feature_cols).copy().sort_values("date")
        split = int(len(data) * 0.8)
        train, valid = data.iloc[:split], data.iloc[split:]

    st.info(f"Train data: {len(train)} matches, validation: {len(valid)} matches, "
            f"features: {len(feature_cols)}")

    with st.spinner(f"Optuna runs up to {n_trials} trials, timeout {timeout_s}s..."):
        try:
            best = tune_lgbm_1x2(
                train[feature_cols], train["result_1x2"],
                valid[feature_cols], valid["result_1x2"],
                n_trials=n_trials, timeout_s=timeout_s,
            )
            st.success("✅ Optimization complete!")
            st.subheader("Best hyperparameters")
            st.json(best)
            st.code(
                "# Paste these into src/models/outcome_model.py defaults:\n"
                + "\n".join(f'    "{k}": {v},' for k, v in best.items()),
                language="python",
            )
            st.session_state["optuna_best"] = best
        except ImportError:
            st.error("Optuna not installed. Run: `pip install optuna`")
        except Exception as e:
            st.error(f"Optimization failed: {e}")
