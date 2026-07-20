<script lang="ts">
	import { auth, signOut } from '$lib/auth.svelte';
	import { capture } from '$lib/analytics';
	import icon from '$lib/assets/goaliq-appicon-192.png';

	// #149: tilaustaso-badge lukee SAMAN auth.sub-tilan jota ProView gateaa →
	// header ja feature-lukot eivät voi olla ristiriidassa. undefined =
	// entitlement ei vielä ratkennut → ei badgea (ei väläytetä väärää tasoa).
	let { onUpgrade }: { onUpgrade?: () => void } = $props();

	function upgrade() {
		capture('upgrade_tapped', { source: 'header_badge' });
		onUpgrade?.();
	}
</script>

<header class="hero">
	<div class="brand">
		<img src={icon} alt="" width="44" height="44" />
		<div>
			<div class="word">Goal<span>IQ</span> Premium</div>
			<div class="tag">
				Fantasy Premier League tools from the GoalIQ match model ·
				<a href="https://goaliq.app">goaliq.app</a>
			</div>
		</div>
	</div>
	{#if auth.user}
		<div class="session">
			<span class="muted">Signed in: {auth.user.email}</span>
			{#if auth.sub}
				<span class="plan premium">Premium</span>
			{:else if auth.sub === null}
				<button class="plan free" onclick={upgrade}>Free · Upgrade</button>
			{/if}
			<button class="ghost" onclick={() => void signOut()}>Sign out</button>
		</div>
	{/if}
</header>

<style>
	.hero {
		/* #53: tumma ink-bändi vaalealla sivulla = brändin header-kieli
		   (vrt. privacy.html). Token-overridet: lapset (.muted, ghost-nappi)
		   perivät bändin tummat roolivärit ilman komponenttimuutoksia. */
		--text: var(--giq-cream);
		--text-muted: #c9c3da;
		--border: rgba(255, 255, 255, 0.25);
		color: var(--text);
		background: linear-gradient(165deg, var(--giq-ink-2), var(--giq-ink));
		border: 1px solid rgba(255, 46, 126, 0.35);
		border-radius: 16px;
		padding: var(--s-4) var(--s-6);
		display: flex;
		flex-wrap: wrap;
		gap: var(--s-4);
		align-items: center;
		justify-content: space-between;
	}
	.brand {
		display: flex;
		align-items: center;
		gap: var(--s-3);
	}
	.brand img {
		border-radius: 11px;
		display: block;
	}
	.word {
		font-size: 26px;
		font-weight: 700;
		line-height: 1.1;
	}
	.word span {
		color: var(--giq-magenta);
	}
	.tag {
		color: var(--text-muted);
		font-size: var(--step--1);
		margin-top: 2px;
	}
	.tag a {
		/* kirkas magenta luettavana tummalla bändillä (deep jäisi heikoksi) */
		color: var(--giq-magenta);
	}
	.session {
		display: flex;
		align-items: center;
		gap: var(--s-3);
	}
	.plan {
		font-size: 12px;
		font-weight: 700;
		letter-spacing: 0.04em;
		text-transform: uppercase;
		line-height: 1.6;
		padding: 1px 10px;
		border-radius: 999px;
		white-space: nowrap;
	}
	.plan.premium {
		background: var(--giq-magenta);
		color: var(--giq-ink);
	}
	.plan.free {
		background: none;
		border: 1px solid var(--border);
		color: var(--text-muted);
		cursor: pointer;
		min-height: 0;
	}
	.plan.free:hover {
		color: var(--text);
		border-color: var(--giq-magenta);
	}
</style>
