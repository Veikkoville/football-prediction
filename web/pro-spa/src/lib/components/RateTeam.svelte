<script lang="ts">
	import {
		fetchRateTeam,
		fetchRateTeamManual,
		type RatedPlayer,
		type RateTeamResponse,
		type TransferSuggestion
	} from '$lib/fantasyTools';
	import { fetchXp, type XpPlayer } from '$lib/api';
	import { capture } from '$lib/analytics';
	import { auth } from '$lib/auth.svelte';
	import {
		fplEntry,
		forgetEntry,
		loadProfileEntry,
		persistEntry,
		toggleRemember
	} from '$lib/fplEntry.svelte';
	import HoldVerdictCard from './HoldVerdictCard.svelte';
	import ModelWorking from './ModelWorking.svelte';
	import TeamPitchManager from './TeamPitchManager.svelte';

	// #73: lataustilan askeleet = putken oikeat vaiheet (rehellinen checklist)
	const WORKING_STEPS = [
		'Fetching your FPL squad',
		'Loading model xP projections',
		'Picking your best XI and captain',
		'Checking every transfer against holding'
	];

	// FREE/PREMIUM-raja komponenttitasolla: siirtosuositukset renderöityvät
	// VAIN premium={true} (ProView, tilauksen takana). Free näyttää lukitun
	// teaser-rivin joka vie Paywalliin (onUpgrade → Pro-tab).
	let { premium = false, onUpgrade }: { premium?: boolean; onUpgrade?: () => void } = $props();

	// #66: entry-kenttä on jaettu (fplEntry.entry) RateTeamin + Plannerin kesken
	let loading = $state(false);
	let error = $state<string | null>(null);
	let data = $state<RateTeamResponse | null>(null);

	let entryValid = $derived(/^\d{1,10}$/.test(fplEntry.entry.trim()));

	async function runRate() {
		if (!entryValid || loading) return;
		loading = true;
		error = null;
		try {
			const id = Number(fplEntry.entry.trim());
			data = await fetchRateTeam(id);
			void persistEntry(id); // #66: talteen vasta onnistuneesta hausta
		} catch (err) {
			data = null;
			error = err instanceof Error ? err.message : String(err);
		}
		loading = false;
	}

	function rate(e: SubmitEvent) {
		e.preventDefault();
		void runRate();
	}

	// #66: kirjautuneena lue tallennettu entry-ID profiilista (kerran per user)
	// -> esitäyttö + kertaluontoinen automaattinen rate-ajo (kuten mobiili-#64).
	$effect(() => {
		if (auth.sessionResolved && auth.user) void loadProfileEntry();
	});
	$effect(() => {
		if (fplEntry.autoRunPending && entryValid && !data && !loading) {
			fplEntry.autoRunPending = false;
			void runRate();
		}
	});

	function unlock() {
		// Sama funnel-pari kuin Paywall/billing, source erottaa työkalupolun
		capture('upgrade_tapped', { source: 'fantasy_tools' });
		onUpgrade?.();
	}

	// P1 (23.7): esikausi-draft — FPL julkaisee picksit vasta GW-deadlinen
	// jälkeen, joten ennen GW1:tä entry-polku on tyhjän päällä. Draft: valitse
	// 15 (2 GKP / 5 DEF / 5 MID / 3 FWD) → sama arvio kuin importoidulla
	// joukkueella. Kapteenin valitsee malli (paras GW-xP).
	const DRAFT_CAPS: Record<string, number> = { GKP: 2, DEF: 5, MID: 5, FWD: 3 };
	const DRAFT_ORDER = ['GKP', 'DEF', 'MID', 'FWD'];
	let draftOpen = $state(false);
	let pool = $state<XpPlayer[]>([]);
	let poolError = $state(false);
	let picks = $state<XpPlayer[]>([]);
	let draftQuery = $state('');
	$effect(() => {
		if (draftOpen && pool.length === 0 && !poolError) {
			fetchXp().then(
				(d) => (pool = d.players ?? []),
				() => (poolError = true)
			);
		}
	});
	const posCount = $derived.by(() => {
		const c: Record<string, number> = { GKP: 0, DEF: 0, MID: 0, FWD: 0 };
		for (const p of picks) c[p.pos] = (c[p.pos] ?? 0) + 1;
		return c;
	});
	const draftReady = $derived(picks.length === 15 && !loading);
	// Sama normalisointi kuin FitChecker/XpTable-haussa (#145/#147-pariteetti).
	function normDraft(s: string): string {
		return s
			.normalize('NFD')
			.replace(/[̀-ͯ]/g, '')
			.toLowerCase()
			.replace(/ø/g, 'o')
			.replace(/['’ʼ]/g, '')
			.replace(/[-.]/g, ' ')
			.trim();
	}
	const draftMatches = $derived.by(() => {
		const q = normDraft(draftQuery);
		if (q.length < 2) return [];
		const pickedIds = new Set(picks.map((p) => p.id));
		return pool
			.filter(
				(p) =>
					!pickedIds.has(p.id) &&
					(posCount[p.pos] ?? 0) < (DRAFT_CAPS[p.pos] ?? 0) &&
					(normDraft(p.web_name).includes(q) ||
						(p.full_name ? normDraft(p.full_name).includes(q) : false) ||
						normDraft(p.team_short).includes(q))
			)
			.slice(0, 6);
	});
	function addPick(p: XpPlayer) {
		if (picks.length >= 15 || (posCount[p.pos] ?? 0) >= (DRAFT_CAPS[p.pos] ?? 0)) return;
		picks = [...picks, p];
		draftQuery = '';
	}
	function removePick(id: number) {
		picks = picks.filter((p) => p.id !== id);
	}
	async function submitDraft() {
		if (!draftReady) return;
		loading = true;
		error = null;
		capture('rate_team_draft_submitted', { picked_n: picks.length });
		try {
			data = await fetchRateTeamManual(picks.map((p) => p.id));
		} catch (err) {
			data = null;
			error = err instanceof Error ? err.message : String(err);
		}
		loading = false;
	}

	// #121: apply-to-planner (read-only what-if) — siirtoehdotukset sovelletaan
	// LOKAALISTI planned-tiimiin (pitch + xP + budjetti heti). EI write-backia
	// oikeaan FPL:ään. Uusi rate-ajo nollaa suunnitelman.
	let appliedTransfers = $state<TransferSuggestion[]>([]);
	$effect(() => {
		void data; // riippuvuus: uusi rate-ajo → suunnitelma nollaan
		appliedTransfers = [];
	});
	const plannedPlayers = $derived.by(() => {
		let roster: RatedPlayer[] = data?.team.players ?? [];
		for (const s of appliedTransfers) {
			roster = roster.map((p) =>
				p.id === s.out.id
					? {
							id: s.in.id,
							web_name: s.in.web_name,
							team_short: s.in.team_short,
							pos: p.pos,
							price: s.in.price,
							xp_per_gw: s.in.xp_per_gw ?? 0,
							xp_horizon_total: s.in.xp_horizon_total ?? 0,
							gameweeks: s.in.gameweeks,
							in_xi: p.in_xi,
							is_captain: p.is_captain
						}
					: p
			);
		}
		return roster;
	});
	const plannedIds = $derived(new Set(plannedPlayers.map((p) => p.id)));
	// #35: budjetti on JAETTU siirtojen yli — juokseva bank, ei naiivia summaa.
	const planBank = $derived(
		(data?.team.bank ?? 0) - appliedTransfers.reduce((s, x) => s + x.delta_cost, 0)
	);
	// Sovellettujen siirtojen netto-horisontti-xP on eksakti (jokainen delta on
	// oman out-pelaajansa korvaus, ei saman listan kilpailevia vaihtoehtoja).
	const planNetXp = $derived(
		appliedTransfers.reduce((s, x) => s + x.delta_xp_horizon, 0)
	);
	const appliedKeys = $derived(
		new Set(appliedTransfers.map((s) => `${s.out.id}-${s.in.id}`))
	);
	function canApply(s: TransferSuggestion): boolean {
		return (
			s.in.xp_per_gw != null && // vanha backend ilman planner-kenttiä → ei applya
			plannedIds.has(s.out.id) &&
			!plannedIds.has(s.in.id) &&
			planBank - s.delta_cost >= -1e-9
		);
	}

	$effect(() => {
		// Paywall-pariteetti: teaser näkyvissä = paywall_shown (kerran per lataus)
		if (!premium && data) {
			capture('paywall_shown', { source: 'fantasy_tools' }, 'paywall_shown_fantasy_tools');
		}
	});
</script>

<h2>Rate my FPL team</h2>
<p class="muted">
	Import your squad with your public FPL entry ID, no login or password needed.
</p>

<form class="entry-form" onsubmit={rate}>
	<div>
		<label for="rate-entry">FPL entry ID</label>
		<input
			id="rate-entry"
			inputmode="numeric"
			autocomplete="off"
			placeholder="e.g. 1234567"
			bind:value={fplEntry.entry}
		/>
	</div>
	<button class="primary" type="submit" disabled={!entryValid || loading}>
		{loading ? 'Rating…' : 'Rate my team'}
	</button>
</form>
<p class="muted hint">
	Find the ID on the FPL website: open your Points page and copy the number from the address
	bar (fantasy.premierleague.com/entry/<strong>YOUR-ID</strong>/event/...). FPL publishes
	squads only after each deadline, so before Gameweek 1 use the draft option below.
</p>

<!-- P1: esikausi-draft ilman entry-ID:tä (backendin players=-moodi) -->
<button type="button" class="linklike draft-toggle" onclick={() => (draftOpen = !draftOpen)}>
	No team ID yet? Draft your 15
</button>
{#if draftOpen}
	<div class="draft-box">
		<p class="muted hint">
			Pick a full 15-man squad (2 GK, 5 DEF, 5 MID, 3 FWD) and the model rates it like an
			imported team: best XI, captain pick and projected points.
		</p>
		{#if poolError}
			<p class="banner error">
				Could not load the player pool right now. Please try again shortly.
			</p>
		{:else}
			<div class="draft-chips">
				{#each DRAFT_ORDER as pos (pos)}
					{#each picks.filter((p) => p.pos === pos) as p (p.id)}
						<button type="button" class="draft-chip" onclick={() => removePick(p.id)}>
							{p.web_name}
							<span class="muted">{p.team_short} · {p.pos}</span>
							<span aria-hidden="true">×</span>
						</button>
					{/each}
				{/each}
			</div>
			<p class="muted hint">
				{picks.length} / 15 picked · GK {posCount.GKP}/2 · DEF {posCount.DEF}/5 · MID
				{posCount.MID}/5 · FWD {posCount.FWD}/3
			</p>
			{#if picks.length < 15}
				<label for="draft-search">Add a player</label>
				<input
					id="draft-search"
					type="search"
					placeholder="Player or team (e.g. Haaland, ARS)"
					bind:value={draftQuery}
				/>
				{#each draftMatches as p (p.id)}
					<button type="button" class="picker-row" onclick={() => addPick(p)}>
						<strong>{p.web_name}</strong>
						<span class="muted">{p.team_short} · {p.pos}</span>
					</button>
				{/each}
			{/if}
			<button type="button" class="primary" disabled={!draftReady} onclick={submitDraft}>
				{loading ? 'Rating…' : 'Rate my draft'}
			</button>
		{/if}
	</div>
{/if}

{#if auth.user}
	<!-- #66: tili-taso persistointi vain kirjautuneena (cross-device) -->
	<div class="remember-row">
		<label class="remember-toggle">
			<input type="checkbox" checked={fplEntry.remember} onchange={() => void toggleRemember()} />
			Remember my team
		</label>
		{#if fplEntry.savedEntry != null}
			<button type="button" class="linklike" onclick={() => void forgetEntry()}>
				Forget saved team
			</button>
		{/if}
	</div>
	{#if fplEntry.savedEntry != null}
		<p class="muted hint">
			Saved to your GoalIQ account. Your team loads automatically on any device where you sign
			in.
		</p>
	{/if}
{/if}

{#if loading}
	<!-- #73: malli tekee töitä -progressiivinen paljastus -->
	<ModelWorking steps={WORKING_STEPS} />
{/if}

{#if error}
	<p class="banner error">{error}</p>
{:else if data}
	<!-- #50: hero-luku = Team xP horisontilla (FPL-natiivi mittari); rating
	     sen alla = "% of the best possible budget team" (uusi semantiikka,
	     gap_to_optimal_xp defensiivisesti jos backend jo tarjoaa sen) -->
	<div class="rating card">
		<div class="hero-top">
			<p class="hero-xp" aria-hidden="true">
				<span class="hero-num">{Math.round(data.rating.team_xp_horizon)}</span><span
					class="hero-unit">xP</span
				>
			</p>
			<div class="hero-copy">
				<p class="headline">
					<abbr
						title="Expected points: our match model's projection per player per gameweek, summed over your squad"
						>Team xP</abbr
					>,
					<abbr title="The horizon: how many upcoming gameweeks the projection covers"
						>next {data.meta.horizon_gw ?? 6} GWs</abbr
					>: <strong>{data.rating.team_xp_horizon.toFixed(1)}</strong>
				</p>
				<p class="subline">
					That is <strong>{Math.min(100, Math.round(data.rating.percentile))}%</strong> of the
					best possible budget team{#if typeof data.rating.gap_to_optimal_xp === 'number'}
						({data.rating.gap_to_optimal_xp > 0.05
							? `-${data.rating.gap_to_optimal_xp.toFixed(1)} xP vs the best possible team`
							: 'level with the best possible team'}){/if}.
				</p>
			</div>
		</div>
		<div class="facts">
			<div class="fact">
				<span class="muted">Team xP, GW{data.meta.gw}</span>
				<span class="val">{data.rating.team_xp_gw.toFixed(1)}</span>
			</div>
			<div class="fact">
				<span class="muted">Strongest line</span>
				<span class="val line-strong">{data.rating.strongest_line}</span>
			</div>
			<div class="fact">
				<span class="muted">Weakest line</span>
				<span class="val line-weak">{data.rating.weakest_line}</span>
			</div>
		</div>
		<p class="captain">
			Captain suggestion: <strong>{data.captain.pick.web_name}</strong>
			<span class="muted">({data.captain.pick.team_short})</span>,
			{data.captain.pick.gw_xp.toFixed(2)} xP in GW{data.meta.gw}{#if data.captain.alternative}.
				Alternative: {data.captain.alternative.web_name}
				<span class="muted">({data.captain.alternative.team_short})</span>,
				{data.captain.alternative.gw_xp.toFixed(2)} xP{/if}.
		</p>
		{#if data.team.missing_ids.length > 0}
			<p class="muted">
				{data.team.missing_ids.length}
				{data.team.missing_ids.length === 1 ? 'player has' : 'players have'} no projection yet
				and {data.team.missing_ids.length === 1 ? 'is' : 'are'} excluded from the rating.
			</p>
		{/if}
		{#if typeof data.meta.note === 'string'}
			<p class="muted">{data.meta.note}</p>
		{/if}
	</div>

	<!-- #113: pitch + kitit + what-if-manager (pariteetti mobiilin #106+#112:lle;
	     free = staattinen pitch + lukko, premium = editointi). #121: manageri
	     saa PLANNED-rosterin (sovelletut siirrot mukana); #123: default-GW. -->
	<TeamPitchManager players={plannedPlayers} {premium} defaultGw={data.meta.gw} {onUpgrade} />

	{#if premium}
		<!-- #63: HOLD-verdikti HERO-kantana siirtolistan yläpuolella; backendin
		     hold_verdict on hit-tietoinen. Fallback #50-riviin jos kenttä puuttuu. -->
		{#if data.transfers.hold_verdict}
			<HoldVerdictCard verdict={data.transfers.hold_verdict} surface="rate_team" />
			{#if data.transfers.hold_verdict.verdict === 'transfer' && data.transfers.suggestions.length > 0}
				{@const top = data.transfers.suggestions[0]}
				<p class="verdict-line">
					Weak spot: <strong>{data.rating.weakest_line}</strong>. Top upgrade:
					<strong>{top.out.web_name}</strong> to <strong>{top.in.web_name}</strong>,
					<span class="gain-text">+{top.delta_xp_horizon.toFixed(1)} xP</span>.
				</p>
			{/if}
		{:else if data.transfers.hold}
			<p class="verdict-line hold">
				Verdict: <abbr
					title="Keeping (rolling) your free transfer this week instead of spending it"
					>hold</abbr
				> your transfer, rolling it looks like the better play this week.
			</p>
		{:else if data.transfers.suggestions.length > 0}
			{@const top = data.transfers.suggestions[0]}
			<p class="verdict-line">
				Weak spot: <strong>{data.rating.weakest_line}</strong>. Top upgrade:
				<strong>{top.out.web_name}</strong> to <strong>{top.in.web_name}</strong>,
				<span class="gain-text">+{top.delta_xp_horizon.toFixed(1)} xP</span>.
			</p>
		{/if}
		<h3>Transfer suggestions</h3>
		{#if data.transfers.suggestions.length > 0}
			<div class="table-wrap">
				<table>
					<thead>
						<tr>
							<th>Out</th>
							<th>In</th>
							<th>Pos</th>
							<th class="num"><abbr title="Price change from the swap, millions">Δ cost</abbr></th>
							<th class="num"
								><abbr title="Projected xP gain over the remaining horizon">Δ xP</abbr></th
							>
							<th></th>
						</tr>
					</thead>
					<tbody>
						{#each data.transfers.suggestions as s (s.out.id + '-' + s.in.id)}
							{@const key = `${s.out.id}-${s.in.id}`}
							{@const isApplied = appliedKeys.has(key)}
							<tr>
								<td
									>{s.out.web_name}
									<span class="muted">({s.out.team_short}, {s.out.price.toFixed(1)})</span></td
								>
								<td
									>{s.in.web_name}
									<span class="muted">({s.in.team_short}, {s.in.price.toFixed(1)})</span></td
								>
								<td>{s.pos}</td>
								<td class="num">{s.delta_cost > 0 ? '+' : ''}{s.delta_cost.toFixed(1)}</td>
								<td class="num gain">+{s.delta_xp_horizon.toFixed(2)}</td>
								<td class="num">
									<!-- #121: Apply → planned-pitch päivittyy heti (lokaali) -->
									{#if s.in.xp_per_gw != null}
										<button
											type="button"
											class="apply-btn"
											class:applied={isApplied}
											disabled={isApplied || !canApply(s)}
											onclick={() => (appliedTransfers = [...appliedTransfers, s])}
										>
											{isApplied ? 'Applied' : 'Apply'}
										</button>
									{/if}
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		{/if}
		{#if appliedTransfers.length > 0}
			<!-- #121: suunnitelman yhteenveto — juokseva bank (jaettu budjetti,
			     #35) + eksakti netto-xP + undo/reset. Read-only what-if. -->
			<div class="plan-box">
				<p class="plan-title">
					Your transfer plan ({appliedTransfers.length})
					<span class="muted">
						· Bank after transfers: {planBank.toFixed(1)}m · Net xP over horizon:
						{planNetXp > 0 ? '+' : ''}{planNetXp.toFixed(1)}
					</span>
				</p>
				<div class="plan-actions">
					<button
						type="button"
						class="plan-btn"
						onclick={() => (appliedTransfers = appliedTransfers.slice(0, -1))}
					>
						Undo last
					</button>
					<button type="button" class="plan-btn" onclick={() => (appliedTransfers = [])}>
						Reset plan
					</button>
				</div>
				<p class="muted plan-note">
					A planning sandbox: nothing is sent to FPL. Apply your final team in the official FPL
					app.
				</p>
			</div>
		{/if}
		{#if data.transfers.note}
			<p class="muted">{data.transfers.note}</p>
		{/if}
	{:else}
		<button type="button" class="teaser-row" onclick={unlock}>
			<span>
				Transfer suggestions <span class="muted">(out → in, with projected xP gain)</span>
			</span>
			<span class="locked" aria-label="Locked">•.••</span>
			<span class="cta">Unlock with Premium</span>
		</button>
	{/if}
{/if}

<style>
	.entry-form {
		display: flex;
		flex-wrap: wrap;
		gap: var(--s-3);
		align-items: end;
		margin-bottom: var(--s-4);
	}
	.hint {
		margin: 0 0 var(--s-4);
		font-size: var(--step--1);
	}
	/* #66: Remember my team -rivi (vain kirjautuneena) */
	.remember-row {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		justify-content: space-between;
		gap: var(--s-3);
		max-width: 640px;
		margin: 0 0 var(--s-4);
	}
	.remember-toggle {
		display: inline-flex;
		align-items: center;
		gap: var(--s-2);
		font-size: var(--step--1);
		font-weight: 600;
		cursor: pointer;
	}
	.remember-toggle input {
		accent-color: var(--giq-magenta);
	}
	/* #121: apply-to-planner */
	.apply-btn {
		border: 1px solid var(--giq-magenta);
		border-radius: 999px;
		background: var(--surface);
		color: var(--giq-magenta);
		font-weight: 700;
		font-size: var(--step--1);
		padding: 4px 12px;
		cursor: pointer;
	}
	.apply-btn:disabled {
		opacity: 0.4;
		cursor: default;
	}
	.apply-btn.applied {
		background: rgba(255, 46, 126, 0.1);
		border-color: rgba(255, 46, 126, 0.35);
		opacity: 1;
	}
	.plan-box {
		background: var(--giq-paper, #f6f4ff);
		border: 1px solid var(--border);
		border-radius: var(--radius);
		padding: var(--s-3);
		margin: var(--s-3) 0;
		max-width: 680px;
	}
	.plan-title {
		margin: 0;
		font-weight: 700;
		font-size: var(--step--1);
	}
	.plan-actions {
		display: flex;
		gap: var(--s-2);
		margin-top: var(--s-2);
	}
	.plan-btn {
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: 8px;
		color: var(--text);
		font-weight: 600;
		font-size: var(--step--1);
		padding: 6px 12px;
		cursor: pointer;
	}
	.plan-note {
		margin: var(--s-2) 0 0;
		font-size: var(--step--1);
	}
	.linklike {
		background: none;
		border: none;
		padding: 0;
		color: var(--giq-magenta-deep);
		font-weight: 700;
		font-size: var(--step--1);
		cursor: pointer;
	}
	/* P1: esikausi-draft */
	.draft-toggle {
		display: block;
		margin: 0 0 var(--s-3);
	}
	.draft-box {
		max-width: 640px;
		border: 1px solid var(--border);
		border-radius: var(--radius);
		padding: var(--s-3) var(--s-4);
		margin-bottom: var(--s-4);
	}
	.draft-chips {
		display: flex;
		flex-wrap: wrap;
		gap: var(--s-2);
		margin-bottom: var(--s-2);
	}
	.draft-chip {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		background: rgba(255, 46, 126, 0.1);
		border: 1px solid rgba(255, 46, 126, 0.35);
		border-radius: 999px;
		padding: 4px 12px;
		font-weight: 700;
		cursor: pointer;
	}
	.picker-row {
		display: flex;
		gap: 8px;
		align-items: baseline;
		width: 100%;
		text-align: left;
		background: var(--surface-2);
		border: none;
		border-radius: 6px;
		padding: 8px 10px;
		margin-top: 4px;
		cursor: pointer;
	}
	.linklike:hover {
		text-decoration: underline;
	}
	.rating {
		max-width: 680px;
		margin-bottom: var(--s-4);
		border-color: rgba(255, 46, 126, 0.35);
		background:
			linear-gradient(160deg, rgba(255, 46, 126, 0.09), transparent 55%),
			var(--surface);
	}
	.hero-top {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--s-2) var(--s-4);
		margin-bottom: var(--s-4);
	}
	.hero-xp {
		margin: 0;
		line-height: 1;
		white-space: nowrap;
		color: var(--giq-magenta-deep);
		font-weight: 700;
	}
	.hero-num {
		font-size: clamp(2.8rem, 2.2rem + 3vw, 4.2rem);
		letter-spacing: -2px;
		font-variant-numeric: tabular-nums;
	}
	.hero-unit {
		font-size: var(--step-2);
		margin-left: 2px;
	}
	.hero-copy {
		flex: 1 1 220px;
	}
	.headline {
		font-size: var(--step-1);
		margin: 0 0 var(--s-1);
	}
	.subline {
		margin: 0;
		color: var(--text-muted);
		font-size: var(--step--1);
	}
	.line-strong {
		color: var(--positive);
	}
	.line-weak {
		color: var(--negative);
	}
	/* #50: verdict + action -rivi taulukon yllä; hold-variantti kulta-aksentilla */
	.verdict-line {
		max-width: 640px;
		border: 1px solid var(--border);
		border-left: 4px solid var(--giq-magenta-deep);
		background: var(--surface);
		border-radius: var(--radius);
		padding: var(--s-3) var(--s-4);
		margin: var(--s-4) 0 0;
	}
	.verdict-line.hold {
		border-left-color: var(--giq-gold-deep);
		color: var(--warn-text);
		font-weight: 700;
	}
	.gain-text {
		color: var(--positive);
		font-weight: 700;
	}
	.facts {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
		gap: var(--s-3);
		margin-bottom: var(--s-4);
	}
	.fact {
		display: grid;
		gap: 2px;
	}
	.fact .val {
		font-weight: 700;
		font-variant-numeric: tabular-nums;
	}
	.captain {
		margin-bottom: var(--s-2);
	}
	td.gain {
		color: var(--positive);
		font-weight: 700;
	}
	/* Lukittu teaser: sama •.••-kieli kuin Paywall-teaser */
	.teaser-row {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--s-3);
		width: 100%;
		max-width: 640px;
		text-align: left;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: var(--radius);
		padding: var(--s-3) var(--s-4);
		color: var(--text);
		font-weight: 500;
		font-size: var(--step--1);
	}
	.teaser-row:hover {
		border-color: var(--giq-magenta);
	}
	.locked {
		color: var(--giq-magenta-deep);
		font-weight: 700;
		letter-spacing: 2px;
		margin-left: auto;
	}
	.cta {
		color: var(--positive);
		font-weight: 700;
	}
</style>
