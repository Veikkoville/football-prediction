<script lang="ts">
	import type { XpResponse } from '$lib/api';
	import { gwXp, gwOpponents } from '$lib/api';

	let { data }: { data: XpResponse } = $props();

	let nextGw = $derived(data.meta.next_gameweek);
	let top = $derived(
		[...data.players].sort((a, b) => gwXp(b, nextGw) - gwXp(a, nextGw)).slice(0, 10)
	);
</script>

<h2>Captain ranker: top xP for GW{nextGw}</h2>
<p class="muted">
	The ten highest projected scores for the next gameweek only — a captaincy shortlist.
	The full table below covers the whole horizon.
</p>
<div class="table-wrap">
	<table>
		<thead>
			<tr>
				<th class="num">#</th>
				<th>Player</th>
				<th>Team</th>
				<th>Pos</th>
				<th class="num">GW{nextGw} xP</th>
				<th>Opponent</th>
			</tr>
		</thead>
		<tbody>
			{#each top as p, i (p.id)}
				<tr>
					<td class="num">{i + 1}</td>
					<td>{p.web_name}</td>
					<td>{p.team_short}</td>
					<td>{p.pos}</td>
					<td class="num">{gwXp(p, nextGw).toFixed(2)}</td>
					<td>{gwOpponents(p, nextGw)}</td>
				</tr>
			{/each}
		</tbody>
	</table>
</div>
