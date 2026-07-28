#!/usr/bin/env python3
"""Copy-tyyliportti web-pinnalle: em dash (U+2014) kielletty copyssa.

Pari mobiilin `scripts/check-copy-style.js`:lle. Villen saanto 27.7:
korjaukset AINA web + mobiili, joten myos portin on oltava molemmilla.

MITA SKANNATAAN JA MIKSI JUURI TATA
-----------------------------------
1. JULKAISTUT HTML-sivut (goaliq.app: juuri + fpl/ + predictions/).
   Naista <script>- ja <style>-lohkot ja <!-- --> -kommentit leikataan pois:
   ne eivat ole copya.
2. pro-SPA:n Svelte-markup (script- ja style-lohkojen ULKOPUOLINEN teksti).

GENERAATTOREITA (build_*.py) EI skannata suoraan, ja se on tietoinen valinta.
Ensimmainen versio skannasi ne ja tuotti 30 vaaraa osumaa: Python-docstringit
ja suomenkieliset koodikommentit ovat taynna em dasheja, eivatka ne ole copya.
Generaattorin tuotos on committattuna repossa, joten generaattorin lisaama em
dash nakyy kohdassa 1 seuraavalla ajolla. Portti osoittaa silloin HTML-riviin;
korjaus kuuluu silti generaattoriin, koska CI kirjoittaa nama sivut yli
<= 3 h valein (vrt. 27.7: sivuille tehty korjaus katosi hiljaa).

Rajaus:
  - Yksinainen '—' lainausmerkkien valissa = puuttuvan arvon merkki, sallitaan.
  - &mdash; on sama merkki HTML-entiteettina, joten se lasketaan mukaan.

Aja: python scripts/check_copy_style.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EM = "—"

HTML_GLOBS = ["*.html", "fpl/*.html", "predictions/*.html", "predictions/**/*.html"]
SPA_DIR = ROOT / "web" / "pro-spa" / "src"
# 28.7: versioidut CSV-inputit joiden tekstikentat paatyvat API-payloadiin ja
# sielta UI:hin (esim. fpl_player_overrides.csv:n `reason` nakyy pelaajakortilla).
# Nama eivat ole koodia eivatka HTML:aa, joten ne jaivat portin ulkopuolelle ja
# yksi em dash paasi lapi kayttajalle asti.
COPY_CSV = ["data/fpl_player_overrides.csv", "data/fpl_manual_overrides.csv"]

PLACEHOLDER = re.compile(r"(['\"`>])" + EM + r"(['\"`<])")


def _blank(m: re.Match) -> str:
    """Korvaa osuma valilyonnein niin etta rivinumerot sailyvat."""
    return re.sub(r"[^\n]", " ", m.group(0))


def _mask_non_copy(text: str) -> str:
    """Nollaa kaikki mika ei ole kayttajalle nakyvaa tekstia."""
    text = re.sub(r"<!--.*?-->", _blank, text, flags=re.DOTALL)
    text = re.sub(r"<script\b.*?</script>", _blank, text, flags=re.DOTALL | re.I)
    text = re.sub(r"<style\b.*?</style>", _blank, text, flags=re.DOTALL | re.I)
    return text


def scan(path: Path) -> list[tuple[int, str]]:
    raw = path.read_text(encoding="utf-8", errors="replace")
    if EM not in raw and "&mdash;" not in raw:
        return []
    # CSV-inputeissa #-rivit ovat dokumentaatiota (suomeksi, taynna em dasheja),
    # eivat copya. Vain datarivien tekstikentat paatyvat kayttajalle.
    is_csv = path.suffix.lower() == ".csv"
    masked = raw if is_csv else _mask_non_copy(raw)
    raw_lines = raw.split("\n")
    hits: list[tuple[int, str]] = []
    for i, line in enumerate(masked.split("\n")):
        if is_csv and line.lstrip().startswith("#"):
            continue
        probe = PLACEHOLDER.sub("  ", line)
        if EM in probe or "&mdash;" in probe:
            hits.append((i + 1, raw_lines[i].strip()[:200]))
    return hits


def main() -> int:
    targets: list[Path] = []
    for g in HTML_GLOBS:
        targets += sorted(ROOT.glob(g))
    if SPA_DIR.exists():
        targets += sorted(SPA_DIR.rglob("*.svelte"))
    targets += [ROOT / c for c in COPY_CSV if (ROOT / c).exists()]
    targets = sorted(set(targets))

    all_hits = [(p, n, t) for p in targets for n, t in scan(p)]

    if not all_hits:
        print(f"check_copy_style OK - 0 em dashia copyssa ({len(targets)} tiedostoa)")
        return 0

    print(
        f"check_copy_style FAIL - {len(all_hits)} em dashia kayttajalle "
        f"nakyvassa tekstissa:\n"
    )
    for path, line_no, text in all_hits:
        print(f"  {path.relative_to(ROOT)}:{line_no}\n    {text}\n")
    print(
        "Em dash on kielletty GoalIQ-copyssa. Kayta pistetta, pilkkua tai "
        "kaksoispistetta. Jos rivi on generoitu, korjaa GENERAATTORI: CI "
        "kirjoittaa nama sivut yli <= 3 h valein."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
