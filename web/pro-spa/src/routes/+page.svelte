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

	<!-- SPL-nosto (7.8): footer-linkki ei riitä löydettävyyteen (sama oppi
	     kuin career-kortissa: haudattu linkki = ei käyttäjiä). Yksi hillitty
	     rivi heron alla — SPL-sisältö itse pysyy omalla reitillään. -->
	<p class="spl-note">
		New: <a href="/spl">Saudi Pro League fantasy tools</a>, completely free.
	</p>

	<main>
		<ToolsHome {upgradeSignal} />
	</main>

	<footer>
		<hr />
		<p class="muted">
			One account, premium on web, iOS and Android. · {DISCLAIMER} ·
			<!-- SPL = oma osio (etiikkakehys 7.8): löydettävissä muttei FPL-feedin
			     seassa — SPL:stä kiinnostumaton ei törmää siihen työkaluissa. -->
			<a href="/spl">Saudi Pro League tools (free)</a> ·
			<a href="https://goaliq.app/privacy.html">Privacy</a> ·
			<a href="https://goaliq.app/faq.html">FAQ</a> ·
			<!-- Kohde on Google Form eika hello@: poistaa riippuvuuden DMARC-portista
			     (linjautumaton tukivastaus suodattuisi hiljaa). Perustelu kokonaan
			     commitissa ae9545d6. -->
			<a href="https://forms.gle/wTfsB3Kvuukodtd26" rel="noopener">Contact</a> · Built by an
			independent developer in Finland.
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
	.spl-note {
		border: 1px solid var(--border);
		border-left: 3px solid var(--accent);
		padding: var(--s-2) var(--s-3);
		margin: var(--s-3) 0 0;
		font-size: 0.9em;
	}
	hr {
		border: none;
		border-top: 1px solid var(--border);
		margin-bottom: var(--s-4);
	}
</style>
