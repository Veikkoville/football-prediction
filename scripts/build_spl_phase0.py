"""
SPL Phase 0 — Saudi Pro League fantasy: clean sheet -% + mallipohjainen FDR.

Sama tuote kuin FPL Phase 0 (scripts/build_fpl_phase0.py) RSL Fantasylle
(fantasy.spl.com.sa) — alusta on FPL:n klooni identtisillä APIeilla
(bootstrap-static / fixtures; 18 joukkuetta, 590 pelaajaa, 34 GW; recon
6.8.2026, ks. goaliq-app/STATE.md). Kausi alkaa 13.8.2026 klo 16:10 UTC.

Erot FPL-builderiin:
  - Fixturet + deadlinet suoraan SPL-fantasy-APIsta (ei fallback-lähdettä:
    peli on jo auki 26/27-kaudelle, verifioitu 7.8).
  - Joukkuevoimat: DC-fitti vendoroidusta tuloshistoriasta
    data/spl_results.csv (ESPN, 2 kautta; scripts/fetch_spl_results_espn.py).
    MAALIPOHJAINEN fitti kuten muut ei-Understat-liigat — SPL:lle ei ole
    ilmaista xG-fixturefeediä. Sama fit-config kuin tuotanto (decay/bayes).
  - Nousijabaseline: add_promoted_baseline REFERENSSILLÄ = 25/26:n
    nousijatrio (mitattu tästä fitistä), allow_frozen=False — PL:n
    jäädytetyt luvut ovat PL-skaalaa eikä niitä käytetä tänne.
  - Ei Phase 1b -kontekstikerrosta (fpl_context on PL-datan varassa) —
    raaka DC, kirjattu meta.caveatiin.

Ulos: data/spl_projections_phase0.json — sama skeema kuin FPL Phase 0
(teams[] + fixtures-ticker + meta), jotta /api/fantasy-pinta ja klientit
voivat käyttää samaa renderöintipolkua base-URL/liigavalinnalla.

Ajo:  python -m scripts.build_spl_phase0
Sanity-gate: FAIL -> JSONia EI kirjoiteta, exit 2 (sama fail-safe-kuvio).
EI auto-pushia.
"""

from __future__ import annotations

import datetime as _dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd
import requests

import config
from src.models.dixon_coles import DixonColesModel
from src.models.promoted_baseline import add_promoted_baseline

# Geneeriset osat FPL-builderista: add_fdr operoi puhtailla riveillä eikä
# tunne liigaa; importti pitää FDR-menetelmän YHTENÄ lähteenä molemmille
# fantasy-tuotteille (sama 0.55/0.45-paino + kvintiilibucket).
from scripts.build_fpl_phase0 import (
    FIT_BAYES,
    FIT_DECAY,
    HORIZON_GW,
    NEAR_HORIZON_GW,
    FAR_BASIS_LABEL,
    add_fdr,
    _parse_iso_utc,
)

SPL_BASE = "https://fantasy.spl.com.sa/api"
SPL_HEADERS = {"User-Agent": "Mozilla/5.0 (GoalIQ refresh job)"}
SEASON_LABEL = "2026/27"
RESULTS_CSV = config.PROJECT_ROOT / "data" / "spl_results.csv"
OUT_PATH = config.PROJECT_ROOT / "data" / "spl_projections_phase0.json"

# ---------------------------------------------------------------------------
# Joukkuemappaus: SPL-fantasy-APIn short_name → mallin nimi (= ESPN:n
# englanninkielinen displayName, sama kuin data/spl_results.csv:ssä).
# APIn omat name-kentät ovat arabiaa → mappaus tehdään short-koodilla, joka
# on latinalainen ja stabiili. Verifioitu bootstrap-dumpista 7.8.2026.
# ---------------------------------------------------------------------------
SHORT_TO_MODEL = {
    "AHL": "Al Ahli",
    "FAT": "Al Fateh",
    "FYH": "Al Fayha",
    "HIL": "Al Hilal",
    "ETT": "Al Ettifaq",
    "ITT": "Al Ittihad",
    "KLJ": "Al Khaleej",
    "NAS": "Al Nassr",
    "RIY": "Al Riyadh",
    "SHB": "Al Shabab",
    "TWN": "Al Taawoun",
    "QAD": "Al Qadsiah",
    "KLD": "Al Kholood",
    "NEO": "Neom SC",
    "HAZ": "Al Hazem",
    "ABH": "Abha",
    "FSL": "Al Faisaly",
    "DIR": "Al Diriyah",
}
MODEL_TO_SHORT = {v: k for k, v in SHORT_TO_MODEL.items()}

