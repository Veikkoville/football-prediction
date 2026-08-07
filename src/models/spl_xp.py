"""SPL (RSL Fantasy) xP -ydin: pisteytys + vauhdit + yksinkertaistettu minuuttimalli.

OMA MODUULI eikä fpl_xp:n parametrisointi kahdesta syystä:
  1. RSL-pisteytys EROAA FPL:stä olennaisesti (maali FWD/MID +5 & DEF/GK +6,
     CS GK5/DEF4/MID1, torjunnat /2, GK-päästetyt jokaisesta 1. jälkeen,
     voittomaali +1, fani-MOTM +2, ja mikrostatsit: taklaukset, defensiiviset
     aktiot, laukaukset, isot paikat, syötöt) — FPL-vakioiden uudelleenkäyttö
     olisi hiljaa väärin.
  2. fpl_xp:n minuutti-/vauhtikoneisto on per-GW-historiavetoinen; SPL:n
     element-summary tarjoilee vain KAUSIAGGREGAATIT (history_past, ei
     starts-kenttää, ei kierroksia) → tarvitaan aggregaattipohjainen malli.
     FPL-tuotantopolkuun ei kosketa.

Pisteytyslähde: RSL Fantasy -säännöt, dokumentoitu FFScoutin how-to-play
-artikkelissa (20.8.2025) + bootstrapin element_stats-lista (7.8.2026).
HUOM: mikrostatsien kynnykset ovat 25/26-mekaniikka; SPL on julkistanut
26/27-bonusmuutoksia — jos scoring muuttuu, päivitä vakiot ja aja gradaus.

REHELLISYYS: SPL:lle ei ole ilmaista pelaaja-xG:tä → hyökkäyskomponentit
lasketaan TOTEUTUNEISTA maali-/syöttövauhdeista (g90/a90), ei xG:stä.
data_basis kertoo tämän klientille; älä väitä xG-pohjaa SPL-copyssa.
"""
from __future__ import annotations

# Kutistus jaetaan FPL-ytimestä: sama minuuttipainotettu kaava, samat
# prioripainot (minuuttiskaala on liigariippumaton).
from src.models.fpl_xp import (  # noqa: F401
    M_PRIOR_ATTACK,
    M_PRIOR_MISC,
    _shrink90,
    depth_factor,
)

# ---------------------------------------------------------------------------
# RSL-pisteytys (positio: 1=GK, 2=DEF, 3=MID, 4=FWD — sama kuin FPL)
# ---------------------------------------------------------------------------
GOAL_PTS = {1: 6, 2: 6, 3: 5, 4: 5}
ASSIST_PTS = 3
CS_PTS = {1: 5, 2: 4, 3: 1, 4: 0}
SAVE_PTS_PER = 2.0            # 1 piste / 2 torjuntaa (FPL: /3)
WINNING_GOAL_PTS = 1.0
MOTM_PTS = 2.0                # fani-äänestetty man of the match
YC_PTS = -1.0
RC_PTS = -3.0
BONUS_CAP = 3.0

# Mikrostatsit: (jakaja, pistettä per täyttynyt kynnys) per positio.
# None = ei pisteitä tälle positiolle. Lähde: FFScout scoring-taulukko.
TACKLE_RULE = {2: (3, 1.0), 3: (3, 1.0), 4: (2, 1.0)}
DEF_ACTION_RULE = {1: (10, 1.0), 2: (6, 1.0), 3: (6, 1.0), 4: (6, 1.0)}
SHOT_TARGET_RULE = {2: (2, 1.0), 3: (3, 1.0), 4: (3, 1.0)}
BIG_CHANCE_MISS_RULE = {2: (2, -1.0), 3: (2, -1.0), 4: (2, -2.0)}
PASS_RULE = {1: (40, 1.0), 2: (40, 1.0), 3: (40, 1.0), 4: (40, 1.0)}
BIG_CHANCE_CREATE_RULE = {1: (2, 1.0), 2: (1, 1.0), 3: (2, 1.0), 4: (2, 1.0)}

# SPL-kausi on 34 GW:tä (18 joukkuetta).
SEASON_GWS = 34

# Tyypillinen XI positioittain — syvyysnormalisoinnin slotit (SPL:n
# element-summary ei kerro startteja, joten FPL:n itsekonsistenttia
# starttidataa ei ole; kiinteä XI-jako on dokumentoitu heuristiikka).
XI_SLOTS = {1: 1.0, 2: 4.0, 3: 4.3, 4: 1.7}

# Aloittajan/vaihtopelaajan keskiminuutit — minuuttimallin kaksi moodia.
START_MINS = 86.0
CAMEO_MINS = 20.0


