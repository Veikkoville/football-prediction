<script lang="ts">
	// #48: premium-FPL-työkalut segmenttidashboardina. Yksi työkaluryhmä
	// kerrallaan näkyvissä. Renderöidään VAIN gatatusta haarasta (ProView:
	// auth.user + auth.sub + xp) tai dev-esikatselusta (/dev-premium, DEV-only).
	import type { XpResponse } from '$lib/api';
	import Provenance from './Provenance.svelte';
	import LeagueBanner from './LeagueBanner.svelte';
	import SegmentNav, { type Segment } from './SegmentNav.svelte';
	import CaptainRanker from './CaptainRanker.svelte';
	import XpTable from './XpTable.svelte';
	import RateTeam from './RateTeam.svelte';
	import TransferPlanner from './TransferPlanner.svelte';
	import Differentials from './Differentials.svelte';
	import ComparePlayers from './ComparePlayers.svelte';
	import Leaders from './Leaders.svelte';
	import Value from './Value.svelte';
	import ChipEv from './ChipEv.svelte';
	import PlanChains from './PlanChains.svelte';
	import PlayerCard from './PlayerCard.svelte';
	import EdgeMode from './EdgeMode.svelte';
	import Predict from './Predict.svelte';
	import Fixtures from './Fixtures.svelte';
	import Standings from './Standings.svelte';

	let { xp }: { xp: XpResponse } = $props();

	// 28.7: Fixtures-rivin "Predict" vie ennustenäkymään esitäytettynä (sama
	// kaava kuin free-puolella). Ilman tätä otteluohjelma olisi kalenteri.
	let predictPrefill = $state<{ league: string; home: string; away: string } | null>(null);
	function goPredict(lg: string, h: string, a: string) {
		predictPrefill = { league: lg, home: h, away: a };
		segment = 'predict';
	}

	// Edge-sprint: Chips (chip-EV), Chains (plan-chains) ja Edge (protect/climb)
	// ovat uusia premium-segmenttejä — renderöityvät VAIN tästä gatatusta
	// haarasta (ei premium-vuotoa).
	const SEGMENTS: Segment[] = [
		{ id: 'players', label: 'Players' },
		{ id: 'myteam', label: 'My team' },
		{ id: 'lookup', label: 'Player card' },
		{ id: 'chips', label: 'Chips' },
		{ id: 'chains', label: 'Chains' },
		{ id: 'edge', label: 'Edge' },
		{ id: 'value', label: 'Value' },
		{ id: 'leaders', label: 'Leaders' },
		{ id: 'differentials', label: 'Differentials' },
		{ id: 'compare', label: 'Compare' },
		// 28.7 pariteetti: samat kolme kuin free-puolella, mutta premium-rajaus
		// auki (xG, top 10 tulosta, over/under, BTTS, fair value, koko
		// otteluohjelma). Renderoidaan VAIN tasta gatatusta haarasta.
		{ id: 'predict', label: 'Predict a match' },
		{ id: 'fixtures', label: 'Fixtures' },
		{ id: 'standings', label: 'Table' }
	];
	let segment = $state('players');
</script>

<!-- #50: mallin alkuperä-rivi myös pro-pinnalla (sama kiila kuin FreeView) -->
<Provenance />
<!-- M29: Beat the Model -miniliigan liittymiskortti (julkinen koodi jgi6j9) -->
<LeagueBanner />
<SegmentNav segments={SEGMENTS} bind:active={segment} label="Premium FPL tools" />

{#if segment === 'players'}
	<div id="panel-players" role="tabpanel" aria-labelledby="seg-players">
		<section class="tool-card"><CaptainRanker data={xp} /></section>
		<section class="tool-card"><XpTable data={xp} /></section>
	</div>
{:else if segment === 'myteam'}
	<div id="panel-myteam" role="tabpanel" aria-labelledby="seg-myteam">
		<!-- #46: RateTeam premium={true} vain tilauksen takana → ei premium-vuotoa. -->
		<section class="tool-card"><RateTeam premium={true} /></section>
		<section class="tool-card"><TransferPlanner /></section>
	</div>
{:else if segment === 'lookup'}
	<div id="panel-lookup" role="tabpanel" aria-labelledby="seg-lookup">
		<section class="tool-card"><PlayerCard premium={true} /></section>
	</div>
{:else if segment === 'chips'}
	<!-- Edge-sprint kohta 6: chip-ajoituksen EV -->
	<div id="panel-chips" role="tabpanel" aria-labelledby="seg-chips">
		<section class="tool-card"><ChipEv /></section>
	</div>
{:else if segment === 'chains'}
	<!-- Edge-sprint kohta 7: plan-chains (solver-light) -->
	<div id="panel-chains" role="tabpanel" aria-labelledby="seg-chains">
		<section class="tool-card"><PlanChains /></section>
	</div>
{:else if segment === 'edge'}
	<!-- Edge-sprint kohta 8: rank-tietoinen protect/climb -->
	<div id="panel-edge" role="tabpanel" aria-labelledby="seg-edge">
		<section class="tool-card"><EdgeMode /></section>
	</div>
{:else if segment === 'value'}
	<!-- #127: value + GK-parit (premium-haara → koko listat, #114-web-pariteetti) -->
	<div id="panel-value" role="tabpanel" aria-labelledby="seg-value">
		<section class="tool-card"><Value premium={true} /></section>
	</div>
{:else if segment === 'leaders'}
	<!-- #124/#125: xG leaders + DefCon tracker (premium-haara → koko listat) -->
	<div id="panel-leaders" role="tabpanel" aria-labelledby="seg-leaders">
		<section class="tool-card"><Leaders premium={true} /></section>
	</div>
{:else if segment === 'differentials'}
	<div id="panel-differentials" role="tabpanel" aria-labelledby="seg-differentials">
		<section class="tool-card"><Differentials /></section>
	</div>
{:else if segment === 'compare'}
	<div id="panel-compare" role="tabpanel" aria-labelledby="seg-compare">
		<section class="tool-card"><ComparePlayers {xp} /></section>
	</div>
{:else if segment === 'predict'}
	<div id="panel-predict" role="tabpanel" aria-labelledby="seg-predict">
		<section class="tool-card">
			<Predict premium={true} prefill={predictPrefill} />
		</section>
	</div>
{:else if segment === 'fixtures'}
	<div id="panel-fixtures" role="tabpanel" aria-labelledby="seg-fixtures">
		<section class="tool-card">
			<Fixtures premium={true} onPredict={(l, h, a) => goPredict(l, h, a)} />
		</section>
	</div>
{:else}
	<div id="panel-standings" role="tabpanel" aria-labelledby="seg-standings">
		<section class="tool-card"><Standings /></section>
	</div>
{/if}
