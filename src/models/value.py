"""
Vetokerroin- ja value-laskuri.

Vetokerroin (decimal odds) ja todennäköisyys ovat käänteislukuja:
  p_implisit = 1 / odds

Markkinakerroin sisältää aina marginaalin (overround):
  sum(1/odds) > 1.0   →   marginaali = sum(1/odds) - 1

Mallin "edge":
  edge = p_malli - p_markkina_normalisoitu

Value % (kuinka paljon mallin mukaan pitäisi voittaa pitkässä juoksussa):
  value_pct = (p_malli * odds - 1) * 100

Kelly-criterion (optimaalinen panostuskoko):
  f = (b*p - q) / b   missä b = odds - 1, p = mallin_p, q = 1 - p
  Negatiivinen f = älä panosta. Käytännössä käytetään 1/4 Kellyä riskin pienentämiseen.
"""

from __future__ import annotations


def implisit_p(odds: float) -> float:
    """Kertoimesta implisiittinen todennäköisyys."""
    return 1.0 / odds if odds > 0 else 0.0


def normalisoi_kertoimet(odds_dict: dict[str, float]) -> dict[str, float]:
    """
    Poista marginaali — normalisoi kerrointen implisiittiset
    todennäköisyydet summalla 1.0.
    """
    p_raw = {k: implisit_p(v) for k, v in odds_dict.items()}
    s = sum(p_raw.values())
    if s == 0:
        return p_raw
    return {k: v / s for k, v in p_raw.items()}


def marginaali(odds_dict: dict[str, float]) -> float:
    """Vetomyyjän marginaali (overround). Esim. 0.06 = 6 %."""
    return sum(implisit_p(v) for v in odds_dict.values()) - 1.0


def value_pct(p_malli: float, odds: float) -> float:
    """Mallin näkemä value % yhdelle valinnalle."""
    return (p_malli * odds - 1.0) * 100.0


def kelly_fraktio(p_malli: float, odds: float) -> float:
    """
    Optimaalinen panostuskoko bankrollistä (0.0 - 1.0).

    Negatiivinen → ei panostusta. Käytä 1/4 Kellyä turvallisuuden vuoksi:
        suositus = max(0, kelly_fraktio(p, odds) / 4)
    """
    if odds <= 1.0 or p_malli <= 0:
        return 0.0
    b = odds - 1.0
    q = 1.0 - p_malli
    f = (b * p_malli - q) / b
    return float(f)


def vertaile_kertoimia(
    malli_p: dict[str, float],
    markkina_odds: dict[str, float],
) -> list[dict]:
    """
    Tee taulukko: malli vs markkina, edge, value-%, Kelly-suositus.

    `malli_p` ja `markkina_odds` käyttävät samoja avaimia (esim. "home", "draw", "away").
    """
    p_markkina = normalisoi_kertoimet(markkina_odds)
    rivit = []
    for k in malli_p.keys():
        p_m = malli_p[k]
        p_mk = p_markkina.get(k, 0.0)
        odds = markkina_odds.get(k, 0.0)
        kelly = kelly_fraktio(p_m, odds)
        rivit.append({
            "Valinta": k,
            "Markkinakerroin": odds,
            "Markkinan p (norm.)": p_mk,
            "Mallin p": p_m,
            "Mallin reilu kerroin": (1.0 / p_m) if p_m > 0 else float("inf"),
            "Edge": p_m - p_mk,
            "Value %": value_pct(p_m, odds),
            "Kelly (1x)": kelly,
            "Kelly (1/4)": max(0.0, kelly / 4.0),
        })
    return rivit
