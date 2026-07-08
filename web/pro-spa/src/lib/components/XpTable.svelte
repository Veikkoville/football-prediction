<script lang="ts">
	import type { XpResponse, XpPlayer } from '$lib/api';
	import { gwXp } from '$lib/api';
	import ComponentSplit from './ComponentSplit.svelte';
	import MethodNote from './MethodNote.svelte';

	let { data }: { data: XpResponse } = $props();

	const POSITIONS = ['All', 'GKP', 'DEF', 'MID', 'FWD'] as const;
	// Sorttaus (#22): numeeriset laskevaan, tekstit nousevaan järjestykseen.
	const POS_ORDER: Record<string, number> = { GKP: 0, DEF: 1, MID: 2, FWD: 3 };
	const SORTS = {
		total: {
			label: 'Total xP (high to low)',
			cmp: (a: XpPlayer, b: XpPlayer) => b.xp_horizon_total - a.xp_horizon_total
		},
		perGw: {
			label: 'xP per GW (high to low)',
			cmp: (a: XpPlayer, b: XpPlayer) => b.xp_per_gw - a.xp_per_gw
		},
		xmins: {
			label: 'Expected minutes (high to low)',
			cmp: (a: XpPlayer, b: XpPlayer) => b.xmins - a.xmins
		},
		pos: {
			label: 'Position (GKP to FWD)',
			cmp: (a: XpPlayer, b: XpPlayer) =>
				(POS_ORDER[a.pos] ?? 9) - (POS_ORDER[b.pos] ?? 9) ||
				b.xp_horizon_total - a.xp_horizon_total
		},
		team: {
			label: 'Team (A to Z)',
			cmp: (a: XpPlayer, b: XpPlayer) =>
				a.team.localeCompare(b.team) || b.xp_horizon_total - a.xp_horizon_total
		},
		name: {
			label: 'Name (A to Z)',
			cmp: (a: XpPlayer, b: XpPlayer) => a.web_name.localeCompare(b.web_name)
		}
	} as const;

	let pos = $state<(typeof POSITIONS)[number]>('All');
	let sortBy = $state<keyof typeof SORTS>('total');
	let groupByTeam = $state(false);
	let selectedId = $state<number | null>(null);

	let nextGw = $derived(data.meta.next_gameweek);
	let gwCols = $derived(data.players[0]?.gameweeks.map((g) => g.gw) ?? []);
	let horizonN = $derived(data.meta.horizon_gw ?? gwCols.length ?? 6);
	let horizonLabel = $derived(
		gwCols.length > 0 ? `GW${gwCols[0]}–GW${gwCols[gwCols.length - 1]}` : `next ${horizonN} GWs`
	);
	// Kokonais-xP-rank pysyy samana sorttauksesta/ryhmittelystä riippumatta →
	// # on aina "overall xP rank", ei rivin juokseva numero (selkeys #22).
	let rankById = $derived(
		new Map(
			[...data.players]
				.sort((a, b) => b.xp_horizon_total - a.xp_horizon_total)
				.map((p, i) => [p.id, i + 1])
		)
	);
	let pool = $derived(
		data.players
			.filter((p) => pos === 'All' || p.pos === pos)
			.toSorted(SORTS[sortBy].cmp)
	);
	// Joukkueittain-ryhmittely: seurat aakkosin, pelaajat valitussa sortissa.
	let groups = $derived.by(() => {
		if (!groupByTeam) return [{ team: null as string | null, players: pool }];
		const byTeam = new Map<string, XpPlayer[]>();
		for (const p of pool) {
			const list = byTeam.get(p.team) ?? [];
			list.push(p);
			byTeam.set(p.team, list);
		}
		return [...byTeam.entries()]
			.sort(([a], [b]) => a.localeCompare(b))
			.map(([team, players]) => ({ team: team as string | null, players }));
	});
	// Komponenttierittely (#13-pariteetti): vain pelaajat joilla backend
	// tarjoaa components-kentän; defensiivinen jos kenttä puuttuu kokonaan.
	let compPool = $derived(pool.filter((p) => p.components));
	let selected = $derived(
		compPool.find((p) => p.id === selectedId) ?? compPool[0] ?? null
	);
	let compGw = $derived(compPool[0]?.components_gw ?? nextGw);
</script>

