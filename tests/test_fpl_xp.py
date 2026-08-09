"""FPL Phase 1 xP -testit: loader-fallback, endpointin muoto, kaavan sanityt.

Ei verkkoa, ei mallifittiä — builderin/backtestin verkko- ja fit-polut
ajetaan vain oikeissa joboissa. Domestic-malliin ei kosketa.
"""
from __future__ import annotations

import json

import pytest

from src.models import fpl_xp as xp


# ---------------------------------------------------------------------------
# Loader (peili: test_fpl_phase0)
# ---------------------------------------------------------------------------
def test_load_xp_missing_file_returns_empty(tmp_path):
    data = xp.load_xp(tmp_path / "ei-ole.json")
    assert data["meta"]["available"] is False
    assert data["players"] == []


def test_load_xp_corrupt_file_returns_empty(tmp_path):
    p = tmp_path / "rikki.json"
    p.write_text("{ei json", encoding="utf-8")
    assert xp.load_xp(p)["meta"]["available"] is False


def test_load_xp_reads_valid_file(tmp_path):
    payload = {
        "meta": {"available": True, "next_gameweek": 1},
        "players": [{"id": 1, "web_name": "Testaaja", "gameweeks": []}],
    }
    p = tmp_path / "ok.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    out = xp.load_xp(p)
    assert out["meta"] == payload["meta"]
    # 5.8: load_xp rikastaa rivit vauhtikentalla. Rivilla ei ole xp_per_gw:ta
    # eika xmins:ia -> None, ei kaatumista ja EI arvausta.
    assert out["players"][0]["xp_per_90"] is None
    assert {k: v for k, v in out["players"][0].items() if k != "xp_per_90"} \
        == payload["players"][0]


def test_load_xp_does_not_derive_rate_from_minutes(tmp_path):
    """load_xp EI keksi vauhtia (xp_per_gw, xmins) -parista.

    Alkuperainen 5.8. toteutus laski `xp_per_gw * 90 / xmins` tassa. Se on
    vaara: xP ei ole lineaarinen minuuttien suhteen (ks. xp_full_90). Rivi
    ilman putken kenttaa saa None:n, ja rivin oma arvo menee lapi
    koskemattomana.
    """
    payload = {
        "meta": {"available": True, "next_gameweek": 1},
        "players": [
            {"id": 1, "web_name": "FromPipeline", "xp_per_gw": 2.0,
             "xmins": 45.0, "xp_per_90": 3.5},
            {"id": 2, "web_name": "NoField", "xp_per_gw": 2.0, "xmins": 45.0},
        ],
    }
    p = tmp_path / "rates.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    rows = {r["web_name"]: r for r in xp.load_xp(p)["players"]}
    assert rows["FromPipeline"]["xp_per_90"] == 3.5
    assert rows["NoField"]["xp_per_90"] is None
    assert rows["NoField"]["xp_per_90"] != 4.0, (
        "serve-time johtaa vauhdin uudestaan vanhalla kaavalla"
    )


def _rates(xg90=0.0, xa90=0.0, bonus90=0.0, yc90=0.0, saves90=0.0, dc_freq=0.0):
    return {"xg90": xg90, "xa90": xa90, "bonus90": bonus90, "yc90": yc90,
            "saves90": saves90, "dc_freq": dc_freq}


def _ctx90():
    return {"goal_mult": 1.0, "cs_prob": 0.3, "conceded_dist": [0.3, 0.4, 0.3],
            "opp_goal_mult": 1.0}


def test_xp_full_90_does_not_reward_short_minutes():
    """NEGATIIVINEN KONTROLLI: vanha kaava kaansi jarjestyksen, uusi ei.

    Terava hyokkaaja joka pelaa 77 min vs vaihtomies joka pelaa 16 min ja jonka
    oma vauhti on murto-osa. Vanhalla kaavalla (xp_per_gw * 90 / xmins)
    vaihtomies NOUSEE karkeen, koska kiinteat esiintymispisteet jaetaan
    pienella minuuttiluvulla. Tama testi vaatii etta (a) vanha kaava todella
    inversoi — muuten testi ei kontrolloi mitaan — ja (b) uusi ei.
    """
    pos = 4  # FWD
    elite = _rates(xg90=0.80, xa90=0.20, bonus90=0.9)
    # Vaihtomiehen vauhti on TARKOITUKSELLA uskottava eika olematon: juuri niin
    # tuotannon tapaus syntyi (317 minuutin otos, 0.57 maalia/90). Olemattomalla
    # vauhdilla vanha kaava ei edes inversoi, eli testi ei kontrolloisi mitaan.
    fringe = _rates(xg90=0.45, xa90=0.20, bonus90=0.3)
    ctx = _ctx90()

    # Tuotannon kaltaiset minuuttiprofiilit
    elite_xm, elite_p60, elite_p1 = 77.0, 0.83, 0.06
    frin_xm, frin_p60, frin_p1 = 16.0, 0.12, 0.63

    elite_gw = xp.xp_components(pos, elite, elite_xm, elite_p60, elite_p1,
                                ctx)["total"]
    frin_gw = xp.xp_components(pos, fringe, frin_xm, frin_p60, frin_p1,
                               ctx)["total"]

    old_elite = elite_gw * 90.0 / elite_xm
    old_fringe = frin_gw * 90.0 / frin_xm
    assert old_fringe > old_elite, (
        "testin premissi ei pade: vanha kaava ei inversoi nailla luvuilla, "
        "joten testi ei kontrolloi korjausta"
    )

    new_elite = xp.xp_full_90(pos, elite, ctx)
    new_fringe = xp.xp_full_90(pos, fringe, ctx)
    assert new_elite > new_fringe, (
        f"korjattu vauhti asettaa vaihtomiehen ({new_fringe:.2f}) yha "
        f"karkipelaajan ({new_elite:.2f}) edelle"
    )


