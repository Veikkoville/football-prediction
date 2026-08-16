"""Luojan oma nakyma omiin lukuihinsa (16.8.2026).

Wolfy kysyi 16.8: "how would i know if someone has come from me or not? Will
it show on my account?" Vastaus oli EI. `GET /api/creator/report` on se
vastaus, ja siina on kaksi asiaa jotka voivat menna pieleen hiljaa:

  1. LUOJA NAKEE TOISEN LUOJAN LUVUT. Admin-raportti palauttaa kaikki koodit
     yhtena karttana, ja jos luojanakyma rakennettaisiin sen paalle
     unohtamalla rajaus, vika ei nakyisi kehityksessa lainkaan — meilla on
     kolme luojaa joilla kaikilla on nolla. Se paljastuisi vasta kun luvut
     alkavat liikkua, eli tasan silloin kun ne ovat luottamuksellisia.

  2. NOLLA ESITETAAN MITTAUKSENA. Jos Supabase-haku kaatuu, laskuri on 0.
     Luojalle "0 signups" tarkoittaa "kukaan ei tullut linkistasi" — se on
     eri vaite kuin "emme saaneet lukua luettua", ja se on vaite jonka
     nojalla luoja lopettaa linkin jakamisen.

Kolmas portti on paasyn ehto: `creator_code` on ERI kentta kuin `ref`. Sama
ihminen voi olla molempia (luoja joka itse tuli toisen luojan linkista), ja
`ref`in lukeminen paasyoikeutena antaisi hanelle toisen luojan luvut.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import api.main as m

SUPA = "https://supa.test"
KEY = "service-role-key"


class _Resp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status
        self.text = str(payload)

    def json(self):
        return self._payload


class _Subs:
    def __init__(self, rows):
        self._rows = rows

    def auto_paging_iter(self):
        return iter(self._rows)


def _sub(code, status="active"):
    return {"metadata": {"affiliate": code}, "status": status}


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    """Cache on prosessitason tila: ilman tyhjennysta yksi testi syottaisi
    lukunsa seuraavalle."""
    m._AFFILIATE_TALLY_CACHE.clear()
    monkeypatch.setattr(m, "SUPABASE_URL", SUPA)
    monkeypatch.setattr(m, "SUPABASE_SERVICE_ROLE_KEY", KEY)
    yield
    m._AFFILIATE_TALLY_CACHE.clear()


def _wire(monkeypatch, *, users, tokens, subs=(), supabase_fails=False,
          supabase_status=200, stripe_fails=False):
    """Yksi valefiksaus koko polulle: token-verify, tilihaku ja listaus.

    Testit ajavat oikean koodipolun (`_verify_supabase_token` ->
    `_account_creator_code` -> `_affiliate_tally`) eivatka monkeypatchaa
    endpointin omia apureita — muuten rajaus voisi olla rikki juuri siina
    kohdassa jota testi ei aja.
    """
    def fake_get(url, params=None, headers=None, timeout=None):
        auth = (headers or {}).get("Authorization", "")
        if url.endswith("/auth/v1/user"):
            token = auth.replace("Bearer ", "")
            uid = tokens.get(token)
            return _Resp({"id": uid} if uid else {}, 200 if uid else 401)
        if "/auth/v1/admin/users/" in url:
            uid = url.rsplit("/", 1)[-1]
            hit = next((u for u in users if u["id"] == uid), None)
            return _Resp(hit or {}, 200 if hit else 404)
        if url.endswith("/auth/v1/admin/users"):
            if supabase_fails:
                raise RuntimeError("supabase down")
            if supabase_status != 200:
                # 🔴 Toinen virhemuoto kuin poikkeus, ja se oli se rikki
                # oleva: Supabase vastaa 401/429/500 ilman etta requests
                # heittaa mitaan.
                return _Resp({"msg": "nope"}, supabase_status)
            page = (params or {}).get("page", 1)
            return _Resp({"users": users if page == 1 else []})
        raise AssertionError(f"odottamaton URL: {url}")

    class _Stripe:
        @staticmethod
        def list(**kw):
            if stripe_fails:
                raise RuntimeError("stripe down")
            return _Subs(list(subs))

    monkeypatch.setattr(m.requests, "get", fake_get)
    monkeypatch.setattr(m.stripe, "Subscription", _Stripe)
    return TestClient(m.app)


WOLFY = {"id": "u-wolfy", "email": "wolfy@example.com",
         "user_metadata": {"creator_code": "WOLFY"}}
DAZ = {"id": "u-daz", "email": "daz@example.com",
       "user_metadata": {"creator_code": "DAZ"}}
FAN_W = {"id": "u-f1", "email": "f1@example.com",
         "user_metadata": {"ref": "WOLFY"}}
FAN_D1 = {"id": "u-f2", "email": "f2@example.com",
          "user_metadata": {"ref": "DAZ"}}
FAN_D2 = {"id": "u-f3", "email": "f3@example.com",
          "user_metadata": {"ref": "DAZ"}}
TOKENS = {"tok-wolfy": "u-wolfy", "tok-daz": "u-daz", "tok-plain": "u-f1"}
ALL_USERS = [WOLFY, DAZ, FAN_W, FAN_D1, FAN_D2]


def _get(client, token=None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return client.get("/api/creator/report", headers=headers)


# ---------------------------------------------------------------------------
# Paasy
# ---------------------------------------------------------------------------

def test_anonymous_gets_401(monkeypatch):
    c = _wire(monkeypatch, users=ALL_USERS, tokens=TOKENS)
    assert _get(c).status_code == 401


def test_invalid_token_gets_401(monkeypatch):
    c = _wire(monkeypatch, users=ALL_USERS, tokens=TOKENS)
    assert _get(c, "tok-forged").status_code == 401


def test_ordinary_account_is_not_a_creator(monkeypatch):
    """🔴 Paasyn ehto on `creator_code`, EI `ref`.

    u-f1 on tavallinen kayttaja joka tuli WOLFYn linkista. Jos paasy
    luettaisiin `ref`ista, han nakisi Wolfyn provisioluvut.
    """
    c = _wire(monkeypatch, users=ALL_USERS, tokens=TOKENS)
    r = _get(c, "tok-plain")
    assert r.status_code == 403
    assert "WOLFY" not in r.text


# ---------------------------------------------------------------------------
# Rajaus
# ---------------------------------------------------------------------------

def test_creator_sees_only_own_numbers(monkeypatch):
    """Dazilla on kaksi signupia ja yksi leimattu tilaus. Kumpikaan luku ei
    saa esiintya Wolfyn vastauksessa missaan muodossa."""
    c = _wire(monkeypatch, users=ALL_USERS, tokens=TOKENS,
              subs=[_sub("DAZ"), _sub("WOLFY"), _sub("WOLFY", "canceled")])
    r = _get(c, "tok-wolfy")
    assert r.status_code == 200
    d = r.json()
    assert d["code"] == "WOLFY"
    assert d["signups"] == 1
    assert d["stamped"] == 2
    assert d["statuses"] == {"active": 1, "canceled": 1}
    assert "DAZ" not in r.text, "toisen luojan koodi vuoti vastaukseen"


def test_each_creator_gets_their_own_row(monkeypatch):
    c = _wire(monkeypatch, users=ALL_USERS, tokens=TOKENS,
              subs=[_sub("DAZ")])
    daz = _get(c, "tok-daz").json()
    assert (daz["code"], daz["signups"], daz["stamped"]) == ("DAZ", 2, 1)
    wolfy = _get(c, "tok-wolfy").json()
    assert (wolfy["code"], wolfy["signups"], wolfy["stamped"]) == ("WOLFY", 1, 0)


def test_unused_code_reports_zero_and_not_an_error(monkeypatch):
    """Nolla on oikea vastaus kun koodi on olemassa muttei kayttoa. Se ei saa
    olla 404 eika null — luoja tarvitsee eron "ei ketaan" ja "ei tietoa"
    valilla, ja tama on se ensimmainen."""
    c = _wire(monkeypatch, users=[WOLFY], tokens=TOKENS)
    d = _get(c, "tok-wolfy").json()
    assert d["signups"] == 0 and d["stamped"] == 0


def test_tally_only_filter_does_not_leak(monkeypatch):
    _wire(monkeypatch, users=ALL_USERS, tokens=TOKENS, subs=[_sub("DAZ")])
    t = m._affiliate_tally(only="WOLFY")
    assert set(t["codes"]) == {"WOLFY"}


# ---------------------------------------------------------------------------
# Nolla vs "ei tietoa"
# ---------------------------------------------------------------------------

def test_supabase_failure_reports_null_not_zero(monkeypatch):
    """🔴 Tama on se testi jonka takia tiedosto on olemassa.

    Kaatunut haku antaa laskurille arvon 0. Nakymassa se lukee
    "0 sign-ups", eli vaite "kukaan ei tullut linkistasi" — mika on eri asia
    kuin totuus "emme saaneet lukua luettua".
    """
    c = _wire(monkeypatch, users=ALL_USERS, tokens=TOKENS,
              subs=[_sub("WOLFY")], supabase_fails=True)
    d = _get(c, "tok-wolfy").json()
    assert d["signups"] is None
    assert d["sources_ok"]["supabase"] is False
    # Stripe-puoli toimii yha, eika sita saa piilottaa Supabasen mukana.
    assert d["stamped"] == 1


@pytest.mark.parametrize("status", [401, 429, 500])
def test_supabase_http_error_also_reports_null(monkeypatch, status):
    """🔴 Julkaisutarkistaja loysi taman 16.8, ja se oli oikeassa.

    Ensimmainen versio nosti `supa_ok = True` sivutussilmukan JALKEEN, ja
    non-200 poistui silmukasta `break`illa - eli avaimen rotaatio tai 429
    tuotti "signups: 0, supabase: true". Poikkeuspolku oli testattu ja tama
    ei, vaikka tama on se muoto jossa Supabase oikeasti epaonnistuu:
    HTTP-vastaus tulee perille eika `requests` heita mitaan.
    """
    c = _wire(monkeypatch, users=ALL_USERS, tokens=TOKENS,
              subs=[_sub("WOLFY")], supabase_status=status)
    d = _get(c, "tok-wolfy").json()
    assert d["signups"] is None, f"HTTP {status} raportoitiin nollana"
    assert d["sources_ok"]["supabase"] is False


def test_pagination_cap_is_not_a_number(monkeypatch):
    """Jos tililista jatkuu yli sivutuskaton, luku on vaillinainen. Sekin on
    "ei tietoa" eika pienempi luku."""
    def endless(url, params=None, headers=None, timeout=None):
        if url.endswith("/auth/v1/user"):
            return _Resp({"id": "u-wolfy"})
        if "/auth/v1/admin/users/" in url:
            return _Resp(WOLFY)
        return _Resp({"users": [dict(FAN_W, id=f"u-{(params or {}).get('page')}-{i}")
                                for i in range(200)]})
    monkeypatch.setattr(m.requests, "get", endless)
    monkeypatch.setattr(m.stripe, "Subscription",
                        type("S", (), {"list": staticmethod(
                            lambda **kw: _Subs([]))}))
    d = _get(TestClient(m.app), "tok-wolfy").json()
    assert d["signups"] is None
    assert d["sources_ok"]["supabase"] is False


def test_stripe_failure_reports_null_stamped(monkeypatch):
    c = _wire(monkeypatch, users=ALL_USERS, tokens=TOKENS, stripe_fails=True)
    d = _get(c, "tok-wolfy").json()
    assert d["stamped"] is None
    assert d["statuses"] is None
    assert d["signups"] == 1


def test_failed_read_is_not_cached(monkeypatch):
    """Cache jaadyttaisi virhetilan 60 sekunniksi. Luoja paivittaa sivun ja
    saa saman vaaran nollan uudelleen, mika nayttaa vahvistukselta."""
    c = _wire(monkeypatch, users=ALL_USERS, tokens=TOKENS,
              supabase_fails=True)
    assert _get(c, "tok-wolfy").json()["signups"] is None
    c2 = _wire(monkeypatch, users=ALL_USERS, tokens=TOKENS)
    assert _get(c2, "tok-wolfy").json()["signups"] == 1


def test_payload_carries_the_floor_caveat_and_window(monkeypatch):
    """`signups` on alaraja eika mittaus, ja sen on sanottava se itse: nakyma
    lukee taman kentan eika toista sanamuotoa omassa koodissaan."""
    c = _wire(monkeypatch, users=ALL_USERS, tokens=TOKENS)
    d = _get(c, "tok-wolfy").json()
    assert "floor" in d["caveat"]
    assert d["commission_pct"] == 30
    assert d["free_window"]["ends_utc"] == m.FREE_PREMIUM_UNTIL_DEFAULT


def test_no_customer_identities_in_payload(monkeypatch):
    """Luojalle summat, ei ihmisia. Sahkoposti tai user-id vastauksessa olisi
    kolmannelle osapuolelle luovutettua henkilotietoa."""
    c = _wire(monkeypatch, users=ALL_USERS, tokens=TOKENS,
              subs=[_sub("WOLFY")])
    body = _get(c, "tok-wolfy").text
    for u in ALL_USERS:
        assert u["email"] not in body
        assert u["id"] not in body


# ---------------------------------------------------------------------------
# Koodin kytkeminen tiliin (admin)
# ---------------------------------------------------------------------------

def _wire_admin(monkeypatch, users, put_sink):
    def fake_get(url, params=None, headers=None, timeout=None):
        if url.endswith("/auth/v1/admin/users"):
            page = (params or {}).get("page", 1)
            return _Resp({"users": users if page == 1 else []})
        raise AssertionError(f"odottamaton URL: {url}")

    def fake_put(url, json=None, headers=None, timeout=None):
        put_sink.append((url, json))
        return _Resp({"id": url.rsplit("/", 1)[-1]})

    monkeypatch.setattr(m.requests, "get", fake_get)
    monkeypatch.setattr(m.requests, "put", fake_put)
    monkeypatch.setenv("ADMIN_TOKEN", "adm")
    return TestClient(m.app)


def test_creator_code_requires_admin_token(monkeypatch):
    c = _wire_admin(monkeypatch, [WOLFY], [])
    r = c.post("/api/admin/creator-code",
               json={"email": "wolfy@example.com", "code": "WOLFY"})
    assert r.status_code == 403


def test_setting_creator_code_preserves_existing_ref(monkeypatch):
    """🔴 Read-modify-write, ei ylikirjoitus.

    Luoja on usein itse tullut jonkun linkista. `{"creator_code": X}`
    -kirjoitus pudottaisi `ref`in, eli tekisi hanesta luojan ja poistaisi
    samalla han oman attribuutionsa toiselta luojalta.
    """
    both = {"id": "u-x", "email": "x@example.com",
            "user_metadata": {"ref": "DAZ", "locale": "en"}}
    sink: list = []
    c = _wire_admin(monkeypatch, [both], sink)
    r = c.post("/api/admin/creator-code",
               headers={"X-Admin-Token": "adm"},
               json={"email": "X@Example.com", "code": "rowan"})
    assert r.status_code == 200, r.text
    _, body = sink[0]
    assert body["user_metadata"] == {
        "ref": "DAZ", "locale": "en", "creator_code": "ROWAN"}
    assert r.json()["creator_code"] == "ROWAN"


def test_unknown_email_is_404_not_a_silent_success(monkeypatch):
    sink: list = []
    c = _wire_admin(monkeypatch, [WOLFY], sink)
    r = c.post("/api/admin/creator-code",
               headers={"X-Admin-Token": "adm"},
               json={"email": "nobody@example.com", "code": "NOBODY"})
    assert r.status_code == 404
    assert sink == [], "tuntemattomalle emailille kirjoitettiin silti"


def test_invalid_code_is_rejected(monkeypatch):
    sink: list = []
    c = _wire_admin(monkeypatch, [WOLFY], sink)
    r = c.post("/api/admin/creator-code",
               headers={"X-Admin-Token": "adm"},
               json={"email": "wolfy@example.com", "code": "no spaces!"})
    assert r.status_code == 400
    assert sink == []


def test_empty_code_detaches(monkeypatch):
    sink: list = []
    c = _wire_admin(monkeypatch, [WOLFY], sink)
    r = c.post("/api/admin/creator-code",
               headers={"X-Admin-Token": "adm"},
               json={"email": "wolfy@example.com", "code": None})
    assert r.status_code == 200
    _, body = sink[0]
    assert "creator_code" not in body["user_metadata"]
