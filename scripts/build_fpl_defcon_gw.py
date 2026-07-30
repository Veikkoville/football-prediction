"""Per-GW DefCon -matriisi (30.7.2026, Villen GO).

Kirjoittaa data/fpl_defcon_gw.json: nykykauden (26/27) DEF/MID/FWD-pelaajat +
KOKO 25/26-kauden per-kierros DefCon-rivit levyarkistosta. Mappaus element-
CODElla (pysyvä kausien yli) — id:t nollautuvat kausivaihdossa, sama oppi
kuin leaders-builderin kausivaihto-mergessä.

Endpoint /api/fantasy/defcon-gw lukee tiedoston — ei laskentaa pyynnössä
(Render 0.5 vCPU -budjetti, sama konventio kuin muut FPL-builderit).

REHELLISYYS ENSILUOKKAISENA:
  - basis = 2025/26 + pakollinen basis_label (sama kaava kuin leaders).
  - Meta kantaa MITATUN vastustajaefektin (28.7 mittaus, 7 382 ottelua,
    within-player-poikkeamat): korrelaatio +0.026, helpoin-vs-vaikein-ero
    0.16 toimintoa/ottelu tasolla 6.5. UI:n kuuluu sanoa suoraan: DefCon
    seuraa pelaajaa, ei fixtureä. Emme myy vastustajakontekstia signaalina
    jota oma mittauksemme ei löydä.
  - Vain pelatut ottelut (minutes > 0); pelaaja ilman yhtään riviä ei ole
    mukana (frontend: No data yet) — ei arvauksia.

Rivit kompaktoitu listoiksi [gw, opp, venue, min, dc] — 700+ pelaajaa × ~38
riviä objekteina olisi turhaan ~3x isompi payload.

Fail-safe: sanity gate FAIL → exit 2 → EI committia (sama konventio).
"""
from __future__ import annotations

import datetime as _dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from src.data.fpl_api import fetch_bootstrap
from src.models.fpl_leaders import DEFCON_THRESHOLD

OUT_PATH = config.DATA_DIR / "fpl_defcon_gw.json"
CACHE = Path(__file__).resolve().parent.parent / "data" / "raw" / "fpl"
ARCHIVE_BOOT = CACHE / "bootstrap_static_2526.archive.json"
SUMMARY_DIR = CACHE / "summary_2526"

POS_NAME = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}
BASIS_SEASON = "2025/26"
SANITY_MIN_PLAYERS = 300
SANITY_MAX_DC = 40        # kukaan ei tee >40 puolustustoimintoa ottelussa
SANITY_MAX_ROWS = 38


def _rows_by_code() -> dict[int, list[list]]:
    """25/26-arkisto: element-code → kompaktit per-GW-rivit [gw,opp,venue,min,dc]."""
    boot = json.loads(ARCHIVE_BOOT.read_text(encoding="utf-8"))
    if not boot["events"][0]["deadline_time"].startswith("2025-"):
        raise SystemExit("VIRHE: arkistobootstrap ei ole 25/26-kautta.")
    teams = {t["id"]: t["short_name"] for t in boot["teams"]}
    id_to_code = {e["id"]: e.get("code") for e in boot["elements"]}
    out: dict[int, list[list]] = {}
    for e in boot["elements"]:
        p = SUMMARY_DIR / f"element_{e['id']}.json"
        if not p.exists():
            continue
        history = json.loads(p.read_text(encoding="utf-8")).get("history", [])
        rows = []
        for r in sorted(history, key=lambda r: (r.get("round") or 0,
                                                r.get("kickoff_time") or "")):
            if (r.get("minutes") or 0) <= 0:
                continue
            cbit = ((r.get("clearances_blocks_interceptions") or 0)
                    + (r.get("tackles") or 0))
            cbirt = cbit + (r.get("recoveries") or 0)
            pos = POS_NAME.get(e["element_type"])
            dc = (r.get("defensive_contribution")
                  if r.get("defensive_contribution") is not None
                  else (cbit if pos == "DEF" else cbirt))
            rows.append([
                int(r.get("round") or 0),
                teams.get(r.get("opponent_team"), ""),
                "H" if r.get("was_home") else "A",
                int(r.get("minutes") or 0),
                int(dc),
            ])
        code = id_to_code.get(e["id"])
        if rows and code:
            out[code] = rows
    return out


