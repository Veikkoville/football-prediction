"""ROLE-CHANGE-WATCH — seula roolimuutoksille (14.8.2026).

Spec: cos-reports/role-change-watch-spec-2026-08-14.md (goaliq-app-hub).

ONGELMA. Minuuttimalli kayttaa priorina viime kauden minuutteja eika nae
esikauden roolimuutosta. Kaksi tapausta loytyi 14.8 SATTUMALTA, molemmat
livena, eika kumpaakaan loytanyt yksikaan portti:
  * Kinsky (TOT): 19,5 % omistettu ALOITTAVA maalivahti puuttui projektiosta
    kokonaan. Loytyi vain koska Ville luki artikkelin ja kysyi.
  * Dubravka (TOT): varamies projisoi ykkosen ohi (3 150 min Newcastlessa).
    Loytyi vain koska Kinskyn korjaus paljasti sen.

YDINOIVALLUS. Ei tarvitse kayda lapi 587 pelaajaa. Etsitaan ne joissa
MARKKINA JA MALLI OVAT ERI MIELTA — omistusprosentti on ilmainen, elava
joukkoaly siita kuka aloittaa.

  suunta A: markkina odottaa peliaikaa, me emme
      A1 = FPL:n listalla omistettu mutta EI RIVIA meilla lainkaan (Kinsky)
      A2 = rivi on, mutta p_start on matala vaikka omistus on korkea
  suunta B: me odotamme peliaikaa, markkina ei
      korkea xP + matala omistus. TAMA EI OLE AUTOMAATTISESTI VIKA —
      Struijk (xP6 23,8 / 0,4 %) osoittautui aidoksi differentiaaliksi
      (20 M£ siirto Brightoniin). Vahdin tehtava on erottaa nama kaksi.

🔴 EI KOSKAAN AUTOMAATTISTA SOVELTAMISTA. Tama tulostaa EHDOTUKSIA. Ohitus
on kasin tehty paatos lahdeviitteella, ja `review_by` pakottaa
uusintatarkistuksen. Sama kaava kuin Isak/Kinsky/Dubravka.

🔴 EGRESS. GitHub-runnerin egress on GitHub-only, joten tama EI aja
GitHub Actionsissa: FPL-bootstrap ei ole tavoitettavissa sielta. Ajetaan
paikallisesti (Villen kone / CC-sessio). Seula on ilmainen; vain
shortlistin uutishaku vaatii verkkoa ja se tehdaan erikseen.

Kaytto:
    python -m scripts.role_change_watch
    python -m scripts.role_change_watch --top-b 15
    python -m scripts.role_change_watch --offline   # vain B + A2
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests

import config
from src.models.fpl_player_overrides import load_player_overrides

XP_PATH = config.PROJECT_ROOT / "data" / "fpl_xp_projections.json"
FPL_BASE = "https://fantasy.premierleague.com/api"
FPL_HEADERS = {"User-Agent": "Mozilla/5.0 (GoalIQ role-change watch)"}

POS = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}


def load_projection() -> tuple[dict[int, dict], dict]:
    if not XP_PATH.exists():
        raise SystemExit(f"VIRHE: {XP_PATH.name} puuttuu.")
    data = json.loads(XP_PATH.read_text(encoding="utf-8"))
    by_id = {int(p["id"]): p for p in (data.get("players") or []) if p.get("id")}
    return by_id, (data.get("meta") or {})


def fetch_bootstrap() -> list[dict]:
    r = requests.get(f"{FPL_BASE}/bootstrap-static/", headers=FPL_HEADERS,
                     timeout=30)
    r.raise_for_status()
    return r.json().get("elements") or []


def _owned(el: dict) -> float:
    try:
        return float(el.get("selected_by_percent") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def direction_a(ours: dict[int, dict], elements: list[dict],
                min_owned: float, max_p_start: float,
                overrides: dict) -> tuple[list[dict], list[dict]]:
    """(A1 puuttuvat, A2 matala p_start). Ohitetut merkitaan, ei piiloteta."""
    a1, a2 = [], []
    for el in elements:
        pid = int(el["id"])
        owned = _owned(el)
        if owned < min_owned:
            continue
        # Saatavuuslippu kattaa loukkaantumiset jo (status i/s/u/n) — TAMA
        # vika on nimenomaan pelaaja jonka lippu on 'a' mutta rooli muuttunut.
        # Kinskyn lippu oli 'a'.
        if (el.get("status") or "a") != "a":
            continue
        mine = ours.get(pid)
        row = {
            "id": pid,
            "web_name": el.get("web_name"),
            "pos": POS.get(el.get("element_type"), "?"),
            "owned": owned,
            "overridden": pid in overrides,
        }
        if mine is None:
            a1.append(row)
            continue
        p_start = float(mine.get("p_start") or 0.0)
        if p_start < max_p_start:
            row["p_start"] = p_start
            row["xp6"] = float(mine.get("xp_horizon_total") or 0.0)
            a2.append(row)
    a1.sort(key=lambda r: -r["owned"])
    # ERIMIELISYYDEN MASSA, ei pelkka omistus. `owned * (1 - p_start)` =
    # kuinka moni managerin odotus on ristiriidassa mallin kanssa. Pelkalla
    # omistuksella lajiteltuna karkeen nousi varamaalivahteja joiden matala
    # p_start on OIKEIN — ne ovat kohinaa, eivat loydoksia.
    for r in a2:
        r["mass"] = r["owned"] * (1.0 - r["p_start"])
    a2.sort(key=lambda r: -r["mass"])
    return a1, a2


def direction_a3(ours: dict[int, dict], elements: list[dict],
                 overrides: dict, min_owned: float = 1.0) -> list[dict]:
    """SEURAN SISAINEN RISTIRIITA — tama on se kuvio joka meilta meni ohi.

    Jos seuran OMISTETUIN pelaaja jossain positiossa ei ole se jolla on
    korkein `p_start`, markkina ja malli ovat eri mielta siita KUKA on
    ykkonen. Tasan tama oli Kinsky/Dubravka: malli piti Dubravkaa ykkosena
    (3 150 min Newcastlessa) kun markkina omisti Kinskya.

    Rajattu maalivahteihin ja hyokkaajiin: niissa on yksi paikka, joten
    "kuka on ykkonen" on aito binaarinen kysymys. Puolustus ja keskikentta
    rotatoivat normaalisti eika ero ole siella ristiriita.
    """
    by_club_pos: dict[tuple, list[dict]] = {}
    for el in elements:
        if (el.get("status") or "a") != "a":
            continue
        pos = POS.get(el.get("element_type"))
        if pos not in ("GKP",):
            continue
        mine = ours.get(int(el["id"]))
        if mine is None:
            continue
        by_club_pos.setdefault((el.get("team"), pos), []).append({
            "id": int(el["id"]),
            "web_name": el.get("web_name"),
            "pos": pos,
            "team": mine.get("team_short"),
            "owned": _owned(el),
            "p_start": float(mine.get("p_start") or 0.0),
        })
    out = []
    for rows in by_club_pos.values():
        if len(rows) < 2:
            continue
        most_owned = max(rows, key=lambda r: r["owned"])
        top_start = max(rows, key=lambda r: r["p_start"])
        if most_owned["id"] == top_start["id"]:
            continue
        if most_owned["owned"] < min_owned:
            continue
        out.append({
            "team": most_owned["team"],
            "pos": most_owned["pos"],
            "market": most_owned,
            "model": top_start,
            "overridden": (most_owned["id"] in overrides
                           or top_start["id"] in overrides),
        })
    out.sort(key=lambda r: -r["market"]["owned"])
    return out


def direction_b(ours: dict[int, dict], min_xp: float, max_owned: float,
                overrides: dict) -> list[dict]:
    out = []
    for pid, p in ours.items():
        xp6 = float(p.get("xp_horizon_total") or 0.0)
        owned = float(p.get("owned_pct") or 0.0)
        if xp6 >= min_xp and owned < max_owned:
            out.append({
                "id": pid,
                "web_name": p.get("web_name"),
                "pos": p.get("pos"),
                "team": p.get("team_short"),
                "owned": owned,
                "xp6": xp6,
                "p_start": float(p.get("p_start") or 0.0),
                "overridden": pid in overrides,
            })
    out.sort(key=lambda r: -r["xp6"])
    return out


def _print(rows, cols, empty="  (ei yhtaan)"):
    if not rows:
        print(empty)
        return
    for r in rows:
        mark = "  [OHITETTU JO]" if r.get("overridden") else ""
        print("  " + cols(r) + mark)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-owned", type=float, default=0.5,
                    help="suunta A: omistuskynnys %% (oletus 0.5)")
    ap.add_argument("--max-p-start", type=float, default=0.35,
                    help="suunta A2: p_start jonka alle liputetaan")
    ap.add_argument("--b-min-xp", type=float, default=12.0)
    ap.add_argument("--b-max-owned", type=float, default=1.0)
    ap.add_argument("--top-a2", type=int, default=15,
                    help="montako suunnan A2 nimea listataan")
    ap.add_argument("--top-b", type=int, default=15,
                    help="montako suunnan B nimea listataan (spec: 15 ensin, "
                         "mitataan osumatarkkuus, sitten paatetaan laajennus)")
    ap.add_argument("--offline", action="store_true",
                    help="ohita FPL-bootstrap (vain suunta B)")
    args = ap.parse_args()

    ours, meta = load_projection()
    overrides = load_player_overrides()
    print(f"Projektio: {len(ours)} pelaajaa, generoitu {meta.get('generated_at')}")
    print(f"Ohituksia voimassa: {len(overrides)}")
    print()

    if args.offline:
        print("OFFLINE — suunta A ohitettu (vaatii FPL-bootstrapin).")
        a1 = a2 = []
    else:
        try:
            elements = fetch_bootstrap()
        except Exception as e:
            # EI hiljaista skippia: vahti joka ei voi tehda puolta tyostaan
            # on rikki eika "osittain ajettu". Sama vikaluokka kuin
            # render-daily-deployn hiljainen vihrea.
            print(f"::error::FPL-bootstrap epaonnistui: {e!r}")
            print("::error::Suunta A jai ajamatta. Aja paikallisesti tai "
                  "kayta --offline jos haluat vain suunnan B.")
            return 1
        a1, a2 = direction_a(ours, elements, args.min_owned,
                             args.max_p_start, overrides)

    print(f"=== SUUNTA A1: omistettu >= {args.min_owned} %, EI RIVIA meilla ===")
    print("    (Kinsky-luokka: markkina pitaa aloittajana, meilla ei ole riviä)")
    _print(a1, lambda r: f"{r['owned']:5.1f} %  {r['web_name']:<16} {r['pos']}  id={r['id']}")
    print()

    a2_shown = a2[:args.top_a2]
    print(f"=== SUUNTA A2: omistettu >= {args.min_owned} %, p_start < {args.max_p_start} ===")
    print("    (me sanomme penkki, markkina sanoo aloittaja. Lajiteltu")
    print("     ERIMIELISYYDEN MASSALLA = omistus x (1 - p_start), koska")
    print("     pelkka omistus nosti karkeen varamaalivahteja joiden matala")
    print("     p_start on OIKEIN.)")
    _print(a2_shown, lambda r: (f"massa {r['mass']:5.1f}  {r['owned']:5.1f} %  "
                                f"{r['web_name']:<16} {r['pos']}  "
                                f"p_start={r['p_start']:.2f}  xP6={r['xp6']:.1f}  "
                                f"id={r['id']}"))
    if len(a2) > len(a2_shown):
        print(f"  ...ja {len(a2) - len(a2_shown)} muuta kynnyksen ylittavaa "
              f"(--top-a2 {len(a2)} nayttaa kaikki)")
    print()

    if not args.offline:
        a3 = direction_a3(ours, elements, overrides)
        print("=== SUUNTA A3: SEURAN SISAINEN RISTIRIITA (maalivahdit) ===")
        print("    (markkina omistaa eri pelaajaa kuin malli pitaa ykkosena —")
        print("     tasan Kinsky/Dubravka-kuvio)")
        if not a3:
            print("  (ei yhtaan)")
        for r in a3:
            mark = "  [OHITETTU JO]" if r["overridden"] else ""
            m, o = r["market"], r["model"]
            print(f"  {r['team']:<4} {r['pos']}: markkina {m['web_name']} "
                  f"({m['owned']:.1f} %, p_start {m['p_start']:.2f})  "
                  f"vs  malli {o['web_name']} (p_start {o['p_start']:.2f}, "
                  f"{o['owned']:.1f} %){mark}")
        print()

    b = direction_b(ours, args.b_min_xp, args.b_max_owned, overrides)
    shown = b[:args.top_b]
    print(f"=== SUUNTA B: xP6 >= {args.b_min_xp}, omistus < {args.b_max_owned} % ===")
    print("    (me suosittelemme, markkina ei usko. EI automaattisesti vika:")
    print("     aito differentiaali nayttaa talta — verifioi lahteesta.)")
    _print(shown, lambda r: (f"{r['owned']:5.2f} %  {r['web_name']:<16} {r['pos']} "
                             f"{r['team']:<4} xP6={r['xp6']:5.1f}  "
                             f"p_start={r['p_start']:.2f}  id={r['id']}"))
    if len(b) > len(shown):
        # EI HILJAISTA KATKAISUA: jos vahti rajaa kattavuutta, se sanoo
        # ääneen mita jai pois. Muuten "kaikki tarkistettu" lukee vaarin.
        print(f"  ...ja {len(b) - len(shown)} muuta yli kynnyksen "
              f"(--top-b {len(b)} nayttaa kaikki)")
    print()

    total = len(a1) + len(a2_shown) + len(shown)
    print(f"Shortlist yhteensa: {total} nimea "
          f"(A1 {len(a1)} · A2 {len(a2_shown)}/{len(a2)} · B {len(shown)}/{len(b)})")
    print()
    print("SEURAAVA ASKEL — kasin, ei automaatiota:")
    print("  1. Hae kustakin nimesta roolisignaali useasta lahteesta")
    print("     ('first choice', 'number one', 'deputy', 'transfer market',")
    print("      'new contract', 'starting XI')")
    print("  2. Jos rooli on aidosti eri kuin malli olettaa, lisaa rivi")
    print("     data/fpl_player_overrides.csv:hen:")
    print("       player_id,web_name,p_start,reason,review_by")
    print("     `reason` kantaa LAHTEEN ja `review_by` pakottaa uusinnan.")
    print("  3. Aja build_fpl_xp uudelleen ja verifioi etta luku liikkui.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
