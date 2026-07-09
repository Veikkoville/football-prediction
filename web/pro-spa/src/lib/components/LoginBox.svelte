<script lang="ts">
	import { signIn, signUp } from '$lib/auth.svelte';

	let mode = $state<'in' | 'up'>('in');
	let email = $state('');
	let password = $state('');
	let error = $state<string | null>(null);
	let busy = $state(false);

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
</script>

<h3>Sign in to continue</h3>
<p class="muted">
	Expected points (xP) is part of GoalIQ Pro. Sign in or create an account first. Already
	subscribed in the GoalIQ app? Sign in with the same account and Pro is already active
	here.
</p>

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
	<button class="primary" type="submit" disabled={busy}>
		{mode === 'in' ? 'Sign in' : 'Create account'}
	</button>
</form>

<style>
	.modes {
		display: flex;
		gap: var(--s-2);
		margin-bottom: var(--s-3);
	}
	.modes .active {
		color: var(--giq-magenta-deep);
		border-color: var(--giq-magenta-deep);
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
</style>
