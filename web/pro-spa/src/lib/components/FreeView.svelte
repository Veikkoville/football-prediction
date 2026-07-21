<script lang="ts">
	import { fetchFantasy, type FantasyResponse } from '$lib/api';
	import MethodNote from './MethodNote.svelte';
	import Provenance from './Provenance.svelte';
	import RateTeam from './RateTeam.svelte';
	import PriceWatch from './PriceWatch.svelte';
	import Leaders from './Leaders.svelte';
	import Value from './Value.svelte';
	import SegmentNav, { type Segment } from './SegmentNav.svelte';

	// #46: lukitun siirtosuositus-teaserin klikki nostaa tämän → +page vaihtaa
	// Pro-tabiin, jossa Paywall elää (ei premium-sisältöä free-puolella).
	let { onUpgrade }: { onUpgrade?: () => void } = $props();

	// #48: yksi työkalu kerrallaan segmenttinavilla (dashboard-rakenne).
	// Rate my team + Price watch toimivat myös ilman fixture-dataa, joten
	// navi elää datahaarojen ULKOPUOLELLA.
	const SEGMENTS: Segment[] = [
		{ id: 'cleansheets', label: 'Clean sheets' },
		{ id: 'rateteam', label: 'Rate my team' },
		{ id: 'value', label: 'Value' },
		{ id: 'leaders', label: 'Leaders' },
		{ id: 'pricewatch', label: 'Price watch' }
	];
	let segment = $state('cleansheets');

	let data = $state<FantasyResponse | null>(null);
	let error = $state<string | null>(null);

	$effect(() => {
		fetchFantasy().then(
			(d) => (data = d),
			(e) => (error = String(e))
		);
	});

	// #148: jatkuva CS%-väriskaala soluihin (#144-mobiilipariteetti) — FDR-
	// bucket-tint ei säilytä edes järjestystä cs_pct:ssä. Ankkurit = FDR-
	// chippien brändivärit (magenta-deep → coral → gold-deep → gold → teal)
	// samoissa cs_pct-pisteissä kuin mobiilin CS_STOPS. Tint pitää solun
	// luettavana vaalealla pohjalla (vahvin = matalin CS% = magenta).
	const CS_COLOR_STOPS: [number, string][] = [
		[8, '#D6006E'],
		[20, '#FF6A3D'],
		[32, '#F4A800'],
		[44, '#FFC93C'],
		[58, '#19E3D2']
	];
	function csCellBg(csPct: number): string {
		const stops = CS_COLOR_STOPS;
		let hex = stops[0][1];
		if (csPct >= stops[stops.length - 1][0]) {
			hex = stops[stops.length - 1][1];
		} else if (csPct > stops[0][0]) {
			for (let i = 0; i < stops.length - 1; i++) {
				if (csPct <= stops[i + 1][0]) {
					const t = (csPct - stops[i][0]) / (stops[i + 1][0] - stops[i][0]);
					const a = stops[i][1];
					const b = stops[i + 1][1];
					const mix = [1, 3, 5].map((j) =>
						Math.round(
							parseInt(a.slice(j, j + 2), 16) +
								(parseInt(b.slice(j, j + 2), 16) - parseInt(a.slice(j, j + 2), 16)) * t
						)
					);
					hex = `#${mix.map((v) => v.toString(16).padStart(2, '0')).join('')}`;
					break;
				}
			}
		}
		// vahvempi tint vaikeimmille (matala CS%) — #96-oppi käännettynä
		const tint = csPct <= 20 ? 26 : 16;
		return `color-mix(in srgb, ${hex} ${tint}%, transparent)`;
	}

	let gwCols = $derived(
		data?.teams?.[0]?.fixtures?.map((f) => f.gw) ?? []
	);
</script>

<!-- min-height varaa taulukkoalueen tilan ennen API-vastausta → sisältö ei
     hyppää (Lighthouse CLS -fix, QUEUE #15: 0.136-0.784 → tavoite <0.1) -->
<div class="free-view">
<!-- #50: mallin alkuperä-rivi työkalualueen yläreunassa (kiila: sama malli
     kuin julkaistun, pre-match-logatun track recordin takana) -->
<Provenance />
<SegmentNav segments={SEGMENTS} bind:active={segment} label="Free FPL tools" />

