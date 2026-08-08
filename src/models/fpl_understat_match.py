"""FPL ↔ Understat -pelaajamatsays (STATS-ZONE vaihe 2, 8.8.2026).

Lahteilla ei ole yhteista ID:ta, ja tama on sama kustannus jonka takia FBref
hylattiin toisena pelaajalahteena 26.7. Tassa se maksetaan kerran ja mitataan:
matsayksen kattavuus ja tarkkuus ajetaan porttina joka buildissa.

Menetelma on tikapuut, tiukimmasta lofsimpaan. Jokainen askel vaatii
YKSIKASITTEISEN osuman; monikko-osuma putoaa seuraavalle askeleelle tai
hylataan. Loysemmat askeleet (sukunimi, sumea sukunimi) vaativat lisaksi etta
minuutit tasmaavat karkeasti — se on riippumaton signaali nimesta.

Havaitut nimierot 25/26-datasta (miksi pelkka tasmavertailu ei riita):
  Matty Cash / Matthew Cash · Josh King / Joshua King · Joe Gomez / Joseph
  Gomez · Destiny Udogie / Iyenoma Destiny Udogie · Yeremy Pino Santos /
  Yeremi Pino · Yehor Yarmoliuk / Yehor Yarmolyuk · Abdukodir / Abduqodir
  Khusanov · Kroupi.Jr / Eli Junior Kroupi · Alisson Becker / Alisson

Minuutit EIVAT ole identtiset lahteiden valilla (Haaland 2953 vs 2979), joten
niita kaytetaan valjana vahvistuksena, ei avaimena.
"""
from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from difflib import SequenceMatcher

# Merkit joita NFKD ei hajota. ı (turkkilainen pisteeton i) katosi kokonaan
# ilman tata: "Kadıoğlu" -> "kadoglu" != "kadioglu".
CHARMAP = str.maketrans({
    "ø": "o", "ı": "i", "đ": "d", "ł": "l", "ß": "ss", "æ": "ae", "œ": "oe",
    "þ": "th", "ð": "d",
})

FUZZY_MIN = 0.88
MIN_TOLERANCE_ABS = 150
MIN_TOLERANCE_REL = 0.30


def tokens(name: str) -> list[str]:
    s = (name or "").lower().translate(CHARMAP).replace("-", " ").replace("'", "")
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z ]", " ", s).split()


def _minutes_ok(fpl_mins: int, us_mins: int) -> bool:
    tol = max(MIN_TOLERANCE_ABS, int(MIN_TOLERANCE_REL * max(fpl_mins, 1)))
    return abs(us_mins - fpl_mins) <= tol


