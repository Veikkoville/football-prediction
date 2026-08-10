"""FPL Phase 1 xP — walk-forward-backtest valmiilla 25/26-kaudella (SHIP-GATE).

Laskee xP:n jokaiselle kauden GW:lle käyttäen VAIN GW:tä edeltävää dataa:
  - pelaajavauhdit: FPL-API:n per-GW-historia kierroksilta < GW
  - joukkuekonteksti: Dixon-Coles sovitettuna otteluihin joiden päivä < GW:n
    ensimmäinen kickoff (sama fit-config kuin tuotannon /api/predict)
ja vertaa toteutuneisiin FPL-pisteisiin.

Baseline: FPL:n historiallista ep_next:iä EI ole saatavilla (kenttä on
live-only, API ei arkistoi sitä) → promptin mukainen fallback = form-baseline
(viimeisten 5 joukkuekierroksen pistekeskiarvo). Tämä on sama signaali josta
FPL:n oma "form"/ep_next johdetaan.

🔒 SHIP-GATE: xP:n MAE pienempi JA Spearman korkeampi kuin baseline
(vähintään toinen selkeästi parempi, ei kumpikaan huonompi) pelanneiden
populaatiossa GW2-38. Tulos + per-positio-erittely raportoidaan; FAIL →
xP:tä EI julkaista.

Datalähde valitaan AUTOMAATTISESTI: jos elävässä FPL-API:ssa ei ole päättynyttä
kautta (kausiflippi), ajo putoaa levyarkistoon 25/26. DC:n treenikaudet
johdetaan backtestattavasta kaudesta, EI kalenterista.

Ajo:  python -m scripts.backtest_fpl_xp          (välimuisti data/raw/fpl/)
      python -m scripts.backtest_fpl_xp --refresh  (pakota FPL-haku uusiksi)
Raportti: logs/fpl_xp_backtest_<pvm>.json (gitignored) + stdout-taulukko.
"""
from __future__ import annotations

import argparse
import csv
import datetime as _dt
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
from scipy.stats import spearmanr

import config
from scripts.build_fpl_phase0 import FIT_BAYES, FIT_DECAY, add_promoted_baseline, map_name
from src.data import fpl_api
from src.data.loader import lataa_otteludata
from src.models import fpl_xp as xp
from src.models.dixon_coles import DixonColesModel
from src.models.fpl_context import build_context, fixture_contexts, neutral_lambda, promoted_teams

FORM_WINDOW = 5          # baseline: viim. 5 joukkuekierroksen pistekeskiarvo
GW_FIRST_EVAL = 2        # GW1:lle ei ole kummallakaan menetelmällä dataa
LATE_SEASON_FROM = 7     # lisäraportti: vakiintunut kausi (molemmilla >=6 GW dataa)

# Minuuttipolku: sama kuin tuotanto-builderin live-kausi-asetus
# (build_fpl_xp.py: mm_window = 6). Ks. MINUTES_CAVEAT.
MM_WINDOW = 6

# Kausi on "päättynyt" vasta kun lähes kaikki ottelut on pelattu. Alle tämän
# elävä API ei kelpaa walk-forward-backtestiin → arkisto.
FULL_SEASON_MIN_FINISHED = 300

MINUTES_CAVEAT = (
    "minutes_model (tuotannon polku, n_last=6, pelaajakohtaiset kierrokset). "
    "EI sisällä builderin live-kerroksia: apply_availability (FPL:n "
    "saatavuuslippu) ja klubi+positio-syvyyskorjaus — kumpaakaan ei ole "
    "historiallisena. Gate mittaa siis minuuttimallin, ei koko builderia."
)


def seasons_for(season_key: str) -> list[str]:
    """[edellinen, backtestattava] kausi DC-fittiä varten.

    MIKSI EI config.current_season_pair(): se seuraa kalenteria, joten
    kausiflipin jälkeen se palautti ['2526','2627'] vaikka backtest ajaa
    25/26:tta. 26/27:ssa ei ole vielä yhtään ottelua, joten
      - DC-fit menetti KOKO edelliskauden (GW2:n fitissä oli 10 ottelua),
      - nousijalista tyhjeni (cur − prev = ∅) → kontekstikerroksen
        nousijakäsittely ja kaikki vs_promoted-slicet kuolivat HILJAA.
    Backtestin kausi ratkaisee treeni-ikkunan, ei tämän päivän päivämäärä.
    """
    start = int(season_key[:2])
    return [f"{(start - 1) % 100:02d}{start:02d}", season_key]


# ---------------------------------------------------------------------------
# Datarakenteet
# ---------------------------------------------------------------------------
def build_structures(boot: dict, fixtures: list, summaries: dict[int, list[dict]]):
    tid_to_model = {t["id"]: map_name(t["name"]) for t in boot["teams"]}
    pos_by_player = {e["id"]: e["element_type"] for e in boot["elements"]}
    team_by_player = {e["id"]: e["team"] for e in boot["elements"]}
    name_by_player = {e["id"]: e["web_name"] for e in boot["elements"]}

    fixtures_by_event: dict[int, list[dict]] = defaultdict(list)
    team_rounds: dict[int, list[int]] = defaultdict(list)
    for f in fixtures:
        ev = f.get("event")
        if ev is None:
            continue
        fixtures_by_event[ev].append(f)
        for tid in (f["team_h"], f["team_a"]):
            if ev not in team_rounds[tid]:
                team_rounds[tid].append(ev)
    for tid in team_rounds:
        team_rounds[tid].sort()

    # Per pelaaja: rivit ja minuutit/pisteet kierroksittain
    rows_by_round: dict[int, dict[int, list[dict]]] = {}
    mins_by_round: dict[int, dict[int, float]] = {}
    pts_by_round: dict[int, dict[int, float]] = {}
    starts_by_round: dict[int, dict[int, int]] = {}
    for pid, hist in summaries.items():
        rr: dict[int, list[dict]] = defaultdict(list)
        for r in hist:
            rnd = r.get("round")
            if rnd is not None:
                rr[rnd].append(r)
        rows_by_round[pid] = dict(rr)
        mins_by_round[pid] = {rnd: sum((x.get("minutes") or 0) for x in rows)
                              for rnd, rows in rr.items()}
        pts_by_round[pid] = {rnd: sum((x.get("total_points") or 0) for x in rows)
                             for rnd, rows in rr.items()}
        # minutes_model tarvitsee startit erikseen (p_start ≠ p(minuutteja)).
        starts_by_round[pid] = {rnd: sum((x.get("starts") or 0) for x in rows)
                                for rnd, rows in rr.items()}
    return (tid_to_model, pos_by_player, team_by_player, name_by_player,
            fixtures_by_event, team_rounds, rows_by_round, mins_by_round,
            pts_by_round, starts_by_round)


