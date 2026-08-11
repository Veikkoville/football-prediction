<script lang="ts">
	/**
	 * CleanSheets – CS%/FDR-matriisi GW-välivalitsimella. Web P1 (30.7):
	 * ekstraktoitu FreeView'sta omaksi komponentiksi, jotta yhdistetty
	 * 6 ryhmän ToolsHome voi renderöidä sen Players-ryhmässä. Logiikka ja
	 * markup ovat 1:1 entiset (27.7-horisonttikontrakti + 26.7 classic
	 * -värisäännöt) – vain kuori vaihtui.
	 */
	import { fetchFantasy, type FantasyResponse, type FantasyTeam } from '$lib/api';
	import { canShareToApps, shareCard } from '$lib/shareCard';
	import { capture } from '$lib/analytics';
	import MethodNote from './MethodNote.svelte';

	let data = $state<FantasyResponse | null>(null);
	let error = $state<string | null>(null);

	$effect(() => {
		fetchFantasy().then(
			(d) => (data = d),
			(e) => (error = String(e))
		);
	});

	function csCellClass(csPct: number): string {
		if (csPct >= 44) return 'is-easy';
		if (csPct <= 20) return 'is-hard';
		return '';
	}
	function fdrCellClass(fdr: number): string {
		if (fdr <= 2) return 'is-easy';
		if (fdr >= 4) return 'is-hard';
		return '';
	}

	let nearHorizon = $derived(data?.meta?.near_horizon_gw ?? 6);
	let allGws = $derived(
		[...new Set((data?.teams ?? []).flatMap((t) => t.fixtures.map((f) => f.gw)))].sort(
			(a, b) => a - b
		)
	);
	let minGw = $derived(allGws[0] ?? 1);
	let maxGw = $derived(allGws[allGws.length - 1] ?? 1);

	let gwFrom = $state(0);
	let gwTo = $state(0);
	let rangeTouched = $state(false);

	$effect(() => {
		if (!rangeTouched && allGws.length) {
			gwFrom = minGw;
			gwTo = Math.min(minGw + nearHorizon - 1, maxGw);
		}
	});

	let gwCols = $derived(allGws.filter((g) => g >= gwFrom && g <= gwTo));

	type RangeAgg = {
		n: number;
		avgFdr: number | null;
		avgCs: number | null;
		allNear: boolean;
	};

	function rangeAgg(t: FantasyTeam): RangeAgg {
		const fx = t.fixtures.filter((f) => f.gw >= gwFrom && f.gw <= gwTo);
		if (!fx.length) return { n: 0, avgFdr: null, avgCs: null, allNear: false };
		const allNear = fx.every((f) => (f.tier ?? 'near') === 'near');
		const cs = fx.map((f) => f.cs_pct).filter((v): v is number => typeof v === 'number');
		return {
			n: fx.length,
			avgFdr: fx.reduce((s, f) => s + f.fdr, 0) / fx.length,
			avgCs: allNear && cs.length === fx.length ? cs.reduce((s, v) => s + v, 0) / cs.length : null,
			allNear
		};
	}

	let sortKey = $state<'fdr' | 'cs' | 'n' | 'name'>('fdr');

	let sortedTeams = $derived.by(() => {
		const rows = (data?.teams ?? []).map((t) => ({ t, a: rangeAgg(t) }));
		rows.sort((x, y) => {
			if (x.a.n === 0 !== (y.a.n === 0)) return x.a.n === 0 ? 1 : -1;
			if (sortKey === 'name') return x.t.name.localeCompare(y.t.name);
			if (sortKey === 'n') return y.a.n - x.a.n;
			if (sortKey === 'cs') {
				if (x.a.avgCs == null && y.a.avgCs == null) return 0;
				if (x.a.avgCs == null) return 1;
				if (y.a.avgCs == null) return -1;
				return y.a.avgCs - x.a.avgCs;
			}
			return (x.a.avgFdr ?? 99) - (y.a.avgFdr ?? 99);
		});
		return rows;
	});

	/* 2.8: jakokortti myös FREE-datalle. #9a shipattiin 31.7 vain premium-
	 * listoille sillä perusteella että kortti on premium-datan johdannainen.
	 * Clean sheet -ennuste EI ole premiumia (FAQ: "Free: clean sheet
	 * probabilities, fixture difficulty ratings"), joten tässä ei ole mitään
	 * porttia – ja juuri free-datan jakaminen on se jakelusilmukka jonka
	 * haluamme: jakaja mainostaa meitä ilman että hän on maksanut. */
	let sharing = $state(false);

	/* Vain joukkueet joilla on mallinnettu CS% valitulla välillä. Kaukaisilla
	 * kierroksilla avgCs on null (far_basis), eikä korttiin panna tyhjää
	 * lukua eikä FDR:ää CS%:n paikalle.
	 * 6.8 laiteverify-pariteetti: kortin rivit AINA CS%-järjestyksessä UI-
	 * sortista riippumatta – FDR-sortilla rank-numerot näyttivät CS-rankingilta
	 * jossa 31 % oli sijalla 10 ja 35 % sijalla 4 = julkisena kuvana bugilta. */
	let shareRows = $derived(
		sortedTeams
			.filter((r) => r.a.avgCs != null)
			.toSorted((x, y) => (y.a.avgCs as number) - (x.a.avgCs as number))
			.slice(0, 10)
	);

	async function shareCs() {
		if (sharing || shareRows.length < 3) return;
		sharing = true;
		try {
			const method = await shareCard({
				title: 'CLEAN SHEET OUTLOOK',
				subtitle: `GW${gwFrom} to GW${gwTo}, GoalIQ match model`,
				nameLabel: 'TEAM',
				midLabel: 'FDR',
				valueLabel: 'CS%',
				fileName: 'goaliq_clean_sheets.png',
				rows: shareRows.map((r, i) => ({
					rank: i + 1,
					name: r.t.name,
					// tyhjä GW = 0 ja tupla = 2: se on FPL-pelaajalle olennaisin
					// konteksti keskiarvon vieressä.
					tag: `${r.a.n}x`,
					team: '',
					mid: r.a.avgFdr != null ? r.a.avgFdr.toFixed(2) : '',
					value: `${Math.round(r.a.avgCs as number)}%`
				}))
			});
			if (method !== 'aborted') capture('xp_card_shared', { list: 'clean_sheets', method });
		} finally {
			sharing = false;
		}
	}

	let rangeHasFar = $derived(gwTo > minGw + nearHorizon - 1);
	let hasDuoAny = $derived(
		data?.teams?.some((t) =>
			t.fixtures.some((f) => typeof f.def_fdr === 'number' && typeof f.att_fdr === 'number')
		) ?? false
	);
