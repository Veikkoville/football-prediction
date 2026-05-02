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

st.set_page_config(page_title="Vetokerroin-ROI", page_icon="💰", layout="wide")
st.title("💰 Vetokerroin-ROI — historiallinen simulaatio")
st.caption(
    "Walk-forward: malli ennustaa joka ottelulle, vertaa Bet365/Pinnacle-kertoimiin, "
    "panostaa value-vetoihin Kelly-fraktiolla. Lopussa ROI-prosentti."
)

st.sidebar.header("Asetukset")
liiga = st.sidebar.selectbox(
    "Liiga", [
        "ENG-Premier League", "ENG-Championship", "ESP-La Liga",
        "GER-Bundesliga", "ITA-Serie A", "FRA-Ligue 1",
        "POR-Primeira Liga", "NED-Eredivisie", "SCO-Premiership",
    ],
)
kaudet = st.sidebar.multiselect(
    "Kaudet (mainstream-tiedostot)",
    options=["2122", "2223", "2324", "2425"],
    default=["2223", "2324", "2425"],
)
min_train = st.sidebar.slider("Min train size", 100, 1500, 380, 50)
refit_days = st.sidebar.slider("Refit-välit (pv)", 1, 30, 14, 1)
value_threshold = st.sidebar.slider("Value-kynnys (%)", 0, 30, 5, 1) / 100.0
kelly_kerroin = st.sidebar.slider(
    "Kelly-fraktio", 0.05, 1.0, 0.25, 0.05,
    help="0.25 = 1/4 Kelly (suositeltava). 1.0 = täysi Kelly (riskialtis).",
)
odds_source = st.sidebar.radio(
    "Vetomyyjä", ["Bet365 (odds_home/draw/away)", "Pinnacle (ps_home/draw/away)"],
)
odds_lahde = "ps_home" if "Pinnacle" in odds_source else "odds_home"

if st.sidebar.button("▶️ Aja simulaatio", type="primary"):
    st.session_state["aja"] = True

if not st.session_state.get("aja"):
    st.info("👈 Valitse asetukset ja paina **Aja simulaatio**.")
    st.stop()

if not kaudet:
    st.warning("Valitse vähintään yksi kausi.")
    st.stop()


@st.cache_data(show_spinner="Ladataan dataa...")
def lataa(liiga, kaudet):
    return lataa_fd(liiga, list(kaudet))


df = lataa(liiga, tuple(kaudet))
if df.empty:
    st.error("Ei dataa.")
    st.stop()

st.success(f"Datassa {len(df)} ottelua.")
oc_check = ["ps_home", "ps_draw", "ps_away"] if odds_lahde == "ps_home" else ["odds_home", "odds_draw", "odds_away"]
puuttuvat = [c for c in oc_check if c not in df.columns]
if puuttuvat:
    st.error(f"Vetomyyjän kertoimet puuttuvat datasta: {puuttuvat}. Vaihda vetomyyjää tai liigaa.")
    st.stop()
df_kertoimilla = df.dropna(subset=oc_check)
st.caption(f"Kertoimet löytyvät {len(df_kertoimilla)} ottelulle.")

with st.spinner("Walk-forward simulaatio käynnissä..."):
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
    st.warning("Ei panostuksia syntynyt — value-kynnys liian korkea tai data puuttuu.")
    st.stop()

metr = laske_roi_metriikat(panostukset)

st.subheader("📊 Tulokset")
m1, m2, m3, m4 = st.columns(4)
m1.metric("Panostuksia", metr["n_panoksia"])
m2.metric("Voittoprosentti", f"{metr['voittoprosentti']:.1f} %")
m3.metric("ROI", f"{metr['roi_pct']:.2f} %",
          delta=f"{metr['kokonaistuotto']:+.1f} yks")
m4.metric("Max drawdown", f"{metr['max_drawdown']:.1f} yks")

if metr["roi_pct"] > 0:
    st.success(
        f"🎉 Malli olisi tehnyt **+{metr['roi_pct']:.2f}% ROI** {metr['n_panoksia']} "
        f"panostuksella. Varauma: yksi kausi/liiga ei vielä todista voittavaa mallia "
        f"— tarvitaan >2000 panostusta tilastollista merkitsevyyttä varten."
    )
else:
    st.warning(
        f"Malli olisi hävinnyt **{metr['roi_pct']:.2f}% ROI** {metr['n_panoksia']} "
        "panostuksella. Tämä on yleisin tulos (~94% julkaistuista vetomalleista häviää "
        "markkinaa pitkässä juoksussa)."
    )

st.divider()

# Kumulatiivinen tuotto
st.subheader("📈 Kumulatiivinen tuotto")
kum = panostukset.copy()
kum = kum.sort_values("date").reset_index(drop=True)
kum["kum_tuotto"] = kum["tuotto"].cumsum()
kum["panos_n"] = range(1, len(kum) + 1)
fig = px.line(kum, x="panos_n", y="kum_tuotto",
              labels={"panos_n": "Panostus #", "kum_tuotto": "Kumulatiivinen tuotto (yks)"},
              title=f"ROI {metr['roi_pct']:.2f}% • {metr['n_panoksia']} panostusta")
fig.add_hline(y=0, line_dash="dash", line_color="gray")
st.plotly_chart(fig, use_container_width=True)

st.divider()

# Panostustaulukko
st.subheader("📋 Yksittäiset panostukset")
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
