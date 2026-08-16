"""FPL Phase 1 — tuotanto-builderi: xP per pelaaja per GW → staattinen JSON.

Tuottaa `data/fpl_xp_projections.json`:n jonka `/api/fantasy/xp` tarjoilee
(EI on-request-laskentaa — Render 0.5 vCPU -budjettisääntö, sama kuin Phase 0).
Ajo: ajastettu refresh-job (scripts/fpl_phase0_refresh.ps1 ajaa Phase 0:n
jälkeen) tai käsin `python -m scripts.build_fpl_xp`.

Lähteet:
  - Fixturet + kausi: sama lähdekerros kuin Phase 0 (FPL-API ensisijainen,
    pulselive-fallback kunnes FPL avaa 26/27-pelin).
  - Pelaajabaselinet: FPL-API bootstrap + element-summary -historia (pelkkä
    JSON-HTTP — EI FBrefiä/Chromea, ks. Phase 1 -riskilippuraportti).
    Pre-season: baselinet = koko 25/26-kausi; kun 26/27 avautuu, historia
    alkaa kertyä ja painottua automaattisesti (sama koodipolku).
  - Joukkuekonteksti: GoalIQ Dixon-Coles (Understat PL, sama fit kuin
    /api/predict) — CS-%, maalijakaumat, fixture-kertoimet.

xP-kaava: src/models/fpl_xp.py — TÄSMÄLLEEN sama kuin walk-forward-backtestin
(scripts/backtest_fpl_xp.py) ship-gatessa validoitu. Tuotannossa lisänä vain
FPL:n saatavuustieto (status/chance_of_playing → minuuttikerroin), jota
historiasta ei saa — vaikuttaa vain poissaolevien poistoon, ei kaavaan.

Sanity-gate (fail-safe kuten Phase 0): FAIL → JSONia EI kirjoiteta, exit 2.
EI auto-pushia: onnistunut ajo tulostaa git-komennot.
"""
from __future__ import annotations

import datetime as _dt
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

import config
from scripts.build_fpl_phase0 import (
    HORIZON_GW,
    SEASON_LABEL,
    add_promoted_baseline,
    fetch_source,
    fit_model,
    map_name,
    short_name,
)
from src.data import fpl_api
from src.data.loader import lataa_otteludata
from src.models import fpl_xp as xp
from src.models.fpl_context import (
    PROMOTED_HOME_OPENER_ATT_BOOST,
    build_context,
    fixture_adjustments,
    fixture_contexts,
    load_overrides,
    neutral_lambda,
    promoted_teams,
    xmins_multiplier,
)
from src.models.fpl_player_overrides import load_player_overrides

OUT_PATH = config.PROJECT_ROOT / "data" / "fpl_xp_projections.json"

# Pre-season-baselinet (26/27-flippi 23.7.2026): FPL:n element-summary
# tarjoilee vain kuluvan kauden historian → flipin jälkeen historiat ovat
# tyhjiä JA element-id:t vaihtuneet. Edellisen kauden per-GW-data jäädytettiin
# committoiduksi artefaktiksi (scripts/build_fpl_prev_baselines.py), avaimena
# kausien yli pysyvä element code. Kun kohdekauden kierroksia alkaa kertyä,
# normaali live-polku jatkaa automaattisesti (sama koodipolku kuin ennen).
PREV_BASELINES_PATH = config.PROJECT_ROOT / "data" / "fpl_prev_baselines_2526.json"

# Pudota kuollut paino JSONista (ei minuutteja odotettavissa, ei pisteitä).
MIN_XP_TOTAL = 1.0


# ---------------------------------------------------------------------------
# Saatavuus (vain tuotanto — backtestissä ei historiallista statusta)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Avopeliosuus (15.8.2026) — ks. soveltamiskohdan kommentti build():ssa.
# ---------------------------------------------------------------------------
SHOTS_PATH = config.PROJECT_ROOT / "data" / "understat_player_shots_2526.json"


def _shot_key(element: dict) -> str:
    """Normalisoitu nimiavain FPL-elementille laukausdatan yhdistamiseen."""
    import unicodedata
    name = (element.get("full_name")
            or f"{element.get('first_name', '')} {element.get('second_name', '')}")
    s = unicodedata.normalize("NFKD", str(name))
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return " ".join(s.split())


def effective_team_mult(t_mult: float, open_play_share: float) -> float:
    """Joukkuekerroin painotettuna pelaajan avopeliosuudella.

    share 1.0 -> koko joukkuevaikutus (entinen kaytos)
    share 0.0 -> ei vaikutusta lainkaan (kaikki xG erikoistilanteista)
    Omana funktiona jotta saanto on testattavissa ilman koko builderia.
    """
    return 1.0 + (t_mult - 1.0) * open_play_share


