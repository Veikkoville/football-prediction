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
# Kohorttitunnisteet. Liigalla voi olla yksi nimeton kohortti (tuple, entinen
# muoto) tai useita nimettyja (dict) — ks. REFERENCE_BY_LEAGUE:n kommentti.
COHORT_UP = "promoted_from_below"
COHORT_DOWN = "relegated_from_above"

PROMOTED_BY_SEASON: dict[str, dict[str, tuple[str, ...] | dict[str, tuple[str, ...]]]] = {
    "2627": {
        "ENG-Premier League": ("Coventry", "Hull", "Ipswich"),
        # 1.8 laajennus (TASKS 4d, Villen GO "samanlainen laajennus kuin
        # PL:ssä"): ilman injektiota 378 ottelua ohittui track recordista
        # (accuracy-ajon mittaus 1.8: PD 108, SA 108, FL1 66, BL1 96).
        # FD-liigojen MALLINIMET = football-data.org:n täysnimet (loader
        # käyttää homeTeam.name-kenttää sellaisenaan) — verifioitu
        # PD/SA/FL1/BL1_2026.json-joukkuediffillä 1.8.
        "ESP-La Liga-FD": (
            "Málaga CF", "RC Deportivo La Coruña", "Real Racing Club de Santander",
        ),
        "ITA-Serie A-FD": ("AC Monza", "Frosinone Calcio", "Venezia FC"),
        "FRA-Ligue 1-FD": ("ES Troyes AC", "Le Mans FC"),
        "GER-Bundesliga-FD": (
            "FC Schalke 04", "SC Paderborn 07", "SV 07 Elversberg",
        ),
        # 15.8 (Villen GO): Championshipin kuusi tulokasta KAHTENA kohorttina.
        # Perustelu ja mittaustapa: ks. REFERENCE_BY_LEAGUE yllä.
        #
        # Nimet ovat football-data.co.uk:n E-sarjojen mallinimia ja ne on
        # VERIFIOITU lähdetiedostoista eikä muistettu: 'West Ham' ja 'Wolves'
        # löytyvät E0 24/25:stä, 'Burnley' E0 25/26:sta (se pelasi 24/25:n
        # Championshipissa), ja 'Bolton', 'Cardiff', 'Lincoln' E2 25/26:sta.
        # Väärä nimi ei kaataisi mitään — se injektoisi avaimen jota kukaan ei
        # hae, ja joukkue jäisi silti puuttumaan.
        "ENG-Championship": {
            COHORT_UP: ("Bolton", "Cardiff", "Lincoln"),
            COHORT_DOWN: ("Burnley", "West Ham", "Wolves"),
        },
    },
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
        # 1.8: sama valitsinsiivous muille liigoille nousijalaajennuksen
        # parina (kausidiff FD-datasta, sama ajo kuin PROMOTED-listat yllä).
        "ESP-La Liga-FD": ("Girona FC", "RCD Mallorca", "Real Oviedo"),
        "ITA-Serie A-FD": ("AC Pisa 1909", "Hellas Verona FC", "US Cremonese"),
        "FRA-Ligue 1-FD": ("FC Metz", "FC Nantes"),
        "GER-Bundesliga-FD": (
            "1. FC Heidenheim 1846", "FC St. Pauli 1910", "VfL Wolfsburg",
        ),
        # 15.8.2026: kolme liigaa lisattiin track recordiin (Villen
        # toimeksianto), ja samalla paljastui etta niiden VALITSIN tarjosi
        # joukkueita jotka eivat pelaa kautta 26/27 lainkaan.
        #
        # MITATTU eika arvattu: FD:n todelliset 26/27-osallistujat
        # (/api/fixtures, 45 vrk) resolvoituna mallinimiin, ja erotus mallin
        # /api/teams-listaan. Lahde on tallennettu:
        # tests/fixtures/fd_participants_2026-08-15.json
        #
        # Championshipissa poistuvat kahta eri reittia — Coventry, Hull ja
        # Ipswich nousivat PL:aan (ne ovat jo PROMOTED-listalla PL:n puolella),
        # Leicester, Oxford ja Sheffield Weds putosivat League Oneen. Molemmat
        # tarkoittavat samaa asiaa tälle listalle: eivat pelaa Championshipia.
        "ENG-Championship": (
            "Coventry", "Hull", "Ipswich", "Leicester", "Oxford",
            "Sheffield Weds",
        ),
        "NED-Eredivisie": ("Heracles", "NAC Breda", "Volendam"),
        "POR-Primeira Liga": ("AVS", "Tondela"),
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
        # 🔴 `_kohortteina` on PAKOLLINEN, ei kosmetiikkaa. Liigan arvo voi olla
        # dict {kohortti: joukkueet} (Championship 15.8 alkaen), ja dictin yli
        # iterointi antaa KOHORTTIEN NIMET joukkueiden sijaan. Mitattu
        # tuotannosta: nousijapoiminta palautti {'promoted_from_below',
        # 'relegated_from_above'} ja /api/teams naytti Championshipille 18
        # joukkuetta 24:n sijaan.
        #
        # Vika oli NAKYMATON koska kutsuja vartioi listauksen `dc.attack`
        # -jasenyydella: kohorttinimet eivat ole mallissa, joten ne suodattuivat
        # pois eivatka paatyneet valitsimeen. Vartio muutti rikkinaisen listan
        # hiljaa vajaaksi listaksi — hyvaa suunnittelua, ja juuri siksi tama oli
        # loydettava mittaamalla tuotannosta eika lukemalla koodia.
        #
        # Sama normalisointi molemmissa funktioissa vaikka RELEGATED on tanaan
        # tuple: ansa ei saa jaada odottamaan seuraavaa kohorttilisaysta.
        for joukkueet in _kohortteina(per_liiga.get(liiga, ())).values():
            out.update(joukkueet)
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
        # 🔴 `_kohortteina` on PAKOLLINEN, ei kosmetiikkaa. Liigan arvo voi olla
        # dict {kohortti: joukkueet} (Championship 15.8 alkaen), ja dictin yli
        # iterointi antaa KOHORTTIEN NIMET joukkueiden sijaan. Mitattu
        # tuotannosta: nousijapoiminta palautti {'promoted_from_below',
        # 'relegated_from_above'} ja /api/teams naytti Championshipille 18
        # joukkuetta 24:n sijaan.
        #
        # Vika oli NAKYMATON koska kutsuja vartioi listauksen `dc.attack`
        # -jasenyydella: kohorttinimet eivat ole mallissa, joten ne suodattuivat
        # pois eivatka paatyneet valitsimeen. Vartio muutti rikkinaisen listan
        # hiljaa vajaaksi listaksi — hyvaa suunnittelua, ja juuri siksi tama oli
        # loydettava mittaamalla tuotannosta eika lukemalla koodia.
        #
        # Sama normalisointi molemmissa funktioissa vaikka RELEGATED on tanaan
        # tuple: ansa ei saa jaada odottamaan seuraavaa kohorttilisaysta.
        for joukkueet in _kohortteina(per_liiga.get(liiga, ())).values():
            out.update(joukkueet)
    return frozenset(out)


# Viimeisin trio jonka PL-voima on mitattu (nousi 24/25).
REFERENCE_TRIO: tuple[str, ...] = ("Ipswich", "Leicester", "Southampton")

# ---------------------------------------------------------------------------
# Per-liiga-viiteryhmät (1.8 laajennus): edellisen kauden nousijat, joilla on
# TÄYSI 25/26-kausi treeni-ikkunassa → baseline mitataan AINA nykyisestä
# fitistä (source='measured'). Toisin kuin PL:ssä, frozen-fallbackia EI ole:
# PL:n jäädytetyt luvut ovat PL-skaalaa eikä niitä saa soveltaa muihin
# liigoihin — jos viiteryhmä puuttuisi fitistä, injektio ohittuu näkyvästi
# (needed jää tyhjäksi vasta resolvoinnissa, loki kertoo). Ryhmät laskettu
# FD-kausidiffistä 1.8 (25/26-joukot miinus 24/25-joukot):
#   FL1/BL1: vain 2 nimeä (nousu 2 suoraa + karsinta) — keskiarvo 2:sta
#   on silti mitattu luku, ei arvaus.
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# KAKSI KOHORTTIA, EI YHTÄ (15.8.2026, Villen GO)
#
# Ylimmällä sarjalla tulokkaat tulevat vain yhdestä suunnasta: alhaalta. Siksi
# yksi viiteryhmä riitti PL:lle ja muille big-5-liigoille.
#
# CHAMPIONSHIP ON ERI: sinne tullaan MOLEMMISTA suunnista. Kaudelle 26/27
# tulokkaita on kuusi, ja ne jakautuvat kahteen täysin eri voimaluokkaan:
#     League Onesta nousseet   Bolton, Cardiff, Lincoln
#     PL:stä pudonneet         Burnley, West Ham, Wolves
#
# Yhden baselinen antaminen kaikille kuudelle tekisi West Hamista yhtä heikon
# kuin Lincolnista. Se ei olisi konservatiivinen arvio vaan mitattavasti väärä,
# ja se näkyisi julkisissa ennusteissa heti ensimmäisestä kierroksesta.
#
# Siksi sekä PROMOTED_BY_SEASON että REFERENCE_BY_LEAGUE hyväksyvät nyt
# tuplen SIJASTA myös dictin {kohortti: joukkueet}. Vanha tuple-muoto toimii
# ennallaan (= yksi kohortti), joten big-5-liigojen käytös on bittitarkasti
# entinen.
#
# Championshipin viiteryhmät on MITATTU kausidiffistä eikä muistettu:
#     E1 25/26 miinus E1 24/25          -> uudet: Birmingham, Charlton,
#                                          Ipswich, Leicester, Southampton,
#                                          Wrexham
#     joista E0 24/25:ssä                -> PL:stä pudonneet: Ipswich,
#                                          Leicester, Southampton
#     loput                              -> League Onesta nousseet: Birmingham,
#                                          Charlton, Wrexham
# Molemmat kuusikot ovat nykyisessä fitissä, joten kumpikin baseline on
# `source: measured` eikä jäädytetty.
# ---------------------------------------------------------------------------
REFERENCE_BY_LEAGUE: dict[str, tuple[str, ...] | dict[str, tuple[str, ...]]] = {
    "ENG-Premier League": REFERENCE_TRIO,
    "ESP-La Liga-FD": ("Elche CF", "Levante UD", "Real Oviedo"),
    "ITA-Serie A-FD": ("AC Pisa 1909", "US Cremonese", "US Sassuolo Calcio"),
    "FRA-Ligue 1-FD": ("FC Lorient", "FC Metz", "Paris FC"),
    "GER-Bundesliga-FD": ("1. FC Köln", "Hamburger SV"),
    "ENG-Championship": {
        COHORT_UP: ("Birmingham", "Charlton", "Wrexham"),
        COHORT_DOWN: ("Ipswich", "Leicester", "Southampton"),
    },
}

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


def add_promoted_baseline(
    dc: DixonColesModel,
    needed: list[str],
    reference: tuple[str, ...] = REFERENCE_TRIO,
    allow_frozen: bool = True,
) -> dict:
    """Anna `needed`-joukkueille viimeisimmän nousijaryhmän toteutunut voima.

    Mutatoi `dc`:n paikan päällä. Palauttaa yhteenvedon telemetriaa/lokitusta
    varten. Jos viiteryhmä puuttuu fitistä eikä frozen-varakeinoa saa käyttää,
    tai `needed` on tyhjä, ei tee mitään — baselinea ei arvata.

    `reference`/`allow_frozen` oletuksineen = entinen PL-käytös bittitarkasti
    (FPL-builderit kutsuvat suoraan kahdella argumentilla). FROZEN_BASELINE on
    PL-skaalaa: muille liigoille allow_frozen=False, jolloin puuttuva
    viiteryhmä → näkyvä skip, ei väärän liigan lukuja.
    """
    trio = [t for t in reference if t in dc.attack]
    needed = [t for t in needed if t not in dc.attack]
    if not needed:
        return {"trio_used": trio, "applied_to": []}
    if not trio and not allow_frozen:
        return {"trio_used": [], "applied_to": [],
                "skipped": list(needed),
                "reason": "viiteryhmä ei fitissä eikä frozen sallittu"}

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


def _kohortteina(
    arvo: tuple[str, ...] | dict[str, tuple[str, ...]]
) -> dict[str, tuple[str, ...]]:
    """Normalisoi tuple TAI dict samaan {kohortti: joukkueet} -muotoon.

    Vanha tuple-muoto = yksi nimeton kohortti, jolloin big-5-liigojen polku on
    bittitarkasti entinen. Tyhja arvo -> tyhja dict, ei kohorttia.
    """
    if isinstance(arvo, dict):
        return arvo
    return {"": tuple(arvo)} if arvo else {}


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

    # 1.8: injektio per liiga, koska viiteryhmä on liigakohtainen — PL:n
    # baseline ei saa vuotaa esim. Bundesliigan nousijoille (eri skaala).
    # Yhden liigan pyynnöillä (kaikki nykyklientit) käytös = ennen, mutta
    # applied_to/trio_used aggregoituvat jos pyydetään useita liigoja.
    yhdiste: dict = {"applied_to": []}
    for liiga in liigat:
        # 15.8: liigalla voi olla YKSI kohortti (tuple, entinen muoto) tai
        # USEITA (dict). Championship on jalkimmainen: sinne tullaan seka
        # ylhaalta etta alhaalta, ja niilla on eri voimaluokka. Normalisoidaan
        # molemmat samaan muotoon, jolloin silmukka on yksi.
        ryhmat = _kohortteina(per_liiga.get(liiga, ()))
        viitteet = _kohortteina(REFERENCE_BY_LEAGUE.get(liiga, ()))
        for nimi, joukkueet in ryhmat.items():
            needed = [t for t in joukkueet if t not in dc.attack]
            if not needed:
                continue
            info = add_promoted_baseline(
                dc, needed,
                reference=viitteet.get(nimi, ()),
                allow_frozen=(liiga == "ENG-Premier League"),
            )
            if info.get("applied_to"):
                yhdiste["applied_to"] = yhdiste["applied_to"] + info["applied_to"]
                # Yksi kohortti + yksi liiga (normaalitapaus) -> kentat suoraan
                # lokiin. Useammalla kohortilla ne kirjataan lisaksi nimettyina,
                # jotta jalkikateen nakee KUMPI baseline mihinkin osui.
                for k in ("trio_used", "attack", "defence", "home_gamma",
                          "source", "provenance"):
                    if k in info:
                        yhdiste[k] = info[k]
                if len(ryhmat) > 1:
                    yhdiste.setdefault("cohorts", {})[nimi] = {
                        k: info[k] for k in
                        ("trio_used", "applied_to", "attack", "defence",
                         "home_gamma", "source") if k in info
                    }
            if info.get("skipped"):
                yhdiste.setdefault("skipped", []).extend(info["skipped"])
    return yhdiste
