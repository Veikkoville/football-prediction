<script lang="ts">
	/**
	 * WeeklyActions — FM-silmukan etuovi (web). Mobiilin
	 * `components/WeeklyActions.tsx` -vastine.
	 *
	 * Määrittely: goaliq-app/cos-reports/team-manager-fm-loop-maarittely-2026-07-27.md §3b(ii)
	 *
	 * Appissa on 14 fantasy-endpointtia. Se on työkalupakki, ja työkalupakki on
	 * syy avata sivu silloin kun sinulla on JO kysymys. Tämä antaa syyn avata
	 * se tiistaina kun kysymystä ei vielä ole.
	 *
	 * Säännöt identtiset mobiilin kanssa: silmukan lopputulos ei saa riippua
	 * siitä kummalla pinnalla päätös kirjattiin.
	 */
	import { auth } from '$lib/auth.svelte';
	import {
		isOpenForLogging,
		loadDecisions,
		logDecision,
		type DecisionKind,
		type StoredDecision
	} from '$lib/fplDecisions';

	export interface WeeklyAction {
		kind: DecisionKind;
		label: string;
		modelText: string;
		modelChoice: Record<string, unknown>;
		rationale?: string;
	}

	let {
		gw,
		deadlineUtc,
		actions,
		onFollowTransfer,
		refreshToken
	}: {
		gw: number | null;
		deadlineUtc: string | null;
		actions: WeeklyAction[];
		/**
		 * 29.7 (Villen havainto 28.7: "painaa do it, niin se ei muuta
		 * kokoonpanossa sitä pelaajaa"). Kutsutaan kun siirtopäätös kirjattiin
		 * followed-tilassa — parent soveltaa siirron suunniteltuun joukkueeseen
		 * SAMALLA setPlan-polulla kuin Apply-nappi (#121), jolloin portit
		 * (budjetti, duplikaatit) pysyvät yhdessä paikassa. true = sovellettu,
		 * jolloin käyttäjä saa vahvistuksen.
		 */
		onFollowTransfer?: (choice: Record<string, unknown>) => boolean;
		/**
		 * Silmukka-bugi #8 (30.7): parent voi päivittää kirjattua päätöstä
		 * kortin ohi (managerin kapteeninvaihto). Kun token muuttuu,
		 * logged-tila ladataan uudelleen.
		 */
		refreshToken?: number;
	} = $props();

	let logged = $state<Record<string, StoredDecision>>({});
	let busy = $state<string | null>(null);
	let note = $state<string | null>(null);
	// Silmukka-bugi #8 (30.7): kirjattu päätös EI lukitu ensimmäiseen
	// klikkaukseen — kanta upserttaa deadlineen asti, ja lukitus kuuluu
	// deadlinelle. editing[kind] avaa napit uudelleen "Change"-painalluksesta.
	let editing = $state<Record<string, boolean>>({});

	let open = $derived(isOpenForLogging(deadlineUtc));

	async function refresh() {
		if (!auth.user || gw == null) return;
		const rows = await loadDecisions(gw);
		const byKind: Record<string, StoredDecision> = {};
		for (const r of rows) byKind[r.kind] = r;
		logged = byKind;
	}

	$effect(() => {
		void auth.user;
		void gw;
		void refreshToken;
		refresh();
	});

	async function record(a: WeeklyAction, followed: boolean) {
		if (gw == null || !deadlineUtc) return;
		busy = a.kind;
		note = null;
		const res = await logDecision({
			gw,
			kind: a.kind,
			modelChoice: a.modelChoice,
			// "Eri valinta" kirjataan aikeena: käyttäjä ei ole vielä kertonut
			// MITÄ hän tekee sen sijaan. Silmukan kevyin sisääntulo.
			userChoice: followed ? a.modelChoice : { deviated: true },
			deadlineUtc
		});
		busy = null;
		if (res.ok) {
			editing = { ...editing, [a.kind]: false };
			// FM-silmukka: "I'll do this" siirrolle päivittää myös suunnitellun
			// joukkueen — päätös joka ei muuta mitään ei ole päätös. Vain
			// onnistuneen kirjauksen jälkeen: loki ja joukkue pysyvät synkassa.
			if (followed && a.kind === 'transfer' && onFollowTransfer) {
				if (onFollowTransfer(a.modelChoice)) {
					note = 'Applied to your planned squad on GoalIQ. Remember to make the transfer in FPL too.';
				}
			}
			await refresh();
		} else {
			note =
				res.reason === 'locked'
					? 'This gameweek is locked. Decisions can only be logged before the deadline, and that is what makes the comparison mean anything.'
					: res.reason === 'auth'
						? 'Sign in to log your decisions.'
						: "Couldn't save that. Try again in a moment.";
		}
	}
