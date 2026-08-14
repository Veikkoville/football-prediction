"""WHY-THIS-PICK -portit.

Painopiste on yhdessa asiassa: **lukuprovenienssiportissa**. Kehotus joka
kieltaa keksimisen on toive; portti on mittaus. Jokaiselle saannolle on
negatiivinen kontrolli — testi joka osoittaa etta portti kaataa kun sen
kuuluu (muisti: substring-osuma on sokea).
"""
from __future__ import annotations

import pytest

from scripts import build_fpl_why as why


PLAYER = {
    "id": 426,
    "web_name": "B.Fernandes",
    "team": "Manchester United",
    "pos": "MID",
    "price": 12.0,
    "owned_pct": 48.1,
    "xmins": 83.6,
    "p_start": 0.8569,
    "minutes_confidence": "high",
    "e_bonus": 0.98,
    "xp_horizon_total": 34.05,
    "set_pieces": {"pens": 1, "corners": 1, "fk": 1},
    "last_season": {
        "minutes": 3065, "starts": 35, "goals": 9, "assists": 24,
        "per90": {"goals": 0.26, "assists": 0.7, "xgi": 0.68},
    },
    "gameweeks": [
        {"gw": 1, "xp": 5.8, "opponents": [{"opp": "HUL", "venue": "A"}]},
        {"gw": 2, "xp": 7.21, "opponents": [{"opp": "IPS", "venue": "H"}]},
    ],
}


@pytest.fixture
def facts():
    return why.player_facts(PLAYER, gw=1, horizon=2)


# --------------------------------------------------------------------------
# Faktalohko
# --------------------------------------------------------------------------

def test_facts_carry_the_model_components(facts):
    assert facts["name"] == "B.Fernandes"
    assert facts["xp_this_gw"] == 5.8
    assert facts["expected_minutes"] == 84          # pyoristetty
    assert facts["start_probability_pct"] == 86
    assert facts["next_opponents"] == ["HUL (A)", "IPS (H)"]
    assert facts["set_piece_duties"] == ["pens", "corners", "fk"]
    assert facts["last_season"]["xgi_per90"] == 0.68


def test_facts_drop_empty_fields():
    thin = {"id": 1, "web_name": "X", "gameweeks": []}
    got = why.player_facts(thin, gw=1, horizon=2)
    assert "set_piece_duties" not in got
    assert "next_opponents" not in got
    assert "availability_note" not in got


# --------------------------------------------------------------------------
# Lukuprovenienssiportti — TAMA on se joka estaa keksimisen
# --------------------------------------------------------------------------

def test_grounded_sentence_passes(facts):
    s = ("He is on all three set pieces and projected for 84 minutes a game, "
         "so the floor is unusually safe for a midfielder.")
    assert why.sentence_problems(s, facts) == []


def test_invented_number_is_rejected(facts):
    """NEGATIIVINEN KONTROLLI: uskottava mutta pohjaton luku."""
    s = "He has scored in 7 of his last 9 games, which lifts the projection."
    problems = why.sentence_problems(s, facts)
    assert any("pohjaton luku" in p for p in problems), problems


def test_recomputed_number_is_rejected(facts):
    """Malli EI saa laskea uusia lukuja faktoista — 5.8 + 7.21 = 13.01
    on totta mutta ei ole faktalohkossa, eika lukija voi tarkistaa sita."""
    s = "That is 13.01 points across the next two gameweeks."
    assert any("pohjaton luku" in p for p in why.sentence_problems(s, facts))


def test_number_from_facts_in_any_reasonable_format_passes(facts):
    # 12.0 -> "12", 0.68 -> "0.68", 48.1 -> "48.1"
    for s in ("At 12 million he is the priced-in captain option.",
              "0.68 expected goal involvements per 90 last season.",
              "Owned by 48.1 percent, so he is no differential."):
        assert why.sentence_problems(s, facts) == [], s


def test_em_dash_and_odds_are_rejected(facts):
    """Copy-portti koskee myos tata pintaa (em dash kielletty, brandilinja
    on tuloksiin eika kertoimiin)."""
    assert any("kielletty" in p for p in why.sentence_problems(
        "Safe minutes — and set pieces.", facts))
    assert any("kielletty" in p for p in why.sentence_problems(
        "The odds favour him.", facts))


def test_multi_sentence_and_overlong_are_rejected(facts):
    assert any("useampi" in p for p in why.sentence_problems(
        "He starts. He takes pens. He is good.", facts))
    long_s = "He is projected for 84 minutes a game. " + "very " * 60 + "good"
    assert why.sentence_problems(long_s, facts)


