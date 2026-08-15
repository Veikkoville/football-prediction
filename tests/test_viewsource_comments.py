# VIEWSOURCE-FI-portti (12.8.2026): julkisten sivujen View Source on osa
# julkista pintaa. Suomenkielinen kommentti tai em dash kommentissa on sama
# uskottavuusvuoto kuin AI-tunnusmerkki copyssa (Villen tilaus 11.8).
#
# MIKSI LAHTEET EIKA VAIN SIVUT: sivut regeneroidaan, joten likainen
# generaattori palauttaa suomen hiljaa seuraavassa ajossa. Siksi portti
# mittaa seka generaattorien emitoimat kommentit etta otoksen sivuista.
#
# MIKSI OTOS EIKA KAIKKI 1953 SIVUA: ottelusivut ovat yhdesta templatesta,
# joten yksi sivu per liiga riittaa; koko pinnan skannaus kesti mitattuna
# sekunteja mutta ei loyda mitaan mita otos ei loyda.
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# Sanalista on tarkoituksella suppea ja sanarajattu: "ja"/"ei" osuvat myos
# englantiin ("ei" ei kylla, mutta "on" osuisi) - siksi mukana vain sanoja
# jotka eivat esiinny englannissa eivatka koodissa.
FINNISH = re.compile(
    r"\b(eli|joten|jotta|ilman|koska|mutta|vaatii|siksi|muuten|nakyy|"
    r"korjattu|lisatty|poistettu|kaytetaan|naytetaan|tama|tassa|nama|"
    r"seka|myos|evasteita|kavijoita|sivulla|taulukko|sarake|kentta|"
    r"tämä|myös|tässä|nämä|näkyy|kenttä|käytetään|näytetään|"
    # 12.8 ilta: live-etusivulta loytyi suomenkielinen CSS-kommentti jota
    # tama lista ei nahnyt ("Ottelunimi oli nowrap ... yhdella rivilla").
    # Lisatyt sanat ovat ASCII-suomea joka ei esiinny englannissa.
    r"yhdella|rivilla|puhelimessa|luettavan|ottelunimi|luettavuus|"
    r"kosketuskohteet|oli|"
    # 15.8: julkaisutarkistaja loysi livesta KUUSI suomenkielista
    # JS-kommenttia joita tama lista EI nahnyt, vaikka se on juuri niita
    # varten. Syy oli TAIVUTUS: listassa oli `ruudun` muttei `ruudusta`,
    # eika lainkaan `eivat` tai `vaittaisi`. Tarkka sanamuoto vanhenee
    # jokaisen uuden lauseen mukana (kirjattu: portin sanalista vanhenee).
    # Siksi nama ovat VARTALOITA: yksi uusi kirjoitusasu ei enaa riita
    # ohittamaan porttia.
    r"eiv[aä]t|eik[aä]|ett[aä]|silt[aä]|siit[aä]|t[aä]st[aä]|niiden|"
    r"jotka|jonka|joka|sit[aä]|niit[aä]|vain|kun|jos|"
    r"ruud\w*|v[aä]itt\w*|n[aä]ytt\w*|valehtel\w*|erkaant\w*|"
    r"kausisumm\w*|muistist\w*|suodatti\w*|k[aä]ytt?[aä]\w*)\b",
    re.I,
)

GENERATORS = [
    "scripts/mobile_css.py",
    "scripts/build_fpl_page.py",
    "scripts/build_fpl_longtail.py",
    "scripts/build_prediction_pages.py",
    "scripts/share_card_js.py",
]

SAMPLE_PAGES = [
    "index.html", "fpl.html", "predictions.html", "faq.html", "spl.html",
    "career.html", "creators.html", "privacy.html", "reset-password.html",
    "fpl/stats.html", "fpl/xg-leaders.html", "fpl/expected-points.html",
    "predictions/premier-league", "predictions/la-liga",
    # pro.goaliq.app:n shell servataan lahes sellaisenaan JOKAISELLA
    # SPA-sivulla -> sen kommentit ovat julkista view-sourcea siina missa
    # juurisivujenkin. Siivottu kasin 11.8; ilman porttia ajautuu takaisin.
    "web/pro-spa/src/app.html",
]


