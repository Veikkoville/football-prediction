"""Domestic /api/predict golden-master (#61: "domestic koskematon" automaattisena).

Vertaa nykyistä outputtia committoituun golden-JSONiin BIT-EXACT (== JSON-
round-tripin jälkeen). Caset + kentät = scripts/regression_predict.py (sama
setti jota build-gate on ajanut käsin).

Golden päivitetään TIETOISESTI: python -m tests.update_golden
(ristiintarkistaa tuotantoa vasten ennen tallennusta).

@pytest.mark.slow: fittaa 6 domestic-mallia on-demand + vaatii lokaalin
football-data-datan (downloaded_files/ gitignored) -> ei ajeta CI:ssä.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.regression_predict import CASES, NUMERIC_FIELDS

GOLDEN_PATH = Path(__file__).parent / "golden" / "domestic_predict_golden.json"

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def golden() -> dict:
    if not GOLDEN_PATH.exists():
        pytest.skip(f"golden puuttuu: {GOLDEN_PATH} — generoi: python -m tests.update_golden")
    with open(GOLDEN_PATH, encoding="utf-8") as f:
        return json.load(f)


def _case_key(league: str, home: str, away: str) -> str:
    return f"{league}|{home}-{away}"


def _extract(resp_json: dict) -> dict:
    rec = {k: resp_json.get(k) for k in NUMERIC_FIELDS}
    rec["top_scores"] = [[s["score"], s["probability"]]
                         for s in resp_json.get("top_scores", [])]
    return json.loads(json.dumps(rec))  # normalisoi JSON-round-tripilla


@pytest.mark.parametrize("league,seasons,home,away", CASES,
                         ids=[_case_key(l, h, a) for l, _, h, a in CASES])
def test_domestic_predict_matches_golden(client, golden, league, seasons, home, away):
    key = _case_key(league, home, away)
    assert key in golden, f"golden ei sisällä casea {key} — päivitä golden"
    r = client.post("/api/predict", json={
        "home_team": home, "away_team": away,
        "leagues": [league], "seasons": seasons,
    })
    assert r.status_code == 200, f"{key}: HTTP {r.status_code} {r.text[:200]}"
    current = _extract(r.json())
    expected = golden[key]

    diffs = []
    for field in NUMERIC_FIELDS:
        cv, ev = current[field], expected[field]
        if cv != ev:
            d = abs(cv - ev) if isinstance(cv, (int, float)) and isinstance(ev, (int, float)) else "type"
            diffs.append(f"{field}: golden={ev!r} nyt={cv!r} |diff|={d}")
    if current["top_scores"] != expected["top_scores"]:
        diffs.append(f"top_scores: golden={expected['top_scores']} nyt={current['top_scores']}")
    assert not diffs, f"{key} EI bit-exact:\n  " + "\n  ".join(diffs)
