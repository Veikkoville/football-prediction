"""Nightly-cache #124 xG leaders + #125 DefCon tracker -datalle.

Hakee FPL bootstrap + element-summaryt (levyvälimuisti src/data/fpl_api.py:n
kautta — valmiin kauden summaryt eivät vanhene) ja kirjoittaa per-pelaaja
viimeisimmät pelatut ottelut → data/fpl_player_leaders.json. Endpointit
/api/fantasy/xg-leaders + /api/fantasy/defcon-leaders rankkaavat tästä
(src/models/fpl_leaders.py) — ei laskentaa pyynnössä.

DATA-RAJOITUKSET ENSILUOKKAISENA (Villen vaatimus 17.7):
  - basis_season = bootstrapin servaama kausi. Nyt (ennen 26/27-avausta) se on
    2025/26 → meta.is_prev_season_basis=True + pakollinen basis_label.
  - Kun FPL avaa 26/27:n: basis vaihtuu automaattisesti. Pelaajille joilla
    < MIN_CURRENT_GAMES (3) pelattua 26/27-ottelua käytetään EDELLISEN
    committatun snapshotin 25/26-rivejä (per-pelaaja basis-kenttä kertoo
    lähteen) — 25/26-baseline kunnes todellista kauden dataa on tarpeeksi.
  - Pelaaja ilman yhtään pelattua ottelua kummassakaan → ei listalla
    (frontend: "No data yet") — EI arvauksia.

Fail-safe: sanity gate FAIL → exit 2 → EI committia (vanha data jää voimaan),
sama konventio kuin muut FPL-builderit.
"""
from __future__ import annotations

import datetime as _dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data.fpl_api import (fetch_bootstrap, fetch_all_summaries,
                              season_key_from_bootstrap)
from src.models.fpl_leaders import LEADERS_PATH, MIN_CURRENT_GAMES

POS_NAME = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}
RECENT_KEEP = 10          # rivejä per pelaaja → window 3-10 endpointissa
TARGET_SEASON = "2026/27"  # kausi jota kohti ollaan menossa (label-logiikka)
SANITY_MIN_PLAYERS = 200
SANITY_MAX_XG_PG = 2.5    # kukaan ei tuota >2.5 xG/game kestävästi


def season_label(key: str) -> str:
    """"2526" → "2025/26"."""
    return f"20{key[:2]}/{key[2:]}"


def _player_rows(boot: dict, summaries: dict, season: str,
                 keep_empty: bool) -> list[dict]:
    """Rakenna per-pelaaja-rivit bootstrap+summary-datasta. keep_empty=True
    jättää 0 pelatun ottelun pelaajat mukaan stubina (recent_games=[]) —
    kausivaihto-merge voi täyttää ne edellisen snapshotin riveillä."""
    teams = {t["id"]: t["short_name"] for t in boot["teams"]}
    players = []
    for e in boot["elements"]:
        pos = POS_NAME.get(e["element_type"])
        if pos is None:
            continue
        history = summaries.get(e["id"]) or []
        played = [r for r in history if (r.get("minutes") or 0) > 0]
        played.sort(key=lambda r: (r.get("round") or 0, r.get("kickoff_time") or ""))
        recent = played[-RECENT_KEEP:]
        if not recent and not keep_empty:
            continue  # ei pelattuja otteluita → ei listalle (No data yet)
        rows = []
        for r in recent:
            cbit = ((r.get("clearances_blocks_interceptions") or 0)
                    + (r.get("tackles") or 0))
            cbirt = cbit + (r.get("recoveries") or 0)
            rows.append({
                "round": r.get("round"),
                "opp": teams.get(r.get("opponent_team"), ""),
                "venue": "H" if r.get("was_home") else "A",
                "minutes": r.get("minutes") or 0,
                "xg": float(r.get("expected_goals") or 0.0),
                "xa": float(r.get("expected_assists") or 0.0),
                "xgi": float(r.get("expected_goal_involvements") or 0.0),
                # dc = FPL:n defensive_contribution-kenttä (== CBIT DEF:lle,
                # CBIRT MID/FWD:lle; empiirisesti verifioitu 100 %) — fallback
                # laskettuun arvoon jos kenttä puuttuu.
                "dc": int(r.get("defensive_contribution")
                          if r.get("defensive_contribution") is not None
                          else (cbit if pos == "DEF" else cbirt)),
                # Villen pyyntö 25.7: DefCon eriteltynä. Osatekijät laskettiin
                # jo (cbit/cbirt) mutta heitettiin pois — nyt talteen, jotta
                # player card voi näyttää mistä luku koostuu. cbi ja tackles
                # erikseen koska FPL tarjoaa ne eri kenttinä (cbi on valmiiksi
                # yhdistetty clearances+blocks+interceptions, ei eroteltavissa).
                "cbi": int(r.get("clearances_blocks_interceptions") or 0),
                "tkl": int(r.get("tackles") or 0),
                "rec": int(r.get("recoveries") or 0),
            })
        players.append({
            "id": e["id"],
            # code = FPL:n kausien yli pysyvä pelaajakoodi — kausivaihto-
            # mergen avain (element-id:t NOLLAUTUVAT kausivaihdossa, joten
            # id-mappaus sekoittaisi eri pelaajien historiat).
            "code": e.get("code"),
            "web_name": e["web_name"],
            "team_short": teams.get(e["team"], ""),
            "pos": pos,
            "price": (e.get("now_cost") or 0) / 10.0,
            "owned_pct": float(e.get("selected_by_percent") or 0.0),
            "games_total": len(played),
            "basis": season,
            "recent_games": rows,
        })
    return players


