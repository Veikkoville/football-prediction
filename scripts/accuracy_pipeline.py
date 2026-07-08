"""Tarkkuus-track-record -putki (#100) — ajastettu LOKAALISTI (Task Scheduler).

Kolme vaihetta, kaikki idempotentteja:

  seed       Siemennä prediction-log WC-hubin (world-cup-2026-predictions.html)
             julkaistuista pre-match-kutsuista (40 ottelua = WC-hubin 21/40).
             Aja kerran — uudet rivit lisätään vain jos puuttuvat.
  log        Logaa mallin pre-match-ennuste tuleville OIKEILLE WC-otteluille
             (football-data.org SCHEDULED/TIMED, vain ennen kickoffia). Lukitsee
             ennusteen = ei muutu vaikka malli myöhemmin virkistetään.
  reconcile  Hae FT-tulokset (football-data.org FINISHED) ja täytä toteutuneet
             logattuihin ennusteisiin → laske aggregaatti uudelleen.
  run        log + reconcile (oletus päivittäisajoon).
  regrade    Kertaluontoinen #24-integriteettikorjaus: re-gradaa jo
             reconciloidut ottelut 90 min (regularTime) -tuloksella —
             ET/rankkariottelu jonka 90 min oli tasan = 1X2-miss.

Aja repojuuresta:
  python -m scripts.accuracy_pipeline run        # päivittäinen
  python -m scripts.accuracy_pipeline seed       # kertaluontoinen siemennys
  python -m scripts.accuracy_pipeline reconcile

EI auto-pushia eikä auto-deployta — kuten wc_daily_refresh: putki päivittää
data/prediction_log.json + data/accuracy.json, ja Ville pushaa (Render
auto-deployaa mainista → GET /api/accuracy lukee committatun aggregaatin).
"""

from __future__ import annotations

import re
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# repojuuri Python-polkuun (jotta `python -m` + suora ajo molemmat toimivat)
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import config
from src.models import accuracy as acc

WC_HUB_HTML = ROOT / "world-cup-2026-predictions.html"
WC_COMPETITION_CODE = "WC"
WC_SEASON = "2026"


# ---------------------------------------------------------------------------
# SEED — WC-hubin julkaistut pre-match-kutsut
# ---------------------------------------------------------------------------
# Track-record-taulun rivi:
#   <td class="match">Home – Away</td><td>Pick</td>
#   <td class="num">Win%</td><td class="num">H–A</td> ...
_SEED_ROW = re.compile(
    r'<td class="match">([^<]+?)\s*[–-]\s*([^<]+?)</td>'
    r'\s*<td>([^<]+?)</td>'
    r'\s*<td class="num">([\d.]+)</td>'
    r'\s*<td class="num">(\d+)\s*[–-]\s*(\d+)</td>',
)


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def parse_seed_rows(html: str) -> list[dict]:
    """Pura track-record-taulun rivit hub-HTML:stä → seed-ennusteet."""
    rows = []
    for i, m in enumerate(_SEED_ROW.finditer(html)):
        home, away, pick, win_pct, hs, as_ = (g.strip() for g in m.groups())
        win = round(float(win_pct) / 100.0, 4)
        if pick == home:
            winner, p_home, p_away = "home", win, None
        elif pick == away:
            winner, p_home, p_away = "away", None, win
        else:
            # Pick ei täsmää kumpaankaan (ei pitäisi tapahtua) — ohita rivi
            continue
        rows.append({
            "match_id": f"seed-{i:03d}-{_slug(home)}-{_slug(away)}",
            "source": "wc_hub_seed",
            "competition": "WC",
            "date": None,  # hubissa ei per-ottelu-päivää; seed = vanhin kohortti
            "home_team": home,
            "away_team": away,
            "p_home": p_home,
            "p_draw": None,
            "p_away": p_away,
            "xg_home": None,
            "xg_away": None,
            "most_likely_score": None,
            "predicted_winner": winner,
            "logged_at": None,
            "result": None,
            "_seed_score": (int(hs), int(as_)),
        })
    return rows


def cmd_seed(log: dict) -> int:
    if not WC_HUB_HTML.exists():
        print(f"VIRHE: {WC_HUB_HTML.name} puuttuu — ei voi siementää.")
        return 2
    html = WC_HUB_HTML.read_text(encoding="utf-8")
    seed_rows = parse_seed_rows(html)
    if not seed_rows:
        print("VIRHE: track-record-taulusta ei löytynyt rivejä (regex ei osunut).")
        return 2

    added = 0
    for r in seed_rows:
        hs, as_ = r.pop("_seed_score")
        if acc.upsert_prediction(log, r):
            acc.set_result(log, r["match_id"], hs, as_)
            added += 1
    print(f"SEED: {added} uutta riviä (taulussa {len(seed_rows)}, "
          f"logissa nyt {len(log['predictions'])}).")
    return 0


