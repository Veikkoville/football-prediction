"""Gate-funktioiden testit: backtest _score/evaluate -muoto + sanity() erikseen.

Varmistaa että refresh_wc_model-putken rakennuspalikat pysyvät ajettavina ja
palauttavat odotetun muodon (#79 vaihe 5 + virkistysputki).
"""
from __future__ import annotations

import json
import math

import numpy as np
import pytest

import config
from scripts.backtest_wc import CUTOFF, TEST_TOURNAMENTS, _prep, _score, evaluate
from scripts.tune_wc_elo import sanity
from src.data.wc_teams import WC2026_TEAMS_SET
from src.models.dixon_coles import DixonColesModel


@pytest.fixture(scope="module")
def live_model() -> DixonColesModel:
    with open(config.DATA_DIR / "wc_model.json", encoding="utf-8") as f:
        d = json.load(f)
    return DixonColesModel(
        attack=d["attack"], defence=d["defence"],
        home_advantage=d["home_advantage"],
        home_advantage_per_team=d["home_advantage_per_team"],
        rho=d["rho"], teams_=d["teams_"],
        per_team_home_adv=d.get("per_team_home_adv", False),
        model_type_=d.get("model_type_", "dc"),
    )


def test_score_uniform_known_values():
    """Käsinlasketut arvot: p=[1/3,1/3,1/3], toteuma=kotivoitto."""
    ll, brier, rps = _score([1 / 3, 1 / 3, 1 / 3], 0)
    assert ll == pytest.approx(math.log(3), abs=1e-12)
    assert brier == pytest.approx(2 / 3, abs=1e-12)
    assert rps == pytest.approx(0.5 * ((1 / 3 - 1) ** 2 + (2 / 3 - 1) ** 2), abs=1e-12)


def test_score_perfect_prediction_near_zero():
    ll, brier, rps = _score([1.0, 0.0, 0.0], 0)
    assert ll == pytest.approx(0.0, abs=1e-9)
    assert brier == pytest.approx(0.0, abs=1e-9)
    assert rps == pytest.approx(0.0, abs=1e-9)


def test_evaluate_shape_and_ranges(live_model):
    """evaluate() palauttaa dict(n, logloss, brier, rps) järkevillä arvoilla."""
    raw = _prep()
    test = raw[(raw["date"] >= CUTOFF) & raw["tournament"].isin(TEST_TOURNAMENTS)]
    ev = evaluate(live_model, test, allowed=set(live_model.teams_) & WC2026_TEAMS_SET)
    assert ev is not None
    assert set(ev) == {"n", "logloss", "brier", "rps"}
    assert ev["n"] > 0
    assert 0.0 < ev["logloss"] < math.log(3) * 2, "log-loss kaukana järkevästä"
    assert 0.0 < ev["brier"] < 2.0
    assert 0.0 < ev["rps"] < 1.0
    assert all(np.isfinite(ev[k]) for k in ("logloss", "brier", "rps"))


def test_evaluate_empty_testset_returns_none(live_model):
    raw = _prep()
    empty = raw[raw["date"] > raw["date"].max()]
    assert evaluate(live_model, empty, allowed=WC2026_TEAMS_SET) is None


def test_sanity_runs_standalone_and_passes_on_live_model(live_model):
    """sanity() ajettavissa erikseen; live-mallin pitää läpäistä kaikki 5 ehtoa
    (sama malli on tuotannossa — FAIL tässä = tuotannossa on sanity-rikkomus)."""
    checks, info = sanity(live_model)
    assert set(checks) == {"NED>JPN", "no AFC/CONCACAF top6", "Japan out of top6",
                           "top12 vs Elo >=8", "no Elo-inversions(gap>=25)"}
    failed = [k for k, v in checks.items() if not v]
    assert not failed, f"live-malli rikkoo sanity-ehtoja: {failed} (info: {info})"
    assert info["jpn_rank"] > 6
    assert len(info["top6"]) == 6
