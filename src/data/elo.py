"""#79 — World Football Elo -ankkuri WC-mallin cross-confederation-kalibrointiin.

Vendoroitu snapshot data/elo_ratings.csv (eloratings.net). Elo → DixonColesModel
`team_priors`: ankkuroi joukkueen vahvuus (attack/defence) uskottavaan skaalaan
niin että heikon konfederaation karsintainflaatio (esim. Japani) ei nosta tiimiä
maailman kärkeen. Data säätää priorista; weight säätelee priorin voimaa.
"""
from __future__ import annotations

import csv
from functools import lru_cache

import config
from src.data.wc_teams import resolve_wc_name

ELO_PATH = config.DATA_DIR / "elo_ratings.csv"


@lru_cache(maxsize=1)
def load_elo() -> dict[str, int]:
    """{joukkueen nimi → Elo}. Avaimina sekä eloratings-nimi että WC-kanoninen
    (resolve_wc_name) → osuu malliin tulevat nimet (martj42 + FD-kanoniset)."""
    out: dict[str, int] = {}
    with open(ELO_PATH, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                elo = int(r["elo"])
            except (ValueError, KeyError):
                continue
            name = r["name"].strip()
            out[name] = elo
            canon = resolve_wc_name(name)
            if canon:
                out[canon] = elo
    return out


def build_team_priors(
    teams, beta: float, weight: float
) -> dict[str, dict]:
    """Rakenna DixonColesModel.fit():n team_priors Elo-ankkurista.

    strength s_i = beta * (Elo_i - mean_Elo)   [log-goal-yksikköä]
    prior_attack = +s_i/2, prior_defence = -s_i/2  (centroitu → maalitaso säilyy).
    weight = priorin voima (skaalaa l2_attack_defence per joukkue).

    Joukkueet joilla ei Eloa → prior 0 (= keskiarvo), sama weight.
    """
    elo = load_elo()
    vals = [elo[t] for t in teams if t in elo]
    mean_elo = sum(vals) / len(vals) if vals else 1500.0
    priors: dict[str, dict] = {}
    for t in teams:
        e = elo.get(t)
        s = beta * (e - mean_elo) if e is not None else 0.0
        priors[t] = {"attack": s / 2.0, "defence": -s / 2.0, "weight": weight}
    return priors
