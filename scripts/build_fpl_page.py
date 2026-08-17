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

# Tama moduuli ajetaan MOLEMMILLA tavoilla: `python -m scripts.build_fpl_page`
# (accuracy-log.yml) ja `python scripts/build_fpl_page.py` (fpl-page-refresh.yml).
# Jalkimmaisessa sys.path[0] on scripts/, jolloin `scripts.*` ei resolvoidu ilman
# tata — sama bootstrap kuin build_prediction_pages.py:ssa.
if str(Path(__file__).resolve().parent.parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Pending-predikaatti JAETTUNA: sama saanto API:lle ja generoiduille sivuille.
from src.models.accuracy import is_pending as acc_is_pending  # noqa: E402

from scripts.mobile_css import (  # noqa: E402
    MOBILE_BLOCK_COLS,
    MOBILE_COLS_JS,
    MOBILE_CSS,
    MOBILE_GW_COLS,
)
from scripts.slugs import slug as _slug  # noqa: E402
from scripts.build_fpl_phase0 import map_name  # noqa: E402

# #38: PostHog cookieless site-analytiikka (persistence=memory -> ei evasteita,
# ei consent-banneria; ei PII:ta). Sama projekti kuin appi + pro-web (427890);
# client-avain on julkinen by design (sama avain SPA-bundlessa).
POSTHOG_SNIPPET = """<!-- PostHog (#38): cookieless site analytics - persistence=memory, no cookies, no PII -->
<script>
!function(t,e){var o,n,p,r;e.__SV||(window.posthog=e,e._i=[],e.init=function(i,s,a){function g(t,e){var o=e.split(".");2==o.length&&(t=t[o[0]],e=o[1]),t[e]=function(){t.push([e].concat(Array.prototype.slice.call(arguments,0)))}}(p=t.createElement("script")).type="text/javascript",p.async=!0,p.src=s.api_host+"/static/array.js",(r=t.getElementsByTagName("script")[0]).parentNode.insertBefore(p,r);var u=e;for(void 0!==a?u=e[a]=[]:a="posthog",u.people=u.people||[],u.toString=function(t){var e="posthog";return"posthog"!==a&&(e+="."+a),t||(e+=" (stub)"),e},u.people.toString=function(){return u.toString(1)+".people (stub)"},o="capture identify alias people.set people.set_once set_config register register_once unregister opt_out_capturing has_opted_out_capturing opt_in_capturing reset isFeatureEnabled onFeatureFlags getFeatureFlag getFeatureFlagPayload reloadFeatureFlags group updateEarlyAccessFeatureEnrollment getEarlyAccessFeatures getActiveMatchingSurveys getSurveys onSessionId".split(" "),n=0;n<o.length;n++)g(u,o[n]);e._i.push([i,s,a])},e.__SV=1)}(document,window.posthog||[]);
/* 1 Aug 2026: capture_pageview added, persistence NOT changed.
   $pageview was missing entirely, so PostHog Web Analytics showed
   goaliq.app near zero despite real traffic (the same bug was fixed for
   pro.goaliq.app on 25 Jul but the fix never spread here).
   persistence:'memory' + identified_only STAYS: privacy.html promises a
   cookieless setup and names it as the reason the page has no cookie
   banner. This therefore counts PAGE LOADS, not unique visitors, since
   uniques would need a persistent identifier and thus a banner. */
posthog.init('phc_ASmq5P9R5goGTDxze3GkXHJqU6RsvMCNqunSVBMgGkn7',{api_host:'https://us.i.posthog.com',persistence:'memory',autocapture:false,person_profiles:'identified_only',capture_pageview:true});
posthog.register({platform:'web',source_app:'goaliq-static'});
posthog.capture('web_landing_viewed',{page:location.pathname});
</script>"""

# #56: Pro CTA -klikkimittaus (pro_cta_clicked, propit location + page) - delegoitu
# listener, ei blokkaa navigaatiota, ei PII:ta, cookieless-moodi ennallaan.
# 2.8.2026: sama snippet liittaa pro.goaliq.app-linkkeihin lahdetagin (src/srcp),
# jonka SPA lukee pro_page_viewed-eventtiin -> saapumisaste per CTA-paikka.
# Raw-string, koska tagays sisaltaa regex-kenoviivoja.
CTA_TRACK_SNIPPET = r"""<!-- #56: Pro CTA click metric (PostHog pro_cta_clicked) - non-blocking, no PII, still cookieless -->
<script>
document.addEventListener('click', function (e) {
  var a = e.target && e.target.closest ? e.target.closest('a[data-cta]') : null;
  if (a && window.posthog) { posthog.capture('pro_cta_clicked', {location: a.getAttribute('data-cta'), page: location.pathname}); }
});
/* 2 Aug 2026 arrival attribution: goaliq.app runs persistence:'memory' and
   pro.goaliq.app runs localStorage+cookie, so distinct_id does NOT carry
   across the domains. Pro links get a non-identifying source tag that the
   SPA reads into its pro_page_viewed event. No cookie, no PII. */
(function () {
  var links = document.querySelectorAll('a[data-cta]');
  for (var i = 0; i < links.length; i++) {
    var a = links[i], href = a.getAttribute('href');
    if (!href) continue;
    try {
      var u = new URL(href, location.href);
      if (u.hostname !== 'pro.goaliq.app' || u.searchParams.has('src')) continue;
      u.searchParams.set('src', a.getAttribute('data-cta'));
      u.searchParams.set('srcp', location.pathname.replace(/^\/|\.html$/g, '') || 'index');
      a.setAttribute('href', u.toString());
    } catch (err) { /* virheellinen href - jata linkki ennalleen */ }
  }
})();
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
# 27.7: oma domain jaetun *.onrender.com-vyohykkeen tilalle. DNA:n nimipalvelu
# palautti NXDOMAINin koko vyohykkeelle -> operaattorin kayttajilta kaatui koko
# tuotepinta. api.goaliq.app on CF-proxyn takana, joten onrender.com-nimea ei
# tarvitse selvittaa missaan vaiheessa.
API_BASE = "https://api.goaliq.app"   # #85: accuracy-Datasetin distribution

# FDR-väriasteikko GoalIQ:n kanonisesta brändipaletista (brand-tokens.md,
# täsmähexit, EI approksimaatioita): 1 helpoin = Teal → Gold → Gold Deep →
# Coral → 5 vaikein = Magenta Deep. Tekstiväri kontrastin mukaan (1-4 ink,
# 5 valkoinen) - arvot CSS:ssä.
# 26.7 CLASSIC: FDR_COLORS poistettu — lämpökartta ei ole enää käytössä
# (ks. cs_cell_class/fdr_cell_class). Vaikeus kannetaan luvun painolla.


# ---------------------------------------------------------------------------
# 1. Data
# ---------------------------------------------------------------------------
def _strength_window_label(c: dict) -> str:
    """Fit-ikkuna ARTEFAKTISTA, ei kovakoodattuna.

    14.8: sivulla luki "2024/25 and 2025/26" kun renderoity artefakti oli
    jo ['2526','2627']. Metodiseloste on juuri se rivi jonka tarkka lukija
    tarkistaa, ja se oli vanhentunut hiljaa — kovakoodattu vuosiluku ei liiku
    kun malli refitataan. Tuntematon muoto palauttaa yleisen sanamuodon eika
    arvaa vuosia.
    """
    src = str(c.get("team_strength_source") or "")
    seasons = re.findall(r"'(\d{4})'", src)
    if not seasons:
        return "recent Premier League"
    def pretty(s: str) -> str:
        return f"20{s[:2]}/{s[2:]}"
    labels = [pretty(x) for x in seasons]
    if len(labels) == 1:
        return labels[0]
    return " and ".join([", ".join(labels[:-1]), labels[-1]])


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
    # 27.7 HORISONTTILAAJENNUS: teams[].fixtures sisältää nyt KOKO KAUDEN, ja
    # kaukorivit (tier="far") EIVÄT kanna cs_pct-kenttää — se on kontraktin
    # rakenteellinen rehellisyysrajoite, ei unohdus
    # (goaliq-app/cos-reports/horizon-extension-contract-2026-07-27.md).
    #
    # Tämä sivu lukee cs_pct:tä ehdoitta viidessä kohdassa (CS-taulu, FDR-grid,
    # JSON-LD, meta-description), joten se KAATUI KeyErroriin heti kun
    # projektio-JSON regeneroitiin. Havaittu accuracy-log-ajon punaisena
    # 27.7 16:57 UTC — "Page-build health (fail loud)" teki työnsä.
    #
    # Staattinen sivu näyttää LÄHIHORISONTIN (kontrakti §6: fpl.html tulee
    # horisonttiominaisuuteen viimeisenä), joten suodatus tehdään tässä
    # YHDESSÄ paikassa eikä viidessä kutsukohdassa erikseen. Kun sivu joskus
    # saa GW-välivalitsimen, tämä on se rivi joka poistetaan.
    #
    # Defensiivinen molempiin suuntiin: vanha payload ilman tier-kenttää
    # käyttäytyy täsmälleen kuten ennen (kaikki rivit läpi).
    def _near_only(team: dict) -> dict:
        fx = [
            f for f in team.get("fixtures", [])
            if f.get("tier", "near") == "near" and f.get("cs_pct") is not None
        ]
        return {**team, "fixtures": fx}

    # teams_all = koko kausi (kaukolohkoja varten), teams = lähihorisontti
    # (yksityiskohtainen CS%-grid). Kaksi eri esitystä samasta datasta, eri
    # tarkkuuslupauksella.
    teams_all = fpl["teams"]
    teams = [_near_only(t) for t in teams_all]
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

    # ------------------------------------------------------------------
    # 27.7 KAUKOHORISONTTI, 6 GW:n lohkokeskiarvoina.
    #
    # Miksi lohkot eikä 32 saraketta: koko kauden taulukko olisi lukukelvoton
    # puhelimessa. Ja lohkot kertovat sen mitä kaukokalenterista OIKEASTI
    # luetaan — missä swingit ovat — eivät desimaaleja joita malli ei voi
    # luvata GW30:lle.
    #
    # Miksi palvelimella renderöitynä eikä välivalitsimena: tämä on SEO-pinta.
    # Taulukko on indeksoitavaa sisältöä; JS:llä rakennettu ei ole. Naiivi
    # pariteetti SPA:n kanssa maksaisi sivun tärkeimmällä ominaisuudella
    # vuorovaikutuksesta jota tämän sivun yleisö ei ole tullut hakemaan.
    # Suunnittelutyökalu elää SPA:ssa ja appissa.
    #
    # VAIN FDR, EI CS%: kaukoriveillä ei ole cs_pct-kenttää lainkaan
    # (kontraktin rakenteellinen rehellisyysrajoite).
    # ------------------------------------------------------------------
    far_blocks: list[tuple[int, int]] = []
    far_rows: list[dict] = []
    all_far = [
        f for t in teams_all for f in (t.get("fixtures") or [])
        if (f.get("tier") or "near") == "far"
    ]
    if all_far:
        lo, hi = min(f["gw"] for f in all_far), max(f["gw"] for f in all_far)
        far_blocks = [(s, min(s + 5, hi)) for s in range(lo, hi + 1, 6)]
        for t in teams_all:
            cells = []
            for a, b in far_blocks:
                fx = [
                    f for f in (t.get("fixtures") or [])
                    if a <= f["gw"] <= b and (f.get("tier") or "near") == "far"
                ]
                cells.append(
                    {"avg_fdr": sum(f["fdr"] for f in fx) / len(fx), "n": len(fx)}
                    if fx else None
                )
            vals = [c["avg_fdr"] for c in cells if c]
            far_rows.append({
                "team": t["name"],
                "cells": cells,
                "avg_fdr": sum(vals) / len(vals) if vals else 99.0,
            })
        far_rows.sort(key=lambda r: r["avg_fdr"])

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
        "far_blocks": far_blocks,
        "far_rows": far_rows,
        "far_basis_label": (fpl.get("meta") or {}).get("far_basis_label") or "",
        # 14.8: fit-ikkuna kontekstiin, jotta metodiseloste ei ole
        # kovakoodattu. Ilman tata rivia _strength_window_label putoaa
        # varasanamuotoon ja sivu menettaa juuri ne vuodet jotka tarkka
        # lukija tarkistaa.
        "team_strength_source": (fpl.get("meta") or {}).get("team_strength_source") or "",
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
        # 1.8.2026 rehellisyyskorjaus: luku on laskettu TOTEUTUNEEN tuloksen
        # mukaan (accuracy.py: actual_outcome != "draw"), ei sen mukaan mitä
        # malli ennusti. Malli nimeää todennäköisemmän voittajan joka ottelussa,
        # joten "kun malli nimesi voittajan" antoi ymmärtää valikoinnin jota ei
        # ole. Sama sanamuoto kuin WC-sivulla, joka kuvasi tämän alusta oikein.
        (
            f"In the {c['acc_dec_n']} matches that did not end in a draw, the model "
            f"called the result right {fmt_pct(c['acc_pct_dec'])} of the time "
            f"({c['acc_dec_c']} of {c['acc_dec_n']})."
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
                "that builds the best valid 15 around your must-have players, "
                "a pre-season draft rater (no team ID needed), price watch and "
                "the full xG/xA/xGI leaderboard for every player "
                "with data, a filterable player stats table with shots, "
                "shots in the box and key passes, "
                "are free, and GoalIQ Premium adds an interactive team manager "
                "with a gameweek planner, player expected points (xP), the "
                "captain ranker, chip timing for the best Wildcard, Bench Boost, "
                "Triple Captain and Free Hit windows, transfer plans that chain "
                "1 to 2 moves with hits priced in, an edge mode with rank-aware "
                "picks for your mini-league, a player value ranking, a DefCon "
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
                "must-have players, the model builds the best valid 15 around "
                "them), price watch, a season-long Beat the model scoreboard "
                "(log your calls before the deadline and they get graded "
                "against the model's every gameweek), the season race "
                "against the model's own squad, which is locked before every "
                "deadline and scored with official FPL points, and Catch your rival "
                "(how likely you are to close the gap to anyone in your "
                "mini-league with the gameweeks left), a watchlist for the "
                "players you are deciding on, the "
                "full xG/xA/xGI leaderboard for every player with data, a "
                "filterable player stats table with shots, shots in the box "
                "and key passes, the "
                "top three of the value and DefCon lists, and "
                "shareable image cards of the clean sheet outlook and price "
                "watch tables on the web. GoalIQ "
                "Premium: an interactive team manager (formations, bench swaps, "
                "captaincy, a GW1 to GW6 gameweek planner with each player's "
                "opponent per week), player expected points (xP), the captain "
                "ranker, transfer suggestions with one-tap apply to your "
                "planned squad, player value (xP per million) for the top 50 with position and team filters, showing the scoring rate per 90 minutes and expected minutes separately so a high rate on low minutes reads as a bench risk and not a bargain, a live DefCon "
                "panel that tracks your own squad against the threshold while "
                "a gameweek is being played (web), the full DefCon "
                "(defensive contribution) leaderboard, goalkeeper "
                "rotation pairs, differentials, a round-by-round breakdown of where "
                "the gap to the model came from (captaincy, bench points and "
                "autosubs) with a decision journal of the calls you made "
                "differently, the players that actually close the gap to your "
                "mini-league rival, player compare for up to four "
        "players and predicted "
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
            # Mobiili (a): Date ja Competition piiloon kapealla naytolla.
            # Competition-suodatin on taulukon ylapuolella ja rivit ovat
            # uusin ensin, joten kumpikaan tieto ei katoa sivulta — ja
            # jaljelle jaa nelja saraketta jotka ovat itse asia:
            # ottelu, veikkaus, tulos, osui/ei. Taulukko oli 1202px = 3,1 x
            # puhelimen leveys; Date yksin oli 102px.
            f'<td class="num m-hide">{escape(date_txt)}</td>'
            f'<td class="m-hide">{escape(COMP_NAMES.get(code, code))}</td>'
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
    # 10.8: `void` (siirretty/peruttu ottelu) pois — TAMA SUODATIN ON ERI KUIN
    # accuracy.pending_rows, ja juuri siksi se jai ensin korjaamatta: sama
    # lista rakennetaan kahdesti, API:lle ja tälle sivulle. Ilman tata riviä
    # web-taulu olisi nayttanyt neljä 29.7. POSTPONED-ottelua karjessa senkin
    # jalkeen kun mobiili oli jo korjaantunut.
    pending = [e for e in preds if acc_is_pending(e)]
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
            f'<td class="m-hide">{escape(COMP_NAMES.get(code, code))}</td>'
            f'<td class="team">{escape(e.get("home_team", ""))} v {escape(e.get("away_team", ""))}</td>'
            f'<td><strong>{pick_sym}</strong> {escape(pick_name)}'
            f'<span class="rec-pct">{_pick_pct(e)}</span></td>'
            # "Logged" on todiste ennen kickoffia, mutta kick-off-sarake
            # kertoo saman asian rivilta; kapealla naytolla toinen riittaa.
            f'<td class="num m-hide">{escape(logged)}</td>'
            # Status-sarake toistaa lohkon otsikon ("Upcoming: logged,
            # awaiting result") jokaisella rivilla. Kapealla naytolla se vei
            # 124px eli kolmanneksen ruudusta ilman uutta tietoa.
            f'<td class="num m-hide"><span class="rec-pending">awaiting result</span></td>'
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
            '<thead><tr><th scope="col">Kick-off</th>'
            '<th scope="col" class="m-hide">Competition</th>'
            '<th scope="col">Match</th><th scope="col">Pick</th>'
            '<th scope="col" class="m-hide">Logged</th>'
            '<th scope="col" class="m-hide">Status</th></tr></thead>'
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
        "color:inherit;border-radius: 0;padding:6px 14px;font-size:13px;"
        "font-weight:600;cursor:pointer;}"
        ".rec-filter.on{background:var(--rec-on-bg,transparent);"
        "border-color:var(--rec-on-line,#B68235);color:var(--rec-on-fg,#8C6428);}"
        ".rec-scroll{overflow-x:auto;overflow-y:auto;max-height:560px;"
        "-webkit-overflow-scrolling:touch;border:1px solid rgba(128,128,128,.3);"
        "border-radius: 0;}"
        ".rec-scroll table{width:100%;border-collapse:collapse;min-width:640px;}"
        ".rec-scroll th,.rec-scroll td{text-align:left;padding:8px 10px;"
        "border-bottom:1px solid rgba(128,128,128,.2);font-size:14px;}"
        # 28.7 TELETEXT: tama lohko injektoidaan KAHTEEN sivuun joilla on eri
        # paletti (fpl.html tumma, predictions.html classic-vaalea), joten
        # yksikaan kovakoodattu vari ei kelpaa molempiin: amber on vaalealla
        # 1.9:1 ja #007A6C tummalla 2.4:1. Arvot tulevat nyt sivun omasta
        # :root-lohkosta var()-tokeneina, ja FALLBACK on classic — eli
        # predictions.html sailyy ennallaan ilman etta sita kosketaan.
        # 26.7 CLASSIC (tausta): nämä värit olivat kovakoodattuja stringiin,
        # joten kolme token-ajoa eivät nähneet niitä (var()-vaihto ei osu
        # literaaliin). Vihreä #0A9E75 ja magenta-miss #D6006E olivat sivun
        # viimeiset paletin ulkopuoliset värit. Uudet: osuma = teal tekstinä
        # (designin "voitot"), huti = coral (designin "pudotukset"), pending
        # = kulta. Kaikki AA-kontrastissa cream-pohjalla.
        ".rec-scroll th{position:sticky;top:0;background:var(--rec-thead-bg,#EAE9E9);font-size:12px;"
        "font-weight:700;text-transform:uppercase;letter-spacing:.05em;color:var(--rec-thead-fg,#54506B);}"
        ".rec-scroll td.team{font-weight:600;white-space:nowrap;}"
        ".rec-scroll .num{white-space:nowrap;font-variant-numeric:tabular-nums;}"
        ".rec-hit{color:var(--rec-hit,#007A6C);font-weight:800;}"
        ".rec-miss{color:var(--rec-miss,#C4441A);font-weight:800;}"
        ".rec-note{font-size:13px;opacity:.7;margin:10px 0 0;}"
        ".rec-subhead{font-size:18px;margin:26px 0 4px;}"
        ".rec-pending{color:var(--rec-pending,#8C6428);font-weight:700;font-size:12px;"
        "white-space:nowrap;}"
        ".rec-pct{color:var(--rec-pct,#54506B);font-variant-numeric:tabular-nums;}"
        "</style>"
        + by_comp_html(c)
        + f'<div class="rec-filters" role="group" aria-label="Filter by competition">{filter_btns}</div>'
        + '<div class="rec-scroll"><table>'
        + "<caption style=\"caption-side:bottom;font-size:13px;opacity:.7;"
        + "text-align:left;padding:8px 2px;\">Every graded GoalIQ pre-match "
        + "prediction, newest first. Logged before kick-off, no edits afterwards.</caption>"
        + '<thead><tr><th scope="col" class="m-hide">Date</th>'
        + '<th scope="col" class="m-hide">Competition</th>'
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


def _turnover_by_model_team() -> dict[str, dict]:
    """model_team -> luottamustiedot.

    NIMIEN NORMALISOINTI ON PAKOLLINEN: tama sivu kayttaa FPL:n pitkia nimia
    ("Leeds United", "Tottenham Hotspur", "Brighton & Hove Albion"), artefakti
    lyhyita. Suora join olisi osunut 17/20 ja jattanyt kolme joukkuetta tyhjaksi
    NAYTTAMATTA virhetta. map_name on sama normalisoija jota builderit kayttavat.
    """
    p = ROOT / "data" / "team_confidence.json"
    if not p.exists():
        return {}
    doc = json.loads(p.read_text(encoding="utf-8"))
    return {t["model_team"]: t for t in doc["teams"]}


def cs_table_html(c: dict) -> str:
    conf = _turnover_by_model_team()
    rows = []
    hits = 0
    for r in c["cs_rows"]:
        fdr = r["fdr"]
        t = conf.get(map_name(r["team"]))
        if t:
            hits += 1
        if t and t.get("is_promoted"):
            # 14.8 kaksi korjausta yhdessa:
            # (a) "no Premier League record" oli VAARA Ipswichista (se pelasi
            #     PL:aa 24/25 ja on osa mitattua nousijabaselinea);
            # (b) tyopoydalla merkinta oli paljas "new" ja merkitys vain
            #     `title=`-attribuutissa, jota ei nae kosketuslaitteella eika
            #     nappaimistolla — sama tooltip-ansa joka puri 11.8 (`vs crowd`
            #     -yksikko oli tooltipissa). Nyt sana kantaa merkityksen itse.
            churn = ('<span title="Promoted: runs on a measured '
                     'promoted-side baseline, not a rating of its own">'
                     'baseline</span>')
            sub = "baseline rating"
        elif t and t.get("minutes_churn_pct") is not None:
            churn = f'{t["minutes_churn_pct"]:.0f}%'
            sub = f'{t["minutes_churn_pct"]:.0f}% turnover'
        else:
            churn = "&ndash;"
            sub = ""
        # Sarake on .m-hide (5. sarake ei mahdu 390px:aan). "Show all columns"
        # tuo sen takaisin, mutta se on kaksi tapahtumaa liian kaukana luvusta
        # jota kukaan ei viela osaa etsia — ja puhelin on FPL-liikenteen
        # paapinta. Alarivi antaa saman luvun ilman saraketta ja katoaa kun
        # sarake palautetaan (body.cols-all .m-only), joten lukua ei nayteta
        # kahdesti kummassakaan tilassa.
        sub_html = (f'<span class="m-only m-sub">{escape(sub)}</span>'
                    if sub else "")
        rows.append(
            "<tr>"
            f'<td class="team">{escape(r["team"])}{sub_html}</td>'
            f'<td class="num">{fmt_pct(r["cs_pct"])}</td>'
            f'<td>{escape(r["opponent"])} ({r["venue"]})</td>'
            f'<td class="num fdr {fdr_cell_class(fdr)}">{fdr}</td>'
            f'<td class="num m-hide">{churn}</td>'
            "</tr>"
        )
    # Nolla osumaa = nimien normalisointi hajosi. Sarake taynna viivoja nayttaa
    # "ei dataa" eika vialta, joten se ei kaadu itsestaan.
    if c["cs_rows"] and not hits:
        raise SystemExit("cs_table: luottamusdata ei osunut yhteenkaan "
                         "joukkueeseen — nimien normalisointi on rikki")
    return (
        '<div class="scroll"><table>'
        f"<caption>Model clean sheet probability for every Premier League team, "
        f"Gameweek {c['next_gw']}, {c['season']} season. Sorted by clean sheet chance. "
        f"Squad turnover is the share of last season's minutes played by players "
        f"who have since left; the model is fitted on results, so it prices a "
        f"squad by what it did rather than by who is in it now.</caption>"
        "<thead><tr>"
        '<th scope="col">Team</th><th scope="col" class="num">Clean sheet %</th>'
        '<th scope="col">Next opponent</th><th scope="col" class="num">FDR</th>'
        '<th scope="col" class="num m-hide">Squad turnover</th>'
        "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></div>"
    )


# 26.7 CLASSIC: lämpökarttatäyttö POISTETTU. Aiemmin (#148) solu sai jatkuvan
# CS%-tintin; uusi ilme kieltää lämpökartan eksplisiittisesti — vaikeus
# kannetaan LUVUN painolla ja värillä, ei solun taustalla, jotta numerot
# pysyvät sivun äänekkäimpänä asiana. Sama kaava kuin SPA:n FreeView.svelte
# (csCellClass/fdrCellClass) -> pinnat eivät eriydy.
#
# Kynnykset ovat vanhan skaalan ankkureita (44 = gold, 20 = coral), joten
# tulkinta ei muutu. Väri EI ole ainoa signaali — paino kulkee mukana, joten
# rivi luetaan myös värisokeana ja mustavalkotulosteessa.
CS_EASY_MIN = 44.0
CS_HARD_MAX = 20.0


def cs_cell_class(cs_pct: float) -> str:
    """'' | 'is-easy' | 'is-hard' clean sheet -todennäköisyydestä."""
    if cs_pct >= CS_EASY_MIN:
        return "is-easy"
    if cs_pct <= CS_HARD_MAX:
        return "is-hard"
    return ""


def fdr_cell_class(fdr: int) -> str:
    """Sama logiikka FDR 1-5:lle (1 = helpoin)."""
    if fdr <= 2:
        return "is-easy"
    if fdr >= 4:
        return "is-hard"
    return ""


def _pred_slug(s: str) -> str:
    """Ottelusivujen slug — SAMA funktio kuin generaattorilla, ei kopio kaavasta.

    5.8.2026: tama oli oma re.sub-rivinsa, ja kun ottelusivujen kaava korjattiin
    translitteroivaksi (#229-SEO), naista soluista olisi tullut 404-linkkeja.
    Kahdennus poistettiin — drift on nyt rakenteellisesti mahdoton.
    """
    return _slug(s)


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


def far_grid_html(c: dict) -> str:
    """Kaukohorisontti 6 GW:n lohkokeskiarvoina. Tyhjä jos dataa ei ole.

    Palvelimella renderöity ja indeksoitava — ei JS:ää. Vain FDR: kaukoriveillä
    ei ole cs_pct:tä, ja se on kontrakti eikä puute.
    """
    if not c.get("far_rows") or not c.get("far_blocks"):
        return ""
    # Mobiili (a): kolme lahinta lohkoa nakyviin, loput piiloon kapealla
    # naytolla. Kaukohorisontti on selailua, ja GW31-38 ei ole se mita
    # puhelimella avattu linkki tulee katsomaan.
    head = "".join(
        f'<th scope="col" class="num{" m-hide" if i >= MOBILE_BLOCK_COLS else ""}">'
        f"GW{a}-{b}</th>"
        for i, (a, b) in enumerate(c["far_blocks"])
    )
    rows = []
    for r in c["far_rows"]:
        cells = []
        for i, cell in enumerate(r["cells"]):
            m = " m-hide" if i >= MOBILE_BLOCK_COLS else ""
            if not cell:
                # Ei otteluita lohkossa. Viiva eikä 0 — tyhjä ei ole "helppo".
                cells.append(f'<td class="num{m}">-</td>')
            else:
                cls = fdr_cell_class(cell["avg_fdr"])
                # n tooltippiin: 6 GW:n lohkossa voi olla tuplaviikkoja tai
                # blankkeja, ja keskiarvo yksin ei kerro kumpaa.
                cells.append(
                    f'<td class="num {cls}{m}" title="{cell["n"]} fixtures">'
                    f'{cell["avg_fdr"]:.1f}</td>'
                )
        rows.append(
            f'<tr><th scope="row">{r["team"]}</th>{"".join(cells)}</tr>'
        )
    label = c.get("far_basis_label") or (
        "Fixture difficulty only, based on today's ratings, and it will move "
        "as the season plays."
    )
    return (
        '<h2 id="long-range">Long-range fixture difficulty</h2>\n'
        f'<p class="muted">{label} Lower is easier. Each column averages the '
        'model\'s difficulty over six gameweeks, so what you are reading here '
        'is where the swings are, not a precise number for any single match.</p>\n'
        '<div class="table-wrap"><table class="fdr-grid">\n'
        f'<thead><tr><th scope="col">Team</th>{head}</tr></thead>\n'
        f'<tbody>{"".join(rows)}</tbody></table></div>\n'
    )


def fdr_grid_html(c: dict) -> str:
    # Mobiili 9.8, Villen valinta (a): kapealla naytolla nakyvat vain Team +
    # kolme seuraavaa gameweekia + Avg. Kahdeksan sarakkeen ruudukko oli
    # 832px = 2,1 x puhelimen leveys, ja koska vieritys tapahtui sisemmassa
    # laatikossa, kayttaja ei huomannut etta loput sarakkeet ovat olemassa.
    # Leveilla naytoilla taulukko on tasmalleen entisellaan.
    head = "".join(
        f'<th scope="col" class="num{" m-hide" if i >= MOBILE_GW_COLS else ""}">'
        f"GW{g}</th>"
        for i, g in enumerate(c["gws"])
    )
    rows = []
    for r in c["fdr_rows"]:
        cells = []
        for i, fx in enumerate(r["cells"]):
            m = " m-hide" if i >= MOBILE_GW_COLS else ""
            if fx is None:
                cells.append(f'<td class="num{m}">-</td>')
            else:
                # #148: solussa vastustaja + venue + per-fixture CS% (pariteetti
                # mobiilin #144:n kanssa); FDR-luokka siirtyi tooltippiin.
                # #152: solu on linkki predict-pinnalle (mobiilin solu-tap-pariteetti).
                # 26.7 CLASSIC: ei taustatäyttöä — luokka värittää LUVUN.
                cls = cs_cell_class(float(fx["cs_pct"]))
                href = predict_cell_href(r["team"], fx["opponent"], fx["venue"])
                cells.append(
                    f'<td class="num {cls}{m}"><a class="fdr" href="{href}" '
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
        f"{len(c['gws'])} gameweeks, with opponent and venue. Easy fixtures "
        f"({CS_EASY_MIN:.0f}% or more) are picked out in gold, hard ones "
        f"({CS_HARD_MAX:.0f}% or less) in coral (model FDR in the cell tooltip). "
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
            "ranker, player value, a DefCon tracker, "
            "differentials, player compare for up to four players and transfer "
            "suggestions with apply on GoalIQ "
            "Premium - powered by a Dixon-Coles match model "
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
            "captain pick, price watch, and shareable image cards of the free "
            "tables on the web. GoalIQ Premium adds an interactive "
            "team manager with a GW1 to GW6 gameweek planner, player expected "
            "points (xP), the captain ranker, chip timing for Wildcard, Bench "
            "Boost, Triple Captain and Free Hit, transfer plans that chain 1 to "
            "2 moves, an edge mode with rank-aware picks, player value (xP per "
            "million) for the top 50 with position and team filters, showing "
            "the scoring rate per 90 minutes and expected minutes separately "
            "so a high rate on low minutes reads as a bench risk and not a "
            "bargain, xG "
            "leaders, a DefCon (defensive contribution) tracker, "
            "differentials and transfer suggestions with apply. On the web it "
            "also shows upcoming fixtures and league tables. Also predicts "
            "any match - win probability, expected goals (xG) and the most "
            "likely score - using a Dixon-Coles model. Analytics, not betting."
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
  /* 28 Jul TELETEXT. Values are exactly the same as in the landing page's
     :root block, pro-spa/theme.css and the app's lib/theme.ts.
     Measured contrasts against the --ink #0B0A09 base:
       --cream 17.70:1  --ink-muted 7.82:1  --amber 12.20:1
       --teal 10.85:1   --negative 8.52:1   --faint 5.33:1
     NOTE --magenta-deep is 3.31:1 on dark, i.e. BELOW AA: it is no longer
     a link or number color, only a mark. Links = teal, numbers = amber. */
  :root{ --coral:#FF8A5C; --gold:#F5C542; --gold-deep:#F5C542; --amber:#F5C542; --amber-deep:#F5C542; --teal:#2ED6C2; --ink:#0B0A09; --ink2:#141311; --cream:#F3F2F2; --paper:#1F1D1A; --ink-muted:#A8A29A; --hero-muted:#A8A29A; --faint:#8A847A; --line:rgba(243,242,242,0.24); --line-strong:rgba(243,242,242,0.40); --negative:#FF8A5C; --radius:0;
    /* Tokens for the shared record block (build_fpl_page.by_comp/record).
       predictions.html does NOT define these -> it gets the classic
       fallbacks. */
    --rec-thead-bg:#1F1D1A; --rec-thead-fg:#A8A29A; --rec-hit:#5FD97A;
    --rec-miss:#FF8A5C; --rec-pending:#F5C542; --rec-pct:#A8A29A;
    --rec-on-bg:#F5C542; --rec-on-line:#F5C542; --rec-on-fg:#0B0A09; }
  *{ box-sizing:border-box; }
  body{ margin:0; font-family:"IBM Plex Mono",ui-monospace,SFMono-Regular,Menlo,Consolas,monospace; background:var(--ink); color:var(--cream); line-height:1.6; font-size:17px; }
  h1,h2,h3,.brand{ font-family:"IBM Plex Mono",ui-monospace,SFMono-Regular,Menlo,Consolas,monospace; text-transform:uppercase; letter-spacing:-0.01em; }
  /* Base link rule: without this, links OUTSIDE the .content block (e.g.
     the mini league link in the .note paragraph) stay browser-default
     blue #0000EE. An element selector (0,0,1) loses to every class rule,
     so it only hits genuinely unstyled links. */
  a{ color:var(--teal); }
  .dark{ background:var(--ink); color:var(--cream); }
  .wrap{ max-width:960px; margin:0 auto; padding:0 20px; }
  .bar{ height:1px;background:var(--line); }
  .nav{ max-width:960px; margin:0 auto; padding:18px 20px; display:flex; align-items:center; justify-content:space-between; gap:12px; }
  .brand{ font-size:24px; font-weight:800; letter-spacing:.5px; }
  .brand a{ color:var(--cream); text-decoration:none; display:inline-flex; align-items:center; gap:0; }
  .brand span{ color:var(--amber); }
  .brand-icon{ margin-right:8px; width:26px; height:26px; border-radius:var(--radius); display:block; }
  .cta{ display:inline-block; background:transparent; color:var(--amber); border:1px solid var(--amber); text-decoration:none; padding:14px 24px; border-radius:var(--radius); font-weight:800; min-height:48px; }
  .cta:hover{ background:var(--amber); color:var(--ink); }
  .cta.secondary{ background:transparent; border:1px solid var(--line-strong); color:inherit; }
  .cta-row{ display:flex; flex-wrap:wrap; gap:12px; margin:26px 0 8px; }
  .hero{ padding:44px 0 52px; }
  .hero h1{ font-size:36px; line-height:1.15; margin:0 0 14px; color:var(--cream); }
  .hero .lede{ font-size:19px; color:var(--hero-muted); max-width:720px; }
  .hero .meta,.hero .note{ color:var(--hero-muted); }
  .meta{ font-size:14px; margin-top:10px; }
  .note{ color:var(--ink-muted); font-size:14px; }
  h2{ font-size:25px; margin:54px 0 10px; }
  .content{ padding-bottom:70px; }
  .content a{ color:var(--teal); }
  .content a.cta{ color:var(--amber); }
  .content a.cta.secondary{ color:var(--cream); }
  .scroll{ overflow-x:auto; -webkit-overflow-scrolling:touch; background:var(--paper); border:1px solid var(--line); border-radius:var(--radius); padding:4px 12px 10px; }
  /* 8 Aug (user report): the column is 960px, so even a wide screen did not
     show every table column. Tables may now escape the column and grow with
     the window; body text stays at 960. The table itself does not stretch
     as filler. */
  .scroll,.table-wrap,.rec-scroll{ width:min(96vw,1560px); margin-left:50%; transform:translateX(-50%); }
  .scroll>table,.table-wrap>table,.rec-scroll>table{ width:auto; min-width:min(100%,560px); margin:0 auto; }
  /* .table-wrap was unstyled: the FDR grid overflowed on narrow screens
     with no way to scroll. Same wrapper as everywhere else. */
  .table-wrap{ overflow-x:auto; -webkit-overflow-scrolling:touch; }
  table{ width:100%; border-collapse:collapse; min-width:560px; }
  caption{ caption-side:bottom; color:var(--ink-muted); font-size:13px; text-align:left; padding:10px 2px 4px; }
  th,td{ text-align:left; padding:10px 8px; border-bottom:1px solid var(--line); font-size:15px; }
  tbody tr:last-child td{ border-bottom:none; }
  th{ color:var(--ink-muted); font-weight:600; font-size:13px; }
  th.num,td.num{ text-align:right; font-variant-numeric:tabular-nums; white-space:nowrap; }
  td.team{ font-weight:700; white-space:nowrap; }
  /* 26 Jul CLASSIC: heatmap removed. Color and weight live in the NUMBER,
     not the cell background; weight travels with the color, so the column
     reads under color blindness too. Same formula as the SPA's FreeView
     (is-easy/is-hard). */
  .fdr{ display:inline-block; min-width:34px; text-align:center; font-size:13px; text-decoration:none; color:inherit; font-variant-numeric:tabular-nums; }
  /* .content a colors links magenta and beats .fdr on specificity
     (0,1,1 > 0,1,0) -> without this EVERY neutral cell would be magenta.
     Only ever found in a browser; the gates cannot see the cascade. */
  .content a.fdr{ color:inherit; }
  a.fdr:hover{ text-decoration:underline; }
  td.is-easy,td.is-easy .fdr,span.fdr.is-easy{ color:var(--amber); font-weight:600; }
  td.is-hard,td.is-hard .fdr,span.fdr.is-hard{ color:var(--negative); }
  .legend{ color:var(--ink-muted); font-size:14px; margin:8px 0 0; }
  .stat-row{ display:flex; flex-wrap:wrap; gap:14px; margin:18px 0; }
  .stat{ background:var(--paper); border:1px solid var(--line); border-radius:var(--radius); padding:16px 20px; flex:1 1 180px; }
  .stat b{ display:block; font-size:30px; color:var(--amber); font-variant-numeric:tabular-nums; }
  .stat span{ color:var(--ink-muted); font-size:14px; }
  .faq dt{ font-weight:700; margin-top:20px; }
  .faq dd{ margin:6px 0 0; }
  .toollist{ margin:14px 0 8px; padding-left:20px; }
  .toollist li{ margin:10px 0; }
  .toollist a{ font-weight:700; }
  .disclaimer{ border:1px solid var(--line); background:var(--paper); border-radius:var(--radius); padding:12px 16px; color:var(--ink-muted); font-size:14px; margin:26px 0 60px; }
  .upsell{ border:1px solid var(--line); background:var(--paper); border-radius:var(--radius); padding:24px 26px; margin:48px 0 6px; }
  .upsell h2{ margin:0 0 10px; }
  .upsell p{ margin:0 0 6px; }
  .upsell .cta-row{ margin:18px 0 4px; }
  .upsell .price-note{ color:var(--ink-muted); font-size:14px; margin:10px 0 0; }
  footer{ padding:30px 0 40px; font-size:14px; }
  footer .wrap{ color:var(--hero-muted); }
  /* Bug 26 Jul: this was var(--cream) = cream on a cream background -> 8
     footer links were COMPLETELY invisible (contrast 1.00). Leftover from
     the dark footer; the classic switch lightened the background but not
     this. */
  footer a{ color:var(--hero-muted); text-decoration:underline; }
  footer a:hover{ color:var(--amber); }
  @media (max-width:640px){ .hero h1{ font-size:29px; } .hero .lede{ font-size:17px; } .nav{ padding:14px 16px; } .hero{ padding:30px 0 40px; } }
  /* Narrow mobile: CTA buttons stack full width, a long label cannot overflow (#15) */
  @media (max-width:520px){
    .cta-row{ flex-direction:column; align-items:stretch; }
    .cta{ max-width:100%; text-align:center; }
  }
  html,body{ overflow-x:clip; }
""" + MOBILE_CSS




NOTES_PATH = ROOT / "data" / "fpl_notes.json"


def latest_articles_block(notes_doc: dict | None, limit: int = 1) -> str:
    """Etusivun "Latest from the model" -lohko (15.8.2026, Villen pyynto).

    MIKSI. Ville: FFScoutilla on etusivulla "latest articles" ja "featured
    article" jotka nakyvat heti kun saavut sivulle. Meilla muistiot olivat
    `/fpl/notes`-osoitteessa johon paasi vain alatunnisteen kautta — eli
    kirjoitettu sisalto oli kaytannossa nakymatonta.

    🔴 SIJAINTI KORJATTU 15.8 SAMANA PAIVANA. Laitoin lohkon ensin heron
    JALKEEN omaksi sectionikseen. Mitattu selaimella: `y = 1051 px`, eli palkki
    nakyi juuri ja juuri fold-rajalla ja sisalto ei lainkaan. Villen palaute:
    "en kylla vielakaan nae mitaan livena tosta" ja "se pitaa olla niin isosti
    esilla etta sivulle tulija huomaa sen heti".

    Curl nakisi sen, kayttaja ei. Se on ero jota ei voi ratkaista curlilla, ja
    siksi tama piti katsoa selaimella niin kuin lukija sen nakee.

    Lohko on nyt heron OIKEASSA PALSTASSA track record -kortin alla. Se paikka
    oli tyhjaa noin 600 px, eli paras mahdollinen kiinteisto oli kaytosta
    poissa. Yksi kortti, ei kolmea: featured-lohko joka kilpailee itsensa
    kanssa ei ole featured.

    Nayttaa uusimmat `limit` muistiota: otsikko, paivays ja ENSIMMAINEN
    kappale kokonaisena. Ei katkaisua kolmeen pisteeseen — leikattu virke on
    lupaus jota lohko ei pida, ja ensimmainen kappale on kirjoitettu
    kantamaan itsenaisesti.

    Tyhja tai puuttuva data -> tyhja merkkijono -> koko lohko jaa pois.
    """
    notes = ((notes_doc or {}).get("notes") or [])
    # 🔴 TASATILANNE RATKAISTAAN JARJESTYSNUMEROLLA. Pelkka paivays ei riita:
    # 15.8 kirjoitettiin kaksi muistiota samalle paivalle, vakaa lajittelu
    # sailytti alkuperaisen jarjestyksen ja etusivun nosto jai nayttamaan
    # AAMUN muistiota vaikka uudempi oli jo julkaistu. Mitattu fpl.html:sta.
    # Myohemmin lisatty voittaa saman paivan sisalla.
    notes = [
        n for _, n in sorted(
            enumerate(notes),
            key=lambda p: (str(p[1].get("date") or ""), p[0]),
            reverse=True,
        )
    ]
    kortit = []
    for n in notes[:limit]:
        paras = [x for x in (n.get("paragraphs") or []) if isinstance(x, str)]
        # Vain merkkijonokappaleet: muistio voi alkaa valiotsikko- tai
        # taulukkolohkolla, ja niiden str()-esitys olisi Python-dict etusivulla.
        if not paras or not n.get("title"):
            continue
        slug = escape(str(n.get("slug") or ""))
        kortit.append(
            '<a class="note-card" href="/fpl/notes#' + slug + '">'
            f'<span class="note-date">{escape(str(n.get("date") or ""))}</span>'
            f'<span class="note-title">{escape(str(n["title"]))}</span>'
            f'<span class="note-lede">{escape(str(paras[0]))}</span>'
            "</a>"
        )
    if not kortit:
        return ""
    return (
        f'<style>{NOTES_CSS}</style>'
        '<div class="note-list">' + "".join(kortit) + "</div>"
        '<p class="note-more"><a href="/fpl/notes">'
        "All notes from the model &#9656;</a></p>"
    )


NOTES_CSS = """
.note-list{display:flex;flex-direction:column;gap:10px}
a.note-card{display:block;padding:clamp(16px,2.2vw,22px);border:2px solid var(--amber);
background:var(--panel);text-decoration:none;color:inherit}
a.note-card:hover{background:var(--track)}
.note-date{display:block;font-size:.72rem;letter-spacing:.10em;
text-transform:uppercase;color:var(--amber);margin-bottom:10px}
.note-title{display:block;font-size:clamp(19px,2.2vw,25px);font-weight:800;
line-height:1.25;margin-bottom:10px}
.note-lede{display:block;font-size:.95rem;line-height:1.55;color:var(--muted)}
.note-more{margin:2px 0 0;font-size:.85rem;letter-spacing:.04em;
text-transform:uppercase}
"""


def team_news_block(xp: dict | None) -> str:
    """Tiivis team news -nosto fpl.html:aan (15.8.2026, Villen pyynto).

    MIKSI ETUSIVULLE. Ville kysyi kannattaako uutiset nayttaa etusivulla.
    Kannattaa: se on ainoa pinta joka muuttuu joka paiva deadlinejen valissa,
    eli ainoa jatkuva syy palata. Muut lohkot (CS%, FDR, track record) liikkuvat
    kerran kierroksessa tai harvemmin.

    MITA TASSA EI NAYTETA. Vain LUKUMAARAT ja kolme eniten omistettua nimea,
    ei koko taulukkoa. Perustelu on sama kuin muillakin nostoilla: etusivun
    tehtava on kertoa etta tieto on olemassa ja tuore, ei korvata sivua jolle
    se vie. Poissaolevien xP:ta ei nayteta tassakaan.

    Puuttuva tai tyhja data -> tyhja merkkijono, jolloin koko lohko jaa pois
    eika sivulle jaa otsikkoa ilman sisaltoa.
    """
    if not xp:
        return ""
    rows = []
    for r in list(xp.get("players") or []) + list(xp.get("excluded") or []):
        if (r.get("news") or "").strip() and r.get("chance_next") is not None:
            rows.append(r)
    if not rows:
        return ""

    def owned(r):
        try:
            return float(r.get("owned_pct") or 0.0)
        except (TypeError, ValueError):
            return 0.0

    n_out = sum(1 for r in rows if r.get("chance_next") == 0)
    n_doubt = len(rows) - n_out
    top = sorted(rows, key=owned, reverse=True)[:3]
    names = ", ".join(
        f'{escape(str(r.get("web_name", "")))} ({escape(str(r.get("team_short", "")))})'
        for r in top
    )
    return (
        '\n<h2 id="team-news">Team news right now</h2>\n'
        f'<p><strong>{n_out} players are ruled out and {n_doubt} are doubtful</strong> '
        "for the next deadline, taken from the official Fantasy Premier League "
        "status feed. Most owned among them: "
        f"{names}.</p>\n"
        '<p>The full list is free and sorted by ownership, and every doubtful '
        "player carries the model's projected points with the reduced chance of "
        "playing already priced in, so you can see what the doubt actually costs: "
        '<a href="/fpl/team-news">FPL team news</a>.</p>\n'
    )


def render_page(c: dict, xp: dict | None = None) -> str:
    faq = build_faq(c)
    team_news = team_news_block(xp)
    tr = track_record_sentences(c)
    jsonld = jsonld_blocks(c, faq)
    cs_table = cs_table_html(c)
    fdr_grid = fdr_grid_html(c)
    far_grid = far_grid_html(c)
    # 26.7 CLASSIC: legenda seuraa solujen kaavaa (kolme luokkaa, ei
    # jatkuvaa skaalaa) — legenda ja solu eivät saa kertoa eri tarinaa.
    cs_legend = " ".join(
        '<span class="fdr {cls}">{p}%</span>'.format(cls=cs_cell_class(p), p=p)
        for p in (10, 22, 34, 46, 58)
    )

    title = "Free FPL Tools: Rate My Team, Captain Pick & Clean Sheet Probability | GoalIQ"
    meta_desc = (
        "Free FPL tools: clean sheet probability & FDR, a filterable player "
        "stats table with shots and key passes, xG/xA/xGI leaders for "
        "every player, rate my team with a captain pick, "
        "fit checker, pre-season draft rater "
        "and price watch. Premium adds a team manager with gameweek planner, "
        "player xP, value ranking and a DefCon tracker. "
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
        f'<span>correct in matches that did not end in a draw '
        f'({c["acc_dec_c"]} of {c["acc_dec_n"]})</span></div>'
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
<!-- pro.goaliq.app is a single page app and its boot costs time. Opening the
     connection and DNS here means a click only pays for the download, not the
     handshake. No effect on this page. -->
<link rel="preconnect" href="https://pro.goaliq.app">
<link rel="preconnect" href="https://api.goaliq.app" crossorigin>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="preload" as="style" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600;700&display=swap" onload="this.rel='stylesheet'">
<noscript><link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600;700&display=swap" rel="stylesheet"></noscript>
<link rel="apple-touch-icon" sizes="180x180" href="/assets/brand/goaliq-apple-touch-180.png">

<meta property="og:type" content="website">
<meta property="og:title" content="Free FPL Tools: Rate My Team, Captain Pick & Clean Sheet Probability | GoalIQ">
<meta property="og:description" content="{meta_desc}">
<meta property="og:url" content="{CANONICAL}">
<meta property="og:image" content="{BASE}/assets/brand/goaliq-social-1200x630.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:site" content="@goaliqapp">
<meta name="twitter:title" content="Free FPL Tools: Rate My Team, Captain Pick & Clean Sheet Probability | GoalIQ">
<meta name="twitter:description" content="{meta_desc}">
<meta name="twitter:image" content="{BASE}/assets/brand/goaliq-social-1200x630.png">

{jsonld}
<meta name="theme-color" content="#0B0A09">
<style>{CSS}</style>
{POSTHOG_SNIPPET}
</head>
<body>
<header class="dark">
  <div class="bar"></div>
  <div class="nav">
    <div class="brand"><a href="./"><svg class="brand-icon" width="26" height="26" viewBox="0 0 44 44" role="img" aria-label="GoalIQ" focusable="false"><rect x="0" y="0" width="44" height="44" fill="#F5C542"/><text x="22" y="30" text-anchor="middle" font-family="IBM Plex Mono,ui-monospace,Consolas,monospace" font-size="20" font-weight="700" letter-spacing="-0.5" fill="#0B0A09">IQ</text></svg>Goal<span>IQ</span></a></div>
    <a class="cta" href="{PRO_TAB_URL}" data-cta="nav">Open GoalIQ Premium</a>
  </div>
</header>

<main>
<article>

<section class="hero dark">
<div class="wrap">
<h1>Free FPL Tools: Clean Sheet Probability, Fixture Difficulty and More</h1>
<p class="lede">GoalIQ is a free FPL assistant built on a match model with a
published, pre-match-logged track record.
This page gives clean sheet probability and fixture difficulty for every
Premier League team, free and updated every gameweek. Rate my team, a captain
pick and price watch are free too; GoalIQ Premium adds an interactive team
manager with a gameweek planner, player expected points (xP), the captain
ranker, player value, a DefCon tracker and transfer suggestions
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
GoalIQ Premium, free: one prize, decided by the mini-league table when the season ends.</p>
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

{team_news}<h2 id="clean-sheets">Gameweek {c["next_gw"]} clean sheet probabilities</h2>
<p>Model clean sheet probability for all 20 Premier League teams in
Gameweek {c["next_gw"]} ({c["gw_label"]}). FDR is GoalIQ's model fixture
difficulty for that match, 1 easiest to 5 hardest.</p>
{cs_table}
<p class="note">Pre-season projection: team strengths are fitted on
{_strength_window_label(c)} results, and newly promoted sides use an empirical
promoted-team baseline measured from recent promoted seasons. The numbers
sharpen as {c["season"]} results arrive.</p>

<h2 id="fixture-difficulty">Fixture difficulty for the next six gameweeks</h2>
<p>Clean sheet probability per team and gameweek. Each cell shows the opponent,
venue and the model's clean sheet probability for that match, so two fixtures in
the same FDR class no longer look identical. Easy runs stand out in gold and
hard ones in coral; there is no colour wash behind the numbers, because the
numbers are the point. Model FDR (1 easiest, 5 hardest) stays in the cell
tooltip. Model-derived, not the official FPL difficulty.</p>
{fdr_grid}
{far_grid}
<p class="legend">Clean sheet scale: {cs_legend}
(low CS% = hard fixture, high CS% = easy). H home, A away.</p>

<aside class="upsell">
<h2 id="pro">Unlock the full FPL toolkit with Premium</h2>
<p>GoalIQ Premium adds an interactive team manager (formations, bench swaps,
captaincy and a GW1 to GW6 gameweek planner showing each player's opponent
per week), player expected points (xP), a captain ranker, transfer suggestions
you can apply straight to your planned squad, a player value ranking (xP per
million), the full DefCon leaderboard with a gameweek-by-gameweek
breakdown, goalkeeper rotation pairs,
differential picks, player compare for up to four players and predicted
  starting minutes, from the
same match model as this page. Rate my team, a captain pick, price watch and
the top three of every leaderboard are free.</p>
<!-- REMOVE the free window after 2026-09-12 12:30 UTC: the CTA goes back to
     checkout and the first price note goes away. The notice sits above the CTA
     on purpose; the other way round the page offered a buy button directly
     above the sentence saying you do not need to pay yet. -->
<p class="price-note"><b>Premium is free on the web until the GW4 deadline on 12 September,
so GW1 to GW3. Create a free account and it's on. No card, nothing to cancel.</b></p>
<div class="cta-row">
  <a class="cta" href="{PRO_URL}" data-cta="fpl-freewindow">Get Premium free</a>
</div>
<p class="price-note">After 12 September it is €25 a year, which is under €2.10 a month, or
€3.99 a month. One subscription covers web, iOS and Android. Cancel anytime.
30-day money back on web purchases.</p>
</aside>

<!-- Career card discoverability. This is a free distribution tool, so the teal
     border separates it from the Premium upsell. Click tracking is delegated. -->
<aside class="upsell" style="border-color:var(--teal-ink);">
<h2 id="career-card">Your FPL Career Card - free, on one shareable image</h2>
<p>Best season, all-time points and your rank history on one card, built from
your public FPL entry ID. No login. Made for sharing with your mini-league.</p>
<div class="cta-row">
  <a class="cta" href="/career" data-cta="fpl-career">Build your career card</a>
</div>
</aside>

<!-- SPL keeps its own section. This page carries one restrained aside only, no
     SPL content mixed in with the FPL tools. Free by design, and the disclaimer
     line is part of the ethics framing set out on the SPL page. -->
<aside class="upsell" style="border-color:var(--teal-ink);">
<h2 id="spl-tools">Play RSL Fantasy too? Saudi Pro League tools, free</h2>
<p>Clean sheet probability, model fixture difficulty and expected points for the
official Saudi Pro League fantasy game, from the same match model. Goals-based
model (no xG feed exists for the SPL), labeled honestly. Independent data
tool; not affiliated with or paid by the SPL.</p>
<div class="cta-row">
  <a class="cta" href="https://pro.goaliq.app/spl" data-cta="spl-tools">Open the free SPL tools</a>
</div>
</aside>

<h2 id="creators">Using these numbers in your content?</h2>
<p>There's a creator program. Your code takes 30 percent off your audience's
first payment at the web checkout, and you keep earning on the renewals after
it. Everything on this page stays free to quote with or without it.</p>
<div class="cta-row">
  <a class="cta" href="/creators" data-cta="creators">Read the terms and apply</a>
</div>

<h2 id="methodology">Methodology</h2>
<p>A Dixon-Coles style match model, tau corrected, fitted on recent results
and the xG those matches produced.
Clean sheet probability comes from the score matrix: the chance the opponent
scores zero. Fixture difficulty is derived from win and clean sheet
probabilities, ranked across every team fixture of the season and bucketed
into five tiers. Fixture data comes from the official Premier League fantasy
API, with premierleague.com as the fixture source until the FPL game opens
for {c["season"]}.</p>

<h2 id="tools">More free FPL tools</h2>
<p>Every page below is built from the same model that powers this one, and each
one refreshes on the same schedule. No login, no paywall.</p>
<ul class="toollist">
  <li><a href="/fpl/best-captain">Captain picks for the next deadline</a>:
  every player ranked by expected points, not by last week's haul.</li>
  <li><a href="/fpl/model-xi">The model's own XI</a>: the squad our numbers
  would pick inside the budget, published before every deadline.</li>
  <li><a href="/fpl/differentials">Differentials under 10% ownership</a>:
  where the model disagrees with the crowd.</li>
  <li><a href="/fpl/price-changes">Price change watch</a>: who is close to
  rising or falling tonight.</li>
  <li><a href="/fpl/xg-leaders">xG, xA and xGI leaders</a>: the underlying
  numbers behind the point returns.</li>
  <li><a href="/fpl/defcon">DefCon leaders</a>: defensive contribution ranked
  under the current scoring rules.</li>
  <li><a href="/fpl/stats">Player stats</a>: shots, shots in the box, key
  passes, tackles and the rest of the raw numbers in one filterable table,
  per 90 or per start, with CSV export.</li>
  <li><a href="/fpl/defence">Defence profiles</a>: what each defence actually
  concedes, by pitch zone, plus headers faced and set-piece xG.</li>
  <li><a href="/fpl/club-best">Best player at every club</a>: each club's
  leading goalkeeper, defender, midfielder and forward by projected points,
  with the gap to that club's second option.</li>
  <li><a href="/fpl/team-news">Team news</a>: every player ruled out or
  doubtful, sorted by ownership, with what the model still projects a
  doubtful player to score over the horizon.</li>
  <li><a href="/fpl/notes">Notes from the model</a>: a short note each
  gameweek, only when the numbers say something worth saying, with every
  figure on a free page you can open.</li>
  <li>A page for every club, with its best players, who takes its penalties
  and corners, and a predicted XI: <a href="/fpl/club/arsenal">Arsenal</a>,
  <a href="/fpl/club/liverpool">Liverpool</a>,
  <a href="/fpl/club/bournemouth">Bournemouth</a> and the rest, linked from
  <a href="/fpl/club-best">best player at every club</a>.</li>
</ul>

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
  <a href="/fpl/best-captain">Captain picks</a> &middot;
  <a href="/fpl/model-xi">Model XI</a> &middot;
  <a href="/fpl/differentials">Differentials</a> &middot;
  <a href="/fpl/price-changes">Price changes</a> &middot;
  <a href="/fpl/xg-leaders">xG leaders</a> &middot;
  <a href="/fpl/defcon">DefCon leaders</a> &middot;
  <a href="/fpl/stats">Player stats</a> &middot;
  <a href="/fpl/defence">Defence profiles</a> &middot;
  <a href="/fpl/club-best">Best per club</a> &middot;
  <a href="/fpl/team-news">Team news</a> &middot;
  <a href="/fpl/notes">Notes</a> &middot;
  <a href="/fpl/club-best">Club pages</a> &middot;
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
{MOBILE_COLS_JS}
</body>
</html>
"""


# ---------------------------------------------------------------------------
# 5. Etusivun track record -markerit (index.html, homepage-update 4.7)
# ---------------------------------------------------------------------------
INDEX_PATH = ROOT / "index.html"
# Etusivun projektiotaulukon lähde (sama tiedosto jonka fpl-data-refresh
# rakentaa joka päivä) — taulukko oli aiemmin kovakoodattu, ks. xp_table_rows.
XP_PATH = ROOT / "data" / "fpl_xp_projections.json"
# Perustajan FPL-historia (scripts/build_founder_stats.py) — luvut samasta
# julkisesta entrystä johon etusivun teksti linkkaa.
FOUNDER_PATH = ROOT / "data" / "founder_entry.json"


def _load_json(path) -> dict | None:
    """Valinnainen datatiedosto: puuttuva tiedosto ei kaada sivubuildia."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def xp_table_rows(xp: dict, n: int = 4) -> str:
    """Etusivun "Live model projections" -taulukon rivit LIVE-datasta (1.8.2026).

    Tausta: taulukko oli kovakoodattu 24.7. value-ajosta samalla kun sen oma
    alaviite lupasi "refreshed daily · live numbers, not a mock season".
    Luvut olivat viikon vanhoja ja kärkirivillä oli James Garner, jonka FPL
    on sittemmin liputtanut loukkaantuneeksi (status i, 0 % pelitodennäköisyys)
    — eli etusivu suositteli pelaajaa jota ei voi pelauttaa.

    Siksi tässä on kaksi porttia, ei vain tuoreus:
      1. vain status 'a' (ei liputettuja) JA chance_next ei 0
      2. vain pelaajat joilla on PL-historia (data_basis == 'pl_history'),
         koska nousijoiden baseline-arviot eivät kuulu etusivun kärkeen
    """
    rows = [
        p for p in (xp.get("players") or [])
        if p.get("status") == "a"
        and p.get("chance_next") in (None, 100)
        and p.get("data_basis") == "pl_history"
        and isinstance(p.get("xp_horizon_total"), (int, float))
    ]
    rows.sort(key=lambda p: p["xp_horizon_total"], reverse=True)
    out = []
    for p in rows[:n]:
        out.append(
            '        <div class="mock-row">'
            f'<span class="mock-team">{escape(p["team_short"])}</span>'
            f'<span><span class="mock-name">{escape(p["web_name"])}</span> '
            f'<span class="mock-meta">&middot; {escape(p["pos"])}</span></span>'
            f'<span>&pound;{p["price"]:.1f}</span>'
            f'<span>{float(p.get("owned_pct") or 0):.1f}%</span>'
            f'<span class="mock-xp">{p["xp_horizon_total"]:.1f}</span></div>'
        )
    horizon = (xp.get("meta") or {}).get("horizon_gw")
    foot = (
        '        <div class="mock-foot">Model projections'
        + (f", next {horizon} gameweeks" if horizon else "")
        + " &middot; <strong>live numbers, not a mock season</strong></div>"
    )
    return "\n" + "\n".join(out + [foot]) + "\n      "


# ---------------------------------------------------------------------------
# "Every match that matters" -liigalohko (Villen havainto 15.8):
#   "goaliq.app sivuilla nayttaa brasileiro live now mutta ei esim
#    championship, la liga, eredivisie jotka kans live."
#
# Lohko oli KASIN kirjoitettua HTML:aa: `live-chip` oli kovakoodattu
# Brasileiroon ja saateteksti sanoi Championshipista, Eredivisiesta ja
# Primeira Ligasta "with their seasons kicking off in August" - lause joka oli
# tosi kun se kirjoitettiin ja vanhentui itsestaan sina paivana kun ne alkoivat.
#
# Tama on SAMA VIKALUOKKA kuin mobiilin etusivulla samana paivana: kovakoodattu
# liigalista jonka paivittaminen jaa ihmisen muistin varaan. Korjaus on sama:
# tila johdetaan datasta joka ajossa.
#
# FAIL-SOFT ON TAHALLINEN: jos fixture-haku ei onnistu (CI ilman verkkoa,
# API alhaalla), lohkoa EI kirjoiteta uusiksi. Vanha oikea teksti on parempi
# kuin uusi vaara, ja hiljainen "ei yhtaan live-liigaa" olisi vaara vaite.
# ---------------------------------------------------------------------------

LEAGUE_CHIPS = [
    ("ENG-Premier League", "Premier League"),
    ("ESP-La Liga-FD", "La Liga"),
    ("GER-Bundesliga-FD", "Bundesliga"),
    ("ITA-Serie A-FD", "Serie A"),
    ("FRA-Ligue 1-FD", "Ligue 1"),
    ("INT-Champions League", "Champions League"),
    ("BRA-Serie A", "Brasileirão"),
    ("ENG-Championship", "Championship"),
    ("NED-Eredivisie", "Eredivisie"),
    ("POR-Primeira Liga", "Primeira Liga"),
]

# Liiga on "live now" jos silla on ottelu talla ikkunalla.
#
# 🔴 IKKUNA ON KAPEA TAHALLAAN. Ensimmainen versio kaytti +7 vrk ja merkitsi
# Valioliigan liveksi 15.8, vaikka GW1 on 21.8 - kuuden paivan paassa. "Live
# now" on silloin valhe, ja se on tasan se vika joka tassa korjataan: lukija
# klikkaisi liigaa jolla ei ole yhtaan ottelua. 3 vrk taaksepain kattaa
# viikonlopun josta on jo pelattu, 2 eteenpain taman viikon kierroksen.
LIVE_BACK_DAYS = 3
LIVE_FWD_DAYS = 2


def _league_live_map(api_base: str = "https://api.goaliq.app") -> dict | None:
    """{liigakoodi: bool} tai None jos dataa ei saatu. None = ala koske lohkoon."""
    import datetime as _dt
    import json as _json
    import urllib.parse as _up
    import urllib.request as _ur

    today = _dt.date.today()
    lo = today - _dt.timedelta(days=LIVE_BACK_DAYS)
    hi = today + _dt.timedelta(days=LIVE_FWD_DAYS)
    out = {}
    for code, _ in LEAGUE_CHIPS:
        url = f"{api_base}/api/fixtures?league={_up.quote(code)}"
        # User-Agent on PAKOLLINEN: api.goaliq.app on Cloudflaren proxyn
        # takana ja se palauttaa Pythonin oletus-UA:lle 403. Sama vikaluokka
        # kuin ESPN-haussa (kirjattu muistiin: python-clientit torjutaan).
        req = _ur.Request(url, headers={"User-Agent": "goaliq-build/1.0"})
        try:
            with _ur.urlopen(req, timeout=25) as r:
                data = _json.loads(r.read().decode("utf-8"))
        except Exception:
            return None
        fx = data.get("fixtures") if isinstance(data, dict) else data
        live = False
        for f in (fx or []):
            d = str(f.get("date") or "")[:10]
            try:
                dd = _dt.date.fromisoformat(d)
            except ValueError:
                continue
            if lo <= dd <= hi:
                live = True
                break
        out[code] = live
    return out


def _leagues_block(live: dict) -> tuple[str, str]:
    """Palauta (grid_html, note_html) mitatusta live-tilasta."""
    chips = []
    live_names = []
    for code, name in LEAGUE_CHIPS:
        if live.get(code):
            live_names.append(name)
            chips.append(
                f'<div class="league-chip live-chip">{name} &middot; live now</div>')
        else:
            chips.append(f'<div class="league-chip">{name}</div>')
    grid = "".join(chips)

    if not live_names:
        note = ("Every league below is supported. None of them has a fixture "
                "in the next week.")
    elif len(live_names) == 1:
        note = f"{live_names[0]} is playing right now. The rest are supported and waiting on their next round."
    else:
        head = ", ".join(live_names[:-1])
        note = (f"{head} and {live_names[-1]} are playing right now. "
                "The rest are supported and waiting on their next round.")
    return grid, f'<p class="league-note">{note}</p>'


def update_index_leagues(api_base: str = "https://api.goaliq.app") -> bool:
    """Kirjoita liigaruudukko ja saateteksti mitatusta tilasta. False = ei muutosta."""
    if not INDEX_PATH.exists():
        return False
    live = _league_live_map(api_base)
    if live is None:
        print("      [liigat] fixture-hakua ei saatu -> lohko jatetaan ennalleen")
        return False
    grid, note = _leagues_block(live)
    s = INDEX_PATH.read_text(encoding="utf-8")
    new = re.sub(
        r"(<!-- GEN:LEAGUES-START -->).*?(<!-- GEN:LEAGUES-END -->)",
        lambda m: m.group(1) + grid + m.group(2), s, flags=re.S)
    new = re.sub(
        r"(<!-- GEN:LEAGUE-NOTE-START -->).*?(<!-- GEN:LEAGUE-NOTE-END -->)",
        lambda m: m.group(1) + note + m.group(2), new, flags=re.S)
    if new == s:
        return False
    INDEX_PATH.write_text(new, encoding="utf-8")
    n = sum(1 for v in live.values() if v)
    print(f"      [liigat] {n}/{len(LEAGUE_CHIPS)} liigaa live -> index.html")
    return True


def update_index(c: dict, xp: dict | None = None) -> bool:
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
    # Teletext-ticker (2 ticker-set-kopiota) samasta lähteestä kuin chipit —
    # kovakoodattuna se jäi jälkeen jokaisella bakella (P1 30.7).
    ticker = (
        f'<b>{c["acc_n"]} completed matches</b>\n      '
        f'<b class="t-amber">&#9612; {fmt_pct(c["acc_pct_1x2"])} correct results</b>'
    )
    new, n_ticker = re.subn(
        r"(<!-- GEN:ACC-TICKER-START -->).*?(<!-- GEN:ACC-TICKER-END -->)",
        lambda m: m.group(1) + ticker + m.group(2), new, flags=re.S)
    if n_ticker != 2:
        raise RuntimeError(
            f"index.html GEN:ACC-TICKER: odotettiin 2 markerilohkoa, löytyi {n_ticker}")
    # 1.8: WC-luku oli tickerissä ACC-TICKER-markerien ULKOPUOLELLA, eli se ei
    # päivittynyt tästä botista lainkaan. Oma markeri per-kilpailu-luvulle.
    wc = next((r for r in (c.get("by_comp") or []) if r["code"] == "WC"), None)
    if wc:
        wc_block = f'<b>World Cup 2026 &middot; {fmt_pct(wc["pct"])}</b>'
        new, n_wc = re.subn(
            r"(<!-- GEN:ACC-WC-START -->).*?(<!-- GEN:ACC-WC-END -->)",
            lambda m: m.group(1) + wc_block + m.group(2), new, flags=re.S)
        if n_wc != 2:
            raise RuntimeError(
                f"index.html GEN:ACC-WC: odotettiin 2 markerilohkoa, löytyi {n_wc}")
    # Perustajalohko: luvut samasta julkisesta entrystä johon teksti linkkaa
    # (scripts/build_founder_stats.py). "12 seasons" vanheni ennen joka kausi.
    fe = _load_json(FOUNDER_PATH)
    if fe and fe.get("seasons"):
        founder = (
            f'<a href="https://fantasy.premierleague.com/entry/{fe["entry_id"]}/history"'
            f' rel="noopener" data-cta="founder-entry">{fe["seasons"]} seasons,'
            f" anyone can check it</a>.\n"
            f'            My best finish is {fe["best"]["rank"]:,} ({fe["best"]["season"]}).'
            f' My worst is {fe["worst"]["rank"]:,} ({fe["worst"]["season"]}), the season I'
            f" stopped\n            updating my team in October."
        )
        new, n_f = re.subn(
            r"(<!-- GEN:FOUNDER-START -->).*?(<!-- GEN:FOUNDER-END -->)",
            lambda m: m.group(1) + founder + m.group(2), new, flags=re.S)
        if n_f != 1:
            raise RuntimeError(
                f"index.html GEN:FOUNDER: odotettiin 1 markerilohko, löytyi {n_f}")
    # "Live model projections" -taulukko: rivit tuoreesta xP-datasta, ei
    # kovakoodattuna. Ilman dataa markeri jätetään koskematta (ei tyhjennetä
    # taulukkoa sivulta jos builder ajetaan ilman xP-tiedostoa).
    if xp and xp.get("players"):
        new, n_xp = re.subn(
            r"(<!-- GEN:XP-TABLE-START -->).*?(<!-- GEN:XP-TABLE-END -->)",
            lambda m: m.group(1) + xp_table_rows(xp) + m.group(2), new, flags=re.S)
        if n_xp != 1:
            raise RuntimeError(
                f"index.html GEN:XP-TABLE: odotettiin 1 markerilohko, löytyi {n_xp}")
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
    # 15.8: team news paasivulle. Villen havainto: "https://goaliq.app/ en nae
    # mitaan uutisjuttua ... toi on se meidan paasivu" — olin laittanut lohkon
    # vain fpl.html:aan. Sama sisalto, sama artefakti, ei kovakoodattuja lukuja.
    articles_block = latest_articles_block(_load_json(NOTES_PATH))
    if articles_block:
        new, n_art = re.subn(
            r"(<!-- GEN:LATEST-ARTICLES-START -->).*?(<!-- GEN:LATEST-ARTICLES-END -->)",
            lambda m: m.group(1) + articles_block + m.group(2), new, flags=re.S)
        if n_art != 1:
            raise RuntimeError(
                f"index.html GEN:LATEST-ARTICLES: odotettiin 1 markerilohko, "
                f"loytyi {n_art}")

    news_block = team_news_block(xp)
    if news_block:
        new, n_news = re.subn(
            r"(<!-- GEN:TEAM-NEWS-START -->).*?(<!-- GEN:TEAM-NEWS-END -->)",
            lambda m: m.group(1) + news_block + m.group(2), new, flags=re.S)
        if n_news != 1:
            raise RuntimeError(
                f"index.html GEN:TEAM-NEWS: odotettiin 1 markerilohko, "
                f"loytyi {n_news}")

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
    xp = _load_json(XP_PATH)
    html_out = render_page(c, xp)
    OUT_PATH.write_text(html_out, encoding="utf-8")
    sitemap_changed = update_sitemap(c["iso_date"])
    index_changed = update_index(c, xp)
    # Liigalohko samaan ajoon: "live now" johdetaan fixtureista joka kerta,
    # eika jaa ihmisen muistin varaan (Villen havainto 15.8). Fail-soft:
    # epaonnistunut haku EI kirjoita lohkoa, jolloin vanha oikea teksti jaa.
    index_changed = update_index_leagues() or index_changed
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
