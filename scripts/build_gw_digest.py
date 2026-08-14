"""GW-DEADLINE-DIGEST: MailerLite-vedos kierroksen deadlinesta (14.8).

Kehityslista 12.8 (Villen paatos): "sama data kuin push-notifikaatioissa
sahkopostilistalle. Kanava jo kytketty (MCP), puuttuu sisaltoputki."

TAMA SKRIPTI EI LAHETA MITAAN, EIKA SAA LAHETTAA. Se kirjoittaa vedoksen
levylle. Syy on CLAUDE.md:n saanto 6b: jokainen julkinen teksti ajetaan
julkaisutarkistaja-agentin lapi ENNEN kuin se naytetaan Villelle. Cron joka
lahettaisi 134 tilaajalle ilman porttia kiertaisi tasan sen saannon jonka
takia portti on olemassa — ja sahkoposti on ainoa kanava jota ei voi
poistaa jalkikateen.

TOINEN KOVA SAANTO: digest rakennetaan ILMAISPINNAN luvuista. Portin 1.
kysymys on "pystyyko lukija tarkistamaan vaitteen ilmaispinnalta". Pelaajan
xP on premiumin takana, joten sita EI kirjoiteta lukuna vedokseen — premium
teasataan nimella, ei luvulla. Hinta-watch, deadline ja ohjelma ovat
ilmaisia ja siksi tarkistettavia.

KOLMAS: vedos generoidaan LAHETYSHETKELLA, ei etukateen. Botti paivittaa
projektiot ja hintawatchin 3 h valein; viikko sitten generoitu vedos on
vanhentunut eika sita saa lahettaa (muisti: verifiointi postaushetkella).

Exit 0 myos kun ei deadlinea nakyvissa; tekninen virhe -> 1.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests

import config
from scripts.build_fpl_why import ungrounded_numbers

OUT_DIR = config.PROJECT_ROOT / "outputs" / "gw_digest"
XP_PATH = config.PROJECT_ROOT / "data" / "fpl_xp_projections.json"
PRICE_PATH = config.PROJECT_ROOT / "data" / "fpl_price_watch.json"
FROZEN_DIR = config.PROJECT_ROOT / "data" / "model_squad_frozen"

FPL_BASE = "https://fantasy.premierleague.com/api"
FPL_HEADERS = {"User-Agent": "Mozilla/5.0 (GoalIQ digest)"}

# CTA on aina season-checkout (muisti: goaliq-email-stack).
CTA_URL = "https://pro.goaliq.app/checkout?plan=season"
FREE_URL = "https://goaliq.app/fpl"

# Digest lahetetaan vasta kun deadline on lahella: aikaisemmin lahetetty
# muistutus ei ole muistutus vaan uutiskirje, ja avausprosentti kertoo sen.
SEND_WINDOW_H = (6.0, 48.0)


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def next_deadline(events: list[dict], now: _dt.datetime) -> dict | None:
    """Lahin tuleva GW-deadline. None jos kausi on ohi."""
    best = None
    for e in events or []:
        raw = e.get("deadline_time")
        if not raw:
            continue
        try:
            dl = _dt.datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            continue
        if dl <= now:
            continue
        if best is None or dl < best[1]:
            best = (int(e.get("id") or 0), dl)
    if best is None:
        return None
    gw, dl = best
    return {"gw": gw, "deadline": dl,
            "hours_left": round((dl - now).total_seconds() / 3600.0, 1)}


def fixture_notes(xp_payload: dict, gw: int, limit: int = 3) -> list[dict]:
    """Joukkueet joilla on tunnistettavin ohjelma tulevalla kierroksella.

    Vastustaja + kentta ovat ilmaissivulla, joten lukija voi tarkistaa taman
    yhdessa sekunnissa. Mitaan mallin lukua ei liiteta.
    """
    seen: dict[str, dict] = {}
    for p in xp_payload.get("players") or []:
        team = p.get("team")
        if not team or team in seen:
            continue
        for g in p.get("gameweeks") or []:
            if g.get("gw") != gw:
                continue
            opps = g.get("opponents") or []
            if opps:
                seen[team] = {
                    "team": team,
                    "opponent": opps[0].get("opp"),
                    "venue": opps[0].get("venue"),
                }
            break
    return list(seen.values())[:limit]


def price_notes(watch: dict, limit: int = 3) -> dict:
    """Hinta-watchin karki. Ilmainen pinta -> luvut saa kirjoittaa nakyviin."""
    def rows(key: str) -> list[dict]:
        out = []
        for r in (watch.get(key) or []):
            if r.get("status", "").endswith("_soon") and not r.get(
                    "already_changed_today"):
                out.append({"name": r.get("web_name"),
                            "progress_pct": r.get("progress_pct")})
            if len(out) >= limit:
                break
        return out
    return {"risers": rows("risers"), "fallers": rows("fallers")}


def frozen_squad_note(gw: int) -> dict | None:
    """Mallin lukittu rivi jos se on jo jaadytetty (BTM V2). Julkinen."""
    path = FROZEN_DIR / f"gw{gw}.json"
    data = read_json(path)
    if not data:
        return None
    return {"cost_m": data.get("cost"), "frozen_at": data.get("frozen_at")}


def build_facts(deadline: dict, xp_payload: dict, watch: dict) -> dict:
    """Kaikki luvut jotka vedos saa sisaltaa. Muut hylataan portissa."""
    facts = {
        "gw": deadline["gw"],
        "hours_left": int(deadline["hours_left"]),
        "fixtures": fixture_notes(xp_payload, deadline["gw"]),
        "prices": price_notes(watch),
    }
    frozen = frozen_squad_note(deadline["gw"])
    if frozen:
        facts["model_squad"] = frozen
    return facts


def render_markdown(facts: dict) -> str:
    """Vedos tekstina. Ei em dasheja, ei paikallista kelloa, ei premium-lukuja."""
    gw = facts["gw"]
    hours = facts["hours_left"]
    lines = [
        f"Subject: GW{gw} deadline in about {hours} hours",
        "",
        f"The GW{gw} deadline is about {hours} hours away. Here is what "
        "moved since you last looked.",
        "",
    ]

    prices = facts.get("prices") or {}
    risers, fallers = prices.get("risers") or [], prices.get("fallers") or []
    if risers or fallers:
        lines.append("Prices on the move")
        for r in risers:
            lines.append(f"* {r['name']} is {r['progress_pct']} percent of "
                         "the way to a rise")
        for f in fallers:
            lines.append(f"* {f['name']} is {f['progress_pct']} percent of "
                         "the way to a fall")
        lines.append("")
        lines.append("Those numbers come from transfer velocity, not from "
                     f"FPL. You can check them yourself at {FREE_URL}.")
        lines.append("")

    fixtures = facts.get("fixtures") or []
    if fixtures:
        lines.append("Fixtures worth a second look")
        for f in fixtures:
            venue = "at home to" if f.get("venue") == "H" else "away at"
            lines.append(f"* {f['team']} {venue} {f['opponent']}")
        lines.append("")

    squad = facts.get("model_squad")
    if squad and squad.get("cost_m") is not None:
        lines.append(
            f"The model's own squad for GW{gw} is locked at "
            f"{squad['cost_m']} million and logged before kickoff, so you "
            "can score yourself against it when the round finishes.")
        lines.append("")

    lines += [
        "Members also get the model's pick of the week, expected points for "
        "every player, and price alerts on their own watchlist.",
        "",
        f"Season pass: {CTA_URL}",
        "",
        "You are getting this because you signed up at goaliq.app. "
        "Unsubscribe any time from the link below.",
    ]
    return "\n".join(lines)


def render_html(markdown: str) -> str:
    """Yksinkertainen HTML MailerLiten Drag & drop -editoriin liitettavaksi
    (muisti: Simple editorin alatunniste on lukittu)."""
    body = []
    for line in markdown.split("\n"):
        if not line.strip():
            continue
        if line.startswith("Subject: "):
            continue
        if line.startswith("* "):
            body.append(f"<li>{line[2:]}</li>")
        else:
            body.append(f"<p>{line}</p>")
    html = "\n".join(body).replace("<li>", "<ul><li>", 1)
    if "<li>" in html:
        html = html.replace("</li>\n<p>", "</li></ul>\n<p>", 1)
    return html


def draft_problems(markdown: str, facts: dict) -> list[str]:
    """Vedoksen mekaaniset portit. Tyhja = valmis agenttitarkistukseen.

    HUOM: tama EI korvaa julkaisutarkistajaa. Tama loytaa pohjattomat luvut
    ja kielletyt merkit; agentti loytaa AI-tunnusmerkit ja kulman uutuuden.
    """
    problems: list[str] = []
    body = markdown.split("\n", 1)[1] if "\n" in markdown else markdown
    bad = ungrounded_numbers(body, facts)
    if bad:
        problems.append("pohjaton luku: " + ", ".join(sorted(set(bad))))
    for ch in ("—", "–"):
        if ch in markdown:
            problems.append(f"kielletty merkki: {ch}")
    lowered = markdown.lower()
    for word in ("odds", "eest", "eet", "helsinki"):
        if word in lowered:
            problems.append(f"kielletty sana: {word}")
    if CTA_URL not in markdown:
        problems.append("CTA puuttuu")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true",
                    help="rakenna vedos vaikka deadline ei ole ikkunassa")
    args = ap.parse_args()

    now = _dt.datetime.now(_dt.timezone.utc)
    try:
        boot = requests.get(f"{FPL_BASE}/bootstrap-static/",
                            headers=FPL_HEADERS, timeout=30).json()
    except (requests.RequestException, ValueError) as e:
        print(f"VIRHE: FPL bootstrap epaonnistui: {e}")
        return 1

    deadline = next_deadline(boot.get("events") or [], now)
    if deadline is None:
        print("Ei tulevaa deadlinea — ei vedosta.")
        return 0
    print(f"GW{deadline['gw']}, deadlineen {deadline['hours_left']} h")

    lo, hi = SEND_WINDOW_H
    if not args.force and not (lo <= deadline["hours_left"] <= hi):
        print(f"Deadline ei ole lahetysikkunassa ({lo}-{hi} h) — ei vedosta. "
              "Aja --force jos haluat vedoksen silti.")
        return 0

    facts = build_facts(deadline, read_json(XP_PATH), read_json(PRICE_PATH))
    markdown = render_markdown(facts)
    problems = draft_problems(markdown, facts)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stem = OUT_DIR / f"gw{deadline['gw']}"
    stem.with_suffix(".md").write_text(markdown, encoding="utf-8")
    stem.with_suffix(".html").write_text(render_html(markdown),
                                         encoding="utf-8")
    stem.with_suffix(".facts.json").write_text(
        json.dumps(facts, ensure_ascii=False, indent=1, default=str),
        encoding="utf-8")

    if problems:
        print("::warning::vedoksessa on ongelmia: " + "; ".join(problems))
    print(f"OK: {stem.with_suffix('.md').name} kirjoitettu "
          f"({len(markdown)} merkkia).")
    print("SEURAAVA ASKEL: aja julkaisutarkistaja tälle vedokselle ENNEN "
          "kuin naytat sen Villelle. Tama skripti ei laheta mitaan.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"VIRHE: build_gw_digest kaatui: {exc}")
        sys.exit(1)