# 25/26:n nousijatrio = tuorein ryhmä jonka toteutunut SPL-voima on samassa
# fitissä täydellä kaudella (kausidiff 2425→2526 vendoroidusta CSV:stä 7.8:
# sisään Al Hazem, Al Najma, Neom SC / ulos Al Orobah, Al Raed, Al Wehda).
REFERENCE_TRIO_SPL = ("Al Hazem", "Al Najma", "Neom SC")

# Sanity-gaten kärkiryhmä (SPL:n vakiokärki; sama rooli kuin MCI/ARS/LIV).
STRONG_TEAMS = ("Al Hilal", "Al Nassr", "Al Ittihad")


def short_name(model_name: str) -> str:
    return MODEL_TO_SHORT.get(model_name, model_name[:3].upper())


# ---------------------------------------------------------------------------
# 1. Lähde: SPL-fantasy-API (bootstrap + fixtures)
# ---------------------------------------------------------------------------
def fetch_source() -> dict:
    print("[1/5] Haetaan SPL-fantasy bootstrap + fixtures...")
    r = requests.get(f"{SPL_BASE}/bootstrap-static/", headers=SPL_HEADERS, timeout=30)
    r.raise_for_status()
    boot = r.json()
    r = requests.get(f"{SPL_BASE}/fixtures/", headers=SPL_HEADERS, timeout=30)
    r.raise_for_status()
    raw_fixtures = r.json()

    teams_by_id = {t["id"]: t for t in boot.get("teams", [])}
    tuntemattomat = sorted(
        t["short_name"] for t in teams_by_id.values()
        if t["short_name"] not in SHORT_TO_MODEL
    )
    if tuntemattomat:
        raise SystemExit(
            f"SHORT_TO_MODEL ei tunne koodeja {tuntemattomat} — päivitä mappaus."
        )

    fixtures = []
    for f in raw_fixtures:
        th, ta = teams_by_id.get(f.get("team_h")), teams_by_id.get(f.get("team_a"))
        if not th or not ta:
            continue
        ko = _parse_iso_utc(f.get("kickoff_time"))
        fixtures.append(
            {
                "gameweek": f.get("event"),
                "kickoff": ko.strftime("%a %d %b %Y, %H:%M UTC") if ko else "TBC",
                "kickoff_ms": int(ko.timestamp() * 1000) if ko else None,
                "finished": bool(f.get("finished")),
                "home": SHORT_TO_MODEL[th["short_name"]],
                "away": SHORT_TO_MODEL[ta["short_name"]],
            }
        )

    # 🔴 KIERROSNUMERO JA DEADLINE SAMASTA TAPAHTUMASTA (15.8.2026).
    #
    # MITATTU VIKA, Villen havainto: SPL-sivu naytti "GW1 deadline: 20 Aug
    # 17:55". Virallinen RSL Fantasy sanoo:
    #     GW1  deadline 2026-08-13T16:10Z  is_current=True   (pelattu 13.8)
    #     GW2  deadline 2026-08-20T17:55Z  is_next=True
    # Eli ruudulla oli GW2:n deadline GW1:n nimella, ja lukija joka suunnitteli
    # GW1:ta oli myohassa kahdella paivalla.
    #
    # Syy oli KAKSI ERI SAANTOA jotka kuvasivat eri kierrosta:
    #   deadline_utc  = min(deadline | ei finished JA deadline > nyt)  -> GW2
    #   next_gameweek = min(gw | fixture ei finished)                  -> GW1
    # GW1:n `finished` ei ole viela True (kierros on kesken), joten
    # fixture-pohjainen saanto jai siihen samalla kun deadline-saanto oli jo
    # siirtynyt eteenpain. Kumpikin oli yksinaan puolustettava. Yhdessa ne
    # tuottivat lauseen jota kumpikaan ei tarkoittanut.
    #
    # Korjaus ei ole kolmas saanto vaan YKSI LAHDE: API kertoo itse mika on
    # seuraava kierros (`is_next`), ja seka numero etta deadline luetaan
    # SIITA tapahtumasta. Silloin ne eivat voi olla eri mielta.
    now = _dt.datetime.now(_dt.timezone.utc)
    events = boot.get("events", []) or []
    nxt = next((ev for ev in events if ev.get("is_next")), None)
    if nxt is None:
        # Varakeino jos lippu puuttuu: ensimmainen tapahtuma jonka deadline on
        # viela edessa. Sama semantiikka, heikompi lahde.
        nxt = next(
            (ev for ev in sorted(events, key=lambda e: e.get("id") or 0)
             if (d := _parse_iso_utc(ev.get("deadline_time"))) and d > now),
            None,
        )
    next_deadline = _parse_iso_utc(nxt.get("deadline_time")) if nxt else None
    next_event_id = (nxt or {}).get("id")
    teams = sorted(SHORT_TO_MODEL[t["short_name"]] for t in teams_by_id.values())
    print(f"      {len(fixtures)} fixturea, {len(teams)} joukkuetta, "
          f"seuraava GW{next_event_id} deadline {next_deadline}")
    return {
        "fixtures": fixtures,
        "teams": teams,
        "deadline_utc": (
            next_deadline.isoformat(timespec="seconds") if next_deadline else None
        ),
        # Sama tapahtuma josta deadline luettiin. Naita EI saa johtaa erikseen.
        "next_gameweek": next_event_id,
        "source": "spl-fantasy-api",
        "source_label": "RSL Fantasy official API (fantasy.spl.com.sa)",
    }


