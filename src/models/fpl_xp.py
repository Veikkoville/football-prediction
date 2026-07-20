"""FPL Phase 1 — xP (expected points) -ydin + tuotanto-JSON:n loader.

Kaikki xP-laskenta on tässä moduulissa PUHTAINA funktioina, jotta
backtest (scripts/backtest_fpl_xp.py) ja tuotanto-builderi
(scripts/build_fpl_xp.py) käyttävät TÄSMÄLLEEN samaa kaavaa — ship-gate
mittaa sitä mitä shipataan.

xP per pelaaja per fixture = summa komponenteista (FPL 25/26 -säännöt):
  - esiintyminen:  P(60+) * 2 + P(1-59) * 1
  - maalit:        E[maalit] * positiopisteet (GKP 10 / DEF 6 / MID 5 / FWD 4)
  - syötöt:        E[syötöt] * 3
  - clean sheet:   P(joukkueen CS) * P(60+) * positiopisteet (GKP/DEF 4, MID 1)
  - päästetyt:     -E[floor(k/2)] vastustajan maalijakaumasta (GKP/DEF)
  - torjunnat:     E[torjunnat] / 3 (GKP)
  - def. contrib:  2 * P(kynnys täyttyy) * P(60+) (DEF kynnys 10 CBIT,
                   MID/FWD 12 CBIRT — uusi 25/26-sääntö)
  - keltainen:     -1 * E[keltaiset]
  - bonus:         per-90-bonusvauhti * minuuttiosuus (kevyt proxy)

Pelaajavauhdit (per-90) lasketaan FPL-historiasta kumulatiivisesti ja
kutistetaan positioprioria kohti (minuuttipainotettu shrinkage) — pieni
otos ei tuota villejä ennusteita. Joukkuekonteksti (maaliodotus-kerroin,
CS-%, päästettyjen jakauma) tulee GoalIQ:n Dixon-Coles -mallista.

Ei mallinneta (pienet/harvinaiset): punaiset, omat maalit, rankkarin
ohilaukaus/torjunta, maalivahdin syöttöbonus. MAE sietää nämä.
"""
from __future__ import annotations

import json
from pathlib import Path

import config

XP_PATH = config.DATA_DIR / "fpl_xp_projections.json"

# ---------------------------------------------------------------------------
# FPL 25/26 -pistesäännöt
# ---------------------------------------------------------------------------
POS_NAME = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}
GOAL_PTS = {1: 10, 2: 6, 3: 5, 4: 4}
CS_PTS = {1: 4, 2: 4, 3: 1, 4: 0}
ASSIST_PTS = 3
SAVE_PTS_PER = 3.0          # 1 piste / 3 torjuntaa
DC_PTS = 2                  # defensive contribution -bonus
DC_THRESHOLD = {2: 10, 3: 12, 4: 12}   # DEF: CBIT >= 10, MID/FWD: CBIRT >= 12

# Shrinkage-painot (minuutteina): pieni otos -> lähellä positioprioria.
M_PRIOR_ATTACK = 450.0      # xG/xA
M_PRIOR_MISC = 900.0        # torjunnat, keltaiset, bonus
DC_PRIOR_GAMES = 5.0        # def. contribution -frekvenssin prioripaino

# Minuuttimallin recency-painot (vanhin -> uusin viimeisistä joukkuekierroksista).
MINUTE_WEIGHTS = (1.0, 1.0, 2.0, 2.0, 4.0)

# #143: estimaatin datapohja-luokat ("model can't see this yet" -rehellisyys).
# Akseli on EVIDENSSI (paljonko pelaajan omaa PL-dataa estimaatin takana on),
# ei siirtostatus — new_signing-lippua ei voi täyttää totuudella pre-season-
# bootstrapista (edellisen kauden data, siirrot näkymättömiä).
DATA_BASIS_FULL = "pl_history"        # oma historia kantaa >= 50 % painon
DATA_BASIS_LIMITED = "limited_history"  # ohut otos, positiopriori dominoi
DATA_BASIS_NONE = "no_history"        # ei yhtään PL-minuuttia -> pelkkä priori
DATA_BASIS_VALUES = (DATA_BASIS_FULL, DATA_BASIS_LIMITED, DATA_BASIS_NONE)


