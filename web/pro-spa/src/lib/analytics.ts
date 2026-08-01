/** PostHog web-funnel (QUEUE #14) — IDENTTISET eventtinimet #12:n
 * (Streamlit server-side) ja mobiilin kanssa funnel-jatkuvuudelle:
 *   pro_page_viewed / signup_completed / paywall_shown /
 *   upgrade_tapped {plan, price} / purchase_completed {plan}
 *
 * distinct_id = Supabase-uid kirjautuneena (identify tekee anon->uid-aliaksen),
 * platform='web' super-propina. EI PII:tä event-propeissa (email vain
 * person-propina, kuten #12).
 */
import posthog from 'posthog-js';
import { POSTHOG_KEY, POSTHOG_HOST } from './config';

let ready = false;
const onceKeys = new Set<string>();

export function initAnalytics(): void {
	if (ready || !POSTHOG_KEY) return;
	posthog.init(POSTHOG_KEY, {
		api_host: POSTHOG_HOST,
		// $pageview tarvitaan PostHogin Web Analyticsiin: ilman sita
		// pro.goaliq.app nakyi dashboardilla nollana vaikka liikennetta oli
		// (havaittu 25.7 kampanjamittausta valmistellessa). pro_page_viewed
		// jaa funnelin omaksi eventiksi.
		capture_pageview: true,
		autocapture: false,
		persistence: 'localStorage+cookie'
	});
	posthog.register({ platform: 'web', source_app: 'pro-web-spa' });
	ready = true;
}

export function capture(
	event: string,
	props?: Record<string, unknown>,
	onceKey?: string
): void {
	if (!ready) return;
	if (onceKey) {
		if (onceKeys.has(onceKey)) return;
		onceKeys.add(onceKey);
	}
	posthog.capture(event, props);
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
	if (!ready) return;
	posthog.capture(event, props, { transport: 'sendBeacon' });
}

export function identifyUser(userId: string, email?: string | null): void {
	if (!ready) return;
	posthog.identify(userId, email ? { email } : undefined);
}

export function resetAnalytics(): void {
	if (!ready) return;
	posthog.reset();
}
