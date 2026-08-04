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

    report_newcomers(pos_by_id)
    report_by_position(thin, thick, pct)


# ---------------------------------------------------------------------------
# EHTO 1/3 apply_price_priorin kytkennalle (27.7. peruutuksen jalkeen):
# per-positio-validointi. Peruutusmuistiinpano epaili ettei hinta erottele
# maalivahteja lainkaan (kaikki 4.0-5.5M), jolloin priori luottaisi
# informaatioon jota siina ei ole. Tama mittaa sen sen sijaan etta uskoisi.
# ---------------------------------------------------------------------------
POS_NAME = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}


def report_by_position(thin: list[dict], thick: list[dict],
                       pct: dict[int, float]) -> None:
    print("\n" + "=" * 62)
    print("EHTO 1: PER-POSITIO-VALIDOINTI (ohut otos)")
    print("=" * 62)
    print(f"{'pos':>5} {'n':>5} {'w=0':>9} {'w=0.15':>9} {'w=0.25':>9} "
          f"{'w=0.35':>9}  {'paras':>7}")
    for p in (1, 2, 3, 4):
        grp = [r for r in thin if r["pos"] == p]
        if len(grp) < 15:
            print(f"{POS_NAME[p]:>5} {len(grp):>5}   otos liian pieni")
            continue
        vals = [evaluate(grp, pct, w)[0] for w in (0.0, 0.15, 0.25, 0.35)]
        best = min(range(4), key=lambda i: vals[i])
        print(f"{POS_NAME[p]:>5} {len(grp):>5} " + " ".join(f"{v:9.4f}" for v in vals)
              + f"  {(0.0, 0.15, 0.25, 0.35)[best]:>7.2f}")
    print("\nSama paksulla otoksella (ei saa heiketa):")
    for p in (1, 2, 3, 4):
        grp = [r for r in thick if r["pos"] == p]
        if len(grp) < 15:
            print(f"{POS_NAME[p]:>5} {len(grp):>5}   otos liian pieni")
            continue
        vals = [evaluate(grp, pct, w)[0] for w in (0.0, 0.25)]
        print(f"{POS_NAME[p]:>5} {len(grp):>5} {vals[0]:9.4f} {vals[1]:9.4f}"
              f"   {'HEIKKENEE' if vals[1] > vals[0] else 'ok'}")
    print("\nHintahajonta positioittain (jos hinta ei erottele, priori ei kanna "
          "informaatiota):")
    for p in (1, 2, 3, 4):
        prices = sorted(r["price"] for r in thin + thick if r["pos"] == p)
        if not prices:
            continue
        print(f"{POS_NAME[p]:>5}  min {prices[0]:.1f}  mediaani "
              f"{prices[len(prices) // 2]:.1f}  max {prices[-1]:.1f}  "
              f"vaihteluvali {prices[-1] - prices[0]:.1f}M")


# ---------------------------------------------------------------------------
# 4.8.2026 LISÄYS: NOLLAHISTORIAN POPULAATIO
#
# Yllä oleva koe rajaa nollahistorian pelaajat POIS (build_rows: "if not prev:
# continue"), koska sekoitussuhde vaatii baselinen jota heillä ei ole. Se on
# oikein siinä kokeessa, mutta se tarkoittaa myös ettei mitään yllä olevaa
# lukua saa käyttää perusteena sille mitä tehdään pelaajalle jolla EI ole
# yhtään PL-kautta takana. Tuotannossa juuri he ovat se ryhmä joka putoaa
# projektiosta kokonaan (Tzolis, Munoz: last_season = null).
#
# Tämä osa mittaa sen populaation suoraan: pelaajat joilla EI ole 24/25
# history_pastia mutta jotka pelasivat 25/26:n. Kysymys ei ole sekoitussuhde
# vaan: ENNUSTAAKO HINTA HEIDÄN ALOITUKSIAAN, ja millä tasolla.
# ---------------------------------------------------------------------------
def build_rows_newcomers(pos_by_id: dict[int, int]) -> list[dict]:
    rows = []
    for f in sorted(glob.glob(str(SUMMARY_DIR / "*.json"))):
        d = json.loads(Path(f).read_text(encoding="utf-8"))
        hist = d.get("history") or []
        if not hist:
            continue
        pid = hist[0].get("element")
        if pid is None or pid not in pos_by_id:
            continue
        prev = next((h for h in (d.get("history_past") or [])
                     if h.get("season_name") == PREV_SEASON), None)
        if prev:
            continue                      # <-- tässä kokeessa VAIN historiattomat
        gw1 = next((h for h in hist if h.get("round") == 1), None)
        if not gw1 or not gw1.get("value"):
            continue
        window = [h for h in hist if 1 <= (h.get("round") or 0) <= HORIZON]
        if len(window) < HORIZON:
            continue
        rows.append({
            "pid": pid, "pos": pos_by_id[pid], "price": (gw1["value"] or 0) / 10.0,
            "act_starts": sum(h.get("starts", 0) or 0 for h in window),
        })
    return rows


