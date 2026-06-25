"""
Verifioitava tarkkuus-track-record (#100).

Putki kahdessa vaiheessa:

  1. PREDICTION-LOG — ennustushetkellä (ennen kickoffia) logataan mallin
     julkaistu ennuste jokaiselle oikealle ottelulle: 1X2-todennäköisyydet,
     odotetut maalit (xG), todennäköisin tulos. Lukitaan = ei muutu vaikka
     malli myöhemmin virkistetään → ennuste on aidosti pre-match.

  2. RESULTS-RECONCILE — ottelun jälkeen haetaan FT-tulos ja täytetään
     toteutunut: 1X2-osuma, exact-score-osuma. Tästä lasketaan aggregaatti
     (rolling N + all-time): 1X2 %, exact %, Brier, kalibraatio.

Pysyväistallennus = committoidut JSON-tiedostot (data/prediction_log.json +
data/accuracy.json), samaa mallia kuin data/wc_model.json. Render-levy on
efemeerinen → ajastettu LOKAALI skripti (scripts/accuracy_pipeline.py,
Task Scheduler) ylläpitää tiedostoja ja Ville pushaa = Render lukee committatun
aggregaatin. GET /api/accuracy lukee VAIN aggregaatin (ei laskentaa pyynnössä).

Brier/kalibraatio nojaa olemassa olevaan backtest-infraan
(src.models.backtest.laske_metriikat + kalibrointi_data) — sama metriikka kuin
walk-forward-backtestissä, jotta luvut ovat vertailukelpoisia.
"""

from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import config

# ---------------------------------------------------------------------------
# Tiedostopolut (committoitu data, kuten wc_model.json / elo_ratings.csv)
# ---------------------------------------------------------------------------
LOG_PATH: Path = config.DATA_DIR / "prediction_log.json"
AGGREGATE_PATH: Path = config.DATA_DIR / "accuracy.json"

LOG_VERSION = 1
DEFAULT_ROLLING_WINDOW = 100
DEFAULT_RECENT_N = 20
# Pieni-otoksiset metriikat (exact-score, Brier) eivät ole tilastollisesti
# mielekkäitä pienellä n:llä → näytetään vasta kun ali-otos >= tämä. Alle rajan
# pct_exact/brier = null (frontend → "Coming soon"/"—"), ettei näytetä
# harhaanjohtavaa "0 %"/"0.30" muutamasta ottelusta. Koskee all_time + rolling.
MIN_DISPLAY_N = 30


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# ---------------------------------------------------------------------------
# Pien-helpurit (tulos -> 1X2)
# ---------------------------------------------------------------------------
def outcome_from_score(home_score: int, away_score: int) -> str:
    """Tulos 1X2-luokaksi merkkijonona."""
    if home_score > away_score:
        return "home"
    if home_score < away_score:
        return "away"
    return "draw"


def named_winner(p_home: float, p_away: float) -> str:
    """Mallin nimeämä voittaja kahden joukkueen välillä (ei koskaan 'draw').

    Vastaa julkaistua "called it" -metodologiaa: malli nimeää AINA
    todennäköisemmän voittajan. Tasapeli lasketaan tällöin missiksi
    headline-1X2-luvussa (rehellinen: WC-hubin 21/40 = 52 % perustuu tähän).
    """
    return "home" if p_home >= p_away else "away"


