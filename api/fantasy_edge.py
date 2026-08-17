"""Edge-sprint API-kerros: chip-EV, plan-chains, league-proxy, H2H, edge + CSV.

Kaikki endpointit rakentuvat OLEMASSA OLEVAN infran paalle (LUKEE, ei muokkaa):
  - src.models.fpl_rate_team: build_context (committattu xP-projektio +
    FPL-bootstrap + pooli), resolve_squad (entry-tuonti), optimal_xi,
    _fetch_fpl (10 min TTL-cache + #52 stale-fallback)
  - src.models.fpl_planner: HIT_COST (-4), kandidaattirajaus
  - data/fpl_cs_fdr.json: koko kauden 380 fixturea (CS%/FDR/1X2) —
    joukkuetason approksimaatio xP-horisontin (6 GW) ulkopuolelle

Kontrakti-integraatio (cos-reports/edge-sprint/contract-data.md): pelaajarivit
VOIVAT saada owned_pct, p_start, p_cameo, p_bench, set_pieces{pens,corners,fk},
e_bonus — kaikki luetaan defensiivisesti payload.get(...)-tyylilla, puuttuva
kentta ei kaada mitaan.

MVP-kaavat ovat karkeita mutta dokumentoituja (basis/notes-kentat vastauksissa
sanovat rehellisesti mihin arvio perustuu). Premium-maskit: ks. api.premium.
"""
from __future__ import annotations

import csv
import io
import json
import math
import threading
import time
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request, Response

from src.models.fpl_planner import HIT_COST, TOP_CANDIDATES_PER_POS
from src.models.fpl_rate_team import (
    AVAILABILITY_GATE_NOTE, MAX_PER_CLUB, POS_NAME, SQUAD_QUOTA, XI_MAX,
    XI_MIN, BUDGET_TENTHS, RateTeamError, _fetch_fpl, _gw_xp, _resolve_gw,
    apply_availability_gate, build_context, clamp_gw_to_projections,
    get_bootstrap, get_entry_picks, optimal_xi, resolve_squad,
)
from src.models.fpl_xp import load_xp

from api.premium import (
    FREE_CHIP_WINDOWS, FREE_EDGE_CAPTAINS, FREE_EDGE_DIFFERENTIALS,
    FREE_EDGE_TEMPLATE_RISKS, FREE_PLAN_CHAINS, FREE_XP_TEASER_N,
    is_premium_request,
)

router = APIRouter()

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

DISCLAIMER = "GoalIQ model projections - for fun and planning, not betting advice."

# Kevyt tuloscache (Render = 1 prosessi). Avaimet sisaltavat projektion
# generated_at:n -> uusi projektio invalidoi automaattisesti.
_RESULT_CACHE: dict[tuple, tuple[float, object]] = {}
_RESULT_CACHE_LOCK = threading.Lock()
RESULT_CACHE_TTL_SEC = 600  # 10 min — sama TTL kuin FPL-fetch-cache


def _cache_get(key: tuple):
    with _RESULT_CACHE_LOCK:
        hit = _RESULT_CACHE.get(key)
    if hit and time.time() - hit[0] < RESULT_CACHE_TTL_SEC:
        return hit[1]
    return None


def _cache_put(key: tuple, value) -> None:
    with _RESULT_CACHE_LOCK:
        if len(_RESULT_CACHE) > 200:
            _RESULT_CACHE.clear()
        _RESULT_CACHE[key] = (time.time(), value)


def _parse_ids(raw: str) -> list[int]:
    """Pilkkuerotellut element-ID:t. Sama sopimus kuin main.py:n _parse_id_csv
    (PI-16b: plan-chains sai `players`-moodin, joten parseri tarvitaan tanne)."""
    try:
        return [int(x) for x in raw.split(",") if x.strip()]
    except ValueError:
        raise HTTPException(status_code=400,
                            detail="players must be comma-separated integers")


def _http(e: RateTeamError) -> HTTPException:
    """PI-16b (28.7): koneluettava `code` mukaan headeriin, kuten rate-teamissa.

    Ilman tata chip-EV, plan-chains, H2H ja edge naittavat esikauden 404:n
    samannakoisena kuin vaaran entry-ID:n, eika UI voi haarautua toimivaan
    draft-polkuun. `detail` sailyy merkkijonona -> julkaistut klientit
    ennallaan.
    """
    if getattr(e, "code", None):
        return HTTPException(status_code=e.status_code, detail=e.detail,
                             headers={"X-GoalIQ-Error-Code": e.code})
    return HTTPException(status_code=e.status_code, detail=e.detail)


# ---------------------------------------------------------------------------
# Yleiset apurit
# ---------------------------------------------------------------------------

def _covered_gws(pool: list[dict]) -> list[int]:
    return sorted({g.get("gw") for p in pool for g in (p.get("gameweeks") or [])
                   if g.get("gw") is not None})


def _remaining_xp(player: dict, gws: list[int]) -> float:
    return sum(_gw_xp(player, g) for g in gws)


def _optimal_xi_for(squad: list[dict], key) -> list[dict]:
    """optimal_xi:n geneerinen versio mielivaltaisella avainfunktiolla
    (esim. yhden GW:n xP). Sama muodostelmalogiikka kuin fpl_rate_team."""
    by_pos: dict[int, list[dict]] = {1: [], 2: [], 3: [], 4: []}
    for p in squad:
        by_pos[p["element_type"]].append(p)
    for lst in by_pos.values():
        lst.sort(key=key, reverse=True)
    best: tuple[float, list[dict]] | None = None
    for n_def in range(XI_MIN[2], XI_MAX[2] + 1):
        for n_mid in range(XI_MIN[3], XI_MAX[3] + 1):
            n_fwd = 11 - 1 - n_def - n_mid
            if not XI_MIN[4] <= n_fwd <= XI_MAX[4]:
                continue
            counts = {1: 1, 2: n_def, 3: n_mid, 4: n_fwd}
            if any(len(by_pos[t]) < n for t, n in counts.items()):
                continue
            xi = [p for t, n in counts.items() for p in by_pos[t][:n]]
            total = sum(key(p) for p in xi)
            if best is None or total > best[0]:
                best = (total, xi)
    if best is None:
        raise RateTeamError(400, "Squad cannot form a legal XI.")
    return best[1]


