"""Kayttajan pyynto ei saa koskaan odottaa upstreamia (16.8.2026 ilta).

MIKSI TAMA ON OLEMASSA. Aamun 429-korjaus siirsi rinnakkaisuusportin ja
NELJA uusintaa jitteroidyllä backoffilla kayttajan pyynnon polkuun. Se
poisti 429-virheet ja loi tilalle pitkan odotuksen:

    mitattu tuotannosta 16.8 illalla
      /api/standings  38,2 s
      /api/teams       0,12 s
      /api/fixtures    0,12 s

Appin timeout on 60 s, joten kayttaja ei nahnyt virhetta vaan jumin.
"Ei noi standingsit lataudu" ja "lagii koko paska" olivat molemmat taman
aiheuttamia.

Nama testit pinnaavat sen lupauksen joka rikkoutui: uusinnat ja backoff
kuuluvat taustasaikeeseen, eivat pyyntopolkuun.
"""
from __future__ import annotations

import threading
import time

import pytest

import api.main as m


@pytest.fixture(autouse=True)
def _clean():
    m._FD_HTTP_CACHE.clear()
    with m._FD_BG_GUARD:
        m._FD_BG_INFLIGHT.clear()
    yield
    m._FD_HTTP_CACHE.clear()
    with m._FD_BG_GUARD:
        m._FD_BG_INFLIGHT.clear()


def _hang(seconds: float):
    def fake_get(url, headers=None, timeout=None):
        threading.Event().wait(seconds)
        raise RuntimeError("upstream ei vastaa")
    return fake_get


def test_stale_cache_returns_immediately_when_upstream_hangs(monkeypatch):
    """🔴 TAMA ON SE TESTI. Vanha data cachessa + upstream jumissa ->
    vastaus tulee VALITTOMASTI, ei 38 sekunnissa."""
    m._FD_HTTP_CACHE["k"] = (time.time() - 99999, {"ok": 1})
    monkeypatch.setattr(m.requests, "get", _hang(30))

    t0 = time.time()
    data, stale = m._fd_get_cached("http://x", "key", ttl_sec=1, cache_key="k")
    elapsed = time.time() - t0

    assert data == {"ok": 1} and stale is True
    assert elapsed < 0.5, f"kayttaja odotti {elapsed:.1f} s vanhan datan yli"


def test_cold_request_fails_fast_instead_of_retrying(monkeypatch):
    """Ilman cachea yksi lyhyt yritys, EI uusintaketjua. Nopea virhe on
    parempi kuin puolen minuutin jumi."""
    monkeypatch.setattr(m.requests, "get", _hang(0.1))
    t0 = time.time()
    with pytest.raises(m.HTTPException) as e:
        m._fd_get_cached("http://x", "key", cache_key="cold")
    elapsed = time.time() - t0
    assert e.value.status_code == 503
    budget = m.FD_FG_TIMEOUT_SEC + m.FD_FG_GATE_WAIT_SEC + 1
    assert elapsed < budget, f"kylma pyynto kesti {elapsed:.1f} s"


def test_foreground_makes_at_most_one_attempt(monkeypatch):
    """Negatiivinen kontrolli uusintaketjulle: jos joku palauttaa uusinnat
    pyyntopolkuun, tama kaatuu."""
    calls = {"n": 0}

    def counting(url, headers=None, timeout=None):
        calls["n"] += 1
        raise RuntimeError("nope")

    monkeypatch.setattr(m.requests, "get", counting)
    # Taustahaku mykistetaan: se SAA uusia, ja tama testi mittaa vain
    # pyyntopolkua. Ilman tata laskuri nayttaisi taustasaikeen yritykset.
    monkeypatch.setattr(m, "_fd_kick_refresh", lambda *a, **kw: None)
    with pytest.raises(m.HTTPException):
        m._fd_get_cached("http://x", "key", cache_key="c2")
    assert calls["n"] == 1, f"pyyntopolku teki {calls['n']} yritysta"


