"""GoalIQ Pro — FPL-dashboard (pro.goaliq.app), web-v1 fast-path.

Free:    GW clean sheet -% -taulu + FDR-grid + track record -proof (/api/fantasy).
Premium: xP-pelaajalista (lajiteltava, positiosuodatin, per-GW-erittely) +
         kapteeni-ranker (/api/fantasy/xp). Gate: Supabase-auth +
         web_subscriptions-status; osto Stripe Checkoutilla (billing.py).

Rehellisyys + IP: "GoalIQ model expected points", EI "beats FPL"; disclaimer
"model prediction, not betting advice, not a gambling service"; tekstipohjainen
(ei seurakrestejä), ei betting/odds/Kelly-näkymiä (puhdas FPL, päätös 5.7).

Ajo lokaalisti: streamlit run web/pro/app.py  (ilman secreteja free-osa toimii,
auth/billing näyttää config-ohjeen — ks. README.md + .env.example).
"""
from __future__ import annotations

import base64
from pathlib import Path

import envload

envload.load()  # lokaali .env -> os.environ ENNEN auth/billing-importteja

import pandas as pd
import streamlit as st

import analytics
import auth
import billing
from data import fetch_accuracy, fetch_fantasy, fetch_xp

_APP_DIR = Path(__file__).parent
_ICON_PATH = _APP_DIR / "assets" / "goaliq-appicon-192.png"

st.set_page_config(page_title="GoalIQ Pro | FPL tools",
                   page_icon=str(_ICON_PATH) if _ICON_PATH.exists() else "⚽",
                   layout="wide")

# Brändipaletti (goaliq-app/assets/brand/brand-tokens.md — TÄSMÄHEXIT)
MAGENTA = "#FF2E7E"
MAGENTA_DEEP = "#D6006E"
INK = "#0A0820"
INK2 = "#140F1E"
CREAM = "#FFF6EC"
TEAL = "#19E3D2"
TEAL_DEEP = "#00C2AD"
GOLD_DEEP = "#F4A800"
CORAL = "#FF6A3D"
# FDR 1-5 brändiasteikko Teal → Gold → Coral → MagentaDeep (sama kuin fpl.html)
FDR_COLORS = {1: TEAL_DEEP, 2: TEAL, 3: GOLD_DEEP, 4: CORAL, 5: MAGENTA_DEEP}

DISCLAIMER = ("GoalIQ model expected points: a model prediction, not betting "
              "advice, and not a gambling service.")