def matrix_players(cur_elements: list[dict], cur_teams: dict[int, str],
                   rows_by_code: dict[int, list[list]]) -> list[dict]:
    """Puhdas ydin (pytest-testattava): nykykauden attribuutit + arkistorivit.

    Hinta/seura/pos/omistus tulevat KULUVAN kauden bootstrapista (26.7-oppi:
    historialliset statsit peritään, attribuutit eivät). GKP ei DefConia.
    """
    players = []
    for e in cur_elements:
        pos = POS_NAME.get(e["element_type"])
        if pos in (None, "GKP"):
            continue
        rows = rows_by_code.get(e.get("code")) or []
        if not rows:
            continue
        thr = DEFCON_THRESHOLD[pos]
        hits = sum(1 for r in rows if r[4] >= thr)
        players.append({
            "id": e["id"],
            "code": e.get("code"),
            "web_name": e["web_name"],
            "team_short": cur_teams.get(e["team"], ""),
            "pos": pos,
            "price": (e.get("now_cost") or 0) / 10.0,
            "owned_pct": float(e.get("selected_by_percent") or 0.0),
            "threshold": thr,
            "games": len(rows),
            "hits": hits,
            "hit_rate": round(hits / len(rows), 3),
            "dc_points": hits * 2,
            "basis": BASIS_SEASON,
            "per_gw": rows,
        })
    # Järjestys: eniten DefCon-pisteitä ensin (tiebreak hit_rate).
    players.sort(key=lambda p: (-p["dc_points"], -p["hit_rate"], p["web_name"]))
    return players


def build() -> dict:
    boot = fetch_bootstrap()
    cur_teams = {t["id"]: t["short_name"] for t in boot["teams"]}
    players = matrix_players(boot["elements"], cur_teams, _rows_by_code())
    return {
        "meta": {
            "available": True,
            "generated_at": _dt.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "basis_season": BASIS_SEASON,
            "basis_label": f"Based on {BASIS_SEASON} · updates as the new season plays",
            "row_format": ["gw", "opp", "venue", "minutes", "dc"],
            "thresholds": dict(DEFCON_THRESHOLD),
            # 28.7 mittaus (STATE: CC yö 5): within-player-korrelaatio ja
            # helpoin-vs-vaikein-vastustaja-ero. UI näyttää tämän suoraan.
            "opponent_effect": {
                "correlation": 0.026,
                "spread_actions_per_game": 0.16,
                "note": ("DefCon follows the player, not the fixture: opponent "
                         "shifts it by about 2% in 25/26 data (7,382 player-"
                         "matches). Bonus is the stat that moves with fixtures."),
            },
            "n_players": len(players),
        },
        "players": players,
    }


def sanity(data: dict) -> list[str]:
    fails = []
    ps = data["players"]
    if len(ps) < SANITY_MIN_PLAYERS:
        fails.append(f"pelaajia {len(ps)} < {SANITY_MIN_PLAYERS}")
    for p in ps:
        if len(p["per_gw"]) > SANITY_MAX_ROWS:
            fails.append(f"{p['web_name']}: {len(p['per_gw'])} rivia > 38")
            break
    mx = max((r[4] for p in ps for r in p["per_gw"]), default=0)
    if mx > SANITY_MAX_DC:
        fails.append(f"max dc {mx} > {SANITY_MAX_DC}")
    if not any(p["hits"] > 0 for p in ps):
        fails.append("kenellakaan ei yhtaan DefCon-hittia (data rikki?)")
    return fails


if __name__ == "__main__":
    data = build()
    fails = sanity(data)
    if fails:
        print("SANITY FAIL:")
        for f in fails:
            print(" -", f)
        raise SystemExit(2)
    OUT_PATH.write_text(json.dumps(data, ensure_ascii=False,
                                   separators=(",", ":")),
                        encoding="utf-8")
    kb = OUT_PATH.stat().st_size / 1024
    print(f"OK: {len(data['players'])} pelaajaa -> {OUT_PATH} ({kb:.0f} kB)")
