"""Yhdistetty otteludatan loader: Understat + football-data.co.uk + openfootball + FBref."""

from __future__ import annotations
from typing import Iterable
import pandas as pd
import config

UNDERSTAT_LEAGUES = {
    "ENG-Premier League", "ESP-La Liga", "GER-Bundesliga",
    "ITA-Serie A", "FRA-Ligue 1", "RUS-Premier League",
}

from src.data.footballdata import MAIN_CODES, NEW_FILES, lataa as lataa_fd
FOOTBALLDATA_LEAGUES = set(MAIN_CODES.keys()) | set(NEW_FILES.keys())

from src.data.openfootball import TOURNAMENT_CODES, lataa as lataa_of
from src.data.football_data_org import (
    COMPETITION_CODES as FDORG_CODES,
    lataa as lataa_fdorg,
    api_key_kunnossa,
)
OPENFOOTBALL_LEAGUES = set(TOURNAMENT_CODES.keys())


# Pohjoismaat noudattavat kalenterivuotta — muunna "2526" -> ["2025", "2026"]
KALENTERIVUOSI_LIIGAT = {
    "FIN-Veikkausliiga", "SWE-Allsvenskan", "NOR-Eliteserien",
    "USA-MLS", "BRA-Serie A", "ARG-Primera Division", "JPN-J1 League",
}


def _kausi_to_kalenterivuosi(kausi: str) -> list[str]:
    if len(kausi) == 4:
        a = int("20" + kausi[:2])
        b = int("20" + kausi[2:])
        return [str(y) for y in range(a, b + 1)]
    if len(kausi) == 2:
        return [str(2000 + int(kausi))]
    return [kausi]


class LoaderTulokset:
    def __init__(self):
        self.data = pd.DataFrame()
        self.virheet: dict[str, str] = {}
        self.onnistui: dict[str, int] = {}


