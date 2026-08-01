<script lang="ts">
	// Edge-sprint kohta 8: rank-tietoinen kerros (premium). Toggle protect/climb:
	// protect painottaa korkeaa EO:ta (suojaa rankia), climb kääntää painon
	// differentiaaleihin. entry pakollinen (backend vaatii); ilman tallennettua
	// entryä näytetään kehote. Esikaudella backend palauttaa 404 + selitteen.
	import {
		fetchEdge,
		type EdgeMode as Mode,
		type EdgeResponse
	} from '$lib/fantasyTools';
	import { capture } from '$lib/analytics';
	import { fplEntry, persistEntry } from '$lib/fplEntry.svelte';
	import MethodNote from './MethodNote.svelte';
	import ModelWorking from './ModelWorking.svelte';

	const WORKING_STEPS = [
		'Fetching your FPL squad and rank',
		'Weighing captains by effective ownership',
		'Scanning differentials and template risks'
	];

	let mode = $state<Mode>('protect');
	let loading = $state(false);
	let error = $state<string | null>(null);
	let data = $state<EdgeResponse | null>(null);

	let entryValid = $derived(/^\d{1,10}$/.test(fplEntry.entry.trim()));

	async function run() {
		if (!entryValid || loading) return;
		loading = true;
		error = null;
		try {
			const id = Number(fplEntry.entry.trim());
			data = await fetchEdge(id, mode);
			void persistEntry(id); // #66: talteen vasta onnistuneesta hausta
		} catch (err) {
			data = null;
			error = err instanceof Error ? err.message : String(err);
		}
		loading = false;
	}

	function setMode(m: Mode) {
		if (mode === m) return;
		mode = m;
		capture('edge_mode_toggled', { source: 'pro_spa', mode: m });
		// Data on mode-riippuvaista → hae uudelleen jos entry on jo annettu
		if (entryValid && (data || error)) void run();
	}
</script>

<h2>Edge mode: play your rank, not just the points</h2>
<p class="muted">
	Two ways to weigh the same projections. <strong>Protect</strong> leans on highly owned
	captains and flags template players you are missing (limits how far a bad week drops
	you). <strong>Climb</strong> leans on low-ownership upside to gain places. Same xP
	model underneath, only the ownership weighting flips.
</p>

<div class="mode-row" role="group" aria-label="Edge mode">
	<button
		type="button"
		class="mode-btn"
		class:active={mode === 'protect'}
		aria-pressed={mode === 'protect'}
		onclick={() => setMode('protect')}
	>
		Protect my rank
	</button>
	<button
		type="button"
		class="mode-btn"
		class:active={mode === 'climb'}
		aria-pressed={mode === 'climb'}
		onclick={() => setMode('climb')}
	>
		Climb the ranks
	</button>
</div>

<form
	class="edge-form"
	onsubmit={(e) => {
		e.preventDefault();
		void run();
	}}
>
	<div>
		<label for="edge-entry">FPL entry ID</label>
		<input
			id="edge-entry"
			inputmode="numeric"
			autocomplete="off"
			placeholder="e.g. 1234567"
			bind:value={fplEntry.entry}
		/>
	</div>
	<button class="primary" type="submit" disabled={!entryValid || loading}>
		{loading ? 'Analysing…' : 'Analyse my edge'}
	</button>
