<script lang="ts">
	/**
	 * /spl — RSL Fantasy (Saudi Pro League) -työkalut, OMA OSIO (7.8).
	 *
	 * Kolme tietoista linjausta (etiikkaselvitys cc-reports 7.8 + Villen
	 * päätökset):
	 *   1. TÄYSIN ILMAINEN — hankintakiila FPL-premiumiin, ei paywallia.
	 *   2. Oma reitti eikä FPL-feedin seassa — FPL-first-brändi säilyy,
	 *      SPL:stä kiinnostumaton ei näe sitä koskaan.
	 *   3. Disclaimer näkyvissä: riippumaton datatyökalu, ei makseta
	 *      promoamisesta (FFScout-precedentin mukainen raja).
	 *
	 * Databasis EROAA FPL:stä ja se sanotaan ääneen: maalipohjainen malli
	 * (ei xG-feediä SPL:lle), minuutit kausiaggregaateista. Ei väitetä
	 * enempää kuin data kantaa — [[honest-data-labels]].
	 */
	import {
		fetchSplFantasy,
		fetchSplXp,
		type FantasyResponse,
		type FantasyTeam,
		type XpResponse
	} from '$lib/api';
	import { capture } from '$lib/analytics';
	import { DISCLAIMER } from '$lib/config';

	let cs = $state<FantasyResponse | null>(null);
	let xp = $state<XpResponse | null>(null);
	let csError = $state<string | null>(null);
	let xpError = $state<string | null>(null);

	$effect(() => {
		capture('spl_page_viewed');
		fetchSplFantasy().then(
			(d) => (cs = d),
			(e) => (csError = String(e))
		);
		fetchSplXp().then(
			(d) => (xp = d),
			(e) => (xpError = String(e))
		);
	});

	let nearHorizon = $derived((cs?.meta?.near_horizon_gw as number) ?? 6);
	let nextGw = $derived((cs?.meta?.next_gameweek as number) ?? 1);
	let deadline = $derived.by(() => {
		const raw = cs?.meta?.deadline_utc as string | undefined;
		if (!raw) return null;
		const d = new Date(raw);
		return isNaN(d.getTime()) ? null : d;
	});

	/** CS/FDR: lähihorisontin rivit valmiiksi aggregoituna. */
	type Agg = { t: FantasyTeam; avgFdr: number; avgCs: number | null; n: number };
	let teams = $derived.by<Agg[]>(() => {
		const cut = nextGw + nearHorizon - 1;
		return (cs?.teams ?? [])
			.map((t) => {
				const fx = t.fixtures.filter((f) => f.gw >= nextGw && f.gw <= cut);
				const csVals = fx
					.map((f) => f.cs_pct)
					.filter((v): v is number => typeof v === 'number');
				return {
					t,
					n: fx.length,
					avgFdr: fx.length ? fx.reduce((s, f) => s + f.fdr, 0) / fx.length : 99,
					avgCs: csVals.length === fx.length && fx.length ? csVals.reduce((s, v) => s + v, 0) / fx.length : null
				};
			})
			.sort((a, b) => (b.avgCs ?? -1) - (a.avgCs ?? -1));
	});

	function fdrClass(fdr: number): string {
		if (fdr <= 2) return 'is-easy';
		if (fdr >= 4) return 'is-hard';
		return '';
	}

	type PosFilter = 'ALL' | 'GKP' | 'DEF' | 'MID' | 'FWD';
	let posFilter = $state<PosFilter>('ALL');
	let players = $derived(
		(xp?.players ?? [])
			.filter((p) => posFilter === 'ALL' || p.pos === posFilter)
			.slice(0, 50)
	);

	/* ---- Launch-laajennus (7.8, Villen "rakenna kaikki"): captain / model
	   squad / value / differentials / leaders / compare — kaikki johdettu jo
	   ladatuista payloadeista, ei uusia API-kutsuja. ---- */

	type SplPlayer = (typeof players)[number] & {
		price?: number;
		owned_pct?: number;
		last_season?: {
			minutes?: number;
			goals?: number;
			assists?: number;
			points?: number;
		} | null;
	};
	let pool = $derived((xp?.players ?? []) as SplPlayer[]);

	/** Kapteeni: GW1-xP:n kärki (vain XI-tason minuuttiodotus mukaan —
	 *  cameo-kärki olisi kapteenina harhaanjohtava). */
	let captainPicks = $derived(
		pool
			.filter((p) => p.xmins >= 45)
			.map((p) => ({ p, gw1: p.gameweeks?.[0]?.xp ?? 0 }))
			.sort((a, b) => b.gw1 - a.gw1)
			.slice(0, 5)
	);

	/** Value: xP/GW per miljoona (min. xmins-raja pitää penkkiriskit poissa —
	 *  sama oppi kuin FPL:n xP/90-vika 5.8: pieni jakaja valehtelee). */
	let valuePicks = $derived(
		pool
			.filter((p) => (p.price ?? 0) >= 4 && p.xmins >= 45)
			.map((p) => ({ p, vpm: p.xp_per_gw / (p.price ?? 1) }))
			.sort((a, b) => b.vpm - a.vpm)
			.slice(0, 20)
	);

	/** Differentials: omistus alle 10 %, xP-kärki. */
	let differentials = $derived(
		pool
			.filter((p) => (p.owned_pct ?? 100) < 10 && p.xmins >= 45)
			.sort((a, b) => b.xp_per_gw - a.xp_per_gw)
			.slice(0, 10)
	);

	/** Viime kauden leaderit payloadin last_season-lohkosta. */
	function leaders(key: 'goals' | 'assists' | 'points') {
		return pool
			.filter((p) => p.last_season && (p.last_season[key] ?? 0) > 0)
			.sort((a, b) => (b.last_season?.[key] ?? 0) - (a.last_season?.[key] ?? 0))
			.slice(0, 8);
	}

	type ModelSquad = {
		cost: number;
		xi_xp_horizon: number;
		note: string;
		players: {
			id: number;
			web_name: string;
			team_short: string;
			pos: string;
			price: number;
			xp_per_gw: number;
			in_xi: boolean;
		}[];
	} | null;
	let modelSquad = $derived(((xp as unknown as { model_squad?: ModelSquad })?.model_squad) ?? null);

	/* Compare-lite: kaksi valintaa rinnakkain. */
	let cmpA = $state<number | null>(null);
	let cmpB = $state<number | null>(null);
	let cmpPlayers = $derived(
		[cmpA, cmpB]
			.map((id) => pool.find((p) => p.id === id))
			.filter((p): p is SplPlayer => !!p)
	);
