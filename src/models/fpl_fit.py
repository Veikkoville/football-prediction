"""#155 Fit checker — "mahtuuko premium-trio runkoon" -laskin.

Pre-GW1-yhteisön ykköskysymys (X-signaali 22.7: OfficialFPL "will you try to
fit Haaland, Fernandes and Gabriel", managerit laskevat £64.5-jäännöstä
käsin): lukitse 1–3 pakkopelaajaa → rakennetaan paras laillinen XI + penkki
niiden ympärille horisontti-xP:llä, ja näytetään mitä lukitseminen maksaa
suhteessa mallin vapaaseen optimibudjettijoukkueeseen (#50-benchmark).

29.7 — YKSI OPTIMOIJA, EI KAHTA. Tässä oli oma vanhempi ahne optimoija, josta
puuttui 28.7. tehty eksakti haku (DP + max-plus-konvoluutio) JA pelattava penkki
(BENCH_MIN_XMINS). Seuraus mitattiin tuotannosta: fit väitti "mallin parhaaksi"
282.31 xP samaan aikaan kun benchmark ja /fpl/model-xi väittivät 303.34 —
21 xP:n ero, ja fitin viesti kuului sanatarkasti "Locking Haaland costs nothing:
this is the model's best budget XI" vaikka mallin oma XI ei sisällä Haalandia
lainkaan. Kaksi pintaa ei voi molempia olla "mallin paras". Nyt molemmat ajavat
fpl_rate_team.build_optimal_squadia; lukitut ovat sille parametri, joten ero on
rakenteellisesti mahdoton eikä kirjanpidon varassa.

Copy noudattaa samaa rehellisyysporttia kuin rate-team: "best" vain kun ratkaisu
on todistetusti optimi (proven), muuten "the strongest ... the model found".

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
    build_context,
    build_optimal_squad,
    free_optimum,
)

MAX_LOCKED = 3


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


def fit_squad(locked_ids: list[int]) -> dict:
    """Rakenna paras laillinen runko lukittujen ympärille + delta vs vapaa
    optimi SAMALLA optimoijalla — omenat-omenoihin, ja sama luku kuin
    rate-teamin benchmark ja /fpl/model-xi näyttävät.
    Deterministinen; ei kirjoita mitään."""
    xp_data, _bootstrap, pool, pool_by_id = build_context()
    locked = _validate_locked(locked_ids, pool_by_id)

    by_pos: dict[int, list[dict]] = {1: [], 2: [], 3: [], 4: []}
    for p in pool:
        by_pos[p["element_type"]].append(p)
    if any(len(by_pos[t]) < n for t, n in SQUAD_QUOTA.items()):
        raise RateTeamError(503, "Projection pool is too small for a squad.")

    fitted = build_optimal_squad(pool, locked)
    xi, bench = fitted["xi"], fitted["bench"]
    if not xi or len(bench) != 4:
        raise RateTeamError(
            422, "Could not build a legal XI around the locked players "
                 "within the budget. Try locking fewer or cheaper players.")

    xi_xp = fitted["xi_xp"]
    horizon = int(xp_data["meta"].get("horizon_gw") or 6)

    free = free_optimum(pool, str(xp_data["meta"].get("generated_at")))
    optimal_xp = free["xi_xp"]
    # "Paras" saa esiintyä copyssa vain kun MOLEMMAT puolet vertailua ovat
    # todistettuja: väite koskee sekä lukittua runkoa että vertailukohtaa.
    proven = bool(fitted["proven"] and free["proven"])
    delta = round(xi_xp - optimal_xp, 2)
    squad_cost = sum(p["price"] for p in xi) + sum(p["price"] for p in bench)

    locked_names = ", ".join(p["web_name"] for p in locked)
    if delta >= -0.005:
        tail = ("the model's best budget XI" if proven
                else "the strongest budget XI the model found")
        message = (f"Locking {locked_names} costs nothing: this is "
                   f"{tail} over the next {horizon} GWs.")
    else:
        tail = ("the model's best free squad" if proven
                else "the strongest free squad the model found")
        message = (f"Fitting {locked_names} costs {abs(delta):.1f} xP over "
                   f"the next {horizon} GWs vs {tail}. "
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
            "optimal_proven": proven,
        },
        "message": message,
    }
