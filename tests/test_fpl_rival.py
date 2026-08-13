"""MINI-LEAGUE-RIVAL — puhtaan laskennan testit (spec vaihe a).

Spec vaatii negatiivisen kontrollin asemalogiikalle: takaa-ajajan ja
johtajan suositus EIVÄT saa olla sama lista. Jos ne ovat, koko ominaisuuden
idea on kadonnut ja jäljelle jää kallis differentiaalilista.

Luvut ovat erisuuria, jotta väärä kaava tuottaa eri tuloksen.
"""
from __future__ import annotations

from src.models.fpl_rival import (
    STANCE_CHASE_STEADY,
    STANCE_CHASE_VARIANCE,
    STANCE_LEVEL,
    STANCE_PROTECT,
    VARIANCE_MODE_P,
    build_rival_view,
    catch_probability,
    differentials,
    round_probability,
    stance,
)


def P(pid: int, xp: float, owned: float = 5.0) -> dict:
    return {"id": pid, "web_name": f"P{pid}", "team_short": "XXX",
            "price": 50, "owned_pct": owned, "xp_horizon_total": xp}


POOL = [P(1, 40.0), P(2, 35.0, owned=45.0), P(3, 30.0), P(4, 25.0),
        P(5, 20.0), P(6, 15.0), P(7, 10.0)]


# --- kiinnikurontatodennäköisyys -----------------------------------------

def test_tasavaisilla_joukkueilla_iso_ero_on_epatodennakoinen():
    p = catch_probability(gap=40, mu_you=50, mu_rival=50,
                          var_you=100, var_rival=100, gameweeks_left=2)
    assert p < 0.15, p


def test_parempi_joukkue_kuroo_todennakoisemmin():
    same = catch_probability(20, 50, 50, 100, 100, 5)
    better = catch_probability(20, 55, 50, 100, 100, 5)
    assert better > same


def test_johdossa_oleva_saa_korkean_luvun():
    """gap < 0 = olet edellä -> "kiinnikurominen" on jo tapahtunut."""
    assert catch_probability(-30, 50, 50, 100, 100, 3) > 0.8


def test_kierrokset_lopussa_ero_on_lopullinen():
    assert catch_probability(10, 99, 1, 100, 100, 0) == 0.0
    assert catch_probability(-10, 1, 99, 100, 100, 0) == 1.0


def test_useampi_kierros_kasvattaa_hajontaa():
    """Sama ero, enemmän kierroksia -> takaa-ajajalla enemmän mahdollisuuksia
    vaikka odotusarvo olisi sama. Väärä kaava (ei skaalaa varianssia N:llä)
    antaisi saman luvun."""
    few = catch_probability(30, 50, 50, 100, 100, 1)
    many = catch_probability(30, 50, 50, 100, 100, 10)
    assert many > few


# --- esitystarkkuus -------------------------------------------------------

def test_pyoristys_on_viiden_prosentin_tarkkuudella():
    assert round_probability(0.23) == 0.25
    assert round_probability(0.211) == 0.2
    assert round_probability(0.0) == 0.0
    assert round_probability(1.0) == 1.0


# --- asemalogiikka --------------------------------------------------------

def test_johdossa_on_suojaustila():
    assert stance(gap=-15, p_catch=0.9) == STANCE_PROTECT


def test_tasoissa_on_oma_tila():
    assert stance(gap=0, p_catch=0.5) == STANCE_LEVEL


def test_jaljessa_hyvalla_todennakoisyydella_on_rauhallinen_takaa_ajo():
    assert stance(gap=10, p_catch=0.45) == STANCE_CHASE_STEADY


def test_jaljessa_huonolla_todennakoisyydella_vaihtuu_varianssitilaan():
    assert stance(gap=60, p_catch=0.05) == STANCE_CHASE_VARIANCE