# ---------------------------------------------------------------------------
# 2. DC-fitti vendoroidusta tuloshistoriasta (maalipohjainen)
# ---------------------------------------------------------------------------
def fit_model() -> tuple[DixonColesModel, list[str]]:
    if not RESULTS_CSV.exists():
        raise SystemExit(
            f"{RESULTS_CSV} puuttuu — aja ensin scripts/fetch_spl_results_espn.py"
        )
    df = pd.read_csv(RESULTS_CSV, encoding="utf-8")
    df["date"] = pd.to_datetime(df["date"])
    seasons = sorted(df["season"].astype(str).unique())
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


# ---------------------------------------------------------------------------
# 3. Per-fixture CS% + win% + xG (raaka DC, ei kontekstikerrosta)
# ---------------------------------------------------------------------------
def compute_fixtures(dc: DixonColesModel, fixtures: list[dict]) -> list[dict]:
    rows = []
    for f in fixtures:
        h, a = f["home"], f["away"]
        if h not in dc.attack or a not in dc.attack:
            continue  # ei pitäisi tapahtua (baseline lisätty) — ohita turvallisesti
        lam, mu = dc.expected_goals(h, a)
        m = dc.score_matrix(h, a)
        rows.append(
            {
                "gameweek": f["gameweek"],
                "kickoff": f["kickoff"],
                "kickoff_ms": f["kickoff_ms"],
                "finished": f.get("finished", False),
                "home": h,
                "away": a,
                "home_short": short_name(h),
                "away_short": short_name(a),
                "xg_home": round(lam, 3),
                "xg_away": round(mu, 3),
                "p_home_win": round(float(np.tril(m, -1).sum()), 4),
                "p_draw": round(float(np.trace(m)), 4),
                "p_away_win": round(float(np.triu(m, 1).sum()), 4),
                "cs_home_pct": round(float(m[:, 0].sum()) * 100, 1),
                "cs_away_pct": round(float(m[0, :].sum()) * 100, 1),
            }
        )
    return rows


def next_gameweek(rows: list[dict]) -> int | None:
    gws = [r["gameweek"] for r in rows if r["gameweek"] and not r["finished"]]
    return min(gws) if gws else None


def build_team_view(rows: list[dict], next_gw: int) -> list[dict]:
    """Sama rakenne + tier-kontrakti kuin FPL-builderissa: cs_pct VAIN
    lähihorisontissa (near), kaukoriveillä pelkkä FDR. Ks. build_fpl_phase0
    NEAR_HORIZON_GW-lohkon perustelu — kenttä puuttuu rakenteesta, ei
    konventiolla."""
    near_cut = next_gw + NEAR_HORIZON_GW - 1
    teams: dict[str, dict] = {}
    for r in rows:
        gw = r["gameweek"]
        if not gw or gw < next_gw or r["finished"]:
            continue
        near = gw <= near_cut
        for side, opp_side in (("home", "away"), ("away", "home")):
            team = r[side]
            entry = teams.setdefault(
                team,
                {"name": team, "short": short_name(team), "fixtures": []},
            )
            fx = {
                "gw": gw,
                "opponent": r[opp_side],
                "opponent_short": r[f"{opp_side}_short"],
                "venue": "H" if side == "home" else "A",
                "kickoff_ms": r["kickoff_ms"],
                "fdr": r[f"fdr_{side}"],
                "def_fdr": r[f"fdr_{side}"],
                "att_fdr": r[f"att_fdr_{side}"],
                "tier": "near" if near else "far",
            }
            if near:
                fx["cs_pct"] = r[f"cs_{side}_pct"]
            entry["fixtures"].append(fx)
    out = []
    for entry in teams.values():
        entry["fixtures"].sort(key=lambda x: (x["gw"], x["kickoff_ms"] or 0))
        near_fx = [f for f in entry["fixtures"] if f["tier"] == "near"]
        cs = [f["cs_pct"] for f in near_fx]
        fdr = [f["fdr"] for f in near_fx]
        entry["next_avg_cs_pct"] = round(float(np.mean(cs)), 1) if cs else 0.0
        entry["next_avg_fdr"] = round(float(np.mean(fdr)), 2) if fdr else 0.0
        entry["next_n"] = len(cs)
        out.append(entry)
    out.sort(key=lambda t: (-t["next_avg_cs_pct"], t["name"]))
    return out