def _greedy_budget_xi(pool: list[dict], key) -> list[dict]:
    """Paras laillinen budjetti-XI annetulla avainfunktiolla — sama
    dokumentoitu ahne heuristiikka kuin fpl_rate_team.optimal_budget_team_xp
    (penkkireservi + kiintio-/klubi-/budjettiturvaus), mutta palauttaa XI:n
    ja tukee mielivaltaista scorea (GW-xP, jaljella oleva horisontti)."""
    by_pos: dict[int, list[dict]] = {1: [], 2: [], 3: [], 4: []}
    for p in pool:
        by_pos[p["element_type"]].append(p)
    if any(len(by_pos[t]) < n for t, n in SQUAD_QUOTA.items()):
        return []
    cheapest_gk = min(p["price"] for p in by_pos[1])
    outfield_prices = sorted(p["price"] for t in (2, 3, 4) for p in by_pos[t])
    bench_reserve = cheapest_gk + sum(outfield_prices[:3])
    xi_budget = BUDGET_TENTHS - bench_reserve
    min_price = min(p["price"] for p in pool)

    ranked = sorted(pool, key=key, reverse=True)
    xi: list[dict] = []
    counts = {1: 0, 2: 0, 3: 0, 4: 0}
    clubs: dict[int, int] = {}
    cost = 0
    for p in ranked:
        if len(xi) == 11:
            break
        t = p["element_type"]
        if counts[t] >= XI_MAX[t]:
            continue
        if clubs.get(p["club"], 0) >= MAX_PER_CLUB:
            continue
        need_min = sum(max(0, XI_MIN[q] - counts[q] - (1 if q == t else 0))
                       for q in XI_MIN)
        slots_left = 11 - len(xi) - 1
        if need_min > slots_left:
            continue
        if cost + p["price"] + slots_left * min_price > xi_budget:
            continue
        xi.append(p)
        counts[t] += 1
        clubs[p["club"]] = clubs.get(p["club"], 0) + 1
        cost += p["price"]
    return xi if len(xi) == 11 else []


def _squad_from_entry_or_model(pool, pool_by_id, bootstrap, entry, gw=None):
    """(squad-list, picks_gw, mode). entry -> resolve_squad; ilman entrya ->
    mallin oma runko (greedy budjetti-XI + halvin laillinen penkki)."""
    if entry is not None:
        squad_ids, _cap, _bank, picks_gw = resolve_squad(
            bootstrap, entry, gw, None, None, None)
        squad = [pool_by_id[i] for i in squad_ids if i in pool_by_id]
        if len(squad) < 11:
            raise RateTeamError(
                422, "Too few of the squad's players have xP projections.")
        return squad, picks_gw, "entry"
    xi = _greedy_budget_xi(pool, key=lambda p: p["xp_horizon_total"])
    if not xi:
        raise RateTeamError(503, "Cannot build a model squad from the pool.")
    squad = list(xi)
    counts: dict[int, int] = {1: 0, 2: 0, 3: 0, 4: 0}
    clubs: dict[int, int] = {}
    ids = {p["id"] for p in squad}
    for p in squad:
        counts[p["element_type"]] += 1
        clubs[p["club"]] = clubs.get(p["club"], 0) + 1
    for t in (1, 2, 3, 4):
        need = SQUAD_QUOTA[t] - counts[t]
        if need <= 0:
            continue
        cheap = sorted((p for p in pool if p["element_type"] == t
                        and p["id"] not in ids), key=lambda p: p["price"])
        for p in cheap:
            if need == 0:
                break
            if clubs.get(p["club"], 0) >= MAX_PER_CLUB:
                continue
            squad.append(p)
            ids.add(p["id"])
            clubs[p["club"]] = clubs.get(p["club"], 0) + 1
            need -= 1
    return squad, _resolve_gw(bootstrap, gw), "model_xi"


def _mini(p: dict) -> dict:
    return {"id": p["id"], "web_name": p["web_name"],
            "team_short": p["team_short"],
            "pos": POS_NAME[p["element_type"]]}


# ---------------------------------------------------------------------------
# data/fpl_cs_fdr.json — koko kauden joukkuetason approksimaatio
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _load_cs_fdr() -> dict:
    path = _PROJECT_ROOT / "data" / "fpl_cs_fdr.json"
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"fixtures": []}


def _gw_quality_index() -> dict[int, float]:
    """GW -> laatuindeksi (1.0 = kauden keskitaso). Per fixture kummallekin
    joukkueelle score = P(voitto) + 0.5 * CS%. GW:n laatu = 6 parhaan
    joukkuescoren keskiarvo (DGW: saman joukkueen kaksi fixturea summautuvat
    -> indeksi nousee luonnostaan). Normalisoitu kauden yli. Karkea,
    dokumentoitu approksimaatio chip-EV:n hantaosalle."""
    fixtures = _load_cs_fdr().get("fixtures") or []
    per_gw_team: dict[int, dict[str, float]] = {}
    for f in fixtures:
        gw = f.get("gameweek")
        if gw is None:
            continue
        t = per_gw_team.setdefault(int(gw), {})
        h, a = f.get("home"), f.get("away")
        if h:
            t[h] = t.get(h, 0.0) + float(f.get("p_home_win") or 0.0) \
                + 0.5 * float(f.get("cs_home_pct") or 0.0) / 100.0
        if a:
            t[a] = t.get(a, 0.0) + float(f.get("p_away_win") or 0.0) \
                + 0.5 * float(f.get("cs_away_pct") or 0.0) / 100.0
    raw: dict[int, float] = {}
    for gw, teams in per_gw_team.items():
        top = sorted(teams.values(), reverse=True)[:6]
        raw[gw] = sum(top) / len(top) if top else 0.0
    if not raw:
        return {}
    season_avg = sum(raw.values()) / len(raw)
    if season_avg <= 0:
        return {gw: 1.0 for gw in raw}
    return {gw: max(0.6, min(1.8, v / season_avg)) for gw, v in raw.items()}


# ---------------------------------------------------------------------------
# GET /api/fantasy/xp.csv — xP-projektiot CSV:na (premium-arvoinen)
# ---------------------------------------------------------------------------

_CSV_BASE_COLUMNS = [
    "id", "web_name", "full_name", "team", "team_short", "pos", "price",
    "owned_pct", "xmins", "predicted_starts", "minutes_confidence",
    "data_basis", "p_start", "p_cameo", "p_bench", "e_bonus",
    "set_pieces_pens", "set_pieces_corners", "set_pieces_fk",
    "xp_per_gw", "xp_per_90", "xp_horizon_total",
]


def _csv_cell(v, dec_comma: bool):
    """Desimaalierotin EU-muodossa. MIKSI (Villen bugiloyto 26.7): pisteelliset
    desimaalit (1.10, 2.11) tulkitaan fi/eu-locale-Excelissa PAIVAMAARIKSI,
    koska piste on siella paivamaaraerotin -> liian kapea paivamaarasolu
    renderoityy '####'. Muut desimaalit paatyvat tekstiksi, jolloin niilla ei
    voi laskea. EU-muodossa desimaali on pilkku ja erotin ';', jolloin Excel
    lukee ne oikeina lukuina."""
    if dec_comma and isinstance(v, float):
        return repr(v).replace(".", ",")
    return v


