<script lang="ts">
	/**
	 * Value (#127) — web-pariteetti mobiilin #114:lle: xP/£-value-ranking +
	 * GK rotation pairs. Sama gate kuin mobiilissa: free = top-3 + lukko,
	 * premium = koko lista + GK-parit. Source fantasy_value (identtinen
	 * paywall_shown/upgrade_tapped, #85-oppi). Korttikieli #124 Leadersin
	 * mukainen, paletti #108.
	 */
	import { capture } from '$lib/analytics';
	import { fetchValue, type ValueResponse } from '$lib/fantasyTools';

	let { premium = false, onUpgrade }: { premium?: boolean; onUpgrade?: () => void } = $props();

	const FREE_ROWS = 3;
	const SWING_LABEL: Record<string, string> = {
		steady: 'Steady fixtures',
		moderate: 'Moderate swing',
		swingy: 'Swingy fixtures'
	};

	let data = $state<ValueResponse | null>(null);
	let error = $state<string | null>(null);
	let loading = $state(true);

	$effect(() => {
		loading = true;
		fetchValue()
			.then((d) => (data = d))
			.catch((e) => (error = e instanceof Error ? e.message : String(e)))
			.finally(() => (loading = false));
	});

	$effect(() => {
		if (!premium && (data?.players?.length ?? 0) > 0) {
			capture('paywall_shown', { source: 'fantasy_value' }, 'paywall_shown_fantasy_value');
		}
	});

	const visible = $derived(
		premium ? (data?.players ?? []) : (data?.players ?? []).slice(0, FREE_ROWS)
	);
	const pairs = $derived(data?.gk?.pairs ?? []);

	function unlock() {
		capture('upgrade_tapped', { source: 'fantasy_value' });
		onUpgrade?.();
	}
</script>

<h2>Player value: xP per million</h2>
<p class="muted">
	Projected points per million spent over the next {data?.meta?.horizon_gw ?? 6} gameweeks, with a
	fixture-swing flag. Pre-season prices come from the 2025/26 game until GW1.
</p>

{#if loading}
	<p class="muted">Loading value ranking…</p>
{:else if error}
	<p class="banner error">{error}</p>
{:else}
	{#if visible.length === 0}
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
						<th class="num"><abbr title="Projected xP per million over the horizon">Value</abbr></th>
						<th class="num"><abbr title="Total projected points over the horizon">xP</abbr></th>
						<th>Fixtures</th>
						<th class="num">Owned</th>
					</tr>
				</thead>
				<tbody>
					{#each visible as p, i (p.id)}
						<tr>
							<td class="muted">{i + 1}</td>
							<td>{p.web_name} <span class="muted">({p.team_short})</span></td>
							<td>{p.pos}</td>
							<td class="num">{p.price.toFixed(1)}</td>
							<td class="num strong">{p.value.toFixed(2)}</td>
							<td class="num">{p.xp_horizon_total.toFixed(1)}</td>
							<td>{SWING_LABEL[p.swing_label] ?? p.swing_label}</td>
							<td class="num">{p.owned_pct.toFixed(1)}%</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
		<p class="muted note">
			Fixture swing measures calendar difficulty variation over the horizon, not point variance.
		</p>
	{/if}

	{#if premium}
		{#if pairs.length > 0}
			<h2 class="gk-title">GK rotation pairs</h2>
			<p class="muted">
				Two budget keepers whose fixtures alternate: start whichever has the better clean-sheet
				chance each week.
			</p>
			<div class="table-wrap">
				<table>
					<thead>
						<tr>
							<th>Pair</th>
							<th class="num"><abbr title="Combined price of both keepers">Cost</abbr></th>
							<th class="num"
								><abbr title="Average of the better keeper's clean-sheet chance each gameweek"
									>Avg best CS%</abbr
								></th
							>
							<th>Start plan</th>
						</tr>
					</thead>
					<tbody>
						{#each pairs.slice(0, 5) as pair (pair.gk_a.id + '-' + pair.gk_b.id)}
							<tr>
								<td>
									{pair.gk_a.web_name} <span class="muted">({pair.gk_a.team_short})</span> +
									{pair.gk_b.web_name} <span class="muted">({pair.gk_b.team_short})</span>
								</td>
								<td class="num">{pair.combined_price.toFixed(1)}</td>
								<td class="num strong">{pair.avg_best_cs_pct.toFixed(1)}%</td>
								<td class="muted plan-cells">
									{pair.gw_split.map((s) => `GW${s.gw} ${s.team_short}`).join(' · ')}
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		{/if}
	{:else if (data?.players?.length ?? 0) > FREE_ROWS}
		<!-- 🔒 sama gate kuin mobiili #114: top-3 free, loput + GK-parit premium -->
		<button type="button" class="teaser-row" onclick={unlock}>
			<span>
				Full value ranking and GK rotation pairs <span class="muted">(top 3 shown free)</span>
			</span>
			<span class="locked" aria-label="Locked">•.••</span>
			<span class="cta">Unlock with Premium</span>
		</button>
	{/if}
{/if}

<style>
	.strong {
		font-weight: 800;
		color: var(--giq-magenta-deep);
	}
	.gk-title {
		margin-top: var(--s-5);
	}
	.note {
		font-size: var(--step--1);
	}
	.plan-cells {
		font-size: var(--step--1);
		white-space: nowrap;
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
