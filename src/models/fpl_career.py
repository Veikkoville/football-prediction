"""#55 FPL Career / Season Review — urahistoria jakokorttia varten.

Hakee managerin urahistorian JULKISELLA entry-ID:llä (ei kirjautumista, ei
salasanoja) FPL-API:n entry/{id}/ + entry/{id}/history/ -endpointeista ja
tiivistää sen jakokortin tarvitsemaan muotoon: past_seasons + summary +
viimeisimmän kauden GW-erittely + GoalIQ-malliteaser (#34 rate-team,
#50 opti-baseline — EI satunnaisotos).

Uudelleenkäyttää fpl_rate_team-infran (_fetch_fpl: 10 min TTL-cache +
#52 stale-fallback, RateTeamError, rate_team) — EI duplikoi hakua/cachea.

Esikausi-degradaatio (kriittinen, Hub-oppi #52): past_seasons + summary
palautuvat ympäri vuoden (past-data on aina olemassa); current voi olla
tyhjä 26/27-resetin jälkeen ennen GW1:tä → latest_season palautuu
available=False + selite, EI blank/virhe. Kesän välitila huomioitu:
FPL näyttää juuri päättyneen kauden SEKÄ current- ETTÄ past-listassa →
dedup ettei kausi tuplaannu summaryssä.

Malliteaser on best-effort-kääre: jos squadia ei voi tuoda tai projektio
puuttuu, teaser jätetään pois (ei placeholderia) — urahistoria palautuu silti.

Ei kirjoita mitään; rate-team/xP-polut jäävät bittitarkasti koskemattomiksi.
"""
from __future__ import annotations

import src.models.fpl_rate_team as rt
from src.models.fpl_rate_team import RateTeamError

__all__ = ["career", "RateTeamError"]


def _season_start_year(season_name: str | None) -> int | None:
    """'2025/26' → 2025."""
    if not season_name:
        return None
    try:
        return int(str(season_name).split("/")[0])
    except (ValueError, IndexError):
        return None


def _fetch_history(entry: int) -> tuple[dict, dict]:
    """(entry-root, history). Erottelee 'entry ei ole olemassa' selkeästi."""
    try:
        root = rt._fetch_fpl(f"/entry/{entry}/")
    except RateTeamError as e:
        if e.status_code == 404:
            raise RateTeamError(
                404, f"FPL entry {entry} was not found. Check the ID "
                     "(it is the number in your FPL points-page URL).")
        raise
    history = rt._fetch_fpl(f"/entry/{entry}/history/")
    return root, history


def _preseason_note() -> str:
    """Selite tyhjälle current-kaudelle; deadline bootstrapista jos saatavilla.
    Bootstrap-haun failaus ei saa kaataa career-vastausta (fail-safe)."""
    generic = "The new FPL season has not started yet - GW1 is coming up."
    try:
        events = rt.get_bootstrap().get("events") or []
    except Exception:
        return generic
    for e in events:
        if e.get("is_next") and e.get("deadline_time"):
            day = str(e["deadline_time"])[:10]  # YYYY-MM-DD
            return (f"The new FPL season has not started yet - "
                    f"GW{e['id']} deadline is {day}.")
    return generic


def _latest_season(current: list[dict], past: list[dict]) -> dict:
    """Viimeisimmän kauden GW-erittely current-listasta.

    Kesävälitila: juuri päättynyt kausi näkyy myös past-listassa → nimetään
    sieltä ja merkitään finished (ei tuplalaskentaa summaryssä; ks. career()).
    """
    if not current:
        return {"available": False, "note": _preseason_note()}

    last = current[-1]
    finished = bool(past) and past[-1].get("total_points") == last.get(
        "total_points") and len(current) >= 38
    season = past[-1].get("season_name") if finished else None

    played = [g for g in current if g.get("points") is not None]
    best = max(played, key=lambda g: g["points"]) if played else None
    worst = min(played, key=lambda g: g["points"]) if played else None
    return {
        "available": True,
        "season": season,
        "finished": finished,
        "total_points": last.get("total_points"),
        "overall_rank": last.get("overall_rank"),
        "best_gw": ({"gw": best["event"], "points": best["points"]}
                    if best else None),
        "worst_gw": ({"gw": worst["event"], "points": worst["points"]}
                     if worst else None),
        "total_hits": sum(int(g.get("event_transfers_cost") or 0)
                          for g in current),
        "bench_points": sum(int(g.get("points_on_bench") or 0)
                            for g in current),
        "gws": [{"gw": g.get("event"), "points": g.get("points"),
                 "overall_rank": g.get("overall_rank")} for g in current],
    }


