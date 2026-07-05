"""FPL Phase 1b — konteksti/override-kerros DC-pohjaisiin FPL-projektioihin.

Kolme mekanismia (scope-kuri: EI täydellistä kontekstimoottoria):

1. NOUSIJA-KOTI-AVAUS-BUUSTI (parametroitu, automaattinen):
   Raaka DC + promoted-baseline aliarvioi nousijan hyökkäystä sarja-avauksessa
   kotona → vastustajan CS-% ja puolustajien xP yliarvioituvat (esim. naivi
   "Man Utd 43 % CS @ Hull"). Kalibrointi 25/26-datasta (walk-forward):
   nousijat kotona elo-syyskuussa toteuma/odotus = 1.28 (n=9), koti-avauksissa
   2.8 (n=3, jokainen ylitti odotuksen). Vieraissa 0.84 → EI buustia vieraisiin.
   Konservatiivinen kerroin 1.30 vain ENSIMMÄISEEN kotipeliin.

2. MANUAALISET YLIAJOT (data/fpl_manual_overrides.csv):
   Joukkue/fixture-kohtaiset kertoimet joilla korjataan tunnetut naivit
   tapaukset käsin ilman koodimuutosta. Sama tiedosto kantaa myös
   MM-2026-väsymyskertoimet (scope=wc_fatigue): pelaajakohtaisia MM-minuutteja
   ei ole ilmaisessa datassa (FPL-API ei tunne maajoukkueminuutteja,
   international_results.csv on joukkuetaso) → seura-tason kertoimet
   syötetään käsin MM-finaalin (~19.7) jälkeen.

3. xMINS-KERROIN (väsymys): overrides-rivin xmins_mult skaalaa joukkueen
   pelaajien minuuttiodotusta annetulla GW-välillä (builderissa).

Kerroin-semantiikka: attack_mult kertoo JOUKKUEEN oman maaliodotuksen (λ),
defence_mult kertoo VASTUSTAJAN maaliodotuksen (>1 = puolustus vuotaa
enemmän). Sovellus DC:n olemassa olevan adjustments-mekanismin kautta
(dixon_coles.expected_goals/score_matrix: home_factor/away_factor) —
sama polku jota /api/predictin manuaalisäädöt käyttävät.

Walk-forward-laillisuus: nousijastatus ja ensimmäisen kotipelin GW ovat
tiedossa ennen kautta → mekanismi #1 saa olla mukana 25/26-backtestissä
(gate-uusinta). Manuaaliset yliajot ja MM-kertoimet ovat 26/27-inputteja —
niitä EI ladata backtestissä.
"""
from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

import numpy as np

import config

OVERRIDES_PATH = config.DATA_DIR / "fpl_manual_overrides.csv"

# Kalibroitu 25/26 walk-forward -datasta (ks. moduulidocstring + Phase 1b
# -raportti): koti-avauksen toteuma/odotus 2.8 (n=3), koko alkukauden koti
# 1.28 (n=9). 1.30 = konservatiivinen, koskee vain yhtä fixturea per nousija.
PROMOTED_HOME_OPENER_ATT_BOOST = 1.30

_OVERRIDE_FIELDS = ("scope", "team", "opponent", "venue", "gw_from", "gw_to",
                    "attack_mult", "defence_mult", "xmins_mult", "note")


# ---------------------------------------------------------------------------
# Konfiguraatio
# ---------------------------------------------------------------------------
def promoted_teams(current_teams: set[str], previous_teams: set[str]) -> set[str]:
    """Nousijat = tämän kauden joukkueet joita ei ollut edellisellä kaudella."""
    return set(current_teams) - set(previous_teams)


def first_home_gw(fixtures: list[dict]) -> dict[str, int]:
    """Ensimmäisen KOTIpelin GW per joukkue. fixtures: {gameweek, home, away}
    (mallinimillä). Käytetään nousija-koti-avaus-buustin kohdistamiseen."""
    out: dict[str, int] = {}
    for f in fixtures:
        gw = f.get("gameweek")
        h = f.get("home")
        if gw is None or h is None:
            continue
        if h not in out or gw < out[h]:
            out[h] = gw
    return out


