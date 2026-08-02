"""DefCon-live (2.8.2026): oman joukkueen defensive contribution KESKEN kierroksen.

Miksi tama on ainoa live-pinta jonka rakennamme: FPL:n virallinen appi vei
live-rankit 20.-21.7. featurepudotuksessa, mutta DefCon-kertyma on yha aukko.
Se on uusi pistesaanto, sita on vaikea seurata ottelun aikana, ja meilla on jo
koko DefCon-datamalli (leaders, per-GW-matriisi, xP-komponentti). "Gabriel 7/10,
20 min jaljella" on syy avata appi kesken lauantain.

LAHDE = FPL:n oma `defensive_contribution` element/{gw}/live/-vastauksesta.
Sama kentta jota historiallinen DefCon-putki lukee (fpl_xp.dc_hit,
fpl_leaders) -> live ja historia EIVAT voi ajautua eri mielta. Kynnykset
tulevat fpl_leaders.DEFCON_THRESHOLD:sta samasta syysta.

HUOM minuuttisaanto: historiallinen osumaprosentti suodattaa >= 60 min rivit
(count_dc_hits), koska se mittaa luotettavuutta per taysi peli. LIVE EI SAA
suodattaa: FPL myontaa DefCon-pisteen kun kynnys tayttyy, pelatuista
minuuteista riippumatta. Suodatus tekisi live-nakymasta vaaran.

Esikausi ja kierrosten valit: is_current puuttuu -> available=False + note,
sama konventio kuin price watchissa. Ei keksita dataa jota ei ole.
"""
from __future__ import annotations

import threading
import time
from typing import Any

import requests

from src.models.fpl_leaders import DEFCON_THRESHOLD
from src.models.fpl_rate_team import RateTeamError

FPL_BASE = "https://fantasy.premierleague.com/api"
_UA = {"User-Agent": "GoalIQ/1.0"}

# Live-data muuttuu ottelun aikana jatkuvasti, mutta 0.5 vCPU:n Renderilla ja
# FPL:n rajoitteilla per-pyynto-haku on kohtuuton. 60 s on tarpeeksi tuore
# ottelunseurantaan ja pitaa kuorman kurissa.
_LIVE_TTL_S = 60.0
_lock = threading.Lock()
_live_cache: dict[int, tuple[float, dict[int, dict]]] = {}


def _get(url: str, timeout: float = 15.0) -> Any:
    r = requests.get(url, timeout=timeout, headers=_UA)
    r.raise_for_status()
    return r.json()


def _live_stats(gw: int) -> dict[int, dict]:
    """element_id -> stats-dict kierroksen live-datasta (60 s TTL)."""
    now = time.time()
    with _lock:
        hit = _live_cache.get(gw)
        if hit and (now - hit[0]) < _LIVE_TTL_S:
            return hit[1]
    data = _get(f"{FPL_BASE}/event/{gw}/live/")
    out: dict[int, dict] = {}
    for el in data.get("elements", []):
        if isinstance(el.get("id"), int):
            out[el["id"]] = el.get("stats") or {}
    with _lock:
        _live_cache[gw] = (time.time(), out)
    return out


def _entry_picks(entry_id: int, gw: int) -> list[dict]:
    data = _get(f"{FPL_BASE}/entry/{entry_id}/event/{gw}/picks/")
    picks = data.get("picks")
    if not isinstance(picks, list):
        raise RateTeamError(502, "FPL returned no picks for that team.")
    return picks


def _unavailable(note: str) -> dict:
    return {
        "meta": {
            "available": False,
            "gw": None,
            "generated_at": None,
            "thresholds": DEFCON_THRESHOLD,
            "note": note,
        },
        "players": [],
    }


def load_defcon_live(entry_id: int | None = None,
                     ids: list[int] | None = None) -> dict:
    """Live DefCon -kertyma joko entryn kokoonpanolle tai annetuille id:ille.

    Nostaa RateTeamErrorin vain kayttajan syotteen tai ylavirran vian takia;
    puuttuva kierros ei ole virhe vaan available=False.
    """
    from src.data.fpl_api import fetch_bootstrap

    if entry_id is None and not ids:
        raise RateTeamError(400, "Give either entry or ids.")

    boot = fetch_bootstrap()
    events = boot.get("events") or []
    current = next((e for e in events if e.get("is_current")), None)
    if current is None:
        return _unavailable(
            "DefCon live goes live when a gameweek is in play."
        )
    gw = int(current["id"])

    pos_by_type = {
        int(t["id"]): t.get("singular_name_short")
        for t in (boot.get("element_types") or [])
        if isinstance(t.get("id"), int)
    }
    team_short = {
        int(t["id"]): t.get("short_name")
        for t in (boot.get("teams") or [])
        if isinstance(t.get("id"), int)
    }
    elements = {
        int(e["id"]): e for e in (boot.get("elements") or [])
        if isinstance(e.get("id"), int)
    }

    if entry_id is not None:
        picks = _entry_picks(entry_id, gw)
        wanted = [(int(p["element"]), int(p.get("position") or 0),
                   bool(p.get("is_captain")))
                  for p in picks if isinstance(p.get("element"), int)]
    else:
        wanted = [(int(i), 0, False) for i in (ids or [])]

    stats = _live_stats(gw)

    players: list[dict] = []
    for element_id, squad_pos, is_captain in wanted:
        el = elements.get(element_id)
        if el is None:
            continue
        pos = pos_by_type.get(int(el.get("element_type") or 0)) or "?"
        thr = DEFCON_THRESHOLD.get(pos)  # GKP -> None, ei DefConia
        st = stats.get(element_id) or {}
        dc = int(st.get("defensive_contribution", 0) or 0)
        minutes = int(st.get("minutes", 0) or 0)
        players.append({
            "id": element_id,
            "web_name": el.get("web_name"),
            "team_short": team_short.get(int(el.get("team") or 0)),
            "pos": pos,
            "squad_position": squad_pos or None,
            "is_captain": is_captain,
            "minutes": minutes,
            "defcon": dc,
            "threshold": thr,
            # Kynnys tayttyy minuuteista riippumatta — EI 60 min suodatusta,
            # toisin kuin historiallisessa osumaprosentissa.
            "hit": thr is not None and dc >= thr,
            "remaining": None if thr is None else max(0, thr - dc),
            "eligible": thr is not None,
        })

    return {
        "meta": {
            "available": True,
            "gw": gw,
            "generated_at": current.get("deadline_time"),
            "thresholds": DEFCON_THRESHOLD,
            "note": (
                "Defensive contribution so far this gameweek, straight from "
                "the FPL match feed. A defender scores 2 points at 10 combined "
                "clearances, blocks, interceptions and tackles; a midfielder "
                "or forward at 12 including ball recoveries. Goalkeepers do "
                "not score defensive contribution."
            ),
        },
        "players": players,
    }
