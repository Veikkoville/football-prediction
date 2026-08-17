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

# #100: WC-refitin staging-kansio — ship-gate PASS -kandidaatti odottaa täällä
# eksplisiittistä promotea (scripts/promote_wc_refit.py) eikä likaa trackattuja
# data/-mallitiedostoja. /data/* on gitignoressa → kansio ei näy git statusissa.
WC_REFIT_STAGING_DIR = DATA_DIR / "_refit_candidate"

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

# xG-painotettu likelihood kotimaisessa ottelumallissa (17.8.2026, Villen GO).
#
# YKSI LAHDE, KOSKA PINNAT EIVAT SAA AJAUTUA ERILLEEN. Sama arvo luetaan
# `/api/predict`:iin ja FPL-putken fitteihin (build_fpl_phase0, build_fpl_cs_fdr).
# Ne fittasivat jo ennestaan samoilla decay/bayes-arvoilla, ja build_fpl_phase0:n
# oma teksti lupaa "sama fit-config kuin /api/predict" — jos xG kytkettaisiin vain
# toiseen, sama ottelu saisi kaksi eri lukua eika lupaus pitaisi paikkaansa.
#
# Mitattu walk-forwardilla (raportti 2026-08-17-xg-weight-mittaus.md), top-5-liigat,
# kaudet 2324-2526, n=4641 ennustetta, tuotannon fit-parametreilla:
#   xg_weight 0.0 -> log loss 0,99588 / Brier 0,59468 / osumatarkkuus 51,15 %
#   xg_weight 0.5 -> log loss 0,98672 / Brier 0,58831 / osumatarkkuus 51,95 %
#   xg_weight 0.7 -> log loss 0,98648 / Brier 0,58812 / osumatarkkuus 51,93 %
# Parittain: 0.5 vs 0.0 delta log loss -0,00916 (t -5,26). Voitto toistuu
# JOKAISESSA viidessa liigassa erikseen. 0.5 ja 0.7 ovat kaytannossa identtiset
# eli optimi on littea -> valittu 0.5, koska se vie mallin vahemman kauas
# maalidatasta samalla hyodylla.
#
# INERTTI ILMAN xG-DATAA: `DixonColesModel.fit` kytkee termin paalle vain jos
# xG-sarakkeet ovat datassa JA arvoja on. Liigat joilla ei ole Understat-dataa
# (esim. SPL, Championship) fittautuvat bittitarkasti kuten ennen.
DIXON_COLES_XG_WEIGHT = 0.5
DIXON_COLES_XG_COLS = ("home_xg", "away_xg")

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
