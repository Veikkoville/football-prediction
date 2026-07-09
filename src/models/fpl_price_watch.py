"""#43 FPL price watch — committatun hinnanmuutosennusteen lataus.

`/api/fantasy/price-watch` lukee `data/fpl_price_watch.json`:n jonka
`scripts/build_fpl_price_watch.py` tuottaa (päivittäinen fpl-data-refresh-cron).
Sama pattern kuin fpl_phase0/fpl_xp: endpoint EI laske mitään pyynnössä.
"""
from __future__ import annotations

import json
from pathlib import Path

import config

PW_PATH = config.DATA_DIR / "fpl_price_watch.json"

DISCLAIMER = ("Estimated from FPL net-transfer velocity - FPL's exact price "
              "thresholds are not public. Model estimate, not a guarantee.")


def empty_price_watch() -> dict:
    """Runko kun tiedostoa ei ole committattu — appi näyttää tyhjän tilan."""
    return {
        "meta": {
            "product": "GoalIQ Fantasy - price watch",
            "available": False,
            "generated_at": None,
            "disclaimer": DISCLAIMER,
        },
        "risers": [],
        "fallers": [],
    }


def load_price_watch(path: Path = PW_PATH) -> dict:
    if not path.exists():
        return empty_price_watch()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return empty_price_watch()
    if not isinstance(data, dict) or "meta" not in data:
        return empty_price_watch()
    data.setdefault("risers", [])
    data.setdefault("fallers", [])
    return data
