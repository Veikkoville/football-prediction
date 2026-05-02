"""Pelaajaspesifinen poissaolovaikutus joukkueen xG:hen."""

from __future__ import annotations
import pandas as pd


def laske_poissaolovaikutus(
    pelaajat: pd.DataFrame,
    joukkue: str,
    poissa_pelaajat: list[str],
    minuutit_col: str | None,
    xg_col: str,
    team_col: str = "team",
    player_col: str = "player",
) -> dict:
    """
    Laske kuinka monta % joukkueen totaali-xG:sta poissa olevat pelaajat tuottavat.

    Idea: jos pelaaja tuottaa 25% joukkueen xG:sta ja on poissa, joukkueen
    odotettu xG laskee likimaarin 25% (olettaen ettei 1:1 korvattava korvaaja).
    Realistisesti vahennys on hieman pienempi (korvaaja on usein joukkueen
    seuraavaksi paras vaihtoehto), siksi taman jalkeen kerrotaan 0.7:lla.
    """
    if not poissa_pelaajat:
        return {"prosentti": 0.0, "absoluuttinen_xg": 0.0, "joukkueen_xg": 0.0}

    j_pelaajat = pelaajat[pelaajat[team_col] == joukkue].copy()
    j_pelaajat[xg_col] = pd.to_numeric(j_pelaajat[xg_col], errors="coerce").fillna(0)
    if minuutit_col and minuutit_col in j_pelaajat.columns:
        j_pelaajat[minuutit_col] = pd.to_numeric(j_pelaajat[minuutit_col], errors="coerce").fillna(0)

    joukkueen_total_xg = j_pelaajat[xg_col].sum()
    if joukkueen_total_xg <= 0:
        return {"prosentti": 0.0, "absoluuttinen_xg": 0.0, "joukkueen_xg": 0.0}

    poissa = j_pelaajat[j_pelaajat[player_col].isin(poissa_pelaajat)]
    if poissa.empty:
        return {"prosentti": 0.0, "absoluuttinen_xg": 0.0, "joukkueen_xg": joukkueen_total_xg}

    poissa_xg = poissa[xg_col].sum()
    raaka_pct = poissa_xg / joukkueen_total_xg

    # Korvaaja-shrinkage: korvaava pelaaja tuottaa ~30% poissa olevan xG:sta
    KORVAUS_TEHO = 0.3
    nettovaikutus = raaka_pct * (1 - KORVAUS_TEHO)

    return {
        "prosentti": float(nettovaikutus * 100),
        "absoluuttinen_xg": float(poissa_xg),
        "joukkueen_xg": float(joukkueen_total_xg),
        "raaka_prosentti": float(raaka_pct * 100),
    }
