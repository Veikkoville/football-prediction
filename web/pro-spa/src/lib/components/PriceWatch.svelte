<script lang="ts">
	import { fetchPriceWatch, confBand, type PriceWatchResponse, type PriceMove } from '$lib/fantasyTools';

	let data = $state<PriceWatchResponse | null>(null);
	let error = $state<string | null>(null);

	$effect(() => {
		fetchPriceWatch().then(
			(d) => (data = d),
			(e) => (error = e instanceof Error ? e.message : String(e))
		);
	});

	const STATUS_LABEL: Record<string, string> = {
		rising_soon: 'Rising soon',
		rising_watch: 'On watch',
		falling_soon: 'Falling soon',
		falling_watch: 'On watch'
	};

	const CONF_LABEL = { low: 'low', med: 'medium', high: 'high' } as const;

	let empty = $derived(
		data != null && data.risers.length === 0 && data.fallers.length === 0
	);
</script>

{#snippet moveTable(title: string, rows: PriceMove[])}
	<div class="watch-col">
		<h3>{title}</h3>
		{#if rows.length === 0}
			<p class="muted">No candidates right now.</p>
		{:else}
			<div class="table-wrap">
				<table>
					<thead>
						<tr>
							<th>Player</th>
							<th class="num">Price</th>
							<th>Status</th>
							<th class="num"
								><abbr title="Estimated progress towards the next price change; the mark shows confidence"
									>Progress</abbr
								></th
							>
						</tr>
					</thead>
					<tbody>
						{#each rows as r (r.id)}
							{@const band = confBand(r.confidence)}
							<tr>
								<td
									>{r.web_name}{#if r.already_changed_today}
										<span class="muted"> (changed today)</span>{/if}</td
								>
								<td class="num">{r.now_cost.toFixed(1)}</td>
								<td>
									<span class="badge {r.status.startsWith('rising') ? 'up' : 'down'}">
										{STATUS_LABEL[r.status] ?? r.status}
									</span>
								</td>
								<td class="num">
									<span class="conf conf-{band}" title="{CONF_LABEL[band]} confidence">&#9679;</span
									>{Math.round(r.progress_pct)}%
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		{/if}
	</div>
{/snippet}

<h2>Price watch</h2>
<p class="muted">
	Estimated price change candidates based on FPL net-transfer velocity. Free tool.
</p>

{#if error}
	<p class="banner error">{error}</p>
{:else if !data}
	<p class="muted">Loading price watch…</p>
{:else if !data.meta.available || empty}
	<p class="banner success">
		{data.meta.note ?? 'No price change candidates right now. Check back later.'}
	</p>
{:else}
	<div class="watch-grid">
		{@render moveTable('Risers', data.risers)}
		{@render moveTable('Fallers', data.fallers)}
	</div>
{/if}

{#if data}
	<p class="muted disclaimer">{data.meta.disclaimer}</p>
{/if}

<style>
	.watch-grid {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
		gap: var(--s-6);
		align-items: start;
	}
	.watch-col h3 {
		margin-top: 0;
	}
	.badge {
		display: inline-block;
		border-radius: 999px;
		padding: 1px 10px;
		font-size: var(--step--1);
		font-weight: 700;
		border: 1px solid transparent;
	}
	.badge.up {
		color: var(--giq-teal);
		background: rgba(25, 227, 210, 0.1);
		border-color: rgba(25, 227, 210, 0.35);
	}
	.badge.down {
		color: var(--giq-coral);
		background: rgba(255, 106, 61, 0.1);
		border-color: rgba(255, 106, 61, 0.4);
	}
	/* confidence-merkki: sama väriasteikko kuin XpTable #33f */
	.conf {
		font-size: 0.65em;
		vertical-align: 1px;
		margin-right: 3px;
	}
	.conf-high {
		color: var(--giq-teal-deep);
	}
	.conf-med {
		color: var(--text-muted);
	}
	.conf-low {
		color: var(--text-muted);
		opacity: 0.45;
	}
	.disclaimer {
		margin-top: var(--s-3);
	}
</style>
