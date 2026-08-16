<script lang="ts">
	import { signIn, signUp, sendMagicLink, freePremiumWindowActive } from '$lib/auth.svelte';

	// 🔴 Villen havainto 16.8: "missa ohjeistus". Tama lomake avautui aina
	// tilassa 'in' otsikolla "Already have an account?", eli ilmaisen ikkunan
	// ainoa sisaankaynti ohjasi uuden kayttajan kirjautumislomakkeelle jolle
	// hanella ei ole tunnuksia. Ikkunan ajan oletus on tilin LUONTI; sen
	// jalkeen vanha oletus on taas oikea, koska osto ei vaadi tilia.
	const windowOpen = freePremiumWindowActive();
	let mode = $state<'in' | 'up'>(windowOpen ? 'up' : 'in');
	let email = $state('');
	let password = $state('');
	let error = $state<string | null>(null);
	let busy = $state(false);
	// #101: sisäänpääsylinkki mailiin — guest-checkout-ostaja (ei salasanaa)
	// tai salasanansa unohtanut pääsee sisään ilman tukikierrosta.
	let linkNotice = $state<string | null>(null);

	async function submit(e: SubmitEvent) {
		e.preventDefault();
		if (!email || !password) {
			error = 'Email and password required.';
			return;
		}
		busy = true;
		error = null;
		error = mode === 'in' ? await signIn(email, password) : await signUp(email, password);
		busy = false;
	}

	async function emailLink() {
		if (!email) {
			error = 'Enter your email above first.';
			return;
		}
		busy = true;
		error = null;
		const err = await sendMagicLink(email);
		linkNotice = err ? null : 'Sign-in link sent. Check your email (and spam).';
		error = err;
		busy = false;
	}
</script>

<!-- #101: osto ei enää vaadi tiliä (napit PremiumPreview'ssä yllä) →
     tämä lomake palvelee OLEMASSA OLEVIA tilejä, ei portita ostoa. -->
{#if windowOpen}
	<!-- 🔴 POISTA 12.9.2026 12:30 UTC jalkeen: palauta alla oleva sign-in-otsikko. -->
	<h3>Create your free account</h3>
	<p class="muted">
		Email and a password, that is all it takes. Premium switches on straight away and stays on
		until the GW4 deadline on 12 September. No card, nothing to cancel. Already have an
		account? Use Sign in below and Premium is on there too.
	</p>
{:else}
	<h3>Already have an account? Sign in</h3>
	<p class="muted">
		Subscribed in the GoalIQ app, bought Premium here earlier, or want to use an existing
		account? Sign in and Premium is active here too.
	</p>
{/if}

<div class="modes" role="tablist" aria-label="Sign in or create account">
	<button
		class="ghost"
		class:active={mode === 'in'}
		role="tab"
		aria-selected={mode === 'in'}
		onclick={() => (mode = 'in')}>Sign in</button
	>
	<button
		class="ghost"
		class:active={mode === 'up'}
		role="tab"
		aria-selected={mode === 'up'}
		onclick={() => (mode = 'up')}>Create account</button
	>
</div>

{#if mode === 'up'}
	<p class="muted">One GoalIQ account works in the app and on the web.</p>
{/if}

<form class="card" onsubmit={submit}>
	<label for="email">Email</label>
	<input id="email" type="email" autocomplete="email" bind:value={email} />
	<label for="password">Password{mode === 'up' ? ' (min 6 chars)' : ''}</label>
	<input
		id="password"
		type="password"
		autocomplete={mode === 'up' ? 'new-password' : 'current-password'}
		bind:value={password}
	/>
	{#if error}
		<p class="banner error">Authentication failed: {error}</p>
	{/if}
	{#if linkNotice}
		<p class="banner success">{linkNotice}</p>
	{/if}
	<button class="primary" type="submit" disabled={busy}>
		{mode === 'in' ? 'Sign in' : 'Create account'}
	</button>
	{#if mode === 'in'}
		<p class="muted link-row">
			Bought Premium without a password, or forgot it?
			<button type="button" class="linklike" disabled={busy} onclick={() => void emailLink()}>
				Email me a sign-in link
			</button>
		</p>
	{/if}
</form>

<style>
	.modes {
		display: flex;
		gap: var(--s-2);
		margin-bottom: var(--s-3);
	}
	.modes .active {
		color: var(--giq-rust);
		border-color: var(--giq-rust);
	}
	form {
		max-width: 460px;
		display: grid;
		gap: var(--s-2);
	}
	form button {
		justify-self: start;
		margin-top: var(--s-2);
	}
	.link-row {
		margin: 0;
		font-size: var(--step--1);
	}
	.linklike {
		background: none;
		border: none;
		padding: 0;
		margin: 0;
		color: var(--giq-rust);
		font-size: inherit;
		font-weight: 700;
		text-decoration: underline;
		cursor: pointer;
		min-height: 0;
	}
</style>
