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
  regrade    Re-gradaa jo reconciloidut ottelut nykyisellä normilla.
             Gradausnormi = FT-AET (Villen päätös 20.7): virallinen
             lopputulos jatkoajan jälkeen; rankkarikisa = tasapeli.

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
# #110: domestic-kilpailut — track record ei jäädy WC-finaaliin 19.7.
# ---------------------------------------------------------------------------
# fd = football-data.org-koodi, league = mallin liigakoodi (/api/predict +
# /api/teams). overrides = FD-nimi → mallinimi niille joille normalisointi ei
# riitä (verifioitu live-/api/teams- ja live-FD-fixture-listoja vasten 17.7).
#
# LIVE-LOGAUS ON OPT-IN: ympäristömuuttuja ACC_DOMESTIC_COMPETITIONS
# (pilkkulista FD-koodeja, esim. "BSA" tai "BSA,PL"). Tyhjä/puuttuva → domestic
# EI logaa mitään (WC-putki bittitarkasti ennallaan). 🔒 GO = Ville asettaa
# muuttujan workflowiin/repo-variableen → 1. live-domestic-logi käynnistyy.
DOMESTIC_COMPETITIONS: dict[str, dict] = {
    "BSA": {
        "league": "BRA-Serie A",
        "overrides": {
            "CA Mineiro": "Atletico-MG",
            "CA Paranaense": "Athletico-PR",
            "Botafogo FR": "Botafogo RJ",
            "CR Vasco da Gama": "Vasco",
            "Sport Club do Recife": "Sport Recife",
            "Sport Recife": "Sport Recife",
            "EC Juventude": "Juventude",
            "Ceará SC": "Ceara",
            "Ceara SC": "Ceara",
        },
    },
    # Big-5 + CL: kaudet alkavat elokuussa — off-season-haku palauttaa tyhjää
    # (halpa no-op). Overridet täydennetään kun 1. kausikierros on FD:ssä.
    "PL":  {"league": "ENG-Premier League", "overrides": {
        "Wolverhampton Wanderers FC": "Wolverhampton Wanderers",
    }},
    "PD":  {"league": "ESP-La Liga-FD", "overrides": {}},
    "BL1": {"league": "GER-Bundesliga-FD", "overrides": {}},
    "SA":  {"league": "ITA-Serie A-FD", "overrides": {}},
    "FL1": {"league": "FRA-Ligue 1-FD", "overrides": {}},
    "CL":  {"league": "INT-Champions League", "overrides": {}},
}

# Live-API jonka julkaistua ennustetta logataan (= sama malli jonka käyttäjät
# näkevät — rehellisin mahdollinen pre-match-lähde). Ylikirjoitettavissa
# testeihin/lokaaliin ympäristömuuttujalla.
import os
PREDICT_API_BASE = os.environ.get(
    "ACC_PREDICT_API_BASE", "https://goaliq-api.onrender.com"
)


def enabled_domestic_codes() -> list[str]:
    """FD-koodit joille domestic-logaus on kytketty (ACC_DOMESTIC_COMPETITIONS).

    Tuntemattomat koodit ohitetaan varoituksella — kirjoitusvirhe muuttujassa
    ei saa kaataa WC-putkea.
    """
    raw = os.environ.get("ACC_DOMESTIC_COMPETITIONS", "")
    codes = []
    for c in (s.strip().upper() for s in raw.split(",")):
        if not c:
            continue
        if c not in DOMESTIC_COMPETITIONS:
            print(f"VAROITUS: tuntematon domestic-koodi '{c}' — ohitetaan.")
            continue
        codes.append(c)
    return codes


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
# football-data.org -haku (yleinen; WC + domestic-kilpailut, #110)
# ---------------------------------------------------------------------------
def _fetch_matches(comp_code: str, season: str | None = None) -> list[dict] | None:
    """Hae kilpailun ottelut (yksi pyyntö). None jos avain puuttuu/virhe.

    season=None → FD palauttaa kuluvan kauden (domestic-oletus). WC käyttää
    kiinteää season=2026.
    """
    import requests
    from src.data.football_data_org import _api_key, BASE, _await_rate_limit

    api_key = _api_key()
    if not api_key:
        print("VAROITUS: FOOTBALL_DATA_API_KEY puuttuu — ohitetaan FD-haku.")
        return None
    _await_rate_limit()
    url = f"{BASE}/competitions/{comp_code}/matches"
    if season:
        url += f"?season={season}"
    try:
        r = requests.get(url, headers={"X-Auth-Token": api_key}, timeout=20)
    except Exception as e:
        print(f"VAROITUS: FD-haku ({comp_code}) epäonnistui: {type(e).__name__}: {e}")
        return None
    if r.status_code != 200:
        print(f"VAROITUS: FD ({comp_code}) palautti {r.status_code}: {r.text[:160]}")
        return None
    return r.json().get("matches", [])


