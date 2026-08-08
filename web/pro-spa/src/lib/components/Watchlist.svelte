<script lang="ts">
	/**
	 * Watchlist (V3, FM: skoutauslista) — mobiilin WatchlistSection-vastine.
	 * Määrittely: goaliq-app/cos-reports/beat-the-model-maarittely-2026-07-29.md §3.
	 *
	 * Pelaajat seurantaan → hinta ja availability-liput SINUN pelaajistasi
	 * yhdellä silmäyksellä. FREE 3 pelaajaa, premium rajatta (gate täällä,
	 * kanta sallii 50 = roskadatan torjunta). Sama teaser-kaava kuin
	 * leaders-listoissa: free näkee mekanismin, premium poistaa rajan.
	 */
	import { fetchXp, type XpPlayer } from '$lib/api';
	import { capture } from '$lib/analytics';
	import { fetchPriceWatch } from '$lib/fantasyTools';
	import {
		EMPTY_PREFS,
		WATCHLIST_FREE_LIMIT,
		WATCHLIST_MAX,
		loadPrefs,
		savePrefs,
		pushRemotePrefsSoon,
		syncPrefs,
		type FplPrefs
	} from '$lib/prefs';
	import PlayerSearch from './PlayerSearch.svelte';
	import TeamKit from './TeamKit.svelte';
	import { teamColorByShort } from '$lib/teamColors';

	let { premium = false }: { premium?: boolean } = $props();

	let pool = $state<XpPlayer[]>([]);
	let prefs = $state<FplPrefs>({ ...EMPTY_PREFS });
	let query = $state('');
	// Hinnanmuutosennuste (sama data kuin Prices-työkalussa). Fail-safe:
	// esikaudella listat ovat tyhjät eikä se ole vika.
	let priceMap = $state<Map<number, string>>(new Map());
	// Kun price watch on tyhjä (esikausi), paljas rivi ei kerro että signaali
	// on tulossa. API kertoo syyn itse (meta.note) — näytetään se, ei arvata.
	let priceNote = $state<string | null>(null);

	// SAMA termistö kuin PriceWatch.svelte — pariteetti, ei kahta sanastoa.
	const TREND: Record<string, { arrow: string; cls: string; label: string }> = {
		rising_soon: { arrow: '▲', cls: 'up', label: 'Rising soon' },
		rising_watch: { arrow: '▲', cls: 'up', label: 'On watch' },
		falling_soon: { arrow: '▼', cls: 'down', label: 'Falling soon' },
		falling_watch: { arrow: '▼', cls: 'down', label: 'On watch' }
	};

	$effect(() => {
		fetchXp().then(
			(d) => (pool = d.players ?? []),
			() => {}
		);
		fetchPriceWatch().then(
			(pw) => {
				const m = new Map<number, string>();
				for (const p of pw.risers ?? []) m.set(p.id, p.status);
				for (const p of pw.fallers ?? []) m.set(p.id, p.status);
				priceMap = m;
				if (m.size === 0) priceNote = pw.meta?.note ?? null;
			},
			() => {}
		);
		prefs = loadPrefs();
		syncPrefs().then((remote) => {
			if (remote) prefs = remote;
		});
	});

	function update(next: FplPrefs) {
		prefs = next;
		savePrefs(next);
		pushRemotePrefsSoon(next);
	}

	let limit = $derived(premium ? WATCHLIST_MAX : WATCHLIST_FREE_LIMIT);
	let atLimit = $derived(prefs.watchlist.length >= limit);
	let byId = $derived(new Map(pool.map((p) => [p.id, p])));
	let rows = $derived(
		prefs.watchlist.map((id) => byId.get(id)).filter((p): p is XpPlayer => p != null)
	);
	let candidates = $derived(pool.filter((p) => !prefs.watchlist.includes(p.id)));

	// 31.7 (Villen palaute): lista oletuksena KIINNI — auki levitettynä se söi
	// team-segmentin. Alasveto, sisältö säilyy täsmälleen samana avattuna.
	let open = $state(false);
	function toggle() {
		open = !open;
		capture('watchlist_toggled', { open });
	}

	// 31.7 (Villen palaute): samat rajaimet kuin leaders-listoissa — hinta ja
	// omistus%. Oma lista = oma data, ei premium-gatea (ei enumerointivuotoa).
	// Labelit rehellisiä 0.1-granulariteetille kuten Leadersissa (#9b).
	const PRICE_BANDS = [
		{ label: 'All', min: 0, max: Infinity },
		{ label: '4.5-', min: 0, max: 4.5 },
		{ label: '4.6-6.0', min: 4.6, max: 6.0 },
		{ label: '6.1-8.0', min: 6.1, max: 8.0 },
		{ label: '8.1+', min: 8.1, max: Infinity }
	] as const;
	const OWN_BANDS = [
		{ label: 'All', min: 0, max: Infinity },
		{ label: '<5%', min: 0, max: 4.99 },
		{ label: '5-15%', min: 5, max: 15 },
		{ label: '15-40%', min: 15.01, max: 40 },
		{ label: '40%+', min: 40.01, max: Infinity }
	] as const;
	let priceBand = $state<(typeof PRICE_BANDS)[number]>(PRICE_BANDS[0]);
	let ownBand = $state<(typeof OWN_BANDS)[number]>(OWN_BANDS[0]);
	// 31.7 jatko (Ville): sama rajaus koskee myös Add a player -hakua, ja
	// mukaan joukkuefiltteri — löytäminen helpottuu kun 700 kandidaattia
	// kapenee esim. yhden joukkueen 4.6-6.0m-riveihin.
	let teamFilter = $state('');
	const teams = $derived([...new Set(pool.map((p) => p.team_short))].sort());
	function setPriceBand(b: (typeof PRICE_BANDS)[number]) {
		priceBand = b;
		capture('watchlist_filtered', { kind: 'price', band: b.label });
	}
	function setOwnBand(b: (typeof OWN_BANDS)[number]) {
		ownBand = b;
		capture('watchlist_filtered', { kind: 'own', band: b.label });
	}
	function setTeam(t: string) {
		teamFilter = t;
		capture('watchlist_filtered', { kind: 'team', band: t || 'All' });
	}
	function inBands(p: XpPlayer): boolean {
		if (teamFilter && p.team_short !== teamFilter) return false;
		if (priceBand.label !== 'All') {
			// Hinnaton rivi ei voi osua haarukkaan — pois rajatusta näkymästä.
			if (p.price == null || p.price < priceBand.min || p.price > priceBand.max) return false;
		}
		if (ownBand.label !== 'All') {
			if (p.owned_pct == null || p.owned_pct < ownBand.min || p.owned_pct > ownBand.max)
				return false;
		}
		return true;
	}
	let visibleRows = $derived(rows.filter(inBands));
	let filtered = $derived(
		priceBand.label !== 'All' || ownBand.label !== 'All' || teamFilter !== ''
	);
	// Sama rajaus hakukandidaatteihin — All-tilassa käyttäytyy kuten ennen.
	let visibleCandidates = $derived(filtered ? candidates.filter(inBands) : candidates);
