<script lang="ts">
	import { onMount } from 'svelte';
	import { auth, refreshSubscription } from '$lib/auth.svelte';
	import { fetchXp, type XpResponse } from '$lib/api';
	import { capture } from '$lib/analytics';
	import LoginBox from './LoginBox.svelte';
	import Paywall from './Paywall.svelte';
	import PremiumPreview from './PremiumPreview.svelte';
	import ProTools from './ProTools.svelte';
	import SetPassword from './SetPassword.svelte';

	let xp = $state<XpResponse | null>(null);
	let xpError = $state<string | null>(null);
	let checkoutSuccess = $state(false);
	// #101: guest-checkout-paluu — ostaja EI ole kirjautunut, tili + magic
	// link syntyvät webhookissa → oma banneri (ei "Checking subscription").
	let guestCheckout = $state(false);

	onMount(() => {
		// Checkout-paluu: ?checkout=success&session_id=... Fulfillment tekee
		// webhook /api/webhook/stripe-web - täällä vain kuitataan + kysytään
		// tilaustila uudelleen (pienellä uusinnalla webhook-viivettä vastaan).
		const params = new URLSearchParams(window.location.search);
		if (params.get('checkout') === 'success') {
			checkoutSuccess = true;
			guestCheckout = params.get('guest') === '1';
			const sid = params.get('session_id') ?? 'unknown';
			capture('purchase_completed', { source: 'web', guest: guestCheckout }, `purchase_${sid}`);
			history.replaceState(null, '', window.location.pathname);
			let tries = 0;
			const poll = () => {
				void refreshSubscription().then(() => {
					if (!auth.sub && ++tries < 5) setTimeout(poll, 3000);
				});
			};
			poll();
		}
	});

	$effect(() => {
		if (auth.user && auth.sub && !xp && !xpError) {
			fetchXp().then(
				(d) => (xp = d),
				(e) => (xpError = String(e))
			);
		}
	});
</script>

{#if checkoutSuccess}
	{#if guestCheckout && !auth.user}
		<p class="banner success">
			Payment received — Premium is yours! We just emailed you a sign-in link (check spam
			too). Click it to open Premium here on the web; once signed in, you can set a password
			to use the same account in the GoalIQ app on iOS and Android.
		</p>
	{:else}
		<p class="banner success">
			Premium active, welcome aboard! Premium is now active on the web AND in the GoalIQ app
			(iOS and Android). Just sign in with the same account on your phone.
		</p>
	{/if}
{/if}

{#if !auth.sessionResolved}
	<p class="muted">Checking session…</p>
{:else if !auth.user}
	<!-- #95: arvo-esikatselu ENNEN login-lomaketta (design-audit vk3 P1) —
	     bulletit + live-trust-rivi + lukittu xP-teaser; paljas kirjautumis-
	     seinä ei myynyt mitään juuri konversiohetkellä. -->
	<PremiumPreview />
	<LoginBox />
{:else if auth.subLoading && auth.sub === undefined}
	<p class="muted">Checking subscription…</p>
{:else if auth.sub}
	{#if auth.sub.plan === 'app'}
		<p class="banner success">Your GoalIQ app subscription is active here too. Welcome.</p>
	{:else}
		<p class="muted">GoalIQ Premium active ({auth.sub.plan}) · thank you for the support!</p>
		<!-- #101: guest-tili syntyy ilman salasanaa → tarjoa asetus appia varten -->
		<SetPassword />
	{/if}
	{#if xpError}
		<p class="banner error">Could not load xP projections right now. Please try again shortly.</p>
	{:else if !xp}
		<p class="muted">Loading expected points…</p>
	{:else if !xp.meta?.available}
		<p class="banner success">xP projections go live before Gameweek 1.</p>
	{:else}
		<!-- #46/#48: premium-FPL-työkalut segmenttidashboardina (ProTools).
		     Renderöityvät VAIN tässä haarassa (auth.user + auth.sub + xp
		     saatavilla) → ei premium-vuotoa. -->
		<ProTools {xp} />
	{/if}
{:else}
	<Paywall />
{/if}
