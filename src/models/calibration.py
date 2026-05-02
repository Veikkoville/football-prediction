"""
Mallin kalibrointi — Platt-skaalaus ja isotoninen regressio.

Idea: malli antaa "raakat" todennakoisyydet jotka voivat olla yli- tai
ali-itsevarmoja. Kalibrointi opettaa erillisen "korjausmallin" joka muuntaa
raakat todennakoisyydet kalibroiduiksi: kun malli sanoo 60%, toteutuma on
todella ~60%.

Kaksi metodia:
  - Platt:   sigmoidikorjaus (parametrinen, hyva kun datasetti pieni)
  - Isotoninen: monotoninen funktio (joustava, vaatii enemman dataa)

Kalibroinnin jalkeen:
  - Reliability-diagrammin pisteet noin diagonaalilla
  - Brier score paranee
  - Log loss paranee marginaalisesti
"""

from __future__ import annotations
import numpy as np
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression


class MulticlassCalibrator:
    """
    Kalibroi 3-luokkainen probabilisuusvektori (1, X, 2).

    One-vs-rest -lahestyminen: jokaiselle luokalle erillinen kalibraattori.
    """

    def __init__(self, method: str = "isotonic"):
        if method not in ("isotonic", "platt"):
            raise ValueError("method = 'isotonic' tai 'platt'")
        self.method = method
        self.kalibraattorit = []

    def fit(self, p_raw: np.ndarray, y: np.ndarray) -> "MulticlassCalibrator":
        """
        p_raw: shape (n, 3) — raakat todennakoisyydet
        y:     shape (n,)   — todelliset luokat 0, 1, 2
        """
        self.kalibraattorit = []
        for k in range(3):
            y_bin = (y == k).astype(int)
            if self.method == "isotonic":
                cal = IsotonicRegression(out_of_bounds="clip")
                cal.fit(p_raw[:, k], y_bin)
            else:
                cal = LogisticRegression(C=1.0)
                cal.fit(p_raw[:, k:k+1], y_bin)
            self.kalibraattorit.append(cal)
        return self

    def transform(self, p_raw: np.ndarray) -> np.ndarray:
        """Skaalaa raakat todennakoisyydet kalibroiduiksi."""
        out = np.zeros_like(p_raw)
        for k in range(3):
            cal = self.kalibraattorit[k]
            if self.method == "isotonic":
                out[:, k] = cal.predict(p_raw[:, k])
            else:
                out[:, k] = cal.predict_proba(p_raw[:, k:k+1])[:, 1]
        # Normalisoi summa = 1.0
        out = np.clip(out, 1e-10, 1 - 1e-10)
        out = out / out.sum(axis=1, keepdims=True)
        return out

    def fit_transform(self, p_raw: np.ndarray, y: np.ndarray) -> np.ndarray:
        return self.fit(p_raw, y).transform(p_raw)


def kalibroi_walk_forward(p_raw: np.ndarray, y: np.ndarray,
                          method: str = "isotonic", split_frac: float = 0.5) -> np.ndarray:
    """
    Kalibroi backtestin tuloksia walk-forward-tyyliin.

    Ensimmainen puolisko opettaa kalibraattorin, toinen puolisko kalibroidaan.
    Talla tavoin kalibrointi ei "huijaa" — se ei nae ennustettavaa dataa.
    """
    n = len(p_raw)
    split = int(n * split_frac)
    cal = MulticlassCalibrator(method=method).fit(p_raw[:split], y[:split])
    p_cal = p_raw.copy()
    p_cal[split:] = cal.transform(p_raw[split:])
    return p_cal


class BinaryCalibrator:
    """Yksinkertainen binaarikalibraattori (yli/alle, BTTS jne.)."""

    def __init__(self, method: str = "isotonic"):
        if method not in ("isotonic", "platt"):
            raise ValueError("method = 'isotonic' tai 'platt'")
        self.method = method
        self.cal = None

    def fit(self, p_raw: np.ndarray, y: np.ndarray) -> "BinaryCalibrator":
        if self.method == "isotonic":
            cal = IsotonicRegression(out_of_bounds="clip")
            cal.fit(p_raw, y)
        else:
            cal = LogisticRegression(C=1.0)
            cal.fit(p_raw.reshape(-1, 1), y)
        self.cal = cal
        return self

    def transform(self, p_raw: np.ndarray) -> np.ndarray:
        if self.cal is None:
            return p_raw
        if self.method == "isotonic":
            return np.clip(self.cal.predict(p_raw), 1e-10, 1 - 1e-10)
        return np.clip(self.cal.predict_proba(p_raw.reshape(-1, 1))[:, 1],
                       1e-10, 1 - 1e-10)
