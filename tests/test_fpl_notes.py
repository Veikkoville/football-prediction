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

from scripts.build_fpl_longtail import (  # noqa: E402
    NOTES_PATH,
    note_plain_text,
    render_notes,
)

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
        teksti = note_plain_text(n)
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


# ---------------------------------------------------------------------------
# Etusivun esilletuonti
# ---------------------------------------------------------------------------
# Villen pyynto 15.8: FFScoutilla on etusivulla "latest articles" joka nakyy
# heti kun saavut sivulle. Meilla muistiot olivat /fpl/notes-osoitteessa johon
# paasi vain alatunnisteen kautta — kirjoitettu sisalto oli kaytannossa
# nakymatonta, eli sen kirjoittaminen oli hukkaan heitettya tyota.

def test_etusivun_lohko_ilman_dataa_on_tyhja():
    from scripts.build_fpl_page import latest_articles_block
    assert latest_articles_block(None) == ""
    assert latest_articles_block({"notes": []}) == ""
    assert latest_articles_block({"notes": [{"title": "X", "paragraphs": []}]}) == ""


def test_etusivun_lohko_nayttaa_VAIN_uusimman():
    """Featured on YKSI kortti, ei kolme. Lohko joka kilpailee itsensa kanssa
    ei ole featured, ja se on heron oikeassa palstassa jossa tilaa on yhdelle."""
    from scripts.build_fpl_page import latest_articles_block
    notes = [
        {"slug": "vanha", "date": "2026-01-01", "title": "Vanha",
         "paragraphs": ["A."]},
        {"slug": "uusi", "date": "2026-08-15", "title": "Uusi",
         "paragraphs": ["B."]},
    ]
    html = latest_articles_block({"notes": notes})
    assert "Uusi" in html
    assert "Vanha" not in html, "featured-lohkossa on useampi kuin yksi kortti"
    # Jarjestys on silti uusin ensin, mikä nakyy kun rajaa nostetaan.
    kaksi = latest_articles_block({"notes": notes}, limit=2)
    assert kaksi.index("Uusi") < kaksi.index("Vanha")


def test_etusivun_lohko_linkittaa_ankkuriin():
    """Kortin on vietava SIIHEN muistioon eika vain sivun ylaosaan."""
    from scripts.build_fpl_page import latest_articles_block
    html = latest_articles_block({"notes": [
        {"slug": "abc", "date": "2026-08-15", "title": "T", "paragraphs": ["A."]}]})
    assert 'href="/fpl/notes#abc"' in html


def test_etusivun_lohko_ei_katkaise_ledea():
    """Kolme pistetta on lupaus jota lohko ei pida. Ensimmainen kappale on
    kirjoitettu kantamaan itsenaisesti, joten se nayteta kokonaan."""
    from scripts.build_fpl_page import latest_articles_block
    lede = "Ensimmainen kappale joka on tarkoituksella melko pitka jotta katkaisu nakyisi."
    html = latest_articles_block({"notes": [
        {"slug": "a", "date": "2026-08-15", "title": "T", "paragraphs": [lede]}]})
    assert lede in html
    assert "…" not in html and "..." not in html


def test_paasivulla_on_latest_articles_markerit():
    idx = (ROOT / "index.html").read_text(encoding="utf-8")
    assert idx.count("<!-- GEN:LATEST-ARTICLES-START -->") == 1
    assert idx.count("<!-- GEN:LATEST-ARTICLES-END -->") == 1


