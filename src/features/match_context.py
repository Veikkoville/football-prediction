"""
Ottelukohtaiset konteksti-piirteet.

Lasketaan suoraan otteludatasta — eivät vaadi ulkoista lähdettä:

- **rest_days** : päivää edellisestä ottelusta (väsymys/lepo)
- **days_until_next** : päivää seuraavaan otteluun (vrt. rotaatio UCL:n alla)
- **season_progress** : 0.0 - 1.0 missä kohtaa kautta ollaan
- **is_end_of_season** : viimeiset 3 kierrosta (pelaajat säästelevät / ei mitään pelattavaa)
- **league_position** : sarjasijoitus ennen ottelua (vaatii liikkuvan laskennan)

Käytännössä: aja `lisaa_konteksti(joukkue_ottelu_df)` joukkue-ottelu -DataFramelle
ja saat takaisin samat rivit täydennettynä uusilla sarakkeilla.
"""

from __future__ import annotations

import pandas as pd


def lisaa_lepopaivat(df: pd.DataFrame, group_col: str = "team", date_col: str = "date") -> pd.DataFrame:
    """
    Laske kuinka monta päivää joukkueen edellisestä ottelusta on kulunut.

    Käytä joukkue-ottelu -muotoiselle DataFramelle (laajenna_per_joukkue:n tuotos).
    Ensimmäinen ottelu kaudella saa NaN — voit korvata sen 7:llä (oletus-välipäivät).
    """
    df = df.sort_values([group_col, date_col]).copy()
    df[date_col] = pd.to_datetime(df[date_col])

    df["rest_days"] = (
        df.groupby(group_col)[date_col].diff().dt.days
    )
    return df


def lisaa_days_until_next(
    df: pd.DataFrame, group_col: str = "team", date_col: str = "date"
) -> pd.DataFrame:
    """Päiviä seuraavaan otteluun — proxy rotaation ennustamiseen."""
    df = df.sort_values([group_col, date_col]).copy()
    df[date_col] = pd.to_datetime(df[date_col])

    df["days_until_next"] = (
        df.groupby(group_col)[date_col].shift(-1) - df[date_col]
    ).dt.days
    return df


def lisaa_kauden_eteneminen(
    df: pd.DataFrame, season_col: str = "season", date_col: str = "date"
) -> pd.DataFrame:
    """
    Laske 0.0–1.0 -arvo, missä kohtaa kautta ottelu pelataan.
    Hyödyllinen "kausi loppumassa, mitään pelattavaa" -tilanteen tunnistamiseen.
    """
    df = df.copy()
    df[date_col] = pd.to_datetime(df[date_col])

    def laske_progress(g: pd.DataFrame) -> pd.Series:
        alku = g[date_col].min()
        loppu = g[date_col].max()
        kesto = (loppu - alku).days
        if kesto <= 0:
            return pd.Series(0.5, index=g.index)
        return ((g[date_col] - alku).dt.days / kesto).clip(0, 1)

    df["season_progress"] = df.groupby(season_col, group_keys=False).apply(laske_progress)
    df["is_end_of_season"] = (df["season_progress"] >= 0.92).astype(int)
    return df


def lisaa_konteksti(
    joukkue_ottelu_df: pd.DataFrame,
    season_col: str = "season",
    date_col: str = "date",
    team_col: str = "team",
) -> pd.DataFrame:
    """Aja kaikki konteksti-piirteet kerralla."""
    df = lisaa_lepopaivat(joukkue_ottelu_df, group_col=team_col, date_col=date_col)
    df = lisaa_days_until_next(df, group_col=team_col, date_col=date_col)
    df = lisaa_kauden_eteneminen(df, season_col=season_col, date_col=date_col)
    return df
