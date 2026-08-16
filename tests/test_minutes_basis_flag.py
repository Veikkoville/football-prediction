"""Minuuttipriorin rehellisyyslippu (16.8.2026, Villen havainto).

Ville: *"arsenalilla ei edes ole odegaardia laitettu alotuksee ???"*

Mitattu juurisyy: korrelaatio(viime kauden avaukset / 38, `p_start`) = 0,785
(n=285). Priori on kaytannossa viime kauden avauskertojen kopio eika se kysy
MIKSI minuutit puuttuivat. Odegaard pelasi 1363 minuuttia ja 16 avausta ->
`p_start` 0,428, kahdeksas Arsenalin keskikentista. Sama mies aloitti
Community Shieldin kapteenina.

🔴 KAKSI ERI ASIAA, JA VAIN TOINEN NIISTA RIITTAA.

Rivikohtainen lippu nakyy vain pelaajilla jotka ovat jo sivulla. Odegaard
EI ole sivulla: hanta ei renderoida XI:hin eika kahdeksan parhaan listaan.
Valitus koski nimenomaan PUUTTUVAA nimea, joten pelkka rivilippu olisi ollut
korjaus joka ei koske sita tapausta josta se syntyi. Siksi seurasivulla on
myos rivi joka nimeaa ulos jaaneet.

Lippu EI korjaa lukua eika kerro suuntaa. Katkennut kausi voi tarkoittaa
loukkaantunutta tahtea TAI pelaajaa joka ei kelvannut, eika minuuttiluku
erota niita. Sama sitova rajaus kuin `team_flag`illa, jonka kalibrointi
kaatui 9.8 (hyokkays R^2 0,000, puolustus vaara merkki).
"""
from __future__ import annotations

import importlib
import re

import pytest

xpb = importlib.import_module("scripts.build_fpl_xp")
lt = importlib.import_module("scripts.build_fpl_longtail")


def _row(**kw):
    base = {
        "web_name": "Test", "pos": "MID", "price": 6.5,
        "data_basis": "pl_history", "predicted_starts": 43.0,
        "last_season": {"minutes": 1363, "starts": 16},
    }
    base.update(kw)
    return base


# ---------------------------------------------------------------------------
# Kuka saa lipun
# ---------------------------------------------------------------------------

def test_short_season_gets_the_flag():
    rows = [_row()]
    assert xpb.attach_minutes_basis_flag(rows) == 1
    assert rows[0]["minutes_basis_flag"] == "short_season"


def test_full_season_does_not():
    rows = [_row(last_season={"minutes": 2374, "starts": 27})]
    assert xpb.attach_minutes_basis_flag(rows) == 0
    assert "minutes_basis_flag" not in rows[0]


def test_threshold_is_exclusive():
    """1500 tasan EI ole alle 1500. Kynnyksen suunta on se osa joka menee
    hiljaa vaarin."""
    rows = [_row(last_season={"minutes": xpb.SHORT_SEASON_MINUTES})]
    assert xpb.attach_minutes_basis_flag(rows) == 0


def test_override_row_is_left_alone():
    """Ohitettu rivi on ihmisen paatos eika priorin tuotos. Lippu
    valehtelisi siita mihin luku nojaa."""
    rows = [_row(minutes_source="override")]
    assert xpb.attach_minutes_basis_flag(rows) == 0


def test_no_history_row_is_left_alone():
    """`no_history` kantaa jo oman lippunsa.

    🔴 Rivilla ON tarkoituksella viime kauden minuutit alle kynnyksen.
    Ensimmainen versio tasta testista antoi `last_season=None`, jolloin
    `mins is None` -vahti nappasi sen JOKA TAPAUKSESSA ja `data_basis`
    -ehdon poisto lapaisi mutaatiotestin. Rivi tulee ulkomaalta: sarjatasoa
    ei sekoiteta, joten PL-minuutit eivat kerro hanen roolistaan mitaan.
    """
    rows = [_row(data_basis="no_history",
                 last_season={"minutes": 400, "starts": 4})]
    assert xpb.attach_minutes_basis_flag(rows) == 0
    assert "minutes_basis_flag" not in rows[0]


def test_missing_last_season_is_not_a_zero():
    """Puuttuva kausitieto ei ole 'pelasi nolla minuuttia'."""
    rows = [_row(last_season=None), _row(last_season={})]
    assert xpb.attach_minutes_basis_flag(rows) == 0


