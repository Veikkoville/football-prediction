<script lang="ts">
	import { onMount } from 'svelte';
	import { PLANS, planApprox, startCheckout, type PlanKey } from '$lib/billing';
	import { capture } from '$lib/analytics';
	import { fetchXp, gwXp, type XpResponse } from '$lib/api';
	import { freePremiumWindowActive } from '$lib/auth.svelte';

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

<!-- 🔴 Ikkunan aikana talle sivulle tullaan "Keep it after that" -napista, eli
     kayttajalla ON jo Premium. "Unlock" olisi vaara verbi ja lukisi silta etta
     jotain on kiinni. 🔴 POISTA HAARA 12.9.2026 12:30 UTC jalkeen. -->
{#if freePremiumWindowActive()}
	<h3>Keep Premium after 12 September</h3>
	<p class="muted">
		Nothing is locked right now, so there is no rush. Worth saying plainly: paying today
		starts the subscription today, it does not wait for 12 September, so you would be
		paying for weeks you already have for free. Coming back after the window is the
		cheaper move, and this is only here for anyone who would rather deal with it now.
	</p>
{:else}
	<h3>Unlock GoalIQ Premium</h3>
{/if}
<!--
	4.8 (Villen paatos): molemmat pinnat olivat puolikkaita. Mobiilin
	scoreline-lukko myi VAIN ottelusisaltoa ja tama sivu VAIN FPL:aa, vaikka
	tilaus on yksi ja kattaa molemmat. Mobiilin laajin paywall-pinta (24
	kayttajaa / 7 vrk) konvertoi NOLLAA, ja diagnoosi oli lupaus eika sijainti.
	Molemmat tuotteet nakyvat nyt molemmilla pinnoilla, FPL karkena.
	⚠️ Pinta-pariteetti: parikorjaus on goaliq-app/screens/PredictScreen.tsx +
	lib/i18n/*.ts (vrt. em-dash-ja-pinta-pariteetti).
-->
<p class="muted">
	<strong>FPL:</strong> player expected points (xP), captain ranker, differential finder,
	chip timing, transfer plan chains, edge mode, a live DefCon panel for your own squad
	during a gameweek, shareable image cards and per-gameweek breakdowns.
</p>
<p class="muted">
	<strong>Match model:</strong> full analysis for any fixture across the ten competitions we
	cover, from the Premier League to the Champions League: top-10 most likely scorelines,
	total goals, both teams to score, form and momentum trends, head-to-head record and fair
	value estimates.
</p>
<p class="muted">
	Season pass renews yearly, monthly renews monthly, cancel anytime. One subscription
	covers web, iOS and Android.
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

<!-- 16.8: puolustava rivi. Ikkunan aikana kirjautunut kayttaja ei normaalisti
     paady tanne lainkaan (auth.sub on tosi), mutta jos han paatyy, hanelle ei
     saa myyda hintaan sita mika on juuri nyt ilmaista.
     🔴 POISTA 12.9.2026 12:30 UTC jalkeen. -->
{#if freePremiumWindowActive()}
	<p class="banner success">
		Premium is free until the GW4 deadline on 12 September. You do not need to pay yet.
	</p>
{/if}

<div class="plans">
	{#each Object.entries(PLANS) as [key, plan] (key)}
		{@const approx = planApprox(key as PlanKey)}
		<div class="plan">
			<!-- 31.7: UK/US-kävijälle valuuttalikiarvo (Adaptive Pricing hoitaa
			     checkoutin tarkan summan kävijän valuutassa) -->
			<span class="muted">{plan.hint}{approx ? ` · ${approx}` : ''}</span>
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
		color: var(--giq-rust);
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
