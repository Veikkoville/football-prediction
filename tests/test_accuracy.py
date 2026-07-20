"""Tarkkuus-track-record -putken testit (#100).

Kattaa: 1X2/exact/decisive-osumalogiikan, aggregaatin (reuse backtest-Brier),
seed-parsinnan WC-hubista (= julkaistu 21/40), endpointin muodon ja
WC pre-match -helperin neutraali-venue-symmetrian (peili predict_wc:stä).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.models import accuracy as acc


# ---------------------------------------------------------------------------
# Pien-helpurit
# ---------------------------------------------------------------------------
def test_outcome_from_score():
    assert acc.outcome_from_score(2, 0) == "home"
    assert acc.outcome_from_score(1, 1) == "draw"
    assert acc.outcome_from_score(0, 3) == "away"


def test_named_winner_never_draw():
    assert acc.named_winner(0.6, 0.2) == "home"
    assert acc.named_winner(0.2, 0.5) == "away"
    # tasan -> home (deterministinen tie-break)
    assert acc.named_winner(0.3, 0.3) == "home"


# ---------------------------------------------------------------------------
# upsert + set_result idempotenssi + osumalogiikka
# ---------------------------------------------------------------------------
def _entry(mid, winner, mls=None, p=(None, None, None), date="2026-06-20"):
    return {
        "match_id": mid, "source": "test", "competition": "WC", "date": date,
        "home_team": "A", "away_team": "B",
        "p_home": p[0], "p_draw": p[1], "p_away": p[2],
        "xg_home": None, "xg_away": None,
        "most_likely_score": mls, "predicted_winner": winner,
        "logged_at": None, "result": None,
    }


def test_upsert_is_idempotent():
    log = acc.empty_log()
    assert acc.upsert_prediction(log, _entry("m1", "home")) is True
    assert acc.upsert_prediction(log, _entry("m1", "away")) is False  # ei ylikirjoita
    assert len(log["predictions"]) == 1
    assert log["predictions"][0]["predicted_winner"] == "home"


def test_set_result_hit_and_exact():
    log = acc.empty_log()
    acc.upsert_prediction(log, _entry("m1", "home", mls="2-1"))
    assert acc.set_result(log, "m1", 2, 1) is True
    res = log["predictions"][0]["result"]
    assert res["actual_outcome"] == "home"
    assert res["hit_1x2"] is True
    assert res["exact_hit"] is True
    assert res["actual_score"] == "2-1"
    # idempotentti: toinen reconcile ei muuta
    assert acc.set_result(log, "m1", 0, 5) is False


def test_set_result_draw_is_miss_for_named_winner():
    log = acc.empty_log()
    acc.upsert_prediction(log, _entry("m1", "home", mls="2-1"))
    acc.set_result(log, "m1", 1, 1)  # tasapeli
    res = log["predictions"][0]["result"]
    assert res["actual_outcome"] == "draw"
    assert res["hit_1x2"] is False
    assert res["exact_hit"] is False  # 2-1 != 1-1


def test_exact_hit_none_without_mls():
    log = acc.empty_log()
    acc.upsert_prediction(log, _entry("m1", "home", mls=None))  # seed-tyyppi
    acc.set_result(log, "m1", 3, 0)
    assert log["predictions"][0]["result"]["exact_hit"] is None


# ---------------------------------------------------------------------------
# 90 min -gradaus (Villen päätös 20.7 ilta, kumosi saman päivän FT-AET-kokeilun):
# täysajalla tasan ollut pudotuspeli = tasapeli, ET JA pilkut samalla säännöllä.
# ---------------------------------------------------------------------------
def test_set_result_extra_time_win_graded_as_90min_draw():
    log = acc.empty_log()
    acc.upsert_prediction(log, _entry("m1", "home", mls="1-1"))
    # 90 min 1-1, koti voitti jatkoajalla 3-2 (esim. Argentina-Cape Verde)
    assert acc.set_result(log, "m1", 3, 2, duration="EXTRA_TIME",
                          regular_home=1, regular_away=1) is True
    res = log["predictions"][0]["result"]
    assert res["actual_score"] == "3-2"          # näyttötulos säilyy
    assert res["duration"] == "EXTRA_TIME"
    assert res["regular_score"] == "1-1"
    assert res["actual_outcome"] == "draw"       # 90 min -gradaus
    assert res["hit_1x2"] is False               # ET-voitto ei ole 1X2-osuma
    assert res["exact_hit"] is True              # mls 1-1 == 90 min 1-1


def test_set_result_final_shape_et_win_is_miss():
    # GRADE-90-ankkuri: regular 0-0, lopputulos 1-0 aet, pick home → MISSI.
    log = acc.empty_log()
    acc.upsert_prediction(log, _entry("m1", "home", mls="1-0"))
    acc.set_result(log, "m1", 1, 0, duration="EXTRA_TIME",
                   regular_home=0, regular_away=0)
    res = log["predictions"][0]["result"]
    assert res["actual_outcome"] == "draw"
    assert res["hit_1x2"] is False
    assert res["exact_hit"] is False             # mls 1-0 != 90 min 0-0


def test_set_result_penalty_shootout_graded_as_90min():
    log = acc.empty_log()
    acc.upsert_prediction(log, _entry("m1", "away", mls="0-1"))
    acc.set_result(log, "m1", 1, 1, duration="PENALTY_SHOOTOUT",
                   regular_home=1, regular_away=1)
    res = log["predictions"][0]["result"]
    assert res["actual_outcome"] == "draw"
    assert res["hit_1x2"] is False
    assert res["exact_hit"] is False
    assert res["duration"] == "PENALTY_SHOOTOUT"


def test_set_result_regular_time_win_unchanged():
    # Regressiosuoja: normaali 90 min -ratkaisu gradataan kuten ennenkin.
    log = acc.empty_log()
    acc.upsert_prediction(log, _entry("m1", "home", mls="2-1"))
    acc.set_result(log, "m1", 2, 1)
    res = log["predictions"][0]["result"]
    assert res["actual_outcome"] == "home"
    assert res["hit_1x2"] is True
    assert res["exact_hit"] is True


def test_regrade_flips_ft_aet_graded_et_win_back_to_draw():
    # Siirtymä FT-AET-välitilasta (20.7 päivä) 90 min -normiin: FT-AET gradasi
    # ET-voiton osumaksi → regrade kääntää tasapeliksi/missiksi, rivi ei putoa.
    log = acc.empty_log()
    acc.upsert_prediction(log, _entry("m1", "home", mls="2-0"))
    acc.set_result(log, "m1", 3, 2, duration="EXTRA_TIME",
                   regular_home=1, regular_away=1)
    orig_reconciled = log["predictions"][0]["result"]["reconciled_at"]
    # simuloi FT-AET-normilla gradattu lohko (kuten prediction_logissa 20.7 päivällä)
    log["predictions"][0]["result"].update(
        {"actual_outcome": "home", "hit_1x2": True}
    )

    assert acc.regrade_result(log, "m1", 3, 2, duration="EXTRA_TIME",
                              regular_home=1, regular_away=1) is True
    assert len(log["predictions"]) == 1          # union: rivi ei putoa
    res = log["predictions"][0]["result"]
    assert res["hit_1x2"] is False               # gradaus kääntyi 90 miniin
    assert res["actual_outcome"] == "draw"
    assert res["actual_score"] == "3-2"
    assert res["regular_score"] == "1-1"
    assert res["reconciled_at"] == orig_reconciled
    assert res["regraded_at"] is not None
    # ennustekentät koskemattomat
    assert log["predictions"][0]["predicted_winner"] == "home"


def test_regrade_noop_for_regular_match():
    log = acc.empty_log()
    acc.upsert_prediction(log, _entry("m1", "home", mls="2-1"))
    acc.set_result(log, "m1", 2, 1)
    assert acc.regrade_result(log, "m1", 2, 1) is False  # ei muutosta
    assert "regraded_at" not in log["predictions"][0]["result"]


# ---------------------------------------------------------------------------
# Aggregaatti (sis. Brier täysiltä riveiltä)
# ---------------------------------------------------------------------------
def test_compute_aggregate_metrics():
    log = acc.empty_log()
    # 2 täyttä-jakauma-riviä + 1 seed-tyyppinen (vain voittaja)
    acc.upsert_prediction(log, _entry("f1", "home", mls="2-1", p=(0.6, 0.25, 0.15)))
    acc.upsert_prediction(log, _entry("f2", "away", mls="0-1", p=(0.2, 0.3, 0.5)))
    acc.upsert_prediction(log, _entry("s1", "home", mls=None, p=(None, None, None)))
    acc.set_result(log, "f1", 2, 1)   # home, exact hit
    acc.set_result(log, "f2", 1, 1)   # draw -> miss
    acc.set_result(log, "s1", 3, 0)   # home, hit (1x2)

    agg = acc.compute_aggregate(log)
    at = agg["all_time"]
    assert at["n"] == 3
    assert at["correct_1x2"] == 2          # f1 + s1
    assert at["pct_1x2"] == pytest.approx(2 / 3, abs=1e-4)
    assert at["decisive_n"] == 2           # f1 (home), s1 (home); f2 ended draw
    assert at["decisive_correct"] == 2
    assert at["exact_n"] == 2              # vain f1, f2 (mls tunnetaan)
    assert at["exact_correct"] == 1        # f1
    assert at["brier_n"] == 2              # vain täydet jakaumat
    # MIN_DISPLAY_N-gate: exact_n/brier_n (2) < 30 → näytettävä arvo nullataan,
    # ali-otoskoot säilyvät raportoituina (data kertyy taustalla).
    assert at["pct_exact"] is None
    assert at["brier"] is None
    assert agg["pending"] == 0
    assert agg["logged_total"] == 3


def test_small_sample_exact_brier_gated():
    """exact/Brier nullataan kun ali-otos < MIN_DISPLAY_N, näkyy rajalla."""
    # Alle rajan (1 täysi-jakauma-rivi) → molemmat null, 1X2 ennallaan
    log = acc.empty_log()
    acc.upsert_prediction(log, _entry("a", "home", mls="2-1", p=(0.6, 0.25, 0.15)))
    acc.set_result(log, "a", 2, 1)
    at = acc.compute_aggregate(log)["all_time"]
    assert at["pct_1x2"] is not None       # 1X2 ei koskaan gateta
    assert at["pct_exact"] is None
    assert at["brier"] is None
    assert at["exact_n"] == 1 and at["brier_n"] == 1  # ali-otos yhä raportoitu

    # >= MIN_DISPLAY_N täysi-jakauma-rivillä → exact + Brier näkyvät
    log = acc.empty_log()
    for i in range(acc.MIN_DISPLAY_N):
        acc.upsert_prediction(log, _entry(f"f{i}", "home", mls="2-1",
                                          p=(0.6, 0.25, 0.15), date=f"2026-06-{i % 28 + 1:02d}"))
        acc.set_result(log, f"f{i}", 2, 1)
    at = acc.compute_aggregate(log)["all_time"]
    assert at["exact_n"] == acc.MIN_DISPLAY_N
    assert at["brier_n"] == acc.MIN_DISPLAY_N
    assert at["pct_exact"] is not None
    assert at["brier"] is not None


def test_empty_aggregate_shape():
    agg = acc.empty_aggregate()
    assert agg["all_time"]["n"] == 0
    assert agg["all_time"]["pct_1x2"] is None
    assert agg["rolling"]["window"] == acc.DEFAULT_ROLLING_WINDOW
    assert agg["calibration"] == []
    assert agg["recent"] == []


# ---------------------------------------------------------------------------
# Seed-parsinta WC-hubista = julkaistu 21/40
# ---------------------------------------------------------------------------
def test_seed_parse_matches_published_record():
    # 21/40 = ryhmävaiheen JULKAISTU track-record = immutaabeli historia. Pinnataan
    # arkistoituun ryhmävaihe-hubiin (tests/fixtures/) EIKÄ live-WC_HUB_HTML:ään:
    # live-hub rullaa kierroksittain eteenpäin (R32 → predictions-taulu, ei enää 40
    # ryhmävaiherivin track-recordia), joten golden-check ei saa riippua siitä.
    from scripts.accuracy_pipeline import parse_seed_rows
    fixture = Path(__file__).parent / "fixtures" / "wc-hub-groupstage.html"
    rows = parse_seed_rows(fixture.read_text(encoding="utf-8"))
    assert len(rows) == 40, f"odotettiin 40 seed-riviä, saatiin {len(rows)}"

    log = acc.empty_log()
    for r in rows:
        hs, as_ = r.pop("_seed_score")
        acc.upsert_prediction(log, r)
        acc.set_result(log, r["match_id"], hs, as_)
    at = acc.compute_aggregate(log)["all_time"]
    assert at["n"] == 40
    assert at["correct_1x2"] == 21          # WC-hubin julkaistu 21/40
    assert at["decisive_correct"] == 21
    assert at["decisive_n"] == 27           # 13 tasapeliä -> 27 ratkaisevaa
    assert at["pct_1x2"] == pytest.approx(0.525, abs=1e-3)


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------
def test_accuracy_endpoint_shape(client):
    r = client.get("/api/accuracy")
    assert r.status_code == 200
    b = r.json()
    for key in ("updated_at", "all_time", "rolling", "calibration", "recent"):
        assert key in b
    for key in ("n", "pct_1x2", "decisive_n", "exact_n", "brier"):
        assert key in b["all_time"]


# ---------------------------------------------------------------------------
# WC pre-match -helper: neutraali-venue-symmetria (peili predict_wc:stä)
# ---------------------------------------------------------------------------
def test_wc_prematch_symmetry():
    a = acc.wc_prematch_prediction("Brazil", "France")
    b = acc.wc_prematch_prediction("France", "Brazil")
    assert a is not None and b is not None
    assert a["p_home"] == pytest.approx(b["p_away"], abs=1e-9)
    assert a["p_away"] == pytest.approx(b["p_home"], abs=1e-9)
    assert a["p_draw"] == pytest.approx(b["p_draw"], abs=1e-9)
    assert a["xg_home"] == pytest.approx(b["xg_away"], abs=1e-9)
    assert a["xg_away"] == pytest.approx(b["xg_home"], abs=1e-9)
    # nimetty voittaja peilautuu
    assert {a["predicted_winner"], b["predicted_winner"]} <= {"home", "away"}


def test_wc_prematch_non_wc_team_returns_none():
    assert acc.wc_prematch_prediction("Finland", "Brazil") is None


# ---------------------------------------------------------------------------
# #110: domestic-liigat — nimiresolveri, opt-in-portti, logaus, by_competition
# ---------------------------------------------------------------------------
BSA_MODEL_TEAMS = [
    "Athletico-PR", "Atletico GO", "Atletico-MG", "Bahia", "Botafogo RJ",
    "Bragantino", "Ceara", "Chapecoense-SC", "Corinthians", "Coritiba",
    "Criciuma", "Cruzeiro", "Cuiaba", "Flamengo RJ", "Fluminense",
    "Fortaleza", "Gremio", "Internacional", "Juventude", "Mirassol",
    "Palmeiras", "Remo", "Santos", "Sao Paulo", "Sport Recife", "Vasco",
    "Vitoria",
]

# Live-FD:n BSA-nimet (verifioitu /api/fixtures-listasta 17.7) → odotettu
# mallinimi. Kattaa normalisointipolun (aksentit, klubi-tokenit) + overridet.
BSA_FD_TO_MODEL = {
    "Botafogo FR": "Botafogo RJ",
    "CA Mineiro": "Atletico-MG",
    "CA Paranaense": "Athletico-PR",
    "Chapecoense AF": "Chapecoense-SC",
    "Clube do Remo": "Remo",
    "Coritiba FBC": "Coritiba",
    "CR Flamengo": "Flamengo RJ",
    "Cruzeiro EC": "Cruzeiro",
    "EC Bahia": "Bahia",
    "EC Vitória": "Vitoria",
    "Fluminense FC": "Fluminense",
    "Grêmio FBPA": "Gremio",
    "Mirassol FC": "Mirassol",
    "RB Bragantino": "Bragantino",
    "São Paulo FC": "Sao Paulo",
    "SC Corinthians Paulista": "Corinthians",
    "SC Internacional": "Internacional",
    "SE Palmeiras": "Palmeiras",
    "Santos FC": "Santos",
    "Fortaleza EC": "Fortaleza",
    "CR Vasco da Gama": "Vasco",
}


def test_resolve_domestic_name_covers_live_bsa_names():
    from scripts.accuracy_pipeline import (
        DOMESTIC_COMPETITIONS, resolve_domestic_name,
    )
    overrides = DOMESTIC_COMPETITIONS["BSA"]["overrides"]
    for fd_name, expected in BSA_FD_TO_MODEL.items():
        got = resolve_domestic_name(fd_name, BSA_MODEL_TEAMS, overrides)
        assert got == expected, f"{fd_name!r}: odotettiin {expected!r}, saatiin {got!r}"


def test_resolve_domestic_name_unknown_returns_none():
    from scripts.accuracy_pipeline import resolve_domestic_name
    assert resolve_domestic_name("FC Nobody United", BSA_MODEL_TEAMS, {}) is None
    # Chapecoense ilman overrideä EI saa arvautua väärin normalisoinnilla —
    # "chapecoense" ⊆ "chapecoense sc" -osajoukko osuu yhteen kandidaattiin → OK,
    # mutta moniselitteinen ei koskaan: kaksi kandidaattia → None.
    assert resolve_domestic_name(
        "Atletico", ["Atletico-MG", "Atletico GO"], {}
    ) is None


def test_enabled_domestic_codes_gating(monkeypatch):
    from scripts import accuracy_pipeline as ap
    monkeypatch.delenv("ACC_DOMESTIC_COMPETITIONS", raising=False)
    assert ap.enabled_domestic_codes() == []          # oletus: OFF (GO-portti)
    monkeypatch.setenv("ACC_DOMESTIC_COMPETITIONS", "")
    assert ap.enabled_domestic_codes() == []
    monkeypatch.setenv("ACC_DOMESTIC_COMPETITIONS", "bsa, PL ,TYPO")
    assert ap.enabled_domestic_codes() == ["BSA", "PL"]  # typo ohitetaan


def _fd_match(mid, home, away, utc, status="TIMED", score=None):
    m = {
        "id": mid, "status": status, "utcDate": utc,
        "homeTeam": {"name": home}, "awayTeam": {"name": away},
    }
    if score is not None:
        m["status"] = "FINISHED"
        m["score"] = {"duration": "REGULAR",
                      "fullTime": {"home": score[0], "away": score[1]}}
    return m


def test_log_domestic_matches_prematch_only_and_idempotent():
    from datetime import datetime, timezone
    from scripts.accuracy_pipeline import log_domestic_matches

    now = datetime(2026, 7, 17, 12, 0, tzinfo=timezone.utc)
    matches = [
        _fd_match(1001, "EC Bahia", "Chapecoense AF", "2026-07-18T00:30:00Z"),
        # jo alkanut → EI logata jälkikäteen
        _fd_match(1002, "Fluminense FC", "RB Bragantino", "2026-07-17T00:30:00Z"),
        # nimi joka ei resolvoidu → skip, ei kaatumista
        _fd_match(1003, "FC Nobody United", "EC Bahia", "2026-07-19T00:30:00Z"),
        # pelattu → ei logata
        _fd_match(1004, "SE Palmeiras", "Cruzeiro EC", "2026-07-16T00:30:00Z",
                  score=(2, 0)),
    ]

    def fake_predict(league, home, away):
        assert league == "BRA-Serie A"
        return {
            "home_team": home, "away_team": away,
            "p_home": 0.5, "p_draw": 0.3, "p_away": 0.2,
            "xg_home": 1.4, "xg_away": 0.9,
            "most_likely_score": "1-0", "predicted_winner": "home",
        }

    log = acc.empty_log()
    added, skipped = log_domestic_matches(
        log, "BSA", matches, BSA_MODEL_TEAMS, fake_predict, now=now)
    assert added == 1 and skipped == 1
    e = log["predictions"][0]
    assert e["match_id"] == "fd-1001"
    assert e["competition"] == "BSA"
    assert e["league"] == "BRA-Serie A"
    assert e["home_team"] == "Bahia"
    assert e["away_team"] == "Chapecoense-SC"
    assert e["predicted_winner"] == "home"

    # idempotentti: toinen ajo ei duplikoi
    added2, _ = log_domestic_matches(
        log, "BSA", matches, BSA_MODEL_TEAMS, fake_predict, now=now)
    assert added2 == 0
    assert len(log["predictions"]) == 1


def test_domestic_reconcile_via_combined_matches():
    """WC-lokirivit + domestic-rivi reconciloituvat samasta yhdistelmälistasta
    eikä WC-riveihin kosketa (fd-id:t uniikkeja)."""
    from datetime import datetime, timezone
    from scripts.accuracy_pipeline import cmd_reconcile, log_domestic_matches

    now = datetime(2026, 7, 17, 12, 0, tzinfo=timezone.utc)
    log = acc.empty_log()
    # olemassa oleva WC-rivi (jo reconciloitu) — ei saa muuttua
    acc.upsert_prediction(log, _entry("fd-500", "home", mls="2-1"))
    acc.set_result(log, "fd-500", 2, 1)
    wc_before = dict(log["predictions"][0]["result"])

    matches = [_fd_match(1001, "EC Bahia", "Chapecoense AF",
                         "2026-07-18T00:30:00Z")]

    def fake_predict(league, home, away):
        return {"home_team": home, "away_team": away,
                "p_home": 0.5, "p_draw": 0.3, "p_away": 0.2,
                "xg_home": 1.4, "xg_away": 0.9,
                "most_likely_score": "1-0", "predicted_winner": "home"}

    log_domestic_matches(log, "BSA", matches, BSA_MODEL_TEAMS, fake_predict,
                         now=now)
    # ottelu pelataan: FINISHED 90 min 1-1 → named winner home = miss
    finished = [_fd_match(1001, "EC Bahia", "Chapecoense AF",
                          "2026-07-18T00:30:00Z", score=(1, 1))]
    cmd_reconcile(log, finished)
    dom = next(e for e in log["predictions"] if e["match_id"] == "fd-1001")
    assert dom["result"]["actual_outcome"] == "draw"
    assert dom["result"]["hit_1x2"] is False
    assert log["predictions"][0]["result"] == wc_before  # WC-rivi koskematon


def test_aggregate_by_competition_split():
    log = acc.empty_log()
    acc.upsert_prediction(log, _entry("w1", "home", mls="2-1"))      # WC
    acc.set_result(log, "w1", 2, 1)                                   # hit
    e = _entry("b1", "away", mls="0-1")
    e["competition"] = "BSA"
    acc.upsert_prediction(log, e)
    acc.set_result(log, "b1", 2, 0)                                   # miss
    agg = acc.compute_aggregate(log)
    assert agg["all_time"]["n"] == 2                                  # blended
    assert agg["all_time"]["correct_1x2"] == 1
    bc = agg["by_competition"]
    assert bc["WC"]["n"] == 1 and bc["WC"]["correct_1x2"] == 1        # WC säilyy
    assert bc["BSA"]["n"] == 1 and bc["BSA"]["correct_1x2"] == 0
