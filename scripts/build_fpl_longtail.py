"""Ilmaiset indeksoitavat FPL-long-tail-sivut (#120).

Kolme evergreen-URLia, per-GW päivittyvä sisältö:

  fpl/best-captain.html    "Best FPL captain GW{n}" — top-pick NIMENÄ, sijat
                           2-3 niminä, EI xP-lukuja (3.8. korjaus: alkuperäinen
                           "captain suggestion on ilmainen appissa" oli VÄÄRÄ
                           premissi, CaptainRanker on kokonaan premium).
  fpl/differentials.html   "Best FPL differentials GW{n}" — top-1 nimi + EO
                           (FPL:n omaa julkista dataa), EI xP:tä → Premium.
  fpl/price-changes.html   "FPL price changes" — koko risers/fallers-lista
                           (price watch on ilmainen appissa). Esikausi →
                           rehellinen tyhjätila meta.notesta.

EI Premium-vuotoa: teaser-syvyys peilaa appin free/premium-rajaa.
Datalähteet: data/fpl_xp_projections.json + data/fpl_price_watch.json
(committattuja) + /api/fantasy/differentials (EO vaatii bootstrap-joinin —
yksi kevyt kutsu; virhe → sivu ohitetaan, ei kaatoa).
Gambling-safe: predictions/xP/model — EI betting/odds/tips.
Ajo: python -m scripts.build_fpl_longtail  (accuracy-log.yml, 3 h)
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import urllib.request
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

# 15.8: analytiikka MYOS longtail-sivuille. Mitattu 15.8: fpl.html sisalsi
# PostHogin (202 latausta / 14 vrk) mutta /fpl/expected-points ja
# /fpl/predicted-lineups eivat sisaltaneet sita LAINKAAN -> koko generoitu
# sisaltopinta oli mittaamaton. Sama vakio kuin paasivuilla eika kopio:
# kaksi rinnakkaista snippettia eriytyisivat hiljaa.
from scripts.build_fpl_page import (  # noqa: E402
    POSTHOG_SNIPPET,
    ROOT as _FP_ROOT,
    write_urlset,
)
from scripts.mobile_css import MOBILE_COLS_JS, MOBILE_CSS
from scripts.share_card_js import SHARE_CARD_JS
from scripts.table_tools import TABLE_TOOLS_JS  # noqa: E402

# #119b: long-tail-sivut omaan lapsi-sitemapiin (sitemap.xml-index listaa).
# Wholesale OUT_DIR-globista → entry jokaiselle olemassa olevalle sivulle,
# myös silloin kun jokin data-lähde puuttui tältä ajolta (sivu jää voimaan).
SITEMAP_FPL_PATH = _FP_ROOT / "sitemap-fpl.xml"
from scripts.build_prediction_pages import DISCLAIMER
from src.models.fpl_club_best import POSITIONS, club_best_rows, gap_text

BASE = "https://goaliq.app"
OUT_DIR = ROOT / "fpl"
XP_PATH = ROOT / "data" / "fpl_xp_projections.json"
PW_PATH = ROOT / "data" / "fpl_price_watch.json"
# #128/#120: xG- + DefCon-leaders-sivut samasta nightly-cachesta kuin API
LEADERS_PATH = ROOT / "data" / "fpl_player_leaders.json"
# 8.8 STATS-ZONE: ilmainen suodatettava raakataulukko (scripts/build_fpl_stats.py)
STATS_PATH = ROOT / "data" / "fpl_player_stats.json"
# 8.8: joukkuetason puolustusprofiili (scripts/build_understat_team_defence.py)
DEFENCE_PATH = ROOT / "data" / "understat_team_defence_2526.json"
API = "https://api.goaliq.app"  # 27.7: pois estetysta onrender.com-vyohykkeesta

UPSELL = (
    '<div class="rec">Powered by the GoalIQ match model with a published, '
    'pre-match-logged track record. The full toolkit (captain ranker, all '
    'differentials, transfer planner) is <a '
    'href="https://pro.goaliq.app/?tab=premium">GoalIQ Premium</a>: '
    '3.99 €/month or 25 €/season. '
    'One subscription on web, iOS and Android.</div>'
)

# 24.7 brand redesign: sama ilme kuin fpl.html (Space Grotesk, magenta-bar,
# tumma ink-hero, cream-body, paper-kortit, pillerinapit). Longtail-sivuilla
# OMA template — build_prediction_pages.CSS/NAV/_page jää prediction-sivujen
# vanhaan asuun, ei sivuvaikutuksia sinne.
def _strip_css_comments(css: str) -> str:
    """Poista /* ... */ -kommentit ENNEN kuin CSS kirjoitetaan sivulle.

    11.8.2026: CSS-lohkon perustelukommentit ovat suomeksi ja sisaltavat em
    dasheja, ja ne servattiin sellaisenaan julkisella englanninkielisella
    sivulla (nakyvat view-sourcesta). Kommentit kuuluvat lahdekoodiin, eivat
    tuotokseen. Ei kaanneta niita: pidetaan perustelut taalla ja jatetaan ne
    pois HTML:sta.

    Huom: ei koske MOBILE_CSS/SHARE_CARD_JS -moduuleja, ne injektoidaan
    erikseen; jos niissa on kommentteja, aja sama funktio niillekin.
    """
    out = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    # Kommenttien tilalle jaaneet tyhjat rivit pois, muuten sivulle jaa
    # kymmenia perakkaisia rivinvaihtoja.
    return re.sub(r"\n{2,}", "\n", out).strip()


CSS = """
.brand-icon{width:22px;height:22px;display:inline-block;vertical-align:-4px;margin-right:8px;flex:none;}
:root{--teal:#2ED6C2;
--teal-ink:#2ED6C2;--amber:#F5C542;--amber-deep:#F5C542;
--gold:#F5C542;--gold-deep:#F5C542;--coral:#FF8A5C;
--ink:#0B0A09;--ink2:#141311;--cream:#F3F2F2;
--paper:#1F1D1A;--muted:#A8A29A;--hero-muted:#A8A29A;--faint:#8A847A;
--line:rgba(243,242,242,0.24);--line-strong:rgba(243,242,242,0.40);--radius:0;}
*{box-sizing:border-box;margin:0;padding:0;}
body{background:var(--ink);color:var(--cream);font-family:"IBM Plex Mono",ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;line-height:1.6;}
h1,h2,h3,.brand{font-family:"IBM Plex Mono",ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;text-transform:uppercase;letter-spacing:-0.01em;}
.wrap{max-width:820px;margin:0 auto;padding:0 20px;}
.bar{height:1px;background:var(--line);}
/* Bug 26 Jul: color was var(--cream) = cream on a cream background -> every
   color:inherit child would be invisible. Leftover from the dark-to-light
   switch. */
.dark{background:var(--ink);
color:var(--cream);}
nav{display:flex;align-items:center;justify-content:space-between;
padding:18px 0;font-size:14px;}
nav a{text-decoration:none;color:var(--cream);font-weight:600;}
.brand{font-size:20px;font-weight:700;letter-spacing:.5px;}
.brand span{color:var(--amber);}
.nav-cta{background:transparent;color:var(--amber);border:1px solid var(--amber);padding:8px 16px;
border-radius:var(--radius);font-weight:700;}
.nav-cta:hover{background:var(--amber);color:var(--ink);}
/* 9 Aug (spotted on a large screen): this was 'padding:26px 0 44px', and
   the shorthand zeroed .wrap's horizontal padding -> the hero heading and
   lede started 20px left of everything else. The page had two different
   left edges (303 and 323). Vertical padding only. */
.hero{padding-top:26px;padding-bottom:44px;}
.hero h1{color:var(--cream);font-size:31px;line-height:1.15;margin:0 0 12px;
letter-spacing:-0.01em;}
.hero .lede{color:var(--hero-muted);max-width:640px;}
h2{font-size:22px;margin:30px 0 10px;}
.content{padding-top:26px;}
.card{background:var(--paper);border:1px solid var(--line);
border-radius:var(--radius);padding:18px 20px;margin-bottom:14px;}
.lede{color:var(--muted);margin-bottom:22px;}
.stat-row{display:flex;flex-wrap:wrap;gap:12px;margin:14px 0;}
.stat{background:var(--paper);border:1px solid var(--line);
border-radius:var(--radius);padding:14px 18px;flex:1 1 140px;}
.stat b{display:block;font-size:22px;color:var(--amber);
font-family:"IBM Plex Mono",ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;}
.stat span{color:var(--muted);font-size:12px;}
.rec{border:1px solid var(--line);background:var(--paper);
border-radius:var(--radius);padding:16px 20px;font-size:14px;color:var(--muted);
margin:24px 0 16px;}
.rec a{color:var(--teal);font-weight:700;}
.cta-row{display:flex;flex-wrap:wrap;gap:12px;margin:22px 0;}
.btn{background:transparent;color:var(--amber);border:1px solid var(--amber);font-weight:700;padding:12px 22px;
border-radius:var(--radius);text-decoration:none;font-size:14px;}
.btn:hover{background:var(--amber);color:var(--ink);}
.btn.ghost{background:transparent;color:var(--cream);
border:1px solid var(--line);}
.btn.ghost:hover{background:transparent;color:var(--amber);}
.mrow{display:flex;align-items:center;justify-content:space-between;gap:10px;
padding:12px 0;border-bottom:1px solid var(--line);}
.mrow:last-child{border-bottom:none;}
.mrow a{color:var(--teal);font-weight:700;text-decoration:none;}
.mrow .meta{color:var(--muted);font-size:12px;}
.pick{color:var(--teal-ink);font-weight:700;font-size:13px;white-space:nowrap;}
footer{border-top:1px solid var(--line);margin-top:36px;padding:22px 0 34px;
color:var(--muted);font-size:13px;}
footer a{color:var(--teal);}
.note{color:var(--muted);font-size:12px;margin:18px 0;}
/* 26 Jul: the xG leaderboard opened up, full table free */
/* 8 Aug (user report): the page column is 820px, so even a wide screen did
   not show every table column and you had to scroll sideways with the arrow.
   Now EVERY table may escape the column and grow with the window up to
   1560px; header, body text and footer stay at 820 (line length is
   readability). 96vw rather than 100vw so the vertical scrollbar cannot push
   the page sideways. The table itself does NOT stretch as filler: width:auto
   + min-width keeps narrow tables at their previous width, centered, and
   only wide ones use the extra room. On a narrow screen min() returns 100%
   -> behavior is exactly what it was. */
/* Article typography. Long-form notes need paragraph spacing; without it the
   blocks run together into one wall of text. */
.note-body p{margin:0 0 15px;}
.note-body h3{margin:26px 0 10px;font-size:1.05rem;letter-spacing:.01em;}
.note-body h3:first-child{margin-top:0;}
/* Article data table. Deliberately NOT .lb-wrap: that stretches a table to
   the full viewport and centres it, which is wrong for a narrow four-column
   table inside a text column. It still gets its own scroll container so a
   narrow screen scrolls the table rather than the page. */
.tblwrap{overflow-x:auto;margin:14px 0;}
.note-tbl{border-collapse:collapse;font-size:.95rem;min-width:22rem;}
.note-tbl th,.note-tbl td{padding:5px 14px 5px 0;text-align:left;
white-space:nowrap;}
.note-tbl th{border-bottom:1px solid var(--line-strong);font-weight:600;}
.note-tbl td:nth-child(n+2){text-align:right;font-variant-numeric:tabular-nums;}
.note-tbl tbody tr+tr td{border-top:1px solid var(--line);}
.lb-wrap{overflow-x:auto;margin:14px 0;
width:min(96vw,1560px);margin-left:50%;transform:translateX(-50%);}
/* 820px was .wrap's max-width INCLUDING PADDING, but the text column is
   780px. A table centered at 820 in the full-width wrapper thus started
   20px left of the text. Same number as the text column -> edges align;
   wide tables still grow. */
.lb-wrap>.lb{width:auto;min-width:min(100%,780px);margin:0 auto;}
/* 96vw + translateX must not create page-level horizontal scrolling */
html,body{overflow-x:clip;}
.lb{width:100%;border-collapse:collapse;font-size:14px;}
.lb th,.lb td{padding:8px 10px;text-align:left;
border-bottom:1px solid var(--line);white-space:nowrap;}
.lb th{font-size:11px;text-transform:uppercase;letter-spacing:.06em;
color:var(--muted);font-weight:700;}
.lb td.n,.lb th.n{text-align:right;font-variant-numeric:tabular-nums;}
.lb td.hi{color:var(--amber);font-weight:700;}
.lb tbody tr:last-child td{border-bottom:none;}
.lb thead th:hover{color:var(--amber);}
.lbctl{display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin:16px 0 6px;}
.lbctl .lbl{font-size:11px;text-transform:uppercase;letter-spacing:.06em;
color:var(--muted);font-weight:700;margin-left:6px;}
.lbctl .lbl:first-child{margin-left:0;}
.chips{display:inline-flex;gap:6px;}
.chip{min-width:34px;border:1px solid var(--line-strong);background:var(--paper);
color:var(--cream);border-radius:var(--radius);padding:6px 12px;font-size:13px;
font-weight:600;cursor:pointer;}
.chip.on{background:var(--amber);border-color:var(--amber);color:var(--ink);}
.lbctl select{border:1px solid var(--line-strong);background:var(--paper);
color:var(--cream);border-radius:var(--radius);padding:6px 12px;font-size:13px;
font-weight:600;}
/* Neutral team shirt (no crest or player likeness, see the IP note in code) */
.lb td.tm{display:flex;align-items:center;gap:7px;}
/* Confidence flag (10 Aug): the team's rating rests on weaker information.
   DESCRIPTIVE - it does not say which way the projection moves. Muted on
   purpose: it is a margin note on the row, not the row's main point. */
.tflag{flex:0 0 auto;font-size:10px;font-weight:600;letter-spacing:.04em;
text-transform:uppercase;padding:1px 5px;border:1px solid var(--line-strong);
border-radius:var(--radius);opacity:.72;white-space:nowrap;}
.kit{flex:0 0 auto;display:block;}
/* Model XI pitch. 26 Jul: same look as the SPA's TeamPitchManager and the
   mobile #106 pitch (teal tint, #108 palette) - NOT grass green. Decision:
   the brand palette beats literal grass, and all three surfaces must look
   the same. */
