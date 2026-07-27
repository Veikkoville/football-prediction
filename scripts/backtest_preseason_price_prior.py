"""Esikausi-backtest: auttaako HINTA kun edelliskauden minuutit ovat harhaanjohtavia?

MIKSI TÄMÄ ON ERI KOE KUIN backtest_fpl_minutes / backtest_fpl_xp
Ne mittaavat GW2-38 pelanneiden populaatiossa, eli tilanteessa jossa mallilla
ON tuoretta kausidataa. Hintapriorin koko arvo on päinvastaisessa tilanteessa:
esikaudella edelliskauden minuutit ovat ainoa signaali, ja jos ne ovat
harhaanjohtavia (siirtosaaga, loukkaantuminen), estimaatti on väärä.
Nykyisellä portilla ajettuna priori näyttäisi todennäköisesti "ei eroa" — ja
se olisi väärä johtopäätös väärästä koeasetelmasta.

KOEASETELMA (tasan se tilanne jossa nyt ollaan, 27.7.2026)
  Syötteet, jotka tiedettiin ENNEN 25/26 GW1:tä:
    - 24/25 minuutit + avaukset      (history_past, season_name "2024/25")
    - hinta 25/26 GW1:ssä            (history[round==1].value; FPL asettaa
                                      hinnat ennen kauden alkua -> ei vuoda)
  Kohde:
    - toteutuneet avaukset ja minuutit 25/26 GW1-6

  A  BASELINE   p_start = 24/25 avaukset / 38
  B  HINTAPRIORI  A sekoitettuna position sisäiseen hintapersentiiliin

Mitataan koko populaatiossa JA erikseen OHUEN OTOKSEN alaryhmässä (< 900 min
24/25), koska juuri siellä priorin pitäisi auttaa. Jos se auttaa vain koko
populaatiossa muttei ohuessa, se ei ratkaise Isakin ongelmaa.

Read-only: ei kirjoita tuotantodataa.
Ajo: .venv/Scripts/python.exe scripts/backtest_preseason_price_prior.py
"""

from __future__ import annotations

import glob
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SUMMARY_DIR = ROOT / "data" / "raw" / "fpl" / "summary_2526"
ARCHIVE = ROOT / "data" / "raw" / "fpl" / "bootstrap_static_2526.archive.json"

PREV_SEASON = "2024/25"
HORIZON = 6
ROUNDS_PREV = 38
THIN_MINUTES = 900  # alle tämän 24/25 = "ohut otos" (~10 täyttä ottelua)


def load_positions() -> dict[int, int]:
    """element_id -> element_type (1 GKP, 2 DEF, 3 MID, 4 FWD)."""
    boot = json.loads(ARCHIVE.read_text(encoding="utf-8"))
    return {e["id"]: e["element_type"] for e in boot["elements"]}


def build_rows(pos_by_id: dict[int, int]) -> list[dict]:
    rows = []
    for f in sorted(glob.glob(str(SUMMARY_DIR / "*.json"))):
        d = json.loads(Path(f).read_text(encoding="utf-8"))
        hist = d.get("history") or []
        if not hist:
            continue
        pid = hist[0].get("element")
        if pid is None or pid not in pos_by_id:
            continue

        prev = next(
            (h for h in (d.get("history_past") or [])
             if h.get("season_name") == PREV_SEASON),
            None,
        )
        if not prev:
            continue  # ei edelliskautta -> esikausiennustetta ei voi tehdä tästä priorista

        gw1 = next((h for h in hist if h.get("round") == 1), None)
        if not gw1 or not gw1.get("value"):
            continue

        window = [h for h in hist if 1 <= (h.get("round") or 0) <= HORIZON]
        if len(window) < HORIZON:
            continue

        rows.append({
            "pid": pid,
            "pos": pos_by_id[pid],
            "prev_minutes": prev.get("minutes", 0) or 0,
            "prev_starts": prev.get("starts", 0) or 0,
            "price": (gw1["value"] or 0) / 10.0,
            "act_starts": sum(h.get("starts", 0) or 0 for h in window),
            "act_minutes": sum(h.get("minutes", 0) or 0 for h in window),
        })
    return rows


def price_percentile(rows: list[dict]) -> dict[int, float]:
    """Hintapersentiili POSITION SISÄLLÄ (0..1). Positioiden välinen vertailu
    olisi merkityksetön: 5.5M puolustaja ja 5.5M hyökkääjä ovat eri rooleja."""
    out: dict[int, float] = {}
    for pos in {r["pos"] for r in rows}:
        grp = sorted([r for r in rows if r["pos"] == pos], key=lambda r: r["price"])
        n = len(grp)
        for i, r in enumerate(grp):
            out[r["pid"]] = i / max(n - 1, 1)
    return out


