"""Portti: natiivin pudotusvalikon on oltava luettava.

🔴 MITATTU VIKA (14.8.2026, Villen havainto). SPL-sivun "Compare two players"
-valikko avautui valkoisena, eika tekstia nakynyt lainkaan. Syy oli kaksi
sanaa CSS:ssa:

    .cmp-row select { background: none; color: inherit; }

SULJETTUNA kontrolli nayttaa oikealta, koska tumma sivu kuultaa lapi. Mutta
natiivi popup EI peri sivun taustaa: selain maalaa sen valkoiseksi, ja
`--text` (#F3F2F2) valkoisella pohjalla on nakymaton. Vika on siis nakyva
vasta klikkauksen jalkeen, mika on tasan se tila jota kukaan ei testaa.

`theme.css` asettaa oikeat arvot globaalisti (`input, select { background:
var(--surface); color: var(--text) }`), ja jokainen muu komponentti toistaa
ne eksplisiittisesti. Tama sivu oli ainoa joka kumosi ne.

`none` ja `inherit` eivat tarkoita "peri teema" vaan "anna selaimen paattaa".
Siksi portti kieltaa ne nimenomaan selectilta.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

SPA = Path(__file__).resolve().parents[1] / "web" / "pro-spa" / "src"

# Sallitut arvot selectin taustalle ja varille: teematokeni tai konkreettinen
# vari. Kielletyt ovat ne jotka luovuttavat paatoksen selaimelle.
_BANNED = ("none", "transparent", "inherit", "initial", "unset", "revert")


def _svelte_files() -> list[Path]:
    if not SPA.exists():  # pragma: no cover
        pytest.skip("SPA-lahdetta ei ole talla koneella")
    return sorted(SPA.rglob("*.svelte"))


def _select_rules(text: str) -> list[tuple[str, str]]:
    """(valitsin, saannon runko) jokaiselle selectia koskevalle saannolle.

    KOMMENTIT RIISUTAAN ENSIN. Ilman sita portti kaatui omaan
    dokumentaatioonsa: korjauksen viereen kirjoitettu selitys sisaltaa sanat
    `background: none` esimerkkina siita mita EI saa tehda, ja skanneri luki
    sen saannoksi. Sama ansa koskee jokaista lahdekoodia lukevaa porttia.
    """
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    out = []
    for m in re.finditer(r"([^{}]*\bselect\b[^{}]*)\{([^{}]*)\}", text):
        sel = m.group(1).strip().splitlines()[-1].strip()
        if sel.startswith(("@", "/*")) or "<" in sel:
            continue
        out.append((sel, m.group(2)))
    return out


def test_no_select_hands_its_colours_to_the_browser():
    """Yksikaan select ei saa asettaa background/color-arvoa joka luovuttaa
    paatoksen selaimelle. Popup ei peri sivun teemaa."""
    offenders = []
    for f in _svelte_files():
        text = f.read_text(encoding="utf-8")
        for sel, body in _select_rules(text):
            for prop in ("background", "background-color", "color"):
                m = re.search(rf"(?<![-\w]){prop}\s*:\s*([^;]+);", body)
                if not m:
                    continue
                val = m.group(1).strip().lower()
                if val in _BANNED:
                    offenders.append(
                        f"{f.relative_to(SPA)} :: {sel} :: {prop}: {val}")
    assert not offenders, (
        "select luovuttaa varinsa selaimelle -> natiivi popup voi olla "
        "lukukelvoton:\n  " + "\n  ".join(offenders))


def test_the_spl_compare_select_sets_both_colours_explicitly():
    """POSITIIVINEN KONTROLLI juuri sille valikolle joka rikkoutui. Ilman
    tata edellinen testi menisi lapi myos jos joku poistaisi saannon
    kokonaan — silloin globaali saanto kantaisi, mutta seuraava muokkaaja ei
    nakisi mitaan syyta olla kirjoittamatta `none`:a takaisin."""
    p = SPA / "routes" / "spl" / "+page.svelte"
    if not p.exists():  # pragma: no cover
        pytest.skip("SPL-sivua ei loydy")
    body = next((b for sel, b in _select_rules(p.read_text(encoding="utf-8"))
                 if "cmp-row" in sel), None)
    assert body is not None, ".cmp-row select -saanto puuttuu"
    assert "var(--surface)" in body
    assert "var(--text)" in body


def test_the_global_rule_still_sets_them():
    """Jos globaali saanto katoaa, jokainen select jaa selaimen armoille
    riippumatta komponenttikohtaisista saannoista."""
    css = (SPA / "lib" / "theme.css").read_text(encoding="utf-8")
    m = re.search(r"input,\s*\n?select\s*\{([^{}]*)\}", css)
    assert m, "globaali input/select-saanto puuttuu theme.css:sta"
    assert "var(--surface)" in m.group(1) and "var(--text)" in m.group(1)
