"""SPL xP — tuotanto-builderi: xP per pelaaja per GW → staattinen JSON (RSL Fantasy).

Tuottaa `data/spl_xp_projections.json`:n jonka `/api/fantasy/xp?league=spl`
tarjoilee. Sama serving-malli kuin FPL: EI on-request-laskentaa.

EROT FPL-BUILDERIIN (scripts/build_fpl_xp.py) — ja miksi:
  - Pelaajabaselinet: SPL:n element-summary tarjoilee vain KAUSIAGGREGAATIT
    (history_past; ei per-GW-rivejä, ei starts-kenttää) → vauhdit ja
    minuuttimalli rakennetaan aggregaateista (src/models/spl_xp.py).
    minutes_confidence on korkeintaan 'med' — per-GW-muotoa ei ole.
  - Pisteytys: RSL:n omat säännöt (spl_xp-vakiot), EI FPL-pisteitä.
  - Hyökkäysvauhdit TOTEUTUNEISTA maaleista/syötöistä (ei pelaaja-xG:tä
    SPL:lle) → data_basis kertoo tämän.
  - Joukkuekonteksti: SPL-DC (build_spl_phase0.fit_model, vendoroitu
    ESPN-historia) + fixture_contexts cfg=None (raaka DC).
  - Uudet pelaajat ilman RSL-historiaa (nousijaseurat + uudet hankinnat):
    hintajärjestyksen rooliprioris (FPL:ssä 4.8 MITATUT tierit 0.47/0.21/0.05
    — käytetään samoja; SPL-kalibrointia ei ole ennen kuin kausi tuottaa
    dataa, kirjattu meta.caveatiin).

Sanity-gate (fail-safe): FAIL → JSONia EI kirjoiteta, exit 2. EI auto-pushia.
Ajo:  python -m scripts.build_spl_xp
"""
from __future__ import annotations

import datetime as _dt
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import requests

import config
from scripts.build_spl_phase0 import (
    MODEL_TO_SHORT,
    REFERENCE_TRIO_SPL,
    SEASON_LABEL,
    SHORT_TO_MODEL,
    SPL_BASE,
    SPL_HEADERS,
    fetch_source,
    fit_model,
    short_name,
)
from src.models import spl_xp as xp
from src.models.fpl_context import fixture_contexts, neutral_lambda
from src.models.promoted_baseline import add_promoted_baseline

OUT_PATH = config.PROJECT_ROOT / "data" / "spl_xp_projections.json"
HORIZON_GW = 6
MIN_XP_TOTAL = 1.0

# Hintajärjestyksen roolipriorit pelaajille ilman RSL-historiaa — FPL:ssä
# 4.8.2026 mitatut tierit (backtest_preseason_price_prior.py::
# report_production_tiers, n=178). SPL-mittausta ei voi tehdä ennen kuin
# kausi tuottaa per-GW-dataa; tämä on paras saatavilla oleva estimaatti ja
# meta.caveat kertoo sen.
PRIOR_TIERS = (0.47, 0.21, 0.05)
PRIOR_SLOTS = {1: 1, 2: 4, 3: 4, 4: 2}   # tyypillinen XI


