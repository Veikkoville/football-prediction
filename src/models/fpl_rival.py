"""MINI-LEAGUE-RIVAL — "Catch your rival" -laskenta (13.8).

Spec: goaliq-app/cos-reports/mini-league-rival-spec-2026-08-13.md

Vastaa kysymykseen jota taulukko ei vastaa: *"olen X pistettä jäljessä ja
kierroksia on N — mitä teen?"* Takaa-ajaja ja johtaja tarvitsevat
VASTAKKAISET strategiat, ja se ero on laskettavissa.

TODENNÄKÖISYYSKONEISTO ON JAETTU h2h:n kanssa (api/fantasy_edge.py):
sama normaaliapproksimaatio ja sama per-pelaaja-varianssiheuristiikka
(VAR_PER_XP * xP, kapteeni multiplier^2). Emme keksi toista varianssimallia
samaan tuotteeseen — kaksi mallia samasta asiasta on tasan se rakenne josta
28.7 syntyi kaksi eri lukua mallin parhaasta joukkueesta.

REHELLISYYS:
  - riippumattomuusoletus on VÄÄRÄ (yhteiset pelaajat korreloivat) ja se
    kerrotaan payloadissa asti, kuten h2h:n docstring tekee
  - P(catch) pyöristetään 5 %:iin — luku ei saa näyttää tarkemmalta kuin on
  - hittejä ei suositella, koska hitin hinta ei ole tässä laskennassa
"""
from __future__ import annotations

import math

# Jaettu h2h:n kanssa. Jos tätä muutetaan, h2h muuttuu samalla — se on
# tarkoitus: yksi varianssiheuristiikka per tuote.
VAR_PER_XP = 2.5

# Alle tämän kiinnikurontatodennäköisyyden ollaan "varianssitilassa": vain
# hajonta voi enää kuroa eron, joten suositus vaihtuu. Kynnys on vakio ja
# kirjattu, ei tapauskohtainen arvio.
VARIANCE_MODE_P = 0.20

STANCE_CHASE_STEADY = "chase_steady"
STANCE_CHASE_VARIANCE = "chase_variance"
STANCE_PROTECT = "protect"
STANCE_LEVEL = "level"

METHOD_NOTE = (
    "Normal approximation over the remaining gameweeks: per-gameweek XI xP "
    "sums (captain doubled) give the mean, per-player variance "
    f"{VAR_PER_XP} * xP gives the spread. Assumes player scores independent; "
    "shared players cancel in the mean but not in the variance, so treat the "
    "probability as a direction, not a precise number."
)


