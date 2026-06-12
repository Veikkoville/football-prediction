"""Dynaaminen kausi-resolvointi (config.current_season*): kausiraja elo-touko.

Frontend (goaliq-app lib/season.ts) käyttää identtistä algoritmia — jos sääntö
muuttuu täällä, muuta myös siellä (ristiviittaus molempien docstringeissä).
"""
from __future__ import annotations

from datetime import date

import config


def test_season_boundary_july_to_august():
    """Speksattu raja: 31.7. -> 2526, 1.8. -> 2627."""
    assert config.current_season(date(2026, 7, 31)) == "2526"
    assert config.current_season(date(2026, 8, 1)) == "2627"


def test_season_within_year():
    assert config.current_season(date(2026, 1, 1)) == "2526"    # kevätkierros
    assert config.current_season(date(2026, 5, 24)) == "2526"   # kauden finaali
    assert config.current_season(date(2026, 12, 31)) == "2627"  # syyskierros
    assert config.current_season(date(2027, 1, 15)) == "2627"   # sama kausi jatkuu


def test_season_pair_boundary():
    assert config.current_season_pair(date(2026, 7, 31)) == ["2425", "2526"]
    assert config.current_season_pair(date(2026, 8, 1)) == ["2526", "2627"]


def test_century_wrap():
    assert config.current_season(date(2099, 9, 1)) == "9900"
    assert config.current_season_pair(date(2100, 2, 1)) == ["9899", "9900"]


def test_seasons_since():
    s = config.seasons_since("2122", today=date(2026, 6, 12))
    assert s == ["2122", "2223", "2324", "2425", "2526"]
    assert config.seasons_since("2122", today=date(2026, 8, 1))[-1] == "2627"


def test_api_defaults_use_dynamic_pair():
    """Endpoint-defaultit seuraavat resolvointia (tänään == 2425+2526 →
    bittitarkkuus säilyy; 1.8. jälkeen siirtyvät automaattisesti)."""
    from api.main import WARMUP_LEAGUES, PredictionRequest, ParlayLeg
    pair = config.current_season_pair()
    assert PredictionRequest(home_team="a", away_team="b").seasons == pair
    assert ParlayLeg(home_team="a", away_team="b", pick="1").seasons == pair
    assert all(list(seasons) == pair for _, seasons in WARMUP_LEAGUES)
