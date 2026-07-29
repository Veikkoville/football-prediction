"""Beat the model V1 — päätösten gradaus (backend-eräajo).

Määrittely: goaliq-app/cos-reports/beat-the-model-maarittely-2026-07-29.md
Skeema: supabase/migrations/20260729233000_add_decision_grading_and_captaincy.sql

SILMUKAN VIIMEINEN ASKEL: malli sanoo -> sinä päätät -> deadline lukitsee ->
kierros ratkeaa -> TÄMÄ kertoo kumpi oli oikeassa. Klientti ei koskaan gradaa
itseään; tämä ajetaan service-roolilla admin-endpointista (sama ADMIN_TOKEN-
kaava kuin clear-cache) kun GW on FPL:n mukaan valmis.

GRADAUSKAAVAT (yksi GW, ei kumulatiivinen):
  captain : pelaajan toteutuneet GW-pisteet x 2 (kapteenitupla)
  transfer: in-pelaajan pisteet - out-pelaajan pisteet samalta GW:ltä

TIETOINEN POIKKEAMA määrittelyn 1. versiosta: siirto gradataan siirto-GW:n
deltana, EI kumulatiivisena "loppukauteen asti". Kumulatiivinen tulos eläisi
joka kierroksen jälkeen, mikä on ristiriidassa immutable graded -rivin kanssa
— ja immutability on koko vertailun uskottavuus. Yhden GW:n delta on sama
mittayksikkö jolla FPL itse ratkeaa. (Määrittely päivitetty 29.7.)

DEVIATED-PÄÄTÖKSET: käyttäjän toteutunut valinta luetaan FPL:n julkisesta
datasta (picks / transfers) entry-ID:llä. Ilman entry-ID:tä poikkeamaa ei voi
gradata -> user_points=NULL + grade_note='no_entry_id'. Rehellinen rajoite,
ei arvausta.

Puhdas logiikka (grade_one) on erotettu IO:sta testattavuuden takia: testit
syöttävät live-pisteet ja picks-hakijat funktioina.
"""
from __future__ import annotations

from typing import Callable

# grade_note-arvot (koneluettava; UI kääntää)
NOTE_OK = "ok"
NOTE_NO_ENTRY = "no_entry_id"
NOTE_PICKS_UNAVAILABLE = "picks_unavailable"
NOTE_PLAYER_MISSING = "player_missing"
NOTE_KIND_NOT_GRADED = "kind_not_graded"

# Palautettu tulos: (model_points, user_points, grade_note)
GradeResult = tuple[float | None, float | None, str]


def _num(v: object) -> float | None:
    return float(v) if isinstance(v, (int, float)) else None


def grade_one(
    kind: str,
    model_choice: dict,
    user_choice: dict,
    followed: bool,
    live_points: dict[int, float],
    entry_id: int | None,
    fetch_captain: Callable[[int], int | None],
    fetch_transfers: Callable[[int], list[tuple[int, int]] | None],
) -> GradeResult:
    """Gradaa yksi päätös. Ei IO:ta — hakijat tulevat parametreina.

    live_points   : element_id -> toteutuneet GW-pisteet
    fetch_captain : entry_id -> toteutuneen kapteenin element_id (None = ei saatu)
    fetch_transfers: entry_id -> [(in_id, out_id), ...] ko. GW:llä (None = ei saatu)
    """
    if kind == "captain":
        model_id = model_choice.get("id")
        if not isinstance(model_id, int) or model_id not in live_points:
            return (None, None, NOTE_PLAYER_MISSING)
        model_pts = live_points[model_id] * 2.0

        if followed:
            return (model_pts, model_pts, NOTE_OK)
        if entry_id is None:
            return (model_pts, None, NOTE_NO_ENTRY)
        actual_id = fetch_captain(entry_id)
        if actual_id is None:
            return (model_pts, None, NOTE_PICKS_UNAVAILABLE)
        if actual_id not in live_points:
            return (model_pts, None, NOTE_PLAYER_MISSING)
        return (model_pts, live_points[actual_id] * 2.0, NOTE_OK)

    if kind == "transfer":
        in_id, out_id = model_choice.get("in_id"), model_choice.get("out_id")
        if (not isinstance(in_id, int) or not isinstance(out_id, int)
                or in_id not in live_points or out_id not in live_points):
            return (None, None, NOTE_PLAYER_MISSING)
        model_pts = live_points[in_id] - live_points[out_id]

        if followed:
            return (model_pts, model_pts, NOTE_OK)
        if entry_id is None:
            return (model_pts, None, NOTE_NO_ENTRY)
        moves = fetch_transfers(entry_id)
        if moves is None:
            return (model_pts, None, NOTE_PICKS_UNAVAILABLE)
        # Ei siirtoja = piti joukkueen -> vertailukohta on 0.0 (hold).
        total = 0.0
        for m_in, m_out in moves:
            if m_in not in live_points or m_out not in live_points:
                return (model_pts, None, NOTE_PLAYER_MISSING)
            total += live_points[m_in] - live_points[m_out]
        return (model_pts, total, NOTE_OK)

    # chip / lineup: silmukka ei tuota näitä vielä. Merkitään gradatuiksi
    # notella, jotta ungraded-indeksi ei kasva ikuisesti.
    return (None, None, NOTE_KIND_NOT_GRADED)