def data_basis(acc: dict) -> str:
    """Estimaatin datapohja pelaajan kertyneistä PL-minuuteista.

    Kynnys = M_PRIOR_ATTACK (_shrink90:n 50 %-piste): sen alle pelaajan oma
    xG/xA-vauhti kantaa alle puolet painosta eli estimaatti on enemmän
    positioprioria kuin pelaajaa itseään. Puhdas emissio — ei saa muuttaa
    yhtäkään xP-lukua.
    """
    mins = acc.get("mins", 0.0) or 0.0
    if mins <= 0:
        return DATA_BASIS_NONE
    if mins < M_PRIOR_ATTACK:
        return DATA_BASIS_LIMITED
    return DATA_BASIS_FULL


# ---------------------------------------------------------------------------
# Pelaajavauhdit historiasta (walk-forward-turvallinen: kutsuja antaa vain
# kierrosta edeltävät rivit)
# ---------------------------------------------------------------------------
def _f(x) -> float:
    """FPL-API palauttaa xG/xA:n merkkijonoina ("0.85")."""
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def accumulate_history(rows: list[dict]) -> dict:
    """Summaa pelaajan historiarivit kumulatiiviseksi pohjaksi vauhdeille."""
    acc = {
        "mins": 0.0, "xg": 0.0, "xa": 0.0, "saves": 0.0,
        "yc": 0.0, "bonus": 0.0, "n60": 0, "dc_hits": 0,
    }
    for r in rows:
        m = r.get("minutes", 0) or 0
        acc["mins"] += m
        acc["xg"] += _f(r.get("expected_goals"))
        acc["xa"] += _f(r.get("expected_assists"))
        acc["saves"] += r.get("saves", 0) or 0
        acc["yc"] += r.get("yellow_cards", 0) or 0
        acc["bonus"] += r.get("bonus", 0) or 0
        if m >= 60:
            acc["n60"] += 1
    return acc


def dc_hit(row: dict, pos: int) -> bool:
    """Täyttyikö defensive contribution -kynnys tällä rivillä."""
    thr = DC_THRESHOLD.get(pos)
    if thr is None:
        return False
    return (row.get("defensive_contribution", 0) or 0) >= thr


def count_dc_hits(rows: list[dict], pos: int) -> int:
    return sum(1 for r in rows if (r.get("minutes", 0) or 0) >= 60 and dc_hit(r, pos))


def position_priors(acc_by_player: dict[int, dict],
                    pos_by_player: dict[int, int]) -> dict[int, dict]:
    """Positiotason per-90-priorit poolista (walk-forward: kutsuja antaa
    vain kierrosta edeltävistä riveistä lasketut accit)."""
    tot: dict[int, dict] = {p: {"mins": 0.0, "xg": 0.0, "xa": 0.0, "saves": 0.0,
                                "yc": 0.0, "bonus": 0.0, "n60": 0, "dc_hits": 0}
                            for p in POS_NAME}
    for pid, acc in acc_by_player.items():
        pos = pos_by_player.get(pid)
        if pos not in tot:
            continue
        for k in ("mins", "xg", "xa", "saves", "yc", "bonus"):
            tot[pos][k] += acc[k]
        tot[pos]["n60"] += acc["n60"]
        tot[pos]["dc_hits"] += acc.get("dc_hits", 0)
    priors = {}
    for pos, t in tot.items():
        mins = max(t["mins"], 1.0)
        priors[pos] = {
            "xg90": 90.0 * t["xg"] / mins,
            "xa90": 90.0 * t["xa"] / mins,
            "saves90": 90.0 * t["saves"] / mins,
            "yc90": 90.0 * t["yc"] / mins,
            "bonus90": 90.0 * t["bonus"] / mins,
            "dc_freq": t["dc_hits"] / max(t["n60"], 1),
        }
    return priors


