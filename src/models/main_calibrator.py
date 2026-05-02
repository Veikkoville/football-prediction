"""
Kalibraattorin koulutus pää-mallia varten — sekä 1X2 että Over/Under 2.5.
"""

from __future__ import annotations
from dataclasses import dataclass
import numpy as np
import pandas as pd

from src.models.dixon_coles import DixonColesModel
from src.models.calibration import MulticlassCalibrator, BinaryCalibrator


@dataclass
class MainCalibrators:
    """Kotelo: 1X2-kalibraattori ja O/U 2.5 -kalibraattori."""
    cal_1x2: MulticlassCalibrator | None = None
    cal_ou: BinaryCalibrator | None = None


def kouluta_kalibraattori(
    matches: pd.DataFrame,
    decay: float = 0.0065,
    min_train_size: int = 380,
    refit_every_days: int = 28,
    method: str = "isotonic",
) -> MainCalibrators | None:
    """
    Walk-forward jolla kerataan kalibrointidata sekä 1X2:lle että O/U 2.5:lle.

    Palauttaa MainCalibrators-olion joka sisaltaa molemmat (tai None jos
    datasetti liian pieni).
    """
    df = matches.dropna(subset=["home_score", "away_score"]).copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)

    if len(df) <= min_train_size + 50:
        return None

    raakat_p_1x2 = []
    todelliset_y = []
    raakat_p_over = []
    todelliset_over = []

    last_fit_date = None
    dc = None

    for i in range(min_train_size, len(df)):
        ottelu = df.iloc[i]
        if (dc is None or last_fit_date is None
                or (ottelu["date"] - last_fit_date).days >= refit_every_days):
            dc = DixonColesModel().fit(df.iloc[:i], decay=decay, date_col="date")
            last_fit_date = ottelu["date"]
        try:
            p1x2 = dc.predict_1x2(ottelu["home_team"], ottelu["away_team"])
            pou = dc.predict_over_under(ottelu["home_team"], ottelu["away_team"], line=2.5)
        except ValueError:
            continue

        h_g = int(ottelu["home_score"])
        a_g = int(ottelu["away_score"])
        actual = 0 if h_g > a_g else (1 if h_g == a_g else 2)
        total = h_g + a_g

        raakat_p_1x2.append([p1x2["home"], p1x2["draw"], p1x2["away"]])
        todelliset_y.append(actual)
        raakat_p_over.append(pou["over"])
        todelliset_over.append(1 if total > 2.5 else 0)

    if len(raakat_p_1x2) < 50:
        return None

    cal_1x2 = MulticlassCalibrator(method=method).fit(
        np.array(raakat_p_1x2), np.array(todelliset_y),
    )
    cal_ou = BinaryCalibrator(method=method).fit(
        np.array(raakat_p_over), np.array(todelliset_over),
    )
    return MainCalibrators(cal_1x2=cal_1x2, cal_ou=cal_ou)
