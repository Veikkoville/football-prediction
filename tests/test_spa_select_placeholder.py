"""Portti: select ei saa renderoitya tyhjana.

MITATTU VIKA (15.8.2026, tuotannosta selaimella). SPL-sivun "Compare two
players" -valikot olivat SULJETTUNA taysin tyhjia: ei placeholderia, ei
mitaan. Vika loytyi kun verifioin edellisen korjauksen (popupin luettavuus)
selaimesta — `select.selectedIndex` oli **-1** molemmissa.

Syy: markup sitoi selectin arvoksi `number | null` -tilan:

    let cmpA = $state<number | null>(null);
    <select value={cmpA}>
        <option value="">Pick player 1…</option>

`null` ei vastaa yhtaan optionia — placeholderin arvo on tyhja MERKKIJONO —
joten selain ei valitse mitaan ja piirtaa tyhjan laatikon. Korjaus on
`?? ''`, joka kaantaa nullin placeholderin arvoksi.

Tama on eri vika kuin `test_spa_select_contrast.py`:n: se koskee AVATTUA
valikkoa, tama SULJETTUA. Molemmat ovat nakymattomia lahdekoodia lukemalla ja
molemmat vaativat sen tilan katsomista jota kukaan ei testaa.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

SPA = Path(__file__).resolve().parents[1] / "web" / "pro-spa" / "src"


def _svelte_files() -> list[Path]:
    if not SPA.exists():  # pragma: no cover
        pytest.skip("SPA-lahdetta ei ole talla koneella")
    return sorted(SPA.rglob("*.svelte"))


def _nullable_state_names(text: str) -> set[str]:
    """Tilamuuttujat joiden tyyppi sallii nullin/undefinedin."""
    out = set()
    for m in re.finditer(r"let\s+(\w+)\s*=\s*\$state<([^>]*)>\(", text):
        if re.search(r"\b(null|undefined)\b", m.group(2)):
            out.add(m.group(1))
    return out


def _select_tags(text: str) -> list[str]:
    """Jokaisen <select ...>-avaustagin attribuuttiosa.

    EI regexilla `<select[^>]*>`: attribuuteissa on nuolifunktioita
    (`onchange={(e) => ...}`) joissa on `>`, ja naiivi skanneri katkaisisi
    tagin kesken ja lukisi vaaran value-lausekkeen. Sulut lasketaan.
    """
    out = []
    for m in re.finditer(r"<select\b", text):
        i, depth = m.end(), 0
        while i < len(text):
            c = text[i]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
            elif c == ">" and depth == 0:
                break
            i += 1
        out.append(text[m.end():i])
    return out


def _value_expr(tag: str) -> str | None:
    """`value={...}`-lausekkeen sisalto sulkuja laskien. `bind:value` ei kelpaa
    tahan porttiin: Svelte hoitaa sidonnan itse eika placeholder katoa."""
    m = re.search(r"(?<![:\w-])value=\{", tag)
    if not m:
        return None
    i, depth = m.end(), 1
    while i < len(tag) and depth:
        if tag[i] == "{":
            depth += 1
        elif tag[i] == "}":
            depth -= 1
        i += 1
    return tag[m.end():i - 1]


def test_no_select_can_render_blank():
    """Jos selectin arvo voi olla null, lausekkeessa on oltava `??`.

    Muuten `selectedIndex` menee -1:een ja kayttaja nakee tyhjan laatikon —
    ei virhetta, ei placeholderia, ei vihjetta siita mita kontrolli tekee.
    """
    offenders = []
    for f in _svelte_files():
        text = f.read_text(encoding="utf-8")
        nullable = _nullable_state_names(text)
        if not nullable:
            continue
        for tag in _select_tags(text):
            expr = _value_expr(tag)
            if expr is None or "??" in expr:
                continue
            hit = sorted(n for n in nullable
                         if re.search(rf"\b{re.escape(n)}\b", expr))
            if hit:
                offenders.append(
                    f"{f.relative_to(SPA)} :: value={{{expr.strip()}}} "
                    f":: nullable: {', '.join(hit)}")
    assert not offenders, (
        "select saa arvokseen nullin -> selectedIndex = -1 -> kontrolli "
        "renderoituu tyhjana. Lisaa `?? ''` (placeholderin arvo):\n  "
        + "\n  ".join(offenders))


def test_the_spl_compare_selects_fall_back_to_the_placeholder():
    """POSITIIVINEN KONTROLLI juuri sille kontrollille joka oli tyhja.

    Ilman tata edellinen testi menisi lapi myos jos joku vaihtaisi tilan
    tyypin `number`:ksi ja alustaisi sen nollalla — silloin skanneri ei enaa
    tunnistaisi muuttujaa nullableksi eika mikaan huutaisi, vaikka tyhja
    laatikko palaisi.
    """
    p = SPA / "routes" / "spl" / "+page.svelte"
    if not p.exists():  # pragma: no cover
        pytest.skip("SPL-sivua ei loydy")
    text = p.read_text(encoding="utf-8")
    exprs = [e for e in (_value_expr(t) for t in _select_tags(text))
             if e is not None and ("cmpA" in e or "cmpB" in e)]
    assert exprs, "compare-selectin value-lauseketta ei loydy"
    for e in exprs:
        assert "??" in e, f"compare-select voi saada nullin: value={{{e}}}"
    assert '<option value="">Pick player' in text, (
        "placeholder-option puuttuu — `?? ''` osoittaisi olemattomaan arvoon")
