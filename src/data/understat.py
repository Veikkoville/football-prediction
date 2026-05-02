"""
Understat-datan haku.

Understat on ainoa avoin lähde, joka tarjoaa **laukaustason xG-arvot** kuudelle
suurelle liigalle vuodesta 2014 alkaen. Käytämme näitä xG-trendien
visualisointiin ja rolling-form -piirteisiin.

Tuetut liigat:
    EPL, La Liga, Bundesliga, Serie A, Ligue 1, RFPL (Venäjä).
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

import pandas as pd


def lataa_otteludata(
    leagues: Iterable[str],
    seasons: Iterable[str],
    cache_dir: Path | None = None,
) -> pd.DataFrame:
    """
    Hae Understatin ottelutason data: kotixG, vierasxG, maalit jne.

    Liigatunnisteet (Understat-spesifiset):
        ``"ENG-Premier League"``, ``"ESP-La Liga"``, ``"GER-Bundesliga"``,
        ``"ITA-Serie A"``, ``"FRA-Ligue 1"``, ``"RUS-Premier League"``.
    """
    import soccerdata as sd

    us = sd.Understat(
        leagues=list(leagues),
        seasons=list(seasons),
        data_dir=cache_dir,
    )
    df = us.read_schedule().reset_index()
    return df


def lataa_laukaukset(
    leagues: Iterable[str],
    seasons: Iterable[str],
    cache_dir: Path | None = None,
) -> pd.DataFrame:
    """
    Hae jokainen laukaus xG-arvolla varustettuna.

    Sarakkeet:
      - ``minute``, ``player``, ``team``, ``xG``, ``result``,
        ``situation`` (esim. OpenPlay, FromCorner), ``shotType``
        (RightFoot, LeftFoot, Head), ``X``/``Y`` (sijainti normalisoituna).

    Käyttötapauksia:
      - xG-trendien visualisointi joukkueittain
      - Pelaajien laukauskartat
      - "Expected" vs. todelliset maalit -ali-/yli-suorittajat
    """
    import soccerdata as sd

    us = sd.Understat(
        leagues=list(leagues),
        seasons=list(seasons),
        data_dir=cache_dir,
    )
    df = us.read_shot_events().reset_index()
    return df


def joukkueen_xg_aikasarja(
    laukaukset_df: pd.DataFrame,
    joukkue: str,
) -> pd.DataFrame:
    """
    Aggregoi laukaukset ottelutason xG / xGA -aikasarjaksi yhdelle joukkueelle.

    Hyödyllinen visualisointiin (rolling 5-ottelun keskiarvo).
    """
    # soccerdata käyttää sarakenimeä "xg" (pienellä). Tuetaan molempia
    # turvallisuussyistä — vanhempi versio käytti "xG".
    xg_col = "xg" if "xg" in laukaukset_df.columns else "xG"

    omat = (
        laukaukset_df[laukaukset_df["team"] == joukkue]
        .groupby("game_id", as_index=False)
        .agg(xG=(xg_col, "sum"))
    )
    vastustajan = (
        laukaukset_df[laukaukset_df["team"] != joukkue]
        # Suodatetaan vain pelit, joissa joukkue on mukana.
        .merge(
            laukaukset_df[laukaukset_df["team"] == joukkue][["game_id"]].drop_duplicates(),
            on="game_id",
            how="inner",
        )
        .groupby("game_id", as_index=False)
        .agg(xGA=(xg_col, "sum"))
    )
    yhdistetty = omat.merge(vastustajan, on="game_id")
    return yhdistetty.sort_values("game_id").reset_index(drop=True)
