"""Ilmaisikkunan seuranta (16.8.2026, Villen pyynto).

Ville: *"pystyta joku seuranta etta kuinka moni 'lunastaa' nyt free
premiumin"* — lainausmerkit olivat hanen omansa, ja ne ovat oikeassa:
ikkuna ei kirjoita mitaan. Se on puhdas lukuoperaatio kolmessa portissa
eika `is_premium`-lippua kaanneta, joten lunastusta ei ole olemassa
tapahtumana jota voisi laskea.

Mitattava asia on TILIN LUONTI, koska tilin tekeminen on ainoa asia jonka
premiumin saaminen taman ikkunan aikana vaatii.

🔴 KAKSI ASIAA JOTKA MENISIVAT HILJAA PIELEEN:

1. **Luku ilman vertailukohtaa.** "4 tilia tanaan" ei kerro mitaan jos
   normaali tahti on 1-3. Siksi vastauksessa on ikkunaa EDELTAVIEN 14
   vuorokauden mediaani, ja nollapaivat lasketaan siihen mukaan: niiden
   pudottaminen nostaisi vertailutasoa ja piilottaisi nousun.
2. **Epaonnistunut haku nollana.** Sama vikaluokka kuin luojaraportissa.
   Tyhja tililista nayttaisi silta etta ikkuna ei tuottanut ketaan.
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


def _user(created, last_sign_in=None, ref=None):
    u = {"id": f"u{created}{last_sign_in}", "created_at": created,
         "user_metadata": ({"ref": ref} if ref else {})}
    if last_sign_in:
        u["last_sign_in_at"] = last_sign_in
    return u


def _wire(monkeypatch, users, status=200, pages=None):
    monkeypatch.setattr(m, "SUPABASE_URL", "https://supa.test")
    monkeypatch.setattr(m, "SUPABASE_SERVICE_ROLE_KEY", "key")
    monkeypatch.setenv("ADMIN_TOKEN", "adm")

    def fake_get(url, params=None, headers=None, timeout=None):
        if status != 200:
            return _Resp({"msg": "nope"}, status)
        page = (params or {}).get("page", 1)
        if pages is not None:
            return _Resp({"users": pages.get(page, [])})
        return _Resp({"users": users if page == 1 else []})

    monkeypatch.setattr(m.requests, "get", fake_get)
    return TestClient(m.app)


def _get(client):
    return client.get("/api/admin/free-window-report",
                      headers={"X-Admin-Token": "adm"})


def test_requires_admin_token(monkeypatch):
    c = _wire(monkeypatch, [])
    assert c.get("/api/admin/free-window-report").status_code == 403


def test_counts_accounts_since_the_window_opened(monkeypatch):
    users = [
        _user("2026-08-14T10:00:00Z"),
        _user("2026-08-15T10:00:00Z"),
        _user("2026-08-16T10:00:00Z"),
        _user("2026-08-16T18:00:00Z", last_sign_in="2026-08-16T20:00:00Z"),
        _user("2026-08-17T09:00:00Z", ref="WOLFY"),
    ]
    d = _get(_wire(monkeypatch, users)).json()
    assert d["total_accounts"] == 5
    assert d["accounts_since_window"] == 3
    assert d["returned_since_window"] == 1
    assert d["with_creator_ref"] == 1
    assert d["window"]["opened"] == "2026-08-16"


def test_baseline_counts_the_quiet_days(monkeypatch):
    """🔴 Jos nollapaivat pudotetaan, vertailutaso nousee ja nousu katoaa.

    Kaksi tilia 14 vuorokauden ikkunassa: mediaani on 0, ei 1.
    """
    users = [_user("2026-08-10T10:00:00Z"), _user("2026-08-11T10:00:00Z")]
    d = _get(_wire(monkeypatch, users)).json()
    assert d["baseline_per_day_before_window"] == 0


def test_baseline_is_a_median_of_the_days_before_only(monkeypatch):
    """Ikkunan aikaiset paivat eivat saa nostaa omaa vertailutasoaan."""
    users = ([_user(f"2026-08-{d:02d}T10:00:00Z") for d in range(2, 16)]
             + [_user("2026-08-16T10:00:00Z") for _ in range(50)])
    d = _get(_wire(monkeypatch, users)).json()
    assert d["baseline_per_day_before_window"] == 1, (
        "ikkunan 50 tilia vuotivat vertailutasoon")
    assert d["accounts_since_window"] == 50


@pytest.mark.parametrize("status", [401, 429, 500])
def test_failed_read_is_503_and_not_zero(monkeypatch, status):
    """Tyhja tililista nayttaisi silta etta ikkuna ei tuottanut ketaan."""
    r = _get(_wire(monkeypatch, [], status=status))
    assert r.status_code == 503
    assert "not zero" in r.json()["detail"]


def test_pagination_cap_is_not_a_smaller_number(monkeypatch):
    """Vaillinainen luku on 'ei tietoa' eika pienempi luku."""
    full = {p: [_user(f"2026-08-0{(p % 9) + 1}T10:00:00Z") for _ in range(200)]
            for p in range(1, 45)}
    assert _get(_wire(monkeypatch, [], pages=full)).status_code == 503


def test_second_page_is_read(monkeypatch):
    """Sivutus on se kohta jossa luku jaa hiljaa liian pieneksi."""
    pages = {1: [_user("2026-08-16T10:00:00Z") for _ in range(200)],
             2: [_user("2026-08-16T11:00:00Z") for _ in range(5)]}
    d = _get(_wire(monkeypatch, [], pages=pages)).json()
    assert d["total_accounts"] == 205


def test_caveat_says_what_is_not_measured(monkeypatch):
    """Luku on tilin luonti eika premium-nakyman avaus, ja vastauksen on
    sanottava se itse: se lahtee eteenpain ilman tata koodia."""
    d = _get(_wire(monkeypatch, [_user("2026-08-16T10:00:00Z")])).json()
    assert "no claim event" in d["caveat"]
    assert "proxy" in d["caveat"]
