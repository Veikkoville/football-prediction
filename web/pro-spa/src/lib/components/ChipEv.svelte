<script lang="ts">
	// Edge-sprint kohta 6: chip-ajoituksen EV (premium). Renderöidään VAIN
	// gatatusta haarasta (ProTools). entry valinnainen: tallennettu/validi
	// entry → käyttäjän runko; ilman → mallin optimirunko (meta.mode=model_xi).
	// Esikaudella entry-picksit puuttuvat (404) → automaattinen fallback
	// mallirunkoon selitteellä. Basis-alaviite: GW7+ = team-level estimate.
	import { fetchChipEv, type ChipEvResponse, type ChipWindow } from '$lib/fantasyTools';
	import { capture } from '$lib/analytics';
	import { fplEntry } from '$lib/fplEntry.svelte';
	import MethodNote from './MethodNote.svelte';
	import ModelWorking from './ModelWorking.svelte';

	const WORKING_STEPS = [
		'Loading model xP projections',
		'Scoring every remaining gameweek per chip',
		'Picking the best window for each chip'
	];

	const CHIPS = [
		{ key: 'wc', label: 'Wildcard', ev: (w: ChipWindow) => w.wc_ev },
		{ key: 'bb', label: 'Bench Boost', ev: (w: ChipWindow) => w.bb_ev },
		{ key: 'tc', label: 'Triple Captain', ev: (w: ChipWindow) => w.tc_ev },
		{ key: 'fh', label: 'Free Hit', ev: (w: ChipWindow) => w.fh_ev }
	] as const;

	let loading = $state(false);
	let error = $state<string | null>(null);
	let data = $state<ChipEvResponse | null>(null);
	/** Selite kun entry annettiin mutta picksit eivät vielä julki (pre-GW1). */
	let entryFallback = $state(false);

	let entryValid = $derived(/^\d{1,10}$/.test(fplEntry.entry.trim()));

	async function load() {
		if (loading) return;
		loading = true;
		error = null;
		entryFallback = false;
		try {
			if (entryValid) {
				try {
					data = await fetchChipEv(Number(fplEntry.entry.trim()));
				} catch {
					// Esikausi: FPL ei ole julkaissut picksejä → mallirunko selitteellä
					data = await fetchChipEv(null);
					entryFallback = true;
				}
			} else {
				data = await fetchChipEv(null);
			}
			capture('chip_ev_viewed', { source: 'pro_spa', mode: data?.meta?.mode ?? 'unknown' });
		} catch (err) {
			data = null;
			error = err instanceof Error ? err.message : String(err);
		}
		loading = false;
	}

	// Autoload kerran kun osio avataan (entry-kenttä ei ole pakollinen).
	let started = $state(false);
	$effect(() => {
		if (!started) {
			started = true;
			void load();
		}
	});

	function top3(chip: (typeof CHIPS)[number]): ChipWindow[] {
		if (!data) return [];
		return [...data.windows].sort((a, b) => chip.ev(b) - chip.ev(a)).slice(0, 3);
	}

	let hasTeamApprox = $derived(
		data?.windows?.some((w) => w.basis !== 'player_xp') ?? false
	);
</script>

