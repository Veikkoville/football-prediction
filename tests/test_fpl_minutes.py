"""#33: Ennustettujen minuuttien (start% × xMins) yksikkötestit.

Kattaa: p_start-rajat, saatavuus-gate (injured → 0), syvyys-korjauksen
suunta + cap, ruuhka-kertoimen rajat, shrinkage-eriytyksen (xmins raa'asta,
p_start kalibroituna) ja confidence-mappauksen determinismin.
"""
from __future__ import annotations

import pytest

from src.models import fpl_xp as xp


def _mm(mins: dict[int, float], starts: dict[int, int],
        rounds: list[int], n_last=xp.START_WINDOW):
    return xp.minutes_model(mins, starts, rounds, n_last=n_last)


def test_nailed_on_starter():
    rounds = [1, 2, 3, 4]
    mm = _mm({r: 90.0 for r in rounds}, {r: 1 for r in rounds}, rounds)
    assert mm["p_start_raw"] == pytest.approx(1.0)
    # näytettävä p_start shrinkattu prioria kohti — EI väitä 100 % varmuutta
    assert mm["p_start"] == pytest.approx(
        (1 - xp.P_START_SHRINK) * 1.0 + xp.P_START_SHRINK * xp.P_START_PRIOR)
    assert mm["xmins"] == pytest.approx(90.0)   # minuutit raa'asta sharesta
    assert mm["p60"] == pytest.approx(1.0)
    assert mm["confidence"] == "high"


def test_p_start_bounds_and_bench_player():
    rounds = [1, 2, 3, 4]
    mm = _mm({r: 0.0 for r in rounds}, {}, rounds)
    assert 0.0 <= mm["p_start"] <= 1.0
    assert mm["p_start_raw"] == 0.0
    assert mm["xmins"] == 0.0                    # ei startteja, ei nousuja
    assert mm["confidence"] == "high"            # vakaa "ei pelaa" -signaali


def test_sub_pathway():
    rounds = [1, 2, 3, 4]
    # nousee joka kierros penkiltä 20 minuutiksi
    mm = _mm({r: 20.0 for r in rounds}, {}, rounds)
    assert mm["p_start_raw"] == 0.0
    assert mm["p_sub"] == pytest.approx(1.0)
    assert mm["xmins"] == pytest.approx(20.0)
    assert mm["p60"] == 0.0 and mm["p1_59"] == pytest.approx(1.0)


def test_no_rounds_returns_zero_minutes():
    mm = _mm({}, {}, [])
    assert mm["xmins"] == 0.0 and mm["confidence"] == "low"


def test_injured_zeroes_minutes():
    rounds = [1, 2, 3, 4]
    mm = _mm({r: 90.0 for r in rounds}, {r: 1 for r in rounds}, rounds)
    out = xp.apply_availability(mm, "i", None)
    assert out["xmins"] == pytest.approx(0.0)
    assert out["p_start"] == 0.0 and out["p_start_raw"] == 0.0
    # alkuperäinen ei mutatoidu
    assert mm["xmins"] == pytest.approx(90.0)


def test_doubtful_scales_by_chance():
    rounds = [1, 2, 3, 4]
    mm = _mm({r: 90.0 for r in rounds}, {r: 1 for r in rounds}, rounds)
    out = xp.apply_availability(mm, "d", 75)
    assert out["xmins"] == pytest.approx(0.75 * 90.0)
    out_none = xp.apply_availability(mm, "d", None)
    assert out_none["xmins"] == pytest.approx(0.5 * 90.0)


def test_depth_factor_thin_squad_boosts_capped():
    # kilpailija pudonnut (esim. injured nollasi) → Σp_start 2.5 < slots 4
    f = xp.depth_factor([1.0, 1.0, 0.5], 4.0)
    assert f == xp.DEPTH_BOOST_CAP                # nosto capattu
    # ylibuukattu ryhmä skaalataan alas rajatta
    f_down = xp.depth_factor([1.0, 1.0, 1.0, 1.0, 1.0], 4.0)
    assert f_down == pytest.approx(0.8)
    # degeneroitunut ryhmä → neutraali
    assert xp.depth_factor([0.0, 0.0], 4.0) == 1.0
    assert xp.depth_factor([1.0], 0.0) == 1.0


def test_scale_p_start_caps_at_one():
    rounds = [1, 2, 3, 4]
    mm = _mm({r: 90.0 for r in rounds}, {r: 1 for r in rounds}, rounds)
    out = xp.scale_p_start(mm, 1.5)
    assert out["p_start_raw"] == 1.0 and out["p_start"] <= 1.0
    assert out["xmins"] <= 90.0 + 1e-9


def test_congestion_multiplier_bounds():
    # tupla-GW + kärkiminuutit → CONGESTION_MULT, ei koskaan negatiivinen/nolla
    assert xp.congestion_multiplier(2, 85.0) == xp.CONGESTION_MULT
    assert 0.0 < xp.CONGESTION_MULT < 1.0
    # yksi ottelu tai matalat minuutit → neutraali
    assert xp.congestion_multiplier(1, 85.0) == 1.0
    assert xp.congestion_multiplier(2, 30.0) == 1.0
    assert xp.congestion_multiplier(0, 85.0) == 1.0


def test_confidence_mapping_deterministic():
    rounds = [1, 2, 3, 4]
    # rotaatiopelaaja (p_start ~0.5) → ei "high" vaikka otos täysi
    mm = _mm({1: 90.0, 2: 0.0, 3: 90.0, 4: 0.0},
             {1: 1, 3: 1}, rounds)
    assert mm["confidence"] == "med"
    # lyhyt historia → low
    mm2 = _mm({1: 90.0}, {1: 1}, [1], n_last=4)
    assert mm2["confidence"] == "low"


def test_recompute_idempotent():
    rounds = [1, 2, 3, 4]
    mm = _mm({1: 90.0, 2: 60.0, 3: 20.0, 4: 90.0}, {1: 1, 2: 1, 4: 1}, rounds)
    once = dict(mm)
    twice = xp.recompute_minutes(dict(mm))
    for k in ("xmins", "p60", "p1_59"):
        assert twice[k] == pytest.approx(once[k])
