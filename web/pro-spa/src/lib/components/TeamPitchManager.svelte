<script lang="ts">
	/**
	 * TeamPitchManager (#113) — web-pariteetti mobiilin #106-pitchille +
	 * #112-managerille: XI tintattuina kitteinä positiorivein + penkki,
	 * ja premiumille READ-ONLY what-if-editointi (formation-vaihto,
	 * penkki↔XI-vaihdot, kapteeni/vara, LIVE GW-xP kapteeni ×2, optimal).
	 * Sama /api/fantasy-data (RatedPlayer[]), sama free/premium-gate kuin
	 * mobiilissa (perus-pitch free, editointi premium, source fantasy_manager).
	 * Pitch-tausta = teal-tint (#108-paletti, ei uutta nurmiväriä).
	 */
	import { capture } from '$lib/analytics';
	import type { RatedPlayer } from '$lib/fantasyTools';
	import { teamColorByShort } from '$lib/teamColors';
	import { canShareToApps, sharePitchCard, type PitchCardPlayer } from '$lib/shareCard';
	import TeamKit from './TeamKit.svelte';

	let {
		players,
		premium = false,
		defaultGw = null,
		onUpgrade,
		initialCaptaincy,
		onCaptaincyChange
	}: {
		players: RatedPlayer[];
		premium?: boolean;
		/** #123: aloitus-GW (rate-teamin meta.gw eli seuraava deadline). */
		defaultGw?: number | null;
		onUpgrade?: () => void;
		/** 29.7 (kapteeni/vice-persistointi, skeema 20260729233000): tallennettu
		 *  pari. Ylikirjoittaa players.is_captain-fallbackin — käyttäjän tuorein
		 *  oma valinta voittaa FPL:n viimeksi julkaiseman. */
		initialCaptaincy?: { captain_id: number | null; vice_id: number | null };
		/** Kutsutaan kun kapteeni TAI vice vaihtuu — parent persistoi draftiin. */
		onCaptaincyChange?: (captainId: number | null, viceId: number | null) => void;
	} = $props();

	/** Validit FPL-muodostelmat [DEF, MID, FWD] (GK aina 1, yht. 11). */
	const FORMATIONS: readonly (readonly [number, number, number])[] = [
		[3, 4, 3],
		[3, 5, 2],
		[4, 4, 2],
		[4, 3, 3],
		[4, 5, 1],
		[5, 4, 1],
		[5, 3, 2]
	];
	const POS_ORDER = ['GKP', 'DEF', 'MID', 'FWD'] as const;

	/* 14.8 (Villen palaute: "pitchia vois tehda isommaksi"): kentta on
	   GRAAFIIKKAA eika tekstia, joten viereisilta tekstikorteilta peritty
	   680px:n lukumitta ei koske sita. Leveilla ruuduilla koko kentta
	   skaalataan SUHTEESSA — pelkka leveyden kasvatus olisi litistanyt sen,
	   koska korkeus tulee sisallosta eika kuvasuhteesta.
	   Paidan koko on komponentin propi eika CSS:aa, joten se on pakko
	   johtaa ikkunan leveydesta taalla; media query ei ylla siihen. */
	let winW = $state(0);
	const kitSize = $derived(winW >= 1040 ? 58 : 44);
	let xiIds = $state<number[]>([]);
	let captainId = $state<number | null>(null);
	let viceId = $state<number | null>(null);
	let selectedId = $state<number | null>(null);
	let selGw = $state<number | null>(null);

	// #121: transfer-apply vaihtaa rosterissa yhden pelaajan → sovita what-if-
	// tila swap-diffistä (XI/kapteeni/vara seuraavat). Täysi reset vain kun
	// kyseessä on kokonaan uusi rate-ajo.
	let prevIds: Set<number> = new Set();
	$effect(() => {
		const cur = new Set(players.map((p) => p.id));
		const removed = [...prevIds].filter((id) => !cur.has(id));
		const added = [...cur].filter((id) => !prevIds.has(id));
		const isSwap =
			removed.length === 1 && added.length === 1 && prevIds.size === cur.size;
		prevIds = cur;
		if (isSwap) {
			const [outId] = removed;
			const [inId] = added;
			xiIds = xiIds.map((id) => (id === outId ? inId : id));
			if (captainId === outId) captainId = inId;
			if (viceId === outId) viceId = inId;
			selectedId = null;
			return;
		}
		xiIds = players.filter((p) => p.in_xi).map((p) => p.id);
		// 29.7: reset palauttaa TALLENNETUN kapteeniparin kun se on rosterissa —
		// muuten jokainen uusi rate-ajo pyyhkisi käyttäjän oman valinnan.
		const savedCap = initialCaptaincy?.captain_id;
		const savedVice = initialCaptaincy?.vice_id;
		captainId =
			savedCap != null && cur.has(savedCap)
				? savedCap
				: (players.find((p) => p.is_captain)?.id ?? null);
		viceId = savedVice != null && cur.has(savedVice) && savedVice !== captainId ? savedVice : null;
		selectedId = null;
	});

	// Persistointi: raportoi kapteeniparin muutokset parentille. Ensimmäinen
	// ajo (mount/reset-alustus) ohitetaan — pelkkä lataus ei saa kirjoittaa.
	let capInitialized = false;
	$effect(() => {
		void captainId;
		void viceId;
		if (!capInitialized) {
			capInitialized = true;
			return;
		}
		onCaptaincyChange?.(captainId, viceId);
	});

	// #123: GW-valitsin — GW:t datasta (vain kun backend lähettää gameweeks).
	const gwsAvailable = $derived.by(() => {
		const s = new Set<number>();
		for (const p of players) for (const g of p.gameweeks ?? []) s.add(g.gw);
		return Array.from(s).sort((a, b) => a - b);
	});
	$effect(() => {
		if (gwsAvailable.length === 0) {
			selGw = null;
			return;
		}
		if (selGw != null && gwsAvailable.includes(selGw)) return;
		selGw =
			defaultGw != null && gwsAvailable.includes(defaultGw)
				? defaultGw
				: gwsAvailable[0];
	});

	// #122: valitun GW:n xP — SAMA GW-kohtainen luku kuin summaryn team_xp_gw
	// (ei enää horisonttikeskiarvo-vs-GW-ristiriitaa). Fallback vanhalla API:lla.
	function xpOf(p: RatedPlayer): number {
		if (selGw != null && p.gameweeks && p.gameweeks.length > 0) {
			const g = p.gameweeks.find((x) => x.gw === selGw);
			return g ? g.xp : 0;
		}
		return p.xp_per_gw;
	}

	/** #123: valitun GW:n vastustaja(t): "HUL (A)", DGW molemmat, blank → "No game". */
	function oppOf(p: RatedPlayer): string | null {
		if (selGw == null || !p.gameweeks || p.gameweeks.length === 0) return null;
		const g = p.gameweeks.find((x) => x.gw === selGw);
		if (!g || g.opponents.length === 0) return 'No game';
		return g.opponents.map((o) => `${o.opp} (${o.venue})`).join(' + ');
	}

	// Free näkee staattisen pitchin + lukon → paywall_shown kerran (#85-oppi).
	$effect(() => {
		if (!premium && players.length > 0) {
			capture('paywall_shown', { source: 'fantasy_manager' }, 'paywall_shown_fantasy_manager');
		}
	});

	const byId = $derived(new Map(players.map((p) => [p.id, p])));
	const xi = $derived(
		xiIds.map((id) => byId.get(id)).filter((p): p is RatedPlayer => !!p)
	);
	const bench = $derived(players.filter((p) => !xiIds.includes(p.id)));
	const rows = $derived(
		POS_ORDER.map((pos) => xi.filter((p) => p.pos === pos)).filter((r) => r.length > 0)
	);
	const counts = $derived.by(() => {
		const c: Record<string, number> = { GKP: 0, DEF: 0, MID: 0, FWD: 0 };
		for (const p of xi) c[p.pos] = (c[p.pos] ?? 0) + 1;
		return c;
	});
	const effCaptain = $derived(
		captainId != null && xiIds.includes(captainId) ? captainId : null
	);
	const effVice = $derived(
		viceId != null && xiIds.includes(viceId) && viceId !== effCaptain ? viceId : null
	);
	const gwXp = $derived(
		xi.reduce((s, p) => s + xpOf(p), 0) +
			(effCaptain != null ? xpOf(byId.get(effCaptain)!) : 0)
	);
	// #122: lataus-tilan (importattu XI + kapteeni) xP samalle GW:lle →
	// user-editin ero näytetään eksplisiittisenä labelina, ei äänettömänä.
	const baselineXp = $derived.by(() => {
		const base = players.filter((p) => p.in_xi);
		const cap = players.find((p) => p.is_captain);
		return base.reduce((s, p) => s + xpOf(p), 0) + (cap ? xpOf(cap) : 0);
	});
	const editDelta = $derived(gwXp - baselineXp);
	const selectedInXi = $derived(selectedId != null && xiIds.includes(selectedId));

	/** FPL-säännöt: 11 pelaajaa, 1 MV, DEF 3–5, MID 2–5, FWD 1–3. */
	function isValidXi(xs: RatedPlayer[]): boolean {
		if (xs.length !== 11) return false;
		const c: Record<string, number> = { GKP: 0, DEF: 0, MID: 0, FWD: 0 };
		for (const p of xs) c[p.pos] = (c[p.pos] ?? 0) + 1;
		return (
			c.GKP === 1 && c.DEF >= 3 && c.DEF <= 5 && c.MID >= 2 && c.MID <= 5 && c.FWD >= 1 && c.FWD <= 3
		);
	}

	function bestXiForFormation(f: readonly [number, number, number]): number[] | null {
		const pick = (pos: string, n: number) => {
			const xs = players
				.filter((p) => p.pos === pos)
				.sort((a, b) => xpOf(b) - xpOf(a))
				.slice(0, n);
			return xs.length === n ? xs : null;
		};
		const gk = pick('GKP', 1);
		const d = pick('DEF', f[0]);
		const m = pick('MID', f[1]);
		const fw = pick('FWD', f[2]);
		if (!gk || !d || !m || !fw) return null;
		return [...gk, ...d, ...m, ...fw].map((p) => p.id);
	}

	/** XI:stä poistuva kapteeni → vara perii → muuten korkein xP. */
	function fixLeadership(nextXi: number[]) {
		let c = captainId != null && nextXi.includes(captainId) ? captainId : null;
		let v = viceId != null && nextXi.includes(viceId) ? viceId : null;
		if (c == null) {
			c =
				v ??
				nextXi
					.map((id) => byId.get(id)!)
					.sort((a, b) => xpOf(b) - xpOf(a))[0]?.id ??
				null;
		}
		if (v === c) v = null;
		captainId = c;
		viceId = v;
	}

	function trySwap(aId: number, bId: number): boolean {
		const inA = xiIds.includes(aId);
		const inB = xiIds.includes(bId);
		if (inA === inB) return false;
		const leaving = inA ? aId : bId;
		const entering = inA ? bId : aId;
		const next = xiIds.map((id) => (id === leaving ? entering : id));
		const nextPlayers = next.map((id) => byId.get(id)).filter((p): p is RatedPlayer => !!p);
		if (!isValidXi(nextPlayers)) return false;
		xiIds = next;
		fixLeadership(next);
		return true;
	}

	function onPlayerClick(id: number) {
		if (!premium) return;
		if (selectedId == null) {
			selectedId = id;
			return;
		}
		if (selectedId === id) {
			selectedId = null;
			return;
		}
		if (trySwap(selectedId, id)) selectedId = null;
		else selectedId = id;
	}

	function applyFormation(f: readonly [number, number, number]) {
		const ids = bestXiForFormation(f);
		if (!ids) return;
		xiIds = ids;
		fixLeadership(ids);
		selectedId = null;
	}

	function applyOptimal() {
		let best: { ids: number[]; xp: number } | null = null;
		for (const f of FORMATIONS) {
			const ids = bestXiForFormation(f);
			if (!ids) continue;
			const ps = ids.map((id) => byId.get(id)!);
			const cap = Math.max(...ps.map((p) => xpOf(p)));
			const xp = ps.reduce((s, p) => s + xpOf(p), 0) + cap;
			if (!best || xp > best.xp) best = { ids, xp };
		}
		if (!best) return;
		xiIds = best.ids;
		const top = best.ids
			.map((id) => byId.get(id)!)
			.sort((a, b) => xpOf(b) - xpOf(a))[0];
		captainId = top?.id ?? null;
		viceId = null;
		selectedId = null;
	}

	function unlock() {
		capture('upgrade_tapped', { source: 'fantasy_manager' });
		onUpgrade?.();
	}

	// #9a jatko (31.7, Villen pyyntö): jaettava pitch-kortti — XI + penkki,
	// sama teletext-kehys kuin listakorteissa. Kattaa SEKÄ draft-raten ETTÄ
	// entry-ID-raten (molemmat renderöivät tämän komponentin). Premium-gate:
	// kortin luvut ovat mallin xP:tä.
	let sharing = $state(false);
	function toCardPlayer(p: RatedPlayer): PitchCardPlayer {
		const tc = teamColorByShort(p.team_short);
		return {
			name: p.web_name,
			team: p.team_short,
			color: tc.color,
			textColor: tc.textColor,
			xp: xpOf(p).toFixed(1),
			badge: effCaptain === p.id ? 'C' : effVice === p.id ? 'V' : undefined
		};
	}
	async function shareImage() {
		if (sharing) return;
		sharing = true;
		try {
			const method = await sharePitchCard({
				title: selGw != null ? `GAMEWEEK ${selGw} XI` : 'MY FPL XI',
				subtitle: `projected ${gwXp.toFixed(1)} points, captain doubled, GoalIQ model`,
				unitNote: 'xP under each name',
				fileName: selGw != null ? `goaliq_xi_gw${selGw}.png` : 'goaliq_xi.png',
				rows: rows.map((row) => row.map(toCardPlayer)),
				bench: bench.map(toCardPlayer)
			});
			if (method !== 'aborted') capture('xp_card_shared', { list: 'pitch', method });
		} finally {
			sharing = false;
		}
	}
