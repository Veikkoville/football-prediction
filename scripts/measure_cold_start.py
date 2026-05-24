"""
Mittaa cold-start /api/teams + /api/predict per liiga.

Käyttö:
  python -m scripts.measure_cold_start --base http://localhost:8765

Cold = muistissa-oleva _MODEL_CACHE tyhjä ennen kutakin liigaa
(kutsuu /api/admin/clear-cache jokaisen liigan välissä). Levycache
säilyy — tämä vastaa Render-kontekstia: kontti on lämmennyt, mutta
malli on vielä fitaamatta tälle liigalle.
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.request
import urllib.error


LEAGUES = [
    ("ENG-Premier League",   ["2425", "2526"], "Arsenal",       "Liverpool"),
    ("ESP-La Liga-FD",       ["2425", "2526"], "Real Madrid CF","FC Barcelona"),
    ("GER-Bundesliga-FD",    ["2425", "2526"], "FC Bayern München","Borussia Dortmund"),
    ("ITA-Serie A-FD",       ["2425", "2526"], "FC Internazionale Milano","AC Milan"),
    ("FRA-Ligue 1-FD",       ["2425", "2526"], "Paris Saint-Germain FC","Olympique de Marseille"),
    ("INT-Champions League", ["2425", "2526"], "Real Madrid CF","FC Bayern München"),
]


def _get(url: str, timeout: float = 120.0):
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
            return time.perf_counter() - t0, r.status, body
    except urllib.error.HTTPError as e:
        return time.perf_counter() - t0, e.code, e.read()
    except Exception as e:
        return time.perf_counter() - t0, -1, str(e).encode()


def _post(url: str, payload: dict, timeout: float = 120.0):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST",
                                  headers={"Content-Type": "application/json"})
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
            return time.perf_counter() - t0, r.status, body
    except urllib.error.HTTPError as e:
        return time.perf_counter() - t0, e.code, e.read()
    except Exception as e:
        return time.perf_counter() - t0, -1, str(e).encode()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--base", default="http://localhost:8765")
    args = p.parse_args()

    print(f"\n{'League':<26} {'/api/teams':>12} {'/api/predict':>14} {'2nd /teams':>12} {'2nd /predict':>14}")
    print("-" * 84)
    rows = []
    for league, seasons, home, away in LEAGUES:
        # 1) tyhjennä mallicache - simuloi "kontti lämmin, malli fittaamatta"
        _post(f"{args.base}/api/admin/clear-cache", {})

        from urllib.parse import quote_plus
        q = "&".join([f"leagues={quote_plus(league)}"] +
                     [f"seasons={s}" for s in seasons])
        t_teams_cold, status_t, body_t = _get(f"{args.base}/api/teams?{q}")
        ok_teams = (status_t == 200)

        payload = {
            "home_team": home, "away_team": away,
            "leagues": [league], "seasons": seasons,
        }
        t_pred_cold, status_p, body_p = _post(f"{args.base}/api/predict", payload)
        ok_pred = (status_p == 200)

        # 2) warm - malli muistissa, ei pitäisi fit/data fetch
        t_teams_warm, _, _ = _get(f"{args.base}/api/teams?{q}")
        t_pred_warm, _, _ = _post(f"{args.base}/api/predict", payload)

        rows.append((league, t_teams_cold, ok_teams, t_pred_cold, ok_pred,
                     t_teams_warm, t_pred_warm, body_p[:200] if not ok_pred else b""))
        print(f"{league:<26} {t_teams_cold:>10.2f}s{'' if ok_teams else '*'} "
              f"{t_pred_cold:>12.2f}s{'' if ok_pred else '*'} "
              f"{t_teams_warm:>10.2f}s {t_pred_warm:>12.2f}s")

    print("\n* = HTTP error (status != 200). Detail:")
    for league, _, ok_t, _, ok_p, _, _, err in rows:
        if not (ok_t and ok_p):
            print(f"  {league}: predict_err={err[:160].decode('utf-8','replace')}")


if __name__ == "__main__":
    main()
