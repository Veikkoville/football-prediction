<script lang="ts">
	import { onMount } from 'svelte';
	import { fetchXp, gwXp, type XpResponse } from '$lib/api';
	import { capture } from '$lib/analytics';
	import Provenance from './Provenance.svelte';

	// #95: login-seinä myy ennen lomaketta — sama arvolupaus kuin mobiilin
	// UpgradeCard-paywallissa. Copy 1:1 paywall.bullet_* -en-avaimista
	// (goaliq-app/lib/i18n/en.ts) → yksi lähde arvoviestille molemmilla pinnoilla.
	const BULLETS = [
		'Per-player xP projections for every gameweek',
		'Captain ranker with top picks',
		'Differential finder: low ownership, high xP',
		'Multi-gameweek transfer planner',
		'Full match analysis: scorelines, goals & momentum'
	];

	let teaser = $state<XpResponse | null>(null);

	onMount(() => {
		// Sama funneli-event kuin Paywall, oma source erottaa login-seinän
		// (kirjautumaton) varsinaisesta plan-valitsimesta (kirjautunut, ei subia).
		capture(
			'paywall_shown',
			{ source: 'pro_web_login_gate' },
			'paywall_shown_login_gate'
		);
		fetchXp().then((d) => (teaser = d), () => {});
	});

	// Sama top-3-poiminta kuin Paywall-teaser: nimet näkyvät, arvot lukossa
	// (•.••) → ei premium-arvovuotoa, mutta käyttäjä näkee MITÄ avaa.
	let top3 = $derived.by(() => {
		if (!teaser?.meta?.available) return [];
		const gw = teaser.meta.next_gameweek;
		return [...teaser.players].sort((a, b) => gwXp(b, gw) - gwXp(a, gw)).slice(0, 3);
	});
</script>

<section class="preview card" aria-label="What GoalIQ Premium includes">
	<h3>What Premium unlocks</h3>
	<ul class="bullets">
		{#each BULLETS as b (b)}
			<li>{b}</li>
		{/each}
	</ul>

	{#if top3.length > 0}
		<div class="teaser" aria-label="Locked expected points preview">
			<table>
				<thead>
					<tr>
						<th>Player</th>
						<th class="num"><abbr title="Expected points from the GoalIQ match model">xP</abbr> · GW{teaser?.meta.next_gameweek}</th>
					</tr>
				</thead>
				<tbody>
					{#each top3 as p, i (p.id)}
						<tr>
							<td>{i + 1}. {p.web_name} <span class="muted">({p.team_short}, {p.pos})</span></td>
							<td class="num locked-val" aria-label="Locked">•.••</td>
						</tr>
					{/each}
				</tbody>
			</table>
			<span class="lock-pill">
				<svg
					width="12"
					height="12"
					viewBox="0 0 24 24"
					fill="currentColor"
					aria-hidden="true"
				>
					<path
						d="M12 2a5 5 0 0 0-5 5v3H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-8a2 2 0 0 0-2-2h-1V7a5 5 0 0 0-5-5Zm-3 8V7a3 3 0 1 1 6 0v3H9Z"
					/>
				</svg>
				Unlocks with Premium
			</span>
		</div>
	{/if}

	<Provenance />
</section>

<style>
	.preview {
		max-width: 460px;
		margin-bottom: var(--s-4);
	}
	.preview h3 {
		margin-top: 0;
	}
	.bullets {
		margin: 0 0 var(--s-4);
		padding: 0;
		list-style: none;
		display: grid;
		gap: var(--s-2);
	}
	.bullets li {
		position: relative;
		padding-left: var(--s-4);
		font-size: var(--step--1);
	}
	.bullets li::before {
		content: '◆';
		position: absolute;
		left: 0;
		color: var(--giq-magenta-deep);
		font-size: 0.7em;
		top: 0.35em;
	}
	/* Lukittu xP-teaser: rivit himmennetty + lukko-pilleri overlayna →
	   käyttäjä näkee taulukon muodon muttei arvoja (sama •.••-kieli kuin
	   Paywall/RateTeam-teaserit) */
	.teaser {
		position: relative;
		border: 1px solid var(--border);
		border-radius: var(--radius-sm);
		overflow: hidden;
		margin-bottom: var(--s-4);
	}
	.teaser table {
		width: 100%;
	}
	.teaser tbody {
		opacity: 0.75;
	}
	.locked-val {
		color: var(--giq-magenta-deep);
		font-weight: 700;
		letter-spacing: 2px;
	}
	.lock-pill {
		position: absolute;
		top: 50%;
		left: 50%;
		transform: translate(-50%, -50%);
		display: inline-flex;
		align-items: center;
		gap: var(--s-1);
		background: var(--giq-ink);
		color: var(--giq-cream);
		border-radius: 999px;
		padding: var(--s-1) var(--s-3);
		font-size: var(--step--1);
		font-weight: 700;
		white-space: nowrap;
		box-shadow: var(--shadow-1);
		pointer-events: none;
	}
	.lock-pill svg {
		color: var(--giq-magenta);
	}
</style>
