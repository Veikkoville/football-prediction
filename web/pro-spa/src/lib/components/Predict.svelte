<script lang="ts">
	/**
	 * Ottelu-ennuste webiin (28.7).
	 *
	 * MIKSI: mitattu endpoint-kartta osoitti että /api/predict, /api/teams ja
	 * /api/leagues olivat mobiilissa mutta EIVÄT lainkaan webissä. Samaan aikaan
	 * goaliq.app:n 181 staattista ennustesivua ovat suurin indeksoitu pintamme,
	 * eikä niistä ollut mihinkään konvertoida: kävijä ei voinut valita kahta
	 * joukkuetta ja saada ennustetta. Landing ja JSON-LD myyvät tätä silti
	 * eksplisiittisesti. Backend oli valmis ja julkinen, joten kyse oli
	 * pelkästä UI-portista.
	 *
	 * FREE/PREMIUM-RAJAUS on kopioitu mobiilista tarkoituksella, ei valittu
	 * uudelleen: pariteetti on Villen sääntö, ja eri raja kahdella pinnalla on
	 * uusi vika eikä puolikas työ.
	 *   free    : 1X2 + todennäköisin tulos (top 5)
	 *   premium : xG, top 10, over/under 2.5, BTTS, mallin fair value
	 */
	import {
		fetchTeams,
		predictMatch,
		type PredictResponse
	} from '$lib/api';
	import { LEAGUES as SPA_LEAGUES } from '$lib/leagues';
	import { capture } from '$lib/analytics';

	let {
		premium = false,
		onUpgrade,
		prefill = null
	}: {
		premium?: boolean;
		onUpgrade?: () => void;
		/** Fixtures-näkymästä tuleva esitäyttö. Null = käyttäjä valitsee itse. */
		prefill?: { league: string; home: string; away: string } | null;
	} = $props();

	/** 28.7: KURATOITU lista. 8.8: siirretty $lib/leagues.ts:aan, koska
	 *  Fixtures ja Standings jaivat tata korjatessa /api/leagues:n varaan ja
	 *  tarjosivat liigoja joille otteluohjelmaa ei ole (Veikkausliiga) samalla
	 *  kun Brasileirao puuttui niista kokonaan. */
	const LEAGUES = SPA_LEAGUES;
	let league = $state('ENG-Premier League');
	let teams = $state<string[]>([]);
	let home = $state('');
	let away = $state('');

	let loading = $state(false);
	let error = $state<string | null>(null);
	let data = $state<PredictResponse | null>(null);

	// Vain LIPUTETUT näytetään (nousija / korkea vaihtuvuus). Pelkkä
	// vaihtuvuusluku kuuluu työkalutaulukoihin, ei jokaisen ennusteen alle:
	// 26/27 kukaan ei ylitä kynnystä, joten luku olisi tässä kohinaa.
	const confidenceNotes = $derived(
		Object.values(data?.data_confidence ?? {}).filter((c) => c?.flag && c?.note)
	);


	// Fixtures-näkymästä tuleva esitäyttö. Käsitellään ENNEN liigaefektiä ja
	// vasta joukkuelistan latauduttua: liigan vaihto tyhjentää valinnat, joten
	// naiivi "aseta kaikki kerralla" hävittäisi kotijoukkueen välittömästi.
	/** 28.7 (Villen havainto): otteluohjelman nimet ovat football-data.orgin
	 *  muodossa ("Brighton Hove", "Nottingham", "Man City") ja mallin lista on
	 *  omassaan ("Brighton", "Nottingham Forest", "Manchester City"). Tarkka
	 *  vertailu jatti kotijoukkueen tyhjaksi aina kun nimet erosivat.
	 *
	 *  Tavallisia funktioita tarkoituksella: ei $state, ei $derived, ei uusia
	 *  efekteja. Juuri uusi efekti rikkoi bind:valuen aiemmin tanaan. */
	function norm(s: string): string {
		return s
			.toLowerCase()
			.replace(/\b(fc|afc|cf|sc|ac|as|ss|us)\b/g, '')
			.replace(/[^a-z0-9]/g, '');
	}
	/** Nimet joita etuliitesaanto ei saa kiinni: lyhenne ei ole mallin nimen
	 *  etuliite eika painvastoin. Yleistetty samankaltaisuus sekoittaisi
	 *  Man Cityn ja Man Unitedin, joten nama kirjataan kasin. */
	const NAME_ALIASES: Record<string, string> = {
		mancity: 'manchestercity',
		manutd: 'manchesterunited',
		manunited: 'manchesterunited',
		spurs: 'tottenham'
	};
	function matchTeam(name: string, pool: string[]): string | null {
		if (pool.includes(name)) return name;
		let n = norm(name);
		n = NAME_ALIASES[n] ?? n;
		const exact = pool.find((x) => norm(x) === n);
		if (exact) return exact;
		// "Brighton Hove" -> "Brighton", "Nottingham" -> "Nottingham Forest".
		// Vain YKSIKASITTEINEN osuma kelpaa, muuten jatetaan tyhjaksi eika arvata.
		const partial = pool.filter((x) => n.startsWith(norm(x)) || norm(x).startsWith(n));
		return partial.length === 1 ? partial[0] : null;
	}

	let pending = $state<{ home: string; away: string } | null>(null);
	$effect(() => {
		if (!prefill) return;
		league = prefill.league;
		pending = { home: prefill.home, away: prefill.away };
	});

	// Liigan vaihto tyhjentää joukkuevalinnat: vanha valinta ei kuulu uuteen
	// liigaan, ja sen jättäminen näkyviin tuottaisi varman 404:n.
	// Juokseva pyyntonumero. TAVALLINEN muuttuja eika $state: tama on
	// kilpa-ajon esto, ei UI-tilaa, eika sen kuulu laukaista renderointia.
	let reqSeq = 0;
	let teamsLoading = $state(false);

	$effect(() => {
		const lg = league;
		const seq = ++reqSeq;
		teams = [];
		home = '';
		away = '';
		teamsLoading = true;
		fetchTeams(lg).then(
			(t) => {
				// Villen havainto "valilla vaarat joukkueet vaarassa liigassa":
				// hidas liiga ehtii vastata vasta kun kayttaja on jo vaihtanut.
				if (seq !== reqSeq) return;
				teamsLoading = false;
				teams = t.teams ?? [];
				if (pending) {
					// Nimet tulevat otteluohjelmasta (football-data.org) ja
					// joukkuelista mallista. Täsmäytetään vain jos nimi löytyy,
					// muuten jätetään käyttäjän valittavaksi eikä arvata.
					const h = matchTeam(pending.home, teams);
					const a = matchTeam(pending.away, teams);
					if (h) home = h;
					if (a) away = a;
					// Villen havainto: otteluohjelman Predict vei valilehdelle mutta
					// vaati viela napin painalluksen. Jos molemmat joukkueet
					// ratkesivat, ajetaan ennuste heti. Jos toinen jai auki (esim.
					// nousija jota ei viela ole mallissa), EI ajeta: silloin
					// kayttajan pitaa valita se itse.
					if (h && a && h !== a) void doPredict();
					pending = null;
				}
			},
			() => {
				if (seq !== reqSeq) return;
				teamsLoading = false;
				teams = [];
			}
		);
	});

	let canPredict = $derived(!!home && !!away && home !== away && !loading);

	async function run(e: SubmitEvent) {
		e.preventDefault();
		void doPredict();
	}

	async function doPredict() {
		if (!canPredict) return;
		loading = true;
		error = null;
		try {
			data = await predictMatch(league, home, away, premium ? 10 : 5);
			capture('predict_used', { league, premium });
		} catch (err) {
			data = null;
			error = err instanceof Error ? err.message : String(err);
		}
		loading = false;
	}

	function pct(v: number | undefined): string {
		return v == null ? '' : `${Math.round(v * 100)}%`;
	}

	function showPaywall() {
		capture('paywall_shown', { source: 'predict' }, 'paywall_shown_predict');
		onUpgrade?.();
	}
