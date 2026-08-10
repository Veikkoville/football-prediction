"""P1 (10.8.2026): pre-season-priori YLIARVIOI minuutit kesatauon yli.

MITTAUS JOKA TAMAN AVASI (`measure_absence_streak_prior.py`, 10.8):

    poissaolo + paluu   n=495   bias -2.80 min
    kaikki muut         n=621   bias +8.01 min

Eli se ryhma josta 9.8. huolestuttiin on paremmin kalibroitu, ja oikea vika on
yleinen optimismi. +8 min on iso: se on melkein kokonainen vaihto-osuus, ja se
menee suoraan xP:hen (appearance-pisteet, CS-osuus, DefCon-osuus).

MIKSI PRIORI YLIARVIOI: se nakee vain viime kauden kierrokset. Se ei nae
myyntia, ikaantymista, uutta kilpailijaa eika paikan menetysta. Nama ovat
kaikki YKSISUUNTAISIA: pelaaja voi menettaa paikkansa helpommin kuin saada
lisaa minuutteja kun han jo pelaa 90.

TAMA SKRIPTI TESTAA KOLME KALIBROINTIA ristiinvalidoiden. Fitti tehdaan
KAHDELLA kesalla ja mitataan KOLMANNELLA, ja se kierratetaan. Ilman sita
kalibrointi sovittaisi itsensa omaan mittariinsa.

    1. affine        pred' = a + b*pred                  (pienimman nelion sovite)
    2. shrink        pred' = m + k*(pred - m), k sweep    (m = treenin keskiarvo)
    3. multiplic.    pred' = c*pred

HUOM: tama MUUTTAA xP:ta toisin kuin 10.8. muut muutokset. Pre-season-polkua
ei kata kauden sisainen ship-gate lainkaan (siksi validate_preseason_prior.py
on olemassa), joten portti tassa on foldien MAE + karkipaan tarkistus:
naulattu avaaja ei saa valua alas, koska hanen 90 minuuttiaan on oikein.

Ajo:  python -m scripts.calibrate_preseason_minutes
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

from scripts.validate_preseason_prior import (
    FOLDS, _load_actuals_from_artifact, _load_eval_actuals, _load_prev,
)
from scripts.measure_absence_streak_prior import predict

SHRINK_KS = [0.70, 0.75, 0.80, 0.85, 0.90, 0.95]


def fold_pairs(a: str, b: str, to_gw: int = 6):
    """(pred, actual, pos) yhdelle foldille nykyisella prioorilla."""
    prev = _load_prev(a)
    actual = (_load_eval_actuals(to_gw)[0] if b == "2526"
              else _load_actuals_from_artifact(b, to_gw))
    base, meta = predict(prev["players"], None)
    codes = sorted(set(base) & set(actual))
    if not codes:
        raise SystemExit(f"fold {a}->{b}: nolla yhteista pelaajaa")
    return (np.array([base[c] for c in codes]),
            np.array([actual[c] for c in codes]),
            np.array([int(meta["pos"].get(c) or 0) for c in codes]))


def clip(x):
    return np.clip(x, 0.0, 90.0)


def main() -> int:
    data = {f"{a}->{b}": fold_pairs(a, b) for a, b in FOLDS}
    names = list(data)

    print("=" * 78)
    print("PRE-SEASON-MINUUTTIEN KALIBROINTI — leave-one-fold-out")
    print("Fitti kahdella kesalla, mittaus kolmannella. Mitta: MAE (min).")
    print("=" * 78)

    results: dict[str, list[float]] = {}
    top_shift: dict[str, list[float]] = {}
    cs: list[float] = []
    affine_coefs: list[tuple[float, float]] = []

    for test in names:
        train = [n for n in names if n != test]
        tr_p = np.concatenate([data[n][0] for n in train])
        tr_a = np.concatenate([data[n][1] for n in train])
        te_p, te_a, _ = data[test]

        base_mae = float(np.mean(np.abs(te_p - te_a)))
        results.setdefault("nykyinen", []).append(base_mae)
        top_shift.setdefault("nykyinen", []).append(0.0)

        # 1. affine
        b, a_ = np.polyfit(tr_p, tr_a, 1)
        affine_coefs.append((a_, b))
        pred = clip(a_ + b * te_p)
        results.setdefault("affine", []).append(float(np.mean(np.abs(pred - te_a))))
        top = te_p >= 75
        top_shift.setdefault("affine", []).append(
            float(np.mean(pred[top] - te_p[top])) if top.any() else 0.0)

        # 2. shrink kohti treenin toteumakeskiarvoa
        m = float(np.mean(tr_a))
        for k in SHRINK_KS:
            pr = clip(m + k * (te_p - m))
            key = f"shrink k={k:.2f}"
            results.setdefault(key, []).append(float(np.mean(np.abs(pr - te_a))))
            top_shift.setdefault(key, []).append(
                float(np.mean(pr[top] - te_p[top])) if top.any() else 0.0)

        # 3. multiplikatiivinen
        # Avain on VAKIO ("mult") eika sisalla kerrointa: kerroin muuttuu
        # foldeittain, joten kertoimellinen avain tuottaisi kolme eri avainta
        # joissa on yksi havainto kukin -> "voittaa 3/3" olisi mahdoton.
        c = float(np.sum(tr_p * tr_a) / np.sum(tr_p * tr_p))
        cs.append(c)
        pr = clip(c * te_p)
        results.setdefault("mult", []).append(float(np.mean(np.abs(pr - te_a))))
        top_shift.setdefault("mult", []).append(
            float(np.mean(pr[top] - te_p[top])) if top.any() else 0.0)

    base = float(np.mean(results["nykyinen"]))
    print(f"\n  {'variantti':<20}{'MAE ka.':>9}{'delta':>9}{'voittaa':>9}"
          f"{'karki >=75 min siirtyy':>26}")
    order = sorted(results, key=lambda k: float(np.mean(results[k])))
    for k in order:
        m = float(np.mean(results[k]))
        wins = sum(1 for i in range(3) if results[k][i] < results["nykyinen"][i])
        ts = float(np.mean(top_shift[k]))
        print(f"  {k:<20}{m:>9.3f}{m - base:>+9.3f}{wins:>7}/3"
              f"{ts:>+24.1f} min")

    aa = float(np.mean([c[0] for c in affine_coefs]))
    ab = float(np.mean([c[1] for c in affine_coefs]))
    print(f"\n  sovitetut kertoimet: affine a={aa:.2f} b={ab:.3f} | "
          f"mult c={float(np.mean(cs)):.3f}")

    best = order[0]
    print()
    if best == "nykyinen":
        print("  TULOS: yksikaan kalibrointi ei voita. Optimismi jaa korjaamatta.")
    else:
        wins = sum(1 for i in range(3)
                   if results[best][i] < results["nykyinen"][i])
        print(f"  TULOS: paras on '{best}' ({np.mean(results[best]):.3f} vs "
              f"{base:.3f}), voittaa {wins}/3 foldia.")
        if wins < 3:
            print("  EI RIITA: vaadi 3/3, muuten yksi kesa on kohinaa.")
        elif abs(np.mean(top_shift[best])) > 3.0:
            print(f"  VAROITUS: karki siirtyy {np.mean(top_shift[best]):+.1f} min. "
                  f"Naulatun avaajan 90 min on oikein — ala shippaa jos karki valuu.")
        else:
            print("  Ehdokas shipattavaksi: voittaa kaikissa foldeissa eika "
                  "karki valu.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
