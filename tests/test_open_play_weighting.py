"""Portti: joukkueen maaliuhkakerroin painotetaan avopeliosuudella.

TAUSTA (15.8.2026, ATTACK-PROPAGATION, Villen GO). Jonorivi sanoi etta
kalibrointiluku olisi "toistaiseksi harkinta, koska set_pieces on tyhja". Se
piti paikkansa FPL:n bootstrapista, mutta EI Understatin laukaustason
artefaktista, jossa `spxg` on ollut koko ajan. Osuus on siis MITATTAVISSA eika
harkintaa, ja se on mitattava PER PELAAJA eika arvattava kerran kaikille.

MITATTU 15.8 (data/understat_player_shots_2526.json, 25/26, 380 ottelua):
    Malick Thiaw   npxg 5.90  spxg 5.38  ->  91 % erikoistilanteista
    Gabriel        npxg 4.65  spxg 4.50  ->  97 %
    liigan mediaani (npxg >= 2.0)         ->  16 %

MIKSI TAMA ON VIKA EIKA VIRITYS. `attack_mult` kuvaa AVOPELIN hyokkaysvoimaa:
se syntyy siirtoikkunasta, valmentajanvaihdosta ja rungon menetyksesta.
Kulmasyoton laatu ja pelaajan ilmapeli eivat katoa silla etta seura menetti
hyokkaajan. Kertoimen soveltaminen tasaisesti kaikkiin leikkaisi Thiawilta
10 % myos siita 91 %:sta johon se ei pade.

Aktiivinen ohitusrivi on juuri Newcastle, ja Thiaw pelaa siella.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.build_fpl_xp import (  # noqa: E402
    _load_open_play_share,
    _shot_key,
    effective_team_mult,
)


# ---------------------------------------------------------------------------
# Saanto
# ---------------------------------------------------------------------------

def test_kerroin_on_inertti_kun_joukkuekerrointa_ei_ole():
    """TARKEIN: ilman aktiivista kerrointa yksikaan luku ei saa liikkua.
    `attack_mult` on tanaan tyhja kaikilla riveilla, joten muutoksen on oltava
    todistettavasti inertti tuotannossa."""
    for share in (0.0, 0.088, 0.5, 1.0):
        assert effective_team_mult(1.0, share) == 1.0


def test_taysi_avopeliosuus_sailyttaa_entisen_kayttaytymisen():
    """share 1.0 = pelaajalla ei ole erikoistilanne-xG:ta -> koko vaikutus.
    Sama koskee pelaajaa jolle dataa ei ole (kutsuja antaa oletuksen 1.0),
    joten muutos ei voi heikentaa ketaan jota ei ole mitattu."""
    assert effective_team_mult(0.90, 1.0) == pytest.approx(0.90)
    assert effective_team_mult(1.10, 1.0) == pytest.approx(1.10)


def test_pelkka_erikoistilannepelaaja_ei_liiku_lainkaan():
    assert effective_team_mult(0.90, 0.0) == pytest.approx(1.0)
    assert effective_team_mult(1.25, 0.0) == pytest.approx(1.0)


def test_thiaw_liikkuu_selvasti_vahemman_kuin_avopelipelaaja():
    """SUBSTANSSI. 10 %:n joukkueleikkaus vie avopelipelaajalta ~10 % mutta
    Thiawilta alle 1 %, koska 91 % hanen xG:staan on erikoistilanteista."""
    avopeli = effective_team_mult(0.90, 0.894)   # Bruno Fernandes, mitattu
    thiaw = effective_team_mult(0.90, 0.088)     # mitattu
    assert thiaw > avopeli
    assert 1.0 - thiaw < 0.02, f"Thiaw liikkui {1 - thiaw:.3f}, odotettu < 0.02"
    assert 1.0 - avopeli > 0.08


def test_suunta_sailyy_molempiin_suuntiin():
    """Nosto ja lasku kayttaytyvat symmetrisesti: painotus ei saa kaantaa
    merkkia, vain vaimentaa sita."""
    assert effective_team_mult(0.80, 0.5) < 1.0
    assert effective_team_mult(1.20, 0.5) > 1.0


# ---------------------------------------------------------------------------
# Mitattu data
# ---------------------------------------------------------------------------

def test_avopeliosuudet_luetaan_artefaktista():
    s = _load_open_play_share()
    if not s:  # pragma: no cover
        pytest.skip("laukausartefaktia ei ole talla koneella")
    assert len(s) > 300, f"osuuksia loytyi vain {len(s)}"
    assert all(0.0 <= v <= 1.0 for v in s.values()), "osuus rajojen ulkopuolella"


@pytest.mark.parametrize("nimi,ylaraja", [
    ("malick thiaw", 0.20),   # 91 % erikoistilanteista
    ("gabriel", 0.20),        # 97 %
])
def test_erikoistilannepuolustajat_tunnistetaan(nimi, ylaraja):
    s = _load_open_play_share()
    if not s:  # pragma: no cover
        pytest.skip("laukausartefaktia ei ole")
    assert nimi in s, f"{nimi} puuttuu laukausdatasta"
    assert s[nimi] < ylaraja, f"{nimi} avopeliosuus {s[nimi]:.3f}, odotettu < {ylaraja}"


@pytest.mark.parametrize("nimi,alaraja", [
    ("erling haaland", 0.70),
    ("bruno fernandes", 0.70),
])
def test_avopelipelaajat_tunnistetaan(nimi, alaraja):
    """NEGATIIVINEN KONTROLLI: jos kaikki saisivat matalan osuuden, portti
    menisi lapi mutta painotus olisi rikki."""
    s = _load_open_play_share()
    if not s:  # pragma: no cover
        pytest.skip("laukausartefaktia ei ole")
    assert nimi in s
    assert s[nimi] > alaraja, f"{nimi} avopeliosuus {s[nimi]:.3f}, odotettu > {alaraja}"


def test_nimiavain_normalisoi_aksentit_ja_valilyonnit():
    assert _shot_key({"full_name": "  Malick  Thiaw "}) == "malick thiaw"
    assert _shot_key({"first_name": "Benjamin", "second_name": "Šeško"}) == "benjamin sesko"
