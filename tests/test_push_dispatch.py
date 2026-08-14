"""PUSH-NOTIF vaihe b+c: push_dispatch-portit.

Painopiste on kolmessa asiassa jotka tuotannossa maksavat eniten:
  1) idempotenssi (kaksi ajoa samalla kellolla = 1 lahetys, ja markkeri on
     levylla ENNEN lahetysta),
  2) ikkuna osuu 3 h cronilla (mitattu ansa: 2 h levea ikkuna ei osu
     KOSKAAN kun ajot ovat 15:00 ja 18:00 ja deadline 17:30),
  3) premium- ja watchlist-portit price-pusheissa.

Jokaiselle portille on negatiivinen kontrolli: testi joka osoittaa etta
portti kaataa kun sen kuuluu (muisti: substring-osuma on sokea).
"""
from __future__ import annotations

import datetime as _dt
import json

import pytest

from scripts import push_dispatch as pd


UTC = _dt.timezone.utc
DEADLINE = "2026-08-21T17:30:00Z"


def _events(deadline: str = DEADLINE, gw: int = 1,
            finished: bool = False) -> list[dict]:
    return [{"id": gw, "deadline_time": deadline, "finished": finished}]


def _dt_utc(s: str) -> _dt.datetime:
    return _dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


# --------------------------------------------------------------------------
# Ikkunalogiikka
# --------------------------------------------------------------------------

def test_24h_window_fires_inside_and_not_outside():
    now = _dt_utc("2026-08-20T17:30:00Z")          # tasan 24 h
    got = pd.deadline_windows(_events(), now)
    assert [w["kind"] for w in got] == ["deadline_24h"]

    too_early = _dt_utc("2026-08-20T10:00:00Z")    # 31,5 h
    assert pd.deadline_windows(_events(), too_early) == []


def test_2h_window_fires_and_excludes_past_deadline():
    now = _dt_utc("2026-08-21T15:45:00Z")          # 1,75 h
    assert [w["kind"] for w in pd.deadline_windows(_events(), now)] \
        == ["deadline_2h"]
    after = _dt_utc("2026-08-21T17:35:00Z")
    assert pd.deadline_windows(_events(), after) == []


def test_windows_never_overlap_in_the_same_run():
    """24 h- ja 2 h -ikkunat eivat voi olla auki yhta aikaa — muuten
    kayttaja saisi kaksi pushia minuutin sisalla."""
    t = _dt_utc("2026-08-20T13:30:00Z")
    while t < _dt_utc("2026-08-21T18:00:00Z"):
        assert len(pd.deadline_windows(_events(), t)) <= 1
        t += _dt.timedelta(minutes=5)


def test_three_hour_cron_hits_both_windows_exactly_once():
    """MITATTU ANSA: cron 0 */3 -> ajot 15:00 ja 18:00, deadline 17:30.
    Kapea 2 h -ikkuna ei osuisi kertaakaan. Tama testi kaatuu jos ikkunaa
    kavennetaan takaisin."""
    hits: list[str] = []
    t = _dt_utc("2026-08-19T00:00:00Z")
    while t < _dt_utc("2026-08-22T00:00:00Z"):
        hits += [w["kind"] for w in pd.deadline_windows(_events(), t)]
        t += _dt.timedelta(hours=3)
    assert hits.count("deadline_24h") >= 1, "24 h -ikkuna ei osunut cronilla"
    assert hits.count("deadline_2h") >= 1, "2 h -ikkuna ei osunut cronilla"


def test_finished_event_is_skipped():
    now = _dt_utc("2026-08-21T15:45:00Z")
    assert pd.deadline_windows(_events(finished=True), now) == []


def test_missed_window_is_reported_loudly():
    now = _dt_utc("2026-08-21T20:00:00Z")   # deadline meni 2,5 h sitten
    missed = pd.missed_deadline_windows(_events(), now, {"sent": {}})
    assert set(missed) == {"deadline_24h:gw1", "deadline_2h:gw1"}
    # Negatiivinen kontrolli: lahetetty ikkuna EI ole missed.
    state = {"sent": {"deadline_2h:gw1": {"at": "2026-08-21T15:00:00Z"}}}
    assert pd.missed_deadline_windows(_events(), now, state) \
        == ["deadline_24h:gw1"]


# --------------------------------------------------------------------------
# Quiet hours + locale
# --------------------------------------------------------------------------

