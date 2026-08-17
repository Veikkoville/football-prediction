"""#155 fit-checker -testit: laillisuus, lukitus, delta, validoinnit.

Hermeettinen: uudelleenkäyttää test_fpl_rate_team-fixturet (sama mock-pooli,
sama monkeypatch-kohde rt-moduulissa — fpl_fit lukee poolin build_contextin
kautta).
"""
from __future__ import annotations

import pytest

import src.models.fpl_rate_team as rt
from src.models.fpl_fit import fit_squad
from tests.test_fpl_rate_team import FAKE_BOOTSTRAP, FAKE_XP


@pytest.fixture(autouse=True)
def _mock_fpl(monkeypatch):
    def fake_fetch(path):
        if path == "/bootstrap-static/":
            return FAKE_BOOTSTRAP
        raise rt.RateTeamError(404, "Not found on the FPL API.")

    monkeypatch.setattr(rt, "_fetch_fpl", fake_fetch)
    monkeypatch.setattr(rt, "load_xp", lambda: FAKE_XP)
    rt._OPTIMAL_XP_CACHE.clear()
    rt._FPL_CACHE.clear()
    yield
    rt._OPTIMAL_XP_CACHE.clear()
    rt._FPL_CACHE.clear()


def _assert_legal_squad(out):
    squad = out["xi"] + out["bench"]
    assert len(out["xi"]) == 11
    assert len(out["bench"]) == 4
    # Runkokiintiöt tasan 2/5/5/3
    by_pos = {}
    for p in squad:
        by_pos[p["pos"]] = by_pos.get(p["pos"], 0) + 1
    assert by_pos == {"GKP": 2, "DEF": 5, "MID": 5, "FWD": 3}
    # Max 3 / klubi
    clubs = {}
    for p in squad:
        clubs[p["team_short"]] = clubs.get(p["team_short"], 0) + 1
    assert max(clubs.values()) <= 3
    # Budjetti
    assert out["meta"]["squad_cost"] <= out["meta"]["budget_cap"]
    # Ei duplikaatteja
    ids = [p["id"] for p in squad]
    assert len(ids) == len(set(ids))


def test_fit_locks_suboptimal_player_and_reports_cost():
    # id 30 = heikoin FWD (xp 3.8/GW) — ei mahtuisi vapaaseen optimiin
    out = fit_squad([30])
    _assert_legal_squad(out)
    assert 30 in [p["id"] for p in out["xi"]]
    assert out["totals"]["delta_xp"] < 0
    assert "costs" in out["message"]
    assert out["totals"]["optimal_xp_horizon"] > 0


def test_fit_top_players_costs_nothing():
    # 25 (paras FWD) + 15 (paras MID) kuuluvat vapaaseen optimiin →
    # lukitseminen ei maksa mitään (sama ahne polku molemmin puolin).
    out = fit_squad([25, 15])
    _assert_legal_squad(out)
    xi_ids = [p["id"] for p in out["xi"]]
    assert 25 in xi_ids and 15 in xi_ids
    assert out["totals"]["delta_xp"] >= -0.01


def test_fit_three_locked_all_in_xi():
    out = fit_squad([30, 24, 14])  # heikoin FWD + heikoin MID + heikoin DEF
    _assert_legal_squad(out)
    xi_ids = [p["id"] for p in out["xi"]]
    for pid in (30, 24, 14):
        assert pid in xi_ids
    assert out["totals"]["delta_xp"] < 0


@pytest.mark.parametrize("locked,status", [
    ([], 400),
    ([1, 2, 3, 4], 400),
    ([15, 15], 400),
    ([99999], 404),
    ([1, 2], 400),  # kaksi maalivahtia — XI:ssä on yksi
])
def test_fit_validation_errors(locked, status):
    with pytest.raises(rt.RateTeamError) as e:
        fit_squad(locked)
    assert e.value.status_code == status


def test_fit_response_shape():
    out = fit_squad([25])
    assert set(out) == {"meta", "locked", "xi", "bench", "totals", "message"}
    assert out["meta"]["horizon_gw"] == 6
    p = out["xi"][0]
    assert set(p) == {"id", "web_name", "team_short", "pos", "price",
                      "xp_horizon_total", "xp_per_gw"}
    assert out["locked"][0]["id"] == 25


# --- 29.7: fit ja benchmark eivät saa väittää eri "mallin parasta" ----------


def _pool_and_key():
    xp_data, _boot, pool, _by_id = rt.build_context()
    return pool, str(xp_data["meta"].get("generated_at"))


