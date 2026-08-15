"""Portti: uusin muistio on etusivun nostossa ja muistiosivun ylimpana.

MITATTU VIKA (15.8.2026). Kaksi muistiota kirjoitettiin samalle paivalle.
Lajittelu kaytti pelkkaa paivaysta, ja Pythonin vakaa sorttaus sailyttaa
yhtasuurten alkuperaisen jarjestyksen — joten etusivun "Latest from the
model" jai nayttamaan AAMUN muistiota vaikka uudempi oli jo julkaistu.

Vika oli nakymaton koodista: molemmat muistiot olivat olemassa, sivu
renderoitui virheetta ja `fpl.html` ei edes muuttunut uudelleenajossa. Se
loytyi vasta vertaamalla generoitua artefaktia siihen mita piti nakya.

Tarkeys: Ville pyysi 15.8 nimenomaan etta artikkeli on "niin isosti esilla
etta sivulle tulija huomaa sen heti". Nosto joka nayttaa vanhaa on juuri se
lupaus rikottuna.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.build_fpl_page import latest_articles_block  # noqa: E402

VANHA = {
    "slug": "aamu", "date": "2026-08-15", "title": "Aamun muistio",
    "paragraphs": ["Aamun ensimmainen kappale."],
}
UUSI = {
    "slug": "ilta", "date": "2026-08-15", "title": "Illan artikkeli",
    "paragraphs": ["Illan ensimmainen kappale."],
}


def test_saman_paivan_uudempi_voittaa():
    html = latest_articles_block({"notes": [VANHA, UUSI]}, limit=1)
    assert "Illan artikkeli" in html
    assert "Aamun muistio" not in html


def test_negatiivinen_kontrolli_vanhempi_paiva_ei_voita():
    """Jarjestysnumero ei saa ohittaa PAIVAYSTA. Jos se ohittaisi, myohemmin
    listaan lisatty vanha muistio nousisi nostoon."""
    vanhempi = dict(UUSI, date="2026-08-01", title="Elokuun alusta")
    html = latest_articles_block({"notes": [VANHA, vanhempi]}, limit=1)
    assert "Aamun muistio" in html
    assert "Elokuun alusta" not in html


def test_lede_on_ensimmainen_TEKSTIkappale():
    """Muistio voi alkaa valiotsikko- tai taulukkolohkolla. Niiden str()-esitys
    olisi Python-dict etusivulla, eli rikkinaista tekstia lukijalle."""
    lohkoilla = {
        "slug": "x", "date": "2026-08-16", "title": "Taulukolla alkava",
        "paragraphs": [
            {"h2": "Valiotsikko"},
            {"head": ["A"], "rows": [["1"]]},
            "Tama on oikea lede.",
        ],
    }
    html = latest_articles_block({"notes": [lohkoilla]}, limit=1)
    assert "Tama on oikea lede." in html
    assert "h2" not in html.split('note-lede')[1][:200]
    assert "rows" not in html


def test_negatiivinen_kontrolli_pelkat_lohkot_eivat_tuota_korttia():
    """Jos muistiossa EI ole yhtaan tekstikappaletta, korttia ei synny —
    tyhja lede olisi huonompi kuin puuttuva kortti."""
    vain_lohkot = {
        "slug": "y", "date": "2026-08-16", "title": "Ei tekstia",
        "paragraphs": [{"h2": "Vain otsikko"}],
    }
    assert latest_articles_block({"notes": [vain_lohkot]}, limit=1) == ""


def test_tyhja_data_ei_kaada():
    assert latest_articles_block(None, limit=1) == ""
    assert latest_articles_block({}, limit=1) == ""
    assert latest_articles_block({"notes": []}, limit=1) == ""