def _shrink90(cum: float, mins: float, prior90: float, m_prior: float) -> float:
    """Minuuttipainotettu shrinkage: rate90 -> prior90 kun otos pieni."""
    return 90.0 * (cum + prior90 / 90.0 * m_prior) / (mins + m_prior)


def player_rates(acc: dict, pos: int, priors: dict[int, dict]) -> dict:
    """Kutistetut per-90-vauhdit yhdelle pelaajalle."""
    pr = priors.get(pos) or {"xg90": 0, "xa90": 0, "saves90": 0,
                             "yc90": 0, "bonus90": 0, "dc_freq": 0}
    mins = acc["mins"]
    return {
        "xg90": _shrink90(acc["xg"], mins, pr["xg90"], M_PRIOR_ATTACK),
        "xa90": _shrink90(acc["xa"], mins, pr["xa90"], M_PRIOR_ATTACK),
        "saves90": _shrink90(acc["saves"], mins, pr["saves90"], M_PRIOR_MISC),
        "yc90": _shrink90(acc["yc"], mins, pr["yc90"], M_PRIOR_MISC),
        "bonus90": _shrink90(acc["bonus"], mins, pr["bonus90"], M_PRIOR_MISC),
        "dc_freq": ((acc.get("dc_hits", 0) + DC_PRIOR_GAMES * pr["dc_freq"])
                    / (acc["n60"] + DC_PRIOR_GAMES)),
    }


# ---------------------------------------------------------------------------
# Minuuttimalli: viimeiset joukkuekierrokset, recency-painotus
# ---------------------------------------------------------------------------
def minutes_form(mins_by_round: dict[int, float],
                 team_rounds_before: list[int],
                 n_last: int | None = 5) -> tuple[float, float, float]:
    """(xMins, P(60+), P(1-59)) pelaajan viimeisistä joukkuekierroksista.

    mins_by_round: pelaajan minuutit per kierros (fixturet summattu).
    team_rounds_before: joukkueen pelatut kierrokset ennen kohde-GW:tä
    (nousevassa järjestyksessä). Kierros ilman riviä = 0 min (ei pelannut).
    Poissaolot painuvat siis nollaan luonnostaan.

    n_last=None = koko ikkuna tasapainoin — pre-season-snapshot päättyneestä
    kaudesta (kauden lopun rotaatio ei saa dominoida uuden kauden GW1-arviota;
    nykyhetken poissaolot hoitaa FPL:n saatavuustieto builderissa).
    Kesken kauden käytetään recency-painotettua last-5:tä (ship-gaten polku).
    """
    rounds = team_rounds_before if n_last is None else team_rounds_before[-n_last:]
    if not rounds:
        return 0.0, 0.0, 0.0
    w = ([1.0] * len(rounds) if n_last is None
         else MINUTE_WEIGHTS[-len(rounds):])
    wsum = sum(w)
    xmins = p60 = p1 = 0.0
    for wi, rnd in zip(w, rounds):
        m = min(float(mins_by_round.get(rnd, 0.0)), 90.0)
        xmins += wi * m
        if m >= 60:
            p60 += wi
        elif m >= 1:
            p1 += wi
    return xmins / wsum, p60 / wsum, p1 / wsum


# ---------------------------------------------------------------------------
# #33: Ennustetut minuutit — probabilistinen start% × xMins
# ---------------------------------------------------------------------------
# Korvaa naiivin availability_factor-skaalauksen ehdollisella rakenteella:
#   xMins = p_start·E[min|start] + (1−p_start)·p_sub·E[min|sub]
# EI deterministinen XI (managerit arvaamattomia) — probabilistinen +
# confidence-taso, jotta UI näyttää epävarmuuden rehellisesti (brändilinja).
# Walk-forward-turvallinen: kutsuja antaa vain kohde-GW:tä edeltävät kierrokset.

