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

OUT_PATH = config.PROJECT_ROOT / "data" / "fpl_xp_projections.json"

# Pudota kuollut paino JSONista (ei minuutteja odotettavissa, ei pisteitä).
MIN_XP_TOTAL = 1.0


# ---------------------------------------------------------------------------
# Saatavuus (vain tuotanto — backtestissä ei historiallista statusta)
# ---------------------------------------------------------------------------
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
def sanity_gate(players: list[dict], boot: dict, coverable_teams: set[str]) -> bool:
    """coverable_teams = tulevan kauden fixture-joukkueet joilla on FPL-
    pelaajadataa. Pre-seasonissa nousijat puuttuvat FPL:stä rakenteellisesti
    (meta.todo) — gate vaatii että KAIKKI katettavissa olevat on katettu
    ja että niitä on vähintään 15 (17 = normaali pre-season, 20 = live)."""
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
    pts_rank = {e["id"]: i for i, e in enumerate(
        sorted(boot["elements"], key=lambda e: -e["total_points"]))}
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
# main
# ---------------------------------------------------------------------------
def main() -> int:
    src = fetch_source()

    print("[2/6] FPL-pelaajadata (bootstrap + element-historiat)...")
    boot = fpl_api.fetch_bootstrap()
    # Kesken kauden historia muuttuu joka GW → pakota tuore haku. Päättyneen
    # kauden data on staattista → välimuisti riittää (pre-season-ajot nopeita).
    season_live = any(not ev.get("finished") for ev in boot.get("events", []))
    summaries = fpl_api.fetch_all_summaries(boot, force=season_live)
    print(f"      {len(boot['elements'])} pelaajaa "
          f"({'live-kausi, tuore haku' if season_live else 'päättynyt kausi, välimuisti'})")

    print("[3/6] Sovitetaan PL Dixon-Coles (sama fit kuin /api/predict)...")
    dc, seasons = fit_model()
    fixture_teams = sorted({map_name(t) for t in src["teams"]})
    missing = sorted(set(fixture_teams) - set(dc.attack))
    baseline = add_promoted_baseline(dc, missing)
    print(f"      {len(dc.teams_)} joukkuetta, promoted baseline: {missing or '-'}")

    print("[4/6] Pelaajavauhdit + minuuttimalli (koko saatavilla oleva historia)...")
    pos_by_player = {e["id"]: e["element_type"] for e in boot["elements"]}
    acc_by_player: dict[int, dict] = {}
    mins_by_round: dict[int, dict[int, float]] = {}
    starts_by_round: dict[int, dict[int, int]] = {}
    for e in boot["elements"]:
        pid = e["id"]
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
    all_rounds = sorted({rnd for mr in mins_by_round.values() for rnd in mr})

    # #33: probabilistinen minuuttimalli — kaksi passia:
    #   A) minutes_model + saatavuus-gate per pelaaja
    #   B) syvyys-korjaus klubi+positio-ryhmittäin (Σp_start → historialliset
    #      starttipaikat; availability-nollaama kilpailija nostaa muita capatusti)
    mm_window = 6 if season_live else None
    mm_by_player: dict[int, dict] = {}
    for e in boot["elements"]:
        pid = e["id"]
        mm = xp.minutes_model(mins_by_round[pid], starts_by_round[pid],
                              all_rounds, n_last=mm_window)
        mm_by_player[pid] = xp.apply_availability(
            mm, e.get("status", "a"), e.get("chance_of_playing_next_round"))
    window_rounds = all_rounds if mm_window is None else all_rounds[-mm_window:]
    groups: dict[tuple[int, int], list[int]] = defaultdict(list)
    for e in boot["elements"]:
        groups[(e["team"], e["element_type"])].append(e["id"])
    for (_team, _pos), pids in groups.items():
        # slots = ryhmän toteutuneet startit / kierros ikkunassa (itsekonsistentti)
        slots = (sum(starts_by_round[p].get(rnd, 0)
                     for p in pids for rnd in window_rounds)
                 / max(len(window_rounds), 1))
        # Syvyys nojaa RAAKAAN start-shareen (slots samasta datasta → konsistentti)
        f = xp.depth_factor([mm_by_player[p]["p_start_raw"] for p in pids], slots)
        if f != 1.0:
            for p in pids:
                mm_by_player[p] = xp.scale_p_start(mm_by_player[p], f)

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

    # FPL-joukkue (25/26) → mallinimi → fixture-id. Joukkueet joita ei ole
    # tulevan kauden fixtureissa (putoajat) jäävät pois; nousijoilla ei ole
    # FPL-pelaajia ennen kuin 26/27-peli avautuu (meta.todo).
    fplteam_to_fid = {}
    for t in boot["teams"]:
        model = map_name(t["name"])
        if model in name_to_fid:
            fplteam_to_fid[t["id"]] = name_to_fid[model]
    covered_fids = set(fplteam_to_fid.values())
    uncovered = sorted(n for n, fid in name_to_fid.items() if fid not in covered_fids)

    players = []
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
        gws = []
        total = 0.0
        # #3 OSA A: komponenttierittely headline-GW:lle (next_gw). Kertyy
        # TÄSMÄLLEEN samoista xp_components-dicteistä joista totalit lasketaan
        # → pelkkä emittointi, ei laskennan muutosta (xp-arvot identtiset).
        headline_comps: dict[str, float] = {}
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
            continue
        # Promptin kenttänimet (def_contribution -> defensive_contribution,
        # cards -> yellows). Emitoidaan vain jos headline-GW:llä oli fixture.
        components = None
        if headline_comps:
            key_map = {"def_contribution": "defensive_contribution",
                       "cards": "yellows"}
            components = {key_map.get(k, k): round(v, 2)
                          for k, v in headline_comps.items()}
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
            # #143: rehellisyyslippu — paljonko pelaajan omaa PL-dataa
            # estimaatin takana on (puhdas emissio, ei muuta xP-lukuja).
            "data_basis": xp.data_basis(acc_by_player[pid]),
            "xp_per_gw": round(total / max(len(horizon), 1), 2),
            "xp_horizon_total": round(total, 2),
            "gameweeks": gws,
        }
        if components is not None:
            player_row["components"] = components
            player_row["components_gw"] = next_gw
        players.append(player_row)
    players.sort(key=lambda p: -p["xp_horizon_total"])
    print(f"      {len(players)} pelaajaa (xP >= {MIN_XP_TOTAL} horisontissa), "
          f"GW{next_gw}-{horizon[-1]}")

    coverable = {n for n, fid in name_to_fid.items() if fid in covered_fids}
    if not sanity_gate(players, boot, coverable):
        print("SANITY-GATE FAIL — data/fpl_xp_projections.json EI kirjoitettu.")
        return 2

    print("\n[6/6] Kirjoitetaan JSON...")
    todo = []
    if src["source"] != "fpl-api":
        todo.append(
            "TODO(kaudenvaihto): FPL-API ei vielä tarjoile 26/27-kautta — "
            "fixturet pulselive-fallbackista, pelaajabaselinet = koko 25/26-kausi "
            "(siirtoja ei tunneta). Aja uudelleen kun FPL-peli avautuu."
        )
    if uncovered:
        todo.append(
            f"Ilman pelaajadataa (nousijat, ei vielä FPL:ssä): {uncovered} — "
            "täyttyvät automaattisesti kun 26/27-peli avautuu."
        )
    out = {
        "meta": {
            "product": "GoalIQ Fantasy Phase 1 — expected points (xP)",
            "available": True,
            "phase": 1,
            "generated_at": _dt.datetime.now().isoformat(timespec="seconds"),
            "season": SEASON_LABEL,
            "fixture_source": src["source_label"],
            "player_source": "FPL official API (bootstrap + element-summary history)",
            "team_strength_source": (
                f"GoalIQ Dixon-Coles, Understat PL {seasons} "
                "(sama fit-config kuin /api/predict)"
            ),
            "method": (
                "xP = esiintyminen + maalit + syötöt + CS + päästetyt + torjunnat "
                "+ def.contribution + bonus-proxy - kortit; kaava src/models/fpl_xp.py, "
                "validoitu walk-forward-backtestillä 25/26 (scripts/backtest_fpl_xp.py)"
            ),
            "caveat": (
                "Pre-season: pelaajabaselinet = edellisen kauden FPL-historia, "
                "minuuttiarvio = kauden lopun rotaatio + FPL-saatavuustieto. "
                "Tarkentuu automaattisesti kun 26/27-kierroksia kertyy."
            ),
            "promoted_baseline_teams": missing,
            "promoted_baseline_values": baseline,
            # #143: rakenteinen katvealueraportti — sama tieto joka tähän asti
            # oli vain proosana todo-listassa, nyt UI:n luettavissa.
            "data_coverage": {
                "baseline_season": prev_key,
                "transfers_known": src["source"] == "fpl-api",
                "teams_without_player_data": uncovered,
                "player_basis_counts": {
                    v: sum(1 for p in players if p["data_basis"] == v)
                    for v in xp.DATA_BASIS_VALUES
                },
                "basis_threshold_minutes": xp.M_PRIOR_ATTACK,
                "note": (
                    "data_basis per pelaaja: pl_history = oma PL-historia "
                    "kantaa >= 50 % painon; limited_history = ohut otos, "
                    "positiopriori dominoi; no_history = ei PL-minuutteja. "
                    "transfers_known=false: pre-season-bootstrap on edellisen "
                    "kauden -> kesäsiirrot eivät näy."
                ),
            },
            "context_layer": {
                "promoted_teams": sorted(promoted),
                "promoted_home_opener_att_boost": PROMOTED_HOME_OPENER_ATT_BOOST,
                "manual_overrides": len(overrides),
                "applied_in_horizon": ctx_notes,
                "note": ("Phase 1b: nousija-koti-avaus-buusti + manuaaliset "
                         "yliajot (data/fpl_manual_overrides.csv) + "
                         "MM-väsymyskertoimet (täytetään ~20.7)"),
            },
            "sanity_gate": "PASS",
            "next_gameweek": next_gw,
            "deadline_utc": src["deadline_utc"],
            "horizon_gw": HORIZON_GW,
            "min_xp_total": MIN_XP_TOTAL,
            "n_players": len(players),
            "todo": todo,
        },
        "players": players,
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
