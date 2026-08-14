<script lang="ts">
	/**
	 * BeatTheModel — kauden "sinä vs malli" -tuloskortti (V1, web).
	 * Mobiilin components/BeatTheModel.tsx -vastine; säännöt identtiset.
	 *
	 * Määrittely: goaliq-app/cos-reports/beat-the-model-maarittely-2026-07-29.md
	 * Silmukan askel 5: kierros ratkeaa → tämä kertoo kumpi oli oikeassa.
	 * Klientti ei laske pisteitä — se summaa backend-graderin immutable-tulokset.
	 *
	 * REHELLISYYS: molemmat suunnat samalla painolla, gradaamattomat kerrotaan
	 * eikä arvata, ennen ensimmäistä gradausta sanotaan suoraan milloin tulokset
	 * tulevat. FREE: tuloskortti on silmukan palkinto, ei myyntimuuri.
	 */
	import { auth } from '$lib/auth.svelte';
	import { capture } from '$lib/analytics';
	import {
		latestDebrief,
		loadDecisions,
		seasonScore,
		whatIfRows,
		type StoredDecision
	} from '$lib/fplDecisions';
	import {
		EMPTY_PREFS,
		loadPrefs,
		savePrefs,
		pushRemotePrefsSoon,
		type FplPrefs
	} from '$lib/prefs';

	let rows = $state<StoredDecision[] | null>(null);
	// V4 kauden tavoite (FM: johtokunnan odotukset). Sama prefs-objekti kuin
	// watchlistilla — eri lohko, sama tallennus- ja synkkapolku.
	let prefs = $state<FplPrefs>({ ...EMPTY_PREFS });
	let targetText = $state('');

	// 30.7 digest-instrumentointi: kortin näyttö kerran per mount kun data on
	// ratkennut. SAMA eventtinimi + kentät kuin mobiilissa (pariteetti).
	let viewedFired = false;

	$effect(() => {
		void auth.user;
		if (!auth.user) {
			rows = null;
			return;
		}
		loadDecisions().then((r) => {
			rows = r;
			if (!viewedFired) {
				viewedFired = true;
				capture('beat_scoreboard_viewed', {
					decisions: r.length,
					graded: r.filter((x) => x.graded_at != null).length
				});
			}
		});
		prefs = loadPrefs();
	});

	function saveObjective(value: number | null) {
		prefs = {
			...prefs,
			objective: value != null ? { kind: 'overall_rank', value } : null
		};
		savePrefs(prefs);
		pushRemotePrefsSoon(prefs);
	}

	let score = $derived(rows ? seasonScore(rows) : null);
	let gradedRows = $derived(
		(rows ?? []).filter(
			(r) =>
				r.graded_at != null &&
				typeof r.model_points === 'number' &&
				typeof r.user_points === 'number'
		)
	);
	let debrief = $derived(rows ? latestDebrief(rows) : null);
	// V2 päätöspäiväkirja: mitä poikkeaminen maksoi tai tuotti. Premium —
	// tuloskortti itse pysyy ilmaisena (V1-linjaus).
	let whatIf = $derived(rows ? whatIfRows(rows) : []);
</script>

