"""
GoalIQ Backend API — FastAPI-pohjainen REST-rajapinta.

Korvaa Streamlitin käyttöliittymän JSON-API:lla jota mobiili-app
(React Native) ja muut clientit voivat kutsua.

Käynnistys lokaalisti:
    uvicorn api.main:app --reload --port 8000

Sitten avaa selain:
    http://localhost:8000          → tervehdys
    http://localhost:8000/docs     → automaattinen Swagger-dokumentaatio
    http://localhost:8000/api/leagues → JSON-lista saatavilla olevista liigoista
"""

from __future__ import annotations

import copy
import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Literal, Optional

# Lisää projektin juuri Python-polkuun jotta `src.*` -importit toimivat
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
import stripe
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator

import config
from src.data.loader import lataa_otteludata
from src.models.dixon_coles import DixonColesModel, apply_match_adjustments

import requests

# Stripe-konfiguraatio (Render env varseista)
stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_PRICE_ID = os.getenv("STRIPE_PRICE_ID", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")

# RevenueCat (Google Play Billing) -webhookin jaettu salaisuus. Arvo on sama
# merkkijono joka asetetaan RevenueCat-dashboardin webhook-asetuksiin
# (Authorization header value) — RevenueCat lahettaa sen sellaisenaan
# Authorization-headerissa. Tyhja => webhook ei kasittele (ei luvattomia
# is_premium-kirjoituksia).
REVENUECAT_WEBHOOK_AUTH = os.getenv("REVENUECAT_WEBHOOK_AUTH", "")

# Supabase-konfiguraatio webhook-päivityksiä varten.
# SUPABASE_SERVICE_ROLE_KEY on backend-only-key (ei saa koskaan vuotaa frontille);
# se ohittaa Row Level Securityn, jotta webhook voi päivittää profiilin.
SUPABASE_URL = os.getenv("SUPABASE_URL", "")  # esim. https://xxxx.supabase.co
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")


def _update_profile(user_id: str, fields: dict) -> bool:
    """
    Geneerinen Supabase profiles -paivitys. fields = sarakkeet jotka asetetaan.
    Palauttaa True jos onnistui, False jos epaonnistui (logaa virheen).
    """
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        print(f"[Supabase] WARNING: missing env vars, cannot update user_id={user_id}")
        return False

    url = f"{SUPABASE_URL}/rest/v1/profiles?id=eq.{user_id}"
    headers = {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }
    try:
        resp = requests.patch(url, json=fields, headers=headers, timeout=10)
        if resp.status_code in (200, 204):
            print(f"[Supabase] Updated user_id={user_id} fields={fields}")
            return True
        print(
            f"[Supabase] FAILED status={resp.status_code} body={resp.text[:200]} "
            f"user_id={user_id}"
        )
        return False
    except Exception as e:
        print(f"[Supabase] EXCEPTION user_id={user_id}: {e}")
        return False


def _update_profile_premium(user_id: str, is_premium: bool) -> bool:
    """Yksinkertaistettu wrapper vain is_premium -kentalle."""
    return _update_profile(user_id, {"is_premium": is_premium})


# ---------------------------------------------------------------------------
# FastAPI -instanssi
# ---------------------------------------------------------------------------
app = FastAPI(
    title="GoalIQ API",
    description="AI-powered football match predictions (Dixon-Coles + LightGBM ensemble)",
    version="0.1.0",
)

# CORS — sallitaan mobiili-appin & muiden clienttien kutsut
# Tuotannossa rajoita vain omaan domainiin
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Kehityksessä kaikki, tuotannossa esim. ["https://goaliq.app"]
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Mallin välimuisti — sovitetaan kerran liiga+kausi-yhdistelmälle
# ---------------------------------------------------------------------------
_MODEL_CACHE: dict[tuple, DixonColesModel] = {}
# #69: turnauskoodia (WC/EC) sisältävät avaimet tarvitsevat refit:n kun
# uusi turnausdata on saatavilla. Tallennetaan fit-aikaleima ja refit:taan
# jos loaderin turnausdataa on haettu sen jälkeen uudelleen.
_MODEL_FITTED_AT: dict[tuple, float] = {}
# #72: stale-while-revalidate. Kun #69:n TTL umpeutuu, palautetaan vanha
# malli ja triggataan tausta-refit. _REFIT_IN_PROGRESS estaa tuplarefit
# samalle avaimelle. _MODEL_LOCK suojaa _MODEL_CACHE / _MODEL_FITTED_AT /
# _REFIT_IN_PROGRESS check-then-set -sekvenssit (warmup-thread,
# tausta-refit-thread ja pyyntö-säikeet ajaa rinnakkain).
_REFIT_IN_PROGRESS: set[tuple] = set()
_MODEL_LOCK = threading.Lock()

# #71: DataFrame-välimuisti — /api/predict kutsuu lataa_otteludata kahdesti
# per request (mallia varten + H2H/form-trend-laskuun). Understat-loaderin
# read_schedule() voi tehdä HTTP-kutsuja → PL:n /api/predict warm-aika oli
# 44 s vaikka malli oli cachetettu. Cache ohitetaan turnauskaudille jotta
# #69:n TTL-logiikka pysyy ehjänä (loader hoitaa turnausten freshnessin).
# Lukko: warmup-thread + pyyntö-säikeet voivat ajaa rinnakkain → double-
# checked locking estää tuplakirjoituksen pitämättä lukkoa hidastavan
# lataa_otteludata-kutsun ajan.
_DATA_CACHE: dict[tuple, pd.DataFrame] = {}
_DATA_CACHE_LOCK = threading.Lock()


def _lataa_otteludata_cached(liigat, kaudet) -> pd.DataFrame:
    """Muistissa-oleva DataFrame-cache lataa_otteludata-kutsuille.

    Domestic-liigoille pysyvä prosessin keston ajan (data ei muutu). Turnaus-
    liigoille (WC/EC live-kaudella) ohittaa cachen ja kutsuu loaderia joka
    soveltaa #69:n TTL-logiikkaa.
    """
    if _liigat_sisaltavat_turnauksen(tuple(liigat)):
        return lataa_otteludata(list(liigat), list(kaudet))
    key = (tuple(liigat), tuple(kaudet))
    with _DATA_CACHE_LOCK:
        df = _DATA_CACHE.get(key)
    if df is not None:
        return df
    # Cache miss → lataa lukon ulkopuolella (voi viedä sekunteja).
    new_df = lataa_otteludata(list(liigat), list(kaudet))
    with _DATA_CACHE_LOCK:
        existing = _DATA_CACHE.get(key)
        if existing is not None:
            # Toinen säie ehti välissä — palautetaan sama instance kaikille.
            return existing
        _DATA_CACHE[key] = new_df
        return new_df


# ---------------------------------------------------------------------------
# Lämmitys käynnistyksessä — sovittaa kaikkien tarjottujen liigojen mallit
# taustalla jotta ensimmäinen /api/teams + /api/predict on nopea.
#
# Aiemmin warmup koski vain PL:ää → muut 5 liigaa (PD, BL1, SA, FL1, CL)
# fitattiin lazy ensimmäisellä /api/teams-kutsulla → mobiili näki "server took
# too long" -timeoutin (#71). Sarjallinen jotta CPU ei ylikuormiu ja
# football-data.org rate-limit (6.5 s väli) säilyy alle 10/min rajan.
# #72: WC lisattiin viimeiseksi jotta launch-paivan domestic-liigaliikenne
# saa CPU:n ensin. WC-fit on 30 s -luokkaa, joten sen jattaminen lazyksi
# blokkasi mobiili-WC-tabin ensimmaisen klikkauksen.
# ---------------------------------------------------------------------------
# Kausi-ikkuna resolvoidaan dynaamisesti (config.current_season_pair):
# elo-touko-sääntö → 1.8. alkaen warmup + endpoint-defaultit siirtyvät uuteen
# kauteen ilman koodimuutosta. Prosessin käynnistyshetki määrää warmup-avaimet
# (Render restarttaa deployssa); per-pyyntö-defaultit resolvoidaan pyynnössä.
_DOMESTIC_SEASONS: tuple[str, ...] = tuple(config.current_season_pair())

WARMUP_LEAGUES: list[tuple[tuple[str, ...], tuple[str, ...]]] = [
    (("ENG-Premier League",),    _DOMESTIC_SEASONS),
    (("ESP-La Liga-FD",),        _DOMESTIC_SEASONS),
    (("GER-Bundesliga-FD",),     _DOMESTIC_SEASONS),
    (("ITA-Serie A-FD",),        _DOMESTIC_SEASONS),
    (("FRA-Ligue 1-FD",),        _DOMESTIC_SEASONS),
    (("INT-Champions League",),  _DOMESTIC_SEASONS),
]

# #79: WC-mallin fit-parametrit (kanoninen lähde = international_results).
# PredictWCRequest käyttää näitä defaultteina (vain dokumentaatio/compat — serving
# lataa esirakennetun JSON-mallin, ei fittaa näillä ajossa).
from src.data.international_results import WC_FIT_DECAY, WC_FIT_BAYES


@app.on_event("startup")
def _warmup_default_models():
    def _fit_all():
        for liigat, kaudet in WARMUP_LEAGUES:
            try:
                t0 = time.time()
                _saa_malli(liigat, kaudet)
                print(f"[Warmup] {liigat[0]} ready in {time.time()-t0:.1f}s")
            except Exception as e:
                print(f"[Warmup] {liigat[0]} failed: {type(e).__name__}: {e}")
        # #79: WC-malli on ESIRAKENNETTU (data/wc_model.json) — Render Starter ei
        # jaksa fitata "any"-mallia ajossa. Esiladataan lru-cacheen (instant);
        # ei fittiä, ei livelock-riskiä.
        try:
            from src.data.international_results import load_wc_model
            t0 = time.time()
            dc = load_wc_model()
            print(f"[Warmup] WC model (prebuilt) loaded: {len(dc.teams_)} teams "
                  f"in {time.time()-t0:.2f}s")
        except Exception as e:
            print(f"[Warmup] WC prebuilt model load failed: {type(e).__name__}: {e}")

    threading.Thread(target=_fit_all, daemon=True).start()


def _liigat_sisaltavat_turnauksen(liigat: tuple[str, ...]) -> bool:
    """#69: True jos jokin liiga mappautuu live-turnauskoodiin (WC/EC)."""
    from src.data.football_data_org import COMPETITION_CODES, _LIVE_TOURNAMENT_CODES
    for liiga in liigat:
        if COMPETITION_CODES.get(liiga) in _LIVE_TOURNAMENT_CODES:
            return True
    return False


def _malli_vanhentunut(key: tuple, liigat: tuple[str, ...]) -> bool:
    """
    #69: invalidoi cached DC-malli jos avaimessa on turnauskoodi (WC/EC)
    ja malli on TTL:n verran vanha. Refit kutsuu loaderia → loader-TTL
    laukeaa rinnakkain → API-haku tuoreelle datalle.

    Domestic-only avaimille palauttaa aina False → /api/predict ei saa
    lisälatenssia kuin yhden cheap dict-lookupin verran.
    """
    if not _liigat_sisaltavat_turnauksen(liigat):
        return False
    from src.data.football_data_org import TOURNAMENT_TTL_SEC
    fitted_at = _MODEL_FITTED_AT.get(key, 0.0)
    return (time.time() - fitted_at) >= TOURNAMENT_TTL_SEC


def _fit_malli(liigat: tuple[str, ...], kaudet: tuple[str, ...],
               decay: float, bayes_shrinkage: float,
               per_team_home_adv: bool,
               shrink_defence_to_mean: bool) -> DixonColesModel:
    """Sovita DixonColesModel annetuilla parametreilla. Heittaa HTTPException."""
    df = _lataa_otteludata_cached(list(liigat), list(kaudet))
    if df.empty:
        raise HTTPException(
            status_code=404,
            detail=f"No match data found for leagues={liigat}, seasons={kaudet}",
        )
    # #79: kansainvälinen WC-data tuo "tournament"-sarakkeen → kilpailu-paino.
    # Domestic-datassa saraketta ei ole → fit_kwargs tyhjä → bittitarkasti ennallaan.
    fit_kwargs: dict = {}
    if "tournament" in df.columns:
        from src.data.international_results import (
            COMPETITION_WEIGHTS,
            DEFAULT_COMPETITION_WEIGHT,
        )
        fit_kwargs = dict(
            competition_col="tournament",
            competition_weights=COMPETITION_WEIGHTS,
            default_competition_weight=DEFAULT_COMPETITION_WEIGHT,
        )
    try:
        return DixonColesModel(per_team_home_adv=per_team_home_adv).fit(
            df,
            home_team_col="home_team", away_team_col="away_team",
            home_goals_col="home_score", away_goals_col="away_score",
            decay=decay, date_col="date",
            l2_attack_defence=bayes_shrinkage,
            shrink_defence_to_mean=shrink_defence_to_mean,
            **fit_kwargs,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Model fit failed: {e}")


def _taustarefit(key: tuple, liigat: tuple[str, ...], kaudet: tuple[str, ...],
                  decay: float, bayes_shrinkage: float,
                  per_team_home_adv: bool,
                  shrink_defence_to_mean: bool) -> None:
    """#72: refit:taa mallin taustasaikeessa, vapauttaa _REFIT_IN_PROGRESS-lipun.

    Pyynnot tarjoillaan vanhalla cachetetulla mallilla kunnes uusi valmis.
    Virheet logataan mutta ei propagoida — pyyntotie pysyy ehjana ja
    seuraava TTL-tarkistus yrittaa uudelleen.
    """
    try:
        dc = _fit_malli(liigat, kaudet, decay, bayes_shrinkage,
                        per_team_home_adv, shrink_defence_to_mean)
        with _MODEL_LOCK:
            _MODEL_CACHE[key] = dc
            _MODEL_FITTED_AT[key] = time.time()
        print(f"[Refit] {liigat[0]} ready")
    except Exception as e:
        print(f"[Refit] {liigat[0]} failed: {type(e).__name__}: {e}")
    finally:
        with _MODEL_LOCK:
            _REFIT_IN_PROGRESS.discard(key)


def _saa_malli(liigat: tuple[str, ...], kaudet: tuple[str, ...],
               decay: float = 0.0035, bayes_shrinkage: float = 2.0,
               per_team_home_adv: bool = True,
               shrink_defence_to_mean: bool = False) -> DixonColesModel:
    """
    Hae cached DC-malli tai sovita uusi jos ei välimuistissa.

    #72: turnausmalleille (WC/EC) #69:n TTL-tarkistus on stale-while-
    revalidate — vanhentunut malli palautetaan heti, ja tausta-saie
    refit:taa uudella datalla. Yksikaan pyynto ei blokkaudu 30 s fitin
    taakse. Cold-cold (ei cachea ollenkaan) sovittaa synkronisesti —
    warmup-saie estaa taman kaytannossa.

    per_team_home_adv
        False = älä sovita joukkuekohtaisia kotietu-parametreja (n kpl).
        WC-malli (`/api/predict-wc`) nollaa kotiedun joka tapauksessa, joten
        näiden sovittaminen on n hukkaparametria pienelle WC-datalle (#61).
    shrink_defence_to_mean
        True = shrinkkaa puolustuksen joukkue-eroja, ei maalitasoa (#61).
        Estää bayes_shrinkagea deflatoimasta ennustettuja maaleja.
    """
    key = (liigat, kaudet, round(decay, 4), round(bayes_shrinkage, 2),
           per_team_home_adv, shrink_defence_to_mean)

    # Lukon alla: peek cache + arvioi tuoreus. _malli_vanhentunut lukee
    # _MODEL_FITTED_AT:ia, joten se kuuluu kriittiseen alueeseen.
    with _MODEL_LOCK:
        cached = _MODEL_CACHE.get(key)
        stale = cached is not None and _malli_vanhentunut(key, liigat)

    if cached is not None and not stale:
        return cached

    if cached is not None and stale:
        # Stale-while-revalidate: kaynnista tausta-refit vain jos ei jo kaynnissa.
        with _MODEL_LOCK:
            start_thread = key not in _REFIT_IN_PROGRESS
            if start_thread:
                _REFIT_IN_PROGRESS.add(key)
        if start_thread:
            threading.Thread(
                target=_taustarefit,
                args=(key, liigat, kaudet, decay, bayes_shrinkage,
                      per_team_home_adv, shrink_defence_to_mean),
                daemon=True,
            ).start()
        return cached

    # Cold-cold: ei cachea ollenkaan -> synk fit. Warmup hoitaa taman
    # kaytannossa Renderissa; lazy-tie on jaljella vain epatavallisille
    # liiga+kausi-yhdistelmille (esim. /api/team -kutsuille muille kuin
    # warmup-listalle).
    dc = _fit_malli(liigat, kaudet, decay, bayes_shrinkage,
                    per_team_home_adv, shrink_defence_to_mean)
    with _MODEL_LOCK:
        _MODEL_CACHE[key] = dc
        _MODEL_FITTED_AT[key] = time.time()
    return dc


# ---------------------------------------------------------------------------
# Pydantic-mallit (request/response -tyypit)
# ---------------------------------------------------------------------------
class PredictionRequest(BaseModel):
    """Ennustepyyntö."""
    home_team: str = Field(..., description="Home team name", examples=["Arsenal"])
    away_team: str = Field(..., description="Away team name", examples=["Liverpool"])
    leagues: list[str] = Field(
        default=["ENG-Premier League"],
        description="Leagues to use for training the model",
    )
    seasons: list[str] = Field(
        default_factory=config.current_season_pair,
        description="Seasons (YYMM format). Default: edellinen + aktiivinen kausi.",
    )
    decay: float = Field(default=0.0035, ge=0.0, le=0.020,
                          description="Time-decay weight (0=no decay)")
    bayes_shrinkage: float = Field(default=2.0, ge=0.0, le=10.0,
                                    description="Bayes shrinkage strength")
    # Manuaaliset säädöt (kaikki valinnaisia)
    home_injury_pct: float = Field(default=0.0, ge=-30.0, le=0.0)
    away_injury_pct: float = Field(default=0.0, ge=-30.0, le=0.0)
    home_motivation_pct: float = Field(default=0.0, ge=-15.0, le=15.0)
    away_motivation_pct: float = Field(default=0.0, ge=-15.0, le=15.0)
    is_derby: bool = Field(default=False)
    # T6: todennakoisimpien tulosten maara (5 free, 10 premium)
    top_n: int = Field(default=5, ge=1, le=10,
                       description="Number of most-likely scorelines to return")


class PredictWCRequest(BaseModel):
    """
    WC-ennustepyyntö — kansainväliset joukkueet, ei seurajoukkueet.

    Defaults:
      - leagues: ["INT-World Cup"]
      - seasons: ["2018", "2022", "2026"] — 4-digit year format, normalisoidaan
        sisäisesti 2-digit-formaattiin loader-yhteensopivuuden vuoksi
        (football_data_org._kausi_to_year tulkitsee "2018" → "2020", joten
        meidän on muunnettava ne "18", "22", "26" ennen lähetystä).

    Datalähde: football-data.org / ML Pack Light -tier
      (avaa "10 seasons of history" → WC 2018, 2022 FINISHED-ottelut).
    """
    home_team: str = Field(..., description="Home team (e.g., 'Argentina')",
                            examples=["Argentina"])
    away_team: str = Field(..., description="Away team (e.g., 'France')",
                            examples=["France"])
    leagues: list[str] = Field(
        default=["INT-World Cup"],
        description="Käytä oletusta — WC-endpoint tukee vain tätä koodia",
    )
    seasons: list[str] = Field(
        default=["2018", "2022", "2026"],
        description="WC-kaudet (4-digit years).",
    )
    # WC-otteluissa ei perinteistä kotietua. decay=0 (#61): WC-dataa on vain
    # ~128 ottelua kahdelta turnaukselta — aikapainotus pudottaisi efektiivisen
    # otoskoon ~75:een (WC 2018 paino ~0.2), mikä pahentaa yliparametrisointia.
    # decay=0 → ESS 128, eikä WC 2018:n dataa heitetä hukkaan.
    decay: float = Field(default=WC_FIT_DECAY, ge=0.0, le=0.020)
    # #79: WC-malli treenataan nyt tuoreesta maaotteludatasta (martj42, ~2000
    # ottelua) eikä vain WC 2018/22 (~128) → decay/shrinkage virittää vaiheen 5
    # backtest. Arvot tulevat WC_FIT_DECAY/WC_FIT_BAYES-vakioista (sama kuin
    # warmup → cache-avain täsmää).
    bayes_shrinkage: float = Field(default=WC_FIT_BAYES, ge=0.0, le=10.0)
    # Manuaaliset säädöt — samat kuin /api/predict
    home_injury_pct: float = Field(default=0.0, ge=-30.0, le=0.0)
    away_injury_pct: float = Field(default=0.0, ge=-30.0, le=0.0)
    home_motivation_pct: float = Field(default=0.0, ge=-15.0, le=15.0)
    away_motivation_pct: float = Field(default=0.0, ge=-15.0, le=15.0)
    is_derby: bool = Field(default=False)


class PredictionResponse(BaseModel):
    """Ennustevastaus 1X2, O/U 2.5, BTTS."""
    home_team: str
    away_team: str
    expected_goals_home: float
    expected_goals_away: float
    p_home_win: float
    p_draw: float
    p_away_win: float
    fair_odds_home: float
    fair_odds_draw: float
    fair_odds_away: float
    p_over_2_5: float
    p_under_2_5: float
    p_btts_yes: float
    p_btts_no: float
    top_scores: list[dict]  # [{score: "2-1", probability: 0.087}, ...]
    # T5: viimeiset 5 keskinaista kohtaamista (vain /api/predict — /api/predict-wc
    # tayttaa kentan tyhjana koska WC-otteluissa parit harvoin toistuvat)
    h2h: list[dict] = Field(default_factory=list)
    # T7: premium-visualisoinnit (vain /api/predict). h2h_summary = W/D/L-jakauma
    # kaikista ladatun kausi-ikkunan keskinaisista kohtaamisista. form_trend =
    # kummankin joukkueen viimeisimmat ottelut momentum-kayraa varten.
    h2h_summary: dict = Field(default_factory=dict)
    form_trend: dict = Field(default_factory=dict)


class TeamsResponse(BaseModel):
    leagues: list[str]
    seasons: list[str]
    teams: list[str]
    n_matches: int


# ---------------------------------------------------------------------------
# ENDPOINT: tervehdys
# ---------------------------------------------------------------------------
@app.get("/")
def root():
    """Health check."""
    return {
        "service": "GoalIQ API",
        "version": "0.1.0",
        "status": "ok",
        "docs": "/docs",
        "endpoints": ["/api/leagues", "/api/teams", "/api/predict"],
    }


# ---------------------------------------------------------------------------
# ENDPOINT: saatavat liigat
# ---------------------------------------------------------------------------
@app.get("/api/leagues")
def list_leagues():
    """Lista kaikista liigoista joita malli tukee."""
    return {
        "top5_xg_leagues": [
            "ENG-Premier League", "ESP-La Liga", "GER-Bundesliga",
            "ITA-Serie A", "FRA-Ligue 1",
        ],
        "other_leagues": [
            "ENG-Championship", "ENG-League One", "ENG-League Two",
            "ESP-La Liga 2", "GER-2. Bundesliga", "ITA-Serie B", "FRA-Ligue 2",
            "POR-Primeira Liga", "NED-Eredivisie", "BEL-Pro League",
            "SCO-Premiership", "TUR-Super Lig",
            "FIN-Veikkausliiga", "SWE-Allsvenskan", "NOR-Eliteserien", "DEN-Superliga",
        ],
        "uefa_tournaments": [
            "INT-Champions League", "INT-Europa League", "INT-Conference League",
        ],
        "available_seasons": config.seasons_since("2122"),
        # Selitykset mobiilia varten — joukkueiden valinta liigan mukaan
        "league_presets": {
            "ENG-Premier League": {
                "label": "Premier League",
                "icon": "⚽",
                "seasons": config.current_season_pair(),
            },
        },
        "coming_soon": [
            {
                "code": "INT-World Cup",
                "label": "World Cup 2026",
                "icon": "🏆",
                "available_from": "2026-06-11",
                "note": "World Cup predictions launching when the tournament starts on June 11, 2026.",
            },
        ],
    }


# ---------------------------------------------------------------------------
# ENDPOINT: joukkueet liigassa
# ---------------------------------------------------------------------------
@app.get("/api/teams", response_model=TeamsResponse)
def list_teams(
    leagues: list[str] = Query(default=["ENG-Premier League"]),
    seasons: list[str] | None = Query(default=None,
        description="Default: edellinen + aktiivinen kausi (dynaaminen)"),
):
    """Lista joukkueista jotka mallissa esiintyvät annetussa liiga+kausi-yhdistelmässä."""
    if seasons is None:
        seasons = config.current_season_pair()
    # #79: WC-lista on 48 WC2026-maata — palautetaan suoraan ILMAN mallin fittausta
    # (Render Starter ei jaksa fitata "any"-mallia ajossa; malli on esirakennettu).
    if leagues == ["INT-World Cup"]:
        from src.data.wc_teams import WC2026_TEAMS
        return TeamsResponse(
            leagues=leagues, seasons=seasons,
            teams=sorted(WC2026_TEAMS), n_matches=len(WC2026_TEAMS),
        )
    dc = _saa_malli(tuple(leagues), tuple(seasons))
    n = 0
    try:
        # Mallin opetuksessa käytetty data — heuristinen arvio
        n = len(dc.attack)
    except Exception:
        pass
    teams = sorted(dc.teams_)
    return TeamsResponse(
        leagues=leagues,
        seasons=seasons,
        teams=teams,
        n_matches=n,
    )


# ---------------------------------------------------------------------------
# ENDPOINT: liiga-taulukko (T3)
# ---------------------------------------------------------------------------

# Frontend lähettää PredictScreenistä "ENG-Premier League" (Understat-pohjaista
# data-koodia DC-mallin koulutukseen), mutta football-data.org -pohjaiset
# endpointit (/api/standings, /api/fixtures) tarvitsevat -FD-suffiksin
# saadakseen kilpailukoodin "PL". Muut liigat tulevat frontendiltä jo
# "X-Y-FD"-muodossa.
FD_LEAGUE_ALIASES = {
    "ENG-Premier League": "ENG-Premier League-FD",
}


def _fd_standings_row(row: dict) -> dict:
    """FD:n table-rivi → API:n rivi. Jaettu domestic- ja WC-polun kesken —
    domestic-output pysyy bittitarkasti ennallaan (samat avaimet, sama järjestys)."""
    return {
        "position": row["position"],
        "team_name": row["team"]["name"],
        "team_short_name": row["team"].get("shortName"),
        "team_crest": row["team"].get("crest"),
        "played_games": row["playedGames"],
        "won": row["won"],
        "draw": row["draw"],
        "lost": row["lost"],
        "goals_for": row["goalsFor"],
        "goals_against": row["goalsAgainst"],
        "goal_difference": row["goalDifference"],
        "points": row["points"],
    }


@app.get("/api/standings")
def league_standings(
    league: str = Query(..., description="Liiga-koodi (esim. 'ENG-Premier League' tai 'ESP-La Liga-FD')"),
    season: str | None = Query(default=None, description="Kausi YYMM-muodossa (esim. '2526' → 2025). Default: aktiivinen kausi (dynaaminen). Turnaukset (WC) ignoroivat tämän."),
):
    """
    Liigan tabletti suoraan football-data.org:n /competitions/{id}/standings:ista.

    Returns (domestic):
      - rows: lista riveistä järjestyksessä sijan mukaan
        (position, team_name, team_short_name, team_crest, played_games,
         won, draw, lost, goals_for, goals_against, goal_difference, points)

    Returns (turnaus, esim. INT-World Cup, #19):
      - groups: [{group: "Group A", rows: [rivi + form]}] — FD palauttaa
        lohkoitetun standingsin VAIN ilman season-paramia (verifioitu 12.6.:
        ?season=2026 antaa litteän 48 maan taulukon group=null, ?season=2025
        404:n). Siksi turnaushaara kutsuu FD:tä ilman seasonia.
    """
    from src.data.football_data_org import (
        COMPETITION_CODES,
        _LIVE_TOURNAMENT_CODES,
        _api_key,
        _kausi_to_year,
    )

    if season is None:
        season = config.current_season()
    league_for_fd = FD_LEAGUE_ALIASES.get(league, league)
    code = COMPETITION_CODES.get(league_for_fd)
    if not code:
        raise HTTPException(
            status_code=404,
            detail=f"League '{league}' not supported by football-data.org. "
                   f"Supported: {sorted(COMPETITION_CODES.keys())}",
        )

    api_key = _api_key()
    if not api_key:
        raise HTTPException(
            status_code=500,
            detail="FOOTBALL_DATA_API_KEY not configured on server",
        )

    # Turnaushaara (#19): WC/EC → lohkoitettu standings ilman season-paramia.
    is_tournament = code in _LIVE_TOURNAMENT_CODES
    if is_tournament:
        url = f"https://api.football-data.org/v4/competitions/{code}/standings"
    else:
        year = _kausi_to_year(season)
        url = f"https://api.football-data.org/v4/competitions/{code}/standings?season={year}"
    try:
        r = requests.get(url, headers={"X-Auth-Token": api_key}, timeout=15)
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"Upstream error contacting football-data.org: {type(e).__name__}: {e}",
        )
    if r.status_code != 200:
        raise HTTPException(
            status_code=r.status_code,
            detail=f"football-data.org returned {r.status_code}: {r.text[:200]}",
        )

    data = r.json()

    if is_tournament:
        # Kaikki TOTAL-elementit = lohkot (group: "Group A"… kun FD on
        # lohkomoodissa; jos FD palauttaisi litteän group=null -muodon,
        # groups jää [{group: None, ...}] → frontend fallbackaa staattiseen).
        groups = [
            {
                "group": s.get("group"),
                "rows": [
                    {**_fd_standings_row(row), "form": row.get("form")}
                    for row in s.get("table", [])
                ],
            }
            for s in data.get("standings", [])
            if s.get("type") == "TOTAL" and s.get("group")
        ]
        return {"league": league, "season": None, "groups": groups}

    total = next(
        (s for s in data.get("standings", []) if s.get("type") == "TOTAL"),
        None,
    )
    if not total:
        return {"league": league, "season": season, "rows": []}

    return {
        "league": league,
        "season": season,
        "rows": [_fd_standings_row(row) for row in total["table"]],
    }


# ---------------------------------------------------------------------------
# ENDPOINT: joukkue-detail (T1)
# ---------------------------------------------------------------------------
@app.get("/api/team/{team_name}")
def team_detail(
    team_name: str,
    leagues: list[str] = Query(default=["ENG-Premier League"]),
    seasons: list[str] | None = Query(default=None,
        description="Default: edellinen + aktiivinen kausi (dynaaminen)"),
):
    """
    Joukkueen detail-tiedot DC-mallin koulutusdatasta.

    Käyttää samaa lataa_otteludata-funktiota kuin /api/predict — palauttaa
    cachetetun ottelut-DataFramen liiga+kausi-yhdistelmälle.

    Returns:
      - last_5_matches: 5 viimeisintä ottelua (date, home/away, score, location)
      - form: list of 5 chars ("W"|"D"|"L"), uusin ensin
      - home_stats: kotiotteluiden avg goals for/against + matches_played
      - away_stats: vierasotteluiden avg goals for/against + matches_played
      - total_matches: kokonaisottelumäärä joukkueelle datasetissä
    """
    if seasons is None:
        seasons = config.current_season_pair()
    df = _lataa_otteludata_cached(list(leagues), list(seasons))
    if df.empty:
        raise HTTPException(
            status_code=404,
            detail=f"No match data for leagues={leagues} seasons={seasons}",
        )

    home_matches = df[df["home_team"] == team_name].sort_values("date", ascending=False)
    away_matches = df[df["away_team"] == team_name].sort_values("date", ascending=False)
    all_matches = pd.concat([home_matches, away_matches]).sort_values("date", ascending=False)

    if all_matches.empty:
        raise HTTPException(
            status_code=404,
            detail=f"Team '{team_name}' not found in dataset for "
                   f"leagues={leagues} seasons={seasons}. "
                   f"Use /api/teams to list available teams.",
        )

    last_5_records = all_matches.head(5).to_dict("records")
    last_5_clean = [
        {
            "date": str(m["date"])[:10],
            "home_team": m["home_team"],
            "away_team": m["away_team"],
            "home_score": int(m["home_score"]),
            "away_score": int(m["away_score"]),
            "location": "home" if m["home_team"] == team_name else "away",
        }
        for m in last_5_records
    ]

    def _result(m, team):
        h, a = int(m["home_score"]), int(m["away_score"])
        is_home = m["home_team"] == team
        if h == a:
            return "D"
        if (is_home and h > a) or (not is_home and a > h):
            return "W"
        return "L"

    form = [_result(m, team_name) for m in last_5_records]

    def _venue_stats(matches, is_home: bool):
        if matches.empty:
            return None
        goals_for_col = "home_score" if is_home else "away_score"
        goals_against_col = "away_score" if is_home else "home_score"
        return {
            "avg_goals_for": round(float(matches[goals_for_col].mean()), 2),
            "avg_goals_against": round(float(matches[goals_against_col].mean()), 2),
            "matches_played": int(len(matches)),
        }

    return {
        "team_name": team_name,
        "leagues": leagues,
        "seasons": seasons,
        "last_5_matches": last_5_clean,
        "form": form,
        "home_stats": _venue_stats(home_matches, True),
        "away_stats": _venue_stats(away_matches, False),
        "total_matches": int(len(all_matches)),
    }


# ---------------------------------------------------------------------------
# ENDPOINT: tulevat ottelut (T4)
# ---------------------------------------------------------------------------
@app.get("/api/fixtures")
def upcoming_fixtures(
    league: str = Query(..., description="Liiga-koodi (esim. 'ENG-Premier League' tai 'ESP-La Liga-FD')"),
    days: int = Query(default=7, ge=1, le=60, description="Montako päivää eteenpäin haetaan (turnauksilla laajempi ikkuna)"),
):
    """
    Tulevat ottelut football-data.org:n /competitions/{id}/matches:ista.

    Hakee SCHEDULED + TIMED -statuksen ottelut tästä päivästä `days` päivää
    eteenpäin. Huom: kauden loppupuolella (touko-kesäkuu) lista voi olla tyhjä
    jos liiga on jo pelannut kautensa loppuun — se ei ole virhe.

    Returns:
      - league, days: echo
      - fixtures: lista otteluita aikajärjestyksessä (date, datetime,
        home_team, away_team, home_team_short_name, away_team_short_name,
        matchday)
    """
    from datetime import datetime, timedelta, timezone
    from src.data.football_data_org import COMPETITION_CODES, _api_key

    league_for_fd = FD_LEAGUE_ALIASES.get(league, league)
    code = COMPETITION_CODES.get(league_for_fd)
    if not code:
        raise HTTPException(
            status_code=404,
            detail=f"League '{league}' not supported by football-data.org. "
                   f"Supported: {sorted(COMPETITION_CODES.keys())}",
        )

    api_key = _api_key()
    if not api_key:
        raise HTTPException(
            status_code=500,
            detail="FOOTBALL_DATA_API_KEY not configured on server",
        )

    today = datetime.now(timezone.utc).date()
    date_to = today + timedelta(days=days)
    url = (
        f"https://api.football-data.org/v4/competitions/{code}/matches"
        f"?status=SCHEDULED,TIMED"
        f"&dateFrom={today.isoformat()}&dateTo={date_to.isoformat()}"
    )
    try:
        r = requests.get(url, headers={"X-Auth-Token": api_key}, timeout=15)
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"Upstream error contacting football-data.org: {type(e).__name__}: {e}",
        )
    if r.status_code != 200:
        raise HTTPException(
            status_code=r.status_code,
            detail=f"football-data.org returned {r.status_code}: {r.text[:200]}",
        )

    data = r.json()
    fixtures = []
    for m in data.get("matches", []):
        home = m.get("homeTeam") or {}
        away = m.get("awayTeam") or {}
        # Ohita ottelut joista vastustaja ei ole vielä ratkennut (yleistä
        # CL-karsinnoissa: homeTeam/awayTeam name on tällöin None)
        if not home.get("name") or not away.get("name"):
            continue
        fixtures.append({
            "date": (m.get("utcDate") or "")[:10],
            "datetime": m.get("utcDate"),
            "home_team": home.get("name"),
            "away_team": away.get("name"),
            "home_team_short_name": home.get("shortName"),
            "away_team_short_name": away.get("shortName"),
            "matchday": m.get("matchday"),
        })

    fixtures.sort(key=lambda f: f["datetime"] or "")
    return {"league": league, "days": days, "fixtures": fixtures}


