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

# KOLMAS LUOKKA (13.8): ilmainen ydin + premium-erittely samassa vastauksessa.
# Taksonomia oli binaarinen, ja `/api/fantasy/model-race` ei mahtunut
# kumpaankaan: Season race -tulos on ilmainen (silmukan palkinto), mutta
# "missa ero syntyi" -erittely on premiumia. Pakottaminen GATEDiin olisi
# vaittanyt etta koko endpoint on maksumuurin takana; FREEhen pakottaminen
# olisi kaatanut test_free_endpoints_stay_ungatedin ja poistanut gaten.
# Nailla on TIUKEMMAT saannot kuin kummallakaan: gate on pakollinen JA
# maskaus todennetaan ajamalla, ei merkkijonohaulla.
PARTIAL_EXPECTED = {
    "/api/fantasy/model-race",
    # 13.8: sama kuvio — sija ja piste-ero ovat FPL:n julkista dataa
    # (free), mallin kanta siihen mita erolle pitaisi tehda on premium.
    "/api/fantasy/rival",
    # 15.8: captain siirtyi FREEsta tanne. Se oli listattu ilmaiseksi ja
    # palautti autentikoimattomalle `top3` JA `differential` — eli tasan sen
    # mita premium-paneeli myy ("Captain ranker: top three, a differential
    # pick"). Portti oli VAIN selaimessa, joten suora API-kutsu sai koko
    # ominaisuuden.
    #
    # Se ei kuulu kumpaankaan binaariseen luokkaan: myyntisivu lupaa ILMAISEKSI
    # "Rate my team, with a captain pick" eli YHDEN valinnan. Vastaus on siis
    # ilmainen ydin + premium-erittely, mika on tasan tama kolmas luokka.
    # Koodi siirtyi vastaamaan copya, ei toisin pain.
    "/api/fantasy/captain",
}

