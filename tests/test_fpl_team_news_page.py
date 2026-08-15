"""Portti: team news -sivu ei saa keksia lukuja eika luvata journalismia.

TAUSTA (15.8.2026, Villen kysymys): saisiko meille FFScoutin kaltaisen team
news -pinnan, ja vaatiiko se toimittajan lehdistotilaisuuteen. Ei vaadi —
FPL:n oma API julkaisee virallisen status- ja uutistekstin, ja se on jo
committoidussa artefaktissamme.

Sivun KULMA on se mita kilpailija ei voi kopioida: FFScout kertoo kuka on
ulkona, me kerromme mita se maksaa pisteina. Juuri siksi kaksi asiaa on
lukittava portilla:

  (1) Poissaolevalle EI SAA nayttaa xP:ta. Malli ei projisoi pelaajaa jonka se
      on sulkenut pois, ja luvun keksiminen olisi tasan sen vastakohta mita
      sivu lupaa. Ruled out -taulukko nayttaa viime kauden pisteet, ja se
      kerrotaan lukijalle.
  (2) Sivu ei saa vaittaa tietavansa lehdistotilaisuuksista. Se lukee
      virallista syotetta, joka laahaa managerin kommenttien perassa.

Sivu on generoitu taulukko mallin omista luvuista eika teeskentele
journalismia. Peruste on mitattu: 9.-10.8 nelja Reddit-kayttajaa tunnisti
tekstimme koneen kirjoittamaksi.
"""
from __future__ import annotations

import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.build_fpl_longtail import render_team_news  # noqa: E402

NOW = datetime(2026, 8, 15, tzinfo=timezone.utc)


def _xp(players, excluded=()):
    return {
        "meta": {"available": True, "next_gameweek": 1},
        "players": list(players),
        "excluded": list(excluded),
    }


def _p(name, **kw):
    base = {
        "web_name": name, "team_short": "ARS", "pos": "MID",
        "owned_pct": 1.0, "news": "", "chance_next": None,
        "gameweeks": [1, 2, 3, 4, 5, 6],
    }
    base.update(kw)
    return base