def build() -> dict:
    boot = fetch_bootstrap()
    season = season_label(season_key_from_bootstrap(boot))
    players = _player_rows(boot, fetch_all_summaries(boot), season,
                           keep_empty=(season == TARGET_SEASON))

    # Kausivaihto-merge: jos basis on jo target-kausi mutta pelaajalla on alle
    # MIN_CURRENT_GAMES pelattua ottelua → käytä edellisen snapshotin
    # edelliskauden riviä (basis-kenttä säilyy 2025/26 → rehellinen label).
    # Mappaus element CODElla (pysyvä kausien yli) — EI id:llä (nollautuu).
    if season == TARGET_SEASON and LEADERS_PATH.exists():
        try:
            prev = json.loads(LEADERS_PATH.read_text(encoding="utf-8"))
            prev_by_code = {p["code"]: p for p in prev.get("players", [])
                            if p.get("basis") != TARGET_SEASON and p.get("code")}
        except Exception:
            prev_by_code = {}
        merged = []
        for p in players:
            if p["games_total"] < MIN_CURRENT_GAMES and p.get("code") in prev_by_code:
                # KORJAUS 26.7: aiemmin tassa otettiin KOKO edellisen kauden rivi,
                # jolloin taulukkoon jai viime kauden HINTA, omistus-% ja seura.
                # Esikaudella se koski kaikkia pelaajia -> esim. Haaland 14.7
                # vaikka FPL:n 26/27-hinta on 15.5, ja seuraa vaihtanut pelaaja
                # nakyi vanhassa seurassaan.
                #
                # Historialliset ottelustatsit KUULUU perii vanhasta (niita ei ole
                # uudelta kaudelta), mutta hinta, omistus, seura ja pelipaikka ovat
                # KULUVAN kauden attribuutteja ja tulevat elavasta bootstrapista.
                old = prev_by_code[p["code"]]
                row = dict(p)                      # tuore rivi = tuoreet attribuutit
                row["recent_games"] = old.get("recent_games") or []
                row["games_total"] = old.get("games_total", 0)
                row["basis"] = old.get("basis")    # rehellinen label sailyy
                merged.append(row)
            else:
                merged.append(p)
        players = merged
    # Stubit joille ei löytynyt edelliskauden riviä → pois (No data yet).
    players = [p for p in players if p["recent_games"]]
    return _package(season, players)


