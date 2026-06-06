"""martj42/international_results -pohjainen maaotteludata WC-mallille (#79).

Vendoroitu CSV (data/international_results.csv, CC0). EI live-pullia ajossa —
snapshot virkistetään scripts/update_international_results.py:llä + redeploy.

Korvaa pelkän WC 2018/2022 -pohjan: /api/predict-wc -malli treenataan kaikkien
48 WC 2026 -maan tuoreista maaotteluista (WC-karsinnat, Nations League,
konfederaatiokisat, friendlyt). Kilpailu-paino (competition_weights) viedään
DixonColesModel.fit():iin tournament-sarakkeen kautta.
"""
from __future__ import annotations

import pandas as pd

import config

CSV_PATH = config.DATA_DIR / "international_results.csv"

# Loader-liigatunnus jolla tämä lähde reititetään (sama kuin ennen → frontend
# + cache-avaimet pysyvät yhteensopivina; vain datalähde vaihtuu).
LEAGUE_LABEL = "INT-World Cup"

# Oletus-aikaikkuna. Backtest (#79 vaihe 5) valitsee lopullisen; decay hoitaa
# recency-painotuksen ikkunan sisällä. "any"-moodi antaa per maa ~38-77 ottelua
# (2022→) tai ~22-45 (2024→).
DEFAULT_WINDOW_START = "2022-01-01"

# Kuinka ottelu valitaan otokseen:
#   "any"  = vähintään toinen joukkue on WC2026-maa (rikkaampi otos + ristikkäis-
#            konfederaatiokalibrointi sparrausvastustajien kautta).
#   "both" = vain WC-maa vs WC-maa (pienempi, nopeampi fit).
DEFAULT_INCLUDE = "any"

# Kilpailu-paino per ottelu (competition_weights). Kilpailulliset ottelut
# painavat enemmän kuin friendlyt. Tuntematon kilpailu → DEFAULT.
COMPETITION_WEIGHTS: dict[str, float] = {
    # Tier top — kilpailulliset huiput
    "FIFA World Cup": 1.0,
    "FIFA World Cup qualification": 1.0,
    "UEFA Nations League": 1.0,
    "CONCACAF Nations League": 1.0,
    "UEFA Euro": 1.0,
    "Copa América": 1.0,
    "African Cup of Nations": 1.0,
    "AFC Asian Cup": 1.0,
    "Gold Cup": 0.9,
    # Tier mid — karsinnat + muut konfederaatiokisat
    "UEFA Euro qualification": 0.85,
    "African Cup of Nations qualification": 0.85,
    "AFC Asian Cup qualification": 0.85,
    "Copa América qualification": 0.85,
    "Gold Cup qualification": 0.8,
    "Arab Cup": 0.7,
    "Gulf Cup": 0.7,
    "ASEAN Championship": 0.7,
    "Oceania Nations Cup": 0.7,
    "EAFF Championship": 0.7,
    "King's Cup": 0.6,
    # Tier friendly / järjestetyt ystävyysottelut
    "FIFA Series": 0.6,
    "CONCACAF Series": 0.6,
    "Friendly": 0.5,
}
DEFAULT_COMPETITION_WEIGHT = 0.5


def _read_raw() -> pd.DataFrame:
    """Lue vendoroitu CSV (UTF-8). 'NA'-tulokset → NaN."""
    return pd.read_csv(CSV_PATH, encoding="utf-8")


def wc2026_participants(raw: pd.DataFrame | None = None) -> set[str]:
    """48 WC 2026 -maata johdettuna datasta (2026 'FIFA World Cup' -ottelut,
    ml. fixturet). Itsepäivittyvä snapshotin virkistyessä."""
    if raw is None:
        raw = _read_raw()
    d = pd.to_datetime(raw["date"], errors="coerce")
    wc = raw[(raw["tournament"] == "FIFA World Cup") & (d.dt.year >= 2026)]
    return set(wc["home_team"]) | set(wc["away_team"])


def lataa(
    kaudet=None,
    window_start: str = DEFAULT_WINDOW_START,
    include: str = DEFAULT_INCLUDE,
) -> pd.DataFrame:
    """Palauta WC-mallin treenidata loaderin vakioskeemassa + tournament/neutral.

    `kaudet` jätetään tietoisesti huomiotta (aikaikkuna ohjaa otosta) — säilytetään
    silti signatuurissa loader-yhteensopivuuden + cache-avaimen vuoksi.
    """
    raw = _read_raw()
    raw["date"] = pd.to_datetime(raw["date"], errors="coerce")
    played = raw[raw["home_score"].notna() & raw["away_score"].notna()].copy()
    played = played[played["date"] >= pd.Timestamp(window_start)]

    teams = wc2026_participants(raw)
    h_in = played["home_team"].isin(teams)
    a_in = played["away_team"].isin(teams)
    played = played[(h_in & a_in) if include == "both" else (h_in | a_in)]

    out = pd.DataFrame(
        {
            "date": played["date"].values,
            "home_team": played["home_team"].values,
            "away_team": played["away_team"].values,
            "home_score": played["home_score"].astype(int).values,
            "away_score": played["away_score"].astype(int).values,
            "league": LEAGUE_LABEL,
            "season": pd.to_datetime(played["date"]).dt.year.astype(str).values,
            "home_xg": pd.NA,
            "away_xg": pd.NA,
            "lahde": "martj42/international_results",
            "tournament": played["tournament"].values,
            "neutral": played["neutral"].astype(str).str.upper().eq("TRUE").values,
        }
    )
    return out.sort_values("date").reset_index(drop=True)