# ---------------------------------------------------------------------------
# T7-apufunktiot: premium-H2H-jakauma + joukkueen muoto-trendi
# ---------------------------------------------------------------------------
def _h2h_summary(h2h_all: pd.DataFrame, home_team: str, away_team: str) -> dict:
    """
    Keskinaisten kohtaamisten voitto/tasapeli/haviö-jakauma (T7 premium).

    'Kaikista' tarkoittaa ladatun kausi-ikkunan sisalta — vastaus EI vaita
    olevansa taydellinen historia. total_matches kertoo todellisen maaran
    jota frontend kayttaa rehellisessa labelissa ("All N meetings").
    """
    if h2h_all.empty:
        return {"total_matches": 0, "home_team_wins": 0, "draws": 0, "away_team_wins": 0}

    home_wins = away_wins = draws = 0
    for _, m in h2h_all.iterrows():
        h, a = int(m["home_score"]), int(m["away_score"])
        if h == a:
            draws += 1
            continue
        winner = m["home_team"] if h > a else m["away_team"]
        if winner == home_team:
            home_wins += 1
        elif winner == away_team:
            away_wins += 1
    return {
        "total_matches": int(len(h2h_all)),
        "home_team_wins": home_wins,
        "draws": draws,
        "away_team_wins": away_wins,
    }


