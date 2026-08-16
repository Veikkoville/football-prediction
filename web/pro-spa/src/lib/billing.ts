/** Stripe Checkout SPA-polku (QUEUE #14 + #101 guest checkout).
 *
 * Staattinen SPA EI voi pitää STRIPE_SECRET_KEY:tä → checkout-session luodaan
 * backendissä. Kaksi polkua:
 *   - kirjautunut: POST /api/web/checkout (Supabase-JWT bearer) →
 *     client_reference_id linkittää oston suoraan tiliin
 *   - kirjautumaton (#101): POST /api/web/checkout/guest — Stripe kerää
 *     emailin, tili provisioidaan maksun JÄLKEEN webhookissa + magic link
 * Fulfillment = webhook /api/webhook/stripe-web molemmissa.
 * Hinnat: kausi 25 €/v (oletus) + kuukausi 3,99 €/kk.
 */
import { API_BASE } from './config';
import { accessToken } from './auth.svelte';
import { capture, captureBeforeUnload } from './analytics';

/** 11.8: alennettu hinta hintapaikkaan ja koodi NAPIN TEKSTIIN. Ennen tata
 *  paywall sanoi "25 €/year" ja koodi mainittiin hintissa, eli kayttaja klikkasi
 *  itsensa Stripeen tietamatta etta kentta pitaa tayttaa.
 *  Kuponki on `once`, joten 17.50 koskee VAIN ensimmaista vuotta ja tilaus
 *  uusiutuu 25 eurolla. Uusiutumishinta on sanottava joka pinnalla.
 *  Takaraja sidotaan GW1-deadlineen (pe 21.8. 17:30 UTC, luettu FPL:n
 *  bootstrap-staticista) eika Stripen expiryyn (20:59 UTC): deadline on
 *  aikaisempi, yleison oma kello, ja tosi joka aikavyohykkeella.
 *  `price` on ja pysyy LISTAhinta: se menee analytiikkaan (upgrade_tapped,
 *  checkout_opened) ja sen vaihtaminen katkaisisi vertailun vanhaan dataan. */
export const PLANS = {
	season: { label: 'Season pass: 25 € a year', price: 25.0, hint: 'One subscription covers web, iOS and Android. Cancel anytime.' },
	monthly: { label: 'Monthly: 3.99 €/mo', price: 3.99, hint: 'Flexible, try it for a month' }
} as const;

export type PlanKey = keyof typeof PLANS;

/** 31.7 (Villen GO): Stripe Adaptive Pricing on päällä → checkout näyttää ja
 * veloittaa kävijän valuutassa. Nämä ovat NÄYTÖN likiarvoja UK/US-kävijöille
 * ("about" pitää ne rehellisinä, checkout näyttää aina tarkan summan).
 * Kurssit päivitetään käsin harvakseltaan — älä lisää FX-API-riippuvuutta. */
const APPROX: Record<'GBP' | 'USD', Record<PlanKey, string>> = {
	GBP: { season: 'about £21/year', monthly: 'about £3.40/mo' },
	USD: { season: 'about $27/year', monthly: 'about $4.40/mo' }
};

function localCurrency(): 'GBP' | 'USD' | null {
	if (typeof navigator === 'undefined') return null;
	let region = '';
	try {
		region = new Intl.Locale(navigator.language).maximize().region ?? '';
	} catch {
		region = '';
	}
	if (region === 'GB') return 'GBP';
	if (region === 'US') return 'USD';
	return null;
}

/** Paikallinen likiarvo plan-riville, tai null (= pelkkä EUR riittää). */
export function planApprox(plan: PlanKey): string | null {
	const c = localCurrency();
	return c ? APPROX[c][plan] : null;
}

/** Vie Stripe Checkoutiin. Kirjautunut → authed endpoint (osto linkittyy
 * tiliin heti); kirjautumaton → guest endpoint (tili syntyy maksun jälkeen).
 * Palauttaa virheviestin tai null (= redirect käynnissä). */