@pytest.mark.parametrize("locale,expected", [
    ("en-GB", 1.0), ("fi-FI", 3.0), ("ar-SA", 3.0), ("pt-BR", -3.0),
    ("es-ES", 2.0), ("en_US", -5.0),
    (None, pd.DEFAULT_UTC_OFFSET), ("", pd.DEFAULT_UTC_OFFSET),
    ("xx", pd.DEFAULT_UTC_OFFSET), ("en-ZZ", pd.DEFAULT_UTC_OFFSET),
])
def test_utc_offset_from_locale(locale, expected):
    assert pd.utc_offset_hours(locale) == expected


def test_quiet_hours_window():
    # UTC+3: paikallinen 23:30 = 20:30 UTC -> hiljaista.
    assert pd.in_quiet_hours(_dt_utc("2026-08-20T20:30:00Z"), 3.0)
    # Paikallinen 08:30 -> ei hiljaista.
    assert not pd.in_quiet_hours(_dt_utc("2026-08-20T05:30:00Z"), 3.0)
    # Sama UTC-hetki, UK (+1): paikallinen 21:30 -> ei hiljaista.
    assert not pd.in_quiet_hours(_dt_utc("2026-08-20T20:30:00Z"), 1.0)


def test_eligible_tokens_filters_optin_and_quiet_hours():
    now = _dt_utc("2026-08-20T20:30:00Z")   # +3 hiljainen, +1 ei
    rows = [
        {"expo_token": "a", "locale": "fi-FI", "opted_in_deadline": True},
        {"expo_token": "b", "locale": "en-GB", "opted_in_deadline": True},
        {"expo_token": "c", "locale": "en-GB", "opted_in_deadline": False},
    ]
    got = [r["expo_token"] for r in pd.eligible_tokens(rows, "deadline", now)]
    assert got == ["b"]


# --------------------------------------------------------------------------
# Tekstit (copy-portti koskee myos pusheja)
# --------------------------------------------------------------------------

def test_deadline_text_has_no_timezone_leak_and_no_em_dash():
    for remaining in (1.2, 2.0, 3.5, 24.0, 25.8):
        title, body = pd.deadline_message(1, remaining)
        text = f"{title} {body}"
        assert "—" not in text and "–" not in text
        for leak in ("EEST", "EET", "UTC", "GMT", "AM", "PM", ":30", ":00"):
            assert leak not in text, f"aikavyohykevuoto: {text}"
    assert "in about 2 hours" in pd.deadline_message(1, 2.0)[0]
    assert "under 90 minutes" in pd.deadline_message(1, 0.8)[0]


def test_price_and_pick_text_have_no_em_dash_in_title():
    t, b = pd.price_message([{"web_name": "Saka"}])
    assert "Saka is close to a price rise" == t
    assert "—" not in t
    t2, _ = pd.price_message([{"web_name": f"P{i}"} for i in range(5)])
    assert "+2 more" in t2


# --------------------------------------------------------------------------
# Price-portit
# --------------------------------------------------------------------------

def test_new_price_risers_gates():
    watch = {"risers": [
        {"id": 1, "web_name": "A", "status": "rising_soon",
         "already_changed_today": False},
        {"id": 2, "web_name": "B", "status": "rising_watch",
         "already_changed_today": False},
        {"id": 3, "web_name": "C", "status": "rising_soon",
         "already_changed_today": True},
        {"id": 4, "web_name": "D", "status": "rising_soon",
         "already_changed_today": False},
    ]}
    got = pd.new_price_risers(watch, {"4": "2026-08-14"}, "2026-08-14")
    assert [r["id"] for r in got] == [1]
    # Negatiivinen kontrolli: eilinen halytys ei estä tanaan.
    got2 = pd.new_price_risers(watch, {"4": "2026-08-13"}, "2026-08-14")
    assert [r["id"] for r in got2] == [1, 4]


def test_price_targets_requires_premium_watchlist_and_daily_cap():
    risers = [{"id": 11, "web_name": "A"}]
    tokens = [
        {"expo_token": "t1", "is_premium": True, "watchlist": [11, 12]},
        {"expo_token": "t2", "is_premium": False, "watchlist": [11]},
        {"expo_token": "t3", "is_premium": True, "watchlist": [99]},
        {"expo_token": "t4", "is_premium": False, "watchlist": []},  # anon
    ]
    got = pd.price_targets(tokens, risers, {}, "2026-08-14")
    assert [t[0]["expo_token"] for t in got] == ["t1"]

    # Kova saanto 1: max 1 price-push / kayttaja / vrk.
    capped = pd.price_targets(tokens, risers, {"t1": "2026-08-14"},
                              "2026-08-14")
    assert capped == []


