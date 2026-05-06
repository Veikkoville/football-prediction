"""
xG-trendien visualisoinnit (Understat-data).

Yleisimmät plotit jalkapalloanalytiikassa:
  1. Rolling xG / xGA -aikasarja per joukkue
  2. xG kumuloituvasti yhdessä ottelussa ("xG race")
  3. Pelaajan laukauskartta xG:llä
"""

from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def plot_rolling_xg(
    aikasarja: pd.DataFrame,
    joukkue: str,
    ikkuna: int = 5,
    ax: plt.Axes | None = None,
):
    """
    Piirrä rolling N-ottelun xG ja xGA -aikasarja.

    `aikasarja`: tulee funktiosta ``src.data.understat.joukkueen_xg_aikasarja``
    sarakkeilla ``game_id``, ``xG``, ``xGA``.
    """
    if ax is None:
        _, ax = plt.subplots(figsize=(10, 5))

    df = aikasarja.copy().reset_index(drop=True)
    df["xG_roll"] = df["xG"].rolling(ikkuna, min_periods=1).mean()
    df["xGA_roll"] = df["xGA"].rolling(ikkuna, min_periods=1).mean()

    x = np.arange(len(df))
    ax.plot(x, df["xG_roll"], label=f"xG (rolling-{ikkuna})", linewidth=2.5)
    ax.plot(x, df["xGA_roll"], label=f"xGA (rolling-{ikkuna})", linewidth=2.5)
    ax.fill_between(x, df["xG_roll"], df["xGA_roll"],
                    where=(df["xG_roll"] >= df["xGA_roll"]),
                    alpha=0.2, label="xG > xGA")

    ax.set_title(f"{joukkue} — rolling xG / xGA -trendi", fontsize=13)
    ax.set_xlabel("Ottelu (kronologinen järjestys)")
    ax.set_ylabel("xG / xGA")
    ax.legend(loc="best")
    ax.grid(alpha=0.3)
    return ax


def plot_xg_race(
    laukaukset_ottelusta: pd.DataFrame,
    home_team: str,
    away_team: str,
    ax: plt.Axes | None = None,
):
    """
    Piirrä yhden ottelun "xG race" — xG kumuloituvasti minuuteittain.
    """
    if ax is None:
        _, ax = plt.subplots(figsize=(10, 5))

    h = laukaukset_ottelusta[laukaukset_ottelusta["team"] == home_team].copy()
    a = laukaukset_ottelusta[laukaukset_ottelusta["team"] == away_team].copy()

    for df, joukkue in [(h, home_team), (a, away_team)]:
        df = df.sort_values("minute")
        df["cum_xG"] = df["xG"].cumsum()
        # Step-plot näyttää selkeämmin laukauskohtaisen "hypyn"
        ax.step(df["minute"], df["cum_xG"], where="post", label=joukkue,
                linewidth=2.5)
        # Maalit erikseen pisteinä
        maalit = df[df["result"] == "Goal"]
        ax.scatter(maalit["minute"], maalit["cum_xG"],
                   s=100, zorder=5, edgecolor="black")

    ax.set_xlim(0, 95)
    ax.set_xlabel("Minuutti")
    ax.set_ylabel("Kumulatiivinen xG")
    ax.set_title(f"xG race — {home_team} vs {away_team}", fontsize=13)
    ax.legend(loc="best")
    ax.grid(alpha=0.3)
    return ax


