"""#124/#125: fpl_leaders-rankkausfunktioiden yksikkötestit (ei verkkoa)."""
from src.models.fpl_leaders import (
    DEFCON_THRESHOLD, defcon_hit, rank_defcon_leaders, rank_xg_leaders,
)


def _player(pid, pos, games, *, xg=0.5, dc=5, name=None):
    return {
        "id": pid, "web_name": name or f"P{pid}", "team_short": "TST",
        "pos": pos, "price": 7.5, "owned_pct": 12.3, "basis": "2025/26",
        "games_total": games,
        "recent_games": [
            {"round": i + 1, "opp": "OPP", "venue": "H", "minutes": 90,
             "xg": xg, "xa": 0.1, "xgi": xg + 0.1, "dc": dc}
            for i in range(games)
        ],
    }


def _data(players):
    return {
        "meta": {"available": True, "basis_season": "2025/26",
                 "is_prev_season_basis": True,
                 "basis_label": "Based on 2025/26",
                 "generated_at": "2026-07-17T00:00:00"},
        "players": players,
    }


def test_defcon_thresholds_by_position():
    assert defcon_hit("DEF", 10) and not defcon_hit("DEF", 9)
    assert defcon_hit("MID", 12) and not defcon_hit("MID", 11)
    assert defcon_hit("FWD", 12) and not defcon_hit("FWD", 11)
    assert not defcon_hit("GKP", 99)  # GKP ei saa DefCon-pisteitä


def test_xg_ranking_and_window():
    data = _data([
        _player(1, "FWD", 8, xg=0.9),
        _player(2, "MID", 8, xg=0.4),
        _player(3, "DEF", 2, xg=0.1),   # vain 2 pelattua → games=2, ei pois
        _player(4, "GKP", 8, xg=0.0),   # GKP pois xG-listalta oletuksena
    ])
    out = rank_xg_leaders(data, window=5, top_n=10)
    ids = [p["id"] for p in out["players"]]
    assert ids[0] == 1 and 4 not in ids
    top = out["players"][0]
    assert top["games"] == 5                      # window rajaa
    assert abs(top["xg_per_game"] - 0.9) < 1e-9
    small = next(p for p in out["players"] if p["id"] == 3)
    assert small["games"] == 2                    # TODELLINEN otoskoko näkyy
    assert out["meta"]["basis_label"] == "Based on 2025/26"


def test_xg_pos_filter():
    data = _data([_player(1, "FWD", 5, xg=0.9), _player(2, "MID", 5, xg=0.8)])
    out = rank_xg_leaders(data, window=5, pos="MID")
    assert [p["id"] for p in out["players"]] == [2]


def test_defcon_hit_rate_and_points():
    # DEF: dc 10 joka pelissä → 100 % hit-rate, 2 p/peli
    always = _player(1, "DEF", 5, dc=10)
    # MID: dc 12 kahdesti, 5 kolmesti → 40 %
    mixed = _player(2, "MID", 5, dc=12)
    for i, g in enumerate(mixed["recent_games"]):
        g["dc"] = 12 if i < 2 else 5
    # GKP ei koskaan listalle
    gk = _player(3, "GKP", 5, dc=50)
    out = rank_defcon_leaders(_data([always, mixed, gk]), window=5)
    ids = [p["id"] for p in out["players"]]
    assert ids == [1, 2] and 3 not in ids
    top, mid = out["players"]
    assert top["hit_rate_pct"] == 100 and top["defcon_points_window"] == 10
    assert mid["hit_rate_pct"] == 40 and mid["defcon_points_window"] == 4
    assert top["threshold"] == 10 and mid["threshold"] == 12
    assert out["meta"]["thresholds"] == DEFCON_THRESHOLD


def test_no_played_games_excluded():
    p = _player(1, "MID", 0)
    out = rank_xg_leaders(_data([p]), window=5)
    assert out["players"] == []  # "No data yet" — ei arvauksia

# ---------------------------------------------------------------------------
# Koko kausi -basis (#7, 30.7): ranking per-GW-matriisin kausisummista
# ---------------------------------------------------------------------------
def _gw_player(pid, pos, games, hits, dc_each=8, name=None):
    return {
        "id": pid, "code": 90000 + pid, "web_name": name or f"P{pid}",
        "team_short": "TST", "pos": pos, "price": 5.0, "owned_pct": 3.0,
        "threshold": DEFCON_THRESHOLD.get(pos), "games": games, "hits": hits,
        "hit_rate": round(hits / games, 3) if games else 0.0,
        "dc_points": hits * 2, "basis": "2025/26",
        "per_gw": [[i + 1, "OPP", "H", 90, dc_each] for i in range(games)],
    }


def _gw_data(players):
    return {
        "meta": {"available": True, "basis_season": "2025/26",
                 "basis_label": "Based on 2025/26",
                 "generated_at": "2026-07-30T00:00:00", "n_players": len(players)},
        "players": players,
    }