# ---------------------------------------------------------------------------
# WC pre-match -ennuste (mirror /api/predict-wc -neutraloinnista)
# ---------------------------------------------------------------------------
# HUOM: TÄMÄ ON PEILI predict_wc():n neutralointilogiikasta (api/main.py).
# Endpointia EI refaktoroida jaettuun helperiin, jotta hot-polku + golden-
# testit pysyvät koskemattomina (CLAUDE.md: verifoi WC käänteisparilla aina kun
# DC-parametreja muutetaan). Jos predict_wc():n neutralointi muuttuu, päivitä
# myös tämä — symmetria-testi tests/test_accuracy.py vahtii peilin yhtenevyyttä.
def wc_prematch_prediction(home_team: str, away_team: str) -> Optional[dict]:
    """Tuota mallin pre-match-ennuste WC-ottelulle kanonisilla nimillä.

    Palauttaa None jos jompikumpi joukkue ei ole WC2026-maa tai mallista
    puuttuu data. Muuten dict: p_home/p_draw/p_away, xg_home/xg_away,
    most_likely_score ("h-a"), predicted_winner, home_team/away_team (kanoniset).
    """
    from src.data.wc_teams import resolve_wc_name
    from src.data.international_results import load_wc_model

    home_canon = resolve_wc_name(home_team)
    away_canon = resolve_wc_name(away_team)
    if home_canon is None or away_canon is None:
        return None

    try:
        dc_cached = load_wc_model()
    except Exception:
        return None

    # Neutraali venue: γ/2 molemmille (peili predict_wc:stä).
    dc = copy.copy(dc_cached)
    half_home_adv = dc_cached.home_advantage / 2.0
    dc.defence = {t: v + half_home_adv for t, v in dc_cached.defence.items()}
    dc.home_advantage = 0.0
    dc.home_advantage_per_team = {t: 0.0 for t in dc.teams_}

    if home_canon not in dc.attack or away_canon not in dc.attack:
        return None

    lam, mu = dc.expected_goals(home_canon, away_canon)
    p = dc.predict_1x2(home_canon, away_canon)
    top = dc.todennakoisin_tulos(home_canon, away_canon, top_n=1)
    mls = top[0][0] if top else None

    return {
        "home_team": home_canon,
        "away_team": away_canon,
        "p_home": round(float(p["home"]), 4),
        "p_draw": round(float(p["draw"]), 4),
        "p_away": round(float(p["away"]), 4),
        "xg_home": round(float(lam), 3),
        "xg_away": round(float(mu), 3),
        "most_likely_score": mls,
        "predicted_winner": named_winner(p["home"], p["away"]),
    }


# ---------------------------------------------------------------------------
# Logi-IO
# ---------------------------------------------------------------------------
def empty_log() -> dict:
    return {"version": LOG_VERSION, "predictions": []}


def load_log(path: Path = LOG_PATH) -> dict:
    if not path.exists():
        return empty_log()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return empty_log()
    if not isinstance(data, dict) or "predictions" not in data:
        return empty_log()
    return data


