<script lang="ts">
	import type { XpResponse, XpPlayer } from '$lib/api';
	import { gwXp } from '$lib/api';
	import ComponentSplit from './ComponentSplit.svelte';

	let { data }: { data: XpResponse } = $props();

	const POSITIONS = ['All', 'GKP', 'DEF', 'MID', 'FWD'] as const;
	const SORTS = {
		total: { label: 'Total xP (horizon)', key: (p: XpPlayer) => p.xp_horizon_total },
		perGw: { label: 'xP per GW', key: (p: XpPlayer) => p.xp_per_gw },
		xmins: { label: 'Expected minutes', key: (p: XpPlayer) => p.xmins }
	} as const;

	let pos = $state<(typeof POSITIONS)[number]>('All');
	let sortBy = $state<keyof typeof SORTS>('total');
	let selectedId = $state<number | null>(null);

	let nextGw = $derived(data.meta.next_gameweek);
	let gwCols = $derived(data.players[0]?.gameweeks.map((g) => g.gw) ?? []);
	let pool = $derived(
		data.players
			.filter((p) => pos === 'All' || p.pos === pos)
			.toSorted((a, b) => SORTS[sortBy].key(b) - SORTS[sortBy].key(a))
	);
	// Komponenttierittely (#13-pariteetti): vain pelaajat joilla backend
	// tarjoaa components-kentän; defensiivinen jos kenttä puuttuu kokonaan.
	let compPool = $derived(pool.filter((p) => p.components));
	let selected = $derived(
		compPool.find((p) => p.id === selectedId) ?? compPool[0] ?? null
	);
	let compGw = $derived(compPool[0]?.components_gw ?? nextGw);
</script>

<h2>Player expected points, next {data.meta.horizon_gw ?? 6} gameweeks</h2>

<div class="controls">
	<div>
		<label for="pos">Position</label>
		<select id="pos" bind:value={pos}>
			{#each POSITIONS as p (p)}
				<option value={p}>{p}</option>
			{/each}
		</select>
	</div>
	<fieldset>
		<legend>Sort by</legend>
		{#each Object.entries(SORTS) as [key, s] (key)}
			<label class="radio">
				<input type="radio" name="sort" value={key} bind:group={sortBy} />
				{s.label}
			</label>
		{/each}
	</fieldset>
</div>

<div class="table-wrap tall">
	<table>
		<thead>
			<tr>
				<th class="num">#</th>
				<th>Player</th>
				<th>Team</th>
				<th>Pos</th>
				<th class="num">xMins</th>
				<th class="num">xP/GW</th>
				<th class="num">Total</th>
				{#each gwCols as gw (gw)}
					<th class="num">GW{gw}</th>
				{/each}
			</tr>
		</thead>
		<tbody>
			{#each pool as p, i (p.id)}
				<tr
					class:selected={selected?.id === p.id}
					onclick={() => (selectedId = p.id)}
				>
					<td class="num">{i + 1}</td>
					<td>{p.web_name}</td>
					<td>{p.team_short}</td>
					<td>{p.pos}</td>
					<td class="num">{p.xmins.toFixed(1)}</td>
					<td class="num">{p.xp_per_gw.toFixed(2)}</td>
					<td class="num">{p.xp_horizon_total.toFixed(2)}</td>
					{#each gwCols as gw (gw)}
						<td class="num">{gwXp(p, gw).toFixed(2)}</td>
					{/each}
				</tr>
			{/each}
		</tbody>
	</table>
</div>

{#if compPool.length > 0}
	<h3>Where the GW{compGw} xP comes from</h3>
	<p class="muted">
		GoalIQ model expected points, split by scoring component. Defensive contribution is
		where the model finds edges the eye test misses. Click a row above or pick a player.
	</p>
	<label for="comp-player">Player</label>
	<select
		id="comp-player"
		value={selected?.id}
		onchange={(e) => (selectedId = Number(e.currentTarget.value))}
	>
		{#each compPool as p (p.id)}
			<option value={p.id}>{p.web_name} ({p.team_short}, {p.pos})</option>
		{/each}
	</select>
	{#if selected}
		<ComponentSplit player={selected} />
	{/if}
	<p class="muted">Differentials (xP vs ownership) come in Phase 2.</p>
{:else}
	<p class="muted">
		Per-gameweek xP columns = the per-GW breakdown. Differentials (xP vs ownership) come
		in Phase 2.
	</p>
{/if}

<style>
	.controls {
		display: flex;
		flex-wrap: wrap;
		gap: var(--s-6);
		align-items: end;
		margin-bottom: var(--s-4);
	}
	fieldset {
		border: none;
		padding: 0;
		margin: 0;
		display: flex;
		gap: var(--s-4);
		flex-wrap: wrap;
	}
	legend {
		font-size: var(--step--1);
		color: var(--text-muted);
		padding: 0;
		margin-bottom: var(--s-1);
	}
	.radio {
		display: flex;
		align-items: center;
		gap: var(--s-1);
		font-size: var(--step--1);
		color: var(--text);
		margin: 0;
	}
	.radio input {
		min-height: 0;
		accent-color: var(--accent);
	}
	.tall {
		max-height: 640px;
		overflow-y: auto;
	}
	tbody tr {
		cursor: pointer;
	}
	tr.selected td {
		background: rgba(255, 46, 126, 0.1);
	}
	select {
		margin-bottom: var(--s-3);
	}
</style>
