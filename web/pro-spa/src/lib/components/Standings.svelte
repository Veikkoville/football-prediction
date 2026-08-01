<script lang="ts">
	/**
	 * Sarjataulukko webiin (28.7, pariteetti mobiilin StandingsScreenin kanssa).
	 *
	 * Mobiilissa tämä on kirjautumisen takana ("Sign in to view standings").
	 * Webissä EI ole: sarjataulukko on julkista tietoa, ja kirjautumisseinä
	 * hyödyttömän datan edessä on juuri se kitka joka ajaa kävijän pois
	 * hakutulossivulta. Ero on tietoinen, ei vahinko.
	 */
	import { fetchLeagues, fetchStandings, type StandingsRow } from '$lib/api';

	// 1.8.2026: kausi resolvoidaan kalenterista (elo-touko), ei kovakoodata.
	// Valikosta puuttui 2026/27 kokonaan ja oletus oli jumissa 25/26:ssa, joten
	// web ei pystynyt näyttämään kuluvaa kautta lainkaan. Sama sääntö kuin
	// mobiilin lib/season.ts:ssä: kuukaudet 8-12 -> alkava kausi.
	function currentSeasonCode(now = new Date()): string {
		const y = now.getUTCFullYear() % 100;
		const start = now.getUTCMonth() + 1 >= 8 ? y : y - 1;
		return `${String(start).padStart(2, '0')}${String(start + 1).padStart(2, '0')}`;
	}

	let leagues = $state<string[]>([]);
	let league = $state('ENG-Premier League');
	let season = $state(currentSeasonCode());
	let rows = $state<StandingsRow[]>([]);
	let loading = $state(true);
	let error = $state<string | null>(null);

	$effect(() => {
		fetchLeagues().then(
			(l) => {
				leagues = [
					...(l.top5_xg_leagues ?? []),
					...(l.uefa_tournaments ?? []),
					...(l.other_leagues ?? [])
				];
			},
			() => (leagues = ['ENG-Premier League'])
		);
	});

	$effect(() => {
		const lg = league;
		const se = season;
		loading = true;
		error = null;
		fetchStandings(lg, se).then(
			(d) => {
				rows = d.rows ?? [];
				loading = false;
			},
			() => {
				rows = [];
				error = 'Could not load the table right now. Please try again shortly.';
				loading = false;
			}
		);
	});
</script>

<h2>League tables</h2>
<p class="muted lede">
	Final positions, goal difference and points. The same source the model reads when it rates a
	fixture.
</p>

<div class="controls">
	<div class="field">
		<label for="st-league">League</label>
		<select id="st-league" bind:value={league}>
			{#each leagues as l (l)}
				<option value={l}>{l}</option>
			{/each}
		</select>
	</div>
	<div class="field">
		<label for="st-season">Season</label>
		<select id="st-season" bind:value={season}>
			<option value="2627">2026/27</option>
			<option value="2526">2025/26</option>
			<option value="2425">2024/25</option>
			<option value="2324">2023/24</option>
		</select>
	</div>
</div>

{#if error}
	<p class="banner">{error}</p>
{:else if loading}
	<p class="muted">Loading…</p>
{:else if rows.length === 0}
	<p class="muted">No table available for this league and season yet.</p>
{:else}
	<div class="table-wrap">
		<table>
			<thead>
				<tr>
					<th scope="col" class="num">#</th>
					<th scope="col">Team</th>
					<th scope="col" class="num">P</th>
					<th scope="col" class="num">W</th>
					<th scope="col" class="num">D</th>
					<th scope="col" class="num">L</th>
					<th scope="col" class="num">GF</th>
					<th scope="col" class="num">GA</th>
					<th scope="col" class="num">GD</th>
					<th scope="col" class="num">Pts</th>
				</tr>
			</thead>
			<tbody>
				{#each rows as r (r.position)}
					<tr>
						<td class="num">{r.position}</td>
						<th scope="row">{r.team_short_name || r.team_name}</th>
						<td class="num">{r.played_games}</td>
						<td class="num">{r.won}</td>
						<td class="num">{r.draw}</td>
						<td class="num">{r.lost}</td>
						<td class="num">{r.goals_for}</td>
						<td class="num">{r.goals_against}</td>
						<td class="num">{r.goal_difference > 0 ? '+' : ''}{r.goal_difference}</td>
						<td class="num pts">{r.points}</td>
					</tr>
				{/each}
			</tbody>
		</table>
	</div>
{/if}

<style>
	.lede {
		max-width: 62ch;
	}
	.controls {
		display: flex;
		flex-wrap: wrap;
		gap: var(--s-3);
		margin: var(--s-5) 0 var(--s-4);
	}
	.field {
		display: flex;
		flex-direction: column;
		gap: 4px;
		min-width: 180px;
	}
	.field label {
		font-size: var(--step--1);
		color: var(--text-muted);
		font-weight: 700;
	}
	.field select {
		min-height: 44px;
		padding: 0 0.7em;
		border: 1px solid var(--border);
		border-radius: var(--radius);
		background: var(--surface);
		color: var(--text);
		font: inherit;
	}
	.banner {
		border: 1px solid var(--border);
		border-radius: var(--radius);
		padding: var(--s-3) var(--s-4);
		max-width: 62ch;
	}
	/* Leveä taulukko vierii omassa laatikossaan, sivun runko ei koskaan. */
	.table-wrap {
		overflow-x: auto;
	}
	table {
		border-collapse: collapse;
		width: 100%;
		min-width: 560px;
	}
	th,
	td {
		padding: 7px 10px;
		border-bottom: 1px solid var(--border);
		text-align: left;
	}
	thead th {
		font-size: var(--step--1);
		color: var(--text-muted);
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}
	.num {
		text-align: right;
		font-variant-numeric: tabular-nums;
	}
	.pts {
		font-weight: 700;
	}
</style>