</script>

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
		<h2>
			Clean sheet outlook, GW{gwFrom}-{gwTo}
		</h2>
		<p class="muted">
			Free · <strong>Avg CS%</strong> = the team's average chance of a clean sheet from the
			match model across the gameweeks you select. It is shown only while the whole range
			sits inside the modelled window. Beyond that the calendar still tells you where the
			swings are, but a precise percentage would not be honest.
			<strong>Avg FDR</strong> = average fixture difficulty from the GoalIQ model (win% +
			xG), not FPL's official FDR; 1 = easiest, 5 = hardest. Each GW cell shows opponent,
			venue and that fixture's clean sheet probability; the cell colour follows the same
			probability on a continuous scale (model FDR in the cell tooltip).{#if hasDuoAny}
				The <strong>D · A</strong> chip splits difficulty by direction:
				<strong>D</strong> = how hard it is to keep a clean sheet,
				<strong>A</strong> = how hard it is to score, both 1 (easiest) to 5 (hardest).{/if}
		</p>

		<MethodNote summary="How these numbers are calculated">
			<p>
				<strong>Clean sheet probability</strong> is the GoalIQ match model's chance that the
				team concedes zero in that fixture. It comes from a Dixon-Coles score matrix
				(tau-corrected) fitted on match data, the same engine behind our published,
				pre-match logged track record.
			</p>
			<p>
				<strong>Fixture difficulty (FDR 1-5)</strong> is derived from the same model, not
				from FPL's official ratings: each fixture's expected outcome is scaled onto a 1-5
				band, so a "2" here means the model itself rates the matchup favourable.
			</p>
			<p>
				Projections refresh daily, including availability and injury flags. Model
				projections for fun and planning, not betting advice.
			</p>
		</MethodNote>

		<div class="gw-range">
			<label>
				<span class="muted">From GW</span>
				<select
					bind:value={gwFrom}
					onchange={() => {
						rangeTouched = true;
						if (gwTo < gwFrom) gwTo = gwFrom;
					}}
				>
					{#each allGws as g (g)}<option value={g}>{g}</option>{/each}
				</select>
			</label>
			<label>
				<span class="muted">to GW</span>
				<select
					bind:value={gwTo}
					onchange={() => {
						rangeTouched = true;
						if (gwFrom > gwTo) gwFrom = gwTo;
					}}
				>
					{#each allGws as g (g)}<option value={g}>{g}</option>{/each}
				</select>
			</label>
			<label>
				<span class="muted">Sort by</span>
				<select bind:value={sortKey}>
					<option value="fdr">Easiest fixtures</option>
					<option value="cs">Best clean sheet %</option>
					<option value="n">Most fixtures</option>
					<option value="name">Team name</option>
				</select>
			</label>
			{#if rangeTouched && (gwFrom !== minGw || gwTo !== Math.min(minGw + nearHorizon - 1, maxGw))}
				<button
					type="button"
					class="gw-reset"
					onclick={() => {
						gwFrom = minGw;
						gwTo = Math.min(minGw + nearHorizon - 1, maxGw);
					}}>Reset</button
				>
			{/if}
		</div>

		{#if rangeHasFar}
			<p class="banner">
				{data.meta.far_basis_label ??
					'Fixture difficulty only beyond the next few gameweeks. Clean sheet % appears as each gameweek moves closer.'}
			</p>
		{/if}

		{#if shareRows.length >= 3}
			<div class="share-row">
				<button type="button" class="gw-reset" onclick={shareCs} disabled={sharing}>
					{sharing
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
						<th>Team</th>
						<th class="num"><abbr title="Chance of a clean sheet from the match model, averaged over the selected gameweeks. Blank when the range reaches beyond the modelled window.">Avg CS%</abbr></th>
						<th class="num m-hide"><abbr title="Fixture difficulty from the GoalIQ model (win% + xG), not FPL's official FDR; 1 easiest to 5 hardest">Avg FDR</abbr></th>
						<th class="num m-hide"><abbr title="Fixtures in the selected range: 0 = blank gameweek, 2+ = double gameweek">Games</abbr></th>
						{#each gwCols as gw (gw)}
							<th class:is-far={gw > minGw + nearHorizon - 1} class:m-hide={gw > minGw + 1}>GW{gw}</th>
						{/each}
					</tr>
				</thead>
				<tbody>
					{#each sortedTeams as { t, a } (t.name)}
						<tr class:is-blank={a.n === 0}>
							<td>{t.name}</td>
							<td class="num">{a.avgCs != null ? a.avgCs.toFixed(1) : '–'}</td>
							<td class="num m-hide">{a.avgFdr != null ? a.avgFdr.toFixed(2) : '–'}</td>
							<td class="num m-hide">{a.n}</td>
							{#each gwCols as gw (gw)}
								{@const f = t.fixtures.find((x) => x.gw === gw)}
								{#if f}
									{@const hasDuo =
										typeof f.def_fdr === 'number' && typeof f.att_fdr === 'number'}
									{@const fdrTitle = hasDuo
										? `Defence FDR ${f.def_fdr} (clean sheet angle) · Attack FDR ${f.att_fdr} (scoring angle)`
										: `FDR ${f.fdr}`}
									{#if typeof f.cs_pct === 'number'}
										<td
											class="cs-link-cell {csCellClass(f.cs_pct)}"
											class:m-hide={gw > minGw + 1}
											title="{f.opponent ?? f.opponent_short} ({f.venue}) · {fdrTitle} · view model prediction"
										>
											<a
												class="cs-cell-a"
												href="https://goaliq.app/predictions"
												target="_blank"
												rel="noopener"
											>
												{f.opponent_short} ({f.venue}) {Math.round(f.cs_pct)}%{#if hasDuo}
													<span class="fdr-duo">D{f.def_fdr} · A{f.att_fdr}</span>{/if}
											</a>
										</td>
									{:else}
										<td
											class={fdrCellClass(f.fdr)}
											class:m-hide={gw > minGw + 1}
											title={hasDuo ? fdrTitle : undefined}
										>
											{f.opponent_short} ({f.venue})
											{#if hasDuo}
												<span class="fdr-duo">D{f.def_fdr} · A{f.att_fdr}</span>
											{:else}{f.fdr}{/if}
										</td>
									{/if}
								{:else}
									<td class="muted" class:m-hide={gw > minGw + 1}>Blank</td>
								{/if}
							{/each}
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	</section>
{/if}

<style>
	.gw-range {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--s-3);
		margin: var(--s-3) 0;
	}
	.gw-range label {
		display: inline-flex;
		align-items: center;
		gap: var(--s-2);
		font-size: var(--step--1);
	}
	.gw-range select {
		font: inherit;
		padding: 0.2em 0.4em;
		border: 1px solid var(--border);
		border-radius: var(--radius);
		background: var(--surface);
		color: var(--text);
	}
	.share-row {
		display: flex;
		justify-content: flex-end;
		margin: 0 0 8px;
	}
	.gw-reset {
		font: inherit;
		font-size: var(--step--1);
		padding: 0.2em 0.7em;
		border: 1px solid var(--border);
		border-radius: var(--radius);
		background: transparent;
		color: var(--text-muted);
		cursor: pointer;
	}
	th.is-far {
		opacity: 0.62;
		font-weight: 400;
	}
	tbody tr.is-blank {
		opacity: 0.55;
	}
	.skel-row {
		height: 34px;
		border-radius: var(--radius);
		background: var(--surface);
		border: 1px solid var(--border);
		margin: var(--s-2) 0;
	}
	.cs-link-cell {
		padding: 0;
	}
	.cs-cell-a {
		display: block;
		padding: 0.5em 0.75em;
		color: inherit;
		text-decoration: none;
	}
	.cs-cell-a:hover {
		background: rgba(243, 242, 242, 0.06);
	}
	:global(td.is-easy),
	:global(td.is-easy) .cs-cell-a {
		color: var(--accent-strong);
		font-weight: 600;
	}
	:global(td.is-hard),
	:global(td.is-hard) .cs-cell-a {
		color: var(--negative);
	}
	.fdr-duo {
		display: inline-block;
		margin-left: 6px;
		padding: 0 5px;
		border: 1px solid rgba(243, 242, 242, 0.4);
		border-radius: var(--radius);
		background: rgba(11, 10, 9, 0.72);
		color: var(--giq-cream);
		font-size: 0.72em;
		font-weight: 700;
		line-height: 1.6;
		white-space: nowrap;
	}
</style>
