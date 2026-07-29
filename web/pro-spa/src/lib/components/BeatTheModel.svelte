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
	import { loadDecisions, seasonScore, type StoredDecision } from '$lib/fplDecisions';

	let rows = $state<StoredDecision[] | null>(null);

	$effect(() => {
		void auth.user;
		if (!auth.user) {
			rows = null;
			return;
		}
		loadDecisions().then((r) => (rows = r));
	});

	let score = $derived(rows ? seasonScore(rows) : null);
	let gradedRows = $derived(
		(rows ?? []).filter(
			(r) =>
				r.graded_at != null &&
				typeof r.model_points === 'number' &&
				typeof r.user_points === 'number'
		)
	);
</script>

{#if auth.user && rows != null && rows.length > 0 && score != null}
	<section class="beat">
		<h3>You vs the model</h3>

		{#if score.gradedCount === 0}
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
			<ul>
				{#each gradedRows.slice(0, 5) as r (`${r.gw}-${r.kind}`)}
					<li>
						<span class="muted">GW{r.gw} · {r.kind}</span>
						<span>you {(r.user_points as number).toFixed(1)} · model {(r.model_points as number).toFixed(1)}</span>
					</li>
				{/each}
			</ul>
		{/if}

		{#if score.ungradableCount > 0}
			<p class="muted small">
				{score.ungradableCount} calls could not be graded without an FPL entry ID.
			</p>
		{/if}
	</section>
{/if}

<style>
	.beat {
		/* Sama kohtelu kuin track record -lohkolla: kauden vertailu on
		   luottamusväite, ei yksi kortti muiden joukossa. */
		border: 2px solid var(--teal, #2ed6c2);
		border-radius: var(--radius, 0);
		padding: var(--s-4);
		margin: var(--s-4) 0;
		background: var(--surface);
	}
	h3 {
		margin: 0 0 var(--s-3);
		font-size: var(--step--1);
		text-transform: uppercase;
		letter-spacing: 0.08em;
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
</style>