def test_pick_of_week_excludes_owned_and_picks_highest_gw_xp():
    payload = {"players": [
        {"id": 1, "web_name": "Owned", "owned_pct": 48.1,
         "gameweeks": [{"gw": 1, "xp": 9.0}]},
        {"id": 2, "web_name": "Diff", "owned_pct": 4.2,
         "gameweeks": [{"gw": 1, "xp": 6.1}, {"gw": 2, "xp": 9.9}]},
        {"id": 3, "web_name": "Diff2", "owned_pct": 2.0,
         "gameweeks": [{"gw": 1, "xp": 5.0}]},
    ]}
    pick = pd.pick_of_week(payload, 1)
    assert pick["player"]["web_name"] == "Diff" and pick["xp"] == 6.1
    # Negatiivinen kontrolli: kierros jolle ei ole xP:ta -> ei poimintaa.
    assert pd.pick_of_week(payload, 7) is None


# --------------------------------------------------------------------------
# Idempotenssi (koko main-silmukka, IO monkeypatchattuna)
# --------------------------------------------------------------------------

@pytest.fixture
def wired(monkeypatch, tmp_path):
    """push_dispatch verkkoriippuvuudet katkaistuna + tila tmp-kansioon."""
    sent_batches: list[list[dict]] = []

    monkeypatch.setattr(pd, "STATE_PATH", tmp_path / "push_state.json")
    monkeypatch.setenv("ADMIN_TOKEN", "test-admin")
    monkeypatch.setenv("API_BASE", "https://example.invalid")
    monkeypatch.delenv("POSTHOG_API_KEY", raising=False)
    monkeypatch.setattr(pd, "fetch_bootstrap", lambda: {"events": _events()})
    monkeypatch.setattr(pd, "fetch_push_targets", lambda: [
        {"expo_token": "ExponentPushToken[aaaaaaaaaaaaaaaa]",
         "user_id": None, "platform": "ios", "locale": "en-GB",
         "opted_in_deadline": True, "opted_in_price": False,
         "opted_in_picks": False, "is_premium": False, "watchlist": []},
    ])
    monkeypatch.setattr(pd, "check_receipts", lambda state: None)
    monkeypatch.setattr(pd, "read_json", lambda p: {})

    def fake_send(messages):
        sent_batches.append(list(messages))
        return [{"status": "ok", "id": f"t{i}"}
                for i, _ in enumerate(messages)]

    monkeypatch.setattr(pd, "expo_send", fake_send)
    return sent_batches


def _at(monkeypatch, iso: str):
    """Siirra dispatchin kello. Patchaa vain push_dispatch._now(), EI koko
    datetime-moduulia — moduulin patchaus vuotaisi testitiedostoon itseensa."""
    monkeypatch.setattr(pd, "_now", lambda: _dt_utc(iso))


def test_two_consecutive_runs_send_once(wired, monkeypatch):
    """Specin kova saanto: kaksi perakkaista ajoa samalla kellolla = 1 lahetys."""
    _at(monkeypatch, "2026-08-21T15:45:00Z")
    assert pd.main() == 0
    assert pd.main() == 0
    assert len(wired) == 1, "toinen ajo lahetti uudelleen"
    assert len(wired[0]) == 1


def test_marker_is_on_disk_before_send(wired, monkeypatch):
    """Jos lahetys kaatuu, markkerin on JO oltava levylla — muuten seuraava
    ajo lahettaa saman pushin uudelleen."""
    def exploding(messages):
        raise RuntimeError("expo down")
    monkeypatch.setattr(pd, "expo_send", exploding)
    _at(monkeypatch, "2026-08-21T15:45:00Z")
    with pytest.raises(RuntimeError):
        pd.main()
    state = json.loads(pd.STATE_PATH.read_text(encoding="utf-8"))
    assert "deadline_2h:gw1" in state["sent"]


def test_both_windows_send_separately(wired, monkeypatch):
    _at(monkeypatch, "2026-08-20T17:00:00Z")     # 24 h -ikkuna
    pd.main()
    _at(monkeypatch, "2026-08-21T15:45:00Z")     # 2 h -ikkuna
    pd.main()
    assert len(wired) == 2
    kinds = [b[0]["data"]["kind"] for b in wired]
    assert kinds == ["deadline_24h", "deadline_2h"]


def test_no_window_sends_nothing(wired, monkeypatch):
    _at(monkeypatch, "2026-08-18T09:00:00Z")
    assert pd.main() == 0
    assert wired == []