# neutral_lambda + fixture_contexts siirretty src/models/fpl_context.py:hyn
# (Phase 1b) — sama koodi backtestissä ja tuotanto-buildereissa.


# ---------------------------------------------------------------------------
# Metriikat
# ---------------------------------------------------------------------------
def mae(pred: list[float], actual: list[float]) -> float:
    return float(np.mean(np.abs(np.array(pred) - np.array(actual))))


def rho(pred: list[float], actual: list[float]) -> float:
    if len(pred) < 3 or len(set(actual)) < 2 or len(set(pred)) < 2:
        return float("nan")
    r = spearmanr(pred, actual).statistic
    return float(r)


# ---------------------------------------------------------------------------
# Backtest
# ---------------------------------------------------------------------------
def _load_archive_2526():
    """25/26-data levyarkistosta (28.7).

    MIKSI: kausiflipin (26/27) jalkeen elava bootstrap + element-summary
    palauttavat tyhjan uuden kauden, jolloin tama ship-gate ajoi lapi
    n=0 pelannutta joka kierroksella ja kaatui aggregointiin. Portti oli siis
    HILJAA ajokelvoton juuri silloin kun malliin tehdaan muutoksia.

    fixtures.json on samoin jo 26/27, joten 25/26:n ottelut rekonstruoidaan
    summary-riveista (jokainen rivi kantaa fixture-id:n, kierroksen,
    vastustajan, koti/vieras-lipun, kickoffin ja molempien maalit).
    """
    boot = json.loads((config.RAW_DATA_DIR / "fpl"
                       / "bootstrap_static_2526.archive.json")
                      .read_text(encoding="utf-8"))
    team_of = {e["id"]: e["team"] for e in boot["elements"]}
    summaries = {}
    sdir = config.RAW_DATA_DIR / "fpl" / "summary_2526"
    for f in sorted(sdir.glob("element_*.json")):
        eid = int(f.stem.split("_")[1])
        summaries[eid] = json.loads(f.read_text(encoding="utf-8"))
    # fetch_all_summaries palauttaa {id: history-lista}, ei koko dokumenttia
    hist_only = {eid: (d.get("history") or []) for eid, d in summaries.items()}
    fx = {}
    for eid, d in summaries.items():
        for r in d.get("history") or []:
            fid = r["fixture"]
            if fid in fx:
                continue
            team = team_of.get(eid)
            if team is None:
                continue
            h, a = (team, r["opponent_team"]) if r["was_home"] else (
                r["opponent_team"], team)
            fx[fid] = {"id": fid, "event": r["round"], "team_h": h, "team_a": a,
                       "kickoff_time": r["kickoff_time"], "finished": True,
                       "team_h_score": r["team_h_score"],
                       "team_a_score": r["team_a_score"]}
    return boot, sorted(fx.values(), key=lambda f: f["id"]), hist_only, "2526"


# ---------------------------------------------------------------------------
# TULOKAS-SLICE (10.8.2026)
#
# MIKSI TAMA EIKA VAIHTUVUUSLUKU: 9.8. shipattu vaihtuvuusluku on JOUKKUETASON
# kuvaileva mitta, ja sen ennustava kaytto kaatui kalibroinnissa (hyokkays
# R^2 0,000, puolustus vaara merkki). Pelaajatasolla kysymys on eri: pelaajan
# omat vauhdit lasketaan HANEN PL-riveistaan, ja tulokkaalla niita ei ole
# yhtaan -> xP nojaa positiopriorin ja hinnan varaan. Onko se oikeasti
# huonompi? Tama slice mittaa sen sen sijaan etta arvattaisiin.
#
# WALK-FORWARD-LAILLINEN: "ei minuutteja EDELLISELLA kaudella" on tiedossa
# ennen kauden alkua eika lue kohde-GW:n dataa.
#
# LIITOS TEHDAAN `code`-KENTALLA. `id` on kausikohtainen ja uudelleenkaytetty
# -> id-liitos osuisi VAARIIN pelaajiin nayttamatta virhetta.
# ---------------------------------------------------------------------------
def _prev_season_key(season_key: str) -> str:
    """'2526' -> '2425'."""
    yy = int(season_key[:2])
    return f"{yy - 1:02d}{yy:02d}"


def _newcomer_by_pid(boot: dict, season_key: str) -> tuple[dict[int, bool], str]:
    """pid -> True jos pelaajalla EI ole PL-minuutteja edelliselta kaudelta.

    Palauttaa ({}, syy) jos edelliskauden arkistoa ei ole — slice jaa pois ja
    syy TULOSTETAAN. Puuttuva arkisto ei saa kaataa ship-gatea, mutta se ei saa
    myoskaan kadota hiljaa: tyhja slice raportissa nayttaa samalta kuin
    "ei loydoksia".
    """
    prev = _prev_season_key(season_key)
    p = config.RAW_DATA_DIR / "fpl" / f"season_{prev}" / "players_raw.csv"
    if not p.exists():
        return {}, f"{p.name} puuttuu kaudelta {prev}"
    played_codes: set[int] = set()
    with p.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            try:
                if float(row.get("minutes") or 0) > 0:
                    played_codes.add(int(row["code"]))
            except (TypeError, ValueError, KeyError):
                continue
    if not played_codes:
        return {}, f"kaudella {prev} nolla pelaajaa minuuteilla"

    out: dict[int, bool] = {}
    n_prev = 0
    for e in boot["elements"]:
        code = e.get("code")
        if code is None:
            continue
        was_there = int(code) in played_codes
        n_prev += was_there
        out[e["id"]] = not was_there
    # Nolla osumaa = code-liitos on rikki (esim. arkiston skeema vaihtui).
    # Silloin JOKAINEN pelaaja nayttaisi tulokkaalta ja slice raportoisi
    # taysin vaaraa lukua taydella itseluottamuksella. Sama vikaluokka jonka
    # cs_table-liitos kaataa (9.8).
    if n_prev == 0:
        raise SystemExit(
            f"tulokas-slice: yksikaan {season_key}-pelaaja ei osunut kauden "
            f"{prev} koodeihin ({len(played_codes)} koodia luettu) — "
            f"code-liitos on rikki, EI 'kaikki ovat tulokkaita'")
    return out, (f"kausi {prev}: {len(played_codes)} pelaajaa minuuteilla, "
                 f"{n_prev}/{len(out)} liitosta")


