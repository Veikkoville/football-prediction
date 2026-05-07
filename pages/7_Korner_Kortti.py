"""Korner- ja korttiennusteet Poisson-mallilla."""

from __future__ import annotations
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
import streamlit as st

from src.data.footballdata import lataa as lataa_fd
from src.models.poisson_market import CornerCardModel

st.set_page_config(page_title="Corners & Cards", page_icon="🚩", layout="wide")
st.title("🚩 Corner and card predictions")
st.caption("Poisson model from football-data.co.uk historical data.")

st.sidebar.header("Data selection")
liiga = st.sidebar.selectbox(
    "League", [
        "ENG-Premier League", "ENG-Championship", "ENG-League One",
        "ESP-La Liga", "GER-Bundesliga", "ITA-Serie A", "FRA-Ligue 1",
        "NED-Eredivisie", "POR-Primeira Liga", "SCO-Premiership",
    ],
)
kaudet = st.sidebar.multiselect(
    "Seasons", ["2122", "2223", "2324", "2425", "2526"],
    default=["2324", "2425", "2526"],
)

if not kaudet:
    st.warning("Select a season.")
    st.stop()


@st.cache_data(show_spinner="Loading data...")
def lataa(liiga, kaudet):
    return lataa_fd(liiga, list(kaudet))


df = lataa(liiga, tuple(kaudet))
if df.empty:
    st.error("No data.")
    st.stop()

if "home_corners" not in df.columns:
    st.warning("This league has no corner/card data in football-data.co.uk.")

malli = CornerCardModel().fit(df)

joukkueet = sorted(set(df["home_team"]) | set(df["away_team"]))

# Use shared session_state choice
koti_def = st.session_state.get("koti", joukkueet[0])
vieras_def = st.session_state.get("vieras", joukkueet[1] if len(joukkueet) > 1 else joukkueet[0])
koti_idx = joukkueet.index(koti_def) if koti_def in joukkueet else 0
vieras_idx = joukkueet.index(vieras_def) if vieras_def in joukkueet else 1

c1, c2 = st.columns(2)
koti = c1.selectbox("🏠 Home team", joukkueet, index=koti_idx, key="koti")
vieras = c2.selectbox("✈️ Away team", joukkueet, index=vieras_idx, key="vieras")

if koti == vieras:
    st.warning("Select different teams.")
    st.stop()

st.divider()

# CORNERS
st.subheader("🚩 Corners")
c_line = st.select_slider(
    "Line", options=[7.5, 8.5, 9.5, 10.5, 11.5, 12.5], value=9.5, key="c_line",
)
k_pred = malli.ennusta_kornerit(koti, vieras, line=c_line)
m1, m2, m3, m4 = st.columns(4)
m1.metric(f"{koti} avg corners", f"{k_pred['lambda_home']:.1f}")
m2.metric(f"{vieras} avg corners", f"{k_pred['lambda_away']:.1f}")
m3.metric(f"Over {c_line}", f"{k_pred['yli']*100:.1f} %")
m4.metric(f"Under {c_line}", f"{k_pred['alle']*100:.1f} %")
st.caption(f"Fair odds: over **{1/k_pred['yli']:.2f}**, under **{1/k_pred['alle']:.2f}**")

st.divider()

# CARDS
st.subheader("🟨 Yellow cards")
y_line = st.select_slider(
    "Card line", options=[2.5, 3.5, 4.5, 5.5, 6.5], value=4.5, key="y_line",
)
y_pred = malli.ennusta_kortit(koti, vieras, line=y_line)
m1, m2, m3, m4 = st.columns(4)
m1.metric(f"{koti} avg cards", f"{y_pred['lambda_home']:.1f}")
m2.metric(f"{vieras} avg cards", f"{y_pred['lambda_away']:.1f}")
m3.metric(f"Over {y_line}", f"{y_pred['yli']*100:.1f} %")
m4.metric(f"Under {y_line}", f"{y_pred['alle']*100:.1f} %")
st.caption(f"Fair odds: over **{1/y_pred['yli']:.2f}**, under **{1/y_pred['alle']:.2f}**")

st.divider()
st.caption(
    "💡 Simple Poisson — does not account for opponent strength or referee card profile. "
    "Use as a baseline estimate. In betting markets, corners and cards are often "
    "less efficiently priced than 1X2."
)
