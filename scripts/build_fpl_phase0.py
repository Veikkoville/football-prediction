"""
FPL Phase 0 — tuotanto-builderi: clean sheet -% + mallipohjainen FDR → staattinen JSON.

Tuottaa `data/fpl_projections_phase0.json`:n jonka `/api/fantasy` tarjoilee
(EI on-request-laskentaa — Render 0.5 vCPU -budjettisääntö, FPL-speksi luku 2).
Ajo: ajastettu refresh-job (scripts/fpl_phase0_refresh.ps1, Task Scheduler
"GoalIQ-FPL-Phase0-refresh") tai käsin `python -m scripts.build_fpl_phase0`.

Lähteet (fixturet + joukkueet), prioriteettijärjestys:
  1. FPL:n virallinen API (fantasy.premierleague.com/api/) — ENSISIJAINEN heti
     kun se tarjoilee 2026/27-kautta. Antaa myös GW-deadlinet + short-nimet.
  2. premierleague.com (pulselive) compSeason 841 = 2026/27 — FALLBACK niin
     kauan kuin FPL-API tarjoilee päättynyttä 25/26-kautta ("later this
     summer" -avaus). TODO-lippu kirjataan meta.todo:hon kun fallback aktiivinen.

Joukkuevoimat: GoalIQ:n OLEMASSA OLEVA Dixon-Coles -ottelumalli (Understat PL,
config.current_season_pair()), sama fit-config kuin tuotannon /api/predict
(_saa_malli-defaultit). Tämä skripti vain LUKEE mallia — ei muuta fit-koodia,
domestic-malli pysyy bittitarkasti koskemattomana.

Metodologia:
  - CS-% = P(vastustaja tekee 0) DC-score-matriisista (tau-korjattu) —
    sama matriisi josta tuotannon 1X2/BTTS lasketaan (m[:,0]/m[0,:]-summat).
  - Mallipohjainen FDR (1-5) = 0.55*rank(1-voitto%) + 0.45*rank(odotetut
    päästetyt), kvintiilibucket koko kauden joukkue-fixtureiden yli.

Sanity-gate (fail-safe kuten WC-refresh G2): jos kärki/nousija-separaatio ei
täyty → JSONia EI kirjoiteta, exit 2. Exit 0 = ok, 1 = tekninen virhe.

EI auto-pushia: onnistuneen ajon lopuksi tulostetaan git-komennot Villelle
(sama konventio kuin scripts/wc_daily_refresh.py).
"""

from __future__ import annotations

import datetime as _dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import requests

import config
from src.data.loader import lataa_otteludata
from src.models.dixon_coles import DixonColesModel

# ---------------------------------------------------------------------------
# 1. Asetukset
# ---------------------------------------------------------------------------
FPL_BASE = "https://fantasy.premierleague.com/api"
FPL_HEADERS = {"User-Agent": "Mozilla/5.0 (GoalIQ refresh job)"}
PULSE_HEADERS = {"User-Agent": "Mozilla/5.0", "Origin": "https://www.premierleague.com"}
COMPSEASON_2627 = 841  # premierleague.com -kausi-id 2026/27
SEASON_LABEL = "2026/27"
OUT_PATH = config.PROJECT_ROOT / "data" / "fpl_projections_phase0.json"

# Tuotannon /api/predict -fit-parametrit (_saa_malli-defaultit) — pidä synkassa.
FIT_DECAY = 0.0035
FIT_BAYES = 2.0

# Kuinka monta tulevaa GW:tä outputtiin (per-joukkue-lista + ticker + aggregaatit).
HORIZON_GW = 6

