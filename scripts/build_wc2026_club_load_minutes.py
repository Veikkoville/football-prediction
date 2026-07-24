"""PL-seura -> MM-2026-MINUUTTIKARTTA (#142 OSA A, feasibility-ajo 24.7).

Korvaa exposure-proxyn (build_wc2026_club_load.py, jaa fallbackiksi) aidoilla
per-pelaaja-turnausminuuteilla. Minuuttilahde: FIFA-World-Cup-2026-Dataset
(github.com/mominullptr/FIFA-World-Cup-2026-Dataset, CC0 1.0, data_source=
sofascore.com, last_verified 2026-07-19, sis. finaalin M104). Pinnattu
committiin 8fcb734 = reprodusoitava; aja HEADilla vasta kun uusi commit on
verifioitu samoilla sanity-checkeilla.

VERIFIOINTI (24.7, ks. cc-report 2026-07-24-wc-fatigue-142-osa-a.md):
  - 104/104 ottelua Completed; SF/pronssi/finaali = CoS-faktapohja (AET-finaali).
  - Lineup-minuuttisummat per joukkue per ottelu ~990 (reg) / ~1320 (AET).
  - player_stats == match_lineups-summa kaikilla 1248 pelaajalla (0 diffia).
  - CoS:n FotMob-ristiintarkistus: 7/8 pelaajaa +-3 min sisalla.

PELAAJA->PL-SEURA: FPL bootstrap-static = KANONINEN (26/27-rosterit,
ajanhetken totuus -> aja uudelleen ~15.8 ennen GW1:ta). Datasetin club_team
on vain matchausvihje + danger-tarkistus (kesasiirrot muuttavat seuraa).

Ajo:  .venv/Scripts/python.exe -m scripts.build_wc2026_club_load_minutes
Ulos: data/wc2026_club_load.csv (pelaajataso: player, fpl_team, country,
      wc_minutes, ...) + stdout-raportti (seurakooste, matchaamattomat).
"""
from __future__ import annotations

import csv
import io
import re
import sys
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402

OUT_PATH = config.DATA_DIR / "wc2026_club_load.csv"

DATASET_REPO = "mominullptr/FIFA-World-Cup-2026-Dataset"
DATASET_COMMIT = "8fcb734c8d8e14622659a52ca3ab5e0973376096"  # sis. finaalin
RAW_BASE = f"https://raw.githubusercontent.com/{DATASET_REPO}/{DATASET_COMMIT}"
SOURCE_TAG = f"github:{DATASET_REPO}@{DATASET_COMMIT[:7]} (CC0, sofascore-pohj.)"

FPL_BOOTSTRAP = "https://fantasy.premierleague.com/api/bootstrap-static/"
UA = {"User-Agent": "Mozilla/5.0 (goaliq-wc2026-club-load)"}

# Datasetin club_team -> FPL-seuranimi. EKSAKTI whitelist — huom.
# 'Newcastle United Jets FC' (A-League) EI saa osua Newcastleen.
PL_CLUB_MAP = {
    "AFC Bournemouth": "Bournemouth",
    "Arsenal FC": "Arsenal",
    "Aston Villa FC": "Aston Villa",
    "Brentford FC": "Brentford",
    "Brighton & Hove Albion FC": "Brighton",
    "Chelsea FC": "Chelsea",
    "Coventry City FC": "Coventry City",
    "Crystal Palace FC": "Crystal Palace",
    "Everton FC": "Everton",
    "Fulham FC": "Fulham",
    "Hull City FC": "Hull City",
    "Ipswich Town FC": "Ipswich Town",
    "Leeds United FC": "Leeds",
    "Liverpool FC": "Liverpool",
    "Manchester City FC": "Man City",
    "Manchester United FC": "Man Utd",
    "Newcastle United FC": "Newcastle",
    "Nottingham Forest FC": "Nott'm Forest",
    "Sunderland AFC": "Sunderland",
    "Tottenham Hotspur FC": "Spurs",
}

