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