def _fetch_wc_matches() -> list[dict] | None:
    """Hae kaikki WC2026-ottelut (säilytetty wrapperina — kutsujat + testit)."""
    return _fetch_matches(WC_COMPETITION_CODE, WC_SEASON)


# ---------------------------------------------------------------------------
# #110: FD-nimi → mallinimi -resolveri + live-API-ennuste (domestic)
# ---------------------------------------------------------------------------
# FD käyttää virallisia klubinimiä ("SE Palmeiras", "CA Mineiro"); malli
# käyttää datalähteen lyhytnimiä ("Palmeiras", "Atletico-MG"). Resolvointi:
# 1) eksplisiittinen override, 2) normalisoitu vertailu (aksentit pois,
# klubimuoto-tokenit pois), 3) token-osajoukko. Ei osumaa → None (kutsuja
# skippaa varoituksella — rehellinen fail-open, ei arvauksia).
_CLUB_TOKENS = frozenset({
    "fc", "cf", "ec", "sc", "cr", "ca", "se", "af", "ac", "as", "ss", "rc",
    "rcd", "cd", "ud", "fbc", "fbpa", "fr", "afc", "bc", "clube", "club",
    "de", "do", "da", "e", "regatas", "esporte", "futebol",
})


def _normalize_team(name: str) -> str:
    """Pieniksi, aksentit pois, klubimuoto-tokenit pois, aakkosnumeeriseksi."""
    import unicodedata
    s = unicodedata.normalize("NFKD", name)
    s = "".join(ch for ch in s if not unicodedata.combining(ch)).lower()
    tokens = [t for t in re.split(r"[^a-z0-9]+", s) if t and t not in _CLUB_TOKENS]
    return " ".join(tokens)


def resolve_domestic_name(
    fd_name: str, model_teams: list[str], overrides: dict[str, str]
) -> str | None:
    """FD-ottelunimi → mallin joukkuenimi (tai None jos ei varmaa osumaa)."""
    if fd_name in overrides:
        ov = overrides[fd_name]
        return ov if ov in model_teams else None
    norm_fd = _normalize_team(fd_name)
    if not norm_fd:
        return None
    by_norm = {_normalize_team(t): t for t in model_teams}
    if norm_fd in by_norm:
        return by_norm[norm_fd]
    # Token-osajoukko: "sao paulo" ⊆ "sao paulo" jne. Hyväksy vain YKSI ehdokas
    # (moniselitteinen → None, ei arvata).
    fd_tokens = set(norm_fd.split())
    candidates = [
        t for n, t in by_norm.items()
        if fd_tokens and (fd_tokens <= set(n.split()) or set(n.split()) <= fd_tokens)
    ]
    return candidates[0] if len(candidates) == 1 else None


