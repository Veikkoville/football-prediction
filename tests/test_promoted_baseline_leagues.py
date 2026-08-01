"""Nousijabaselinen liigalaajennus (1.8, TASKS 4d): per-liiga-viiteryhmät.

Ei fittiä — stub-malli jolla attack/defence/home_advantage_per_team-dictit.
Ydinvaatimukset:
  1. FD-liigan nousijat saavat OMAN liigansa viiteryhmän mitatun keskiarvon.
  2. PL:n frozen-fallback EI vuoda muihin liigoihin (allow_frozen vain PL).
  3. Vanha 2-argumenttinen add_promoted_baseline-kutsu (FPL-builderit) =
     entinen käytös bittitarkasti.
"""
from __future__ import annotations

from src.models.promoted_baseline import (
    FROZEN_BASELINE,
    PROMOTED_BY_SEASON,
    REFERENCE_BY_LEAGUE,
    add_promoted_baseline,
    taydenna_nousijat,
)

PD = "ESP-La Liga-FD"
BL1 = "GER-Bundesliga-FD"
PL = "ENG-Premier League"


class _StubDC:
    def __init__(self, attack: dict, defence: dict | None = None,
                 gamma: dict | None = None):
        self.attack = dict(attack)
        self.defence = dict(defence if defence is not None
                            else {t: -v for t, v in attack.items()})
        self.home_advantage_per_team = dict(gamma or {})


def test_fd_liigan_nousijat_saavat_oman_viiteryhman_keskiarvon():
    ref = REFERENCE_BY_LEAGUE[PD]
    dc = _StubDC(attack={ref[0]: -0.3, ref[1]: -0.1, ref[2]: -0.2,
                         "FC Barcelona": 0.9})
    info = taydenna_nousijat(dc, (PD,), ("2526", "2627"))
    odotetut = set(PROMOTED_BY_SEASON["2627"][PD])
    assert set(info["applied_to"]) == odotetut
    assert info["source"] == "measured"
    for t in odotetut:
        assert abs(dc.attack[t] - (-0.2)) < 1e-9  # mean(-0.3, -0.1, -0.2)


def test_frozen_ei_vuoda_fd_liigaan():
    # Viiteryhmä EI fitissä → FD-liigassa injektio ohittuu näkyvästi,
    # PL-frozen-lukuja ei kirjoiteta.
    dc = _StubDC(attack={"FC Bayern München": 0.8})
    info = taydenna_nousijat(dc, (BL1,), ("2526", "2627"))
    assert info["applied_to"] == []
    assert set(info.get("skipped", [])) == set(PROMOTED_BY_SEASON["2627"][BL1])
    for t in PROMOTED_BY_SEASON["2627"][BL1]:
        assert t not in dc.attack


def test_pl_frozen_fallback_ennallaan():
    # PL: trio poissa ikkunasta → frozen-arvot (entinen käytös).
    dc = _StubDC(attack={"Arsenal": 0.7})
    info = taydenna_nousijat(dc, (PL,), ("2526", "2627"))
    assert info["source"] == "frozen"
    assert set(info["applied_to"]) == set(PROMOTED_BY_SEASON["2627"][PL])
    assert dc.attack["Coventry"] == FROZEN_BASELINE["attack"]


def test_kahden_argumentin_kutsu_on_entinen_pl_kaytos():
    # FPL-builderien suora kutsu ilman uusia parametreja.
    dc = _StubDC(attack={"Arsenal": 0.7})
    info = add_promoted_baseline(dc, ["Coventry"])
    assert info["source"] == "frozen"
    assert dc.attack["Coventry"] == FROZEN_BASELINE["attack"]


def test_monta_liigaa_yhdessa_pyynnossa_aggregoituu():
    ref_pd = REFERENCE_BY_LEAGUE[PD]
    dc = _StubDC(attack={ref_pd[0]: -0.3, ref_pd[1]: -0.1, ref_pd[2]: -0.2})
    info = taydenna_nousijat(dc, (PD, BL1), ("2526", "2627"))
    # PD injektoituu (viiteryhmä fitissä), BL1 skippaa (ei viiteryhmää).
    assert set(info["applied_to"]) == set(PROMOTED_BY_SEASON["2627"][PD])
    assert set(info["skipped"]) == set(PROMOTED_BY_SEASON["2627"][BL1])