def test_empty_sentence_is_rejected(facts):
    assert why.sentence_problems("", facts) == ["tyhja virke"]


# --------------------------------------------------------------------------
# Varalause + cache
# --------------------------------------------------------------------------

def test_template_is_itself_grounded(facts):
    """Varalause on generoitu faktoista, joten sen TAYTYY lapaista sama
    portti — muuten fallback vuotaisi juuri sen mita portti estaa."""
    s = why.template_sentence(facts)
    assert why.sentence_problems(s, facts) == [], s
    assert "84" in s and "0.68" in s


def test_template_survives_a_thin_player():
    thin = why.player_facts({"id": 9, "web_name": "Y"}, gw=1, horizon=2)
    s = why.template_sentence(thin)
    assert s and why.sentence_problems(s, thin) == []


def test_hash_changes_only_when_components_change(facts):
    same = why.player_facts(dict(PLAYER), gw=1, horizon=2)
    assert why.component_hash(facts) == why.component_hash(same)

    moved = dict(PLAYER)
    moved["xmins"] = 70.0
    assert why.component_hash(why.player_facts(moved, gw=1, horizon=2)) \
        != why.component_hash(facts)

    # Negatiivinen kontrolli: kentta jota faktalohko ei kanna EI saa
    # invalidoida cachea (muuten jokainen refresh maksaisi taydet kutsut).
    noise = dict(PLAYER)
    noise["xp_per_90"] = 6.19
    assert why.component_hash(why.player_facts(noise, gw=1, horizon=2)) \
        == why.component_hash(facts)


def test_selection_matches_visible_order():
    """Valinnan on vastattava SITA jarjestysta jonka ostaja nakee ruudulla.

    MIKSI TAMA MUUTTUI (14.8): valinta oli taman kierroksen xP:lla, mutta
    molemmat pinnat lajittelevat ja nayttavat `xp_horizon_total`-luvun
    (`XpTable.svelte` SORTS.total + sarake "Total xP"; `FantasyScreen.tsx`
    oletuslajittelu 'total'). Ero ei ollut teoreettinen: nakyvan top 150:n
    joukossa oli nelja rivia ILMAN selitysta (Van de Ven 132, Porro 134,
    Maatsen 138, McGinn 143) ja nelja selitysta sen ULKOPUOLELLA. Maksumuuri
    lupaa "top 150 by Total xP" ja ostaja tarkistaa sen avaamalla rivin.

    Tama testi korvaa `test_select_players_orders_by_this_gw_xp`:n, joka
    koodasi vanhan kaytoksen.
    """
    payload = {"players": [
        # Jarjestys KAANTYY jos katsotaan GW1:ta horisontin sijaan -> tama
        # on negatiivinen kontrolli vanhaa toteutusta vastaan.
        {"id": 1, "xp_horizon_total": 30.0, "gameweeks": [{"gw": 1, "xp": 2.0}]},
        {"id": 2, "xp_horizon_total": 10.0, "gameweeks": [{"gw": 1, "xp": 9.0}]},
        {"id": 3, "xp_horizon_total": 0.0, "gameweeks": [{"gw": 2, "xp": 9.9}]},
    ]}
    got = why.select_players(payload, gw=1, top_n=5)
    assert [p["id"] for p in got] == [1, 2], (
        "valinta ei seuraa xp_horizon_totalia -> maksumuurin lupaus on vaarin")


def test_template_drops_meaningless_xgi():
    """`leans on 0.03 expected goal involvements` vaittaa projektion nojaavan
    lukuun joka ei kanna mitaan. Mitattu 14.8: 43/150 lausetta teki niin."""
    facts = {"id": 0, "expected_minutes": 62,
             "last_season": {"xgi_per90": 0.03}, "next_opponents": ["IPS (A)"]}
    assert "expected goal involvements" not in why.template_sentence(facts)
    facts["last_season"]["xgi_per90"] = 0.42
    assert "0.42 expected goal involvements" in why.template_sentence(facts)


def test_template_frames_vary_by_player():
    """Yksi runko 150 rivilla luetaan botiksi, ja rivien avaaminen perakkain
    on tuotteen normaali kaytto. Valinnan on silti oltava deterministinen,
    jotta refresh ei vaihda tekstia turhaan."""
    base = {"expected_minutes": 80, "last_season": {}, "next_opponents": ["A (H)"]}
    seen = {why.template_sentence({**base, "id": i}).split(" ")[0] for i in range(9)}
    assert len(seen) > 1, "kaikki lauseet alkavat samalla sanalla"
    a = why.template_sentence({**base, "id": 7})
    assert a == why.template_sentence({**base, "id": 7}), "ei deterministinen"


