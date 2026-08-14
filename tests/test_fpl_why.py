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


def test_select_players_orders_by_this_gw_xp():
    payload = {"players": [
        {"id": 1, "gameweeks": [{"gw": 1, "xp": 2.0}]},
        {"id": 2, "gameweeks": [{"gw": 1, "xp": 9.0}]},
        {"id": 3, "gameweeks": [{"gw": 2, "xp": 9.9}]},   # ei GW1:ta
    ]}
    got = why.select_players(payload, gw=1, top_n=5)
    assert [p["id"] for p in got] == [2, 1]


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