</script>

{#if gw != null && actions.length > 0}
	<section class="weekly">
		<!-- 28.7: monikkobugi. Livesivulla luki "1 things to do this week", ja
	     yksi tehtava on esikaudella tavallisin tila. -->
			<h3>
				{actions.length}
				{actions.length === 1 ? 'thing' : 'things'} to do this week
			</h3>
		{#if !open}
			<p class="muted locked">
				This gameweek is locked. Decisions can only be logged before the deadline, and that is what
				makes the comparison mean anything.
			</p>
		{/if}

		{#each actions as a (a.kind)}
			{@const rec = logged[a.kind]}
			<div class="row">
				<div class="body">
					<span class="kind">{a.label}</span>
					<p class="model">The model says: {a.modelText}</p>
					{#if a.rationale}<p class="muted why">{a.rationale}</p>{/if}
					{#if rec}
						<p class="done">
							{rec.followed ? 'Logged: following the model' : 'Logged: going your own way'}
						</p>
					{/if}
				</div>

				{#if !auth.user}
					<span class="muted hint">Sign in to log</span>
				{:else if open && (!rec || editing[a.kind])}
					<div class="btns">
						<button type="button" class="primary" disabled={busy === a.kind}
							onclick={() => record(a, true)}>I'll do this</button
						>
						<button type="button" disabled={busy === a.kind} onclick={() => record(a, false)}
							>Doing something else</button
						>
						<!-- Muutoksen voi perua ilman kirjoitusta — vanha kirjaus jää. -->
						{#if rec}
							<button
								type="button"
								disabled={busy === a.kind}
								onclick={() => (editing = { ...editing, [a.kind]: false })}
								>Keep as logged</button
							>
						{/if}
					</div>
				{:else if open && rec}
					<!-- #8: kirjattua päätöstä voi muuttaa deadlineen asti. -->
					<button type="button" onclick={() => (editing = { ...editing, [a.kind]: true })}
						>Change</button
					>
				{/if}
			</div>
		{/each}

		{#if note}<p class="muted">{note}</p>{/if}

		<!-- Ei koskaan piiloteta sitä mitä nappi EI tee. -->
		<p class="muted foot">
			Logging keeps a record of your call against the model's. Following a transfer also updates
			your planned squad here on GoalIQ. Nothing changes in your actual Fantasy Premier League
			team, so make the move there yourself.
		</p>
	</section>
{/if}

<style>
	.weekly {
		border: 1px solid var(--border);
		border-radius: var(--radius);
		padding: var(--s-4);
		margin: var(--s-4) 0;
		background: var(--surface);
	}
	h3 {
		margin: 0 0 var(--s-3);
		font-size: var(--step-1);
	}
	.locked {
		font-style: italic;
		margin: 0 0 var(--s-3);
	}
	.row {
		display: flex;
		gap: var(--s-3);
		align-items: flex-start;
		justify-content: space-between;
		padding: var(--s-3) 0;
		border-top: 1px solid var(--border);
		flex-wrap: wrap;
	}
	.body {
		flex: 1;
		min-width: 14rem;
	}
	.kind {
		font-size: var(--step--1);
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: var(--text-muted);
		font-weight: 700;
	}
	.model {
		margin: 0.15rem 0 0;
	}
	.why {
		margin: 0.2rem 0 0;
		font-size: var(--step--1);
	}
	.done {
		margin: 0.35rem 0 0;
		color: var(--positive);
		font-weight: 600;
		font-size: var(--step--1);
	}
	.hint {
		font-size: var(--step--1);
	}
	.btns {
		display: flex;
		gap: var(--s-2);
		flex-wrap: wrap;
	}
	button {
		font: inherit;
		font-size: var(--step--1);
		padding: 0.35em 0.9em;
		border-radius: var(--radius);
		border: 1px solid var(--border);
		background: transparent;
		color: var(--text-muted);
		cursor: pointer;
	}
	button.primary {
		background: var(--accent);
		border-color: var(--accent);
		color: var(--accent-contrast);
		font-weight: 700;
	}
	button:disabled {
		opacity: 0.6;
		cursor: default;
	}
	.foot {
		margin: var(--s-3) 0 0;
		font-size: var(--step--1);
	}
</style>
