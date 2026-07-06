"""FPL-saatavuuslogiikan testit (QUEUE #16 — deadline-tuoreus).

availability_factor on tihennetyn refreshin ydin: tuore FPL-status skaalaa
xMins→xP:n samassa ajossa. Nämä testit lukitsevat statuskartan:
a=pelattavissa, d=epävarma (chance-% tai 0.5), i/s/u/n=sivussa.
"""
from __future__ import annotations

import pytest

from scripts.build_fpl_xp import availability_factor


def test_available_full_factor():
    assert availability_factor({"status": "a"}) == 1.0


def test_missing_status_defaults_available():
    assert availability_factor({}) == 1.0


def test_doubtful_scales_by_chance():
    assert availability_factor(
        {"status": "d", "chance_of_playing_next_round": 75}) == 0.75
    assert availability_factor(
        {"status": "d", "chance_of_playing_next_round": 25}) == 0.25


def test_doubtful_without_chance_is_half():
    assert availability_factor(
        {"status": "d", "chance_of_playing_next_round": None}) == 0.5


@pytest.mark.parametrize("status", ["i", "s", "u", "n"])
def test_out_statuses_zero(status: str):
    assert availability_factor({"status": status}) == 0.0
