"""#35 Transfer Planner -suite: monen GW:n siirtosuunnittelu + captain-picker +
differential finder + pelaajavertailu.

Kaikki nojaa OLEMASSA OLEVAAN xP-projektioon (/api/fantasy/xp, #33
predicted-minutes mukana) ja #34-rate-teamin jaettuun infraan (build_context,
resolve_squad, optimal_xi) — xP-malliin EI kosketa.

PLANNER-HEURISTIIKKA (dokumentoitu rajaus, EI globaali optimoija — scope-kuri
CoS-linjauksen mukaan; greedy + rajattu kandidaattijoukko riittää GW1-arvoon):
  - Käydään horisontin GW:t järjestyksessä. Per GW arvioidaan yhden siirron
    kandidaatit: ulos kuka tahansa rungon 15:stä, sisään saman position
    TOP_CANDIDATES_PER_POS parasta poolipelaajaa (jäljellä olevan horisontin
    xP:llä), budjetti (bank + lähtevän hinta) + max 3/klubi vaihdon jälkeen.
  - Siirron arvo = sisään tulevan ja lähtevän xP-ero JÄLJELLÄ OLEVALLE
    horisontille (ei koko kaudelle) − hit-kustannus (HIT_COST jos free
    transferit loppu). Tehdään ahneesti niin kauan kuin paras arvo ylittää
    MIN_GAIN_PER_TRANSFER:in, max MAX_TRANSFERS_PER_GW/GW.
  - Free transferit: alussa `ft`-parametri (oletus 1), +1 per GW, katto
    FT_CARRY_MAX (FPL 2024- säännöt: 5). "Roll transfer" kirjataan kun optimi
    on säästää siirto.
  - Gate: suunnitelman netto-xP (kumulatiivinen xP − hitit) ei koskaan alita
    ei-siirtoja-baselinea — muuten palautetaan hold-suunnitelma (testattu).
"""
from __future__ import annotations

from src.models.fpl_rate_team import (
    POS_NAME, MAX_PER_CLUB, RateTeamError, build_context,
    captain_suggestion, clamp_gw_to_projections, optimal_xi, resolve_squad,
    _gw_xp,
)

HIT_COST = 4.0
FT_CARRY_MAX = 5
MAX_TRANSFERS_PER_GW = 2
TOP_CANDIDATES_PER_POS = 8
MIN_GAIN_PER_TRANSFER = 0.5  # alle tämän → roll (siirto ei ole vaivan arvoinen)
DIFFERENTIAL_MAX_OWNERSHIP = 10.0
DIFFERENTIAL_TOP_N = 20
CAPTAIN_DIFFERENTIAL_EO = 10.0


def _horizon_gws(pool: list[dict], start_gw: int, horizon: int) -> list[int]:
    covered = sorted({g.get("gw") for p in pool
                      for g in (p.get("gameweeks") or [])})
    gws = [g for g in covered if g >= start_gw][:horizon]
    if not gws:
        raise RateTeamError(503, "No projected gameweeks in range.")
    return gws


def _remaining_xp(player: dict, gws: list[int]) -> float:
    return sum(_gw_xp(player, g) for g in gws)


def _club_counts(squad: list[dict]) -> dict[int, int]:
    counts: dict[int, int] = {}
    for p in squad:
        counts[p["club"]] = counts.get(p["club"], 0) + 1
    return counts


def _best_transfer(squad: list[dict], pool: list[dict], bank_tenths: int,
                   gws_left: list[int]) -> dict | None:
    """Paras yksittäinen siirto jäljellä olevalle horisontille (tai None)."""
    squad_ids = {p["id"] for p in squad}
    clubs = _club_counts(squad)
    # Kandidaatit: per positio TOP_N jäljellä olevan horisontin xP:llä
    by_pos: dict[int, list[dict]] = {1: [], 2: [], 3: [], 4: []}
    for p in pool:
        if p["id"] not in squad_ids:
            by_pos[p["element_type"]].append(p)
    for t in by_pos:
        by_pos[t].sort(key=lambda p: _remaining_xp(p, gws_left), reverse=True)
        by_pos[t] = by_pos[t][:TOP_CANDIDATES_PER_POS]

    best: dict | None = None
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
            if best is None or gain > best["gain"]:
                best = {"out": out_p, "in": in_p, "gain": gain}
    return best


