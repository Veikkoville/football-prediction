<script lang="ts">
	import type { XpResponse } from '$lib/api';
	import {
		fetchComparePlayers,
		type CompareResponse,
		type ComparePlayer
	} from '$lib/fantasyTools';
	import { capture } from '$lib/analytics';
	import { teamColorByShort } from '$lib/teamColors';
	import { canShareToApps, shareCompareCard } from '$lib/shareCard';

	// Valinnat populoituvat jo ladatusta xP-datasta (sama prop kuin XpTable) -
	// ei erillistä pelaajahakua eikä käsin syötettäviä ID:itä.
	let { xp }: { xp: XpResponse } = $props();

	// Labelit = ComponentSplit-pariteetti
	const LABELS: Record<string, string> = {
		appearance: 'Appearance',
		goals: 'Goals',
		assists: 'Assists',
		clean_sheet: 'Clean sheet',
		conceded: 'Conceded',
		saves: 'Saves',
		defensive_contribution: 'Def. contribution',
		yellows: 'Cards',
		bonus: 'Bonus'
	};
	const CONF_LABEL = { low: 'low', med: 'medium', high: 'high' } as const;

	// 28.7: 2 -> 4 pelaajaa. Kaksi ensimmaista pakollisia, kolmas ja neljas
	// valinnaisia. Neljä on realistinen kun mietit kahta siirtoa samalla
	// kertaa, ja se on myös se lupaus jolla kilpailijat myyvät vertailua.
	let ids = $state<(number | null)[]>([null, null, null, null]);
	let loading = $state(false);
	let error = $state<string | null>(null);
	let data = $state<CompareResponse | null>(null);

	let options = $derived(
		[...xp.players].sort(
			(a, b) => a.web_name.localeCompare(b.web_name) || a.team_short.localeCompare(b.team_short)
		)
	);
	/* 6.8 (Villen palaute): select → hakukenttä. 500+ pelaajan alasvetovalikko
	 * on kivulias; datalist antaa selaimen oman haun ilman riippuvuuksia.
	 * Label → id -kartta; törmäys (sama nimi+klubi+pos) on käytännössä
	 * mahdoton, ja jos tulee, viimeinen voittaa (ei kaadu). */
	const optionLabel = (p: (typeof options)[number]) =>
		`${p.web_name} (${p.team_short}, ${p.pos})`;
	let byLabel = $derived(new Map(options.map((p) => [optionLabel(p), p.id])));
	let texts = $state<string[]>(['', '', '', '']);
	function onPickInput(i: number, value: string) {
		texts[i] = value;
		ids[i] = byLabel.get(value) ?? null;
	}
	/** Valitut, jarjestys sailyttaen ja tyhjat pois. */
	let picked = $derived(ids.filter((v): v is number => v != null));
	let hasDupes = $derived(new Set(picked).size !== picked.length);
	let ready = $derived(picked.length >= 2 && !hasDupes);

	async function compare(e: SubmitEvent) {
		e.preventDefault();
		if (!ready || loading) return;
		loading = true;
		error = null;
		try {
			data = await fetchComparePlayers(picked);
		} catch (err) {
			data = null;
			error = err instanceof Error ? err.message : String(err);
		}
		loading = false;
	}

	function components(p: ComparePlayer) {
		return Object.entries(p.components ?? {})
			.filter(([, v]) => typeof v === 'number' && Math.abs(v) >= 0.005)
			.sort(([, a], [, b]) => b - a);
	}

	/* 6.8 (Rowanin palaute): vertailun jakokortti — rivin paras xP/start-%
	 * amberilla, hinta/omistus neutraaleina, mallin verdikti mukana. Sama
	 * kortti shipattiin mobiiliin samana päivänä. */
	let sharing = $state(false);
	async function shareImage() {
		if (sharing || !data) return;
		sharing = true;
		try {
			const rows = data.players;
			const best = (vals: (number | null | undefined)[]): number | null => {
				const max = Math.max(...vals.map((v) => (v == null ? -Infinity : v)));
				if (!Number.isFinite(max)) return null;
				return vals.findIndex((v) => v === max);
			};
			const method = await shareCompareCard({
				title: 'PLAYER COMPARISON',
				subtitle: `next ${data.meta.horizon_gw ?? 6} gameweeks, GoalIQ match model`,
				fileName: 'goaliq_player_comparison.png',
				players: rows.map((p) => {
					const tc = teamColorByShort(p.team_short);
					return {
						name: p.web_name,
						team: p.team_short,
						color: tc.color,
						textColor: tc.textColor,
						pos: p.pos
					};
				}),
				stats: [
					{
						label: 'xP / GW',
						values: rows.map((p) => p.xp_per_gw.toFixed(2)),
						bestIndex: best(rows.map((p) => p.xp_per_gw))
					},
					{
						label: `xP ${data.meta.horizon_gw ?? 6} GWS`,
						values: rows.map((p) => p.xp_horizon_total.toFixed(1)),
						bestIndex: best(rows.map((p) => p.xp_horizon_total))
					},
					{
						label: 'PRICE',
						values: rows.map((p) => p.price.toFixed(1)),
						bestIndex: null
					},
					/* 6.8 (Ville): VALUE tekee hinnasta kannanoton — xP koko
					 * horisontilta per miljoona. Tälle amber kuuluu. */
					{
						label: 'xP / £m',
						values: rows.map((p) =>
							p.price > 0 ? (p.xp_horizon_total / p.price).toFixed(2) : '-'
						),
						bestIndex: best(
							rows.map((p) => (p.price > 0 ? p.xp_horizon_total / p.price : null))
						)
					},
					{
						label: 'OWNED',
						values: rows.map((p) => (p.owned_pct != null ? `${p.owned_pct.toFixed(1)}%` : '-')),
						bestIndex: null
					},
					{
						label: 'START %',
						values: rows.map((p) =>
							p.predicted_starts != null ? `${Math.round(p.predicted_starts)}%` : '-'
						),
						bestIndex: best(rows.map((p) => p.predicted_starts))
					},
					/* 6.8 V1 (Villen idea): pelipaikkakohtaiset rivit kun KAIKKI samaa
					 * paikkaa. Luvut = xP-komponentit YHDELLE GW:lle (components_gw) —
					 * EI per-GW-keskiarvo, siksi GW-numero labelissa (komponenttisumma
					 * täsmää gameweeks[0].xp:hen, ei xp_per_gw:hen). Sama mobiilissa. */
					...(new Set(rows.map((p) => p.pos)).size === 1 &&
					rows.every((p) => p.components != null && p.components_gw != null)
						? (
								({
									GKP: [
										['saves', 'SAVES xP'],
										['clean_sheet', 'CS xP']
									],
									DEF: [
										['clean_sheet', 'CS xP'],
										['defensive_contribution', 'DEFCON xP']
									],
									/* 6.8b (Ville): DefCon myös MID/FWD:lle — 12 CBIRT-kynnys
									 * sisältää recoveryt ja leaders-listan kärkikin on MID. */
									MID: [
										['goals', 'GOALS xP'],
										['assists', 'ASSISTS xP'],
										['defensive_contribution', 'DEFCON xP'],
										['bonus', 'BONUS xP']
									],
									FWD: [
										['goals', 'GOALS xP'],
										['assists', 'ASSISTS xP'],
										['defensive_contribution', 'DEFCON xP'],
										['bonus', 'BONUS xP']
									]
								}[rows[0].pos] ?? []) as [string, string][]
							).map(([key, label]) => {
								const vals = rows.map((p) => p.components?.[key] ?? 0);
								return {
									label: `${label} GW${rows[0].components_gw}`,
									values: vals.map((v) => v.toFixed(2)),
									bestIndex: best(vals)
								};
							})
						: []),
					/* V2: raakastatit backendista kun kaikilla on ne — DEFCON HIT näkyy
					 * AINA kun jokaisella on hit rate (myös MID/FWD: 12 CBIRT sisältää
					 * recoveryt; leaders-lista rankkaa samat positiot yhdessä). */
					...(rows.every((p) => p.defcon_hit_rate_pct != null)
						? [
								{
									label: 'DEFCON HIT',
									values: rows.map((p) => `${Math.round(p.defcon_hit_rate_pct as number)}%`),
									bestIndex: best(rows.map((p) => p.defcon_hit_rate_pct))
								}
							]
						: []),
					...(rows.every((p) => p.pos === 'MID' || p.pos === 'FWD') &&
					rows.every((p) => p.xg90_prev != null)
						? [
								{
									label: `xG/90 ${rows[0].prev_season ?? 'prev'}`,
									values: rows.map((p) => (p.xg90_prev as number).toFixed(2)),
									bestIndex: best(rows.map((p) => p.xg90_prev))
								},
								{
									label: `xA/90 ${rows[0].prev_season ?? 'prev'}`,
									values: rows.map((p) => (p.xa90_prev as number).toFixed(2)),
									bestIndex: best(rows.map((p) => p.xa90_prev))
								}
							]
						: [])
				],
				verdict: data.verdict.text
			});
			if (method !== 'aborted') capture('xp_card_shared', { list: 'compare', method });
		} finally {
			sharing = false;
		}
	}
