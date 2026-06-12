"""Name-alias-resolvointi 3 nimiavaruudessa (martj42 / FD / variantit).

Pytest-portti scripts/test_wc_teams.py:n tarkistuksista (#79 vaihe 2).
"""
from __future__ import annotations

import pytest

from src.data.international_results import lataa, wc2026_participants
from src.data.wc_teams import WC2026_TEAMS, WC2026_TEAMS_SET, resolve_wc_name


def test_48_unique_canonical_teams():
    assert len(WC2026_TEAMS) == 48
    assert len(WC2026_TEAMS_SET) == 48, "WC2026_TEAMS sisältää duplikaatteja"


def test_canonical_names_resolve_to_themselves():
    for t in WC2026_TEAMS:
        assert resolve_wc_name(t) == t


def test_martj42_participants_resolve_with_zero_drops():
    """Datasta johdetut 2026-osallistujat (martj42-nimet) -> kanoninen, 0 pudotusta."""
    participants = wc2026_participants()
    assert len(participants) == 48
    resolved = {resolve_wc_name(t) for t in participants}
    assert None not in resolved, (
        f"pudotukset: {sorted(t for t in participants if resolve_wc_name(t) is None)}")
    assert resolved == WC2026_TEAMS_SET


@pytest.mark.parametrize("variant,canon", [
    # martj42 <-> FD (todelliset erot treenidatassa)
    ("Bosnia and Herzegovina", "Bosnia-Herzegovina"),
    ("Cape Verde", "Cape Verde Islands"),
    ("Czech Republic", "Czechia"),
    ("DR Congo", "Congo DR"),
    # frontend/uutislähde-variantit
    ("Korea Republic", "South Korea"),
    ("Côte d'Ivoire", "Ivory Coast"),
    ("Türkiye", "Turkey"),
    ("USA", "United States"),
    ("IR Iran", "Iran"),
    ("Curacao", "Curaçao"),
    ("  south korea ", "South Korea"),  # whitespace + case + fold
])
def test_alias_resolves(variant, canon):
    assert resolve_wc_name(variant) == canon


@pytest.mark.parametrize("name", ["Finland", "Italy", "", None, "Nowhere FC"])
def test_non_wc_name_resolves_to_none(name):
    assert resolve_wc_name(name) is None


def test_loader_output_is_canonical():
    """Loaderin jälkeen kaikki 48 WC-maata df:ssä kanonisina, ei martj42-vuotoja."""
    df = lataa(window_start="2022-01-01", include="any")
    teams = set(df["home_team"]) | set(df["away_team"])
    assert teams & WC2026_TEAMS_SET == WC2026_TEAMS_SET, (
        f"loaderista puuttuu: {sorted(WC2026_TEAMS_SET - teams)}")
    leaked = teams & {"Bosnia and Herzegovina", "Cape Verde", "Czech Republic", "DR Congo"}
    assert not leaked, f"kanonisoimattomia martj42-nimiä: {sorted(leaked)}"
