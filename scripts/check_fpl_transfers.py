"""Siirtovahti: onko julkaistu xP-artefakti eri mielta FPL:n kanssa siita
missa joukkueessa pelaaja on?

MIKSI TAMA ON OLEMASSA (10.8.2026, Bruno G. -case)
Ville huomasi listalta etta Bruno Guimaraes oli yha Newcastlessa vaikka FPL:n
oma API sanoi Arsenal. Artefakti oli ajettu 12:53 UTC ja siirto oli kirjattu
FPL:aan sen jalkeen, joten 3 h -refresh olisi korjannut sen itsestaan. Mutta
vika ei ollut vaaraton odotusaikana: pelaajan koko projektio lasketaan VAARAN
JOUKKUEEN OTTELUITA vastaan. Bruno G:lla se tarkoitti Newcastlen ohjelmaa
(LIV, TOT, BOU, LEE) kun oikea oli Arsenalin (COV, AVL, CHE, SUN), ja hanta
omisti 10,2 % pelaajista.

Yksikaan portti ei nayttanyt tata, koska builderi ottaa joukkueen samasta
bootstrapista jonka se juuri haki -> se ei voi olla eri mielta itsensa kanssa.
Ero syntyy VAIN ajan kuluessa: julkaistu artefakti vs FPL nyt. Sita ei voi
mitata builderin sisalta, joten se mitataan taalta.

Ero on aina vain viiveen mittainen, mutta siirtoikkunassa viive on se mika
ratkaisee: kayttaja katsoo listaa tanaan.

KAYTTO
    python scripts/check_fpl_transfers.py            # artefakti levylta
    python scripts/check_fpl_transfers.py --api      # tuotannon API:sta

Exit 0 = tasmaa. Exit 3 = eroja loytyi (workflow kaynnistaa refreshin).
Exit 2 = ei voitu mitata (verkko/tiedosto) -> ei hiljaista PASSia.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.build_fpl_phase0 import map_name  # noqa: E402
from src.data import fpl_api  # noqa: E402

ARTIFACT = ROOT / "data" / "fpl_xp.json"
API_URL = "https://api.goaliq.app/api/fantasy/xp"


def load_artifact(from_api: bool) -> dict:
    if from_api:
        import requests
        r = requests.get(API_URL, timeout=30)
        r.raise_for_status()
        return r.json()
    return json.loads(ARTIFACT.read_text(encoding="utf-8"))


def compare(doc: dict, boot: dict) -> list[dict]:
    """Palauttaa rivit joissa artefaktin joukkue != FPL:n nykyinen joukkue.

    Vertailu tehdaan FPL:n joukkue-ID:n kautta mallinimeen (map_name), EI
    merkkijonojen sumeaa vertailua: builderi kirjoittaa mallinimen
    ("Manchester United") ja FPL sanoo "Man Utd", joten suora vertailu
    tuottaisi 207 valhetta ja hukuttaisi ne 2 aitoa.
    """
    fpl_team_by_pid = {}
    team_name_by_id = {t["id"]: t["name"] for t in boot["teams"]}
    for e in boot["elements"]:
        fpl_team_by_pid[e["id"]] = map_name(team_name_by_id[e["team"]])

    out = []
    for p in doc.get("players", []):
        want = fpl_team_by_pid.get(p["id"])
        if want is None:
            # Pelaaja poistunut bootstrapista kokonaan (esim. myyty
            # liigasta ulos). Sama vikaluokka, eri korjaus -> raportoidaan.
            out.append({"id": p["id"], "name": p["web_name"],
                        "ours": p["team"], "fpl": None,
                        "owned_pct": p.get("owned_pct"),
                        "xp": p.get("xp_horizon_total")})
            continue
        if want != p["team"]:
            out.append({"id": p["id"], "name": p["web_name"],
                        "ours": p["team"], "fpl": want,
                        "owned_pct": p.get("owned_pct"),
                        "xp": p.get("xp_horizon_total")})
    return out


def main() -> int:
    # Windows-konsoli on cp1252 ja pelaajanimissa on diakriitteja (Lukic ->
    # Lukić). Ilman tata vahti KAATUU juuri siihen riviin jota se raportoi,
    # eli epaonnistuu tasan silloin kun se on loytanyt jotain.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    ap = argparse.ArgumentParser()
    ap.add_argument("--api", action="store_true",
                    help="lue artefakti tuotannon API:sta levyn sijaan")
    args = ap.parse_args()

    try:
        doc = load_artifact(args.api)
        # force=True: 6 h cache tekisi vahdista tautologian jos builderi on
        # juuri ajanut samalla koneella samasta cachesta.
        boot = fpl_api.fetch_bootstrap(force=True)
    except Exception as exc:  # noqa: BLE001
        print(f"[VAHTI] EI VOITU MITATA: {exc}")
        return 2

    n = len(doc.get("players", []))
    if n == 0:
        print("[VAHTI] EI VOITU MITATA: artefaktissa 0 pelaajaa")
        return 2

    diffs = compare(doc, boot)
    gen = (doc.get("meta") or {}).get("generated_at")
    print(f"[VAHTI] artefakti {gen} · {n} pelaajaa · eroja {len(diffs)}")

    if not diffs:
        print("[VAHTI] OK — joukkueet tasmaavat FPL:n kanssa.")
        return 0

    for d in sorted(diffs, key=lambda x: -(x["owned_pct"] or 0)):
        print(f"  SIIRTO: {d['name']} (id {d['id']}) meilla {d['ours']!r} "
              f"-> FPL {d['fpl']!r} · omistus {d['owned_pct']} % · "
              f"xP {d['xp']}")
    print("[VAHTI] Projektiot on laskettu VAARAN joukkueen otteluita vastaan. "
          "Refresh tarvitaan.")
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
