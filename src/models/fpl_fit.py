"""#155 Fit checker — "mahtuuko premium-trio runkoon" -laskin.

Pre-GW1-yhteisön ykköskysymys (X-signaali 22.7: OfficialFPL "will you try to
fit Haaland, Fernandes and Gabriel", managerit laskevat £64.5-jäännöstä
käsin): lukitse 1–3 pakkopelaajaa → rakennetaan paras laillinen XI + penkki
niiden ympärille horisontti-xP:llä, ja näytetään mitä lukitseminen maksaa
suhteessa mallin vapaaseen optimibudjettijoukkueeseen (#50-benchmark).

Sama dokumentoitu ahne heuristiikka kuin optimal_budget_team_xp (ei globaali
optimi, mutta deterministinen ja rehellinen — sama menetelmä molemmilla
puolilla vertailua, joten delta on omenat-omenoihin). Lukitut pakotetaan
XI:hin (penkille lukittu pakkopelaaja olisi kysymyksen ohittamista).

Ei kirjoita mitään; lukee saman committatun projektion + bootstrapin kuin
rate-team (build_context). Analytics, not betting.
"""
from __future__ import annotations

from src.models.fpl_rate_team import (
    BUDGET_TENTHS,
    MAX_PER_CLUB,
    POS_NAME,
    RateTeamError,
    SQUAD_QUOTA,
    XI_MAX,
    XI_MIN,
    build_context,
)

MAX_LOCKED = 3


def _bench_outfield(xi: list[dict], bench_gk: dict,
                    pool: list[dict]) -> list[dict]:
    """Halvimmat kenttäpenkkarit niin että XI + penkki-GK + nämä = tasan
    SQUAD_QUOTA (2/5/5/3) ja max 3/klubi säilyy koko rungossa."""
    used_ids = {p["id"] for p in xi} | {bench_gk["id"]}
    counts = {t: 0 for t in SQUAD_QUOTA}
    clubs: dict[int, int] = {}
    for p in xi + [bench_gk]:
        counts[p["element_type"]] += 1
        clubs[p["club"]] = clubs.get(p["club"], 0) + 1
    bench: list[dict] = []
    for t in (2, 3, 4):
        need = SQUAD_QUOTA[t] - counts[t]
        if need <= 0:
            continue
        candidates = sorted(
            (p for p in pool
             if p["element_type"] == t and p["id"] not in used_ids),
            key=lambda p: (p["price"], -p["xp_horizon_total"]))
        for p in candidates:
            if need == 0:
                break
            if clubs.get(p["club"], 0) >= MAX_PER_CLUB:
                continue
            bench.append(p)
            clubs[p["club"]] = clubs.get(p["club"], 0) + 1
            need -= 1
        if need > 0:
            raise RateTeamError(
                500, "Could not complete a legal bench from the player pool.")
    return bench


def _greedy_xi(pool: list[dict], locked: list[dict], xi_budget: int,
               base_clubs: dict[int, int], skip_ids: set[int],
               club_cap: int = MAX_PER_CLUB) -> list[dict]:
    """Ahne XI lukituilla pohjalla: sama kiintiö-/klubi-/budjettiturvaus kuin
    #50-benchmarkissa, mutta aloitetaan lukituista. base_clubs = etukäteen
    varatun penkki-GK:n klubi (lasketaan capiin ettei runko lukkiudu);
    club_cap voidaan tiukentaa fallback-kierroksella."""
    xi = list(locked)
    counts = {t: 0 for t in XI_MIN}
    clubs: dict[int, int] = dict(base_clubs)
    cost = 0
    for p in xi:
        counts[p["element_type"]] += 1
        clubs[p["club"]] = clubs.get(p["club"], 0) + 1
        cost += p["price"]
    min_price = min(p["price"] for p in pool)
    locked_ids = {p["id"] for p in locked}
    ranked = sorted(pool, key=lambda p: p["xp_horizon_total"], reverse=True)
    for p in ranked:
        if len(xi) == 11:
            break
        if p["id"] in locked_ids or p["id"] in skip_ids:
            continue
        t = p["element_type"]
        if counts[t] >= XI_MAX[t]:
            continue
        if clubs.get(p["club"], 0) >= club_cap:
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
    if len(xi) < 11 or any(counts[t] < n for t, n in XI_MIN.items()):
        raise RateTeamError(
            422, "Could not build a legal XI around the locked players "
                 "within the budget. Try locking fewer or cheaper players.")
    return xi


