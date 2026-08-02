<script lang="ts">
	import { fetchPriceWatch, confBand, type PriceWatchResponse, type PriceMove } from '$lib/fantasyTools';
	import { canShareToApps, shareCard } from '$lib/shareCard';
	import { capture } from '$lib/analytics';

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
	/* 2.8: jakokortti free-datalle. Price watch ei ole premiumia, ja juuri
	 * free-datan jakaminen on jakelusilmukka: jakaja mainostaa meitä
	 * maksamatta. Sama shareCard-moottori kuin leaders-listoilla. */
	let sharing = $state('');

	async function shareMoves(title: string, rows: PriceMove[]) {
		if (sharing) return;
		sharing = title;
		try {
			const method = await shareCard({
				title: `PRICE ${title.toUpperCase()}`,
				// Disclaimer kortin kylkeen: FPL:n kynnysarvot eivät ole julkisia,
				// joten tämä on arvio eikä virallinen. Sama rehellisyysrivi kuin
				// endpointin metassa.
				subtitle: 'estimated from transfer activity, not official',
				midLabel: 'PRICE',
				valueLabel: 'PROGRESS',
				fileName: `goaliq_price_${title.toLowerCase()}.png`,
				rows: rows.slice(0, 10).map((r, i) => ({
					rank: i + 1,
					name: r.web_name,
					tag: confBand(r.confidence).toUpperCase(),
					team: '',
					mid: typeof r.now_cost === 'number' ? (r.now_cost / 10).toFixed(1) : '',
					value: `${Math.round(r.progress_pct)}%`
				}))
			});
			if (method !== 'aborted') {
				capture('xp_card_shared', { list: `price_${title.toLowerCase()}`, method });
			}
		} finally {
			sharing = '';
		}
	}
</script>

{#snippet moveTable(title: string, rows: PriceMove[])}
	<div class="watch-col">
		<h3>{title}</h3>
		{#if rows.length === 0}
			<p class="muted">No candidates right now.</p>
		{:else}
			<!-- 2.8: jakokortti free-datalle, sama kaava kuin Clean Sheetsissä.
			     Nappi ilmestyy itsestään kun listalla on 3+ riviä: esikaudella
			     risers/fallers ovat tyhjät (n_with_transfer_activity 0), joten
			     tämä on inertti 21.8. asti eikä lupaa korttia jota ei voi tehdä. -->
			{#if rows.length >= 3}
				<div class="share-row">
					<button type="button" class="share-btn" onclick={() => shareMoves(title, rows)} disabled={sharing !== ''}>
						{sharing === title
							? 'Rendering…'
							: canShareToApps()
								? 'Share as image'
								: 'Download image'}
					</button>
				</div>
			{/if}
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
	.share-row {
		display: flex;
		justify-content: flex-end;
		margin: 0 0 8px;
	}
	.share-btn {
		background: transparent;
		border: 1px solid var(--track);
		color: var(--muted);
		font: inherit;
		font-size: 11px;
		padding: 4px 8px;
		cursor: pointer;
	}
	.share-btn:hover:not(:disabled) {
		color: var(--cream);
		border-color: var(--muted);
	}
	.share-btn:disabled {
		opacity: 0.6;
		cursor: default;
	}
	.watch-col h3 {
		margin-top: 0;
	}
	.badge {
		display: inline-block;
		border-radius: var(--radius);
		padding: 1px 10px;
		font-size: var(--step--1);
		font-weight: 700;
		border: 1px solid transparent;
	}
	.badge.up {
		color: var(--positive);
		background: rgba(46, 214, 194, 0.12);
		border-color: rgba(0, 148, 130, 0.4);
	}
	.badge.down {
		color: var(--negative);
		background: rgba(255, 138, 92, 0.12);
		border-color: rgba(194, 65, 12, 0.4);
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
