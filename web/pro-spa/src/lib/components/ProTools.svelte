<script lang="ts">
	// #48: premium-FPL-työkalut segmenttidashboardina. Yksi työkaluryhmä
	// kerrallaan näkyvissä. Renderöidään VAIN gatatusta haarasta (ProView:
	// auth.user + auth.sub + xp) tai dev-esikatselusta (/dev-premium, DEV-only).
	import type { XpResponse } from '$lib/api';
	import Provenance from './Provenance.svelte';
	import SegmentNav, { type Segment } from './SegmentNav.svelte';
	import CaptainRanker from './CaptainRanker.svelte';
	import XpTable from './XpTable.svelte';
	import RateTeam from './RateTeam.svelte';
	import TransferPlanner from './TransferPlanner.svelte';
	import Differentials from './Differentials.svelte';
	import ComparePlayers from './ComparePlayers.svelte';

	let { xp }: { xp: XpResponse } = $props();

	const SEGMENTS: Segment[] = [
		{ id: 'players', label: 'Players' },
		{ id: 'myteam', label: 'My team' },
		{ id: 'differentials', label: 'Differentials' },
		{ id: 'compare', label: 'Compare' }
	];
	let segment = $state('players');
</script>

<!-- #50: mallin alkuperä-rivi myös pro-pinnalla (sama kiila kuin FreeView) -->
<Provenance />
<SegmentNav segments={SEGMENTS} bind:active={segment} label="Pro FPL tools" />

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
{:else if segment === 'differentials'}
	<div id="panel-differentials" role="tabpanel" aria-labelledby="seg-differentials">
		<section class="tool-card"><Differentials /></section>
	</div>
{:else}
	<div id="panel-compare" role="tabpanel" aria-labelledby="seg-compare">
		<section class="tool-card"><ComparePlayers {xp} /></section>
	</div>
{/if}