def _fetch_model_teams(league: str) -> list[str] | None:
    """Mallin joukkuenimet liigalle live-API:sta (/api/teams). None jos virhe."""
    import requests
    try:
        r = requests.get(
            f"{PREDICT_API_BASE}/api/teams",
            params={"leagues": league},
            timeout=120,  # kylmä Render voi fitata mallin tässä
        )
    except Exception as e:
        print(f"VAROITUS: /api/teams ({league}) epäonnistui: {type(e).__name__}: {e}")
        return None
    if r.status_code != 200:
        print(f"VAROITUS: /api/teams ({league}) palautti {r.status_code}.")
        return None
    teams = r.json().get("teams") or []
    return list(teams) if teams else None


def domestic_prematch_prediction(
    league: str, home_model: str, away_model: str
) -> dict | None:
    """Logattava pre-match-ennuste LIVE-API:sta (/api/predict) — täsmälleen
    sama julkaistu malli jonka käyttäjät näkevät. None jos kutsu epäonnistuu."""
    import requests
    try:
        r = requests.post(
            f"{PREDICT_API_BASE}/api/predict",
            json={"home_team": home_model, "away_team": away_model,
                  "leagues": [league]},
            timeout=120,
        )
    except Exception as e:
        print(f"VAROITUS: /api/predict ({home_model}-{away_model}) epäonnistui: "
              f"{type(e).__name__}: {e}")
        return None
    if r.status_code != 200:
        print(f"VAROITUS: /api/predict ({home_model}-{away_model}) → {r.status_code}.")
        return None
    d = r.json()
    top = d.get("top_scores") or []
    return {
        "home_team": home_model,
        "away_team": away_model,
        "p_home": round(float(d["p_home_win"]), 4),
        "p_draw": round(float(d["p_draw"]), 4),
        "p_away": round(float(d["p_away_win"]), 4),
        "xg_home": round(float(d["expected_goals_home"]), 3),
        "xg_away": round(float(d["expected_goals_away"]), 3),
        "most_likely_score": (top[0].get("score") if top else None),
        "predicted_winner": acc.named_winner(d["p_home_win"], d["p_away_win"]),
    }


def log_domestic_matches(
    log: dict,
    comp_code: str,
    matches: list[dict],
    model_teams: list[str],
    predict_fn,
    now: datetime | None = None,
) -> tuple[int, int]:
    """Logaa pre-match-ennusteet yhden domestic-kilpailun tuleville otteluille.

    Sama pre-match-kuri kuin WC:llä: vain SCHEDULED/TIMED + kickoff > now,
    jo logattuja ei ylikirjoiteta (upsert). predict_fn injektoidaan → testit
    ajavat ilman verkkoa. Palauttaa (lisätyt, ohitetut-ilman-ennustetta).
    """
    cfg = DOMESTIC_COMPETITIONS[comp_code]
    overrides = cfg.get("overrides", {})
    now = now or datetime.now(timezone.utc)
    existing = {e["match_id"] for e in log["predictions"]}
    added = skipped = 0
    for m in matches:
        if m.get("status") not in ("SCHEDULED", "TIMED"):
            continue
        fd_home = (m.get("homeTeam") or {}).get("name")
        fd_away = (m.get("awayTeam") or {}).get("name")
        if not fd_home or not fd_away:
            continue
        utc = m.get("utcDate") or ""
        try:
            kickoff = datetime.fromisoformat(utc.replace("Z", "+00:00"))
        except Exception:
            continue
        if kickoff <= now:
            continue  # ei enää pre-match → ei logata jälkikäteen
        match_id = f"fd-{m.get('id')}"
        if match_id in existing:
            continue
        home = resolve_domestic_name(fd_home, model_teams, overrides)
        away = resolve_domestic_name(fd_away, model_teams, overrides)
        if home is None or away is None:
            miss = fd_home if home is None else fd_away
            print(f"VAROITUS: {comp_code} nimi ei resolvoidu malliin: '{miss}' "
                  f"({fd_home} - {fd_away}) — ohitetaan.")
            skipped += 1
            continue
        pred = predict_fn(cfg["league"], home, away)
        if pred is None:
            skipped += 1
            continue
        entry = {
            "match_id": match_id,
            "source": "fd",
            "competition": comp_code,
            "league": cfg["league"],
            "date": utc[:10],
            "kickoff": utc,
            **{k: pred[k] for k in (
                "home_team", "away_team", "p_home", "p_draw", "p_away",
                "xg_home", "xg_away", "most_likely_score", "predicted_winner",
            )},
            "logged_at": acc._now_iso(),
            "result": None,
        }
        if acc.upsert_prediction(log, entry):
            existing.add(match_id)
            added += 1
    print(f"LOG[{comp_code}]: {added} uutta pre-match-ennustetta"
          + (f" ({skipped} ohitettu)." if skipped else "."))
    return added, skipped


