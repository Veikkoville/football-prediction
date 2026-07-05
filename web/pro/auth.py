"""GoalIQ Pro — Supabase-auth + subscription-status.

Sama Supabase-projekti kuin mobiili (auth uudelleenkäyttö: sama tili toimii
webissä ja appissa). Web-tilaukset elävät OMASSA `web_subscriptions`-taulussa
(sql/web_subscriptions.sql) — ei kosketa mobiilin profiles/RevenueCat-polkuun.

Secretit (EI koskaan koodiin — .env / hostin secret-dashboard):
  SUPABASE_URL, SUPABASE_ANON_KEY  — auth-kirjautuminen (selainturvallinen taso)
  SUPABASE_SERVICE_KEY             — subscription-upsert (vain palvelinpuoli)

Ilman secreteja: is_configured()=False → UI näyttää config-ohjeen, free-osa
toimii normaalisti (julkinen API).
"""
from __future__ import annotations

import os

import streamlit as st

try:
    from supabase import Client, create_client
except ImportError:  # pragma: no cover - requirements asentaa
    create_client = None
    Client = None


def _env(name: str) -> str | None:
    # Streamlit Cloud käyttää st.secrets; Render/lokaali .env/ympäristö.
    try:
        if name in st.secrets:
            return st.secrets[name]
    except Exception:
        pass
    return os.environ.get(name)


def is_configured() -> bool:
    return bool(create_client and _env("SUPABASE_URL") and _env("SUPABASE_ANON_KEY"))


@st.cache_resource
def _client() -> "Client":
    return create_client(_env("SUPABASE_URL"), _env("SUPABASE_ANON_KEY"))


@st.cache_resource
def _service_client() -> "Client | None":
    # Sama env-nimi kuin backendin Renderissä (SUPABASE_SERVICE_ROLE_KEY);
    # SUPABASE_SERVICE_KEY hyväksytään aliaksena.
    key = _env("SUPABASE_SERVICE_ROLE_KEY") or _env("SUPABASE_SERVICE_KEY")
    if not key:
        return None
    return create_client(_env("SUPABASE_URL"), key)


# ---------------------------------------------------------------------------
# Sessio
# ---------------------------------------------------------------------------
def current_user() -> dict | None:
    """{id, email} tai None. Sessio elää st.session_state:ssa."""
    return st.session_state.get("giq_user")


def sign_out() -> None:
    st.session_state.pop("giq_user", None)
    st.session_state.pop("giq_sub", None)


def login_box() -> None:
    """Email+salasana-kirjautuminen (sama tili kuin mobiilissa) + rekisteröinti."""
    tab_in, tab_up = st.tabs(["Sign in", "Create account"])
    with tab_in:
        with st.form("signin"):
            email = st.text_input("Email", key="si_email")
            pw = st.text_input("Password", type="password", key="si_pw")
            if st.form_submit_button("Sign in", type="primary"):
                _do_auth("sign_in", email, pw)
    with tab_up:
        st.caption("One GoalIQ account works in the app and on the web.")
        with st.form("signup"):
            email = st.text_input("Email", key="su_email")
            pw = st.text_input("Password (min 6 chars)", type="password", key="su_pw")
            if st.form_submit_button("Create account"):
                _do_auth("sign_up", email, pw)


def _do_auth(mode: str, email: str, pw: str) -> None:
    if not email or not pw:
        st.error("Email and password required.")
        return
    try:
        sb = _client()
        if mode == "sign_in":
            res = sb.auth.sign_in_with_password({"email": email, "password": pw})
        else:
            res = sb.auth.sign_up({"email": email, "password": pw})
        user = getattr(res, "user", None)
        if user is None:
            st.error("Authentication failed.")
            return
        st.session_state["giq_user"] = {"id": user.id, "email": user.email}
        st.session_state.pop("giq_sub", None)
        st.rerun()
    except Exception as e:
        st.error(f"Authentication failed: {e}")


# ---------------------------------------------------------------------------
# Subscription-status (web_subscriptions-taulu)
# ---------------------------------------------------------------------------
def subscription(user_id: str) -> dict | None:
    """Aktiivinen premium tai None. Kevyt session-cache.

    Cross-platform (#7): web_subscriptions TAI profiles.is_premium —
    mobiilitilaaja (RC/Play/App Store asettaa profiles.is_premium) saa
    web-premiumin ilman uutta ostoa, ja toisinpäin.
    """
    cached = st.session_state.get("giq_sub")
    if cached is not None:
        return cached or None
    sb = _service_client() or _client()
    sub = None
    try:
        rows = (
            sb.table("web_subscriptions")
            .select("status, plan, current_period_end")
            .eq("user_id", user_id)
            .eq("status", "active")
            .order("current_period_end", desc=True)
            .limit(1)
            .execute()
        )
        sub = rows.data[0] if rows.data else None
    except Exception:
        sub = None
    if sub is None:
        try:
            prof = (
                sb.table("profiles")
                .select("is_premium")
                .eq("id", user_id)
                .limit(1)
                .execute()
            )
            if prof.data and prof.data[0].get("is_premium"):
                sub = {"status": "active", "plan": "app",
                       "current_period_end": None}
        except Exception:
            pass
    st.session_state["giq_sub"] = sub or False
    return sub


def upsert_subscription(user_id: str, plan: str, status: str,
                        period_end: str | None,
                        stripe_customer: str | None,
                        stripe_subscription: str | None) -> bool:
    """Merkitse tilaus Supabaseen (redirect-verify-polku; webhook tekee saman
    palvelinpäässä). Vaatii SERVICE-avaimen (RLS estää client-kirjoituksen)."""
    sb = _service_client()
    if sb is None:
        return False
    try:
        sb.table("web_subscriptions").upsert(
            {
                "user_id": user_id,
                "plan": plan,
                "status": status,
                "current_period_end": period_end,
                "stripe_customer_id": stripe_customer,
                "stripe_subscription_id": stripe_subscription,
            },
            on_conflict="user_id",
        ).execute()
        # Cross-platform (#7): web-tilaus avaa myös mobiiliappin premiumin
        # (appi gateaa profiles.is_premium-kentällä). Sama kirjoitus tapahtuu
        # myös backend-webhookissa — idempotentti.
        if status == "active":
            try:
                pf = {"is_premium": True,
                      "subscription_cancel_at_period_end": False}
                if period_end:
                    pf["subscription_current_period_end"] = period_end
                sb.table("profiles").update(pf).eq("id", user_id).execute()
            except Exception:
                pass  # webhook varmistaa; ei kaadeta ostoflowta tähän
        st.session_state.pop("giq_sub", None)
        return True
    except Exception as e:
        st.error(f"Subscription update failed: {e}")
        return False
