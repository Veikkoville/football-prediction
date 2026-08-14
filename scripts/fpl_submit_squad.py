"""Vie jäädytetty mallin runko FPL-joukkueeseen (kokoonpano + kapteeni + penkki).

    python scripts/fpl_submit_squad.py --gw 1              # NÄYTÄ vain
    python scripts/fpl_submit_squad.py --gw 1 --send --yes # LÄHETÄ

🔴 MITÄ TÄMÄ EI TEE. FPL:n `my-team`-endpoint EI OSTA PELAAJIA. Se asettaa
vain kokoonpanon, kapteenin, varakapteenin ja penkkijärjestyksen JO OLEMASSA
OLEVASTA 15 pelaajan rivistä. Siirrot ovat eri endpoint (`/api/transfers/`),
ja niiden automatisointi on eri riski: väärä siirto polttaa rahaa ja
pisteitä eikä sitä voi perua. Siksi tämä skripti VERTAA ensin nykyistä riviä
jäädytettyyn ja KIELTÄYTYY lähettämästä jos pelaajajoukot eroavat — se
tulostaa tarvittavat siirrot ja jättää ne sinun tehtäväksesi.

🔴 TUNNISTAUTUMINEN ON SINUN. Skripti ei koskaan pyydä, tallenna eikä
kirjoita salasanaa. Se lukee valmiin istuntoevästeen ympäristömuuttujasta
FPL_COOKIE, jonka asetat itse siinä terminaalissa jossa ajat tämän:

    Chrome -> fantasy.premierleague.com kirjautuneena -> DevTools ->
    Application -> Cookies -> kopioi `pl_profile` ja `csrftoken`.

    PowerShell:  $env:FPL_COOKIE = "pl_profile=...; csrftoken=..."
    bash:        export FPL_COOKIE='pl_profile=...; csrftoken=...'

Eväste on kertakäyttöinen työkalu: älä committaa sitä äläkä liitä chattiin.
Ilman --send skripti ei ota verkkoyhteyttä lainkaan evästeellä.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FROZEN_DIR = ROOT / "data" / "model_squad_frozen"
ENTRY_ID = 116920
FPL_BASE = "https://fantasy.premierleague.com/api"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

POS_NAME = {1: "MV", 2: "PUO", 3: "KES", 4: "HYÖ"}


def load_freeze(gw: int) -> dict:
    p = FROZEN_DIR / f"gw{gw}.json"
    if not p.exists():
        raise SystemExit(
            f"VIRHE: {p.relative_to(ROOT)} puuttuu.\n"
            f"Jäädytys ajetaan vasta deadline-ikkunassa "
            f"(scripts/freeze_model_squad_gw.py). Ilman sitä ei ole mitään "
            f"vietävää — ÄLÄ rakenna riviä käsin tästä skriptistä, koska "
            f"julkinen väite on nimenomaan 'jäädytetty ennen deadlinea'.")
    return json.loads(p.read_text(encoding="utf-8"))


def build_positions(freeze: dict) -> list[dict]:
    """FPL-järjestys: 1 = aloittava MV, 2-11 = kenttäpelaajat, 12 = varamaalivahti,
    13-15 = penkin kenttäpelaajat autosub-järjestyksessä.

    Penkin järjestys tulee jäädytyksestä sellaisenaan (order_bench on jo
    ratkaissut sen) — tässä sitä EI järjestetä uusiksi, jotta vietävä rivi on
    tasan se joka jäädytettiin.
    """
    xi, bench = list(freeze["xi"]), list(freeze["bench"])
    cap, vice = int(freeze["captain"]), int(freeze["vice_captain"])

    xi_gk = [p for p in xi if int(p["pos"]) == 1]
    xi_out = [p for p in xi if int(p["pos"]) != 1]
    if len(xi_gk) != 1:
        raise SystemExit(f"VIRHE: XI:ssä {len(xi_gk)} maalivahtia, pitää olla 1.")
    bench_gk = [p for p in bench if int(p["pos"]) == 1]
    bench_out = [p for p in bench if int(p["pos"]) != 1]
    if len(bench_gk) != 1:
        raise SystemExit(f"VIRHE: penkissä {len(bench_gk)} maalivahtia, pitää olla 1.")

    # Kenttäpelaajat positioittain (MV/PUO/KES/HYÖ) — FPL näyttää rivin näin.
    xi_out.sort(key=lambda p: (int(p["pos"]), p["id"]))
    ordered = xi_gk + xi_out + bench_gk + bench_out
    if len(ordered) != 15:
        raise SystemExit(f"VIRHE: {len(ordered)} pelaajaa, pitää olla 15.")

    picks = []
    for i, p in enumerate(ordered, start=1):
        pid = int(p["id"])
        picks.append({"element": pid, "position": i,
                      "is_captain": pid == cap,
                      "is_vice_captain": pid == vice})
    # 🔴 Lippuja EI riitä laskea koko 15:stä. Penkillä oleva kapteeni antaisi
    # nekin luvut 1+1 ja menisi läpi — mutta tuplaus ei laukea penkiltä, eli
    # se olisi hiljainen pistetappio jonka huomaisi vasta kierroksen jälkeen.
    # Siksi tarkistus on nimenomaan ALOITTAVAA yhtätoista vastaan.
    xi_ids = {int(p["id"]) for p in xi}
    if cap not in xi_ids:
        raise SystemExit(f"VIRHE: kapteeni {cap} ei ole aloittavassa XI:ssä.")
    if vice not in xi_ids:
        raise SystemExit(f"VIRHE: varakapteeni {vice} ei ole aloittavassa XI:ssä.")
    n_cap = sum(1 for x in picks if x["is_captain"])
    n_vice = sum(1 for x in picks if x["is_vice_captain"])
    if n_cap != 1 or n_vice != 1:
        raise SystemExit(
            f"VIRHE: kapteeneja {n_cap}, varakapteeneja {n_vice} — pitää olla 1+1.")
    if cap == vice:
        raise SystemExit("VIRHE: kapteeni ja varakapteeni ovat sama pelaaja.")
    return picks, ordered


def show(freeze: dict, picks: list[dict], ordered: list[dict]) -> None:
    m = freeze.get("meta", {})
    print(f"\nGW{m.get('gw')} — jäädytetty {m.get('frozen_at')} "
          f"(deadline {m.get('deadline')})")
    print(f"hinta {m.get('cost')}m · XI xP {m.get('xi_xp_gw')} · "
          f"chip {m.get('chip')}\n")
    by_id = {int(p["id"]): p for p in ordered}
    for pk in picks:
        p = by_id[pk["element"]]
        mark = " (C)" if pk["is_captain"] else (" (VC)" if pk["is_vice_captain"] else "")
        line = "PENKKI " if pk["position"] >= 12 else "       "
        print(f"  {pk['position']:>2}. {line}{POS_NAME.get(int(p['pos']), '?'):<4} "
              f"{str(p.get('web_name')):<16} {str(p.get('team_short')):<4} "
              f"{(int(p.get('price') or 0)) / 10:>4.1f}m  xP {p.get('xp')}{mark}")
    print()


def fetch_current(session: requests.Session) -> list[int]:
    r = session.get(f"{FPL_BASE}/my-team/{ENTRY_ID}/", timeout=30)
    if r.status_code in (401, 403):
        raise SystemExit(
            "VIRHE: FPL palautti "
            f"{r.status_code} — istuntoeväste puuttuu tai on vanhentunut. "
            "Kirjaudu selaimessa uudelleen ja päivitä FPL_COOKIE.")
    r.raise_for_status()
    return [int(p["element"]) for p in (r.json().get("picks") or [])]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gw", type=int, required=True)
    ap.add_argument("--entry", type=int, default=ENTRY_ID)
    ap.add_argument("--send", action="store_true",
                    help="lähetä FPL:ään (vaatii FPL_COOKIE + --yes)")
    ap.add_argument("--yes", action="store_true",
                    help="vahvistus; ilman tätä --send ei lähetä")
    args = ap.parse_args()

    freeze = load_freeze(args.gw)
    picks, ordered = build_positions(freeze)
    show(freeze, picks, ordered)

    payload = {"chip": None, "picks": picks}
    if not args.send:
        print("KUIVA-AJO. Payload jonka --send lähettäisi:")
        print(json.dumps(payload, ensure_ascii=False, indent=1))
        print(f"\n-> POST {FPL_BASE}/my-team/{args.entry}/")
        print("Lähetä: --send --yes (ja FPL_COOKIE asetettuna).")
        return 0

    cookie = os.environ.get("FPL_COOKIE", "").strip()
    if not cookie:
        raise SystemExit(
            "VIRHE: FPL_COOKIE puuttuu. Ks. tiedoston yläosan ohje. "
            "Skripti ei kysy salasanaa eikä kirjaudu puolestasi.")
    csrf = ""
    for part in cookie.split(";"):
        k, _, v = part.strip().partition("=")
        if k == "csrftoken":
            csrf = v
    if not csrf:
        raise SystemExit("VIRHE: evästeestä puuttuu csrftoken — FPL hylkää kirjoituksen.")

    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Cookie": cookie,
                      "X-CSRFToken": csrf, "Content-Type": "application/json",
                      "Referer": "https://fantasy.premierleague.com/my-team",
                      "Origin": "https://fantasy.premierleague.com"})

    current = fetch_current(s)
    want = {pk["element"] for pk in picks}
    have = set(current)
    if want != have:
        by_id = {int(p["id"]): p for p in ordered}
        print("🔴 EI LÄHETETÄ: rivisi pelaajat eivät ole samat kuin mallin.")
        print("   Tämä endpoint järjestää vain olemassa olevan rivin — se ei osta.")
        print(f"\n   SISÄÄN ({len(want - have)}):")
        for pid in sorted(want - have):
            p = by_id[pid]
            print(f"     {p.get('web_name')} ({p.get('team_short')}, "
                  f"{(int(p.get('price') or 0)) / 10:.1f}m)")
        print(f"\n   ULOS ({len(have - want)}): element-id:t "
              f"{sorted(have - want)}")
        print("\n   Tee siirrot itse FPL:ssä ja aja tämä uudelleen.")
        return 2

    if not args.yes:
        print("--send annettu mutta --yes puuttuu — ei lähetetty.")
        return 1

    r = s.post(f"{FPL_BASE}/my-team/{args.entry}/",
               data=json.dumps(payload), timeout=30)
    if r.status_code >= 400:
        print(f"VIRHE {r.status_code}: {r.text[:400]}")
        return 1

    # 🔴 EI LUOTETA VASTAUSKOODIIN. Luetaan rivi takaisin ja verrataan.
    # Vrt. sama periaate kuin muualla repossa: onnistumisilmoitus ei ole
    # todiste lopputilasta.
    back = s.get(f"{FPL_BASE}/my-team/{args.entry}/", timeout=30).json()
    got = {int(p["element"]): (int(p["position"]), bool(p.get("is_captain")),
                               bool(p.get("is_vice_captain")))
           for p in (back.get("picks") or [])}
    want_map = {pk["element"]: (pk["position"], pk["is_captain"],
                                pk["is_vice_captain"]) for pk in picks}
    diff = [pid for pid, v in want_map.items() if got.get(pid) != v]
    if diff:
        print(f"🔴 VARMISTUS EPÄONNISTUI: {len(diff)} pelaajaa ei vastaa "
              f"lähetettyä ({sorted(diff)}). Tarkista rivi selaimessa.")
        return 1
    print(f"OK: GW{args.gw} rivi viety ja varmistettu takaisinluvulla "
          f"(kapteeni {freeze['captain']}, varakapteeni {freeze['vice_captain']}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
