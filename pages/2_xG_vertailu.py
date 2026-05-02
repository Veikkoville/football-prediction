"""
StatsBomb xG-vertailu — kaikki saatavilla olevat kilpailut + ottelumäärät.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

from src.data.statsbomb import (
    listaa_kilpailut, hae_ottelut, hae_tapahtumat, laske_xg_per_joukkue,
)

st.set_page_config(page_title="xG-vertailu", page_icon="📊", layout="wide")
st.title("📊 StatsBomb xG-vertailu")
st.caption(
    "StatsBomb open data on alan tunnustettu xG-malli. "
    "Käytä tätä sivua tarkistamaan tuttujen otteluiden xG-arvoja, ja vertaa niitä "
    "mielessäsi mallin Understat-pohjaisiin lukuihin."
)


# ---------------------------------------------------------------------------
# KILPAILUT — lasketaan ottelumäärät
# ---------------------------------------------------------------------------
@st.cache_data(show_spinner="Haetaan kilpailulista...")
def lataa_kilpailut() -> pd.DataFrame:
    return listaa_kilpailut()


@st.cache_data(show_spinner=False)
def laske_ottelumaarat(kilpailut: pd.DataFrame) -> pd.DataFrame:
    """Lisää ``n_matches`` -sarake — kuinka monta ottelua per kilpailu/kausi."""
    rivit = []
    progress = st.progress(0.0, text="Lasketaan ottelumääriä per kilpailu...")
    for i, (_, r) in enumerate(kilpailut.iterrows()):
        try:
            ot = hae_ottelut(competition_id=int(r["competition_id"]),
                             season_id=int(r["season_id"]))
            rivit.append({**r.to_dict(), "n_matches": len(ot)})
        except Exception:
            rivit.append({**r.to_dict(), "n_matches": 0})
        progress.progress((i + 1) / len(kilpailut))
    progress.empty()
    return pd.DataFrame(rivit)


kilpailut = lataa_kilpailut()

st.sidebar.header("Suodatus")
nayta_kaikki = st.sidebar.checkbox(
    "Näytä kaikki kilpailut (myös pienet)",
    value=False,
    help="Päällä → näytetään kaikki StatsBombin avoimet kilpailut. "
         "Pois → näytetään vain isot turnaukset (MM, EM, NWSL, La Liga 'Messi-data').",
)

if nayta_kaikki:
    st.sidebar.info("Lasketaan ottelumäärät kerran — kestää muutaman minuutin ensimmäisellä kerralla.")
    if st.sidebar.button("📊 Laske ottelumäärät"):
        with st.spinner("Lasketaan..."):
            kilpailut = laske_ottelumaarat(kilpailut)
            st.session_state["lasketut_kilpailut"] = kilpailut
    if "lasketut_kilpailut" in st.session_state:
        kilpailut = st.session_state["lasketut_kilpailut"]
    else:
        kilpailut = kilpailut.copy()
        kilpailut["n_matches"] = -1  # Ei tiedetä vielä
else:
    # Suodata isot turnaukset (vähintään 10 ottelua taatusti)
    isot = ["FIFA World Cup", "UEFA Euro", "FIFA Women's World Cup",
            "UEFA Women's Euro", "La Liga", "NWSL", "Indian Super League",
            "Premier League", "Bundesliga", "Serie A", "Ligue 1",
            "Africa Cup of Nations", "Copa America", "FA Women's Super League",
            "Liga Profesional", "1. Bundesliga"]
    kilpailut = kilpailut[
        kilpailut["competition_name"].isin(isot)
    ].copy()
    kilpailut["n_matches"] = -1

# Lajittele uusimmat ensin
kilpailut = kilpailut.sort_values(["competition_name", "season_id"], ascending=[True, False])

if kilpailut.empty:
    st.warning("Ei kilpailuita näytettäväksi. Käännä 'Näytä kaikki' päälle.")
    st.stop()

# Näytä label (ottelumäärä jos tiedossa)
def _label(r):
    txt = f"{r['competition_name']} — {r['season_name']}"
    if r.get("n_matches", -1) > 0:
        txt += f" ({int(r['n_matches'])} ottelua)"
    return txt

kilpailut["_label"] = kilpailut.apply(_label, axis=1)

valinta = st.selectbox("Kilpailu / kausi", kilpailut["_label"].tolist())
rivi = kilpailut[kilpailut["_label"] == valinta].iloc[0]
comp_id = int(rivi["competition_id"])
season_id = int(rivi["season_id"])

# ---------------------------------------------------------------------------
# OTTELUT
# ---------------------------------------------------------------------------
@st.cache_data(show_spinner="Haetaan otteluita...")
def lataa_ottelut(c: int, s: int) -> pd.DataFrame:
    return hae_ottelut(competition_id=c, season_id=s)

try:
    ottelut = lataa_ottelut(comp_id, season_id)
except Exception as e:
    st.error(f"Otteluiden haku epäonnistui: {e}")
    st.stop()

if ottelut.empty:
    st.warning("Tässä kilpailussa ei ole avoimena yhtään ottelua.")
    st.stop()

st.success(f"Kilpailussa **{rivi['competition_name']} {rivi['season_name']}** on {len(ottelut)} ottelua avoimena.")

ottelut_sorted = ottelut.sort_values("match_date", ascending=False)
ottelu_strings = (
    ottelut_sorted["match_date"].astype(str) + ": " +
    ottelut_sorted["home_team"] + " vs " + ottelut_sorted["away_team"]
).tolist()
valittu = st.selectbox(f"Valitse ottelu ({len(ottelu_strings)})", ottelu_strings)
match_idx = ottelu_strings.index(valittu)
match_id = int(ottelut_sorted.iloc[match_idx]["match_id"])
home_team = ottelut_sorted.iloc[match_idx]["home_team"]
away_team = ottelut_sorted.iloc[match_idx]["away_team"]
home_score = int(ottelut_sorted.iloc[match_idx]["home_score"])
away_score = int(ottelut_sorted.iloc[match_idx]["away_score"])

# ---------------------------------------------------------------------------
# TAPAHTUMAT
# ---------------------------------------------------------------------------
@st.cache_data(show_spinner="Haetaan ottelun tapahtumia...")
def lataa_tapahtumat(m: int) -> pd.DataFrame:
    return hae_tapahtumat(match_id=m)

events = lataa_tapahtumat(match_id)
xg_per = laske_xg_per_joukkue(events)

st.subheader(f"{home_team} {home_score} — {away_score} {away_team}")

c1, c2 = st.columns(2)
with c1:
    h_row = xg_per[xg_per["team"] == home_team]
    if not h_row.empty:
        h_row = h_row.iloc[0]
        st.metric(f"{home_team} StatsBomb xG", f"{h_row['xG']:.2f}")
        st.metric(f"{home_team} laukauksia", int(h_row['shots']))
        st.metric(f"{home_team} maalit", int(h_row['goals']))
with c2:
    a_row = xg_per[xg_per["team"] == away_team]
    if not a_row.empty:
        a_row = a_row.iloc[0]
        st.metric(f"{away_team} StatsBomb xG", f"{a_row['xG']:.2f}")
        st.metric(f"{away_team} laukauksia", int(a_row['shots']))
        st.metric(f"{away_team} maalit", int(a_row['goals']))

yhteen_xg = xg_per["xG"].sum()
yhteen_maalit = xg_per["goals"].sum()
delta = yhteen_maalit - yhteen_xg
if abs(delta) > 0.5:
    suunta = "yli-" if delta > 0 else "ali-"
    st.info(
        f"Ottelussa tehtiin {yhteen_maalit} maalia mutta xG yhteensä oli "
        f"{yhteen_xg:.2f} → joukkueet {suunta}suorittivat {abs(delta):.2f} maalilla."
    )

# Laukaustaulukko
laukaukset = events[events["type"] == "Shot"].copy()
if not laukaukset.empty:
    st.markdown("### Kaikki laukaukset")
    nayta = laukaukset[[
        "minute", "team", "player", "shot_outcome", "shot_statsbomb_xg"
    ]].rename(columns={
        "minute": "Min", "team": "Joukkue", "player": "Pelaaja",
        "shot_outcome": "Lopputulos", "shot_statsbomb_xg": "xG",
    }).round({"xG": 3})
    st.dataframe(nayta.sort_values("Min"), hide_index=True, use_container_width=True, height=300)

# Laukauskartta
st.markdown("### Laukauskartta")
try:
    from mplsoccer import Pitch
    pitch = Pitch(pitch_type="statsbomb", pitch_color="white", line_color="black")
    fig, ax = pitch.draw(figsize=(10, 6))
    for _, r in laukaukset.iterrows():
        if isinstance(r.get("location"), list) and len(r["location"]) == 2:
            x, y = r["location"]
            xg = r.get("shot_statsbomb_xg", 0.05) or 0.05
            koko = (xg * 1500) + 30
            on_maali = r.get("shot_outcome") == "Goal"
            vari = "red" if on_maali else ("blue" if r["team"] == home_team else "orange")
            pitch.scatter(x, y, s=koko, color=vari, alpha=0.7, edgecolor="black", ax=ax)
    ax.set_title(f"{home_team} (sininen) vs {away_team} (oranssi). Maalit punaisella.")
    st.pyplot(fig)
except Exception as e:
    st.warning(f"Laukauskartan piirto ei onnistunut: {e}")
