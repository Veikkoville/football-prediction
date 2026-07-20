<script lang="ts">
	import { DISCLAIMER } from '$lib/config';
	import Hero from '$lib/components/Hero.svelte';
	import FreeView from '$lib/components/FreeView.svelte';
	import ProView from '$lib/components/ProView.svelte';

	// #101: ?tab=premium avaa Premium-välilehden suoraan (etusivun selailu-
	// CTA:t → arvo-esikatselu + hinnat heti, ei piilossa toisen tabin takana).
	// Sama myös ?checkout=success|cancelled -paluulle: success-banneri ja
	// purchase_completed-event elävät ProView'ssä — ilman tätä ostaja
	// laskeutuisi free-tabille eikä näkisi kuittausta.
	// SPA-moodi (ssr=false) → window on käytettävissä jo initissä.
	const initialParams = new URLSearchParams(window.location.search);
	const initialTab = initialParams.get('tab');
	let tab = $state<'free' | 'pro'>(
		initialTab === 'premium' || initialTab === 'pro' || initialParams.has('checkout')
			? 'pro'
			: 'free'
	);

	// #46: free-puolen lukittu teaser vie Pro-tabiin, jossa Paywall elää.
	function goPro() {
		tab = 'pro';
		requestAnimationFrame(() => {
			document.querySelector('main')?.scrollIntoView({ behavior: 'smooth' });
		});
	}
</script>

<div class="shell">
	<Hero onUpgrade={goPro} />

	<div class="tabs" role="tablist" aria-label="Views">
		<button
			role="tab"
			aria-selected={tab === 'free'}
			class:active={tab === 'free'}
			onclick={() => (tab = 'free')}
		>
			Clean sheets &amp; FDR (free)
		</button>
		<button
			role="tab"
			aria-selected={tab === 'pro'}
			class:active={tab === 'pro'}
			onclick={() => (tab = 'pro')}
		>
			Expected points (Premium)
		</button>
	</div>

	<main>
		{#if tab === 'free'}
			<FreeView onUpgrade={goPro} />
		{:else}
			<ProView />
		{/if}
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
	.tabs {
		display: flex;
		gap: var(--s-2);
		margin: var(--s-4) 0;
		border-bottom: 1px solid var(--border);
	}
	.tabs button {
		background: none;
		border: none;
		border-bottom: 3px solid transparent;
		border-radius: 0;
		color: var(--text-muted);
		font-weight: 700;
		padding: var(--s-2) var(--s-3);
		min-height: 44px;
	}
	.tabs button.active {
		color: var(--giq-magenta-deep);
		border-bottom-color: var(--giq-magenta-deep);
	}
	.tabs button:hover {
		color: var(--text);
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