def _phi(x: float) -> float:
    """Standardinormaalin kertymäfunktio (sama kuin h2h:n _phi)."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def catch_probability(gap: float, mu_you: float, mu_rival: float,
                      var_you: float, var_rival: float,
                      gameweeks_left: int) -> float:
    """P(kurot `gap` kiinni `gameweeks_left` kierroksessa).

    gap > 0 = olet jäljessä. Palauttaa 0..1 pyöristämättömänä; esityskerros
    pyöristää. Jos kierroksia ei ole jäljellä, ero on lopullinen.
    """
    if gameweeks_left <= 0:
        return 1.0 if gap < 0 else 0.0
    mu_diff = gameweeks_left * (mu_you - mu_rival)
    var_diff = gameweeks_left * (var_you + var_rival)
    s = math.sqrt(max(var_diff, 1e-9))
    return 1.0 - _phi((gap - mu_diff) / s)


def round_probability(p: float) -> float:
    """5 %:n tarkkuus. Riippumattomuusoletuksen kanssa tarkempi luku olisi
    väärää täsmällisyyttä, ja lukija lukisi sen lupauksena."""
    return round(round(p * 20) / 20, 2)


def stance(gap: float, p_catch: float) -> str:
    """Asema ratkaisee strategian, ei pelkkä piste-ero.

    Johtaja EI saa samaa ohjetta kuin takaa-ajaja: johtajan optimi on riskin
    poisto (peilaa uhkaajat), takaa-ajan riskin OTTO. Tämä on koko
    ominaisuuden idea, ja sillä on oma negatiivinen kontrolli testeissä.
    """
    if gap < 0:
        return STANCE_PROTECT
    if gap == 0:
        return STANCE_LEVEL
    return STANCE_CHASE_VARIANCE if p_catch < VARIANCE_MODE_P else STANCE_CHASE_STEADY


def player_swing(xp: float) -> float:
    """Varianssikontribuutio = kuinka paljon pelaaja voi kääntää eroa
    KUMPAANKIN suuntaan. Sama heuristiikka kuin h2h:n varianssitermi."""
    return VAR_PER_XP * max(xp, 0.0)


def differentials(pool: list[dict], your_ids: set[int], rival_ids: set[int],
                  stance_key: str, limit: int = 5) -> list[dict]:
    """Kandidaatit poimittuna ASEMAN mukaan.

    - takaa-ajo (varianssitila): pelaajat joita rivaali EI omista, suurin
      swing edellä — vain hajonta voi kuroa eron
    - takaa-ajo (rauhallinen): sama joukko, mutta xP edellä
    - suojaus: rivaalin omistamat joita SINÄ et omista — ne ovat ne jotka
      voivat kaataa johtosi, ja peilaaminen poistaa riskin
    - tasoissa: puhdas xP

    Palauttaa aina `rival_owns`-lipun, jotta UI voi kertoa MIKSI rivi on
    listalla ilman että logiikka piiloutuu komponenttiin.
    """
    if stance_key == STANCE_PROTECT:
        cands = [p for p in pool
                 if p["id"] in rival_ids and p["id"] not in your_ids]
    else:
        cands = [p for p in pool
                 if p["id"] not in your_ids and p["id"] not in rival_ids]

    rows = []
    for p in cands:
        xp = float(p.get("xp_horizon_total") or 0.0)
        rows.append({
            "id": p["id"],
            "web_name": p.get("web_name"),
            "team_short": p.get("team_short"),
            "price": p.get("price"),
            "owned_pct": p.get("owned_pct"),
            "xp_horizon": round(xp, 2),
            "swing": round(player_swing(xp), 2),
            "rival_owns": p["id"] in rival_ids,
        })

    if stance_key == STANCE_CHASE_VARIANCE:
        rows.sort(key=lambda r: (-r["swing"], r["owned_pct"] or 0.0, r["id"]))
    else:
        rows.sort(key=lambda r: (-r["xp_horizon"], r["id"]))
    return rows[:limit]


def build_rival_view(gap: float, gameweeks_left: int,
                     mu_you: float, mu_rival: float,
                     var_you: float, var_rival: float,
                     pool: list[dict], your_ids: set[int],
                     rival_ids: set[int],
                     premium: bool = True) -> dict:
    """Koko payload. FREE = ero + kierrokset + P(catch) (tarkistettavissa
    FPL:n omasta taulukosta). PREMIUM = mitä sille pitäisi tehdä."""
    p_raw = catch_probability(gap, mu_you, mu_rival, var_you, var_rival,
                              gameweeks_left)
    p = round_probability(p_raw)
    st = stance(gap, p_raw)
    out = {
        "meta": {
            "gameweeks_left": gameweeks_left,
            "method": METHOD_NOTE,
            "masked": not premium,
            # Kynnys on datassa asti, jotta paneelin ei tarvitse tuntea sitä
            # eikä copy voi ajautua eri lukuun kuin logiikka.
            "variance_mode_below": VARIANCE_MODE_P,
        },
        "gap": round(gap, 1),
        "behind": gap > 0,
        "p_catch": p,
        "stance": st,
    }
    if premium:
        out["differentials"] = differentials(pool, your_ids, rival_ids, st)
    return out
