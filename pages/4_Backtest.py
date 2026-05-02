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
st.title("🔬 Backtest, kalibrointi ja historialliset ennusteet")
st.caption(
    "Walk-forward -arviointi: jokaiselle ottelulle malli sovitetaan "
    "VAIN sitä edeltävällä datalla. Tämä on rehellinen mittari mallin "
    "todelliselle ennustekyvylle."
)

st.sidebar.header("Backtestin asetukset")
liigat = st.sidebar.multiselect(
    "Liigat",
    options=["ENG-Premier League", "ESP-La Liga", "GER-Bundesliga", "ITA-Serie A", "FRA-Ligue 1"],
    default=["ENG-Premier League"],
)
kaudet = st.sidebar.multiselect(
    "Kaudet", options=["2122", "2223", "2324", "2425"],
    default=["2425"],
)
min_train = st.sidebar.slider(
    "Minimi treenikoko", 30, 1500, 380, 10,
    help="Kuinka monta ottelua skipataan ennen kuin aletaan ennustaa. "
         "380 = yksi PL-kausi -> arviointi vasta sitten kun malli on vakaa. "
         "Useamman kauden datalla suosittele 380-760.",
)
refit_days = st.sidebar.slider("Sovita malli uudelleen joka N päivä", 1, 30, 7, 1)

st.sidebar.divider()
kaytä_ensemble = st.sidebar.toggle(
    "🤝 Käytä Ensemble (DC + LightGBM)",
    value=False,
    help="LightGBM tarvitsee xG-piirteet — toimii vain Top-5 -liigoille. "
         "Hitaampi (LGB sovittuu uudelleen joka refit) mutta usein parempi.",
)
ens_paino = st.sidebar.slider(
    "Ensemble: Dixon-Coles paino", 0.0, 1.0, 0.5, 0.05,
    disabled=not kaytä_ensemble,
)

if st.sidebar.button("▶️ Aja backtest", type="primary"):
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

    progress = st.progress(0.0, text="Walk-forward käynnissä...")
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
    st.info("👈 Valitse asetukset sivupalkista ja paina **Aja backtest**. "
            "Ensimmäinen ajo voi kestää 1–5 minuuttia.")
    st.stop()

if not liigat or not kaudet:
    st.warning("Valitse liiga ja kausi.")
    st.stop()

bt = cached_backtest(tuple(liigat), tuple(kaudet), min_train, refit_days, kaytä_ensemble, ens_paino)

if bt.empty:
    st.error("Backtest ei tuottanut yhtään ennustetta. Vähennä `min_train`-arvoa.")
    st.stop()

# ---------------------------------------------------------------------------
# METRIIKAT
# ---------------------------------------------------------------------------
# Kalibroi tulokset (oletus: paalla)
kalibroi = st.checkbox(
    "🎯 Kalibroi todennakoisyydet (Platt/isotoninen)",
    value=True,
    help="Korjaa malllin yli-/ali-itsevarmuuden. Tekee kalibrointipisteet nojaamaan diagonaaliin.",
)
kal_method = st.radio("Kalibrointimetodi", ["isotonic", "platt"], horizontal=True)

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

st.subheader("📈 Suorituskykymittarit")
if kalibroi:
    st.caption(
        f"Raaka log loss: {metr_raaka['log_loss']:.3f} -> kalibroitu: {metr['log_loss']:.3f}. "
        f"Brier: {metr_raaka['brier']:.3f} -> {metr['brier']:.3f}."
    )
m1, m2, m3, m4 = st.columns(4)
m1.metric("Otteluita ennustettu", metr["n"])
m2.metric("Log loss", f"{metr['log_loss']:.3f}",
          help="Pieni = hyvä. Pelkkä tasajako tuottaa ~1.099.")
m3.metric("Accuracy (1X2)", f"{metr['accuracy']*100:.1f} %",
          help="Suurin todennäköisyys = ennuste. Sattuma = ~33%, kotietuus ~46%.")
m4.metric("Brier score", f"{metr['brier']:.3f}",
          help="Pieni = hyvä. 0 = täydellinen, 0.667 = naiivi.")

st.divider()

# ---------------------------------------------------------------------------
# KALIBROINTIKUVAAJA
# ---------------------------------------------------------------------------
st.subheader("📐 Kalibrointi (reliability diagram)")
st.caption(
    "Hyvin kalibroitu malli: kun malli sanoo 'voitto 60 %', toteumassa "
    "voittaa 60 % ajasta. Diagonaali = täydellinen kalibrointi."
)