{#if segment === 'cleansheets'}
	<div id="panel-cleansheets" role="tabpanel" aria-labelledby="seg-cleansheets">
		{#if error}
			<p class="banner error">Could not load projections right now. Please try again shortly.</p>
		{:else if !data}
			<div class="skeleton" aria-hidden="true">
				<p class="muted">Loading fixtures…</p>
				{#each Array(12) as _, i (i)}
					<div class="skel-row" style="width: {92 - (i % 4) * 6}%"></div>
				{/each}
			</div>
		{:else if !data.meta?.available}
			<p class="banner success">Projections go live before Gameweek 1. Check back soon.</p>
		{:else}
			<section class="tool-card">
				<h2>Clean sheet outlook, next {data.meta.horizon_gw ?? 6} gameweeks</h2>
				<p class="muted">
					Free · <strong>Avg CS%</strong> = the team's average chance of a clean sheet from the
					match model over the next {data.meta.horizon_gw ?? 6} gameweeks.
					<strong>Avg FDR</strong> = average fixture difficulty from the GoalIQ model (win% +
					xG), not FPL's official FDR; 1 = easiest, 5 = hardest. Each GW cell shows opponent,
					venue and that fixture's clean sheet probability; the cell colour follows the same
					probability on a continuous scale (model FDR in the cell tooltip).
				</p>

				<MethodNote summary="How these numbers are calculated">
					<p>
						<strong>Clean sheet probability</strong> is the GoalIQ match model's chance that the
						team concedes zero in that fixture. It comes from a Dixon-Coles score matrix
						(tau-corrected) fitted on match data, the same engine behind our published,
						pre-match logged track record.
					</p>
					<p>
						<strong>Fixture difficulty (FDR 1–5)</strong> is derived from the same model, not
						from FPL's official ratings: each fixture's expected outcome is scaled onto a 1–5
						band, so a "2" here means the model itself rates the matchup favourable.
					</p>
					<p>
						Projections refresh daily, including availability and injury flags. Model
						projections for fun and planning, not betting advice.
					</p>
				</MethodNote>

				<div class="table-wrap">
					<table>
						<thead>
							<tr>
								<th>Team</th>
								<th class="num"><abbr title="Chance of a clean sheet from the match model, averaged over the next gameweeks">Avg CS%</abbr></th>
								<th class="num"><abbr title="Fixture difficulty from the GoalIQ model (win% + xG), not FPL's official FDR; 1 easiest to 5 hardest">Avg FDR</abbr></th>
								{#each gwCols as gw (gw)}
									<th>GW{gw}</th>
								{/each}
							</tr>
						</thead>
						<tbody>
							{#each data.teams as t (t.name)}
								<tr>
									<td>{t.name}</td>
									<td class="num">{t.next_avg_cs_pct.toFixed(1)}</td>
									<td class="num">{t.next_avg_fdr.toFixed(2)}</td>
									{#each gwCols as gw (gw)}
										{@const f = t.fixtures.find((x) => x.gw === gw)}
										{#if f}
											<!-- #148: per-fixture CS% solussa + jatkuva väri; FDR tooltippiin.
											     Defensiivinen: cs_pct puuttuu vanhasta payloadista → FDR-tint
											     + FDR-luku kuten ennen. -->
											{#if typeof f.cs_pct === 'number'}
												<!-- #152: solu linkittää predict-pinnalle (mobiilin solu-tap-
												     pariteetti). SPA:ssa ei ole match-predict-näkymää eikä
												     build-aikaista tietoa ottelusivujen olemassaolosta →
												     kohde on aina elävä /predictions-hub goaliq.appissa. -->
												<td
													class="cs-link-cell"
													style="background: {csCellBg(f.cs_pct)}"
													title="{f.opponent ?? f.opponent_short} ({f.venue}) · FDR {f.fdr} · view model prediction"
												>
													<a
														class="cs-cell-a"
														href="https://goaliq.app/predictions"
														target="_blank"
														rel="noopener"
													>
														{f.opponent_short} ({f.venue}) {Math.round(f.cs_pct)}%
													</a>
												</td>
											{:else}
												<td
													style="background: color-mix(in srgb, var(--fdr-{Math.min(Math.max(f.fdr, 1), 5)}) {f.fdr >= 5 ? 26 : 14}%, transparent)"
												>
													{f.opponent_short} ({f.venue}) {f.fdr}
												</td>
											{/if}
										{:else}
											<td class="muted">Blank</td>
										{/if}
									{/each}
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			</section>
		{/if}
	</div>
{:else if segment === 'rateteam'}
	<!-- #46: rate-my-team ilman siirtosuosituksia (lukittu teaser → Paywall).
	     Toimii myös ilman fixture-dataa. -->
	<div class="tool-card" id="panel-rateteam" role="tabpanel" aria-labelledby="seg-rateteam">
		<RateTeam {onUpgrade} />
	</div>
{:else if segment === 'value'}
	<!-- #127: top-3 free -teaser, koko lista + GK-parit premiumissa -->
	<div class="tool-card" id="panel-value" role="tabpanel" aria-labelledby="seg-value">
		<Value premium={false} {onUpgrade} />
	</div>
{:else if segment === 'leaders'}
	<!-- #124/#125: top-3 free -teaser, koko listat premiumissa -->
	<div class="tool-card" id="panel-leaders" role="tabpanel" aria-labelledby="seg-leaders">
		<Leaders premium={false} {onUpgrade} />
	</div>
{:else}
	<div class="tool-card" id="panel-pricewatch" role="tabpanel" aria-labelledby="seg-pricewatch">
		<PriceWatch />
	</div>
{/if}
</div>

<style>
	.free-view {
		min-height: 82vh;
	}
	.skel-row {
		height: 34px;
		border-radius: var(--radius-sm);
		background: var(--surface);
		border: 1px solid var(--border);
		margin: var(--s-2) 0;
	}
	/* #152: CS-solun linkki perii solun värin, ei alleviivausta —
	   koko solu klikattavaksi ilman visuaalista muutosta. */
	.cs-link-cell {
		padding: 0;
	}
	.cs-cell-a {
		display: block;
		padding: 0.5em 0.75em; /* = theme.css td-padding, solu ei muutu */
		color: inherit;
		text-decoration: none;
	}
	.cs-cell-a:hover {
		filter: brightness(0.94);
	}
</style>
