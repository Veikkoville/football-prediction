# -*- coding: utf-8 -*-
"""Kausihorisontin backtest: kestaako PITKAN horisontin summa? (4.8.2026)

Miksi tama on olemassa: kilpailijat (FFScout ym.) julkaisevat koko kauden
projisoidut pisteet, maalit ja syotot. Kysymys ei ole "osaammeko laskea" -
malli laskee maalit ja syotot jo nyt, ne ovat xP:n sisalla - vaan "pitaako
luku 38 kierroksen paassa". Tuotannon HORIZON_GW on 6, ja ennen kuin sita
nostetaan, degradaatio on mitattava.

MIKSI TAMA EIKA ESIKAUSIPROJEKTION EMULOINTI: uskollinen esikausiajo vaatisi
edellisen kauden PELAAJAKOHTAISET xG/xA-luvut. FPL:n history_past antaa vain
toteutuneet maalit ja syotot (ei xG), ja tuotanto nojaa nimenomaan xG-pohjaisiin
vauhteihin - eli emulointi mittaisi ERI MALLIA kuin se joka shipataan. Siksi
mitataan sama rakenteellinen kysymys datalla joka on: jaadyta mallin tila
kierroksella C ja projisoi C..38 yhtena summana.

MITA TAMA EI KERRO: esikausiprojektio on TATA HUONOMPI, koska silla ei ole
yhtaan kuluvan kauden minuuttihavaintoa. Talla saadaan siis YLARAJA sille
kuinka hyva koko kauden luku voi olla. Jos luku ei kesta tassa, se ei kesta
esikaudellakaan.

Menetelma per cutoff C:
  - DC-fit otteluista joiden paiva < GW C:n 1. kickoff (walk-forward-laillinen)
  - pelaajavauhdit + minuuttimuoto kierroksilta < C, JAADYTETTY
  - projisoi jokainen GW C..38 samalla jaadytetylla tilalla, summaa
  - vertaa toteutuneisiin pisteisiin ja maaleihin samalla valilla

Baseline: pelaajan toteutunut pistekeskiarvo kierroksilta < C x jaljella
olevien fixtureiden maara. Sama idea kuin walk-forward-backtestin form5, mutta
koko jaljella olevalle kaudelle - eli "oleta etta jatkat kuten tahan asti".

Ajo:  python -m scripts.backtest_fpl_season_horizon
      python -m scripts.backtest_fpl_season_horizon --cutoffs 6,15,25
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
from scipy.stats import spearmanr

import config
from scripts.backtest_fpl_xp import _load_archive_2526, build_structures
from scripts.build_fpl_phase0 import FIT_BAYES, FIT_DECAY, add_promoted_baseline
from src.data import fpl_api
from src.data.loader import lataa_otteludata
from src.models import fpl_xp as xp
from src.models.dixon_coles import DixonColesModel
from src.models.fpl_context import build_context, fixture_contexts, neutral_lambda, promoted_teams

POS_NAME = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}


def _bias(pred: float, act: float) -> float:
    return (pred - act) / act * 100.0 if act else float("nan")


def _rho(a: list[float], b: list[float]) -> float:
    if len(a) < 3:
        return float("nan")
    r = spearmanr(a, b).correlation
    return float(r) if r == r else float("nan")


def project_from_cutoff(cutoff_gw: int, data: dict) -> list[dict]:
    """Jaadyta malli kierroksella cutoff_gw ja projisoi loppukausi."""
    (boot, fixtures, tid_to_model, pos_by_player, team_by_player,
     fixtures_by_event, team_rounds, rows_by_round, mins_by_round,
     pts_by_round, matches, ctx_cfg, fpl_team_names) = (
        data["boot"], data["fixtures"], data["tid_to_model"],
        data["pos_by_player"], data["team_by_player"], data["fixtures_by_event"],
        data["team_rounds"], data["rows_by_round"], data["mins_by_round"],
        data["pts_by_round"], data["matches"], data["ctx_cfg"],
        data["fpl_team_names"])

    events = sorted(fixtures_by_event)
    future = [g for g in events if g >= cutoff_gw]

    # --- 1. DC-fit VAIN cutoffia edeltavasta datasta -----------------------
    kickoffs = [fpl_api.parse_kickoff(f.get("kickoff_time"))
                for f in fixtures_by_event[cutoff_gw]]
    kickoffs = [k for k in kickoffs if k]
    cut_dt = min(kickoffs).replace(tzinfo=None)
    sub = matches[matches["date"] < cut_dt]
    dc = DixonColesModel(per_team_home_adv=True).fit(
        sub, home_team_col="home_team", away_team_col="away_team",
        home_goals_col="home_score", away_goals_col="away_score",
        decay=FIT_DECAY, date_col="date", l2_attack_defence=FIT_BAYES)
    missing = sorted(set(fpl_team_names) - set(dc.attack))
    if missing:
        add_promoted_baseline(dc, missing)
    lam_avg = neutral_lambda(dc, fpl_team_names)

    # --- 2. Pelaajatila JAADYTETAAN kierroksille < cutoff ------------------
    acc_by_player: dict[int, dict] = {}
    for pid, rr in rows_by_round.items():
        before = [r for rnd, rows in rr.items() if rnd < cutoff_gw for r in rows]
        acc = xp.accumulate_history(before)
        acc["dc_hits"] = xp.count_dc_hits(before, pos_by_player[pid])
        acc_by_player[pid] = acc
    priors = xp.position_priors(acc_by_player, pos_by_player)

    # --- 3. Kontekstit jokaiselle tulevalle GW:lle, SAMA jaadytetty dc ------
    ctx_by_gw = {g: fixture_contexts(dc, fixtures_by_event[g], tid_to_model,
                                     lam_avg, cfg=ctx_cfg) for g in future}

    rows = []
    for pid, rr in rows_by_round.items():
        tid = team_by_player[pid]
        pos = pos_by_player[pid]
        trounds_before = [r for r in team_rounds[tid] if r < cutoff_gw]
        if not trounds_before:
            continue
        rates = xp.player_rates(acc_by_player[pid], pos, priors)
        xmins, p60, p1_59 = xp.minutes_form(mins_by_round[pid], trounds_before)

        pred_pts = 0.0
        pred_goals = 0.0
        n_fix = 0
        for g in future:
            ctxs = ctx_by_gw[g].get(tid, [])
            if not ctxs:
                continue
            n_fix += len(ctxs)
            for c in ctxs:
                comp = xp.xp_components(pos, rates, xmins, p60, p1_59, c)
                pred_pts += comp["total"]
                pred_goals += comp["goals"] / xp.GOAL_PTS[pos]
        if n_fix == 0:
            continue

        act_pts = sum(pts_by_round[pid].get(g, 0.0) for g in future)
        act_goals = 0
        act_mins = 0.0
        for g in future:
            for r in rr.get(g, []):
                act_goals += (r.get("goals_scored") or 0)
                act_mins += (r.get("minutes") or 0)

        # Baseline: "jatka kuten tahan asti" - pisteet per kierros x jaljella
        played_before = [r for r in trounds_before if mins_by_round[pid].get(r, 0) > 0]
        ppg = (float(np.mean([pts_by_round[pid].get(r, 0.0) for r in played_before]))
               if played_before else 0.0)
        base_pts = ppg * n_fix

        rows.append({
            "pid": pid, "pos": pos, "n_fix": n_fix,
            "pred_pts": pred_pts, "base_pts": base_pts, "act_pts": act_pts,
            "pred_goals": pred_goals, "act_goals": act_goals,
            "act_mins": act_mins,
            "mins_before": sum(mins_by_round[pid].get(r, 0.0) for r in trounds_before),
        })
    return rows


def report(cutoff: int, rows: list[dict], last_gw: int) -> None:
    horizon = last_gw - cutoff + 1
    print("\n" + "=" * 74)
    print(f"CUTOFF GW{cutoff}  ->  projisoidaan GW{cutoff}-{last_gw} "
          f"({horizon} kierrosta) yhtena summana")
    print("=" * 74)

    pops = {
        "kaikki rekisteroidyt": rows,
        "pelasi >= 1 min ikkunassa": [r for r in rows if r["act_mins"] > 0],
        "vakiokalusto (>=450 min ennen)": [r for r in rows if r["mins_before"] >= 450],
    }
    for tag, pop in pops.items():
        if not pop:
            continue
        p = sum(r["pred_pts"] for r in pop)
        b = sum(r["base_pts"] for r in pop)
        a = sum(r["act_pts"] for r in pop)
        mae_x = float(np.mean([abs(r["pred_pts"] - r["act_pts"]) for r in pop]))
        mae_b = float(np.mean([abs(r["base_pts"] - r["act_pts"]) for r in pop]))
        rx = _rho([r["pred_pts"] for r in pop], [r["act_pts"] for r in pop])
        rb = _rho([r["base_pts"] for r in pop], [r["act_pts"] for r in pop])
        print(f"\n  {tag}  (n={len(pop)})")
        print(f"    PISTEET summa   malli {p:9.0f}   baseline {b:9.0f}   "
              f"toteutunut {a:9.0f}")
        print(f"    bias            malli {_bias(p, a):+7.1f} %          "
              f"baseline {_bias(b, a):+7.1f} %")
        print(f"    MAE per pelaaja malli {mae_x:9.1f}   baseline {mae_b:9.1f}   "
              f"({'malli parempi' if mae_x < mae_b else 'BASELINE PAREMPI'})")
        print(f"    Spearman        malli {rx:9.3f}   baseline {rb:9.3f}")

    print("\n  MAALIT per positio (populaatio: pelasi >= 1 min ikkunassa)")
    played = [r for r in rows if r["act_mins"] > 0]
    for pos in (2, 3, 4):
        sel = [r for r in played if r["pos"] == pos]
        if not sel:
            continue
        pg = sum(r["pred_goals"] for r in sel)
        ag = sum(r["act_goals"] for r in sel)
        rg = _rho([r["pred_goals"] for r in sel], [float(r["act_goals"]) for r in sel])
        print(f"    {POS_NAME[pos]}  odotus {pg:7.1f}  toteutunut {ag:5d}  "
              f"bias {_bias(pg, ag):+6.1f} %   rho {rg:+.3f}  (n={len(sel)})")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cutoffs", default="6,15,25",
                    help="pilkulla erotellut cutoff-GW:t (oletus 6,15,25)")
    args = ap.parse_args()

    print("[1/3] Ladataan 25/26-levyarkisto (elava API on jo 26/27)...")
    boot, fixtures, summaries, season_key = _load_archive_2526()
    summaries = xp.adjust_summaries_bps_2627(summaries)
    (tid_to_model, pos_by_player, team_by_player, name_by_player,
     fixtures_by_event, team_rounds, rows_by_round, mins_by_round,
     pts_by_round) = build_structures(boot, fixtures, summaries)
    print(f"      kausi {season_key}: {len(boot['elements'])} pelaajaa, "
          f"{len(fixtures)} fixturea, bonus oikaistu 26/27 BPS:aan")

    print("[2/3] PL-otteludata DC-mallia varten...")
    matches = lataa_otteludata(["ENG-Premier League"], config.current_season_pair())
    if matches.empty:
        raise SystemExit("PL-otteludata tyhja.")
    fpl_team_names = [tid_to_model[t["id"]] for t in boot["teams"]]
    seasons_str = matches["season"].astype(str)
    promoted = promoted_teams(
        set(matches[seasons_str == max(seasons_str.unique())]["home_team"]),
        set(matches[seasons_str == min(seasons_str.unique())]["home_team"]))
    model_fixtures = [{"gameweek": f.get("event"),
                       "home": tid_to_model.get(f["team_h"]),
                       "away": tid_to_model.get(f["team_a"])}
                      for f in fixtures if f.get("event")]
    ctx_cfg = build_context(promoted, model_fixtures)
    print(f"      {len(matches)} ottelua, kontekstikerros PAALLA")

    data = dict(boot=boot, fixtures=fixtures, tid_to_model=tid_to_model,
                pos_by_player=pos_by_player, team_by_player=team_by_player,
                fixtures_by_event=fixtures_by_event, team_rounds=team_rounds,
                rows_by_round=rows_by_round, mins_by_round=mins_by_round,
                pts_by_round=pts_by_round, matches=matches, ctx_cfg=ctx_cfg,
                fpl_team_names=fpl_team_names)

    last_gw = max(fixtures_by_event)
    print(f"[3/3] Projisoidaan cutoffeista {args.cutoffs} kierrokseen {last_gw}...")
    for c in [int(x) for x in args.cutoffs.split(",")]:
        rows = project_from_cutoff(c, data)
        report(c, rows, last_gw)

    print("\n" + "=" * 74)
    print("TULKINTA: jos bias kasvaa horisontin myota ja/tai baseline ohittaa")
    print("mallin, koko kauden luku ei ole julkaisukelpoinen sellaisenaan.")
    print("Esikausiprojektio on TATA HUONOMPI (ei yhtaan kuluvan kauden")
    print("minuuttihavaintoa), joten tama on ylaraja eika arvio.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
