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
st.title("⚽ Live-ottelut + in-play ennuste")

st.caption(
    "Listaa kaikki SofaScoren mukaan parhaillaan kaynnissa olevat ottelut. "
    "Valitse ottelu nahdaksesi live-tilastot (laukaukset, kulmat, kortit, hallinta) "
    "ja saadaksesi paivitetyn ennusteen jaljella olevalle peliajalle. "
    "**Epavirallinen API** — paivita malttisesti."
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
    if st.button("🔄 Paivita lista", use_container_width=True):
        _lataa_live.clear()
        st.rerun()
with top_r:
    st.caption(f"Sivu renderoity: {datetime.now().strftime('%H:%M:%S')} • Cache 60 s")

with st.spinner("Haetaan live-otteluita…"):
    try:
        df_live, raw_by_id = _lataa_live()
    except Exception as e:
        st.error(f"Live-haku epaonnistui: {e}")
        try:
            from src.data.sofascore import _SCRAPER as _scr
            scraper_ok = _scr is not None
        except Exception:
            scraper_ok = False
        if not scraper_ok:
            st.warning(
                "🛠 **cloudscraper-kirjastoa ei ole asennettu** — se kiertaa "
                "SofaScoren Cloudflare-suojauksen. Asenna terminaalissa:\n\n"
                "```\npip install cloudscraper\n```\n\n"
                "Sen jalkeen kaynnista Streamlit uudelleen."
            )
        else:
            st.info(
                "Cloudscraper kayttoiset, mutta SofaScore blokkasi silti. "
                "Cloudflare-suojaus on saattanut paivittya, tai liian monta "
                "pyyntoa peratysti. Odota muutama minuutti ja yrita uudelleen."
            )
        st.stop()

if df_live.empty:
    st.info("Ei kaynnissa olevia jalkapallo-otteluita talla hetkella.")
    st.stop()

st.success(f"Loytyi **{len(df_live)}** kaynnissa olevaa ottelua.")


# ---------------------------------------------------------------------------
# FILTERIT
# ---------------------------------------------------------------------------
fc1, fc2, fc3 = st.columns(3)
maat = sorted([m for m in df_live["country"].dropna().unique().tolist() if m])
turnaukset = sorted([t for t in df_live["tournament"].dropna().unique().tolist() if t])

with fc1:
    valitut_maat = st.multiselect("Maat", maat, default=[])
with fc2:
    valitut_turnaukset = st.multiselect("Turnaukset", turnaukset, default=[])
with fc3:
    haku = st.text_input("Haku (joukkueen nimi)", "")

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

st.markdown(f"**Naytetaan {len(df_nayta)} / {len(df_live)} ottelua**")

naytto = df_nayta[[
    "country", "tournament", "home_team", "home_score", "away_score",
    "away_team", "status",
]].rename(columns={
    "country": "Maa",
    "tournament": "Turnaus",
    "home_team": "Koti",
    "home_score": "K",
    "away_score": "V",
    "away_team": "Vieras",
    "status": "Status",
})

st.dataframe(naytto, hide_index=True, use_container_width=True, height=380)


# ---------------------------------------------------------------------------
# OTTELUN VALINTA
# ---------------------------------------------------------------------------
st.divider()
st.subheader("📊 Valitse ottelu tarkemmaksi tarkasteluksi")

valinnat = [
    f"{r['home_team']} {r.get('home_score','?')}-{r.get('away_score','?')} {r['away_team']}  "
    f"({r['tournament']})"
    for _, r in df_nayta.iterrows()
]
if not valinnat:
    st.info("Ei valittavia otteluita — vapauta filttereita.")
    st.stop()

idx_valinta = st.selectbox(
    "Ottelu",
    options=range(len(valinnat)),
    format_func=lambda i: valinnat[i],
)
rivi = df_nayta.iloc[idx_valinta]
match_id = int(rivi["match_id"])


# ---------------------------------------------------------------------------
# OTTELUN HEADER + MINUUTTI
# ---------------------------------------------------------------------------
st.markdown(
    f"### {rivi['home_team']} {rivi.get('home_score','?')}-"
    f"{rivi.get('away_score','?')} {rivi['away_team']}"
)
st.caption(
    f"Turnaus: {rivi['tournament']} • Maa: {rivi['country']} • Status: {rivi['status']}"
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
st.markdown("#### 📈 Live-tilastot")

with st.spinner("Haetaan live-tilastot…"):
    statit = _lataa_tilastot(match_id)

if "_error" in statit:
    st.warning(f"Tilastoja ei saatu: {statit['_error']}")
else:
    periods = statit.get("statistics", []) or []
    if not periods:
        st.info("Ei tilastoja viela saatavilla — odota ensimmaisia tapahtumia.")
    else:
        # Kayta 'ALL' periodin tilastoja jos saatavilla
        valittu_per = next((p for p in periods if p.get("period") == "ALL"), periods[0])
        for grp in valittu_per.get("groups", []):
            grp_nimi = grp.get("groupName", "Tilastot")
            with st.expander(f"📂 {grp_nimi}", expanded=("Shots" in grp_nimi or "Match overview" in grp_nimi)):
                rivit_grp = []
                for it in grp.get("statisticsItems", []):
                    rivit_grp.append({
                        "Tilasto": it.get("name"),
                        "Koti": it.get("home"),
                        "Vieras": it.get("away"),
                    })
                if rivit_grp:
                    st.dataframe(
                        pd.DataFrame(rivit_grp),
                        hide_index=True, use_container_width=True,
                    )


# ---------------------------------------------------------------------------
# IN-PLAY ENNUSTE
# ---------------------------------------------------------------------------
st.divider()
st.subheader("🎯 In-play ennuste loppuottelulle")

st.caption(
    "Pre-match Dixon-Coles -ennuste skaalataan jaljella olevalle peliajalle "
    "ja lisataan nykyiseen tulokseen. Vaatii etta valitut joukkueet loytyvat "
    "opetusdatasta."
)

with st.expander("Mallin opetusasetukset", expanded=True):
    liigat = st.multiselect(
        "Liigat (mallia varten)",
        options=[
            "ENG-Premier League", "ESP-La Liga", "GER-Bundesliga",
            "ITA-Serie A", "FRA-Ligue 1",
            "ENG-Championship", "ENG-League One",
            "FIN-Veikkausliiga", "SWE-Allsvenskan",
            "NOR-Eliteserien", "DEN-Superliga",
        ],
        default=["ENG-Premier League"],
        key="live_liigat",
        help="Valitse liiga johon ottelu kuuluu, jotta joukkueet ovat opetusdatassa.",
    )
    kaudet = st.multiselect(
        "Kaudet", ["2324", "2425", "2526"],
        default=["2425", "2526"], key="live_kaudet",
    )
    decay = st.slider(
        "Decay (recency-painotus, suurempi = viime ottelut painottuvat enemman)",
        min_value=0.0, max_value=0.01, value=0.0035, step=0.0005,
        format="%.4f", key="live_decay",
    )

# Manuaalinen minuutti jos automaattinen ei toimi
if minuutti_arvio is not None:
    st.metric("Ottelun minuutti (arvioitu)", f"{minuutti_arvio}'")
    minuutti_kaytetty = st.slider(
        "Korjaa minuutti tarvittaessa",
        0, 90, value=min(90, minuutti_arvio), key="live_minuutti",
    )
else:
    st.info("Minuuttia ei saatu SofaScoresta — syota se kasin.")
    minuutti_kaytetty = st.slider(
        "Ottelun minuutti", 0, 90, 45, key="live_minuutti",
    )

if st.button("🚀 Laske in-play ennuste", use_container_width=False):
    from src.data.loader import lataa_otteludata
    from src.models.dixon_coles import DixonColesModel

    if not liigat or not kaudet:
        st.error("Valitse liiga ja kausi.")
        st.stop()

    with st.spinner("Ladataan otteludata ja sovitetaan Dixon-Coles…"):
        try:
            df_otts = lataa_otteludata(liigat, kaudet)
        except Exception as e:
            st.error(f"Datan lataus epaonnistui: {e}")
            st.stop()
        if df_otts.empty:
            st.error("Otteludata on tyhja — kokeile toista liigaa/kautta.")
            st.stop()
        try:
            dc = DixonColesModel().fit(
                df_otts, decay=decay, date_col="date",
                home_team_col="home_team", away_team_col="away_team",
                home_goals_col="home_score", away_goals_col="away_score",
            )
        except Exception as e:
            st.error(f"Mallin opetus epaonnistui: {e}")
            st.stop()

    koti = rivi["home_team"]
    vieras = rivi["away_team"]

    if koti not in dc.attack:
        # Kokeile sumeaa hakua
        kandidaatit = [t for t in dc.attack if koti.lower() in t.lower() or t.lower() in koti.lower()]
        if kandidaatit:
            st.info(f"'{koti}' ei suoraan loydy — kaytetaan: {kandidaatit[0]}")
            koti = kandidaatit[0]
        else:
            st.error(
                f"Joukkue '{koti}' ei loydy mallista. "
                f"Mallissa {len(dc.attack)} joukkuetta. Tarkista liigavalinta."
            )
            st.stop()
    if vieras not in dc.attack:
        kandidaatit = [t for t in dc.attack if vieras.lower() in t.lower() or t.lower() in vieras.lower()]
        if kandidaatit:
            st.info(f"'{vieras}' ei suoraan loydy — kaytetaan: {kandidaatit[0]}")
            vieras = kandidaatit[0]
        else:
            st.error(
                f"Joukkue '{vieras}' ei loydy mallista. "
                f"Mallissa {len(dc.attack)} joukkuetta. Tarkista liigavalinta."
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
        f"**Tilanne:** {koti} **{h_now}-{a_now}** {vieras}  "
        f"• {minuutti_kaytetty}' pelattu, **{min_jaljella}' jaljella**"
    )
    st.caption(
        f"Pre-match odotetut maalit: {koti} {lam:.2f} - {mu:.2f} {vieras}  •  "
        f"Jaljella olevan ajan odotetut: {lam_left:.2f} - {mu_left:.2f}"
    )

    st.markdown("##### Lopullisen tuloksen todennakoisyydet")
    c1, c2, c3 = st.columns(3)
    c1.metric(f"1 ({koti})", f"{p_h*100:.1f} %", help=f"Reilu kerroin {1/max(p_h,0.001):.2f}")
    c2.metric("X (tasapeli)", f"{p_d*100:.1f} %", help=f"Reilu kerroin {1/max(p_d,0.001):.2f}")
    c3.metric(f"2 ({vieras})", f"{p_a*100:.1f} %", help=f"Reilu kerroin {1/max(p_a,0.001):.2f}")

    c4, c5 = st.columns(2)
    c4.metric("Yli 2.5 maalia", f"{p_over*100:.1f} %", help=f"Reilu kerroin {1/max(p_over,0.001):.2f}")
    c5.metric("Alle 2.5 maalia", f"{p_under*100:.1f} %", help=f"Reilu kerroin {1/max(p_under,0.001):.2f}")

    c6, c7 = st.columns(2)
    c6.metric("BTTS Kylla", f"{p_btts_yes*100:.1f} %", help=f"Reilu kerroin {1/max(p_btts_yes,0.001):.2f}")
    c7.metric("BTTS Ei", f"{p_btts_no*100:.1f} %", help=f"Reilu kerroin {1/max(p_btts_no,0.001):.2f}")

    st.caption(
        "💡 Mallin oletus: jaljella oleva aika on Poisson-jakauma skaalatulla "
        "pre-match xG:lla. Ei huomioi punaisia kortteja, vaihtoja eika sita "
        "etta johdossa oleva joukkue tyypillisesti hidastaa peliä."
    )

st.caption("⚠️ Vastuuvapaus: oppimissovellus, ei sijoitusneuvo.")
