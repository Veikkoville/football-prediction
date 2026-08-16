"""Affiliate-attribuutio ilman promokoodia (16.8.2026).

MIKSI TAMA ON OLEMASSA.

Attribuutio luki aiemmin VAIN kaytetyn promokoodin, eli se toimi vain jos
asiakas maksoi alennuksella. GW1-GW3 ilmaisikkuna rikkoi sen:

    luojan katsoja tulee ikkunan aikana -> luo ilmaisen tilin -> kayttaa
    tuotetta nelja viikkoa -> maksaa 12.9. jalkeen TAYTTA HINTAA ilman
    koodia -> attribuutio palauttaa None -> luoja ei saa mitaan

Provisio on luvattu Dazille, Rowanille ja Wolfylle sanoilla "for as long as
they keep the subscription" (DM 12.8). Se lupaus ei saa katketa siihen etta
tarjosimme tuotetta ilmaiseksi juuri siina ikkunassa jossa he tuovat eniten
kayttajia.

Ref matkustaa checkout-session metadatassa, joten uutta kantasaraketta ei
tarvita eika tuotantoon tarvita migraatiota.
"""
from __future__ import annotations

import api.main as m


# --- normalisointi --------------------------------------------------------

def test_ref_is_normalised_to_upper():
    assert m._clean_affiliate_ref("daz") == "DAZ"
    assert m._clean_affiliate_ref("  Wolfy  ") == "WOLFY"


def test_junk_ref_is_rejected():
    """Arvo paatyy Stripe-metadataan ja payout-tasmaytykseen, joten siihen
    mita URLissa sattui olemaan ei luoteta."""
    for bad in [None, "", "a", "x" * 33, "DAZ; DROP", "<script>", "ro wan",
                123, {"code": "DAZ"}]:
        assert m._clean_affiliate_ref(bad) is None, bad


# --- attribuutio ----------------------------------------------------------

def test_promo_code_still_wins_over_ref(monkeypatch):
    """Kaytetty koodi on vahvempi todiste kuin selaimeen sailottu ref."""
    monkeypatch.setattr(m, "_promo_code_string", lambda p: "WOLFY")
    session = {
        "discounts": [{"promotion_code": "promo_x"}],
        "metadata": {"ref": "DAZ"},
    }
    assert m._affiliate_code_from_session(session) == "WOLFY"


def test_ref_attributes_when_no_code_was_used():
    """🔴 Tama on se tapaus jonka ilmaisikkuna loi. Ilman ref-fallbackia
    tama palauttaa None ja luoja jaa ilman provisiota."""
    session = {"discounts": [], "subscription": None,
               "metadata": {"ref": "daz", "plan": "season"}}
    assert m._affiliate_code_from_session(session) == "DAZ"


def test_no_code_and_no_ref_is_still_none():
    """Negatiivinen kontrolli: fallback ei saa keksia attribuutiota
    tyhjasta. Orpo provisio olisi pahempi kuin puuttuva."""
    session = {"discounts": [], "subscription": None,
               "metadata": {"plan": "season", "source": "pro-web"}}
    assert m._affiliate_code_from_session(session) is None


def test_junk_ref_in_metadata_does_not_attribute():
    session = {"discounts": [], "subscription": None,
               "metadata": {"ref": "not a code!!"}}
    assert m._affiliate_code_from_session(session) is None


def test_missing_metadata_does_not_crash():
    assert m._affiliate_code_from_session({"discounts": []}) is None
    assert m._affiliate_code_from_session({"metadata": None}) is None


# --- pyyntomalli ----------------------------------------------------------

def test_checkout_request_accepts_and_defaults_ref():
    r = m.WebCheckoutRequest(plan="season")
    assert r.ref == "", "ref on valinnainen; vanha klientti ei saa kaatua"
    assert m.WebCheckoutRequest(plan="season", ref="daz").ref == "daz"


# --- ref paatyy oikeasti checkout-sessioon --------------------------------
#
# Ilman tata testi todistaisi vain etta pyynto ei kaadu. Sen ero on iso:
# 16.8 tuotantoajo palautti Stripe-URLin ref-kentalla, mika ei kerro
# yhtaan mitaan siita paatyiko ref metadataan. Talla se on pinnattu.

def _capture_session(monkeypatch):
    seen = {}

    class _S:
        url = "https://checkout.stripe.com/test"

    def fake_create(**kw):
        seen.update(kw)
        return _S()

    monkeypatch.setattr(m.stripe.checkout.Session, "create", fake_create)
    monkeypatch.setattr(m, "STRIPE_PRICE_SEASON_ID", "price_test")
    monkeypatch.setattr(m.stripe, "api_key", "sk_test")
    return seen


def test_guest_checkout_puts_ref_in_metadata(client, monkeypatch):
    seen = _capture_session(monkeypatch)
    r = client.post("/api/web/checkout/guest",
                    json={"plan": "season", "origin": "https://pro.goaliq.app",
                          "ref": "daz"})
    assert r.status_code == 200, r.text
    assert seen["metadata"]["ref"] == "DAZ", seen.get("metadata")


def test_guest_checkout_without_ref_has_no_ref_key(client, monkeypatch):
    """Negatiivinen kontrolli: tyhja ref ei saa luoda avainta. Orpo
    'ref': '' metadatassa nayttaisi attribuutiolta jota ei ole."""
    seen = _capture_session(monkeypatch)
    r = client.post("/api/web/checkout/guest",
                    json={"plan": "season", "origin": "https://pro.goaliq.app"})
    assert r.status_code == 200, r.text
    assert "ref" not in seen["metadata"], seen.get("metadata")


def test_junk_ref_is_not_written_to_metadata(client, monkeypatch):
    seen = _capture_session(monkeypatch)
    r = client.post("/api/web/checkout/guest",
                    json={"plan": "season", "origin": "https://pro.goaliq.app",
                          "ref": "not a code!!"})
    assert r.status_code == 200, r.text
    assert "ref" not in seen["metadata"], seen.get("metadata")