def test_kynnys_on_tasan_dokumentoitu_vakio():
    """Rajan ALLA varianssitila, rajalla ja yli rauhallinen — ei liukumaa."""
    assert stance(10, VARIANCE_MODE_P - 0.001) == STANCE_CHASE_VARIANCE
    assert stance(10, VARIANCE_MODE_P) == STANCE_CHASE_STEADY


# --- differentiaalipoiminta ----------------------------------------------

def test_takaa_ajo_ei_ehdota_rivaalin_omistamia():
    """Rivaalin omistama pelaaja ei kuro eroa: hän saa samat pisteet."""
    rows = differentials(POOL, your_ids={7}, rival_ids={1, 2},
                         stance_key=STANCE_CHASE_STEADY)
    assert all(not r["rival_owns"] for r in rows)
    assert all(r["id"] not in (1, 2, 7) for r in rows)


def test_suojaus_ehdottaa_TASAN_rivaalin_omistamia():
    """NEGATIIVINEN KONTROLLI ASEMALOGIIKALLE: johtajan lista on eri joukko
    kuin takaa-ajajan. Jos nämä ovat samat, koko ominaisuus on turha."""
    chase = differentials(POOL, {7}, {1, 2}, STANCE_CHASE_STEADY)
    protect = differentials(POOL, {7}, {1, 2}, STANCE_PROTECT)
    assert all(r["rival_owns"] for r in protect)
    assert {r["id"] for r in protect} == {1, 2}
    assert {r["id"] for r in chase}.isdisjoint({r["id"] for r in protect})


def test_varianssitila_jarjestaa_swingin_mukaan_ei_xp():
    """Varianssitilassa kärki on suurimman swingin pelaaja. Koska swing on
    tässä VAR_PER_XP * xp, järjestys osuu xP:hen — testi varmistaa että
    swing-kenttä on laskettu eikä kopioitu xP:stä."""
    rows = differentials(POOL, set(), set(), STANCE_CHASE_VARIANCE)
    assert rows[0]["swing"] == 2.5 * rows[0]["xp_horizon"]
    assert rows[0]["swing"] != rows[0]["xp_horizon"]


def test_rauhallinen_takaa_ajo_jarjestaa_xp_mukaan():
    rows = differentials(POOL, set(), set(), STANCE_CHASE_STEADY)
    assert [r["id"] for r in rows][:3] == [1, 2, 3]


def test_limit_rajaa_listan():
    assert len(differentials(POOL, set(), set(), STANCE_CHASE_STEADY, limit=2)) == 2


# --- koko payload ---------------------------------------------------------

def test_free_saa_luvun_muttei_listaa():
    d = build_rival_view(30, 10, 50, 50, 100, 100, POOL, {7}, {1},
                         premium=False)
    assert d["p_catch"] is not None          # koukku on ilmainen
    assert "differentials" not in d          # ohje on premium
    assert d["meta"]["masked"] is True


def test_premium_saa_listan():
    d = build_rival_view(30, 10, 50, 50, 100, 100, POOL, {7}, {1},
                         premium=True)
    assert len(d["differentials"]) == 5
    assert d["meta"]["masked"] is False


def test_riippumattomuusoletus_kerrotaan_payloadissa():
    """Rehellisyysvaatimus: lukija saa tietää ettei luku ole tarkka."""
    d = build_rival_view(30, 10, 50, 50, 100, 100, POOL, {7}, {1})
    assert "independent" in d["meta"]["method"]


def test_behind_lippu_seuraa_eroa():
    assert build_rival_view(5, 3, 50, 50, 1, 1, POOL, set(), set())["behind"]
    assert not build_rival_view(-5, 3, 50, 50, 1, 1, POOL, set(), set())["behind"]


def test_kynnys_kulkee_datassa_jotta_copy_ei_ajaudu():
    d = build_rival_view(30, 10, 50, 50, 100, 100, POOL, {7}, {1})
    assert d["meta"]["variance_mode_below"] == VARIANCE_MODE_P