def run_backtest(force_refresh: bool = False, use_context: bool = True,
                 bps_2627: bool = True, archive: bool = False,
                 show_components: bool = False, live: bool = False,
                 legacy_minutes: bool = False) -> dict:
    print("[1/4] FPL-data (bootstrap + fixtures + 841 element-historiaa)...")
    # Lähteen valinta on AUTOMAATTINEN. Aiemmin arkisto oli lipun takana ja
    # oletusajo osui kausiflipin jälkeen tyhjään 26/27:aan: jokainen kierros
    # sai n=0 pelannutta ja ajo kaatui vasta aggregoinnissa (KeyError:
    # 'mae_xp'). Portti, joka vaatii muistamaan lipun, on portti jota ei ajeta.
    if not archive:
        boot = fpl_api.fetch_bootstrap(force=force_refresh)
        fixtures = fpl_api.fetch_fixtures(force=force_refresh)
        season_key = fpl_api.season_key_from_bootstrap(boot)
        n_finished = sum(1 for f in fixtures if f.get("finished"))
        if n_finished < FULL_SEASON_MIN_FINISHED and not live:
            print(f"      elava kausi {season_key}: vain {n_finished} pelattua "
                  f"ottelua (< {FULL_SEASON_MIN_FINISHED}) — walk-forward "
                  f"vaatii paattyneen kauden")
            archive = True
        else:
            summaries = fpl_api.fetch_all_summaries(boot, force=force_refresh)
    if archive:
        boot, fixtures, summaries, season_key = _load_archive_2526()
        print("      -> LEVYARKISTO 25/26 (paattynyt kausi)")
    print(f"      kausi {season_key}: {len(boot['elements'])} pelaajaa, "
          f"{len(fixtures)} fixturea")
    # #151: sama bonus-oikaisu kuin tuotanto-builderissa — ship-gate mittaa
    # sitä mitä shipataan. Vaikuttaa VAIN vauhteihin (bonus-kenttä); actualit
    # ja form-baseline lasketaan total_points-kentästä, joka ei muutu.
    if bps_2627:
        summaries = xp.adjust_summaries_bps_2627(summaries)
        print("      bonus-historia oikaistu 26/27 BPS-sääntöihin (#151)")
    else:
        print("      HUOM: legacy-BPS (25/26) — vertailuajo")

    (tid_to_model, pos_by_player, team_by_player, name_by_player,
     fixtures_by_event, team_rounds, rows_by_round, mins_by_round,
     pts_by_round, starts_by_round) = build_structures(boot, fixtures, summaries)

    # Pelaajakohtainen kierrosuniversumi = sama kuin tuotanto-builderissa:
    # pelaajan omat rivit, ei joukkueen fixture-listaa. Kesken kautta
    # siirtyneellä tämä on vain hänen PL-jaksonsa.
    prounds_by_player = {pid: sorted(m) for pid, m in mins_by_round.items()}

    newcomer_by_pid, newcomer_src = _newcomer_by_pid(boot, season_key)
    if newcomer_by_pid:
        n_new = sum(1 for v in newcomer_by_pid.values() if v)
        print(f"      tulokas-slice: {n_new}/{len(newcomer_by_pid)} ilman "
              f"edelliskauden PL-minuutteja ({newcomer_src})")
    else:
        print(f"      VAROITUS: tulokas-slice EI aja — {newcomer_src}")

    print("[2/4] PL-otteludata DC-mallia varten (Understat, sama lähde kuin tuotanto)...")
    seasons = seasons_for(season_key)
    matches = lataa_otteludata(["ENG-Premier League"], seasons)
    if matches.empty:
        raise SystemExit("PL-otteludata tyhjä — backtest ei voi ajaa.")
    have = set(matches["season"].astype(str))
    if set(seasons) - have:
        raise SystemExit(
            f"PL-otteludata puuttuu kausilta {sorted(set(seasons) - have)} "
            f"(saatavilla {sorted(have)}). DC-fit jäisi ilman edelliskautta, "
            f"jolloin backtestin alkukierrokset fitataan lähes tyhjällä "
            f"aineistolla ja nousijalista tyhjenee.")
    print(f"      {len(matches)} ottelua (kaudet {seasons})")

    events = sorted(fixtures_by_event)
    fpl_team_names = [tid_to_model[t["id"]] for t in boot["teams"]]

    # Phase 1b -kontekstikerros: nousijat (tämä kausi − edellinen kausi
    # otteludatasta) + ensimmäisen kotipelin GW → koti-avaus-buusti.
    # Walk-forward-laillista (tiedossa ennen kautta). Manuaalisia yliajoja
    # EI ladata backtestissä (ne ovat tulevan kauden inputteja).
    ctx_cfg = None
    promoted: set[str] = set()
    if use_context:
        seasons_str = matches["season"].astype(str)
        cur_s, prev_s = max(seasons_str.unique()), min(seasons_str.unique())
        promoted = promoted_teams(
            set(matches[seasons_str == cur_s]["home_team"]),
            set(matches[seasons_str == prev_s]["home_team"]))
        model_fixtures = [{"gameweek": f.get("event"),
                           "home": tid_to_model.get(f["team_h"]),
                           "away": tid_to_model.get(f["team_a"])}
                          for f in fixtures if f.get("event")]
        ctx_cfg = build_context(promoted, model_fixtures)
        print(f"      kontekstikerros PÄÄLLÄ: nousijat {sorted(promoted)}, "
              f"koti-avaus-buusti")
    else:
        # Slice-raportointi tarvitsee nousijalistan myös raa'assa ajossa
        seasons_str = matches["season"].astype(str)
        cur_s, prev_s = max(seasons_str.unique()), min(seasons_str.unique())
        promoted = promoted_teams(
            set(matches[seasons_str == cur_s]["home_team"]),
            set(matches[seasons_str == prev_s]["home_team"]))
        print("      kontekstikerros POIS (raaka DC, Phase 1 -käyttäytyminen)")

    # PL:ssä nousijoita on aina 3. Tyhjä lista tarkoittaa että treeni-ikkuna on
    # väärä — ja se ei kaada mitään, vaan tappaa hiljaa nousijakäsittelyn ja
    # kaikki vs_promoted-slicet (todettu 9.8.2026: slicet katosivat raportista
    # ilman yhtään virhettä).
    if len(promoted) != 3:
        raise SystemExit(
            f"Nousijoita {len(promoted)} kpl ({sorted(promoted)}), pitäisi olla 3 "
            f"— kaudet {seasons} eivät kelpaa nousijoiden johtamiseen.")

    per_gw: list[dict] = []
    obs_rows: list[dict] = []  # per pelaaja-GW: diagnoosiin + sliceihin

    print(f"[3/4] Walk-forward GW{GW_FIRST_EVAL}-{max(events)} "
          f"(DC-fit per GW, vain edeltävä data)...")
    for g in events:
        if g < GW_FIRST_EVAL:
            continue
        fxs = fixtures_by_event[g]
        kickoffs = [fpl_api.parse_kickoff(f.get("kickoff_time")) for f in fxs]
        kickoffs = [k for k in kickoffs if k]
        if not kickoffs:
            continue
        cutoff = min(kickoffs).replace(tzinfo=None)

        sub = matches[matches["date"] < cutoff]
        dc = DixonColesModel(per_team_home_adv=True).fit(
            sub, home_team_col="home_team", away_team_col="away_team",
            home_goals_col="home_score", away_goals_col="away_score",
            decay=FIT_DECAY, date_col="date", l2_attack_defence=FIT_BAYES)
        missing = sorted(set(fpl_team_names) - set(dc.attack))
        if missing:
            add_promoted_baseline(dc, missing)
        lam_avg = neutral_lambda(dc, fpl_team_names)
        ctx_by_team = fixture_contexts(dc, fxs, tid_to_model, lam_avg, cfg=ctx_cfg)

        # Vastustajat per joukkue-id tälle GW:lle (slice: vs nousija)
        opps_by_tid: dict[int, list[str]] = defaultdict(list)
        for f in fxs:
            h, a = tid_to_model.get(f["team_h"]), tid_to_model.get(f["team_a"])
            if h and a:
                opps_by_tid[f["team_h"]].append(a)
                opps_by_tid[f["team_a"]].append(h)

        # Kumulatiiviset accit + positiopriorit kierroksilta < g
        acc_by_player: dict[int, dict] = {}
        for pid, rr in rows_by_round.items():
            before = [r for rnd, rows in rr.items() if rnd < g for r in rows]
            acc = xp.accumulate_history(before)
            acc["dc_hits"] = xp.count_dc_hits(before, pos_by_player[pid])
            acc_by_player[pid] = acc
        priors = xp.position_priors(acc_by_player, pos_by_player)

        gw_pred_xp, gw_pred_base, gw_actual, gw_played, gw_pos = [], [], [], [], []
        for pid, rr in rows_by_round.items():
            if g not in rr:
                continue  # ei rekisteröitynä tälle GW:lle
            tid = team_by_player[pid]
            ctxs = ctx_by_team.get(tid, [])
            if not ctxs:
                continue
            pos = pos_by_player[pid]
            rates = xp.player_rates(acc_by_player[pid], pos, priors)
            trounds = [r for r in team_rounds[tid] if r < g]
            if legacy_minutes:
                xmins, p60, p1_59 = xp.minutes_form(mins_by_round[pid], trounds)
            else:
                # TUOTANNON POLKU. minutes_form on jäänyt eläkkeelle
                # builderista (#33), joten gate mittasi eri mallia kuin
                # shipataan: 9.8. minuuttipriorin korjaus siirsi Palmerin
                # 43 → 74 min tuotannossa eikä gaten luvuissa muuttunut
                # yksikään desimaali. Walk-forward säilyy: rounds-lista on
                # rajattu kohde-GW:tä edeltäviin.
                prounds = [r for r in prounds_by_player[pid] if r < g]
                mm = xp.minutes_model(mins_by_round[pid], starts_by_round[pid],
                                      prounds, n_last=MM_WINDOW)
                xmins, p60, p1_59 = mm["xmins"], mm["p60"], mm["p1_59"]
            comps = [xp.xp_components(pos, rates, xmins, p60, p1_59, c)
                     for c in ctxs]
            pred = sum(c["total"] for c in comps)
            # Komponenttitason validointi (4.8): maali- ja syottokomponentit
            # ovat PISTEINA, joten yksikko puretaan takaisin kappaleiksi.
            # Nain mitataan tasan se luku joka tuotteessa naytettaisiin.
            eg = sum(c["goals"] for c in comps) / xp.GOAL_PTS[pos]
            ea = sum(c["assists"] for c in comps) / xp.ASSIST_PTS
            raw_rows = rows_by_round[pid][g]
            ag = sum((x.get("goals_scored") or 0) for x in raw_rows)
            aa = sum((x.get("assists") or 0) for x in raw_rows)

            form_rounds = trounds[-FORM_WINDOW:]
            base = (float(np.mean([pts_by_round[pid].get(r, 0.0) for r in form_rounds]))
                    if form_rounds else 0.0)
            # DGW: baseline on per kierros -> skaalaa fixtureiden määrällä
            base *= len(ctxs)

            actual = pts_by_round[pid][g]
            played = mins_by_round[pid][g] > 0
            gw_pred_xp.append(pred)
            gw_pred_base.append(base)
            gw_actual.append(actual)
            gw_played.append(played)
            gw_pos.append(pos)
            obs_rows.append({"gw": g, "pid": pid, "pos": pos, "pred": pred,
                             "eg": eg, "ea": ea, "ag": ag, "aa": aa,
                             "base": base, "actual": actual, "played": played,
                             "newcomer": newcomer_by_pid.get(pid),
                             "xmins": xmins,
                             "amins": mins_by_round[pid][g],
                             # Hinta TALLA kierroksella (tiedossa ennen
                             # kickoffia -> ei vuoda). Erottaa oikean
                             # hankinnan akatemiapelaajasta ilman etta
                             # valitaan kauden lopputuloksen perusteella.
                             "price": max((x.get("value") or 0)
                                          for x in raw_rows) / 10.0,
                             "vs_promoted": any(o in promoted
                                                for o in opps_by_tid.get(tid, ()))})

        idx_played = [i for i, p in enumerate(gw_played) if p]
        entry = {"gw": g, "n_all": len(gw_actual), "n_played": len(idx_played)}
        for tag, idx in (("all", range(len(gw_actual))), ("played", idx_played)):
            xs = [gw_pred_xp[i] for i in idx]
            bs = [gw_pred_base[i] for i in idx]
            ys = [gw_actual[i] for i in idx]
            if len(ys) >= 3:
                entry[f"{tag}_mae_xp"] = mae(xs, ys)
                entry[f"{tag}_mae_base"] = mae(bs, ys)
                entry[f"{tag}_rho_xp"] = rho(xs, ys)
                entry[f"{tag}_rho_base"] = rho(bs, ys)
        per_gw.append(entry)
        if g % 5 == 0 or g == max(events):
            print(f"      GW{g}: n={entry['n_played']} pelannutta, "
                  f"MAE xp={entry.get('played_mae_xp', float('nan')):.3f} "
                  f"base={entry.get('played_mae_base', float('nan')):.3f}")

    print("[4/4] Aggregointi + ship-gate...")
    # Backstop: ilman tätä tyhjä populaatio eteni aggregointiin ja kaatui
    # sinne KeyErroriin, joka ei kerro syytä. Portin pitää sanoa MIKSI se ei
    # voinut ajaa.
    n_played_total = sum(e["n_played"] for e in per_gw)
    if n_played_total == 0:
        raise SystemExit(
            f"Kaudella {season_key} ei ole yhtään pelattua pelaaja-kierrosta "
            f"({len(per_gw)} kierrosta läpi). Ship-gate ei ajanut. "
            f"Yleisin syy: kausiflippi — elävä FPL-API tarjoaa uutta kautta, "
            f"jossa ei ole vielä historiaa. Aja ilman --live (auto-arkisto).")
    res = aggregate_and_gate(per_gw, obs_rows, season_key,
                             use_context=use_context, bps_2627=bps_2627,
                             seasons=seasons, legacy_minutes=legacy_minutes)
    report_newcomer(obs_rows)
    if show_components:
        report_components(obs_rows)
    return res