def fetch_bootstrap() -> dict:
    r = requests.get(f"{SPL_BASE}/bootstrap-static/", headers=SPL_HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()


def fetch_history_past(elements: list[dict]) -> dict[int, dict | None]:
    """Viimeisin history_past-kausirivi per pelaaja (element-summary).

    ~590 pyyntöä; kohtelias tahti. Epäonnistunut yksittäinen haku → None
    (pelaaja saa positiopriorin, ei kaadeta koko ajoa) — mutta jos yli 10 %
    hauista kaatuu, koko ajo keskeytyy (systeeminen vika, ei kohina).
    """
    out: dict[int, dict | None] = {}
    failed = 0
    for i, e in enumerate(elements):
        pid = e["id"]
        try:
            r = requests.get(f"{SPL_BASE}/element-summary/{pid}/",
                             headers=SPL_HEADERS, timeout=20)
            r.raise_for_status()
            hp = r.json().get("history_past") or []
            out[pid] = max(hp, key=lambda s: s.get("season_name") or "") if hp else None
        except Exception:
            failed += 1
            out[pid] = None
        if i % 100 == 99:
            print(f"      ... {i + 1}/{len(elements)} haettu ({failed} virhettä)")
        time.sleep(0.12)
    if failed > len(elements) * 0.10:
        raise SystemExit(f"element-summary: {failed}/{len(elements)} hakua "
                         "epäonnistui — systeeminen vika, keskeytetään.")
    return out


def price_tier_factor(rank_in_group: int, pos: int) -> float:
    """Hintajärjestyksen rooliprioritier klubi+positio-ryhmässä: position
    XI-slotit = tier 0 (0.47), 2 seuraavaa = tier 1 (0.21), loput 0.05 —
    sama jako jolla FPL-tierit mitattiin."""
    slots = PRIOR_SLOTS.get(pos, 4)
    if rank_in_group < slots:
        return PRIOR_TIERS[0]
    if rank_in_group < slots + 2:
        return PRIOR_TIERS[1]
    return PRIOR_TIERS[2]


def main() -> int:
    src = fetch_source()

    print("[2/6] SPL-pelaajadata (bootstrap + element-historiat, ~590 hakua)...")
    boot = fetch_bootstrap()
    elements = boot["elements"]
    teams_by_id = {t["id"]: t for t in boot["teams"]}
    history = fetch_history_past(elements)
    n_hist = sum(1 for v in history.values() if v)
    print(f"      {len(elements)} pelaajaa, {n_hist} RSL-kausihistorialla")

    print("[3/6] Sovitetaan SPL-DC + nousijabaseline...")
    dc, seasons = fit_model()
    fixture_teams = sorted({f["home"] for f in src["fixtures"]}
                           | {f["away"] for f in src["fixtures"]})
    missing = sorted(set(fixture_teams) - set(dc.attack))
    baseline = add_promoted_baseline(dc, missing, reference=REFERENCE_TRIO_SPL,
                                     allow_frozen=False)
    if missing and not baseline.get("trio_used"):
        print("VIRHE: nousijabaseline ei injektoitunut — keskeytetään.")
        return 1
    print(f"      {len(dc.teams_)} joukkuetta, baseline: {missing or '-'}")

    print("[4/6] Vauhdit + minuuttimalli (kausiaggregaatit)...")
    pos_by_player = {e["id"]: e["element_type"] for e in elements}
    acc_by_player = {e["id"]: xp.acc_from_history_past(history[e["id"]])
                     for e in elements}
    priors = xp.position_priors(acc_by_player, pos_by_player)

    mm_by_player: dict[int, dict] = {}
    for e in elements:
        pid = e["id"]
        mm = xp.minutes_model_from_aggregates(acc_by_player[pid]["mins"])
        av = xp.availability_factor(e.get("status", "a"),
                                    e.get("chance_of_playing_next_round"))
        mm_by_player[pid] = xp.scale_minutes(mm, av) if av < 1.0 else mm

    # Historiattomat: hintajärjestyksen roolipriori klubi+positio-ryhmässä
    # (vain heille — historiapohjaisiin arvioihin ei kosketa).
    groups: dict[tuple[int, int], list[dict]] = defaultdict(list)
    for e in elements:
        groups[(e["team"], e["element_type"])].append(e)
    n_prior = 0
    for (_t, _p), grp in groups.items():
        no_hist = [e for e in grp if acc_by_player[e["id"]]["mins"] <= 0
                   and mm_by_player[e["id"]]["p_start"] <= 0.0]
        no_hist.sort(key=lambda e: -(e.get("now_cost") or 0))
        for rank, e in enumerate(no_hist):
            av = xp.availability_factor(e.get("status", "a"),
                                        e.get("chance_of_playing_next_round"))
            p = price_tier_factor(rank, _p) * av
            base = xp.minutes_model_from_aggregates(0.0)
            mm_by_player[e["id"]] = xp.scale_minutes(
                {**base, "p_start": p, "p_cameo": min(0.25, 1.0 - p)}, 1.0)
            mm_by_player[e["id"]]["minutes_confidence"] = "low"
            n_prior += 1
    print(f"      roolipriorilla (ei historiaa): {n_prior} pelaajaa")

    # Syvyysnormalisointi: Σp_start klubi+positio-ryhmässä → XI-slotit.
    for (_t, pos), grp in groups.items():
        pids = [e["id"] for e in grp]
        f = xp.depth_factor([mm_by_player[p]["p_start"] for p in pids],
                            xp.XI_SLOTS.get(pos, 4.0))
        if f != 1.0:
            for p in pids:
                mm_by_player[p] = xp.scale_minutes(mm_by_player[p], f)

    print("[5/6] xP per pelaaja per GW...")
    upcoming = [f for f in src["fixtures"] if f["gameweek"] and not f["finished"]]
    next_gw = min((f["gameweek"] for f in upcoming), default=None)
    if next_gw is None:
        print("VIRHE: ei pelaamattomia fixtureita — ei kirjoiteta.")
        return 1
    horizon = list(range(next_gw, next_gw + HORIZON_GW))
    lam_avg = neutral_lambda(dc, fixture_teams)

    name_to_fid = {n: i + 1 for i, n in enumerate(fixture_teams)}
    fid_to_model = {v: k for k, v in name_to_fid.items()}
    ctx_by_gw: dict[int, dict[int, list[dict]]] = {}
    opp_by_gw: dict[int, dict[int, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for g in horizon:
        fxs = []
        for f in upcoming:
            if f["gameweek"] != g:
                continue
            h, a = f["home"], f["away"]
            fxs.append({"team_h": name_to_fid[h], "team_a": name_to_fid[a], "event": g})
            opp_by_gw[g][name_to_fid[h]].append({"opp": short_name(a), "venue": "H"})
            opp_by_gw[g][name_to_fid[a]].append({"opp": short_name(h), "venue": "A"})
        ctx_by_gw[g] = fixture_contexts(dc, fxs, fid_to_model, lam_avg, cfg=None)

    team_to_fid = {}
    for t in boot["teams"]:
        model = SHORT_TO_MODEL[t["short_name"]]
        if model in name_to_fid:
            team_to_fid[t["id"]] = name_to_fid[model]

    players_out = []
    for e in elements:
        pid = e["id"]
        pos = pos_by_player[pid]
        fid = team_to_fid.get(e["team"])
        if fid is None:
            continue
        acc = acc_by_player[pid]
        rates = xp.player_rates(acc, pos, priors)
        mm = mm_by_player[pid]
        gw_rows = []
        total = 0.0
        for g in horizon:
            ctxs = ctx_by_gw.get(g, {}).get(fid, [])
            gxp = 0.0
            for ctx in ctxs:
                gxp += xp.xp_components(pos, rates, mm["xmins"], mm["p60"],
                                        mm["p1_59"], ctx)["total"]
            total += gxp
            gw_rows.append({"gw": g, "opponents": opp_by_gw[g].get(fid, []),
                            "xp": round(gxp, 2)})
        if total < MIN_XP_TOTAL:
            continue
        neutral_ctx = {"goal_mult": 1.0, "opp_goal_mult": 1.0,
                       "cs_prob": float(np.mean([c["cs_prob"] for g in horizon
                                                 for c in ctx_by_gw.get(g, {}).get(fid, [])]
                                                or [0.0])),
                       "conceded_dist": [0.3, 0.35, 0.2, 0.1, 0.05]}
        hp = history[pid]
        model_team = SHORT_TO_MODEL[teams_by_id[e["team"]]["short_name"]]
        players_out.append({
            "id": pid,
            "web_name": e.get("web_name"),
            "full_name": f"{e.get('first_name', '')} {e.get('second_name', '')}".strip(),
            "team": model_team,
            "team_short": MODEL_TO_SHORT.get(model_team, "???"),
            "pos": {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}[pos],
            "price": (e.get("now_cost") or 0) / 10.0,
            "owned_pct": float(e.get("selected_by_percent") or 0.0),
            "status": e.get("status", "a"),
            "news": e.get("news") or "",
            "chance_next": e.get("chance_of_playing_next_round"),
            "yellows": int(acc["yc"]),
            "xmins": round(mm["xmins"], 1),
            "predicted_starts": round(mm["p_start"] * 100, 1),
            "minutes_confidence": mm["minutes_confidence"],
            "p_start": round(mm["p_start"], 4),
            "p_cameo": round(mm["p_cameo"], 4),
            "p_bench": round(mm["p_bench"], 4),
            "data_basis": "spl_history" if acc["mins"] > 0 else "no_history",
            "last_season": ({
                "season": (hp.get("season_name") or "").strip() or None,
                "league": "Saudi Pro League",
                "minutes": int(acc["mins"]),
                "goals": int(acc["goals"]),
                "assists": int(acc["assists"]),
                "cs": int(hp.get("clean_sheets") or 0),
                "points": int(hp.get("total_points") or 0),
                "per90": {
                    "goals": round(rates["goals90"], 2),
                    "assists": round(rates["assists90"], 2),
                },
            } if hp else None),
            "xp_per_gw": round(total / len(horizon), 2),
            "xp_per_90": round(xp.xp_full_90(pos, rates, neutral_ctx), 2),
            "xp_horizon_total": round(total, 2),
            "gameweeks": gw_rows,
        })
    players_out.sort(key=lambda p: -p["xp_horizon_total"])
    print(f"      pooliin {len(players_out)} pelaajaa (xP >= {MIN_XP_TOTAL})")

    # Sanity-gate ---------------------------------------------------------
    print("\n" + "=" * 64)
    print("SANITY-GATE (SPL-xP)")
    print("=" * 64)
    checks: list[tuple[str, bool]] = []
    checks.append(("pooli >= 250 pelaajaa", len(players_out) >= 250))
    top = players_out[0] if players_out else None
    if top:
        print(f"    kärki: {top['web_name']} ({top['team_short']}) "
              f"xP/GW {top['xp_per_gw']} xmins {top['xmins']}")
        checks.append(("kärjen xP/GW järkevällä välillä [3, 12]",
                       3.0 <= top["xp_per_gw"] <= 12.0))
        top_teams = {p["team_short"] for p in players_out[:10]}
        print(f"    top-10 joukkueet: {sorted(top_teams)}")
        checks.append(("top-10:ssä kärkiseuroja (HIL/NAS/ITT/AHL/QAD)",
                       bool(top_teams & {"HIL", "NAS", "ITT", "AHL", "QAD"})))
    by_pos = defaultdict(list)
    for p in players_out:
        by_pos[p["pos"]].append(p["xp_per_gw"])
    for posname in ("GKP", "DEF", "MID", "FWD"):
        checks.append((f"{posname}-pooli ei tyhjä", len(by_pos[posname]) > 0))
    nan_count = sum(1 for p in players_out
                    if not np.isfinite(p["xp_per_gw"]) or not np.isfinite(p["xp_per_90"]))
    checks.append(("ei NaN/inf-arvoja", nan_count == 0))
    ok = True
    for label, passed in checks:
        print(f"  [{'OK ' if passed else 'FAIL'}] {label}")
        ok = ok and passed
    print(f"\nGATE: {'PASS' if ok else 'FAIL'}")
    if not ok:
        print("SANITY-GATE FAIL — data/spl_xp_projections.json EI kirjoitettu.")
        return 2

    print("\n[6/6] Kirjoitetaan JSON...")
    out = {
        "meta": {
            "product": "GoalIQ SPL Fantasy — expected points (xP)",
            "available": True,
            "league": "SAU-Saudi Pro League",
            "generated_at": _dt.datetime.now().isoformat(timespec="seconds"),
            "season": SEASON_LABEL,
            "source": src["source"],
            "scoring": "RSL Fantasy rules (goals FWD/MID +5 DEF/GK +6, CS 5/4/1, "
                       "saves /2, micro-stats: tackles/def actions/shots/passes/big chances)",
            "team_strength_source": (
                f"GoalIQ Dixon-Coles, SPL results (ESPN) {seasons} — goals-based fit"
            ),
            "attack_basis": (
                "Realized goal/assist rates per 90 (shrunk to position priors). "
                "No free per-player xG feed exists for the SPL; this is NOT an "
                "xG-based projection and public copy must not claim it is."
            ),
            "minutes_basis": (
                "Season-aggregate minutes only (the RSL API has no per-round "
                "history or starts). Two-mode estimate (start ~86min / cameo "
                "~20min) + depth normalization to a typical XI; confidence is "
                "'med' at best. Players with no RSL history use price-order "
                "role priors measured on FPL data (0.47/0.21/0.05) — an "
                "uncalibrated transfer, stated here deliberately."
            ),
            "promoted_baseline_teams": missing,
            "sanity_gate": "PASS",
            "next_gameweek": next_gw,
            "deadline_utc": src["deadline_utc"],
            "horizon_gw": HORIZON_GW,
        },
        "players": players_out,
    }
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"      -> {OUT_PATH}  ({len(players_out)} pelaajaa)")
    print("\nEI auto-pushia. Deploy = Villen 🔒 GO.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
