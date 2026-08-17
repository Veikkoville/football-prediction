"""#34 Rate my team — FPL-joukkueen tuonti + xP-pohjainen tiimiarvio.

Käyttäjän FPL-joukkue haetaan JULKISELLA entry-ID:llä (ei kirjautumista, ei
salasanoja — IP/turva). Jokaiseen pelaajaan liitetään committattu xP-projektio
(data/fpl_xp_projections.json, #33 predicted-minutes mukana) → tiimiarvio
(percentiili vs satunnaisotos laillisia budjettijoukkueita) + kapteeni- ja
siirtosuositukset (laillisuus + budjetti kunnioittaen, "hold" jos paras delta
alle kynnyksen — ei yli-ehdoteta siirtoja).

Esikausihuomio: FPL-API:n bootstrap on kesällä vielä edellisen kauden tilassa
→ entry-tuonti palauttaa viimeksi pelatun GW:n joukkueen (element-ID:t ovat
samat kuin projektioissa, jotka on rakennettu samasta bootstrapista). Ennen
GW1-deadlinea frontend voi vaihtoehtoisesti syöttää 15 pelaaja-ID:tä käsin
(players-parametri) — sama arviointipolku, ei FPL-hakua.

Ei kirjoita mitään; /api/fantasy/xp-polku (load_xp) jää bittitarkasti
koskemattomaksi — tämä moduuli vain LUKEE saman projektion.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import requests

from src.models.fpl_xp import load_xp

# 26.7: projektioiden osuvuus rating-vastaukseen. Committoitu tiiviste
# (logs/ on gitignored -> Render ei nakisi sita). Puuttuva tiedosto EI kaada
# rate-teamia: palautetaan None ja UI jattaa rivin pois.
_XP_ACCURACY_PATH = (Path(__file__).resolve().parents[2] / "data"
                     / "fpl_xp_accuracy.json")
_XP_ACCURACY_UNSET = object()
_xp_accuracy_cache: object = _XP_ACCURACY_UNSET


def _load_xp_accuracy() -> dict | None:
    """Luetaan kerran prosessin elinaikana. Puuttuva/rikki tiedosto -> None."""
    global _xp_accuracy_cache
    if _xp_accuracy_cache is _XP_ACCURACY_UNSET:
        try:
            _xp_accuracy_cache = json.loads(
                _XP_ACCURACY_PATH.read_text(encoding="utf-8"))
        except Exception:
            _xp_accuracy_cache = None
    return _xp_accuracy_cache  # type: ignore[return-value]

FPL_BASE = "https://fantasy.premierleague.com/api"
FPL_TIMEOUT_SEC = 15
CACHE_TTL_SEC = 600  # 10 min — promptin vaatimus; FPL-data muuttuu hitaasti

# FPL element_type → positio; kiintiöt 15 pelaajan rungolle ja XI:lle.
POS_NAME = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}
SQUAD_QUOTA = {1: 2, 2: 5, 3: 5, 4: 3}
XI_MIN = {1: 1, 2: 3, 3: 2, 4: 1}
XI_MAX = {1: 1, 2: 5, 3: 5, 4: 3}
MAX_PER_CLUB = 3
BUDGET_TENTHS = 1000  # 100.0 m — satunnaisotoksen budjettiraja

# "Hold"-kynnys: paras yksittäisen siirron horisontti-xP-delta alle tämän →
# suositus on pitää joukkue (siirto ei ole hitin arvoinen; -4 p ≈ 2 GW:n etu).
HOLD_THRESHOLD_XP = 2.0
# FPL:n siirtohitti (-4 p). #63: hold_verdict lasketaan hitin JÄLKEEN —
# ilman vapaata siirtoa (ft=0) netto = delta - 4. fpl_planner käyttää samaa
# arvoa (HIT_COST importataan täältä).
HIT_COST_XP = 4.0
# Kapteenivaihtoehto näytetään jos ero kärkeen on alle tämän (GW-xP).
CAPTAIN_ALT_MARGIN_XP = 0.5



class RateTeamError(Exception):
    """Virhe jolle on selkeä HTTP-status + käyttäjäluettava viesti.

    28.7: `code` on koneluettava syy. Ilman sitä klientti joutuu arvaamaan
    virheen luonteen tekstistä, ja juuri se on tehnyt esikauden 404:sta
    umpikujan: sama status tarkoittaa "ID on väärin" ja "FPL ei ole vielä
    julkaissut kokoonpanoja", joista jälkimmäinen ei ole käyttäjän virhe
    vaan kalenterin tila, ja siihen on toimiva vaihtoehtoinen polku.
    """

    def __init__(self, status_code: int, detail: str, code: str | None = None):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        self.code = code


# ---------------------------------------------------------------------------
# FPL-haku + 10 min TTL-cache (jaettu prosessin sisällä, thread-safe)
# ---------------------------------------------------------------------------

_FPL_CACHE: dict[str, tuple[float, dict]] = {}
_FPL_CACHE_LOCK = threading.Lock()


def _fetch_fpl(path: str) -> dict:
    """#52 deadline-resilienssi: TTL-cache + stale-fallback. FPL:n failatessa
    (verkko / 5xx / 429 — tyypillistä juuri GW-deadlinen ruuhkassa) serveerataan
    viimeisin onnistunut vastaus vaikka TTL olisi ohi — EI virhettä käyttäjälle.
    404 on deterministinen (väärä entry) → nostetaan aina. Ilman cachea →
    hallittu virhe kuten ennen."""
    now = time.time()
    with _FPL_CACHE_LOCK:
        hit = _FPL_CACHE.get(path)
        if hit and now - hit[0] < CACHE_TTL_SEC:
            return hit[1]
    try:
        r = requests.get(f"{FPL_BASE}{path}", timeout=FPL_TIMEOUT_SEC,
                         headers={"User-Agent": "GoalIQ/1.0"})
    except requests.RequestException as e:
        if hit:
            return hit[1]  # stale > virhe (deadline-ilta)
        raise RateTeamError(
            503, "FPL API is not responding right now. Try again in a moment."
        ) from e
    if r.status_code == 404:
        raise RateTeamError(404, "Not found on the FPL API.")
    if r.status_code != 200:
        if hit:
            return hit[1]  # stale > virhe
        raise RateTeamError(
            503, f"FPL API returned an unexpected status ({r.status_code})."
        )
    data = r.json()
    with _FPL_CACHE_LOCK:
        _FPL_CACHE[path] = (now, data)
    return data


def get_bootstrap() -> dict:
    return _fetch_fpl("/bootstrap-static/")


def _resolve_gw(bootstrap: dict, gw: int | None) -> int:
    if gw is not None:
        if not 1 <= gw <= 38:
            raise RateTeamError(400, "gw must be between 1 and 38.")
        return gw
    events = bootstrap.get("events") or []
    current = [e["id"] for e in events if e.get("is_current")]
    if current:
        return current[0]
    nxt = [e["id"] for e in events if e.get("is_next")]
    if nxt:
        return nxt[0]
    raise RateTeamError(503, "FPL API has no current gameweek yet.")


def get_entry_picks(entry_id: int, gw: int) -> dict:
    """Hae entryn picks; erotellaan 'entry ei ole olemassa' vs 'picks puuttuu'."""
    try:
        _fetch_fpl(f"/entry/{entry_id}/")
    except RateTeamError as e:
        if e.status_code == 404:
            raise RateTeamError(
                404, f"FPL entry {entry_id} was not found. Check the ID "
                     "(it is the number in your FPL points-page URL).")
        raise
    try:
        return _fetch_fpl(f"/entry/{entry_id}/event/{gw}/picks/")
    except RateTeamError as e:
        if e.status_code == 404:
            # 28.7: ohjaus vaihdettu fit checkeristä DRAFT RATERIIN, ja lisätty
            # koneluettava code.
            #
            # Vanha kommentti sanoi "ÄLÄ lupaa manuaalisyöttöä, UI:ssa ei ole
            # syöttöä" — se piti paikkansa 23.7. mutta ei enää: draft rater
            # (Rate my draft) rakennettiin sen jälkeen ja tekee TÄSMÄLLEEN
            # saman työn kuin rate my team. Fit checker vastaa eri kysymykseen
            # ("rakenna joukkue näiden pelaajien ympärille"), joten se ohjasi
            # käyttäjän sivuun siitä mitä hän tuli tekemään.
            #
            # Miksi tämä on kiireellinen: FPL 26/27 avautui 23.7. ja GW1 on
            # 21.8. Koko sitä väliä entry-ID-polku palauttaa 404:n, koska FPL
            # julkaisee kokoonpanot vasta deadlinen jälkeen. Se on vuoden
            # korkeimman ostoaikeen ikkuna, ja juuri silloin 1,66 M managerilla
            # ON team ID mutta EI vielä julkaistua kokoonpanoa.
            raise RateTeamError(
                404, f"Your squad is not public yet. FPL publishes every team "
                     f"only after the GW{gw} deadline passes, so this opens up "
                     "when the gameweek locks. Until then, rate the draft you "
                     "are planning: pick your 15 and the model rates that "
                     "squad exactly the same way.",
                code="picks_not_published")
        raise


# ---------------------------------------------------------------------------
# XI-valinta + arvio
# ---------------------------------------------------------------------------

def _best_split(squad: list[dict],
                keep_ids: set[int] | None = None
                ) -> tuple[list[dict], list[dict]] | None:
    """Paras laillinen XI/penkki-jako KIINTEÄSTÄ rungosta.

    Käy kaikki muodostelmat läpi ja poimii per positio parhaat; per-positio-
    valinta on riippumaton, joten tulos on tarkka eikä heuristiikka.

    `keep_ids` = pelaajat jotka on pakko pitää avauksessa (fit checkerin
    lukitut). Ne asetetaan ensin, loput paikat täytetään xP-järjestyksessä.

    Palauttaa (xi, bench) tai None jos laillista XI:tä ei ole.
    """
    keep_ids = keep_ids or set()
    by_pos: dict[int, list[dict]] = {1: [], 2: [], 3: [], 4: []}
    for p in squad:
        by_pos[p["element_type"]].append(p)
    for lst in by_pos.values():
        lst.sort(key=lambda p: p["xp_horizon_total"], reverse=True)
    forced = {t: [p for p in by_pos[t] if p["id"] in keep_ids]
              for t in (1, 2, 3, 4)}

    best: tuple[float, list[dict]] | None = None
    for n_def in range(XI_MIN[2], XI_MAX[2] + 1):
        for n_mid in range(XI_MIN[3], XI_MAX[3] + 1):
            n_fwd = 11 - 1 - n_def - n_mid
            if not XI_MIN[4] <= n_fwd <= XI_MAX[4]:
                continue
            counts = {1: 1, 2: n_def, 3: n_mid, 4: n_fwd}
            if any(len(by_pos[t]) < n for t, n in counts.items()):
                continue
            if any(len(forced[t]) > counts[t] for t in counts):
                continue  # lukitut eivät mahdu tähän muodostelmaan
            xi: list[dict] = []
            for t, n in counts.items():
                rest = [p for p in by_pos[t] if p["id"] not in keep_ids]
                xi += forced[t] + rest[:n - len(forced[t])]
            total = sum(p["xp_horizon_total"] for p in xi)
            if best is None or total > best[0]:
                best = (total, xi)
    if best is None:
        return None
    xi_ids = {p["id"] for p in best[1]}
    return best[1], [p for p in squad if p["id"] not in xi_ids]


def optimal_xi(squad: list[dict]) -> list[dict]:
    """Paras laillinen XI horisontti-xP:llä."""
    split = _best_split(squad)
    if split is None:
        raise RateTeamError(
            400, "Squad cannot form a legal XI (need 1 GKP, 3+ DEF, 2+ MID, "
                 "1+ FWD from 15 players).")
    return split[0]


def _squad_clubs_ok(squad: list[dict]) -> bool:
    counts: dict[int, int] = {}
    for p in squad:
        counts[p["club"]] = counts.get(p["club"], 0) + 1
    return all(c <= MAX_PER_CLUB for c in counts.values())


_OPTIMAL_XP_CACHE: dict[str, dict] = {}
_NEG = float("-inf")
# Viimeisimmän optimoinnin todistustila. Copy saa väittää "paras mahdollinen"
# VAIN kun tämä on True (28.7: aiempi ahne heuristiikka jäi mitatusti 14.19 xP
# optimista ja copy väitti silti parasta mahdollista).
_LAST_OPTIMAL_PROVEN: dict[str, bool] = {"v": False}


def optimal_xi_proven() -> bool:
    """Oliko viimeisin optimal_budget_xi-ajo todistetusti optimaalinen?"""
    return _LAST_OPTIMAL_PROVEN["v"]


def _price_unit(pool: list[dict]) -> int:
    """Suurin yhteinen hintayksikkö (kymmenyksinä). FPL:n esikausihinnat ovat
    tyypillisesti 0.5m:n monikertoja, jolloin DP:n kustannusakseli lyhenee
    viidesosaan ilman että mitään pyöristetään. Kauden aikana hinnat liikkuvat
    0.1m:n askelin → palaa automaattisesti kymmenyksiin."""
    from math import gcd
    u = 0
    for p in pool:
        u = gcd(u, int(p["price"]))
    return u or 1


def _pos_dp(players: list[dict], kmax: int, budget: int, unit: int):
    """0/1-knapsack per positio: dp[k][c] = paras xP kun valittu TASAN k
    pelaajaa hinnalla TASAN c. pick[k][c] = (pelaaja, edellinen c).

    Karsinta on eksakti: samalla hinnalla riittää säilyttää kmax parasta,
    koska useampaa saman hintaista ei voi koskaan valita enempää."""
    by_price: dict[int, list[dict]] = {}
    for p in sorted(players, key=lambda x: -x["xp_horizon_total"]):
        by_price.setdefault(p["price"], [])
        if len(by_price[p["price"]]) < kmax:
            by_price[p["price"]].append(p)
    keep = [p for lst in by_price.values() for p in lst]

    dp = [[_NEG] * (budget + 1) for _ in range(kmax + 1)]
    pick: list[list] = [[None] * (budget + 1) for _ in range(kmax + 1)]
    dp[0][0] = 0.0
    for p in keep:
        c_p = p["price"] // unit
        xp = p["xp_horizon_total"]
        for k in range(kmax - 1, -1, -1):
            row, nxt = dp[k], dp[k + 1]
            for c in range(budget - c_p, -1, -1):
                base = row[c]
                if base == _NEG:
                    continue
                v = base + xp
                if v > nxt[c + c_p]:
                    nxt[c + c_p] = v
                    pick[k + 1][c + c_p] = (p, c)
    return dp, pick


def _maxplus(a: list[float], b: list[float], budget: int) -> list[float]:
    """(max, +) -konvoluutio: paras summa kun kustannukset lasketaan yhteen."""
    out = [_NEG] * (budget + 1)
    for ca, va in enumerate(a):
        if va == _NEG:
            continue
        room = budget - ca
        for cb in range(room + 1):
            vb = b[cb]
            if vb == _NEG:
                continue
            s = va + vb
            if s > out[ca + cb]:
                out[ca + cb] = s
    return out


BENCH_MIN_XMINS = 45.0
# Montako kertaa muodostelman XI-budjettia kiristetään todellisella
# penkkihinnalla ennen kuin muodostelma hylätään (14.8, ks. build_optimal_squad).
_BENCH_FIXPOINT_ROUNDS = 6
_LAST_BENCH: dict[str, list[dict]] = {"v": []}


def bench_of_last_optimum() -> list[dict]:
    """Viimeisimmän benchmark-ajon PENKKI (4 pelaajaa)."""
    return list(_LAST_BENCH["v"])


def _playable(p: dict) -> bool:
    """Kelpaako penkille oikeasti.

    28.7 (Villen havainto): vanha benchmark varasi penkkiin vain *halvimmat*
    pelaajat, mikä on epärealistinen vertailukohta. Siirtoja on rajallisesti,
    joten joskus penkkiläinen ON pakko laittaa kentälle — ja jos hän ei pelaa
    seurassaan lainkaan, joukkue on käytännössä 11 pelaajan varassa koko
    kauden. Vaatimus ei ole "priimaa" vaan "pelaa": 45 odotettua minuuttia
    ottelussa. Villen oma esimerkki (4.5m hyökkääjä) läpäisee tämän.

    Varamaalivahti on tietoinen poikkeus: hän ei pelaa jos ykkönen on kunnossa,
    joten siellä halvin on oikea valinta (Villen sanoin "halpa maalivahti").
    """
    return (p.get("xmins") or 0.0) >= BENCH_MIN_XMINS


def _club_counts(players: list[dict]) -> dict:
    out: dict = {}
    for p in players:
        out[p["club"]] = out.get(p["club"], 0) + 1
    return out


def _shape_of(xi: list[dict]) -> dict[int, int]:
    """XI:n muoto positiolaskureina."""
    out = {1: 0, 2: 0, 3: 0, 4: 0}
    for p in xi:
        out[p["element_type"]] += 1
    return out


def _bench_for_shape(pool: list[dict], shape: dict[int, int],
                     exclude: set[int],
                     club_counts: dict | None = None) -> tuple[list[dict], int]:
    """Muodostelmaa täydentävä halvin PELATTAVA penkki (4 pelaajaa).

    Penkin kokoonpano ei ole vapaa: 15 pelaajan kiintiö on 2/5/5/3, joten
    XI:n muoto määrää mitä penkille jää. Vanha versio otti "3 halvinta
    kenttäpelaajaa" positiosta riippumatta, mikä saattoi olla laiton.
    """
    need = {1: 1, 2: SQUAD_QUOTA[2] - shape[2],
            3: SQUAD_QUOTA[3] - shape[3], 4: SQUAD_QUOTA[4] - shape[4]}
    # 3/klubi koskee KOKO 15:tä, ei vain XI:tä. Ilman tätä penkki saattoi
    # tehdä laillisesta XI:stä laittoman rungon (mock-poolilla 4 samasta
    # seurasta); tuotannossa se meni läpi vain sattumalta.
    clubs = dict(club_counts or {})
    bench: list[dict] = []
    cost = 0
    for t, n in need.items():
        if n <= 0:
            continue
        # GK-penkki: halvin kelpaa. Kenttäpelaajat: pelattavuusvaatimus.
        cands = [p for p in pool
                 if p["element_type"] == t and p["id"] not in exclude
                 and (t == 1 or _playable(p))]
        cands.sort(key=lambda p: (p["price"], -p["xp_horizon_total"]))
        taken = 0
        for p in cands:
            if taken >= n:
                break
            if clubs.get(p["club"], 0) >= MAX_PER_CLUB:
                continue
            bench.append(p)
            clubs[p["club"]] = clubs.get(p["club"], 0) + 1
            cost += p["price"]
            taken += 1
        if taken < n:
            return [], -1
    return bench, cost


def _quota_ok(pool: list[dict], locked_ids: set[int]) -> bool:
    """Riittääkö poolissa pelaajia 15:n kiintiöön 2/5/5/3?"""
    counts: dict[int, int] = {1: 0, 2: 0, 3: 0, 4: 0}
    for p in pool:
        counts[p["element_type"]] += 1
    return all(counts[t] >= n for t, n in SQUAD_QUOTA.items())


def _unconstrained_optimum(pool: list[dict], xi_budget: int,
                           locked: list[dict] | None = None,
                           bench_pool: list[dict] | None = None):
    """Eksakti paras XI ILMAN 3/klubi-rajaa → todistettu YLÄRAJA.

    `bench_pool` (17.8): penkin hinta-arvio lasketaan TASTA, ei `pool`:sta.
    Kun XI:n valinta rajattiin pelaaviin maalivahteihin, `pool` ei enaa sisalla
    halpaa varavahtia — ja koska sama lista syotti seka XI-ehdokkaat etta
    penkkivarauksen, penkki "kallistui" 0,5m ja XI-budjetti kutistui saman
    verran. Oire oli hamaava: kaksi ajoa vaitti molemmat `proven=True` mutta
    antoi eri summan (295,07 vs 294,17), mika on mahdotonta jos molemmat ovat
    eksakteja. DP oli eksakti; syote oli vaara.

    Jos tuloksena oleva XI sattuu täyttämään klubikaton, se on samalla
    todistetusti paras LAILLINEN XI: rajoitteen poistaminen ei voi huonontaa
    optimia, joten kelvollinen ratkaisu ylärajan arvolla on optimi.

    `xi_budget` on YLÄRAJA kaikille muodostelmille; kunkin muodostelman oma
    budjetti lasketaan sen vaatimasta penkistä (28.7).

    `locked` (29.7, #155-yhtenäistys): pakotetut XI-pelaajat. Ne poistetaan
    valinta-avaruudesta ja niiden hinta budjetista, jolloin DP ratkaisee tasan
    jäljellä olevat paikat. Todistus säilyy: lukitut ovat kiinteä vakio, joten
    rajoitteeton optimi jäännösongelmaan + vakio on yläraja koko tehtävälle.

    Palauttaa (xi, total) tai (None, -inf).
    """
    locked = list(locked or [])
    bench_pool = pool if bench_pool is None else bench_pool
    locked_ids = {p["id"] for p in locked}
    locked_shape = _shape_of(locked)
    locked_cost = sum(p["price"] for p in locked)
    locked_xp = sum(p["xp_horizon_total"] for p in locked)

    unit = _price_unit(pool)
    B = max(0, xi_budget - locked_cost) // unit
    by_pos: dict[int, list[dict]] = {1: [], 2: [], 3: [], 4: []}
    for p in pool:
        if p["id"] not in locked_ids:
            by_pos[p["element_type"]].append(p)

    kmax = {1: 1, 2: XI_MAX[2], 3: XI_MAX[3], 4: XI_MAX[4]}
    tables = {t: _pos_dp(by_pos[t], kmax[t], B, unit) for t in (1, 2, 3, 4)}

    best = (_NEG, None)
    for n_def in range(XI_MIN[2], XI_MAX[2] + 1):
        for n_mid in range(XI_MIN[3], XI_MAX[3] + 1):
            n_fwd = 10 - n_def - n_mid
            if not XI_MIN[4] <= n_fwd <= XI_MAX[4]:
                continue
            shape = {1: 1, 2: n_def, 3: n_mid, 4: n_fwd}
            need = {t: shape[t] - locked_shape[t] for t in shape}
            if any(v < 0 for v in need.values()):
                continue  # lukitut eivät mahdu tähän muodostelmaan
            # Muodostelmakohtainen budjetti: 100.0m miinus TÄMÄN muodon
            # vaatima pelattava penkki.
            _bench, bench_cost = _bench_for_shape(bench_pool, shape, locked_ids)
            if bench_cost < 0:
                continue
            b_shape = (BUDGET_TENTHS - bench_cost - locked_cost) // unit
            if b_shape < 0:
                continue
            rows = [tables[t][0][n] for t, n in need.items()]
            acc = rows[0]
            for r in rows[1:]:
                acc = _maxplus(acc, r, B)
            top = max(acc[:b_shape + 1]) if b_shape <= B else max(acc)
            if top > best[0]:
                best = (top, (shape, need, min(b_shape, B)))
    if best[1] is None or best[0] == _NEG:
        return None, _NEG

    # Rekonstruktio: etsi kustannusjako joka toteuttaa optimin, sitten pelaajat.
    shape, need, shape_budget = best[1]
    order = [1, 2, 3, 4]
    rows = {t: tables[t][0][need[t]] for t in order}

    def _split(idx: int, budget_left: int, target: float, chosen: list[int]):
        t = order[idx]
        if idx == len(order) - 1:
            for c in range(budget_left + 1):
                if rows[t][c] != _NEG and abs(rows[t][c] - target) < 1e-6:
                    return chosen + [c]
            return None
        for c in range(budget_left + 1):
            v = rows[t][c]
            if v == _NEG:
                continue
            got = _split(idx + 1, budget_left - c, target - v, chosen + [c])
            if got is not None:
                return got
        return None

    costs = _split(0, shape_budget, best[0], [])
    if costs is None:
        return None, _NEG
    xi: list[dict] = list(locked)
    for t, c in zip(order, costs):
        _dp, pick = tables[t]
        k, cur = need[t], c
        while k > 0:
            entry = pick[k][cur]
            if entry is None:
                return None, _NEG
            p, prev = entry
            xi.append(p)
            k, cur = k - 1, prev
    return ((xi, best[0] + locked_xp) if len(xi) == 11
            else (None, _NEG))


def _improve_legal(xi: list[dict], pool: list[dict], xi_budget: int,
                   keep_ids: set[int] | None = None) -> list[dict]:
    """Paikallishaku: vaihda yksi pelaaja kerrallaan parempaan samassa
    positiossa niin kauan kuin budjetti ja klubikatto sallivat. Käytetään VAIN
    kun eksakti optimi rikkoo klubikaton — ahne lähtökohta jää muuten
    todistettavasti kauas (mitattu 28.7: 288.23 vs 302.42).

    `keep_ids` = lukitut pelaajat, joita ei saa vaihtaa pois (fit checker)."""
    keep_ids = keep_ids or set()
    cur = list(xi)
    ids = {p["id"] for p in cur}
    improved = True
    while improved:
        improved = False
        for i, out in enumerate(cur):
            if out["id"] in keep_ids:
                continue
            for cand in pool:
                if (cand["element_type"] != out["element_type"]
                        or cand["id"] in ids
                        or cand["xp_horizon_total"] <= out["xp_horizon_total"]):
                    continue
                new = cur[:i] + [cand] + cur[i + 1:]
                if (sum(p["price"] for p in new) <= xi_budget
                        and _squad_clubs_ok(new)):
                    ids.discard(out["id"])
                    ids.add(cand["id"])
                    cur = new
                    improved = True
                    break
            if improved:
                break
    return cur


def build_optimal_squad(pool: list[dict],
                        locked: list[dict] | None = None) -> dict:
    """Paras laillinen 15, ALOITUSVAHTI pelaava. Ks. _build_optimal_squad.

    KORJAUS 17.8 (loytyi tuotannosta, luojan postauksesta). Fit checker palautti
    aloituskokoonpanoon Steelen (BHA, 4.0m), jonka oma xP-mallimme antaa
    **19,3 odotettua minuuttia ja 5,74 pistetta** kuudelle kierrokselle.
    Verbruggen maksaa 0,5m enemman ja tuottaa 22,76. Otsikko lukee "BEST XI
    AROUND YOUR LOCKS", joten se oli vaara vaite mallin OMILLA luvuilla.

    Juurisyy oli `playable_pool`-rajauksen maalivahtipoikkeus: penkkivahti EI
    pelaa jos ykkonen on kunnossa, joten halvin on siella oikea valinta, ja
    siksi maalivahdit vapautettiin `_playable`-suodattimesta kokonaan. Vapautus
    oli oikein penkille mutta koski myos avausta, joten kireassa budjetissa
    ahne tayttö osti KAKSI ei-pelaavaa vahtia ja toinen niista jai avaukseen.
    Laukaisin on budjetti: rivi 700 hylkaa kalliimman vahdin varauslaskennassa.

    Korjaus rajaa VAIN aloituskokoonpanon valinnan pelaaviin vahteihin; penkin
    valinta kayttaa yha koko poolia, joten halpa varavahti sailyy. Jos pelaavaa
    vahtia ei saada mahtumaan lainkaan, palataan vanhaan kayttaytymiseen eika
    palauteta virhetta: huonompi vastaus on parempi kuin ei vastausta.
    """
    res = _build_optimal_squad(pool, locked, require_playable_gk=True)
    if res["xi"]:
        return res
    return _build_optimal_squad(pool, locked, require_playable_gk=False)


def _build_optimal_squad(pool: list[dict],
                         locked: list[dict] | None = None,
                         require_playable_gk: bool = True) -> dict:
    """Paras laillinen 15 (XI + pelattava penkki), valinnaisilla lukituilla.

    YKSI LÄHDE (29.7): tätä käyttävät sekä #50-benchmark (locked=[]) että
    #155-fit-checker (locked=1-3 pelaajaa). Aiemmin fit checkerillä oli oma
    vanhempi ahne optimoija ilman eksaktia hakua ja ilman pelattavaa penkkiä,
    jolloin kaksi pintaa väitti eri lukua "mallin parhaaksi": fit 282.31 vs
    benchmark 303.34 (mitattu tuotannosta 28.7). Sama koneisto molemmilla
    poistaa ristiriidan rakenteellisesti, ei kirjanpidolla.

    Palauttaa {"xi", "bench", "xi_xp", "proven"}; xi=[] jos runkoa ei saada.
    "proven" = XI on todistetusti paras laillinen (eksakti DP osui laillisena),
    ei pelkkä heuristiikan paras — copy saa sanoa "best" vain silloin.

    MIKSI ERIKSEEN (26.7): "Model XI" halutaan renderöidä kenttägrafiikkana
    julkiselle webille, ja siihen tarvitaan rivit eikä yhtä lukua. Logiikka on
    tässä yhdessä paikassa, ja optimal_budget_team_xp kutsuu tätä → benchmark
    ja grafiikka eivät voi eriytyä toisistaan.

    Heuristiikka (dokumentoitu, deterministinen — ei globaali optimi mutta kova
    ja rehellinen benchmark):
      1. Penkkireservi: halvin GKP + 3 halvinta kenttäpelaajaa (XI:n
         ulkopuolinen raha minimiin) → XI-budjetti = 100.0m − reservi.
      2. Jokainen laillinen MUODOSTELMA erikseen (3-5 DEF, 2-5 MID, 1-3 FWD),
         kussakin ahne valinta horisontti-xP:llä; max 3/klubi ja joka
         poiminnalla varmistetaan että loput paikat voi vielä täyttää
         halvimmalla mahdollisella (budjetti ei lukkiudu). Paras voittaa.

    KORJAUS 26.7 (Villen bugilöytö): aiemmin ajettiin YKSI ahne passi ilman
    muodostelmavertailua, jolloin muoto valikoitui sivutuotteena. Se jätti
    paremmat muodot löytämättä: Villen oikea joukkue (5-4-2, 279.4 xP, 82.5m)
    voitti benchmarkin (4-4-2, 277.7 xP, 84.0m) ja sai clampista harhaanjohtavan
    "100 % of the best possible team". Muodostelmien läpikäynti poistaa juuri
    tämän aukon.

    KORJAUS 14.8 (mitattu tuotannosta: julkaistu XI 277.49, sama 15 parhaalla
    jaolla 298.05 = +7.4 %). Kolme toisiaan ruokkivaa vikaa:
      a) XI/penkki-jakoa ei optimoitu uudelleen sen jälkeen kun 15 oli koossa,
         eikä muodostelmia pisteytetty sillä luvulla → malli penkitti Beton
         (18.44) ja aloitti O'Nienin (8.15).
      b) Ahne täyttö varasi jäljellä oleville paikoille POOLIN halvimman hinnan
         (4.0m = puolustaja), vaikka viimeinen slotti olisi hyökkääjä (4.5m) →
         kuusi kahdeksasta muodostelmasta ei saanut XI:tä kokoon lainkaan ja
         26.7 lisätty muodostelmavertailu oli käytännössä kuollut koodi.
      c) Muodostelman penkkivaraus laskettiin poolista JOSTA XI:tä ei ollut
         poistettu → varaus alitti todellisen penkkihinnan, runko ylitti
         100.0m ja koko muodostelma pudotettiin sen sijaan että budjettia
         olisi kiristetty.

    Palauttaa [] jos laillista XI:tä ei saada kokoon.
    """
    locked = list(locked or [])
    locked_ids = {p["id"] for p in locked}
    locked_shape = _shape_of(locked)
    empty: dict = {"xi": [], "bench": [], "xi_xp": 0.0, "proven": False}

    # 14.8: mallin oma runko rakennetaan PELATTAVISTA kenttäpelaajista.
    # Penkin 45 min -vaatimus (28.7) koski ennen vain penkkiä, jolloin ahne
    # täyttö saattoi ostaa XI-täytteeksi pelaajan jota ei voi koskaan penkittää
    # (Destan, 33.5 min) ja joka jäi siksi pysyvästi avaukseen. Mitattu: paras
    # ei-pelattava kenttäpelaaja on 16.72 xP, halvin pelattava samassa hinnassa
    # 22.52-23.36 → rajaus ei maksa mitään mutta poistaa koko vikaluokan.
    # Varamaalivahti on sama tietoinen poikkeus kuin _playable-dokumentissa.
    playable_pool = [p for p in pool
                     if p["element_type"] == 1 or _playable(p)
                     or p["id"] in locked_ids]
    if _quota_ok(playable_pool, locked_ids):
        pool = playable_pool

    by_pos: dict[int, list[dict]] = {1: [], 2: [], 3: [], 4: []}
    for p in pool:
        by_pos[p["element_type"]].append(p)
    if any(len(by_pos[t]) < n for t, n in SQUAD_QUOTA.items()):
        return empty

    # 17.8: ALOITUSKOKOONPANON pooli erikseen. `pool` sailyy penkin valintaan,
    # jotta halpa varavahti loytyy yha; XI:n vahdiksi kelpaa vain pelaava.
    # Ilman tata erottelua kireassa budjetissa avaukseen paatyi 19 minuutin
    # vahti (ks. build_optimal_squadin docstring).
    xi_pool = pool
    if require_playable_gk:
        cand = [p for p in pool
                if p["element_type"] != 1 or _playable(p) or p["id"] in locked_ids]
        if any(p["element_type"] == 1 for p in cand):
            xi_pool = cand
    xi_by_pos: dict[int, list[dict]] = {1: [], 2: [], 3: [], 4: []}
    for p in xi_pool:
        xi_by_pos[p["element_type"]].append(p)
    if any(not xi_by_pos[t] for t in xi_by_pos):
        return empty
    # Per-positio-halvin: ahne täyttö varaa jäljellä oleville paikoille TÄMÄN,
    # ei poolin globaalia minimiä (ks. korjaus b yllä). Lasketaan XI-poolista,
    # koska varaus koskee XI-paikkoja: pool-minimi aliarvioisi vahtislotin nyt
    # kun avaukseen ei kelpaa halvin ei-pelaava vahti.
    pos_min = {t: min(p["price"] for p in xi_by_pos[t]) for t in xi_by_pos}

    # 28.7 (Villen havainto): penkkireservi lasketaan PELATTAVASTA penkistä,
    # ei kolmesta halvimmasta. Tässä lasketaan vain kaikkien muodostelmien
    # HALVIN mahdollinen penkki, jotta DP:n kustannusakseli on tarpeeksi pitkä;
    # kukin muodostelma käyttää sisällä omaa, tiukempaa budjettiaan.
    cheapest_bench = None
    bench_lb: dict[tuple[int, int, int], int] = {}
    for n_def in range(XI_MIN[2], XI_MAX[2] + 1):
        for n_mid in range(XI_MIN[3], XI_MAX[3] + 1):
            n_fwd = 10 - n_def - n_mid
            if not XI_MIN[4] <= n_fwd <= XI_MAX[4]:
                continue
            shape = {1: 1, 2: n_def, 3: n_mid, 4: n_fwd}
            if any(shape[t] < locked_shape[t] for t in shape):
                continue
            _b, c = _bench_for_shape(pool, shape, locked_ids)
            if c >= 0:
                bench_lb[(n_def, n_mid, n_fwd)] = c
                if cheapest_bench is None or c < cheapest_bench:
                    cheapest_bench = c
    if cheapest_bench is None:
        return empty
    # DP:n kustannusakseli tarvitsee LÖYSIMMÄN varauksen (muuten eksakti
    # yläraja jäisi laskematta); muodostelmakohtainen kiristys tehdään
    # varapolulla per shape, ks. bench_lb-käyttö alla.
    xi_budget = BUDGET_TENTHS - cheapest_bench

    # XI valitaan xi_poolista (pelaava vahti); penkki yha koko poolista.
    ranked = sorted(xi_pool, key=lambda p: p["xp_horizon_total"], reverse=True)

    def _fill(shape: dict[int, int], budget: int) -> list[dict]:
        """Ahne täyttö KIINTEÄLLE muodostelmalle, lukitut pohjalla.

        `budget` on TÄMÄN muodostelman XI-budjetti (100.0m − sen oma halvin
        pelattava penkki). 13.8: aiemmin tässä käytettiin kaikkien
        muodostelmien halvinta penkkiä, jolloin kalliimman penkin vaativa
        muoto sai liikaa rahaa XI:hin ja lopullinen 15 ylitti budjetin
        äänettömästi — tuotannossa 101.5m eli runko jota ei voi omistaa.
        Palauttaa [] jos ei onnistu."""
        xi: list[dict] = list(locked)
        counts = _shape_of(xi)
        clubs: dict = _club_counts(xi)
        cost = sum(p["price"] for p in xi)
        if any(counts[t] > shape[t] for t in shape):
            return []
        if any(n > MAX_PER_CLUB for n in clubs.values()):
            return []
        for p in ranked:
            if len(xi) == 11:
                break
            if p["id"] in locked_ids:
                continue
            t = p["element_type"]
            if counts[t] >= shape[t]:
                continue
            if clubs.get(p["club"], 0) >= MAX_PER_CLUB:
                continue
            # Budjettiturvaus: loput paikat halvimmalla täytettävissä —
            # POSITIOKOHTAISESTI. 14.8: globaali minimi (4.0m puolustaja)
            # aliarvioi 4.5m:n hyökkääjä- ja keskikenttäslotit, jolloin ahne
            # täyttö jätti viimeisen paikan täyttämättä ja koko muodostelma
            # katosi vertailusta äänettömästi.
            reserve = sum(pos_min[q] * (shape[q] - counts[q]) for q in shape)
            reserve -= pos_min[t]
            if cost + p["price"] + reserve > budget:
                continue
            xi.append(p)
            counts[t] += 1
            clubs[p["club"]] = clubs.get(p["club"], 0) + 1
            cost += p["price"]
        return xi if len(xi) == 11 else []

    def _result(xi: list[dict], proven: bool) -> dict:
        if not xi:
            return empty
        bench, bench_cost = _bench_for_shape(
            pool, _shape_of(xi), {p["id"] for p in xi}, _club_counts(xi))
        # 13.8: viimeinen vahti. Runko joka ylittää 100.0m ei ole omistettava,
        # eikä sitä saa palauttaa "mallin joukkueena" — se meni ennen läpi
        # äänettömästi, koska vain eksakti polku tarkisti kokonaishinnan.
        if not bench or sum(p["price"] for p in xi) + bench_cost > BUDGET_TENTHS:
            return empty
        # 14.8: XI/penkki-jako uudelleen KOKO 15:stä. Ahne passi valitsi XI:n
        # ennen kuin penkki oli olemassa, joten jako jäi lukkoon siihen mitä
        # täyttöjärjestys sattui tuottamaan. 15:n kiintiö 2/5/5/3 takaa että
        # jäljelle jää aina 1 GKP + 3 kenttäpelaajaa, eli jako on aina laillinen.
        squad = xi + bench
        split = _best_split(squad, locked_ids)
        if split is not None:
            xi, bench = split
        return {
            "xi": xi,
            "bench": bench,
            "xi_xp": sum(p["xp_horizon_total"] for p in xi),
            "proven": proven,
        }

    # --- 1. EKSAKTI polku (28.7): DP ilman klubikattoa = todistettu yläraja.
    # XI-ehdokkaat xi_poolista, penkin hinta-arvio koko poolista.
    exact, exact_total = _unconstrained_optimum(
        xi_pool, xi_budget, locked, bench_pool=pool)
    if exact and _squad_clubs_ok(exact):
        # Kelvollinen ratkaisu ylärajan arvolla ⇒ todistetusti optimi.
        # 14.8: sama _result kuin varapolulla, jotta polut eivät voi eriytyä
        # jaossa. Uudelleenjako ei voi ylittää ylärajaa (yläraja pätee mille
        # tahansa lailliselle 15:lle), joten "proven" säilyy pätevänä.
        res = _result(exact, True)
        if res["xi"]:
            return res
        # Klubikatto teki oletetun penkin kalliimmaksi kuin varaus → tämä XI
        # ei ole rahoitettavissa. Pudotaan varapolulle, joka tarkistaa
        # rungon kokonaisuutena.

    # --- 2. Varapolku: klubikatto sitoo → ahne + paikallishaku.
    best_res: dict = empty
    best_total = -1.0
    for n_def in range(XI_MIN[2], XI_MAX[2] + 1):
        for n_mid in range(XI_MIN[3], XI_MAX[3] + 1):
            n_fwd = 10 - n_def - n_mid
            if not XI_MIN[4] <= n_fwd <= XI_MAX[4]:
                continue
            # Muodostelmakohtainen budjetti: tämän muodon oma halvin
            # pelattava penkki, ei kaikkien muotojen halvin.
            lb = bench_lb.get((n_def, n_mid, n_fwd))
            if lb is None:
                continue
            shape = {1: 1, 2: n_def, 3: n_mid, 4: n_fwd}
            # Kiintopiste: bench_lb laskettiin poolista josta XI:tä ei ollut
            # poistettu, joten se ALIARVIOI penkin hinnan. Jos runko ylittää
            # 100.0m, kiristetään XI-budjettia todellisella penkkihinnalla ja
            # yritetään uudelleen — ennen tässä muodostelma vain katosi.
            reserve = lb
            for _ in range(_BENCH_FIXPOINT_ROUNDS):
                shape_budget = BUDGET_TENTHS - reserve
                cand = _fill(shape, shape_budget)
                if not cand:
                    break
                cand = _improve_legal(cand, xi_pool, shape_budget, locked_ids)
                _bench, bcost = _bench_for_shape(
                    pool, _shape_of(cand), {p["id"] for p in cand},
                    _club_counts(cand))
                if not _bench:
                    break
                if sum(p["price"] for p in cand) + bcost <= BUDGET_TENTHS:
                    # Muodostelmat pisteytetään KOKO 15:n parhaalla jaolla,
                    # ei ahneen passin XI:llä (korjaus a).
                    res = _result(cand, False)
                    if res["xi"] and res["xi_xp"] > best_total:
                        best_total, best_res = res["xi_xp"], res
                    break
                if bcost <= reserve:
                    break  # ei kiristy → ei ratkea
                reserve = bcost
    # Jos paikallishaku osuu ylärajaan, ratkaisu on silti todistetusti optimi.
    if best_res["xi"] and exact_total != _NEG \
            and abs(best_total - exact_total) < 1e-6:
        best_res = dict(best_res, proven=True)
    return best_res


def optimal_budget_xi(pool: list[dict]) -> list[dict]:
    """#50-benchmarkin XI (ei lukittuja). Ohut kääre build_optimal_squadille,
    joka pitää moduulitason todistus-/penkkitilan ennallaan vanhoille
    kutsujille (rate_team-payload + model-xi-sivu)."""
    res = build_optimal_squad(pool)
    _LAST_OPTIMAL_PROVEN["v"] = res["proven"]
    _LAST_BENCH["v"] = res["bench"]
    return res["xi"]


def free_optimum(pool: list[dict], cache_key: str) -> dict:
    """Vapaa optimi (ei lukittuja) välimuistista — KOKO tulos, ei pelkkä luku.

    29.7: välimuisti säilöi ennen vain xP:n, jolloin osumalla `optimal_xi_proven()`
    palautti edellisen ajon lipun eikä välimuistiin osuneen. Sama arvo samalla
    poolilla, joten oire ei näkynyt — mutta lippu on nimenomaan rehellisyysportti,
    joten sen ei kuulu roikkua globaalissa tilassa. Nyt lippu ja penkki tulevat
    aina samasta tuloksesta kuin luku.

    Fit checker (#155) käyttää TÄTÄ vertailukohtanaan → sen "vapaa optimi" ei voi
    poiketa rate-teamin benchmarkista.
    """
    hit = _OPTIMAL_XP_CACHE.get(cache_key)
    if hit is None:
        hit = build_optimal_squad(pool)
        _OPTIMAL_XP_CACHE.clear()
        _OPTIMAL_XP_CACHE[cache_key] = hit
    return hit


def optimal_budget_team_xp(pool: list[dict], cache_key: str) -> float:
    """#50: paras mahdollinen laillinen budjettijoukkue -benchmark (XI:n
    horisontti-xP). Korvaa satunnaisotoksen: "300 random squads" antoi lähes
    kaikille oikeille joukkueille ~100 % = ontto imartelu (Hub 2,0★ -oppi 4).

    Rakentaa XI:n build_optimal_squadilla → yksi optimoija, ei kahta."""
    res = free_optimum(pool, cache_key)
    _LAST_OPTIMAL_PROVEN["v"] = res["proven"]
    _LAST_BENCH["v"] = res["bench"]
    return res["xi_xp"]


def _line_strength(xi: list[dict], pool: list[dict]) -> tuple[str, str]:
    """Vahvin/heikoin rivi: XI:n rivin keski-xP/GW suhteessa poolin saman
    position keskiarvoon (suhde > 1 = rivi on poolikeskiarvoa vahvempi)."""
    pool_avg: dict[int, float] = {}
    for t in POS_NAME:
        vals = [p["xp_per_gw"] for p in pool if p["element_type"] == t]
        pool_avg[t] = sum(vals) / len(vals) if vals else 0.0
    ratios: dict[str, float] = {}
    for t, name in POS_NAME.items():
        vals = [p["xp_per_gw"] for p in xi if p["element_type"] == t]
        if vals and pool_avg[t] > 0:
            ratios[name] = (sum(vals) / len(vals)) / pool_avg[t]
    if not ratios:
        return "", ""
    strongest = max(ratios, key=ratios.get)
    weakest = min(ratios, key=ratios.get)
    return strongest, weakest


# ---------------------------------------------------------------------------
# Suositukset
# ---------------------------------------------------------------------------

def _gw_xp(player: dict, gw: int) -> float:
    for g in player.get("gameweeks") or []:
        if g.get("gw") == gw:
            return float(g.get("xp") or 0.0)
    return 0.0


def _player_gameweeks(p: dict) -> list[dict]:
    """#122/#123: per-GW-xP + vastustajat vastaukseen (sama muoto kuin
    /api/fantasy/xp:n FantasyXpGameweek). DGW = useampi opponent, BGW = []."""
    return [
        {
            "gw": g.get("gw"),
            "opponents": g.get("opponents") or [],
            "xp": round(float(g.get("xp") or 0.0), 2),
        }
        for g in (p.get("gameweeks") or [])
    ]


def captain_suggestion(xi: list[dict], gw: int) -> dict:
    ranked = sorted(xi, key=lambda p: _gw_xp(p, gw), reverse=True)
    pick = ranked[0]
    out = {"pick": {"id": pick["id"], "web_name": pick["web_name"],
                    "team_short": pick["team_short"],
                    "gw_xp": round(_gw_xp(pick, gw), 2)},
           "alternative": None}
    if len(ranked) > 1:
        alt = ranked[1]
        if _gw_xp(pick, gw) - _gw_xp(alt, gw) < CAPTAIN_ALT_MARGIN_XP:
            out["alternative"] = {"id": alt["id"], "web_name": alt["web_name"],
                                  "team_short": alt["team_short"],
                                  "gw_xp": round(_gw_xp(alt, gw), 2)}
    return out


def transfer_suggestions(squad: list[dict], pool: list[dict],
                         bank_tenths: int) -> dict:
    """Top 3–5 yhden pelaajan siirtoa: sama positio, budjetti (bank + myyntihinta
    = now_cost, MVP-yksinkertaistus), max 3/klubi vaihdon JÄLKEEN, suurin
    horisontti-xP-delta. Deltat ovat per-siirto (eivät summaudu — budjetti
    jaetaan). 'hold' jos paras delta < kynnys."""
    squad_ids = {p["id"] for p in squad}
    club_counts: dict[int, int] = {}
    for p in squad:
        club_counts[p["club"]] = club_counts.get(p["club"], 0) + 1

    # 28.7 (Villen bugilöytö): delta lasketaan AVAUSKOKOONPANOSTA, ei pelaajien
    # raakaerotuksesta.
    #
    # Vanha kaava (in.xP - out.xP) lupasi Villelle "+18.74 xP over the horizon"
    # kakkosvahdin vaihdosta. Todennettu tuotannosta ajamalla sama 15 ennen ja
    # jälkeen: XI-xP 315.31 -> 315.31, rating 92 -> 92. Muutos oli TASAN NOLLA,
    # koska kumpikaan vahti ei nouse Verbruggenin ohi. Luku oli tosi pelaajien
    # välillä ja epätosi pisteinä — ja se on silmukan pääsuositus, johon
    # käyttäjä kirjaa "following the model".
    #
    # Raakaerotus säilyy YLÄRAJANA ja siksi kelpaa haarukointiin: jos uusi XI
    # käyttää tulokasta, hänen korvaamisensa lähtijällä antaa laillisen vanhan
    # XI:n (sama positio) → XI-hyöty ≤ raakaerotus. Käydään kandidaatit läpi
    # raakaerotus laskevassa järjestyksessä ja lopetetaan kun se alittaa jo
    # löydetyn parhaan todellisen hyödyn: tulos on eksakti, ei otos.
    base_xi_xp = sum(p["xp_horizon_total"] for p in optimal_xi(squad))
    squad_by_id = {p["id"]: p for p in squad}

    def _xi_gain(out_p: dict, in_p: dict) -> float:
        new_squad = [in_p if p["id"] == out_p["id"] else p for p in squad]
        return sum(p["xp_horizon_total"] for p in optimal_xi(new_squad)) - base_xi_xp

    cands = []
    for out_p in squad:
        budget = bank_tenths + out_p["price"]
        for in_p in pool:
            if in_p["id"] in squad_ids:
                continue
            if in_p["element_type"] != out_p["element_type"]:
                continue
            if in_p["price"] > budget:
                continue
            # klubiraja vaihdon jälkeen
            after = club_counts.get(in_p["club"], 0) + 1
            if in_p["club"] != out_p["club"] and after > MAX_PER_CLUB:
                continue
            raw = in_p["xp_horizon_total"] - out_p["xp_horizon_total"]
            if raw <= 0:
                continue
            cands.append((raw, out_p["id"], in_p["id"], out_p, in_p))

    cands.sort(key=lambda c: c[0], reverse=True)
    scored: list[tuple[float, float, dict, dict]] = []
    best_gain = 0.0
    for raw, _oid, _iid, out_p, in_p in cands:
        # Haarukointi: raakaerotus on yläraja, joten tästä eteenpäin ei voi
        # enää löytyä 5. parasta parempaa kun lista on jo täynnä.
        if len(scored) >= 5 and raw <= min(s[0] for s in scored):
            break
        gain = _xi_gain(out_p, in_p)
        if gain <= 0:
            continue
        best_gain = max(best_gain, gain)
        scored.append((gain, raw, out_p, in_p))
        scored.sort(key=lambda s: s[0], reverse=True)
        del scored[5:]

    suggestions = []
    for gain, raw, out_p, in_p in scored:
        suggestions.append({
            "out": {"id": out_p["id"], "web_name": out_p["web_name"],
                    "team_short": out_p["team_short"],
                    "price": out_p["price"] / 10.0},
            # #121: in-pelaajalle täydet planner-kentät → apply-to-planner
            # voi liittää pelaajan pitchiin ilman lisäkutsua.
            "in": {"id": in_p["id"], "web_name": in_p["web_name"],
                   "team_short": in_p["team_short"],
                   "price": in_p["price"] / 10.0,
                   "xp_per_gw": round(in_p["xp_per_gw"], 2),
                   "xp_horizon_total": round(in_p["xp_horizon_total"], 2),
                   "gameweeks": _player_gameweeks(in_p)},
            "pos": POS_NAME[out_p["element_type"]],
            # Hyöty AVAUSKOKOONPANOON, ei pelaajien raakaerotus (28.7).
            "delta_xp_horizon": round(gain, 2),
            # Raakaerotus jää näkyviin läpinäkyvyyden vuoksi: se kertoo
            # pelaajien eron, ja ero näihin kahteen lukuun ON se asia jonka
            # vanha versio piilotti (syvyysparannus ≠ pisteparannus).
            "delta_xp_squad": round(raw, 2),
            "delta_cost": round((in_p["price"] - out_p["price"]) / 10.0, 1),
        })
    top = suggestions[:5]
    hold = not top or top[0]["delta_xp_horizon"] < HOLD_THRESHOLD_XP
    return {
        "suggestions": top,
        "hold": hold,
        "note": ("Best available single-transfer gain is small - holding your "
                 "team is a fine play this week." if hold else
                 "Deltas are per single transfer over the projection horizon; "
                 "they do not simply add up (budget is shared)."),
    }


def build_hold_verdict(best_gain_xp: float | None, horizon_gws: int,
                       ft: int = 1) -> dict:
    """#63: eksplisiittinen hero-verdikti UI-kannaksi. Hit-tietoinen: ilman
    vapaata siirtoa (ft=0) siirron netto = delta - HIT_COST_XP → verdikti
    lasketaan hitin JÄLKEEN (vanha `hold`-bool jää bruttona ennalleen,
    yhteensopivuus). Kynnys = HOLD_THRESHOLD_XP netolle."""
    hit = 0.0 if ft > 0 else HIT_COST_XP
    if best_gain_xp is None:
        return {
            "verdict": "hold",
            "best_move_gain_xp": None,
            "horizon_gws": horizon_gws,
            "threshold_xp": HOLD_THRESHOLD_XP,
            "hit_applied_xp": hit,
            "message": (f"No transfer beats your team over the next "
                        f"{horizon_gws} GWs - holding is the play."),
        }
    net = round(best_gain_xp - hit, 2)
    hold = net < HOLD_THRESHOLD_XP
    hit_note = " after a -4 hit" if hit else ""
    if hold:
        message = (f"Your best move gains only {net:+.1f} xP over "
                   f"{horizon_gws} GWs{hit_note} - holding is the play.")
    else:
        message = (f"Your best move gains {net:+.1f} xP over "
                   f"{horizon_gws} GWs{hit_note} - worth a transfer.")
    return {
        "verdict": "hold" if hold else "transfer",
        "best_move_gain_xp": net,
        "horizon_gws": horizon_gws,
        "threshold_xp": HOLD_THRESHOLD_XP,
        "hit_applied_xp": hit,
        "message": message,
    }


# ---------------------------------------------------------------------------
# Pääorkestrointi
# ---------------------------------------------------------------------------

def _projection_pool(xp_data: dict, price_by_id: dict[int, dict]) -> list[dict]:
    """Yhdistä projektio + bootstrap-hinta/klubi. Pelaaja ilman bootstrap-riviä
    pudotetaan poolista (ei voida hinnoitella siirtoa/otosta)."""
    pool = []
    pos_by_name = {v: k for k, v in POS_NAME.items()}
    for p in xp_data.get("players") or []:
        boot = price_by_id.get(p["id"])
        if not boot:
            continue
        try:
            owned_pct = float(boot.get("selected_by_percent") or 0.0)
        except (TypeError, ValueError):
            owned_pct = 0.0
        pool.append({
            "id": p["id"], "web_name": p["web_name"],
            "team_short": p.get("team_short") or "",
            "element_type": pos_by_name.get(p.get("pos"), boot["element_type"]),
            "club": boot["team"],
            "price": boot["now_cost"],
            "owned_pct": owned_pct,
            "xp_per_gw": float(p.get("xp_per_gw") or 0.0),
            "xp_horizon_total": float(p.get("xp_horizon_total") or 0.0),
            "gameweeks": p.get("gameweeks") or [],
            # #35 compare: erittelykentät kulkevat poolin mukana
            "xmins": p.get("xmins"),
            # 5.8: vauhti tulee putkesta ja sen ON kuljettava poolin mukana.
            # Pool muotoilee rivin uusiksi, joten kentta joka ei ole TASSA
            # listassa katoaa aanettomasti — juuri siksi alkuperainen toteutus
            # laski vauhdin uudestaan value-listalla (ja laski sen vaarin).
            "xp_per_90": p.get("xp_per_90"),
            # 5.8: vauhti tulee putkesta ja sen ON kuljettava poolin mukana.
            # Pool muotoilee rivin uusiksi, joten kentta joka ei ole TASSA
            # listassa katoaa aanettomasti — juuri siksi alkuperainen toteutus
            # laski vauhdin uudestaan value-listalla (ja laski sen vaarin).
            "predicted_starts": p.get("predicted_starts"),
            "minutes_confidence": p.get("minutes_confidence"),
            # 15.8: saatavuus kentalle. Lisasin nama ensin VAIN vastausriviin
            # ja arvo oli `None` tuotannossa — tasan se ansa jota yllaoleva
            # 5.8:n kommentti varoittaa: pool muotoilee rivin uusiksi, joten
            # kentta joka ei ole TASSA listassa katoaa aanettomasti. Luin
            # varoituksen ja tein sen silti.
            "chance_next": p.get("chance_next"),
            "news": p.get("news"),
            "components": p.get("components"),
            "components_gw": p.get("components_gw"),
            # 6.8 compare-V2: xG/xA-raakastatit tulevat last_season-lohkosta ja
            # sen ON kuljettava poolin mukana — pool muotoilee rivin uusiksi,
            # joten kenttä joka ei ole tässä listassa katoaa äänettömästi.
            "last_season": p.get("last_season"),
            # Addendum 2: projektiohetken FPL-status (serve-time-portin
            # vertailukohta). Vanha projektio ilman kenttaa -> None -> portti
            # kohtelee sita "a":na (sama kayttaytyminen kuin ennen).
            "status": p.get("status"),
        })
    return pool


# ---------------------------------------------------------------------------
# Serve-time availability -portti (EDGE-sprint addendum 2, 25.7)
# ---------------------------------------------------------------------------
# Projektio rakennetaan ~3 h valein; FPL:n saatavuuslippu voi vaihtua milloin
# vain (Garner-tyyppinen "Groin injury" tunti ennen deadlinea). Portti vertaa
# ELAVAA bootstrap-statusta (jo haettu build_context()issa, 10 min TTL-cache ->
# EI yhtaan uutta HTTP-kutsua) projektiohetken statukseen: jos pelaaja on nyt
# sivussa eika projektio tienyt sita viela, han putoaa suosituksista heti.
# Palautetut rivit kertovat vastauksen metassa REHELLISESTI kuka putosi ja miksi.
LIVE_OUT_STATUSES = frozenset({"i", "s", "u", "n"})

AVAILABILITY_GATE_NOTE = (
    "Serve-time availability check: players flagged unavailable on the live "
    "FPL bootstrap (status i/s/u/n) after this projection was built are "
    "dropped from the lists below. The projection itself is unchanged.")


def availability_changes(pool: list[dict],
                         bootstrap: dict | None = None) -> dict[int, dict]:
    """{player_id: muutosrivi} niille poolin pelaajille jotka ovat ELAVASSA
    bootstrapissa sivussa (i/s/u/n) mutta EIVAT olleet sita projektiohetkella.

    Ei koskaan nosta poikkeusta: bootstrapin puuttuessa (testit, FPL alhaalla)
    palautetaan tyhja dict -> vastaus on tasmalleen kuten ennen."""
    try:
        boot = bootstrap if bootstrap is not None else get_bootstrap()
    except Exception:
        return {}
    elements = (boot or {}).get("elements") or []
    if not elements:
        return {}
    live = {e.get("id"): e for e in elements}
    out: dict[int, dict] = {}
    for p in pool:
        e = live.get(p.get("id"))
        if not e:
            continue
        live_status = e.get("status") or "a"
        was = p.get("status") or "a"
        if live_status in LIVE_OUT_STATUSES and was not in LIVE_OUT_STATUSES:
            out[p["id"]] = {
                "id": p["id"], "web_name": p.get("web_name"),
                "team_short": p.get("team_short"),
                "status": live_status,
                "news": (e.get("news") or "").strip()[:140],
                "chance_next": e.get("chance_of_playing_next_round"),
                "projection_status": was,
            }
    return out


def apply_availability_gate(pool: list[dict], bootstrap: dict | None = None
                            ) -> tuple[list[dict], list[dict]]:
    """(suodatettu pooli, pudotetut rivit). Kevyt: yksi dict-lookup per pelaaja."""
    changes = availability_changes(pool, bootstrap)
    if not changes:
        return pool, []
    return ([p for p in pool if p["id"] not in changes],
            sorted(changes.values(), key=lambda r: (r["web_name"] or "")))


def build_context() -> tuple[dict, dict, list[dict], dict[int, dict]]:
    """#35: jaettu konteksti rate-teamille + planner-suitelle:
    (xp_data, bootstrap, pool, pool_by_id). Nostaa 503:n jos projektio puuttuu."""
    xp_data = load_xp()
    if not xp_data.get("meta", {}).get("available") or not xp_data.get("players"):
        raise RateTeamError(503, "xP projections are not available yet.")
    bootstrap = get_bootstrap()
    price_by_id = {e["id"]: e for e in bootstrap.get("elements") or []}
    pool = _projection_pool(xp_data, price_by_id)
    return xp_data, bootstrap, pool, {p["id"]: p for p in pool}


def resolve_squad(bootstrap: dict, entry: int | None, gw: int | None,
                  players: list[int] | None, captain: int | None,
                  bank: float | None) -> tuple[list[int], int | None, int, int]:
    """#35: jaettu joukkueresoluutio → (squad_ids, captain_id, bank_tenths,
    picks_gw). entry-moodi hakee picksit; manual-moodi validoi 15 ID:tä."""
    bank_tenths = int(round((bank or 0.0) * 10))
    if players:
        if len(players) != 15:
            raise RateTeamError(400, "players must list exactly 15 FPL element IDs.")
        if len(set(players)) != 15:
            raise RateTeamError(400, "players contains duplicate IDs.")
        # Draft-rehellisyys (23.7): manual-moodi on esikausidraftin polku, joten
        # runko validoidaan FPL:n draft-sääntöihin — muuten ylikallis runko
        # saisi "100 % of the best budget team" -arvion jota ei voi omistaa.
        # Hinnat + positiot bootstrapista (kattaa KAIKKI pelaajat, myös ilman
        # xP-projektiota olevat). Entry-moodissa validointia EI tehdä: oikean
        # joukkueen arvo saa ylittää 100.0m (team value kasvaa kaudella).
        elements = {e["id"]: e for e in (bootstrap.get("elements") or [])}
        unknown = [pid for pid in players if pid not in elements]
        if unknown:
            raise RateTeamError(
                400, f"Unknown player IDs: {unknown}. Use FPL element IDs "
                     "from the current season.")
        pos_need = {1: 2, 2: 5, 3: 5, 4: 3}
        pos_have: dict[int, int] = {1: 0, 2: 0, 3: 0, 4: 0}
        for pid in players:
            et = elements[pid].get("element_type")
            if et in pos_have:
                pos_have[et] += 1
        if pos_have != pos_need:
            raise RateTeamError(
                400, "A draft needs 2 GK, 5 DEF, 5 MID and 3 FWD. This one "
                     f"has {pos_have[1]} GK, {pos_have[2]} DEF, "
                     f"{pos_have[3]} MID, {pos_have[4]} FWD.")
        cost_tenths = sum(int(elements[pid].get("now_cost") or 0)
                          for pid in players)
        if cost_tenths > 1000:
            raise RateTeamError(
                400, f"This draft costs {cost_tenths / 10:.1f}m, over the "
                     "100.0m budget. Swap something pricey for a cheaper "
                     "pick and try again.")
        # Manual-draftin bank = budjetin jäännös (informatiivinen).
        if bank is None:
            bank_tenths = 1000 - cost_tenths
        return list(players), captain, bank_tenths, _resolve_gw(bootstrap, gw)
    if entry is None:
        raise RateTeamError(400, "Provide either entry or players.")
    picks_gw = _resolve_gw(bootstrap, gw)
    picks_data = get_entry_picks(entry, picks_gw)
    picks = picks_data.get("picks") or []
    if not picks:
        raise RateTeamError(404, f"Entry {entry} has no picks for GW{picks_gw}.")
    squad_ids = [pk["element"] for pk in picks]
    cap = [pk["element"] for pk in picks if pk.get("is_captain")]
    captain_id = captain or (cap[0] if cap else None)
    if bank is None:
        bank_tenths = int((picks_data.get("entry_history") or {}).get("bank") or 0)
    return squad_ids, captain_id, bank_tenths, picks_gw


def clamp_gw_to_projections(target_gw: int, pool: list[dict],
                            xp_data: dict) -> int:
    """Esikausiclamppi: jos GW ei ole projektioiden kattama, käytä projektioiden
    seuraavaa GW:tä (meta.next_gameweek, fallback pienin katettu)."""
    covered = {g.get("gw") for p in pool for g in (p.get("gameweeks") or [])}
    if target_gw in covered:
        return target_gw
    return (xp_data["meta"].get("next_gameweek")
            or (min(covered) if covered else target_gw))


def rate_team(entry: int | None = None, gw: int | None = None,
              players: list[int] | None = None, captain: int | None = None,
              bank: float | None = None, ft: int = 1) -> dict:
    """Arvioi joukkue. entry-moodi (julkinen FPL-ID) TAI manual-moodi
    (players = 15 element-ID:tä, esikausifallback). ft = vapaat siirrot
    (#63: 0 → hold_verdict laskee -4 hitin siirron nettoon)."""
    if not 0 <= ft <= 5:
        raise RateTeamError(400, "ft must be between 0 and 5.")
    xp_data, bootstrap, pool, pool_by_id = build_context()
    mode = "manual" if players else "entry"
    missing: list[int] = []
    squad_ids, captain_id, bank_tenths, picks_gw = resolve_squad(
        bootstrap, entry, gw, players, captain, bank)

    # Esikausiclamppi: picks voi tulla viime kauden GW:stä (esim. GW38), mutta
    # projektiot kattavat tulevan horisontin (GW1–6) → xP-laskennan GW on aina
    # projektioiden kattama. picks_gw raportoidaan erikseen metassa.
    target_gw = clamp_gw_to_projections(picks_gw, pool, xp_data)

    squad: list[dict] = []
    for pid in squad_ids:
        p = pool_by_id.get(pid)
        if p:
            squad.append(p)
        else:
            missing.append(pid)
    if len(squad) < 11:
        raise RateTeamError(
            422, "Too few of the squad's players have xP projections "
                 f"({len(squad)}/15 matched). Check the player IDs.")

    xi = optimal_xi(squad) if len(squad) >= 11 else squad
    xi_ids = {p["id"] for p in xi}

    # Kapteeni: annettu/picksistä jos XI:ssä, muuten paras GW-xP
    cap_sugg = captain_suggestion(xi, target_gw)
    effective_captain = (captain_id if captain_id in xi_ids
                         else cap_sugg["pick"]["id"])
    cap_player = pool_by_id[effective_captain]

    team_xp_horizon = sum(p["xp_horizon_total"] for p in xi)
    team_xp_gw = sum(_gw_xp(p, target_gw) for p in xi)
    # Kapteeni tuplaa pisteensä (promptin vaatimus: huomioitu molemmissa)
    team_xp_horizon_c = team_xp_horizon + cap_player["xp_horizon_total"]
    team_xp_gw_c = team_xp_gw + _gw_xp(cap_player, target_gw)

    # #50: rating = vertailu PARHAASEEN mahdolliseen budjettijoukkueeseen
    # (satunnaisotos antoi kaikille ~100 % = ontto). percentile-kenttä säilyy
    # yhteensopivuuden takia mutta tarkoittaa "% of the best possible budget
    # team".
    #
    # 26.7: rating = sama luku kokonaislukuna 0-100 (luettavampi otsikkoluku
    # kuin desimaalinen prosentti). beats_benchmark kertoo jos joukkue YLITTÄÄ
    # benchmarkin: aiemmin se leikattiin hiljaa sataan, jolloin tieto katosi ja
    # luku näytti ontolta imartelulta. Nyt se on eksplisiittinen ja ansaittu.
    cache_key = str(xp_data["meta"].get("generated_at"))
    optimal_xp = optimal_budget_team_xp(pool, cache_key)
    raw_pct = (100.0 * team_xp_horizon / optimal_xp) if optimal_xp > 0 else 0.0
    pct_of_optimal = round(min(100.0, raw_pct), 1)
    rating = int(round(min(100.0, raw_pct)))
    beats_benchmark = raw_pct > 100.0
    gap_to_optimal = round(max(0.0, optimal_xp - team_xp_horizon), 2)
    strongest, weakest = _line_strength(xi, pool)

    transfers = transfer_suggestions(squad, pool, bank_tenths)
    # #63: hero-verdikti — paras yksittäinen siirto hitin jälkeen vs kynnys
    best_gain = (transfers["suggestions"][0]["delta_xp_horizon"]
                 if transfers["suggestions"] else None)
    transfers["hold_verdict"] = build_hold_verdict(
        best_gain, int(xp_data["meta"].get("horizon_gw") or 6), ft)

    return {
        "meta": {
            "mode": mode,
            "entry": entry,
            "gw": target_gw,
            "picks_gw": picks_gw if mode == "entry" else None,
            "season": xp_data["meta"].get("season"),
            "generated_at": xp_data["meta"].get("generated_at"),
            "horizon_gw": xp_data["meta"].get("horizon_gw"),
            "rating_method": "vs_optimal_budget_team",
            # 26.7: projektioiden osuvuus mukaan vastaukseen, jotta rating on
            # falsifioituva eika vain sisaisesti johdonmukainen. Lahde on
            # committoitu tiiviste walk-forward-backtestista (koko 25/26).
            "projection_accuracy": _load_xp_accuracy(),
            "note": ("GoalIQ model projections, not FPL official expected "
                     "points. For fun and planning, not betting advice."),
        },
        "team": {
            "players": [{
                "id": p["id"], "web_name": p["web_name"],
                "team_short": p["team_short"],
                "pos": POS_NAME[p["element_type"]],
                "price": p["price"] / 10.0,
                "xp_per_gw": round(p["xp_per_gw"], 2),
                "xp_horizon_total": round(p["xp_horizon_total"], 2),
                # #122/#123: per-GW-xP + vastustajat manageriin — summary ja
                # manageri laskevat samasta GW-kohtaisesta luvusta (ei enää
                # keskiarvo-vs-GW1-ristiriitaa), ja GW-valitsin saa datansa.
                "gameweeks": _player_gameweeks(p),
                "in_xi": p["id"] in xi_ids,
                "is_captain": p["id"] == effective_captain,
                # 15.8: saatavuus kentalle asti. Luvut olivat projektiossa jo,
                # mutta ne EIVAT kulkeneet manageriin, joten kentalla epavarma
                # pelaaja nayttti tasan samalta kuin terve. Se on se tieto
                # jonka takia kayttaja avaa naytön deadlinen alla.
                # None = FPL ei ole liputtanut, ei "100 % varma".
                "chance_next": p.get("chance_next"),
                "news": (p.get("news") or "").strip()[:120] or None,
            } for p in squad],
            "missing_ids": missing,
            "bank": round(bank_tenths / 10.0, 1),
        },
        "rating": {
            "team_xp_gw": round(team_xp_gw_c, 2),
            "team_xp_horizon": round(team_xp_horizon_c, 2),
            "team_xp_horizon_no_captain": round(team_xp_horizon, 2),
            "percentile": pct_of_optimal,
            "rating": rating,
            "rating_max": 100,
            "beats_benchmark": beats_benchmark,
            # 28.7: onko vertailukohta TODISTETUSTI paras mahdollinen. Copy saa
            # sanoa "best possible" vain kun tama on True. Ennen tata paivaa
            # vertailukohta oli ahne heuristiikka joka jai tuotantodatalla
            # 15.2 xP optimista, ja copy vaitti silti parasta mahdollista.
            "optimal_proven": optimal_xi_proven(),
            "optimal_team_xp": round(optimal_xp, 2),
            "gap_to_optimal_xp": gap_to_optimal,
            "strongest_line": strongest,
            "weakest_line": weakest,
        },
        "captain": cap_sugg,
        "transfers": transfers,
    }