def _agg(per_gw: list[dict], tag: str, gw_from: int, gw_to: int) -> dict:
    sel = [e for e in per_gw if gw_from <= e["gw"] <= gw_to and f"{tag}_mae_xp" in e]
    if not sel:
        return {}
    def m(key):
        vals = [e[key] for e in sel if not np.isnan(e[key])]
        return float(np.mean(vals)) if vals else float("nan")
    return {
        "gw_range": f"{gw_from}-{gw_to}", "n_gws": len(sel),
        "mae_xp": m(f"{tag}_mae_xp"), "mae_base": m(f"{tag}_mae_base"),
        "rho_xp": m(f"{tag}_rho_xp"), "rho_base": m(f"{tag}_rho_base"),
    }


def _slice_stats(obs: list[dict]) -> dict:
    """MAE/rho + signed bias (pred − actual) molemmille malleille."""
    if len(obs) < 10:
        return {"n": len(obs)}
    preds = [o["pred"] for o in obs]
    bases = [o["base"] for o in obs]
    ys = [o["actual"] for o in obs]
    return {
        "n": len(obs),
        "mae_xp": mae(preds, ys), "mae_base": mae(bases, ys),
        "rho_xp": rho(preds, ys), "rho_base": rho(bases, ys),
        "bias_xp": float(np.mean(np.array(preds) - np.array(ys))),
        "bias_base": float(np.mean(np.array(bases) - np.array(ys))),
    }


