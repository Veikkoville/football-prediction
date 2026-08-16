<script lang="ts">
	import { onMount } from 'svelte';
	import { fetchXp, gwXp, type XpResponse } from '$lib/api';
	import { capture } from '$lib/analytics';
	import { PLANS, planApprox, startCheckout, type PlanKey } from '$lib/billing';
	import Provenance from './Provenance.svelte';
	import { preferredStore, appCtaLabel, STORE_URL } from '$lib/appHandoff';
	import { freePremiumWindowActive } from '$lib/auth.svelte';

	// #95: login-seinä myy ennen lomaketta — sama arvolupaus kuin mobiilin
	// UpgradeCard-paywallissa. Copy 1:1 paywall.bullet_* -en-avaimista
	// (goaliq-app/lib/i18n/en.ts) → yksi lähde arvoviestille molemmilla pinnoilla.
	// PREMIUM-KARKI (14.8, mitattu): karki oli xP. Expected points on ILMAINEN
	// kolmella kilpailijalla (Fine Line, FPL Pundit, OddAlerts), joten listan
	// ensimmainen rivi lupasi asiaa jonka lukija saa muualta maksutta. Karkeen
	// se mita muilla EI ole. COPY-SYNC: sama jarjestys mobiilin
	// ProfileScreen.tsx:n bullets-listassa.
	// WEB-TO-APP-CTA (14.8): puhelimella sovellus on ensisijainen ostopolku.
	// Luetaan onMountissa, koska `navigator` ei ole olemassa staattisessa
	// prerenderissa — SSR-aikainen luku kaataisi buildin.
	let appStore = $state<ReturnType<typeof preferredStore>>(null);
	onMount(() => {
		appStore = preferredStore(navigator?.userAgent);
		if (appStore) capture('app_handoff_shown', { store: appStore });
	});

	const BULLETS = [
		'Where the gap to the model came from: captaincy, bench points and autosubs, round by round',
		'Which players actually close the gap on your mini-league rival, and whether they already have them',
		'Per-player xP projections for every gameweek',
		// WHY-THIS-PICK (14.8): heti xP:n jalkeen, koska se selittaa juuri sen
		// luvun. Kattavuus (150) on copyssa: premium nakee ~505 pelaajaa, joten
		// "jokaiselle" olisi kate jota ei ole. Synkattu paywall.bullet_why:hyn.
		'Why a projection looks the way it does, in one line, for the top 150 by Total xP',
		'Captain ranker with top picks',
		'Share as image: post-ready cards from your XI, the captain ranker, the value ranking and leaderboards',
		'Differential finder: low ownership, high xP',
		'Multi-gameweek transfer planner and plan chains',
		'Chip timing: best window for Wildcard, Bench Boost, Triple Captain and Free Hit',
		'Edge mode: protect or climb your rank with ownership-weighted picks',
		'Watchlist for up to 50 players: track everyone you are deciding on',
		'Player compare: up to four players side by side',
		'CSV export of the full projection set',
		// 4.8: synkattu paywall.bullet_match-avaimeen (goaliq-app/lib/i18n/en.ts).
		// Kommentti ylla lupaa 1:1-vastaavuuden, ja 29.7 todettiin ettei yksikaan
		// portti nae pintojen valista eroa -> se loytyy vain lukemalla molemmat.
		'Full match analysis: top-10 scorelines, total goals, both teams to score, form & momentum and head-to-head'
	];

	let teaser = $state<XpResponse | null>(null);
	// #101: suora osto ilman tiliä — hinta + Osta-napit esikatselussa.
	// Kirjautumaton → guest checkout (tili syntyy maksun jälkeen).
	let buyError = $state<string | null>(null);
	let busy = $state<PlanKey | null>(null);

	async function buy(plan: PlanKey) {
		busy = plan;
		buyError = await startCheckout(plan, 'pro_web_preview');
		busy = null;
	}

	onMount(() => {
		// Sama funneli-event kuin Paywall, oma source erottaa login-seinän
		// (kirjautumaton) varsinaisesta plan-valitsimesta (kirjautunut, ei subia).
		capture(
			'paywall_shown',
			{ source: 'pro_web_login_gate' },
			'paywall_shown_login_gate'
		);
		fetchXp().then((d) => (teaser = d), () => {});
	});

	// Sama top-3-poiminta kuin Paywall-teaser: nimet näkyvät, arvot lukossa
	// (•.••) → ei premium-arvovuotoa, mutta käyttäjä näkee MITÄ avaa.
	let top3 = $derived.by(() => {
		if (!teaser?.meta?.available) return [];
		const gw = teaser.meta.next_gameweek;
		return [...teaser.players].sort((a, b) => gwXp(b, gw) - gwXp(a, gw)).slice(0, 3);
	});
