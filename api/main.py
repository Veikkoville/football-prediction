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

import json
import os
import sys
from pathlib import Path
from typing import Optional

# Lisää projektin juuri Python-polkuun jotta `src.*` -importit toimivat
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

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
            cancel_at_end = obj.get("cancel_at_period_end", False)
            period_end_ts = obj.get("current_period_end")  # unix timestamp tai null
            period_end_iso = None
            if period_end_ts:
                from datetime import datetime, timezone
                period_end_iso = datetime.fromtimestamp(period_end_ts, tz=timezone.utc).isoformat()
            print(
                f"[Stripe webhook] subscription.updated user_id={user_id} "
                f"cancel_at_period_end={cancel_at_end} period_end={period_end_iso}"
            )
            _update_profile(user_id, {
                "subscription_cancel_at_period_end": cancel_at_end,
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