# ---------------------------------------------------------------------------
# Aggregaatit → acc (history_past-rivistä; vastine fpl_xp.accumulate_history)
# ---------------------------------------------------------------------------
AGG_KEYS = {
    "goals": "goals_scored", "assists": "assists", "wgoals": "winning_goals",
    "saves": "saves", "yc": "yellow_cards", "rc": "red_cards",
    "bonus": "bonus", "motm": "fmmp", "tackles": "won_tackle",
    "defacts": "clearances_blocks_interceptions", "sot": "shot_target",
    "bcm": "big_chance_missed", "bcc": "big_chance_created",
    "passes": "accurate_pass",
}


def acc_from_history_past(row: dict | None) -> dict:
    """history_past-kausirivi → kumulatiivinen acc. None → nolla-acc
    (positiopriori dominoi, data_basis='no_history')."""
    acc = {k: 0.0 for k in AGG_KEYS}
    acc["mins"] = 0.0
    if row:
        acc["mins"] = float(row.get("minutes") or 0)
        for out_key, src_key in AGG_KEYS.items():
            acc[out_key] = float(row.get(src_key) or 0)
    return acc


def position_priors(acc_by_player: dict[int, dict],
                    pos_by_player: dict[int, int]) -> dict[int, dict]:
    """Positiotason per-90-priorit poolista (vastine fpl_xp.position_priors)."""
    tot: dict[int, dict] = {p: {k: 0.0 for k in AGG_KEYS} | {"mins": 0.0}
                            for p in (1, 2, 3, 4)}
    for pid, acc in acc_by_player.items():
        pos = pos_by_player.get(pid)
        if pos not in tot:
            continue
        for k in list(AGG_KEYS) + ["mins"]:
            tot[pos][k] += acc[k]
    priors = {}
    for pos, t in tot.items():
        mins = max(t["mins"], 1.0)
        priors[pos] = {f"{k}90": 90.0 * t[k] / mins for k in AGG_KEYS}
    return priors


def player_rates(acc: dict, pos: int, priors: dict[int, dict]) -> dict:
    """Kutistetut per-90-vauhdit. Maalit/syötöt attack-priorilla, muut misc."""
    pr = priors.get(pos) or {f"{k}90": 0.0 for k in AGG_KEYS}
    mins = acc["mins"]
    out = {}
    for k in AGG_KEYS:
        m_prior = M_PRIOR_ATTACK if k in ("goals", "assists") else M_PRIOR_MISC
        out[f"{k}90"] = _shrink90(acc[k], mins, pr[f"{k}90"], m_prior)
    return out


# ---------------------------------------------------------------------------
# Minuuttimalli kausiaggregaateista
# ---------------------------------------------------------------------------
def minutes_model_from_aggregates(season_minutes: float) -> dict:
    """Kaksimoodinen arvio (startti ~86 min / cameo ~20 min) kauden
    kokonaisminuuteista. KARKEAMPI kuin FPL:n per-GW-malli — ei muotoa, ei
    starttisarjoja — siksi minutes_confidence on korkeintaan 'med'.

    p_start = min(0.95, kesk.min/86); jäännösminuutit → cameo-tn.
    """
    mbar = max(0.0, season_minutes) / SEASON_GWS
    p_start = min(0.95, mbar / START_MINS)
    residual = max(0.0, mbar - p_start * START_MINS)
    p_cameo = min(1.0 - p_start, residual / CAMEO_MINS)
    p60 = 0.92 * p_start           # osa aloittajista vaihdetaan ennen 60:tä
    p1_59 = (p_start - p60) + p_cameo
    xmins = p_start * START_MINS + p_cameo * CAMEO_MINS
    conf = "med" if season_minutes >= 900 else "low"
    return {
        "p_start": p_start, "p_start_raw": p_start, "p_cameo": p_cameo,
        "p_bench": max(0.0, 1.0 - p_start - p_cameo),
        "p60": p60, "p1_59": p1_59, "xmins": xmins,
        "minutes_confidence": conf,
    }


def scale_minutes(mm: dict, factor: float) -> dict:
    """Skaalaa aloitus-tn:ää kertoimella ja johda muut suureet uudelleen
    (syvyysnormalisointi + saatavuus käyttävät tätä)."""
    f = max(0.0, factor)
    p_start = min(0.95, mm["p_start"] * f)
    p_cameo = min(1.0 - p_start, mm["p_cameo"] * f)
    p60 = 0.92 * p_start
    return {
        **mm,
        "p_start": p_start, "p_start_raw": p_start, "p_cameo": p_cameo,
        "p_bench": max(0.0, 1.0 - p_start - p_cameo),
        "p60": p60, "p1_59": (p_start - p60) + p_cameo,
        "xmins": p_start * START_MINS + p_cameo * CAMEO_MINS,
    }


def availability_factor(status: str, chance) -> float:
    """FPL-konventio (sama status-koodisto kloonialustalla): 'a' = pelikuntoinen,
    muuten chance_of_playing ohjaa; None+ei-a = 0."""
    if status == "a":
        return 1.0
    try:
        return max(0.0, min(1.0, float(chance) / 100.0))
    except (TypeError, ValueError):
        return 0.0