# Recency-painot viime joukkuekierroksille (vanhin → uusin). Ikkuna + painot
# valittu walk-forward-sweepillä 25/26 (w4 voitti w5/w6/w8/w10:n xMins-MAE:ssa).
START_WINDOW = 4
START_WEIGHTS = (1.0, 2.0, 3.0, 4.0)
# p_start-kalibrointi: raaka start-share YLIarvioi startteja korkeissa arvoissa
# (rotaatio-regressio, todettu backtestissä: raaka Brier 0.175 vs p60-proxy
# 0.167) → NÄYTETTÄVÄ p_start shrinkataan neutraalia prioria kohti. xMins
# johdetaan RAA'ASTA sharesta (shrinkattu p_start veisi minuutit keskinkertaisiksi
# → MAE huononisi; eriytys dokumentoitu backtestissä: MAE 21.15 + Brier 0.164
# = molemmat paremmat kuin baseline 21.60 / 0.167).
P_START_SHRINK = 0.2
P_START_PRIOR = 0.5   # neutraali — EI backtestistä sovitettu (rakenteellinen)
# Fallbackit kun ehdollisia havaintoja ei ole (uusi pelaaja / pelkkä penkki).
START_FALLBACK_MIN = 78.0
SUB_FALLBACK_MIN = 18.0
P60_GIVEN_START_FALLBACK = 0.85
# Syvyys-korjaus: klubi+positio-ryhmän Σp_start normalisoidaan ryhmän
# historialliseen starttipaikkamäärään. Nosto capattu — ohut kärki (esim.
# kilpailija loukkaantunut → availability nollasi hänet) nostaa muita
# maltillisesti, ei räjäytä.
DEPTH_BOOST_CAP = 1.10
# Fixture-ruuhka: tupla-GW (2 ottelua samassa ikkunassa) → pieni, dokumentoitu
# rotaatioriski kärkiminuuttien pelaajille. Konservatiivinen — ei mustaa laatikkoa.
CONGESTION_MULT = 0.95
CONGESTION_XMINS_GATE = 70.0


def minutes_model(mins_by_round: dict[int, float],
                  starts_by_round: dict[int, int],
                  team_rounds_before: list[int],
                  n_last: int | None = START_WINDOW) -> dict:
    """Probabilistinen minuuttiestimaatti pelaajan viime kierroksista.

    Palauttaa dictin jossa EHDOLLISET parametrit (p_start, p_sub,
    e_min_start, e_min_sub, p60_start, p60_sub) + niistä johdetut
    (xmins, p60, p1_59) + n_obs + confidence ('low'|'med'|'high').
    Johdetut lasketaan recompute_minutes():llä → skaalaukset (saatavuus,
    syvyys) muuttavat p_startia ja johdetut pysyvät konsistentteina.

    n_last=None = koko ikkuna tasapainoin (pre-season-snapshot päättyneestä
    kaudesta, sama konventio kuin minutes_form).
    """
    rounds = team_rounds_before if n_last is None else team_rounds_before[-n_last:]
    base = {
        "p_start_raw": 0.0, "p_start": 0.0, "p_sub": 0.0,
        "e_min_start": START_FALLBACK_MIN, "e_min_sub": SUB_FALLBACK_MIN,
        "p60_start": P60_GIVEN_START_FALLBACK, "p60_sub": 0.0,
        "n_obs": len(rounds), "confidence": "low",
    }
    if not rounds:
        return recompute_minutes(base)
    w = ([1.0] * len(rounds) if n_last is None
         else list(START_WEIGHTS[-len(rounds):]))
    wsum = sum(w)

    w_start = w_sub_pool = 0.0          # painot: startit / ei-startit
    w_sub_app = 0.0                     # ei-starteista: nousi kentälle
    min_start = min_sub = 0.0           # painotetut minuuttisummat
    w60_start = w60_sub = 0.0
    for wi, rnd in zip(w, rounds):
        m = min(float(mins_by_round.get(rnd, 0.0)), 90.0)
        started = (starts_by_round.get(rnd, 0) or 0) >= 1
        if started:
            w_start += wi
            min_start += wi * m
            if m >= 60:
                w60_start += wi
        else:
            w_sub_pool += wi
            if m >= 1:
                w_sub_app += wi
                min_sub += wi * m
                if m >= 60:
                    w60_sub += wi

    base["p_start_raw"] = w_start / wsum
    # Näytettävä/kalibroitu aloitus-tn (ks. P_START_SHRINK-kommentti yllä)
    base["p_start"] = ((1.0 - P_START_SHRINK) * base["p_start_raw"]
                       + P_START_SHRINK * P_START_PRIOR)
    if w_start > 0:
        base["e_min_start"] = min_start / w_start
        base["p60_start"] = w60_start / w_start
    if w_sub_pool > 0:
        base["p_sub"] = w_sub_app / w_sub_pool
    if w_sub_app > 0:
        base["e_min_sub"] = min_sub / w_sub_app
        base["p60_sub"] = w60_sub / w_sub_app

    # Confidence: otoskoko + start-signaalin vakaus (ääripäät = vakaa).
    # Deterministinen ja dokumentoitu — UI:n low/med/high nojaa tähän.
    p = base["p_start_raw"]
    stable = p <= 0.2 or p >= 0.8
    if base["n_obs"] >= 4 and stable:
        base["confidence"] = "high"
    elif base["n_obs"] >= 3:
        base["confidence"] = "med"
    return recompute_minutes(base)


