"""#34 rate-my-team -testit: laillisuus, budjetti, xP-monotonia, golden-master.

Hermeettinen: FPL-API (_fetch_fpl) ja xP-projektio (load_xp) mockataan —
ei verkkoa, ei riippuvuutta committattuun projektioon.
"""
from __future__ import annotations

import pytest

import src.models.fpl_rate_team as rt

# Aito _fetch_fpl talteen ENNEN autouse-mockia (#52-stale-testi käyttää)
_REAL_FETCH_FPL = rt._fetch_fpl


# ---------------------------------------------------------------------------
# Fixturet: pieni mutta laillinen pelaajapooli + fake-FPL
# ---------------------------------------------------------------------------

def _mk_player(pid, pos, club, price, xp_gw, name=None):
    """pos: 1..4; price kymmenyksinä; xp_gw = xP/GW → horisontti = 6 × xp_gw."""
    return {
        "id": pid, "web_name": name or f"P{pid}",
        "team": f"Club{club}", "team_short": f"C{club:02d}",
        "pos": rt.POS_NAME[pos],
        "xmins": 85.0, "xp_per_gw": xp_gw, "xp_horizon_total": round(xp_gw * 6, 2),
        "gameweeks": [{"gw": g, "opponents": [], "xp": xp_gw} for g in range(1, 7)],
    }


def _build_pool():
    """30 pelaajaa: per positio riittävästi sekä rungolle että siirtokandidaateille.
    Hinnat maltillisia → satunnaisotos mahtuu budjettiin."""
    players = []
    boot = []
    pid = 1

    def add(pos, club, price, xp, eo="5.0"):
        nonlocal pid
        players.append(_mk_player(pid, pos, club, price, xp))
        boot.append({"id": pid, "now_cost": price, "team": club,
                     "element_type": pos, "web_name": f"P{pid}", "status": "a",
                     "selected_by_percent": eo})
        pid += 1

    # EO: per position 2 ensimmäistä (= parhaat) "template"-omistuksella 40 %,
    # loput 5 % → differential-testit saavat molempia luokkia.
    # GKP ×4 (klubit 1-4)
    for i, xp in enumerate([4.0, 3.5, 3.0, 2.5]):
        add(1, i + 1, 45, xp, eo="40.0" if i < 2 else "5.0")
    # DEF ×10 (klubit 1-10)
    for i, xp in enumerate([4.5, 4.2, 4.0, 3.8, 3.6, 3.4, 3.2, 3.0, 2.8, 2.6]):
        add(2, i + 1, 50, xp, eo="40.0" if i < 2 else "5.0")
    # MID ×10 (klubit 1-10)
    for i, xp in enumerate([5.5, 5.2, 5.0, 4.8, 4.6, 4.4, 4.2, 4.0, 3.8, 3.6]):
        add(3, i + 1, 70, xp, eo="40.0" if i < 2 else "5.0")
    # FWD ×6 (klubit 1-6)
    for i, xp in enumerate([5.8, 5.4, 5.0, 4.6, 4.2, 3.8]):
        add(4, i + 1, 75, xp, eo="40.0" if i < 2 else "5.0")
    return players, boot


POOL_PLAYERS, POOL_BOOT = _build_pool()

# Käyttäjän 15: GK 1-2, DEF 5-9, MID 15-19, FWD 25-27 (id-järjestys yllä:
# GKP=1..4, DEF=5..14, MID=15..24, FWD=25..30)
SQUAD_IDS = [1, 2, 5, 6, 7, 8, 9, 15, 16, 17, 18, 19, 25, 26, 27]

FAKE_XP = {"meta": {"available": True, "season": "2026/27",
                    "generated_at": "test-fixture", "next_gameweek": 1,
                    "horizon_gw": 6},
           "players": POOL_PLAYERS}

FAKE_BOOTSTRAP = {
    "events": [{"id": 1, "is_current": False, "is_next": True},
               {"id": 2, "is_current": False, "is_next": False}],
    "elements": POOL_BOOT,
    "teams": [{"id": i} for i in range(1, 11)],
}

FAKE_PICKS = {
    "picks": ([{"element": e, "is_captain": e == 15, "is_vice_captain": False}
               for e in SQUAD_IDS]),
    "entry_history": {"bank": 15},  # 1.5m
}


@pytest.fixture(autouse=True)
def _mock_fpl(monkeypatch):
    def fake_fetch(path):
        if path == "/bootstrap-static/":
            return FAKE_BOOTSTRAP
        if path == "/entry/424242/":
            return {"id": 424242}
        if path == "/entry/424242/event/1/picks/":
            return FAKE_PICKS
        raise rt.RateTeamError(404, "Not found on the FPL API.")

    monkeypatch.setattr(rt, "_fetch_fpl", fake_fetch)
    monkeypatch.setattr(rt, "load_xp", lambda: FAKE_XP)
    rt._OPTIMAL_XP_CACHE.clear()
    rt._FPL_CACHE.clear()
    yield
    rt._OPTIMAL_XP_CACHE.clear()
    rt._FPL_CACHE.clear()