def plot_shot_heatmap(
    laukaukset: pd.DataFrame,
    joukkue: str | None = None,
    ax: plt.Axes | None = None,
    cmap: str = "Reds",
):
    """
    Piirra laukausten LAMPOKARTTA jalkapallokentalla.

    Tama on tehokkaampi kuin scatter kun laukauksia paljon — alueet jotka
    saavat eniten laukauksia tulevat tummempina. Voi vertailla joukkueen
    hyokkayksen "tiheyspaikkoja".

    Vaatii mplsoccer:n.
    """
    df = laukaukset.copy()
    if joukkue and "team" in df.columns:
        df = df[df["team"] == joukkue]
    if df.empty:
        raise ValueError(f"Ei laukauksia joukkueelle '{joukkue}'")

    # Etsi sarakkeet — soccerdatan versiot vaihtelevat
    # Tunnetut variantit: X/Y, x/y, shot_x/shot_y, location_x/location_y
    KOORDINAATTI_KANDIDAATIT = [
        ("X", "Y"),
        ("x", "y"),
        ("shot_x", "shot_y"),
        ("location_x", "location_y"),
        ("x_coord", "y_coord"),
        ("X_coord", "Y_coord"),
    ]
    x_col, y_col = None, None
    for xc, yc in KOORDINAATTI_KANDIDAATIT:
        if xc in df.columns and yc in df.columns:
            x_col, y_col = xc, yc
            break

    # Fallback: etsi yhden kirjaimen sarakkeet jotka voisivat olla koordinaatteja
    if not x_col:
        x_kandidaatit = [c for c in df.columns
                         if isinstance(c, str) and c.lower() in ("x", "shot_x", "x_pos")]
        y_kandidaatit = [c for c in df.columns
                         if isinstance(c, str) and c.lower() in ("y", "shot_y", "y_pos")]
        if x_kandidaatit and y_kandidaatit:
            x_col, y_col = x_kandidaatit[0], y_kandidaatit[0]

    if not x_col or not y_col:
        raise ValueError(
            f"X/Y-koordinaatteja ei loytynyt. Kaikki saatavilla olevat sarakkeet: "
            f"{', '.join(str(c) for c in df.columns)}"
        )

    xg_col = next((c for c in ["xG", "xg"] if c in df.columns), None)
    result_col = next((c for c in ["result", "Result"] if c in df.columns), None)

    from mplsoccer import VerticalPitch
    pitch = VerticalPitch(
        half=True, pitch_type="opta",
        line_color="white", pitch_color="#0d4f3c", linewidth=1.5,
    )
    if ax is None:
        fig, ax = pitch.draw(figsize=(7, 9))

    # Understatin x/y on normalisoitu 0-1; muunna Opta-skaalaan (0-100)
    x_vals = pd.to_numeric(df[x_col], errors="coerce") * 100
    y_vals = pd.to_numeric(df[y_col], errors="coerce") * 100
    valid = x_vals.notna() & y_vals.notna()
    x_vals = x_vals[valid]
    y_vals = y_vals[valid]

    # Lampokartta — tiheys laukausten sijainneista
    bin_x = pitch.bin_statistic(
        x_vals.values, y_vals.values, statistic="count", bins=(8, 8),
    )
    pitch.heatmap(bin_x, ax=ax, cmap=cmap, edgecolors="white", alpha=0.7)

    # Paalle laukaukset & maalit erottuvana
    df_v = df.loc[valid]
    if result_col:
        maalit = df_v[result_col].astype(str).str.lower() == "goal"
    else:
        maalit = pd.Series([False] * len(df_v), index=df_v.index)
    pitch.scatter(x_vals[~maalit], y_vals[~maalit], s=30, ax=ax,
                  alpha=0.6, color="white", edgecolor="black", linewidth=0.5)
    pitch.scatter(x_vals[maalit], y_vals[maalit], s=120, ax=ax,
                  color="yellow", edgecolor="black", linewidth=1.5,
                  marker="*", label="Maali", zorder=5)

    otsikko = "Laukauskeskittyma"
    if joukkue:
        otsikko += f" — {joukkue}"
    ax.set_title(otsikko, fontsize=13, color="white", weight="bold")
    return ax


def plot_laukauskartta(
    laukaukset: pd.DataFrame,
    pelaaja: str | None = None,
    joukkue: str | None = None,
    ax: plt.Axes | None = None,
):
    """
    Piirrä laukauskartta — käyttää mplsoccer-kirjastoa jalkapallokenttään.

    Jos `mplsoccer` ei ole asennettuna, piirretään yksinkertainen scatter.
    """
    df = laukaukset.copy()
    if pelaaja:
        df = df[df["player"] == pelaaja]
    if joukkue:
        df = df[df["team"] == joukkue]

    try:
        from mplsoccer import VerticalPitch
        pitch = VerticalPitch(half=True, pitch_type="opta")
        if ax is None:
            fig, ax = pitch.draw(figsize=(7, 9))
        else:
            pitch.draw(ax=ax)
        # Understatin x/y on normalisoitu 0-1; muunna Opta-skaalaan (0-100)
        x = df["X"] * 100
        y = df["Y"] * 100
        size = (df["xG"] * 800).clip(20, 800)
        maalit = df["result"] == "Goal"
        pitch.scatter(x[~maalit], y[~maalit], s=size[~maalit], ax=ax,
                      alpha=0.5, color="C0", label="Laukaus")
        pitch.scatter(x[maalit], y[maalit], s=size[maalit], ax=ax,
                      color="red", edgecolor="black", label="Maali")
    except ImportError:
        # Fallback: tavallinen scatter
        if ax is None:
            _, ax = plt.subplots(figsize=(7, 9))
        ax.scatter(df["X"], df["Y"], s=(df["xG"] * 500).clip(20, 500),
                   c=(df["result"] == "Goal"), cmap="RdYlBu_r", alpha=0.6)
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)

    ax.legend(loc="lower right")
    otsikko = "Laukauskartta"
    if pelaaja:
        otsikko += f" — {pelaaja}"
    elif joukkue:
        otsikko += f" — {joukkue}"
    ax.set_title(otsikko, fontsize=13)
    return ax
