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

from scripts.build_fpl_page import ROOT as _FP_ROOT, write_urlset
from scripts.mobile_css import MOBILE_COLS_JS, MOBILE_CSS
from scripts.share_card_js import SHARE_CARD_JS

# #119b: long-tail-sivut omaan lapsi-sitemapiin (sitemap.xml-index listaa).
# Wholesale OUT_DIR-globista → entry jokaiselle olemassa olevalle sivulle,
# myös silloin kun jokin data-lähde puuttui tältä ajolta (sivu jää voimaan).
SITEMAP_FPL_PATH = _FP_ROOT / "sitemap-fpl.xml"
from scripts.build_prediction_pages import DISCLAIMER

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
    '3.99 €/month or 25 €/season. Enter EARLY30 at checkout before the GW1 '
    'deadline on Friday 21 August for 30% off the first year (17.50 €, then '
    '25 €). One subscription on web, iOS and Android.</div>'
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
/* 🐛 26.7: color oli var(--cream) = cream cream-pohjalla -> kaikki
   color:inherit -lapset olisivat nakymattomia. Jaanne tumma->vaalea-
   vaihdosta. */
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
/* 9.8 (Villen havainto isolla naytolla): tama oli 'padding:26px 0 44px',
   ja shorthand nollasi .wrapin vaakapaddingin -> hero-otsikko ja lede
   alkoivat 20px muuta sisaltoa vasemmalta. Sivulla oli siis kaksi eri
   vasenta reunaa (303 ja 323). Vain pystypadding. */
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
/* 26.7: vapautettu xG-leaderboard, koko taulukko ilmaiseksi */
/* 8.8 (Villen havainto): sivun palsta on 820px, joten leveakaan naytto ei
   nayttanyt kaikkia sarakkeita — piti vierittaa vaakaan nuolella. Nyt JOKAINEN
   taulukko paasee ulos palstasta ja kasvaa ikkunan mukana 1560 pikseliin asti;
   header, leipateksti ja footer pysyvat 820:ssa (rivinpituus = luettavuus).
   96vw eika 100vw, jotta pystyvierityspalkki ei tyonna sivua vaakaan.
   Taulukko itse EI veny taytteeksi: width:auto + min-width pitaa kapeat
   taulukot entisen levyisina keskitettyna, ja vain leveat kayttavat lisatilan.
   Kapealla naytolla min() palauttaa 100% -> kaytos on tasmalleen entinen. */
.lb-wrap{overflow-x:auto;margin:14px 0;
width:min(96vw,1560px);margin-left:50%;transform:translateX(-50%);}
/* 820px oli .wrapin max-width PADDING MUKAAN LUKIEN, mutta tekstipalsta
   on 780px. Taulukko keskittyi siis 820:n levyisena tayssleveaan
   kaareen ja alkoi 20px tekstia vasemmalta. Sama luku kuin
   tekstipalstalla -> reunat linjassa; leveat taulukot kasvavat yha. */
.lb-wrap>.lb{width:auto;min-width:min(100%,780px);margin:0 auto;}
/* 96vw + translateX ei saa synnyttaa sivutason vaakavieritysta */
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
/* Neutraali joukkuepaita (ei krestia/pelaajakuvaa, ks. IP-huomio koodissa) */
.lb td.tm{display:flex;align-items:center;gap:7px;}
/* Luottamuslippu (10.8): joukkueen luokitus nojaa heikompaan tietoon.
   KUVAILEVA - ei kerro kumpaan suuntaan projektio liikkuu. Vaimennettu
   tahallaan: se on reunahuomautus rivilla, ei rivin tarkein asia. */
.tflag{flex:0 0 auto;font-size:10px;font-weight:600;letter-spacing:.04em;
text-transform:uppercase;padding:1px 5px;border:1px solid var(--line-strong);
border-radius:var(--radius);opacity:.72;white-space:nowrap;}
.kit{flex:0 0 auto;display:block;}
/* Model XI -kentta. 26.7: sama ilme kuin SPA:n TeamPitchManagerilla ja
   mobiilin #106-pitchilla (teal-tint, #108-paletti) - EI nurmivaria. Villen
   paatos: brandipaletti voittaa kirjaimellisen nurmen, ja kolmen pinnan
   pitaa nayttaa samalta. */
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
display:flex;flex-wrap:wrap;align-items:baseline;gap:10px 14px;}
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
_TOOL_LINKS = [
    ("/fpl/best-captain", "Captain picks"),
    ("/fpl/model-xi", "Model XI"),
    ("/fpl/differentials", "Differentials"),
    ("/fpl/price-changes", "Price changes"),
    ("/fpl/xg-leaders", "xG leaders"),
    ("/fpl/defcon", "DefCon leaders"),
    ("/fpl/stats", "Player stats"),
    ("/fpl/defence", "Defence profiles"),
]


