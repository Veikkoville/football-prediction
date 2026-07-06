<script lang="ts">
	import { onMount } from 'svelte';
	import { auth, refreshSubscription } from '$lib/auth.svelte';
	import { fetchXp, type XpResponse } from '$lib/api';
	import { capture } from '$lib/analytics';
	import LoginBox from './LoginBox.svelte';
	import Paywall from './Paywall.svelte';
	import CaptainRanker from './CaptainRanker.svelte';
	import XpTable from './XpTable.svelte';

	let xp = $state<XpResponse | null>(null);
	let xpError = $state<string | null>(null);
	let checkoutSuccess = $state(false);

	onMount(() => {
		// Checkout-paluu: ?checkout=success&session_id=... Fulfillment tekee
		// webhook /api/webhook/stripe-web — täällä vain kuitataan + kysytään
		// tilaustila uudelleen (pienellä uusinnalla webhook-viivettä vastaan).
		const params = new URLSearchParams(window.location.search);
		if (params.get('checkout') === 'success') {
			checkoutSuccess = true;
			const sid = params.get('session_id') ?? 'unknown';
			capture('purchase_completed', { source: 'web' }, `purchase_${sid}`);
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
	<p class="banner success">
		Premium active, welcome aboard! Pro is now active on the web AND in the GoalIQ app
		(iOS and Android). Just sign in with the same account on your phone.
	</p>
{/if}

{#if !auth.sessionResolved}
	<p class="muted">Checking session…</p>
{:else if !auth.user}
	<LoginBox />
{:else if auth.subLoading && auth.sub === undefined}
	<p class="muted">Checking subscription…</p>
{:else if auth.sub}
	{#if auth.sub.plan === 'app'}
		<p class="banner success">Your GoalIQ app subscription is active here too. Welcome.</p>
	{:else}
		<p class="muted">GoalIQ Pro active ({auth.sub.plan}) · thank you for the support!</p>
	{/if}
	{#if xpError}
		<p class="banner error">Could not load xP projections right now. Please try again shortly.</p>
	{:else if !xp}
		<p class="muted">Loading expected points…</p>
	{:else if !xp.meta?.available}
		<p class="banner success">xP projections go live before Gameweek 1.</p>
	{:else}
		<CaptainRanker data={xp} />
		<XpTable data={xp} />
	{/if}
{:else}
	<Paywall />
{/if}