def _load_open_play_share() -> dict[str, float]:
    """{nimiavain: avopeliosuus} Understatin laukausdatasta.

    osuus = 1 - spxg/npxg. Puuttuva tai nolla npxg -> pelaajaa ei kirjata,
    jolloin kutsuja saa oletuksen 1.0 eli entisen kayttaytymisen.
    """
    if not SHOTS_PATH.exists():
        return {}
    try:
        import json as _json
        doc = _json.loads(SHOTS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out: dict[str, float] = {}
    import unicodedata
    for r in doc.get("players") or []:
        npxg = float(r.get("npxg") or 0.0)
        if npxg <= 0:
            continue
        spxg = float(r.get("spxg") or 0.0)
        share = 1.0 - min(spxg / npxg, 1.0)
        s = unicodedata.normalize("NFKD", str(r.get("name") or ""))
        key = " ".join("".join(
            c for c in s if not unicodedata.combining(c)).lower().split())
        if key:
            out[key] = share
    return out


def availability_factor(element: dict) -> float:
    """FPL status → minuuttikerroin. a=pelattavissa, d=epävarma (chance-%),
    i/s/u/n = sivussa.

    #33: tuotantopolku käyttää nyt xp.apply_availability-porttia (sama
    semantiikka p_start/p_sub-tasolla) — tämä säilyy refresh-testien
    (test_fpl_availability.py) kiinnityspisteenä statussemantiikalle."""
    status = element.get("status", "a")
    if status == "a":
        return 1.0
    if status == "d":
        chance = element.get("chance_of_playing_next_round")
        return (chance / 100.0) if chance is not None else 0.5
    return 0.0


# ---------------------------------------------------------------------------
# Sanity-gate
# ---------------------------------------------------------------------------
def sanity_gate(players: list[dict], boot: dict, coverable_teams: set[str],
                points_by_id: dict[int, int] | None = None) -> bool:
    """coverable_teams = tulevan kauden fixture-joukkueet joilla on FPL-
    pelaajadataa. Pre-seasonissa nousijat puuttuvat FPL:stä rakenteellisesti
    (meta.todo) — gate vaatii että KAIKKI katettavissa olevat on katettu
    ja että niitä on vähintään 15 (17 = normaali pre-season, 20 = live).

    points_by_id: tähtitestin pisteranking-lähde. Pre-seasonissa bootstrapin
    total_points on 0 kaikilla → kutsuja antaa edelliskauden pisteet
    baseline-artefaktista; None = bootstrapin total_points (live-kausi)."""
    print("\n" + "=" * 64)
    print("SANITY-GATE  (xP-jakauma + kärkipelaajat, fail-safe)")
    print("=" * 64)
    checks: list[tuple[str, bool]] = []

    checks.append((f"pelaajia outputissa >= 300 (nyt {len(players)})",
                   len(players) >= 300))
    teams = {p["team"] for p in players}
    checks.append(
        (f"kaikki katettavissa olevat joukkueet mukana "
         f"(nyt {len(teams)}/{len(coverable_teams)}, min 15)",
         teams >= coverable_teams and len(coverable_teams) >= 15))

    totals = [p["xp_horizon_total"] for p in players]
    per_gw_max = max((g["xp"] for p in players for g in p["gameweeks"]), default=0.0)
    checks.append(("ei NaN/negatiivisia xP-summia",
                   all(np.isfinite(t) and t >= 0 for t in totals)))
    checks.append((f"max yhden GW:n xP <= 15 (nyt {per_gw_max:.2f})", per_gw_max <= 15.0))

    # Dynaaminen tähtitesti: top-10 xP:n pelaajien pitää olla lähdekauden
    # pistekärkeä (top-100 total_points) — ei kovakoodattuja nimiä (siirrot).
    if points_by_id is None:
        points_by_id = {e["id"]: e["total_points"] for e in boot["elements"]}
    pts_rank = {pid: i for i, pid in enumerate(
        sorted(points_by_id, key=lambda p: -points_by_id[p]))}
    top10 = players[:10]
    hits = sum(1 for p in top10 if pts_rank.get(p["id"], 9999) < 100)
    for p in top10:
        print(f"    top-xP {p['web_name']:18s} {p['pos']}  "
              f"xP/GW {p['xp_per_gw']:.2f}  (kausirank #{pts_rank.get(p['id'], -1) + 1})")
    checks.append((f"top-10 xP:stä >= 7 lähdekauden top-100-pisteissä (nyt {hits})",
                   hits >= 7))

    starters = [p for p in players if p["xmins"] >= 60]
    if starters:
        mean_xp = float(np.mean([p["xp_per_gw"] for p in starters]))
        checks.append((f"avaajien (xMins>=60) xP/GW-keskiarvo 2..6 (nyt {mean_xp:.2f})",
                       2.0 <= mean_xp <= 6.0))

    # #33: sivussa oleva (i/s/u/n) ei saa olla top-xMins-listalla — saatavuus-
    # portin pitää nollata minuutit ennen syvyys/ruuhka-modifioijia.
    status_by_id = {e["id"]: e.get("status", "a") for e in boot["elements"]}
    top_xm = sorted(players, key=lambda p: -p["xmins"])[:20]
    bad = [p["web_name"] for p in top_xm
           if status_by_id.get(p["id"]) in ("i", "s", "u", "n")]
    checks.append((f"top-20 xMins ilman sivussa-olevia (nyt: {bad or 'puhdas'})",
                   not bad))
    # #33: predicted_starts-kenttä validi [0,100] kaikilla
    ps_ok = all(0.0 <= p.get("predicted_starts", 0.0) <= 100.0 for p in players)
    checks.append(("predicted_starts kaikilla valissa [0,100]", ps_ok))

    ok = True
    for label, passed in checks:
        print(f"  [{'OK ' if passed else 'FAIL'}] {label}")
        ok = ok and passed
    print(f"\nGATE: {'PASS' if ok else 'FAIL'}")
    return ok


# ---------------------------------------------------------------------------
# LUOTTAMUSLIPPU xP-RIVEILLE (10.8.2026)
#
# MIKSI: r/FantasyPL-lukija FPLDPS pyysi lippua nimenomaan PROJEKTIOIHIN
# ("could warn people that the projection is working with less reliable
# information"). 9.8. lippu shipattiin ottelupolulle ja CS/FDR-taulukkoon —
# xP-lista, se sivu jota han luki, ei saanut mitaan.
#
# MIKSI TASSA EIKA RENDEREISSA: tama artefakti on AINOA lahde kaikille
# xP-pinnoille (/api/fantasy/xp -> SPA + mobiili, build_fpl_longtail ->
# /fpl/expected-points, build_fpl_page -> etusivun projections-taulukko).
# Yhteen renderiin haudattu korjaus korjaa yhden nakyman: 8.8. SPA:n Fixtures
# ja Table jaivat 11 paivaksi vaaraan lahteeseen tasan nain.
#
# LIITOSAVAIN on `model_team`, sama merkkijono kuin player_row["team"] ->
# ei nimien normalisointia eika 17/20-osumaa. Nolla osumaa kaataa ajon.
#
# EI SUUNTAVAITETTA: siirtojen hinnoittelun kalibrointi kaatui 9.8. (hyokkays
# R^2 0,000, puolustus vaara merkki), joten lippu kertoo MIKA on muuttunut,
# ei mita siita seuraa. Sama sitova rajaus kuin muilla pinnoilla.
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# MINUUTTIPRIORIN REHELLISYYSLIPPU (16.8.2026, Villen paatos)
#
# 🔴 MIKSI. Ville huomasi ettei Arsenalin ennustetussa XI:ssa ole Odegaardia.
# Mitattu: korrelaatio(viime kauden avaukset / 38, p_start) = 0,785 (n=285),
# eli priori on kaytannossa viime kauden avauskertojen kopio EIKA se kysy
# miksi minuutit puuttuivat. Odegaard 1363 min / 16 avausta -> p_start 0,428,
# ja sama mies aloitti Community Shieldin kapteenina.
#
# Sama sokeus jonka takia data/fpl_player_overrides.csv on olemassa:
#   "ei pelannut koska ei ollut tarpeeksi hyva"       -> matala p_start OIKEIN
#   "ei pelannut koska oli loukkaantunut / lainalla"  -> matala p_start VAARIN
# Malli nakee vain minuuttiluvun, ei syyta.
#
# Tama lippu EI korjaa lukua. Se lopettaa luvun esittamisen mittauksena.
# Oikea korjaus on hintapriori myos pl_history-riveille, ja se vaatii
# walk-forward-backtestin (jonorivi PREDICTED-XI-PRIORI).
#
# 🔴 EI SUUNTAVAITETTA, sama sitova rajaus kuin team_flagilla: lippu kertoo
# etta arvio nojaa lyhyeen otokseen, ei sita kumpaan suuntaan luku on
# vaarassa. Katkennut kausi voi tarkoittaa loukkaantunutta tahtea TAI
# pelaajaa joka ei kelvannut, eika minuuttiluku erota niita.
# ---------------------------------------------------------------------------
# 1500 min = noin 17 ottelua taydelta 38 ottelun kaudelta. Kynnys on
# kalibroitu siihen tapaukseen josta tama alkoi: Odegaard (1363) osuu,
# Doku ja Cherki (1773) eivat. Heidan kohdallaan kyse on eri asiasta,
# XI-rungon muodosta, eika lippu saa vaittaa muuta.
SHORT_SEASON_MINUTES = 1500


def attach_minutes_basis_flag(players: list[dict]) -> int:
    """Merkitsee rivit joiden minuuttipriori nojaa katkenneeseen kauteen."""
    n = 0
    for row in players:
        # Ohitettu rivi on ihmisen paatos eika priorin tuotos -> lippu
        # valehtelisi siita mihin luku nojaa.
        if row.get("minutes_source") == "override":
            continue
        # no_history-rivit kantavat jo oman lippunsa (data_basis) eika
        # niilla ole viime kauden minuutteja joihin viitata.
        if row.get("data_basis") != "pl_history":
            continue
        mins = (row.get("last_season") or {}).get("minutes")
        if mins is None or mins >= SHORT_SEASON_MINUTES:
            continue
        row["minutes_basis_flag"] = "short_season"
        n += 1
    return n


def attach_team_confidence(players: list[dict]) -> dict:
    """Merkitsee liputetut joukkueet xP-riveille ja palauttaa meta-lohkon.

    Vain LIPUTETUT saavat rivikentan (`team_flag`): pelkka vaihtuvuusluku
    kuuluu tyokalutaulukoihin, ei jokaisen pelaajan viereen. Koko 20 joukkueen
    taulukko menee metaan, jotta pinta voi halutessaan nayttaa myos luvun
    ilman uutta liitosta.

    excluded[]-rivit jatetaan tarkoituksella rauhaan: ne kantavat vain FPL:n
    virallista tietoa eivatka sisalla projektiota jota lippu koskisi.
    """
    p = config.PROJECT_ROOT / "data" / "team_confidence.json"
    if not p.exists():
        print("      VAROITUS: team_confidence.json puuttuu — xP-riveilla "
              "EI lippuja (aja scripts.build_team_confidence)")
        return {}
    doc = json.loads(p.read_text(encoding="utf-8"))
    by_team = {t["model_team"]: t for t in doc["teams"]}

    n_joined = n_flagged = 0
    for row in players:
        t = by_team.get(row.get("team"))
        if t is None:
            continue
        n_joined += 1
        if t.get("flag"):
            row["team_flag"] = t["flag"]
            n_flagged += 1
    # Nolla osumaa = liitos on rikki. Ilman tata jokainen rivi jaisi ilman
    # lippua ja artefakti nayttaisi tasan silta kuin mitaan liputettavaa ei
    # olisi — hiljainen katoaminen, ei virhe.
    if players and not n_joined:
        raise SystemExit(
            f"team_confidence: yksikaan {len(players)} xP-rivista ei osunut "
            f"joukkueisiin {sorted(by_team)[:3]}... — model_team-liitos on "
            f"rikki, EI 'ei liputettavia'")
    print(f"      luottamuslippu: {n_flagged}/{len(players)} rivia liputettu "
          f"({n_joined} liitosta, kynnys "
          f"{doc.get('high_turnover_threshold_pct')} %)")
    return {
        "schema_version": doc.get("schema_version"),
        "basis_season": doc.get("basis_season"),
        "high_turnover_threshold_pct": doc.get("high_turnover_threshold_pct"),
        "historical_median_pct": doc.get("historical_median_pct"),
        "method": doc.get("method"),
        "note": ("Descriptive, not predictive. The flag says a rating is "
                 "built on weaker information; it does not say which way "
                 "that moves the projection."),
        "n_flagged_players": n_flagged,
        "teams": {k: {"flag": v.get("flag"),
                      "note": v.get("note"),
                      "is_promoted": v.get("is_promoted"),
                      "minutes_churn_pct": v.get("minutes_churn_pct")}
                  for k, v in by_team.items()},
    }


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--legacy-bps", action="store_true",
                    help="OHITA 26/27 BPS-oikaisu (#151) — vain ennen/jälkeen-"
                         "vertailuajoihin, EI tuotantoon")
    args = ap.parse_args(argv)

    src = fetch_source()

    print("[2/6] FPL-pelaajadata (bootstrap + element-historiat)...")
    boot = fpl_api.fetch_bootstrap()
    # Pre-season = kohdekaudella ei yhtään pelattua GW:tä → element-summaryt
    # ovat tyhjiä eikä niitä haeta; baselinet jäädytetystä artefaktista
    # (PREV_BASELINES_PATH, element code -mappaus).
    preseason = not any(ev.get("finished") for ev in boot.get("events", []))
    prev_players: dict | None = None
    recency_window = False  # True = last-6-recency minuuttimallissa
    # Addendum 2: viime kauden kausisummat player cardia varten luetaan
    # SAMASTA jaadytetysta artefaktista aina (myos live-kaudella) — se on
    # committattu ja avaimena kausien yli pysyva element code.
    try:
        prev_archive = json.loads(PREV_BASELINES_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        prev_archive = {"players": {}, "meta": {}}
    prev_by_code: dict = prev_archive.get("players") or {}
    if preseason:
        prev = prev_archive
        prev_players = prev["players"]
        summaries = {}
        print(f"      {len(boot['elements'])} pelaajaa (pre-season: baselinet "
              f"= jäädytetty {prev['meta']['season']}-artefakti, "
              f"{len(prev_players)} pelaajaa; element-summaryja ei haeta)")
        # Artefaktin bonus-historia on jo oikaistu 26/27 BPS-sääntöihin (#151)
        # jäädytettäessä — EI oikaista uudelleen.
        if args.legacy_bps:
            print("      HUOM: --legacy-bps ei vaikuta pre-season-artefaktiin "
                  "(BPS-oikaisu tehty jo jäädytettäessä)")
    else:
        # Kesken kauden historia muuttuu joka GW → pakota tuore haku.
        # Päättyneen kauden data on staattista → välimuisti riittää.
        season_live = any(not ev.get("finished") for ev in boot.get("events", []))
        recency_window = season_live
        summaries = fpl_api.fetch_all_summaries(boot, force=season_live)
        print(f"      {len(boot['elements'])} pelaajaa "
              f"({'live-kausi, tuore haku' if season_live else 'päättynyt kausi, välimuisti'})")
        # #151: bonus-historia oikaistaan 26/27 BPS-sääntöihin ennen vauhteja
        # (CBI 1/3 + pilkkutorjunta 7; ottelukohtainen bonuksen uudelleenjako).
        if args.legacy_bps:
            print("      HUOM: --legacy-bps — 26/27 BPS-oikaisu OHITETTU (vertailuajo)")
        else:
            summaries = xp.adjust_summaries_bps_2627(summaries)
            print("      bonus-historia oikaistu 26/27 BPS-sääntöihin (#151)")

    print("[3/6] Sovitetaan PL Dixon-Coles (sama fit kuin /api/predict)...")
    dc, seasons = fit_model()
    fixture_teams = sorted({map_name(t) for t in src["teams"]})
    missing = sorted(set(fixture_teams) - set(dc.attack))
    baseline = add_promoted_baseline(dc, missing)
    print(f"      {len(dc.teams_)} joukkuetta, promoted baseline: {missing or '-'}")

    # 14.8: JOUKKUETASON VOIMAOHITUS. DC-reittaus sovitetaan tuloksiin eika se
    # nae siirtoikkunaa — esikaudella se on pahimmillaan. Sovelletaan TASSA:
    # promoted baselinen JALKEEN (jotta nousijoiden rivi on olemassa) ja
    # xP-laskennan EDELLA. Ks. data/fpl_team_overrides.csv merkkisopimuksesta.
    from src.models.fpl_team_overrides import apply_to_fit
    team_overrides_applied = apply_to_fit(dc, "xp")

    print("[4/6] Pelaajavauhdit + minuuttimalli (koko saatavilla oleva historia)...")
    pos_by_player = {e["id"]: e["element_type"] for e in boot["elements"]}
    acc_by_player: dict[int, dict] = {}
    mins_by_round: dict[int, dict[int, float]] = {}
    starts_by_round: dict[int, dict[int, int]] = {}
    for e in boot["elements"]:
        pid = e["id"]
        if prev_players is not None:
            # Pre-season: jäädytetty acc + per-kierros-minuutit element
            # codella. Ilman artefaktiriviä (uusi PL-tulokas) → nolla-acc →
            # positiopriori dominoi (data_basis=no_history, olemassa oleva
            # mekanismi).
            b = prev_players.get(str(e.get("code")))
            if b is not None:
                acc_by_player[pid] = dict(b["acc"])
                mins_by_round[pid] = {int(k): v for k, v in b["mins_by_round"].items()}
                starts_by_round[pid] = {int(k): int(v) for k, v in b["starts_by_round"].items()}
            else:
                acc_by_player[pid] = xp.accumulate_history([])
                mins_by_round[pid] = {}
                starts_by_round[pid] = {}
            continue
        hist = summaries.get(pid, [])
        acc = xp.accumulate_history(hist)
        acc["dc_hits"] = xp.count_dc_hits(hist, pos_by_player[pid])
        acc_by_player[pid] = acc
        mr: dict[int, float] = defaultdict(float)
        sr: dict[int, int] = defaultdict(int)
        for r in hist:
            if r.get("round") is not None:
                mr[r["round"]] += r.get("minutes", 0) or 0
                sr[r["round"]] += r.get("starts", 0) or 0
        mins_by_round[pid] = dict(mr)
        starts_by_round[pid] = dict(sr)
    priors = xp.position_priors(acc_by_player, pos_by_player)

    # #33: probabilistinen minuuttimalli — kaksi passia:
    #   A) minutes_model + saatavuus-gate per pelaaja
    #   B) syvyys-korjaus klubi+positio-ryhmittäin (Σp_start → historialliset
    #      starttipaikat; availability-nollaama kilpailija nostaa muita capatusti)
    # Pre-season: koko edelliskausi tasapainoin (kuten päättyneen kauden ajo);
    # live-kausi: last-6 recency.
    mm_window = 6 if recency_window else None
    # Kierrosuniversumi on PELAAJAKOHTAINEN, ei kaikkien joukkueiden unioni:
    # blank gameweek ei tuota riviä element-summaryyn, joten unionissa se
    # luettiin penkitykseksi ja painoi p_startin nimittäjää (todennettu
    # 9.8.2026: Haalandilta puuttuivat kierrokset 31 ja 34 = Cityn blankit,
    # Palmerilta 34 = Chelsean blank). Pelaajan omat rivit = hänen joukkueensa
    # pelaamat kierrokset, ja kesken kautta siirtyneellä vain PL-jakso.
    prounds_by_player = {e["id"]: sorted(mins_by_round[e["id"]])
                         for e in boot["elements"]}
    mm_by_player: dict[int, dict] = {}
    for e in boot["elements"]:
        pid = e["id"]
        mm = xp.minutes_model(mins_by_round[pid], starts_by_round[pid],
                              prounds_by_player[pid], n_last=mm_window)
        mm_by_player[pid] = xp.apply_availability(
            mm, e.get("status", "a"), e.get("chance_of_playing_next_round"))
    groups: dict[tuple[int, int], list[int]] = defaultdict(list)
    for e in boot["elements"]:
        groups[(e["team"], e["element_type"])].append(e["id"])
    for (_team, _pos), pids in groups.items():
        # slots = ryhmän toteutuneet startit / kierros ikkunassa (itsekonsistentti).
        # Sama blank-korjaus kuin yllä: joukkueen kierrokset = ryhmän pelaajien
        # rivien unioni, muuten nimittäjä sisältäisi pelaamattomat kierrokset ja
        # slots deflatoituisi eri tahtiin kuin p_start.
        team_rounds = sorted({rnd for p in pids for rnd in prounds_by_player[p]})
        window_rounds = (team_rounds if mm_window is None
                         else team_rounds[-mm_window:])
        slots = (sum(starts_by_round[p].get(rnd, 0)
                     for p in pids for rnd in window_rounds)
                 / max(len(window_rounds), 1))
        # Syvyys nojaa RAAKAAN start-shareen (slots samasta datasta → konsistentti)
        f = xp.depth_factor([mm_by_player[p]["p_start_raw"] for p in pids], slots)
        if f != 1.0:
            for p in pids:
                mm_by_player[p] = xp.scale_p_start(mm_by_player[p], f)

    # -----------------------------------------------------------------
    # HINTAPRIORI OHUELLE OTOKSELLE (4.8.2026). Kytketty vasta nyt: se
    # peruutettiin 27.7 ja koodissa (src/models/fpl_xp.py) oli kolme ehtoa
    # ennen uudelleenkytkentaa. Kaikki kolme on nyt mitattu.
    #
    # EHTO 1 — per-positio-validointi. Peruutusmuistiinpano epaili ettei hinta
    # erottele maalivahteja (kaikki 4.0-5.5M). Mitattuna se erottelee: ohuen
    # otoksen Brier w=0 -> paras painolla, GKP 0.0613 -> 0.0503, DEF 0.0474 ->
    # 0.0409, MID 0.0533 -> 0.0452, FWD 0.0678 -> 0.0521. Kaikki paranevat.
    #
    # EHTO 2 — priorin JA syvyysnormalisoinnin yhteisvaikutus. Tama oli koko
    # 27.7. vian syy, ja se on KYTKENTAJARJESTYS eika priori itse. Sama
    # priori, kaksi paikkaa, mitattu paksussa otoksessa (p_start >= 70 %,
    # n=102):
    #     ENNEN syvyys-passia (27.7. tapa): xP-mediaani -3.6 %,
    #        yli 5 % pudonneita 39/102, pahimmat Donnarumma -16.5 %,
    #        Gyokeres -15.0 %, Raya -14.9 %   <- vika toistettu
    #     JALKEEN syvyys-passin (tama):     xP-mediaani +0.00 %,
    #        yli 5 % pudonneita 0/102
    # Mekanismi: ennen passia nostettu varamiehen p_start meni depth_factorin
    # syotteeksi, joka skaalasi koko ryhman alas ja ykkospelaaja absorboi sen.
    # Passin jalkeen priori ei voi enaa siirtaa massaa toiselta pelaajalta.
    #
    # EHTO 3 — regressioportti korkean omistuksen pelaajille. Ensimmaisessa
    # ajossa yksi rikkoi portin: Diop (IPS, 20 % omistus) -7.6 %. Han on
    # hintapersentiililtaan 0.00 eli halvin mahdollinen, ja juuri sille
    # alaryhmalle backtest sanoi ettei priori auta (HALPA + ohut: Brier
    # -1.5 %, baseline oli jo oikeassa). Siksi priori rajataan sinne missa
    # hyoty on MITATTU (persentiili >= 0.30: KESKI +13.8 %, KALLIS +35.0 %).
    # Rajauksen jalkeen: yli 10 % omistettuja 45, yli 5 % pudonneita 0 —
    # itse asiassa koko projektiossa EI YHTAAN yli 5 % pudonnutta.
    #
    # Hinta rajauksesta: uusia projektioon 29 -> 16. Se on tarkoituksellista;
    # halvassa hannassa priori ei tuonut mitattua hyotya.
    # -----------------------------------------------------------------
    PRICE_BLEND_MIN_PCT = 0.30
    price_pct_by_id: dict[int, float] = {}
    for _et in (1, 2, 3, 4):
        _grp = sorted([e for e in boot["elements"] if e["element_type"] == _et],
                      key=lambda e: (e.get("now_cost") or 0, e["id"]))
        for _i, _e in enumerate(_grp):
            price_pct_by_id[_e["id"]] = _i / max(len(_grp) - 1, 1)
    blended_pids: set[int] = set()
    for e in boot["elements"]:
        pid = e["id"]
        mins = acc_by_player[pid].get("mins", 0.0) or 0.0
        # mins == 0 kuuluu historiattomien prioriin (alempana), ei tanne.
        if mins <= 0 or mins >= xp.PRICE_PRIOR_THIN_MINUTES:
            continue
        if price_pct_by_id[pid] < PRICE_BLEND_MIN_PCT:
            continue
        before = mm_by_player[pid]["p_start"]
        mm_by_player[pid] = xp.apply_price_prior(
            mm_by_player[pid], price_pct_by_id[pid], mins)
        if abs(mm_by_player[pid]["p_start"] - before) > 1e-9:
            blended_pids.add(pid)
    print(f"      hintapriori (ohut otos): {len(blended_pids)} pelaajaa — "
          f"paino {xp.PRICE_PRIOR_WEIGHT}, vain persentiili >= "
          f"{PRICE_BLEND_MIN_PCT}, syvyys-passin JALKEEN")

    # -----------------------------------------------------------------
    # RAKENTEELLINEN JOUKKUERAJOITE (5.8.2026) — ks. fpl_xp.TEAM_*_SLOTS.
    #
    # Klubi+positio-passi yllä ei sido, koska sen `slots` tulee samojen
    # pelaajien historiasta. Tämä passi sitoo pelin sääntöön: tasan 1
    # maalivahti + 10 kenttäpelaajaa. Ylibuukattu ryhmä skaalataan alas
    # RAJATTA (tila on mahdoton), alibuukattu vain DEPTH_BOOST_CAP:iin —
    # nousijaklubien 4,71 ei ole sama vika vaan ohuen otoksen hintapriori,
    # eikä sitä korjata kertomalla kaikki kahdella.
    #
    # SIJAINTI: hintapriorin JÄLKEEN (muuten priori siirtäisi massaa
    # normalisoinnin läpi, sama mekanismi kuin 27.7. vika) mutta
    # pelaajaohitusten EDELLÄ (ohitus on tietoinen ihmispäätös ja sen pitää
    # tarkoittaa sitä mitä CSV:ssä lukee — ks. seuraava lohko).
    etype_by_pid = {e["id"]: e["element_type"] for e in boot["elements"]}
    team_pids: dict[int, list[int]] = defaultdict(list)
    for e in boot["elements"]:
        team_pids[e["team"]].append(e["id"])
    struct_before, struct_after, n_scaled = [], [], 0
    for _tid, pids in team_pids.items():
        for slots, is_gk in ((xp.TEAM_GK_SLOTS, True),
                             (xp.TEAM_OUTFIELD_SLOTS, False)):
            grp = [p for p in pids
                   if (etype_by_pid[p] == 1) == is_gk
                   and mm_by_player[p]["p_start_raw"] > 0]
            if not grp:
                continue
            ps = [mm_by_player[p]["p_start_raw"] for p in grp]
            tot = sum(ps)
            if is_gk:
                struct_before.append(tot)
            if tot > slots:
                # Ylibuukattu: naulatut avaajat (raw >= NAILED_PROTECT) ovat
                # koskemattomia — Villen korjaus 5.8: selkea ykkoshyokkaaja ei
                # maksa keskikentan ruuhkasta. Leikkaus kohdistuu p**k:lla vain
                # kiistanalaisiin paikkoihin (jaljelle jaavat slotit).
                prot = [p for p in grp
                        if mm_by_player[p]["p_start_raw"]
                        >= xp.NAILED_PROTECT_P_START]
                rest = [p for p in grp if p not in prot]
                prot_sum = sum(mm_by_player[p]["p_start_raw"] for p in prot)
                if prot_sum >= slots or not rest:
                    # Degeneraatti (naulattuja enemman kuin paikkoja) ->
                    # p**k koko ryhmalle; kaytannossa ei tapahdu.
                    target, cut = grp, slots
                else:
                    target, cut = rest, slots - prot_sum
                cps = [mm_by_player[p]["p_start_raw"] for p in target]
                k = xp.structural_exponent(cps, cut)
                if k > 1.0:
                    n_scaled += 1
                    for p in target:
                        cur = mm_by_player[p]["p_start_raw"]
                        f = (cur ** k) / cur if cur > 0 else 1.0
                        mm_by_player[p] = xp.scale_p_start(mm_by_player[p], f)
            else:
                # Alibuukattu: sama capattu nosto kuin ennen (nousijaklubien
                # ohut otos ei ole sama vika eika sita korjata tassa).
                f = xp.depth_factor(ps, slots)
                if f != 1.0:
                    n_scaled += 1
                    for p in grp:
                        mm_by_player[p] = xp.scale_p_start(mm_by_player[p], f)
            if is_gk:
                struct_after.append(
                    sum(mm_by_player[p]["p_start_raw"] for p in grp))
    if struct_before:
        print(f"      rakenteellinen joukkuerajoite: {n_scaled} ryhmää skaalattu; "
              f"GKP-summa max {max(struct_before):.2f} -> {max(struct_after):.2f} "
              f"(paikkoja {xp.TEAM_GK_SLOTS:.0f})")

    print("[5/6] xP per pelaaja per GW (horisontti + Phase 1b -konteksti)...")
    # Tulevat fixturet per GW mallinimillä
    upcoming = [f for f in src["fixtures"] if f["gameweek"] and not f["finished"]]
    next_gw = min(f["gameweek"] for f in upcoming) if upcoming else None
    if next_gw is None:
        print("VIRHE: ei pelaamattomia fixtureita — ei kirjoiteta.")
        return 1
    horizon = [g for g in range(next_gw, next_gw + HORIZON_GW)]
    lam_avg = neutral_lambda(dc, fixture_teams)

    # Phase 1b -kontekstikerros: nousijat (fixture-joukkueet − edellisen
    # PL-kauden joukkueet) + koti-avaus-buusti + manuaaliset yliajot.
    y = int(SEASON_LABEL[:4])
    prev_key = f"{(y - 1) % 100:02d}{y % 100:02d}"
    prev_matches = lataa_otteludata(["ENG-Premier League"], [prev_key])
    promoted = promoted_teams(set(fixture_teams), set(prev_matches["home_team"]))
    model_fixtures = [{"gameweek": f["gameweek"], "home": map_name(f["home"]),
                       "away": map_name(f["away"])}
                      for f in src["fixtures"] if f["gameweek"]]
    overrides = load_overrides()
    cfg = build_context(promoted, model_fixtures, overrides)
    print(f"      nousijat: {sorted(promoted)} (koti-avaus-buusti "
          f"x{PROMOTED_HOME_OPENER_ATT_BOOST}), yliajoja: {len(overrides)}")
    ctx_notes: list[str] = []
    for f in model_fixtures:
        if f["gameweek"] not in horizon:
            continue
        _, notes = fixture_adjustments(f["home"], f["away"], f["gameweek"], cfg)
        ctx_notes.extend(f"GW{f['gameweek']}: {n}" for n in notes)
    for n in ctx_notes:
        print(f"      konteksti: {n}")

    # fixture_contexts odottaa FPL-muotoisia fixtureita (team_h/team_a-id:t) —
    # rakennetaan kevyt id-avaruus mallinimistä (toimii myös pulselive-lähteellä).
    name_to_fid = {n: i + 1 for i, n in enumerate(fixture_teams)}
    ctx_by_gw: dict[int, dict[int, list[dict]]] = {}
    opp_by_gw: dict[int, dict[int, list[dict]]] = {}
    for g in horizon:
        fxs = []
        for f in upcoming:
            if f["gameweek"] != g:
                continue
            h, a = map_name(f["home"]), map_name(f["away"])
            if h not in name_to_fid or a not in name_to_fid:
                continue
            fxs.append({"team_h": name_to_fid[h], "team_a": name_to_fid[a],
                        "event": g})
            opp_by_gw.setdefault(g, defaultdict(list))
            opp_by_gw[g][name_to_fid[h]].append({"opp": short_name(a), "venue": "H"})
            opp_by_gw[g][name_to_fid[a]].append({"opp": short_name(h), "venue": "A"})
        fid_to_model = {v: k for k, v in name_to_fid.items()}
        ctx_by_gw[g] = fixture_contexts(dc, fxs, fid_to_model, lam_avg, cfg=cfg)

    # FPL-joukkue → mallinimi → fixture-id. Joukkueet joita ei ole tulevan
    # kauden fixtureissa (putoajat) jäävät pois. history_fids = joukkueella on
    # vähintään yksi pelaaja jolla on omaa PL-baseline-historiaa; nousijat
    # katetaan erikseen positiopriorilla (alla) → data_coverage erottelee
    # nämä kaksi (teams_without_player_history vs teams_without_player_data).
    fplteam_to_fid = {}
    for t in boot["teams"]:
        model = map_name(t["name"])
        if model in name_to_fid:
            fplteam_to_fid[t["id"]] = name_to_fid[model]
    history_fids = {
        fplteam_to_fid[e["team"]] for e in boot["elements"]
        if e["team"] in fplteam_to_fid and acc_by_player[e["id"]]["mins"] > 0}

    # -----------------------------------------------------------------
    # Addendum 2, tehtava 1: NOUSIJAPELAAJAT pooliin positiopriorilla.
    #
    # Ongelma: builderi vaati PL-minuuttihistoriaa -> Hull 0 / Coventry 2 /
    # Ipswich 1 pelaajaa poolissa, vaikka joukkuetason malli (promoted
    # baseline: CS% / xG) on olemassa. Ratkaisu: pelaajille joilla EI ole
    # yhtaan PL-minuuttia JA jotka pelaavat nousijaseurassa, minuuttiarvio
    # tehdaan FPL-hinnan mukaisella rooliprioorilla (kalleimmat = todennakoi-
    # simmat aloittajat — dokumentoitu MVP-heuristiikka, ei mallinnettu XI)
    # ja vauhdit tulevat positiopriorista (player_rates nolla-accilla).
    #
    # TEHDAAN VASTA syvyys-passin JALKEEN eika sen syotteena: nain yhdenkaan
    # olemassa olevan (historiallisen) pelaajan luvut eivat muutu — Coventryn
    # 2 ex-PL-pelaajaa saavat tasan samat arvot kuin ennen (diff-verifioitu).
    # Rehellisyysliput seuraavat automaattisesti: data_basis='no_history'
    # (nolla PL-minuuttia) ja minutes_confidence='low' (n_obs=0).
    # -----------------------------------------------------------------
    PROMOTED_PRIOR_SLOTS = {1: 1, 2: 4, 3: 4, 4: 2}   # tyypillinen XI
    # (p_start, p_sub | ei-start) roolitasoittain, hintajarjestyksen mukaan.
    #
    # 4.8.2026 REKALIBROINTI + LAAJENNUS KAIKKIIN SEUROIHIN (Villen GO).
    #
    # Aiemmat tasot 0.72 / 0.30 / 0.08 olivat MVP-heuristiikka. Ne mitattiin
    # 4.8. samalla valintasaannolla jolla ne jaetaan (klubi+positio,
    # hintajarjestys) populaatiossa "ei 24/25 PL-kautta, pelasi 25/26" (n=178,
    # backtest_preseason_price_prior.py -> report_production_tiers):
    #
    #   tier 0 (XI-slotit)     n=33   TOTEUTUNUT 0.47   tuotannossa oli 0.72
    #   tier 1 (2 seuraavaa)   n=38   TOTEUTUNUT 0.21   tuotannossa oli 0.30
    #   tier 2 (loput)        n=107   TOTEUTUNUT 0.17   tuotannossa oli 0.08
    #
    # Eli karkitaso oli 25 pp liian korkea.
    #
    # 🔴 4.8. ILTAPAIVA: YLLA OLEVA SOVITUS TEHTIIN VAARASSA POPULAATIOSSA.
    # Se rajattiin pelaajiin joilla oli vahintaan 6 GW-rivia 25/26:ssa, eli
    # niihin jotka olivat kauden ajan kirjoilla. TUOTANTO soveltaa tasoa
    # JOKAISEEN bootstrapin historiattomaan (n=307, joista 224 ei pelannut
    # minuuttiakaan), joten selviytymissuodatettu sovitus yliarvioi
    # systemaattisesti - pahiten tier 2:ssa jossa on 200 pelaajaa.
    #
    # Mitattu OIKEASSA populaatiossa (pelaamattomat mukana nollana):
    #     tier 0  n= 53   toteutunut 0.377
    #     tier 1  n= 54   toteutunut 0.164
    #     tier 2  n=200   toteutunut 0.096
    #   Brier: vanhat 0.72/0.30/0.08      0.1037
    #          valiversio 0.47/0.18/0.18  0.0861
    #          NAMA 0.38/0.16/0.10        0.0800   (+7.1 % valiversiosta)
    # Tier 1 ja 2 EROAVAT tassa populaatiossa (0.164 vs 0.096) -> kolme tasoa
    # palautetaan; valiversion yhdistaminen oli seurausta samasta suodatuksesta.
    #
    # SEURATYYPIN KERROIN MITATTIIN JA HYLATTIIN. Nousijaseurojen historiattomat
    # toimittavat 9.1 aloitusta/seura kun malli antaa 6.9 (kerroin 1.33),
    # vakiintuneilla 1.22 vs 1.61 (0.75) -> summavaje on TODELLINEN. Mutta
    # kerroin ei paranna ennustetta omassa alaryhmassaan: nousijoilla Brier
    # 0.1210 (kerroin 1.00) -> 0.1206 (1.33), ja optimi on 1.15 eika summan
    # korjaava 1.33. Skaalaus sovittaisi siis summan silmamaaraisesti ja tekisi
    # pelaajakohtaisesta arviosta huonomman. Vaje jaa TUNNETUKSI RAJOITTEEKSI:
    # sen syy on ettei tier-jako anna nousijaseurassa tarpeeksi monelle
    # tier 0:aa, ei se etta yksittaiset tn:t olisivat liian matalia.
    #
    # LAAJENNUS: sama priori kaikkien seurojen historiattomille, ei vain
    # nousijoille. Perustelu on mittaus, ei symmetria: hinta ennustaa
    # aloituksia koko historiattomassa populaatiossa (aloitusosuus laskee
    # monotonisesti 0.45 -> 0.24 -> 0.16 -> 0.09 hintaneljanneksittain,
    # Brier +13.8 % vs sama luku kaikille). Ilman tata liigaan tullut pelaaja
    # saa p_start ~0.10 ja putoaa koko projektiosta: 4.8. livedatassa
    # Tzolis (ARS 6.5M), Munoz (LIV 6.5M) ja N.Jackson (CHE 6.5M) olivat
    # FPL-statukseltaan TERVEITA mutta poissa jokaiselta listalta.
    #
    # 🔴 EI KOSKE OHUTTA OTOSTA (0 < min < 900). Se on eri muutos
    # (apply_price_prior) ja se PERUUTETTIIN 27.7, koska sen vuorovaikutus
    # syvyysnormalisoinnin kanssa pudotti vakiintuneita pelaajia (Raya
    # -26.8 %). Talla laajennuksella ei ole sita mekanismia: priori annetaan
    # syvyys-passin JALKEEN ja vain pelaajille joiden p_start ei ole mallin
    # laskema, joten yhdenkaan historiallisen pelaajan luku ei muutu.
    # apply_price_prior pysyy kytkematta kunnes sen kolme ehtoa on tehty.
    PROMOTED_PRIOR_TIERS = ((0.38, 0.35), (0.16, 0.45), (0.096, 0.20))
    prior_team_ids = {t["id"] for t in boot["teams"]}
    prior_pids: set[int] = set()
    for team_id in sorted(prior_team_ids):
        club = [e for e in boot["elements"] if e["team"] == team_id]
        for etype, slots in PROMOTED_PRIOR_SLOTS.items():
            # Hintajarjestys KOKO positioryhmasta (myos ex-PL-pelaajat
            # kilpailevat paikoista) — vain historiattomat saavat priorin.
            grp = sorted((e for e in club if e["element_type"] == etype),
                         key=lambda e: (-(e.get("now_cost") or 0), e["id"]))
            for rank, e in enumerate(grp):
                if acc_by_player[e["id"]]["mins"] > 0:
                    continue          # oma PL-historia -> mallipolku ennallaan
                tier = 0 if rank < slots else (1 if rank < slots + 2 else 2)
                p_start, p_sub = PROMOTED_PRIOR_TIERS[tier]
                mm_prior = xp.recompute_minutes({
                    "p_start_raw": p_start, "p_start": p_start, "p_sub": p_sub,
                    "e_min_start": xp.START_FALLBACK_MIN,
                    "e_min_sub": xp.SUB_FALLBACK_MIN,
                    "p60_start": xp.P60_GIVEN_START_FALLBACK, "p60_sub": 0.0,
                    "n_obs": 0, "confidence": "low",
                })
                # FPL:n saatavuustieto porttina kuten muillakin (i/s/u/n -> 0).
                mm_by_player[e["id"]] = xp.apply_availability(
                    mm_prior, e.get("status", "a"),
                    e.get("chance_of_playing_next_round"))
                prior_pids.add(e["id"])
    prior_fids = {fplteam_to_fid[e["team"]] for e in boot["elements"]
                  if e["id"] in prior_pids and e["team"] in fplteam_to_fid}
    print(f"      hintapriori (historiattomat): {len(prior_pids)} pelaajaa "
          f"({len(prior_team_ids)} seuraa) — positiopriori x "
          f"hintapohjainen rooliarvio, data_basis=no_history")

    # Pelaajatason minuuttiohitukset — AIVAN VIIMEISENÄ.
    #
    # 🔴 14.8: TÄMÄ LOHKO OLI VÄÄRÄSSÄ PAIKASSA JA OHITUS EI MENNYT PERILLE.
    # Se oli syvyyskorjauksen jälkeen mutta hintapriorin EDELLÄ. Hintapriori
    # yllä kirjoittaa `mm_by_player[e["id"]]` UUSIKSI jokaiselle pelaajalle
    # jolla ei ole PL-minuutteja, joten jokainen ohitus historiattomaan
    # pelaajaan katosi. Vika oli täysin hiljainen ja PAHEMMALLA tavalla kuin
    # gitignore-vika 28.7: loki tulosti "[Overrides] 110: p_start 0.00 -> 0.90"
    # ja lopputiedostoon jäi 0.38 — eli signaali VALEHTELI onnistumisesta.
    # Löytyi kun Coventryn Rushworth-ohitus ei liikuttanut lukua.
    # Alkuperäinen järjestysperustelu pätee yhä: depth_factor skaalaa koko
    # klubi+positio-ryhmää, joten ohitus ennen sitä ei tarkoittaisi sitä mitä
    # CSV:ssä lukee. Nyt sääntö on yksinkertaisempi: ohitus on VIIMEINEN SANA
    # jokaista minuuttipassia vastaan. Portti: test_shipped_overrides_land.
    #
    # Miksi ohituksia on: minuuttimalli käyttää priorina viime kauden
    # minuutteja eikä erota "ei ollut tarpeeksi hyvä" ja "oli myynnissä tai
    # loukkaantunut". Isak: 694 min / 8 avausta 25/26 -> p_start 0.30 -> xP
    # 1.06/GW 9.0M ykköshyökkääjälle. Väliaikainen; hintapriori korvaa.
    player_overrides, _po_warn = load_player_overrides()
    for w in _po_warn:
        # EI HILJAISTA OHITUSTA. Vanhentunut tai rajojen ulkopuolinen rivi
        # tarkoittaa etta tuotannossa on eri luku kuin CSV:ssa lukee, ja se on
        # tasan se tila jonka pitaa nakya ilman etta joku katsoo yhta pelaajaa.
        print(f"::warning::[Overrides] {w}")
        print(f"[Overrides] VAROITUS: {w}")
    # 28.7 SIGNAALI. Ohituslataus on tarkoituksella fail-safe (puuttuva tiedosto
    # -> tyhjä dict, ei kaadu). Se on oikein, MUTTA ilman signaalia se on myös
    # täysin hiljainen: 27.7. korjattu Isak (6.34 -> 18.93) palautui tuotannossa
    # heti takaisin 6.34:ään, koska CSV oli gitignoressa eikä sitä ollut koskaan
    # committoitu -> CI-runnerilla tiedostoa ei ollut olemassa. Mikään ei
    # huutanut: gate meni PASS, ajo onnistui, luku oli vain väärä.
    #
    # Nyt lukumäärä tulostetaan AINA ja se viedään meta.overrides_applied-kenttään,
    # jolloin sama vika näkyy suoraan tuotannon payloadista eikä vaadi että joku
    # sattuu katsomaan yhtä pelaajaa.
    if not player_overrides:
        print("[Overrides] 0 riviä ladattu "
              "(data/fpl_player_overrides.csv puuttuu tai on tyhjä)")
    override_applied: dict[int, dict] = {}
    for pid, ov in player_overrides.items():
        if pid not in mm_by_player:
            print(f"[Overrides] pelaaja {pid} ei ole bootstrapissa — rivi ohitettu")
            continue
        # 🔴 Ehdollinen rivi purkautuu ITSESTAAN kun pelaaja on taas
        # saatavilla (Villen kysymys 16.8: "kun pelaaja palaa pelikuntoon
        # niin xmins yms ymmärtää sen?"). Ilman tätä loukkaantumisen takia
        # laskettu rivi jäisi voimaan paluun jälkeenkin ja ALIARVIOISI
        # pelaajan, eli tekisi peilikuvan siitä viasta jonka se korjasi.
        # Saatavuus luetaan FPL:n omasta syötteestä joka pyörii joka
        # tapauksessa, joten mitään uutta lähdettä ei tarvita.
        if ov.get("until_available"):
            el = next((e for e in boot["elements"] if e["id"] == pid), {})
            chance = el.get("chance_of_playing_next_round")
            back = (el.get("status") == "a"
                    and (chance is None or chance >= 75))
            if back:
                print(f"[Overrides] {pid}: pelaaja on taas saatavilla "
                      f"(status {el.get('status')}, chance {chance}) — "
                      f"ehdollista ohitusta EI sovelleta")
                continue
        override_applied[pid] = ov
        # `p_start` on nyt VALINNAINEN: rivi voi säätää pelkkää maaliuhkaa
        # (xg_mult) koskematta minuutteihin.
        if ov["p_start"] is not None:
            before = mm_by_player[pid]["p_start_raw"]
            mm_by_player[pid] = xp.set_p_start(mm_by_player[pid], ov["p_start"])
            # Kerro jos ohitus söi juuri annetun hintapriorin — se on odotettu ja
            # haluttu, mutta sen on näyttävä lokissa ettei kukaan ihmettele.
            tag = " (kumosi hintapriorin)" if pid in prior_pids else ""
            print(f"[Overrides] {pid}: p_start {before:.2f} -> "
                  f"{ov['p_start']:.2f} "
                  f"(xmins {mm_by_player[pid]['xmins']:.1f}){tag} — "
                  f"{ov['reason'][:60]}")
        if ov["xg_mult"] != 1.0:
            print(f"[Overrides] {pid}: xg_mult x{ov['xg_mult']:.2f} "
                  f"(maaliuhka) — {ov['reason'][:60]}")

    covered_fids = history_fids | prior_fids
    uncovered = sorted(n for n, fid in name_to_fid.items() if fid not in covered_fids)
    no_history_teams = sorted(n for n, fid in name_to_fid.items()
                              if fid not in history_fids)

    # EDGE-sprint addendum 2 (#Garner-bugi 25.7): projektiosta pudonneet
    # FPL-listautuneet pelaajat emitoidaan ERILLISEEN excluded[]-listaan, jotta
    # player card / haku loytaa heidat (aiemmin i-statuksinen pelaaja katosi
    # payloadista kokonaan -> "ei hakutuloksia"). ERILLINEN lista players[]:n
    # RINNALLA = vanhat klientit (jotka iteroivat players[]-listaa xP-arvoilla)
    # eivat nae muutosta lainkaan.
    def _last_season(e: dict):
        """Viime kauden PL-kausisummat jaadytetysta artefaktista (element code
        -avain) tai None. None = pelaajalla EI ole 25/26 PL-kautta (nousija/
        ulkomailta tullut) — Championship-lukuja ei ole eika niita sekoiteta
        PL-lukuihin ilman sarjatason labelia (objektissa on 'league')."""
        row = prev_by_code.get(str(e.get("code"))) or {}
        return row.get("last_season")

    def _identity_row(e: dict, pid: int, pos: int, model_team_name: str,
                      reason: str) -> dict:
        return {
            "id": pid,
            "web_name": e["web_name"],
            "full_name": f"{e.get('first_name', '')} "
                         f"{e.get('second_name', '')}".strip(),
            "team": model_team_name,
            "team_short": short_name(model_team_name),
            "pos": xp.POS_NAME[pos],
            "price": (e.get("now_cost") or 0) / 10.0,
            "owned_pct": float(e.get("selected_by_percent") or 0.0),
            "status": e.get("status", "a"),
            "news": (e.get("news") or "").strip()[:140],
            "chance_next": e.get("chance_of_playing_next_round"),
            "yellows": int(e.get("yellow_cards") or 0),
            "set_pieces": {
                "pens": e.get("penalties_order"),
                "corners": e.get("corners_and_indirect_freekicks_order"),
                "fk": e.get("direct_freekicks_order"),
            },
            # Player cardin historiaosio toimii myos ilman projektiota.
            "last_season": _last_season(e),
            # EI xP/xmins/p_start-arvoja: naille riveille ei ole mallilukuja.
            "in_projection": False,
            "excluded_reason": reason,
        }

    # Joukkuetason maaliuhkakerroin mallinimen mukaan. Vain `found=True` -rivit:
    # nimikirjoitusvirhe on jo raportoitu äänekkäästi ylempänä, eikä sitä saa
    # täällä tulkita hiljaa kertoimeksi jota ei sovelleta mihinkään.
    team_xg_mult = {r["team"]: float(r.get("attack_mult") or 1.0)
                    for r in team_overrides_applied
                    if r.get("found") and float(r.get("attack_mult") or 1.0) != 1.0}
    if team_xg_mult:
        for t, m in sorted(team_xg_mult.items()):
            print(f"      joukkueen maaliuhkakerroin {t}: xg90 ja xa90 x{m:.2f}")

    # 🔴 AVOPELIPAINOTUS (15.8.2026). Joukkuetason maaliuhkakerroin kuvaa
    # AVOPELIN hyokkaysvoimaa: se syntyy siirtoikkunasta, valmentajanvaihdosta
    # ja rungon menetyksesta. Erikoistilannemaali ei skaalaudu sen mukana —
    # kulmasyoton laatu ja pelaajan ilmapeli eivat katoa silla etta seura
    # menetti hyokkaajan.
    #
    # Kertoimen soveltaminen tasaisesti kaikkiin oli siis mis-spesifioitu, ja
    # MITTAUS kertoo kuinka paljon: Malick Thiawin ei-rangaistuspotku-xG:sta
    # 5.90:sta on erikoistilanteista 5.38 eli 91 %. Liigan mediaani on 16 %.
    # Newcastlen ohitus on juuri se rivi joka on aktiivisena, ja Thiaw pelaa
    # siella — 10 % joukkueleikkaus olisi vienyt 10 % myos siita 91 %:sta
    # johon se ei pade.
    #
    # Jonorivi sanoi etta kalibrointiluku olisi "toistaiseksi harkinta, koska
    # set_pieces on tyhja". Se piti paikkansa FPL:n bootstrapista, mutta EI
    # Understatin laukaisutason artefaktista, jossa `spxg` on ollut koko ajan.
    # Nyt luku on mitattu per pelaaja eika arvattu kerran kaikille.
    #
    # SAANTO: efektiivinen kerroin = 1 + (kerroin - 1) * avopeliosuus.
    #   avopeliosuus 1.00 (ei erikoistilanteita) -> koko joukkuevaikutus
    #   avopeliosuus 0.09 (Thiaw)                -> lahes ei vaikutusta
    # Puuttuva laukausdata (uusi pelaaja PL:ssa) -> osuus 1.0 eli ENTINEN
    # kaytos. Muutos ei voi siis heikentaa ketaan jolle dataa ei ole.
    open_play_share = _load_open_play_share()
    if team_xg_mult and open_play_share:
        print(f"      avopeliosuus luettu {len(open_play_share)} pelaajalle "
              f"(joukkuekerroin painotetaan silla)")

    players = []
    excluded = []
    for e in boot["elements"]:
        pid = e["id"]
        fid = fplteam_to_fid.get(e["team"])
        if fid is None:
            continue  # putoaja tulevalta kaudelta
        pos = pos_by_player[pid]
        rates = xp.player_rates(acc_by_player[pid], pos, priors)
        # #33: probabilistinen minuuttimalli (start%×xMins + saatavuus + syvyys)
        # korvaa minutes_form+availability_factor-skalaarin. Pre-season: koko
        # kausi tasapainoin (mm_window=None), live-kausi: last-6 recency.
        mm = mm_by_player[pid]
        xmins, p60, p1_59 = mm["xmins"], mm["p60"], mm["p1_59"]

        model_team_name = [n for n, i in name_to_fid.items() if i == fid][0]

        # MAALIUHKAN OHITUS. Tämä on ainoa paikka jossa "seura tekee vähemmän
        # maaleja" voidaan sanoa: `attack_delta` ei yllä tänne lainkaan, koska
        # `goal_mult` on suhde joukkueen OMAAN keskiarvoon ja kerroin supistuu
        # pois täsmälleen (ks. fpl_team_overrides.py:n docstring, mitattu 14.8).
        #
        # Järjestys: joukkuekerroin ensin, pelaajakerroin sen päälle. Ne ovat
        # eri väitteitä eivätkä vaihtoehtoja — "koko seura tekee vähemmän" ja
        # "tältä pelaajalta katosi kulmasyöttö" voivat molemmat päteä.
        t_mult = team_xg_mult.get(model_team_name, 1.0)
        p_mult = (override_applied.get(pid) or {}).get("xg_mult", 1.0)
        if t_mult != 1.0:
            # Seuran maalimäärän lasku laskee syöttöjä identiteetin nojalla:
            # jokaisella maalilla on korkeintaan yksi syöttö.
            #
            # xg90 painotetaan pelaajan AVOPELIOSUUDELLA (ks. ylla). xa90 EI
            # painoteta: meilla on laukaustason erikoistilannedata (`spxg`)
            # muttei syottotason vastinetta, joten kulmasyottajan xA:n
            # painottaminen laukausosuudella olisi luvun soveltamista asiaan
            # jota se ei mittaa. Taysi joukkuevaikutus on siella
            # konservatiivisempi valinta kuin keksitty osuus.
            share = open_play_share.get(_shot_key(e), 1.0)
            eff = effective_team_mult(t_mult, share)
            rates = dict(rates, xg90=rates["xg90"] * eff,
                         xa90=rates["xa90"] * t_mult)
        if p_mult != 1.0:
            # Pelaajakerroin EI koske xa90:tä: yksittäisen pelaajan syötöt
            # eivät ole sama asia kuin hänen maalintekonsa.
            rates = dict(rates, xg90=rates["xg90"] * p_mult)
        gws = []
        total = 0.0
        # #3 OSA A: komponenttierittely headline-GW:lle (next_gw). Kertyy
        # TÄSMÄLLEEN samoista xp_components-dicteistä joista totalit lasketaan
        # → pelkkä emittointi, ei laskennan muutosta (xp-arvot identtiset).
        headline_comps: dict[str, float] = {}
        # Vauhti (xP/90) = mitä pelaaja tekisi TÄYSILLÄ 90 minuutilla, keskiarvo
        # horisontin fixtureista. Lasketaan TÄSSÄ eikä serve-timessa, koska
        # p60/p1_59 eivät ole tarjoillulla rivillä eikä lukua siksi voi johtaa
        # (xp_per_gw, xmins) -parista — se yritys tuotti käänteisen sarakkeen
        # matalan minuutin pelaajille. Keskiarvo per FIXTURE eikä per GW: per-90
        # on ottelukohtainen luku, joten tupla-GW ei saa painaa tuplasti.
        full90_sum, full90_n = 0.0, 0
        for g in horizon:
            ctxs = ctx_by_gw.get(g, {}).get(fid, [])
            opps = opp_by_gw.get(g, {}).get(fid, [])
            # Phase 1b: minuuttikerroin (MM-väsymys yms.) per joukkue/GW
            # + #33: tupla-GW-ruuhka → pieni rotaatioriski kärkipelaajille
            mult = (xmins_multiplier(model_team_name, g, cfg)
                    * xp.congestion_multiplier(len(ctxs), xmins))
            xm_g = min(xmins * mult, 90.0)
            p60_g, p1_g = min(p60 * mult, 1.0), min(p1_59 * mult, 1.0)
            gw_xp = 0.0
            for c in ctxs:
                comp = xp.xp_components(pos, rates, xm_g, p60_g, p1_g, c)
                gw_xp += comp["total"]
                # Sama ctx, samat rates, vain minuutit täysinä. Ei rotaatio-
                # kerrointa (`mult`): se on minuuttiodotuksen korjaus, eikä
                # kysymys "jos hän pelaa 90" sisällä sitä.
                full90_sum += xp.xp_full_90(pos, rates, c)
                full90_n += 1
                if g == next_gw:
                    for k, v in comp.items():
                        if k != "total":
                            headline_comps[k] = headline_comps.get(k, 0.0) + v
            total += gw_xp
            gws.append({
                "gw": g,
                "opponents": opps,   # [] = blank GW
                "xp": round(gw_xp, 2),
            })
        if total < MIN_XP_TOTAL:
            # Rehellinen syy: FPL:n virallinen saatavuuslippu (i/s/u/n) vs
            # pelkka kuollut paino (syvalla penkilla / ei minuutteja odotossa).
            reason = ("unavailable" if e.get("status", "a") in ("i", "s", "u", "n")
                      else "below_min_xp")
            excluded.append(_identity_row(e, pid, pos, model_team_name, reason))
            continue
        # Promptin kenttänimet (def_contribution -> defensive_contribution,
        # cards -> yellows). Emitoidaan vain jos headline-GW:llä oli fixture.
        components = None
        if headline_comps:
            key_map = {"def_contribution": "defensive_contribution",
                       "cards": "yellows"}
            components = {key_map.get(k, k): round(v, 2)
                          for k, v in headline_comps.items()}
        # EDGE-sprint (datakerros): minuuttijakauma kolmeen tilaan SAMASTA
        # minuuttimallista josta predicted_starts tulee (kalibroitu p_start,
        # saatavuus- ja syvyyskorjattu). Summa = 1.0 rakenteellisesti ennen
        # pyöristystä: p_cameo = (1-p_start)*p_sub, p_bench = loppu.
        p_start_e = mm["p_start"]
        p_cameo_e = (1.0 - p_start_e) * mm["p_sub"]
        p_bench_e = max(1.0 - p_start_e - p_cameo_e, 0.0)
        player_row = {
            "id": pid,
            "web_name": e["web_name"],
            # #147: koko nimi VAIN hakua varten (näyttönimi pysyy web_namena;
            # "van dijk" ei löytynyt koska web_name = "Virgil").
            "full_name": f"{e.get('first_name', '')} {e.get('second_name', '')}".strip(),
            "team": model_team_name,
            "team_short": short_name(model_team_name),
            "pos": xp.POS_NAME[pos],
            "xmins": round(xmins, 1),
            # #33: probabilistinen kokoonpanoennuste + rehellinen epävarmuus
            "predicted_starts": round(mm["p_start"] * 100.0, 1),
            "minutes_confidence": mm["confidence"],
            # 27.7 REHELLISYYSLIPPU: kun minuutit on ohitettu käsin, se SANOTAAN
            # — sekä koneluettavasti että käyttäjälle näytettävänä perusteluna.
            # Käsin korotettu projektio jota ei merkitä on täsmälleen se asia
            # joka syö "todennettava malli" -lupauksen. Kentät puuttuvat kun
            # ohitusta ei ole (defensiivinen kaikilla pinnoilla).
            **(
                {
                    "minutes_source": "override",
                    "minutes_override_reason": override_applied[pid]["reason"],
                }
                if pid in override_applied
                else {
                    # 4.8: sama rehellisyyslippu hintapriorille. Naiden
                    # pelaajien aloitus-tn EI ole mallin laskema vaan
                    # hintajarjestykseen perustuva rooliarvio, ja kortti
                    # nayttaa luvun isolla. Ilman lippua UI ei voi erottaa
                    # sita mallin omasta arviosta.
                    "minutes_source": "price_prior",
                    "minutes_override_reason":
                        "no Premier League minutes yet, expected role estimated "
                        "from where the player is priced in his club's squad",
                }
                if pid in prior_pids
                else {
                    # Sama rehellisyyslippu ohuelle otokselle: neljasosa
                    # aloitus-tn:sta tulee hinnasta eika pelaajan omista
                    # minuuteista, joten "based on the player's own PL
                    # minutes" ei enaa pida taysin paikkaansa.
                    "minutes_source": "price_blend",
                    "minutes_override_reason":
                        "thin Premier League sample, the expected role is part "
                        "model and part where the player is priced",
                }
                if pid in blended_pids
                else {}
            ),
            # #143: rehellisyyslippu — paljonko pelaajan omaa PL-dataa
            # estimaatin takana on (puhdas emissio, ei muuta xP-lukuja).
            "data_basis": xp.data_basis(acc_by_player[pid]),
            # EDGE: omistus-% bootstrapista (sama konventio kuin price watch /
            # leaders: selected_by_percent on merkkijono -> float).
            "owned_pct": float(e.get("selected_by_percent") or 0.0),
            # UX-palaute-erä (25.7): FPL:n VIRALLINEN saatavuus/kurinpitotieto
            # sellaisenaan bootstrapista (player cardin "official"-osio).
            # status: a=pelattavissa, d=epävarma, i=loukkaantunut,
            # s=pelikiellossa, u=poissa käytöstä, n=ei saatavilla.
            # news typistetään ~140 merkkiin (payload-koko; FPL:n tekstit
            # ovat käytännössä lyhyempiä). chance_next = FPL:n oma
            # chance_of_playing_next_round (int % tai null).
            "status": e.get("status", "a"),
            "news": (e.get("news") or "").strip()[:140],
            "chance_next": e.get("chance_of_playing_next_round"),
            # yellows = kuluvan kauden keltaiset bootstrapista (pre-season
            # = 0 kaikilla, kertyy kauden edetessä). Suspensiokynnykset
            # (5/10/15) ovat UI-copyä, ei tässä.
            "yellows": int(e.get("yellow_cards") or 0),
            # UX-palaute-erä: hinta puuttui xp-payloadista kokonaan, mutta
            # player card + pickerit tarvitsevat sen (CSV-endpoint lukee jo
            # saman now_costin bootstrapista). now_cost on kymmenesosia.
            "price": (e.get("now_cost") or 0) / 10.0,
            # Addendum 2 (player card): viime kauden PL-kausisummat
            # jäädytetystä 25/26-artefaktista. null = ei PL-kautta 25/26
            # (nousijapelaaja / ulkomailta tullut) — sarjatasoa EI sekoiteta.
            "last_season": _last_season(e),
            # EDGE: minuuttijakauma (ks. p_start_e-kommentti yllä).
            # p_start on sama kalibroitu tn kuin predicted_starts/100.
            "p_start": round(p_start_e, 4),
            "p_cameo": round(p_cameo_e, 4),
            "p_bench": round(p_bench_e, 4),
            # EDGE: erikoistilannevastuut FPL-bootstrapista sellaisenaan
            # (int = järjestys listalla, null = ei listalla).
            "set_pieces": {
                "pens": e.get("penalties_order"),
                "corners": e.get("corners_and_indirect_freekicks_order"),
                "fk": e.get("direct_freekicks_order"),
            },
            # EDGE: odotettu bonus / ottelu — KARKEA PROXY, ei simuloitu
            # BPS-jako: shrinkattu bonus90-vauhti * (xmins/90), cap 3.0.
            # Sama kaava kuin xP:n bonus-komponentti neutraalille fixturelle;
            # bonushistoria on 26/27-BPS-oikaistu (#151).
            "e_bonus": round(min(rates["bonus90"] * xmins / 90.0, 3.0), 2),
            "xp_per_gw": round(total / max(len(horizon), 1), 2),
            # None kun horisontissa ei ole yhtään fixturea (blank) — ei 0.0,
            # joka lukisi "ei tuota pisteitä".
            "xp_per_90": (round(full90_sum / full90_n, 2) if full90_n else None),
            "xp_horizon_total": round(total, 2),
            "gameweeks": gws,
        }
        if pid in prior_pids:
            # Rehellisyyslippu VAIN naille riveille (vanhat rivit ennallaan):
            # minuutit eivat tule minuuttimallista vaan roolipriorista.
            player_row["minutes_method"] = "promoted_price_prior"
        if components is not None:
            player_row["components"] = components
            player_row["components_gw"] = next_gw
        players.append(player_row)
    players.sort(key=lambda p: -p["xp_horizon_total"])
    excluded.sort(key=lambda p: (-p["owned_pct"], p["web_name"]))
    n_unavail = sum(1 for p in excluded if p["excluded_reason"] == "unavailable")
    print(f"      {len(players)} pelaajaa (xP >= {MIN_XP_TOTAL} horisontissa), "
          f"GW{next_gw}-{horizon[-1]}")
    print(f"      {len(excluded)} excluded-rivia hakua varten "
          f"({n_unavail} saatavuuslipulla, "
          f"{len(excluded) - n_unavail} alle xP-kynnyksen)")

    coverable = {n for n, fid in name_to_fid.items() if fid in covered_fids}
    gate_points = None
    if prev_players is not None:
        gate_points = {
            e["id"]: prev_players.get(str(e.get("code")), {}).get("total_points", 0)
            for e in boot["elements"]}
    if not sanity_gate(players, boot, coverable, points_by_id=gate_points):
        print("SANITY-GATE FAIL — data/fpl_xp_projections.json EI kirjoitettu.")
        return 2

    print("\n[6/6] Kirjoitetaan JSON...")
    todo = []
    if src["source"] != "fpl-api":
        todo.append(
            "TODO(season rollover): the FPL API does not serve 2026/27 yet, "
            "so fixtures come from the pulselive fallback and player baselines "
            "are the whole 2025/26 season, with transfers unknown. Re-run once "
            "the FPL game opens."
        )
    if uncovered:
        todo.append(
            f"No player data yet (promoted sides, not in FPL yet): {uncovered}. "
            "These fill in automatically once the 2026/27 game opens."
        )
    if prior_pids:
        todo.append(
            f"{len(prior_pids)} promoted-club players are on a position prior "
            f"with no Premier League history: {no_history_teams}. Roles come "
            "from price order, and they sharpen as 2026/27 gameweeks are "
            "played."
        )
    tc_meta = attach_team_confidence(players)
    n_short = attach_minutes_basis_flag(players)
    print(f"      minuuttipriorin lippu: {n_short}/{len(players)} rivia nojaa "
          f"alle {SHORT_SEASON_MINUTES} minuutin kauteen")
    out = {
        "meta": {
            "product": "GoalIQ Fantasy Phase 1: expected points (xP)",
            "available": True,
            "team_confidence": tc_meta,
            "phase": 1,
            "generated_at": _dt.datetime.now().isoformat(timespec="seconds"),
            "season": SEASON_LABEL,
            # 28.7: ohitusten määrä payloadiin, jotta niiden katoaminen näkyy
            # TUOTANNOSTA eikä vaadi että joku sattuu katsomaan yhtä pelaajaa.
            # Vrt. Isak-regressio: CSV oli gitignoressa -> CI ajoi 0 ohituksella
            # -> luku putosi 18.93 -> 6.34 eikä yksikään portti huutanut.
            "overrides_applied": len(override_applied),
            "fixture_source": src["source_label"],
            "player_source": (
                "FPL official API bootstrap (26/27) + frozen 25/26 "
                "baseline artifact (data/fpl_prev_baselines_2526.json, "
                "element code mapping)" if preseason
                else "FPL official API (bootstrap + element-summary history)"),
            "team_strength_source": (
                f"GoalIQ Dixon-Coles, Understat PL {seasons} "
                "(sama fit-config kuin /api/predict)"
            ),
            # 14.8: kasin tehdyt joukkuevoiman ohitukset NAKYVIIN dataan asti.
            # Sama peruste kuin `overrides_applied`illa: Isak-regressiossa CSV
            # oli gitignoressa, CI ajoi 0 ohituksella ja luku putosi
            # 18,93 -> 6,34 eika yksikaan portti huutanut. Joukkueohitus
            # liikuttaa koko seuran kerralla, joten se on nakyva tai se on
            # nakymaton virhe.
            "team_overrides": [
                {k: r[k] for k in ("team", "found", "attack_delta",
                                   "defence_delta", "review_by", "reason")}
                for r in team_overrides_applied
            ],
            "method": (
                "xP = appearance + goals + assists + clean sheets + goals "
                "conceded + saves + defensive contribution + bonus proxy - "
                "cards; formula in src/models/fpl_xp.py, validated with a "
                "walk-forward backtest on 2025/26 (scripts/backtest_fpl_xp.py)"
            ),
            # #151: bonus-proxyn historia oikaistu 26/27 BPS-sääntöihin
            # (CBI 1/3, pilkkutorjunta 7; premierleague.com news/4679946).
            "bps_rules": ("legacy 25/26 (vertailuajo)" if args.legacy_bps
                          else "2026/27 recalibrated (#151)"),
            "caveat": (
                "Pre-season: player baselines come from last season's FPL "
                "history, and the minutes estimate comes from end-of-season "
                "rotation plus FPL availability. It sharpens automatically as "
                "2026/27 gameweeks are played."
            ),
            "promoted_baseline_teams": missing,
            "promoted_baseline_values": baseline,
            # #143: rakenteinen katvealueraportti — sama tieto joka tähän asti
            # oli vain proosana todo-listassa, nyt UI:n luettavissa.
            "data_coverage": {
                "baseline_season": prev_key,
                "baseline_mode": ("prev_season_archive" if preseason
                                  else "live_history"),
                "transfers_known": src["source"] == "fpl-api",
                "teams_without_player_data": uncovered,
                # Addendum 2: erottelu "ei dataa lainkaan" (yllä, nyt tyhjä)
                # vs "ei omaa PL-historiaa, arvio = positiopriori" (alla).
                # Nousijaseurat ovat poolissa mutta EIVÄT historian varassa.
                "teams_without_player_history": no_history_teams,
                "promoted_prior_players": len(prior_pids),
                "promoted_prior_method": (
                    "Promoted-club players with no Premier League minutes: "
                    "minutes come from a role prior built on FPL price order "
                    "(XI slots 1/4/4/2 per position; top p_start 0.72, next two "
                    "0.30, rest 0.08) times the FPL availability gate. Rates "
                    "come from a position prior. "
                    "data_basis=no_history, minutes_confidence=low, "
                    "minutes_method=promoted_price_prior."),
                "player_basis_counts": {
                    v: sum(1 for p in players if p["data_basis"] == v)
                    for v in xp.DATA_BASIS_VALUES
                },
                "basis_threshold_minutes": xp.M_PRIOR_ATTACK,
                "note": (
                    "data_basis per player: pl_history = the player's own "
                    "Premier League history carries at least 50% of the weight; "
                    "limited_history = thin sample, the position prior "
                    "dominates; no_history = no Premier League minutes. "
                    "transfers_known=false means the pre-season bootstrap is "
                    "last season's, so summer transfers are not visible."
                ),
            },
            "context_layer": {
                "promoted_teams": sorted(promoted),
                "promoted_home_opener_att_boost": PROMOTED_HOME_OPENER_ATT_BOOST,
                "manual_overrides": len(overrides),
                "applied_in_horizon": ctx_notes,
                "note": ("Phase 1b: promoted-side home opener attack boost, "
                         "manual overrides (data/fpl_manual_overrides.csv) and "
                         "World Cup fatigue factors"),
            },
            "sanity_gate": "PASS",
            "next_gameweek": next_gw,
            "deadline_utc": src["deadline_utc"],
            "horizon_gw": HORIZON_GW,
            "min_xp_total": MIN_XP_TOTAL,
            "n_players": len(players),
            "n_excluded": len(excluded),
            # Addendum 2: excluded[] on HAKUA/player cardia varten, ei
            # rankkauslista. Rivit kantavat vain FPL:n virallisen tiedon
            # (status/news/hinta/EO/erikoistilanteet) — EI mallilukuja.
            "excluded_note": (
                "excluded[] lists FPL players who are not in the projection "
                "(availability flag i/s/u/n, or horizon xP below "
                f"{MIN_XP_TOTAL}). The rows exist for search and the player "
                "card: in_projection=false, with no xP/xmins/p_start fields. "
                "Older clients can ignore the list."),
            "todo": todo,
        },
        "players": players,
        "excluded": excluded,
    }
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    size_kb = OUT_PATH.stat().st_size / 1024
    print(f"      -> {OUT_PATH}  ({len(players)} pelaajaa, {size_kb:.0f} kB)")

    print("\nEI auto-pushia. Deploy Renderiin (Villen vahvistus):")
    print("  git add data/fpl_xp_projections.json")
    print('  git commit -m "data(fpl): Phase 1 xP refresh"')
    print("  git push")
    return 0


if __name__ == "__main__":
    sys.exit(main())
