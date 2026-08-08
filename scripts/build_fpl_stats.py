"""FREE STATS ZONE -builderi (8.8.2026) — per-pelaaja kausitilastot → JSON.

Tuottaa `data/fpl_player_stats.json`:n jonka `/fpl/stats` renderöi. Kysyntä-
signaali: FFH:n Opta-osio katosi maksavalta käyttäjältä ja hän kysyi julkisesti
mistä muualta saa "filter tables for shots, shots in the box…". Iso osa noista
luvuista on FPL:n omassa APIssa, joka on Opta-lähtöinen (bootstrapissa on kenttä
`opta_code`) — eli jaettavissa ilmaiseksi ilman lisenssiä.

Lähde: `bootstrap-static/elements` (src/data/fpl_api.py:n levyvälimuisti).
Bootstrap kantaa **edellisen kauden kausitotaalit** siihen asti kunnes uusi
kausi alkaa, ja samaan aikaan kuluvan kauden hinnat/omistukset/erikoistilanne-
järjestyksen. Sama basis-konventio kuin fpl_player_leaders: rivi kertoo aina
MINKÄ kauden datasta se on (`meta.basis_label`), ei koskaan hiljaista sekoitusta.

RAJA (Villen päätös 8.8): raakaluvut ovat ilmaisia, **johdettu DefCon-tracker
ei**. Tämä tiedosto emittoi `dc`-kertymän (defensive_contribution = CBIT/CBIRT-
lukumäärä) mutta EI hit-rate-prosenttia, kynnysosumia eikä projisoituja DefCon-
pisteitä — ne ovat premium (`/api/fantasy/defcon-*`, src/models/fpl_leaders.py).

Fail-safe: sanity gate FAIL → JSONia EI kirjoiteta, exit 2 (vanha data jää
voimaan). EI auto-pushia — onnistunut ajo tulostaa git-komennot.

Ajo: python -m scripts.build_fpl_stats
"""
from __future__ import annotations

import datetime as _dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from src.data.fpl_api import fetch_bootstrap, season_key_from_bootstrap
from src.models.fpl_understat_match import match_all

STATS_PATH = config.DATA_DIR / "fpl_player_stats.json"

POS_NAME = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}

# Sarakejärjestys on osa julkista sopimusta (sivun JS indeksoi näillä).
# Lisää uusi sarake AINA loppuun — järjestyksen muutos rikkoisi vanhan sivun.
COLS = [
    "id", "name", "team", "pos", "price", "own", "status",
    "mins", "starts",
    "g", "xg", "threat",
    "a", "xa", "xgi", "creativity",
    "tkl", "cbi", "rec", "dc",
    "cs", "gc", "xgc", "saves",
    "pts", "ppg", "bps", "bonus", "ict", "yc", "rc",
    "pen", "cor", "fk",
    # Vaihe 2 (8.8): Understatin laukaustasolta. EI Optaa — oma xG-malli, ks.
    # meta.shots_source. Matsaamaton pelaaja saa None:n eika nollaa: nolla
    # olisi vaite ("ei laukauksia"), tyhja on totuus ("ei tietoa").
    "sh", "sot", "box", "head", "hvc", "npxg", "spxg",
    "kp", "xgchain", "xgbuildup",
]
SHOT_COLS = ["sh", "sot", "box", "head", "hvc", "npxg", "spxg",
             "kp", "xgchain", "xgbuildup"]
MIN_SHOT_COVERAGE = 0.97   # promptin hyvaksymiskynnys vaiheelle 2

# Sanity-rajat. Nämä ovat tarkoituksella väljiä: portin tehtävä on estää
# rikkinäisen datan julkaisu, ei toistaa mallin validointia.
MIN_PLAYERS = 200
MAX_MINS = 4200           # 38 GW × 90 min + tuplakierrokset
MAX_STARTS = 42
MAX_XG_PER_90 = 2.5       # kukaan ei tuota tätä kestävästi
MIN_MINS_FOR_RATE_CHECK = 450


def _f(value, default: float = 0.0) -> float:
    """FPL palauttaa osan luvuista merkkijonoina ("2.94") ja osan None:na."""
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _i(value, default: int = 0) -> int:
    return int(_f(value, default))


def season_label(key: str) -> str:
    """"2526" → "2025/26"."""
    return f"20{key[:2]}/{key[2:]}"