def lataa_otteludata_yksityiskohtaisesti(liigat: Iterable[str], kaudet: Iterable[str]) -> LoaderTulokset:
    tulos = LoaderTulokset()
    liigat = list(liigat)
    kaudet = list(kaudet)
    palaset = []

    for liiga in liigat:
        # 1. Understat
        if liiga in UNDERSTAT_LEAGUES:
            try:
                from src.data.understat import lataa_otteludata as lataa_us
                us = lataa_us([liiga], kaudet, cache_dir=config.RAW_DATA_DIR / "understat")
                us = us.rename(columns={"home_goals": "home_score", "away_goals": "away_score"})
                us = us[us["home_score"].notna() & us["away_score"].notna()].copy()
                if us.empty:
                    tulos.virheet[liiga] = "Understat: ei valmiita otteluita."
                    continue
                us["date"] = pd.to_datetime(us["date"])
                us["lahde"] = "Understat"
                cols = ["date", "home_team", "away_team", "home_score", "away_score",
                        "league", "season", "home_xg", "away_xg", "lahde"]
                us = us[[c for c in cols if c in us.columns]].copy()
                palaset.append(us)
                tulos.onnistui[liiga] = len(us)
            except Exception as e:
                tulos.virheet[liiga] = f"Understat: {type(e).__name__}: {e}"
            continue

        # 2a. football-data.org (jos API-avain) — UEFA-turnaukset
        if liiga in FDORG_CODES and api_key_kunnossa():
            try:
                from src.data.football_data_org import COMPETITION_CODES, FREE_TIER
                code = COMPETITION_CODES.get(liiga)
                if code and code not in FREE_TIER:
                    tulos.virheet[liiga] = (
                        f"⚠️ {liiga} (koodi {code}) ei sisally football-data.org "
                        f"ilmaiseen tier:iin. Vaatii Tier One -tilauksen (€10/kk). "
                        f"Vaihtoehto: Champions League toimii ilmaisella avaimella."
                    )
                    continue
                fd = lataa_fdorg(liiga, kaudet)
                if not fd.empty:
                    palaset.append(fd)
                    tulos.onnistui[liiga] = len(fd)
                    continue
                else:
                    tulos.virheet[liiga] = (
                        "football-data.org: API-avaimella ei dataa. "
                        "Ilmainen tier kattaa vain edellinen + nykyinen kausi."
                    )
                    continue
            except Exception as e:
                tulos.virheet[liiga] = f"football-data.org: {type(e).__name__}: {e}"
        # 2b. openfootball — UEFA-turnaukset
        if liiga in OPENFOOTBALL_LEAGUES:
            try:
                from src.data.openfootball import lataa_diag
                res = lataa_diag(liiga, kaudet)
                if res.data.empty:
                    yritetyt = "\n  - ".join(res.yritetyt_url[-6:])
                    tulos.virheet[liiga] = (
                        f"openfootball: ei dataa loytynyt repon polusta. "
                        f"Tarkista openfootball/football.json -repo, onko {liiga} "
                        f"saatavilla. Yritetyt URLit:\n  - " + yritetyt
                    )
                    continue
                palaset.append(res.data)
                tulos.onnistui[liiga] = len(res.data)
            except Exception as e:
                tulos.virheet[liiga] = f"openfootball: {type(e).__name__}: {e}"
            continue

        # 3. football-data.co.uk
        if liiga in FOOTBALLDATA_LEAGUES:
            try:
                # Pohjoismaat: muunna kaudet kalenterivuosiksi
                kayt_kaudet = kaudet
                if liiga in KALENTERIVUOSI_LIIGAT:
                    kayt = []
                    for k in kaudet:
                        kayt.extend(_kausi_to_kalenterivuosi(k))
                    kayt_kaudet = sorted(set(kayt))
                fd = lataa_fd(liiga, kayt_kaudet)
                if fd.empty:
                    tulos.virheet[liiga] = (
                        f"football-data.co.uk: ei dataa kausille {kayt_kaudet}."
                    )
                    continue
                palaset.append(fd)
                tulos.onnistui[liiga] = len(fd)
            except Exception as e:
                tulos.virheet[liiga] = f"football-data.co.uk: {type(e).__name__}: {e}"
            continue

        # 4. Fallback: soccerdata-FBref
        try:
            from src.data.fbref import lataa_otteludata as lataa_fb
            import re
            fb = lataa_fb([liiga], kaudet, cache_dir=config.RAW_DATA_DIR / "fbref")
            if "score" in fb.columns:
                def _p(s):
                    if not isinstance(s, str):
                        return (None, None)
                    m = re.match(r"\s*(\d+)\s*[-–]\s*(\d+)", s)
                    return (int(m.group(1)), int(m.group(2))) if m else (None, None)
                parsed = fb["score"].apply(_p)
                fb["home_score"] = parsed.apply(lambda x: x[0])
                fb["away_score"] = parsed.apply(lambda x: x[1])
            fb = fb[fb["home_score"].notna() & fb["away_score"].notna()].copy()
            if fb.empty:
                tulos.virheet[liiga] = "FBref: tyhja datasetti."
                continue
            fb["date"] = pd.to_datetime(fb["date"])
            fb["lahde"] = "FBref"
            fb["home_xg"] = pd.NA
            fb["away_xg"] = pd.NA
            cols = ["date", "home_team", "away_team", "home_score", "away_score",
                    "league", "season", "home_xg", "away_xg", "lahde"]
            fb = fb[[c for c in cols if c in fb.columns]].copy()
            palaset.append(fb)
            tulos.onnistui[liiga] = len(fb)
        except Exception as e:
            tulos.virheet[liiga] = f"FBref: {type(e).__name__}: {e}"

    if palaset:
        tulos.data = pd.concat(palaset, ignore_index=True).sort_values("date").reset_index(drop=True)
    return tulos


def lataa_otteludata(liigat: Iterable[str], kaudet: Iterable[str]) -> pd.DataFrame:
    return lataa_otteludata_yksityiskohtaisesti(liigat, kaudet).data
