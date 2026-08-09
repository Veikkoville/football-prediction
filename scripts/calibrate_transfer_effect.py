"""VAIHE 2+3: paljonko kesan siirrot TODELLA siirtavat joukkueluokitusta.

ONGELMA: DC-luokitukset sovitetaan toteutuneisiin tuloksiin, joten ne eivat nae
siirtoikkunaa. Aikavaimennuksella (half-life ~198 pv) uusi kausi on GW6:ssa vasta
25 % fitin painosta - kesan siirrot ovat puoliksi mukana vasta tammikuussa.
Tama koskee YHTA LAILLA ottelumallia (/api/predict) ja FPL-tyokaluja.

VAIHE 2 - tulokkaiden arvottaminen FPL-HINNALLA.
  Understat kattaa vain 5 suurta liigaa, joten sielta tuleva arvotus jattaisi
  osan tulokkaista nollaksi (Newcastlella 5 kpl). FPL hinnoittelee 100 %
  pelaajista riippumatta siita mista he tulevat, joten hinta on ainoa taysin
  kattava signaali. Se on markkinan odotus, ei totuus - ja juuri siksi se
  kelpaa prioriksi ennen kuin yhtaan ottelua on pelattu.
  Mitta on hinta YLI KORVAAJATASON (position halvin), koska 4.0-4.5 M pelaaja
  on taytetta eika vahvistus.

VAIHE 3 - empiirinen kerroin.
  Kolme kausivaihdosta (22/23->23/24, 23/24->24/25, 24/25->25/26). Jokaiselle:
  nettohintamassan muutos vs joukkueen DC-luokituksen TOTEUTUNUT muutos, kun
  molemmat kaudet fitataan erikseen. Regressio antaa kertoimen jolla
  nettohintamassa muunnetaan attack_mult/defence_mult-yliajoksi.

  ILMAN TATA VAIHETTA yliajo olisi arvaus mallin tulosteen nakoisena. Sita ei
  shipata.

Ajo:  python -m scripts.calibrate_transfer_effect
"""
from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

import config
from scripts.build_fpl_phase0 import FIT_BAYES, FIT_DECAY, map_name
from src.data.loader import lataa_otteludata
from src.models.dixon_coles import DixonColesModel

# Kausi -> mista pelaajarivit luetaan. 25/26 tulee levyarkiston bootstrapista,
# vanhemmat yhteisoarkiston players_raw.csv:sta (sama lahde kuin
# build_fpl_prev_season_minutes).
SEASONS = ["2223", "2324", "2425", "2526"]