def report_newcomers(pos_by_id: dict[int, int]) -> None:
    rows = build_rows_newcomers(pos_by_id)
    print("\n" + "=" * 62)
    print(f"NOLLAHISTORIA: ei 24/25 PL-kautta, pelasi 25/26  (n={len(rows)})")
    print("=" * 62)
    if len(rows) < 20:
        print("Otos liian pieni johtopäätökseen.")
        return
    pct = price_percentile(rows)
    bands = (("KALLEIN 25 %", 0.75, 1.01), ("2. neljännes", 0.50, 0.75),
             ("3. neljännes", 0.25, 0.50), ("HALVIN 25 %", 0.0, 0.25))
    print(f"{'ryhmä':>14} {'n':>5} {'toteutunut aloitusosuus':>25}")
    fitted = {}
    for label, lo, hi in bands:
        grp = [r for r in rows if lo <= pct[r["pid"]] < hi]
        if not grp:
            continue
        act = sum(r["act_starts"] for r in grp) / len(grp) / HORIZON
        fitted[label] = act
        print(f"{label:>14} {len(grp):>5} {act:>25.2f}")

    # Vertailu tuotannon nykyiseen nousijaprioriin (0.72 / 0.30 / 0.08).
    print("\nTuotannon nousijapriori antaa tälle ryhmälle 0.72 / 0.30 / 0.08 "
          "(hintajärjestys klubin sisällä).")
    # Brier: vakiopriori per ryhmä vs koko populaation keskiarvo
    base = sum(r["act_starts"] for r in rows) / len(rows) / HORIZON
    b_flat = sum((base - r["act_starts"] / HORIZON) ** 2 for r in rows) / len(rows)
    b_band = 0.0
    for label, lo, hi in bands:
        grp = [r for r in rows if lo <= pct[r["pid"]] < hi]
        if not grp:
            continue
        p = fitted[label]
        b_band += sum((p - r["act_starts"] / HORIZON) ** 2 for r in grp)
    b_band /= len(rows)
    print(f"\nBrier, sama luku kaikille ({base:.2f}): {b_flat:.4f}")
    print(f"Brier, hintaryhmittäin:               {b_band:.4f} "
          f"({(b_flat - b_band) / b_flat * 100:+.1f} %)")
    print("\nTULKINTA: hinta on informatiivinen tälle ryhmälle vain jos "
          "ryhmittäinen Brier on selvästi parempi JA aloitusosuus laskee "
          "monotonisesti hinnan mukana. Jos ei, historiattomille ei pidä "
          "antaa hintaprioria vaan jättää heidät projektion ulkopuolelle "
          "kuten nyt.")
    report_production_tiers(rows, pos_by_id)


# Tuotannon nousijapriori ei valitse hintapersentiilillä vaan KLUBIN SISÄISELLÄ
# hintajärjestyksellä positioryhmässä (slots ~= tyypillinen XI). Se on eri
# valinta kuin liigatason persentiili, joten tasot on mitattava samalla
# säännöllä jolla ne tuotannossa jaetaan — muuten luku on arvaus vaikka
# ympärillä olisi backtest.
PROD_SLOTS = {1: 1, 2: 4, 3: 4, 4: 2}