def _h2h_item(m) -> dict:
    """Yksi h2h-rivi API-vastaukseen (#77b).

    Näyttöscore = reg + jatkoaika ILMAN rangaistuspotkuja (*_disp, jonka
    FD-loader johtaa duration == PENALTY_SHOOTOUT -kentästä). FD summaa
    shootoutin fullTimeen (esim. CL-finaali 30.5.2026 fullTime 5-4 = 1-1 +
    pakat 4-3), joten fullTime != disp <=> PENALTY_SHOOTOUT — additiivinen
    penalties-lippu on durationista johdettu, ei heuristiikka.

    Lähteissä ilman disp-sarakkeita (understat-PL, martj42-WC) penalties jää
    Falseksi: pakkatietoa ei ole datassa (WC-puutteen korjaus = shootouts.csv-
    vendorointi, ks. #77-raportti 12.6.).
    """
    h_full, a_full = int(m["home_score"]), int(m["away_score"])
    hd = m.get("home_score_disp")
    ad = m.get("away_score_disp")
    h_disp = h_full if hd is None or pd.isna(hd) else int(hd)
    a_disp = a_full if ad is None or pd.isna(ad) else int(ad)
    item = {
        "date": str(m["date"])[:10],
        "home_team": m["home_team"],
        "away_team": m["away_team"],
        "home_score": h_disp,
        "away_score": a_disp,
        "penalties": (h_full, a_full) != (h_disp, a_disp),
    }
    if item["penalties"]:
        # Shootoutissa fullTime ei voi olla tasan -> voittaja vertailusta.
        item["penalty_winner"] = "home" if h_full > a_full else "away"
    return item