</script>

<h2>Predict any match</h2>
<p class="muted lede">
	The same model that powers our published, pre-match-logged predictions. Pick two teams and
	it returns win probability, expected goals and the most likely scorelines.
</p>

<form class="pick" onsubmit={run}>
	<div class="field">
		<label for="pred-league">League</label>
		<select id="pred-league" bind:value={league}>
			{#each LEAGUES as l (l.code)}
				<option value={l.code}>{l.label}</option>
			{/each}
		</select>
	</div>
	<div class="field">
		<label for="pred-home">Home team</label>
		<select id="pred-home" bind:value={home} disabled={teamsLoading || teams.length === 0}>
			<option value="">Select</option>
			{#each teams as t (t)}
				<option value={t}>{t}</option>
			{/each}
		</select>
	</div>
	<div class="field">
		<label for="pred-away">Away team</label>
		<select id="pred-away" bind:value={away} disabled={teamsLoading || teams.length === 0}>
			<option value="">Select</option>
			{#each teams as t (t)}
				<option value={t}>{t}</option>
			{/each}
		</select>
	</div>
	<button class="primary" type="submit" disabled={!canPredict}>
		{loading ? 'Predicting…' : 'Predict match'}
	</button>
</form>

{#if teamsLoading}
	<!-- Odotus oli aiemmin taysin hiljainen. Mitattu: liigan ensilataus vie
	     jopa 6 - 9 s, koska palvelin sovittaa mallin pyynnon yhteydessa. -->
	<p class="muted hint">Loading teams. The first time you open a league this can take a few seconds.</p>
{/if}

{#if home && away && home === away}
	<p class="muted hint">Home and away cannot be the same team.</p>
{/if}

{#if error}
	<p class="errorbox">{error}</p>
{/if}

{#if data && !loading}
	<section class="result">
		<h3>{data.home_team} vs {data.away_team}</h3>

		<!-- FREE: 1X2. Tämä on koko tuotteen ydinlupaus, joten se ei ole
		     paywallin takana kummallakaan pinnalla. -->
		<div class="outcome">
			<div class="oc">
				<span class="oc-label">{data.home_team}</span>
				<strong>{pct(data.p_home_win)}</strong>
			</div>
			<div class="oc">
				<span class="oc-label">Draw</span>
				<strong>{pct(data.p_draw)}</strong>
			</div>
			<div class="oc">
				<span class="oc-label">{data.away_team}</span>
				<strong>{pct(data.p_away_win)}</strong>
			</div>
		</div>
		<div class="bar" aria-hidden="true">
			<span class="seg seg-home" style="width:{data.p_home_win * 100}%"></span>
			<span class="seg seg-draw" style="width:{data.p_draw * 100}%"></span>
			<span class="seg seg-away" style="width:{data.p_away_win * 100}%"></span>
		</div>

		<!-- Luottamuslippu on VAPAAN puolella tarkoituksella: se kertoo milloin
		     luku on epävarmempi, eikä sellaista saa myydä erikseen. Sama
		     rajaus kuin ottelusivuilla goaliq.app:ssa. -->
		{#if confidenceNotes.length}
			<div class="conf">
				<strong>Lower confidence in this one.</strong>
				<ul>
					{#each confidenceNotes as c (c.team)}
						<li><strong>{c.team}</strong>: {c.note}</li>
					{/each}
				</ul>
				The model is fitted on results, so it prices a squad by what it did, not by who
				is in it now.
			</div>
		{/if}

		{#if premium}
			<div class="xg">
				<div><span class="k">Expected goals</span></div>
				<div class="xg-row">
					<span>{data.home_team}</span>
					<strong>{data.expected_goals_home.toFixed(2)}</strong>
				</div>
				<div class="xg-row">
					<span>{data.away_team}</span>
					<strong>{data.expected_goals_away.toFixed(2)}</strong>
				</div>
			</div>
		{/if}

		{#if premium}
			<h4>
				Most likely {data.top_scores.length === 1 ? 'scoreline' : 'scorelines'}
			</h4>
			<ul class="scores">
				{#each data.top_scores as s (s.score)}
					<li>
						<span class="sc">{s.score}</span>
						<span class="sp">{(s.probability * 100).toFixed(1)}%</span>
					</li>
				{/each}
			</ul>
		{/if}

		{#if premium}
			<div class="grid2">
				{#if data.p_over_2_5 != null}
					<div class="tile">
						<span class="k">Over 2.5 goals</span>
						<strong>{pct(data.p_over_2_5)}</strong>
					</div>
					<div class="tile">
						<span class="k">Under 2.5 goals</span>
						<strong>{pct(data.p_under_2_5)}</strong>
					</div>
				{/if}
				{#if data.p_btts_yes != null}
					<div class="tile">
						<span class="k">Both teams score</span>
						<strong>{pct(data.p_btts_yes)}</strong>
					</div>
					<div class="tile">
						<span class="k">Not both</span>
						<strong>{pct(data.p_btts_no)}</strong>
					</div>
				{/if}
			</div>
			{#if data.fair_odds_home != null}
				<p class="muted hint">
					Model fair value: {data.fair_odds_home.toFixed(2)} / {data.fair_odds_draw?.toFixed(
						2
					)} / {data.fair_odds_away?.toFixed(2)}. This is 1 divided by the model's
					probability, not a bookmaker line.
				</p>
			{/if}
		{:else}
			<!-- Paywall kertoo mitä puuttuu, ei piilota sitä että jotain puuttuu.
			     Sama rajaus kuin mobiilissa. -->
			<div class="locked">
				<strong>Free shows the win probabilities.</strong> Premium adds expected goals for
				both teams, the most likely scorelines, over/under 2.5, both teams to score, and
				the model's fair value.
				<button type="button" class="linklike" onclick={showPaywall}>See Premium</button>
			</div>
		{/if}

		<p class="disclaimer">
			Model prediction, not betting advice. Probabilities are estimates, not outcomes.
		</p>
	</section>
{/if}

<style>
	.lede {
		max-width: 62ch;
	}
	.pick {
		display: flex;
		flex-wrap: wrap;
		align-items: flex-end;
		gap: var(--s-3);
		margin: var(--s-5) 0 var(--s-3);
	}
	.field {
		display: flex;
		flex-direction: column;
		gap: 4px;
		min-width: 180px;
	}
	.field label {
		font-size: var(--step--1);
		color: var(--text-muted);
		font-weight: 700;
	}
	.field select {
		min-height: 44px;
		padding: 0 0.7em;
		border: 1px solid var(--border);
		border-radius: var(--radius);
		background: var(--surface);
		color: var(--text);
		font: inherit;
	}
	.hint {
		font-size: var(--step--1);
	}
	/* Sama muoto kuin errorbox mutta neutraali reunaväri: tämä ei ole virhe
	   eikä varoitus vaan tiedon rajaus. */
	.conf {
		border: 1px solid var(--border);
		border-left: 3px solid var(--accent, var(--border));
		border-radius: var(--radius);
		padding: var(--s-3) var(--s-4);
		max-width: 62ch;
		font-size: var(--step--1);
	}
	.conf ul {
		margin: var(--s-2) 0;
		padding-left: var(--s-4);
	}
	.errorbox {
		border: 1px solid var(--border);
		border-left: 3px solid var(--negative, var(--border));
		border-radius: var(--radius);
		padding: var(--s-3) var(--s-4);
		max-width: 62ch;
	}
	.result {
		margin-top: var(--s-5);
	}
	.outcome {
		display: flex;
		gap: var(--s-4);
		flex-wrap: wrap;
		margin-bottom: var(--s-2);
	}
	.oc {
		flex: 1 1 140px;
	}
	.oc-label {
		display: block;
		font-size: var(--step--1);
		color: var(--text-muted);
	}
	.oc strong {
		font-size: var(--step-3);
		font-variant-numeric: tabular-nums;
	}
	/* Kolme eri kirkkautta, ei kolmea eri sävyä: palkki luetaan myös
	   värisokeana ja mustavalkotulosteessa. */
	.bar {
		display: flex;
		height: 10px;
		border-radius: var(--radius);
		overflow: hidden;
		background: var(--surface);
		max-width: 620px;
	}
	.seg-home {
		background: var(--accent-strong, #8a6224);
	}
	.seg-draw {
		background: var(--text-muted);
		opacity: 0.55;
	}
	.seg-away {
		background: var(--text-muted);
		opacity: 0.25;
	}
	.xg {
		margin: var(--s-5) 0 var(--s-3);
		max-width: 380px;
	}
	.xg-row {
		display: flex;
		justify-content: space-between;
		padding: 4px 0;
		border-bottom: 1px solid var(--border);
		font-variant-numeric: tabular-nums;
	}
	.k {
		font-size: var(--step--1);
		color: var(--text-muted);
		font-weight: 700;
	}
	.scores {
		list-style: none;
		padding: 0;
		margin: var(--s-2) 0 var(--s-4);
		max-width: 380px;
	}
	.scores li {
		display: flex;
		justify-content: space-between;
		padding: 5px 0;
		border-bottom: 1px solid var(--border);
		font-variant-numeric: tabular-nums;
	}
	.sc {
		font-weight: 700;
	}
	.grid2 {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
		gap: var(--s-3);
		max-width: 620px;
		margin-bottom: var(--s-3);
	}
	.tile {
		border: 1px solid var(--border);
		border-radius: var(--radius);
		padding: var(--s-3);
	}
	.tile strong {
		display: block;
		font-size: var(--step-1);
		font-variant-numeric: tabular-nums;
	}
	.locked {
		border: 1px solid var(--border);
		border-left: 3px solid var(--accent, var(--border));
		border-radius: var(--radius);
		padding: var(--s-3) var(--s-4);
		max-width: 62ch;
		font-size: var(--step--1);
	}
	.disclaimer {
		color: var(--text-muted);
		font-size: var(--step--1);
		margin-top: var(--s-4);
	}
</style>
