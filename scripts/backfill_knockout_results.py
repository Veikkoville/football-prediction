"""WC-pudotuspelitulosten backfill international_results.csv:hen (recent-form).

ONGELMA: /api/team last_5/form lukee international_results.csv:stä, jonka
loader pudottaa NA-tulosrivit → pelatut knockoutit (NA-fixtureina CSV:ssä)
eivät näy ja recent-form jäätyy viimeiseen täytettyyn tulokseen.

RATKAISU: hae FT-tulokset football-data.org:sta (SAMA autoritatiivinen lähde
josta accuracy-pipeline reconciloi; sama _disp_score-konventio = reg+jatkoaika
ILMAN rangaistuspotkuja, kuten martj42) ja:
  - TÄYTÄ olemassa olevien NA-rivien tulokset (upsert, ei ylikirjoita täytettyä),
  - APPENDAA puuttuvat pelatut WC-ottelut (esim. R16+ joita ei ole fixtureina).

EI KOSKAAN regeneroi eikä poista rivejä (ks. muisti: regen pudotti backfillit).
Rivimäärä jälkeen >= ennen, kova assert. city/country appendeissa jää tyhjäksi
(malli ei lue niitä; seuraava martj42-upstream-sync normalisoi).

Ajo: python -m scripts.backfill_knockout_results
     (FOOTBALL_DATA_API_KEY ympäristöstä, kuten accuracy_pipeline)
Exit: 0 = ok (myös "ei muutoksia"), 1 = tekninen virhe.

Tulosdataa, EI mallia → ship-gate ei koske. Deploy = commit + push (Render).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

import config
from scripts.accuracy_pipeline import _disp_score, _fetch_wc_matches
from src.data.wc_teams import resolve_wc_name

CSV_PATH = config.DATA_DIR / "international_results.csv"
WC_START = "2026-06-11"  # turnauksen avauspäivä — vanhempia ei kosketa


def _canon(name: str) -> str:
    r = resolve_wc_name(name)
    return r if r is not None else name


def main() -> int:
    # 1. Lue CSV merkkijonoina — "NA" säilyy literaalina, ei muunnoksia muihin
    #    riveihin (fill/append-only, kirjoitus säilyttää sarakkeet + järjestyksen).
    df = pd.read_csv(CSV_PATH, dtype=str, keep_default_na=False, encoding="utf-8")
    n_before = len(df)
    print(f"CSV: {n_before} riviä ennen backfilliä.")

    # 2. Indeksoi 2026-WC-rivit kanonisoiduilla nimillä (FD-nimi <-> martj42-nimi
    #    -erot, esim. Cape Verde/Cape Verde Islands, ratkeaa resolve_wc_name:lla).
    wc_mask = (df["tournament"] == "FIFA World Cup") & df["date"].ge(WC_START)
    by_key: dict[tuple[str, str, str], int] = {}
    by_pair: dict[tuple[str, str], list[tuple[str, int]]] = {}
    csv_name: dict[str, str] = {}  # kanoninen -> CSV:n nimikonventio (appendeille)
    for idx in df.index[wc_mask]:
        h, a = _canon(df.at[idx, "home_team"]), _canon(df.at[idx, "away_team"])
        d = df.at[idx, "date"]
        by_key[(d, h, a)] = idx
        by_pair.setdefault((h, a), []).append((d, idx))
        csv_name.setdefault(h, df.at[idx, "home_team"])
        csv_name.setdefault(a, df.at[idx, "away_team"])

    # 3. FD:n pelatut WC-ottelut
    matches = _fetch_wc_matches()
    if matches is None:
        print("VIRHE: football-data.org-haku epäonnistui (avain/verkko).")
        return 1

    filled: list[str] = []
    appended: list[str] = []
    warned: list[str] = []
    for m in matches:
        if m.get("status") != "FINISHED":
            continue
        date = (m.get("utcDate") or "")[:10]
        if date < WC_START:
            continue
        home = (m.get("homeTeam") or {}).get("name")
        away = (m.get("awayTeam") or {}).get("name")
        disp = _disp_score(m)
        if not home or not away or disp is None:
            continue
        ch, ca = _canon(home), _canon(away)

        def _find(h: str, a: str) -> int | None:
            i = by_key.get((date, h, a))
            if i is not None:
                return i
            # ±1 pv toleranssi (UTC- vs. paikallispäivä fixture-riveissä)
            cands = [
                (d, i) for d, i in by_pair.get((h, a), [])
                if abs((pd.Timestamp(d) - pd.Timestamp(date)).days) <= 1
            ]
            return cands[0][1] if cands else None

        idx = _find(ch, ca)
        swapped = False
        if idx is None:
            # FD:n koti/vieras-designaatio voi olla käänteinen CSV:n riviin
            # nähden (esim. CSV "Canada,Switzerland,1,2" vs FD "Switzerland
            # 2-1 Canada") → tarkista käännetty pari ENNEN appendia, muuten
            # syntyy duplikaattiottelu käänteisellä orientaatiolla.
            idx = _find(ca, ch)
            if idx is not None:
                swapped = True
                disp = (disp[1], disp[0])  # tulos CSV-rivin orientaatioon

        label = f"{date} {ch if not swapped else ca} {disp[0]}-{disp[1]} {ca if not swapped else ch}"
        if idx is not None:
            hs, as_ = df.at[idx, "home_score"], df.at[idx, "away_score"]
            if hs in ("NA", "") or as_ in ("NA", ""):
                df.at[idx, "home_score"] = str(disp[0])
                df.at[idx, "away_score"] = str(disp[1])
                filled.append(label)
            elif (hs, as_) != (str(disp[0]), str(disp[1])):
                warned.append(f"{label} — CSV:ssä jo {hs}-{as_}, EI ylikirjoitettu")
            continue

        # Riviä ei ole → appendaa (esim. R16+ joita ei fixture-riveinä).
        new_row = {c: "" for c in df.columns}
        new_row.update(
            {
                "date": date,
                "home_team": csv_name.get(ch, home),
                "away_team": csv_name.get(ca, away),
                "home_score": str(disp[0]),
                "away_score": str(disp[1]),
                "tournament": "FIFA World Cup",
                "neutral": "TRUE",
            }
        )
        df.loc[len(df)] = new_row
        appended.append(label + " (append; city/country tyhjä, martj42-sync normalisoi)")

    print(f"\nTÄYTETTY {len(filled)} NA-riviä:")
    for s in filled:
        print(f"  {s}")
    print(f"APPENDATTU {len(appended)} uutta riviä:")
    for s in appended:
        print(f"  {s}")
    for s in warned:
        print(f"  VAROITUS: {s}")

    if not filled and not appended:
        print("\nEi muutoksia — CSV ajan tasalla.")
        return 0

    # 4. Union-todiste + kirjoitus (LF, minimal quoting = alkuperäinen muoto).
    assert len(df) >= n_before, "Rivimäärä pieneni — EI kirjoiteta (regen-suoja)."
    df.to_csv(CSV_PATH, index=False, encoding="utf-8", lineterminator="\n")
    print(f"\nCSV: {n_before} -> {len(df)} riviä (union, ei droppeja).")
    print("Deploy: git add data/international_results.csv && commit + push (Render).")
    print('Verify: curl "https://goaliq-api.onrender.com/api/team/Canada?leagues=INT-World+Cup&seasons=26"')
    return 0


if __name__ == "__main__":
    sys.exit(main())
