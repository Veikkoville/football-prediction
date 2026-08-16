"""#49 standings/fixtures 429-kovennus: TTL-cache, backoff, stale-fallback.

Hermeettinen: requests.get mockataan api.main-namespacessa; FD-avain feikataan.
"""
from __future__ import annotations

import pytest

import api.main as m


def _row(pos=1, name="Arsenal"):
    return {"position": pos, "team": {"name": name, "shortName": name[:3],
                                      "crest": None},
            "playedGames": 1, "won": 1, "draw": 0, "lost": 0,
            "goalsFor": 2, "goalsAgainst": 0, "goalDifference": 2, "points": 3}


STANDINGS_BODY = {"standings": [{"type": "TOTAL", "table": [_row()]}]}
FIXTURES_BODY = {"matches": [{"utcDate": "2026-08-21T19:00:00Z",
                              "homeTeam": {"name": "Arsenal", "shortName": "ARS"},
                              "awayTeam": {"name": "Coventry", "shortName": "COV"},
                              "matchday": 1}]}


class _Resp:
    def __init__(self, status, body=None, text=""):
        self.status_code = status
        self._body = body or {}
        self.text = text

    def json(self):
        return self._body


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    m._FD_HTTP_CACHE.clear()
    m._FD_HTTP_LOCKS.clear()
    import src.data.football_data_org as fdo
    monkeypatch.setattr(fdo, "_api_key", lambda: "test-key")
    monkeypatch.setattr(m.time, "sleep", lambda s: None)  # backoff heti
    yield
    m._FD_HTTP_CACHE.clear()
    m._FD_HTTP_LOCKS.clear()


def _mock_get(monkeypatch, responses):
    """responses: lista _Resp per FD-kutsu (kulutetaan järjestyksessä);
    viimeinen jää voimaan. Palauttaa kutsulaskurin."""
    calls = {"n": 0}

    def fake_get(url, headers=None, timeout=None):
        calls["n"] += 1
        i = min(calls["n"] - 1, len(responses) - 1)
        return responses[i]

    monkeypatch.setattr(m.requests, "get", fake_get)
    return calls


def test_standings_cached_second_call_no_upstream(client, monkeypatch):
    calls = _mock_get(monkeypatch, [_Resp(200, STANDINGS_BODY)])
    r1 = client.get("/api/standings?league=ENG-Premier League-FD")
    r2 = client.get("/api/standings?league=ENG-Premier League-FD")
    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.json() == r2.json()
    assert "stale" not in r1.json()
    assert calls["n"] == 1, "toinen kutsu pitää tulla cachesta"


def test_rapid_league_browse_no_user_429(client, monkeypatch):
    # Nopea selaus: sama liigasetti kahdesti → FD-kutsuja vain 1/liiga
    calls = _mock_get(monkeypatch, [_Resp(200, STANDINGS_BODY)])
    leagues = ["ENG-Premier League-FD", "GER-Bundesliga-FD", "ESP-La Liga-FD",
               "ITA-Serie A-FD", "FRA-Ligue 1-FD", "ENG-Championship",
               "NED-Eredivisie", "POR-Primeira Liga", "BRA-Serie A"]
    for _ in range(2):
        for lg in leagues:
            assert client.get(f"/api/standings?league={lg}").status_code == 200
    assert calls["n"] == len(leagues)


def test_foreground_does_not_retry_on_429(client, monkeypatch):
    """🔴 KAANNETTY 16.8 illalla. Tama testi vaati aiemmin uusintaa
    pyyntopolussa. Se uusinta oli juuri se joka teki /api/standings:sta
    38 sekunnin jumin (mitattu tuotannosta), koska kylma pyynto ketjutti
    nelja yritysta backoffeineen. Uusinnat ovat nyt taustasaikeessa.

    Kylma 429 on siis nopea 503 eika hidas 200. Klientti nayttaa
    "Server is having trouble" ja pull-to-refresh toimii heti."""
    calls = _mock_get(monkeypatch, [_Resp(429, text="Too many requests"),
                                    _Resp(200, STANDINGS_BODY)])
    # Taustahaku mykistetaan: se SAA uusia, ja tama testi mittaa vain
    # pyyntopolkua.
    monkeypatch.setattr(m, "_fd_kick_refresh", lambda *a, **kw: None)
    r = client.get("/api/standings?league=ENG-Premier League-FD")
    assert r.status_code == 503
    assert calls["n"] == 1, "pyyntopolku saa tehda tasan yhden yrityksen"