def aggregate_and_gate(per_gw: list[dict], obs_rows: list[dict],
                       season_key: str, use_context: bool = True,
                       bps_2627: bool = True, seasons: list[str] | None = None,
                       legacy_minutes: bool = False) -> dict:
    bps_rules = ("2026/27 recalibrated (#151)" if bps_2627
                 else "legacy 25/26 (vertailuajo)")
    gw_max = max(e["gw"] for e in per_gw)
    agg = {
        "played_full": _agg(per_gw, "played", GW_FIRST_EVAL, gw_max),
        "played_late": _agg(per_gw, "played", LATE_SEASON_FROM, gw_max),
        "all_full": _agg(per_gw, "all", GW_FIRST_EVAL, gw_max),
        "all_late": _agg(per_gw, "all", LATE_SEASON_FROM, gw_max),
    }

    # Per positio (pelanneet, koko kausi) — diagnoosi promptin §4 mukaan
    by_pos = {}
    for pos, pname in xp.POS_NAME.items():
        sel = [o for o in obs_rows if o["pos"] == pos and o["played"]]
        if len(sel) < 10:
            continue
        preds = [o["pred"] for o in sel]
        bases = [o["base"] for o in sel]
        ys = [o["actual"] for o in sel]
        by_pos[pname] = {
            "n": len(sel),
            "mae_xp": mae(preds, ys), "mae_base": mae(bases, ys),
            "rho_xp": rho(preds, ys), "rho_base": rho(bases, ys),
        }

    # 🔒 SHIP-GATE: pelanneet, koko arviointiväli. Ei kumpikaan huonompi,
    # vähintään toinen selkeästi parempi (MAE -2 % tai Spearman +0.02).
    p = agg["played_full"]
    mae_ok = p["mae_xp"] <= p["mae_base"]
    rho_ok = p["rho_xp"] >= p["rho_base"]
    mae_clear = p["mae_xp"] <= p["mae_base"] * 0.98
    rho_clear = p["rho_xp"] >= p["rho_base"] + 0.02
    gate_pass = mae_ok and rho_ok and (mae_clear or rho_clear)

    # §1b-slicet (pelanneet): nousijavastustaja + early season + leikkaus.
    # bias > 0 = xP yliarvioi (CS-inflaatio nousijaa vastaan näkyisi tässä
    # erityisesti GKP/DEF-bias_xp:ssä).
    played = [o for o in obs_rows if o["played"]]
    slices = {
        "vs_promoted": _slice_stats([o for o in played if o["vs_promoted"]]),
        "vs_promoted_def_gkp": _slice_stats(
            [o for o in played if o["vs_promoted"] and o["pos"] in (1, 2)]),
        "vs_promoted_early_gw2_6": _slice_stats(
            [o for o in played if o["vs_promoted"] and o["gw"] <= 6]),
        "early_gw2_6": _slice_stats([o for o in played if o["gw"] <= 6]),
        "muut (ei nousijaa, GW7+)": _slice_stats(
            [o for o in played if not o["vs_promoted"] and o["gw"] > 6]),
        # Tulokas-slice (10.8): vertaa AINA parin sisalla xP:ta baselineen,
        # ala vertaa ryhmien MAE:ta keskenaan. Tulokas pelaa vahemman ja
        # skooraa vahemman -> hanen absoluuttinen virheensa on pienempi
        # vaikka malli olisi hanesta huonompi. GW7+ kertoo sulkeutuuko ero
        # kun pelaajan omia rivelja kertyy — se ratkaisee vaimeneeko lippu.
        "tulokas (ei edelliskauden PL-min)": _slice_stats(
            [o for o in played if o.get("newcomer") is True]),
        "tulokas, GW2-6": _slice_stats(
            [o for o in played if o.get("newcomer") is True and o["gw"] <= 6]),
        "tulokas, GW7+": _slice_stats(
            [o for o in played if o.get("newcomer") is True and o["gw"] > 6]),
        "vakiintunut (on edelliskauden PL-min)": _slice_stats(
            [o for o in played if o.get("newcomer") is False]),
        "vakiintunut, GW2-6": _slice_stats(
            [o for o in played if o.get("newcomer") is False and o["gw"] <= 6]),
        "vakiintunut, GW7+": _slice_stats(
            [o for o in played if o.get("newcomer") is False and o["gw"] > 6]),
    }

    report = {
        "generated_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "season": season_key,
        "dc_train_seasons": seasons,
        "context_layer": use_context,
        "bps_rules": bps_rules,
        "minutes_path": ("minutes_form (LEGACY, ei tuotannossa)"
                         if legacy_minutes else MINUTES_CAVEAT),
        "baseline": (f"form{FORM_WINDOW} (viim. {FORM_WINDOW} joukkuekierroksen "
                     "pistekeskiarvo; FPL:n historiallista ep_next:iä ei ole "
                     "API:ssa saatavilla)"),
        "gate": {
            "population": "pelanneet (minuutit > 0)",
            "criteria": "MAE <= baseline JA Spearman >= baseline, väh. toinen selkeästi parempi",
            "mae_not_worse": mae_ok, "rho_not_worse": rho_ok,
            "mae_clearly_better": mae_clear, "rho_clearly_better": rho_clear,
            "PASS": gate_pass,
        },
        "aggregates": agg,
        "by_position": by_pos,
        "slices": slices,
        "per_gw": per_gw,
    }

    print("\n" + "=" * 72)
    print(f"SHIP-GATE — xP vs form{FORM_WINDOW}-baseline, kausi {season_key}, "
          f"walk-forward GW{GW_FIRST_EVAL}-{gw_max}")
    print("=" * 72)
    for label, a in (("Pelanneet, koko kausi (GATE)", agg["played_full"]),
                     (f"Pelanneet, GW{LATE_SEASON_FROM}+", agg["played_late"]),
                     ("Kaikki rekisteröidyt, koko kausi", agg["all_full"])):
        if not a:
            continue
        print(f"  {label}:")
        print(f"      MAE  xP {a['mae_xp']:.4f}  vs  baseline {a['mae_base']:.4f}"
              f"   ({(a['mae_base'] - a['mae_xp']) / a['mae_base'] * 100:+.1f} %)")
        print(f"      rho  xP {a['rho_xp']:.4f}  vs  baseline {a['rho_base']:.4f}"
              f"   ({a['rho_xp'] - a['rho_base']:+.4f})")
    print("  Per positio (pelanneet):")
    for pname, s in by_pos.items():
        print(f"      {pname}: MAE {s['mae_xp']:.3f} vs {s['mae_base']:.3f}, "
              f"rho {s['rho_xp']:.3f} vs {s['rho_base']:.3f}  (n={s['n']})")
    print("  Slicet (pelanneet; bias = pred - actual, + = yliarvio):")
    for sname, s in slices.items():
        if "mae_xp" not in s:
            continue
        print(f"      {sname}: MAE {s['mae_xp']:.3f} vs base {s['mae_base']:.3f}, "
              f"bias xP {s['bias_xp']:+.3f} / base {s['bias_base']:+.3f}  (n={s['n']})")
    print(f"\n  GATE: {'PASS' if gate_pass else 'FAIL'}")
    print("=" * 72)
    return report



