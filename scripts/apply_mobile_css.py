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

from scripts.mobile_css import BEGIN_MARKER, END_MARKER, MOBILE_CSS  # noqa: E402

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
    cut = stripped.rindex("</style>")
    new = stripped[:cut] + MOBILE_CSS + stripped[cut:]
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
    cut = stripped.rindex("</style>")
    return (stripped[:cut] + MOBILE_CSS + stripped[cut:]) == original


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
