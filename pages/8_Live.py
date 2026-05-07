"""
Live-ottelut SofaScoresta + in-play ennuste jaljella olevalle peliajalle.

VAROITUS: SofaScore ei tarjoa virallista APIa. Tama sivu kayttaa epavirallista
reittia. Pida pyynnot harvoina (>=30 s vali) ja kayta vain henkilokohtaiseen
kokeiluun. Jos saat 403:n, SofaScore on muuttanut suojaustaan.
"""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd
import streamlit as st
from scipy.stats import poisson

from src.data.sofascore import (
    hae_live_ottelut,
    parsi_live_ottelut,
    hae_ottelun_tilastot,
)

st.set_page_config(page_title="Live", layout="wide", page_icon="⚽")
st.title("⚽ Live matches + in-play prediction")

st.caption(
    "Lists all matches currently in-play according to SofaScore. "
    "Select a match to see live stats (shots, corners, cards, possession) "
    "and an updated prediction for the remaining time. "
    "**Unofficial API** — refresh sparingly."
)


# ---------------------------------------------------------------------------
# CACHED DATA FETCHERS
# ---------------------------------------------------------------------------
@st.cache_data(ttl=60, show_spinner=False)
def _lataa_live():
    events = hae_live_ottelut()
    df = parsi_live_ottelut(events)
    raw_by_id = {e.get("id"): e for e in events}
    return df, raw_by_id


@st.cache_data(ttl=30, show_spinner=False)
def _lataa_tilastot(match_id: int):
    try:
        return hae_ottelun_tilastot(match_id)
    except Exception as e:
        return {"_error": str(e)}


# ---------------------------------------------------------------------------
# YLAREUNA + PAIVITYS
# ---------------------------------------------------------------------------
top_l, top_r = st.columns([1, 4])
with top_l:
    if st.button("🔄 Refresh list", use_container_width=True):
        _lataa_live.clear()
        st.rerun()
with top_r:
    st.caption(f"Page rendered: {datetime.now().strftime('%H:%M:%S')} • Cache 60 s")

with st.spinner("Fetching live matches…"):
    try:
        df_live, raw_by_id = _lataa_live()
    except Exception as e:
        st.error(f"Live fetch failed: {e}")
        try:
            from src.data.sofascore import _SCRAPER as _scr
            scraper_ok = _scr is not None
        except Exception:
            scraper_ok = False
        if not scraper_ok:
            st.warning(
                "🛠 **cloudscraper library not installed** — it bypasses "
                "SofaScore's Cloudflare protection. Install in your terminal:\n\n"
                "```\npip install cloudscraper\n```\n\n"
                "Then restart Streamlit."
            )
        else:
            st.info(
                "Cloudscraper in use but SofaScore still blocked. "
                "Cloudflare protection may have updated, or too many "
                "requests in a row. Wait a few minutes and try again."
            )
        st.stop()

if df_live.empty:
    st.info("No football matches currently in-play.")
    st.stop()

st.success(f"Found **{len(df_live)}** live matches.")


# ---------------------------------------------------------------------------
# FILTERIT
# ---------------------------------------------------------------------------
fc1, fc2, fc3 = st.columns(3)
maat = sorted([m for m in df_live["country"].dropna().unique().tolist() if m])
turnaukset = sorted([t for t in df_live["tournament"].dropna().unique().tolist() if t])

with fc1:
    valitut_maat = st.multiselect("Countries", maat, default=[])
with fc2:
    valitut_turnaukset = st.multiselect("Tournaments", turnaukset, default=[])
with fc3:
    haku = st.text_input("Search (team name)", "")

df_nayta = df_live.copy()
if valitut_maat:
    df_nayta = df_nayta[df_nayta["country"].isin(valitut_maat)]
if valitut_turnaukset:
    df_nayta = df_nayta[df_nayta["tournament"].isin(valitut_turnaukset)]
if haku:
    h = haku.lower()
    mask = (
        df_nayta["home_team"].str.lower().str.contains(h, na=False)
        | df_nayta["away_team"].str.lower().str.contains(h, na=False)
    )
    df_nayta = df_nayta[mask]

st.markdown(f"**Showing {len(df_nayta)} / {len(df_live)} matches**")

naytto = df_nayta[[
    "country", "tournament", "home_team", "home_score", "away_score",
    "away_team", "status",
]].rename(columns={
    "country": "Country",
    "tournament": "Tournament",
    "home_team": "Home",
    "home_score": "H",
    "away_score": "A",
    "away_team": "Away",
    "status": "Status",
})

st.dataframe(naytto, hide_index=True, use_container_width=True, height=380)


# ---------------------------------------------------------------------------
# OTTELUN VALINTA
# ---------------------------------------------------------------------------
st.divider()
st.subheader("📊 Select a match for detailed view")

valinnat = [
    f"{r['home_team']} {r.get('home_score','?')}-{r.get('away_score','?')} {r['away_team']}  "
    f"({r['tournament']})"
    for _, r in df_nayta.iterrows()
]
if not valinnat:
    st.info("No matches to select — relax the filters.")
    st.stop()