# --------------------------------------------------------------------------
# 27.7 HORISONTTILAAJENNUS (kontrakti:
# goaliq-app/cos-reports/horizon-extension-contract-2026-07-27.md)
#
# Malli laskee CS%:n ja FDR:n JO NYT koko kaudelle: fetch_fixtures() hakee
# Pulselivesta kaikki kauden ottelut ja add_fdr muodostaa kvintiilibucketit
# 760 joukkue-fixturen yli. HORIZON_GW=6 oli pelkka ULOSTULON katkaisu.
# Emitoidaan nyt kaikki jaljella olevat GW:t; endpoint rajaa pyynnossa.
#
# KAKSITASOINEN REHELLISYYS:
#   near (gw <= next_gw + NEAR_HORIZON_GW - 1): cs_pct mukana, taysi paino
#   far  (siita eteenpain):                     EI cs_pct LAINKAAN, vain FDR
#
# cs_pct jatetaan pois RAKENTEESSA eika konventiolla: GW30:n CS-% laskettuna
# heinakuussa perustuu heinakuun joukkuearvioihin ja on maaliskuussa vaara.
# Jos kentta lahetetaan, joku renderoi sen ennen pitkaa. FDR jaa, koska se on
# 1-5 bucket eli jo valmiiksi karkea eika lupaa desimaalitarkkuutta.
#
# HUOM next_avg_cs_pct / next_avg_fdr / next_n PYSYVAT LAHIHORISONTISSA.
# Kaksi syyta: (1) taaksepain-yhteensopivuus, kentat tarkoittavat samaa kuin
# ennen; (2) sanity_gate nojaa naihin ja sen kynnykset (kärki FDR <= 3.2,
# nousijat >= 3.5, marginit) on kalibroitu 6 GW:n ikkunalle — koko kauden
# keskiarvot regressoituisivat keskelle ja portti mittaisi vaaraa asiaa
# HILJAA. Ala "yksinkertaista" naita koko kauden keskiarvoiksi.
# --------------------------------------------------------------------------
NEAR_HORIZON_GW = 6

# 28.7: em dash pois (projektin copy-saanto) JA loppupiste lisatty. Ilman
# pistetta fpl.html liitti taman perään "Lower is easier." ilman valimerkkia
# -> julkaistulla sivulla luki "...moves closer Lower is easier."
# Tama merkkijono valuu YHDESTA lahteesta neljalle pinnalle (fpl.html, SPA,
# mobiili, API-meta), joten se korjataan tasta eika pinnoilta.
FAR_BASIS_LABEL = (
    "Fixture difficulty only, based on today's ratings. "
    "Clean sheet % appears as each gameweek moves closer."
)

# Lähdenimi (pulselive-pitkä TAI FPL-lyhyt) -> mallin (Understat) nimi.
NAME_MAP = {
    # pulselive (premierleague.com)
    "Brighton & Hove Albion": "Brighton",
    "Tottenham Hotspur": "Tottenham",
    "Leeds United": "Leeds",
    "Ipswich Town": "Ipswich",
    "Coventry City": "Coventry",
    "Hull City": "Hull",
    "Leicester City": "Leicester",
    "Luton Town": "Luton",
    "Norwich City": "Norwich",
    "Sheffield United": "Sheffield United",
    "West Ham United": "West Ham",
    "West Bromwich Albion": "West Bromwich Albion",
    # FPL-API (bootstrap-static team.name)
    "Man City": "Manchester City",
    "Man Utd": "Manchester United",
    "Spurs": "Tottenham",
    "Nott'm Forest": "Nottingham Forest",
    "Newcastle": "Newcastle United",
    "Wolves": "Wolverhampton Wanderers",
    "Sheffield Utd": "Sheffield United",
}

# Mallinimi -> 3-kirjaiminen koodi (tekstipohjainen, EI seurakrestejä — 5.2.1-oppi).
SHORT_MAP = {
    "Arsenal": "ARS", "Aston Villa": "AVL", "Bournemouth": "BOU",
    "Brentford": "BRE", "Brighton": "BHA", "Burnley": "BUR",
    "Chelsea": "CHE", "Coventry": "COV", "Crystal Palace": "CRY",
    "Everton": "EVE", "Fulham": "FUL", "Hull": "HUL", "Ipswich": "IPS",
    "Leeds": "LEE", "Leicester": "LEI", "Liverpool": "LIV", "Luton": "LUT",
    "Manchester City": "MCI", "Manchester United": "MUN",
    "Newcastle United": "NEW", "Norwich": "NOR", "Nottingham Forest": "NFO",
    "Sheffield United": "SHU", "Southampton": "SOU", "Sunderland": "SUN",
    "Tottenham": "TOT", "West Bromwich Albion": "WBA", "West Ham": "WHU",
    "Wolverhampton Wanderers": "WOL",
}


