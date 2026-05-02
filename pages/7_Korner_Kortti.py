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

st.set_page_config(page_title="Korner & kortti", page_icon="🚩", layout="wide")
st.title("🚩 Korner- ja korttiennusteet")
st.caption("Poisson-malli football-data.co.uk:n historiallisesta datasta.")

st.sidebar.header("Datan valinta")
liiga = st.sidebar.selectbox(
    "Liiga", [
        "ENG-Premier League", "ENG-Championship", "ENG-League One",
        "ESP-La Liga", "GER-Bundesliga", "ITA-Serie A", "FRA-Ligue 1",
        "NED-Eredivisie", "POR-Primeira Liga", "SCO-Premiership",
    ],
)
kaudet = st.sidebar.multiselect(
    "Kaudet", ["2122", "2223", "2324", "2425", "2526"],
    default=["2324", "2425", "2526"],
)

if not kaudet:
    st.warning("Valitse kausi.")
    st.stop()


@st.cache_data(show_spinner="Ladataan dataa...")
def lataa(liiga, kaudet):
    return lataa_fd(liiga, list(kaudet))


df = lataa(liiga, tuple(kaudet))
if df.empty:
    st.error("Ei dataa.")
    st.stop()

if "home_corners" not in df.columns:
    st.warning("Tassa liigassa ei ole korner-/korttidataa football-data.co.uk:ssa.")

malli = CornerCardModel().fit(df)

joukkueet = sorted(set(df["home_team"]) | set(df["away_team"]))

# Kayta session_statesta jaettua valintaa
koti_def = st.session_state.get("koti", joukkueet[0])
vieras_def = st.session_state.get("vieras", joukkueet[1] if len(joukkueet) > 1 else joukkueet[0])
koti_idx = joukkueet.index(koti_def) if koti_def in joukkueet else 0
vieras_idx = joukkueet.index(vieras_def) if vieras_def in joukkueet else 1

c1, c2 = st.columns(2)
koti = c1.selectbox("🏠 Kotijoukkue", joukkueet, index=koti_idx, key="koti")
vieras = c2.selectbox("✈️ Vierasjoukkue", joukkueet, index=vieras_idx, key="vieras")

if koti == vieras:
    st.warning("Valitse eri joukkueet.")
    st.stop()

st.divider()

# KORNERIT
st.subheader("🚩 Kornerit")
c_line = st.select_slider(
    "Maaliraja", options=[7.5, 8.5, 9.5, 10.5, 11.5, 12.5], value=9.5, key="c_line",
)
k_pred = malli.ennusta_kornerit(koti, vieras, line=c_line)
m1, m2, m3, m4 = st.columns(4)
m1.metric(f"{koti} ka. kornerit", f"{k_pred['lambda_home']:.1f}")
m2.metric(f"{vieras} ka. kornerit", f"{k_pred['lambda_away']:.1f}")
m3.metric(f"Yli {c_line}", f"{k_pred['yli']*100:.1f} %")
m4.metric(f"Alle {c_line}", f"{k_pred['alle']*100:.1f} %")
st.caption(f"Reilu kerroin: yli **{1/k_pred['yli']:.2f}**, alle **{1/k_pred['alle']:.2f}**")

st.divider()

# KORTIT
st.subheader("🟨 Keltaiset kortit")
y_line = st.select_slider(
    "Korttiraja", options=[2.5, 3.5, 4.5, 5.5, 6.5], value=4.5, key="y_line",
)
y_pred = malli.ennusta_kortit(koti, vieras, line=y_line)
m1, m2, m3, m4 = st.columns(4)
m1.metric(f"{koti} ka. kortit", f"{y_pred['lambda_home']:.1f}")
m2.metric(f"{vieras} ka. kortit", f"{y_pred['lambda_away']:.1f}")
m3.metric(f"Yli {y_line}", f"{y_pred['yli']*100:.1f} %")
m4.metric(f"Alle {y_line}", f"{y_pred['alle']*100:.1f} %")
st.caption(f"Reilu kerroin: yli **{1/y_pred['yli']:.2f}**, alle **{1/y_pred['alle']:.2f}**")

st.divider()
st.caption(
    "💡 Yksinkertainen Poisson — ei huomioi vastustajan vaikutusta tai tuomarin kortti-profiilia. "
    "Sopii pohja-arvioksi. Vetomarkkinassa kornerit ja kortit ovat usein paremmin "
    "hinnoittelemattomia kuin 1X2."
)
