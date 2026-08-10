/** PostHog web-funnel (QUEUE #14) — IDENTTISET eventtinimet #12:n
 * (Streamlit server-side) ja mobiilin kanssa funnel-jatkuvuudelle:
 *   pro_page_viewed / signup_completed / paywall_shown /
 *   upgrade_tapped {plan, price} / purchase_completed {plan}
 *
 * distinct_id = Supabase-uid kirjautuneena (identify tekee anon->uid-aliaksen),
 * platform='web' super-propina. EI PII:tä event-propeissa (email vain
 * person-propina, kuten #12).
 */
import type PostHogJs from 'posthog-js';
import { POSTHOG_KEY, POSTHOG_HOST } from './config';

/* 2.8.2026 PERF: posthog-js EI ole enaa staattinen import.
 *
 * Mitattu: SPA lahettaa 736 kB JS:aa 14 tiedostossa, ja suurin yksittainen
 * pala (405 kB) on posthog-js + supabase-js. pro.goaliq.appin HTML on 5,5 kB
 * tyhja kuori, joten ruudulla ei nay MITAAN ennen kuin tuo nippu on ladattu,
 * jasennetty ja ajettu. Landing (goaliq.app) on 57 kB valmista HTML:aa ja
 * maalautuu heti — siita syntyi "ekalla kerralla lagaa" -tunne.
 *
 * Mikaan ruudulla ei riipu analytiikasta, joten se ladataan vasta kun selain
 * on jouten (requestIdleCallback, 3 s katto).
 *
 * Tapahtumat JONOTETAAN, ei pudoteta. pro_page_viewed laukeaa layoutin
 * onMountissa eli aina ennen kuin kirjasto on valmis; sen pudottaminen
 * nollaisi koko web-funnelin mittauksen — sen saman jonka juuri korjasimme. */
let posthog: typeof PostHogJs | null = null;
let ready = false;
let loading = false;
const onceKeys = new Set<string>();

/* 10.8.2026: paywall-versiotagi WEBILLE (mobiilin #61-pariteetti).
 *
 * Mobiili rekisteroi `paywall_variant`-super-propin 12.7 alkaen
 * (goaliq-app/lib/analytics.ts). Web ei ole koskaan rekisteroinyt sita, joten
 * jokainen variantti-suodatettu funnel on pudottanut webin HILJAA pois — ja web
 * tuotti 1/3 mitatuista ostoista. Sama vika toiseen suuntaan: kysely
 * "paywall_variant is not set" = pre-#61-mobiili + KAIKKI web, aina.
 *
 * ARVO EI OLE 'v2_value_trust'. #61 kosketti vain mobiilia (817413f: App.tsx,
 * ProfileScreen, i18n, purchases) eika webissa ole v2:n trust-puoliskoa
 * lainkaan: mobiilin luottamusrivi hakee track recordin LIVENA /api/accuracy:sta
 * (ProfileScreen.tsx:651), webin Paywall.svelte ei hae mitaan, ja vuosi-ankkuri
 * on staattinen merkkijono planin labelissa (billing.ts:17) eika laskettu
 * save-%. Saman merkkijonon lisaaminen yhdistaisi kaksi eri tarjousta yhdeksi
 * kohortiksi — vale-signaali, joka nayttaisi portissa vihrealta.
 * Vrt. muisti `portti-voi-mitata-eri-koodipolkua`. */
export const PAYWALL_VARIANT = 'web_v1_dual_product';

type Queued = { event: string; props?: Record<string, unknown>; beacon?: boolean };
const queue: Queued[] = [];
let pendingIdentity: { userId: string; email?: string | null } | null = null;