<h2>Chip timing: expected value per gameweek</h2>
<p class="muted">
	When to play Wildcard, Bench Boost, Triple Captain and Free Hit: each remaining gameweek
	gets a rough expected-value estimate per chip, and the best window is highlighted.
	{#if data?.meta?.mode === 'model_xi'}Based on the model's optimal squad{#if entryFallback},
			because FPL publishes squads only after the GW1 deadline (your entry will be used once
			picks are live){/if}.{:else if data?.meta?.entry != null}Based on your squad (entry
		{data.meta.entry}).{/if}
</p>

<form
	class="chip-form"
	onsubmit={(e) => {
		e.preventDefault();
		void load();
	}}
>
	<div>
		<label for="chip-entry">FPL entry ID (optional)</label>
		<input
			id="chip-entry"
			inputmode="numeric"
			autocomplete="off"
			placeholder="e.g. 1234567"
			bind:value={fplEntry.entry}
		/>
	</div>
	<button class="primary" type="submit" disabled={loading}>
		{loading ? 'Estimating…' : 'Recalculate'}
	</button>
</form>

{#if loading}
	<ModelWorking steps={WORKING_STEPS} />
{/if}

{#if error}
	<p class="banner error">{error}</p>
{:else if data}
	<div class="chip-grid">
		{#each CHIPS as chip (chip.key)}
			{@const best = data.best?.[chip.key]}
			<div class="chip-card card">
				<div class="chip-head">
					<h3>{chip.label}</h3>
					{#if best && typeof best.gw === 'number'}
						<span class="best-pill">Best: GW{best.gw}</span>
					{/if}
				</div>
				{#if best && typeof best.ev === 'number'}
					<p class="best-ev">
						<span class="ev-num">+{best.ev.toFixed(1)}</span>
						<span class="ev-unit">xP est.</span>
						{#if best.basis && best.basis !== 'player_xp'}
							<span class="basis-mark" title="Team-level estimate beyond the player-projection horizon">*</span>
						{/if}
					</p>
				{/if}
				<table class="chip-top3">
					<tbody>
						{#each top3(chip) as w (w.gw)}
							<tr>
								<td>GW{w.gw}{#if w.basis !== 'player_xp'}<span
											class="basis-mark"
											title="Team-level estimate beyond the player-projection horizon">*</span
										>{/if}</td>
								<td class="num">+{chip.ev(w).toFixed(1)}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		{/each}
	</div>
	{#if hasTeamApprox}
		<p class="muted basis-note">
			* Gameweeks beyond the current player-projection horizon (GW{(data.meta.horizon_gws?.at(
				-1
			) ?? 6) + 1}+) use a team-level estimate from full-season fixture quality, not
			per-player projections. Treat those windows as rougher.
		</p>
	{/if}
	<MethodNote summary="How chip EV is estimated (and its limits)">
		{#if data.meta.notes && data.meta.notes.length > 0}
			{#each data.meta.notes as n (n)}
				<p>{n}</p>
			{/each}
		{:else}
			<p>
				Rough MVP estimates: Triple Captain = best XI score with an extra captain
				multiplier, Bench Boost = bench xP, Free Hit and Wildcard = best budget team vs
				your squad. Within the next six gameweeks the numbers come from player projections;
				beyond that from team-level fixture quality.
			</p>
		{/if}
		<p>GoalIQ model projections, for fun and planning, not betting advice.</p>
	</MethodNote>
{/if}

<style>
	.chip-form {
		display: flex;
		flex-wrap: wrap;
		gap: var(--s-3);
		align-items: end;
		margin-bottom: var(--s-4);
	}
	.chip-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
		gap: var(--s-4);
		margin-bottom: var(--s-3);
	}
	.chip-card {
		padding: var(--s-4);
	}
	.chip-head {
		display: flex;
		justify-content: space-between;
		align-items: baseline;
		gap: var(--s-2);
	}
	.chip-head h3 {
		margin: 0;
		font-size: var(--step-0);
	}
	.best-pill {
		background: rgba(255, 138, 92, 0.1);
		border: 1px solid rgba(255, 138, 92, 0.35);
		color: var(--giq-rust);
		border-radius: var(--radius);
		padding: 1px 10px;
		font-size: var(--step--1);
		font-weight: 700;
		white-space: nowrap;
	}
	.best-ev {
		margin: var(--s-2) 0 var(--s-2);
		color: var(--giq-rust);
		font-weight: 700;
		line-height: 1;
	}
	/* isot luvut = display-fontti (theme.css-sääntö: Space Grotesk vain
	   otsikot/brändi/isot luvut) */
	.ev-num {
		font-family: var(--font-display);
		font-size: var(--step-2);
		font-variant-numeric: tabular-nums;
	}
	.ev-unit {
		font-size: var(--step--1);
		margin-left: 2px;
	}
	.chip-top3 {
		font-size: var(--step--1);
	}
	.chip-top3 td {
		padding: 0.3em 0.5em 0.3em 0;
		border-bottom: none;
	}
	.basis-mark {
		color: var(--warn-text);
		font-weight: 700;
		margin-left: 2px;
		cursor: help;
	}
	.basis-note {
		margin-top: 0;
	}
</style>