def test_persistent_429_serves_stale_after_ttl(client, monkeypatch):
    calls = _mock_get(monkeypatch, [_Resp(200, STANDINGS_BODY),
                                    _Resp(429, text="Too many requests")])
    r1 = client.get("/api/standings?league=ENG-Premier League-FD")
    assert r1.status_code == 200
    # Vanhennetaan cache käsin (TTL ohi) → seuraava FD-haku failaa 429 ×2
    for k in list(m._FD_HTTP_CACHE):
        ts, data = m._FD_HTTP_CACHE[k]
        m._FD_HTTP_CACHE[k] = (ts - m.FD_HTTP_TTL_SEC - 1, data)
    r2 = client.get("/api/standings?league=ENG-Premier League-FD")
    assert r2.status_code == 200, "stale-fallback, EI käyttäjävirhettä"
    assert r2.json().get("stale") is True
    assert r2.json()["rows"] == r1.json()["rows"]


def test_persistent_failure_without_cache_is_fast_503(client, monkeypatch):
    """Ilman cachea: nopea, hallittu virhe. Status on 503 eika 429, koska
    vika ei ole kayttajan pyyntotahdissa vaan siina ettei upstream vastaa
    juuri nyt. Klientti mappaa 5xx:n uudelleenyritettavaksi."""
    _mock_get(monkeypatch, [_Resp(429, text="Too many requests")])
    r = client.get("/api/standings?league=ENG-Premier League-FD")
    assert r.status_code == 503


def test_fixtures_share_cache_and_stale_flag(client, monkeypatch):
    calls = _mock_get(monkeypatch, [_Resp(200, FIXTURES_BODY)])
    r1 = client.get("/api/fixtures?league=ENG-Premier League-FD&days=7")
    r2 = client.get("/api/fixtures?league=ENG-Premier League-FD&days=7")
    assert r1.status_code == 200 and calls["n"] == 1
    assert r1.json()["fixtures"][0]["home_team"] == "Arsenal"
    assert "stale" not in r1.json()
    assert r2.json() == r1.json()


def test_stale_cache_is_served_instead_of_waiting(client, monkeypatch):
    """Se mita aamun uusintaketju YRITTI saavuttaa, saadaan nyt ilman etta
    kukaan odottaa: vanha vastaus heti + virkistys taustalla."""
    _mock_get(monkeypatch, [_Resp(200, STANDINGS_BODY)])
    r1 = client.get("/api/standings?league=ENG-Premier League-FD")
    assert r1.status_code == 200
    for k in list(m._FD_HTTP_CACHE):
        ts, data = m._FD_HTTP_CACHE[k]
        m._FD_HTTP_CACHE[k] = (ts - m.FD_HTTP_TTL_SEC - 1, data)
    _mock_get(monkeypatch, [_Resp(429, text="Too many requests")])
    r2 = client.get("/api/standings?league=ENG-Premier League-FD")
    assert r2.status_code == 200, "stale, EI virhetta eika odotusta"
    assert r2.json().get("stale") is True
    assert r2.json()["rows"] == r1.json()["rows"]


def test_429_sleep_honours_fd_hint_and_adds_jitter():
    """FD kertoo bodyssa kauanko odottaa. Ilman jitteriä rinnakkaiset säikeet
    heräävät samalla sekunnilla ja törmäävät uudelleen."""
    body = '{"message":"You reached your request limit. Wait 7 seconds.","errorCode":429}'
    samples = [m._fd_429_sleep_sec(body, 0) for _ in range(20)]
    assert all(s >= 7.0 for s in samples), "FD:n vihjettä on noudatettava"
    assert len(set(samples)) > 1, "jitterin pitää hajauttaa herätykset"
    # Negatiivinen kontrolli: ilman vihjettä pohja-backoff kasvaa yritysten mukana
    assert m._fd_429_sleep_sec("", 2) > m._fd_429_sleep_sec("", 0) - 1.5


