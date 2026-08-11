"""P0 (11.8.2026): Premium-payload oli julkinen tuotannossa.

Loydos: `curl https://api.goaliq.app/api/fantasy/xp` palautti 502 pelaajaa
taysilla kentilla (xp_per_gw, xp_horizon_total, components, owned_pct) ILMAN
autentikointia. Syy ei ollut puuttuva gate vaan se etta `PREMIUM_ENFORCE` oli
Renderissa pois, jolloin `is_premium_request()` palauttaa aina True.

Nama testit lukitsevat kaksi asiaa joita mikaan olemassa oleva portti ei mitannut:

  1. **Maskaus toimii kun flagi on paalla.** Ilman tata "gate on paikallaan"
     -tarkistus on pelkka koodinluku: kutsupaikan olemassaolo ei todista etta
     payload oikeasti kutistuu (vrt. muisti `portti-voi-mitata-eri-koodipolkua`).
  2. **Gatettujen endpointtien JOUKKO on tasan odotettu.** Jos joku lisaa uuden
     premium-endpointin ilman gatea, tai poistaa gaten olemassa olevasta, testi
     kaatuu. Tama on se portti jota ei ollut: gatejen kattavuutta ei mitannut
     mikaan, joten aukon olisi voinut huomata vasta tuotannosta.

Negatiivinen kontrolli mukana molemmissa: flagi pois -> payload EI kutistu.
Ilman sita testi lapaisisi myos silloin kun maskaus kutistaisi kaiken aina.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

API_DIR = Path(__file__).resolve().parents[1] / "api"

# Endpointit jotka SAAVAT palauttaa premium-datan vain tunnistautuneelle.
# Lahde: klienttien gate-totuus (goaliq-app/components/FantasyTools.tsx
# TOOL_PREMIUM = chips/plans/edge true; web/pro-spa .../ToolsHome.svelte
# premium: true) + landingin Premium-paneeli (index.html).
GATED_EXPECTED = {
    "/api/fantasy/xp",
    "/api/fantasy/xp.csv",
    "/api/fantasy/plan",
    "/api/fantasy/chip-ev",
    "/api/fantasy/plan-chains",
    "/api/fantasy/edge",
}

# Nama ovat tarkoituksella ilmaisia (rate my team, kapteenipoiminta,
# price watch, leaderboardien karki, career, mini-liiga). Jos jokin naista
# muuttuu premiumiksi, se lisataan GATED_EXPECTEDiin ja gate koodiin.
FREE_EXPECTED = {
    "/api/fantasy/price-watch",
    "/api/fantasy/rate-team",
    "/api/fantasy/fit",
    "/api/fantasy/model-squad",
    "/api/fantasy/captain",
    "/api/fantasy/differentials",
    "/api/fantasy/value",
    "/api/fantasy/xg-leaders",
    "/api/fantasy/defcon-leaders",
    "/api/fantasy/defcon-gw",
    "/api/fantasy/defcon-live",
    "/api/fantasy/compare",
    "/api/fantasy/career",
    "/api/fantasy/league/{league_id}",
    "/api/fantasy/h2h",
    "/api/fantasy/defcon/{player_id}",
}


def _scan_gates() -> dict[str, bool]:
    """Lue @app/@router-dekoraattorit ja kerro kutsuuko runko gatea.

    Staattinen luku eika app.routes-introspektio, koska me haluamme tietaa
    kutsuuko juuri TAMAN endpointin runko is_premium_requestia — reitistosta
    sita ei nae.
    """
    gates: dict[str, bool] = {}
    pat = re.compile(r'@(?:app|router)\.(?:get|post)\("(/api/fantasy/[^"]+)"')
    for src in (API_DIR / "main.py", API_DIR / "fantasy_edge.py"):
        lines = src.read_text(encoding="utf-8").split("\n")
        hits = [(i, m.group(1)) for i, ln in enumerate(lines)
                if (m := pat.match(ln.strip()))]
        for k, (i, path) in enumerate(hits):
            end = hits[k + 1][0] if k + 1 < len(hits) else len(lines)
            body = "\n".join(lines[i:end])
            gates[path] = "is_premium_request" in body
    return gates


def test_premium_endpoints_are_gated():
    """Jokainen premium-endpoint kutsuu gatea."""
    gates = _scan_gates()
    missing = sorted(p for p in GATED_EXPECTED if not gates.get(p))
    unknown = sorted(p for p in GATED_EXPECTED if p not in gates)
    assert not unknown, f"Endpointtia ei loydy koodista enaa: {unknown}"
    assert not missing, (
        "Premium-endpoint ilman is_premium_request-gatea: "
        f"{missing}. Tama on P0 — payload vuotaa tunnistautumattomille."
    )


def test_no_new_ungated_endpoint_appeared():
    """Uusi fantasy-endpoint on luokiteltava eksplisiittisesti.

    Tama on se portti jota ei ollut: aiemmin uuden endpointin saattoi lisata
    ilman etta kukaan paatti onko se ilmainen vai maksullinen.
    """
    gates = _scan_gates()
    known = GATED_EXPECTED | FREE_EXPECTED
    surprises = sorted(set(gates) - known)
    assert not surprises, (
        f"Luokittelematon fantasy-endpoint: {surprises}. Lisaa se joko "
        "GATED_EXPECTEDiin (ja gate koodiin) tai FREE_EXPECTEDiin."
    )


def test_free_endpoints_stay_ungated():
    """Negatiivinen kontrolli luokittelulle: ilmaiset EIVAT ole gatettuja.

    Ilman tata GATED_EXPECTED lapaisisi myos silloin jos joku gateaisi kaiken,
    jolloin ilmaispinta ja sivugeneraattorit hajoaisivat hiljaa.
    """
    gates = _scan_gates()
    wrongly_gated = sorted(p for p in FREE_EXPECTED if gates.get(p))
    assert not wrongly_gated, (
        f"Ilmaiseksi luokiteltu endpoint on gatettu: {wrongly_gated}. "
        "Tama katkaisee ilmaispinnan ja mahdollisesti sivugeneraattorit."
    )


@pytest.fixture()
def client():
    import api.main as m
    return TestClient(m.app)


def test_xp_is_masked_when_enforcement_on(client, monkeypatch):
    """Flagi paalla + ei tokenia -> typistetty lista, ei koko payload."""
    monkeypatch.setenv("PREMIUM_ENFORCE", "on")
    from api.premium import FREE_XP_TEASER_N

    r = client.get("/api/fantasy/xp")
    assert r.status_code == 200
    d = r.json()
    assert d["meta"].get("masked") is True
    assert len(d["players"]) == FREE_XP_TEASER_N


def test_xp_is_masked_for_invalid_token(client, monkeypatch):
    """Kelvoton token ei ohita gatea (fail-closed tunnistautumisessa)."""
    monkeypatch.setenv("PREMIUM_ENFORCE", "on")
    from api.premium import FREE_XP_TEASER_N

    r = client.get("/api/fantasy/xp",
                   headers={"Authorization": "Bearer ei-kelpaa"})
    assert r.status_code == 200
    assert len(r.json()["players"]) == FREE_XP_TEASER_N


def test_xp_is_full_when_enforcement_off(client, monkeypatch):
    """NEGATIIVINEN KONTROLLI: flagi pois -> payload EI kutistu.

    Ilman tata kaksi edellista testia lapaisisivat myos silloin jos maskaus
    olisi paalla aina — eli emme mittaisi flagia vaan maskifunktiota.
    """
    monkeypatch.setenv("PREMIUM_ENFORCE", "off")
    from api.premium import FREE_XP_TEASER_N

    r = client.get("/api/fantasy/xp")
    assert r.status_code == 200
    d = r.json()
    assert d["meta"].get("masked") is not True
    assert len(d["players"]) > FREE_XP_TEASER_N, (
        "Flagi pois eika payload ole taysi — maskaus vuotaa flagin ohi."
    )


def test_masked_rows_stay_complete(client, monkeypatch):
    """Maski on TYPISTYS eika null-korvaus.

    Mobiili renderoi esim. player.xp_per_gw.toFixed(1); null kaataisi nakyman.
    Sama suunnitteluperiaate on kirjattu api/premium.py:n maskilohkoon.
    """
    monkeypatch.setenv("PREMIUM_ENFORCE", "on")
    r = client.get("/api/fantasy/xp")
    players = r.json()["players"]
    assert players, "Maskattu payload on tyhja — teaser ei saa olla nolla rivia."
    for p in players:
        for field in ("web_name", "team", "pos", "xp_per_gw", "xp_horizon_total"):
            assert p.get(field) is not None, f"Maskattu rivi menetti kentan {field}"
