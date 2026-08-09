<script lang="ts">
	/**
	 * Leaders (#124/#125) — xG leaders + DefCon tracker (FPLWolfy-ehdotukset).
	 * Sama korttikieli kuin value/differentials. Basis-label AINA näkyvissä
	 * (datarajoitukset ensiluokkaisena: esikausi = 25/26-data, otoskoko per
	 * rivi, ei arvauksia).
	 *
	 * 26.7: xG-lista VAPAUTETTU kokonaan ilmaiseksi. xG/xA/xGI on FPL:n itsensä
	 * julkaisemaa taaksepäin katsovaa dataa, jonka kilpailijat (fpl.page ym.)
	 * antavat ilmaiseksi — maksumuuri hyödykedatan päällä ei puolusta mitään ja
	 * on ristiriidassa "ilmaistaso on aidosti hyödyllinen" -lupauksen kanssa.
	 * DefCon PYSYY premiumissa: hit rate + kynnysanalyysi on oma johdannaisemme,
	 * ei julkista dataa. Maksumuuri kuuluu eteenpäin katsoviin mallin tuotoksiin
	 * (xP, captain ranker, chips, edge), ei menneisyyteen.
	 */
	import { capture } from '$lib/analytics';
	// 26.7: joukkuepaidat riveilla. IP-turva: neutraali siluetti + klubin
	// primary-vari, EI pelaajakuvia eika krestejä. Renderoidaan <symbol>+<use>
	// -parina (ks. PERF-huomio alempana), joten TeamKit-komponenttia ei tarvita.
	import { teamColorByShort } from '$lib/teamColors';
	import { fetchXp } from '$lib/api';
	import { canShareToApps, shareCard } from '$lib/shareCard';
	import {
		fetchDefconGw,
		fetchDefconLeaders,
		fetchXgLeaders,
		type DefconGwResponse,
		type DefconLeadersResponse,
		type XgLeadersResponse
	} from '$lib/fantasyTools';

	let { premium = false, onUpgrade }: { premium?: boolean; onUpgrade?: () => void } = $props();

	const FREE_ROWS = 3;
	const WINDOWS = [3, 5, 10];

	let xg = $state<XgLeadersResponse | null>(null);
	let defcon = $state<DefconLeadersResponse | null>(null);
	let error = $state<string | null>(null);
	let loading = $state(true);
	// #137: pelimäärävalitsin (Wolfy: "more expansive to pick for more games")
	let gameWindow = $state(5);
	// #7 (30.7, Villen idea): DefConin basis. Esikaudella default = KOKO KAUSI:
	// 38 pelin hit-rate on vakain basis, ja "viimeiset N 25/26-pelia" on
	// mielivaltainen häntä ennen kuin uusi kausi tuottaa dataa.
	// 30.7 tarkennus (Ville): xG:n ja DefConin valitsimet ovat ERILLISET —
	// DefConin basis/ikkuna ei saa liikuttaa xG-listaa eikä toisinpäin.
	// Siksi oma dcWindow + kaksi erillistä hakuefektiä.
	let dcBasis = $state<'recent' | 'season'>('season');
	let dcWindow = $state(5);

	$effect(() => {
		const w = gameWindow;
		loading = true;
		error = null;
		fetchXgLeaders(w)
			.then((x) => (xg = x))
			.catch((e) => (error = e instanceof Error ? e.message : String(e)))
			.finally(() => (loading = false));
	});

	$effect(() => {
		const w = dcWindow;
		const b = dcBasis;
		fetchDefconLeaders(w, b)
			.then((d) => (defcon = d))
			.catch((e) => (error = e instanceof Error ? e.message : String(e)));
	});

	$effect(() => {
		// Paywall koskee enää DefConia — xG on ilmainen, joten sen näyttäminen
		// ei ole paywall-tapahtuma.
		if (!premium && (defcon?.players?.length ?? 0) > 0) {
			capture('paywall_shown', { source: 'fantasy_leaders' }, 'paywall_shown_fantasy_leaders');
		}
	});

	// 30.7 per-GW DefCon -matriisi (Vollo-vertailu): koko 25/26-kauden
	// kierroskohtaiset rivit laajennettavana rivina. Haetaan kerran, vasta
	// ensimmaisesta avauksesta (240 kB payload ei kuulu listan critical pathiin).
	let gwData = $state<DefconGwResponse | null>(null);
	let gwError = $state<string | null>(null);
	let expandedId = $state<number | null>(null);

	function toggleGw(id: number) {
		if (expandedId === id) {
			expandedId = null;
			return;
		}
		expandedId = id;
		capture('defcon_gw_expanded', { player_id: id });
		if (!gwData && !gwError) {
			fetchDefconGw().then(
				(d) => (gwData = d),
				(e) => (gwError = e instanceof Error ? e.message : String(e))
			);
		}
	}

	const gwById = $derived(new Map((gwData?.players ?? []).map((p) => [p.id, p])));

	// 26.7: sama kontrollisetti kuin julkisella /fpl/xg-leaders-sivulla. Ilman
	// naita SPA oli kapeampi kuin ilmainen SEO-sivu, mika on vaara suunta.
	// Season-nakymassa vasen vaihtoehto on TOTAALI, ei per ottelu: meilla on
	// avaukset (starts) muttei esiintymisia, joten aitoa per-ottelu-jakajaa ei ole.
	let per90 = $state(false);
	let minMins = $state(0);
	let posFilter = $state('');
	let teamFilter = $state('');
	let sortKey = $state<'xg' | 'xa' | 'xgi' | 'mins' | 'price' | 'games' | 'name' | 'xp6'>('xg');
	let sortDesc = $state(true);
	let seasonView = $state(false);

	const MIN_MINS = [0, 90, 180, 270];

	// #9b (31.7, Villen idea): hintahaarukkafiltteri — "Tarkowski vs 6.0m midit"
	// / "best budget defenders" yhdellä klikkauksella. Rajat jatkuvina väleinä,
	// labelit rehellisiä 0.1-hintagranulariteetille (siksi 8.1+, ei 8.0+).
	// xG-listassa VAPAA (koko lista on jo ilmainen, filtteri ei vuoda mitään);
	// DefConissa vain premiumille — vapaa filtteri antaisi enumeroida
	// premium-rivejä top-3:n ohi eri haarukoilla (sama logiikka kuin sorttigate).
	const PRICE_BANDS = [
		{ label: 'All', min: 0, max: Infinity },
		{ label: '4.5-', min: 0, max: 4.5 },
		{ label: '4.6-6.0', min: 4.6, max: 6.0 },
		{ label: '6.1-8.0', min: 6.1, max: 8.0 },
		{ label: '8.1+', min: 8.1, max: Infinity }
	] as const;
	type PriceBand = (typeof PRICE_BANDS)[number];
	let xgBand = $state<PriceBand>(PRICE_BANDS[0]);
	let dcBand = $state<PriceBand>(PRICE_BANDS[0]);
	function setBand(list: 'xg' | 'defcon', b: PriceBand) {
		if (list === 'xg') xgBand = b;
		else dcBand = b;
		capture('leaders_filtered', { list, band: b.label });
	}

	// #9b-c: 6 GW xP -sarake molempiin listoihin → poikkipositiovertailu
	// pisteillä onnistuu suoraan (data on jo /api/fantasy/xp:ssä). xP on
	// eteenpäin katsovaa mallidataa → sarake VAIN premiumille; ilmaisen
	// xG-listan vapautus (26.7) koski taaksepäin katsovaa hyödykedataa.
	let xpById = $state<Map<number, number> | null>(null);
	let xpHorizon = $state<number | null>(null);
	$effect(() => {
		if (!premium || xpById) return;
		fetchXp().then(
			(x) => {
				if (!x.meta?.available) return;
				xpById = new Map(
					x.players
						.filter((p) => typeof p.xp_horizon_total === 'number')
						.map((p) => [p.id, p.xp_horizon_total])
				);
				xpHorizon = x.meta.horizon_gw ?? null;
			},
			() => {
				// xP-haun kaatuminen ei saa kaataa leaders-listoja — sarake vain jää pois.
			}
		);
	});
	const xpLabel = $derived(xpHorizon ? `${xpHorizon}GW xP` : 'xP');
	const hasXpCol = $derived(premium && (xpById?.size ?? 0) > 0);

	type Agg = {
		row: (typeof xgRowsRaw)[number];
		xg: number;
		xa: number;
		xgi: number;
		mins: number;
		games: number;
	};

	const xgRowsRaw = $derived(xg?.players ?? []);

	function agg(r: (typeof xgRowsRaw)[number]): Agg {
		if (seasonView) {
			const s = r.season;
			const mins = s?.mins ?? 0;
			const d = per90 ? mins / 90 : 1;
			const k = d > 0 ? d : 1;
			return {
				row: r,
				xg: (s?.xg ?? 0) / k,
				xa: (s?.xa ?? 0) / k,
				xgi: (s?.xgi ?? 0) / k,
				mins,
				games: s?.starts ?? 0
			};
		}
		const mins = r.mins ?? 0;
		const d = per90 ? mins / 90 : r.games;
		const k = d > 0 ? d : 1;
		return {
			row: r,
			xg: (r.xg_per_game * r.games) / k,
			xa: (r.xa_per_game * r.games) / k,
			xgi: (r.xgi_per_game * r.games) / k,
			mins,
			games: r.games
		};
	}

	const teams = $derived([...new Set(xgRowsRaw.map((r) => r.team_short))].sort());

	const xgVisible = $derived.by(() => {
		const out: Agg[] = [];
		for (const r of xgRowsRaw) {
			if (posFilter && r.pos !== posFilter) continue;
			if (teamFilter && r.team_short !== teamFilter) continue;
			// #9b: hintahaarukka (vapaa — koko xG-lista on jo ilmainen)
			if (r.price < xgBand.min || r.price > xgBand.max) continue;
			if (seasonView && !r.season) continue;
			const a = agg(r);
			if (per90 && a.mins < 1) continue;
			if (a.mins < minMins) continue;
			out.push(a);
		}
		// HUOM: vertailut ovat muotoa (y - x) eli VALMIIKSI laskevia, joten
		// laskevassa kertoimen on oltava +1. Aiempi -1 kaansi listan nurin
		// (xG 0.00 karjessa).
		const dir = sortDesc ? 1 : -1;
		out.sort((x, y) => {
			if (sortKey === 'name') return dir * y.row.web_name.localeCompare(x.row.web_name);
			if (sortKey === 'price') return dir * (y.row.price - x.row.price);
			if (sortKey === 'xp6') {
				// Puuttuva projektio (ei projektiossa / ei premium-dataa) aina hännille.
				const xv = xpById?.get(x.row.id) ?? -Infinity;
				const yv = xpById?.get(y.row.id) ?? -Infinity;
				return dir * (yv - xv);
			}
			return dir * ((y[sortKey] as number) - (x[sortKey] as number));
		});
		return out;
	});

	// Naytetaan 100 riviä kerrallaan. Sama oppi kuin /fpl/xg-leaders-sivulla:
	// koko listan (373) renderointi jokaisella suodatinklikkauksella lagasi.
	// Suodatus ja lajittelu koskevat silti KOKO aineistoa.
	const RENDER_LIMIT = 100;
	let showAllXg = $state(false);
	const xgShown = $derived(showAllXg ? xgVisible : xgVisible.slice(0, RENDER_LIMIT));

	function sortBy(k: typeof sortKey) {
		if (sortKey === k) sortDesc = !sortDesc;
		else {
			sortKey = k;
			sortDesc = k !== 'name';
		}
	}

	function setSeason(v: boolean) {
		seasonView = v;
		// Per 90:een siirryttaessa oletuskynnys paalle, takaisin pois.
		if (!v && minMins === 180 && !per90) minMins = 0;
	}

	function setPer90(v: boolean) {
		const was = per90;
		per90 = v;
		if (!was && v && minMins === 0) minMins = 180;
		if (was && !v && minMins === 180) minMins = 0;
	}
	// #7: top_n nostettiin 20 → 400 ("vain 20 pelaajaa" -havainto) → sama
	// RENDER_LIMIT + Show all -kaava kuin xG-listassa, ettei 373 rivin
	// renderöinti lagaa. Suodatus/gate koskee silti koko aineistoa.
	let showAllDc = $state(false);
	const dcAll = $derived(defcon?.players ?? []);
	// 31.7 (Villen pyyntö; _fpltips-kulma "best budget defenders"): DefCon-
	// taulun saraksorttaus, erityisesti hinnan mukaan. VAIN premiumille:
	// free näkee top-3 leadersit palvelinjärjestyksessä, ja vapaa sortti
	// antaisi enumeroida premium-rivejä kolme kerrallaan eri avaimilla.
	// Hinta aukeaa halvin ensin (budjettikulma), muut suurin ensin.
	let dcSortKey = $state<'hit' | 'dc' | 'price' | 'pts' | 'games' | 'name' | 'pos' | 'xp6'>('hit');
	let dcSortDesc = $state(true);
	// #226-DC (1.8): kausibasiksella hit rate lasketaan STARTEISTA, sama
	// nimittäjä kuin Premier Leaguen omissa luvuissa. Otoskoko-sarake näyttää
	// silloin startit, ei pelattuja otteluita, jotta luku ja sen nimittäjä
	// ovat samalla rivillä (aiemmin: 47 % ja "26 games" = eri joukot).
	const dcSeason = $derived(defcon?.meta?.window === 'season');
	const hitRateHelp = $derived(
		dcSeason
			? 'Share of the player’s starts where he reached the DefCon threshold, the same basis the official FPL figures use'
			: 'Share of played games in the window where the player reached the DefCon threshold'
	);
	const dcSampleLabel = $derived(dcSeason ? 'Starts' : 'Games');
	const dcSampleHelp = $derived(
		dcSeason
			? 'Starts in the basis season (the denominator of the hit rate)'
			: 'Games played in the window (real sample size)'
	);
	const DC_SORT_FIELDS = {
		hit: 'hit_rate_pct',
		dc: 'dc_per_game',
		price: 'price',
		pts: 'defcon_points_window',
		games: 'games'
	} as const;
	// Otoskoko-solu: kausibasiksella startit (hit raten nimittäjä), muuten
	// pelatut. Defensiivinen fallback jos payload on vanhaa (ei starts-kenttää).
	const dcSample = (p: { games: number; starts?: number }) =>
		dcSeason && typeof p.starts === 'number' ? p.starts : p.games;
	const dcSorted = $derived.by(() => {
		if (!premium) return dcAll;
		const dir = dcSortDesc ? 1 : -1;
		// #9b: hintahaarukka ENNEN sorttia — vain premium (free-polku ei koske tätä).
		const rows = dcAll.filter((p) => p.price >= dcBand.min && p.price <= dcBand.max);
		rows.sort((x, y) => {
			if (dcSortKey === 'name') return dir * y.web_name.localeCompare(x.web_name);
			if (dcSortKey === 'pos') return dir * y.pos.localeCompare(x.pos);
			if (dcSortKey === 'xp6') {
				const xv = xpById?.get(x.id) ?? -Infinity;
				const yv = xpById?.get(y.id) ?? -Infinity;
				const d = dir * (yv - xv);
				return d !== 0 ? d : y.dc_per_game - x.dc_per_game;
			}
			const f = DC_SORT_FIELDS[dcSortKey];
			const d = dir * ((y[f] as number) - (x[f] as number));
			// Tiebreak aina dc/game desc — sama kuin palvelimen toissijainen avain.
			return d !== 0 ? d : y.dc_per_game - x.dc_per_game;
		});
		return rows;
	});
	const dcVisible = $derived(
		premium
			? showAllDc
				? dcSorted
				: dcSorted.slice(0, RENDER_LIMIT)
			: dcAll.slice(0, FREE_ROWS)
	);
	function dcSortBy(k: typeof dcSortKey) {
		if (dcSortKey === k) {
			dcSortDesc = !dcSortDesc;
		} else {
			dcSortKey = k;
			dcSortDesc = k !== 'name' && k !== 'pos' && k !== 'price';
		}
		capture('leaders_sorted', { list: 'defcon', key: k, desc: dcSortDesc });
	}
	const basisLabel = $derived(xg?.meta?.basis_label ?? defcon?.meta?.basis_label ?? null);

	function unlock() {
		capture('upgrade_tapped', { source: 'fantasy_leaders' });
		onUpgrade?.();
	}

	// #9a: Share as image molemmista listoista — jakaa NÄKYVÄN näkymän
	// (aktiiviset suodattimet mukana, top 10). Vain premiumille: kortti on
	// premium-datan johdannainen ja jakaja mainostaa meitä omilla luvuillamme.
	let sharing = $state<'' | 'xg' | 'defcon'>('');
	function bandPart(b: PriceBand): string[] {
		return b.label === 'All' ? [] : [`${b.label}m`];
	}
	async function shareXg() {
		if (sharing) return;
		sharing = 'xg';
		try {
			const basisPart = seasonView
				? 'season totals'
				: `last ${xg?.meta?.window ?? gameWindow} games`;
			const sub = [basisPart, ...(per90 ? ['per 90'] : []), ...bandPart(xgBand)].join(', ');
			const method = await shareCard({
				title: 'XG LEADERS TOP 10',
				subtitle: `${sub}, official FPL data`,
				midLabel: 'PRICE',
				valueLabel: 'xG',
				fileName: 'goaliq_xg_leaders.png',
				rows: xgVisible.slice(0, 10).map((a, i) => ({
					rank: i + 1,
					name: a.row.web_name,
					tag: a.row.pos,
					team: a.row.team_short,
					mid: a.row.price.toFixed(1),
					value: a.xg.toFixed(2)
				}))
			});
			if (method !== 'aborted') capture('xp_card_shared', { list: 'xg', method });
		} finally {
			sharing = '';
		}
	}
	async function shareDc() {
		if (sharing) return;
		sharing = 'defcon';
		try {
			const basisPart =
				dcBasis === 'season'
					? `full ${defcon?.meta?.basis_season ?? 'previous'} season`
					: `last ${dcWindow} games`;
			const sub = [basisPart, ...bandPart(dcBand)].join(', ');
			const method = await shareCard({
				title: 'DEFCON LEADERS TOP 10',
				subtitle: `${sub}, DefCon hit rate per ${dcBasis === 'season' ? 'start' : 'game'}, GoalIQ`,
				midLabel: 'PRICE',
				valueLabel: 'HIT',
				fileName: 'goaliq_defcon_leaders.png',
				rows: dcSorted.slice(0, 10).map((p, i) => ({
					rank: i + 1,
					name: p.web_name,
					tag: p.pos,
					team: p.team_short,
					mid: p.price.toFixed(1),
					value: `${Math.round(p.hit_rate_pct)}%`
				}))
			});
			if (method !== 'aborted') capture('xp_card_shared', { list: 'defcon', method });
		} finally {
			sharing = '';
		}
	}

	// 26.7 PERF: TeamKit renderoi per rivi 4 polkua + tekstin = ~500 SVG-solmua
	// 100 rivilla, ja lajittelu siirtelee ne kaikki -> lagi. Sama korjaus kuin
	// staattisella /fpl/xg-leaders-sivulla: yksi <symbol> per joukkue kerran,
	// rivit viittaavat siihen <use>:lla.
	const JERSEY =
		'M 33 15 L 43 9 C 46 15 54 15 57 9 L 67 15 L 84 27 L 76 42 L 67 36 ' +
		'L 67 86 Q 67 90 63 90 L 37 90 Q 33 90 33 86 L 33 36 L 24 42 L 16 27 Z';
	const SLEEVE_L = 'M 33 15 L 16 27 L 24 42 L 33 36 Z';
	const SLEEVE_R = 'M 67 15 L 84 27 L 76 42 L 67 36 Z';
	function darken(hex: string, f = 0.7): string {
		const m = /^#?([0-9a-f]{6})$/i.exec(hex.trim());
		if (!m) return hex;
		const n = parseInt(m[1], 16);
		const p = [16, 8, 0].map((s) => Math.max(0, Math.round(((n >> s) & 0xff) * f)));
		return `#${p.map((v) => v.toString(16).padStart(2, '0')).join('')}`;
	}
	const kitDefs = $derived(
		teams.map((t) => {
			const c = teamColorByShort(t);
			return { short: t, color: c.color, sleeve: darken(c.color) };
		})
	);
