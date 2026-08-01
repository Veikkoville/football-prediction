<script lang="ts">
	// Edge-sprint: erikoistilanne-badget (P/C/FK) pelaajanimen perään.
	// Näytetään vain jos ottajajärjestys on 1 tai 2 (contract-data 1:
	// order = FPL bootstrapin lista, 1 = ykkösottaja; null = ei listalla).
	// Defensiivinen: kenttä puuttuu → ei renderöidä mitään.
	let {
		sp
	}: {
		sp?: { pens?: number | null; corners?: number | null; fk?: number | null };
	} = $props();

	const LABELS: Record<string, string> = {
		P: 'penalties',
		C: 'corners and indirect free kicks',
		FK: 'direct free kicks'
	};

	let badges = $derived.by(() => {
		if (!sp) return [] as { key: string; order: number }[];
		const out: { key: string; order: number }[] = [];
		if (typeof sp.pens === 'number' && sp.pens <= 2) out.push({ key: 'P', order: sp.pens });
		if (typeof sp.corners === 'number' && sp.corners <= 2)
			out.push({ key: 'C', order: sp.corners });
		if (typeof sp.fk === 'number' && sp.fk <= 2) out.push({ key: 'FK', order: sp.fk });
		return out;
	});
</script>

{#each badges as b (b.key)}
	<span
		class="sp-badge"
		class:first={b.order === 1}
		title="{b.order === 1 ? 'First' : 'Second'} in line for {LABELS[b.key]} (FPL squad data)"
		>{b.key}</span
	>
{/each}

<style>
	.sp-badge {
		display: inline-block;
		margin-left: 5px;
		padding: 0 5px;
		border-radius: var(--radius);
		border: 1px solid rgba(46, 214, 194, 0.45);
		color: var(--giq-ink);
		background: rgba(25, 227, 210, 0.14);
		font-size: 0.68em;
		font-weight: 700;
		line-height: 1.5;
		vertical-align: 1px;
		cursor: help;
	}
	/* 2. ottaja: himmennetty variantti — järjestys näkyy ilman lisätekstiä */
	.sp-badge:not(.first) {
		opacity: 0.55;
	}
</style>