@router.get("/api/fantasy/xp.csv")
def fantasy_xp_csv(
    request: Request,
    response: Response,
    sep: str = Query(default=",", pattern="^[,;]$",
                     description="Kenttaerotin. ';' = eurooppalainen Excel "
                                 "(desimaalit pilkulla)."),
):
    """xP-projektiot CSV:na (Excel/Sheets-export). Sarakkeet: perustiedot +
    kontraktin defensiiviset kentat (owned_pct, p_start/p_cameo/p_bench,
    e_bonus, set_pieces_*; tyhja jos dataa ei viela ole) + xp_gw{N} per
    katettu GW. PREMIUM_ENFORCE=on + free -> top-10 rivia (teaser).

    ?sep=; -> eurooppalainen muoto (';' erottimena, ',' desimaalina). Oletus
    ',' pysyy UK/US-Excelille, Sheetsille ja pandasille."""
    data = load_xp()
    if not data.get("meta", {}).get("available") or not data.get("players"):
        raise HTTPException(status_code=503,
                            detail="xP projections are not available yet.")
    premium = is_premium_request(request)
    dec_comma = (sep == ";")
    cache_key = ("xp_csv", data["meta"].get("generated_at"), premium, sep)
    cached = _cache_get(cache_key)
    if cached is None:
        try:
            boot = {e["id"]: e for e in
                    (get_bootstrap().get("elements") or [])}
        except Exception:
            boot = {}  # hinta/EO jaavat tyhjiksi — CSV palautuu silti
        players = sorted(data["players"],
                         key=lambda p: float(p.get("xp_horizon_total") or 0.0),
                         reverse=True)
        if not premium:
            players = players[:FREE_XP_TEASER_N]
        gws = sorted({g.get("gw") for p in players
                      for g in (p.get("gameweeks") or [])})
        buf = io.StringIO()
        w = csv.writer(buf, delimiter=sep, lineterminator="\n")
        w.writerow(_CSV_BASE_COLUMNS + [f"xp_gw{g}" for g in gws])
        for p in players:
            b = boot.get(p.get("id")) or {}
            sp = p.get("set_pieces") or {}
            gw_xp = {g.get("gw"): g.get("xp")
                     for g in (p.get("gameweeks") or [])}
            price = b.get("now_cost")
            w.writerow([_csv_cell(v, dec_comma) for v in ([
                p.get("id"), p.get("web_name"), p.get("full_name"),
                p.get("team"), p.get("team_short"), p.get("pos"),
                (price / 10.0 if isinstance(price, (int, float)) else ""),
                p.get("owned_pct", b.get("selected_by_percent", "")),
                p.get("xmins"), p.get("predicted_starts"),
                p.get("minutes_confidence"), p.get("data_basis"),
                p.get("p_start", ""), p.get("p_cameo", ""),
                p.get("p_bench", ""), p.get("e_bonus", ""),
                sp.get("pens", ""), sp.get("corners", ""), sp.get("fk", ""),
                # 5.8: vauhti sarakkeena minuuttien rinnalle. Tyhja solu
                # (None) = alle minuuttikynnyksen; 0 olisi eri vaite.
                p.get("xp_per_gw"),
                ("" if p.get("xp_per_90") is None else p.get("xp_per_90")),
                p.get("xp_horizon_total"),
            ] + [gw_xp.get(g, "") for g in gws])])
        # Excel-yhteensopivuus (Villen bugilöytö 25.7): UTF-8 BOM (aksentilliset
        # nimet, esim. Kadıoğlu) + "sep=,"-vihjerivi, jota ilman fi/eu-locale-
        # Excel (listaerotin ";") kaataa kaiken yhteen sarakkeeseen. Sheets ja
        # pandas sietavat vihjerivin (pandas: skiprows=1).
        cached = f"﻿sep={sep}\n" + buf.getvalue()
        _cache_put(cache_key, cached)
    season = str(data["meta"].get("season") or "").replace("/", "-")
    response.headers["Cache-Control"] = "no-store"
    return Response(
        content=cached, media_type="text/csv; charset=utf-8",
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition":
                f'attachment; filename="goaliq_xp_{season or "season"}.csv"',
        })


# ---------------------------------------------------------------------------
# GET /api/fantasy/chip-ev — chip-ajoituksen EV-ikkunat
# ---------------------------------------------------------------------------

@router.get("/api/fantasy/chip-ev",
            description="Expected value of each chip for every remaining gameweek. The response states which basis each number rests on.")
def fantasy_chip_ev(
    request: Request, response: Response,
    entry: int | None = Query(default=None,
                              description="Julkinen FPL entry-ID (valinnainen; "
                                          "ilman -> mallin oma runko)"),
):
    """Chip-ajoitus-EV per jaljella oleva GW. basis kertoo rehellisesti
    arvioperustan: xP-horisontin (6 GW) sisalla pelaajatason xP, sen yli
    joukkuetason approksimaatio data/fpl_cs_fdr.json:sta (kauden 380 fixturen
    1X2 + CS% -> GW-laatuindeksi joka skaalaa horisontin keski-EV:ta).

    MVP-kaavat (karkeita, ei tarkkuusvaitteita — dokumentoitu vastauksen
    notes-kentassa):
      tc_ev = XI:n paras GW-xP (yksi lisakerroin kapteenille)
      bb_ev = penkin 4 pelaajan GW-xP-summa
      fh_ev = paras budjetti-XI talle GW:lle - oman rungon XI samalle GW:lle
      wc_ev = paras budjetti-XI jaljella olevalle horisontille - oman rungon
              per-GW-optimi-XI:iden summa samalle ikkunalle
    """
    response.headers["Cache-Control"] = "no-store"
    premium = is_premium_request(request)
    try:
        xp_data, bootstrap, pool, pool_by_id = build_context()
        cache_key = ("chip_ev", entry, xp_data["meta"].get("generated_at"))
        payload = _cache_get(cache_key)
        if payload is None:
            squad, _picks_gw, mode = _squad_from_entry_or_model(
                pool, pool_by_id, bootstrap, entry)
            covered = _covered_gws(pool)
            windows = []
            per_chip: dict[str, list[float]] = {
                "wc": [], "bb": [], "tc": [], "fh": []}
            for g in covered:
                gws_left = [x for x in covered if x >= g]
                xi_g = _optimal_xi_for(squad, key=lambda p: _gw_xp(p, g))
                xi_ids = {p["id"] for p in xi_g}
                xi_total = sum(_gw_xp(p, g) for p in xi_g)
                bench = [p for p in squad if p["id"] not in xi_ids]
                bb = sum(_gw_xp(p, g) for p in bench)
                tc = max((_gw_xp(p, g) for p in xi_g), default=0.0)
                fh_xi = _greedy_budget_xi(pool, key=lambda p: _gw_xp(p, g))
                fh = max(0.0, sum(_gw_xp(p, g) for p in fh_xi) - xi_total)
                wc_xi = _greedy_budget_xi(
                    pool, key=lambda p: _remaining_xp(p, gws_left))
                wc_total = sum(_remaining_xp(p, gws_left) for p in wc_xi)
                base_total = sum(
                    sum(_gw_xp(p, x) for p in
                        _optimal_xi_for(squad, key=lambda q: _gw_xp(q, x)))
                    for x in gws_left)
                wc = max(0.0, wc_total - base_total)
                row = {"gw": g, "wc_ev": round(wc, 2), "bb_ev": round(bb, 2),
                       "tc_ev": round(tc, 2), "fh_ev": round(fh, 2),
                       "basis": "player_xp"}
                windows.append(row)
                per_chip["wc"].append(wc)
                per_chip["bb"].append(bb)
                per_chip["tc"].append(tc)
                per_chip["fh"].append(fh)

            # Horisontin ulkopuoliset GW:t: joukkuetason skaalaus.
            quality = _gw_quality_index()
            future = sorted(g for g in quality if covered
                            and g > max(covered))
            base = {k: (sum(v) / len(v) if v else 0.0)
                    for k, v in per_chip.items()}
            for g in future:
                q = quality.get(g, 1.0)
                windows.append({
                    "gw": g,
                    "wc_ev": round(base["wc"] * q, 2),
                    "bb_ev": round(base["bb"] * q, 2),
                    "tc_ev": round(base["tc"] * q, 2),
                    "fh_ev": round(base["fh"] * q, 2),
                    "basis": "team_approx_cs_fdr",
                })

            best = {}
            for chip in ("wc", "bb", "tc", "fh"):
                if windows:
                    top = max(windows, key=lambda r: r[f"{chip}_ev"])
                    best[chip] = {"gw": top["gw"], "ev": top[f"{chip}_ev"],
                                  "basis": top["basis"]}
            payload = {
                "meta": {
                    "entry": entry, "mode": mode,
                    "horizon_gws": covered,
                    "generated_at": xp_data["meta"].get("generated_at"),
                    "notes": [
                        "Rough MVP estimates - EV in expected FPL points, "
                        "not a guarantee.",
                        "basis=player_xp: player-level xP inside the "
                        "projection horizon.",
                        "basis=team_approx_cs_fdr: horizon average scaled by "
                        "a team-level gameweek quality index from the full-"
                        "season CS%/1X2 file (double gameweeks raise it).",
                        "Free transfers and squad churn between now and the "
                        "window are ignored.",
                    ],
                    "disclaimer": DISCLAIMER,
                },
                "windows": windows,
                "best": best,
            }
            _cache_put(cache_key, payload)
    except RateTeamError as e:
        raise _http(e)
    if not premium:
        payload = dict(payload)
        payload["meta"] = {**payload["meta"], "masked": True,
                           "mask": f"first {FREE_CHIP_WINDOWS} windows "
                                   "(free preview)"}
        payload["windows"] = payload["windows"][:FREE_CHIP_WINDOWS]
        payload["best"] = {}
    return payload


