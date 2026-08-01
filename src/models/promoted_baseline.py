"""Nousijoiden empiirinen PL-voima — YKSI jaettu lähde kaikille pinnoille.

ONGELMA (verifioitu tuotantoa vasten 27.7.2026):
    POST /api/predict {"home_team":"Arsenal","away_team":"Coventry",
                       "seasons":["2526","2627"]}
    -> 404 {"detail":"Away team 'Coventry' not found in model."}

1.8. alkaen mallin treeni-ikkuna on ['2526','2627']. Understatissa on 2526-
dataa muttei 2627 -> nousijoilla EI OLE YHTÄÄN riviä. GW1:ssä 21.8. se on
3/20 joukkuetta = jopa **3/10 ottelua per kierros ilman ennustetta**, ja tila
kestää kunnes kullakin on ~5-8 pelattua ottelua (loka-alku). Se on tasan se
ikkuna jossa GW1-liikennepiikki tulee.

MIKSI `promotion_priors.laske_alasarjapriorit` EI korjaa tätä (mitattu 27.7):
    tunnista_promotoidut(...)  -> []
    laske_alasarjapriorit(...) -> {}
Sen tunnistus etsii joukkueita jotka ovat ylätason datassa mutta eivät
edellisen kauden datassa. Esikaudella nousijoilla on NOLLA ottelua ylätasolla,
joten ne ovat sille näkymättömiä. Lisäksi `DixonColesModel.fit` ohittaa
team_priorsin hiljaa tuntemattomalle joukkueelle (`if tnimi in idx`) — priori
voi kutistaa olemassa olevaa estimaattia, mutta se ei voi LUODA joukkuetta.

MIKSI PELKKÄ SKAALAUS OLISI VÄÄRIN:
DC:n attack/defence ovat log-kertoimia liigan keskitason ympärillä. Championship-
estimaatin skaalaus kohti nollaa tekisi nousijasta PL:n KESKITASOISEN, mikä on
liian antelias — nousija on systemaattisesti keskitason alapuolella. Siksi
tässä käytetään empiiristä tasoa, ei skaalausta.

MENETELMÄ:
Viimeisimmän tunnetun nousijatrion TOTEUTUNUT PL-voima samasta fitistä.
24/25 nousi Ipswich, Leicester, Southampton -> niiden mitattu attack/defence/
kotietu on paras arvio siitä mitä nousijalta odotetaan. Mitattu 27.7:
attack -0.3018, defence +0.4813, home_gamma -0.1553.

OMINAISUUS JOKA RATKAISEE PORTIN: tämä on FITIN JÄLKEINEN injektio. Se lisää
avaimia joukkueille joita mallissa ei ole, eikä kosketa yhdenkään olemassa
olevan joukkueen estimaattia -> domestic-regressio pysyy bittitarkkana.

ITSESTÄÄN VANHENEVA: kun nousijalla on oikeaa PL-dataa, se on `dc.attack`issa
fitin jäljiltä ja `taydenna_nousijat` ohittaa sen. Baseline ei siis koskaan
ylikirjoita oikeaa estimaattia.
"""

from __future__ import annotations

import numpy as np

from src.models.dixon_coles import DixonColesModel

# ---------------------------------------------------------------------------
# Nousijat per kausi.
#
# MIKSI EKSPLISIITTINEN LISTA EIKÄ PÄÄTELTY: nousijalla on nolla ottelua
# ylätasolla ennen kauden alkua, joten sitä EI VOI päätellä otteludatasta —
# se on juuri tämän bugin juurisyy. Lista vaihtuu kerran vuodessa ja on
# verifioitavissa kahdesta riippumattomasta lähteestä (FPL bootstrap-static +
# football-data.org /api/standings), kuten tehtiin 27.7:
#   cc-reports/2026-07-27-standings-rollover-check.md §1
#
# Nimet ovat MALLINIMIÄ (Understat/football-data), eivät FD:n täysnimiä.
# ---------------------------------------------------------------------------
PROMOTED_BY_SEASON: dict[str, dict[str, tuple[str, ...]]] = {
    "2627": {"ENG-Premier League": ("Coventry", "Hull", "Ipswich")},
}

