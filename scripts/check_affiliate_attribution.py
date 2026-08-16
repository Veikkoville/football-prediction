"""Affiliate-attribuution tasmaytysvahti (AFF-ATTRIB, 11.8.2026).

MIKSI TAMA ON OLEMASSA
Ville lupasi kumppaneille 30 % provision "for as long as they stay subscribed".
Kupongit ovat `duration: once`, joten alennus irtoaa tilaukselta ensimmaisen
laskun jalkeen. Yhteys sailyy vain siina etta webhook leimasi promokoodin
tilauksen metadataan (`subscription.metadata.affiliate`) sina hetkena kun
`checkout.session.completed` laukesi.

Se leimaus voi jaada tekematta hiljaa: webhook-katkos, Stripe-virhe leimauksessa
(joka on tarkoituksella fail-soft, jottei fulfillment kaadu), tai ostopolku joka
ei osu webhookiin lainkaan. Silloin provisio jaa maksamatta, kukaan ei huomaa,
ja se paljastuu vasta kun kumppani kysyy miksi hanen maksunsa on liian pieni.

MITA TAMA MITTAA
Jokaiselle promokoodille: `times_redeemed` (Stripen oma lunastuslaskuri) vs.
niiden tilausten maara joilla on vastaava `metadata.affiliate`-leima.

  leimattuja == lunastuksia   -> OK
  leimattuja  <  lunastuksia  -> VUOTO. Joku lunastus ei leimautunut.
                                 Nama on paikattava kasin ensimmaiselta
                                 laskulta ennen seuraavaa payoutia.
  leimattuja  >  lunastuksia  -> MAHDOTON. Leimoja on enemman kuin lunastuksia,
                                 eli leimataan jotain jota ei pitaisi. Tama on
                                 pahempi kuin vuoto: se johtaisi LIIKAA
                                 maksettuun provisioon ja tarkoittaa etta
                                 leimauslogiikka on rikki.

EXIT-KOODIT (tarkoituksella eri asiat)
  0 = tasmaa
  1 = ero havaittu (vuoto tai mahdoton tila)
  2 = EI VOITU MITATA (avain puuttuu, Stripe-virhe). Tama EI ole PASS.
      Muisti `accuracy-log-403-gh-runners`: vahti joka huutaa varoitustasolla
      jaa huomaamatta. Mittaamattomuus nostaa ajon punaiseksi.

HUOM STRIPEN SEARCH-API:STA
`Subscription.search` on eventually consistent (~1 min viive). Juuri tehty
ostos voi puuttua tuloksista. Siksi tama ajetaan aikataululla eika heti
oston jalkeen, ja yhden yksikon ero raportoidaan mutta se ei yksin ole
todiste vuodosta jos ostoja on tapahtunut viime minuutteina.
"""
from __future__ import annotations

import os
import sys

import stripe


def _fetch_promotion_codes() -> list[dict]:
    """Kaikki promokoodit (myos deaktivoidut).

    Deaktivoidut otetaan mukaan tarkoituksella: `EARLY30`:n vanha koodi
    deaktivoitiin 11.8 ja korvattiin uudella samalla merkkijonolla. Jos vanha
    ehti kerata lunastuksia, ne kuuluvat silti tasmaytykseen.
    """
    out: list[dict] = []
    for pc in stripe.PromotionCode.list(limit=100).auto_paging_iter():
        out.append(pc)
    return out


