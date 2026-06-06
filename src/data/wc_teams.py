"""WC 2026 -joukkueiden keskitetty nimiresoluutio (#79 vaihe 2).

Kanoninen nimiavaruus = **football-data.org (FD)** -nimet, koska frontend käyttää
niitä jo sekä `/api/teams`- että `/api/fixtures`-poluissa → ei frontend-muutosta.

martj42/international_results -treenidata käyttää muutamaa eri kirjoitusasua
(4 maata 48:sta); `resolve_wc_name()` mappaa ne + FD-nimet + yleiset variantit
kanoniseen muotoon. Loader (international_results.py) kanonisoi 48 WC-maan nimet
ennen mallin fittausta, jotta predict-wc:hen tulevat FD-nimiset pyynnöt osuvat.
"""
from __future__ import annotations

import unicodedata

# 48 WC 2026 -maata FD-kanonisessa muodossa (lähde: /api/fixtures WC 2026, 72 ott.)
WC2026_TEAMS: tuple[str, ...] = (
    "Algeria", "Argentina", "Australia", "Austria", "Belgium",
    "Bosnia-Herzegovina", "Brazil", "Canada", "Cape Verde Islands", "Colombia",
    "Croatia", "Curaçao", "Czechia", "Congo DR", "Ecuador",
    "Egypt", "England", "France", "Germany", "Ghana",
    "Haiti", "Iran", "Iraq", "Ivory Coast", "Japan",
    "Jordan", "Mexico", "Morocco", "Netherlands", "New Zealand",
    "Norway", "Panama", "Paraguay", "Portugal", "Qatar",
    "Saudi Arabia", "Scotland", "Senegal", "South Africa", "South Korea",
    "Spain", "Sweden", "Switzerland", "Tunisia", "Turkey",
    "United States", "Uruguay", "Uzbekistan",
)

WC2026_TEAMS_SET = frozenset(WC2026_TEAMS)

# variantti → FD-kanoninen. Kattaa martj42-nimet (4 todellista eroa) + yleiset
# vaihtoehtoiset kirjoitusasut robustiuden vuoksi (FD/Understat/uutislähteet).
_ALIASES: dict[str, str] = {
    # martj42 ↔ FD (todelliset erot treenidatassa)
    "Bosnia and Herzegovina": "Bosnia-Herzegovina",
    "Cape Verde": "Cape Verde Islands",
    "Czech Republic": "Czechia",
    "DR Congo": "Congo DR",
    # Yleiset variantit (robustius — eivät esiinny martj42:ssa mutta voivat tulla
    # muista lähteistä / käsin)
    "Democratic Republic of the Congo": "Congo DR",
    "Côte d'Ivoire": "Ivory Coast",
    "Cote d'Ivoire": "Ivory Coast",
    "Korea Republic": "South Korea",
    "IR Iran": "Iran",
    "Türkiye": "Turkey",
    "Turkiye": "Turkey",
    "USA": "United States",
    "Cabo Verde": "Cape Verde Islands",
    "Curacao": "Curaçao",
}


def _fold(s: str) -> str:
    """casefold + aksenttien poisto vertailuavaimeksi."""
    n = unicodedata.normalize("NFKD", s.strip())
    n = "".join(c for c in n if not unicodedata.combining(c))
    return n.casefold()


# Hakurakenne: foldattu avain → kanoninen. Sisältää kanoniset nimet itse +
# aliakset + foldatut variantit.
_LOOKUP: dict[str, str] = {}
for _canon in WC2026_TEAMS:
    _LOOKUP[_fold(_canon)] = _canon
for _variant, _canon in _ALIASES.items():
    _LOOKUP[_fold(_variant)] = _canon


def resolve_wc_name(name: str | None) -> str | None:
    """Palauta WC-maan FD-kanoninen nimi, tai None jos ei tunnistettu WC-maaksi."""
    if not name:
        return None
    n = name.strip()
    if n in WC2026_TEAMS_SET:
        return n
    return _LOOKUP.get(_fold(n))


def is_wc_team(name: str | None) -> bool:
    return resolve_wc_name(name) is not None
