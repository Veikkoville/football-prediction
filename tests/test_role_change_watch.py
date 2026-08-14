"""Portit roolimuutosvahdille.

Vahdin arvo on siina etta se loytaa Kinsky-luokan vian ILMAN etta kukaan
lukee artikkelia sattumalta. Siksi jokaiselle suunnalle on seka positiivinen
etta negatiivinen kontrolli: testi joka osoittaa etta seula loytaa kun sen
kuuluu JA vaikenee kun sen kuuluu.
"""
from __future__ import annotations

import pytest

from scripts import role_change_watch as w


def el(pid, name, et=1, owned="10.0", status="a", team=1):
    return {"id": pid, "web_name": name, "element_type": et,
            "selected_by_percent": owned, "status": status, "team": team}


def mine(pid, name, p_start, xp6=5.0, owned=10.0, pos="GKP", team="TOT"):
    return {"id": pid, "web_name": name, "p_start": p_start,
            "xp_horizon_total": xp6, "owned_pct": owned, "pos": pos,
            "team_short": team}


# --------------------------------------------------------------------------
# Suunta A1 — omistettu mutta ei riviä (Kinsky-luokka)
# --------------------------------------------------------------------------

def test_a1_finds_owned_player_with_no_row():
    """Kinsky oli 19,5 % omistettu ja puuttui projektiosta KOKONAAN."""
    a1, _ = w.direction_a({}, [el(1, "Kinsky", owned="19.5")], 0.5, 0.35, {})
    assert [r["web_name"] for r in a1] == ["Kinsky"]


def test_a1_ignores_low_ownership():
    a1, _ = w.direction_a({}, [el(1, "Nobody", owned="0.1")], 0.5, 0.35, {})
    assert a1 == []


def test_a1_ignores_unavailable_but_not_available():
    """NEGATIIVINEN + POSITIIVINEN SAMASSA. Saatavuuslippu (i/s/u) kattaa
    loukkaantumiset jo, joten niita ei liputeta uudelleen — mutta **Kinskyn
    lippu oli 'a'**, ja juuri se tapaus on taman vahdin koko olemassaolon
    syy. Jos statussuodatin joskus laajenee, tama testi kaatuu."""
    injured = el(1, "Injured", owned="19.5", status="i")
    fit = el(2, "Fit", owned="19.5", status="a")
    a1, _ = w.direction_a({}, [injured, fit], 0.5, 0.35, {})
    assert [r["web_name"] for r in a1] == ["Fit"]


# --------------------------------------------------------------------------
# Suunta A2 — rivi on, mutta p_start on matala
# --------------------------------------------------------------------------

def test_a2_ranks_by_disagreement_mass_not_raw_ownership():
    """NEGATIIVINEN KONTROLLI LAJITTELULLE. Pelkalla omistuksella karkeen
    nousi varamaalivahteja joiden matala p_start on OIKEIN. Massa
    (omistus x (1 - p_start)) laskee ne alas: 20 %:n varamies jonka
    p_start on 0.02 on vahemman ristiriitainen kuin 15 %:n pelaaja jonka
    p_start on 0.30 vain jos malli on hanesta varma — tassa se ei ole,
    joten jarjestys maaraytyy massasta eika omistuksesta."""
    ours = {
        1: mine(1, "HighOwnBackup", p_start=0.02, owned=20.0),
        2: mine(2, "MidOwnDoubt", p_start=0.30, owned=18.0),
    }
    els = [el(1, "HighOwnBackup", owned="20.0"),
           el(2, "MidOwnDoubt", owned="18.0")]
    _, a2 = w.direction_a(ours, els, 0.5, 0.35, {})
    masses = [round(r["mass"], 2) for r in a2]
    assert masses == sorted(masses, reverse=True), "ei lajiteltu massalla"
    assert a2[0]["web_name"] == "HighOwnBackup"   # 20*0.98=19.6 > 18*0.70=12.6


def test_a2_ignores_confident_starter():
    ours = {1: mine(1, "Starter", p_start=0.95, owned=40.0)}
    _, a2 = w.direction_a(ours, [el(1, "Starter", owned="40.0")], 0.5, 0.35, {})
    assert a2 == []


