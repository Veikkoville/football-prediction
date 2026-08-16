"""Luojan linkista tullut tili -> ostiko han myohemmin (16.8.2026).

Villen kysymys: *"onko meilla myos seuranta siita kuinka moni on dazin
wolfyn tai rowanin linkin kautta tehneet free tilin -> ostaneet sitte
premiumin myohemmin"*.

🔴 MIKSI TAMA EI OLE `affiliate-report`. Siella `signups` ja `stamped` ovat
kaksi ERI POPULAATIOTA eivatka sama joukko kahdessa vaiheessa:

  signups = tilit joiden `raw_user_meta_data.ref` on koodi
  stamped = Stripe-tilaukset joiden `metadata.affiliate` on koodi

Lukija joka nappaili koodin checkoutissa ilman etta ref-tagia koskaan
kirjoitettiin selaimeen on `stamped`issa muttei `signups`issa. Naiden
jakaminen keskenaan antaisi konversioprosentin joka ei tarkoita mitaan, ja
se olisi juuri se luku jonka nojalla ikkunasta paatettaisiin 12.9.

🔴 STORE-OSTOT ERIKSEEN, JA SE ON RAHAA. Luojan provisio maksetaan vain
sivulla tehdyista ostoista: store-ostot eivat kulje meidan checkoutimme
kautta eika niissa ole mitaan mista attribuution voisi lukea. Samaan lukuun
niputettuna raportti nayttaisi luojalle tuloa jota han ei saa.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import api.main as m


class _Resp:
    def __init__(self, payload, status=200):
        self._p, self.status_code, self.text = payload, status, str(payload)

    def json(self):
        return self._p


def _user(uid, ref=None):
    return {"id": uid, "email": f"{uid}@example.com",
            "user_metadata": ({"ref": ref} if ref else {})}


def _wire(monkeypatch, users, web_subs=(), premium_ids=(),
          users_status=200, subs_status=200, prof_status=200):
    monkeypatch.setattr(m, "SUPABASE_URL", "https://supa.test")
    monkeypatch.setattr(m, "SUPABASE_SERVICE_ROLE_KEY", "key")
    monkeypatch.setenv("ADMIN_TOKEN", "adm")

    def fake_get(url, params=None, headers=None, timeout=None):
        if "/auth/v1/admin/users" in url:
            if users_status != 200:
                return _Resp({}, users_status)
            page = (params or {}).get("page", 1)
            return _Resp({"users": users if page == 1 else []})
        if "/rest/v1/web_subscriptions" in url:
            if subs_status != 200:
                return _Resp({}, subs_status)
            asked = url.split("in.(")[1].split(")")[0].split(",")
            return _Resp([{"user_id": u, "status": "active"}
                          for u in web_subs if u in asked])
        if "/rest/v1/profiles" in url:
            if prof_status != 200:
                return _Resp({}, prof_status)
            asked = url.split("in.(")[1].split(")")[0].split(",")
            return _Resp([{"id": u} for u in premium_ids if u in asked])
        raise AssertionError(f"odottamaton URL: {url}")

    monkeypatch.setattr(m.requests, "get", fake_get)
    return TestClient(m.app)


def _get(c):
    return c.get("/api/admin/affiliate-cohort", headers={"X-Admin-Token": "adm"})


def test_requires_admin(monkeypatch):
    c = _wire(monkeypatch, [])
    assert c.get("/api/admin/affiliate-cohort").status_code == 403


def test_counts_the_chain_per_code(monkeypatch):
    users = [_user("a", "WOLFY"), _user("b", "WOLFY"), _user("c", "WOLFY"),
             _user("d", "DAZ"), _user("e")]
    c = _wire(monkeypatch, users, web_subs=["a"], premium_ids=["a", "b"])
    d = _get(c).json()["codes"]
    assert d["WOLFY"]["signups"] == 3
    assert d["WOLFY"]["signups_paid_on_web"] == 1
    assert d["WOLFY"]["signups_paid_in_app_only"] == 1, (
        "b on premium ilman web-tilausta, eli store-osto")
    assert d["WOLFY"]["conversion_pct"] == 33.3
    assert d["DAZ"]["signups"] == 1 and d["DAZ"]["signups_paid_on_web"] == 0
    # Reffiton tili ei kuulu yhteenkaan koodiin. Mitataan summasta eika
    # merkkijonohausta: ensimmainen versio etsi kirjainta "e", joka osuu
    # sanaan "signups".
    assert sum(v["signups"] for v in d.values()) == 4


def test_conversion_counts_web_only(monkeypatch):
    """🔴 Store-osto EI ole luojalle maksettava, joten se ei saa nostaa
    konversiota. Jos se nostaisi, raportti lupaisi tuloa jota ei tule."""
    users = [_user("a", "DAZ"), _user("b", "DAZ")]
    c = _wire(monkeypatch, users, web_subs=[], premium_ids=["a", "b"])
    d = _get(c).json()["codes"]["DAZ"]
    assert d["signups_paid_in_app_only"] == 2
    assert d["conversion_pct"] == 0.0


def test_web_payer_is_not_double_counted_as_app(monkeypatch):
    """Web-tilaaja on yleensa MYOS profiles.is_premium (cross-platform).
    Ilman erotusta sama ihminen nakyisi molemmissa sarakkeissa."""
    users = [_user("a", "DAZ")]
    c = _wire(monkeypatch, users, web_subs=["a"], premium_ids=["a"])
    d = _get(c).json()["codes"]["DAZ"]
    assert (d["signups_paid_on_web"], d["signups_paid_in_app_only"]) == (1, 0)


@pytest.mark.parametrize("kw", [{"users_status": 500}, {"subs_status": 500},
                                {"prof_status": 500}])
def test_any_failed_source_is_503_not_zero(monkeypatch, kw):
    users = [_user("a", "DAZ")]
    r = _get(_wire(monkeypatch, users, **kw))
    assert r.status_code == 503
    assert "not zero" in r.json()["detail"]


def test_chunking_reads_every_account(monkeypatch):
    """🔴 PostgREST `in.()` menee URLiin, joten lista on pilkottava. Jos
    pilkkominen unohtuu tai lukee vain ensimmaisen palan, konversio jaa
    hiljaa liian pieneksi."""
    users = [_user(f"u{i}", "WOLFY") for i in range(250)]
    c = _wire(monkeypatch, users, web_subs=[f"u{i}" for i in range(250)])
    d = _get(c).json()["codes"]["WOLFY"]
    assert d["signups"] == 250
    assert d["signups_paid_on_web"] == 250, "osa tileista jai kysymatta"


def test_caveat_names_the_two_populations(monkeypatch):
    c = _wire(monkeypatch, [_user("a", "DAZ")])
    cav = _get(c).json()["caveat"]
    assert "not the same thing as the stamped" in cav
    assert "not payable" in cav
