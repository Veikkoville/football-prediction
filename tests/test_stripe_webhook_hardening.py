"""Portti: Stripe-webhook kuittaa ENNEN Supabase-kirjoitusta, ja ei estä silmukkaa.

MITATTU TILANNE (15.8.2026). Jonorivi 37 oli merkitty "EI SHIPATTU" ja se piti
paikkansa: haara `feat/stripe-webhook-hardening` oli 1009 committia jaljessa
eika mainissa ollut `BackgroundTasks`-kasittelya lainkaan. Webhook odotti
Supabase-kirjoitukset ennen kuin ack lahti Stripelle.

Juurisyy oli pahempi kuin hitaus: `_update_profile` kayttaa
`requests.patch`-kutsua, joka on ESTAVA, ja se ajettiin `async def`
-endpointin sisalla 10 sekunnin timeoutilla. Se ei hidastanut vain webhookia
vaan pysaytti koko tapahtumasilmukan KAIKILTA kayttajilta siksi ajaksi.

Kolme asiaa jotka tama portti pitaa paikallaan:

1. **Allekirjoitus tarkistetaan synkronisesti.** Se on turvaportti. Jos se
   siirtyisi taustalle, vaarin allekirjoitettu pyynto saisi 200:n.
2. **Kasittely EI ole vastauspolulla.** Ack lahtee heti.
3. **Kasittelija on tavallinen `def`, ei `async def`.** Tama on se yksi rivi
   joka pitaa eston pois silmukasta: Starlette ajaa synkronisen taustatehtavan
   saikeessa, mutta `async def` -tehtavan suoraan silmukassa. Muutos
   `async def`:ksi nayttaisi harmittomalta siistimiselta ja palauttaisi koko
   vian hiljaa, joten se on lukittu testilla.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time

import stripe  # noqa: F401  (varmistaa etta riippuvuus on asennettu)


SECRET = "whsec_test_hardening"


def _signed(event: dict) -> tuple[bytes, str]:
    body = json.dumps(event).encode()
    ts = int(time.time())
    sig = hmac.new(SECRET.encode(), f"{ts}.".encode() + body,
                   hashlib.sha256).hexdigest()
    return body, f"t={ts},v1={sig}"


def _event(user_id: str = "u-1") -> dict:
    return {
        "id": "evt_hardening",
        "object": "event",
        "api_version": "2024-06-20",
        "created": int(time.time()),
        "type": "checkout.session.completed",
        "data": {"object": {"object": "checkout.session",
                            "client_reference_id": user_id}},
    }


def test_kasittelija_ei_ole_koroutiini():
    """TARKEIN TESTI TASSA TIEDOSTOSSA.

    `async def` ajaisi estavan `requests.patch`-kutsun suoraan
    tapahtumasilmukassa ja palauttaisi tasan sen vian jota tama muutos korjaa.
    """
    import api.main as m

    assert not asyncio.iscoroutinefunction(m._kasittele_stripe_tapahtuma), (
        "_kasittele_stripe_tapahtuma on async: estava Supabase-kirjoitus "
        "palaisi tapahtumasilmukkaan ja pysayttaisi palvelimen kaikilta"
    )


def test_ack_lahtee_ennen_supabase_kirjoitusta(client, monkeypatch):
    """Vastaus tulee, vaikka Supabase-kirjoitus kestaisi kauan."""
    import api.main as m

    monkeypatch.setattr(m, "STRIPE_WEBHOOK_SECRET", SECRET)
    kirjoitukset: list[tuple[str, dict]] = []

    def hidas(user_id, fields):
        kirjoitukset.append((user_id, fields))
        return True

    monkeypatch.setattr(m, "_update_profile", hidas)

    body, sig = _signed(_event())
    r = client.post("/api/webhook/stripe", content=body,
                    headers={"stripe-signature": sig})
    assert r.status_code == 200
    assert r.json() == {"received": True}
    # TestClient ajaa taustatehtavat ennen kuin se palauttaa vastauksen, joten
    # tama todistaa etta tehtava AJETTIIN — ei sita missa jarjestyksessa.
    # Jarjestys on lukittu erikseen testissa test_kasittely_ei_ole_endpointissa.
    assert kirjoitukset and kirjoitukset[0][0] == "u-1"
    assert kirjoitukset[0][1]["is_premium"] is True


def test_kasittely_ei_ole_endpointissa():
    """Endpointin rungossa ei saa olla kirjoituskutsuja.

    Tama on se rakenteellinen ero jota `client.post` ei voi nayttaa: TestClient
    ajaa taustatehtavat synkronisesti, joten pelkka onnistunut kutsu nayttaisi
    identtiselta myos silloin jos muutos peruttaisiin.
    """
    import inspect

    import api.main as m

    src = inspect.getsource(m.stripe_webhook)
    assert "add_task" in src, "endpoint ei ajastaa taustatehtavaa"
    assert "_update_profile" not in src, (
        "endpoint kirjoittaa Supabaseen suoraan: kasittely on takaisin "
        "vastauspolulla"
    )
    # Allekirjoitus PITAA olla endpointissa, ei taustalla.
    assert "construct_event" in src, (
        "allekirjoituksen tarkistus on siirtynyt pois vastauspolulta: "
        "vaarin allekirjoitettu pyynto saisi 200:n"
    )


def test_vaara_allekirjoitus_400_eika_taustatehtavaa(client, monkeypatch):
    """NEGATIIVINEN KONTROLLI: turvaportti ei saa loystya kovennuksen mukana."""
    import api.main as m

    monkeypatch.setattr(m, "STRIPE_WEBHOOK_SECRET", SECRET)
    ajettu: list[dict] = []
    monkeypatch.setattr(m, "_kasittele_stripe_tapahtuma",
                        lambda e: ajettu.append(e))

    body = json.dumps(_event()).encode()
    r = client.post("/api/webhook/stripe", content=body,
                    headers={"stripe-signature": "t=1,v1=feikki"})
    assert r.status_code == 400
    assert not ajettu, "vaarin allekirjoitettu tapahtuma paatyi kasittelyyn"


def test_kasittelijan_virhe_ei_kaada_eika_katoa(capsys):
    """Kuittaus on jo lahtenyt, joten loki on ainoa jalki. Se ei saa puuttua,
    eika poikkeus saa nousta ulos taustatehtavasta."""
    import api.main as m

    def rikki(*_a, **_k):
        raise RuntimeError("supabase alhaalla")

    alkuperainen = m._update_profile
    m._update_profile = rikki
    try:
        m._kasittele_stripe_tapahtuma(_event())  # ei saa nostaa
    finally:
        m._update_profile = alkuperainen

    loki = capsys.readouterr().out
    assert "KASITTELY EPAONNISTUI" in loki, (
        "epaonnistunut tapahtuma katosi ilman jalkea"
    )


def test_tuntematon_tapahtuma_ei_kirjoita(monkeypatch):
    """NEGATIIVINEN KONTROLLI kasittelijalle: vain tunnetut tyypit kirjoittavat."""
    import api.main as m

    kirjoitukset: list = []
    monkeypatch.setattr(m, "_update_profile",
                        lambda u, f: kirjoitukset.append((u, f)))
    e = _event()
    e["type"] = "invoice.payment_failed"
    m._kasittele_stripe_tapahtuma(e)
    assert not kirjoitukset
