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
