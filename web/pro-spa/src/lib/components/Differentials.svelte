<script lang="ts">
	import { onMount } from 'svelte';
	import { fetchDifferentials, type DifferentialsResponse, type Pos } from '$lib/fantasyTools';

	const POSITIONS = ['All', 'GKP', 'DEF', 'MID', 'FWD'] as const;

	let maxOwnership = $state(10);
	let pos = $state<(typeof POSITIONS)[number]>('All');
	let loading = $state(false);
	let error = $state<string | null>(null);
	let data = $state<DifferentialsResponse | null>(null);

	let maxValid = $derived(maxOwnership > 0 && maxOwnership <= 100);

	async function load() {
		if (!maxValid || loading) return;
		loading = true;
		error = null;
		try {
			data = await fetchDifferentials(maxOwnership, pos === 'All' ? null : (pos as Pos));
		} catch (err) {
			data = null;
			error = err instanceof Error ? err.message : String(err);
		}
		loading = false;
	}

	function apply(e: SubmitEvent) {
		e.preventDefault();
		void load();
	}

	// Ensimmäinen haku oletusfilttereillä heti kun komponentti on näkyvissä
	onMount(() => {
		void load();
	});
</script>

<h2><abbr title="A differential: low ownership, high projected points">Differentials</abbr></h2>
<p class="muted">
	Low-ownership players with high projected points: where the GoalIQ model disagrees with
	the crowd. Ownership comes from the FPL game, projections from the GoalIQ model.
</p>

<form class="diff-form" onsubmit={apply}>
	<div>
		<label for="diff-max">Max ownership %</label>
		<input
			id="diff-max"
			type="number"
			min="1"
			max="100"
			step="1"
			bind:value={maxOwnership}
		/>
	</div>
	<div>
		<label for="diff-pos">Position</label>
		<select id="diff-pos" bind:value={pos}>
			{#each POSITIONS as p (p)}
				<option value={p}>{p}</option>
			{/each}
		</select>
	</div>
	<button class="secondary" type="submit" disabled={!maxValid || loading}>
		{loading ? 'Searching…' : 'Update'}
	</button>
</form>

{#if error}
	<p class="banner error">{error}</p>
{:else if !data}
	<p class="muted">Loading differentials…</p>
{:else if data.players.length === 0}
	<p class="muted">No players under {maxOwnership}% ownership match. Try a higher limit.</p>
{:else}
	<div class="table-wrap">
		<table>
			<thead>
				<tr>
					<th class="num">#</th>
					<th>Player</th>
					<th>Team</th>
					<th>Pos</th>
					<th class="num">Price</th>
					<th class="num"><abbr title="Effective ownership in the FPL game">Owned %</abbr></th>
					<th class="num"><abbr title="Average expected points per gameweek">xP/GW</abbr></th>
					<th class="num"
						><abbr title="Sum of expected points, next {data.meta.horizon_gw ?? 6} gameweeks"
							>Total xP</abbr
						></th
					>
				</tr>
			</thead>
			<tbody>
				{#each data.players as p, i (p.id)}
					<tr>
						<td class="num muted">{i + 1}</td>
						<td>{p.web_name}</td>
						<td>{p.team_short}</td>
						<td>{p.pos}</td>
						<td class="num">{p.price.toFixed(1)}</td>
						<td class="num">{p.owned_pct.toFixed(1)}</td>
						<td class="num">{p.xp_per_gw.toFixed(2)}</td>
						<td class="num total-col">{p.xp_horizon_total.toFixed(2)}</td>
					</tr>
				{/each}
			</tbody>
		</table>
	</div>
{/if}

<style>
	.diff-form {
		display: flex;
		flex-wrap: wrap;
		gap: var(--s-3);
		align-items: end;
		margin-bottom: var(--s-4);
	}
	#diff-max {
		width: 130px;
	}
	td.total-col {
		font-weight: 700;
		color: var(--text);
	}
</style>
