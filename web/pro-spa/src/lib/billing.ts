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
import { capture } from './analytics';

export const PLANS = {
	season: { label: 'Season pass: 25 €/year', price: 25.0, hint: 'Best value, under 2.10 €/month' },
	monthly: { label: 'Monthly: 3.99 €/mo', price: 3.99, hint: 'Flexible, try it for a month' }
} as const;

export type PlanKey = keyof typeof PLANS;

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
			body: JSON.stringify({ plan, origin: window.location.origin })
		});
		if (!r.ok) {
			const detail = (await r.json().catch(() => null))?.detail;
			return `Checkout failed (${r.status})${detail ? `: ${detail}` : ''}`;
		}
		const { url } = await r.json();
		if (!url) return 'Checkout failed: no redirect URL.';
		window.location.href = url;
		return null;
	} catch (e) {
		return `Checkout failed: ${e instanceof Error ? e.message : e}`;
	}
}
