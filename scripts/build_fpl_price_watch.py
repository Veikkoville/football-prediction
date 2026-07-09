"""#43 FPL hinnanmuutosennuste — tuotanto-builderi: net-transfer-velocity → JSON.

Tuottaa `data/fpl_price_watch.json`:n jonka `/api/fantasy/price-watch` tarjoilee
(ei on-request-laskentaa — Render 0.5 vCPU -budjettisääntö, sama pattern kuin
build_fpl_phase0/build_fpl_xp). Ajo: päivittäinen fpl-data-refresh.yml-cron
(#16) tai käsin `python -m scripts.build_fpl_price_watch`.

SIGNAALIKAAVA (dokumentoitu approksimaatio — FPL ei julkaise kynnyksiään):
  net_event   = transfers_in_event - transfers_out_event (bootstrap, per pelaaja)
  owners      = selected_by_percent / 100 * total_players
  threshold   = max(MIN_THRESHOLD, THRESHOLD_OWNER_RATE * owners)
                (yhteisöheuristiikka: kynnys skaalautuu omistajamäärään;
                 laskuille korkeampi kerroin — pudotukset ovat FPL:ssä jäykempiä)
  progress    = |net_event| / threshold  → progress_pct = min(100, 100*progress)
  status      = rising_soon  (net>0, progress >= 0.9)
                rising_watch (net>0, progress >= 0.5)
                falling_soon / falling_watch (net<0, samat rajat)
                stable       (muuten)
  confidence  = min(1.0, progress) pyöristettynä — monotoninen net_eventissä
                samassa omistushaarukassa (ship-gate vahtii).
  cost_change_event != 0 → already_changed_today=true; jos toteutunut muutos on
  ristiriidassa lasketun suunnan kanssa (nousi mutta luokka falling_* tms.),
  luokka clampataan stableksi (suunta-konsistenssi, ship-gate).

REHELLISYYS: output kantaa disclaimeria "estimated - FPL's exact threshold
isn't public". EI "guaranteed"-copyä. IP-puhdas (ei krestejä, vain tekstidata).

FAIL-SAFE: FPL-API alhaalla / vastaus rikki / sanity-gate kiinni → JSONia EI
kirjoiteta (vanha jää voimaan), exit != 0 → cron-step punainen, ei committia.
Exit 0 = ok, 1 = tekninen virhe, 2 = sanity-gate.
"""
from __future__ import annotations

import datetime as _dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests

import config
from src.models.fpl_price_watch import DISCLAIMER

FPL_BASE = "https://fantasy.premierleague.com/api"
FPL_HEADERS = {"User-Agent": "Mozilla/5.0 (GoalIQ refresh job)"}
OUT_PATH = config.PROJECT_ROOT / "data" / "fpl_price_watch.json"

# Kynnysapproksimaation parametrit (dokumentoitu yllä; EI virallinen algoritmi)
THRESHOLD_OWNER_RATE_RISE = 0.05   # ~5 % omistajista nettona sisään ≈ nousu
THRESHOLD_OWNER_RATE_FALL = 0.075  # laskut jäykempiä → korkeampi kynnys
MIN_THRESHOLD = 20_000             # pieniomisteisten lattia (kohinasuoja)
SOON_PROGRESS = 0.9
WATCH_PROGRESS = 0.5
TOP_N = 20


def fetch_bootstrap() -> dict:
    r = requests.get(f"{FPL_BASE}/bootstrap-static/", headers=FPL_HEADERS,
                     timeout=30)
    r.raise_for_status()
    return r.json()


def classify(net_event: int, owners: float,
             cost_change_event: int) -> tuple[str, float, float]:
    """→ (status, confidence, progress_pct). Puhdas funktio → testattava."""
    if net_event > 0:
        threshold = max(MIN_THRESHOLD, THRESHOLD_OWNER_RATE_RISE * owners)
        direction = "rising"
    elif net_event < 0:
        threshold = max(MIN_THRESHOLD, THRESHOLD_OWNER_RATE_FALL * owners)
        direction = "falling"
    else:
        return "stable", 0.0, 0.0
    progress = min(1.0, abs(net_event) / threshold)
    if progress >= SOON_PROGRESS:
        status = f"{direction}_soon"
    elif progress >= WATCH_PROGRESS:
        status = f"{direction}_watch"
    else:
        status = "stable"
    # Suunta-konsistenssi toteutuneeseen muutokseen: nousi tänään → ei falling_*,
    # laski tänään → ei rising_* (clamp stableksi).
    if cost_change_event > 0 and status.startswith("falling"):
        status = "stable"
    if cost_change_event < 0 and status.startswith("rising"):
        status = "stable"
    return status, round(progress, 2), round(100.0 * progress, 1)


