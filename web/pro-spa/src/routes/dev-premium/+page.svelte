<script lang="ts">
	// DEV-ONLY premium-esikatselu (ei auth-gatea) - renderöityy VAIN vite dev
	// -moodissa; tuotantobuildissa reitti näyttää ohjeen eikä dataa (ei
	// paywall-ohitusta, data on silti julkisesta API:sta).
	// Web P1 (30.7): ProTools poistui → esikatselu on ToolsHome forcePremiumilla.
	import ToolsHome from '$lib/components/ToolsHome.svelte';

	const isDev = import.meta.env.DEV;
</script>

<div class="shell">
	{#if !isDev}
		<p class="muted">Dev preview only. Use the app at <a href="/">/</a>.</p>
	{:else}
		<p class="banner success">DEV PREVIEW: premium-näkymät ilman auth-gatea</p>
		<ToolsHome forcePremium />
	{/if}
</div>

<style>
	.shell {
		max-width: var(--shell);
		margin: 0 auto;
		padding: var(--s-4);
	}
</style>
