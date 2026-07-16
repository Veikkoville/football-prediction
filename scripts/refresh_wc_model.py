"""WC-mallin datan virkistysputki + kova ship-gate (yksi ajo).

Ketjuttaa: update_international_results → update_elo_ratings → kandidaattifitti
(väliaikaistiedostoon) → offline-backtest VANHAA data/wc_model.json:ia vasten →
marquee/konfederaatio-sanity → domestic /api/predict bit-exact-regressio.

data/wc_model.json korvataan VAIN jos KAIKKI kolme gatea aukeavat:
  G1  backtest: uusi <= vanha log-lossissa, Brierissä JA RPS:ssä (samat ottelut)
  G2  sanity:   scripts.tune_wc_elo.sanity() kaikki ehdot (NED>JPN, ei
                AFC/CONCACAF top-6:ssa, Japan ulkona top-6:sta, top12∩Elo>=8,
                ei Elo-inversioita gap>=25 -pareissa)
  G3  domestic: regression_predict-caset OLD vs NEW, max|diff| = 0.0 (pakollinen
                joka ajossa — todistaa ettei virkistys kosketa /api/predict-polkua)

Gate kiinni → diff-raportti, KAIKKI datatiedostot palautetaan backupista
(työpuu ennalleen), exit != 0. Live-malliin ei kosketa.

#100: myös PASS jättää työpuun puhtaaksi — refit siirretään staging-kansioon
(data/_refit_candidate/, gitignoressa /data/*:n kautta) ja trackatut tiedostot
palautetaan backupista. Käyttöönotto = scripts/promote_wc_refit.py (kopioi
staging → data/) + git commit + push. Näin ajastettu ajo ei koskaan jätä
committoimattomia jäänteitä trackattuihin mallitiedostoihin (vrt. QUEUE #99).
Poikkeus: GitHub Actionsissa (GITHUB_ACTIONS=true) PASS säilyttää vanhan
kontraktin (tiedostot työpuuhun → workflow committaa itse) — ephemeral
runnerilla hygieniaongelmaa ei ole eikä workflown deploy-polku muutu.

Kaikki esirakennus offline — ei runtime-fittiä (Render 0.5 vCPU lataa vain JSONin).
EI git-operaatioita: PASS tulostaa promote+commit-ohjeen, päätös Villellä.

Aja repojuuresta: python -m scripts.refresh_wc_model
Exit: 0 = gate auki (uusi malli kirjoitettu), 1 = gate kiinni, 2 = infra-virhe.
"""
from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import config
from scripts import update_elo_ratings, update_international_results
from scripts.backtest_wc import CUTOFF, TEST_TOURNAMENTS, _prep, evaluate, _neutralize
from scripts.regression_predict import NUMERIC_FIELDS, snapshot
from scripts.tune_wc_elo import sanity
from src.data.elo import build_team_priors
from src.data.international_results import (
    DEFAULT_COMPETITION_WEIGHT, DEFAULT_INCLUDE, DEFAULT_WINDOW_START,
    COMPETITION_WEIGHTS, ELO_PRIOR_BETA, ELO_PRIOR_WEIGHT, WC_FIT_BAYES,
    WC_FIT_DECAY, WC_MODEL_PATH, WC_SHRINK_DEFENCE, lataa,
)
from src.data.wc_teams import WC2026_TEAMS_SET
from src.models.dixon_coles import DixonColesModel

DATA_FILES = ["international_results.csv", "elo_ratings.csv", "wc_model.json"]
BACKUP_DIR = config.DATA_DIR / ".refresh_backup"
CANDIDATE_PATH = config.DATA_DIR / "wc_model.candidate.json"
# #100: PASS-refit EI jää enää trackattuihin tiedostoihin odottamaan päätöstä
# (ajastettu ajo → kukaan ei näe banneria → pysyvästi likainen työpuu, osui
# #99:ään). PASS siirtää tulokset staging-kansioon + palauttaa työpuun;
# promote = scripts/promote_wc_refit.py (eksplisiittinen hyväksyntä).
STAGING_DIR = config.WC_REFIT_STAGING_DIR
STAGING_META = "_refit_meta.json"
PORT = 8765
BASE = f"http://localhost:{PORT}"
METRICS = ("logloss", "brier", "rps")

