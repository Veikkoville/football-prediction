"""
Promotoitujen joukkueiden priorityyppejen rakentaminen alasarjadatasta.

Idea:
  - Joukkue X siirtyi Championshipista PL:aan kaudeksi 2526
  - PL-mallissa X:lla on vain ~38 ottelua -> estimaatti epavakaa
  - Sovita erillinen DC Championship 2425 -datalle -> X:n attack/defence
  - Skaalaa promotion_factor:lla (esim. 0.5 = 50% Championship-tasosta)
  - Kaytetaan PL-mallin team_priors:ssa: vetaa estimaatit tata kohti

Promotoinnin vaikutuksen empiirinen tutkimus (FiveThirtyEight, footballranks):
  - Promotoitu joukkue on tyypillisesti 0.4-0.6 std-dev heikompi PL:n
    keskitasoa kuin omaa Championship-keskiarvoaan (joka on 0)
  - Eli skaalauskerroin n. 0.4-0.6 hyokkaykselle ja puolustukselle on jarkeva
"""

from __future__ import annotations

import pandas as pd

from src.data.loader import lataa_otteludata
from src.models.dixon_coles import DixonColesModel


# Englannin liigan promotioketju
PROMOTIO_KETJU = {
    "ENG-Premier League": "ENG-Championship",
    "ENG-Championship": "ENG-League One",
    "ENG-League One": "ENG-League Two",
}


def tunnista_promotoidut(
    nykyinen_data: pd.DataFrame,
    edellinen_data: pd.DataFrame,
    min_otteluja_kynnys: int = 60,
) -> list[str]:
    """
    Tunnista joukkueet jotka ovat nykyisessa datassa mutta eivat edellisessa
    (= promotoidut tahan liigaan).

    Lisaksi suodatetaan: vain joukkueet joilla on alle `min_otteluja_kynnys`
    ottelua nykyisessa datassa - jos joukkue on pelannut paljon, ei tarvita
    prioria.
    """
    nykyiset_joukkueet = set(nykyinen_data["home_team"]) | set(nykyinen_data["away_team"])
    edelliset_joukkueet = set(edellinen_data["home_team"]) | set(edellinen_data["away_team"])
    uudet = nykyiset_joukkueet - edelliset_joukkueet

    # Suodata vain ne joilla on vahan otteluja
    promotoidut = []
    for j in uudet:
        n = ((nykyinen_data["home_team"] == j) | (nykyinen_data["away_team"] == j)).sum()
        if n < min_otteluja_kynnys:
            promotoidut.append(j)
    return sorted(promotoidut)


def laske_alasarjapriorit(
    yliliiga: str,
    nykyiset_kaudet: list[str],
    edellinen_kausi: str,
    promotion_factor: float = 0.5,
    prior_weight: float = 2.0,
    decay_alasarja: float = 0.0035,
    bayes_shrinkage_alasarja: float = 2.0,
) -> dict[str, dict]:
    """
    Lataa edellisen kauden alasarja, sovittaa DC, palauttaa skaalatut priorit
    ylaliigaan promotoituneille joukkueille.

    Parametrit
    ----------
    yliliiga
        Esim. "ENG-Premier League"
    nykyiset_kaudet
        Mihin kausiin yliliigan datassa tarkastellaan promotoituneita
        (esim. ["2425", "2526"])
    edellinen_kausi
        Mista alasarjakaudesta priorit haetaan (esim. "2425" antaa kauden joka
        nostatti joukkueet 2526:lle)
    promotion_factor
        Skaalauskerroin: 1.0 = priorit suoraan alasarjaestimaatista (epatodennakoinen),
        0.5 = puolet alasarjaestimaatista (varovainen oletus, kompensoi tasoeroa),
        0.0 = pelkka 0-prior (= jatko vanhaan kayttaytymiseen)
    prior_weight
        Kuinka vahvasti taman priorin pitaa shrinkata estimaattia (suhteessa
        muihin joukkueisiin, joiden weight = 1.0). 2.0 = priorityys tuplattu.
    decay_alasarja
        Aikapainotus alasarjamallin sovituksessa
    bayes_shrinkage_alasarja
        Bayes-shrinkage alasarjamallissa

    Palauttaa
    ---------
    Dict joukkue -> {"attack": x, "defence": y, "weight": w}, valmis kaytettavaksi
    DixonColesModel.fit(team_priors=...) -parametrissa.
    """
    if yliliiga not in PROMOTIO_KETJU:
        # Liigalle ei tuettu alasarjamappausta -> tyhja prior
        return {}

    alasarja = PROMOTIO_KETJU[yliliiga]

    # Lataa yliliigan nykyiset kaudet ja edellinen kausi (vertailuun)
    yliliiga_data = lataa_otteludata([yliliiga], nykyiset_kaudet)
    if yliliiga_data.empty:
        return {}

    # Edellinen kausi yliliigassa = ne jotka olivat siella aiemmin
    yliliiga_edellinen = lataa_otteludata([yliliiga], [edellinen_kausi])

    # Promotoidut joukkueet = nykyisessa mutta ei edellisessa, ja vahan otteluja
    promotoidut = tunnista_promotoidut(yliliiga_data, yliliiga_edellinen)
    if not promotoidut:
        return {}

    # Lataa alasarjadata edelliselta kaudelta
    alasarja_data = lataa_otteludata([alasarja], [edellinen_kausi])
    if alasarja_data.empty:
        return {}

    # Sovita DC alasarjadataan
    dc_alasarja = DixonColesModel().fit(
        alasarja_data,
        decay=decay_alasarja, date_col="date",
        l2_attack_defence=bayes_shrinkage_alasarja,
    )

    # Hae priorit promotoiduille joukkueille
    priorit: dict[str, dict] = {}
    for j in promotoidut:
        if j in dc_alasarja.attack:
            priorit[j] = {
                "attack": float(dc_alasarja.attack[j]) * promotion_factor,
                "defence": float(dc_alasarja.defence[j]) * promotion_factor,
                "weight": float(prior_weight),
            }
    return priorit
