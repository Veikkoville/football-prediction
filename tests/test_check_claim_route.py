"""Portti tarkistusreitin vahdille.

TAUSTA (15.8.2026). Julkaisutarkistaja blokkasi GW1-muistion kuudella
loydoksella, joista KAKSI oli puhtaasti mekaanisia:

  1. "beats 119 of the 161 fully fit defenders" — tosi luku, mutta linkattu
     sivu on top-100 eika siina pelaajaa (Mukiele, 17.0) ollut lainkaan.
  2. Sesko 11.4 kun sivu sanoo 11.3 — ja 11.4 oli sivulla mutta kuului
     TOISELLE pelaajalle.

Molemmat olisi loytynyt koneella. Tekstin TYYLI ei ole koneellisesti
tarkistettavissa, ja siksi tama tyokalu ei kirjoita eika arvioi tekstia — se
vastaa yhteen kysymykseen: naakko lukija taman luvun siina paikassa johon
teksti hanet lahettaa.

Testit ajavat OFFLINE: verkkokutsu on monkeypatchattu, koska CI:ssa ei ole
egressia julkiseen webiin (kirjattu rajoite) eika portti saa olla riippuvainen
tuotannon senhetkisesta sisallosta.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.check_claim_route as ccr  # noqa: E402

SIVU = """
<html><head><style>.x{content:"999"}</style>
<script>var hidden = "12345";</script></head>
<body>
<!-- kommentissa oleva 777 ei ole nakyvaa sisaltoa -->
<h1>Team news</h1>
<p>61 players are ruled out and 15 are doubtful.</p>
<table>
<thead><tr><th>Player</th><th class="n">Owned</th>
<th class="n m-hide">Last season</th><th>Cover</th></tr></thead>
<tbody>
<tr><td>Mukiele</td><td class="n">4.3%</td>
    <td class="n m-hide">113 last yr</td><td>Hume <span>17.9</span></td></tr>
<tr><td>&Scaron;e&scaron;ko</td><td class="n">2.1%</td>
    <td class="n m-hide">88 last yr</td><td>Zirkzee <span>11.3</span></td></tr>
</tbody></table>
</body></html>
"""


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    monkeypatch.setattr(ccr, "fetch", lambda url: SIVU)


def _tulos(claims):
    return dict(ccr.check("https://example.test/x", claims))


def test_nakyva_luku_on_ok():
    assert _tulos(["61", "Mukiele", "4.3%", "11.3"]) == {
        "61": "OK", "Mukiele": "OK", "4.3%": "OK", "11.3": "OK"}


def test_puuttuva_luku_havaitaan():
    """TAMA on se vika joka blokkasi muistion: luku jota sivulla ei ole."""
    assert _tulos(["119", "161"]) == {"119": "EI-LOYDY", "161": "EI-LOYDY"}


def test_vain_tyopoydalla_nakyva_erotellaan_puuttuvasta():
    """m-hide-sarake ei ole tarkistusreitti puhelinkayttajalle, mutta se on
    eri asia kuin puuttuva luku — ja lopputulos on eri toimenpide."""
    assert _tulos(["113 last yr"]) == {"113 last yr": "VAIN-TYOPOYTA"}


def test_scriptin_ja_tyylin_sisalto_ei_kelpaa_todisteeksi():
    """Lukija ei nae script- eika style-lohkoa. Jos ne kelpaisivat, portti
    hyvaksyisi luvun jota kukaan ei voi nahda."""
    assert _tulos(["12345", "999"]) == {"12345": "EI-LOYDY", "999": "EI-LOYDY"}


def test_html_kommentti_ei_kelpaa_todisteeksi():
    assert _tulos(["777"]) == {"777": "EI-LOYDY"}


def test_entiteetit_puretaan():
    """Sivu koodaa aksentit entiteeteiksi. Ilman purkua Sesko ei loytyisi
    vaikka lukija nakee hanet."""
    assert _tulos(["Šeško"]) == {"Šeško": "OK"}


def test_tagirajan_yli_menevaa_ei_yhdisteta_vaaraan_osumaan():
    """`Hume <span>17.9</span>` -> nakyvassa tekstissa "Hume 17.9". Tama on
    tarkoitettu kayttaytyminen: lukija nakee ne vierekkain."""
    assert _tulos(["Hume 17.9"]) == {"Hume 17.9": "OK"}


def test_main_palauttaa_ykkosen_kun_vaite_puuttuu(capsys):
    rc = ccr.main(["--url", "https://example.test/x", "--claim", "119"])
    assert rc == 1
    out = capsys.readouterr().out
    assert "EI OLE sivulla" in out


def test_main_palauttaa_nollan_kun_kaikki_loytyy():
    assert ccr.main(["--url", "https://example.test/x",
                     "--claim", "61", "--claim", "Mukiele"]) == 0


def test_ilman_vaitteita_virhe():
    assert ccr.main(["--url", "https://example.test/x"]) == 2
