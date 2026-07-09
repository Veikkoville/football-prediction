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


@pytest.fixture(autouse=True)
def _clear_fd_http_cache():
    """#49: FD-TTL-cache on prosessitason tila — nollataan joka testissä ettei
    cache vuoda testien välillä (mock-vastaus vs cachetettu edellinen)."""
    import api.main as m
    m._FD_HTTP_CACHE.clear()
    yield
    m._FD_HTTP_CACHE.clear()
