/** WEB-TO-APP-CTA (14.8): puhelimella ostopolku ohjataan sovellukseen.
 *
 * MIKSI, MITATTUNA: 14.8 web-checkoutista avattiin 8 sessiota ja niistä
 * konvertoi 0. Viidessä kuudesta `email` oli tyhjä, eli käyttäjä poistui
 * ENNEN kuin kirjoitti sähköpostinsa — ja `payment_intents` oli 0/24 h, eli
 * kukaan ei edes yrittänyt veloitusta. Mobiilipolulla sama hinta meni läpi
 * 37 sekunnissa. Ero ei ole tuote eikä hinta vaan maksutapahtuma: appissa se
 * on tallennettu Google/Apple-tili, webissä korttilomake jota kukaan ei täytä.
 *
 * PROVISIO ON LASKETTU, EI ARVATTU: 25 EUR kausi tuottaa Stripen jälkeen
 * 24,38 EUR ja Applen 30 %:n jälkeen 17,50 EUR (Small Business Programissa
 * 21,25 EUR). Apple ottaa siis 28 %, mutta **72 % jostakin voittaa 100 %
 * nollasta**. Kynnys jolla web olisi parempi: 0,88 EUR per checkout-avaus.
 * Nyt se tuottaa 0,00.
 *
 * ⚠️ OTOS ON YKSI KAUPPA. Tämä ei ole mitattu konversioprosentti vaan yksi
 * tapahtuma, joten muutos on rakennettu **mitattavaksi ja peruttavaksi**:
 * molemmat polut jäävät näkyviin, vain järjestys vaihtuu, ja kumpikin
 * napautus kirjaa oman eventtinsä. Jos web voittaa mittauksessa, järjestys
 * käännetään takaisin yhdellä rivillä.
 *
 * Puhdas moduuli ilman Svelte- tai selainriippuvuuksia, jotta se on
 * testattavissa ilman DOMia.
 */

export type AppStore = 'ios' | 'android';

/** Store-linkit. Samat kuin `/spl`-sivulla jo käytössä olevat. */
export const STORE_URL: Record<AppStore, string> = {
  ios: 'https://apps.apple.com/app/id6780047163',
  android: 'https://play.google.com/store/apps/details?id=com.veikkoville.goaliq',
};

/**
 * Tunnistaa puhelimen ja kertoo kumpi kauppa.
 *
 * TABLETIT JÄTETÄÄN WEBIIN tietoisesti: iPadilla korttilomake ei ole samalla
 * tavalla kitkainen kuin puhelimessa, eikä tablettikäyttäjä välttämättä
 * halua appia. Sääntö on siis kapea eikä "ei-työpöytä".
 *
 * Palauttaa `null` kun ostopolkua EI pidä vaihtaa (työpöytä, tabletti,
 * tuntematon) — kutsuja saa silloin nykyisen käytöksen muuttumattomana.
 */
export function preferredStore(
  userAgent: string | null | undefined
): AppStore | null {
  const ua = (userAgent || '').toLowerCase();
  if (!ua) return null;

  // iPadOS 13+ valehtelee olevansa Macintosh, joten iPad tunnistetaan sekä
  // nimellä että sillä Mac-osumalla jolla on kosketustuki. Emme näe
  // kosketustukea täällä (puhdas funktio), joten riittää nimipohjainen
  // poissulku: väärä positiivinen veisi iPad-käyttäjän turhaan kauppaan.
  if (ua.includes('ipad') || ua.includes('tablet')) return null;

  if (ua.includes('iphone') || ua.includes('ipod')) return 'ios';
  // Androidilla "mobile" erottaa puhelimen tabletista: Android-tabletin UA
  // sisältää "android" muttei "mobile".
  if (ua.includes('android') && ua.includes('mobile')) return 'android';
  return null;
}

/** Napin teksti. Erillään komponentista, jotta copy-portti näkee sen. */
export function appCtaLabel(store: AppStore): string {
  return store === 'ios' ? 'Get it on the App Store' : 'Get it on Google Play';
}
