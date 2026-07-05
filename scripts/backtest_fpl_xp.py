"""FPL Phase 1 xP — walk-forward-backtest valmiilla 25/26-kaudella (SHIP-GATE).

Laskee xP:n jokaiselle kauden GW:lle käyttäen VAIN GW:tä edeltävää dataa:
  - pelaajavauhdit: FPL-API:n per-GW-historia kierroksilta < GW
  - joukkuekonteksti: Dixon-Coles sovitettuna otteluihin joiden päivä < GW:n
    ensimmäinen kickoff (sama fit-config kuin tuotannon /api/predict)
ja vertaa toteutuneisiin FPL-pisteisiin.

Baseline: FPL:n historiallista ep_next:iä EI ole saatavilla (kenttä on
live-only, API ei arkistoi sitä) → promptin mukainen fallback = form-baseline
(viimeisten 5 joukkuekierroksen pistekeskiarvo). Tämä on sama signaali josta
FPL:n oma "form"/ep_next johdetaan.

🔒 SHIP-GATE: xP:n MAE pienempi JA Spearman korkeampi kuin baseline
(vähintään toinen selkeästi parempi, ei kumpikaan huonompi) pelanneiden
populaatiossa GW2-38. Tulos + per-positio-erittely raportoidaan; FAIL →
xP:tä EI julkaista.

Ajo:  python -m scripts.backtest_fpl_xp          (välimuisti data/raw/fpl/)
      python -m scripts.backtest_fpl_xp --refresh  (pakota FPL-haku uusiksi)
Raportti: logs/fpl_xp_backtest_<pvm>.json (gitignored) + stdout-taulukko.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
from scipy.stats import spearmanr

import config
from scripts.build_fpl_phase0 import FIT_BAYES, FIT_DECAY, add_promoted_baseline, map_name
from src.data import fpl_api
from src.data.loader import lataa_otteludata
from src.models import fpl_xp as xp
from src.models.dixon_coles import DixonColesModel

FORM_WINDOW = 5          # baseline: viim. 5 joukkuekierroksen pistekeskiarvo
GW_FIRST_EVAL = 2        # GW1:lle ei ole kummallakaan menetelmällä dataa
LATE_SEASON_FROM = 7     # lisäraportti: vakiintunut kausi (molemmilla >=6 GW dataa)


# ---------------------------------------------------------------------------
# Datarakenteet
# ---------------------------------------------------------------------------
def build_structures(boot: dict, fixtures: list, summaries: dict[int, list[dict]]):
    tid_to_model = {t["id"]: map_name(t["name"]) for t in boot["teams"]}
    pos_by_player = {e["id"]: e["element_type"] for e in boot["elements"]}
    team_by_player = {e["id"]: e["team"] for e in boot["elements"]}
    name_by_player = {e["id"]: e["web_name"] for e in boot["elements"]}

    fixtures_by_event: dict[int, list[dict]] = defaultdict(list)
    team_rounds: dict[int, list[int]] = defaultdict(list)
    for f in fixtures:
        ev = f.get("event")
        if ev is None:
            continue
        fixtures_by_event[ev].append(f)
        for tid in (f["team_h"], f["team_a"]):
            if ev not in team_rounds[tid]:
                team_rounds[tid].append(ev)
    for tid in team_rounds:
        team_rounds[tid].sort()

    # Per pelaaja: rivit ja minuutit/pisteet kierroksittain
    rows_by_round: dict[int, dict[int, list[dict]]] = {}
    mins_by_round: dict[int, dict[int, float]] = {}
    pts_by_round: dict[int, dict[int, float]] = {}
    for pid, hist in summaries.items():
        rr: dict[int, list[dict]] = defaultdict(list)
        for r in hist:
            rnd = r.get("round")
            if rnd is not None:
                rr[rnd].append(r)
        rows_by_round[pid] = dict(rr)
        mins_by_round[pid] = {rnd: sum((x.get("minutes") or 0) for x in rows)
                              for rnd, rows in rr.items()}
        pts_by_round[pid] = {rnd: sum((x.get("total_points") or 0) for x in rows)
                             for rnd, rows in rr.items()}
    return (tid_to_model, pos_by_player, team_by_player, name_by_player,
            fixtures_by_event, team_rounds, rows_by_round, mins_by_round, pts_by_round)


def neutral_lambda(dc: DixonColesModel, teams: list[str]) -> dict[str, float]:
    """Joukkueen neutraali maaliodotus: keskiarvo koti+vieras kaikkia muita
    kauden joukkueita vastaan. Kerroin goal_mult = fixture-λ / tämä."""
    out = {}
    for t in teams:
        vals = []
        for o in teams:
            if o == t:
                continue
            lam_h, _ = dc.expected_goals(t, o)
            _, mu_a = dc.expected_goals(o, t)
            vals.extend([lam_h, mu_a])
        out[t] = float(np.mean(vals)) if vals else 1.0
    return out


def fixture_contexts(dc: DixonColesModel, fxs: list[dict],
                     tid_to_model: dict[int, str],
                     lam_avg: dict[str, float]) -> dict[int, list[dict]]:
    """Per joukkue-id: lista fixture-konteksteja (DGW:ssä useampi)."""
    ctx_by_team: dict[int, list[dict]] = defaultdict(list)
    for f in fxs:
        h = tid_to_model.get(f["team_h"])
        a = tid_to_model.get(f["team_a"])
        if h not in dc.attack or a not in dc.attack:
            continue
        lam, mu = dc.expected_goals(h, a)
        m = dc.score_matrix(h, a)
        home_goals_dist = m.sum(axis=1)   # P(koti tekee i)
        away_goals_dist = m.sum(axis=0)   # P(vieras tekee j)
        ctx_by_team[f["team_h"]].append({
            "goal_mult": lam / max(lam_avg.get(h, 1.0), 1e-9),
            "cs_prob": float(m[:, 0].sum()),
            "conceded_dist": [float(p) for p in away_goals_dist],
            "opp_goal_mult": mu / max(lam_avg.get(a, 1.0), 1e-9),
        })
        ctx_by_team[f["team_a"]].append({
            "goal_mult": mu / max(lam_avg.get(a, 1.0), 1e-9),
            "cs_prob": float(m[0, :].sum()),
            "conceded_dist": [float(p) for p in home_goals_dist],
            "opp_goal_mult": lam / max(lam_avg.get(h, 1.0), 1e-9),
        })
    return ctx_by_team


# ---------------------------------------------------------------------------
# Metriikat
# ---------------------------------------------------------------------------
def mae(pred: list[float], actual: list[float]) -> float:
    return float(np.mean(np.abs(np.array(pred) - np.array(actual))))


def rho(pred: list[float], actual: list[float]) -> float:
    if len(pred) < 3 or len(set(actual)) < 2 or len(set(pred)) < 2:
        return float("nan")
    r = spearmanr(pred, actual).statistic
    return float(r)


# ---------------------------------------------------------------------------
# Backtest
# ---------------------------------------------------------------------------
def run_backtest(force_refresh: bool = False) -> dict:
    print("[1/4] FPL-data (bootstrap + fixtures + 841 element-historiaa)...")
    boot = fpl_api.fetch_bootstrap(force=force_refresh)
    fixtures = fpl_api.fetch_fixtures(force=force_refresh)
    season_key = fpl_api.season_key_from_bootstrap(boot)
    summaries = fpl_api.fetch_all_summaries(boot, force=force_refresh)
    print(f"      kausi {season_key}: {len(boot['elements'])} pelaajaa, "
          f"{len(fixtures)} fixturea")

    (tid_to_model, pos_by_player, team_by_player, name_by_player,
     fixtures_by_event, team_rounds, rows_by_round, mins_by_round,
     pts_by_round) = build_structures(boot, fixtures, summaries)

    print("[2/4] PL-otteludata DC-mallia varten (Understat, sama lähde kuin tuotanto)...")
    seasons = config.current_season_pair()
    matches = lataa_otteludata(["ENG-Premier League"], seasons)
    if matches.empty:
        raise SystemExit("PL-otteludata tyhjä — backtest ei voi ajaa.")
    print(f"      {len(matches)} ottelua (kaudet {seasons})")

    events = sorted(fixtures_by_event)
    fpl_team_names = [tid_to_model[t["id"]] for t in boot["teams"]]

    per_gw: list[dict] = []
    obs_rows: list[dict] = []  # per pelaaja-GW: diagnoosiin

    print(f"[3/4] Walk-forward GW{GW_FIRST_EVAL}-{max(events)} "
          f"(DC-fit per GW, vain edeltävä data)...")
    for g in events:
        if g < GW_FIRST_EVAL:
            continue
        fxs = fixtures_by_event[g]
        kickoffs = [fpl_api.parse_kickoff(f.get("kickoff_time")) for f in fxs]
        kickoffs = [k for k in kickoffs if k]
        if not kickoffs:
            continue
        cutoff = min(kickoffs).replace(tzinfo=None)

        sub = matches[matches["date"] < cutoff]
        dc = DixonColesModel(per_team_home_adv=True).fit(
            sub, home_team_col="home_team", away_team_col="away_team",
            home_goals_col="home_score", away_goals_col="away_score",
            decay=FIT_DECAY, date_col="date", l2_attack_defence=FIT_BAYES)
        missing = sorted(set(fpl_team_names) - set(dc.attack))
        if missing:
            add_promoted_baseline(dc, missing)
        lam_avg = neutral_lambda(dc, fpl_team_names)
        ctx_by_team = fixture_contexts(dc, fxs, tid_to_model, lam_avg)

        # Kumulatiiviset accit + positiopriorit kierroksilta < g
        acc_by_player: dict[int, dict] = {}
        for pid, rr in rows_by_round.items():
            before = [r for rnd, rows in rr.items() if rnd < g for r in rows]
            acc = xp.accumulate_history(before)
            acc["dc_hits"] = xp.count_dc_hits(before, pos_by_player[pid])
            acc_by_player[pid] = acc
        priors = xp.position_priors(acc_by_player, pos_by_player)

        gw_pred_xp, gw_pred_base, gw_actual, gw_played, gw_pos = [], [], [], [], []
        for pid, rr in rows_by_round.items():
            if g not in rr:
                continue  # ei rekisteröitynä tälle GW:lle
            tid = team_by_player[pid]
            ctxs = ctx_by_team.get(tid, [])
            if not ctxs:
                continue
            pos = pos_by_player[pid]
            rates = xp.player_rates(acc_by_player[pid], pos, priors)
            trounds = [r for r in team_rounds[tid] if r < g]
            xmins, p60, p1_59 = xp.minutes_form(mins_by_round[pid], trounds)
            pred = sum(
                xp.xp_components(pos, rates, xmins, p60, p1_59, c)["total"]
                for c in ctxs)

            form_rounds = trounds[-FORM_WINDOW:]
            base = (float(np.mean([pts_by_round[pid].get(r, 0.0) for r in form_rounds]))
                    if form_rounds else 0.0)
            # DGW: baseline on per kierros -> skaalaa fixtureiden määrällä
            base *= len(ctxs)

            actual = pts_by_round[pid][g]
            played = mins_by_round[pid][g] > 0
            gw_pred_xp.append(pred)
            gw_pred_base.append(base)
            gw_actual.append(actual)
            gw_played.append(played)
            gw_pos.append(pos)
            obs_rows.append({"gw": g, "pid": pid, "pos": pos, "pred": pred,
                             "base": base, "actual": actual, "played": played})

        idx_played = [i for i, p in enumerate(gw_played) if p]
        entry = {"gw": g, "n_all": len(gw_actual), "n_played": len(idx_played)}
        for tag, idx in (("all", range(len(gw_actual))), ("played", idx_played)):
            xs = [gw_pred_xp[i] for i in idx]
            bs = [gw_pred_base[i] for i in idx]
            ys = [gw_actual[i] for i in idx]
            if len(ys) >= 3:
                entry[f"{tag}_mae_xp"] = mae(xs, ys)
                entry[f"{tag}_mae_base"] = mae(bs, ys)
                entry[f"{tag}_rho_xp"] = rho(xs, ys)
                entry[f"{tag}_rho_base"] = rho(bs, ys)
        per_gw.append(entry)
        if g % 5 == 0 or g == max(events):
            print(f"      GW{g}: n={entry['n_played']} pelannutta, "
                  f"MAE xp={entry.get('played_mae_xp', float('nan')):.3f} "
                  f"base={entry.get('played_mae_base', float('nan')):.3f}")

    print("[4/4] Aggregointi + ship-gate...")
    return aggregate_and_gate(per_gw, obs_rows, season_key)


def _agg(per_gw: list[dict], tag: str, gw_from: int, gw_to: int) -> dict:
    sel = [e for e in per_gw if gw_from <= e["gw"] <= gw_to and f"{tag}_mae_xp" in e]
    if not sel:
        return {}
    def m(key):
        vals = [e[key] for e in sel if not np.isnan(e[key])]
        return float(np.mean(vals)) if vals else float("nan")
    return {
        "gw_range": f"{gw_from}-{gw_to}", "n_gws": len(sel),
        "mae_xp": m(f"{tag}_mae_xp"), "mae_base": m(f"{tag}_mae_base"),
        "rho_xp": m(f"{tag}_rho_xp"), "rho_base": m(f"{tag}_rho_base"),
    }


def aggregate_and_gate(per_gw: list[dict], obs_rows: list[dict],
                       season_key: str) -> dict:
    gw_max = max(e["gw"] for e in per_gw)
    agg = {
        "played_full": _agg(per_gw, "played", GW_FIRST_EVAL, gw_max),
        "played_late": _agg(per_gw, "played", LATE_SEASON_FROM, gw_max),
        "all_full": _agg(per_gw, "all", GW_FIRST_EVAL, gw_max),
        "all_late": _agg(per_gw, "all", LATE_SEASON_FROM, gw_max),
    }

    # Per positio (pelanneet, koko kausi) — diagnoosi promptin §4 mukaan
    by_pos = {}
    for pos, pname in xp.POS_NAME.items():
        sel = [o for o in obs_rows if o["pos"] == pos and o["played"]]
        if len(sel) < 10:
            continue
        preds = [o["pred"] for o in sel]
        bases = [o["base"] for o in sel]
        ys = [o["actual"] for o in sel]
        by_pos[pname] = {
            "n": len(sel),
            "mae_xp": mae(preds, ys), "mae_base": mae(bases, ys),
            "rho_xp": rho(preds, ys), "rho_base": rho(bases, ys),
        }

    # 🔒 SHIP-GATE: pelanneet, koko arviointiväli. Ei kumpikaan huonompi,
    # vähintään toinen selkeästi parempi (MAE -2 % tai Spearman +0.02).
    p = agg["played_full"]
    mae_ok = p["mae_xp"] <= p["mae_base"]
    rho_ok = p["rho_xp"] >= p["rho_base"]
    mae_clear = p["mae_xp"] <= p["mae_base"] * 0.98
    rho_clear = p["rho_xp"] >= p["rho_base"] + 0.02
    gate_pass = mae_ok and rho_ok and (mae_clear or rho_clear)

    report = {
        "generated_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "season": season_key,
        "baseline": (f"form{FORM_WINDOW} (viim. {FORM_WINDOW} joukkuekierroksen "
                     "pistekeskiarvo; FPL:n historiallista ep_next:iä ei ole "
                     "API:ssa saatavilla)"),
        "gate": {
            "population": "pelanneet (minuutit > 0)",
            "criteria": "MAE <= baseline JA Spearman >= baseline, väh. toinen selkeästi parempi",
            "mae_not_worse": mae_ok, "rho_not_worse": rho_ok,
            "mae_clearly_better": mae_clear, "rho_clearly_better": rho_clear,
            "PASS": gate_pass,
        },
        "aggregates": agg,
        "by_position": by_pos,
        "per_gw": per_gw,
    }

    print("\n" + "=" * 72)
    print(f"SHIP-GATE — xP vs form{FORM_WINDOW}-baseline, kausi {season_key}, "
          f"walk-forward GW{GW_FIRST_EVAL}-{gw_max}")
    print("=" * 72)
    for label, a in (("Pelanneet, koko kausi (GATE)", agg["played_full"]),
                     (f"Pelanneet, GW{LATE_SEASON_FROM}+", agg["played_late"]),
                     ("Kaikki rekisteröidyt, koko kausi", agg["all_full"])):
        if not a:
            continue
        print(f"  {label}:")
        print(f"      MAE  xP {a['mae_xp']:.4f}  vs  baseline {a['mae_base']:.4f}"
              f"   ({(a['mae_base'] - a['mae_xp']) / a['mae_base'] * 100:+.1f} %)")
        print(f"      rho  xP {a['rho_xp']:.4f}  vs  baseline {a['rho_base']:.4f}"
              f"   ({a['rho_xp'] - a['rho_base']:+.4f})")
    print("  Per positio (pelanneet):")
    for pname, s in by_pos.items():
        print(f"      {pname}: MAE {s['mae_xp']:.3f} vs {s['mae_base']:.3f}, "
              f"rho {s['rho_xp']:.3f} vs {s['rho_base']:.3f}  (n={s['n']})")
    print(f"\n  GATE: {'PASS' if gate_pass else 'FAIL'}")
    print("=" * 72)
    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true",
                    help="pakota FPL-datan uudelleenhaku (ohita välimuisti)")
    args = ap.parse_args()

    report = run_backtest(force_refresh=args.refresh)

    out_dir = config.PROJECT_ROOT / "logs"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / f"fpl_xp_backtest_{_dt.date.today().isoformat()}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    print(f"\nRaportti: {out}")
    return 0 if report["gate"]["PASS"] else 2


if __name__ == "__main__":
    sys.exit(main())
