"""GoalIQ Pro — Stripe Checkout (web-billing, ohittaa store-cutin).

Kaksi polkua tilauksen aktivointiin:
  1. ENSISIJAINEN (tuotanto): Stripe-webhook → backendin /api/webhook/stripe-web
     → upsert web_subscriptions (koodi api/main.py:ssä, deploy = Villen GO).
  2. FALLBACK + TEST-MODE: success_url?session_id=... → tämä moduuli verifioi
     sessionin suoraan Stripe-API:sta ja upserttaa — e2e toimii ilman
     deployattua webhookkia (Stripe-testiavaimilla).

Secretit: STRIPE_SECRET_KEY (sk_test_... test-modessa), hinnat
STRIPE_PRICE_MONTHLY_ID + STRIPE_PRICE_SEASON_ID, APP_BASE_URL (redirectit).
"""
from __future__ import annotations

import datetime as _dt
import os

import streamlit as st

try:
    import stripe
except ImportError:  # pragma: no cover
    stripe = None

from auth import upsert_subscription

PLANS = {
    # UI-oletus = kausi. Villen päätös 5.7 (tarkennettu): 25 €/vuosi VUOSITTAIN
    # UUSIUTUVA subscription (ei one-time) — Stripe-hinta luotu recurring-
    # yearlyna (ks. STRIPE_SUPABASE_CONFIG.md). MOLEMMAT mode='subscription'.
    "season": {"label": "Season pass — 25 €/year", "env": "STRIPE_PRICE_SEASON_ID",
               "mode": "subscription"},
    "monthly": {"label": "Monthly — 3.99 €/mo", "env": "STRIPE_PRICE_MONTHLY_ID",
                "mode": "subscription"},
}


def _env(name: str) -> str | None:
    try:
        if name in st.secrets:
            return st.secrets[name]
    except Exception:
        pass
    return os.environ.get(name)


def is_configured() -> bool:
    return bool(stripe and _env("STRIPE_SECRET_KEY")
                and _env("STRIPE_PRICE_SEASON_ID") and _env("STRIPE_PRICE_MONTHLY_ID"))


def _base_url() -> str:
    return (_env("APP_BASE_URL") or "http://localhost:8501").rstrip("/")


def checkout_url(user: dict, plan: str) -> str | None:
    """Luo Stripe Checkout -session ja palauta URL (test/live avaimen mukaan)."""
    stripe.api_key = _env("STRIPE_SECRET_KEY")
    cfg = PLANS[plan]
    try:
        session = stripe.checkout.Session.create(
            mode=cfg["mode"],
            line_items=[{"price": _env(cfg["env"]), "quantity": 1}],
            customer_email=user["email"],
            client_reference_id=user["id"],
            metadata={"user_id": user["id"], "plan": plan, "source": "pro-web"},
            success_url=f"{_base_url()}/?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{_base_url()}/?checkout=cancelled",
            allow_promotion_codes=True,
        )
        return session.url
    except Exception as e:
        st.error(f"Checkout failed: {e}")
        return None


def _season_end_iso() -> str:
    """Kausipassin voimassaolo: kauden loppu (30.6.) ostohetkestä eteenpäin."""
    today = _dt.date.today()
    year = today.year + 1 if today.month >= 7 else today.year
    return f"{year}-06-30T23:59:59+00:00"


def handle_success_redirect() -> None:
    """?session_id=... → verifioi Stripestä → merkitse tilaus aktiiviseksi.
    Idempotentti: upsert per user_id; webhook kirjoittaa saman tiedon."""
    sid = st.query_params.get("session_id")
    if not sid or not is_configured():
        return
    user = st.session_state.get("giq_user")
    stripe.api_key = _env("STRIPE_SECRET_KEY")
    try:
        session = stripe.checkout.Session.retrieve(sid)
    except Exception as e:
        st.error(f"Could not verify payment: {e}")
        return
    if session.get("payment_status") != "paid":
        st.warning("Payment not completed.")
        return
    uid = (session.get("client_reference_id")
           or (session.get("metadata") or {}).get("user_id")
           or (user or {}).get("id"))
    if not uid:
        st.error("Paid session without user reference — contact support.")
        return
    plan = (session.get("metadata") or {}).get("plan", "season")
    stripe_sub = session.get("subscription")
    if stripe_sub:
        # Molemmat planit ovat recurring-subscriptioneita (kausi = yearly).
        sub = stripe.Subscription.retrieve(stripe_sub)
        period_end = _dt.datetime.fromtimestamp(
            sub["current_period_end"], _dt.timezone.utc).isoformat()
    else:
        # Defensiivinen fallback (ei pitäisi tapahtua subscription-modessa)
        period_end = _season_end_iso()
    if upsert_subscription(uid, plan, "active", period_end,
                           session.get("customer"), stripe_sub):
        st.query_params.clear()
        st.success("Premium active — welcome aboard!")
        st.balloons()


def upgrade_box(user: dict) -> None:
    """Paywall-CTA: kausi oletuksena, kuukausi rinnalla."""
    st.markdown("#### Unlock GoalIQ Pro")
    st.caption("Player expected points (xP), captain ranker and per-gameweek "
               "breakdowns. Season pass renews yearly, monthly renews monthly — "
               "cancel anytime.")
    c1, c2 = st.columns(2)
    for col, plan in ((c1, "season"), (c2, "monthly")):
        with col:
            primary = plan == "season"
            if st.button(PLANS[plan]["label"], type="primary" if primary else "secondary",
                         use_container_width=True, key=f"buy_{plan}"):
                url = checkout_url(user, plan)
                if url:
                    st.link_button("Continue to secure checkout →", url,
                                   use_container_width=True)
