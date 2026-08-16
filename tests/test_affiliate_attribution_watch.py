"""Tasmaytysvahdin testit (scripts/check_affiliate_attribution.py).

Vahdin koko arvo on siina etta se EROTTAA kolme tilaa toisistaan: tasmaa,
vuotaa, ja "ei voitu mitata". Jos mittaamattomuus palauttaisi 0:n, vahti olisi
haitallinen — se vakuuttaisi etta kaikki on kunnossa juuri silloin kun mitaan
ei tiedeta. Siksi jokaiselle exit-koodille on oma testi.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "check_affiliate_attribution",
    Path(__file__).resolve().parents[1] / "scripts" / "check_affiliate_attribution.py",
)
watch = importlib.util.module_from_spec(_SPEC)
sys.modules["check_affiliate_attribution"] = watch
_SPEC.loader.exec_module(watch)


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_dummy")


def _codes(monkeypatch, rows):
    monkeypatch.setattr(watch, "_fetch_promotion_codes", lambda: rows)


def test_matching_counts_exit_0(monkeypatch, capsys):
    _codes(monkeypatch, [{"code": "ROWAN", "times_redeemed": 3}])
    monkeypatch.setattr(watch, "_count_stamped", lambda c: (3, 0, 0))
    assert watch.main() == 0
    assert "täsmäävät" in capsys.readouterr().out


def test_missing_stamp_is_a_leak_exit_1(monkeypatch, capsys):
    """Lunastuksia enemman kuin leimoja = provisio jaisi maksamatta."""
    _codes(monkeypatch, [{"code": "ROWAN", "times_redeemed": 5}])
    monkeypatch.setattr(watch, "_count_stamped", lambda c: (3, 0, 0))
    assert watch.main() == 1
    out = capsys.readouterr().out
    assert "VUOTO" in out and "2 lunastusta ilman leimaa" in out
    assert "::error::" in out, "vuodon on huudettava error-tasolla, ei warningina"


def test_extra_stamps_are_impossible_exit_1(monkeypatch, capsys):
    """Leimoja enemman kuin lunastuksia = maksaisimme LIIKAA provisiota.

    Tama on eri vika kuin vuoto ja se on pahempi, joten se raportoidaan
    eri sanoilla eika niputeta samaan.
    """
    _codes(monkeypatch, [{"code": "ROWAN", "times_redeemed": 1}])
    monkeypatch.setattr(watch, "_count_stamped", lambda c: (4, 0, 0))
    assert watch.main() == 1
    assert "MAHDOTON" in capsys.readouterr().out


def test_missing_key_is_exit_2_not_pass(monkeypatch, capsys):
    """EI VOITU MITATA ei ole PASS.

    Ilman tata vahti olisi vihrea silloin kun avain puuttuu CI:sta — eli
    tasan silloin kun se ei mittaa mitaan. Muisti
    `accuracy-log-403-gh-runners`.
    """
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    assert watch.main() == 2
    assert "::error::" in capsys.readouterr().out


def test_stripe_error_is_exit_2(monkeypatch, capsys):
    def _boom():
        raise RuntimeError("Stripe alhaalla")
    monkeypatch.setattr(watch, "_fetch_promotion_codes", _boom)
    assert watch.main() == 2
    assert "::error::" in capsys.readouterr().out


def test_no_codes_at_all_is_exit_2(monkeypatch):
    """Nolla promokoodia on odottamaton tila, ei tyhja PASS.

    Kupongit ovat olemassa (ROWAN, EARLY30). Jos lista on tyhja, kysely meni
    vaaraan tiliin tai avaimella ei ole oikeuksia — kumpikin on
    mittaamattomuus eika 'kaikki hyvin'.
    """
    _codes(monkeypatch, [])
    assert watch.main() == 2


def test_several_codes_only_broken_one_reported(monkeypatch, capsys):
    """NEGATIIVINEN KONTROLLI: tasmaava koodi ei saa laukaista halytysta.

    Ilman tata lapaisisi toteutus joka huutaa aina, ja sellainen vahti
    opetetaan ohittamaan.
    """
    _codes(monkeypatch, [
        {"code": "EARLY30", "times_redeemed": 2},
        {"code": "ROWAN", "times_redeemed": 4},
    ])
    monkeypatch.setattr(watch, "_count_stamped",
                        lambda c: (2, 0, 0) if c == "EARLY30" else (1, 0, 0))
    assert watch.main() == 1
    out = capsys.readouterr().out
    assert "::error::ROWAN" in out
    assert "::error::EARLY30" not in out


def test_per_code_lookup_failure_does_not_hide_others(monkeypatch, capsys):
    """Yhden koodin haun kaatuminen ei saa keskeyttaa muiden mittausta."""
    _codes(monkeypatch, [
        {"code": "EARLY30", "times_redeemed": 2},
        {"code": "ROWAN", "times_redeemed": 2},
    ])

    def _lookup(c):
        if c == "EARLY30":
            raise RuntimeError("search API alhaalla")
        return 2, 0, 0

    monkeypatch.setattr(watch, "_count_stamped", _lookup)
    assert watch.main() == 1
    out = capsys.readouterr().out
    assert "EI MITATTAVISSA" in out
    assert "ROWAN" in out, "toisen koodin mittauksen on silti nayttava"


def test_ref_stamps_do_not_trigger_the_impossible_alarm(monkeypatch, capsys):
    """🔴 Tama on koko lahde-erottelun syy (16.8.2026).

    Luojan katsoja tulee linkista, luo ilmaisen tilin ikkunan aikana ja
    maksaa 12.9. jalkeen taytta hintaa ilman koodia. Leima syntyy,
    lunastusta ei tapahdu. Ennen erottelua tama tuotti `stamped > redeemed`
    eli MAHDOTON + exit 1 - punainen halytys tilanteessa jossa kaikki toimi
    tasan oikein, ja juuri ennen GW19:n ensimmaista payoutia.
    """
    _codes(monkeypatch, [{"code": "WOLFY", "times_redeemed": 2}])
    # 2 kuponkilunastusta leimattu + 5 linkkiattribuutiota.
    monkeypatch.setattr(watch, "_count_stamped", lambda c: (2, 5, 0))
    assert watch.main() == 0, "ref-leimat laukaisivat halytyksen"
    out = capsys.readouterr().out
    assert "MAHDOTON" not in out
    assert "5 linkkiattribuutiota" in out, (
        "ref-leimat pitaa RAPORTOIDA vaikka niita ei verrata; muuten ne "
        "katoavat nakyvista eika kukaan huomaa jos ne lakkaavat syntymasta")


def test_leak_is_still_caught_when_ref_stamps_exist(monkeypatch, capsys):
    """Negatiivinen kontrolli: erottelu ei saa vaimentaa oikeaa vuotoa.

    Ilman tata korjaus voisi olla se etta vahti lakkaa halyttamasta
    kokonaan - mika olisi pahempi kuin alkuperainen vika."""
    _codes(monkeypatch, [{"code": "WOLFY", "times_redeemed": 5}])
    monkeypatch.setattr(watch, "_count_stamped", lambda c: (3, 9, 0))
    assert watch.main() == 1, "2 lunastusta ilman leimaa jai huomaamatta"
    assert "VUOTO" in capsys.readouterr().out


def test_pre_split_stamps_count_as_coupon(monkeypatch, capsys):
    """Ennen 16.8 kirjoitetuissa leimoissa ei ole lahdetta. Ref-polkua ei
    ollut olemassa, joten ne ovat kuponkiperaisia - ja jos ne laskettaisiin
    vertailun ulkopuolelle, vahti raportoisi vuotoa jota ei ole."""
    _codes(monkeypatch, [{"code": "ROWAN", "times_redeemed": 3}])
    monkeypatch.setattr(watch, "_count_stamped", lambda c: (0, 0, 3))
    assert watch.main() == 0
    assert "VUOTO" not in capsys.readouterr().out
