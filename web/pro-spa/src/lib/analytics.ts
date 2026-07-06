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
		capture_pageview: false, // pro_page_viewed on funnelin oma eventti
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

export function identifyUser(userId: string, email?: string | null): void {
	if (!ready) return;
	posthog.identify(userId, email ? { email } : undefined);
}

export function resetAnalytics(): void {
	if (!ready) return;
	posthog.reset();
}