def map_name(source_name: str) -> str:
    return NAME_MAP.get(source_name, source_name)


def short_name(model_name: str) -> str:
    return SHORT_MAP.get(model_name, model_name[:3].upper())


# ---------------------------------------------------------------------------
# 2. Lähdekerros — FPL-API ensisijainen, pulselive-fallback
# ---------------------------------------------------------------------------
def _parse_iso_utc(s: str | None) -> _dt.datetime | None:
    if not s:
        return None
    try:
        return _dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def fetch_fpl_official() -> dict | None:
    """Yritä FPL:n virallista API:a. Palauttaa {fixtures, teams, deadline_utc,
    source_label} jos API tarjoilee tulevaa (26/27) kautta, muuten None.

    26/27-detektio: bootstrap-static/events sisältää vähintään yhden
    EI-finished-GW:n jonka deadline ei ole kaukana menneisyydessä. Päättynyt
    25/26 = kaikki eventit finished → None → fallback.
    """
    try:
        r = requests.get(f"{FPL_BASE}/bootstrap-static/", headers=FPL_HEADERS, timeout=30)
        r.raise_for_status()
        boot = r.json()
    except Exception as e:
        print(f"      FPL-API ei vastannut ({type(e).__name__}) -> fallback")
        return None

    events = boot.get("events", [])
    now = _dt.datetime.now(_dt.timezone.utc)
    upcoming = [
        ev for ev in events
        if not ev.get("finished")
        and (_parse_iso_utc(ev.get("deadline_time")) or now) >= now - _dt.timedelta(days=30)
    ]
    if not upcoming:
        print("      FPL-API tarjoilee yhä päättynyttä kautta (kaikki GW:t finished) -> fallback")
        return None

    teams_by_id = {t["id"]: t for t in boot.get("teams", [])}
    try:
        r = requests.get(f"{FPL_BASE}/fixtures/", headers=FPL_HEADERS, timeout=30)
        r.raise_for_status()
        raw_fixtures = r.json()
    except Exception as e:
        print(f"      FPL-API fixtures epäonnistui ({type(e).__name__}) -> fallback")
        return None

    fixtures = []
    for f in raw_fixtures:
        th, ta = teams_by_id.get(f.get("team_h")), teams_by_id.get(f.get("team_a"))
        if not th or not ta:
            continue
        ko = _parse_iso_utc(f.get("kickoff_time"))
        fixtures.append(
            {
                "gameweek": f.get("event"),
                "kickoff": ko.strftime("%a %d %b %Y, %H:%M UTC") if ko else "TBC",
                "kickoff_ms": int(ko.timestamp() * 1000) if ko else None,
                "finished": bool(f.get("finished")),
                "home": th["name"],
                "away": ta["name"],
            }
        )
    next_deadline = min(
        (d for ev in upcoming if (d := _parse_iso_utc(ev.get("deadline_time"))) and d > now),
        default=None,
    )
    return {
        "fixtures": fixtures,
        "teams": sorted(t["name"] for t in boot.get("teams", [])),
        "deadline_utc": next_deadline.isoformat(timespec="seconds") if next_deadline else None,
        "source": "fpl-api",
        "source_label": "FPL official API (fantasy.premierleague.com)",
    }


def fetch_pulselive() -> dict:
    """Fallback: premierleague.com (pulselive) 2026/27 -fixtuurifeed
    (sama lähde kuin 19.6. pohjatyössä build_fpl_cs_fdr.py)."""
    fixtures: list[dict] = []
    page = 0
    while True:
        url = (
            "https://footballapi.pulselive.com/football/fixtures"
            f"?comps=1&compSeasons={COMPSEASON_2627}"
            f"&page={page}&pageSize=40&sort=asc&statuses=U,L,C"
        )
        r = requests.get(url, headers=PULSE_HEADERS, timeout=30)
        r.raise_for_status()
        d = r.json()
        for f in d.get("content", []):
            teams = f.get("teams", [])
            if len(teams) < 2:
                continue
            gw = f.get("gameweek", {}).get("gameweek")
            ko = f.get("kickoff", {})
            fixtures.append(
                {
                    "gameweek": int(gw) if gw is not None else None,
                    "kickoff": ko.get("label", "TBC"),
                    "kickoff_ms": ko.get("millis"),
                    "finished": f.get("status") == "C",
                    "home": teams[0]["team"]["name"],
                    "away": teams[1]["team"]["name"],
                }
            )
        info = d.get("pageInfo", {})
        if page >= info.get("numPages", 1) - 1:
            break
        page += 1

    r = requests.get(
        f"https://footballapi.pulselive.com/football/compseasons/{COMPSEASON_2627}/teams",
        headers=PULSE_HEADERS,
        timeout=30,
    )
    r.raise_for_status()
    return {
        "fixtures": fixtures,
        "teams": sorted(t["name"] for t in r.json()),
        "deadline_utc": None,  # pulselive ei tunne FPL-deadlineja
        "source": "pulselive-fallback",
        "source_label": f"premierleague.com (pulselive) compSeason {COMPSEASON_2627}",
    }