def _count_stamped(code: str) -> tuple[int, int, int]:
    """Leimatut tilaukset lahteen mukaan: (promo, ref, tuntematon).

    🔴 LAHDE-EROTTELU ON TAMAN VAHDIN EHTO TOIMIA (16.8.2026).

    Vahti vertaa leimoja Stripen `times_redeemed`-laskuriin. Se oli oikein
    niin kauan kuin leima saattoi syntya VAIN kupongin kaytosta: yksi
    lunastus, yksi leima.

    16.8 rakennettu ref-polku rikkoo tuon suhteen. Luojan katsoja tulee
    linkista, luo ilmaisen tilin GW1-GW3-ikkunan aikana ja maksaa 12.9.
    jalkeen TAYTTA HINTAA ilman koodia. Leima syntyy, lunastusta ei tapahdu.
    Ilman erottelua ensimmainen sellainen maksu tuottaisi `stamped >
    redeemed` eli tilan jota tama skripti kutsuu MAHDOTTOMAKSI - punainen
    hälytys tilanteessa jossa kaikki toimi tasan oikein.

    Vaara halytys on pahempi kuin puuttuva: se opettaa lakkaamaan lukemasta
    vahtia, ja sitten oikea vuoto piiloutuu sen taakse. Juuri ennen GW19:n
    ensimmaista payoutia se olisi kallein mahdollinen hetki.

    `tuntematon` = ennen 16.8 kirjoitetut leimat, joissa ei ole
    `affiliate_source`-kenttaa. Niita EI voi luokitella jalkikateen, koska
    kupongit ovat `duration: once` ja alennus on jo irronnut. Ne lasketaan
    promo-puolelle, koska ref-polkua ei ollut olemassa kun ne syntyivat.
    """
    promo = ref = unknown = 0
    query = f"metadata['affiliate']:'{code}'"
    for sub in stripe.Subscription.search(query=query, limit=100).auto_paging_iter():
        src = ((sub.get("metadata") or {}).get("affiliate_source") or "").strip()
        if src == "ref":
            ref += 1
        elif src == "promo":
            promo += 1
        else:
            unknown += 1
    return promo, ref, unknown


def main() -> int:
    key = (os.getenv("STRIPE_SECRET_KEY") or "").strip()
    if not key:
        print("::error::STRIPE_SECRET_KEY puuttuu — attribuutiota EI voitu mitata.")
        return 2
    stripe.api_key = key

    try:
        codes = _fetch_promotion_codes()
    except Exception as e:
        print(f"::error::Promokoodien haku epäonnistui: {type(e).__name__}: {e}")
        return 2

    if not codes:
        print("::error::Yhtään promokoodia ei löytynyt — odottamaton tila, "
              "ei mitattavissa.")
        return 2

    problems: list[str] = []
    print(f"{'koodi':14} {'lunastuksia':>12} {'leimattuja':>11}  tila")
    for pc in sorted(codes, key=lambda c: c["code"]):
        code = pc["code"]
        redeemed = int(pc.get("times_redeemed") or 0)
        try:
            promo, ref, unknown = _count_stamped(code)
        except Exception as e:
            print(f"{code:14} {redeemed:>12} {'?':>11}  EI MITATTAVISSA "
                  f"({type(e).__name__}: {e})")
            problems.append(f"{code}: leimattujen haku epäonnistui")
            continue

        # Vain kuponkilahteiset leimat ovat vertailukelpoisia lunastuslukuun.
        # Ref-leimat raportoidaan, ei verrata: niille ei ole lunastusta.
        comparable = promo + unknown
        if comparable == redeemed:
            tila = "OK"
        elif comparable < redeemed:
            tila = f"VUOTO: {redeemed - comparable} lunastusta ilman leimaa"
            problems.append(f"{code}: {tila}")
        else:
            tila = f"MAHDOTON: {comparable - redeemed} ylimääräistä koodileimaa"
            problems.append(f"{code}: {tila}")
        if ref:
            tila += f" · {ref} linkkiattribuutiota (ei lunastusta, ei vertailua)"
        print(f"{code:14} {redeemed:>12} {comparable:>11}  {tila}")

    if problems:
        print()
        for p in problems:
            print(f"::error::{p}")
        print("::error::Affiliate-attribuutio ei täsmää. Paikkaa puuttuvat "
              "leimat ensimmäiseltä laskulta ENNEN seuraavaa payoutia.")
        return 1

    print("\nKaikki koodit täsmäävät.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
