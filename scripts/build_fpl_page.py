"""
FPL-landing-sivun (fpl.html) bake-builderi - SEO + GEO (#SEO-runway, 4.7.2026).

Generoi KOKO staattisen fpl.html:n repossa olevasta datasta:
  - data/fpl_projections_phase0.json  (sama tiedosto jonka /api/fantasy servaa;
    builderi scripts/build_fpl_phase0.py, sanity-gaten takana)
  - data/accuracy.json                (sama jonka /api/accuracy servaa;
    accuracy-log.yml päivittää mainiin 3 h välein)

MIKSI staattinen bake eikä client-JS-fetch: crawlerit + AI-vastausmoottorit
(GPTBot, PerplexityBot, ClaudeBot) lukevat initial HTML:n - JS-renderöity data
jää usein indeksoimatta, ja GEO vaatii tekstiksi purettavat taulut.

STDLIB-ONLY (json, datetime, html, re, pathlib) - GH Actions -refresh
(fpl-page-refresh.yml) ajaa tämän ilman pip installia.


Fail-safe: jos FPL-data ei ole available tai sanity_gate != PASS → exit 2,
sivua EI kirjoiteta (vanha versio jää voimaan). Sama konventio kuin
build_fpl_phase0.py.

Päivittää myös sitemap.xml:n fpl.html-entryn <lastmod>-arvon.
EI auto-pushia: git-komennot tulostetaan (workflow hoitaa commitin).
"""

from __future__ import annotations

import datetime as _dt
import json
import re
import sys
from html import escape
from pathlib import Path

# #38: PostHog cookieless site-analytiikka (persistence=memory -> ei evasteita,
# ei consent-banneria; ei PII:ta). Sama projekti kuin appi + pro-web (427890);
# client-avain on julkinen by design (sama avain SPA-bundlessa).
POSTHOG_SNIPPET = """<!-- PostHog (#38): cookieless site-analytiikka - persistence=memory, ei evasteita, ei PII -->
<script>
!function(t,e){var o,n,p,r;e.__SV||(window.posthog=e,e._i=[],e.init=function(i,s,a){function g(t,e){var o=e.split(".");2==o.length&&(t=t[o[0]],e=o[1]),t[e]=function(){t.push([e].concat(Array.prototype.slice.call(arguments,0)))}}(p=t.createElement("script")).type="text/javascript",p.async=!0,p.src=s.api_host+"/static/array.js",(r=t.getElementsByTagName("script")[0]).parentNode.insertBefore(p,r);var u=e;for(void 0!==a?u=e[a]=[]:a="posthog",u.people=u.people||[],u.toString=function(t){var e="posthog";return"posthog"!==a&&(e+="."+a),t||(e+=" (stub)"),e},u.people.toString=function(){return u.toString(1)+".people (stub)"},o="capture identify alias people.set people.set_once set_config register register_once unregister opt_out_capturing has_opted_out_capturing opt_in_capturing reset isFeatureEnabled onFeatureFlags getFeatureFlag getFeatureFlagPayload reloadFeatureFlags group updateEarlyAccessFeatureEnrollment getEarlyAccessFeatures getActiveMatchingSurveys getSurveys onSessionId".split(" "),n=0;n<o.length;n++)g(u,o[n]);e._i.push([i,s,a])},e.__SV=1)}(document,window.posthog||[]);
posthog.init('phc_ASmq5P9R5goGTDxze3GkXHJqU6RsvMCNqunSVBMgGkn7',{api_host:'https://us.i.posthog.com',persistence:'memory',autocapture:false,person_profiles:'identified_only'});
posthog.register({platform:'web',source_app:'goaliq-static'});
posthog.capture('web_landing_viewed',{page:location.pathname});
</script>"""

# #56: Pro CTA -klikkimittaus (pro_cta_clicked, prop location) - delegoitu
# listener, ei blokkaa navigaatiota, ei PII:ta, cookieless-moodi ennallaan.
CTA_TRACK_SNIPPET = """<!-- #56: Pro CTA -klikkimittaus (PostHog pro_cta_clicked) - ei-blokkaava, ei PII, cookieless ennallaan -->
<script>
document.addEventListener('click', function (e) {
  var a = e.target && e.target.closest ? e.target.closest('a[data-cta]') : null;
  if (a && window.posthog) { posthog.capture('pro_cta_clicked', {location: a.getAttribute('data-cta')}); }
});
</script>"""


ROOT = Path(__file__).resolve().parent.parent
FPL_PATH = ROOT / "data" / "fpl_projections_phase0.json"
ACC_PATH = ROOT / "data" / "accuracy.json"
LOG_PATH = ROOT / "data" / "prediction_log.json"
OUT_PATH = ROOT / "fpl.html"
# #119b: sitemap.xml on nyt <sitemapindex> (core + predictions + fpl) —
# ydinsivujen entryt elävät sitemap-core.xml:ssä. Lapsi-sitemapit kirjoittavat
# build_prediction_pages.py ja build_fpl_longtail.py (write_urlset alla).
SITEMAP_PATH = ROOT / "sitemap-core.xml"

# #111: per-kilpailu-näyttönimet (accuracy.json by_competition -koodit).
# Tuntematon koodi renderöityy koodina — ei kaadu kun elokuun liigat tulevat.
COMP_NAMES = {
    "WC": "World Cup 2026",
    "BSA": "Brasileirão Série A",
    "PL": "Premier League",
    "PD": "La Liga",
    "BL1": "Bundesliga",
    "SA": "Serie A",
    "FL1": "Ligue 1",
    "CL": "Champions League",
}

# Custom domain (goaliq.app, Cloudflare, rekisteröity 4.7.2026). GitHub Pages
# servaa CNAME:n kautta juuresta → EI /football-prediction-polkuprefiksiä.
# Vanhat veikkoville.github.io/football-prediction/* -URLit redirectaavat.
BASE = "https://goaliq.app"
CANONICAL = f"{BASE}/fpl.html"
PLAY_URL = "https://play.google.com/store/apps/details?id=com.veikkoville.goaliq"
APPSTORE_URL = "https://apps.apple.com/app/id6780047163"
PRO_URL = "https://pro.goaliq.app"
# #101: selailu-CTA:t avaavat Premium-tabin suoraan (arvo-esikatselu + hinnat
# heti näkyviin); hinta-CTA:t vievät suoraan Stripe Checkoutiin (/checkout-
# reitti luo session heti, tili syntyy maksun jälkeen — ei pakko-sign-iniä).
PRO_TAB_URL = f"{PRO_URL}/?tab=premium"
PRO_CHECKOUT_SEASON_URL = f"{PRO_URL}/checkout?plan=season"
X_URL = "https://x.com/goaliqapp"
# #121-GEO: Villen vahvistamat somekanavat (22.7) entiteetti-disambiguaatioon -
# sameAs vain aitoihin kanaviin, ei keksittyjä URLeja.
TIKTOK_URL = "https://www.tiktok.com/@goaliqfpl"
IG_URL = "https://www.instagram.com/goaliqfpl/"
ORG_ID = BASE + "/#organization"
API_BASE = "https://goaliq-api.onrender.com"   # #85: accuracy-Datasetin distribution

# FDR-väriasteikko GoalIQ:n kanonisesta brändipaletista (brand-tokens.md,
# täsmähexit, EI approksimaatioita): 1 helpoin = Teal → Gold → Gold Deep →
# Coral → 5 vaikein = Magenta Deep. Tekstiväri kontrastin mukaan (1-4 ink,
# 5 valkoinen) - arvot CSS:ssä.
FDR_COLORS = {1: "#19E3D2", 2: "#FFC93C", 3: "#F4A800", 4: "#FF6A3D", 5: "#D6006E"}


# ---------------------------------------------------------------------------
# 1. Data
# ---------------------------------------------------------------------------
def load_data() -> tuple[dict, dict]:
    fpl = json.loads(FPL_PATH.read_text(encoding="utf-8"))
    acc = json.loads(ACC_PATH.read_text(encoding="utf-8"))
    meta = fpl.get("meta", {})
    if not meta.get("available", False):
        print("FAIL: FPL-data ei available - sivua ei kirjoiteta.")
        sys.exit(2)
    if meta.get("sanity_gate") != "PASS":
        print("FAIL: FPL sanity_gate != PASS - sivua ei kirjoiteta.")
        sys.exit(2)
    if not fpl.get("teams") or not fpl.get("fixtures"):
        print("FAIL: FPL-datasta puuttuu teams/fixtures - sivua ei kirjoiteta.")
        sys.exit(2)
    return fpl, acc


def fmt_pct(x: float, decimals: int = 1) -> str:
    return f"{x:.{decimals}f}".rstrip("0").rstrip(".") + "%"


