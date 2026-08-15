"""Portti: luvattu hinta on se joka nakyy Checkoutissa.

MITATTU VIKA 15.8. Landing myy "€17.50 first year, enter EARLY30 at checkout",
mutta Stripe Checkout avautui 25,00 euroon ja alennus vaati etta kayttaja
klikkaa "Anna tarjouskoodi" ja kirjoittaa koodin itse.

Se osuu tasan siihen kohtaan jossa pudotus on MITATTU: 8 web-checkoutia,
0 kauppaa, ja 5/6 poistui ENNEN sahkopostikentan tayttamista. Hinta on
ensimmainen asia jonka he nakivat, ja se oli 43 % korkeampi kuin luvattu.

TURVALLISUUS: arvo tulee ymparistosta. Asettamaton -> entinen kaytos, joten
muutos ei voi rikkoa maksupolkua ennen kuin joku kytkee sen tietoisesti.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.main import _auto_promo_discount  # noqa: E402


def test_asettamaton_ymparisto_ei_esitayta(monkeypatch):
    """Oletus on entinen kaytos. Tama on se testi joka takaa ettei muutos voi
    rikkoa maksupolkua vahingossa."""
    monkeypatch.delenv("STRIPE_AUTO_PROMO_CODE", raising=False)
    assert _auto_promo_discount() is None


def test_tyhja_arvo_ei_esitayta(monkeypatch):
    monkeypatch.setenv("STRIPE_AUTO_PROMO_CODE", "   ")
    assert _auto_promo_discount() is None


def test_vaaran_muotoinen_arvo_hylataan(monkeypatch):
    """Kuponki-ID (`coupon_`) ja pelkka koodi (`EARLY30`) EIVAT ole
    promotion_code-ID:ta. Vaara tyyppi kaataisi Stripe-kutsun maksuhetkella,
    eli pahimmassa mahdollisessa paikassa."""
    for vaara in ("EARLY30", "coupon_abc", "promo", "prom_o123"):
        monkeypatch.setenv("STRIPE_AUTO_PROMO_CODE", vaara)
        assert _auto_promo_discount() is None, f"{vaara} hyvaksyttiin"


def test_oikea_id_esitaytetaan(monkeypatch):
    monkeypatch.setenv("STRIPE_AUTO_PROMO_CODE", "promo_1AbCdEf")
    assert _auto_promo_discount() == [{"promotion_code": "promo_1AbCdEf"}]


def test_valilyonnit_siistitaan(monkeypatch):
    monkeypatch.setenv("STRIPE_AUTO_PROMO_CODE", "  promo_1AbCdEf  ")
    assert _auto_promo_discount() == [{"promotion_code": "promo_1AbCdEf"}]


def test_checkout_kayttaa_toisensa_poissulkevia_parametreja():
    """`discounts` ja `allow_promotion_codes` eivat voi olla molemmat: Stripe
    hylkaa kutsun. Testi lukee lahteen, koska virhe nakyisi vasta
    maksuhetkella oikealla asiakkaalla."""
    src = (ROOT / "api" / "main.py").read_text(encoding="utf-8")
    i = src.index('mode="subscription"', src.index("def create_web_checkout")
                  if "def create_web_checkout" in src else 0)
    lohko = src[i:i + 1400]
    assert '"discounts": promo' in lohko
    assert '"allow_promotion_codes": True' in lohko
    assert "else" in lohko, "parametrit eivat ole toisensa poissulkevia"


# ---------------------------------------------------------------------------
# EARLY30 poistettu julkisilta pinnoilta
# ---------------------------------------------------------------------------

def test_early30_ei_esiinny_yhdellakaan_julkisella_pinnalla():
    """Villen paatos 15.8: koodi poistettiin kaikkialta, koska se lupasi
    17,50 euroa ja Checkout avasi 25,00. Koodi on yha Stripessa (luojakoodien
    kanssa samassa listassa), mutta sita EI mainita missaan.

    Testi kattaa generoidut sivut JA kasin yllapidetyt: 1954 tiedostoa mainitsi
    sen ennen poistoa, ja generoidut korjautuvat vain jos LAHDE korjataan."""
    import re
    osumat = []
    for pat in ("*.html", "fpl/*.html", "fpl/club/*.html",
                "predictions/**/*.html", "llms.txt"):
        for f in ROOT.glob(pat):
            if "node_modules" in str(f):
                continue
            if "EARLY30" in f.read_text(encoding="utf-8", errors="replace"):
                osumat.append(str(f.relative_to(ROOT)))
    assert not osumat, "EARLY30 mainitaan yha: " + ", ".join(osumat[:8])


def test_early30_ei_esiinny_sivugeneraattoreissa():
    """Generoidut sivut palaisivat seuraavassa buildissa jos lahde mainitsee
    koodin. Tama on se portti joka estaa paluun."""
    for nimi in ("build_fpl_page.py", "build_fpl_longtail.py",
                 "build_prediction_pages.py"):
        src = (ROOT / "scripts" / nimi).read_text(encoding="utf-8")
        assert "EARLY30" not in src, f"{nimi} mainitsee EARLY30:n"
    spa = (ROOT / "web" / "pro-spa" / "src" / "lib" / "billing.ts").read_text(
        encoding="utf-8")
    assert "EARLY30" not in spa, "billing.ts mainitsee EARLY30:n"
