"""
FPL Phase 0 -pohjatyö — clean sheet -% + mallipohjainen FDR per PL-joukkue/fixture.

Tuottaa STAATTISEN `data/fpl_cs_fdr.json`:n tulevan FPL-endpointin pohjaksi.
EI on-request raskasta laskentaa (Render-budjettisääntö, FPL-speksi luku 2).

Lähteet:
  - Fixturet + joukkueet: premierleague.com (pulselive) compSeason 841 = 2026/27.
    FPL:n virallinen API (fantasy.premierleague.com) tarjoilee tämän ajon hetkellä
    yhä päättynyttä 25/26-kautta (current GW 38, ei next), joten 26/27 luetaan
    PL:n omasta fixtuurifeed:stä (julkaistu 19.6.2026).
  - Joukkuevoimat: GoalIQ:n OLEMASSA OLEVA Dixon-Coles -ottelumalli (Understat
    PL 24/25 + 25/26), sama fit-config kuin tuotannon /api/predict (_saa_malli).

Metodologia:
  - CS-% = Poisson(0; vastustajan odotetut maalit)  (FPL-speksi / kickoff-memo).
  - Mallipohjainen FDR (1-5) = johdettu voitto-%:sta + odotetuista päästetyistä
    maaleista, bucketoitu kvintiileihin koko kauden 760 joukkue-fixturen yli.

CAVEAT (kirjattu outputtiin): 26/27 team-voimat = viime kauden priorit →
suuntaa-antava teaser, ei tarkka. Nousijat Coventry + Hull (ei tuoretta
ylätason xG-dataa) saavat empiirisen "promoted baseline" -priorin.

EI committia tuotantoon ilman lupaa. Domestic-malli bittitarkasti koskematon —
tämä skripti vain LUKEE mallia, ei muuta fit-koodia.
"""

from __future__ import annotations

import datetime as _dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import requests
from scipy.stats import poisson

import config
from src.data.loader import lataa_otteludata
from src.models.dixon_coles import DixonColesModel

# ---------------------------------------------------------------------------
# 1. Asetukset
# ---------------------------------------------------------------------------
PULSE_HEADERS = {"User-Agent": "Mozilla/5.0", "Origin": "https://www.premierleague.com"}
COMPSEASON_2627 = 841  # premierleague.com -kausi-id 2026/27
OUT_PATH = config.PROJECT_ROOT / "data" / "fpl_cs_fdr.json"

# Tuotannon /api/predict -fit-parametrit (_saa_malli-defaultit) — pidä synkassa.
FIT_DECAY = 0.0035
FIT_BAYES = 2.0

# pulselive-nimi -> mallin (Understat) nimi
NAME_MAP = {
    "Brighton & Hove Albion": "Brighton",
    "Tottenham Hotspur": "Tottenham",
    "Leeds United": "Leeds",
    "Ipswich Town": "Ipswich",
    "Newcastle United": "Newcastle United",
    "Manchester City": "Manchester City",
    "Manchester United": "Manchester United",
    "Nottingham Forest": "Nottingham Forest",
}

# Nousijat ilman tuoretta ylätason dataa → empiirinen promoted baseline (alla).
# Ipswich on 24/25-datassa (alaspainotettu), joten se EI tarvitse priorip.


def map_name(pulse_name: str) -> str:
    return NAME_MAP.get(pulse_name, pulse_name)


# ---------------------------------------------------------------------------
# 2. Hae 26/27 fixturet + joukkueet PL:n feed:stä
# ---------------------------------------------------------------------------
def fetch_fixtures() -> list[dict]:
    fixtures: list[dict] = []
    page = 0
    while True:
        url = (
            "https://footballapi.pulselive.com/football/fixtures"
            f"?comps=1&compSeasons={COMPSEASON_2627}"
            f"&page={page}&pageSize=40&sort=asc&statuses=U,L,C"
        )
        r = requests.get(url, headers=PULSE_HEADERS, timeout=30)
        r.raise_for_status()
        d = r.json()
        content = d.get("content", [])
        for f in content:
            teams = f.get("teams", [])
            if len(teams) < 2:
                continue
            gw = f.get("gameweek", {}).get("gameweek")
            ko = f.get("kickoff", {})
            fixtures.append(
                {
                    "gameweek": int(gw) if gw is not None else None,
                    "kickoff": ko.get("label", "TBC"),
                    "kickoff_ms": ko.get("millis"),
                    "home": teams[0]["team"]["name"],
                    "away": teams[1]["team"]["name"],
                }
            )
        info = d.get("pageInfo", {})
        if page >= info.get("numPages", 1) - 1:
            break
        page += 1
    return fixtures


