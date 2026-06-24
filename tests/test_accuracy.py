"""Tarkkuus-track-record -putken testit (#100).

Kattaa: 1X2/exact/decisive-osumalogiikan, aggregaatin (reuse backtest-Brier),
seed-parsinnan WC-hubista (= julkaistu 21/40), endpointin muodon ja
WC pre-match -helperin neutraali-venue-symmetrian (peili predict_wc:stä).
"""
from __future__ import annotations

import pytest

from src.models import accuracy as acc


# ---------------------------------------------------------------------------
# Pien-helpurit
# ---------------------------------------------------------------------------
def test_outcome_from_score():
    assert acc.outcome_from_score(2, 0) == "home"
    assert acc.outcome_from_score(1, 1) == "draw"
    assert acc.outcome_from_score(0, 3) == "away"


def test_named_winner_never_draw():
    assert acc.named_winner(0.6, 0.2) == "home"
    assert acc.named_winner(0.2, 0.5) == "away"
    # tasan -> home (deterministinen tie-break)
    assert acc.named_winner(0.3, 0.3) == "home"


# ---------------------------------------------------------------------------
# upsert + set_result idempotenssi + osumalogiikka
# ---------------------------------------------------------------------------
def _entry(mid, winner, mls=None, p=(None, None, None), date="2026-06-20"):
    return {
        "match_id": mid, "source": "test", "competition": "WC", "date": date,
        "home_team": "A", "away_team": "B",
        "p_home": p[0], "p_draw": p[1], "p_away": p[2],
        "xg_home": None, "xg_away": None,
        "most_likely_score": mls, "predicted_winner": winner,
        "logged_at": None, "result": None,
    }


def test_upsert_is_idempotent():
    log = acc.empty_log()
    assert acc.upsert_prediction(log, _entry("m1", "home")) is True
    assert acc.upsert_prediction(log, _entry("m1", "away")) is False  # ei ylikirjoita
    assert len(log["predictions"]) == 1
    assert log["predictions"][0]["predicted_winner"] == "home"


def test_set_result_hit_and_exact():
    log = acc.empty_log()
    acc.upsert_prediction(log, _entry("m1", "home", mls="2-1"))
    assert acc.set_result(log, "m1", 2, 1) is True
    res = log["predictions"][0]["result"]
    assert res["actual_outcome"] == "home"
    assert res["hit_1x2"] is True
    assert res["exact_hit"] is True
    assert res["actual_score"] == "2-1"
    # idempotentti: toinen reconcile ei muuta
    assert acc.set_result(log, "m1", 0, 5) is False


def test_set_result_draw_is_miss_for_named_winner():
    log = acc.empty_log()
    acc.upsert_prediction(log, _entry("m1", "home", mls="2-1"))
    acc.set_result(log, "m1", 1, 1)  # tasapeli
    res = log["predictions"][0]["result"]
    assert res["actual_outcome"] == "draw"
    assert res["hit_1x2"] is False
    assert res["exact_hit"] is False  # 2-1 != 1-1


def test_exact_hit_none_without_mls():
    log = acc.empty_log()
    acc.upsert_prediction(log, _entry("m1", "home", mls=None))  # seed-tyyppi
    acc.set_result(log, "m1", 3, 0)
    assert log["predictions"][0]["result"]["exact_hit"] is None