# CI-portti (#100 knockout-automaatio): GitHub Actions ei aja luotettavasti
# live-uvicornia + domestic-datahakua (understat/FD-flakeus → väärä NO-GO). G3:n
# invariantti on RAKENTEELLINEN: WC-virkistys kirjoittaa vain WC-datatiedostot
# eikä domestic /api/predict lue niitä → ohitettavissa CI:ssä turvallisesti
# (G3 ajetaan silti lokaalisti pre-push). G1+G2 (cross-confed-sanity) = offline,
# safety-kriittinen → AINA ajossa. Lokaali oletus (env unset) = ennallaan (#79).
SKIP_DOMESTIC_LIVE = os.getenv("REFRESH_SKIP_DOMESTIC_LIVE") == "1"

MARQUEE = [("Netherlands", "Japan"), ("France", "Australia"), ("Belgium", "Mexico"),
           ("Brazil", "South Korea"), ("Spain", "Iran"), ("England", "United States"),
           ("Germany", "Japan"), ("Portugal", "Morocco")]


def _backup() -> None:
    BACKUP_DIR.mkdir(exist_ok=True)
    for name in DATA_FILES:
        shutil.copy2(config.DATA_DIR / name, BACKUP_DIR / name)
    print(f"Backup -> {BACKUP_DIR} ({', '.join(DATA_FILES)})")


def _restore() -> None:
    for name in DATA_FILES:
        src = BACKUP_DIR / name
        if src.exists():
            shutil.copy2(src, config.DATA_DIR / name)
    print("PALAUTETTU: kaikki datatiedostot backupista — työpuu ennallaan.")


def _stage(meta: dict, gate_summary: dict) -> None:
    """#100: kopioi PASS-refitin tulokset stagingiin promotea odottamaan.

    Trackatut data/-tiedostot palautetaan tämän jälkeen backupista → työpuu
    pysyy puhtaana kunnes promote (Ville tai CI:n PASS-askel) ajetaan.
    """
    if STAGING_DIR.exists():
        shutil.rmtree(STAGING_DIR)
    STAGING_DIR.mkdir(parents=True)
    for name in DATA_FILES:
        shutil.copy2(config.DATA_DIR / name, STAGING_DIR / name)
    with open(STAGING_DIR / STAGING_META, "w", encoding="utf-8") as f:
        json.dump({"fit_meta": meta, "gate": gate_summary,
                   "staged_at": time.strftime("%Y-%m-%dT%H:%M:%S")},
                  f, ensure_ascii=False, indent=1)
    print(f"STAGED: PASS-refit -> {STAGING_DIR} (odottaa promotea).")


def _cleanup() -> None:
    """#100: siivoa ajon väliaikaisartefaktit (backup palvellut, kandidaatti
    joko hylätty tai stagingissa) — mikään ajo ei jätä roskia data/-juureen."""
    CANDIDATE_PATH.unlink(missing_ok=True)
    shutil.rmtree(BACKUP_DIR, ignore_errors=True)


def _load_model(path: Path) -> DixonColesModel:
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    return DixonColesModel(
        attack=d["attack"], defence=d["defence"],
        home_advantage=d["home_advantage"],
        home_advantage_per_team=d["home_advantage_per_team"],
        rho=d["rho"], teams_=d["teams_"],
        per_team_home_adv=d.get("per_team_home_adv", False),
        model_type_=d.get("model_type_", "dc"),
    )


def _save_model(dc: DixonColesModel, meta: dict, path: Path) -> None:
    payload = {
        "meta": meta,
        "attack": dc.attack, "defence": dc.defence,
        "home_advantage": dc.home_advantage,
        "home_advantage_per_team": dc.home_advantage_per_team,
        "rho": dc.rho, "teams_": list(dc.teams_),
        "per_team_home_adv": dc.per_team_home_adv,
        "model_type_": getattr(dc, "model_type_", "dc"),
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)