# Brändi-CSS (#10): Space Grotesk -otsikot, magenta-aksentit, Ink-hero,
# Streamlitin deploy-toolbarin piilotus tuotantopinnasta.
_BRAND_CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;700&display=swap');
html, body, [data-testid="stAppViewContainer"] * {{
  font-family: 'Space Grotesk', -apple-system, 'Segoe UI', sans-serif;
}}
[data-testid="stToolbar"] {{ visibility: hidden; }}
h1, h2, h3 {{ letter-spacing: -0.4px; }}
.giq-hero {{
  background: linear-gradient(165deg, {INK2}, {INK});
  border: 1px solid {MAGENTA}33;
  border-radius: 16px;
  padding: 18px 22px 14px;
  margin-bottom: 6px;
}}
.giq-hero .brand {{ display: flex; align-items: center; gap: 12px; }}
.giq-hero img {{ width: 44px; height: 44px; border-radius: 11px; display: block; }}
.giq-hero .word {{ font-size: 28px; font-weight: 700; color: {CREAM}; line-height: 1; }}
.giq-hero .word span {{ color: {MAGENTA}; }}
.giq-hero .tag {{ color: #C9C3DA; font-size: 13px; margin-top: 6px; }}
.giq-hero a {{ color: {TEAL}; text-decoration: none; }}
[data-testid="stButton"] button[kind="primary"] {{
  background: {MAGENTA}; border: none; border-radius: 24px; font-weight: 700;
}}
[data-testid="stButton"] button[kind="primary"]:hover {{ background: {MAGENTA_DEEP}; }}
[data-testid="stButton"] button[kind="secondary"] {{
  border: 2px solid {MAGENTA}; border-radius: 24px; font-weight: 700;
}}
[data-baseweb="tab-highlight"] {{ background-color: {MAGENTA}; }}
</style>
"""


def _icon_b64() -> str | None:
    try:
        return base64.b64encode(_ICON_PATH.read_bytes()).decode()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Header + auth-tila
# ---------------------------------------------------------------------------
def header() -> None:
    st.markdown(_BRAND_CSS, unsafe_allow_html=True)
    left, right = st.columns([3, 1])
    with left:
        icon = _icon_b64()
        icon_html = (f'<img src="data:image/png;base64,{icon}" alt="">'
                     if icon else "")
        st.markdown(
            f'<div class="giq-hero"><div class="brand">{icon_html}'
            f'<div class="word">Goal<span>IQ</span> Pro</div></div>'
            f'<div class="tag">Fantasy Premier League tools from the GoalIQ '
            f'match model · <a href="https://goaliq.app">goaliq.app</a></div></div>',
            unsafe_allow_html=True,
        )
    with right:
        user = auth.current_user()
        if user:
            st.caption(f"Signed in: {user['email']}")
            if st.button("Sign out", use_container_width=True):
                auth.sign_out()
                st.rerun()


# ---------------------------------------------------------------------------
# Free: CS% + FDR + track record
# ---------------------------------------------------------------------------
def free_views() -> None:
    data = fetch_fantasy()
    meta = data.get("meta", {})
    if not meta.get("available"):
        st.info("Projections go live before Gameweek 1. Check back soon.")
        return

    acc = fetch_accuracy()
    all_time = acc.get("all_time") or {}
    n = all_time.get("n")
    pct = all_time.get("pct_1x2")
    if n and pct:
        st.success(f"Track record: {pct * 100:.1f} % correct 1X2 across {n} "
                   f"pre-match-logged predictions · "
                   f"[methodology](https://goaliq.app/fpl.html#track-record)")

    st.markdown(f"### Clean sheet outlook, next {meta.get('horizon_gw', 6)} gameweeks")
    st.caption("Free · P(clean sheet) from the GoalIQ Dixon-Coles match engine. "
               "Model-based fixture difficulty (FDR) 1 = easiest, 5 = hardest.")

    teams = data.get("teams", [])
    rows = []
    for t in teams:
        row = {"Team": t["name"], "Avg CS%": t["next_avg_cs_pct"],
               "Avg FDR": t["next_avg_fdr"]}
        for f in t.get("fixtures", []):
            row[f"GW{f['gw']}"] = f"{f['opponent_short']} ({f['venue']}) {f['fdr']}"
        rows.append(row)
    df = pd.DataFrame(rows)

    def _fdr_style(val: object) -> str:
        s = str(val)
        if s and s[-1].isdigit():
            c = FDR_COLORS.get(int(s[-1]), "")
            return f"background-color: {c}22; color: inherit"
        return ""

    gw_cols = [c for c in df.columns if c.startswith("GW")]
    st.dataframe(
        df.style.map(_fdr_style, subset=gw_cols)
          .format({"Avg CS%": "{:.1f}", "Avg FDR": "{:.2f}"}),
        use_container_width=True, hide_index=True, height=740,
    )


# ---------------------------------------------------------------------------
# Premium: xP-lista + kapteeni-ranker
# ---------------------------------------------------------------------------
# #13: labelit = mobiilin XpComponentSplit-pariteetti (goaliq-app lib/i18n/en.ts)
_COMPONENT_LABELS = {
    "appearance": "Appearance", "goals": "Goals", "assists": "Assists",
    "clean_sheet": "Clean sheet", "conceded": "Conceded", "saves": "Saves",
    "defensive_contribution": "Def. contribution", "yellows": "Cards",
    "bonus": "Bonus",
}


def _component_breakdown(p: dict) -> None:
    """Headline-GW:n xP-komponenttisplit yhdelle pelaajalle (#13).

    Sama esitysjärjestys kuin mobiilin XpComponentSplit: nollasta poikkeavat
    suurin ensin. Bar skaalataan suurimpaan positiiviseen komponenttiin;
    negatiiviset (conceded/cards) näytetään ilman baria coral-arvolla.
    """
    comps = p.get("components") or {}
    parts = [(k, float(v)) for k, v in comps.items()
             if isinstance(v, (int, float)) and abs(float(v)) >= 0.005]
    parts.sort(key=lambda kv: -kv[1])
    if not parts:
        st.caption("No component breakdown available for this player.")
        return
    # GW total = taulukon virallinen per-GW-xp (komponenttien 2 desim
    # pyöristyssumma voi heittää ±0.01 siitä — ei näytetä kahta eri lukua).
    comp_gw = p.get("components_gw")
    gw_xp = next((g["xp"] for g in p.get("gameweeks", [])
                  if g.get("gw") == comp_gw), None)
    if gw_xp is None:
        gw_xp = sum(v for _, v in parts)
    max_pos = max((v for _, v in parts if v > 0), default=1.0)
    rows = []
    for key, val in parts:
        label = _COMPONENT_LABELS.get(key, key.replace("_", " ").title())
        width = max(round(val / max_pos * 100), 2) if val > 0 else 0
        share = f" · {val / gw_xp:.0%}" if gw_xp > 0 and val > 0 else ""
        color = TEAL_DEEP if val > 0 else CORAL
        rows.append(
            f'<div style="display:flex;align-items:center;gap:10px;'
            f'margin:3px 0;font-size:14px;">'
            f'<span style="width:150px;flex:none;">{label}</span>'
            f'<div style="flex:1;background:{INK}14;border-radius:4px;'
            f'height:10px;"><div style="width:{width}%;background:{color};'
            f'border-radius:4px;height:10px;"></div></div>'
            f'<span style="width:110px;flex:none;text-align:right;'
            f'color:{color};font-weight:700;">{val:+.2f}{share}</span></div>')
    st.markdown(
        f'<div style="max-width:560px;">{"".join(rows)}'
        f'<div style="display:flex;justify-content:space-between;'
        f'max-width:560px;margin-top:6px;padding-top:6px;'
        f'border-top:1px solid {INK}22;font-size:14px;font-weight:700;">'
        f'<span>GW total</span><span>{gw_xp:.2f} xP</span></div></div>',
        unsafe_allow_html=True,
    )


def premium_views() -> None:
    data = fetch_xp()
    meta = data.get("meta", {})
    if not meta.get("available"):
        st.info("xP projections go live before Gameweek 1.")
        return
    players = data.get("players", [])
    next_gw = meta.get("next_gameweek")

    st.markdown("### Captain ranker: top xP for the next gameweek")
    cap = sorted(
        (p for p in players),
        key=lambda p: -next((g["xp"] for g in p["gameweeks"] if g["gw"] == next_gw), 0.0),
    )[:10]
    cap_rows = [{
        "#": i + 1, "Player": p["web_name"], "Team": p["team_short"],
        "Pos": p["pos"],
        f"GW{next_gw} xP": next((g["xp"] for g in p["gameweeks"] if g["gw"] == next_gw), 0.0),
        "Opponent": ", ".join(
            f"{o['opp']} ({o['venue']})"
            for g in p["gameweeks"] if g["gw"] == next_gw
            for o in g["opponents"]) or "Blank",
    } for i, p in enumerate(cap)]
    st.dataframe(pd.DataFrame(cap_rows), use_container_width=True, hide_index=True)

    st.markdown(f"### Player expected points, next {meta.get('horizon_gw', 6)} gameweeks")
    c1, c2 = st.columns([1, 2])
    with c1:
        pos = st.selectbox("Position", ["All", "GKP", "DEF", "MID", "FWD"])
    with c2:
        sort_by = st.radio("Sort by", ["Total xP (horizon)", "xP per GW", "Expected minutes"],
                           horizontal=True)

    pool = [p for p in players if pos == "All" or p["pos"] == pos]
    key = {"Total xP (horizon)": "xp_horizon_total", "xP per GW": "xp_per_gw",
           "Expected minutes": "xmins"}[sort_by]
    pool.sort(key=lambda p: -p[key])

    rows = []
    for i, p in enumerate(pool):
        row = {"#": i + 1, "Player": p["web_name"], "Team": p["team_short"],
               "Pos": p["pos"], "xMins": p["xmins"], "xP/GW": p["xp_per_gw"],
               "Total": p["xp_horizon_total"]}
        for g in p["gameweeks"]:
            row[f"GW{g['gw']}"] = g["xp"]
        rows.append(row)
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True,
                 height=700)

    # #13: komponenttierittely headline-GW:lle. Defensiivinen: renderöityy
    # vain kun backend tuo components-kentän — ilman sitä näkymä ennallaan.
    comp_pool = [p for p in pool if p.get("components")]
    if comp_pool:
        comp_gw = comp_pool[0].get("components_gw", next_gw)
        st.markdown(f"#### Where the GW{comp_gw} xP comes from")
        st.caption("GoalIQ model expected points, split by scoring component. "
                   "Defensive contribution is where the model finds edges "
                   "the eye test misses.")
        sel = st.selectbox(
            "Player", range(len(comp_pool)),
            format_func=lambda i: (f'{comp_pool[i]["web_name"]} '
                                   f'({comp_pool[i]["team_short"]}, '
                                   f'{comp_pool[i]["pos"]})'),
            key="xp_component_player",
        )
        _component_breakdown(comp_pool[sel])
        st.caption("Per-gameweek xP columns above = the per-GW breakdown. "
                   "Differentials (xP vs ownership) come in Phase 2.")
    else:
        st.caption("Per-gameweek xP columns = the per-GW breakdown. Component "
                   "split (goals/CS/defcon) lands when the backend ships it. "
                   "Differentials (xP vs ownership) come in Phase 2.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    # Web-funnel (#12): sivulataus kerran per sessio
    analytics.capture("pro_page_viewed", once_key="page_viewed")
    header()
    billing_ready = billing.is_configured()
    auth_ready = auth.is_configured()

    if billing_ready and auth_ready:
        billing.handle_success_redirect()

    tab_free, tab_pro = st.tabs(["Clean sheets & FDR (free)", "Expected points (Pro)"])

    with tab_free:
        free_views()

    with tab_pro:
        if not auth_ready:
            st.warning("Sign-in is not configured yet in this environment "
                       "(missing Supabase secrets, see README).")
            st.markdown(f"*{DISCLAIMER}*")
            return
        user = auth.current_user()
        if not user:
            st.markdown("#### Sign in to continue")
            st.caption("Expected points (xP) is part of GoalIQ Pro. "
                       "Sign in or create an account first. Already subscribed "
                       "in the GoalIQ app? Sign in with the same account and "
                       "Pro is already active here.")
            auth.login_box()
        else:
            sub = auth.subscription(user["id"])
            if sub:
                plan = sub.get("plan", "")
                if plan == "app":
                    # Cross-platform-comms (#8): premium tuli appista
                    st.success("Your GoalIQ app subscription is active here too. Welcome.")
                else:
                    st.caption(f"GoalIQ Pro active ({plan}) · thank you for the support!")
                premium_views()
            elif billing_ready:
                billing.upgrade_box(user)
            else:
                st.warning("Checkout is not configured yet in this environment "
                           "(missing Stripe secrets, see README).")

    st.divider()
    st.caption(f"One account, premium on web, iOS and Android. · {DISCLAIMER} · "
               f"[Privacy](https://goaliq.app/privacy.html) · "
               f"[FAQ](https://goaliq.app/faq.html) · Built by an independent "
               f"developer in Finland.")


main()
