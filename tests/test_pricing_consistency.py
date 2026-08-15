"""Portti: julkinen sivu ei saa luvata alennushintaa jota ei voi lunastaa.

MITATTU VIKA (15.8.2026, Villen havainto). EARLY30 poistettiin kaikilta
pinnoilta ja verifioin sen livesta: 6/6 puhdas. Mutta verifiointini etsi
merkkijonoa `EARLY30`, ei HINTAA. Etusivu ja predictions.html jaivat
myymaan "17.50 first year, then 25" ilman etta koodia enaa mainittiin
missaan, eli lupasivat alennuksen jota kukaan ei voinut lunastaa.

Vaite oli vaara mutta portti mittasi vaaraa asiaa. Sama luokka kuin
aiemmin kirjattu "portti voi mitata eri koodipolkua".

INVARIANTTI jota tama vartioi: alennuslupaus ("first year", "% off")
saa esiintya VAIN sivulla joka nimeaa lunastettavan koodin. creators.html
on ainoa sallittu, ja siella 17.50 on luoja-koodin (DAZ/WOLFY/ROWAN,
kaikki aktiivisia) todellinen hinta eika kampanja.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# Julkiset myyntipinnat, kasin yllapidetyt.
MYYNTIPINNAT = ["index.html", "predictions.html", "fpl.html", "faq.html"]


def _generoidut() -> list[str]:
    """Generoidut sivut mukaan skannaukseen.

    🔴 TAMA PUUTTUI ENSIMMAISESTA VERSIOSTA JA SE OLI SE AUKKO. Portti
    rakennettiin 15.8 estamaan lunastamaton alennuslupaus, mutta se skannasi
    vain kasin yllapidetyt sivut. Samana paivana julkaisutarkistaja loysi
    livesta rikkinaisen orpolauseen JOKAISEN longtail- ja ennustesivun
    footerista:

        "... 25 €/season. deadline on Friday 21 August for 30% off the
         first year (17.50 €, then 25 €)."

    Sama vaara hintalupaus, kymmenilla sivuilla, ja oma porttini oli sokea
    silla juuri se lahde on generaattorissa eika HTML:ssa. Portti joka
    kattaa vain sen pinnan jolta vika loytyi ensin ei ole portti vaan
    korjauksen muistiinpano.
    """
    ulos = []
    for kuvio in ("fpl/*.html", "fpl/club/*.html", "predictions/*/index.html"):
        ulos += [str(x.relative_to(ROOT)).replace("\\", "/")
                 for x in sorted(ROOT.glob(kuvio))]
    return ulos

# Sivu jolla alennushinta on TOSI: luoja-koodit ovat aktiivisia Stripessa
# (verifioitu 15.8: DAZ, WOLFY, ROWAN active=true) ja sivu nimeaa ne.
SALLITTU_ALENNUSSIVU = "creators.html"

# Alennuslupauksen merkit MEIDAN OMASTA hinnastamme.
ALENNUSSIGNAALIT = [
    re.compile(r"first year", re.I),
    re.compile(r"\d+\s*(?:%|percent)\s*off", re.I),
    re.compile(r"17[.,]50"),
]

# 🔴 KONTEKSTIPOIKKEUS, LISATTY HETI ENSIMMAISEN AJON JALKEEN. Portti loi
# ensin index.html:n ja fpl.html:n, mutta molemmat osumat olivat LUOJA-
# OHJELMAN kuvausta ("your code takes 30 percent off your audience's first
# payment"). Se on tosi ja lunastettavissa: DAZ, WOLFY ja ROWAN ovat
# Stripessa aktiivisia.
#
# Portti joka huutaa todesta vaitteesta opitaan ohittamaan, ja silloin se ei
# estä sita vaaraa jota varten se rakennettiin. Invariantti on siis
# tarkemmin: alennuslupaus MEIDAN hinnastamme. Luojan koodin kuvaus on eri
# vaite ja se saa jaada.
LUOJAKONTEKSTI = re.compile(r"creator|your code|audience", re.I)
KONTEKSTI_MERKKIA = 220

KANONINEN_VUOSI = re.compile(r"(?:&euro;|€)\s*25\b")


def _teksti(nimi: str) -> str:
    p = ROOT / nimi
    if not p.exists():
        pytest.skip(f"{nimi} puuttuu")
    return p.read_text(encoding="utf-8", errors="replace")


def _alennusosumat(t: str) -> list[str]:
    osumat = []
    for r in ALENNUSSIGNAALIT:
        for m in r.finditer(t):
            ymparys = t[max(0, m.start() - KONTEKSTI_MERKKIA):
                        m.end() + KONTEKSTI_MERKKIA]
            if LUOJAKONTEKSTI.search(ymparys):
                continue
            osumat.append(f"{r.pattern} @ {m.group(0)!r}")
    return osumat


def test_generoidut_sivut_eivat_lupaa_lunastamatonta_alennusta():
    """Kaikki generoidut sivut kerralla: vika oli identtinen kymmenilla."""
    rikki = {}
    for nimi in _generoidut():
        osumat = _alennusosumat((ROOT / nimi).read_text(encoding="utf-8",
                                                        errors="replace"))
        if osumat:
            rikki[nimi] = osumat
    assert not rikki, (
        f"{len(rikki)} generoitua sivua lupaa lunastamattoman alennuksen. "
        f"Korjaa GENERAATTORI, ei tulostetta. Esimerkki: "
        f"{list(rikki.items())[:2]}"
    )


def test_generoituja_sivuja_loytyy():
    """NEGATIIVINEN KONTROLLI: tyhja lista tekisi ylemmasta testista
    ikuisesti vihrean eika se mittaisi mitaan."""
    assert len(_generoidut()) >= 20, (
        f"vain {len(_generoidut())} generoitua sivua loytyi; kuvio on rikki"
    )


@pytest.mark.parametrize("nimi", MYYNTIPINNAT)
def test_myyntipinta_ei_lupaa_lunastamatonta_alennusta(nimi):
    t = _teksti(nimi)
    osumat = []
    for r in ALENNUSSIGNAALIT:
        for m in r.finditer(t):
            ymparys = t[max(0, m.start() - KONTEKSTI_MERKKIA):
                        m.end() + KONTEKSTI_MERKKIA]
            if LUOJAKONTEKSTI.search(ymparys):
                continue
            osumat.append(f"{r.pattern} @ {m.group(0)!r}")
    assert not osumat, (
        f"{nimi} lupaa alennuksen ilman lunastettavaa koodia: {osumat}. "
        "Joko poista lupaus tai nimea koodi joka on Stripessa aktiivinen."
    )


@pytest.mark.parametrize("nimi", ["index.html", "predictions.html"])
def test_kanoninen_vuosihinta_nakyy(nimi):
    """NEGATIIVINEN KONTROLLI ylemmalle testille.

    Pelkka "ei alennuslupausta" menisi lapi myos sivulla jolta hinta on
    kokonaan kadonnut. Hinnan PITAA olla nakyvissa, ja sen pitaa olla 25.
    """
    assert KANONINEN_VUOSI.search(_teksti(nimi)), (
        f"{nimi}: kanonista vuosihintaa (25) ei loydy lainkaan"
    )


def test_creators_saa_yha_kertoa_luojahinnan():
    """NEGATIIVINEN KONTROLLI: portti ei saa olla niin leveä etta se
    poistaisi toden tiedon. Luoja-koodit ovat aktiivisia, joten 17.50 on
    creators.html:lla oikea luku eika jaanne."""
    t = _teksti(SALLITTU_ALENNUSSIVU)
    assert "17.50" in t
    assert re.search(r"\b(DAZ|WOLFY|ROWAN)\b", t) or "code with your name" in t.lower()


def test_havaitsee_paluun():
    """NEGATIIVINEN KONTROLLI itse tunnistimelle: jos ALENNUSSIGNAALIT ei
    osuisi mihinkaan, ylempi testi olisi vihrea ikuisesti eika mittaisi
    mitaan. Tama varmistaa etta kuvio osuu juuri siihen tekstiin joka
    15.8 oli livena."""
    livena_ollut = (
        '<h3><span class="price-tag">&euro;17.50<span> first year</span></span> '
        '<span class="price-alt">then &euro;25 / year</span></h3>'
    )
    assert any(r.search(livena_ollut) for r in ALENNUSSIGNAALIT)


def test_luojakonteksti_ei_vaimenna_meidan_hintalappuamme():
    """NEGATIIVINEN KONTROLLI kontekstipoikkeukselle, tarkein tassa
    tiedostossa. Poikkeus saa vaimentaa VAIN luojan koodin kuvauksen. Jos se
    vaimentaisi hintalapun aina kun samalla sivulla puhutaan luojista, koko
    portti olisi hampaaton juuri index.html:lla, jolla molemmat esiintyvat.
    """
    hintalappu = (
        '<div class="panel-body"><h3><span class="price-tag">&euro;17.50'
        '<span> first year</span></span></h3></div>'
    )
    osumat = []
    for r in ALENNUSSIGNAALIT:
        for m in r.finditer(hintalappu):
            ymparys = hintalappu[max(0, m.start() - KONTEKSTI_MERKKIA):
                                 m.end() + KONTEKSTI_MERKKIA]
            if LUOJAKONTEKSTI.search(ymparys):
                continue
            osumat.append(r.pattern)
    assert osumat, "hintalappu paasi lapi: portti ei mittaa mitaan"


def test_luojakuvaus_menee_lapi():
    """Vastinpari ylemmalle: tama teksti on livena index.html:lla ja on tosi."""
    luoja = ("<h2>Make FPL content? Join the creator program</h2><p>Your code "
             "takes 30 percent off your audience's first payment at the web "
             "checkout.</p>")
    osumat = []
    for r in ALENNUSSIGNAALIT:
        for m in r.finditer(luoja):
            ymparys = luoja[max(0, m.start() - KONTEKSTI_MERKKIA):
                            m.end() + KONTEKSTI_MERKKIA]
            if LUOJAKONTEKSTI.search(ymparys):
                continue
            osumat.append(r.pattern)
    assert not osumat, f"tosi luojakuvaus blokattiin: {osumat}"


# --- Takuu (15.8, Villen paatos) ---------------------------------------

TAKUU_LYHYT = "30-day money back on web purchases."

# Pinnat joilla lyhyt lupaus on. faq.html ja llms.txt kantavat PITKAN
# muodon; ne tarkistetaan erikseen, koska lyhyt lupaus ilman rajausta olisi
# niilla epataydellinen.
TAKUUPINNAT = ["index.html", "fpl.html", "predictions.html", "faq.html"]


@pytest.mark.parametrize("nimi", TAKUUPINNAT)
def test_takuu_on_jokaisella_myyntipinnalla(nimi):
    """COPY-SYNC-GATE koodina.

    Takuu on lupaus jonka ostaja lukee yhdelta pinnalta ja lunastaa toiselta.
    Jos se on vain osalla sivuista, osa ostajista ei tieda sita olevan ja
    osa luulee sita laajemmaksi kuin se on. Sama sana kaikkialla tai ei
    missaan.
    """
    assert TAKUU_LYHYT in _teksti(nimi), (
        f"{nimi}: takuulupaus puuttuu tai on eri sanoin. "
        f"Odotettu tasmalleen: {TAKUU_LYHYT!r}"
    )


@pytest.mark.parametrize("nimi", ["faq.html", "llms.txt"])
def test_takuun_rajaus_kerrotaan_siella_missa_se_selitetaan(nimi):
    """Rajaus EI saa jaada pois: emme voi palauttaa App Storen tai Google
    Playn ostoja, koska Apple ja Google hoitavat ne. Lupaus ilman tata olisi
    lupaus jota emme voi pitaa."""
    teksti = _teksti(nimi)
    assert "30 days" in teksti or "30-day" in teksti
    assert "hello@goaliq.app" in teksti, f"{nimi}: lunastusreitti puuttuu"
    for sana in ("App Store", "Google Play"):
        assert sana in teksti, f"{nimi}: rajaus {sana!r} puuttuu"


def test_takuu_ei_lupaa_mobiiliostojen_palautusta():
    """NEGATIIVINEN KONTROLLI: portti ei saa mennä lapi tekstista joka
    lupaa palautuksen KAIKISTA ostoista. Juuri se on se lupaus jota emme
    voi pitaa, koska Apple ja Google omistavat sen paatoksen."""
    huono = "Money back within 30 days on any purchase, no questions asked."
    assert TAKUU_LYHYT not in huono
    assert "App Store" not in huono


def test_faq_kertoo_myos_web_tilauksen_peruutuksen():
    """Peruutusohje puhui vain sovelluskaupasta, vaikka pro.goaliq.app/checkout
    myy Stripen kautta. Web-ostaja ei loytanyt ohjeestaan mitaan."""
    t = _teksti("faq.html")
    # Ankkuri on NAKYVA <summary>, ei pelkka otsikkoteksti: sama otsikko
    # esiintyy myos JSON-LD-lohkossa aiemmin sivulla, ja osajonohaku osui
    # siihen. Rakenteinen data oli jo oikein, nakyva ohje ei — eli testi
    # mittasi vaaraa esiintymaa. Sama ansa kuin luvun 1.4 osuminen lukuun
    # 1.45 samana paivana.
    i = t.find("<summary>How do I cancel my Premium subscription?</summary>")
    assert i > 0, "nakyvaa peruutuslohkoa ei loydy"
    lohko = t[i:i + 2000]
    assert "web checkout" in lohko, "nakyva peruutusohje ei mainitse web-tilausta"


def test_rakenteinen_data_kertoo_saman():
    """NEGATIIVINEN KONTROLLI: nakyva teksti ja JSON-LD eivat saa erota.
    Vastausmoottori lukee jalkimmaista, ihminen edellista."""
    t = _teksti("faq.html")
    i = t.find('"name": "How do I cancel my Premium subscription?"')
    assert i > 0
    assert "hello@goaliq.app" in t[i:i + 900]
