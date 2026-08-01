<script lang="ts">
	/**
	 * FixtureSwing (30.7, Villen GO) — missä fixturet OIKEASTI liikuttavat
	 * pisteitä. DefCon-rehellisyysnoten vastinpari: sama malli joka mittasi
	 * ettei vastustaja siirrä DefConia (~2%) näyttää tässä missä vastustaja
	 * siirtää xP:tä (maalit, syötöt, bonus ja clean sheet skaalautuvat).
	 *
	 * Laskenta kokonaan klientissä /api/fantasy/xp:n gameweeks-riveistä —
	 * ei uutta endpointtia. FPL näyttää FDR-värin; tämä näyttää montako
	 * pistettä väri on arvoltaan.
	 */
	import { type XpResponse, type XpPlayer } from '$lib/api';
	import { capture } from '$lib/analytics';

	let { data = null }: { data?: XpResponse | null } = $props();

	const TOP_N = 15;
	// Penkkiläisen "swing" on kohinaa: vaaditaan aito minuuttiodote.
	const MIN_XMINS = 45;

	type SwingRow = {
		p: XpPlayer;
		min: { xp: number; label: string };
		max: { xp: number; label: string };
		swing: number;
		ratio: number;
	};

	function gwLabel(g: { opponents: { opp: string; venue: string }[] }): string {
		if (!g.opponents.length) return 'Blank';
		return g.opponents.map((o) => `${o.venue === 'H' ? 'vs' : 'at'} ${o.opp}`).join(', ');
	}

	const rows = $derived.by<SwingRow[]>(() => {
		const out: SwingRow[] = [];
		for (const p of data?.players ?? []) {
			const gws = (p.gameweeks ?? []).filter((g) => g.opponents.length > 0);
			if (gws.length < 2 || (p.xmins ?? 0) < MIN_XMINS) continue;
			let lo = gws[0];
			let hi = gws[0];
			for (const g of gws) {
				if (g.xp < lo.xp) lo = g;
				if (g.xp > hi.xp) hi = g;
			}
			if (hi.xp <= 0) continue;
			out.push({
				p,
				min: { xp: lo.xp, label: `GW${lo.gw} ${gwLabel(lo)}` },
				max: { xp: hi.xp, label: `GW${hi.gw} ${gwLabel(hi)}` },
				swing: hi.xp - lo.xp,
				ratio: lo.xp > 0 ? hi.xp / lo.xp : Infinity
			});
		}
		out.sort((a, b) => b.swing - a.swing);
		return out.slice(0, TOP_N);
	});

	let viewedFired = false;
	$effect(() => {
		if (rows.length > 0 && !viewedFired) {
			viewedFired = true;
			capture('fixture_swing_viewed', { n: rows.length });
		}
	});

	// 30.7 (Villen havainto: "näyttää vain low ja high, ei mitään"): rivin
	// klikkaus avaa koko per-GW-stripin — sama data josta low/high lasketaan,
	// joten käyttäjä näkee MISTÄ swing tulee (ei vain ääripäitä). Sama
	// expand-kaava kuin DefCon-matriisissa.
	let expandedId = $state<number | null>(null);
	function toggleRow(id: number) {
		if (expandedId === id) {
			expandedId = null;
			return;
		}
		expandedId = id;
		capture('fixture_swing_expanded', { player_id: id });
	}
</script>

