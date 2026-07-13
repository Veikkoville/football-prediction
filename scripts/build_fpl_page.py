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
OUT_PATH = ROOT / "fpl.html"
SITEMAP_PATH = ROOT / "sitemap.xml"

# Custom domain (goaliq.app, Cloudflare, rekisteröity 4.7.2026). GitHub Pages
# servaa CNAME:n kautta juuresta → EI /football-prediction-polkuprefiksiä.
# Vanhat veikkoville.github.io/football-prediction/* -URLit redirectaavat.
BASE = "https://goaliq.app"
CANONICAL = f"{BASE}/fpl.html"
PLAY_URL = "https://play.google.com/store/apps/details?id=com.veikkoville.goaliq"
APPSTORE_URL = "https://apps.apple.com/app/id6780047163"
PRO_URL = "https://pro.goaliq.app"
X_URL = "https://x.com/goaliqapp"
ORG_ID = BASE + "/#organization"

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
            f"The GoalIQ model logged {c['acc_logged']} pre-match predictions "
            f"live during the 2026 World Cup, before kickoff, with no edits afterwards."
        ),
        (
            f"Across the {c['acc_n']} matches already played, the model called the "
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
                "Yes. GoalIQ is built FPL-first: clean sheet odds, fixture "
                "difficulty, rate my team with a captain pick, and price watch "
                "are free, and GoalIQ Premium adds player expected points (xP), "
                "the captain ranker, differentials and a transfer planner. "
                "Every number comes from a match model with a published, "
                "pre-match-logged track record."
            ),
        ),
        (
            "What FPL tools does GoalIQ have?",
            (
                "Free: clean sheet probabilities, fixture difficulty ratings "
                "(FDR), rate my team with a captain pick, and price watch. "
                "GoalIQ Premium: player expected points (xP) per gameweek, the "
                "captain ranker, differentials, player compare, predicted "
                "starting minutes and a transfer planner. Available on the "
                "web, iOS and Android."
            ),
        ),
        (
            "Is GoalIQ free?",
            (
                "Yes. Clean sheet odds and fixture difficulty are free, on the web "
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


def fdr_grid_html(c: dict) -> str:
    head = "".join(f'<th scope="col" class="num">GW{g}</th>' for g in c["gws"])
    rows = []
    for r in c["fdr_rows"]:
        cells = []
        for fx in r["cells"]:
            if fx is None:
                cells.append('<td class="num">-</td>')
            else:
                cells.append(
                    f'<td class="num"><span class="fdr fdr{fx["fdr"]}" '
                    f'title="{escape(fx["opponent"])} ({fx["venue"]})">'
                    f'{escape(fx["opponent_short"])} {fx["fdr"]}</span></td>'
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
        f"<caption>Model fixture difficulty (1 easiest, 5 hardest) for the next "
        f"{len(c['gws'])} gameweeks, with opponent and average. Sorted by easiest run.</caption>"
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
    # → Organization + sameAs VAIN virallisiin kanaviin (Play, App Store, X).
    org = {
        "@context": "https://schema.org",
        "@type": "Organization",
        "@id": ORG_ID,
        "name": "GoalIQ",
        "url": BASE + "/",
        "description": (
            "GoalIQ makes FPL (Fantasy Premier League) tools - clean sheet "
            "odds and fixture difficulty, rate my team with a captain pick, "
            "and price watch free, plus player expected points (xP), the "
            "captain ranker, differentials and a transfer planner on GoalIQ "
            "Premium - powered by a Dixon-Coles + machine-learning match model "
            "with a public, pre-match-logged prediction track record. Built by "
            "an independent developer in Finland. Analytics, not betting."
        ),
        "logo": BASE + "/assets/brand/goaliq-appicon-512.png",
        "sameAs": [PLAY_URL, APPSTORE_URL, X_URL],
    }
    app = {
        "@context": "https://schema.org",
        "@type": "SoftwareApplication",
        "name": "GoalIQ: FPL Assistant",
        "operatingSystem": "Android, iOS",
        "applicationCategory": "SportsApplication",
        "description": (
            "Free FPL assistant and football prediction app. Free FPL tools: "
            "clean sheet odds and fixture difficulty, rate my team with a "
            "captain pick, and price watch. GoalIQ Premium adds player expected "
            "points (xP) per gameweek, the captain ranker, differentials and "
            "a transfer planner. Also predicts any match - "
            "win probability, expected goals (xG) and the most likely score - "
            "using a Dixon-Coles model with an expected-goals ensemble. "
            "Analytics, not betting."
        ),
        "url": BASE + "/",
        "downloadUrl": [PLAY_URL, APPSTORE_URL],
        "author": {"@id": ORG_ID},
        "offers": [
            {"@type": "Offer", "name": "GoalIQ app (free download)",
             "price": "0", "priceCurrency": "USD"},
            {"@type": "Offer", "name": "GoalIQ Premium on the web, monthly",
             "price": "3.99", "priceCurrency": "EUR", "url": PRO_URL},
            {"@type": "Offer", "name": "GoalIQ Premium on the web, season (yearly)",
             "price": "25", "priceCurrency": "EUR", "url": PRO_URL},
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
            f"GoalIQ FPL clean sheet odds and fixture difficulty, "
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
            "clean sheet odds",
            "FDR",
        ],
    }
    return "".join(
        f'<script type="application/ld+json">\n{json.dumps(b, ensure_ascii=False, indent=1)}\n</script>\n'
        for b in (org, app, faq_ld, dataset)
    )


# ---------------------------------------------------------------------------
# 4. Sivu
# ---------------------------------------------------------------------------
# Kanoninen brändipaletti (goaliq-app/assets/brand/brand-tokens.md) - täsmähexit.
# Hero = tumma (Ink) + magenta, sisältö = vaalea (Cream/Paper) + ink-teksti.
CSS = """
  :root{ --magenta:#FF2E7E; --magenta-deep:#D6006E; --coral:#FF6A3D; --gold:#FFC93C; --gold-deep:#F4A800; --teal:#19E3D2; --ink:#0A0820; --ink2:#140F1E; --cream:#FFF6EC; --paper:#F6F4FF; --ink-muted:#54506B; --hero-muted:#C9C3DA; --line:#E7DDCF; }
  *{ box-sizing:border-box; }
  body{ margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif; background:var(--cream); color:var(--ink); line-height:1.6; font-size:17px; }
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
  .fdr{ display:inline-block; min-width:34px; padding:3px 8px; border-radius:8px; color:var(--ink); font-weight:700; text-align:center; font-size:13px; }
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

    title = "Free FPL Tools – Rate My Team, Captain Pick & Clean Sheet Odds | GoalIQ"
    meta_desc = (
        "Free FPL tools: clean sheet odds & FDR, rate my team with a captain pick, "
        "and price watch. Premium adds player xP and the captain ranker. "
        "Published track record. Not betting."
    )

    faq_html = "".join(
        f"<dt>{escape(q)}</dt><dd>{escape(a)}</dd>" for q, a in faq
    )

    stats = (
        '<div class="stat-row">'
        f'<div class="stat"><b>{fmt_pct(c["acc_pct_1x2"])}</b>'
        f'<span>correct results across {c["acc_n"]} completed predictions</span></div>'
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
<link rel="apple-touch-icon" sizes="180x180" href="/assets/brand/goaliq-apple-touch-180.png">

<meta property="og:type" content="website">
<meta property="og:title" content="Free FPL Tools – Rate My Team, Captain Pick & Clean Sheet Odds | GoalIQ">
<meta property="og:description" content="{meta_desc}">
<meta property="og:url" content="{CANONICAL}">
<meta property="og:image" content="{BASE}/assets/brand/goaliq-social-1200x630.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:site" content="@goaliqapp">
<meta name="twitter:title" content="Free FPL Tools – Rate My Team, Captain Pick & Clean Sheet Odds | GoalIQ">
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
    <a class="cta" href="{PRO_URL}" data-cta="nav">Open GoalIQ Premium</a>
  </div>
</header>

<main>
<article>

<section class="hero dark">
<div class="wrap">
<h1>Free FPL Tools: Clean Sheet Odds, Fixture Difficulty and More</h1>
<p class="lede">GoalIQ is a free FPL assistant built on a proven match model.
This page gives clean sheet probability and fixture difficulty for every
Premier League team, free and updated every gameweek. Rate my team, a captain
pick and price watch are free too; GoalIQ Premium adds player expected points (xP),
the captain ranker and a transfer planner.</p>
<p class="meta">Season {c["season"]}. Data updated {c["data_date"]}.
Gameweek {c["next_gw"]} starts {c["gw_label"]}.</p>

<div class="cta-row">
  <a class="cta" href="{PRO_URL}" data-cta="fpl">See the full xP dashboard on GoalIQ Premium</a>
  <a class="cta secondary" href="{PLAY_URL}">Google Play</a>
  <a class="cta secondary" href="{APPSTORE_URL}">App Store</a>
</div>
<p class="meta">One account, premium on web, iOS and Android.</p>
<p class="note">Free download. Predict any fixture yourself in the app.</p>
</div>
</section>

<div class="wrap content">

<h2 id="track-record">The model publishes its prediction record</h2>
<p>{escape(tr[0])} {escape(tr[1])} {escape(tr[2])}</p>
{stats}
<p class="note">Source: GoalIQ prediction log, updated {c["acc_date"]}. The full
log, including every miss, is served live by the same model that produces the
tables below.</p>

<h2 id="clean-sheets">Gameweek {c["next_gw"]} clean sheet odds</h2>
<p>Model clean sheet probability for all 20 Premier League teams in
Gameweek {c["next_gw"]} ({c["gw_label"]}). FDR is GoalIQ's model fixture
difficulty for that match, 1 easiest to 5 hardest.</p>
{cs_table}
<p class="note">Pre-season projection: team strengths use 2024/25 and 2025/26
results as priors, and newly promoted sides use an empirical promoted-team
baseline. The numbers sharpen as {c["season"]} results arrive.</p>

<h2 id="fixture-difficulty">Fixture difficulty for the next six gameweeks</h2>
<p>GoalIQ's fixture difficulty rating per team and gameweek. Each cell shows the
opponent and the model FDR. A lower number is an easier fixture. This is
model-derived, not the official FPL difficulty.</p>
{fdr_grid}
<p class="legend">FDR scale: <span class="fdr fdr1">1</span>
<span class="fdr fdr2">2</span> <span class="fdr fdr3">3</span>
<span class="fdr fdr4">4</span> <span class="fdr fdr5">5</span>
(1 easiest, 5 hardest). Venue in cell tooltip: H home, A away.</p>

<aside class="upsell">
<h2 id="pro">Unlock xP, captain ranker and transfer planner with Premium</h2>
<p>GoalIQ Premium adds player expected points (xP) per gameweek, a captain ranker,
a transfer planner, differential picks, player compare and predicted starting
minutes, from the same match model as this page. Rate my team, a captain pick
and price watch are free on the web with your public FPL entry ID.</p>
<div class="cta-row">
  <a class="cta" href="{PRO_URL}" data-cta="fpl">Start GoalIQ Premium</a>
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
  <a class="cta" href="{PRO_URL}" data-cta="fpl">Open GoalIQ Premium: player xP and captain ranker</a>
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
        f'<div class="lbl">result accuracy across {c["acc_n"]} logged matches</div>'
    )
    proof = (
        f"The model logs every prediction before kickoff. "
        f"{fmt_pct(c['acc_pct_1x2'])} correct results across {c['acc_n']} matches played."
    )
    trust = (
        f"Built on a model with {fmt_pct(c['acc_pct_1x2'])} correct 1X2 results "
        f"across {c['acc_n']} logged matches, every prediction logged before kick-off."
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
    if new != s:
        INDEX_PATH.write_text(new, encoding="utf-8")
        return True
    return False


# ---------------------------------------------------------------------------
# 6. Sitemap lastmod
# ---------------------------------------------------------------------------
def update_sitemap(iso_date: str) -> bool:
    xml = SITEMAP_PATH.read_text(encoding="utf-8")
    entry = (
        "  <url>\n"
        f"    <loc>{CANONICAL}</loc>\n"
        f"    <lastmod>{iso_date}</lastmod>\n"
        "    <changefreq>weekly</changefreq>\n"
        "    <priority>0.9</priority>\n"
        "  </url>\n"
    )
    if CANONICAL in xml:
        # korvaa olemassa oleva fpl.html-blokki
        new = re.sub(
            r"  <url>\s*<loc>" + re.escape(CANONICAL) + r"</loc>.*?</url>\n",
            entry,
            xml,
            flags=re.S,
        )
    else:
        new = xml.replace("</urlset>", entry + "</urlset>")
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
    html_out = render_page(c)
    OUT_PATH.write_text(html_out, encoding="utf-8")
    sitemap_changed = update_sitemap(c["iso_date"])
    index_changed = update_index(c)

    print("=" * 64)
    print("FPL-LANDING BAKE OK")
    print("=" * 64)
    print(f"  fpl.html          : {len(html_out)} merkkiä")
    print(f"  sitemap.xml       : {'päivitetty' if sitemap_changed else 'ei muutosta'}")
    print(f"  index.html        : {'accuracy-markerit päivitetty' if index_changed else 'ei muutosta'}")
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
    print("  git add fpl.html sitemap.xml")
    print('  git commit -m "geo(fpl): FPL-landing data-refresh"')
    print("  git push")


if __name__ == "__main__":
    main()
