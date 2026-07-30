"""Price watch -tarkkuusloki (30.7, Villen GO): julkinen gradaus.

Ajetaan fpl-data-refreshissä ENNEN build_fpl_price_watchia: committattu
fpl_price_watch.json on edellisen yön ennuste + hintasnapshot. Diffataan
snapshot elävään bootstrapiin → toteutuneet muutokset → gradataan.

REHELLISYYSSÄÄNNÖT:
  - Vain *_soon on väite ("ennustamme muutosta tänä yönä") → vain ne
    gradataan. *_watch ei ole väite, sitä ei lasketa osumaksi eikä hudiksi.
  - already_changed_today-rivit ohitetaan (muutos oli jo tapahtunut kun
    ennuste tehtiin — sen laskeminen osumaksi olisi itsepetosta).
  - Miss kirjataan samalla painolla kuin hitti. Recall raportoidaan myös:
    kuinka moni TOTEUTUNUT muutos oli ennustettu (_soon TAI _watch).
  - Append-only-loki; sama pred_at ei gradaudu kahdesti (idempotentti).
  - Esikausi (0 ennustetta, 0 muutosta) kirjataan päivärivinä sellaisenaan —
    tyhjä päivä on dataa, ei virhe.

Exit 0 aina kun loki on konsistentti (myös "ei gradattavaa") — grader ei saa
kaataa refresh-workflowta. Tekninen virhe → exit 1 (steppi punaiseksi).
"""
from __future__ import annotations

import datetime as _dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests

import config

WATCH_PATH = config.PROJECT_ROOT / "data" / "fpl_price_watch.json"
LOG_PATH = config.PROJECT_ROOT / "data" / "fpl_price_accuracy.json"
FPL_BASE = "https://fantasy.premierleague.com/api"
FPL_HEADERS = {"User-Agent": "Mozilla/5.0 (GoalIQ grade job)"}


def grade(prev: dict, live_prices: dict[str, int]) -> dict | None:
    """Puhdas ydin: edellinen payload + elävät hinnat → päivärivi (tai None
    jos snapshot puuttuu = vanha formaatti ennen 30.7)."""
    snap = prev.get("prices")
    if not isinstance(snap, dict) or not snap:
        return None
    rose = {pid for pid, p in snap.items()
            if pid in live_prices and live_prices[pid] > p}
    fell = {pid for pid, p in snap.items()
            if pid in live_prices and live_prices[pid] < p}

    def _grade_side(rows: list[dict], actual: set[str], prefix: str):
        soon = [r for r in rows
                if r.get("status") == f"{prefix}_soon"
                and not r.get("already_changed_today")]
        hits = sum(1 for r in soon if str(r["id"]) in actual)
        predicted_any = {str(r["id"]) for r in rows
                         if str(r.get("status", "")).startswith(prefix)}
        caught = sum(1 for pid in actual if pid in predicted_any)
        return len(soon), hits, caught

    r_pred, r_hits, r_caught = _grade_side(prev.get("risers") or [], rose, "rising")
    f_pred, f_hits, f_caught = _grade_side(prev.get("fallers") or [], fell, "falling")
    return {
        "graded_at": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "pred_at": prev.get("meta", {}).get("generated_at"),
        "rise_soon_pred": r_pred, "rise_soon_hits": r_hits,
        "fall_soon_pred": f_pred, "fall_soon_hits": f_hits,
        "actual_risers": len(rose), "actual_fallers": len(fell),
        "risers_caught_any_tier": r_caught, "fallers_caught_any_tier": f_caught,
    }


def main() -> int:
    if not WATCH_PATH.exists():
        print("Ei price_watch.jsonia — ei gradattavaa.")
        return 0
    prev = json.loads(WATCH_PATH.read_text(encoding="utf-8"))
    log = (json.loads(LOG_PATH.read_text(encoding="utf-8"))
           if LOG_PATH.exists() else {"meta": {
               "product": "GoalIQ price watch accuracy log",
               "rules": ("Only *_soon predictions are graded (a watch flag is "
                         "not a claim). Rows that had already changed when "
                         "predicted are excluded. Misses logged with the same "
                         "weight as hits. Append-only."),
           }, "days": []})
    pred_at = prev.get("meta", {}).get("generated_at")
    if any(d.get("pred_at") == pred_at for d in log["days"]):
        print(f"Jo gradattu (pred_at {pred_at}) — idempotentti ohitus.")
        return 0
    try:
        r = requests.get(f"{FPL_BASE}/bootstrap-static/", headers=FPL_HEADERS,
                         timeout=30)
        r.raise_for_status()
        boot = r.json()
    except Exception as e:
        print(f"VIRHE: bootstrap-haku epäonnistui: {e!r}")
        return 1
    live = {str(e["id"]): int(e.get("now_cost") or 0)
            for e in boot.get("elements") or []}
    day = grade(prev, live)
    if day is None:
        print("Edellisessä payloadissa ei hintasnapshotia (formaatti ennen "
              "30.7) — gradaus alkaa seuraavasta ajosta.")
        return 0
    log["days"].append(day)
    LOG_PATH.write_text(json.dumps(log, ensure_ascii=False, indent=1) + "\n",
                        encoding="utf-8")
    print(f"OK: {day['graded_at']} — rise_soon {day['rise_soon_hits']}/"
          f"{day['rise_soon_pred']}, fall_soon {day['fall_soon_hits']}/"
          f"{day['fall_soon_pred']}, toteutuneita {day['actual_risers']}↑ "
          f"{day['actual_fallers']}↓. Päiviä lokissa {len(log['days'])}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
