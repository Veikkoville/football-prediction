<script lang="ts">
	// UX-palaute-erä (25.7) kohta 1: player card / hakutietopankki
	// (Dubravka-case). FREE — kaikki kortin data on julkista (FPL bootstrap +
	// julkaistut GoalIQ-projektiot). Rehellisyysraja pidetään visuaalisesti:
	// "Official FPL status" -blokki = FPL:n virallinen fakta (status, news,
	// keltaiset, set-piece-listat), "GoalIQ model view" -blokki = mallin
	// estimaatti (p_start, confidence, data_basis, xP). Defensiiviset luvut:
	// vanha payload ilman uusia kenttiä ei kaada mitään.
	import {
		fetchXp,
		fetchPlayerDefcon,
		type CardPlayer,
		type DefconPlayerResponse,
		type XpMeta
	} from '$lib/api';
	// Free-tier-rajaus (Villen havainto 25.7): xP-numerot ovat premium-arvoa
	// kaikkialla muualla -> kortti nayttaa ne vain premium-pinnalta (ProTools).
	let { premium = false }: { premium?: boolean } = $props();
	import { capture } from '$lib/analytics';
	import PlayerSearch from './PlayerSearch.svelte';
	import SetPieceBadges from './SetPieceBadges.svelte';
	import { canShareToApps, sharePlayerCard, type PlayerCardCell } from '$lib/shareCard';

	let pool = $state<CardPlayer[]>([]);
	let meta = $state<XpMeta | null>(null);
	let poolError = $state(false);
	$effect(() => {
		fetchXp().then(
			(d) => {
				// Hakupooli = projektio + excluded[]. Poissuljetut rivit (i/s/u/n
				// -status tai xP alle kynnyksen) tulevat payloadissa erillisenä
				// listana; jos ne jätettäisiin pois, hakukenttä vastaisi "ei
				// tuloksia" juuri niistä pelaajista joiden tilanne kiinnostaa
				// eniten. Projektiorivit ensin, jotta ne rankkaavat kärkeen.
				pool = [...(d.players ?? []), ...(d.excluded ?? [])];
				meta = d.meta ?? null;
			},
			() => (poolError = true)
		);
	});

	let query = $state('');
	let player = $state<CardPlayer | null>(null);

	// Sama normalisointi kuin FitChecker/XpTable-haussa (#145/#147-pariteetti).
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
	const matches = $derived.by(() => {
		const q = norm(query);
		if (q.length < 2) return [];
		return pool
			.filter(
				(p) =>
					norm(p.web_name).includes(q) ||
					(p.full_name ? norm(p.full_name).includes(q) : false) ||
					norm(p.team_short).includes(q)
			)
			.slice(0, 8);
	});

	// DefCon-erittely (Villen pyyntö 25.7): haetaan vasta valinnan yhteydessä,
	// jotta kortin avaus ei odota erillistä kutsua. GKP ei voi saada DefConia.
	let defcon = $state<DefconPlayerResponse | null>(null);
	let defconLoading = $state(false);

	async function loadDefcon(p: CardPlayer) {
		defcon = null;
		if (p.pos === 'GKP') return;
		defconLoading = true;
		try {
			defcon = await fetchPlayerDefcon(p.id, 10);
		} catch {
			defcon = null; // ei dataa (esim. ei otteluita) → osio jää pois
		} finally {
			defconLoading = false;
		}
	}

	function select(p: CardPlayer) {
		player = p;
		query = '';
		// Ei PII:tä: pelaaja-ID/positio/status ovat julkista FPL-dataa.
		capture('player_card_viewed', { player_id: p.id, pos: p.pos, status: p.status ?? 'a' });
		void loadDefcon(p);
	}

	// Virallinen FPL-status → label + sävy (EI mallin päättelyä).
	const STATUS_LABEL: Record<string, string> = {
		a: 'Available',
		d: 'Doubtful',
		i: 'Injured',
		s: 'Suspended',
		u: 'Unavailable',
		n: 'Not available'
	};
	const st = $derived(player?.status ?? 'a');
	const statusTone = $derived(st === 'a' ? 'ok' : st === 'd' ? 'warn' : 'out');

	// Pre-season: bootstrapin yellow_cards on vielä EDELLISEN kauden lukema
	// (contract-data.md luku 5) → rehellinen "last season" -label ilman
	// kynnyslaskentaa. Live-kaudella 5/10/15-kynnykset (5 keltaista = 1 GW:n
	// pelikielto, sääntö voimassa GW19 asti; 10 = 2 GW; 15 = 3 GW).
	const preseason = $derived(meta?.data_coverage?.baseline_mode === 'prev_season_archive');
	function suspensionLine(y: number): string {
		if (y < 5) return 'next suspension at 5 yellows (1-match ban, threshold applies until GW19)';
		if (y < 10) return 'next suspension at 10 yellows (2-match ban)';
		if (y < 15) return 'next suspension at 15 yellows (3-match ban)';
		return 'past the 15-yellow line (3-match ban)';
	}

	const spListed = $derived.by(() => {
		const sp = player?.set_pieces;
		if (!sp) return false;
		return [sp.pens, sp.corners, sp.fk].some((v) => typeof v === 'number' && v <= 2);
	});

	const DATA_BASIS_LABEL: Record<string, string> = {
		pl_history: "based on the player's own PL minutes",
		limited_history: 'thin PL sample, the position average carries most of the weight',
		no_history: 'no PL minutes yet, position average only'
	};

	// Etuliite aloitus-tn:n lähteelle. Sanamuoto kertoo KUKA luvun asetti:
	// "Set by hand" ei saa lukea kuten mallin oma arvio, koska se ei ole sitä.
	const MINUTES_SOURCE_LABEL: Record<string, string> = {
		override: 'Set by hand',
		price_prior: 'Role estimate',
		price_blend: 'Part model, part price'
	};

	// --- 4.8: odotetut maalit (VAIN MID/FWD) -----------------------------
	// Malli on laskenut taman koko ajan; se on vain ollut PISTEINA
	// (components.goals = xg90 * xmins/90 * goal_mult * GOAL_PTS[pos]).
	// Yksikko puretaan takaisin kappaleiksi jakamalla pistekertoimella.
	//
	// MIKSI VAIN MID/FWD: komponenttitason backtest 4.8 (25/26 walk-forward,
	// n=10 733 pelaaja-GW) mittasi jokaisen ryhman erikseen:
	//   FWD  bias -5.2 %   Brier 0.1553 vs naiivi 0.1596  (+2.7 %)
	//   MID  bias -10.7 %  Brier 0.0828 vs naiivi 0.0858  (+3.6 %)
	//   DEF  bias +4.6 %   Brier 0.0326 vs naiivi 0.0322  (-1.3 %)  <- HAVIAA
	// Puolustajilla luku ei siis voita naiivia vakiota, joten sita ei nayteta.
	//
	// SYOTTOJA EI NAYTETA LAINKAAN: sama backtest antoi biasiksi -40 %, ja syy
	// on lahdedatassa - FPL:n oma expected_assists on -27.5 % toteutuneista
	// syotoista (683 vs 942 kaudella 25/26), koska FPL palkitsee syotosta myos
	// ansaitusta rangaistuspotkusta ja kimmokkeista joita xA ei laske. Se ei
	// ole kalibrointivirhe vaan eri suure.
	const GOAL_PTS: Record<string, number> = { GKP: 10, DEF: 6, MID: 5, FWD: 4 };
	const goalOutlook = $derived.by(() => {
		const p = player;
		if (!p || excluded) return null;
		if (p.pos !== 'MID' && p.pos !== 'FWD') return null;
		const g = p.components?.goals;
		if (typeof g !== 'number' || !Number.isFinite(g)) return null;
		const eg = g / GOAL_PTS[p.pos];
		if (eg <= 0) return null;
		// P(vahintaan 1 maali) Poissonista. Tama on se muoto joka on
		// tarkistettavissa jalkikateen; 0.68 maalia ei ole.
		return { eg, pct: Math.round((1 - Math.exp(-eg)) * 100), gw: p.components_gw };
	});

	function fixtureLabel(opps: { opp: string; venue: string }[]): string {
		if (opps.length === 0) return 'Blank';
		return opps.map((o) => `${o.opp} (${o.venue})`).join(', ');
	}

	// --- Projektiosta poissuljetut pelaajat (edge-sprint addendum) ---------
	// Payload voi tuoda mukaan pelaajia joille xP:tä ei lasketa (in_projection
	// false, tai pitkä poissaolo i/u/n/s). Haku löytää heidät (pool-filtteri on
	// pelkkä nimihaku, ei projektiorajausta), mutta kortti EI saa näyttää
	// xP-lukuja: ne olisivat merkityksettömiä. Defensiivinen myös vanhalle
	// payloadille — kenttien puuttuessa kaikki käyttäytyy kuten ennen.
	const hasXp = $derived(
		!!player &&
			Array.isArray(player.gameweeks) &&
			player.gameweeks.length > 0 &&
			typeof player.xp_horizon_total === 'number' &&
			typeof player.xp_per_gw === 'number'
	);
	const excluded = $derived(!!player && (player.in_projection === false || !hasXp));
	const OUT_STATUS: Record<string, string> = {
		i: 'injured',
		s: 'suspended',
		u: 'unavailable',
		n: 'not available'
	};
	const exclusionReason = $derived.by(() => {
		if (!player) return null;
		if (player.excluded_reason === 'below_min_xp')
			return 'the model expects too few minutes to project points';
		if (OUT_STATUS[st]) return `FPL lists this player as ${OUT_STATUS[st]}`;
		if (player.excluded_reason === 'unavailable') return 'FPL lists this player as unavailable';
		return null;
	});

	// --- Viime kauden historia (FREE: julkista dataa, ei premium-gatea) ----
	type Cell = { key: string; label: string; value: string };
	function cell(key: string, label: string, v: unknown, digits = 0): Cell | null {
		if (typeof v !== 'number' || !Number.isFinite(v)) return null;
		return { key, label, value: v.toFixed(digits) };
	}
	const lastSeason = $derived(
		player?.last_season && typeof player.last_season === 'object' ? player.last_season : null
	);
	const lastSeasonLabel = $derived(
		typeof lastSeason?.season === 'string' && lastSeason.season ? lastSeason.season : '2025/26'
	);
	// Sarja mukaan kun payload kertoo sen: nousijoilla ja tulokkailla viime
	// kausi ei ole PL-kausi, eikä lukuja saa esittää sellaisena.
	const lastSeasonLeague = $derived(
		typeof lastSeason?.league === 'string' && lastSeason.league ? lastSeason.league : null
	);
	// Kenttäohjattu, ei muoto-ohjattu: payloadin lopullinen nimeäminen ei ole
	// vielä kontraktissa (litteä {minutes, points, ...} vs prev-baselines-
	// artefaktin {total_points, acc:{mins, xg, ...}}), joten jokainen luku
	// poimitaan aliaslistalla ja acc-fallbackilla. Ei osumaa = ruutua ei ole.
	function pickNum(src: Record<string, unknown> | null | undefined, keys: string[]): number | null {
		if (!src) return null;
		for (const k of keys) {
			const v = src[k];
			if (typeof v === 'number' && Number.isFinite(v)) return v;
		}
		return null;
	}
	function lsNum(keys: string[]): number | null {
		const ls = lastSeason;
		if (!ls) return null;
		return pickNum(ls, keys) ?? pickNum(ls.acc, keys);
	}
	const lsMinutes = $derived(lsNum(['minutes', 'mins']));
	const lsTotals = $derived.by((): Cell[] => {
		if (!lastSeason) return [];
		return [
			cell('minutes', 'Minutes', lsMinutes),
			cell('starts', 'Starts', lsNum(['starts'])),
			cell('n60', 'Games 60+ min', lsNum(['n60'])),
			cell('goals', 'Goals', lsNum(['goals'])),
			cell('assists', 'Assists', lsNum(['assists'])),
			cell('xg', 'xG', lsNum(['xg']), 1),
			cell('xa', 'xA', lsNum(['xa']), 1),
			cell('cs', 'Clean sheets', lsNum(['cs', 'clean_sheets'])),
			cell('saves', 'Saves', lsNum(['saves'])),
			cell('bonus', 'Bonus', lsNum(['bonus'])),
			cell('points', 'FPL points', lsNum(['points', 'total_points']))
		].filter((c): c is Cell => c != null);
	});
	// Per-90: käytetään payloadin valmiita arvoja jos ne tulevat, muuten
	// lasketaan minuuteista. Laskenta vasta 90 minuutista ylöspäin — pienestä
	// otoksesta johdettu per-90 olisi harhaanjohtava.
	const per90Computed = $derived(!lastSeason?.per90 && (lsMinutes ?? 0) >= 90);
	const lsPer90 = $derived.by((): Cell[] => {
		const ls = lastSeason;
		if (!ls) return [];
		const given = ls.per90 && typeof ls.per90 === 'object' ? ls.per90 : null;
		const mins = lsMinutes;
		const rate = (keys: string[]): number | null => {
			if (given) return pickNum(given, keys);
			if (!per90Computed || mins == null || mins <= 0) return null;
			const tot = lsNum(keys);
			return tot == null ? null : (tot / mins) * 90;
		};
		// xGI = maali + syöttö -osallisuus. Payload tuo sen valmiina; laskettuna
		// se on xG + xA samasta minuuttimäärästä.
		const xgi = (): number | null => {
			if (given) return pickNum(given, ['xgi']);
			if (!per90Computed || mins == null || mins <= 0) return null;
			const g = lsNum(['xg']);
			const a = lsNum(['xa']);
			if (g == null && a == null) return null;
			return (((g ?? 0) + (a ?? 0)) / mins) * 90;
		};
		return [
			cell('goals', 'Goals', rate(['goals']), 2),
			cell('assists', 'Assists', rate(['assists']), 2),
			cell('xg', 'xG', rate(['xg']), 2),
			cell('xa', 'xA', rate(['xa']), 2),
			cell('xgi', 'xGI', xgi(), 2),
			cell('saves', 'Saves', rate(['saves']), 2),
			cell('bonus', 'Bonus', rate(['bonus']), 2),
			cell('points', 'FPL points', rate(['points', 'total_points']), 2),
			cell('cs', 'Clean sheets', given ? pickNum(given, ['cs', 'clean_sheets']) : null, 2)
		].filter((c): c is Cell => c != null);
	});
	const showLastSeason = $derived(lsTotals.length > 0 || lsPer90.length > 0);

	// --- 4.8: jaettava pelaajakortti (Villen pyynto) ----------------------
	// Kortti jakaa TASAN sen mita katsoja itse nakee: free saa julkiset faktat
	// (FPL-status, hinta, omistus, aloitustodennakoisyys, viime kauden tuotanto),
	// premium saa lisaksi xP-rivin. Sama raja kuin itse kortissa (:348), joten
	// jakonappi ei voi vuotaa premium-lukua freelle.
	//
	// Nappi nakyy MYOS freelle, toisin kuin Leaders/Value/CaptainRanker. Peruste
	// on 2.8. paatos: kortti gatetaan premiumille vain kun se on premium-datan
	// johdannainen, ja juuri free-datan jakaminen ON jakelusilmukka - jakaja
	// mainostaa meita maksamatta. Pelaajakortti on paaosin julkista dataa ja se
	// on koko sivun oma lupaus ("Free ...").
	let sharing = $state(false);

	function startPct(p: CardPlayer): number | null {
		if (typeof p.p_start === 'number') return Math.round(p.p_start * 100);
		if (typeof p.predicted_starts === 'number') return Math.round(p.predicted_starts);
		return null;
	}

	/** Poimi solut avainjarjestyksessa, pudota puuttuvat. Pelipaikka ratkaisee:
	 *  maalivahdin maalit/syotot per 90 olisivat nollarivi eivatka kerro mitaan. */
	function pick(cells: Cell[], keys: string[], max: number): PlayerCardCell[] {
		const out: PlayerCardCell[] = [];
		for (const k of keys) {
			const c = cells.find((x) => x.key === k);
			if (c) out.push({ label: c.label, value: c.value });
			if (out.length >= max) break;
		}
		return out;
	}

	async function share() {
		const p = player;
		if (!p || sharing) return;
		sharing = true;
		try {
			const sp = startPct(p);
			const metaBits: string[] = [];
			if (typeof p.price === 'number' && p.price > 0) metaBits.push(`${p.price.toFixed(1)}m`);
			if (typeof p.owned_pct === 'number') metaBits.push(`${p.owned_pct.toFixed(1)}% owned`);

			// Tuotantorivi kayttaa KAUDEN KERTYMIA, ei per 90 -vauhteja. 1. veto
			// kaytti per 90:aa ja Zubimendin kortille tuli "0.15 goals / 0.03
			// assists" - teknisesti oikein mutta laiha jakolupaus, ja per-90-rivi
			// oli lisaksi harvemmin taytetty (vain 2/4 solua). Kertymat ovat se
			// muoto jossa FPL-yleiso lukee kauden.
			//
			// Pelipaikka ratkaisee jarjestyksen, ja se KORJATTIIN kuvasta: 1. veto
			// antoi kaikille kentallisille goals/assists/xg/xa, jolloin Gabrielin
			// kortti johti luvuilla 3 maalia ja 2.9 xG eika kertonut lainkaan
			// 18:aa clean sheetia - puolustajan koko FPL-valuuttaa. Kortissa on
			// nelja slottia, joten jarjestys on sisaltopaatos.
			//
			// minutes/starts/points EIVAT ole soluja: ne ovat jo totals-rivilla.
			// Raya sai solun "FPL POINTS 162" ja heti sen alle rivin
			// "... 162 FPL points" - sama luku kahdesti perakkain (nakyi vasta
			// kuvasta; GKP:lla saves/bonus puuttuvat payloadista, joten points
			// nousi listalta soluksi).
			const keys =
				p.pos === 'GKP'
					? ['cs', 'saves', 'bonus']
					: p.pos === 'DEF'
						? ['cs', 'goals', 'assists', 'bonus']
						: ['goals', 'assists', 'xg', 'xa', 'bonus'];
			const cells = pick(lsTotals, keys, 4);
			// Sanamuodot kasin: c.label.toLowerCase() tuotti "133 fpl points".
			const TOTALS_WORD: Record<string, string> = {
				minutes: 'minutes',
				starts: 'starts',
				points: 'FPL points'
			};
			const totalsLine = ['minutes', 'starts', 'points']
				.map((k) => {
					const c = lsTotals.find((x) => x.key === k);
					return c ? `${c.value} ${TOTALS_WORD[k]}` : null;
				})
				.filter((x): x is string => x != null)
				.join(' · ');

			// DefCon omalle riville: se on eri ikkuna kuin viime kausi, eika
			// niita saa esittaa samana lukusarjana.
			//
			// VAIN DEF/MID. FPL:ssa myos hyokkaaja voi saada DC-pisteita, mutta
			// kynnys (12 CBIRT) tayttyy karkipaikalla niin harvoin etta luku on
			// kaytannossa aina 0 % - Haalandin kortilla luki "DefCon 0% hit rate
			// over 10 games", mika ei kerro pelaajasta mitaan ja on
			// jaettavalla kortilla pelkkaa kohinaa. Puolustajalla sama luku on
			// kortin erottava sisalto.
			const dcRelevant = p.pos === 'DEF' || p.pos === 'MID';
			const dcLine =
				dcRelevant && defcon && defcon.totals.games > 0
					? `DefCon ${Math.round(defcon.totals.hit_rate_pct)}% hit rate over the last ${defcon.totals.games} games`
					: undefined;

			const noteBits: string[] = [];
			if (excluded) noteBits.push('not in the projections right now, official FPL data only');
			else if (sp != null) noteBits.push('start chance is a model estimate, not team news');
			// Datapohja MUKAAN kun se ei ole pelaajan oma PL-historia. Kortti nayttaa
			// aloitus-tn:n isolla, ja juuri uusilla pelaajilla luku ei tule heidan
			// omista minuuteistaan: nousijaseurojen historiattomat saavat hinnan
			// mukaisen rooliprioorin (kaikki samaan 72 %:iin), ohuen otoksen
			// pelaajilla positiokeskiarvo kantaa. Appi nayttaa taman labelin kortin
			// vieressa - jos se putoaa jaettavasta kuvasta, luku matkustaa ilman
			// sita varausta joka tekee siita rehellisen ([[honest-data-labels]]).
			if (!excluded && sp != null && p.data_basis && p.data_basis !== 'pl_history') {
				noteBits.push(DATA_BASIS_LABEL[p.data_basis] ?? p.data_basis);
			}
			// Lahde mukaan MYOS jaettavaan kuvaan. Kortti on se artefakti joka
			// lahtee appista ulos, ja juuri siina luku on isoimmillaan: jos
			// varaus jaa vain sivulle, luku matkustaa ilman sita.
			if (!excluded && sp != null && p.minutes_source && p.minutes_override_reason) {
				noteBits.push(p.minutes_override_reason);
			}

			const method = await sharePlayerCard({
				name: p.web_name,
				tag: p.pos,
				team: p.team_short,
				teamName: p.team ?? p.team_short,
				meta: metaBits.join(' · '),
				// "Available" olisi kohinaa - status vain kun on kerrottavaa.
				statusLine:
					st !== 'a'
						? `FPL: ${STATUS_LABEL[st] ?? st.toUpperCase()}${
								p.chance_next != null ? `, ${p.chance_next}% chance of playing` : ''
							}`
						: undefined,
				// Karkiluku EI poissuljetulle: se olisi mallin luku tilanteesta jota
				// malli ei projisoi (sama peruste kuin kortin oma "left out on purpose").
				hero:
					sp != null && !excluded
						? { value: `${sp}%`, label: 'chance of starting the next gameweek' }
						: undefined,
				modelLine:
					premium && !excluded && typeof p.xp_horizon_total === 'number'
						? `${p.xp_horizon_total.toFixed(1)} xP projected over the next ${
								(p.gameweeks ?? []).length
							} gameweeks`
						: undefined,
				production:
					cells.length > 0
						? {
								title: `Last season ${lastSeasonLabel}${
									lastSeasonLeague ? `, ${lastSeasonLeague}` : ''
								}`,
								cells,
								totals: totalsLine || undefined
							}
						: undefined,
				defconLine: dcLine,
				note: noteBits.join(' · ') || undefined,
				fileName: `goaliq_${p.web_name.toLowerCase().replace(/[^a-z0-9]+/g, '_')}.png`
			});
			if (method !== 'aborted') {
				capture('xp_card_shared', { list: 'player_card', method, premium });
			}
		} finally {
			sharing = false;
		}
	}