def _team_recent_form(df: pd.DataFrame, team: str, n: int = 8) -> list[dict]:
    """
    Joukkueen n viimeisinta ottelua momentum-visualisointia varten (T7).

    Palautetaan aikajarjestyksessa (vanhin ensin) jotta frontend piirtaa
    tuloskayran luonnollisesti vasemmalta oikealle. Yhden joukkueen otteluita
    on ladatussa 2 kauden datassa runsaasti (~75) — toisin kuin H2H-paria,
    joten muoto-trendi on taysin katettu nykydatalla.
    """
    matches = df[
        (df["home_team"] == team) | (df["away_team"] == team)
    ].sort_values("date", ascending=False).head(n)

    out = []
    for _, m in matches.iterrows():
        is_home = m["home_team"] == team
        scored = int(m["home_score"] if is_home else m["away_score"])
        conceded = int(m["away_score"] if is_home else m["home_score"])
        if scored > conceded:
            result, points = "W", 3
        elif scored == conceded:
            result, points = "D", 1
        else:
            result, points = "L", 0
        out.append({
            "date": str(m["date"])[:10],
            "opponent": m["away_team"] if is_home else m["home_team"],
            "location": "home" if is_home else "away",
            "scored": scored,
            "conceded": conceded,
            "result": result,
            "points": points,
        })
    out.reverse()  # vanhin ensin
    return out