def test_xp_full_90_is_independent_of_minute_expectation():
    """Maaritelman ydin: per-90 ei saa riippua siita kuinka paljon pelaajan
    ODOTETAAN pelaavan — se on nimenomaan se sekaannus joka korjattiin. Sama
    rates + sama ctx = sama luku riippumatta minuuttiprofiilista."""
    ctx = _ctx90()
    r = _rates(xg90=0.5, xa90=0.2, bonus90=0.5)
    assert xp.xp_full_90(3, r, ctx) == xp.xp_full_90(3, r, ctx)
    # ja se on sama kuin komponenttilaskenta taysilla minuuteilla
    assert xp.xp_full_90(3, r, ctx) == pytest.approx(
        xp.xp_components(3, r, 90.0, 1.0, 0.0, ctx)["total"])


def test_xp_full_90_counts_full_appearance_points():
    """Esiintyminen on taydet 2 pistetta, ei cameo-odotusarvoa skaalattuna.
    Tama on se komponentti joka teki vanhasta luvusta kaanteisen."""
    ctx = _ctx90()
    bare = xp.xp_full_90(4, _rates(), ctx)   # ei maaleja, syottoja, bonusta
    assert bare == pytest.approx(2.0, abs=0.01), (
        f"tyhjilla vauhdeilla per-90 pitaisi olla pelkka esiintyminen 2.0, "
        f"sai {bare:.3f}"
    )


# ---------------------------------------------------------------------------
# #143: data_basis — estimaatin datapohja-luokka (puhdas emissio)
# ---------------------------------------------------------------------------
def test_data_basis_no_history():
    assert xp.data_basis({"mins": 0}) == xp.DATA_BASIS_NONE


def test_data_basis_limited_history():
    assert xp.data_basis({"mins": 200.0}) == xp.DATA_BASIS_LIMITED


def test_data_basis_threshold_boundary():
    # Raja on M_PRIOR_ATTACK (_shrink90:n 50 %-piste): alle = priori dominoi.
    assert xp.data_basis({"mins": xp.M_PRIOR_ATTACK - 1}) == xp.DATA_BASIS_LIMITED
    assert xp.data_basis({"mins": xp.M_PRIOR_ATTACK}) == xp.DATA_BASIS_FULL


def test_data_basis_full_history():
    assert xp.data_basis({"mins": 3000.0}) == xp.DATA_BASIS_FULL


def test_data_basis_defensive_inputs():
    # Puuttuva/None-mins ei saa kaataa; palautusarvo aina tunnettu luokka.
    assert xp.data_basis({}) == xp.DATA_BASIS_NONE
    assert xp.data_basis({"mins": None}) == xp.DATA_BASIS_NONE
    for acc in ({}, {"mins": None}, {"mins": 0}, {"mins": 10}, {"mins": 5000}):
        assert xp.data_basis(acc) in xp.DATA_BASIS_VALUES


# ---------------------------------------------------------------------------
# #151: 26/27 BPS-oikaisu (bonus-historian uudelleenjako)
# ---------------------------------------------------------------------------
def test_bps_2627_delta_cbi_only():
    # 12 CBI: vanha 12//2=6 BPS, uusi 12//3=4 -> delta -2. Ei pilkkutorjuntoja.
    assert xp.bps_2627_delta({"clearances_blocks_interceptions": 12}) == -2
    # 5 CBI: vanha 2, uusi 1 -> -1.
    assert xp.bps_2627_delta({"clearances_blocks_interceptions": 5}) == -1
    # 0-2 CBI: molemmilla 0 tai sama floor -> 0 / -1 rajat.
    assert xp.bps_2627_delta({"clearances_blocks_interceptions": 0}) == 0
    assert xp.bps_2627_delta({"clearances_blocks_interceptions": 2}) == -1


def test_bps_2627_delta_penalty_save():
    assert xp.bps_2627_delta({"penalties_saved": 1}) == -1
    assert xp.bps_2627_delta({"penalties_saved": 2,
                              "clearances_blocks_interceptions": 6}) == -3


def test_bps_2627_delta_defensive_inputs():
    assert xp.bps_2627_delta({}) == 0
    assert xp.bps_2627_delta({"clearances_blocks_interceptions": None,
                              "penalties_saved": None}) == 0


def test_allocate_bonus_plain_top3():
    assert xp.allocate_bonus([30, 25, 20, 10]) == [3, 2, 1, 0]


def test_allocate_bonus_tie_for_first():
    # Tasoissa 1.: molemmat 3, seuraava 1 (2 pistettä ei jaeta).
    assert xp.allocate_bonus([30, 30, 20, 10]) == [3, 3, 1, 0]


def test_allocate_bonus_tie_for_second():
    # Tasoissa 2.: 1. saa 3, tasoissa olevat 2, 1 pistettä ei jaeta.
    assert xp.allocate_bonus([30, 25, 25, 10]) == [3, 2, 2, 0]


def test_allocate_bonus_tie_for_third():
    assert xp.allocate_bonus([30, 25, 20, 20, 10]) == [3, 2, 1, 1, 0]


