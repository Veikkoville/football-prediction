"""DefCon-live (2.8.2026) — live-haaran testit.

Miksi nama ovat pakolliset: live-polkua EI voi ajaa oikeaa FPL:aa vasten
ennen kuin kierros on kaynnissa (21.8.2026). Ilman naita endpoint menisi
tuotantoon niin, etta vain esikauden available=False -haara on koskaan ajettu.
"""
from __future__ import annotations

import pytest

from src.models import fpl_defcon_live as dcl
from src.models.fpl_rate_team import RateTeamError


BOOT = {
    "events": [
        {"id": 1, "is_current": False, "deadline_time": "2026-08-21T17:30:00Z"},
        {"id": 2, "is_current": True, "deadline_time": "2026-08-28T17:30:00Z"},
    ],
    "element_types": [
        {"id": 1, "singular_name_short": "GKP"},
        {"id": 2, "singular_name_short": "DEF"},
        {"id": 3, "singular_name_short": "MID"},
        {"id": 4, "singular_name_short": "FWD"},
    ],
    "teams": [{"id": 1, "short_name": "ARS"}, {"id": 2, "short_name": "LIV"}],
    "elements": [
        {"id": 11, "web_name": "Raya", "element_type": 1, "team": 1},
        {"id": 12, "web_name": "Gabriel", "element_type": 2, "team": 1},
        {"id": 13, "web_name": "Rice", "element_type": 3, "team": 1},
        {"id": 14, "web_name": "Isak", "element_type": 4, "team": 2},
    ],
}

LIVE = {
    11: {"minutes": 90, "defensive_contribution": 4},    # GKP: ei DefConia
    12: {"minutes": 70, "defensive_contribution": 7},    # DEF 7/10 -> kesken
    13: {"minutes": 90, "defensive_contribution": 12},   # MID 12/12 -> osuma
    14: {"minutes": 20, "defensive_contribution": 12},   # FWD 12/12, vain 20 min
}


@pytest.fixture(autouse=True)
def _patch(monkeypatch):
    monkeypatch.setattr("src.data.fpl_api.fetch_bootstrap", lambda *a, **k: BOOT)
    monkeypatch.setattr(dcl, "_live_stats", lambda gw: LIVE)
    monkeypatch.setattr(
        dcl, "_entry_picks",
        lambda entry_id, gw: [
            {"element": 11, "position": 1, "is_captain": False},
            {"element": 12, "position": 2, "is_captain": False},
            {"element": 13, "position": 5, "is_captain": True},
            {"element": 14, "position": 11, "is_captain": False},
        ],
    )
    dcl._live_cache.clear()


def _by_id(out):
    return {p["id"]: p for p in out["players"]}


def test_entry_polku_palauttaa_koko_kokoonpanon():
    out = dcl.load_defcon_live(entry_id=123)
    assert out["meta"]["available"] is True
    assert out["meta"]["gw"] == 2  # is_current voittaa, ei ensimmainen event
    assert len(out["players"]) == 4


def test_maalivahdilla_ei_ole_defconia():
    gk = _by_id(dcl.load_defcon_live(entry_id=123))[11]
    assert gk["threshold"] is None
    assert gk["eligible"] is False
    assert gk["hit"] is False
    assert gk["remaining"] is None


def test_puolustajan_kynnys_ja_jaljella():
    d = _by_id(dcl.load_defcon_live(entry_id=123))[12]
    assert (d["pos"], d["threshold"], d["defcon"]) == ("DEF", 10, 7)
    assert d["hit"] is False
    assert d["remaining"] == 3


def test_keskikentta_osuma_ja_kapteenilippu():
    m = _by_id(dcl.load_defcon_live(entry_id=123))[13]
    assert (m["pos"], m["threshold"]) == ("MID", 12)
    assert m["hit"] is True
    assert m["remaining"] == 0
    assert m["is_captain"] is True


def test_osuma_ei_vaadi_60_minuuttia():
    """Historiallinen osumaprosentti suodattaa >=60 min, LIVE ei saa:
    FPL myontaa pisteen kynnyksesta riippumatta pelatuista minuuteista."""
    f = _by_id(dcl.load_defcon_live(entry_id=123))[14]
    assert f["minutes"] == 20
    assert f["hit"] is True


def test_ids_polku_ilman_entrya():
    out = dcl.load_defcon_live(ids=[12, 13])
    assert [p["id"] for p in out["players"]] == [12, 13]
    assert all(p["squad_position"] is None for p in out["players"])


def test_tuntematon_id_ohitetaan_ei_kaadu():
    out = dcl.load_defcon_live(ids=[12, 999999])
    assert [p["id"] for p in out["players"]] == [12]


def test_puuttuva_syote_on_400():
    with pytest.raises(RateTeamError) as e:
        dcl.load_defcon_live()
    assert e.value.status_code == 400


def test_kierrosten_valissa_available_false(monkeypatch):
    boot = {**BOOT, "events": [{"id": 1, "is_current": False}]}
    monkeypatch.setattr("src.data.fpl_api.fetch_bootstrap", lambda *a, **k: boot)
    out = dcl.load_defcon_live(entry_id=123)
    assert out["meta"]["available"] is False
    assert out["players"] == []
    # kynnykset kulkevat mukana myos suljetussa tilassa (frontend voi selittaa)
    assert out["meta"]["thresholds"]["DEF"] == 10


def test_pelaaja_ilman_live_riveja_on_nolla_ei_none():
    """Ennen ottelun alkua elementilla ei ole stats-rivia — sen pitaa nayttaa
    0/10, ei tyhjaa, muuten UI joutuisi arvaamaan."""
    dcl._live_cache.clear()
    out = dcl.load_defcon_live(ids=[12])
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(dcl, "_live_stats", lambda gw: {})
        out = dcl.load_defcon_live(ids=[12])
    p = out["players"][0]
    assert p["defcon"] == 0 and p["minutes"] == 0 and p["remaining"] == 10