def gw_date_label(fixtures: list[dict], gw: int) -> str:
    """Aikaisimman kickoffin päivämäärä, esim. 'Friday 21 August 2026'."""
    gws = [f for f in fixtures if f.get("gameweek") == gw and f.get("kickoff_ms")]
    if not gws:
        return ""
    first = min(gws, key=lambda f: f["kickoff_ms"])
    dt = _dt.datetime.fromtimestamp(first["kickoff_ms"] / 1000, tz=_dt.timezone.utc)
    return dt.strftime("%A %d %B %Y").replace(" 0", " ")


def build_context(fpl: dict, acc: dict) -> dict:
    meta = fpl["meta"]
    teams = fpl["teams"]
    fixtures = fpl["fixtures"]
    next_gw = meta.get("next_gameweek") or min(
        f["gameweek"] for f in fixtures if f.get("gameweek")
    )

    # CS-taulun rivit: per joukkue, next_gw:n fixture
    cs_rows = []
    for t in teams:
        fx = next((f for f in t["fixtures"] if f["gw"] == next_gw), None)
        if not fx:
            continue
        cs_rows.append(
            {
                "team": t["name"],
                "cs_pct": fx["cs_pct"],
                "opponent": fx["opponent"],
                "venue": fx["venue"],
                "fdr": fx["fdr"],
            }
        )
    cs_rows.sort(key=lambda r: r["cs_pct"], reverse=True)

    # FDR-gridin rivit: per joukkue, kaikki horisontin GW:t
    gws = sorted({f["gw"] for t in teams for f in t["fixtures"]})
    fdr_rows = []
    for t in teams:
        by_gw = {f["gw"]: f for f in t["fixtures"]}
        fdr_rows.append(
            {
                "team": t["name"],
                "cells": [by_gw.get(g) for g in gws],
                "avg_fdr": t["next_avg_fdr"],
                "avg_cs": t["next_avg_cs_pct"],
            }
        )
    fdr_rows.sort(key=lambda r: r["avg_fdr"])

    # Track record (/api/accuracy-datan peili)
    at = acc.get("all_time", {})
    n = at.get("n", 0)
    pct_1x2 = at.get("pct_1x2", 0.0) * 100
    dec_n = at.get("decisive_n", 0)
    dec_c = at.get("decisive_correct", 0)
    pct_dec = at.get("pct_decisive", 0.0) * 100
    logged = acc.get("logged_total", n)

    gen_dt = _dt.datetime.fromisoformat(meta["generated_at"])
    acc_dt = _dt.datetime.fromisoformat(acc["updated_at"])

    # #111: per-kilpailu-rivit (vain n > 0 — tyhjät off-season-liigat piiloon).
    # Järjestys: eniten gradattuja ensin → WC pysyy kärjessä kunnes domestic ohittaa.
    by_comp = [
        {
            "code": code,
            "name": COMP_NAMES.get(code, code),
            "n": m.get("n", 0),
            "correct": m.get("correct_1x2", 0),
            "pct": m.get("pct_1x2", 0.0) * 100,
        }
        for code, m in (acc.get("by_competition") or {}).items()
        if m.get("n", 0) > 0
    ]
    by_comp.sort(key=lambda r: r["n"], reverse=True)

    return {
        "season": meta.get("season", "2026/27"),
        "next_gw": next_gw,
        "gw_label": gw_date_label(fixtures, next_gw),
        "cs_rows": cs_rows,
        "fdr_rows": fdr_rows,
        "gws": gws,
        "top3": cs_rows[:3],
        "acc_n": n,
        "acc_pct_1x2": pct_1x2,
        "acc_dec_n": dec_n,
        "acc_dec_c": dec_c,
        "acc_pct_dec": pct_dec,
        "acc_logged": logged,
        "acc_pending": max(0, logged - n),
        "by_comp": by_comp,
        "data_date": gen_dt.strftime("%d %B %Y").lstrip("0"),
        "acc_date": acc_dt.strftime("%d %B %Y").lstrip("0"),
        "iso_date": max(gen_dt.date(), acc_dt.date()).isoformat(),
        "fixture_source": meta.get("fixture_source", "premierleague.com"),
    }


# ---------------------------------------------------------------------------
# 2. Sisältöpalat (copy + data → HTML ja plain-tekstiversiot GEO/JSON-LD:hen)
# ---------------------------------------------------------------------------
def venue_txt(v: str) -> str:
    return "home" if v == "H" else "away"


def track_record_sentences(c: dict) -> list[str]:
    """Sitaatinkelpoiset faktalauseet, käytetään sekä sivulla että FAQ:ssa."""
    return [
        (
            f"The GoalIQ model has logged {c['acc_logged']} pre-match predictions, "
            f"before kickoff, with no edits afterwards, starting with the 2026 "
            f"World Cup and now covering domestic leagues."
        ),
        (
            f"Across the {c['acc_n']} completed matches, the model called the "
            f"result correctly in {fmt_pct(c['acc_pct_1x2'])} of matches."
        ),
        (
            f"When the model named a clear winner rather than a draw, it was right "
            f"{fmt_pct(c['acc_pct_dec'])} of the time ({c['acc_dec_c']} of {c['acc_dec_n']})."
        ),
    ]


def build_faq(c: dict) -> list[tuple[str, str]]:
    """(kysymys, vastaus-plain) -parit. Sama teksti näkyvään FAQ:hun ja JSON-LD:hen."""
    top3 = c["top3"]
    top3_txt = "; ".join(
        f"{r['team']} at {fmt_pct(r['cs_pct'])} ({venue_txt(r['venue'])} against {r['opponent']})"
        for r in top3
    )
    tr = track_record_sentences(c)
    return [
        (
            f"Which teams are most likely to keep a clean sheet in Gameweek {c['next_gw']}?",
            (
                f"On GoalIQ's model the top clean sheet chances in Gameweek {c['next_gw']} "
                f"of the {c['season']} Premier League season are {top3_txt}. "
                f"These are pre-season projections and will sharpen once {c['season']} "
                f"results arrive."
            ),
        ),
        (
            "What is fixture difficulty rating (FDR)?",
            (
                "GoalIQ's fixture difficulty rating comes from the match model's win "
                "and clean sheet probabilities, on a 1 to 5 scale. A lower number is "
                "an easier fixture. It is model-derived and independent of the "
                "official FPL fixture difficulty."
            ),
        ),
        (
            "Is GoalIQ good for FPL?",
            (
                "Yes. GoalIQ is built FPL-first: clean sheet probability, fixture "
                "difficulty, rate my team with a captain pick, a fit checker "
                "that builds the best legal 15 around your must-have players, "
                "a pre-season draft rater (no team ID needed), and price watch "
                "are free, and GoalIQ Premium adds an interactive team manager "
                "with a gameweek planner, player expected points (xP), the "
                "captain ranker, a player value ranking, xG leaders, a DefCon "
                "tracker, differentials and transfer suggestions you can apply "
                "to your planned squad. Every number comes from a match model "
                "with a published, pre-match-logged track record."
            ),
        ),
        (
            "What FPL tools does GoalIQ have?",
            (
                "Free: clean sheet probabilities, fixture difficulty ratings "
                "(FDR), rate my team with a captain pick, a pre-season draft "
                "rater (pick 15, no team ID needed), the fit checker (lock "
                "must-have players, the model builds the best legal 15 around "
                "them), price watch, and the "
                "top three of the value, xG leaders and DefCon lists. GoalIQ "
                "Premium: an interactive team manager (formations, bench swaps, "
                "captaincy, a GW1 to GW6 gameweek planner with each player's "
                "opponent per week), player expected points (xP), the captain "
                "ranker, transfer suggestions with one-tap apply to your "
                "planned squad, player value (xP per million), full xG leaders "
                "and DefCon (defensive contribution) leaderboards, goalkeeper "
                "rotation pairs, differentials, player compare and predicted "
                "starting minutes. Available on the web, iOS and Android."
            ),
        ),
        (
            "What is DefCon in FPL and does GoalIQ track it?",
            (
                "DefCon (defensive contribution) is an FPL scoring rule: a "
                "defender earns 2 points with 10 combined clearances, blocks, "
                "interceptions and tackles in a match, and a midfielder or "
                "forward with 12 including ball recoveries. GoalIQ tracks "
                "every player's DefCon actions per game and hit rate, so you "
                "can find the most reliable DefCon point scorers. The top "
                "three are free and the full leaderboard is on GoalIQ Premium."
            ),
        ),
        (
            "Is GoalIQ free?",
            (
                "Yes. Clean sheet probability and fixture difficulty are free, on the web "
                "and in the GoalIQ app for Android and iOS."
            ),
        ),
        (
            "How accurate is the GoalIQ model?",
            (
                f"{tr[0]} {tr[1]} {tr[2]} "
                "Every prediction is logged, hits and misses."
            ),
        ),
        (
            "Does GoalIQ give betting tips?",
            (
                "No. GoalIQ publishes model predictions and analytics, not betting "
                "advice. It is not a gambling service and has no odds or bookmaker links."
            ),
        ),
        (
            "Is there a full xP dashboard on top of this free page?",
            (
                "Yes. GoalIQ Premium at pro.goaliq.app adds player expected points "
                "(xP) for the coming gameweeks, a captain ranker and per-gameweek "
                "breakdowns, from the same match model as this page. 3.99 EUR "
                "per month or 25 EUR per year, and one account unlocks premium "
                "on the web, iOS and Android."
            ),
        ),
    ]


