"""
Pelaajatason ennustemallit.

Lähtötaso: per-90 -arvot * odotetut minuutit, painotettuna vastustajan
puolustustasolla. Tämä baseline vastaa hämmästyttävän hyvin julkisia
fantasiaennusteita.

Kun haluat astua eteenpäin, kokeile:
  - Hierarkkinen Bayes-malli (PyMC) — pelaaja, joukkue, liiga -tasoiset priorit
  - xG/xA mallinnetaan erikseen ja käytetään Poisson-jakaumaa
  - Pelipaikkavaikutukset (FW vs MF vs DF)
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import poisson


def ennusta_per90_baseline(
    pelaaja_per90: pd.DataFrame,
    odotetut_minuutit: pd.Series,
    opp_strength: pd.Series | None = None,
    metriikat: tuple[str, ...] = ("xG_per90", "xA_per90"),
) -> pd.DataFrame:
    """
    Ennusta seuraavan ottelun odotusarvot per pelaaja.

    expected_value = per90 * (odotetut_minuutit / 90) * opp_strength_factor
    """
    df = pelaaja_per90.copy()
    if opp_strength is None:
        opp_strength = pd.Series(1.0, index=df.index)

    skaala = (odotetut_minuutit / 90.0) * opp_strength

    for m in metriikat:
        kohde = m.replace("_per90", "")
        df[f"expected_{kohde}"] = df[m].fillna(0.0) * skaala
    return df


def todennakoisyys_pelaaja_skoraa(odotettu_xg: float, n_max: int = 5) -> dict[str, float]:
    """
    Pelaajan odotetusta xG:stä → P(maaleja=k) Poisson-oletuksella.

    Palauttaa myös ``P(maaleja >= 1)`` -markkinan ("anytime scorer").
    """
    p = {f"k={k}": float(poisson.pmf(k, odotettu_xg)) for k in range(n_max + 1)}
    p["anytime_scorer"] = float(1 - poisson.pmf(0, odotettu_xg))
    return p


def kortti_todennakoisyys(
    rolling_kortit_per90: float,
    odotetut_minuutit: float,
    derby_bonus: float = 1.15,
    on_derby: bool = False,
) -> float:
    """
    Karkea arvio pelaajan keltaisen kortin todennäköisyydestä.

    Olettaa Poisson-jakautuman korteille — yliarvioi hieman, koska
    yhteen otteluun mahtuu vain pari korttia.
    """
    odotettu = rolling_kortit_per90 * (odotetut_minuutit / 90.0)
    if on_derby:
        odotettu *= derby_bonus
    # P(vähintään yksi)
    return float(1 - poisson.pmf(0, odotettu))
