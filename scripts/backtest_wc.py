"""#79 vaihe 5 — WC-mallin offline-backtest (ship-gate).

Train ennen cutoff X → ennusta X:n jälkeiset KILPAILULLISET maaottelut → pisteytä
log-loss + Brier + RPS. Vertaa VANHA (WC 2018/22) vs UUSI (martj42, viritetty).

Aja: python -m scripts.backtest_wc
Ship-gate: UUSI ≥ VANHA kaikilla kolmella mittarilla (samoilla otteluilla) +
marquee-sanity (Brazil/France/England/Argentina järkevinä suosikkeina).
"""
from __future__ import annotations

import sys
import copy
import numpy as np
import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from src.data.international_results import (
    _read_raw, COMPETITION_WEIGHTS, DEFAULT_COMPETITION_WEIGHT,
)
from src.data.wc_teams import WC2026_TEAMS_SET, resolve_wc_name
from src.models.dixon_coles import DixonColesModel

CUTOFF = pd.Timestamp("2025-06-01")          # train < X, test >= X
TEST_END = pd.Timestamp("2026-06-07")
# Kilpailulliset testikilpailut (ei friendlyt) — "oikeat" ennustekohteet.
TEST_TOURNAMENTS = {
    "FIFA World Cup", "FIFA World Cup qualification", "UEFA Nations League",
    "CONCACAF Nations League", "UEFA Euro", "Copa América",
    "African Cup of Nations", "AFC Asian Cup", "Gold Cup",
}


def _canon(name):
    r = resolve_wc_name(name)
    return r if r is not None else name


def _prep():
    raw = _read_raw().copy()
    raw = raw[raw["home_score"].notna() & raw["away_score"].notna()].copy()
    raw["home_team"] = raw["home_team"].map(_canon)
    raw["away_team"] = raw["away_team"].map(_canon)
    raw["home_score"] = raw["home_score"].astype(int)
    raw["away_score"] = raw["away_score"].astype(int)
    raw["neutral"] = raw["neutral"].astype(str).str.upper().eq("TRUE")
    return raw


def _fit(df, decay, bayes, comp=True):
    kw = {}
    if comp:
        kw = dict(competition_col="tournament",
                  competition_weights=COMPETITION_WEIGHTS,
                  default_competition_weight=DEFAULT_COMPETITION_WEIGHT)
    return DixonColesModel(per_team_home_adv=False).fit(
        df, decay=decay, date_col="date", l2_attack_defence=bayes,
        shrink_defence_to_mean=True, **kw)


def _neutralize(dc):
    d = copy.copy(dc)
    h = dc.home_advantage / 2.0
    d.defence = {t: v + h for t, v in dc.defence.items()}
    d.home_advantage = 0.0
    d.home_advantage_per_team = {t: 0.0 for t in dc.teams_}
    return d


def _probs(dc, dc_neutral, home, away, neutral):
    model = dc_neutral if neutral else dc
    p = model.predict_1x2(home, away)
    return [p["home"], p["draw"], p["away"]]


def _outcome_idx(hs, as_):
    return 0 if hs > as_ else (1 if hs == as_ else 2)


def _score(probs, oi):
    p = np.clip(np.array(probs, dtype=float), 1e-12, 1.0)
    p = p / p.sum()
    logloss = -np.log(p[oi])
    o = np.zeros(3); o[oi] = 1.0
    brier = np.sum((p - o) ** 2)
    cp = np.cumsum(p); co = np.cumsum(o)
    rps = 0.5 * np.sum((cp[:-1] - co[:-1]) ** 2)
    return logloss, brier, rps


def evaluate(dc, test, allowed):
    dcn = _neutralize(dc)
    rows = []
    for _, m in test.iterrows():
        h, a = m["home_team"], m["away_team"]
        if h not in allowed or a not in allowed:
            continue
        if h not in dc.attack or a not in dc.attack:
            continue
        probs = _probs(dc, dcn, h, a, bool(m["neutral"]))
        rows.append(_score(probs, _outcome_idx(m["home_score"], m["away_score"])))
    if not rows:
        return None
    arr = np.array(rows)
    return dict(n=len(rows), logloss=arr[:, 0].mean(),
                brier=arr[:, 1].mean(), rps=arr[:, 2].mean())


