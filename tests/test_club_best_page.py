"""Portit /fpl/club-best -sivulle ja sen ja jakokortin yhtapitavyydelle.

MIKSI NAMA OVAT OLEMASSA. Jakokortin alatunniste ohjaa lukijan tälle
sivulle todistamaan kortin luvut. Se tekee kahdesta pinnasta yhden vaitteen:
jos ne ajautuvat erilleen, kortti ohjaa lukijan kumoamaan oman lukunsa.

Alatunniste on ollut vaarin jo kahdesti (14.8):
  1. "goaliq.app/fpl" — se sivu renderoi listansa MASKATUSTA top-10-teaserista,
     eli 17 rivia 20:sta ei ollut tarkistettavissa.
  2. raaka JSON "goaliq.app/data/..." — reitti vastasi 200, mutta 1,3 MB JSON
     puhelimen selaimessa ei ole tarkistus vaan este. Portti ei nostanut sita
     koska se testasi vain HTTP-statuksen.
Siksi alla ei testata "vastaako URL" vaan "onko rivi siella".
"""
from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.models.fpl_club_best import POSITIONS, club_best_rows, gap_text

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "fpl" / "club-best.html"
XP = ROOT / "data" / "fpl_xp_projections.json"

_spec = importlib.util.spec_from_file_location(
    "gen_share_card", ROOT / "scripts" / "gen_share_card.py")
gsc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gsc)


@pytest.fixture(scope="module")
def payload():
    return json.loads(XP.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def html():
    if not PAGE.exists():
        pytest.skip("sivua ei ole rakennettu talla koneella")
    return PAGE.read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# Kortti ja sivu ovat sama vaite
# --------------------------------------------------------------------------

@pytest.mark.parametrize("pos", POSITIONS)
def test_every_card_row_is_on_the_page(payload, html, pos):
    """Kortin jokainen rivi on loydyttava sivulta NIMELLA JA LUVULLA.

    Tama on koko alatunnisteen lupaus. Jos rivi puuttuu, kortti ohjaa
    lukijan sivulle jolta se ei loydy.
    """
    rows = club_best_rows(payload["players"], pos)
    assert rows, f"ei rivejä positiolle {pos}"
    missing = [r["name"] for r in rows if str(r["name"]) not in html]
    assert not missing, f"{pos}: kortin rivit puuttuvat sivulta: {missing}"
    wrong = [f'{r["name"]} {r["xp"]:.1f}' for r in rows
             if f'{r["xp"]:.1f}' not in html]
    assert not wrong, f"{pos}: xP-luku ei tasmaa sivulla: {wrong}"


def test_card_footnote_points_at_the_page_not_at_raw_data(payload):
    """Alatunniste ei saa osoittaa maskattuun pintaan eika raakadataan."""
    import types
    spec = gsc.card_club_best(types.SimpleNamespace(pos="MID", top=10,
                                                    min_mins=400))
    foot = spec["footNote"]
    assert "goaliq.app/fpl/club-best" in foot
    assert ".json" not in foot, "raaka JSON ei ole ihmisluettava tarkistus"
    assert "goaliq.app/fpl " not in foot and not foot.endswith("goaliq.app/fpl")


def test_card_and_page_use_the_same_gap_wording(payload):
    """Sanamuodon on tultava jaetusta moduulista. Jos kortti sanoo
    "+6.7 vs next" ja sivu jotain muuta, lukija ei loyda samaa riviä."""
    rows = club_best_rows(payload["players"], "MID")
    import types
    spec = gsc.card_club_best(types.SimpleNamespace(pos="MID", top=10,
                                                    min_mins=400))
    card_mid = [r["mid"] for r in spec["rows"]]
    assert card_mid == [gap_text(r) for r in rows]


# --------------------------------------------------------------------------
# Sivun oma sisalto
# --------------------------------------------------------------------------

def test_page_covers_all_four_positions(html):
    for pos in POSITIONS:
        assert f"Best {pos} at every club" in html


def test_page_includes_promoted_club_leaders(payload, html):
    """NAMA OVAT KOKO SIVUN OLEMASSAOLON SYY. `/fpl/expected-points` on
    `rows[:100]`, joten nousijaseurojen karjet eivat mahdu sinne — ja ne ovat
    tasan ne rivit joita lukija todennakoisimmin haluaa tarkistaa."""
    top100 = {p["web_name"] for p in sorted(
        payload["players"],
        key=lambda p: -(p.get("xp_horizon_total") or 0))[:100]}
    outside = [r["name"] for pos in POSITIONS
               for r in club_best_rows(payload["players"], pos)
               if r["name"] not in top100]
    assert outside, "odotettiin rivejä top-100:n ulkopuolelta"
    missing = [n for n in outside if str(n) not in html]
    assert not missing, f"top-100:n ulkopuoliset puuttuvat sivulta: {missing}"


def test_page_explains_the_gap_column(html):
    """Sarake on kortin oma kulma ja se on helppo lukea vaarin listan
    seuraavaan riviin. Selite on siksi pakollinen."""
    assert "same club and the same position" in html


def test_page_is_english_only(html):
    """Julkinen copy on aina englanniksi."""
    assert 'lang="en"' in html
    for word in (" jokainen ", " seuran ", " pelaaja ", " ilman "):
        assert word not in html.lower(), f"suomea sivulla: {word!r}"


def test_page_has_no_em_dash(html):
    assert "—" not in html


def test_page_is_in_the_tool_nav():
    """Sivu jolle ei osoita yksikaan linkki on orpo, eika Google priorisoi
    sen indeksointia. Mitattu aiemmin: fpl.html -> 0 kpl /fpl/*-linkkeja."""
    src = (ROOT / "scripts" / "build_fpl_longtail.py").read_text(encoding="utf-8")
    assert '("/fpl/club-best"' in src


def test_page_is_in_the_sitemap():
    sm = ROOT / "sitemap-fpl.xml"
    if not sm.exists():
        pytest.skip("sitemappia ei ole rakennettu talla koneella")
    assert "/fpl/club-best" in sm.read_text(encoding="utf-8")