def test_fit_vertailukohta_on_sama_luku_kuin_rate_teamin_benchmark():
    """Juuri tämä ristiriita mitattiin tuotannosta 28.7: fit väitti mallin
    parhaaksi 282.31 ja benchmark 303.34. Kaksi pintaa, kaksi "parasta"."""
    pool, key = _pool_and_key()
    benchmark = rt.optimal_budget_team_xp(pool, key)
    out = fit_squad([30])
    assert out["totals"]["optimal_xp_horizon"] == round(benchmark, 2)


def _wide_pool():
    """Synteettinen pooli jossa klubikatto EI sido (oma klubi lähes jokaiselle)
    → eksakti polku menee läpi ja proven=True. Jaetussa mock-rungossa klubeja
    on liian vähän, joten siellä ajetaan varapolku eikä todistuslippua nosteta;
    tämä testi tarvitsee nimenomaan todistetun tapauksen."""
    pool, pid, club = [], 0, 0

    def add(t, price, xp, xmins=90.0):
        nonlocal pid, club
        pid += 1
        club += 1
        pool.append({"id": pid, "web_name": f"P{pid}", "element_type": t,
                     "price": price, "xp_horizon_total": xp,
                     "xp_per_gw": xp / 6, "club": club,
                     "team_short": f"C{club:02d}", "xmins": xmins,
                     "gameweeks": []})

    for i in range(4):
        add(1, 40 + 5 * i, 10.0 + 4 * i)
    for i in range(9):
        add(2, 40 + 5 * i, 12.0 + 3 * i)
    for i in range(9):
        add(3, 40 + 5 * i, 14.0 + 3 * i)
    for i in range(7):
        add(4, 40 + 5 * i, 13.0 + 3 * i)
    return pool


def test_lukitus_optimin_pelaajaan_maksaa_tasan_nolla():
    """Jos lukittu kuuluu vapaaseen optimiin, sama XI on yhä laillinen ja
    budjetin sisällä → paras lukittu runko on TASAN vapaa optimi.

    Tämän vanha fit rikkoi: sen oma heikompi optimoija ei löytänyt samaa runkoa,
    jolloin lukitseminen näytti maksavan vaikkei maksanut (ja päinvastoin —
    tuotannossa se väitti Haalandin olevan ilmainen, koska sen vertailukohta oli
    21 xP liian matala)."""
    pool = _wide_pool()
    free = rt.build_optimal_squad(pool)
    assert free["proven"], "leveän poolin pitää mennä eksaktia polkua"
    best = max(free["xi"], key=lambda p: p["xp_horizon_total"])
    fitted = rt.build_optimal_squad(pool, [best])
    assert fitted["proven"]
    assert round(fitted["xi_xp"], 6) == round(free["xi_xp"], 6)


def test_lukitus_optimin_ulkopuolelle_ei_voi_parantaa_optimia():
    """Rajoitteen lisääminen ei voi parantaa optimia: minkä tahansa lukituksen
    tulos on ≤ vapaa optimi. Tämä on se suunta jonka vanha fit rikkoi
    (fit-optimi 282.31 < benchmark 303.34, mutta copy väitti fitin olevan
    mallin paras)."""
    pool = _wide_pool()
    free = rt.build_optimal_squad(pool)
    free_ids = {p["id"] for p in free["xi"]}
    outsiders = [p for p in pool if p["id"] not in free_ids]
    assert outsiders
    for p in outsiders[:5]:
        fitted = rt.build_optimal_squad(pool, [p])
        if not fitted["xi"]:
            continue
        assert fitted["xi_xp"] <= free["xi_xp"] + 1e-9
        assert p["id"] in {q["id"] for q in fitted["xi"]}


def test_fit_copy_vaatii_todistuksen_sanalle_best():
    """Rehellisyysportti: 'the model's best' vain kun proven. Sama sääntö kuin
    rate-teamissa (28.7), nyt myös fitissä. Toimii kummallakin poolilla —
    jaetussa mock-rungossa klubikatto sitoo, joten siellä testataan juuri se
    haara jossa väitettä EI saa esittää."""
    out = fit_squad([30])
    msg = out["message"]
    if out["totals"]["optimal_proven"]:
        assert "the model's best" in msg
    else:
        assert "the model's best" not in msg
        assert "the model found" in msg