{#if auth.user && rows != null && score != null}
	<section class="beat">
		<h3>Your calls vs the model</h3>
		<p class="sub">Only the calls you logged, decision by decision.</p>

		{#if rows.length === 0}
			<p class="muted">Log your first call above and the season scoreboard starts here.</p>
		{:else if score.gradedCount === 0}
			<p class="muted">
				Your logged calls get graded once the gameweek finishes. First scores land after GW1.
			</p>
		{:else}
			<div class="totals">
				<div><span class="lbl">You</span><span class="num">{score.userTotal.toFixed(1)}</span></div>
				<div>
					<span class="lbl">Model</span><span class="num">{score.modelTotal.toFixed(1)}</span>
				</div>
			</div>
			<p class="delta" class:ahead={score.delta > 0} class:behind={score.delta < 0}>
				{#if score.delta > 0}
					You are {score.delta.toFixed(1)} points ahead over {score.gradedCount} graded calls
				{:else if score.delta < 0}
					The model is {Math.abs(score.delta).toFixed(1)} points ahead over {score.gradedCount} graded
					calls
				{:else}
					Level with the model over {score.gradedCount} graded calls
				{/if}
			</p>
			{#if debrief}
				<!-- V2 GW-debrief: viimeisin ratkennut kierros. Lause johdetaan
				     deltasta deterministisesti — UI ei keksi narratiivia. -->
				<div class="debrief">
					<span class="debrief-title">GW{debrief.gw} debrief</span>
					<p class="debrief-sentence">
						{#if debrief.delta > 0}
							Your calls beat the model by {debrief.delta.toFixed(1)} points in GW{debrief.gw}.
						{:else if debrief.delta < 0}
							The model's calls would have scored {Math.abs(debrief.delta).toFixed(1)} more in GW{debrief.gw}.
						{:else}
							You and the model came out level in GW{debrief.gw}.
						{/if}
					</p>
					<ul>
						{#each debrief.rows as r (`${r.gw}-${r.kind}`)}
							<li>
								<span class="muted">{r.kind}</span>
								<span>you {(r.user_points as number).toFixed(1)} · model {(r.model_points as number).toFixed(1)}</span>
							</li>
						{/each}
					</ul>
				</div>
			{/if}
			<ul>
				{#each gradedRows.filter((r) => r.gw !== debrief?.gw).slice(0, 5) as r (`${r.gw}-${r.kind}`)}
					<li>
						<span class="muted">GW{r.gw} · {r.kind}</span>
						<span>you {(r.user_points as number).toFixed(1)} · model {(r.model_points as number).toFixed(1)}</span>
					</li>
				{/each}
			</ul>
		{/if}

		{#if whatIf.length > 0 && auth.sub}
			<!-- Decision journal (V2): ei uutta laskentaa, sama graderin luku
			     toisin esitettynä. Molemmat suunnat samalla painolla. -->
			<div class="journal">
				<span class="debrief-title">Decision journal</span>
				<ul>
					{#each whatIf as w (`${w.gw}-${w.kind}`)}
						<li>
							<span class="muted">GW{w.gw} · you {w.text}</span>
							<span class="d" class:ahead={w.delta > 0} class:behind={w.delta < 0}>
								{w.delta > 0 ? '+' : ''}{w.delta.toFixed(1)}
							</span>
						</li>
					{/each}
				</ul>
			</div>
		{/if}

		{#if score.ungradableCount > 0}
			<p class="muted small">
				{score.ungradableCount} calls could not be graded without an FPL entry ID.
			</p>
		{/if}

		<!-- V4 kauden tavoite. Rank-trendi tavoitetta vasten tulee kun kaudella
		     on rank-dataa — siihen asti sanotaan se suoraan. -->
		<div class="objective">
			<span class="debrief-title">Season target</span>
			{#if prefs.objective != null}
				<div class="objective-row">
					<span class="objective-value">Top {prefs.objective.value.toLocaleString('en-GB')} overall</span>
					<button type="button" class="quiet" onclick={() => saveObjective(null)}>Clear</button>
				</div>
			{:else}
				<div class="objective-row">
					<input
						type="text"
						inputmode="numeric"
						placeholder="Overall rank target, e.g. 1000000"
						bind:value={targetText}
					/>
					<button
						type="button"
						class="set"
						onclick={() => {
							const v = parseInt(targetText.replace(/[^0-9]/g, ''), 10);
							if (Number.isFinite(v) && v > 0) {
								saveObjective(v);
								targetText = '';
							}
						}}>Set</button
					>
				</div>
			{/if}
			<p class="muted small">Rank tracking against your target starts once the season is under way.</p>
		</div>
	</section>
{/if}

<style>
	.beat {
		/* Sama kohtelu kuin track record -lohkolla: kauden vertailu on
		   luottamusväite, ei yksi kortti muiden joukossa. */
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
	/* Kertoo MITA tama paneeli laskee (PAATOKSET), erotuksena SeasonRacesta
	   joka laskee JOUKKUEET. Ilman tata kaksi korttia allekkain lukee
	   duplikaatilta ja niiden eriavat luvut bugilta. */
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
	.delta.ahead {
		color: var(--positive);
	}
	.delta.behind {
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
		gap: var(--s-3);
		padding: 0.3rem 0;
		border-top: 1px solid var(--border);
		font-size: var(--step--1);
	}
	.small {
		font-size: var(--step--2);
		margin: var(--s-2) 0 0;
	}
	.debrief {
		border-top: 1px solid var(--border);
		padding-top: var(--s-2);
		margin-bottom: var(--s-2);
	}
	.debrief-title {
		font-size: var(--step--2);
		text-transform: uppercase;
		letter-spacing: 0.08em;
		color: var(--text-muted);
		font-weight: 700;
	}
	.debrief-sentence {
		margin: 0.2rem 0 0.3rem;
		font-size: var(--step--1);
	}
	.journal {
		border-top: 1px solid var(--border);
		padding-top: var(--s-2);
		margin-top: var(--s-2);
	}
	.d {
		font-weight: 700;
	}
	.d.ahead {
		color: var(--positive);
	}
	.d.behind {
		color: var(--negative);
	}
	.objective {
		border-top: 1px solid var(--border);
		padding-top: var(--s-2);
		margin-top: var(--s-2);
	}
	.objective-row {
		display: flex;
		align-items: center;
		gap: var(--s-3);
		margin-top: 0.3rem;
	}
	.objective-value {
		flex: 1;
		font-weight: 700;
	}
	.objective input {
		flex: 1;
		font: inherit;
		font-size: var(--step--1);
		padding: 0.35em 0.6em;
		border: 1px solid var(--border);
		border-radius: var(--radius);
		background: var(--surface-alt, transparent);
		color: var(--text);
	}
	.objective button {
		font: inherit;
		font-size: var(--step--1);
		border: none;
		background: transparent;
		cursor: pointer;
	}
	.objective button.set {
		color: var(--teal, #2ed6c2);
		font-weight: 700;
	}
	.objective button.quiet {
		color: var(--text-muted);
	}
</style>