def by_comp_html(c: dict) -> str:
    """#111: per-kilpailu-erottelu (headline = blended all_time, tämä lohko
    näyttää mistä se koostuu). Vain n > 0 -rivit; renderöityy tyhjänä stringinä
    jos by_competition puuttuu (vanha accuracy.json) → ei kaadu."""
    if not c["by_comp"]:
        return ""
    rows = "".join(
        '<div class="bycomp-row">'
        f'<span class="bycomp-name">{escape(r["name"])}</span>'
        f'<span class="bycomp-pct">{fmt_pct(r["pct"])}</span>'
        f'<span class="bycomp-n">{r["correct"]} of {r["n"]}</span>'
        "</div>"
        for r in c["by_comp"]
    )
    return (
        '<div class="bycomp" aria-label="Accuracy by competition">'
        '<div class="bycomp-title">By competition</div>'
        + rows
        + "</div>"
    )


# CSS jaettuna fpl.html-templaten ja predictions.html-markerin kesken —
# injektoidaan inline record-lohkoon jotta marker-fill ei riipu sivun
# omasta tyylitiedostosta.
BYCOMP_CSS = (
    ".bycomp{margin:14px 0 4px;max-width:520px;}"
    ".bycomp-title{font-size:12px;font-weight:700;letter-spacing:.08em;"
    "text-transform:uppercase;opacity:.65;margin-bottom:6px;}"
    ".bycomp-row{display:flex;align-items:baseline;gap:10px;padding:6px 0;"
    "border-top:1px solid rgba(128,128,128,.25);font-size:15px;}"
    ".bycomp-name{flex:1;font-weight:600;}"
    ".bycomp-pct{font-weight:800;font-variant-numeric:tabular-nums;}"
    ".bycomp-n{opacity:.65;font-size:13px;font-variant-numeric:tabular-nums;"
    "white-space:nowrap;}"
)


def load_log() -> list[dict]:
    """#117: koko ennusteloki record-taulua varten. Puuttuva tiedosto → []."""
    if not LOG_PATH.exists():
        return []
    return json.loads(LOG_PATH.read_text(encoding="utf-8")).get("predictions", [])


def _pick_txt(e: dict) -> tuple[str, str]:
    """(1/X/2-symboli, joukkuenimi tai Draw) lokirivin pickistä."""
    w = e.get("predicted_winner")
    if w == "home":
        return "1", e.get("home_team", "")
    if w == "away":
        return "2", e.get("away_team", "")
    if w == "draw":
        return "X", "Draw"
    return "-", ""


def _pick_pct(e: dict) -> str:
    """#133: pickin luottamus-% ("71%") lokirivin todennäköisyyksistä, tai ""
    jos dataa ei ole (seed-rivit). Näytetään pick-solussa mobiilin kanssa
    yhtenäisesti (mobiili näyttää 'Pick: X · 71.2%')."""
    w = e.get("predicted_winner")
    p = {"home": e.get("p_home"), "draw": e.get("p_draw"),
         "away": e.get("p_away")}.get(w)
    if p is None:
        return ""
    return f" &middot; {p * 100:.0f}%"


def record_table_html(preds: list[dict], c: dict) -> str:
    """#117: koko per-ottelu-record näkyväksi tauluksi. Vain gradatut rivit
    (result != null) — pending-ennusteet ovat lukittuja mutta pelaamattomia,
    ne mainitaan lukumääränä. Uusin ensin; seed-rivit (WC-lohkovaihe, ei
    päivämäärää) pohjalle. Gradaus = 90 min -tulos (Villen 20.7-normi:
    ET/pilkut = tasapeli): duration != REGULAR merkitään tähdellä."""
    graded = [e for e in preds if e.get("result")]

    def sort_key(e: dict) -> str:
        return e.get("date") or ""

    graded.sort(key=sort_key, reverse=True)

    # #129: filtterit kattavat myös pending-lohkon kilpailut (esim. BSA
    # ennen ensimmäistä gradausta) — sama data-comp-attribuutti molemmissa
    # tauluissa, filtteri-JS osuu kaikkiin .rec-scroll-riveihin.
    comps_in_table = []
    for e in preds:
        code = e.get("competition") or "WC"
        if code not in comps_in_table:
            comps_in_table.append(code)

    filter_btns = '<button class="rec-filter on" data-comp="all">All</button>' + "".join(
        f'<button class="rec-filter" data-comp="{escape(code)}">'
        f"{escape(COMP_NAMES.get(code, code))}</button>"
        for code in comps_in_table
    )

    rows = []
    has_nonregular = False
    for e in graded:
        r = e["result"]
        code = e.get("competition") or "WC"
        pick_sym, pick_name = _pick_txt(e)
        hit = r.get("hit_1x2")
        score = r.get("actual_score", "")
        star = ""
        if r.get("duration") and r["duration"] != "REGULAR":
            star = "*"
            has_nonregular = True
        date_txt = e.get("date") or "Group stage"
        # HUOM: ei backslasheja f-string-lausekkeisiin — CI ajaa Python 3.11:tä
        # (sallittu vasta 3.12+); tämä rivi kaatoi kaikki sivubuilderit 17.–19.7.
        hit_cell = (
            '<span class="rec-hit">&#10003;</span>'
            if hit
            else '<span class="rec-miss">&#10007;</span>'
        )
        rows.append(
            f'<tr data-comp="{escape(code)}">'
            f'<td class="num">{escape(date_txt)}</td>'
            f"<td>{escape(COMP_NAMES.get(code, code))}</td>"
            f'<td class="team">{escape(e.get("home_team", ""))} v {escape(e.get("away_team", ""))}</td>'
            f'<td><strong>{pick_sym}</strong> {escape(pick_name)}'
            f'<span class="rec-pct">{_pick_pct(e)}</span></td>'
            f'<td class="num">{escape(score)}{star}</td>'
            f'<td class="num">{hit_cell}</td>'
            "</tr>"
        )

    star_note = (
        "<p class=\"rec-note\">* Knockout matches level after 90 minutes are "
        "graded as a draw. Extra time and penalty shootouts do not count "
        "toward the result.</p>"
        if has_nonregular
        else ""
    )

    # #129: logatut, pelaamattomat ennusteet omana lohkonaan — "malli teki
    # kutsun ENNEN kickoffia, receipts livenä". Lähin kickoff ensin. EI
    # vaikuta headline-%:iin (vain gradatut lasketaan); reconcile siirtää
    # rivin gradattuun tauluun automaattisesti kun ottelu on pelattu.
    pending = [e for e in preds if not e.get("result")]
    pending.sort(key=lambda e: e.get("kickoff") or e.get("date") or "9999")
    pending_rows = []
    for e in pending:
        code = e.get("competition") or "WC"
        pick_sym, pick_name = _pick_txt(e)
        ko = e.get("kickoff") or ""
        ko_txt = ko.replace("T", " ").replace("Z", " UTC") if ko else (e.get("date") or "")
        logged = (e.get("logged_at") or "")[:10]
        pending_rows.append(
            f'<tr data-comp="{escape(code)}">'
            f'<td class="num">{escape(ko_txt)}</td>'
            f"<td>{escape(COMP_NAMES.get(code, code))}</td>"
            f'<td class="team">{escape(e.get("home_team", ""))} v {escape(e.get("away_team", ""))}</td>'
            f'<td><strong>{pick_sym}</strong> {escape(pick_name)}'
            f'<span class="rec-pct">{_pick_pct(e)}</span></td>'
            f'<td class="num">{escape(logged)}</td>'
            f'<td class="num"><span class="rec-pending">awaiting result</span></td>'
            "</tr>"
        )
    pending_block = (
        (
            "<h3 class=\"rec-subhead\">Upcoming: logged, awaiting result "
            f"({len(pending_rows)})</h3>"
            "<p class=\"rec-note\">These predictions are logged before "
            "kickoff and graded after the match. Nothing is edited once "
            "logged; each row moves to the graded table above when the "
            "result is in.</p>"
            '<div class="rec-scroll"><table>'
            '<thead><tr><th scope="col">Kick-off</th><th scope="col">Competition</th>'
            '<th scope="col">Match</th><th scope="col">Pick</th>'
            '<th scope="col">Logged</th><th scope="col">Status</th></tr></thead>'
            "<tbody>" + "".join(pending_rows) + "</tbody></table></div>"
        )
        if pending_rows
        else ""
    )
    pending_note = (
        f"<p class=\"rec-note\">{c['acc_pending']} further predictions are "
        f"already logged and locked for upcoming matches; they are listed "
        f"below and appear in the graded table once played.</p>"
        if pending_rows
        else ""
    )

    return (
        f"<style>{BYCOMP_CSS}"
        ".rec-filters{display:flex;flex-wrap:wrap;gap:8px;margin:14px 0;}"
        ".rec-filter{border:1px solid rgba(128,128,128,.4);background:transparent;"
        "color:inherit;border-radius:20px;padding:6px 14px;font-size:13px;"
        "font-weight:600;cursor:pointer;}"
        ".rec-filter.on{background:#D6006E;border-color:#D6006E;color:#fff;}"
        ".rec-scroll{overflow-x:auto;overflow-y:auto;max-height:560px;"
        "-webkit-overflow-scrolling:touch;border:1px solid rgba(128,128,128,.3);"
        "border-radius:14px;}"
        ".rec-scroll table{width:100%;border-collapse:collapse;min-width:640px;}"
        ".rec-scroll th,.rec-scroll td{text-align:left;padding:8px 10px;"
        "border-bottom:1px solid rgba(128,128,128,.2);font-size:14px;}"
        ".rec-scroll th{position:sticky;top:0;background:#FFF6EC;font-size:12px;"
        "font-weight:700;text-transform:uppercase;letter-spacing:.05em;color:#54506B;}"
        ".rec-scroll td.team{font-weight:600;white-space:nowrap;}"
        ".rec-scroll .num{white-space:nowrap;font-variant-numeric:tabular-nums;}"
        ".rec-hit{color:#0A9E75;font-weight:800;}"
        ".rec-miss{color:#D6006E;font-weight:800;}"
        ".rec-note{font-size:13px;opacity:.7;margin:10px 0 0;}"
        ".rec-subhead{font-size:18px;margin:26px 0 4px;}"
        ".rec-pending{color:#F4A800;font-weight:700;font-size:12px;"
        "white-space:nowrap;}"
        ".rec-pct{color:#54506B;font-variant-numeric:tabular-nums;}"
        "</style>"
        + by_comp_html(c)
        + f'<div class="rec-filters" role="group" aria-label="Filter by competition">{filter_btns}</div>'
        + '<div class="rec-scroll"><table>'
        + "<caption style=\"caption-side:bottom;font-size:13px;opacity:.7;"
        + "text-align:left;padding:8px 2px;\">Every graded GoalIQ pre-match "
        + "prediction, newest first. Logged before kick-off, no edits afterwards.</caption>"
        + '<thead><tr><th scope="col">Date</th><th scope="col">Competition</th>'
        + '<th scope="col">Match</th><th scope="col">Pick</th>'
        + '<th scope="col">Result</th><th scope="col">1X2</th></tr></thead>'
        + "<tbody>"
        + "".join(rows)
        + "</tbody></table></div>"
        + star_note
        + pending_note
        + pending_block
        + "<script>document.querySelectorAll('.rec-filter').forEach(function(b){"
        + "b.addEventListener('click',function(){"
        + "document.querySelectorAll('.rec-filter').forEach(function(x){x.classList.remove('on');});"
        + "b.classList.add('on');var v=b.getAttribute('data-comp');"
        + "document.querySelectorAll('.rec-scroll tbody tr').forEach(function(tr){"
        + "tr.style.display=(v==='all'||tr.getAttribute('data-comp')===v)?'':'none';});"
        + "});});</script>"
    )


