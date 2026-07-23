"""Jäädytä 25/26-kauden pelaajabaselinet committoitavaksi artefaktiksi.

MIKSI (23.7.2026, FPL 26/27 -flippi): FPL:n element-summary tarjoilee vain
KULUVAN kauden per-kierros-historian. Kun bootstrap flippasi 26/27:ään,
historiat tyhjenivät ja element-id:t vaihtuivat → build_fpl_xp:n baselinet
katosivat (sanity-gate FAIL, 0 pelaajaa). 25/26-per-kierros-data ei ole enää
haettavissa API:sta — mutta se on tallella lokaalissa levyvälimuistissa
(data/raw/fpl/summary_2526/, 841 pelaajaa, täysi kausi).

Tämä skripti ajetaan KERRAN lokaalisti koneella jolla cache on:
  python -m scripts.build_fpl_prev_baselines
→ data/fpl_prev_baselines_2526.json (committoidaan repoon), avaimena FPL:n
kausien yli pysyvä pelaajakoodi (element code). build_fpl_xp lukee tämän
pre-seasonissa (ei yhtään pelattua GW:tä) ja mappaa 26/27-bootstrapin
pelaajiin e["code"]:lla — kesäsiirrot PL-seurojen välillä seuraavat mukana,
PL:stä lähteneet putoavat pois (eivät ole 26/27-bootstrapissa), PL:ään
tulevat uudet saavat positiopriorin (data_basis=no_history, olemassa oleva
mekanismi). Kun 26/27-kierroksia alkaa kertyä, normaali live-polku jatkaa.

LUKEE VAIN levycachea — EI verkkohakuja (verkosta saisi nyt vain tyhjän
26/27-datan, joka korruptoisi 2526-cachen). Puuttuva tiedosto = kova virhe.

Bonus-historia oikaistaan 26/27 BPS-sääntöihin (#151) ENNEN akkumulointia —
sama oikaisu jonka build_fpl_xp teki live-riveille, joten artefaktin luvut
ovat suoraan yhteensopivia (builderi EI oikaise näitä uudelleen).
"""
from __future__ import annotations

import datetime as _dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from src.models import fpl_xp as xp

CACHE_DIR = config.RAW_DATA_DIR / "fpl"
OLD_BOOT_PATH = CACHE_DIR / "bootstrap_static.json"
SUMMARY_DIR = CACHE_DIR / "summary_2526"
OUT_PATH = config.PROJECT_ROOT / "data" / "fpl_prev_baselines_2526.json"

SEASON_KEY = "2526"
EXPECTED_DEADLINE_PREFIX = "2025-"  # 25/26-kauden GW1-deadline elokuu 2025


def main() -> int:
    boot = json.loads(OLD_BOOT_PATH.read_text(encoding="utf-8"))
    first_deadline = boot["events"][0]["deadline_time"]
    if not first_deadline.startswith(EXPECTED_DEADLINE_PREFIX):
        raise SystemExit(
            f"VIRHE: bootstrap-cache ei ole 25/26-kautta (events[0].deadline "
            f"= {first_deadline}). Cache on jo ylikirjoitettu 26/27:llä — "
            f"artefaktia ei voi rakentaa tästä.")
    elements = boot["elements"]
    print(f"[1/3] 25/26-bootstrap: {len(elements)} pelaajaa "
          f"(GW1 deadline {first_deadline})")

    summaries: dict[int, list[dict]] = {}
    missing = []
    for e in elements:
        p = SUMMARY_DIR / f"element_{e['id']}.json"
        if not p.exists():
            missing.append(e["id"])
            continue
        summaries[e["id"]] = json.loads(
            p.read_text(encoding="utf-8")).get("history", [])
    if missing:
        raise SystemExit(
            f"VIRHE: {len(missing)} element-summary-tiedostoa puuttuu "
            f"cachesta (esim. {missing[:5]}) — EI haeta verkosta (palauttaisi "
            f"tyhjän 26/27-datan). Aja koneella jolla täysi 2526-cache on.")
    n_rows = sum(len(h) for h in summaries.values())
    print(f"[2/3] {len(summaries)} historiaa levycachesta ({n_rows} riviä); "
          f"BPS-oikaisu 26/27-sääntöihin (#151)...")
    summaries = xp.adjust_summaries_bps_2627(summaries)

    players: dict[str, dict] = {}
    for e in elements:
        pid, code, pos = e["id"], e["code"], e["element_type"]
        hist = summaries.get(pid, [])
        acc = xp.accumulate_history(hist)
        acc["dc_hits"] = xp.count_dc_hits(hist, pos)
        mins_by_round: dict[str, float] = {}
        starts_by_round: dict[str, int] = {}
        for r in hist:
            rnd = r.get("round")
            if rnd is None:
                continue
            k = str(rnd)
            mins_by_round[k] = mins_by_round.get(k, 0.0) + (r.get("minutes", 0) or 0)
            starts_by_round[k] = starts_by_round.get(k, 0) + (r.get("starts", 0) or 0)
        players[str(code)] = {
            "web_name": e["web_name"],
            "element_type": pos,
            "total_points": e.get("total_points", 0),
            "acc": acc,
            "mins_by_round": mins_by_round,
            "starts_by_round": starts_by_round,
        }

    out = {
        "meta": {
            "season": "2025/26",
            "season_key": SEASON_KEY,
            "generated_at": _dt.datetime.now().isoformat(timespec="seconds"),
            "source": ("FPL element-summary per-GW-historia, jäädytetty "
                       "lokaalista levycachesta 26/27-flipin jälkeen "
                       "(data ei enää saatavissa API:sta)"),
            "bps_rules": "2026/27 recalibrated (#151) — EI oikaista uudelleen",
            "n_players": len(players),
            "n_history_rows": n_rows,
            "key": "FPL element code (pysyvä kausien yli; 26/27-mappaus "
                   "bootstrap elements[].code)",
        },
        "players": players,
    }
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    size_kb = OUT_PATH.stat().st_size / 1024
    print(f"[3/3] -> {OUT_PATH}  ({len(players)} pelaajaa, {size_kb:.0f} kB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