def test_allocate_bonus_short_lists():
    assert xp.allocate_bonus([]) == []
    assert xp.allocate_bonus([10]) == [3]
    assert xp.allocate_bonus([10, 5]) == [3, 2]


def test_adjust_summaries_reallocates_and_is_pure():
    # Ottelu 1: A (CB, bps 30 josta iso CBI-osuus) vs B (bps 29, ei CBI:tä).
    # Vanha jako: A=3, B=2. 26/27: A:n 12 CBI -> -2 BPS -> A 28 < B 29 -> flip.
    row_a = {"fixture": 1, "minutes": 90, "bps": 30, "bonus": 3,
             "clearances_blocks_interceptions": 12}
    row_b = {"fixture": 1, "minutes": 90, "bps": 29, "bonus": 2,
             "clearances_blocks_interceptions": 0}
    row_c = {"fixture": 1, "minutes": 90, "bps": 10, "bonus": 1,
             "clearances_blocks_interceptions": 0}
    summaries = {101: [dict(row_a)], 102: [dict(row_b)], 103: [dict(row_c)]}
    out = xp.adjust_summaries_bps_2627(summaries)
    assert out[102][0]["bonus"] == 3   # nousi
    assert out[101][0]["bonus"] == 2   # laski
    assert out[103][0]["bonus"] == 1   # ennallaan
    # Puhtaus: syöte ei mutatoitunut.
    assert summaries[101][0]["bonus"] == 3
    assert summaries[102][0]["bonus"] == 2


def test_adjust_summaries_zero_minutes_excluded():
    # 0 min pelannut ei osallistu jakoon eikä saa bonusta.
    summaries = {
        1: [{"fixture": 7, "minutes": 0, "bps": 50, "bonus": 0}],
        2: [{"fixture": 7, "minutes": 90, "bps": 10, "bonus": 3}],
    }
    out = xp.adjust_summaries_bps_2627(summaries)
    assert out[1][0]["bonus"] == 0
    assert out[2][0]["bonus"] == 3


def test_adjust_summaries_total_bonus_conserved_no_ties():
    # Ilman tasapelejä ottelun bonuspotti pysyy 3+2+1:nä.
    summaries = {i: [{"fixture": 5, "minutes": 90, "bps": 40 - 2 * i, "bonus": 0,
                      "clearances_blocks_interceptions": 0}]
                 for i in range(1, 8)}
    out = xp.adjust_summaries_bps_2627(summaries)
    total = sum(out[i][0]["bonus"] for i in range(1, 8))
    assert total == 6


# ---------------------------------------------------------------------------
# Endpoint (TestClient conftestista)
# ---------------------------------------------------------------------------
def test_fantasy_xp_endpoint_shape(client):
    r = client.get("/api/fantasy/xp")
    assert r.status_code == 200
    # 26.7 PERF: tietoinen poikkeus muiden endpointtien no-storeen — ainoa iso
    # payload (555 kB) haettiin joka sivulatauksella vaikka data on 3 h vanhaa.
    # `private` + `Vary: Authorization` ovat pakollisia, koska vastaus riippuu
    # Bearer-tokenista (mask_xp_payload) eikä saa päätyä jaettuun välimuistiin.
    assert r.headers["cache-control"] == "private, max-age=300"
    assert r.headers["vary"] == "Authorization"
    assert r.headers["etag"].startswith('W/"xp-')
    data = r.json()
    assert "meta" in data and "players" in data
    assert isinstance(data["players"], list)


def test_fantasy_xp_etag_revalidates_to_304(client):
    """Toinen haku samalla ETagilla → 304 eikä payloadia siirretä uudelleen."""
    first = client.get("/api/fantasy/xp")
    etag = first.headers["etag"]
    again = client.get("/api/fantasy/xp", headers={"If-None-Match": etag})
    assert again.status_code == 304
    assert again.headers["etag"] == etag
    assert again.content == b""
    # Väärä ETag → täysi vastaus (ei hiljaista 304:ää vanhentuneelle datalle)
    stale = client.get("/api/fantasy/xp", headers={"If-None-Match": 'W/"xp-old-f"'})
    assert stale.status_code == 200
    assert "players" in stale.json()


# ---------------------------------------------------------------------------
# Minuuttimalli
# ---------------------------------------------------------------------------
def test_minutes_form_full_starter():
    mins = {r: 90 for r in range(1, 11)}
    xmins, p60, p1 = xp.minutes_form(mins, list(range(1, 11)))
    assert xmins == pytest.approx(90.0)
    assert p60 == pytest.approx(1.0)
    assert p1 == pytest.approx(0.0)


def test_minutes_form_no_history():
    assert xp.minutes_form({}, []) == (0.0, 0.0, 0.0)


def test_minutes_form_benched_recently_decays():
    # Pelasi 90 min kierrokset 1-3, penkillä (0 min) kierrokset 4-5:
    # recency-painotus painaa xMinsin alle puoleen.
    mins = {1: 90, 2: 90, 3: 90, 4: 0, 5: 0}
    xmins, p60, _ = xp.minutes_form(mins, [1, 2, 3, 4, 5])
    assert xmins < 45.0
    assert p60 < 0.5