def test_drivers_enum_is_closed():
    """Suljettu lista on koko pointti: ilman sita 'why' ajautuisi eri
    sanastoon kausien mittaan eika sita voisi suodattaa tai kaantaa."""
    assert why.SCHEMA["properties"]["drivers"]["items"]["enum"] == why.DRIVERS
    assert why.SCHEMA["additionalProperties"] is False


def test_prompt_contains_only_facts(facts):
    prompt = why.build_prompt(facts)
    assert "FACTS" in prompt
    # Pelaajan nimi on faktoissa; mitaan muuta ulkoista ei syoteta.
    assert "B.Fernandes" in prompt
    assert "Premier League" not in prompt


# --------------------------------------------------------------------------
# Portin omat sokeat pisteet (loytyivat kuivaharjoituksesta, ei testista)
# --------------------------------------------------------------------------

def test_trailing_zero_stripping_does_not_leak_whole_numbers(facts):
    """LOYTYNYT BUGI: token '90' -> rstrip('0') -> '9', ja 9 oli faktoissa
    (viime kauden maalit) -> pohjaton luku lapaisi portin. Nollien karsinta
    kuuluu VAIN desimaaliosaan."""
    # 9 maalia on faktoissa; 90-luvun EI pida periytya siita.
    assert facts["last_season"]["goals"] == 9
    assert "90" not in why.allowed_numbers(facts)
    # 900 on samalla tavalla pohjaton eika saa lapaista.
    assert why.ungrounded_numbers("He made 900 passes.", facts) == ["900"]
    # Desimaalimuoto lapaisee yha: 0.7 == 0.70.
    assert why.ungrounded_numbers("0.70 assists per 90.", facts) == []


def test_per_90_is_the_only_unit_exemption(facts):
    assert why.UNIT_NUMBERS == {"90"}
    assert why.ungrounded_numbers("0.68 per 90.", facts) == []
    # Negatiivinen kontrolli: mikaan muu "yksikkoluku" ei ole vapautettu.
    assert why.ungrounded_numbers("Over 45 minutes.", facts) == ["45"]


def test_rounding_to_a_whole_number_is_not_grounded(facts):
    """5.8 EI oikeuta sanomaan 6: lukija tarkistaa luvun sivulta jossa
    lukee 5.8, ja nakee eri luvun kuin selitys vaittaa."""
    assert facts["xp_this_gw"] == 5.8
    assert why.ungrounded_numbers("Worth 6 points this week.", facts) == ["6"]


def test_template_reads_as_a_sentence(facts):
    s = why.template_sentence(facts)
    assert s.startswith("The projection leans on ")
    assert " and " in s and s.endswith(".")
    assert "leans on projected" not in s
    assert why.sentence_problems(s, facts) == []


# --------------------------------------------------------------------------
# Serve-time-liitos (/api/fantasy/xp) — premium-portti + ETag
# --------------------------------------------------------------------------

def test_attach_why_adds_only_known_players():
    from src.models.fpl_xp import attach_why
    payload = {"meta": {}, "players": [{"id": 1}, {"id": 2}]}
    entries = {"1": {"sentence": "Because minutes.", "drivers": ["minutes"],
                     "source": "model"}}
    got = attach_why(payload, entries)
    assert got["players"][0]["why"]["sentence"] == "Because minutes."
    assert got["players"][0]["why"]["source"] == "model"
    assert "why" not in got["players"][1]
    assert got["meta"]["n_explained"] == 1


def test_attach_why_is_a_noop_without_entries():
    from src.models.fpl_xp import attach_why
    payload = {"meta": {}, "players": [{"id": 1}]}
    got = attach_why(dict(payload), {})
    assert "why" not in got["players"][0]
    assert "n_explained" not in got["meta"]


def test_xp_endpoint_etag_carries_the_why_stamp(client, monkeypatch, tmp_path):
    """Serve-time-kentta ei liikuta generated_at:ia, joten ilman why-leimaa
    ehdollinen pyynto validoisi vanhan vastauksen 304:lla ja uusi selitys
    jaisi nakymatta (muisti: serve-time-kentta ei invalidoi ETagia)."""
    import src.models.fpl_xp as fx

    p = tmp_path / "fpl_why.json"
    p.write_text('{"entries": {}}', encoding="utf-8")
    first = fx.why_stamp(p)
    p.write_text('{"entries": {"1": {"sentence": "x"}}}', encoding="utf-8")
    assert fx.why_stamp(p) != first
    # Negatiivinen kontrolli: puuttuva tiedosto ei kaada eika arvo ole tyhja.
    assert fx.why_stamp(tmp_path / "ei-ole.json") == "0"