def recompute_minutes(mm: dict) -> dict:
    """Johda xmins/p60/p1_59 ehdollisista parametreista (idempotentti).

    HUOM: minuutit johdetaan RAA'ASTA start-sharesta (p_start_raw) — shrinkattu
    p_start on kalibroitu tn näyttöä/Brieriä varten, ei minuuttiestimaattiin
    (eriytys perusteltu backtestissä, ks. P_START_SHRINK)."""
    p_start, p_sub = mm["p_start_raw"], mm["p_sub"]
    sub_path = (1.0 - p_start) * p_sub
    mm["xmins"] = p_start * mm["e_min_start"] + sub_path * mm["e_min_sub"]
    mm["p60"] = p_start * mm["p60_start"] + sub_path * mm["p60_sub"]
    mm["p1_59"] = (p_start * (1.0 - mm["p60_start"])
                   + sub_path * (1.0 - mm["p60_sub"]))
    return mm


def apply_availability(mm: dict, status: str, chance) -> dict:
    """FPL-saatavuus porttina: a=ennallaan, d=skaalaa chance-%:lla,
    i/s/u/n = sivussa (p_start ja p_sub nollaan → xmins 0)."""
    if status == "a":
        return mm
    if status == "d":
        f = (chance / 100.0) if chance is not None else 0.5
    else:
        f = 0.0
    out = dict(mm)
    out["p_start_raw"] = mm["p_start_raw"] * f
    out["p_start"] = mm["p_start"] * f
    out["p_sub"] = mm["p_sub"] * f
    return recompute_minutes(out)


def depth_factor(group_p_starts: list[float], slots: float) -> float:
    """Syvyys-korjauskerroin klubi+positio-ryhmälle.

    slots = ryhmän historiallinen starttipaikkamäärä per kierros (laskettu
    samasta datasta → itsekonsistentti). Kun Σp_start < slots (esim.
    kilpailija pudonnut saatavuus-gatessa → ohut kärki), jäljelle jäävien
    p_start nousee — nosto capattu DEPTH_BOOST_CAP:iin. Ylibuukattu ryhmä
    (Σ > slots) skaalataan alas rajatta (paikkoja ei voi olla enempää).
    """
    total = sum(group_p_starts)
    if total <= 0 or slots <= 0:
        return 1.0
    return min(slots / total, DEPTH_BOOST_CAP)


