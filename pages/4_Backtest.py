"""
Walk-forward -backtest, kalibrointikuvaaja ja historialliset ennusteet.

Tämä on hidas — Dixon-Coles sovittuu uudelleen viikon välein, mikä voi
kestää useita minuutteja koko kauden datalle. Sovellus välimuistittaa
tuloksen, joten toinen ajo on välitön.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import config
from src.data.understat import lataa_otteludata as lataa_us_ottelut
from src.models.backtest import (
    walk_forward_dixon_coles, walk_forward_ensemble,
    laske_metriikat, kalibrointi_data,
)
from src.models.calibration import kalibroi_walk_forward

st.set_page_config(page_title="Backtest", page_icon="🔬", layout="wide")
st.title("🔬 Backtest, calibration and historical predictions")
st.caption(
    "Walk-forward evaluation: for each match the model is fitted "
    "ONLY on data preceding it. This is an honest measure of the model's "
    "true predictive power."
)

st.sidebar.header("Backtest settings")
liigat = st.sidebar.multiselect(
    "Leagues",
    options=["ENG-Premier League", "ESP-La Liga", "GER-Bundesliga", "ITA-Serie A", "FRA-Ligue 1"],
    default=["ENG-Premier League"],
)
kaudet = st.sidebar.multiselect(
    "Seasons", options=["2122", "2223", "2324", "2425"],
    default=["2425"],
)
min_train = st.sidebar.slider(
    "Minimum train size", 30, 1500, 380, 10,
    help="How many matches to skip before starting predictions. "
         "380 = one PL season -> evaluation only after the model is stable. "
         "With multiple seasons of data, recommend 380-760.",
)
refit_days = st.sidebar.slider("Refit model every N days", 1, 30, 7, 1)

st.sidebar.divider()
kaytä_ensemble = st.sidebar.toggle(
    "🤝 Use Ensemble (DC + LightGBM)",
    value=False,
    help="LightGBM requires xG features — works only for Top-5 leagues. "
         "Slower (LGB refits on each refit cycle) but usually better.",
)
ens_paino = st.sidebar.slider(
    "Ensemble: Dixon-Coles weight", 0.0, 1.0, 0.5, 0.05,
    disabled=not kaytä_ensemble,
)

if st.sidebar.button("▶️ Run backtest", type="primary"):
    st.session_state["aja_backtest"] = True


@st.cache_data(show_spinner=False)
def cached_backtest(liigat: tuple, kaudet: tuple, min_train: int, refit_days: int, kaytä_ensemble: bool, ens_paino: float) -> pd.DataFrame:
    us = lataa_us_ottelut(list(liigat), list(kaudet),
                          cache_dir=config.RAW_DATA_DIR / "understat")
    matches = us.rename(columns={
        "home_goals": "home_score", "away_goals": "away_score",
    }).dropna(subset=["home_score", "away_score"]).copy()
    # Ensemble vaatii xG-sarakkeet sailytetylla (home_xg, away_xg jo nimettyna oikein Understatissa)
    matches["date"] = pd.to_datetime(matches["date"])

    progress = st.progress(0.0, text="Walk-forward running...")
    def cb(i, n):
        progress.progress(min(i / max(n, 1), 1.0), text=f"Walk-forward: {i}/{n}")

    if kaytä_ensemble:
        bt = walk_forward_ensemble(
            matches,
            min_train_size=min_train,
            refit_every_days=refit_days,
            paino_dixon=ens_paino,
            progress_callback=cb,
        )
    else:
        bt = walk_forward_dixon_coles(
            matches,
            min_train_size=min_train,
            refit_every_days=refit_days,
            progress_callback=cb,
        )
    progress.empty()
    return bt


if not st.session_state.get("aja_backtest"):
    st.info("👈 Select settings in the sidebar and click **Run backtest**. "
            "First run may take 1–5 minutes.")
    st.stop()

if not liigat or not kaudet:
    st.warning("Select league and season.")
    st.stop()

bt = cached_backtest(tuple(liigat), tuple(kaudet), min_train, refit_days, kaytä_ensemble, ens_paino)

if bt.empty:
    st.error("Backtest produced no predictions. Lower `min_train`.")
    st.stop()

# ---------------------------------------------------------------------------
# METRIIKAT
# ---------------------------------------------------------------------------
# Calibrate results (default: on)
kalibroi = st.checkbox(
    "🎯 Calibrate probabilities (Platt/isotonic)",
    value=True,
    help="Corrects model over-/under-confidence. Pulls calibration points toward the diagonal.",
)
kal_method = st.radio("Calibration method", ["isotonic", "platt"], horizontal=True)

bt_kal = bt.copy()
if kalibroi and len(bt) >= 50:
    p_raw = bt[["p_home", "p_draw", "p_away"]].values
    y = bt["actual_1x2"].values
    p_cal = kalibroi_walk_forward(p_raw, y, method=kal_method, split_frac=0.5)
    bt_kal["p_home"] = p_cal[:, 0]
    bt_kal["p_draw"] = p_cal[:, 1]
    bt_kal["p_away"] = p_cal[:, 2]

metr_raaka = laske_metriikat(bt)
metr = laske_metriikat(bt_kal) if kalibroi else metr_raaka

st.subheader("📈 Performance metrics")
if kalibroi:
    st.caption(
        f"Raw log loss: {metr_raaka['log_loss']:.3f} -> calibrated: {metr['log_loss']:.3f}. "
        f"Brier: {metr_raaka['brier']:.3f} -> {metr['brier']:.3f}."
    )
m1, m2, m3, m4 = st.columns(4)
m1.metric("Matches predicted", metr["n"])
m2.metric("Log loss", f"{metr['log_loss']:.3f}",
          help="Lower = better. Uniform distribution gives ~1.099.")
m3.metric("Accuracy (1X2)", f"{metr['accuracy']*100:.1f} %",
          help="Largest probability = prediction. Random = ~33%, home advantage ~46%.")
m4.metric("Brier score", f"{metr['brier']:.3f}",
          help="Lower = better. 0 = perfect, 0.667 = naive.")

st.divider()

# ---------------------------------------------------------------------------
# CALIBRATION CHART
# ---------------------------------------------------------------------------
st.subheader("📐 Calibration (reliability diagram)")
st.caption(
    "A well-calibrated model: when the model says 'win 60%', the team wins "
    "60% of the time in reality. Diagonal = perfect calibration."
)

kal = kalibrointi_data(bt_kal if kalibroi else bt, n_bins=10)
fig = go.Figure()
fig.add_trace(go.Scatter(x=[0, 1], y=[0, 1], mode="lines",
                         name="Perfect calibration", line=dict(dash="dash", color="gray")))
fig.add_trace(go.Scatter(x=kal["ennustettu"], y=kal["toteutunut"],
                         mode="lines+markers", name="Model calibration",
                         marker=dict(size=12)))
fig.update_layout(
    xaxis_title="Model predicted probability",
    yaxis_title="Realized fraction",
    xaxis=dict(range=[0, 1]), yaxis=dict(range=[0, 1]),
    height=500,
)
st.plotly_chart(fig, use_container_width=True)

st.caption(
    f"Sample size per bin: {', '.join(str(int(n)) for n in kal['n'])}. "
    "More observations per bin = more reliable point."
)

st.divider()

# ---------------------------------------------------------------------------
# HISTORICAL PREDICTIONS
# ---------------------------------------------------------------------------
st.subheader("📜 Historical predictions vs outcomes")
st.caption("What the model said before the match and what the result was.")

bt_show = (bt_kal if kalibroi else bt).copy()
bt_show["Score"] = bt_show["home_score"].astype(str) + "-" + bt_show["away_score"].astype(str)
bt_show["Actual"] = bt_show["actual_1x2"].map({0: "1", 1: "X", 2: "2"})

# Model pick = highest p
bt_show["Model pick"] = bt_show[["p_home", "p_draw", "p_away"]].values.argmax(axis=1)
bt_show["Model pick"] = bt_show["Model pick"].map({0: "1", 1: "X", 2: "2"})
bt_show["Correct?"] = (bt_show["Model pick"] == bt_show["Actual"]).map({True: "✅", False: "❌"})

bt_show["1 %"] = (bt_show["p_home"] * 100).round(1)
bt_show["X %"] = (bt_show["p_draw"] * 100).round(1)
bt_show["2 %"] = (bt_show["p_away"] * 100).round(1)

# Filter
suodatin = st.text_input("Filter by team (free text)", "")
if suodatin:
    mask = (
        bt_show["home_team"].str.contains(suodatin, case=False, na=False) |
        bt_show["away_team"].str.contains(suodatin, case=False, na=False)
    )
    bt_show = bt_show[mask]

st.dataframe(
    bt_show[[
        "date", "home_team", "away_team", "Score", "Actual",
        "1 %", "X %", "2 %", "Model pick", "Correct?",
    ]].sort_values("date", ascending=False),
    hide_index=True, use_container_width=True, height=500,
)

# ---------------------------------------------------------------------------
# PROFIITTISIMULAATIO (jos olisi panostettu mallin suurimman p:n mukaan)
# ---------------------------------------------------------------------------
st.divider()
st.subheader("💸 Naive betting calculation (if you had bet the model's pick)")
st.caption(
    "Hypothetical 1.0 unit stake on each match's highest model probability, "
    "assuming fair odds = 1/p."
)

bt2 = bt.copy()
bt2["pred_idx"] = bt2[["p_home", "p_draw", "p_away"]].values.argmax(axis=1)
bt2["pred_p"] = bt2[["p_home", "p_draw", "p_away"]].values.max(axis=1)
bt2["voitti"] = bt2["pred_idx"] == bt2["actual_1x2"]
# Reilu kerroin
bt2["reilu_kerroin"] = 1.0 / bt2["pred_p"]
# Tulos jos reilulla kertoimella (ei marginaalia) → break-even
bt2["voitto_yks"] = bt2.apply(lambda r: (r["reilu_kerroin"] - 1.0) if r["voitti"] else -1.0, axis=1)

# Kuvitteelliset markkinakertoimet 6% marginaalilla
bt2["markkina_kerroin"] = bt2["reilu_kerroin"] * (1 - 0.06)
bt2["markkina_voitto"] = bt2.apply(lambda r: (r["markkina_kerroin"] - 1.0) if r["voitti"] else -1.0, axis=1)

s1, s2, s3 = st.columns(3)
s1.metric("Matches", len(bt2))
s2.metric("Fair-odds cumulative ROI",
          f"{bt2['voitto_yks'].sum():.1f} units", delta=f"{bt2['voitto_yks'].mean()*100:.1f} % per bet")
s3.metric("Market (6 % margin) ROI",
          f"{bt2['markkina_voitto'].sum():.1f} units", delta=f"{bt2['markkina_voitto'].mean()*100:.1f} % per bet")

st.caption(
    "💡 The market estimate assumes the bookmaker prices their view with a "
    "+6% margin. If your model is as good as the market, ROI is around -6 % "
    "(you lose the margin). Positive ROI = your model beat the market in "
    "this sample, but one season is not enough to prove a profitable model."
)
