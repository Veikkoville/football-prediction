"""Ohjelmalliset ennustesivut (#119) — orgaanisen haun long-tail-jalanjälki.

Generoi data/prediction_log.json:sta (= #110-putken lokaamat PRE-MATCH-
ennusteet, sama julkinen malli + track record):

  predictions/{league}/index.html            per-liiga-hub ("this week")
  predictions/{league}/{home}-vs-{away}.html per-ottelu-sivu (win% / xG /
                                             todennäköisin tulos + record-linkki)

MIKSI prediction_log eikä live-API: sivun luku = TÄSMÄLLEEN se ennuste joka
on lukittu julkiseen track recordiin ("logged before kickoff") → sivu ja
record eivät voi erota, ja generointi ei kuormita Renderiä. Uniikki
rehellisyyskulma jota kilpailijoilla ei ole.

Vain TULEVAT ottelut (result=None, kickoff > now). Regen poistaa liigan
vanhentuneet ottelusivut (ei staleja ennusteita indeksissä). Hub-sivut ovat
pysyviä URL:eja (sitemap daily). predictions.html:n GEN:PRED-LEAGUES-markerit
täytetään livenä olevilla hubeilla.

Gambling-safe: predictions / win probability / xG / model — EI betting/odds/tips.
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
from scripts.build_fpl_page import _upsert_sitemap_entry, SITEMAP_PATH

BASE = "https://goaliq.app"
OUT_ROOT = ROOT / "predictions"
PREDICTIONS_HTML = ROOT / "predictions.html"

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

CSS = """
:root{--bg:#FFF6EC;--card:#FFFFFF;--line:rgba(10,8,32,0.12);--text:#0A0820;
--muted:#575170;--magenta:#FF2E7E;--magenta-deep:#D6006E;--teal:#19E3D2;
--teal-ink:#007A6C;--radius:14px;}
*{box-sizing:border-box;margin:0;padding:0;}
body{background:var(--bg);color:var(--text);font-family:-apple-system,
BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;line-height:1.6;}
.wrap{max-width:820px;margin:0 auto;padding:0 20px;}
.bar{height:6px;background:var(--magenta);}
nav{display:flex;align-items:center;justify-content:space-between;padding:18px 0;
font-size:14px;}
nav a{text-decoration:none;color:var(--text);font-weight:600;}
.nav-cta{background:var(--magenta);color:#fff;padding:8px 16px;border-radius:999px;}
h1{font-size:30px;line-height:1.2;margin:26px 0 10px;letter-spacing:-0.02em;}
.lede{color:var(--muted);margin-bottom:22px;}
.card{background:var(--card);border:1px solid var(--line);border-radius:var(--radius);
padding:18px 20px;margin-bottom:14px;}
.probbar{display:flex;height:12px;border-radius:6px;overflow:hidden;margin:10px 0 6px;}
.probbar .h{background:var(--magenta);} .probbar .d{background:rgba(10,8,32,0.18);}
.probbar .a{background:var(--teal);}
.legend{display:flex;justify-content:space-between;font-size:12px;color:var(--muted);}
.big{font-size:15px;}
.stat-row{display:flex;flex-wrap:wrap;gap:12px;margin:14px 0;}
.stat{background:var(--card);border:1px solid var(--line);border-radius:var(--radius);
padding:12px 16px;flex:1 1 140px;}
.stat b{display:block;font-size:22px;color:var(--magenta-deep);}
.stat span{color:var(--muted);font-size:12px;}
.rec{border-left:4px solid var(--teal);background:var(--card);border-radius:8px;
padding:10px 14px;font-size:13px;color:var(--muted);margin:16px 0;}
.cta-row{display:flex;flex-wrap:wrap;gap:12px;margin:22px 0;}
.btn{background:var(--magenta);color:#fff;font-weight:700;padding:12px 22px;
border-radius:999px;text-decoration:none;font-size:14px;}
.btn.ghost{background:transparent;color:var(--text);border:1px solid var(--line);}
.mrow{display:flex;align-items:center;justify-content:space-between;gap:10px;
padding:12px 0;border-bottom:1px solid var(--line);}
.mrow:last-child{border-bottom:none;}
.mrow a{color:var(--magenta-deep);font-weight:700;text-decoration:none;}
.mrow .meta{color:var(--muted);font-size:12px;}
.pick{color:var(--teal-ink);font-weight:700;font-size:13px;white-space:nowrap;}
footer{border-top:1px solid var(--line);margin-top:36px;padding:22px 0 34px;
color:var(--muted);font-size:13px;}
footer a{color:var(--muted);}
.note{color:var(--muted);font-size:12px;margin:18px 0;}
"""

NAV = (
    '<div class="bar"></div><div class="wrap"><nav>'
    '<a href="/">GoalIQ</a>'
    '<span><a href="/predictions">All predictions</a> · '
    '<a class="nav-cta" href="https://pro.goaliq.app/">Try it live</a></span>'
    "</nav></div>"
)

DISCLAIMER = (
    "GoalIQ model predictions are statistical estimates for fun and analysis, "
    "not betting advice, and not a gambling service."
)


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def _fmt_pct(x: float) -> str:
    return f"{round(x * 100)}%"


def _fmt_kickoff(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%a %d %b %Y, %H:%M UTC")
    except Exception:
        return iso


def _page(title: str, desc: str, canonical: str, body: str,
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
        '<link rel="icon" href="/favicon.ico" sizes="any">\n'
        f"{ld}"
        f"<style>{CSS}</style>\n"
        "</head>\n<body>\n"
        f"{NAV}\n"
        f'<div class="wrap">\n{body}\n'
        f'<footer>© 2026 GoalIQ · <a href="/predictions">Football predictions</a> · '
        f'<a href="/fpl.html">Free FPL tools</a> · '
        f'<a href="/privacy.html">Privacy</a><br>{DISCLAIMER}</footer>\n'
        "</div>\n</body>\n</html>\n"
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


def render_match_page(comp: str, e: dict) -> str:
    cfg = LEAGUES[comp]
    home, away = e["home_team"], e["away_team"]
    ph, pd_, pa = e["p_home"], e["p_draw"], e["p_away"]
    fav = home if e["predicted_winner"] == "home" else away
    fav_pct = _fmt_pct(ph if e["predicted_winner"] == "home" else pa)
    url = f"{BASE}/predictions/{cfg['slug']}/{_match_filename(e)[:-5]}"
    title = f"{home} vs {away} Prediction – {cfg['name']} | GoalIQ"
    desc = (
        f"{home} vs {away} ({cfg['name']}, {e.get('date')}): the GoalIQ model "
        f"gives {fav} a {fav_pct} chance to win. Expected goals "
        f"{e['xg_home']:.2f}-{e['xg_away']:.2f}, most likely score "
        f"{e.get('most_likely_score') or 'n/a'}. Logged pre-match in our public "
        f"track record."
    )
    body = (
        f"<h1>{escape(home)} vs {escape(away)} prediction</h1>"
        f'<p class="lede">{escape(cfg["name"])} · kickoff {_fmt_kickoff(e.get("kickoff") or "")}. '
        f"The GoalIQ match model makes <strong>{escape(fav)}</strong> the favourite "
        f"at <strong>{fav_pct}</strong> to win.</p>"
        f'<div class="card big">{_prob_block(e)}</div>'
        f'<div class="stat-row">'
        f'<div class="stat"><b>{e["xg_home"]:.2f}</b><span>expected goals, {escape(home)}</span></div>'
        f'<div class="stat"><b>{e["xg_away"]:.2f}</b><span>expected goals, {escape(away)}</span></div>'
        f'<div class="stat"><b>{escape(e.get("most_likely_score") or "–")}</b><span>most likely score</span></div>'
        f"</div>"
        f'<div class="rec">This prediction was logged before kickoff on '
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
        },
    ]
    return _page(title, desc, url, body, jsonld)


def render_league_hub(comp: str, rows: list[dict], now: datetime) -> str:
    cfg = LEAGUES[comp]
    url = f"{BASE}/predictions/{cfg['slug']}/"
    title = f"{cfg['name']} Predictions This Week – Win % & xG | GoalIQ"
    desc = (
        f"Model predictions for upcoming {cfg['name']} matches: win probability, "
        f"expected goals and the most likely score for every fixture. Every "
        f"prediction is logged before kickoff in GoalIQ's public track record."
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
    body = (
        f"<h1>{escape(cfg['name'])} predictions</h1>"
        f'<p class="lede">The GoalIQ match model predicts every upcoming '
        f"{escape(cfg['name'])} fixture: win probability for each side, expected "
        f"goals and the most likely score. Predictions are logged before kickoff "
        f"and graded in a public track record.</p>"
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
        }
    ]
    return _page(title, desc, url, body, jsonld)


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


def main() -> int:
    now = datetime.now(timezone.utc)
    log = acc.load_log()
    by_comp = _upcoming_by_comp(log, now)

    xml = SITEMAP_PATH.read_text(encoding="utf-8")
    live_hubs: list[str] = []
    total_pages = 0

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
        # Siivoa vanhentuneet ottelusivut (kickoff mennyt / pariutus muuttui)
        keep = {"index.html"} | {_match_filename(e) for e in rows}
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
        total_pages += 1 + len(rows)
        xml = _upsert_sitemap_entry(
            xml, f"{BASE}/predictions/{cfg['slug']}/",
            now.strftime("%Y-%m-%d"), "daily", "0.8",
        )
        print(f"{comp}: hub + {len(rows)} ottelusivua → predictions/{cfg['slug']}/")

    SITEMAP_PATH.write_text(xml, encoding="utf-8")
    hub_updated = update_predictions_hub_links(live_hubs)
    print(f"Yhteensä {total_pages} sivua ({len(live_hubs)} liigaa). "
          f"predictions.html-hublinkit: {'päivitetty' if hub_updated else 'ei muutosta'}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