def test_minutes_form_full_window_uniform():
    # n_last=None (pre-season): koko kausi tasapainoin — lopun rotaatio
    # ei romahduta xMinsiä. 33x90 + 5x20 -> keskiarvo ~80.8, ei ~30.
    mins = {r: 90 for r in range(1, 34)}
    mins.update({r: 20 for r in range(34, 39)})
    rounds = list(range(1, 39))
    xmins_all, p60_all, _ = xp.minutes_form(mins, rounds, n_last=None)
    xmins_l5, _, _ = xp.minutes_form(mins, rounds, n_last=5)
    assert xmins_all == pytest.approx((33 * 90 + 5 * 20) / 38)
    assert p60_all == pytest.approx(33 / 38)
    assert xmins_l5 == pytest.approx(20.0)


def test_minutes_form_missing_round_counts_as_zero():
    # Kierros ilman riviä (esim. loukkaantunut) = 0 min, ei kaadu.
    mins = {1: 90}
    xmins, _, _ = xp.minutes_form(mins, [1, 2, 3, 4, 5])
    assert 0.0 < xmins < 20.0


# ---------------------------------------------------------------------------
# Vauhdit + shrinkage
# ---------------------------------------------------------------------------
def _acc(**kw):
    base = {"mins": 0.0, "xg": 0.0, "xa": 0.0, "saves": 0.0,
            "yc": 0.0, "bonus": 0.0, "n60": 0, "dc_hits": 0}
    base.update(kw)
    return base


PRIORS = {p: {"xg90": 0.2, "xa90": 0.1, "saves90": 0.0, "yc90": 0.15,
              "bonus90": 0.1, "dc_freq": 0.2} for p in xp.POS_NAME}


def test_player_rates_zero_minutes_returns_prior():
    rates = xp.player_rates(_acc(), 4, PRIORS)
    assert rates["xg90"] == pytest.approx(0.2)
    assert rates["dc_freq"] == pytest.approx(0.2)


def test_player_rates_large_sample_dominates_prior():
    # 3000 min ja 30 xG (0.9/90) >> priori 0.2 -> vauhti lähellä havaittua.
    rates = xp.player_rates(_acc(mins=3000.0, xg=30.0), 4, PRIORS)
    assert rates["xg90"] > 0.75


def test_accumulate_history_parses_string_xg():
    rows = [{"minutes": 90, "expected_goals": "0.85", "expected_assists": "0.10",
             "saves": 0, "yellow_cards": 1, "bonus": 2}]
    acc = xp.accumulate_history(rows)
    assert acc["xg"] == pytest.approx(0.85)
    assert acc["n60"] == 1
    assert acc["yc"] == 1


def test_dc_hit_thresholds():
    assert xp.dc_hit({"defensive_contribution": 10}, 2) is True   # DEF: CBIT >= 10
    assert xp.dc_hit({"defensive_contribution": 9}, 2) is False
    assert xp.dc_hit({"defensive_contribution": 12}, 3) is True   # MID: CBIRT >= 12
    assert xp.dc_hit({"defensive_contribution": 11}, 3) is False
    assert xp.dc_hit({"defensive_contribution": 99}, 1) is False  # GKP: ei DC-pisteitä


# ---------------------------------------------------------------------------
# xP-komponentit
# ---------------------------------------------------------------------------
CTX = {"goal_mult": 1.0, "cs_prob": 0.5,
       "conceded_dist": [0.5, 0.3, 0.15, 0.05], "opp_goal_mult": 1.0}


def _rates(**kw):
    base = {"xg90": 0.0, "xa90": 0.0, "saves90": 0.0, "yc90": 0.0,
            "bonus90": 0.0, "dc_freq": 0.0}
    base.update(kw)
    return base


def test_xp_appearance_points():
    comp = xp.xp_components(4, _rates(), 90.0, 1.0, 0.0, CTX)
    assert comp["appearance"] == pytest.approx(2.0)
    comp = xp.xp_components(4, _rates(), 30.0, 0.0, 1.0, CTX)
    assert comp["appearance"] == pytest.approx(1.0)


def test_xp_goal_points_by_position():
    # Sama E[maalit]=0.5: FWD 4 p/maali, MID 5, DEF 6, GKP 10 (25/26-sääntö).
    for pos, pts in ((4, 4), (3, 5), (2, 6), (1, 10)):
        comp = xp.xp_components(pos, _rates(xg90=0.5), 90.0, 1.0, 0.0, CTX)
        assert comp["goals"] == pytest.approx(0.5 * pts)


def test_xp_clean_sheet_only_gk_def_mid():
    for pos, pts in ((1, 4), (2, 4), (3, 1), (4, 0)):
        comp = xp.xp_components(pos, _rates(), 90.0, 1.0, 0.0, CTX)
        assert comp["clean_sheet"] == pytest.approx(0.5 * pts)


def test_xp_conceded_penalty_negative_for_def():
    # E[floor(k/2)] = 0.15*1 + 0.05*1 = 0.20 -> -0.20 DEF:lle täydellä pelillä
    comp = xp.xp_components(2, _rates(), 90.0, 1.0, 0.0, CTX)
    assert comp["conceded"] == pytest.approx(-0.20)
    comp_fwd = xp.xp_components(4, _rates(), 90.0, 1.0, 0.0, CTX)
    assert comp_fwd["conceded"] == 0.0


def test_xp_saves_only_gk():
    comp = xp.xp_components(1, _rates(saves90=3.0), 90.0, 1.0, 0.0, CTX)
    assert comp["saves"] == pytest.approx(1.0)
    assert xp.xp_components(2, _rates(saves90=3.0), 90.0, 1.0, 0.0, CTX)["saves"] == 0.0