class UnderstatIndex:
    """Hakuindeksit Understat-riveille (uid, name, mins, ...)."""

    def __init__(self, rows: list[dict]):
        self.rows = rows
        self.by_full: dict[str, list[dict]] = defaultdict(list)
        self.by_surname: dict[str, list[dict]] = defaultdict(list)
        # Kaikki tokenit, ei vain viimeinen: "Amad Diallo Traore" loytyy vain
        # jos "diallo" on hakuavain (FPL:n sukunimi on Diallo, Understatin
        # viimeinen token on Traore).
        self.by_token: dict[str, list[dict]] = defaultdict(list)
        for r in rows:
            t = tokens(r["name"])
            if not t:
                continue
            self.by_full[" ".join(t)].append(r)
            self.by_surname[t[-1]].append(r)
            for tok in set(t):
                self.by_token[tok].append(r)
        self._surnames = list(self.by_surname)

    def _unique(self, key: str, index: dict) -> dict | None:
        hits = index.get(key) or []
        return hits[0] if len(hits) == 1 else None

    def match(self, element: dict) -> tuple[dict | None, str]:
        """FPL bootstrap -element → (understat-rivi | None, menetelma)."""
        first = tokens(element.get("first_name"))
        second = tokens(element.get("second_name"))
        web = tokens(element.get("web_name"))
        # "A.Becker" -> ["a", "becker"]: yhden kirjaimen etuliite on alkukirjain
        if web and len(web[0]) == 1:
            web = web[1:]
        mins = int(element.get("minutes") or 0)

        # Koko nimi ja sukunimi ovat vahvoja avaimia. Pelkka web_name tai
        # pelkka etunimi EI ole: "Gabriel" osui Martinelliin (1065 min) vaikka
        # kyseessa oli 2748 minuutin Gabriel — siksi loysat avaimet vaativat
        # minuuttivahvistuksen samoin kuin sukunimihaku.
        for key, how, needs_mins in (
            (" ".join(first + second), "full", False),
            (" ".join(second), "second", False),
            (" ".join(web), "web", True),
            (" ".join(first), "first", True),
        ):
            if key:
                hit = self._unique(key, self.by_full)
                if hit and (not needs_mins or _minutes_ok(mins, hit["mins"])):
                    return hit, how

        # Token-osajoukko kumpaan suuntaan tahansa: FPL:n "Iyenoma Destiny
        # Udogie" vs Understatin "Destiny Udogie" ja painvastoin.
        fpl_set = set(first + second + web)
        cands: dict[str, dict] = {}
        for tok in fpl_set:
            for r in self.by_token.get(tok, []):
                cands[r["uid"]] = r
        subset = [r for r in cands.values()
                  if set(tokens(r["name"])) <= fpl_set
                  or fpl_set <= set(tokens(r["name"]))]
        if len(subset) == 1 and _minutes_ok(mins, subset[0]["mins"]):
            return subset[0], "subset"

        # Yksikasitteinen nimenosa + minuuttivahvistus. Kaydaan lapi KAIKKI
        # FPL:n tokenit, ei vain viimeista: "Yeremy Pino Santos" tunnistuu
        # vain sanasta "pino" (Understatilla "Yeremi Pino", ja "santos" on
        # yleinen). Uniikkius + minuutit ovat portti vaarille osumille.
        ordered = ([second[-1]] if second else []) + ([web[-1]] if web else [])
        ordered += [t for t in (second + first + web) if t not in ordered]
        for tok in ordered:
            for index in (self.by_surname, self.by_token):
                hit = self._unique(tok, index)
                if hit and _minutes_ok(mins, hit["mins"]):
                    return hit, "surname"

        # Sumea sukunimi (Yarmoliuk/Yarmolyuk) + minuuttivahvistus.
        target = (second[-1] if second else (web[-1] if web else ""))
        if target:
            near = [s for s in self._surnames
                    if SequenceMatcher(None, target, s).ratio() >= FUZZY_MIN]
            hits = [r for s in near for r in self.by_surname[s]
                    if _minutes_ok(mins, r["mins"])]
            if len(hits) == 1:
                return hits[0], "fuzzy"

        return None, "none"


def match_all(elements: list[dict], rows: list[dict],
              min_minutes: int = 450) -> dict:
    """Matsaa kaikki ja palauta mitattava raportti (portin syote)."""
    idx = UnderstatIndex(rows)
    out: dict[str, dict] = {}
    how_counts: dict[str, int] = defaultdict(int)
    considered = matched = 0
    suspect: list[tuple[str, int, int]] = []
    misses: list[str] = []
    for e in elements:
        mins = int(e.get("minutes") or 0)
        hit, how = idx.match(e)
        if hit:
            out[str(e["id"])] = hit
            how_counts[how] += 1
            if mins >= min_minutes and not _minutes_ok(mins, hit["mins"]):
                suspect.append((e.get("web_name", ""), mins, hit["mins"]))
        if mins >= min_minutes:
            considered += 1
            if hit:
                matched += 1
            else:
                misses.append(e.get("web_name", ""))
    return {
        "map": out,
        "considered": considered,
        "matched": matched,
        "coverage": (matched / considered) if considered else 0.0,
        "how": dict(how_counts),
        "suspect": suspect,
        "misses": misses,
    }
