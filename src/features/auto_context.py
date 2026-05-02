"""
Auto-konteksti — laske ottelukohtainen tilanne ennen ottelua.

Tarjoaa:
  - Lepopaivat (kotijoukkue, vierasjoukkue) datasta
  - Sarjasija ja motivaatio (putoamiskamppailu / mestaruustaistelu / mitaan pelattavaa)
  - Derby-tunnistus (manuaalinen pari-lista)
  - Saa wttr.in:sta (ilmainen, ei API-avainta)

Loukkaantumisia/kokoonpanoja EI haeta automaattisesti — ei luotettavaa
avointa rajapintaa. Kayttajan pitaa syottaa manuaalisesti.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
import requests

# Tunnetut derby-parit Top-5 + Pohjoismaat
DERBY_PAIRS = {
    # Premier League
    frozenset(["Liverpool", "Everton"]),
    frozenset(["Arsenal", "Tottenham"]),
    frozenset(["Manchester United", "Manchester City"]),
    frozenset(["Manchester United", "Liverpool"]),
    frozenset(["Chelsea", "Arsenal"]),
    frozenset(["Chelsea", "Tottenham"]),
    frozenset(["West Ham", "Tottenham"]),
    # La Liga
    frozenset(["Real Madrid", "Barcelona"]),
    frozenset(["Real Madrid", "Atletico Madrid"]),
    frozenset(["Barcelona", "Espanyol"]),
    frozenset(["Sevilla", "Real Betis"]),
    # Bundesliga
    frozenset(["Borussia Dortmund", "Schalke 04"]),
    frozenset(["Bayern Munich", "1860 Munich"]),
    frozenset(["Borussia Dortmund", "Bayern Munich"]),
    # Serie A
    frozenset(["Inter", "Milan"]),
    frozenset(["Roma", "Lazio"]),
    frozenset(["Juventus", "Torino"]),
    frozenset(["Genoa", "Sampdoria"]),
    frozenset(["Napoli", "Roma"]),
    # Ligue 1
    frozenset(["Marseille", "Paris S-G"]),
    frozenset(["Paris Saint-Germain", "Marseille"]),
    frozenset(["Lyon", "Saint-Etienne"]),
    # Suomi
    frozenset(["HJK", "HIFK"]),
    frozenset(["HJK", "Inter Turku"]),
    # Ruotsi
    frozenset(["AIK", "Djurgardens IF"]),
    frozenset(["AIK", "Hammarby"]),
    frozenset(["IFK Goteborg", "GAIS"]),
    # Norja
    frozenset(["Brann", "Vaalerenga"]),
    frozenset(["Rosenborg", "Molde"]),
    # Tanska
    frozenset(["FC Kobenhavn", "Brondby"]),
}


def on_derby(home_team: str, away_team: str) -> bool:
    return frozenset([home_team, away_team]) in DERBY_PAIRS


# ---------------------------------------------------------------------------
# LEPOPAIVAT
# ---------------------------------------------------------------------------
def laske_lepopaivat(
    matches: pd.DataFrame,
    team: str,
    ottelu_paiva: Optional[datetime] = None,
) -> int | None:
    """Kuinka monta paivaa joukkueen edellisesta ottelusta. None jos ei dataa."""
    if matches.empty:
        return None
    df = matches.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    # Tz-naive jos merkinta paalla
    try:
        if df["date"].dt.tz is not None:
            df["date"] = df["date"].dt.tz_convert("UTC").dt.tz_localize(None)
    except (AttributeError, TypeError):
        pass
    own = df[(df["home_team"] == team) | (df["away_team"] == team)]
    if own.empty:
        return None
    if ottelu_paiva is None:
        ottelu_paiva = datetime.now()
    aiemmat = own[own["date"] < pd.Timestamp(ottelu_paiva)]
    if aiemmat.empty:
        return None
    viimeinen = aiemmat["date"].max()
    return int((pd.Timestamp(ottelu_paiva) - viimeinen).days)


# ---------------------------------------------------------------------------
# SARJATAULUKKO ja motivaatio
# ---------------------------------------------------------------------------
def laske_sarjataulukko(
    matches: pd.DataFrame,
    league: Optional[str] = None,
    season: Optional[str] = None,
    ottelu_paiva: Optional[datetime] = None,
) -> pd.DataFrame:
    """Laske sarjataulukko ennen `ottelu_paiva` -hetkea."""
    df = matches.copy()
    df["date"] = pd.to_datetime(df["date"])
    if league and "league" in df.columns:
        df = df[df["league"] == league]
    if season and "season" in df.columns:
        df = df[df["season"].astype(str) == str(season)]
    if ottelu_paiva is not None:
        df = df[df["date"] < pd.Timestamp(ottelu_paiva)]

    if df.empty:
        return pd.DataFrame(columns=["team", "matches", "wins", "draws", "losses",
                                     "gf", "ga", "gd", "points"])

    rows = []
    for team in pd.concat([df["home_team"], df["away_team"]]).unique():
        omat = df[(df["home_team"] == team) | (df["away_team"] == team)]
        wins = draws = losses = gf = ga = 0
        for _, r in omat.iterrows():
            on_koti = r["home_team"] == team
            omat_maalit = r["home_score"] if on_koti else r["away_score"]
            vast_maalit = r["away_score"] if on_koti else r["home_score"]
            gf += omat_maalit
            ga += vast_maalit
            if omat_maalit > vast_maalit:
                wins += 1
            elif omat_maalit == vast_maalit:
                draws += 1
            else:
                losses += 1
        rows.append({
            "team": team, "matches": len(omat),
            "wins": wins, "draws": draws, "losses": losses,
            "gf": gf, "ga": ga, "gd": gf - ga,
            "points": 3 * wins + draws,
        })
    table = pd.DataFrame(rows).sort_values(
        ["points", "gd", "gf"], ascending=False
    ).reset_index(drop=True)
    table["position"] = table.index + 1
    return table


def arvioi_motivaatio(
    table: pd.DataFrame,
    team: str,
    n_teams: int | None = None,
) -> int:
    """
    Arvioi pelaajien motivaatio sarjasijasta.

    Palauttaa -10 - +10 prosenttia (sopii apply_match_adjustments-funktioon).
    Logiikka:
      - Mestaruustaistelu (top 4) -> +5
      - Eurocup-paikat (5-7) -> +3
      - Putoamiskamppailu (3 viimeista) -> +5
      - Mid-table ilman mitaan -> -3
    """
    if table.empty or team not in table["team"].values:
        return 0
    rivi = table[table["team"] == team].iloc[0]
    pos = int(rivi["position"])
    if n_teams is None:
        n_teams = len(table)

    if pos <= 4:
        return 5  # mestaruus / UCL paikka
    if pos <= 7:
        return 5  # eurocup paikat
    if pos > n_teams - 3:
        return 5  # putoamiskamppailu
    return -5  # mid-table — ei mitaan pelattavaa


# ---------------------------------------------------------------------------
# SAA — wttr.in ilmainen API
# ---------------------------------------------------------------------------
def hae_saa(kaupunki: str, paiva: datetime | None = None) -> dict:
    """
    Hae sa wttr.in-palvelusta. Ei API-avainta tarvitse.

    Palauttaa: {"temp_c": int, "rain_mm": float, "wind_kph": int, "desc": str}
    """
    try:
        url = f"https://wttr.in/{kaupunki}?format=j1"
        r = requests.get(url, timeout=8)
        r.raise_for_status()
        data = r.json()
        nyk = data.get("current_condition", [{}])[0]
        return {
            "temp_c": int(nyk.get("temp_C", 15)),
            "rain_mm": float(nyk.get("precipMM", 0)),
            "wind_kph": int(nyk.get("windspeedKmph", 10)),
            "desc": nyk.get("weatherDesc", [{}])[0].get("value", "Tuntematon"),
        }
    except Exception as e:
        return {"error": str(e)}


def saa_to_total_goals_delta(saa: dict) -> float:
    """Muunna saatieto kokonaismaalien deltaksi."""
    if "error" in saa:
        return 0.0
    delta = 0.0
    if saa["rain_mm"] > 5:
        delta -= 0.4  # ankara sade
    elif saa["rain_mm"] > 1:
        delta -= 0.2  # kohtalainen sade
    if saa["wind_kph"] > 40:
        delta -= 0.3  # myrskyinen
    elif saa["wind_kph"] > 25:
        delta -= 0.1  # tuulista
    if saa["temp_c"] < 0:
        delta -= 0.2  # pakkanen
    return round(delta, 2)


# ---------------------------------------------------------------------------
# JOUKKUE -> KAUPUNKI -mappaus saata varten
# ---------------------------------------------------------------------------
TEAM_CITY = {
    "Arsenal": "London", "Chelsea": "London", "Tottenham": "London",
    "West Ham": "London", "Crystal Palace": "London", "Fulham": "London",
    "Manchester United": "Manchester", "Manchester City": "Manchester",
    "Liverpool": "Liverpool", "Everton": "Liverpool",
    "Newcastle Utd": "Newcastle", "Newcastle United": "Newcastle",
    "Leicester City": "Leicester", "Leicester": "Leicester",
    "Aston Villa": "Birmingham", "Wolves": "Wolverhampton",
    "Southampton": "Southampton", "Brighton": "Brighton",
    "Brentford": "London", "Nottingham Forest": "Nottingham",
    "Bournemouth": "Bournemouth",
    # La Liga
    "Real Madrid": "Madrid", "Atletico Madrid": "Madrid",
    "Barcelona": "Barcelona", "Espanyol": "Barcelona",
    "Sevilla": "Seville", "Real Betis": "Seville",
    "Valencia": "Valencia", "Athletic Club": "Bilbao",
    # Bundesliga
    "Bayern Munich": "Munich", "Borussia Dortmund": "Dortmund",
    "RB Leipzig": "Leipzig", "Bayer Leverkusen": "Leverkusen",
    "Eintracht Frankfurt": "Frankfurt",
    # Serie A
    "Inter": "Milan", "Milan": "Milan", "AC Milan": "Milan",
    "Juventus": "Turin", "Torino": "Turin",
    "Roma": "Rome", "Lazio": "Rome", "Napoli": "Naples",
    "Atalanta": "Bergamo", "Fiorentina": "Florence",
    # Ligue 1
    "Paris S-G": "Paris", "Paris Saint-Germain": "Paris",
    "Marseille": "Marseille", "Lyon": "Lyon", "Monaco": "Monaco",
    # Pohjoismaat
    "HJK": "Helsinki", "HIFK": "Helsinki",
    "Inter Turku": "Turku", "FC Lahti": "Lahti",
    "AIK": "Stockholm", "Hammarby": "Stockholm",
    "Djurgardens IF": "Stockholm", "IFK Goteborg": "Gothenburg",
    "Malmo FF": "Malmo",
    "Brann": "Bergen", "Rosenborg": "Trondheim", "Molde": "Molde",
    "FC Kobenhavn": "Copenhagen", "Brondby": "Copenhagen",
    "Midtjylland": "Herning",
}


def joukkueen_kaupunki(team: str) -> str:
    return TEAM_CITY.get(team, "London")  # fallback London (yleinen sa keskiarvoa varten)