def save_log(log: dict, path: Path = LOG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")


def _index_by_id(log: dict) -> dict[str, dict]:
    return {e["match_id"]: e for e in log["predictions"] if e.get("match_id")}


def upsert_prediction(log: dict, entry: dict) -> bool:
    """Lisää ennuste logiin jos match_id on uusi. Idempotentti: jo logattua
    ennustetta EI ylikirjoiteta (pre-match-lukko — ennuste ei muutu). Palauttaa
    True jos uusi rivi lisättiin.
    """
    idx = _index_by_id(log)
    mid = entry.get("match_id")
    if not mid or mid in idx:
        return False
    log["predictions"].append(entry)
    return True


def set_result(
    log: dict,
    match_id: str,
    home_score: int,
    away_score: int,
) -> bool:
    """Täytä toteutunut tulos logatulle ennusteelle. Idempotentti: jo
    reconciloitua ei muuteta. Palauttaa True jos tulos kirjattiin nyt.
    """
    idx = _index_by_id(log)
    entry = idx.get(match_id)
    if entry is None or entry.get("result") is not None:
        return False

    actual = outcome_from_score(home_score, away_score)
    pred_winner = entry.get("predicted_winner")
    mls = entry.get("most_likely_score")
    actual_score = f"{int(home_score)}-{int(away_score)}"

    entry["result"] = {
        "home_score": int(home_score),
        "away_score": int(away_score),
        "actual_score": actual_score,
        "actual_outcome": actual,
        # headline-1X2: nimetty voittaja vs toteutunut (tasapeli = miss)
        "hit_1x2": bool(pred_winner is not None and pred_winner == actual),
        # exact-score vain jos most_likely_score tunnetaan (FD-rivit, ei seed)
        "exact_hit": (None if mls is None else bool(mls == actual_score)),
        "reconciled_at": _now_iso(),
    }
    return True


# ---------------------------------------------------------------------------
# Aggregaatin laskenta (reuse backtest-infra)
# ---------------------------------------------------------------------------
def _resolved(log: dict) -> list[dict]:
    """Ennusteet joilla on toteutunut tulos, aikajärjestyksessä (vanhin->uusin)."""
    rows = [e for e in log["predictions"] if e.get("result")]
    rows.sort(key=lambda e: (e.get("date") or "", e.get("logged_at") or ""))
    return rows


def _metrics_block(rows: list[dict]) -> dict:
    """1X2-, decisive- ja exact-osumat + Brier/n riviltä."""
    n = len(rows)
    correct = sum(1 for e in rows if e["result"]["hit_1x2"])
    decisive = [e for e in rows if e["result"]["actual_outcome"] != "draw"]
    decisive_correct = sum(1 for e in decisive if e["result"]["hit_1x2"])

    exact_rows = [e for e in rows if e["result"]["exact_hit"] is not None]
    exact_correct = sum(1 for e in exact_rows if e["result"]["exact_hit"])

    block = {
        "n": n,
        "correct_1x2": correct,
        "pct_1x2": round(correct / n, 4) if n else None,
        "decisive_n": len(decisive),
        "decisive_correct": decisive_correct,
        "pct_decisive": round(decisive_correct / len(decisive), 4) if decisive else None,
        "exact_n": len(exact_rows),
        "exact_correct": exact_correct,
        "pct_exact": round(exact_correct / len(exact_rows), 4) if exact_rows else None,
    }

    brier = _brier(rows)
    block["brier"] = brier["brier"]
    block["brier_n"] = brier["n"]

    # Gate pieni-otoksiset metriikat (ks. MIN_DISPLAY_N). exact_n/brier_n säilyvät
    # raportoituina (data kertyy taustalla), vain näytettävä arvo nullataan.
    if block["exact_n"] < MIN_DISPLAY_N:
        block["pct_exact"] = None
    if block["brier_n"] < MIN_DISPLAY_N:
        block["brier"] = None
    return block


def _full_prob_rows(rows: list[dict]) -> list[dict]:
    """Rivit joilla on täysi 1X2-jakauma (FD-rivit; seed-rivit pudotetaan)."""
    out = []
    for e in rows:
        if e.get("p_home") is None or e.get("p_draw") is None or e.get("p_away") is None:
            continue
        out.append(e)
    return out


def _brier(rows: list[dict]) -> dict:
    """Multi-class Brier täyden jakauman riveiltä (reuse backtest.laske_metriikat)."""
    full = _full_prob_rows(rows)
    if not full:
        return {"brier": None, "n": 0}
    try:
        import pandas as pd
        from src.models.backtest import laske_metriikat
    except Exception:
        return {"brier": None, "n": 0}

    code = {"home": 0, "draw": 1, "away": 2}
    df = pd.DataFrame([
        {
            "p_home": e["p_home"],
            "p_draw": e["p_draw"],
            "p_away": e["p_away"],
            "actual_1x2": code[e["result"]["actual_outcome"]],
        }
        for e in full
    ])
    m = laske_metriikat(df)
    brier = m.get("brier")
    return {
        "brier": (None if brier is None or brier != brier else round(float(brier), 4)),
        "n": int(m.get("n", 0)),
    }


def _calibration(rows: list[dict], n_bins: int = 10) -> list[dict]:
    """Reliability-data täyden jakauman riveiltä (reuse backtest.kalibrointi_data)."""
    full = _full_prob_rows(rows)
    if not full:
        return []
    try:
        import pandas as pd
        from src.models.backtest import kalibrointi_data
    except Exception:
        return []

    code = {"home": 0, "draw": 1, "away": 2}
    df = pd.DataFrame([
        {
            "p_home": e["p_home"],
            "p_draw": e["p_draw"],
            "p_away": e["p_away"],
            "actual_1x2": code[e["result"]["actual_outcome"]],
        }
        for e in full
    ])
    cal = kalibrointi_data(df, n_bins=n_bins)
    out = []
    for _, r in cal.iterrows():
        out.append({
            "bin_mid": round(float(r["bin_mid"]), 4),
            "predicted": round(float(r["ennustettu"]), 4),
            "actual": round(float(r["toteutunut"]), 4),
            "n": int(r["n"]),
        })
    return out


def _recent_view(rows: list[dict], recent_n: int) -> list[dict]:
    """Viimeisimmät ottelut rehellistä missit-näyttöä varten (uusin ensin)."""
    out = []
    for e in rows[-recent_n:][::-1]:
        res = e["result"]
        out.append({
            "date": e.get("date"),
            "home_team": e.get("home_team"),
            "away_team": e.get("away_team"),
            "predicted_winner": e.get("predicted_winner"),
            "p_winner": _winner_pct(e),
            "most_likely_score": e.get("most_likely_score"),
            "actual_score": res["actual_score"],
            "actual_outcome": res["actual_outcome"],
            "hit_1x2": res["hit_1x2"],
            "exact_hit": res["exact_hit"],
        })
    return out


def _winner_pct(e: dict) -> Optional[float]:
    """Nimetyn voittajan voittotodennäköisyys (näyttöä varten)."""
    pw = e.get("predicted_winner")
    if pw == "home" and e.get("p_home") is not None:
        return round(float(e["p_home"]), 4)
    if pw == "away" and e.get("p_away") is not None:
        return round(float(e["p_away"]), 4)
    return None


def compute_aggregate(
    log: dict,
    rolling_window: int = DEFAULT_ROLLING_WINDOW,
    recent_n: int = DEFAULT_RECENT_N,
) -> dict:
    """Laske GET /api/accuracy -aggregaatti logista."""
    rows = _resolved(log)
    pending = sum(1 for e in log["predictions"] if not e.get("result"))

    all_time = _metrics_block(rows)
    rolling_rows = rows[-rolling_window:]
    rolling = _metrics_block(rolling_rows)
    rolling["window"] = rolling_window

    return {
        "updated_at": _now_iso(),
        "logged_total": len(log["predictions"]),
        "pending": pending,
        "all_time": all_time,
        "rolling": rolling,
        "calibration": _calibration(rows),
        "recent": _recent_view(rows, recent_n),
    }


def empty_aggregate() -> dict:
    base = {
        "n": 0, "correct_1x2": 0, "pct_1x2": None,
        "decisive_n": 0, "decisive_correct": 0, "pct_decisive": None,
        "exact_n": 0, "exact_correct": 0, "pct_exact": None,
        "brier": None, "brier_n": 0,
    }
    return {
        "updated_at": _now_iso(),
        "logged_total": 0,
        "pending": 0,
        "all_time": dict(base),
        "rolling": {**base, "window": DEFAULT_ROLLING_WINDOW},
        "calibration": [],
        "recent": [],
    }


def load_aggregate(path: Path = AGGREGATE_PATH) -> dict:
    if not path.exists():
        return empty_aggregate()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return empty_aggregate()
    if not isinstance(data, dict) or "all_time" not in data:
        return empty_aggregate()
    return data


def save_aggregate(agg: dict, path: Path = AGGREGATE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(agg, ensure_ascii=False, indent=2), encoding="utf-8")


def recompute_and_save(
    log: dict,
    rolling_window: int = DEFAULT_ROLLING_WINDOW,
    recent_n: int = DEFAULT_RECENT_N,
) -> dict:
    agg = compute_aggregate(log, rolling_window=rolling_window, recent_n=recent_n)
    save_aggregate(agg)
    return agg
