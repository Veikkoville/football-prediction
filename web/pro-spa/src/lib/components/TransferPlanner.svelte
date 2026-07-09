<script lang="ts">
	import { fetchPlan, type PlanResponse } from '$lib/fantasyTools';
	import MethodNote from './MethodNote.svelte';

	const HORIZONS = [2, 3, 4, 5, 6] as const;
	const FTS = [0, 1, 2, 3, 4, 5] as const;

	let entryInput = $state('');
	let horizon = $state(3);
	let ft = $state(1);
	let loading = $state(false);
	let error = $state<string | null>(null);
	let data = $state<PlanResponse | null>(null);

	let entryValid = $derived(/^\d{1,10}$/.test(entryInput.trim()));

	async function build(e: SubmitEvent) {
		e.preventDefault();
		if (!entryValid || loading) return;
		loading = true;
		error = null;
		try {
			data = await fetchPlan(Number(entryInput.trim()), horizon, ft);
		} catch (err) {
			data = null;
			error = err instanceof Error ? err.message : String(err);
		}
		loading = false;
	}
</script>

<h2>Transfer planner</h2>
<p class="muted">
	A multi-gameweek transfer plan built on the same xP projections as the table above. Pick
	your horizon and how many free transfers you have banked.
</p>

<form class="plan-form" onsubmit={build}>
	<div>
		<label for="plan-entry">FPL entry ID</label>
		<input
			id="plan-entry"
			inputmode="numeric"
			autocomplete="off"
			placeholder="e.g. 1234567"
			bind:value={entryInput}
		/>
	</div>
	<div>
		<label for="plan-horizon"
			><abbr title="How many upcoming gameweeks the plan covers">Horizon</abbr> (GWs)</label
		>
		<select id="plan-horizon" bind:value={horizon}>
			{#each HORIZONS as h (h)}
				<option value={h}>{h}</option>
			{/each}
		</select>
	</div>
	<div>
		<label for="plan-ft">Free transfers</label>
		<select id="plan-ft" bind:value={ft}>
			{#each FTS as f (f)}
				<option value={f}>{f}</option>
			{/each}
		</select>
	</div>
	<button class="primary" type="submit" disabled={!entryValid || loading}>
		{loading ? 'Planning…' : 'Build plan'}
	</button>
</form>

{#if error}
	<p class="banner error">{error}</p>
{:else if data}
	<MethodNote summary="How this plan is built (and its limits)">
		<p>{data.meta.heuristic}</p>
		{#if data.meta.note}
			<p>{data.meta.note}</p>
		{:else}
			<p>GoalIQ model projections, not FPL official; not betting advice.</p>
		{/if}
	</MethodNote>

	<div class="timeline">
		{#each data.plan as g (g.gw)}
			<div class="gw-card card">
				<div class="gw-head">
					<strong>GW{g.gw}</strong>
					<span class="gw-xp">{g.gw_xp.toFixed(1)} xP</span>
				</div>
				{#if g.roll_transfer}
					<p class="muted roll">
						<abbr title="Hold: keep the free transfer this week and bank it for the next one"
							>Roll transfer</abbr
						>
					</p>
				{:else}
					<ul class="moves">
						{#each g.transfers as t (t.out.id + '-' + t.in.id)}
							<li>
								{t.out.web_name} <span class="muted">({t.out.team_short})</span>
								<span class="arrow">→</span>
								{t.in.web_name} <span class="muted">({t.in.team_short})</span>
								<span class="gain">+{t.gain_xp_remaining.toFixed(1)} xP</span>
								{#if t.hit}<span class="hit">{t.hit} hit</span>{/if}
							</li>
						{/each}
					</ul>
				{/if}
				<p class="gw-meta muted">
					Captain: {g.captain.web_name} ({g.captain.gw_xp.toFixed(1)} xP) · FTs left:
					{g.free_transfers_left} · Bank: {g.bank.toFixed(1)}
				</p>
			</div>
		{/each}
	</div>

	<div class="totals card">
		<div class="fact">
			<span class="muted">Plan xP</span>
			<span class="val">{data.totals.plan_xp.toFixed(1)}</span>
		</div>
		<div class="fact">
			<span class="muted">No-transfer baseline</span>
			<span class="val">{data.totals.baseline_xp_no_transfers.toFixed(1)}</span>
		</div>
		<div class="fact">
			<span class="muted">Net gain</span>
			<span class="val gain">
				{data.totals.net_gain >= 0 ? '+' : ''}{data.totals.net_gain.toFixed(1)}
			</span>
		</div>
		<div class="fact">
			<span class="muted">Hits taken</span>
			<span class="val">{data.totals.hits_taken}</span>
		</div>
	</div>
{/if}

<style>
	.plan-form {
		display: flex;
		flex-wrap: wrap;
		gap: var(--s-3);
		align-items: end;
		margin-bottom: var(--s-4);
	}
	.timeline {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
		gap: var(--s-4);
		margin-bottom: var(--s-4);
	}
	.gw-card {
		padding: var(--s-4);
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
		color: var(--giq-magenta-deep);
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
	.totals {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
		gap: var(--s-3);
		padding: var(--s-4);
		max-width: 640px;
	}
	.fact {
		display: grid;
		gap: 2px;
	}
	.fact .val {
		font-weight: 700;
		font-variant-numeric: tabular-nums;
	}
</style>
