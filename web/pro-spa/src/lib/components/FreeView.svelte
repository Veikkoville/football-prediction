<script lang="ts">
	import { fetchFantasy, fetchAccuracy, type FantasyResponse, type AccuracyResponse } from '$lib/api';

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

{#if error}
	<p class="banner error">Could not load projections right now. Please try again shortly.</p>
{:else if !data}
	<p class="muted">Loading fixtures…</p>
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
		Free · P(clean sheet) from the GoalIQ Dixon-Coles match engine. Model-based fixture
		difficulty (FDR) 1 = easiest, 5 = hardest.
	</p>

	<div class="table-wrap">
		<table>
			<thead>
				<tr>
					<th>Team</th>
					<th class="num">Avg CS%</th>
					<th class="num">Avg FDR</th>
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
