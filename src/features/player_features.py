"""
Pelaajatason piirteet.

Lähestymistapa: per-90 -arvot (skaalataan minuutteihin) plus rolling-form.
Tämä on yksinkertainen mutta tehokas baseline. Edistyneempiä malleja varten
tutustu hierarkkisiin Bayes-malleihin tai pelaajaspesifeihin xG-mukautuksiin.
"""

from __future__ import annotations

import pandas as pd


def per_90(df: pd.DataFrame, sarakkeet: list[str], minuutit_col: str = "minutes") -> pd.DataFrame:
    """
    Lisää ``<sarake>_per90`` -sarakkeet annetuista määrällisistä mittareista.

    Esim. xG, xA, kpl (key passes), shots, sca, ...
    """
    df = df.copy()
    minuutit = df[minuutit_col].replace(0, pd.NA)
    for s in sarakkeet:
        df[f"{s}_per90"] = df[s] * 90.0 / minuutit
    return df


def vastustajan_taso(
    pelaajat: pd.DataFrame,
    joukkue_xga: pd.DataFrame,
    pelaaja_joukkue_col: str = "team",
    vastustaja_col: str = "opponent",
) -> pd.DataFrame:
    """
    Painota pelaajan ennusteita vastustajan puolustustasolla.

    `joukkue_xga` on DataFrame, jossa joukkueen kausittainen
    xGA/ottelu (vastaanotettu xG). Mitä korkeampi, sitä helpompi vastustaja.
    """
    skaalattu = pelaajat.merge(
        joukkue_xga.rename(columns={"team": vastustaja_col, "xGA_per_match": "opp_xGA_per_match"}),
        on=vastustaja_col,
        how="left",
    )
    # Liigan keskiarvo, johon normalisoidaan.
    keskimaara = skaalattu["opp_xGA_per_match"].mean()
    skaalattu["opp_strength_factor"] = skaalattu["opp_xGA_per_match"] / keskimaara
    return skaalattu


def odotetut_minuutit(
    pelaaja_historia: pd.DataFrame,
    ikkuna: int = 5,
) -> pd.DataFrame:
    """
    Arvioi pelaajan **odotetut minuutit** seuraavaan otteluun.

    Yksinkertainen lähtötaso: viime ``ikkuna`` ottelun keskiarvo. Tämä on
    yllättävän vahva ennustaja, koska valmentajat suosivat vakiintunutta
    aloituskokoonpanoa.
    """
    pelaaja_historia = pelaaja_historia.sort_values(["player", "date"]).copy()
    pelaaja_historia["expected_minutes"] = (
        pelaaja_historia.groupby("player")["minutes"]
        .shift(1)
        .rolling(ikkuna, min_periods=1)
        .mean()
        .reset_index(drop=True)
    )
    return pelaaja_historia