def build_from_cache_2526() -> dict:
    """Kertaluontoinen kausivaihtoajo (--freeze-prev-2526): rakenna snapshot
    lokaalista 25/26-levycachesta (vanha bootstrap + summary_2526/). MIKSI:
    26/27-flipin (23.7.2026) jälkeen 25/26-per-ottelu-data ei ole enää
    haettavissa API:sta, ja aiemmin committoidusta snapshotista puuttuvat
    code-kentät joita kausivaihto-merge tarvitsee. VAIN levycache — ei
    verkkohakuja."""
    cache = Path(__file__).resolve().parent.parent / "data" / "raw" / "fpl"
    boot = json.loads((cache / "bootstrap_static.json").read_text(encoding="utf-8"))
    if not boot["events"][0]["deadline_time"].startswith("2025-"):
        raise SystemExit(
            "VIRHE: bootstrap-cache ei ole 25/26-kautta (ylikirjoitettu jo "
            "26/27:llä) — freeze ei mahdollinen tällä koneella.")
    summaries: dict[int, list[dict]] = {}
    missing = 0
    for e in boot["elements"]:
        p = cache / "summary_2526" / f"element_{e['id']}.json"
        if p.exists():
            summaries[e["id"]] = json.loads(
                p.read_text(encoding="utf-8")).get("history", [])
        else:
            missing += 1
    if missing:
        raise SystemExit(f"VIRHE: {missing} summary-tiedostoa puuttuu cachesta.")
    season = season_label(season_key_from_bootstrap(boot))
    players = _player_rows(boot, summaries, season, keep_empty=False)
    return _package(season, players)


def _package(season: str, players: list[dict]) -> dict:
    is_prev = season != TARGET_SEASON or all(
        p.get("basis") != TARGET_SEASON for p in players)
    basis_label = (
        f"Based on {season} · updates as the new season plays"
        if season != TARGET_SEASON else
        "Mixed basis: players with under 3 games this season show last "
        "season's data (per-row basis field)."
        if any(p.get("basis") != TARGET_SEASON for p in players) else
        "This season's data."
    )

    return {
        "meta": {
            "available": True,
            "generated_at": _dt.datetime.now(_dt.timezone.utc)
                .strftime("%Y-%m-%dT%H:%M:%S"),
            "basis_season": season,
            "target_season": TARGET_SEASON,
            "is_prev_season_basis": is_prev,
            "basis_label": basis_label,
            "recent_keep": RECENT_KEEP,
            "min_current_games": MIN_CURRENT_GAMES,
            "n_players": len(players),
            "source": "FPL official API (bootstrap + element-summary)",
            "defcon_rule_verified": (
                "2026-07-17: premierleague.com 25/26 rules (DEF 10 CBIT / "
                "MID+FWD 12 CBIRT, 2 pts, capped per match) + bootstrap "
                "game_config.scoring + empirical field check 100%"),
        },
        "players": players,
    }


def sanity(data: dict) -> list[str]:
    fails = []
    n = len(data["players"])
    if n < SANITY_MIN_PLAYERS:
        fails.append(f"players {n} < {SANITY_MIN_PLAYERS}")
    for p in data["players"]:
        recent = p["recent_games"][-5:]
        if not recent:
            continue
        xg_pg = sum(g["xg"] for g in recent) / len(recent)
        if xg_pg > SANITY_MAX_XG_PG:
            fails.append(f"{p['web_name']} xg/game {xg_pg:.2f} epäuskottava")
        for g in recent:
            if g["dc"] < 0 or g["dc"] > 60:
                fails.append(f"{p['web_name']} dc {g['dc']} out of range")
    return fails[:10]


