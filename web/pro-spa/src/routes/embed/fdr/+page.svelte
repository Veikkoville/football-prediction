<script lang="ts">
	/**
	 * /embed/fdr — upotettava CS%/FDR-widget (7.8, kasvutemppu 5).
	 *
	 * MIKSI: kukaan FPL-työkaluista ei tarjoa embed-widgettiä (tutkimus 7.8)
	 * — ilmainen upote FPL-blogeille = jakelu + "powered by GoalIQ" -backlink
	 * (SEO) nollakustannuksella. Jokainen upotus on mainos.
	 *
	 * KÄYTTÖ: <iframe src="https://pro.goaliq.app/embed/fdr?league=fpl&gws=6"
	 *          width="100%" height="480" frameborder="0"></iframe>
	 * Parametrit: league=fpl|spl (oletus fpl), gws=1..6 (oletus 6).
	 *
	 * Suora vierailu ilman iframe-kontekstia näyttää saman + upotusohjeen
	 * (sivu dokumentoi itsensä). Powered-by-linkki on osa tuotetta, ei
	 * poistettavissa parametrilla — se on koko jakelumekanismin pointti.
	 */
	import { page } from '$app/state';
	import {
		fetchFantasy,
		fetchSplFantasy,
		type FantasyResponse,
		type FantasyTeam
	} from '$lib/api';
	import { capture } from '$lib/analytics';

	let data = $state<FantasyResponse | null>(null);
	let error = $state<string | null>(null);

	let league = $derived(page.url.searchParams.get('league') === 'spl' ? 'spl' : 'fpl');
	let gws = $derived(
		Math.min(6, Math.max(1, Number(page.url.searchParams.get('gws')) || 6))
	);
	let embedded = $derived.by(() => {
		try {
			return window.self !== window.top;
		} catch {
			return true;
		}
	});

	$effect(() => {
		capture('embed_fdr_viewed', { league, embedded: String(embedded) });
		(league === 'spl' ? fetchSplFantasy() : fetchFantasy()).then(
			(d) => (data = d),
			(e) => (error = String(e))
		);
	});

	let nextGw = $derived((data?.meta?.next_gameweek as number) ?? 1);

	type Row = { t: FantasyTeam; avgCs: number | null; avgFdr: number };
	let rows = $derived.by<Row[]>(() => {
		const cut = nextGw + gws - 1;
		return (data?.teams ?? [])
			.map((t) => {
				const fx = t.fixtures.filter((f) => f.gw >= nextGw && f.gw <= cut);
				const cs = fx.map((f) => f.cs_pct).filter((v): v is number => typeof v === 'number');
				return {
					t,
					avgFdr: fx.length ? fx.reduce((s, f) => s + f.fdr, 0) / fx.length : 99,
					avgCs:
						cs.length === fx.length && fx.length
							? cs.reduce((s, v) => s + v, 0) / fx.length
							: null
				};
			})
			.sort((a, b) => (b.avgCs ?? -1) - (a.avgCs ?? -1));
	});

	function fdrClass(fdr: number): string {
		if (fdr <= 2) return 'is-easy';
		if (fdr >= 4) return 'is-hard';
		return '';
	}

	const embedSnippet = `<iframe src="https://pro.goaliq.app/embed/fdr?league=fpl&gws=6" width="100%" height="480" frameborder="0" title="GoalIQ fixture difficulty"></iframe>`;
</script>

<svelte:head>
	<title>GoalIQ FDR widget</title>
	<meta name="robots" content="noindex" />
</svelte:head>

<div class="widget">
	<p class="head">
		{league === 'spl' ? 'Saudi Pro League' : 'FPL'} clean sheet % + fixture difficulty, next {gws}
		GWs
	</p>
	{#if error}
		<p class="muted">Could not load data.</p>
	{:else if !data}
		<p class="muted">Loading…</p>
	{:else}
		<table>
			<thead>
				<tr><th>Team</th><th class="num">CS%</th><th class="num">FDR</th><th>Fixtures</th></tr>
			</thead>
			<tbody>
				{#each rows as { t, avgCs, avgFdr } (t.name)}
					<tr>
						<td>{t.name}</td>
						<td class="num">{avgCs == null ? '–' : avgCs.toFixed(0) + '%'}</td>
						<td class="num {fdrClass(avgFdr)}">{avgFdr === 99 ? '–' : avgFdr.toFixed(1)}</td>
						<td class="fx">
							{#each t.fixtures.filter((f) => f.gw >= nextGw && f.gw < nextGw + gws) as f (String(f.gw) + f.opponent_short)}
								<span class="chip {fdrClass(f.fdr)}">{f.opponent_short}{f.venue === 'H' ? '' : '*'}</span>
							{/each}
						</td>
					</tr>
				{/each}
			</tbody>
		</table>
		<p class="legend muted">* = away. Model-based FDR, 1 easy to 5 hard.</p>
	{/if}
	<p class="powered">
		<a
			href="https://pro.goaliq.app/{league === 'spl' ? 'spl' : ''}?src=embed"
			target="_blank"
			rel="noopener"
			onclick={() => capture('embed_fdr_clickthrough', { league })}
			>Powered by GoalIQ, the match model with a public track record</a
		>
	</p>

	{#if !embedded}
		<div class="docs">
			<p><strong>Embed this on your site, free:</strong></p>
			<pre>{embedSnippet}</pre>
			<p class="muted">
				Swap league=fpl for league=spl for the Saudi Pro League version. Data refreshes every
				few hours from the GoalIQ match model. The powered-by link stays; that is the deal.
			</p>
		</div>
	{/if}
</div>

<style>
	.widget {
		font-size: 13px;
		padding: 8px;
		max-width: 720px;
	}
	.head {
		font-weight: 700;
		margin: 0 0 6px;
	}
	table {
		border-collapse: collapse;
		width: 100%;
	}
	th,
	td {
		text-align: left;
		padding: 2px 6px;
		border-bottom: 1px solid var(--border);
		white-space: nowrap;
	}
	.num {
		text-align: right;
		font-variant-numeric: tabular-nums;
	}
	.fx {
		white-space: normal;
	}
	.chip {
		display: inline-block;
		border: 1px solid var(--border);
		border-radius: 2px;
		padding: 0 3px;
		margin: 1px;
		font-size: 11px;
	}
	.is-easy {
		color: var(--ok, #2e7d32);
	}
	.is-hard {
		color: var(--bad, #c62828);
	}
	.legend {
		margin: 6px 0 0;
		font-size: 11px;
	}
	.powered {
		margin: 8px 0 0;
		font-size: 12px;
	}
	.docs {
		margin-top: 16px;
		border-top: 1px solid var(--border);
		padding-top: 8px;
	}
	pre {
		overflow-x: auto;
		border: 1px solid var(--border);
		padding: 6px;
		font-size: 11px;
	}
</style>
