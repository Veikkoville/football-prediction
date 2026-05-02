"""
Edistyneita piirteita — head-to-head, koti/vieras-form erikseen, momentum.

Naita kaytetaan LightGBM-mallin parantamiseen perus-rolling-piirteiden lisaksi.
"""

from __future__ import annotations
import numpy as np
import pandas as pd


def koti_vieras_form(df: pd.DataFrame, ikkuna: int = 5) -> pd.DataFrame:
    """
    Joukkueen koti- ja vierasform erikseen — joukkueet pelaavat usein eri
    tavoin kotona/vieraissa.

    Vaatii: laajenna_per_joukkue-tuotos jossa is_home, goals_for, goals_against.
    Lisaa: home_goals_for_rolling, away_goals_for_rolling, ja samat against.
    """
    df = df.sort_values(["team", "date"]).copy()

    # Koti: vain otteluita is_home==1
    koti_data = df[df["is_home"] == 1][["team", "date", "goals_for", "goals_against"]].copy()
    koti_data = koti_data.sort_values(["team", "date"])
    koti_data["home_gf_rolling"] = (
        koti_data.groupby("team")["goals_for"].shift(1)
        .rolling(ikkuna, min_periods=1).mean().reset_index(drop=True)
    )
    koti_data["home_ga_rolling"] = (
        koti_data.groupby("team")["goals_against"].shift(1)
        .rolling(ikkuna, min_periods=1).mean().reset_index(drop=True)
    )

    vieras_data = df[df["is_home"] == 0][["team", "date", "goals_for", "goals_against"]].copy()
    vieras_data = vieras_data.sort_values(["team", "date"])
    vieras_data["away_gf_rolling"] = (
        vieras_data.groupby("team")["goals_for"].shift(1)
        .rolling(ikkuna, min_periods=1).mean().reset_index(drop=True)
    )
    vieras_data["away_ga_rolling"] = (
        vieras_data.groupby("team")["goals_against"].shift(1)
        .rolling(ikkuna, min_periods=1).mean().reset_index(drop=True)
    )

    # Yhdista takaisin paatauluun
    df = df.merge(
        koti_data[["team", "date", "home_gf_rolling", "home_ga_rolling"]],
        on=["team", "date"], how="left",
    )
    df = df.merge(
        vieras_data[["team", "date", "away_gf_rolling", "away_ga_rolling"]],
        on=["team", "date"], how="left",
    )
    return df


def head_to_head_piirteet(matches: pd.DataFrame, ikkuna_vuotta: int = 3) -> pd.DataFrame:
    """
    Lisaa H2H-piirteet ottelutason DataFrameen.

    h2h_home_wins, h2h_draws, h2h_away_wins, h2h_avg_total_goals
    laskettuina viimeisimmista <ikkuna_vuotta> vuoden ottelukohtaisista
    kohtaamisista (kotijoukkueen ja vierasjoukkueen valilla).
    """
    df = matches.copy().sort_values("date")
    df["date"] = pd.to_datetime(df["date"])

    rivit = []
    for i, ottelu in df.iterrows():
        koti, vieras = ottelu["home_team"], ottelu["away_team"]
        ottelu_pvm = ottelu["date"]
        raja = ottelu_pvm - pd.Timedelta(days=ikkuna_vuotta * 365)

        aiemmat = df[
            (df["date"] < ottelu_pvm) &
            (df["date"] >= raja) &
            (
                ((df["home_team"] == koti) & (df["away_team"] == vieras)) |
                ((df["home_team"] == vieras) & (df["away_team"] == koti))
            )
        ]

        if aiemmat.empty:
            rivit.append({"h2h_home_wins": 0, "h2h_draws": 0, "h2h_away_wins": 0,
                          "h2h_avg_total_goals": 2.5, "h2h_n": 0})
            continue

        h_wins = d_count = a_wins = 0
        total_goals = 0
        for _, m in aiemmat.iterrows():
            on_koti = (m["home_team"] == koti)
            koti_g = m["home_score"] if on_koti else m["away_score"]
            vieras_g = m["away_score"] if on_koti else m["home_score"]
            total_goals += m["home_score"] + m["away_score"]
            if koti_g > vieras_g:
                h_wins += 1
            elif koti_g == vieras_g:
                d_count += 1
            else:
                a_wins += 1
        n = len(aiemmat)
        rivit.append({
            "h2h_home_wins": h_wins / n,
            "h2h_draws": d_count / n,
            "h2h_away_wins": a_wins / n,
            "h2h_avg_total_goals": total_goals / n,
            "h2h_n": n,
        })

    h2h_df = pd.DataFrame(rivit, index=df.index)
    return pd.concat([df, h2h_df], axis=1)


def points_form(df: pd.DataFrame, ikkuna: int = 5) -> pd.DataFrame:
    """
    Lisaa points_per_game viime N ottelusta — pelisuoritus-kompaktio.
    Vaatii laajenna_per_joukkue-tuotos.
    """
    df = df.sort_values(["team", "date"]).copy()
    df["match_points"] = np.where(
        df["goals_for"] > df["goals_against"], 3,
        np.where(df["goals_for"] == df["goals_against"], 1, 0),
    )
    df["points_form"] = (
        df.groupby("team")["match_points"]
        .shift(1).rolling(ikkuna, min_periods=1).mean().reset_index(drop=True)
    )
    return df


def momentum(df: pd.DataFrame, ikkuna_lyh: int = 3, ikkuna_pit: int = 10) -> pd.DataFrame:
    """
    Momentum = lyhyt-rolling - pitka-rolling.
    Positiivinen = joukkue parantanut viime aikoina, negatiivinen = laskussa.
    """
    df = df.sort_values(["team", "date"]).copy()
    for sarake in ["goals_for", "goals_against"]:
        lyh = df.groupby("team")[sarake].shift(1).rolling(ikkuna_lyh, min_periods=1).mean()
        pit = df.groupby("team")[sarake].shift(1).rolling(ikkuna_pit, min_periods=1).mean()
        df[f"{sarake}_momentum"] = (lyh - pit).reset_index(drop=True)
    return df
