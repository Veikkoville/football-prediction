"""Syntaksi joka kaataa CI:n muttei tata konetta (16.8.2026).

MITATTU TAPAUS. `scripts/build_fpl_longtail.py` sisalsi

    f"{escape(str(ryhma[0].get("team") or short))} ..."

eli SAMAN lainausmerkin f-stringin sisalla. Se on laillinen vasta Python
3.12:sta (PEP 701). Tama kone ajaa 3.14:aa ja CI ajaa 3.11:ta, joten:

  - paikallisesti pytest oli VIHREA
  - CI:ssa se oli SyntaxError joka kaatoi KOKO tests.yml-ajon

Eika vain yhden kerran: ajo oli punaisena 15.8 asti, eli jokainen sen
jalkeinen backend-commit meni sisaan ilman etta yksikaan testi ajoi
CI:ssa. Vika ei ollut testeissa vaan sivugeneraattorissa.

Sama vikaluokka on kirjattu aiemmin toisella kielella: "gate vihrea
lokaalisti ei ole sama kuin CI" (node 20 vs 24).

🔴 DETEKTORIN HISTORIA on osa tata tiedostoa, koska se on varoitus.
Ensimmainen versio kaytti regexia -> 17 osumaa, valtaosa vaaria.
Toinen kaytti `ast.get_source_segment`ia -> 5 osumaa, KAIKKI vaaria:
peräkkaiset literaalit ovat YKSI JoinedStr-solmu, joten lainausmerkkien
laskenta meni sekaisin. Kolmas kaytti tokenisoijaa mutta ei erottanut
kolmoislainausta -> 7 osumaa, kaikki vaaria (`f\"\"\"... {c["k"]} ...\"\"\"`
on taysin laillista). Vasta neljas erottaa delimiterin.

Vaara positiivinen portissa on yhta paha kuin puuttuva: se opettaa
ohittamaan portin. Siksi alla on kontrolli molempiin suuntiin.
"""
from __future__ import annotations

import io
import pathlib
import re
import tokenize

ROOT = pathlib.Path(__file__).resolve().parents[1]
SKIP = (".venv", "node_modules", "__pycache__", "data/raw", "data\\raw")
_DELIMS = ('"""', "'''", '"', "'")


def _ci_python_version() -> tuple[int, int]:
    """CI:n python-versio workflow-tiedostosta, EI kovakoodattuna: portti ei
    saa ajautua erilleen siita mita CI oikeasti ajaa."""
    wf = (ROOT / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")
    m = re.search(r'python-version:\s*"?(\d+)\.(\d+)"?', wf)
    assert m, "tests.yml:sta ei loydy python-versiota"
    return int(m.group(1)), int(m.group(2))


def _delim(fstring_start: str) -> str | None:
    for d in _DELIMS:
        if fstring_start.endswith(d):
            return d
    return None


# 🔴 `tokenize.FSTRING_START` lisattiin vasta 3.12:ssa. Ensimmainen versio
# tasta portista kaatui CI:lla AttributeErroriin - eli CI-yhteensopivuutta
# vahtiva portti ei itse ollut CI-yhteensopiva. Sama vikaluokka kolmatta
# kertaa saman paivan aikana.
#
# Kun ajamme 3.11:lla EI TARVITA detektoria lainkaan: tulkki itse on
# auktoriteetti, ja `compile()` nostaa saman SyntaxErrorin jota vastaan
# tama portti suojaa. Detektoria tarvitaan vain uudemmalla tulkilla, joka
# hyvaksyy syntaksin jota CI ei hyvaksy.
_HAS_FSTRING_TOKENS = hasattr(tokenize, "FSTRING_START")


def same_quote_lines(src: str) -> list[int]:
    """Rivit joilla f-stringin SISALLA on sen oma yhden merkin delimiter."""
    if not _HAS_FSTRING_TOKENS:
        # Tulkki on jo CI:n ikainen -> compile() nappaa asian suoraan.
        try:
            compile(src, "<gate>", "exec")
            return []
        except SyntaxError as e:
            return [e.lineno or 0]
    out: list[int] = []
    stack: list[str | None] = []
    try:
        toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
    except Exception:
        return []  # rikkinaisen tiedoston nappaa pytestin oma import
    for t in toks:
        if t.type == tokenize.FSTRING_START:
            stack.append(_delim(t.string))
        elif t.type == tokenize.FSTRING_END:
            if stack:
                stack.pop()
        elif t.type == tokenize.STRING and stack:
            d = stack[-1]
            # Kolmoislainaus on turvallinen: sisempi yksittainen merkki ei
            # paata sita edes 3.11:ssa.
            if d and len(d) == 1 and t.string.lstrip("rbuRBUf")[:1] == d:
                out.append(t.start[0])
    return sorted(set(out))


def test_ci_python_is_older_than_local_so_this_gate_is_needed():
    """Jos CI paivitetaan 3.12:een, f-string-nesting on laillista ja taman
    portin voi poistaa. Sita ennen se on ainoa asia joka nakee eron."""
    assert _ci_python_version() < (3, 12), (
        "CI on nyt 3.12+; tama portti on tarpeeton ja voi poistua")


def test_detector_controls_both_directions():
    """🔴 Ilman naita portti nayttaisi valppaalta ja olisi kohinaa. Kolme
    ensimmaista detektoriversiota lapaisi tasan tallaisen tarkistuksen
    puutteen takia."""
    if not _HAS_FSTRING_TOKENS:
        # 3.11:lla aito tapaus on SyntaxError jo compile()-vaiheessa, ja
        # tulkki on silloin itse portti. Riittaa todistaa etta se nappaa.
        assert same_quote_lines('x = f"{r.get("team")}"') == [1]
        return
    assert same_quote_lines('x = f"{r.get("team")} page"') == [1], \
        "aito tapaus jai loytymatta"
    assert same_quote_lines('x = f"""a {c["k"]} b"""') == [], \
        "kolmoislainaus on laillinen myos 3.11:ssa"
    assert same_quote_lines("""x = f"{r.get('team')} page\"""") == [], \
        "eri lainausmerkit ovat laillisia"
    assert same_quote_lines('d = {"isPartOf": {"@id": f"{BASE}/#org"}}') == [], \
        "tavallinen sanakirja ei ole f-string-nesting"


def test_no_fstring_reuses_its_own_quote():
    hits: list[str] = []
    for f in ROOT.rglob("*.py"):
        if any(s in str(f) for s in SKIP):
            continue
        for ln in same_quote_lines(f.read_text(encoding="utf-8")):
            hits.append(f"{f.relative_to(ROOT)}:{ln}")
    ver = ".".join(map(str, _ci_python_version()))
    assert not hits, (
        f"f-string kayttaa omaa lainausmerkkiaan sisallaan. Laillista 3.12+, "
        f"mutta CI ajaa {ver} -> SyntaxError joka kaataa KOKO ajon:\n  "
        + "\n  ".join(hits))
