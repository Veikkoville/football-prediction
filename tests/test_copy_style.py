"""Em dash -portti julkisille pinnoille (11.8.2026).

MIKSI: goaliq-app-repossa on `scripts/check-copy-style.js`, joka estaa em
dashin mobiilin copysta. football-predictionissa EI ollut vastaavaa, ja 11.8
oma korjaukseni vei em dashin `Differentials.svelte`:n nakyvaan tekstiin.
Julkaisutarkistaja-agentti nappasi sen, ei portti. Tama sulkee aukon.

MITA MITATAAN: **renderoityva teksti**, ei tiedostotavut. Repossa on 57 em
dashia julkisissa HTML-tiedostoissa, ja mitattuna 11.8 ne ovat KAIKKI
kehittajakommenteissa (HTML `<!-- -->`, CSS ja JS). Ne eivat nay lukijalle,
joten tavutason portti olisi punainen syntyessaan eika kertoisi mitaan.
Kommenttien suomenkielisyys on eri ongelma (hygienia, ei copy-saanto) ja
kirjattu TASKS.md:hen erikseen.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EM_DASH = "—"

SKIP_DIRS = {"node_modules", ".venv", ".git", "data", "tests", "build", ".svelte-kit"}


def _iter_files(pattern: str):
    for path in ROOT.rglob(pattern):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        yield path


def _visible_text_from_html(raw: str) -> str:
    """Pudota kommentit, script/style-lohkot ja tagit; jaljelle jaa se mita
    lukija nakee."""
    out = re.sub(r"<!--.*?-->", " ", raw, flags=re.DOTALL)
    out = re.sub(r"<script\b.*?</script>", " ", out, flags=re.DOTALL | re.IGNORECASE)
    out = re.sub(r"<style\b.*?</style>", " ", out, flags=re.DOTALL | re.IGNORECASE)
    out = re.sub(r"<[^>]+>", " ", out)
    return out


def _text_outside_comments_from_svelte(raw: str) -> str:
    """Svelte: pudota HTML-kommentit, <script>-lohko ja CSS-kommentit.

    Nakyva teksti jaa jaljelle markupin sekaan; se riittaa, koska etsimme
    yhta merkkia emmeka jasenna rakennetta.
    """
    out = re.sub(r"<!--.*?-->", " ", raw, flags=re.DOTALL)
    out = re.sub(r"<script\b.*?</script>", " ", out, flags=re.DOTALL | re.IGNORECASE)
    out = re.sub(r"/\*.*?\*/", " ", out, flags=re.DOTALL)
    return out


def _hits(path: Path, text: str) -> list[str]:
    hits = []
    for i, ch in enumerate(text):
        if ch == EM_DASH:
            seg = text[max(0, i - 60) : i + 60].replace("\n", " ").strip()
            hits.append(f"{path.relative_to(ROOT)}: ...{seg}...")
    return hits


def test_no_em_dash_in_rendered_html():
    """Julkisten HTML-sivujen lukijalle nakyva teksti ei saa sisaltaa em dashia."""
    offenders: list[str] = []
    for path in _iter_files("*.html"):
        try:
            raw = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        offenders += _hits(path, _visible_text_from_html(raw))
    assert not offenders, "Em dash nakyvassa HTML-copyssa:\n" + "\n".join(offenders)


def test_no_em_dash_in_svelte_markup():
    """pro-spa: em dash ei saa paatya komponenttien nakyvaan tekstiin."""
    offenders: list[str] = []
    for path in _iter_files("*.svelte"):
        try:
            raw = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        offenders += _hits(path, _text_outside_comments_from_svelte(raw))
    assert not offenders, "Em dash Svelte-copyssa:\n" + "\n".join(offenders)


@pytest.mark.parametrize(
    "sample,should_flag",
    [
        (f"<p>a {EM_DASH} b</p>", True),  # nakyva teksti  -> kiinni
        (f"<!-- kommentti {EM_DASH} tassa -->", False),  # kommentti      -> ohi
        (f"<style>/* css {EM_DASH} */</style>", False),  # style-lohko    -> ohi
        (f"<script>// js {EM_DASH}</script>", False),  # script-lohko   -> ohi
        ("<p>ei viivaa</p>", False),  # puhdas         -> ohi
    ],
)
def test_detector_negative_controls(sample: str, should_flag: bool):
    """Negatiivinen kontrolli (muisti `gate-substring-osuma-on-sokea`).

    Ilman tata portti voisi olla vihrea siksi ettei se osu MIHINKAAN.
    """
    found = EM_DASH in _visible_text_from_html(sample)
    assert found is should_flag
