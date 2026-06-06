"""#79 — viritä Elo-priori + kilpailu-paino niin että MOLEMMAT gatet menevät läpi:
(a) backtest uusi >= vanha (log-loss/Brier/RPS), (b) konfederaatio-sanity.

Aja: python -m scripts.tune_wc_elo
"""
from __future__ import annotations

import sys
import copy
import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from src.data.international_results import COMPETITION_WEIGHTS, DEFAULT_COMPETITION_WEIGHT
from src.data.wc_teams import WC2026_TEAMS_SET
from src.data.elo import build_team_priors, load_elo
from src.models.dixon_coles import DixonColesModel
from scripts.backtest_wc import _prep, _neutralize, evaluate, CUTOFF, TEST_END, TEST_TOURNAMENTS, _fit

CONF = {
 'UEFA':['Austria','Belgium','Bosnia-Herzegovina','Croatia','Czechia','England','France','Germany','Netherlands','Norway','Portugal','Scotland','Spain','Sweden','Switzerland','Turkey'],
 'CONMEBOL':['Argentina','Brazil','Colombia','Ecuador','Paraguay','Uruguay'],
 'CONCACAF':['Canada','Curaçao','Haiti','Mexico','Panama','United States'],
 'AFC':['Australia','Iran','Iraq','Japan','Jordan','Qatar','Saudi Arabia','South Korea','Uzbekistan'],
 'CAF':['Algeria','Cape Verde Islands','Congo DR','Egypt','Ghana','Ivory Coast','Morocco','Senegal','South Africa','Tunisia'],
 'OFC':['New Zealand'],
}
CONF_OF = {t: c for c, ts in CONF.items() for t in ts}


def custom_weights(friendly_w):
    w = dict(COMPETITION_WEIGHTS)
    for k in ("Friendly", "FIFA Series", "CONCACAF Series"):
        w[k] = friendly_w
    return w


def fit_priors(train, beta, weight, shrink, friendly_w):
    teams = sorted(set(train["home_team"]) | set(train["away_team"]))
    priors = build_team_priors(teams, beta=beta, weight=weight)
    return DixonColesModel(per_team_home_adv=False).fit(
        train, decay=0.0, date_col="date", l2_attack_defence=1.0,
        shrink_defence_to_mean=shrink, team_priors=priors,
        competition_col="tournament", competition_weights=custom_weights(friendly_w),
        default_competition_weight=DEFAULT_COMPETITION_WEIGHT,
    )


# Elo-suuntainen sanity: korkeamman Elon joukkue on mallin suosikki (kun Elo-gap
# merkittävä). Lähellä-tasapeli-parit eivät saa kääntyä rajusti.
DIRECTIONAL_PAIRS = [
    ("Netherlands", "Japan"), ("Belgium", "Mexico"), ("France", "Australia"),
    ("England", "United States"), ("Brazil", "South Korea"), ("Germany", "Japan"),
    ("Portugal", "Morocco"), ("Spain", "Iran"), ("Croatia", "United States"),
]


def sanity(dc):
    d = _neutralize(dc)
    elo = load_elo()
    strength = {t: dc.attack[t] - dc.defence[t] for t in dc.teams_ if t in CONF_OF}
    top = sorted(strength, key=lambda t: -strength[t])
    top6, top12 = top[:6], top[:12]
    elo_top12 = set(sorted([t for t in CONF_OF if t in elo], key=lambda t: -elo[t])[:12])
    bad_top6 = [t for t in top6 if CONF_OF[t] in ("AFC", "CONCACAF")]
    overlap = len(set(top12) & elo_top12)

    # Suuntaiset tarkistukset: kun Elo-gap >= 25, korkeamman Elon pitää olla suosikki.
    inversions = []
    for h, a in DIRECTIONAL_PAIRS:
        if h not in d.attack or a not in d.attack:
            continue
        p = d.predict_1x2(h, a)
        gap = elo.get(h, 1500) - elo.get(a, 1500)
        fav_high_elo = (p["home"] > p["away"]) == (gap > 0)
        if abs(gap) >= 25 and not fav_high_elo:
            inversions.append(f"{h}({elo.get(h)})<{a}({elo.get(a)})")
    ned = d.predict_1x2("Netherlands", "Japan")
    checks = {
        "NED>JPN": ned["home"] > ned["away"],          # inversio korjattu (Elo-gap 38)
        "no AFC/CONCACAF top6": not bad_top6,
        "Japan out of top6": top.index("Japan") + 1 > 6,
        "top12 vs Elo >=8": overlap >= 8,
        "no Elo-inversions(gap>=25)": not inversions,
    }
    return checks, dict(ned=(ned["home"], ned["away"]), top6=top6, bad_top6=bad_top6,
                        overlap=overlap, jpn_rank=top.index("Japan") + 1, inversions=inversions)


