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

st.set_page_config(page_title="xG comparison", page_icon="📊", layout="wide")
st.title("📊 StatsBomb xG comparison")
st.caption(
    "StatsBomb open data uses an industry-recognized xG model. "
    "Use this page to verify xG values for known matches and mentally compare "
    "them against the model's Understat-based numbers."
)


# ---------------------------------------------------------------------------
# COMPETITIONS — count matches
# ---------------------------------------------------------------------------
@st.cache_data(show_spinner="Fetching competition list...")
def lataa_kilpailut() -> pd.DataFrame:
    return listaa_kilpailut()


@st.cache_data(show_spinner=False)
def laske_ottelumaarat(kilpailut: pd.DataFrame) -> pd.DataFrame:
    """Add ``n_matches`` column — how many matches per competition/season."""
    rivit = []
    progress = st.progress(0.0, text="Counting matches per competition...")
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

st.sidebar.header("Filter")
nayta_kaikki = st.sidebar.checkbox(
    "Show all competitions (including small ones)",
    value=False,
    help="On → show all open StatsBomb competitions. "
         "Off → show only big tournaments (World Cup, Euro, NWSL, La Liga 'Messi data').",
)

if nayta_kaikki:
    st.sidebar.info("Match counts are computed once — takes a few minutes the first time.")
    if st.sidebar.button("📊 Count matches"):
        with st.spinner("Counting..."):
            kilpailut = laske_ottelumaarat(kilpailut)
            st.session_state["lasketut_kilpailut"] = kilpailut
    if "lasketut_kilpailut" in st.session_state:
        kilpailut = st.session_state["lasketut_kilpailut"]
    else:
        kilpailut = kilpailut.copy()
        kilpailut["n_matches"] = -1  # not known yet
else:
    # Filter big tournaments (with at least 10 matches reliably)
    isot = ["FIFA World Cup", "UEFA Euro", "FIFA Women's World Cup",
            "UEFA Women's Euro", "La Liga", "NWSL", "Indian Super League",
            "Premier League", "Bundesliga", "Serie A", "Ligue 1",
            "Africa Cup of Nations", "Copa America", "FA Women's Super League",
            "Liga Profesional", "1. Bundesliga"]
    kilpailut = kilpailut[
        kilpailut["competition_name"].isin(isot)
    ].copy()
    kilpailut["n_matches"] = -1

# Sort newest first
kilpailut = kilpailut.sort_values(["competition_name", "season_id"], ascending=[True, False])

if kilpailut.empty:
    st.warning("No competitions to show. Toggle 'Show all' on.")
    st.stop()

# Show label (match count if known)
def _label(r):
    txt = f"{r['competition_name']} — {r['season_name']}"
    if r.get("n_matches", -1) > 0:
        txt += f" ({int(r['n_matches'])} matches)"
    return txt

kilpailut["_label"] = kilpailut.apply(_label, axis=1)

valinta = st.selectbox("Competition / season", kilpailut["_label"].tolist())
rivi = kilpailut[kilpailut["_label"] == valinta].iloc[0]
comp_id = int(rivi["competition_id"])
season_id = int(rivi["season_id"])

# ---------------------------------------------------------------------------
# MATCHES
# ---------------------------------------------------------------------------
@st.cache_data(show_spinner="Fetching matches...")
def lataa_ottelut(c: int, s: int) -> pd.DataFrame:
    return hae_ottelut(competition_id=c, season_id=s)

try:
    ottelut = lataa_ottelut(comp_id, season_id)
except Exception as e:
    st.error(f"Match fetch failed: {e}")
    st.stop()

if ottelut.empty:
    st.warning("No matches available for this competition.")
    st.stop()

st.success(f"Competition **{rivi['competition_name']} {rivi['season_name']}** has {len(ottelut)} matches available.")

ottelut_sorted = ottelut.sort_values("match_date", ascending=False)
ottelu_strings = (
    ottelut_sorted["match_date"].astype(str) + ": " +
    ottelut_sorted["home_team"] + " vs " + ottelut_sorted["away_team"]
).tolist()
valittu = st.selectbox(f"Select match ({len(ottelu_strings)})", ottelu_strings)
match_idx = ottelu_strings.index(valittu)
match_id = int(ottelut_sorted.iloc[match_idx]["match_id"])
home_team = ottelut_sorted.iloc[match_idx]["home_team"]
away_team = ottelut_sorted.iloc[match_idx]["away_team"]
home_score = int(ottelut_sorted.iloc[match_idx]["home_score"])
away_score = int(ottelut_sorted.iloc[match_idx]["away_score"])

# ---------------------------------------------------------------------------
# TAPAHTUMAT
# ---------------------------------------------------------------------------
@st.cache_data(show_spinner="Fetching match events...")
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
        st.metric(f"{home_team} shots", int(h_row['shots']))
        st.metric(f"{home_team} goals", int(h_row['goals']))
with c2:
    a_row = xg_per[xg_per["team"] == away_team]
    if not a_row.empty:
        a_row = a_row.iloc[0]
        st.metric(f"{away_team} StatsBomb xG", f"{a_row['xG']:.2f}")
        st.metric(f"{away_team} shots", int(a_row['shots']))
        st.metric(f"{away_team} goals", int(a_row['goals']))

yhteen_xg = xg_per["xG"].sum()
yhteen_maalit = xg_per["goals"].sum()
delta = yhteen_maalit - yhteen_xg
if abs(delta) > 0.5:
    suunta = "over" if delta > 0 else "under"
    st.info(
        f"The match had {yhteen_maalit} goals while total xG was "
        f"{yhteen_xg:.2f} → teams {suunta}-performed by {abs(delta):.2f} goals."
    )

# Shot table
laukaukset = events[events["type"] == "Shot"].copy()
if not laukaukset.empty:
    st.markdown("### All shots")
    nayta = laukaukset[[
        "minute", "team", "player", "shot_outcome", "shot_statsbomb_xg"
    ]].rename(columns={
        "minute": "Min", "team": "Team", "player": "Player",
        "shot_outcome": "Outcome", "shot_statsbomb_xg": "xG",
    }).round({"xG": 3})
    st.dataframe(nayta.sort_values("Min"), hide_index=True, use_container_width=True, height=300)

# Shot map
st.markdown("### Shot map")
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
    ax.set_title(f"{home_team} (blue) vs {away_team} (orange). Goals in red.")
    st.pyplot(fig)
except Exception as e:
    st.warning(f"Shot map could not be drawn: {e}")
