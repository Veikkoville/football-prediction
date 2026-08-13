"""SPL availability-override (13.8.2026): syötekorjaus kun pelin data on vanhentunut.

Tausta: RSL Fantasy näytti Enriquen (id 521) status 'a' vaikka toistuva
nilkkavamma + ohitti King's Cup -finaalin + yhteisöraportti leikkauksesta.
Lippumekanismi datassa toimii (29 muuta liputettu) — tämä yksi puuttui.
Override korjaa SYÖTTEEN (status/chance), ei lopputulosta: optimoija ja
kaikki kuluttajat näkevät saman korjatun datan.

Kriittisin ominaisuus on web_name-vartija: pelin id:t voivat driftata
kausien välillä eikä korjaus saa IKINÄ osua väärään pelaajaan.
"""
from __future__ import annotations

import json

import pytest

import scripts.build_spl_xp as b


@pytest.fixture
def overrides(monkeypatch, tmp_path):
    p = tmp_path / "spl_availability_overrides.json"
    monkeypatch.setattr(b, "OVERRIDES_PATH", p)
    return p


def _write(p, players):
    p.write_text(json.dumps({"players": players}), encoding="utf-8")


def test_override_korjaa_statuksen_ja_chancen(overrides):
    _write(overrides, {"521": {"web_name": "Enrique", "status": "i",
                               "chance": 0, "reason": "nilkka + leikkaus"}})
    elements = [{"id": 521, "web_name": "Enrique", "status": "a",
                 "chance_of_playing_next_round": None}]
    applied = b.apply_availability_overrides(elements)
    assert len(applied) == 1
    assert elements[0]["status"] == "i"
    assert elements[0]["chance_of_playing_next_round"] == 0
    # ja availability_factor vie minuutit nollaan tällä syötteellä
    from src.models import spl_xp as xp
    assert xp.availability_factor("i", 0) == 0.0


def test_nimivartija_estaa_vaaran_pelaajan(overrides):
    """Id-drift: sama id kuuluu nyt eri pelaajalle → EI kosketa."""
    _write(overrides, {"521": {"web_name": "Enrique", "status": "i", "chance": 0}})
    elements = [{"id": 521, "web_name": "Al Buraikan", "status": "a",
                 "chance_of_playing_next_round": None}]
    applied = b.apply_availability_overrides(elements)
    assert applied == []
    assert elements[0]["status"] == "a", "väärän pelaajan status ei saa muuttua"


def test_tuntematon_id_ohitetaan(overrides):
    _write(overrides, {"99999": {"web_name": "Ghost", "status": "i", "chance": 0}})
    elements = [{"id": 521, "web_name": "Enrique", "status": "a"}]
    assert b.apply_availability_overrides(elements) == []
    assert elements[0]["status"] == "a"


def test_ilman_tiedostoa_noop(overrides):
    """Negatiivinen kontrolli: ei override-tiedostoa → käytös ennallaan."""
    elements = [{"id": 521, "web_name": "Enrique", "status": "a"}]
    assert b.apply_availability_overrides(elements) == []
    assert elements[0]["status"] == "a"
