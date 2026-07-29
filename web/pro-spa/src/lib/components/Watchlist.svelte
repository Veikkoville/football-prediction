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
</script>

<section class="watchlist">
	<h3>Watchlist</h3>
	<p class="muted">
		Track the players you are watching: price and availability at a glance.
	</p>

	{#each rows as p (p.id)}
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
	{/if}
	{#if rows.length > 0 && priceNote != null}
		<p class="muted limit">{priceNote}</p>
	{/if}

	{#if !atLimit}
		<PlayerSearch
			id="watchlist-add"
			label="Add a player"
			bind:query
			items={candidates}
			onSelect={(p) => {
				update({ ...prefs, watchlist: [...prefs.watchlist, p.id] });
				query = '';
			}}
		/>
	{:else if !premium}
		<p class="muted limit">Free tracks {WATCHLIST_FREE_LIMIT} players. Premium removes the limit.</p>
	{/if}
</section>

<style>
	.watchlist {
		border: 1px solid var(--border);
		border-radius: var(--radius, 0);
		padding: var(--s-4);
		margin: var(--s-4) 0;
		background: var(--surface);
	}
	h3 {
		margin: 0 0 var(--s-1);
		font-size: var(--step-1);
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
