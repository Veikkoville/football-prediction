<script lang="ts">
	// Edge-sprint kohta 9: mini-league MVP (free). Julkinen liigakoodi →
	// standings (max 1. sivu, 50 riviä, backend-proxy). Kaksi riviä valitsemalla
	// GW-voittotodennäköisyys (/h2h, normaaliapproksimaatio). Liigakoodi
	// persistoituu localStorageen (kevyt MVP, ei tili-tasoa).
	import {
		fetchLeague,
		fetchH2h,
		type H2hResponse,
		type LeagueResponse,
		type LeagueRow
	} from '$lib/fantasyTools';
	import { capture } from '$lib/analytics';
	import RivalPanel from './RivalPanel.svelte';
	import { fplEntry } from '$lib/fplEntry.svelte';

	// UX-palaute-erä (25.7) kohta 5: "Use this team" — FPL:ssä ei ole
	// globaalia nimihakua, joten nimipohjainen joukkueen valinta kulkee
	// liigan standings-rivin kautta: nappi asettaa rivin entry-ID:n jaettuun
	// fplEntry-storeen + autoRunPending → Rate my team ajaa arvion heti.
	// onUseTeam: FreeView vaihtaa segmentin rateteam-paneeliin.
	let { onUseTeam }: { onUseTeam?: () => void } = $props();

	function useTeam(row: LeagueRow) {
		fplEntry.entry = String(row.entry);
		fplEntry.autoRunPending = true;
		// Ei PII:tä eventtiin (entry-ID ei mene mukaan, sama linja kuin muut).
		capture('league_use_team_tapped', { source: 'pro_spa' });
		onUseTeam?.();
	}

	const LS_KEY = 'goaliq.fplLeagueId';

	let leagueId = $state('');
	try {
		const saved = localStorage.getItem(LS_KEY);
		if (saved && /^\d{1,10}$/.test(saved)) leagueId = saved;
	} catch {
		/* fail-safe: storage estetty → kenttä vain tyhjä */
	}

	let loading = $state(false);
	let error = $state<string | null>(null);
	let data = $state<LeagueResponse | null>(null);

	let h2hLoading = $state(false);
	let h2hError = $state<string | null>(null);
	let h2h = $state<H2hResponse | null>(null);
	let selected = $state<LeagueRow[]>([]);

	let idValid = $derived(/^\d{1,10}$/.test(leagueId.trim()));

	async function load(e?: SubmitEvent) {
		e?.preventDefault();
		if (!idValid || loading) return;
		loading = true;
		error = null;
		selected = [];
		h2h = null;
		h2hError = null;
		try {
			data = await fetchLeague(Number(leagueId.trim()));
			try {
				localStorage.setItem(LS_KEY, leagueId.trim());
			} catch {
				/* fail-safe */
			}
			capture('league_viewed', { source: 'pro_spa', standings_n: data.standings.length });
		} catch (err) {
			data = null;
			error = err instanceof Error ? err.message : String(err);
		}
		loading = false;
	}

	// Autoload: tallennettu liigakoodi → standings heti (kuten mobiilin #64-kaava)
	let started = $state(false);
	$effect(() => {
		if (!started) {
			started = true;
			if (idValid) void load();
		}
	});

	async function toggleRow(row: LeagueRow) {
		h2hError = null;
		const idx = selected.findIndex((r) => r.entry === row.entry);
		if (idx >= 0) {
			selected = selected.toSpliced(idx, 1);
			h2h = null;
			return;
		}
		selected = selected.length >= 2 ? [selected[1], row] : [...selected, row];
		h2h = null;
		if (selected.length === 2) {
			h2hLoading = true;
			try {
				h2h = await fetchH2h(selected[0].entry, selected[1].entry);
			} catch (err) {
				h2h = null;
				h2hError = err instanceof Error ? err.message : String(err);
			}
			h2hLoading = false;
		}
	}

	// "Catch your rival": oma entry vs valittu rivi. Erillinen H2H-valinnasta,
	// jotta kaksi eri kysymystä eivät kilpaile samasta klikkauksesta.
	let rivalRow = $state<LeagueRow | null>(null);
	let ownEntry = $derived(
		/^\d{1,10}$/.test((fplEntry.entry || fplEntry.savedEntry || '').trim())
			? Number((fplEntry.entry || fplEntry.savedEntry || '').trim())
			: null
	);

	function isSelected(row: LeagueRow): boolean {
		return selected.some((r) => r.entry === row.entry);
	}

	function rankMove(row: LeagueRow): 'up' | 'down' | 'same' {
		if (!row.last_rank || row.last_rank === row.rank) return 'same';
		return row.rank < row.last_rank ? 'up' : 'down';
	}
