"""
Projektin keskitetyt asetukset.

Tähän tiedostoon kerätään polut, sarjojen tunnisteet ja muut vakiot.
Näin yksittäisten skriptien koodi pysyy puhtaana ja muutokset on helppo
tehdä yhdestä paikasta.
"""

from pathlib import Path

# ---------------------------------------------------------------------------
# POLUT
# ---------------------------------------------------------------------------
# __file__ = config.py — sen vanhempi-kansio on projektin juuri.
PROJECT_ROOT = Path(__file__).resolve().parent

DATA_DIR = PROJECT_ROOT / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
PROCESSED_DATA_DIR = DATA_DIR / "processed"

# Varmistetaan että kansiot ovat olemassa kun moduulia importataan.
for _d in (RAW_DATA_DIR, PROCESSED_DATA_DIR):
    _d.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# LIIGAT
# ---------------------------------------------------------------------------
# soccerdata käyttää standardoituja "league_id" -merkkijonoja.
# Listaus: https://soccerdata.readthedocs.io/en/latest/datasources.html

# Top-5 Eurooppa
TOP5_LEAGUES = [
    "ENG-Premier League",
    "ESP-La Liga",
    "GER-Bundesliga",
    "ITA-Serie A",
    "FRA-Ligue 1",
]

# Eurocupit (FBref)
EURO_CUPS = [
    "INT-Champions League",
    "INT-Europa League",
    "INT-Europa Conference League",
]

# Pohjoismaat (FBref tukee näitä)
NORDIC_LEAGUES = [
    "FIN-Veikkausliiga",
    "SWE-Allsvenskan",
    "NOR-Eliteserien",
    "DEN-Superliga",
]

# Kausi merkitään muodossa "YYYY-YYYY" (esim. 2024-2025) tai pelkkänä
# loppuvuonna ("2425"). soccerdata hyväksyy molemmat.
DEFAULT_SEASONS = ["2122", "2223", "2324", "2425", "2526"]


def current_season(today: "datetime.date | None" = None) -> str:
    """Aktiivinen eurooppalainen kausi YYMM-muodossa (esim. '2526').

    Sääntö: elo-touko = kausi. Kuukausi >= 8 → uusi kausi alkaa (1.8. → '2627'),
    kuukaudet 1-7 → edellisenä syksynä alkanut kausi (31.7. → '2526').
    Sama algoritmi frontendissä: goaliq-app lib/season.ts (pidä synkassa).
    """
    import datetime
    d = today or datetime.date.today()
    start = d.year if d.month >= 8 else d.year - 1
    return f"{start % 100:02d}{(start + 1) % 100:02d}"


def current_season_pair(today: "datetime.date | None" = None) -> list[str]:
    """[edellinen, aktiivinen] kausi — DC-mallien treeni-ikkuna (esim.
    ['2425', '2526']). Endpoint-defaultit + warmup käyttävät tätä."""
    cur = current_season(today)
    prev_start = (int(cur[:2]) - 1) % 100
    return [f"{prev_start:02d}{cur[:2]}", cur]


def seasons_since(first: str = "2122", today: "datetime.date | None" = None) -> list[str]:
    """Kaudet first..aktiivinen nousevassa järjestyksessä (/api/leagues)."""
    out = [first]
    cur = current_season(today)
    while out[-1] != cur:
        start = (int(out[-1][:2]) + 1) % 100
        out.append(f"{start:02d}{(start + 1) % 100:02d}")
        if len(out) > 50:  # vahti: ei ikuista silmukkaa jos cur on menneisyydessä
            raise ValueError(f"seasons_since: '{cur}' ei saavutettavissa '{first}':sta")
    return out


# ---------------------------------------------------------------------------
# MALLIN ASETUKSET
# ---------------------------------------------------------------------------
# Rolling-form -ikkuna: kuinka monta edellistä ottelua otetaan
# huomioon piirteissä.
ROLLING_WINDOW = 5

# Dixon-Coles "rho" alustusarvo (sovitetaan optimoinnissa).
DIXON_COLES_RHO_INIT = -0.1

# LightGBM-mallin perusasetukset.
LGB_PARAMS = {
    "objective": "multiclass",
    "num_class": 3,           # 1, X, 2
    "learning_rate": 0.05,
    "num_leaves": 31,
    "feature_fraction": 0.9,
    "bagging_fraction": 0.8,
    "bagging_freq": 5,
    "verbose": -1,
}
