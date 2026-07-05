"""GoalIQ Pro — datakerros: LIVE-API:n luku (EI mallikoodia, vain HTTP-JSON).

Lähteet (sama julkinen backend kuin mobiili):
  - /api/fantasy     — Phase 0: CS% + FDR (free-näkymät)
  - /api/fantasy/xp  — Phase 1: xP per pelaaja/GW (premium-näkymät)
  - /api/accuracy    — julkinen track record (proof-elementti)

st.cache_data(ttl=15 min): data päivittyy viikkotasolla → cache poistaa
Render-cold-startin näkyvyyden toistokäytössä.
"""
from __future__ import annotations

import requests
import streamlit as st

API_BASE = "https://goaliq-api.onrender.com"
_TIMEOUT = 30


def _get(path: str) -> dict:
    r = requests.get(f"{API_BASE}{path}", timeout=_TIMEOUT,
                     headers={"User-Agent": "GoalIQ-Pro-Web/1.0"})
    r.raise_for_status()
    return r.json()


@st.cache_data(ttl=900, show_spinner="Loading fixtures…")
def fetch_fantasy() -> dict:
    return _get("/api/fantasy")


@st.cache_data(ttl=900, show_spinner="Loading expected points…")
def fetch_xp() -> dict:
    return _get("/api/fantasy/xp")


@st.cache_data(ttl=900, show_spinner=False)
def fetch_accuracy() -> dict:
    try:
        return _get("/api/accuracy")
    except Exception:
        return {}