def load_overrides(path: Path = OVERRIDES_PATH) -> list[dict]:
    """Lue manuaaliset yliajot. Puuttuva tiedosto / kommenttirivit (#) ok.
    Virheellinen rivi ohitetaan äänekkäästi (print), ei kaadeta builderia."""
    if not path.exists():
        return []
    rows: list[dict] = []
    with path.open(encoding="utf-8") as fh:
        reader = csv.DictReader(r for r in fh if not r.lstrip().startswith("#"))
        for i, raw in enumerate(reader, 2):
            try:
                rows.append({
                    "scope": (raw.get("scope") or "manual").strip(),
                    "team": (raw.get("team") or "").strip(),
                    "opponent": (raw.get("opponent") or "").strip() or None,
                    "venue": (raw.get("venue") or "").strip().upper() or None,
                    "gw_from": int(raw["gw_from"]) if (raw.get("gw_from") or "").strip() else None,
                    "gw_to": int(raw["gw_to"]) if (raw.get("gw_to") or "").strip() else None,
                    "attack_mult": float(raw["attack_mult"]) if (raw.get("attack_mult") or "").strip() else 1.0,
                    "defence_mult": float(raw["defence_mult"]) if (raw.get("defence_mult") or "").strip() else 1.0,
                    "xmins_mult": float(raw["xmins_mult"]) if (raw.get("xmins_mult") or "").strip() else 1.0,
                    "note": (raw.get("note") or "").strip(),
                })
            except (KeyError, ValueError) as e:
                print(f"      VAROITUS: overrides-rivi {i} ohitettu ({e})")
    for r in rows:
        if not r["team"]:
            print("      VAROITUS: overrides-rivi ilman team-kenttää ohitettu")
    return [r for r in rows if r["team"]]


def build_context(promoted: set[str], fixtures: list[dict],
                  overrides: list[dict] | None = None) -> dict:
    """Kokoa cfg jonka fixture_contexts/xmins_multiplier ottavat vastaan."""
    return {
        "promoted": set(promoted),
        "first_home_gw": first_home_gw(fixtures),
        "overrides": list(overrides or []),
    }


# ---------------------------------------------------------------------------
# Fixture-kertoimet
# ---------------------------------------------------------------------------
def _override_matches(r: dict, team: str, opponent: str, venue: str,
                      gw: int | None) -> bool:
    if r["team"] != team:
        return False
    if r["opponent"] and r["opponent"] != opponent:
        return False
    if r["venue"] and r["venue"] != venue:
        return False
    if gw is not None:
        if r["gw_from"] is not None and gw < r["gw_from"]:
            return False
        if r["gw_to"] is not None and gw > r["gw_to"]:
            return False
    return True


def fixture_adjustments(home: str, away: str, gw: int | None,
                        cfg: dict | None) -> tuple[dict | None, list[str]]:
    """DC-adjustments ({home_factor, away_factor}) + selitteet fixturelle.

    home_factor kertoo kotijoukkueen λ:n, away_factor vierasjoukkueen λ:n
    (dixon_coles.expected_goals-semantiikka). None = ei säätöjä (raaka DC).
    """
    if not cfg:
        return None, []
    hf = af = 1.0
    notes: list[str] = []

    # 1. Nousija-koti-avaus-buusti (vain kotijoukkueelle, vain 1. kotipeli)
    if (home in cfg.get("promoted", ())
            and gw is not None
            and cfg.get("first_home_gw", {}).get(home) == gw):
        hf *= PROMOTED_HOME_OPENER_ATT_BOOST
        notes.append(f"promoted-home-opener {home} x{PROMOTED_HOME_OPENER_ATT_BOOST}")

    # 2. Manuaaliset yliajot (molemmilta puolilta)
    for r in cfg.get("overrides", ()):
        for team, opp, venue in ((home, away, "H"), (away, home, "A")):
            if not _override_matches(r, team, opp, venue, gw):
                continue
            own = "home_factor" if venue == "H" else "away_factor"
            if r["attack_mult"] != 1.0:
                if own == "home_factor":
                    hf *= r["attack_mult"]
                else:
                    af *= r["attack_mult"]
            if r["defence_mult"] != 1.0:
                # defence_mult kertoo VASTUSTAJAN maaliodotuksen
                if own == "home_factor":
                    af *= r["defence_mult"]
                else:
                    hf *= r["defence_mult"]
            if r["attack_mult"] != 1.0 or r["defence_mult"] != 1.0:
                notes.append(f"override[{r['scope']}] {team} vs {opp} ({venue}) "
                             f"att x{r['attack_mult']} def x{r['defence_mult']}"
                             + (f" ({r['note']})" if r["note"] else ""))

    if hf == 1.0 and af == 1.0:
        return None, []
    return {"home_factor": hf, "away_factor": af}, notes


