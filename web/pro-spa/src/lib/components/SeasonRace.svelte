<script lang="ts">
	/**
	 * SeasonRace — Beat the Model V2: mallin lukittu joukkue pysyvänä rivaalina.
	 * Mobiilin components/SeasonRace.tsx -vastine; säännöt ja copy identtiset.
	 *
	 * Spec: goaliq-app/cos-reports/beat-the-model-v2-kausikisa-spec-2026-08-13.md
	 * V1 (BeatTheModel.svelte) vertaa PÄÄTÖKSIÄ, tämä vertaa JOUKKUEITA.
	 *
	 * Klientti ei laske pisteitä: kaikki luvut tulevat /api/fantasy/model-race
	 * -endpointilta, joka lukee backendin gradaamaa immutable-lokia. Mallin rivi
	 * on lukittu ennen deadlinea ja todistettavissa git-historiasta.
	 *
	 * REHELLISYYS:
	 *  - ennen ensimmäistä gradausta ei arvata, kerrotaan milloin luvut tulevat
	 *  - kierros jota ei ole omassa historiassa jää tyhjäksi, EI nollaksi
	 *  - malli ei pelaa chippejä ja se sanotaan näkyvästi, muuten ero näyttää
	 *    väärältä chip-viikkoina
	 *  - tappio näytetään yhtä suurella painolla kuin voitto
	 */
	import { fetchModelRace, type ModelRaceResponse } from '$lib/api';
	import { capture } from '$lib/analytics';
	import { fplEntry } from '$lib/fplEntry.svelte';

	let data = $state<ModelRaceResponse | null>(null);
	let failed = $state(false);
	let loadedKey = $state<string | null>(null);
	let viewedFired = false;

	$effect(() => {
		const raw = (fplEntry.entry || fplEntry.savedEntry || '').trim();
		const entry = /^\d{1,10}$/.test(raw) ? Number(raw) : null;
		const key = String(entry ?? '-');
		if (loadedKey === key) return;
		loadedKey = key;
		failed = false;
		fetchModelRace(entry)
			.then((r) => {
				data = r;
				if (!viewedFired && r.meta.available) {
					viewedFired = true;
					capture('season_race_viewed', {
						graded_gws: r.meta.graded_gws,
						compared_gws: r.meta.compared_gws ?? 0,
						has_entry: entry != null,
						masked: r.meta.masked
					});
				}
			})
			.catch(() => {
				// Fail-safe (Hub-oppi #52): paneeli katoaa, työkalut jäävät.
				failed = true;
				data = null;
			});
	});

	let rows = $derived(data ? [...data.gameweeks].reverse() : []);
	let diff = $derived(data?.totals.diff ?? null);
</script>