def _model_teaser(entry: int) -> dict | None:
    """GoalIQ-kääre-kiila: nykyisen squadin projektio #34-rate-teamilla
    (#50: percentile = % of the best possible budget team, EI satunnaisotos).
    Best-effort: mikä tahansa failure → None (teaser pois, ei placeholderia)."""
    try:
        rated = rt.rate_team(entry=entry)
    except Exception:
        return None
    rating = rated.get("rating") or {}
    if not rating.get("team_xp_gw"):
        return None
    return {
        "gw": rated["meta"].get("gw"),
        "team_xp_gw": rating.get("team_xp_gw"),
        "team_xp_horizon": rating.get("team_xp_horizon"),
        "percentile": rating.get("percentile"),
        "rating_method": rated["meta"].get("rating_method"),
        "note": ("Projected with the same match model behind GoalIQ's "
                 "public pre-match-logged track record."),
    }


def career(entry: int) -> dict:
    """Urahistoria + summary + viimeisin kausi + malliteaser entry-ID:llä."""
    root, history = _fetch_history(entry)
    past = list(history.get("past") or [])
    current = list(history.get("current") or [])
    chips = list(history.get("chips") or [])

    latest = _latest_season(current, past)
    if latest.get("available"):
        latest["chips_used"] = [{"name": c.get("name"), "gw": c.get("event")}
                                for c in chips]

    past_seasons = [{
        "season": s.get("season_name"),
        "points": s.get("total_points"),
        "rank": s.get("rank"),
    } for s in past]

    # Summary koko uralta. Kesävälitila: finished current on JO past-listassa
    # → ei lisätä toiseen kertaan. Keskeneräinen current lasketaan mukaan.
    in_progress = latest.get("available") and not latest.get("finished")
    all_time = sum(int(s.get("total_points") or 0) for s in past)
    seasons_played = len(past)
    if in_progress:
        all_time += int(latest.get("total_points") or 0)
        seasons_played += 1

    best_season = None
    if past:
        b = max(past, key=lambda s: int(s.get("total_points") or 0))
        best_season = {"season": b.get("season_name"),
                       "points": b.get("total_points"),
                       "rank": b.get("rank")}
    ranks = [int(s["rank"]) for s in past if s.get("rank")]
    if in_progress and latest.get("overall_rank"):
        ranks.append(int(latest["overall_rank"]))

    since = _season_start_year(past[0].get("season_name")) if past else None
    if since is None:
        joined = str(root.get("joined_time") or "")
        since = int(joined[:4]) if joined[:4].isdigit() else None

    first = (root.get("player_first_name") or "").strip()
    last_n = (root.get("player_last_name") or "").strip()

    result = {
        "meta": {
            "entry": entry,
            "source": "FPL public entry API (no login)",
            "note": ("Career history from the official FPL API. "
                     "For fun, not betting advice."),
        },
        "manager": {
            "name": " ".join(x for x in (first, last_n) if x) or None,
            "team_name": root.get("name"),
            "since": since,
        },
        "past_seasons": past_seasons,
        "summary": {
            "seasons_played": seasons_played,
            "all_time_points": all_time,
            "best_season": best_season,
            "best_rank": min(ranks) if ranks else None,
            "avg_rank": round(sum(ranks) / len(ranks)) if ranks else None,
            "since": since,
        },
        "latest_season": latest,
    }
    teaser = _model_teaser(entry)
    if teaser:
        result["model_teaser"] = teaser
    return result