def _comment_bodies(html: str):
    """HTML-, CSS- ja JS-kommenttien sisallot. Rivikommentit (//) mukana,
    URL:ien '//' rajattu pois negaatiolla."""
    for m in re.finditer(r"<!--(.*?)-->", html, re.S):
        yield m.group(1)
    for m in re.finditer(r"<(script|style)\b[^>]*>(.*?)</\1>", html, re.S | re.I):
        inner = m.group(2)
        for c in re.finditer(r"/\*(.*?)\*/", inner, re.S):
            yield c.group(1)
        for c in re.finditer(r"(?m)(?<![:\w/])//(.*)$", inner):
            yield c.group(1)


def _emitted_comments(py_source: str):
    """Generaattorin EMITOIMAT kommentit = /* */, <!-- --> ja //-rivit
    merkkijonoliteraaleissa. Pythonin omat #-kommentit eivat emitoidu
    eivatka kuulu porttiin - ne pudotetaan ENNEN /* */-skannia, koska
    glob-polku #-rivilla ("football-prediction/* -URLit") avaisi muuten
    valekommentin joka nielaisee koodia (loytyi taman portin 1. ajossa)."""
    no_hash = "\n".join(
        line for line in py_source.splitlines()
        if not line.strip().startswith("#")
    )
    for m in re.finditer(r"/\*(.*?)\*/", no_hash, re.S):
        yield m.group(1)
    for m in re.finditer(r"<!--(.*?)-->", no_hash, re.S):
        yield m.group(1)
    for line in no_hash.splitlines():
        m = re.search(r"(?<![:\w/])//(.*)$", line)
        if m:
            yield m.group(1)


def _violations(bodies):
    out = []
    for b in bodies:
        snippet = " ".join(b.split())[:90]
        if FINNISH.search(b):
            out.append(f"suomi: {snippet}")
        if "—" in b:
            out.append(f"em dash: {snippet}")
    return out


@pytest.mark.parametrize("rel", GENERATORS)
def test_generator_emits_no_finnish_comments(rel):
    src = (ROOT / rel).read_text(encoding="utf-8")
    bad = _violations(_emitted_comments(src))
    assert not bad, f"{rel} emitoi kiellettyja kommentteja:\n" + "\n".join(bad)


def test_public_pages_have_no_finnish_comments():
    pages = []
    for rel in SAMPLE_PAGES:
        p = ROOT / rel
        if p.is_dir():
            found = sorted(p.glob("*.html"))
            assert found, f"otos tyhja: {rel}"
            pages.append(found[0])
        elif p.exists():
            pages.append(p)
    assert len(pages) >= 10, "otos kutistui - tarkista SAMPLE_PAGES"
    bad = []
    for p in pages:
        html = p.read_text(encoding="utf-8", errors="replace")
        bad += [f"{p.relative_to(ROOT)}: {v}" for v in _violations(_comment_bodies(html))]
    assert not bad, "julkisilla sivuilla kiellettyja kommentteja:\n" + "\n".join(bad)


def test_negative_control_detector_sees_planted_finnish():
    """Portti joka ei laukea istutetusta rikkeesta on pelkka vihrea valo
    (muisti: gate-substring-osuma-on-sokea)."""
    planted_html = "<html><style>/* tama sarake korjattu eilen */</style></html>"
    assert _violations(_comment_bodies(planted_html)), "HTML-detektori on sokea"
    planted_py = 'CSS = """ /* taulukko nakyy vaarin */ """'
    assert _violations(_emitted_comments(planted_py)), "generaattoridetektori on sokea"
    planted_em = "<html><!-- results — graded nightly --></html>"
    assert _violations(_comment_bodies(planted_em)), "em dash -detektori on sokea"
