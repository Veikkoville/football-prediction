"""#34 Rate my team — FPL-joukkueen tuonti + xP-pohjainen tiimiarvio.

Käyttäjän FPL-joukkue haetaan JULKISELLA entry-ID:llä (ei kirjautumista, ei
salasanoja — IP/turva). Jokaiseen pelaajaan liitetään committattu xP-projektio
(data/fpl_xp_projections.json, #33 predicted-minutes mukana) → tiimiarvio
(percentiili vs satunnaisotos laillisia budjettijoukkueita) + kapteeni- ja
siirtosuositukset (laillisuus + budjetti kunnioittaen, "hold" jos paras delta
alle kynnyksen — ei yli-ehdoteta siirtoja).

Esikausihuomio: FPL-API:n bootstrap on kesällä vielä edellisen kauden tilassa
→ entry-tuonti palauttaa viimeksi pelatun GW:n joukkueen (element-ID:t ovat
samat kuin projektioissa, jotka on rakennettu samasta bootstrapista). Ennen
GW1-deadlinea frontend voi vaihtoehtoisesti syöttää 15 pelaaja-ID:tä käsin
(players-parametri) — sama arviointipolku, ei FPL-hakua.

Ei kirjoita mitään; /api/fantasy/xp-polku (load_xp) jää bittitarkasti
koskemattomaksi — tämä moduuli vain LUKEE saman projektion.
"""
from __future__ import annotations

import random
import threading
import time

import requests

from src.models.fpl_xp import load_xp

FPL_BASE = "https://fantasy.premierleague.com/api"
FPL_TIMEOUT_SEC = 15
CACHE_TTL_SEC = 600  # 10 min — promptin vaatimus; FPL-data muuttuu hitaasti

# FPL element_type → positio; kiintiöt 15 pelaajan rungolle ja XI:lle.
POS_NAME = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}
SQUAD_QUOTA = {1: 2, 2: 5, 3: 5, 4: 3}
XI_MIN = {1: 1, 2: 3, 3: 2, 4: 1}
XI_MAX = {1: 1, 2: 5, 3: 5, 4: 3}
MAX_PER_CLUB = 3
BUDGET_TENTHS = 1000  # 100.0 m — satunnaisotoksen budjettiraja

# "Hold"-kynnys: paras yksittäisen siirron horisontti-xP-delta alle tämän →
# suositus on pitää joukkue (siirto ei ole hitin arvoinen; -4 p ≈ 2 GW:n etu).
HOLD_THRESHOLD_XP = 2.0
# Kapteenivaihtoehto näytetään jos ero kärkeen on alle tämän (GW-xP).
CAPTAIN_ALT_MARGIN_XP = 0.5

RATING_SAMPLE_N = 300
RATING_SEED = 1926  # deterministinen otos → testattava + vakaa vastausten yli


