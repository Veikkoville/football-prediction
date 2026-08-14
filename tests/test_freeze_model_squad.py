"""Beat the Model V2 vaihe a — freeze_model_squad_gw puhtaat ytimet.

Ei verkkoa eikä levyä: kaikki testattava logiikka on funktioina joille
syötetään pooli. Arvot ovat tarkoituksella ERISUURIA, jotta väärä kaava
tuottaa eri tuloksen — homogeeninen pooli läpäisisi myös rikkinäisen
toteutuksen (28.7. mock-pooliopetus, ks. test_fpl_grade.py).

Laillisuusvahdilla on oma negatiivinen kontrolli: 12.8 julkaistiin laiton
model squad koska mikään portti ei mitannut seurakattoa. Jokainen rike
testataan erikseen JA todistetaan että sama runko ilman rikettä menee läpi
— muuten testi voisi olla vihreä väärästä syystä.
"""
from __future__ import annotations

import datetime as _dt

from scripts.freeze_model_squad_gw import (
    gw_xp,
    next_freeze_gw,
    order_bench,
    pick_captain,
    validate_squad,
)

GW = 1


def P(pid: int, et: int, club: int, price: int = 50,
      xp_gw: float = 1.0, xp_other: float = 0.0) -> dict:
    """Poolirivi: xp_gw on GW1:lle, xp_other GW2:lle (horisonttiharhan testiin)."""
    return {"id": pid, "web_name": f"P{pid}", "team_short": "XXX",
            "element_type": et, "club": club, "price": price,
            "gameweeks": [{"gw": 1, "xp": xp_gw}, {"gw": 2, "xp": xp_other}]}


def legal_squad() -> tuple[list[dict], list[dict]]:
    """Laillinen 15: 2/5/5/3, max 3/seura, 90.0m. XI = 1 GK, 4 DEF, 4 MID, 2 FWD."""
    xi = [
        P(1, 1, 10, xp_gw=2.0),
        P(2, 2, 10, xp_gw=3.0), P(3, 2, 10, xp_gw=4.0),
        P(4, 2, 11, xp_gw=5.0), P(5, 2, 11, xp_gw=6.0),
        P(6, 3, 11, xp_gw=7.0), P(7, 3, 12, xp_gw=8.0),
        P(8, 3, 12, xp_gw=9.0), P(9, 3, 12, xp_gw=10.0),
        P(10, 4, 13, xp_gw=11.0), P(11, 4, 13, xp_gw=12.0),
    ]
    bench = [
        P(12, 1, 13, xp_gw=0.5),   # penkin GK
        P(13, 2, 14, xp_gw=1.5),
        P(14, 3, 14, xp_gw=2.5),
        P(15, 4, 14, xp_gw=3.5),
    ]
    return xi, bench


# --- laillisuusvahti -------------------------------------------------------

def test_laillinen_runko_lapaisee():
    xi, bench = legal_squad()
    assert validate_squad(xi, bench) == []


def test_seurakatto_rike_havaitaan():
    """12.8:n bugi: neljä samasta seurasta. Sama runko ilman riketta läpäisi yllä."""
    xi, bench = legal_squad()
    bench[1]["club"] = 10          # seurasta 10 tulee 4 pelaajaa
    problems = validate_squad(xi, bench)
    assert any("yli 3/seura" in p for p in problems), problems


def test_seurakatto_rike_myos_kokonaan_penkilla():
    """Kattorike voi olla pelkästään penkillä — XI:n tarkistus ei riitä."""
    xi, bench = legal_squad()
    for b in bench[1:]:
        b["club"] = 14
    bench[0]["club"] = 14          # 4 pelaajaa seurasta 14, kaikki penkillä
    problems = validate_squad(xi, bench)
    assert any("yli 3/seura" in p for p in problems), problems


def test_budjetin_ylitys_havaitaan():
    xi, bench = legal_squad()
    xi[0]["price"] = 900           # 15 x 50 = 750 -> 1600 kymmenyksiä
    problems = validate_squad(xi, bench)
    assert any("yli 100.0m" in p for p in problems), problems


def test_positiojakauman_rike_havaitaan():
    xi, bench = legal_squad()
    xi[1]["element_type"] = 3      # DEF -> MID: 4 DEF / 6 MID
    problems = validate_squad(xi, bench)
    assert any("positiojakauma" in p for p in problems), problems


def test_sama_pelaaja_kahdesti_havaitaan():
    xi, bench = legal_squad()
    bench[3] = dict(xi[10])        # duplikaatti FWD
    problems = validate_squad(xi, bench)
    assert any("kahdesti" in p for p in problems), problems


def test_vajaa_runko_havaitaan():
    xi, bench = legal_squad()
    problems = validate_squad(xi, bench[:3])
    assert any("14 pelaajaa" in p for p in problems), problems


# --- kapteenivalinta -------------------------------------------------------

def test_kapteeni_on_kierroksen_paras_ei_horisontin():
    """Ratkaiseva testi: id 2:lla on surkea GW1 mutta valtava GW2.

    Horisonttisummalla hän olisi kapteeni (3.0 + 99.0), kierroskohtaisesti
    ei ole lähelläkään. Väärä toteutus tuottaa siis ERI tuloksen.
    """
    xi, _ = legal_squad()
    xi[1]["gameweeks"] = [{"gw": 1, "xp": 3.0}, {"gw": 2, "xp": 99.0}]
    cap, _vice = pick_captain(xi, GW)
    assert cap["id"] == 11         # 12.0 GW1:ssä, ei id 2


