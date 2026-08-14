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

# ILMAISPINNAN LINKKI OSOITTAA SIVULLE JOLLA VAITE ON, ei sivulle joka
# linkittaa sinne. Alkuperainen /fpl mainitsee hinnat mutta ei renderoi
# yhtaan riser-rivia -> lukija ei loytanyt lukua jonka tarkistettavuudella
# me myymme. Tasan 10.8:n epaonnistuminen uudelleen (muisti:
# varoitus-kaukana-luvusta).
FREE_URL = "https://goaliq.app/fpl/price-changes"

# Julkinen mini-liiga on ainoa ilmaispinta jolta lukija voi verrata itseaan
# mallin riviin. Jaadytetyn rivin kustannuksella EI ole julkista sivua, joten
# sita ei saa vaittaa tarkistettavaksi. Verifioitu /fpl/model-xi:sta.
MINI_LEAGUE_CODE = "jgi6j9"

# Premium-ominaisuuksien nimet ovat SUORAAN landing-copysta. Vapaa muotoilu
# tuottaa nimen jota tuotteessa ei ole (portti 14.8 kaatoi keksityt
# "Season pass", "pick of the week" ja "price alerts"). Jos landing muuttuu,
# tama lista muuttuu — testi pitaa ne synkassa.
PREMIUM_FEATURES = (
    "the team manager",
    "a GW1 to GW6 gameweek planner",
)

# Ilmaissivun /fpl/expected-points katkaisukohta ("Top 100 by expected points
# (of 505 players)"). Premium-lupaus on EROTUS, ei koko luku: ostaja ei saa
# maksaa siita mita han jo nakee ilmaiseksi.
FREE_XP_TOP_N = 100

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


# OTTELUBLOKKI POISTETTU TIETOISESTI (portti 14.8). Se otsikoitiin
# "Fixtures worth a second look", mutta koodi otti kolme ensimmaista ERI
# joukkuetta xP-jarjestyksessa — eli kolmen parhaan pelaajan seurat. Ne ovat
# kierroksen ilmeisimmat ottelut, eivat ne joita katsotaan toiseen kertaan.
# Otsikko vaitti toimituksellista valintaa jota koodi ei tehnyt. Blokki
# palautetaan vasta kun valinta rakennetaan ilmaisen CS/FDR-taulun luvuista.


def price_notes(watch: dict, limit: int = 3) -> dict:
    """Hinta-watchin karki. Ilmainen pinta -> luvut saa kirjoittaa nakyviin.

    LUKU LUETAAN SAMASTA KENTASTA JA SAMASSA MUODOSSA KUIN ILMAISSIVU:
    `build_fpl_longtail.py` renderoi `round(confidence * 100)%`. Aiemmin tassa
    kirjoitettiin `progress_pct` yhdella desimaalilla ("87.0 percent") — sama
    luku, mutta eri muoto kuin sivulla ("87%"). Lukija joka tarkistaa nakee
    kaksi eri nakoista lukua, ja se lukee ristiriidalta eika muotoerolta.
    """
    def rows(key: str) -> list[dict]:
        out = []
        for r in (watch.get(key) or []):
            if r.get("status", "").endswith("_soon") and not r.get(
                    "already_changed_today"):
                out.append({
                    "name": r.get("web_name"),
                    "confidence_pct": round(float(r.get("confidence") or 0.0)
                                            * 100),
                })
            if len(out) >= limit:
                break
        return out
    return {"risers": rows("risers"), "fallers": rows("fallers")}


def build_facts(deadline: dict, xp_payload: dict, watch: dict) -> dict:
    """Kaikki luvut jotka vedos saa sisaltaa. Muut hylataan portissa."""
    return {
        "gw": deadline["gw"],
        "hours_left": int(deadline["hours_left"]),
        "prices": price_notes(watch),
        "mini_league_code": MINI_LEAGUE_CODE,
        # Nama kolme ovat tosia ja tarkistettavissa, mutta ne EIVAT tulleet
        # datasta -> portti kaatoi ne aivan oikein kunnes ne kirjattiin
        # faktoiksi lahteineen. Portin loysentaminen olisi ollut vaara korjaus.
        "squad_size": 15,               # FPL:n rungon koko
        "free_xp_top_n": FREE_XP_TOP_N,  # /fpl/expected-points: "Top 100"
        # Luetaan DATASTA eika kovakoodata: jos pelaajamaara muuttuu kauden
        # aikana, vaite korjautuu itsestaan eika vanhene hiljaa.
        "total_players": len(xp_payload.get("players") or []),
    }


