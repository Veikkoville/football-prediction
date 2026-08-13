"""FPL-autosub- ja kapteenisäännöt — testisetti VIRALLISISTA säännöistä.

Spec (BTM V2) nimeää autosub-gradauksen ainoaksi oikeasti virhealttiiksi
palaksi ja vaatii oman testisetin ENNEN ensimmäistä julkaistua lukua. Tämä
on se setti.

Pisteet ovat kaikilla ERI, jotta väärä kaava tuottaa eri summan: tasapisteinen
pooli läpäisisi myös rikkinäisen toteutuksen (28.7. mock-pooliopetus).
Perusjoukkue on 4-4-2, penkki järjestyksessä GK, DEF, MID, FWD.
"""
from __future__ import annotations

from src.models.fpl_autosub import (
    apply_autosubs,
    captain_multiplier,
    score_gw,
)

GK, DEF, MID, FWD = 1, 2, 3, 4


def _sq(xi_pos: list[int] | None = None) -> dict:
    """Jäädytetty rivi: XI 4-4-2 (id 1-11), penkki GK/DEF/MID/FWD (id 12-15)."""
    pos = xi_pos or [GK, DEF, DEF, DEF, DEF, MID, MID, MID, MID, FWD, FWD]
    xi = [{"id": i + 1, "pos": p} for i, p in enumerate(pos)]
    bench = [{"id": 12, "pos": GK}, {"id": 13, "pos": DEF},
             {"id": 14, "pos": MID}, {"id": 15, "pos": FWD}]
    return {"meta": {"gw": 1}, "xi": xi, "bench": bench,
            "captain": 10, "vice_captain": 6}


# Eri pistemäärä joka pelaajalla -> kaavavirhe näkyy summassa.
POINTS = {i: i for i in range(1, 16)}
ALL_PLAYED = {i: 90 for i in range(1, 16)}


def _mins(**over: int) -> dict[int, int]:
    m = dict(ALL_PLAYED)
    for k, v in over.items():
        m[int(k[1:])] = v          # p7=0 -> pelaaja 7 pelasi 0 min
    return m


# --- perustapaus ----------------------------------------------------------

def test_kaikki_pelasivat_ei_vaihtoja():
    final, subs = apply_autosubs(_sq()["xi"], _sq()["bench"], ALL_PLAYED)
    assert subs == []
    assert [p["id"] for p in final] == list(range(1, 12))


def test_perustapauksen_pisteet_kapteenilla():
    r = score_gw(_sq(), POINTS, ALL_PLAYED)
    # XI 1..11 = 66, kapteeni id 10 tuplaantuu -> +10
    assert r["points_before_captain"] == 66
    assert r["points"] == 76
    assert r["captain_reason"] == "captain"


# --- autosub-perussäännöt -------------------------------------------------

def test_pelaamaton_kenttapelaaja_korvataan_prioriteettijarjestyksessa():
    """Penkin ensimmäinen kenttäpelaaja (id 13, DEF) tulee 4-4-2:sta
    5-3-2:een — laillinen, joten hän ohittaa myöhemmät penkkiläiset."""
    final, subs = apply_autosubs(_sq()["xi"], _sq()["bench"], _mins(p7=0))
    assert [s["in"] for s in subs] == [13]
    assert subs[0]["out"] == 7
    assert 7 not in [p["id"] for p in final]


def test_pelaamaton_penkkilainen_ohitetaan():
    """id 13 ei pelannut -> seuraava pelannut (id 14) tulee tilalle."""
    _final, subs = apply_autosubs(_sq()["xi"], _sq()["bench"],
                                  _mins(p7=0, p13=0))
    assert [s["in"] for s in subs] == [14]


def test_yksi_minuutti_riittaa_eika_vaihtoa_tehda():
    """Sääntö on 0 minuuttia, EI 0 pistettä."""
    _final, subs = apply_autosubs(_sq()["xi"], _sq()["bench"], _mins(p7=1))
    assert subs == []


def test_korkeintaan_kolme_kenttavaihtoa():
    """Penkillä on 3 kenttäpelaajaa -> neljäs blank jää korvaamatta."""
    final, subs = apply_autosubs(
        _sq()["xi"], _sq()["bench"], _mins(p6=0, p7=0, p8=0, p9=0))
    assert len(subs) == 3
    assert len(final) == 11
    # yksi pelaamaton jäi kentälle
    assert len([p for p in final if p["id"] in (6, 7, 8, 9)]) == 1


# --- muodostelmavahti -----------------------------------------------------

def test_muodostelma_estaa_laittoman_vaihdon():
    """3-5-2: yksi DEF blank. Penkin DEF (13) korjaisi asian, mutta jos hän
    ei pelannut, MID/FWD veisi puolustuksen kahteen -> ei vaihtoa."""
    sq = _sq([GK, DEF, DEF, DEF, MID, MID, MID, MID, MID, FWD, FWD])
    _final, subs = apply_autosubs(sq["xi"], sq["bench"], _mins(p2=0, p13=0))
    assert subs == []


