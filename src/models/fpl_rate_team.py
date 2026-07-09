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
    """#52 deadline-resilienssi: TTL-cache + stale-fallback. FPL:n failatessa
    (verkko / 5xx / 429 — tyypillistä juuri GW-deadlinen ruuhkassa) serveerataan
    viimeisin onnistunut vastaus vaikka TTL olisi ohi — EI virhettä käyttäjälle.
    404 on deterministinen (väärä entry) → nostetaan aina. Ilman cachea →
    hallittu virhe kuten ennen."""
    now = time.time()
    with _FPL_CACHE_LOCK:
        hit = _FPL_CACHE.get(path)
        if hit and now - hit[0] < CACHE_TTL_SEC:
            return hit[1]
    try:
        r = requests.get(f"{FPL_BASE}{path}", timeout=FPL_TIMEOUT_SEC,
                         headers={"User-Agent": "GoalIQ/1.0"})
    except requests.RequestException as e:
        if hit:
            return hit[1]  # stale > virhe (deadline-ilta)
        raise RateTeamError(
            503, "FPL API is not responding right now. Try again in a moment."
        ) from e
    if r.status_code == 404:
        raise RateTeamError(404, "Not found on the FPL API.")
    if r.status_code != 200:
        if hit:
            return hit[1]  # stale > virhe
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


_OPTIMAL_XP_CACHE: dict[str, float] = {}


def optimal_budget_team_xp(pool: list[dict], cache_key: str) -> float:
    """#50: paras mahdollinen laillinen budjettijoukkue -benchmark (XI:n
    horisontti-xP). Korvaa satunnaisotoksen: "300 random squads" antoi lähes
    kaikille oikeille joukkueille ~100 % = ontto imartelu (Hub 2,0★ -oppi 4).

    Heuristiikka (dokumentoitu, deterministinen — ei globaali optimi mutta kova
    ja rehellinen benchmark):
      1. Penkkireservi: halvin GKP + 3 halvinta kenttäpelaajaa (XI:n
         ulkopuolinen raha minimiin) → XI-budjetti = 100.0m − reservi.
      2. XI: ahne valinta horisontti-xP:llä; kiintiöt XI_MIN/MAX:n sisällä,
         max 3/klubi, ja joka poiminnalla varmistetaan että loput XI-paikat
         voi vielä täyttää halvimmalla mahdollisella (budjetti ei lukkiudu)."""
    hit = _OPTIMAL_XP_CACHE.get(cache_key)
    if hit is not None:
        return hit
    by_pos: dict[int, list[dict]] = {1: [], 2: [], 3: [], 4: []}
    for p in pool:
        by_pos[p["element_type"]].append(p)
    if any(len(by_pos[t]) < n for t, n in SQUAD_QUOTA.items()):
        return 0.0

    cheapest_gk = min(p["price"] for p in by_pos[1])
    outfield_prices = sorted(p["price"] for t in (2, 3, 4) for p in by_pos[t])
    bench_reserve = cheapest_gk + sum(outfield_prices[:3])
    xi_budget = BUDGET_TENTHS - bench_reserve
    min_price = min(p["price"] for p in pool)

    ranked = sorted(pool, key=lambda p: p["xp_horizon_total"], reverse=True)
    xi: list[dict] = []
    counts = {1: 0, 2: 0, 3: 0, 4: 0}
    clubs: dict[int, int] = {}
    cost = 0
    for p in ranked:
        if len(xi) == 11:
            break
        t = p["element_type"]
        if counts[t] >= XI_MAX[t]:
            continue
        if clubs.get(p["club"], 0) >= MAX_PER_CLUB:
            continue
        # Minimipaikkojen turvaus: jäljellä olevien pakollisten slotien on
        # mahduttava vielä valinnan jälkeen.
        need_min = sum(max(0, XI_MIN[q] - counts[q] - (1 if q == t else 0))
                       for q in XI_MIN)
        slots_left = 11 - len(xi) - 1
        if need_min > slots_left:
            continue
        # Budjettiturvaus: loput paikat halvimmalla täytettävissä.
        if cost + p["price"] + slots_left * min_price > xi_budget:
            continue
        xi.append(p)
        counts[t] += 1
        clubs[p["club"]] = clubs.get(p["club"], 0) + 1
        cost += p["price"]
    total = sum(p["xp_horizon_total"] for p in xi) if len(xi) == 11 else 0.0
    _OPTIMAL_XP_CACHE[cache_key] = total
    return total


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
        try:
            owned_pct = float(boot.get("selected_by_percent") or 0.0)
        except (TypeError, ValueError):
            owned_pct = 0.0
        pool.append({
            "id": p["id"], "web_name": p["web_name"],
            "team_short": p.get("team_short") or "",
            "element_type": pos_by_name.get(p.get("pos"), boot["element_type"]),
            "club": boot["team"],
            "price": boot["now_cost"],
            "owned_pct": owned_pct,
            "xp_per_gw": float(p.get("xp_per_gw") or 0.0),
            "xp_horizon_total": float(p.get("xp_horizon_total") or 0.0),
            "gameweeks": p.get("gameweeks") or [],
            # #35 compare: erittelykentät kulkevat poolin mukana
            "xmins": p.get("xmins"),
            "predicted_starts": p.get("predicted_starts"),
            "minutes_confidence": p.get("minutes_confidence"),
            "components": p.get("components"),
            "components_gw": p.get("components_gw"),
        })
    return pool