idx_valinta = st.selectbox(
    "Match",
    options=range(len(valinnat)),
    format_func=lambda i: valinnat[i],
)
rivi = df_nayta.iloc[idx_valinta]
match_id = int(rivi["match_id"])


# ---------------------------------------------------------------------------
# MATCH HEADER + MINUTE
# ---------------------------------------------------------------------------
st.markdown(
    f"### {rivi['home_team']} {rivi.get('home_score','?')}-"
    f"{rivi.get('away_score','?')} {rivi['away_team']}"
)
st.caption(
    f"Tournament: {rivi['tournament']} • Country: {rivi['country']} • Status: {rivi['status']}"
)

raw = raw_by_id.get(match_id, {}) or {}


def _arvioi_minuutti(raw_event: dict) -> int | None:
    """Arvioi ottelun minuutti SofaScoren raw-eventista."""
    time_info = raw_event.get("time", {}) or {}
    cur_start = time_info.get("currentPeriodStartTimestamp")
    if cur_start:
        try:
            elapsed = (datetime.now().timestamp() - float(cur_start)) / 60.0
            return int(max(0, min(120, elapsed)))
        except Exception:
            pass
    status = raw_event.get("status", {}) or {}
    code = status.get("code")
    # SofaScoren statuskoodit: 6=1H, 7=2H, 31=HT, 100=FT, 60=postponed
    if code == 6:
        return 30
    if code == 7:
        return 70
    if code == 31:
        return 45
    return None


minuutti_arvio = _arvioi_minuutti(raw)


# ---------------------------------------------------------------------------
# LIVE-TILASTOT
# ---------------------------------------------------------------------------
st.markdown("#### 📈 Live stats")

with st.spinner("Fetching live stats…"):
    statit = _lataa_tilastot(match_id)

if "_error" in statit:
    st.warning(f"Stats not available: {statit['_error']}")
else:
    periods = statit.get("statistics", []) or []
    if not periods:
        st.info("No stats available yet — wait for the first events.")
    else:
        # Use 'ALL' period stats if available
        valittu_per = next((p for p in periods if p.get("period") == "ALL"), periods[0])
        for grp in valittu_per.get("groups", []):
            grp_nimi = grp.get("groupName", "Stats")
            with st.expander(f"📂 {grp_nimi}", expanded=("Shots" in grp_nimi or "Match overview" in grp_nimi)):
                rivit_grp = []
                for it in grp.get("statisticsItems", []):
                    rivit_grp.append({
                        "Stat": it.get("name"),
                        "Home": it.get("home"),
                        "Away": it.get("away"),
                    })
                if rivit_grp:
                    st.dataframe(
                        pd.DataFrame(rivit_grp),
                        hide_index=True, use_container_width=True,
                    )


# ---------------------------------------------------------------------------
# IN-PLAY PREDICTION
# ---------------------------------------------------------------------------
st.divider()
st.subheader("🎯 In-play prediction for the rest of the match")

st.caption(
    "The pre-match Dixon-Coles prediction is scaled to the remaining playing time "
    "and added to the current score. Requires that the selected teams are in "
    "the training data."
)

with st.expander("Model training settings", expanded=True):
    liigat = st.multiselect(
        "Leagues (for the model)",
        options=[
            "ENG-Premier League", "ESP-La Liga", "GER-Bundesliga",
            "ITA-Serie A", "FRA-Ligue 1",
            "ENG-Championship", "ENG-League One",
            "FIN-Veikkausliiga", "SWE-Allsvenskan",
            "NOR-Eliteserien", "DEN-Superliga",
        ],
        default=["ENG-Premier League"],
        key="live_liigat",
        help="Choose the league the match belongs to, so the teams are in the training data.",
    )
    kaudet = st.multiselect(
        "Seasons", ["2324", "2425", "2526"],
        default=["2425", "2526"], key="live_kaudet",
    )
    decay = st.slider(
        "Decay (recency weighting, higher = recent matches weight more)",
        min_value=0.0, max_value=0.01, value=0.0035, step=0.0005,
        format="%.4f", key="live_decay",
    )

# Manual minute if automatic doesn't work
if minuutti_arvio is not None:
    st.metric("Match minute (estimated)", f"{minuutti_arvio}'")
    minuutti_kaytetty = st.slider(
        "Adjust minute if needed",
        0, 90, value=min(90, minuutti_arvio), key="live_minuutti",
    )
else:
    st.info("Minute could not be obtained from SofaScore — enter manually.")
    minuutti_kaytetty = st.slider(
        "Match minute", 0, 90, 45, key="live_minuutti",
    )