def fetch_teams() -> list[str]:
    url = f"https://footballapi.pulselive.com/football/compseasons/{COMPSEASON_2627}/teams"
    r = requests.get(url, headers=PULSE_HEADERS, timeout=30)
    r.raise_for_status()
    return sorted(t["name"] for t in r.json())


# ---------------------------------------------------------------------------
# 3. Sovita PL-malli (sama config kuin tuotanto) + promoted baseline
# ---------------------------------------------------------------------------
def fit_model() -> tuple[DixonColesModel, list[str]]:
    seasons = config.current_season_pair()
    df = lataa_otteludata(["ENG-Premier League"], seasons)
    if df.empty:
        raise SystemExit("PL-otteludata tyhjä — ei voi sovittaa mallia.")
    dc = DixonColesModel(per_team_home_adv=True).fit(
        df,
        home_team_col="home_team",
        away_team_col="away_team",
        home_goals_col="home_score",
        away_goals_col="away_score",
        decay=FIT_DECAY,
        date_col="date",
        l2_attack_defence=FIT_BAYES,
    )
    return dc, seasons


def add_promoted_baseline(dc: DixonColesModel, needed: list[str]) -> dict:
    """Anna nousijoille (ei tuoretta ylätason dataa) empiirinen prior =
    viimeisimmän nousijatrion (Ipswich/Leicester/Southampton, 24/25) toteutunut
    PL-voima. Palauttaa baseline-arvot raportointia varten."""
    trio = ["Ipswich", "Leicester", "Southampton"]
    trio = [t for t in trio if t in dc.attack]
    base_att = float(np.mean([dc.attack[t] for t in trio]))
    base_def = float(np.mean([dc.defence[t] for t in trio]))
    base_gamma = float(np.mean([dc.home_advantage_per_team[t] for t in trio]))
    for t in needed:
        dc.attack[t] = base_att
        dc.defence[t] = base_def
        dc.home_advantage_per_team[t] = base_gamma
    return {
        "trio_used": trio,
        "attack": round(base_att, 4),
        "defence": round(base_def, 4),
        "home_gamma": round(base_gamma, 4),
    }


# ---------------------------------------------------------------------------
# 4. Laske per-fixture CS% + win% + xG
# ---------------------------------------------------------------------------
def compute_fixtures(dc: DixonColesModel, fixtures: list[dict]) -> list[dict]:
    rows = []
    for f in fixtures:
        h = map_name(f["home"])
        a = map_name(f["away"])
        if h not in dc.attack or a not in dc.attack:
            # ei pitäisi tapahtua (baseline lisätty) — ohita turvallisesti
            continue
        lam, mu = dc.expected_goals(h, a)  # lam=koti xG, mu=vieras xG
        probs = dc.predict_1x2(h, a)       # täysi DC-matriisi (tau-korjattu)
        cs_home = float(poisson.pmf(0, mu))  # koti pitää nollan: vieras tekee 0
        cs_away = float(poisson.pmf(0, lam))
        rows.append(
            {
                **f,
                "home_model": h,
                "away_model": a,
                "xg_home": round(lam, 3),
                "xg_away": round(mu, 3),
                "p_home_win": round(probs["home"], 4),
                "p_draw": round(probs["draw"], 4),
                "p_away_win": round(probs["away"], 4),
                "cs_home_pct": round(cs_home * 100, 1),
                "cs_away_pct": round(cs_away * 100, 1),
            }
        )
    return rows


