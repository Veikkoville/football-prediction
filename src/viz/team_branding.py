"""
Joukkueen branding-data: logot, päävärit, aliakset.

Premier Leaguen omat badge-URL:t toimivat ilmaiseksi:
  https://resources.premierleague.com/premierleague/badges/{size}/t{id}.png

Värit ovat virallisten brändiohjeiden mukaisia (Wikipedia / klubien sivut).
"""

from __future__ import annotations
import unicodedata


# Englannin Valioliiga — kaikki viime ~5 kauden joukkueet
PL_TIIMI_DATA: dict = {
    "Arsenal":                  {"id": 3,  "color": "#EF0107", "alt": "#FFFFFF"},
    "Aston Villa":              {"id": 7,  "color": "#95BFE5", "alt": "#670E36"},
    "Bournemouth":              {"id": 91, "color": "#DA020E", "alt": "#000000"},
    "AFC Bournemouth":          {"id": 91, "color": "#DA020E", "alt": "#000000"},
    "Brentford":                {"id": 94, "color": "#E30613", "alt": "#FFFFFF"},
    "Brighton":                 {"id": 36, "color": "#0057B8", "alt": "#FFCD00"},
    "Brighton & Hove Albion":   {"id": 36, "color": "#0057B8", "alt": "#FFCD00"},
    "Burnley":                  {"id": 90, "color": "#6C1D45", "alt": "#99D6EA"},
    "Chelsea":                  {"id": 8,  "color": "#034694", "alt": "#FFFFFF"},
    "Crystal Palace":           {"id": 31, "color": "#1B458F", "alt": "#A7A5A6"},
    "Everton":                  {"id": 11, "color": "#003399", "alt": "#FFFFFF"},
    "Fulham":                   {"id": 54, "color": "#000000", "alt": "#CC0000"},
    "Ipswich Town":             {"id": 40, "color": "#0444AA", "alt": "#FFFFFF"},
    "Leeds United":             {"id": 2,  "color": "#FFFFFF", "alt": "#1D428A"},
    "Leeds":                    {"id": 2,  "color": "#FFFFFF", "alt": "#1D428A"},
    "Leicester City":           {"id": 13, "color": "#003090", "alt": "#FDBE11"},
    "Leicester":                {"id": 13, "color": "#003090", "alt": "#FDBE11"},
    "Liverpool":                {"id": 14, "color": "#C8102E", "alt": "#00B2A9"},
    "Luton Town":               {"id": 38, "color": "#F78F1E", "alt": "#1F4E79"},
    "Manchester City":          {"id": 43, "color": "#6CABDD", "alt": "#FFFFFF"},
    "Man City":                 {"id": 43, "color": "#6CABDD", "alt": "#FFFFFF"},
    "Manchester United":        {"id": 1,  "color": "#DA020E", "alt": "#FFE500"},
    "Manchester Utd":           {"id": 1,  "color": "#DA020E", "alt": "#FFE500"},
    "Man United":               {"id": 1,  "color": "#DA020E", "alt": "#FFE500"},
    "Man Utd":                  {"id": 1,  "color": "#DA020E", "alt": "#FFE500"},
    "Newcastle United":         {"id": 4,  "color": "#241F20", "alt": "#FFFFFF"},
    "Newcastle Utd":            {"id": 4,  "color": "#241F20", "alt": "#FFFFFF"},
    "Newcastle":                {"id": 4,  "color": "#241F20", "alt": "#FFFFFF"},
    "Nottingham Forest":        {"id": 17, "color": "#DD0000", "alt": "#FFFFFF"},
    "Nott'ham Forest":          {"id": 17, "color": "#DD0000", "alt": "#FFFFFF"},
    "Sheffield United":         {"id": 49, "color": "#EE2737", "alt": "#000000"},
    "Sheffield Utd":            {"id": 49, "color": "#EE2737", "alt": "#000000"},
    "Southampton":              {"id": 20, "color": "#D71920", "alt": "#FFFFFF"},
    "Sunderland":               {"id": 56, "color": "#EB172B", "alt": "#FFFFFF"},
    "Tottenham Hotspur":        {"id": 6,  "color": "#132257", "alt": "#FFFFFF"},
    "Tottenham":                {"id": 6,  "color": "#132257", "alt": "#FFFFFF"},
    "Spurs":                    {"id": 6,  "color": "#132257", "alt": "#FFFFFF"},
    "West Ham United":          {"id": 21, "color": "#7A263A", "alt": "#1BB1E7"},
    "West Ham":                 {"id": 21, "color": "#7A263A", "alt": "#1BB1E7"},
    "Wolverhampton Wanderers":  {"id": 39, "color": "#FDB913", "alt": "#231F20"},
    "Wolves":                   {"id": 39, "color": "#FDB913", "alt": "#231F20"},
    "Wolverhampton":            {"id": 39, "color": "#FDB913", "alt": "#231F20"},
}

PL_LOGO_URL = "https://resources.premierleague.com/premierleague/badges/{size}/t{id}.png"

DEFAULT_COLOR = "#6B7280"  # neutraali harmaa fallback
DEFAULT_ALT = "#FFFFFF"


def _normalize(s: str) -> str:
    """Normalisoi nimi: aksentit pois + lowercase."""
    return "".join(
        c for c in unicodedata.normalize("NFD", str(s))
        if unicodedata.category(c) != "Mn"
    ).lower()


def get_team_data(team_name: str) -> dict | None:
    """Hae tiimin branding-tiedot. Sumea-haku jos tarkkaa nimea ei ole."""
    if not team_name:
        return None
    # 1. Eksakti
    if team_name in PL_TIIMI_DATA:
        return PL_TIIMI_DATA[team_name]
    # 2. Aksenttitietoinen normalisoitu match
    nimi_norm = _normalize(team_name)
    for key, data in PL_TIIMI_DATA.items():
        if _normalize(key) == nimi_norm:
            return data
    # 3. Substring-haku (löysempi)
    for key, data in PL_TIIMI_DATA.items():
        key_norm = _normalize(key)
        if nimi_norm in key_norm or key_norm in nimi_norm:
            return data
    return None


def get_logo_url(team_name: str, size: int = 70) -> str | None:
    """Palauta PL-logon URL tai None jos ei loydy. Size 25, 50 tai 70."""
    data = get_team_data(team_name)
    if data and "id" in data:
        return PL_LOGO_URL.format(size=size, id=data["id"])
    return None


def get_team_color(team_name: str) -> str:
    """Palauta tiimin paavari hex-muodossa. Fallback harmaaseen."""
    data = get_team_data(team_name)
    return data.get("color", DEFAULT_COLOR) if data else DEFAULT_COLOR


def get_team_alt(team_name: str) -> str:
    """Tiimin sekundaarivari (kontrasti)."""
    data = get_team_data(team_name)
    return data.get("alt", DEFAULT_ALT) if data else DEFAULT_ALT