def fetch_source() -> dict:
    print("[1/5] Haetaan 26/27 fixturet + joukkueet (FPL-API ensisijainen)...")
    src = fetch_fpl_official()
    if src is None:
        src = fetch_pulselive()
    print(f"      lähde={src['source']}: {len(src['fixtures'])} fixturea, {len(src['teams'])} joukkuetta")
    return src


# ---------------------------------------------------------------------------
# 3. Sovita PL-malli (sama config kuin tuotanto) + promoted baseline
# ---------------------------------------------------------------------------
def fit_model() -> tuple[DixonColesModel, list[str]]:
    seasons = config.current_season_pair()
    df = lataa_otteludata(["ENG-Premier League"], seasons)
    if df.empty:
        raise SystemExit("PL-otteludata tyhjä — ei voi sovittaa mallia.")
    dc = DixonColesModel(per_team_home_adv=True).fit(
        df,
        home_team_col="home_team",
        away_team_col="away_team",
        home_goals_col="home_score",
        away_goals_col="away_score",
        decay=FIT_DECAY,
        date_col="date",
        l2_attack_defence=FIT_BAYES,
        # 17.8: sama xG-painotus kuin /api/predict. Talla rivilla on merkitysta:
        # alempana luvataan tekstissa "sama fit-config kuin /api/predict", ja
        # jos xG kytkettaisiin vain toiseen, sama ottelu saisi kaksi eri lukua.
        home_xg_col=config.DIXON_COLES_XG_COLS[0],
        away_xg_col=config.DIXON_COLES_XG_COLS[1],
        xg_weight=config.DIXON_COLES_XG_WEIGHT,
    )
    return dc, seasons


# 27.7: siirretty jaettuun moduuliin src/models/promoted_baseline.py.
#
# Sama logiikka oli KOPIOITUNA tässä ja build_fpl_cs_fdr.py:ssä, eikä
# /api/predict käyttänyt sitä lainkaan — siksi ennuste palautti 404:n
# Coventrylle vaikka CS%/FDR tunsi sen. Yksi lähde = pinnat eivät voi ajautua
# erilleen nousijoiden voimasta.
from src.models.promoted_baseline import add_promoted_baseline  # noqa: E402


