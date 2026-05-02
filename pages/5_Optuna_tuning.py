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

st.set_page_config(page_title="Optuna-tuning", page_icon="🔧", layout="wide")
st.title("🔧 LightGBM-hyperparametrien optimointi")
st.caption(
    "Optuna etsii parhaat hyperparametrit minimoiden validointi log lossin. "
    "Tee tama kerran kun haluat saada lisaa suorituskykya — kayta tuloksena saatuja "
    "parametreja Ensemble-sivulla."
)

st.sidebar.header("Datan valinta")
liigat = st.sidebar.multiselect(
    "Liigat (vain Top-5 toimii — tarvitaan xG)",
    options=["ENG-Premier League", "ESP-La Liga", "GER-Bundesliga", "ITA-Serie A", "FRA-Ligue 1"],
    default=["ENG-Premier League"],
)
kaudet = st.sidebar.multiselect(
    "Kaudet", options=["2122", "2223", "2324", "2425", "2526"],
    default=["2324", "2425"],
)
n_trials = st.sidebar.slider("Optuna trial-maara", 10, 100, 30, 5,
                             help="Enemman = parempi tulos mutta hitaampi.")
timeout_s = st.sidebar.slider("Timeout (sekuntia)", 30, 600, 120, 30)

if not liigat or not kaudet:
    st.warning("Valitse liiga + kausi.")
    st.stop()

if st.button("▶️ Aja Optuna-tuning", type="primary"):
    with st.spinner("Ladataan dataa..."):
        treenidata = lataa_otteludata(list(liigat), list(kaudet))
        treenidata = treenidata[treenidata["home_xg"].notna()].copy()
        if treenidata.empty:
            st.error("Ei xG-dataa — Optuna toimii vain Understat-liigoille.")
            st.stop()

    with st.spinner("Rakennetaan piirteita..."):
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

    st.info(f"Treenidata: {len(train)} ottelua, validointi: {len(valid)} ottelua, "
            f"piirteita: {len(feature_cols)}")

    with st.spinner(f"Optuna ajaa enintaan {n_trials} trialia, timeout {timeout_s}s..."):
        try:
            best = tune_lgbm_1x2(
                train[feature_cols], train["result_1x2"],
                valid[feature_cols], valid["result_1x2"],
                n_trials=n_trials, timeout_s=timeout_s,
            )
            st.success("✅ Optimointi valmis!")
            st.subheader("Parhaat hyperparametrit")
            st.json(best)
            st.code(
                "# Liita nama src/models/outcome_model.py:n oletuksiin:\n"
                + "\n".join(f'    "{k}": {v},' for k, v in best.items()),
                language="python",
            )
            st.session_state["optuna_best"] = best
        except ImportError:
            st.error("Optuna ei ole asennettuna. Aja: `pip install optuna`")
        except Exception as e:
            st.error(f"Optimointi epaonnistui: {e}")
