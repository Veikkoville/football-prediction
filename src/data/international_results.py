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

from functools import lru_cache

import config
from src.data.wc_teams import WC2026_TEAMS_SET, resolve_wc_name

CSV_PATH = config.DATA_DIR / "international_results.csv"

# Esirakennettu WC-malli (JSON). Render Starterin ~0.5 vCPU ei jaksa fitata
# "any"-mallia (195 maata / 302 param SLSQP) ajossa ilman timeoutia → malli
# rakennetaan offline (scripts/build_wc_model.py) ja ladataan ajossa.
WC_MODEL_PATH = config.DATA_DIR / "wc_model.json"

# WC-mallin fit-parametrit (vaiheen 5 backtestin voittaja: window=2022, any,
# decay=0.0, bayes=1.0). Kanoninen lähde — build-skripti + api.main lukevat tästä.
WC_FIT_DECAY: float = 0.0
WC_FIT_BAYES: float = 1.0

# #79 konfederaatio-kalibrointikorjaus: World Football Elo -priori ankkuroi
# attack/defencen cross-confederation-uskottavaan skaalaan (esim. Japani-tyyppinen
# heikon konfederaation karsintainflaatio pois — Japani #5→#11). Arvot
# tune_wc_elo-gridistä (paras out-of-sample log-loss + konfederaatio-sanity läpi):
#   beta=0.004, weight=16, shrink_defence_to_mean=False (Elo-priori ankkuroi
#   defencen → ei tarvita keskiarvo-shrinkkausta, joka jätti Japanin top-5:een).
ELO_PRIOR_BETA: float = 0.004
ELO_PRIOR_WEIGHT: float = 16.0
WC_SHRINK_DEFENCE: bool = False

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


@lru_cache(maxsize=1)
def _read_raw() -> pd.DataFrame:
    """Lue vendoroitu CSV (UTF-8) ja parsi päivät. 'NA'-tulokset → NaN.

    Cachetettu prosessin keston ajaksi — CSV on staattinen snapshot. Kutsujat
    EIVÄT mutatoi paluuarvoa (lataa() rakentaa uuden DataFramen). Sama jaettu-
    instanssi-malli kuin domestic _DATA_CACHE."""
    df = pd.read_csv(CSV_PATH, encoding="utf-8")
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    return df


def save_wc_model(dc, meta: dict) -> None:
    """Sarjallista fitattu DixonColesModel JSONiksi (vain dict/float/list-kentät)."""
    import json
    payload = {
        "meta": meta,
        "attack": dc.attack,
        "defence": dc.defence,
        "home_advantage": dc.home_advantage,
        "home_advantage_per_team": dc.home_advantage_per_team,
        "rho": dc.rho,
        "teams_": list(dc.teams_),
        "per_team_home_adv": dc.per_team_home_adv,
        "model_type_": getattr(dc, "model_type_", "dc"),
    }
    with open(WC_MODEL_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)


@lru_cache(maxsize=1)
def load_wc_model():
    """Lataa esirakennettu WC-malli JSONista → DixonColesModel. EI fittiä ajossa.
    Cachetettu (lru) — tiedosto on staattinen vendoroitu snapshot."""
    import json
    from src.models.dixon_coles import DixonColesModel
    with open(WC_MODEL_PATH, encoding="utf-8") as f:
        d = json.load(f)
    return DixonColesModel(
        attack=d["attack"],
        defence=d["defence"],
        home_advantage=d["home_advantage"],
        home_advantage_per_team=d["home_advantage_per_team"],
        rho=d["rho"],
        teams_=d["teams_"],
        per_team_home_adv=d.get("per_team_home_adv", False),
        model_type_=d.get("model_type_", "dc"),
    )


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
    silti signatuurissa loader-yhteensopivuuden + cache-avaimen vuoksi. Tulos
    cachetetaan (window_start, include) -avaimella → predict-wc:n per-pyyntö-H2H ei
    suodata 49k riviä joka kerta."""
    return _build(window_start, include)


@lru_cache(maxsize=8)
def _build(window_start: str, include: str) -> pd.DataFrame:
    raw = _read_raw()  # cachetettu, parsittu date — EI mutatoida tässä
    played = raw[raw["home_score"].notna() & raw["away_score"].notna()].copy()
    played = played[played["date"] >= pd.Timestamp(window_start)]

    # Kanonisoi 48 WC-maan nimet martj42 → FD (4 todellista eroa). Ei-WC-
    # vastustajat säilyttävät martj42-nimensä (vain sparrausdataa, ei kyselyä).
    def _canon(name: str) -> str:
        r = resolve_wc_name(name)
        return r if r is not None else name

    played["home_team"] = played["home_team"].map(_canon)
    played["away_team"] = played["away_team"].map(_canon)

    h_in = played["home_team"].isin(WC2026_TEAMS_SET)
    a_in = played["away_team"].isin(WC2026_TEAMS_SET)
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