def refresh_current_attrs(boot: dict) -> dict | None:
    """Esikausipäivitys: pidä historialliset ottelurivit, mutta päivitä
    KULUVAN kauden attribuutit elävästä bootstrapista. Vain 1 API-kutsu.

    MIKSI (26.7.2026): kausivaihto-guard jäädytti koko snapshotin, jolloin
    taulukko näytti viime kauden hintoja (Haaland 14.7 vaikka 26/27-hinta on
    15.5, B.Fernandes 10.4 vaikka 12.0) ja seuraa vaihtaneet pelaajat näkyivät
    vanhassa seurassaan. Ottelustatsit KUULUU periä vanhasta (niitä ei ole
    uudelta kaudelta), mutta hinta, omistus-%, seura ja pelipaikka ovat
    kuluvan kauden attribuutteja.

    Pelaajat jotka eivät ole enää 26/27-pelissä pudotetaan: heitä ei voi
    valita, joten heidän näyttämisensä on harhaanjohtavaa.
    """
    if not LEADERS_PATH.exists():
        return None
    data = json.loads(LEADERS_PATH.read_text(encoding="utf-8"))
    teams = {t["id"]: t["short_name"] for t in boot["teams"]}
    by_code = {e["code"]: e for e in boot["elements"]}
    kept, dropped = [], 0
    for p in data.get("players", []):
        e = by_code.get(p.get("code"))
        pos = POS_NAME.get(e["element_type"]) if e else None
        if e is None or pos is None:
            dropped += 1
            continue
        p["id"] = e["id"]
        p["web_name"] = e["web_name"]
        p["team_short"] = teams.get(e["team"], p.get("team_short", ""))
        p["pos"] = pos
        p["price"] = e["now_cost"] / 10.0
        p["owned_pct"] = float(e.get("selected_by_percent") or 0.0)
        # Kausitotaalit suoraan bootstrapista (sama lahde kuin per-ottelu-
        # rivit). Nailla saa "koko kausi" -ikkunan ilman yhtaan lisahakua:
        # rullaava 3/5/10 kertoo vireesta, kausitotaali otoskoosta.
        p["season"] = {
            "mins": int(e.get("minutes") or 0),
            "starts": int(e.get("starts") or 0),
            "xg": round(float(e.get("expected_goals") or 0.0), 2),
            "xa": round(float(e.get("expected_assists") or 0.0), 2),
            "xgi": round(float(e.get("expected_goal_involvements") or 0.0), 2),
        }
        kept.append(p)
    data["players"] = kept
    meta = data.setdefault("meta", {})
    meta["n_players"] = len(kept)
    meta["current_attrs_refreshed_at"] = _dt.datetime.now(
        _dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"  attribuutit paivitetty: {len(kept)} pelaajaa, "
          f"pudotettu (ei 26/27-pelissa): {dropped}")
    return data


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--freeze-prev-2526", action="store_true",
                    help="Rakenna snapshot lokaalista 25/26-cachesta "
                         "(kertaluontoinen kausivaihtoajo, lisää code-kentät)")
    args = ap.parse_args(argv)

    if args.freeze_prev_2526:
        data = build_from_cache_2526()
    else:
        boot = fetch_bootstrap()
        season = season_label(season_key_from_bootstrap(boot))
        # Kausivaihto-guard: kohdekausi ilman yhtään pelattua GW:tä →
        # edellinen (25/26-basis, rehellisesti labeloitu) snapshot jää
        # voimaan EIKÄ haeta 841 tyhjää element-summarya turhaan.
        if season == TARGET_SEASON and not any(
                ev.get("finished") for ev in boot.get("events", [])):
            # Historiarivit jäävät ennalleen (ei haeta 841 tyhjää summarya),
            # mutta hinta/omistus/seura/pelipaikka päivitetään bootstrapista.
            print(f"PRE-SEASON ({season}, 0 pelattua GW:tä) — ottelurivit "
                  f"ennallaan, kuluvan kauden attribuutit päivitetään.")
            data = refresh_current_attrs(boot)
            if data is None:
                print("  ei aiempaa snapshottia — ei mitään päivitettävää.")
                return 0
        else:
            data = build()
    fails = sanity(data)
    if fails:
        print("SANITY FAIL — dataa EI kirjoiteta:")
        for f in fails:
            print(f"  - {f}")
        return 2
    LEADERS_PATH.write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8")
    m = data["meta"]
    print("=" * 64)
    print("FPL PLAYER LEADERS BUILD OK")
    print("=" * 64)
    print(f"  players       : {m['n_players']}")
    print(f"  basis_season  : {m['basis_season']} (prev-basis: {m['is_prev_season_basis']})")
    print(f"  label         : {m['basis_label']}")
    print(f"  out           : {LEADERS_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
