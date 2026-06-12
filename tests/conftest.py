"""Yhteiset fixturet: in-process TestClient ilman lifespan-kontekstia.

TestClient(app) ILMAN with-lohkoa ei aja startup-eventtejä → warmup-säie
(6 domestic-fittiä) ei käynnisty. Domestic-testit fittaavat on-demand (slow),
WC-testit lataavat vain esirakennetun data/wc_model.json:in (nopea).
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="session")
def client() -> TestClient:
    from api.main import app
    return TestClient(app)
