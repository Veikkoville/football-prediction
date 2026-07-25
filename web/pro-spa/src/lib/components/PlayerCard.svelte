<script lang="ts">
	// UX-palaute-erä (25.7) kohta 1: player card / hakutietopankki
	// (Dubravka-case). FREE — kaikki kortin data on julkista (FPL bootstrap +
	// julkaistut GoalIQ-projektiot). Rehellisyysraja pidetään visuaalisesti:
	// "Official FPL status" -blokki = FPL:n virallinen fakta (status, news,
	// keltaiset, set-piece-listat), "GoalIQ model view" -blokki = mallin
	// estimaatti (p_start, confidence, data_basis, xP). Defensiiviset luvut:
	// vanha payload ilman uusia kenttiä ei kaada mitään.
	import { fetchXp, type XpMeta, type XpPlayer } from '$lib/api';
	// Free-tier-rajaus (Villen havainto 25.7): xP-numerot ovat premium-arvoa
	// kaikkialla muualla -> kortti nayttaa ne vain premium-pinnalta (ProTools).
	let { premium = false }: { premium?: boolean } = $props();
	import { capture } from '$lib/analytics';
	import PlayerSearch from './PlayerSearch.svelte';
	import SetPieceBadges from './SetPieceBadges.svelte';

	let pool = $state<XpPlayer[]>([]);
	let meta = $state<XpMeta | null>(null);
	let poolError = $state(false);
	$effect(() => {
		fetchXp().then(
			(d) => {
				pool = d.players ?? [];
				meta = d.meta ?? null;
			},
			() => (poolError = true)
		);
	});

	let query = $state('');
	let player = $state<XpPlayer | null>(null);

	// Sama normalisointi kuin FitChecker/XpTable-haussa (#145/#147-pariteetti).
	function norm(s: string): string {
		return s
			.normalize('NFD')
			.replace(/[̀-ͯ]/g, '')
			.toLowerCase()
			.replace(/ø/g, 'o')
			.replace(/['’ʼ]/g, '')
			.replace(/[-.]/g, ' ')
			.trim();
	}
	const matches = $derived.by(() => {
		const q = norm(query);
		if (q.length < 2) return [];
		return pool
			.filter(
				(p) =>
					norm(p.web_name).includes(q) ||
					(p.full_name ? norm(p.full_name).includes(q) : false) ||
					norm(p.team_short).includes(q)
			)
			.slice(0, 8);
	});

	function select(p: XpPlayer) {
		player = p;
		query = '';
		// Ei PII:tä: pelaaja-ID/positio/status ovat julkista FPL-dataa.
		capture('player_card_viewed', { player_id: p.id, pos: p.pos, status: p.status ?? 'a' });
	}

	// Virallinen FPL-status → label + sävy (EI mallin päättelyä).
	const STATUS_LABEL: Record<string, string> = {
		a: 'Available',
		d: 'Doubtful',
		i: 'Injured',
		s: 'Suspended',
		u: 'Unavailable',
		n: 'Not available'
	};
	const st = $derived(player?.status ?? 'a');
	const statusTone = $derived(st === 'a' ? 'ok' : st === 'd' ? 'warn' : 'out');

	// Pre-season: bootstrapin yellow_cards on vielä EDELLISEN kauden lukema
	// (contract-data.md luku 5) → rehellinen "last season" -label ilman
	// kynnyslaskentaa. Live-kaudella 5/10/15-kynnykset (5 keltaista = 1 GW:n
	// pelikielto, sääntö voimassa GW19 asti; 10 = 2 GW; 15 = 3 GW).
	const preseason = $derived(meta?.data_coverage?.baseline_mode === 'prev_season_archive');
	function suspensionLine(y: number): string {
		if (y < 5) return 'next suspension at 5 yellows (1-match ban, threshold applies until GW19)';
		if (y < 10) return 'next suspension at 10 yellows (2-match ban)';
		if (y < 15) return 'next suspension at 15 yellows (3-match ban)';
		return 'past the 15-yellow line (3-match ban)';
	}

	const spListed = $derived.by(() => {
		const sp = player?.set_pieces;
		if (!sp) return false;
		return [sp.pens, sp.corners, sp.fk].some((v) => typeof v === 'number' && v <= 2);
	});

	const DATA_BASIS_LABEL: Record<string, string> = {
		pl_history: "based on the player's own PL minutes",
		limited_history: 'thin PL sample, the position average carries most of the weight',
		no_history: 'no PL minutes yet, position average only'
	};

	function fixtureLabel(opps: { opp: string; venue: string }[]): string {
		if (opps.length === 0) return 'Blank';
		return opps.map((o) => `${o.opp} (${o.venue})`).join(', ');
	}
</script>

<h2>Player card</h2>
<p class="muted">
	Free · Look up any covered player: the official FPL availability news side by side with
	the GoalIQ model's view on starting and projected points. Official data comes straight
	from the FPL API and refreshes with the daily projection build.
</p>

{#if poolError}
	<p class="banner error">Could not load the player pool right now. Please try again shortly.</p>
{:else}
	<PlayerSearch id="pc-search" label="Find a player" bind:query items={matches} onSelect={select} />

	{#if player}
		<article class="pc card">
			<header class="pc-head">
				<h3 class="pc-name">{player.web_name}</h3>
				<p class="muted pc-sub">
					{#if player.full_name && player.full_name !== player.web_name}{player.full_name}
						·{/if}
					{player.team} · {player.pos}{#if typeof player.price === 'number' && player.price > 0}
						· {player.price.toFixed(1)}m{/if}{#if typeof player.owned_pct === 'number'}
						· owned by {player.owned_pct.toFixed(1)}%{/if}
				</p>
			</header>

			<div class="pc-grid">
				<section class="pc-block">
					<h4>Official FPL status <span class="src">source: FPL</span></h4>
					<p class="status-line">
						<span class="chip {statusTone}">{STATUS_LABEL[st] ?? st.toUpperCase()}</span>
						{#if player.chance_next != null && st !== 'a'}
							<span>{player.chance_next}% chance of playing the next round</span>
						{/if}
					</p>
					{#if player.news}
						<p class="news">{player.news}</p>
					{:else if st === 'a'}
						<p class="muted">No flags right now.</p>
					{/if}
					{#if typeof player.yellows === 'number'}
						{#if preseason}
							<p class="muted">
								{player.yellows} yellow {player.yellows === 1 ? 'card' : 'cards'} last season
								(FPL data). Booking counts reset for the new season.
							</p>
						{:else}
							<p class="muted">
								{player.yellows}
								{player.yellows === 1 ? 'yellow' : 'yellows'}, {suspensionLine(player.yellows)}.
							</p>
						{/if}
					{/if}
					{#if player.set_pieces}
						{#if spListed}
							<p class="muted sp-line">Set pieces: <SetPieceBadges sp={player.set_pieces} /></p>
						{:else}
							<p class="muted">No penalty, corner or free-kick duties in FPL's lists.</p>
						{/if}
					{/if}
				</section>

				<section class="pc-block model">
					<h4>GoalIQ model view <span class="src">estimate, not team news</span></h4>
					{#if typeof player.p_start === 'number'}
						<p class="start-line">
							<span class="brand big">{Math.round(player.p_start * 100)}%</span>
							chance of starting the next gameweek{#if player.minutes_confidence}
								<span class="muted">({player.minutes_confidence} confidence)</span>{/if}
						</p>
					{:else if typeof player.predicted_starts === 'number'}
						<p class="start-line">
							<span class="brand big">{Math.round(player.predicted_starts)}%</span>
							chance of starting the next gameweek{#if player.minutes_confidence}
								<span class="muted">({player.minutes_confidence} confidence)</span>{/if}
						</p>
					{/if}
					{#if player.data_basis}
						<p class="muted">
							The model's view on starting, {DATA_BASIS_LABEL[player.data_basis] ??
								player.data_basis}.
						</p>
					{/if}
					{#if premium}
						<p>
							<strong>{player.xp_horizon_total.toFixed(1)} xP</strong> projected over the next
							{player.gameweeks.length} gameweeks ({player.xp_per_gw.toFixed(1)} per GW).
						</p>
					{:else}
						<p class="muted">
							Projected points for this player are part of GoalIQ Premium. The start
							chance and official status here are free.
						</p>
					{/if}
				</section>
			</div>

			{#if premium}
			<h4 class="gw-title">Projected points by gameweek</h4>
			<div class="table-wrap">
				<table>
					<thead>
						<tr>
							<th>GW</th>
							<th>Fixture</th>
							<th class="num"><abbr title="Expected points from the GoalIQ match model">xP</abbr></th>
						</tr>
					</thead>
					<tbody>
						{#each player.gameweeks as g (g.gw)}
							<tr>
								<td>GW{g.gw}</td>
								<td class:muted={g.opponents.length === 0}>{fixtureLabel(g.opponents)}</td>
								<td class="num">{g.xp.toFixed(2)}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
			{/if}
			<p class="muted disclaimer">
				Official status and news are FPL's own data. Starting chance and xP are GoalIQ model
				projections, for fun and planning, not betting advice.
			</p>
		</article>
	{/if}
{/if}

<style>
	.pc {
		max-width: 760px;
		margin-top: var(--s-4);
	}
	.pc-head {
		margin-bottom: var(--s-4);
	}
	.pc-name {
		margin: 0 0 var(--s-1);
		font-size: var(--step-2);
	}
	.pc-sub {
		margin: 0;
	}
	.pc-grid {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
		gap: var(--s-4);
		margin-bottom: var(--s-4);
	}
	/* Fakta vs estimaatti: virallinen blokki neutraalilla paper-pohjalla,
	   malliblokki magenta-aksentilla — sama data ei sekoitu. */
	.pc-block {
		border: 1px solid var(--border);
		border-radius: var(--radius-sm);
		background: var(--surface-2);
		padding: var(--s-3) var(--s-4);
	}
	.pc-block.model {
		background: var(--surface);
		border-left: 4px solid var(--giq-magenta-deep);
	}
	.pc-block h4 {
		margin: 0 0 var(--s-2);
		font-size: var(--step--1);
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.4px;
	}
	.pc-block h4 .src {
		text-transform: none;
		letter-spacing: 0;
		font-weight: 500;
		color: var(--text-muted);
	}
	.status-line {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--s-2);
	}
	.chip {
		display: inline-block;
		padding: 2px 10px;
		border-radius: 999px;
		font-size: var(--step--1);
		font-weight: 700;
		border: 1px solid transparent;
	}
	.chip.ok {
		background: rgba(25, 227, 210, 0.14);
		border-color: rgba(0, 194, 173, 0.45);
		color: var(--giq-ink);
	}
	.chip.warn {
		background: rgba(255, 201, 60, 0.2);
		border-color: rgba(244, 168, 0, 0.5);
		color: var(--giq-ink);
	}
	.chip.out {
		background: rgba(255, 106, 61, 0.12);
		border-color: rgba(194, 65, 12, 0.4);
		color: var(--negative);
	}
	.news {
		font-weight: 600;
	}
	.sp-line {
		display: flex;
		align-items: center;
		gap: 2px;
	}
	.start-line .big {
		font-size: var(--step-2);
		font-weight: 700;
		color: var(--giq-magenta-deep);
		font-variant-numeric: tabular-nums;
		margin-right: 4px;
	}
	.gw-title {
		margin: 0 0 var(--s-2);
		font-size: var(--step--1);
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.4px;
	}
	.disclaimer {
		margin: var(--s-3) 0 0;
	}
</style>
