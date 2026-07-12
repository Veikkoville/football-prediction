<script lang="ts">
	import { onMount } from 'svelte';
	import { PLANS, startCheckout, type PlanKey } from '$lib/billing';
	import { capture } from '$lib/analytics';
	import { fetchXp, gwXp, type XpResponse } from '$lib/api';

	let error = $state<string | null>(null);
	let busy = $state<PlanKey | null>(null);
	let teaser = $state<XpResponse | null>(null);

	onMount(() => {
		// Web-funnel (#12-pariteetti): paywall renderöityy (kerran per lataus)
		capture(
			'paywall_shown',
			{ source: 'pro_web', plans: ['season', 'monthly'] },
			'paywall_shown'
		);
		fetchXp().then((d) => (teaser = d), () => {});
	});

	async function buy(plan: PlanKey) {
		busy = plan;
		error = await startCheckout(plan);
		busy = null;
	}

	let top3 = $derived.by(() => {
		if (!teaser?.meta?.available) return [];
		const gw = teaser.meta.next_gameweek;
		return [...teaser.players].sort((a, b) => gwXp(b, gw) - gwXp(a, gw)).slice(0, 3);
	});
</script>

<h3>Unlock GoalIQ Premium</h3>
<p class="muted">
	Player expected points (xP), captain ranker and per-gameweek breakdowns. Season pass
	renews yearly, monthly renews monthly, cancel anytime. One subscription covers web, iOS
	and Android.
</p>
<p class="muted">
	Already subscribed in the GoalIQ app? Sign in with the same account and Premium is already
	active here.
</p>

{#if top3.length > 0}
	<div class="teaser card">
		<div class="muted">Top xP for GW{teaser?.meta.next_gameweek} (Premium)</div>
		{#each top3 as p, i (p.id)}
			<div class="row">
				<span>{i + 1}. {p.web_name} <span class="muted">({p.team_short}, {p.pos})</span></span>
				<span class="locked" aria-label="Locked">•.••</span>
			</div>
		{/each}
	</div>
{/if}

<div class="plans">
	{#each Object.entries(PLANS) as [key, plan] (key)}
		<div class="plan">
			<span class="muted">{plan.hint}</span>
			<button
				class={key === 'season' ? 'primary' : 'secondary'}
				disabled={busy !== null}
				onclick={() => void buy(key as PlanKey)}
			>
				{busy === key ? 'Opening checkout…' : plan.label}
			</button>
		</div>
	{/each}
</div>

{#if error}
	<p class="banner error">{error}</p>
{/if}

<style>
	.teaser {
		max-width: 460px;
		margin-bottom: var(--s-4);
		padding: var(--s-4);
		display: grid;
		gap: var(--s-1);
	}
	.row {
		display: flex;
		justify-content: space-between;
	}
	.locked {
		color: var(--giq-magenta-deep);
		font-weight: 700;
		letter-spacing: 2px;
	}
	.plans {
		display: flex;
		flex-wrap: wrap;
		gap: var(--s-6);
		margin-top: var(--s-4);
	}
	.plan {
		display: grid;
		gap: var(--s-2);
		justify-items: start;
	}
</style>
