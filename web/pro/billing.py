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
    import json as _json

    try:
        # HUOM: stripe v15:n resurssiobjektit eivät käyttäydy dictinä
        # (.get()/dict() kaatuvat) → parsi raaka-JSONiksi (__str__ = JSON),
        # sama tekniikka kuin backendin mobiiliwebhookissa.
        session = _json.loads(str(stripe.checkout.Session.retrieve(sid)))
    except Exception as e:
        st.error(f"Could not verify payment: {e}")
        return
    if session.get("payment_status") != "paid":
        st.warning("Payment not completed.")
        return
    metadata = session.get("metadata") or {}
    uid = (session.get("client_reference_id")
           or metadata.get("user_id")
           or (user or {}).get("id"))
    if not uid:
        st.error("Paid session without user reference — contact support.")
        return
    plan = metadata.get("plan", "season")
    sub_field = session.get("subscription")
    stripe_sub = (sub_field.get("id") if isinstance(sub_field, dict)
                  else sub_field)
    period_end = None
    if stripe_sub:
        # Molemmat planit ovat recurring-subscriptioneita (kausi = yearly).
        try:
            sub = _json.loads(str(stripe.Subscription.retrieve(stripe_sub)))
            # Uusissa Stripe-API-versioissa current_period_end siirtyi
            # itemeille -> lue top-level TAI items.data[0].
            items = (sub.get("items") or {}).get("data") or [{}]
            ts = sub.get("current_period_end") or items[0].get("current_period_end")
            if ts:
                period_end = _dt.datetime.fromtimestamp(
                    ts, _dt.timezone.utc).isoformat()
        except Exception:
            period_end = None
    if period_end is None:
        # Defensiivinen fallback (esim. period-kenttä puuttuu API-versiosta)
        period_end = _season_end_iso()
    cust_field = session.get("customer")
    customer_id = (cust_field.get("id") if isinstance(cust_field, dict)
                   else cust_field)
    if upsert_subscription(uid, plan, "active", period_end,
                           customer_id, stripe_sub):
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