# ---------------------------------------------------------------------------
# Odotusarvo kynnyspisteille: E[floor(X/n)] per ottelu
# ---------------------------------------------------------------------------
def e_floor(mean_per_match: float, divisor: int) -> float:
    """Approksimaatio E[floor(X/n)] ≈ max(0, (E[X] - (n-1)/2) / n).

    Tarkka odotusarvo vaatisi X:n jakauman; lineaarinen E[X]/n YLIarvioisi
    matalilla määrillä (floor syö keskimäärin ~(n-1)/2 yksikköä). Tämä
    korjaus on dokumentoitu approksimaatio, ei kalibroitu malli.
    """
    if divisor <= 1:
        return max(0.0, mean_per_match)
    return max(0.0, (mean_per_match - (divisor - 1) / 2.0) / divisor)


def _rule_points(rule: dict, pos: int, rate90: float, share: float) -> float:
    r = rule.get(pos)
    if not r:
        return 0.0
    divisor, pts = r
    return e_floor(rate90 * share, divisor) * pts


def expected_conceded_gk(conceded_dist: list[float]) -> float:
    """GK: -1 jokaisesta päästetystä ENSIMMÄISEN jälkeen = E[max(k-1, 0)]."""
    return sum(p * max(k - 1, 0) for k, p in enumerate(conceded_dist))


def expected_conceded_def(conceded_dist: list[float]) -> float:
    """DEF: -1 / 2 päästettyä = E[floor(k/2)] (sama muoto kuin FPL:ssä)."""
    return sum(p * (k // 2) for k, p in enumerate(conceded_dist))


# ---------------------------------------------------------------------------
# xP yhdelle fixturelle
# ---------------------------------------------------------------------------
def xp_components(pos: int, rates: dict, xmins: float, p60: float, p1_59: float,
                  ctx: dict) -> dict:
    """RSL-xP-komponentit yhdelle fixturelle. ctx = sama joukkuekonteksti kuin
    FPL:ssä (fixture_contexts: goal_mult, cs_prob, conceded_dist, opp_goal_mult).

    Hyökkäysvauhdit skaalataan goal_multilla (fixture-vaikeus); mikrostatsit
    pidetään vastustajaneutraaleina — FPL-mittaus 28.7 näytti DefConin ja
    korttien olevan käytännössä vastustajariippumattomia, ja SPL-kalibrointia
    näille ei ole. Bonus ilman fixture-betaa samasta syystä (FPL:n 0.837 on
    FPL-datasta kalibroitu).
    """
    share = xmins / 90.0
    goal_mult = ctx.get("goal_mult", 1.0)
    comp = {
        "appearance": 2.0 * p60 + 1.0 * p1_59,
        "goals": rates["goals90"] * share * goal_mult * GOAL_PTS[pos],
        "winning_goal": rates["wgoals90"] * share * goal_mult * WINNING_GOAL_PTS,
        "assists": rates["assists90"] * share * goal_mult * ASSIST_PTS,
        "clean_sheet": CS_PTS[pos] * ctx.get("cs_prob", 0.0) * p60,
        "conceded": 0.0,
        "saves": 0.0,
        "cards": (rates["yc90"] * YC_PTS + rates["rc90"] * RC_PTS) * share,
        "bonus": min(rates["bonus90"] * share, BONUS_CAP),
        "motm": rates["motm90"] * share * MOTM_PTS,
        "tackles": _rule_points(TACKLE_RULE, pos, rates["tackles90"], share),
        "def_actions": _rule_points(DEF_ACTION_RULE, pos, rates["defacts90"], share),
        "shots_on_target": _rule_points(SHOT_TARGET_RULE, pos, rates["sot90"], share),
        "big_chance_missed": -_rule_points(
            {k: (v[0], -v[1]) for k, v in BIG_CHANCE_MISS_RULE.items()},
            pos, rates["bcm90"], share),
        "big_chance_created": _rule_points(BIG_CHANCE_CREATE_RULE, pos,
                                           rates["bcc90"], share),
        "passes": _rule_points(PASS_RULE, pos, rates["passes90"], share),
    }
    if pos == 1:
        comp["conceded"] = -expected_conceded_gk(
            ctx.get("conceded_dist", [1.0])) * share
        comp["saves"] = (rates["saves90"] * share
                         * ctx.get("opp_goal_mult", 1.0)) / SAVE_PTS_PER
    elif pos == 2:
        comp["conceded"] = -expected_conceded_def(
            ctx.get("conceded_dist", [1.0])) * share
    comp["total"] = sum(v for k, v in comp.items() if k != "total")
    return comp


def xp_full_90(pos: int, rates: dict, ctx: dict) -> float:
    """xP jos pelaisi täydet 90 min (sama määritelmä kuin FPL:n xp_full_90)."""
    return xp_components(pos, rates, 90.0, 1.0, 0.0, ctx)["total"]