def add_fdr(rows: list[dict]) -> None:
    """Mallipohjainen FDR (1-5) per joukkue/fixture. Difficulty = rank-keskiarvo
    (1 - voitto-%) ja (odotetut päästetyt maalit), kvintiilibucket koko kauden
    760 joukkue-fixturen yli. 1 = helpoin, 5 = vaikein."""
    # Kokoa molemmat perspektiivit
    persp = []  # (row_idx, side, p_win, xGC)
    for i, r in enumerate(rows):
        persp.append((i, "home", r["p_home_win"], r["xg_away"]))
        persp.append((i, "away", r["p_away_win"], r["xg_home"]))
    n = len(persp)
    lose = np.array([1.0 - p[2] for p in persp])  # korkea = vaikeampi
    xgc = np.array([p[3] for p in persp])

    def pct_rank(x):
        order = x.argsort()
        ranks = np.empty(n, dtype=float)
        ranks[order] = np.arange(n)
        return ranks / max(n - 1, 1)

    diff = 0.55 * pct_rank(lose) + 0.45 * pct_rank(xgc)
    # kvintiilit -> FDR 1..5
    qs = np.quantile(diff, [0.2, 0.4, 0.6, 0.8])
    fdr = np.searchsorted(qs, diff, side="right") + 1  # 1..5
    for (i, side, _p, _x), d in zip(persp, fdr):
        rows[i][f"fdr_{side}"] = int(d)


# ---------------------------------------------------------------------------
# 5. Per-joukkue aggregaatit (seuraavat 6 GW)
# ---------------------------------------------------------------------------
def team_aggregates(rows: list[dict], horizon_gw: int = 6) -> dict:
    if not rows:
        return {}
    min_gw = min(r["gameweek"] for r in rows if r["gameweek"])
    gw_cut = min_gw + horizon_gw - 1
    agg: dict[str, dict] = {}
    for r in rows:
        if not r["gameweek"] or r["gameweek"] > gw_cut:
            continue
        for side in ("home", "away"):
            team = r["home"] if side == "home" else r["away"]
            cs = r[f"cs_{side}_pct"]
            fdr = r[f"fdr_{side}"]
            a = agg.setdefault(team, {"cs_pcts": [], "fdrs": [], "n": 0})
            a["cs_pcts"].append(cs)
            a["fdrs"].append(fdr)
            a["n"] += 1
    out = {}
    for team, a in agg.items():
        out[team] = {
            "next6_avg_cs_pct": round(float(np.mean(a["cs_pcts"])), 1),
            "next6_avg_fdr": round(float(np.mean(a["fdrs"])), 2),
            "next6_fixtures": a["n"],
        }
    return out