</script>

<svelte:window bind:innerWidth={winW} />

{#if players.length > 0}
	<!--
	🔴 SAATAVUUS KENTALLE (15.8, Villen tilaus pitch-nakyman parantamisesta).
	Aiemmin epavarma pelaaja nayttti kentalla TASAN samalta kuin terve, vaikka
	juuri se on syy avata naytto deadlinen alla. Luku oli projektiossa jo,
	mutta se ei kulkenut rate-teamin riveille.

	null = FPL ei ole liputtanut. Se EI ole sama kuin "100 % varma", ja siksi
	lippu naytetaan vain kun luku on olemassa ja alle 100.
-->
<div class="pitch-block">
		{#if premium}
			{#if gwsAvailable.length > 1}
				<p class="label">Gameweek</p>
				<div class="chips">
					{#each gwsAvailable as gw (gw)}
						<button
							type="button"
							class="chip"
							class:on={selGw === gw}
							onclick={() => (selGw = gw)}
						>
							GW{gw}
						</button>
					{/each}
				</div>
			{/if}

			<p class="label">Formation</p>
			<div class="chips">
				{#each FORMATIONS as f (f.join('-'))}
					<button
						type="button"
						class="chip"
						class:on={counts.DEF === f[0] && counts.MID === f[1] && counts.FWD === f[2]}
						onclick={() => applyFormation(f)}
					>
						{f.join('-')}
					</button>
				{/each}
				<button type="button" class="chip" onclick={applyOptimal}>Optimal lineup</button>
			</div>
			<div class="xp-row">
				<span class="label" style="margin:0"
					>Projected {selGw != null ? `GW${selGw}` : 'GW'} xP
					<span class="muted">(captain doubled)</span></span
				>
				<span class="xp-col">
					<span class="xp-val">{gwXp.toFixed(1)}</span>
					{#if Math.abs(editDelta) >= 0.05}
						<span class="xp-delta"
							>{editDelta > 0 ? '+' : ''}{editDelta.toFixed(1)} xP vs your loaded lineup</span
						>
					{/if}
				</span>
			</div>
		{/if}

		<div class="xi-head">
			<p class="label" style="margin:0">Starting XI</p>
			{#if premium}
				<!-- #9a: pitch-kortti (XI + penkki) — sama kortti draftille ja ID-ratelle -->
				<button type="button" class="chip" onclick={shareImage} disabled={sharing}>
					{sharing ? 'Rendering…' : canShareToApps() ? 'Share as image' : 'Download image'}
				</button>
			{/if}
		</div>
		<!-- 14.8 (Villen palaute "täyttää toi enemmän dashboard maiseksi"):
		     penkki kentan VIEREEN eika alle leveilla ruuduilla. Kentta jatti
		     oikealle tyhjan kaistan ja penkki oli neljan paidan rivi jonka
		     alla sivu jatkui — nyt se tayttaa kaistan ja sivu lyhenee.
		     Kapealla ruudulla penkki palaa kentan alle kuten ennen. -->
		<div class="pitch-row" class:has-bench={bench.length > 0}>
		<div class="pitch">
			<!-- 31.7 (Villen palaute "saataisko kentästä parempi" + tarkennus):
			     PUOLIKAS kenttä kuten OfficialFPL/FFScout — maali+boksit ylhäällä,
			     alareuna = keskiviiva keskiympyränkaarineen → FWD-rivi istuu
			     keskiviivan tuntumaan. Teal-token, ei uusia värejä (#108-kaanon).
			     preserveAspectRatio=none venyy pitchin mittoihin; non-scaling-stroke
			     pitää viivat ohuina venytyksestä riippumatta. -->
			<svg class="pitch-lines" viewBox="0 0 100 140" preserveAspectRatio="none" aria-hidden="true">
				<rect x="2.5" y="2.5" width="95" height="135" vector-effect="non-scaling-stroke" />
				<rect x="27" y="2.5" width="46" height="15" vector-effect="non-scaling-stroke" />
				<rect x="38.5" y="2.5" width="23" height="7" vector-effect="non-scaling-stroke" />
				<path d="M 42 17.5 A 9 9 0 0 1 58 17.5" vector-effect="non-scaling-stroke" />
				<path d="M 37 137.5 A 13 13 0 0 0 63 137.5" vector-effect="non-scaling-stroke" />
			</svg>
			{#each rows as row, i (i)}
				<div class="row">
					{#each row as p (p.id)}
						<button
							type="button"
							class="player"
							class:selected={premium && selectedId === p.id}
							disabled={!premium}
							onclick={() => onPlayerClick(p.id)}
						>
							<span class="kitwrap">
								<TeamKit
									{...teamColorByShort(p.team_short)}
									label={p.team_short}
									size={kitSize}
								/>
								{#if effCaptain === p.id}<span class="badge">C</span>{/if}
								{#if effCaptain !== p.id && effVice === p.id}<span class="badge vice">V</span>{/if}
							</span>
							<span class="pname">{p.web_name}</span>
							{#if typeof p.chance_next === 'number' && p.chance_next < 100}
								<span
									class="doubt"
									class:out={p.chance_next === 0}
									title={p.news ?? ''}
								>{p.chance_next === 0 ? 'OUT' : `${p.chance_next}%`}</span>
							{/if}
							<span class="pxp">{xpOf(p).toFixed(1)}</span>
							{#if oppOf(p)}
								<span class="popp">{oppOf(p)}</span>
							{/if}
						</button>
					{/each}
				</div>
			{/each}
		</div>

		{#if bench.length > 0}
			<div class="pitch-side">
			<p class="label bench-label">Bench</p>
			<div class="benchrow">
				{#each bench as p (p.id)}
					<button
						type="button"
						class="player compact"
						class:selected={premium && selectedId === p.id}
						disabled={!premium}
						onclick={() => onPlayerClick(p.id)}
					>
						<span class="kitwrap">
							<TeamKit {...teamColorByShort(p.team_short)} label={p.team_short} size={34} />
						</span>
						<span class="pname">{p.web_name}</span>
						<span class="pxp">{xpOf(p).toFixed(1)}</span>
					</button>
				{/each}
			</div>
			</div>
		{/if}
		</div>

		{#if premium}
			<p class="muted hint">
				{selectedId == null
					? 'Click a player to select them.'
					: 'Click another player to swap bench and XI, or use the buttons below.'}
			</p>
			{#if selectedInXi}
				<div class="actions">
					<button
						type="button"
						class="action"
						onclick={() => {
							captainId = selectedId;
							if (viceId === selectedId) viceId = null;
							selectedId = null;
						}}>Make captain</button
					>
					<button
						type="button"
						class="action"
						onclick={() => {
							if (captainId === selectedId) captainId = null;
							viceId = selectedId;
							selectedId = null;
						}}>Make vice</button
					>
				</div>
			{/if}
			<p class="muted hint">
				Plan your lineup here, then apply it in the official FPL app. GoalIQ never changes your
				real team.
			</p>
		{:else}
			<button type="button" class="lockrow" onclick={unlock}>
				<span aria-hidden="true">🔒</span>
				Lineup editing (formations, swaps, captain) is Premium
				<span class="cta">Unlock with Premium</span>
			</button>
		{/if}
	</div>
{/if}

<style>
	.pitch-block {
		max-width: 680px;
		margin-top: var(--s-4);
	}
	/* 14.8: koko kentta suuremmaksi leveilla ruuduilla. Skaalataan kaikki
	   mitat samassa suhteessa (leveys, paikan leveys, nimikentat,
	   nurmiraidat) — paidan koko tulee `kitSize`-propista yllä, koska se on
	   komponentin propi eika CSS. Pelkka `.pitch-block`in leventaminen olisi
	   litistanyt kentan: korkeus tulee sisallosta eika kuvasuhteesta. */
	.pitch-row {
		display: grid;
		gap: var(--s-3);
	}
	.bench-label {
		margin-top: var(--s-3);
	}
	@media (min-width: 1040px) {
		.pitch-block {
			max-width: 1040px;
		}
		/* Penkki kentan viereen. `minmax(0, ...)` kentalle, jotta paidat
		   eivat levita saraketta yli gridin. 210px riittaa kahdelle
		   paidalle rinnakkain -> 4 penkkilaista asettuu 2x2. */
		.pitch-row.has-bench {
			grid-template-columns: minmax(0, 1fr) 210px;
			align-items: start;
			gap: var(--s-5);
		}
		.pitch-row.has-bench .benchrow {
			flex-wrap: wrap;
			justify-content: flex-start;
			gap: var(--s-2);
		}
		.pitch-row.has-bench .bench-label {
			margin-top: 0;
		}
		.player {
			width: 90px;
		}
		.pname,
		.popp {
			max-width: 88px;
		}
		.doubt {
		display: inline-block;
		margin: 1px 0 0;
		padding: 0 4px;
		font-size: 10px;
		font-weight: 700;
		letter-spacing: 0.04em;
		color: var(--ink);
		background: var(--amber);
		line-height: 1.5;
	}
	.doubt.out {
		background: var(--negative, #ff8a5c);
	}

	.pname {
			font-size: 11.5px;
		}
		.popp {
			font-size: 10px;
		}
		.pitch {
			background: repeating-linear-gradient(
				180deg,
				rgba(46, 214, 194, 0.2) 0 56px,
				rgba(46, 214, 194, 0.27) 56px 112px
			);
		}
	}
	.label {
		margin: 0 0 var(--s-1);
		font-size: var(--step--1);
		font-weight: 700;
		color: var(--text-muted);
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}
	.chips {
		display: flex;
		flex-wrap: wrap;
		gap: var(--s-2);
		margin-bottom: var(--s-3);
	}
	.chip {
		border: 1px solid var(--border);
		border-radius: var(--radius);
		background: var(--surface);
		color: var(--text-muted);
		font-weight: 700;
		font-size: var(--step--1);
		padding: 6px 12px;
		cursor: pointer;
	}
	.chip.on {
		background: transparent;
		border-color: var(--accent);
		color: var(--accent-strong);
	}
	.xp-row {
		display: flex;
		align-items: baseline;
		justify-content: space-between;
		gap: var(--s-3);
		background: var(--giq-paper);
		border-radius: var(--radius);
		padding: var(--s-2) var(--s-3);
		margin-bottom: var(--s-3);
	}
	.xp-val {
		color: var(--giq-rust);
		font-size: var(--step-2);
		font-weight: 800;
		font-variant-numeric: tabular-nums;
	}
	.xp-col {
		display: grid;
		justify-items: end;
	}
	/* #122: user-editin ero lataus-tilaan eksplisiittisenä */
	.xp-delta {
		color: var(--text-muted);
		font-size: 11px;
		font-variant-numeric: tabular-nums;
	}
	/* #123: GW:n vastustaja kitin alla */
	.popp {
		font-size: 9px;
		color: var(--text-muted);
		max-width: 66px;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	/* #9a: Starting XI -otsikko + share-nappi samalle riville */
	.xi-head {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--s-2);
		margin: 0 0 var(--s-1);
	}
	.chip:disabled {
		opacity: 0.6;
		cursor: default;
	}
	/* Pitch-tausta = teal-tint (#108: kanoninen token, ei uutta nurmiväriä) */
	.pitch {
		/* 28.7 (Villen havainto): 0.08 = kontrasti 1.067:1 cream-taustaan eli
		   kaytannossa nakymaton, ja kuvakaappauksessa/skaalauksessa se katoaa
		   kokonaan - jaljelle jaa vain 1 px:n reuna. Mitattu 0.24 = 1.215:1.
		   Sama arvo kaikilla kolmella pinnalla (SPA, mobiili, longtail).
		   31.7: + nurmiraidat (kaksi teal-alphaa) ja viivasto-SVG paalle. */
		position: relative;
		background: repeating-linear-gradient(
			180deg,
			rgba(46, 214, 194, 0.2) 0 44px,
			rgba(46, 214, 194, 0.27) 44px 88px
		);
		border: 1px solid var(--border);
		border-radius: var(--radius);
		padding: var(--s-2) var(--s-1);
		overflow: hidden;
	}
	.pitch-lines {
		position: absolute;
		inset: 0;
		width: 100%;
		height: 100%;
		fill: none;
		stroke: rgba(46, 214, 194, 0.45);
		stroke-width: 1.5;
		pointer-events: none;
	}
	.row {
		position: relative;
		display: flex;
		justify-content: space-evenly;
		margin: var(--s-2) 0;
	}
	.player {
		display: grid;
		justify-items: center;
		gap: 1px;
		width: 68px;
		background: none;
		border: 2px solid transparent;
		border-radius: var(--radius);
		padding: 2px;
		cursor: pointer;
		color: var(--text);
	}
	.player:disabled {
		cursor: default;
	}
	.player.selected {
		border-color: var(--accent);
	}
	.kitwrap {
		position: relative;
		display: inline-block;
	}
	/* 26.7 CLASSIC: kapteenimerkki on RENGAS, ei täyttö. Magenta on varattu
	   kolmeen työhön (mark, captain, live) ja aina outlinena — täytetty
	   pallo oli kentän ainoa magentaläikkä ja rikkoi ilmeen omaa sääntöä.
	   Tausta on paperi eikä läpinäkyvä, jotta rengas erottuu paidan päällä. */
	.badge {
		position: absolute;
		top: -3px;
		right: -5px;
		width: 15px;
		height: 15px;
		border-radius: var(--radius);
		background: var(--surface);
		border: 1.5px solid var(--accent);
		color: var(--giq-rust);
		font-size: 9px;
		font-weight: 800;
		display: flex;
		align-items: center;
		justify-content: center;
	}
	.badge.vice {
		border-color: var(--border);
		color: var(--text-muted);
	}
	.pname {
		font-size: 10px;
		font-weight: 600;
		max-width: 66px;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.pxp {
		font-size: 10px;
		color: var(--text-muted);
		font-variant-numeric: tabular-nums;
	}
	.benchrow {
		display: flex;
		flex-wrap: wrap;
		gap: var(--s-1);
	}
	.hint {
		margin: var(--s-2) 0 0;
		font-size: var(--step--1);
	}
	.actions {
		display: flex;
		gap: var(--s-2);
		margin-top: var(--s-2);
	}
	.action {
		background: var(--surface);
		border: 1px solid rgba(255, 138, 92, 0.35);
		border-radius: var(--radius);
		color: var(--accent);
		font-weight: 700;
		font-size: var(--step--1);
		padding: 8px 14px;
		cursor: pointer;
	}
	.lockrow {
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
	.cta {
		margin-left: auto;
		color: var(--positive);
		font-weight: 700;
	}
</style>