def _validate_locked(locked_ids: list[int],
                     pool_by_id: dict[int, dict]) -> list[dict]:
    if not locked_ids:
        raise RateTeamError(400, "Provide 1-3 locked player IDs.")
    if len(locked_ids) > MAX_LOCKED:
        raise RateTeamError(400, f"Lock at most {MAX_LOCKED} players.")
    if len(set(locked_ids)) != len(locked_ids):
        raise RateTeamError(400, "locked contains duplicate IDs.")
    locked = []
    for pid in locked_ids:
        p = pool_by_id.get(pid)
        if p is None:
            raise RateTeamError(
                404, f"Player {pid} is not in the projection pool.")
        locked.append(p)
    if len([p for p in locked if p["element_type"] == 1]) > XI_MAX[1]:
        raise RateTeamError(400, "Lock at most one goalkeeper (XI has one).")
    clubs: dict[int, int] = {}
    for p in locked:
        clubs[p["club"]] = clubs.get(p["club"], 0) + 1
    if any(n > MAX_PER_CLUB for n in clubs.values()):
        raise RateTeamError(400, f"At most {MAX_PER_CLUB} players per club.")
    if sum(p["price"] for p in locked) > BUDGET_TENTHS:
        raise RateTeamError(422, "Locked players alone exceed the budget.")
    return locked


def _player_out(p: dict) -> dict:
    return {
        "id": p["id"],
        "web_name": p["web_name"],
        "team_short": p["team_short"],
        "pos": POS_NAME[p["element_type"]],
        "price": round(p["price"] / 10, 1),
        "xp_horizon_total": round(p["xp_horizon_total"], 2),
        "xp_per_gw": round(p["xp_per_gw"], 2),
    }


def _best_squad(pool: list[dict], by_pos: dict[int, list[dict]],
                locked: list[dict]) -> tuple[list[dict], list[dict]]:
    """Paras laillinen 15 (XI + penkki) lukittujen ympärille. Penkki-GK:t
    kokeillaan max 4 eri klubin halvimmista (yksi kiinteä valinta voi
    deadlockata XI-GKP:n jos vapaiden maalivahtien klubit täyttyvät) ja
    PARAS XI-xP-tulos voittaa; budjettiylitys → tiukennus (max 4 kierrosta);
    jos cap 3 ei tuota runkoa → fallback cap 2 (hajauttaa klubit)."""
    locked_ids_set = {p["id"] for p in locked}
    gk_candidates = sorted(
        (p for p in by_pos[1] if p["id"] not in locked_ids_set),
        # Halvin ja heikoin ensin — penkki-GK on kehonlämmitin.
        key=lambda p: (p["price"], p["xp_horizon_total"]))
    if not gk_candidates:
        raise RateTeamError(503, "No goalkeeper available for the bench.")
    bench_gk_tries: list[dict] = []
    seen_clubs: set[int] = set()
    for p in gk_candidates:
        if p["club"] in seen_clubs:
            continue
        bench_gk_tries.append(p)
        seen_clubs.add(p["club"])
        if len(bench_gk_tries) == 4:
            break
    outfield_prices = sorted(p["price"] for t in (2, 3, 4) for p in by_pos[t])

    best: tuple[float, list[dict], list[dict]] | None = None
    for club_cap in (MAX_PER_CLUB, MAX_PER_CLUB - 1):
        for bench_gk in bench_gk_tries:
            xi_budget = BUDGET_TENTHS - (bench_gk["price"]
                                         + sum(outfield_prices[:3]))
            try:
                for _attempt in range(4):
                    xi = _greedy_xi(pool, locked, xi_budget,
                                    base_clubs={bench_gk["club"]: 1},
                                    skip_ids={bench_gk["id"]},
                                    club_cap=club_cap)
                    bench = [bench_gk] + _bench_outfield(xi, bench_gk, pool)
                    total_cost = (sum(p["price"] for p in xi)
                                  + sum(p["price"] for p in bench))
                    if total_cost <= BUDGET_TENTHS:
                        xi_xp = sum(p["xp_horizon_total"] for p in xi)
                        if best is None or xi_xp > best[0]:
                            best = (xi_xp, xi, bench)
                        break
                    xi_budget -= total_cost - BUDGET_TENTHS
            except RateTeamError as e:
                if e.status_code == 400:
                    raise
                continue
        if best is not None:
            break  # cap 2 vain jos cap 3 ei tuottanut yhtään runkoa
    if best is None:
        raise RateTeamError(
            422, "Could not fit a legal 15-player squad under the budget "
                 "with these locked players.")
    return best[1], best[2]