# ---------------------------------------------------------------------------
# Pudonneet per kausi — nousijalistan peilikuva, sama ylläpitosykli.
#
# MIKSI TÄMÄ ON OLEMASSA (kausiflippi 1.8.2026): treeni-ikkuna on kaksi
# kautta, joten 2526+2627-ikkunassa 25/26:n pudonneet OVAT mallissa (niillä
# on kokonainen kausi dataa) mutta ne eivät pelaa aktiivista kautta.
# /api/teams rakentaa ottelu-ennusteen joukkuevalitsimen mallin joukkueista
# → ilman suodatusta valitsin tarjoaisi Burnleyta 26/27-kaudella. Malli
# ITSE saa pitää joukkueet (H2H ja eksplisiittiset kausipyynnöt toimivat) —
# vain aktiivisen kauden LISTA suodatetaan.
#
# Verifioitu datasta 30.7.2026 (ENG_Premier_League_2526.csv:n joukkuejoukko
# miinus FPL 26/27 -feedin 20 joukkuetta): pudonneet = Burnley, West Ham,
# Wolverhampton Wanderers. Leicester EI kuulu tähän — se putosi jo 24/25:n
# jälkeen ja poistuu ikkunasta itsestään flipissä. Nimet ovat MALLINIMIÄ
# (verifioitu tuotannon /api/teams-listasta 30.7).
#
# Muut liigat voi lisätä samalla kaavalla kun niiden valitsinta halutaan
# siivota; puuttuva liiga = ei suodatusta = entinen käytös.
# ---------------------------------------------------------------------------
RELEGATED_BY_SEASON: dict[str, dict[str, tuple[str, ...]]] = {
    "2627": {
        "ENG-Premier League": ("Burnley", "West Ham", "Wolverhampton Wanderers"),
    },
}


def pudonneet_aktiiviselta_kaudelta(
    liigat: tuple[str, ...] | list[str],
    kaudet: tuple[str, ...] | list[str],
) -> frozenset[str]:
    """Joukkueet jotka ovat treeni-ikkunassa mutta eivät pelaa aktiivista
    kautta annetuissa liigoissa. Aktiivinen kausi = viimeisin pyydetyistä
    (sama sääntö kuin taydenna_nousijat). Tuntematon kausi/liiga → tyhjä
    joukko eli ei suodatusta — käytös ei voi muuttua vahingossa vanhoille
    kausipyynnöille."""
    if not kaudet:
        return frozenset()
    per_liiga = RELEGATED_BY_SEASON.get(str(kaudet[-1]))
    if not per_liiga:
        return frozenset()
    out: set[str] = set()
    for liiga in liigat:
        out.update(per_liiga.get(liiga, ()))
    return frozenset(out)

def nousijat_aktiiviselta_kaudelta(
    liigat: tuple[str, ...] | list[str],
    kaudet: tuple[str, ...] | list[str],
) -> frozenset[str]:
    """Kauden nousijat annetuissa liigoissa — pudonneet-suodattimen peilikuva
    /api/teams-valitsinta varten. Aktiivinen kausi = viimeisin pyydetyistä
    (sama sääntö kuin taydenna_nousijat). Tuntematon kausi/liiga → tyhjä
    joukko. HUOM: kutsuja vartioi listauksen dc.attack-jäsenyydellä, jotta
    valitsin ei koskaan tarjoa joukkuetta jolle /api/predict palauttaisi 404."""
    if not kaudet:
        return frozenset()
    per_liiga = PROMOTED_BY_SEASON.get(str(kaudet[-1]))
    if not per_liiga:
        return frozenset()
    out: set[str] = set()
    for liiga in liigat:
        out.update(per_liiga.get(liiga, ()))
    return frozenset(out)


# Viimeisin trio jonka PL-voima on mitattu (nousi 24/25).
REFERENCE_TRIO: tuple[str, ...] = ("Ipswich", "Leicester", "Southampton")

