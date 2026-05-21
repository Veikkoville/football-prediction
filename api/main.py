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
from pathlib import Path
from typing import Optional

# Lisää projektin juuri Python-polkuun jotta `src.*` -importit toimivat
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
import stripe
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import config
from src.data.loader import lataa_otteludata
from src.models.dixon_coles import DixonColesModel, apply_match_adjustments

import requests

# Stripe-konfiguraatio (Render env varseista)
stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_PRICE_ID = os.getenv("STRIPE_PRICE_ID", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")

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


# ---------------------------------------------------------------------------
# Lämmitys käynnistyksessä — sovittaa oletusmallin (PL 24/25 + 25/26) taustalla
# jotta ensimmäinen /api/predict kutsu on nopea (ei 5-15s mallin sovitusta)
# ---------------------------------------------------------------------------
@app.on_event("startup")
def _warmup_default_model():
    import threading

    def _fit_premier_league():
        try:
            print("[Warmup] Pre-fitting Premier League DC model...")
            _saa_malli(("ENG-Premier League",), ("2425", "2526"))
            print("[Warmup] Premier League model ready.")
        except Exception as e:
            print(f"[Warmup] Premier League failed: {e}")

    # World Cup pre-warm poistettu launchin ajaksi —
    # soccerdata vaatii Chromen WC-sivuille jota Renderissä ei ole.
    # WC-tuki lisätään launchin jälkeen joko hardcoded-JSON:lla tai
    # Chromen asennuksella Starter-tasolla.

    threading.Thread(target=_fit_premier_league, daemon=True).start()


def _saa_malli(liigat: tuple[str, ...], kaudet: tuple[str, ...],
               decay: float = 0.0035, bayes_shrinkage: float = 2.0) -> DixonColesModel:
    """Hae cached DC-malli tai sovita uusi jos ei välimuistissa."""
    key = (liigat, kaudet, round(decay, 4), round(bayes_shrinkage, 2))
    if key not in _MODEL_CACHE:
        df = lataa_otteludata(list(liigat), list(kaudet))
        if df.empty:
            raise HTTPException(
                status_code=404,
                detail=f"No match data found for leagues={liigat}, seasons={kaudet}",
            )
        try:
            dc = DixonColesModel().fit(
                df,
                home_team_col="home_team", away_team_col="away_team",
                home_goals_col="home_score", away_goals_col="away_score",
                decay=decay, date_col="date",
                l2_attack_defence=bayes_shrinkage,
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Model fit failed: {e}")
        _MODEL_CACHE[key] = dc
    return _MODEL_CACHE[key]


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
        default=["2425", "2526"],
        description="Seasons (YYMM format)",
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
    # WC-otteluissa ei perinteistä kotietua → decay pienempi (vanha data
    # arvokkaampaa kun kausia on 3 eri vuotta) ja shrinkage suurempi
    # (uudet kvalifioituneet maajoukkueet kohti kv-keskiarvoa).
    decay: float = Field(default=0.0010, ge=0.0, le=0.020)
    bayes_shrinkage: float = Field(default=3.0, ge=0.0, le=10.0)
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
        "available_seasons": ["2122", "2223", "2324", "2425", "2526"],
        # Selitykset mobiilia varten — joukkueiden valinta liigan mukaan
        "league_presets": {
            "ENG-Premier League": {
                "label": "Premier League",
                "icon": "⚽",
                "seasons": ["2425", "2526"],
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
    seasons: list[str] = Query(default=["2425", "2526"]),
):
    """Lista joukkueista jotka mallissa esiintyvät annetussa liiga+kausi-yhdistelmässä."""
    dc = _saa_malli(tuple(leagues), tuple(seasons))
    n = 0
    try:
        # Mallin opetuksessa käytetty data — heuristinen arvio
        n = len(dc.attack)
    except Exception:
        pass
    return TeamsResponse(
        leagues=leagues,
        seasons=seasons,
        teams=sorted(dc.teams_),
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


@app.get("/api/standings")
def league_standings(
    league: str = Query(..., description="Liiga-koodi (esim. 'ENG-Premier League' tai 'ESP-La Liga-FD')"),
    season: str = Query(default="2526", description="Kausi YYYY tai YY:YY muodossa (esim. '2526' → 2025)"),
):
    """
    Liigan tabletti suoraan football-data.org:n /competitions/{id}/standings:ista.

    Returns:
      - rows: lista riveistä järjestyksessä sijan mukaan
        (position, team_name, team_short_name, team_crest, played_games,
         won, draw, lost, goals_for, goals_against, goal_difference, points)
    """
    from src.data.football_data_org import COMPETITION_CODES, _api_key, _kausi_to_year

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
    total = next(
        (s for s in data.get("standings", []) if s.get("type") == "TOTAL"),
        None,
    )
    if not total:
        return {"league": league, "season": season, "rows": []}

    return {
        "league": league,
        "season": season,
        "rows": [
            {
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
            for row in total["table"]
        ],
    }


# ---------------------------------------------------------------------------
# ENDPOINT: joukkue-detail (T1)
# ---------------------------------------------------------------------------
@app.get("/api/team/{team_name}")
def team_detail(
    team_name: str,
    leagues: list[str] = Query(default=["ENG-Premier League"]),
    seasons: list[str] = Query(default=["2425", "2526"]),
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
    df = lataa_otteludata(list(leagues), list(seasons))
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
    days: int = Query(default=7, ge=1, le=30, description="Montako päivää eteenpäin haetaan"),
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
    # Lataa_otteludata on sama kuin _saa_malli kayttaa sisaisesti — loader
    # cachettaa DataFrame:n joten tama on kayatannossa lookup.
    df = lataa_otteludata(list(req.leagues), list(req.seasons))
    h2h_all = df[
        ((df["home_team"] == req.home_team) & (df["away_team"] == req.away_team))
        | ((df["home_team"] == req.away_team) & (df["away_team"] == req.home_team))
    ].sort_values("date", ascending=False)
    h2h = [
        {
            "date": str(m["date"])[:10],
            "home_team": m["home_team"],
            "away_team": m["away_team"],
            "home_score": int(m["home_score"]),
            "away_score": int(m["away_score"]),
        }
        for _, m in h2h_all.head(5).iterrows()
    ]

    # T7: premium-visualisoinnit — H2H-jakauma + kummankin joukkueen muoto.
    # Kaytetaan jo ladattua df:aa, ei lisalatauskustannuksia.
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
    Tee 1X2, O/U 2.5, BTTS -ennuste kansainvälisten joukkueiden välille
    WC-historiadatan pohjalta (WC 2018 + 2022 + 2026 fixtures).

    Datalähde: football-data.org ML Pack Light -tier.
    Env: FOOTBALL_DATA_API_KEY pakollinen.
    """
    if req.leagues != ["INT-World Cup"]:
        raise HTTPException(
            status_code=400,
            detail="WC endpoint supports only leagues=['INT-World Cup']. "
                   "Use /api/predict for other leagues.",
        )

    loader_seasons = _wc_seasons_to_loader_format(req.seasons)

    dc_cached = _saa_malli(
        tuple(req.leagues), tuple(loader_seasons),
        decay=req.decay, bayes_shrinkage=req.bayes_shrinkage,
    )

    # WC-otteluita pelataan neutraalilla maalla (Qatar 2022, USA/CAN/MEX 2026).
    # DC-malli oppii datasta noin ~1.5x kotietu-kerroin koska data on kirjattu
    # home/away-rakenteena, vaikka kentällä koti-rooli on satunnainen ja
    # merkityksetön. Nollataan kotietu shallow-kopiolla — alkuperäinen
    # cache-objekti säilyy ennallaan muille mahdollisille kutsujille.
    dc = copy.copy(dc_cached)
    dc.home_advantage = 0.0
    dc.home_advantage_per_team = {t: 0.0 for t in dc.teams_}

    if req.home_team not in dc.attack:
        raise HTTPException(
            status_code=404,
            detail=f"Home team '{req.home_team}' not found in WC model. "
                   f"First 10 available: {sorted(dc.teams_)[:10]}.",
        )
    if req.away_team not in dc.attack:
        raise HTTPException(
            status_code=404,
            detail=f"Away team '{req.away_team}' not found in WC model.",
        )

    saadot = apply_match_adjustments(
        home_injury_pct=req.home_injury_pct,
        away_injury_pct=req.away_injury_pct,
        home_motivation_pct=req.home_motivation_pct,
        away_motivation_pct=req.away_motivation_pct,
        is_derby=req.is_derby,
    )

    lam, mu = dc.expected_goals(req.home_team, req.away_team, adjustments=saadot)
    p_1x2 = dc.predict_1x2(req.home_team, req.away_team, adjustments=saadot)
    p_ou = dc.predict_over_under(req.home_team, req.away_team, line=2.5, adjustments=saadot)
    p_btts = dc.predict_btts(req.home_team, req.away_team, adjustments=saadot)
    top = dc.todennakoisin_tulos(req.home_team, req.away_team, top_n=5, adjustments=saadot)

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
    )


# ---------------------------------------------------------------------------
# ENDPOINT: tyhjennä mallin välimuisti (debug-tarkoitukseen)
# ---------------------------------------------------------------------------
@app.post("/api/admin/clear-cache")
def clear_cache():
    """Tyhjennä mallin välimuisti — pakottaa uudelleen-sovituksen."""
    n = len(_MODEL_CACHE)
    _MODEL_CACHE.clear()
    return {"cleared_models": n}


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