# ---------------------------------------------------------------------------
# Golden-master (entry-moodi)
# ---------------------------------------------------------------------------

def test_entry_mode_golden():
    out = rt.rate_team(entry=424242)
    assert out["meta"]["mode"] == "entry"
    assert out["meta"]["gw"] == 1  # is_next kun current puuttuu
    assert len(out["team"]["players"]) == 15
    assert out["team"]["bank"] == 1.5
    assert out["team"]["missing_ids"] == []
    # XI = paras laillinen; kapteeni picksistä (15 = paras MID) on XI:ssä
    xi = [p for p in out["team"]["players"] if p["in_xi"]]
    assert len(xi) == 11
    caps = [p for p in out["team"]["players"] if p["is_captain"]]
    assert len(caps) == 1 and caps[0]["id"] == 15
    # Kapteenisuositus = XI:n korkein GW-xP (FWD 25: 5.8)
    assert out["captain"]["pick"]["id"] == 25
    assert 0.0 <= out["rating"]["percentile"] <= 100.0
    assert out["rating"]["team_xp_horizon"] > out["rating"]["team_xp_horizon_no_captain"]
    assert out["meta"]["rating_method"] == "vs_optimal_budget_team"
    assert out["rating"]["optimal_team_xp"] > 0


def test_manual_mode_and_validation():
    out = rt.rate_team(players=SQUAD_IDS, captain=25, bank=2.0)
    assert out["meta"]["mode"] == "manual"
    assert out["team"]["bank"] == 2.0
    with pytest.raises(rt.RateTeamError) as e:
        rt.rate_team(players=SQUAD_IDS[:14])
    assert e.value.status_code == 400
    with pytest.raises(rt.RateTeamError) as e:
        rt.rate_team(players=SQUAD_IDS[:14] + [SQUAD_IDS[0]])
    assert "duplicate" in e.value.detail


def test_unknown_entry_404():
    with pytest.raises(rt.RateTeamError) as e:
        rt.rate_team(entry=999999)
    assert e.value.status_code == 404


# ---------------------------------------------------------------------------
# Ship-gatet: laillisuus, budjetti, monotonia
# ---------------------------------------------------------------------------

def _apply_transfer(squad_ids, sugg):
    ids = [i for i in squad_ids if i != sugg["out"]["id"]] + [sugg["in"]["id"]]
    return ids


def test_transfers_legal_and_within_budget():
    out = rt.rate_team(entry=424242)
    pool = {p["id"]: p for p in POOL_BOOT}
    squad_clubs = {}
    for sid in SQUAD_IDS:
        c = pool[sid]["team"]
        squad_clubs[c] = squad_clubs.get(c, 0) + 1
    bank = 15  # kymmenyksiä
    for s in out["transfers"]["suggestions"]:
        out_p, in_p = pool[s["out"]["id"]], pool[s["in"]["id"]]
        # sama positio
        assert out_p["element_type"] == in_p["element_type"]
        # budjetti: sisään tulevan hinta <= bank + ulos lähtevän hinta
        assert in_p["now_cost"] <= bank + out_p["now_cost"]
        # ei jo rungossa
        assert s["in"]["id"] not in SQUAD_IDS
        # klubiraja vaihdon jälkeen
        after = dict(squad_clubs)
        after[out_p["team"]] -= 1
        after[in_p["team"]] = after.get(in_p["team"], 0) + 1
        assert all(v <= rt.MAX_PER_CLUB for v in after.values())


def test_transfer_monotonicity_team_xp_never_drops():
    out = rt.rate_team(entry=424242)
    base = out["rating"]["team_xp_horizon_no_captain"]
    for s in out["transfers"]["suggestions"]:
        new_ids = _apply_transfer(SQUAD_IDS, s)
        new_out = rt.rate_team(players=new_ids)
        assert new_out["rating"]["team_xp_horizon_no_captain"] >= base - 1e-9


def test_hold_when_no_meaningful_upgrade():
    # Runko = poolin parhaat joka positiossa → ei positiivista deltaa → hold
    best_ids = [1, 2, 5, 6, 7, 8, 9, 15, 16, 17, 18, 19, 25, 26, 27]
    # (SQUAD_IDS on jo per positio parhaat tässä poolissa)
    out = rt.rate_team(players=best_ids, bank=0.0)
    assert out["transfers"]["hold"] is True or (
        out["transfers"]["suggestions"]
        and out["transfers"]["suggestions"][0]["delta_xp_horizon"]
        >= rt.HOLD_THRESHOLD_XP)