# ---------------------------------------------------------------------------
# JÄÄDYTETTY BASELINE — ja tämä on se kohta joka esti hiljaisen katoamisen.
#
# Viitetrio mitataan ENSISIJAISESTI nykyisestä fitistä (itsestään päivittyvä).
# Mutta 1.8.2026 alkaen ikkuna on ['2526','2627'], ja Ipswich, Leicester ja
# Southampton putosivat KAIKKI 24/25 jälkeen -> trio katoaa ikkunasta:
#
#     ikkuna ['2425','2526'] -> trio mallissa: Ipswich, Leicester, Southampton
#     ikkuna ['2526','2627'] -> trio mallissa: EI YHTÄÄN        (mitattu 27.7)
#
# Ilman tätä varakeinoa `add_promoted_baseline` olisi palauttanut hiljaa
# `trio_used: []` ja nousijat olisivat jääneet tuntemattomiksi. Seuraus EI
# olisi ollut virheilmoitus vaan katoaminen: `compute_fixtures` ohittaa
# fixturen jonka joukkuetta ei ole mallissa, joten FPL:n CS%/FDR olisi
# menettänyt kaikki Coventryn ja Hullin ottelut — ja sanity_gate olisi silti
# mennyt läpi, koska se ohittaa nousijatarkistukset kun `weak` on tyhjä
# (`weak = [t for t in promoted if t in agg]`).
#
# Arvot on MITATTU 27.7.2026 tuotantokonfiguraatiolla (ikkuna 2425+2526,
# decay 0.0035, bayes 2.0) — ei arvattu. Sama luku näkyy sen päivän
# Phase 0 -ajon lokissa.
#
# PÄIVITYSOHJE: kun uusi nousijatrio on pelannut kautensa, mittaa sen
# toteutunut attack/defence/home_gamma ja korvaa nämä. Siihen asti nämä ovat
# paras käytettävissä oleva arvio.
# ---------------------------------------------------------------------------
FROZEN_BASELINE: dict[str, float] = {
    "attack": -0.3018,
    "defence": 0.4813,
    "home_gamma": -0.1553,
}
FROZEN_PROVENANCE = "mitattu 27.7.2026, PL-ikkuna 2425+2526, trio Ipswich/Leicester/Southampton"


def add_promoted_baseline(dc: DixonColesModel, needed: list[str]) -> dict:
    """Anna `needed`-joukkueille viimeisimmän nousijatrion toteutunut PL-voima.

    Mutatoi `dc`:n paikan päällä. Palauttaa yhteenvedon telemetriaa/lokitusta
    varten. Jos trio puuttuu fitistä tai `needed` on tyhjä, ei tee mitään —
    baselinea ei arvata.
    """
    trio = [t for t in REFERENCE_TRIO if t in dc.attack]
    needed = [t for t in needed if t not in dc.attack]
    if not needed:
        return {"trio_used": trio, "applied_to": []}

    if trio:
        # Ensisijainen: mittaa trio nykyisestä fitistä (itsestään päivittyvä).
        base_att = float(np.mean([dc.attack[t] for t in trio]))
        base_def = float(np.mean([dc.defence[t] for t in trio]))
        base_gamma = float(
            np.mean([dc.home_advantage_per_team.get(t, 0.0) for t in trio])
        )
        source = "measured"
    else:
        # Varakeino: trio ei ole ikkunassa (1.8. alkaen se ei ole). ÄLÄ palauta
        # tyhjää — se johtaisi nousijoiden hiljaiseen katoamiseen, ei virheeseen.
        base_att = FROZEN_BASELINE["attack"]
        base_def = FROZEN_BASELINE["defence"]
        base_gamma = FROZEN_BASELINE["home_gamma"]
        source = "frozen"

    for t in needed:
        dc.attack[t] = base_att
        dc.defence[t] = base_def
        dc.home_advantage_per_team[t] = base_gamma
    return {
        "trio_used": trio,
        "applied_to": list(needed),
        "attack": round(base_att, 4),
        "defence": round(base_def, 4),
        "home_gamma": round(base_gamma, 4),
        # source tekee varakeinon kaytosta NAKYVAN: 'frozen' kertoo etta
        # viitetrio ei ollut ikkunassa. Ilman tata kentta olisi mahdotonta
        # erottaa mitattua ja jaadytettya baselinea jalkikateen.
        "source": source,
        "provenance": FROZEN_PROVENANCE if source == "frozen" else None,
    }


def taydenna_nousijat(
    dc: DixonColesModel,
    liigat: tuple[str, ...] | list[str],
    kaudet: tuple[str, ...] | list[str],
) -> dict:
    """Täydennä malliin kauden nousijat joilla ei ole yhtään ottelua.

    Kutsutaan FITIN JÄLKEEN. Turvallinen kutsua aina: jos kaudelle/liigalle ei
    ole kirjattuja nousijoita tai ne ovat jo mallissa, funktio on no-op.
    """
    if not kaudet:
        return {"applied_to": []}
    # Aktiivinen kausi = viimeisin pyydetyistä (kausipari ['2526','2627']).
    kausi = str(kaudet[-1])
    per_liiga = PROMOTED_BY_SEASON.get(kausi)
    if not per_liiga:
        return {"applied_to": []}

    needed: list[str] = []
    for liiga in liigat:
        for t in per_liiga.get(liiga, ()):
            if t not in dc.attack and t not in needed:
                needed.append(t)
    if not needed:
        return {"applied_to": []}
    return add_promoted_baseline(dc, needed)