# ---------------------------------------------------------------------------
# Aggregaatti (sis. Brier täysiltä riveiltä)
# ---------------------------------------------------------------------------
def test_compute_aggregate_metrics():
    log = acc.empty_log()
    # 2 täyttä-jakauma-riviä + 1 seed-tyyppinen (vain voittaja)
    acc.upsert_prediction(log, _entry("f1", "home", mls="2-1", p=(0.6, 0.25, 0.15)))
    acc.upsert_prediction(log, _entry("f2", "away", mls="0-1", p=(0.2, 0.3, 0.5)))
    acc.upsert_prediction(log, _entry("s1", "home", mls=None, p=(None, None, None)))
    acc.set_result(log, "f1", 2, 1)   # home, exact hit
    acc.set_result(log, "f2", 1, 1)   # draw -> miss
    acc.set_result(log, "s1", 3, 0)   # home, hit (1x2)

    agg = acc.compute_aggregate(log)
    at = agg["all_time"]
    assert at["n"] == 3
    assert at["correct_1x2"] == 2          # f1 + s1
    assert at["pct_1x2"] == pytest.approx(2 / 3, abs=1e-4)
    assert at["decisive_n"] == 2           # f1 (home), s1 (home); f2 ended draw
    assert at["decisive_correct"] == 2
    assert at["exact_n"] == 2              # vain f1, f2 (mls tunnetaan)
    assert at["exact_correct"] == 1        # f1
    assert at["brier_n"] == 2              # vain täydet jakaumat
    assert at["brier"] is not None
    assert agg["pending"] == 0
    assert agg["logged_total"] == 3


def test_empty_aggregate_shape():
    agg = acc.empty_aggregate()
    assert agg["all_time"]["n"] == 0
    assert agg["all_time"]["pct_1x2"] is None
    assert agg["rolling"]["window"] == acc.DEFAULT_ROLLING_WINDOW
    assert agg["calibration"] == []
    assert agg["recent"] == []


# ---------------------------------------------------------------------------
# Seed-parsinta WC-hubista = julkaistu 21/40
# ---------------------------------------------------------------------------
def test_seed_parse_matches_published_record():
    from scripts.accuracy_pipeline import WC_HUB_HTML, parse_seed_rows
    rows = parse_seed_rows(WC_HUB_HTML.read_text(encoding="utf-8"))
    assert len(rows) == 40, f"odotettiin 40 seed-riviä, saatiin {len(rows)}"

    log = acc.empty_log()
    for r in rows:
        hs, as_ = r.pop("_seed_score")
        acc.upsert_prediction(log, r)
        acc.set_result(log, r["match_id"], hs, as_)
    at = acc.compute_aggregate(log)["all_time"]
    assert at["n"] == 40
    assert at["correct_1x2"] == 21          # WC-hubin julkaistu 21/40
    assert at["decisive_correct"] == 21
    assert at["decisive_n"] == 27           # 13 tasapeliä -> 27 ratkaisevaa
    assert at["pct_1x2"] == pytest.approx(0.525, abs=1e-3)


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------
def test_accuracy_endpoint_shape(client):
    r = client.get("/api/accuracy")
    assert r.status_code == 200
    b = r.json()
    for key in ("updated_at", "all_time", "rolling", "calibration", "recent"):
        assert key in b
    for key in ("n", "pct_1x2", "decisive_n", "exact_n", "brier"):
        assert key in b["all_time"]


# ---------------------------------------------------------------------------
# WC pre-match -helper: neutraali-venue-symmetria (peili predict_wc:stä)
# ---------------------------------------------------------------------------
def test_wc_prematch_symmetry():
    a = acc.wc_prematch_prediction("Brazil", "France")
    b = acc.wc_prematch_prediction("France", "Brazil")
    assert a is not None and b is not None
    assert a["p_home"] == pytest.approx(b["p_away"], abs=1e-9)
    assert a["p_away"] == pytest.approx(b["p_home"], abs=1e-9)
    assert a["p_draw"] == pytest.approx(b["p_draw"], abs=1e-9)
    assert a["xg_home"] == pytest.approx(b["xg_away"], abs=1e-9)
    assert a["xg_away"] == pytest.approx(b["xg_home"], abs=1e-9)
    # nimetty voittaja peilautuu
    assert {a["predicted_winner"], b["predicted_winner"]} <= {"home", "away"}


def test_wc_prematch_non_wc_team_returns_none():
    assert acc.wc_prematch_prediction("Finland", "Brazil") is None
