"""SIVUSOPIMUS: jokainen generoitu sivu on SEO-, GEO- ja loydettavyyskunnossa.

TAUSTA (15.8.2026, Villen vaatimus: "seo ja geo yms automaattisesti aina
kuntoon uusille sivuille seka loydettavyys").

Vaatimus on oikea, ja saman paivan todiste on etta unohdin sen JOKA KERTA:

  team-news       unohtui `_TOOL_LINKS`:sta ja llms.txt:sta
  expected-points oli ollut orpo `_TOOL_LINKS`:sta 9.8 lahtien — ja se on se
                  sivu johon X-postaukset linkittavat
  notes           piti muistaa erikseen kolmeen paikkaan
  club/* (20 kpl) ei nakynyt sitemapissa lainkaan, koska ne ovat
                  alihakemistossa jota `glob("*.html")` ei nae

Muistilista ei toimi. Tama tiedosto on SOPIMUS: uusi sivu joka ei tayta sita
kaataa buildin, eika kukaan joudu muistamaan mitaan.

SOPIMUKSEN VIISI KOHTAA
  1. title + meta description        hakutulos
  2. canonical                       duplikaattien esto
  3. og + twitter                    jakaminen
  4. JSON-LD                         GEO, koneluettava konteksti
  5. sitemap + SISAANTULEVA LINKKI   loydettavyys

Kohta 5 on tarkein ja se on kaksiosainen tarkoituksella. Sitemap on
hakukoneille; LUKIJA tarvitsee linkin. Sivu joka on vain sitemapissa on
GSC:n sanoin "Viittaava sivu: Ei havaittuja", ja se mitattiin meilla 28.7.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FPL = ROOT / "fpl"
SITEMAP = ROOT / "sitemap-fpl.xml"
LLMS = ROOT / "llms.txt"


def _pages() -> list[tuple[str, Path]]:
    """[(url-polku, tiedosto)] kaikille generoiduille FPL-sivuille."""
    if not FPL.exists():  # pragma: no cover
        pytest.skip("fpl/-hakemistoa ei ole talla koneella")
    out = [(f"/fpl/{f.stem}", f) for f in sorted(FPL.glob("*.html"))]
    out += [(f"/fpl/club/{f.stem}", f)
            for f in sorted((FPL / "club").glob("*.html"))]
    return out


def _ids() -> list[str]:
    return [u for u, _ in _pages()]


@pytest.fixture(scope="module")
def sivut():
    p = _pages()
    assert len(p) >= 10, f"sivuja loytyi vain {len(p)} — onko build ajettu?"
    return p


@pytest.fixture(scope="module")
def kaikki_html(sivut):
    """Koko sivuston HTML yhtena merkkijonona sisaantulevien linkkien hakuun.

    Mukana myos kasin yllapidetyt hubit (index.html, fpl.html): linkki niista
    on ARVOKKAAMPI kuin linkki sisarsivulta, ja juuri ne unohtuvat.
    """
    osat = []
    for nimi in ("index.html", "fpl.html", "predictions.html"):
        f = ROOT / nimi
        if f.exists():
            osat.append(f.read_text(encoding="utf-8"))
    for _, f in sivut:
        osat.append(f.read_text(encoding="utf-8"))
    return "\n".join(osat)


@pytest.mark.parametrize("url", _ids())
def test_sivulla_on_hakutulosmeta(url):
    """title ja description: ilman naita sivu ei ole hakutuloksessa mitaan."""
    f = dict(_pages())[url]
    h = f.read_text(encoding="utf-8")
    t = re.search(r"<title>(.*?)</title>", h, re.S)
    assert t and len(t.group(1).strip()) > 15, f"{url}: title puuttuu tai on tynka"
    d = re.search(r'<meta name="description" content="([^"]{40,})"', h)
    assert d, f"{url}: meta description puuttuu tai on alle 40 merkkia"


@pytest.mark.parametrize("url", _ids())
def test_sivulla_on_canonical_joka_osoittaa_itseensa(url):
    f = dict(_pages())[url]
    h = f.read_text(encoding="utf-8")
    c = re.search(r'<link rel="canonical" href="([^"]+)"', h)
    assert c, f"{url}: canonical puuttuu"
    assert c.group(1).endswith(url), (
        f"{url}: canonical osoittaa muualle ({c.group(1)})")


@pytest.mark.parametrize("url", _ids())
def test_sivu_on_jaettavissa(url):
    """og + twitter: ilman naita linkki nayttaa tyhjalta jokaisessa chatissa."""
    f = dict(_pages())[url]
    h = f.read_text(encoding="utf-8")
    for pat, nimi in (
        (r'<meta property="og:title"', "og:title"),
        (r'<meta property="og:description"', "og:description"),
        (r'<meta property="og:image"', "og:image"),
        (r'<meta name="twitter:card"', "twitter:card"),
    ):
        assert re.search(pat, h), f"{url}: {nimi} puuttuu"


@pytest.mark.parametrize("url", _ids())
def test_sivulla_on_jsonld(url):
    """GEO: AI-vastausmoottorit lukevat rakenteisen kontekstin."""
    f = dict(_pages())[url]
    h = f.read_text(encoding="utf-8")
    assert '"@context": "https://schema.org"' in h or \
           '"@context":"https://schema.org"' in h, f"{url}: JSON-LD puuttuu"


@pytest.mark.parametrize("url", _ids())
def test_sivu_on_sitemapissa(url):
    sm = SITEMAP.read_text(encoding="utf-8")
    assert url in sm, (
        f"{url} puuttuu sitemap-fpl.xml:sta. Alihakemistot eivat nay "
        f"glob('*.html')-haussa — se pudotti 20 seurasivua 15.8.")


@pytest.mark.parametrize("url", _ids())
def test_sivulle_on_SISAANTULEVA_LINKKI(url, kaikki_html):
    """🔴 SOPIMUKSEN TARKEIN KOHTA.

    Sitemap on hakukoneille, linkki on lukijalle — ja Google priorisoi
    indeksointia linkkien mukaan. GSC sanoi meille 28.7 naista sivuista
    "Viittaava sivu: Ei havaittuja", ja `expected-points` oli siina tilassa
    9.8 lahtien vaikka X-postauksemme linkittivat siihen.

    Linkki sivulta itseltaan ei kelpaa: se on canonical eika suositus.
    """
    f = dict(_pages())[url]
    oma = f.read_text(encoding="utf-8")
    muut = kaikki_html.replace(oma, "")
    # Seurasivut linkitetaan kootusti club-best-sivulta, muut nimella.
    assert f'href="{url}"' in muut, (
        f"{url}: yksikaan TOINEN sivu ei linkita tanne -> orpo. "
        f"Lisaa linkki _TOOL_LINKSiin, club-bestiin tai fpl.html:aan.")


def test_jokainen_sivu_on_kuvattu_llms_txt_ssa(sivut):
    """GEO: llms.txt:n FPL-osio on KASIN yllapidetty, joten uusi sivu jaa
    siita pois eika mikaan huuda. Seurasivut kuvataan yhtena joukkona, joten
    riittaa etta polku `/fpl/club/` esiintyy."""
    llms = LLMS.read_text(encoding="utf-8")
    puuttuvat = []
    for url, _ in sivut:
        if url.startswith("/fpl/club/"):
            if "/fpl/club/" not in llms:
                puuttuvat.append(url)
        elif url not in llms:
            puuttuvat.append(url)
    assert not puuttuvat, "llms.txt:sta puuttuu: " + ", ".join(puuttuvat)


def test_sopimus_kattaa_kaikki_sivut(sivut):
    """Vahti vahdille: jos sivumaara romahtaa, testit menisivat lapi
    tyhjalla joukolla. Sama vika kuin tyhja lista joka ei ole virhe."""
    assert len(sivut) >= 25, f"sivuja vain {len(sivut)} — build vajaa?"


# ---------------------------------------------------------------------------
# Valikko
# ---------------------------------------------------------------------------
# Villen vaatimus 15.8: "jos sivuja alkaa olla paljon niin sitten menut
# pystyyn". Sivuja on 32 ja tasainen linkkirivi oli 30 sanaa perakkain ilman
# hierarkiaa.

def test_jokainen_toolink_paatyy_johonkin_ryhmaan():
    """Uusi sivu ei saa kadota valikosta hiljaa. Ryhmittelemattomat menevat
    "More"-ryhmaan, joten linkki nakyy vaikka ryhmittely unohtuisi."""
    from scripts.build_fpl_longtail import _NAV_GROUPS, _TOOL_LINKS, _tool_nav
    nav = _tool_nav("https://goaliq.app/fpl/ei-mikaan-sivu")
    for href, label in _TOOL_LINKS:
        assert f'href="{href}"' in nav, f"{href} puuttuu valikosta"
    ryhmitellyt = {h for _, hs in _NAV_GROUPS for h in hs}
    tuntemattomat = ryhmitellyt - {h for h, _ in _TOOL_LINKS}
    assert not tuntemattomat, (
        f"_NAV_GROUPS viittaa polkuihin joita ei ole _TOOL_LINKSissa: "
        f"{sorted(tuntemattomat)}")


def test_valikko_pudottaa_nykyisen_sivun():
    from scripts.build_fpl_longtail import _tool_nav
    nav = _tool_nav("https://goaliq.app/fpl/team-news")
    assert 'href="/fpl/team-news"' not in nav
    assert 'href="/fpl/club-best"' in nav


def test_valikko_on_ryhmitelty_eika_tasainen():
    from scripts.build_fpl_longtail import _tool_nav
    nav = _tool_nav("https://goaliq.app/fpl/notes")
    assert nav.count('class="navgrp"') >= 3, (
        "valikko ei ole ryhmitelty -> 30 linkkia perakkain")


# ---------------------------------------------------------------------------
# Seurasivujen keskinainen linkitys
# ---------------------------------------------------------------------------

def test_seurasivut_linkittavat_toisiinsa():
    """🔴 MITATTU 15.8: seurasivulta linkitettiin NOLLAAN toiseen seurasivuun.
    Sisaantulo oli kunnossa mutta 20 sisarsivua ilman keskinaista linkitysta
    on 20 umpikujaa. Sivuvaikutus joka on paavaikutus: jokainen sivu saa 19
    uutta sisaantulevaa linkkia."""
    d = FPL / "club"
    if not d.exists():  # pragma: no cover
        pytest.skip("seurasivuja ei ole")
    sivut = sorted(d.glob("*.html"))
    for f in sivut:
        h = f.read_text(encoding="utf-8")
        muut = set(re.findall(r'href="/fpl/club/([a-z-]+)"', h))
        assert len(muut) >= len(sivut) - 1, (
            f"{f.stem}: linkittaa vain {len(muut)} sisarsivuun")


def test_seuravalitsin_ei_linkita_olemattomiin_sivuihin():
    """CLUB_SLUGS kattaa 24 seuraa (nousijat ja putoajat), sivuja syntyy 20.
    Ensimmainen versio linkitti neljaan 404:aan. Kuollut linkki on pahempi
    kuin puuttuva."""
    d = FPL / "club"
    if not d.exists():  # pragma: no cover
        pytest.skip("seurasivuja ei ole")
    olemassa = {f.stem for f in d.glob("*.html")}
    for f in sorted(d.glob("*.html")):
        h = f.read_text(encoding="utf-8")
        kuolleet = set(re.findall(r'href="/fpl/club/([a-z-]+)"', h)) - olemassa
        assert not kuolleet, f"{f.stem}: kuolleet linkit {sorted(kuolleet)}"


def test_club_best_nostaa_seurasivut_omaksi_lohkokseen():
    """Villen havainto: linkit olivat pienessa harmaassa alaviitteessa
    pilkkuluettelona, eli 20 sivua piiloutui yhteen virkkeeseen."""
    f = FPL / "club-best.html"
    if not f.exists():  # pragma: no cover
        pytest.skip("club-best puuttuu")
    h = f.read_text(encoding="utf-8")
    assert '<h2 id="club-pages">' in h, "seurasivuilla ei ole omaa otsikkoa"
    assert 'class="clubnav"' in h, "linkit eivat ole chip-lohkona"


# ---------------------------------------------------------------------------
# Saatavuus kentalle (rate-team pool)
# ---------------------------------------------------------------------------

def test_rate_team_pool_kantaa_saatavuuden():
    """🔴 MITATTU 15.8. Lisasin `chance_next`/`news` vain VASTAUSRIVIIN ja
    tuotannossa arvo oli None, koska `_projection_pool` muotoilee rivin
    uusiksi: kentta joka ei ole sen listassa katoaa aanettomasti. Tiedostossa
    on 5.8 kirjoitettu kommentti joka varoittaa tasan tasta ansasta, ja kavelin
    siihen silti.

    Testi kulkee POOLIN lapi eika vastausrivin, koska se on se kohta joka
    pudottaa kentat."""
    import sys
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from src.models.fpl_rate_team import _projection_pool
    xp = {"players": [{
        "id": 1, "web_name": "Testi", "team_short": "ARS", "pos": "DEF",
        "xp_per_gw": 1.0, "xp_horizon_total": 6.0,
        "chance_next": 75, "news": "Knock - 75% chance of playing",
    }]}
    price = {1: {"element_type": 2, "team": 1, "now_cost": 50,
                 "selected_by_percent": "1.0"}}
    pool = _projection_pool(xp, price)
    assert len(pool) == 1
    assert pool[0]["chance_next"] == 75, "chance_next katosi poolissa"
    assert pool[0]["news"].startswith("Knock"), "news katosi poolissa"


# ---------------------------------------------------------------------------
# Jakaminen
# ---------------------------------------------------------------------------
# Villen pyynto 15.8: "noihin artikkeleihin myos jakokortit mukaan tai
# jakomahdollisuudet".

def test_artikkelisivuilla_on_jakorivi():
    for nimi in ("notes.html", "club/bournemouth.html", "club/arsenal.html"):
        f = FPL / nimi
        if not f.exists():  # pragma: no cover
            continue
        h = f.read_text(encoding="utf-8")
        assert 'class="share"' in h, f"{nimi}: jakorivi puuttuu"
        assert "twitter.com/intent" in h and "bsky.app/intent" in h, (
            f"{nimi}: jakolinkit puuttuvat")


def test_jaon_esitaytto_on_VAIN_otsikko_ja_linkki():
    """🔴 TIETOINEN RAJAUS. Jaettu teksti on julkista tekstia. Jos esitaytto
    sisaltaisi VAITTEEN (luvun, vertailun), se pitaisi ajaa
    julkaisutarkistajan lapi joka kerta kun sivu regeneroituu — ja sivut
    regeneroituvat paivittain. Otsikko on jo portitettu sivun mukana.

    Testi kaatuu jos joku lisaa lukuja esitayttoon."""
    import re
    import urllib.parse
    f = FPL / "club" / "bournemouth.html"
    if not f.exists():  # pragma: no cover
        pytest.skip("sivua ei ole")
    h = f.read_text(encoding="utf-8")
    rivi = re.search(r'<div class="share">.*?</div>', h, re.S).group(0)
    href = re.search(r'href="(https://twitter[^"]+)"', rivi).group(1)
    teksti = urllib.parse.unquote(href.split("text=", 1)[1])
    otsikko, _, loppu = teksti.partition("\n\n")
    assert loppu.strip().startswith("https://goaliq.app/"), (
        "esitaytossa on muuta kuin otsikko ja URL")
    assert "xP" not in loppu and "%" not in loppu, (
        "esitaytto sisaltaa lukuja -> se olisi portitettava joka regeneroinnilla")