def test_fit_penkki_on_pelattava_myos_lukittujen_kanssa():
    """Vanhassa fitissä penkki oli 'kolme halvinta' ILMAN pelattavuusvaatimusta,
    eli se poikkesi benchmarkista myös tällä akselilla.

    Synteettinen pooli, koska jaetussa mock-rungossa kaikilla on xmins 85 →
    säännön poisto ei muuttaisi mitään ja kontrolli menisi läpi (sama ansa
    kaatoi neljä testiä 28.7).
    """
    pool, pid = [], 0

    def add(t, price, xp, club, xmins, name):
        nonlocal pid
        pid += 1
        pool.append({"id": pid, "web_name": name, "element_type": t,
                     "price": price, "xp_horizon_total": xp,
                     "xp_per_gw": xp / 6, "club": club,
                     "team_short": f"C{club:02d}", "xmins": xmins,
                     "gameweeks": []})

    add(1, 40, 5.0, 1, 0.0, "GK_CHEAP")        # varavahti: halvin kelpaa
    add(1, 55, 24.0, 2, 90.0, "GK_START")
    add(2, 40, 1.0, 3, 0.0, "DEF_NEVER_PLAYS")  # halvin muttei pelaa
    add(2, 45, 14.0, 4, 60.0, "DEF_PLAYS")
    for i in range(6):
        add(2, 60, 25.0 - i, 10 + i, 90.0, f"DEF{i}")
    for i in range(6):
        add(3, 60, 30.0 - i, 20 + i, 90.0, f"MID{i}")
    for i in range(5):
        add(4, 60, 28.0 - i, 30 + i, 90.0, f"FWD{i}")

    locked = [p for p in pool if p["web_name"] == "FWD4"]  # heikoin FWD
    res = rt.build_optimal_squad(pool, locked)
    assert res["xi"], "lukittu runko pitää saada kokoon"
    assert locked[0]["id"] in {p["id"] for p in res["xi"]}
    names = [p["web_name"] for p in res["bench"]]
    # Odotus on KOVAKOODATTU eikä luettu rt.BENCH_MIN_XMINSistä: jos kynnys
    # luetaan testattavasta moduulista, sen nollaaminen muuttaa myös odotuksen
    # ja negatiivinen kontrolli menee läpi (todettiin 29.7 ajamalla kontrolli).
    assert "DEF_NEVER_PLAYS" not in names, (
        f"penkille valittiin pelaamaton pelaaja: {names}")
    assert "DEF_PLAYS" in names, f"pelattava halpa puolustaja puuttuu: {names}"
    for p in res["bench"]:
        if p["element_type"] == 1:
            continue  # varamaalivahti on tietoinen poikkeus
        assert (p.get("xmins") or 0) >= 45.0, (
            f"penkille valittiin pelaamaton pelaaja: {p['web_name']}")


