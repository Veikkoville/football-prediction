"""xP vs toteuma -gradaus (30.7, Villen GO): putken osa 2.

Kun jäädytetty GW on ratkennut (bootstrap: finished + data_checked), haetaan
toteutuneet pisteet /event/{gw}/live/ ja gradataan jäädytetty ennuste.
Append-only-loki data/fpl_xp_gw_accuracy.json — MAE + bias kokonaisuutena ja
positioittain, EI cherry-pickausta: kaikki jäädytetyt pelaajat mukana, myös
ne joiden xmins petti (0 minuuttia pelannut projisoitu pelaaja on aito miss).

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

FROZEN_DIR = config.PROJECT_ROOT / "data" / "fpl_xp_frozen"
LOG_PATH = config.PROJECT_ROOT / "data" / "fpl_xp_gw_accuracy.json"
FPL_BASE = "https://fantasy.premierleague.com/api"
FPL_HEADERS = {"User-Agent": "Mozilla/5.0 (GoalIQ grade job)"}


def grade_gw(frozen: dict, actual_points: dict[int, int]) -> dict:
    """Puhdas ydin: jäädytetty ennuste + toteutuneet pisteet → GW-rivi."""
    diffs, by_pos = [], {}
    for p in frozen.get("players") or []:
        xp = p.get("xp")
        if xp is None:
            continue
        actual = actual_points.get(int(p["id"]), 0)
        d = actual - float(xp)
        diffs.append(d)
        by_pos.setdefault(p.get("pos") or "?", []).append(d)
    n = len(diffs)
    mae = sum(abs(d) for d in diffs) / n if n else None
    bias = sum(diffs) / n if n else None
    return {
        "gw": frozen.get("meta", {}).get("gw"),
        "graded_at": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "frozen_at": frozen.get("meta", {}).get("frozen_at"),
        "n": n,
        "mae": round(mae, 3) if mae is not None else None,
        "bias": round(bias, 3) if bias is not None else None,
        "mae_by_pos": {pos: round(sum(abs(d) for d in ds) / len(ds), 3)
                       for pos, ds in sorted(by_pos.items()) if ds},
    }


def main() -> int:
    if not FROZEN_DIR.exists():
        print("Ei jäädytettyjä kierroksia — ei gradattavaa.")
        return 0
    log = (json.loads(LOG_PATH.read_text(encoding="utf-8"))
           if LOG_PATH.exists() else {"meta": {
               "product": "GoalIQ per-GW xP accuracy log",
               "rules": ("Projection frozen before the deadline (immutable), "
                         "graded once the gameweek finishes. All frozen "
                         "players graded, including those who did not play. "
                         "Append-only."),
           }, "gameweeks": []})
    done = {g.get("gw") for g in log["gameweeks"]}
    pending = []
    for f in sorted(FROZEN_DIR.glob("gw*.json")):
        frozen = json.loads(f.read_text(encoding="utf-8"))
        gw = frozen.get("meta", {}).get("gw")
        if gw not in done:
            pending.append((gw, frozen))
    if not pending:
        print("Kaikki jäädytetyt kierrokset on jo gradattu.")
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
            r = requests.get(f"{FPL_BASE}/event/{gw}/live/", headers=FPL_HEADERS,
                             timeout=60)
            r.raise_for_status()
            live = r.json()
        except Exception as e:
            print(f"VIRHE: event/{gw}/live-haku epäonnistui: {e!r}")
            return 1
        actual = {int(el["id"]): int(el.get("stats", {}).get("total_points") or 0)
                  for el in live.get("elements") or []}
        row = grade_gw(frozen, actual)
        log["gameweeks"].append(row)
        graded += 1
        print(f"OK: GW{gw} gradattu — n={row['n']}, MAE {row['mae']}, "
              f"bias {row['bias']}, per pos {row['mae_by_pos']}.")
    if graded:
        LOG_PATH.write_text(json.dumps(log, ensure_ascii=False, indent=1) + "\n",
                            encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
