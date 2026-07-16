<script lang="ts">
	import { onMount } from 'svelte';
	import { startCheckout, PLANS, type PlanKey } from '$lib/billing';
	import Provenance from '$lib/components/Provenance.svelte';

	// #101: suora ostopolku — goaliq.app-etusivun hinta-CTA:t laskeutuvat
	// tänne (?plan=monthly|annual|season) ja jatkavat HETI Stripe
	// Checkoutiin. Ei login-seinää: kirjautumaton menee guest-checkoutiin
	// (tili luodaan maksun jälkeen webhookissa), kirjautunut authed-polkuun.
	let plan = $state<PlanKey>('season');
	let error = $state<string | null>(null);
	let busy = $state(true);

	function resolvePlan(): PlanKey {
		const p = new URLSearchParams(window.location.search).get('plan') ?? '';
		return p === 'monthly' ? 'monthly' : 'season'; // annual/season/tuntematon → season
	}

	async function go(source: string) {
		busy = true;
		error = await startCheckout(plan, source);
		busy = false;
	}

	onMount(() => {
		plan = resolvePlan();
		void go('checkout_route');
	});
</script>

<div class="shell">
	<h2>GoalIQ Premium</h2>
	{#if busy}
		<p>Opening secure checkout ({PLANS[plan].label}) via Stripe…</p>
		<p class="muted">
			No account needed — pay first, and we'll email you a sign-in link for the web and the
			GoalIQ app.
		</p>
	{:else if error}
		<p class="banner error">{error}</p>
		<button class="primary" onclick={() => void go('checkout_route_retry')}>Try again</button>
	{/if}
	<Provenance />
	<p class="muted">
		<a href="/">Back to GoalIQ Premium on the web</a> · Cancel anytime. One subscription covers
		web, iOS and Android.
	</p>
</div>

<style>
	.shell {
		max-width: var(--shell);
		margin: 0 auto;
		padding: var(--s-8) var(--s-4);
		display: grid;
		gap: var(--s-4);
		justify-items: start;
	}
</style>