# ---------------------------------------------------------------------------
# 4. Laske per-fixture CS% + win% + xG + FDR
# ---------------------------------------------------------------------------
def compute_fixtures(dc: DixonColesModel, fixtures: list[dict],
                     ctx_cfg: dict | None = None) -> list[dict]:
    """CS-% luetaan DC-score-matriisista (tau-korjattu): koti-CS = P(vieras 0)
    = m[:,0].sum() — sama matriisi josta tuotannon 1X2/BTTS lasketaan.

    ctx_cfg (Phase 1b, src/models/fpl_context.py): nousija-koti-avaus-buusti +
    manuaaliset yliajot sovelletaan DC:n adjustments-mekanismilla ennen
    matriisia. None = raaka DC (alkuperäinen Phase 0 -käyttäytyminen)."""
    from src.models.fpl_context import fixture_adjustments

    rows = []
    for f in fixtures:
        h = map_name(f["home"])
        a = map_name(f["away"])
        if h not in dc.attack or a not in dc.attack:
            continue  # ei pitäisi tapahtua (baseline lisätty) — ohita turvallisesti
        adj, _ = fixture_adjustments(h, a, f.get("gameweek"), ctx_cfg)
        lam, mu = dc.expected_goals(h, a, adjustments=adj)  # lam=koti, mu=vieras
        m = dc.score_matrix(h, a, adjustments=adj)
        cs_home = float(m[:, 0].sum())  # vieras tekee 0
        cs_away = float(m[0, :].sum())  # koti tekee 0
        p_home = float(np.tril(m, -1).sum())
        p_draw = float(np.trace(m))
        p_away = float(np.triu(m, 1).sum())
        rows.append(
            {
                "gameweek": f["gameweek"],
                "kickoff": f["kickoff"],
                "kickoff_ms": f["kickoff_ms"],
                "finished": f.get("finished", False),
                "home": h,
                "away": a,
                "home_short": short_name(h),
                "away_short": short_name(a),
                "xg_home": round(lam, 3),
                "xg_away": round(mu, 3),
                "p_home_win": round(p_home, 4),
                "p_draw": round(p_draw, 4),
                "p_away_win": round(p_away, 4),
                "cs_home_pct": round(cs_home * 100, 1),
                "cs_away_pct": round(cs_away * 100, 1),
            }
        )
    return rows


def add_fdr(rows: list[dict]) -> None:
    """Mallipohjainen FDR (1-5) per joukkue/fixture. Difficulty = rank-keskiarvo
    (1 - voitto-%) ja (odotetut päästetyt maalit), kvintiilibucket koko kauden
    joukkue-fixtureiden yli. 1 = helpoin, 5 = vaikein.

    EDGE-sprint: sama fdr emittoidaan myös nimellä def_fdr_{side} (sovittu
    kontrakti — nykyinen FDR on CS/puolustussuuntainen), ja lisäksi
    att_fdr_{side} = HYÖKKÄYSSUUNNAN vaikeus: oma odotettu xG tässä
    fixturessa rank-normalisoituna (käännetty: vähän omaa xG:tä = vaikea),
    kvintiilibucket samaan 1-5-skaalaan. Johdettu puhtaasti jo lasketuista
    xg_home/xg_away-arvoista — ei uutta mallia."""
    persp = []  # (row_idx, side, p_win, xGC, xGF)
    for i, r in enumerate(rows):
        persp.append((i, "home", r["p_home_win"], r["xg_away"], r["xg_home"]))
        persp.append((i, "away", r["p_away_win"], r["xg_home"], r["xg_away"]))
    n = len(persp)
    if n == 0:
        return
    lose = np.array([1.0 - p[2] for p in persp])  # korkea = vaikeampi
    xgc = np.array([p[3] for p in persp])
    xgf = np.array([p[4] for p in persp])         # oma odotettu maalimäärä

    def pct_rank(x):
        order = x.argsort()
        ranks = np.empty(n, dtype=float)
        ranks[order] = np.arange(n)
        return ranks / max(n - 1, 1)

    diff = 0.55 * pct_rank(lose) + 0.45 * pct_rank(xgc)
    qs = np.quantile(diff, [0.2, 0.4, 0.6, 0.8])
    fdr = np.searchsorted(qs, diff, side="right") + 1  # 1..5
    att_diff = pct_rank(-xgf)                          # korkea = vaikea hyökätä
    qs_att = np.quantile(att_diff, [0.2, 0.4, 0.6, 0.8])
    att_fdr = np.searchsorted(qs_att, att_diff, side="right") + 1  # 1..5
    for (i, side, _p, _x, _g), d, ad in zip(persp, fdr, att_fdr):
        rows[i][f"fdr_{side}"] = int(d)
        rows[i][f"def_fdr_{side}"] = int(d)   # alias (kontrakti)
        rows[i][f"att_fdr_{side}"] = int(ad)


# ---------------------------------------------------------------------------
# 5. Horisontti + per-joukkue-näkymä
# ---------------------------------------------------------------------------
def next_gameweek(rows: list[dict]) -> int | None:
    """Seuraava GW = pienin GW jolla on pelaamaton fixture."""
    gws = [r["gameweek"] for r in rows if r["gameweek"] and not r["finished"]]
    return min(gws) if gws else None