</script>

<svelte:head>
	<title>Saudi Pro League fantasy tools | GoalIQ</title>
	<meta
		name="description"
		content="Free model-based tools for RSL Fantasy (Saudi Pro League): clean sheet odds, fixture difficulty and expected points from the GoalIQ match model."
	/>
	<!-- /spl-prerender (7.8): canonical tälle työkalusivulle itselleen —
	     goaliq.app/spl (staattinen landing) on erillinen sisältösivu joka
	     linkittää tänne, ei duplikaatti. -->
	<link rel="canonical" href="https://pro.goaliq.app/spl" />
	<!-- Prerenderoidulla reitillä boot-runko näkyisi sisällön YLLÄ kunnes
	     hydraatio poistaa sen — tällä reitillä sisältö on jo HTML:ssä,
	     joten runko piilotetaan heti. -->
	{@html '<style>#boot{display:none}</style>'}
</svelte:head>

<div class="shell">
	<header>
		<p class="crumb"><a href="/">← GoalIQ tools</a></p>
		<h1>Saudi Pro League <span class="accent">fantasy tools</span></h1>
		<p class="lede">
			Model-based tools for <strong>RSL Fantasy</strong>, the official Saudi Pro League fantasy
			game. Clean sheet odds, fixture difficulty and expected points from the same GoalIQ match
			model that powers our FPL toolkit. <strong>Completely free.</strong>
		</p>
		{#if deadline}
			<p class="deadline">
				GW{nextGw} deadline: {deadline.toUTCString().replace(':00 GMT', ' UTC')}
			</p>
		{/if}
		<div class="disclaimer">
			<p>
				GoalIQ is an independent data tool. We are not affiliated with, endorsed by, or paid by
				the Saudi Pro League, the RSL Fantasy game, or any club. These tools are free, so
				nobody is paying us to cover this league, including you.
			</p>
			<p class="basis">
				<strong>Data basis, stated plainly:</strong> team strengths come from a goals-based
				Dixon-Coles model fitted on two seasons of SPL results (no free per-match xG feed exists
				for this league). Player projections use realized goal and assist rates plus RSL Fantasy's
				own scoring rules; minutes are estimated from last season's aggregate playing time. This
				is coarser than our FPL pipeline and the confidence labels reflect that.
			</p>
		</div>
	</header>

	<section>
		<h2>Clean sheet % + fixture difficulty <span class="muted">(next {nearHorizon} GWs)</span></h2>
		{#if csError}
			<p class="error">Could not reach the API. {csError}</p>
		{:else if !cs}
			<p class="muted">Loading…</p>
		{:else if !cs.meta.available}
			<p class="muted">SPL projections not published yet. Check back soon.</p>
		{:else}
			<div class="table-wrap">
				<table>
					<thead>
						<tr>
							<th>Team</th>
							<th class="num">avg CS%</th>
							<th class="num">avg FDR</th>
							<th>Fixtures</th>
						</tr>
					</thead>
					<tbody>
						{#each teams as { t, avgFdr, avgCs } (t.name)}
							<tr>
								<td>
									{t.name}
									<span class="muted">{(t as unknown as { short?: string }).short ?? ''}</span>
								</td>
								<td class="num">{avgCs == null ? '–' : avgCs.toFixed(1) + '%'}</td>
								<td class="num {fdrClass(avgFdr)}">{avgFdr === 99 ? '–' : avgFdr.toFixed(2)}</td>
								<td class="fixtures">
									{#each t.fixtures.filter((f) => f.gw >= nextGw && f.gw < nextGw + nearHorizon) as f (f.gw + f.opponent_short)}
										<span class="chip {fdrClass(f.fdr)}" title="GW{f.gw}: {f.opponent} ({f.venue})">
											{f.opponent_short}
											{f.venue === 'H' ? '(H)' : '(A)'}{typeof f.cs_pct === 'number'
												? ` ${Math.round(f.cs_pct)}%`
												: ''}
										</span>
									{/each}
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		{/if}
	</section>

	<section>
		<h2>Expected points <span class="muted">(next {(xp?.meta?.horizon_gw as number) ?? 6} GWs, top 50)</span></h2>
		{#if xpError}
			<p class="error">Could not reach the API. {xpError}</p>
		{:else if !xp}
			<p class="muted">Loading…</p>
		{:else if !xp.meta.available}
			<p class="muted">SPL xP not published yet. Check back soon.</p>
		{:else}
			<div class="posrow">
				{#each ['ALL', 'GKP', 'DEF', 'MID', 'FWD'] as pf (pf)}
					<button
						class:active={posFilter === pf}
						onclick={() => (posFilter = pf as PosFilter)}>{pf}</button
					>
				{/each}
			</div>
			<div class="table-wrap">
				<table>
					<thead>
						<tr>
							<th>Player</th>
							<th>Team</th>
							<th>Pos</th>
							<th class="num">Price</th>
							<th class="num">xP / GW</th>
							<th class="num">xMins</th>
							<th class="num">Total ({(xp?.meta?.horizon_gw as number) ?? 6} GW)</th>
						</tr>
					</thead>
					<tbody>
						{#each players as p (p.id)}
							<tr>
								<td>{p.web_name}</td>
								<td>{p.team_short}</td>
								<td>{p.pos}</td>
								<td class="num">{(p as unknown as { price?: number }).price?.toFixed(1) ?? '–'}</td>
								<td class="num strong">{p.xp_per_gw.toFixed(2)}</td>
								<td class="num">{p.xmins.toFixed(0)}</td>
								<td class="num">{p.xp_horizon_total.toFixed(1)}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
			<p class="muted small">
				Minutes confidence is "med" at best for this league: the RSL API exposes season totals,
				not per-round history. Players new to the league use price-based role priors until real
				minutes accumulate.
			</p>
		{/if}
	</section>

	{#if xp?.meta?.available}
		<section>
			<h2>Captain picks <span class="muted">(GW{nextGw})</span></h2>
			<div class="table-wrap">
				<table>
					<thead>
						<tr>
							<th>#</th><th>Player</th><th>Team</th><th>Pos</th>
							<th>Opponent</th><th class="num">GW{nextGw} xP</th>
						</tr>
					</thead>
					<tbody>
						{#each captainPicks as { p, gw1 }, i (p.id)}
							<tr>
								<td>{i + 1}</td>
								<td>{p.web_name}</td>
								<td>{p.team_short}</td>
								<td>{p.pos}</td>
								<td>
									{(p.gameweeks?.[0]?.opponents ?? [])
										.map((o) => `${o.opp} (${o.venue})`)
										.join(', ') || '–'}
								</td>
								<td class="num strong">{gw1.toFixed(2)}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
			<p class="muted small">
				Captain scores double in RSL Fantasy, so the ranking is simply the highest single-GW
				xP among players the model expects to start.
			</p>
		</section>

		{#if modelSquad}
			<section>
				<h2>The model squad <span class="muted">({modelSquad.cost.toFixed(1)}m of 100.0m)</span></h2>
				<p class="muted small">
					{modelSquad.note} Starting XI in bold, projected XI total {modelSquad.xi_xp_horizon.toFixed(1)}
					xP over the next {(xp?.meta?.horizon_gw as number) ?? 6} GWs.
				</p>
				<div class="table-wrap">
					<table>
						<thead>
							<tr><th>Pos</th><th>Player</th><th>Team</th><th class="num">Price</th><th class="num">xP / GW</th></tr>
						</thead>
						<tbody>
							{#each modelSquad.players as p (p.id)}
								<tr class:xi={p.in_xi}>
									<td>{p.pos}</td>
									<td class={p.in_xi ? 'strong' : ''}>{p.web_name}{p.in_xi ? '' : ' (bench)'}</td>
									<td>{p.team_short}</td>
									<td class="num">{p.price.toFixed(1)}</td>
									<td class="num">{p.xp_per_gw.toFixed(2)}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			</section>
		{/if}

		<section>
			<h2>Best value <span class="muted">(xP per million, next {(xp?.meta?.horizon_gw as number) ?? 6} GWs)</span></h2>
			<div class="table-wrap">
				<table>
					<thead>
						<tr><th>Player</th><th>Team</th><th>Pos</th><th class="num">Price</th><th class="num">xP / GW</th><th class="num">xP / £m</th></tr>
					</thead>
					<tbody>
						{#each valuePicks as { p, vpm } (p.id)}
							<tr>
								<td>{p.web_name}</td>
								<td>{p.team_short}</td>
								<td>{p.pos}</td>
								<td class="num">{p.price?.toFixed(1) ?? '–'}</td>
								<td class="num">{p.xp_per_gw.toFixed(2)}</td>
								<td class="num strong">{vpm.toFixed(3)}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
			<p class="muted small">
				Players below 45 expected minutes are excluded: a good rate on tiny minutes is a bench
				risk, not a bargain.
			</p>
		</section>

		<section>
			<h2>Differentials <span class="muted">(under 10% ownership)</span></h2>
			<div class="table-wrap">
				<table>
					<thead>
						<tr><th>Player</th><th>Team</th><th>Pos</th><th class="num">Owned</th><th class="num">Price</th><th class="num">xP / GW</th></tr>
					</thead>
					<tbody>
						{#each differentials as p (p.id)}
							<tr>
								<td>{p.web_name}</td>
								<td>{p.team_short}</td>
								<td>{p.pos}</td>
								<td class="num">{(p.owned_pct ?? 0).toFixed(1)}%</td>
								<td class="num">{p.price?.toFixed(1) ?? '–'}</td>
								<td class="num strong">{p.xp_per_gw.toFixed(2)}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		</section>

		<section>
			<h2>Last season's leaders <span class="muted">(2025/26, RSL Fantasy data)</span></h2>
			<div class="leaders-grid">
				{#each [['goals', 'Goals'], ['assists', 'Assists'], ['points', 'Fantasy points']] as [key, label] (key)}
					<div>
						<h3>{label}</h3>
						<table>
							<tbody>
								{#each leaders(key as 'goals' | 'assists' | 'points') as p (p.id)}
									<tr>
										<td>{p.web_name} <span class="muted">{p.team_short}</span></td>
										<td class="num strong">{p.last_season?.[key as 'goals' | 'assists' | 'points']}</td>
									</tr>
								{/each}
							</tbody>
						</table>
					</div>
				{/each}
			</div>
		</section>

		<section>
			<h2>Compare two players</h2>
			<div class="cmp-row">
				{#each [0, 1] as slot (slot)}
					<select
						value={slot === 0 ? cmpA : cmpB}
						onchange={(e) => {
							const v = Number((e.target as HTMLSelectElement).value) || null;
							if (slot === 0) cmpA = v;
							else cmpB = v;
							if (cmpA && cmpB) capture('spl_compare_used');
						}}
					>
						<option value="">Pick player {slot + 1}…</option>
						{#each pool.slice(0, 200) as p (p.id)}
							<option value={p.id}>{p.web_name} ({p.team_short}, {p.pos})</option>
						{/each}
					</select>
				{/each}
			</div>
			{#if cmpPlayers.length === 2}
				<div class="table-wrap">
					<table>
						<thead>
							<tr><th></th>{#each cmpPlayers as p (p.id)}<th>{p.web_name} ({p.team_short})</th>{/each}</tr>
						</thead>
						<tbody>
							<tr><td>Price</td>{#each cmpPlayers as p (p.id)}<td class="num">{p.price?.toFixed(1) ?? '–'}</td>{/each}</tr>
							<tr><td>xP / GW</td>{#each cmpPlayers as p (p.id)}<td class="num strong">{p.xp_per_gw.toFixed(2)}</td>{/each}</tr>
							<tr><td>xP / 90</td>{#each cmpPlayers as p (p.id)}<td class="num">{p.xp_per_90?.toFixed(2) ?? '–'}</td>{/each}</tr>
							<tr><td>Expected minutes</td>{#each cmpPlayers as p (p.id)}<td class="num">{p.xmins.toFixed(0)}</td>{/each}</tr>
							<tr><td>25/26 goals</td>{#each cmpPlayers as p (p.id)}<td class="num">{p.last_season?.goals ?? '–'}</td>{/each}</tr>
							<tr><td>25/26 assists</td>{#each cmpPlayers as p (p.id)}<td class="num">{p.last_season?.assists ?? '–'}</td>{/each}</tr>
							<tr><td>25/26 fantasy points</td>{#each cmpPlayers as p (p.id)}<td class="num">{p.last_season?.points ?? '–'}</td>{/each}</tr>
						</tbody>
					</table>
				</div>
			{/if}
		</section>
	{/if}

	<section class="upsell">
		<h2>Play FPL too?</h2>
		<p>
			The same match model runs our full FPL toolkit: xP with a public accuracy log, transfer
			planner, captain ranker, live DefCon and more.
			<a href="/" onclick={() => capture('spl_to_fpl_clicked')}>Open the FPL tools</a>.
		</p>
	</section>

	<footer>
		<hr />
		<p class="muted">{DISCLAIMER} · <a href="https://goaliq.app/privacy.html">Privacy</a></p>
	</footer>
</div>

<style>
	.shell {
		max-width: var(--shell);
		margin: 0 auto;
		padding: var(--s-4);
	}
	.crumb {
		margin-bottom: var(--s-2);
	}
	h1 {
		margin: 0 0 var(--s-2);
	}
	.accent {
		color: var(--accent);
	}
	.lede {
		max-width: 60ch;
	}
	.deadline {
		font-weight: 600;
	}
	.disclaimer {
		border: 1px solid var(--border);
		border-left: 3px solid var(--accent);
		padding: var(--s-3);
		margin: var(--s-4) 0;
		font-size: 0.9em;
	}
	.disclaimer p {
		margin: 0 0 var(--s-2);
	}
	.disclaimer p:last-child {
		margin-bottom: 0;
	}
	section {
		margin-top: var(--s-8);
	}
	.table-wrap {
		overflow-x: auto;
	}
	table {
		border-collapse: collapse;
		width: 100%;
	}
	th,
	td {
		text-align: left;
		padding: var(--s-1) var(--s-2);
		border-bottom: 1px solid var(--border);
		white-space: nowrap;
	}
	.num {
		text-align: right;
		font-variant-numeric: tabular-nums;
	}
	.strong {
		font-weight: 700;
	}
	.fixtures {
		white-space: normal;
	}
	.chip {
		display: inline-block;
		border: 1px solid var(--border);
		border-radius: 3px;
		padding: 0 var(--s-1);
		margin: 1px 2px;
		font-size: 0.8em;
	}
	.is-easy {
		color: var(--ok, #2e7d32);
	}
	.is-hard {
		color: var(--bad, #c62828);
	}
	.posrow {
		display: flex;
		gap: var(--s-1);
		margin-bottom: var(--s-2);
	}
	.posrow button {
		background: none;
		border: 1px solid var(--border);
		border-radius: 3px;
		padding: var(--s-1) var(--s-2);
		cursor: pointer;
		color: inherit;
	}
	.posrow button.active {
		border-color: var(--accent);
		color: var(--accent);
	}
	.upsell {
		border: 1px solid var(--border);
		padding: var(--s-3);
	}
	.leaders-grid {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
		gap: var(--s-4);
	}
	.leaders-grid h3 {
		margin: 0 0 var(--s-1);
		font-size: 1em;
	}
	.cmp-row {
		display: flex;
		gap: var(--s-2);
		flex-wrap: wrap;
		margin-bottom: var(--s-2);
	}
	.cmp-row select {
		background: none;
		color: inherit;
		border: 1px solid var(--border);
		padding: var(--s-1);
		max-width: 100%;
	}
	tr.xi td {
		border-bottom-color: var(--accent);
	}
	.small {
		font-size: 0.85em;
	}
	.error {
		color: var(--bad, #c62828);
	}
	footer {
		margin-top: var(--s-12);
	}
	hr {
		border: none;
		border-top: 1px solid var(--border);
		margin-bottom: var(--s-4);
	}
</style>
