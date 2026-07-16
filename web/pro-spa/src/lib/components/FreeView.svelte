<script lang="ts">
	import { fetchFantasy, type FantasyResponse } from '$lib/api';
	import MethodNote from './MethodNote.svelte';
	import Provenance from './Provenance.svelte';
	import RateTeam from './RateTeam.svelte';
	import PriceWatch from './PriceWatch.svelte';
	import SegmentNav, { type Segment } from './SegmentNav.svelte';

	// #46: lukitun siirtosuositus-teaserin klikki nostaa tämän → +page vaihtaa
	// Pro-tabiin, jossa Paywall elää (ei premium-sisältöä free-puolella).
	let { onUpgrade }: { onUpgrade?: () => void } = $props();

	// #48: yksi työkalu kerrallaan segmenttinavilla (dashboard-rakenne).
	// Rate my team + Price watch toimivat myös ilman fixture-dataa, joten
	// navi elää datahaarojen ULKOPUOLELLA.
	const SEGMENTS: Segment[] = [
		{ id: 'cleansheets', label: 'Clean sheets' },
		{ id: 'rateteam', label: 'Rate my team' },
		{ id: 'pricewatch', label: 'Price watch' }
	];
	let segment = $state('cleansheets');

	let data = $state<FantasyResponse | null>(null);
	let error = $state<string | null>(null);

	$effect(() => {
		fetchFantasy().then(
			(d) => (data = d),
			(e) => (error = String(e))
		);
	});

	const fdrVar = (fdr: number) => `var(--fdr-${Math.min(Math.max(fdr, 1), 5)})`;
	// #96 (design-audit vk3): FDR-5-token on jo magenta-deep, mutta 14 %:n
	// tint pesi sen laventelinnäköiseksi haaleaksi pinkiksi. Vaikeimmalle
	// FDR:lle vahvempi tint → solu lukee selvästi brändimagentana ja
	// "vaikein = voimakkain väri" -signaali toimii.
	const fdrTint = (fdr: number) => (fdr >= 5 ? 26 : 14);

	let gwCols = $derived(
		data?.teams?.[0]?.fixtures?.map((f) => f.gw) ?? []
	);
</script>

<!-- min-height varaa taulukkoalueen tilan ennen API-vastausta → sisältö ei
     hyppää (Lighthouse CLS -fix, QUEUE #15: 0.136-0.784 → tavoite <0.1) -->
<div class="free-view">
<!-- #50: mallin alkuperä-rivi työkalualueen yläreunassa (kiila: sama malli
     kuin julkaistun, pre-match-logatun track recordin takana) -->
<Provenance />
<SegmentNav segments={SEGMENTS} bind:active={segment} label="Free FPL tools" />

{#if segment === 'cleansheets'}
	<div id="panel-cleansheets" role="tabpanel" aria-labelledby="seg-cleansheets">
		{#if error}
			<p class="banner error">Could not load projections right now. Please try again shortly.</p>
		{:else if !data}
			<div class="skeleton" aria-hidden="true">
				<p class="muted">Loading fixtures…</p>
				{#each Array(12) as _, i (i)}
					<div class="skel-row" style="width: {92 - (i % 4) * 6}%"></div>
				{/each}
			</div>
		{:else if !data.meta?.available}
			<p class="banner success">Projections go live before Gameweek 1. Check back soon.</p>
		{:else}
			<section class="tool-card">
				<h2>Clean sheet outlook, next {data.meta.horizon_gw ?? 6} gameweeks</h2>
				<p class="muted">
					Free · <strong>Avg CS%</strong> = the team's average chance of a clean sheet from the
					match model over the next {data.meta.horizon_gw ?? 6} gameweeks.
					<strong>Avg FDR</strong> = average fixture difficulty from the GoalIQ model (win% +
					xG), not FPL's official FDR; 1 = easiest, 5 = hardest. Each GW cell shows opponent,
					venue and that fixture's FDR.
				</p>

				<MethodNote summary="How these numbers are calculated">
					<p>
						<strong>Clean sheet probability</strong> is the GoalIQ match model's chance that the
						team concedes zero in that fixture. It comes from a Dixon-Coles score matrix
						(tau-corrected) fitted on match data, the same engine behind our published,
						pre-match logged track record.
					</p>
					<p>
						<strong>Fixture difficulty (FDR 1–5)</strong> is derived from the same model, not
						from FPL's official ratings: each fixture's expected outcome is scaled onto a 1–5
						band, so a "2" here means the model itself rates the matchup favourable.
					</p>
					<p>
						Projections refresh daily, including availability and injury flags. Model
						projections for fun and planning, not betting advice.
					</p>
				</MethodNote>

				<div class="table-wrap">
					<table>
						<thead>
							<tr>
								<th>Team</th>
								<th class="num"><abbr title="Chance of a clean sheet from the match model, averaged over the next gameweeks">Avg CS%</abbr></th>
								<th class="num"><abbr title="Fixture difficulty from the GoalIQ model (win% + xG), not FPL's official FDR; 1 easiest to 5 hardest">Avg FDR</abbr></th>
								{#each gwCols as gw (gw)}
									<th>GW{gw}</th>
								{/each}
							</tr>
						</thead>
						<tbody>
							{#each data.teams as t (t.name)}
								<tr>
									<td>{t.name}</td>
									<td class="num">{t.next_avg_cs_pct.toFixed(1)}</td>
									<td class="num">{t.next_avg_fdr.toFixed(2)}</td>
									{#each gwCols as gw (gw)}
										{@const f = t.fixtures.find((x) => x.gw === gw)}
										{#if f}
											<td style="background: color-mix(in srgb, {fdrVar(f.fdr)} {fdrTint(f.fdr)}%, transparent)">
												{f.opponent_short} ({f.venue}) {f.fdr}
											</td>
										{:else}
											<td class="muted">Blank</td>
										{/if}
									{/each}
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			</section>
		{/if}
	</div>
{:else if segment === 'rateteam'}
	<!-- #46: rate-my-team ilman siirtosuosituksia (lukittu teaser → Paywall).
	     Toimii myös ilman fixture-dataa. -->
	<div class="tool-card" id="panel-rateteam" role="tabpanel" aria-labelledby="seg-rateteam">
		<RateTeam {onUpgrade} />
	</div>
{:else}
	<div class="tool-card" id="panel-pricewatch" role="tabpanel" aria-labelledby="seg-pricewatch">
		<PriceWatch />
	</div>
{/if}
</div>

<style>
	.free-view {
		min-height: 82vh;
	}
	.skel-row {
		height: 34px;
		border-radius: var(--radius-sm);
		background: var(--surface);
		border: 1px solid var(--border);
		margin: var(--s-2) 0;
	}
</style>
