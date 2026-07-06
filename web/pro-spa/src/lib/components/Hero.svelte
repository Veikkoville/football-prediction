<script lang="ts">
	import { auth, signOut } from '$lib/auth.svelte';
	import icon from '$lib/assets/goaliq-appicon-192.png';
</script>

<header class="hero">
	<div class="brand">
		<img src={icon} alt="" width="44" height="44" />
		<div>
			<div class="word">Goal<span>IQ</span> Pro</div>
			<div class="tag">
				Fantasy Premier League tools from the GoalIQ match model ·
				<a href="https://goaliq.app">goaliq.app</a>
			</div>
		</div>
	</div>
	{#if auth.user}
		<div class="session">
			<span class="muted">Signed in: {auth.user.email}</span>
			<button class="ghost" onclick={() => void signOut()}>Sign out</button>
		</div>
	{/if}
</header>

<style>
	.hero {
		background: linear-gradient(165deg, var(--giq-ink-2), var(--giq-ink));
		border: 1px solid rgba(255, 46, 126, 0.2);
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
	.session {
		display: flex;
		align-items: center;
		gap: var(--s-3);
	}
</style>
