"""Ref-leima ei saa nayttaa kuponkilunastukselta (16.8.2026).

MITATTU RISKI, ei viela tapahtunut vahinko - ja siksi tama on kirjoitettu
ENNEN ensimmaista ref-attribuoitua maksua.

`check_affiliate_attribution.py` vertaa leimattuja tilauksia Stripen
`times_redeemed`-laskuriin ja kutsuu tilaa `stamped > redeemed`
MAHDOTTOMAKSI (exit 1). Se oli oikein niin kauan kuin leima saattoi syntya
vain kupongin kaytosta.

16.8 rakennettu ref-polku tuottaa leiman ILMAN lunastusta: luojan katsoja
tulee linkista, luo ilmaisen tilin GW1-GW3-ikkunan aikana ja maksaa 12.9.
jalkeen taytta hintaa ilman koodia. Ensimmainen sellainen maksu olisi
tehnyt vahdista punaisen tilanteessa jossa kaikki toimi oikein.

🔴 MIKSI TAMA EI OLLUT LYKATTAVISSA. `_stamp_affiliate` kirjoitti
molemmissa tapauksissa saman muodon `{"affiliate": KOODI}`, eika lahdetta
voi paatella jalkikateen: kupongit ovat `duration: once`, joten alennus
irtoaa ensimmaisen laskun jalkeen eika tilauksesta enaa nae kaytettiinko
koodia. Ilman lahdekenttaa kirjoitettu leima jaa PYSYVASTI
tulkinnanvaraiseksi, ja GW19:n payout perustuisi arvaukseen.
"""
from __future__ import annotations

import pathlib
import re

import api.main as m

ROOT = pathlib.Path(__file__).resolve().parents[1]
WATCHDOG = ROOT / "scripts" / "check_affiliate_attribution.py"


def test_promo_path_reports_promo_source():
    session = {"discounts": [{"promotion_code": "promo_x"}]}
    m_code = m._affiliate_code_from_session
    orig = m._promo_code_string
    try:
        m._promo_code_string = lambda p: "WOLFY"
        assert m_code(session) == ("WOLFY", "promo")
    finally:
        m._promo_code_string = orig


def test_link_path_reports_ref_source():
    session = {"discounts": [], "subscription": None,
               "metadata": {"ref": "WOLFY"}}
    assert m._affiliate_code_from_session(session) == ("WOLFY", "ref")


def test_account_path_reports_ref_source(monkeypatch):
    monkeypatch.setattr(m, "_account_affiliate_ref", lambda uid: "DAZ")
    session = {"discounts": [], "subscription": None, "metadata": {},
               "client_reference_id": "u1"}
    assert m._affiliate_code_from_session(session) == ("DAZ", "ref")


def test_stamp_writes_the_source(monkeypatch):
    """Lahde on kirjoitettava LEIMAUSHETKELLA. Jos `_stamp_affiliate`
    unohtaa sen, koko erottelu on kosmeettinen."""
    seen = {}

    class _Sub:
        @staticmethod
        def modify(sub_id, metadata=None, **kw):
            seen.update(metadata or {})
            return {}

    monkeypatch.setattr(m.stripe, "Subscription", _Sub)
    assert m._stamp_affiliate("sub_1", "WOLFY", "ref") is True
    assert seen.get("affiliate") == "WOLFY"
    assert seen.get("affiliate_source") == "ref", (
        "leima ei kirjaa lahdetta; vahti ei voi erottaa ref-attribuutiota "
        "kuponkilunastuksesta eika sita voi paatella jalkikateen")


def test_watchdog_compares_only_coupon_sourced_stamps():
    """🔴 Rakenteellinen portti vahtiin.

    Vahti ei ole ajettavissa taalla (vaatii Stripe-avaimen), joten
    tarkistetaan etta se lukee lahteen EIKA vertaa kokonaismaaraa.
    """
    src = WATCHDOG.read_text(encoding="utf-8")
    assert "affiliate_source" in src, (
        "vahti ei lue leiman lahdetta, joten ref-leimat lasketaan yha "
        "kuponkilunastuksia vasten ja ensimmainen ref-maksu tuottaa "
        "vaaran MAHDOTON-halytyksen")
    assert re.search(r"comparable\s*=\s*promo\s*\+\s*unknown", src), (
        "vahti ei rajaa vertailua kuponkilahteisiin leimoihin")
    assert re.search(r"if\s+comparable\s*==\s*redeemed", src), (
        "vahti vertaa yha kokonaismaaraa lunastuksiin")


def test_watchdog_counts_pre_split_stamps_as_coupon():
    """Ennen 16.8 kirjoitetuissa leimoissa ei ole lahdetta. Ne EIVAT voi
    olla ref-perasia, koska ref-polkua ei ollut olemassa - joten ne
    kuuluvat promo-puolelle. Vaara suunta tuottaisi valheellisen VUOTOn."""
    src = WATCHDOG.read_text(encoding="utf-8")
    assert "unknown" in src and "promo + unknown" in src, (
        "vanhat lahteettomat leimat pitaa laskea kuponkipuolelle; muuten "
        "vahti raportoi vuotoa jota ei ole")
