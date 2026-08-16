"""GW1-GW3 ilmainen ikkuna (Villen paatos 16.8.2026).

Nama testit vahtivat kolmea asiaa, ja jokainen niista on kirjattu miina:

1. Ikkuna avaa premiumin KIRJAUTUNEELLE, ei anonyymille.
2. Ikkuna sulkeutuu KELLON mukaan.
3. 🔴 Ikkuna ei kirjoita `profiles.is_premium`ia kenellekaan. 14.8:n
   toteutettavuusarvio mittasi etta lipun kaantaminen tekisi kayttajasta
   PYSYVAN premiumin, koska `subscription_current_period_end` on
   kirjoitus-only, yksikaan portti ei lue sita eika vanhentumissweeppia ole.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

import api.premium as prem


@pytest.fixture(autouse=True)
def _clean_cache():
    with prem._PREMIUM_CACHE_LOCK:
        prem._PREMIUM_CACHE.clear()
    yield
    with prem._PREMIUM_CACHE_LOCK:
        prem._PREMIUM_CACHE.clear()


class _Req:
    """Starlette-headerit ovat case-insensitiivisia; portti lukee avaimen
    pienella. Tavallinen dict ei ole, joten avain on kirjoitettava samoin."""

    def __init__(self, token: str | None = "tok"):
        self.headers = {"authorization": f"Bearer {token}"} if token else {}


# --- ikkunan oma logiikka --------------------------------------------------

def test_window_default_ends_at_gw4_deadline(monkeypatch):
    """Ikkuna paattyy GW4:n deadlineen, joka luettiin FPL:n bootstrapista
    16.8. Jos vakio muuttuu vahingossa, tama kaatuu."""
    monkeypatch.delenv("FREE_PREMIUM_UNTIL", raising=False)
    end = prem.free_premium_window_end()
    assert end == datetime(2026, 9, 12, 12, 30, tzinfo=timezone.utc)


def test_window_closes_on_the_clock(monkeypatch):
    monkeypatch.delenv("FREE_PREMIUM_UNTIL", raising=False)
    end = prem.free_premium_window_end()
    assert prem.free_premium_window_active(end - timedelta(seconds=1)) is True
    assert prem.free_premium_window_active(end) is False
    assert prem.free_premium_window_active(end + timedelta(days=1)) is False


def test_window_can_be_switched_off_by_env(monkeypatch):
    monkeypatch.setenv("FREE_PREMIUM_UNTIL", "off")
    assert prem.free_premium_window_end() is None
    assert prem.free_premium_window_active() is False


def test_env_cannot_move_the_date_only_switch_it_off(monkeypatch):
    """🔴 Env on PELKKA KATKAISIN. Sama paivamaara elaa kolmella pinnalla ja
    se on kirjoitettu auki julkiseen copyyn ("12 September"). Jos env voisi
    siirtaa paivaa, backend antaisi premiumin eri paivaan asti kuin mita
    sivut lupaavat, eika kumpikaan pinta tietaisi siita. Julkaisutarkistaja
    loysi taman 16.8."""
    monkeypatch.setenv("FREE_PREMIUM_UNTIL", "2099-01-01T00:00:00+00:00")
    assert prem.free_premium_window_end() == datetime(
        2026, 9, 12, 12, 30, tzinfo=timezone.utc), "env ei saa siirtaa paivaa"
    monkeypatch.setenv("FREE_PREMIUM_UNTIL", "ensi viikolla")
    assert prem.free_premium_window_end() == datetime(
        2026, 9, 12, 12, 30, tzinfo=timezone.utc), "roska ei saa siirtaa paivaa"


# --- portti ---------------------------------------------------------------

def _enforce_on(monkeypatch):
    monkeypatch.setenv("PREMIUM_ENFORCE", "on")
    monkeypatch.setenv("SUPABASE_URL", "https://example.test")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "svc")


def test_signed_in_user_is_premium_during_window(monkeypatch):
    _enforce_on(monkeypatch)
    monkeypatch.delenv("FREE_PREMIUM_UNTIL", raising=False)
    monkeypatch.setattr(prem, "_verify_token_user_id", lambda t: "user-1")

    # 🔴 Stubit palauttavat False, EIVAT heita. Ensimmainen versio nostti
    # AssertionErrorin todistaakseen ettei Supabasea kysyta — mutta portin
    # fail-open nappaa jokaisen poikkeuksen ja palauttaa True, joten testi
    # lapaisi myos kun ikkunahaara oli mutatoitu pois. Se mittasi eri
    # koodipolkua kuin luuli. Nyt todiste on kutsulaskuri.
    calls = {"n": 0}

    def _no(*a, **k):
        calls["n"] += 1
        return False

    monkeypatch.setattr(prem, "_profile_is_premium", _no)
    monkeypatch.setattr(prem, "_web_subscription_active", _no)
    assert prem.is_premium_request(_Req()) is True
    assert calls["n"] == 0, "ikkunan ei pida kysya Supabaselta premiumia"


def test_anonymous_caller_is_not_premium_during_window(monkeypatch):
    """Ikkuna koskee kirjautuneita. Anonyymi API-kutsuja ei saa premiumia
    edes ikkunan aikana — muuten payload vuotaisi ilman yhtaan kontaktia."""
    _enforce_on(monkeypatch)
    monkeypatch.delenv("FREE_PREMIUM_UNTIL", raising=False)
    assert prem.is_premium_request(_Req(token=None)) is False


def test_invalid_token_is_not_premium_during_window(monkeypatch):
    _enforce_on(monkeypatch)
    monkeypatch.delenv("FREE_PREMIUM_UNTIL", raising=False)
    monkeypatch.setattr(prem, "_verify_token_user_id", lambda t: None)
    assert prem.is_premium_request(_Req()) is False


def test_after_window_normal_gate_decides(monkeypatch):
    """Negatiivinen kontrolli: ikkunan sulkeuduttua portti palaa ennalleen."""
    _enforce_on(monkeypatch)
    monkeypatch.setenv("FREE_PREMIUM_UNTIL", "off")
    monkeypatch.setattr(prem, "_verify_token_user_id", lambda t: "user-1")
    monkeypatch.setattr(prem, "_profile_is_premium", lambda uid: False)
    monkeypatch.setattr(prem, "_web_subscription_active", lambda uid: False)
    assert prem.is_premium_request(_Req()) is False

    monkeypatch.setattr(prem, "_profile_is_premium", lambda uid: True)
    with prem._PREMIUM_CACHE_LOCK:
        prem._PREMIUM_CACHE.clear()
    assert prem.is_premium_request(_Req()) is True


# --- 🔴 se mika ei saa tapahtua -------------------------------------------

def test_window_never_writes_is_premium():
    """Ikkuna on VAIN LUKUOPERAATIO. Jos joku joskus kytkee sen
    profiilikirjoitukseen, kayttajasta tulee PYSYVA premium: mitaan
    webhookia ei synny (tilausta ei ole) eika mikaan koodipolku lue
    vanhentumispaivaa. Portti lukee lahdekoodia, koska juuri se on se
    muutos jota vastaan halutaan suojautua."""
    import inspect

    src = inspect.getsource(prem)
    start = src.index("def free_premium_window_end")
    end = src.index("def _supabase_headers") if "_supabase_headers" in src \
        else src.index("def is_premium_request")
    window_src = src[start:end]
    for forbidden in ("is_premium\":", "'is_premium'", "patch(", "PATCH",
                      "_update_profile"):
        assert forbidden not in window_src, (
            f"ikkunakoodi ei saa kirjoittaa profiiliin: loytyi {forbidden!r}")