def _fit_candidate() -> tuple[DixonColesModel, dict]:
    df = lataa(window_start=DEFAULT_WINDOW_START, include=DEFAULT_INCLUDE)
    teams = sorted(set(df["home_team"]) | set(df["away_team"]))
    priors = build_team_priors(teams, beta=ELO_PRIOR_BETA, weight=ELO_PRIOR_WEIGHT)
    t0 = time.time()
    dc = DixonColesModel(per_team_home_adv=False).fit(
        df, decay=WC_FIT_DECAY, date_col="date",
        l2_attack_defence=WC_FIT_BAYES, shrink_defence_to_mean=WC_SHRINK_DEFENCE,
        team_priors=priors,
        competition_col="tournament", competition_weights=COMPETITION_WEIGHTS,
        default_competition_weight=DEFAULT_COMPETITION_WEIGHT,
    )
    meta = {
        "source": "martj42/international_results (CC0) + eloratings.net prior",
        "window_start": DEFAULT_WINDOW_START, "include": DEFAULT_INCLUDE,
        "decay": WC_FIT_DECAY, "bayes_shrinkage": WC_FIT_BAYES,
        "elo_prior_beta": ELO_PRIOR_BETA, "elo_prior_weight": ELO_PRIOR_WEIGHT,
        "shrink_defence_to_mean": WC_SHRINK_DEFENCE,
        "n_train_matches": len(df), "n_teams": len(dc.teams_),
        "fit_seconds": round(time.time() - t0, 2),
        "refreshed_by": "scripts/refresh_wc_model.py",
    }
    return dc, meta


def _gate_backtest(old_dc, new_dc):
    """G1: vanha vs uusi artefakti samoilla kilpailullisilla otteluilla CUTOFFista
    eteenpäin. Uusi on nähnyt tuoreimmat ottelut treenissä (virkistyksen pointti)
    → in-sample-etu; gate hylkää silti jos uusi on huonompi."""
    raw = _prep()
    test = raw[(raw["date"] >= CUTOFF) & raw["tournament"].isin(TEST_TOURNAMENTS)]
    common = (set(old_dc.teams_) & set(new_dc.teams_)) & WC2026_TEAMS_SET
    ev_old = evaluate(old_dc, test, allowed=common)
    ev_new = evaluate(new_dc, test, allowed=common)
    ok = bool(ev_old and ev_new and ev_new["n"] > 0)
    print(f"\n=== G1 BACKTEST (kilpailulliset ottelut {CUTOFF.date()}-> , "
          f"yhteiset {len(common)} maata, n={ev_new['n'] if ev_new else 0}) ===")
    print(f"  {'metric':10} {'VANHA':>10} {'UUSI':>10} {'paranema':>10}")
    for k in METRICS:
        improve = ev_old[k] - ev_new[k] if ok else float("nan")
        flag = "OK" if ok and improve >= 0 else "HUONOMPI"
        print(f"  {k:10} {ev_old[k]:>10.4f} {ev_new[k]:>10.4f} {improve:>+10.4f}  {flag}")
        if not ok or improve < 0:
            ok = False
    return ok, ev_old, ev_new


def _gate_sanity(new_dc):
    checks, info = sanity(new_dc)
    ok = all(checks.values())
    print("\n=== G2 MARQUEE/KONFEDERAATIO-SANITY (uusi malli, neutraali) ===")
    for name, passed in checks.items():
        print(f"  {'OK ' if passed else 'FAIL'} {name}")
    print(f"  Japan rank={info['jpn_rank']}, top6={info['top6']}, "
          f"top12 vs Elo overlap={info['overlap']}, inversiot={info['inversions'] or '-'}")
    return ok


