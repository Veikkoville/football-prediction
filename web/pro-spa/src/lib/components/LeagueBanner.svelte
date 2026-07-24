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
			outdraft it. Season winner gets a year of GoalIQ Premium, free.
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
		border: 1px solid rgba(255, 255, 255, 0.08);
		border-left: 4px solid var(--giq-magenta);
		border-radius: var(--radius, 12px);
		padding: 0.75rem 0.9rem;
		margin: 0 0 1rem;
		text-decoration: none;
		color: #fff;
		background: linear-gradient(160deg, var(--giq-ink), var(--giq-ink-2));
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
		color: #c9c3da;
	}
	.cta {
		color: var(--giq-gold);
		font-weight: 700;
	}
</style>