<h2>Player expected points, {horizonLabel}</h2>
<p class="muted">
	<strong>Total xP</strong> = the sum of projected points across {horizonLabel}
	({horizonN} gameweeks). <strong>xP/GW</strong> = the per-gameweek average over the same
	horizon. Click a row to see how a player's xP is built.
</p>

<MethodNote summary="How xP is built">
	<p>
		<strong>xP = expected minutes &times; the sum of scoring components</strong> — appearance
		points, goals, assists, clean sheets, saves, defensive contribution and bonus, minus
		cards. The per-GW columns show the same projection fixture by fixture.
	</p>
	<p>
		Team-level inputs (clean sheet probability, expected goals for and against) come from
		the GoalIQ Dixon-Coles match engine — the same model behind our published, pre-match
		logged track record. Player baselines come from each player's per-gameweek history,
		weighted by expected minutes. Defensive contribution is modelled explicitly, which is
		where the projections most often disagree with the eye test.
	</p>
	<p>
		Honesty notes: these are GoalIQ model projections, not FPL's official expected points.
		Pre-season projections lean on last season's baselines until the new season's data
		arrives. Model projections for fun and planning, not betting advice.
	</p>
</MethodNote>

<div class="controls">
	<div>
		<label for="pos">Position</label>
		<select id="pos" bind:value={pos}>
			{#each POSITIONS as p (p)}
				<option value={p}>{p}</option>
			{/each}
		</select>
	</div>
	<div>
		<label for="sort">Sort by</label>
		<select id="sort" bind:value={sortBy}>
			{#each Object.entries(SORTS) as [key, s] (key)}
				<option value={key}>{s.label}</option>
			{/each}
		</select>
	</div>
	<label class="toggle">
		<input type="checkbox" bind:checked={groupByTeam} />
		Group by team
	</label>
</div>

<div class="table-wrap tall">
	<table>
		<thead>
			<tr>
				<th class="num"><abbr title="Overall rank by total xP">#</abbr></th>
				<th>Player</th>
				<th>Team</th>
				<th>Pos</th>
				<th class="num"><abbr title="Expected minutes per gameweek">xMins</abbr></th>
				<th class="num"><abbr title="Average expected points per gameweek">xP/GW</abbr></th>
				<th class="num"><abbr title="Sum of expected points, {horizonLabel}">Total xP</abbr></th>
				{#each gwCols as gw (gw)}
					<th class="num">GW{gw}</th>
				{/each}
			</tr>
		</thead>
		<tbody>
			{#each groups as g (g.team ?? '_all')}
				{#if g.team}
					<tr class="group-row">
						<td colspan={7 + gwCols.length}>{g.team}</td>
					</tr>
				{/if}
				{#each g.players as p (p.id)}
					<tr
						class:selected={selected?.id === p.id}
						onclick={() => (selectedId = p.id)}
					>
						<td class="num muted">{rankById.get(p.id)}</td>
						<td>{p.web_name}</td>
						<td>{p.team_short}</td>
						<td>{p.pos}</td>
						<td class="num">{p.xmins.toFixed(1)}</td>
						<td class="num">{p.xp_per_gw.toFixed(2)}</td>
						<td class="num total-col">{p.xp_horizon_total.toFixed(2)}</td>
						{#each gwCols as gw (gw)}
							<td class="num">{gwXp(p, gw).toFixed(2)}</td>
						{/each}
					</tr>
				{/each}
			{/each}
		</tbody>
	</table>
</div>

{#if compPool.length > 0}
	<h3>How the GW{compGw} xP is built</h3>
	<p class="muted">
		GoalIQ model expected points, split by scoring component. Defensive contribution is
		where the model finds edges the eye test misses. Click a row above or pick a player.
	</p>
	<label for="comp-player">Player</label>
	<select
		id="comp-player"
		class="comp-select"
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
		gap: var(--s-4) var(--s-6);
		align-items: end;
		margin-bottom: var(--s-4);
	}
	.toggle {
		display: flex;
		align-items: center;
		gap: var(--s-2);
		font-size: var(--step--1);
		color: var(--text);
		margin: 0;
		min-height: 44px;
	}
	.toggle input {
		min-height: 0;
		width: 18px;
		height: 18px;
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
	tr.group-row td {
		background: var(--surface-2);
		color: var(--giq-teal);
		font-weight: 700;
		cursor: default;
	}
	td.total-col {
		font-weight: 700;
		color: var(--text);
	}
	.comp-select {
		margin-bottom: var(--s-3);
	}
</style>
