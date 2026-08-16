"""Uusi tili ei saa peria selaimeen jaanytta joukkuetta (16.8.2026).

MITATTU TAPAUS. Ville loi oikean tilin ja nakit valmiin 15 pelaajan
kokoonpanon jota han ei ollut koskaan valinnut: pelkkia hintalattian
pelaajia (4,0-5,5 m), seitseman samasta noususta. Viikkosilmukka alkoi
heti neuvoa kapteenia ja siirtoa siihen joukkueeseen.

Syy oli `syncDraft`issa:

    if (!remote) {
        if (localIds && localIds.length > 0) void pushRemoteDraft(localIds, ...)
    }

Tuoreella tililla EI ole remote-draftia, joten selaimeen jaanyt kokeilu
(esim. Fit checkerin "Save as draft") nostettiin tilille ja seurasi sita
puhelimeen asti. Draft on selainkohtainen, tili ei ole - ja rekisterointi
oli ainoa kohta jossa nama kaksi kohtasivat ilman etta kukaan paatti mitaan.

Villen saanto: "kun joku tekee tilin niin siella ei saa olla mitaan
joukkuetta valmiina."

Portti on rakenteellinen (lahdekoodigrep) koska SPA:ssa ei ole
JS-testiajuria. Siksi alla on NEGATIIVINEN KONTROLLI: ilman sita tama
mittaisi vain merkkijonon olemassaoloa jossain tiedostossa, ja sellainen
portti nayttaa valppaalta ilman etta se nakee mitaan.
"""
from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
AUTH = ROOT / "web" / "pro-spa" / "src" / "lib" / "auth.svelte.ts"
DRAFT = ROOT / "web" / "pro-spa" / "src" / "lib" / "draft.ts"


def _sign_up_body(src: str) -> str:
    """signUp-funktion runko sulkeiden tasapainon mukaan.

    Rajaus on olennainen: `clearDraft` muualla tiedostossa (esim. signOut)
    EI saa kelvata todisteeksi, koska se ei estaisi perimista.
    """
    m = re.search(r"export async function signUp\b", src)
    assert m, "signUp-funktiota ei loydy auth.svelte.ts:sta"
    i = src.index("{", m.end())
    depth = 0
    for j in range(i, len(src)):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                return src[i : j + 1]
    raise AssertionError("signUp-funktion runko ei sulkeudu")


def test_clear_draft_exists_and_wipes_all_three_keys():
    src = DRAFT.read_text(encoding="utf-8")
    body_start = src.index("export function clearDraft")
    body = src[body_start : body_start + 600]
    for key in ("DRAFT_LS_KEY", "DRAFT_TS_KEY", "CAP_LS_KEY"):
        assert key in body, (
            f"clearDraft ei poista avainta {key}. Jaljelle jaava kapteenivalinta "
            f"tai aikaleima tekee tyhjennyksesta osittaisen.")


def test_signup_clears_local_draft():
    body = _sign_up_body(AUTH.read_text(encoding="utf-8"))
    assert "clearDraft()" in body, (
        "signUp ei tyhjenna lokaalia draftia. Ilman sita syncDraft nostaa "
        "selaimeen jaaneen kokeilun tuoreelle tilille (mitattu 16.8.2026).")


def test_negative_control_mutation_is_caught():
    """Poista kutsu -> portin PITAA kaatua. Ilman tata testi lapaisisi
    myos silloin kun se mittaa vaaraa asiaa."""
    mutated = AUTH.read_text(encoding="utf-8").replace("clearDraft();", "")
    body = _sign_up_body(mutated)
    assert "clearDraft()" not in body, (
        "negatiivinen kontrolli ei purrut: portti lapaisee ilman kutsuakin, "
        "eli se ei mittaa sita mita luulee mittaavansa")
