<script lang="ts">
	import { DISCLAIMER } from '$lib/config';
	import Hero from '$lib/components/Hero.svelte';
	import ToolsHome from '$lib/components/ToolsHome.svelte';

	// Web P1 (30.7): entitlement-ylätabit (Free tools / Premium) poistettu —
	// yksi 6 ryhmän näkymä kaikille, gate lohkon sisällä (ToolsHome).
	// ?tab=premium ja ?checkout käsitellään ToolsHomessa (upgrade-näkymä).
	// Heron Upgrade-badge signaloi ToolsHomelle laskurilla.
	let upgradeSignal = $state(0);
</script>

<div class="shell">
	<Hero onUpgrade={() => upgradeSignal++} />

	<main>
		<ToolsHome {upgradeSignal} />
	</main>

	<footer>
		<hr />
		<p class="muted">
			One account, premium on web, iOS and Android. · {DISCLAIMER} ·
			<a href="https://goaliq.app/privacy.html">Privacy</a> ·
			<a href="https://goaliq.app/faq.html">FAQ</a> · Built by an independent developer in
			Finland.
		</p>
	</footer>
</div>

<style>
	.shell {
		max-width: var(--shell);
		margin: 0 auto;
		padding: var(--s-4);
	}
	footer {
		margin-top: var(--s-12);
	}
	hr {
		border: none;
		border-top: 1px solid var(--border);
		margin-bottom: var(--s-4);
	}
</style>
