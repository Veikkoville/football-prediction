"""Ohjelmalliset ennustesivut (#119) — orgaanisen haun long-tail-jalanjälki.

Generoi data/prediction_log.json:sta (= #110-putken lokaamat PRE-MATCH-
ennusteet, sama julkinen malli + track record):

  predictions/{league}/index.html            per-liiga-hub ("this week")
  predictions/{league}/{home}-vs-{away}.html per-ottelu-sivu (VAIN 1X2-% +
                                             record-linkki; xG ja todennäköisin
                                             tulos ovat premiumia, ks. 2.8.
                                             vuotokorjaus rivillä ~333)

MIKSI prediction_log eikä live-API: sivun luku = TÄSMÄLLEEN se ennuste joka
on lukittu julkiseen track recordiin ("logged before kickoff") → sivu ja
record eivät voi erota, ja generointi ei kuormita Renderiä. Uniikki
rehellisyyskulma jota kilpailijoilla ei ole.

Vain TULEVAT ottelut (result=None, kickoff > now). Regen poistaa liigan
vanhentuneet ottelusivut (ei staleja ennusteita indeksissä). Hub-sivut ovat
pysyviä URL:eja (sitemap daily). predictions.html:n GEN:PRED-LEAGUES-markerit
täytetään livenä olevilla hubeilla.

Gambling-safe: predictions / win probability / model — EI betting/odds/tips.
STDLIB-ONLY (kuten build_fpl_page.py) → ajettavissa CI:ssä ilman pipiä.
Ajo: python -m scripts.build_prediction_pages   (accuracy-log.yml ajaa 3 h välein)
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from html import escape
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.models import accuracy as acc
from scripts.build_fpl_page import ROOT as _FP_ROOT, write_urlset
from scripts.mobile_css import MOBILE_COLS_JS, MOBILE_CSS
from scripts.slugs import fold_ascii, slug

# #119b: KAIKKI generoidut sivut (hubit + ottelusivut) omaan lapsi-sitemapiin,
# jonka sitemap.xml-index listaa. Wholesale-kirjoitus joka ajolla → poistuneet
# sivut putoavat sitemapista samassa ajossa kuin tiedostot siivotaan.
SITEMAP_PRED_PATH = _FP_ROOT / "sitemap-predictions.xml"
# #GSC-INDEX (9.8.2026): sitemapiin vain lahihorisontin ottelut.
#
# Mitattu 9.8.2026: sitemap tarjosi 1 924 URLia = KOKONAISET KAUDET (PL 380
# ottelua, kaukaisin 293 pv paassa eli toukokuussa 2027). GSC-tila oli 1 922
# "havaittu, ei indeksoitu" ja indeksoituja 20 — Google ei kayta
# indeksointibudjettia tuhanteen samankaltaiseen sivuun matalan auktoriteetin
# domainilla, ja suurin osa niista on otteluita joita kukaan ei viela hae.
#
# 30 pv eika 14: indeksointi vie paivia-viikkoja, joten 14 pv ei ehtisi
# indeksoitua ennen ottelua. 30 pv jattaa 197 URLia (-90 %) ja antaa
# jokaiselle sivulle aidon ikkunan nakya haussa ennen kickoffia.
#
# HUOM: tama karsii VAIN sitemapin. Kaikki sivut generoidaan ja ovat yha
# saavutettavissa, ja liigahubit linkittavat niihin — Google loytaa ne
# ryomimalla, ne eivat vain kilpaile budjetista etukateen.
SITEMAP_HORIZON_DAYS = 30

BASE = "https://goaliq.app"
# #121-GEO: kompakti publisher-node jokaiselle ottelusivulle - entiteetti-
# disambiguaatio pitkässä hännässä (pelkkä @id-viittaus ei resolvoidu sivun
# sisällä). sameAs vain aitoihin kanaviin (Villen vahvistamat 22.7).
ORG_PUBLISHER = {
    "@type": "Organization",
    "@id": BASE + "/#organization",
    "name": "GoalIQ",
    "url": BASE + "/",
    "sameAs": [
        "https://play.google.com/store/apps/details?id=com.veikkoville.goaliq",
        "https://apps.apple.com/app/id6780047163",
        "https://x.com/goaliqapp",
        "https://www.tiktok.com/@goaliqfpl",
        "https://www.instagram.com/goaliqfpl/",
    ],
}
OUT_ROOT = ROOT / "predictions"
PREDICTIONS_HTML = ROOT / "predictions.html"
LLMS_TXT = ROOT / "llms.txt"

# competition-koodi (prediction_log) → julkinen slug + näyttönimi.
# Big-5 + CL ovat valmiina: hub generoituu automaattisesti kun #110-lippu
# laajenee ja lokiin ilmestyy tulevia otteluita (elokuu).
LEAGUES: dict[str, dict] = {
    "BSA": {"slug": "brasileirao", "name": "Brasileirão Série A"},
    "PL": {"slug": "premier-league", "name": "Premier League"},
    "PD": {"slug": "la-liga", "name": "La Liga"},
    "BL1": {"slug": "bundesliga", "name": "Bundesliga"},
    "SA": {"slug": "serie-a", "name": "Serie A"},
    "FL1": {"slug": "ligue-1", "name": "Ligue 1"},
    "CL": {"slug": "champions-league", "name": "Champions League"},
}

# 5.8.2026 (#229-SEO, F1): feedin virallinen pitka nimi ei ole se muoto jolla
# kukaan hakee. "FC Internazionale Milano vs Udinese Calcio Prediction" ei osu
# kyselyyn "inter vs udinese prediction" — ja long-tail-ottelusivun koko
# olemassaolon syy on osua siihen kyselyyn. PL ja BSA nayttavat oikeilta vain
# koska feedin nimi sattuu olemaan lyhyt; konventiota ei ole.
#
# Kartta koskee VAIN naita neljaa liigaa (rakenteellinen takuu, ei sattuma):
# PL:n ja BSA:n URLit ovat olleet indeksoitavissa pisimpaan, eika niita saa
# liikuttaa. Puuttuva nimi -> feedin nimi sellaisenaan (ei kaadu), ja ajo
# emitoi kattavuusluvun — hiljainen puolikas kattavuus on tunnettu vikaluokka.
DISPLAY_NAME_COMPS = {"PD", "SA", "BL1", "FL1"}

DISPLAY_NAMES: dict[str, str] = {
    # La Liga (PD)
    "Athletic Club": "Athletic Bilbao",
    "CA Osasuna": "Osasuna",
    "Club Atlético de Madrid": "Atletico Madrid",
    "Deportivo Alavés": "Alaves",
    "Elche CF": "Elche",
    "FC Barcelona": "Barcelona",
    "Getafe CF": "Getafe",
    "Levante UD": "Levante",
    "Málaga CF": "Malaga",
    "RC Celta de Vigo": "Celta Vigo",
    "RC Deportivo La Coruña": "Deportivo La Coruna",
    "RCD Espanyol de Barcelona": "Espanyol",
    "Rayo Vallecano de Madrid": "Rayo Vallecano",
    "Real Betis Balompié": "Real Betis",
    "Real Madrid CF": "Real Madrid",
    "Real Racing Club de Santander": "Racing Santander",
    "Real Sociedad de Fútbol": "Real Sociedad",
    "Sevilla FC": "Sevilla",
    "Valencia CF": "Valencia",
    "Villarreal CF": "Villarreal",
    # Serie A (SA)
    "AC Milan": "AC Milan",
    "AC Monza": "Monza",
    "ACF Fiorentina": "Fiorentina",
    "AS Roma": "Roma",
    "Atalanta BC": "Atalanta",
    "Bologna FC 1909": "Bologna",
    "Cagliari Calcio": "Cagliari",
    "Como 1907": "Como",
    "FC Internazionale Milano": "Inter",
    "Frosinone Calcio": "Frosinone",
    "Genoa CFC": "Genoa",
    "Juventus FC": "Juventus",
    "Parma Calcio 1913": "Parma",
    "SS Lazio": "Lazio",
    "SSC Napoli": "Napoli",
    "Torino FC": "Torino",
    "US Lecce": "Lecce",
    "US Sassuolo Calcio": "Sassuolo",
    "Udinese Calcio": "Udinese",
    "Venezia FC": "Venezia",
    # Bundesliga (BL1)
    "1. FC Köln": "FC Koln",
    "1. FC Union Berlin": "Union Berlin",
    "1. FSV Mainz 05": "Mainz",
    "Bayer 04 Leverkusen": "Bayer Leverkusen",
    "Borussia Dortmund": "Borussia Dortmund",
    "Borussia Mönchengladbach": "Borussia Monchengladbach",
    "Eintracht Frankfurt": "Eintracht Frankfurt",
    "FC Augsburg": "Augsburg",
    "FC Bayern München": "Bayern Munich",
    "FC Schalke 04": "Schalke",
    "Hamburger SV": "Hamburger SV",
    "RB Leipzig": "RB Leipzig",
    "SC Freiburg": "Freiburg",
    "SC Paderborn 07": "Paderborn",
    "SV 07 Elversberg": "Elversberg",
    "SV Werder Bremen": "Werder Bremen",
    "TSG 1899 Hoffenheim": "Hoffenheim",
    "VfB Stuttgart": "Stuttgart",
    # Ligue 1 (FL1)
    "AJ Auxerre": "Auxerre",
    "AS Monaco FC": "Monaco",
    "Angers SCO": "Angers",
    "ES Troyes AC": "Troyes",
    "FC Lorient": "Lorient",
    "Le Havre AC": "Le Havre",
    "Le Mans FC": "Le Mans",
    "Lille OSC": "Lille",
    "OGC Nice": "Nice",
    "Olympique Lyonnais": "Lyon",
    "Olympique de Marseille": "Marseille",
    "Paris FC": "Paris FC",
    "Paris Saint-Germain FC": "Paris Saint-Germain",
    "RC Strasbourg Alsace": "Strasbourg",
    "Racing Club de Lens": "Lens",
    "Stade Brestois 29": "Brest",
    "Stade Rennais FC 1901": "Rennes",
    "Toulouse FC": "Toulouse",
}

# 24.7 redesign: sama brändi-ilme kuin fpl.html — Space Grotesk display-fontti,
# magenta-raita + tumma ink-header (gradient), cream-body, paper-kortit.
CSS = """
.brand-icon{width:22px;height:22px;display:inline-block;vertical-align:-4px;margin-right:8px;flex:none;}
:root{--teal:#2ED6C2;--teal-ink:#2ED6C2;
--ink:#F3F2F2;--ink2:#141311;--cream:#0B0A09;--paper:#1F1D1A;--card:#141311;
--muted:#A8A29A;--hero-muted:#A8A29A;--line:rgba(243,242,242,0.24);--radius:0;
/* 1 Aug 2026: magenta was removed from the palette. These tokens were in
   use as var() references but missing from :root, so they are defined here
   explicitly. */
--amber:#F5C542;--gold:#F5C542;--gold-deep:#F5C542;--ember:#FF8A5C;}
*{box-sizing:border-box;margin:0;padding:0;}
body{background:var(--cream);color:var(--ink);font-family:"IBM Plex Mono",ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;line-height:1.6;}
h1,h2,h3,.brand{font-family:"IBM Plex Mono",ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;}
/* Base link rule: without this the "public track record" link in the .rec
   box stayed browser-default blue #0000EE. An element selector loses to
   every class rule, so it only hits unstyled links. */
a{color:var(--teal);}
.dark{background:var(--cream);color:var(--ink);}
.wrap{max-width:820px;margin:0 auto;padding:0 20px;}
.bar{height:1px;background:var(--line);}
nav{display:flex;align-items:center;justify-content:space-between;padding:18px 0;
font-size:14px;}
nav a{text-decoration:none;color:var(--ink);font-weight:600;}
.brand{font-size:21px;font-weight:700;letter-spacing:.5px;}
.brand span{color:var(--amber);}
.nav-cta{background:transparent;color:var(--gold-deep,#F5C542);border:1px solid var(--gold,#F5C542);padding:8px 16px;border-radius:0;}
.nav-cta:hover{background:rgba(245,197,66,0.14);}
.hero{padding:8px 0 36px;}
.hero h1{color:var(--ink);}
.hero .lede{color:var(--hero-muted);margin-bottom:0;}
.hero .lede strong{color:var(--ink);}
h1{font-size:30px;line-height:1.2;margin:16px 0 10px;letter-spacing:-0.02em;}
.lede{color:var(--muted);margin-bottom:22px;}
.content{padding-top:26px;}
.card{background:var(--card);border:1px solid var(--line);border-radius:var(--radius);
padding:18px 20px;margin-bottom:14px;}
/* 26 Jul CLASSIC: 12px filled bar -> 4px line. The look allows color as a
   line, not as a fill; the percentages are numbers in the legend. */
.probbar{display:flex;height:4px;overflow:hidden;margin:10px 0 6px;}
.probbar .h{background:var(--amber);} .probbar .d{background:rgba(243,242,242,0.24);}
.probbar .a{background:var(--teal);}
.legend{display:flex;justify-content:space-between;font-size:12px;color:var(--muted);}
.big{font-size:15px;}
.stat-row{display:flex;flex-wrap:wrap;gap:12px;margin:14px 0;}
.stat{background:var(--paper);border:1px solid var(--line);border-radius:var(--radius);
padding:12px 16px;flex:1 1 140px;}
.stat b{display:block;font-size:26px;color:var(--amber);
font-family:"IBM Plex Mono",ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
font-variant-numeric:tabular-nums;}
.stat span{color:var(--muted);font-size:12px;}
.rec{border-left:4px solid var(--teal);background:var(--paper);border-radius:0;
padding:10px 14px;font-size:13px;color:var(--muted);margin:16px 0;}
.cta-row{display:flex;flex-wrap:wrap;gap:12px;margin:22px 0;}
.btn{background:transparent;color:var(--gold-deep,#F5C542);border:1px solid var(--gold,#F5C542);font-weight:700;padding:12px 22px;
border-radius:0;text-decoration:none;font-size:14px;}
.btn:hover{background:rgba(245,197,66,0.14);}
.btn.ghost{background:transparent;color:var(--ink);border:1px solid var(--line);}
.mrow{display:flex;align-items:center;justify-content:space-between;gap:10px;
padding:12px 0;border-bottom:1px solid var(--line);}
.mrow:last-child{border-bottom:none;}
.mrow a{color:var(--teal);font-weight:700;text-decoration:none;}
.mrow .meta{color:var(--muted);font-size:12px;}
.pick{color:var(--teal-ink);font-weight:700;font-size:13px;white-space:nowrap;}
footer{border-top:1px solid var(--line);margin-top:36px;padding:22px 0 34px;
color:var(--muted);font-size:13px;}
footer a{color:var(--muted);}
.note{color:var(--muted);font-size:12px;margin:18px 0;}
@media (max-width:520px){.cta-row{flex-direction:column;align-items:stretch;}
.btn{text-align:center;}}
""" + MOBILE_CSS

# theme-color + Google Fonts (preconnect minimoi latauskustannuksen; sama
# family-merkkijono kuin fpl.html:ssä → yksi fonttivälimuisti koko sivustolle)
HEAD_BRAND = (
    '<meta name="theme-color" content="#0B0A09">\n'
    '<link rel="preconnect" href="https://fonts.googleapis.com">\n'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n'
    # 26.7 PERF: preload+onload, ei render-blocking stylesheetiä — FCP ei
    # odota kolmannen osapuolen CSS:ää. noscript = varmistus.
    '<link rel="preload" as="style" href="https://fonts.googleapis.com/css2?family='
    'IBM+Plex+Mono:wght@400;500;600;700&display=swap" onload="this.rel=\'stylesheet\'">\n'
    '<noscript><link href="https://fonts.googleapis.com/css2?family='
    'IBM+Plex+Mono:wght@400;500;600;700&display=swap" rel="stylesheet"></noscript>\n'
)

# Header avautuu tässä; _page sulkee </header>-tagin hero-lohkon jälkeen.
NAV = (
    '<header class="dark"><div class="bar"></div><div class="wrap"><nav>'
    '<a class="brand" href="/"><svg class="brand-icon" width="22" height="22" viewBox="0 0 44 44" role="img" aria-label="GoalIQ" focusable="false"><rect x="0" y="0" width="44" height="44" fill="#F5C542"/><text x="22" y="30" text-anchor="middle" font-family="IBM Plex Mono,ui-monospace,Consolas,monospace" font-size="20" font-weight="700" letter-spacing="-0.5" fill="#0B0A09">IQ</text></svg>Goal<span>IQ</span></a>'
    '<span><a href="/predictions">All predictions</a> · '
    '<a class="nav-cta" href="https://pro.goaliq.app/">Try it live</a></span>'
    "</nav></div>"
)

DISCLAIMER = (
    "GoalIQ model predictions are statistical estimates for fun and analysis, "
    "not betting advice, and not a gambling service."
)

FOOTER = (
    '<footer>© 2026 GoalIQ · <a href="/predictions">Football predictions</a> · '
    '<a href="/fpl.html">Free FPL tools</a> · '
    '<a href="/privacy.html">Privacy</a><br>'
    'GoalIQ: FPL Assistant is free on '
    '<a href="https://play.google.com/store/apps/details?id=com.veikkoville.goaliq">'
    "Google Play</a> and the "
    '<a href="https://apps.apple.com/app/id6780047163">App Store</a>. '
    "Premium is 3.99 €/month or 25 €/year. "
    "One subscription on web, iOS "
    "and Android.<br>" + DISCLAIMER + "</footer>\n"
)


# 5.8.2026 (#229-SEO, F2): slug-kaava asuu nyt scripts/slugs.py:ssa, koska
# build_fpl_page linkittaa naille sivuille ja tarvitsee TASMALLEEN saman
# kaavan. Nimi _slug sailytetaan, koska tests/ importtaa sen.
_slug = slug


def _fmt_pct(x: float) -> str:
    return f"{round(x * 100)}%"


def _fmt_kickoff(iso: str) -> str:
    """Ottelun aika — ja rehellisyys silloin kun sita ei ole.

    1.8.2026: 403/1926 tulevalla ottelulla (20 %) kickoff on tasan 00:00, mika
    on fixture-feedin paikkamerkki kaudelle jonka aikatauluja ei ole viela
    lyoty lukkoon. Sivu tulosti sen muodossa "Sat 19 Sep 2026, 00:00 UTC" eli
    esitti paikkamerkin faktana. Keskiyon ottelu on teoriassa mahdollinen
    (BSA pelaa myohaan), mutta "aika vahvistamatta" ei ole koskaan vaara
    vaite, kun taas vaara kellonaika on.
    """
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except Exception:
        return iso
    if dt.hour == 0 and dt.minute == 0:
        return dt.strftime("%a %d %b %Y") + ", kick-off time to be confirmed"
    return dt.strftime("%a %d %b %Y, %H:%M UTC")


SOCIAL_IMAGE = f"{BASE}/assets/brand/goaliq-social-1200x630.png"


def _social_meta(title: str, desc: str, canonical: str) -> str:
    """OG + Twitter Card, sama muoto ja sama kuva-asset kuin fpl.html:ssä
    (build_fpl_page.py). Ilman näitä sivu renderöityy jaettaessa paljaana
    linkkinä ilman otsikkoa, kuvausta tai kuvaa."""
    t, d = escape(title), escape(desc)
    return (
        '<meta property="og:type" content="article">\n'
        f'<meta property="og:title" content="{t}">\n'
        f'<meta property="og:description" content="{d}">\n'
        f'<meta property="og:url" content="{canonical}">\n'
        f'<meta property="og:image" content="{SOCIAL_IMAGE}">\n'
        '<meta property="og:image:width" content="1200">\n'
        '<meta property="og:image:height" content="630">\n'
        '<meta property="og:site_name" content="GoalIQ">\n'
        '<meta name="twitter:card" content="summary_large_image">\n'
        '<meta name="twitter:site" content="@goaliqapp">\n'
        f'<meta name="twitter:title" content="{t}">\n'
        f'<meta name="twitter:description" content="{d}">\n'
        f'<meta name="twitter:image" content="{SOCIAL_IMAGE}">\n'
    )


def _page(title: str, desc: str, canonical: str, hero: str, body: str,
          jsonld: list[dict]) -> str:
    ld = "".join(
        '<script type="application/ld+json">\n'
        + json.dumps(b, ensure_ascii=False, indent=1)
        + "\n</script>\n"
        for b in jsonld
    )
    return (
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n"
        '<meta charset="UTF-8" />\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0" />\n'
        f"<title>{escape(title)}</title>\n"
        f'<meta name="description" content="{escape(desc)}" />\n'
        f'<link rel="canonical" href="{canonical}" />\n'
        # 29.7 (#225-SEO): OG/Twitter myös ohjelmallisille sivuille. Konventio
        # oli olemassa vain build_fpl_page.py:ssä, joten 180 ottelusivua +hub
        # renderöityi jaettaessa paljaana linkkinä. Arvot johdetaan samoista
        # _page()-parametreista, ei uutta dataa.
        f"{_social_meta(title, desc, canonical)}"
        # 27.7: koko ikonisetti myös ohjelmallisille ottelusivuille (ks.
        # build_fpl_longtail.py, sama perustelu).
        '<link rel="icon" href="/favicon.ico" sizes="any">\n'
        '<link rel="icon" type="image/png" sizes="32x32" href="/assets/brand/goaliq-favicon-32.png">\n'
        '<link rel="icon" type="image/png" sizes="48x48" href="/assets/brand/goaliq-favicon-48.png">\n'
        '<link rel="apple-touch-icon" sizes="180x180" href="/assets/brand/goaliq-apple-touch-180.png">\n'
        f"{HEAD_BRAND}"
        f"{ld}"
        f"<style>{CSS}</style>\n"
        "</head>\n<body>\n"
        f"{NAV}\n"
        f'<div class="wrap hero">\n{hero}\n</div>\n</header>\n'
        f'<div class="wrap content">\n{body}\n'
        f"{FOOTER}"
        "</div>\n" + MOBILE_COLS_JS + "</body>\n</html>\n"
    )


def _upcoming_by_comp(log: dict, now: datetime) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for e in log["predictions"]:
        comp = e.get("competition")
        if comp not in LEAGUES or e.get("result") is not None:
            continue
        kickoff = e.get("kickoff") or ""
        try:
            ko = datetime.fromisoformat(kickoff.replace("Z", "+00:00"))
        except Exception:
            continue
        if ko <= now:
            continue
        if e.get("p_home") is None:
            continue
        out.setdefault(comp, []).append(e)
    for rows in out.values():
        rows.sort(key=lambda e: e.get("kickoff") or "")
    return out


def _within_horizon(entry: dict, now: datetime) -> bool:
    """Onko ottelu SITEMAP_HORIZON_DAYS:n sisalla? Ks. vakion perustelu."""
    try:
        ko = datetime.fromisoformat((entry.get("kickoff") or "").replace("Z", "+00:00"))
    except Exception:
        return False
    return (ko - now).days <= SITEMAP_HORIZON_DAYS


def _apply_display_names(by_comp: dict[str, list[dict]]) -> tuple[set, set]:
    """Kirjoita nayttonimet SISAANLUKUUN, ei renderoijiin.

    Tama on tarkoituksella ainoa kohta jossa nimi vaihtuu: slug, title, H1,
    description ja JSON-LD lukevat kaikki samasta home_team/away_team-kentasta,
    joten ne eivat voi erota toisistaan. Jos kartta ajettaisiin renderoijissa,
    yhden pinnan unohtaminen tuottaisi URLin ja otsikon jotka eivat vastaa.

    Muokkaa kopiota (dict(e)) — prediction_log.json:n loki on julkisen track
    recordin lahde eika sita saa kirjoittaa uusiksi nayttosyista.
    """
    mapped: set[str] = set()
    unmapped: set[str] = set()
    for comp, rows in by_comp.items():
        if comp not in DISPLAY_NAME_COMPS:
            continue
        for i, e in enumerate(rows):
            new = dict(e)
            for key in ("home_team", "away_team"):
                raw = e[key]
                if raw in DISPLAY_NAMES:
                    mapped.add(raw)
                    new[key] = DISPLAY_NAMES[raw]
                else:
                    unmapped.add(raw)
            rows[i] = new
    return mapped, unmapped


def _attach_confidence(by_comp: dict[str, list[dict]]) -> int:
    """Liita luottamuslippu RAAOILLA mallinimilla ennen nayttonimien vaihtoa.

    Nimi vaihtuu _apply_display_names():ssa, joten renderoijassa e["home_team"]
    on jo nayttonimi eika osuisi artefaktiin. Lippu jaisi silloin pois
    NAYTTAMATTA virhetta — sama vikaluokka kuin slug-tormays, jota vastaan
    tassa tiedostossa on jo oma tarkistuksensa.

    Vain liputetut naytetaan (nousija / korkea vaihtuvuus). Pelkka
    vaihtuvuusluku kuuluu tyokaluihin, ei jokaiselle ottelusivulle: 26/27
    kukaan ei ylita kynnysta, joten luku olisi 380 sivulla kohinaa.
    """
    path = ROOT / "data" / "team_confidence.json"
    if not path.exists():
        print("VAROITUS: team_confidence.json puuttuu — ei lippuja")
        return 0
    doc = json.loads(path.read_text(encoding="utf-8"))
    conf = {t["model_team"]: t for t in doc["teams"] if t.get("flag")}
    n = 0
    for rows in by_comp.values():
        for e in rows:
            notes = []
            for key in ("home_team", "away_team"):
                t = conf.get(e.get(key))
                if t and t.get("note"):
                    notes.append((e[key], t["note"]))
            if notes:
                e["_confidence"] = notes
                n += 1
    return n


def _match_filename(e: dict) -> str:
    return f"{_slug(e['home_team'])}-vs-{_slug(e['away_team'])}.html"


def _prob_block(e: dict) -> str:
    ph, pd_, pa = e["p_home"], e["p_draw"], e["p_away"]
    return (
        f'<div class="probbar" aria-hidden="true">'
        f'<span class="h" style="width:{ph * 100:.1f}%"></span>'
        f'<span class="d" style="width:{pd_ * 100:.1f}%"></span>'
        f'<span class="a" style="width:{pa * 100:.1f}%"></span></div>'
        f'<div class="legend"><span>{escape(e["home_team"])} {_fmt_pct(ph)}</span>'
        f"<span>Draw {_fmt_pct(pd_)}</span>"
        f'<span>{escape(e["away_team"])} {_fmt_pct(pa)}</span></div>'
    )


def _confidence_block(e: dict) -> str:
    """Nakyva varoitus kun luokitus nojaa vanhentuneeseen tietoon.

    Sanamuoto kertoo MIKSI luku on epavarmempi, ei pelkkaa etikettia: malli
    sovitetaan tuloksiin eika nae siirtoikkunaa, ja nousijalla ei ole
    PL-tuloksia lainkaan. Vrt. yritys korjata luokitusta suoraan — se ei
    validoitunut (calibrate_transfer_effect), joten kerromme epavarmuuden
    emmeka saada lukua.
    """
    notes = e.get("_confidence")
    if not notes:
        return ""
    items = "".join(
        f"<li><strong>{escape(team)}</strong>: {escape(note)}</li>"
        for team, note in notes
    )
    return (
        '<div class="rec"><strong>Lower confidence in this one.</strong> '
        f"<ul>{items}</ul>"
        "The model is fitted on results, so it prices a squad by what it did, "
        "not by who is in it now.</div>"
    )


def render_match_page(comp: str, e: dict) -> str:
    cfg = LEAGUES[comp]
    home, away = e["home_team"], e["away_team"]
    ph, pd_, pa = e["p_home"], e["p_draw"], e["p_away"]
    fav = home if e["predicted_winner"] == "home" else away
    fav_pct = _fmt_pct(ph if e["predicted_winner"] == "home" else pa)
    url = f"{BASE}/predictions/{cfg['slug']}/{_match_filename(e)[:-5]}"
    title = f"{home} vs {away} Prediction: {cfg['name']} | GoalIQ"
    # 2.8.2026 PREMIUM-VUOTO KIINNI: raaka xG on premium-dataa (PredictScreen
    # #92: "siita johtaa total goals + BTTS + scoreline", XgStat locked=
    # !isPremium), mutta se julkaistiin 1 930 indeksoidulla sivulla ilmaiseksi.
    # Julki jaavat 1X2 ja todennakoisin tulos: molemmat ovat osa JULKAISTUA
    # track recordia (pct_1x2 + pct_exact gradataan), eli ilman niita koko
    # "logged before kickoff" -vaite ei olisi todennettavissa. xG ei ole
    # gradattu mittari eika sita siksi tarvita vaitteen tueksi.
    desc = (
        f"{home} vs {away} ({cfg['name']}, {e.get('date')}): the GoalIQ model "
        f"gives {fav} a {fav_pct} chance to win. Logged before kick-off in our "
        f"public track record and graded after the match."
    )
    hero = (
        f"<h1>{escape(home)} vs {escape(away)} prediction</h1>"
        f'<p class="lede">{escape(cfg["name"])} · kickoff {_fmt_kickoff(e.get("kickoff") or "")}. '
        f"The GoalIQ match model makes <strong>{escape(fav)}</strong> the favourite "
        f"at <strong>{fav_pct}</strong> to win.</p>"
    )
    body = (
        f'<div class="card big">{_prob_block(e)}</div>'
        f'<div class="stat-row">'
        f'<div class="stat"><b>Premium</b><span>expected goals and the most likely score on '
        f'<a href="https://pro.goaliq.app/?tab=premium&amp;src=predict-page&amp;srcp=predictions">GoalIQ Premium</a></span></div>'
        f"</div>"
        + _confidence_block(e)
        + f'<div class="rec">This prediction was logged before kickoff on '
        f'{escape((e.get("logged_at") or "")[:10])} and will be graded in our '
        f'<a href="/predictions">public track record</a>, hits and misses included.</div>'
        f'<div class="cta-row">'
        f'<a class="btn" href="https://pro.goaliq.app/">Run your own prediction</a>'
        f'<a class="btn ghost" href="/predictions/{cfg["slug"]}/">More {escape(cfg["name"])} predictions</a>'
        f"</div>"
        f'<p class="note">{DISCLAIMER}</p>'
    )
    jsonld = [
        {
            "@context": "https://schema.org",
            "@type": "SportsEvent",
            "name": f"{home} vs {away}",
            "startDate": e.get("kickoff"),
            "sport": "Soccer",
            "homeTeam": {"@type": "SportsTeam", "name": home},
            "awayTeam": {"@type": "SportsTeam", "name": away},
            "location": {"@type": "Place", "name": cfg["name"]},
        },
        {
            "@context": "https://schema.org",
            "@type": "WebPage",
            "name": title,
            "url": url,
            "description": desc,
            "isPartOf": {"@id": f"{BASE}/#organization"},
            "publisher": ORG_PUBLISHER,
        },
    ]
    return _page(title, desc, url, hero, body, jsonld)


def render_league_hub(comp: str, rows: list[dict], now: datetime) -> str:
    cfg = LEAGUES[comp]
    url = f"{BASE}/predictions/{cfg['slug']}/"
    title = f"{cfg['name']} Predictions This Week: Win Probability | GoalIQ"
    desc = (
        f"Model win probabilities for upcoming {cfg['name']} matches. Every "
        f"prediction is logged before kickoff in GoalIQ's public track record "
        f"and graded after the match, hits and misses included."
    )
    items = []
    for e in rows:
        fname = _match_filename(e)
        fav = e["home_team"] if e["predicted_winner"] == "home" else e["away_team"]
        fav_pct = _fmt_pct(
            e["p_home"] if e["predicted_winner"] == "home" else e["p_away"]
        )
        items.append(
            f'<div class="mrow"><div>'
            f'<a href="/predictions/{cfg["slug"]}/{fname[:-5]}">'
            f'{escape(e["home_team"])} vs {escape(e["away_team"])}</a>'
            f'<div class="meta">{_fmt_kickoff(e.get("kickoff") or "")}</div></div>'
            f'<span class="pick">{escape(fav)} {fav_pct}</span></div>'
        )
    hero = (
        f"<h1>{escape(cfg['name'])} predictions</h1>"
        f'<p class="lede">The GoalIQ match model predicts every upcoming '
        f"{escape(cfg['name'])} fixture: win probability for each side, expected "
        f"goals and the most likely score. Predictions are logged before kickoff "
        f"and graded in a public track record.</p>"
    )
    body = (
        f'<div class="card">{"".join(items)}</div>'
        f'<div class="cta-row">'
        f'<a class="btn" href="https://pro.goaliq.app/">Run your own prediction</a>'
        f'<a class="btn ghost" href="/predictions">All football predictions</a>'
        f"</div>"
        f'<p class="note">Updated {now.strftime("%d %b %Y %H:%M UTC")} · {DISCLAIMER}</p>'
    )
    jsonld = [
        {
            "@context": "https://schema.org",
            "@type": "ItemList",
            "name": title,
            "url": url,
            "numberOfItems": len(rows),
            "itemListElement": [
                {
                    "@type": "ListItem",
                    "position": i + 1,
                    "name": f"{e['home_team']} vs {e['away_team']}",
                    "url": f"{BASE}/predictions/{cfg['slug']}/{_match_filename(e)[:-5]}",
                }
                for i, e in enumerate(rows)
            ],
        },
        {
            "@context": "https://schema.org",
            "@type": "WebPage",
            "name": title,
            "url": url,
            "description": desc,
            "publisher": ORG_PUBLISHER,
        },
    ]
    return _page(title, desc, url, hero, body, jsonld)


def update_predictions_hub_links(live: list[str]) -> bool:
    """Täytä predictions.html:n GEN:PRED-LEAGUES-markerit livenä olevilla
    liigahubeilla (hub-spoke). Markerit puuttuvat → False (ei kaatoa)."""
    if not PREDICTIONS_HTML.exists():
        return False
    s = PREDICTIONS_HTML.read_text(encoding="utf-8")
    if "GEN:PRED-LEAGUES-START" not in s:
        return False
    links = " ".join(
        f'<a class="btn-ghost" href="/predictions/{LEAGUES[c]["slug"]}/" '
        f'style="margin:4px;">{escape(LEAGUES[c]["name"])} predictions</a>'
        for c in live
    )
    block = links or '<span class="cta-note">League pages return with the new seasons.</span>'
    new = re.sub(
        r"(<!-- GEN:PRED-LEAGUES-START -->).*?(<!-- GEN:PRED-LEAGUES-END -->)",
        lambda m: m.group(1) + block + m.group(2),
        s,
        flags=re.S,
    )
    if new != s:
        PREDICTIONS_HTML.write_text(new, encoding="utf-8")
        return True
    return False


def update_llms_txt(counts: dict[str, int]) -> bool:
    """#231-GEO: kasvumoottorin luvut llms.txt:hyn SAMASTA datasta kuin sitemap.

    Ongelma ei ollut llms.txt:n sisalto vaan se etta se oli kasin yllapidetty:
    kolme perakkaista viikkoauditointia loysi siita eri staleuden (17.7 faq,
    29.7 termi + kuolleet WC-sivut, 5.8 koko 1752 sivun laajennus puuttui),
    koska mikaan generaattori ei kirjoittanut sita eika mikaan portti lukenut.

    Generoidaan VAIN markkeriparin sisus eli liigarivit ja sivumaarat. Loppu
    tiedostosta (disambiguaatio, tuotekuvaukset, hinnat) pysyy kasin
    kirjoitettuna tarkoituksella - se on arvostelukykya, ei dataa.

    Markkerit puuttuvat -> False, ei kaatoa (sama sopimus kuin
    update_predictions_hub_links).
    """
    if not LLMS_TXT.exists():
        return False
    s = LLMS_TXT.read_text(encoding="utf-8")
    if "GEN:LLMS-START" not in s:
        return False
    order = ["PL", "PD", "SA", "BL1", "FL1", "BSA", "CL"]
    live = [c for c in order if counts.get(c)] + [
        c for c in counts if c not in order and counts.get(c)
    ]
    rows = [
        f"- [{fold_ascii(LEAGUES[c]['name'])} predictions]"
        f"(https://goaliq.app/predictions/{LEAGUES[c]['slug']}/): "
        f"{counts[c]} fixture pages."
        for c in live
    ]
    total = sum(counts[c] for c in live)
    rows.append(
        f"- Live now: {len(live)} league hubs and {total} fixture pages, "
        "regenerated every three hours as fixtures are played and new ones "
        "are logged."
        if live else
        "- No fixture pages are live right now; league pages return with the "
        "new seasons."
    )
    block = "\n" + "\n".join(rows) + "\n"
    new = re.sub(
        r"(<!-- GEN:LLMS-START -->).*?(<!-- GEN:LLMS-END -->)",
        lambda m: m.group(1) + block + m.group(2),
        s,
        flags=re.S,
    )
    if new != s:
        LLMS_TXT.write_text(new, encoding="utf-8")
        return True
    return False


def main() -> int:
    now = datetime.now(timezone.utc)
    log = acc.load_log()
    by_comp = _upcoming_by_comp(log, now)
    # JARJESTYS ON PAKOLLINEN: luottamuslippu haetaan raaoilla mallinimilla
    # ENNEN nayttonimien vaihtoa (ks. _attach_confidence).
    n_conf = _attach_confidence(by_comp)
    pl_rows = len(by_comp.get("PL") or [])
    print(f"Luottamuslippu: {n_conf} ottelusivulle (PL-otteluita {pl_rows})")
    if pl_rows and not n_conf:
        # PL:ssa on aina 3 nousijaa, joten liputettuja otteluita ON oltava.
        # Nolla tarkoittaa etta nimimappays hajosi — ja se ei kaadu itsestaan.
        print("VIRHE: PL-otteluita on mutta yksikaan ei saanut lippua — "
              "mallinimien haku on rikki", file=sys.stderr)
        return 1

    mapped, unmapped = _apply_display_names(by_comp)
    total_names = len(mapped) + len(unmapped)
    print(f"DISPLAY_NAMES: {len(mapped)}/{total_names} osumaa, "
          f"{len(unmapped)} ilman karttaa"
          + (f" -> {sorted(unmapped)}" if unmapped else ""))

    sitemap_entries: list[tuple[str, str, str, str]] = []
    sitemap_skipped = 0
    live_hubs: list[str] = []
    match_counts: dict[str, int] = {}
    total_pages = 0
    today = now.strftime("%Y-%m-%d")

    for comp, cfg in LEAGUES.items():
        rows = by_comp.get(comp) or []
        out_dir = OUT_ROOT / cfg["slug"]
        if not rows:
            # Off-season/ei dataa → ei hubia; siivoa mahdolliset vanhat sivut
            if out_dir.exists():
                for f in out_dir.glob("*.html"):
                    f.unlink()
            print(f"{comp}: 0 tulevaa ottelua — ohitetaan (template valmiina).")
            continue
        out_dir.mkdir(parents=True, exist_ok=True)
        # Slug-tormays: kaksi eri ottelua samaan tiedostonimeen tarkoittaa etta
        # nayttonimikartta on vienyt kaksi joukkuetta samaan sluginiin. Ilman
        # tata tarkistusta jalkimmainen kirjoittaa edellisen yli ja sivumaara
        # putoaa HILJAA — juuri se vikaluokka jota vastaan tama koko commit on.
        names = [_match_filename(e) for e in rows]
        if len(set(names)) != len(names):
            dupes = sorted({n for n in names if names.count(n) > 1})
            print(f"VIRHE {comp}: slug-tormays {len(names) - len(set(names))} "
                  f"sivulla -> {dupes}", file=sys.stderr)
            return 1
        # Siivoa vanhentuneet ottelusivut (kickoff mennyt / pariutus muuttui)
        keep = {"index.html"} | set(names)
        for f in out_dir.glob("*.html"):
            if f.name not in keep:
                f.unlink()
        (out_dir / "index.html").write_text(
            render_league_hub(comp, rows, now), encoding="utf-8"
        )
        for e in rows:
            (out_dir / _match_filename(e)).write_text(
                render_match_page(comp, e), encoding="utf-8"
            )
        live_hubs.append(comp)
        match_counts[comp] = len(rows)
        total_pages += 1 + len(rows)
        # Hubi aina sitemapiin; ottelusivut vain lahihorisontista (ks.
        # SITEMAP_HORIZON_DAYS). Sivut itse on jo kirjoitettu levylle yllä —
        # tämä rajaa vain sen mitä Googlelle tarjotaan ryömittäväksi.
        sitemap_entries.append(
            (f"{BASE}/predictions/{cfg['slug']}/", today, "daily", "0.8")
        )
        near = [e for e in rows if _within_horizon(e, now)]
        sitemap_entries.extend(
            (f"{BASE}/predictions/{cfg['slug']}/{_match_filename(e)[:-5]}",
             today, "daily", "0.7")
            for e in near
        )
        sitemap_skipped += len(rows) - len(near)
        print(f"{comp}: hub + {len(rows)} ottelusivua → predictions/{cfg['slug']}/")

    write_urlset(SITEMAP_PRED_PATH, sitemap_entries)
    print(f"sitemap-predictions.xml: {len(sitemap_entries)} URL:ia "
          f"({sitemap_skipped} ottelusivua jatetty pois, kickoff yli "
          f"{SITEMAP_HORIZON_DAYS} pv paassa — sivut ovat silti olemassa "
          f"ja hubit linkittavat niihin)")
    hub_updated = update_predictions_hub_links(live_hubs)
    llms_updated = update_llms_txt(match_counts)
    print(f"Yhteensä {total_pages} sivua ({len(live_hubs)} liigaa). "
          f"predictions.html-hublinkit: {'päivitetty' if hub_updated else 'ei muutosta'}.")
    print(f"llms.txt GEN:LLMS-lohko: "
          f"{'päivitetty' if llms_updated else 'ei muutosta'}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