def report_production_tiers(rows: list[dict], pos_by_id: dict[int, int]) -> None:
    boot = json.loads(ARCHIVE.read_text(encoding="utf-8"))
    team_of = {e["id"]: e["team"] for e in boot["elements"]}
    # Hintajärjestys KOKO klubi+positio-ryhmästä (kuten tuotannossa: myös
    # historialliset pelaajat kilpailevat paikoista), mutta mitataan vain
    # historiattomat.
    price_of = {e["id"]: (e.get("now_cost") or 0) for e in boot["elements"]}
    newcomer = {r["pid"]: r for r in rows}
    tier_of: dict[int, int] = {}
    clubs = {(e["team"], e["element_type"]) for e in boot["elements"]}
    for team, etype in clubs:
        grp = sorted((e["id"] for e in boot["elements"]
                      if e["team"] == team and e["element_type"] == etype),
                     key=lambda pid: (-price_of[pid], pid))
        slots = PROD_SLOTS[etype]
        for rank, pid in enumerate(grp):
            if pid in newcomer:
                tier_of[pid] = 0 if rank < slots else (1 if rank < slots + 2 else 2)

    print("\n" + "=" * 62)
    print("TUOTANNON VALINTASÄÄNTÖ (klubi+positio, hintajärjestys)")
    print("=" * 62)
    current = (0.72, 0.30, 0.08)
    names = ("tier 0 (XI-slotit)", "tier 1 (2 seuraavaa)", "tier 2 (loput)")
    print(f"{'ryhmä':>22} {'n':>4} {'toteutunut':>11} {'tuotannossa':>12}")
    fitted = []
    for t in (0, 1, 2):
        grp = [newcomer[p] for p, tt in tier_of.items() if tt == t]
        if not grp:
            fitted.append(None)
            continue
        act = sum(r["act_starts"] for r in grp) / len(grp) / HORIZON
        fitted.append(act)
        print(f"{names[t]:>22} {len(grp):>4} {act:>11.2f} {current[t]:>12.2f}")

    b_cur = b_fit = 0.0
    n = 0
    for pid, t in tier_of.items():
        a = newcomer[pid]["act_starts"] / HORIZON
        b_cur += (current[t] - a) ** 2
        b_fit += ((fitted[t] if fitted[t] is not None else current[t]) - a) ** 2
        n += 1
    print(f"\nBrier nykyisillä tasoilla: {b_cur / n:.4f}")
    print(f"Brier mitatuilla tasoilla: {b_fit / n:.4f} "
          f"({(b_cur / n - b_fit / n) / (b_cur / n) * 100:+.1f} %)")
    print("HUOM: mitatut tasot on sovitettu TÄHÄN otokseen, joten niiden etu "
          "on yläraja eikä ulkoinen validointi. Suunta (nykyinen 0.72 vs "
          "toteutunut) on silti luettavissa.")

    # -----------------------------------------------------------------
    # Ansaitseeko NOUSIJASEURA oman tasonsa?
    #
    # Rakenteellinen argumentti sanoo kylla: nousijan XI koostuu lahes
    # kokonaan historiattomista, eli jonkun heista ON aloitettava. Yhteinen
    # taso tekee koko joukkueesta ohuen (tuotannossa Sum(p_start) putosi
    # nousijoilla 9.7 -> 7.6, kun sen pitaisi olla ~11). Mutta rakenteellinen
    # argumentti ei ole mittaus, ja edellinen kerta kun tama priori kytkettiin
    # rakenteellisella perustelulla, se peruutettiin.
    #
    # Nousijaseurat tunnistetaan DATASTA eika listalta: 25/26:n seura jonka
    # pelaajilla ei kertynyt 24/25 PL-minuutteja on noussut.
    # -----------------------------------------------------------------
    prev_mins_by_team: dict[int, float] = {}
    for f in glob.glob(str(SUMMARY_DIR / "*.json")):
        d = json.loads(Path(f).read_text(encoding="utf-8"))
        hist = d.get("history") or []
        if not hist:
            continue
        pid = hist[0].get("element")
        prev = next((h for h in (d.get("history_past") or [])
                     if h.get("season_name") == PREV_SEASON), None)
        t = team_of.get(pid)
        if t is None:
            continue
        prev_mins_by_team[t] = prev_mins_by_team.get(t, 0.0) + (
            (prev or {}).get("minutes", 0) or 0)
    ranked_teams = sorted(prev_mins_by_team, key=lambda t: prev_mins_by_team[t])
    promoted_ids = set(ranked_teams[:3])
    name_of = {t["id"]: t["name"] for t in boot["teams"]}
    print("\nNousijaseurat datasta (vähiten 24/25 PL-minuutteja):")
    for t in ranked_teams[:5]:
        mark = "  <- nousija" if t in promoted_ids else ""
        print(f"   {name_of.get(t, t):<18} {prev_mins_by_team[t]:>8.0f} min{mark}")

    print(f"\n{'ryhmä':>34} {'n':>4} {'toteutunut':>11}")
    for tlabel, tsel in (("NOUSIJA", lambda p: team_of.get(p) in promoted_ids),
                         ("vakiintunut", lambda p: team_of.get(p) not in promoted_ids)):
        for t in (0, 1):
            grp = [newcomer[p] for p, tt in tier_of.items() if tt == t and tsel(p)]
            if len(grp) < 8:
                print(f"{tlabel + ' tier ' + str(t):>34} {len(grp):>4} "
                      f"{'otos liian pieni':>11}")
                continue
            act = sum(r["act_starts"] for r in grp) / len(grp) / HORIZON
            print(f"{tlabel + ' tier ' + str(t):>34} {len(grp):>4} {act:>11.2f}")
    print("\nTULKINTA: nousijoille annetaan oma taso VAIN jos ero vakiintuneisiin "
          "on suurempi kuin otoksen keskivirhe. Muuten yhteinen taso jää voimaan "
          "ja joukkuetason ohuus kirjataan avoimeksi.")


if __name__ == "__main__":
    main()
