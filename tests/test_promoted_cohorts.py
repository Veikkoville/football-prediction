"""Portti: Championshipin tulokkaat eivat saa yhteista baselinea.

TAUSTA (15.8.2026, Villen GO). Championshipiin tullaan MOLEMMISTA suunnista, ja
kaudella 26/27 tulokkaita on kuusi kahdessa taysin eri voimaluokassa:

    League Onesta nousseet   Bolton, Cardiff, Lincoln
    PL:sta pudonneet         Burnley, West Ham, Wolves

Ylimmalla sarjalla tata ongelmaa ei ole — sinne tullaan vain alhaalta — joten
yksi viiteryhma riitti PL:lle ja muille big-5-liigoille.

MITATTU EROTUS (oikea fitti, ikkuna 2526+2627, decay 0.0035, bayes 2.0):
    promoted_from_below   attack -0.1221  defence +0.1121
    relegated_from_above  attack +0.2250  defence +0.0824
Attack-ero on 0.347 log-yksikkoa eli exp(0.347) ~ 1.41x. Yksi yhteinen
baseline olisi tehnyt West Hamista yhta heikon kuin Lincolnista, ja se olisi
nakynyt julkisissa ennusteissa heti ensimmaisesta kierroksesta.

MIKSI PORTIN ARVOINEN: yhteen niputtaminen ei kaada mitaan eika nay lokissa.
Se tuottaa taysin uskottavan nakoisia lukuja jotka ovat systemaattisesti
vaarin — kuudelle joukkueelle, koko kauden.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.models.dixon_coles import DixonColesModel  # noqa: E402
from src.models.promoted_baseline import (  # noqa: E402
    COHORT_DOWN,
    COHORT_UP,
    PROMOTED_BY_SEASON,
    REFERENCE_BY_LEAGUE,
    _kohortteina,
    taydenna_nousijat,
)

ELC = "ENG-Championship"


def _malli_jossa(arvot: dict[str, tuple[float, float]]) -> DixonColesModel:
    """Kevyt DC-malli ilman fittia: {joukkue: (attack, defence)}."""
    dc = DixonColesModel()
    for t, (a, d) in arvot.items():
        dc.attack[t] = a
        dc.defence[t] = d
        dc.home_advantage_per_team[t] = 0.0
    dc.teams_ = list(arvot)
    return dc


def _viiteryhmat() -> DixonColesModel:
    """Kummankin kohortin viiteryhma erottuvilla arvoilla."""
    ref = REFERENCE_BY_LEAGUE[ELC]
    arvot = {}
    for t in ref[COHORT_UP]:
        arvot[t] = (-0.20, 0.20)      # heikko hyokkays, heikko puolustus
    for t in ref[COHORT_DOWN]:
        arvot[t] = (0.30, 0.05)       # vahva hyokkays
    return _malli_jossa(arvot)


def test_normalisointi_hyvaksyy_seka_tuplen_etta_dictin():
    assert _kohortteina(("a", "b")) == {"": ("a", "b")}
    assert _kohortteina({"x": ("a",)}) == {"x": ("a",)}
    assert _kohortteina(()) == {}


def test_championship_on_kaksi_kohorttia_eika_yksi():
    for taulu, nimi in ((PROMOTED_BY_SEASON["2627"], "PROMOTED_BY_SEASON"),
                        (REFERENCE_BY_LEAGUE, "REFERENCE_BY_LEAGUE")):
        arvo = taulu[ELC]
        assert isinstance(arvo, dict), (
            f"{nimi}[{ELC}] on tuple -> kaikki kuusi tulokasta saisivat saman "
            f"baselinen")
        assert set(arvo) == {COHORT_UP, COHORT_DOWN}


def test_kumpikin_kohortti_saa_OMAN_viiteryhmansa():
    dc = _viiteryhmat()
    info = taydenna_nousijat(dc, (ELC,), ("2526", "2627"))
    cohorts = info.get("cohorts") or {}
    assert set(cohorts) == {COHORT_UP, COHORT_DOWN}, (
        "kohorttikohtaista telemetriaa ei kirjattu -> jalkikateen ei voi "
        "todeta kumpi baseline mihinkin osui")
    assert cohorts[COHORT_UP]["trio_used"] == list(REFERENCE_BY_LEAGUE[ELC][COHORT_UP])
    assert cohorts[COHORT_DOWN]["trio_used"] == list(REFERENCE_BY_LEAGUE[ELC][COHORT_DOWN])


def test_pudonneet_saavat_vahvemman_hyokkayksen_kuin_nousijat():
    """TAMA on koko muutoksen substanssi. Jos se kaatuu, kohortit ovat
    menneet sekaisin tai ne on niputettu takaisin yhdeksi."""
    dc = _viiteryhmat()
    taydenna_nousijat(dc, (ELC,), ("2526", "2627"))
    ylhaalta = [dc.attack[t] for t in PROMOTED_BY_SEASON["2627"][ELC][COHORT_DOWN]]
    alhaalta = [dc.attack[t] for t in PROMOTED_BY_SEASON["2627"][ELC][COHORT_UP]]
    assert min(ylhaalta) > max(alhaalta), (
        f"PL:sta pudonneiden hyokkays ({ylhaalta}) ei ole vahvempi kuin "
        f"League Onesta nousseiden ({alhaalta})")


def test_kaikki_kuusi_tulokasta_saavat_arvon():
    dc = _viiteryhmat()
    info = taydenna_nousijat(dc, (ELC,), ("2526", "2627"))
    odotetut = set(PROMOTED_BY_SEASON["2627"][ELC][COHORT_UP]) | set(
        PROMOTED_BY_SEASON["2627"][ELC][COHORT_DOWN])
    assert set(info["applied_to"]) == odotetut
    for t in odotetut:
        assert t in dc.attack and t in dc.defence


def test_yhden_kohortin_liigat_toimivat_ennallaan():
    """NEGATIIVINEN KONTROLLI muutoksen laajuudelle: tuple-muotoiset liigat
    eivat saa muuttua. Jos ne alkaisivat kayttaytya kohortteina, big-5:n
    julkaistut luvut liikkuisivat ilman etta kukaan pyysi sita."""
    pl = "ENG-Premier League"
    assert isinstance(PROMOTED_BY_SEASON["2627"][pl], tuple)
    dc = _malli_jossa({t: (0.1, 0.1) for t in REFERENCE_BY_LEAGUE[pl]})
    info = taydenna_nousijat(dc, (pl,), ("2526", "2627"))
    assert "cohorts" not in info, (
        "yhden kohortin liiga kirjasi kohorttitelemetriaa -> muoto muuttui")
    # Ipswich on SEKA nousijalistalla etta viiteryhmassa, joten se on jo
    # mallissa eika tarvitse injektiota. Kirjoitin taman ensin muodossa
    # "applied_to == koko nousijalista" ja testi kaatui — oletus oli vaara,
    # ei koodi. `add_promoted_baseline` ei ylikirjoita olemassa olevaa
    # estimaattia, ja juuri se on sen dokumentoitu lupaus.
    odotetut = {t for t in PROMOTED_BY_SEASON["2627"][pl]
                if t not in REFERENCE_BY_LEAGUE[pl]}
    assert set(info["applied_to"]) == odotetut
    for t in REFERENCE_BY_LEAGUE[pl]:
        assert dc.attack[t] == 0.1, "viiteryhman oma estimaatti ylikirjoitettiin"


@pytest.mark.parametrize("joukkue", ["Bolton", "Cardiff", "Lincoln",
                                     "Burnley", "West Ham", "Wolves"])
def test_mallinimet_ovat_football_data_muotoa(joukkue):
    """Vaara nimi ei kaataisi mitaan: se injektoisi avaimen jota kukaan ei hae
    ja joukkue jaisi silti puuttumaan. Nimet on verifioitu lahdetiedostoista
    (E0 24/25, E0 25/26, E2 25/26) — tama lukitsee ne."""
    kaikki = set(PROMOTED_BY_SEASON["2627"][ELC][COHORT_UP]) | set(
        PROMOTED_BY_SEASON["2627"][ELC][COHORT_DOWN])
    assert joukkue in kaikki


# ---------------------------------------------------------------------------
# Poimintafunktiot (dict-muoto)
# ---------------------------------------------------------------------------
# 🔴 OMA AUKKO PORTISSA (loydetty 15.8 tuotannosta mittaamalla). Testasin
# `taydenna_nousijat`-injektion mutta EN poimintafunktioita. Ne iteroivat
# `per_liiga.get(liiga, ())` suoraan, ja dictin yli iterointi antaa KOHORTTIEN
# NIMET joukkueiden sijaan:
#
#     nousijat_aktiiviselta_kaudelta(("ENG-Championship",), ...)
#     -> {'promoted_from_below', 'relegated_from_above'}
#
# /api/teams naytti Championshipille 18 joukkuetta 24:n sijaan. Vika oli
# NAKYMATON koska kutsuja vartioi listauksen dc.attack-jasenyydella:
# kohorttinimet eivat ole mallissa -> suodattuivat pois. Vartio muutti
# rikkinaisen listan hiljaa vajaaksi listaksi.
#
# Oppi: kun tietorakenteen MUOTO muuttuu, portin on katettava JOKAINEN sita
# lukeva funktio, ei vain sita jota oltiin muuttamassa.

def test_nousijapoiminta_palauttaa_joukkueet_eika_kohorttinimia():
    from src.models.promoted_baseline import nousijat_aktiiviselta_kaudelta
    got = nousijat_aktiiviselta_kaudelta((ELC,), ("2526", "2627"))
    assert got == frozenset(
        set(PROMOTED_BY_SEASON["2627"][ELC][COHORT_UP])
        | set(PROMOTED_BY_SEASON["2627"][ELC][COHORT_DOWN]))
    for nimi in (COHORT_UP, COHORT_DOWN):
        assert nimi not in got, f"kohortin nimi '{nimi}' vuoti joukkuelistaan"


def test_pudonneidenpoiminta_kestaa_dict_muodon():
    """RELEGATED on Championshipille tanaan tuple, mutta normalisointi on
    molemmissa funktioissa jotta ansa ei jaa odottamaan seuraavaa
    kohorttilisaysta."""
    from src.models.promoted_baseline import (
        _kohortteina, pudonneet_aktiiviselta_kaudelta)
    got = pudonneet_aktiiviselta_kaudelta((ELC,), ("2526", "2627"))
    odotettu = set()
    for j in _kohortteina(
            __import__("src.models.promoted_baseline", fromlist=["x"])
            .RELEGATED_BY_SEASON["2627"][ELC]).values():
        odotettu |= set(j)
    assert got == frozenset(odotettu)
    assert "Coventry" in got


def test_yhden_kohortin_liigan_poiminta_ennallaan():
    """NEGATIIVINEN KONTROLLI: tuple-muotoiset liigat eivat saa muuttua."""
    from src.models.promoted_baseline import nousijat_aktiiviselta_kaudelta
    pl = "ENG-Premier League"
    assert nousijat_aktiiviselta_kaudelta((pl,), ("2526", "2627")) == frozenset(
        PROMOTED_BY_SEASON["2627"][pl])
