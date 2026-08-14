# -*- coding: utf-8 -*-
"""Etusivun (index.html) generoitujen lohkojen portit — scripts/build_fpl_page.py.

Kattaa "Live model projections" -taulukon: rivit tulevat xP-datasta ja
liputetut pelaajat rajataan pois. Negatiivinen kontrolli varmistaa etta portit
oikeasti suodattavat (ilman sita testi ei mittaisi mitaan).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# ---------------------------------------------------------------------------
# 1.8.2026: etusivun "Live model projections" -taulukko generoidaan datasta.
# Aiemmin kovakoodattu 24.7. ajosta samalla kun alaviite lupasi "refreshed
# daily". Karkirivilla oli pelaaja jonka FPL oli liputtanut loukkaantuneeksi.
# ---------------------------------------------------------------------------
def _xp_player(name, xp, status="a", chance=None, basis="pl_history"):
    return {"web_name": name, "team_short": "TST", "pos": "MID", "price": 6.0,
            "owned_pct": 5.0, "xp_horizon_total": xp, "status": status,
            "chance_next": chance, "data_basis": basis}


def test_xp_table_excludes_flagged_players():
    from scripts.build_fpl_page import xp_table_rows
    xp = {"meta": {"horizon_gw": 6}, "players": [
        _xp_player("Injured", 40.0, status="i", chance=0),
        _xp_player("Doubtful", 39.0, status="d", chance=25),
        _xp_player("Promoted", 38.0, basis="no_history"),
        _xp_player("Fit", 30.0),
    ]}
    html = xp_table_rows(xp, n=4)
    assert "Fit" in html
    # Negatiivinen kontrolli: jos portit eivat toimi, korkeamman xP:n nimet
    # nousevat karkeen ja etusivu suosittelee pelaajaa jota ei voi pelauttaa.
    for name in ("Injured", "Doubtful", "Promoted"):
        assert name not in html, f"{name} paasi etusivun taulukkoon"


# ---------------------------------------------------------------------------
# 10.8.2026: vaihtuvuusluku oli 5. sarakkeessa, joka on .m-hide eli piilossa
# kapealla naytolla — eli poissa siita pinnasta jolla FPL-liikenne on. Luku
# tulee riville .m-only-alarivina ja katoaa kun sarake palautetaan.
# ---------------------------------------------------------------------------
def _cs_row(team, cs_pct, opponent, venue, fdr):
    return {"team": team, "cs_pct": cs_pct, "opponent": opponent,
            "venue": venue, "fdr": fdr}


def test_cs_table_turnover_reaches_narrow_screen(monkeypatch):
    from scripts import build_fpl_page as bp
    from scripts.build_fpl_phase0 import map_name
    monkeypatch.setattr(bp, "_turnover_by_model_team", lambda: {
        map_name("Brighton & Hove Albion"): {"is_promoted": False,
                                             "minutes_churn_pct": 21.4},
        map_name("Coventry City"): {"is_promoted": True,
                                    "minutes_churn_pct": None},
    })
    html = bp.cs_table_html({
        "next_gw": 1, "season": "2026/27", "cs_rows": [
            _cs_row("Brighton & Hove Albion", 34.0, "Aston Villa", "H", 2),
            _cs_row("Coventry City", 6.4, "Arsenal", "A", 5),
            _cs_row("Tuntematon FC", 20.0, "Arsenal", "H", 4),
        ]})
    # Luku on rivilla ILMAN etta sarake tarvitsee palauttaa...
    assert '<span class="m-only m-sub">21% turnover</span>' in html
    # 14.8: teksti oli "no PL record", mutta se oli VAARA — Ipswich pelasi
    # PL:aa 24/25 ja on osa mitattua nousijabaselinea. Nyt merkinta kertoo
    # mika on totta: naillä ei ole omaa luokitusta nykyisesta fit-ikkunasta.
    assert '<span class="m-only m-sub">baseline rating</span>' in html
    # ...ja sarake on yha paikallaan leveille naytoille.
    assert '<td class="num m-hide">21%</td>' in html
    # Negatiivinen kontrolli: ilman tata testi menisi lapi myos jos alarivi
    # liimattaisiin jokaiseen riviin datasta riippumatta.
    assert html.count('class="m-only m-sub"') == 2, "alarivi ilman dataa"
    assert "Tuntematon FC" in html


def test_xp_table_foot_states_horizon_not_daily_promise():
    from scripts.build_fpl_page import xp_table_rows
    html = xp_table_rows({"meta": {"horizon_gw": 6},
                          "players": [_xp_player("Fit", 30.0)]}, n=1)
    assert "next 6 gameweeks" in html
    assert "refreshed daily" not in html
