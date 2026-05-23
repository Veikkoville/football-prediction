"""
#69 manuaalitesti: in-memory TTL-cache turnauskausille.

Aja: python scripts/test_69_tournament_ttl.py
"""
from __future__ import annotations
import sys
import time
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.data import football_data_org as fdo


class FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None, text: str = ""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text
        self.content = b"{}"

    def json(self):
        return self._payload


def _reset():
    fdo._TOURNAMENT_MEM_CACHE.clear()


def test_is_live_tournament():
    current_year = time.gmtime().tm_year
    assert fdo._is_live_tournament("WC", str(current_year)) is True
    assert fdo._is_live_tournament("EC", str(current_year)) is True
    assert fdo._is_live_tournament("WC", "2018") is False, "menneitä turnauksia ei refreshatä"
    assert fdo._is_live_tournament("PL", str(current_year)) is False, "PL ei ole turnaus"
    assert fdo._is_live_tournament("PL", "2425") is False
    assert fdo._is_live_tournament("WC", "nonsense") is False
    print("[OK] _is_live_tournament")


def test_tournament_memory_cache_hit():
    """Toinen kutsu TTL:n sisällä -> muistista, ei API-kutsua."""
    _reset()
    payload = {"matches": [{"id": 1, "status": "FINISHED",
                            "score": {"fullTime": {"home": 1, "away": 0}},
                            "homeTeam": {"name": "A"}, "awayTeam": {"name": "B"},
                            "utcDate": "2026-06-15T18:00:00Z"}]}
    current_year = str(time.gmtime().tm_year)
    calls = {"n": 0}

    def fake_get(url, headers=None, timeout=None):
        calls["n"] += 1
        return FakeResponse(200, payload)

    with patch.object(fdo.requests, "get", side_effect=fake_get):
        d1 = fdo._hae_kausi("WC", current_year, "fake-key")
        d2 = fdo._hae_kausi("WC", current_year, "fake-key")
    assert calls["n"] == 1, f"odotettu 1 API-kutsu, saatu {calls['n']}"
    assert d1 == payload and d2 == payload
    print(f"[OK] memory hit TTL:n sisällä (API-kutsut: {calls['n']})")


def test_tournament_ttl_expiry():
    """TTL:n umpeuduttua -> uusi API-haku."""
    _reset()
    payload = {"matches": []}
    current_year = str(time.gmtime().tm_year)
    calls = {"n": 0}

    def fake_get(url, headers=None, timeout=None):
        calls["n"] += 1
        return FakeResponse(200, payload)

    with patch.object(fdo.requests, "get", side_effect=fake_get):
        fdo._hae_kausi("WC", current_year, "fake-key")
        # Pakota TTL:n umpeutuminen siirtämällä entry-aikaleimaa taaksepäin
        key = ("WC", current_year)
        old_ts, data = fdo._TOURNAMENT_MEM_CACHE[key]
        fdo._TOURNAMENT_MEM_CACHE[key] = (old_ts - fdo.TOURNAMENT_TTL_SEC - 1, data)
        fdo._hae_kausi("WC", current_year, "fake-key")
    assert calls["n"] == 2, f"TTL:n jälkeen pitäisi tulla 2. API-kutsu, saatu {calls['n']}"
    print(f"[OK] TTL-expiry triggeröi uudelleenhaun (API-kutsut: {calls['n']})")