<section class="swing">
	<h3>Fixture swing</h3>
	<p class="muted">
		Where fixtures actually move points: the same player's projected xP at his best and worst
		opponent over the next six gameweeks. Goals, assists, bonus and clean sheets scale with the
		opponent. DefCon does not (about 2% in 25/26 data), which is why it is not in this list.
	</p>
	{#if rows.length === 0}
		<p class="muted">No projection data yet.</p>
	{:else}
		<div class="table-wrap">
			<table>
				<thead>
					<tr>
						<th>Player</th>
						<th class="num">Low</th>
						<th class="num">High</th>
						<th class="num"><abbr title="High xP divided by low xP">Swing</abbr></th>
					</tr>
				</thead>
				<tbody>
					{#each rows as r (r.p.id)}
						<tr class:expanded={expandedId === r.p.id}>
							<td>
								<button
									type="button"
									class="row-toggle"
									aria-expanded={expandedId === r.p.id}
									onclick={() => toggleRow(r.p.id)}
								>
									<span class="name">{r.p.web_name}</span>
									<span class="muted meta">{r.p.team_short} · {r.p.pos}</span>
									<span class="chev" aria-hidden="true"
										>{expandedId === r.p.id ? '▾' : '▸'}</span
									>
								</button>
							</td>
							<td class="num">
								{r.min.xp.toFixed(1)}
								<span class="muted meta">{r.min.label}</span>
							</td>
							<td class="num hi">
								{r.max.xp.toFixed(1)}
								<span class="muted meta">{r.max.label}</span>
							</td>
							<td class="num strong">
								{r.ratio === Infinity ? '∞' : `${r.ratio.toFixed(1)}x`}
							</td>
						</tr>
						{#if expandedId === r.p.id}
							<!-- Per-GW-strippi: paras korostettuna, pahin himmennettynä.
							     Sama data josta low/high poimittiin — ei uutta hakua. -->
							<tr class="gw-row">
								<td colspan="4">
									<div class="gw-strip" role="list">
										{#each (r.p.gameweeks ?? []).filter((g) => g.opponents.length > 0) as g (g.gw)}
											<span
												role="listitem"
												class="gw-chip"
												class:best={g.xp === r.max.xp}
												class:worst={g.xp === r.min.xp}
												title="GW{g.gw} {gwLabel(g)}: {g.xp.toFixed(2)} xP"
											>
												<span class="gw-n">GW{g.gw}</span>
												<span class="gw-opp">{gwLabel(g)}</span>
												<span class="gw-xp">{g.xp.toFixed(1)}</span>
											</span>
										{/each}
									</div>
								</td>
							</tr>
						{/if}
					{/each}
				</tbody>
			</table>
		</div>
		<p class="muted foot">
			Projected xP per gameweek from the match model. Minimum {MIN_XMINS} expected minutes.
		</p>
	{/if}
</section>

<style>
	h3 {
		margin: 0 0 var(--s-1);
		font-size: var(--step-1);
	}
	.muted {
		color: var(--muted-fg, #8a847a);
	}
	.meta {
		display: block;
		font-size: var(--step--1);
	}
	.table-wrap {
		overflow-x: auto;
	}
	table {
		width: 100%;
		border-collapse: collapse;
	}
	th,
	td {
		text-align: left;
		padding: 6px 8px;
		border-bottom: 1px solid var(--border);
		vertical-align: top;
	}
	.num {
		text-align: right;
		font-variant-numeric: tabular-nums;
	}
	.hi {
		color: var(--teal, #2ed6c2);
	}
	.strong {
		font-weight: 700;
	}
	.foot {
		font-size: var(--step--1);
	}
	/* 30.7 expand: sama kieli kuin DefCon-matriisin stripissä */
	.row-toggle {
		display: flex;
		flex-wrap: wrap;
		align-items: baseline;
		gap: 4px 8px;
		background: none;
		border: none;
		padding: 0;
		font: inherit;
		color: inherit;
		cursor: pointer;
		text-align: left;
	}
	.chev {
		color: var(--muted-fg, #8a847a);
	}
	.gw-row td {
		background: rgba(243, 242, 242, 0.03);
	}
	.gw-strip {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
		padding: 4px 0;
	}
	.gw-chip {
		display: inline-flex;
		flex-direction: column;
		align-items: center;
		gap: 1px;
		border: 1px solid var(--border);
		border-radius: var(--radius);
		padding: 3px 7px;
		font-size: var(--step--1);
		font-variant-numeric: tabular-nums;
	}
	.gw-chip .gw-n {
		color: var(--muted-fg, #8a847a);
		font-size: 0.85em;
	}
	.gw-chip .gw-opp {
		color: var(--muted-fg, #8a847a);
		font-size: 0.85em;
		white-space: nowrap;
	}
	.gw-chip .gw-xp {
		font-weight: 700;
	}
	.gw-chip.best {
		border-color: var(--accent, #f5c542);
	}
	.gw-chip.best .gw-xp {
		color: var(--accent-strong, #f5c542);
	}
	.gw-chip.worst {
		opacity: 0.6;
	}
</style>