def load_shots() -> tuple[list[dict], dict]:
    """Understat-laukausaggregaatti (scripts/build_understat_shots.py).

    Puuttuva tiedosto EI kaada buildia: sivu rakentuu ilman laukaussarakkeita
    ja meta kertoo sen. Sama fail-safe-linja kuin muut lahteet."""
    path = config.DATA_DIR / "understat_player_shots_2526.json"
    if not path.exists():
        return [], {"available": False, "reason": "artefakti puuttuu"}
    blob = json.loads(path.read_text(encoding="utf-8"))
    return blob.get("players") or [], blob.get("meta") or {}


def build_rows(boot: dict, shots: list[dict]) -> tuple[list[list], dict]:
    teams = {t["id"]: t["short_name"] for t in boot["teams"]}
    report = match_all(boot["elements"], shots) if shots else None
    smap = report["map"] if report else {}
    rows: list[list] = []
    for e in boot["elements"]:
        pos = POS_NAME.get(e.get("element_type"))
        if pos is None:
            continue
        mins = _i(e.get("minutes"))
        if mins <= 0:
            # Ei pelattuja minuutteja basis-kaudella → ei riviä. Nolla olisi
            # väite ("pelasi eikä tehnyt mitään"), puuttuva rivi on totuus.
            continue
        rows.append([
            _i(e.get("id")),
            e.get("web_name") or "",
            teams.get(e.get("team"), ""),
            pos,
            round(_i(e.get("now_cost")) / 10.0, 1),
            round(_f(e.get("selected_by_percent")), 1),
            e.get("status") or "a",
            mins,
            _i(e.get("starts")),
            _i(e.get("goals_scored")),
            round(_f(e.get("expected_goals")), 2),
            round(_f(e.get("threat")), 1),
            _i(e.get("assists")),
            round(_f(e.get("expected_assists")), 2),
            round(_f(e.get("expected_goal_involvements")), 2),
            round(_f(e.get("creativity")), 1),
            _i(e.get("tackles")),
            _i(e.get("clearances_blocks_interceptions")),
            _i(e.get("recoveries")),
            _i(e.get("defensive_contribution")),
            _i(e.get("clean_sheets")),
            _i(e.get("goals_conceded")),
            round(_f(e.get("expected_goals_conceded")), 2),
            _i(e.get("saves")),
            _i(e.get("total_points")),
            round(_f(e.get("points_per_game")), 1),
            _i(e.get("bps")),
            _i(e.get("bonus")),
            round(_f(e.get("ict_index")), 1),
            _i(e.get("yellow_cards")),
            _i(e.get("red_cards")),
            _i(e.get("penalties_order"), 0),
            _i(e.get("corners_and_indirect_freekicks_order"), 0),
            _i(e.get("direct_freekicks_order"), 0),
        ])
        u = smap.get(str(e.get("id")))
        rows[-1].extend([
            u["sh"] if u else None,
            u["sot"] if u else None,
            u["box"] if u else None,
            u["head"] if u else None,
            u["hvc"] if u else None,
            u["npxg"] if u else None,
            u["spxg"] if u else None,
            u["kp"] if u else None,
            u["xgchain"] if u else None,
            u["xgbuildup"] if u else None,
        ])
    rows.sort(key=lambda r: -r[COLS.index("pts")])
    return rows, (report or {})


def build() -> dict:
    boot = fetch_bootstrap()
    key = season_key_from_bootstrap(boot)
    target = season_label(key)
    finished = sum(1 for ev in boot.get("events", []) if ev.get("finished"))
    # Ennen kohdekauden ensimmäistä pelattua kierrosta bootstrapin totaalit
    # ovat EDELLISEN kauden. Tämä ei ole arvaus vaan FPL:n käytös, ja se on
    # verifioitu 8.8.2026 (season_key 2627, 0 finished, Raya 3330 min = 25/26).
    is_prev = finished == 0
    prev_key = f"{int(key[:2]) - 1:02d}{int(key[2:]) - 1:02d}"
    basis = season_label(prev_key) if is_prev else target
    label = (f"Based on {basis} · updates as the new season plays"
             if is_prev else f"{basis} season to date")
    shots, shots_meta = load_shots()
    rows, report = build_rows(boot, shots)
    return {
        "meta": {
            "shots_available": bool(shots) and bool(report),
            "shots_source": shots_meta.get(
                "source", "Understat shot-level data (own xG model, NOT Opta)"),
            "shots_season": shots_meta.get("season"),
            "shots_box_definition": shots_meta.get("box_definition"),
            "shots_high_value_threshold": shots_meta.get(
                "high_value_threshold"),
            "shots_match_coverage": round(report.get("coverage", 0.0), 4)
            if report else 0.0,
            "shots_match_methods": report.get("how") if report else {},
            "shots_unmatched": report.get("misses") if report else [],
            "available": True,
            "generated_at": _dt.datetime.now().isoformat(timespec="seconds"),
            "basis_season": basis,
            "target_season": target,
            "is_prev_season_basis": is_prev,
            "basis_label": label,
            "finished_events": finished,
            "n_players": len(rows),
            "source": "FPL official API bootstrap (Opta-sourced xG/xA/xGI/xGC)",
            "scope_note": (
                "Season totals for the basis season plus current-season price, "
                "ownership and set-piece order. Raw counting stats only: the "
                "DefCon tracker (hit rate, thresholds, projected points) is a "
                "GoalIQ model output and is not part of this file."
            ),
            "cols": COLS,
        },
        "players": rows,
    }


