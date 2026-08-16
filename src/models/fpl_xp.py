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

# SPL-fantasy (7.8): sama serving-polku, eri projektio — /api/fantasy/xp?league=spl.
# Builderi: scripts/build_spl_xp.py (RSL-pisteytys, src/models/spl_xp.py).
# Sama ei-fallback-periaate kuin fpl_phase0.PHASE0_PATHS: tuntematon avain = 404.
SPL_XP_PATH = config.DATA_DIR / "spl_xp_projections.json"
XP_PATHS = {"fpl": XP_PATH, "spl": SPL_XP_PATH}

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


# ---------------------------------------------------------------------------
# #151: FPL 26/27 BPS-sääntömuutos — historiallisen bonuksen oikaisu
# ---------------------------------------------------------------------------
# Bonus-komponentti on empiirinen per-90-vauhti, joka on opittu 25/26-
# historiasta VANHOILLA BPS-säännöillä. FPL muutti BPS:ää 26/27:ään
# (lähde: premierleague.com "What's new in 2026/27 Fantasy: Changes to
# Bonus Points System", /en/news/4679946, julkaistu 20.7.2026):
#   1. CBI: 1 BPS / 2 CBI  ->  1 BPS / 3 CBI             (laskettavissa)
#   2. Pilkkutorjunta: 8 BPS -> 7 BPS                     (laskettavissa)
#   3. "Tackled" (-1 BPS / taklatuksi tulo): poistettu    (EI FPL-API:ssa)
#   4. GK-torjunnat: 3 (boksista) / 2 (ulkoa) -> 2 / mikä tahansa torjunta
#      + uusi +1 BPS / big chance -torjunta               (jakoa EI API:ssa)
# Historiallinen per-rivi-BPS oikaistaan VAIN laskettavista osista (1+2,
# kentät clearances_blocks_interceptions + penalties_saved) ja ottelun
# bonukset jaetaan uudelleen oikaistulla BPS:llä (top-3 = 3/2/1).
# Kohtia 3-4 EI arvata (#151-portti: älä fabrikoi painoja). Suunta on
# silti oikea: CBI-raskaiden BPS laskee -> uudelleenjaossa maalivahdit,
# laiturit ja hyökkääjät nousevat. Dokumentoitu vaje: dribblaajien
# (tackled-poisto) ja GK:n (big chance -metriikka) nousu ALIarvioituu.
BPS_2627_CBI_PER = 3         # oli: 1 BPS / 2 CBI
BPS_2627_PENSAVE_DELTA = -1  # pilkkutorjunta 8 -> 7 BPS