def _rows(html: str, section: str) -> list[list[str]]:
    blk = re.search(rf'<h2 id="{section}">.*?</table>', html, re.S)
    if not blk:
        return []
    out = []
    for row in re.findall(r"<tr>(.*?)</tr>", blk.group(0), re.S):
        cells = [re.sub(r"<[^>]+>", "", c).strip()
                 for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
        if cells:
            out.append(cells)
    return out


def test_ilman_uutisia_sivua_ei_synny():
    """Tyhja sivu on huonompi kuin ei sivua: vanha jaa voimaan."""
    assert render_team_news(_xp([_p("A")]), NOW) is None


def test_saatavuustieto_ilman_uutistekstia_ei_paady_sivulle():
    """`excluded` sisaltaa myos below_min_xp -rivit joilla ei ole uutista.
    Ne eivat ole team newsia."""
    html = render_team_news(_xp(
        [_p("Uutinen", news="Knock - 75% chance of playing", chance_next=75,
            xp_horizon_total=10.0)],
        [_p("Hiljainen", chance_next=0, news="")],
    ), NOW)
    assert html is not None
    assert "Hiljainen" not in html


def test_poissaolevalle_ei_nayteta_xp_lukua():
    """TAMA on portin ydin. Jos ruled out -riville vuotaa xP, sivu vaittaa
    mallin projisoineen pelaajan jonka se sulki pois."""
    # `players` ei ole koskaan tyhja kun meta.available on True, ja sivun
    # horisontti luetaan players[0]:sta -> tyhja lista palauttaisi Nonen.
    # Kirjoitin taman ensin ilman terveita pelaajia ja se kaatui siihen;
    # testi oli epärealistinen, ei koodi.
    html = render_team_news(_xp(
        [_p("Terve")],
        [_p("Ulkona", chance_next=0, news="Knee injury - Unknown return date",
            last_season={"points": 113})],
    ), NOW)
    assert html is not None
    rivit = _rows(html, "out")
    assert len(rivit) == 1
    # Viime kauden sarake: TOTEUTUNUT FPL-piste, merkittyna faktaksi.
    assert "113" in rivit[0][-2]
    assert "last yr" in rivit[0][-2], (
        "viime kauden pisteita ei merkitty -> lukija luulee sita projektioksi")


def test_epavarmalle_nayteta_xp_koska_se_on_koko_kulma():
    html = render_team_news(_xp(
        [_p("Epavarma", chance_next=75, news="Shin injury - 75% chance",
            xp_horizon_total=11.35, owned_pct=2.1)],
    ), NOW)
    rivit = _rows(html, "doubtful")
    assert len(rivit) == 1
    assert "11.3" in rivit[0][-1], f"xP puuttuu rivilta: {rivit[0]}"
    assert "75%" in " ".join(rivit[0])


def test_jarjestys_on_omistus_laskevasti():
    """Sivun kysymys on 'koskeeko tama minua', ei 'kuka on paras'."""
    html = render_team_news(_xp([
        _p("Pieni", chance_next=75, news="Knock", xp_horizon_total=9.0,
           owned_pct=0.4),
        _p("Iso", chance_next=75, news="Knock", xp_horizon_total=1.0,
           owned_pct=42.0),
    ]), NOW)
    rivit = _rows(html, "doubtful")
    assert [r[0] for r in rivit] == ["Iso", "Pieni"], (
        "jarjestys ei ole omistuksen mukaan")


def test_sivu_ei_vaita_tietavansa_lehdistotilaisuuksista():
    """Rehellisyysrajaus: virallinen syote laahaa managerin kommenttien
    perassa, ja sen on lukija saatava tietaa."""
    html = render_team_news(_xp(
        [_p("X", chance_next=75, news="Knock", xp_horizon_total=5.0)]), NOW)
    assert "press conference" in html.lower()
    assert "official Fantasy" in html


@pytest.mark.parametrize("kentta", ["team-news", "Ruled out", "Doubtful"])
def test_sivun_rakenne(kentta):
    html = render_team_news(_xp(
        [_p("D", chance_next=75, news="Knock", xp_horizon_total=5.0)],
        [_p("O", chance_next=0, news="Injury", last_season={"points": 10})],
    ), NOW)
    assert kentta in html


def test_landing_linkittaa_sivun():
    """COPY-SYNC: generoitu sivu jota mikaan ei linkita on kayttajalle
    olematon. Sitemap yksin ei riita — se on hakukoneille, ei lukijalle."""
    src = (ROOT / "scripts" / "build_fpl_page.py").read_text(encoding="utf-8")
    assert src.count('/fpl/team-news') >= 2, (
        "team-news puuttuu fpl.html:n listasta tai alatunnisteesta")


# ---------------------------------------------------------------------------
# llms.txt-kattavuus
# ---------------------------------------------------------------------------
# MUISTETTU SOKEA PISTE: llms.txt:n FPL-osio on KASIN yllapidetty (vain
# kasvumoottorin luvut paivittyvat automaattisesti, ks. build_prediction_pages
# .update_llms_txt). Uusi sivu jaa siita pois eika mikaan huuda — se vain
# puuttuu AI-vastausmoottoreiden lahdeluettelosta.
#
# Tama portti on tarkoituksella LAAJEMPI kuin tama sivu: se vaatii jokaiselta
# generoidulta /fpl/-sivulta rivin llms.txt:aan, jolloin seuraava lisays ei voi
# unohtua samalla tavalla.

def test_jokainen_fpl_sivu_on_llms_txt_ssa():
    fpl_dir = ROOT / "fpl"
    if not fpl_dir.exists():  # pragma: no cover
        pytest.skip("fpl/-hakemistoa ei ole")
    llms = (ROOT / "llms.txt").read_text(encoding="utf-8")
    puuttuvat = [
        f.stem for f in sorted(fpl_dir.glob("*.html"))
        if f"/fpl/{f.stem}" not in llms
    ]
    assert not puuttuvat, (
        "generoituja /fpl/-sivuja puuttuu llms.txt:sta: "
        + ", ".join(puuttuvat))


def test_jokainen_fpl_sivu_on_ristiinlinkityslistalla():
    """SISAINEN LINKITYS. `_TOOL_LINKS` on kuratoitu lista, ja se oli itse
    vanhentunut kahdesti: 15.8 mitattuna siita puuttuivat seka `team-news`
    etta `expected-points`, joten yksikaan sisarsivu ei osoittanut niihin.

    `expected-points` on se sivu johon X-postaukset linkittavat, eli orvoksi
    oli jaanyt tarkein ilmaispinta. Listan oma kommentti dokumentoi tasan taman
    vian jo 28.7 (GSC: "Viittaava sivu: Ei havaittuja"), ja se toistui silti.
    Kuratoitu lista ilman porttia vanhenee joka lisayksella.
    """
    from scripts.build_fpl_longtail import _TOOL_LINKS
    fpl_dir = ROOT / "fpl"
    if not fpl_dir.exists():  # pragma: no cover
        pytest.skip("fpl/-hakemistoa ei ole")
    listalla = {p for p, _ in _TOOL_LINKS}
    puuttuvat = [
        f.stem for f in sorted(fpl_dir.glob("*.html"))
        if f"/fpl/{f.stem}" not in listalla
    ]
    assert not puuttuvat, (
        "generoituja /fpl/-sivuja puuttuu _TOOL_LINKS-ristiinlinkityksesta "
        "-> ne jaavat orvoiksi: " + ", ".join(puuttuvat))


# ---------------------------------------------------------------------------
# Etusivun nosto (fpl.html)
# ---------------------------------------------------------------------------

def test_etusivun_nosto_puuttuvalla_datalla_on_tyhja():
    """Puuttuva data -> koko lohko pois. Otsikko ilman sisaltoa on pahempi
    kuin ei otsikkoa: se lupaa tuoretta tietoa jota ei ole."""
    from scripts.build_fpl_page import team_news_block
    assert team_news_block(None) == ""
    assert team_news_block({"players": [], "excluded": []}) == ""
    # Saatavuustieto ilman uutistekstia ei ole team newsia.
    assert team_news_block({"players": [{"news": "", "chance_next": 0}]}) == ""


def test_etusivun_nosto_laskee_ulkona_ja_epavarmat_erikseen():
    from scripts.build_fpl_page import team_news_block
    xp = {"players": [
        {"web_name": "A", "team_short": "ARS", "news": "Knock",
         "chance_next": 75, "owned_pct": 30.0},
        {"web_name": "B", "team_short": "CHE", "news": "Injury",
         "chance_next": 0, "owned_pct": 5.0},
        {"web_name": "C", "team_short": "LIV", "news": "Injury",
         "chance_next": 0, "owned_pct": 1.0},
    ], "excluded": []}
    html = team_news_block(xp)
    assert "2 players are ruled out and 1 are doubtful" in html
    # Jarjestys omistuksen mukaan, eniten omistettu ensin.
    assert html.index("A (ARS)") < html.index("B (CHE)")
    assert '/fpl/team-news' in html


def test_etusivun_nosto_ei_lupaa_lehdistotilaisuutta():
    from scripts.build_fpl_page import team_news_block
    html = team_news_block({"players": [
        {"web_name": "A", "team_short": "ARS", "news": "Knock",
         "chance_next": 75, "owned_pct": 1.0}]})
    assert "official Fantasy Premier League status feed" in html


# ---------------------------------------------------------------------------
# Villen saanto: ennustepisteet vain omia
# ---------------------------------------------------------------------------
# 15.8: "jos team news tms uutisissa on jotain pistedataa tms niin sen tulee
# olla meidan omaa" — ja tarkennus: "viime kauden fpl pisteet ovat sellasia
# jotka voi nakya, ne on muuttumattomia" seka "miten meidan viime kauden fpl
# pisteet muka eroavat niista toteutuneista oikeista?".
#
# Raja on siis TOTEUTUNUT vs ENNUSTETTU, ei lahde. Toteutuneesta ei ole
# olemassa "meidan versiota": silla on yksi arvo. Ennustettu luku sen sijaan
# on aina jonkun malli, ja sivulla saa esiintya vain meidan.

def test_ruled_out_nayttaa_seka_toteutuneen_etta_OMAN_ennusteen():
    html = render_team_news(_xp(
        [_p("Korvaaja", team_short="ARS", pos="MID", xp_horizon_total=26.1)],
        [_p("Ulkona", team_short="ARS", pos="MID", chance_next=0,
            news="Knee injury", last_season={"points": 113})],
    ), NOW)
    rivit = _rows(html, "out")
    assert len(rivit) == 1
    assert "113 last yr" in rivit[0][-2], "toteutunut piste puuttuu"
    assert "Korvaaja" in rivit[0][-1] and "26.1" in rivit[0][-1], (
        "oma ennusteemme (kuka korvaa) puuttuu viimeisesta sarakkeesta")


def test_korvaajasarake_ei_ehdota_poissaolevaa_itseaan():
    """Jos seuran paras samassa positiossa ON poissaoleva itse, sarake on
    tyhja. Muuten sivu neuvoisi korvaamaan pelaajan itsellaan."""
    html = render_team_news(_xp(
        [_p("Sama", team_short="ARS", pos="MID", xp_horizon_total=10.0)],
        [_p("Sama", team_short="ARS", pos="MID", chance_next=0,
            news="Knee injury")],
    ), NOW)
    rivit = _rows(html, "out")
    assert rivit[0][-1] == "-", f"korvaajaksi ehdotettiin: {rivit[0][-1]}"


def test_sivu_sanoo_etta_ennusteluvut_ovat_omia():
    html = render_team_news(_xp(
        [_p("K", team_short="ARS", pos="MID", xp_horizon_total=9.0)],
        [_p("U", team_short="ARS", pos="MID", chance_next=0, news="Injury",
            last_season={"points": 50})],
    ), NOW)
    assert "our own number" in html
    assert "fixed historical number" in html


def test_paasivulla_on_team_news_markerit():
    """Villen havainto 15.8: "https://goaliq.app/ en nae mitaan uutisjuttua ...
    toi on se meidan paasivu". Lohko oli vain fpl.html:ssa.

    index.html on kasin yllapidettya HTML:aa jossa generoitu sisalto elaa
    markerien valissa. Ilman markereita update_index heittaa, mutta ilman TATA
    testia markerit voi poistaa index.html:sta eika mikaan huuda ennen
    seuraavaa buildia."""
    idx = (ROOT / "index.html").read_text(encoding="utf-8")
    assert idx.count("<!-- GEN:TEAM-NEWS-START -->") == 1
    assert idx.count("<!-- GEN:TEAM-NEWS-END -->") == 1
    assert '/fpl/team-news' in idx, "paasivu ei linkita team news -sivulle"
