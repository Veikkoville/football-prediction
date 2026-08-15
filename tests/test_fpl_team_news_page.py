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
    assert "113" in rivit[0][-1]
    assert "last yr" in rivit[0][-1], (
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
