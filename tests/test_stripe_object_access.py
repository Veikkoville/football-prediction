"""Stripe-objekti ei ole dict (16.8.2026, mitattu tuotannosta).

🔴 MITEN TAMA LOYTYI. Rakensin luojanakyman joka palauttaa `null`in kun
lukua ei saada luettua, ja ensimmainen tuotantoajo palautti
`stamped: null, sources_ok.stripe: false`. Ilman sita erottelua sivu olisi
nayttanyt luojalle "0 paid subscriptions" ja se olisi luettu mittauksena.

Juurisyy: `stripe`-kirjaston 15.x-sarjassa `Subscription`, `PromotionCode`
ja `metadata` EIVAT ole dict-alaluokkia eika niilla ole `.get`-metodia.
`sub.get("discount")` heittaa `AttributeError: get`. Webhookin oma payload
sen sijaan on `json.loads`-dict, jossa `.get` toimii - eli sama koodirivi
kasittelee kahta eri tyyppia sen mukaan tuliko arvo eventista vai
API-haulla.

🔴 MIKSI TESTIT EIVAT NAHNEET SITA. Jokainen testikaksoisolento oli dict.
Testit ajoivat koodipolun jota tuotannossa ei ole olemassa. Siksi tassa
tiedostossa on `StripeObj` joka nimenomaan EI tarjoa `.get`ia.

Toinen seuraus oli pahempi kuin puuttuva raporttiluku:
`_affiliate_code_from_session` heitti poikkeuksen KESKELLA web-checkoutin
fulfillmentia, kutsupaikassa jossa ei ole try-lohkoa. Jarjestys siina
haarassa on: `_upsert_web_subscription` -> affiliate-leima ->
`_update_profile(is_premium)` -> guestin magic link. Poikkeus keskimmaisessa
tarkoittaa maksanutta asiakasta jolla on tilausrivi mutta ei
`profiles.is_premium`ia (mobiili ei aukea) eika kirjautumislinkkia.
"""
from __future__ import annotations

import pytest

import api.main as m


class StripeObj:
    """Jaljittelee stripe 15.x StripeObjectia: `obj[key]` ja `obj.key`
    toimivat, `obj.get(key)` heittaa AttributeErrorin."""

    def __init__(self, data: dict):
        object.__setattr__(self, "_data", dict(data))

    def __getitem__(self, k):
        return object.__getattribute__(self, "_data")[k]

    def __getattr__(self, k):
        try:
            return object.__getattribute__(self, "_data")[k]
        except KeyError as e:
            raise AttributeError(k) from e


def test_the_double_really_has_no_get():
    """Portti itselleen: jos tama menee lapi `.get`illa, koko tiedosto
    mittaa vaaraa asiaa."""
    o = StripeObj({"status": "active"})
    assert o["status"] == "active"
    with pytest.raises(AttributeError):
        o.get("status")  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Fulfillment-polku
# ---------------------------------------------------------------------------

def test_session_read_survives_a_subscription_object(monkeypatch):
    """Tama on se rivi joka kaatoi fulfillmentin. Session on dict (webhookin
    payload), tilaus on StripeObject (API-haku)."""
    monkeypatch.setattr(m.stripe, "Subscription",
                        type("S", (), {"retrieve": staticmethod(
                            lambda sid: StripeObj({"id": sid, "discount": None}))}))
    monkeypatch.setattr(m, "_account_affiliate_ref", lambda uid: None)
    session = {"discounts": [], "subscription": "sub_1", "metadata": {},
               "client_reference_id": "u1"}
    assert m._affiliate_code_from_session(session) is None


def test_promo_is_found_through_a_subscription_object(monkeypatch):
    """Ja kun alennus ON tilauksella, koodi on luettava sielta. Pelkka
    "ei kaadu" olisi lapaissyt myos toteutuksella joka palauttaa aina None,
    eli provisio jaisi maksamatta hiljaa."""
    promo = StripeObj({"id": "promo_1", "code": "WOLFY"})
    sub = StripeObj({"id": "sub_1", "discount": StripeObj({"promotion_code": promo})})
    monkeypatch.setattr(m.stripe, "Subscription",
                        type("S", (), {"retrieve": staticmethod(lambda sid: sub)}))
    session = {"discounts": [], "subscription": "sub_1", "metadata": {}}
    assert m._affiliate_code_from_session(session) == ("WOLFY", "promo")


def test_promo_code_string_reads_a_retrieved_object(monkeypatch):
    monkeypatch.setattr(m.stripe, "PromotionCode",
                        type("P", (), {"retrieve": staticmethod(
                            lambda pid: StripeObj({"id": pid, "code": "DAZ"}))}))
    assert m._promo_code_string("promo_x") == "DAZ"


def test_dict_payloads_still_work():
    """Webhookin oma payload on ja pysyy dictina. Korjaus ei saa rikkoa sita."""
    assert m._promo_code_string({"code": "ROWAN"}) == "ROWAN"
    assert m._affiliate_code_from_session(
        {"discounts": [{"promotion_code": {"code": "ROWAN"}}]}) == ("ROWAN", "promo")


# ---------------------------------------------------------------------------
# Raporttilaskenta
# ---------------------------------------------------------------------------

def test_tally_counts_subscription_objects(monkeypatch):
    """Ennen korjausta tama nosti `sources_ok.stripe = false` ja jokaisen
    koodin `stamped`in nollaan - ilman yhtaan virhetta vastauksessa."""
    m._AFFILIATE_TALLY_CACHE.clear()
    monkeypatch.setattr(m, "SUPABASE_URL", "")
    monkeypatch.setattr(m, "SUPABASE_SERVICE_ROLE_KEY", "")
    rows = [
        StripeObj({"status": "active", "metadata": StripeObj({"affiliate": "WOLFY"})}),
        StripeObj({"status": "canceled", "metadata": StripeObj({"affiliate": "WOLFY"})}),
        StripeObj({"status": "active", "metadata": StripeObj({})}),
    ]
    monkeypatch.setattr(m.stripe, "Subscription",
                        type("S", (), {"list": staticmethod(
                            lambda **kw: type("L", (), {"auto_paging_iter": staticmethod(
                                lambda: iter(rows))})())}))
    t = m._affiliate_tally()
    assert t["sources_ok"]["stripe"] is True
    assert t["codes"]["WOLFY"]["stamped"] == 2
    assert t["codes"]["WOLFY"]["statuses"] == {"active": 1, "canceled": 1}
    m._AFFILIATE_TALLY_CACHE.clear()


# ---------------------------------------------------------------------------
# Apuri
# ---------------------------------------------------------------------------

def test_stripe_field_handles_both_shapes():
    assert m._stripe_field({"a": 1}, "a") == 1
    assert m._stripe_field(StripeObj({"a": 1}), "a") == 1
    assert m._stripe_field(StripeObj({}), "a", "fb") == "fb"
    assert m._stripe_field(None, "a", "fb") == "fb"
    assert m._stripe_field({"a": None}, "a", "fb") == "fb"