def test_aloitusvahti_on_pelaava_myos_kireassa_budjetissa():
    """17.8: fit checker palautti AVAUKSEEN 19 minuutin varavahdin.

    Löytyi tuotannosta, luojan julkaisemasta kuvasta: XI:n maalivahtina oli
    Steele (4.0m), jolle oma xP-mallimme antaa 19,3 odotettua minuuttia ja
    5,74 pistettä; Verbruggen maksoi 0,5m enemmän ja tuotti 22,76. Otsikko
    lukee "BEST XI AROUND YOUR LOCKS", joten väite oli väärä mallin OMILLA
    luvuilla.

    Juurisyy: `_playable`-rajauksen maalivahtipoikkeus on oikein PENKILLE
    (varavahti ei pelaa jos ykkönen on kunnossa) mutta koski myös avausta.
    Kireässä budjetissa ahne täyttö osti kaksi ei-pelaavaa vahtia.

    Synteettinen pooli ja tiukka budjetti, koska väljässä budjetissa vika ei
    laukea lainkaan — sama ansa kuin 28.7:n penkkitestissä.
    """
    pool, pid = [], 0

    def add(t, price, xp, club, xmins, name):
        nonlocal pid
        pid += 1
        pool.append({"id": pid, "web_name": name, "element_type": t,
                     "price": price, "xp_horizon_total": xp,
                     "xp_per_gw": xp / 6, "club": club,
                     "team_short": f"C{club:02d}", "xmins": xmins,
                     "gameweeks": []})

    # Budjetti on viritetty niin että 0,5m ratkaisee: koko 15 maksaa tasan
    # 100.0m molemmilla haaroilla, ja halvemmalla vahdilla säästyvä 0,5m
    # riittää nostamaan SWING_BADin tilalle SWING_GOODin (+22 xP > vahdin
    # -19 xP). Ilman tätä viritystä vika ei laukea eikä testi mittaa mitään.
    add(1, 45, 24.0, 1, 90.0, "GK_START")
    add(1, 40, 5.0, 2, 10.0, "GK_BACKUP")     # ei pelaa
    add(1, 40, 4.0, 3, 8.0, "GK_BENCH")       # penkin varavahti
    for i in range(4):
        add(2, 70, 26.0 - i * 0.1, 10 + i, 90.0, f"DEF{i}")
    for i in range(4):
        add(3, 70, 27.0 - i * 0.1, 20 + i, 90.0, f"MID{i}")
    add(4, 75, 28.0, 30, 90.0, "FWD_CORE")
    # Swing-pari: sama positio, 0,5m ero, iso xP-ero.
    add(4, 150, 30.0, 31, 90.0, "SWING_GOOD")
    add(4, 145, 8.0, 32, 90.0, "SWING_BAD")
    for i in range(3):
        add(2, 45, 3.0, 40 + i, 60.0, f"BDEF{i}")
    for i in range(3):
        add(3, 45, 3.0, 50 + i, 60.0, f"BMID{i}")
    for i in range(2):
        add(4, 45, 3.0, 60 + i, 60.0, f"BFWD{i}")

    locked: list[dict] = []

    def _xi_gk(res):
        gks = [p for p in res["xi"] if p["element_type"] == 1]
        assert len(gks) == 1, "XI:ssä pitää olla tasan yksi maalivahti"
        return gks[0]

    res = rt.build_optimal_squad(pool, locked)
    assert res["xi"], "runko pitää saada kokoon"
    gk = _xi_gk(res)
    # Kynnys kovakoodattu: jos se luetaan moduulista, kynnyksen nollaaminen
    # muuttaisi myös odotuksen ja kontrolli menisi läpi.
    assert (gk.get("xmins") or 0) >= 45.0, (
        f"avaukseen valittiin pelaamaton maalivahti: "
        f"{gk['web_name']} xmins={gk.get('xmins')}")
    assert gk["web_name"] == "GK_START"
    # Halpa varavahti kuuluu yhä PENKILLE — rajaus ei saa poistaa sitä.
    assert any(p["element_type"] == 1 for p in res["bench"]), \
        "penkiltä puuttuu varamaalivahti"

    # NEGATIIVINEN KONTROLLI: ilman rajausta sama pooli tuottaa vian.
    # Ilman tätä testi voisi mennä läpi vaikka se ei mittaisi mitään.
    rikki = rt._build_optimal_squad(pool, locked, require_playable_gk=False)
    assert rikki["xi"], "kontrollin pitää tuottaa runko"
    assert (_xi_gk(rikki).get("xmins") or 0) < 45.0, (
        "negatiivinen kontrolli ei toistanut vikaa -> testi ei mittaa mitään")


def test_pelaavan_vahdin_rajaus_ei_maksa_mitaan_kun_budjetti_riittaa():
    """Korjaus ei saa huonontaa tapauksia jotka olivat jo kunnossa.

    Ensimmäinen versioni huononsi niitä: annoin `_unconstrained_optimum`ille
    xi_poolin, ja koska sama lista syötti sekä XI-ehdokkaat että PENKIN
    hinta-arvion, penkki kallistui 0,5m ja XI-budjetti kutistui. Oire oli
    kaksi ajoa jotka molemmat väittivät `proven=True` mutta antoivat eri
    summan. Tämä testi lukitsee sen: väljässä budjetissa tulos on identtinen.
    """
    pool, pid = [], 0

    def add(t, price, xp, club, xmins, name):
        nonlocal pid
        pid += 1
        pool.append({"id": pid, "web_name": name, "element_type": t,
                     "price": price, "xp_horizon_total": xp,
                     "xp_per_gw": xp / 6, "club": club,
                     "team_short": f"C{club:02d}", "xmins": xmins,
                     "gameweeks": []})

    add(1, 40, 5.0, 1, 10.0, "GK_BACKUP")
    add(1, 45, 24.0, 2, 90.0, "GK_START")
    for i in range(8):
        add(2, 45, 18.0 - i * 0.1, 10 + i, 90.0, f"DEF{i}")
    for i in range(8):
        add(3, 45, 19.0 - i * 0.1, 20 + i, 90.0, f"MID{i}")
    for i in range(6):
        add(4, 45, 17.0 - i * 0.1, 30 + i, 90.0, f"FWD{i}")

    rajattu = rt._build_optimal_squad(pool, [], require_playable_gk=True)
    vapaa = rt._build_optimal_squad(pool, [], require_playable_gk=False)
    assert rajattu["xi"] and vapaa["xi"]
    assert abs(rajattu["xi_xp"] - vapaa["xi_xp"]) < 1e-9, (
        f"rajaus maksoi xP:tä väljässä budjetissa: "
        f"{rajattu['xi_xp']} vs {vapaa['xi_xp']}")