def test_api_fail_disk_fallback():
    """API-virhe -> palaa levycacheen jos olemassa."""
    _reset()
    current_year = str(time.gmtime().tm_year)
    cache_path = fdo.CACHE_DIR / f"WC_{current_year}.json"
    backup = cache_path.read_bytes() if cache_path.exists() else None
    try:
        # > 100 tavua (loaderin sanity-check size > 100)
        cache_path.write_text(
            '{"matches": [{"id": 999, "padding": "' + "x" * 200 + '"}]}',
            encoding="utf-8",
        )

        def fake_get(url, headers=None, timeout=None):
            return FakeResponse(503, text="upstream down")

        with patch.object(fdo.requests, "get", side_effect=fake_get):
            data = fdo._hae_kausi("WC", current_year, "fake-key")
        assert isinstance(data, dict) and "matches" in data and data["matches"][0]["id"] == 999, \
            f"odotettu disk-fallback, saatu: {data}"
        print("[OK] API-virhe -> disk fallback")
    finally:
        if backup is not None:
            cache_path.write_bytes(backup)
        elif cache_path.exists():
            cache_path.unlink()


def test_domestic_unchanged():
    """Domestic-liigat (esim. PL_2425.json) käyttävät pelkkää levycachea, ei TTL-tarkistusta."""
    _reset()
    cache_path = fdo.CACHE_DIR / "PL_2024.json"
    backup = cache_path.read_bytes() if cache_path.exists() else None
    try:
        cache_path.write_text(
            '{"matches": [{"id": 42, "padding": "' + "x" * 200 + '"}]}',
            encoding="utf-8",
        )
        calls = {"n": 0}

        def fake_get(url, headers=None, timeout=None):
            calls["n"] += 1
            return FakeResponse(200, {"matches": []})

        with patch.object(fdo.requests, "get", side_effect=fake_get):
            d1 = fdo._hae_kausi("PL", "2024", "fake-key")
            d2 = fdo._hae_kausi("PL", "2024", "fake-key")
        assert calls["n"] == 0, f"domestic ei saa kutsua API:a kun disk-cache on, saatu {calls['n']}"
        assert d1["matches"][0]["id"] == 42 and d2 == d1
        assert ("PL", "2024") not in fdo._TOURNAMENT_MEM_CACHE, "domestic ei saa joutua TTL-muistiin"
        print(f"[OK] domestic-liigat ennallaan, ei TTL-koskettelua (API-kutsut: {calls['n']})")
    finally:
        if backup is not None:
            cache_path.write_bytes(backup)
        elif cache_path.exists():
            cache_path.unlink()


def test_past_tournament_seasons_unchanged():
    """WC_2018, WC_2022 -> ei TTL-tarkistusta (vuosi != kuluva), pelkkä levycache."""
    _reset()
    calls = {"n": 0}

    def fake_get(url, headers=None, timeout=None):
        calls["n"] += 1
        return FakeResponse(200, {"matches": []})

    cache_2018 = fdo.CACHE_DIR / "WC_2018.json"
    assert cache_2018.exists(), "test-edellytys: WC_2018.json on cachessa"
    with patch.object(fdo.requests, "get", side_effect=fake_get):
        d = fdo._hae_kausi("WC", "2018", "fake-key")
    assert calls["n"] == 0, "WC 2018 (menneisyys) ei saa API-kutsua"
    assert d is not None and "matches" in d
    assert ("WC", "2018") not in fdo._TOURNAMENT_MEM_CACHE
    print(f"[OK] WC 2018 menneisyys ennallaan (API-kutsut: {calls['n']})")


def test_tournament_last_refresh():
    _reset()
    assert fdo.tournament_last_refresh() == 0.0
    fdo._TOURNAMENT_MEM_CACHE[("WC", "2026")] = (1000.0, {})
    fdo._TOURNAMENT_MEM_CACHE[("EC", "2026")] = (2000.0, {})
    assert fdo.tournament_last_refresh() == 2000.0
    _reset()
    print("[OK] tournament_last_refresh palauttaa uusimman aikaleiman")


if __name__ == "__main__":
    test_is_live_tournament()
    test_tournament_memory_cache_hit()
    test_tournament_ttl_expiry()
    test_api_fail_disk_fallback()
    test_domestic_unchanged()
    test_past_tournament_seasons_unchanged()
    test_tournament_last_refresh()
    print("\n[ALL PASS]")
