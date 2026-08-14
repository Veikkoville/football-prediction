"""Portit vahdille joka vertaa FPL-tilin rivia jaadytettyyn runkoon.

Vahdin koko arvo on siina etta se KAATUU kun rivit eroavat. Siksi jokaiselle
vihrealle haaralle on negatiivinen kontrolli: testi joka osoittaa etta sama
koodipolku palauttaa 1 kun sen kuuluu.

Tausta: entryn rivi valittiin kasin 23.7, ENNEN 13.8:n P0-korjausta joka
muutti mallin XI:n. Mikaan ei huomannut eroa, koska mikaan ei katsonut.
"""
from __future__ import annotations

import datetime as _dt
import json

import pytest

from scripts import verify_model_entry_matches_freeze as w


def _frozen(gw: int, deadline: _dt.datetime, ids: list[int],
            captain: int) -> dict:
    xi = [{"id": i, "web_name": f"P{i}", "team_short": "XXX", "pos": 3,
           "club": "X", "price": 50, "xp": 1.0} for i in ids[:11]]
    bench = [{"id": i, "web_name": f"P{i}", "team_short": "XXX", "pos": 3,
              "club": "X", "price": 40, "xp": 0.5} for i in ids[11:]]
    return {
        "meta": {"gw": gw, "deadline": deadline.strftime("%Y-%m-%dT%H:%M:%SZ"),
                 "frozen_at": "2026-08-20T12:00:00Z"},
        "captain": captain, "vice_captain": ids[1],
        "xi": xi, "bench": bench,
    }


@pytest.fixture
def frozen_dir(tmp_path, monkeypatch):
    d = tmp_path / "model_squad_frozen"
    d.mkdir()
    monkeypatch.setattr(w, "FROZEN_DIR", d)
    return d


def _write(d, gw, deadline, ids, captain=101):
    (d / f"gw{gw}.json").write_text(
        json.dumps(_frozen(gw, deadline, ids, captain)), encoding="utf-8")


IDS = list(range(101, 116))          # 15 pelaajaa
# HUOM: GW1:n oikea deadline (21.8.2026) on TULEVAISUUDESSA kun tama
# kirjoitettiin, joten sita ei voi kayttaa "mennyt deadline" -tapauksena.
# Ensimmainen versio kaytti sita ja kolme testia ajoi hiljaa vaaraan
# haaraan — ne olisivat menneet vihreiksi vasta 21.8 ja vaarin perustein.
PAST = _dt.datetime(2020, 8, 21, 17, 30, tzinfo=_dt.timezone.utc)
FUTURE = _dt.datetime(2099, 1, 1, 12, 0, tzinfo=_dt.timezone.utc)


def test_no_freeze_is_not_an_error(frozen_dir, monkeypatch):
    """Ennen kauden ensimmaista freezea hakemisto on tyhja. Se EI ole vika."""
    monkeypatch.setattr("sys.argv", ["x"])
    assert w.main() == 0


def test_before_deadline_prints_squad_and_passes(frozen_dir, monkeypatch, capsys):
    """Rivin syottaminen on kasityota, joten puuttuva syotto ei ole viela
    virhe — mutta tuloste on annettava syotettavassa muodossa."""
    _write(frozen_dir, 1, FUTURE, IDS)
    monkeypatch.setattr("sys.argv", ["x"])
    assert w.main() == 0
    out = capsys.readouterr().out
    assert "KAPTEENI" in out
    assert "PENKKI" in out
    assert "P101" in out


def test_after_deadline_match_passes(frozen_dir, monkeypatch):
    _write(frozen_dir, 1, PAST, IDS)
    monkeypatch.setattr(w, "fetch_picks", lambda e, g: (
        [{"element": i, "is_captain": i == 101} for i in IDS], "200"))
    monkeypatch.setattr("sys.argv", ["x"])
    assert w.main() == 0


def test_after_deadline_mismatch_fails(frozen_dir, monkeypatch, capsys):
    """NEGATIIVINEN KONTROLLI. Tama on koko vahdin olemassaolon syy: yksi
    vaara pelaaja tilillä = julkinen vaite osoittaa joukkueeseen jota malli
    ei valinnut."""
    _write(frozen_dir, 1, PAST, IDS)
    wrong = IDS[:-1] + [999]
    monkeypatch.setattr(w, "fetch_picks", lambda e, g: (
        [{"element": i, "is_captain": i == 101} for i in wrong], "200"))
    monkeypatch.setattr("sys.argv", ["x"])
    assert w.main() == 1
    out = capsys.readouterr().out
    assert "EI VASTAA" in out
    assert "P115" in out       # jaadytetyssa mutta ei tilillä
    assert "999" in out        # tilillä mutta ei jaadytetyssa


def test_captain_difference_alone_fails(frozen_dir, monkeypatch, capsys):
    """15/15 voi tasmata ja rivi olla silti vaara: kapteeni on
    kaksinkertainen pistevaikutus."""
    _write(frozen_dir, 1, PAST, IDS, captain=101)
    monkeypatch.setattr(w, "fetch_picks", lambda e, g: (
        [{"element": i, "is_captain": i == 102} for i in IDS], "200"))
    monkeypatch.setattr("sys.argv", ["x"])
    assert w.main() == 1
    assert "KAPTEENI eroaa" in capsys.readouterr().out


def test_missing_picks_after_deadline_fails(frozen_dir, monkeypatch):
    """404 ENNEN deadlinea on normaali; deadlinen JALKEEN se tarkoittaa
    ettei tilia ole pelattu — ja silloin koko kausikisa on tyhja."""
    _write(frozen_dir, 1, PAST, IDS)
    monkeypatch.setattr(w, "fetch_picks", lambda e, g: (None, "404"))
    monkeypatch.setattr("sys.argv", ["x"])
    assert w.main() == 1


def test_latest_frozen_sorts_numerically(frozen_dir):
    """gw10 > gw9. Merkkijonolajittelu antaisi gw9:n ja vahti vertaisi
    vaaraa kierrosta koko loppukauden."""
    for gw in (2, 9, 10):
        _write(frozen_dir, gw, PAST, IDS)
    assert w.latest_frozen().name == "gw10.json"
