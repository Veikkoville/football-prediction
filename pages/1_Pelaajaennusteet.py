"""Pelaajaennusteet — toimii xG:n kanssa tai ilman (fallback Goalsiin)."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
import streamlit as st
from scipy.stats import poisson

import config
from src.data.fbref import lataa_pelaajat_kausi

st.set_page_config(page_title="Player predictions", page_icon="⭐", layout="wide")
st.title("⭐ Player-level predictions")
st.caption("Per-90 values → expected goals and anytime scorer %.")


def _flatten(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [
        "_".join([str(x) for x in c]).strip("_") if isinstance(c, tuple) else c
        for c in df.columns
    ]
    return df


@st.cache_data(show_spinner="Loading player data from FBref...")
def lataa(liigat: tuple, kaudet: tuple) -> pd.DataFrame:
    """Yritetään ensin standard, jos xG puuttuu yritetään myös shooting."""
    try:
        std = _flatten(lataa_pelaajat_kausi(
            list(liigat), list(kaudet),
            stat_type="standard",
            cache_dir=config.RAW_DATA_DIR / "fbref",
        ))
    except Exception as e:
        st.error(f"FBref fetch failed: {e}")
        return pd.DataFrame()

    # Jos xG-saraketta ei löydy, kokeile yhdistää shooting-data
    has_xg = any("xG" in str(c) for c in std.columns)
    if not has_xg:
        try:
            sh = _flatten(lataa_pelaajat_kausi(
                list(liigat), list(kaudet),
                stat_type="shooting",
                cache_dir=config.RAW_DATA_DIR / "fbref",
            ))
            avaimet = [c for c in ["league", "season", "team", "player"]
                       if c in std.columns and c in sh.columns]
            if avaimet:
                std = std.merge(sh, on=avaimet, how="outer", suffixes=("", "_sh"))
        except Exception as e:
            st.warning(f"Shooting data did not load: {e}")
    return std


def loyda_xg(df: pd.DataFrame) -> str | None:
    # 1. Tarkka osuma
    for k in ["Expected_xG", "Standard_xG", "xG"]:
        if k in df.columns:
            return k
    # 2. Etsi sarake jossa on tarkalleen "_xG" tai päättyy "xG":hen, mutta ei npxG
    for col in df.columns:
        if not isinstance(col, str):
            continue
        if col == "xG" or col.endswith("_xG"):
            if "npxG" not in col and "xGA" not in col and "/" not in col:
                return col
    # 3. Sumea
    for col in df.columns:
        if not isinstance(col, str):
            continue
        cl = col.lower()
        if "xg" in cl and "xga" not in cl and "npxg" not in cl and "/" not in cl and "+" not in cl:
            return col
    return None


def loyda_xa(df: pd.DataFrame) -> str | None:
    for k in ["Expected_xAG", "Expected_xA", "xAG", "xA"]:
        if k in df.columns:
            return k
    for col in df.columns:
        if isinstance(col, str) and ("xAG" in col or col.endswith("_xA")):
            return col
    return None


def loyda_min(df: pd.DataFrame) -> str | None:
    for k in ["Playing Time_Min", "Playing_Time_Min", "Min", "Minutes"]:
        if k in df.columns:
            return k
    for col in df.columns:
        if isinstance(col, str) and (col.endswith("_Min") or col.endswith("Time_Min")):
            return col
    return None


def loyda_gls(df: pd.DataFrame) -> str | None:
    """Etsi todelliset maalit fallbackiksi."""
    for k in ["Performance_Gls", "Standard_Gls", "Gls", "Goals"]:
        if k in df.columns:
            return k
    for col in df.columns:
        if isinstance(col, str) and (col.endswith("_Gls") or col.endswith("Gls")):
            if "+" not in col and "-" not in col:
                return col
    return None


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------
st.sidebar.header("Data selection")
liigat = st.sidebar.multiselect(
    "Leagues",
    options=["ENG-Premier League", "ESP-La Liga", "GER-Bundesliga",
             "ITA-Serie A", "FRA-Ligue 1",
             "ENG-Championship", "ENG-League One", "ENG-League Two",
             "FIN-Veikkausliiga", "SWE-Allsvenskan",
             "NOR-Eliteserien", "DEN-Superliga"],
    default=["ENG-Premier League"],
)
kaudet = st.sidebar.multiselect("Seasons", ["2324", "2425", "2526"], default=["2425"])

if not liigat or not kaudet:
    st.warning("Select league and season.")
    st.stop()

pelaajat = lataa(tuple(liigat), tuple(kaudet))
if pelaajat.empty:
    st.error("Player data is empty.")
    st.stop()

st.caption(f"Loaded **{len(pelaajat)}** player rows, **{len(pelaajat.columns)}** columns.")

col_minutes = loyda_min(pelaajat)
col_xg = loyda_xg(pelaajat)
col_xa = loyda_xa(pelaajat)
col_gls = loyda_gls(pelaajat)
col_team = "team" if "team" in pelaajat.columns else None
col_player = "player" if "player" in pelaajat.columns else None
col_pos = "pos" if "pos" in pelaajat.columns else None

# Päätä käytetäänkö xG vai todellinen Gls
metriikka = None
metriikka_nimi = None
if col_xg:
    metriikka = col_xg
    metriikka_nimi = "xG"
elif col_gls:
    metriikka = col_gls
    metriikka_nimi = "Goals (xG not available)"

if not col_minutes or not metriikka:
    with st.expander("🔍 Column diagnostics", expanded=True):
        st.warning("Required column missing:")
        st.json({
            "minutes": col_minutes, "xG": col_xg, "xA": col_xa,
            "Gls (fallback)": col_gls,
            "team": col_team, "player": col_player,
        })
        st.markdown("**All columns:**")
        st.code("\n".join(str(c) for c in pelaajat.columns))
    st.stop()

if not col_xg:
    st.info(
        "ℹ️ No xG column found in FBref data — using **actual goals**. "
        "This is a coarser proxy, suitable when sample is small."
    )

# Per-90
df = pelaajat.copy()
df[col_minutes] = pd.to_numeric(df[col_minutes], errors="coerce")
df[metriikka] = pd.to_numeric(df[metriikka], errors="coerce")
df = df[df[col_minutes].fillna(0) >= 270].copy()

if df.empty:
    st.warning("No players ≥ 270 min.")
    st.stop()

df["primary_per90"] = df[metriikka].fillna(0) * 90.0 / df[col_minutes]
if col_xa:
    df[col_xa] = pd.to_numeric(df[col_xa], errors="coerce")
    df["xA_per90"] = df[col_xa].fillna(0) * 90.0 / df[col_minutes]
else:
    df["xA_per90"] = 0.0

# Joukkuevalinta — käytä session_state
joukkueet = sorted(df[col_team].dropna().unique())
joukkue_def = st.session_state.get("koti", joukkueet[0])
joukkue_idx = joukkueet.index(joukkue_def) if joukkue_def in joukkueet else 0

c1, c2 = st.columns(2)
joukkue = c1.selectbox("Team", joukkueet, index=joukkue_idx)
odotetut_minuutit = c2.slider("Expected minutes", 30, 90, 75, 5)

joukkueen_pelaajat = df[df[col_team] == joukkue].copy().sort_values("primary_per90", ascending=False)

st.subheader(f"Predictions — {joukkue}")
skaala = odotetut_minuutit / 90.0
joukkueen_pelaajat["expected_primary"] = joukkueen_pelaajat["primary_per90"] * skaala
joukkueen_pelaajat["expected_xA"] = joukkueen_pelaajat["xA_per90"] * skaala
joukkueen_pelaajat["anytime_scorer_%"] = (
    1 - poisson.pmf(0, joukkueen_pelaajat["expected_primary"].fillna(0))
) * 100

show = [col_player]
if col_pos:
    show.append(col_pos)
show += [col_minutes, "primary_per90", "xA_per90",
         "expected_primary", "expected_xA", "anytime_scorer_%"]
nayta = joukkueen_pelaajat[show].copy()
new_names = ["Player"] + (["Position"] if col_pos else []) + [
    "Min", f"{metriikka_nimi}/90", "xA/90",
    f"Expected {metriikka_nimi}", "Expected xA", "Anytime %"]
nayta.columns = new_names
nayta = nayta.round(3)
st.dataframe(nayta.head(20), hide_index=True, use_container_width=True)

# #13 — Player cards with photos (FPL API)
st.markdown("### 🏃 Top-8 scorers — photo cards")
st.caption("Photos from the Premier League official CDN (FPL). Cards appear if the team is in the PL.")

try:
    from src.viz.player_photos import hae_pelaaja_kortti_html
    top8 = nayta.head(8)
    cols_per_row = 4
    for row_start in range(0, len(top8), cols_per_row):
        cols = st.columns(cols_per_row)
        for i, (_, rivi) in enumerate(top8.iloc[row_start:row_start + cols_per_row].iterrows()):
            with cols[i]:
                kortti_html = hae_pelaaja_kortti_html(
                    rivi["Player"],
                    joukkue=joukkue,
                    xg=float(rivi[f"Expected {metriikka_nimi}"]),
                    stat_label=f"Expected {metriikka_nimi}",
                )
                st.markdown(kortti_html, unsafe_allow_html=True)
except Exception as e:
    st.caption(f"Player cards failed to load: {e}")

st.markdown("### Top-10 anytime scorers")
top10 = nayta.head(10).set_index("Player")["Anytime %"]
st.bar_chart(top10, height=300)

st.caption(
    f"💡 Primary metric used: **{metriikka_nimi}** (column `{metriikka}`). "
    f"Anytime % = 1 − exp(−expected {metriikka_nimi})."
)
