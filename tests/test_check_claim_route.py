"""Portti tarkistusreitin vahdille itselleen.

MIKSI TAMA ON OLEMASSA (15.8.2026). `check_claim_route.py` rakennettiin
estamaan julkaisu jossa vaite on tosi mutta lukija ei loyda sita. Ajoin sen
omaan erikoistilanne-artikkeliini ja se antoi VAARAN HALYTYKSEN kahdesti:

  1. `/fpl/stats` renderoi taulukkonsa selaimessa. Vahti riisuu script-lohkot
     (oikein: lukija ei nae niita), joten koko datataulukko oli sille
     nakymaton ja se vaitti etta "Struijk" ei ole sivulla.
  2. Payload kantaa raakoja floatteja (`4.5`) ja solu muotoillaan `4.50`.
     Merkkijonohaku ei loytanyt lukua jonka lukija nakee.

Vaara halytys on PAHEMPI kuin puuttuva tyokalu: portti joka huutaa turhaan
opitaan ohittamaan, ja silloin se ei estä sita oikeaa virhetta jota varten se
rakennettiin.

Korjaus toi kolmannen tilan `VAIN-DATASSA`. Vaara jota se avaa on toinen:
numeerinen vertailu voi KEKSIA katteen jota ei ole. Siksi jokaisella
positiivisella vaitteella on tassa negatiivinen kontrolli.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.check_claim_route import _numerot, _visible_text, check  # noqa: E402

# Pienoismalli client-renderoidusta sivusta: nakyva teksti on ohut, luvut
# elavat script-lohkon raakana JSONina ilman perannollisia nollia.
DOC = """<html><body>
<p>Free FPL stats. 400 players, season totals.</p>
<table><tbody><tr><td>Mbeumo</td><td class="n m-hide">13.31</td></tr></tbody></table>
<script>const ROWS=[[328,"Struijk","BHA","DEF",2.97,2.62],[4,"Gabriel","ARS","DEF",4.65,4.5],
[96,"Thiaw","NEW","DEF",5.9,5.38],[1,"O'Reilly","MCI","DEF",6.73,1.45]];</script>
</body></html>"""


def _tulos(monkeypatch, claims):
    import scripts.check_claim_route as m

    monkeypatch.setattr(m, "fetch", lambda url: DOC)
    return dict(check("https://example.invalid", claims))


def test_nakyva_teksti_on_ok(monkeypatch):
    assert _tulos(monkeypatch, ["400 players"])["400 players"] == "OK"


def test_script_lohkon_nimi_on_vain_datassa(monkeypatch):
    # Ennen korjausta tama oli EI-LOYDY ja olisi blokannut toden vaitteen.
    assert _tulos(monkeypatch, ["Struijk"])["Struijk"] == "VAIN-DATASSA"


def test_perannolliset_nollat_loytyvat_numeerisesti(monkeypatch):
    # Payload: 4.5 ja 5.9. Artikkeli: 4.50 ja 5.90. Lukija nakee jalkimmaiset.
    r = _tulos(monkeypatch, ["4.50", "5.90"])
    assert r["4.50"] == "VAIN-DATASSA"
    assert r["5.90"] == "VAIN-DATASSA"


def test_numeerinen_vertailu_ei_nosta_ok_tasolle(monkeypatch):
    """NEGATIIVINEN KONTROLLI: datassa oleva luku ei saa nayttaa lukijan
    nakemalta. Jos tama palauttaisi OK:n, portti lakkaisi erottamasta
    renderoidun tekstin datasta ja koko kolmas tila olisi turha."""
    assert _tulos(monkeypatch, ["4.50"])["4.50"] != "OK"


def test_puuttuva_luku_yha_blokkaa(monkeypatch):
    """NEGATIIVINEN KONTROLLI: korjaus ei saa tehda vahdista hyvaksyvaa.
    9.99 ei ole dokumentissa missaan muodossa."""
    assert _tulos(monkeypatch, ["9.99"])["9.99"] == "EI-LOYDY"


def test_osajono_ei_kelpaa_numeeriseksi_osumaksi(monkeypatch):
    """NEGATIIVINEN KONTROLLI, tarkein tassa tiedostossa.

    `1.4` on osajono luvusta `1.45` joka on datassa. Jos vertailu tehtaisiin
    merkkijonona tai normalisoimalla, portti keksisi katteen vaitteelle jota
    sivu ei tue. Sama reika kuin aiemmin mitattu rstrip/lower-normalisoinnissa.
    """
    assert _tulos(monkeypatch, ["1.4"])["1.4"] == "EI-LOYDY"


def test_mobiilissa_piilotettu_erotetaan(monkeypatch):
    # 13.31 on m-hide-solussa: tyopoydalla nakyy, puhelimessa ei.
    assert _tulos(monkeypatch, ["13.31"])["13.31"] == "VAIN-TYOPOYTA"


def test_script_sisalto_ei_vuoda_nakyvaan_tekstiin():
    """NEGATIIVINEN KONTROLLI riisunnalle: jos script-lohko vuotaisi nakyvaan
    tekstiin, kaikki olisi OK eivatka tilat erottuisi mistaan."""
    nakyva = _visible_text(DOC)
    assert "Struijk" not in nakyva
    assert "400 players" in nakyva


def test_numerot_poimii_rajoineen():
    luvut = _numerot('a 4.5 b 14.55 c 328 d')
    assert 4.5 in luvut and 14.55 in luvut and 328.0 in luvut
    # 4.55 ei ole dokumentissa vaikka merkkijono "4.55" esiintyy luvun
    # 14.55 sisalla.
    assert 4.55 not in luvut