def test_lohko_on_HERON_SISALLA_eika_sen_alla():
    """🔴 SIJAINTI ON OSA VAATIMUSTA, ja se mitattiin selaimella.

    Laitoin lohkon ensin heron jalkeen omaksi sectionikseen. Mitattu:
    y = 1051 px, eli palkki nakyi juuri fold-rajalla ja sisalto ei lainkaan.
    Villen palaute: "en kylla vielakaan nae mitaan livena tosta". Curl nakisi
    sen, kayttaja ei.

    Nyt se on heron oikeassa palstassa track record -kortin alla. Jos joku
    siirtaa sen ulos herosta, tama kaatuu."""
    idx = (ROOT / "index.html").read_text(encoding="utf-8")
    hero_alku = idx.index('<header class="hero">')
    hero_loppu = idx.index("</header>", hero_alku)
    marker = idx.index("GEN:LATEST-ARTICLES-START")
    assert hero_alku < marker < hero_loppu, (
        "featured-lohko ei ole heron sisalla -> se putoaa fold-rajan alle")
    assert marker < idx.index("GEN:XP-TABLE-START")


# ---------------------------------------------------------------------------
# Seurasivut
# ---------------------------------------------------------------------------

def test_seurasivun_XI_alkaa_maalivahdista_ja_on_11():
    """🔴 MITATTU VIKA. Kirjoitin kiintioon {"GK": 1, ...} vaikka FPL:n koodi
    on "GKP", ja `src.models.fpl_club_best.POSITIONS` tiesi sen jo. Jokaisen
    20 seuran "Predicted XI" renderoitui KYMMENELLA pelaajalla ilman
    maalivahtia, ja korjauksen jalkeen maalivahti sortautui listan hannille
    koska sama kovakoodaus oli jarjestyksessa. Kumpikin nakyi vasta valmiilla
    sivulla, ei koodia lukemalla."""
    import re
    d = ROOT / "fpl" / "club"
    if not d.exists():  # pragma: no cover
        pytest.skip("seurasivuja ei ole rakennettu")
    sivut = sorted(d.glob("*.html"))
    assert len(sivut) >= 18, f"seurasivuja vain {len(sivut)}"
    for f in sivut:
        h = f.read_text(encoding="utf-8")
        blk = re.search(r'<h2 id="xi">.*?</table>', h, re.S)
        if not blk:
            continue
        rivit = [r for r in re.findall(r"<tr>(.*?)</tr>", blk.group(0), re.S)
                 if "<td" in r]
        assert len(rivit) == 11, f"{f.stem}: XI:ssa {len(rivit)} pelaajaa"
        eka = re.findall(r"<td[^>]*>(.*?)</td>", rivit[0], re.S)
        assert "GKP" in re.sub(r"<[^>]+>", "", eka[1]), (
            f"{f.stem}: XI ei ala maalivahdista")


def test_seurasivut_ovat_sitemapissa():
    """Alihakemisto ei nay `glob('*.html')`-haussa, joten 20 sivua olisi
    olemassa mutta poissa sitemapista."""
    sm = (ROOT / "sitemap-fpl.xml").read_text(encoding="utf-8")
    d = ROOT / "fpl" / "club"
    if not d.exists():  # pragma: no cover
        pytest.skip("seurasivuja ei ole")
    for f in sorted(d.glob("*.html")):
        assert f"/fpl/club/{f.stem}" in sm, f"{f.stem} puuttuu sitemapista"


def test_seurasivuihin_linkitetaan_club_bestista():
    """Sitemap on hakukoneille. Lukija tarvitsee linkin."""
    cb = ROOT / "fpl" / "club-best.html"
    if not cb.exists():  # pragma: no cover
        pytest.skip("club-best puuttuu")
    h = cb.read_text(encoding="utf-8")
    assert h.count("/fpl/club/") >= 15, (
        "club-best ei linkita seurasivuihin -> ne jaavat orvoiksi")


def test_seurasivu_kertoo_mita_tyhja_erikoistilanne_tarkoittaa():
    """Rehellisyysrajaus koodissa eika vain copyssa: tyhja vuoro tarkoittaa
    ettei FPL ole julkaissut jarjestysta, EI etta pelaaja ei ota niita."""
    f = ROOT / "fpl" / "club" / "bournemouth.html"
    if not f.exists():  # pragma: no cover
        pytest.skip("sivua ei ole")
    h = f.read_text(encoding="utf-8")
    assert "has not published an order" in h
    assert "not a lineup leak" in h
