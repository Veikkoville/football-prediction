"""
Smoke-test tuotannossa: ensimmäinen /api/teams + /api/predict per liiga.

EI clear-cache:tä — vastaa käyttäjän todellista kokemusta deploy + warmupin
jälkeen. Tavoite: alle 5 s per kutsu.
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.request
import urllib.error
from urllib.parse import quote_plus


LEAGUES = [
    ("ENG-Premier League",   ["2425", "2526"], "Arsenal",                  "Liverpool"),
    ("ESP-La Liga-FD",       ["2425", "2526"], "Real Madrid CF",           "FC Barcelona"),
    ("GER-Bundesliga-FD",    ["2425", "2526"], "FC Bayern München",        "Borussia Dortmund"),
    ("ITA-Serie A-FD",       ["2425", "2526"], "FC Internazionale Milano", "AC Milan"),
    ("FRA-Ligue 1-FD",       ["2425", "2526"], "Paris Saint-Germain FC",   "Olympique de Marseille"),
    ("INT-Champions League", ["2425", "2526"], "Real Madrid CF",           "FC Bayern München"),
]


def _get(url, timeout=60.0):
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return time.perf_counter() - t0, r.status, r.read()
    except urllib.error.HTTPError as e:
        return time.perf_counter() - t0, e.code, e.read()
    except Exception as e:
        return time.perf_counter() - t0, -1, str(e).encode()


def _post(url, payload, timeout=60.0):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST",
                                  headers={"Content-Type": "application/json"})
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return time.perf_counter() - t0, r.status, r.read()
    except urllib.error.HTTPError as e:
        return time.perf_counter() - t0, e.code, e.read()
    except Exception as e:
        return time.perf_counter() - t0, -1, str(e).encode()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--base", default="https://goaliq-api.onrender.com")
    args = p.parse_args()

    print(f"\n{'League':<26} {'1. /teams':>11} {'1. /predict':>13} {'2. /teams':>11} {'2. /predict':>13}")
    print("-" * 80)
    rows = []
    for league, seasons, home, away in LEAGUES:
        q = "&".join([f"leagues={quote_plus(league)}"] +
                     [f"seasons={s}" for s in seasons])
        t_t1, st_t1, _ = _get(f"{args.base}/api/teams?{q}")
        payload = {"home_team": home, "away_team": away,
                   "leagues": [league], "seasons": seasons}
        t_p1, st_p1, body_p1 = _post(f"{args.base}/api/predict", payload)
        t_t2, st_t2, _ = _get(f"{args.base}/api/teams?{q}")
        t_p2, st_p2, _ = _post(f"{args.base}/api/predict", payload)

        ok_t1 = "" if st_t1 == 200 else f"*{st_t1}"
        ok_p1 = "" if st_p1 == 200 else f"*{st_p1}"
        ok_t2 = "" if st_t2 == 200 else f"*{st_t2}"
        ok_p2 = "" if st_p2 == 200 else f"*{st_p2}"
        print(f"{league:<26} {t_t1:>8.2f}s{ok_t1:<3} {t_p1:>10.2f}s{ok_p1:<3} "
              f"{t_t2:>8.2f}s{ok_t2:<3} {t_p2:>10.2f}s{ok_p2:<3}")
        rows.append((league, t_t1, st_t1, t_p1, st_p1, t_t2, t_p2,
                     body_p1 if st_p1 != 200 else b""))

    print("\n=== summary ===")
    fails = [(l, t1, t_p, err) for (l, t1, st_t1, t_p, st_p, _, _, err) in rows
             if st_t1 != 200 or st_p != 200 or t1 > 5.0 or t_p > 5.0]
    if fails:
        print(f"FAIL: {len(fails)} liigaa ylitti 5s tai HTTP-virheen:")
        for league, t1, tp, err in fails:
            print(f"  {league}: /teams={t1:.2f}s /predict={tp:.2f}s err={err[:160].decode('utf-8','replace')}")
    else:
        print("PASS: kaikki 6 liigaa /teams + /predict < 5 s ja 200 OK")


if __name__ == "__main__":
    main()