def sanity(data: dict) -> list[str]:
    fails: list[str] = []
    rows = data.get("players") or []
    if len(rows) < MIN_PLAYERS:
        fails.append(f"vain {len(rows)} pelaajaa (min {MIN_PLAYERS})")
    idx = {c: i for i, c in enumerate(COLS)}
    if not data.get("meta", {}).get("basis_label"):
        fails.append("basis_label puuttuu (data-rajoitus on ensiluokkainen)")
    seen_ids = set()
    for r in rows:
        if len(r) != len(COLS):
            fails.append(f"rivin pituus {len(r)} != {len(COLS)} ({r[:2]})")
            break
        name = r[idx["name"]]
        if r[idx["id"]] in seen_ids:
            fails.append(f"duplikaatti-id {r[idx['id']]} ({name})")
            break
        seen_ids.add(r[idx["id"]])
        if not name or not r[idx["team"]]:
            fails.append(f"nimi tai joukkue puuttuu (id {r[idx['id']]})")
            break
        mins = r[idx["mins"]]
        if not 0 < mins <= MAX_MINS:
            fails.append(f"{name}: minuutit {mins} rajan ulkona")
            break
        if not 0 <= r[idx["starts"]] <= MAX_STARTS:
            fails.append(f"{name}: starts {r[idx['starts']]} rajan ulkona")
            break
        if any(isinstance(v, (int, float)) and v < 0
               for v in r[idx["mins"]:]):
            fails.append(f"{name}: negatiivinen arvo rivillä")
            break
        if mins >= MIN_MINS_FOR_RATE_CHECK:
            xg90 = r[idx["xg"]] / mins * 90
            if xg90 > MAX_XG_PER_90:
                fails.append(f"{name}: xG/90 {xg90:.2f} > {MAX_XG_PER_90}")
                break
        # xGI:n pitää olla xG+xA:n tuntumassa (FPL pyöristää itse, siksi 0.15)
        if abs(r[idx["xgi"]] - (r[idx["xg"]] + r[idx["xa"]])) > 0.15:
            fails.append(
                f"{name}: xGI {r[idx['xgi']]} != xG {r[idx['xg']]} + "
                f"xA {r[idx['xa']]}")
            break
        sh = r[idx["sh"]]
        if sh is not None:
            for col in ("sot", "box", "head"):
                if (r[idx[col]] or 0) > sh:
                    fails.append(f"{name}: {col} {r[idx[col]]} > laukaukset {sh}")
                    break
            if fails:
                break
    meta = data.get("meta", {})
    if meta.get("shots_available"):
        cov = meta.get("shots_match_coverage", 0.0)
        if cov < MIN_SHOT_COVERAGE:
            fails.append(
                f"FPL↔Understat-kattavuus {cov:.1%} < {MIN_SHOT_COVERAGE:.0%} "
                "— laukaussarakkeet eivät shippaa vajaalla matsayksella")
    return fails


def main(argv: list[str] | None = None) -> int:
    data = build()
    fails = sanity(data)
    if fails:
        print("SANITY FAIL — dataa EI kirjoiteta:")
        for f in fails:
            print(f"  - {f}")
        return 2
    STATS_PATH.write_text(json.dumps(data, ensure_ascii=False),
                          encoding="utf-8")
    m = data["meta"]
    kb = STATS_PATH.stat().st_size / 1024
    print("=" * 64)
    print("FPL PLAYER STATS BUILD OK")
    print("=" * 64)
    print(f"  players      : {m['n_players']}")
    print(f"  basis        : {m['basis_season']} (prev-basis: {m['is_prev_season_basis']})")
    print(f"  label        : {m['basis_label']}")
    print(f"  out          : {STATS_PATH} ({kb:.0f} kB)")
    print()
    print("  git add data/fpl_player_stats.json")
    print('  git commit -m "data(fpl): player stats refresh"')
    return 0


if __name__ == "__main__":
    sys.exit(main())