kal = kalibrointi_data(bt_kal if kalibroi else bt, n_bins=10)
fig = go.Figure()
fig.add_trace(go.Scatter(x=[0, 1], y=[0, 1], mode="lines",
                         name="Täydellinen kalibrointi", line=dict(dash="dash", color="gray")))
fig.add_trace(go.Scatter(x=kal["ennustettu"], y=kal["toteutunut"],
                         mode="lines+markers", name="Mallin kalibrointi",
                         marker=dict(size=12)))
fig.update_layout(
    xaxis_title="Mallin ennustama todennäköisyys",
    yaxis_title="Toteutunut osuus",
    xaxis=dict(range=[0, 1]), yaxis=dict(range=[0, 1]),
    height=500,
)
st.plotly_chart(fig, use_container_width=True)

st.caption(
    f"Otoskoko per bin: {', '.join(str(int(n)) for n in kal['n'])}. "
    "Mitä useampi havainto per bin, sitä luotettavampi piste."
)

st.divider()

# ---------------------------------------------------------------------------
# HISTORIALLISET ENNUSTEET
# ---------------------------------------------------------------------------
st.subheader("📜 Historialliset ennusteet vs toteutumat")
st.caption("Mitä malli sanoi ennen ottelua ja mikä lopputulos oli.")

bt_show = (bt_kal if kalibroi else bt).copy()
bt_show["Tulos"] = bt_show["home_score"].astype(str) + "-" + bt_show["away_score"].astype(str)
bt_show["Toteutunut"] = bt_show["actual_1x2"].map({0: "1", 1: "X", 2: "2"})

# Mallin valinta = suurin p
bt_show["Mallin veikkaus"] = bt_show[["p_home", "p_draw", "p_away"]].values.argmax(axis=1)
bt_show["Mallin veikkaus"] = bt_show["Mallin veikkaus"].map({0: "1", 1: "X", 2: "2"})
bt_show["Oikein?"] = (bt_show["Mallin veikkaus"] == bt_show["Toteutunut"]).map({True: "✅", False: "❌"})

bt_show["1 %"] = (bt_show["p_home"] * 100).round(1)
bt_show["X %"] = (bt_show["p_draw"] * 100).round(1)
bt_show["2 %"] = (bt_show["p_away"] * 100).round(1)

# Suodatin
suodatin = st.text_input("Suodata joukkueella (vapaa teksti)", "")
if suodatin:
    mask = (
        bt_show["home_team"].str.contains(suodatin, case=False, na=False) |
        bt_show["away_team"].str.contains(suodatin, case=False, na=False)
    )
    bt_show = bt_show[mask]

st.dataframe(
    bt_show[[
        "date", "home_team", "away_team", "Tulos", "Toteutunut",
        "1 %", "X %", "2 %", "Mallin veikkaus", "Oikein?",
    ]].sort_values("date", ascending=False),
    hide_index=True, use_container_width=True, height=500,
)

# ---------------------------------------------------------------------------
# PROFIITTISIMULAATIO (jos olisi panostettu mallin suurimman p:n mukaan)
# ---------------------------------------------------------------------------
st.divider()
st.subheader("💸 Naiivi vetokalkyyli (jos olisi panostettu mallin valintaan)")
st.caption(
    "Kuvitteellinen 1.0 yksikön panos jokaiseen otteluun mallin suurimmalle "
    "todennäköisyydelle, oletetaan reilu kerroin = 1/p."
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
s1.metric("Otteluita", len(bt2))
s2.metric("Reilun kertoimen kumulatiivinen ROI",
          f"{bt2['voitto_yks'].sum():.1f} yks", delta=f"{bt2['voitto_yks'].mean()*100:.1f} % per veto")
s3.metric("Markkina (6 % marginaali) ROI",
          f"{bt2['markkina_voitto'].sum():.1f} yks", delta=f"{bt2['markkina_voitto'].mean()*100:.1f} % per veto")

st.caption(
    "💡 Markkina-arvio olettaa että vetomyyjä hinnoittelee oman näkemyksensä +6% "
    "Markkina-arvio olettaa etta vetomyyja hinnoittelee oman nakemyksensa +6% "
    "marginaalilla. Jos malli on yhta hyva kuin markkina, ROI on noin -6 % "
    "(haviat marginaalin). Positiivinen ROI = mallisi peittosi markkinan tassa "
    "otoksessa, mutta yksi kausi ei viela riita todistamaan voitollista mallia."
)