def _tool_nav(canonical: str) -> str:
    """Ristiinlinkitys muihin longtail-sivuihin, nykyinen sivu pois.

    Renderoidaan <nav>-elementtina eika pelkkana linkkilistana, jotta
    sivun oma navigointirakenne on koneluettava.
    """
    here = canonical.rstrip("/").replace(BASE, "")
    items = "".join(
        f'<a href="{href}">{escape(label)}</a>'
        for href, label in _TOOL_LINKS
        if href != here
    )
    return (
        '<nav class="toolnav" aria-label="More free FPL tools">'
        f'<b>More free FPL tools</b>{items}</nav>\n'
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
    return f"{BASE}/{rel}" if (_FP_ROOT / rel).exists() else SOCIAL_IMAGE

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
            else "start odds in Premium"

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
 // Nayta oletuksena 100 rivia. MIKSI: 373 riviä = ~5000 DOM-solmua ja jokainen
 // kontrolliklikkaus rakensi ne kaikki uudelleen innerHTML:lla -> sivu lagasi
 // pahasti. 100 riittaa kaytannossa kaikkeen, ja "show all" on yhden klikin
 // paassa. Payloadissa on silti kaikki, joten suodatus ja lajittelu koskevat
 // koko aineistoa - vain NAYTTO on rajattu.
 var LIMIT=100,showAll=false;
 // Sama neutraali paitasiluetti kuin palvelinrenderoinnissa ja
 // TeamKit.svelte/TeamKit.tsx:ssa. Ei krestia eika pelaajakuvaa (IP).
 var JP='M 33 15 L 43 9 C 46 15 54 15 57 9 L 67 15 L 84 27 L 76 42 L 67 36 '
  +'L 67 86 Q 67 90 63 90 L 37 90 Q 33 90 33 86 L 33 36 L 24 42 L 16 27 Z';
 function kit(c,lbl){
  // Viittaa samaan <symbol>-kirjastoon jonka palvelin renderoi kerran.
  return '<svg class="kit" width="26" height="26" aria-hidden="true">'
   +'<use href="#k'+(lbl||'').toUpperCase()+'"/></svg>';
 }
 // Minuuttikynnys. Per 90 ilman tata on rikki: 2 minuuttia pelannut nousee
 // karkeen puhtaana kohinana. Kynnys on NAKYVA ja saadettava, ei hiljainen
 // piilotus: kayttaja nakee mika suodatin on paalla ja voi ottaa sen pois.
 var minm=0;
 var tb=document.getElementById('xgb'),cnt=document.getElementById('xgc');
 if(!tb)return;
 function agg(p){
  if(w==='S'){
   // Koko kausi: bootstrapin totaalit. "Per game" -tilassa naytetaan
   // TOTAALIT (kaudelle per-ottelu ei ole mielekas: meilla on avaukset,
   // ei esiintymisia), "Per 90" jakaa minuuteilla.
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
   // pois oletuksena, koska tama on xG-lista eika torjuntalista. GKP-suodatin
   // nayttaa ne erikseen. Ilman tata sivu antaisi kaksi eri lukua.
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
  // Kausitilassa viimeisessa sarakkeessa on AVAUKSET, ei esiintymisia
  // (bootstrap antaa startsin). Otsikko kertoo kumpi, ei arvata.
  var hh=document.querySelectorAll('#xgt2 thead th');
  if(hh&&hh[9])hh[9].textContent=(w==='S')?'Starts':'Games';
  var span=(w==='S')?', full season':', last '+w+' games each';
  var rate=per90?', per 90 minutes':((w==='S')?', season totals':', per game');
  if(cnt)cnt.textContent=r.length+' players'+rate+span
   +(minm?', at least '+minm+' minutes played':', no minutes filter');
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
  // Kausitilassa vasen vaihtoehto EI ole per ottelu vaan summa (meilla on
  // avaukset, ei esiintymisia -> aitoa per-ottelu-jakajaa ei ole). Chipin
  // teksti kertoo sen, muuten 25.50 nayttaisi "per game" -lukemalta.
  chips('xgr',[[0,(w==='S')?'Total':'Per game'],[1,'Per 90']],
        function(){return per90?1:0;},
        function(v){
         var was=per90;per90=!!v;
         // Per 90:een siirryttaessa oletuskynnys paalle, takaisin per game:een
         // siirryttaessa pois. Kayttajan oma valinta jaa voimaan jos han on
         // sita jo koskenut talla naytolla.
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
 // Kausisummista ei voi laskea "GW1-6" jalkikateen, joten kierroskohtaiset
 // rivit haetaan ERILLISESTA tiedostosta ja VASTA kun kayttaja koskee
 // suodattimeen: se on 551 KB (122 KB gzip) eika sita makseta niiden
 // puolesta jotka eivat sita kayta.
 var GW=null,gwFrom=0,gwTo=0,gwLoading=false,gwCache={},GWI=null;
 // Vain FPL:n virallisen APIn sarakkeet ovat ikkunoitavissa. Laukaustason
 // luvut tulevat Understatista ilman kierroserittelya, joten niiden
 // ikkunointi olisi vale: sivu estaa sen sen sijaan etta nayttaisi nollia.
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
  // null = pelaajaa ei matsattu laukausdataan. Tyhja viiva on totuus,
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
   if(gwOn()&&!winRow(r))continue;   // ei minuutteja ikkunassa
   if(raw(r,'mins')<minm)continue;
   if(r[C.price]>maxp)continue;
   if(q&&(r[C.name]+' '+r[C.team]).toLowerCase().indexOf(q)<0)continue;
   if(mode==='pstart'&&raw(r,'starts')<1)continue;
   out.push(r);
  }
  // Erikoistilannejarjestykset ovat sijalukuja: 1 = ensimmainen potkaisija.
  // Suurin-ensin olisi vaarinpain (5. pilkkuvuorossa oleva karkeen), ja
  // 0 = "ei listalla" pitaa aina valua loppuun kumpaankin suuntaan.
  var ORD=ORDCOLS.indexOf(sortKey)>=0;
  out.sort(function(a,b){
   var x=val(a,sortKey),y=val(b,sortKey);
   // Tuntematon arvo ei kilpaile jarjestyksesta kumpaankaan suuntaan.
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
  // Mobiili (a) 9.8: Pos/Price/Mins/Starts ovat suodatinkontekstia (ne
  // saadetaan yllä olevilla napeilla), joten kapealla naytolla nakyvat
  // Player + Team + valitun ryhman tilastot. Taulukko oli 657px = 1,7 x
  // puhelimen leveys. Sarakkeet ovat yha DOMissa -> lajittelu ja CSV
  // eivat muutu.
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
    // Mins ja Starts ovat ikkunoitavia: ilman raw():ta ne nayttivat kauden
    // lukuja GW-otsikon alla (Haaland 2953 min "GW1-6:lla"). Loytyi vasta
    // livesivua katsomalla, ei koodista.
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
    // Otoskokovahti: 7 pelattua minuuttia tuottaa 12.86 tacklea/90 ja
    // valtaa koko listan karjen. Suhdeluku ilman otoskokoa on harhaanjohtava,
    // joten rate-tilaan siirtyminen nostaa minimin 450 minuuttiin. Kayttaja
    // voi laskea sen takaisin nollaan yhdella klikilla - sita ei estetä,
    // se vain lakkaa olemasta oletus.
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
  // Laukaustason ryhmat eivat ole ikkunoitavissa (Understat, ei
  // kierroserittelya). Ne lukitaan nakyvasti sen sijaan etta nayttaisivat
  // nollia tai kausisummia ikkunan otsikon alla -- kumpikin valehtelisi.
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
   // Epaonnistunut lataus palauttaa valikon kausitilaan JA sanoo sen.
   // Hiljainen paluu kausisummiin nayttaisi silta etta ikkuna toimii.
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
  // Alaotsikko kokoaa AKTIIVISET suodattimet, ei pelkkaa rivimaaraa. Ilman
  // tata jaettu kortti sanoisi "40 players" kertomatta etta ne ovat
  // puolustajia, yhdesta seurasta tai hintakaton alta -- lukija ei voi
  // tietaa mita han katsoo. Arvot luetaan nakyvista kontrolleista, joten
  // ne eivat voi erkaantua ruudusta.
  function chipOn(id){
   var e=document.getElementById(id);
   if(!e)return '';
   var b=e.querySelector('.chip.on');
   return b?(b.textContent||'').trim():'';
  }
  var bits=[];
  // Gameweek-ikkuna ENSIN: se on vahvin rajaus ja jaettu kortti ilman sita
  // vaittaisi kauden lukuja. Arvot luetaan valikoista, eivat muistista.
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
  // Hintavalitsimen oletus on ylaraja (99), joka EI ole suodatin. Ilman
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
          // Tama kortti on RAAKADATAA, ei mallin ennuste. Oletusalatunniste
          // ("logged before kickoff, graded in public") vaittaisi vaarin.
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
  // Taulukko on NOUSEVASSA jarjestyksessa (Arsenal 0.91 = paras puolustus).
  // Ensimmainen otsikkoehdotus "MOST XG CONCEDED" vaitti tasmalleen
  // painvastoin kuin data, ja se olisi mennyt X:aan sellaisenaan.
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
        "Click a column to sort.</p>"
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
        "definition of a big chance. Our DefCon tracker (hit rate, thresholds, "
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
        '<p class="lede">Clean sheet odds tell you how likely a shutout is. '
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
        f'<td class="m-hide">{escape(r["pos"])}</td>'
        f'<td class="n m-hide">{r["price"]:.1f}</td>'
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
        '<th class="m-hide">Pos</th><th class="n m-hide">Price</th>'
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
    write_urlset(SITEMAP_FPL_PATH, [
        (f"{BASE}/fpl/{f.stem}", today, "daily", "0.7")
        for f in sorted(OUT_DIR.glob("*.html"))
    ])
    print(f"LONGTAIL: {', '.join(built) or 'ei sivuja (data puuttuu)'} "
          f"(sitemap-fpl.xml: {len(list(OUT_DIR.glob('*.html')))} URL:ia)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
