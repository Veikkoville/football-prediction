<script lang="ts">
	import { onMount } from 'svelte';
	import type { XpResponse } from '$lib/api';
	import { gwXp, gwOpponents } from '$lib/api';
	import { capture } from '$lib/analytics';
	import { canShareToApps, shareCard } from '$lib/shareCard';
	import SetPieceBadges from './SetPieceBadges.svelte';

	let { data }: { data: XpResponse } = $props();

	let nextGw = $derived(data.meta.next_gameweek);
	let top = $derived(
		[...data.players].sort((a, b) => gwXp(b, nextGw) - gwXp(a, nextGw)).slice(0, 10)
	);
	// Edge-sprint kohta 3: e_bonus-sarake vain jos backend tuo kentän
	// (defensiivinen — vanha payload ei tuo). Karkea proxy, EI BPS-simulaatio.
	let hasEBonus = $derived(top.some((p) => typeof p.e_bonus === 'number'));

	onMount(() => {
		capture('captain_viewed', { source: 'pro_spa' }, 'captain_viewed_pro_spa');
	});

	// #9a Share as image (Wolfy-flow tuotteessa): sama teletext-kortti kuin
	// viikkopostauksessa, suoraan tästä taulusta. Komponentti renderöityy vain
	// premiumille (ToolsHome-gate), joten nappi on premium-gatettu implisiittisesti.
	let sharing = $state(false);
	async function shareImage() {
		if (sharing) return;
		sharing = true;
		try {
			const method = await shareCard({
				title: `GAMEWEEK ${nextGw} TOP 10`,
				subtitle: 'expected points, GoalIQ match model',
				midLabel: 'FIXTURE',
				valueLabel: 'xP',
				fileName: `goaliq_xp_gw${nextGw}_top10.png`,
				rows: top.map((p, i) => ({
					rank: i + 1,
					name: p.web_name,
					tag: p.pos,
					team: p.team_short,
					badges: [
						...(typeof p.set_pieces?.pens === 'number' && p.set_pieces.pens <= 2 ? ['P'] : []),
						...(typeof p.set_pieces?.fk === 'number' && p.set_pieces.fk <= 2 ? ['FK'] : [])
					],
					mid: gwOpponents(p, nextGw),
					value: gwXp(p, nextGw).toFixed(2)
				}))
			});
			if (method !== 'aborted') capture('xp_card_shared', { list: 'captain', method });
		} finally {
			sharing = false;
		}
	}
</script>

<div class="head-row">
	<h2>Captain ranker: top xP for GW{nextGw}</h2>
	<!-- Desktopilla label lupaa latauksen, mobiilissa share-arkin (31.7) -->
	<button type="button" class="share-chip" onclick={shareImage} disabled={sharing}>
		{sharing ? 'Rendering…' : canShareToApps() ? 'Share as image' : 'Download image'}
	</button>
</div>
<p class="muted">
	The ten highest projected scores for the next gameweek only, a captaincy shortlist.
	{#if hasEBonus}<abbr
			title="Expected bonus points per match: a rough estimate from the player's historical bonus rate scaled by expected minutes, not a simulated bonus"
			>eBonus</abbr
		> is already part of xP, shown separately so you can see who tends to sweep bonus.{/if}
	The full table below covers the whole horizon.
</p>
<!-- 31.7 (Wolfyn palaute, Villen GO): lista luetaan yhdellä silmäyksellä —
     positio heti nimen vieressä tagina, joukkue himmeänä perässä, vastustaja
     heti pelaajan jälkeen (ei enää rivin hännillä), luvut oikeaan laitaan.
     Sama järjestys jonka jaettava viikkokuva käyttää → screenshot ja kuva
     kertovat saman tarinan samassa muodossa. -->
<div class="table-wrap">
	<table>
		<thead>
			<tr>
				<th class="num">#</th>
				<th>Player</th>
				<th>Fixture</th>
				<th class="num">GW{nextGw} xP</th>
				{#if hasEBonus}
					<th class="num"
						><abbr
							title="Expected bonus points per match, a rough historical-rate estimate (already included in xP)"
							>eBonus</abbr
						></th
					>
				{/if}
			</tr>
		</thead>
		<tbody>
			{#each top as p, i (p.id)}
				<tr>
					<td class="num">{i + 1}</td>
					<td
						>{p.web_name}
						<span class="pos-tag">{p.pos}</span>
						<span class="team-muted">{p.team_short}</span><SetPieceBadges
							sp={p.set_pieces}
						/></td
					>
					<td>{gwOpponents(p, nextGw)}</td>
					<td class="num">{gwXp(p, nextGw).toFixed(2)}</td>
					{#if hasEBonus}
						<td class="num">
							{#if typeof p.e_bonus === 'number'}{p.e_bonus.toFixed(2)}{/if}
						</td>
					{/if}
				</tr>
			{/each}
		</tbody>
	</table>
</div>

<style>
	.head-row {
		display: flex;
		align-items: baseline;
		justify-content: space-between;
		gap: var(--s-2);
		flex-wrap: wrap;
	}
	.share-chip {
		flex: 0 0 auto;
		border: 1px solid var(--border);
		border-radius: var(--radius);
		background: var(--surface);
		color: var(--text-muted);
		font-weight: 700;
		font-size: var(--step--1);
		padding: 4px 12px;
		cursor: pointer;
		white-space: nowrap;
		line-height: 1.4;
	}
	.share-chip:disabled {
		opacity: 0.6;
		cursor: default;
	}
	.pos-tag {
		display: inline-block;
		margin-left: 5px;
		padding: 0 5px;
		border-radius: var(--radius);
		border: 1px solid rgba(243, 242, 242, 0.28);
		font-size: 0.68em;
		font-weight: 700;
		line-height: 1.5;
		vertical-align: 1px;
		opacity: 0.85;
	}
	.team-muted {
		margin-left: 4px;
		opacity: 0.55;
		font-size: 0.85em;
	}
</style>