def test_varakapteeni_on_toiseksi_paras():
    xi, _ = legal_squad()
    cap, vice = pick_captain(xi, GW)
    assert (cap["id"], vice["id"]) == (11, 10)   # 12.0 ja 11.0


def test_kapteenin_tasapeli_ratkeaa_deterministisesti():
    """Freeze on todiste — sama pooli ei saa tuottaa eri riviä eri ajolla."""
    xi, _ = legal_squad()
    xi[9]["gameweeks"] = [{"gw": 1, "xp": 12.0}, {"gw": 2, "xp": 0.0}]
    cap, vice = pick_captain(xi, GW)
    assert (cap["id"], vice["id"]) == (10, 11)   # sama xP -> pienempi id ensin
    assert pick_captain(list(reversed(xi)), GW)[0]["id"] == 10


# --- penkkijärjestys -------------------------------------------------------

def test_penkin_gk_on_aina_ensimmainen():
    """Autosub kohtelee penkin GK:ta erikseen, joten hän ei kilpaile xP:llä."""
    _xi, bench = legal_squad()
    bench[0]["gameweeks"] = [{"gw": 1, "xp": 99.0}, {"gw": 2, "xp": 0.0}]
    assert order_bench(bench, GW)[0]["id"] == 12
    bench[0]["gameweeks"] = [{"gw": 1, "xp": 0.0}, {"gw": 2, "xp": 0.0}]
    assert order_bench(bench, GW)[0]["id"] == 12   # myös huonoimpana


def test_kenttapelaajat_xp_laskevasti():
    _xi, bench = legal_squad()
    order = [p["id"] for p in order_bench(bench, GW)]
    assert order == [12, 15, 14, 13]   # 3.5 > 2.5 > 1.5


def test_penkkijarjestys_kayttaa_kierroksen_xp():
    _xi, bench = legal_squad()
    bench[1]["gameweeks"] = [{"gw": 1, "xp": 9.0}, {"gw": 2, "xp": 0.0}]
    assert [p["id"] for p in order_bench(bench, GW)] == [12, 13, 15, 14]


# --- xP-poiminta ja freeze-ikkuna ------------------------------------------

def test_gw_xp_palauttaa_nollan_puuttuvalle_kierrokselle():
    assert gw_xp(P(1, 3, 10, xp_gw=5.0), 38) == 0.0


NOW = _dt.datetime(2026, 8, 20, 12, 0, tzinfo=_dt.timezone.utc)


def _ev(gw: int, when: str, finished: bool = False) -> dict:
    return {"id": gw, "deadline_time": when, "finished": finished}


def test_freeze_ikkuna_osuu_alle_30h_paassa():
    evs = [_ev(1, "2026-08-21T17:30:00Z")]        # +29,5 h
    assert next_freeze_gw(evs, NOW) is not None
    assert next_freeze_gw(evs, NOW)[0] == 1


def test_freeze_ikkuna_ei_osu_yli_30h_paassa():
    evs = [_ev(1, "2026-08-22T12:00:00Z")]        # +48 h
    assert next_freeze_gw(evs, NOW) is None


def test_freeze_ohittaa_paattyneet_kierrokset():
    evs = [_ev(1, "2026-08-20T18:00:00Z", finished=True),
           _ev(2, "2026-08-21T10:00:00Z")]
    assert next_freeze_gw(evs, NOW)[0] == 2


def test_freeze_ei_osu_menneeseen_deadlineen():
    evs = [_ev(1, "2026-08-20T11:00:00Z")]        # jo mennyt, ei finished
    assert next_freeze_gw(evs, NOW) is None


# --- optimaalisuusvahti (14.8) --------------------------------------------

def _horizon(xi: list[dict], bench: list[dict],
             xi_xp: list[float], bench_xp: list[float]) -> None:
    """Lisää horisontti-xP:t paikan päällä; ilman niitä vahti ohittaa."""
    for p, v in zip(xi, xi_xp):
        p["xp_horizon_total"] = v
    for p, v in zip(bench, bench_xp):
        p["xp_horizon_total"] = v


def test_optimaalisuusvahti_ei_valita_parhaasta_jaosta():
    """Kontrolli: kun jako on jo paras, vahti on hiljaa."""
    xi, bench = legal_squad()
    _horizon(xi, bench, [30.0] * 11, [5.0] * 4)
    assert validate_squad(xi, bench) == []


def test_optimaalisuusvahti_havaitsee_penkille_haviavan_xin():
    """14.8:n oire: laillinen runko jonka penkillä on XI:tä parempi pelaaja.

    Ilman tätä vahtia freeze olisi lukinnut sen koko kaudeksi immutablena.
    """
    xi, bench = legal_squad()
    # XI:n heikoin on hyökkääjä 4.0; penkillä on hyökkääjä 25.0 -> sama
    # muodostelma paremmalla jaolla tuottaa enemmän.
    _horizon(xi, bench,
             [30.0, 30.0, 30.0, 30.0, 30.0, 30.0, 30.0, 30.0, 30.0, 30.0, 4.0],
             [1.0, 1.0, 1.0, 25.0])
    problems = validate_squad(xi, bench)
    assert any("häviää omalle penkilleen" in p for p in problems), problems


def test_optimaalisuusvahti_ohitetaan_ilman_horisonttilukuja():
    """Eksplisiittinen ohitus: kevyt poolirivi ei saa kaataa vahtia
    KeyErroriin eikä toisaalta teeskennellä tarkistaneensa."""
    xi, bench = legal_squad()
    assert all("xp_horizon_total" not in p for p in xi + bench)
    assert validate_squad(xi, bench) == []