# ---------------------------------------------------------------------------
# ENDPOINT: ennuste
# ---------------------------------------------------------------------------
@app.post("/api/predict", response_model=PredictionResponse)
def predict(req: PredictionRequest):
    """Tee 1X2, O/U 2.5, BTTS -ennuste annetulle ottelulle."""
    dc = _saa_malli(
        tuple(req.leagues), tuple(req.seasons),
        decay=req.decay, bayes_shrinkage=req.bayes_shrinkage,
    )

    if req.home_team not in dc.attack:
        raise HTTPException(
            status_code=404,
            detail=f"Home team '{req.home_team}' not found in model. "
                   f"Use /api/teams to list available teams.",
        )
    if req.away_team not in dc.attack:
        raise HTTPException(
            status_code=404,
            detail=f"Away team '{req.away_team}' not found in model.",
        )

    # Manuaaliset säädöt → multiplier
    saadot = apply_match_adjustments(
        home_injury_pct=req.home_injury_pct,
        away_injury_pct=req.away_injury_pct,
        home_motivation_pct=req.home_motivation_pct,
        away_motivation_pct=req.away_motivation_pct,
        is_derby=req.is_derby,
    )

    # Ennusteet
    lam, mu = dc.expected_goals(req.home_team, req.away_team, adjustments=saadot)
    p_1x2 = dc.predict_1x2(req.home_team, req.away_team, adjustments=saadot)
    p_ou = dc.predict_over_under(req.home_team, req.away_team, line=2.5, adjustments=saadot)
    p_btts = dc.predict_btts(req.home_team, req.away_team, adjustments=saadot)
    top = dc.todennakoisin_tulos(req.home_team, req.away_team, top_n=req.top_n, adjustments=saadot)

    # T5: 5 viimeista keskinaista kohtaamista (molemmat venue-jarjestykset).
    # #71: lataa_otteludata-tason DataFrame-cache eliminoi tuplakutsun cold-
    # latauskustannuksen. Domestic-liigoille pysyva, turnausliigoille
    # ohitettu (#69:n TTL-logiikka).
    df = _lataa_otteludata_cached(list(req.leagues), list(req.seasons))
    h2h_all = df[
        ((df["home_team"] == req.home_team) & (df["away_team"] == req.away_team))
        | ((df["home_team"] == req.away_team) & (df["away_team"] == req.home_team))
    ].sort_values("date", ascending=False)
    # #77b: rivit _h2h_item-helperilla -> nayttoscore ilman pakkoja (CL-
    # shootoutit eivat enaa nayta fullTime 5-4 vaan 1-1 + penalties-lippu).
    h2h = [_h2h_item(m) for _, m in h2h_all.head(5).iterrows()]

    # T7: premium-visualisoinnit — H2H-jakauma + kummankin joukkueen muoto.
    # Kaytetaan jo ladattua df:aa, ei lisalatauskustannuksia.
    # HUOM: summary lasketaan fullTimesta -> pakkapelivoittaja kirjautuu
    # voitoksi (FD-lahteet); h2h-rivin "(pens)"-merkinta selittaa eron.
    h2h_summary = _h2h_summary(h2h_all, req.home_team, req.away_team)
    form_trend = {
        "home_team": _team_recent_form(df, req.home_team),
        "away_team": _team_recent_form(df, req.away_team),
    }

    return PredictionResponse(
        home_team=req.home_team,
        away_team=req.away_team,
        expected_goals_home=round(float(lam), 3),
        expected_goals_away=round(float(mu), 3),
        p_home_win=round(p_1x2["home"], 4),
        p_draw=round(p_1x2["draw"], 4),
        p_away_win=round(p_1x2["away"], 4),
        fair_odds_home=round(1.0 / max(p_1x2["home"], 0.001), 2),
        fair_odds_draw=round(1.0 / max(p_1x2["draw"], 0.001), 2),
        fair_odds_away=round(1.0 / max(p_1x2["away"], 0.001), 2),
        p_over_2_5=round(p_ou["over"], 4),
        p_under_2_5=round(p_ou["under"], 4),
        p_btts_yes=round(p_btts["btts_yes"], 4),
        p_btts_no=round(p_btts["btts_no"], 4),
        top_scores=[{"score": s, "probability": round(p, 4)} for s, p in top],
        h2h=h2h,
        h2h_summary=h2h_summary,
        form_trend=form_trend,
    )


# ---------------------------------------------------------------------------
# WC-endpoint — kansainväliset joukkueet
# ---------------------------------------------------------------------------
def _wc_seasons_to_loader_format(seasons: list[str]) -> list[str]:
    """
    Muunna 4-digit WC-vuodet ('2018', '2022', '2026') 2-digit-formaattiin
    ('18', '22', '26'), jonka football_data_org._kausi_to_year tulkitsee
    oikein vuosiksi 2018, 2022, 2026.

    Tämä kerros suojaa muita endpointteja: emme muuta loaderin
    _kausi_to_year-funktiota, joka tällä hetkellä on suunniteltu
    seurakausi-formaatille '2425' → '2024'.
    """
    out = []
    for s in seasons:
        s = s.strip()
        if len(s) == 4 and s.startswith("20"):
            out.append(s[2:])  # '2018' → '18'
        elif len(s) == 2:
            out.append(s)
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid WC season '{s}'. Use 4-digit year like '2018'.",
            )
    return out


