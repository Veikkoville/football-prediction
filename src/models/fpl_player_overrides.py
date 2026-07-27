"""Pelaajatason minuuttiohitusten lataus (data/fpl_player_overrides.csv).

Ks. CSV:n oma otsikko perusteluineen. Lyhyesti: minuuttimalli ei erota
"ei pelannut koska ei ollut tarpeeksi hyvä" ja "ei pelannut koska oli
myynnissä tai loukkaantunut" — se näkee vain minuuttiluvun.

Väliaikainen. Hintapriori korvaa tämän.
"""

from __future__ import annotations

import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OVERRIDES_PATH = ROOT / "data" / "fpl_player_overrides.csv"


def load_player_overrides(path: Path | None = None) -> dict[int, dict]:
    """player_id -> {"p_start": float, "reason": str, "review_by": str}.

    Puuttuva tai rikkinäinen tiedosto -> tyhjä dict. Ohitusten puuttuminen ei
    saa KOSKAAN kaataa projektioajoa: ilman niitä malli on täsmälleen se mikä
    se oli ennen tätä mekanismia.
    """
    p = path or OVERRIDES_PATH
    out: dict[int, dict] = {}
    if not p.exists():
        return out
    try:
        with p.open(encoding="utf-8", newline="") as fh:
            rows = [r for r in fh if not r.lstrip().startswith("#")]
        for r in csv.DictReader(rows):
            try:
                pid = int(str(r.get("player_id", "")).strip())
                ps = float(str(r.get("p_start", "")).strip())
            except (TypeError, ValueError):
                continue
            if not 0.0 <= ps <= 1.0:
                continue
            out[pid] = {
                "p_start": ps,
                "reason": (r.get("reason") or "").strip(),
                "review_by": (r.get("review_by") or "").strip(),
            }
    except Exception as e:  # pragma: no cover — luku ei saa kaataa ajoa
        print(f"[Overrides] luku epaonnistui, jatketaan ilman: {type(e).__name__}: {e}")
        return {}
    return out
