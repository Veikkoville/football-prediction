"""Vetokerroin-ROI backtest — olisiko malli tehnyt rahaa historiassa?"""

from __future__ import annotations
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
import plotly.express as px
import streamlit as st

from src.data.footballdata import lataa as lataa_fd
from src.models.betting_backtest import aja_vetokerroin_roi, laske_roi_metriikat

st.set_page_config(page_title="Odds ROI", page_icon="💰", layout="wide")
st.title("💰 Odds ROI — historical simulation")
st.caption(
    "Walk-forward: model predicts each match, compares to Bet365/Pinnacle odds, "
    "stakes value bets via Kelly fraction. Final result is ROI %."
)

st.sidebar.header("Settings")
liiga = st.sidebar.selectbox(
    "League", [
        "ENG-Premier League", "ENG-Championship", "ESP-La Liga",
        "GER-Bundesliga", "ITA-Serie A", "FRA-Ligue 1",
        "POR-Primeira Liga", "NED-Eredivisie", "SCO-Premiership",
    ],
)
kaudet = st.sidebar.multiselect(
    "Seasons (mainstream files)",
    options=["2122", "2223", "2324", "2425"],
    default=["2223", "2324", "2425"],
)
min_train = st.sidebar.slider("Min train size", 100, 1500, 380, 50)
refit_days = st.sidebar.slider("Refit interval (days)", 1, 30, 14, 1)
value_threshold = st.sidebar.slider("Value threshold (%)", 0, 30, 5, 1) / 100.0
kelly_kerroin = st.sidebar.slider(
    "Kelly fraction", 0.05, 1.0, 0.25, 0.05,
    help="0.25 = 1/4 Kelly (recommended). 1.0 = full Kelly (high-risk).",
)
odds_source = st.sidebar.radio(
    "Bookmaker", ["Bet365 (odds_home/draw/away)", "Pinnacle (ps_home/draw/away)"],
)
odds_lahde = "ps_home" if "Pinnacle" in odds_source else "odds_home"

if st.sidebar.button("▶️ Run simulation", type="primary"):
    st.session_state["aja"] = True

if not st.session_state.get("aja"):
    st.info("👈 Choose settings and click **Run simulation**.")
    st.stop()

if not kaudet:
    st.warning("Select at least one season.")
    st.stop()


@st.cache_data(show_spinner="Loading data...")
def lataa(liiga, kaudet):
    return lataa_fd(liiga, list(kaudet))


df = lataa(liiga, tuple(kaudet))
if df.empty:
    st.error("No data.")
    st.stop()

st.success(f"Data has {len(df)} matches.")
oc_check = ["ps_home", "ps_draw", "ps_away"] if odds_lahde == "ps_home" else ["odds_home", "odds_draw", "odds_away"]
puuttuvat = [c for c in oc_check if c not in df.columns]
if puuttuvat:
    st.error(f"Bookmaker odds missing from data: {puuttuvat}. Switch bookmaker or league.")
    st.stop()
df_kertoimilla = df.dropna(subset=oc_check)
st.caption(f"Odds available for {len(df_kertoimilla)} matches.")

with st.spinner("Walk-forward simulation running..."):
    progress = st.progress(0.0)
    def cb(i, n):
        progress.progress(min(i / max(n, 1), 1.0))
    panostukset = aja_vetokerroin_roi(
        df, min_train_size=min_train, refit_every_days=refit_days,
        value_threshold=value_threshold, kelly_kerroin=kelly_kerroin,
        odds_lahde=odds_lahde, progress_callback=cb,
    )
    progress.empty()

if panostukset.empty:
    st.warning("No bets generated — value threshold too high or data missing.")
    st.stop()

metr = laske_roi_metriikat(panostukset)

st.subheader("📊 Results")
m1, m2, m3, m4 = st.columns(4)
m1.metric("Bets placed", metr["n_panoksia"])
m2.metric("Win rate", f"{metr['voittoprosentti']:.1f} %")
m3.metric("ROI", f"{metr['roi_pct']:.2f} %",
          delta=f"{metr['kokonaistuotto']:+.1f} units")
m4.metric("Max drawdown", f"{metr['max_drawdown']:.1f} units")

if metr["roi_pct"] > 0:
    st.success(
        f"🎉 Model would have made **+{metr['roi_pct']:.2f}% ROI** with {metr['n_panoksia']} "
        f"bets. Caveat: one season/league is not enough to prove a winning model "
        f"— need >2000 bets for statistical significance."
    )
else:
    st.warning(
        f"Model would have lost **{metr['roi_pct']:.2f}% ROI** with {metr['n_panoksia']} "
        "bets. This is the most common result (~94% of published betting models lose "
        "to the market in the long run)."
    )

st.divider()

# Cumulative profit
st.subheader("📈 Cumulative profit")
kum = panostukset.copy()
kum = kum.sort_values("date").reset_index(drop=True)
kum["kum_tuotto"] = kum["tuotto"].cumsum()
kum["panos_n"] = range(1, len(kum) + 1)
fig = px.line(kum, x="panos_n", y="kum_tuotto",
              labels={"panos_n": "Bet #", "kum_tuotto": "Cumulative profit (units)"},
              title=f"ROI {metr['roi_pct']:.2f}% • {metr['n_panoksia']} bets")
fig.add_hline(y=0, line_dash="dash", line_color="gray")
st.plotly_chart(fig, use_container_width=True)

st.divider()

# Bets table
st.subheader("📋 Individual bets")
nayta = panostukset.copy()
nayta["date"] = nayta["date"].dt.strftime("%Y-%m-%d")
nayta["mallin_p"] = (nayta["mallin_p"] * 100).round(1)
nayta["value"] = (nayta["value"] * 100).round(2)
nayta["kerroin"] = nayta["kerroin"].round(2)
nayta["panos"] = nayta["panos"].round(3)
nayta["tuotto"] = nayta["tuotto"].round(3)
nayta["voitti"] = nayta["voitti"].map({True: "✅", False: "❌"})
st.dataframe(
    nayta[["date", "home_team", "away_team", "tulos", "valinta", "kerroin",
           "mallin_p", "value", "panos", "tuotto", "voitti"]],
    hide_index=True, use_container_width=True, height=400,
)