# ---------------------------------------------------------------------------
# GET /api/fantasy/plan-chains — beam-search "solver-light"
# ---------------------------------------------------------------------------

BEAM_WIDTH = 8
CHAIN_SINGLES_PER_STEP = 4     # montako yhden siirron kandidaattia per tila
CHAIN_DOUBLES_PER_STEP = 2     # montako 2-siirron ketjua per tila
CHAIN_TIME_BUDGET_SEC = 6.0    # timeout-suoja (Render 0.5 vCPU)
CHAIN_FT_ASSUMED = 1           # FPL-API ei kerro vapaita siirtoja -> oletus


def _top_transfers(squad, pool, bank_tenths, gws_left, k):
    """Top-k yhden pelaajan siirtoa jaljella olevalle horisontille — sama
    kandidaattirajaus kuin fpl_planner._best_transfer, mutta lista."""
    squad_ids = {p["id"] for p in squad}
    clubs: dict[int, int] = {}
    for p in squad:
        clubs[p["club"]] = clubs.get(p["club"], 0) + 1
    by_pos: dict[int, list[dict]] = {1: [], 2: [], 3: [], 4: []}
    for p in pool:
        if p["id"] not in squad_ids:
            by_pos[p["element_type"]].append(p)
    for t in by_pos:
        by_pos[t].sort(key=lambda p: _remaining_xp(p, gws_left), reverse=True)
        by_pos[t] = by_pos[t][:TOP_CANDIDATES_PER_POS]
    cands = []
    for out_p in squad:
        budget = bank_tenths + out_p["price"]
        out_xp = _remaining_xp(out_p, gws_left)
        for in_p in by_pos[out_p["element_type"]]:
            if in_p["price"] > budget:
                continue
            after = clubs.get(in_p["club"], 0) + 1
            if in_p["club"] != out_p["club"] and after > MAX_PER_CLUB:
                continue
            gain = _remaining_xp(in_p, gws_left) - out_xp
            if gain <= 0:
                continue
            cands.append({"out": out_p, "in": in_p, "gain": gain})
    cands.sort(key=lambda c: c["gain"], reverse=True)
    return cands[:k]


def _apply_move(squad, bank, mv):
    squad2 = [p for p in squad if p["id"] != mv["out"]["id"]] + [mv["in"]]
    return squad2, bank + mv["out"]["price"] - mv["in"]["price"]


def _gw_score_with_captain(squad, g):
    xi = _optimal_xi_for(squad, key=lambda p: _gw_xp(p, g))
    cap = max(xi, key=lambda p: _gw_xp(p, g))
    return sum(_gw_xp(p, g) for p in xi) + _gw_xp(cap, g), xi, cap


