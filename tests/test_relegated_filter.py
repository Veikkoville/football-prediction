"""Kausiflipin joukkuelistasuodatus: pudonneet pois /api/teams-valitsimesta.

Ei verkkoa, ei mallifittiä — helper on puhdas funktio, endpoint testataan
stub-mallilla. Tausta: 2526+2627-ikkunassa 25/26:n pudonneet (Burnley,
West Ham, Wolverhampton Wanderers) ovat mallissa kokonaisella kaudella
dataa, mutta valitsin ei saa tarjota niitä 26/27-kaudella.
"""
from __future__ import annotations

from src.models.promoted_baseline import (
    RELEGATED_BY_SEASON,
    nousijat_aktiiviselta_kaudelta,
    pudonneet_aktiiviselta_kaudelta,
)

PL = "ENG-Premier League"


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------
def test_2627_ikkuna_suodattaa_pudonneet():
    pois = pudonneet_aktiiviselta_kaudelta((PL,), ("2526", "2627"))
    assert pois == {"Burnley", "West Ham", "Wolverhampton Wanderers"}


def test_vanha_ikkuna_ei_suodata_mitaan():
    # Eksplisiittinen vanha kausipyyntö säilyttää entisen käytöksen.
    assert pudonneet_aktiiviselta_kaudelta((PL,), ("2425", "2526")) == frozenset()


def test_tuntematon_liiga_ei_suodata():
    # 1.8 laajennuksen jälkeen FD-top-5 ON listoissa → aidosti tuntematon
    # liiga testaa yhä ettei suodatus laukea väärin.
    assert pudonneet_aktiiviselta_kaudelta(("NED-Eredivisie-FD",), ("2526", "2627")) == frozenset()


def test_tyhja_kausilista_ei_suodata():
    assert pudonneet_aktiiviselta_kaudelta((PL,), ()) == frozenset()


def test_aktiivinen_kausi_on_viimeisin():
    # Sama sääntö kuin taydenna_nousijat: kaudet[-1] määrää. Jos joku pyytää
    # yhden kauden ikkunaa ['2627'], suodatus pätee silti.
    assert pudonneet_aktiiviselta_kaudelta((PL,), ("2627",)) == {
        "Burnley", "West Ham", "Wolverhampton Wanderers",
    }


def test_negatiivinen_kontrolli_lista_luetaan_datasta(monkeypatch):
    # Kontrolli joka kaatuu jos suodatin ei oikeasti lue RELEGATED_BY_SEASONia
    # (esim. palauttaa aina vakiojoukon tai aina tyhjän).
    monkeypatch.setitem(
        RELEGATED_BY_SEASON, "9999", {PL: ("Testipudonnut",)}
    )
    assert pudonneet_aktiiviselta_kaudelta((PL,), ("9998", "9999")) == {"Testipudonnut"}
    assert "Burnley" not in pudonneet_aktiiviselta_kaudelta((PL,), ("9998", "9999"))


# ---------------------------------------------------------------------------
# Nousijahelper (valitsimen peilikuva pudonneille)
# ---------------------------------------------------------------------------
def test_2627_ikkuna_listaa_nousijat():
    lisaa = nousijat_aktiiviselta_kaudelta((PL,), ("2526", "2627"))
    assert lisaa == {"Coventry", "Hull", "Ipswich"}


def test_nousijahelper_vanha_ikkuna_tyhja():
    assert nousijat_aktiiviselta_kaudelta((PL,), ("2425", "2526")) == frozenset()
    assert nousijat_aktiiviselta_kaudelta((PL,), ()) == frozenset()
    # 1.8: ESP on nyt nousijalistoissa → tuntemattoman liigan kontrolli.
    assert nousijat_aktiiviselta_kaudelta(("NED-Eredivisie-FD",), ("2526", "2627")) == frozenset()
    assert nousijat_aktiiviselta_kaudelta(("ESP-La Liga-FD",), ("2526", "2627")) == {
        "Málaga CF", "RC Deportivo La Coruña", "Real Racing Club de Santander",
    }


# ---------------------------------------------------------------------------
# /api/teams-endpoint stub-mallilla (ei fittiä)
# ---------------------------------------------------------------------------
class _StubDC:
    def __init__(self, teams, attack=None):
        self.teams_ = list(teams)
        # attack voi kattaa teams_-listaa laajemman joukon: fitin jälkeinen
        # nousijainjektio (taydenna_nousijat) lisää avaimia vain attackiin.
        self.attack = {t: 0.0 for t in (attack if attack is not None else teams)}


def test_list_teams_suodattaa_pudonneet_2627(monkeypatch):
    import api.main as m

    kaikki = ["Arsenal", "Burnley", "Coventry", "Hull", "West Ham",
              "Wolverhampton Wanderers"]
    monkeypatch.setattr(m, "_saa_malli", lambda *a, **k: _StubDC(kaikki))
    resp = m.list_teams(leagues=[PL], seasons=["2526", "2627"])
    # Ipswich tulee nousijaunionista vain jos se on attackissa — stubissa ei ole.
    assert resp.teams == ["Arsenal", "Coventry", "Hull"]
    # Kontrolli: sama stub vanhalla ikkunalla palauttaa kaikki.
    resp_vanha = m.list_teams(leagues=[PL], seasons=["2425", "2526"])
    assert resp_vanha.teams == sorted(kaikki)


def test_list_teams_listaa_injektoidut_nousijat(monkeypatch):
    # Tuotantotilanne 1.8: nousijat EIVÄT ole teams_-listassa (ei treenidataa)
    # mutta OVAT attackissa injektion jäljiltä → valitsimen pitää listata ne.
    import api.main as m

    treenidata = ["Arsenal", "Burnley", "Chelsea"]
    injektion_jalkeen = treenidata + ["Coventry", "Hull", "Ipswich"]
    monkeypatch.setattr(
        m, "_saa_malli",
        lambda *a, **k: _StubDC(treenidata, attack=injektion_jalkeen))
    resp = m.list_teams(leagues=[PL], seasons=["2526", "2627"])
    assert resp.teams == ["Arsenal", "Chelsea", "Coventry", "Hull", "Ipswich"]


def test_list_teams_ei_listaa_nousijaa_ilman_injektiota(monkeypatch):
    # attack-vartio: jos injektio epäonnistui, valitsin ei saa tarjota
    # joukkuetta jolle /api/predict palauttaisi 404.
    import api.main as m

    treenidata = ["Arsenal", "Chelsea"]
    monkeypatch.setattr(
        m, "_saa_malli", lambda *a, **k: _StubDC(treenidata))
    resp = m.list_teams(leagues=[PL], seasons=["2526", "2627"])
    assert resp.teams == ["Arsenal", "Chelsea"]