# ---------------------------------------------------------------------------
# 6. Sanity-gate + sample-taulukko
# ---------------------------------------------------------------------------
def sanity_and_sample(rows: list[dict], teams_agg: dict, promoted: list[str]) -> bool:
    print("\n" + "=" * 64)
    print("SANITY-GATE  (suunta-/separaatiotesti, ei absoluuttiset kynnykset)")
    print("=" * 64)
    ok = True

    # Vahvat (mallin kärki att-def) vs nousijat (promoted baseline).
    strong = ["Manchester City", "Arsenal", "Liverpool"]
    strong = [t for t in strong if t in teams_agg]
    weak = [t for t in promoted if t in teams_agg]

    print("  next6-aggregaatit:")
    for t in strong + weak:
        a = teams_agg[t]
        tag = "promoted" if t in weak else "kärki"
        print(f"    {t:20s} fdr={a['next6_avg_fdr']:.2f}  cs={a['next6_avg_cs_pct']:.1f}%  ({tag})")

    s_fdr = float(np.mean([teams_agg[t]["next6_avg_fdr"] for t in strong]))
    s_cs = float(np.mean([teams_agg[t]["next6_avg_cs_pct"] for t in strong]))
    w_fdr = float(np.mean([teams_agg[t]["next6_avg_fdr"] for t in weak]))
    w_cs = float(np.mean([teams_agg[t]["next6_avg_cs_pct"] for t in weak]))

    checks = [
        ("kärki avg FDR < nousijat avg FDR (margin >=1.0)", w_fdr - s_fdr >= 1.0),
        ("kärki avg CS% > nousijat avg CS% (margin >=8pp)", s_cs - w_cs >= 8.0),
        ("jokainen kärkijoukkue FDR <= 3.2", all(teams_agg[t]["next6_avg_fdr"] <= 3.2 for t in strong)),
        ("jokainen nousija FDR >= 3.5", all(teams_agg[t]["next6_avg_fdr"] >= 3.5 for t in weak)),
    ]
    print(f"\n  kärki:   FDR={s_fdr:.2f}  CS={s_cs:.1f}%")
    print(f"  nousijat: FDR={w_fdr:.2f}  CS={w_cs:.1f}%")
    for label, passed in checks:
        print(f"  [{'OK ' if passed else 'FAIL'}] {label}")
        ok = ok and passed

    # GW1 CS%-taulukko (koti+vieras perspektiivit erikseen)
    min_gw = min(r["gameweek"] for r in rows if r["gameweek"])
    gw1 = [r for r in rows if r["gameweek"] == min_gw]
    persp = []
    for r in gw1:
        persp.append((r["home"], r["away"], "H", r["cs_home_pct"], r["fdr_home"]))
        persp.append((r["away"], r["home"], "A", r["cs_away_pct"], r["fdr_away"]))
    persp.sort(key=lambda x: x[3], reverse=True)

    print("\n" + "=" * 64)
    print(f"SAMPLE — GW{min_gw} clean sheet -% (mallipohjainen, suuntaa-antava)")
    print("=" * 64)
    print("  TOP-5 CS%:")
    for team, opp, ha, cs, fdr in persp[:5]:
        print(f"    {cs:5.1f}%  FDR{fdr}  {team:20s} ({ha} vs {opp})")
    print("  BOTTOM-5 CS%:")
    for team, opp, ha, cs, fdr in persp[-5:]:
        print(f"    {cs:5.1f}%  FDR{fdr}  {team:20s} ({ha} vs {opp})")

    print("\n" + "=" * 64)
    print(f"GATE: {'PASS' if ok else 'FAIL'}")
    print("=" * 64)
    return ok


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main() -> None:
    print("[1/5] Haetaan 26/27 fixturet + joukkueet (premierleague.com)...")
    fixtures = fetch_fixtures()
    teams_2627 = fetch_teams()
    print(f"      {len(fixtures)} fixturea, {len(teams_2627)} joukkuetta")

    print("[2/5] Sovitetaan PL Dixon-Coles -malli (Understat 24/25+25/26)...")
    dc, seasons = fit_model()
    print(f"      {len(dc.teams_)} joukkuetta mallissa (kaudet {seasons})")

    # Mitkä 26/27-joukkueet puuttuvat mallista?
    missing = sorted({map_name(t) for t in teams_2627} - set(dc.attack))
    print(f"[3/5] Nousijat ilman tuoretta ylätason dataa: {missing}")
    baseline = add_promoted_baseline(dc, missing)
    print(f"      promoted baseline: {baseline}")

    print("[4/5] Lasketaan CS% + win% + FDR per fixture...")
    rows = compute_fixtures(dc, fixtures)
    add_fdr(rows)
    teams_agg = team_aggregates(rows)

    gate_pass = sanity_and_sample(rows, teams_agg, missing)

    print("\n[5/5] Kirjoitetaan JSON...")
    out = {
        "meta": {
            "product": "GoalIQ FPL Phase 0 — clean sheet % + model FDR",
            "generated_at": _dt.datetime.now().isoformat(timespec="seconds"),
            "season": "2026/27",
            "fixture_source": "premierleague.com (pulselive) compSeason 841, julkaistu 2026-06-15",
            "team_strength_source": (
                f"GoalIQ Dixon-Coles, Understat PL {seasons} "
                f"(sama fit-config kuin /api/predict: decay={FIT_DECAY}, bayes={FIT_BAYES})"
            ),
            "cs_method": "Poisson(0; vastustajan odotetut maalit)",
            "fdr_method": (
                "Mallipohjainen 1-5: 0.55*(1-voitto%) + 0.45*(odotetut päästetyt maalit), "
                "rank-normalisoitu, kvintiilibucket koko kauden 760 joukkue-fixturen yli"
            ),
            "caveat": (
                "26/27 team-voimat = viime kauden priorit, suuntaa-antava (ei tarkka). "
                "Nousijat Coventry/Hull = empiirinen promoted baseline (24/25 nousijatrio)."
            ),
            "promoted_baseline_teams": missing,
            "promoted_baseline_values": baseline,
            "sanity_gate": "PASS" if gate_pass else "FAIL",
            "phase": "Phase 0 — pohjatyö, EI shipattava feature",
        },
        "teams_next6": teams_agg,
        "fixtures": rows,
    }
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"      → {OUT_PATH}  ({len(rows)} fixturea)")


if __name__ == "__main__":
    main()