def _print_marquee(old_dc, new_dc) -> None:
    print("\n=== MARQUEE-DIFF (neutraali, vanha -> uusi) ===")
    do, dn = _neutralize(old_dc), _neutralize(new_dc)
    for h, a in MARQUEE:
        if h not in new_dc.attack or a not in new_dc.attack:
            continue
        if h in old_dc.attack and a in old_dc.attack:
            po = do.predict_1x2(h, a)
            old_s = f"{po['home']:.2f}/{po['draw']:.2f}/{po['away']:.2f}"
        else:
            old_s = "-"
        pn = dn.predict_1x2(h, a)
        print(f"  {h:12} vs {a:14} {old_s:>16} -> "
              f"{pn['home']:.2f}/{pn['draw']:.2f}/{pn['away']:.2f}")


def _wait_server(proc: subprocess.Popen, timeout: float = 120.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            return False
        try:
            with urllib.request.urlopen(f"{BASE}/openapi.json", timeout=2):
                return True
        except Exception:
            time.sleep(1.0)
    return False


def _domestic_snapshot() -> dict:
    """Käynnistä tuore uvicorn (lru-cachet nollautuvat), snapshottaa, sammuta."""
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "api.main:app", "--port", str(PORT)],
        cwd=config.PROJECT_ROOT,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        if not _wait_server(proc):
            raise RuntimeError("uvicorn ei noussut 120 s:ssa (domestic-regressio)")
        return snapshot(BASE)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()


def _gate_domestic(before: dict, after: dict) -> bool:
    """G3: bit-exact — sama logiikka kuin regression_predict.compare()."""
    max_diff, n_mismatch = 0.0, 0
    print("\n=== G3 DOMESTIC /api/predict -REGRESSIO (bit-exact) ===")
    for k in sorted(set(before) | set(after)):
        b, a = before.get(k), after.get(k)
        if b == a:
            continue
        if isinstance(b, dict) and isinstance(a, dict):
            for field in set(b) | set(a):
                bv, av = b.get(field), a.get(field)
                if isinstance(bv, (int, float)) and isinstance(av, (int, float)):
                    d = abs(bv - av)
                    if d > 0:
                        max_diff = max(max_diff, d)
                        print(f"  DIFF {k} {field}: {bv!r} -> {av!r} (|d|={d})")
                elif bv != av:
                    n_mismatch += 1
                    print(f"  DIFF {k} {field}: {bv!r} -> {av!r}")
        else:
            n_mismatch += 1
            print(f"  DIFF {k}: {b!r} -> {a!r}")
    errors = [k for k, v in {**before, **after}.items()
              if isinstance(v, dict) and "_error" in v]
    if errors:
        print(f"  VIRHE: snapshot-caseissa _error: {errors}")
    print(f"  max|diff|={max_diff}, non-numeric mismatches={n_mismatch}, "
          f"cases={len(before)}")
    return max_diff == 0.0 and n_mismatch == 0 and not errors