export async function startCheckout(plan: PlanKey, source = 'pro_web'): Promise<string | null> {
	// Web-funnel: osto-intentti ennen redirectiä (sama muoto kuin #12)
	capture('upgrade_tapped', { source, plan, price: PLANS[plan].price });
	const token = await accessToken();
	const endpoint = token ? '/api/web/checkout' : '/api/web/checkout/guest';
	const headers: Record<string, string> = { 'Content-Type': 'application/json' };
	if (token) headers.Authorization = `Bearer ${token}`;
	try {
		const r = await fetch(`${API_BASE}${endpoint}`, {
			method: 'POST',
			headers,
			body: JSON.stringify({
				plan,
				origin: window.location.origin,
				...(storedRef() ? { ref: storedRef() } : {})
			})
		});
		if (!r.ok) {
			const detail = (await r.json().catch(() => null))?.detail;
			return `Checkout failed (${r.status})${detail ? `: ${detail}` : ''}`;
		}
		const { url } = await r.json();
		if (!url) return 'Checkout failed: no redirect URL.';
		// 1.8.2026: upgrade_tapped lahtee ENNEN tata kutsua, eli se mittaa
		// aikomusta — myos silloin kun sessio ei synny ja kayttaja ei paady
		// Stripeen koskaan. Tama lahtee vasta kun Stripe on palauttanut URLin,
		// eli se on ensimmainen tapahtuma joka oikeasti vastaa kysymykseen
		// "moniko avasi checkoutin". Lahetetaan ennen redirectia; PostHog
		// kayttaa sendBeaconia, joten se selviaa sivun vaihdosta.
		captureBeforeUnload('checkout_opened', { source, plan, price: PLANS[plan].price });
		window.location.href = url;
		return null;
	} catch (e) {
		return `Checkout failed: ${e instanceof Error ? e.message : e}`;
	}
}

// ---------------------------------------------------------------------------
// Luojan ref (16.8.2026)
//
// Affiliate-attribuutio luki aiemmin vain KAYTETYN promokoodin, eli se toimi
// vain jos asiakas maksoi alennuksella. GW1-GW3 ilmaisikkuna rikkoi sen:
// luojan katsoja tulee ikkunan aikana, luo ilmaisen tilin, kayttaa tuotetta
// nelja viikkoa ja maksaa 12.9. jalkeen TAYTTA HINTAA ilman koodia. Luoja jai
// silloin ilman provisiota vaikka toi asiakkaan, ja provisio on luvattu
// sanoilla "for as long as they keep the subscription".
//
// Ref sailotaan selaimeen, koska se on ainoa paikka joka kestaa nelja viikkoa
// rekisteroinnin ja maksun valissa ILMAN uutta kantasaraketta (ja siten ilman
// tuotantomigraatiota). Rajoite sanottava aaneen: se ei kesta laitteen
// vaihtoa eika selaimen tyhjennysta.
const REF_KEY = 'giq:ref';
const REF_RE = /^[A-Z0-9_-]{2,32}$/;

/** Normalisoi ja validoi. Sama saanto kuin backendin `_clean_affiliate_ref`. */
export function cleanRef(value: string | null | undefined): string | null {
	if (typeof value !== 'string') return null;
	const v = value.trim().toUpperCase();
	return REF_RE.test(v) ? v : null;
}

/** Poimii `?ref=` URLista ja sailoo sen. Kutsutaan bootissa. */
export function captureRef(search = ''): string | null {
	try {
		const found = cleanRef(new URLSearchParams(search).get('ref'));
		// EI ylikirjoiteta olemassa olevaa: ensimmainen luoja joka toi
		// kayttajan saa attribuution, eika myohempi linkki vie sita.
		if (found && !localStorage.getItem(REF_KEY)) localStorage.setItem(REF_KEY, found);
		return storedRef();
	} catch {
		return null;
	}
}

export function storedRef(): string | null {
	try {
		return cleanRef(localStorage.getItem(REF_KEY));
	} catch {
		return null;
	}
}