</script>

<h2>Compare players</h2>
<p class="muted">
	Up to four players side by side on the GoalIQ projections: xP, price, ownership, predicted
	minutes and the per-component split for the next gameweek.
</p>

<form class="cmp-form" onsubmit={compare}>
	<datalist id="cmp-player-options">
		{#each options as p (p.id)}
			<option value={optionLabel(p)}></option>
		{/each}
	</datalist>
	{#each [0, 1, 2, 3] as i (i)}
		<div>
			<label for="cmp-{i}">
				Player {i + 1}{i > 1 ? ' (optional)' : ''}
			</label>
			<input
				id="cmp-{i}"
				list="cmp-player-options"
				type="text"
				autocomplete="off"
				placeholder={i > 1 ? 'Type to search (optional)' : 'Type to search'}
				value={texts[i]}
				oninput={(e) => onPickInput(i, e.currentTarget.value)}
			/>
		</div>
	{/each}
	<button class="primary" type="submit" disabled={!ready || loading}>
		{loading ? 'Comparing…' : 'Compare'}
	</button>
</form>
{#if hasDupes}
	<p class="muted">Each slot needs a different player.</p>
{/if}

{#if error}
	<p class="banner error">{error}</p>
{:else if data}
	<div class="verdict-row">
		<p class="verdict">{data.verdict.text}</p>
		<button type="button" class="share-chip" onclick={shareImage} disabled={sharing}>
			{sharing ? 'Rendering…' : canShareToApps() ? 'Share as image' : 'Download image'}
		</button>
	</div>
	<div class="cmp-grid">
		{#each data.players as p (p.id)}
			<div class="card cmp-card" class:winner={p.id === data.verdict.pick.id}>
				<h3>{p.web_name} <span class="muted">({p.team_short}, {p.pos})</span></h3>
				<dl>
					<div><dt>Total xP, next {data.meta.horizon_gw ?? 6} GWs</dt><dd class="strong">{p.xp_horizon_total.toFixed(2)}</dd></div>
					<div><dt>xP per GW</dt><dd>{p.xp_per_gw.toFixed(2)}</dd></div>
					<div><dt>Price</dt><dd>{p.price.toFixed(1)}</dd></div>
					<div><dt>Owned %</dt><dd>{p.owned_pct != null ? p.owned_pct.toFixed(1) : 'n/a'}</dd></div>
					<div>
						<dt>Predicted starts</dt>
						<dd>
							{#if p.predicted_starts != null}
								{Math.round(p.predicted_starts)}%
								{#if p.minutes_confidence}
									<span
										class="conf conf-{p.minutes_confidence}"
										title="{CONF_LABEL[p.minutes_confidence]} confidence">&#9679;</span
									><span class="muted"> {CONF_LABEL[p.minutes_confidence]} confidence</span>
								{/if}
							{:else}
								n/a
							{/if}
						</dd>
					</div>
					<!-- 6.8 V2: pelipaikkarelevantit raakastatit kun backend lähettää ne -->
					{#if p.defcon_hit_rate_pct != null}
						<div><dt>DefCon hit rate</dt><dd>{Math.round(p.defcon_hit_rate_pct)}%</dd></div>
					{/if}
					{#if p.xg90_prev != null}
						<div><dt>xG per 90 ({p.prev_season ?? 'prev season'})</dt><dd>{p.xg90_prev.toFixed(2)}</dd></div>
						<div><dt>xA per 90</dt><dd>{(p.xa90_prev ?? 0).toFixed(2)}</dd></div>
					{/if}
				</dl>
				{#if p.components}
					<h4 class="muted">GW{p.components_gw ?? ''} xP components</h4>
					<ul class="comps">
						{#each components(p) as [key, value] (key)}
							<li>
								<span>{LABELS[key] ?? key}</span>
								<span class="val" class:neg={value < 0}>
									{value > 0 ? '+' : ''}{value.toFixed(2)}
								</span>
							</li>
						{/each}
					</ul>
				{/if}
			</div>
		{/each}
	</div>
	<p class="muted">GoalIQ model projections, not FPL official; not betting advice.</p>
{/if}

<style>
	.cmp-form {
		display: flex;
		flex-wrap: wrap;
		gap: var(--s-3);
		align-items: end;
		margin-bottom: var(--s-4);
	}
	.verdict-row {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--s-3);
		flex-wrap: wrap;
	}
	.verdict {
		font-size: var(--step-1);
		font-weight: 700;
		color: var(--positive);
		margin-bottom: var(--s-4);
	}
	/* sama chip kuin CaptainRankerissa (komponenttiscope → kopio) */
	.share-chip {
		flex: 0 0 auto;
		border: 1px solid var(--border);
		border-radius: var(--radius);
		background: var(--surface);
		color: var(--text-muted);
		font-weight: 700;
		font-size: var(--step--1);
		padding: 4px 12px;
		cursor: pointer;
		white-space: nowrap;
		line-height: 1.4;
	}
	.share-chip:disabled {
		opacity: 0.6;
		cursor: default;
	}
	.cmp-grid {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
		gap: var(--s-4);
		max-width: 760px;
		margin-bottom: var(--s-3);
	}
	.cmp-card {
		padding: var(--s-4);
	}
	.cmp-card.winner {
		border-color: var(--giq-teal-deep);
	}
	.cmp-card h3 {
		margin-top: 0;
	}
	dl {
		margin: 0 0 var(--s-3);
		display: grid;
		gap: var(--s-1);
	}
	dl > div {
		display: flex;
		justify-content: space-between;
		gap: var(--s-3);
		font-size: var(--step--1);
	}
	dt {
		color: var(--text-muted);
	}
	dd {
		margin: 0;
		font-variant-numeric: tabular-nums;
	}
	dd.strong {
		font-weight: 700;
	}
	h4 {
		margin: 0 0 var(--s-2);
		font-size: var(--step--1);
		font-weight: 700;
	}
	.comps {
		list-style: none;
		margin: 0;
		padding: 0;
		display: grid;
		gap: 2px;
		font-size: var(--step--1);
	}
	.comps li {
		display: flex;
		justify-content: space-between;
	}
	.comps .val {
		color: var(--positive);
		font-weight: 700;
		font-variant-numeric: tabular-nums;
	}
	.comps .val.neg {
		color: var(--negative);
	}
	.conf {
		font-size: 0.65em;
		vertical-align: 1px;
		margin-left: 4px;
	}
	.conf-high {
		color: var(--giq-teal-deep);
	}
	.conf-med {
		color: var(--text-muted);
	}
	.conf-low {
		color: var(--text-muted);
		opacity: 0.45;
	}
</style>
