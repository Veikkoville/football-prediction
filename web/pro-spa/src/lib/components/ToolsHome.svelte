<script lang="ts">
	/**
	 * ToolsHome — Web P1 (30.7, Villen GO "Web P1 go, matches omaan ryhmään").
	 *
	 * Korvaa FreeView + ProView + ProTools -kolmikon YHDELLÄ näkymällä:
	 * 6 sisältöryhmää, yksi segmenttinauha, gate LOHKON sisällä (sama malli
	 * kuin mobiilin Fantasy-tab). Vanha rakenne jakoi ylätabit ENTITLEMENTIN
	 * mukaan → 24 välilehtipositiota, 7 työkalua duplikoituna ja 4 työkalua
	 * jotka MAKSAVA käyttäjä menetti (clean sheets, fit checker, price watch,
	 * mini-league olivat vain free-nauhassa). Maksu ei saa koskaan kaventaa
	 * näkymää — nyt kaikki näkevät saman rakenteen ja premium avaa lohkoja.
	 *
	 * Upgrade-polku: teaserien onUpgrade avaa upgrade-näkymän (PremiumPreview
	 * + LoginBox kirjautumattomalle, Paywall kirjautuneelle ilman tilausta) —
	 * osto- ja checkout-paluulogiikka siirtyi ProView'sta tänne sellaisenaan.
	 */
	import { onMount } from 'svelte';
	import { auth, refreshSubscription, freePremiumWindowActive } from '$lib/auth.svelte';
	import { fetchXp, type XpResponse } from '$lib/api';
	import { capture } from '$lib/analytics';
	import DefConLive from './DefConLive.svelte';
	import Provenance from './Provenance.svelte';
	import LeagueBanner from './LeagueBanner.svelte';
	import SegmentNav, { type Segment } from './SegmentNav.svelte';
	import LoginBox from './LoginBox.svelte';
	import Paywall from './Paywall.svelte';
	import PremiumPreview from './PremiumPreview.svelte';
	import SetPassword from './SetPassword.svelte';
	import RateTeam from './RateTeam.svelte';
	import FitChecker from './FitChecker.svelte';
	import Watchlist from './Watchlist.svelte';
	import TransferPlanner from './TransferPlanner.svelte';
	import PlayerCard from './PlayerCard.svelte';
	import CaptainRanker from './CaptainRanker.svelte';
	import FixtureSwing from './FixtureSwing.svelte';
	import XpTable from './XpTable.svelte';
	import CleanSheets from './CleanSheets.svelte';
	import Value from './Value.svelte';
	import Leaders from './Leaders.svelte';
	import Differentials from './Differentials.svelte';
	import ComparePlayers from './ComparePlayers.svelte';
	import ChipEv from './ChipEv.svelte';
	import PlanChains from './PlanChains.svelte';
	import EdgeMode from './EdgeMode.svelte';
	import MiniLeague from './MiniLeague.svelte';
	import PriceWatch from './PriceWatch.svelte';
	import Predict from './Predict.svelte';
	import Fixtures from './Fixtures.svelte';
	import Standings from './Standings.svelte';

	let {
		forcePremium = false,
		upgradeSignal = 0
	}: {
		/** DEV-esikatselu (/dev-premium): premium-lohkot auki ilman gatea. */
		forcePremium?: boolean;
		/** Heron Upgrade-badge nostaa tätä → upgrade-näkymä auki. */
		upgradeSignal?: number;
	} = $props();

	const GROUPS: Segment[] = [
		{ id: 'week', label: 'This week' },
		{ id: 'team', label: 'My team' },
		{ id: 'players', label: 'Players' },
		{ id: 'tools', label: 'Tools' },
		{ id: 'prices', label: 'Prices' },
		{ id: 'matches', label: 'Matches' }
	];

	// Vanhat #tools=-deep-linkit (24 segmentti-id:tä) mappautuvat uusiin
	// ryhmiin — linkki ei saa hajota IA-muutokseen.
	const LEGACY_HASH: Record<string, string> = {
		cleansheets: 'players',
		playercard: 'players',
		lookup: 'players',
		rateteam: 'team',
		myteam: 'team',
		fitchecker: 'team',
		value: 'players',
		leaders: 'players',
		differentials: 'players',
		compare: 'players',
		pricewatch: 'prices',
		league: 'tools',
		chips: 'tools',
		chains: 'tools',
		edge: 'tools',
		predict: 'matches',
		fixtures: 'matches',
		standings: 'matches'
	};

	let segment = $state('week');
	/** 6.8: sticky-segmenttirivin mitattu korkeus → onpage-rivin top-offset. */
	let segNavH = $state(0);
	let upgradeOpen = $state(false);
	let checkoutSuccess = $state(false);
	let guestCheckout = $state(false);

	// Tools-hakemiston avattu työkalu (sama grid-kaava kuin mobiilin P1).
	type ToolKey = 'chips' | 'chains' | 'edge' | 'league';
	const TOOL_CARDS: { key: ToolKey; title: string; desc: string; premium: boolean }[] = [
		{
			key: 'chips',
			title: 'Chip timing',
			desc: 'The best windows for Wildcard, Bench Boost, Triple Captain and Free Hit, scored by expected points.',
			premium: true
		},
		{
			key: 'chains',
			title: 'Transfer chains',
			desc: 'One and two-move transfer plans with hits priced in, chained over the coming gameweeks.',
			premium: true
		},
		{
			key: 'edge',
			title: 'Edge mode',
			desc: 'Rank-aware picks: ownership-weighted captains, differentials you do not own and template risks.',
			premium: true
		},
		{
			key: 'league',
			title: 'Beat the Model league',
			desc: 'Join the public mini-league and track the standings with head-to-head win probabilities.',
			premium: false
		}
	];
	let openTool = $state<ToolKey | null>(null);

	// Matches-ryhmän sisäinen valinta (Villen valinta: oma ryhmä, ei gridiä).
	let matchesView = $state<'predict' | 'fixtures' | 'standings'>('predict');
	let predictPrefill = $state<{ league: string; home: string; away: string } | null>(null);
	function goPredict(lg: string, h: string, a: string) {
		predictPrefill = { league: lg, home: h, away: a };
		matchesView = 'predict';
	}

	const premium = $derived(forcePremium || !!auth.sub);
	/**
	 * 🔴 Villen havainto 16.8: "keep it after that -buttoni ei ohjaa mihinkään".
	 *
	 * `premium` avaa työkalut, ja ilmaisikkunan synteettinen tilaus tekee siitä
	 * toden. Upgrade-näkymä ei kuitenkaan saa käyttää samaa lippua: se sulkeutui
	 * heti auettuaan (efekti alla) eikä renderöitynyt koskaan, koska ikkunan
	 * käyttäjä lasketaan premiumiksi. Nappi nosti lipun ja efekti laski sen
	 * samassa hetkessä.
	 *
	 * Seuraus oli tulonmenetys eikä kosmeettinen vika: ikkuna piilottaa
	 * paywallin, joten tämä oli AINOA ostopolku ikkunan aikana. Kukaan ei ole
	 * voinut ostaa siitä hetkestä kun ikkuna avattiin.
	 */
	const paidPremium = $derived(
		forcePremium || (!!auth.sub && auth.sub.plan !== 'gw1-3-free')
	);

	/**
	 * Miksi nakyma avattiin. Ratkaisee saako se sulkeutua itsestaan.
	 *
	 * 🔴 Kaksi vaatimusta jotka ovat suoraan ristiriidassa, ja siksi pelkka
	 * lippu ei riita (mitattu: molemmat rikkoutuivat vuorollaan 16.8):
	 *   'gate' = kayttaja tormasi lukkoon -> kun oikeus aukeaa, nakyman ON
	 *            sulkeuduttava, muuten rekisteroitynyt jaa jumiin
	 *            upgrade-sivulle ja joutuu etsimaan "Back to the tools".
	 *   'keep' = kayttajalla ON jo oikeus ja han tuli ostamaan sen jatkoksi
	 *            ("Keep it after that") -> nakyma EI saa sulkeutua, muuten
	 *            nappi sulkee itsensa samassa hetkessa kun se aukeaa.
	 */
	let upgradeIntent = $state<'gate' | 'keep'>('gate');

	function openUpgrade(intent: 'gate' | 'keep') {
		upgradeIntent = intent;
		upgradeOpen = true;
		requestAnimationFrame(() => {
			document.querySelector('main')?.scrollIntoView({ behavior: 'smooth' });
		});
	}
	// 🔴 Nama kaksi eivat ota parametria. Ensimmainen versio oli
	// `goUpgrade(intent = 'gate')`, ja `onclick={goUpgrade}` syotti sille
	// MouseEventin: aie ei ollut kumpikaan arvo, joten sulkeva efekti ei
	// laukennut koskaan ja korjaus oli nakymaton. svelte-check nappasi sen
	// tyyppivirheena, mutta vika oli toiminnallinen.
	function goUpgrade() {
		openUpgrade('gate');
	}
	function goKeepPremium() {
		openUpgrade('keep');
	}

	// Hero-badge → upgrade-näkymä (signaali +page.sveltestä).
	let lastSignal = 0;
	$effect(() => {
		if (upgradeSignal > lastSignal) {
			lastSignal = upgradeSignal;
			goUpgrade();
		}
	});

	// Tilauksen aktivoituminen sulkee upgrade-näkymän itsestään.
	$effect(() => {
		// Oikeuden aukeaminen sulkee nakyman VAIN jos kayttaja tuli tanne
		// lukon takia. 'keep'-aikeella tullut on jo premium, ja sulkeminen
		// tappaisi juuri sen napin jota han painoi.
		if (upgradeOpen && upgradeIntent === 'gate' && premium) upgradeOpen = false;
		if (upgradeOpen && upgradeIntent === 'keep' && paidPremium) upgradeOpen = false;
	});

	onMount(() => {
		// Checkout-paluu (?checkout=success): fulfillment tapahtuu webhookissa —
		// täällä kuitataan + kysytään tilaustila uudelleen (webhook-viivettä
		// vastaan). Siirretty ProView'sta sellaisenaan.
		const params = new URLSearchParams(window.location.search);
		if (params.get('checkout') === 'success') {
			checkoutSuccess = true;
			guestCheckout = params.get('guest') === '1';
			const sid = params.get('session_id') ?? 'unknown';
			capture('purchase_completed', { source: 'web', guest: guestCheckout }, `purchase_${sid}`);
			history.replaceState(null, '', window.location.pathname);
			upgradeOpen = true;
			let tries = 0;
			const poll = () => {
				void refreshSubscription().then(() => {
					if (!auth.sub && ++tries < 5) setTimeout(poll, 3000);
				});
			};
			poll();
		}
		// #101: ?tab=premium avaa arvo-esikatselun + hinnat suoraan.
		const tab = params.get('tab');
		if (tab === 'premium' || tab === 'pro') upgradeOpen = true;
		// Vanhat deep-linkit uusiin ryhmiin (SegmentNav hoitaa uudet id:t).
		const m = window.location.hash.match(/^#tools=([\w-]+)$/);
		if (m && LEGACY_HASH[m[1]]) {
			segment = LEGACY_HASH[m[1]];
			if (m[1] === 'fixtures') matchesView = 'fixtures';
			if (m[1] === 'standings') matchesView = 'standings';
			if (m[1] === 'chips' || m[1] === 'chains' || m[1] === 'edge' || m[1] === 'league')
				openTool = m[1] as ToolKey;
		}
	});

	// xP-pooli premium-työkaluille. Haku lähtee heti session ratkettua
	// (rinnakkain tilaustarkistuksen kanssa, 26.7 PERF-oppi); free-käyttäjälle
	// 555 kB:n haku ei lähde lainkaan.
	let xp = $state<XpResponse | null>(null);
	let xpError = $state<string | null>(null);
	$effect(() => {
		if ((auth.user || forcePremium) && !xp && !xpError) {
			fetchXp().then(
				(d) => (xp = d),
				(e) => (xpError = String(e))
			);
		}
	});

	/** "On this page" -ankkurihyppy (Villen palaute 30.7: työkalut hukkuvat
	 *  pitkään scrolliin — sisällys näkyviin ryhmän kärkeen). */
	function jumpTo(id: string) {
		document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
	}

	function openToolCard(t: (typeof TOOL_CARDS)[number]) {
		if (t.premium && !premium) {
			capture('upgrade_tapped', { source: `fantasy_${t.key}` });
			goUpgrade();
			return;
		}
		openTool = t.key;
		capture('fantasy_tool_opened', { tool: t.key });
	}
</script>

{#if checkoutSuccess}
	{#if guestCheckout && !auth.user}
		<p class="banner success">
			Payment received. Premium is yours! We just emailed you a sign-in link (check spam
			too). Click it to open Premium here on the web; once signed in, you can set a password
			to use the same account in the GoalIQ app on iOS and Android.
		</p>
	{:else}
		<p class="banner success">
			Premium active, welcome aboard! Premium is now active on the web AND in the GoalIQ app
			(iOS and Android). Just sign in with the same account on your phone.
		</p>
	{/if}
{/if}

<!-- 🔴 IKKUNAILMOITUS LASKEUTUMISNAKYMAAN (16.8, portin loydos).
     Ilmoitus oli vain `PremiumPreview`-komponentissa, joka renderoityy
     VASTA kun `upgradeOpen` on tosi eli `?tab=premium`-parametrilla tai
     Upgrade-klikilla. Kirjautumaton kavija joka tuli suoraan
     pro.goaliq.appiin ei nahnyt ikkunasta mitaan - ja juuri se on se URL
     jonka annoimme luojille heidan ref-linkkiinsa. Heidan liikenteensa
     olisi laskeutunut sivulle joka ei kerro tarjouksesta.
     🔴 POISTA 12.9.2026 12:30 UTC jalkeen. -->
{#if freePremiumWindowActive() && !auth.user}
	<!-- 🔴 Villen havainto 16.8: "missa ohjeistus". Tama oli kappale jonka
	     sisassa sisaankaynti oli tekstilinkkina, eli sivun tarkein teko nakyi
	     samankokoisena kuin sen ymparilla oleva selitys. -->
	<div class="free-card">
		<h2>Premium is free until 12 September</h2>
		<p>
			That is GW1 to GW3. Create a free account and every Premium tool switches on straight
			away. No card, nothing to cancel, and nothing happens when the window closes unless you
			decide to keep it.
		</p>
		<button type="button" class="free-card-cta" onclick={goUpgrade}>
			Create a free account
		</button>
	</div>
{/if}

{#if upgradeOpen && !paidPremium}
	<!-- Upgrade-näkymä: ei enää oma ylätabi vaan päällekkäinen tila, josta
	     pääsee takaisin työkaluihin yhdellä klikillä. -->
	<button type="button" class="back-link" onclick={() => (upgradeOpen = false)}>
		‹ Back to the tools
	</button>
	{#if !auth.sessionResolved}
		<p class="muted">Checking session…</p>
	{:else if !auth.user}
		<!-- 🔴 Ikkunan aikana lomake ENNEN ominaisuuslistaa: teko ensin, myynti
		     perassa. Normaalisti jarjestys on oikein pain, koska silloin
		     kavijan pitaa vakuuttua ennen kuin tili on hanelle mitaan arvoinen
		     - ikkunan aikana tili on ilmainen eika vakuuttelua tarvita.
		     🔴 PALAUTA ALKUPERAINEN JARJESTYS 12.9.2026 12:30 UTC jalkeen. -->
		{#if freePremiumWindowActive()}
			<LoginBox />
			<PremiumPreview />
		{:else}
			<PremiumPreview />
			<LoginBox />
		{/if}
	{:else if auth.subLoading && auth.sub === undefined}
		<p class="muted">Checking subscription…</p>
	{:else}
		<Paywall />
	{/if}
{:else}
	{#if auth.sub}
		{#if auth.sub.plan === 'gw1-3-free'}
			<!-- 16.8: ilmainen ikkuna EI saa nayttaa ostetulta tilaukselta.
			     Vanha else-haara olisi sanonut "thank you for the support"
			     kayttajalle joka ei ole maksanut, ja tarjonnut SetPasswordin
			     jota ei ole ostettu. Ja koska ikkuna piilottaa paywallin,
			     ostopolun on oltava tassa - muuten kukaan ei voi ostaa
			     ikkunan aikana vaikka haluaisi. -->
			<p class="banner success">
				Premium is open to every account until the GW4 deadline on 12 September. Nothing to pay
				and nothing to cancel. <button type="button" class="linklike" onclick={goKeepPremium}
					>Keep it after that</button
				>
			</p>
		{:else if auth.sub.plan === 'app'}
			<p class="banner success">Your GoalIQ app subscription is active here too. Welcome.</p>
		{:else}
			<p class="muted">GoalIQ Premium active ({auth.sub.plan}) · thank you for the support!</p>
			<SetPassword />
		{/if}
	{/if}

	<Provenance />
	<LeagueBanner />
	<!-- 2.8: DefCon-live ylimpänä ja segmenttien ULKOPUOLELLA — se on
	     aikakriittinen eikä saa olla välilehden takana. Renderöi tyhjää aina
	     kun kierros ei ole käynnissä, joten esikaudella tämä ei näy. -->
	<DefConLive />
	<!-- 6.8 (Villen palaute): segmenttirivi kulkee scrollissa mukana —
	     Players → My team ilman paluuta ylös. Korkeus mitataan, jotta
	     onpage-rivi osaa asettua sen ALLE myös kun pillit rivittyvät. -->
	<div class="segnav-sticky" bind:clientHeight={segNavH}>
		<SegmentNav segments={GROUPS} bind:active={segment} label="GoalIQ FPL tools" />
	</div>

	{#if segment === 'week' || segment === 'team'}
		<!-- week + team jakavat SAMAN RateTeam-elementin (sama puupositio →
		     Svelte ei tuhoa instanssia vaihdossa → data/entry-tila säilyy). -->
		<div id="panel-{segment}" role="tabpanel" aria-labelledby="seg-{segment}">
			{#if segment === 'team'}
				<!-- 30.7 (Villen palaute: "fit checker yms hukkuu"): ryhmän
				     sisällys ankkuririvinä heti nauhan alle — pitkä scroll ei
				     saa piilottaa työkalun olemassaoloa. -->
				<div class="onpage" style="top: {segNavH}px">
					<span class="muted">On this page:</span>
					{#each [['tc-rate', 'Rate my team'], ['tc-fit', 'Fit checker'], ...(premium ? [['tc-planner', 'Transfer planner']] : []), ['tc-watchlist', 'Watchlist']] as [id, label] (id)}
						<button type="button" onclick={() => jumpTo(id)}>{label}</button>
					{/each}
				</div>
			{/if}
			<div class="tool-card" id="tc-rate">
				<RateTeam
					{premium}
					onUpgrade={goUpgrade}
					weekMode={segment === 'week'}
					onGoToTeam={() => (segment = 'team')}
				/>
			</div>
			{#if segment === 'team'}
				<!-- Järjestys 30.7: fit checker HETI raten alle (esikauden
				     sankarityökalu), watchlist viimeiseksi (pisin lista).
				     14.8 (Villen palaute: "ne ovat tossa allekain ns listana"):
				     sama järjestys, mutta kaksi saraketta leveillä ruuduilla.
				     Fit on yhä ensimmäinen; watchlist ei ole enää pitkän
				     vierityksen pohjalla vaan sen VIERESSÄ — 30.7:n peruste
				     ("pisin lista viimeiseksi") koski vierityksen pituutta,
				     eikä se päde kun se ei enää ole vierityksessä.
				     Planner saa koko leveyden: se sisältää taulukoita joita
				     puolikas sarake ei kanna. -->
				<div class="team-grid">
					<div class="tool-card" id="tc-fit">
						<FitChecker onOpenRateTeam={() => (segment = 'team')} />
					</div>
					<div class="tool-card" id="tc-watchlist"><Watchlist {premium} /></div>
					{#if premium}
						<div class="tool-card span-all" id="tc-planner"><TransferPlanner /></div>
					{/if}
				</div>
			{/if}
		</div>
	{:else if segment === 'players'}
		<div id="panel-players" role="tabpanel" aria-labelledby="seg-players">
			<div class="onpage" style="top: {segNavH}px">
				<span class="muted">On this page:</span>
				{#each [['pc-card', 'Player card'], ...(premium ? [['pc-captain', 'Captain ranker'], ['pc-swing', 'Fixture swing'], ['pc-xp', 'Player xP']] : []), ['pc-cs', 'Clean sheets'], ['pc-value', 'Value'], ['pc-leaders', 'Leaders'], ...(premium ? [['pc-diff', 'Differentials'], ['pc-compare', 'Compare']] : [])] as [id, label] (id)}
					<button type="button" onclick={() => jumpTo(id)}>{label}</button>
				{/each}
			</div>
			<div class="tool-card" id="pc-card"><PlayerCard {premium} /></div>
			{#if premium}
				{#if xpError}
					<p class="banner error">
						Could not load xP projections right now. Please try again shortly.
					</p>
				{:else if !xp}
					<p class="muted">Loading expected points…</p>
				{:else if !xp.meta?.available}
					<p class="banner success">xP projections go live before Gameweek 1.</p>
				{:else}
					<div class="tool-card" id="pc-captain"><CaptainRanker data={xp} /></div>
					<div class="tool-card" id="pc-swing"><FixtureSwing data={xp} /></div>
					<div class="tool-card" id="pc-xp"><XpTable data={xp} /></div>
				{/if}
			{:else}
				<!-- Sama .locked-kaava kuin Predict/Fixtures-lohkoissa. -->
				<div class="locked">
					<p>
						Player xP per gameweek, the captain ranker and fixture swing are part of GoalIQ
						Premium.
					</p>
					<button type="button" class="primary" onclick={goUpgrade}>See Premium</button>
				</div>
			{/if}
			<div id="pc-cs"><CleanSheets /></div>
			<div class="tool-card" id="pc-value"><Value {premium} onUpgrade={goUpgrade} /></div>
			<div class="tool-card" id="pc-leaders"><Leaders {premium} onUpgrade={goUpgrade} /></div>
			{#if premium}
				<div class="tool-card" id="pc-diff"><Differentials /></div>
				{#if xp}
					<div class="tool-card" id="pc-compare"><ComparePlayers {xp} /></div>
				{/if}
			{/if}
		</div>
	{:else if segment === 'tools'}
		<div id="panel-tools" role="tabpanel" aria-labelledby="seg-tools">
			{#if openTool === null}
				<!-- Hakemisto-grid: nimi + rivin kuvaus + premium-badge. Sama
				     kaava kuin mobiilin P1 Tools-segmentissä. -->
				<div class="tools-grid">
					{#each TOOL_CARDS as t (t.key)}
						<button type="button" class="tool-card-btn" onclick={() => openToolCard(t)}>
							<span class="tool-card-head">
								<span class="tool-card-title">{t.title}</span>
								{#if t.premium && !premium}<span class="tool-lock">Premium</span>{/if}
							</span>
							<span class="tool-card-desc muted">{t.desc}</span>
						</button>
					{/each}
				</div>
			{:else}
				<button type="button" class="back-link" onclick={() => (openTool = null)}>
					‹ All tools
				</button>
				{#if openTool === 'chips'}
					<div class="tool-card"><ChipEv /></div>
				{:else if openTool === 'chains'}
					<div class="tool-card"><PlanChains /></div>
				{:else if openTool === 'edge'}
					<div class="tool-card"><EdgeMode /></div>
				{:else}
					<div class="tool-card">
						<MiniLeague onUseTeam={() => (segment = 'team')} />
					</div>
				{/if}
			{/if}
		</div>
	{:else if segment === 'prices'}
		<div id="panel-prices" role="tabpanel" aria-labelledby="seg-prices">
			<div class="tool-card"><PriceWatch /></div>
		</div>
	{:else}
		<div id="panel-matches" role="tabpanel" aria-labelledby="seg-matches">
			<!-- Matches-alavalinta: kolme ottelutyökalua yhdessä ryhmässä
			     (Villen valinta: oma ryhmä). -->
			<div class="matches-nav" role="tablist" aria-label="Match tools">
				{#each [['predict', 'Predict a match'], ['fixtures', 'Fixtures'], ['standings', 'Table']] as [id, label] (id)}
					<button
						type="button"
						role="tab"
						aria-selected={matchesView === id}
						class:active={matchesView === id}
						onclick={() => (matchesView = id as typeof matchesView)}
					>
						{label}
					</button>
				{/each}
			</div>
			{#if matchesView === 'predict'}
				<div class="tool-card">
					<Predict {premium} onUpgrade={goUpgrade} prefill={predictPrefill} />
				</div>
			{:else if matchesView === 'fixtures'}
				<div class="tool-card">
					<Fixtures {premium} onUpgrade={goUpgrade} onPredict={(l, h, a) => goPredict(l, h, a)} />
				</div>
			{:else}
				<div class="tool-card"><Standings /></div>
			{/if}
		</div>
	{/if}
{/if}

<style>
	/* 🔴 POISTA 12.9.2026 12:30 UTC jalkeen yhdessa .free-card-lohkon kanssa. */
	.free-card {
		border: 2px solid var(--accent);
		border-radius: var(--radius);
		background: var(--surface);
		padding: var(--s-3);
		margin-bottom: var(--s-4);
	}
	.free-card h2 {
		margin: 0 0 var(--s-2);
		font-size: var(--step-2);
		line-height: 1.15;
	}
	.free-card p {
		margin: 0 0 var(--s-3);
		max-width: 60ch;
	}
	.free-card-cta {
		background: var(--accent);
		border: 2px solid var(--accent);
		border-radius: var(--radius);
		color: var(--surface);
		font: inherit;
		font-weight: 700;
		padding: 12px 22px;
		cursor: pointer;
	}
	.free-card-cta:hover {
		background: transparent;
		color: var(--accent);
	}
	.back-link {
		background: none;
		border: none;
		color: var(--text-muted);
		font: inherit;
		font-weight: 600;
		padding: var(--s-2) 0;
		cursor: pointer;
	}
	.back-link:hover {
		color: var(--text);
	}
	.tools-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(16rem, 1fr));
		gap: var(--s-3);
	}
	.tool-card-btn {
		display: flex;
		flex-direction: column;
		align-items: flex-start;
		gap: var(--s-1);
		text-align: left;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: var(--radius);
		padding: var(--s-4);
		font: inherit;
		color: var(--text);
		cursor: pointer;
	}
	.tool-card-btn:hover {
		border-color: var(--accent);
	}
	.tool-card-head {
		display: flex;
		align-items: center;
		gap: var(--s-2);
	}
	.tool-card-title {
		font-weight: 700;
	}
	.tool-lock {
		font-size: var(--step--1);
		color: var(--text-muted);
		border: 1px solid var(--border);
		border-radius: var(--radius);
		padding: 0 0.6em;
	}
	.tool-card-desc {
		font-size: var(--step--1);
	}
	.matches-nav {
		display: flex;
		flex-wrap: wrap;
		gap: var(--s-2);
		margin: 0 0 var(--s-4);
	}
	.matches-nav button {
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: var(--radius);
		color: var(--text-muted);
		font-size: var(--step--1);
		font-weight: 700;
		padding: 0.4em 1em;
		min-height: 40px;
	}
	.matches-nav button.active {
		background: transparent;
		border-color: var(--accent);
		color: var(--accent-strong);
	}
	.locked {
		border: 1px solid var(--border);
		border-radius: var(--radius);
		padding: var(--s-4);
		margin: var(--s-4) 0;
		background: var(--surface);
	}
	.locked p {
		margin: 0 0 var(--s-3);
	}
	/* 30.7: ryhmän sisällysrivi — kevyet tekstilinkit, ei kilpaile
	   segmenttinauhan pillien kanssa */
	.onpage {
		display: flex;
		flex-wrap: wrap;
		align-items: baseline;
		gap: var(--s-1) var(--s-3);
		font-size: var(--step--1);
		margin: 0 0 var(--s-3);
		/* 6.8 (Villen palaute, sama kuin mobiilissa): rivi pysyy näkyvissä
		   scrollatessa — työkalusta toiseen ilman paluuta ylös. top tulee
		   inline-tyylistä (mitattu segnav-korkeus → asettuu sen alle). */
		position: sticky;
		z-index: 10;
		background: var(--bg);
		padding: var(--s-2) 0;
		border-bottom: 1px solid var(--border);
	}
	/* 6.8: ylätabit mukaan scrolliin — Players → My team ilman paluuta ylös */
	/* 14.8: My teamin työkalut kahteen sarakkeeseen leveillä ruuduilla.
	   `minmax(0, 1fr)` on pakollinen — ilman sitä kortin sisällä oleva
	   taulukko levittäisi sarakkeen yli gridin. `.tool-card` tuo oman
	   `margin-bottom`insa, joten rivivälin hoitaa se eikä `row-gap`
	   (muuten väli olisi kaksinkertainen). */
	.team-grid {
		display: grid;
		gap: 0;
	}
	@media (min-width: 1100px) {
		.team-grid {
			grid-template-columns: repeat(2, minmax(0, 1fr));
			column-gap: var(--s-5);
			align-items: start;
		}
		.team-grid > :global(.span-all) {
			grid-column: 1 / -1;
		}
	}
	.segnav-sticky {
		position: sticky;
		top: 0;
		z-index: 20;
		background: var(--bg);
	}
	.onpage button {
		background: none;
		border: none;
		padding: 0;
		font: inherit;
		font-size: var(--step--1);
		color: var(--accent-strong);
		text-decoration: underline;
		text-underline-offset: 3px;
		cursor: pointer;
	}
	.onpage button:hover {
		color: var(--text);
	}
</style>