@app.post("/api/predict-wc", response_model=PredictionResponse)
def predict_wc(req: PredictWCRequest):
    """
    Tee 1X2, O/U 2.5, BTTS -ennuste kansainvälisten joukkueiden välille.

    #79: datalähde = martj42 maaotteludata (kaikkien 48 WC-maan tuoreet ottelut).
    Malli on ESIRAKENNETTU (data/wc_model.json) ja ladataan ajossa — Render
    Starter ei jaksa fitata "any"-mallia (195 maata) ajossa ilman timeoutia.
    H2H/form-trend ladataan martj42-datasta (cachetettu CSV-suodatus).
    """
    if req.leagues != ["INT-World Cup"]:
        raise HTTPException(
            status_code=400,
            detail="WC endpoint supports only leagues=['INT-World Cup']. "
                   "Use /api/predict for other leagues.",
        )

    # #79: resolvoi joukkuenimet FD-kanoniseen muotoon (frontend voi lähettää
    # FD-, martj42- tai varianttinimiä). resolve_wc_name palauttaa None jos ei
    # WC2026-maa → 404. Mallin sisäiset nimet + H2H-data ovat kanonisia.
    from src.data.wc_teams import resolve_wc_name
    home_canon = resolve_wc_name(req.home_team)
    away_canon = resolve_wc_name(req.away_team)
    if home_canon is None:
        raise HTTPException(
            status_code=404,
            detail=f"Home team '{req.home_team}' is not a World Cup 2026 team.",
        )
    if away_canon is None:
        raise HTTPException(
            status_code=404,
            detail=f"Away team '{req.away_team}' is not a World Cup 2026 team.",
        )

    loader_seasons = _wc_seasons_to_loader_format(req.seasons)

    # #79: lataa esirakennettu WC-malli (ei fittiä ajossa). JSON-lataus on
    # lru-cachetettu → ~ms. req.decay/req.bayes_shrinkage jätetään huomiotta
    # (malli on rakennettu WC_FIT_DECAY/WC_FIT_BAYES-arvoilla offline).
    from src.data.international_results import load_wc_model
    try:
        dc_cached = load_wc_model()
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"WC model unavailable: {type(e).__name__}",
        )

    # WC-otteluita pelataan neutraalilla maalla (Qatar 2022, USA/CAN/MEX 2026).
    # DC-malli oppii datasta globaalin kotiedun (home_advantage = γ) koska data
    # on kirjattu home/away-rakenteena.
    #
    # #61 (2b-1): neutralointi ei ole home_advantage=0 vaan PUOLET kotiedusta
    # molemmille. Mallissa lam saa kotiboostin γ, mu ei saa mitään → pelkkä
    # nollaus ennustaisi BOLEMMAT joukkueet vierasvauhtia (kokonaistaso
    # deflatoituu ~exp(γ/2)). Oikea neutraali = kotidatan ja vierasdatan
    # geometrinen keskiarvo: molemmat saavat γ/2.
    #
    # γ/2 viedään defence-parametriin, koska defence esiintyy SEKÄ lam:ssa
    # (defence[away]) ETTÄ mu:ssa (defence[home]) → boost osuu molempiin.
    # Shallow-kopio: defence-dict KORVATAAN uudella, alkuperäinen cache säilyy.
    dc = copy.copy(dc_cached)
    half_home_adv = dc_cached.home_advantage / 2.0
    dc.defence = {t: v + half_home_adv for t, v in dc_cached.defence.items()}
    dc.home_advantage = 0.0
    dc.home_advantage_per_team = {t: 0.0 for t in dc.teams_}

    # Sekundaarivahti: maa on validi WC-maa mutta sillä ei ole dataa ikkunassa
    # (käytännössä ei tapahdu — min ~22-38 ottelua/maa). Kanoniset nimet.
    if home_canon not in dc.attack:
        raise HTTPException(
            status_code=404,
            detail=f"No recent international data for '{req.home_team}'.",
        )
    if away_canon not in dc.attack:
        raise HTTPException(
            status_code=404,
            detail=f"No recent international data for '{req.away_team}'.",
        )

    saadot = apply_match_adjustments(
        home_injury_pct=req.home_injury_pct,
        away_injury_pct=req.away_injury_pct,
        home_motivation_pct=req.home_motivation_pct,
        away_motivation_pct=req.away_motivation_pct,
        is_derby=req.is_derby,
    )

    lam, mu = dc.expected_goals(home_canon, away_canon, adjustments=saadot)
    p_1x2 = dc.predict_1x2(home_canon, away_canon, adjustments=saadot)
    p_ou = dc.predict_over_under(home_canon, away_canon, line=2.5, adjustments=saadot)
    p_btts = dc.predict_btts(home_canon, away_canon, adjustments=saadot)
    top = dc.todennakoisin_tulos(home_canon, away_canon, top_n=5, adjustments=saadot)

    # T5/T7 (#25): H2H + form-trend WC-historiadatasta (sama WC-loader jota malli
    # kayttaa). Mirror domestic /api/predict -polusta — _h2h_summary +
    # _team_recent_form ovat geneerisia (df + nimet). df ladataan loader_seasons-
    # formaatissa (#69:n turnaus-TTL hoitaa cachen).
    df = _lataa_otteludata_cached(list(req.leagues), loader_seasons)
    h2h_all = df[
        ((df["home_team"] == home_canon) & (df["away_team"] == away_canon))
        | ((df["home_team"] == away_canon) & (df["away_team"] == home_canon))
    ].sort_values("date", ascending=False)
    # #25/#77b: rivit _h2h_item-helperilla (näyttöscore ilman pakkoja +
    # penalties-lippu). martj42-datassa ei ole disp-/shootout-sarakkeita ->
    # penalties jää aina Falseksi tällä polulla.
    h2h = [_h2h_item(m) for _, m in h2h_all.head(5).iterrows()]
    # HUOM (#77, todettu 12.6.): martj42-scoret ovat reg + jatkoaika ILMAN
    # pakkoja -> summary kirjaa pakkapelivoitot TASAPELEIKSI (esim. Argentina-
    # France 2022 = draw). Tunnettu rajoite; faktinen korjaus vaatisi martj42
    # shootouts.csv:n vendoroinnin (h2h-only lookup, Villen päätös).
    h2h_summary = _h2h_summary(h2h_all, home_canon, away_canon)
    form_trend = {
        "home_team": _team_recent_form(df, home_canon),
        "away_team": _team_recent_form(df, away_canon),
    }

    return PredictionResponse(
        home_team=req.home_team,
        away_team=req.away_team,
        expected_goals_home=round(float(lam), 3),
        expected_goals_away=round(float(mu), 3),
        p_home_win=round(p_1x2["home"], 4),
        p_draw=round(p_1x2["draw"], 4),
        p_away_win=round(p_1x2["away"], 4),
        fair_odds_home=round(1.0 / max(p_1x2["home"], 0.001), 2),
        fair_odds_draw=round(1.0 / max(p_1x2["draw"], 0.001), 2),
        fair_odds_away=round(1.0 / max(p_1x2["away"], 0.001), 2),
        p_over_2_5=round(p_ou["over"], 4),
        p_under_2_5=round(p_ou["under"], 4),
        p_btts_yes=round(p_btts["btts_yes"], 4),
        p_btts_no=round(p_btts["btts_no"], 4),
        top_scores=[{"score": s, "probability": round(p, 4)} for s, p in top],
        h2h=h2h,
        h2h_summary=h2h_summary,
        form_trend=form_trend,
    )


# ---------------------------------------------------------------------------
# ENDPOINT: parlay — P(kaikki valinnat oikein) tulona (vC23, premium-UI)
#
# Gambling-turvallinen linja: EI kertoimia, EI "odds"/"betting"-sanastoa —
# vain "model-implied probability that all N predictions are correct".
# Riippumattomuusoletus sanotaan vastauksessa eksplisiittisesti.
#
# Reuse ilman tuplafittiä: domestic-leg osuu _saa_malli-cacheen (warmup
# esifittaa 6 liigaa) ja WC-leg lru-cachettuun load_wc_model():iin. Leg laskee
# VAIN predict_1x2:n — ei H2H/form/top_scores-kuormaa. predict()/predict_wc()
# -funktioihin ei kosketa (domestic bit-exact, regressiosuite vahtii).
# ---------------------------------------------------------------------------
class ParlayLeg(BaseModel):
    """Yksi parlay-valinta: ottelu + käyttäjän 1/X/2-pick."""
    home_team: str = Field(..., examples=["Arsenal"])
    away_team: str = Field(..., examples=["Liverpool"])
    leagues: list[str] = Field(default=["ENG-Premier League"])
    seasons: list[str] = Field(default_factory=config.current_season_pair)
    pick: Literal["1", "X", "2"] = Field(
        ..., description="1 = home win, X = draw, 2 = away win")


class ParlayRequest(BaseModel):
    legs: list[ParlayLeg] = Field(..., min_length=2, max_length=5)

    @field_validator("legs")
    @classmethod
    def _no_duplicate_matches(cls, v: list[ParlayLeg]) -> list[ParlayLeg]:
        # Sama ottelu kahdesti rikkoisi riippumattomuustulon (p*p != p).
        seen = set()
        for leg in v:
            key = (leg.home_team, leg.away_team, tuple(leg.leagues))
            if key in seen:
                raise ValueError(
                    f"Duplicate match in parlay: {leg.home_team} vs {leg.away_team}")
            seen.add(key)
        return v


class ParlayLegResult(BaseModel):
    home_team: str
    away_team: str
    leagues: list[str]
    pick: str
    p_home_win: float
    p_draw: float
    p_away_win: float
    pick_probability: float


class ParlayResponse(BaseModel):
    legs: list[ParlayLegResult]
    n_legs: int
    # Tulo pyöristetyistä per-leg-arvoista (4 dp) → näytetyistä luvuista
    # laskettavissa käsin. 6 dp riittää 5 legille (min ~1e-5-tasoa).
    combined_probability: float
    assumes_independence: bool = True
    note: str
    disclaimer: str


def _parlay_leg_1x2(leg: ParlayLeg, idx: int) -> dict:
    """Palauta legin 1X2-jakauma lämpimästä mallista. HTTPException jos
    joukkue/malli puuttuu — virheviesti kantaa leg-numeron (1-pohjainen)."""
    if leg.leagues == ["INT-World Cup"]:
        from src.data.wc_teams import resolve_wc_name
        from src.data.international_results import load_wc_model
        home = resolve_wc_name(leg.home_team)
        away = resolve_wc_name(leg.away_team)
        if home is None:
            raise HTTPException(
                status_code=404,
                detail=f"Leg {idx + 1}: '{leg.home_team}' is not a World Cup 2026 team.")
        if away is None:
            raise HTTPException(
                status_code=404,
                detail=f"Leg {idx + 1}: '{leg.away_team}' is not a World Cup 2026 team.")
        try:
            dc_cached = load_wc_model()
        except Exception as e:
            raise HTTPException(
                status_code=503,
                detail=f"WC model unavailable: {type(e).__name__}")
        # #61 (2b-1): neutraali venue = γ/2 molemmille defenceen — sama
        # neutralointi kuin predict_wc():ssä (kopio, jotta sitä ei kosketa).
        dc = copy.copy(dc_cached)
        half = dc_cached.home_advantage / 2.0
        dc.defence = {t: v + half for t, v in dc_cached.defence.items()}
        dc.home_advantage = 0.0
        dc.home_advantage_per_team = {t: 0.0 for t in dc.teams_}
        if home not in dc.attack or away not in dc.attack:
            raise HTTPException(
                status_code=404,
                detail=f"Leg {idx + 1}: no recent international data for this pair.")
        return dc.predict_1x2(home, away)

    dc = _saa_malli(tuple(leg.leagues), tuple(leg.seasons))
    if leg.home_team not in dc.attack:
        raise HTTPException(
            status_code=404,
            detail=f"Leg {idx + 1}: home team '{leg.home_team}' not found in model. "
                   f"Use /api/teams to list available teams.")
    if leg.away_team not in dc.attack:
        raise HTTPException(
            status_code=404,
            detail=f"Leg {idx + 1}: away team '{leg.away_team}' not found in model.")
    return dc.predict_1x2(leg.home_team, leg.away_team)