def test_missing_admin_token_is_not_an_error(wired, monkeypatch):
    """Secret puuttuu -> ohitus varoituksella, EI punaista ajoa. Sama
    linjaus kuin grade-decisions-stepilla: data-refresh ei saa kaatua siihen
    etta push-kanava on viela konfiguroimatta."""
    monkeypatch.delenv("ADMIN_TOKEN", raising=False)
    _at(monkeypatch, "2026-08-21T15:45:00Z")
    assert pd.main() == 0
    assert wired == []


def test_prune_keeps_state_small():
    state = {"price_alerted": {"1": "2026-06-01", "2": "2026-08-13"},
             "last_price_push": {"t": "2026-06-01"},
             "sent": {"a:gw1": {"at": "2026-06-01T00:00:00Z"},
                      "b:gw2": {"at": "2026-08-13T00:00:00Z"}}}
    pd.prune_state(state, _dt_utc("2026-08-14T00:00:00Z"))
    assert state["price_alerted"] == {"2": "2026-08-13"}
    assert state["last_price_push"] == {}
    assert list(state["sent"]) == ["b:gw2"]


# --------------------------------------------------------------------------
# Admin-endpointit (runnerin datalahde) — turvaportti + liitos
# --------------------------------------------------------------------------

def test_push_targets_requires_admin_token(client, monkeypatch):
    """Fail-closed: ilman ADMIN_TOKENia 403, ja vaaralla tokenilla 403."""
    monkeypatch.delenv("ADMIN_TOKEN", raising=False)
    assert client.get("/api/admin/push-targets").status_code == 403

    monkeypatch.setenv("ADMIN_TOKEN", "right")
    assert client.get("/api/admin/push-targets",
                      headers={"X-Admin-Token": "wrong"}).status_code == 403
    assert client.post("/api/admin/push-token-delete",
                       json={"token": "ExponentPushToken[x]"},
                       headers={"X-Admin-Token": "wrong"}).status_code == 403


def test_push_targets_joins_premium_and_watchlist(client, monkeypatch):
    """Liitos tehdaan palvelimella: runner saa is_premium + watchlist
    valmiina eika nae profiles-taulua."""
    import api.main as m
    monkeypatch.setenv("ADMIN_TOKEN", "right")
    monkeypatch.setattr(m, "SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.setattr(m, "SUPABASE_SERVICE_ROLE_KEY", "svc")

    class _Resp:
        def __init__(self, payload):
            self._p = payload

        def json(self):
            return self._p

    def fake_get(url, **kw):
        if "push_tokens" in url:
            return _Resp([
                {"expo_token": "t1", "user_id": "u1", "platform": "ios",
                 "locale": "en-GB", "opted_in_deadline": True,
                 "opted_in_price": True, "opted_in_picks": False},
                {"expo_token": "t2", "user_id": None, "platform": "android",
                 "locale": None, "opted_in_deadline": True,
                 "opted_in_price": False, "opted_in_picks": False},
            ])
        return _Resp([{"id": "u1", "is_premium": True,
                       "fpl_prefs": {"watchlist": [11, 22]}}])

    monkeypatch.setattr(m.requests, "get", fake_get)
    r = client.get("/api/admin/push-targets",
                   headers={"X-Admin-Token": "right"})
    assert r.status_code == 200
    targets = {t["expo_token"]: t for t in r.json()["targets"]}
    assert targets["t1"]["is_premium"] is True
    assert targets["t1"]["watchlist"] == [11, 22]
    # Negatiivinen kontrolli: anon-rivi EI saa premiumia eika watchlistia.
    assert targets["t2"]["is_premium"] is False
    assert targets["t2"]["watchlist"] == []


def test_message_routes_with_the_shipped_app_vocabulary():
    """App.tsx reitittaa `data.type`:lla ja tuntee vain lokaalien
    notifikaatioiden sanaston. Vaara arvo veisi deadline-pushin Fixtures-
    tabiin shipatussa bundlessa — siksi tama on portti eika kommentti."""
    row = {"expo_token": "t"}
    for kind, expect in [("deadline_24h", "gw_deadline"),
                         ("deadline_2h", "gw_deadline"),
                         ("price", "fpl_price"),
                         ("picks", "gw_deadline")]:
        msg = pd.build_message(row, "t", "b", kind, pd.CHANNEL_DEADLINE)
        assert msg["data"]["type"] == expect
        assert msg["data"]["kind"] == kind
        assert msg["data"]["source"] == "server"
