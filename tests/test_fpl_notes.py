"""Portti kierrosmuistioille (/fpl/notes).

TAUSTA (15.8.2026, Villen GO). Muistio kirjoitetaan kasin kierrosta varten ja
se kay julkaisutarkistajan lapi. Se EI ole "ihmisen kirjoittama" — kirjoitin
llms.txt:aan sellaisen vaitteen ja se oli valhe, Villen huomio samana paivana.
Sita EI generoida: portti blokkasi
ensimmaisen version kuudella loydoksella joista nelja koski tyylia, ja
generaattori tuottaisi tasan ne.

Koneellisesti tarkistettava osa on se joka petti: onko jokainen luku
loydettavissa siita sivusta johon muistio linkittaa. Siksi jokaisella
merkinnalla on PAKOLLINEN `claims`-lista ja `check_url`, ja
scripts/check_claim_route.py ajaa ne tuotantoa vasten ennen julkaisua.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.build_fpl_longtail import NOTES_PATH, render_notes  # noqa: E402

NOW = datetime(2026, 8, 15, tzinfo=timezone.utc)


def _doc() -> dict:
    return json.loads(NOTES_PATH.read_text(encoding="utf-8"))


def test_tyhja_lista_ei_tuota_sivua():
    """Sivu jolla ei ole muistioita on lupaus ilman sisaltoa."""
    assert render_notes({"notes": []}, NOW) is None
    assert render_notes({}, NOW) is None


def test_merkinta_ilman_kappaleita_ohitetaan():
    assert render_notes({"notes": [{"title": "X", "paragraphs": []}]}, NOW) is None


def test_jokaisella_merkinnalla_on_tarkistusreitti():
    """PAKOLLINEN: ilman claims-listaa ja check_urlia muistion lukuja ei voi
    ajaa check_claim_route.py:lla, ja juuri se tarkistus petti 15.8."""
    for n in _doc()["notes"]:
        assert n.get("check_url"), f"{n.get('slug')}: check_url puuttuu"
        assert n.get("claims"), f"{n.get('slug')}: claims puuttuu"
        assert len(n["claims"]) >= 3, f"{n.get('slug')}: claims on liian ohut"


def test_jokainen_claim_esiintyy_muistion_tekstissa():
    """Claims-lista ei saa ajautua erilleen tekstista: silloin ajaisimme
    tarkistuksen luvuille joita muistiossa ei ole, ja painvastoin."""
    for n in _doc()["notes"]:
        teksti = " ".join(n["paragraphs"])
        puuttuu = [c for c in n["claims"] if c not in teksti]
        assert not puuttuu, f"{n['slug']}: claims joita ei ole tekstissa: {puuttuu}"


def test_uusin_muistio_on_ensin():
    doc = _doc()
    doc["notes"] = [
        {"slug": "vanha", "date": "2026-01-01", "title": "Vanha",
         "paragraphs": ["a"], "check_url": "https://x.test"},
        {"slug": "uusi", "date": "2026-08-15", "title": "Uusi",
         "paragraphs": ["b"], "check_url": "https://x.test"},
    ]
    html = render_notes(doc, NOW)
    assert html.index('id="uusi"') < html.index('id="vanha"')


def test_sivu_sanoo_etta_luvut_ovat_omia_ja_tarkistettavissa():
    html = render_notes(_doc(), NOW)
    assert "our own model output" in html
    assert "free page you can open" in html


def test_muistio_linkittaa_tarkistussivulle():
    html = render_notes(_doc(), NOW)
    for n in _doc()["notes"]:
        assert n["check_url"] in html, f"{n['slug']}: check_url ei ole sivulla"
