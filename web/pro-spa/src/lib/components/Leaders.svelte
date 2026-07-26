<script lang="ts">
	/**
	 * Leaders (#124/#125) — xG leaders + DefCon tracker (FPLWolfy-ehdotukset).
	 * Sama korttikieli kuin value/differentials. Basis-label AINA näkyvissä
	 * (datarajoitukset ensiluokkaisena: esikausi = 25/26-data, otoskoko per
	 * rivi, ei arvauksia).
	 *
	 * 26.7: xG-lista VAPAUTETTU kokonaan ilmaiseksi. xG/xA/xGI on FPL:n itsensä
	 * julkaisemaa taaksepäin katsovaa dataa, jonka kilpailijat (fpl.page ym.)
	 * antavat ilmaiseksi — maksumuuri hyödykedatan päällä ei puolusta mitään ja
	 * on ristiriidassa "ilmaistaso on aidosti hyödyllinen" -lupauksen kanssa.
	 * DefCon PYSYY premiumissa: hit rate + kynnysanalyysi on oma johdannaisemme,
	 * ei julkista dataa. Maksumuuri kuuluu eteenpäin katsoviin mallin tuotoksiin
	 * (xP, captain ranker, chips, edge), ei menneisyyteen.
	 */
	import { capture } from '$lib/analytics';
	// 26.7 visuaalinen remontti: joukkuepaita riveihin. IP-turva: neutraali
	// siluetti + klubin primary-vari, EI pelaajakuvia eika krestejä.
	import TeamKit from './TeamKit.svelte';
	import { teamColorByShort } from '$lib/teamColors';
	import {
		fetchDefconLeaders,
		fetchXgLeaders,
		type DefconLeadersResponse,
		type XgLeadersResponse
	} from '$lib/fantasyTools';

	let { premium = false, onUpgrade }: { premium?: boolean; onUpgrade?: () => void } = $props();

	const FREE_ROWS = 3;
	const WINDOWS = [3, 5, 10];

	let xg = $state<XgLeadersResponse | null>(null);
	let defcon = $state<DefconLeadersResponse | null>(null);
	let error = $state<string | null>(null);
	let loading = $state(true);
	// #137: pelimäärävalitsin (Wolfy: "more expansive to pick for more games")
	let gameWindow = $state(5);

	$effect(() => {
		const w = gameWindow;
		loading = true;
		error = null;
		Promise.all([fetchXgLeaders(w), fetchDefconLeaders(w)])
			.then(([x, d]) => {
				xg = x;
				defcon = d;
			})
			.catch((e) => (error = e instanceof Error ? e.message : String(e)))
			.finally(() => (loading = false));
	});

	$effect(() => {
		// Paywall koskee enää DefConia — xG on ilmainen, joten sen näyttäminen
		// ei ole paywall-tapahtuma.
		if (!premium && (defcon?.players?.length ?? 0) > 0) {
			capture('paywall_shown', { source: 'fantasy_leaders' }, 'paywall_shown_fantasy_leaders');
		}
	});

	// 26.7: sama kontrollisetti kuin julkisella /fpl/xg-leaders-sivulla. Ilman
	// naita SPA oli kapeampi kuin ilmainen SEO-sivu, mika on vaara suunta.
	// Season-nakymassa vasen vaihtoehto on TOTAALI, ei per ottelu: meilla on
	// avaukset (starts) muttei esiintymisia, joten aitoa per-ottelu-jakajaa ei ole.
	let per90 = $state(false);
	let minMins = $state(0);
	let posFilter = $state('');
	let teamFilter = $state('');
	let sortKey = $state<'xg' | 'xa' | 'xgi' | 'mins' | 'price' | 'games' | 'name'>('xg');
	let sortDesc = $state(true);
	let seasonView = $state(false);

	const MIN_MINS = [0, 90, 180, 270];

	type Agg = {
		row: (typeof xgRowsRaw)[number];
		xg: number;
		xa: number;
		xgi: number;
		mins: number;
		games: number;
	};

	const xgRowsRaw = $derived(xg?.players ?? []);

	function agg(r: (typeof xgRowsRaw)[number]): Agg {
		if (seasonView) {
			const s = r.season;
			const mins = s?.mins ?? 0;
			const d = per90 ? mins / 90 : 1;
			const k = d > 0 ? d : 1;
			return {
				row: r,
				xg: (s?.xg ?? 0) / k,
				xa: (s?.xa ?? 0) / k,
				xgi: (s?.xgi ?? 0) / k,
				mins,
				games: s?.starts ?? 0
			};
		}
		const mins = r.mins ?? 0;
		const d = per90 ? mins / 90 : r.games;
		const k = d > 0 ? d : 1;
		return {
			row: r,
			xg: (r.xg_per_game * r.games) / k,
			xa: (r.xa_per_game * r.games) / k,
			xgi: (r.xgi_per_game * r.games) / k,
			mins,
			games: r.games
		};
	}

	const teams = $derived([...new Set(xgRowsRaw.map((r) => r.team_short))].sort());

	const xgVisible = $derived.by(() => {
		const out: Agg[] = [];
		for (const r of xgRowsRaw) {
			if (posFilter && r.pos !== posFilter) continue;
			if (teamFilter && r.team_short !== teamFilter) continue;
			if (seasonView && !r.season) continue;
			const a = agg(r);
			if (per90 && a.mins < 1) continue;
			if (a.mins < minMins) continue;
			out.push(a);
		}
		// HUOM: vertailut ovat muotoa (y - x) eli VALMIIKSI laskevia, joten
		// laskevassa kertoimen on oltava +1. Aiempi -1 kaansi listan nurin
		// (xG 0.00 karjessa).
		const dir = sortDesc ? 1 : -1;
		out.sort((x, y) => {
			if (sortKey === 'name') return dir * y.row.web_name.localeCompare(x.row.web_name);
			if (sortKey === 'price') return dir * (y.row.price - x.row.price);
			return dir * ((y[sortKey] as number) - (x[sortKey] as number));
		});
		return out;
	});

	// Naytetaan 100 riviä kerrallaan. Sama oppi kuin /fpl/xg-leaders-sivulla:
	// koko listan (373) renderointi jokaisella suodatinklikkauksella lagasi.
	// Suodatus ja lajittelu koskevat silti KOKO aineistoa.
	const RENDER_LIMIT = 100;
	let showAllXg = $state(false);
	const xgShown = $derived(showAllXg ? xgVisible : xgVisible.slice(0, RENDER_LIMIT));

	function sortBy(k: typeof sortKey) {
		if (sortKey === k) sortDesc = !sortDesc;
		else {
			sortKey = k;
			sortDesc = k !== 'name';
		}
	}

	function setSeason(v: boolean) {
		seasonView = v;
		// Per 90:een siirryttaessa oletuskynnys paalle, takaisin pois.
		if (!v && minMins === 180 && !per90) minMins = 0;
	}

	function setPer90(v: boolean) {
		const was = per90;
		per90 = v;
		if (!was && v && minMins === 0) minMins = 180;
		if (was && !v && minMins === 180) minMins = 0;
	}
	const dcVisible = $derived(
		premium ? (defcon?.players ?? []) : (defcon?.players ?? []).slice(0, FREE_ROWS)
	);
	const basisLabel = $derived(xg?.meta?.basis_label ?? defcon?.meta?.basis_label ?? null);

	function unlock() {
		capture('upgrade_tapped', { source: 'fantasy_leaders' });
		onUpgrade?.();
	}