if st.button("🚀 Compute in-play prediction", use_container_width=False):
    from src.data.loader import lataa_otteludata
    from src.models.dixon_coles import DixonColesModel

    if not liigat or not kaudet:
        st.error("Select league and season.")
        st.stop()

    with st.spinner("Loading match data and fitting Dixon-Coles…"):
        try:
            df_otts = lataa_otteludata(liigat, kaudet)
        except Exception as e:
            st.error(f"Data load failed: {e}")
            st.stop()
        if df_otts.empty:
            st.error("Match data is empty — try a different league/season.")
            st.stop()
        try:
            dc = DixonColesModel().fit(
                df_otts, decay=decay, date_col="date",
                home_team_col="home_team", away_team_col="away_team",
                home_goals_col="home_score", away_goals_col="away_score",
            )
        except Exception as e:
            st.error(f"Model fitting failed: {e}")
            st.stop()

    koti = rivi["home_team"]
    vieras = rivi["away_team"]

    if koti not in dc.attack:
        # Try fuzzy match
        kandidaatit = [t for t in dc.attack if koti.lower() in t.lower() or t.lower() in koti.lower()]
        if kandidaatit:
            st.info(f"'{koti}' not found exactly — using: {kandidaatit[0]}")
            koti = kandidaatit[0]
        else:
            st.error(
                f"Team '{koti}' not found in model. "
                f"Model has {len(dc.attack)} teams. Check league selection."
            )
            st.stop()
    if vieras not in dc.attack:
        kandidaatit = [t for t in dc.attack if vieras.lower() in t.lower() or t.lower() in vieras.lower()]
        if kandidaatit:
            st.info(f"'{vieras}' not found exactly — using: {kandidaatit[0]}")
            vieras = kandidaatit[0]
        else:
            st.error(
                f"Team '{vieras}' not found in model. "
                f"Model has {len(dc.attack)} teams. Check league selection."
            )
            st.stop()

    # Pre-match xG
    lam, mu = dc.expected_goals(koti, vieras)

    # Jaljella oleva aika (lisapeliaika otetaan huomioon karkeasti minuutilla 90)
    min_jaljella = max(0, 90 - minuutti_kaytetty)
    scale = min_jaljella / 90.0
    lam_left = lam * scale
    mu_left = mu * scale

    # Nykyinen tulos
    try:
        h_now = int(rivi.get("home_score") or 0)
        a_now = int(rivi.get("away_score") or 0)
    except (TypeError, ValueError):
        h_now, a_now = 0, 0

    # Laske jaljella olevien maalien jakauma
    max_g = 8
    h_dist = poisson.pmf(np.arange(max_g + 1), max(0.001, lam_left))
    a_dist = poisson.pmf(np.arange(max_g + 1), max(0.001, mu_left))
    m = np.outer(h_dist, a_dist)
    # Normalisoidaan (tarvittaessa)
    m = m / m.sum()

    # Lopulliset todennakoisyydet (1X2, O/U2.5, BTTS)
    p_h = p_d = p_a = 0.0
    p_over = 0.0
    p_btts_yes = 0.0
    for i in range(max_g + 1):
        for j in range(max_g + 1):
            final_h = h_now + i
            final_a = a_now + j
            p = float(m[i, j])
            if final_h > final_a:
                p_h += p
            elif final_h == final_a:
                p_d += p
            else:
                p_a += p
            if final_h + final_a > 2.5:
                p_over += p
            if final_h >= 1 and final_a >= 1:
                p_btts_yes += p

    p_under = 1.0 - p_over
    p_btts_no = 1.0 - p_btts_yes

    st.markdown(
        f"**Situation:** {koti} **{h_now}-{a_now}** {vieras}  "
        f"• {minuutti_kaytetty}' played, **{min_jaljella}' remaining**"
    )
    st.caption(
        f"Pre-match expected goals: {koti} {lam:.2f} - {mu:.2f} {vieras}  •  "
        f"Remaining-time expected: {lam_left:.2f} - {mu_left:.2f}"
    )

    st.markdown("##### Final-result probabilities")
    c1, c2, c3 = st.columns(3)
    c1.metric(f"1 ({koti})", f"{p_h*100:.1f} %", help=f"Fair odds {1/max(p_h,0.001):.2f}")
    c2.metric("X (Draw)", f"{p_d*100:.1f} %", help=f"Fair odds {1/max(p_d,0.001):.2f}")
    c3.metric(f"2 ({vieras})", f"{p_a*100:.1f} %", help=f"Fair odds {1/max(p_a,0.001):.2f}")

    c4, c5 = st.columns(2)
    c4.metric("Over 2.5 goals", f"{p_over*100:.1f} %", help=f"Fair odds {1/max(p_over,0.001):.2f}")
    c5.metric("Under 2.5 goals", f"{p_under*100:.1f} %", help=f"Fair odds {1/max(p_under,0.001):.2f}")

    c6, c7 = st.columns(2)
    c6.metric("BTTS Yes", f"{p_btts_yes*100:.1f} %", help=f"Fair odds {1/max(p_btts_yes,0.001):.2f}")
    c7.metric("BTTS No", f"{p_btts_no*100:.1f} %", help=f"Fair odds {1/max(p_btts_no,0.001):.2f}")

    st.caption(
        "💡 Model assumption: remaining time is a Poisson distribution with scaled "
        "pre-match xG. Does not account for red cards, substitutions or the fact "
        "that a leading team typically slows down the game."
    )

st.caption("⚠️ Disclaimer: educational app, not investment advice.")