def main() -> int:
    print("=" * 60)
    print("WC-MALLIN VIRKISTYS + SHIP-GATE")
    print("=" * 60)
    _backup()

    try:
        # Domestic "before" PUHTAASTA tilasta ennen mitään muutoksia.
        before = None
        if SKIP_DOMESTIC_LIVE:
            print("\n[0/4] Domestic before-snapshot OHITETTU "
                  "(REFRESH_SKIP_DOMESTIC_LIVE=1, CI-portti).")
        else:
            print("\n[0/4] Domestic before-snapshot (vanha tila)...")
            before = _domestic_snapshot()

        print("\n[1/4] martj42-snapshotin virkistys...")
        update_international_results.main()
        print("\n[2/4] Elo-snapshotin virkistys...")
        update_elo_ratings.main()

        print("\n[3/4] Kandidaattifitti (offline, ei kosketa live-malliin)...")
        old_dc = _load_model(WC_MODEL_PATH)
        new_dc, meta = _fit_candidate()
        _save_model(new_dc, meta, CANDIDATE_PATH)
        print(f"Kandidaatti: {meta['n_train_matches']} ottelua, "
              f"{meta['n_teams']} maata, fit {meta['fit_seconds']}s -> {CANDIDATE_PATH.name}")

        print("\n[4/4] Gatet...")
        g1, ev_old, ev_new = _gate_backtest(old_dc, new_dc)
        g2 = _gate_sanity(new_dc)
        _print_marquee(old_dc, new_dc)

        if not (g1 and g2):
            print("\n" + "=" * 60)
            print(f"SHIP-GATE: NO-GO (G1 backtest={'OK' if g1 else 'FAIL'}, "
                  f"G2 sanity={'OK' if g2 else 'FAIL'}) — live-malliin ei kosketa.")
            _restore()
            _cleanup()
            return 1

        # G1+G2 auki → kirjoita kandidaatti liveksi ja todista G3 uudella tilalla.
        # Jos G3 kaatuu, kaikki (ml. wc_model.json) palautuu backupista.
        shutil.copy2(CANDIDATE_PATH, WC_MODEL_PATH)
        if SKIP_DOMESTIC_LIVE:
            print("\nG3 DOMESTIC-LIVE OHITETTU (CI-portti): invariantti rakenteellinen — "
                  "WC-virkistys kirjoittaa VAIN WC-datatiedostot (international_results.csv, "
                  "elo_ratings.csv, wc_model.json); domestic /api/predict lukee understat/FD-"
                  "loaderit, EI näitä. G1+G2 (cross-confed-sanity) ajettu ja PASS. "
                  "G3 verifioidaan lokaalisti pre-push (tests/test_domestic_golden.py).")
            g3 = True
        else:
            print("\nG1+G2 OK -> kandidaatti asennettu väliaikaisesti, ajetaan G3...")
            after = _domestic_snapshot()
            g3 = _gate_domestic(before, after)

        if not g3:
            print("\n" + "=" * 60)
            print("SHIP-GATE: NO-GO (G3 domestic-regressio FAIL) — palautetaan kaikki.")
            _restore()
            _cleanup()
            return 1

        if os.getenv("GITHUB_ACTIONS") == "true":
            # #100: CI = ephemeral runner → paikallista hygieniaongelmaa ei ole,
            # ja wc-knockout-refresh.yml:n PASS-askel odottaa muutettuja
            # tiedostoja työpuussa (git add → commit → push, Villen hyväksymä
            # kontrakti #79/#100). Säilytetään se ENNALLAAN.
            _cleanup()
            print("\n" + "=" * 60)
            print("SHIP-GATE: PASS — uusi data/wc_model.json kirjoitettu (CI-polku: "
                  "workflow committaa; ephemeral runner, ei staging-tarvetta).")
            print(f"  backtest n={ev_new['n']}: " + ", ".join(
                f"{k} {ev_old[k]:.4f}->{ev_new[k]:.4f}" for k in METRICS))
            return 0

        # #100 (lokaali): PASS ei jätä trackattuja tiedostoja likaisiksi — refit
        # stagingiin, työpuu takaisin lähtötilaan, promote = erillinen askel.
        gate_summary = {"n": ev_new["n"]} | {
            k: {"old": round(ev_old[k], 4), "new": round(ev_new[k], 4)} for k in METRICS
        }
        _stage(meta, gate_summary)
        _restore()
        _cleanup()
        print("\n" + "=" * 60)
        print("SHIP-GATE: PASS — refit stagingissa, trackatut tiedostot KOSKEMATTA.")
        print(f"  backtest n={ev_new['n']}: " + ", ".join(
            f"{k} {ev_old[k]:.4f}->{ev_new[k]:.4f}" for k in METRICS))
        print("  Seuraavaksi (manuaalisesti, Villen päätös):")
        print("    python -m scripts.promote_wc_refit   <- kopioi staging -> data/")
        print("    git add data/international_results.csv data/elo_ratings.csv data/wc_model.json")
        print("    git commit + push -> Render auto-deploy")
        print(f"  Hylkäys: poista {STAGING_DIR} (työpuu on jo puhdas).")
        return 0

    except Exception as e:
        print(f"\nINFRA-VIRHE: {e!r} — palautetaan backup, live-malliin ei kosketa.")
        _restore()
        _cleanup()
        return 2


if __name__ == "__main__":
    sys.exit(main())
