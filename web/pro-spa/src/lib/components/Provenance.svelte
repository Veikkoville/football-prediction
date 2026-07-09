<script lang="ts">
	// #50: mallin alkuperä-rivi FPL-työkalualueen yläreunassa (free + pro).
	// Live track record /api/accuracy:sta jos kentät ovat saatavilla;
	// ilman niitä rivi renderöityy silti (defensiivinen, ei kaadu).
	import { fetchAccuracy, type AccuracyResponse } from '$lib/api';

	let acc = $state<AccuracyResponse | null>(null);

	$effect(() => {
		fetchAccuracy().then((a) => (acc = a));
	});

	let track = $derived.by(() => {
		const at = acc?.all_time;
		if (at?.n && at?.pct_1x2) return { n: at.n, pct: at.pct_1x2 * 100 };
		return null;
	});
</script>

<p class="provenance">
	Powered by the same match model behind our published, pre-match-logged
	predictions{#if track}: {track.pct.toFixed(0)}% correct
		<abbr title="Match result: home win, draw or away win">1X2</abbr> across
		{track.n} logged matches{/if}.
	<a href="https://goaliq.app/fpl.html#track-record">Track record</a>
</p>

<style>
	.provenance {
		font-size: var(--step--1);
		color: var(--text-muted);
		margin: var(--s-3) 0 0;
	}
</style>
