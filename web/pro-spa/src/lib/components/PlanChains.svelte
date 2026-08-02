<script lang="ts">
	// Edge-sprint kohta 7: plan-chains (solver-light beam search, premium).
	// plans[0] = hero, 2 seuraavaa kompakteina vaihtoehtoina (backend dedupaa,
	// mutta ketjut voivat silti erota vain yhdellä siirrolla — contract-api).
	// Pre-GW1: backend palauttaa 404 + selitteen → näytetään siististi.
	import {
		fetchPlanChains,
		fetchPlanChainsDraft,
		type PlanChainsResponse
	} from '$lib/fantasyTools';
	import { runWithSquadFallback, NoSquadInputError, type SquadBasis } from '$lib/squadInput';
	import { capture } from '$lib/analytics';
	import { fplEntry, persistEntry } from '$lib/fplEntry.svelte';
	import MethodNote from './MethodNote.svelte';
	import ModelWorking from './ModelWorking.svelte';

	const WORKING_STEPS = [
		'Fetching your FPL squad',
		'Loading model xP projections',
		'Beam-searching transfer chains (0-2 moves per GW)',
		'Ranking the best plans against holding'
	];

	const HORIZONS = [2, 3, 4, 5, 6] as const;

	let horizon = $state(3);
	let loading = $state(false);
	let error = $state<string | null>(null);
	/** PI-16b: 'draft' = ajettu tallennetulla 15:llä, koska FPL ei ole vielä
	 *  julkaissut kokoonpanoja. */
	let basedOn = $state<SquadBasis>('entry');
	let needsDraft = $state(false);
	let data = $state<PlanChainsResponse | null>(null);

	let entryValid = $derived(/^\d{1,10}$/.test(fplEntry.entry.trim()));

	async function build(e: SubmitEvent) {
		e.preventDefault();
		if (!entryValid || loading) return;
		loading = true;
		error = null;
		needsDraft = false;
		try {
			const id = Number(fplEntry.entry.trim());
			// PI-16b (28.7): sama esikausifallback kuin plannerissa. Ilman tätä
			// tämä työkalu oli 404 kaikille GW1-deadlineen (21.8) asti.
			const run = await runWithSquadFallback(
				id,
				(entry) => fetchPlanChains(entry, horizon),
				(ids) => fetchPlanChainsDraft(ids, horizon)
			);
			data = run.data;
			basedOn = run.basedOn;
			void persistEntry(id); // #66: talteen vasta onnistuneesta hausta
			capture('plan_chains_viewed', { source: 'pro_spa', horizon, basis: run.basedOn });
		} catch (err) {
			data = null;
			if (err instanceof NoSquadInputError) {
				needsDraft = true;
			} else {
				error = err instanceof Error ? err.message : String(err);
			}
		}
		loading = false;
	}

	let hero = $derived(data?.plans?.[0] ?? null);
	let alternatives = $derived(data?.plans?.slice(1, 3) ?? []);

	function movesSummary(plan: { gws: { moves: { out: { web_name: string }; in: { web_name: string } }[] }[] }): string {
		const parts: string[] = [];
		for (const g of plan.gws) {
			for (const m of g.moves) parts.push(`${m.out.web_name} to ${m.in.web_name}`);
		}
		return parts.length > 0 ? parts.join(', ') : 'No transfers, roll every week';
	}
</script>

<h2>Plan chains: best transfer paths over your horizon</h2>
<p class="muted">
	A beam search tries 0-2 transfers per gameweek (hits included at -4) and returns the
	three best chains against simply holding. Deeper than the single-path planner: it
	weighs whole sequences of moves, not one week at a time.
</p>

