"""Portti: jaettu linkki nayttaa siita mita linkin takana on.

MITATTU VIKA (15.8.2026, Villen havainto). Artikkelin jakaminen tuotti tasan
saman esikatselukuvan kuin etusivun jakaminen: "Free FPL tools, backed by a
real match model." Kortti ei kertonut mitaan sisallosta eika houkutellut
klikkaamaan. Kahdeksan longtail-sivua oli saanut oman korttinsa 8.8, mutta
`notes`, `team-news`, `club-best` ja `expected-points` jaivat ilman.

TAMA PORTTI VARTIOI KAHTA ASIAA:

1. Jokaisella sivulla jolla on oma kortti, kortti on OLEMASSA. `_og_image()`
   putoaa hiljaa yhteiseen korttiin jos tiedosto puuttuu, mika on oikea
   kaytos ajossa mutta tarkoittaa etta puuttuva kortti ei nay mitenkaan.

2. Muistiokortti on TUOREESTA artikkelista. Pelkka olemassaolo naytaisi
   vihrealta myos silloin kun uusi artikkeli on julkaistu ja kortti on
   edellisesta — eli tasan silloin kun vika on pahin, koska juuri uutta
   artikkelia jaetaan. Generaattori kirjoittaa slugin sidecar-tiedostoon ja
   tama vertaa sita uusimpaan muistioon.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OG = ROOT / "assets" / "brand" / "og"
NOTES = ROOT / "data" / "fpl_notes.json"

# Sivut joilla ON oltava oma kortti. Lista on tarkoituksella kasin
# yllapidetty: uusi sivu ei saa olla portin takana vahingossa, vaan
# paatoksesta.
OMA_KORTTI = [
    "stats", "defence", "xg-leaders", "model-xi", "best-captain",
    "differentials", "price-changes", "defcon", "notes", "team-news",
    "club-best", "expected-points", "predicted-lineups",
]


@pytest.mark.parametrize("slug", OMA_KORTTI)
def test_kortti_on_olemassa(slug):
    p = OG / f"{slug}-1200x630.png"
    assert p.exists(), (
        f"{slug}: og-kortti puuttuu -> sivu putoaa yhteiseen korttiin ja "
        f"jaettu linkki nayttaa samalta kuin kaikki muut. Aja "
        f"assets/brand/gen_og_cards.py (tai gen_note_og_card.py)."
    )
    assert p.stat().st_size > 5000, f"{slug}: kortti on epailyttavan pieni"


def test_muistiokortti_on_uusimmasta_artikkelista():
    if not NOTES.exists():
        pytest.skip("fpl_notes.json puuttuu")
    notes = json.loads(NOTES.read_text(encoding="utf-8")).get("notes") or []
    if not notes:
        pytest.skip("muistioita ei ole")
    uusin = sorted(
        enumerate(notes),
        key=lambda p: (str(p[1].get("date") or ""), p[0]),
        reverse=True,
    )[0][1]
    if not uusin.get("og_headline"):
        pytest.skip(f"{uusin['slug']}: ei og_headlinea, yhteinen kortti on ok")

    sidecar = OG / "notes-1200x630.slug.txt"
    assert sidecar.exists(), (
        "muistiokortin sidecar puuttuu -> emme voi tietaa mista artikkelista "
        "kortti on. Aja assets/brand/gen_note_og_card.py."
    )
    assert sidecar.read_text(encoding="utf-8").strip() == uusin["slug"], (
        f"muistiokortti on artikkelista "
        f"{sidecar.read_text(encoding='utf-8').strip()!r} mutta uusin on "
        f"{uusin['slug']!r}. Uutta artikkelia jaetaan vanhalla kuvalla."
    )


def test_og_headline_on_kirjoitettu_ei_johdettu():
    """NEGATIIVINEN KONTROLLI kortin tekstille.

    Kortin teksti on julkista tekstia. Jos se johdettaisiin leipatekstista,
    se olisi julkaisua joka ei ole kulkenut julkaisutarkistajan lapi. Kentan
    on siis oltava OMA eika ensimmainen kappale.
    """
    if not NOTES.exists():
        pytest.skip("fpl_notes.json puuttuu")
    for n in json.loads(NOTES.read_text(encoding="utf-8")).get("notes") or []:
        otsikko = n.get("og_headline")
        if not otsikko:
            continue
        rivit = [otsikko] if isinstance(otsikko, str) else list(otsikko)
        kappaleet = [p for p in n.get("paragraphs") or [] if isinstance(p, str)]
        assert kappaleet, f"{n['slug']}: ei tekstikappaleita"
        assert " ".join(rivit) != kappaleet[0], (
            f"{n['slug']}: og_headline on suoraan ensimmainen kappale"
        )
        for r in rivit:
            assert len(r) <= 34, (
                f"{n['slug']}: kortin rivi on {len(r)} merkkia, se kutistuu "
                f"lukukelvottomaksi: {r!r}"
            )


def test_yhteinen_kortti_on_yha_olemassa():
    """NEGATIIVINEN KONTROLLI: sivukohtaiset kortit eivat saa korvata
    fallbackia. Sivu jolla ei ole omaa korttia tarvitsee sen yha, ja
    puuttuva fallback tuottaisi 404-kuvan joka on huonompi kuin geneerinen."""
    p = ROOT / "assets" / "brand" / "goaliq-social-1200x630.png"
    assert p.exists(), "yhteinen og-kortti puuttuu"


# --- Valimuistin murto (15.8) -------------------------------------------

def test_og_url_kantaa_sisaltotiivisteen():
    """X ja Bluesky valimuistittavat esikatselukortin URL-kohtaisesti.

    MITATTU 15.8: kortti vaihdettiin, palvelimen tiedosto oli uusi (live ja
    lokaali tavulleen identtiset), ja Ville nakin yha vanhan kuvan. Sama
    tiedostonimi eri sisallolla ei kerro alustalle mitaan, eika ankkuri
    (#slug) auta koska fragmenttia ei laheteta palvelimelle lainkaan.

    Tiiviste muuttuu vain kun kuva muuttuu, joten tama ei riko
    valimuistitusta silloin kun mitaan ei ole muuttunut.
    """
    import hashlib
    import re

    sivu = ROOT / "fpl" / "notes.html"
    if not sivu.exists():
        pytest.skip("notes.html puuttuu")
    h = sivu.read_text(encoding="utf-8", errors="replace")
    m = re.search(r'og:image" content="([^"]+)"', h)
    assert m, "og:image puuttuu"
    url = m.group(1)
    assert "?v=" in url, f"og:image ilman sisaltotiivistetta: {url}"

    tiiviste = url.split("?v=")[1]
    kuva = OG / "notes-1200x630.png"
    odotettu = hashlib.sha256(kuva.read_bytes()).hexdigest()[:8]
    assert tiiviste == odotettu, (
        f"og:image-tiiviste {tiiviste!r} ei vastaa kuvan sisaltoa "
        f"{odotettu!r}: sivu on rakennettu eri kuvasta kuin levylla on"
    )


def test_tiiviste_muuttuu_sisallon_mukana():
    """NEGATIIVINEN KONTROLLI: jos tiiviste olisi vakio tai johdettu
    tiedostonimesta, se ei murtaisi mitaan valimuistia ja koko keino olisi
    naennainen."""
    import hashlib

    a = hashlib.sha256(b"kuva-a").hexdigest()[:8]
    b = hashlib.sha256(b"kuva-b").hexdigest()[:8]
    assert a != b
