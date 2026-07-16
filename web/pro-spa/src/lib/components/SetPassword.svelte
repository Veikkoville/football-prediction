<script lang="ts">
	// #101: guest-checkout-tili syntyy ilman salasanaa (magic-link-kirjautuminen).
	// Mobiili-app kirjautuu email+salasanalla → tarjoa salasanan asetus webissä
	// kirjautuneelle. Suljettu <details> → ei kohinaa salasanallisille.
	import { setPassword } from '$lib/auth.svelte';

	let password = $state('');
	let notice = $state<string | null>(null);
	let error = $state<string | null>(null);
	let busy = $state(false);

	async function submit(e: SubmitEvent) {
		e.preventDefault();
		if (password.length < 6) {
			error = 'Password must be at least 6 characters.';
			return;
		}
		busy = true;
		error = null;
		const err = await setPassword(password);
		error = err;
		notice = err ? null : 'Password set. You can now sign in to the GoalIQ app with it.';
		if (!err) password = '';
		busy = false;
	}
</script>

<details class="setpw">
	<summary>Set a password (to sign in to the GoalIQ iOS/Android app)</summary>
	<form onsubmit={submit}>
		<label for="new-password">New password (min 6 chars)</label>
		<input id="new-password" type="password" autocomplete="new-password" bind:value={password} />
		{#if error}
			<p class="banner error">{error}</p>
		{/if}
		{#if notice}
			<p class="banner success">{notice}</p>
		{/if}
		<button class="secondary" type="submit" disabled={busy}>
			{busy ? 'Saving…' : 'Save password'}
		</button>
	</form>
</details>

<style>
	.setpw {
		margin: var(--s-3) 0;
		font-size: var(--step--1);
	}
	.setpw summary {
		cursor: pointer;
		color: var(--text-muted);
	}
	form {
		max-width: 320px;
		display: grid;
		gap: var(--s-2);
		margin-top: var(--s-2);
	}
	form button {
		justify-self: start;
	}
</style>