# --------------------------------------------------------------------------
# Suunta A3 — seuran sisäinen ristiriita (Kinsky/Dubravka-kuvio)
# --------------------------------------------------------------------------

def test_a3_flags_club_internal_contradiction():
    """Markkina omistaa eri maalivahtia kuin malli pitaa ykkosena."""
    ours = {1: mine(1, "Dubravka", p_start=0.08, owned=22.4),
            2: mine(2, "Kinsky", p_start=0.90, owned=19.6)}
    els = [el(1, "Dubravka", owned="22.4", team=17),
           el(2, "Kinsky", owned="19.6", team=17)]
    out = w.direction_a3(ours, els, {})
    assert len(out) == 1
    assert out[0]["market"]["web_name"] == "Dubravka"
    assert out[0]["model"]["web_name"] == "Kinsky"


def test_a3_silent_when_market_and_model_agree():
    """NEGATIIVINEN KONTROLLI. Jos omistetuin ON se jolla on korkein
    p_start, ristiriitaa ei ole eika vahti saa huutaa."""
    ours = {1: mine(1, "No1", p_start=0.92, owned=30.0),
            2: mine(2, "Backup", p_start=0.08, owned=1.0)}
    els = [el(1, "No1", owned="30.0", team=17),
           el(2, "Backup", owned="1.0", team=17)]
    assert w.direction_a3(ours, els, {}) == []


def test_a3_marks_known_cases_instead_of_hiding_them():
    """Jo ohitettu tapaus EI katoa listalta vaan merkitaan. Piilottaminen
    veisi positiivisen kontrollin: silloin tyhja lista voisi tarkoittaa
    joko 'ei loydoksia' tai 'seula on rikki'."""
    ours = {1: mine(1, "Dubravka", p_start=0.08, owned=22.4),
            2: mine(2, "Kinsky", p_start=0.90, owned=19.6)}
    els = [el(1, "Dubravka", owned="22.4", team=17),
           el(2, "Kinsky", owned="19.6", team=17)]
    out = w.direction_a3(ours, els, {1: {"p_start": 0.08}})
    assert len(out) == 1 and out[0]["overridden"] is True


# --------------------------------------------------------------------------
# Suunta B
# --------------------------------------------------------------------------

def test_b_finds_high_xp_low_ownership():
    ours = {1: mine(1, "Struijk", p_start=0.86, xp6=23.8, owned=0.4, pos="DEF")}
    out = w.direction_b(ours, 12.0, 1.0, {})
    assert [r["web_name"] for r in out] == ["Struijk"]


def test_b_ignores_well_owned():
    ours = {1: mine(1, "Popular", p_start=0.9, xp6=30.0, owned=45.0)}
    assert w.direction_b(ours, 12.0, 1.0, {}) == []


# --------------------------------------------------------------------------
# Vahdin oma rehellisyys
# --------------------------------------------------------------------------

def test_bootstrap_failure_is_loud_not_silent(monkeypatch, capsys):
    """Vahti joka ei voi tehda puolta tyostaan on RIKKI, ei 'osittain
    ajettu'. Sama vikaluokka kuin render-daily-deployn hiljainen vihrea,
    joka raportoi onnistuneeksi tekematta mitaan joka ajossa."""
    monkeypatch.setattr(w, "load_projection", lambda: ({}, {}))
    monkeypatch.setattr(w, "load_player_overrides", lambda: ({}, []))
    monkeypatch.setattr(w, "fetch_bootstrap",
                        lambda: (_ for _ in ()).throw(RuntimeError("verkko")))
    monkeypatch.setattr("sys.argv", ["x"])
    assert w.main() == 1
    assert "::error::" in capsys.readouterr().out


# --------------------------------------------------------------------------
# Suunta A4 — epäselvä peliaika (Villen kysymys: "siirtyneitä jne")
# --------------------------------------------------------------------------