def test_odegaard_case_is_covered_and_doku_case_is_not():
    """Kynnys on kalibroitu siihen tapaukseen josta tama alkoi. Jos se
    liukuu, Odegaard putoaa pois lipun alta ilman etta mikaan huutaa."""
    ode = _row(web_name="Ødegaard", last_season={"minutes": 1363, "starts": 16})
    doku = _row(web_name="Doku", last_season={"minutes": 1773, "starts": 19})
    xpb.attach_minutes_basis_flag([ode, doku])
    assert ode.get("minutes_basis_flag") == "short_season"
    assert "minutes_basis_flag" not in doku, (
        "Doku pelasi tayden kauden mittaisen otoksen; hanen kohdallaan kyse "
        "on XI-rungon muodosta eika katkenneesta kaudesta, eika lippu saa "
        "vaittaa muuta")


# ---------------------------------------------------------------------------
# Mita lukija nakee
# ---------------------------------------------------------------------------

def test_flag_renders_on_a_visible_row():
    p = _row(minutes_basis_flag="short_season")
    html = lt._no_history_flag(p)
    assert "1363 minutes last season" in html
    assert 'class="flag"' in html


def test_no_history_flag_still_wins_for_no_history():
    p = _row(data_basis="no_history", minutes_basis_flag="short_season")
    assert "No Premier League games yet" in lt._no_history_flag(p)


def test_the_flag_makes_no_directional_claim():
    """🔴 Sitova rajaus. Lippu kertoo etta arvio nojaa lyhyeen otokseen, EI
    kumpaan suuntaan luku on vaarassa."""
    html = lt._no_history_flag(_row(minutes_basis_flag="short_season"))
    for kielletty in ("too low", "too high", "underrat", "overrat",
                      "should be", "higher than", "lower than"):
        assert kielletty not in html.lower(), (
            f"lippu vaittaa suuntaa sanalla {kielletty!r}")


def test_omissions_line_names_the_player_who_is_missing():
    """🔴 Tama on se testi joka vastaa Villen alkuperaiseen valitukseen.

    Rivikohtainen lippu ei riita: valitus koski nimea jota EI renderoida.
    """
    ode = _row(web_name="Ødegaard", minutes_basis_flag="short_season",
               predicted_starts=42.8)
    rice = _row(web_name="Rice", predicted_starts=84.9,
                last_season={"minutes": 3093, "starts": 35})
    html = lt._xi_omissions([ode, rice], [rice])
    assert "Ødegaard" in html
    assert "43%" in html and "1363 min" in html
    assert "Rice" not in html, "XI:hin valittu ei kuulu ulosjaaneiden listaan"


def test_omissions_line_lists_only_flagged_players():
    """🔴 Ulos jaa aina kymmenia pelaajia. Rivi on hyodyllinen VAIN jos se
    rajautuu niihin joiden priori nojaa katkenneeseen kauteen.

    Ensimmainen versio tasta testista antoi vain XI:hin valitun pelaajan,
    jolloin `otetut`-vahti hylkasi hanet joka tapauksessa ja lippurajauksen
    poisto lapaisi mutaatiotestin.
    """
    ode = _row(web_name="Ødegaard", minutes_basis_flag="short_season",
               predicted_starts=42.8)
    varamies = _row(web_name="Nelson", predicted_starts=20.3,
                    last_season={"minutes": 2100, "starts": 24})
    rice = _row(web_name="Rice", predicted_starts=84.9,
                last_season={"minutes": 3093, "starts": 35})
    html = lt._xi_omissions([ode, varamies, rice], [rice])
    assert "Ødegaard" in html
    assert "Nelson" not in html, (
        "tayden kauden pelannut varamies ei kuulu talle riville: rivi "
        "vaittaisi silloin selittavansa jotain mita se ei selita")
    assert lt._xi_omissions([varamies, rice], [rice]) == ""


def test_omissions_line_makes_no_directional_claim():
    ode = _row(web_name="Ødegaard", minutes_basis_flag="short_season")
    html = lt._xi_omissions([ode], []).lower()
    for kielletty in ("too low", "should start", "underrat", "will start"):
        assert kielletty not in html, f"ulosjaaneiden rivi lupaa {kielletty!r}"


def test_built_artifact_carries_the_flag():
    """Portti artefaktia vasten: jos kutsu katoaa builderista, kentta
    haviaa hiljaa eika yksikaan sivu nayta mitaan."""
    import json
    import pathlib
    import config
    p = pathlib.Path(config.PROJECT_ROOT) / "data" / "fpl_xp_projections.json"
    if not p.exists():
        pytest.skip("projektioartefaktia ei ole")
    players = json.loads(p.read_text(encoding="utf-8"))["players"]
    flagged = [r for r in players if r.get("minutes_basis_flag")]
    assert flagged, "artefaktissa ei ole yhtaan liputettua rivia"
    for r in flagged:
        mins = (r.get("last_season") or {}).get("minutes")
        assert mins is not None and mins < xpb.SHORT_SEASON_MINUTES
        assert r.get("data_basis") == "pl_history"
        assert r.get("minutes_source") != "override"
