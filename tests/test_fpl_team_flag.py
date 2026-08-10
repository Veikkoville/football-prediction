# -*- coding: utf-8 -*-
"""Joukkuetason luottamuslippu xP-riveilla (10.8.2026).

TAUSTA: r/FantasyPL-lukija pyysi lippua nimenomaan PROJEKTIOIHIN. 9.8. lippu
shipattiin ottelupolulle ja CS/FDR-taulukkoon, mutta xP-lista jai ilman.
Lippu kiinnitetaan artefaktiin (build_fpl_xp) eika rendereihin, jotta SPA,
mobiili ja molemmat web-sivut lukevat saman lahteen.

Portit tassa vastaavat kahteen kysymykseen:
  1. merkitaanko VAIN liputetut (ei kaikkia 20 joukkuetta)
  2. kaatuuko ajo jos liitos hajoaa (vs. hiljainen "ei liputettavia")
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _conf_doc():
    return {
        "schema_version": 1,
        "high_turnover_threshold_pct": 25.0,
        "historical_median_pct": 13.0,
        "method": "test",
        "teams": [
            {"model_team": "Arsenal", "is_promoted": False,
             "minutes_churn_pct": 5.6, "flag": None, "note": "6% left."},
            {"model_team": "Brighton", "is_promoted": False,
             "minutes_churn_pct": 31.0, "flag": "high_turnover",
             "note": "31% left."},
            {"model_team": "Coventry", "is_promoted": True,
             "minutes_churn_pct": None, "flag": "promoted",
             "note": "Promoted side."},
        ],
    }


def _write_conf(tmp_path, monkeypatch, doc):
    import config
    from scripts import build_fpl_xp as b
    (tmp_path / "data").mkdir(exist_ok=True)
    (tmp_path / "data" / "team_confidence.json").write_text(
        json.dumps(doc), encoding="utf-8")
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(b.config, "PROJECT_ROOT", tmp_path)


def test_only_flagged_teams_get_a_row_field(tmp_path, monkeypatch):
    from scripts.build_fpl_xp import attach_team_confidence
    _write_conf(tmp_path, monkeypatch, _conf_doc())
    players = [
        {"web_name": "Saka", "team": "Arsenal"},
        {"web_name": "Mitoma", "team": "Brighton"},
        {"web_name": "Wright", "team": "Coventry"},
    ]
    meta = attach_team_confidence(players)

    assert players[1]["team_flag"] == "high_turnover"
    assert players[2]["team_flag"] == "promoted"
    # Negatiivinen kontrolli: ilman tata testi menisi lapi myos jos kenttä
    # liimattaisiin JOKAISELLE riville. Liputtamaton ei saa kenttaa lainkaan,
    # jotta klientin `if (p.team_flag)` riittaa eika 17 joukkuetta saa tagia.
    assert "team_flag" not in players[0]
    assert meta["n_flagged_players"] == 2
    assert meta["high_turnover_threshold_pct"] == 25.0
    # Koko taulukko metaan, jotta pinta voi nayttaa myos luvun ilman uutta
    # liitosta.
    assert meta["teams"]["Arsenal"]["minutes_churn_pct"] == 5.6


def test_broken_join_crashes_instead_of_silently_flagging_nothing(
        tmp_path, monkeypatch):
    """Rikkoutunut liitos EI saa nayttaa samalta kuin 'ei liputettavia'.

    Tama on sama vikaluokka joka 9.8. tappoi kaikki vs_promoted-slicet
    aanettomasti: nolla osumaa nayttaa raportissa tyhjalta tulokselta.
    """
    from scripts.build_fpl_xp import attach_team_confidence
    _write_conf(tmp_path, monkeypatch, _conf_doc())
    players = [{"web_name": "X", "team": "Arsenal FC"}]  # vaara nimimuoto
    with pytest.raises(SystemExit, match="model_team-liitos on rikki"):
        attach_team_confidence(players)


def test_missing_artifact_is_survivable_but_loud(tmp_path, monkeypatch, capsys):
    """Puuttuva team_confidence.json ei saa kaataa xP-buildia."""
    from scripts.build_fpl_xp import attach_team_confidence
    import config
    from scripts import build_fpl_xp as b
    (tmp_path / "data").mkdir(exist_ok=True)
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(b.config, "PROJECT_ROOT", tmp_path)
    players = [{"web_name": "X", "team": "Arsenal"}]

    assert attach_team_confidence(players) == {}
    assert "team_flag" not in players[0]
    assert "VAROITUS" in capsys.readouterr().out


def test_page_note_says_when_no_flagged_player_is_visible():
    """Selite ei saa luvata merkkia jota taulukossa ei ole.

    Liputetut ovat nousijoiden pelaajia eivatka yla top 100:aan (paras #129),
    joten ensimmainen versio selitti tagin jota lukija ei loydä mistaan.
    """
    from scripts.build_fpl_longtail import _tflag_html, _tflag_note
    xp = {"meta": {"team_confidence": {"teams": {
        "Coventry": {"flag": "promoted"},
        "Arsenal": {"flag": None},
    }}}}
    allrows = ([{"web_name": "Saka", "team_short": "ARS"}] * 3
               + [{"web_name": "Wright", "team_short": "COV",
                   "team_flag": "promoted"}])
    note = _tflag_note(xp, allrows[:3], allrows)

    assert "Coventry" in note
    assert "No flagged player makes this top 100" in note
    assert "#4 of 4" in note
    # Suuntavaite on kielletty: kalibrointi kaatui (R^2 0,000 / vaara merkki).
    assert "does not say which way" in note
    for banned in ("weaker team", "worse", "will score"):
        assert banned not in note

    # Kun liputettu NAKYY, selite kertoo maaran eika puutetta.
    note2 = _tflag_note(xp, allrows, allrows)
    assert "1 of them" in note2
    assert "No flagged player" not in note2

    assert _tflag_html({"team_flag": "promoted"}) == (
        '<span class="tflag">promoted</span>')
    assert _tflag_html({}) == ""
