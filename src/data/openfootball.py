"""openfootball/football.json — UEFA-turnaukset, robusti URL-yritys."""

from __future__ import annotations
from pathlib import Path
import json
import pandas as pd
import requests

import config

CACHE_DIR = config.RAW_DATA_DIR / "openfootball"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Useita nimivaihtoehtoja jokaiselle turnaukselle — kokeillaan kaikki
TOURNAMENT_CODES = {
    "INT-Champions League": [
        "uefa.cl", "uefa-cl", "champions-league", "europe.cl",
    ],
    "INT-Europa League": [
        "uefa.el", "uefa-el", "europa-league", "europe.el",
    ],
    "INT-Conference League": [
        "uefa.uecl", "uefa-uecl", "uefa.el2", "uefa-el2",
        "conference-league", "europe.uecl",
    ],
}


def _kausi_to_url(kausi: str) -> str:
    if len(kausi) == 4:
        return f"20{kausi[:2]}-{kausi[2:]}"
    return kausi


def _hae_json(url: str, cache_path: Path) -> dict | None:
    if cache_path.exists() and cache_path.stat().st_size > 100:
        try:
            return json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    try:
        r = requests.get(url, timeout=15)
        if r.status_code != 200:
            return None
        cache_path.write_bytes(r.content)
        return r.json()
    except Exception:
        return None


def _poimi_ottelut(data: dict) -> list[dict]:
    ottelut = []
    if "matches" in data:
        ottelut.extend(data["matches"])
    if "rounds" in data:
        for kierros in data["rounds"]:
            if isinstance(kierros, dict) and "matches" in kierros:
                ottelut.extend(kierros["matches"])
    return ottelut


def _parse_score(ot: dict):
    score = ot.get("score") or {}
    if isinstance(score, dict):
        for k in ["ft", "regular", "fulltime"]:
            v = score.get(k)
            if isinstance(v, list) and len(v) >= 2:
                try:
                    return int(v[0]), int(v[1])
                except (TypeError, ValueError):
                    continue
    h = ot.get("score1", ot.get("home_goals"))
    a = ot.get("score2", ot.get("away_goals"))
    if h is not None and a is not None:
        try:
            return int(h), int(a)
        except (TypeError, ValueError):
            pass
    return None


def _parse_data(data: dict, liiga: str, kausi: str) -> pd.DataFrame:
    ottelut = _poimi_ottelut(data)
    rivit = []
    for ot in ottelut:
        h_team = ot.get("team1", ot.get("home"))
        a_team = ot.get("team2", ot.get("away"))
        if isinstance(h_team, dict):
            h_team = h_team.get("name") or h_team.get("code")
        if isinstance(a_team, dict):
            a_team = a_team.get("name") or a_team.get("code")
        date_str = ot.get("date")
        if not (h_team and a_team and date_str):
            continue
        score = _parse_score(ot)
        if score is None:
            continue
        rivit.append({
            "date": pd.to_datetime(date_str, errors="coerce"),
            "home_team": h_team, "away_team": a_team,
            "home_score": score[0], "away_score": score[1],
            "league": liiga, "season": kausi,
            "home_xg": pd.NA, "away_xg": pd.NA, "lahde": "openfootball",
        })
    if not rivit:
        return pd.DataFrame(columns=[
            "date", "home_team", "away_team", "home_score", "away_score",
            "league", "season", "home_xg", "away_xg", "lahde"])
    df = pd.DataFrame(rivit).dropna(subset=["date"])
    return df


class LataaResult:
    def __init__(self):
        self.data = pd.DataFrame()
        self.yritetyt_url: list[str] = []
        self.onnistunut_url: str | None = None


def lataa_diag(liiga: str, kaudet: list[str]) -> LataaResult:
    """Lataa data ja palauta diagnostiikka."""
    res = LataaResult()
    if liiga not in TOURNAMENT_CODES:
        return res
    palaset = []
    for k in kaudet:
        kausi_url = _kausi_to_url(k)
        loytyi = False
        for code in TOURNAMENT_CODES[liiga]:
            url = f"https://raw.githubusercontent.com/openfootball/football.json/master/{kausi_url}/{code}.json"
            res.yritetyt_url.append(url)
            cache = CACHE_DIR / f"{code}_{kausi_url}.json"
            data = _hae_json(url, cache)
            if data:
                d = _parse_data(data, liiga, k)
                if not d.empty:
                    palaset.append(d)
                    res.onnistunut_url = url
                    loytyi = True
                    break
    if palaset:
        res.data = pd.concat(palaset, ignore_index=True)
    return res


def lataa(liiga: str, kaudet: list[str]) -> pd.DataFrame:
    return lataa_diag(liiga, kaudet).data


def tuetut_liigat() -> list[str]:
    return sorted(TOURNAMENT_CODES.keys())