@app.post("/api/parlay", response_model=ParlayResponse)
def parlay(req: ParlayRequest):
    """
    Model-implied probability that all N predictions are correct.

    2-5 ottelua, kullekin käyttäjän 1/X/2-valinta → per-leg P(valittu
    lopputulos) + kumulatiivinen tulo. Olettaa ottelut riippumattomiksi
    (assumes_independence: true) — sanottu rehellisesti vastauksessa.
    """
    pick_key = {"1": "home", "X": "draw", "2": "away"}
    results: list[ParlayLegResult] = []
    combined = 1.0
    for i, leg in enumerate(req.legs):
        p = _parlay_leg_1x2(leg, i)
        ph, pd_, pa = round(p["home"], 4), round(p["draw"], 4), round(p["away"], 4)
        pick_p = {"1": ph, "X": pd_, "2": pa}[leg.pick]
        combined *= pick_p
        results.append(ParlayLegResult(
            home_team=leg.home_team, away_team=leg.away_team,
            leagues=leg.leagues, pick=leg.pick,
            p_home_win=ph, p_draw=pd_, p_away_win=pa,
            pick_probability=pick_p,
        ))
    return ParlayResponse(
        legs=results,
        n_legs=len(results),
        combined_probability=round(combined, 6),
        assumes_independence=True,
        note="Combined probability assumes each match is independent.",
        disclaimer="Model prediction, not betting advice.",
    )


# ---------------------------------------------------------------------------
# ENDPOINT: tyhjennä mallin välimuisti (debug-tarkoitukseen)
# ---------------------------------------------------------------------------
@app.post("/api/admin/clear-cache")
def clear_cache():
    """Tyhjennä mallin välimuisti — pakottaa uudelleen-sovituksen."""
    from src.data.football_data_org import _TOURNAMENT_MEM_CACHE
    with _MODEL_LOCK:
        n = len(_MODEL_CACHE)
        _MODEL_CACHE.clear()
        _MODEL_FITTED_AT.clear()
        _REFIT_IN_PROGRESS.clear()
    cleared_tournament = len(_TOURNAMENT_MEM_CACHE)
    _TOURNAMENT_MEM_CACHE.clear()
    with _DATA_CACHE_LOCK:
        cleared_data = len(_DATA_CACHE)
        _DATA_CACHE.clear()
    return {
        "cleared_models": n,
        "cleared_tournament_data": cleared_tournament,
        "cleared_match_data": cleared_data,
    }


# ---------------------------------------------------------------------------
# STRIPE: Checkout-session ja webhook
# ---------------------------------------------------------------------------
class CheckoutRequest(BaseModel):
    """Pyyntö Stripe Checkout Sessionin luomiseen."""
    user_id: str = Field(..., description="Supabase user UUID")
    email: str = Field(..., description="Käyttäjän sähköposti (Stripe lähettää kuitin)")


class CheckoutResponse(BaseModel):
    checkout_url: str
    session_id: str


@app.post("/api/checkout", response_model=CheckoutResponse)
def create_checkout_session(req: CheckoutRequest):
    """
    Luo Stripe Checkout Session premium-tilaukselle.

    Mobiili-app kutsuu tätä → saa `checkout_url`:n → avaa selaimessa →
    kayttaja maksaa → Stripe lahettaa webhook:in joka päivittää
    Supabase profiles.is_premium = true.
    """
    if not stripe.api_key:
        raise HTTPException(
            status_code=500,
            detail="Stripe not configured (STRIPE_SECRET_KEY missing)",
        )
    if not STRIPE_PRICE_ID:
        raise HTTPException(
            status_code=500,
            detail="Stripe price not configured (STRIPE_PRICE_ID missing)",
        )

    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            payment_method_types=["card"],
            line_items=[{
                "price": STRIPE_PRICE_ID,
                "quantity": 1,
            }],
            customer_email=req.email,
            client_reference_id=req.user_id,  # Webhook käyttää tätä identifiointiin
            metadata={"user_id": req.user_id},
            # Kopioi user_id myös tilauksen metadataan, jotta cancel-eventti
            # tietää kenen premium poistetaan
            subscription_data={"metadata": {"user_id": req.user_id}},
            # Deep linkit takaisin mobiili-appiin
            success_url="goaliq://payment-success?session_id={CHECKOUT_SESSION_ID}",
            cancel_url="goaliq://payment-cancel",
            allow_promotion_codes=True,
        )
        return CheckoutResponse(
            checkout_url=session.url or "",
            session_id=session.id,
        )
    except stripe.error.StripeError as e:
        raise HTTPException(status_code=400, detail=f"Stripe error: {e.user_message or str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal error: {e}")


class PortalRequest(BaseModel):
    email: str = Field(..., description="Käyttäjän sähköposti (löytää Stripe-customerin)")


class PortalResponse(BaseModel):
    portal_url: str