# ---------------------------------------------------------------------------
# #63 hold_verdict: hold/transfer + hit-tietoisuus
# ---------------------------------------------------------------------------

# Heikko runko (per positio poolin huonoimmat) — jaettu myös planner-testeihin
WEAK_SQUAD_IDS = [3, 4, 10, 11, 12, 13, 14, 20, 21, 22, 23, 24, 28, 29, 30]
# Runko jossa paras upgrade on FWD 28 (4.6/GW) -> 27 (5.0/GW) = +2.4 xP gross
# 6 GW:lle: ft=1 -> netto 2.4 >= kynnys 2.0 (transfer); ft=0 -> 2.4-4 = -1.6 (hold)
NEAR_OPTIMAL_SQUAD_IDS = [1, 2, 5, 6, 7, 8, 9, 15, 16, 17, 18, 19, 25, 26, 28]


def test_hold_verdict_optimized_team_holds():
    # (a) selvästi optimoitu tiimi -> verdict=hold + gain alle kynnyksen
    out = rt.rate_team(players=SQUAD_IDS, bank=0.0)
    hv = out["transfers"]["hold_verdict"]
    assert hv["verdict"] == "hold"
    assert (hv["best_move_gain_xp"] is None
            or hv["best_move_gain_xp"] < rt.HOLD_THRESHOLD_XP)
    assert hv["horizon_gws"] == 6
    assert hv["threshold_xp"] == rt.HOLD_THRESHOLD_XP
    assert "holding" in hv["message"].lower()


def test_hold_verdict_weak_team_transfers():
    # (b) selvästi heikko tiimi -> verdict=transfer + oikea out->in
    out = rt.rate_team(players=WEAK_SQUAD_IDS, bank=0.0)
    hv = out["transfers"]["hold_verdict"]
    assert hv["verdict"] == "transfer"
    assert hv["best_move_gain_xp"] >= rt.HOLD_THRESHOLD_XP
    top = out["transfers"]["suggestions"][0]
    assert top["out"]["id"] in WEAK_SQUAD_IDS
    assert top["in"]["id"] not in WEAK_SQUAD_IDS
    # ft=1 (oletus) -> ei hittiä -> netto == brutto-delta
    assert hv["best_move_gain_xp"] == top["delta_xp_horizon"]
    assert hv["hit_applied_xp"] == 0.0


def test_hold_verdict_hit_aware():
    # (c) siirto joka voittaa brutto +2.4 xP: ft=1 -> transfer;
    # ft=0 -> -4 hitti -> netto -1.6 -> HOLD (hit-tietoisuus)
    with_ft = rt.rate_team(players=NEAR_OPTIMAL_SQUAD_IDS, bank=0.0, ft=1)
    assert with_ft["transfers"]["hold_verdict"]["verdict"] == "transfer"
    assert with_ft["transfers"]["hold_verdict"]["best_move_gain_xp"] == 2.4

    no_ft = rt.rate_team(players=NEAR_OPTIMAL_SQUAD_IDS, bank=0.0, ft=0)
    hv = no_ft["transfers"]["hold_verdict"]
    assert hv["verdict"] == "hold"
    assert hv["hit_applied_xp"] == rt.HIT_COST_XP
    assert hv["best_move_gain_xp"] == round(2.4 - rt.HIT_COST_XP, 2)
    assert "hit" in hv["message"]


def test_hold_verdict_ft_validation():
    with pytest.raises(rt.RateTeamError) as e:
        rt.rate_team(players=SQUAD_IDS, ft=99)
    assert e.value.status_code == 400


def test_hold_verdict_golden_master_entry():
    # Golden: entry-runko = poolin parhaat -> hold, kentät vakiot
    hv = rt.rate_team(entry=424242)["transfers"]["hold_verdict"]
    assert hv == {
        "verdict": "hold",
        "best_move_gain_xp": None,
        "horizon_gws": 6,
        "threshold_xp": rt.HOLD_THRESHOLD_XP,
        "hit_applied_xp": 0.0,
        "message": ("No transfer beats your team over the next 6 GWs - "
                    "holding is the play."),
    }


def test_optimal_xi_formation_legal():
    squad = [p for p in rt._projection_pool(FAKE_XP,
             {e["id"]: e for e in POOL_BOOT}) if p["id"] in SQUAD_IDS]
    xi = rt.optimal_xi(squad)
    assert len(xi) == 11
    counts = {}
    for p in xi:
        counts[p["element_type"]] = counts.get(p["element_type"], 0) + 1
    assert counts[1] == 1
    assert rt.XI_MIN[2] <= counts.get(2, 0) <= rt.XI_MAX[2]
    assert rt.XI_MIN[3] <= counts.get(3, 0) <= rt.XI_MAX[3]
    assert rt.XI_MIN[4] <= counts.get(4, 0) <= rt.XI_MAX[4]


