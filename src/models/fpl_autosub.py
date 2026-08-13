"""FPL:n autosub- ja kapteenisäännöt (Beat the Model V2 vaihe b, 13.8).

Puhdas logiikka: syötteenä jäädytetty rivi + toteutuneet minuutit/pisteet,
tuloksena lopullinen XI, tehdyt vaihdot ja pistemäärä. Ei IO:ta, jotta
säännöt voi testata virallisista säännöistä johdetuilla tapauksilla ENNEN
ensimmäistä julkaistua lukua (specin riski #1: väärä luku julkisessa
race-paneelissa on luottamusmyrkkyä, Hub 2,0★ -oppi).

Viralliset säännöt jotka tämä toteuttaa:
  1. Autosub koskee vain aloittajaa joka pelasi 0 minuuttia. Yksikin minuutti
     = ei vaihtoa (myös 0 pistettä pelanneelta).
  2. Penkin maalivahti vaihtuu VAIN aloittavan maalivahdin tilalle, ja vain
     jos hän itse pelasi. Kenttäpelaaja ei koskaan korvaa maalivahtia.
  3. Kenttäpelaajat tulevat penkkijärjestyksessä (prioriteetti), ja vaihto
     tehdään vain jos lopullinen muodostelma on laillinen: 1 GK, 3-5 DEF,
     2-5 MID, 1-3 FWD.
  4. Jos kapteeni ei pelannut, kaksinkertaistus siirtyy varakapteenille.
     Jos kumpikaan ei pelannut, kukaan ei saa kaksinkertaistusta — se EI
     siirry kentälle tulleelle vaihtopelaajalle.

TIETOINEN TULKINTA (dokumentoitu, koska sääntöteksti ei kata tätä):
penkki käydään läpi PRIORITEETTIJÄRJESTYKSESSÄ ja kukin penkkiläinen tulee
kentälle jos hän voi laillisesti korvata jonkun pelaamattoman aloittajan.
Vaihtoehtoinen luenta (käy pelaamattomat aloittajat läpi ja etsi kullekin
penkkiläinen) tuottaa saman PISTEMÄÄRÄN, koska pelaamattomat aloittajat
tuottavat aina 0 — ero näkyisi vain siinä kenet raportoidaan korvatuksi.
"""
from __future__ import annotations

GK, DEF, MID, FWD = 1, 2, 3, 4
XI_MIN = {GK: 1, DEF: 3, MID: 2, FWD: 1}
XI_MAX = {GK: 1, DEF: 5, MID: 5, FWD: 3}


def _counts(players: list[dict]) -> dict[int, int]:
    out = {GK: 0, DEF: 0, MID: 0, FWD: 0}
    for p in players:
        out[p["pos"]] = out.get(p["pos"], 0) + 1
    return out


def _formation_ok(players: list[dict]) -> bool:
    if len(players) != 11:
        return False
    c = _counts(players)
    return all(XI_MIN[t] <= c[t] <= XI_MAX[t] for t in (GK, DEF, MID, FWD))


def _played(pid: int, minutes: dict[int, int]) -> bool:
    return int(minutes.get(pid, 0) or 0) > 0


def apply_autosubs(xi: list[dict], bench: list[dict],
                   minutes: dict[int, int]) -> tuple[list[dict], list[dict]]:
    """(lopullinen XI, tehdyt vaihdot). Ei muuta syötelistoja."""
    final = list(xi)
    subs: list[dict] = []

    # --- 1. Maalivahti omana sääntönään.
    bench_gk = next((b for b in bench if b["pos"] == GK), None)
    start_gk = next((p for p in final if p["pos"] == GK), None)
    if (start_gk is not None and bench_gk is not None
            and not _played(start_gk["id"], minutes)
            and _played(bench_gk["id"], minutes)):
        final[final.index(start_gk)] = bench_gk
        subs.append({"out": start_gk["id"], "in": bench_gk["id"], "pos": GK})

    # --- 2. Kenttäpelaajat penkkijärjestyksessä.
    for b in [x for x in bench if x["pos"] != GK]:
        if not _played(b["id"], minutes):
            continue
        for starter in [p for p in final
                        if p["pos"] != GK and not _played(p["id"], minutes)]:
            trial = [b if p is starter else p for p in final]
            if _formation_ok(trial):
                final = trial
                subs.append({"out": starter["id"], "in": b["id"],
                             "pos": b["pos"]})
                break
    return final, subs


def captain_multiplier(captain: int, vice: int,
                       minutes: dict[int, int]) -> tuple[int | None, str]:
    """(kaksinkertaistettava pelaaja tai None, syy).

    Armband ei koskaan siirry vaihtopelaajalle — jos kumpikaan nimetty ei
    pelannut, kierros pelataan ilman kaksinkertaistusta.
    """
    if _played(captain, minutes):
        return captain, "captain"
    if _played(vice, minutes):
        return vice, "vice"
    return None, "none"


def score_gw(frozen: dict, points: dict[int, int],
             minutes: dict[int, int]) -> dict:
    """Jäädytetty mallirivi + toteuma → kierroksen tulos.

    `points` on FPL:n oma total_points per pelaaja, joten luku on
    tarkistettavissa kenen tahansa FPL-tililtä.
    """
    xi = list(frozen.get("xi") or [])
    bench = list(frozen.get("bench") or [])
    final, subs = apply_autosubs(xi, bench, minutes)

    cap_id, cap_reason = captain_multiplier(
        int(frozen.get("captain")), int(frozen.get("vice_captain")), minutes)

    base = sum(int(points.get(p["id"], 0) or 0) for p in final)
    cap_bonus = 0
    if cap_id is not None and any(p["id"] == cap_id for p in final):
        cap_bonus = int(points.get(cap_id, 0) or 0)
    return {
        "gw": frozen.get("meta", {}).get("gw"),
        "points": base + cap_bonus,
        "points_before_captain": base,
        "captain_id": cap_id,
        "captain_reason": cap_reason,
        "captain_points_added": cap_bonus,
        "autosubs": subs,
        "bench_points": sum(int(points.get(b["id"], 0) or 0) for b in bench
                            if not any(p["id"] == b["id"] for p in final)),
        "xi_ids": [p["id"] for p in final],
    }
