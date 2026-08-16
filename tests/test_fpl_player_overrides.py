"""Portit pelaajatason ohituksille (p_start + xg_mult).

MIKSI TAMA TIEDOSTO ON OLEMASSA (14.8.2026). Pelaajaohituksilla ei ollut
YHTAAN porttia, ja mekanismi ehti rikkoutua kahdesti eri tavalla:

  27.7  CSV oli gitignoressa -> tiedostoa ei ollut CI-runnerilla -> ohitus
        eli vain kehityskoneella (korjattu !-poikkeuksella).
  14.8  Ohituslohko oli builderissa hintapriorin EDELLA. Hintapriori
        kirjoittaa `mm_by_player[pid]` uusiksi jokaiselle pelaajalle jolla ei
        ole PL-minuutteja -> jokainen ohitus historiattomaan pelaajaan
        katosi. Loki tulosti silti "p_start 0.00 -> 0.90" ja artefaktiin jai
        0.38. Signaali siis VALEHTELI onnistumisesta.

Molemmat vikaluokat nayttavat lokista onnistuneilta. Siksi tarkein portti
alla ei katso koodia eika lokia vaan ARTEFAKTIA: onko CSV:n luku oikeasti
siina tiedostossa jonka API servaa.
"""
from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path

import pytest

from src.models import fpl_xp as xp
from src.models.fpl_player_overrides import load_player_overrides

ROOT = Path(__file__).resolve().parents[1]
PROJECTIONS = ROOT / "data" / "fpl_xp_projections.json"

TODAY = _dt.date(2026, 8, 14)


def _write(tmp_path, body, header="player_id,web_name,p_start,reason,review_by,xg_mult,until_available"):
    p = tmp_path / "o.csv"
    p.write_text(header + "\n" + body, encoding="utf-8")
    return p


# --------------------------------------------------------------------------
# TARKEIN PORTTI: menikö ohitus artefaktiin asti
# --------------------------------------------------------------------------

def test_shipped_overrides_land_in_the_projection_artifact():
    """Jokaisen CSV-rivin p_start on LOYDYTTAVA projektiotiedostosta.

    Tama on ainoa portti joka mittaa sita mika oikeasti kiinnostaa: mita
    API servaa. Builderin loki ei kelpaa todisteeksi — se tulosti 14.8
    onnistumisen ohituksesta joka ei mennyt perille.

    Jos tama kaatuu ja CSV:ta on juuri muokattu, aja
    `python scripts/build_fpl_xp.py` ja committaa artefakti. Rivi jota ei ole
    artefaktissa EI OLE tuotannossa, joten punainen on oikea vari.
    """
    overrides, warn = load_player_overrides()
    assert overrides, f"CSV on tyhja tai kaikki rivit hylattiin: {warn}"
    payload = json.loads(PROJECTIONS.read_text(encoding="utf-8"))
    by_id = {int(p["id"]): p for p in payload["players"]}

    missing, wrong = [], []
    for pid, ov in overrides.items():
        if ov["p_start"] is None:
            continue          # pelkka maaliuhkarivi, ei kosketa minuutteihin
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


def test_shipped_rows_are_all_live_not_expired():
    """`review_by` on nyt PORTTI. Vanhentunut rivi ei ole voimassa, ja
    silloin tuotannossa on eri luku kuin CSV:ssa lukee — ilman tata testia se
    tila olisi nakyvissa vain yhdessa builderin lokirivissa."""
    _out, warn = load_player_overrides()
    expired = [w for w in warn if "MENNYT" in w]
    assert not expired, "vanhentuneita rivejä:\n  " + "\n  ".join(expired)


def test_overridden_players_are_not_all_price_prior_tiers():
    """NEGATIIVINEN KONTROLLI edelliselle.

    Hintapriorin tasot ovat 0.38 / 0.16 / 0.096. Jos ohituslohko siirtyisi
    taas priorin edelle, ohitetut historiattomat pelaajat asettuisivat
    TASMALLEEN naihin lukuihin — ja edellinen testi laukeaisi vain jos joku
    sattuu kirjoittamaan CSV:hen muun luvun.
    """
    overrides, _ = load_player_overrides()
    tiers = {0.38, 0.16, 0.096}
    non_tier = [pid for pid, ov in overrides.items()
                if ov["p_start"] is not None
                and round(ov["p_start"], 3) not in tiers]
    assert non_tier, (
        "jokainen ohitus osuu hintapriorin tasoon — portti ei erota "
        "onnistumista siita etta priori kirjoitti arvon")


# --------------------------------------------------------------------------
# xg_mult: TODISTA ETTA NUPPI LIIKUTTAA LUKUA
# --------------------------------------------------------------------------

