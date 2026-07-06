<script lang="ts">
	import type { XpPlayer } from '$lib/api';
	import { gwXp } from '$lib/api';

	// Labelit = mobiilin XpComponentSplit-pariteetti (goaliq-app lib/i18n/en.ts)
	const LABELS: Record<string, string> = {
		appearance: 'Appearance',
		goals: 'Goals',
		assists: 'Assists',
		clean_sheet: 'Clean sheet',
		conceded: 'Conceded',
		saves: 'Saves',
		defensive_contribution: 'Def. contribution',
		yellows: 'Cards',
		bonus: 'Bonus'
	};

	let { player }: { player: XpPlayer } = $props();

	let parts = $derived(
		Object.entries(player.components ?? {})
			.filter(([, v]) => typeof v === 'number' && Math.abs(v) >= 0.005)
			.sort(([, a], [, b]) => b - a)
	);
	// GW total = taulukon virallinen per-GW-xp (ei komponenttien
	// pyöristyssummaa -> ei ±0.01-ristiriitaa taulukon kanssa)
	let total = $derived.by(() => {
		const t = gwXp(player, player.components_gw);
		return t > 0 ? t : parts.reduce((s, [, v]) => s + v, 0);
	});
	let maxPos = $derived(Math.max(...parts.map(([, v]) => v), 0.001));
</script>

{#if parts.length > 0}
	<div class="split">
		{#each parts as [key, value] (key)}
			<div class="row">
				<span class="lbl">{LABELS[key] ?? key}</span>
				<div class="bar">
					{#if value > 0}
						<div class="fill" style="width: {Math.max((value / maxPos) * 100, 2)}%"></div>
					{/if}
				</div>
				<span class="val" class:neg={value < 0}>
					{value > 0 ? '+' : ''}{value.toFixed(2)}{value > 0 && total > 0
						? ` · ${Math.round((value / total) * 100)}%`
						: ''}
				</span>
			</div>
		{/each}
		<div class="total">
			<span>GW total</span>
			<span>{total.toFixed(2)} xP</span>
		</div>
	</div>
{:else}
	<p class="muted">No component breakdown available for this player.</p>
{/if}

<style>
	.split {
		max-width: 560px;
	}
	.row {
		display: flex;
		align-items: center;
		gap: var(--s-3);
		margin: 3px 0;
		font-size: var(--step--1);
	}
	.lbl {
		width: 130px;
		flex: none;
	}
	.bar {
		flex: 1;
		background: rgba(255, 255, 255, 0.08);
		border-radius: 4px;
		height: 10px;
	}
	.fill {
		background: var(--positive);
		border-radius: 4px;
		height: 10px;
	}
	.val {
		width: 105px;
		flex: none;
		text-align: right;
		color: var(--positive);
		font-weight: 700;
		font-variant-numeric: tabular-nums;
	}
	.val.neg {
		color: var(--negative);
	}
	.total {
		display: flex;
		justify-content: space-between;
		margin-top: var(--s-2);
		padding-top: var(--s-2);
		border-top: 1px solid var(--border);
		font-weight: 700;
		font-size: var(--step--1);
	}
</style>
