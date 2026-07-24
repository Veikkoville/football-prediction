<script lang="ts">
	// M29: julkinen "Beat the Model | GoalIQ" -miniliiga (classic league).
	// Koodi on julkinen ja sama kaikilla pinnoilla (X/mobiili/web).
	import { capture } from '$lib/analytics';

	const LEAGUE_CODE = 'jgi6j9';
	const JOIN_URL = `https://fantasy.premierleague.com/leagues/auto-join/${LEAGUE_CODE}`;
</script>

<a
	class="league-banner"
	href={JOIN_URL}
	target="_blank"
	rel="noopener"
	onclick={() => capture('league_join_tapped', { source: 'pro_spa_banner' })}
>
	<span class="trophy" aria-hidden="true">🏆</span>
	<span class="body">
		<strong>Beat the Model | GoalIQ</strong>
		<span class="text">
			The model picks its own FPL team this season. Join our public mini-league and try to
			outdraft it. Bragging rights on the line.
		</span>
		<span class="cta">Join with code {LEAGUE_CODE}</span>
	</span>
</a>

<style>
	.league-banner {
		display: flex;
		align-items: center;
		gap: 0.7rem;
		border: 1px solid var(--accent);
		border-radius: var(--radius, 12px);
		padding: 0.7rem 0.9rem;
		margin: 0 0 1rem;
		text-decoration: none;
		color: var(--text, inherit);
		background: var(--surface, transparent);
	}
	.league-banner:hover .cta {
		text-decoration: underline;
	}
	.trophy {
		font-size: 1.3rem;
	}
	.body {
		display: flex;
		flex-direction: column;
		gap: 0.15rem;
		font-size: var(--step--1, 0.85rem);
	}
	.text {
		color: var(--text-muted, inherit);
	}
	.cta {
		color: var(--accent);
		font-weight: 700;
	}
</style>
