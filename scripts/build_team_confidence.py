"""Joukkuekohtainen LUOTTAMUSLIPPU: milloin luokitus nojaa vanhentuneeseen tietoon.

MIKSI TAMA EIKA LUOKITUKSEN SAATO: DC-luokitukset sovitetaan toteutuneisiin
tuloksiin eivatka nae siirtoikkunaa (aikavaimennus half-life ~198 pv -> GW6:ssa
uusi kausi on vasta 25 % fitin painosta). Yritimme kalibroida suoran korjauksen
(scripts/calibrate_transfer_effect.py) ja se EI validoitunut: hyokkayspuolella
R2 = 0.000 ja puolustuspuolella merkki oli nurin. Vaihtuvuuden SUURUUS on siis
mitattavissa luotettavasti, sen SUUNTA ei.

Siksi malli pysyy koskemattomana ja kayttaja saa tiedon siita mihin lukuun
luottaa vahemman. Sama ratkaisu jota r/FantasyPL-lukija ehdotti itsenaisesti
9.8.2026.

MITTA ON MINUUTIT, EI HINTA. Hintapohjainen mitta kaatui samassa kalibroinnissa:
FPL hinnoittelee tuntemattoman ulkomaisen tulokkaan positiotason mukaan eika
laadun, joten hyvan mutta tuntemattoman ostaminen nayttaa datassa menetykselta.
"Osuus viime kauden minuuteista jotka lahtivat" on fakta, ei arvio.

KYNNYS ON MITATTU, EI VALITTU: 51 joukkue-kausivaihdosta (22/23->23/24,
23/24->24/25, 24/25->25/26) antaa mediaanin 13,0 %, 75. persentiili 22,8 %,
90. persentiili 29,4 %. HIGH_TURNOVER_PCT osuu 80.-90. persentiilin valiin eli
liputtaa noin joka kuudennen joukkueen.

Ajo:  python -m scripts.build_team_confidence
Tuottaa committoitavan `data/team_confidence.json`:n.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from scripts.build_fpl_phase0 import map_name

SCHEMA_VERSION = 1
PREV_SEASON = "2526"

# Mitattu 51 joukkue-kausivaihdoksesta (ks. docstring).
HIGH_TURNOVER_PCT = 25.0
HISTORICAL_MEDIAN_PCT = 13.0

RAW = config.RAW_DATA_DIR / "fpl"


def _prev_season_minutes() -> tuple[dict[int, str], dict[int, float], set[str]]:
    """25/26: code -> joukkue, code -> minuutit, ja joukkuenimet."""
    boot = json.loads((RAW / f"bootstrap_static_{PREV_SEASON}.archive.json")
                      .read_text(encoding="utf-8"))
    tname = {t["id"]: t["name"] for t in boot["teams"]}
    team_by_code = {e["code"]: tname[e["team"]] for e in boot["elements"]}
    id_to_code = {e["id"]: e["code"] for e in boot["elements"]}
    mins: dict[int, float] = defaultdict(float)
    for f in sorted((RAW / f"summary_{PREV_SEASON}").glob("element_*.json")):
        code = id_to_code.get(int(f.stem.split("_")[1]))
        if code is None:
            continue
        for r in json.loads(f.read_text(encoding="utf-8")).get("history") or []:
            mins[code] += min(float(r.get("minutes") or 0), 90.0)
    return team_by_code, dict(mins), set(tname.values())


def build() -> dict:
    prev_team, prev_mins, prev_names = _prev_season_minutes()
    cur = json.loads((RAW / "bootstrap_static.json").read_text(encoding="utf-8"))
    cur_tname = {t["id"]: t["name"] for t in cur["teams"]}
    cur_team_by_code = {e["code"]: cur_tname[e["team"]] for e in cur["elements"]}
    cur_names = set(cur_tname.values())

    # Nousijat = talla kaudella mutta ei viime kaudella. Kerrotaan NIMELTA
    # molemmat suunnat: 8.8.2026 /fpl/defence listasi pudonneet ja unohti
    # nousseet, koska vain toinen suunta tarkistettiin.
    promoted = sorted(cur_names - prev_names)
    relegated = sorted(prev_names - cur_names)

    total: dict[str, float] = defaultdict(float)
    gone: dict[str, float] = defaultdict(float)
    for code, team in prev_team.items():
        m = prev_mins.get(code, 0.0)
        if m <= 0 or team not in cur_names:
            continue
        total[team] += m
        now = cur_team_by_code.get(code)
        if now != team:
            gone[team] += m

    teams = []
    for team in sorted(cur_names):
        if team in promoted:
            teams.append({
                "team": team, "model_team": map_name(team),
                "is_promoted": True, "minutes_churn_pct": None,
                "flag": "promoted",
                # 14.8: EDELLINEN TEKSTI OLI VAARA. Se sanoi "No Premier
                # League results to fit a rating on", mutta Ipswich pelasi
                # PL:aa 2024/25 — ja meidan oma nousijabaseline on MITATTU
                # muun muassa sen kaudesta (`promoted_baseline.py:157`
                # REFERENCE_TRIO = Ipswich/Leicester/Southampton). Vaite oli
                # tosi vain suhteessa nykyiseen fit-ikkunaan; tavallisena
                # englantina se oli valhe yhdesta kolmesta seurasta, ja se oli
                # livena ilmaissivulla seka API:ssa. Uusi teksti sanoo mika on
                # oikeasti totta: naillä ei ole OMAA luokitusta nykyikkunasta.
                "note": ("Promoted side. No results inside the model's "
                         "current fitting window, so this team runs on a "
                         "measured baseline from recent promoted sides "
                         "instead of a rating of its own."),
            })
            continue
        t, g = total.get(team, 0.0), gone.get(team, 0.0)
        pct = round(100.0 * g / t, 1) if t > 0 else None
        high = pct is not None and pct >= HIGH_TURNOVER_PCT
        # LUKU NAYTETAAN AINA, lippu vain kun se on ansaittu. Binaarinen lippu
        # yksin olisi hyodyton rauhallisena kesana (26/27: korkein 21,4 % eli
        # kukaan ei ylita kynnysta) - ja houkutus olisi laskea kynnysta kunnes
        # joku laukaisee sen. Se kertoisi kayttajalle "korkea vaihtuvuus"
        # kesana jona vaihtuvuutta ei ollut. Luku on informatiivinen joka
        # kausi ja pysyy totena.
        teams.append({
            "team": team, "model_team": map_name(team),
            "is_promoted": False, "minutes_churn_pct": pct,
            "flag": "high_turnover" if high else None,
            "note": ((f"{pct:.0f}% of last season's minutes were played by "
                      f"players who have since left. The rating is fitted on "
                      f"results, so it has not priced that in yet.")
                     if high else
                     (f"{pct:.0f}% of last season's minutes have left the club."
                      if pct is not None else None)),
        })

    flagged = [t for t in teams if t["flag"]]
    pcts = sorted(t["minutes_churn_pct"] for t in teams
                  if t["minutes_churn_pct"] is not None)
    season_median = (round(pcts[len(pcts) // 2], 1) if pcts else None)
    return {
        "schema_version": SCHEMA_VERSION,
        "basis_season": PREV_SEASON,
        "method": ("share of last season's minutes played by players no longer "
                   "at the club; ratings are fitted on results and cannot see "
                   "the transfer window"),
        "high_turnover_threshold_pct": HIGH_TURNOVER_PCT,
        "historical_median_pct": HISTORICAL_MEDIAN_PCT,
        "season_median_pct": season_median,
        "promoted": promoted,
        "relegated": relegated,
        "n_flagged": len(flagged),
        "teams": teams,
    }


def main() -> int:
    doc = build()
    out = config.PROJECT_ROOT / "data" / "team_confidence.json"
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=1),
                   encoding="utf-8")

    print(f"{out.name}: {len(doc['teams'])} joukkuetta, "
          f"{doc['n_flagged']} liputettua")
    print(f"  nousijat  : {doc['promoted']}")
    print(f"  pudonneet : {doc['relegated']}")
    for t in sorted((x for x in doc["teams"] if x["flag"]),
                    key=lambda x: -(x["minutes_churn_pct"] or 0)):
        pct = t["minutes_churn_pct"]
        print(f"  {t['flag']:<14} {t['team']:<18} "
              f"{'' if pct is None else f'{pct:.1f} %'}")

    # Sanity: PL:ssa on 20 joukkuetta ja tasan 3 nousee. Muu tarkoittaa etta
    # jompikumpi bootstrap on vaarasta kaudesta.
    if len(doc["teams"]) != 20:
        raise SystemExit(f"joukkueita {len(doc['teams'])}, odotettu 20")
    if len(doc["promoted"]) != 3 or len(doc["relegated"]) != 3:
        raise SystemExit(
            f"nousijoita {len(doc['promoted'])}, pudonneita "
            f"{len(doc['relegated'])} — odotettu 3 ja 3")
    if doc["n_flagged"] > 10:
        raise SystemExit(f"liputettuja {doc['n_flagged']}/20 — kynnys on rikki, "
                         f"lippu ei erottele mitaan jos se osuu puoleen liigaa")
    return 0


if __name__ == "__main__":
    sys.exit(main())