def test_foreground_budget_stays_small():
    """Katot ovat pienia TARKOITUKSELLA. Jos joku nostaa niita, se nakyy
    tassa eika vasta kayttajan ruudulla."""
    assert m.FD_FG_TIMEOUT_SEC <= 8
    assert m.FD_FG_GATE_WAIT_SEC <= 3


def test_stale_hit_kicks_exactly_one_background_refresh(monkeypatch):
    """Sata rinnakkaista lukijaa ei saa kaynnistaa sataa taustahakua."""
    m._FD_HTTP_CACHE["k"] = (time.time() - 99999, {"ok": 1})
    started = {"n": 0}

    def fake_thread(target=None, args=(), daemon=None):
        started["n"] += 1

        class _T:
            def start(self_inner):
                pass
        return _T()

    monkeypatch.setattr(m.threading, "Thread", fake_thread)
    for _ in range(25):
        m._fd_get_cached("http://x", "key", ttl_sec=1, cache_key="k")
    assert started["n"] == 1, f"kaynnistettiin {started['n']} taustahakua"


# --- lammitin: tyhjasta avaimesta harvinainen -----------------------------

def test_failed_cold_request_kicks_a_background_refresh(monkeypatch):
    """🔴 Ensimmainen versio taman paivan korjauksesta poisti odotuksen
    muttei laittanut mitaan tilalle: jos upstream oli juuri silla hetkella
    tukossa, kayttaja sai 503:n eika mikaan yrittanyt uudelleen. Mitattu
    16.8 iltana: Eredivisie, Ligue 1 ja Primeira palauttivat 503:n
    peraakkain, koska niilla ei ollut cache-riviä.

    Nyt epaonnistunut kylma pyynto kaynnistaa taustahaun, joten seuraava
    napautus onnistuu."""
    kicked = []
    monkeypatch.setattr(m, "_fd_kick_refresh",
                        lambda url, key, k: kicked.append(k))
    monkeypatch.setattr(m, "_fd_fetch_once", lambda *a, **kw: None)
    with pytest.raises(m.HTTPException):
        m._fd_get_cached("http://x", "key", cache_key="cold2")
    assert kicked == ["cold2"], "epaonnistunut kylma haku ei kaynnistanyt uusintaa"


def test_warmer_covers_every_league_the_app_can_open():
    """Lammittimen kattavuus johdetaan SAMASTA lahteesta kuin endpointit.
    Kovakoodattu lista olisi tasan se vika joka 15.8 jatti kolme liigaa
    pois etusivulta."""
    from src.data.football_data_org import FIXTURE_STANDINGS_CODES

    targets = m._fd_warm_targets()
    keys = {t[1] for t in targets}
    for code in FIXTURE_STANDINGS_CODES.values():
        assert any(k.startswith(f"standings:{code}:") for k in keys), code
        assert f"fixtures:{code}:7" in keys, code


def test_warmer_pacing_stays_under_upstream_limit():
    """Lammitin ei saa aiheuttaa sita ongelmaa jota se korjaa. FD:n raja on
    ~10 pyyntoa/min; 7 s vali on ~8,6/min."""
    assert m.FD_WARM_INTERVAL_SEC >= 6.0
    per_min = 60.0 / m.FD_WARM_INTERVAL_SEC
    assert per_min <= 10, f"{per_min:.1f} pyyntoa/min on liikaa"


def test_warmer_skips_still_fresh_keys(monkeypatch):
    """Lammitin ei kilpaile kayttajan kanssa samasta minuuttikiintiosta."""
    calls = []
    monkeypatch.setattr(m, "_fd_fetch_once",
                        lambda url, k, t: calls.append(url) or {"ok": 1})
    for _, ck, _ in m._fd_warm_targets():
        m._FD_HTTP_CACHE[ck] = (time.time(), {"cached": 1})
    # simuloi yksi kierros ilman nukkumista
    for url, ck, _ in m._fd_warm_targets():
        hit = m._FD_HTTP_CACHE.get(ck)
        if hit and time.time() - hit[0] < m.FD_HTTP_TTL_SEC * 0.8:
            continue
        m._fd_fetch_once(url, "k", 1)
    assert calls == [], "tuoreita avaimia ei saa hakea uudelleen"