_FREE_OPTIMUM_CACHE: dict[str, float] = {}


def fit_squad(locked_ids: list[int]) -> dict:
    """Rakenna paras laillinen runko lukittujen ympärille + delta vs vapaa
    optimi SAMALLA koneistolla (locked=[]) — omenat-omenoihin-vertailu
    (#50-benchmark ei rakenna oikeaa penkkiä → olisi optimistinen).
    Deterministinen; ei kirjoita mitään."""
    xp_data, _bootstrap, pool, pool_by_id = build_context()
    locked = _validate_locked(locked_ids, pool_by_id)

    by_pos: dict[int, list[dict]] = {1: [], 2: [], 3: [], 4: []}
    for p in pool:
        by_pos[p["element_type"]].append(p)
    if any(len(by_pos[t]) < n for t, n in SQUAD_QUOTA.items()):
        raise RateTeamError(503, "Projection pool is too small for a squad.")

    xi, bench = _best_squad(pool, by_pos, locked)
    xi_xp = sum(p["xp_horizon_total"] for p in xi)
    horizon = int(xp_data["meta"].get("horizon_gw") or 6)

    cache_key = str(xp_data["meta"].get("generated_at") or "fit")
    optimal_xp = _FREE_OPTIMUM_CACHE.get(cache_key)
    if optimal_xp is None:
        free_xi, _free_bench = _best_squad(pool, by_pos, [])
        optimal_xp = sum(p["xp_horizon_total"] for p in free_xi)
        _FREE_OPTIMUM_CACHE.clear()
        _FREE_OPTIMUM_CACHE[cache_key] = optimal_xp
    delta = round(xi_xp - optimal_xp, 2)
    squad_cost = sum(p["price"] for p in xi) + sum(p["price"] for p in bench)

    locked_names = ", ".join(p["web_name"] for p in locked)
    if delta >= -0.005:
        message = (f"Locking {locked_names} costs nothing: this is the "
                   f"model's best budget XI over the next {horizon} GWs.")
    else:
        message = (f"Fitting {locked_names} costs {abs(delta):.1f} xP over "
                   f"the next {horizon} GWs vs the model's best free squad. "
                   f"Model projection, not advice you have to follow.")

    return {
        "meta": {
            "horizon_gw": horizon,
            "next_gameweek": xp_data["meta"].get("next_gameweek"),
            "generated_at": xp_data["meta"].get("generated_at"),
            "budget_cap": round(BUDGET_TENTHS / 10, 1),
            "squad_cost": round(squad_cost / 10, 1),
            "bank": round((BUDGET_TENTHS - squad_cost) / 10, 1),
        },
        "locked": [_player_out(p) for p in locked],
        "xi": [_player_out(p) for p in sorted(
            xi, key=lambda p: (p["element_type"], -p["xp_horizon_total"]))],
        "bench": [_player_out(p) for p in sorted(
            bench, key=lambda p: p["element_type"])],
        "totals": {
            "xi_xp_horizon": round(xi_xp, 2),
            "optimal_xp_horizon": round(optimal_xp, 2),
            "delta_xp": delta,
        },
        "message": message,
    }
