"""Dixon-Coles + LightGBM ensemble — kaikki liigat ja kaudet."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st

import config
from src.data.loader import lataa_otteludata
from src.features.team_features import (
    laajenna_per_joukkue, rolling_keskiarvo, yhdista_ottelutasolle, lisaa_1x2,
)
from src.models.dixon_coles import DixonColesModel
from src.models.outcome_model import opeta_1x2
from src.models.ensemble import yhdista_1x2

st.set_page_config(page_title="Ensemble", page_icon="🤝", layout="wide")
st.title("🤝 Ensemble: Dixon-Coles + LightGBM")
st.caption("Two models for the same match. Weighted average is often better than either alone.")

st.sidebar.header("Data selection")
us_liigat = st.sidebar.multiselect(
    "Top-5 leagues (Understat, xG)",
    options=["ENG-Premier League", "ESP-La Liga", "GER-Bundesliga", "ITA-Serie A", "FRA-Ligue 1"],
    default=["ENG-Premier League"],
)
fb_liigat = st.sidebar.multiselect(
    "Other leagues (football-data.co.uk)",
    options=[
        "ENG-Championship", "ENG-League One", "ENG-League Two",
        "ESP-La Liga 2", "GER-2. Bundesliga", "ITA-Serie B", "FRA-Ligue 2",
        "POR-Primeira Liga", "NED-Eredivisie", "BEL-Pro League",
        "SCO-Premiership", "TUR-Super Lig",
        "FIN-Veikkausliiga", "SWE-Allsvenskan", "NOR-Eliteserien", "DEN-Superliga",
    ],
    default=[],
)
liigat = us_liigat + fb_liigat
kaudet = st.sidebar.multiselect(
    "Seasons", options=["2122", "2223", "2324", "2425", "2526"],
    default=["2425", "2526"],
    help="Adding seasons -> Dixon-Coles learns from longer history and refits.",
)
decay_val = st.sidebar.slider(
    "Decay", min_value=0.0, max_value=0.020, value=0.0065, step=0.0005, format="%.4f",
)


@st.cache_resource(show_spinner="Fitting both models...")
def opeta_mallit(liigat: tuple, kaudet: tuple, decay: float):
    treenidata = lataa_otteludata(list(liigat), list(kaudet))
    if treenidata.empty:
        return None, None, None, None

    dc = DixonColesModel().fit(
        treenidata,
        home_team_col="home_team", away_team_col="away_team",
        home_goals_col="home_score", away_goals_col="away_score",
        decay=decay, date_col="date",
    )

    # LightGBM tarvitsee xG-piirteet — toimii vain Understat-otteluille
    us_only = treenidata[treenidata["home_xg"].notna()].copy()
    if len(us_only) < 50:
        return dc, None, None, None

    joukkue_ottelu = laajenna_per_joukkue(us_only)
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
    train = ottelutaso.dropna(subset=feature_cols)
    if len(train) < 50:
        return dc, None, None, None
    lgb = opeta_1x2(train[feature_cols], train["result_1x2"], num_boost_round=200)

    viimeisimmat = (
        joukkue_ottelu.dropna(subset=rolling_cols)
        .sort_values("date").groupby("team")
        .tail(1)[["team"] + rolling_cols].set_index("team")
    )
    return dc, lgb, feature_cols, viimeisimmat


if not liigat or not kaudet:
    st.warning("Select league and season.")
    st.stop()

try:
    dc, lgb, feature_cols, viimeisimmat = opeta_mallit(tuple(liigat), tuple(kaudet), float(decay_val))
except Exception as e:
    st.error(f"Model loading failed: {e}")
    st.stop()

if dc is None:
    st.error("Dixon-Coles could not be fitted — dataset empty.")
    st.stop()

joukkueet = sorted(dc.teams_)
c1, c2 = st.columns(2)
with c1:
    koti_def = st.session_state.get("koti", joukkueet[0])
    koti = st.selectbox("Home team", joukkueet,
                        index=joukkueet.index(koti_def) if koti_def in joukkueet else 0,
                        key="koti")
with c2:
    vieras_def = st.session_state.get("vieras", joukkueet[1] if len(joukkueet) > 1 else joukkueet[0])
    vieras = st.selectbox("Away team", joukkueet,
                          index=joukkueet.index(vieras_def) if vieras_def in joukkueet else min(1, len(joukkueet) - 1),
                          key="vieras")

if koti == vieras:
    st.warning("Select two different teams.")
    st.stop()

paino = st.slider("Dixon-Coles weight (1.0 = DC only, 0.0 = LightGBM only)",
                  0.0, 1.0, 0.5, 0.05)

p_dc = dc.predict_1x2(koti, vieras)

p_lgb = None
p_ens = None
if lgb is not None and viimeisimmat is not None:
    if koti in viimeisimmat.index and vieras in viimeisimmat.index:
        h = viimeisimmat.loc[koti].add_prefix("home_")
        a = viimeisimmat.loc[vieras].add_prefix("away_")
        rivi = pd.concat([h, a]).to_frame().T
        if all(c in rivi.columns for c in feature_cols):
            X = rivi[feature_cols]
            p_lgb_arr = lgb.predict(X)[0]
            p_lgb = {"home": float(p_lgb_arr[0]), "draw": float(p_lgb_arr[1]), "away": float(p_lgb_arr[2])}
            p_ens = yhdista_1x2(p_dc, p_lgb_arr, paino_dixon=paino)

st.subheader("Model comparison")
vertailu_df = pd.DataFrame({
    "Model": ["Dixon-Coles", "LightGBM", "Ensemble"],
    "1": [p_dc["home"], p_lgb["home"] if p_lgb else np.nan, p_ens["home"] if p_ens else np.nan],
    "X": [p_dc["draw"], p_lgb["draw"] if p_lgb else np.nan, p_ens["draw"] if p_ens else np.nan],
    "2": [p_dc["away"], p_lgb["away"] if p_lgb else np.nan, p_ens["away"] if p_ens else np.nan],
})
vs = vertailu_df.copy()
for c in ["1", "X", "2"]:
    vs[c] = (vs[c] * 100).round(2).astype(str) + " %"
st.dataframe(vs, hide_index=True, use_container_width=True)

if p_ens is None:
    st.warning(
        "LightGBM prediction could not be made for this match — either dataset too small "
        "or home/away team not in Understat leagues (LGB requires xG features)."
    )

chart_df = vertailu_df.melt(id_vars="Model", var_name="Outcome", value_name="Probability")
chart_df["Probability %"] = chart_df["Probability"] * 100
fig = px.bar(chart_df.dropna(), x="Outcome", y="Probability %",
             color="Model", barmode="group", height=400)
st.plotly_chart(fig, use_container_width=True)

st.divider()
st.caption(
    "Dixon-Coles looks at long-term attack/defence levels of teams "
    "(historical seasons with decay-weighting). LightGBM focuses on what has "
    "happened in the last 5 matches (rolling form). Ensemble softens "
    "both models' over-confidence — often a more stable prediction than either alone."
)