def plan_transfers(entry: int | None = None, gw: int | None = None,
                   players: list[int] | None = None, bank: float | None = None,
                   horizon: int = 3, ft: int = 1) -> dict:
    """Monen GW:n siirtosuunnitelma (greedy + jäljellä olevan horisontin arvo)."""
    if not 2 <= horizon <= 6:
        raise RateTeamError(400, "horizon must be between 2 and 6.")
    if not 0 <= ft <= FT_CARRY_MAX:
        raise RateTeamError(400, f"ft must be between 0 and {FT_CARRY_MAX}.")
    xp_data, bootstrap, pool, pool_by_id = build_context()
    squad_ids, _cap, bank_tenths, picks_gw = resolve_squad(
        bootstrap, entry, gw, players, None, bank)
    start_gw = clamp_gw_to_projections(picks_gw, pool, xp_data)
    gws = _horizon_gws(pool, start_gw, horizon)

    squad = [pool_by_id[i] for i in squad_ids if i in pool_by_id]
    if len(squad) < 11:
        raise RateTeamError(422, "Too few of the squad's players have xP "
                                 f"projections ({len(squad)}/15 matched).")
    missing = [i for i in squad_ids if i not in pool_by_id]

    # Baseline: ei siirtoja — sama XI-valinta per GW (penkkirotaatio sallittu)
    def _gw_score(sq: list[dict], g: int) -> float:
        xi = optimal_xi(sq)
        cap = max(xi, key=lambda p: _gw_xp(p, g))
        return sum(_gw_xp(p, g) for p in xi) + _gw_xp(cap, g)

    baseline_total = sum(_gw_score(squad, g) for g in gws)
    original_squad = list(squad)

    plan = []
    fts = ft
    bank_now = bank_tenths
    total_hits = 0.0
    for idx, g in enumerate(gws):
        gws_left = gws[idx:]
        moves = []
        n_moves = 0
        while n_moves < MAX_TRANSFERS_PER_GW:
            cand = _best_transfer(squad, pool, bank_now, gws_left)
            if cand is None:
                break
            hit = 0.0 if fts > 0 else HIT_COST
            net_gain = cand["gain"] - hit
            if net_gain < MIN_GAIN_PER_TRANSFER:
                break
            # Toteuta siirto
            squad = [p for p in squad if p["id"] != cand["out"]["id"]]
            squad.append(cand["in"])
            bank_now += cand["out"]["price"] - cand["in"]["price"]
            if fts > 0:
                fts -= 1
            else:
                total_hits += HIT_COST
            n_moves += 1
            moves.append({
                "out": {"id": cand["out"]["id"],
                        "web_name": cand["out"]["web_name"],
                        "team_short": cand["out"]["team_short"]},
                "in": {"id": cand["in"]["id"],
                       "web_name": cand["in"]["web_name"],
                       "team_short": cand["in"]["team_short"]},
                "pos": POS_NAME[cand["out"]["element_type"]],
                "gain_xp_remaining": round(cand["gain"], 2),
                "hit": hit,
            })
        xi = optimal_xi(squad)
        cap = max(xi, key=lambda p: _gw_xp(p, g))
        gw_xp_val = sum(_gw_xp(p, g) for p in xi) + _gw_xp(cap, g)
        plan.append({
            "gw": g,
            "transfers": moves,
            "roll_transfer": not moves,
            "captain": {"id": cap["id"], "web_name": cap["web_name"],
                        "gw_xp": round(_gw_xp(cap, g), 2)},
            "gw_xp": round(gw_xp_val, 2),
            "free_transfers_left": fts,
            "bank": round(bank_now / 10.0, 1),
        })
        fts = min(FT_CARRY_MAX, fts + 1)  # +1 FT seuraavaan GW:hen

    plan_total = sum(p["gw_xp"] for p in plan) - total_hits
    # Gate: suunnitelma ei koskaan alita ei-siirtoja-baselinea → hold-fallback
    # (rakenteellisesti epätodennäköinen koska jokainen siirto vaatii
    # MIN_GAIN-ylityksen hitin jälkeen, mutta vahditaan silti eksplisiittisesti)
    if plan_total < baseline_total:
        plan = []
        fts_h = ft
        for g in gws:
            xi = optimal_xi(original_squad)
            cap = max(xi, key=lambda p: _gw_xp(p, g))
            plan.append({
                "gw": g, "transfers": [], "roll_transfer": True,
                "captain": {"id": cap["id"], "web_name": cap["web_name"],
                            "gw_xp": round(_gw_xp(cap, g), 2)},
                "gw_xp": round(sum(_gw_xp(p, g) for p in xi)
                               + _gw_xp(cap, g), 2),
                "free_transfers_left": fts_h,
                "bank": round(bank_tenths / 10.0, 1),
            })
            fts_h = min(FT_CARRY_MAX, fts_h + 1)
        plan_total = baseline_total
        total_hits = 0.0

    return {
        "meta": {
            "entry": entry, "start_gw": gws[0], "horizon": len(gws),
            "generated_at": xp_data["meta"].get("generated_at"),
            "heuristic": ("greedy, remaining-horizon value, max "
                          f"{MAX_TRANSFERS_PER_GW} transfers/GW, hit -4, "
                          f"FT carry max {FT_CARRY_MAX} - not a global optimum"),
            "note": "GoalIQ model projections - for fun and planning, "
                    "not betting advice.",
        },
        "plan": plan,
        "totals": {
            "plan_xp": round(plan_total, 2),
            "baseline_xp_no_transfers": round(baseline_total, 2),
            "net_gain": round(plan_total - baseline_total, 2),
            "hits_taken": int(total_hits / HIT_COST),
        },
        "missing_ids": missing,
    }


