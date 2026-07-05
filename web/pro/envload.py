"""Lataa web/pro/.env os.environiin (stdlib — ei python-dotenv-riippuvuutta).

Lokaali kehitys/e2e: secretit .env-tiedostossa (gitignored). Hostissa
(Streamlit Cloud st.secrets / Render env) tiedostoa ei ole → no-op.
setdefault = oikea ympäristömuuttuja voittaa aina .env-arvon.
"""
from __future__ import annotations

import os
from pathlib import Path


def load() -> None:
    p = Path(__file__).parent / ".env"
    if not p.exists():
        return
    try:
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    except Exception:
        pass  # viallinen .env ei saa kaataa appia — config-ohje näkyy UI:ssa
