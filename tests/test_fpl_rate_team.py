"""#34 rate-my-team -testit: laillisuus, budjetti, xP-monotonia, golden-master.

Hermeettinen: FPL-API (_fetch_fpl) ja xP-projektio (load_xp) mockataan —
ei verkkoa, ei riippuvuutta committattuun projektioon.
"""
from __future__ import annotations

import pytest

import src.models.fpl_rate_team as rt


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

    def add(pos, club, price, xp):
        nonlocal pid
        players.append(_mk_player(pid, pos, club, price, xp))
        boot.append({"id": pid, "now_cost": price, "team": club,
                     "element_type": pos, "web_name": f"P{pid}", "status": "a"})
        pid += 1

    # GKP ×4 (klubit 1-4)
    for i, xp in enumerate([4.0, 3.5, 3.0, 2.5]):
        add(1, i + 1, 45, xp)
    # DEF ×10 (klubit 1-10)
    for i, xp in enumerate([4.5, 4.2, 4.0, 3.8, 3.6, 3.4, 3.2, 3.0, 2.8, 2.6]):
        add(2, i + 1, 50, xp)
    # MID ×10 (klubit 1-10)
    for i, xp in enumerate([5.5, 5.2, 5.0, 4.8, 4.6, 4.4, 4.2, 4.0, 3.8, 3.6]):
        add(3, i + 1, 70, xp)
    # FWD ×6 (klubit 1-6)
    for i, xp in enumerate([5.8, 5.4, 5.0, 4.6, 4.2, 3.8]):
        add(4, i + 1, 75, xp)
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
    rt._RATING_DIST_CACHE.clear()
    yield
    rt._RATING_DIST_CACHE.clear()


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
    assert out["meta"]["sample_size"] > 0


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


def test_rating_distribution_deterministic():
    pool = rt._projection_pool(FAKE_XP, {e["id"]: e for e in POOL_BOOT})
    d1 = rt.rating_distribution(pool, "k1")
    rt._RATING_DIST_CACHE.clear()
    d2 = rt.rating_distribution(pool, "k1")
    assert d1 == d2 and len(d1) > 0


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
