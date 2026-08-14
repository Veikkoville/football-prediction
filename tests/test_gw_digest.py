"""GW-DIGEST-portit.

Kaksi asiaa joita mikaan muu ei valvo:
  1) skripti EI SAA lahettaa mitaan (CLAUDE.md 6b: julkaisutarkistaja ajetaan
     ennen kuin teksti naytetaan Villelle, eika sahkopostia voi peruuttaa),
  2) vedos saa sisaltaa vain ilmaispinnan lukuja (portin 1. kysymys on
     "pystyyko lukija tarkistamaan vaitteen ilmaispinnalta").
"""
from __future__ import annotations

import datetime as _dt
import inspect

import pytest

from scripts import build_gw_digest as dg


UTC = _dt.timezone.utc


def _events():
    return [
        {"id": 1, "deadline_time": "2026-08-21T17:30:00Z"},
        {"id": 2, "deadline_time": "2026-08-29T17:30:00Z"},
    ]


@pytest.fixture
def facts():
    now = _dt.datetime(2026, 8, 20, 17, 30, tzinfo=UTC)
    deadline = dg.next_deadline(_events(), now)
    xp = {"players": [
        {"team": "Arsenal", "gameweeks": [
            {"gw": 1, "opponents": [{"opp": "HUL", "venue": "H"}]}]},
        {"team": "Chelsea", "gameweeks": [
            {"gw": 1, "opponents": [{"opp": "IPS", "venue": "A"}]}]},
    ]}
    watch = {"risers": [{"web_name": "Saka", "status": "rising_soon",
                         "progress_pct": 82.0,
                         "already_changed_today": False}],
             "fallers": []}
    return dg.build_facts(deadline, xp, watch)


# --------------------------------------------------------------------------
# 1) Ei lahetysta — rakenteellinen takuu, ei lupaus kommentissa
# --------------------------------------------------------------------------

def test_module_cannot_send_anything():
    src = inspect.getsource(dg).lower()
    # Haetaan LAHETYSKYKYA, ei sanaa "mailerlite" — tiedoston otsikkokommentti
    # saa nimeta kanavan. Osoite tai lahetyskirjasto on kyky; nimi ei ole.
    for forbidden in ("api.mailerlite", "mailerlite.com", "requests.post",
                      "requests.put", "smtplib", "sendgrid", "resend.",
                      "urlopen", "httpx"):
        assert forbidden not in src, \
            f"digest-skriptiin ilmestyi lahetyskyky: {forbidden}"
    # Ainoa sallittu verkkokutsu on FPL:n julkinen bootstrap (deadline).
    assert src.count("requests.get") == 1


def test_output_paths_are_drafts_only():
    assert dg.OUT_DIR.name == "gw_digest"
    assert "outputs" in str(dg.OUT_DIR)


# --------------------------------------------------------------------------
# 2) Deadline-ikkuna
# --------------------------------------------------------------------------

def test_next_deadline_picks_the_nearest_future_one():
    now = _dt.datetime(2026, 8, 20, 17, 30, tzinfo=UTC)
    got = dg.next_deadline(_events(), now)
    assert got["gw"] == 1 and got["hours_left"] == 24.0
    # Deadlinen jalkeen seuraava kierros ottaa vuoron.
    after = _dt.datetime(2026, 8, 21, 18, 0, tzinfo=UTC)
    assert dg.next_deadline(_events(), after)["gw"] == 2
    # Kausi ohi -> None, ei kaatumista.
    end = _dt.datetime(2026, 9, 1, tzinfo=UTC)
    assert dg.next_deadline(_events(), end) is None


def test_send_window_excludes_a_week_early_draft():
    lo, hi = dg.SEND_WINDOW_H
    assert lo < 24.0 < hi           # vuorokausi ennen = ikkunassa
    assert 168.0 > hi               # viikko ennen = ei ikkunassa


# --------------------------------------------------------------------------
# 3) Sisalto: vain ilmaispinnan luvut
# --------------------------------------------------------------------------

def test_draft_passes_its_own_gates(facts):
    md = dg.render_markdown(facts)
    assert dg.draft_problems(md, facts) == []


def test_premium_number_is_never_written(facts):
    """Pelaajan xP on premiumin takana. Jos se vuotaa vedokseen, lukija ei
    voi tarkistaa sita ilmaispinnalta ja portti 1 kaatuu."""
    md = dg.render_markdown(facts)
    assert "xP" not in md
    assert "expected points for" in md   # teasataan, ei paljasteta luvulla


def test_invented_number_in_the_draft_is_caught(facts):
    """NEGATIIVINEN KONTROLLI: portti kaataa kun luku ei ole faktoissa."""
    md = dg.render_markdown(facts) + "\nOur model hit 71 percent last season."
    problems = dg.draft_problems(md, facts)
    assert any("pohjaton luku" in p for p in problems), problems


def test_banned_words_and_dashes_are_caught(facts):
    md = dg.render_markdown(facts)
    assert any("kielletty merkki" in p
               for p in dg.draft_problems(md + "\nGood — very good.", facts))
    assert any("kielletty sana: odds" in p
               for p in dg.draft_problems(md + "\nCheck the odds.", facts))
    # Sijaintivuoto (muisti: no-location-in-public-copy).
    assert any("kielletty sana: eest" in p
               for p in dg.draft_problems(md + "\nSent 20:30 EEST.", facts))


def test_cta_is_the_season_checkout(facts):
    md = dg.render_markdown(facts)
    assert "checkout?plan=season" in md
    assert any("CTA puuttuu" in p
               for p in dg.draft_problems(md.replace(dg.CTA_URL, "x"), facts))


def test_price_notes_only_take_imminent_movers():
    watch = {"risers": [
        {"web_name": "A", "status": "rising_soon", "progress_pct": 90.0,
         "already_changed_today": False},
        {"web_name": "B", "status": "rising_watch", "progress_pct": 50.0,
         "already_changed_today": False},
        {"web_name": "C", "status": "rising_soon", "progress_pct": 95.0,
         "already_changed_today": True},
    ], "fallers": []}
    got = dg.price_notes(watch)
    assert [r["name"] for r in got["risers"]] == ["A"]


def test_html_render_has_no_subject_line(facts):
    md = dg.render_markdown(facts)
    html = dg.render_html(md)
    assert "Subject:" not in html
    assert "<p>" in html and "<li>" in html
