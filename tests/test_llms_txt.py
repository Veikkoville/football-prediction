"""#231-GEO: llms.txt:n portti - se on ainoa tiedosto jonka koko tarkoitus on
syottaa AI-vastausta, ja se oli ainoa julkinen pinta jota mikaan portti ei
lukenut. Kolme perakkaista viikkoauditointia loysi siita eri staleuden
(17.7 faq, 29.7 "best legal 15" + kuolleet WC-sivut, 5.8 puuttuva 1752 sivun
laajennus + vaara xG-lupaus).

Ei verkkoa: kaikki tarkistukset ovat repon sisaisia.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLMS = ROOT / "llms.txt"
SITEMAPS = ("sitemap-core.xml", "sitemap-fpl.xml", "sitemap-predictions.xml")


def _sitemap_urls() -> set[str]:
    urls: set[str] = set()
    for name in SITEMAPS:
        p = ROOT / name
        if p.exists():
            urls |= set(re.findall(r"<loc>(.*?)</loc>",
                                   p.read_text(encoding="utf-8")))
    return urls


def _llms_urls() -> set[str]:
    txt = LLMS.read_text(encoding="utf-8")
    # <league> ja <home-team>-vs-<away-team> ovat dokumentoituja URL-malleja,
    # eivat konkreettisia osoitteita -> '<' katkaisee osuman.
    return {u.rstrip(".,;") for u in
            re.findall(r"https://goaliq\.app[^\s)\]\"<]*", txt)}


def _matches(url: str, urls: set[str]) -> bool:
    bare = url.rstrip("/")
    return bare in urls or bare + "/" in urls


def _exists_on_disk(url: str) -> bool:
    """Onko osoitetta vastaava sivu repossa?

    9.8.2026: sitemap karsittiin 30 paivan horisonttiin (1924 -> 197 URLia),
    mutta SIVUT jaivat kaikki paikoilleen. Sita ennen sitemap oli sivuston
    tayslista, ja molemmat llms-portit oli rakennettu sen varaan. Karsinnan
    jalkeen ne alkoivat raportoida puuttuvaksi sivuja jotka ovat olemassa.
    Portin pitaa kysya "onko sivu olemassa", ei "mainostetaanko sita nyt".
    """
    path = url.rstrip("/").removeprefix("https://goaliq.app").lstrip("/")
    if not path:
        return True
    for cand in (ROOT / path, ROOT / f"{path}.html", ROOT / path / "index.html"):
        if cand.exists():
            return True
    return False


def test_llms_urls_exist_on_site():
    """Jokainen llms.txt:n mainitsema osoite on oikeasti sivustolla.

    Tama olisi napannut 29.7:n loydoksen: llms.txt mainosti 12:ta WC-ryhmasivua
    sisaltona, vaikka ne olivat jo eloonjaaneita meta-refresh-tynkia eivatka
    olleet sitemapissa. Nappaa myos rikkinaiset slugit (F2-luokka).

    Lahde on sitemap TAI levylla oleva sivu: sitemapissa on tarkoituksella vain
    30 paivan ikkuna, joten pelkka sitemap-tarkistus hylkaisi olemassa olevia
    sivuja (esim. esimerkkina kaytetty ottelusivu, joka liukuu ikkunasta ulos).
    """
    urls = _sitemap_urls()
    assert urls, "sitemapit puuttuvat - tarkistus olisi tyhja ja vihrea"
    missing = sorted(u for u in _llms_urls()
                     if not _matches(u, urls) and not _exists_on_disk(u))
    assert not missing, f"llms.txt mainitsee osoitteita joita ei ole sivustolla: {missing}"


def test_llms_url_check_has_teeth():
    """Negatiivinen kontrolli: keksitty osoite EI saa lapaista tarkistusta.

    Levy-fallback loysentaa porttia, joten sen on todistettava etta se yha
    hylkaa jotain (vrt. muistiinpano substring-osumasta 5.8).
    """
    urls = _sitemap_urls()
    fake = "https://goaliq.app/predictions/serie-a/inter-vs-eiolemassa"
    assert not _matches(fake, urls) and not _exists_on_disk(fake)


def test_every_live_league_hub_is_in_llms():
    """Jokainen livena oleva liigahub nakyy llms.txt:ssa.

    Tama on F3:n suunta: 1752 eurooppalaista sivua oli livena, mutta llms.txt
    kuvasi ottelusivut yksinomaan Brasileiraon ominaisuutena. Kasvumoottori voi
    kasvaa ilman etta yksikaan olemassa oleva vaite muuttuu vaaraksi - vain
    tama tarkistus huomaa sen.
    """
    hubs = {u for u in _sitemap_urls()
            if re.fullmatch(r"https://goaliq\.app/predictions/[a-z0-9-]+/", u)}
    assert hubs, "sitemap-predictions.xml ei sisalla yhtaan liigahubia"
    txt = LLMS.read_text(encoding="utf-8")
    # Pelkka substring-osuma EI kelpaa: esimerkkiottelusivu
    # ".../serie-a/inter-vs-udinese" sisaltaa hub-URLin merkkijonona, jolloin
    # liiga voisi olla llms.txt:ssa pelkkana esimerkkina ilman omaa riviaan ja
    # portti nayttaisi silti vihreaa (todettu negatiivisella kontrollilla 5.8).
    # Hubin on esiinnyttava omana osoitteenaan eli ilman jatkopolkua.
    missing = sorted(
        h for h in hubs
        if not re.search(re.escape(h) + r"(?![A-Za-z0-9-])", txt)
    )
    assert not missing, f"livena olevat liigahubit puuttuvat llms.txt:sta: {missing}"


def test_gen_markers_present():
    """Markkerien katoaminen tekisi generoinnista hiljaisen no-opin.

    update_llms_txt palauttaa False jos markkerit puuttuvat (ei kaada ajoa,
    tarkoituksella) - eli ilman tata testia llms.txt jaisi jalkeen taysin
    aanettomasti, mika on juuri se vikaluokka jota #231 korjaa.
    """
    txt = LLMS.read_text(encoding="utf-8")
    assert "<!-- GEN:LLMS-START -->" in txt
    assert "<!-- GEN:LLMS-END -->" in txt


def test_generated_block_matches_generator_output():
    """Kasin editoitu GEN-lohko on regressio, ei korjaus."""
    from scripts.build_prediction_pages import LEAGUES, update_llms_txt

    # Varmuuskopio TAVUINA: read_text/write_text normalisoi rivinvaihdot, joten
    # palautus jatti tiedoston muuttuneeksi (CRLF -> LF) vaikka sisalto oli
    # sama. Testi ei saa likaista tyopuuta.
    backup = LLMS.read_bytes()
    txt = LLMS.read_text(encoding="utf-8")
    # Luvut LEVYLTA, ei sitemapista: llms.txt vastaa kysymykseen "montako
    # ottelusivua sivustolla on", sitemap kysymykseen "mita tarjoamme
    # indeksoitavaksi juuri nyt" (30 pv). Nama erkanivat 9.8.2026 karsinnassa,
    # ja sitemap-pohjainen laskenta olisi vaatinut llms.txt:hen VAARAN luvun
    # (197) jotta portti olisi vihrea.
    counts = {}
    for comp, cfg in LEAGUES.items():
        d = ROOT / "predictions" / cfg["slug"]
        if not d.is_dir():
            continue
        n = len([p for p in d.glob("*.html") if p.name != "index.html"])
        if n:
            counts[comp] = n
    try:
        assert update_llms_txt(counts) is False, (
            "generaattori kirjoittaisi llms.txt:n toisin kuin se on committoitu "
            "- lohko on kasin editoitu tai luvut ovat vanhentuneet"
        )
    finally:
        LLMS.write_bytes(backup)
