"""
StatsBomb Open Data — tapahtumatason data.

StatsBomb (https://github.com/statsbomb/open-data) tarjoaa ammattitason
tapahtumadataa avoimena: jokainen syöttö, laukaus, paine, puolustus-
kosketus tarkoilla x/y-koordinaateilla. Tämä on sama data, jota
ammattiseurat käyttävät — vain rajatumpi otos turnauksia.

Saatavilla mm.:
  - MM-kisat 2018, 2022 (sekä naiset 2019, 2023)
  - EM 2020, EM-naiset 2022
  - Champions League finaaleita
  - "Messi-data" (kaikki La Liga -ottelut joissa Messi pelasi)
  - NWSL kaudet 2018-2023
  - Indian Super League jne.

Käytämme virallista `statsbombpy`-Python-kääräistä.

Esimerkki:
    >>> from src.data.statsbomb import listaa_kilpailut, hae_ottelut, hae_tapahtumat
    >>> kilpailut = listaa_kilpailut()
    >>> # MM 2022 -ottelut
    >>> ottelut = hae_ottelut(competition_id=43, season_id=106)
    >>> # Yhden ottelun kaikki tapahtumat
    >>> events = hae_tapahtumat(match_id=ottelut.iloc[0]["match_id"])
"""

from __future__ import annotations

import pandas as pd


def listaa_kilpailut() -> pd.DataFrame:
    """
    Listaa kaikki avoimet kilpailut/kaudet.

    Palauttaa DataFramen sarakkeilla mm.
    ``competition_id``, ``season_id``, ``competition_name``,
    ``season_name``, ``country_name``.
    """
    from statsbombpy import sb
    return sb.competitions()


def hae_ottelut(competition_id: int, season_id: int) -> pd.DataFrame:
    """
    Hae kaikki ottelut tietylle kilpailu-/kausi-yhdistelmälle.

    `competition_id` ja `season_id` saa funktiolta `listaa_kilpailut()`.
    """
    from statsbombpy import sb
    return sb.matches(competition_id=competition_id, season_id=season_id)


def hae_tapahtumat(match_id: int) -> pd.DataFrame:
    """
    Hae yhden ottelun kaikki tapahtumat (eventit) DataFramena.

    Tärkeimmät sarakkeet:
      - ``type`` — "Pass", "Shot", "Pressure", "Carry", ...
      - ``player`` — pelaajan nimi
      - ``team`` — joukkue
      - ``location`` — [x, y] kentän koordinaatit (0-120, 0-80)
      - ``shot_statsbomb_xg`` — laukauksen xG (vain kun type == "Shot")
      - ``pass_end_location`` — syötön päätepiste
      - ``minute``, ``second``
    """
    from statsbombpy import sb
    return sb.events(match_id=match_id)


def hae_360_data(match_id: int) -> pd.DataFrame:
    """
    Hae 360-tason data (pelaajien sijainnit jokaisella tapahtumalla).

    Saatavilla vain osalle otteluista (esim. EURO 2020 alkaen).
    Tämä on raskasta dataa: ottelu voi olla 10+ MB.
    """
    from statsbombpy import sb
    try:
        return sb.frames(match_id=match_id)
    except Exception as e:
        # Jos 360-dataa ei ole, palautetaan tyhjä DataFrame.
        print(f"360-dataa ei saatavilla ottelulle {match_id}: {e}")
        return pd.DataFrame()


def laske_xg_per_joukkue(events: pd.DataFrame) -> pd.DataFrame:
    """
    Aggregoi yhden ottelun StatsBomb-tapahtumat → xG per joukkue.

    Käytännöllinen "ground truth" mallin kalibrointiin:
    StatsBombin xG-malli on yleisesti pidetty yhtenä alan parhaista.
    """
    laukaukset = events[events["type"] == "Shot"].copy()
    if laukaukset.empty:
        return pd.DataFrame(columns=["team", "shots", "xG", "goals"])

    laukaukset["goal"] = (laukaukset["shot_outcome"] == "Goal").astype(int)
    grouped = (
        laukaukset.groupby("team", as_index=False)
        .agg(
            shots=("type", "count"),
            xG=("shot_statsbomb_xg", "sum"),
            goals=("goal", "sum"),
        )
    )
    return grouped