def build_context() -> tuple[dict, dict, list[dict], dict[int, dict]]:
    """#35: jaettu konteksti rate-teamille + planner-suitelle:
    (xp_data, bootstrap, pool, pool_by_id). Nostaa 503:n jos projektio puuttuu."""
    xp_data = load_xp()
    if not xp_data.get("meta", {}).get("available") or not xp_data.get("players"):
        raise RateTeamError(503, "xP projections are not available yet.")
    bootstrap = get_bootstrap()
    price_by_id = {e["id"]: e for e in bootstrap.get("elements") or []}
    pool = _projection_pool(xp_data, price_by_id)
    return xp_data, bootstrap, pool, {p["id"]: p for p in pool}


def resolve_squad(bootstrap: dict, entry: int | None, gw: int | None,
                  players: list[int] | None, captain: int | None,
                  bank: float | None) -> tuple[list[int], int | None, int, int]:
    """#35: jaettu joukkueresoluutio → (squad_ids, captain_id, bank_tenths,
    picks_gw). entry-moodi hakee picksit; manual-moodi validoi 15 ID:tä."""
    bank_tenths = int(round((bank or 0.0) * 10))
    if players:
        if len(players) != 15:
            raise RateTeamError(400, "players must list exactly 15 FPL element IDs.")
        if len(set(players)) != 15:
            raise RateTeamError(400, "players contains duplicate IDs.")
        return list(players), captain, bank_tenths, _resolve_gw(bootstrap, gw)
    if entry is None:
        raise RateTeamError(400, "Provide either entry or players.")
    picks_gw = _resolve_gw(bootstrap, gw)
    picks_data = get_entry_picks(entry, picks_gw)
    picks = picks_data.get("picks") or []
    if not picks:
        raise RateTeamError(404, f"Entry {entry} has no picks for GW{picks_gw}.")
    squad_ids = [pk["element"] for pk in picks]
    cap = [pk["element"] for pk in picks if pk.get("is_captain")]
    captain_id = captain or (cap[0] if cap else None)
    if bank is None:
        bank_tenths = int((picks_data.get("entry_history") or {}).get("bank") or 0)
    return squad_ids, captain_id, bank_tenths, picks_gw


def clamp_gw_to_projections(target_gw: int, pool: list[dict],
                            xp_data: dict) -> int:
    """Esikausiclamppi: jos GW ei ole projektioiden kattama, käytä projektioiden
    seuraavaa GW:tä (meta.next_gameweek, fallback pienin katettu)."""
    covered = {g.get("gw") for p in pool for g in (p.get("gameweeks") or [])}
    if target_gw in covered:
        return target_gw
    return (xp_data["meta"].get("next_gameweek")
            or (min(covered) if covered else target_gw))


def rate_team(entry: int | None = None, gw: int | None = None,
              players: list[int] | None = None, captain: int | None = None,
              bank: float | None = None) -> dict:
    """Arvioi joukkue. entry-moodi (julkinen FPL-ID) TAI manual-moodi
    (players = 15 element-ID:tä, esikausifallback)."""
    xp_data, bootstrap, pool, pool_by_id = build_context()
    mode = "manual" if players else "entry"
    missing: list[int] = []
    squad_ids, captain_id, bank_tenths, picks_gw = resolve_squad(
        bootstrap, entry, gw, players, captain, bank)

    # Esikausiclamppi: picks voi tulla viime kauden GW:stä (esim. GW38), mutta
    # projektiot kattavat tulevan horisontin (GW1–6) → xP-laskennan GW on aina
    # projektioiden kattama. picks_gw raportoidaan erikseen metassa.
    target_gw = clamp_gw_to_projections(picks_gw, pool, xp_data)

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

    # #50: rating = vertailu PARHAASEEN mahdolliseen budjettijoukkueeseen
    # (satunnaisotos antoi kaikille ~100 % = ontto). percentile-kenttä säilyy
    # yhteensopivuuden takia mutta tarkoittaa nyt "% of the best possible
    # budget team" (clampattu 100:aan — ahne benchmark voi alittaa aidon
    # optimin marginaalisesti).
    cache_key = str(xp_data["meta"].get("generated_at"))
    optimal_xp = optimal_budget_team_xp(pool, cache_key)
    pct_of_optimal = (round(min(100.0, 100.0 * team_xp_horizon / optimal_xp), 1)
                      if optimal_xp > 0 else 0.0)
    gap_to_optimal = round(max(0.0, optimal_xp - team_xp_horizon), 2)
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
            "rating_method": "vs_optimal_budget_team",
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
            "percentile": pct_of_optimal,
            "optimal_team_xp": round(optimal_xp, 2),
            "gap_to_optimal_xp": gap_to_optimal,
            "strongest_line": strongest,
            "weakest_line": weakest,
        },
        "captain": cap_sugg,
        "transfers": transfers,
    }
