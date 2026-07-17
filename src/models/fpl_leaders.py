"""FPL player leaders — #124 xG leaders + #125 DefCon tracker (V1).

Nightly-builderi (scripts/build_fpl_player_leaders.py) cachettaa per-pelaaja
viimeisimmät pelatut ottelut (minutes > 0) FPL element-summarysta →
data/fpl_player_leaders.json. Tämä moduuli rankkaa cachesta rolling-windowilla
(3-10, default 5) — puhtaita funktioita, ei verkkoa → pytest-testattavissa.

DATA-RAJOITUKSET ENSILUOKKAISENA (Villen vaatimus 17.7, #80-linja):
  - basis_season kertoo MINKÄ kauden datasta rivit ovat. Ennen 26/27-kauden
    avautumista basis = 2025/26 → meta.basis_label pakotettu frontendiin
    ("Based on 2025/26 · updates as the new season plays").
  - Jokainen rivi kantaa TODELLISEN otoskoon (games ikkunassa) — ei koskaan
    thin-dataa täytenä lukuna ilman otoskokoa.
  - Pelaajat ilman yhtään pelattua ottelua basis-kaudella EIVÄT ole listalla
    (frontend näyttää "No data yet" -tilan tyhjälle haulle) — ei arvauksia.
  - Kun FPL avaa 26/27:n: builderi vaihtaa basis-kauden automaattisesti ja
    MIN_CURRENT_GAMES-sääntö (3) pitää 25/26-baselinen kunnes pelaajalla on
    ≥3 pelattua 26/27-ottelua (per-pelaaja basis-kenttä kertoo kumpaa dataa
    rivi on). Toteutus builderissa (prev-snapshot-merge).

DefCon (Defensive Contribution, FPL 25/26 mekaniikka):
  - DEF: 2 p kun CBIT (clearances+blocks+interceptions+tackles) >= 10
  - MID/FWD: 2 p kun CBIRT (CBIT + recoveries) >= 12
  - GKP: ei DefCon-pisteitä. Max 2 p / ottelu.
  Kynnykset verifioitu 17.7.2026: premierleague.com-säännöt (25/26 "What's
  new") + bootstrap game_config.scoring.defensive_contribution {DEF/MID/FWD:
  2, GKP: 0} + empiirinen tarkistus: element-summaryn defensive_contribution-
  kenttä == CBIT (DEF, 3950/3950 riviä) / CBIRT (MID+FWD, 6775/6775 riviä).
"""
from __future__ import annotations

import json

import config
from src.models.fpl_rate_team import RateTeamError

LEADERS_PATH = config.DATA_DIR / "fpl_player_leaders.json"

DEFCON_POINTS = 2
DEFCON_THRESHOLD = {"DEF": 10, "MID": 12, "FWD": 12}  # GKP: ei DefConia
MIN_CURRENT_GAMES = 3   # 26/27-rolling vasta kun ≥3 pelattua kauden ottelua
WINDOW_DEFAULT = 5
WINDOW_MIN, WINDOW_MAX = 3, 10


def load_leaders() -> dict:
    if not LEADERS_PATH.exists():
        raise RateTeamError(503, "Player leaders data is not built yet.")
    data = json.loads(LEADERS_PATH.read_text(encoding="utf-8"))
    if not data.get("meta", {}).get("available", False):
        raise RateTeamError(503, "Player leaders data is not available.")
    return data


def defcon_hit(pos: str, dc_count: int) -> bool:
    thr = DEFCON_THRESHOLD.get(pos)
    return thr is not None and dc_count >= thr


def _window_rows(player: dict, window: int) -> list[dict]:
    return (player.get("recent_games") or [])[-window:]


def _base_row(p: dict, games: int) -> dict:
    return {
        "id": p["id"],
        "web_name": p["web_name"],
        "team_short": p["team_short"],
        "pos": p["pos"],
        "price": p["price"],
        "owned_pct": p.get("owned_pct"),
        "games": games,                    # TODELLINEN otoskoko ikkunassa
        "basis": p.get("basis"),           # esim. "2025/26" — rehellinen lähde
    }


def rank_xg_leaders(data: dict, window: int = WINDOW_DEFAULT,
                    pos: str | None = None, top_n: int = 20) -> dict:
    """#124: top xG-tekijät rolling-windowilla. Rankkaus xG/game (tiebreak
    window-total). GKP jätetään pois oletuksena (xG-lista, ei torjuntalista)."""
    window = max(WINDOW_MIN, min(WINDOW_MAX, window))
    rows = []
    for p in data.get("players", []):
        if p["pos"] == "GKP" and pos != "GKP":
            continue
        if pos and p["pos"] != pos:
            continue
        recent = _window_rows(p, window)
        games = len(recent)
        if games == 0:
            continue
        xg = sum(g["xg"] for g in recent)
        xa = sum(g["xa"] for g in recent)
        xgi = sum(g["xgi"] for g in recent)
        row = _base_row(p, games)
        row.update({
            "xg_total": round(xg, 2),
            "xg_per_game": round(xg / games, 2),
            "xa_total": round(xa, 2),
            "xa_per_game": round(xa / games, 2),
            "xgi_per_game": round(xgi / games, 2),
        })
        rows.append(row)
    rows.sort(key=lambda r: (r["xg_per_game"], r["xg_total"]), reverse=True)
    return {
        "meta": _out_meta(data, window),
        "players": rows[:top_n],
    }


def rank_defcon_leaders(data: dict, window: int = WINDOW_DEFAULT,
                        pos: str | None = None, top_n: int = 20) -> dict:
    """#125: DefCon-leaderboard. Rankkaus hit-rate % (montako %:ssa pelatuista
    peleistä ylitti kynnyksen = luotettava DefCon-lähde), tiebreak actions/game.
    GKP ei voi saada DefCon-pisteitä → aina pois."""
    window = max(WINDOW_MIN, min(WINDOW_MAX, window))
    rows = []
    for p in data.get("players", []):
        if p["pos"] == "GKP":
            continue
        if pos and p["pos"] != pos:
            continue
        recent = _window_rows(p, window)
        games = len(recent)
        if games == 0:
            continue
        hits = sum(1 for g in recent if defcon_hit(p["pos"], g["dc"]))
        actions = sum(g["dc"] for g in recent)
        row = _base_row(p, games)
        row.update({
            "threshold": DEFCON_THRESHOLD[p["pos"]],
            "dc_per_game": round(actions / games, 1),
            "hit_rate_pct": round(100.0 * hits / games, 0),
            "defcon_points_window": hits * DEFCON_POINTS,
            "hits": hits,
        })
        rows.append(row)
    rows.sort(key=lambda r: (r["hit_rate_pct"], r["dc_per_game"]), reverse=True)
    return {
        "meta": {**_out_meta(data, window),
                 "thresholds": DEFCON_THRESHOLD,
                 "points_per_hit": DEFCON_POINTS,
                 "rule_note": ("2 pts when a defender reaches 10 CBIT "
                               "(clearances, blocks, interceptions, tackles) "
                               "or a midfielder/forward reaches 12 CBIRT "
                               "(CBIT + recoveries) in a match. Capped at 2 "
                               "pts per match.")},
        "players": rows[:top_n],
    }


def _out_meta(data: dict, window: int) -> dict:
    m = data.get("meta", {})
    return {
        "window": window,
        "basis_season": m.get("basis_season"),
        "is_prev_season_basis": m.get("is_prev_season_basis"),
        "basis_label": m.get("basis_label"),
        "generated_at": m.get("generated_at"),
        "note": ("GoalIQ analytics from official FPL match data. "
                 "Not betting advice."),
    }
