"""Portit pelaajatason minuuttiohituksille.

MIKSI TAMA TIEDOSTO ON OLEMASSA (14.8.2026). Pelaajaohituksilla ei ollut
YHTAAN porttia, ja mekanismi ehti rikkoutua kahdesti eri tavalla:

  27.7  CSV oli gitignoressa -> tiedostoa ei ollut CI-runnerilla -> ohitus
        eli vain kehityskoneella (korjattu !-poikkeuksella).
  14.8  Ohituslohko oli builderissa hintapriorin EDELLA. Hintapriori
        kirjoittaa `mm_by_player[pid]` uusiksi jokaiselle pelaajalle jolla ei
        ole PL-minuutteja -> jokainen ohitus historiattomaan pelaajaan
        katosi. Loki tulosti silti "p_start 0.00 -> 0.90" ja artefaktiin jai
        0.38. Signaali siis VALEHTELI onnistumisesta.

Molemmat vikaluokat naytttavat lokista onnistuneilta. Siksi tarkein portti
alla ei katso koodia eika lokia vaan ARTEFAKTIA: onko CSV:n luku oikeasti
siina tiedostossa jonka API servaa. Se nappaa kumman tahansa mekanismin —
ja myos seuraavan jota kukaan ei ole viela keksinyt.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.models.fpl_player_overrides import load_player_overrides

ROOT = Path(__file__).resolve().parents[1]
PROJECTIONS = ROOT / "data" / "fpl_xp_projections.json"


def _write(tmp_path, body):
    p = tmp_path / "o.csv"
    p.write_text("player_id,p_start,reason,review_by\n" + body, encoding="utf-8")
    return p


# --------------------------------------------------------------------------
# TARKEIN PORTTI: menikö ohitus artefaktiin asti
# --------------------------------------------------------------------------

def test_shipped_overrides_land_in_the_projection_artifact():
    """Jokaisen CSV-rivin p_start on LOYDYTTAVA projektiotiedostosta.

    Tama on ainoa portti joka mittaa sita mika oikeasti kiinnostaa: mita
    API servaa. Builderin loki ei kelpaa todisteeksi — se tulosti 14.8
    onnistumisen ohituksesta joka ei mennyt perille (ks. moduulin docstring).

    Jos tama kaatuu ja CSV:ta on juuri muokattu, aja
    `python scripts/build_fpl_xp.py` ja committaa artefakti. Rivi jota ei ole
    artefaktissa EI OLE tuotannossa, joten punainen on oikea vari.
    """
    overrides = load_player_overrides()
    assert overrides, "CSV on tyhja tai puuttuu — ohitusmekanismi on pois paalta"
    payload = json.loads(PROJECTIONS.read_text(encoding="utf-8"))
    by_id = {int(p["id"]): p for p in payload["players"]}

    missing, wrong = [], []
    for pid, ov in overrides.items():
        row = by_id.get(pid)
        if row is None:
            missing.append(pid)
            continue
        if abs(float(row["p_start"]) - ov["p_start"]) > 0.01:
            wrong.append(
                f"{pid} ({row.get('web_name')}): CSV {ov['p_start']:.2f} != "
                f"artefakti {float(row['p_start']):.2f}")
    assert not missing, f"ohitetut pelaajat puuttuvat projektiosta: {missing}"
    assert not wrong, "ohitus ei mennyt perille:\n  " + "\n  ".join(wrong)


def test_overridden_players_are_not_all_price_prior_tiers():
    """NEGATIIVINEN KONTROLLI edelliselle.

    Hintapriorin tasot ovat 0.38 / 0.16 / 0.096. Jos ohituslohko siirtyisi
    taas priorin edelle, ohitetut historiattomat pelaajat asettuisivat
    TASMALLEEN naihin lukuihin — ja edellinen testi laukeaisi vain jos joku
    sattuu kirjoittamaan CSV:hen muun luvun. Tama sanoo sen suoraan: ainakin
    yhden ohitetun pelaajan on oltava jokin muu kuin priorin taso.
    """
    overrides = load_player_overrides()
    tiers = {0.38, 0.16, 0.096}
    non_tier = [pid for pid, ov in overrides.items()
                if round(ov["p_start"], 3) not in tiers]
    assert non_tier, (
        "jokainen ohitus osuu hintapriorin tasoon — portti ei erota "
        "onnistumista siita etta priori kirjoitti arvon")


# --------------------------------------------------------------------------
# Lataus: rikkinainen rivi ei saa kaataa eika livahtaa lapi
# --------------------------------------------------------------------------

def test_out_of_range_p_start_is_dropped(tmp_path):
    assert load_player_overrides(_write(tmp_path, '1,1.4,"x",2026-10-01\n')) == {}
    assert load_player_overrides(_write(tmp_path, '1,-0.2,"x",2026-10-01\n')) == {}


def test_valid_row_is_loaded(tmp_path):
    """POSITIIVINEN KONTROLLI: ilman tata tyhja tulos voisi tarkoittaa joko
    'hylatty' tai 'lukija on rikki'."""
    out = load_player_overrides(_write(tmp_path, '379,0.85,"x",2026-10-01\n'))
    assert out == {379: {"p_start": 0.85, "reason": "x", "review_by": "2026-10-01"}}


def test_non_numeric_row_is_skipped_not_fatal(tmp_path):
    out = load_player_overrides(
        _write(tmp_path, 'abc,0.5,"x",2026-10-01\n379,0.85,"y",2026-10-01\n'))
    assert set(out) == {379}


def test_missing_file_is_not_an_error(tmp_path):
    assert load_player_overrides(tmp_path / "ei-ole.csv") == {}


def test_comment_lines_are_ignored(tmp_path):
    p = tmp_path / "c.csv"
    p.write_text("# selitys\nplayer_id,p_start,reason,review_by\n"
                 '379,0.85,"x",2026-10-01\n', encoding="utf-8")
    assert set(load_player_overrides(p)) == {379}


# --------------------------------------------------------------------------
# Shipatun CSV:n sisalto
# --------------------------------------------------------------------------

@pytest.mark.parametrize("field", ["reason", "review_by"])
def test_every_shipped_row_has_a_reason_and_a_review_date(field):
    """Ohitus ilman perustelua on kasisaato jota kukaan ei osaa myohemmin
    kumota, ja ilman review_by:ta se jaa taistelemaan mallia vastaan sen
    jalkeen kun mallilla on oikeaa 26/27-dataa."""
    for pid, ov in load_player_overrides().items():
        assert ov[field], f"pelaaja {pid}: {field} puuttuu"