<form class="chains-form" onsubmit={build}>
	<div>
		<label for="chains-entry">FPL entry ID</label>
		<input
			id="chains-entry"
			inputmode="numeric"
			autocomplete="off"
			placeholder="e.g. 1234567"
			bind:value={fplEntry.entry}
		/>
	</div>
	<div>
		<label for="chains-horizon"
			><abbr title="How many upcoming gameweeks the chains cover">Horizon</abbr> (GWs)</label
		>
		<select id="chains-horizon" bind:value={horizon}>
			{#each HORIZONS as h (h)}
				<option value={h}>{h}</option>
			{/each}
		</select>
	</div>
	<button class="primary" type="submit" disabled={!entryValid || loading}>
		{loading ? 'Searching…' : 'Find best chains'}
	</button>
</form>
{#if !entryValid}
	<!-- PI-16b (28.7): vanha teksti sanoi "before that this tool has no squad to
	     plan from". Se piti paikkansa ennen tätä korjausta eikä pidä enää:
	     tallennettu draft kelpaa syötteeksi. -->
	<p class="muted hint">
		Enter your public FPL entry ID (the number in your Points page URL). Before the Gameweek 1
		deadline FPL keeps every squad private, so the chains run on the 15 you drafted in Rate my
		team instead.
	</p>
{/if}

{#if loading}
	<ModelWorking steps={WORKING_STEPS} />
{/if}

{#if needsDraft}
	<p class="notice-preseason">
		<strong>Your squad is not public yet.</strong> FPL publishes every team only after the
		Gameweek 1 deadline. Until then, draft your 15 in Rate my team and the chain search runs on
		that draft.
	</p>
{:else if error}
	<p class="banner error">{error}</p>
{:else if data && hero}
	{#if basedOn === 'draft'}
		<p class="notice-preseason">
			Based on your saved draft of 15, because FPL does not publish squads until the Gameweek
			1 deadline.
		</p>
	{/if}
	{#if data.meta.timeout_degraded}
		<p class="muted">
			The search hit its time budget and was trimmed, results are still valid plans but
			the space was not fully explored.
		</p>
	{/if}

	<!-- Hero: paras ketju kokonaisena aikajanana -->
	<div class="hero-plan card">
		<div class="hero-head">
			<h3>Best chain</h3>
			<span class="net-pill"
				>{hero.net_ev_vs_hold >= 0 ? '+' : ''}{hero.net_ev_vs_hold.toFixed(1)} xP vs
				holding</span
			>
		</div>
		<p class="muted rationale">{hero.rationale}</p>
		<div class="chain-timeline">
			{#each hero.gws as g (g.gw)}
				<div class="gw-card">
					<div class="gw-head">
						<strong>GW{g.gw}</strong>
						<span class="gw-xp">{g.gw_xp.toFixed(1)} xP</span>
					</div>
					{#if g.roll_transfer || g.moves.length === 0}
						<p class="muted roll">Roll transfer</p>
					{:else}
						<ul class="moves">
							{#each g.moves as m (m.out.id + '-' + m.in.id)}
								<li>
									{m.out.web_name} <span class="muted">({m.out.team_short})</span>
									<span class="arrow">→</span>
									{m.in.web_name} <span class="muted">({m.in.team_short})</span>
									<span class="gain">+{m.gain_xp_remaining.toFixed(2)}</span>
									{#if m.hit}<span class="hit">{m.hit} hit</span>{/if}
								</li>
							{/each}
						</ul>
					{/if}
					<p class="gw-meta muted">
						C: {g.captain.web_name} ({g.captain.gw_xp.toFixed(1)}) · FTs left:
						{g.free_transfers_left} · Bank: {g.bank.toFixed(1)}
					</p>
				</div>
			{/each}
		</div>
		<p class="totals-line">
			Chain total: <strong>{hero.total_xp.toFixed(1)} xP</strong>
			<span class="muted">
				· no-transfer baseline {data.baseline_xp_no_transfers.toFixed(1)} · hits taken
				{hero.hits_taken}</span
			>
		</p>
	</div>

	{#if alternatives.length > 0}
		<h3>Alternatives</h3>
		<div class="alt-grid">
			{#each alternatives as plan, i (i)}
				<div class="alt-card card">
					<p class="alt-head">
						<strong>Plan {i + 2}</strong>
						<span class="net-pill alt"
							>{plan.net_ev_vs_hold >= 0 ? '+' : ''}{plan.net_ev_vs_hold.toFixed(1)} xP</span
						>
					</p>
					<p class="alt-moves">{movesSummary(plan)}</p>
					<p class="muted alt-meta">
						{plan.total_xp.toFixed(1)} xP total · {plan.hits_taken}
						{plan.hits_taken === 1 ? 'hit' : 'hits'}
					</p>
				</div>
			{/each}
		</div>
	{/if}

	<MethodNote summary="How chains are found (and their limits)">
		<p>
			{data.meta.heuristic ??
				'Beam search, 0-2 transfers per GW, hit -4, remaining-horizon xP, not a global optimum.'}
		</p>
		<p>
			Free transfers are assumed at {data.meta.ft_assumed} to start (the FPL API does not
			expose your banked transfers). The top plans can be near-identical when the search
			converges, that is expected.
		</p>
		<p>{data.meta.note ?? 'GoalIQ model projections, for fun and planning, not betting advice.'}</p>
	</MethodNote>
{/if}

<style>
	.chains-form {
		display: flex;
		flex-wrap: wrap;
		gap: var(--s-3);
		align-items: end;
		margin-bottom: var(--s-3);
	}
	.hint {
		margin: 0 0 var(--s-4);
	}
	.hero-plan {
		border-color: rgba(255, 138, 92, 0.35);
		background:
			linear-gradient(160deg, rgba(255, 138, 92, 0.07), transparent 55%),
			var(--surface);
		margin-bottom: var(--s-4);
	}
	.hero-head {
		display: flex;
		flex-wrap: wrap;
		justify-content: space-between;
		align-items: baseline;
		gap: var(--s-2);
	}
	.hero-head h3 {
		margin: 0;
	}
	.net-pill {
		background: rgba(46, 214, 194, 0.12);
		border: 1px solid rgba(0, 148, 130, 0.4);
		color: var(--giq-ink);
		border-radius: var(--radius);
		padding: 2px 12px;
		font-size: var(--step--1);
		font-weight: 700;
		white-space: nowrap;
	}
	.net-pill.alt {
		padding: 1px 10px;
	}
	.rationale {
		margin: var(--s-2) 0 var(--s-4);
	}
	.chain-timeline {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
		gap: var(--s-3);
		margin-bottom: var(--s-3);
	}
	.gw-card {
		border: 1px solid var(--border);
		border-radius: var(--radius);
		background: var(--surface);
		padding: var(--s-3);
	}
	.gw-head {
		display: flex;
		justify-content: space-between;
		align-items: baseline;
		margin-bottom: var(--s-2);
	}
	.gw-xp {
		font-weight: 700;
		font-variant-numeric: tabular-nums;
		color: var(--positive);
	}
	.moves {
		list-style: none;
		margin: 0 0 var(--s-2);
		padding: 0;
		font-size: var(--step--1);
		display: grid;
		gap: var(--s-1);
	}
	.arrow {
		color: var(--giq-rust);
		font-weight: 700;
	}
	.gain {
		color: var(--positive);
		font-weight: 700;
	}
	.hit {
		color: var(--negative);
		font-weight: 700;
	}
	.roll {
		margin-bottom: var(--s-2);
		font-weight: 700;
	}
	.gw-meta {
		margin: 0;
	}
	.totals-line {
		margin: 0;
	}
	.alt-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
		gap: var(--s-3);
		margin-bottom: var(--s-4);
	}
	.alt-card {
		padding: var(--s-4);
	}
	.alt-head {
		display: flex;
		justify-content: space-between;
		align-items: baseline;
		gap: var(--s-2);
		margin: 0 0 var(--s-2);
	}
	.alt-moves {
		font-size: var(--step--1);
		margin: 0 0 var(--s-2);
	}
	.alt-meta {
		margin: 0;
	}
</style>
