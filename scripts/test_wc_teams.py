"""#79 vaihe 2 — WC-nimiresoluution testit.

Aja: python -m scripts.test_wc_teams
Verifioi: kaikki 48 WC-maata resolvoituvat, 0 pudotusta, data ↔ kanoninen lista täsmää.
Exit 0 = PASS, 1 = FAIL.
"""
from __future__ import annotations

import sys

try:  # Windows-konsoli on cp1252 — pakota UTF-8 jotta aksenttinimet tulostuvat
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from src.data.wc_teams import (
    WC2026_TEAMS,
    WC2026_TEAMS_SET,
    resolve_wc_name,
)
from src.data.international_results import lataa, wc2026_participants


def main() -> int:
    fails: list[str] = []

    # 1. 48 uniikkia kanonista nimeä
    if len(WC2026_TEAMS) != 48:
        fails.append(f"WC2026_TEAMS pituus {len(WC2026_TEAMS)}, odotettu 48")
    if len(WC2026_TEAMS_SET) != len(WC2026_TEAMS):
        fails.append("WC2026_TEAMS sisältää duplikaatteja")

    # 2. Kanoniset nimet resolvoituvat itseensä (identiteetti)
    for t in WC2026_TEAMS:
        if resolve_wc_name(t) != t:
            fails.append(f"kanoninen ei resolvoidu itseensä: {t!r} -> {resolve_wc_name(t)!r}")

    # 3. Datasta johdetut martj42-osallistujat resolvoituvat kanoniseen, 0 pudotusta
    martj42_participants = wc2026_participants()  # martj42-nimet
    if len(martj42_participants) != 48:
        fails.append(f"martj42 2026-osallistujia {len(martj42_participants)}, odotettu 48")
    resolved = set()
    dropped = []
    for t in martj42_participants:
        r = resolve_wc_name(t)
        if r is None:
            dropped.append(t)
        else:
            resolved.add(r)
    if dropped:
        fails.append(f"PUDOTUKSET (martj42 ei resolvoidu): {sorted(dropped)}")

    # 4. Resolvoitu data-setti == kanoninen lista (ei ylimääräisiä, ei puuttuvia)
    missing = WC2026_TEAMS_SET - resolved
    extra = resolved - WC2026_TEAMS_SET
    if missing:
        fails.append(f"kanonisesta listasta puuttuu datasta: {sorted(missing)}")
    if extra:
        fails.append(f"datassa kanonisen listan ulkopuolisia: {sorted(extra)}")

    # 5. Alias-spot-check (martj42 ↔ FD erot + yleiset variantit)
    spot = {
        "Bosnia and Herzegovina": "Bosnia-Herzegovina",
        "Cape Verde": "Cape Verde Islands",
        "Czech Republic": "Czechia",
        "DR Congo": "Congo DR",
        "Korea Republic": "South Korea",
        "Côte d'Ivoire": "Ivory Coast",
        "Türkiye": "Turkey",
        "USA": "United States",
        "  south korea ": "South Korea",  # whitespace + case
    }
    for variant, canon in spot.items():
        if resolve_wc_name(variant) != canon:
            fails.append(f"alias {variant!r} -> {resolve_wc_name(variant)!r}, odotettu {canon!r}")

    # 6. Ei-WC-nimi → None
    for n in ("Finland", "Italy", "", None, "Nowhere FC"):
        if resolve_wc_name(n) is not None:
            fails.append(f"ei-WC {n!r} resolvoitui virheellisesti: {resolve_wc_name(n)!r}")

    # 7. Loaderin jälkeen kaikki WC-joukkueet df:ssä ovat kanonisia (any-moodi)
    df = lataa(window_start="2022-01-01", include="any")
    teams_in_df = set(df["home_team"]) | set(df["away_team"])
    wc_in_df = teams_in_df & WC2026_TEAMS_SET
    if wc_in_df != WC2026_TEAMS_SET:
        fails.append(f"loaderissa puuttuu WC-maita: {sorted(WC2026_TEAMS_SET - wc_in_df)}")
    # martj42-erikoisnimet eivät saa enää esiintyä kanonisoinnin jälkeen
    leaked = teams_in_df & {"Bosnia and Herzegovina", "Cape Verde", "Czech Republic", "DR Congo"}
    if leaked:
        fails.append(f"kanonisoimattomia martj42-nimiä df:ssä: {sorted(leaked)}")

    if fails:
        print("FAIL:")
        for f in fails:
            print("  -", f)
        return 1
    print(f"PASS — 48/48 WC-maata resolvoituu, 0 pudotusta, data↔kanoninen täsmää.")
    print(f"  martj42 participants: {len(martj42_participants)}, df rows(any/2022): {len(df)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
