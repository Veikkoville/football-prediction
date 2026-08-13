"""Beat the Model V2 vaihe b: mallin joukkueen gradaus (13.8).

Kun jäädytetty GW on ratkennut (finished + data_checked), lasketaan mallin
lukitulle riville FPL:n omat pisteet: XI + autosubit + kapteenin tuplaus.
Append-only-loki data/model_squad_gw_scores.json.

Säännöt ovat src/models/fpl_autosub.py:ssä puhtaana logiikkana ja katettu
omalla testisetillä (tests/test_fpl_autosub.py) — spec nimeää autosubin
ainoaksi oikeasti virhealttiiksi palaksi, ja väärä luku julkisessa
race-paneelissa on luottamusmyrkkyä.

Luku on tarkistettavissa: se lasketaan FPL:n `total_points`-kentästä
jäädytetylle riville, jonka git-historia todistaa lukituksi ennen deadlinea.

Idempotentti per GW. Exit 0 kun ei gradattavaa; tekninen virhe → 1.
"""
from __future__ import annotations

import datetime as _dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests

import config
from src.models.fpl_autosub import score_gw

FROZEN_DIR = config.PROJECT_ROOT / "data" / "model_squad_frozen"
LOG_PATH = config.PROJECT_ROOT / "data" / "model_squad_gw_scores.json"
FPL_BASE = "https://fantasy.premierleague.com/api"
FPL_HEADERS = {"User-Agent": "Mozilla/5.0 (GoalIQ grade job)"}

_NEW_LOG = {
    "meta": {
        "product": "GoalIQ Beat the Model — model squad per-GW scores",
        "rules": ("The model's squad is frozen before the deadline "
                  "(immutable, provable from git history) and scored with "
                  "official FPL points once the gameweek finishes. "
                  "Autosubs and the captain/vice rule are applied exactly as "
                  "FPL applies them. The model plays no chips. Append-only."),
    },
    "gameweeks": [],
}


def main() -> int:
    if not FROZEN_DIR.exists():
        print("Ei jäädytettyjä mallirivejä — ei gradattavaa.")
        return 0
    log = (json.loads(LOG_PATH.read_text(encoding="utf-8"))
           if LOG_PATH.exists() else json.loads(json.dumps(_NEW_LOG)))
    done = {g.get("gw") for g in log["gameweeks"]}

    pending = []
    for f in sorted(FROZEN_DIR.glob("gw*.json")):
        frozen = json.loads(f.read_text(encoding="utf-8"))
        gw = frozen.get("meta", {}).get("gw")
        if gw not in done:
            pending.append((gw, frozen))
    if not pending:
        print("Kaikki jäädytetyt mallirivit on jo gradattu.")
        return 0

    try:
        r = requests.get(f"{FPL_BASE}/bootstrap-static/", headers=FPL_HEADERS,
                         timeout=30)
        r.raise_for_status()
        events = {int(e["id"]): e for e in r.json().get("events") or []}
    except Exception as e:
        print(f"VIRHE: bootstrap-haku epäonnistui: {e!r}")
        return 1

    graded = 0
    for gw, frozen in pending:
        ev = events.get(int(gw))
        if not ev or not (ev.get("finished") and ev.get("data_checked")):
            print(f"GW{gw}: ei vielä ratkennut (finished+data_checked) — odotetaan.")
            continue
        try:
            r = requests.get(f"{FPL_BASE}/event/{gw}/live/",
                             headers=FPL_HEADERS, timeout=60)
            r.raise_for_status()
            live = r.json()
        except Exception as e:
            print(f"VIRHE: event/{gw}/live-haku epäonnistui: {e!r}")
            return 1
        points, minutes = {}, {}
        for el in live.get("elements") or []:
            st = el.get("stats") or {}
            points[int(el["id"])] = int(st.get("total_points") or 0)
            minutes[int(el["id"])] = int(st.get("minutes") or 0)

        row = score_gw(frozen, points, minutes)
        row["graded_at"] = _dt.datetime.now(_dt.timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ")
        row["frozen_at"] = frozen.get("meta", {}).get("frozen_at")
        # Keskiarvo vertailukohdaksi: "voititko mallin" on eri kysymys kuin
        # "voititko keskiverto-FPL-managerin", ja molemmat kiinnostavat.
        row["fpl_average"] = ev.get("average_entry_score")
        log["gameweeks"].append(row)
        graded += 1
        subs = ", ".join(f"{s['out']}->{s['in']}" for s in row["autosubs"]) or "-"
        print(f"OK: GW{gw} mallin rivi gradattu — {row['points']} p "
              f"(ilman kapteenia {row['points_before_captain']}, "
              f"kapteeni {row['captain_reason']} +{row['captain_points_added']}), "
              f"autosubit: {subs}, penkille jäi {row['bench_points']} p, "
              f"FPL-keskiarvo {row['fpl_average']}.")

    if graded:
        LOG_PATH.write_text(json.dumps(log, ensure_ascii=False, indent=1) + "\n",
                            encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