def test_muodostelma_sallii_kun_penkilta_loytyy_sama_positio():
    """Sama tilanne, mutta penkin DEF pelasi -> vaihto tehdään."""
    sq = _sq([GK, DEF, DEF, DEF, MID, MID, MID, MID, MID, FWD, FWD])
    _final, subs = apply_autosubs(sq["xi"], sq["bench"], _mins(p2=0))
    assert [s["in"] for s in subs] == [13]


def test_viimeinen_hyokkaaja_ei_saa_kadota():
    """3-4-3 -> jos ainoa FWD blankkaisi ja vain DEF/MID penkillä pelasi,
    FWD-minimi 1 estäisi vaihdon. Tässä 4-5-1: ainoa FWD id 11 blank,
    penkin DEF ja MID pelasivat mutta FWD ei."""
    sq = _sq([GK, DEF, DEF, DEF, DEF, MID, MID, MID, MID, MID, FWD])
    _final, subs = apply_autosubs(sq["xi"], sq["bench"], _mins(p11=0, p15=0))
    assert subs == []


# --- maalivahtisääntö -----------------------------------------------------

def test_maalivahti_vaihtuu_kun_molemmat_ehdot_tayttyvat():
    final, subs = apply_autosubs(_sq()["xi"], _sq()["bench"], _mins(p1=0))
    assert subs == [{"out": 1, "in": 12, "pos": GK}]
    assert 12 in [p["id"] for p in final]


def test_maalivahti_ei_vaihdu_jos_penkin_gk_ei_pelannut():
    _final, subs = apply_autosubs(_sq()["xi"], _sq()["bench"],
                                  _mins(p1=0, p12=0))
    assert subs == []


def test_penkin_maalivahti_ei_korvaa_kenttapelaajaa():
    """Kenttäpelaaja blank, GK pelasi normaalisti -> penkin GK ei tule.

    MITTAA LOPPUTULOSTA, EI MEKANISMIA (mitattu mutaatiotestillä 13.8):
    koodin `pos != GK` -suodatin on kaksinkertaista varmistusta — sen
    poistaminen ei kaada yhtään testiä, koska muodostelmasääntö (max 1 GK)
    estää toisen maalivahdin joka tapauksessa. Tapausta jossa suodatin olisi
    sitova ei ole olemassa: XI:ssä on aina tasan yksi maalivahti.
    Jos muodostelmatarkistusta joskus kevennetään, TÄMÄ on se testi joka ei
    enää suojaa mitään — lisää silloin suora tarkistus.
    """
    _final, subs = apply_autosubs(_sq()["xi"], _sq()["bench"], _mins(p7=0))
    assert 12 not in [s["in"] for s in subs]


def test_kenttapelaaja_ei_korvaa_maalivahtia():
    """GK blank ja penkin GK blank -> kukaan muu ei saa tulla maaliin."""
    _final, subs = apply_autosubs(_sq()["xi"], _sq()["bench"],
                                  _mins(p1=0, p12=0))
    assert all(s["pos"] != GK for s in subs)


# --- kapteenisääntö -------------------------------------------------------

def test_kapteeni_pelasi_tuplaantuu():
    assert captain_multiplier(10, 6, ALL_PLAYED) == (10, "captain")


def test_kapteeni_ei_pelannut_armband_varakapteenille():
    assert captain_multiplier(10, 6, _mins(p10=0)) == (6, "vice")


def test_kumpikaan_ei_pelannut_ei_kaksinkertaistusta():
    assert captain_multiplier(10, 6, _mins(p10=0, p6=0)) == (None, "none")


def test_armband_ei_siirry_vaihtopelaajalle():
    """Kapteeni (10) ja vara (6) molemmat blank, vaihdot tehdään silti —
    mutta kentälle tullut ei saa kaksinkertaistusta."""
    r = score_gw(_sq(), POINTS, _mins(p10=0, p6=0))
    assert r["captain_id"] is None
    assert r["captain_points_added"] == 0
    assert r["points"] == r["points_before_captain"]


def test_kapteenin_tuplaus_lasketaan_varakapteenin_pisteista():
    """Numeroilla: kapteeni 10 blank -> vara id 6 (6 p) tuplaantuu.
    Väärä toteutus (tuplaa yhä kapteenin 10 p) antaisi eri summan."""
    r = score_gw(_sq(), POINTS, _mins(p10=0))
    # id 10 ulos, id 13 (DEF) sisään: 66 - 10 + 13 = 69; vara 6 -> +6
    assert r["points_before_captain"] == 69
    assert r["captain_id"] == 6
    assert r["captain_points_added"] == 6
    assert r["points"] == 75


# --- kokonaisuus ----------------------------------------------------------

def test_penkkipisteet_laskee_vain_kentalle_jaaneet():
    r = score_gw(_sq(), POINTS, _mins(p7=0))
    # id 13 tuli kentälle -> penkille jäi 12, 14, 15 = 41
    assert r["bench_points"] == 12 + 14 + 15


def test_tulos_sisaltaa_vaihdot_erittelya_varten():
    r = score_gw(_sq(), POINTS, _mins(p7=0))
    assert r["autosubs"] == [{"out": 7, "in": 13, "pos": DEF}]
    assert r["gw"] == 1
    assert len(r["xi_ids"]) == 11
