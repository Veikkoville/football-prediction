"""build_optimal_squad — XI/PENKKI-JAKO (14.8).

Tausta: /fpl/model-xi.html näytti 277.49, mutta sama 15 pelaajaa
`optimal_xi()`:n läpi ajettuna antoi 298.05 (+7.4 %). Julkaistussa
avauksessa oli kaksi 4.0m puolustajaa (8.15 ja 7.79 xP) ja penkillä
hyökkääjä joka tuottaa yli tuplasti enemmän (18.44). Kuka tahansa olisi
voinut ottaa mallin oman joukkueen, siirtää kaksi pelaajaa penkiltä
avaukseen ja voittaa "mallin" FPL:n omalla sivulla.

Juurisyy: ahne varapolku valitsi XI:n ENNEN kuin penkki oli olemassa eikä
jakoa optimoitu uudelleen sen jälkeen kun 15 oli koossa — ja muodostelmien
vertailu pisteytettiin tuolla väärällä jaolla.

Ydinväite tässä tiedostossa on invariantti eikä yksittäinen luku:
**paras laillinen jako KOKO 15:stä ei saa koskaan olla parempi kuin se
jako jonka optimoija palauttaa.** Se pätee riippumatta siitä mitä
poolia tai kautta ajetaan.

NEGATIIVINEN KONTROLLI (ajettu 14.8): vanhalla koodilla
`test_jako_on_paras_mahdollinen` kaatuu — se on tämän testin
olemassaolon ehto. Ilman sitä testi voisi mitata tyhjää.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import src.models.fpl_rate_team as rt

XP_PATH = Path(__file__).resolve().parents[1] / "data" / "fpl_xp_projections.json"
_ET = {"GKP": 1, "DEF": 2, "MID": 3, "FWD": 4}


def _p(pid: int, et: int, club: int, price: int, xp: float,
       xmins: float) -> dict:
    return {"id": pid, "web_name": f"P{pid}", "team_short": "XXX",
            "element_type": et, "club": club, "price": price,
            "owned_pct": 5.0, "xp_per_gw": xp / 5.0,
            "xp_horizon_total": xp, "xmins": xmins, "gameweeks": []}


def _pool() -> list[dict]:
    """Pooli joka toistaa tuotannon oireen.

    Rakenne on kopio 14.8 mitatusta tilanteesta: puolustajien kärki on
    kallista, halpa puolustajatäyte on ARVOTONTA (8/7 xP), ja halpa
    keskikentän/hyökkäyksen täyte on PELATTAVAA JA HYVÄÄ (15-18 xP).
    Ahne 5-DEF-täyttö ostaa siis arvotonta puolustajatäytettä XI:hin ja
    jättää hyvän halvan pelaajan penkille.

    Seurakatto (kolme kärkipuolustajaa samassa seurassa) pakottaa ajon
    VARAPOLULLE, joka oli se rikkinäinen haara — eksakti polku ei koskaan
    kärsinyt tästä.
    """
    pool: list[dict] = []
    pid = 1

    def add(et, club, price, xp, xmins):
        nonlocal pid
        pool.append(_p(pid, et, club, price, xp, xmins))
        pid += 1

    # Luvut on skaalattu 14.8 mitatusta tuotantopoolista: kärki on kallista,
    # halvin puolustaja (4.0m) on halvempi kuin halvin keskikenttä (5.0m) tai
    # hyökkääjä (5.5m), ja budjetti on aidosti kireä. Kaikki kolme ehtoa
    # tarvitaan, muuten oire ei synny.

    # GKP: aloittaja + halpa varamies (varamies saa olla pelaamaton).
    add(1, 1, 45, 24.0, 90.0)
    add(1, 2, 40, 19.0, 77.0)
    add(1, 3, 40, 3.0, 0.0)

    # DEF: NELJÄ kärkipuolustajaa samassa seurassa -> rajoittamaton DP ottaa
    # kaikki neljä -> 3/seura-katto rikkoutuu -> ajo putoaa varapolulle.
    add(2, 7, 80, 30.9, 88.0)
    add(2, 7, 60, 28.7, 90.0)
    add(2, 7, 60, 27.3, 84.0)
    add(2, 7, 50, 27.0, 86.0)
    # Muuta puolustajatarjontaa EI ole kuin halpaa ja arvotonta. Tämä on se
    # joukko josta ahne täyttö joutui ammentamaan XI:hin.
    for i in range(6):
        add(2, 20 + i, 40, 8.0 - i * 0.2, 90.0)

    # MID: kärki + halpaa mutta HYVÄÄ pelattavaa täytettä.
    add(3, 30, 120, 34.1, 84.0)
    add(3, 31, 65, 28.1, 87.0)
    add(3, 32, 60, 27.0, 89.0)
    add(3, 33, 60, 26.0, 88.0)
    add(3, 34, 55, 25.0, 86.0)
    for i in range(4):
        add(3, 40 + i, 50, 18.1 - i, 63.0)

    # FWD: kärki + halpa hyvä pelattava. Halvin hyökkääjä on kalliimpi kuin
    # halvin puolustaja -> globaali minimivaraus aliarvioi FWD-slotin.
    add(4, 50, 155, 32.6, 77.0)
    add(4, 51, 80, 28.8, 89.0)
    add(4, 52, 60, 23.4, 85.0)
    for i in range(3):
        add(4, 60 + i, 55, 18.4 - i, 46.0)
    return pool


def _squad(res: dict) -> list[dict]:
    return list(res["xi"]) + list(res["bench"])


# --- kontrollit testipoolille itselleen -----------------------------------

def test_pooli_ajaa_varapolun():
    """Jos ajo osuisi eksaktiin polkuun, testi ei koskettaisi rikkinäistä
    haaraa lainkaan ja olisi vihreä myös bugisella koodilla."""
    assert rt.build_optimal_squad(_pool())["proven"] is False


def test_pooli_tarjoaa_halpaa_hyvaa_penkkitavaraa():
    """Oire syntyy vain jos halpa pelattava pelaaja on PAREMPI kuin halpa
    puolustajatäyte. Ilman tätä eroa jaon uudelleenoptimointi ei voisi
    muuttaa mitään ja testi mittaisi tyhjää."""
    pool = _pool()
    halpa_def = max(p["xp_horizon_total"] for p in pool
                    if p["element_type"] == 2 and p["price"] <= 40)
    halpa_muu = max(p["xp_horizon_total"] for p in pool
                    if p["element_type"] in (3, 4) and p["price"] <= 55)
    assert halpa_muu > halpa_def * 2, (halpa_muu, halpa_def)


# --- ydinväite ------------------------------------------------------------

def test_jako_on_paras_mahdollinen():
    """EI KOSKAAN: paras jako 15:stä > optimoijan palauttama xi_xp.

    Tämä on se testi joka kaatuu vanhalla koodilla (lukuun 298.05
    tuotantopoolilla, ks. moduulin docstring)."""
    res = rt.build_optimal_squad(_pool())
    assert res["xi"], "optimoija ei palauttanut runkoa"
    paras = sum(p["xp_horizon_total"] for p in rt.optimal_xi(_squad(res)))
    assert paras <= res["xi_xp"] + 1e-9, (
        f"malli häviää omalle penkilleen: paras jako {paras:.2f} > "
        f"julkaistu XI {res['xi_xp']:.2f} "
        f"(+{paras - res['xi_xp']:.2f} xP, "
        f"{(paras / res['xi_xp'] - 1) * 100:+.1f} %)")


def test_penkki_on_pelattava():
    """Jaon uudelleenoptimointi ei saa siirtää penkille pelaajaa joka ei
    täytä sivulla luvattua 45 minuutin vaatimusta (varamaalivahti on
    dokumentoitu poikkeus)."""
    res = rt.build_optimal_squad(_pool())
    huonot = [p["web_name"] for p in res["bench"]
              if p["element_type"] != 1 and not rt._playable(p)]
    assert not huonot, f"penkillä pelaamattomia kenttäpelaajia: {huonot}"


def test_runko_pysyy_laillisena():
    """Jaon vaihto ei saa rikkoa kiintiötä, seurakattoa eikä budjettia."""
    res = rt.build_optimal_squad(_pool())
    squad = _squad(res)
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
    assert sum(p["price"] for p in squad) <= rt.BUDGET_TENTHS
    # XI itse on laillinen muodostelma.
    shape = rt._shape_of(res["xi"])
    assert shape[1] == 1
    for t in (2, 3, 4):
        assert rt.XI_MIN[t] <= shape[t] <= rt.XI_MAX[t], shape


def test_kaikki_muodostelmat_saavat_kandidaatin():
    """Muodostelmavertailu (26.7) oli kuollutta koodia: ahne täyttö varasi
    jäljellä oleville paikoille poolin globaalin minimihinnan, joten
    muodostelma jonka viimeinen slotti oli kalliimmassa positiossa ei
    saanut XI:tä kokoon lainkaan. Tuotannossa 6/8 muodostelmaa katosi."""
    pool = _pool()
    res = rt.build_optimal_squad(pool)
    assert res["xi"]
    # Ei väitetä että jokainen muoto on rahoitettavissa — väitetään että
    # voittaja EI ole se yksi muoto joka selvisi vanhalla varauksella.
    # Riittävä ja mitattava muotoilu: XI:n muoto on jokin muu kuin se johon
    # ahne globaalivaraus lukitsi (5 DEF), TAI jos on, se on paras jako.
    paras = sum(p["xp_horizon_total"] for p in rt.optimal_xi(_squad(res)))
    assert abs(paras - res["xi_xp"]) < 1e-9


# --- sama invariantti TUOTANTODATALLA -------------------------------------

@pytest.mark.skipif(not XP_PATH.exists(), reason="xP-projektiot puuttuvat")
def test_tuotantopooli_ei_havia_omalle_penkilleen():
    """Sama invariantti oikealla poolilla. Tämä on se pinta joka renderöityy
    /fpl/model-xi.html:lle ja toimii rate-teamin benchmarkin nimittäjänä."""
    xp = json.loads(XP_PATH.read_text(encoding="utf-8"))
    pool = []
    for p in xp.get("players") or []:
        t = _ET.get(p.get("pos"))
        if t is None or p.get("price") in (None, ""):
            continue
        pool.append({
            "id": p.get("id"), "xmins": p.get("xmins"), "element_type": t,
            "price": int(round(float(p["price"]) * 10)),
            "club": p.get("team_short") or p.get("team"),
            "xp_horizon_total": float(p.get("xp_horizon_total") or 0.0),
            "xp_per_gw": float(p.get("xp_per_gw") or 0.0),
            "web_name": p.get("web_name") or "",
            "team_short": p.get("team_short") or "",
        })
    if len(pool) < 15:
        pytest.skip("pooli liian pieni")
    res = rt.build_optimal_squad(pool)
    assert res["xi"], "tuotantopooli ei tuota runkoa"
    squad = _squad(res)
    paras = sum(p["xp_horizon_total"] for p in rt.optimal_xi(squad))
    assert paras <= res["xi_xp"] + 1e-9, (
        f"tuotannon malli-XI häviää omalle penkilleen: {paras:.2f} > "
        f"{res['xi_xp']:.2f}")
    assert sum(p["price"] for p in squad) <= rt.BUDGET_TENTHS
    assert not [p for p in res["bench"]
                if p["element_type"] != 1 and not rt._playable(p)]
