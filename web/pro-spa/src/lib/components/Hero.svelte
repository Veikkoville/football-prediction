<script lang="ts">
	import { auth, sendPasswordReset, signOut } from '$lib/auth.svelte';
	import { capture } from '$lib/analytics';
	import icon from '$lib/assets/goaliq-appicon-192.png';
	import SetPassword from './SetPassword.svelte';

	// #149: tilaustaso-badge lukee SAMAN auth.sub-tilan jota ProView gateaa →
	// header ja feature-lukot eivät voi olla ristiriidassa. undefined =
	// entitlement ei vielä ratkennut → ei badgea (ei väläytetä väärää tasoa).
	let { onUpgrade }: { onUpgrade?: () => void } = $props();

	// #150: email pois persistentistä headerista → account-valikko (email +
	// plan + salasanan vaihto/reset + sign out).
	let menuOpen = $state(false);
	let resetNotice = $state<string | null>(null);
	let resetBusy = $state(false);

	// #150b: valikkotila EI saa elää sign-outin yli (Hero ei unmounttaudu →
	// auki jäänyt valikko pomppasi esiin seuraavassa kirjautumisessa).
	$effect(() => {
		if (!auth.user) {
			menuOpen = false;
			resetNotice = null;
		}
	});

	// #150b: reset-linkistä saapuneelle avataan valikko + lomake valmiiksi —
	// SPA-landing oli mykkä eikä ohjannut uuden salasanan asetukseen.
	$effect(() => {
		if (auth.passwordRecovery && auth.user) menuOpen = true;
	});

	function upgrade() {
		capture('upgrade_tapped', { source: 'header_badge' });
		onUpgrade?.();
	}

	async function resetLink() {
		const email = auth.user?.email;
		if (!email || resetBusy) return;
		resetBusy = true;
		const err = await sendPasswordReset(email);
		resetNotice = err
			? `Could not send the link: ${err}`
			: 'Password reset link sent — check your email (and spam).';
		resetBusy = false;
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
			{#if auth.sub}
				<span class="plan premium">Premium</span>
			{:else if auth.sub === null}
				<button class="plan free" onclick={upgrade}>Free · Upgrade</button>
			{/if}
			<button
				class="ghost"
				aria-expanded={menuOpen}
				aria-haspopup="true"
				onclick={() => (menuOpen = !menuOpen)}
			>
				Account
			</button>
			<button class="ghost" onclick={() => void signOut()}>Sign out</button>
			{#if menuOpen}
				<div class="menu" role="dialog" aria-label="Account">
					<div class="menu-email">{auth.user.email}</div>
					<div class="menu-plan">
						Plan: {auth.sub ? 'Premium' : auth.sub === null ? 'Free' : 'checking…'}
						{#if auth.sub === null}
							· <button type="button" class="linklike" onclick={upgrade}>Upgrade</button>
						{/if}
					</div>
					{#if auth.passwordRecovery}
						<p class="banner success">
							Password reset link accepted — set your new password below.
						</p>
					{/if}
					<SetPassword
						summary="Change password (works in the GoalIQ app too)"
						open={auth.passwordRecovery}
					/>
					<button type="button" class="linklike" disabled={resetBusy} onclick={() => void resetLink()}>
						Forgot it? Email me a password reset link
					</button>
					{#if resetNotice}
						<p class="menu-notice">{resetNotice}</p>
					{/if}
					<button class="ghost menu-signout" onclick={() => void signOut()}>Sign out</button>
				</div>
			{/if}
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
		position: relative;
	}
	/* #150: account-valikko on vaalea kortti tummalla bändillä → palautetaan
	   sivun roolivärit hero-bändin overridejen alta lapsille (SetPassword,
	   .muted, inputit perivät nämä). */
	.menu {
		--text: var(--giq-ink);
		--text-muted: #5c566b;
		--border: rgba(10, 8, 32, 0.18);
		position: absolute;
		top: calc(100% + 10px);
		right: 0;
		z-index: 20;
		min-width: 300px;
		max-width: min(92vw, 380px);
		background: var(--giq-paper);
		color: var(--text);
		border: 1px solid var(--border);
		border-radius: 12px;
		padding: var(--s-4);
		box-shadow: 0 12px 32px rgba(10, 8, 32, 0.35);
		display: grid;
		gap: var(--s-2);
		text-align: left;
	}
	.menu-email {
		font-weight: 700;
		overflow-wrap: anywhere;
	}
	.menu-plan {
		color: var(--text-muted);
		font-size: var(--step--1);
	}
	.menu-notice {
		margin: 0;
		font-size: var(--step--1);
		color: var(--text-muted);
	}
	.linklike {
		background: none;
		border: none;
		padding: 0;
		margin: 0;
		color: var(--giq-magenta-deep);
		font-size: var(--step--1);
		font-weight: 700;
		text-decoration: underline;
		cursor: pointer;
		min-height: 0;
		justify-self: start;
		text-align: left;
	}
	.menu-signout {
		justify-self: start;
		color: var(--text-muted);
		border-color: var(--border);
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
