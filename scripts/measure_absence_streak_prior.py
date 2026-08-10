"""P1 (9.8.2026): pitka loppukauden poissaolo painaa Start%:n — mittaa se.

TAUSTA: kaksi nimettya osumaa samana paivana. Alisson (7 kierroksen poissaolo,
palasi viimeisella) sai Start% 51 %, Gvardiol (9 kierrosta, palasi 57+12 min)
sai 22 % ja 12,7 % omistuksella. Molemmat `status: a`. Tanaan 10.8. Gvardiolin
luku esti @OfficialFPL-vastauksen: se on dokumentoitu virhetila, joten sita ei
voi lainata julkisesti.

MIKA ON JO MITATTU (9.8, commit dbe6dd66): kaksi korjausta havisivat.

    priori          maalivahdit (n=116)   kenttapelaajat (n=1511)
    hl10 (nyt)      20.73                 20.18
    tasapaino       21.40                 21.07
    0-putki pois    27.50                 21.70

"0-putki pois" poisti KAIKKI nollaputket ehdoitta ja romutti maalivahdit
(20.73 -> 27.50). Se on odotettavaa: varamaalivahdin nollat OVAT signaali.

TAMA SKRIPTI MITTAA KAPEAMMAN EHDON jota ei ole testattu:

    poista 0-putki VAIN jos se on SISAINEN eli pelaaja PALASI sen jalkeen.

Kauden loppuun jaava putki sailyy — se voi olla aito "ei enaa suosiossa" eika
loukkaantuminen. Juuri tama erottaa Alissonin ja Gvardiolin (palasivat)
varamaalivahdista (ei palannut).

MITTA on minuutit, ei xP, ja fold on kesatauon yli — sama rakenne kuin
validate_preseason_prior.py:ssa, josta lataus- ja fold-koodi lainataan.

RAJOITE JOKA ON SANOTTAVA: Gvardiolin ja Alissonin OMIA tapauksia ei voi
validoida, koska niiden poissaolo on 25/26:n lopussa ja 26/27:sta ei ole
toteumia. Mittaus koskee MEKANISMIA kolmella historiallisella kesalla.

Ajo:  python -m scripts.measure_absence_streak_prior
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

from src.models import fpl_xp as xp
from scripts.validate_preseason_prior import (
    FOLDS, MIN_PREV_ROUNDS, _load_actuals_from_artifact, _load_eval_actuals,
    _load_prev,
)

# Putken vahimmaispituus. Sweep, koska tama on vapaa parametri eika sita saa
# valita jalkikateen tuloksen perusteella ilman etta se sanotaan.
MIN_RUN_LENS = [3, 4, 5, 6, 8]


def strip_interior_absences(mins: dict[int, float], rounds: list[int],
                            min_len: int) -> list[int]:
    """Palauta kierrosjoukko josta SISAISET >=min_len 0-putket on poistettu.

    Sisainen = putken jalkeen tulee vahintaan yksi kierros jolla on minuutteja.
    Loppuun jaava putki EI ole sisainen eika sita poisteta.
    """
    keep: list[int] = []
    i, n = 0, len(rounds)
    while i < n:
        if mins.get(rounds[i], 0.0) > 0.0:
            keep.append(rounds[i])
            i += 1
            continue
        j = i
        while j < n and mins.get(rounds[j], 0.0) <= 0.0:
            j += 1
        run = rounds[i:j]
        returned_after = any(mins.get(r, 0.0) > 0.0 for r in rounds[j:])
        if not (len(run) >= min_len and returned_after):
            keep.extend(run)
        i = j
    return keep


def predict(prev_players: dict, min_len: int | None) -> tuple[dict, dict]:
    """xmins per code. min_len=None = nykyinen tuotantopolku (ei poistoa)."""
    out: dict[int, float] = {}
    pos_by_code: dict[int, str] = {}
    n_touched = 0
    for code_s, p in prev_players.items():
        rr = {int(k): v for k, v in p["rounds"].items()}
        if len(rr) < MIN_PREV_ROUNDS:
            continue
        mins = {k: float(v[0]) for k, v in rr.items()}
        starts = {k: int(v[1]) for k, v in rr.items()}
        own_rounds = sorted(rr)
        if min_len is not None:
            kept = strip_interior_absences(mins, own_rounds, min_len)
            # Jos poisto veisi otoksen alle prioorin minimin, ala koske riviin.
            if len(kept) >= MIN_PREV_ROUNDS and len(kept) != len(own_rounds):
                own_rounds = kept
                n_touched += 1
        mm = xp.minutes_model(mins, starts, own_rounds, n_last=None)
        out[int(code_s)] = mm["xmins"]
        pos_by_code[int(code_s)] = p.get("pos") or "?"
    return out, {"n_touched": n_touched, "pos": pos_by_code}


def mae(pred: dict, actual: dict, codes: list[int]) -> float:
    xs = np.array([pred[c] for c in codes])
    ys = np.array([actual[c] for c in codes])
    return float(np.mean(np.abs(xs - ys)))


def run_fold(a: str, b: str, to_gw: int = 6) -> dict:
    prev = _load_prev(a)
    actual = (_load_eval_actuals(to_gw)[0] if b == "2526"
              else _load_actuals_from_artifact(b, to_gw))
    base, meta = predict(prev["players"], None)
    codes = sorted(set(base) & set(actual))
    pos = meta["pos"]
    # Artefaktin `pos` on FPL:n element_type (1=GKP), EI merkkijono. Ensimmainen
    # versio vertasi merkkijonoon "GKP" -> GK-joukko oli tyhja JOKA foldissa ja
    # sarake naytti nan:ia. Se olisi mennyt lapi "ei GK-ongelmaa" -tulkintana,
    # vaikka juuri GK romutti 9.8. laajan version. Nolla osumaa kaataa nyt ajon.
    gk = [c for c in codes if int(pos.get(c) or 0) == 1]
    of = [c for c in codes if int(pos.get(c) or 0) in (2, 3, 4)]
    if not gk:
        raise SystemExit(
            f"fold {a}->{b}: nolla maalivahtia populaatiossa (pos-arvot "
            f"{sorted({pos.get(c) for c in codes})}) — positiosuodatin on rikki, "
            f"EI 'ei maalivahteja'")

    rows = [{"variant": "nykyinen (ei poistoa)", "touched": 0,
             "all": mae(base, actual, codes),
             "gk": mae(base, actual, gk) if len(gk) >= 20 else float("nan"),
             "of": mae(base, actual, of)}]
    for L in MIN_RUN_LENS:
        pr, m = predict(prev["players"], L)
        rows.append({"variant": f"sisainen putki >={L} pois", "touched": m["n_touched"],
                     "all": mae(pr, actual, codes),
                     "gk": mae(pr, actual, gk) if len(gk) >= 20 else float("nan"),
                     "of": mae(pr, actual, of)})
    return {"fold": f"{a}->{b}", "n": len(codes), "n_gk": len(gk),
            "n_of": len(of), "rows": rows}


def main() -> int:
    print("=" * 78)
    print("SISAISEN POISSAOLOPUTKEN POISTO — pre-season-priori, 3 kesataukoa")
    print("Mitta: xMins MAE (min) GW1-6. Pienempi parempi.")
    print("=" * 78)
    all_res = [run_fold(a, b) for a, b in FOLDS]
    for r in all_res:
        print(f"\n{r['fold']}  n={r['n']} (GK {r['n_gk']} / kenttä {r['n_of']})")
        print(f"  {'variantti':<24}{'koskettu':>9}{'MAE all':>10}"
              f"{'MAE GK':>9}{'MAE kenttä':>12}")
        base = r["rows"][0]
        for row in r["rows"]:
            d = row["all"] - base["all"]
            mark = "" if row is base else f"  ({d:+.3f})"
            print(f"  {row['variant']:<24}{row['touched']:>9}"
                  f"{row['all']:>10.3f}{row['gk']:>9.3f}{row['of']:>12.3f}{mark}")

    print("\n" + "=" * 78)
    print("YHTEENVETO — keskiarvo kolmesta foldista")
    print("=" * 78)
    names = [row["variant"] for row in all_res[0]["rows"]]
    base_all = float(np.mean([r["rows"][0]["all"] for r in all_res]))
    verdict_rows = []
    for i, name in enumerate(names):
        m_all = float(np.mean([r["rows"][i]["all"] for r in all_res]))
        m_gk = float(np.mean([r["rows"][i]["gk"] for r in all_res]))
        m_of = float(np.mean([r["rows"][i]["of"] for r in all_res]))
        wins = sum(1 for r in all_res if r["rows"][i]["all"] < r["rows"][0]["all"])
        verdict_rows.append((name, m_all, m_gk, m_of, wins))
        print(f"  {name:<24}  all {m_all:6.3f} ({m_all - base_all:+.3f})  "
              f"GK {m_gk:6.3f}  kenttä {m_of:6.3f}  voittaa {wins}/3 foldia")

    best = min(verdict_rows[1:], key=lambda t: t[1])
    print()
    if best[1] < base_all and best[4] == 3:
        print(f"  TULOS: '{best[0]}' voittaa kaikissa kolmessa foldissa "
              f"({best[1]:.3f} vs {base_all:.3f}). Ehdokas shipattavaksi.")
    elif best[1] < base_all:
        print(f"  TULOS: '{best[0]}' on keskimaarin parempi mutta voittaa vain "
              f"{best[4]}/3 foldia — EI riita. Yksi fold on kohinaa.")
    else:
        print(f"  TULOS: yksikaan variantti EI voita nykyista "
              f"({base_all:.3f}). Hypoteesi kaatui.")
    print("  HUOM: GK-sarake on se joka romutti 9.8. laajan version "
          "(20.73 -> 27.50). Katso se erikseen.")

    # -----------------------------------------------------------------
    # ONKO ILMIOTA EDES OLEMASSA?
    #
    # Ylla oleva mittaa KORJAUKSEN. Jos korjaus haviaa, se ei viela kerro
    # onko alkuperainen havainto (Alisson/Gvardiol) oikea. Tama leikkaus
    # mittaa sen suoraan: aliarvioiko priori juuri niita joilla on sisainen
    # poissaolojakso ja paluu?
    #
    # bias = ennuste - toteuma. Negatiivinen = ennustimme liian vahan.
    # -----------------------------------------------------------------
    print("\n" + "=" * 78)
    print("ONKO ILMIOTA? — bias (ennuste − toteuma, min) ryhmittain")
    print("=" * 78)
    RUN = 5
    tot = {"aff": [], "rest": []}
    for a, b in FOLDS:
        prev = _load_prev(a)
        actual = (_load_eval_actuals(6)[0] if b == "2526"
                  else _load_actuals_from_artifact(b, 6))
        base, meta = predict(prev["players"], None)
        aff, rest = [], []
        for code_s, p in prev["players"].items():
            c = int(code_s)
            if c not in base or c not in actual:
                continue
            rr = {int(k): v for k, v in p["rounds"].items()}
            mins = {k: float(v[0]) for k, v in rr.items()}
            rounds = sorted(rr)
            touched = len(strip_interior_absences(mins, rounds, RUN)) != len(rounds)
            (aff if touched else rest).append(base[c] - actual[c])
        tot["aff"] += aff
        tot["rest"] += rest
        print(f"  {a}->{b}: poissaolo+paluu n={len(aff):<4} bias {np.mean(aff):+6.2f}"
              f"   muut n={len(rest):<4} bias {np.mean(rest):+6.2f}")
    ba, br = float(np.mean(tot["aff"])), float(np.mean(tot["rest"]))
    print(f"\n  YHTEENSA: poissaolo+paluu n={len(tot['aff'])} bias {ba:+.2f} min"
          f"   |   muut n={len(tot['rest'])} bias {br:+.2f} min")
    print(f"  Ero: {ba - br:+.2f} min")
    # LUKUOHJE: ryhmien EROA ei saa lukea virheeksi ilman etta katsoo kumpi
    # ryhma on lahempana nollaa. Ero kertoo miksi luku NAYTTAA vaaralta
    # kayttajalle; |bias| kertoo kumpi ryhma on oikeasti vaarin.
    print(f"\n  |bias|: poissaolo+paluu {abs(ba):.2f}  vs  muut {abs(br):.2f}")
    if abs(ba) < abs(br):
        print("  -> KAANTEINEN TULOS. Poissaolo+paluu -ryhma on se joka on")
        print("     PAREMMIN kalibroitu. Systemaattinen virhe on muualla:")
        print(f"     priori YLIarvioi muut {br:+.2f} min kesatauon yli.")
        print("     Alisson/Gvardiol nayttavat vaarilta koska heidat mitataan")
        print("     mallin yleista optimismia vasten, ei toteumaa vasten.")
        print("     -> Aliarviota EI korjata. Alkuperainen P1-diagnoosi kaatuu.")
    elif ba < br - 2.0:
        print("  -> Ilmio on olemassa ja se on ALIARVIO. Korjaus ei validoitunut,")
        print("     joten oikea vaste on LIPPU eika luvun saato.")
    else:
        print("  -> Ryhma ei eroa muista.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
