"""football-data.co.uk CSV-loader (mainstream + 'new' tiedostot)."""

from __future__ import annotations
from pathlib import Path
import pandas as pd
import requests

import config

MAIN_CODES = {
    "ENG-Premier League": "E0", "ENG-Championship": "E1",
    "ENG-League One": "E2", "ENG-League Two": "E3",
    "ESP-La Liga": "SP1", "ESP-La Liga 2": "SP2",
    "GER-Bundesliga": "D1", "GER-2. Bundesliga": "D2",
    "ITA-Serie A": "I1", "ITA-Serie B": "I2",
    "FRA-Ligue 1": "F1", "FRA-Ligue 2": "F2",
    "POR-Primeira Liga": "P1", "NED-Eredivisie": "N1",
    "BEL-Pro League": "B1", "SCO-Premiership": "SC0",
    "TUR-Super Lig": "T1", "GRE-Super League": "G1",
}

NEW_FILES = {
    "FIN-Veikkausliiga": "FIN", "SWE-Allsvenskan": "SWE",
    "NOR-Eliteserien": "NOR", "DEN-Superliga": "DNK",
    "USA-MLS": "USA", "MEX-Liga MX": "MEX",
    "JPN-J1 League": "JPN", "BRA-Serie A": "BRA",
    "ARG-Primera Division": "ARG",
}

CACHE_DIR = config.RAW_DATA_DIR / "footballdata"
CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _hae_csv(url: str, cache_path: Path, force: bool = False) -> pd.DataFrame:
    if cache_path.exists() and not force:
        try:
            return pd.read_csv(cache_path, encoding="latin-1")
        except Exception:
            pass
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    cache_path.write_bytes(r.content)
    return pd.read_csv(cache_path, encoding="latin-1")


def _normalisoi(df: pd.DataFrame, liiga: str) -> pd.DataFrame:
    """
    Yhteneva muoto eri football-data.co.uk -CSV:ille.

    Mainstream CSV: HomeTeam, AwayTeam, FTHG, FTAG, Date, Season(meidan lisaama).
    'New' CSV:    Home, Away, HG, AG, Date (Season-sarake on jo CSV:ssa).
    """
    if df.empty:
        return df
    df = df.copy()
    if "Date" not in df.columns:
        return pd.DataFrame()
    df["date"] = pd.to_datetime(df["Date"], dayfirst=True, errors="coerce")

    # Joukkueet: yritetaa molempia formaatteja
    df["home_team"] = df.get("HomeTeam", df.get("Home"))
    df["away_team"] = df.get("AwayTeam", df.get("Away"))

    # Maalit: yritetaa FTHG/FTAG ensin, sitten HG/AG
    h = df.get("FTHG", df.get("HG"))
    a = df.get("FTAG", df.get("AG"))
    df["home_score"] = pd.to_numeric(h, errors="coerce") if h is not None else pd.NA
    df["away_score"] = pd.to_numeric(a, errors="coerce") if a is not None else pd.NA

    if "Season" in df.columns:
        df["season"] = df["Season"].astype(str)
    df["league"] = liiga
    df["home_xg"] = pd.NA
    df["away_xg"] = pd.NA
    df["lahde"] = "football-data.co.uk"

    # Vetokertoimet ja muita lisasarakkeita (kun saatavilla)
    extra_cols_map = {
        "B365H": "odds_home", "B365D": "odds_draw", "B365A": "odds_away",
        "PSH": "ps_home", "PSD": "ps_draw", "PSA": "ps_away",
        "B365>2.5": "odds_over_25", "B365<2.5": "odds_under_25",
        "HC": "home_corners", "AC": "away_corners",
        "HY": "home_yellow", "AY": "away_yellow",
        "HR": "home_red", "AR": "away_red",
        "HS": "home_shots", "AS": "away_shots",
        "HST": "home_shots_target", "AST": "away_shots_target",
        "Referee": "referee",
    }
    for src, dst in extra_cols_map.items():
        if src in df.columns:
            df[dst] = df[src]

    df = df.dropna(subset=["date", "home_team", "away_team", "home_score", "away_score"])
    cols = ["date", "home_team", "away_team", "home_score", "away_score",
            "league", "season", "home_xg", "away_xg", "lahde",
            "odds_home", "odds_draw", "odds_away", "ps_home", "ps_draw", "ps_away",
            "odds_over_25", "odds_under_25",
            "home_corners", "away_corners", "home_yellow", "away_yellow",
            "home_red", "away_red", "home_shots", "away_shots",
            "home_shots_target", "away_shots_target", "referee"]
    return df[[c for c in cols if c in df.columns]].copy()


def lataa_mainstream(liiga: str, kausi: str, force: bool = False) -> pd.DataFrame:
    if liiga not in MAIN_CODES:
        return pd.DataFrame()
    code = MAIN_CODES[liiga]
    url = f"https://www.football-data.co.uk/mmz4281/{kausi}/{code}.csv"
    cache = CACHE_DIR / f"{liiga.replace(' ', '_').replace('-', '_')}_{kausi}.csv"
    try:
        df = _hae_csv(url, cache, force=force)
        df["Season"] = kausi
        return _normalisoi(df, liiga)
    except Exception as e:
        print(f"football-data ({liiga} {kausi}): {e}")
        return pd.DataFrame()


def lataa_new(liiga: str, kaudet: list[str] | None = None, force: bool = False) -> pd.DataFrame:
    if liiga not in NEW_FILES:
        return pd.DataFrame()
    code = NEW_FILES[liiga]
    url = f"https://www.football-data.co.uk/new/{code}.csv"
    cache = CACHE_DIR / f"{liiga.replace(' ', '_').replace('-', '_')}_all.csv"
    try:
        df = _hae_csv(url, cache, force=force)
        df = _normalisoi(df, liiga)
        if kaudet and not df.empty and "season" in df.columns:
            # Joustava match: kausi-merkkijono sisaltaa kalenterivuoden
            kaudet_str = [str(k) for k in kaudet]
            mask = df["season"].astype(str).apply(
                lambda s: any(k in s for k in kaudet_str)
            )
            df = df[mask]
        return df
    except Exception as e:
        print(f"football-data 'new' ({liiga}): {e}")
        return pd.DataFrame()


def lataa(liiga: str, kaudet: list[str], force: bool = False) -> pd.DataFrame:
    if liiga in MAIN_CODES:
        palaset = []
        for k in kaudet:
            d = lataa_mainstream(liiga, k, force=force)
            if not d.empty:
                palaset.append(d)
        return pd.concat(palaset, ignore_index=True) if palaset else pd.DataFrame()
    if liiga in NEW_FILES:
        return lataa_new(liiga, kaudet, force=force)
    return pd.DataFrame()


def tuetut_liigat() -> list[str]:
    return sorted(list(MAIN_CODES.keys()) + list(NEW_FILES.keys()))
