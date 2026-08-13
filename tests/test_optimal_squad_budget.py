"""build_optimal_squad — 15 pelaajan KOKONAISBUDJETTI (13.8).

Tausta: tuotannossa /api/fantasy/model-squad tarjosi 101.5m rungon, jota ei
voi omistaa (mitattu livenä 13.8). Syy: XI-budjetti varattiin KAIKKIEN
muodostelmien halvimmalla pelattavalla penkillä, mutta valittu muodostelma
saattoi vaatia kalliimman penkin — eikä lopullista 15:tä punnittu missään.
Eksakti polku tarkisti kokonaishinnan, varapolku (klubikatto sitoo) ei.

Testipooli on rakennettu niin, että halvin pelattava penkki ERIÄÄ
muodostelmittain (DEF-fodder on halpaa ja pelattavaa, MID/FWD-fodder ei
ole), ja klubikatto pakottaa varapolulle. Homogeeninen pooli ei paljastaisi
tätä lainkaan: siinä kaikkien muotojen penkki maksaa saman verran, jolloin
globaali varaus sattuu olemaan oikea.
"""
from __future__ import annotations

import src.models.fpl_rate_team as rt


def _p(pid: int, et: int, club: int, price: int, xp: float,
       xmins: float) -> dict:
    return {"id": pid, "web_name": f"P{pid}", "team_short": "XXX",
            "element_type": et, "club": club, "price": price,
            "owned_pct": 5.0, "xp_per_gw": xp / 6.0,
            "xp_horizon_total": xp, "xmins": xmins, "gameweeks": []}


def _pool() -> list[dict]:
    pool: list[dict] = []
    pid = 1

    def add(et, club, price, xp, xmins):
        nonlocal pid
        pool.append(_p(pid, et, club, price, xp, xmins))
        pid += 1

    # GK: penkin GK saa olla pelaamaton (tietoinen poikkeus _playablessa).
    add(1, 1, 55, 30.0, 90.0)
    add(1, 2, 50, 26.0, 90.0)
    add(1, 3, 40, 2.0, 0.0)      # halvin penkki-GK
    add(1, 4, 40, 2.0, 0.0)

    # DEF: neljä ylivoimaista huippua SAMASSA seurassa (7). Hinta/xP on niin
    # dominoiva, että rajoittamaton DP ottaa kaikki neljä -> 3/seura-katto
    # rikkoutuu -> ajo putoaa varapolulle, joka oli se rikkinäinen haara.
    for i in range(4):
        add(2, 7, 50, 100.0 - i, 90.0)
    for i in range(4):
        add(2, 20 + i, 75, 55.0 - i, 90.0)
    # Halpaa PELATTAVAA DEF-fodderia -> 3-DEF-muodon penkki on halpa.
    for i in range(6):
        add(2, 30 + i, 40, 6.0, 90.0)

    # MID: halvin PELATTAVA on 50 (40-fodder ei pelaa -> ei kelpaa penkille).
    for i in range(6):
        add(3, 40 + i, 90, 40.0 - i, 90.0)
    for i in range(6):
        add(3, 50 + i, 50, 8.0, 90.0)
    for i in range(4):
        add(3, 60 + i, 40, 1.0, 0.0)     # halpa mutta pelaamaton

    # FWD: halvin PELATTAVA on 55.
    for i in range(4):
        add(4, 70 + i, 95, 45.0 - i, 90.0)
    for i in range(4):
        add(4, 80 + i, 55, 7.0, 90.0)
    for i in range(4):
        add(4, 90 + i, 45, 1.0, 0.0)     # halpa mutta pelaamaton
    return pool


def _cost(players: list[dict]) -> int:
    return sum(p["price"] for p in players)


def test_pooli_erottaa_muodostelmien_penkkihinnat():
    """Kontrolli testipoolille itselleen: jos penkkihinnat eivät eroa
    muodostelmittain, koko regressiotesti mittaisi tyhjää."""
    pool = _pool()
    b_5def = rt._bench_for_shape(pool, {1: 1, 2: 5, 3: 3, 4: 2}, set())[1]
    b_3def = rt._bench_for_shape(pool, {1: 1, 2: 3, 3: 5, 4: 2}, set())[1]
    assert b_5def > b_3def, (b_5def, b_3def)


def test_runko_mahtuu_budjettiin():
    """Ydinväite: 15 pelaajaa ei saa maksaa yli 100.0m."""
    res = rt.build_optimal_squad(_pool())
    squad = list(res["xi"]) + list(res["bench"])
    assert squad, "optimoija ei palauttanut runkoa"
    assert _cost(squad) <= rt.BUDGET_TENTHS, (
        f"runko {_cost(squad) / 10:.1f}m > 100.0m: "
        f"XI {_cost(res['xi']) / 10:.1f}m + penkki "
        f"{_cost(res['bench']) / 10:.1f}m")


def test_runko_on_muutenkin_laillinen():
    """Budjettikorjaus ei saa rikkoa kiintiötä tai seurakattoa."""
    res = rt.build_optimal_squad(_pool())
    squad = list(res["xi"]) + list(res["bench"])
    assert len(squad) == 15
    assert len({p["id"] for p in squad}) == 15
    pos: dict[int, int] = {}
    for p in squad:
        pos[p["element_type"]] = pos.get(p["element_type"], 0) + 1
    assert pos == rt.SQUAD_QUOTA
    clubs: dict[int, int] = {}
    for p in squad:
        clubs[p["club"]] = clubs.get(p["club"], 0) + 1
    assert max(clubs.values()) <= rt.MAX_PER_CLUB


def test_varapolku_oli_se_joka_ajettiin():
    """Todiste että testi kattaa RIKKINÄISEN haaran eikä eksaktia polkua.

    Eksakti polku tarkisti kokonaishinnan jo ennen korjausta, joten testi
    joka osuu siihen olisi ollut vihreä myös bugisella koodilla.
    """
    res = rt.build_optimal_squad(_pool())
    assert res["proven"] is False


def test_free_optimum_palauttaa_saman_laillisen_rungon():
    """Julkinen polku (/api/fantasy/model-squad, rate-team-benchmark) käyttää
    tätä käärettä — välimuisti ei saa säilöä laitonta runkoa."""
    pool = _pool()
    res = rt.free_optimum(pool, "budget-test-key")
    squad = list(res["xi"]) + list(res["bench"])
    assert _cost(squad) <= rt.BUDGET_TENTHS