def test_optimal_benchmark_deterministic_and_beats_squads():
    # #50: benchmark on deterministinen ja aidosti erotteleva — paras runko
    # saa korkean %-arvon, heikko runko selvasti matalamman (ei "kaikille 100 %").
    pool = rt._projection_pool(FAKE_XP, {e["id"]: e for e in POOL_BOOT})
    o1 = rt.optimal_budget_team_xp(pool, "k1")
    rt._OPTIMAL_XP_CACHE.clear()
    o2 = rt.optimal_budget_team_xp(pool, "k1")
    assert o1 == o2 and o1 > 0
    best = rt.rate_team(players=SQUAD_IDS, bank=0.0)
    weak = rt.rate_team(players=[3, 4, 10, 11, 12, 13, 14, 20, 21, 22, 23, 24,
                                 28, 29, 30], bank=0.0)
    assert best["rating"]["percentile"] <= 100.0
    assert weak["rating"]["percentile"] < best["rating"]["percentile"]
    assert weak["rating"]["gap_to_optimal_xp"] > best["rating"]["gap_to_optimal_xp"]


# ---------------------------------------------------------------------------
# Endpoint-smoke (TestClient)
# ---------------------------------------------------------------------------

def test_endpoint_entry_mode(client, monkeypatch):
    r = client.get("/api/fantasy/rate-team?entry=424242")
    assert r.status_code == 200
    b = r.json()
    assert b["meta"]["mode"] == "entry"
    assert b["rating"]["percentile"] >= 0
    assert r.headers["cache-control"] == "no-store"


def test_endpoint_requires_entry_or_players(client):
    r = client.get("/api/fantasy/rate-team")
    assert r.status_code == 400


def test_endpoint_manual_mode(client):
    ids = ",".join(str(i) for i in SQUAD_IDS)
    r = client.get(f"/api/fantasy/rate-team?players={ids}&captain=25&bank=1.0")
    assert r.status_code == 200
    assert r.json()["meta"]["mode"] == "manual"


def test_endpoint_bad_players_param(client):
    r = client.get("/api/fantasy/rate-team?players=1,2,abc")
    assert r.status_code == 400


def test_endpoint_hold_verdict_and_ft_param(client):
    # #63: hold_verdict kulkee endpointin läpi + ft=0 flippaa hit-tietoisesti
    ids = ",".join(str(i) for i in NEAR_OPTIMAL_SQUAD_IDS)
    r1 = client.get(f"/api/fantasy/rate-team?players={ids}&bank=0")
    assert r1.status_code == 200
    assert r1.json()["transfers"]["hold_verdict"]["verdict"] == "transfer"
    r0 = client.get(f"/api/fantasy/rate-team?players={ids}&bank=0&ft=0")
    assert r0.status_code == 200
    assert r0.json()["transfers"]["hold_verdict"]["verdict"] == "hold"
    r_bad = client.get(f"/api/fantasy/rate-team?players={ids}&ft=99")
    assert r_bad.status_code == 422  # FastAPI Query(le=5)


def test_fetch_fpl_stale_fallback_on_failure(monkeypatch):
    """#52: FPL failaa (deadline-ruuhka) → serveerataan vanhentunut cache,
    EI virhettä. Ilman cachea → hallittu 503."""
    import requests as _rq
    rt._FPL_CACHE.clear()
    calls = {"n": 0}

    class _Boom:
        status_code = 500
        def json(self):
            return {}

    def fake_get(url, timeout=None, headers=None):
        calls["n"] += 1
        if calls["n"] == 1:
            class _Ok:
                status_code = 200
                def json(self):
                    return {"ok": True}
            return _Ok()
        return _Boom()

    monkeypatch.setattr(rt, "_fetch_fpl", _REAL_FETCH_FPL)
    monkeypatch.setattr(rt.requests, "get", fake_get)
    assert rt._fetch_fpl("/stale-test/") == {"ok": True}
    # Vanhenna cache → seuraava haku failaa 500 → stale-fallback
    ts, data = rt._FPL_CACHE["/stale-test/"]
    rt._FPL_CACHE["/stale-test/"] = (ts - rt.CACHE_TTL_SEC - 1, data)
    assert rt._fetch_fpl("/stale-test/") == {"ok": True}
    # Ilman cachea → hallittu virhe
    rt._FPL_CACHE.clear()
    with pytest.raises(rt.RateTeamError) as e:
        rt._fetch_fpl("/stale-test/")
    assert e.value.status_code == 503
