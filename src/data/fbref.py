"""
FBref-datan haku (Sports Reference).

FBref tarjoaa monipuoliset edistyneet tilastot mm. Top-5 Euroopan liigoille,
eurocupeille ja monille muille — mukaan lukien Veikkausliiga ja Pohjoismaat.

Käytämme `soccerdata`-kirjaston `FBref`-luokkaa, joka hoitaa scrapingin,
välimuistin ja datan jäsentelyn puolestamme.

Esimerkki:
    >>> from src.data.fbref import lataa_otteludata
    >>> df = lataa_otteludata(["ENG-Premier League"], ["2425"])
    >>> df.head()
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

import pandas as pd

# soccerdata importataan funktion sisällä, jotta moduulin voi importata
# ilman että kirjasto on asennettu (esim. dokumentaatiota generoidessa).


# ---------------------------------------------------------------------------
# JOUKKUETASON DATA
# ---------------------------------------------------------------------------
def lataa_otteludata(
    leagues: Iterable[str],
    seasons: Iterable[str],
    cache_dir: Path | None = None,
) -> pd.DataFrame:
    """
    Hae ottelukohtainen pohjadata (kotijoukkue, vierasjoukkue, maalit, päivä).

    Parametrit
    ----------
    leagues : iterable[str]
        soccerdata-tunnisteet, esim. ``["ENG-Premier League"]``.
    seasons : iterable[str]
        Kaudet, esim. ``["2324", "2425"]``.
    cache_dir : Path, optional
        Polku jonne soccerdata tallentaa välimuistin (HTML-sivut).
        Oletus: soccerdata käyttää käyttäjän kotihakemistoa.

    Palauttaa
    ---------
    DataFrame
        Sarakkeet sisältävät mm. ``date``, ``home_team``, ``away_team``,
        ``home_score``, ``away_score``, ``league``, ``season``.
    """
    import soccerdata as sd

    fbref = sd.FBref(
        leagues=list(leagues),
        seasons=list(seasons),
        data_dir=cache_dir,
    )
    # read_schedule palauttaa pelilistan, jossa kaikki ottelut + tulokset.
    schedule = fbref.read_schedule().reset_index()
    return schedule


def lataa_joukkueen_kausistatistiikka(
    leagues: Iterable[str],
    seasons: Iterable[str],
    stat_type: str = "standard",
    cache_dir: Path | None = None,
) -> pd.DataFrame:
    """
    Hae joukkueiden kausitilastot (ei ottelutason).

    `stat_type` -vaihtoehdot mm.:
      - ``"standard"`` — perustilastot (maalit, syötöt, xG, ottelut)
      - ``"shooting"`` — laukaisutilastot (laukaukset, xG, np-xG)
      - ``"passing"`` — syöttötilastot
      - ``"defense"`` — puolustustilastot
      - ``"possession"`` — pallonhallinta (PPDA, kosketukset)
      - ``"keeper_adv"`` — maalivahdin kehittyneet tilastot (PSxG)
    """
    import soccerdata as sd

    fbref = sd.FBref(
        leagues=list(leagues),
        seasons=list(seasons),
        data_dir=cache_dir,
    )
    # opponent_stats=False → joukkueiden omat tilastot (ei vastustajien).
    df = fbref.read_team_season_stats(stat_type=stat_type, opponent_stats=False)
    return df.reset_index()


# ---------------------------------------------------------------------------
# OTTELUKOHTAINEN JOUKKUEDATA
# ---------------------------------------------------------------------------
def lataa_ottelukohtainen_data(
    leagues: Iterable[str],
    seasons: Iterable[str],
    stat_type: str = "schedule",
    cache_dir: Path | None = None,
) -> pd.DataFrame:
    """
    Hae jokaiselle ottelulle tilastot, esim. shooting / passing.

    Tämä luo joukkue-x-ottelu-tason rivit, joista voi laskea
    rolling-form -piirteet.

    HUOM: tämä kutsu voi olla hidas (yksi pyyntö per ottelu) — käytä
    vain pienelle ottelumäärälle aluksi.
    """
    import soccerdata as sd

    fbref = sd.FBref(
        leagues=list(leagues),
        seasons=list(seasons),
        data_dir=cache_dir,
    )
    df = fbref.read_team_match_stats(stat_type=stat_type)
    return df.reset_index()


# ---------------------------------------------------------------------------
# PELAAJATASON DATA
# ---------------------------------------------------------------------------
def lataa_pelaajat_kausi(
    leagues: Iterable[str],
    seasons: Iterable[str],
    stat_type: str = "standard",
    cache_dir: Path | None = None,
) -> pd.DataFrame:
    """
    Hae pelaajakohtainen kausistatistiikka.

    Käytetään pelaajaennustemallin pohjadatana (xG/90, xA/90 jne.).
    """
    import soccerdata as sd

    fbref = sd.FBref(
        leagues=list(leagues),
        seasons=list(seasons),
        data_dir=cache_dir,
    )
    df = fbref.read_player_season_stats(stat_type=stat_type)
    return df.reset_index()


# ---------------------------------------------------------------------------
# CSV-VIENTI POWER BI:hin
# ---------------------------------------------------------------------------
def vie_csv(df: pd.DataFrame, polku: str | Path) -> Path:
    """
    Tallenna DataFrame CSV:nä Power BI:tä varten.

    Käytämme `utf-8-sig`-koodausta, jotta Excel/Power BI tunnistavat
    skandit (ä, ö) oikein avattaessa.
    """
    polku = Path(polku)
    polku.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(polku, index=False, encoding="utf-8-sig")
    return polku
