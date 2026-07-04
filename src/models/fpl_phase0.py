"""FPL Phase 0 — staattisen projektio-JSON:n loader (#FPL-P0).

`/api/fantasy` tarjoilee ajastetun refresh-jobin (scripts/build_fpl_phase0.py)
tuottaman `data/fpl_projections_phase0.json`:n. Tämä moduuli vain lukee
tiedoston — EI laskentaa pyynnössä (Render 0.5 vCPU -budjettisääntö,
FPL-speksi luku 2). Peili: src/models/accuracy.py::load_aggregate.
"""
from __future__ import annotations

import json
from pathlib import Path

import config

PHASE0_PATH = config.DATA_DIR / "fpl_projections_phase0.json"


def empty_phase0() -> dict:
    """Runko kun projektiota ei ole vielä committattu — appi näyttää
    tyhjän tilan (available=False), ei kaadu."""
    return {
        "meta": {
            "product": "GoalIQ Fantasy Phase 0 — clean sheet % + model FDR",
            "available": False,
            "season": None,
            "generated_at": None,
            "next_gameweek": None,
            "horizon_gw": 0,
        },
        "teams": [],
        "fixtures": [],
    }


def load_phase0(path: Path = PHASE0_PATH) -> dict:
    if not path.exists():
        return empty_phase0()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return empty_phase0()
    if not isinstance(data, dict) or "teams" not in data or "fixtures" not in data:
        return empty_phase0()
    return data