def build_payload(bootstrap: dict) -> dict:
    total_players = int(bootstrap.get("total_players") or 0)
    rows = []
    for e in bootstrap.get("elements") or []:
        net_event = int(e.get("transfers_in_event") or 0) - \
            int(e.get("transfers_out_event") or 0)
        try:
            owned_pct = float(e.get("selected_by_percent") or 0.0)
        except (TypeError, ValueError):
            owned_pct = 0.0
        owners = owned_pct / 100.0 * total_players
        cce = int(e.get("cost_change_event") or 0)
        status, confidence, progress_pct = classify(net_event, owners, cce)
        rows.append({
            "id": e["id"],
            "web_name": e.get("web_name") or "",
            "team": e.get("team"),
            "now_cost": (e.get("now_cost") or 0) / 10.0,
            "status": status,
            "confidence": confidence,
            "progress_pct": progress_pct,
            "net_event": net_event,
            "already_changed_today": cce != 0,
        })
    risers = sorted((r for r in rows if r["status"].startswith("rising")),
                    key=lambda r: r["progress_pct"], reverse=True)[:TOP_N]
    fallers = sorted((r for r in rows if r["status"].startswith("falling")),
                     key=lambda r: r["progress_pct"], reverse=True)[:TOP_N]
    n_active = sum(1 for r in rows if r["net_event"] != 0)
    return {
        "meta": {
            "product": "GoalIQ Fantasy - price watch",
            "available": True,
            "generated_at": _dt.datetime.now(_dt.timezone.utc)
                            .strftime("%Y-%m-%dT%H:%M:%SZ"),
            "total_players": total_players,
            "n_players_scanned": len(rows),
            "n_with_transfer_activity": n_active,
            "disclaimer": DISCLAIMER,
            **({"note": "Pre-season: no transfer activity yet - price watch "
                        "goes live when the FPL game opens."}
               if n_active == 0 else {}),
        },
        "risers": risers,
        "fallers": fallers,
    }


def sanity_gate(payload: dict) -> list[str]:
    """Ship-gate: suunta-konsistenssi + top-listojen eheys. → rikkeet."""
    errors = []
    for r in payload["risers"]:
        if not r["status"].startswith("rising") or r["net_event"] <= 0:
            errors.append(f"riser-rikke: {r['web_name']} {r['status']} net={r['net_event']}")
    for r in payload["fallers"]:
        if not r["status"].startswith("falling") or r["net_event"] >= 0:
            errors.append(f"faller-rikke: {r['web_name']} {r['status']} net={r['net_event']}")
    for r in payload["risers"] + payload["fallers"]:
        if not 0.0 <= r["confidence"] <= 1.0 or not 0.0 <= r["progress_pct"] <= 100.0:
            errors.append(f"range-rikke: {r['web_name']}")
    return errors


def main() -> int:
    try:
        bootstrap = fetch_bootstrap()
    except Exception as e:
        print(f"VIRHE: FPL-API-haku epäonnistui: {e!r} — vanha JSON jää voimaan.")
        return 1
    if not bootstrap.get("elements"):
        print("VIRHE: bootstrap ilman elements-listaa — ei kirjoiteta.")
        return 1

    payload = build_payload(bootstrap)
    errors = sanity_gate(payload)
    if errors:
        print("SANITY-GATE KIINNI — JSONia ei kirjoiteta:")
        for err in errors:
            print(f"  {err}")
        return 2

    OUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n",
                        encoding="utf-8")
    print(f"OK: {OUT_PATH.name} kirjoitettu — risers {len(payload['risers'])}, "
          f"fallers {len(payload['fallers'])}, "
          f"aktiivisia {payload['meta']['n_with_transfer_activity']}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