def xmins_multiplier(team: str, gw: int | None, cfg: dict | None) -> float:
    """Joukkueen pelaajien minuuttikerroin (esim. MM-väsymys) GW:lle."""
    if not cfg:
        return 1.0
    m = 1.0
    for r in cfg.get("overrides", ()):
        if r["xmins_mult"] != 1.0 and _override_matches(r, team, "", "", gw):
            # opponent/venue-suodattimet eivät sovellu xmins-kertoimeen —
            # vaaditaan että ne ovat tyhjiä ettei rivi osu vahingossa
            if r["opponent"] is None and r["venue"] is None:
                m *= r["xmins_mult"]
    return m


# ---------------------------------------------------------------------------
# Joukkuekonteksti DC:stä (siirretty backtest-skriptistä; nyt cfg-tietoinen)
# ---------------------------------------------------------------------------
def neutral_lambda(dc, teams: list[str]) -> dict[str, float]:
    """Joukkueen neutraali maaliodotus: keskiarvo koti+vieras kaikkia muita
    kauden joukkueita vastaan (ILMAN säätöjä — kertoimien vertailupohja)."""
    out = {}
    for t in teams:
        vals = []
        for o in teams:
            if o == t:
                continue
            lam_h, _ = dc.expected_goals(t, o)
            _, mu_a = dc.expected_goals(o, t)
            vals.extend([lam_h, mu_a])
        out[t] = float(np.mean(vals)) if vals else 1.0
    return out


def fixture_contexts(dc, fxs: list[dict], tid_to_model: dict[int, str],
                     lam_avg: dict[str, float],
                     cfg: dict | None = None,
                     gw: int | None = None) -> dict[int, list[dict]]:
    """Per joukkue-id: lista fixture-konteksteja (DGW:ssä useampi).

    cfg (build_context) → nousijabuusti + manuaaliset yliajot sovelletaan
    DC:n adjustments-mekanismilla ennen score-matriisia. cfg=None = raaka DC
    (identtinen Phase 1 -käyttäytymisen kanssa).
    """
    ctx_by_team: dict[int, list[dict]] = defaultdict(list)
    for f in fxs:
        h = tid_to_model.get(f["team_h"])
        a = tid_to_model.get(f["team_a"])
        if h not in dc.attack or a not in dc.attack:
            continue
        fgw = f.get("event", gw)
        adj, _notes = fixture_adjustments(h, a, fgw, cfg)
        lam, mu = dc.expected_goals(h, a, adjustments=adj)
        m = dc.score_matrix(h, a, adjustments=adj)
        home_goals_dist = m.sum(axis=1)   # P(koti tekee i)
        away_goals_dist = m.sum(axis=0)   # P(vieras tekee j)
        ctx_by_team[f["team_h"]].append({
            "goal_mult": lam / max(lam_avg.get(h, 1.0), 1e-9),
            "cs_prob": float(m[:, 0].sum()),
            "conceded_dist": [float(p) for p in away_goals_dist],
            "opp_goal_mult": mu / max(lam_avg.get(a, 1.0), 1e-9),
        })
        ctx_by_team[f["team_a"]].append({
            "goal_mult": mu / max(lam_avg.get(a, 1.0), 1e-9),
            "cs_prob": float(m[0, :].sum()),
            "conceded_dist": [float(p) for p in home_goals_dist],
            "opp_goal_mult": lam / max(lam_avg.get(h, 1.0), 1e-9),
        })
    return ctx_by_team