def cs_table_html(c: dict) -> str:
    rows = []
    for r in c["cs_rows"]:
        fdr = r["fdr"]
        rows.append(
            "<tr>"
            f'<td class="team">{escape(r["team"])}</td>'
            f'<td class="num">{fmt_pct(r["cs_pct"])}</td>'
            f'<td>{escape(r["opponent"])} ({r["venue"]})</td>'
            f'<td class="num"><span class="fdr fdr{fdr}">{fdr}</span></td>'
            "</tr>"
        )
    return (
        '<div class="scroll"><table>'
        f"<caption>Model clean sheet probability for every Premier League team, "
        f"Gameweek {c['next_gw']}, {c['season']} season. Sorted by clean sheet chance.</caption>"
        "<thead><tr>"
        '<th scope="col">Team</th><th scope="col" class="num">Clean sheet %</th>'
        '<th scope="col">Next opponent</th><th scope="col" class="num">FDR</th>'
        "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></div>"
    )


# #148: jatkuva CS%-väriskaala grid-soluihin (#144-mobiilipariteetti).
# Ankkurit = olemassa olevat FDR-chippien brändivärit (fdr5→fdr1) samoissa
# cs_pct-pisteissä kuin mobiilin CS_STOPS — FDR-bucket ei säilytä edes
# järjestystä cs_pct:ssä (luokkaparit menevät päällekkäin).
CS_COLOR_STOPS = [
    (8.0, "#D6006E"),   # magenta-deep = vaikein
    (20.0, "#FF6A3D"),  # coral
    (32.0, "#F4A800"),  # gold-deep
    (44.0, "#FFC93C"),  # gold
    (58.0, "#19E3D2"),  # teal = helpoin
]


def _hex_rgb(h: str) -> tuple[int, int, int]:
    return int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)


def cs_cell_colors(cs_pct: float) -> tuple[str, str]:
    """(background, text) jatkuvana cs_pct:stä. Teksti valkoinen tummilla."""
    stops = CS_COLOR_STOPS
    if cs_pct <= stops[0][0]:
        bg = _hex_rgb(stops[0][1])
    elif cs_pct >= stops[-1][0]:
        bg = _hex_rgb(stops[-1][1])
    else:
        bg = None
        for (p0, c0), (p1, c1) in zip(stops, stops[1:]):
            if cs_pct <= p1:
                t = (cs_pct - p0) / (p1 - p0)
                a, b = _hex_rgb(c0), _hex_rgb(c1)
                bg = tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))
                break
        assert bg is not None
    lum = 0.299 * bg[0] + 0.587 * bg[1] + 0.114 * bg[2]
    fg = "#fff" if lum < 140 else "#0A0820"
    return f"#{bg[0]:02X}{bg[1]:02X}{bg[2]:02X}", fg


def _pred_slug(s: str) -> str:
    """SAMA kaava kuin build_prediction_pages._slug (testi vartioi driftin)."""
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def predict_cell_href(team: str, opponent: str, venue: str,
                      root: Path = ROOT) -> str:
    """#152: CS-solun linkkikohde (mobiilipariteetti: solu -> predict-pinta).

    Ohjelmallinen ottelusivu (#119) jos se on generoitu build-hetkellä,
    muuten /predictions-hub (on aina olemassa). PL-ottelusivut syntyvät
    prediction_logista vasta kun lokiin ilmestyy tulevia PL-otteluita
    (elokuu) -> solut päivittyvät ottelusivuiksi automaattisesti
    seuraavassa regenissä, ei koodimuutosta.
    """
    home, away = (team, opponent) if venue == "H" else (opponent, team)
    rel = f"predictions/premier-league/{_pred_slug(home)}-vs-{_pred_slug(away)}.html"
    if (root / rel).exists():
        return "/" + rel
    return "/predictions"


def fdr_grid_html(c: dict) -> str:
    head = "".join(f'<th scope="col" class="num">GW{g}</th>' for g in c["gws"])
    rows = []
    for r in c["fdr_rows"]:
        cells = []
        for fx in r["cells"]:
            if fx is None:
                cells.append('<td class="num">-</td>')
            else:
                # #148: solussa vastustaja + venue + per-fixture CS% (pariteetti
                # mobiilin #144:n kanssa); FDR-luokka siirtyi tooltippiin.
                # #152: solu on linkki predict-pinnalle (mobiilin solu-tap-pariteetti).
                bg, fg = cs_cell_colors(float(fx["cs_pct"]))
                href = predict_cell_href(r["team"], fx["opponent"], fx["venue"])
                cells.append(
                    f'<td class="num"><a class="fdr" href="{href}" '
                    f'style="background:{bg};color:{fg}" '
                    f'title="{escape(fx["opponent"])} ({fx["venue"]}) '
                    f'&middot; FDR {fx["fdr"]} &middot; view model prediction">'
                    f'{escape(fx["opponent_short"])} ({fx["venue"]}) '
                    f'{fx["cs_pct"]:.0f}%'
                    f"</a></td>"
                )
        rows.append(
            "<tr>"
            f'<td class="team">{escape(r["team"])}</td>'
            + "".join(cells)
            + f'<td class="num"><strong>{r["avg_fdr"]:.2f}</strong></td>'
            "</tr>"
        )
    return (
        '<div class="scroll"><table>'
        f"<caption>Clean sheet probability per fixture for the next "
        f"{len(c['gws'])} gameweeks, with opponent and venue. Colour follows the "
        f"clean sheet probability (model FDR in the cell tooltip). "
        f"Sorted by easiest run.</caption>"
        "<thead><tr>"
        '<th scope="col">Team</th>' + head + '<th scope="col" class="num">Avg</th>'
        "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></div>"
    )