.pitch{background:rgba(46,214,194,0.22);border:1px solid var(--line);
border-radius:var(--radius);padding:10px 6px;margin:18px 0;}
.xirow{display:flex;justify-content:space-evenly;flex-wrap:wrap;gap:8px;
margin:10px 0;}
.xip{width:76px;text-align:center;color:var(--cream);}
.xip b{display:block;font-size:11px;font-weight:600;margin-top:2px;
overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.xip span{display:block;font-size:10px;color:var(--muted);
font-variant-numeric:tabular-nums;}
@media (max-width:520px){.xip{width:64px;}.xirow{gap:6px;}}
@media (max-width:520px){.cta-row{flex-direction:column;align-items:stretch;}
.btn{text-align:center;}}
.toolnav{margin:34px 0 6px;padding-top:18px;border-top:1px solid var(--line);
display:flex;flex-direction:column;gap:10px;justify-content:flex-start;
align-items:stretch;}
.navgrp{display:flex;flex-wrap:wrap;align-items:baseline;gap:8px 14px;}
/* justify-content MUST be set here. The bare `nav` rule further up sets
   space-between for the page header, and .clubnav inherits it, which spread
   the last row of club links evenly across the full width. An element
   selector that reaches a component added later is a silent trap. */
.clubnav{display:flex;flex-wrap:wrap;align-items:baseline;gap:6px 10px;
justify-content:flex-start;
margin:0 0 26px;padding-bottom:14px;border-bottom:1px solid var(--line);}
.clubnav b{font-size:13px;letter-spacing:.06em;text-transform:uppercase;
color:var(--muted);font-weight:600;margin-right:4px;}
.clubnav a{font-size:14px;color:var(--cream);text-decoration:none;
border:1px solid var(--line);padding:3px 7px;}
.clubnav a:hover{border-color:var(--amber);}
.share{display:flex;flex-wrap:wrap;align-items:baseline;gap:8px 12px;
justify-content:flex-start;margin:26px 0 6px;}
.share span{font-size:13px;letter-spacing:.06em;text-transform:uppercase;
color:var(--muted);}
.share a{font-size:14px;color:var(--cream);text-decoration:none;
border:1px solid var(--line);padding:3px 10px;}
.share a:hover{border-color:var(--amber);}
.clubnav b.here{color:var(--amber);border:1px solid var(--amber);
padding:3px 7px;font-size:14px;letter-spacing:0;text-transform:none;}
.navgrp b{min-width:88px;}
.toolnav b{font-size:13px;letter-spacing:.06em;text-transform:uppercase;
color:var(--muted);font-weight:600;margin-right:2px;}
.toolnav a{font-size:15px;color:var(--cream);text-decoration:none;
border-bottom:1px solid var(--line);padding-bottom:1px;}
.toolnav a:hover{border-bottom-color:currentColor;}
""" + MOBILE_CSS


# 28.7: SISAINEN LINKITYS. GSC:n URL-tarkastus paljasti etta naista sivuista
# 5/6 oli Googlelle taysin tuntemattomia: "Viittaavia sivustokarttoja ei
# havaittu" JA "Viittaava sivu: Ei havaittuja". Sitemap yksin on heikko
# signaali - sivu jolle ei osoita yksikaan linkki on orpo, eika Google
# priorisoi sen indeksointia. Mitattu ennen korjausta: fpl.html -> 0 kpl
# /fpl/*-linkkeja, etusivu -> 1 (model-xi), /predictions -> 0.
# Naiden sivujen koko olemassaolon syy on FPL-hakuliikenne ennen GW1:ta.
#
# 15.8: TAMA LISTA OLI ITSE VANHENTUNUT. Yllaoleva kommentti kuvaa vian, mutta
# sen jalkeen lisatyt sivut jaivat listalta pois — mitattu 15.8: `expected-
# points` ja `team-news` eivat olleet siina, joten yksikaan sisarsivu eika
# etusivu osoittanut niihin. `expected-points` on se sivu johon X-postaukset
# linkittavat, eli orvoksi oli jaanyt tarkein ilmaispinta.
#
# Lista on nyt PORTITETTU (tests/test_fpl_team_news_page.py): jokaisen
# generoidun /fpl/-sivun on oltava taalla. Kuratoitu lista ilman porttia
# vanhenee joka kerta kun sivuja lisataan, ja se on tapahtunut nyt kahdesti.
_TOOL_LINKS = [
    ("/fpl/best-captain", "Captain picks"),
    ("/fpl/expected-points", "Expected points"),
    ("/fpl/club-best", "Best per club"),
    ("/fpl/team-news", "Team news"),
    ("/fpl/notes", "Notes"),
    ("/fpl/model-xi", "Model XI"),
    ("/fpl/differentials", "Differentials"),
    ("/fpl/price-changes", "Price changes"),
    ("/fpl/xg-leaders", "xG leaders"),
    ("/fpl/defcon", "DefCon leaders"),
    ("/fpl/stats", "Player stats"),
    ("/fpl/defence", "Defence profiles"),
    ("/fpl/predicted-lineups", "Predicted XI"),
]


# Valikon ryhmittely (15.8.2026, Villen vaatimus: "jos sivuja alkaa olla
# paljon niin sitten menut pystyyn").
#
# Sivuja on nyt 32 ja tasainen linkkirivi on lukukelvoton siina koossa: se on
# 30 sanaa perakkain ilman hierarkiaa, eika lukija loyda siita mitaan. Ryhmat
# vastaavat kysymykseen jota lukija kysyy, eivat sita miten sivut syntyivat.
#
# Ryhma per rivi, otsikko lihavoituna. Nykyinen sivu jaa pois omasta
# ryhmastaan mutta ryhma sailyy — muuten valikko hyppii sivulta toiselle.
_NAV_GROUPS: list[tuple[str, tuple[str, ...]]] = [
    ("Picks", ("/fpl/best-captain", "/fpl/model-xi", "/fpl/differentials",
               "/fpl/expected-points")),
    ("Teams", ("/fpl/club-best", "/fpl/defence", "/fpl/team-news",
               "/fpl/predicted-lineups")),
    ("Numbers", ("/fpl/stats", "/fpl/xg-leaders", "/fpl/defcon",
                 "/fpl/price-changes")),
    ("Reading", ("/fpl/notes",)),
]


def _tool_nav(canonical: str) -> str:
    """Ristiinlinkitys ryhmiteltyna, nykyinen sivu pois.

    Renderoidaan <nav>-elementtina eika pelkkana linkkilistana, jotta
    sivun oma navigointirakenne on koneluettava.

    Jokainen `_TOOL_LINKS`-polku kuuluu johonkin ryhmaan; ryhmittelemattomat
    paatyvat "More"-ryhmaan, jottei uusi sivu voi kadota valikosta hiljaa.
    Sivusopimus (tests/test_page_contract.py) vaatii sisaantulevan linkin, ja
    tama on se paikka josta se yleensa tulee.
    """
    here = canonical.rstrip("/").replace(BASE, "")
    labels = dict(_TOOL_LINKS)
    ryhmitellyt = {h for _, hs in _NAV_GROUPS for h in hs}
    ryhmat = list(_NAV_GROUPS)
    loput = tuple(h for h, _ in _TOOL_LINKS if h not in ryhmitellyt)
    if loput:
        ryhmat.append(("More", loput))

    osat = []
    for otsikko, polut in ryhmat:
        linkit = "".join(
            f'<a href="{h}">{escape(labels.get(h, h))}</a>'
            for h in polut if h != here and h in labels
        )
        if linkit:
            osat.append(f'<span class="navgrp"><b>{otsikko}</b>{linkit}</span>')
    return (
        '<nav class="toolnav" aria-label="More free FPL tools">'
        + "".join(osat)
        + "</nav>\n"
    )


SOCIAL_IMAGE = f"{BASE}/assets/brand/goaliq-social-1200x630.png"


def _social_meta(title: str, desc: str, canonical: str,
                 image: str | None = None) -> str:
    """OG + Twitter Card, sama muoto ja sama kuva-asset kuin fpl.html:ssä
    (build_fpl_page.py). Ilman näitä sivu renderöityy jaettaessa paljaana
    linkkinä ilman otsikkoa, kuvausta tai kuvaa."""
    t, d = escape(title), escape(desc)
    img = image or SOCIAL_IMAGE
    return (
        '<meta property="og:type" content="article">\n'
        f'<meta property="og:title" content="{t}">\n'
        f'<meta property="og:description" content="{d}">\n'
        f'<meta property="og:url" content="{canonical}">\n'
        f'<meta property="og:image" content="{img}">\n'
        '<meta property="og:image:width" content="1200">\n'
        '<meta property="og:image:height" content="630">\n'
        '<meta property="og:site_name" content="GoalIQ">\n'
        '<meta name="twitter:card" content="summary_large_image">\n'
        '<meta name="twitter:site" content="@goaliqapp">\n'
        f'<meta name="twitter:title" content="{t}">\n'
        f'<meta name="twitter:description" content="{d}">\n'
        f'<meta name="twitter:image" content="{img}">\n'
    )



def _og_image(canonical: str) -> str:
    """Sivukohtainen og:image jos sellainen on generoitu, muuten yhteinen.

    Kortit: assets/brand/gen_og_cards.py (goaliq-app). Polku johdetaan
    canonicalin slugista, joten uusi sivu saa oman korttinsa automaattisesti
    heti kun tiedosto on olemassa — eika yksikaan render-funktio tarvitse
    muutosta. Puuttuva tiedosto putoaa yhteiseen korttiin, ei rikkinaiseen
    URLiin (jaettu linkki ilman kuvaa on parempi kuin 404-kuva).
    """
    slug = canonical.rstrip("/").rsplit("/", 1)[-1]
    rel = f"assets/brand/og/{slug}-1200x630.png"
    polku = _FP_ROOT / rel
    if not polku.exists():
        return SOCIAL_IMAGE
    # 🔴 SISALTOTIIVISTE URLIIN (15.8). Villen havainto: "Linkkikuva edelleen
    # toi sama?" Palvelimen tiedosto oli jo uusi (live ja lokaali tavulleen
    # identtiset), mutta X ja Bluesky valimuistittavat esikatselukortin
    # URL-kohtaisesti. Sama tiedostonimi eri sisallolla = alusta tarjoilee
    # vanhaa kuvaa, eika ankkuri (#slug) murra sita koska fragmenttia ei
    # laheteta palvelimelle lainkaan.
    #
    # Tiiviste muuttuu vain kun kuva muuttuu, joten tama ei riko
    # valimuistitusta silloin kun mitaan ei ole muuttunut.
    tiiviste = hashlib.sha256(polku.read_bytes()).hexdigest()[:8]
    return f"{BASE}/{rel}?v={tiiviste}"

def _page(title: str, desc: str, canonical: str, hero: str, body: str,
          jsonld: list[dict]) -> str:
    """Longtail-sivun runko uudessa ilmeessä: magenta-bar + tumma header/hero
    (h1 + lede) + cream-content. Sama head-järjestys kuin fpl.html:ssä."""
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
        # 29.7 (#225-SEO): OG/Twitter myös longtail-sivuille — kuusi
        # fpl-alasivua jaettiin paljaana linkkinä vaikka fpl.html emittoi
        # nämä. Sama kuva-asset, arvot _page()-parametreista.
        f"{_social_meta(title, desc, canonical, _og_image(canonical))}"
        # 27.7: koko ikonisetti myös alasivuille. Pelkkä .ico jätti selaimet
        # käyttämään matalaresoluutioista varianttia ja iOS:n kotinäytön ilman
        # ikonia — 187 alasivua näytti eri merkkiä kuin neljä pääsivua.
        '<link rel="icon" href="/favicon.ico" sizes="any">\n'
        '<link rel="icon" type="image/png" sizes="32x32" href="/assets/brand/goaliq-favicon-32.png">\n'
        '<link rel="icon" type="image/png" sizes="48x48" href="/assets/brand/goaliq-favicon-48.png">\n'
        '<link rel="apple-touch-icon" sizes="180x180" href="/assets/brand/goaliq-apple-touch-180.png">\n'
        + POSTHOG_SNIPPET + "\n" +
        TABLE_TOOLS_JS + "\n" +
        '<link rel="preconnect" href="https://fonts.googleapis.com">\n'
        '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n'
        # 26.7 PERF: preload+onload, ei render-blocking stylesheetiä — FCP ei
        # odota kolmannen osapuolen CSS:ää. noscript = varmistus.
        '<link rel="preload" as="style" href="https://fonts.googleapis.com/css2?family='
        'IBM+Plex+Mono:wght@400;500;600;700&display=swap" onload="this.rel=\'stylesheet\'">\n'
        '<noscript><link href="https://fonts.googleapis.com/css2?family='
        'IBM+Plex+Mono:wght@400;500;600;700&display=swap" rel="stylesheet"></noscript>\n'
        '<meta name="theme-color" content="#0B0A09">\n'
        f"{ld}"
        f"<style>{_strip_css_comments(CSS)}</style>\n"
        "</head>\n<body>\n"
        '<header class="dark">\n'
        '<div class="bar"></div>\n'
        '<div class="wrap"><nav>'
        '<a class="brand" href="/"><svg class="brand-icon" width="22" height="22" viewBox="0 0 44 44" role="img" aria-label="GoalIQ" focusable="false"><rect x="0" y="0" width="44" height="44" fill="#F5C542"/><text x="22" y="30" text-anchor="middle" font-family="IBM Plex Mono,ui-monospace,Consolas,monospace" font-size="20" font-weight="700" letter-spacing="-0.5" fill="#0B0A09">IQ</text></svg>Goal<span>IQ</span></a>'
        '<span><a href="/predictions">All predictions</a> · '
        '<a class="nav-cta" href="https://pro.goaliq.app/">Try it live</a></span>'
        "</nav></div>\n"
        f'<div class="wrap hero">\n{hero}\n</div>\n'
        "</header>\n"
        f'<main class="wrap content">\n{body}\n'
        f"{_tool_nav(canonical)}"
        f'<footer>© 2026 GoalIQ · '
        f'<a href="/predictions">Football predictions</a> · '
        f'<a href="/fpl.html">Free FPL tools</a> · '
        f'<a href="/privacy.html">Privacy</a><br>{DISCLAIMER}</footer>\n'
        "</main>\n" + MOBILE_COLS_JS + "</body>\n</html>\n"
    )


def _load(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _fetch_differentials() -> dict | None:
    # 27.7: EKSPLISIITTINEN User-Agent on PAKOLLINEN. Kun API siirtyi
    # api.goaliq.app-domainiin Cloudflaren taakse, CF alkoi torjua urllib:n
    # oletus-UA:n ("Python-urllib/3.x") 403:lla -> differentials-sivu olisi
    # lakannut paivittymasta HILJAA (builderi nappaa poikkeuksen ja jatkaa
    # varoituksella). onrender.com-osoite vastasi ilman tata.
    #
    # Sama koskee KAIKKIA skripteja jotka hakevat api.goaliq.app:sta
    # urllibilla — jos lisaat uuden, muista UA.
    req = urllib.request.Request(
        f"{API}/api/fantasy/differentials?max_ownership=10",
        headers={"User-Agent": "GoalIQ-PageBuilder/1.0 (+https://goaliq.app)"},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.load(r)
    except Exception as e:
        print(f"VAROITUS: differentials-haku epäonnistui: {type(e).__name__}: {e}")
        return None


def _cta() -> str:
    return (
        '<div class="cta-row">'
        '<a class="btn" href="https://pro.goaliq.app/?tab=premium">Open GoalIQ Premium</a>'
        '<a class="btn ghost" href="/fpl.html">Free clean-sheet probability &amp; FDR</a>'
        "</div>"
    )


def render_captain(xp: dict, now: datetime) -> str | None:
    meta = xp.get("meta") or {}
    players = xp.get("players") or []
    if not meta.get("available") or not players:
        return None
    gw = meta.get("next_gameweek") or "?"

    # 8.8.2026 (Villen havainto): sivu lupaa otsikossa "Best FPL Captain GW{n}"
    # mutta sorttasi xp_per_gw:lla (koko horisontin keskiarvo) -> sivu ja appin
    # CaptainRanker antoivat ERI ykkosen (B.Fernandes vs Gabriel) samasta
    # datasta. Kapteeni valitaan YHDEKSI kierrokseksi, joten avain on seuraavan
    # GW:n xp. Fallback xp_per_gw:hen jos gameweeks puuttuu (vanha payload).
    def _next_gw_xp(p: dict) -> float:
        gws = p.get("gameweeks") or []
        if gws and gws[0].get("xp") is not None:
            return float(gws[0]["xp"])
        return float(p.get("xp_per_gw") or 0.0)

    ranked = sorted(players, key=_next_gw_xp, reverse=True)
    top = ranked[0]
    alts = ranked[1:3]
    url = f"{BASE}/fpl/best-captain"
    # 3.8.2026 PREMIUM-VUOTO KIINNI: xP-luku pois julkiselta sivulta.
    # Taman sivun alkuperainen perustelu oli "free-pariteetti: captain
    # suggestion on ilmainen appissa". Se EI pida paikkaansa: CaptainRanker
    # on kokonaan premium (CAPTAIN_PAYWALL_SOURCE = 'fantasy_captain',
    # FantasyEdge.tsx:71) ja captain_viewed emittoituu vain premium-listalta,
    # eli free-kayttaja ei nae appissa yhtaan kapteenisuositusta. Julkinen
    # sivu antoi siis nimen JA xP:n ilmaiseksi. NIMI jaa (se on sivun
    # SEO-arvo ja teaser), LUKU menee lukon taakse — sama linja kuin
    # 2.8. ottelusivujen xG-korjauksessa: paywall kertoo mita puuttuu.
    title = f"Best FPL Captain GW{gw}: Model Pick | GoalIQ"
    desc = (
        f"The GoalIQ model's best FPL captain for Gameweek {gw}: "
        f"{top['web_name']} ({top['team_short']}). Expected points and the "
        f"full captain ranking are in GoalIQ Premium. Updated every round "
        f"from the match model behind our public track record."
    )
    hero = (
        f"<h1>Best FPL captain, Gameweek {gw}</h1>"
        f'<p class="lede">The GoalIQ match model\'s top captain pick for GW{gw} is '
        f"<strong>{escape(top['web_name'])} ({escape(top['team_short'])})</strong>.</p>"
    )
    # 9.8: Start% nakyviin. Sivu nimesi kapteenin ja piilotti KAIKKI luvut
    # ("xP in Premium"), joten lukija ei nahnyt onko valinta varma vai
    # kolikonheitto. 32 % pelaajista on vyohykkeella p_start 0,35-0,70, jossa
    # xMins on kahden lopputuloksen keskiarvo eika kumpikaan tapahdu.
    # Aloitustodennakoisyys EI ole se mita premium myy (se on xP ja
    # personointi), joten sen nayttaminen ei syo tuotetta - se tekee
    # suosituksesta luettavan.
    def _start_txt(p: dict) -> str:
        v = p.get("p_start")
        return f"starts {round(float(v) * 100)}%" if isinstance(v, (int, float)) \
            else "start probability in Premium"

    body = (
        f'<div class="stat-row">'
        f'<div class="stat"><b>{escape(top["web_name"])}</b>'
        f'<span>#1 pick · {escape(top["team_short"])} · {_start_txt(top)} '
        "· xP in Premium</span></div>"
        + "".join(
            f'<div class="stat"><b>{escape(p["web_name"])}</b>'
            f'<span>contender · {escape(p["team_short"])} · {_start_txt(p)} '
            "· xP in Premium</span></div>"
            for p in alts
        )
        + "</div>"
        '<p class="note"><strong>Start%</strong> is how likely the model thinks '
        "he is to be in the XI. Near 50 it is a coin flip, and a captaincy on a "
        "coin flip is a bet on team news. Check the press conference before you "
        "commit the armband.</p>"
        f"{UPSELL}{_cta()}"
        f'<p class="note">Updated {now.strftime("%d %b %Y")} · {DISCLAIMER}</p>'
    )
    jsonld = [{
        "@context": "https://schema.org", "@type": "WebPage",
        "name": title, "url": url, "description": desc,
        "isPartOf": {"@id": f"{BASE}/#organization"},
        "dateModified": now.strftime("%Y-%m-%d"),
    }]
    return _page(title, desc, url, hero, body, jsonld)


def render_differentials(diff: dict, now: datetime) -> str | None:
    players = (diff or {}).get("players") or []
    if not players:
        return None
    meta = diff.get("meta") or {}
    gw_txt = f"GW{meta['gw']}" if meta.get("gw") else "this gameweek"
    top = players[0]
    url = f"{BASE}/fpl/differentials"
    title = f"Best FPL Differentials {gw_txt}: Low-Owned Model Picks | GoalIQ"
    # 3.8.2026 PREMIUM-VUOTO KIINNI (sama silmays kuin best-captain):
    # DifferentialsSection on appissa premium (FantasyTools.tsx:3424) eika
    # siina ole free-teaseria, joten xP-luku ei saa nakya julkisella sivulla.
    # Omistus-% JAA: se on FPL:n omaa julkista dataa, ei mallin tuotos.
    desc = (
        f"GoalIQ's model differential for {gw_txt}: {top['web_name']} "
        f"({top['team_short']}), owned by just {top['owned_pct']}% of managers. "
        f"Expected points and {len(players)} more low-owned picks in GoalIQ Premium."
    )
    hero = (
        f"<h1>Best FPL differentials, {escape(gw_txt)}</h1>"
        f'<p class="lede">A differential is a low-owned player (under 10% '
        f"ownership) the model rates far higher than the crowd does. Today's "
        f"top model differential:</p>"
    )
    body = (
        f'<div class="stat-row">'
        f'<div class="stat"><b>{escape(top["web_name"])}</b>'
        f'<span>{escape(top["team_short"])} · owned {top["owned_pct"]}% · '
        f"xP in Premium</span></div>"
        f'<div class="stat"><b>+{len(players) - 1} more</b>'
        f"<span>full differential list in Premium</span></div>"
        f"</div>"
        f"{UPSELL}{_cta()}"
        f'<p class="note">Updated {now.strftime("%d %b %Y")} · {DISCLAIMER}</p>'
    )
    jsonld = [{
        "@context": "https://schema.org", "@type": "WebPage",
        "name": title, "url": url, "description": desc,
        "isPartOf": {"@id": f"{BASE}/#organization"},
        "dateModified": now.strftime("%Y-%m-%d"),
    }]
    return _page(title, desc, url, hero, body, jsonld)


def render_price_changes(pw: dict, now: datetime) -> str:
    meta = (pw or {}).get("meta") or {}
    risers = (pw or {}).get("risers") or []
    fallers = (pw or {}).get("fallers") or []
    url = f"{BASE}/fpl/price-changes"
    title = "FPL Price Changes Tonight: Predicted Risers & Fallers | GoalIQ"
    desc = (
        "Predicted FPL price changes from GoalIQ's transfer-velocity model: "
        "tonight's likely risers and fallers, updated daily. Free, no sign-in."
    )

    def rows(items, label):
        if not items:
            return ""
        lines = "".join(
            f'<div class="mrow"><div><strong>{escape(p["web_name"])}</strong>'
            f'<div class="meta">£{p["now_cost"]:.1f}m · confidence '
            f'{round(float(p.get("confidence") or 0) * 100)}%</div></div>'
            f'<span class="pick">{label}</span></div>'
            for p in items[:10]
        )
        return f'<div class="card">{lines}</div>'

    if not risers and not fallers:
        content = (
            f'<div class="card"><p class="lede" style="margin:0">'
            f'{escape(meta.get("note") or "Price watch goes live when the FPL game opens for the new season.")}'
            f"</p></div>"
        )
    else:
        content = (
            ("<h2>Predicted risers</h2>" + rows(risers, "rising")) if risers else ""
        ) + (
            ("<h2>Predicted fallers</h2>" + rows(fallers, "falling")) if fallers else ""
        )
    hero = (
        "<h1>FPL price changes: predicted risers and fallers</h1>"
        '<p class="lede">GoalIQ tracks net transfer velocity to estimate which '
        "players are about to rise or fall in price. Free on the web and in the "
        "app, updated daily.</p>"
    )
    body = (
        f"{content}"
        f"{UPSELL}{_cta()}"
        f'<p class="note">Updated {now.strftime("%d %b %Y")} · '
        f'{escape(meta.get("disclaimer") or "")} {DISCLAIMER}</p>'
    )
    jsonld = [{
        "@context": "https://schema.org", "@type": "WebPage",
        "name": title, "url": url, "description": desc,
        "isPartOf": {"@id": f"{BASE}/#organization"},
        "dateModified": now.strftime("%Y-%m-%d"),
    }]
    return _page(title, desc, url, hero, body, jsonld)


# Joukkuevarit lyhytkoodilla. LAHDE: web/pro-spa/src/lib/teamColors.ts
# (joka on generoitu mobiilin lib/teamMeta.ts:sta) -> sama vari kaikilla
# kolmella pinnalla. Klubien primary-varit ovat julkista tietoa.
#
# IP-TURVA: emme kayta pelaajakuvia emmeka klubien krestejä. Ne ovat Premier
# Leaguen/klubien tekijanoikeus- ja tavaramerkkiaineistoa, ja appi on
# molemmissa kaupoissa IP-puhtaana. Tassa renderoidaan NEUTRAALI paitasiluetti
# joukkueen varilla + lyhenne, sama SVG-polku kuin TeamKit.svelte/TeamKit.tsx.
_TEAM_COLORS = {
    "ARS": ("#EF0107", "#FFFFFF"), "AVL": ("#670E36", "#FFFFFF"),
    "BOU": ("#DA291C", "#FFFFFF"), "BRE": ("#E30613", "#FFFFFF"),
    "BHA": ("#0057B8", "#FFFFFF"), "BUR": ("#6C1D45", "#FFFFFF"),
    "CHE": ("#034694", "#FFFFFF"), "COV": ("#009CD8", "#FFFFFF"),
    "CRY": ("#1B458F", "#FFFFFF"), "EVE": ("#003399", "#FFFFFF"),
    "FUL": ("#000000", "#FFFFFF"), "HUL": ("#F0A800", "#000000"),
    "IPS": ("#4172B5", "#FFFFFF"), "LEE": ("#FFCD00", "#1D428A"),
    "LEI": ("#003090", "#FFFFFF"), "LIV": ("#C8102E", "#FFFFFF"),
    "MCI": ("#6CABDD", "#FFFFFF"), "MUN": ("#DA291C", "#FFFFFF"),
    "NEW": ("#241F20", "#FFFFFF"), "NFO": ("#DD0000", "#FFFFFF"),
    "SHU": ("#EE2737", "#FFFFFF"), "SOU": ("#D71920", "#FFFFFF"),
    "SUN": ("#EB172B", "#FFFFFF"), "TOT": ("#132257", "#FFFFFF"),
    "WHU": ("#7A263A", "#FFFFFF"), "WOL": ("#FDB913", "#231F20"),
}

# Sama siluetti kuin TeamKit.svelte / TeamKit.tsx (1:1).
_JERSEY = ("M 33 15 L 43 9 C 46 15 54 15 57 9 L 67 15 L 84 27 L 76 42 L 67 36 "
           "L 67 86 Q 67 90 63 90 L 37 90 Q 33 90 33 86 L 33 36 L 24 42 L 16 27 Z")
_SLEEVE_L = "M 33 15 L 16 27 L 24 42 L 33 36 Z"
_SLEEVE_R = "M 67 15 L 84 27 L 76 42 L 67 36 Z"


def _hash_color(name: str) -> str:
    """Deterministinen fallback, peili teamColors.ts:n hashColorista."""
    h = 0
    for ch in name:
        h = (h * 31 + ord(ch)) & 0xFFFFFF
    return f"hsl({h % 360}, 45%, 32%)"


def _team_color(short: str) -> tuple[str, str]:
    hit = _TEAM_COLORS.get((short or "").upper())
    return hit if hit else (_hash_color(short or "?"), "#FFFFFF")


def _darken(hex_color: str, factor: float = 0.7) -> str:
    m = re.fullmatch(r"#?([0-9a-fA-F]{6})", (hex_color or "").strip())
    if not m:
        return hex_color
    n = int(m.group(1), 16)
    parts = [max(0, round(((n >> s) & 0xFF) * factor)) for s in (16, 8, 0)]
    return "#{:02x}{:02x}{:02x}".format(*parts)


def _kit_defs(shorts) -> str:
    """Yksi <symbol> per joukkue kerran sivun alussa.

    MIKSI: rivikohtainen inline-SVG toisti saman polun 373 kertaa ja kasvatti
    sivun 175 kB -> 468 kB. Joukkueita on ~20, joten symboli per joukkue +
    pieni <use> per rivi pitaa sivun kevyena.
    """
    out = []
    for s in sorted({(x or "").upper() for x in shorts if x}):
        color, _ = _team_color(s)
        sleeve = _darken(color)
        # EI lyhennetta paidan sisalle: 26 px:ssa se on lukukelvoton ja sotkee
        # siluetin, ja sama lyhenne on jo paidan vieressa omana solunaan.
        # (TeamKit.svelte/tsx pitaa tekstin, koska ne renderoivat 44 px:ssa.)
        out.append(
            f'<symbol id="k{escape(s)}" viewBox="0 0 100 100">'
            f'<path d="{_JERSEY}" fill="{color}"/>'
            f'<path d="{_SLEEVE_L}" fill="{sleeve}"/>'
            f'<path d="{_SLEEVE_R}" fill="{sleeve}"/>'
            f'<path d="{_JERSEY}" fill="none" stroke="rgba(10,8,32,0.28)" '
            f'stroke-width="3" stroke-linejoin="round"/>'
            f"</symbol>"
        )
    return ('<svg width="0" height="0" style="position:absolute" '
            'aria-hidden="true"><defs>' + "".join(out) + "</defs></svg>")


def _kit_svg(short: str, size: int = 26) -> str:
    """Viittaus valmiiseen symboliin. Ei krestia, ei sponsoria, ei pelaajakuvaa."""
    s = escape((short or "").upper())
    return (f'<svg class="kit" width="{size}" height="{size}" aria-hidden="true">'
            f'<use href="#k{s}"/></svg>')


XI_NAILED_FLOOR = 0.75


def _xi_start_risk(xi) -> str:
    """Nosta esiin ne XI:n pelaajat jotka EIVAT ole varmoja avaajia (9.8).

    Sivu suosittelee yhdentoista pelaajan joukkuetta ja nayttaa jokaisen xP:n,
    mutta ei kertonut kuinka varma kukin paikka on. 32 % kaikista pelaajista on
    vyohykkeella p_start 0,35-0,70, jossa xP on kahden lopputuloksen keskiarvo
    eika kumpikaan tapahdu — eli XI:n kokonaisluku voi levata pelaajilla jotka
    eivat pelaa lainkaan.

    Numero jokaiseen paitaan sotkisi kentan, joten nostetaan vain poikkeamat.
    Kynnys 0,75: sen ylapuolella pelaaja on kaytannossa naulattu.
    """
    risky = [p for p in xi
             if isinstance(p.get("p_start"), (int, float))
             and p["p_start"] < XI_NAILED_FLOOR]
    if not risky:
        # Prosentti johdetaan vakiosta: kovakoodattuna se valehtelisi heti kun
        # XI_NAILED_FLOOR muuttuu (havaittu negatiivisessa kontrollissa 9.8).
        return ('<p class="note"><strong>Every player in this XI projects as a '
                "nailed starter</strong> (start probability "
                f"{round(XI_NAILED_FLOOR * 100)}% or higher). "
                "The total does not rest on anyone who might be benched.</p>")
    risky.sort(key=lambda p: p["p_start"])
    names = ", ".join(
        f"{escape(p['web_name'])} {round(p['p_start'] * 100)}%" for p in risky)
    return ('<p class="note"><strong>Not everyone here is nailed.</strong> '
            f"{names}. Those totals are an average of two outcomes, playing "
            "and not playing, so the XI total is less certain than it looks. "
            "Check team news before you copy it.</p>")


def render_model_xi(xp: dict, now: datetime) -> str | None:
    """Model XI kenttagrafiikkana (26.7).

    MIKSI: sivustolla ei ollut yhtaan grafiikkaa, ja "beat the model" -liigalla
    ei ollut kotisivua. Mallin oma XI on jo olemassa oleva kasite (se postataan
    someen gen_card.py:lla) mutta se ei nakynyt webissa missaan.

    XI tulee fpl_rate_team.optimal_budget_xi():sta = SAMA heuristiikka kuin
    rate-my-teamin benchmark, joten sivu ja tuote eivat voi eriytya.
    """
    from src.models.fpl_rate_team import (BUDGET_TENTHS, POS_NAME,
                                          optimal_budget_xi)
    players = xp.get("players") or []
    if not xp.get("meta", {}).get("available") or not players:
        return None
    et = {"GKP": 1, "DEF": 2, "MID": 3, "FWD": 4}
    pool = []
    for p in players:
        t = et.get(p.get("pos"))
        if t is None or p.get("price") in (None, ""):
            continue
        pool.append({
            # 28.7: id ja xmins pakollisia - penkkivalinta tarvitsee molemmat
            # (duplikaattisuoja + pelattavuusvaatimus).
            "id": p.get("id"),
            "xmins": p.get("xmins"),
            "element_type": t,
            "price": int(round(float(p["price"]) * 10)),   # tenths
            "club": p.get("team_short") or p.get("team"),
            "xp_horizon_total": float(p.get("xp_horizon_total") or 0.0),
            "xp_per_gw": float(p.get("xp_per_gw") or 0.0),
            "web_name": p.get("web_name") or "",
            "team_short": p.get("team_short") or "",
        })
    xi = optimal_budget_xi(pool)
    if not xi:
        return None

    rows = {t: [p for p in xi if p["element_type"] == t] for t in (1, 2, 3, 4)}
    for t in rows:
        rows[t].sort(key=lambda p: p["xp_horizon_total"], reverse=True)
    shape = "-".join(str(len(rows[t])) for t in (2, 3, 4))
    total_xp = sum(p["xp_horizon_total"] for p in xi)
    cost = sum(p["price"] for p in xi) / 10.0

    def line(ps: list[dict]) -> str:
        cells = "".join(
            '<div class="xip">'
            f'{_kit_svg(p["team_short"], size=44)}'
            f'<b>{escape(p["web_name"])}</b>'
            f'<span>{p["xp_horizon_total"]:.1f} xP</span>'
            "</div>"
            for p in ps
        )
        return f'<div class="xirow">{cells}</div>'

    # 28.7 (Villen havainto): penkki nakyviin. Vertailukohta on KOKO 15, ja
    # penkin pelattavuus on osa sen uskottavuutta - "halvimmat mahdolliset"
    # -penkki ei ole joukkue jonka kukaan voisi oikeasti pelata kauden lapi.
    from src.models.fpl_rate_team import bench_of_last_optimum
    bench = bench_of_last_optimum()
    bench_cost = sum(p["price"] for p in bench) / 10.0
    bench_block = ""
    if bench:
        bench_block = (
            '<h2 class="bench-h">Bench</h2>'
            f'<p class="muted">The other four in the 15, {bench_cost:.1f}m. '
            "Outfield bench players must project at least 45 expected minutes "
            "a game, so the squad can cover a blank without a transfer. The "
            "backup keeper is the cheapest available: he only plays if the "
            "first choice does not.</p>"
            + line(sorted(bench, key=lambda p: (p["element_type"],
                                                -p["xp_horizon_total"]))))

    pitch = ('<div class="pitch">'
             + "".join(line(rows[t]) for t in (1, 2, 3, 4))
             + "</div>" + bench_block)

    url = f"{BASE}/fpl/model-xi"
    title = "The GoalIQ Model XI: best 100.0m FPL squad on xP | GoalIQ"
    desc = (f"The highest-scoring XI inside the 100.0m budget: {shape}, "
            f"{total_xp:.1f} projected points over the horizon, with a bench "
            f"that actually plays. Free, no sign-in, rebuilt daily.")
    # 28.7: vaite optimaalisuudesta VAIN kun ratkaisija on sen todistanut.
    # Ennen tata paivaa sivu vaitti "strongest" ahneesta heuristiikasta joka
    # jai tuotantodatalla 15.2 xP optimista.
    from src.models.fpl_rate_team import optimal_xi_proven
    claim = ("The highest-scoring XI that fits inside the standard 100.0m "
             "budget, proven optimal by exhaustive search"
             if optimal_xi_proven() else
             "The strongest XI the GoalIQ model found inside the standard "
             "100.0m budget")
    # 28.7 (Villen havainto): budjetti kattaa 15 pelaajaa, ei 11. Aiempi
    # vertailukohta varasi penkkiin halvimmat mahdolliset, mika on
    # epärealistista: siirtoja on rajallisesti, joten penkkiläinen on joskus
    # pakko pelauttaa. Sivun tekstin on kerrottava se, muuten luku nayttaa
    # paremmalta kuin mika on pelattavissa.
    hero = ("<h1>The Model XI</h1>"
            f'<p class="lede">{claim}, ranked on projected points. '
            "The budget has to cover a full 15, so the four on the bench are "
            "the cheapest players who still project real minutes: the squad "
            "can cover a blank without spending a transfer. "
            "This is the same squad logic the rate-my-team benchmark uses, so "
            "the page and the product cannot drift apart.</p>")
    body = (
        f'<div class="stat-row">'
        f'<div class="stat"><b>{shape}</b><span>Shape</span></div>'
        f'<div class="stat"><b>{total_xp:.1f}</b><span>Projected points, XI</span></div>'
        f'<div class="stat"><b>{cost:.1f}m</b><span>XI cost, {bench_cost:.1f}m on the bench</span></div>'
        f"</div>"
        f"{_kit_defs(p['team_short'] for p in list(xi) + list(bench))}"
        f"{pitch}"
        f"{_xi_start_risk(xi)}"
        '<p class="note">Shirts show club colours only. GoalIQ is not '
        "affiliated with the Premier League and uses no club badges or player "
        "images. Projected points are model estimates, not betting advice.</p>"
        '<div class="rec">The model plays this season in a public mini-league. '
        '<a href="https://fantasy.premierleague.com/leagues/auto-join/jgi6j9">'
        "Join with code jgi6j9</a> and try to beat it. Season winner gets a "
        "year of Premium, free.</div>"
        f"{UPSELL}{_cta()}"
        f'<p class="note">Updated {now.strftime("%d %b %Y")} · {DISCLAIMER}</p>'
    )
    jsonld = [{
        "@context": "https://schema.org", "@type": "WebPage",
        "name": title, "url": url, "description": desc,
        "isPartOf": {"@id": f"{BASE}/#organization"},
        "dateModified": now.strftime("%Y-%m-%d"),
    }]
    return _page(title, desc, url, hero, body, jsonld)


def _xg_payload(leaders: dict) -> str:
    """Kompakti JSON selainlaskentaa varten: [nimi, joukkue, pos, hinta,
    [[min, xg, xa, xgi], ...enintaan 10 viimeisinta]].

    Selain laskee tasta 3/5/10 pelin ikkunat seka per-game- ja per-90-luvut,
    joten yksi payload kattaa lajittelun, suodattimet ja ikkunavalinnan ilman
    yhtaan API-kutsua. Ikkunasemantiikka on sama kuin palvelimella
    (fpl_leaders._window_rows = recent_games[-window:]) -> JS kayttaa
    slice(-w), jolloin luvut tasmaavat bitilleen server-renderoidyn
    oletustaulukon kanssa.
    """
    out = []
    for p in leaders.get("players") or []:
        games = p.get("recent_games") or []
        if not games:
            continue
        rows = [[
            int(g.get("minutes") or 0),
            round(float(g.get("xg") or 0.0), 2),
            round(float(g.get("xa") or 0.0), 2),
            round(float(g.get("xgi") or 0.0), 2),
        ] for g in games[-10:]]
        s = p.get("season") or {}
        out.append([
            p.get("web_name", ""), p.get("team_short", ""), p.get("pos", ""),
            round(float(p.get("price") or 0.0), 1), rows,
            # kausitotaalit: [minuutit, avaukset, xG, xA, xGI]
            [int(s.get("mins") or 0), int(s.get("starts") or 0),
             float(s.get("xg") or 0.0), float(s.get("xa") or 0.0),
             float(s.get("xgi") or 0.0)],
            # paidan varit [pohja, hiha, teksti] -> JS piirtaa saman kitin
            list(_team_color(p.get("team_short", ""))[:1])
            + [_darken(_team_color(p.get("team_short", ""))[0])]
            + [_team_color(p.get("team_short", ""))[1]],
        ])
    return json.dumps(out, separators=(",", ":"), ensure_ascii=False)


# Selainlogiikka: ikkuna (3/5/10), per game vs per 90, lajittelu, suodattimet.
# Ei em dashia missaan nakyvassa tekstissa (viestintatyyli SS1b).
XG_JS = """
<script>
(function(){
 var D=window.__XG__||[],w=5,per90=false,pos='',team='',key=5,desc=true;
 // Show 100 rows by default. WHY: 373 rows = ~5000 DOM nodes, and every
 // control click rebuilt them all through innerHTML -> the page lagged
 // badly. 100 covers practically everything, and "show all" is one click
 // away. The payload still holds everything, so filtering and sorting work
 // on the full data - only the DISPLAY is capped.
 var LIMIT=100,showAll=false;
 // Same neutral shirt silhouette as in server rendering and in
 // TeamKit.svelte/TeamKit.tsx. No crest, no player likeness (IP).
 var JP='M 33 15 L 43 9 C 46 15 54 15 57 9 L 67 15 L 84 27 L 76 42 L 67 36 '
  +'L 67 86 Q 67 90 63 90 L 37 90 Q 33 90 33 86 L 33 36 L 24 42 L 16 27 Z';
 function kit(c,lbl){
  // Points at the same <symbol> library the server renders once.
  return '<svg class="kit" width="26" height="26" aria-hidden="true">'
   +'<use href="#k'+(lbl||'').toUpperCase()+'"/></svg>';
 }
 // Minutes threshold. Per 90 is broken without it: a player with 2 minutes
 // tops the list as pure noise. The threshold is VISIBLE and adjustable,
 // not a silent hide: the user sees which filter is on and can remove it.
 var minm=0;
 var tb=document.getElementById('xgb'),cnt=document.getElementById('xgc');
 if(!tb)return;
 function agg(p){
  if(w==='S'){
   // Full season: bootstrap totals. "Per game" mode shows TOTALS (per
   // match is not meaningful for the season: we have starts, not
   // appearances), "Per 90" divides by minutes.
   var s=p[5]||[0,0,0,0,0],d=per90?(s[0]/90):1;
   if(!d)d=1;
   return {n:p[0],t:p[1],p:p[2],c:p[3],g:s[1],m:s[0],k:p[6],
           xg:s[2]/d,xa:s[3]/d,xgi:s[4]/d};
  }
  var g=p[4].slice(-w),m=0,xg=0,xa=0,xgi=0;
  for(var i=0;i<g.length;i++){m+=g[i][0];xg+=g[i][1];xa+=g[i][2];xgi+=g[i][3];}
  var d=per90?(m/90):g.length;
  if(!d)d=1;
  return {n:p[0],t:p[1],p:p[2],c:p[3],g:g.length,m:m,k:p[6],
          xg:xg/d,xa:xa/d,xgi:xgi/d};
 }
 function rows(){
  var r=[];
  for(var i=0;i<D.length;i++){
   // Sama saanto kuin palvelimella (fpl_leaders.rank_xg_leaders): maalivahdit
   // out by default, because this is an xG list, not a saves list. The GKP
   // filter shows them separately. Without this the page would give two
   // different numbers.
   if(D[i][2]==='GKP'&&pos!=='GKP')continue;
   if(pos&&D[i][2]!==pos)continue;
   if(team&&D[i][1]!==team)continue;
   var a=agg(D[i]);
   if(per90&&a.m<1)continue;
   if(a.m<minm)continue;
   r.push(a);
  }
  // Indeksit vastaavat sarakeotsikoita: 0 #, 1 Player, 2 Team, 3 Pos,
  // 4 Price, 5 xG, 6 xA, 7 xGI, 8 Mins, 9 Games.
  var ks=['n','n','t','p','c','xg','xa','xgi','m','g'];
  var k=ks[key];
  r.sort(function(x,y){
   var A=x[k],B=y[k];
   if(typeof A==='string')return desc?B.localeCompare(A):A.localeCompare(B);
   return desc?B-A:A-B;
  });
  return r;
 }
 function draw(){
  var r=rows(),h='';
  var n=showAll?r.length:Math.min(LIMIT,r.length);
  for(var i=0;i<n;i++){
   var a=r[i];
   h+='<tr><td class="n">'+(i+1)+'</td><td>'+a.n+'</td><td class="tm">'
    +kit(a.k,a.t)+'<span>'+a.t+'</span></td><td class="m-hide">'
    +a.p+'</td><td class="n m-hide">'+a.c.toFixed(1)+'</td><td class="n hi">'
    +a.xg.toFixed(2)+'</td><td class="n">'+a.xa.toFixed(2)+'</td><td class="n">'
    +a.xgi.toFixed(2)+'</td><td class="n m-hide">'+a.m
    +'</td><td class="n m-hide">'+a.g
    +'</td></tr>';
  }
  tb.innerHTML=h;
  var more=document.getElementById('xgmore');
  if(more){
   if(showAll||r.length<=LIMIT){more.style.display='none';}
   else{more.style.display='';
        more.textContent='Show all '+r.length+' players';}
  }
  // In season mode the last column holds STARTS, not appearances (the
  // bootstrap provides starts). The header says which one, no guessing.
  var hh=document.querySelectorAll('#xgt2 thead th');
  if(hh&&hh[9])hh[9].textContent=(w==='S')?'Starts':'Games';
  var span=(w==='S')?', full season':', last '+w+' games each';
  var rate=per90?', per 90 minutes':((w==='S')?', season totals':', per game');
  // The count must match what is on screen. Saying "400 players" while the
  // table renders 100 is the same failure as a claim the reader cannot check:
  // they count the rows and get a different answer from the page.
  var nn=showAll?r.length:Math.min(LIMIT,r.length);
  if(cnt)cnt.textContent=r.length+' players'+rate+span
   +(minm?', at least '+minm+' minutes played':', no minutes filter')
   +((nn<r.length)?'. Showing '+nn:'');
 }
 function chips(id,vals,cur,set){
  var e=document.getElementById(id);if(!e)return;
  e.innerHTML='';
  vals.forEach(function(v){
   var b=document.createElement('button');
   b.type='button';b.className='chip'+(cur()===v[0]?' on':'');b.textContent=v[1];
   b.onclick=function(){set(v[0]);sync();};
   e.appendChild(b);
  });
 }
 function sync(){
  chips('xgw',[[3,'3'],[5,'5'],[10,'10'],['S','Season']],
        function(){return w;},function(v){w=v;});
  // In season mode the left option is NOT per match but a sum (we have
  // starts, not appearances -> there is no true per-match divisor). The
  // chip text says so, otherwise 25.50 would read like a "per game" figure.
  chips('xgr',[[0,(w==='S')?'Total':'Per game'],[1,'Per 90']],
        function(){return per90?1:0;},
        function(v){
         var was=per90;per90=!!v;
         // Switching to per 90 turns the default minutes threshold on, and
         // leaving it turns it back off. The user's own choice stays in force
         // if they have already touched it on this screen.
         if(!was&&per90&&minm===0)minm=180;
         if(was&&!per90&&minm===180)minm=0;
        });
  chips('xgm',[[0,'Any'],[90,'90+'],[180,'180+'],[270,'270+']],
        function(){return minm;},function(v){minm=v;});
  chips('xgp',[['','All'],['GKP','GKP'],['DEF','DEF'],['MID','MID'],
        ['FWD','FWD']],function(){return pos;},function(v){pos=v;});
  draw();
 }
 var ts=[];for(var i=0;i<D.length;i++){if(ts.indexOf(D[i][1])<0)ts.push(D[i][1]);}
 ts.sort();
 var sel=document.getElementById('xgt');
 if(sel){
  sel.innerHTML='<option value="">All teams</option>';
  ts.forEach(function(t){
   var o=document.createElement('option');o.value=t;o.textContent=t;
   sel.appendChild(o);
  });
  sel.onchange=function(){team=sel.value;draw();};
 }
 var hs=document.querySelectorAll('#xgt2 thead th');
 for(var i=0;i<hs.length;i++){
  (function(i){
   hs[i].style.cursor='pointer';
   hs[i].onclick=function(){
    if(key===i)desc=!desc;else{key=i;desc=(i>=4);}
    draw();
   };
  })(i);
 }
 var moreBtn=document.getElementById('xgmore');
 if(moreBtn)moreBtn.onclick=function(){showAll=true;draw();};
 sync();
})();
</script>
"""


def render_xg_leaders(leaders: dict, now: datetime) -> str | None:
    """#128/#120: 'Top xG performers'.

    26.7: VAPAUTETTU. Aiemmin top-3 luvuilla + sijat 4-10 pelkkinä niminä
    ("Per-game numbers, xGI and position filters are on GoalIQ Premium").
    Maksumuuri hyödykedatan päällä ei puolustanut mitään — xG/xA/xGI on FPL:n
    itsensä julkaisemaa taaksepäin katsovaa dataa, jonka kilpailijat antavat
    ilmaiseksi. Nyt koko top-100 kaikilla sarakkeilla, ei porttia. Upsell
    siirtyi eteenpäin katsoviin mallin tuotoksiin (xP, captain ranker).
    Basis-label AINA näkyvissä (esikaudella 25/26-data, ei arvauksia)."""
    from src.models.fpl_leaders import rank_xg_leaders
    if not leaders.get("meta", {}).get("available"):
        return None
    # Ei keinotekoista kattoa: sivu listaa JOKAISEN pelaajan jolla on dataa
    # ikkunassa (~497). API:n top_n on rajattu 100:aan (le=100), mutta tämä
    # generaattori kutsuu mallia suoraan → ei kattoa. SPA/mobiili jäävät
    # 100:aan kunnes API:n raja nostetaan (vaatii backend-deployn).
    out = rank_xg_leaders(leaders, window=5, top_n=100000)
    rows = out["players"]
    if not rows:
        return None
    basis = out["meta"].get("basis_label") or ""
    url = f"{BASE}/fpl/xg-leaders"
    title = "Top xG Performers: FPL Expected Goals Leaders | GoalIQ"
    desc = (
        f"The top FPL expected-goals (xG) performers over each player's last "
        f"5 games: {rows[0]['web_name']} leads at {rows[0]['xg_per_game']:.2f} "
        f"xG per game. From official FPL match data, updated daily."
    )
    top3 = "".join(
        '<div class="stat">'
        f'<b>{escape(r["web_name"])}</b>'
        f'<span>#{i + 1} · {escape(r["team_short"])} · {r["xg_per_game"]:.2f} '
        f'xG/game · {r["games"]} games</span></div>'
        for i, r in enumerate(rows[:3])
    )
    # Koko lista taulukkona. Kaksi desimaalia on tarkoituksellista: 0.46 ja
    # 0.54 eivät saa näyttää samalta (FPL-yhteisön palaute 26.7).
    # Minuutit oletusikkunalle (w=5) server-renderoityyn tauluun. rank_xg_
    # leaders ei palauta minuutteja, joten haetaan ne samasta lahteesta id:lla.
    mins5 = {
        p["id"]: sum(int(g.get("minutes") or 0)
                     for g in (p.get("recent_games") or [])[-5:])
        for p in (leaders.get("players") or [])
    }
    trows = "".join(
        "<tr>"
        f'<td class="n">{i + 1}</td>'
        f'<td>{escape(r["web_name"])}</td>'
        f'<td class="tm">{_kit_svg(r["team_short"])}'
        f'<span>{escape(r["team_short"])}</span></td>'
        f'<td>{escape(r["pos"])}</td>'
        f'<td class="n">{r["price"]:.1f}</td>'
        f'<td class="n hi">{r["xg_per_game"]:.2f}</td>'
        f'<td class="n">{r["xa_per_game"]:.2f}</td>'
        f'<td class="n">{r["xgi_per_game"]:.2f}</td>'
        f'<td class="n">{mins5.get(r["id"], 0)}</td>'
        f'<td class="n">{r["games"]}</td>'
        "</tr>"
        # Palvelin renderoi 100 riviä, sama raja kuin JS:n oletus. Koko
        # aineisto on payloadissa (suodatus/lajittelu koskee kaikkia), joten
        # tama on puhtaasti DOM-painon rajaus: 373 riviä teki sivusta laggaavan.
        for i, r in enumerate(rows[:100])
    )
    kitdefs = _kit_defs(p.get("team_short") for p in (leaders.get("players") or []))
    controls = (
        '<div class="lbctl">'
        '<span class="lbl">Games</span><span id="xgw" class="chips"></span>'
        '<span class="lbl">Rate</span><span id="xgr" class="chips"></span>'
        '<span class="lbl">Min mins</span><span id="xgm" class="chips"></span>'
        '<span class="lbl">Position</span><span id="xgp" class="chips"></span>'
        '<select id="xgt" aria-label="Filter by team"></select>'
        "</div>"
        f'<p class="note" id="xgc">{len(rows)} players, per game, '
        "last 5 games each. Click a column to sort.</p>"
    )
    table = (
        '<div class="lb-wrap"><table class="lb" id="xgt2">'
        "<thead><tr>"
        # Mobiili (a) 9.8: Pos/Price/Mins/Games ovat suodatinkontekstia, xG/xA/
        # xGI on se mita sivulta tullaan katsomaan. Taulukko oli 589px = 1,5 x
        # puhelimen leveys; kuudella sarakkeella se mahtuu ilman vieritysta.
        # Sarakkeita EI poisteta DOMista -> JS:n indeksiviittaukset (hh[9])
        # ja lajittelu toimivat entiseen tapaan kaikilla leveyksilla.
        '<th class="n">#</th><th>Player</th><th>Team</th><th class="m-hide">Pos</th>'
        '<th class="n m-hide">Price</th><th class="n">xG</th>'
        '<th class="n">xA</th><th class="n">xGI</th>'
        '<th class="n m-hide">Mins</th><th class="n m-hide">Games</th>'
        "</tr></thead>"
        f'<tbody id="xgb">{trows}</tbody></table></div>'
        '<button type="button" class="chip" id="xgmore" '
        'style="margin:4px 0 8px;">Show all players</button>'
    )
    payload = (
        '<script id="xgdata">window.__XG__='
        f"{_xg_payload(leaders)};</script>"
    )
    hero = (
        "<h1>Top xG performers in FPL</h1>"
        '<p class="lede">Which players generate the most expected goals (xG) '
        "per game? Ranked over each player's last five played matches from "
        "official FPL match data. Free, no sign-in, updated daily.</p>"
    )
    body = (
        f'<p class="note"><strong>{escape(basis)}</strong></p>'
        f'<div class="stat-row">{top3}</div>'
        f"<h2>Full leaderboard: every player with data ({len(rows)})</h2>"
        '<p class="note">Two decimals, because 0.46 and 0.54 are not the same '
        "player. Switch between per game and per 90 minutes, pick a 3, 5 or 10 "
        "game window, filter by position or team, and sort any column. No "
        "cut-off and no sign-in: this is public FPL match data, so it is not "
        "behind a subscription.</p>"
        f"{kitdefs}{controls}{table}{payload}{XG_JS}"
        + f"{UPSELL}{_cta()}"
        + f'<p class="note">Updated {now.strftime("%d %b %Y")} · {DISCLAIMER}</p>'
    )
    jsonld = [{
        "@context": "https://schema.org", "@type": "WebPage",
        "name": title, "url": url, "description": desc,
        "isPartOf": {"@id": f"{BASE}/#organization"},
        "dateModified": now.strftime("%Y-%m-%d"),
    }]
    return _page(title, desc, url, hero, body, jsonld)


def render_defcon(leaders: dict, now: datetime) -> str | None:
    """#128/#120: 'Best DefCon players' — FPL:n defensive contribution
    -pistemekaniikan luotettavimmat lähteet. Top-3 luvuilla, loput niminä.

    #226-DC (1.8.2026): basis vaihdettu viimeisistä 5 pelistä KOKO KAUTEEN ja
    nimittäjä starteiksi. Kaksi syytä: (1) esikaudella "viimeiset 5" on
    mielivaltainen häntä edelliskaudesta, (2) tämä on julkinen sivu jonka luvut
    verrataan Premier Leaguen omaan DC-taulukkoon — eri nimittäjä tuotti eri
    prosentin samasta datasta. Season-basis ei ole saatavilla ennen kuin
    per-GW-matriisi on rakennettu → fallback vanhaan, ei tyhjää sivua."""
    from src.models.fpl_leaders import (load_defcon_gw, rank_defcon_leaders,
                                        rank_defcon_season)
    if not leaders.get("meta", {}).get("available"):
        return None
    try:
        out = rank_defcon_season(load_defcon_gw(), top_n=10)
    except Exception:
        out = rank_defcon_leaders(leaders, window=5, top_n=10)
    rows = out["players"]
    if not rows:
        return None
    per = "starts" if out["meta"].get("hit_rate_denominator") == "starts" else "games"
    basis = out["meta"].get("basis_label") or ""
    url = f"{BASE}/fpl/defcon"
    title = "Best DefCon Players: FPL Defensive Contribution Leaders | GoalIQ"
    desc = (
        f"The most reliable FPL defensive contribution (DefCon) point scorers: "
        f"{rows[0]['web_name']} hits the threshold in "
        f"{rows[0]['hit_rate_pct']:.0f}% of his {per}. Defenders need 10 CBIT, "
        f"midfielders and forwards 12 CBIRT, for 2 points."
    )
    top3 = "".join(
        '<div class="stat">'
        f'<b>{escape(r["web_name"])}</b>'
        f'<span>#{i + 1} · {escape(r["team_short"])} · '
        f'{r["hit_rate_pct"]:.0f}% of {per} · {r["dc_per_game"]:.1f} DC/game</span></div>'
        for i, r in enumerate(rows[:3])
    )
    rest = ", ".join(escape(r["web_name"]) for r in rows[3:10])
    hero = (
        "<h1>Best DefCon players in FPL</h1>"
        '<p class="lede">Defensive contribution (DefCon) is worth 2 FPL points '
        "a match: defenders need 10 combined clearances, blocks, interceptions "
        "and tackles (CBIT); midfielders and forwards need 12 including ball "
        "recoveries (CBIRT). These players hit the threshold most often.</p>"
    )
    pool = out["meta"].get("pool_min_starts")
    basis_note = (
        f"Hit rate is the share of a player's {per} that reached the "
        "threshold, the same basis the official FPL figures use."
        + (f" Ranking needs at least {pool} starts." if per == "starts" and pool
           else "")
    )
    body = (
        f'<p class="note"><strong>{escape(basis)}</strong></p>'
        f'<div class="stat-row">{top3}</div>'
        f'<p class="note">{escape(basis_note)}</p>'
        + (
            f'<p class="note">Also in the top 10: {rest}. Hit rates, DC per '
            f"game and position filters are on GoalIQ Premium.</p>"
            if rest
            else ""
        )
        + f"{UPSELL}{_cta()}"
        + f'<p class="note">Updated {now.strftime("%d %b %Y")} · {DISCLAIMER}</p>'
    )
    jsonld = [{
        "@context": "https://schema.org", "@type": "WebPage",
        "name": title, "url": url, "description": desc,
        "isPartOf": {"@id": f"{BASE}/#organization"},
        "dateModified": now.strftime("%Y-%m-%d"),
    }]
    return _page(title, desc, url, hero, body, jsonld)


# ---------------------------------------------------------------------------
# STATS ZONE (8.8) — ilmainen suodatettava raakataulukko
#
# Kysyntasignaali: FFH:n Opta-osio katosi maksavalta kayttajalta ja han kysyi
# julkisesti mista muualta saa "filter tables". Iso osa noista luvuista on
# FPL:n omassa APIssa, joka on Opta-lahtoinen -> jaettavissa ilmaiseksi.
#
# RAJA (Villen paatos 8.8): raakaluvut ilmaiseksi, johdettu DefCon-tracker
# (hit rate, kynnysosumat, projisoidut pisteet) pysyy premiumina. Tama sivu
# nayttaa dc-kertyman lukuna, EI trackeria.
# ---------------------------------------------------------------------------
STATS_GROUPS = [
    # pts on mukana Key-ryhmassa tarkoituksella: taulukko on oletuksena
    # jarjestetty pisteilla, ja lajitteluperusteen pitaa olla nakyvissa.
    # Ilman sita "#"-sarakkeen jarjestys naytti selittamattomalta.
    ("key", "Key", ["pts", "g", "a", "xg", "xa", "xgi"]),
    # HUOM: xG (FPL/Opta) EI ole tassa ryhmassa vaikka se sinne kuuluisi
    # aiheen puolesta. Syy: npxG tulee laukausdatan omasta mallista, ja
    # vierekkain ne nayttavat rikkinaisilta — Haaland xG 25.50 (Opta) ja
    # npxG 25.75 (laukausmalli) = rangaistuspotkuton luku on suurempi kuin
    # kokonaisluku, mika on mahdotonta jos oletat yhden mallin. FPL:n xG
    # asuu Key-ryhmassa, laukausmallin luvut taalla. Ei sekoiteta rivilla.
    ("threat", "Goal threat", ["sh", "sot", "box", "head", "hvc", "npxg",
                               "g"]),
    ("create", "Creativity", ["kp", "a", "xa", "xgi", "xgchain", "xgbuildup",
                              "creativity"]),
    ("defend", "Defending", ["tkl", "cbi", "rec", "dc", "cs", "gc", "xgc",
                             "saves"]),
    ("setp", "Set pieces", ["pen", "cor", "fk", "spxg"]),
    ("fpl", "FPL", ["pts", "ppg", "bps", "bonus", "ict", "yc", "rc"]),
]
STATS_LABELS = {
    "g": "G", "a": "A", "xg": "xG", "xa": "xA", "xgi": "xGI",
    "threat": "Threat", "creativity": "Creativity",
    "tkl": "Tackles", "cbi": "CBI", "rec": "Recov", "dc": "DefCon",
    "cs": "CS", "gc": "GC", "xgc": "xGC", "saves": "Saves",
    "pen": "Pens", "cor": "Corners", "fk": "FK",
    "pts": "Pts", "ppg": "PPG", "bps": "BPS", "bonus": "Bonus",
    "ict": "ICT", "yc": "YC", "rc": "RC",
    # Vaihe 2, Understat. "hvc" ei ole Optan big chance vaan oma xG-kynnys,
    # ja otsikko kertoo kynnyksen itse — vaara termi vuoti aiemmin neljalle
    # pinnalle, joten talla kertaa nimi on laskusaanto.
    "sh": "Shots", "sot": "On target", "box": "In box", "head": "Headers",
    "hvc": "xG 0.3+", "npxg": "npxG", "spxg": "Set-piece xG",
    "kp": "Key passes", "xgchain": "xGChain", "xgbuildup": "xGBuildup",
}
# Sarakekohtainen lahdemerkinta (title-tooltip). Ilman tata kayttaja ei nae
# rivilta kumpi luku on FPL:n virallinen ja kumpi laukausdatan oma malli.
STATS_SOURCE = {
    k: ("Shot-level data, own expected-goals model (not Opta)"
        if k in {"sh", "sot", "box", "head", "hvc", "npxg", "spxg", "kp",
                 "xgchain", "xgbuildup"}
        else "Official FPL API (Opta-sourced)")
    for k in STATS_LABELS
}
# Sarakkeet joita per 90 / per start skaalaa. ppg on jo suhdeluku ja
# erikoistilannejarjestykset ovat sijalukuja -> ei skaalata kumpaakaan.
STATS_RATEABLE = {
    "g", "a", "xg", "xa", "xgi", "threat", "creativity", "tkl", "cbi", "rec",
    "dc", "cs", "gc", "xgc", "saves", "pts", "bps", "bonus", "ict", "yc", "rc",
    "sh", "sot", "box", "head", "hvc", "npxg", "spxg", "kp", "xgchain",
    "xgbuildup",
}
STATS_INT = {"g", "a", "tkl", "cbi", "rec", "dc", "cs", "gc", "saves", "pts",
             "bps", "bonus", "yc", "rc", "sh", "sot", "box", "head", "hvc",
             "kp"}

STATS_JS = """
<script>
(function(){
 var D=window.__ST__||{c:[],r:[]},C={},i;
 for(i=0;i<D.c.length;i++){C[D.c[i]]=i;}
 var GROUPS=__GROUPS__,LAB=__LAB__,RATE=__RATE__,INT=__INT__,SRC=__SRC__,
     ORDCOLS=['pen','cor','fk'];
 var grp='key',mode='total',pos='',team='',minm=0,maxp=99,q='',
     sortKey='pts',desc=true,all=false;
 // --- Gameweek-ikkuna (Villen pyynto 9.8) --------------------------------
 // "GW1-6" cannot be derived from season totals after the fact, so the
 // per-gameweek rows come from a SEPARATE file and only WHEN the user
 // reaches for the filter: it is 551 KB (122 KB gzip), and the readers who
 // never use it should not pay for it.
 var GW=null,gwFrom=0,gwTo=0,gwLoading=false,gwCache={},GWI=null;
 // Only columns from the official FPL API can be windowed. Shot-level
 // numbers come from Understat with no per-gameweek breakdown, so
 // windowing them would be a lie: the page blocks it rather than show
 // zeros.
 var WINCOLS=['pts','g','a','tkl','cbi','rec','dc','cs','gc','saves','bps',
              'bonus','yc','rc','starts','mins','xg','xa','xgi','xgc','ict',
              'ppg'];
 var WINGROUPS=['key','defend','fpl'];
 function gwOn(){return !!(GW&&gwFrom);}
 function winRow(row){
  if(!gwOn())return null;
  var id=row[C.id],key=id+':'+gwFrom+':'+gwTo;
  if(gwCache[key]!==undefined)return gwCache[key];
  var rs=GW.players[id];
  if(!rs){gwCache[key]=null;return null;}
  var acc={n:0},i,m;
  for(m=1;m<GW.meta.cols.length;m++)acc[GW.meta.cols[m]]=0;
  for(i=0;i<rs.length;i++){
   var g=rs[i][0];
   if(g<gwFrom||g>gwTo)continue;
   acc.n++;
   for(m=1;m<GW.meta.cols.length;m++)acc[GW.meta.cols[m]]+=rs[i][m];
  }
  gwCache[key]=acc.n?acc:null;
  return gwCache[key];
 }
 var tb=document.getElementById('stb'),cnt=document.getElementById('stc'),
     head=document.getElementById('sth'),more=document.getElementById('stmore');
 function cols(){return GROUPS[grp];}
 function raw(row,k){
  var w=winRow(row);
  if(w&&WINCOLS.indexOf(k)>=0){
   if(k==='ppg')return w.n?w.pts/w.n:0;
   return w[k];
  }
  return row[C[k]];
 }
 function val(row,k){
  var v=raw(row,k);
  if(typeof v!=='number')return v;
  if(mode==='total'||RATE.indexOf(k)<0)return v;
  var d=mode==='p90'?raw(row,'mins')/90:raw(row,'starts');
  return d>0?v/d:0;
 }
 function fmt(row,k){
  var v=val(row,k);
  // null = the player was not matched to shot data. An empty dash is the
  // truth,
  // nolla olisi vaite ettei han laukonut kertaakaan.
  if(v===null||v===undefined)return '\\u2013';
  if(k==='pen'||k==='cor'||k==='fk')return v?String(v):'\\u2013';
  if(typeof v!=='number')return v;
  if(mode==='total'&&INT.indexOf(k)>=0)return String(v);
  return v.toFixed(2);
 }
 function rows(){
  var out=[],j;
  for(j=0;j<D.r.length;j++){
   var r=D.r[j];
   if(pos&&r[C.pos]!==pos)continue;
   if(team&&r[C.team]!==team)continue;
   if(gwOn()&&!winRow(r))continue;   // no minutes in the window
   if(raw(r,'mins')<minm)continue;
   if(r[C.price]>maxp)continue;
   if(q&&(r[C.name]+' '+r[C.team]).toLowerCase().indexOf(q)<0)continue;
   if(mode==='pstart'&&raw(r,'starts')<1)continue;
   out.push(r);
  }
  // Set-piece orders are ordinal ranks: 1 = first taker. Largest-first
  // would be backwards (5th in the penalty queue at the top), and
  // 0 = "not listed" must always sink to the end in both directions.
  var ORD=ORDCOLS.indexOf(sortKey)>=0;
  out.sort(function(a,b){
   var x=val(a,sortKey),y=val(b,sortKey);
   // An unknown value competes in neither sort direction.
   var xn=(x===null||x===undefined),yn=(y===null||y===undefined);
   if(xn||yn)return xn&&yn?0:(xn?1:-1);
   if(ORD){
    x=x?x:9999;y=y?y:9999;
    return desc?x-y:y-x;
   }
   if(typeof x==='string')return desc?(y>x?1:-1):(x>y?1:-1);
   return desc?y-x:x-y;
  });
  return out;
 }
 function draw(){
  // Mobile (a) 9 Aug: Pos/Price/Mins/Starts are filter context (they are
  // set with the buttons above), so a narrow screen shows Player + Team +
  // the chosen group's stats. The table was 657px = 1.7x a phone's width.
  // The columns are still in the DOM -> sorting and CSV are unchanged.
  var ks=cols(),h='<tr><th class="n">#</th><th data-k="name">Player</th>'
   +'<th data-k="team">Team</th><th class="m-hide" data-k="pos">Pos</th>'
   +'<th class="n m-hide" data-k="price">Price</th>'
   +'<th class="n m-hide" data-k="mins">Mins</th>',j;
  if(mode==='pstart')h+='<th class="n m-hide" data-k="starts">Starts</th>';
  for(j=0;j<ks.length;j++){
   h+='<th class="n" data-k="'+ks[j]+'" title="'+(SRC[ks[j]]||'')+'">'
     +LAB[ks[j]]
     +(sortKey===ks[j]?(desc?' \\u25be':' \\u25b4'):'')+'</th>';
  }
  head.innerHTML=h+'</tr>';
  var rs=rows(),n=all?rs.length:Math.min(100,rs.length),s='';
  for(j=0;j<n;j++){
   var r=rs[j];
   s+='<tr><td class="n">'+(j+1)+'</td><td>'+r[C.name]+'</td>'
    +'<td>'+r[C.team]+'</td><td class="m-hide">'+r[C.pos]+'</td>'
    +'<td class="n m-hide">'+r[C.price].toFixed(1)+'</td>'
    // Mins and Starts are windowable: without raw() they showed the season
    // lukuja GW-otsikon alla (Haaland 2953 min "GW1-6:lla"). Loytyi vasta
    // by looking at the live page, not from code.
    +'<td class="n m-hide">'+raw(r,'mins')+'</td>';
   if(mode==='pstart')s+='<td class="n m-hide">'+raw(r,'starts')+'</td>';
   for(var m=0;m<ks.length;m++){
    s+='<td class="n'+(ks[m]===sortKey?' hi':'')+'">'+fmt(r,ks[m])+'</td>';
   }
   s+='</tr>';
  }
  tb.innerHTML=s;
  var span=gwOn()?('GW'+gwFrom+(gwTo>gwFrom?'-'+gwTo:'')):'';
  var lbl=mode==='total'?(span?span+' totals':'season totals')
    :(mode==='p90'?'per 90 minutes':'per start');
  cnt.textContent=rs.length+' players, '+lbl
   +(minm?', '+minm+'+ minutes':'')+'. Showing '+n
   +'. Click a column to sort.';
  more.style.display=(!all&&rs.length>100)?'':'none';
  window.__STROWS__=rs;
 }
 function chips(id,items,cur,cb){
  var e=document.getElementById(id),s='',j;
  for(j=0;j<items.length;j++){
   s+='<button type="button" class="chip'+(items[j][0]===cur?' on':'')
    +'" data-v="'+items[j][0]+'">'+items[j][1]+'</button>';
  }
  e.innerHTML=s;
  e.onclick=function(ev){
   var b=ev.target.closest('button');if(!b)return;cb(b.getAttribute('data-v'));
  };
 }
 function paint(){
  chips('stg',GROUPKEYS,grp,function(v){grp=v;
   if(cols().indexOf(sortKey)<0){sortKey=cols()[0];desc=true;}paint();});
  chips('stm',[['total','Total'],['p90','Per 90'],['pstart','Per start']],
   mode,function(v){
    // Sample-size guard: 7 minutes played yields 12.86 tackles/90 and
    // takes over the top of the list. A rate without sample size is
    // misleading, so switching to rate mode raises the minimum to 450
    // minutes. The user can drop it back to zero in one click - it is not
    // blocked, it just stops being the default.
    if(v!=='total'&&mode==='total'&&minm===0){minm=450;}
    mode=v;paint();});
  chips('stp',[['','All'],['GKP','GKP'],['DEF','DEF'],['MID','MID'],
   ['FWD','FWD']],pos,function(v){pos=v;paint();});
  chips('stmin',[[0,'0'],[450,'450'],[900,'900'],[1500,'1500']],minm,
   function(v){minm=+v;paint();});
  draw();
 }
 var GROUPKEYS=[];
 for(var gk in GROUPS){if(GROUPS.hasOwnProperty(gk)){
  GROUPKEYS.push([gk,GROUPNAMES[gk]]);}}
 head.onclick=function(ev){
  var th=ev.target.closest('th');if(!th)return;
  var k=th.getAttribute('data-k');if(!k)return;
  if(k===sortKey){desc=!desc;}else{sortKey=k;desc=true;}
  draw();
 };
 more.onclick=function(){all=true;draw();};
 var ts={},j2;
 for(j2=0;j2<D.r.length;j2++){ts[D.r[j2][C.team]]=1;}
 var tsel=document.getElementById('stteam'),o='<option value="">All teams</option>',
     tk=Object.keys(ts).sort();
 for(j2=0;j2<tk.length;j2++){o+='<option value="'+tk[j2]+'">'+tk[j2]+'</option>';}
 tsel.innerHTML=o;
 tsel.onchange=function(){team=this.value;draw();};
 var psel=document.getElementById('stprice'),po='<option value="99">Any price</option>';
 for(var p=40;p<=155;p+=5){po+='<option value="'+(p/10)+'">Max '+(p/10).toFixed(1)+'</option>';}
 psel.innerHTML=po;
 psel.onchange=function(){maxp=+this.value;draw();};
 var qi=document.getElementById('stq');
 qi.oninput=function(){q=this.value.toLowerCase();all=false;draw();};

 // --- Gameweek-ikkuna ----------------------------------------------------
 var gwf=document.getElementById('stgwf'),gwt=document.getElementById('stgwt');
 function syncGroups(){
  // Shot-level groups cannot be windowed (Understat, no per-gameweek
  // breakdown). They lock visibly instead of showing zeros or season totals
  // under a gameweek heading, because either one would lie.
  var on=gwOn(),e=document.getElementById('stg');
  if(!e)return;
  var bs=e.querySelectorAll('.chip'),i;
  for(i=0;i<bs.length;i++){
   var k=bs[i].getAttribute('data-v'),lock=on&&WINGROUPS.indexOf(k)<0;
   bs[i].disabled=lock;
   bs[i].style.opacity=lock?'0.4':'';
   bs[i].title=lock?'No per-gameweek data for these columns':'';
  }
 }
 function applyGw(){
  var f=gwf&&gwf.value?+gwf.value:0,t=gwt&&gwt.value?+gwt.value:0;
  if(f&&t&&t<f){t=f;if(gwt)gwt.value=String(t);}
  gwFrom=f;gwTo=t;gwCache={};
  if(gwOn()&&WINGROUPS.indexOf(grp)<0){grp='key';sync();}
  syncGroups();draw();
 }
 function loadGw(cb){
  if(GW||gwLoading)return cb&&cb();
  gwLoading=true;
  if(cnt)cnt.textContent='Loading gameweek data…';
  fetch('/fpl/player-gw.json').then(function(r){
   if(!r.ok)throw new Error(r.status);return r.json();
  }).then(function(j){
   GW=j;gwLoading=false;cb&&cb();
  })['catch'](function(){
   gwLoading=false;
   // A failed load returns the picker to season mode AND says so. Falling
   // back silently would look exactly like a window that works.
   if(gwf)gwf.value='';
   gwFrom=0;gwTo=0;syncGroups();draw();
   if(cnt)cnt.textContent='Could not load gameweek data. Showing season totals.';
  });
 }
 if(gwf){
  gwf.onchange=function(){
   if(!this.value){applyGw();return;}
   loadGw(applyGw);
  };
 }
 if(gwt)gwt.onchange=function(){if(gwf&&gwf.value)loadGw(applyGw);};
 document.getElementById('stcsv').onclick=function(){
  var ks=cols(),hdr=['Player','Team','Pos','Price','Mins'];
  if(mode==='pstart')hdr.push('Starts');
  for(var j=0;j<ks.length;j++){hdr.push(LAB[ks[j]]);}
  var lines=[hdr.join(',')],rs=window.__STROWS__||[];
  for(var m=0;m<rs.length;m++){
   var r=rs[m],line=['"'+String(r[C.name]).replace(/"/g,'""')+'"',r[C.team],
    r[C.pos],r[C.price].toFixed(1),raw(r,'mins')];
   if(mode==='pstart')line.push(raw(r,'starts'));
   for(var n2=0;n2<ks.length;n2++){
    var v=val(r,ks[n2]);
    line.push(typeof v==='number'?v.toFixed(2):v);
   }
   lines.push(line.join(','));
  }
  var b=new Blob([lines.join('\\n')],{type:'text/csv'}),
      a=document.createElement('a');
  a.href=URL.createObjectURL(b);
  a.download='goaliq-fpl-stats-'+grp+'-'+mode+'.csv';
  document.body.appendChild(a);a.click();document.body.removeChild(a);
  setTimeout(function(){URL.revokeObjectURL(a.href);},1000);
 };
 paint();
})();
</script>
"""


def _stats_js() -> str:
    groups = {k: c for k, _, c in STATS_GROUPS}
    names = {k: n for k, n, _ in STATS_GROUPS}
    js = STATS_JS.replace("__GROUPS__", json.dumps(groups))
    js = js.replace("__LAB__", json.dumps(STATS_LABELS))
    js = js.replace("__RATE__", json.dumps(sorted(STATS_RATEABLE)))
    js = js.replace("__INT__", json.dumps(sorted(STATS_INT)))
    js = js.replace("__SRC__", json.dumps(STATS_SOURCE))
    # GROUPNAMES on erillinen, jotta ryhmien jarjestys sailyy chipeissa
    return js.replace(
        "(function(){",
        "(function(){\n var GROUPNAMES=" + json.dumps(names) + ";", 1)


# Jakokortin spec luetaan RENDEROIDYSTA taulukosta eika datasta: silloin
# kortti vastaa tasmalleen sita mita kayttaja nakee ruudulla (valittu
# tilastoryhma, lajittelu, suodattimet). Datasta rakennettu kortti voisi
# eriytya nakymasta huomaamatta.
_STATS_SPEC_FN = r"""function(){
  var tb=document.getElementById('stb'),head=document.getElementById('sth');
  if(!tb||!head)return null;
  var ths=head.querySelectorAll('th'),hiIdx=-1,i;
  for(i=0;i<ths.length;i++){
   if(/[▾▴]/.test(ths[i].textContent)){hiIdx=i;break;}
  }
  var label=(hiIdx>=0?ths[hiIdx].textContent:'Pts')
             .replace(/[▾▴]/g,'').trim();
  var rows=[],trs=tb.querySelectorAll('tr');
  for(i=0;i<trs.length&&rows.length<10;i++){
   var td=trs[i].children;
   if(td.length<4)continue;
   rows.push({rank:rows.length+1,
              name:(td[1].textContent||'').trim(),
              tag:(td[3]?td[3].textContent:'').trim(),
              team:(td[2].textContent||'').trim(),
              value:(hiIdx>=0&&td[hiIdx]?td[hiIdx].textContent:'').trim()});
  }
  // The subtitle collects the ACTIVE filters, not just a row count.
  // Without it a shared card would say "40 players" without saying they
  // are defenders, from one club, or under a price cap -- the reader
  // cannot know what they are looking at. Values are read from the visible
  // controls, so they cannot drift away from what is on screen.
  function chipOn(id){
   var e=document.getElementById(id);
   if(!e)return '';
   var b=e.querySelector('.chip.on');
   return b?(b.textContent||'').trim():'';
  }
  var bits=[];
  // Gameweek window FIRST: it is the strongest scope, and a shared card
  // without it would claim season numbers. Values are read from the pickers,
  // not from memory.
  var gf=document.getElementById('stgwf'),gt=document.getElementById('stgwt');
  if(gf&&gf.value){
   var a=gf.value,b=(gt&&gt.value)||a;
   bits.push('GW'+a+(b!==a?'-'+b:''));
  }
  var grp=chipOn('stg'); if(grp)bits.push(grp);
  var mode=chipOn('stm'); if(mode&&mode!=='Total')bits.push(mode.toLowerCase());
  var pos=chipOn('stp'); if(pos&&pos!=='All')bits.push(pos);
  var mins=chipOn('stmin'); if(mins&&mins!=='0')bits.push(mins+'+ mins');
  var tm=document.getElementById('stteam');
  if(tm&&tm.value)bits.push(tm.value);
  var pr=document.getElementById('stprice');
  // The price picker's default is the upper bound (99), which is NOT a
  // filter. Without
  // tarkistusta kortti sanoi "max 99" jokaisessa kuvassa.
  if(pr&&pr.value&&Number(pr.value)<99)bits.push('max '+Number(pr.value).toFixed(1)+'m');
  var qq=document.getElementById('stq');
  if(qq&&qq.value.trim())bits.push('"'+qq.value.trim()+'"');
  var cnt=document.getElementById('stc');
  var n=cnt?(cnt.textContent||'').split(' ')[0]:'';
  if(n)bits.push(n+' players');
  var sub=bits.join(' · ');
  return {title:('Top 10 by '+label).toUpperCase(),
          subtitle:sub,
          nameLabel:'PLAYER',
          valueLabel:label.toUpperCase(),
          // This card is RAW DATA, not a model prediction. The default footer
          // ("logged before kickoff, graded in public") would be a false claim.
          footNote:'free FPL stats at goaliq.app',
          footNote2:'official FPL API and shot-level data, not betting advice',
          rows:rows,
          fileName:'goaliq-fpl-stats-'
                   +label.toLowerCase().replace(/[^a-z0-9]+/g,'-')+'.png'};
 }"""


def _stats_gw_controls() -> str:
    """Gameweek-ikkunan valikot.

    Renderoidaan VAIN jos fpl/player-gw.json on olemassa. Jos data puuttuu,
    koko kontrolli jaa pois eika sivulle jaa nappia joka ei tee mitaan --
    rikkinainen suodatin on huonompi kuin puuttuva.
    """
    meta = _player_gw_meta()
    if not meta:
        return ""
    n = int(meta.get("max_gw") or 0)
    if n < 2:
        return ""
    opts_from = '<option value="">All gameweeks</option>' + "".join(
        f'<option value="{i}">From GW{i}</option>' for i in range(1, n + 1))
    opts_to = "".join(
        f'<option value="{i}"{" selected" if i == n else ""}>To GW{i}</option>'
        for i in range(1, n + 1))
    return (
        '<span class="lbl">Gameweeks</span>'
        f'<select id="stgwf" aria-label="From gameweek">{opts_from}</select>'
        f'<select id="stgwt" aria-label="To gameweek">{opts_to}</select>'
    )


def _player_gw_meta() -> dict | None:
    p = _FP_ROOT / "fpl" / "player-gw.json"
    if not p.exists():
        return None
    try:
        # Vain meta tarvitaan; tiedosto on 551 KB, joten se luetaan kerran.
        return json.loads(p.read_text(encoding="utf-8")).get("meta") or None
    except Exception:
        return None


def _stats_share_card() -> str:
    return SHARE_CARD_JS.replace("__CARD_ROWS_FN__", _STATS_SPEC_FN)


# Defence-sivun taulukko on palvelimella renderoity ja jarjestetty xGC:lla,
# joten kortti on aina "eniten xG:ta paastavat" -lista.
_DEFENCE_SPEC_FN = r"""function(){
  var t=document.querySelector('table.lb');
  if(!t)return null;
  var rows=[],trs=t.querySelectorAll('tbody tr'),i;
  for(i=0;i<trs.length&&rows.length<10;i++){
   var td=trs[i].children;
   if(td.length<3)continue;
   rows.push({rank:rows.length+1,
              name:(td[1].textContent||'').trim(),
              value:(td[2].textContent||'').trim()});
  }
  // The table is in ASCENDING order (Arsenal 0.91 = best defence). The
  // first proposed heading "MOST XG CONCEDED" claimed exactly the opposite
  // of the data, and it would have gone out to X as it was.
  return {title:'FEWEST XG CONCEDED',
          subtitle:'Expected goals conceded per match, lowest is best',
          nameLabel:'TEAM',
          valueLabel:'XGC',
          footNote:'shot-level data, own expected-goals model',
          footNote2:'free at goaliq.app, not betting advice',
          rows:rows,
          fileName:'goaliq-defence-xgc.png'};
 }"""


def _defence_share_card() -> str:
    return SHARE_CARD_JS.replace("__CARD_ROWS_FN__", _DEFENCE_SPEC_FN)


def render_stats(stats: dict, now: datetime) -> str | None:
    """Ilmainen Stats zone: koko pelaajajoukko, suodattimet, per 90 / per start.

    Palvelin renderoi 100 rivia default-ryhmalla (SEO + ei-JS), loput ja
    ryhmavaihdot klientissa. Sama 100-rivin DOM-katto kuin xg-leaders: 26.7
    todettiin etta 373 rivia x taysrender teki sivusta laggaavan."""
    meta = stats.get("meta") or {}
    rows = stats.get("players") or []
    if not meta.get("available") or not rows:
        return None
    cols = meta.get("cols") or []
    idx = {c: i for i, c in enumerate(cols)}
    basis = meta.get("basis_label") or ""
    url = f"{BASE}/fpl/stats"
    title = "Free FPL Player Stats: Shots, xG and Filterable Raw Numbers | GoalIQ"
    desc = (
        f"Every Premier League player's numbers in one filterable table: "
        f"shots, shots in the box, key passes, xG, xA, xGI, tackles, "
        f"recoveries and set-piece order. {len(rows)} players, per 90 or per "
        f"start, CSV export. Free, no sign-in."
    )
    keys = STATS_GROUPS[0][2]
    trows = "".join(
        "<tr>"
        f'<td class="n">{i + 1}</td>'
        f'<td>{escape(str(r[idx["name"]]))}</td>'
        f'<td>{escape(str(r[idx["team"]]))}</td>'
        f'<td class="m-hide">{escape(str(r[idx["pos"]]))}</td>'
        f'<td class="n m-hide">{r[idx["price"]]:.1f}</td>'
        f'<td class="n m-hide">{r[idx["mins"]]}</td>'
        + "".join(f'<td class="n">{r[idx[k]]}</td>' for k in keys)
        + "</tr>"
        for i, r in enumerate(rows[:100])
    )
    thead = (
        '<tr><th class="n">#</th><th data-k="name">Player</th>'
        '<th data-k="team">Team</th><th class="m-hide" data-k="pos">Pos</th>'
        '<th class="n m-hide" data-k="price">Price</th>'
        '<th class="n m-hide" data-k="mins">Mins</th>'
        + "".join(
            f'<th class="n" data-k="{k}" title="{STATS_SOURCE[k]}">'
            f'{STATS_LABELS[k]}</th>' for k in keys)
        + "</tr>"
    )
    controls = (
        '<div class="lbctl">'
        '<span class="lbl">Stats</span><span id="stg" class="chips"></span>'
        '<span class="lbl">Show</span><span id="stm" class="chips"></span>'
        "</div>"
        '<div class="lbctl">'
        '<span class="lbl">Position</span><span id="stp" class="chips"></span>'
        '<span class="lbl">Min mins</span><span id="stmin" class="chips"></span>'
        + _stats_gw_controls() +
        '<select id="stteam" aria-label="Filter by team"></select>'
        '<select id="stprice" aria-label="Maximum price"></select>'
        '<input id="stq" type="search" placeholder="Search player" '
        'aria-label="Search player" style="border:1px solid '
        'var(--line-strong);background:var(--paper);color:var(--cream);'
        'padding:7px 10px;font:inherit;font-size:13px;">'
        '<button type="button" class="chip" id="stcsv">Download CSV</button>'
        # Jakokortti (Villen pyynto 9.8): sama kortti kuin SPA:ssa ja
        # viikkopostauksessa. Vapaata dataa, joten ei premium-porttia.
        '<button type="button" class="chip" id="sharecard">Share as image</button>'
        "</div>"
        f'<p class="note" id="stc">{len(rows)} players, season totals. '
        "Showing 100. Click a column to sort, or press Show all players.</p>"
    )
    table = (
        '<div class="lb-wrap"><table class="lb">'
        f'<thead id="sth">{thead}</thead>'
        f'<tbody id="stb">{trows}</tbody></table></div>'
        '<button type="button" class="chip" id="stmore" '
        'style="margin:4px 0 8px;">Show all players</button>'
    )
    payload = ('<script id="stdata">window.__ST__='
               + json.dumps({"c": cols, "r": rows}, ensure_ascii=False)
               + ";</script>")
    hero = (
        "<h1>Free FPL player stats</h1>"
        '<p class="lede">The raw numbers, in one filterable table. Shots, '
        "shots in the box, key passes, expected goals and assists, tackles, "
        "recoveries, clean sheets, set-piece order and FPL scoring history "
        "for every player. Filter by position, team, price and minutes, "
        "switch to per 90 or per start, sort any column, export CSV. Free, "
        "no sign-in.</p>"
    )
    body = (
        f'<p class="note"><strong>{escape(basis)}</strong></p>'
        f"<h2>Every player with minutes ({len(rows)})</h2>"
        '<p class="note">Two sources, both stated plainly. Goals, assists, '
        "expected goals, expected assists, expected goals conceded, tackles, "
        "clearances, recoveries, clean sheets, saves and set-piece order come "
        "from the official FPL API, which is Opta-sourced, so there is no "
        "reason to put them behind a subscription and we do not. Shots, shots "
        "on target, shots in the box, headers, non-penalty xG, set-piece xG, "
        "key passes, xGChain and xGBuildup come from shot-level data with its "
        "own expected-goals model, so those numbers will not match Opta's and "
        "we do not call them Opta. In box means the shot was taken inside the "
        "penalty area. The xG 0.3+ column counts chances worth at least 0.3 "
        "expected goals, which is our own threshold and not anyone else's "
        # 15.8: portti blokkasi erikoistilanne-artikkelin koska teksti sanoi
        # "corner" ja sarake tarkoittaa laajempaa joukkoa. Sarakkeen sisalto
        # oli sivulla maarittelematta, joten lukija ei voinut ratkaista eroa
        # miltaan pinnalta. Maaritelma kuuluu sinne missa luku on.
        "definition of a big chance. Set-piece xG counts shots from corners, "
        "free kicks and other dead-ball situations, not corners alone, and the "
        "column does not split them. Our DefCon tracker (hit rate, thresholds, "
        "projected points) is a model output rather than a raw stat, so it "
        "lives in the app and the DefCon column here is the raw count. A dash "
        "means we have no data for that player, not zero.</p>"
        f"{controls}{table}{payload}{_stats_js()}{_stats_share_card()}"
        + f"{UPSELL}{_cta()}"
        + f'<p class="note">Updated {now.strftime("%d %b %Y")} · {DISCLAIMER}</p>'
    )
    # GEO/SEO: Dataset kertoo koneluettavasti MITA sarakkeita sivulla on ja
    # etta ne ovat ilmaisia. WebPage yksin ei kerro kumpaakaan, ja juuri nama
    # kaksi ovat ne joita hakukone tai kielimalli tarvitsee vastatakseen
    # kysymykseen "mista saa ilmaiseksi FPL:n laukausdataa".
    measured = [STATS_LABELS[k] for _, _, cols in STATS_GROUPS for k in cols]
    measured = list(dict.fromkeys(measured))
    jsonld = [
        {
            "@context": "https://schema.org", "@type": "WebPage",
            "name": title, "url": url, "description": desc,
            "isPartOf": {"@id": f"{BASE}/#organization"},
            "dateModified": now.strftime("%Y-%m-%d"),
        },
        {
            "@context": "https://schema.org", "@type": "Dataset",
            "name": "GoalIQ free FPL player stats",
            "url": url,
            "description": (
                "Season statistics for every Premier League player with "
                "minutes, covering shots, shots on target, shots in the box, "
                "headed attempts, non-penalty expected goals, set-piece "
                "expected goals, key passes, xGChain, xGBuildup, goals, "
                "assists, expected goals, expected assists, expected goal "
                "involvement, expected goals conceded, tackles, clearances "
                "blocks and interceptions, recoveries, defensive "
                "contribution, clean sheets, saves, penalty, corner and "
                "free-kick order, points, bonus, BPS and ICT."
            ),
            "isAccessibleForFree": True,
            "creator": {"@id": f"{BASE}/#organization"},
            "temporalCoverage": (meta.get("basis_season") or "").replace(
                "/", "-"),
            "variableMeasured": measured,
            "distribution": [{
                "@type": "DataDownload",
                "encodingFormat": "text/csv",
                "name": "CSV export of the current view",
            }],
        },
        {
            "@context": "https://schema.org", "@type": "BreadcrumbList",
            "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": "GoalIQ",
                 "item": BASE},
                {"@type": "ListItem", "position": 2, "name": "Free FPL tools",
                 "item": f"{BASE}/fpl.html"},
                {"@type": "ListItem", "position": 3, "name": "Player stats",
                 "item": url},
            ],
        },
    ]
    return _page(title, desc, url, hero, body, jsonld)



def _join_names(names: list[str]) -> str:
    """["A", "B", "C"] -> "A, B and C" (luettelo copyyn, ei koodilistana)."""
    safe = [escape(n) for n in names]
    if len(safe) == 1:
        return safe[0]
    return ", ".join(safe[:-1]) + " and " + safe[-1]

def render_defence(defence: dict, now: datetime) -> str | None:
    """Joukkuetason puolustusprofiili: MILLAISIA paikkoja puolustus paastaa.

    Taydentaa CS-% ja FDR -sivua, joka kertoo KUINKA PALJON muttei mista.
    FPL-hyoty: paalaukausmaara kertoo erikoistilanneriskin, keskiboksin
    paikat avoimen pelin heikkoudesta."""
    meta = defence.get("meta") or {}
    rows = defence.get("teams") or []
    if not meta.get("available") or not rows:
        return None
    season = meta.get("season", "")
    url = f"{BASE}/fpl/defence"
    title = "Premier League Defence Profiles: What Each Defence Concedes | GoalIQ"
    desc = (
        f"Not how many chances each Premier League defence concedes but what "
        f"kind: shots in the six-yard box, central box, wide box, edge of box "
        f"and long range, plus headers and set-piece xG. {season} data, free."
    )
    best = rows[0]
    most_headers = max(rows, key=lambda r: r["head_pm"])
    most_central = max(rows, key=lambda r: r["central_pm"])
    stat_row = "".join([
        '<div class="stat"><b>' + escape(best["team"]) + "</b>"
        f'<span>Fewest expected goals conceded: {best["xg_pm"]:.2f} per match</span></div>',
        '<div class="stat"><b>' + escape(most_headers["team"]) + "</b>"
        f'<span>Most headers faced: {most_headers["head_pm"]:.2f} per match</span></div>',
        '<div class="stat"><b>' + escape(most_central["team"]) + "</b>"
        f'<span>Most central-box shots faced: {most_central["central_pm"]:.2f} per match</span></div>',
    ])
    trows = "".join(
        "<tr>"
        f'<td class="n">{i + 1}</td>'
        f'<td>{escape(r["team"])}</td>'
        f'<td class="n hi">{r["xg_pm"]:.2f}</td>'
        f'<td class="n">{r["shots_pm"]:.1f}</td>'
        f'<td class="n">{r["six_pm"]:.2f}</td>'
        f'<td class="n m-hide">{r["central_pm"]:.2f}</td>'
        f'<td class="n m-hide">{r["wide_pm"]:.2f}</td>'
        f'<td class="n m-hide">{r["edge_pm"]:.2f}</td>'
        f'<td class="n m-hide">{r["far_pm"]:.2f}</td>'
        f'<td class="n">{r["head_pm"]:.2f}</td>'
        f'<td class="n m-hide">{r["sp_xg_pm"]:.2f}</td>'
        f'<td class="n">{r["box_share"]:.0f}%</td>'
        "</tr>"
        for i, r in enumerate(rows)
    )
    table = (
        '<div class="lb-wrap"><table class="lb">'
        "<thead><tr>"
        '<th class="n">#</th><th>Team</th>'
        '<th class="n" title="Expected goals conceded per match">xGC</th>'
        '<th class="n" title="Shots faced per match">Shots</th>'
        '<th class="n" title="Six-yard box, central">6yd</th>'
        '<th class="n m-hide" title="Penalty area, central band">Central</th>'
        '<th class="n m-hide" title="Penalty area, wide of the central band">Wide</th>'
        '<th class="n m-hide" title="Between 18 yards and the penalty area">Edge</th>'
        '<th class="n m-hide" title="Long range">Far</th>'
        '<th class="n" title="Headed attempts faced per match">Headers</th>'
        '<th class="n m-hide" title="Set-piece expected goals conceded per match">SP xG</th>'
        '<th class="n" title="Share of shots faced that came from inside the box">In box</th>'
        "</tr></thead>"
        f"<tbody>{trows}</tbody></table></div>"
        # Lede lupaa kaikki vyohykkeet, mutta kapea naytto nayttaa niista
        # viisi. Ilman tata rivia copy lupaisi enemman kuin ruutu antaa
        # (COPY-SYNC-GATE: pinta ja lupaus eivat saa eriytya).
        '<p class="note m-only">Central, wide, edge, long range and set-piece '
        "xG are in the same table on a wider screen.</p>"
        # Jakokortti (Villen pyynto 9.8)
        '<button type="button" class="chip" id="sharecard" '
        'style="margin:10px 0 4px;">Share as image</button>'
    )
    hero = (
        "<h1>What each Premier League defence concedes</h1>"
        '<p class="lede">Clean sheet probability tells you how likely a shutout is. '
        "This tells you what a defence actually gives up: shots from the "
        "six-yard box, the central penalty area, wide in the box, the edge and "
        "long range, plus headers faced and set-piece expected goals. Two "
        "defences can face the same number of shots and be nothing alike.</p>"
    )
    promoted = meta.get("promoted_no_data") or []
    relegated = meta.get("relegated_excluded") or []
    scope = (
        f"<strong>{escape(season)} season, per match.</strong> This covers the "
        f"{len(rows)} clubs that played in the Premier League last season and "
        "are still in it."
    )
    if promoted:
        scope += (
            " " + _join_names(promoted) + " came up from the Championship, so "
            "there is no Premier League shot data for them yet and they are "
            "not in the table."
        )
    if relegated:
        scope += (
            " " + _join_names(relegated) + " are in last season's data but "
            "went down, so they are left out."
        )
    body = (
        f'<p class="note">{scope}</p>'
        '<p class="note">Penalties are counted separately and left out of the '
        "zone columns, because they say nothing about defensive shape.</p>"
        f'<div class="stat-row">{stat_row}</div>'
        f"<h2>These {len(rows)} defences, sorted by expected goals conceded</h2>"
        '<p class="note">Why this matters for FPL: a defence that faces a lot '
        "of headers is a set-piece risk, so its clean sheet is fragile even "
        "against weak opponents. A defence that concedes mostly from long "
        "range is giving up volume without quality, and its goalkeeper is a "
        "save-points candidate. These come from shot-level data with its own "
        "expected-goals model, so the numbers are not Opta's and we do not "
        "call them that.</p>"
        f"{table}"
        + _defence_share_card()
        + f"{UPSELL}{_cta()}"
        + f'<p class="note">Updated {now.strftime("%d %b %Y")} · {DISCLAIMER}</p>'
    )
    jsonld = [
        {
            "@context": "https://schema.org", "@type": "WebPage",
            "name": title, "url": url, "description": desc,
            "isPartOf": {"@id": f"{BASE}/#organization"},
            "dateModified": now.strftime("%Y-%m-%d"),
        },
        {
            "@context": "https://schema.org", "@type": "Dataset",
            "name": "GoalIQ Premier League defence profiles",
            "url": url,
            "description": (
                "Per match, for every Premier League team: shots faced split "
                "by pitch zone (six-yard box, central penalty area, wide in "
                "the box, edge of the box, long range), headed attempts "
                "faced, set-piece expected goals conceded, expected goals "
                "conceded and the share of shots faced from inside the box. "
                "Penalties are counted separately and excluded from the zone "
                "columns."
            ),
            "isAccessibleForFree": True,
            "creator": {"@id": f"{BASE}/#organization"},
            "temporalCoverage": season.replace("/", "-"),
            "variableMeasured": [
                "Expected goals conceded per match", "Shots faced per match",
                "Six-yard box shots faced", "Central penalty area shots faced",
                "Wide penalty area shots faced", "Edge of box shots faced",
                "Long range shots faced", "Headed attempts faced",
                "Set-piece expected goals conceded", "Share of shots in box",
            ],
        },
        {
            "@context": "https://schema.org", "@type": "BreadcrumbList",
            "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": "GoalIQ",
                 "item": BASE},
                {"@type": "ListItem", "position": 2, "name": "Free FPL tools",
                 "item": f"{BASE}/fpl.html"},
                {"@type": "ListItem", "position": 3,
                 "name": "Defence profiles", "item": url},
            ],
        },
    ]
    return _page(title, desc, url, hero, body, jsonld)


# ---------------------------------------------------------------------------
# LUOTTAMUSLIPPU (10.8.2026) — lippu tulee ARTEFAKTISTA (build_fpl_xp.py), ei
# talta sivulta. Renderin tyo on vain nayttaa se. Nain SPA, mobiili, etusivu ja
# tama sivu lukevat saman lahteen eivatka voi eriytya.
#
# EI SUUNTAVAITETTA copyyn: kalibrointi kaatui 9.8. (hyokkays R^2 0,000,
# puolustus vaara merkki), joten lippu kertoo mika on muuttunut, ei mita siita
# seuraa. Tama on sitova rajaus kaikilla pinnoilla.
# ---------------------------------------------------------------------------
_TFLAG_LABEL = {"promoted": "promoted", "high_turnover": "turnover"}


def _tflag_html(row: dict) -> str:
    label = _TFLAG_LABEL.get(row.get("team_flag") or "")
    return f'<span class="tflag">{label}</span>' if label else ""


def _tflag_note(xp: dict, shown: list[dict], allrows: list[dict]) -> str:
    """Selite taulukon alle, vain jos jokin joukkue on liputettu.

    KORJAUS 10.8: ensimmainen versio selitti merkin jota sivulla ei nay.
    Liputetut ovat nousijoiden pelaajia, eika yksikaan yllä tallä hetkella
    top 100:aan (paras on #129), joten taulukossa on nolla merkkia. Selite
    kertoo sen nyt itse sen sijaan etta lukija etsisi merkkia turhaan.
    """
    tc = (xp.get("meta") or {}).get("team_confidence") or {}
    teams = tc.get("teams") or {}
    promoted = sorted(k for k, v in teams.items() if v.get("flag") == "promoted")
    churn = sorted(k for k, v in teams.items()
                   if v.get("flag") == "high_turnover")
    if not promoted and not churn:
        return ""
    bits = []
    if promoted:
        bits.append(
            f"<strong>{escape(', '.join(promoted))}</strong> "
            f"{'are' if len(promoted) > 1 else 'is'} newly promoted, so "
            "there are no Premier League results to fit a team rating on and "
            "the model starts them from a baseline.")
    if churn:
        bits.append(
            f"<strong>{escape(', '.join(churn))}</strong> lost an unusually "
            "large share of last season's minutes, and team ratings are "
            "fitted on results, so they still read as last season's squad.")
    n_shown = sum(1 for r in shown if r.get("team_flag"))
    if n_shown:
        where = (f" Their players carry a tag in the table, {n_shown} of them "
                 f"in this top 100.")
    else:
        best = next(((i + 1, r) for i, r in enumerate(allrows)
                     if r.get("team_flag")), None)
        where = (
            f" No flagged player makes this top 100. The highest is "
            f"{escape(best[1]['web_name'])} "
            f"({escape(best[1]['team_short'])}) at #{best[0]} of "
            f"{len(allrows)}." if best else "")
    return (
        '<p class="note"><strong>Flagged teams.</strong> ' + " ".join(bits) +
        " The flag means the projection is working with weaker information. "
        "It does not say which way that moves the number, because that is "
        "the part the data would not support." + where + "</p>")


def render_club_best(xp: dict, now: datetime) -> str | None:
    """Jokaisen seuran paras pelaaja per positio (14.8.2026).

    MIKSI TAMA SIVU ON OLEMASSA. Jakokortti (`gen_share_card.py club-best`)
    julkaisee samat 80 rivia kuvana, ja sen alatunniste ohjaa TANNE. Ilman
    tata sivua kortin luvut eivat olisi tarkistettavissa milläan ilmaisella
    pinnalla: `/api/fantasy/xp` on premium-portin takana maskattu top-10:een,
    ja `/fpl/expected-points` on `rows[:100]` — eli nousijaseurojen karjet
    (Belloumi, Tchaouna, Florentino, Smith Rowe) eivat mahdu koko liigan
    sadan parhaan joukkoon, ja ne ovat tasan ne rivit joita lukija
    todennakoisimmin haluaa tarkistaa.

    Laskenta on JAETTU MODUULI (`src/models/fpl_club_best.py`) kortin kanssa.
    Jos ne laskettaisiin erikseen, ne voisivat ajautua erilleen ja kortin
    vaite kaatuisi tasan silla reitilla jolla se piti todistaa.

    VAPAA/PREMIUM-RAJA: tama on seurakohtainen KARKI, ei koko lista — 80
    rivia 507:sta. Rate-my-team, siirtosuunnittelija ja kapteenirankkeri
    pysyvat premiumina. Sama peruste kuin /fpl/expected-points-rajassa:
    lista on sisaltoa, tyokalut ovat tuote.
    """
    meta = xp.get("meta") or {}
    players = xp.get("players") or []
    if not meta.get("available") or not players:
        return None

    n_gw = len(((players[0] if players else {}).get("gameweeks")) or []) or 6
    first_gw = meta.get("next_gameweek")
    window = f"GW{first_gw}-{first_gw + n_gw - 1}" if first_gw else f"next {n_gw} GWs"
    url = f"{BASE}/fpl/club-best"

    sections, all_clubs, lead = [], [], None
    for pos in POSITIONS:
        rows = club_best_rows(players, pos)
        if not rows:
            continue
        if pos == "MID":
            lead = rows[0]
        all_clubs.extend(r["club"] for r in rows)
        n_prior = sum(1 for r in rows if r["prior"])
        trows = "".join(
            "<tr>"
            f'<td class="n">{i + 1}</td>'
            f'<td>{escape(str(r["name"]))}'
            + (' <span class="flag" title="No Premier League games yet, '
               'role guessed from price">?</span>' if r["prior"] else "")
            + "</td>"
            f'<td class="tm">{_kit_svg(r["club"])}'
            f'<span>{escape(r["club"])}</span></td>'
            f'<td class="n m-hide">{r["price"]:.1f}</td>'
            f'<td class="n hi">{r["xp"]:.1f}</td>'
            f'<td>{escape(gap_text(r))}</td>'
            f'<td class="n m-hide">{r["xmins"]:.0f}</td>'
            "</tr>"
            for i, r in enumerate(rows)
        )
        note = ""
        if n_prior:
            note = (f'<p class="note">? = no Premier League games yet, role '
                    f"guessed from price ({n_prior} of {len(rows)}).</p>")
        sections.append(
            f'<h2 id="{pos.lower()}">Best {pos} at every club</h2>'
            '<div class="lb-wrap"><table class="lb">'
            "<thead><tr>"
            '<th class="n">#</th><th>Player</th><th>Club</th>'
            '<th class="n m-hide">Price</th>'
            f'<th class="n">{n_gw}GW xP</th>'
            "<th>Gap to club's 2nd</th>"
            '<th class="n m-hide">xMins</th>'
            "</tr></thead>"
            f"<tbody>{trows}</tbody></table></div>{note}"
        )
    if not sections:
        return None

    title = (f"Best FPL Player at Every Club by Position "
             f"({window}) | GoalIQ")
    desc = (
        f"Every Premier League club's best goalkeeper, defender, midfielder "
        f"and forward by projected points for {window}, with the gap to that "
        f"club's second option. Free, no sign-in."
    )
    lead_txt = ""
    if lead:
        lead_txt = (
            f" {escape(str(lead['name']))} leads the midfielders on "
            f"{lead['xp']:.1f} xP.")
    hero = (
        "<h1>The best player at every club, by position</h1>"
        '<p class="lede">Our match model projects every player over '
        f"{escape(window)}. This page shows the leader at each club in each "
        "position, plus the gap to that club's second option, which tells you "
        "whether the club has one obvious pick or a real choice."
        f"{lead_txt} Free, no sign-in, updated daily.</p>"
    )
    body = (
        f"{_kit_defs(all_clubs)}"
        + "".join(sections)
        # 🔴 15.8, Villen havainto: "aika huonosti erottee tuolta noi seurojen
        # omat sivut tosta club-best sivulta". Nama olivat pienessa harmaassa
        # alaviitteessa kahdenkymmenen nimen pilkkuluettelona, eli 20 sivua
        # piiloutui yhteen virkkeeseen. Nyt oma otsikko ja sama chip-tyyli
        # kuin seurasivujen valitsimessa: sama asia nayttaa samalta.
        + '<h2 id="club-pages">Every club has its own page</h2>'
        + '<p>Set-piece takers with the order FPL publishes, a predicted XI '
          "with start probabilities, and that club's best players in one "
          "place.</p>"
        + '<nav class="clubnav" aria-label="Club pages"><b>Clubs</b>'
        + "".join(
            f'<a href="/fpl/club/{s}">{escape(c)}</a>'
            for c, s in sorted(
                (c, CLUB_SLUGS[c]) for c in set(all_clubs) if c in CLUB_SLUGS))
        + "</nav>"
        + '<p class="note">The gap is measured against the same club and the '
          "same position, not against the row above. \"No 2nd projected\" "
          "means no other player at that club cleared the projection "
          "threshold, which is not the same as the club having only one.</p>"
        + f"{UPSELL}{_cta()}"
        + f'<p class="note">Updated {now.strftime("%d %b %Y")} · {DISCLAIMER}</p>'
    )
    jsonld = [{
        "@context": "https://schema.org", "@type": "WebPage",
        "name": title, "url": url, "description": desc,
        "isPartOf": {"@id": f"{BASE}/#organization"},
        "dateModified": now.strftime("%Y-%m-%d"),
    }]
    return _page(title, desc, url, hero, body, jsonld)



def render_team_news(xp: dict, now: datetime) -> str | None:
    """Team news, mutta KAANTEISENA: mita poissaolo maksaa pisteina (15.8.2026).

    MIKSI TAMA SIVU ON OLEMASSA. Villen kysymys 15.8: saisiko meille FFScoutin
    kaltaisen team news -pinnan, ja vaatiiko se toimittajan lehdistotilaisuuteen.

    Ei vaadi. Mittasin FPL:n bootstrapista samana paivana: 76 pelaajaa 587:sta
    kantaa VIRALLISTA news-tekstia aikaleimoineen (news, news_added,
    chance_of_playing_next_round). Se on sama pohja jolta FFScout lahtee, ja se
    on jo committoidussa artefaktissamme — tama sivu ei tee yhtaan uutta hakua.

    ERO KILPAILIJAAN ON KULMA, EI DATA. FFScout kertoo KUKA on ulkona. Me
    kerromme MITA SE MAKSAA: epavarmalla pelaajalla on xP-luku horisontille ja
    omistusprosentti, eli lukija nakee seka riskin etta sen laajuuden. Sita
    lukua ei voi kirjoittaa ilman mallia, joten sivua ei voi kopioida
    uutisvirrasta.

    EI TEKOALYARTIKKELEITA. Tama on generoitu taulukko mallin omista luvuista
    eika teeskentele journalismia. Peruste on mitattu: 9.-10.8 nelja
    Reddit-kayttajaa tunnisti tekstimme koneen kirjoittamaksi, ja ainoa
    puolustettava omaisuutemme on julkinen track record.

    JARJESTYS on omistusprosentti laskevasti eika xP: sivun kysymys on
    "koskeeko tama minua", ja omistus on FPL:n oma julkinen luku johon lukija
    voi verrata omaa joukkuettaan.
    """
    meta = xp.get("meta") or {}
    players = xp.get("players") or []
    excluded = xp.get("excluded") or []
    if not meta.get("available") or not players:
        return None

    n_gw = len(((players[0] if players else {}).get("gameweeks")) or []) or 6
    first_gw = meta.get("next_gameweek")
    window = f"GW{first_gw}-{first_gw + n_gw - 1}" if first_gw else f"next {n_gw} GWs"
    url = f"{BASE}/fpl/team-news"

    def _owned(r):
        try:
            return float(r.get("owned_pct") or 0.0)
        except (TypeError, ValueError):
            return 0.0

    # Ulkona = chance 0 kummastakin listasta. `excluded` sisaltaa myos
    # below_min_xp -rivit joilla ei ole uutista lainkaan -> ne EIVAT ole team
    # newsia ja ne rajautuvat pois uutistekstin olemassaololla.
    out_rows, doubt_rows = [], []
    for r in list(players) + list(excluded):
        news = (r.get("news") or "").strip()
        chance = r.get("chance_next")
        if not news or chance is None:
            continue
        (out_rows if chance == 0 else doubt_rows).append(r)
    out_rows.sort(key=_owned, reverse=True)
    doubt_rows.sort(key=_owned, reverse=True)
    if not out_rows and not doubt_rows:
        return None

    all_clubs = [r.get("team_short") for r in out_rows + doubt_rows
                 if r.get("team_short")]

    # 15.8, Villen saanto: "jos team news tms uutisissa on jotain pistedataa
    # tms niin sen tulee olla meidan omaa" — ja tarkennus: viime kauden
    # FPL-pisteet SAAVAT nakya, koska ne ovat muuttumaton fakta eivatka
    # johdettu luku. Ne jaavat siis omalle sarakkeelleen.
    #
    # Sen RINNALLE tulee oma lukumme, koska pelkka viime kausi ei vastaa siihen
    # mita lukija oikeasti kysyy ("pitaako minun tehda siirto"): kuka seurassa
    # korvaa ja mita meidan malli antaa hanelle. Laskenta on jaettu moduuli
    # club_best_rows, sama jota /fpl/club-best kayttaa, joten luvut eivat voi
    # ajautua erilleen.
    cover: dict[tuple[str, str], dict] = {}
    for _pos in POSITIONS:
        for _row in club_best_rows(players, _pos):
            cover[(_row["club"], _pos)] = _row

    def _cover_cell(r):
        """Seuran paras saatavilla oleva pelaaja samassa positiossa, meidan xP."""
        c = cover.get((r.get("team_short"), r.get("pos")))
        if not c or c.get("name") == r.get("web_name"):
            return "<td>-</td>"
        return (f'<td>{escape(str(c["name"]))} '
                f'<span class="hi">{c["xp"]:.1f}</span></td>')

    def _xp_cell(r):
        v = r.get("xp_horizon_total")
        if isinstance(v, (int, float)):
            return f'<td class="n hi">{v:.1f}</td>'
        # Poissaolevalla ei ole projektiota. Viime kauden pisteet kertovat mika
        # on poissa, ilman etta keksitaan xP:ta jota ei laskettu.
        ls = (r.get("last_season") or {}).get("points")
        if isinstance(ls, (int, float)):
            return f'<td class="n">{ls:.0f}<span class="m-hide"> last yr</span></td>'
        return '<td class="n">-</td>'

    sections = []
    if out_rows:
        trows = "".join(
            "<tr>"
            f'<td>{escape(str(r.get("web_name", "")))}</td>'
            f'<td class="tm">{_kit_svg(r.get("team_short", ""))}'
            f'<span>{escape(str(r.get("team_short", "")))}</span></td>'
            f'<td class="m-hide">{escape(str(r.get("pos", "")))}</td>'
            f'<td>{escape((r.get("news") or "").strip())}</td>'
            f'<td class="n">{_owned(r):.1f}%</td>'
            + _xp_cell(r)
            + _cover_cell(r)
            + "</tr>"
            for r in out_rows
        )
        sections.append(
            '<h2 id="out">Ruled out</h2>'
            '<div class="lb-wrap"><table class="lb">'
            "<thead><tr><th>Player</th><th>Club</th>"
            '<th class="m-hide">Pos</th><th>Status</th>'
            '<th class="n">Owned</th>'
            '<th class="n m-hide">Last season</th>'
            "<th>Who covers (our xP)</th>"
            "</tr></thead>"
            f"<tbody>{trows}</tbody></table></div>"
            '<p class="note">Last season is the player\'s final FPL total, '
            "a fixed historical number, not a projection. The model does not "
            "project a player it has ruled out, so the last column is our own "
            "number instead: the club's best available player in the same "
            "position and what we project them to score. A dash means no "
            "other player at that club cleared the projection threshold "
            "there.</p>"
        )

    if doubt_rows:
        trows = "".join(
            "<tr>"
            f'<td>{escape(str(r.get("web_name", "")))}</td>'
            f'<td class="tm">{_kit_svg(r.get("team_short", ""))}'
            f'<span>{escape(str(r.get("team_short", "")))}</span></td>'
            f'<td class="m-hide">{escape(str(r.get("pos", "")))}</td>'
            f'<td>{escape((r.get("news") or "").strip())}</td>'
            f'<td class="n">{int(r.get("chance_next") or 0)}%</td>'
            f'<td class="n">{_owned(r):.1f}%</td>'
            + _xp_cell(r)
            + "</tr>"
            for r in doubt_rows
        )
        sections.append(
            '<h2 id="doubtful">Doubtful</h2>'
            '<div class="lb-wrap"><table class="lb">'
            "<thead><tr><th>Player</th><th>Club</th>"
            '<th class="m-hide">Pos</th><th>Status</th>'
            '<th class="n">Chance</th><th class="n">Owned</th>'
            f'<th class="n">{n_gw}GW xP</th>'
            "</tr></thead>"
            f"<tbody>{trows}</tbody></table></div>"
            '<p class="note">The xP column already carries the flag: a '
            "reduced chance of playing lowers projected minutes, so the "
            "number you see is what the model expects including the doubt, "
            "not what the player would score if fully fit.</p>"
        )

    n_out, n_doubt = len(out_rows), len(doubt_rows)
    title = f"FPL Team News: Injuries and Suspensions ({window}) | GoalIQ"
    desc = (
        f"Every Premier League player currently ruled out or doubtful for "
        f"{window}, with ownership and what the model projects them to score. "
        f"{n_out} out, {n_doubt} doubtful. Free, no sign-in."
    )
    hero = (
        "<h1>Team news, with the points cost attached</h1>"
        '<p class="lede">Official FPL status for every ruled-out and doubtful '
        "player, sorted by how many managers own them. The difference from a "
        "team news list is the last column: our match model projects what each "
        f"doubtful player is still worth over {escape(window)}, with the "
        "reduced chance of playing already priced in. "
        f"{n_out} out, {n_doubt} doubtful. Updated daily, no sign-in.</p>"
    )
    body = (
        f"{_kit_defs(all_clubs)}"
        + "".join(sections)
        + '<p class="note">Status text comes from the official Fantasy '
          "Premier League feed, which is what clubs report. It is not a press "
          "conference summary: if a manager says a player trained today but "
          "the official status has not changed, this page will not know it "
          "yet.</p>"
        + f"{UPSELL}{_cta()}"
        + f'<p class="note">Updated {now.strftime("%d %b %Y")} · {DISCLAIMER}</p>'
    )
    jsonld = [{
        "@context": "https://schema.org", "@type": "WebPage",
        "name": title, "url": url, "description": desc,
        "isPartOf": {"@id": f"{BASE}/#organization"},
        "dateModified": now.strftime("%Y-%m-%d"),
    }]
    return _page(title, desc, url, hero, body, jsonld)



NOTES_PATH = ROOT / "data" / "fpl_notes.json"


def note_plain_text(n: dict) -> str:
    """Muistion KOKO teksti litteana, taulukon solut mukaan lukien.

    Tarvitaan koska `claims`-portti vertaa vaitteita muistion tekstiin, ja
    15.8 artikkelin luvut siirtyivat kappaleista datataulukkoon. Pelkka
    `" ".join(paragraphs)` kaatuu dict-lohkoon eika nakisi taulukon soluja
    vaikka ne ovat juuri ne luvut jotka lukija tarkistaa.
    """
    osat = []
    for p in n.get("paragraphs") or []:
        if isinstance(p, str):
            osat.append(p)
        elif isinstance(p, dict):
            if p.get("h2"):
                osat.append(str(p["h2"]))
            for solu in (p.get("head") or []):
                osat.append(str(solu))
            for rivi in (p.get("rows") or []):
                osat += [str(c) for c in rivi]
    return " ".join(osat)


def _note_block(p) -> str:
    """Yksi muistiolohko: merkkijono = kappale, dict = valiotsikko tai taulukko.

    MIKSI LAAJENNUS (15.8). Ensimmainen muistio oli neljan kappaleen mittainen
    ja litteä lista riitti. Villen pyytama LAAJA analyyttinen artikkeli (malli
    FFScoutin seuraennakot) ei mahdu siihen muotoon: siina on valiotsikot ja
    datataulukko, ja taulukon puristaminen kappaleeksi tekisi juuri sen mita
    artikkeli kritisoi — lukujen esittamisen muodossa jota ei voi lukea.

    Taaksepain yhteensopiva: merkkijono kayttaytyy tasan kuten ennen, joten
    olemassa oleva muistio renderoityy muuttumattomana.
    """
    if isinstance(p, str):
        return f"<p>{escape(p)}</p>"
    if isinstance(p, dict):
        if p.get("h2"):
            return f"<h3>{escape(str(p['h2']))}</h3>"
        rows = p.get("rows") or []
        if rows:
            head = p.get("head") or []
            th = (
                "<thead><tr>"
                + "".join(f"<th>{escape(str(c))}</th>" for c in head)
                + "</tr></thead>"
                if head
                else ""
            )
            body = "".join(
                "<tr>" + "".join(f"<td>{escape(str(c))}</td>" for c in r) + "</tr>"
                for r in rows
            )
            # Taulukko kaaritaan omaan vieritinsailioonsa: leveä sisalto ei saa
            # panna koko sivua vaakavieritykseen kapealla ruudulla.
            return f'<div class="tblwrap"><table class="note-tbl">{th}<tbody>{body}</tbody></table></div>'
    return ""


def render_notes(notes_doc: dict, now: datetime) -> str | None:
    """Kierrosmuistiot yhdella URLilla (15.8.2026, Villen GO).

    MIKSI YKSI SIVU EIKA SIVU PER MUISTIO. Erillinen sivu per muistio jaisi
    orvoksi sisaisessa linkityksessa — sama vika joka mitattiin samana paivana
    kahdesti (`team-news` ja `expected-points` puuttuivat `_TOOL_LINKS`:sta,
    ja `expected-points` on se sivu johon X-postaukset linkittavat). Yksi
    kertyva URL keskittaa linkit eika voi vanhentua kuratoidusta listasta.

    MIKSI TEKSTIA EI GENEROIDA. Villen kysymys 15.8 oli voiko naita
    automatisoida. Julkaisutarkistaja blokkasi ensimmaisen muistion kuudella
    loydoksella, joista NELJA koski tyylia: nolla lyhennetta 960 merkissa,
    pilkottu antiteesi, yhteenvetolause. Generaattori tuottaisi tasan ne.
    Teksti tulee siis `data/fpl_notes.json`:sta kasin kirjoitettuna kierrosta
    varten ja julkaisutarkistajan lapaisemana; tama funktio vain lataa sen.

    🔴 EI KUITENKAAN "ihmisen kirjoittama". Kirjoitin llms.txt:aan 15.8
    rivin "Written by a person, not generated" ja se oli VALHE: tekstin
    kirjoitti tama assistentti. Villen huomio samana paivana. Ero jota
    oikeasti ajoin takaa on generoitu vs kierrosta varten kirjoitettu, eika
    se ole sama asia kuin tekijyys. Kirjattu muisti: AI-kayttoa ei koskaan
    kiisteta.

    Automatisoitu on se osa joka petti MEKAANISESTI: `claims`-lista ajetaan
    `scripts/check_claim_route.py`:lla, joka tarkistaa etta jokainen luku on
    loydettavissa siita sivusta johon muistio linkittaa. Se on tarpeen koska
    15.8 kirjoitin vaitteen joka oli TOSI mutta jonka lukija ei olisi voinut
    tarkistaa.
    """
    notes = (notes_doc or {}).get("notes") or []
    if not notes:
        return None
    # Sama tasatilanne kuin etusivun nostossa: jarjestysnumero ratkaisee, jotta
    # saman paivan uudempi muistio on sivulla ylimpana.
    notes = [
        n for _, n in sorted(
            enumerate(notes),
            key=lambda p: (str(p[1].get("date") or ""), p[0]),
            reverse=True,
        )
    ]
    url = f"{BASE}/fpl/notes"

    blocks = []
    for n in notes:
        paras = "".join(_note_block(p) for p in n.get("paragraphs") or [])
        if not paras:
            continue
        check = str(n.get("check_url") or f"{BASE}/fpl/team-news")
        cta = escape(str(n.get("cta") or "Check the numbers"))
        # Otsikko linkittaa artikkelin omaan URLiin. Ilman tata kokoomasivu
        # olisi ainoa reitti, ja ulkoiset linkit osoittaisivat sivulle jonka
        # sisalto vaihtuu seuraavan muistion myota.
        slug_ = escape(str(n.get("slug") or ""))
        blocks.append(
            f'<h2 id="{slug_}">'
            f'<a href="/fpl/note/{slug_}">'
            f'{escape(str(n.get("title") or ""))}</a></h2>'
            f'<p class="note">{escape(str(n.get("date") or ""))}</p>'
            f'<div class="note-body">{paras}</div>'
            f'<p><a href="{escape(check)}">{cta}</a>.</p>'
            + _share_row(str(n.get("title") or ""),
                         f'{url}#{n.get("slug") or ""}')
        )
    if not blocks:
        return None

    latest = notes[0]
    title = "FPL notes from the model | GoalIQ"
    desc = (
        "Short gameweek notes where every number comes from our own match "
        "model and every one of them is on a free page you can open. Latest: "
        + str(latest.get("title") or "")
    )
    hero = (
        "<h1>Notes from the model</h1>"
        '<p class="lede">Short notes, one per gameweek, written when the '
        "numbers say something worth saying. Every figure here is our own "
        "model output and every one of them sits on a free page you can open "
        "and check. No sign-in.</p>"
    )
    body = (
        "".join(blocks)
        + f"{UPSELL}{_cta()}"
        + f'<p class="note">Updated {now.strftime("%d %b %Y")} · {DISCLAIMER}</p>'
    )
    jsonld = [{
        "@context": "https://schema.org", "@type": "WebPage",
        "name": title, "url": url, "description": desc,
        "isPartOf": {"@id": f"{BASE}/#organization"},
        "dateModified": now.strftime("%Y-%m-%d"),
    }]
    return _page(title, desc, url, hero, body, jsonld)



NOTE_DIR = OUT_DIR / "note"


def render_note_page(n: dict, now: datetime) -> str | None:
    """Yksi artikkeli omalla URLillaan: /fpl/note/<slug>.

    🔴 MIKSI TAMA LISATTIIN 15.8, vaikka `render_notes` valittiin nimenomaan
    YHDEKSI kertyvaksi URLiksi. Kaksi mitattua syyta, kumpikaan ei ollut
    tiedossa silloin:

    1. Alustan valimuisti. X tallentaa esikatselukortin sivukohtaisesti ja
       yhdistaa variantit `og:url`:n kautta, joten utm-parametri ei murra
       sita. Mitattu 15.8: `/fpl/stats` naytti X:ssa GENEERISTA korttia
       vaikka silla on ollut oma 8.8 lahtien, ja `/fpl/notes` naytti kortin
       ilman kuvaa lainkaan. Osoite jota alusta ei ole nahnyt haetaan
       tuoreena.
    2. Linkin hauraus. Kokoomasivulle osoittava linkki nayttaa sen artikkelin
       joka sattuu olemaan ylimpana. Uusi muistio tyontaa edellisen alemmas
       ilman etta mikaan huutaa, eli eilen jaettu linkki vie tanaan eri
       tekstiin.

    Kokoomasivu JAA paikalleen ja linkittaa naihin, joten alkuperainen
    orpoushuoli ei palaa: jokainen artikkeli on kahden sisaisen linkin paassa.

    og:image loytyy automaattisesti, koska kortti on nimetty artikkelin
    slugilla ja `_og_image()` johtaa nimen canonicalista.
    """
    slug = str(n.get("slug") or "").strip()
    otsikko = str(n.get("title") or "").strip()
    if not slug or not otsikko:
        return None
    paras = "".join(_note_block(x) for x in n.get("paragraphs") or [])
    if not paras:
        return None

    url = f"{BASE}/fpl/note/{slug}"
    tekstit = [x for x in (n.get("paragraphs") or []) if isinstance(x, str)]
    desc = (tekstit[0] if tekstit else otsikko)[:300]
    check = str(n.get("check_url") or f"{BASE}/fpl/stats")
    cta = escape(str(n.get("cta") or "Check the numbers"))

    body = (
        f'<p class="note">{escape(str(n.get("date") or ""))}</p>'
        f'<div class="note-body">{paras}</div>'
        f'<p><a href="{escape(check)}">{cta}</a>.</p>'
        + _share_row(otsikko, url)
        + '<p class="note-more"><a href="/fpl/notes">'
        "All notes from the model &#9656;</a></p>"
        + f"{UPSELL}{_cta()}"
        + f'<p class="note">Updated {now.strftime("%d %b %Y")} · {DISCLAIMER}</p>'
    )
    jsonld = [{
        "@context": "https://schema.org", "@type": "Article",
        "headline": otsikko, "url": url, "description": desc,
        "datePublished": str(n.get("date") or ""),
        "dateModified": now.strftime("%Y-%m-%d"),
        "isPartOf": {"@id": f"{BASE}/#organization"},
        "mainEntityOfPage": {"@type": "WebPage", "@id": url},
    }]
    return _page(f"{otsikko} | GoalIQ", desc, url,
                 f"<h1>{escape(otsikko)}</h1>", body, jsonld)


CLUB_DIR = OUT_DIR / "club"

# FPL:n lyhenne -> URL-slug. Kirjoitettu auki eika johdettu nimesta, koska
# slug on PYSYVA sopimus: johdettu slug muuttuisi jos seuran nayttonimi
# muuttuu, ja jokainen ulkoinen linkki katkeaisi hiljaa.
CLUB_SLUGS = {
    "ARS": "arsenal", "AVL": "aston-villa", "BOU": "bournemouth",
    "BRE": "brentford", "BHA": "brighton", "BUR": "burnley",
    "CHE": "chelsea", "COV": "coventry", "CRY": "crystal-palace",
    "EVE": "everton", "FUL": "fulham", "HUL": "hull", "IPS": "ipswich",
    "LEE": "leeds", "LEI": "leicester", "LIV": "liverpool",
    "MCI": "manchester-city", "MUN": "manchester-united",
    "NEW": "newcastle", "NFO": "nottingham-forest", "SOU": "southampton",
    "SUN": "sunderland", "TOT": "tottenham", "WHU": "west-ham",
    "WOL": "wolves",
}

_SP_LABELS = (("pens", "Penalties"), ("corners", "Corners"), ("fk", "Free kicks"))





def _share_row(title: str, url: str) -> str:
    """Jakonapit artikkelille (15.8, Villen pyynto).

    ESITAYTETTY TEKSTI ON VAIN OTSIKKO JA LINKKI. Se on tietoinen rajaus:
    jaettu teksti on julkista tekstia, ja jos se sisaltaisi vaitteen, se
    pitaisi ajaa julkaisutarkistajan lapi joka kerta kun sivu regeneroituu.
    Otsikko on jo portitettu sivun mukana, joten se on ainoa turvallinen
    esitaytto joka ei vanhene lukujen mukana.

    Ei JS:aa: intent-linkit toimivat ilman skriptia, ja sivut ovat staattisia.
    """
    from urllib.parse import quote
    teksti = quote(f"{title}\n\n{url}")
    x = f"https://twitter.com/intent/tweet?text={teksti}"
    bsky = f"https://bsky.app/intent/compose?text={teksti}"
    return (
        '<div class="share"><span>Share</span>'
        f'<a href="{x}" rel="noopener nofollow" target="_blank">X</a>'
        f'<a href="{bsky}" rel="noopener nofollow" target="_blank">Bluesky</a>'
        f'<a href="{escape(url)}">Link</a>'
        "</div>"
    )


def _club_switcher(current: str, saatavilla: set[str]) -> str:
    """Kaikki 20 seuraa linkkeina, nykyinen korostettuna.

    🔴 MITATTU 15.8: seurasivulta linkitettiin NOLLAAN toiseen seurasivuun.
    Sisaantulo oli kunnossa (club-best linkitti kaikkiin 20), mutta lukija
    joka oli Bournemouthin sivulla ei paassyt Arsenaliin ilman paluuta.
    Kahdenkymmenen sisarsivun setti ilman keskinaista linkitysta on
    kaksikymmenta umpikujaa.

    Sivuvaikutus joka on itse asiassa paavaikutus: jokainen sivu saa 19 uutta
    sisaantulevaa linkkia, mika on tasan se signaali jota GSC kaipasi 28.7.
    """
    # VAIN sivut jotka oikeasti kirjoitetaan. CLUB_SLUGS kattaa 24 seuraa
    # (nousijat ja putoajat mukana), mutta sivuja syntyy vain niille joilla on
    # projektio: ensimmainen versio linkitti neljaan 404:aan (BUR, LEI, SOU,
    # WOL). Kuollut linkki on pahempi kuin puuttuva.
    rivit = []
    for short, slug in sorted(CLUB_SLUGS.items(), key=lambda x: x[1]):
        if slug not in saatavilla:
            continue
        if slug == current:
            rivit.append(f'<b class="here">{escape(short)}</b>')
        else:
            rivit.append(f'<a href="/fpl/club/{slug}">{escape(short)}</a>')
    return (
        '<nav class="clubnav" aria-label="Other clubs">'
        "<b>Clubs</b>" + "".join(rivit) + "</nav>"
    )


def _no_history_flag(p: dict) -> str:
    """Merkinta pelaajalle jolla ei ole Valioliiga-historiaa.

    🔴 MITATTU 15.8, Villen havainto: "araujon projected points 8.7 kuulostaa
    liian matalalta, han siirtyi juuri barcelonasta". Luku ei ollut vaite
    laadusta vaan minuuteista: `xmins` 33.5 ja `predicted_starts` 38 %, koska
    `data_basis` on `no_history` eika minuuttimallilla ole mihin ankkuroida.

    Malli KERTOO taman kahdella kentalla, ja niita on 158/505. Ne saavat myos
    saman kovakoodatun 38,0 %:n oletuksen, eli luku on sama arvaus kaikille.
    Ensimmainen versioni seurasivuista pudotti lipun, joten lukija nakisi
    "8.7" ilman merkkia siita etta se on arvaus. `club-best` naytti taman
    oikein jo ennestaan — en vain kayttanyt sen konventiota.

    🔴 TOINEN LIPPU 16.8, Villen havainto: "arsenalilla ei edes ole
    odegaardia laitettu alotuksee". Odegaard EI ole `no_history` vaan
    tavallinen `pl_history`-rivi, joten yllakuvattu lippu ei koskenut hanta
    lainkaan. Mitattu: korrelaatio(viime kauden avaukset / 38, `p_start`) =
    0,785 (n=285), eli katkennut kausi painaa priorin alas ilman etta
    mikaan kertoo sita lukijalle. 1363 minuuttia ja 16 avausta luetaan
    rotaatiopelaajaksi.

    Lippu ei korjaa lukua eika kerro suuntaa. Se kertoo etta arvio nojaa
    lyhyeen otokseen.
    """
    if p.get("data_basis") == "no_history":
        return (' <span class="flag" title="No Premier League games yet, role '
                'and minutes estimated">?</span>')
    if p.get("minutes_basis_flag") == "short_season":
        mins = (p.get("last_season") or {}).get("minutes")
        return (' <span class="flag" title="Only '
                f'{mins} minutes last season, so this player&#x27;s minutes '
                'estimate rests on a short spell rather than a full one. It '
                'does not say which way the number is off">!</span>')
    return ""


def _set_piece_rows(players: list[dict]) -> str:
    """Erikoistilannevuorot jarjestysnumeron mukaan.

    FPL julkaisee jarjestyksen (1 = ensimmainen vuorossa). Naytetaan vain
    numerot jotka FPL on antanut — tyhja tarkoittaa ettei jarjestysta ole
    julkaistu, EI etta pelaaja ei ota niita. Se ero on kerrottava, koska
    esikaudella tyhjia on paljon.
    """
    out = []
    for avain, otsikko in _SP_LABELS:
        rivit = [(p, (p.get("set_pieces") or {}).get(avain)) for p in players]
        rivit = sorted(((p, n) for p, n in rivit if isinstance(n, int)),
                       key=lambda x: x[1])
        if not rivit:
            continue
        nimet = ", ".join(
            f'{escape(str(p["web_name"]))} <span class="hi">{n}</span>'
            for p, n in rivit[:4])
        out.append(f"<tr><td>{otsikko}</td><td>{nimet}</td></tr>")
    return "".join(out)


def _xi_rows(players: list[dict]) -> tuple[str, int, list[dict]]:
    """Ennustettu avauskokoonpano: paras 11 aloitustodennakoisyyden mukaan,
    positiorajoilla 1-4-4-2 -tyyliin taipuen. Palauttaa (rivit, n)."""
    # 🔴 Kayta JAETTUA POSITIONS-vakiota, ala kovakoodaa. Kirjoitin tahan
    # ensin {"GK": 1, ...} ja jokaisen 20 seuran "Predicted XI" renderoitui
    # KYMMENELLA pelaajalla ilman maalivahtia: FPL:n koodi on "GKP" eika "GK",
    # ja `src.models.fpl_club_best.POSITIONS` tiesi sen jo. Rivi nakyi vaarana
    # vasta valmiilla sivulla, ei koodia lukemalla.
    kiintio = dict(zip(POSITIONS, (1, 4, 4, 2)))
    valitut = []
    for pos, n in kiintio.items():
        ryhma = sorted(
            (p for p in players if p.get("pos") == pos
             and isinstance(p.get("predicted_starts"), (int, float))),
            key=lambda p: -p["predicted_starts"])
        valitut.extend(ryhma[:n])
    # 🔴 TAYDENNYS 11:een. Kiintio 1-4-4-2 ei tayty jos seuralla ei ole
    # tarpeeksi pelaajia jossakin positiossa: mitattu Liverpool, jolla on
    # projektiossa YKSI nimellinen hyokkaaja, jolloin XI jai kymmeneen.
    # Vajaa "Predicted XI" on nakyva virhe. Taytetaan parhailla jaljella
    # olevilla aloitustodennakoisyyden mukaan, mika on myos lahempana sita
    # miten seura oikeasti pelaa kuin tyhja paikka.
    if len(valitut) < 11:
        otetut = {id(p) for p in valitut}
        loput = sorted(
            (p for p in players
             if id(p) not in otetut
             and isinstance(p.get("predicted_starts"), (int, float))),
            key=lambda p: -p["predicted_starts"])
        valitut.extend(loput[:11 - len(valitut)])
    if len(valitut) < 11:
        return "", 0, []
    # Sama kovakoodaus oli myos tassa: "GK" ei osunut, joten maalivahti
    # sortautui listan HANNILLE. Kentalla se on absurdi jarjestys.
    jarj = {pos: i for i, pos in enumerate(POSITIONS)}
    valitut.sort(key=lambda p: (jarj.get(p.get("pos"), 9), -p["predicted_starts"]))
    rivit = "".join(
        "<tr>"
        f'<td>{escape(str(p["web_name"]))}{_no_history_flag(p)}</td>'
        f'<td class="m-hide">{escape(str(p.get("pos", "")))}</td>'
        f'<td class="n">{float(p.get("price") or 0):.1f}</td>'
        f'<td class="n hi">{p["predicted_starts"]:.0f}%</td>'
        "</tr>"
        for p in valitut)
    return rivit, len(valitut), valitut


def _xi_omissions(players: list[dict], valitut: list[dict]) -> str:
    """Liputetut pelaajat jotka JAIVAT ulos ennustetusta XI:sta.

    🔴 MIKSI TAMA ON ERI ASIA KUIN RIVIN LIPPU. Ville huomasi 16.8 ettei
    Arsenalin XI:ssa ole Odegaardia. Rivikohtainen "!" ei auta hanta
    lainkaan, koska Odegaard ei ole sivulla: hanta ei renderoida XI:hin
    eika kahdeksan parhaan listaan. Lippu nakyy vain niille jotka ovat jo
    nakyvissa, ja valitus koski nimenomaan puuttuvaa nimea.

    Tama rivi vastaa siihen kysymykseen suoraan: kuka jai ulos ja mihin
    lukuun se nojaa. Ei suuntavaitetta.
    """
    otetut = {id(p) for p in valitut}
    ulkona = [p for p in players
              if id(p) not in otetut
              and p.get("minutes_basis_flag") == "short_season"
              and isinstance(p.get("predicted_starts"), (int, float))]
    if not ulkona:
        return ""
    ulkona.sort(key=lambda p: -(p.get("price") or 0))
    osat = []
    for p in ulkona[:4]:
        mins = (p.get("last_season") or {}).get("minutes")
        osat.append(f'{escape(str(p["web_name"]))} '
                    f'({p["predicted_starts"]:.0f}%, {mins} min)')
    return ('<p class="note">Missing from that eleven, and the reason is the '
            "same in each case: they played a short season, so the estimate "
            "reads them as rotation. "
            + ", ".join(osat) + ".</p>")


def render_club_page(short: str, players: list[dict], meta: dict,
                     now: datetime, saatavilla: set[str] | None = None) -> str | None:
    """Yhden seuran esittelysivu (15.8.2026, Villen tilaus).

    MIKSI TAMA FORMAATTI. Ville antoi esimerkiksi FFScoutin seurakohtaisen
    ennakon (parhaat pelaajat, erikoistilannevuorot, ennustettu XI). Se on
    heilla proosaa; meilla se on DATAA, ja siksi se on ainoa artikkelityyppi
    jonka runko voidaan generoida ilman etta teksti alkaa kuulostaa koneelta.
    Generoitu taulukko ei teeskentele mielipidetta.

    Kolme osaa vastaavat esimerkin kolmea lupausta:
      1. Best players    xP-jarjestys, hinta ja omistus rinnalla
      2. Set-piece takers FPL:n julkaisema jarjestysnumero
      3. Predicted XI     aloitustodennakoisyys, ei arvaus

    REHELLISYYSRAJAUS joka on koodissa eika vain copyssa: tyhja
    erikoistilannevuoro tarkoittaa ettei FPL ole julkaissut jarjestysta, EI
    etta pelaaja ei ota niita. Esikaudella tyhjia on paljon, ja tuon eron
    piilottaminen tekisi sivusta itsevarmemman kuin data on.
    """
    if len(players) < 8:
        return None
    slug = CLUB_SLUGS.get(short)
    if not slug:
        return None
    nimi = str(players[0].get("team") or short)
    url = f"{BASE}/fpl/club/{slug}"
    n_gw = len(((players[0]).get("gameweeks")) or []) or 6
    first_gw = (meta or {}).get("next_gameweek")
    window = f"GW{first_gw}-{first_gw + n_gw - 1}" if first_gw else f"next {n_gw} GWs"

    karki = sorted(players, key=lambda p: -(p.get("xp_horizon_total") or 0))[:8]
    best_rows = "".join(
        "<tr>"
        f'<td class="n">{i + 1}</td>'
        f'<td>{escape(str(p["web_name"]))}{_no_history_flag(p)}</td>'
        f'<td class="m-hide">{escape(str(p.get("pos", "")))}</td>'
        f'<td class="n">{float(p.get("price") or 0):.1f}</td>'
        f'<td class="n m-hide">{float(p.get("owned_pct") or 0):.1f}%</td>'
        f'<td class="n hi">{float(p.get("xp_horizon_total") or 0):.1f}</td>'
        "</tr>"
        for i, p in enumerate(karki))

    osat = [
        f'<h2 id="best">{escape(nimi)} best players for {escape(window)}</h2>'
        '<div class="lb-wrap"><table class="lb">'
        '<thead><tr><th class="n">#</th><th>Player</th>'
        '<th class="m-hide">Pos</th><th class="n">Price</th>'
        '<th class="n m-hide">Owned</th>'
        f'<th class="n">{n_gw}GW xP</th></tr></thead>'
        f"<tbody>{best_rows}</tbody></table></div>"
    ]

    sp = _set_piece_rows(players)
    if sp:
        osat.append(
            '<h2 id="set-pieces">Set-piece takers</h2>'
            '<div class="lb-wrap"><table class="lb">'
            "<thead><tr><th>Situation</th><th>Order</th></tr></thead>"
            f"<tbody>{sp}</tbody></table></div>"
            # 🔴 16.8: edellinen versio sanoi etta nama pelaajat "all start
            # from the same default". Se on epatosi: PROMOTED_PRIOR_TIERS
            # antaa kolme eri arvoa (0.38 / 0.16 / 0.096) sen mukaan monesko
            # kallein pelaaja on klubinsa positioryhmassa. Lause selitti
            # samat luvut vaaralla syylla ja piilotti sen etta luku ON
            # roolin luenta, karkea mutta mitattu (Brier +13,8 %).
            '<p class="note">? = no Premier League games yet, so the start '
            "probability comes from where the player sits in his club's price "
            "order rather than from anything he has done here. Players on the "
            "same rung get the same number.</p>"
            '<p class="note">The number is the order FPL publishes, so 1 is '
            "first in line. An empty situation means FPL has not published an "
            "order for it, which is not the same as nobody taking them. "
            "Pre-season there are a lot of blanks.</p>")

    xi, n_xi, xi_valitut = _xi_rows(players)
    if xi:
        osat.append(
            '<h2 id="xi">Predicted XI</h2>'
            '<div class="lb-wrap"><table class="lb">'
            '<thead><tr><th>Player</th><th class="m-hide">Pos</th>'
            '<th class="n">Price</th><th class="n">Start</th></tr></thead>'
            f"<tbody>{xi}</tbody></table></div>"
            '<p class="note">This table answers one question: who starts. '
            "Projected points for the same players are in GoalIQ Premium, "
            "along with the tools that use them. "
            "Start is our projected chance of starting, not a "
            "lineup leak. We do not watch press conferences. The shape is the "
            "highest-probability starter at each position, so it will not "
            "always match the manager's formation.</p>"
            # 🔴 16.8: kaksi rajoitetta jotka lukija nakee ITSE sivulta, joten
            # ne on parempi sanoa kuin antaa hanen loytaa. Kumpikaan ei
            # kerro suuntaa: emme tieda kumpaan suuntaan luku on vaarassa.
            '<p class="note">Two things this table gets wrong in a way worth '
            "knowing. A player who missed most of last season is read as a "
            "rotation player, because the estimate leans on the minutes he "
            "actually played and it cannot tell an injury from a benching. "
            "Those names carry a ! here. And the shape is fixed, so a club "
            "that plays five in midfield will always have one real starter "
            "pushed out of this eleven.</p>"
            + _xi_omissions(players, xi_valitut))

    conf = ((meta or {}).get("team_confidence") or {}).get("teams", {}).get(nimi)
    if conf and conf.get("note"):
        osat.append(f'<h2 id="squad">Squad turnover</h2>'
                    f'<p>{escape(str(conf["note"]))}</p>')

    title = f"{nimi} FPL {escape(window)}: best players, set-piece takers, predicted XI | GoalIQ"
    lead = karki[0]
    desc = (
        f"{nimi}'s best FPL picks for {window} by projected points, who takes "
        f"their penalties and corners, and our predicted XI with start "
        f"probabilities. {lead['web_name']} leads on "
        f"{float(lead.get('xp_horizon_total') or 0):.1f} xP. Free, no sign-in."
    )
    hero = (
        f"<h1>{escape(nimi)}: best players, set pieces and a predicted XI</h1>"
        f'<p class="lede">Everything on this page comes from our own match '
        f"model over {escape(window)}. "
        f"{escape(str(lead['web_name']))} leads the squad on "
        f"{float(lead.get('xp_horizon_total') or 0):.1f} projected points. "
        "Free, no sign-in, updated daily.</p>"
    )
    body = (
        f"{_kit_defs([short])}"
        + _club_switcher(slug, saatavilla or {slug})
        + _share_row(f"{nimi} FPL {window}: best players, set pieces, XI", url)
        + "".join(osat)
        + f"{UPSELL}{_cta()}"
        + f'<p class="note">Updated {now.strftime("%d %b %Y")} · {DISCLAIMER}</p>'
    )
    jsonld = [{
        "@context": "https://schema.org", "@type": "WebPage",
        "name": title, "url": url, "description": desc,
        "isPartOf": {"@id": f"{BASE}/#organization"},
        "dateModified": now.strftime("%Y-%m-%d"),
    }]
    return _page(title, desc, url, hero, body, jsonld)


def render_predicted_lineups(xp: dict, now: datetime) -> str | None:
    """Kaikkien seurojen Model Predicted XI yhdella sivulla.

    MIKSI (15.8.2026, Villen tilaus). Kilpailijalla on yksi "Predicted
    Lineups" -tyokalu; meilla sama data oli olemassa mutta hajallaan 20
    seurasivulla, eli sita ei voinut selata eika loytaa yhdesta paikasta.

    🔴 NIMI ON "MODEL PREDICTED XI" EIKA "PREDICTED LINEUPS". Ero ei ole
    kosmeettinen. FFScoutin ja Roguen kokoonpanot nojaavat IHMISIIN:
    lehdistotilaisuudet, toimittajat, viime hetken tiedot. Meidan XI on
    mallin arvio aloitustodennakoisyyksista. Jos kutsuisimme sita samalla
    nimella, lupaisimme scout-tason tietoa jota meilla ei ole — ja se on
    tasan se virhe joka on tanaan jo kahdesti maksanut julkaisun.

    Vastineeksi annamme sen luvun jota HEILLA ei ole rivilla: kunkin
    pelaajan aloitustodennakoisyys prosenttina. Arvaus ilman lukua on
    mielipide; luku on tarkistettavissa jalkikateen.
    """
    meta = xp.get("meta") or {}
    players = xp.get("players") or []
    if not meta.get("available") or not players:
        return None
    per_club: dict[str, list[dict]] = {}
    for pl in players:
        s = pl.get("team_short")
        if s:
            per_club.setdefault(s, []).append(pl)

    lohkot = []
    n_klubia = 0
    for short, ryhma in sorted(per_club.items()):
        if short not in CLUB_SLUGS or len(ryhma) < 8:
            continue
        rivit, n, _ = _xi_rows(ryhma)
        if not rivit:
            continue
        n_klubia += 1
        slug = CLUB_SLUGS[short]
        lohkot.append(
            f'<h2 id="{slug}">{escape(str(ryhma[0].get("team") or short))}</h2>'
            '<div class="lb-wrap"><table class="lb">'
            '<thead><tr><th>Player</th><th class="m-hide">Pos</th>'
            '<th class="n">Price</th><th class="n">Start</th></tr></thead>'
            f"<tbody>{rivit}</tbody></table></div>"
            f'<p class="note"><a href="/fpl/club/{slug}">'
            # Sisempi lainausmerkki on HIPSU, ei kaksoislainaus. Sama merkki
            # f-stringin sisalla on laillinen vasta 3.12:sta (PEP 701), ja
            # CI ajaa 3.11:ta -> tama oli SyntaxError joka kaatoi KOKO
            # tests.yml-ajon 15.8 asti. Paikallisesti se ei nakynyt, koska
            # tama kone ajaa 3.14:aa.
            f"{escape(str(ryhma[0].get('team') or short))} club page &#9656;</a></p>"
        )
    if not lohkot:
        return None

    url = f"{BASE}/fpl/predicted-lineups"
    title = "Model Predicted XI for every Premier League club | GoalIQ"
    desc = (
        "The eleven our model expects to start for all 20 Premier League "
        "clubs, with each player's chance of starting. Not a lineup leak: "
        "these are projections from minutes history, not press conferences. "
        "Free, no sign-in."
    )
    hero = (
        "<h1>Model Predicted XI</h1>"
        '<p class="lede">The eleven our model expects to start at every club, '
        "with each player's projected chance of starting next to his name. "
        "This is a projection from minutes history, not a lineup leak. We do "
        "not watch press conferences, and when a manager surprises everyone "
        "this table will be wrong with him.</p>"
    )
    body = (
        f'<p class="note"><strong>{n_klubia} clubs</strong>. Start is the '
        "model's projected chance that the player is in the starting eleven, "
        "shown as a percentage so you can weigh it yourself. The shape is the "
        "highest-probability starter at each position, so it will not always "
        "match the manager's formation.</p>"
        + "".join(lohkot)
        + f"{UPSELL}{_cta()}"
        + f'<p class="note">Updated {now.strftime("%d %b %Y")} · {DISCLAIMER}</p>'
    )
    jsonld = [{
        "@context": "https://schema.org", "@type": "WebPage",
        "name": title, "url": url, "description": desc,
        "isPartOf": {"@id": f"{BASE}/#organization"},
        "dateModified": now.strftime("%Y-%m-%d"),
    }]
    return _page(title, desc, url, hero, body, jsonld)


def render_club_pages(xp: dict, now: datetime) -> list[str]:
    """Kirjoita jokaisen seuran sivu. Palauttaa kirjoitetut slugit."""
    meta = xp.get("meta") or {}
    players = xp.get("players") or []
    if not meta.get("available") or not players:
        return []
    per_club: dict[str, list[dict]] = {}
    for p in players:
        s = p.get("team_short")
        if s:
            per_club.setdefault(s, []).append(p)
    CLUB_DIR.mkdir(parents=True, exist_ok=True)
    # Laske ensin MITKA sivut syntyvat, jotta valitsin voi linkittaa vain
    # niihin. Sama kynnys kuin renderoijassa (alle 8 pelaajaa -> ei sivua).
    saatavilla = {
        CLUB_SLUGS[s] for s, g in per_club.items()
        if s in CLUB_SLUGS and len(g) >= 8
    }
    tehdyt = []
    for short, ryhma in sorted(per_club.items()):
        page = render_club_page(short, ryhma, meta, now, saatavilla)
        if not page:
            continue
        (CLUB_DIR / f"{CLUB_SLUGS[short]}.html").write_text(page, encoding="utf-8")
        tehdyt.append(CLUB_SLUGS[short])
    return tehdyt


def render_expected_points(xp: dict, now: datetime) -> str | None:
    """Koko xP-lista ilmaiseksi, ilman kirjautumista (9.8.2026).

    MIKSI TAMA SIVU ON OLEMASSA: postasimme X:aan ja Blueskyyn xP-lukuja
    ("Bruno 34.1 xP, No.1 midfielder") ja linkitimme /fpl/stats-sivulle, jossa
    on RAAKADATAA (laukaukset, xG) eika xP:ta lainkaan. Villen huomio 9.8:
    lupasimme numeron ja toimitimme jotain muuta. Ilmaista xP-listaa ei ollut
    millaan pinnalla — model-xi nayttaa 11 pelaajaa ja best-captain karjen,
    mutta rankattua listaa ei.

    Sivu on myos ainoa Reddit-kelpoinen kohde xP-sisallolle: r/FantasyPL:n
    saanto 9 poistaa linkit sivustoihin jotka vaativat rekisteroitymisen
    tiedon nakemiseen.

    VAPAA/PREMIUM-RAJA: lista on sisaltoa, tyokalut ovat tuote. Ranking nakyy
    kokonaan ilmaiseksi; rate-my-team, siirtosuunnittelija, kapteenirankkeri
    ja watchlist pysyvat premiumina. Sama peruste kuin /fpl/stats-rajassa:
    puolustettavuus, ei kustannus.

    Sarakevalinta on tahallinen: xP/90 (vauhti) ja xMins (peliaika) ERIKSEEN,
    koska niiden sekoittaminen on juuri se virhe joka korjattiin 9.8. Lukija
    nakee itse kumpi ajaa lukua.
    """
    meta = xp.get("meta") or {}
    players = xp.get("players") or []
    if not meta.get("available") or not players:
        return None

    rows = sorted(players, key=lambda p: -(p.get("xp_horizon_total") or 0))
    n_gw = len(rows[0].get("gameweeks") or []) or 6
    url = f"{BASE}/fpl/expected-points"
    title = (f"FPL Expected Points: Every Player Ranked by xP "
             f"(next {n_gw} GWs) | GoalIQ")
    lead = rows[0]
    desc = (
        f"Every FPL player ranked by expected points over the next {n_gw} "
        f"gameweeks. {lead['web_name']} leads on "
        f"{lead['xp_horizon_total']:.1f} xP. Scoring rate and minutes shown "
        f"separately. Free, no sign-in."
    )

    top3 = "".join(
        '<div class="stat">'
        f'<b>{escape(r["web_name"])}</b>'
        f'<span>#{i + 1} · {escape(r["team_short"])} · '
        f'{r["xp_horizon_total"]:.1f} xP · {r["price"]:.1f}m</span></div>'
        for i, r in enumerate(rows[:3])
    )

    trows = "".join(
        "<tr>"
        f'<td class="n">{i + 1}</td>'
        f'<td>{escape(r["web_name"])}</td>'
        f'<td class="tm">{_kit_svg(r["team_short"])}'
        f'<span>{escape(r["team_short"])}</span>{_tflag_html(r)}</td>'
        # 15.8: pos ja price ilman m-hidea, kuten otsikotkin. Suodatin lukee
        # naita soluja, joten piilotettuina se suodattaisi nakymattomalla
        # perusteella.
        f'<td>{escape(r["pos"])}</td>'
        f'<td class="n">{r["price"]:.1f}</td>'
        f'<td class="n hi">{r["xp_horizon_total"]:.1f}</td>'
        f'<td class="n m-hide">{(r.get("xp_per_gw") or 0):.2f}</td>'
        f'<td class="n">{(r.get("xp_per_90") or 0):.2f}</td>'
        f'<td class="n">{(r.get("p_start") or 0) * 100:.0f}</td>'
        f'<td class="n m-hide">{(r.get("xmins") or 0):.0f}</td>'
        f'<td class="n m-hide">{(r.get("owned_pct") or 0):.1f}</td>'
        "</tr>"
        # Sama 100 rivin DOM-rajaus kuin xg-leadersissa; koko lista on
        # nakyvissa positiosuodattimen kautta appissa/premiumissa.
        for i, r in enumerate(rows[:100])
    )
    kitdefs = _kit_defs(p.get("team_short") for p in rows[:100])
    table = (
        '<div class="lb-wrap"><table class="lb">'
        "<thead><tr>"
        '<th class="n">#</th><th>Player</th><th>Team</th>'
        # 15.8: Pos ja Price EIVAT ole enaa m-hide. Ne ovat suodattimen
        # kaksi ulottuvuutta, ja piilotettuina suodatin olisi sokea juuri
        # silla laitteella jolla suurin osa lukijoista tulee. Sama puute
        # esti julkaisutarkistajaa verifioimasta hintavaitetta puhelimella.
        '<th>Pos</th><th class="n">Price</th>'
        f'<th class="n">{n_gw}GW xP</th>'
        '<th class="n m-hide">xP/GW</th><th class="n">xP/90</th>'
        '<th class="n">Start%</th>'
        '<th class="n m-hide">xMins</th><th class="n m-hide">Own%</th>'
        "</tr></thead>"
        f"<tbody>{trows}</tbody></table></div>"
    )
    hero = (
        "<h1>FPL expected points, every player ranked</h1>"
        '<p class="lede">What our match model projects each player to score '
        f"over the next {n_gw} gameweeks. Scoring rate and expected minutes "
        "are shown separately, so you can see which one is driving the "
        "number. Free, no sign-in, updated daily.</p>"
    )
    body = (
        f'<div class="stat-row">{top3}</div>'
        f"<h2>Top 100 by expected points (of {len(rows)} players)</h2>"
        # Selitys taulukon ALLE, ei ylle (9.8): ensimmainen versio tyonsi 237
        # sanaa datan eteen, eli X:sta tulija joutui vierittamaan kaksi
        # ruudullista mobiilissa paastakseen siihen lukuun joka hanelle
        # luvattiin. Sivun tyo on antaa luku ensin ja selittaa sitten.
        '<p class="note">'
        f"Ranked by total xP over the next {n_gw} gameweeks. <em>xP/90</em> "
        "is the scoring rate, <em>Start%</em> is how likely he is to start, "
        "<em>xMins</em> combines the two.</p>"
        f"{kitdefs}{table}"
        + _tflag_note(xp, rows[:100], rows) +
        '<p class="note"><strong>Start% near 50 means the model is split.'
        "</strong> Those totals are a bet on team news, not a settled "
        "projection. A keeper on 51% is not a 45-minute keeper.</p>"
        # 10.8: mitattu harha julki (Villen valinta C). Nelja korjausyritysta
        # havisi, viimeisin ristiinvalidoitu kalibrointi kaikilla varianteilla,
        # joten lukua EI sadeta. Sama vaste kuin siirtosokeudessa: kerro se.
        # Lahde: scripts/calibrate_preseason_minutes.py, 3 kesataukoa.
        '<p class="note"><strong>Our pre-season minutes run high at the top.'
        "</strong> We tested our own prior across the last three summers. "
        "Players we projected at 80+ minutes came in about 14 minutes lower "
        "than we said, and players we projected at the bottom came in a "
        "little higher. The order of this list is unchanged by that, and the "
        "gap closes as 2026/27 results arrive.</p>"
        # 16.8: sokea piste sanottu ääneen. Villen päätös oli ettei vahti
        # kysy esikaudesta, joten rajoite kirjataan näkyviin siellä missä
        # luku esitetään. Laukaiseva tapaus 15.8: João Pedro teki kaksi
        # esikauden maalia eikä lukumme liikkunut lainkaan, ja olin
        # kirjoittamassa siitä X-vastausta.
        '<p class="note"><strong>Start% does not read pre-season.</strong> '
        "It comes from last season's minutes and FPL's own availability "
        "flags, and for players with no Premier League history yet, from how "
        "they are priced in the squad. A player who has looked like a new "
        "first choice in friendlies will not move this number until league "
        "minutes arrive.</p>"
        '<p class="note">This ranking is free and needs no account. The tools '
        "built on top of it, rate my team, the transfer planner, the captain "
        "ranker and your watchlist, are part of GoalIQ Premium.</p>"
        + f"{UPSELL}{_cta()}"
        + f'<p class="note">Updated {now.strftime("%d %b %Y")} · '
        + f'{escape(str(meta.get("caveat") or ""))[:300]} · {DISCLAIMER}</p>'
    )
    jsonld = [{
        "@context": "https://schema.org", "@type": "WebPage",
        "name": title, "url": url, "description": desc,
        "isPartOf": {"@id": f"{BASE}/#organization"},
        "dateModified": now.strftime("%Y-%m-%d"),
    }]
    return _page(title, desc, url, hero, body, jsonld)


def main() -> int:
    now = datetime.now(timezone.utc)
    OUT_DIR.mkdir(exist_ok=True)
    built = []

    xp = _load(XP_PATH)
    if xp:
        page = render_captain(xp, now)
        if page:
            (OUT_DIR / "best-captain.html").write_text(page, encoding="utf-8")
            built.append("best-captain")
        # 26.7: Model XI kenttagrafiikkana (sama XI-heuristiikka kuin
        # rate-my-teamin benchmark) — antaa myos beat-the-model-liigalle kodin.
        page = render_model_xi(xp, now)
        if page:
            (OUT_DIR / "model-xi.html").write_text(page, encoding="utf-8")
            built.append("model-xi")
        # 9.8: koko xP-lista ilmaiseksi — ks. render_expected_points-docstring.
        page = render_expected_points(xp, now)
        if page:
            (OUT_DIR / "expected-points.html").write_text(page, encoding="utf-8")
            built.append("expected-points")
        # 14.8: jakokortin tarkistuskohde — ks. render_club_best-docstring.
        page = render_club_best(xp, now)
        if page:
            (OUT_DIR / "club-best.html").write_text(page, encoding="utf-8")
            built.append("club-best")
        # 15.8: team news kaanteisena - ks. render_team_news-docstring.
        page = render_team_news(xp, now)
        if page:
            (OUT_DIR / "team-news.html").write_text(page, encoding="utf-8")
            built.append("team-news")

    if xp:
        clubs = render_club_pages(xp, now)
        if clubs:
            built.append(f"club x{len(clubs)}")
        sivu = render_predicted_lineups(xp, now)
        if sivu:
            (OUT_DIR / "predicted-lineups.html").write_text(sivu, encoding="utf-8")
            built.append("predicted-lineups")

    notes_doc = _load(NOTES_PATH)
    if notes_doc:
        page = render_notes(notes_doc, now)
        if page:
            (OUT_DIR / "notes.html").write_text(page, encoding="utf-8")
            built.append("notes")
        NOTE_DIR.mkdir(parents=True, exist_ok=True)
        n_art = 0
        for muistio in notes_doc.get("notes") or []:
            sivu = render_note_page(muistio, now)
            if sivu:
                (NOTE_DIR / f"{muistio['slug']}.html").write_text(
                    sivu, encoding="utf-8")
                n_art += 1
        if n_art:
            built.append(f"note x{n_art}")

    diff = _fetch_differentials()
    if diff:
        page = render_differentials(diff, now)
        if page:
            (OUT_DIR / "differentials.html").write_text(page, encoding="utf-8")
            built.append("differentials")

    pw = _load(PW_PATH)
    if pw is not None:
        (OUT_DIR / "price-changes.html").write_text(
            render_price_changes(pw, now), encoding="utf-8")
        built.append("price-changes")

    # #128/#120: xG- + DefCon-leaders-sivut (nightly-cache; puuttuva data →
    # sivut ohitetaan, vanhat jäävät voimaan)
    leaders = _load(LEADERS_PATH)
    if leaders:
        page = render_xg_leaders(leaders, now)
        if page:
            (OUT_DIR / "xg-leaders.html").write_text(page, encoding="utf-8")
            built.append("xg-leaders")
        page = render_defcon(leaders, now)
        if page:
            (OUT_DIR / "defcon.html").write_text(page, encoding="utf-8")
            built.append("defcon")

    # 8.8 STATS-ZONE: oma nightly-JSON (build_fpl_stats.py). Puuttuva data →
    # sivu ohitetaan ja vanha jää voimaan, sama konventio kuin muut.
    stats = _load(STATS_PATH)
    if stats:
        page = render_stats(stats, now)
        if page:
            (OUT_DIR / "stats.html").write_text(page, encoding="utf-8")
            built.append("stats")

    defence = _load(DEFENCE_PATH)
    if defence:
        page = render_defence(defence, now)
        if page:
            (OUT_DIR / "defence.html").write_text(page, encoding="utf-8")
            built.append("defence")

    today = now.strftime("%Y-%m-%d")
    # Seurasivut ovat alihakemistossa, joten `glob("*.html")` EI nae niita.
    # Ilman tata 20 sivua olisi olemassa mutta poissa sitemapista — sama
    # orpous joka mitattiin 15.8 `expected-points`- ja `team-news`-sivuilla.
    urlit = [(f"{BASE}/fpl/{f.stem}", today, "daily", "0.7")
             for f in sorted(OUT_DIR.glob("*.html"))]
    urlit += [(f"{BASE}/fpl/club/{f.stem}", today, "daily", "0.6")
              for f in sorted(CLUB_DIR.glob("*.html"))]
    # Artikkelisivut ovat myos alihakemistossa: sama orpousansa kuin
    # seurasivuilla, ja juuri niihin ulkoiset linkit osoittavat.
    urlit += [(f"{BASE}/fpl/note/{f.stem}", today, "weekly", "0.7")
              for f in sorted(NOTE_DIR.glob("*.html"))]
    write_urlset(SITEMAP_FPL_PATH, urlit)
    print(f"LONGTAIL: {', '.join(built) or 'ei sivuja (data puuttuu)'} "
          f"(sitemap-fpl.xml: {len(urlit)} URL:ia)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
