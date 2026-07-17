<script lang="ts">
	/**
	 * Leaders (#124/#125) — xG leaders + DefCon tracker (FPLWolfy-ehdotukset).
	 * Sama korttikieli kuin value/differentials. Top-3 free + koko lista
	 * premium (#114-linja, source fantasy_leaders). Basis-label AINA näkyvissä
	 * (datarajoitukset ensiluokkaisena: esikausi = 25/26-data, otoskoko per
	 * rivi, ei arvauksia).
	 */
	import { capture } from '$lib/analytics';
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
		if (!premium && ((xg?.players?.length ?? 0) > 0 || (defcon?.players?.length ?? 0) > 0)) {
			capture('paywall_shown', { source: 'fantasy_leaders' }, 'paywall_shown_fantasy_leaders');
		}
	});

	const xgVisible = $derived(premium ? (xg?.players ?? []) : (xg?.players ?? []).slice(0, FREE_ROWS));
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
<!-- #137: pelimäärävalitsin — vaihtaa window-parametrin molemmille listoille -->
<div class="window-row">
	<span class="muted">Games:</span>
	{#each WINDOWS as w (w)}
		<button
			type="button"
			class="window-chip"
			class:on={gameWindow === w}
			onclick={() => (gameWindow = w)}
		>
			{w}
		</button>
	{/each}
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
						<th>Player</th>
						<th>Pos</th>
						<th class="num">Price</th>
						<th class="num"><abbr title="Expected goals per game over the window">xG/game</abbr></th>
						<th class="num"><abbr title="Expected assists per game over the window">xA/game</abbr></th>
						<th class="num"><abbr title="Expected goal involvements (goals + assists) per game">xGI/game</abbr></th>
						<th class="num"><abbr title="Games played in the window (real sample size)">Games</abbr></th>
					</tr>
				</thead>
				<tbody>
					{#each xgVisible as p, i (p.id)}
						<tr>
							<td class="muted">{i + 1}</td>
							<td>{p.web_name} <span class="muted">({p.team_short})</span></td>
							<td>{p.pos}</td>
							<td class="num">{p.price.toFixed(1)}</td>
							<td class="num strong">{p.xg_per_game.toFixed(2)}</td>
							<td class="num">{p.xa_per_game.toFixed(2)}</td>
							<td class="num">{p.xgi_per_game.toFixed(2)}</td>
							<td class="num">{p.games}</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
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
							<td>{p.web_name} <span class="muted">({p.team_short})</span></td>
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

	{#if !premium && ((xg?.players?.length ?? 0) > FREE_ROWS || (defcon?.players?.length ?? 0) > FREE_ROWS)}
		<!-- 🔒 top-3 free → loput premium (#114-linja) -->
		<button type="button" class="teaser-row" onclick={unlock}>
			<span>
				Full xG and DefCon leaderboards <span class="muted">(top 3 shown free)</span>
			</span>
			<span class="locked" aria-label="Locked">•.••</span>
			<span class="cta">Unlock with Premium</span>
		</button>
	{/if}
{/if}

<style>
	.basis {
		color: var(--giq-gold-deep, #f4a800);
		font-weight: 600;
		font-size: var(--step--1);
		margin: 0 0 var(--s-3);
	}
	/* #137: pelimäärävalitsin */
	.window-row {
		display: flex;
		align-items: center;
		gap: var(--s-2);
		margin: 0 0 var(--s-2);
		font-size: var(--step--1);
	}
	.window-chip {
		min-width: 36px;
		border: 1px solid var(--border);
		border-radius: 999px;
		background: var(--surface);
		color: var(--text-muted);
		font-weight: 700;
		font-size: var(--step--1);
		padding: 4px 12px;
		cursor: pointer;
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
