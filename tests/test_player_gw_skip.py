"""build_fpl_player_gw: jäädytetyn basis-kauden SKIP-logiikka (13.8.2026).

Tausta: steppi failasi accuracy-logissa joka ajossa 9.8–13.8 (26 punaista
runia), koska jäädytetyn basis-kauden (2025/26) lähdecache elää vain
lokaalikoneella eikä sitä voi hakea FPL-API:sta. CI:ssä oikea tulos on
SKIP kun committoitu output on jo samalta kaudelta — ja aito virhe kun
kelvollista outputtia ei ole.
"""
from __future__ import annotations

import json

import pytest

import scripts.build_fpl_player_gw as gw


@pytest.fixture
def runner_ymparisto(monkeypatch, tmp_path):
    """CI-runnerin tila: STATS on (committoitu), FPL-cache puuttuu."""
    stats = tmp_path / "fpl_player_stats.json"
    stats.write_text(json.dumps({"meta": {"basis_season": "2025/26"}}),
                     encoding="utf-8")
    monkeypatch.setattr(gw, "STATS", stats)
    monkeypatch.setattr(gw, "CACHE", tmp_path / "raw_fpl")  # ei ole olemassa
    monkeypatch.setattr(gw, "OUT", tmp_path / "player-gw.json")
    return tmp_path


def test_skip_kun_output_on_samalta_jaadytetylta_kaudelta(runner_ymparisto):
    gw.OUT.write_text(json.dumps({"meta": {"basis_season": "2025/26"},
                                  "players": {}}), encoding="utf-8")
    assert gw.main() == 0


def test_virhe_kun_outputtia_ei_ole(runner_ymparisto):
    assert gw.main() == 1


def test_virhe_kun_output_on_vaaralta_kaudelta(runner_ymparisto):
    gw.OUT.write_text(json.dumps({"meta": {"basis_season": "2024/25"},
                                  "players": {}}), encoding="utf-8")
    assert gw.main() == 1


def test_rikkinainen_output_ei_kaada_vaan_failaa_siististi(runner_ymparisto):
    gw.OUT.write_text("ei-json{", encoding="utf-8")
    assert gw.main() == 1