def build_team_view(
    rows: list[dict], next_gw: int, near_horizon_gw: int = NEAR_HORIZON_GW
) -> list[dict]:
    """Per-joukkue: KAIKKI jäljellä olevat fixturet (vastustaja, H/A, FDR) +
    lähihorisontin keskiarvot. Lajiteltu next_avg_cs_pct desc (appin oletusnäkymä).

    27.7: gw_cut poistettu — emitoidaan koko kausi ja merkitään jokainen rivi
    tierillä. Endpoint rajaa pyynnössä (?horizon=). Kaukorivit EIVÄT saa
    cs_pct-kenttää lainkaan; ks. NEAR_HORIZON_GW-lohkon perustelu.
    """
    near_cut = next_gw + near_horizon_gw - 1
    teams: dict[str, dict] = {}
    for r in rows:
        gw = r["gameweek"]
        if not gw or gw < next_gw or r["finished"]:
            continue
        near = gw <= near_cut
        for side, opp_side in (("home", "away"), ("away", "home")):
            team = r[side]
            entry = teams.setdefault(
                team,
                {"name": team, "short": short_name(team), "fixtures": []},
            )
            fx = {
                "gw": gw,
                "opponent": r[opp_side],
                "opponent_short": r[f"{opp_side}_short"],
                "venue": "H" if side == "home" else "A",
                "kickoff_ms": r["kickoff_ms"],
                "fdr": r[f"fdr_{side}"],
                # EDGE: def_fdr = alias nykyiselle CS-pohjaiselle FDR:lle,
                # att_fdr = hyökkäyssuunnan vaikeus (ks. add_fdr).
                "def_fdr": r[f"fdr_{side}"],
                "att_fdr": r[f"att_fdr_{side}"],
                "tier": "near" if near else "far",
            }
            # cs_pct VAIN lähihorisontissa. Kentän puuttuminen on kontrakti,
            # ei unohdus — kaukoviikon CS-% olisi tarkkuuslupaus jota malli ei
            # voi pitää. tier on eksplisiittinen, jottei klientin tarvitse
            # laskea samaa sääntöä uudelleen gw-vertailusta.
            if near:
                fx["cs_pct"] = r[f"cs_{side}_pct"]
            entry["fixtures"].append(fx)
    out = []
    for entry in teams.values():
        entry["fixtures"].sort(key=lambda x: (x["gw"], x["kickoff_ms"] or 0))
        near_fx = [f for f in entry["fixtures"] if f["tier"] == "near"]
        # Keskiarvot LÄHIHORISONTISTA (taaksepäin-yhteensopivuus + sanity_gaten
        # kalibrointi). Tyhjä near-ikkuna on mahdollinen vain kauden lopussa.
        cs = [f["cs_pct"] for f in near_fx]
        fdr = [f["fdr"] for f in near_fx]
        entry["next_avg_cs_pct"] = round(float(np.mean(cs)), 1) if cs else 0.0
        entry["next_avg_fdr"] = round(float(np.mean(fdr)), 2) if fdr else 0.0
        entry["next_n"] = len(cs)
        out.append(entry)
    out.sort(key=lambda t: (-t["next_avg_cs_pct"], t["name"]))
    return out


# ---------------------------------------------------------------------------
# 6. Sanity-gate (fail-safe: FAIL -> ei kirjoiteta, exit 2)
# ---------------------------------------------------------------------------
def _horizon_span(team_view: list[dict]) -> int:
    """Montako GW:tä team_view kattaa (viimeisin GW - ensimmäinen + 1).

    Lasketaan datasta eikä vakiosta: kauden lopussa jäljellä on vähemmän kuin
    38, ja väärä luku metassa saisi klientin varaamaan tilaa peliviikoille
    joita ei ole.
    """
    gws = [f["gw"] for t in team_view for f in t["fixtures"]]
    return (max(gws) - min(gws) + 1) if gws else 0


