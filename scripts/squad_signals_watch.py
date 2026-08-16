"""SQUAD-SIGNALS-WATCH — ajuri (vaihe A + raportti).

Speksi: goaliq-app/cos-reports/squad-signals-watch-spec-2026-08-15.md

Ajo:
    python scripts/squad_signals_watch.py                # normaali paivittainen
    python scripts/squad_signals_watch.py --dry-run      # ei kirjoita lumikuvaa
    python scripts/squad_signals_watch.py --out <polku>

🔴 EI KOSKAAN AUTOMAATTISTA SOVELTAMISTA. Tama kirjoittaa raportin ja lokin.
Ohitus `data/fpl_player_overrides.csv`:hen on aina ihmisen paatos
lahdeviitteella. Liputus on kysymys, ei vaite.

Ajetaan PAIKALLISESTI (Task Scheduler), ei GitHub-runnerilta: runnerin
egress on GitHub-only, joten FPL-suuntaiset kutsut estyvat siella (kirjattu
tapaus). Vaihe A ei sinansa tarvitse muuta kuin FPL:n bootstrapin, mutta
vaihe B (verkkohaku shortlistille) tarvitsee taydet oikeudet.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data.fpl_api import fetch_bootstrap  # noqa: E402
from src.models.squad_signals import (  # noqa: E402
    Flag,
    Snapshot,
    diff_signals,
    summarise,
    team_name_map,
)

SNAPSHOT_PATH = ROOT / "data" / "squad_signals_snapshot.json"
FLAG_LOG_PATH = ROOT / "data" / "watch_flags.json"
# Raportit elavat goaliq-app-hubissa (CLAUDE.md: QUEUE, promptit ja raportit
# aina siella, koska CoS ei nae tata repoa).
HUB_WATCH_DIR = Path(r"C:\Users\vvsaa\Documents\goaliq-app\cos-reports\watch")
PROJECTIONS_PATH = ROOT / "data" / "fpl_xp_projections.json"

TRIGGER_LABELS = {
    "status": "Saatavuus",
    "chance_conflict": "Erimielisyys FPL:n kanssa",
    "set_piece_order": "Erikoistilannejarjestys",
    "transfer": "Siirto",
    "new_player": "Uusi pelaaja",
}


def _load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _fmt(v) -> str:
    if v is None:
        return "-"
    return str(v)


def render_report(flags: list[Flag], prev_taken_at: str | None,
                  taken_at: str, roster_size: int) -> str:
    """Ihmisluettava raportti. Raaka JSON ei ole tarkistus vaan este
    (kirjattu oppi): jokainen rivi kertoo mika muuttui ja mika meidan luku
    on, jotta lukija voi paattaa ilman etta avaa artefaktia."""
    lines: list[str] = []
    lines.append(f"# Squad signals — {taken_at[:10]}")
    lines.append("")
    if prev_taken_at:
        lines.append(f"Vertailu edelliseen lumikuvaan **{prev_taken_at[:10]}**. "
                     f"Rosterissa {roster_size} pelaajaa.")
    else:
        lines.append(
            f"**Ensimmainen ajo** — lumikuva kirjoitettu ({roster_size} "
            f"pelaajaa), ei vertailukohtaa. Ensimmainen ajo ei liputa mitaan: "
            f"se ei ole muutos, ja koko rosterin liputtaminen olisi kohinaa.")
    lines.append("")

    if not flags:
        lines.append("Ei muutoksia. **Tama on validi tulos** eika merkki "
                     "rikkinaisesta vahdista.")
        lines.append("")
        # Sokeat pisteet myos tyhjaan raporttiin — nimenomaan silloin
        # hiljaisuus luettaisiin todennakoisimmin "kaikki ennallaan".
        lines.append(_blind_spot_note())
        return "\n".join(lines)

    counts = summarise(flags)
    lines.append("| laukaisin | kpl |")
    lines.append("|---|---|")
    for trig, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        lines.append(f"| {TRIGGER_LABELS.get(trig, trig)} | {n} |")
    lines.append("")

    lines.append("## Liputukset (omistuksen mukaan)")
    lines.append("")
    lines.append("| pelaaja | laukaisin | kentta | ennen | jalkeen | omistus % | meidan p_start |")
    lines.append("|---|---|---|---|---|---|---|")
    for f in flags:
        owned = f"{f.owned_pct:.1f}" if f.owned_pct is not None else "-"
        ps = f"{f.our_p_start:.2f}" if f.our_p_start is not None else "-"
        lines.append(
            f"| {f.web_name} | {TRIGGER_LABELS.get(f.trigger, f.trigger)} | "
            f"{f.field} | {_fmt(f.before)} | {_fmt(f.after)} | {owned} | {ps} |")
    lines.append("")

    lines.append("## Ehdotetut ohitusrivit")
    lines.append("")
    lines.append("🔴 **EI SOVELLETTU.** Ohitus on ihmisen paatos "
                 "lahdeviitteella, ja `review_by` pakottaa "
                 "uusintatarkistuksen. Vahti ei arvioi kuka aloittaa — se "
                 "kertoo missa syotteemme on vanhentunut.")
    lines.append("")
    lines.append(_blind_spot_note())
    return "\n".join(lines)


def _blind_spot_note() -> str:
    """Villen paatos 16.8: **vahti ei kysy.**

    Speksin ulottuvuus 5 (esikauden muoto) ehdotti etta ensimmainen versio
    kysyisi Villelta sen sijaan etta arvaisi. Ville: ei kysy. Rajoite
    kirjataan siis nakyviin sen sijaan etta se muuttuisi kysymykseksi.

    Tama ei ole kohteliaisuusteksti vaan portti lukijalle: ilman sita
    raportin hiljaisuus jostain pelaajasta luettaisiin "ei muutosta", kun
    oikea luenta on "ei kanavaa". Tasan se ero kaatoi Joao Pedro -kulman
    15.8.
    """
    return "\n".join([
        "## Mita tama vahti EI nae",
        "",
        "Nama eivat ole hiljaisuutta vaan sokeita pisteita. Jos pelaaja ei",
        "esiinny ylla, se EI tarkoita etta hanen tilanteensa on ennallaan.",
        "",
        "- **Esikauden muoto.** Ystavyysotteluille ei ole ilmaista",
        "  rakenteista lahdetta, eika minuuttimalli syota niita lainkaan.",
        "  Aloitustodennakoisyys on johdettu VIIME KAUDEN minuuteista.",
        "  (15.8: Joao Pedro teki kaksi esikauden maalia eika lukumme",
        "  liikkunut lainkaan.)",
        "- **Pelityylit ja -tavat.** Rooliosuus on johdettavissa Understatin",
        "  laukaisutasosta, mutta se on viime kauden rooli eika taman.",
        "- **Hintaliike ilman xP-liiketta** (laukaisin 5). Vaatii",
        "  xP-historian, jota ei viela kerata.",
        "",
    ])


def append_flag_log(flags: list[Flag], taken_at: str) -> None:
    """Loki on se mika tekee osumatarkkuuden mittaamisesta mahdollista.
    Ilman sita vahdin laatu olisi arvio, ja mittari olisi liputusten maara
    eli tasan vaara mittari (speksin luku 5)."""
    log = _load_json(FLAG_LOG_PATH) or {"runs": []}
    log["runs"].append({
        "taken_at": taken_at,
        "flags": [f.as_dict() for f in flags],
    })
    FLAG_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    FLAG_LOG_PATH.write_text(
        json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="ala kirjoita lumikuvaa tai lokia")
    ap.add_argument("--out", default=None, help="raportin polku")
    args = ap.parse_args()

    taken_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    bootstrap = fetch_bootstrap(force=True)
    curr = Snapshot.from_bootstrap(bootstrap, taken_at)
    prev_raw = _load_json(SNAPSHOT_PATH)
    prev = Snapshot.from_dict(prev_raw) if prev_raw else None

    flags = diff_signals(
        prev, curr,
        projections=_load_json(PROJECTIONS_PATH),
        team_names=team_name_map(bootstrap),
    )

    report = render_report(
        flags, prev.taken_at if prev else None, taken_at, len(curr.players))

    out = Path(args.out) if args.out else (
        HUB_WATCH_DIR / f"squad-signals-{taken_at[:10]}.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")

    if not args.dry_run:
        SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
        SNAPSHOT_PATH.write_text(
            json.dumps(curr.as_dict(), ensure_ascii=False), encoding="utf-8")
        append_flag_log(flags, taken_at)

    counts = summarise(flags)
    print(f"[squad-signals] {len(flags)} liputusta {len(curr.players)} "
          f"pelaajasta; {counts or 'ei muutoksia'}")
    print(f"[squad-signals] raportti: {out}")
    if args.dry_run:
        print("[squad-signals] DRY RUN: lumikuvaa ja lokia EI kirjoitettu")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