def evaluate(rows: list[dict], pct: dict[int, float], w: float) -> tuple[float, float]:
    """Palauta (Brier p_start, MAE xMins) painolla w hintapriorille.

    w=0 -> puhdas baseline (edelliskauden avaukset).
    Minuutit johdetaan p_startista karkeasti (p_start * 90) — tarkoitus on
    verrata KAHTA MALLIA keskenään, ei tuottaa tuotantominuutteja.
    """
    brier = 0.0
    mae = 0.0
    for r in rows:
        base = r["prev_starts"] / ROUNDS_PREV
        p = (1 - w) * base + w * pct[r["pid"]]
        p = min(max(p, 0.0), 1.0)
        # Brier per ottelu horisontissa: toteutunut aloitusosuus
        act_rate = r["act_starts"] / HORIZON
        brier += (p - act_rate) ** 2
        mae += abs(p * 90.0 * HORIZON - r["act_minutes"]) / HORIZON
    n = max(len(rows), 1)
    return brier / n, mae / n


def report(label: str, rows: list[dict], pct: dict[int, float]) -> None:
    print(f"\n=== {label}  (n={len(rows)}) ===")
    print(f"{'paino w':>9} {'Brier':>9} {'MAE min':>9}   huom")
    best = None
    for w in (0.0, 0.15, 0.25, 0.35, 0.50, 0.75, 1.0):
        b, m = evaluate(rows, pct, w)
        tag = "baseline" if w == 0.0 else ("pelkka hinta" if w == 1.0 else "")
        print(f"{w:9.2f} {b:9.4f} {m:9.2f}   {tag}")
        if best is None or b < best[1]:
            best = (w, b, m)
    b0, m0 = evaluate(rows, pct, 0.0)
    print(f"  paras w={best[0]:.2f}: Brier {b0:.4f} -> {best[1]:.4f} "
          f"({(b0 - best[1]) / b0 * 100:+.1f} %), MAE {m0:.2f} -> {best[2]:.2f}")


def main() -> None:
    pos_by_id = load_positions()
    rows = build_rows(pos_by_id)
    if not rows:
        print("Ei rivejä — tarkista summary_2526 / archive-bootstrap.")
        return
    pct = price_percentile(rows)

    report("KOKO POPULAATIO", rows, pct)

    thin = [r for r in rows if r["prev_minutes"] < THIN_MINUTES]
    report(f"OHUT OTOS (24/25 alle {THIN_MINUTES} min)", thin, pct)

    thick = [r for r in rows if r["prev_minutes"] >= THIN_MINUTES]
    report(f"PAKSU OTOS (24/25 vähintään {THIN_MINUTES} min)", thick, pct)

    # ------------------------------------------------------------------
    # RATKAISEVA TESTI: erotteleeko priori OIKEAT pelaajat?
    #
    # Ohut otos sisältää KAKSI täysin eri populaatiota:
    #   kallis + vähän minuutteja  = Isak-tapaus (hyvä, harhaanjohtava otos)
    #   halpa  + vähän minuutteja  = aito reservi (matala p_start on OIKEIN)
    # Jos priori nostaa molempia, se on hyödytön — se vain siirtää kaikkia
    # kohti keskiarvoa. Sen ARVO on siinä että hinta erottaa nämä toisistaan.
    #
    # MAE jätetään tästä pois tarkoituksella: p_start * 90 ei ole minuutti-
    # malli (50 % aloitus-tn ei ole 45 min vaan joko ~80 tai ~0), joten se
    # mittaisi eri asiaa kuin mitä tässä päätetään. Brier on oikea
    # pisteytyssääntö binääriselle aloitustapahtumalle.
    # ------------------------------------------------------------------
    print("\n" + "=" * 62)
    print("RATKAISEVA: ohut otos jaettuna hinnan mukaan")
    print("=" * 62)
    for label, sel in (
        ("KALLIS + ohut  (Isak-tapaus)", lambda r: pct[r["pid"]] >= 0.70),
        ("KESKI  + ohut", lambda r: 0.30 <= pct[r["pid"]] < 0.70),
        ("HALPA  + ohut  (aito reservi)", lambda r: pct[r["pid"]] < 0.30),
    ):
        grp = [r for r in thin if sel(r)]
        if not grp:
            continue
        b0, _ = evaluate(grp, pct, 0.0)
        b1, _ = evaluate(grp, pct, 0.25)
        avg_act = sum(r["act_starts"] for r in grp) / len(grp) / HORIZON
        avg_base = sum(r["prev_starts"] / ROUNDS_PREV for r in grp) / len(grp)
        delta = (b0 - b1) / b0 * 100 if b0 else 0.0
        print(f"\n{label}  (n={len(grp)})")
        print(f"  Brier {b0:.4f} -> {b1:.4f}  ({delta:+.1f} %)")
        print(f"  baseline arvioi aloitusosuudeksi {avg_base:.2f}, "
              f"TOTEUTUNUT {avg_act:.2f}")

    print("\nTULKINTAOHJE: hintapriori on perusteltu vain jos se parantaa "
          "OHUTTA otosta EIKÄ heikennä paksua — ja ennen kaikkea jos se "
          "parantaa KALLISTA ohutta ryhmää enemmän kuin halpaa. Jos se "
          "nostaa kaikkia tasaisesti, se on keskiarvoon vetämistä eikä "
          "informaatiota.")


if __name__ == "__main__":
    main()