# ---------------------------------------------------------------------------
# 3. JSON-LD
# ---------------------------------------------------------------------------
def jsonld_blocks(c: dict, faq: list[tuple[str, str]]) -> str:
    # Entiteetti-disambiguaatio (GEO): goaliq.app = kanoninen GoalIQ-entiteetti.
    # Google sekoittaa GoalIQ:n samannimiseen Benisse-appiin + YouTube/IG-tileihin
    # → Organization + sameAs VAIN virallisiin kanaviin (Play, App Store, X,
    #   TikTok, IG - Villen vahvistamat 22.7, #121-GEO).
    org = {
        "@context": "https://schema.org",
        "@type": "Organization",
        "@id": ORG_ID,
        "name": "GoalIQ",
        "url": BASE + "/",
        "description": (
            "GoalIQ makes FPL (Fantasy Premier League) tools - clean sheet "
            "probability and fixture difficulty, rate my team with a captain pick, "
            "a fit checker, a pre-season draft rater "
            "and price watch free, plus an interactive team manager with a "
            "gameweek planner, player expected points (xP), the captain "
            "ranker, player value, xG leaders, a DefCon tracker, "
            "differentials and transfer suggestions with apply on GoalIQ "
            "Premium - powered by a Dixon-Coles + machine-learning match model "
            "with a public, pre-match-logged prediction track record. Built by "
            "an independent developer in Finland. Analytics, not betting."
        ),
        "logo": BASE + "/assets/brand/goaliq-appicon-512.png",
        "sameAs": [PLAY_URL, APPSTORE_URL, X_URL, TIKTOK_URL, IG_URL],
    }
    app = {
        "@context": "https://schema.org",
        "@type": "SoftwareApplication",
        "name": "GoalIQ",
        "operatingSystem": "Android, iOS, Web",
        "identifier": "com.veikkoville.goaliq",
        "applicationCategory": "SportsApplication",
        "description": (
            "Free FPL assistant and football prediction app. Free FPL tools: "
            "clean sheet probability and fixture difficulty, rate my team with a "
            "captain pick, and price watch. GoalIQ Premium adds an interactive "
            "team manager with a GW1 to GW6 gameweek planner, player expected "
            "points (xP), the captain ranker, player value (xP per million), "
            "xG leaders, a DefCon (defensive contribution) tracker, "
            "differentials and transfer suggestions with apply. Also predicts "
            "any match - win probability, expected goals (xG) and the most "
            "likely score - using a Dixon-Coles model with an expected-goals "
            "ensemble. Analytics, not betting."
        ),
        "url": BASE + "/",
        "downloadUrl": [PLAY_URL, APPSTORE_URL],
        "author": {"@id": ORG_ID},
        "offers": [
            {"@type": "Offer", "name": "GoalIQ app (free download)",
             "price": "0", "priceCurrency": "USD"},
            {"@type": "Offer", "name": "GoalIQ Premium on the web, monthly",
             "price": "3.99", "priceCurrency": "EUR",
             "url": f"{PRO_URL}/checkout?plan=monthly"},
            {"@type": "Offer", "name": "GoalIQ Premium on the web, season (yearly)",
             "price": "25", "priceCurrency": "EUR",
             "url": PRO_CHECKOUT_SEASON_URL},
        ],
    }
    faq_ld = {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": q,
                "acceptedAnswer": {"@type": "Answer", "text": a},
            }
            for q, a in faq
        ],
    }
    dataset = {
        "@context": "https://schema.org",
        "@type": "Dataset",
        "name": (
            f"GoalIQ FPL clean sheet probability and fixture difficulty, "
            f"Premier League {c['season']}"
        ),
        "description": (
            f"Model clean sheet probability for every Premier League team and a "
            f"model fixture difficulty rating (1 to 5) for the next {len(c['gws'])} "
            f"gameweeks of the {c['season']} season, from GoalIQ's Dixon-Coles "
            f"match model. Updated every gameweek."
        ),
        "url": CANONICAL,
        "isAccessibleForFree": True,
        "dateModified": c["iso_date"],
        "temporalCoverage": "2026-08/2027-05",
        "creator": {"@id": ORG_ID},
        "keywords": [
            "FPL clean sheets",
            "fixture difficulty rating",
            "Premier League predictions",
            "clean sheet probability",
            "FDR",
        ],
    }
    # #85 GEO: track record koneluettavana Datasetina (LLM-sitaattien
    # ykkösmuoto). Luvut samasta accuracy-lähteestä kuin GEN:ACC-chipit →
    # pysyy tuoreena joka regen-ajolla, ei kovakoodattuja staleja.
    acc_dataset = accuracy_dataset_ld(c, CANONICAL)
    return "".join(
        f'<script type="application/ld+json">\n{json.dumps(b, ensure_ascii=False, indent=1)}\n</script>\n'
        for b in (org, app, faq_ld, dataset, acc_dataset)
    )


def accuracy_dataset_ld(c: dict, page_url: str) -> dict:
    """#85: julkisen ennuste-track-recordin Dataset-schema (jaettu fpl.html-
    templaten ja index.html-markerin kesken — yksi määritelmä, ei driftiä)."""
    return {
        "@context": "https://schema.org",
        "@type": "Dataset",
        "name": "GoalIQ football prediction accuracy log (pre-match, publicly tracked)",
        "description": (
            f"Every GoalIQ model prediction is logged before kickoff and "
            f"reconciled against the final result, with no edits afterwards. "
            f"Current aggregate: {fmt_pct(c['acc_pct_1x2'])} correct 1X2 results "
            f"across {c['acc_n']} completed matches. Includes per-match win/draw/loss "
            f"probabilities, expected goals (xG) and reconciled outcomes."
        ),
        "url": page_url,
        "distribution": {
            "@type": "DataDownload",
            "encodingFormat": "application/json",
            "contentUrl": API_BASE + "/api/accuracy",
        },
        "isAccessibleForFree": True,
        "dateModified": c["iso_date"],
        "creator": {"@id": ORG_ID},
        "keywords": [
            "football prediction accuracy",
            "prediction track record",
            "1X2 accuracy",
            "pre-match predictions",
            "model accountability",
        ],
    }