</script>

<h2>Player card</h2>
<p class="muted">
	Free · Look up any covered player: the official FPL availability news side by side with
	the GoalIQ model's view on starting and projected points. Official data comes straight
	from the FPL API and refreshes with the daily projection build.
</p>

{#if poolError}
	<p class="banner error">Could not load the player pool right now. Please try again shortly.</p>
{:else}
	<PlayerSearch id="pc-search" label="Find a player" bind:query items={matches} onSelect={select} />

	{#if player}
		<article class="pc card">
			<header class="pc-head">
				<div class="pc-name-row">
					<h3 class="pc-name">{player.web_name}</h3>
					<!-- 4.8: jaettava kortti. Nakyy myos freelle, ks. share()-kommentti. -->
					<button type="button" class="share-btn" onclick={share} disabled={sharing}>
						{sharing ? 'Rendering…' : canShareToApps() ? 'Share as image' : 'Download image'}
					</button>
				</div>
				<p class="muted pc-sub">
					{#if player.full_name && player.full_name !== player.web_name}{player.full_name}
						·{/if}
					{player.team} · {player.pos}{#if typeof player.price === 'number' && player.price > 0}
						· {player.price.toFixed(1)}m{/if}{#if typeof player.owned_pct === 'number'}
						· owned by {player.owned_pct.toFixed(1)}%{/if}
				</p>
			</header>

			<div class="pc-grid">
				<section class="pc-block">
					<h4>Official FPL status <span class="src">source: FPL</span></h4>
					<p class="status-line">
						<span class="chip {statusTone}">{STATUS_LABEL[st] ?? st.toUpperCase()}</span>
						{#if player.chance_next != null && st !== 'a'}
							<span>{player.chance_next}% chance of playing the next round</span>
						{/if}
					</p>
					{#if player.news}
						<p class="news">{player.news}</p>
					{:else if st === 'a'}
						<p class="muted">No flags right now.</p>
					{/if}
					{#if typeof player.yellows === 'number'}
						{#if preseason}
							<p class="muted">
								{player.yellows} yellow {player.yellows === 1 ? 'card' : 'cards'} last season
								(FPL data). Booking counts reset for the new season.
							</p>
						{:else}
							<p class="muted">
								{player.yellows}
								{player.yellows === 1 ? 'yellow' : 'yellows'}, {suspensionLine(player.yellows)}.
							</p>
						{/if}
					{/if}
					{#if player.set_pieces}
						{#if spListed}
							<p class="muted sp-line">Set pieces: <SetPieceBadges sp={player.set_pieces} /></p>
						{:else}
							<p class="muted">No penalty, corner or free-kick duties in FPL's lists.</p>
						{/if}
					{/if}
				</section>

				<section class="pc-block model">
					<h4>GoalIQ model view <span class="src">estimate, not team news</span></h4>
					{#if excluded}
						<p class="excluded-note">
							Not in the projections right now{#if exclusionReason}:
								{exclusionReason}{/if}.
						</p>
						<p class="muted">
							Projected points are left out on purpose. They would not say anything useful
							until this player is back in contention, so the card stays with the official
							status above.
						</p>
					{:else}
						{#if typeof player.p_start === 'number'}
							<p class="start-line">
								<span class="brand big">{Math.round(player.p_start * 100)}%</span>
								chance of starting the next gameweek{#if player.minutes_confidence}
									<span class="muted">({player.minutes_confidence} confidence)</span>{/if}
							</p>
						{:else if typeof player.predicted_starts === 'number'}
							<p class="start-line">
								<span class="brand big">{Math.round(player.predicted_starts)}%</span>
								chance of starting the next gameweek{#if player.minutes_confidence}
									<span class="muted">({player.minutes_confidence} confidence)</span>{/if}
							</p>
						{/if}
						{#if player.data_basis}
							<p class="muted">
								The model's view on starting, {DATA_BASIS_LABEL[player.data_basis] ??
									player.data_basis}.
							</p>
						{/if}
						<!-- 4.8: aloitus-tn:n LÄHDE kun se ei ole puhtaasti mallin laskema.
						     Payload on tuonut `override`-arvon 27.7. lähtien, mutta mikään
						     pinta ei näyttänyt sitä: Isakin käsin nostettu 0.30 -> 0.85 on
						     ollut käyttäjälle näkymätön. Ohitustiedosto sanoo näyttämisen
						     ei-neuvoteltavaksi, joten tämä ei ole uusi sääntö vaan
						     toteuttamatta jäänyt. -->
						{#if player.minutes_source && player.minutes_override_reason}
							<p class="muted">
								{MINUTES_SOURCE_LABEL[player.minutes_source] ?? 'Adjusted'}:
								{player.minutes_override_reason}.
							</p>
						{/if}
						<!-- 16.8: minuuttipriori nojaa katkenneeseen kauteen. Villen
						     havainto: Arsenalin ennustetussa XI:ssä ei ole Ødegaardia.
						     Mitattu korrelaatio(viime kauden avaukset / 38, p_start) =
						     0,785 (n=285), eli priori ei kysy MIKSI minuutit puuttuivat.
						     EI suuntaväitettä: katkennut kausi voi tarkoittaa
						     loukkaantunutta tähteä tai pelaajaa joka ei kelvannut, eikä
						     minuuttiluku erota niitä. Sama rajaus kuin team_flagilla. -->
						{#if player.minutes_basis_flag === 'short_season'}
							<p class="muted">
								He played {player.last_season?.minutes} minutes last season, so this
								estimate rests on a short spell rather than a full one. That does not
								say which way it is off.
							</p>
						{/if}
						{#if premium}
							{@const tot = player.xp_horizon_total}
							{@const per = player.xp_per_gw}
							{#if typeof tot === 'number' && typeof per === 'number'}
								<p>
									<strong>{tot.toFixed(1)} xP</strong> projected over the next
									{(player.gameweeks ?? []).length} gameweeks ({per.toFixed(1)} per GW).
								</p>
							{/if}
							{#if goalOutlook}
								<p>
									<strong>{goalOutlook.eg.toFixed(2)} goals</strong> expected in
									GW{goalOutlook.gw}, a {goalOutlook.pct}% chance of scoring.
								</p>
							{/if}
						{:else}
							<p class="muted">
								Projected points for this player are part of GoalIQ Premium. The start
								chance and official status here are free.
							</p>
						{/if}
					{/if}
				</section>
			</div>

			{#if showLastSeason}
				<!-- FREE: historia on julkista dataa (FPL + julkaistut xG/xA-summat),
				     ei premium-gatea. Puuttuvat kentät jätetään pois kokonaan —
				     ei koskaan "undefined"/"NaN". -->
				<section class="last-season">
					<h4 class="gw-title">
						Last season {lastSeasonLabel}
						<span class="src"
							>{#if lastSeasonLeague}{lastSeasonLeague}, {/if}public history, not a projection</span
						>
					</h4>
					{#if lsTotals.length > 0}
						<dl class="stat-row">
							{#each lsTotals as c (c.key)}
								<div class="stat">
									<dt>{c.label}</dt>
									<dd>{c.value}</dd>
								</div>
							{/each}
						</dl>
					{/if}
					{#if lsPer90.length > 0}
						<p class="muted p90-label">
						Per 90 minutes{#if per90Computed}
							<span class="src">worked out from the totals above</span>{/if}
					</p>
						<dl class="stat-row p90">
							{#each lsPer90 as c (c.key)}
								<div class="stat">
									<dt>{c.label}</dt>
									<dd>{c.value}</dd>
								</div>
							{/each}
						</dl>
					{/if}
				</section>
			{/if}

			{#if premium && !excluded}
			{@const gws = player.gameweeks ?? []}
			<h4 class="gw-title">Projected points by gameweek</h4>
			<div class="table-wrap">
				<table>
					<thead>
						<tr>
							<th>GW</th>
							<th>Fixture</th>
							<th class="num"><abbr title="Expected points from the GoalIQ match model">xP</abbr></th>
						</tr>
					</thead>
					<tbody>
						{#each player.gameweeks as g (g.gw)}
							<tr>
								<td>GW{g.gw}</td>
								<td class:muted={g.opponents.length === 0}>{fixtureLabel(g.opponents)}</td>
								<td class="num">{g.xp.toFixed(2)}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
			{/if}
			{#if defconLoading}
				<p class="muted">Loading defensive contribution log...</p>
			{:else if defcon && defcon.games.length > 0}
				<h4 class="gw-title">
					Defensive contribution (DefCon)
					<span class="src">source: FPL</span>
				</h4>
				<p class="muted dc-sub">
					{defcon.totals.hits} of {defcon.totals.games} games over the
					{defcon.meta.threshold} action mark ({defcon.totals.hit_rate_pct}% hit rate,
					{defcon.totals.defcon_points} FPL points), {defcon.totals.dc_per_game} actions per game.
					{#if defcon.meta.is_prev_season_basis && defcon.meta.basis_label}
						{defcon.meta.basis_label}.
					{/if}
				</p>
				{#if defcon.meta.components_available}
					<p class="muted dc-sub">
						Per game: {defcon.totals.cbi_per_game} clearances, blocks and interceptions,
						{defcon.totals.tkl_per_game} tackles{#if defcon.meta.counts_recoveries},
							{defcon.totals.rec_per_game} recoveries{/if}.
						{#if !defcon.meta.counts_recoveries}Recoveries do not count for defenders.{/if}
					</p>
				{/if}
				<div class="table-wrap">
					<table>
						<thead>
							<tr>
								<th>GW</th>
								<th>Fixture</th>
								<th class="num"><abbr title="Clearances, blocks and interceptions">CBI</abbr></th>
								<th class="num"><abbr title="Tackles">Tkl</abbr></th>
								<th class="num"><abbr title="Ball recoveries">Rec</abbr></th>
								<th class="num"><abbr title="Defensive contribution total">DC</abbr></th>
							</tr>
						</thead>
						<!-- Each-avain indeksillä, EI kierroksella: tupla-GW:ssä (esim. Senesin
						     DGW33 25/26) round toistuu ja each_key_duplicate kaatoi DefCon-osion
						     pysyvään "Loading..."-tilaan (löydetty 1.8). -->
						<tbody>
							{#each defcon.games as g, i (i)}
								<tr class:dc-hit={g.hit}>
									<td>GW{g.round}</td>
									<td>{g.opp} ({g.venue})</td>
									<td class="num">{g.cbi ?? '-'}</td>
									<td class="num">{g.tkl ?? '-'}</td>
									<td class="num">{g.rec ?? '-'}</td>
									<td class="num dc-total">{g.dc}{#if g.hit} ✓{/if}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
				<p class="muted dc-sub">{defcon.meta.rule_note}</p>
			{/if}

			<p class="muted disclaimer">
				Official status and news are FPL's own data. Starting chance and xP are GoalIQ model
				projections, for fun and planning, not betting advice.
			</p>
		</article>
	{/if}
{/if}

<style>
	.pc {
		max-width: 760px;
		margin-top: var(--s-4);
	}
	.pc-head {
		margin-bottom: var(--s-4);
	}
	.pc-name-row {
		display: flex;
		align-items: baseline;
		justify-content: space-between;
		gap: var(--s-2);
		flex-wrap: wrap;
	}
	.pc-name {
		margin: 0 0 var(--s-1);
		font-size: var(--step-2);
	}
	/* Sama chip-kieli kuin Leadersin/Valuen jakonapissa */
	.share-btn {
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
	.share-btn:disabled {
		opacity: 0.6;
		cursor: default;
	}
	.pc-sub {
		margin: 0;
	}
	.pc-grid {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
		gap: var(--s-4);
		margin-bottom: var(--s-4);
	}
	/* Fakta vs estimaatti: virallinen blokki neutraalilla paper-pohjalla,
	   malliblokki magenta-aksentilla — sama data ei sekoitu. */
	.pc-block {
		border: 1px solid var(--border);
		border-radius: var(--radius);
		background: var(--surface-2);
		padding: var(--s-3) var(--s-4);
	}
	.pc-block.model {
		background: var(--surface);
		border-left: 4px solid var(--giq-rust);
	}
	.pc-block h4 {
		margin: 0 0 var(--s-2);
		font-size: var(--step--1);
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.4px;
	}
	.pc-block h4 .src {
		text-transform: none;
		letter-spacing: 0;
		font-weight: 500;
		color: var(--text-muted);
	}
	.status-line {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--s-2);
	}
	.chip {
		display: inline-block;
		padding: 2px 10px;
		border-radius: var(--radius);
		font-size: var(--step--1);
		font-weight: 700;
		border: 1px solid transparent;
	}
	.chip.ok {
		background: rgba(25, 227, 210, 0.14);
		border-color: rgba(46, 214, 194, 0.45);
		color: var(--giq-ink);
	}
	.chip.warn {
		background: rgba(255, 201, 60, 0.2);
		border-color: rgba(244, 168, 0, 0.5);
		color: var(--giq-ink);
	}
	.chip.out {
		background: rgba(255, 138, 92, 0.12);
		border-color: rgba(194, 65, 12, 0.4);
		color: var(--negative);
	}
	.news {
		font-weight: 600;
	}
	.sp-line {
		display: flex;
		align-items: center;
		gap: 2px;
	}
	.start-line .big {
		font-size: var(--step-2);
		font-weight: 700;
		color: var(--giq-rust);
		font-variant-numeric: tabular-nums;
		margin-right: 4px;
	}
	.dc-sub {
		font-size: var(--step--1);
		margin: 0 0 var(--s-2);
	}
	.dc-hit .dc-total {
		font-weight: 700;
		color: var(--giq-teal-deep, var(--text));
	}
	.gw-title {
		margin: 0 0 var(--s-2);
		font-size: var(--step--1);
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.4px;
	}
	.gw-title .src {
		text-transform: none;
		letter-spacing: 0;
		font-weight: 500;
		color: var(--text-muted);
	}
	.excluded-note {
		font-weight: 700;
		color: var(--negative);
		margin: 0 0 var(--s-2);
	}
	/* Viime kausi: sama laatikkokieli kuin pc-blockissa, mutta koko leveydeltä. */
	.last-season {
		border-top: 1px solid var(--border);
		padding-top: var(--s-4);
		margin-bottom: var(--s-4);
	}
	.stat-row {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(88px, 1fr));
		gap: var(--s-2);
		margin: 0 0 var(--s-3);
	}
	.stat {
		background: var(--surface-2);
		border: 1px solid var(--border);
		border-radius: var(--radius);
		padding: var(--s-2) var(--s-3);
	}
	.stat dt {
		font-size: var(--step--1);
		color: var(--text-muted);
		margin: 0 0 2px;
	}
	/* Isot luvut = display-fontti (theme.css-sääntö), leipäteksti ei. */
	.stat dd {
		margin: 0;
		font-family: var(--font-display);
		font-size: var(--step-1);
		font-weight: 700;
		font-variant-numeric: tabular-nums;
		line-height: 1.1;
	}
	.stat-row.p90 .stat dd {
		font-size: var(--step-0);
	}
	.p90-label {
		margin: 0 0 var(--s-2);
		font-weight: 600;
	}
	.p90-label .src {
		font-weight: 500;
		margin-left: var(--s-1);
	}
	.disclaimer {
		margin: var(--s-3) 0 0;
	}
</style>