# ---------------------------------------------------------------------------
# TULOKAS-RAPORTTI (10.8.2026)
#
# KOLME MITTARIA, KOSKA YKSI VALEHTELEE:
#   1. Pisteet, PELANNEET — vertaa aina parin sisalla xP:ta baselineen. Ryhmien
#      MAE:ta EI saa verrata keskenaan: tulokas pelaa ja skooraa vahemman, joten
#      hanen absoluuttinen virheensa on pienempi vaikka malli olisi hanesta
#      huonompi. Tama on se ansa johon slice-taulukko yksin johtaa.
#   2. Pisteet, KAIKKI REKISTEROIDYT — "pelanneet"-rajaus suodattaa pois tasan
#      sen riskin josta lippu kertoisi: pelaako han lainkaan.
#   3. MINUUTIT — tulokkaalla ei ole omia rivelja joista xMins lasketaan. Jos
#      pelaajatason lippu on olemassa, sen pitaa nakya taalla.
# ---------------------------------------------------------------------------
def _grp(obs: list[dict]) -> dict:
    if len(obs) < 30:
        return {"n": len(obs)}
    preds = np.array([o["pred"] for o in obs])
    bases = np.array([o["base"] for o in obs])
    ys = np.array([o["actual"] for o in obs])
    xm = np.array([o["xmins"] for o in obs if o.get("xmins") is not None])
    am = np.array([o["amins"] for o in obs if o.get("xmins") is not None])
    out = {
        "n": len(obs),
        "mae_xp": float(np.mean(np.abs(preds - ys))),
        "mae_base": float(np.mean(np.abs(bases - ys))),
        "bias_xp": float(np.mean(preds - ys)),
    }
    # Lift = kuinka paljon xP voittaa baselinen SAMASSA ryhmassa. Tama on
    # ainoa ryhmien valilla vertailukelpoinen luku.
    out["lift_pct"] = (out["mae_base"] - out["mae_xp"]) / out["mae_base"] * 100
    if len(xm) >= 30:
        out["mae_mins"] = float(np.mean(np.abs(xm - am)))
        out["bias_mins"] = float(np.mean(xm - am))
    return out