@router.get("/api/fantasy/plan-chains")
def fantasy_plan_chains(
    request: Request, response: Response,
    entry: int | None = Query(default=None,
                              description="Julkinen FPL entry-ID"),
    players: str | None = Query(
        default=None,
        description="Esikausifallback: 15 FPL element-ID:ta pilkuilla"),
    horizon: int = Query(default=3, ge=2, le=6),
):
    """Solver-light: beam-search 0-2 siirtoa per GW olemassa olevalla xP:lla
    + hit-kustannus (sama HIT_COST -4 kuin transfer-suggestions). Palauttaa
    top-3 suunnitelmaa {moves per GW, net_ev vs hold, hits_taken, rationale}.
    Beam width 8, kandidaatit rajattu, aikabudjetti ~6 s (timeout-suoja:
    degradaatio merkitaan metaan). ft-oletus 1 (FPL-API ei kerro FT-saldoa).

    PI-16b (28.7): `players` lisatty samalla kaavalla kuin rate-team/plan/
    captain. Ilman sita tama endpoint palautti 404:n KAIKILLE koko esikauden,
    koska FPL julkaisee kokoonpanot vasta GW1-deadlinen jalkeen."""
    response.headers["Cache-Control"] = "no-store"
    premium = is_premium_request(request)
    player_ids = _parse_ids(players) if players else None
    if not player_ids and entry is None:
        raise HTTPException(status_code=400,
                            detail="Provide either entry or players.")
    try:
        xp_data, bootstrap, pool, pool_by_id = build_context()
        cache_key = ("plan_chains", entry,
                     tuple(player_ids) if player_ids else None, horizon,
                     xp_data["meta"].get("generated_at"))
        payload = _cache_get(cache_key)
        if payload is None:
            squad_ids, _cap, bank_tenths, picks_gw = resolve_squad(
                bootstrap, entry, None, player_ids, None, None)
            start_gw = clamp_gw_to_projections(picks_gw, pool, xp_data)
            covered = _covered_gws(pool)
            gws = [g for g in covered if g >= start_gw][:horizon]
            if not gws:
                raise RateTeamError(503, "No projected gameweeks in range.")
            squad = [pool_by_id[i] for i in squad_ids if i in pool_by_id]
            if len(squad) < 11:
                raise RateTeamError(
                    422, "Too few of the squad's players have xP projections.")

            t0 = time.monotonic()
            timed_out = False
            # Hold-baseline: ei siirtoja, per-GW-optimi-XI + kapteeni.
            baseline = 0.0
            for g in gws:
                s, _xi, _c = _gw_score_with_captain(squad, g)
                baseline += s

            # state: (squad, bank, fts, hits, cum_score, gw_rows, sig)
            beam = [{"squad": squad, "bank": bank_tenths,
                     "fts": CHAIN_FT_ASSUMED, "hits": 0.0, "score": 0.0,
                     "rows": [], "sig": ()}]
            for idx, g in enumerate(gws):
                gws_left = gws[idx:]
                rest = gws[idx + 1:]
                nxt = []
                for st in beam:
                    move_sets = [[]]
                    if not timed_out:
                        singles = _top_transfers(
                            st["squad"], pool, st["bank"], gws_left,
                            CHAIN_SINGLES_PER_STEP)
                        move_sets += [[mv] for mv in singles]
                        for mv in singles[:CHAIN_DOUBLES_PER_STEP]:
                            sq2, bk2 = _apply_move(st["squad"], st["bank"], mv)
                            second = _top_transfers(sq2, pool, bk2, gws_left, 1)
                            if second:
                                move_sets.append([mv, second[0]])
                    for moves in move_sets:
                        sq, bk = st["squad"], st["bank"]
                        fts, hits_gw = st["fts"], 0.0
                        mrows = []
                        for mv in moves:
                            sq, bk = _apply_move(sq, bk, mv)
                            if fts > 0:
                                fts -= 1
                                hit = 0.0
                            else:
                                hit = HIT_COST
                                hits_gw += HIT_COST
                            mrows.append({
                                "out": _mini(mv["out"]), "in": _mini(mv["in"]),
                                "gain_xp_remaining": round(mv["gain"], 2),
                                "hit": hit,
                            })
                        gw_pts, _xi, cap = _gw_score_with_captain(sq, g)
                        cum = st["score"] + gw_pts - hits_gw
                        row = {"gw": g, "moves": mrows,
                               "roll_transfer": not mrows,
                               "captain": {"id": cap["id"],
                                           "web_name": cap["web_name"],
                                           "gw_xp": round(_gw_xp(cap, g), 2)},
                               "gw_xp": round(gw_pts, 2),
                               "free_transfers_left": fts,
                               "bank": round(bk / 10.0, 1)}
                        nxt.append({
                            "squad": sq, "bank": bk,
                            "fts": min(5, fts + 1),
                            "hits": st["hits"] + hits_gw,
                            "score": cum,
                            "rows": st["rows"] + [row],
                            "sig": st["sig"] + tuple(
                                (mv["out"]["id"], mv["in"]["id"])
                                for mv in moves),
                        })
                    if time.monotonic() - t0 > CHAIN_TIME_BUDGET_SEC:
                        timed_out = True
                # Dedup (runko+fts) + karsinta beam-leveyteen: cum + potentiaali
                dedup: dict[tuple, dict] = {}
                for st in nxt:
                    k = (frozenset(p["id"] for p in st["squad"]), st["fts"])
                    if k not in dedup or st["score"] > dedup[k]["score"]:
                        dedup[k] = st
                pruned = list(dedup.values())
                pruned.sort(
                    key=lambda st: st["score"] + (11.0 / 15.0) * sum(
                        _remaining_xp(p, rest) for p in st["squad"]),
                    reverse=True)
                beam = pruned[:BEAM_WIDTH]

            beam.sort(key=lambda st: st["score"], reverse=True)
            plans = []
            seen_sigs = set()
            for st in beam:
                # Dedup jarjestysriippumattomasti: sama siirtojoukko eri
                # GW-jarjestyksessa on kayttajalle sama suunnitelma.
                sig = frozenset(st["sig"])
                if sig in seen_sigs:
                    continue
                seen_sigs.add(sig)
                n_moves = sum(len(r["moves"]) for r in st["rows"])
                net = round(st["score"] - baseline, 2)
                hits_n = int(st["hits"] / HIT_COST) if HIT_COST else 0
                if n_moves == 0:
                    rationale = ("Hold: rolling transfers beats every chain "
                                 f"searched over {len(gws)} GWs.")
                else:
                    first = next(r for r in st["rows"] if r["moves"])
                    mv0 = first["moves"][0]
                    hit_note = (f", {hits_n} hit{'s' if hits_n != 1 else ''}"
                                if hits_n else ", no hits")
                    rationale = (
                        f"{n_moves} move{'s' if n_moves != 1 else ''} over "
                        f"{len(gws)} GWs starting GW{first['gw']} "
                        f"({mv0['out']['web_name']} -> "
                        f"{mv0['in']['web_name']}): {net:+.1f} xP net vs "
                        f"holding{hit_note}.")
                plans.append({"total_xp": round(st["score"], 2),
                              "net_ev_vs_hold": net,
                              "hits_taken": hits_n,
                              "gws": st["rows"],
                              "rationale": rationale})
                if len(plans) == 3:
                    break

            payload = {
                "meta": {
                    "entry": entry, "start_gw": gws[0], "horizon": len(gws),
                    "ft_assumed": CHAIN_FT_ASSUMED,
                    "beam_width": BEAM_WIDTH,
                    "generated_at": xp_data["meta"].get("generated_at"),
                    "timeout_degraded": timed_out,
                    "heuristic": ("beam search, 0-2 transfers per GW, hit -4, "
                                  "remaining-horizon xP - not a global "
                                  "optimum"),
                    "note": DISCLAIMER,
                },
                "baseline_xp_no_transfers": round(baseline, 2),
                "plans": plans,
            }
            _cache_put(cache_key, payload)
    except RateTeamError as e:
        raise _http(e)
    if not premium:
        payload = dict(payload)
        payload["meta"] = {**payload["meta"], "masked": True,
                           "mask": f"top {FREE_PLAN_CHAINS} of "
                                   f"{len(payload['plans'])} plans "
                                   "(free preview)"}
        payload["plans"] = payload["plans"][:FREE_PLAN_CHAINS]
    return payload


# ---------------------------------------------------------------------------
# GET /api/fantasy/league/{league_id} — classic-liigan standings-proxy
# ---------------------------------------------------------------------------

@router.get("/api/fantasy/league/{league_id}",
            description="Proxy for FPL classic league standings, first page only. Public data, no auth.")