def _horizon_span(team_view: list[dict]) -> int:
    gws = [f["gw"] for t in team_view for f in t["fixtures"]]
    return (max(gws) - min(gws) + 1) if gws else 0


# ---------------------------------------------------------------------------
# 4. Sanity-gate (fail-safe: FAIL -> ei kirjoiteta, exit 2)
# ---------------------------------------------------------------------------
def sanity_gate(team_view: list[dict], promoted: list[str]) -> bool:
    print("\n" + "=" * 64)
    print("SANITY-GATE  (suunta-/separaatiotesti, SPL-kärki vs nousijat)")
    print("=" * 64)
    agg = {t["name"]: t for t in team_view}
    strong = [t for t in STRONG_TEAMS if t in agg]
    weak = [t for t in promoted if t in agg]

    for t in strong + weak:
        a = agg[t]
        tag = "promoted" if t in weak else "kärki"
        print(f"    {t:20s} fdr={a['next_avg_fdr']:.2f}  cs={a['next_avg_cs_pct']:.1f}%  ({tag})")

    ok = True
    checks: list[tuple[str, bool]] = []
    if not strong:
        checks.append(("kärkijoukkueet löytyvät aggregaateista", False))
    else:
        checks.append(("jokainen kärkijoukkue FDR <= 3.2",
                       all(agg[t]["next_avg_fdr"] <= 3.2 for t in strong)))
    if weak:
        s_fdr = float(np.mean([agg[t]["next_avg_fdr"] for t in strong])) if strong else 5.0
        s_cs = float(np.mean([agg[t]["next_avg_cs_pct"] for t in strong])) if strong else 0.0
        w_fdr = float(np.mean([agg[t]["next_avg_fdr"] for t in weak]))
        w_cs = float(np.mean([agg[t]["next_avg_cs_pct"] for t in weak]))
        checks.append(("kärki avg FDR < nousijat avg FDR (margin >=1.0)", w_fdr - s_fdr >= 1.0))
        checks.append(("kärki avg CS% > nousijat avg CS% (margin >=8pp)", s_cs - w_cs >= 8.0))
        # 🔴 15.8.2026: tassa oli "jokainen nousija FDR >= 3.5". Se on vaite
        # OTTELUOHJELMASTA eika mallista: nousija voi aidosti saada helpon
        # kuuden pelin jakson, ja silloin portti kaatuu vaikka malli olisi
        # taysin oikeassa.
        #
        # Se osui kun kierrosikkuna korjattiin GW1->GW2 (GW1 oli jo pelattu):
        # Al Faisaly 3.50 -> 3.33, eli lattia oli mennyt lapi TASAN rajalla ja
        # yhden kierroksen siirtyma pudotti sen alle. Kolme muuta tarkistusta
        # eli varsinaiset separaatiotestit menivat lapi reilulla marginaalilla.
        #
        # Tilalle INVERSIOTARKISTUS joka mittaa sita mita portti oikeasti
        # vartioi: yksikaan nousija ei saa nayttaa helpommalta kuin vaikein
        # karkijoukkue. Se on riippumaton siita sattuuko kalenteri olemaan
        # helppo tai vaikea, ja se kaatuu jos malli menee nurin pain.
        checks.append(("yksikaan nousija ei ole karkea helpompi (ei inversiota)",
                       min(agg[t]["next_avg_fdr"] for t in weak)
                       > max(agg[t]["next_avg_fdr"] for t in strong)
                       if strong else False))
    for label, passed in checks:
        print(f"  [{'OK ' if passed else 'FAIL'}] {label}")
        ok = ok and passed
    print(f"\nGATE: {'PASS' if ok else 'FAIL'}")
    return ok


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main() -> int:
    src = fetch_source()

    print("[2/5] Sovitetaan SPL Dixon-Coles (vendoroitu ESPN-tuloshistoria)...")
    dc, seasons = fit_model()
    print(f"      {len(dc.teams_)} joukkuetta mallissa (kaudet {seasons})")

    missing = sorted(set(src["teams"]) - set(dc.attack))
    print(f"[3/5] Nousijat ilman SPL-dataa ikkunassa: {missing}")
    baseline = add_promoted_baseline(
        dc, missing, reference=REFERENCE_TRIO_SPL, allow_frozen=False,
    )
    print(f"      promoted baseline: {baseline}")
    if missing and not baseline.get("trio_used"):
        print("VIRHE: baseline ei injektoitunut (viitetrio puuttuu fitistä?) — "
              "nousijat putoaisivat hiljaa pois. Ei kirjoiteta.")
        return 1

    print("[4/5] Lasketaan CS% + win% + FDR per fixture (raaka DC)...")
    rows = compute_fixtures(dc, src["fixtures"])
    add_fdr(rows)
    # Kierrosnumero tulee API:n `is_next`-tapahtumasta samasta lahteesta kuin
    # deadline (ks. lataajan kommentti). Fixture-pohjainen `next_gameweek` on
    # varakeino, ja jos ne ovat eri mielta se KERROTAAN — hiljainen ero oli
    # tasan se vika joka naytti GW2:n deadlinen GW1:n nimella.
    next_gw = src.get("next_gameweek") or next_gameweek(rows)
    fixture_gw = next_gameweek(rows)
    if next_gw is None:
        print("VIRHE: ei yhtään pelaamatonta fixturea — ei kirjoiteta.")
        return 1
    if fixture_gw is not None and fixture_gw != next_gw:
        print(f"      HUOM: API sanoo seuraava GW{next_gw}, fixture-lippujen "
              f"mukaan GW{fixture_gw} (kierros kesken). Kaytetaan API:n lukua.")
    team_view = build_team_view(rows, next_gw)
    ticker = [
        r for r in rows
        if r["gameweek"] and next_gw <= r["gameweek"] <= next_gw + HORIZON_GW - 1
        and not r["finished"]
    ]

    if not sanity_gate(team_view, missing):
        print("SANITY-GATE FAIL — data/spl_projections_phase0.json EI kirjoitettu.")
        return 2

    print("\n[5/5] Kirjoitetaan JSON...")
    out = {
        "meta": {
            "product": "GoalIQ SPL Fantasy Phase 0 — clean sheet % + model FDR",
            "available": True,
            "phase": 0,
            "league": "SAU-Saudi Pro League",
            "generated_at": _dt.datetime.now().isoformat(timespec="seconds"),
            "season": SEASON_LABEL,
            "source": src["source"],
            "fixture_source": src["source_label"],
            "team_strength_source": (
                f"GoalIQ Dixon-Coles, SPL results (ESPN) {seasons} — "
                f"goals-based fit (decay={FIT_DECAY}, bayes={FIT_BAYES}); "
                "no free per-match xG feed exists for the SPL"
            ),
            "cs_method": "P(opponent scores 0) from the DC score matrix (tau corrected)",
            "fdr_method": (
                "Model based 1-5: 0.55*rank(1 - win%) + 0.45*rank(expected goals conceded), "
                "quintile bucket across every team fixture of the season"
            ),
            "att_fdr_method": (
                "Attack FDR 1-5: rank(own expected xG in the fixture) inverted "
                "(little xG of your own means a hard fixture), quintile bucket "
                "across every team fixture. 1 = easiest to attack against, 5 = hardest."
            ),
            "caveat": (
                "Pre-season: 26/27 team strengths are last-season priors from a "
                "goals-based model (no xG data for the SPL), indicative only. "
                "Promoted sides without top-flight data use an empirical promoted "
                "baseline measured from last season's promoted trio. No manual "
                "context layer (unlike FPL Phase 1b)."
            ),
            "promoted_baseline_teams": missing,
            "promoted_baseline_values": baseline,
            "sanity_gate": "PASS",
            "next_gameweek": next_gw,
            "deadline_utc": src["deadline_utc"],
            "horizon_gw": _horizon_span(team_view),
            "horizon_max": _horizon_span(team_view),
            "near_horizon_gw": NEAR_HORIZON_GW,
            "far_basis_label": FAR_BASIS_LABEL,
            "todo": [],
        },
        "teams": team_view,
        "fixtures": ticker,
    }
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"      -> {OUT_PATH}  ({len(team_view)} joukkuetta, {len(ticker)} ticker-fixturea)")

    print("\nEI auto-pushia. Deploy (Villen 🔒 GO):")
    print("  git add data/spl_projections_phase0.json")
    print('  git commit -m "data(spl): Phase 0 CS%/FDR"')
    return 0


if __name__ == "__main__":
    sys.exit(main())