def test_scaling_xg90_scales_the_goals_component_proportionally():
    """🔴 TAMA ON KOKO MEKANISMIN OLEMASSAOLON SYY.

    `attack_delta` NAYTTI saataavan maaliodotusta mutta ei saatanyt: se
    supistuu pois `goal_mult`-suhteesta tasmalleen (mitattu 14.8, Osula
    1,09 -> 1,09). Uusi nuppi ei saa olla sama pettymys, joten tassa
    todistetaan ettei se ole: xg90:n puolittaminen puolittaa
    goals-komponentin.
    """
    ctx = {"goal_mult": 1.0, "cs_prob": 0.3,
           "conceded_dist": [0.3, 0.4, 0.3], "opp_goal_mult": 1.0}
    rates = {"xg90": 0.40, "xa90": 0.20, "saves90": 0.0,
             "yc90": 0.1, "bonus90": 0.3, "dc_freq": 0.0}
    full = xp.xp_components(2, rates, 90.0, 0.9, 0.05, ctx)
    half = xp.xp_components(2, dict(rates, xg90=0.20), 90.0, 0.9, 0.05, ctx)
    assert half["goals"] == pytest.approx(full["goals"] / 2.0)
    # ...eikä se saa vuotaa muihin komponentteihin.
    assert half["assists"] == pytest.approx(full["assists"])
    assert half["clean_sheet"] == pytest.approx(full["clean_sheet"])


def test_team_attack_delta_cannot_do_this_job():
    """NEGATIIVINEN KONTROLLI JOKA DOKUMENTOI MITATUN TOSIASIAN.

    `goal_mult = lam / lam_avg[t]`, ja lam_avg on saman joukkueen keskiarvo.
    Uniforminen attack-siirto kertoo molemmat exp(d):lla -> suhde sailyy 1.0
    -> goals ei liiku. Jos joku joskus tekee `goal_mult`:sta absoluuttisen,
    tama testi kaatuu ja pakottaa lukemaan miksi nykyinen mekanismi on
    olemassa.
    """
    ctx = {"goal_mult": 1.0, "cs_prob": 0.3,
           "conceded_dist": [0.3, 0.4, 0.3], "opp_goal_mult": 1.0}
    rates = {"xg90": 0.40, "xa90": 0.20, "saves90": 0.0,
             "yc90": 0.1, "bonus90": 0.3, "dc_freq": 0.0}
    base = xp.xp_components(2, rates, 90.0, 0.9, 0.05, ctx)
    # attack[t] += d kertoo seka lam:n etta lam_avg[t]:n -> goal_mult ennallaan
    shifted = xp.xp_components(2, rates, 90.0, 0.9, 0.05, dict(ctx, goal_mult=1.0))
    assert shifted["goals"] == pytest.approx(base["goals"])


def test_xg_mult_is_loaded_and_defaults_to_one(tmp_path):
    out, _ = load_player_overrides(
        _write(tmp_path, '379,Isak,0.85,"x",2026-10-01,\n'
                         '110,Rush,0.90,"y",2026-10-01,0.75\n'), today=TODAY)
    assert out[379]["xg_mult"] == 1.0
    assert out[110]["xg_mult"] == 0.75


def test_a_row_may_set_only_the_goal_threat(tmp_path):
    """Maaliuhkan saato ei saa pakottaa koskemaan minuutteihin. Thiaw aloittaa
    joka viikko; muuttunut asia on kulmasyotto, ei peliaika."""
    out, _ = load_player_overrides(
        _write(tmp_path, '445,Thiaw,,"x",2026-10-01,0.7\n'), today=TODAY)
    assert out[445]["p_start"] is None and out[445]["xg_mult"] == 0.7


def test_a_row_that_changes_nothing_is_rejected_loudly(tmp_path):
    """Rivi ilman p_startia ja ilman kerrointa nayttaisi voimassa olevalta
    ohitukselta tekematta mitaan."""
    out, warn = load_player_overrides(
        _write(tmp_path, '445,Thiaw,,"x",2026-10-01,\n'), today=TODAY)
    assert out == {} and any("ei aseta" in w for w in warn)


@pytest.mark.parametrize("bad", ["0.1", "3.0"])
def test_out_of_range_xg_mult_is_rejected(tmp_path, bad):
    """Kirjoitusvirhe (0.1 eika 1.0) ei saa pyyhkia pelaajan maaliuhkaa."""
    out, warn = load_player_overrides(
        _write(tmp_path, f'110,R,0.9,"x",2026-10-01,{bad}\n'), today=TODAY)
    assert out == {} and any("xg_mult" in w for w in warn)


# --------------------------------------------------------------------------
# review_by on nyt portti
# --------------------------------------------------------------------------

def test_expired_row_is_not_applied(tmp_path):
    out, warn = load_player_overrides(
        _write(tmp_path, '379,Isak,0.85,"x",2026-08-01,\n'), today=TODAY)
    assert out == {} and any("MENNYT" in w for w in warn)