def sanity_gate(team_view: list[dict], promoted: list[str]) -> bool:
    print("\n" + "=" * 64)
    print("SANITY-GATE  (suunta-/separaatiotesti, ei absoluuttiset kynnykset)")
    print("=" * 64)
    agg = {t["name"]: t for t in team_view}
    strong = [t for t in ("Manchester City", "Arsenal", "Liverpool") if t in agg]
    weak = [t for t in promoted if t in agg]

    for t in strong + weak:
        a = agg[t]
        tag = "promoted" if t in weak else "kärki"
        print(f"    {t:20s} fdr={a['next_avg_fdr']:.2f}  cs={a['next_avg_cs_pct']:.1f}%  ({tag})")

    ok = True
    checks: list[tuple[str, bool]] = []
    if not strong:
        checks.append(("kärkijoukkueet löytyvät aggregaateista", False))
    else:
        checks.append(("jokainen kärkijoukkue FDR <= 3.2",
                       all(agg[t]["next_avg_fdr"] <= 3.2 for t in strong)))
    if weak:
        s_fdr = float(np.mean([agg[t]["next_avg_fdr"] for t in strong])) if strong else 5.0
        s_cs = float(np.mean([agg[t]["next_avg_cs_pct"] for t in strong])) if strong else 0.0
        w_fdr = float(np.mean([agg[t]["next_avg_fdr"] for t in weak]))
        w_cs = float(np.mean([agg[t]["next_avg_cs_pct"] for t in weak]))
        checks.append(("kärki avg FDR < nousijat avg FDR (margin >=1.0)", w_fdr - s_fdr >= 1.0))
        checks.append(("kärki avg CS% > nousijat avg CS% (margin >=8pp)", s_cs - w_cs >= 8.0))
        checks.append(("jokainen nousija FDR >= 3.5",
                       all(agg[t]["next_avg_fdr"] >= 3.5 for t in weak)))
    for label, passed in checks:
        print(f"  [{'OK ' if passed else 'FAIL'}] {label}")
        ok = ok and passed
    print(f"\nGATE: {'PASS' if ok else 'FAIL'}")
    return ok


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main() -> int:
    src = fetch_source()

    print("[2/5] Sovitetaan PL Dixon-Coles -malli (Understat)...")
    dc, seasons = fit_model()
    print(f"      {len(dc.teams_)} joukkuetta mallissa (kaudet {seasons})")

    missing = sorted({map_name(t) for t in src["teams"]} - set(dc.attack))
    print(f"[3/5] Nousijat ilman tuoretta ylätason dataa: {missing}")
    baseline = add_promoted_baseline(dc, missing)
    print(f"      promoted baseline: {baseline}")

    # 14.8: JOUKKUETASON VOIMAOHITUS — sama lahde kuin xP-builderilla.
    # Ilman tata rivia tama pinta nayttaisi samasta seurasta eri luvun kuin
    # xP, ja kayttaja nakee molemmat samassa tuotteessa. Sijainti on sama
    # kaikilla kolmella: promoted baselinen JALKEEN, laskennan EDELLA.
    from src.models.fpl_team_overrides import apply_to_fit
    apply_to_fit(dc, "phase0")

    print("[4/5] Lasketaan CS% + win% + FDR per fixture (Phase 1b -konteksti)...")
    # Phase 1b -kontekstikerros (sama kuin xP-builderissa): nousijat =
    # fixture-joukkueet − edellisen PL-kauden joukkueet; koti-avaus-buusti +
    # manuaaliset yliajot data/fpl_manual_overrides.csv:stä.
    from src.data.loader import lataa_otteludata as _lataa
    from src.models.fpl_context import build_context, load_overrides, promoted_teams

    y = int(SEASON_LABEL[:4])
    prev_key = f"{(y - 1) % 100:02d}{y % 100:02d}"
    prev_matches = _lataa(["ENG-Premier League"], [prev_key])
    fixture_team_names = {map_name(t) for t in src["teams"]}
    promoted = promoted_teams(fixture_team_names, set(prev_matches["home_team"]))
    model_fixtures = [{"gameweek": f["gameweek"], "home": map_name(f["home"]),
                       "away": map_name(f["away"])}
                      for f in src["fixtures"] if f["gameweek"]]
    ctx_cfg = build_context(promoted, model_fixtures, load_overrides())
    print(f"      nousijat: {sorted(promoted)}, yliajoja: {len(ctx_cfg['overrides'])}")

    rows = compute_fixtures(dc, src["fixtures"], ctx_cfg=ctx_cfg)
    add_fdr(rows)
    next_gw = next_gameweek(rows)
    if next_gw is None:
        print("VIRHE: ei yhtään pelaamatonta fixturea — ei kirjoiteta.")
        return 1
    team_view = build_team_view(rows, next_gw)
    ticker = [
        r for r in rows
        if r["gameweek"] and next_gw <= r["gameweek"] <= next_gw + HORIZON_GW - 1
        and not r["finished"]
    ]

    if not sanity_gate(team_view, missing):
        print("SANITY-GATE FAIL — data/fpl_projections_phase0.json EI kirjoitettu.")
        return 2

    print("\n[5/5] Kirjoitetaan JSON...")
    todo = []
    if src["source"] != "fpl-api":
        todo.append(
            "TODO(kaudenvaihto): FPL-API ei vielä tarjoile 26/27-kautta — fixturet "
            "pulselive-fallbackista, GW-deadlinet puuttuvat. Aja uudelleen kun FPL-peli "
            "avautuu (builderi vaihtaa lähteen automaattisesti)."
        )
    out = {
        "meta": {
            "product": "GoalIQ Fantasy Phase 0 — clean sheet % + model FDR",
            "available": True,
            "phase": 0,
            "generated_at": _dt.datetime.now().isoformat(timespec="seconds"),
            "season": SEASON_LABEL,
            "source": src["source"],
            "fixture_source": src["source_label"],
            "team_strength_source": (
                f"GoalIQ Dixon-Coles, Understat PL {seasons} "
                f"(sama fit-config kuin /api/predict: decay={FIT_DECAY}, bayes={FIT_BAYES})"
            ),
            "cs_method": "P(vastustaja 0 maalia) DC-score-matriisista (tau-korjattu)",
            "context_layer": {
                "promoted_teams": sorted(promoted),
                "manual_overrides": len(ctx_cfg["overrides"]),
                "note": ("Phase 1b: promoted-side home opener attack boost "
                         "and manual overrides (data/fpl_manual_overrides.csv)"),
            },
            "fdr_method": (
                "Model based 1-5: 0.55*rank(1 - win%) + 0.45*rank(expected goals conceded), "
                "quintile bucket across every team fixture of the season"
            ),
            # EDGE-sprint: def_fdr = alias fdr:lle (CS/puolustussuunta),
            # att_fdr = hyökkäyssuunnan vaikeus samasta DC-mallista.
            "att_fdr_method": (
                "Attack FDR 1-5: rank(own expected xG in the fixture) inverted "
                "(little xG of your own means a hard fixture), quintile bucket "
                "across every team fixture. 1 = easiest to attack against, 5 = hardest."
            ),
            "caveat": (
                "Pre-season: 2026/27 team strengths are last-season priors, indicative "
                "only. Promoted sides with no top-flight data use an empirical baseline."
            ),
            "promoted_baseline_teams": missing,
            "promoted_baseline_values": baseline,
            "sanity_gate": "PASS",
            "next_gameweek": next_gw,
            "deadline_utc": src["deadline_utc"],
            # horizon_gw = montako GW:tä teams[].fixtures TÄSSÄ tiedostossa
            # sisältää (nyt koko kausi). Endpoint YLIKIRJOITTAA tämän sillä
            # mitä se pyynnössä palautti, jotta klientti näkee aina totuuden
            # omasta vastauksestaan eikä tiedoston laajuutta.
            "horizon_gw": _horizon_span(team_view),
            "horizon_max": _horizon_span(team_view),
            "near_horizon_gw": NEAR_HORIZON_GW,
            "far_basis_label": FAR_BASIS_LABEL,
            "todo": todo,
        },
        "teams": team_view,
        "fixtures": ticker,
    }
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"      -> {OUT_PATH}  ({len(team_view)} joukkuetta, {len(ticker)} ticker-fixturea)")

    print("\nEI auto-pushia. Deploy Renderiin (Villen vahvistus):")
    print("  git add data/fpl_projections_phase0.json")
    print('  git commit -m "data(fpl): Phase 0 CS%/FDR refresh"')
    print("  git push")
    return 0


if __name__ == "__main__":
    sys.exit(main())
