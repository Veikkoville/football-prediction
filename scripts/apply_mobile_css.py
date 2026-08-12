# -*- coding: utf-8 -*-
"""Liittaa jaetun mobiili-CSS:n kasin yllapidettyihin sivuihin.

MIKSI TAMA ON OLEMASSA: goaliq.app:n sivuista kolme perhetta generoidaan
buildereilla (ne saavat lohkon suoraan scripts/mobile_css.py:sta), mutta
juurisivut -- index.html, predictions.html, faq.html, career.html, spl.html,
privacy.html, MM-sivut ja tilinhallintasivut -- yllapidetaan kasin. Ilman
tata skriptia ne jaisivat rikki puhelimessa vaikka generoidut sivut
korjattiin, ja ero huomattaisiin vasta kayttajalta.

AJO (idempotentti, voi ajaa niin monta kertaa kuin haluaa):
    python scripts/apply_mobile_css.py            # kirjoittaa
    python scripts/apply_mobile_css.py --check    # ei kirjoita, palauttaa 1
                                                  # jos jokin sivu on jaljessa

--check on tarkoitettu portiksi: se kaatuu jos joku lisaa uuden juurisivun
eika aja tata, eli lohko ei paase hiljaa vanhentumaan yhdella sivulla.

SIJOITUS: lohko menee AINA viimeisen </style>:n eteen. Se on tahallista --
saannot voittavat aiemmat samalla spesifisyydella vain jarjestyksen
perusteella, ja jos lohko olisi sivun ensimmaisessa <style>-elementissa,
myohemmin injektoidut tyylit (esim. BYCOMP_CSS) kumoaisivat sen.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.mobile_css import (  # noqa: E402
    BEGIN_MARKER,
    COLS_JS_BEGIN,
    COLS_JS_END,
    END_MARKER,
    MOBILE_COLS_JS,
    MOBILE_CSS,
)

ROOT = Path(__file__).resolve().parents[1]

# Taysin generoidut sivut: ne saavat lohkon suoraan builderista. Jos ne
# olisivat myos taalla, kaksi lahdetta kilpailisi samasta lohkosta.
FULLY_GENERATED = {"fpl.html"}


def hand_written_pages() -> list[Path]:
    """Juuritason sivut jotka tarvitsevat lohkon.

    Lista on tahallaan JOHDETTU eika kasin kirjoitettu: kasin kirjoitettu
    lista vanhenee hiljaa heti kun joku lisaa uuden juurisivun, ja juuri
    sellainen hiljainen aukko on tama koko tehtava. Sivut joilla ei ole omaa
    <style>-elementtia (esim. MM-kisojen redirect-tyngat) putoavat pois
    itsestaan -- niissa ei ole mitaan tyyliteltavaa.
    """
    out = []
    for p in sorted(ROOT.glob("*.html")):
        if p.name in FULLY_GENERATED or p.name.startswith("_"):
            continue  # _-alkuiset ovat paikallisia tyokaluja, eivat sivuja
        if "</style>" not in p.read_text(encoding="utf-8"):
            continue
        out.append(p)
    return out


def _strip_block(html: str, begin: str, end: str) -> str:
    """Poistaa markkeroidun lohkon (myos jos se on vaarassa paikassa)."""
    while begin in html and end in html:
        a = html.index(begin)
        b = html.index(end, a) + len(end)
        if html[b:b + 1] == "\n":
            b += 1
        html = html[:a] + html[b:]
    return html


def _apply_cols_js(html: str) -> str:
    """Liittaa "Show all columns" -kytkimen </body>:n eteen.

    Kytkin on osa samaa sopimusta kuin CSS-lohko: piilotettu sarake ei saa
    olla saavuttamaton. Jos sivulla ei ole </body>:ta, palautetaan
    muuttamattomana -- kutsuja raportoi sen.
    """
    html = _strip_block(html, COLS_JS_BEGIN, COLS_JS_END)
    if "</body>" not in html:
        return html
    cut = html.rindex("</body>")
    return html[:cut] + MOBILE_COLS_JS + html[cut:]


def _strip_existing(html: str) -> str:
    """Poistaa aiemman lohkon kokonaan (myos jos se on vaarassa paikassa).

    MOBILE_CSS paattyy rivinvaihtoon END_MARKERin jalkeen. Jos sita ei syoda
    tassa, jokainen ajo jattaa yhden ylimaaraisen rivinvaihdon -> tiedosto
    muuttuu joka kerta, --check on ikuisesti punainen ja diff kohisee.
    Loydettiin ajamalla skripti kahdesti perakkain (9.8).
    """
    while BEGIN_MARKER in html and END_MARKER in html:
        a = html.index(BEGIN_MARKER)
        b = html.index(END_MARKER, a) + len(END_MARKER)
        if html[b:b + 1] == "\n":
            b += 1
        html = html[:a] + html[b:]
    return html


def _insert_cut(html: str) -> int:
    """Kohta jonka eteen lohko liitetaan: viimeinen </style> jonka RIVILLA
    ei ole GEN:-markkeria. Palauttaa -1 jos sellaista ei ole.

    Pelkka rindex("</style>") osui index.html:ssa ja predictions.html:ssa
    sivun keskella olevaan generoituun yksiriviseen <style>-lohkoon
    (GEN:ACC-BYCOMP / GEN:ACC-RECORD). Lohko olisi mennyt generoidun alueen
    SISAAN: seuraava bake pyyhkii sen, ja uusi ajo lisaa uudestaan -- tasta
    syntyi 11.-12.8 kahdesti peruutettu tuplausdiff. Rivitarkistus riittaa,
    koska generoidut inline-lohkot ovat yksirivisia ja markkerit ovat
    samalla rivilla kuin niiden </style>.
    """
    cuts = []
    start = 0
    while True:
        i = html.find("</style>", start)
        if i == -1:
            break
        ls = html.rfind("\n", 0, i) + 1
        le = html.find("\n", i)
        line = html[ls:le if le != -1 else len(html)]
        if "GEN:" not in line:
            cuts.append(i)
        start = i + 1
    return cuts[-1] if cuts else -1


def apply_to(path: Path) -> str:
    """Palauttaa 'updated' | 'ok' | 'skipped:<syy>'."""
    if not path.exists():
        return "skipped:puuttuu"
    original = path.read_text(encoding="utf-8")
    if "</style>" not in original:
        # Sivulla ei ole omaa tyylielementtia -> ei paikkaa mihin liittaa.
        # Tama on raportoitava eika vaiettava: sivu jaa korjaamatta.
        return "skipped:ei <style>-elementtia"

    stripped = _strip_existing(original)
    cut = _insert_cut(stripped)
    if cut == -1:
        # Kaikki </style>-elementit ovat generoiduilla riveilla -> ei
        # turvallista liitoskohtaa. Raportoitava, ei vaiettava.
        return "skipped:vain generoituja <style>-elementteja"
    new = stripped[:cut] + MOBILE_CSS + stripped[cut:]
    new = _apply_cols_js(new)
    if new == original:
        return "ok"
    path.write_text(new, encoding="utf-8")
    return "updated"


def check(path: Path) -> bool:
    """True jos sivu on ajan tasalla."""
    if not path.exists():
        return True
    original = path.read_text(encoding="utf-8")
    if "</style>" not in original:
        return False
    stripped = _strip_existing(original)
    cut = _insert_cut(stripped)
    if cut == -1:
        return False
    built = stripped[:cut] + MOBILE_CSS + stripped[cut:]
    return _apply_cols_js(built) == original


def main() -> int:
    check_only = "--check" in sys.argv
    pages = hand_written_pages()
    stale, notes = [], []
    for p in pages:
        if check_only:
            if not check(p):
                stale.append(p.name)
            continue
        r = apply_to(p)
        if r != "ok":
            notes.append(f"  {p.name}: {r}")

    if check_only:
        if stale:
            print("MOBILE-CSS jaljessa seuraavilla sivuilla:")
            for s in stale:
                print(f"  {s}")
            print("Korjaa: python scripts/apply_mobile_css.py")
            return 1
        print(f"MOBILE-CSS ajan tasalla ({len(pages)} kasin sivua).")
        return 0

    print(f"MOBILE-CSS liitetty ({len(pages)} kasin yllapidettya sivua).")
    for n in notes:
        print(n)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
