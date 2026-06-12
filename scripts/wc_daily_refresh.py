"""WC-ikkunan päivittäinen virkistystarkistus (Task Scheduler, klo 09:00).

Lataa martj42-snapshotin MUISTIIN (ei kirjoita levylle) ja vertaa: onko uusia
PELATTUJA WC 2026 -tuloksia vs. vendoroitu data/international_results.csv?
  - Ei uusia        -> exit 0 hiljaa (ei tulostetta, ei raporttia).
  - Uusia tuloksia  -> aja scripts.refresh_wc_model (kova ship-gate):
      PASS  -> tulosta gate-diff + valmiit git-komennot Villen hyväksyttäväksi.
      NO-GO -> refresh tulostaa diff-raportin ja palauttaa backupin.

EI KOSKAAN auto-pushia eikä auto-deployta — push on aina Villen manuaalinen
päätös (Render auto-deployaa mainista).

Aja repojuuresta: python -m scripts.wc_daily_refresh
"""
from __future__ import annotations

import io
import subprocess
import sys
import urllib.request
from datetime import date

import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from scripts.update_international_results import URL, DEST

WINDOW = (date(2026, 6, 12), date(2026, 7, 19))  # WC 2026 avaus -> finaali


def _completed_wc_results(df: pd.DataFrame) -> int:
    d = pd.to_datetime(df["date"], errors="coerce")
    wc = df[(df["tournament"] == "FIFA World Cup") & (d.dt.year >= 2026)]
    return int(wc["home_score"].notna().sum())


def main() -> int:
    today = date.today()
    if not (WINDOW[0] <= today <= WINDOW[1]):
        return 0  # WC-ikkunan ulkopuolella — ei mitään

    req = urllib.request.Request(URL, headers={"User-Agent": "goaliq-update/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read()
    if not data or b"home_team" not in data[:200]:
        print("VIRHE: martj42-payload epäkelpo (home_team puuttuu) — ei ajeta putkea.")
        return 2

    fresh = _completed_wc_results(pd.read_csv(io.BytesIO(data)))
    current = _completed_wc_results(pd.read_csv(DEST))
    if fresh <= current:
        return 0  # ei uusia WC-tuloksia edellisestä ajosta — exit hiljaa

    print(f"Uusia WC 2026 -tuloksia: {fresh - current} (snapshot {fresh}, "
          f"vendoroitu {current}) — ajetaan virkistysputki + ship-gate.\n")
    rc = subprocess.run(
        [sys.executable, "-m", "scripts.refresh_wc_model"]).returncode

    if rc == 0:
        print("\n" + "#" * 60)
        print("# GATE PASS — ODOTTAA VILLEN HYVÄKSYNTÄÄ (ei auto-pushia)")
        print("# Tarkista yllä oleva gate-diff ja aja repojuuresta:")
        print("#   git add data/international_results.csv data/elo_ratings.csv data/wc_model.json")
        print('#   git commit -m "data: WC-mallin virkistys (gate PASS)"')
        print("#   git push   <- Render auto-deployaa mainista")
        print("# Hylkäys: git checkout -- data/")
        print("#" * 60)
    return rc


if __name__ == "__main__":
    sys.exit(main())
