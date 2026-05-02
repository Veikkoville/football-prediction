"""
Joukkuetason piirteet ottelutason ennustamista varten.

Avain-idea: jokaiselle ottelulle lasketaan **kotijoukkueen ja
vierasjoukkueen "muoto"** ENNEN ottelua — viime N ottelun rolling-keskiarvo
mittareista kuten xG, xGA, maalit, hallinta jne. Näin malli ei käytä
"tulevaisuuden" tietoa.

Tärkein periaate:
    Aina kun käytät ottelun X piirteissä mitä tahansa lukuarvoa, varmista
    että se on laskettu **ennen** ottelun X alkua. Muuten malli näyttää
    epärealistisen hyvältä validointijoukossa, mutta mokaa tuotannossa.
"""

from __future__ import annotations

import pandas as pd


# ---------------------------------------------------------------------------
# 1. Pitkästä → leveään muotoon
# ---------------------------------------------------------------------------
def laajenna_per_joukkue(ottelut: pd.DataFrame) -> pd.DataFrame:
    """
    Muunna ottelutason data (1 rivi/ottelu) joukkue-ottelu -muotoon
    (2 riviä/ottelu — yksi koti, yksi vieras).

    Tämä helpottaa rolling-piirteiden laskemista (groupby team).
    """
    koti = ottelut.copy()
    koti["team"] = koti["home_team"]
    koti["opponent"] = koti["away_team"]
    koti["is_home"] = 1
    koti["goals_for"] = koti["home_score"]
    koti["goals_against"] = koti["away_score"]

    vieras = ottelut.copy()
    vieras["team"] = vieras["away_team"]
    vieras["opponent"] = vieras["home_team"]
    vieras["is_home"] = 0
    vieras["goals_for"] = vieras["away_score"]
    vieras["goals_against"] = vieras["home_score"]

    yhdessa = pd.concat([koti, vieras], ignore_index=True)
    return yhdessa.sort_values(["team", "date"]).reset_index(drop=True)


# ---------------------------------------------------------------------------
# 2. Rolling-piirteet
# ---------------------------------------------------------------------------
def rolling_keskiarvo(
    df: pd.DataFrame,
    sarakkeet: list[str],
    ikkuna: int = 5,
    group_col: str = "team",
) -> pd.DataFrame:
    """
    Lisää rolling-keskiarvopiirteet ``ikkuna``-kokoiselta liukuvalta ikkunalta.

    Käytämme `shift(1)` ennen rolling-ikkunaa, jotta nykyinen ottelu EI
    sisälly omiin piirteisiinsä. Tämä on kriittistä leakage-eston kannalta.

    Parametrit
    ----------
    df : DataFrame
        Sisältää ainakin ``team``, ``date`` ja annetut ``sarakkeet``.
    sarakkeet : list[str]
        Sarakkeet joista rolling-keskiarvo lasketaan.
    ikkuna : int
        Kuinka monta edellistä ottelua otetaan mukaan.
    """
    df = df.sort_values([group_col, "date"]).copy()
    for s in sarakkeet:
        uusi = f"{s}_rolling{ikkuna}"
        df[uusi] = (
            df.groupby(group_col)[s]
            .shift(1)
            .rolling(ikkuna, min_periods=1)
            .mean()
            .reset_index(drop=True)
        )
    return df


# ---------------------------------------------------------------------------
# 3. Yhdistä koti + vieras takaisin yhdeksi otteluriviksi
# ---------------------------------------------------------------------------
def yhdista_ottelutasolle(
    joukkue_ottelu_df: pd.DataFrame,
    piirre_sarakkeet: list[str],
) -> pd.DataFrame:
    """
    Pakkaa joukkue-ottelu -taulu takaisin ottelutasolle:
    yksi rivi per ottelu, ``home_*`` ja ``away_*`` -piirresarakkeet.

    Tämä on muoto, jota mallit (LightGBM, Dixon-Coles) syövät.
    """
    koti = (
        joukkue_ottelu_df[joukkue_ottelu_df["is_home"] == 1]
        .copy()
        .rename(columns={p: f"home_{p}" for p in piirre_sarakkeet})
    )
    vieras = (
        joukkue_ottelu_df[joukkue_ottelu_df["is_home"] == 0]
        .copy()
        .rename(columns={p: f"away_{p}" for p in piirre_sarakkeet})
    )
    avaimet = ["date", "home_team", "away_team"]
    pidettavat_koti = avaimet + [f"home_{p}" for p in piirre_sarakkeet] + ["goals_for", "goals_against"]
    pidettavat_vieras = avaimet + [f"away_{p}" for p in piirre_sarakkeet]

    koti = koti[pidettavat_koti].rename(
        columns={"goals_for": "home_score", "goals_against": "away_score"}
    )
    vieras = vieras[pidettavat_vieras]

    yhdistetty = koti.merge(vieras, on=avaimet, how="inner")
    return yhdistetty


# ---------------------------------------------------------------------------
# 4. Tulos-luokka 1X2
# ---------------------------------------------------------------------------
def lisaa_1x2(df: pd.DataFrame) -> pd.DataFrame:
    """Lisää ``result_1x2`` -sarake (0 = koti, 1 = tasapeli, 2 = vieras)."""
    df = df.copy()
    erotus = df["home_score"] - df["away_score"]
    df["result_1x2"] = 1  # X
    df.loc[erotus > 0, "result_1x2"] = 0  # 1
    df.loc[erotus < 0, "result_1x2"] = 2  # 2
    return df


def lisaa_total_goals(df: pd.DataFrame) -> pd.DataFrame:
    """Lisää ``total_goals`` -sarake Over/Under -mallia varten."""
    df = df.copy()
    df["total_goals"] = df["home_score"] + df["away_score"]
    df["btts"] = ((df["home_score"] > 0) & (df["away_score"] > 0)).astype(int)
    return df