# ---------------------------------------------------------------------------
# 4. Sivu
# ---------------------------------------------------------------------------
# Kanoninen brändipaletti (goaliq-app/assets/brand/brand-tokens.md) - täsmähexit.
# Hero = tumma (Ink) + magenta, sisältö = vaalea (Cream/Paper) + ink-teksti.
CSS = """
  :root{ --magenta:#FF2E7E; --magenta-deep:#D6006E; --coral:#FF6A3D; --gold:#FFC93C; --gold-deep:#F4A800; --teal:#19E3D2; --ink:#0A0820; --ink2:#140F1E; --cream:#FFF6EC; --paper:#F6F4FF; --ink-muted:#54506B; --hero-muted:#C9C3DA; --line:#E7DDCF; }
  *{ box-sizing:border-box; }
  body{ margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif; background:var(--cream); color:var(--ink); line-height:1.6; font-size:17px; }
  h1,h2,h3,.brand{ font-family:"Space Grotesk",-apple-system,"Segoe UI",sans-serif; }
  .dark{ background:linear-gradient(165deg,var(--ink2),var(--ink)); color:var(--cream); }
  .wrap{ max-width:960px; margin:0 auto; padding:0 20px; }
  .bar{ height:6px; background:var(--magenta); }
  .nav{ max-width:960px; margin:0 auto; padding:18px 20px; display:flex; align-items:center; justify-content:space-between; gap:12px; }
  .brand{ font-size:24px; font-weight:800; letter-spacing:.5px; }
  .brand a{ color:#fff; text-decoration:none; display:inline-flex; align-items:center; gap:8px; }
  .brand span{ color:var(--magenta); }
  .brand-icon{ width:26px; height:26px; border-radius:7px; display:block; }
  .cta{ display:inline-block; background:var(--magenta); color:#fff; text-decoration:none; padding:14px 24px; border-radius:30px; font-weight:800; min-height:48px; }
  .cta:hover{ background:var(--magenta-deep); }
  .cta.secondary{ background:transparent; border:2px solid var(--magenta); color:inherit; }
  .cta-row{ display:flex; flex-wrap:wrap; gap:12px; margin:26px 0 8px; }
  .hero{ padding:44px 0 52px; }
  .hero h1{ font-size:36px; line-height:1.15; margin:0 0 14px; color:#fff; }
  .hero .lede{ font-size:19px; color:var(--hero-muted); max-width:720px; }
  .hero .meta,.hero .note{ color:var(--hero-muted); }
  .meta{ font-size:14px; margin-top:10px; }
  .note{ color:var(--ink-muted); font-size:14px; }
  h2{ font-size:25px; margin:54px 0 10px; }
  .content{ padding-bottom:70px; }
  .content a{ color:var(--magenta-deep); }
  .content a.cta{ color:#fff; }
  .content a.cta.secondary{ color:var(--ink); }
  .scroll{ overflow-x:auto; -webkit-overflow-scrolling:touch; background:var(--paper); border:1px solid var(--line); border-radius:14px; padding:4px 12px 10px; }
  table{ width:100%; border-collapse:collapse; min-width:560px; }
  caption{ caption-side:bottom; color:var(--ink-muted); font-size:13px; text-align:left; padding:10px 2px 4px; }
  th,td{ text-align:left; padding:10px 8px; border-bottom:1px solid var(--line); font-size:15px; }
  tbody tr:last-child td{ border-bottom:none; }
  th{ color:var(--ink-muted); font-weight:600; font-size:13px; }
  th.num,td.num{ text-align:right; font-variant-numeric:tabular-nums; white-space:nowrap; }
  td.team{ font-weight:700; white-space:nowrap; }
  .fdr{ display:inline-block; min-width:34px; padding:3px 8px; border-radius:8px; color:var(--ink); font-weight:700; text-align:center; font-size:13px; text-decoration:none; }
  a.fdr:hover{ filter:brightness(0.92); }
  .fdr1{ background:#19E3D2; } .fdr2{ background:#FFC93C; } .fdr3{ background:#F4A800; } .fdr4{ background:#FF6A3D; } .fdr5{ background:#D6006E; color:#fff; }
  .legend{ color:var(--ink-muted); font-size:14px; margin:8px 0 0; }
  .stat-row{ display:flex; flex-wrap:wrap; gap:14px; margin:18px 0; }
  .stat{ background:var(--paper); border:1px solid var(--line); border-radius:16px; padding:16px 20px; flex:1 1 180px; }
  .stat b{ display:block; font-size:30px; color:var(--magenta-deep); font-variant-numeric:tabular-nums; }
  .stat span{ color:var(--ink-muted); font-size:14px; }
  .faq dt{ font-weight:700; margin-top:20px; }
  .faq dd{ margin:6px 0 0; }
  .disclaimer{ border:1px solid var(--line); background:var(--paper); border-radius:12px; padding:12px 16px; color:var(--ink-muted); font-size:14px; margin:26px 0 60px; }
  .upsell{ border:2px solid var(--magenta); background:var(--paper); border-radius:16px; padding:24px 26px; margin:48px 0 6px; }
  .upsell h2{ margin:0 0 10px; }
  .upsell p{ margin:0 0 6px; }
  .upsell .cta-row{ margin:18px 0 4px; }
  .upsell .price-note{ color:var(--ink-muted); font-size:14px; margin:10px 0 0; }
  footer{ padding:30px 0 40px; font-size:14px; }
  footer .wrap{ color:var(--hero-muted); }
  footer a{ color:var(--cream); }
  footer a:hover{ color:var(--magenta); }
  @media (max-width:640px){ .hero h1{ font-size:29px; } .hero .lede{ font-size:17px; } .nav{ padding:14px 16px; } .hero{ padding:30px 0 40px; } }
  /* Kapea mobiili: CTA-napit pinoon täysleveinä, pitkä label ei ylivuoda (#15) */
  @media (max-width:520px){
    .cta-row{ flex-direction:column; align-items:stretch; }
    .cta{ max-width:100%; text-align:center; }
  }
  html,body{ overflow-x:clip; }
"""


