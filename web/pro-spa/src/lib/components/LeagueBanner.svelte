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
			outdraft it. Season winner gets a year of GoalIQ Premium, free: one prize, decided by
			the mini-league table when the season ends.
		</span>
		<span class="cta">Join with code {LEAGUE_CODE}</span>
	</span>
</a>

<style>
	/* 24.7 redesign-pariteetti: tumma ink-nauha (sama kuin landingin
	   league-band) — pomppaa kermapohjalta selvästi kortteja paremmin */
	.league-banner {
		display: flex;
		align-items: center;
		gap: 0.7rem;
		/* 26.7 classic: tumma gradienttinauha → paperi + kulta-vasenrule.
		   Sama kieli kuin muillakin korostuksilla: viiva kantaa painon. */
		border: 1px solid var(--border);
		border-left: 2px solid var(--accent);
		border-radius: var(--radius);
		padding: 0.75rem 0.9rem;
		margin: 0 0 1rem;
		text-decoration: none;
		color: var(--text);
		background: var(--surface);
	}
	.league-banner:hover .cta {
		text-decoration: underline;
	}
	.trophy {
		font-size: 1.3rem;
	}
	.body strong {
		font-family: var(--font-display);
	}
	.body {
		display: flex;
		flex-direction: column;
		gap: 0.15rem;
		font-size: var(--step--1);
	}
	.text {
		color: var(--text-muted);
	}
	.cta {
		/* gold-deep, koska nauha on nyt vaalealla paperilla (AA pienessä koossa) */
		color: var(--accent-strong);
		font-weight: 700;
	}
</style>