def _load_players(season: str) -> list[dict]:
    """[{code, team_name, pos, price}] kaudelle."""
    if season == "2526":
        boot = json.loads((config.RAW_DATA_DIR / "fpl"
                           / "bootstrap_static_2526.archive.json")
                          .read_text(encoding="utf-8"))
        tname = {t["id"]: t["name"] for t in boot["teams"]}
        return [{"code": e["code"], "team": tname[e["team"]],
                 "pos": e["element_type"], "price": e["now_cost"] / 10.0}
                for e in boot["elements"]]
    src = config.RAW_DATA_DIR / "fpl" / f"season_{season}"
    teams: dict[int, str] = {}
    tf = src / "teams.csv"
    if tf.exists():
        with tf.open(encoding="utf-8", newline="") as fh:
            teams = {int(r["id"]): r["name"] for r in csv.DictReader(fh)}
    out = []
    with (src / "players_raw.csv").open(encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            out.append({"code": int(r["code"]),
                        "team": teams.get(int(r["team"]), str(r["team"])),
                        "pos": int(r["element_type"]),
                        "price": float(r["now_cost"]) / 10.0})
    return out


def _above_replacement(players: list[dict]) -> dict[int, float]:
    """Hinta yli position halvimman. 4.0 M pelaaja ei ole vahvistus."""
    floor: dict[int, float] = {}
    for p in players:
        floor[p["pos"]] = min(floor.get(p["pos"], 99.0), p["price"])
    return {p["code"]: max(p["price"] - floor[p["pos"]], 0.0) for p in players}


def transfer_mass(prev: str, cur: str) -> dict[str, dict]:
    """Per joukkue: nettohintamassa sisaan-ulos, hyokkays ja puolustus erikseen."""
    pp, cp = _load_players(prev), _load_players(cur)
    ar_p, ar_c = _above_replacement(pp), _above_replacement(cp)
    prev_by_code = {p["code"]: p for p in pp}
    cur_by_code = {p["code"]: p for p in cp}

    prev_squads: dict[str, list[dict]] = defaultdict(list)
    for p in pp:
        prev_squads[p["team"]].append(p)
    cur_squads: dict[str, list[dict]] = defaultdict(list)
    for p in cp:
        cur_squads[p["team"]].append(p)

    out: dict[str, dict] = {}
    for team in set(prev_squads) & set(cur_squads):
        base = sum(ar_p[p["code"]] for p in prev_squads[team]) or 1.0
        gone_a = gone_d = came_a = came_d = 0.0
        for p in prev_squads[team]:
            n = cur_by_code.get(p["code"])
            if n is not None and n["team"] == team:
                continue                         # jai
            if p["pos"] in (1, 2):
                gone_d += ar_p[p["code"]]
            else:
                gone_a += ar_p[p["code"]]
        for p in cur_squads[team]:
            o = prev_by_code.get(p["code"])
            if o is not None and o["team"] == team:
                continue                         # jai
            if p["pos"] in (1, 2):
                came_d += ar_c[p["code"]]
            else:
                came_a += ar_c[p["code"]]
        out[team] = {"net_att": (came_a - gone_a) / base,
                     "net_def": (came_d - gone_d) / base}
    return out


def season_ratings(season: str) -> tuple[dict, dict]:
    """DC-luokitukset kaudelle YKSIN (ei edelliskautta) -> muutos on mitattava."""
    m = lataa_otteludata(["ENG-Premier League"], [season])
    if m.empty:
        raise SystemExit(f"PL-otteludata puuttuu kaudelta {season}")
    dc = DixonColesModel(per_team_home_adv=True).fit(
        m, home_team_col="home_team", away_team_col="away_team",
        home_goals_col="home_score", away_goals_col="away_score",
        decay=FIT_DECAY, date_col="date", l2_attack_defence=FIT_BAYES)
    # DC:n parametrit ovat LOG-avaruudessa (lam = exp(attack + defence + ...)),
    # joten muutos on erotus eika log-suhde.
    #
    # KESKITYS ON PAKOLLINEN: attack/defence-parilla on mittakaavavapaus (vakion
    # lisaaminen kaikkiin attackeihin ja vahentaminen defenceista tuottaa saman
    # mallin). Kun kaudet fitataan erikseen, taso kelluu vapaasti ja liigan
    # yleinen maalitaso vuotaisi jokaiseen joukkuekohtaiseen erotukseen. Se ei
    # nakyisi tuloksessa mitenkaan - regressio vain naytaisi heikommalta.
    a, d = dict(dc.attack), dict(dc.defence)
    ma = float(np.mean(list(a.values())))
    md = float(np.mean(list(d.values())))
    return ({t: v - ma for t, v in a.items()}, {t: v - md for t, v in d.items()})


def main() -> int:
    ratings = {}
    for s in SEASONS:
        ratings[s] = season_ratings(s)
        print(f"  DC-luokitukset {s}: {len(ratings[s][0])} joukkuetta")

    rows = []
    for prev, cur in zip(SEASONS, SEASONS[1:]):
        mass = transfer_mass(prev, cur)
        pa, pd_ = ratings[prev]
        ca, cd = ratings[cur]
        for fpl_team, m in mass.items():
            t = map_name(fpl_team)
            if t not in pa or t not in ca:
                continue                          # nousija/putoaja
            rows.append({
                "transition": f"{prev}->{cur}", "team": t,
                "net_att": m["net_att"], "net_def": m["net_def"],
                # log-avaruudessa: erotus. + = hyokkays parani.
                # defence: + = paastaa ENEMMAN eli puolustus heikkeni
                # (mu = exp(attack_vieras + defence_koti)).
                "d_att": float(ca[t] - pa[t]),
                "d_def": float(cd[t] - pd_[t]),
            })

    print(f"\n  havaintoja: {len(rows)} joukkue-kausivaihdosta")
    if len(rows) < 20:
        raise SystemExit("liian vahan havaintoja regressioon")

    print("\n" + "=" * 70)
    print("VAIHE 3 — siirtyyko luokitus nettohintamassan mukana?")
    print("=" * 70)
    for xk, yk, label in (("net_att", "d_att", "hyokkays"),
                          ("net_def", "d_def", "puolustus")):
        x = np.array([r[xk] for r in rows])
        y = np.array([r[yk] for r in rows])
        slope, intercept = np.polyfit(x, y, 1)
        pred = slope * x + intercept
        ss_res = float(np.sum((y - pred) ** 2))
        ss_tot = float(np.sum((y - y.mean()) ** 2))
        r2 = 1 - ss_res / ss_tot if ss_tot else float("nan")
        r = float(np.corrcoef(x, y)[0, 1])
        print(f"  {label:<10} kulmakerroin {slope:+.4f}  r {r:+.3f}  "
              f"R2 {r2:.3f}  (n={len(x)})")
        # Kaytannon merkitys: mita 20 %:n nettomenetys tekisi
        print(f"             -> netto -20 % siirtaisi luokitusta "
              f"{(np.exp(slope * -0.20) - 1) * 100:+.1f} %")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