/* 3.8.2026: POIKKEUSTEN VARHAISPUSKURI.
 *
 * Miksi tama on olemassa: yllaoleva `queue` kattaa vain NIMENOMAISET
 * capture()-kutsut. Poikkeukset eivat kulje sen lapi — posthog-js asentaa
 * omat virhekuuntelijansa vasta init():issa, joka ajetaan requestIdleCallbackin
 * takana (3 s katto). Ikkuna sivun avauksesta initiin oli siis taysin
 * kuuntelematta, ja juuri se on ikkuna jossa SPA:n chunkit ajetaan: kaikki
 * 31 aiemmin kirjattua $exceptionia (27.7.-1.8.) olivat kasittelemattomia
 * virheita immutable/chunks-paloissa. 2.8. lazy-load-shipin jalkeen
 * niita ei ole kirjautunut yhtaan — mikaan ei todista etta virheet loppuivat,
 * vain etta lakkasimme nakemasta ne.
 *
 * MITATTU ensin, ettei korjata vaaraa asiaa: $web_vitals per pro_page_viewed
 * on 3.8. 0,83 vs 1,20-1,88 aiemmin, mutta sivulatauksia oli 6 (ed. 19-59)
 * — eli VITALS-otoksen romahdus on liikennetta, ei sokeutta. posthog latautuu
 * ja lahettaa normaalisti. Vain poikkeusten ikkuna oli aito aukko.
 *
 * Kuuntelijat IRROTETAAN heti kun posthog on valmis: se asentaa omansa, ja
 * kaksi kuuntelijaa samalle virheelle tuottaisi tuplakirjaukset.
 *
 * EI resurssivirheita (addEventListener 'error' capture-vaiheessa): ne ovat
 * eri luokka (adblock, kuvat) ja tuottaisivat kohinaa jonka seassa aidot
 * koodivirheet katoaisivat. Dynaamisen importin epaonnistuminen nakyy
 * unhandledrejectionina, joka on mukana. */
const MAX_EARLY_ERRORS = 10;
type EarlyError = { error: unknown; kind: 'error' | 'unhandledrejection' };
const earlyErrors: EarlyError[] = [];
let earlyCaptureAttached = false;

function pushEarlyError(error: unknown, kind: EarlyError['kind']): void {
	// Katto suojaa virhemyrskylta: silmukassa heittava koodi tayttaisi muistin
	// ennen kuin posthog ehtii latautua.
	if (earlyErrors.length >= MAX_EARLY_ERRORS) return;
	earlyErrors.push({ error, kind });
}

function onEarlyError(ev: ErrorEvent): void {
	// ev.error puuttuu mm. cross-origin-skripteilta ("Script error."); silloin
	// rakennetaan Error viestista, jotta rivi ei katoa kokonaan.
	pushEarlyError(ev.error ?? new Error(ev.message || 'Unknown error'), 'error');
}

function onEarlyRejection(ev: PromiseRejectionEvent): void {
	pushEarlyError(ev.reason ?? new Error('Unhandled rejection'), 'unhandledrejection');
}

/* 4.8.2026: app.html:n kaynnistysvahti asentaa samat kuuntelijat ENNEN
 * yhtakaan moduulia. Tama nostaa sen keraaman puskurin tanne ja ottaa
 * vastuun — jarjestys on tahallinen: omat kuuntelijat kiinni ENSIN, vasta
 * sitten rungon irrotus, jotta valiin ei jaa kuuntelematonta ikkunaa. */
function adoptInlineBuffer(): void {
	const w = window as unknown as {
		__goaliqEarlyErrors?: EarlyError[];
		__goaliqEarlyDetach?: () => void;
	};
	const inline = w.__goaliqEarlyErrors;
	if (inline) {
		for (const e of inline.splice(0)) pushEarlyError(e.error, e.kind);
	}
	w.__goaliqEarlyDetach?.();
}

function attachEarlyErrorCapture(): void {
	if (earlyCaptureAttached || typeof window === 'undefined') return;
	earlyCaptureAttached = true;
	window.addEventListener('error', onEarlyError);
	window.addEventListener('unhandledrejection', onEarlyRejection);
	adoptInlineBuffer();
}

function detachEarlyErrorCapture(): void {
	if (!earlyCaptureAttached || typeof window === 'undefined') return;
	earlyCaptureAttached = false;
	window.removeEventListener('error', onEarlyError);
	window.removeEventListener('unhandledrejection', onEarlyRejection);
}

function flushEarlyErrors(): void {
	// Tyhjennys VASTA kun vastaanottaja on olemassa: toisin painvastoin
	// splice() tuhoaisi puskurin hiljaa jos posthog puuttuu.
	if (!posthog) return;
	const buffered = earlyErrors.splice(0);
	for (const e of buffered) {
		// $exception_source erottaa nama posthogin omista kirjauksista, jotta
		// datasta nakee onko korjaus oikeasti tuonut virheita takaisin.
		posthog.captureException(e.error, {
			$exception_source: 'early_buffer',
			early_capture_kind: e.kind
		});
	}
}