def test_xp_goal_mult_scales_attack():
    easy = dict(CTX, goal_mult=1.5)
    hard = dict(CTX, goal_mult=0.6)
    c_easy = xp.xp_components(4, _rates(xg90=0.5), 90.0, 1.0, 0.0, easy)
    c_hard = xp.xp_components(4, _rates(xg90=0.5), 90.0, 1.0, 0.0, hard)
    assert c_easy["goals"] > c_hard["goals"]


def test_xp_total_is_component_sum():
    comp = xp.xp_components(3, _rates(xg90=0.3, xa90=0.2, yc90=0.2, bonus90=0.5,
                                      dc_freq=0.3), 90.0, 0.9, 0.1, CTX)
    assert comp["total"] == pytest.approx(
        sum(v for k, v in comp.items() if k != "total"))


def test_expected_conceded_penalty():
    # P(2)=1 -> floor(2/2)=1 piste menetetty
    assert xp.expected_conceded_penalty([0.0, 0.0, 1.0]) == pytest.approx(1.0)
    # P(3)=1 -> floor(3/2)=1
    assert xp.expected_conceded_penalty([0.0, 0.0, 0.0, 1.0]) == pytest.approx(1.0)
    # P(0)=1 -> 0
    assert xp.expected_conceded_penalty([1.0]) == 0.0


# ---------------------------------------------------------------------------
# 28.7: bonus skaalautuu ottelun mukaan, DefCon ja kortit EIVÄT.
#
# Mitattu 25/26:n per-ottelu-historiasta (7382 ottelua, >=60 min, pelaajan
# sisäiset poikkeamat): bonus r=+0.074 / BPS r=+0.167 vastustajan heikkoutta
# vastaan, mutta DefCon vain +0.026 ja kortit +0.034 — ja koska DefCon-pisteet
# laukeavat 10/12 toiminnon kynnyksellä, 0.16 toiminnon siirtymä tasolla 6.5
# ei liikuta pisteitä. Tämä testi lukitsee molemmat puolet.
# ---------------------------------------------------------------------------

def _bonus_rates():
    return {"xg90": 0.4, "xa90": 0.3, "yc90": 0.15, "bonus90": 0.6,
            "saves90": 0.0, "dc_freq": 0.5}


def _bonus_ctx(goal_mult: float):
    return {"goal_mult": goal_mult, "cs_prob": 0.25,
            "conceded_dist": [0.25, 0.35, 0.25, 0.15], "opp_goal_mult": 1.0}


def test_bonus_scales_with_fixture():
    from src.models import fpl_xp as m
    easy = m.xp_components(3, _bonus_rates(), 85.0, 0.9, 0.05, _bonus_ctx(1.30))
    hard = m.xp_components(3, _bonus_rates(), 85.0, 0.9, 0.05, _bonus_ctx(0.75))
    assert easy["bonus"] > hard["bonus"], "bonus ei reagoi otteluun"
    # Kerroin on 1 + beta*(goal_mult-1) -> suhde on ennustettava.
    exp = ((1 + m.BONUS_FIXTURE_BETA * 0.30)
           / (1 + m.BONUS_FIXTURE_BETA * -0.25))
    assert abs(easy["bonus"] / hard["bonus"] - exp) < 1e-9


def test_defcon_and_cards_stay_fixture_blind():
    """Mitattu vaikutus oli olematon -> niitä EI saa skaalata vahingossa."""
    from src.models import fpl_xp as m
    easy = m.xp_components(2, _bonus_rates(), 85.0, 0.9, 0.05, _bonus_ctx(1.30))
    hard = m.xp_components(2, _bonus_rates(), 85.0, 0.9, 0.05, _bonus_ctx(0.75))
    assert easy["def_contribution"] == hard["def_contribution"]
    assert easy["cards"] == hard["cards"]
    assert easy["appearance"] == hard["appearance"]


def test_bonus_multiplier_cannot_go_negative():
    from src.models import fpl_xp as m
    assert m._bonus_fixture_mult(-5.0) == 0.0
    assert m._bonus_fixture_mult(1.0) == 1.0


# ---------------------------------------------------------------------------
# 5.8.2026: rakenteellinen joukkuerajoite (1 GK + 10 kenttapelaajaa)
# ---------------------------------------------------------------------------

def test_depth_factor_scales_overbooked_group_without_limit():
    """Kaksi entista ykkosvahtia samassa klubissa -> summan ON tultava 1.0.

    Tama on se tila joka mitattiin tuotannosta 5.8: Tottenhamin maalivahtien
    Sigma p_start oli 2,10 kun avauspaikkoja on tasan 1. Alaskaalauksella EI
    ole cappia, koska tila on mahdoton eika vain epatodennakoinen.
    """
    keepers = [0.83, 0.76, 0.35, 0.16]           # Sigma 2.10
    f = xp.depth_factor(keepers, xp.TEAM_GK_SLOTS)
    assert f < 1.0
    assert sum(k * f for k in keepers) == pytest.approx(xp.TEAM_GK_SLOTS)


def test_depth_factor_boost_stays_capped_for_thin_group():
    """Alibuukattu ryhma EI skaalaudu taydeksi.

    Nousijaklubien kenttapelaajien summa oli 4,71 (Hull) kun paikkoja on 10.
    Se ei ole sama vika: syy on ohuen otoksen hintapriori, eika sita korjata
    kertomalla koko ryhma kahdella. Nosto pysyy DEPTH_BOOST_CAPissa.
    """
    thin = [0.72, 0.30, 0.30, 0.08, 0.08]        # Sigma 1.48, slots 10
    f = xp.depth_factor(thin, xp.TEAM_OUTFIELD_SLOTS)
    assert f == pytest.approx(xp.DEPTH_BOOST_CAP)
    assert sum(t * f for t in thin) < xp.TEAM_OUTFIELD_SLOTS