def bps_2627_delta(row: dict) -> int:
    """Laskettavissa oleva BPS-muutos 26/27-säännöillä yhdelle historiariville."""
    cbi = int(row.get("clearances_blocks_interceptions", 0) or 0)
    pens = int(row.get("penalties_saved", 0) or 0)
    return (cbi // BPS_2627_CBI_PER - cbi // 2) + BPS_2627_PENSAVE_DELTA * pens


def allocate_bonus(bps_list: list[float]) -> list[int]:
    """FPL:n bonusjako BPS-arvoille: korkein 3, toinen 2, kolmas 1.

    Viralliset tasapelisäännöt: tasoissa 1. sijalla -> kaikki 3, seuraava 1;
    tasoissa 2. sijalla -> 1. saa 3, tasoissa olevat 2, 1 pistettä ei jaeta;
    tasoissa 3. sijalla -> kaikki tasoissa olevat 1.
    """
    order = sorted(range(len(bps_list)), key=lambda i: -bps_list[i])
    pts_by_rank_start = {0: 3, 1: 2, 2: 1}
    out = [0] * len(bps_list)
    pos = 0
    while pos < len(order) and pos <= 2:
        group = [order[pos]]
        while (pos + len(group) < len(order)
               and bps_list[order[pos + len(group)]] == bps_list[group[0]]):
            group.append(order[pos + len(group)])
        pts = pts_by_rank_start[pos]
        for i in group:
            out[i] = pts
        pos += len(group)
    return out


def adjust_summaries_bps_2627(summaries: dict[int, list[dict]]) -> dict[int, list[dict]]:
    """Palauttaa summaries-kopion, jossa rivien 'bonus' on jaettu uudelleen
    26/27-oikaistulla BPS:llä (ottelukohtainen top-3-jako, allocate_bonus).

    Puhdas funktio: syötettä ei mutatoida; vain minuutteja saaneet rivit
    osallistuvat jakoon. Rajoite: jakopooli = välimuistin pelaajat (nykyisen
    bootstrapin elementit) -> kesken kauden liigasta poistuneet puuttuvat
    yksittäisten otteluiden poolista. Vaikutus on pieni ja suuntaamaton
    (sama vaje koskee ennen- ja jälkeen-ajoa identtisesti).
    """
    pool: dict[int, list[tuple[int, int, float]]] = {}
    for pid, hist in summaries.items():
        for i, r in enumerate(hist):
            fx = r.get("fixture")
            if fx is None or not (r.get("minutes", 0) or 0):
                continue
            adj = float(r.get("bps", 0) or 0) + bps_2627_delta(r)
            pool.setdefault(fx, []).append((pid, i, adj))

    new_bonus: dict[tuple[int, int], int] = {}
    for entries in pool.values():
        alloc = allocate_bonus([b for _, _, b in entries])
        for (pid, i, _), pts in zip(entries, alloc):
            new_bonus[(pid, i)] = pts

    out: dict[int, list[dict]] = {}
    for pid, hist in summaries.items():
        rows: list[dict] = []
        for i, r in enumerate(hist):
            nb = new_bonus.get((pid, i))
            if nb is None or nb == (r.get("bonus", 0) or 0):
                rows.append(r)
            else:
                r2 = dict(r)
                r2["bonus"] = nb
                rows.append(r2)
        out[pid] = rows
    return out


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
# Pre-season (n_last=None): koko päättynyt kausi eksponentiaalisella
# vaimennuksella, puoliintuma PRESEASON_HALFLIFE kierrosta.
#
# Oli aiemmin tasapaino, perusteena "kauden lopun rotaatio ei saa dominoida
# uuden kauden GW1-arviota". Se ylikorjasi: 12 kierroksen loukkaantumisjakso
# painoi yhtä paljon kuin sen jälkeinen 22/24-avausputki, joten roolinsa
# TAKAISIN saaneet luettiin yhä vaihtomiehiksi (mitattu 9.8.2026: Palmer
# 51,4 min vaikka avasi 22 kertaa 24:stä kauden lopussa).
#
# Mitattu kauden sisäisellä proxylla (kouluta kierroksilla 1..K, ennusta
# K+1..K+6; K = 10/12/15/19/22/26/30; n = 2630 pelaaja-ikkunaa):
#   tasapaino 20,96 · hl16 20,48 · hl12 20,35 · hl10 20,26 · hl8 20,13 ·
#   hl6 19,98 · hl4 19,81 min MAE.
# Tasapaino häviää JOKAISESSA leikkauksessa.
#
# Valittu 10 eikä proxyn paras 4: proxy ei näe kesätaukoa, joka on juuri se
# mekanismi jota alkuperäinen tasapaino suojasi (kauden lopun lepuutus ei
# ennusta elokuuta). 10 säilyttää roolisignaalin ja vaimentaa lepuutus-
# artefaktin. Vakio on HARKINTA, ei sovitettu optimi — arvioi uudelleen kun
# 26/27-kierroksia on kertynyt (silloin live-polku ottaa muutenkin vallan).
PRESEASON_HALFLIFE = 10.0
# p_start-kalibrointi: raaka start-share YLIarvioi startteja korkeissa arvoissa
# (rotaatio-regressio, todettu backtestissä: raaka Brier 0.175 vs p60-proxy
# 0.167) → NÄYTETTÄVÄ p_start shrinkataan neutraalia prioria kohti. xMins
# johdetaan RAA'ASTA sharesta (shrinkattu p_start veisi minuutit keskinkertaisiksi
# → MAE huononisi; eriytys dokumentoitu backtestissä: MAE 21.15 + Brier 0.164
# = molemmat paremmat kuin baseline 21.60 / 0.167).
P_START_SHRINK = 0.2
P_START_PRIOR = 0.5   # neutraali — EI backtestistä sovitettu (rakenteellinen)

# ---------------------------------------------------------------------------
# CONFIDENCE-KYNNYKSET (kiristetty 10.8.2026)
#
# VIKA JOKA KORJATTIIN: raja oli 0.2/0.8, ja se antoi "high"-lipun 167
# pelaajalle joista 72:lla (43 %) odotetut minuutit olivat alle 20. Chiesan
# raaka start-share oli 0.198 — juuri kynnyksen alla → "high", vaikka näytöllä
# luki samaan aikaan "26 % start" ja hänen todennäköisin lopputuloksensa oli
# vaihdosta tulo (p_cameo 0.47).
#
# 0.2 EI OLE VAKAUS. Se tarkoittaa että pelaaja aloittaa joka viidennen pelin,
# eli rotaatioarpajaiset — juuri se tila jossa estimaatti on epävarrimmillaan.
# Vakaa on vasta kun lopputulos on ~90 % ratkennut kumpaan tahansa suuntaan.
#
# Kynnys on arvostelukysymys eikä sovitettu parametri, ja se sanotaan tässä
# ääneen: ship-gate mittaa xP:tä eikä lippuja, joten se EI voi validoida tätä
# lukua. Muutos ei liikuta yhtäkään xP:tä, xMins:iä tai p_startia.
# ---------------------------------------------------------------------------
CONF_STABLE_LO = 0.10
# YLARAJA JATETTIIN ENNALLEEN (0.80) TARKOITUKSELLA. Kokeilin 0.90:aa ja se
# pudotti Gabrielin (88 xmins) ja Ricen (86 xmins) med-tasolle — naulatut
# avaajat, joiden minuutit ovat juuri niita joista olemme varmimpia.
# Epavarmuus on epasymmetrinen vaikka varianssi p(1-p) on symmetrinen:
# p=0.2 tarkoittaa ennustetta ~20 min kun toteuma on 0 tai 80, eli suhteellinen
# virhe on valtava; p=0.8 tarkoittaa ~75 min kun toteuma on 0 tai 90.
# Mitattu vika oli alapaassa, joten vain alaraja kiristettiin.
CONF_STABLE_HI = 0.80
CONF_MIN_OBS_HIGH = 4
CONF_MIN_OBS_MED = 3
_CONF_RANK = {"low": 0, "med": 1, "high": 2}


def derive_confidence(n_obs: int, p_start_raw: float) -> str:
    """low/med/high otoskoosta ja start-signaalin vakaudesta."""
    stable = p_start_raw <= CONF_STABLE_LO or p_start_raw >= CONF_STABLE_HI
    if n_obs >= CONF_MIN_OBS_HIGH and stable:
        return "high"
    if n_obs >= CONF_MIN_OBS_MED:
        return "med"
    return "low"
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


def start_weights(n: int, n_last: int | None) -> list[float]:
    """Recency-painot n:lle havaitulle kierrokselle (vanhin → uusin).

    n_last=None (pre-season): eksponentiaalinen vaimennus, puoliintuma
    PRESEASON_HALFLIFE kierrosta.
    n_last=k (live-kausi): lineaarinen ramppi 1..k, josta otetaan viimeiset n
    → k=4 ja n≤4 tuottaa täsmälleen entisen START_WEIGHTSin (1,2,3,4).

    Palauttaa AINA tasan n painoa. Aiempi `START_WEIGHTS[-len(rounds):]`
    palautti korkeintaan 4 painoa, joten builderin live-asetuksella n_last=6
    zip(w, rounds) katkesi neljään pariin: kaksi TUOREINTA kierrosta jäi
    kokonaan pois ja recency-järjestys kääntyi ikkunan sisällä (todennettu
    9.8.2026 — kierrokset 1-4 avannut, 5-6 penkittänyt pelaaja sai
    p_start 1,0 / xmins 90,0).
    """
    if n <= 0:
        return []
    if n_last is None:
        return [0.5 ** ((n - 1 - i) / PRESEASON_HALFLIFE) for i in range(n)]
    base = max(n_last, n)
    return [float(base - n + i + 1) for i in range(n)]


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

    n_last=None = koko ikkuna eksponentiaalisella recency-vaimennuksella
    (pre-season-snapshot päättyneestä kaudesta, ks. PRESEASON_HALFLIFE).
    HUOM: minutes_form käyttää yhä tasapainoa n_last=None:lla — se on vanha,
    tuotannosta korvattu polku (build_fpl_xp käyttää minutes_modelia).

    team_rounds_before pitää olla PELAAJAN OMAN joukkueen pelatut kierrokset,
    ei kaikkien joukkueiden kierrosten unioni: blank gameweek on rivitön
    kierros, joka unionissa luetaan penkitykseksi ja painaa p_startia alas.
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
    w = start_weights(len(rounds), n_last)
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
    base["confidence"] = derive_confidence(base["n_obs"], base["p_start_raw"])
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
    # 10.8: lippu seuraa nyt sitä lukua jota se kuvaa. Aiemmin confidence
    # laskettiin KERRAN historiaikkunasta eikä sitä koskaan tarkistettu, vaikka
    # saatavuus- ja syvyysskaalaukset muuttavat p_startia jälkikäteen — eli
    # lippu kuvasi eri lukua kuin se joka näytettiin.
    #
    # VAIN ALASPÄIN: skaalaus ei saa NOSTAA luottamusta. Loukkaantumislippu vie
    # p_start_raw'n nollaan, mikä näyttäisi "vakaalta" ja tuottaisi high-lipun
    # FPL:n lipun perusteella eikä meidän datastamme. Se olisi sama vika
    # toisin päin.
    if "confidence" in mm:
        cand = derive_confidence(int(mm.get("n_obs") or 0), mm["p_start_raw"])
        if _CONF_RANK[cand] < _CONF_RANK[mm["confidence"]]:
            mm["confidence"] = cand
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


# Rakenteellinen joukkuerajoite (5.8.2026)
# ---------------------------------------------------------------------------
# `depth_factor`in `slots` lasketaan SAMOJEN pelaajien viime kauden starteista
# (build_fpl_xp.py), eli se on itsekonsistentti — ja juuri siksi hampaaton:
# kun klubille tulee kaksi entista ykkosvahtia, slots ~ 2 ja rajoite EI SIDO
# KOSKAAN. Mitattu tuotannosta 5.8.2026: Tottenhamin maalivahtien Sigma p_start
# oli 2,10 kun avauspaikkoja on tasan 1 (Dubravka 81,6 min JA Vicario 74,4 min
# samassa ottelussa), 7/20 klubia yli 25 % rajasta, ja kenttapelaajien summa
# vaihteli 4,71 (Hull) - 13,40 (Chelsea) kun sen pitaa olla 10.
#
# Nama kaksi lukua eivat ole malliparametreja vaan pelin saantoja: joukkue
# aloittaa tasan 11 pelaajalla joista tasan 1 on maalivahti. Siksi ne saavat
# olla kovakoodattuja - toisin kuin muodostelmajakauma (4-4-2 vs 3-5-2), jota
# EI oleteta tassa lainkaan: kenttapelaajat normalisoidaan yhtena ryhmana,
# joten viiden puolustajan joukkue pysyy viiden puolustajan joukkueena.
TEAM_GK_SLOTS = 1.0
TEAM_OUTFIELD_SLOTS = 10.0
# Naulatun avaajan suoja (Villen korjaus 5.8. illalla): kenttapelaajat
# normalisoidaan yhtena ryhmana jottei muodostelmaa oleteta - mutta silloin
# keskikentan ylibuukkaus vuotaa ykkoshyokkaajan minuutteihin. Haaland on
# selkea ykkoshyokkaaja eika keskikenttakilpailu koske hanta. Siksi leikkaus
# EI kosketa pelaajia joiden raaka start-share on yli taman: ylibuukkaus ei
# koskaan synny naulatuista (heita mahtuu XI:hin enintaan 10) vaan siita etta
# usea epavarma jakaa samat kiistanalaiset paikat. 0.85 ~ 32/38 starttia.
NAILED_PROTECT_P_START = 0.85


def structural_exponent(p_starts: list[float], slots: float,
                        lo: float = 1.0, hi: float = 12.0) -> float:
    """Eksponentti k jolla Sigma p_i**k == slots (ylibuukattu ryhma).

    MIKSI EI TASAISTA KERROINTA: tasainen skaalaus panee varman avaajan
    maksamaan ryhmansa syvyydesta. Mitattu 5.8: Chelsean kenttapelaajien summa
    oli 13,40, ja tasainen x0,75 vei 15 min myos naulatuilta (Lacroix 86,7 ->
    71,3). Ylibuukkaus EI synny naulatuista pelaajista vaan siita etta usea
    epavarma pelaaja saa uskottavan aloitus-tn:n samaan paikkaan, joten leikkaus
    kuuluu sinne.

    p**k saastaa suuret arvot ja leikkaa pienet jyrkasti (0,9**3 = 0,73 mutta
    0,3**3 = 0,03). Ratkaistaan puolitushaulla: Sigma on aidosti laskeva k:n
    suhteen kun kaikki p < 1, joten juuri on yksikasitteinen.
    """
    tot = sum(p_starts)
    if tot <= slots or slots <= 0:
        return 1.0
    for _ in range(60):
        mid = (lo + hi) / 2.0
        if sum(p ** mid for p in p_starts) > slots:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def scale_p_start(mm: dict, factor: float) -> dict:
    """Skaalaa aloitus-tn (capattu [0,1]) ja johda minuutit uudelleen."""
    out = dict(mm)
    out["p_start_raw"] = min(max(mm["p_start_raw"] * factor, 0.0), 1.0)
    out["p_start"] = min(max(mm["p_start"] * factor, 0.0), 1.0)
    return recompute_minutes(out)


# ---------------------------------------------------------------------------
# Hintapriori ohuelle otokselle (27.7). Parametrit MITATTU, ei valittu:
# scripts/backtest_preseason_price_prior.py, koe = ennusta 25/26 GW1-6
# tiedoilla jotka tiedettiin ennen kauden alkua.
#
#   ohut otos  (<900 min edelliskaudella)  Brier 0.0540 -> 0.0454  +15.9 %
#   paksu otos (>=900 min)                 0.1494 -> 0.1492  +0.2 % (neutraali)
#
#   KALLIS + ohut (Isak-tapaus, n=19)      0.1517 -> 0.0987  +35.0 %
#       baseline arvioi aloitusosuudeksi 0.13, TOTEUTUNUT 0.37
#   HALPA  + ohut (aito reservi, n=145)    0.0145 -> 0.0147  -1.5 %
#       baseline 0.01, toteutunut 0.03 -> jo oikeassa, priori ei tee tyota
#
# Miksi hinta on informaatiota: FPL:n hinnoittelu on RIIPPUMATON arvio
# odotetusta roolista, tehty tiedolla jota mallilla ei ole. Malli nakee vain
# minuuttiluvun eika sita miksi minuutteja on vahan.
#
# PAKSUUN OTOKSEEN EI KOSKETA: siella mittaus nayttti neutraalin, eika prioria
# saa kayttaa korjaamaan sita mika ei ole rikki.
#
# ===========================================================================
# 🔴 EI KYTKETTY TUOTANTOON. ALA KYTKE ILMAN ALLA OLEVAA TYOTA.
#
# Kytkettiin kokeeksi 27.7 ja PERUUTETTIIN. Priori itsessaan toimii, mutta sen
# VUOROVAIKUTUS SYVYYSNORMALISOINNIN kanssa tuottaa systemaattista vahinkoa
# jota backtest ei mitannut:
#
#   paksu otos (n=131, p_start >= 70 %)  xP-muutos mediaani -5.3 %
#     yli 5 % pudonneita 68/131,  yli 10 % 22/131
#   Raya       6.0M  24.65 -> 18.05  (-26.8 %)   omistus 29.8 %
#   Donnarumma 5.5M  20.13 -> 14.91  (-25.9 %)
#   Pickford   5.5M  24.50 -> 18.49  (-24.5 %)
#
# MEKANISMI: maalivahtiryhmassa on YKSI paikka ja 2-3 pelaajaa. Kun priori
# nostaa kakkosvahdin p_startia, depth_factor skaalaa koko ryhman alas ja
# ykkosvahti absorboi lahes kaiken. Lisaksi hinta EI EROTTELE maalivahteja
# (kaikki 4.0-5.5M) -> persentiili ei kanna informaatiota roolista, mutta
# priori luottaa siihen silti.
#
# OPPI: backtest oli patea siihen kysymykseen joka esitettiin, mutta kysymys
# oli vajaa. Vaikutus mitattiin HINTATASOITTAIN muttei POSITIOITTAIN, eika
# vuorovaikutusta normalisoinnin kanssa mitattu lainkaan. Otsikkoluku parani
# ja olisi peittanyt taman alleen.
#
# ENNEN KYTKENTAA TARVITAAN:
#   1. Per-positio-validointi (GK erikseen; hinta ei todennakoisesti kelpaa
#      siella priorina lainkaan)
#   2. Mittaus priorin JA depth_factorin yhteisvaikutuksesta, ei pelkastaan
#      priorista
#   3. Regressioportti korkean omistuksen pelaajille: yksikaan >10 % omistettu
#      ei saa pudota merkittavasti ilman eksplisiittista perustelua
# ===========================================================================
# ---------------------------------------------------------------------------
PRICE_PRIOR_WEIGHT = 0.25
PRICE_PRIOR_THIN_MINUTES = 900


def apply_price_prior(mm: dict, price_pct: float, prior_minutes: float,
                      weight: float = PRICE_PRIOR_WEIGHT,
                      thin_minutes: float = PRICE_PRIOR_THIN_MINUTES) -> dict:
    """Sekoita position sisainen hintapersentiili aloitus-tn:aan OHUELLA otoksella.

    price_pct
        0..1, hintapersentiili SAMAN POSITION sisalla. Positioiden valinen
        vertailu olisi merkityksetonta: 5.5M puolustaja ja 5.5M hyokkaaja ovat
        eri rooleja.
    prior_minutes
        Otoksen koko minuutteina. >= thin_minutes -> palautetaan muuttumattomana.

    Askelfunktio eika liukuva paino: tasan se muoto joka mitattiin. Liukuva
    olisi tyylikkaampi mutta validoimaton.
    """
    if prior_minutes >= thin_minutes or weight <= 0.0:
        return mm
    out = dict(mm)
    for k in ("p_start", "p_start_raw"):
        blended = (1.0 - weight) * out[k] + weight * float(price_pct)
        out[k] = min(max(blended, 0.0), 1.0)
    return recompute_minutes(out)


def set_p_start(mm: dict, p_start: float) -> dict:
    """Aseta aloitus-tn SUORAAN (manuaalinen ohitus) ja johda minuutit uudelleen.

    Ero `scale_p_start`iin: tuo kertoo nykyisen arvion kertoimella (syvyys-
    korjaus), tämä korvaa sen. Käytetään vain kun viime kauden minuutit eivät
    kuvaa nykyistä roolia — ks. src/models/fpl_player_overrides.py.

    Asettaa sekä p_start_raw (minuuttien johtaminen) että p_start (näyttö/
    kalibrointi) samaan arvoon: ohituksen koko pointti on että historiapohjainen
    shrinkkaus ei päde tähän pelaajaan.
    """
    out = dict(mm)
    v = min(max(float(p_start), 0.0), 1.0)
    out["p_start_raw"] = v
    out["p_start"] = v
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


# Bonuksen fixture-herkkyys. 0.0 = vanha kayttaytyminen (vastustajasokea).
# Kalibrointi ja perustelu: ks. xp_components / "bonus".
BONUS_FIXTURE_BETA = 0.837


def _bonus_fixture_mult(goal_mult: float) -> float:
    """Bonuskerroin ottelulle. Rajattu >=0, jotta aariarvo ei tee negatiivista
    bonusta (goal_mult voi periaatteessa olla hyvin pieni)."""
    return max(0.0, 1.0 + BONUS_FIXTURE_BETA * (goal_mult - 1.0))


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
        # 28.7: bonus skaalataan OTTELUN mukaan. Mitattu 25/26:n per-ottelu-
        # historiasta (7382 ottelua, >=60 min, pelaajan sisaiset poikkeamat eli
        # pelaajan taso ei sekoita tulosta): bonus korreloi vastustajan
        # heikkouden kanssa r=+0.074 ja BPS r=+0.167 (bonus on vain top-3-
        # leikkaus BPS:sta, mika puristaa signaalin kasaan). Ero helpoimman ja
        # vaikeimman vastustajan valilla oli 0.14 pistetta/ottelu.
        # Beta kalibroitu LEAVE-ONE-OUT (vastustajan kausisummista poistettiin
        # kysessa oleva ottelu) samaan muotoon jota malli kayttaa:
        # d(bonus)/d(goal_mult) = 0.252, keskibonus 0.301 -> beta 0.837.
        # SAMASSA mittauksessa DefCon (+0.026) ja kortit (+0.034) osoittautuivat
        # kaytannossa vastustajariippumattomiksi -> ne jatetaan ennalleen.
        "bonus": min(rates["bonus90"] * share * _bonus_fixture_mult(goal_mult),
                     3.0),
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
# Vauhti erillään minuuteista (5.8, korjattu 5.8 illalla)
# ---------------------------------------------------------------------------
# `xp_per_gw` kertoo pistevauhdin ja minuuttiodotuksen YHTEEN. 4.8. mitattiin
# että virhe on horisontin funktio (vakiopelaaja +37,9 % 33 GW:n päässä), ja se
# on yhteensopiva sen kanssa että pettävä oletus on nimenomaan minuuttien
# pysyvyys. Kun vauhti ja minuutit näytetään erikseen, se oletus on lukijan
# nähtävissä eikä piilossa yhdessä luvussa.
#
# 🔴 ALKUPERÄINEN KAAVA OLI VÄÄRÄ, ja tapa jolla se oli väärä on opetus.
# Se oli `xp_per_gw * 90 / xmins`, mikä olettaa että xP on LINEAARINEN
# minuuttien suhteen. `xp_components` sanoo toisin: kolme komponenttia on
# porrasfunktioita jotka eivät skaalaudu minuuteilla lainkaan —
#   appearance       = 2.0*p60 + 1.0*p1_59   (esiintymisestä, ei kestosta)
#   clean_sheet      = CS_PTS * cs_prob * p60
#   def_contribution = DC_PTS * dc_freq * p60
# Vain maalit/syötöt/kortit/bonus/päästetyt/torjunnat skaalautuvat `share`lla.
#
# Seuraus mitattiin tuotannosta: 16,2 odotetun minuutin pelaajalla 72 % GW1-xP:stä
# oli esiintymispiste, ja kun se jaettiin 16 minuutilla ja skaalattiin 90:een,
# siitä tuli YKSINÄÄN 4,83 "pistettä per 90". Julkaistu sarake nosti hänet koko
# projektion kärkeen (7,06) ohi pelaajan jonka todellinen vauhti on 2,4-kertainen.
# Sarake ei ollut epätarkka vaan KÄÄNTEINEN hännässä.
#
# Korjattu määritelmä: per-90 = "mitä hän tekisi jos pelaisi täydet 90" eli
# xp_components ajettuna arvoilla xmins=90, p60=1, p1_59=0. Se on se mitä lukija
# joka tapauksessa luulee lukevansa, ja se on vertailukelpoinen kaikkien välillä.
# Luku EI ole enää johdettavissa (xp_per_gw, xmins) -parista, koska p60 ei ole
# rekonstruoitavissa tarjoillusta rivistä → laskenta kuuluu putkeen ja kenttä
# tulee JSON:ista. Serve-time EI arvaa sitä: puuttuva kenttä = None.
#
# Miksi None eikä vanha kaava fallbackina: väärä luku on huonompi kuin puuttuva.
# Nolla taas lukisi "ei tuota pisteitä", mikä on eri väite kuin "emme tiedä".


def xp_full_90(pos: int, rates: dict, ctx: dict) -> float:
    """xP yhdelle fixturelle jos pelaaja pelaisi TÄYDET 90 minuuttia.

    Sama funktio josta totalit lasketaan (ei rinnakkaista kaavaa): erona vain
    minuuttiparametrit. p60=1.0 ja p1_59=0.0 = pelaaja on kentällä koko ajan,
    joten esiintyminen on täydet 2 pistettä eikä cameo-odotusarvo, ja CS/DefCon
    ovat täydellä painolla."""
    return xp_components(pos, rates, 90.0, 1.0, 0.0, ctx)["total"]


def empty_xp() -> dict:
    """Runko kun projektiota ei ole committattu — appi näyttää tyhjän tilan."""
    return {
        "meta": {
            "product": "GoalIQ Fantasy Phase 1: expected points (xP)",
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
    # Vauhti tulee PUTKESTA, ei serve-timesta. Alkuperäinen 5.8. suunnittelu
    # johti kentän tässä (xp_per_gw / xmins) jottei syntyisi toista totuutta —
    # mutta se derivaatio oli väärä (ks. xp_full_90:n yllä oleva perustelu),
    # eikä oikeaa voi laskea tästä: p60 ei ole rivillä. Vanha rivi ilman kenttää
    # saa None:n, ei arvausta.
    for p in data.get("players") or []:
        if isinstance(p, dict):
            p.setdefault("xp_per_90", None)
    return data


WHY_PATH = config.DATA_DIR / "fpl_why.json"


def load_why(path: Path = WHY_PATH) -> dict:
    """WHY-THIS-PICK -selitykset (scripts/build_fpl_why.py). Puuttuu = {}."""
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    entries = data.get("entries")
    return entries if isinstance(entries, dict) else {}


def why_stamp(path: Path = WHY_PATH) -> str:
    """Selitystiedoston sormenjalki ETagiin.

    ILMAN TATA `why` OLISI NAKYMATON PAIVITYS: selitykset elävät omassa
    tiedostossaan, joten `generated_at` ei liiku kun ne uusitaan, ja ehdollinen
    pyyntö validoisi vanhan vastauksen 304:llä. Tiedoston koko + muokkausaika
    riittää ja on ilmainen (ei sisällön hashausta joka pyynnöllä, Render
    0.5 vCPU). Deploy vaihtaa mtimen — turha 200 kerran per deploy on halpa.
    """
    try:
        st = path.stat()
        return f"{st.st_mtime_ns}-{st.st_size}"
    except OSError:
        return "0"


WHY_DEFAULT_LANG = "en"
WHY_LANGS = ("en", "es", "pt")


def attach_why(payload: dict, entries: dict | None = None,
               lang: str = WHY_DEFAULT_LANG) -> dict:
    """Liita selitys jokaiselle riville jolle sellainen on.

    SERVE-TIME eikä putkessa, koska projektio kirjoitetaan uusiksi 3 h välein
    ja selitykset elävät omassa tiedostossaan: yhdistäminen levyllä pyyhkisi
    ne joka refreshissä. Sama kaava kuin xp_per_90:llä yllä.

    HUOM ETag: tämä on serve-time-kenttä, joten `generated_at` EI muutu kun
    selitykset päivittyvät. Endpointin ETag-skeemaversio on nostettava kun
    tämä kenttäjoukko muuttuu (muisti: serve-time-kenttä ei invalidoi ETagia).
    **`lang` on oltava ETagissa**: ilman sitä es-käyttäjän ehdollinen pyyntö
    validoituisi englanninkielisestä välimuistista ja hän saisi englantia.

    LOKAALI (14.8): maksumuuri lupaa `paywall.bullet_why`-rivillä selityksen
    ostajan omalla kielellä es/pt-lokaaleilla. Vanha merkintä ilman
    `sentences`-lohkoa palauttaa englannin — se on tietoinen varapolku (parempi
    kuin tyhjä kenttä), ja `why.lang` kertoo klientille MITÄ kieltä se
    oikeasti sai, jotta pinta ei voi väittää lokalisointia jota ei tapahtunut.
    """
    if entries is None:
        entries = load_why()
    if not entries:
        return payload
    lang = lang if lang in WHY_LANGS else WHY_DEFAULT_LANG
    n = 0
    for p in payload.get("players") or []:
        if not isinstance(p, dict):
            continue
        entry = entries.get(str(p.get("id")))
        if not entry:
            continue
        sentences = entry.get("sentences") or {}
        localized = sentences.get(lang)
        sentence = localized or entry.get("sentence")
        if not sentence:
            continue
        sources = entry.get("sources") or {}
        p["why"] = {
            "sentence": sentence,
            "drivers": entry.get("drivers") or [],
            # Lukija saa tietää kummasta lähteestä lause tuli. "template" ei
            # ole vika vaan tarkka mutta tylsä lause; sen piilottaminen tekisi
            # provenienssilupauksesta valikoivan.
            "source": (sources.get(lang) if localized else None)
                      or entry.get("source") or "template",
            # Toteutunut kieli, EI pyydetty kieli.
            "lang": lang if localized else WHY_DEFAULT_LANG,
        }
        n += 1
    if n:
        payload.setdefault("meta", {})["n_explained"] = n
    return payload