class RateTeamError(Exception):
    """Virhe jolle on selkeä HTTP-status + käyttäjäluettava viesti."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


# ---------------------------------------------------------------------------
# FPL-haku + 10 min TTL-cache (jaettu prosessin sisällä, thread-safe)
# ---------------------------------------------------------------------------

_FPL_CACHE: dict[str, tuple[float, dict]] = {}
_FPL_CACHE_LOCK = threading.Lock()


def _fetch_fpl(path: str) -> dict:
    now = time.time()
    with _FPL_CACHE_LOCK:
        hit = _FPL_CACHE.get(path)
        if hit and now - hit[0] < CACHE_TTL_SEC:
            return hit[1]
    try:
        r = requests.get(f"{FPL_BASE}{path}", timeout=FPL_TIMEOUT_SEC,
                         headers={"User-Agent": "GoalIQ/1.0"})
    except requests.RequestException as e:
        raise RateTeamError(
            503, "FPL API is not responding right now. Try again in a moment."
        ) from e
    if r.status_code == 404:
        raise RateTeamError(404, "Not found on the FPL API.")
    if r.status_code != 200:
        raise RateTeamError(
            503, f"FPL API returned an unexpected status ({r.status_code})."
        )
    data = r.json()
    with _FPL_CACHE_LOCK:
        _FPL_CACHE[path] = (now, data)
    return data


def get_bootstrap() -> dict:
    return _fetch_fpl("/bootstrap-static/")


def _resolve_gw(bootstrap: dict, gw: int | None) -> int:
    if gw is not None:
        if not 1 <= gw <= 38:
            raise RateTeamError(400, "gw must be between 1 and 38.")
        return gw
    events = bootstrap.get("events") or []
    current = [e["id"] for e in events if e.get("is_current")]
    if current:
        return current[0]
    nxt = [e["id"] for e in events if e.get("is_next")]
    if nxt:
        return nxt[0]
    raise RateTeamError(503, "FPL API has no current gameweek yet.")


def get_entry_picks(entry_id: int, gw: int) -> dict:
    """Hae entryn picks; erotellaan 'entry ei ole olemassa' vs 'picks puuttuu'."""
    try:
        _fetch_fpl(f"/entry/{entry_id}/")
    except RateTeamError as e:
        if e.status_code == 404:
            raise RateTeamError(
                404, f"FPL entry {entry_id} was not found. Check the ID "
                     "(it is the number in your FPL points-page URL).")
        raise
    try:
        return _fetch_fpl(f"/entry/{entry_id}/event/{gw}/picks/")
    except RateTeamError as e:
        if e.status_code == 404:
            raise RateTeamError(
                404, f"No picks found for entry {entry_id} in GW{gw}. Before "
                     "the season starts you can enter your 15 player IDs "
                     "manually instead.")
        raise


# ---------------------------------------------------------------------------
# XI-valinta + arvio
# ---------------------------------------------------------------------------

def optimal_xi(squad: list[dict]) -> list[dict]:
    """Paras laillinen XI horisontti-xP:llä: käy kaikki muodostelmat läpi ja
    poimi per positio parhaat (per-positio-valinta on riippumaton → tarkka)."""
    by_pos: dict[int, list[dict]] = {1: [], 2: [], 3: [], 4: []}
    for p in squad:
        by_pos[p["element_type"]].append(p)
    for lst in by_pos.values():
        lst.sort(key=lambda p: p["xp_horizon_total"], reverse=True)

    best: tuple[float, list[dict]] | None = None
    for n_def in range(XI_MIN[2], XI_MAX[2] + 1):
        for n_mid in range(XI_MIN[3], XI_MAX[3] + 1):
            n_fwd = 11 - 1 - n_def - n_mid
            if not XI_MIN[4] <= n_fwd <= XI_MAX[4]:
                continue
            counts = {1: 1, 2: n_def, 3: n_mid, 4: n_fwd}
            if any(len(by_pos[t]) < n for t, n in counts.items()):
                continue
            xi = [p for t, n in counts.items() for p in by_pos[t][:n]]
            total = sum(p["xp_horizon_total"] for p in xi)
            if best is None or total > best[0]:
                best = (total, xi)
    if best is None:
        raise RateTeamError(
            400, "Squad cannot form a legal XI (need 1 GKP, 3+ DEF, 2+ MID, "
                 "1+ FWD from 15 players).")
    return best[1]


def _squad_clubs_ok(squad: list[dict]) -> bool:
    counts: dict[int, int] = {}
    for p in squad:
        counts[p["club"]] = counts.get(p["club"], 0) + 1
    return all(c <= MAX_PER_CLUB for c in counts.values())


_RATING_DIST_CACHE: dict[str, list[float]] = {}


def rating_distribution(pool: list[dict], cache_key: str) -> list[float]:
    """Vertailujakauma: RATING_SAMPLE_N satunnaista laillista budjettijoukkuetta
    (kiintiöt + max 3/klubi + ≤100.0m) projektiopoolista, kunkin optimaalisen
    XI:n horisontti-xP. Deterministinen (kiinteä seed) → vakaa + testattava.
    Pooli = projektiopelaajat (343 relevanttia) → 'kohtuullinen vertailujoukko'."""
    hit = _RATING_DIST_CACHE.get(cache_key)
    if hit is not None:
        return hit
    rng = random.Random(RATING_SEED)
    by_pos: dict[int, list[dict]] = {1: [], 2: [], 3: [], 4: []}
    for p in pool:
        by_pos[p["element_type"]].append(p)
    totals: list[float] = []
    attempts = 0
    while len(totals) < RATING_SAMPLE_N and attempts < RATING_SAMPLE_N * 50:
        attempts += 1
        squad: list[dict] = []
        for t, n in SQUAD_QUOTA.items():
            if len(by_pos[t]) < n:
                break
            squad.extend(rng.sample(by_pos[t], n))
        if len(squad) != 15:
            break
        if not _squad_clubs_ok(squad):
            continue
        if sum(p["price"] for p in squad) > BUDGET_TENTHS:
            continue
        totals.append(sum(p["xp_horizon_total"] for p in optimal_xi(squad)))
    totals.sort()
    _RATING_DIST_CACHE[cache_key] = totals
    return totals


def _percentile(value: float, dist: list[float]) -> float:
    if not dist:
        return 50.0
    below = sum(1 for x in dist if x < value)
    return round(100.0 * below / len(dist), 1)


def _line_strength(xi: list[dict], pool: list[dict]) -> tuple[str, str]:
    """Vahvin/heikoin rivi: XI:n rivin keski-xP/GW suhteessa poolin saman
    position keskiarvoon (suhde > 1 = rivi on poolikeskiarvoa vahvempi)."""
    pool_avg: dict[int, float] = {}
    for t in POS_NAME:
        vals = [p["xp_per_gw"] for p in pool if p["element_type"] == t]
        pool_avg[t] = sum(vals) / len(vals) if vals else 0.0
    ratios: dict[str, float] = {}
    for t, name in POS_NAME.items():
        vals = [p["xp_per_gw"] for p in xi if p["element_type"] == t]
        if vals and pool_avg[t] > 0:
            ratios[name] = (sum(vals) / len(vals)) / pool_avg[t]
    if not ratios:
        return "", ""
    strongest = max(ratios, key=ratios.get)
    weakest = min(ratios, key=ratios.get)
    return strongest, weakest


# ---------------------------------------------------------------------------
# Suositukset
# ---------------------------------------------------------------------------

def _gw_xp(player: dict, gw: int) -> float:
    for g in player.get("gameweeks") or []:
        if g.get("gw") == gw:
            return float(g.get("xp") or 0.0)
    return 0.0


def captain_suggestion(xi: list[dict], gw: int) -> dict:
    ranked = sorted(xi, key=lambda p: _gw_xp(p, gw), reverse=True)
    pick = ranked[0]
    out = {"pick": {"id": pick["id"], "web_name": pick["web_name"],
                    "team_short": pick["team_short"],
                    "gw_xp": round(_gw_xp(pick, gw), 2)},
           "alternative": None}
    if len(ranked) > 1:
        alt = ranked[1]
        if _gw_xp(pick, gw) - _gw_xp(alt, gw) < CAPTAIN_ALT_MARGIN_XP:
            out["alternative"] = {"id": alt["id"], "web_name": alt["web_name"],
                                  "team_short": alt["team_short"],
                                  "gw_xp": round(_gw_xp(alt, gw), 2)}
    return out


def transfer_suggestions(squad: list[dict], pool: list[dict],
                         bank_tenths: int) -> dict:
    """Top 3–5 yhden pelaajan siirtoa: sama positio, budjetti (bank + myyntihinta
    = now_cost, MVP-yksinkertaistus), max 3/klubi vaihdon JÄLKEEN, suurin
    horisontti-xP-delta. Deltat ovat per-siirto (eivät summaudu — budjetti
    jaetaan). 'hold' jos paras delta < kynnys."""
    squad_ids = {p["id"] for p in squad}
    club_counts: dict[int, int] = {}
    for p in squad:
        club_counts[p["club"]] = club_counts.get(p["club"], 0) + 1

    suggestions = []
    for out_p in squad:
        budget = bank_tenths + out_p["price"]
        for in_p in pool:
            if in_p["id"] in squad_ids:
                continue
            if in_p["element_type"] != out_p["element_type"]:
                continue
            if in_p["price"] > budget:
                continue
            # klubiraja vaihdon jälkeen
            after = club_counts.get(in_p["club"], 0) + 1
            if in_p["club"] != out_p["club"] and after > MAX_PER_CLUB:
                continue
            delta = in_p["xp_horizon_total"] - out_p["xp_horizon_total"]
            if delta <= 0:
                continue
            suggestions.append({
                "out": {"id": out_p["id"], "web_name": out_p["web_name"],
                        "team_short": out_p["team_short"],
                        "price": out_p["price"] / 10.0},
                "in": {"id": in_p["id"], "web_name": in_p["web_name"],
                       "team_short": in_p["team_short"],
                       "price": in_p["price"] / 10.0},
                "pos": POS_NAME[out_p["element_type"]],
                "delta_xp_horizon": round(delta, 2),
                "delta_cost": round((in_p["price"] - out_p["price"]) / 10.0, 1),
            })
    suggestions.sort(key=lambda s: s["delta_xp_horizon"], reverse=True)
    top = suggestions[:5]
    hold = not top or top[0]["delta_xp_horizon"] < HOLD_THRESHOLD_XP
    return {
        "suggestions": top,
        "hold": hold,
        "note": ("Best available single-transfer gain is small - holding your "
                 "team is a fine play this week." if hold else
                 "Deltas are per single transfer over the projection horizon; "
                 "they do not simply add up (budget is shared)."),
    }


# ---------------------------------------------------------------------------
# Pääorkestrointi
# ---------------------------------------------------------------------------

def _projection_pool(xp_data: dict, price_by_id: dict[int, dict]) -> list[dict]:
    """Yhdistä projektio + bootstrap-hinta/klubi. Pelaaja ilman bootstrap-riviä
    pudotetaan poolista (ei voida hinnoitella siirtoa/otosta)."""
    pool = []
    pos_by_name = {v: k for k, v in POS_NAME.items()}
    for p in xp_data.get("players") or []:
        boot = price_by_id.get(p["id"])
        if not boot:
            continue
        pool.append({
            "id": p["id"], "web_name": p["web_name"],
            "team_short": p.get("team_short") or "",
            "element_type": pos_by_name.get(p.get("pos"), boot["element_type"]),
            "club": boot["team"],
            "price": boot["now_cost"],
            "xp_per_gw": float(p.get("xp_per_gw") or 0.0),
            "xp_horizon_total": float(p.get("xp_horizon_total") or 0.0),
            "gameweeks": p.get("gameweeks") or [],
        })
    return pool


def rate_team(entry: int | None = None, gw: int | None = None,
              players: list[int] | None = None, captain: int | None = None,
              bank: float | None = None) -> dict:
    """Arvioi joukkue. entry-moodi (julkinen FPL-ID) TAI manual-moodi
    (players = 15 element-ID:tä, esikausifallback)."""
    xp_data = load_xp()
    if not xp_data.get("meta", {}).get("available") or not xp_data.get("players"):
        raise RateTeamError(503, "xP projections are not available yet.")

    bootstrap = get_bootstrap()
    price_by_id = {e["id"]: e for e in bootstrap.get("elements") or []}
    pool = _projection_pool(xp_data, price_by_id)
    pool_by_id = {p["id"]: p for p in pool}

    mode = "manual" if players else "entry"
    bank_tenths = int(round((bank or 0.0) * 10))
    captain_id = captain
    missing: list[int] = []

    if mode == "entry":
        if entry is None:
            raise RateTeamError(400, "Provide either entry or players.")
        target_gw = _resolve_gw(bootstrap, gw)
        picks_data = get_entry_picks(entry, target_gw)
        picks = picks_data.get("picks") or []
        if not picks:
            raise RateTeamError(404, f"Entry {entry} has no picks for GW{target_gw}.")
        squad_ids = [pk["element"] for pk in picks]
        cap = [pk["element"] for pk in picks if pk.get("is_captain")]
        captain_id = captain_id or (cap[0] if cap else None)
        if bank is None:
            bank_tenths = int((picks_data.get("entry_history") or {}).get("bank") or 0)
    else:
        if len(players or []) != 15:
            raise RateTeamError(400, "players must list exactly 15 FPL element IDs.")
        if len(set(players)) != 15:
            raise RateTeamError(400, "players contains duplicate IDs.")
        squad_ids = list(players)
        # Manual-moodi: GW = seuraava pelattava (tai annettu)
        target_gw = _resolve_gw(bootstrap, gw)

    # Esikausiclamppi: picks voi tulla viime kauden GW:stä (esim. GW38), mutta
    # projektiot kattavat tulevan horisontin (GW1–6) → xP-laskennan GW on aina
    # projektioiden kattama. picks_gw raportoidaan erikseen metassa.
    picks_gw = target_gw
    covered = {g.get("gw") for p in pool for g in (p.get("gameweeks") or [])}
    if target_gw not in covered:
        target_gw = (xp_data["meta"].get("next_gameweek")
                     or (min(covered) if covered else target_gw))

    squad: list[dict] = []
    for pid in squad_ids:
        p = pool_by_id.get(pid)
        if p:
            squad.append(p)
        else:
            missing.append(pid)
    if len(squad) < 11:
        raise RateTeamError(
            422, "Too few of the squad's players have xP projections "
                 f"({len(squad)}/15 matched). Check the player IDs.")

    xi = optimal_xi(squad) if len(squad) >= 11 else squad
    xi_ids = {p["id"] for p in xi}

    # Kapteeni: annettu/picksistä jos XI:ssä, muuten paras GW-xP
    cap_sugg = captain_suggestion(xi, target_gw)
    effective_captain = (captain_id if captain_id in xi_ids
                         else cap_sugg["pick"]["id"])
    cap_player = pool_by_id[effective_captain]

    team_xp_horizon = sum(p["xp_horizon_total"] for p in xi)
    team_xp_gw = sum(_gw_xp(p, target_gw) for p in xi)
    # Kapteeni tuplaa pisteensä (promptin vaatimus: huomioitu molemmissa)
    team_xp_horizon_c = team_xp_horizon + cap_player["xp_horizon_total"]
    team_xp_gw_c = team_xp_gw + _gw_xp(cap_player, target_gw)

    cache_key = str(xp_data["meta"].get("generated_at"))
    dist = rating_distribution(pool, cache_key)
    percentile = _percentile(team_xp_horizon, dist)  # vertailu ilman kapteenia
    strongest, weakest = _line_strength(xi, pool)

    transfers = transfer_suggestions(squad, pool, bank_tenths)

    return {
        "meta": {
            "mode": mode,
            "entry": entry,
            "gw": target_gw,
            "picks_gw": picks_gw if mode == "entry" else None,
            "season": xp_data["meta"].get("season"),
            "generated_at": xp_data["meta"].get("generated_at"),
            "horizon_gw": xp_data["meta"].get("horizon_gw"),
            "sample_size": len(dist),
            "note": ("GoalIQ model projections, not FPL official expected "
                     "points. For fun and planning, not betting advice."),
        },
        "team": {
            "players": [{
                "id": p["id"], "web_name": p["web_name"],
                "team_short": p["team_short"],
                "pos": POS_NAME[p["element_type"]],
                "price": p["price"] / 10.0,
                "xp_per_gw": round(p["xp_per_gw"], 2),
                "xp_horizon_total": round(p["xp_horizon_total"], 2),
                "in_xi": p["id"] in xi_ids,
                "is_captain": p["id"] == effective_captain,
            } for p in squad],
            "missing_ids": missing,
            "bank": round(bank_tenths / 10.0, 1),
        },
        "rating": {
            "team_xp_gw": round(team_xp_gw_c, 2),
            "team_xp_horizon": round(team_xp_horizon_c, 2),
            "team_xp_horizon_no_captain": round(team_xp_horizon, 2),
            "percentile": percentile,
            "strongest_line": strongest,
            "weakest_line": weakest,
        },
        "captain": cap_sugg,
        "transfers": transfers,
    }
