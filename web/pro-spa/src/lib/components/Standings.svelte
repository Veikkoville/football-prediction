<script lang="ts">
	/**
	 * Sarjataulukko webiin (28.7, pariteetti mobiilin StandingsScreenin kanssa).
	 *
	 * Mobiilissa tämä on kirjautumisen takana ("Sign in to view standings").
	 * Webissä EI ole: sarjataulukko on julkista tietoa, ja kirjautumisseinä
	 * hyödyttömän datan edessä on juuri se kitka joka ajaa kävijän pois
	 * hakutulossivulta. Ero on tietoinen, ei vahinko.
	 */
	import { fetchStandings, type StandingsRow } from '$lib/api';
	// 1.8.2026: kausi resolvoidaan kalenterista (elo-touko), ei kovakoodata.
	// Valikosta puuttui 2026/27 kokonaan ja oletus oli jumissa 25/26:ssa, joten
	// web ei pystynyt näyttämään kuluvaa kautta lainkaan. Logiikka asuu nyt
	// $lib/leagues.ts:ssä, koska oikea kausikoodi riippuu liigasta (BSA =
	// kalenterivuosi, '26' eikä '2627').
	import { STANDINGS_LEAGUES, seasonChoices, defaultSeason } from '$lib/leagues';

	let league = $state('ENG-Premier League');
	let season = $state(defaultSeason('ENG-Premier League'));
	let rows = $state<StandingsRow[]>([]);
	let loading = $state(true);
	let error = $state<string | null>(null);

	let seasons = $derived(seasonChoices(league));

	/** Liigan vaihto siirtää kauden uuden liigan koodiavaruuteen. Tavallinen
	 *  funktio tarkoituksella: kaksi $effectiä jotka lukevat ja kirjoittavat
	 *  samaa statea tappaisi sidonnan hiljaa (todettu 3.8). */
	function selectLeague(code: string) {
		league = code;
		if (!seasonChoices(code).some((s) => s.value === season)) {
			season = defaultSeason(code);
		}
	}

	$effect(() => {
		const lg = league;
		const se = season;
		loading = true;
		error = null;
		// 16.8: vanhentuneen vastauksen vahti (pinta-pariteetti mobiilin kanssa).
		// Ilman tata kaksi nopeaa liiganvaihtoa ratkeaa saapumisjarjestyksessa:
		// hitaampi VANHEMPI vastaus kirjoittaa rivit viimeisena ja taulukko
		// nayttaa eri liigaa kuin valitsin. Mobiilissa tama nakyi niin etta
		// jokainen liiga naytti Valioliigaa (Villen havainto 16.8).
		//
		// Ehto on "onko tama viela valittu liiga ja kausi", EI juokseva numero:
		// numerovahti hylkaisi myos paallekkaiset haut samalle liigalle, ja
		// hylatty vastaus jattaisi edellisen liigan rivit ruudulle.
		const isCurrent = () => lg === league && se === season;
		fetchStandings(lg, se).then(
			(d) => {
				if (!isCurrent()) return;
				rows = d.rows ?? [];
				loading = false;
			},
			() => {
				if (!isCurrent()) return;
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
		<select
			id="st-league"
			value={league}
			onchange={(e) => selectLeague(e.currentTarget.value)}
		>
			{#each STANDINGS_LEAGUES as l (l.code)}
				<option value={l.code}>{l.label}</option>
			{/each}
		</select>
	</div>
	<div class="field">
		<label for="st-season">Season</label>
		<select id="st-season" bind:value={season}>
			{#each seasons as s (s.value)}
				<option value={s.value}>{s.label}</option>
			{/each}
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