def test_live_row_is_applied(tmp_path):
    """POSITIIVINEN KONTROLLI vanhentumisportille."""
    out, warn = load_player_overrides(
        _write(tmp_path, '379,Isak,0.85,"x",2026-10-01,\n'), today=TODAY)
    assert set(out) == {379} and warn == []


def test_missing_review_by_is_rejected(tmp_path):
    out, warn = load_player_overrides(
        _write(tmp_path, '379,Isak,0.85,"x",,\n'), today=TODAY)
    assert out == {} and any("review_by" in w for w in warn)


# --------------------------------------------------------------------------
# Lataus: rikkinainen rivi ei saa kaataa eika livahtaa lapi
# --------------------------------------------------------------------------

@pytest.mark.parametrize("bad", ["1.4", "-0.2"])
def test_out_of_range_p_start_is_dropped(tmp_path, bad):
    out, warn = load_player_overrides(
        _write(tmp_path, f'1,X,{bad},"x",2026-10-01,\n'), today=TODAY)
    assert out == {} and any("p_start" in w for w in warn)


def test_non_numeric_row_is_skipped_not_fatal(tmp_path):
    out, _ = load_player_overrides(
        _write(tmp_path, 'abc,X,0.5,"x",2026-10-01,\n'
                         '379,Isak,0.85,"y",2026-10-01,\n'), today=TODAY)
    assert set(out) == {379}


def test_missing_file_is_not_an_error(tmp_path):
    out, warn = load_player_overrides(tmp_path / "ei-ole.csv", today=TODAY)
    assert out == {} and warn == []


def test_comment_lines_are_ignored(tmp_path):
    p = tmp_path / "c.csv"
    p.write_text("# selitys\nplayer_id,web_name,p_start,reason,review_by,xg_mult\n"
                 '379,Isak,0.85,"x",2026-10-01,\n', encoding="utf-8")
    assert set(load_player_overrides(p, today=TODAY)[0]) == {379}


def test_old_five_column_rows_still_parse(tmp_path):
    """`xg_mult` lisattiin VIIMEISEKSI sarakkeeksi jotta vanhat rivit pysyvat
    koskemattomina. Jos joku siirtaa sen keskelle, reason ja review_by
    liukuvat sarakkeen verran ja rivit hylataan hiljaa."""
    p = tmp_path / "old.csv"
    p.write_text("player_id,web_name,p_start,reason,review_by,xg_mult\n"
                 '379,Isak,0.85,"x",2026-10-01\n', encoding="utf-8")
    out, warn = load_player_overrides(p, today=TODAY)
    assert set(out) == {379} and out[379]["xg_mult"] == 1.0 and warn == []


# --------------------------------------------------------------------------
# Shipatun CSV:n sisalto
# --------------------------------------------------------------------------

@pytest.mark.parametrize("field", ["reason", "review_by"])
def test_every_shipped_row_has_a_reason_and_a_review_date(field):
    """Ohitus ilman perustelua on kasisaato jota kukaan ei osaa myohemmin
    kumota."""
    for pid, ov in load_player_overrides()[0].items():
        assert ov[field], f"pelaaja {pid}: {field} puuttuu"

# --- until_available: rivi purkautuu kun pelaaja palaa (Villen kysymys 16.8)

def test_until_available_flag_is_parsed(tmp_path):
    """`until_available=1` merkitsee rivin ehdolliseksi. Ilman lippua rivi on
    ehdoton, koska varamiesrivit (Dubravka 0.08) ovat matalia siksi ettei
    pelaaja aloita, EIVAT siksi etta han olisi ulkona."""
    body = "\n".join([
        '1,Loukkaantunut,0.20,"syy",2099-01-01,,1',
        '2,Varamies,0.08,"syy",2099-01-01,,',
    ]) + "\n"
    out, warn = load_player_overrides(
        _write(tmp_path, body), today=_dt.date(2026, 8, 16))
    assert out[1]["until_available"] is True
    assert out[2]["until_available"] is False


def test_builder_releases_conditional_override_when_player_is_back():
    """🔴 Peilikuvavika. Ilman tata loukkaantumisen takia laskettu rivi jaisi
    voimaan paluun jalkeenkin ja ALIARVIOISI pelaajan.

    Ehto on sama looginen rajoite kuin vahdissa: rivi patee vain niin kauan
    kuin FPL sanoo pelaajan olevan poissa."""
    def released(status, chance, conditional):
        el = {"status": status, "chance_of_playing_next_round": chance}
        if not conditional:
            return False
        return el["status"] == "a" and (chance is None or chance >= 75)

    # ulkona -> ohitus patee
    assert released("i", 0, True) is False
    assert released("d", 25, True) is False
    # palannut -> ohitus purkautuu
    assert released("a", 100, True) is True
    assert released("a", None, True) is True
    # ehdoton rivi ei purkaudu koskaan saatavuuden perusteella
    assert released("a", 100, False) is False