def test_scale_p_start_keeps_minutes_consistent():
    """Skaalaus johtaa minuutit uudelleen — muuten p_start ja xmins eriytyvat
    ja UI nayttaisi vahdin jolla on 0.5 aloitus-tn mutta 90 odotettua min."""
    mm = xp.minutes_model({r: 90.0 for r in range(1, 11)},
                          {r: 1 for r in range(1, 11)},
                          list(range(1, 11)), n_last=None)
    before_x, before_p = mm["xmins"], mm["p_start_raw"]
    out = xp.scale_p_start(mm, 0.5)
    assert out["p_start_raw"] == pytest.approx(before_p * 0.5)
    assert out["xmins"] < before_x, "minuutit eivat seuranneet aloitus-tn:aa"


def test_structural_exponent_protects_nailed_starter():
    """Leikkaus kohdistuu epavarmoihin, ei naulattuun avaajaan.

    Tasainen kerroin vei 5.8. mittauksessa 15 min myos Chelsean naulatuilta
    (Lacroix 86,7 -> 71,3), koska ylibuukkaus jaettiin tasan. p**k leikkaa
    pienet jyrkasti ja saastaa suuret.
    """
    grp = [0.95, 0.90, 0.60, 0.55, 0.50, 0.45, 0.40]      # Sigma 4.35, slots 3
    k = xp.structural_exponent(grp, 3.0)
    scaled = [p ** k for p in grp]
    assert sum(scaled) == pytest.approx(3.0, abs=1e-6)
    # naulattu menettaa selvasti vahemman suhteessa kuin epavarma
    nailed_loss = (grp[0] - scaled[0]) / grp[0]
    fringe_loss = (grp[-1] - scaled[-1]) / grp[-1]
    assert nailed_loss < fringe_loss / 2, (
        f"naulattu menetti {nailed_loss:.1%}, epavarma {fringe_loss:.1%} — "
        "leikkaus ei kohdistu epavarmuuteen"
    )
    # ja tasainen kerroin EI olisi tehnyt tata (negatiivinen kontrolli)
    flat = 3.0 / sum(grp)
    assert (grp[0] - grp[0] * flat) / grp[0] > nailed_loss


def test_structural_exponent_noop_when_within_slots():
    assert xp.structural_exponent([0.4, 0.3], 1.0) == 1.0
    assert xp.structural_exponent([0.5, 0.5], 1.0) == 1.0


def test_structural_pass_never_touches_nailed_starter():
    """Villen korjaus 5.8: keskikentan ruuhka ei saa lyhentaa selkean
    ykkoshyokkaajan minuutteja. Naulattu (raw >= NAILED_PROTECT_P_START) on
    koskematon kun ylibuukkaus tulee muista; leikkaus osuu kiistanalaisiin."""
    nailed = 0.92
    fringe = [0.60, 0.55, 0.50, 0.45]           # kiistanalaiset
    slots = 2.0                                  # naulattu + 1.08 muille
    assert nailed >= xp.NAILED_PROTECT_P_START
    cut = slots - nailed
    k = xp.structural_exponent(fringe, cut)
    scaled = [f ** k for f in fringe]
    assert sum(scaled) == pytest.approx(cut, abs=1e-6)
    # naulattu ei ole mukana leikkauksessa lainkaan -> summa = slots tasan
    assert nailed + sum(scaled) == pytest.approx(slots, abs=1e-6)


# ---------------------------------------------------------------------------
# Minuuttipriorin kolme korjausta (9.8.2026) — ks. cc-reports-raportti
# ---------------------------------------------------------------------------
def test_start_weights_length_matches_rounds():
    """Painolista yhta pitka kuin kierroslista JOKAISELLA ikkunalla.

    Regressio: START_WEIGHTS[-len(rounds):] palautti max 4 painoa, joten
    builderin n_last=6 katkaisi zip():n neljaan pariin.
    """
    for n_last in (4, 6, 8, None):
        for n in (1, 3, 4, 6, 12, 38):
            assert len(xp.start_weights(n, n_last)) == n, (n, n_last)


def test_start_weights_backwards_compatible_with_start_weights_const():
    """n_last=4 tuottaa entisen START_WEIGHTSin, myos vajaalla otoksella."""
    assert xp.start_weights(4, 4) == list(xp.START_WEIGHTS)
    assert xp.start_weights(3, 4) == list(xp.START_WEIGHTS[-3:])
    assert xp.start_weights(1, 4) == list(xp.START_WEIGHTS[-1:])


def test_minutes_model_window_uses_most_recent_rounds():
    """n_last=6: kaksi tuoreinta kierrosta EIVAT saa pudota pois.

    Regressio (9.8.2026): pelaaja joka avasi kierrokset 1-4 ja jai penkille
    5-6 sai p_start 1.0 / xmins 90.0 — malli luki hanet naulatuksi juuri kun
    han oli menettanyt paikkansa. Live-kauden polku, laukeaisi GW1:sta.
    """
    rounds = [1, 2, 3, 4, 5, 6]
    lost_place = xp.minutes_model({1: 90, 2: 90, 3: 90, 4: 90, 5: 0, 6: 0},
                                  {1: 1, 2: 1, 3: 1, 4: 1, 5: 0, 6: 0},
                                  rounds, n_last=6)
    won_place = xp.minutes_model({1: 0, 2: 0, 3: 0, 4: 0, 5: 90, 6: 90},
                                 {1: 0, 2: 0, 3: 0, 4: 0, 5: 1, 6: 1},
                                 rounds, n_last=6)
    assert lost_place["p_start_raw"] < 1.0, "tuoreet penkitykset katosivat"
    assert won_place["p_start_raw"] > 0.0, "tuoreet avaukset katosivat"
    assert won_place["xmins"] > lost_place["xmins"], (
        "recency-jarjestys on kaantynyt ikkunan sisalla")


