<script lang="ts">
	import type { XpResponse } from '$lib/api';
	import {
		fetchComparePlayers,
		type CompareResponse,
		type ComparePlayer
	} from '$lib/fantasyTools';

	// Valinnat populoituvat jo ladatusta xP-datasta (sama prop kuin XpTable) -
	// ei erillistä pelaajahakua eikä käsin syötettäviä ID:itä.
	let { xp }: { xp: XpResponse } = $props();

	// Labelit = ComponentSplit-pariteetti
	const LABELS: Record<string, string> = {
		appearance: 'Appearance',
		goals: 'Goals',
		assists: 'Assists',
		clean_sheet: 'Clean sheet',
		conceded: 'Conceded',
		saves: 'Saves',
		defensive_contribution: 'Def. contribution',
		yellows: 'Cards',
		bonus: 'Bonus'
	};
	const CONF_LABEL = { low: 'low', med: 'medium', high: 'high' } as const;

	let idA = $state<number | null>(null);
	let idB = $state<number | null>(null);
	let loading = $state(false);
	let error = $state<string | null>(null);
	let data = $state<CompareResponse | null>(null);

	let options = $derived(
		[...xp.players].sort(
			(a, b) => a.web_name.localeCompare(b.web_name) || a.team_short.localeCompare(b.team_short)
		)
	);
	let ready = $derived(idA != null && idB != null && idA !== idB);

	async function compare(e: SubmitEvent) {
		e.preventDefault();
		if (!ready || loading || idA == null || idB == null) return;
		loading = true;
		error = null;
		try {
			data = await fetchComparePlayers([idA, idB]);
		} catch (err) {
			data = null;
			error = err instanceof Error ? err.message : String(err);
		}
		loading = false;
	}

	function components(p: ComparePlayer) {
		return Object.entries(p.components ?? {})
			.filter(([, v]) => typeof v === 'number' && Math.abs(v) >= 0.005)
			.sort(([, a], [, b]) => b - a);
	}
</script>

<h2>Compare players</h2>
<p class="muted">
	Head to head on the GoalIQ projections: xP, price, ownership, predicted minutes and the
	per-component split for the next gameweek.
</p>

<form class="cmp-form" onsubmit={compare}>
	<div>
		<label for="cmp-a">Player A</label>
		<select id="cmp-a" bind:value={idA}>
			<option value={null} disabled>Select a player</option>
			{#each options as p (p.id)}
				<option value={p.id}>{p.web_name} ({p.team_short}, {p.pos})</option>
			{/each}
		</select>
	</div>
	<div>
		<label for="cmp-b">Player B</label>
		<select id="cmp-b" bind:value={idB}>
			<option value={null} disabled>Select a player</option>
			{#each options as p (p.id)}
				<option value={p.id}>{p.web_name} ({p.team_short}, {p.pos})</option>
			{/each}
		</select>
	</div>
	<button class="primary" type="submit" disabled={!ready || loading}>
		{loading ? 'Comparing…' : 'Compare'}
	</button>
</form>
{#if idA != null && idA === idB}
	<p class="muted">Pick two different players.</p>
{/if}

{#if error}
	<p class="banner error">{error}</p>
{:else if data}
	<p class="verdict">{data.verdict.text}</p>
	<div class="cmp-grid">
		{#each data.players as p (p.id)}
			<div class="card cmp-card" class:winner={p.id === data.verdict.pick.id}>
				<h3>{p.web_name} <span class="muted">({p.team_short}, {p.pos})</span></h3>
				<dl>
					<div><dt>Total xP, next {data.meta.horizon_gw ?? 6} GWs</dt><dd class="strong">{p.xp_horizon_total.toFixed(2)}</dd></div>
					<div><dt>xP per GW</dt><dd>{p.xp_per_gw.toFixed(2)}</dd></div>
					<div><dt>Price</dt><dd>{p.price.toFixed(1)}</dd></div>
					<div><dt>Owned %</dt><dd>{p.owned_pct != null ? p.owned_pct.toFixed(1) : 'n/a'}</dd></div>
					<div>
						<dt>Predicted starts</dt>
						<dd>
							{#if p.predicted_starts != null}
								{Math.round(p.predicted_starts)}%
								{#if p.minutes_confidence}
									<span
										class="conf conf-{p.minutes_confidence}"
										title="{CONF_LABEL[p.minutes_confidence]} confidence">&#9679;</span
									><span class="muted"> {CONF_LABEL[p.minutes_confidence]} confidence</span>
								{/if}
							{:else}
								n/a
							{/if}
						</dd>
					</div>
				</dl>
				{#if p.components}
					<h4 class="muted">GW{p.components_gw ?? ''} xP components</h4>
					<ul class="comps">
						{#each components(p) as [key, value] (key)}
							<li>
								<span>{LABELS[key] ?? key}</span>
								<span class="val" class:neg={value < 0}>
									{value > 0 ? '+' : ''}{value.toFixed(2)}
								</span>
							</li>
						{/each}
					</ul>
				{/if}
			</div>
		{/each}
	</div>
	<p class="muted">GoalIQ model projections, not FPL official; not betting advice.</p>
{/if}

<style>
	.cmp-form {
		display: flex;
		flex-wrap: wrap;
		gap: var(--s-3);
		align-items: end;
		margin-bottom: var(--s-4);
	}
	.verdict {
		font-size: var(--step-1);
		font-weight: 700;
		color: var(--positive);
		margin-bottom: var(--s-4);
	}
	.cmp-grid {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
		gap: var(--s-4);
		max-width: 760px;
		margin-bottom: var(--s-3);
	}
	.cmp-card {
		padding: var(--s-4);
	}
	.cmp-card.winner {
		border-color: var(--giq-teal-deep);
	}
	.cmp-card h3 {
		margin-top: 0;
	}
	dl {
		margin: 0 0 var(--s-3);
		display: grid;
		gap: var(--s-1);
	}
	dl > div {
		display: flex;
		justify-content: space-between;
		gap: var(--s-3);
		font-size: var(--step--1);
	}
	dt {
		color: var(--text-muted);
	}
	dd {
		margin: 0;
		font-variant-numeric: tabular-nums;
	}
	dd.strong {
		font-weight: 700;
	}
	h4 {
		margin: 0 0 var(--s-2);
		font-size: var(--step--1);
		font-weight: 700;
	}
	.comps {
		list-style: none;
		margin: 0;
		padding: 0;
		display: grid;
		gap: 2px;
		font-size: var(--step--1);
	}
	.comps li {
		display: flex;
		justify-content: space-between;
	}
	.comps .val {
		color: var(--positive);
		font-weight: 700;
		font-variant-numeric: tabular-nums;
	}
	.comps .val.neg {
		color: var(--negative);
	}
	.conf {
		font-size: 0.65em;
		vertical-align: 1px;
		margin-left: 4px;
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
</style>