def _disp_score(m: dict) -> tuple[int, int] | None:
    """Virallinen FT-AET-tulos ilman rangaistuspotkuja (reg + jatkoaika).

    FT-AET-normi (20.7): tämä on myös GRADAUSTULOS — 1X2/exact gradataan
    virallisella lopputuloksella. 90 min regularTime (_regular_score) menee
    vain näyttöannotaatioon ("1-0 (a.e.t.)").
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
    """90 min (score.regularTime) -tulos näyttöannotaatioon. None jos puuttuu."""
    reg = (m.get("score") or {}).get("regularTime") or {}
    h, a = reg.get("home"), reg.get("away")
    if h is None or a is None:
        return None
    return int(h), int(a)


def _grading_kwargs(m: dict, mid: str) -> dict:
    """duration + 90 min -annotaatiotulos set_result/regrade_resultille."""
    duration = (m.get("score") or {}).get("duration") or "REGULAR"
    if duration == "REGULAR":
        return {}
    reg = _regular_score(m)
    if reg is None:
        # football-data ei tarjonnut regularTimea → duration-lippu kirjataan
        # ilman 90 min -annotaatiota (gradaus nojaa joka tapauksessa FT-AET:iin).
        print(f"VAROITUS: {mid} duration={duration} mutta regularTime puuttuu "
              f"— 90 min -annotaatio jää pois.")
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
    """Re-gradaa KAIKKI jo reconciloidut fd-ottelut nykyisellä normilla.

    #24 ajoi tämän 90 min -normiin; 20.7 normi vaihdettiin FT-AET:iin (Villen
    päätös) ja sama komento ajaa siirtymän. Union-turvallinen: rivejä ei
    poisteta eikä ennusteisiin kosketa — vain result-lohkon gradauskentät
    päivittyvät (n ei muutu).
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
        domestic: dict[str, list[dict]] = {}
        if cmd in ("log", "reconcile", "run", "regrade"):
            matches = _fetch_wc_matches()
            # #110: domestic-kilpailut vain opt-in-lipulla (🔒 GO-portti).
            # Tyhjä lippu → tämä lohko ei aja → WC-putki bittitarkasti ennallaan.
            if cmd != "regrade":
                for code in enabled_domestic_codes():
                    dm = _fetch_matches(code)
                    if dm is not None:
                        domestic[code] = dm
        if cmd in ("log", "run"):
            cmd_log(log, matches)
            for code, dm in domestic.items():
                teams = _fetch_model_teams(DOMESTIC_COMPETITIONS[code]["league"])
                if teams is None:
                    print(f"VAROITUS: {code} ohitettu — mallin joukkuelista ei "
                          f"saatavilla (/api/teams).")
                    continue
                log_domestic_matches(
                    log, code, dm, teams, domestic_prematch_prediction
                )
        if cmd in ("reconcile", "run"):
            # Yhdistetty lista: FD:n ottelu-id:t ovat globaalisti uniikkeja →
            # sama fd-<id>-avain toimii kaikille kilpailuille.
            combined: list[dict] | None
            if matches is None and not domestic:
                combined = None
            else:
                combined = list(matches or [])
                for dm in domestic.values():
                    combined.extend(dm)
            cmd_reconcile(log, combined)
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
