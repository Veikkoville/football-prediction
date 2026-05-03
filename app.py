"""
Jalkapallon ennustemalli — paasivu (Ensemble + Auto-konteksti).

Pa-paivan ennusteet pohjautuvat ENSEMBLE:een (Dixon-Coles + LightGBM rolling-form).
Manuaaliset saadot (loukkaantumiset, motivaatio, sa, lepoetu, derby) joko taytetaan
automaattisesti otteludatasta tai sa-API:sta — kayttaja voi yliajaa.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np
import pandas as pd
import streamlit as st

import config
from src.data.loader import lataa_otteludata, lataa_otteludata_yksityiskohtaisesti
from src.features.team_features import (
    laajenna_per_joukkue, rolling_keskiarvo, yhdista_ottelutasolle, lisaa_1x2,
)
from src.features.poissaolot import laske_poissaolovaikutus
from src.features.auto_context import (
    on_derby, laske_lepopaivat, laske_sarjataulukko, arvioi_motivaatio,
    hae_saa, saa_to_total_goals_delta, joukkueen_kaupunki,
)
from src.models.dixon_coles import DixonColesModel, apply_match_adjustments
from src.models.outcome_model import opeta_1x2
from src.models.ensemble import yhdista_1x2
from src.models.value import vertaile_kertoimia, marginaali
from src.models.main_calibrator import kouluta_kalibraattori
from src.models.totals_classifier import opeta_totals_classifier, ennusta_totals
import numpy as _np_for_cal

st.set_page_config(page_title="Jalkapallon ennustemalli", page_icon="⚽", layout="wide")


# ---------------------------------------------------------------------------
# SALASANASUOJAUS (vain jos APP_PASSWORD on asetettu st.secrets:iin)
# ---------------------------------------------------------------------------
def _check_password() -> bool:
    """
    Yksinkertainen salasanasuojaus. Aktiivinen jos APP_PASSWORD on st.secrets:issa.
    Lokaalisti (.env / ei secretsia) suojausta ei ole.
    """
    import hmac
    try:
        oikea_salasana = st.secrets.get("APP_PASSWORD")
    except Exception:
        oikea_salasana = None
    if not oikea_salasana:
        return True  # Ei salasanaa asetettu -> vapaa pasy

    if st.session_state.get("password_correct", False):
        return True

    def _password_entered():
        if hmac.compare_digest(
            st.session_state.get("password", ""), str(oikea_salasana)
        ):
            st.session_state["password_correct"] = True
            del st.session_state["password"]
        else:
            st.session_state["password_correct"] = False

    st.title("⚽ Jalkapallon ennustemalli")
    st.text_input(
        "Salasana", type="password",
        on_change=_password_entered, key="password",
    )
    if "password_correct" in st.session_state and not st.session_state["password_correct"]:
        st.error("❌ Vaara salasana.")
    return False


if not _check_password():
    st.stop()


st.title("⚽ Jalkapallon ennustemalli")
st.caption(
    "Ensemble-ennuste = Dixon-Coles (pitka historia) + LightGBM (viime 5 ottelua). "
    "Auto-konteksti tayttaa lepopaivat, sarjasijan, derbyn ja saan — yliajettavissa."
)


# ---------------------------------------------------------------------------
# DATA + MOLEMMAT MALLIT YHDESSA
# ---------------------------------------------------------------------------
@st.cache_resource(show_spinner="Sovitetaan Dixon-Coles + LightGBM...")
def opeta_kaikki(liigat: tuple, kaudet: tuple, decay: float, nopea: bool = False,
                 bayes_shrinkage: float = 2.0,
                 kayta_promotio_priorit: bool = False,
                 promotion_factor: float = 0.5,
                 xg_weight: float = 0.0,
                 form_blend: float = 0.0,
                 model_type: str = "dc"):
    tulos = lataa_otteludata_yksityiskohtaisesti(list(liigat), list(kaudet))
    treenidata = tulos.data
    if treenidata.empty:
        viestit = "\n".join(f"- **{l}**: {e}" for l, e in tulos.virheet.items())
        raise RuntimeError(
            "Datan lataus palautti tyhjan DataFramen.\n\n"
            "Yksityiskohdat per liiga:\n" + viestit
        )

    # Promotoitujen joukkueiden priorit alasarjasta (jos paalla)
    team_priors_yhd: dict = {}
    if kayta_promotio_priorit:
        try:
            from src.models.promotion_priors import laske_alasarjapriorit, PROMOTIO_KETJU
            # Etsi viimeinen kausi kayttoon — alasarjadata haetaan tata edeltavalta
            kaudet_sort = sorted(kaudet)
            if len(kaudet_sort) >= 1:
                # Kaudet ovat YYMM-muodossa, esim "2526"
                # Edellinen kausi = decrement
                viimeinen = kaudet_sort[-1]
                try:
                    yy = int(viimeinen[:2])
                    edellinen_kausi = f"{yy-1:02d}{yy:02d}"
                except Exception:
                    edellinen_kausi = None
                if edellinen_kausi:
                    for liiga in liigat:
                        if liiga in PROMOTIO_KETJU:
                            try:
                                p = laske_alasarjapriorit(
                                    yliliiga=liiga,
                                    nykyiset_kaudet=list(kaudet),
                                    edellinen_kausi=edellinen_kausi,
                                    promotion_factor=promotion_factor,
                                )
                                team_priors_yhd.update(p)
                            except Exception as e:
                                print(f"Promotio-priori epaonnistui {liiga}: {e}")
        except Exception as e:
            print(f"Promotio-prior moduuli epaonnistui: {e}")

    # xG-sarakkeet ovat olemassa Understat-otteluille — vain niille xG-likelihood
    has_xg_cols = "home_xg" in treenidata.columns and "away_xg" in treenidata.columns
    dc = DixonColesModel().fit(
        treenidata,
        home_team_col="home_team", away_team_col="away_team",
        home_goals_col="home_score", away_goals_col="away_score",
        decay=decay, date_col="date",
        l2_attack_defence=bayes_shrinkage,
        team_priors=team_priors_yhd if team_priors_yhd else None,
        home_xg_col="home_xg" if has_xg_cols else None,
        away_xg_col="away_xg" if has_xg_cols else None,
        xg_weight=xg_weight,
        model_type=model_type,
    )
    dc.team_priors_kaytetty = team_priors_yhd

    # Dynamic DC: jos form_blend > 0, sovita toinen DC nopealla decay:lla
    # ja yhdista joukkue-vahvuudet form-painon mukaan.
    if form_blend > 0:
        try:
            decay_nopea = max(decay * 4.0, 0.012)  # ~58 paivan puolittumisaika
            dc_form = DixonColesModel().fit(
                treenidata,
                home_team_col="home_team", away_team_col="away_team",
                home_goals_col="home_score", away_goals_col="away_score",
                decay=decay_nopea, date_col="date",
                l2_attack_defence=bayes_shrinkage,
                team_priors=team_priors_yhd if team_priors_yhd else None,
                home_xg_col="home_xg" if has_xg_cols else None,
                away_xg_col="away_xg" if has_xg_cols else None,
                xg_weight=xg_weight,
                model_type=model_type,
            )
            # Blendaa: uusi attack = baseline + form_blend * (form - baseline)
            for j in dc.attack:
                if j in dc_form.attack:
                    dc.attack[j] = dc.attack[j] + form_blend * (dc_form.attack[j] - dc.attack[j])
                if j in dc_form.defence:
                    dc.defence[j] = dc.defence[j] + form_blend * (dc_form.defence[j] - dc.defence[j])
            dc.form_blend_kaytetty = form_blend
            dc.dc_form_baseline = dc_form  # debug-tarkoituksiin
        except Exception as e:
            print(f"Form-blend epaonnistui: {e}")

    # LightGBM tarvitsee xG-piirteet -> vain Understat-otteluille
    us_only = treenidata[treenidata["home_xg"].notna()].copy()
    lgb = None
    feature_cols = None
    viimeisimmat = None
    if len(us_only) >= 50:
        joukkue_ottelu = laajenna_per_joukkue(us_only)
        joukkue_ottelu["xg_for"] = np.where(
            joukkue_ottelu["is_home"] == 1, joukkue_ottelu["home_xg"], joukkue_ottelu["away_xg"])
        joukkue_ottelu["xg_against"] = np.where(
            joukkue_ottelu["is_home"] == 1, joukkue_ottelu["away_xg"], joukkue_ottelu["home_xg"])
        piirteet = ["goals_for", "goals_against", "xg_for", "xg_against"]
        joukkue_ottelu = rolling_keskiarvo(joukkue_ottelu, piirteet, ikkuna=5)
        rolling_cols = [f"{p}_rolling5" for p in piirteet]
        ottelutaso = yhdista_ottelutasolle(joukkue_ottelu, rolling_cols)
        ottelutaso = lisaa_1x2(ottelutaso)
        feature_cols = [c for c in ottelutaso.columns if "rolling5" in c]
        train = ottelutaso.dropna(subset=feature_cols)
        if len(train) >= 50:
            lgb = opeta_1x2(train[feature_cols], train["result_1x2"], num_boost_round=200)
            viimeisimmat = (
                joukkue_ottelu.dropna(subset=rolling_cols)
                .sort_values("date").groupby("team")
                .tail(1)[["team"] + rolling_cols].set_index("team")
            )
    # Kouluta kalibraattori sisaisesti (vain jos riittavasti dataa ja ei nopea-tila)
    cal = None
    if len(treenidata) >= 500 and not nopea:
        try:
            cal = kouluta_kalibraattori(
                treenidata, decay=decay,
                min_train_size=min(380, len(treenidata) // 3),
                refit_every_days=56,  # Nostettu 28 -> 56 nopeuden vuoksi
            )
        except Exception as e:
            print(f"Kalibraattorin koulutus epaonnistui: {e}")

    # Kouluta erillinen totals-classifier (skipataan nopea-tilassa)
    totals_booster, totals_fc, totals_vm = None, None, None
    if len(us_only) >= 200 and not nopea:
        try:
            totals_booster, totals_fc, totals_vm = opeta_totals_classifier(
                us_only, line=2.5,
            )
        except Exception as e:
            print(f"Totals-classifier epaonnistui: {e}")

    # Lataa pelaajadata (FBref) — kaytetaan poissaolopaneeliin (vain top-5 -liigoille)
    pelaajat = None
    try:
        from src.data.fbref import lataa_pelaajat_kausi
        us_liigat_in_data = [l for l in liigat if l in {
            "ENG-Premier League", "ESP-La Liga", "GER-Bundesliga",
            "ITA-Serie A", "FRA-Ligue 1",
        }]
        if us_liigat_in_data:
            kayt_kaudet = list(kaudet[-2:])  # vain 2 viimeisinta kautta

            def _flatten(df):
                df = df.copy()
                df.columns = [
                    "_".join([str(x) for x in c]).strip("_") if isinstance(c, tuple) else c
                    for c in df.columns
                ]
                return df

            # standard: Playing Time_Min, Performance_Gls
            pelaajat_std = _flatten(lataa_pelaajat_kausi(
                us_liigat_in_data, kayt_kaudet, stat_type="standard",
                cache_dir=config.RAW_DATA_DIR / "fbref",
            ))

            # shooting: Expected_xG (mergetaan jos onnistuu)
            try:
                pelaajat_sho = _flatten(lataa_pelaajat_kausi(
                    us_liigat_in_data, kayt_kaudet, stat_type="shooting",
                    cache_dir=config.RAW_DATA_DIR / "fbref",
                ))
                # Mergetaan vain ne sarakkeet joita ei viela ole standardissa
                avain = [c for c in ["league", "season", "team", "player"] if c in pelaajat_std.columns and c in pelaajat_sho.columns]
                if avain:
                    uudet_col = [c for c in pelaajat_sho.columns if c not in pelaajat_std.columns]
                    pelaajat = pelaajat_std.merge(
                        pelaajat_sho[avain + uudet_col], on=avain, how="left"
                    )
                else:
                    pelaajat = pelaajat_std
            except Exception as e:
                print(f"Shooting-stat lataus epaonnistui, kaytetaan vain standardia: {e}")
                pelaajat = pelaajat_std
    except Exception as e:
        print(f"Pelaajadatan lataus epaonnistui: {e}")

    return dc, lgb, feature_cols, viimeisimmat, treenidata, cal, totals_booster, totals_fc, totals_vm, pelaajat


# ---------------------------------------------------------------------------
# SIVUPALKKI
# ---------------------------------------------------------------------------
st.sidebar.header("Datan valinta")
us_liigat = st.sidebar.multiselect(
    "Top-5 -liigat (Understat, xG)",
    options=["ENG-Premier League", "ESP-La Liga", "GER-Bundesliga", "ITA-Serie A", "FRA-Ligue 1"],
    default=["ENG-Premier League"],
)
fb_liigat = st.sidebar.multiselect(
    "Muut liigat (football-data.co.uk, ei xG)",
    options=[
        # Englannin alasarjat
        "ENG-Championship", "ENG-League One", "ENG-League Two",
        # Muu Eurooppa
        "ESP-La Liga 2", "GER-2. Bundesliga", "ITA-Serie B", "FRA-Ligue 2",
        "POR-Primeira Liga", "NED-Eredivisie", "BEL-Pro League",
        "SCO-Premiership", "TUR-Super Lig", "GRE-Super League",
        # Pohjoismaat (kaikki kaudet yhdessa)
        "FIN-Veikkausliiga", "SWE-Allsvenskan", "NOR-Eliteserien", "DEN-Superliga",
        # Muut maailman sarjat
        "USA-MLS", "MEX-Liga MX", "JPN-J1 League", "BRA-Serie A", "ARG-Primera Division",
        # UEFA-turnaukset (football-data.org tai openfootball)
        "INT-Champions League", "INT-Europa League", "INT-Conference League",
    ],
    default=[],
    help="Englannin alasarjat ja Pohjoismaat football-data.co.uk:sta. "
         "UEFA-turnaukset ensisijaisesti football-data.org API:n kautta jos "
         "FOOTBALL_DATA_API_KEY on .env-tiedostossa, fallbackina openfootball.",
)
liiga_valinta = us_liigat + fb_liigat

kausi_valinta = st.sidebar.multiselect(
    "Kaudet", options=["2122", "2223", "2324", "2425", "2526"],
    default=["2223", "2324", "2425", "2526"],
    help="Useampi kausi -> vakaampi joukkuekohtainen kotietu. Decay painottaa "
         "silti tuoreita otteluita.",
)

# API-avaimen tila
from src.data.football_data_org import api_key_kunnossa
if api_key_kunnossa():
    st.sidebar.success("✅ football-data.org API-avain loytyy")
else:
    st.sidebar.info(
        "ℹ️ football-data.org API-avainta ei loydy. UEL/UECL-data ei ole "
        "saatavilla. Lisaa `.env`-tiedostoon: `FOOTBALL_DATA_API_KEY=oma_avaimesi`"
    )

st.sidebar.divider()
st.sidebar.markdown("**Mallin parametrit**")
decay_val = st.sidebar.slider(
    "Decay (aikapainotus)", 0.0, 0.020, 0.0035, 0.0005, format="%.4f",
)
puoli = (np.log(2) / decay_val) if decay_val > 0 else float("inf")
st.sidebar.caption(f"Puolittumisaika: ~{puoli:.0f} paivaa" if puoli != float("inf") else "Ei aikapainotusta")

bayes_shrink = st.sidebar.slider(
    "Bayes-shrinkage (joukkuevahvuudet)", 0.0, 10.0, 2.0, 0.5,
    help="Vetaa hyokkays/puolustus-estimaatit kohti liigan keskiarvoa. "
         "0 = pure ML (vanha kayttaytyminen), 2 = oletus, 5 = vahva (auttaa "
         "uusille joukkueille kuten Sunderland), 10 = hyvin vahva.",
)

xg_weight_val = st.sidebar.slider(
    "xG-paino likelihood:ssa", 0.0, 1.0, 0.0, 0.05,
    help="0 = vain toteutuneet maalit (vanha kayttaytyminen), 0.3-0.5 = "
         "tasapaino maalit + xG, 1.0 = vain xG. Vaikutus: mallin estimaatit "
         "siloittuvat luck-tekijoita kohti. Toimii vain Understat-liigoissa "
         "(top-5) joissa xG on saatavilla.",
)

form_blend_val = st.sidebar.slider(
    "Form-paino (Dynamic DC)", 0.0, 1.0, 0.0, 0.05,
    help="0 = vain pitkan aikavalin baseline (decay-arvosi), 0.3 = lisaa "
         "viimeaikaista muoto-painotusta, 1.0 = vain viime ottelut. Sovittaa "
         "toisen DC:n nopeammalla decaylla ja blendaa joukkuevahvuudet "
         "(huomioi tuoreet vammat, valmentajavaihdokset, momentum).",
)

model_type_val = st.sidebar.selectbox(
    "Mallityyppi", ["dc", "bivariate_poisson"],
    format_func=lambda x: "Dixon-Coles (oletus)" if x == "dc" else "Bivariate Poisson",
    help="Dixon-Coles: standardi tau-korjauksella matalille tuloksille. "
         "Bivariate Poisson: jaettu Z-komponentti, matemaattisesti elegantimpi "
         "korrelaation kasittely. BP on hitaampi (~5x) mutta voi antaa hieman "
         "tarkempia ennusteita.",
)

kayta_promotio_priorit = st.sidebar.toggle(
    "🆙 Promotoitujen prior alasarjasta",
    value=False,
    help="Sovittaa erillisen DC-mallin alasarjadataan ja kayttaa promotoitujen "
         "joukkueiden estimaatteja prior:ana yliliigan mallissa. Toimii vain "
         "Englannin liigaketjussa (PL <- Championship <- League One <- League Two). "
         "Lisaa latausaikaan ~10 sekuntia. Hyodyllinen kun tasalla on uusia "
         "joukkueita kuten Sunderland 2526.",
)
promotion_factor_val = 0.5
if kayta_promotio_priorit:
    promotion_factor_val = st.sidebar.slider(
        "Promotion factor (alasarjasta -> ylaliiga)", 0.0, 1.0, 0.5, 0.05,
        help="Skaalauskerroin: 1.0 = priorit suoraan alasarjaestimaatista, "
             "0.5 = puolet (varovainen, kompensoi tasoeroa), 0.0 = ei prioria. "
             "Empiirinen tutkimus suosittelee 0.4-0.6.",
    )

# Kalibraattorin tila — nakyy kun malli on koulutettu
if "cal_status_msg" in st.session_state:
    st.sidebar.markdown(st.session_state["cal_status_msg"])

kayta_kalibrointia = st.sidebar.toggle(
    "🎯 Kayta kalibroituja todennakoisyyksia",
    value=True,
    help="Sisaisesti opetettu kalibraattori korjaa mallin yli-/ali-itsevarmuuden. "
         "Tekee todennakoisyyksista luotettavampia.",
)

ensemble_paino_oletus = st.session_state.get("optim_paino", 0.5)
ensemble_paino = st.sidebar.slider(
    "Ensemble-paino (Dixon-Coles)", 0.0, 1.0, ensemble_paino_oletus, 0.05,
    help="0 = pelkka LightGBM (form), 1 = pelkka Dixon-Coles (historia), 0.5 = tasapaino. "
         "Voit optimoida painon walk-forwardilla alaosan paneelista.",
)
if "optim_paino" in st.session_state:
    st.sidebar.caption(
        f"🎯 Walk-forward suositus: **{st.session_state['optim_paino']:.2f}** "
        f"({st.session_state.get('optim_n', '?')} OOS-ennustetta)"
    )

nopea_tila = st.sidebar.toggle(
    "⚡ Nopea-tila",
    value=False,
    help="Ohita kalibraattorin ja totals-classifierin koulutus -> mallin lataus "
         "puolet nopeammin (~30s saastoa). Hyodyllinen kun iteroit eri liigojen valilla. "
         "Tarkista ennusteet pois paalta kun olet valmis.",
)

if st.sidebar.button("🔄 Paivita malli"):
    st.cache_resource.clear()
    st.rerun()

if not liiga_valinta or not kausi_valinta:
    st.warning("Valitse liiga ja kausi sivupalkista.")
    st.stop()

try:
    (dc, lgb, feature_cols, viimeisimmat, hist_data,
     cal, totals_booster, totals_fc, totals_vm, pelaajat) = opeta_kaikki(
        tuple(liiga_valinta), tuple(kausi_valinta), float(decay_val), bool(nopea_tila),
        float(bayes_shrink),
        bool(kayta_promotio_priorit),
        float(promotion_factor_val),
        float(xg_weight_val),
        float(form_blend_val),
        str(model_type_val),
    )
except Exception as e:
    st.error(f"Mallin lataus epaonnistui: {e}")
    st.stop()

# Paivita kalibraattorin tila sivupalkkiin
n_matches = len(hist_data)
if cal is None:
    if n_matches < 500:
        st.session_state["cal_status_msg"] = (
            f"⚠️ **Kalibraattori**: ei opetettu — vain {n_matches} ottelua, "
            "tarvitaan ≥ 500."
        )
    else:
        st.session_state["cal_status_msg"] = (
            f"⚠️ **Kalibraattori**: koulutus epaonnistui ({n_matches} ottelua datassa). "
            "Tarkista terminaalin lokit virheviesteille."
        )
elif hasattr(cal, "cal_1x2") and hasattr(cal, "cal_ou"):
    a = "✅" if cal.cal_1x2 is not None else "❌"
    b = "✅" if cal.cal_ou is not None else "❌"
    st.session_state["cal_status_msg"] = (
        f"**Kalibraattori (MainCalibrators):**\n\n{a} 1X2 • {b} O/U 2.5 "
        f"_(opetettu {n_matches} ottelusta)_"
    )
else:
    st.session_state["cal_status_msg"] = (
        "⚠️ **Kalibraattori (vanha)**: vain 1X2. Paina '🔄 Paivita malli' "
        "saadaksesi uuden MainCalibrators-version (1X2 + O/U)."
    )

joukkueet = sorted(dc.teams_)


# ---------------------------------------------------------------------------
# JOUKKUEIDEN VALINTA — jaetaan session_statella muille sivuille
# ---------------------------------------------------------------------------
st.subheader("Valitse ottelu")
c1, c2, c3 = st.columns([5, 1, 5])
with c1:
    koti = st.selectbox("🏠 Kotijoukkue", joukkueet,
                        index=joukkueet.index(st.session_state.get("koti", joukkueet[0]))
                        if st.session_state.get("koti") in joukkueet else 0,
                        key="koti")
with c2:
    st.markdown("<h2 style='text-align:center;margin-top:30px;'>vs</h2>", unsafe_allow_html=True)
with c3:
    vieras_def = st.session_state.get("vieras", joukkueet[1] if len(joukkueet) > 1 else joukkueet[0])
    vieras_idx = joukkueet.index(vieras_def) if vieras_def in joukkueet else 1
    vieras = st.selectbox("✈️ Vierasjoukkue", joukkueet, index=vieras_idx, key="vieras")

if koti == vieras:
    st.warning("Valitse kaksi eri joukkuetta.")
    st.stop()


# ---------------------------------------------------------------------------
# AUTO-KONTEKSTI
# ---------------------------------------------------------------------------
st.divider()
ottelu_paiva = st.date_input("Ottelun paiva", value=datetime.now().date())
ottelu_dt = datetime.combine(ottelu_paiva, datetime.min.time())

@st.cache_data(show_spinner=False)
def _cached_lepopaivat(_df, team, dt):
    return laske_lepopaivat(_df, team, dt)

# Lepopaivat (cachettu)
home_rest = _cached_lepopaivat(hist_data, koti, ottelu_dt)
away_rest = _cached_lepopaivat(hist_data, vieras, ottelu_dt)
rest_diff = (home_rest or 0) - (away_rest or 0)

# Sarjataulukko — etsi liiga+kausi jossa MOLEMMAT joukkueet pelaavat
def _yhteinen_liiga_ja_kausi(df, h_team, a_team, ennen):
    """Etsi tuorein liiga+kausi jossa molemmat joukkueet ovat olleet."""
    if df.empty or "league" not in df.columns or "season" not in df.columns:
        return None, None
    omat_h = df[(df["home_team"] == h_team) | (df["away_team"] == h_team)]
    omat_a = df[(df["home_team"] == a_team) | (df["away_team"] == a_team)]
    if omat_h.empty or omat_a.empty:
        return None, None
    yhteiset = (
        set(zip(omat_h["league"].astype(str), omat_h["season"].astype(str))) &
        set(zip(omat_a["league"].astype(str), omat_a["season"].astype(str)))
    )
    if not yhteiset:
        return None, None
    rivit = []
    for liiga, kausi in yhteiset:
        m = df[(df["league"].astype(str) == liiga) & (df["season"].astype(str) == kausi)]
        if not m.empty:
            rivit.append((m["date"].max(), liiga, kausi))
    rivit.sort(reverse=True)
    return rivit[0][1], rivit[0][2]


@st.cache_data(show_spinner=False)
def _cached_yhteinen_liiga_kausi(_df, h, a, dt):
    return _yhteinen_liiga_ja_kausi(_df, h, a, dt)

@st.cache_data(show_spinner=False)
def _cached_sarjataulukko(_df, league, season, dt):
    return laske_sarjataulukko(_df, league=league, season=season, ottelu_paiva=dt)

sel_liiga, sel_kausi = _cached_yhteinen_liiga_kausi(hist_data, koti, vieras, ottelu_dt)
table_h = _cached_sarjataulukko(hist_data, sel_liiga, sel_kausi, ottelu_dt)
mot_home = arvioi_motivaatio(table_h, koti)
mot_away = arvioi_motivaatio(table_h, vieras)

# Derby
derby_auto = on_derby(koti, vieras)

# Saa
hae_saa_btn = st.checkbox("🌤️ Hae sa kotijoukkueen kaupungista", value=False)
saa_delta = 0.0
saa_info = None
if hae_saa_btn:
    kaupunki = joukkueen_kaupunki(koti)
    saa_info = hae_saa(kaupunki, ottelu_dt)
    saa_delta = saa_to_total_goals_delta(saa_info)


with st.expander("🤖 Auto-tunnistettu konteksti (yliajettavissa alla)", expanded=True):
    aa, bb, cc = st.columns(3)
    aa.metric(f"{koti} lepopaivat", f"{home_rest if home_rest is not None else '?'} pv")
    bb.metric(f"{vieras} lepopaivat", f"{away_rest if away_rest is not None else '?'} pv")
    cc.metric("Lepoetu kotille", f"{rest_diff:+d} pv")

    dd, ee, ff = st.columns(3)
    if not table_h.empty and koti in table_h["team"].values:
        h_pos = int(table_h[table_h["team"] == koti].iloc[0]["position"])
        dd.metric(f"{koti} sarjasija", f"{h_pos}.")
    if not table_h.empty and vieras in table_h["team"].values:
        a_pos = int(table_h[table_h["team"] == vieras].iloc[0]["position"])
        ee.metric(f"{vieras} sarjasija", f"{a_pos}.")
    if sel_liiga and sel_kausi:
        st.caption(f"Sarjataulukko laskettu: **{sel_liiga}** kaudelta **{sel_kausi}** "
                   f"(otteluita: {len(table_h)*2} per joukkue keskimaarin).")
    else:
        st.caption("⚠️ Joukkueille ei loytynyt yhteista liigaa+kautta — sarjasija perustuu kaikkiin otteluihin.")
    ff.metric("Derby?", "Kylla 🔥" if derby_auto else "Ei")

    if saa_info and "error" not in saa_info:
        st.success(
            f"🌤️ {joukkueen_kaupunki(koti)}: {saa_info['desc']}, "
            f"{saa_info['temp_c']}°C, sade {saa_info['rain_mm']}mm, tuuli {saa_info['wind_kph']}km/h "
            f"-> sa-vaikutus kokonaismaaleihin: {saa_delta:+.2f}"
        )
    elif saa_info:
        st.warning(f"Sa-haku epaonnistui: {saa_info['error']}")


# ---------------------------------------------------------------------------
# MANUAALINEN SAATOPANEELI — tayttaa auto-arvot, kayttaja yliajaa
# ---------------------------------------------------------------------------
with st.expander("🛠️ Manuaaliset saadot (yliaja auto-arvot)", expanded=False):
    s1, s2 = st.columns(2)
    with s1:
        st.markdown(f"**🏠 {koti}**")
        home_injury = st.slider("Avainpelaajia poissa %", -30, 0, 0, 5, key="hi")
        home_motivation = st.slider("Motivaatio %", -15, 15, mot_home, 5, key="hm")
    with s2:
        st.markdown(f"**✈️ {vieras}**")
        away_injury = st.slider("Avainpelaajia poissa %", -30, 0, 0, 5, key="ai")
        away_motivation = st.slider("Motivaatio %", -15, 15, mot_away, 5, key="am")

    s3, s4, s5 = st.columns(3)
    rest_advantage = s3.slider("Lepoetu kotille (pv)", -5, 5, max(-5, min(5, rest_diff)), 1)
    is_derby_ui = s4.toggle("Derby", value=derby_auto)
    weather_delta = s5.number_input("Sa -> kokonaismaalit", -1.0, 0.5, value=float(saa_delta), step=0.1)

    # POISSAOLOPANEELI — pelaajien nimien perusteella laskettu xG-vaikutus
    if pelaajat is not None and not pelaajat.empty:
        st.markdown("---")
        st.markdown("**🏥 Poissaolot (auto-laskenta xG:sta)**")
        st.caption(
            "Kirjoita poissa olevien pelaajien nimet pilkulla erotettuna. "
            "Sovellus etsii heidat FBref-pelaajadatasta ja laskee menetetyn xG-osuuden. "
            "Korvaaja oletetaan tuottavan 30% poissa olevan tasosta -> nettovaikutus n. 70%."
        )
        from src.features.poissaolot import laske_poissaolovaikutus

        # Aggressiivinen sarakehaku (sama logiikka kuin pages/1_Pelaajaennusteet.py)
        def _loyda_xg(df):
            for k in ["Expected_xG", "Standard_xG", "xG"]:
                if k in df.columns:
                    return k
            for col in df.columns:
                if not isinstance(col, str):
                    continue
                if col == "xG" or col.endswith("_xG"):
                    if "npxG" not in col and "xGA" not in col and "/" not in col:
                        return col
            for col in df.columns:
                if not isinstance(col, str):
                    continue
                cl = col.lower()
                if "xg" in cl and "xga" not in cl and "npxg" not in cl and "/" not in cl and "+" not in cl:
                    return col
            return None

        def _loyda_min(df):
            for k in ["Playing Time_Min", "Playing_Time_Min", "Min", "Minutes"]:
                if k in df.columns:
                    return k
            for col in df.columns:
                if isinstance(col, str) and (col.endswith("_Min") or col.endswith("Time_Min")):
                    return col
            for col in df.columns:
                if isinstance(col, str) and "min" in col.lower() and "ball" not in col.lower():
                    return col
            return None

        def _loyda_gls(df):
            for k in ["Performance_Gls", "Standard_Gls", "Gls", "Goals"]:
                if k in df.columns:
                    return k
            for col in df.columns:
                if isinstance(col, str) and (col.endswith("_Gls") or col == "Gls"):
                    if "+" not in col and "-" not in col and "/" not in col:
                        return col
            return None

        col_min = _loyda_min(pelaajat)
        col_xg = _loyda_xg(pelaajat)
        # Fallback: jos xG puuttuu, kaytetaan todellisia maaleja (Performance_Gls)
        metriikka_nimi = "xG"
        if not col_xg:
            col_xg = _loyda_gls(pelaajat)
            if col_xg:
                metriikka_nimi = "maaleja"

        # xG/Gls riittaa, minuutit eivat ole pakollisia poissaololaskennassa
        if col_xg:
            st.caption(
                f"Metriikka: **{metriikka_nimi}** ({col_xg})"
                + (f" • Minuutit: {col_min}" if col_min else "")
            )
            po1, po2 = st.columns(2)
            poissa_koti_str = po1.text_input(
                f"🏠 {koti} poissa pelaajat",
                placeholder="esim. Saka, Saliba",
                key="poissa_koti",
            )
            poissa_vieras_str = po2.text_input(
                f"✈️ {vieras} poissa pelaajat",
                placeholder="esim. Watkins",
                key="poissa_vieras",
            )

            poissa_koti_lista = [p.strip() for p in poissa_koti_str.split(",") if p.strip()]
            poissa_vieras_lista = [p.strip() for p in poissa_vieras_str.split(",") if p.strip()]

            def _yhdista_nimet(syote, kaikki_nimet):
                """Sumea match: 'Saka' -> 'Bukayo Saka'."""
                tulos = []
                for s in syote:
                    s_low = s.lower()
                    matches = [n for n in kaikki_nimet if s_low in str(n).lower()]
                    if matches:
                        tulos.append(matches[0])
                return tulos

            # Manuaaliset alias-mappingit yleisimmille FBref-nimivarianteille
            JOUKKUE_ALIAS = {
                "Manchester United": ["Manchester Utd", "Man United", "Man Utd"],
                "Manchester City": ["Man City", "Manchester C."],
                "Newcastle United": ["Newcastle Utd", "Newcastle"],
                "Tottenham Hotspur": ["Tottenham", "Spurs"],
                "Wolverhampton Wanderers": ["Wolves", "Wolverhampton"],
                "Brighton & Hove Albion": ["Brighton", "Brighton and Hove"],
                "West Ham United": ["West Ham", "West Ham Utd"],
                "Nottingham Forest": ["Nott'ham Forest", "Nottm Forest"],
                "Leicester City": ["Leicester"],
                "Leeds United": ["Leeds", "Leeds Utd"],
                "Sheffield United": ["Sheffield Utd"],
                "Crystal Palace": ["Crystal P."],
                "Aston Villa": ["A. Villa"],
                "AFC Bournemouth": ["Bournemouth"],
            }

            def _etsi_joukkue_pelaajat(joukkue_nimi: str) -> tuple[pd.DataFrame, str]:
                """
                Etsi pelaajadatasta joukkueen pelaajat. Strategiat:
                  1. Eksakti
                  2. Manuaalinen alias-mappi (yleisimmat FBref-variantit)
                  3. SequenceMatcher (sumea, mutta KORKEAT samankaltaisuusvaatimukset)
                """
                if "team" not in pelaajat.columns:
                    return pelaajat, joukkue_nimi
                # 1. Eksakti
                eksakti = pelaajat[pelaajat["team"] == joukkue_nimi]
                if not eksakti.empty:
                    return eksakti, joukkue_nimi
                kaikki_joukkueet = list(pelaajat["team"].dropna().unique())
                # 2. Alias-mappi
                alias_lista = JOUKKUE_ALIAS.get(joukkue_nimi, [])
                for alias in alias_lista:
                    df_alias = pelaajat[pelaajat["team"] == alias]
                    if not df_alias.empty:
                        return df_alias, alias
                # 3. SequenceMatcher — vaadi >0.7 samankaltaisuutta
                from difflib import SequenceMatcher
                kandidaatit = []
                for jt in kaikki_joukkueet:
                    sim = SequenceMatcher(None, joukkue_nimi.lower(), str(jt).lower()).ratio()
                    if sim > 0.7:
                        kandidaatit.append((sim, jt))
                if kandidaatit:
                    kandidaatit.sort(reverse=True)
                    paras = kandidaatit[0][1]
                    return pelaajat[pelaajat["team"] == paras], paras
                return pd.DataFrame(), joukkue_nimi

            joukkue_pelaajat, koti_match = _etsi_joukkue_pelaajat(koti)
            kaikki_koti = joukkue_pelaajat["player"].tolist() if "player" in joukkue_pelaajat.columns else []
            yhdistetyt_koti = _yhdista_nimet(poissa_koti_lista, kaikki_koti)
            if poissa_koti_lista and not yhdistetyt_koti and koti_match != koti:
                st.caption(f"ℹ️ '{koti}' -> FBref-nimi '{koti_match}', mutta nimia ei tunnistettu.")
            elif poissa_koti_lista and koti_match != koti:
                st.caption(f"ℹ️ FBref-nimi: '{koti_match}'")

            joukkue_pelaajat_v, vieras_match = _etsi_joukkue_pelaajat(vieras)
            kaikki_vieras = joukkue_pelaajat_v["player"].tolist() if "player" in joukkue_pelaajat_v.columns else []
            yhdistetyt_vieras = _yhdista_nimet(poissa_vieras_lista, kaikki_vieras)
            if poissa_vieras_lista and not yhdistetyt_vieras and vieras_match != vieras:
                st.caption(f"ℹ️ '{vieras}' -> FBref-nimi '{vieras_match}', mutta nimia ei tunnistettu.")
            elif poissa_vieras_lista and vieras_match != vieras:
                st.caption(f"ℹ️ FBref-nimi: '{vieras_match}'")

            if yhdistetyt_koti:
                v_koti = laske_poissaolovaikutus(
                    pelaajat, koti_match, yhdistetyt_koti,
                    minuutit_col=col_min, xg_col=col_xg,
                )
                st.caption(
                    f"🏠 {koti}: tunnistettu {len(yhdistetyt_koti)} pelaajaa "
                    f"({', '.join(yhdistetyt_koti)}) -> "
                    f"-{v_koti['prosentti']:.1f}% xG"
                )
                # Auto-syota injury-slideriin (yliajaa kayttajan asetuksen)
                home_injury = max(-30, min(0, -int(round(v_koti["prosentti"] / 5)) * 5))

            if yhdistetyt_vieras:
                v_vieras = laske_poissaolovaikutus(
                    pelaajat, vieras_match, yhdistetyt_vieras,
                    minuutit_col=col_min, xg_col=col_xg,
                )
                st.caption(
                    f"✈️ {vieras}: tunnistettu {len(yhdistetyt_vieras)} pelaajaa "
                    f"({', '.join(yhdistetyt_vieras)}) -> "
                    f"-{v_vieras['prosentti']:.1f}% xG"
                )
                away_injury = max(-30, min(0, -int(round(v_vieras["prosentti"] / 5)) * 5))
        else:
            st.warning(
                f"Pelaajadatasta ei loytynyt xG-saraketta. Manuaalinen syotto kaytossa. "
                f"(Saatavilla {len(pelaajat.columns)} saraketta: "
                f"{', '.join(str(c) for c in list(pelaajat.columns))})"
            )

    st.info(
        "ℹ️ **Loukkaantumiset/kokoonpanot eivat paivity automaattisesti** — "
        "ei luotettavaa avointa rajapintaa. Kayta yla 'Avainpelaajia poissa' -liu'utinta "
        "kun tiedat poissaolot esim. SofaScoresta tai Transfermarktista."
    )

    saadot = apply_match_adjustments(
        home_injury_pct=home_injury, away_injury_pct=away_injury,
        home_motivation_pct=home_motivation, away_motivation_pct=away_motivation,
        home_rest_advantage_days=rest_advantage,
        is_derby=is_derby_ui,
        weather_total_goals_delta=weather_delta,
    )


# ---------------------------------------------------------------------------
# ENSEMBLE-ENNUSTE — DC + LightGBM yhdistettyna
# ---------------------------------------------------------------------------
st.divider()
st.subheader(f"📊 Ennuste: {koti} vs {vieras}")

p_dc = dc.predict_1x2(koti, vieras, adjustments=saadot)
lam, mu = dc.expected_goals(koti, vieras, adjustments=saadot)

# LightGBM ennuste, jos mahdollista
p_lgb = None
if lgb is not None and viimeisimmat is not None and koti in viimeisimmat.index and vieras in viimeisimmat.index:
    h = viimeisimmat.loc[koti].add_prefix("home_")
    a = viimeisimmat.loc[vieras].add_prefix("away_")
    rivi = pd.concat([h, a]).to_frame().T
    if all(c in rivi.columns for c in feature_cols):
        p_lgb_arr = lgb.predict(rivi[feature_cols])[0]
        p_ens = yhdista_1x2(p_dc, p_lgb_arr, paino_dixon=ensemble_paino)
        p_lgb = {"home": float(p_lgb_arr[0]), "draw": float(p_lgb_arr[1]), "away": float(p_lgb_arr[2])}
        kaytetty_p = p_ens
        ensemble_aktiivinen = True
    else:
        kaytetty_p = p_dc
        ensemble_aktiivinen = False
else:
    kaytetty_p = p_dc
    ensemble_aktiivinen = False

# Kalibraattori — ulkoinen korjaus mallin todennakoisyyksiin
kalibrointi_aktiivinen = False
if kayta_kalibrointia and cal is not None:
    # Tuki seka uudelle MainCalibrators-rakenteelle etta vanhalle MulticlassCalibratorille
    cal_1x2 = getattr(cal, "cal_1x2", None) or (cal if hasattr(cal, "transform") else None)
    if cal_1x2 is not None:
        p_array = _np_for_cal.array([[kaytetty_p["home"], kaytetty_p["draw"], kaytetty_p["away"]]])
        p_cal = cal_1x2.transform(p_array)[0]
        kaytetty_p = {"home": float(p_cal[0]), "draw": float(p_cal[1]), "away": float(p_cal[2])}
        kalibrointi_aktiivinen = True

# Odotetut maalit
m1, m2, m3 = st.columns(3)
m1.metric(f"{koti} odotetut maalit", f"{lam:.2f}")
m2.metric(f"{vieras} odotetut maalit", f"{mu:.2f}")
m3.metric("Yhteensa", f"{lam + mu:.2f}")

status_osat = []
if ensemble_aktiivinen:
    status_osat.append(
        f"✅ Ensemble: DC {ensemble_paino:.0%} + LightGBM {1-ensemble_paino:.0%}"
    )
else:
    status_osat.append("⚠️ Vain Dixon-Coles (ei xG-piirteita)")
if kalibrointi_aktiivinen:
    status_osat.append("🎯 Kalibroitu")
elif kayta_kalibrointia and cal is None:
    status_osat.append("⚠️ Kalibraattori ei opetettu (datasetti liian pieni)")
st.caption(" • ".join(status_osat))

# 1X2
st.markdown("### 1X2 — voittajaennuste")
c1, c2, c3 = st.columns(3)
c1.metric("1 (kotivoitto)", f"{kaytetty_p['home']*100:.1f} %")
c2.metric("X (tasapeli)", f"{kaytetty_p['draw']*100:.1f} %")
c3.metric("2 (vierasvoitto)", f"{kaytetty_p['away']*100:.1f} %")

st.caption(
    f"Reilu kerroin: 1 = **{1/kaytetty_p['home']:.2f}** | "
    f"X = **{1/kaytetty_p['draw']:.2f}** | 2 = **{1/kaytetty_p['away']:.2f}**"
)

if p_lgb is not None:
    with st.expander("Mallin osatekijat (DC vs LightGBM)"):
        df = pd.DataFrame({
            "Malli": ["Dixon-Coles", "LightGBM", "Ensemble"],
            "1": [p_dc["home"], p_lgb["home"], kaytetty_p["home"]],
            "X": [p_dc["draw"], p_lgb["draw"], kaytetty_p["draw"]],
            "2": [p_dc["away"], p_lgb["away"], kaytetty_p["away"]],
        })
        for c in ["1", "X", "2"]:
            df[c] = (df[c] * 100).round(2).astype(str) + " %"
        st.dataframe(df, hide_index=True, use_container_width=True)

# Over/Under + BTTS
ou = dc.predict_over_under(koti, vieras, line=2.5, adjustments=saadot)
# xG-totals -mallin ennuste jos saatavilla (vain xG-pohjaiset liigat)
ou_xg = ennusta_totals(totals_booster, totals_fc, totals_vm, koti, vieras)
if ou_xg is not None:
    # Yhdistetaan painottaen 50/50
    ou["over"] = 0.5 * ou["over"] + 0.5 * ou_xg
    ou["under"] = 1.0 - ou["over"]
# O/U-kalibraattori (jos paalla ja saatavilla)
if kayta_kalibrointia and cal is not None:
    cal_ou = getattr(cal, "cal_ou", None)
    if cal_ou is not None:
        p_over_cal = float(cal_ou.transform(_np_for_cal.array([ou["over"]]))[0])
        ou["over"] = p_over_cal
        ou["under"] = 1.0 - p_over_cal
btts = dc.predict_btts(koti, vieras, adjustments=saadot)
oc1, oc2 = st.columns(2)
with oc1:
    st.markdown("### Over/Under 2.5")
    o1, o2 = st.columns(2)
    o1.metric("Over", f"{ou['over']*100:.1f} %")
    o2.metric("Under", f"{ou['under']*100:.1f} %")
with oc2:
    st.markdown("### BTTS")
    b1, b2 = st.columns(2)
    b1.metric("Kylla", f"{btts['btts_yes']*100:.1f} %")
    b2.metric("Ei", f"{btts['btts_no']*100:.1f} %")

# Vetokerroin-vertailu
st.divider()
st.markdown("### 💰 Vetokerroin-vertailu")
ok1, ok2, ok3 = st.columns(3)
odds_h = ok1.number_input("1 kerroin", 1.01, value=2.10, step=0.05, format="%.2f")
odds_d = ok2.number_input("X kerroin", 1.01, value=3.40, step=0.05, format="%.2f")
odds_a = ok3.number_input("2 kerroin", 1.01, value=3.50, step=0.05, format="%.2f")
markkina = {"home": odds_h, "draw": odds_d, "away": odds_a}
st.caption(f"Markkinan marginaali: **{marginaali(markkina)*100:.2f} %**")

vertailu = vertaile_kertoimia(kaytetty_p, markkina)
df_v = pd.DataFrame(vertailu)
df_v_show = df_v.copy()
df_v_show["Markkinan p (norm.)"] = (df_v_show["Markkinan p (norm.)"] * 100).round(2).astype(str) + " %"
df_v_show["Mallin p"] = (df_v_show["Mallin p"] * 100).round(2).astype(str) + " %"
df_v_show["Mallin reilu kerroin"] = df_v_show["Mallin reilu kerroin"].round(2)
df_v_show["Edge"] = (df_v_show["Edge"] * 100).round(2).astype(str) + " %"
df_v_show["Value %"] = df_v_show["Value %"].round(2).astype(str) + " %"
df_v_show["Kelly (1/4)"] = df_v_show["Kelly (1/4)"].round(3)
st.dataframe(df_v_show.drop(columns=["Kelly (1x)"]), hide_index=True, use_container_width=True)

suos = [r for r in vertailu if r["Value %"] > 5 and r["Kelly (1/4)"] > 0]
if suos:
    st.success("**Mallin value-vetoehdotus:** " + ", ".join(
        f"{r['Valinta']} @ {r['Markkinakerroin']:.2f} (value {r['Value %']:.1f} %)"
        for r in suos
    ))
else:
    st.info("Mallin mukaan markkina on tehokas — ei yli 5 % value-vetoa.")

# Tarkat tulokset
st.markdown("### 🎯 Todennakoisimmat tarkat tulokset")
top = dc.todennakoisin_tulos(koti, vieras, top_n=10, adjustments=saadot)
df_t = pd.DataFrame(top, columns=["Tulos", "p"])
df_t["%"] = (df_t["p"] * 100).round(2)
st.bar_chart(df_t.set_index("Tulos")["%"], height=300)

st.caption(
    "Vastuuvapaus: oppimismalli, ei sijoitusneuvo. "
    "Loukkaantumiset/kokoonpanot pitaa syottaa kasin (ei avointa rajapintaa). "
    "Sa, lepopaivat, sarjasija, derby — auto."
)

st.divider()
with st.expander("🔍 Mallin parametrit ja joukkueiden vahvuus"):
    cc1, cc2 = st.columns(2)
    with cc1:
        st.markdown("**Globaalit parametrit**")
        st.write({
            "Globaali kotietu (gamma)": round(dc.home_advantage, 4),
            "Rho-korjaus": round(dc.rho, 4),
            "Joukkueita": len(joukkueet),
            "Decay": float(decay_val),
            "Otteluita treenissa": len(hist_data),
        })
        if dc.home_advantage_per_team:
            keskiarvo_kotietu = float(dc.home_advantage)
            tot_kotietu = pd.DataFrame([
                {"Joukkue": j, "Kotietu (yhteens)": round(
                    keskiarvo_kotietu + dc.home_advantage_per_team.get(j, 0.0), 3)}
                for j in joukkueet
            ]).sort_values("Kotietu (yhteens)", ascending=False)
            st.markdown("**Top-5 vahvinta kotietua** (joukkuekohtainen + globaali)")
            st.dataframe(tot_kotietu.head(5), hide_index=True, use_container_width=True)
    with cc2:
        st.markdown("**Hyokkays / puolustus / kotietu**")
        joukkue_df = pd.DataFrame([
            {
                "Joukkue": j,
                "Hyokkays": round(dc.attack[j], 3),
                "Puolustus": round(dc.defence[j], 3),
                "Kotietu+": round(dc.home_advantage_per_team.get(j, 0.0), 3),
            }
            for j in joukkueet
        ]).sort_values("Hyokkays", ascending=False)
        st.dataframe(joukkue_df, hide_index=True, use_container_width=True, height=400)

    # Promotio-priorit (jos kaytossa) — info paneeli
    promotio_priorit = getattr(dc, "team_priors_kaytetty", {}) or {}
    if promotio_priorit:
        with st.expander(f"🆙 Promotio-priorit kaytossa ({len(promotio_priorit)} joukkuetta)", expanded=False):
            st.caption(
                "Naille joukkueille DC-mallin estimaatti vedetaan kohti alasarjasta "
                "skaalattua prioria, ei kohti liigan keskiarvoa (= 0)."
            )
            df_pr = pd.DataFrame([
                {
                    "Joukkue": j,
                    "Prior hyokkays": round(p["attack"], 3),
                    "Prior puolustus": round(p["defence"], 3),
                    "Toteutunut hyokkays": round(dc.attack.get(j, 0.0), 3),
                    "Toteutunut puolustus": round(dc.defence.get(j, 0.0), 3),
                    "Prior weight": round(p["weight"], 2),
                }
                for j, p in promotio_priorit.items()
            ])
            st.dataframe(df_pr, hide_index=True, use_container_width=True)


# ---------------------------------------------------------------------------
# 🎯 ENSEMBLE-PAINON OPTIMOINTI walk-forwardilla
# ---------------------------------------------------------------------------
st.divider()
with st.expander("🎯 Optimoi ensemble-paino walk-forwardilla", expanded=False):
    st.caption(
        "Etsii optimaalisen Dixon-Coles vs LightGBM -painon ajamalla walk-forward-CV:n. "
        "Sovittaa molemmat mallit useaan otokseen ja kokeilee paino-arvoja 0.0 - 1.0. "
        "Vie 30-90 sekuntia datasta riippuen."
    )
    n_folds_input = st.slider("Foldien maara", 3, 10, 6, 1, key="opt_n_folds")
    min_train_input = st.number_input(
        "Min train size", 100, 2000, 300, 50, key="opt_min_train",
        help="Vahimmaismaara otteluita ennen ensimmaista foldia.",
    )
    if st.button("🚀 Aja walk-forward optimointi", use_container_width=False):
        from src.models.ensemble import optimoi_paino_walk_forward
        prog = st.progress(0.0, text="Aloitetaan...")
        def _cb(i, n):
            prog.progress(i / n, text=f"Foldi {i}/{n}")
        try:
            paras_w, log_lossit, n_oos = optimoi_paino_walk_forward(
                hist_data,
                decay=float(decay_val),
                bayes_shrinkage=float(bayes_shrink),
                n_folds=int(n_folds_input),
                min_train_size=int(min_train_input),
                progress_callback=_cb,
            )
            prog.empty()
            st.session_state["optim_paino"] = paras_w
            st.session_state["optim_n"] = n_oos
            st.session_state["optim_log_lossit"] = log_lossit

            st.success(
                f"✅ Paras paino: **{paras_w:.2f}** (DC {paras_w*100:.0f}% / "
                f"LGB {(1-paras_w)*100:.0f}%) • {n_oos} OOS-ennustetta"
            )
            df_ll = pd.DataFrame([
                {"Paino DC": w, "Paino LGB": round(1-w, 2), "Log-loss": ll}
                for w, ll in sorted(log_lossit.items())
            ])
            df_ll["Erotus parhaaseen"] = df_ll["Log-loss"] - df_ll["Log-loss"].min()
            st.dataframe(
                df_ll.style.highlight_min(subset=["Log-loss"], color="#d4f4dd"),
                hide_index=True, use_container_width=True, height=300,
            )
            st.caption(
                "💡 Suositus tallennettu sessio-statiin. Sivupalkin Ensemble-paino "
                "-slider kayttaa sita oletuksena seuraavalla pageloadilla."
            )
        except Exception as e:
            prog.empty()
            st.error(f"Optimointi epaonnistui: {e}")


# ---------------------------------------------------------------------------
# 🎰 EHDOTETTU VETO — kaikkien markkinoiden value-laskenta
# ---------------------------------------------------------------------------
st.divider()
with st.expander("🎰 Ehdotettu veto — kaikki markkinat", expanded=True):
    st.caption(
        "Syota markkinakertoimet alle. Sovellus laskee value-prosentin ja Kelly-suosituksen "
        "kaikille markkinoille. Vihrealla korostettu = paras value (>5%, Kelly>0)."
    )

    st.markdown("**1X2**")
    e1, e2, e3 = st.columns(3)
    eh = e1.number_input("1 (kotivoitto)", 1.01, value=2.10, step=0.05, format="%.2f", key="eh_1")
    ed = e2.number_input("X (tasapeli)", 1.01, value=3.40, step=0.05, format="%.2f", key="eh_x")
    ea = e3.number_input("2 (vierasvoitto)", 1.01, value=3.50, step=0.05, format="%.2f", key="eh_2")

    st.markdown("**Over / Under 2.5 maalia**")
    eo, eu = st.columns(2)
    eyli = eo.number_input("Yli 2.5", 1.01, value=1.90, step=0.05, format="%.2f", key="eh_yli")
    ealle = eu.number_input("Alle 2.5", 1.01, value=1.90, step=0.05, format="%.2f", key="eh_alle")

    st.markdown("**BTTS — Both Teams To Score**")
    eb1, eb2 = st.columns(2)
    ebtts_y = eb1.number_input("Kylla", 1.01, value=1.85, step=0.05, format="%.2f", key="eh_btts_y")
    ebtts_n = eb2.number_input("Ei", 1.01, value=1.90, step=0.05, format="%.2f", key="eh_btts_n")

    st.markdown("---")
    st.markdown("**📊 Value-laskelma**")

    def _value(p_malli, kerroin):
        return (p_malli * kerroin - 1.0) * 100.0

    def _kelly_25(p_malli, kerroin):
        if kerroin <= 1.0 or p_malli <= 0:
            return 0.0
        b = kerroin - 1.0
        q = 1.0 - p_malli
        f = (b * p_malli - q) / b
        return max(0.0, f * 0.25)

    rivit_value = []
    for nimi, p, k in [
        (f"1 - {koti}", kaytetty_p["home"], eh),
        ("X - tasapeli", kaytetty_p["draw"], ed),
        (f"2 - {vieras}", kaytetty_p["away"], ea),
        ("Yli 2.5 maalia", ou["over"], eyli),
        ("Alle 2.5 maalia", ou["under"], ealle),
        ("BTTS Kylla", btts["btts_yes"], ebtts_y),
        ("BTTS Ei", btts["btts_no"], ebtts_n),
    ]:
        v = _value(p, k)
        kel = _kelly_25(p, k)
        rivit_value.append({
            "Markkina": nimi,
            "Mallin %": round(p * 100, 1),
            "Kerroin": round(k, 2),
            "Reilu kerroin": round(1.0 / p, 2) if p > 0 else 0,
            "Value %": round(v, 2),
            "Kelly 1/4 %": round(kel * 100, 2),
        })

    df_value = pd.DataFrame(rivit_value)

    def _korosta(rivi):
        if rivi["Value %"] > 5:
            return ["background-color: #d4f4dd; font-weight: bold"] * len(rivi)
        return [""] * len(rivi)

    styled = df_value.style.apply(_korosta, axis=1)
    st.dataframe(styled, hide_index=True, use_container_width=True)

    parhaat = df_value[(df_value["Value %"] > 5) & (df_value["Kelly 1/4 %"] > 0)].sort_values(
        "Value %", ascending=False
    )
    if not parhaat.empty:
        viestit = "\n\n".join([
            f"- **{r['Markkina']}** @ {r['Kerroin']:.2f} — value {r['Value %']:.1f}%, "
            f"Kelly 1/4 = {r['Kelly 1/4 %']:.2f}% bankrollistä"
            for _, r in parhaat.iterrows()
        ])
        st.success("**🎯 Suositellut value-vedot:**\n\n" + viestit)
    else:
        st.info(
            "Mallin mukaan kaikki markkinat ovat tehokkaasti hinnoiteltuja "
            "(value < 5%). Ei suositusta tahan otteluun."
        )

    st.caption(
        "💡 Value % = (mallin_p × kerroin − 1) × 100. "
        "Kelly 1/4 = optimaalinen panostuskoko bankrollistä, kun otat 1/4 Kelly-fraktiosta. "
        "Korostettu rivi = value > 5%."
    )

st.caption(
    "Vastuuvapaus: tama on oppimismalli, ei sijoitusneuvo. "
    "Markkinat hinnoittelevat usein piirteita joita avoin data ei kata."
)