def test_preseason_prior_weights_recent_role_higher():
    """Pre-season: roolinsa takaisin saanut ei saa jaada vaihtomieheksi.

    Palmer-tapaus 9.8.2026: 12 kierroksen loukkaantumisjakso alkukaudella,
    sitten avauspaikka loppukauden. Tasapaino antoi 51 min; recency nostaa.
    """
    mins = {r: (0.0 if r <= 12 else 90.0) for r in range(1, 39)}
    starts = {r: (0 if r <= 12 else 1) for r in range(1, 39)}
    rounds = list(range(1, 39))
    mm = xp.minutes_model(mins, starts, rounds, n_last=None)
    assert mm["xmins"] > 75.0, f"loukkaantumisjakso yha dominoi: {mm['xmins']:.1f}"
    # Peilitapaus: 26 avausta ja sitten 12 kierrosta sivussa. Priori EI voi
    # erottaa loukkaantumista paikan menetyksesta pelkista minuuteista (sen
    # ratkaisee FPL:n saatavuuslippu builderissa), joten lukitaan vain suunta:
    # loppukauden poissaolo painaa selvasti alle tasapainon (~62 min) ja
    # reilusti alle Palmer-tapauksen. Mitattu 9.8.2026: 35,2 min.
    mirror = xp.minutes_model({r: (90.0 if r <= 26 else 0.0) for r in range(1, 39)},
                              {r: (1 if r <= 26 else 0) for r in range(1, 39)},
                              rounds, n_last=None)
    assert mirror["xmins"] < 45.0, f"loppukauden poissaolo ei nakynyt: {mirror['xmins']:.1f}"
    assert mirror["xmins"] < mm["xmins"] - 25.0, (
        "roolinsa saanut ja sen menettanyt eivat erotu toisistaan")


def test_preseason_prior_blank_gameweek_does_not_count_as_benching():
    """Rivitton kierros (blank GW) ei saa painaa p_startia.

    Builder syottaa pelaajan omat kierrokset; tama lukitsee sen etta
    universumin valinnalla on merkitysta ja etta suunta on oikea.
    """
    mins = {r: 90.0 for r in range(1, 39) if r not in (31, 34)}
    starts = {r: 1 for r in range(1, 39) if r not in (31, 34)}
    own_rounds = sorted(mins)                      # oikein: blankit pois
    union_rounds = list(range(1, 39))              # vaarin: blankit mukana
    correct = xp.minutes_model(mins, starts, own_rounds, n_last=None)
    inflated_denominator = xp.minutes_model(mins, starts, union_rounds, n_last=None)
    assert correct["p_start_raw"] == pytest.approx(1.0)
    assert inflated_denominator["p_start_raw"] < 1.0
    assert correct["xmins"] > inflated_denominator["xmins"]


# ---------------------------------------------------------------------------
# Ship-gaten treeni-ikkuna (9.8.2026)
#
# Gate johti DC:n treenikaudet config.current_season_pair():sta eli
# KALENTERISTA, ei backtestattavasta kaudesta. Kausiflipin jalkeen se palautti
# ['2526','2627'], jolloin 25/26:n backtest fitattiin ilman edelliskautta ja
# nousijalista tyhjeni - mika tappoi hiljaa kaikki vs_promoted-slicet ilman
# yhtaan virheilmoitusta.
# ---------------------------------------------------------------------------
def test_seasons_for_uses_backtest_season_not_calendar():
    from scripts.backtest_fpl_xp import seasons_for

    assert seasons_for("2526") == ["2425", "2526"]
    assert seasons_for("2627") == ["2526", "2627"]
    # Vuosisadan vaihde ei saa tuottaa negatiivista tai 3-merkkista kautta.
    assert seasons_for("0001") == ["9900", "0001"]


def test_seasons_for_never_returns_the_same_season_twice():
    """Pari [X, X] tarkoittaisi etta fit nakee vain backtestattavan kauden."""
    from scripts.backtest_fpl_xp import seasons_for

    for key in ("2324", "2425", "2526", "2627"):
        prev, cur = seasons_for(key)
        assert prev != cur
        assert cur == key


# ---------------------------------------------------------------------------
# Pre-season-priorin validointi kesatauon yli (9.8.2026)
#
# Ship-gate ajaa walk-forwardia yhden kauden sisalla eika siksi kosketa
# pre-season-polkua lainkaan - juuri sita joka tuottaa GW1-luvut. Validointi
# lepaa kahden vaitteen varassa, ja molemmat lukitaan tassa.
# ---------------------------------------------------------------------------
def test_infinite_halflife_equals_balanced_weighting():
    """Tasapaino = aareton puoliintuma, ei erillista koodipolkua.

    Koko vertailu "vaimennus vs pre-9.8. tasapaino" nojaa tahan. Jos se ei
    pida, tasapaino-rivi mittaisi jotain muuta kuin entista kaytosta.
    """
    orig = xp.PRESEASON_HALFLIFE
    xp.PRESEASON_HALFLIFE = 1e9
    try:
        w = xp.start_weights(12, None)
    finally:
        xp.PRESEASON_HALFLIFE = orig
    assert len(w) == 12
    assert all(abs(x - 1.0) < 1e-6 for x in w)


