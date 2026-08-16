"""Luojan ref ei saa kadota hubin ja SPA:n valiin (16.8.2026).

MITATTU TAPAUS. Affiliate-attribuutio kaapataan SPA:ssa (pro.goaliq.app):
`captureRef` lukee `?ref=` ja tallentaa sen localStorageen, josta signUp
liittaa sen tiliin. Se toimii vain jos kavija LASKEUTUU pro.goaliq.appiin
ref mukanaan.

Luojat eivat linkita niin. He linkittavat sivun joka lukee parhaiten, eli
goaliq.appiin tai goaliq.app/fpl:aan. Ne ovat ERI ORIGIN, joten hubiin
tallennettu ref on SPA:lle nakymaton - same-origin-saanto ei ole yksityis-
kohta jonka voi kiertaa. Luoja joka postasi `goaliq.app/fpl?ref=WOLFY` sai
tasan nolla attribuutiota, eika kumpikaan osapuoli nahnyt sita tapahtuvan.

Korjaus: refia ei tallenneta SPA:lle vaan se KANNETAAN sinne. `ref-bridge.js`
muistaa refin hubin sisalla ja liittaa sen jokaiseen pro.goaliq.app-linkkiin.

🔴 Tama portti on rakenteellinen (sivut + skriptin sisalto). Selaimessa
todennettu erikseen 16.8: index.html?ref=WOLFY -> 7/7 SPA-linkkia tagattu,
seuraava hub-sivu ilman parametria -> 6/6 tagattu, tyhja storage -> 0/6
tagattu.
"""
from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "ref-bridge.js"
GENERATOR = ROOT / "scripts" / "build_fpl_page.py"
TAG = "ref-bridge.js"
SPA_HOST = "pro.goaliq.app"


def _hub_pages_linking_to_spa() -> list[pathlib.Path]:
    """Hub-sivut jotka linkittavat SPA:han.

    Lista JOHDETAAN, ei kovakoodata: uusi sivu joka linkittaa SPA:han on
    tasan se tapaus jossa silta unohtuu, ja kovakoodattu lista ei nakisi
    sita koskaan.
    """
    out = []
    for p in sorted(ROOT.glob("*.html")):
        if SPA_HOST in p.read_text(encoding="utf-8"):
            out.append(p)
    return out


def test_bridge_exists_and_targets_the_spa_host():
    src = BRIDGE.read_text(encoding="utf-8")
    assert SPA_HOST in src, "silta ei tunnista SPA:n hostia"
    assert "searchParams.set('ref'" in src, "silta ei liita refia linkkiin"
    assert "localStorage" in src, "silta ei muista refia sivunvaihdon yli"


def test_bridge_regex_matches_the_spa_and_backend_rule():
    """Kolme kopiota samasta saannosta kolmella kielella. Eroavaisuus
    epaonnistuisi HILJAA - juuri niin kuin tama tiedosto on olemassa
    estamaan."""
    src = BRIDGE.read_text(encoding="utf-8")
    assert re.search(r"\^\[A-Z0-9_-\]\{2,32\}\$", src), (
        "sillan ref-validointi ei vastaa SPA:n cleanRefia eika backendin "
        "_clean_affiliate_refia")


def test_every_hub_page_that_links_to_the_spa_loads_the_bridge():
    missing = [p.name for p in _hub_pages_linking_to_spa()
               if TAG not in p.read_text(encoding="utf-8")]
    assert not missing, (
        "nama sivut linkittavat pro.goaliq.appiin ILMAN ref-siltaa, eli "
        f"luojan linkki niille menettaa attribuution: {missing}")


def test_generated_fpl_page_gets_the_bridge_from_its_generator():
    """fpl.html on generoitu. Pelkka tiedostoon lisatty tagi katoaisi
    hiljaa seuraavassa data-refreshissa."""
    assert TAG in GENERATOR.read_text(encoding="utf-8"), (
        "scripts/build_fpl_page.py ei kirjoita ref-siltaa, joten seuraava "
        "regenerointi pudottaa sen fpl.html:sta")


def test_negative_control_page_without_spa_link_is_not_required_to_have_it():
    """Portti ei saa vaatia siltaa sivulta joka ei linkita SPA:han - muuten
    se olisi kohinaa joka opettaa ohittamaan portin."""
    all_pages = set(ROOT.glob("*.html"))
    linking = set(_hub_pages_linking_to_spa())
    assert linking, "yksikaan sivu ei linkita SPA:han - portti mittaa tyhjaa"
    assert linking <= all_pages
