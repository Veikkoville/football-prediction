"""GoalIQ Pro — PostHog-instrumentointi (web-funnel, QUEUE #12).

Server-side capture PostHogin Python-SDK:lla SAMAAN projektiin (427890)
kuin mobiili → yksi yhtenäinen funnel, jaettavissa `platform`-propilla
(web vs mobiili). Eventtinimet = mobiilin nimet (paywall_shown,
upgrade_tapped, signup_completed, purchase_completed) + web-spesifi
pro_page_viewed.

Kestävyys:
  - SAFE NO-OP: jos POSTHOG_API_KEY puuttuu tai SDK ei importtaudu →
    kaikki kutsut palaavat hiljaa (sama kuvio kuin webhookin
    "not configured"). Virhe capturessa ei koskaan kaada appia.
  - EI tuplafirausta Streamlit-rerunissa: once_key-guard
    st.session_stateen (event kerran per sessio/toiminto).
  - EI PII:tä eventteihin: distinct_id = Supabase user id (sama kuin
    mobiilissa → cross-platform-käyttäjä yhdistyy) tai anonyymi
    sessio-uuid; email vain identify-person-propiksi (mobiilin tapa).
  - Anon → user: alias kirjautumisessa, jotta pre-login pro_page_viewed
    liittyy samaan käyttäjään.

Env (Render goaliq-pro-web): POSTHOG_API_KEY (projektin write-key phc_…)
+ POSTHOG_HOST (oletus https://us.i.posthog.com — projekti on US Cloud;
varmista host avainta lisätessä, väärä region hukkaa eventit hiljaa).
"""
from __future__ import annotations

import os
import uuid

import streamlit as st

try:
    import posthog as _posthog
except ImportError:  # pragma: no cover - requirements asentaa
    _posthog = None

_SUPER_PROPS = {"platform": "web", "surface": "pro"}


def _env(name: str) -> str | None:
    try:
        if name in st.secrets:
            return st.secrets[name]
    except Exception:
        pass
    return os.environ.get(name)


@st.cache_resource
def _client():
    """PostHog-client tai None (no-op). cache_resource = yksi per prosessi."""
    key = _env("POSTHOG_API_KEY")
    if not (_posthog and key):
        return None
    try:
        return _posthog.Posthog(
            project_api_key=key,
            host=_env("POSTHOG_HOST") or "https://us.i.posthog.com",
        )
    except Exception:
        return None


def is_configured() -> bool:
    return _client() is not None


def distinct_id() -> str:
    """Kirjautunut = Supabase user id (yhdistyy mobiiliin); muuten
    sessio-anonyymi uuid (luodaan kerran per Streamlit-sessio)."""
    user = st.session_state.get("giq_user")
    if user and user.get("id"):
        return user["id"]
    if "ph_anon_id" not in st.session_state:
        st.session_state["ph_anon_id"] = f"web-anon-{uuid.uuid4()}"
    return st.session_state["ph_anon_id"]


def capture(event: str, props: dict | None = None,
            once_key: str | None = None) -> None:
    """Fire event. once_key → kerran per Streamlit-sessio (rerun-guard)."""
    if once_key:
        flag = f"ph_once_{once_key}"
        if st.session_state.get(flag):
            return
        st.session_state[flag] = True
    ph = _client()
    if ph is None:
        return
    try:
        ph.capture(distinct_id=distinct_id(), event=event,
                   properties={**_SUPER_PROPS, **(props or {})})
    except Exception:
        pass  # analytiikka ei koskaan kaada appia


def identify_user(user_id: str, email: str | None) -> None:
    """Kirjautumisen jälkeen: alias anon→user (pre-login-eventit yhdistyvät)
    + email person-propiksi (sama kuin mobiili). Kerran per sessio."""
    if st.session_state.get("ph_identified"):
        return
    st.session_state["ph_identified"] = True
    ph = _client()
    if ph is None:
        return
    try:
        anon = st.session_state.get("ph_anon_id")
        if anon:
            ph.alias(previous_id=anon, distinct_id=user_id)
        if email:
            ph.capture(distinct_id=user_id, event="$identify",
                       properties={"$set": {"email": email}, **_SUPER_PROPS})
    except Exception:
        pass