def test_preseason_weights_favour_recent_rounds():
    """Vaimennuksen suunta: tuorein kierros painaa eniten, vanhin vahiten."""
    w = xp.start_weights(20, None)
    assert len(w) == 20
    assert w == sorted(w), "painojen pitaa kasvaa vanhimmasta tuoreimpaan"
    assert w[-1] > w[0]
    # Puoliintuma: PRESEASON_HALFLIFE kierroksen paassa paino on puolet.
    i = int(xp.PRESEASON_HALFLIFE)
    assert abs(w[-1 - i] / w[-1] - 0.5) < 1e-9


def test_prev_season_artifacts_are_keyed_by_code():
    """Avain on code, ei element-id.

    FPL:n id:t nollautuvat kausittain; id-avain kadottaisi osan pelaajista
    NAYTTAMATTA virhetta. 25/26:n bootstrapin codet ja artefaktin avaimet
    leikkaavat toisensa laajasti, id:t eivat leikkaisi mielekkaasti.
    """
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    p = root / "data" / "fpl_prev_season_minutes_2425.json"
    if not p.exists():
        pytest.skip("artefakti puuttuu (aja build_fpl_prev_season_minutes)")
    doc = json.loads(p.read_text(encoding="utf-8"))
    assert doc["schema_version"] == 1
    assert doc["n_rounds"] == 38
    assert doc["n_players"] > 400
    keys = [int(k) for k in doc["players"]]
    # FPL:n player code on 5-7-numeroinen; element-id on alle 1000.
    assert min(keys) > 1000, "avaimet nayttavat element-id:ilta, ei codeilta"


# ---------------------------------------------------------------------------
# Luottamuslippu (9.8.2026)
#
# Lippu korvaa luokituksen saadon, koska kalibrointi ei validoitunut:
# vaihtuvuuden suuruus on mitattavissa, suunta ei. Testit lukitsevat sen ettei
# lippu ala valehdella kumpaankaan suuntaan.
# ---------------------------------------------------------------------------
def _confidence_doc():
    import json
    from pathlib import Path
    p = Path(__file__).resolve().parents[1] / "data" / "team_confidence.json"
    if not p.exists():
        pytest.skip("team_confidence.json puuttuu (aja build_team_confidence)")
    return json.loads(p.read_text(encoding="utf-8"))


def test_confidence_covers_exactly_the_current_league():
    """20 joukkuetta, 3 nousijaa, 3 pudonnutta.

    Kausivaihdos on toistuva vikalahde: 8.8.2026 /fpl/defence listasi pudonneet
    ja unohti nousseet, koska vain toinen suunta tarkistettiin.
    """
    doc = _confidence_doc()
    assert len(doc["teams"]) == 20
    assert len(doc["promoted"]) == 3
    assert len(doc["relegated"]) == 3
    assert not (set(doc["promoted"]) & set(doc["relegated"]))


def test_confidence_flag_is_earned_not_relative():
    """Lippu laukeaa VAIN absoluuttisesta kynnyksesta.

    Houkutus rauhallisena kesana on laskea kynnysta kunnes joku laukaisee sen.
    Silloin lippu kertoisi "korkea vaihtuvuus" kesana jona vaihtuvuutta ei
    ollut. Jokaisella liputetulla on oltava luku kynnyksen ylapuolella.
    """
    doc = _confidence_doc()
    thr = doc["high_turnover_threshold_pct"]
    for t in doc["teams"]:
        if t["flag"] == "high_turnover":
            assert t["minutes_churn_pct"] >= thr
        elif not t["is_promoted"]:
            assert t["minutes_churn_pct"] < thr


def test_confidence_number_shown_even_when_not_flagged():
    """Luku naytetaan aina; muuten ominaisuus olisi tyhja rauhallisena kesana."""
    doc = _confidence_doc()
    for t in doc["teams"]:
        if t["is_promoted"]:
            assert t["flag"] == "promoted" and t["note"]
        else:
            assert t["minutes_churn_pct"] is not None
            assert t["note"], f"{t['team']} jai ilman selitetta"


def test_data_confidence_resolves_model_team_names():
    """API:n haku kayttaa MALLINIMIA, artefakti tallentaa ne map_namella.

    Jos nimimappays hajoaa, kentta jaa vain tyhjaksi eika mikaan kaadu — eli
    ominaisuus katoaisi HILJAA. Sama vikaluokka kuin kausivaihdoksen
    id-mappaus. Siksi tama testaa nimenomaan osumisen, ei pelkkaa rakennetta.
    """
    from api.main import _data_confidence, _load_team_confidence

    conf = _load_team_confidence()
    if not conf:
        pytest.skip("team_confidence.json puuttuu")
    assert len(conf) == 20
    got = _data_confidence("Newcastle United", "Coventry")
    assert "home" in got and "away" in got, f"nimimappays ei osunut: {got}"
    assert got["home"]["minutes_churn_pct"] is not None
    assert got["away"]["flag"] == "promoted"


def test_data_confidence_is_fail_safe_on_unknown_team():
    """Tuntematon joukkue ei saa kaataa ennustetta — lippu on lisatieto."""
    from api.main import _data_confidence

    assert _data_confidence("Ei Olemassa FC", "Toinen Ei-Olemassa") == {}