{#if data && !failed}
	<section class="race">
		<h3>Season race: your squad vs the model's</h3>
		<p class="sub">Every point your team scored, gameweek by gameweek.</p>

		{#if !data.meta.available}
			<p class="muted">{data.meta.note}</p>
		{:else}
			<div class="totals">
				<div>
					<span class="lbl">Model</span><span class="num">{data.totals.model}</span>
				</div>
				{#if data.totals.you != null}
					<div><span class="lbl">You</span><span class="num">{data.totals.you}</span></div>
				{/if}
			</div>

			{#if diff != null}
				<p class="delta" class:ahead={diff > 0} class:behind={diff < 0}>
					{#if diff > 0}
						You are {diff} points ahead of the model after {data.meta.compared_gws} gameweeks
					{:else if diff < 0}
						The model is {Math.abs(diff)} points ahead after {data.meta.compared_gws} gameweeks
					{:else}
						Level with the model after {data.meta.compared_gws} gameweeks
					{/if}
				</p>
			{:else if data.meta.note}
				<p class="muted">{data.meta.note}</p>
			{/if}

			<ul>
				{#each rows as r (r.gw)}
					<li>
						<span class="gw">GW{r.gw}</span>
						<span class="pts">
							{#if r.your_points != null}
								you {r.your_points} · model {r.model_points}
							{:else}
								model {r.model_points}
							{/if}
							{#if r.fpl_average != null}
								<span class="muted"> · avg {r.fpl_average}</span>
							{/if}
						</span>
						{#if r.diff != null}
							<span class="d" class:ahead={r.diff > 0} class:behind={r.diff < 0}>
								{r.diff > 0 ? '+' : ''}{r.diff}
							</span>
						{:else}
							<span class="d muted">-</span>
						{/if}
					</li>
					{#if r.model_autosubs != null}
						<!-- Premium: missä ero syntyi. Ilman premiumia nämä kentät
						     eivät tule payloadissa lainkaan (backend maskaa). -->
						<li class="detail">
							<span class="muted">
								model captain {r.model_captain_reason === 'vice' ? '(vice)' : ''} +{r.model_captain_points}
								· bench {r.model_bench_points}
								{#if r.model_autosubs.length}· {r.model_autosubs.length} autosub{r.model_autosubs
										.length > 1
										? 's'
										: ''}{/if}
								{#if r.your_transfer_cost}· your hits −{r.your_transfer_cost}{/if}
							</span>
						</li>
					{/if}
				{/each}
			</ul>

			{#if data.meta.masked}
				<p class="muted small">
					Premium shows where the gap came from: captaincy, bench points and autosubs, round by
					round.
				</p>
			{/if}
		{/if}

		{#if !data.meta.model_plays_chips}
			<p class="muted small">
				The model's squad is locked before every deadline and plays no chips.
			</p>
		{/if}
	</section>
{/if}

<style>
	.race {
		/* Sama kohtelu kuin V1-tuloskortilla: kauden vertailu on luottamusväite. */
		border: 2px solid var(--teal, #2ed6c2);
		border-radius: var(--radius);
		padding: var(--s-4);
		margin: var(--s-4) 0;
		background: var(--surface);
	}
	h3 {
		margin: 0 0 var(--s-1);
		font-size: var(--step--1);
		text-transform: uppercase;
		letter-spacing: 0.08em;
		color: var(--text-muted);
	}
	/* Kertoo MITA tama paneeli laskee (JOUKKUEET), erotuksena
	   BeatTheModelista joka laskee PAATOKSET. Ilman tata kaksi korttia
	   allekkain lukee duplikaatilta ja niiden eriavat luvut bugilta. */
	.sub {
		margin: 0 0 var(--s-3);
		font-size: var(--step--1);
		color: var(--text-muted);
	}
	.totals {
		display: flex;
		gap: var(--s-5);
		margin-bottom: var(--s-2);
	}
	.totals div {
		display: flex;
		flex-direction: column;
	}
	.lbl {
		font-size: var(--step--2);
		text-transform: uppercase;
		letter-spacing: 0.08em;
		color: var(--text-muted);
	}
	.num {
		font-size: var(--step-3);
		font-weight: 700;
		color: var(--accent);
	}
	.delta {
		margin: 0 0 var(--s-2);
		font-weight: 600;
	}
	.delta.ahead,
	.d.ahead {
		color: var(--positive);
	}
	.delta.behind,
	.d.behind {
		color: var(--negative);
	}
	ul {
		list-style: none;
		margin: 0;
		padding: 0;
	}
	li {
		display: flex;
		justify-content: space-between;
		align-items: baseline;
		gap: var(--s-3);
		padding: 0.3rem 0;
		border-top: 1px solid var(--border);
		font-size: var(--step--1);
	}
	li.detail {
		border-top: none;
		padding: 0 0 0.3rem;
		font-size: var(--step--2);
	}
	.gw {
		font-weight: 700;
		min-width: 3.5em;
	}
	.pts {
		flex: 1;
	}
	.d {
		font-weight: 700;
		min-width: 3em;
		text-align: right;
	}
	.small {
		font-size: var(--step--2);
		margin: var(--s-2) 0 0;
	}
</style>
