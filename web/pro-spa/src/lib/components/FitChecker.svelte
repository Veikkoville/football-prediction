<script lang="ts">
	import { draftPool, fetchFit, fetchXp, type FitResponse, type XpPoolPlayer } from '$lib/api';
	import { capture } from '$lib/analytics';
	import { saveDraftIds } from '$lib/draft';
	import MethodNote from './MethodNote.svelte';
	import PlayerSearch from './PlayerSearch.svelte';

	// #155 Fit checker (FREE): lukitse 1-3 pakkopelaajaa → paras laillinen
	// runko niiden ympärille + mitä lukitseminen maksaa vs mallin vapaa
	// optimibudjettijoukkue. Ei entry-ID:tä → toimii myös go-live-hetkellä
	// (PI-13). Free-pinnassa EI näytetä per-pelaaja-xP:tä (sama raja kuin
	// muissa free-työkaluissa) — kokonais-xP ja delta näytetään.

	// UX-palaute-erä (25.7) kohta 3: "Save as draft" vie tuloksen 15 ID:tä
	// samaan draft-storageen jota RateTeam käyttää → onOpenRateTeam-callback
	// (FreeView vaihtaa segmentin) ja draft latautuu siellä automaattisesti.
	let { onOpenRateTeam }: { onOpenRateTeam?: () => void } = $props();

	let pool = $state<XpPoolPlayer[]>([]);
	let poolError = $state(false);
	$effect(() => {
		// 14.8: sama pooli kuin draft raterilla — lukitusvalitsin oli rikki
		// samasta syysta (maskattu teaser 10 rivia).
		fetchXp().then(
			(d) => (pool = draftPool(d)),
			() => (poolError = true)
		);
	});

	let locks = $state<(XpPoolPlayer | null)[]>([null, null, null]);
	let query = $state('');
	let result = $state<FitResponse | null>(null);
	let loading = $state(false);
	let error = $state<string | null>(null);

	let chosen = $derived(locks.filter((p): p is XpPoolPlayer => p != null));

	// Sama normalisointi kuin XpTable-haussa (#145/#147-pariteetti, suppea).
	function norm(s: string): string {
		return s
			.normalize('NFD')
			.replace(/[̀-ͯ]/g, '')
			.toLowerCase()
			.replace(/ø/g, 'o')
			.replace(/['’ʼ]/g, '')
			.replace(/[-.]/g, ' ')
			.trim();
	}
	let matches = $derived.by(() => {
		const q = norm(query);
		if (q.length < 2) return [];
		const chosenIds = new Set(chosen.map((p) => p.id));
		return pool
			.filter(
				(p) =>
					!chosenIds.has(p.id) &&
					(norm(p.web_name).includes(q) ||
						(p.full_name ? norm(p.full_name).includes(q) : false) ||
						norm(p.team_short).includes(q))
			)
			.slice(0, 6);
	});

	function addLock(p: XpPoolPlayer) {
		const i = locks.findIndex((l) => l == null);
		if (i === -1) return;
		locks[i] = p;
		query = '';
		result = null;
		error = null;
	}
	function removeLock(i: number) {
		locks[i] = null;
		result = null;
		error = null;
	}

	async function submit() {
		if (chosen.length < 1 || loading) return;
		loading = true;
		error = null;
		draftSaved = false;
		capture('fit_checker_submitted', { locked_n: chosen.length });
		try {
			result = await fetchFit(chosen.map((p) => p.id));
		} catch {
			result = null;
			error = 'Could not build a squad right now. Please try again shortly.';
		} finally {
			loading = false;
		}
	}

	// Kohta 3: tuloksen XI + penkki = tasan 15 ID:tä → jaettu draft-storage.
	let draftSaved = $state(false);
	const draftIds = $derived(
		result ? [...result.xi, ...result.bench].map((p) => p.id) : []
	);
	function saveAsDraft() {
		if (draftIds.length !== 15) return;
		if (saveDraftIds(draftIds)) {
			draftSaved = true;
			capture('fit_saved_as_draft', { locked_n: chosen.length });
		}
	}
</script>

<section class="tool-card">
	<h2>Fit checker</h2>
	<p class="muted">
		Free · Lock 1-3 must-have players and the model builds the strongest valid 15-player
		squad around them, then shows what forcing those picks costs against the same squad
		built with no locks.
		No FPL entry ID needed. Prices come straight from the official FPL API and update the
		moment FPL opens the new season's game.
	</p>

	<MethodNote summary="How the fit is calculated">
		<p>
			The squad is built greedily by horizon expected points (xP) from the same GoalIQ
			match-model projections as everything else on this page, honouring FPL rules: 15
			players, 2/5/5/3 by position, max 3 per club, 100.0m budget with a real bench. The
			comparison squad is built with the identical method and no locks, so the xP cost of
			your locks is like for like. Model projection, not betting advice.
		</p>
	</MethodNote>

	{#if poolError}
		<p class="banner error">Could not load the player pool right now. Please try again shortly.</p>
	{:else}
		<div class="locks">
			{#each locks as lock, i (i)}
				{#if lock}
					<button type="button" class="lock-chip" onclick={() => removeLock(i)}>
						{lock.web_name}
						<span class="muted">{lock.team_short} · {lock.pos}</span>
						<span aria-hidden="true">×</span>
					</button>
				{/if}
			{/each}
		</div>

		{#if chosen.length < 3}
			<!-- UX-palaute-erä kohdat 2+6: jaettu combobox — hinta + owned%
			     riveillä, nuolinäppäimet + Enter/Esc. -->
			<PlayerSearch
				id="fit-search"
				label="Add a must-have player"
				bind:query
				items={matches}
				onSelect={addLock}
			/>
		{/if}

		<button
			type="button"
			class="primary"
			disabled={chosen.length < 1 || loading}
			onclick={submit}
		>
			{loading ? 'Building…' : 'Build my squad'}
		</button>

		{#if error}
			<p class="banner error">{error}</p>
		{/if}

		{#if result && !loading}
			<p class="verdict">{result.message}</p>

			<h3>Best XI around your locks</h3>
			<div class="table-wrap">
				<table>
					<thead>
						<tr><th>Pos</th><th>Player</th><th>Team</th><th class="num">Price</th></tr>
					</thead>
					<tbody>
						{#each result.xi as p (p.id)}
							<tr>
								<td>{p.pos}</td>
								<td
									>{p.web_name}{#if result.locked.some((l) => l.id === p.id)}
										<span class="lock-tag">LOCK</span>{/if}</td
								>
								<td>{p.team_short}</td>
								<td class="num">{p.price.toFixed(1)}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
			<p class="muted bench-line">
				Bench: {result.bench
					.map((p) => `${p.web_name} (${p.team_short}, ${p.price.toFixed(1)})`)
					.join(' · ')}
			</p>

			<dl class="totals">
				<div>
					<dt>XI expected points, next {result.meta.horizon_gw} GWs</dt>
					<dd>{result.totals.xi_xp_horizon.toFixed(1)}</dd>
				</div>
				<div>
					<!-- 29.7: "best" vain kun backend on TODISTANUT sen. Sama portti kuin
					     RateTeamissa; fit kayttaa nyt samaa optimoijaa, joten lippu on
					     vertailukelpoinen molemmilla pinnoilla. -->
					<dt>
						{result.totals.optimal_proven === false
							? 'vs the strongest free squad the model found'
							: "vs the model's best free squad"}
					</dt>
					<dd class:cost={result.totals.delta_xp < -0.005}>
						{result.totals.delta_xp >= -0.005 ? 'no cost' : result.totals.delta_xp.toFixed(2)}
					</dd>
				</div>
				<div>
					<dt>Squad cost</dt>
					<dd>{result.meta.squad_cost.toFixed(1)}m · {result.meta.bank.toFixed(1)}m in the bank</dd>
				</div>
			</dl>

			{#if draftIds.length === 15}
				<!-- Kohta 3: sama 15 ID:n storage kuin RateTeam-draftilla -->
				<div class="save-row">
					<button type="button" class="secondary" onclick={saveAsDraft} disabled={draftSaved}>
						{draftSaved ? 'Saved as draft' : 'Save as draft'}
					</button>
					{#if draftSaved}
						<span class="muted">
							{#if onOpenRateTeam}
								<button type="button" class="linklike" onclick={onOpenRateTeam}
									>Open Rate my team</button
								> and this squad loads as your draft automatically.
							{:else}
								Open Rate my team and this squad loads as your draft automatically.
							{/if}
						</span>
					{/if}
				</div>
			{/if}
		{/if}
	{/if}
</section>

<style>
	.locks {
		display: flex;
		flex-wrap: wrap;
		gap: var(--s-2);
		margin-bottom: var(--s-3);
	}
	.lock-chip {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		background: rgba(255, 138, 92, 0.1);
		border: 1px solid rgba(255, 138, 92, 0.35);
		border-radius: var(--radius);
		padding: 4px 12px;
		font-weight: 700;
		cursor: pointer;
	}
	.primary {
		margin-top: var(--s-3);
	}
	.verdict {
		background: rgba(255, 138, 92, 0.1);
		border-radius: var(--radius);
		padding: var(--s-3);
		font-weight: 600;
		margin-top: var(--s-4);
	}
	.lock-tag {
		margin-left: 6px;
		font-size: 0.7em;
		font-weight: 800;
		color: var(--accent);
	}
	.bench-line {
		margin-top: var(--s-2);
	}
	.totals {
		margin-top: var(--s-3);
		display: grid;
		gap: var(--s-2);
	}
	.totals div {
		display: flex;
		justify-content: space-between;
		gap: var(--s-4);
	}
	.totals dt {
		color: var(--text-muted);
	}
	.totals dd {
		margin: 0;
		font-weight: 700;
	}
	.totals dd.cost {
		color: var(--giq-coral, #ff6a3d);
	}
	/* Kohta 3: Save as draft -rivi */
	.save-row {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--s-3);
		margin-top: var(--s-4);
	}
	.linklike {
		background: none;
		border: none;
		padding: 0;
		min-height: 0;
		color: var(--giq-rust);
		font-weight: 700;
		font-size: inherit;
		cursor: pointer;
	}
	.linklike:hover {
		text-decoration: underline;
	}
</style>
