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

import pandas as pd
import streamlit as st

import auth
import billing
from data import fetch_accuracy, fetch_fantasy, fetch_xp

st.set_page_config(page_title="GoalIQ Pro — FPL tools", page_icon="⚽",
                   layout="wide")

MAGENTA = "#FF2E7E"
FDR_COLORS = {1: "#00C48C", 2: "#00B8B8", 3: "#F4A800", 4: "#FF6B5E", 5: "#D6006E"}

DISCLAIMER = ("GoalIQ model expected points — a model prediction, not betting "
              "advice, and not a gambling service.")


# ---------------------------------------------------------------------------
# Header + auth-tila
# ---------------------------------------------------------------------------
def header() -> None:
    left, right = st.columns([3, 1])
    with left:
        st.markdown(f"## Goal<span style='color:{MAGENTA}'>IQ</span> Pro",
                    unsafe_allow_html=True)
        st.caption("Fantasy Premier League tools from the GoalIQ match model · "
                   "[goaliq.app](https://goaliq.app)")
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
        st.info("Projections go live before Gameweek 1 — check back soon.")
        return

    acc = fetch_accuracy()
    agg = acc.get("aggregate", acc) if isinstance(acc, dict) else {}
    n = agg.get("n_1x2") or agg.get("n") or None
    pct = agg.get("accuracy_1x2_pct") or agg.get("accuracy_pct") or None
    if n and pct:
        st.success(f"Track record: {pct:.1f} % correct 1X2 across {n} "
                   f"pre-match-logged predictions · "
                   f"[methodology](https://goaliq.app/fpl.html#track-record)")

    st.markdown(f"### Clean sheet outlook — next {meta.get('horizon_gw', 6)} gameweeks")
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
def premium_views() -> None:
    data = fetch_xp()
    meta = data.get("meta", {})
    if not meta.get("available"):
        st.info("xP projections go live before Gameweek 1.")
        return
    players = data.get("players", [])
    next_gw = meta.get("next_gameweek")

    st.markdown("### Captain ranker — top xP for the next gameweek")
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

    st.markdown(f"### Player expected points — next {meta.get('horizon_gw', 6)} gameweeks")
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
    st.caption("Per-gameweek xP columns = the per-GW breakdown. Component split "
               "(goals/CS/defcon) lands when the backend ships it. "
               "Differentials (xP vs ownership) come in Phase 2.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
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
                       "(missing Supabase secrets — see README).")
            st.markdown(f"*{DISCLAIMER}*")
            return
        user = auth.current_user()
        if not user:
            st.markdown("#### Sign in to continue")
            st.caption("Expected points (xP) is part of GoalIQ Pro. "
                       "Sign in or create an account first.")
            auth.login_box()
        else:
            sub = auth.subscription(user["id"])
            if sub:
                plan = sub.get("plan", "")
                st.caption(f"GoalIQ Pro active ({plan}) · thank you for the support!")
                premium_views()
            elif billing_ready:
                billing.upgrade_box(user)
            else:
                st.warning("Checkout is not configured yet in this environment "
                           "(missing Stripe secrets — see README).")

    st.divider()
    st.caption(f"{DISCLAIMER} · [Privacy](https://goaliq.app/privacy.html) · "
               f"[FAQ](https://goaliq.app/faq.html) · Built by an independent "
               f"developer in Finland.")


main()
