"""xP-deadline-freeze (30.7, Villen GO): per-GW xP vs toteuma -putken osa 1.

Kun seuraavan GW:n deadline on alle FREEZE_WINDOW_H päässä, jäädytetään sen
kierroksen per-pelaaja-xP data/fpl_xp_frozen/gw{N}.json:iin. Gradaus (osa 2,
grade_fpl_xp_gw.py) vertaa jäädytettyä ennustetta toteumaan kun kierros on
ratkennut — ennuste on IMMUTABLE ennen kickoffia, sama periaate kuin
ottelulokissa ja Beat the modelissa.

Idempotentti: olemassa olevaa freezeä EI ylikirjoiteta (ennusteen vaihtaminen
jälkikäteen olisi tasan se vilppi jota koko putki torjuu).
Exit 0 myös kun ei jäädytettävää; tekninen virhe → 1.
"""
from __future__ import annotations

import datetime as _dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests

import config

XP_PATH = config.PROJECT_ROOT / "data" / "fpl_xp_projections.json"
FROZEN_DIR = config.PROJECT_ROOT / "data" / "fpl_xp_frozen"
FPL_BASE = "https://fantasy.premierleague.com/api"
FPL_HEADERS = {"User-Agent": "Mozilla/5.0 (GoalIQ freeze job)"}
FREEZE_WINDOW_H = 30   # päivittäinen cron ehtii aina väliin


def slim_rows(xp: dict, gw: int) -> list[dict]:
    """Puhdas ydin: projektiosta kierroksen {gw} slim-rivit."""
    rows = []
    for p in xp.get("players") or []:
        g = next((x for x in p.get("gameweeks") or [] if x.get("gw") == gw), None)
        if g is None:
            continue
        rows.append({"id": p["id"], "web_name": p.get("web_name"),
                     "team_short": p.get("team_short"), "pos": p.get("pos"),
                     "price": p.get("price"), "xmins": p.get("xmins"),
                     "xp": g.get("xp")})
    return rows


def main() -> int:
    try:
        r = requests.get(f"{FPL_BASE}/bootstrap-static/", headers=FPL_HEADERS,
                         timeout=30)
        r.raise_for_status()
        events = r.json().get("events") or []
    except Exception as e:
        print(f"VIRHE: bootstrap-haku epäonnistui: {e!r}")
        return 1
    now = _dt.datetime.now(_dt.timezone.utc)
    nxt = None
    for ev in events:
        if ev.get("finished"):
            continue
        dl = _dt.datetime.fromisoformat(
            str(ev.get("deadline_time", "")).replace("Z", "+00:00"))
        if dl > now and (dl - now) <= _dt.timedelta(hours=FREEZE_WINDOW_H):
            nxt = (int(ev["id"]), dl)
            break
    if nxt is None:
        print("Ei deadlinea freeze-ikkunassa — ei jäädytettävää.")
        return 0
    gw, dl = nxt
    out = FROZEN_DIR / f"gw{gw}.json"
    if out.exists():
        print(f"GW{gw} on jo jäädytetty — ei ylikirjoiteta (immutable).")
        return 0
    if not XP_PATH.exists():
        print("VIRHE: xP-projektiota ei ole.")
        return 1
    xp = json.loads(XP_PATH.read_text(encoding="utf-8"))
    rows = slim_rows(xp, gw)
    if len(rows) < 200:
        print(f"VIRHE: vain {len(rows)} riviä GW{gw}:lle — ei jäädytetä.")
        return 1
    FROZEN_DIR.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "meta": {"gw": gw, "deadline": dl.strftime("%Y-%m-%dT%H:%M:%SZ"),
                 "frozen_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                 "projection_generated_at": xp.get("meta", {}).get("generated_at"),
                 "n_players": len(rows)},
        "players": rows,
    }, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"OK: GW{gw} jäädytetty ({len(rows)} pelaajaa, deadline {dl}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