</script>

<section class="watchlist">
	<button type="button" class="head" aria-expanded={open} onclick={toggle}>
		<h3>Watchlist {#if rows.length > 0}<span class="muted count">({rows.length})</span>{/if}</h3>
		<span class="chev" aria-hidden="true">{open ? '▾' : '▸'}</span>
	</button>
	{#if open}
	<p class="muted">
		Track the players you are watching: price and availability at a glance.
	</p>

	{#if pool.length > 0}
		<!-- Rajaimet koskevat sekä seurattuja että Add a player -hakua -->
		<div class="band-row">
			<span class="muted">Price:</span>
			{#each PRICE_BANDS as b (b.label)}
				<button
					type="button"
					class="band-chip"
					class:on={priceBand === b}
					onclick={() => setPriceBand(b)}>{b.label}</button
				>
			{/each}
			<span class="muted">Owned:</span>
			{#each OWN_BANDS as b (b.label)}
				<button
					type="button"
					class="band-chip"
					class:on={ownBand === b}
					onclick={() => setOwnBand(b)}>{b.label}</button
				>
			{/each}
			<select
				value={teamFilter}
				onchange={(e) => setTeam(e.currentTarget.value)}
				aria-label="Filter by team"
			>
				<option value="">All teams</option>
				{#each teams as t (t)}<option value={t}>{t}</option>{/each}
			</select>
		</div>
	{/if}

	{#each visibleRows as p (p.id)}
		{@const flagged = p.status != null && p.status !== 'a'}
		{@const tc = teamColorByShort(p.team_short)}
		{@const trend = TREND[priceMap.get(p.id) ?? '']}
		<div class="row">
			<TeamKit color={tc.color} textColor={tc.textColor} label={p.team_short} size={24} />
			<div class="body">
				<span class="name"
					>{p.web_name}
					<span class="muted meta">{p.pos}{p.price != null ? ` · ${p.price.toFixed(1)}m` : ''}</span>
				</span>
				{#if trend}
					<span class="trend {trend.cls}">{trend.arrow} {trend.label}</span>
				{/if}
				{#if flagged}
					<span class="flag">{p.news || 'Flagged by FPL'}</span>
				{/if}
			</div>
			<button
				type="button"
				class="remove"
				aria-label="Remove from watchlist"
				onclick={() => update({ ...prefs, watchlist: prefs.watchlist.filter((id) => id !== p.id) })}
				>×</button
			>
		</div>
	{/each}
	{#if rows.length === 0}
		<p class="muted">No players tracked yet. Add the ones you are deciding on.</p>
	{:else if visibleRows.length === 0}
		<!-- Aktiivinen rajaus auki tekstinä, ei hiljaista tyhjää listaa -->
		<p class="muted">No tracked players match these filters.</p>
	{:else if filtered}
		<p class="muted limit">{visibleRows.length} of {rows.length} tracked players shown.</p>
	{/if}
	{#if rows.length > 0 && priceNote != null}
		<p class="muted limit">{priceNote}</p>
	{/if}

	{#if !atLimit}
		<PlayerSearch
			id="watchlist-add"
			label="Add a player"
			bind:query
			items={visibleCandidates}
			onSelect={(p) => {
				// 30.7 digest-instrumentointi: SAMA eventtinimi + n-kenttä kuin
				// mobiilin WatchlistSectionissa (fpl_watchlist_added), pariteetti.
				capture('fpl_watchlist_added', { n: prefs.watchlist.length + 1 });
				update({ ...prefs, watchlist: [...prefs.watchlist, p.id] });
				query = '';
			}}
		/>
	{:else if !premium}
		<p class="muted limit">Free tracks {WATCHLIST_FREE_LIMIT} players. Premium tracks up to 50.</p>
	{/if}
	{/if}
</section>

<style>
	.watchlist {
		border: 1px solid var(--border);
		border-radius: var(--radius);
		padding: var(--s-4);
		margin: var(--s-4) 0;
		background: var(--surface);
	}
	h3 {
		margin: 0 0 var(--s-1);
		font-size: var(--step-1);
	}
	/* 31.7: alasveto-otsikko — koko rivi klikattava, chevron oikealla */
	.head {
		display: flex;
		align-items: center;
		justify-content: space-between;
		width: 100%;
		background: none;
		border: 0;
		padding: 0;
		color: inherit;
		font: inherit;
		cursor: pointer;
		text-align: left;
	}
	.head h3 {
		margin: 0;
	}
	.count {
		font-weight: 400;
		font-size: var(--step--1);
	}
	.chev {
		color: var(--text-muted);
		font-size: var(--step--1);
	}
	/* 31.7: rajainchipit — sama kieli kuin Leadersin window-chipit */
	.band-row {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--s-2);
		row-gap: var(--s-2);
		margin: var(--s-2) 0;
		font-size: var(--step--1);
	}
	.band-chip {
		flex: 0 0 auto;
		border: 1px solid var(--border);
		border-radius: var(--radius);
		background: var(--surface);
		color: var(--text-muted);
		font-weight: 700;
		font-size: var(--step--1);
		padding: 4px 12px;
		cursor: pointer;
		white-space: nowrap;
		line-height: 1.4;
	}
	.band-chip.on {
		background: transparent;
		border-color: var(--accent);
		color: var(--accent-strong);
	}
	.band-row select {
		flex: 0 0 auto;
		border: 1px solid var(--border);
		border-radius: var(--radius);
		background: var(--surface);
		color: var(--text);
		font-weight: 600;
		font-size: var(--step--1);
		padding: 4px 10px;
		line-height: 1.4;
	}
	.row {
		display: flex;
		align-items: center;
		gap: var(--s-3);
		padding: var(--s-2) 0;
		border-bottom: 1px solid var(--border);
	}
	.body {
		flex: 1;
		min-width: 0;
		display: flex;
		flex-direction: column;
	}
	.name {
		font-weight: 700;
	}
	.meta {
		font-weight: 400;
		font-size: var(--step--1);
	}
	.flag {
		color: var(--negative);
		font-size: var(--step--1);
	}
	.trend {
		font-size: var(--step--1);
		font-weight: 600;
	}
	.trend.up {
		color: var(--positive);
	}
	.trend.down {
		color: var(--negative);
	}
	.remove {
		font: inherit;
		font-size: 1.1rem;
		border: none;
		background: transparent;
		color: var(--text-muted);
		cursor: pointer;
		padding: 0 0.3rem;
	}
	.limit {
		margin: var(--s-2) 0 0;
	}
</style>
