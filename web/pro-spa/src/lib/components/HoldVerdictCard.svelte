<script lang="ts">
	import { capture } from '$lib/analytics';
	import type { HoldVerdict } from '$lib/fantasyTools';

	// #63: jaettu hero-verdikti rate-teamille + plannerille. Verdikti tulee
	// backendin hold_verdict-lohkosta (hit-tietoinen netto vs kynnys) - UI ei
	// laske omaa kantaa, vain nostaa mallin kannan keskiöön xP-matikan kera.
	let { verdict, surface }: { verdict: HoldVerdict; surface: 'rate_team' | 'planner' } = $props();

	$effect(() => {
		// Mittaa kuinka usein malli sanoo "hold" (mobiilipariteetti: sama
		// eventtinimi + kentät). Ei PII:tä - entry-ID ei mene eventtiin.
		capture('hold_verdict_shown', {
			verdict: verdict.verdict,
			best_move_gain_xp: verdict.best_move_gain_xp,
			surface
		});
	});

	const gainText = $derived(
		verdict.best_move_gain_xp === null
			? null
			: `${verdict.best_move_gain_xp >= 0 ? '+' : ''}${verdict.best_move_gain_xp.toFixed(1)}`
	);
	const hitNote = $derived(verdict.hit_applied_xp ? ', after a -4 hit' : '');
</script>

{#if verdict.verdict === 'hold'}
	<div class="verdict-hero hold" role="status">
		<p class="title">Hold - no transfer beats your team this GW</p>
		<p class="math">
			{#if gainText === null}
				No available move improves your projected xP over the next {verdict.horizon_gws} GWs.
			{:else}
				Best available move: {gainText} xP over {verdict.horizon_gws} GWs (below the {verdict.threshold_xp.toFixed(
					1
				)} xP threshold{hitNote}).
			{/if}
		</p>
	</div>
{:else}
	<div class="verdict-hero go" role="status">
		<p class="title">{verdict.message}</p>
		<p class="math">
			Best move nets {gainText} xP over {verdict.horizon_gws} GWs (clears the {verdict.threshold_xp.toFixed(
				1
			)} xP threshold{hitNote}).
		</p>
	</div>
{/if}

<style>
	.verdict-hero {
		max-width: 640px;
		border: 1px solid var(--border);
		border-radius: var(--radius);
		padding: var(--s-4);
		margin: var(--s-4) 0 0;
		background: var(--surface);
	}
	.verdict-hero.hold {
		border-color: rgba(0, 194, 173, 0.5);
		border-left: 4px solid var(--positive);
		background: linear-gradient(160deg, rgba(0, 194, 173, 0.08), transparent 60%), var(--surface);
	}
	.verdict-hero.go {
		border-left: 4px solid var(--giq-magenta-deep);
	}
	.title {
		margin: 0 0 var(--s-1);
		font-weight: 700;
		font-size: var(--step-0);
	}
	.verdict-hero.hold .title {
		color: var(--positive);
	}
	.math {
		margin: 0;
		color: var(--text-muted);
		font-size: var(--step--1);
		font-variant-numeric: tabular-nums;
	}
</style>