def test_free_teaser_does_not_carry_explanations(client, monkeypatch):
    """WHY on premium: maskattu teaser nayttaa 10 taytta rivia, ja selitys
    niissa myisi featuren ilmaiseksi juuri silla pinnalla jolla se myydaan."""
    import api.main as m
    monkeypatch.setattr(m, "is_premium_request", lambda request: False)
    monkeypatch.setattr(m, "premium_enforce_on", lambda: True)
    r = client.get("/api/fantasy/xp")
    assert r.status_code == 200
    body = r.json()
    for row in body.get("players") or []:
        assert "why" not in row, "selitys vuoti free-teaseriin"


def test_premium_request_does_carry_explanations(client, monkeypatch):
    """POSITIIVINEN KONTROLLI free-testille: ilman tata 'ei why:ta' voisi
    tarkoittaa 'liitos ei aja lainkaan' eika 'portti pitaa'."""
    import api.main as m
    import src.models.fpl_xp as fx

    monkeypatch.setattr(m, "is_premium_request", lambda request: True)
    monkeypatch.setattr(fx, "load_why", lambda path=None: {
        "1": {"sentence": "Because minutes.", "drivers": ["minutes"],
              "source": "model"},
    })
    r = client.get("/api/fantasy/xp")
    assert r.status_code == 200
    body = r.json()
    ids = {str(p.get("id")) for p in body.get("players") or []}
    assert "1" in ids, "testidata ei sisalla pelaajaa 1 — testi olisi tyhja"
    row = next(p for p in body["players"] if str(p.get("id")) == "1")
    assert row["why"]["sentence"] == "Because minutes."
    assert body["meta"]["n_explained"] == 1


# --------------------------------------------------------------------------
# Lokalisointi (WHY-I18N, 14.8)
#
# Maksumuuri lupaa `paywall.bullet_why`-rivilla es/pt-lokaaleilla selityksen
# ostajan OMALLA KIELELLA. Ennen tata kaikki 150 lausetta olivat englanniksi,
# eli espanjankielinen ostaja maksoi lupauksesta jota tuote ei pitanyt.
# --------------------------------------------------------------------------

def test_template_sentence_is_localised(facts):
    en = why.template_sentence(facts, "en")
    es = why.template_sentence(facts, "es")
    pt = why.template_sentence(facts, "pt")
    assert len({en, es, pt}) == 3, "kaksi kielta antoi saman lauseen"
    assert "minutes a game" in en
    assert "minutos por partido" in es
    assert "minutos por jogo" in pt


def test_localised_templates_keep_their_accents():
    """NEGATIIVINEN KONTROLLI OMALLE VIRHEELLE: taman kaannoksen ensimmainen
    versio riisui aksentit ("proyeccion", "projecao", "participacoes") repon
    ASCII-kommenttikonvention mukana. Kommentit saavat olla ASCIIta;
    kayttajalle NAKYVA espanja ja portugali eivat."""
    for lang in ("es", "pt"):
        blob = "".join(why.FRAMES[lang]) + "".join(
            str(v) for v in why.PHRASES[lang].values())
        assert any(ord(ch) > 127 for ch in blob), (
            f"{lang}: ei yhtaan aksenttia — teksti on riisuttu ASCIIksi")


def test_numbers_are_not_localised(facts):
    """Desimaalipiste sailyy kaikilla kielilla. Lukija tarkistaa luvun samalta
    riviltä jonka taulukko renderoi, ja taulukko renderoi pisteen kaikilla
    lokaaleilla — pilkku lauseessa ja piste taulukossa lukisi kahtena eri
    lukuna samasta asiasta."""
    es = why.template_sentence(facts, "es")
    assert "0.68" in es
    assert "0,68" not in es


def test_unknown_lang_falls_back_to_english(facts):
    assert why.template_sentence(facts, "fi") == why.template_sentence(facts, "en")