def render_markdown(facts: dict) -> str:
    """Vedos tekstina. Ei em dasheja, ei paikallista kelloa, ei premium-lukuja."""
    gw = facts["gw"]
    hours = facts["hours_left"]
    # Otsikko ja avauslause EIVAT toista toisiaan: sama lause kahdesti
    # perakkain on koneen tapa kirjoittaa, ja se hukkaa avauksen.
    lines = [
        f"Subject: GW{gw} deadline, {hours} hours",
        "",
        f"{hours} hours to the GW{gw} deadline.",
        "",
    ]

    prices = facts.get("prices") or {}
    risers, fallers = prices.get("risers") or [], prices.get("fallers") or []
    if risers or fallers:
        moves = []
        for r in risers:
            moves.append(f"* {r['name']} is at {r['confidence_pct']}% "
                         "towards a rise")
        for f in fallers:
            moves.append(f"* {f['name']} is at {f['confidence_pct']}% "
                         "towards a fall")
        lines.append("Our price watch tonight:")
        lines += moves
        lines.append("")
        lines.append("It's an estimate from net transfer velocity, since FPL "
                     "doesn't publish the real thresholds.")
        lines.append("")
    else:
        lines.append("Nothing is close to a price change tonight, so there's "
                     "no rush on that front.")
        lines.append("")

    # ILMAISLINKKI ON AINA MUKANA, myos kun hintablokki on tyhja. Muuten
    # sahkopostin ainoa URL on maksumuuri, ja se toistuu joka kerta kun kukaan
    # ei ole lahella hinnanmuutosta.
    lines += [
        f"Full price watch, free and no sign-in: {FREE_URL}",
        "",
        f"The model's own {facts['squad_size']} for GW{gw} gets locked before "
        "the deadline and "
        "graded on official FPL points, same as yours. It plays a public "
        f"mini-league, code {facts['mini_league_code']}, if you want to beat "
        "it.",
        "",
        # Premium-nimet tulevat PREMIUM_FEATURES-listasta joka on landing-copyn
        # peili. xP mainitaan erotuksena, koska ilmaissivu nayttaa jo top 100:n
        # eika ostaja saa maksaa siita mita han jo nakee.
        "Premium is " + " and ".join(PREMIUM_FEATURES)
        + f", plus expected points for all {facts['total_players']} players "
          f"instead of the free top {facts['free_xp_top_n']}.",
        CTA_URL,
        "",
        "You signed up at goaliq.app. Unsubscribe below.",
    ]
    return "\n".join(lines)


def render_html(markdown: str) -> str:
    """Yksinkertainen HTML MailerLiten Drag & drop -editoriin liitettavaksi
    (muisti: Simple editorin alatunniste on lukittu)."""
    # Listat rakennetaan tilakoneella eika replace(..., 1):lla. Vanha versio
    # avasi ja sulki <ul>:n TASAN KERRAN, joten toinen lista tuotti orpoja
    # <li>-elementteja — ja mekaaninen portti palautti silti [] (se katsoi
    # markdownia, ei HTMLia). Rikkinainen deliverable lapaisi portin tasan
    # siina tapauksessa joka oikeasti lahetetaan.
    body: list[str] = []
    in_list = False
    for line in markdown.split("\n"):
        if not line.strip() or line.startswith("Subject: "):
            continue
        if line.startswith("* "):
            if not in_list:
                body.append("<ul>")
                in_list = True
            body.append(f"<li>{line[2:]}</li>")
        else:
            if in_list:
                body.append("</ul>")
                in_list = False
            body.append(f"<p>{line}</p>")
    if in_list:
        body.append("</ul>")
    return "\n".join(body)


def html_problems(html: str) -> list[str]:
    """HTMLin rakenteelliset viat. Erillinen funktio, koska markdown-portti
    on niille rakenteellisesti sokea."""
    problems = []
    if html.count("<ul>") != html.count("</ul>"):
        problems.append("<ul>-tagit eivat tasmaa")
    if html.count("<li>") != html.count("</li>"):
        problems.append("<li>-tagit eivat tasmaa")
    depth = 0
    for token in html.replace("<", "\n<").split("\n"):
        if token.startswith("<ul>"):
            depth += 1
        elif token.startswith("</ul>"):
            depth -= 1
        elif token.startswith("<li>") and depth == 0:
            problems.append("orpo <li> ilman <ul>:aa")
            break
    return problems


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

    # ILMAISLINKKI ON PAKOLLINEN. Ilman tata vedos jonka hintablokki on tyhja
    # sisaltaa vain maksumuurin, ja portin 1. kysymys ("voiko lukija
    # tarkistaa taman") kaatuu ilman etta mikaan huutaa.
    if FREE_URL not in markdown:
        problems.append("ilmaispinnan linkki puuttuu")

    # KEKSITYT OMINAISUUSNIMET. Portti kaatoi 14.8 kolme nimea joita
    # tuotteessa ei ole ("pick of the week", "price alerts", "Season pass").
    # Nimi joka ei ole landing-copyssa ei saa paatya sahkopostiin.
    for invented in ("pick of the week", "price alert", "season pass",
                     "members also get"):
        if invented in lowered:
            problems.append(f"ominaisuusnimi ei ole landing-copyssa: "
                            f"{invented!r}")

    # LYHENTEIDEN PUUTE on kirjatuin AI-tunnusmerkki (muisti:
    # reddit-ai-teksti-tunnistetaan). Tama ei korvaa agenttia, mutta halvin
    # osuma kannattaa ottaa koneella.
    for stiff in ("here is what", "you are getting this", "do not publish"):
        if stiff in lowered:
            problems.append(f"lyhentamaton muoto: {stiff!r}")

    problems += html_problems(render_html(markdown))
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
