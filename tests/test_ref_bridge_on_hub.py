"""Luojan ref ei saa kadota hubin ja SPA:n valiin (16.8.2026).

MITATTU TAPAUS. Affiliate-attribuutio kaapataan SPA:ssa (pro.goaliq.app):
`captureRef` lukee `?ref=` ja tallentaa sen localStorageen, josta signUp
liittaa sen tiliin. Se toimii vain jos kavija LASKEUTUU pro.goaliq.appiin
ref mukanaan.

Luojat eivat linkita niin. He linkittavat sivun joka lukee parhaiten, eli
goaliq.appiin tai goaliq.app/fpl:aan. Ne ovat ERI ORIGIN, joten hubiin
tallennettu ref on SPA:lle nakymaton - same-origin-saanto ei ole yksityis-
kohta jonka voi kiertaa. Luoja joka postasi `goaliq.app/fpl?ref=WOLFY` sai
tasan nolla attribuutiota, eika kumpikaan osapuoli nahnyt sita tapahtuvan.

Korjaus: refia ei tallenneta SPA:lle vaan se KANNETAAN sinne. `ref-bridge.js`
muistaa refin hubin sisalla ja liittaa sen jokaiseen pro.goaliq.app-linkkiin.

🔴 Tama portti on rakenteellinen (sivut + skriptin sisalto). Selaimessa
todennettu erikseen 16.8: index.html?ref=WOLFY -> 7/7 SPA-linkkia tagattu,
seuraava hub-sivu ilman parametria -> 6/6 tagattu, tyhja storage -> 0/6
tagattu.
"""
from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "ref-bridge.js"
TAG = "ref-bridge.js"
SPA_HOST = "pro.goaliq.app"


# Sivut joille kavija EI voi tulla luojan linkista: naihin tullaan
# sahkopostista tai Stripen paluu-URLista, joten refia ei ole olemassa.
NOT_LANDABLE = {"reset-password.html", "subscription-managed.html"}


def _landing_pages() -> list[pathlib.Path]:
    """Kaikki sivut joille luojan linkki voi laskeutua.

    🔴 Ensimmainen versio tasta portista kysyi "linkittaako sivu SPA:han", ja
    se oli vaara kysymys kahdesta syysta:

      1. Se katsoi vain `ROOT/*.html`, joten `/fpl/`-alasivut (35) ja
         `/predictions/`-sivut (1911) jaivat kokonaan mittaamatta. Silta
         puuttui 28 sivulta tuotannossa, portti oli vihrea, ja niiden
         joukossa oli `/fpl/best-captain` jossa ON upsell-linkki
         pro.goaliq.appiin. Attribuutio katosi tarkalleen siella missa se
         eniten merkitsi.
      2. SPA-linkin puuttuminen ei tarkoita ettei siltaa tarvita. Silta myos
         MUISTAA refin seuraavalle sivulle. World-cup-sivut eivat linkita
         SPA:han, mutta ilman siltaa luojan linkki niille menettaa refin
         heti ensimmaisella klikilla.

    Oikea kysymys on siis "voiko tanne laskeutua", ei "vieko tama SPA:han".
    """
    out = []
    for pat in ("*.html", "fpl/**/*.html", "predictions/**/*.html"):
        for p in sorted(ROOT.glob(pat)):
            if p.name in NOT_LANDABLE:
                continue
            out.append(p)
    return out


def test_bridge_exists_and_targets_the_spa_host():
    src = BRIDGE.read_text(encoding="utf-8")
    assert SPA_HOST in src, "silta ei tunnista SPA:n hostia"
    assert "searchParams.set('ref'" in src, "silta ei liita refia linkkiin"
    assert "localStorage" in src, "silta ei muista refia sivunvaihdon yli"


def test_bridge_regex_matches_the_spa_and_backend_rule():
    """Kolme kopiota samasta saannosta kolmella kielella. Eroavaisuus
    epaonnistuisi HILJAA - juuri niin kuin tama tiedosto on olemassa
    estamaan."""
    src = BRIDGE.read_text(encoding="utf-8")
    assert re.search(r"\^\[A-Z0-9_-\]\{2,32\}\$", src), (
        "sillan ref-validointi ei vastaa SPA:n cleanRefia eika backendin "
        "_clean_affiliate_refia")


def test_every_landing_page_loads_the_bridge():
    missing = [str(p.relative_to(ROOT)) for p in _landing_pages()
               if TAG not in p.read_text(encoding="utf-8")]
    assert not missing, (
        f"{len(missing)} sivua ilman ref-siltaa. Luojan linkki naille "
        f"menettaa attribuution: {missing[:12]}")


def test_generated_subpages_are_actually_covered():
    """Negatiivinen kontrolli kattavuudelle. Ilman tata edellinen testi
    lapaisisi myos silloin kun glob ei osu mihinkaan - ja tasan sellainen
    tyhja mittaus oli syy siihen etta 28 sivua jai huomaamatta."""
    pages = _landing_pages()
    fpl_sub = [p for p in pages if p.parent.name == "fpl" or "fpl/" in str(p)]
    preds = [p for p in pages if "predictions" in str(p.parent)]
    assert len(fpl_sub) >= 12, (
        f"/fpl/-alasivuja loytyi vain {len(fpl_sub)}; portti ei mittaa niita")
    assert len(preds) >= 100, (
        f"/predictions/-sivuja loytyi vain {len(preds)}; portti ei mittaa niita")


def test_shared_generator_tail_carries_the_bridge():
    """Silta on siina merkkijonossa jonka JOKAINEN generaattori jo emittoi.

    Kasin neljaan generaattoriin lisattyna se unohtui kahdesta - siksi se
    ei saa palata generaattorikohtaiseksi."""
    css = (ROOT / "scripts" / "mobile_css.py").read_text(encoding="utf-8")
    assert TAG in css, (
        "scripts/mobile_css.py ei sisalla ref-siltaa. Jos se siirrettiin "
        "takaisin generaattoreihin, seuraava uusi generaattori unohtaa sen.")


def test_every_page_generator_emits_the_shared_tail():
    """Generoidut sivut saavat sillan VAIN jaetun hannan kautta.

    Generaattori joka kirjoittaa oman </body>:nsa ilman `MOBILE_COLS_JS`:aa
    tuottaa sivuja joilta silta puuttuu - ja koska sivut syntyvat vasta
    ajossa, sita ei nakisi kukaan ennen kuin luoja valittaa puuttuvasta
    provisiosta. Siksi vahti on generaattoreissa eika vain tuotoksessa.
    """
    offenders = []
    for g in sorted((ROOT / "scripts").glob("build_*.py")):
        src = g.read_text(encoding="utf-8")
        if "</body>" not in src:
            continue
        if "MOBILE_COLS_JS" not in src:
            offenders.append(g.name)
    assert not offenders, (
        "nama generaattorit kirjoittavat </body>:n ilman jaettua hantaa, "
        f"joten niiden sivuilta puuttuu ref-silta: {offenders}")


def test_non_landing_pages_are_exempt():
    """Portti ei saa vaatia siltaa sivulta jolle ei voi laskeutua luojan
    linkista - se olisi kohinaa joka opettaa ohittamaan portin."""
    names = {p.name for p in _landing_pages()}
    assert not (names & NOT_LANDABLE)
    assert (ROOT / "reset-password.html").exists(), (
        "vapautuslista viittaa sivuun jota ei ole; siivoa lista")