# Nordiset/slaavilaiset merkit joita NFKD ei hajota.
CHAR_MAP = str.maketrans({
    "ø": "o", "Ø": "o", "đ": "d", "Đ": "d", "ł": "l", "Ł": "l",
    "ð": "d", "Ð": "d", "þ": "th", "Þ": "th", "ß": "ss",
    "æ": "ae", "Æ": "ae", "œ": "oe", "Œ": "oe",
    "ı": "i", "İ": "i",  # turkkilainen dotless i (Kadıoğlu, Bayındır)
})

# Datasetin rikkinaiset/mangloidut nimet joita automatiikka ei saa kiinni
# ILMAN vaarallisen loysia saantoja. Jokainen rivi ristiintarkistettu
# FD-squad-pohjaisesta exposure-kartasta (build_wc2026_club_load.py, 20.7):
# maa + seura tasmaavat. wc_name -> FPL full name.
MANUAL_MAP = {
    "Ramsés Alisson": "Alisson Becker",            # Brazil / Liverpool GK
    "Miguel Bruno": "Bruno Borges Fernandes",      # Portugal / Man Utd
    "Mohamed Abdelsalam Omar": "Omar Marmoush",    # Egypt / Man City
}


def norm(s: str) -> str:
    s = str(s).translate(CHAR_MAP)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[-.'’]", " ", s.lower())
    return " ".join(s.split())


def squash(s: str) -> str:
    return norm(s).replace(" ", "")


def _fetch_csv(name: str) -> list[dict]:
    cache_dir = config.DATA_DIR / "raw" / "wc2026_dataset"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache = cache_dir / f"{DATASET_COMMIT[:7]}_{name}"
    if cache.exists():
        text = cache.read_text(encoding="utf-8")
    else:
        r = requests.get(f"{RAW_BASE}/{name}", headers=UA, timeout=60)
        r.raise_for_status()
        text = r.text
        cache.write_text(text, encoding="utf-8")
    return list(csv.DictReader(io.StringIO(text)))


def load_wc_players() -> list[dict]:
    squads = _fetch_csv("squads_and_players.csv")
    stats = {r["player_id"]: r for r in _fetch_csv("player_stats.csv")}
    teams = {r["team_id"]: r["team_name"] for r in _fetch_csv("teams.csv")}
    out = []
    for r in squads:
        st = stats.get(r["player_id"], {})
        name = r["player_name"]
        out.append({
            "wc_id": r["player_id"],
            "name": name,
            "country": teams.get(r["team_id"], "?"),
            "club_team": (r.get("club_team") or "").strip(),
            "minutes": int(st.get("minutes_played") or 0),
            "matches": int(st.get("matches_played") or 0),
            "nrm": norm(name),
            "toks": set(norm(name).split()),
            "sq": squash(name),
        })
    return out


def load_fpl_players() -> list[dict]:
    r = requests.get(FPL_BOOTSTRAP, headers=UA, timeout=60)
    r.raise_for_status()
    d = r.json()
    teams = {t["id"]: t["name"] for t in d["teams"]}
    out = []
    for e in d["elements"]:
        full = f"{e['first_name']} {e['second_name']}"
        out.append({
            "fpl_id": e["id"],
            "full": full,
            "web": e["web_name"],
            "team": teams[e["team"]],
            "nrm": norm(full),
            "toks": set(norm(full).split()),
            "web_toks": set(norm(e["web_name"]).split()),
        })
    return out


# Partikkelit joita ei lasketa yhteisiksi tokeneiksi
STOP_TOKS = {"de", "da", "dos", "das", "do", "van", "der", "den", "el", "al",
             "jr", "e", "y", "di", "la", "le", "bin", "ben"}


def _sig_toks(toks: set[str]) -> set[str]:
    return {t for t in toks if len(t) >= 3 and t not in STOP_TOKS}


def match_players(fpl: list[dict], wc: list[dict]):
    """FPL-pelaaja -> WC-pelaaja kahdessa passissa.

    Pass 0: MANUAL_MAP (kasin verifioidut mangloidut nimet).
    Pass 1 (vahvat nimistrategiat, union + seurapreferenssi): exact /
    token-subset molempiin suuntiin / squash-substring / >=2 yhteista tokenia.
    Pass 2 (heikot, vain viela matchaamattomat FPL vs viela vapaat WC,
    AINA seuravihje vaaditaan, strategiajarjestyksessa): web_name-substring /
    kaanteinen squash ('Mc' -> McGinn). EI yhden-yhteisen-tokenin strategiaa:
    se tuotti vaaria matcheja (Guiu<-Cucurella) kun oikea pelaaja on
    poistunut FPL:sta.

    Kaksipassisuus estaa heikon strategian varastamasta vahvan matchin
    (Jack vs Tyler Fletcher; Bobby Thomas vs Thomas-Asante).
    Palauttaa (matchit, ambiguous).
    """
    matches: dict[int, tuple[dict, dict, str]] = {}
    ambiguous: list[tuple[dict, list[dict]]] = []
    used_wc: set[str] = set()

    def hint_ok(w: dict, p: dict) -> bool:
        return PL_CLUB_MAP.get(w["club_team"]) == p["team"]

    # ---- Pass 0: manuaalimappaus ----
    fpl_by_nrm = {p["nrm"]: p for p in fpl}
    for wc_name, fpl_full in MANUAL_MAP.items():
        c = next((w for w in wc if w["name"] == wc_name), None)
        p = fpl_by_nrm.get(norm(fpl_full))
        if c and p and p["fpl_id"] not in matches:
            used_wc.add(c["wc_id"])
            matches[p["fpl_id"]] = (p, c, "manual")

    # ---- Pass 1: union vahvoista strategioista ----
    for p in fpl:
        if p["fpl_id"] in matches:
            continue
        union: dict[str, tuple[int, dict, str]] = {}  # wc_id -> (rank, wc, how)

        def add(cs, rank, how):
            for c in cs:
                if c["wc_id"] not in union:
                    union[c["wc_id"]] = (rank, c, how)

        add([c for c in wc if c["nrm"] == p["nrm"]], 0, "exact")
        add([c for c in wc if len(p["toks"]) >= 2 and p["toks"] <= c["toks"]],
            1, "fpl_subset")
        add([c for c in wc if len(c["toks"]) >= 2 and c["toks"] <= p["toks"]],
            2, "wc_subset")
        # squash: token osuu jos on WC-nimessa kokonaisena TAI >=6-merkkisena
        # substringina (estaa 'nico' in 'nicolas' -tyyppiset vaaraosumat,
        # sallii concatenaatiot 'MARTINELLIGabriel')
        big = [t for t in p["toks"] if len(t) >= 4]
        if len(big) >= 2:
            need = max(2, len(big) - 1)

            def hits(c):
                return sum(
                    1 for t in big
                    if t in c["toks"] or (len(t) >= 6 and t in c["sq"])
                )
            add([c for c in wc if hits(c) >= need], 3, "squash")
        sig = _sig_toks(p["toks"])
        add([c for c in wc if len(sig & _sig_toks(c["toks"])) >= 2],
            4, "common2")

        cands = list(union.values())
        if not cands:
            continue
        exact = [x for x in cands if x[0] == 0]
        if len(exact) == 1:
            cands = exact
        elif len(cands) > 1:
            pref = [x for x in cands if hint_ok(x[1], p)]
            if len(pref) == 1:
                cands = [(pref[0][0], pref[0][1], pref[0][2] + "+club")]
            else:
                best = min(x[0] for x in cands)
                top = [x for x in cands if x[0] == best]
                if len(top) == 1:
                    cands = top
        if len(cands) == 1:
            _, c, how = cands[0]
            if c["wc_id"] in used_wc:
                ambiguous.append((p, [c]))
                continue
            used_wc.add(c["wc_id"])
            matches[p["fpl_id"]] = (p, c, how)
        else:
            ambiguous.append((p, [x[1] for x in cands]))

    # ---- Pass 2: heikot strategiat strategiajarjestyksessa (web+club ensin
    # KAIKILLE, sitten revsquash) — estaa heikomman strategian varastamasta
    # vahvemman kandidaatin (Hemmings ei saa viedä Watkinsin rivia). ----
    def pass2(strategy_fn, how):
        for p in fpl:
            if p["fpl_id"] in matches:
                continue
            pool = [c for c in wc if c["wc_id"] not in used_wc and hint_ok(c, p)]
            cands = strategy_fn(p, pool)
            if len(cands) == 1:
                c = cands[0]
                used_wc.add(c["wc_id"])
                matches[p["fpl_id"]] = (p, c, how)
            elif len(cands) > 1:
                ambiguous.append((p, cands))

    def s_web(p, pool):
        wt = {t for t in p["web_toks"] if len(t) >= 3}
        return [c for c in pool if wt and all(t in c["sq"] for t in wt)]

    def s_revsquash(p, pool):
        # datasetin katkenneet nimet ('Mc'): WC-tokenit substringina FPL-squashissa
        fsq = squash(p["full"] + " " + p["web"])
        return [c for c in pool if c["toks"] and all(t in fsq for t in c["toks"])]

    pass2(s_web, "web+club")
    pass2(s_revsquash, "revsquash+club")

    return matches, ambiguous


def main() -> None:
    fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    wc = load_wc_players()
    fpl = load_fpl_players()
    print(f"WC-datasetti: {len(wc)} pelaajaa / 48 maata; FPL: {len(fpl)} pelaajaa")

    matches, ambiguous = match_players(fpl, wc)
    matched_wc_ids = {c["wc_id"] for _, c, _ in matches.values()}

    # Danger-lista: WC-pelaaja jonka club_team on PL-seura mutta ei FPL-matchia
    # (= joko kesasiirto pois PL:sta tai matchausmiss — tarkista kasin).
    danger = [
        w for w in wc
        if w["club_team"] in PL_CLUB_MAP and w["wc_id"] not in matched_wc_ids
    ]

    rows = []
    for p, c, how in matches.values():
        rows.append({
            "player": p["full"],
            "fpl_team": p["team"],
            "country": c["country"],
            "wc_minutes": c["minutes"],
            "wc_matches": c["matches"],
            "wc_name": c["name"],
            "wc_club_at_tournament": c["club_team"],
            "match_how": how,
            "source": SOURCE_TAG,
            "fetched_at": fetched_at,
        })
    rows.sort(key=lambda r: (-r["wc_minutes"], r["fpl_team"], r["player"]))

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        wr.writeheader()
        wr.writerows(rows)
    print(f"Kirjoitettu {OUT_PATH} ({len(rows)} rivia)")

    # Seurakooste minuuteilla painotettuna
    agg: dict[str, dict] = defaultdict(lambda: {"players": 0, "minutes": 0, "m600": 0})
    for r in rows:
        a = agg[r["fpl_team"]]
        a["players"] += 1
        a["minutes"] += r["wc_minutes"]
        if r["wc_minutes"] >= 600:
            a["m600"] += 1
    print("\nSeurakooste (minuuteilla jarjestetty):")
    print(f"{'seura':16s} {'pelaajia':>8s} {'minuutit':>8s} {'>=600min':>8s}")
    for team, a in sorted(agg.items(), key=lambda kv: -kv[1]["minutes"]):
        print(f"{team:16s} {a['players']:8d} {a['minutes']:8d} {a['m600']:8d}")

    print(f"\nAmbiguous ({len(ambiguous)}) — EI kirjattu CSV:hen, tarkista kasin:")
    for p, cands in ambiguous:
        opts = "; ".join(f"{c['name']} ({c['country']})" for c in cands[:4])
        print(f"  FPL {p['full']} [{p['team']}] -> {opts}")

    print(f"\nDanger ({len(danger)}): WC-pelaaja PL-club_teamilla ilman FPL-matchia")
    print("(odotettu syy: kesasiirto pois PL:sta tai seura vaihtunut FPL:ssa):")
    for w in sorted(danger, key=lambda x: -x["minutes"]):
        print(f"  {w['name']:38s} {w['country']:14s} {w['club_team']:26s} {w['minutes']:4d} min")


if __name__ == "__main__":
    main()