def report_newcomer(obs_rows: list[dict]) -> None:
    known = [o for o in obs_rows if o.get("newcomer") is not None]
    if not known:
        print("\nTULOKAS-RAPORTTI: ei ajettu (edelliskauden arkisto puuttuu)")
        return
    print()
    print("=" * 72)
    print("TULOKAS vs VAKIINTUNUT — onko xP huonompi ilman liigahistoriaa?")
    print("  tulokas = ei yhtaan PL-minuuttia edellisella kaudella (code-liitos)")
    print("=" * 72)
    for pop_name, pop in (("PELANNEET (min > 0)", [o for o in known if o["played"]]),
                          ("KAIKKI REKISTEROIDYT", known)):
        print(f"  {pop_name}:")
        for label, sel in (("tulokas    ", [o for o in pop if o["newcomer"]]),
                           ("vakiintunut", [o for o in pop if not o["newcomer"]])):
            for win, rows in (("koko kausi", sel),
                              ("GW2-6     ", [o for o in sel if o["gw"] <= 6]),
                              ("GW7+      ", [o for o in sel if o["gw"] > 6])):
                s = _grp(rows)
                if "mae_xp" not in s:
                    print(f"      {label} {win}: n={s['n']} (alle 30, ei laskettu)")
                    continue
                mins = (f"  |  min-MAE {s['mae_mins']:.1f} "
                        f"(bias {s['bias_mins']:+.1f})" if "mae_mins" in s else "")
                print(f"      {label} {win}: MAE {s['mae_xp']:.3f} vs base "
                      f"{s['mae_base']:.3f} = LIFT {s['lift_pct']:+.1f} %  "
                      f"bias {s['bias_xp']:+.3f}  (n={s['n']}){mins}")
    # TERAVAMPI LEIKKAUS: "ei minuutteja viime kaudella" on noin puolet
    # rekisteroidyista, koska se nappaa akatemia- ja reunapelaajat samaan
    # ryhmaan ulkomaisten hankintojen kanssa. Jos lippu shipattaisiin, se
    # naytettaisiin nimenomaan hankinnoista. Hinta on karkea mutta
    # VUOTAMATON erotin (tiedossa ennen kierrosta) — huom. 9.8. mitattiin
    # ettei FPL-hinta ole laatusignaali, joten tama on populaation rajaus
    # eika laadun mittari.
    price_cut = 5.5
    print(f"  HANKINNAT VAIN (hinta >= {price_cut} milj., pelanneet):")
    for label, is_new in (("tulokas    ", True), ("vakiintunut", False)):
        base_sel = [o for o in known
                    if o["played"] and o["newcomer"] is is_new
                    and o.get("price", 0) >= price_cut]
        for win, rows in (("koko kausi", base_sel),
                          ("GW2-6     ", [o for o in base_sel if o["gw"] <= 6])):
            s = _grp(rows)
            if "mae_xp" not in s:
                print(f"      {label} {win}: n={s['n']} (alle 30, ei laskettu)")
                continue
            mins = (f"  |  min-MAE {s['mae_mins']:.1f} "
                    f"(bias {s['bias_mins']:+.1f})" if "mae_mins" in s else "")
            print(f"      {label} {win}: MAE {s['mae_xp']:.3f} vs base "
                  f"{s['mae_base']:.3f} = LIFT {s['lift_pct']:+.1f} %  "
                  f"bias {s['bias_xp']:+.3f}  (n={s['n']}){mins}")
    print("  LUKUOHJE: vertaa LIFT-lukuja ryhmien valilla, ala MAE-lukuja.")
    print("=" * 72)


