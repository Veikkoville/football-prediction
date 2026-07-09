<script lang="ts">
	// DEV-ONLY premium-komponenttien esikatselu (ei auth-gatea) - renderöityy
	// VAIN vite dev -moodissa; tuotantobuildissa reitti näyttää ohjeen eikä
	// dataa (ei paywall-ohitusta, data on silti julkisesta API:sta).
	import { fetchXp, type XpResponse } from '$lib/api';
	import ProTools from '$lib/components/ProTools.svelte';

	const isDev = import.meta.env.DEV;
	let xp = $state<XpResponse | null>(null);

	$effect(() => {
		if (isDev) fetchXp().then((d) => (xp = d));
	});
</script>

<div class="shell">
	{#if !isDev}
		<p class="muted">Dev preview only. Use the app at <a href="/">/</a>.</p>
	{:else if !xp}
		<p class="muted">Loading…</p>
	{:else}
		<p class="banner success">DEV PREVIEW: premium-näkymät ilman auth-gatea</p>
		<!-- #46/#48: sama segmenttidashboard kuin ProView'ssa (RateTeam +
		     TransferPlanner sisältävät oman entry-ID-syötteen devausta varten) -->
		<ProTools {xp} />
	{/if}
</div>

<style>
	.shell {
		max-width: var(--shell);
		margin: 0 auto;
		padding: var(--s-4);
	}
</style>