def render_page(c: dict) -> str:
    faq = build_faq(c)
    tr = track_record_sentences(c)
    jsonld = jsonld_blocks(c, faq)
    cs_table = cs_table_html(c)
    fdr_grid = fdr_grid_html(c)
    # #148: legenda samalla jatkuvalla CS%-skaalalla kuin solut (koherenssi —
    # ei FDR 1-5 -laatikoita cs%-värien päällä, #144-oppi).
    cs_legend = " ".join(
        '<span class="fdr" style="background:{bg};color:{fg}">{p}%</span>'.format(
            bg=cs_cell_colors(p)[0], fg=cs_cell_colors(p)[1], p=p
        )
        for p in (10, 22, 34, 46, 58)
    )

    title = "Free FPL Tools – Rate My Team, Captain Pick & Clean Sheet Probability | GoalIQ"
    meta_desc = (
        "Free FPL tools: clean sheet probability & FDR, rate my team with a captain pick, "
        "fit checker, pre-season draft rater "
        "and price watch. Premium adds a team manager with gameweek planner, "
        "player xP, value ranking, xG leaders and a DefCon tracker. "
        "Published track record. Not betting."
    )

    faq_html = "".join(
        f"<dt>{escape(q)}</dt><dd>{escape(a)}</dd>" for q, a in faq
    )

    stats = (
        '<div class="stat-row">'
        f'<div class="stat"><b>{fmt_pct(c["acc_pct_1x2"])}</b>'
        f'<span>correct results across {c["acc_n"]} completed predictions, all competitions</span></div>'
        f'<div class="stat"><b>{fmt_pct(c["acc_pct_dec"])}</b>'
        f'<span>hit rate when the model called a winner ({c["acc_dec_c"]} of {c["acc_dec_n"]})</span></div>'
        f'<div class="stat"><b>{c["acc_logged"]}</b>'
        f'<span>predictions logged before kickoff, hits and misses</span></div>'
        "</div>"
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<meta name="description" content="{meta_desc}">
<meta name="robots" content="index,follow">
<link rel="canonical" href="{CANONICAL}">
<link rel="alternate" hreflang="en" href="{CANONICAL}">
<link rel="alternate" hreflang="x-default" href="{CANONICAL}">
<link rel="icon" href="/favicon.ico" sizes="any">
<link rel="icon" type="image/png" sizes="32x32" href="/assets/brand/goaliq-favicon-32.png">
<link rel="icon" type="image/png" sizes="48x48" href="/assets/brand/goaliq-favicon-48.png">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;700&display=swap" rel="stylesheet">
<link rel="apple-touch-icon" sizes="180x180" href="/assets/brand/goaliq-apple-touch-180.png">

<meta property="og:type" content="website">
<meta property="og:title" content="Free FPL Tools – Rate My Team, Captain Pick & Clean Sheet Probability | GoalIQ">
<meta property="og:description" content="{meta_desc}">
<meta property="og:url" content="{CANONICAL}">
<meta property="og:image" content="{BASE}/assets/brand/goaliq-social-1200x630.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:site" content="@goaliqapp">
<meta name="twitter:title" content="Free FPL Tools – Rate My Team, Captain Pick & Clean Sheet Probability | GoalIQ">
<meta name="twitter:description" content="{meta_desc}">
<meta name="twitter:image" content="{BASE}/assets/brand/goaliq-social-1200x630.png">

{jsonld}
<meta name="theme-color" content="#0A0820">
<style>{CSS}</style>
{POSTHOG_SNIPPET}
</head>
<body>
<header class="dark">
  <div class="bar"></div>
  <div class="nav">
    <div class="brand"><a href="./"><img class="brand-icon" src="assets/brand/goaliq-appicon-192.png" width="26" height="26" alt="">Goal<span>IQ</span></a></div>
    <a class="cta" href="{PRO_TAB_URL}" data-cta="nav">Open GoalIQ Premium</a>
  </div>
</header>

<main>
<article>

<section class="hero dark">
<div class="wrap">
<h1>Free FPL Tools: Clean Sheet Probability, Fixture Difficulty and More</h1>
<p class="lede">GoalIQ is a free FPL assistant built on a proven match model.
This page gives clean sheet probability and fixture difficulty for every
Premier League team, free and updated every gameweek. Rate my team, a captain
pick and price watch are free too; GoalIQ Premium adds an interactive team
manager with a gameweek planner, player expected points (xP), the captain
ranker, player value, xG leaders, a DefCon tracker and transfer suggestions
you can apply to your planned squad.</p>
<p class="meta">Season {c["season"]}. Data updated {c["data_date"]}.
Gameweek {c["next_gw"]} starts {c["gw_label"]}.</p>

<div class="cta-row">
  <a class="cta" href="{PRO_TAB_URL}" data-cta="fpl">See the full xP dashboard on GoalIQ Premium</a>
  <a class="cta secondary" href="{PLAY_URL}">Google Play</a>
  <a class="cta secondary" href="{APPSTORE_URL}">App Store</a>
</div>
<p class="meta">One account, premium on web, iOS and Android.</p>
<p class="note">Free download. Predict any fixture yourself in the app.</p>
<p class="note">The model plays FPL this season with its own public team.
Think you can outdraft it? Join the
<a href="https://fantasy.premierleague.com/leagues/auto-join/jgi6j9" data-cta="league">Beat
the Model mini-league</a> with code <strong>jgi6j9</strong>. Season winner gets a year of
GoalIQ Premium, free.</p>
</div>
</section>

<div class="wrap content">

<h2 id="track-record">The model publishes its prediction record</h2>
<p>{escape(tr[0])} {escape(tr[1])} {escape(tr[2])}</p>
{stats}
<style>{BYCOMP_CSS}</style>
{by_comp_html(c)}
<p class="note">Source: GoalIQ prediction log, updated {c["acc_date"]}. The full
log, match by match with every miss included, is published on the
<a href="/predictions#record">prediction record page</a>.</p>

<h2 id="clean-sheets">Gameweek {c["next_gw"]} clean sheet probabilities</h2>
<p>Model clean sheet probability for all 20 Premier League teams in
Gameweek {c["next_gw"]} ({c["gw_label"]}). FDR is GoalIQ's model fixture
difficulty for that match, 1 easiest to 5 hardest.</p>
{cs_table}
<p class="note">Pre-season projection: team strengths use 2024/25 and 2025/26
results as priors, and newly promoted sides use an empirical promoted-team
baseline. The numbers sharpen as {c["season"]} results arrive.</p>

<h2 id="fixture-difficulty">Fixture difficulty for the next six gameweeks</h2>
<p>Clean sheet probability per team and gameweek. Each cell shows the opponent,
venue and the model's clean sheet probability for that match; the colour follows
the same probability on a continuous scale, so two fixtures in the same FDR
class no longer look identical. Model FDR (1 easiest, 5 hardest) stays in the
cell tooltip. Model-derived, not the official FPL difficulty.</p>
{fdr_grid}
<p class="legend">Clean sheet scale: {cs_legend}
(low CS% = hard fixture, high CS% = easy). H home, A away.</p>

<aside class="upsell">
<h2 id="pro">Unlock the full FPL toolkit with Premium</h2>
<p>GoalIQ Premium adds an interactive team manager (formations, bench swaps,
captaincy and a GW1 to GW6 gameweek planner showing each player's opponent
per week), player expected points (xP), a captain ranker, transfer suggestions
you can apply straight to your planned squad, a player value ranking (xP per
million), full xG leaders and DefCon leaderboards, goalkeeper rotation pairs,
differential picks, player compare and predicted starting minutes, from the
same match model as this page. Rate my team, a captain pick, price watch and
the top three of every leaderboard are free.</p>
<div class="cta-row">
  <a class="cta" href="{PRO_CHECKOUT_SEASON_URL}" data-cta="fpl">Start GoalIQ Premium &mdash; &euro;25/year</a>
</div>
<p class="price-note">From €25 a year (under €2.10 a month), or €3.99 a month.
One subscription covers web, iOS and Android.</p>
</aside>

<!-- #78: career-kortin löydettävyys - ilmainen jakelutyökalu, teal-reunus
     erottaa premium-upsellista (delegoitu pro_cta_clicked kattaa linkin). -->
<aside class="upsell" style="border-color:var(--teal-ink);">
<h2 id="career-card">Your FPL Career Card - free, on one shareable image</h2>
<p>Best season, all-time points and your rank history on one card, built from
your public FPL entry ID. No login. Made for sharing with your mini-league.</p>
<div class="cta-row">
  <a class="cta" href="/career" data-cta="fpl-career">Build your career card</a>
</div>
</aside>

<h2 id="methodology">Methodology</h2>
<p>A Dixon-Coles style match model, tau corrected, trained on recent results.
Clean sheet probability comes from the score matrix: the chance the opponent
scores zero. Fixture difficulty is derived from win and clean sheet
probabilities, ranked across every team fixture of the season and bucketed
into five tiers. Fixture data comes from the official Premier League fantasy
API, with premierleague.com as the fixture source until the FPL game opens
for {c["season"]}.</p>

<h2 id="about">About GoalIQ</h2>
<p>GoalIQ is a free football prediction app built by an independent developer
in Finland. The same model powers the app and this page. The methodology is
public, and every published prediction is logged before kickoff so the record
cannot be edited after the fact. If the model has a bad week, the log shows it.</p>

<h2 id="faq">FAQ</h2>
<dl class="faq">
{faq_html}
</dl>

<div class="cta-row">
  <a class="cta" href="{PRO_TAB_URL}" data-cta="fpl">Open GoalIQ Premium: player xP and captain ranker</a>
  <a class="cta secondary" href="{PLAY_URL}">Predict any fixture in the GoalIQ app</a>
  <a class="cta secondary" href="{APPSTORE_URL}">Download on the App Store</a>
</div>

<p class="disclaimer"><strong>Disclaimer:</strong> GoalIQ provides model
predictions and analytics. Not betting advice.</p>

</div>
</article>
</main>

<footer class="dark">
  <div class="wrap">
  <p><a href="./">GoalIQ home</a> &middot;
  <a href="{PRO_URL}">GoalIQ Premium (web)</a> &middot;
  <a href="/predictions">Match predictions</a> &middot;
  <a href="world-cup-2026-predictions.html">World Cup 2026 predictions</a> &middot;
  <a href="faq.html">App FAQ</a> &middot;
  <a href="privacy.html">Privacy</a></p>
  <p>&copy; 2026 GoalIQ. Premier League is a trademark of the Football
  Association Premier League Limited. GoalIQ is not affiliated with or endorsed
  by the Premier League. Data on this page is a statistical model output for
  informational purposes.</p>
  </div>
</footer>

{CTA_TRACK_SNIPPET}

</body>
</html>
"""


# ---------------------------------------------------------------------------
# 5. Etusivun track record -markerit (index.html, homepage-update 4.7)
# ---------------------------------------------------------------------------
INDEX_PATH = ROOT / "index.html"


def update_index(c: dict) -> bool:
    """Täytä index.html:n GEN:ACC-markerit tuoreilla accuracy-luvuilla.
    Sama lähde ja refresh-tahti kuin fpl.html (ei staleja kovakoodauksia)."""
    if not INDEX_PATH.exists():
        return False
    s = INDEX_PATH.read_text(encoding="utf-8")
    chip = (
        f'<div class="num">{fmt_pct(c["acc_pct_1x2"])}</div>'
        f'<div class="lbl">result accuracy across {c["acc_n"]} completed matches, '
        f"all competitions</div>"
    )
    proof = (
        f"The model logs every prediction before kickoff. "
        f"{fmt_pct(c['acc_pct_1x2'])} correct results across {c['acc_n']} completed matches."
    )
    trust = (
        f"Built on a model with {fmt_pct(c['acc_pct_1x2'])} correct 1X2 results "
        f"across {c['acc_n']} completed matches, every prediction logged before kick-off."
    )
    new = re.sub(
        r"(<!-- GEN:ACC-CHIP-START -->).*?(<!-- GEN:ACC-CHIP-END -->)",
        lambda m: m.group(1) + chip + m.group(2), s, flags=re.S)
    new = re.sub(
        r"(<!-- GEN:ACC-PROOF-START -->).*?(<!-- GEN:ACC-PROOF-END -->)",
        lambda m: m.group(1) + proof + m.group(2), new, flags=re.S)
    new = re.sub(
        r"(<!-- GEN:ACC-TRUST-START -->).*?(<!-- GEN:ACC-TRUST-END -->)",
        lambda m: m.group(1) + trust + m.group(2), new, flags=re.S)
    # #85 GEO: track-record-Dataset-schema pysyy tuoreena samalla botilla
    # kuin chipit (luvut + dateModified accuracy-lähteestä, ei kovakoodausta).
    ds = accuracy_dataset_ld(c, BASE + "/")
    ds_block = (
        '\n<script type="application/ld+json">\n'
        + json.dumps(ds, ensure_ascii=False, indent=1)
        + "\n</script>\n"
    )
    new = re.sub(
        r"(<!-- GEN:ACC-DATASET-START -->).*?(<!-- GEN:ACC-DATASET-END -->)",
        lambda m: m.group(1) + ds_block + m.group(2), new, flags=re.S)
    # #111: per-kilpailu-erottelu tr-heron alle (sama refresh-tahti kuin chipit).
    bycomp_block = f"<style>{BYCOMP_CSS}</style>" + by_comp_html(c)
    new = re.sub(
        r"(<!-- GEN:ACC-BYCOMP-START -->).*?(<!-- GEN:ACC-BYCOMP-END -->)",
        lambda m: m.group(1) + bycomp_block + m.group(2), new, flags=re.S)
    if new != s:
        INDEX_PATH.write_text(new, encoding="utf-8")
        return True
    return False


# ---------------------------------------------------------------------------
# 5b. Evergreen predict-sivun track record -markerit (predictions.html, #105)
# ---------------------------------------------------------------------------
PREDICTIONS_PATH = ROOT / "predictions.html"
PREDICTIONS_URL = f"{BASE}/predictions"


def update_predictions(c: dict, preds: list[dict]) -> bool:
    """Täytä predictions.html:n GEN:ACC-markerit tuoreilla accuracy-luvuilla
    (#105). Sama lähde ja refresh-tahti kuin fpl.html/index.html - evergreen-
    sivun track record ei koskaan jää staleksi kovakoodaukseksi.
    #117: sama ajo bakee myös koko per-ottelu-recordin (GEN:ACC-RECORD) —
    /predictions on record-taulun kanoninen koti."""
    if not PREDICTIONS_PATH.exists():
        return False
    s = PREDICTIONS_PATH.read_text(encoding="utf-8")
    chip = (
        f'<div class="num">{fmt_pct(c["acc_pct_1x2"])}</div>'
        f'<div class="lbl">result accuracy across {c["acc_n"]} completed matches, '
        f"all competitions</div>"
    )
    proof = (
        f"The model logs every prediction before kickoff. "
        f"{fmt_pct(c['acc_pct_1x2'])} correct results across {c['acc_n']} completed matches."
    )
    trust = (
        f"Built on a model with {fmt_pct(c['acc_pct_1x2'])} correct 1X2 results "
        f"across {c['acc_n']} completed matches, every prediction logged before kick-off."
    )
    new = re.sub(
        r"(<!-- GEN:ACC-CHIP-START -->).*?(<!-- GEN:ACC-CHIP-END -->)",
        lambda m: m.group(1) + chip + m.group(2), s, flags=re.S)
    new = re.sub(
        r"(<!-- GEN:ACC-PROOF-START -->).*?(<!-- GEN:ACC-PROOF-END -->)",
        lambda m: m.group(1) + proof + m.group(2), new, flags=re.S)
    new = re.sub(
        r"(<!-- GEN:ACC-TRUST-START -->).*?(<!-- GEN:ACC-TRUST-END -->)",
        lambda m: m.group(1) + trust + m.group(2), new, flags=re.S)
    ds = accuracy_dataset_ld(c, PREDICTIONS_URL)
    ds_block = (
        '\n<script type="application/ld+json">\n'
        + json.dumps(ds, ensure_ascii=False, indent=1)
        + "\n</script>\n"
    )
    new = re.sub(
        r"(<!-- GEN:ACC-DATASET-START -->).*?(<!-- GEN:ACC-DATASET-END -->)",
        lambda m: m.group(1) + ds_block + m.group(2), new, flags=re.S)
    # #117: koko record-taulu (sisältää #111-by-comp-lohkon taulun päällä).
    record_block = record_table_html(preds, c)
    new = re.sub(
        r"(<!-- GEN:ACC-RECORD-START -->).*?(<!-- GEN:ACC-RECORD-END -->)",
        lambda m: m.group(1) + record_block + m.group(2), new, flags=re.S)
    if new != s:
        PREDICTIONS_PATH.write_text(new, encoding="utf-8")
        return True
    return False


WC_HUB_PATH = ROOT / "world-cup-2026-predictions.html"


def update_wc_recap(acc: dict) -> bool:
    """#140: WC-recap-hubin GEN:WCRECAP-lohko accuracy.json:sta (ei kovakoodattuja
    prosentteja sivulla, vrt. #118). Hub on pysyvä conviction-asetti — luvut
    tulevat by_competition.WC:stä joka on jäädytetty (turnaus ohi) mutta
    regradaus/normimuutos päivittyy tänne automaattisesti."""
    if not WC_HUB_PATH.exists():
        return False
    wc = (acc.get("by_competition") or {}).get("WC") or {}
    n = wc.get("n")
    if not n:
        return False
    # accuracy.json tallentaa osuudet 0..1 — fmt_pct odottaa 0..100 (kuten c:n
    # acc_pct_1x2, jonka build_context kertoo sadalla).
    pct_1x2 = (wc.get("pct_1x2") or 0.0) * 100.0
    pct_dec = (wc.get("pct_decisive") or 0.0) * 100.0
    block = (
        '<div class="statrow">'
        f'<div class="stat"><div class="num">{fmt_pct(pct_1x2)}</div>'
        f'<div class="lbl">correct 1X2 results across all {n} completed '
        "World Cup matches "
        f'({wc.get("correct_1x2")} of {n})</div></div>'
        f'<div class="stat"><div class="num">{fmt_pct(pct_dec)}</div>'
        f'<div class="lbl">accuracy in decisive matches '
        f'({wc.get("decisive_correct")} of {wc.get("decisive_n")} that did not '
        "end in a draw)</div></div>"
        "</div>"
        '<p class="meta">Knockout matches level after 90 minutes are graded '
        "as a draw; extra time and penalty shootouts do not count toward the "
        "result. Numbers update automatically from the same public log as "
        "the track record page.</p>"
    )
    s = WC_HUB_PATH.read_text(encoding="utf-8")
    new = re.sub(
        r"(<!-- GEN:WCRECAP-START -->).*?(<!-- GEN:WCRECAP-END -->)",
        lambda m: m.group(1) + block + m.group(2), s, flags=re.S)
    if new != s:
        WC_HUB_PATH.write_text(new, encoding="utf-8")
        return True
    return False


# ---------------------------------------------------------------------------
# 6. Sitemap lastmod
# ---------------------------------------------------------------------------
def _upsert_sitemap_entry(xml: str, loc: str, iso_date: str,
                          changefreq: str, priority: str) -> str:
    """Päivitä (tai lisää) yhden URL:n sitemap-blokki. Idempotentti."""
    entry = (
        "  <url>\n"
        f"    <loc>{loc}</loc>\n"
        f"    <lastmod>{iso_date}</lastmod>\n"
        f"    <changefreq>{changefreq}</changefreq>\n"
        f"    <priority>{priority}</priority>\n"
        "  </url>\n"
    )
    if f"<loc>{loc}</loc>" in xml:
        return re.sub(
            r"  <url>\s*<loc>" + re.escape(loc) + r"</loc>.*?</url>\n",
            entry,
            xml,
            flags=re.S,
        )
    return xml.replace("</urlset>", entry + "</urlset>")


def write_urlset(path: Path, entries: list[tuple[str, str, str, str]]) -> None:
    """#119b: kirjoita kokonainen urlset-sitemap kerralla (wholesale-regen →
    stalet entryt siivoutuvat automaattisesti kun sivut poistuvat).
    entries = [(loc, lastmod-iso, changefreq, priority), ...]."""
    body = "".join(
        "  <url>\n"
        f"    <loc>{loc}</loc>\n"
        f"    <lastmod>{lastmod}</lastmod>\n"
        f"    <changefreq>{cf}</changefreq>\n"
        f"    <priority>{pr}</priority>\n"
        "  </url>\n"
        for loc, lastmod, cf, pr in entries
    )
    path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + body
        + "</urlset>\n",
        encoding="utf-8",
    )


def update_sitemap(iso_date: str) -> bool:
    xml = SITEMAP_PATH.read_text(encoding="utf-8")
    new = _upsert_sitemap_entry(xml, CANONICAL, iso_date, "weekly", "0.9")
    # #105: evergreen predict-sivu elää samassa refresh-tahdissa (accuracy-
    # markerit päivittyvät joka ajolla → lastmod mukana).
    if PREDICTIONS_PATH.exists():
        new = _upsert_sitemap_entry(new, PREDICTIONS_URL, iso_date, "weekly", "0.9")
    if new != xml:
        SITEMAP_PATH.write_text(new, encoding="utf-8")
        return True
    return False


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main() -> None:
    fpl, acc = load_data()
    c = build_context(fpl, acc)
    preds = load_log()
    html_out = render_page(c)
    OUT_PATH.write_text(html_out, encoding="utf-8")
    sitemap_changed = update_sitemap(c["iso_date"])
    index_changed = update_index(c)
    predictions_changed = update_predictions(c, preds)
    wc_recap_changed = update_wc_recap(acc)

    print("=" * 64)
    print("FPL-LANDING BAKE OK")
    print("=" * 64)
    print(f"  fpl.html          : {len(html_out)} merkkiä")
    print(f"  sitemap.xml       : {'päivitetty' if sitemap_changed else 'ei muutosta'}")
    print(f"  index.html        : {'accuracy-markerit päivitetty' if index_changed else 'ei muutosta'}")
    print(f"  predictions.html  : {'accuracy-markerit päivitetty' if predictions_changed else 'ei muutosta'}")
    print(f"  wc-recap-hub      : {'WCRECAP-markerit päivitetty' if wc_recap_changed else 'ei muutosta'}")
    print(f"  GW                : {c['next_gw']} ({c['gw_label']})")
    print(f"  CS-rivejä         : {len(c['cs_rows'])}")
    print(f"  FDR-rivejä        : {len(c['fdr_rows'])} x {len(c['gws'])} GW")
    print(f"  Track record      : {fmt_pct(c['acc_pct_1x2'])} 1X2 (n={c['acc_n']}), "
          f"decisive {fmt_pct(c['acc_pct_dec'])} ({c['acc_dec_c']}/{c['acc_dec_n']}), "
          f"logged {c['acc_logged']}")
    print(f"  Top-3 CS% GW{c['next_gw']}   : "
          + "; ".join(f"{r['team']} {fmt_pct(r['cs_pct'])}" for r in c["top3"]))
    print(f"  Lähteet           : {FPL_PATH.name} ({c['data_date']}), "
          f"{ACC_PATH.name} ({c['acc_date']})")
    print("\nJulkaisu (Villen GO vaaditaan, Pages servaa mainista):")
    print("  git add fpl.html sitemap-core.xml")
    print('  git commit -m "geo(fpl): FPL-landing data-refresh"')
    print("  git push")


if __name__ == "__main__":
    main()