# ---------------------------------------------------------------------------
# football-data.org -haku (WC-ottelut)
# ---------------------------------------------------------------------------
def _fetch_wc_matches() -> list[dict] | None:
    """Hae kaikki WC2026-ottelut (yksi pyyntö). None jos avain puuttuu/virhe."""
    import requests
    from src.data.football_data_org import _api_key, BASE, _await_rate_limit

    api_key = _api_key()
    if not api_key:
        print("VAROITUS: FOOTBALL_DATA_API_KEY puuttuu — ohitetaan FD-haku.")
        return None
    _await_rate_limit()
    url = f"{BASE}/competitions/{WC_COMPETITION_CODE}/matches?season={WC_SEASON}"
    try:
        r = requests.get(url, headers={"X-Auth-Token": api_key}, timeout=20)
    except Exception as e:
        print(f"VAROITUS: FD-haku epäonnistui: {type(e).__name__}: {e}")
        return None
    if r.status_code != 200:
        print(f"VAROITUS: FD palautti {r.status_code}: {r.text[:160]}")
        return None
    return r.json().get("matches", [])


def _disp_score(m: dict) -> tuple[int, int] | None:
    """NÄYTETTÄVÄ FT-tulos ilman rangaistuspotkuja (reg + jatkoaika).

    HUOM: tämä on näyttötulos, EI gradaustulos — 1X2-gradaus nojaa 90 min
    regularTime-tulokseen (_regular_score), koska malli ennustaa 90 min 1X2:n.
    """
    score = m.get("score") or {}
    ft = score.get("fullTime") or {}
    h, a = ft.get("home"), ft.get("away")
    if h is None or a is None:
        return None
    if score.get("duration") == "PENALTY_SHOOTOUT" and score.get("regularTime"):
        reg = score.get("regularTime") or {}
        et = score.get("extraTime") or {}
        h = int(reg.get("home", h)) + int(et.get("home", 0) or 0)
        a = int(reg.get("away", a)) + int(et.get("away", 0) or 0)
    return int(h), int(a)


def _regular_score(m: dict) -> tuple[int, int] | None:
    """90 min (score.regularTime) -tulos gradausta varten. None jos puuttuu."""
    reg = (m.get("score") or {}).get("regularTime") or {}
    h, a = reg.get("home"), reg.get("away")
    if h is None or a is None:
        return None
    return int(h), int(a)


def _grading_kwargs(m: dict, mid: str) -> dict:
    """duration + 90 min -tulos set_result/regrade_resultille (#24)."""
    duration = (m.get("score") or {}).get("duration") or "REGULAR"
    if duration == "REGULAR":
        return {}
    reg = _regular_score(m)
    if reg is None:
        # football-data ei tarjonnut regularTimea → gradataan näyttötuloksella,
        # mutta EI hiljaa: tämä inflatoisi ET-voitot takaisin osumiksi.
        print(f"VAROITUS: {mid} duration={duration} mutta regularTime puuttuu "
              f"— gradataan näyttötuloksella (tarkista käsin).")
        return {"duration": duration}
    return {"duration": duration, "regular_home": reg[0], "regular_away": reg[1]}


def cmd_log(log: dict, matches: list[dict] | None) -> int:
    """Logaa pre-match-ennuste tuleville WC-otteluille (vain ennen kickoffia)."""
    if matches is None:
        return 0
    now = datetime.now(timezone.utc)
    added = 0
    skipped_no_pred = 0
    for m in matches:
        if m.get("status") not in ("SCHEDULED", "TIMED"):
            continue
        home = (m.get("homeTeam") or {}).get("name")
        away = (m.get("awayTeam") or {}).get("name")
        if not home or not away:
            continue  # vastustaja ei vielä ratkennut (knockout-bracket)
        utc = m.get("utcDate") or ""
        try:
            kickoff = datetime.fromisoformat(utc.replace("Z", "+00:00"))
        except Exception:
            continue
        if kickoff <= now:
            continue  # ei enää pre-match → ei logata jälkikäteen
        match_id = f"fd-{m.get('id')}"
        if match_id in {e["match_id"] for e in log["predictions"]}:
            continue
        pred = acc.wc_prematch_prediction(home, away)
        if pred is None:
            skipped_no_pred += 1
            continue
        entry = {
            "match_id": match_id,
            "source": "fd",
            "competition": "WC",
            "date": utc[:10],
            "kickoff": utc,
            "home_team": pred["home_team"],
            "away_team": pred["away_team"],
            "p_home": pred["p_home"],
            "p_draw": pred["p_draw"],
            "p_away": pred["p_away"],
            "xg_home": pred["xg_home"],
            "xg_away": pred["xg_away"],
            "most_likely_score": pred["most_likely_score"],
            "predicted_winner": pred["predicted_winner"],
            "logged_at": acc._now_iso(),
            "result": None,
        }
        if acc.upsert_prediction(log, entry):
            added += 1
    msg = f"LOG: {added} uutta pre-match-ennustetta"
    if skipped_no_pred:
        msg += f" ({skipped_no_pred} ohitettu — ei mallidataa)"
    print(msg + ".")
    return 0


