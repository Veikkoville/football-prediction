"""Beat the Model V2 -vahti: FPL-tilin rivi vs jäädytetty rivi (14.8).

MIKSI TÄMÄ ON OLEMASSA. `freeze_model_squad_gw.py` lukitsee mallin rungon
tiedostoon ja tekee siitä todistettavan git-historiasta. Mutta se EI kosketa
FPL-tiliä: rivi syötetään FPL:ään käsin. Nämä kaksi ovat siis kaksi eri
totuutta mallin joukkueesta, ja niiden välillä ei ollut mitään joka
huomaisi eron.

Mitattu 14.8: entryn rivi valittiin käsin **23.7** — eli ENNEN 13.8:n
P0-korjausta joka muutti mallin XI:n (101,5 m laiton runko → 100,0 m,
XI xP 311,91 → 277,49). Jos entryä ei päivitetty, "malli pelaa omaa
FPL-joukkuettaan" osoittaa joukkueeseen jota malli ei valinnut — ja koko
Beat the Model, Season race ja "logged before kickoff" nojaavat siihen.

Vahti ei voi korjata tätä (FPL-tilille kirjautuminen on käsityötä eikä sitä
automatisoida). Se tekee erosta ÄÄNEKKÄÄN:

  * ennen deadlinea  -> tulostaa rivin syötettävässä muodossa, exit 0
  * deadlinen jälkeen -> vertaa entryn picksejä jäädytettyyn, ero = exit 1

Ennen-deadlinea-haara on tarkoituksella exit 0: rivin syöttäminen on
Villen tehtävä eikä puuttuva syöttö ole vielä virhe. Jälkeen-haara on
exit 1, koska silloin se on peruuttamaton.

Käyttö:
    python -m scripts.verify_model_entry_matches_freeze          # uusin GW
    python -m scripts.verify_model_entry_matches_freeze --gw 1
    python -m scripts.verify_model_entry_matches_freeze --print  # aina tuloste
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests

import config

FROZEN_DIR = config.PROJECT_ROOT / "data" / "model_squad_frozen"
FPL_BASE = "https://fantasy.premierleague.com/api"
FPL_HEADERS = {"User-Agent": "Mozilla/5.0 (GoalIQ entry-check job)"}

# Entry EI ole kovakoodattu vaan ymparistosta, jotta tama skripti ei ole
# ainoa paikka jossa mallin tilinumero elaa. Oletus on nykyinen tili.
ENTRY_ID = int(os.environ.get("FPL_MODEL_ENTRY_ID", "116920"))

POS_NAME = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}


def latest_frozen() -> Path | None:
    """Suurin gw{N}.json. Nimesta luetaan numero, ei lajitella merkkijonona
    (gw10 < gw9 merkkijonona)."""
    if not FROZEN_DIR.exists():
        return None
    best, best_gw = None, -1
    for p in FROZEN_DIR.glob("gw*.json"):
        m = re.fullmatch(r"gw(\d+)\.json", p.name)
        if not m:
            continue
        n = int(m.group(1))
        if n > best_gw:
            best, best_gw = p, n
    return best


def enterable(frozen: dict) -> str:
    """Runko muodossa jonka voi syottaa FPL:aan rivi kerrallaan."""
    lines = []
    cap, vice = frozen.get("captain"), frozen.get("vice_captain")
    for label, rows in (("XI", frozen.get("xi") or []),
                        ("PENKKI (jarjestyksessa)", frozen.get("bench") or [])):
        lines.append(f"  {label}:")
        for i, p in enumerate(rows, 1):
            mark = ""
            if p.get("id") == cap:
                mark = "  <- KAPTEENI"
            elif p.get("id") == vice:
                mark = "  <- VARAKAPTEENI"
            pos = POS_NAME.get(p.get("pos"), "?")
            price = (p.get("price") or 0) / 10
            lines.append(f"    {i:>2}. {pos} {p.get('web_name','?'):<16} "
                         f"{p.get('team_short','?'):<4} {price:>4.1f}m{mark}")
    return "\n".join(lines)


def fetch_picks(entry: int, gw: int):
    """(picks, status). picks=None kun ei saatavilla."""
    url = f"{FPL_BASE}/entry/{entry}/event/{gw}/picks/"
    try:
        r = requests.get(url, headers=FPL_HEADERS, timeout=30)
    except Exception as e:
        return None, f"verkkovirhe: {e!r}"
    if r.status_code == 404:
        return None, "404"
    if r.status_code != 200:
        return None, f"HTTP {r.status_code}"
    try:
        return r.json().get("picks") or [], "200"
    except Exception as e:
        return None, f"JSON-virhe: {e!r}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gw", type=int, default=None)
    ap.add_argument("--print", dest="always_print", action="store_true")
    args = ap.parse_args()

    path = (FROZEN_DIR / f"gw{args.gw}.json") if args.gw else latest_frozen()
    if path is None or not path.exists():
        # EI VIRHE: ennen kauden ensimmaista freezea hakemistoa ei ole.
        print("::notice::Ei jaadytettya runkoa viela — ei verrattavaa.")
        return 0

    frozen = json.loads(path.read_text(encoding="utf-8"))
    meta = frozen.get("meta") or {}
    gw = int(meta.get("gw") or 0)
    deadline = _dt.datetime.fromisoformat(
        str(meta.get("deadline", "")).replace("Z", "+00:00"))
    now = _dt.datetime.now(_dt.timezone.utc)

    frozen_ids = {p["id"] for p in (frozen.get("xi") or [])}
    frozen_ids |= {p["id"] for p in (frozen.get("bench") or [])}

    print(f"GW{gw} jaadytetty {meta.get('frozen_at')}, deadline {meta.get('deadline')}")
    print(f"entry {ENTRY_ID}, jaadytetyssa {len(frozen_ids)} pelaajaa")

    if now < deadline:
        left = deadline - now
        h = int(left.total_seconds() // 3600)
        print(f"::notice::Deadlineen {h} h — rivi on syotettava FPL-tilille "
              f"ENNEN sita. Vahti kaantyy virheeksi deadlinen jalkeen.")
        print(enterable(frozen))
        return 0

    picks, status = fetch_picks(ENTRY_ID, gw)
    if picks is None:
        print(f"::error::Entryn {ENTRY_ID} GW{gw}-rivi ei ole luettavissa "
              f"({status}) vaikka deadline on mennyt. Joko tilia ei ole "
              f"pelattu tassa kierroksessa tai entry-id on vaara.")
        return 1

    entry_ids = {int(p["element"]) for p in picks}
    missing = frozen_ids - entry_ids     # mallilla on, tilillä ei
    extra = entry_ids - frozen_ids       # tilillä on, mallilla ei

    if args.always_print:
        print(enterable(frozen))

    if not missing and not extra:
        cap_entry = next((int(p["element"]) for p in picks
                          if p.get("is_captain")), None)
        cap_frozen = frozen.get("captain")
        if cap_entry != cap_frozen:
            print(f"::error::15 tasmaa mutta KAPTEENI eroaa: tilillä "
                  f"{cap_entry}, jaadytetyssa {cap_frozen}. Kapteeni on "
                  f"kaksinkertainen pistevaikutus, joten tama ei ole "
                  f"kosmeettinen ero.")
            return 1
        print(f"OK: entry {ENTRY_ID} vastaa GW{gw}:n jaadytettya runkoa "
              f"(15/15 + kapteeni).")
        return 0

    names = {p["id"]: p.get("web_name", "?")
             for p in (frozen.get("xi") or []) + (frozen.get("bench") or [])}
    print(f"::error::ENTRY {ENTRY_ID} EI VASTAA GW{gw}:N JAADYTETTYA RUNKOA.")
    print(f"::error::Julkinen vaite 'malli pelaa omaa FPL-joukkuettaan' "
          f"osoittaa joukkueeseen jota malli ei valinnut.")
    if missing:
        print("  Jaadytetyssa mutta EI tilillä: "
              + ", ".join(f"{names.get(i, i)} ({i})" for i in sorted(missing)))
    if extra:
        print("  Tilillä mutta EI jaadytetyssa: "
              + ", ".join(str(i) for i in sorted(extra)))
    return 1


if __name__ == "__main__":
    sys.exit(main())
