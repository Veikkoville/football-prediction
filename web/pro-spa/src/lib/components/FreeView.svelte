<script lang="ts">
	import { fetchFantasy, fetchAccuracy, type FantasyResponse, type AccuracyResponse } from '$lib/api';
	import MethodNote from './MethodNote.svelte';
	import RateTeam from './RateTeam.svelte';
	import PriceWatch from './PriceWatch.svelte';

	// #46: lukitun siirtosuositus-teaserin klikki nostaa tämän → +page vaihtaa
	// Pro-tabiin, jossa Paywall elää (ei premium-sisältöä free-puolella).
	let { onUpgrade }: { onUpgrade?: () => void } = $props();

	let data = $state<FantasyResponse | null>(null);
	let acc = $state<AccuracyResponse | null>(null);
	let error = $state<string | null>(null);

	$effect(() => {
		fetchFantasy().then(
			(d) => (data = d),
			(e) => (error = String(e))
		);
		fetchAccuracy().then((a) => (acc = a));
	});

	const fdrVar = (fdr: number) => `var(--fdr-${Math.min(Math.max(fdr, 1), 5)})`;

	let gwCols = $derived(
		data?.teams?.[0]?.fixtures?.map((f) => f.gw) ?? []
	);
	let trackRecord = $derived.by(() => {
		const at = acc?.all_time;
		if (at?.n && at?.pct_1x2) return { n: at.n, pct: at.pct_1x2 * 100 };
		return null;
	});
</script>

<!-- min-height varaa taulukkoalueen tilan ennen API-vastausta → sisältö ei
     hyppää (Lighthouse CLS -fix, QUEUE #15: 0.136-0.784 → tavoite <0.1) -->
<div class="free-view">
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
	{#if trackRecord}
		<p class="banner success">
			Track record: {trackRecord.pct.toFixed(1)} % correct 1X2 across {trackRecord.n}
			pre-match-logged predictions ·
			<a href="https://goaliq.app/fpl.html#track-record">methodology</a>
		</p>
	{/if}

	<h2>Clean sheet outlook, next {data.meta.horizon_gw ?? 6} gameweeks</h2>
	<p class="muted">
		Free · <strong>Avg CS%</strong> = the team's average clean sheet probability over the
		next {data.meta.horizon_gw ?? 6} gameweeks. <strong>Avg FDR</strong> = average fixture
		difficulty, 1 = easiest, 5 = hardest. Each GW cell shows opponent, venue and that
		fixture's FDR.
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
					<th class="num"><abbr title="Average clean sheet probability, next gameweeks">Avg CS%</abbr></th>
					<th class="num"><abbr title="Average model-based fixture difficulty, 1 easiest to 5 hardest">Avg FDR</abbr></th>
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
								<td style="background: color-mix(in srgb, {fdrVar(f.fdr)} 14%, transparent)">
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
{/if}

<!-- #46: FPL-työkalut (free-pinta) - rate-my-team ilman siirtosuosituksia
     + price watch. Renderöityvät myös ilman fixture-dataa. -->
<RateTeam {onUpgrade} />
<PriceWatch />
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