def cmd_reconcile(log: dict, matches: list[dict] | None) -> int:
    """Hae FT-tulokset ja täytä toteutuneet logattuihin ennusteisiin."""
    if matches is None:
        return 0
    by_id = {m.get("id"): m for m in matches}
    reconciled = 0
    for e in log["predictions"]:
        if e.get("result") is not None:
            continue
        mid = e.get("match_id", "")
        if not mid.startswith("fd-"):
            continue
        try:
            fd_id = int(mid[3:])
        except ValueError:
            continue
        m = by_id.get(fd_id)
        if not m or m.get("status") != "FINISHED":
            continue
        disp = _disp_score(m)
        if disp is None:
            continue
        if acc.set_result(log, mid, disp[0], disp[1], **_grading_kwargs(m, mid)):
            reconciled += 1
    print(f"RECONCILE: {reconciled} ottelua täytetty FT-tuloksella.")
    return 0


def cmd_regrade(log: dict, matches: list[dict] | None) -> int:
    """Re-gradaa KAIKKI jo reconciloidut fd-ottelut 90 min -gradauksella (#24).

    Kertaluontoinen integriteettikorjaus: ET-voitot gradattiin aiemmin
    fullTime-tuloksella (jatkoajan maalit mukana) → 90 min tasan + ET-voitto
    näkyi 1X2-osumana. Union-turvallinen: rivejä ei poisteta eikä ennusteisiin
    kosketa — vain result-lohkon gradauskentät päivittyvät (n ei muutu).
    """
    if matches is None:
        print("VIRHE: FD-haku epäonnistui — regrade vaatii ottelu-datan.")
        return 2
    by_id = {m.get("id"): m for m in matches}
    n_before = len(log["predictions"])
    checked = changed = 0
    flips = []
    for e in log["predictions"]:
        if not e.get("result") or not e.get("match_id", "").startswith("fd-"):
            continue
        try:
            m = by_id.get(int(e["match_id"][3:]))
        except ValueError:
            continue
        if not m or m.get("status") != "FINISHED":
            continue
        disp = _disp_score(m)
        if disp is None:
            continue
        checked += 1
        old_hit = e["result"]["hit_1x2"]
        if acc.regrade_result(log, e["match_id"], disp[0], disp[1],
                              **_grading_kwargs(m, e["match_id"])):
            changed += 1
            if e["result"]["hit_1x2"] != old_hit:
                flips.append(
                    f"  {e.get('date')} {e['home_team']}-{e['away_team']}: "
                    f"90min {e['result'].get('regular_score')}, "
                    f"lopputulos {e['result']['actual_score']} "
                    f"({e['result'].get('duration')}), "
                    f"hit_1x2 {old_hit} -> {e['result']['hit_1x2']}"
                )
    assert len(log["predictions"]) == n_before, "regrade ei saa pudottaa rivejä"
    print(f"REGRADE: {checked} tarkistettu, {changed} result-lohkoa päivittyi, "
          f"{len(flips)} 1X2-gradausta kääntyi.")
    for line in flips:
        print(line)
    return 0


def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else "run"
    if cmd not in ("seed", "log", "reconcile", "run", "regrade"):
        print(f"Tuntematon komento '{cmd}'. Käytä: seed | log | reconcile | run | regrade")
        return 2

    log = acc.load_log()
    rc = 0
    matches = None

    if cmd == "seed":
        rc = cmd_seed(log)
    else:
        if cmd in ("log", "reconcile", "run", "regrade"):
            matches = _fetch_wc_matches()
        if cmd in ("log", "run"):
            cmd_log(log, matches)
        if cmd in ("reconcile", "run"):
            cmd_reconcile(log, matches)
        if cmd == "regrade":
            rc = cmd_regrade(log, matches)

    acc.save_log(log)
    agg = acc.recompute_and_save(log)
    at = agg["all_time"]
    print(
        f"AGG: n={at['n']} | 1X2 {at['pct_1x2']} ({at['correct_1x2']}/{at['n']}) | "
        f"decisive {at['pct_decisive']} ({at['decisive_correct']}/{at['decisive_n']}) | "
        f"exact {at['pct_exact']} ({at['exact_correct']}/{at['exact_n']}) | "
        f"brier {at['brier']} (n={at['brier_n']}) | pending {agg['pending']}"
    )
    print(f"Kirjoitettu: {acc.LOG_PATH.name} + {acc.AGGREGATE_PATH.name} "
          f"(data/). Push = Villen manuaalinen päätös (ei auto-deployta).")
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv))