# ---------------------------------------------------------------------------
# IO-kerros (FPL:n julkiset endpointit; käytetään vain grade-ajossa)
# ---------------------------------------------------------------------------

FPL_BASE = "https://fantasy.premierleague.com/api"


def fetch_live_points(gw: int) -> dict[int, float]:
    """element_id -> toteutuneet GW-pisteet. Nostaa jos haku epäonnistuu:
    ilman live-dataa koko ajo on merkityksetön (parempi kaatua kuin gradata
    nollilla)."""
    import requests

    r = requests.get(f"{FPL_BASE}/event/{gw}/live/", timeout=30,
                     headers={"User-Agent": "GoalIQ/1.0"})
    r.raise_for_status()
    out: dict[int, float] = {}
    for el in r.json().get("elements", []):
        pts = _num((el.get("stats") or {}).get("total_points"))
        if isinstance(el.get("id"), int) and pts is not None:
            out[el["id"]] = pts
    return out


def make_picks_fetchers(gw: int):
    """(fetch_captain, fetch_transfers) -parivaljakko yhdelle GW:lle,
    per-entry-välimuistilla (sama entry voi esiintyä monessa päätöksessä)."""
    import requests

    picks_cache: dict[int, dict | None] = {}
    transfers_cache: dict[int, list | None] = {}

    def _picks(entry_id: int) -> dict | None:
        if entry_id not in picks_cache:
            try:
                r = requests.get(
                    f"{FPL_BASE}/entry/{entry_id}/event/{gw}/picks/",
                    timeout=20, headers={"User-Agent": "GoalIQ/1.0"})
                picks_cache[entry_id] = r.json() if r.status_code == 200 else None
            except Exception:
                picks_cache[entry_id] = None
        return picks_cache[entry_id]

    def fetch_captain(entry_id: int) -> int | None:
        data = _picks(entry_id)
        if not data:
            return None
        for p in data.get("picks", []):
            if p.get("is_captain"):
                return p.get("element") if isinstance(p.get("element"), int) else None
        return None

    def fetch_transfers(entry_id: int) -> list[tuple[int, int]] | None:
        if entry_id not in transfers_cache:
            try:
                r = requests.get(
                    f"{FPL_BASE}/entry/{entry_id}/transfers/",
                    timeout=20, headers={"User-Agent": "GoalIQ/1.0"})
                if r.status_code != 200:
                    transfers_cache[entry_id] = None
                else:
                    moves = []
                    for t in r.json():
                        if t.get("event") == gw:
                            e_in, e_out = t.get("element_in"), t.get("element_out")
                            if isinstance(e_in, int) and isinstance(e_out, int):
                                moves.append((e_in, e_out))
                    transfers_cache[entry_id] = moves
            except Exception:
                transfers_cache[entry_id] = None
        return transfers_cache[entry_id]

    return fetch_captain, fetch_transfers


def finished_gws() -> set[int]:
    """FPL:n mukaan valmiit kierrokset (finished + data_checked = bonukset
    ja BPS lopullisia). Mieluummin myöhässä ja oikein kuin ajoissa ja väärin."""
    import requests

    r = requests.get(f"{FPL_BASE}/bootstrap-static/", timeout=30,
                     headers={"User-Agent": "GoalIQ/1.0"})
    r.raise_for_status()
    return {
        e["id"] for e in r.json().get("events", [])
        if e.get("finished") and e.get("data_checked") and isinstance(e.get("id"), int)
    }