def test_attach_why_serves_the_requested_language():
    import src.models.fpl_xp as fx
    entries = {"1": {
        "sentence": "English one.",
        "sentences": {"en": "English one.", "es": "Frase en espanol.",
                      "pt": "Frase em portugues."},
        "sources": {"en": "model", "es": "template", "pt": "template"},
        "drivers": ["minutes"], "source": "model",
    }}
    got = fx.attach_why({"players": [{"id": 1}], "meta": {}},
                        entries=entries, lang="es")
    w = got["players"][0]["why"]
    assert w["sentence"] == "Frase en espanol."
    assert w["lang"] == "es"
    assert w["source"] == "template", "lahde on kielikohtainen, ei en:n lahde"


def test_attach_why_does_not_claim_a_localisation_it_did_not_do():
    """REHELLISYYSPORTTI. Vanha merkinta ilman `sentences`-lohkoa palauttaa
    englannin — tietoinen varapolku, koska tyhja kentta olisi huonompi. Mutta
    `lang` EI SAA sanoa "es": muuten pinta voi vaittaa lokalisointia jota ei
    tapahtunut, ja se on sama vikaluokka kuin honest-data-labels."""
    import src.models.fpl_xp as fx
    entries = {"1": {"sentence": "English only.", "drivers": [],
                     "source": "template"}}
    got = fx.attach_why({"players": [{"id": 1}], "meta": {}},
                        entries=entries, lang="es")
    w = got["players"][0]["why"]
    assert w["sentence"] == "English only."
    assert w["lang"] == "en"


def test_etag_separates_languages(client, monkeypatch):
    """ILMAN KIELTA ETagissa es-kayttajan ehdollinen pyynto validoituisi
    englanninkielisesta valimuistista ja han saisi englantia — eli tasan se
    vika jonka tama korjaa, mutta hiljaa ja vain niilla klienteilla joilla
    vastaus on jo valimuistissa (muisti: serve-time-kentta ei invalidoi
    ETagia)."""
    import api.main as m
    import src.models.fpl_xp as fx
    monkeypatch.setattr(m, "is_premium_request", lambda request: True)
    monkeypatch.setattr(fx, "load_why", lambda path=None: {
        "1": {"sentence": "EN.",
              "sentences": {"en": "EN.", "es": "ES.", "pt": "PT."},
              "sources": {"en": "template", "es": "template",
                          "pt": "template"},
              "drivers": [], "source": "template"},
    })
    en = client.get("/api/fantasy/xp?lang=en")
    es = client.get("/api/fantasy/xp?lang=es")
    assert en.status_code == 200 and es.status_code == 200
    assert en.headers["ETag"] != es.headers["ETag"], "kieli puuttuu ETagista"

    # Ristiinvalidointi: en-ETag EI saa validoida es-vastausta 304:lla.
    cross = client.get("/api/fantasy/xp?lang=es",
                       headers={"If-None-Match": en.headers["ETag"]})
    assert cross.status_code == 200, "en-ETag validoi es-vastauksen 304:lla"
    row = next(p for p in cross.json()["players"] if str(p.get("id")) == "1")
    assert row["why"]["sentence"] == "ES."

    # POSITIIVINEN KONTROLLI: sama kieli SAA validoitua 304:lla, muuten
    # testi olisi vihrea myos silla etta ETag on rikki joka pyynnolla.
    same = client.get("/api/fantasy/xp?lang=es",
                      headers={"If-None-Match": es.headers["ETag"]})
    assert same.status_code == 304


def test_endpoint_unknown_lang_falls_back_instead_of_404(client):
    """`league` on RESURSSI (tuntematon = 404), kieli on ESITYSMUOTO."""
    r = client.get("/api/fantasy/xp?lang=zz")
    assert r.status_code == 200


def test_paid_path_needs_two_locks_not_one(monkeypatch):
    """KULULUKKO (Villen linjaus 14.8). Pelkka API-avaimen olemassaolo EI saa
    kaynnistaa maksullista polkua: jos avain lisataan repoon jotain MUUTA
    tarkoitusta varten, vuorokausittainen why-cron alkaisi muuten kuluttaa
    rahaa hiljaa eika kukaan paattaisi sita. `WHY_USE_MODEL=1` on se paatos.

    Tama testi lukee vahdin ehdon suoraan lahteesta: se on tarkoituksella
    hauras kirjoitusasulle, koska ehdon lieventaminen on tasan se muutos
    joka pitaa huomata review'ssa.
    """
    import inspect
    src = inspect.getsource(why.main)
    assert 'WHY_USE_MODEL") == "1"' in src, (
        "maksullisen polun toinen lukko on poistettu tai nimetty uudelleen")
    assert "use_model" in src and "if args.dry_run or not use_model:" in src, (
        "mallipolun vahti ei enaa portita batch-lahetysta")
