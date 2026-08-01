"""Perustajan FPL-historia julkisesta lähteestä (1.8.2026).

Miksi: etusivun uskottavuuslohko väitti "12 seasons", "best finish is top 6%"
ja "worst is 6,138,376" kovakoodattuna. Kaksi ongelmaa:
  1. "12 seasons" vanhenee joka kausi eikä mikään huomauta siitä.
  2. Lohko LINKKAA julkiseen entryyn, eli lukija voi tarkistaa luvut yhdellä
     klikkauksella. Väärä luku juuri siinä kohdassa on pahin mahdollinen,
     koska koko lohkon pointti on "anyone can check it".

Ratkaisu: luvut samasta lähteestä johon linkki osoittaa. "top 6%" pudotettiin,
koska prosentti vaatii kauden pelaajamäärän jota tämä API ei anna — sijaluku
sen sijaan on suoraan verifioitavissa.

Kirjoittaa data/founder_entry.json. Fail-safe: sanity FAIL → exit 2 → ei
tiedostoa → build_fpl_page jättää markerin koskematta (vanha teksti jää).
"""
from __future__ import annotations

import datetime as _dt
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config

ENTRY_ID = 1186244
API = f"https://fantasy.premierleague.com/api/entry/{ENTRY_ID}/history/"
OUT_PATH = config.DATA_DIR / "founder_entry.json"
UA = "Mozilla/5.0 (compatible; GoalIQ/1.0; +https://goaliq.app)"

SANITY_MIN_SEASONS = 5
SANITY_MAX_RANK = 20_000_000


def fetch() -> dict:
    req = urllib.request.Request(API, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def summarise(payload: dict) -> dict:
    past = [p for p in (payload.get("past") or []) if p.get("rank")]
    if not past:
        raise SystemExit("VIRHE: entryn historiassa ei ole yhtään kautta.")
    best = min(past, key=lambda p: p["rank"])
    worst = max(past, key=lambda p: p["rank"])
    return {
        "entry_id": ENTRY_ID,
        "generated_at": _dt.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "source": API,
        "seasons": len(past),
        "first_season": past[0]["season_name"],
        "best": {"season": best["season_name"], "rank": best["rank"]},
        "worst": {"season": worst["season_name"], "rank": worst["rank"]},
    }


def sanity(d: dict) -> list[str]:
    fails = []
    if d["seasons"] < SANITY_MIN_SEASONS:
        fails.append(f"kausia {d['seasons']} < {SANITY_MIN_SEASONS}")
    if d["best"]["rank"] > d["worst"]["rank"]:
        fails.append("paras sija on huonompi kuin huonoin")
    for k in ("best", "worst"):
        if not 0 < d[k]["rank"] < SANITY_MAX_RANK:
            fails.append(f"{k}-sija epauskottava: {d[k]['rank']}")
    return fails


if __name__ == "__main__":
    data = summarise(fetch())
    fails = sanity(data)
    if fails:
        print("SANITY FAIL:")
        for f in fails:
            print(" -", f)
        raise SystemExit(2)
    OUT_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                        encoding="utf-8")
    print(f"OK: {data['seasons']} kautta ({data['first_season']}–), "
          f"paras {data['best']['rank']:,} ({data['best']['season']}), "
          f"huonoin {data['worst']['rank']:,} ({data['worst']['season']}) "
          f"-> {OUT_PATH}")
