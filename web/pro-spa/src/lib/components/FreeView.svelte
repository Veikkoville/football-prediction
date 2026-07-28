<script lang="ts">
	import { fetchFantasy, type FantasyResponse, type FantasyTeam } from '$lib/api';
	import MethodNote from './MethodNote.svelte';
	import Provenance from './Provenance.svelte';
	import LeagueBanner from './LeagueBanner.svelte';
	import RateTeam from './RateTeam.svelte';
	import FitChecker from './FitChecker.svelte';
	import PlayerCard from './PlayerCard.svelte';
	import PriceWatch from './PriceWatch.svelte';
	import Leaders from './Leaders.svelte';
	import Value from './Value.svelte';
	import MiniLeague from './MiniLeague.svelte';
	import SegmentNav, { type Segment } from './SegmentNav.svelte';

	// #46: lukitun siirtosuositus-teaserin klikki nostaa tämän → +page vaihtaa
	// Pro-tabiin, jossa Paywall elää (ei premium-sisältöä free-puolella).
	let { onUpgrade }: { onUpgrade?: () => void } = $props();

	// #48: yksi työkalu kerrallaan segmenttinavilla (dashboard-rakenne).
	// Rate my team + Price watch toimivat myös ilman fixture-dataa, joten
	// navi elää datahaarojen ULKOPUOLELLA.
	const SEGMENTS: Segment[] = [
		{ id: 'cleansheets', label: 'Clean sheets' },
		{ id: 'playercard', label: 'Player card' },
		{ id: 'rateteam', label: 'Rate my team' },
		{ id: 'fitchecker', label: 'Fit checker' },
		{ id: 'value', label: 'Value' },
		{ id: 'leaders', label: 'Leaders' },
		{ id: 'pricewatch', label: 'Price watch' },
		{ id: 'league', label: 'Mini-league' }
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

	// 26.7 CLASSIC: lämpökarttatäyttö POISTETTU. Aiemmin (#148) solu sai
	// jatkuvan CS%-tintin; uusi ilme kieltää sen eksplisiittisesti — vaikeus
	// kannetaan LUVUN painolla ja värillä, ei solun taustalla, jotta numerot
	// pysyvät sivun äänekkäimpänä asiana.
	//
	// Kynnykset ovat samat kuin vanhan skaalan ankkurit, joten tulkinta ei
	// muutu: helppo (kulta, semibold) / neutraali / vaikea (coral, mykistetty).
	// Väri EI ole ainoa signaali — paino kulkee mukana, joten rivi luetaan myös
	// värisokeana ja mustavalkotulosteessa.
	function csCellClass(csPct: number): string {
		if (csPct >= 44) return 'is-easy';
		if (csPct <= 20) return 'is-hard';
		return '';
	}
	/** FDR 1–5 samalla logiikalla (1 = helpoin). */
	function fdrCellClass(fdr: number): string {
		if (fdr <= 2) return 'is-easy';
		if (fdr >= 4) return 'is-hard';
		return '';
	}

	// ------------------------------------------------------------------
	// 27.7 HORISONTTI: GW-välivalitsin + lajittelu
	// (kontrakti: goaliq-app/cos-reports/horizon-extension-contract-2026-07-27.md)
	//
	// Aggregaatit lasketaan KLIENTISSÄ, ei palvelimella: välin raahaaminen on
	// jatkuva ele, ja per-kutsu tuntuisi rikkinäiseltä. Koko kausi tulee
	// yhdessä vastauksessa.
	// ------------------------------------------------------------------
	let nearHorizon = $derived(data?.meta?.near_horizon_gw ?? 6);
	let allGws = $derived(
		[...new Set((data?.teams ?? []).flatMap((t) => t.fixtures.map((f) => f.gw)))].sort(
			(a, b) => a - b
		)
	);
	let minGw = $derived(allGws[0] ?? 1);
	let maxGw = $derived(allGws[allGws.length - 1] ?? 1);

	let gwFrom = $state(0);
	let gwTo = $state(0);
	let rangeTouched = $state(false);

	// Oletusväli = lähihorisontti eli TÄSMÄLLEEN nykyinen näkymä. Kukaan ei
	// avaa sivua 38 peliviikon seinään; laajennus on työkalu jonka käyttäjä
	// ottaa käyttöön. Ei ylikirjoiteta käyttäjän valintaa datan päivittyessä.
	$effect(() => {
		if (!rangeTouched && allGws.length) {
			gwFrom = minGw;
			gwTo = Math.min(minGw + nearHorizon - 1, maxGw);
		}
	});

	let gwCols = $derived(allGws.filter((g) => g >= gwFrom && g <= gwTo));

	type RangeAgg = {
		n: number;
		avgFdr: number | null;
		avgCs: number | null;
		allNear: boolean;
	};

	/** Yhden joukkueen luvut valitulla välillä.
	 *
	 *  KOLME REUNATAPAUSTA (kontrakti §4), kaikki hoidettu tässä jotta molemmat
	 *  pinnat käyttäytyvät samoin:
	 *   1. BLANK GW — 0 fixturea välillä. avgFdr = null, EI 0: tyhjän keskiarvo
	 *      lajittuisi "helpoimmaksi" ja nostaisi pelaamattoman joukkueen kärkeen.
	 *   2. DOUBLE GW — 2 fixturea samassa GW:ssä. Keskiarvo laimentaa, joten
	 *      n näytetään lukuna eikä pelkkänä keskiarvona.
	 *   3. SEKAVÄLI — väli ylittää near/far-rajan → avgCs = null. Osittainen
	 *      keskiarvo olisi eri asioiden keskiarvo, ei epätarkka luku. */
	function rangeAgg(t: FantasyTeam): RangeAgg {
		const fx = t.fixtures.filter((f) => f.gw >= gwFrom && f.gw <= gwTo);
		if (!fx.length) return { n: 0, avgFdr: null, avgCs: null, allNear: false };
		const allNear = fx.every((f) => (f.tier ?? 'near') === 'near');
		const cs = fx.map((f) => f.cs_pct).filter((v): v is number => typeof v === 'number');
		return {
			n: fx.length,
			avgFdr: fx.reduce((s, f) => s + f.fdr, 0) / fx.length,
			avgCs: allNear && cs.length === fx.length ? cs.reduce((s, v) => s + v, 0) / cs.length : null,
			allNear
		};
	}

	let sortKey = $state<'fdr' | 'cs' | 'n' | 'name'>('fdr');

	let sortedTeams = $derived.by(() => {
		const rows = (data?.teams ?? []).map((t) => ({ t, a: rangeAgg(t) }));
		rows.sort((x, y) => {
			// Blank GW aina viimeisenä riippumatta lajittelusta — sillä ei ole
			// mielekästä vaikeutta eikä sitä saa esittää helpoimpana.
			if (x.a.n === 0 !== (y.a.n === 0)) return x.a.n === 0 ? 1 : -1;
			if (sortKey === 'name') return x.t.name.localeCompare(y.t.name);
			if (sortKey === 'n') return y.a.n - x.a.n;
			if (sortKey === 'cs') {
				if (x.a.avgCs == null && y.a.avgCs == null) return 0;
				if (x.a.avgCs == null) return 1;
				if (y.a.avgCs == null) return -1;
				return y.a.avgCs - x.a.avgCs; // korkein CS% ensin
			}
			return (x.a.avgFdr ?? 99) - (y.a.avgFdr ?? 99); // helpoin ensin
		});
		return rows;
	});

	let rangeHasFar = $derived(gwTo > minGw + nearHorizon - 1);
	// Edge-sprint kohta 4: selite näkyviin vain jos payload tuo D/A-kentät.
	let hasDuoAny = $derived(
		data?.teams?.some((t) =>
			t.fixtures.some(
				(f) => typeof f.def_fdr === 'number' && typeof f.att_fdr === 'number'
			)
		) ?? false
	);
</script>

<!-- min-height varaa taulukkoalueen tilan ennen API-vastausta → sisältö ei
     hyppää (Lighthouse CLS -fix, QUEUE #15: 0.136-0.784 → tavoite <0.1) -->
<div class="free-view">
<!-- #50: mallin alkuperä-rivi työkalualueen yläreunassa (kiila: sama malli
     kuin julkaistun, pre-match-logatun track recordin takana) -->
<Provenance />
<!-- M29: Beat the Model -miniliigan liittymiskortti (julkinen koodi jgi6j9) -->
<LeagueBanner />
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
				<h2>
					Clean sheet outlook, GW{gwFrom}–{gwTo}
				</h2>
				<p class="muted">
					Free · <strong>Avg CS%</strong> = the team's average chance of a clean sheet from the
					match model across the gameweeks you select. It is shown only while the whole range
					sits inside the modelled window. Beyond that the calendar still tells you where the
					swings are, but a precise percentage would not be honest.
					<strong>Avg FDR</strong> = average fixture difficulty from the GoalIQ model (win% +
					xG), not FPL's official FDR; 1 = easiest, 5 = hardest. Each GW cell shows opponent,
					venue and that fixture's clean sheet probability; the cell colour follows the same
					probability on a continuous scale (model FDR in the cell tooltip).{#if hasDuoAny}
						The <strong>D · A</strong> chip splits difficulty by direction:
						<strong>D</strong> = how hard it is to keep a clean sheet,
						<strong>A</strong> = how hard it is to score, both 1 (easiest) to 5 (hardest).{/if}
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

				<!-- 27.7: GW-välivalitsin. Oletus = lähihorisontti (nykyinen näkymä);
				     laajennus on työkalu jonka käyttäjä ottaa käyttöön. -->
				<div class="gw-range">
					<label>
						<span class="muted">From GW</span>
						<select
							bind:value={gwFrom}
							onchange={() => {
								rangeTouched = true;
								if (gwTo < gwFrom) gwTo = gwFrom;
							}}
						>
							{#each allGws as g (g)}<option value={g}>{g}</option>{/each}
						</select>
					</label>
					<label>
						<span class="muted">to GW</span>
						<select
							bind:value={gwTo}
							onchange={() => {
								rangeTouched = true;
								if (gwFrom > gwTo) gwFrom = gwTo;
							}}
						>
							{#each allGws as g (g)}<option value={g}>{g}</option>{/each}
						</select>
					</label>
					<label>
						<span class="muted">Sort by</span>
						<select bind:value={sortKey}>
							<option value="fdr">Easiest fixtures</option>
							<option value="cs">Best clean sheet %</option>
							<option value="n">Most fixtures</option>
							<option value="name">Team name</option>
						</select>
					</label>
					{#if rangeTouched && (gwFrom !== minGw || gwTo !== Math.min(minGw + nearHorizon - 1, maxGw))}
						<button
							type="button"
							class="gw-reset"
							onclick={() => {
								gwFrom = minGw;
								gwTo = Math.min(minGw + nearHorizon - 1, maxGw);
							}}>Reset</button
						>
					{/if}
				</div>

				{#if rangeHasFar}
					<!-- Kaukorivien pakollinen label. Ei piiloteta eikä pehmennetä:
					     malli ei voi luvata GW30:n tarkkuutta heinäkuussa. -->
					<p class="banner">
						{data.meta.far_basis_label ??
							'Fixture difficulty only beyond the next few gameweeks. Clean sheet % appears as each gameweek moves closer.'}
					</p>
				{/if}

				<div class="table-wrap">
					<table>
						<thead>
							<tr>
								<th>Team</th>
								<th class="num"><abbr title="Chance of a clean sheet from the match model, averaged over the selected gameweeks. Blank when the range reaches beyond the modelled window.">Avg CS%</abbr></th>
								<th class="num"><abbr title="Fixture difficulty from the GoalIQ model (win% + xG), not FPL's official FDR; 1 easiest to 5 hardest">Avg FDR</abbr></th>
								<th class="num"><abbr title="Fixtures in the selected range: 0 = blank gameweek, 2+ = double gameweek">Games</abbr></th>
								{#each gwCols as gw (gw)}
									<th class:is-far={gw > minGw + nearHorizon - 1}>GW{gw}</th>
								{/each}
							</tr>
						</thead>
						<tbody>
							{#each sortedTeams as { t, a } (t.name)}
								<tr class:is-blank={a.n === 0}>
									<td>{t.name}</td>
									<!-- avgCs null = sekaväli tai blank. Näytetään viiva, EI 0:
									     eri asioiden keskiarvo olisi väärä luku, ei epätarkka. -->
									<td class="num">{a.avgCs != null ? a.avgCs.toFixed(1) : '—'}</td>
									<td class="num">{a.avgFdr != null ? a.avgFdr.toFixed(2) : '—'}</td>
									<td class="num">{a.n}</td>
									{#each gwCols as gw (gw)}
										{@const f = t.fixtures.find((x) => x.gw === gw)}
										{#if f}
											<!-- #148: per-fixture CS% solussa + jatkuva väri; FDR tooltippiin.
											     Defensiivinen: cs_pct puuttuu vanhasta payloadista → FDR-tint
											     + FDR-luku kuten ennen. -->
											{@const hasDuo =
												typeof f.def_fdr === 'number' && typeof f.att_fdr === 'number'}
											{@const fdrTitle = hasDuo
												? `Defence FDR ${f.def_fdr} (clean sheet angle) · Attack FDR ${f.att_fdr} (scoring angle)`
												: `FDR ${f.fdr}`}
											{#if typeof f.cs_pct === 'number'}
												<!-- #152: solu linkittää predict-pinnalle (mobiilin solu-tap-
												     pariteetti). SPA:ssa ei ole match-predict-näkymää eikä
												     build-aikaista tietoa ottelusivujen olemassaolosta →
												     kohde on aina elävä /predictions-hub goaliq.appissa.
												     Edge-sprint kohta 4: D/A-FDR-chip (def = CS-kulma,
												     att = maalintekokulma); fallback vanhaan fdr:ään. -->
												<td
													class="cs-link-cell {csCellClass(f.cs_pct)}"
													title="{f.opponent ?? f.opponent_short} ({f.venue}) · {fdrTitle} · view model prediction"
												>
													<a
														class="cs-cell-a"
														href="https://goaliq.app/predictions"
														target="_blank"
														rel="noopener"
													>
														{f.opponent_short} ({f.venue}) {Math.round(f.cs_pct)}%{#if hasDuo}
															<span class="fdr-duo">D{f.def_fdr} · A{f.att_fdr}</span>{/if}
													</a>
												</td>
											{:else}
												<td
													class={fdrCellClass(f.fdr)}
													title={hasDuo ? fdrTitle : undefined}
												>
													{f.opponent_short} ({f.venue})
													{#if hasDuo}
														<span class="fdr-duo">D{f.def_fdr} · A{f.att_fdr}</span>
													{:else}{f.fdr}{/if}
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
{:else if segment === 'playercard'}
	<!-- UX-palaute-erä (25.7) kohta 1: player card / hakutietopankki (FREE) -->
	<div class="tool-card" id="panel-playercard" role="tabpanel" aria-labelledby="seg-playercard">
		<PlayerCard />
	</div>
{:else if segment === 'rateteam'}
	<!-- #46: rate-my-team ilman siirtosuosituksia (lukittu teaser → Paywall).
	     Toimii myös ilman fixture-dataa. -->
	<div class="tool-card" id="panel-rateteam" role="tabpanel" aria-labelledby="seg-rateteam">
		<RateTeam {onUpgrade} />
	</div>
{:else if segment === 'fitchecker'}
	<!-- #155: lukitse 1-3 pakkopelaajaa → paras runko + lukituksen xP-hinta.
	     FREE, ei entry-ID:tä (PI-13: toimii go-live-hetkellä). -->
	<div class="tool-card" id="panel-fitchecker" role="tabpanel" aria-labelledby="seg-fitchecker">
		<!-- Kohta 3: Save as draft → segmentti vaihtuu rateteamiin -->
		<FitChecker onOpenRateTeam={() => (segment = 'rateteam')} />
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
{:else if segment === 'pricewatch'}
	<div class="tool-card" id="panel-pricewatch" role="tabpanel" aria-labelledby="seg-pricewatch">
		<PriceWatch />
	</div>
{:else}
	<!-- Edge-sprint kohta 9: mini-league standings + H2H (free MVP).
	     UX-palaute-erä kohta 5: Use this team → rateteam-segmentti. -->
	<div class="tool-card" id="panel-league" role="tabpanel" aria-labelledby="seg-league">
		<MiniLeague onUseTeam={() => (segment = 'rateteam')} />
	</div>
{/if}
</div>

<style>
	/* 27.7 horisontti: välivalitsin + near/far-erottelu */
	.gw-range {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--s-3);
		margin: var(--s-3) 0;
	}
	.gw-range label {
		display: inline-flex;
		align-items: center;
		gap: var(--s-2);
		font-size: var(--step--1);
	}
	.gw-range select {
		font: inherit;
		padding: 0.2em 0.4em;
		border: 1px solid var(--border);
		border-radius: 6px;
		background: var(--surface);
		color: var(--text);
	}
	.gw-reset {
		font: inherit;
		font-size: var(--step--1);
		padding: 0.2em 0.7em;
		border: 1px solid var(--border);
		border-radius: 6px;
		background: transparent;
		color: var(--text-muted);
		cursor: pointer;
	}
	/* Kaukohorisontti kevennettynä: sama data, pienempi lupaus. Erottelu
	   tehdään painolla eikä värillä, koska väri on jo varattu vaikeusasteikolle. */
	th.is-far {
		opacity: 0.62;
		font-weight: 400;
	}
	/* Blank GW: rivi himmennetään ja se lajitellaan viimeiseksi (ks. sortedTeams).
	   Sitä ei saa esittää "helpoimpana" vain koska keskiarvoa ei ole. */
	tbody tr.is-blank {
		opacity: 0.55;
	}
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
		background: rgba(32, 31, 29, 0.04);
	}
	/* 26.7 CLASSIC: lämpökarttatäytön korvaajat. Väri EI ole ainoa signaali —
	   paino kulkee mukana, joten sarake luetaan myös värisokeana. */
	:global(td.is-easy),
	:global(td.is-easy) .cs-cell-a {
		color: var(--accent-strong);
		font-weight: 600;
	}
	:global(td.is-hard),
	:global(td.is-hard) .cs-cell-a {
		color: var(--negative);
	}
	/* Edge-sprint kohta 4: suuntajaettu FDR-chip solun sisällä (hillitty,
	   ei kilpaile CS%-taustavärin kanssa) */
	.fdr-duo {
		display: inline-block;
		margin-left: 6px;
		padding: 0 5px;
		border: 1px solid rgba(10, 8, 32, 0.22);
		border-radius: 4px;
		background: rgba(255, 255, 255, 0.55);
		color: var(--giq-ink);
		font-size: 0.72em;
		font-weight: 700;
		line-height: 1.6;
		white-space: nowrap;
	}
</style>