def fantasy_league(league_id: int, response: Response):
    """FPL leagues-classic standings -proxy (vain julkista dataa, max
    ensimmainen sivu, 10 min TTL _fetch_fpl-cachen kautta). Ei authia —
    sama julkisuustaso kuin FPL:n oma API."""
    response.headers["Cache-Control"] = "no-store"
    try:
        data = _fetch_fpl(
            f"/leagues-classic/{league_id}/standings/?page_standings=1")
    except RateTeamError as e:
        if e.status_code == 404:
            raise HTTPException(
                status_code=404,
                detail=f"FPL classic league {league_id} was not found "
                       "(check the ID; only public classic leagues work).")
        raise _http(e)
    league = data.get("league") or {}
    standings = data.get("standings") or {}
    return {
        "meta": {"league_id": league_id, "page": 1,
                 "cache_ttl_sec": 600,
                 "source": "FPL public leagues-classic API"},
        "league": {"id": league.get("id"), "name": league.get("name"),
                   "created": league.get("created")},
        "standings": [{
            "rank": r.get("rank"), "last_rank": r.get("last_rank"),
            "entry": r.get("entry"), "entry_name": r.get("entry_name"),
            "player_name": r.get("player_name"),
            "total": r.get("total"), "event_total": r.get("event_total"),
        } for r in (standings.get("results") or [])],
        "has_next": bool(standings.get("has_next")),
    }


# ---------------------------------------------------------------------------
# GET /api/fantasy/h2h — kahden entryn GW-voittotodennakoisyys
# ---------------------------------------------------------------------------

H2H_VAR_PER_XP = 2.5   # pelaajan GW-pistevarianssi ~ 2.5 * xP (heuristiikka)
H2H_DRAW_BAND = 3.0    # |ero| <= 3 p = "coin flip" -kaista