@app.post("/api/customer-portal", response_model=PortalResponse)
def create_portal_session(req: PortalRequest):
    """
    Luo Stripe Customer Portal -session jossa kayttaja voi peruuttaa
    tilauksen, paivittaa kortin tai nahda laskut.

    Customer haetaan emailin perusteella (yksinkertaisin lahestymistapa MVP:lle —
    myohemmin voi tallentaa stripe_customer_id Supabaseen).
    """
    if not stripe.api_key:
        raise HTTPException(status_code=500, detail="Stripe not configured")

    try:
        # Etsi Stripe-customer emailin perusteella
        customers = stripe.Customer.list(email=req.email, limit=1)
        if not customers.data:
            raise HTTPException(
                status_code=404,
                detail=f"No Stripe customer found for {req.email}",
            )
        customer_id = customers.data[0].id

        # Luo portal-session
        session = stripe.billing_portal.Session.create(
            customer=customer_id,
            return_url="goaliq://subscription-managed",
        )
        return PortalResponse(portal_url=session.url)
    except stripe.error.StripeError as e:
        raise HTTPException(
            status_code=400,
            detail=f"Stripe error: {e.user_message or str(e)}",
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal error: {e}")


@app.post("/api/webhook/stripe")
async def stripe_webhook(request: Request):
    """
    Vastaanottaa Stripen webhookit. Päivittää Supabase profiles.is_premium
    kun maksu onnistuu / tilaus loppuu.

    HUOM: Tama vaatii myöhemmin Supabase service-role-key:n (premium-statuksen
    päivittäminen edellyttää backend-oikeuksia). Toteutetaan vaiheittain.
    """
    if not STRIPE_WEBHOOK_SECRET:
        # Webhook-secret ei vielä konfiguroitu — palauta 200 OK että Stripe
        # ei yritä uudelleen jatkuvasti
        return {"received": True, "warning": "STRIPE_WEBHOOK_SECRET not configured"}

    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    # Tarkista allekirjoitus Stripen kirjastolla (ei käytetä paluuarvoa,
    # koska StripeObject ei tue .get() -metodia natiivisti)
    try:
        stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    # Parsitaan raaka JSON käsittelyä varten — natiivi dict on luotettavampi
    # kuin Stripen StripeObject-wrapper sisäkkäisten kenttien lukemiseen
    event = json.loads(payload)
    event_type = event["type"]
    obj = event["data"]["object"]

    if event_type == "checkout.session.completed":
        # Maksu onnistui — aktivoi premium ja nollaa cancel-tiedot
        user_id = obj.get("client_reference_id") or obj.get("metadata", {}).get("user_id")
        if user_id:
            print(f"[Stripe webhook] checkout.session.completed user_id={user_id}")
            _update_profile(user_id, {
                "is_premium": True,
                "subscription_cancel_at_period_end": False,
                # current_period_end asetetaan kun subscription.updated saapuu
            })
        else:
            print(f"[Stripe webhook] checkout.session.completed but no user_id in payload")

    elif event_type == "customer.subscription.updated":
        # Subscription muuttui — esim. kayttaja peruutti, mutta access on
        # voimassa current_period_end -paivaan asti
        user_id = obj.get("metadata", {}).get("user_id")
        if user_id:
            from datetime import datetime, timezone

            # Stripe API:n eri versiot tallentavat cancel-tiedot eri tavoin:
            # - Vanhempi: cancel_at_period_end (boolean) + current_period_end juuressa
            # - Uudempi (2026+): cancel_at (timestamp) + current_period_end items[0]:ssa
            cancel_at_end_bool = obj.get("cancel_at_period_end", False)
            cancel_at_ts = obj.get("cancel_at")  # uudempi: timestamp tai None
            is_canceled = bool(cancel_at_end_bool) or bool(cancel_at_ts)

            # period_end: kokeile juurikenttaa, sitten cancel_at-timestampia,
            # viimeiseksi items[0].current_period_end (uudempi API)
            period_end_ts = obj.get("current_period_end") or cancel_at_ts
            if not period_end_ts:
                items = obj.get("items") or {}
                items_data = items.get("data") if isinstance(items, dict) else None
                if items_data:
                    period_end_ts = items_data[0].get("current_period_end")

            period_end_iso = None
            if period_end_ts:
                period_end_iso = datetime.fromtimestamp(
                    period_end_ts, tz=timezone.utc
                ).isoformat()
            print(
                f"[Stripe webhook] subscription.updated user_id={user_id} "
                f"is_canceled={is_canceled} (bool={cancel_at_end_bool} ts={cancel_at_ts}) "
                f"period_end={period_end_iso}"
            )
            _update_profile(user_id, {
                "subscription_cancel_at_period_end": is_canceled,
                "subscription_current_period_end": period_end_iso,
            })
        else:
            print(f"[Stripe webhook] subscription.updated no user_id sub_id={obj.get('id')}")

    elif event_type == "customer.subscription.deleted":
        # Tilaus peruttu/loppui — paivita is_premium=false
        user_id = obj.get("metadata", {}).get("user_id")
        if user_id:
            print(f"[Stripe webhook] subscription.deleted user_id={user_id}")
            _update_profile(user_id, {
                "is_premium": False,
                "subscription_cancel_at_period_end": False,
                "subscription_current_period_end": None,
            })
        else:
            print(f"[Stripe webhook] subscription.deleted no user_id in metadata sub_id={obj.get('id')}")

    else:
        print(f"[Stripe webhook] ignored event_type={event_type}")

    return {"received": True}


@app.post("/api/revenuecat/webhook")
async def revenuecat_webhook(request: Request):
    """
    Vastaanottaa RevenueCat-webhookit (Google Play Billing). Paivittaa
    Supabase profiles.is_premium app_user_id:n (= Supabase auth user id)
    perusteella.

    Eventit:
      INITIAL_PURCHASE / RENEWAL / UNCANCELLATION / PRODUCT_CHANGE /
      NON_RENEWING_PURCHASE -> is_premium=True (access voimassa)
      CANCELLATION -> is_premium pysyy True, mutta merkitaan
        cancel_at_period_end=True (auto-renew pois; access jatkuu
        expiration-paivaan asti). Lopullinen access-poisto tulee
        EXPIRATION-eventissa.
      EXPIRATION -> is_premium=False (access paattyi)

    Autentikointi: RevenueCat lahettaa dashboardiin asetetun salaisuuden
    Authorization-headerissa. REVENUECAT_WEBHOOK_AUTH-env-muuttuja on
    pakollinen — jos puuttuu, webhook ei kirjoita mitaan.
    """
    if not REVENUECAT_WEBHOOK_AUTH:
        # Ei konfiguroitu — palauta 200 ettei RevenueCat retry-loopaa, mutta
        # ALA kirjoita Supabaseen (turvallinen oletus).
        return {"received": True, "warning": "REVENUECAT_WEBHOOK_AUTH not configured"}

    auth_header = request.headers.get("authorization", "")
    if auth_header != REVENUECAT_WEBHOOK_AUTH:
        raise HTTPException(status_code=401, detail="Invalid authorization")

    payload = await request.body()
    try:
        data = json.loads(payload)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid payload")

    event = data.get("event", {}) or {}
    event_type = event.get("type", "")

    # Resolvoi Supabase-auth-id alias-joukosta. Osto saattoi tapahtua anonyymilla
    # id:lla ennen logIn:ia → RevenueCat aliasoi anonyymin + Supabase-id:n samaan
    # subscriberiin. Webhook-eventin app_user_id voi olla kumpi tahansa: erityisesti
    # EXPIRATION kantaa usein original_app_user_id:n (= anonyymin), jolloin pelkka
    # app_user_id:n lukeminen skippasi downgraden vaarin. Kay lapi kaikki kandidaatit
    # (app_user_id, original_app_user_id, aliases) ja valitse ensimmainen ei-anonyymi.
    candidate_ids = [
        event.get("app_user_id") or "",
        event.get("original_app_user_id") or "",
        *(event.get("aliases") or []),
    ]
    user_id = next(
        (cid for cid in candidate_ids if cid and not cid.startswith("$RCAnonymousID:")),
        "",
    )

    # Ei yhtaan ei-anonyymia Supabase-id:ta → ei voida paivittaa profiilia.
    if not user_id:
        print(
            f"[RevenueCat webhook] skip event_type={event_type} "
            f"candidates={candidate_ids!r}"
        )
        return {"received": True}

    # expiration_at_ms = milloin access paattyy (renewal-/cancel-tieto).
    from datetime import datetime, timezone

    expiration_ms = event.get("expiration_at_ms")
    period_end_iso = None
    if expiration_ms:
        try:
            period_end_iso = datetime.fromtimestamp(
                int(expiration_ms) / 1000, tz=timezone.utc
            ).isoformat()
        except (ValueError, OSError, OverflowError):
            period_end_iso = None

    active_events = {
        "INITIAL_PURCHASE",
        "RENEWAL",
        "UNCANCELLATION",
        "PRODUCT_CHANGE",
        "NON_RENEWING_PURCHASE",
    }

    if event_type in active_events:
        print(f"[RevenueCat webhook] {event_type} user_id={user_id} period_end={period_end_iso}")
        _update_profile(user_id, {
            "is_premium": True,
            "subscription_cancel_at_period_end": False,
            "subscription_current_period_end": period_end_iso,
        })
    elif event_type == "CANCELLATION":
        # Auto-renew pois paalta; access jatkuu expiration-paivaan asti.
        cancel_reason = event.get("cancel_reason", "")
        print(
            f"[RevenueCat webhook] CANCELLATION user_id={user_id} "
            f"reason={cancel_reason} period_end={period_end_iso}"
        )
        _update_profile(user_id, {
            "is_premium": True,
            "subscription_cancel_at_period_end": True,
            "subscription_current_period_end": period_end_iso,
        })
    elif event_type == "EXPIRATION":
        print(f"[RevenueCat webhook] EXPIRATION user_id={user_id}")
        _update_profile(user_id, {
            "is_premium": False,
            "subscription_cancel_at_period_end": False,
            "subscription_current_period_end": None,
        })
    else:
        # BILLING_ISSUE, TEST, TRANSFER ym. — ei muutosta is_premiumiin.
        print(f"[RevenueCat webhook] ignored event_type={event_type} user_id={user_id}")

    return {"received": True}


@app.get("/api/revenuecat-config")
def revenuecat_config():
    """Diagnostiikka: onko RevenueCat-webhook konfiguroitu (ei paljasta arvoja)."""
    return {
        "webhook_auth_set": bool(REVENUECAT_WEBHOOK_AUTH),
        "supabase_url_set": bool(SUPABASE_URL),
        "supabase_service_role_key_set": bool(SUPABASE_SERVICE_ROLE_KEY),
    }


@app.get("/api/debug/seasons")
def debug_seasons(league: str = Query(default="INT-World Cup")):
    """
    Listaa kaikki seasonit jotka soccerdata FBref tunnistaa annetulle liigalle.
    Auttaa selvittämään oikean season-formaatin.
    """
    try:
        import soccerdata as sd
        # available_leagues() palauttaa kaikki tuetut liigat
        all_leagues = sd.FBref.available_leagues()
        # Yritä luoda FBref-instanssi pelkalla liigalla -> tuottaa virheen jossa
        # season-vaatimukset näkyvät
        result = {"league": league, "league_valid": league in all_leagues}
        # Haetaan saatavilla olevat seasonit suoraan
        try:
            # Kokeile tehdä instanssi ilman seasonia — antaa default-listan
            inst = sd.FBref(leagues=[league])
            # _selected_seasons sisältää seasonit jotka instanssi tunnistaa
            seasons = inst.seasons if hasattr(inst, "seasons") else None
            if seasons is None and hasattr(inst, "_selected_seasons"):
                seasons = inst._selected_seasons
            result["available_seasons_default"] = list(seasons) if seasons else "?"
        except Exception as e:
            result["seasons_error"] = f"{type(e).__name__}: {str(e)[:300]}"
        return result
    except Exception as e:
        return {"error": f"{type(e).__name__}: {str(e)[:500]}"}


@app.get("/api/debug/load")
def debug_load(
    leagues: list[str] = Query(default=["INT-World Cup"]),
    seasons: list[str] = Query(default=["2022"]),
):
    """
    Debug-endpoint: yritä ladata otteludata ja palauta tarkat virheviestit
    per datalähde. Auttaa selvittämään miksi joku liiga ei toimi.
    """
    from src.data.loader import lataa_otteludata_yksityiskohtaisesti
    tulos = lataa_otteludata_yksityiskohtaisesti(leagues, seasons)
    return {
        "requested_leagues": leagues,
        "requested_seasons": seasons,
        "rows_loaded": int(len(tulos.data)),
        "successes_per_league": tulos.onnistui,
        "errors_per_league": tulos.virheet,
        "sample_columns": list(tulos.data.columns) if not tulos.data.empty else [],
    }


@app.get("/api/stripe-config")
def stripe_config():
    """Diagnostiikka: tarkista että Stripe on konfiguroitu (älä paljasta avaimia)."""
    return {
        "secret_key_set": bool(stripe.api_key),
        "price_id_set": bool(STRIPE_PRICE_ID),
        "webhook_secret_set": bool(STRIPE_WEBHOOK_SECRET),
        "supabase_url_set": bool(SUPABASE_URL),
        "supabase_service_role_key_set": bool(SUPABASE_SERVICE_ROLE_KEY),
    }