function boot(): void {
	void import('posthog-js')
		.then((mod) => {
			posthog = mod.default;
			posthog.init(POSTHOG_KEY, {
				api_host: POSTHOG_HOST,
				// $pageview tarvitaan PostHogin Web Analyticsiin: ilman sita
				// pro.goaliq.app nakyi dashboardilla nollana vaikka liikennetta oli
				// (havaittu 25.7 kampanjamittausta valmistellessa). pro_page_viewed
				// jaa funnelin omaksi eventiksi. Myohainen init ei menetä
				// $pageviewta: posthog capturoi sen initissa.
				capture_pageview: true,
				autocapture: false,
				persistence: 'localStorage+cookie'
			});
			posthog.register({
				platform: 'web',
				source_app: 'pro-web-spa',
				paywall_variant: PAYWALL_VARIANT
			});
			ready = true;
			if (pendingIdentity) {
				const { userId, email } = pendingIdentity;
				pendingIdentity = null;
				posthog.identify(userId, email ? { email } : undefined);
			}
			// Irrota omat kuuntelijat ENNEN purkua: posthog on nyt asentanut
			// omansa, eika purku saa palautua takaisin puskuriin.
			detachEarlyErrorCapture();
			flushEarlyErrors();
			for (const q of queue.splice(0)) {
				posthog.capture(q.event, q.props, q.beacon ? { transport: 'sendBeacon' } : undefined);
			}
		})
		.catch(() => {
			// Kuuntelijat jaavat TAHALLAAN paalle: jos kirjasto ei latautunut,
			// puskuri (katto 10) on ainoa paikka jossa virheet sailyvat siihen
			// asti kun seuraava initAnalytics yrittaa uudelleen.
			loading = false;
		});
}

export function initAnalytics(): void {
	if (ready || loading || !POSTHOG_KEY) return;
	loading = true;
	// HETI, ei idlen takana: tama on koko korjauksen pointti. Kuuntelijat ovat
	// muutama tavu ja ne asennetaan ennen kuin 203 kB:n kirjastoa aletaan hakea.
	attachEarlyErrorCapture();
	const ric = (window as { requestIdleCallback?: (cb: () => void, o?: object) => void })
		.requestIdleCallback;
	if (typeof ric === 'function') ric(boot, { timeout: 3000 });
	else setTimeout(boot, 0);
}

export function capture(
	event: string,
	props?: Record<string, unknown>,
	onceKey?: string
): void {
	if (!POSTHOG_KEY) return;
	// once-dedupe TASSA eika jonon purussa: muuten sama eventti voisi jonottua
	// kahdesti ennen kuin kirjasto ehtii latautua.
	if (onceKey) {
		if (onceKeys.has(onceKey)) return;
		onceKeys.add(onceKey);
	}
	if (ready && posthog) posthog.capture(event, props);
	else queue.push({ event, props });
}

/** Tapahtuma joka lahtee juuri ennen sivun vaihtoa (esim. Stripe-redirect).
 *
 * 1.8.2026: tavallinen capture kayttaa XHR/fetchia, joka voidaan perua kun
 * navigaatio alkaa — checkout_opened katoaisi juuri niilta kayttajilta jotka
 * oikeasti paatyivat maksamaan, eli mittari valehtelisi alaspain juuri siina
 * kohtaa mika halutaan tietaa. sendBeacon selviaa unloadista. */
export function captureBeforeUnload(
	event: string,
	props?: Record<string, unknown>
): void {
	if (!POSTHOG_KEY) return;
	if (ready && posthog) {
		posthog.capture(event, props, { transport: 'sendBeacon' });
		return;
	}
	// Reunatapaus jonka sanon aaneen: jos kirjasto ei ole viela latautunut kun
	// sivu jo poistuu, tama menetetaan. Kaytannossa checkout_opened tapahtuu
	// vasta kayttajan klikkauksen jalkeen, jolloin idle-lataus on ehtinyt.
	queue.push({ event, props, beacon: true });
}

export function identifyUser(userId: string, email?: string | null): void {
	if (!POSTHOG_KEY) return;
	if (ready && posthog) {
		posthog.identify(userId, email ? { email } : undefined);
		return;
	}
	pendingIdentity = { userId, email };
}

export function resetAnalytics(): void {
	pendingIdentity = null;
	if (ready && posthog) posthog.reset();
}