def test_defcon_season_ranks_by_hit_rate():
    from src.models.fpl_leaders import rank_defcon_season
    data = _gw_data([
        _gw_player(1, "DEF", 38, 26),           # 68% hit rate
        _gw_player(2, "MID", 38, 30),           # 79% -> karkeen
        _gw_player(3, "DEF", 10, 2),            # 20%
        _gw_player(4, "GKP", 38, 0),            # GKP pois aina
    ])
    out = rank_defcon_season(data, top_n=10)
    ids = [p["id"] for p in out["players"]]
    assert ids == [2, 1, 3] and 4 not in ids
    top = out["players"][0]
    assert top["games"] == 38 and top["hits"] == 30
    assert top["hit_rate_pct"] == round(100.0 * 30 / 38, 0)
    assert top["defcon_points_window"] == 60
    assert out["meta"]["window"] == "season"
    assert out["meta"]["basis_label"] == "Based on 2025/26"


def test_defcon_season_negative_control_top_n_and_pos():
    # Kontrolli joka kaatuu jos top_n tai pos-suodatin ei oikeasti toimi.
    from src.models.fpl_leaders import rank_defcon_season
    data = _gw_data([_gw_player(i, "DEF" if i % 2 else "MID", 20, i)
                     for i in range(1, 8)])
    out = rank_defcon_season(data, top_n=3)
    assert len(out["players"]) == 3
    only_def = rank_defcon_season(data, pos="DEF")
    assert all(p["pos"] == "DEF" for p in only_def["players"])
    assert len(only_def["players"]) > 0


# ---------------------------------------------------------------------------
# #226-DC: season-basis rankkaa STARTEISTA + poolisaanto (>= puolet kierroksista)
# ---------------------------------------------------------------------------
def _gw_player_st(pid, pos, starts, start_hits, subs=0, name=None):
    """Pelaaja jolla on erikseen startit ja vaihdosta tulot."""
    p = _gw_player(pid, pos, starts + subs, start_hits, name=name)
    p.update({"starts": starts, "start_hits": start_hits,
              "hit_rate": round(start_hits / starts, 3) if starts else 0.0,
              "hit_rate_games": round(start_hits / (starts + subs), 3)})
    return p


def test_defcon_season_uses_starts_denominator():
    from src.models.fpl_leaders import rank_defcon_season
    # 20 starttia / 10 osumaa = 50 %, plus 10 vaihtoa jotka EIVAT saa laimentaa.
    data = _gw_data([_gw_player_st(1, "DEF", 20, 10, subs=10)])
    data["meta"]["pool_min_starts"] = 19
    out = rank_defcon_season(data)
    row = out["players"][0]
    assert row["hit_rate_pct"] == 50 and row["starts"] == 20
    assert row["hit_rate_basis"] == "starts"
    assert out["meta"]["hit_rate_denominator"] == "starts"
    # Negatiivinen kontrolli: pelattujen otteluiden nimittaja antaisi 33 %.
    assert row["hit_rate_pct"] != round(100.0 * 10 / 30, 0)


def test_defcon_season_pool_rule_drops_thin_samples():
    from src.models.fpl_leaders import rank_defcon_season
    data = _gw_data([
        _gw_player_st(1, "DEF", 3, 3, name="Cameo"),    # 100 % kolmesta
        _gw_player_st(2, "DEF", 30, 15, name="Regular"),
    ])
    data["meta"]["pool_min_starts"] = 19
    names = [p["web_name"] for p in rank_defcon_season(data)["players"]]
    assert names == ["Regular"]
    # Ilman poolisaantoa ohut otos nousisi karkeen -> sailyy saadettavana.
    loose = [p["web_name"] for p in rank_defcon_season(data, min_starts=0)["players"]]
    assert loose[0] == "Cameo"


def test_defcon_season_falls_back_when_starts_missing():
    """Vanha data levylla (ei starts-kenttaa) ei saa kaataa endpointtia eika
    valehdella basiksesta — rivi kertoo kummasta luku on laskettu."""
    from src.models.fpl_leaders import rank_defcon_season
    data = _gw_data([_gw_player(1, "DEF", 38, 19)])
    row = rank_defcon_season(data)["players"][0]
    assert row["hit_rate_pct"] == 50 and row["hit_rate_basis"] == "games"


def test_defcon_season_pos_change_carries_official_number():
    from src.models.fpl_leaders import rank_defcon_season
    p = _gw_player_st(1, "DEF", 20, 12)
    p.update({"pos_changed": True, "basis_pos": "MID", "hit_rate_basis_pos": 0.25})
    data = _gw_data([p])
    data["meta"]["pool_min_starts"] = 19
    row = rank_defcon_season(data)["players"][0]
    assert row["hit_rate_pct"] == 60 and row["pos_changed"] is True
    assert row["basis_pos"] == "MID" and row["hit_rate_basis_pos_pct"] == 25
