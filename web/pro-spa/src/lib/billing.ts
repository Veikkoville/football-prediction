/** Stripe Checkout SPA-polku (QUEUE #14 ainoa backend-lisäys).
 *
 * Staattinen SPA EI voi pitää STRIPE_SECRET_KEY:tä → checkout-session luodaan
 * backendissä: POST /api/web/checkout (auth = Supabase-JWT bearer) → {url} →
 * redirect. Fulfillment = olemassa oleva webhook /api/webhook/stripe-web
 * (ei muutu). Hinnat: kausi 25 €/v (oletus) + kuukausi 3,99 €/kk.
 */
import { API_BASE } from './config';
import { accessToken } from './auth.svelte';
import { capture } from './analytics';

export const PLANS = {
	season: { label: 'Season pass: 25 €/year', price: 25.0, hint: 'Best value, under 2.10 €/month' },
	monthly: { label: 'Monthly: 3.99 €/mo', price: 3.99, hint: 'Flexible, try it for a month' }
} as const;

export type PlanKey = keyof typeof PLANS;

export async function startCheckout(plan: PlanKey): Promise<string | null> {
	// Web-funnel: osto-intentti ennen redirectiä (sama muoto kuin #12)
	capture('upgrade_tapped', { source: 'pro_web', plan, price: PLANS[plan].price });
	const token = await accessToken();
	if (!token) return 'Sign in first.';
	try {
		const r = await fetch(`${API_BASE}/api/web/checkout`, {
			method: 'POST',
			headers: {
				'Content-Type': 'application/json',
				Authorization: `Bearer ${token}`
			},
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