def _phi(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _entry_xi_xp(entry: int, gw_picks: int, gw_xp_target: int, pool_by_id):
    """(mu, var, matched, missing, entry_name). XI = picksien positiot 1-11,
    kapteeni tuplana (multiplier). Pelaaja ilman projektiota -> 0 xP + missing."""
    from src.models.fpl_rate_team import get_entry_picks
    root = _fetch_fpl(f"/entry/{entry}/")
    picks = (get_entry_picks(entry, gw_picks).get("picks") or [])
    mu = var = 0.0
    matched = 0
    missing = []
    for pk in picks:
        if int(pk.get("position") or 99) > 11:
            continue
        mult = pk.get("multiplier")
        if mult is None:
            mult = 2 if pk.get("is_captain") else 1
        if mult <= 0:
            mult = 1
        p = pool_by_id.get(pk.get("element"))
        if p is None:
            missing.append(pk.get("element"))
            continue
        xp = _gw_xp(p, gw_xp_target)
        mu += mult * xp
        var += (mult ** 2) * H2H_VAR_PER_XP * xp
        matched += 1
    return mu, var, matched, missing, root.get("name")


@router.get("/api/fantasy/h2h",
            description="Win probability between two entries for one gameweek. It assumes the two squads are independent, and the response says so.")
def fantasy_h2h(
    response: Response,
    entry_a: int = Query(...), entry_b: int = Query(...),
    gw: int | None = Query(default=None, ge=1, le=38),
):
    """GW-voittotodennakoisyys kahden entryn valilla. Normaaliapproksimaatio:
    kummankin XI:n xP-summa (kapteeni tuplana) = odotusarvo; varianssi =
    sum(multiplier^2 * 2.5 * xP) per pelaaja (dokumentoitu heuristiikka,
    riippumattomuusoletus — yhteiset pelaajat kumoavat toisensa vain
    odotusarvossa, eivat varianssissa). p_draw_band = |ero| <= 3 p."""
    response.headers["Cache-Control"] = "no-store"
    try:
        xp_data, bootstrap, pool, pool_by_id = build_context()
        picks_gw = _resolve_gw(bootstrap, gw)
        target_gw = clamp_gw_to_projections(picks_gw, pool, xp_data)
        mu_a, var_a, m_a, miss_a, name_a = _entry_xi_xp(
            entry_a, picks_gw, target_gw, pool_by_id)
        mu_b, var_b, m_b, miss_b, name_b = _entry_xi_xp(
            entry_b, picks_gw, target_gw, pool_by_id)
    except RateTeamError as e:
        raise _http(e)
    d = mu_a - mu_b
    s = math.sqrt(max(var_a + var_b, 1e-9))
    p_a = 1.0 - _phi((H2H_DRAW_BAND - d) / s)
    p_b = _phi((-H2H_DRAW_BAND - d) / s)
    p_band = max(0.0, 1.0 - p_a - p_b)
    return {
        "meta": {
            "gw": target_gw,
            "generated_at": xp_data["meta"].get("generated_at"),
            "method": ("Normal approximation: XI xP sums (captain doubled), "
                       f"per-player variance {H2H_VAR_PER_XP} * xP, "
                       f"draw band +/-{H2H_DRAW_BAND} pts. Assumes player "
                       "scores independent; shared players cancel in the "
                       "mean but not in the variance."),
            "disclaimer": DISCLAIMER,
        },
        "entry_a": {"entry": entry_a, "team_name": name_a,
                    "xi_xp": round(mu_a, 2), "players_matched": m_a,
                    "missing_ids": miss_a},
        "entry_b": {"entry": entry_b, "team_name": name_b,
                    "xi_xp": round(mu_b, 2), "players_matched": m_b,
                    "missing_ids": miss_b},
        "p_a": round(p_a, 4),
        "p_draw_band": round(p_band, 4),
        "p_b": round(p_b, 4),
    }


# ---------------------------------------------------------------------------
# GET /api/fantasy/rival — "Catch your rival" (MINI-LEAGUE-RIVAL, 13.8)
# ---------------------------------------------------------------------------

@router.get("/api/fantasy/rival",
            description="What catching a rival would take. The gap, the gameweeks left and the probability are free; the differential list is premium.")
def fantasy_rival(
    request: Request,
    response: Response,
    entry: int = Query(..., ge=1, le=99_999_999, description="Oma FPL entry-ID"),
    rival: int = Query(..., ge=1, le=99_999_999, description="Rivaalin entry-ID"),
    league_id: int | None = Query(default=None,
                                  description="Classic-liiga jonka taulukosta ero luetaan"),
    gap: float | None = Query(default=None,
                              description="Piste-ero suoraan (> 0 = olet jaljessa); ohittaa league_id:n"),
    gw: int | None = Query(default=None, ge=1, le=38),
):
    """Catch your rival: mita eron kiinni kurominen vaatii.

    FREE: ero + jaljella olevat kierrokset + P(catch) — kaikki
    tarkistettavissa FPL:n omasta taulukosta.
    PREMIUM: differentiaalilista ja asemakohtainen suositus, eli mallin kanta
    siihen mita erolle pitaisi tehda.

    Todennakoisyys tulee SAMASTA normaaliapproksimaatiosta ja samasta
    per-pelaaja-varianssista kuin /api/fantasy/h2h — yksi koneisto, ei kahta.
    Riippumattomuusoletus kerrotaan meta.method-kentassa.
    """
    from src.models.fpl_rival import build_rival_view

    response.headers["Cache-Control"] = "no-store"
    try:
        xp_data, bootstrap, pool, pool_by_id = build_context()
        picks_gw = _resolve_gw(bootstrap, gw)
        target_gw = clamp_gw_to_projections(picks_gw, pool, xp_data)

        # Piste-ero: eksplisiittinen arvo voittaa, muuten liigataulukosta.
        # Ilman kumpaakaan emme ARVAA nollaa — se olisi vaite jota kukaan ei
        # tehnyt (sama linja kuin Season racen puuttuvilla kierroksilla).
        the_gap = gap
        if the_gap is None:
            if league_id is None:
                raise HTTPException(
                    status_code=400,
                    detail="Provide either league_id (to read the gap from the "
                           "table) or gap (the points difference directly).")
            data = _fetch_fpl(
                f"/leagues-classic/{league_id}/standings/?page_standings=1")
            rows = ((data.get("standings") or {}).get("results") or [])
            by_entry = {int(r.get("entry")): r for r in rows if r.get("entry")}
            me, them = by_entry.get(entry), by_entry.get(rival)
            if me is None or them is None:
                missing = [e for e, r in ((entry, me), (rival, them)) if r is None]
                raise HTTPException(
                    status_code=404,
                    detail=f"Entry {missing[0]} is not on the first page of "
                           f"league {league_id}. Pass gap directly if the "
                           "rival is further down the table.")
            the_gap = float(them.get("total") or 0) - float(me.get("total") or 0)

        mu_you, var_you, m_you, miss_you, name_you = _entry_xi_xp(
            entry, picks_gw, target_gw, pool_by_id)
        mu_riv, var_riv, m_riv, miss_riv, name_riv = _entry_xi_xp(
            rival, picks_gw, target_gw, pool_by_id)
    except RateTeamError as e:
        raise _http(e)

    events = bootstrap.get("events") or []
    gws_left = sum(1 for e in events if not e.get("finished"))

    your_ids = {int(p["element"]) for p in
                (get_entry_picks(entry, picks_gw).get("picks") or [])}
    rival_ids = {int(p["element"]) for p in
                 (get_entry_picks(rival, picks_gw).get("picks") or [])}

    out = build_rival_view(
        gap=the_gap, gameweeks_left=gws_left,
        mu_you=mu_you, mu_rival=mu_riv,
        var_you=var_you, var_rival=var_riv,
        pool=pool, your_ids=your_ids, rival_ids=rival_ids,
        premium=is_premium_request(request))
    out["meta"]["gw"] = target_gw
    out["meta"]["generated_at"] = xp_data["meta"].get("generated_at")
    out["meta"]["disclaimer"] = DISCLAIMER
    out["you"] = {"entry": entry, "team_name": name_you,
                  "xi_xp": round(mu_you, 2), "players_matched": m_you}
    out["rival"] = {"entry": rival, "team_name": name_riv,
                    "xi_xp": round(mu_riv, 2), "players_matched": m_riv}
    return out


# ---------------------------------------------------------------------------
# GET /api/fantasy/edge — rank-tietoinen kerros (protect / climb)
# ---------------------------------------------------------------------------

EDGE_DIFF_MAX_EO = 10.0
EDGE_TEMPLATE_MIN_EO = 20.0
EDGE_EO_WEIGHT = 0.4  # kapteeniscoren EO-painon osuus (dokumentoitu kaava)


def _owned(p: dict) -> float:
    try:
        return float(p.get("owned_pct") or 0.0)
    except (TypeError, ValueError):
        return 0.0


@router.get("/api/fantasy/edge")
def fantasy_edge(
    request: Request, response: Response,
    entry: int = Query(..., description="Julkinen FPL entry-ID"),
    mode: str = Query(default="protect", pattern="^(protect|climb)$"),
):
    """Rank-tietoinen kerros. Heuristinen MVP, kaava dokumentoitu:
      captain score (protect) = gw_xp * (1 - w + w * EO/100)   [w=0.4]
      captain score (climb)   = gw_xp * (1 - w + w * (1 - EO/100))
    protect suosii korkeaa EO:ta (omistettu kapteeni suojaa rankia),
    climb matalan EO:n korkeaa xP:ta. Differentiaalit = EO <= 10 % korkein
    horisontti-xP joita ei omisteta; template-riskit = korkeimman EO:n
    pelaajat joita kayttajalla EI ole."""
    response.headers["Cache-Control"] = "no-store"
    premium = is_premium_request(request)
    try:
        xp_data, bootstrap, pool, pool_by_id = build_context()
        root = _fetch_fpl(f"/entry/{entry}/")
        overall_rank = root.get("summary_overall_rank")
        squad_ids, _cap, _bank, picks_gw = resolve_squad(
            bootstrap, entry, None, None, None, None)
        target_gw = clamp_gw_to_projections(picks_gw, pool, xp_data)
        squad = [pool_by_id[i] for i in squad_ids if i in pool_by_id]
        if len(squad) < 11:
            raise RateTeamError(
                422, "Too few of the squad's players have xP projections.")
        xi = optimal_xi(squad)
        # Addendum 2: serve-time-portti (jaettu 10 min bootstrap-cache, EI
        # uusia HTTP-kutsuja). Kapteeniehdokkaista ja differentiaali-/
        # template-listoista pudotetaan pelaajat jotka ovat NYT sivussa
        # mutta eivat olleet sita projektiohetkella.
        pool, dropped = apply_availability_gate(pool, bootstrap)
        dropped_ids = {r["id"] for r in dropped}
        xi = [p for p in xi if p["id"] not in dropped_ids] or xi
    except RateTeamError as e:
        raise _http(e)

    w = EDGE_EO_WEIGHT

    def _cap_score(p):
        eo = _owned(p) / 100.0
        factor = (1 - w + w * eo) if mode == "protect" else \
            (1 - w + w * (1 - eo))
        return _gw_xp(p, target_gw) * factor

    cap_rows = []
    for p in sorted(xi, key=_cap_score, reverse=True)[:5]:
        eo = _owned(p)
        if mode == "protect":
            why = (f"High effective ownership ({eo:.0f}%) - captaining him "
                   "shields your rank if he hauls.") if eo >= 20 else \
                  (f"Modest ownership ({eo:.0f}%) but the xP is strong "
                   "enough to keep him in the protect list.")
        else:
            why = (f"Only {eo:.0f}% owned with "
                   f"{_gw_xp(p, target_gw):.1f} xP - a haul moves you up, "
                   "not sideways.") if eo < 20 else \
                  (f"Template pick ({eo:.0f}% owned) - safe floor, "
                   "limited climb upside.")
        cap_rows.append({**_mini(p), "gw_xp": round(_gw_xp(p, target_gw), 2),
                         "owned_pct": eo,
                         "score": round(_cap_score(p), 2),
                         "rationale": why})

    squad_set = {p["id"] for p in squad}
    diffs = []
    for p in sorted((p for p in pool if p["id"] not in squad_set
                     and _owned(p) <= EDGE_DIFF_MAX_EO),
                    key=lambda p: p["xp_horizon_total"], reverse=True)[:5]:
        diffs.append({**_mini(p), "owned_pct": _owned(p),
                      "price": p["price"] / 10.0,
                      "xp_horizon_total": round(p["xp_horizon_total"], 2),
                      "rationale": (f"{_owned(p):.1f}% owned, "
                                    f"{p['xp_horizon_total']:.1f} xP over the "
                                    "horizon - upside the field does not "
                                    "share.")})

    template = []
    high_eo = sorted((p for p in pool if p["id"] not in squad_set),
                     key=_owned, reverse=True)
    for p in high_eo[:3]:
        if _owned(p) < EDGE_TEMPLATE_MIN_EO and template:
            break
        template.append({**_mini(p), "owned_pct": _owned(p),
                         "price": p["price"] / 10.0,
                         "xp_horizon_total": round(p["xp_horizon_total"], 2),
                         "rationale": (f"Owned by {_owned(p):.0f}% - when he "
                                       "scores and you do not own him, your "
                                       "rank slides.")})

    payload = {
        "meta": {
            "entry": entry, "mode": mode, "gw": target_gw,
            "overall_rank": overall_rank,
            "generated_at": xp_data["meta"].get("generated_at"),
            "formula": (f"captain score = gw_xp * (1 - {w} + {w} * EO/100) "
                        "for protect; EO term inverted for climb. Heuristic "
                        "MVP - honest weighting, not a rank simulation."),
            "availability_gate": {"checked": True, "dropped": dropped,
                                  "note": AVAILABILITY_GATE_NOTE},
            "disclaimer": DISCLAIMER,
        },
        "captain_top5": cap_rows,
        "differentials": diffs,
        "template_risks": template,
    }
    if not premium:
        payload["meta"] = {**payload["meta"], "masked": True,
                           "mask": "free preview - lists truncated"}
        payload["captain_top5"] = cap_rows[:FREE_EDGE_CAPTAINS]
        payload["differentials"] = diffs[:FREE_EDGE_DIFFERENTIALS]
        payload["template_risks"] = template[:FREE_EDGE_TEMPLATE_RISKS]
    return payload


# ---------------------------------------------------------------------------
# Per-pelaajan DefCon-erittely (Villen pyynto 25.7: "missa nakyy pelaaja-
# kohtainen defcon ERITELTYNA"). FREE: kaikki luvut ovat FPL:n omaa julkista
# otteludataa (defensive_contribution + CBI/tacklet/riistot), ei mallin
# tuotoksia -> ei premium-maskia.
#
# Lyhenteet vastauksessa: dc = FPL:n defensive_contribution (DEF: CBIT,
# MID/FWD: CBIRT). cbi = clearances+blocks+interceptions (FPL tarjoaa nama
# yhtena kenttana, ei eroteltavissa), tkl = tacklet, rec = riistot
# (recoveries; lasketaan mukaan vain MID/FWD-kynnykseen).
# ---------------------------------------------------------------------------
@router.get("/api/fantasy/defcon/{player_id}")
def fantasy_defcon_player(
    response: Response,
    player_id: int,
    window: int = Query(default=10, ge=3, le=10),
):
    """Yhden pelaajan DefCon-loki ottelu ottelulta + osaerittely.

    Palauttaa per ottelu: dc-summan, kynnysosuman ja komponentit (cbi/tkl/rec)
    kun ne ovat datassa. Komponentit puuttuvat vanhemmista snapshoteista ->
    `components_available` kertoo rehellisesti kumpi tilanne on."""
    from src.models.fpl_leaders import (
        DEFCON_POINTS, DEFCON_THRESHOLD, defcon_hit, load_leaders,
    )
    from src.models.fpl_rate_team import RateTeamError
    response.headers["Cache-Control"] = "no-store"
    try:
        data = load_leaders()
    except RateTeamError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)

    player = next((p for p in data.get("players", [])
                   if p.get("id") == player_id), None)
    if player is None:
        raise HTTPException(status_code=404,
                            detail="Player not found in the DefCon dataset.")
    pos = player.get("pos")
    if pos == "GKP":
        raise HTTPException(
            status_code=404,
            detail="Goalkeepers cannot score defensive contribution points.")

    rows = (player.get("recent_games") or [])[-window:]
    games = []
    tot = {"dc": 0, "cbi": 0, "tkl": 0, "rec": 0, "hits": 0}
    have_components = False
    for g in rows:
        dc = int(g.get("dc") or 0)
        hit = defcon_hit(pos, dc)
        row = {
            "round": g.get("round"),
            "opp": g.get("opp"),
            "venue": g.get("venue"),
            "minutes": g.get("minutes"),
            "dc": dc,
            "hit": hit,
        }
        for key in ("cbi", "tkl", "rec"):
            if g.get(key) is not None:
                row[key] = int(g[key])
                tot[key] += int(g[key])
                have_components = True
        games.append(row)
        tot["dc"] += dc
        tot["hits"] += 1 if hit else 0

    n = len(games) or 1
    threshold = DEFCON_THRESHOLD.get(pos)
    totals = {
        "games": len(games),
        "hits": tot["hits"],
        "hit_rate_pct": round(100.0 * tot["hits"] / n, 0),
        "dc_per_game": round(tot["dc"] / n, 1),
        "defcon_points": tot["hits"] * DEFCON_POINTS,
    }
    if have_components:
        totals.update({
            "cbi_per_game": round(tot["cbi"] / n, 1),
            "tkl_per_game": round(tot["tkl"] / n, 1),
            "rec_per_game": round(tot["rec"] / n, 1),
        })

    meta = dict(data.get("meta") or {})
    return {
        "meta": {
            "window": window,
            "threshold": threshold,
            "points_per_hit": DEFCON_POINTS,
            "counts_recoveries": pos in ("MID", "FWD"),
            "components_available": have_components,
            "basis_season": meta.get("basis_season"),
            "is_prev_season_basis": meta.get("is_prev_season_basis"),
            "basis_label": meta.get("basis_label"),
            "generated_at": meta.get("generated_at"),
            "rule_note": (
                "2 points when a defender reaches 10 CBIT (clearances, "
                "blocks, interceptions, tackles) or a midfielder or forward "
                "reaches 12 CBIRT (CBIT plus ball recoveries). Counts are "
                "FPL's own match data."),
        },
        "player": {
            "id": player.get("id"),
            "web_name": player.get("web_name"),
            "team_short": player.get("team_short"),
            "pos": pos,
            "price": player.get("price"),
            "owned_pct": player.get("owned_pct"),
        },
        "games": games,
        "totals": totals,
    }