def test_both_ttls_are_long_enough_to_keep_cold_rare():
    """Molemmat pintaa saivat pitkan TTL:n. Standings oli 10 minuutissa, ja
    ~65 latauksella/vrk se tarkoitti etta lahes jokainen avaus oli kylma.
    Tuoreus ei karsi, koska vanhentunut osuma virkistyy taustalla."""
    assert m.FD_HTTP_TTL_SEC >= 1800
    assert m.FD_FIXTURES_TTL_SEC >= 1800


def test_concurrent_fanout_is_gated_not_stampeded(client, monkeypatch):
    """Mitattu vika 16.8: 22 rinnakkaista pyyntöä → 22 × 429, koska jokainen
    URL meni omana FD-kutsunaan yhtä aikaa. Portti rajaa yhtäaikaiset."""
    import threading as _th

    peak = {"now": 0, "max": 0}
    guard = _th.Lock()

    def fake_get(url, headers=None, timeout=None):
        with guard:
            peak["now"] += 1
            peak["max"] = max(peak["max"], peak["now"])
        # Event.wait EIKÄ time.sleep: autouse-fixture monkeypatchaa m.time.sleep
        # nollaksi (ja m.time ON time-moduuli), joten sleep ei pitäisi ikkunaa
        # auki eikä mittaus näkisi päällekkäisyyttä.
        _th.Event().wait(0.05)
        with guard:
            peak["now"] -= 1
        return _Resp(200, FIXTURES_BODY)

    monkeypatch.setattr(m.requests, "get", fake_get)

    codes: list[int] = []
    threads = [
        _th.Thread(target=lambda i=i: codes.append(
            client.get(f"/api/fixtures?league=ENG-Premier League-FD&days={30 + i}")
            .status_code))
        for i in range(12)
    ]
    for t_ in threads:
        t_.start()
    for t_ in threads:
        t_.join()
    assert codes == [200] * 12
    # Kiinteä luku EIKÄ m.FD_HTTP_MAX_CONCURRENT: konfiguraatiota vasten
    # mittaava portti läpäisisi itsensä myös silloin kun katto nostetaan
    # vahingossa pois. Negatiivinen kontrolli ajettu (portti pois → 12).
    assert peak["max"] <= 5, f"rinnakkaisia FD-kutsuja {peak['max']}"
    assert m.FD_HTTP_MAX_CONCURRENT <= 5


def test_fixtures_cache_key_survives_utc_date_rollover(client, monkeypatch):
    """Fixtures-URL sisältää dateFrom/dateTo jotka lasketaan kuluvasta
    päivästä → URL vaihtuu joka UTC-vuorokauden vaihteessa. Jos cache-avain
    olisi URL, stale-fallback ei voisi koskaan auttaa: jokainen vuorokausi
    alkaisi tyhjästä ja upstreamin nikotellessa käyttäjä saisi virheen
    eikä eilistä listaa."""
    calls = _mock_get(monkeypatch, [_Resp(200, FIXTURES_BODY)])
    r1 = client.get("/api/fixtures?league=ENG-Premier League-FD&days=7")
    assert r1.status_code == 200 and calls["n"] == 1

    # Simuloi vuorokauden vaihtuminen: URL muuttuu, avain ei.
    keys = list(m._FD_HTTP_CACHE)
    assert keys == ["fixtures:PL:7"], f"cache-avain oli {keys}"

    # Vanhennetaan + upstream failaa → stale eikä virhe, vaikka URL on uusi.
    ts, data = m._FD_HTTP_CACHE[keys[0]]
    m._FD_HTTP_CACHE[keys[0]] = (ts - m.FD_FIXTURES_TTL_SEC - 1, data)
    _mock_get(monkeypatch, [_Resp(429, text="Wait 2 seconds")])
    r2 = client.get("/api/fixtures?league=ENG-Premier League-FD&days=7")
    assert r2.status_code == 200
    assert r2.json().get("stale") is True
    assert r2.json()["fixtures"] == r1.json()["fixtures"]


def test_response_shape_unchanged(client, monkeypatch):
    _mock_get(monkeypatch, [_Resp(200, STANDINGS_BODY)])
    r = client.get("/api/standings?league=ENG-Premier League-FD")
    body = r.json()
    assert set(body.keys()) == {"league", "season", "rows"}
    assert set(body["rows"][0].keys()) == {
        "position", "team_name", "team_short_name", "team_crest",
        "played_games", "won", "draw", "lost", "goals_for", "goals_against",
        "goal_difference", "points"}