def test_a4_flags_owned_player_the_model_is_unsure_about():
    """Bruno G -luokka: rivi ON (A1 ei nappaa), p_start 0,63 (A2 ei nappaa),
    ei maalivahti (A3 ei nappaa) — mutta malli itse sanoo `med` ja 10,3 %
    omistaa. Ilman tata suuntaa seuranvaihtaja putoaa kaikkien lapi."""
    ours = {1: dict(mine(1, "BrunoG", p_start=0.63, xp6=19.0, owned=10.3,
                         pos="MID", team="ARS"),
                    minutes_confidence="med", data_basis="pl_history")}
    out = w.direction_a4(ours, {}, min_owned=2.0)
    assert [r["web_name"] for r in out] == ["BrunoG"]


def test_a4_silent_when_model_is_confident():
    """NEGATIIVINEN KONTROLLI. Korkea omistus EI riita — malli on varma."""
    ours = {1: dict(mine(1, "Nailed", p_start=0.97, owned=60.0),
                    minutes_confidence="high", data_basis="pl_history")}
    assert w.direction_a4(ours, {}, min_owned=2.0) == []


def test_a4_missing_history_outweighs_medium_confidence():
    """`no_history` on isompi epavarmuus kuin `med`: tuntematon pelaaja
    tuntemattomassa roolissa. Painotus lukee mallin OMIA kenttia eika
    keksi omaa lukua (Villen 14.8 lukitus)."""
    ours = {
        1: dict(mine(1, "Unknown", p_start=0.4, owned=10.0),
                minutes_confidence="high", data_basis="no_history"),
        2: dict(mine(2, "MediumConf", p_start=0.4, owned=10.0),
                minutes_confidence="med", data_basis="pl_history"),
    }
    out = w.direction_a4(ours, {}, min_owned=2.0)
    assert out[0]["web_name"] == "Unknown"
    assert out[0]["mass"] > out[1]["mass"]


# --------------------------------------------------------------------------
# Suunta A5 — seura heikentynyt (Villen havainto: "jos joukkue heikentynyt
# niin arvioi uusiksi noita ennusteita")
# --------------------------------------------------------------------------

def _meta(churn_by_team, thr=25.0):
    return {"team_confidence": {
        "high_turnover_threshold_pct": thr,
        "teams": {k: {"minutes_churn_pct": v,
                      "flag": "high_turnover" if v >= thr else None}
                  for k, v in churn_by_team.items()},
    }}


def test_a5_flags_players_at_gutted_clubs():
    """A1-A4 katsovat PELAAJAA. A5 katsoo JOUKKUETTA jonka varassa pelaajan
    luku lepaa. Newcastle on mitattu esimerkki: 25,2 % minuuteista lahtenyt
    (Isak, Bruno G, Gordon) ja silti Thiaw on mallin mukaan liigan paras
    halpa pelaaja."""
    ours = {1: dict(mine(1, "Thiaw", p_start=0.9, xp6=27.0, owned=2.0,
                         pos="DEF", team="NEW"), team="Newcastle United")}
    out = w.direction_a5(ours, _meta({"Newcastle United": 25.2}), {}, 15.0)
    assert [r["web_name"] for r in out] == ["Thiaw"]
    assert out[0]["churn"] == 25.2


def test_a5_silent_for_stable_clubs():
    """NEGATIIVINEN KONTROLLI. Korkea xP EI riita — seuran on oltava
    heikentynyt. Arsenal menetti 5,6 % minuuteista eika kuulu listalle."""
    ours = {1: dict(mine(1, "Gabriel", p_start=0.95, xp6=30.9, owned=20.0,
                         pos="DEF", team="ARS"), team="Arsenal")}
    assert w.direction_a5(ours, _meta({"Arsenal": 5.6}), {}, 15.0) == []


def test_a5_ignores_low_xp_at_gutted_club():
    """Heikentynyt seura ei yksin riita: jos luku on pieni, se ei ole
    suositus eika sen uudelleenarviointi ole kiireellista."""
    ours = {1: dict(mine(1, "Bench", p_start=0.3, xp6=4.0, owned=1.0,
                         pos="DEF", team="NEW"), team="Newcastle United")}
    assert w.direction_a5(ours, _meta({"Newcastle United": 25.2}), {}, 15.0) == []
