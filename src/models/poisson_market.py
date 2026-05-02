"""Poisson-mallit korner-/korttimarkkinoille (yli/alle, BTTS-tyyppiset)."""

from __future__ import annotations
import pandas as pd
from scipy.stats import poisson


def keskiarvo_per_joukkue(df: pd.DataFrame, sarake_h: str, sarake_a: str) -> dict:
    """Laske joukkuekohtaiset keskiarvot kotona ja vieraissa."""
    res = {}
    for tiimit, sarake in [("home", sarake_h), ("away", sarake_a)]:
        if sarake not in df.columns:
            continue
        ka = (
            df.dropna(subset=[sarake])
            .groupby("home_team" if tiimit == "home" else "away_team")[sarake]
            .mean()
            .to_dict()
        )
        res[tiimit] = ka
    return res


def ennusta_poisson_yli_alle(
    lambda_total: float, line: float = 9.5, max_n: int = 30
) -> dict:
    """P(yli line), P(alle line) Poissonista parametri lambda_total."""
    p_alle = sum(poisson.pmf(k, lambda_total) for k in range(int(line) + 1))
    p_yli = 1.0 - p_alle
    return {"yli": float(p_yli), "alle": float(p_alle)}


class CornerCardModel:
    """Yksinkertainen Poisson-pohjainen korner-/korttiennustemalli."""

    def __init__(self):
        self.korner_home_avg: dict = {}
        self.korner_away_avg: dict = {}
        self.kortti_home_avg: dict = {}
        self.kortti_away_avg: dict = {}
        self.global_corner_total: float = 10.5
        self.global_card_total: float = 4.0

    def fit(self, df: pd.DataFrame):
        df = df.copy()
        if "home_corners" in df.columns and "away_corners" in df.columns:
            self.korner_home_avg = df.groupby("home_team")["home_corners"].mean().to_dict()
            self.korner_away_avg = df.groupby("away_team")["away_corners"].mean().to_dict()
            self.global_corner_total = float(
                (df["home_corners"] + df["away_corners"]).mean()
            )
        if "home_yellow" in df.columns and "away_yellow" in df.columns:
            self.kortti_home_avg = df.groupby("home_team")["home_yellow"].mean().to_dict()
            self.kortti_away_avg = df.groupby("away_team")["away_yellow"].mean().to_dict()
            self.global_card_total = float(
                (df["home_yellow"] + df["away_yellow"]).mean()
            )
        return self

    def ennusta_kornerit(self, koti: str, vieras: str, line: float = 9.5) -> dict:
        h = self.korner_home_avg.get(koti, self.global_corner_total / 2)
        a = self.korner_away_avg.get(vieras, self.global_corner_total / 2)
        lam_total = h + a
        return {
            "lambda_home": h, "lambda_away": a, "lambda_total": lam_total,
            **ennusta_poisson_yli_alle(lam_total, line),
        }

    def ennusta_kortit(self, koti: str, vieras: str, line: float = 4.5) -> dict:
        h = self.kortti_home_avg.get(koti, self.global_card_total / 2)
        a = self.kortti_away_avg.get(vieras, self.global_card_total / 2)
        lam_total = h + a
        return {
            "lambda_home": h, "lambda_away": a, "lambda_total": lam_total,
            **ennusta_poisson_yli_alle(lam_total, line),
        }
