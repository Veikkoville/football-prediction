<script lang="ts">
	import { auth, sendPasswordReset, signOut } from '$lib/auth.svelte';
	import { capture } from '$lib/analytics';
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
			: 'Password reset link sent. Check your email (and spam).';
		resetBusy = false;
	}
</script>

<header class="hero">
	<div class="brand">
		<!-- 26.7 classic: merkki outlineksi. App-ikoni (magentatäytteinen PNG)
		     oli sivun ainoa magentaläikkä ja rikkoi ilmeen omaa sääntöä
		     (magenta = mark/captain/live, ei koskaan täyttö). Muoto säilyy —
		     pyöristetty neliö + IQ-aksentti, sama kaava kuin wordmarkissa.
		     HUOM: app-ikonia/faviconia EI muuteta; ne tarvitsevat täytön
		     erottuakseen kotinäytöllä ja kauppalistauksella. -->
		<!-- 1.8.2026: kanoninen merkki = amber-laatikko + ink IQ, sama joka
		     sivulla ja mobiilissa. Aiempi outline-merkki magentalla Q:lla oli
		     kolmas eri versio samasta logosta. -->
		<svg class="mark" width="44" height="44" viewBox="0 0 44 44" role="img" aria-label="GoalIQ">
			<rect x="0" y="0" width="44" height="44" fill="#F5C542" />
			<text x="22" y="30" text-anchor="middle" font-family="IBM Plex Mono,ui-monospace,Consolas,monospace" font-size="20" font-weight="700" letter-spacing="-0.5" fill="#0B0A09">IQ</text>
		</svg>
		<div>
			<div class="word">Goal<span>IQ</span> Premium</div>
			<div class="tag">
				Draft, rate and plan your squad with a real match model. Numbers, not vibes. ·
				<a href="https://goaliq.app">goaliq.app</a>
			</div>
		</div>
	</div>
	{#if auth.user}
		<div class="session">
			{#if auth.sub?.plan === 'gw1-3-free'}
				<!-- 16.8: ikkunan aikana badge ei saa vaittaa ostettua tilausta,
				     ja sen on pysyttava ostopolkuna: ikkuna piilottaa paywallit,
				     joten tama on kirjautuneen ainoa nakyva reitti ostaa. -->
				<button class="plan premium" onclick={upgrade}>Premium · free</button>
			{:else if auth.sub}
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
						Plan: {auth.sub?.plan === 'gw1-3-free'
							? 'Premium, free until 12 September'
							: auth.sub
								? 'Premium'
								: auth.sub === null
									? 'Free'
									: 'checking…'}
						{#if auth.sub === null || auth.sub?.plan === 'gw1-3-free'}
							· <button type="button" class="linklike" onclick={upgrade}>Upgrade</button>
						{/if}
					</div>
					{#if auth.passwordRecovery}
						<p class="banner success">
							Password reset link accepted. Set your new password below.
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
		/* 26.7 classic: tumma bändi pois. Ohjelmalehden ylätunniste on samaa
		   paperia kuin sivu, ja sen erottaa VAIN hiusviiva alla — ei täyttöä,
		   ei gradienttia, ei varjoa. Aiemmat token-overridet (vaalea teksti
		   tummalla) poistettiin, koska pohja on nyt paperi. */
		color: var(--text);
		background: transparent;
		border: none;
		border-bottom: 1px solid var(--border);
		border-radius: var(--radius);
		box-shadow: none;
		padding: var(--s-4) 0 var(--s-5);
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
	.mark {
		display: block;
		color: var(--text);
		flex: 0 0 auto;
	}
	.word {
		font-size: 26px;
		font-weight: 700;
		line-height: 1.1;
	}
	.word span {
		/* sanamerkin IQ seuraa merkkia: amber, ei enaa magenta */
		color: var(--accent);
	}
	.tag {
		color: var(--text-muted);
		font-size: var(--step--1);
		margin-top: 2px;
	}
	.tag a {
		/* landingin linkkivari */
		color: var(--giq-teal);
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
		/* 28.7 TELETEXT: tama oli `var(--giq-ink)`. Kun --giq-paper kaantyi
		   tummaksi, ink-teksti olisi ollut mustaa mustalla eli valikko olisi
		   kadonnut kokonaan. Sama ansa kuin 26.7. kovakoodattu #5c566b, vain
		   yhta astetta pahempi: se ei nakynyt haaleana vaan ei lainkaan. */
		--text: var(--giq-cream);
		/* oli kovakoodattu vanha sinertava #5c566b, joka jai elamaan classic-
		   vaihdon yli. Viittaa nyt samaan lahteeseen kuin :root. */
		--text-muted: var(--giq-muted);
		--border: rgba(243, 242, 242, 0.24);
		position: absolute;
		top: calc(100% + 10px);
		right: 0;
		z-index: 20;
		min-width: 300px;
		max-width: min(92vw, 380px);
		background: var(--giq-paper);
		color: var(--text);
		border: 1px solid var(--border);
		/* teletext: ei pyoristysta, ei varjoa. Varjo ei erota tummaa tummasta,
		   joten kelluvan valikon rajaa reuna. */
		border-radius: var(--radius);
		padding: var(--s-4);
		box-shadow: none;
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
		color: var(--giq-rust);
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
		border-radius: var(--radius);
		white-space: nowrap;
	}
	/* 26.7 classic: premium-merkki on outline, ei magentaläikkä */
	.plan.premium {
		background: transparent;
		border: 1px solid var(--accent);
		color: var(--accent-strong);
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
		border-color: var(--accent);
	}
</style>