</script>

<h2>Mini-league: standings and head-to-head win probabilities</h2>
<p class="muted">
	Paste your classic league's ID (from the league page URL on the FPL site) to see the
	table. Then pick any two managers to get the model's win probability for the next
	gameweek, based on each squad's projected XI points.
</p>

<form class="league-form" onsubmit={load}>
	<div>
		<label for="league-id">FPL league ID</label>
		<input
			id="league-id"
			inputmode="numeric"
			autocomplete="off"
			placeholder="e.g. 314"
			bind:value={leagueId}
		/>
	</div>
	<button class="primary" type="submit" disabled={!idValid || loading}>
		{loading ? 'Loading…' : 'Load league'}
	</button>
</form>

{#if error}
	<p class="banner error">{error}</p>
{:else if data}
	<h3 class="league-name">{data.league.name}</h3>

	{#if data.standings.length === 0}
		<p class="banner success">
			No standings yet: FPL fills league tables once Gameweek 1 has been played. The
			league exists, check back after the first deadline.
		</p>
	{:else}
		<p class="muted">
			Click two rows to compare them head-to-head. "Use this team" loads that manager's
			squad in Rate my team, no entry ID needed.
			{#if data.has_next}Showing the first 50 managers.{/if}
		</p>

		{#if h2hLoading}
			<p class="muted">Crunching the head-to-head…</p>
		{:else if h2hError}
			<p class="banner error">{h2hError}</p>
		{:else if h2h}
			<!-- Voittotodennäköisyyspalkki: A / tasaband / B -->
			<div class="h2h card" aria-label="Head-to-head win probability">
				<p class="h2h-head">
					<strong>{h2h.entry_a.team_name}</strong>
					<span class="muted">vs</span>
					<strong>{h2h.entry_b.team_name}</strong>
					<span class="muted">· GW{h2h.meta.gw}</span>
				</p>
				<div class="h2h-bar" role="img" aria-label="{h2h.entry_a.team_name} {Math.round(h2h.p_a * 100)}%, close band {Math.round(h2h.p_draw_band * 100)}%, {h2h.entry_b.team_name} {Math.round(h2h.p_b * 100)}%">
					<span class="seg a" style="width: {h2h.p_a * 100}%"></span>
					<span class="seg draw" style="width: {h2h.p_draw_band * 100}%"></span>
					<span class="seg b" style="width: {h2h.p_b * 100}%"></span>
				</div>
				<p class="h2h-legend muted">
					<span><span class="dot a"></span>{h2h.entry_a.team_name}
						{Math.round(h2h.p_a * 100)}% ({h2h.entry_a.xi_xp.toFixed(1)} xP)</span>
					<span><span class="dot draw"></span>Too close to call
						{Math.round(h2h.p_draw_band * 100)}%</span>
					<span><span class="dot b"></span>{h2h.entry_b.team_name}
						{Math.round(h2h.p_b * 100)}% ({h2h.entry_b.xi_xp.toFixed(1)} xP)</span>
				</p>
				<p class="muted h2h-note">
					Model estimate from each XI's projected points (captain doubled). "Too close to
					call" covers margins within 3 points. Not betting advice.
				</p>
			</div>
		{/if}

		<div class="table-wrap league-tall">
			<table>
				<thead>
					<tr>
						<th class="num">#</th>
						<th>Team</th>
						<th>Manager</th>
						<th class="num"><abbr title="Points in the latest gameweek">GW</abbr></th>
						<th class="num">Total</th>
						<th></th>
					</tr>
				</thead>
				<tbody>
					{#each data.standings as row (row.entry)}
						<tr
							class:selected={isSelected(row)}
							onclick={() => void toggleRow(row)}
						>
							<td class="num">
								{row.rank}
								{#if rankMove(row) === 'up'}<span class="move up" title="Up from {row.last_rank}">▲</span
									>{:else if rankMove(row) === 'down'}<span class="move down" title="Down from {row.last_rank}">▼</span
									>{/if}
							</td>
							<td>{row.entry_name}</td>
							<td>{row.player_name}</td>
							<td class="num">{row.event_total}</td>
							<td class="num total-col">{row.total}</td>
							<td>
								<!-- Kohta 5: ei osallistu rivin H2H-valintaan (stopPropagation) -->
								<button
									type="button"
									class="use-btn"
									title="Load this manager's squad in Rate my team"
									onclick={(e) => {
										e.stopPropagation();
										useTeam(row);
									}}
								>
									Use this team
								</button>
								{#if ownEntry != null && row.entry !== ownEntry}
									<button
										type="button"
										class="use-btn"
										title="What closing this gap takes"
										onclick={(e) => {
											e.stopPropagation();
											rivalRow = rivalRow?.entry === row.entry ? null : row;
										}}
									>
										{rivalRow?.entry === row.entry ? 'Hide' : 'Catch'}
									</button>
								{/if}
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>

		{#if rivalRow && ownEntry != null && idValid}
			<RivalPanel
				entry={ownEntry}
				rival={rivalRow.entry}
				leagueId={Number(leagueId.trim())}
				rivalName={rivalRow.entry_name}
			/>
		{/if}
	{/if}
{/if}

<style>
	.league-form {
		display: flex;
		flex-wrap: wrap;
		gap: var(--s-3);
		align-items: end;
		margin-bottom: var(--s-4);
	}
	.league-name {
		margin-top: 0;
	}
	.league-tall {
		max-height: 560px;
		overflow-y: auto;
	}
	tbody tr {
		cursor: pointer;
	}
	tr.selected td {
		background: rgba(255, 138, 92, 0.1);
	}
	td.total-col {
		font-weight: 700;
	}
	/* Kohta 5: kompakti rivinappi (taulukkoon sopiva, ei globaali 44px) */
	.use-btn {
		border: 1px solid var(--accent);
		border-radius: var(--radius);
		background: var(--surface);
		color: var(--giq-rust);
		font-weight: 700;
		font-size: var(--step--1);
		padding: 4px 12px;
		min-height: 0;
		cursor: pointer;
		white-space: nowrap;
	}
	.use-btn:hover {
		background: rgba(255, 138, 92, 0.1);
	}
	.move {
		font-size: 0.7em;
		vertical-align: 1px;
	}
	.move.up {
		color: var(--positive);
	}
	.move.down {
		color: var(--negative);
	}
	.h2h {
		max-width: 680px;
		margin-bottom: var(--s-4);
		padding: var(--s-4);
	}
	.h2h-head {
		margin: 0 0 var(--s-2);
	}
	/* 26.7 CLASSIC: palkki oli 18px täyttöä kolmella brändivärillä — ilme
	   sallii värin VIIVANA, ei täyttönä. Sama tieto luetaan 4px:n viivalta,
	   ja prosentit ovat joka tapauksessa legendassa lukuina (= sivun
	   äänekkäin asia). Legendan pallot ovat samasta syystä viivapätkiä. */
	.h2h-bar {
		display: flex;
		height: 4px;
		overflow: hidden;
		margin-bottom: var(--s-3);
	}
	.seg.a,
	.dot.a {
		background: var(--accent);
	}
	.seg.draw,
	.dot.draw {
		background: var(--giq-gold);
	}
	.seg.b,
	.dot.b {
		background: var(--giq-teal-deep);
	}
	.h2h-legend {
		display: flex;
		flex-wrap: wrap;
		gap: var(--s-2) var(--s-4);
		margin: 0 0 var(--s-2);
	}
	.dot {
		display: inline-block;
		width: 14px;
		height: 3px;
		vertical-align: middle;
		margin-right: 6px;
	}
	.h2h-note {
		margin: 0;
	}
</style>