def captain_picker(entry: int | None = None, gw: int | None = None,
                   players: list[int] | None = None) -> dict:
    """Top-3 kapteeniehdokasta + differential-kapteeni (EO ≤ 10 %)."""
    xp_data, bootstrap, pool, pool_by_id = build_context()
    squad_ids, _cap, _bank, picks_gw = resolve_squad(
        bootstrap, entry, gw, players, None, None)
    target_gw = clamp_gw_to_projections(picks_gw, pool, xp_data)
    squad = [pool_by_id[i] for i in squad_ids if i in pool_by_id]
    if len(squad) < 11:
        raise RateTeamError(422, "Too few projected players in the squad.")
    xi = optimal_xi(squad)
    ranked = sorted(xi, key=lambda p: _gw_xp(p, target_gw), reverse=True)

    def _fmt(p):
        return {"id": p["id"], "web_name": p["web_name"],
                "team_short": p["team_short"],
                "gw_xp": round(_gw_xp(p, target_gw), 2),
                "owned_pct": p.get("owned_pct")}

    top3 = [_fmt(p) for p in ranked[:3]]
    for i, t in enumerate(top3):
        t["gap_to_top"] = round(top3[0]["gw_xp"] - t["gw_xp"], 2) if i else 0.0
    diff = next((p for p in ranked
                 if (p.get("owned_pct") or 100.0) <= CAPTAIN_DIFFERENTIAL_EO),
                None)
    return {
        "meta": {"gw": target_gw,
                 "generated_at": xp_data["meta"].get("generated_at")},
        "top3": top3,
        "differential": (_fmt(diff) if diff and diff["id"] not in
                         {t["id"] for t in top3[:1]} else None),
    }


def differential_finder(max_ownership: float = DIFFERENTIAL_MAX_OWNERSHIP,
                        pos: str | None = None) -> dict:
    """Matala EO × korkea xP -listaus koko poolista (ei vaadi entryä)."""
    if not 0 < max_ownership <= 100:
        raise RateTeamError(400, "max_ownership must be in (0, 100].")
    pos_by_name = {v: k for k, v in POS_NAME.items()}
    if pos is not None and pos not in pos_by_name:
        raise RateTeamError(400, f"pos must be one of {sorted(pos_by_name)}.")
    xp_data, _bootstrap, pool, _by_id = build_context()
    cands = [p for p in pool
             if (p.get("owned_pct") or 0.0) <= max_ownership
             and (pos is None or p["element_type"] == pos_by_name[pos])]
    cands.sort(key=lambda p: p["xp_horizon_total"], reverse=True)
    return {
        "meta": {"max_ownership": max_ownership, "pos": pos,
                 "generated_at": xp_data["meta"].get("generated_at"),
                 "horizon_gw": xp_data["meta"].get("horizon_gw")},
        "players": [{
            "id": p["id"], "web_name": p["web_name"],
            "team_short": p["team_short"], "pos": POS_NAME[p["element_type"]],
            "price": p["price"] / 10.0, "owned_pct": p["owned_pct"],
            "xp_per_gw": round(p["xp_per_gw"], 2),
            "xp_horizon_total": round(p["xp_horizon_total"], 2),
        } for p in cands[:DIFFERENTIAL_TOP_N]],
    }


def compare_players(player_ids: list[int]) -> dict:
    """2–3 pelaajan rinnakkaisvertailu + suora kanta xP-erolla."""
    if not 2 <= len(player_ids) <= 3:
        raise RateTeamError(400, "compare takes 2 or 3 player IDs.")
    if len(set(player_ids)) != len(player_ids):
        raise RateTeamError(400, "compare IDs must be distinct.")
    xp_data, _bootstrap, _pool, pool_by_id = build_context()
    rows = []
    for pid in player_ids:
        p = pool_by_id.get(pid)
        if p is None:
            raise RateTeamError(404, f"Player {pid} has no xP projection.")
        rows.append({
            "id": p["id"], "web_name": p["web_name"],
            "team_short": p["team_short"], "pos": POS_NAME[p["element_type"]],
            "price": p["price"] / 10.0, "owned_pct": p["owned_pct"],
            "xmins": p.get("xmins"),
            "predicted_starts": p.get("predicted_starts"),
            "minutes_confidence": p.get("minutes_confidence"),
            "xp_per_gw": round(p["xp_per_gw"], 2),
            "xp_horizon_total": round(p["xp_horizon_total"], 2),
            "components": p.get("components"),
            "components_gw": p.get("components_gw"),
        })
    ranked = sorted(rows, key=lambda r: r["xp_horizon_total"], reverse=True)
    margin = round(ranked[0]["xp_horizon_total"] - ranked[1]["xp_horizon_total"], 2)
    verdict = {
        "pick": {"id": ranked[0]["id"], "web_name": ranked[0]["web_name"]},
        "margin_xp_horizon": margin,
        "text": (f"{ranked[0]['web_name']} projects {margin} xP more than "
                 f"{ranked[1]['web_name']} over the horizon."
                 if margin >= 0.5 else
                 f"Too close to call - {ranked[0]['web_name']} edges it by "
                 f"{margin} xP over the horizon."),
    }
    return {
        "meta": {"generated_at": xp_data["meta"].get("generated_at"),
                 "horizon_gw": xp_data["meta"].get("horizon_gw")},
        "players": rows,
        "verdict": verdict,
    }