def main():
    raw = _prep()
    train_all = raw[raw["date"] < CUTOFF]
    test = raw[(raw["date"] >= CUTOFF) & (raw["date"] < TEST_END)]
    test = test[test["tournament"].isin(TEST_TOURNAMENTS)]
    base = train_all[train_all["date"] >= pd.Timestamp("2022-01-01")]
    hi = base["home_team"].isin(WC2026_TEAMS_SET); ai = base["away_team"].isin(WC2026_TEAMS_SET)
    train = base[hi | ai]

    old_train = train_all[(train_all["tournament"] == "FIFA World Cup")
                          & (train_all["date"].dt.year.between(2017, 2023))]
    old = _fit(old_train, 0.0, 8.0, comp=False)

    best = None
    print(f"{'beta':>7} {'wt':>3} {'shrink':>6} {'frnd':>4} | {'ll':>7} {'brier':>6} {'rps':>6} bt | "
          f"{'JPNrank':>7} NED-JPN sanity")
    for beta in (0.0030, 0.0040, 0.0050, 0.0060):
        for weight in (8.0, 12.0, 16.0):
            for shrink in (False, True):
                for friendly_w in (0.5,):
                    dc = fit_priors(train, beta, weight, shrink, friendly_w)
                    common = (set(dc.teams_) & set(old.teams_)) & WC2026_TEAMS_SET
                    en = evaluate(dc, test, common); eo = evaluate(old, test, common)
                    if not en or not eo:
                        continue
                    bt_ok = all(eo[k] - en[k] >= 0 for k in ("logloss", "brier", "rps"))
                    chk, info = sanity(dc)
                    san_ok = all(chk.values())
                    passed = "BOTH-OK" if (bt_ok and san_ok) else ("bt" if bt_ok else "") + ("/san" if san_ok else "")
                    print(f"{beta:>7.4f} {weight:>3.0f} {str(shrink):>6} {friendly_w:>4} | "
                          f"{en['logloss']:.4f} {en['brier']:.4f} {en['rps']:.4f} {'Y' if bt_ok else 'N'} | "
                          f"{info['jpn_rank']:>7} {info['ned'][0]:.2f}/{info['ned'][1]:.2f} {passed}")
                    if bt_ok and san_ok:
                        score = en["logloss"]
                        if best is None or score < best[0]:
                            best = (score, beta, weight, shrink, friendly_w, dc, en, eo, chk, info)

    print()
    if best is None:
        print("NO CONFIG PASSED BOTH GATES")
        return 1
    _, beta, weight, shrink, friendly_w, dc, en, eo, chk, info = best
    print(f"=== PARAS (BOTH GATES): beta={beta} weight={weight} shrink={shrink} friendly_w={friendly_w} ===")
    print(f"  backtest: logloss {eo['logloss']:.4f}->{en['logloss']:.4f}, "
          f"brier {eo['brier']:.4f}->{en['brier']:.4f}, rps {eo['rps']:.4f}->{en['rps']:.4f} (n={en['n']})")
    print(f"  sanity: {chk}")
    print(f"  Japan rank={info['jpn_rank']}, top6={info['top6']}, top12∩Elo={info['overlap']}")
    d = _neutralize(dc)
    print("  marquee:")
    for h, a in [("Netherlands","Japan"),("France","Australia"),("Belgium","Mexico"),
                 ("Brazil","South Korea"),("Spain","Iran"),("England","United States"),
                 ("Germany","Japan"),("Portugal","Morocco")]:
        p = d.predict_1x2(h, a)
        print(f"    {h:12} vs {a:14} 1={p['home']:.2f} X={p['draw']:.2f} 2={p['away']:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
