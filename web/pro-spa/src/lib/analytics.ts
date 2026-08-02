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

type Queued = { event: string; props?: Record<string, unknown>; beacon?: boolean };
const queue: Queued[] = [];
let pendingIdentity: { userId: string; email?: string | null } | null = null;

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
			posthog.register({ platform: 'web', source_app: 'pro-web-spa' });
			ready = true;
			if (pendingIdentity) {
				const { userId, email } = pendingIdentity;
				pendingIdentity = null;
				posthog.identify(userId, email ? { email } : undefined);
			}
			for (const q of queue.splice(0)) {
				posthog.capture(q.event, q.props, q.beacon ? { transport: 'sendBeacon' } : undefined);
			}
		})
		.catch(() => {
			loading = false; // verkkovirhe: seuraava initAnalytics saa yrittaa uudelleen
		});
}

export function initAnalytics(): void {
	if (ready || loading || !POSTHOG_KEY) return;
	loading = true;
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
