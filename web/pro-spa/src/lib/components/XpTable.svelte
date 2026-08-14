<script lang="ts">
	import type { XpResponse, XpPlayer } from '$lib/api';
	import { gwXp } from '$lib/api';
	import { downloadXpCsv } from '$lib/fantasyTools';
	import { capture } from '$lib/analytics';
	import { canShareToApps, shareCard } from '$lib/shareCard';
	import ComponentSplit from './ComponentSplit.svelte';
	import MethodNote from './MethodNote.svelte';
	import SetPieceBadges from './SetPieceBadges.svelte';

	let { data }: { data: XpResponse } = $props();

	const POSITIONS = ['All', 'GKP', 'DEF', 'MID', 'FWD'] as const;
	// Sorttaus (#22): numeeriset laskevaan, tekstit nousevaan järjestykseen.
	const POS_ORDER: Record<string, number> = { GKP: 0, DEF: 1, MID: 2, FWD: 3 };
	const SORTS = {
		total: {
			label: 'Total xP (high to low)',
			cmp: (a: XpPlayer, b: XpPlayer) => b.xp_horizon_total - a.xp_horizon_total
		},
		perGw: {
			label: 'xP per GW (high to low)',
			cmp: (a: XpPlayer, b: XpPlayer) => b.xp_per_gw - a.xp_per_gw
		},
		xmins: {
			label: 'Expected minutes (high to low)',
			cmp: (a: XpPlayer, b: XpPlayer) => b.xmins - a.xmins
		},
		pos: {
			label: 'Position (GKP to FWD)',
			cmp: (a: XpPlayer, b: XpPlayer) =>
				(POS_ORDER[a.pos] ?? 9) - (POS_ORDER[b.pos] ?? 9) ||
				b.xp_horizon_total - a.xp_horizon_total
		},
		team: {
			label: 'Team (A to Z)',
			cmp: (a: XpPlayer, b: XpPlayer) =>
				a.team.localeCompare(b.team) || b.xp_horizon_total - a.xp_horizon_total
		},
		name: {
			label: 'Name (A to Z)',
			cmp: (a: XpPlayer, b: XpPlayer) => a.web_name.localeCompare(b.web_name)
		},
		starts: {
			label: 'Start % (high to low)',
			cmp: (a: XpPlayer, b: XpPlayer) =>
				(b.predicted_starts ?? -1) - (a.predicted_starts ?? -1) ||
				b.xp_horizon_total - a.xp_horizon_total
		},
		owned: {
			label: 'Ownership % (high to low)',
			cmp: (a: XpPlayer, b: XpPlayer) =>
				(b.owned_pct ?? -1) - (a.owned_pct ?? -1) || b.xp_horizon_total - a.xp_horizon_total
		},
		// Hinta nousevaan: budjettikulma ("halvin ensin"), toisin kuin muut
		// numeeriset sortit. Sama valinta kuin mobiilin Leadersissa.
		price: {
			label: 'Price (low to high)',
			cmp: (a: XpPlayer, b: XpPlayer) =>
				(a.price ?? Infinity) - (b.price ?? Infinity) ||
				b.xp_horizon_total - a.xp_horizon_total
		},
		value: {
			label: 'Value (xP per million, high to low)',
			cmp: (a: XpPlayer, b: XpPlayer) => xpPerMillion(b) - xpPerMillion(a)
		}
	} as const;

	// xP per miljoona. Ilman hintaa arvo on -1, jolloin rivi valuu listan
	// hantaan sen sijaan etta jakolasku tuottaisi Infinityn ja nostaisi sen karkeen.
	function xpPerMillion(p: XpPlayer): number {
		return p.price && p.price > 0 ? p.xp_horizon_total / p.price : -1;
	}

	// #33f: confidence-selite (mobiilipariteetti: sama merkitys, sama copy-henki).
	const CONF_LABEL = { low: 'low', med: 'medium', high: 'high' } as const;

	let pos = $state<(typeof POSITIONS)[number]>('All');
	let sortBy = $state<keyof typeof SORTS>('total');
	// Hintakatto, ei kaistoja: kayttajan kysymys on "parhaat 5,5 miljoonan
	// keskarit", ja kaista 4.6-6.0 vastaisi siihen vaarin. Katto = "talla
	// budjetilla tai halvemmalla", joka on se mita joukkuetta rakentaessa kysytaan.
	let maxPrice = $state<number | null>(null);
	let groupByTeam = $state(false);
	/* WHY-THIS-PICK (14.8): ajurinimikkeet. Sama sanasto kuin
	   scripts/build_fpl_why.py:n DRIVERS-listassa ja mobiilin
	   fantasy.xp.why_driver.* -avaimissa. Tuntematon arvo renderoityy
	   raakana eika katoa: uusi ajuri backendissa ei saa hukata tietoa. */
	const WHY_DRIVER_LABEL: Record<string, string> = {
		minutes: 'Minutes',
		attacking_output: 'Attacking output',
		fixtures: 'Fixtures',
		clean_sheets: 'Clean sheets',
		set_pieces: 'Set pieces',
		bonus: 'Bonus',
		price: 'Price',
		differential: 'Differential'
	};

	let selectedId = $state<number | null>(null);

	let nextGw = $derived(data.meta.next_gameweek);
	let gwCols = $derived(data.players[0]?.gameweeks?.map((g) => g.gw) ?? []);
	let horizonN = $derived(data.meta.horizon_gw ?? gwCols.length ?? 6);
	let horizonLabel = $derived(
		gwCols.length > 0 ? `GW${gwCols[0]}–GW${gwCols[gwCols.length - 1]}` : `next ${horizonN} GWs`
	);
	// Kokonais-xP-rank pysyy samana sorttauksesta/ryhmittelystä riippumatta →
	// # on aina "overall xP rank", ei rivin juokseva numero (selkeys #22).
	let rankById = $derived(
		new Map(
			[...data.players]
				.sort((a, b) => b.xp_horizon_total - a.xp_horizon_total)
				.map((p, i) => [p.id, i + 1])
		)
	);
	// #145/#147: client-side pelaajahaku. Normalisointi (SAMA logiikka
	// mobiilissa, pariteetti): lowercase + strip diacritics (NFD) + poista
	// heittomerkit + väliviivat/pisteet välilyönneiksi → "sesko" löytää Šeškon,
	// "ngolo" N'Golon. Matchataan web_name + full_name ("van dijk" → Virgil) +
	// joukkueen KOKO nimi ("arsenal") + team_short ("ARS").
	function normSearch(s: string): string {
		return s
			.normalize('NFD')
			.replace(/[̀-ͯ]/g, '')
			.toLowerCase()
			// NFD ei hajota näitä → eksplisiittinen kartta (Ødegaard!)
			.replace(/ø/g, 'o')
			.replace(/æ/g, 'ae')
			.replace(/đ/g, 'd')
			.replace(/ł/g, 'l')
			.replace(/['’ʼ]/g, '')
			.replace(/[-.]/g, ' ')
			.replace(/\s+/g, ' ')
			.trim();
	}
	let search = $state('');
	let pool = $derived.by(() => {
		const q = normSearch(search);
		return data.players
			.filter((p) => pos === 'All' || p.pos === pos)
			.filter((p) => maxPrice == null || (typeof p.price === 'number' && p.price <= maxPrice))
			.filter(
				(p) =>
					!q ||
					normSearch(p.web_name).includes(q) ||
					(p.full_name ? normSearch(p.full_name).includes(q) : false) ||
					normSearch(p.team).includes(q) ||
					normSearch(p.team_short).includes(q)
			)
			.toSorted(SORTS[sortBy].cmp);
	});
	// 26.7 PERF: koko 373 pelaajan lista renderöityi kerralla (~4 500 DOM-solmua
	// pelkkään tähän tauluun) ja lajittelu/suodatus siirteli ne kaikki. Sama
	// korjaus kuin Leaders.sveltessä ja /fpl/xg-leaders-sivulla: näytetään 100
	// riviä, suodatus ja lajittelu koskevat silti KOKO aineistoa. Haku ei osu
	// tähän rajaan käytännössä (osumia harvoin >100).
	const RENDER_LIMIT = 100;
	let showAll = $state(false);
	let shown = $derived(showAll ? pool : pool.slice(0, RENDER_LIMIT));
	let hiddenCount = $derived(pool.length - shown.length);

	// Joukkueittain-ryhmittely: seurat aakkosin, pelaajat valitussa sortissa.
	let groups = $derived.by(() => {
		if (!groupByTeam) return [{ team: null as string | null, players: shown }];
		const byTeam = new Map<string, XpPlayer[]>();
		for (const p of shown) {
			const list = byTeam.get(p.team) ?? [];
			list.push(p);
			byTeam.set(p.team, list);
		}
		return [...byTeam.entries()]
			.sort(([a], [b]) => a.localeCompare(b))
			.map(([team, players]) => ({ team: team as string | null, players }));
	});
	// Komponenttierittely (#13-pariteetti): vain pelaajat joilla backend
	// tarjoaa components-kentän; defensiivinen jos kenttä puuttuu kokonaan.
	let compPool = $derived(pool.filter((p) => p.components));
	let selected = $derived(
		compPool.find((p) => p.id === selectedId) ?? compPool[0] ?? null
	);
	let compGw = $derived(compPool[0]?.components_gw ?? nextGw);
	// #33f: Start %-sarake vain jos backend tuo kentän (defensiivinen).
	let hasStarts = $derived(data.players.some((p) => typeof p.predicted_starts === 'number'));
	// Edge-sprint: Own%-sarake vain jos backend tuo kentän (defensiivinen).
	let hasOwned = $derived(data.players.some((p) => typeof p.owned_pct === 'number'));
	// Hinta-sarake ja hintasortit vain jos backend tuo kentän (defensiivinen,
	// sama kaava kuin hasStarts/hasOwned). SPL-syöte kantaa priceä myös.
	let hasPrice = $derived(data.players.some((p) => typeof p.price === 'number'));
	// Hintaportaat aineistosta, ei kovakoodattuna: FPL:n 0,1 M granulariteetti
	// muuttuu kauden aikana, ja kovakoodattu tikapuu vanhenisi hiljaa.
	let priceLadder = $derived(
		[...new Set(data.players.map((p) => p.price).filter((v): v is number => typeof v === 'number'))]
			.sort((a, b) => a - b)
	);
	// Edge-sprint: badge-selite vain jos joku pelaaja saa badgen (order<=2).
	let hasSetPieces = $derived(
		data.players.some(
			(p) =>
				p.set_pieces &&
				[p.set_pieces.pens, p.set_pieces.corners, p.set_pieces.fk].some(
					(o) => typeof o === 'number' && o <= 2
				)
		)
	);

	// Edge-sprint: minuuttijakauma title-tooltippiin (kompakti; contract-data 1:
	// p_start + p_cameo + p_bench = 1). Puuttuvat kentät → vanha tooltip.
	function minutesTitle(p: XpPlayer): string {
		if (
			typeof p.p_start !== 'number' ||
			typeof p.p_cameo !== 'number' ||
			typeof p.p_bench !== 'number'
		) {
			return `${CONF_LABEL[p.minutes_confidence ?? 'low']} confidence`;
		}
		return (
			`Minutes model: start ${Math.round(p.p_start * 100)}%, ` +
			`sub appearance ${Math.round(p.p_cameo * 100)}%, ` +
			`unused ${Math.round(p.p_bench * 100)}% ` +
			`(${CONF_LABEL[p.minutes_confidence ?? 'low']} confidence)`
		);
	}

	// 8.8 (Villen pyyntö): jakokortti myös tähän listaan, samaan paikkaan
	// mistä CSV:n saa. Jakaa NÄKYVÄN näkymän top 10 — aktiiviset suodattimet
	// (pos/hintakatto/sortti/haku) alaotsikossa, muuten kortti väittäisi
	// olevansa koko listan kärki (sama linjaus kuin Value.sveltessä 4.8).
	let sharing = $state(false);
	async function share() {
		if (sharing) return;
		sharing = true;
		try {
			// Vain ensimmäinen kirjain pieneksi — .toLowerCase() rikkoisi
			// xP-kirjoitusasun ("by total xp").
			const sortLabel = SORTS[sortBy].label.replace(/\s*\(.*\)$/, '');
			const sub = [
				horizonLabel,
				`by ${sortLabel.charAt(0).toLowerCase()}${sortLabel.slice(1)}`,
				...(pos !== 'All' ? [pos] : []),
				...(maxPrice != null ? [`max £${maxPrice.toFixed(1)}m`] : []),
				...(search.trim() ? [`"${search.trim()}"`] : [])
			].join(', ');
			const method = await shareCard({
				title: 'EXPECTED POINTS',
				subtitle: `${sub}, GoalIQ model`,
				...(hasPrice ? { midLabel: 'PRICE' } : {}),
				valueLabel: sortBy === 'value' ? 'xP/£m' : 'xP',
				fileName: 'goaliq_xp_list.png',
				rows: pool.slice(0, 10).map((p, i) => ({
					rank: i + 1,
					name: p.web_name,
					tag: p.pos,
					team: p.team_short,
					...(hasPrice && typeof p.price === 'number' ? { mid: p.price.toFixed(1) } : {}),
					value:
						sortBy === 'value'
							? xpPerMillion(p).toFixed(2)
							: p.xp_horizon_total.toFixed(1)
				}))
			});
			if (method !== 'aborted') capture('xp_card_shared', { list: 'xp', method });
		} finally {
			sharing = false;
		}
	}

	// Edge-sprint kohta 5: CSV-lataus (premium-pinta; Bearer-header kulkee
	// downloadXpCsv-helperissä). Virhe inline-banneriin, ei heitetä.
	let csvBusy = $state(false);
	let csvError = $state<string | null>(null);
	async function onCsv(eu = false) {
		if (csvBusy) return;
		csvBusy = true;
		csvError = await downloadXpCsv(eu);
		csvBusy = false;
	}
</script>

<h2>Player expected points, {horizonLabel}</h2>
<p class="muted">
	<strong>Total xP</strong> = the sum of projected points across {horizonLabel}
	({horizonN} gameweeks). <strong>xP/GW</strong> = the per-gameweek average over the same
	horizon. <strong>xP/90</strong> is the rate over a full 90 minutes, shown next to
	<strong>xMins</strong> so the minutes assumption is visible instead of multiplied into one number. Click a row to see how a player's xP is built.{#if hasSetPieces}
		The <strong>P</strong>, <strong>C</strong> and <strong>FK</strong> badges mark players
		first or second in line for penalties, corners and direct free kicks (FPL squad data,
		updated through pre-season).{/if}
</p>

<MethodNote summary="How xP is built">
	<p>
		<strong>xP = expected minutes &times; the sum of scoring components</strong>: appearance
		points, goals, assists, clean sheets, saves, defensive contribution and bonus, minus
		cards. The per-GW columns show the same projection fixture by fixture.
	</p>
	<p>
		Team-level inputs (clean sheet probability, expected goals for and against) come from
		the GoalIQ Dixon-Coles match engine, the same model behind our published, pre-match
		logged track record. Player baselines come from each player's per-gameweek history,
		weighted by expected minutes. Defensive contribution is modelled explicitly, which is
		where the projections most often disagree with the eye test.
	</p>
	<p>
		<strong>Expected minutes are probabilistic, not a guessed lineup.</strong> A minutes
		model estimates each player's start probability (the Start % column) from recent
		starts, availability and squad depth, and combines it with expected minutes when
		starting. The confidence mark next to Start % reflects sample size and rotation
		stability: <span class="conf conf-high">&#9679;</span> high,
		<span class="conf conf-med">&#9679;</span> medium,
		<span class="conf conf-low">&#9679;</span> low.
	</p>
	<!-- 10.8: mitattu harha julki. Neljä korjausyritystä hävisi (viimeisin
	     ristiinvalidoitu kalibrointi, kaikki variantit huonompia), joten lukua
	     EI säädetä. Kuvaileva kerronta on sama vaste kuin siirtosokeudessa.
	     Luvut: scripts/calibrate_preseason_minutes.py, 3 kesätaukoa. -->
	<p>
		<strong>Our pre-season minutes run high at the top.</strong> We tested our own prior
		across the last three summers. Players we projected at 80+ minutes came in about 14
		minutes lower than we said, and players we projected at the bottom came in a little
		higher. The order of this list is unchanged by that, and the gap closes as 2026/27
		results arrive.
	</p>
	<p>
		Honesty notes: these are GoalIQ model projections, not FPL's official expected points.
		Pre-season projections lean on last season's baselines until the new season's data
		arrives. Model projections for fun and planning, not betting advice.
	</p>
</MethodNote>

<div class="controls">
	<div>
		<label for="pos">Position</label>
		<select id="pos" bind:value={pos}>
			{#each POSITIONS as p (p)}
				<option value={p}>{p}</option>
			{/each}
		</select>
	</div>
	{#if hasPrice}
		<div>
			<label for="maxprice">Max price</label>
			<select id="maxprice" bind:value={maxPrice}>
				<option value={null}>Any</option>
				{#each priceLadder as v (v)}
					<option value={v}>&pound;{v.toFixed(1)}m or less</option>
				{/each}
			</select>
		</div>
	{/if}
	<div>
		<label for="sort">Sort by</label>
		<select id="sort" bind:value={sortBy}>
			{#each Object.entries(SORTS).filter(([k]) => (k !== 'starts' || hasStarts) && (!['price', 'value'].includes(k) || hasPrice)) as [key, s] (key)}
				<option value={key}>{s.label}</option>
			{/each}
		</select>
	</div>
	<label class="toggle">
		<input type="checkbox" bind:checked={groupByTeam} />
		Group by team
	</label>
	<div class="search-box">
		<label for="player-search">Search</label>
		<input
			id="player-search"
			type="search"
			placeholder="Player or team (e.g. ARS)"
			bind:value={search}
		/>
		{#if search}
			<button type="button" class="search-clear" onclick={() => (search = '')}
				aria-label="Clear search">&times;</button
			>
		{/if}
	</div>
	<!-- Edge-sprint kohta 5: koko projektio CSV:nä (premium-pinta) -->
	<button type="button" class="ghost csv-btn" disabled={csvBusy} onclick={() => void onCsv(false)}>
		{csvBusy ? 'Preparing CSV…' : 'Download CSV'}
	</button>
	<!-- 8.8: jakokortti näkyvästä näkymästä, CSV:n vierestä -->
	<button type="button" class="ghost" disabled={sharing} onclick={share}>
		{sharing ? 'Rendering…' : canShareToApps() ? 'Share as image' : 'Download image'}
	</button>
</div>
<!-- fi/eu-Excel lukee pisteellisen desimaalin paivamaaraksi ja nayttaa '####'.
     Tama variantti kayttaa ';'-erotinta ja pilkkudesimaaleja. -->
<p class="csv-eu">
	Numbers showing as #### in Excel?
	<button type="button" class="linklike" disabled={csvBusy} onclick={() => void onCsv(true)}>
		Download the European format
	</button>
	(semicolons, comma decimals).
</p>
{#if csvError}
	<p class="banner error">{csvError}</p>
{/if}

{#if pool.length === 0}
	<p class="muted">No players match.</p>
{/if}

<div class="table-wrap tall">
	<table>
		<thead>
			<tr>
				<th class="num"><abbr title="Overall rank by total xP">#</abbr></th>
				<th>Player</th>
				<th>Team</th>
				<th class="m-hide">Pos</th>
				{#if hasPrice}
					<th class="num m-hide"><abbr title="Current FPL price in millions">Price</abbr></th>
				{/if}
				<th class="num m-hide"><abbr title="Expected minutes per gameweek">xMins</abbr></th>
				{#if hasStarts}
					<th class="num m-hide"
						><abbr title="Start probability from the GoalIQ minutes model; the mark shows confidence. Hover a value for the full minutes split (start / sub / unused)"
							>Start %</abbr
						></th
					>
				{/if}
				{#if hasOwned}
					<th class="num m-hide"
						><abbr title="Ownership: share of FPL managers who own the player (FPL data)"
							>Own %</abbr
						></th
					>
				{/if}
				<th class="num"><abbr title="Average expected points per gameweek">xP/GW</abbr></th>
				<th class="num m-hide"
					><abbr title="Expected points if the player completes a full 90 minutes. This is the rate, so read it next to xMins, which is what he is actually expected to play."
						>xP/90</abbr
					></th
				>
				<th class="num"><abbr title="Sum of expected points, {horizonLabel}">Total xP</abbr></th>
				{#each gwCols as gw (gw)}
					<th class="num m-hide">GW{gw}</th>
				{/each}
			</tr>
		</thead>
		<tbody>
			{#each groups as g (g.team ?? '_all')}
				{#if g.team}
					<tr class="group-row">
						<td colspan={7 + (hasPrice ? 1 : 0) + (hasStarts ? 1 : 0) + (hasOwned ? 1 : 0) + gwCols.length}
							>{g.team}</td
						>
					</tr>
				{/if}
				{#each g.players as p (p.id)}
					<tr
						class:selected={selected?.id === p.id}
						onclick={() => (selectedId = p.id)}
					>
						<td class="num muted">{rankById.get(p.id)}</td>
						<td
							>{p.web_name}{#if p.data_basis === 'limited_history' || p.data_basis === 'no_history'}
								<!-- #143-WEB/#146: datapohja-rehellisyysmerkintä (pariteetti
								     mobiiliin: sama tagi + sama selite tooltipissa;
								     pl_history = ei labelia, puuttuva kenttä = ei mitään) -->
								<span
									class="basis-tag"
									title={p.data_basis === 'no_history'
										? 'No Premier League data for this player yet, this is a position-based estimate.'
										: 'The model has little Premier League history for this player yet, so treat this projection as less certain.'}
									>{p.data_basis === 'no_history' ? 'No PL data yet' : 'Limited data'}</span
								>{/if}<SetPieceBadges sp={p.set_pieces} /></td
						>
						<td
							>{p.team_short}{#if p.team_flag}
								<!-- 10.8: JOUKKUEEN luottamuslippu (vrt. basis-tag yllä, joka on
								     PELAAJAN datapohja). Pyydettiin r/FantasyPL:ssä nimenomaan
								     projektioihin. Kuvaileva: kertoo että luokitus nojaa
								     heikompaan tietoon, EI kumpaan suuntaan luku liikkuu —
								     suunnan kalibrointi kaatui 9.8. Vain liputetut saavat
								     kentän, joten tagi ei ilmesty 20 joukkueelle. -->
								<span
									class="basis-tag"
									title={p.team_flag === 'promoted'
										? "Promoted side. No Premier League results to fit a team rating on, so this team starts from a baseline rather than its own record."
										: "Unusually high squad turnover. Team ratings are fitted on results, so this one still reads as last season's squad."}
									>{p.team_flag === 'promoted' ? 'Promoted' : 'High turnover'}</span
								>{/if}</td
						>
						<td class="m-hide">{p.pos}</td>
						{#if hasPrice}
							<td class="num m-hide">
								{#if typeof p.price === 'number'}{p.price.toFixed(1)}{/if}
							</td>
						{/if}
						<td class="num m-hide">{p.xmins.toFixed(1)}</td>
						{#if hasStarts}
							<td class="num m-hide" title={minutesTitle(p)}>
								{#if typeof p.predicted_starts === 'number'}
									<span class="conf conf-{p.minutes_confidence ?? 'low'}">&#9679;</span
									>{Math.round(p.predicted_starts)}
								{/if}
							</td>
						{/if}
						{#if hasOwned}
							<td class="num m-hide">
								{#if typeof p.owned_pct === 'number'}{p.owned_pct.toFixed(1)}{/if}
							</td>
						{/if}
						<td class="num">{p.xp_per_gw.toFixed(2)}</td>
						<td class="num m-hide">
							{#if p.xp_per_90 == null}
								<span class="muted" title="Too few expected minutes for a rate to mean anything"
									>-</span
								>
							{:else}
								{p.xp_per_90.toFixed(2)}
							{/if}
						</td>
						<td class="num total-col">{p.xp_horizon_total.toFixed(2)}</td>
						{#each gwCols as gw (gw)}
							<td class="num m-hide">{gwXp(p, gw).toFixed(2)}</td>
						{/each}
					</tr>
				{/each}
			{/each}
		</tbody>
	</table>
</div>

{#if hiddenCount > 0}
	<button type="button" class="show-all" onclick={() => (showAll = true)}>
		Show all {pool.length} players
	</button>
{/if}

{#if compPool.length > 0}
	<h3>How the GW{compGw} xP is built</h3>
	<p class="muted">
		GoalIQ model expected points, split by scoring component. Defensive contribution is
		where the model finds edges the eye test misses. Click a row above or pick a player.
	</p>
	<label for="comp-player">Player</label>
	<select
		id="comp-player"
		class="comp-select"
		value={selected?.id}
		onchange={(e) => (selectedId = Number(e.currentTarget.value))}
	>
		{#each compPool as p (p.id)}
			<option value={p.id}>{p.web_name} ({p.team_short}, {p.pos})</option>
		{/each}
	</select>
	{#if selected}
		<!-- WHY-THIS-PICK (14.8): selitys ENNEN komponenttisplittia, koska se on
		     vastaus siihen kysymykseen jonka takia rivi avattiin. Premium-only ja
		     vain FPL: backend liittaa `why`:n vain maskaamattomaan vastaukseen,
		     joten tama on tyhja free-kayttajalla ilman erillista gatea taalla.

		     LAHDE NAKYY AINA. `template` ei ole vika vaan tarkka mutta tylsa
		     lause; sen piilottaminen tekisi provenienssilupauksesta valikoivan.
		     Kumpaakaan lahdetta EI kutsuta "malliksi": tassa tuotteessa se sana
		     tarkoittaa ottelumallia, ja lauseen kirjoittajan kutsuminen malliksi
		     siirtaisi ottelumallin uskottavuuden sille. Sama saanto mobiilissa. -->
		{#if selected.why?.sentence}
			<div class="why">
				<p class="why-title">Why this projection</p>
				<p class="why-text">{selected.why.sentence}</p>
				{#if selected.why.drivers?.length}
					<div class="why-chips">
						{#each selected.why.drivers as d (d)}
							<span class="why-chip">{WHY_DRIVER_LABEL[d] ?? d}</span>
						{/each}
					</div>
				{/if}
				<p class="why-source">
					{selected.why.source === 'model'
						? "Written by an AI from the model's own numbers"
						: "Auto-generated from the model's own numbers"}
				</p>
			</div>
		{/if}
		<ComponentSplit player={selected} />
		{#if typeof selected.predicted_starts === 'number'}
			<p class="muted minutes-line">
				Minutes outlook for {selected.web_name}: expected minutes
				{Math.round(selected.xmins)} per GW, start probability
				{Math.round(selected.predicted_starts)}%{#if selected.minutes_confidence}{' '}
					(<span class="conf-text conf-{selected.minutes_confidence}"
						>{CONF_LABEL[selected.minutes_confidence]} confidence</span
					>){/if}. Model-based estimate; confidence reflects sample size and rotation
				stability.{#if selected.data_basis === 'limited_history'}{' '}Limited data:
					the model has little Premier League history for this player yet, so treat
					this projection as less certain.{:else if selected.data_basis === 'no_history'}{' '}No
					PL data yet: this is a position-based estimate.{/if}
			</p>
		{/if}
	{/if}
	<p class="muted">Differentials (xP vs ownership) come in Phase 2.</p>
{:else}
	<p class="muted">
		Per-gameweek xP columns = the per-GW breakdown. Differentials (xP vs ownership) come
		in Phase 2.
	</p>
{/if}

<style>
	/* 26.7 PERF: rivirajauksen purku (sama chip-kieli kuin Leadersissa) */
	.show-all {
		margin-top: var(--s-3);
		border: 1px solid var(--border);
		border-radius: var(--radius);
		background: var(--surface);
		color: var(--text-muted);
		font-weight: 700;
		font-size: var(--step--1);
		padding: 4px 12px;
		cursor: pointer;
		white-space: nowrap;
	}
	.show-all:hover {
		color: var(--text);
		border-color: var(--accent);
	}
	.controls {
		display: flex;
		flex-wrap: wrap;
		gap: var(--s-4) var(--s-6);
		align-items: end;
		margin-bottom: var(--s-4);
	}
	.toggle {
		display: flex;
		align-items: center;
		gap: var(--s-2);
		font-size: var(--step--1);
		color: var(--text);
		margin: 0;
		min-height: 44px;
	}
	.toggle input {
		min-height: 0;
		width: 18px;
		height: 18px;
		accent-color: var(--accent);
	}
	.tall {
		max-height: 640px;
		overflow-y: auto;
	}
	tbody tr {
		cursor: pointer;
	}
	tr.selected td {
		/* magenta-tintti toimii myös vaalealla (10 % valkoisen päällä) */
		background: rgba(255, 138, 92, 0.1);
	}
	tr.group-row td {
		background: var(--surface-2);
		color: var(--positive);
		font-weight: 700;
		cursor: default;
	}
	td.total-col {
		font-weight: 700;
		color: var(--text);
	}
	.comp-select {
		margin-bottom: var(--s-3);
	}
	/* #33f: confidence-merkki: high=teal, med=neutraali, low=himmennetty */
	.conf {
		font-size: 0.65em;
		vertical-align: 1px;
		margin-right: 3px;
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
	.conf-text.conf-high {
		color: var(--positive);
	}
	.minutes-line {
		margin-top: var(--s-3);
	}
	/* #143-WEB: datapohja-rehellisyysmerkintä nimen perässä (hillitty).
	   #146: title-tooltip selittää — cursor: help vihjaa siitä. */
	.basis-tag {
		margin-left: 6px;
		font-size: 0.72em;
		color: var(--text-muted);
		opacity: 0.8;
		white-space: nowrap;
		cursor: help;
		text-decoration: underline dotted;
	}
	/* #145: hakukenttä controls-riviin */
	.search-box {
		display: flex;
		align-items: center;
		gap: 6px;
	}
	.search-box input {
		min-width: 180px;
	}
	.search-clear {
		background: none;
		border: none;
		color: var(--text-muted);
		font-size: 16px;
		cursor: pointer;
		padding: 2px 6px;
	}
	.csv-eu {
		/* --muted ei ole olemassa (oikea nimi on --text-muted) -> ilman
		   fallbackia tama rivi putosi ja teksti peri viereisen varin. */
		color: var(--text-muted);
		font-size: var(--step--1);
		margin: var(--s-3) 0 0;
	}
	.linklike {
		background: none;
		border: 0;
		padding: 0;
		color: var(--giq-rust);
		font: inherit;
		font-weight: 700;
		cursor: pointer;
		text-decoration: underline;
	}
	.linklike:disabled {
		opacity: 0.6;
		cursor: default;
	}
	/* Edge-sprint kohta 5: CSV-nappi controls-rivin oikeaan laitaan */
	.csv-btn {
		margin-left: auto;
		font-size: var(--step--1);
	}

	/* WHY-THIS-PICK (14.8) */
	.why {
		background: var(--surface-alt, #1f1d1a);
		border-left: 2px solid var(--teal, #2ed6c2);
		border-radius: 2px;
		padding: 10px 12px;
		margin: 12px 0;
	}
	.why-title {
		margin: 0 0 4px;
		font-size: 11px;
		font-weight: 700;
		letter-spacing: 0.04em;
		text-transform: uppercase;
		color: var(--muted, #a8a29a);
	}
	.why-text {
		margin: 0;
		font-size: 13px;
		line-height: 1.5;
	}
	.why-source {
		margin: 6px 0 0;
		font-size: 11px;
		color: var(--muted, #a8a29a);
	}
	.why-chips {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
		margin-top: 8px;
	}
	.why-chip {
		font-size: 11px;
		font-weight: 600;
		color: var(--teal, #2ed6c2);
		background: var(--surface, #141311);
		border-radius: 2px;
		padding: 3px 7px;
	}
</style>
