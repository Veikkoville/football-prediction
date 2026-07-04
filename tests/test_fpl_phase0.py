"""FPL Phase 0 -testit: loader-fallback, endpointin muoto, FDR-bucketointi.

Ei verkkoa, ei mallifittiä — builderin verkko-/fit-polut ajetaan vain
oikeassa refresh-jobissa. Domestic-malliin ei kosketa (bit-exact-regressio
kattaa /api/predictin erikseen).
"""
from __future__ import annotations

import json

from src.models import fpl_phase0 as fp


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------
def test_load_phase0_missing_file_returns_empty(tmp_path):
    data = fp.load_phase0(tmp_path / "ei-ole.json")
    assert data["meta"]["available"] is False
    assert data["teams"] == []
    assert data["fixtures"] == []


def test_load_phase0_corrupt_file_returns_empty(tmp_path):
    p = tmp_path / "rikki.json"
    p.write_text("{ei json", encoding="utf-8")
    assert fp.load_phase0(p)["meta"]["available"] is False


def test_load_phase0_reads_valid_file(tmp_path):
    payload = {
        "meta": {"available": True, "next_gameweek": 1},
        "teams": [{"name": "Arsenal", "short": "ARS", "fixtures": []}],
        "fixtures": [],
    }
    p = tmp_path / "ok.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    assert fp.load_phase0(p) == payload


# ---------------------------------------------------------------------------
# Endpoint (TestClient conftestista)
# ---------------------------------------------------------------------------
def test_fantasy_endpoint_shape(client):
    r = client.get("/api/fantasy")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-store"
    data = r.json()
    assert "meta" in data and "teams" in data and "fixtures" in data
    assert isinstance(data["teams"], list)
    assert isinstance(data["fixtures"], list)


# ---------------------------------------------------------------------------
# FDR-bucketointi (puhdas funktio, ei fittiä)
# ---------------------------------------------------------------------------
def _row(home, away, p_home, p_away, xg_home, xg_away):
    return {
        "gameweek": 1, "kickoff": "TBC", "kickoff_ms": None, "finished": False,
        "home": home, "away": away, "home_short": home[:3].upper(),
        "away_short": away[:3].upper(),
        "xg_home": xg_home, "xg_away": xg_away,
        "p_home_win": p_home, "p_draw": round(1 - p_home - p_away, 4),
        "p_away_win": p_away,
        "cs_home_pct": 30.0, "cs_away_pct": 20.0,
    }


def test_add_fdr_range_and_direction():
    from scripts.build_fpl_phase0 import add_fdr

    # 10 fixturea: Superteam murskaa kaikki -> sen fixturet helppoja (matala FDR),
    # vastustajan perspektiivi vaikea (korkea FDR).
    rows = [_row("Superteam", f"Mid{i}", 0.85, 0.05, 2.8, 0.4) for i in range(5)]
    rows += [_row(f"MidA{i}", f"MidB{i}", 0.40, 0.30, 1.4, 1.1) for i in range(5)]
    add_fdr(rows)
    for r in rows:
        assert 1 <= r["fdr_home"] <= 5
        assert 1 <= r["fdr_away"] <= 5
    super_fdr = [r["fdr_home"] for r in rows[:5]]
    opp_fdr = [r["fdr_away"] for r in rows[:5]]
    assert max(super_fdr) < min(opp_fdr)


def test_add_fdr_empty_rows_noop():
    from scripts.build_fpl_phase0 import add_fdr

    rows: list = []
    add_fdr(rows)  # ei kaadu
    assert rows == []