</form>
{#if !entryValid}
	<p class="muted hint">
		This tool needs your public FPL entry ID (the number in your Points page URL) so it
		can compare your squad against the field. FPL publishes squads only after the
		Gameweek 1 deadline.
	</p>
{/if}

{#if loading}
	<ModelWorking steps={WORKING_STEPS} />
{/if}

{#if error}
	<p class="banner error">{error}</p>
{:else if data}
	<p class="muted rank-line">
		GW{data.meta.gw} · mode: <strong>{data.meta.mode}</strong>{#if data.meta.overall_rank != null}
			· your overall rank: <strong>{data.meta.overall_rank.toLocaleString('en-GB')}</strong>{/if}
	</p>

	{#if data.captain_top5.length > 0}
		<h3>Captains, ownership-weighted</h3>
		<div class="table-wrap">
			<table>
				<thead>
					<tr>
						<th class="num">#</th>
						<th>Player</th>
						<th>Team</th>
						<th class="num"><abbr title="Projected points for the gameweek">GW xP</abbr></th>
						<th class="num"><abbr title="Share of FPL managers who own the player">Own %</abbr></th>
						<th class="num"><abbr title="xP weighted by ownership in the selected mode">Score</abbr></th>
						<th>Why</th>
					</tr>
				</thead>
				<tbody>
					{#each data.captain_top5 as c, i (c.id)}
						<tr>
							<td class="num">{i + 1}</td>
							<td>{c.web_name}</td>
							<td>{c.team_short}</td>
							<td class="num">{c.gw_xp.toFixed(2)}</td>
							<td class="num">{c.owned_pct.toFixed(1)}</td>
							<td class="num score-col">{c.score.toFixed(2)}</td>
							<td class="why">{c.rationale}</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	{/if}

	{#if data.differentials.length > 0}
		<h3>Differentials you do not own</h3>
		<ul class="edge-list">
			{#each data.differentials as p (p.id)}
				<li>
					<span class="edge-name"
						>{p.web_name} <span class="muted">({p.team_short}{#if p.price != null},
								{p.price.toFixed(1)}m{/if})</span></span
					>
					<span class="edge-facts muted"
						>{p.owned_pct.toFixed(1)}% owned{#if p.xp_horizon_total != null}
							· {p.xp_horizon_total.toFixed(1)} xP over the horizon{/if}</span
					>
					<span class="edge-why">{p.rationale}</span>
				</li>
			{/each}
		</ul>
	{/if}

	{#if data.template_risks.length > 0}
		<h3>Template risks: popular players you are missing</h3>
		<ul class="edge-list risk">
			{#each data.template_risks as p (p.id)}
				<li>
					<span class="edge-name"
						>{p.web_name} <span class="muted">({p.team_short}{#if p.price != null},
								{p.price.toFixed(1)}m{/if})</span></span
					>
					<span class="edge-facts muted"
						>{p.owned_pct.toFixed(1)}% owned{#if p.xp_horizon_total != null}
							· {p.xp_horizon_total.toFixed(1)} xP over the horizon{/if}</span
					>
					<span class="edge-why">{p.rationale}</span>
				</li>
			{/each}
		</ul>
	{/if}

	<MethodNote summary="How the weighting works (honest MVP)">
		<p>
			{data.meta.formula ??
				'Captain score weighs projected points by effective ownership: towards the crowd in protect, away from it in climb.'}
		</p>
		<p>
			An honest heuristic, not a rank simulation. GoalIQ model projections, for fun and
			planning, not betting advice.
		</p>
	</MethodNote>
{/if}

<style>
	.mode-row {
		display: flex;
		flex-wrap: wrap;
		gap: var(--s-2);
		margin-bottom: var(--s-4);
	}
	.mode-btn {
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: var(--radius);
		color: var(--text-muted);
		font-size: var(--step--1);
		font-weight: 700;
		padding: 0.5em 1.2em;
	}
	.mode-btn:hover {
		color: var(--text);
		border-color: var(--text-muted);
	}
	/* 26.7 classic: outline, ei täyttöä */
	.mode-btn.active {
		background: transparent;
		border-color: var(--accent);
		color: var(--accent-strong);
	}
	.edge-form {
		display: flex;
		flex-wrap: wrap;
		gap: var(--s-3);
		align-items: end;
		margin-bottom: var(--s-3);
	}
	.hint {
		margin: 0 0 var(--s-4);
	}
	.rank-line {
		margin-bottom: var(--s-3);
	}
	.score-col {
		font-weight: 700;
	}
	.why {
		white-space: normal;
		min-width: 220px;
		font-size: var(--step--1);
		color: var(--text-muted);
	}
	.edge-list {
		list-style: none;
		margin: 0 0 var(--s-4);
		padding: 0;
		display: grid;
		gap: var(--s-2);
		max-width: 680px;
	}
	.edge-list li {
		border: 1px solid var(--border);
		border-left: 4px solid var(--giq-teal-deep);
		border-radius: var(--radius);
		background: var(--surface);
		padding: var(--s-2) var(--s-3);
		display: grid;
		gap: 2px;
	}
	.edge-list.risk li {
		border-left-color: var(--giq-coral);
	}
	.edge-name {
		font-weight: 700;
	}
	.edge-facts {
		font-size: var(--step--1);
	}
	.edge-why {
		font-size: var(--step--1);
	}
</style>
