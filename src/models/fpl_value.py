"""FPL value/consistency + GK rotation pairs (#114 = #107:n kohta 1).

Kaksi työkalua olemassa olevan datan päälle (EI uutta dataputkea):

  value_list        xP/£-ranking: xp_horizon_total / hinta(M£) + fixture-swing
                    (per-GW-xP:n keskihajonta). REHELLISYYS: swing mittaa
                    OTTELUOHJELMAN heiluntaa, ei pelaajan pistetuoton
                    stokastista varianssia (aito konsistenssi = V2, vaatisi
                    element-summary-historian). Caption kulkee payloadissa.

  gk_rotation_pairs Paras 2-vahdin rotaatio: per-GW max(CS%) kahdesta eri
                    seurasta (CS% jo fpl_projections_phase0:ssa), rankattu
                    keskiarvolla + yhteishinta. Starter-GK per seura =
                    korkein predicted_starts (fallback xmins).

Molemmat nojaavat fpl_rate_team.build_context()-pooliin (xP + bootstrap-
hinta/omistus jo joinattuna) → sama fail-safe: projektio puuttuu → 503
RateTeamError, ei kaatumista.
"""

from __future__ import annotations

from statistics import pstdev

from src.models.fpl_phase0 import load_phase0
from src.models.fpl_rate_team import POS_NAME, RateTeamError, build_context

# Fixture-swing-luokittelu (per-GW-xP:n keskihajonta, pisteissä). Rajat valittu
# nykyjakaumasta: mediaanipelaajan swing ~0.3-0.6, raskas DGW/kalenteriheilunta
# nostaa >1.0. Vain näyttölabel — raaka arvo kulkee aina mukana.
SWING_STEADY_MAX = 0.6
SWING_HIGH_MIN = 1.2

VALUE_NOTE = (
    "Value = model expected points over the horizon per million. Fixture swing "
    "= spread of per-gameweek xP (schedule volatility, not scoring variance). "
    "Powered by the match model behind our published track record."
)


def _fixture_swing(gameweeks: list[dict]) -> float:
    xs = [float(g["xp"]) for g in (gameweeks or []) if g.get("xp") is not None]
    if len(xs) < 2:
        return 0.0
    return round(pstdev(xs), 3)


def _swing_label(swing: float) -> str:
    if swing <= SWING_STEADY_MAX:
        return "steady"
    if swing >= SWING_HIGH_MIN:
        return "swingy"
    return "moderate"


def value_list(top_n: int = 20) -> dict:
    """xP/£-ranking koko poolista. Nostaa RateTeamErrorin jos projektio puuttuu."""
    xp_data, _bootstrap, pool, _by_id = build_context()
    meta = xp_data.get("meta", {})

    rows = []
    for p in pool:
        price_m = p["price"] / 10.0
        if price_m <= 0:
            continue
        swing = _fixture_swing(p.get("gameweeks"))
        rows.append({
            "id": p["id"],
            "web_name": p["web_name"],
            "team_short": p["team_short"],
            "pos": POS_NAME.get(p["element_type"], "?"),
            "price": round(price_m, 1),
            "owned_pct": p["owned_pct"],
            "xp_horizon_total": round(p["xp_horizon_total"], 2),
            "value": round(p["xp_horizon_total"] / price_m, 3),
            "fixture_swing": swing,
            "swing_label": _swing_label(swing),
        })
    rows.sort(key=lambda r: r["value"], reverse=True)

    return {
        "meta": {
            "available": True,
            "season": meta.get("season"),
            "gw": meta.get("next_gameweek"),
            "horizon_gw": meta.get("horizon_gw"),
            "generated_at": meta.get("generated_at"),
            "note": VALUE_NOTE,
        },
        "players": rows[:top_n],
    }


def _starter_gk_by_club(pool: list[dict]) -> dict[str, dict]:
    """Todennäköisin ykkösvahti per seura (team_short): korkein
    predicted_starts, tasatilanteessa xmins."""
    best: dict[str, dict] = {}
    for p in pool:
        if p["element_type"] != 1:
            continue
        key = p["team_short"]
        cur = best.get(key)
        rank = (float(p.get("predicted_starts") or 0.0), float(p.get("xmins") or 0.0))
        if cur is None or rank > cur["_rank"]:
            best[key] = {**p, "_rank": rank}
    return best


def gk_rotation_pairs(top_n: int = 10) -> dict:
    """Paras 2-vahdin pari: per-GW max(CS%) kahdesta eri seurasta.

    Nostaa RateTeamErrorin jos xP-pooli puuttuu; CS-data puuttuu →
    available=False-runko (ei kaatumista).
    """
    _xp, _boot, pool, _ = build_context()
    phase0 = load_phase0()
    p0_meta = phase0.get("meta", {})
    if not p0_meta.get("available") or not phase0.get("teams"):
        return {"meta": {"available": False,
                         "note": "Clean sheet projections are not available yet."},
                "pairs": []}

    # CS% per seura per GW (short-koodi = join-avain xP-pooliin)
    cs_by_short: dict[str, dict[int, float]] = {}
    for t in phase0["teams"]:
        short = t.get("short")
        if not short:
            continue
        cs_by_short[short] = {
            f["gw"]: float(f["cs_pct"]) for f in (t.get("fixtures") or [])
            if f.get("gw") is not None and f.get("cs_pct") is not None
        }

    gks = _starter_gk_by_club(pool)
    shorts = sorted(s for s in gks if s in cs_by_short)

    pairs = []
    for i, a in enumerate(shorts):
        for b in shorts[i + 1:]:
            common = sorted(set(cs_by_short[a]) & set(cs_by_short[b]))
            if not common:
                continue
            split = []
            for gw in common:
                ca, cb = cs_by_short[a][gw], cs_by_short[b][gw]
                pick = a if ca >= cb else b
                split.append({"gw": gw, "team_short": pick,
                              "cs_pct": round(max(ca, cb), 1)})
            avg_best = sum(s["cs_pct"] for s in split) / len(split)
            ga, gb = gks[a], gks[b]
            pairs.append({
                "avg_best_cs_pct": round(avg_best, 1),
                "combined_price": round((ga["price"] + gb["price"]) / 10.0, 1),
                "gk_a": {"id": ga["id"], "web_name": ga["web_name"],
                         "team_short": a, "price": round(ga["price"] / 10.0, 1)},
                "gk_b": {"id": gb["id"], "web_name": gb["web_name"],
                         "team_short": b, "price": round(gb["price"] / 10.0, 1)},
                "gw_split": split,
            })
    # Paras rotaatio ensin; sama CS% → halvempi pari voittaa
    pairs.sort(key=lambda r: (-r["avg_best_cs_pct"], r["combined_price"]))

    return {
        "meta": {
            "available": True,
            "gw": p0_meta.get("next_gameweek"),
            "horizon_gw": p0_meta.get("horizon_gw"),
            "note": ("Best rotating goalkeeper duo: each gameweek you field the "
                     "keeper with the higher model clean sheet probability."),
        },
        "pairs": pairs[:top_n],
    }


def value_and_gk(top_n_value: int = 20, top_n_pairs: int = 10) -> dict:
    """Yhdistetty payload /api/fantasy/value-endpointille (yksi kutsu, yksi
    build_context-lataus molemmille osille)."""
    value = value_list(top_n=top_n_value)
    try:
        gk = gk_rotation_pairs(top_n=top_n_pairs)
    except RateTeamError:
        gk = {"meta": {"available": False, "note": "GK data unavailable."},
              "pairs": []}
    return {"meta": value["meta"], "players": value["players"], "gk": gk}