# ---------------------------------------------------------------------------
# KOMPONENTTITASON VALIDOINTI (4.8.2026, Villen GO)
#
# Miksi erikseen: ship-gate validoi xP-SUMMAN. Maali- ja syottokomponentit ovat
# summan osia, ja summa voi olla oikein vaikka osat olisivat vaarin vastakkaisiin
# suuntiin. Jos nama luvut aiotaan NAYTTAA tuotteessa ("model expects 0.68
# goals"), ne on validoitava omina lukuinaan.
#
# Kolme kysymysta, kolme mittaria:
#   1. Kalibraatio: summautuuko odotus toteutuneeseen? (bias)
#   2. Erottelu:    rankkaako se oikeat pelaajat karkeen? (Spearman)
#   3. Kaytettavyys: onko P(>=1 maali) parempi kuin naiivi vertailukohta? (Brier)
# ---------------------------------------------------------------------------
def report_components(obs_rows: list[dict]) -> None:
    played = [o for o in obs_rows if o["played"] and "eg" in o]
    if len(played) < 100:
        print("KOMPONENTIT: liian vahan havaintoja")
        return
    print()
    print("=" * 66)
    print(f"KOMPONENTTITASON VALIDOINTI  (n={len(played)} pelaaja-GW, pelanneet)")
    print("=" * 66)

    def block(label, rows):
        if len(rows) < 30:
            print(f"{label:>6}  otos liian pieni (n={len(rows)})")
            return
        for key, act, name in (("eg", "ag", "maalit"), ("ea", "aa", "syotot")):
            pe = sum(r[key] for r in rows)
            pa = sum(r[act] for r in rows)
            bias = (pe / pa - 1) * 100 if pa else float("nan")
            # Spearman ilman scipya: rank-korrelaatio
            def rank(vals):
                order = sorted(range(len(vals)), key=lambda i: vals[i])
                rk = [0.0] * len(vals)
                for pos_, i in enumerate(order):
                    rk[i] = pos_
                return rk
            rx, ry = rank([r[key] for r in rows]), rank([r[act] for r in rows])
            n = len(rows)
            mx, my = sum(rx) / n, sum(ry) / n
            num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
            den = (sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry)) ** 0.5
            rho = num / den if den else 0.0
            # Brier P(>=1) Poissonista vs naiivi (populaation osuus)
            import math
            base_rate = sum(1 for r in rows if r[act] >= 1) / n
            b_model = sum((1 - math.exp(-r[key]) - (1 if r[act] >= 1 else 0)) ** 2
                          for r in rows) / n
            b_naive = sum((base_rate - (1 if r[act] >= 1 else 0)) ** 2 for r in rows) / n
            print(f"{label:>6} {name:>7}  odotus {pe:7.1f}  toteutunut {pa:6.0f}  "
                  f"bias {bias:+6.1f} %   rho {rho:+.3f}   "
                  f"Brier {b_model:.4f} vs naiivi {b_naive:.4f} "
                  f"({(b_naive - b_model) / b_naive * 100:+.1f} %)")

    block("KAIKKI", played)
    for pos, nimi in ((2, "DEF"), (3, "MID"), (4, "FWD")):
        block(nimi, [o for o in played if o["pos"] == pos])
    print("TULKINTA: luku on julkaisukelpoinen vain jos bias on pieni JA "
          "Brier voittaa naiivin. Pelkka korkea rho ei riita: se kertoo "
          "jarjestyksesta, ei siita etta luku 0.68 tarkoittaa 0.68:aa.")

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true",
                    help="pakota FPL-datan uudelleenhaku (ohita välimuisti)")
    ap.add_argument("--raw", action="store_true",
                    help="aja ILMAN Phase 1b -kontekstikerrosta (vertailuajo)")
    ap.add_argument("--archive", action="store_true",
                    help="pakota 25/26 levyarkisto (lahde valitaan muuten auto)")
    ap.add_argument("--live", action="store_true",
                    help="pakota elava FPL-API vaikka kausi olisi kesken "
                         "(vain diagnoosiin — tulos ei ole ship-gate)")
    ap.add_argument("--legacy-minutes", action="store_true",
                    help="aja eliakkeelle jaaneella minutes_form-polulla "
                         "(vain ennen/jalkeen-vertailuun)")
    ap.add_argument("--components", action="store_true",
                    help="lisaa maali- ja syottokomponenttien validointi")
    ap.add_argument("--legacy-bps", action="store_true",
                    help="OHITA 26/27 BPS-oikaisu (#151) — vain ennen/jälkeen-"
                         "vertailuajoihin")
    args = ap.parse_args()

    report = run_backtest(show_components=args.components,
                          force_refresh=args.refresh, use_context=not args.raw,
                          bps_2627=not args.legacy_bps, archive=args.archive,
                          live=args.live, legacy_minutes=args.legacy_minutes)

    out_dir = config.PROJECT_ROOT / "logs"
    out_dir.mkdir(exist_ok=True)
    suffix = (("_raw" if args.raw else "") + ("_legacybps" if args.legacy_bps else "")
              + ("_legacymins" if args.legacy_minutes else "")
              + ("_live" if args.live else ""))
    out = out_dir / f"fpl_xp_backtest_{_dt.date.today().isoformat()}{suffix}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    print(f"\nRaportti: {out}")

    # 26.7: committoitava tiiviste rate-team-selitetta varten. Taysi raportti
    # on gitignored (logs/), joten Render ei nakisi sita — ja ilman tata luvut
    # olisi pitanyt kovakoodata copyyn, jolloin ne vanhenisivat hiljaa
    # seuraavassa refitissa. Vain paaajo kirjoittaa (ei --raw/--legacy-bps,
    # jotka ovat vertailuajoja).
    if not any((args.raw, args.legacy_bps, args.legacy_minutes, args.live)):
        agg = report["aggregates"]["played_full"]
        summary = {
            "meta": {
                "source": out.name,
                "generated_at": report["generated_at"],
                "season": report["season"],
                "method": ("walk-forward backtest on the completed season; the "
                           "model only ever saw gameweeks before the one it "
                           "predicted"),
                "population": report["gate"].get("population"),
                "gate_passed": bool(report["gate"]["PASS"]),
                "minutes_path": report["minutes_path"],
            },
            "played": {
                "gw_range": agg["gw_range"], "n_gws": agg["n_gws"],
                "mae_xp": round(agg["mae_xp"], 3),
                "mae_baseline": round(agg["mae_base"], 3),
                "rho_xp": round(agg["rho_xp"], 3),
                "rho_baseline": round(agg["rho_base"], 3),
            },
            "by_position": {
                k: {"n": v["n"], "mae_xp": round(v["mae_xp"], 3),
                    "mae_baseline": round(v["mae_base"], 3)}
                for k, v in report.get("by_position", {}).items()
            },
            "known_bias": {
                "signed_bias_xp": round(
                    report["slices"]["muut (ei nousijaa, GW7+)"]["bias_xp"], 3),
                "note": ("negative = the model under-predicts points on "
                         "average; ranking is unaffected, absolute values run "
                         "low"),
            },
        }
        acc = config.PROJECT_ROOT / "data" / "fpl_xp_accuracy.json"
        acc.write_text(json.dumps(summary, ensure_ascii=False, indent=1),
                       encoding="utf-8")
        print(f"Tiiviste (committoitava): {acc}")

    return 0 if report["gate"]["PASS"] else 2


if __name__ == "__main__":
    sys.exit(main())