# Erittelykentat jotka EIVAT saa nakya ilman premiumia.
PARTIAL_PREMIUM_KEYS = {
    "/api/fantasy/model-race": (
        "model_captain_id", "model_bench_points", "model_autosubs"),
    "/api/fantasy/rival": ("differentials",),
    # Differential-kapteeni on nimenomaan myyty premium-riville.
    "/api/fantasy/captain": ("differential",),
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
    known = GATED_EXPECTED | FREE_EXPECTED | PARTIAL_EXPECTED
    surprises = sorted(set(gates) - known)
    assert not surprises, (
        f"Luokittelematon fantasy-endpoint: {surprises}. Lisaa se joko "
        "GATED_EXPECTEDiin (ja gate koodiin) tai FREE_EXPECTEDiin."
    )


def test_gated_endpoints_actually_truncate():
    """Gate ei riita: jokaisen on myos TYPISTETTAVA payload.

    Todellinen vikatila jota tama vahtii: endpoint laskee
    `premium = is_premium_request(request)` ja **ei kayta muuttujaa mihinkaan**.
    Silloin `test_premium_endpoints_are_gated` on vihrea, koodinluku nayttaa
    oikealta, ja koko payload menee silti ulos. Sama luokka kuin muisti
    `portti-voi-mitata-eri-koodipolkua`.

    Hyvaksytaan joko FREE_*-vakio (inline-typistys, fantasy_edge.py) tai
    mask_*-funktio (main.py) — molemmat ovat aitoja typistyksia.
    """
    import re
    gates: dict[str, str] = {}
    pat = re.compile(r'@(?:app|router)\.(?:get|post)\("(/api/fantasy/[^"]+)"')
    for src in (API_DIR / "main.py", API_DIR / "fantasy_edge.py"):
        lines = src.read_text(encoding="utf-8").split("\n")
        hits = [(i, m.group(1)) for i, ln in enumerate(lines)
                if (m := pat.match(ln.strip()))]
        for k, (i, path) in enumerate(hits):
            end = hits[k + 1][0] if k + 1 < len(hits) else len(lines)
            gates[path] = "\n".join(lines[i:end])

    toothless = []
    for path in sorted(GATED_EXPECTED):
        body = gates.get(path, "")
        if not ("FREE_" in body or "mask_" in body):
            toothless.append(path)
    assert not toothless, (
        f"Gate ilman typistysta: {toothless}. Endpoint laskee premium-lipun "
        "mutta ei kutista payloadia — portti on vihrea ja data vuotaa silti."
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


def test_partial_endpoints_are_gated():
    """Osittain gatetun endpointin runko ON kutsuttava gatea.

    Ilman tata erittelykentat vuotaisivat kaikille, ja koska ydin on
    ilmainen, mikaan 403 tai tyhja vastaus ei paljastaisi vuotoa.
    """
    gates = _scan_gates()
    missing = sorted(p for p in PARTIAL_EXPECTED if not gates.get(p))
    assert not missing, (
        f"Osittain gatettu endpoint ilman is_premium_requestia: {missing}.")


@pytest.fixture()
def race_client(tmp_path, monkeypatch):
    """TestClient jolla on synteettinen gradausloki levylla.

    Esikaudella oikea loki on tyhja, jolloin maskaustesti mittaisi tyhjaa
    vastausta eika maskausta (vrt. muisti `gate-substring-osuma-on-sokea`).
    """
    import json as _json

    import api.main as m
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "model_squad_gw_scores.json").write_text(
        _json.dumps({"gameweeks": [{
            "gw": 1, "points": 61, "fpl_average": 57, "captain_id": 351,
            "captain_reason": "captain", "captain_points_added": 12,
            "bench_points": 5,
            "autosubs": [{"out": 7, "in": 13, "pos": 2}]}]}),
        encoding="utf-8")
    monkeypatch.setattr(m, "PROJECT_ROOT", tmp_path)
    return TestClient(m.app)


def test_model_race_hides_breakdown_when_enforcement_on(race_client, monkeypatch):
    """Flagi paalla + ei tokenia -> tulos nakyy, erittely ei."""
    monkeypatch.setenv("PREMIUM_ENFORCE", "on")
    d = race_client.get("/api/fantasy/model-race").json()
    assert d["meta"]["available"] is True
    assert d["meta"]["masked"] is True
    assert d["totals"]["model"] == 61          # ydin on ilmainen
    row = d["gameweeks"][0]
    assert row["model_points"] == 61
    leaked = [k for k in PARTIAL_PREMIUM_KEYS["/api/fantasy/model-race"]
              if k in row]
    assert not leaked, f"Premium-erittely vuoti ilmaiselle: {leaked}"


def test_model_race_full_when_enforcement_off(race_client, monkeypatch):
    """NEGATIIVINEN KONTROLLI: flagi pois -> erittely on mukana.

    Ilman tata edellinen testi lapaisisi myos silloin jos kentat puuttuisivat
    aina — eli mittaisimme kentan poissaoloa emmeka maskausta.
    """
    monkeypatch.setenv("PREMIUM_ENFORCE", "off")
    d = race_client.get("/api/fantasy/model-race").json()
    assert d["meta"]["masked"] is False
    row = d["gameweeks"][0]
    for k in PARTIAL_PREMIUM_KEYS["/api/fantasy/model-race"]:
        assert k in row, f"Erittelykentta {k} puuttuu premiumilta"
    assert row["model_captain_id"] == 351


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


# --- FREE-DRAFT-POOL (14.8) ------------------------------------------------
#
# Loydos 14.8: maskattu vastaus antoi free-kayttajalle 10 rivia 505:sta ja
# niissa oli MID 4 / DEF 4 / FWD 2 / **GKP 0**. Draft rater vaatii 2 GKP, joten
# lahetysnappi ei aktivoitunut koskaan — seka mobiilissa etta webissa, koska
# molemmat hakevat valitsinpoolinsa samasta kutsusta. Yksikaan portti ei
# nahnyt sita: backend vastasi 200, tsc oli vihrea, ja rikki oli tyhja lista.
# Nama testit lukitsevat KAYTETTAVYYDEN (voiko 15 slottia tayttaa) eivatka
# vain listan pituutta.

DRAFT_SLOTS = {"GKP": 2, "DEF": 5, "MID": 5, "FWD": 3}


def _pos_counts(rows: list[dict]) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in rows:
        out[r.get("pos")] = out.get(r.get("pos"), 0) + 1
    return out


def test_maskattu_vastaus_ei_riita_valitsimeksi(client, monkeypatch):
    """Kontrolli itse oireelle: teaser-rivit EIVAT tayta draftin slotteja.

    Jos tama joskus lakkaa patemasta, `pool` on tarpeeton — mutta silloin se
    on paatettava eksplisiittisesti eika vahingossa.
    """
    monkeypatch.setenv("PREMIUM_ENFORCE", "on")
    d = client.get("/api/fantasy/xp").json()
    counts = _pos_counts(d["players"])
    puuttuu = {p: n for p, n in DRAFT_SLOTS.items() if counts.get(p, 0) < n}
    assert puuttuu, ("teaser tayttaa jo draftin slotit — tama testi ei enaa "
                     "mittaa mitaan")


def test_anonyymi_saa_taydentavan_valitsinpoolin(client, monkeypatch):
    """POSITIIVINEN: anonyymi pystyy tayttamaan 15/15 slottia."""
    monkeypatch.setenv("PREMIUM_ENFORCE", "on")
    r = client.get("/api/fantasy/xp")
    assert r.status_code == 200
    pool = r.json().get("pool")
    assert pool, "kevyt valitsinpooli puuttuu maskatusta vastauksesta"
    counts = _pos_counts(pool)
    vajaat = {p: (counts.get(p, 0), n) for p, n in DRAFT_SLOTS.items()
              if counts.get(p, 0) < n}
    assert not vajaat, f"valitsimesta ei saa koottua 15:ta: {vajaat}"


def test_valitsinpooli_ei_sisalla_yhtaan_xp_arvoa(client, monkeypatch):
    """NEGATIIVINEN KONTROLLI: pooli ei saa vuotaa premium-ydinta.

    Testataan kentat NIMELTA eika vain otoksesta: uusi kentta joka livahtaa
    XP_POOL_FIELDSiin loytyisi vasta tuotannosta.
    """
    monkeypatch.setenv("PREMIUM_ENFORCE", "on")
    from api.premium import XP_POOL_FIELDS

    pool = client.get("/api/fantasy/xp").json()["pool"]
    assert pool
    kielletyt = {"xp_per_gw", "xp_horizon_total", "xp_per_90", "components",
                 "owned_pct", "why", "gameweeks", "xmins"}
    for row in pool:
        assert set(row) == set(XP_POOL_FIELDS), (
            f"valitsinpoolin kenttajoukko muuttui: {sorted(row)}")
        assert not (set(row) & kielletyt)
    # ...ja sama vaite kenttalistalle itselleen, jotta lisays huomataan
    # myos silloin kun rivi sattuisi olemaan tyhja.
    assert not (set(XP_POOL_FIELDS) & kielletyt)
    assert not [f for f in XP_POOL_FIELDS if "xp" in f.lower()]


def test_valitsinpooli_on_myos_premiumilla(client, monkeypatch):
    """Yksi koodipolku klientilla: pooli tulee myos maskaamattomana.

    Jos pooli olisi vain maskatussa vastauksessa, klientti tarvitsisi kaksi
    haaraa ja pinnat voisivat eriytya — sama vikaluokka josta tama korjaus
    lahti liikkeelle.
    """
    monkeypatch.setenv("PREMIUM_ENFORCE", "off")
    d = client.get("/api/fantasy/xp").json()
    assert d["meta"].get("masked") is not True
    assert _pos_counts(d.get("pool") or {}) and all(
        _pos_counts(d["pool"]).get(p, 0) >= n for p, n in DRAFT_SLOTS.items())


def test_pool_lisays_nosti_etag_skeemaversiota():
    """Serve-time-kentta ilman skeemanostoa jaisi 304:n taakse.

    Muisti `serve-time-kentta-ei-invalidoi-etagia`: `generated_at` ei liiku
    kun kentta lisataan servaushetkella, joten ehdollinen pyynto validoisi
    vanhan vastauksen ja valitsin olisi tyhja tasan niilla kayttajilla joilla
    vastaus on jo valimuistissa.
    """
    # nosta AINA kun pooliin/vastaukseen tulee serve-time-kentta.
    # s6 (14.8): `why.lang` = toteutunut kieli (WHY-I18N). Tama lukitustesti
    # puri kuten kuuluu — se on ainoa asia joka pakottaa nostamaan version
    # kasin, ja se loysi noston puuttumisen ennen kuin kayttajat loysivat
    # tyhjan kentan valimuistista.
    NYKYINEN = "s6"
    src = (API_DIR / "main.py").read_text(encoding="utf-8")
    assert f'schema = "{NYKYINEN}"' in src, (
        f"ETagin skeemaversio ei ole {NYKYINEN}. Jos lisasit pooliin kentan "
        "(XP_POOL_FIELDS) tai muun serve-time-kentan, nosta BOTH: "
        "api/main.py:n `schema` JA tama vakio. Jos et lisannyt, joku muu "
        "nosti version ja tama testi on jaljessa.")
    # Sidonta kenttajoukkoon: jos XP_POOL_FIELDS kasvaa mutta versio ei liiku,
    # yllaoleva assert kaatuu vasta jos joku muistaa paivittaa NYKYISEN.
    # Tama rivi tekee kytkennan nakyvaksi lukijalle: s4 = 5 kenttaa (draft),
    # s5 = 7 kenttaa (+ status/news ilmaista watchlistia varten).
    from api.premium import XP_POOL_FIELDS
    assert len(XP_POOL_FIELDS) == 7, (
        "XP_POOL_FIELDS muuttui — tarkista ETagin skeemaversio ja paivita "
        "tama luku samassa committissa")