</script>

<h2>xG leaders</h2>
<p class="muted">
	Top expected-goals producers over each player's last {xg?.meta?.window ?? gameWindow} games, from
	official FPL match data.
</p>
<!-- #137 + 26.7: sama kontrollisetti kuin julkisella /fpl/xg-leaders-sivulla.
     Games vaihtaa window-parametrin molemmille listoille; Season, Rate, Min
     mins, Position ja Team ovat klienttipuolen suodattimia xG-listalle. -->
<div class="window-row">
	<span class="muted">Games:</span>
	{#each WINDOWS as w (w)}
		<button
			type="button"
			class="window-chip"
			class:on={!seasonView && gameWindow === w}
			onclick={() => {
				setSeason(false);
				gameWindow = w;
			}}
		>
			{w}
		</button>
	{/each}
	<button
		type="button"
		class="window-chip"
		class:on={seasonView}
		onclick={() => setSeason(true)}>Season</button
	>
	<span class="muted">Rate:</span>
	<button type="button" class="window-chip" class:on={!per90} onclick={() => setPer90(false)}>
		{seasonView ? 'Total' : 'Per game'}
	</button>
	<button type="button" class="window-chip" class:on={per90} onclick={() => setPer90(true)}>
		Per 90
	</button>
	<span class="muted">Min mins:</span>
	{#each MIN_MINS as m (m)}
		<button type="button" class="window-chip" class:on={minMins === m} onclick={() => (minMins = m)}>
			{m === 0 ? 'Any' : `${m}+`}
		</button>
	{/each}
	<span class="muted">Pos:</span>
	{#each ['', 'GKP', 'DEF', 'MID', 'FWD'] as pp (pp)}
		<button
			type="button"
			class="window-chip"
			class:on={posFilter === pp}
			onclick={() => (posFilter = pp)}>{pp === '' ? 'All' : pp}</button
		>
	{/each}
	<select bind:value={teamFilter} aria-label="Filter by team">
		<option value="">All teams</option>
		{#each teams as tt (tt)}<option value={tt}>{tt}</option>{/each}
	</select>
</div>
{#if basisLabel}
	<!-- Data-rajoitus ensiluokkaisena: basis-label aina näkyvissä -->
	<p class="basis">{basisLabel}</p>
{/if}

{#if loading}
	<p class="muted">Loading leaderboards…</p>
{:else if error}
	<p class="banner error">{error}</p>
{:else}
	{#if xgVisible.length === 0}
		<p class="muted">No data yet.</p>
	{:else}
		<div class="table-wrap">
			<table>
				<thead>
					<tr>
						<th>#</th>
						<th><button type="button" class="sortbtn" onclick={() => sortBy('name')}>Player</button></th>
						<th>Pos</th>
						<th class="num"><button type="button" class="sortbtn" onclick={() => sortBy('price')}>Price</button></th>
						<th class="num"><button type="button" class="sortbtn" onclick={() => sortBy('xg')}>xG</button></th>
						<th class="num"><button type="button" class="sortbtn" onclick={() => sortBy('xa')}>xA</button></th>
						<th class="num"><button type="button" class="sortbtn" onclick={() => sortBy('xgi')}>xGI</button></th>
						<th class="num"><button type="button" class="sortbtn" onclick={() => sortBy('mins')}>Mins</button></th>
						<th class="num"><button type="button" class="sortbtn" onclick={() => sortBy('games')}>{seasonView ? 'Starts' : 'Games'}</button></th>
					</tr>
				</thead>
				<tbody>
					{#each xgShown as a, i (a.row.id)}
						<tr>
							<td class="muted">{i + 1}</td>
							<td class="pl">
								<TeamKit
									color={teamColorByShort(a.row.team_short).color}
									textColor={teamColorByShort(a.row.team_short).textColor}
									label={a.row.team_short}
									size={26}
								/>
								<span>{a.row.web_name} <span class="muted">({a.row.team_short})</span></span>
							</td>
							<td>{a.row.pos}</td>
							<td class="num">{a.row.price.toFixed(1)}</td>
							<td class="num strong">{a.xg.toFixed(2)}</td>
							<td class="num">{a.xa.toFixed(2)}</td>
							<td class="num">{a.xgi.toFixed(2)}</td>
							<td class="num">{a.mins}</td>
							<td class="num">{a.games}</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
		{#if !showAllXg && xgVisible.length > RENDER_LIMIT}
			<button type="button" class="window-chip" onclick={() => (showAllXg = true)}>
				Show all {xgVisible.length} players
			</button>
		{/if}
		<p class="muted count">
			{xgVisible.length} players{per90 ? ', per 90 minutes' : seasonView ? ', season totals' : ', per game'}{seasonView
				? ', full season'
				: `, last ${xg?.meta?.window ?? gameWindow} games each`}{minMins
				? `, at least ${minMins} minutes played`
				: ''}
		</p>
	{/if}

	<h2 class="dc-title">DefCon leaders</h2>
	<p class="muted">
		The most reliable defensive-contribution scorers over each player's last {defcon?.meta?.window ??
			gameWindow} games. 2 pts when a defender reaches 10 CBIT (clearances, blocks, interceptions,
		tackles) or a midfielder/forward reaches 12 CBIRT (CBIT + recoveries) in a match.
	</p>
	{#if dcVisible.length === 0}
		<p class="muted">No data yet.</p>
	{:else}
		<div class="table-wrap">
			<table>
				<thead>
					<tr>
						<th>#</th>
						<th>Player</th>
						<th>Pos</th>
						<th class="num">Price</th>
						<th class="num"><abbr title="Defensive-contribution actions per game">DC/game</abbr></th>
						<th class="num"
							><abbr title="Share of played games where the player reached the DefCon threshold"
								>Hit rate</abbr
							></th
						>
						<th class="num"><abbr title="DefCon points earned in the window">Pts</abbr></th>
						<th class="num"><abbr title="Games played in the window (real sample size)">Games</abbr></th>
					</tr>
				</thead>
				<tbody>
					{#each dcVisible as p, i (p.id)}
						<tr>
							<td class="muted">{i + 1}</td>
							<td class="pl">
								<TeamKit
									color={teamColorByShort(p.team_short).color}
									textColor={teamColorByShort(p.team_short).textColor}
									label={p.team_short}
									size={26}
								/>
								<span>{p.web_name} <span class="muted">({p.team_short})</span></span>
							</td>
							<td>{p.pos}</td>
							<td class="num">{p.price.toFixed(1)}</td>
							<td class="num">{p.dc_per_game.toFixed(1)}</td>
							<td class="num strong">{Math.round(p.hit_rate_pct)}%</td>
							<td class="num">{p.defcon_points_window}</td>
							<td class="num">{p.games}</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	{/if}

	{#if !premium && (defcon?.players?.length ?? 0) > FREE_ROWS}
		<!-- 🔒 DefCon top-3 free → koko lista premium. xG-lista on ilmainen. -->
		<button type="button" class="teaser-row" onclick={unlock}>
			<span>
				Full DefCon leaderboard <span class="muted">(top 3 shown free)</span>
			</span>
			<span class="locked" aria-label="Locked">•.••</span>
			<span class="cta">Unlock with Premium</span>
		</button>
	{/if}
{/if}

<style>
	/* 26.7: aktiivinen suodatin auki tekstina, ei hiljaista rajausta */
	.count {
		font-size: var(--step--1);
		margin: var(--s-2) 0 0;
	}
	/* 26.7: lajitteluotsikot ja joukkuevalitsin (pariteetti xg-leaders-sivun kanssa) */
	.sortbtn {
		background: none;
		border: 0;
		padding: 0;
		font: inherit;
		color: inherit;
		cursor: pointer;
	}
	.sortbtn:hover {
		color: var(--giq-magenta-deep, #d6006e);
	}
	.window-row select {
		flex: 0 0 auto;
		border: 1px solid var(--border);
		border-radius: 999px;
		background: var(--surface);
		color: var(--text);
		font-weight: 600;
		font-size: var(--step--1);
		padding: 4px 10px;
		line-height: 1.4;
	}
	/* 26.7: paita + nimi samalle riville, paita ei kutistu */
	.pl {
		display: flex;
		align-items: center;
		gap: 8px;
	}
	.pl :global(svg) {
		flex: 0 0 auto;
	}
	.basis {
		color: var(--giq-gold-deep, #f4a800);
		font-weight: 600;
		font-size: var(--step--1);
		margin: 0 0 var(--s-3);
	}
	/* #137: pelimäärävalitsin */
	/* 26.7: rivi karii. Kontrolleja on nyt ~18 (Games/Season/Rate/Min mins/Pos/
	   Team) yhden pelimaaravalitsimen sijaan, ja ilman wrapia flex puristi ne
	   samalle riville -> "Season" ja "Per game" eivat mahtuneet pallukkaan. */
	.window-row {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--s-2);
		row-gap: var(--s-2);
		margin: 0 0 var(--s-2);
		font-size: var(--step--1);
	}
	.window-row > span {
		flex: 0 0 auto;
	}
	.window-chip {
		flex: 0 0 auto;
		min-width: 36px;
		border: 1px solid var(--border);
		border-radius: 999px;
		background: var(--surface);
		color: var(--text-muted);
		font-weight: 700;
		font-size: var(--step--1);
		padding: 4px 12px;
		cursor: pointer;
		text-align: center;
		white-space: nowrap;
		line-height: 1.4;
	}
	.window-chip.on {
		background: var(--giq-magenta);
		border-color: var(--giq-magenta);
		color: #fff;
	}
	.dc-title {
		margin-top: var(--s-5);
	}
	.strong {
		font-weight: 800;
		color: var(--giq-magenta-deep);
	}
	.teaser-row {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--s-2);
		width: 100%;
		margin-top: var(--s-3);
		background: rgba(255, 46, 126, 0.1);
		border: 1px solid rgba(255, 46, 126, 0.35);
		border-radius: var(--radius);
		padding: var(--s-2) var(--s-3);
		color: var(--text);
		font-weight: 600;
		font-size: var(--step--1);
		cursor: pointer;
		text-align: left;
	}
	.teaser-row .cta {
		margin-left: auto;
		color: var(--positive);
		font-weight: 700;
	}
	.locked {
		letter-spacing: 2px;
		color: var(--text-muted);
	}
</style>