</script>

<!-- Paitakirjasto kerran: rivit viittaavat naihin <use>:lla (perf). -->
<svg width="0" height="0" style="position:absolute" aria-hidden="true">
	<defs>
		{#each kitDefs as k (k.short)}
			<symbol id="lk{k.short}" viewBox="0 0 100 100">
				<path d={JERSEY} fill={k.color} />
				<path d={SLEEVE_L} fill={k.sleeve} />
				<path d={SLEEVE_R} fill={k.sleeve} />
				<path
					d={JERSEY}
					fill="none"
					stroke="rgba(243,242,242,0.35)"
					stroke-width="3"
					stroke-linejoin="round"
				/>
			</symbol>
		{/each}
	</defs>
</svg>

<div class="head-row">
	<h2>xG leaders</h2>
	{#if premium}
		<!-- #9a: jaettava kortti näkyvästä näkymästä (premium) -->
		<button type="button" class="window-chip" onclick={shareXg} disabled={sharing !== ''}>
			{sharing === 'xg' ? 'Rendering…' : canShareToApps() ? 'Share as image' : 'Download image'}
		</button>
	{/if}
</div>
<p class="muted">
	Top expected-goals producers over each player's last {xg?.meta?.window ?? gameWindow} games, from
	official FPL match data.
</p>
<!-- #137 + 26.7: sama kontrollisetti kuin julkisella /fpl/xg-leaders-sivulla.
     Games vaihtaa window-parametrin molemmille listoille; Season, Rate, Min
     mins, Position ja Team ovat klienttipuolen suodattimia xG-listalle. -->
<div class="window-row">
	<span class="muted">Games:</span>
	{#each WINDOWS as w (w)}
		<button
			type="button"
			class="window-chip"
			class:on={!seasonView && gameWindow === w}
			onclick={() => {
				setSeason(false);
				gameWindow = w;
			}}
		>
			{w}
		</button>
	{/each}
	<button
		type="button"
		class="window-chip"
		class:on={seasonView}
		onclick={() => setSeason(true)}>Season</button
	>
	<span class="muted">Rate:</span>
	<button type="button" class="window-chip" class:on={!per90} onclick={() => setPer90(false)}>
		{seasonView ? 'Total' : 'Per game'}
	</button>
	<button type="button" class="window-chip" class:on={per90} onclick={() => setPer90(true)}>
		Per 90
	</button>
	<span class="muted">Min mins:</span>
	{#each MIN_MINS as m (m)}
		<button type="button" class="window-chip" class:on={minMins === m} onclick={() => (minMins = m)}>
			{m === 0 ? 'Any' : `${m}+`}
		</button>
	{/each}
	<span class="muted">Pos:</span>
	{#each ['', 'GKP', 'DEF', 'MID', 'FWD'] as pp (pp)}
		<button
			type="button"
			class="window-chip"
			class:on={posFilter === pp}
			onclick={() => (posFilter = pp)}>{pp === '' ? 'All' : pp}</button
		>
	{/each}
	<!-- #9b: hintahaarukka (vapaa xG-listassa — koko lista on jo ilmainen) -->
	<span class="muted">Price:</span>
	{#each PRICE_BANDS as b (b.label)}
		<button
			type="button"
			class="window-chip"
			class:on={xgBand === b}
			onclick={() => setBand('xg', b)}>{b.label}</button
		>
	{/each}
	<select bind:value={teamFilter} aria-label="Filter by team">
		<option value="">All teams</option>
		{#each teams as tt (tt)}<option value={tt}>{tt}</option>{/each}
	</select>
</div>
{#if basisLabel}
	<!-- Data-rajoitus ensiluokkaisena: basis-label aina näkyvissä -->
	<p class="basis">{basisLabel}</p>
{/if}

{#if loading && !xg}
	<!-- 30.7 fix (Villen "napit ei toimi"): skeleton VAIN ensilatauksessa.
	     Basis/window-vaihdossa vanha lista pysyy paikallaan kunnes uusi data
	     saapuu — koko paneelin romahdus skeletoniksi hyppäytti scrollin
	     muualle ja klikki näytti tekevän ei-mitään. -->
	<p class="muted">Loading leaderboards…</p>
{:else if error}
	<p class="banner error">{error}</p>
{:else}
	{#if xgVisible.length === 0}
		<p class="muted">No data yet.</p>
	{:else}
		<div class="table-wrap">
			<table>
				<thead>
					<tr>
						<th>#</th>
						<th><button type="button" class="sortbtn" onclick={() => sortBy('name')}>Player</button></th>
						<th class="m-hide">Pos</th>
						<th class="num m-hide"><button type="button" class="sortbtn" onclick={() => sortBy('price')}>Price</button></th>
						<th class="num"><button type="button" class="sortbtn" onclick={() => sortBy('xg')}>xG</button></th>
						<th class="num"><button type="button" class="sortbtn" onclick={() => sortBy('xa')}>xA</button></th>
						<th class="num"><button type="button" class="sortbtn" onclick={() => sortBy('xgi')}>xGI</button></th>
						<th class="num m-hide"><button type="button" class="sortbtn" onclick={() => sortBy('mins')}>Mins</button></th>
						<th class="num m-hide"><button type="button" class="sortbtn" onclick={() => sortBy('games')}>{seasonView ? 'Starts' : 'Games'}</button></th>
						{#if hasXpCol}
							<!-- #9b-c: mallin projektio rinnalle (vain premium — xP on
							     eteenpäin katsovaa mallidataa, ei ilmaista hyödykedataa) -->
							<th class="num"><button type="button" class="sortbtn" onclick={() => sortBy('xp6')}><abbr title="Projected FPL points over the model horizon (GoalIQ model)">{xpLabel}</abbr></button></th>
						{/if}
					</tr>
				</thead>
				<tbody>
					{#each xgShown as a, i (a.row.id)}
						<tr>
							<td class="muted">{i + 1}</td>
							<td class="pl">
								<svg class="kit" width="26" height="26" aria-hidden="true">
									<use href="#lk{a.row.team_short}" />
								</svg>
								<span>{a.row.web_name} <span class="muted">({a.row.team_short})</span></span>
							</td>
							<td class="m-hide">{a.row.pos}</td>
							<td class="num m-hide">{a.row.price.toFixed(1)}</td>
							<td class="num strong">{a.xg.toFixed(2)}</td>
							<td class="num">{a.xa.toFixed(2)}</td>
							<td class="num">{a.xgi.toFixed(2)}</td>
							<td class="num m-hide">{a.mins}</td>
							<td class="num m-hide">{a.games}</td>
							{#if hasXpCol}
								{@const xv = xpById?.get(a.row.id)}
								<td class="num">{typeof xv === 'number' ? xv.toFixed(1) : ''}</td>
							{/if}
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
		{#if !showAllXg && xgVisible.length > RENDER_LIMIT}
			<button type="button" class="window-chip" onclick={() => (showAllXg = true)}>
				Show all {xgVisible.length} players
			</button>
		{/if}
		<p class="muted count">
			{xgVisible.length} players{per90 ? ', per 90 minutes' : seasonView ? ', season totals' : ', per game'}{seasonView
				? ', full season'
				: `, last ${xg?.meta?.window ?? gameWindow} games each`}{minMins
				? `, at least ${minMins} minutes played`
				: ''}{xgBand.label === 'All' ? '' : `, price ${xgBand.label}m`}
		</p>
	{/if}

	<div class="head-row dc-title">
		<h2>DefCon leaders</h2>
		{#if premium}
			<!-- #9a: jaettava kortti näkyvästä näkymästä (premium) -->
			<button type="button" class="window-chip" onclick={shareDc} disabled={sharing !== ''}>
				{sharing === 'defcon' ? 'Rendering…' : canShareToApps() ? 'Share as image' : 'Download image'}
			</button>
		{/if}
	</div>
	<p class="muted">
		{#if dcBasis === 'season'}
			The most reliable defensive-contribution scorers across the full {defcon?.meta
				?.basis_season ?? 'previous'} season, every player. Hit rate is the share of a player's
			starts that reached the threshold, the same basis the official FPL figures use, and the
			table needs at least {defcon?.meta?.pool_min_starts ?? 19} starts to rank.
		{:else}
			The most reliable defensive-contribution scorers over each player's last {defcon?.meta
				?.window ?? dcWindow} games.
		{/if}
		2 pts when a defender reaches 10 CBIT (clearances, blocks, interceptions, tackles) or a
		midfielder/forward reaches 12 CBIRT (CBIT + recoveries) in a match. Tap a player to open the
		full gameweek-by-gameweek breakdown.
	</p>
	<!-- #7 (30.7): DefConin oma basis-valitsin. Season = koko basis-kausi
	     per-GW-matriisin summista (esikauden default); 3/5/10 = rolling-ikkuna
	     kuten ennen. Erillään xG:n Games-valitsimesta — eri lista, eri basis. -->
	<div class="window-row">
		<span class="muted">Basis:</span>
		<button
			type="button"
			class="window-chip"
			class:on={dcBasis === 'season'}
			aria-pressed={dcBasis === 'season'}
			onclick={() => (dcBasis = 'season')}>Full season</button
		>
		{#each WINDOWS as w (w)}
			<button
				type="button"
				class="window-chip"
				class:on={dcBasis === 'recent' && dcWindow === w}
				aria-pressed={dcBasis === 'recent' && dcWindow === w}
				onclick={() => {
					dcBasis = 'recent';
					dcWindow = w;
				}}>Last {w}</button
			>
		{/each}
		{#if premium}
			<!-- #9b: hintahaarukka vain premiumille (vapaa filtteri antaisi
			     enumeroida premium-rivejä top-3:n ohi — sama logiikka kuin sortti) -->
			<span class="muted">Price:</span>
			{#each PRICE_BANDS as b (b.label)}
				<button
					type="button"
					class="window-chip"
					class:on={dcBand === b}
					onclick={() => setBand('defcon', b)}>{b.label}</button
				>
			{/each}
		{/if}
	</div>
	<!-- 30.7: rehellisyysnote OMASTA mittauksesta. Emme myy vastustajakontekstia
	     signaalina jota mittaus ei löydä (korrelaatio +0.026, 7 382 ottelua). -->
	<p class="muted dc-honesty">
		Worth knowing before you read fixtures into this: DefCon follows the player, not the
		fixture. In 25/26 data the opponent shifted a player's DefCon count by about 2%. Bonus is
		the stat that moves with fixtures.
	</p>
	{#if dcVisible.length === 0}
		<p class="muted">No data yet.</p>
	{:else}
		<div class="table-wrap">
			<table>
				<thead>
					<tr>
						<th>#</th>
						<!-- 31.7: sorttaus vain premiumille (ks. dcSorted-kommentti) -->
						<th>
							{#if premium}<button type="button" class="sortbtn" onclick={() => dcSortBy('name')}
									>Player</button
								>{:else}Player{/if}
						</th>
						<th class="m-hide">
							{#if premium}<button type="button" class="sortbtn" onclick={() => dcSortBy('pos')}
									>Pos</button
								>{:else}Pos{/if}
						</th>
						<th class="num m-hide">
							{#if premium}<button type="button" class="sortbtn" onclick={() => dcSortBy('price')}
									>Price</button
								>{:else}Price{/if}
						</th>
						<th class="num">
							{#if premium}<button type="button" class="sortbtn" onclick={() => dcSortBy('dc')}
									><abbr title="Defensive-contribution actions per game">DC/game</abbr></button
								>{:else}<abbr title="Defensive-contribution actions per game">DC/game</abbr>{/if}
						</th>
						<th class="num">
							{#if premium}<button type="button" class="sortbtn" onclick={() => dcSortBy('hit')}
									><abbr title={hitRateHelp}>Hit rate</abbr></button
								>{:else}<abbr title={hitRateHelp}>Hit rate</abbr
								>{/if}
						</th>
						<th class="num m-hide">
							{#if premium}<button type="button" class="sortbtn" onclick={() => dcSortBy('pts')}
									><abbr title="DefCon points earned in the window">Pts</abbr></button
								>{:else}<abbr title="DefCon points earned in the window">Pts</abbr>{/if}
						</th>
						<th class="num m-hide">
							{#if premium}<button type="button" class="sortbtn" onclick={() => dcSortBy('games')}
									><abbr title={dcSampleHelp}>{dcSampleLabel}</abbr></button
								>{:else}<abbr title={dcSampleHelp}>{dcSampleLabel}</abbr
								>{/if}
						</th>
						{#if hasXpCol}
							<!-- #9b-c: sama premium-projektiosarake kuin xG-listassa -->
							<th class="num m-hide">
								<button type="button" class="sortbtn" onclick={() => dcSortBy('xp6')}
									><abbr title="Projected FPL points over the model horizon (GoalIQ model)"
										>{xpLabel}</abbr
									></button
								>
							</th>
						{/if}
					</tr>
				</thead>
				<tbody>
					{#each dcVisible as p, i (p.id)}
						<tr class:expanded={expandedId === p.id}>
							<td class="muted">{i + 1}</td>
							<td class="pl">
								<button
									type="button"
									class="gw-toggle"
									aria-expanded={expandedId === p.id}
									onclick={() => toggleGw(p.id)}
								>
									<svg class="kit" width="26" height="26" aria-hidden="true">
										<use href="#lk{p.team_short}" />
									</svg>
									<span>{p.web_name} <span class="muted">({p.team_short})</span></span>
									<span class="chev" aria-hidden="true">{expandedId === p.id ? '▾' : '▸'}</span>
								</button>
							</td>
							<td class="m-hide">{p.pos}</td>
							<td class="num m-hide">{p.price.toFixed(1)}</td>
							<td class="num">{p.dc_per_game.toFixed(1)}</td>
							<td class="num strong"
								>{Math.round(p.hit_rate_pct)}%{#if p.pos_changed}<abbr
										class="reclass"
										title="Played as a {p.basis_pos} in {defcon?.meta?.basis_season ??
											'the basis season'} and is a {p.pos} now, so a different threshold applies. At the {p.basis_pos} threshold the same starts give {p.hit_rate_basis_pos_pct}%.">*</abbr
									>{/if}</td
							>
							<td class="num m-hide">{p.defcon_points_window}</td>
							<td class="num m-hide">{dcSample(p)}</td>
							{#if hasXpCol}
								{@const xv = xpById?.get(p.id)}
								<td class="num m-hide">{typeof xv === 'number' ? xv.toFixed(1) : ''}</td>
							{/if}
						</tr>
						{#if expandedId === p.id}
							{@const g = gwById.get(p.id)}
							<tr class="gw-row">
								<td colspan={hasXpCol ? 9 : 8}>
									{#if gwError}
										<p class="muted">Could not load the gameweek data: {gwError}</p>
									{:else if !gwData}
										<p class="muted">Loading the 38-gameweek breakdown…</p>
									{:else if !g}
										<p class="muted">No gameweek data for this player yet.</p>
									{:else}
										<div class="gw-strip" role="list">
											{#each g.per_gw as r, i (i)}
												<span
													role="listitem"
													class="gw-chip"
													class:hit={r[4] >= g.threshold}
													title="GW{r[0]} {r[2] === 'H' ? 'vs' : 'at'} {r[1]}: {r[4]} defensive actions in {r[3]} min{r[4] >= g.threshold ? ', DefCon points earned' : ''}"
												>
													<span class="gw-n">{r[0]}</span>{r[4]}
												</span>
											{/each}
										</div>
										<p class="muted gw-note">
											{g.starts ?? g.games} starts in {g.basis ?? '2025/26'}: {g.start_hits ??
												g.hits} above the threshold of {g.threshold} ({Math.round(
												g.hit_rate * 100
											)}%), worth {g.dc_points} DefCon points across all {g.games} appearances.
											{gwData.meta.basis_label}
										</p>
									{/if}
								</td>
							</tr>
						{/if}
					{/each}
				</tbody>
			</table>
		</div>
	{/if}

	{#if premium && !showAllDc && dcAll.length > RENDER_LIMIT}
		<!-- #7: sama Show all -kaava kuin xG-listassa (perf, ei gate). -->
		<button type="button" class="window-chip" onclick={() => (showAllDc = true)}>
			Show all {dcAll.length} players
		</button>
	{/if}

	{#if !premium && dcAll.length > FREE_ROWS}
		<!-- 🔒 DefCon top-3 free → koko lista premium. xG-lista on ilmainen. -->
		<button type="button" class="teaser-row" onclick={unlock}>
			<span>
				Full DefCon leaderboard <span class="muted">(top 3 shown free)</span>
			</span>
			<span class="locked" aria-label="Locked">•.••</span>
			<span class="cta">Unlock with Premium</span>
		</button>
	{/if}
{/if}

<style>
	/* #9a: otsikko + Share as image samalle riville */
	.head-row {
		display: flex;
		align-items: baseline;
		justify-content: space-between;
		gap: var(--s-2);
		flex-wrap: wrap;
	}
	.head-row h2 {
		margin: 0;
	}
	.window-chip:disabled {
		opacity: 0.6;
		cursor: default;
	}
	/* 30.7 per-GW DefCon -matriisi */
	.dc-honesty {
		border-left: 3px solid var(--accent, #f5c542);
		padding-left: var(--s-2);
		font-size: var(--step--1);
	}
	.gw-toggle {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		background: none;
		border: 0;
		padding: 0;
		color: inherit;
		font: inherit;
		cursor: pointer;
		text-align: left;
	}
	.gw-toggle .chev {
		color: var(--muted-fg, #8a847a);
		font-size: var(--step--1);
	}
	.gw-row td {
		background: var(--surface, transparent);
	}
	.gw-strip {
		display: flex;
		flex-wrap: wrap;
		gap: 4px;
		padding: var(--s-2) 0 var(--s-1);
	}
	.gw-chip {
		display: inline-flex;
		align-items: baseline;
		gap: 3px;
		border: 1px solid var(--border);
		padding: 2px 6px;
		font-size: var(--step--1);
		font-variant-numeric: tabular-nums;
		color: var(--muted-fg, inherit);
	}
	.gw-chip.hit {
		border-color: var(--teal, #2ed6c2);
		color: var(--teal, #2ed6c2);
		font-weight: 700;
	}
	.gw-chip .gw-n {
		font-size: 0.72em;
		opacity: 0.7;
	}
	.gw-note {
		font-size: var(--step--1);
		margin: 0 0 var(--s-2);
	}
	/* #226-DC: tahti = positio vaihtui kausien valilla -> kynnys eri kuin
	   basis-kaudella. Selitys on abbr:n titlessa, ei piilotettuna. */
	.reclass {
		text-decoration: none;
		cursor: help;
		opacity: 0.75;
	}
	/* 26.7: aktiivinen suodatin auki tekstina, ei hiljaista rajausta */
	.count {
		font-size: var(--step--1);
		margin: var(--s-2) 0 0;
	}
	/* 26.7: lajitteluotsikot ja joukkuevalitsin (pariteetti xg-leaders-sivun kanssa) */
	.sortbtn {
		background: none;
		border: 0;
		padding: 0;
		font: inherit;
		color: inherit;
		cursor: pointer;
	}
	.sortbtn:hover {
		color: var(--giq-rust);
	}
	.window-row select {
		flex: 0 0 auto;
		border: 1px solid var(--border);
		border-radius: var(--radius);
		background: var(--surface);
		color: var(--text);
		font-weight: 600;
		font-size: var(--step--1);
		padding: 4px 10px;
		line-height: 1.4;
	}
	/* 26.7: paita + nimi samalle riville, paita ei kutistu */
	.pl {
		display: flex;
		align-items: center;
		gap: 8px;
	}
	.pl :global(svg) {
		flex: 0 0 auto;
	}
	.kit {
		flex: 0 0 auto;
		display: block;
	}
	.basis {
		color: var(--giq-gold-deep);
		font-weight: 600;
		font-size: var(--step--1);
		margin: 0 0 var(--s-3);
	}
	/* #137: pelimäärävalitsin */
	/* 26.7: rivi karii. Kontrolleja on nyt ~18 (Games/Season/Rate/Min mins/Pos/
	   Team) yhden pelimaaravalitsimen sijaan, ja ilman wrapia flex puristi ne
	   samalle riville -> "Season" ja "Per game" eivat mahtuneet pallukkaan. */
	.window-row {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--s-2);
		row-gap: var(--s-2);
		margin: 0 0 var(--s-2);
		font-size: var(--step--1);
	}
	.window-row > span {
		flex: 0 0 auto;
	}
	.window-chip {
		flex: 0 0 auto;
		min-width: 36px;
		border: 1px solid var(--border);
		border-radius: var(--radius);
		background: var(--surface);
		color: var(--text-muted);
		font-weight: 700;
		font-size: var(--step--1);
		padding: 4px 12px;
		cursor: pointer;
		text-align: center;
		white-space: nowrap;
		line-height: 1.4;
	}
	/* 26.7 classic: outline, ei täyttöä */
	.window-chip.on {
		background: transparent;
		border-color: var(--accent);
		color: var(--accent-strong);
	}
	.dc-title {
		margin-top: var(--s-5);
	}
	.strong {
		font-weight: 800;
		color: var(--giq-rust);
	}
	.teaser-row {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--s-2);
		width: 100%;
		margin-top: var(--s-3);
		background: rgba(255, 138, 92, 0.1);
		border: 1px solid rgba(255, 138, 92, 0.35);
		border-radius: var(--radius);
		padding: var(--s-2) var(--s-3);
		color: var(--text);
		font-weight: 600;
		font-size: var(--step--1);
		cursor: pointer;
		text-align: left;
	}
	.teaser-row .cta {
		margin-left: auto;
		color: var(--positive);
		font-weight: 700;
	}
	.locked {
		letter-spacing: 2px;
		color: var(--text-muted);
	}
</style>
