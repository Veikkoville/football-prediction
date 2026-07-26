"""Ilmaiset indeksoitavat FPL-long-tail-sivut (#120).

Kolme evergreen-URLia, per-GW päivittyvä sisältö:

  fpl/best-captain.html    "Best FPL captain GW{n}" — top-pick xP:llä (free-
                           pariteetti: captain suggestion on ilmainen appissa),
                           sijat 2-3 NIMINÄ ilman lukuja → ranker = Premium.
  fpl/differentials.html   "Best FPL differentials GW{n}" — top-1 teaser
                           (nimi+EO+xP), loput lukittu → Premium.
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
API = "https://goaliq-api.onrender.com"

UPSELL = (
    '<div class="rec">Powered by the GoalIQ match model with a published, '
    'pre-match-logged track record. The full toolkit (captain ranker, all '
    'differentials, transfer planner) is <a '
    'href="https://pro.goaliq.app/?tab=premium">GoalIQ Premium</a>: '
    '3.99 €/month or 25 €/season, one subscription on web, iOS '
    'and Android.</div>'
)

# 24.7 brand redesign: sama ilme kuin fpl.html (Space Grotesk, magenta-bar,
# tumma ink-hero, cream-body, paper-kortit, pillerinapit). Longtail-sivuilla
# OMA template — build_prediction_pages.CSS/NAV/_page jää prediction-sivujen
# vanhaan asuun, ei sivuvaikutuksia sinne.
CSS = """
:root{--magenta:#FF2E7E;--magenta-deep:#D6006E;--teal:#19E3D2;
--teal-ink:#007A6C;--ink:#0A0820;--ink2:#140F1E;--cream:#FFF6EC;
--paper:#F6F4FF;--muted:#54506B;--hero-muted:#C9C3DA;
--line:rgba(10,8,32,0.12);--radius:14px;}
*{box-sizing:border-box;margin:0;padding:0;}
body{background:var(--cream);color:var(--ink);font-family:-apple-system,
BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;line-height:1.6;}
h1,h2,h3,.brand{font-family:"Space Grotesk",-apple-system,"Segoe UI",sans-serif;}
.wrap{max-width:820px;margin:0 auto;padding:0 20px;}
.bar{height:6px;background:var(--magenta);}
.dark{background:linear-gradient(165deg,var(--ink2),var(--ink));
color:var(--cream);}
nav{display:flex;align-items:center;justify-content:space-between;
padding:18px 0;font-size:14px;}
nav a{text-decoration:none;color:#fff;font-weight:600;}
.brand{font-size:20px;font-weight:700;letter-spacing:.5px;}
.brand span{color:var(--magenta);}
.nav-cta{background:var(--magenta);color:#fff;padding:8px 16px;
border-radius:999px;font-weight:700;}
.nav-cta:hover{background:var(--magenta-deep);}
.hero{padding:26px 0 44px;}
.hero h1{color:#fff;font-size:31px;line-height:1.15;margin:0 0 12px;
letter-spacing:-0.01em;}
.hero .lede{color:var(--hero-muted);max-width:640px;}
h2{font-size:22px;margin:30px 0 10px;}
.content{padding-top:26px;}
.card{background:var(--paper);border:1px solid var(--line);
border-radius:var(--radius);padding:18px 20px;margin-bottom:14px;}
.lede{color:var(--muted);margin-bottom:22px;}
.stat-row{display:flex;flex-wrap:wrap;gap:12px;margin:14px 0;}
.stat{background:var(--paper);border:1px solid var(--line);
border-radius:16px;padding:14px 18px;flex:1 1 140px;}
.stat b{display:block;font-size:22px;color:var(--magenta-deep);
font-family:"Space Grotesk",-apple-system,"Segoe UI",sans-serif;}
.stat span{color:var(--muted);font-size:12px;}
.rec{border:2px solid var(--magenta);background:var(--paper);
border-radius:16px;padding:16px 20px;font-size:14px;color:var(--muted);
margin:24px 0 16px;}
.rec a{color:var(--magenta-deep);font-weight:700;}
.cta-row{display:flex;flex-wrap:wrap;gap:12px;margin:22px 0;}
.btn{background:var(--magenta);color:#fff;font-weight:700;padding:12px 22px;
border-radius:999px;text-decoration:none;font-size:14px;}
.btn:hover{background:var(--magenta-deep);}
.btn.ghost{background:transparent;color:var(--ink);
border:2px solid var(--magenta);}
.btn.ghost:hover{background:transparent;color:var(--magenta-deep);}
.mrow{display:flex;align-items:center;justify-content:space-between;gap:10px;
padding:12px 0;border-bottom:1px solid var(--line);}
.mrow:last-child{border-bottom:none;}
.mrow a{color:var(--magenta-deep);font-weight:700;text-decoration:none;}
.mrow .meta{color:var(--muted);font-size:12px;}
.pick{color:var(--teal-ink);font-weight:700;font-size:13px;white-space:nowrap;}
footer{border-top:1px solid var(--line);margin-top:36px;padding:22px 0 34px;
color:var(--muted);font-size:13px;}
footer a{color:var(--magenta-deep);}
.note{color:var(--muted);font-size:12px;margin:18px 0;}
/* 26.7: vapautettu xG-leaderboard, koko taulukko ilmaiseksi */
.lb-wrap{overflow-x:auto;margin:14px 0;}
.lb{width:100%;border-collapse:collapse;font-size:14px;}
.lb th,.lb td{padding:8px 10px;text-align:left;
border-bottom:1px solid var(--line);white-space:nowrap;}
.lb th{font-size:11px;text-transform:uppercase;letter-spacing:.06em;
color:var(--muted);font-weight:700;}
.lb td.n,.lb th.n{text-align:right;font-variant-numeric:tabular-nums;}
.lb td.hi{color:var(--magenta-deep);font-weight:700;}
.lb tbody tr:last-child td{border-bottom:none;}
.lb thead th:hover{color:var(--magenta-deep);}
.lbctl{display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin:16px 0 6px;}
.lbctl .lbl{font-size:11px;text-transform:uppercase;letter-spacing:.06em;
color:var(--muted);font-weight:700;margin-left:6px;}
.lbctl .lbl:first-child{margin-left:0;}
.chips{display:inline-flex;gap:6px;}
.chip{min-width:34px;border:1px solid var(--line);background:var(--paper);
color:var(--ink);border-radius:999px;padding:6px 12px;font-size:13px;
font-weight:600;cursor:pointer;}
.chip.on{background:var(--magenta);border-color:var(--magenta);color:#fff;}
.lbctl select{border:1px solid var(--line);background:var(--paper);
color:var(--ink);border-radius:999px;padding:6px 12px;font-size:13px;
font-weight:600;}
@media (max-width:520px){.cta-row{flex-direction:column;align-items:stretch;}
.btn{text-align:center;}}
"""


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
        '<link rel="icon" href="/favicon.ico" sizes="any">\n'
        '<link rel="preconnect" href="https://fonts.googleapis.com">\n'
        '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n'
        '<link href="https://fonts.googleapis.com/css2?family='
        'Space+Grotesk:wght@500;700&display=swap" rel="stylesheet">\n'
        '<meta name="theme-color" content="#0A0820">\n'
        f"{ld}"
        f"<style>{CSS}</style>\n"
        "</head>\n<body>\n"
        '<header class="dark">\n'
        '<div class="bar"></div>\n'
        '<div class="wrap"><nav>'
        '<a class="brand" href="/">Goal<span>IQ</span></a>'
        '<span><a href="/predictions">All predictions</a> · '
        '<a class="nav-cta" href="https://pro.goaliq.app/">Try it live</a></span>'
        "</nav></div>\n"
        f'<div class="wrap hero">\n{hero}\n</div>\n'
        "</header>\n"
        f'<main class="wrap content">\n{body}\n'
        f'<footer>© 2026 GoalIQ · '
        f'<a href="/predictions">Football predictions</a> · '
        f'<a href="/fpl.html">Free FPL tools</a> · '
        f'<a href="/privacy.html">Privacy</a><br>{DISCLAIMER}</footer>\n'
        "</main>\n</body>\n</html>\n"
    )


def _load(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _fetch_differentials() -> dict | None:
    try:
        with urllib.request.urlopen(
            f"{API}/api/fantasy/differentials?max_ownership=10", timeout=120
        ) as r:
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
    ranked = sorted(players, key=lambda p: float(p.get("xp_per_gw") or 0.0),
                    reverse=True)
    top = ranked[0]
    alts = ranked[1:3]
    url = f"{BASE}/fpl/best-captain"
    title = f"Best FPL Captain GW{gw} – Model Pick & xP | GoalIQ"
    desc = (
        f"The GoalIQ model's best FPL captain for Gameweek {gw}: "
        f"{top['web_name']} ({top['team_short']}) at {float(top['xp_per_gw']):.1f} "
        f"expected points. Updated every round from the match model behind our "
        f"public track record."
    )
    hero = (
        f"<h1>Best FPL captain, Gameweek {gw}</h1>"
        f'<p class="lede">The GoalIQ match model\'s top captain pick for GW{gw} is '
        f"<strong>{escape(top['web_name'])} ({escape(top['team_short'])})</strong> at "
        f"<strong>{float(top['xp_per_gw']):.1f} expected points</strong>.</p>"
    )
    body = (
        f'<div class="stat-row">'
        f'<div class="stat"><b>{escape(top["web_name"])}</b>'
        f'<span>#1 pick · {escape(top["team_short"])} · {float(top["xp_per_gw"]):.1f} xP</span></div>'
        + "".join(
            f'<div class="stat"><b>{escape(p["web_name"])}</b>'
            f'<span>contender · {escape(p["team_short"])} · xP in Premium</span></div>'
            for p in alts
        )
        + "</div>"
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
    title = f"Best FPL Differentials {gw_txt} – Low-Owned Model Picks | GoalIQ"
    desc = (
        f"GoalIQ's model differential for {gw_txt}: {top['web_name']} "
        f"({top['team_short']}), owned by just {top['owned_pct']}% of managers "
        f"with {top['xp_horizon_total']} expected points over the horizon. "
        f"{len(players)} more low-owned picks in GoalIQ Premium."
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
        f'{top["xp_horizon_total"]} xP over the horizon</span></div>'
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
    title = "FPL Price Changes Tonight – Predicted Risers & Fallers | GoalIQ"
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
        ])
    return json.dumps(out, separators=(",", ":"), ensure_ascii=False)


# Selainlogiikka: ikkuna (3/5/10), per game vs per 90, lajittelu, suodattimet.
# Ei em dashia missaan nakyvassa tekstissa (viestintatyyli SS1b).
XG_JS = """
<script>
(function(){
 var D=window.__XG__||[],w=5,per90=false,pos='',team='',key=5,desc=true;
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
   return {n:p[0],t:p[1],p:p[2],c:p[3],g:s[1],m:s[0],
           xg:s[2]/d,xa:s[3]/d,xgi:s[4]/d};
  }
  var g=p[4].slice(-w),m=0,xg=0,xa=0,xgi=0;
  for(var i=0;i<g.length;i++){m+=g[i][0];xg+=g[i][1];xa+=g[i][2];xgi+=g[i][3];}
  var d=per90?(m/90):g.length;
  if(!d)d=1;
  return {n:p[0],t:p[1],p:p[2],c:p[3],g:g.length,m:m,
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
  for(var i=0;i<r.length;i++){
   var a=r[i];
   h+='<tr><td class="n">'+(i+1)+'</td><td>'+a.n+'</td><td>'+a.t+'</td><td>'
    +a.p+'</td><td class="n">'+a.c.toFixed(1)+'</td><td class="n hi">'
    +a.xg.toFixed(2)+'</td><td class="n">'+a.xa.toFixed(2)+'</td><td class="n">'
    +a.xgi.toFixed(2)+'</td><td class="n">'+a.m+'</td><td class="n">'+a.g
    +'</td></tr>';
  }
  tb.innerHTML=h;
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
    title = "Top xG Performers – FPL Expected Goals Leaders | GoalIQ"
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
        f'<td>{escape(r["team_short"])}</td>'
        f'<td>{escape(r["pos"])}</td>'
        f'<td class="n">{r["price"]:.1f}</td>'
        f'<td class="n hi">{r["xg_per_game"]:.2f}</td>'
        f'<td class="n">{r["xa_per_game"]:.2f}</td>'
        f'<td class="n">{r["xgi_per_game"]:.2f}</td>'
        f'<td class="n">{mins5.get(r["id"], 0)}</td>'
        f'<td class="n">{r["games"]}</td>'
        "</tr>"
        for i, r in enumerate(rows)
    )
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
        '<th class="n">#</th><th>Player</th><th>Team</th><th>Pos</th>'
        '<th class="n">Price</th><th class="n">xG</th>'
        '<th class="n">xA</th><th class="n">xGI</th>'
        '<th class="n">Mins</th><th class="n">Games</th>'
        "</tr></thead>"
        f'<tbody id="xgb">{trows}</tbody></table></div>'
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
        f"{controls}{table}{payload}{XG_JS}"
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
    -pistemekaniikan luotettavimmat lähteet. Top-3 luvuilla, loput niminä."""
    from src.models.fpl_leaders import rank_defcon_leaders
    if not leaders.get("meta", {}).get("available"):
        return None
    out = rank_defcon_leaders(leaders, window=5, top_n=10)
    rows = out["players"]
    if not rows:
        return None
    basis = out["meta"].get("basis_label") or ""
    url = f"{BASE}/fpl/defcon"
    title = "Best DefCon Players – FPL Defensive Contribution Leaders | GoalIQ"
    desc = (
        f"The most reliable FPL defensive contribution (DefCon) point scorers: "
        f"{rows[0]['web_name']} hits the threshold in "
        f"{rows[0]['hit_rate_pct']:.0f}% of games. Defenders need 10 CBIT, "
        f"midfielders and forwards 12 CBIRT, for 2 points."
    )
    top3 = "".join(
        '<div class="stat">'
        f'<b>{escape(r["web_name"])}</b>'
        f'<span>#{i + 1} · {escape(r["team_short"])} · '
        f'{r["hit_rate_pct"]:.0f}% hit rate · {r["dc_per_game"]:.1f} DC/game</span></div>'
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
    body = (
        f'<p class="note"><strong>{escape(basis)}</strong></p>'
        f'<div class="stat-row">{top3}</div>'
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