def scale_p_start(mm: dict, factor: float) -> dict:
    """Skaalaa aloitus-tn (capattu [0,1]) ja johda minuutit uudelleen."""
    out = dict(mm)
    out["p_start_raw"] = min(max(mm["p_start_raw"] * factor, 0.0), 1.0)
    out["p_start"] = min(max(mm["p_start"] * factor, 0.0), 1.0)
    return recompute_minutes(out)


def congestion_multiplier(n_fixtures_in_gw: int, xmins: float) -> float:
    """Tupla-GW → rotaatioriski-kerroin kärkiminuuttien pelaajille.
    Yksi ottelu tai matalat minuutit → neutraali 1.0. Ei koskaan < CONGESTION_MULT."""
    if n_fixtures_in_gw >= 2 and xmins >= CONGESTION_XMINS_GATE:
        return CONGESTION_MULT
    return 1.0


# ---------------------------------------------------------------------------
# xP yhdelle fixturelle
# ---------------------------------------------------------------------------
def expected_conceded_penalty(conceded_dist: list[float]) -> float:
    """E[floor(k/2)] vastustajan maalijakaumasta (GKP/DEF -1 / 2 päästettyä)."""
    return sum(p * (k // 2) for k, p in enumerate(conceded_dist))


def xp_components(pos: int, rates: dict, xmins: float, p60: float, p1_59: float,
                  ctx: dict) -> dict:
    """xP-komponentit yhdelle fixturelle.

    ctx (joukkuekonteksti Dixon-Colesista):
      goal_mult     — joukkueen maaliodotus tässä fixturessa / neutraali keskiarvo
      cs_prob       — P(joukkue pitää nollan)
      conceded_dist — [P(vastustaja tekee k)] k=0..N
      opp_goal_mult — vastustajan maaliodotus / vastustajan neutraali keskiarvo
    """
    share = xmins / 90.0
    goal_mult = ctx.get("goal_mult", 1.0)
    comp = {
        "appearance": 2.0 * p60 + 1.0 * p1_59,
        "goals": rates["xg90"] * share * goal_mult * GOAL_PTS[pos],
        "assists": rates["xa90"] * share * goal_mult * ASSIST_PTS,
        "clean_sheet": CS_PTS[pos] * ctx.get("cs_prob", 0.0) * p60,
        "conceded": 0.0,
        "saves": 0.0,
        "def_contribution": 0.0,
        "cards": -1.0 * rates["yc90"] * share,
        "bonus": min(rates["bonus90"] * share, 3.0),
    }
    if pos in (1, 2):
        comp["conceded"] = -expected_conceded_penalty(
            ctx.get("conceded_dist", [1.0])) * share
    if pos == 1:
        comp["saves"] = (rates["saves90"] * share
                         * ctx.get("opp_goal_mult", 1.0)) / SAVE_PTS_PER
    if pos in DC_THRESHOLD:
        comp["def_contribution"] = DC_PTS * rates["dc_freq"] * p60
    comp["total"] = sum(v for k, v in comp.items() if k != "total")
    return comp


# ---------------------------------------------------------------------------
# Tuotanto-JSON:n loader (/api/fantasy/xp) — peili: fpl_phase0.load_phase0
# ---------------------------------------------------------------------------
def empty_xp() -> dict:
    """Runko kun projektiota ei ole committattu — appi näyttää tyhjän tilan."""
    return {
        "meta": {
            "product": "GoalIQ Fantasy Phase 1 — expected points (xP)",
            "available": False,
            "phase": 1,
            "season": None,
            "generated_at": None,
            "next_gameweek": None,
            "horizon_gw": 0,
        },
        "players": [],
    }


def load_xp(path: Path = XP_PATH) -> dict:
    if not path.exists():
        return empty_xp()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return empty_xp()
    if not isinstance(data, dict) or "players" not in data or "meta" not in data:
        return empty_xp()
    return data