</script>

<section class="preview card" aria-label="What GoalIQ Premium includes">
	<h3>What Premium unlocks</h3>

	<!-- 16.8: tama on ANONYYMIN kavijan nakyma, eli se ainoa paikka jossa
	     ikkunasta voi kertoa jollekulle joka ei ole viela kirjautunut. Ilman
	     tata koko ilmaisikkuna oli nakyvissa vasta sille joka oli jo saanut
	     sen. Ilmoitus on hintojen YLAPUOLELLA tarkoituksella.
	     🔴 POISTA 12.9.2026 12:30 UTC jalkeen. -->
	{#if freePremiumWindowActive()}
		<p class="banner success">
			Premium is free until the GW4 deadline on 12 September, so GW1 to GW3. Create a free
			account below and it's on. No card, nothing to cancel.
		</p>
	{/if}
	<ul class="bullets">
		{#each BULLETS as b (b)}
			<li>{b}</li>
		{/each}
	</ul>

	<!-- 24.7 conviction-löydös: perumiset tapahtuvat maksuhetkellä → proof
	     suoraan ostopäätöksen viereen (ei numeroita jotka vanhenisivat) -->
	<p class="muted proof">
		Built on a publicly tracked match model: every prediction is logged before kick-off
		and graded afterwards, hits and misses in the same place. Nothing gets edited once
		kick-off comes. <a href="/fpl/model-xi">See the model's own squad</a>.
	</p>

	{#if top3.length > 0}
		<div class="teaser" aria-label="Locked expected points preview">
			<table>
				<thead>
					<tr>
						<th>Player</th>
						<th class="num"><abbr title="Expected points from the GoalIQ match model">xP</abbr> · GW{teaser?.meta.next_gameweek}</th>
					</tr>
				</thead>
				<tbody>
					{#each top3 as p, i (p.id)}
						<tr>
							<td>{i + 1}. {p.web_name} <span class="muted">({p.team_short}, {p.pos})</span></td>
							<td class="num locked-val" aria-label="Locked">•.••</td>
						</tr>
					{/each}
				</tbody>
			</table>
			<span class="lock-pill">
				<svg
					width="12"
					height="12"
					viewBox="0 0 24 24"
					fill="currentColor"
					aria-hidden="true"
				>
					<path
						d="M12 2a5 5 0 0 0-5 5v3H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-8a2 2 0 0 0-2-2h-1V7a5 5 0 0 0-5-5Zm-3 8V7a3 3 0 1 1 6 0v3H9Z"
					/>
				</svg>
				Unlocks with Premium
			</span>
		</div>
	{/if}

	<Provenance />

	<!-- #101: osto suoraan esikatselusta — ei pakko-sign-iniä. Stripe kerää
	     emailin ja maksun; tili + kirjautumislinkki tulevat maksun jälkeen. -->
	<!-- WEB-TO-APP-CTA (14.8, mitattu): puhelimella sovellus ENSIN, Stripe jaa
	     alle. Molemmat polut jaavat nakyviin — vain jarjestys vaihtuu, ja
	     kumpikin napautus kirjaa oman eventtinsa, jotta tama on peruttavissa
	     mittauksen perusteella eika mielipiteen. -->
	{#if appStore}
		<a
			class="app-cta"
			href={STORE_URL[appStore]}
			rel="noopener"
			onclick={() => capture('app_handoff_tapped', { store: appStore })}
		>
			{appCtaLabel(appStore)}
		</a>
		<p class="muted app-cta-note">
			Same subscription either way. On your phone the store already has your
			payment details, so it takes a few seconds.
		</p>
	{/if}

	<!-- 🔴 Villen havainto 16.8: "heti alkuun ihminen menee pro sivuille niin
	     matkastaan premium 25 EUR naamaan". Ikkunan aikana ensimmainen nappi
	     oli "Get Premium: 25 EUR / year", eli sivu pyysi rahaa asiasta joka on
	     juuri nyt ilmainen. Ostopolku ei saa kadota - joku haluaa maksaa heti
	     ja pitaa sen - mutta se ei ole ikkunan aikana ensisijainen teko.
	     🔴 POISTA WRAPPER 12.9.2026 12:30 UTC jalkeen (jata .plans-lohko). -->
	{#snippet planButtons(forceSecondary: boolean)}
		<div class="plans">
			{#each Object.entries(PLANS) as [key, plan] (key)}
				{@const approx = planApprox(key as PlanKey)}
				<div class="plan">
					<!-- 31.7: UK/US-kävijälle valuuttalikiarvo (Adaptive Pricing hoitaa
					     checkoutin tarkan summan kävijän valuutassa) -->
					<span class="muted">{plan.hint}{approx ? ` · ${approx}` : ''}</span>
					<button
						class={!forceSecondary && key === 'season' ? 'primary' : 'secondary'}
						disabled={busy !== null}
						onclick={() => void buy(key as PlanKey)}
					>
						{busy === key ? 'Opening checkout…' : `Get Premium: ${plan.label}`}
					</button>
				</div>
			{/each}
		</div>
	{/snippet}

	{#if freePremiumWindowActive()}
		<details class="pay-later">
			<summary>Rather pay now and keep Premium after 12 September?</summary>
			{@render planButtons(true)}
		</details>
	{:else}
		{@render planButtons(false)}
	{/if}
	<!-- #102: rehellinen copy — tili LUODAAN oston jälkeen (webhook provisioi),
	     joten "No account needed" oli faktavirhe. -->
	{#if freePremiumWindowActive()}
		<!-- Ikkunan aikana "skip the signup" on suoraan vastakkainen ohje kuin
		     se jonka haluamme: tili ON se polku. 🔴 POISTA 12.9.2026 12:30 UTC. -->
		<p class="muted no-account">
			After 12 September it is {PLANS.monthly.label} or {PLANS.season.label}. One subscription
			covers web, iOS and Android, and you can cancel anytime.
		</p>
	{:else}
		<p class="muted no-account">
			Skip the signup: pay with Stripe and we'll set up your account and email you a sign-in
			link. Cancel anytime. One subscription covers web, iOS and Android.
		</p>
	{/if}
	{#if buyError}
		<p class="banner error">{buyError}</p>
	{/if}
</section>

<style>
	.preview {
		max-width: 460px;
		margin-bottom: var(--s-4);
	}
	.preview h3 {
		margin-top: 0;
	}
	.bullets {
		margin: 0 0 var(--s-4);
		padding: 0;
		list-style: none;
		display: grid;
		gap: var(--s-2);
	}
	.bullets li {
		position: relative;
		padding-left: var(--s-4);
		font-size: var(--step--1);
	}
	.bullets li::before {
		content: '◆';
		position: absolute;
		left: 0;
		color: var(--giq-rust);
		font-size: 0.7em;
		top: 0.35em;
	}
	/* Lukittu xP-teaser: rivit himmennetty + lukko-pilleri overlayna →
	   käyttäjä näkee taulukon muodon muttei arvoja (sama •.••-kieli kuin
	   Paywall/RateTeam-teaserit) */
	.teaser {
		position: relative;
		border: 1px solid var(--border);
		border-radius: var(--radius);
		overflow: hidden;
		margin-bottom: var(--s-4);
	}
	.teaser table {
		width: 100%;
	}
	.teaser tbody {
		opacity: 0.75;
	}
	.locked-val {
		color: var(--giq-rust);
		font-weight: 700;
		letter-spacing: 2px;
	}
	.lock-pill {
		position: absolute;
		top: 50%;
		left: 50%;
		transform: translate(-50%, -50%);
		display: inline-flex;
		align-items: center;
		gap: var(--s-1);
		background: var(--giq-ink);
		color: var(--giq-cream);
		border-radius: var(--radius);
		padding: var(--s-1) var(--s-3);
		font-size: var(--step--1);
		font-weight: 700;
		white-space: nowrap;
		box-shadow: var(--shadow-1);
		pointer-events: none;
	}
	.lock-pill svg {
		color: var(--accent);
	}
	.app-cta {
		display: block;
		margin: 0 0 0.5rem;
		padding: 0.85rem 1rem;
		border-radius: 10px;
		background: var(--accent, #e5006d);
		color: #fff;
		font-weight: 600;
		text-align: center;
		text-decoration: none;
	}
	.app-cta-note {
		margin: 0 0 1rem;
		font-size: 0.8rem;
	}
	.plans {
		display: flex;
		flex-wrap: wrap;
		gap: var(--s-4);
		margin-top: var(--s-4);
	}
	.plan {
		display: grid;
		gap: var(--s-1);
		justify-items: start;
	}
	.no-account {
		margin-top: var(--s-3);
		font-size: var(--step--1);
	}
</style>