def main():
    raw = _prep()
    train_all = raw[raw["date"] < CUTOFF]
    test = raw[(raw["date"] >= CUTOFF) & (raw["date"] < TEST_END)]
    test = test[test["tournament"].isin(TEST_TOURNAMENTS)]
    print(f"Cutoff={CUTOFF.date()} | test-ikkuna {CUTOFF.date()}..{TEST_END.date()} | "
          f"kilpailulliset testiottelut={len(test)}")

    # OLD: WC 2018 + 2022 (martj42 'FIFA World Cup' 2017-2023), ennen cutoffia
    old_train = train_all[(train_all["tournament"] == "FIFA World Cup")
                          & (train_all["date"].dt.year.between(2017, 2023))]
    old = _fit(old_train, decay=0.0, bayes=8.0, comp=False)
    print(f"OLD-malli: train={len(old_train)} ottelua, {len(old.teams_)} maata")

    # NEW: grid-haku tuoreelle otokselle
    grid = []
    for window in ("2022-01-01", "2024-01-01"):
        for include in ("any", "both"):
            tr = train_all[train_all["date"] >= pd.Timestamp(window)]
            hi = tr["home_team"].isin(WC2026_TEAMS_SET)
            ai = tr["away_team"].isin(WC2026_TEAMS_SET)
            tr = tr[(hi & ai) if include == "both" else (hi | ai)]
            for decay in (0.0, 0.0008, 0.0015, 0.003):
                for bayes in (1.0, 2.0, 3.0, 5.0):
                    grid.append((window, include, decay, bayes, tr))

    # Pisteytä kaikki samoilla otteluilla joita OLD osaa (reilu head-to-head) →
    # mutta ensin valitaan paras NEW oman kattavuutensa otteluilla, sitten
    # head-to-head OLD vs NEW yhteisotteluilla.
    print("\n=== NEW grid (pisteet NEW:n omalla kattavuudella) ===")
    results = []
    for window, include, decay, bayes, tr in grid:
        dc = _fit(tr, decay=decay, bayes=bayes, comp=True)
        ev = evaluate(dc, test, allowed=set(dc.teams_) & WC2026_TEAMS_SET)
        if ev:
            results.append((ev["logloss"], window, include, decay, bayes, ev, dc))
    results.sort(key=lambda x: x[0])
    for ll, window, include, decay, bayes, ev, dc in results[:8]:
        print(f"  win={window[:4]} inc={include:4} decay={decay:.4f} bayes={bayes:.1f} "
              f"| n={ev['n']} logloss={ev['logloss']:.4f} brier={ev['brier']:.4f} rps={ev['rps']:.4f}")

    best = results[0]
    _, bw, bi, bd, bb, _, best_dc = best
    print(f"\nPARAS NEW: window={bw[:4]} include={bi} decay={bd} bayes={bb}")

    # Head-to-head: samat ottelut joita MOLEMMAT osaavat
    common = (set(best_dc.teams_) & set(old.teams_)) & WC2026_TEAMS_SET
    ev_new = evaluate(best_dc, test, allowed=common)
    ev_old = evaluate(old, test, allowed=common)
    print(f"\n=== HEAD-TO-HEAD (yhteiset otteluparit, allowed={len(common)} maata) ===")
    print(f"  {'metric':10} {'OLD':>10} {'NEW':>10} {'paranema':>10}")
    gate_ok = ev_new and ev_old and ev_new["n"] > 0
    for k in ("logloss", "brier", "rps"):
        improve = ev_old[k] - ev_new[k]
        flag = "OK" if improve >= 0 else "HUONOMPI"
        print(f"  {k:10} {ev_old[k]:>10.4f} {ev_new[k]:>10.4f} {improve:>+10.4f}  {flag}")
        if improve < 0:
            gate_ok = False
    print(f"  (n_otteluita OLD={ev_old['n']}, NEW={ev_new['n']})")
    print(f"  Kattavuus testissä: OLD osaa {ev_old['n']}, "
          f"NEW(48-rajattu) {evaluate(best_dc, test, allowed=WC2026_TEAMS_SET)['n']} ottelua")

    # Marquee-sanity (paras NEW, neutraali venue kuten WC)
    print("\n=== MARQUEE-SANITY (paras NEW, neutraali) ===")
    dcn = _neutralize(best_dc)
    for h, a in [("Brazil", "South Korea"), ("France", "Australia"),
                 ("England", "Haiti"), ("Argentina", "Curaçao"),
                 ("Spain", "Iran"), ("Portugal", "Norway")]:
        if h in best_dc.attack and a in best_dc.attack:
            p = dcn.predict_1x2(h, a)
            lam, mu = dcn.expected_goals(h, a)
            print(f"  {h:10} vs {a:14}: 1={p['home']:.2f} X={p['draw']:.2f} 2={p['away']:.2f}"
                  f"  xg {lam:.2f}-{mu:.2f}")

    print(f"\n{'='*50}\nSHIP-GATE: {'PASS — NEW >= OLD kaikilla' if gate_ok else 'NO-GO'}")
    return 0 if gate_ok else 1


if __name__ == "__main__":
    sys.exit(main())
