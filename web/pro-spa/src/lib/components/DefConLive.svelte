<script lang="ts">
	/** DefCon-live (2.8.2026) — oman kokoonpanon defensive contribution KESKEN
	 * kierroksen. Tuotteen ainoa live-pinta.
	 *
	 * Renderöi tyhjää aina kun sanottavaa ei ole: esikaudella ja kierrosten
	 * välissä (meta.available=false) sekä ennen kuin yksikään pelaaja on
	 * pelannut minuuttiakaan. Kuollut paneeli on pahempi kuin ei paneelia.
	 *
	 * Päivittyy 60 s välein, mutta EI kun välilehti on taustalla — turha
	 * kuorma Renderin 0.5 vCPU:lle ja FPL:lle. Backend cachettaa saman 60 s.
	 */
	import { onMount } from 'svelte';
	import { fplEntry } from '$lib/fplEntry.svelte';
	import { fetchDefconLive, type DefconLiveResponse } from '$lib/api';
	import { capture } from '$lib/analytics';

	const POLL_MS = 60_000;
	let data = $state<DefconLiveResponse | null>(null);
	// Plain let, EI $state: tätä luetaan ja kirjoitetaan efektin sisällä, ja
	// reaktiivisena se tekisi efektikehän (muisti: svelte-effect-cycle).
	let lastLoaded: string | null = null;

	const entryId = $derived.by(() => {
		const saved = fplEntry.savedEntry;
		if (saved && /^\d{1,10}$/.test(saved)) return saved;
		const typed = fplEntry.entry.trim();
		return /^\d{1,10}$/.test(typed) ? typed : null;
	});

	async function load(id: string) {
		try {
			const res = await fetchDefconLive(Number(id));
			data = res.meta.available ? res : null;
		} catch {
			data = null; // live-feedin katko ei saa näkyä virheenä työkalusivulla
		}
	}

	$effect(() => {
		const id = entryId;
		if (!id) {
			data = null;
			lastLoaded = null;
			return;
		}
		if (id !== lastLoaded) {
			lastLoaded = id;
			void load(id);
		}
	});

	onMount(() => {
		const timer = setInterval(() => {
			const id = entryId;
			if (id && !document.hidden) void load(id);
		}, POLL_MS);
		return () => clearInterval(timer);
	});

	/** Vain DefCon-kelpoiset (ei maalivahteja) jotka ovat pelanneet. */
	const rows = $derived(
		(data?.players ?? [])
			.filter((p) => p.eligible && p.minutes > 0)
			// Lähimpänä kynnystä ensin = toiminnallisin järjestys; jo osuneet
			// perään, koska niissä ei ole enää mitään seurattavaa.
			.sort((a, b) => {
				if (a.hit !== b.hit) return a.hit ? 1 : -1;
				return (a.remaining ?? 99) - (b.remaining ?? 99);
			})
	);
	const hits = $derived(rows.filter((p) => p.hit).length);

	let announced = false;
	$effect(() => {
		if (rows.length > 0 && !announced) {
			announced = true;
			capture('defcon_live_shown', { gw: data?.meta.gw ?? null, n: rows.length });
		}
	});
</script>

{#if rows.length > 0}
	<section class="dcl" aria-label="Defensive contribution, live">
		<div class="bar">
			DefCon live · GW{data?.meta.gw} · {hits}/{rows.length} at the threshold
		</div>
		<ul>
			{#each rows as p (p.id)}
				<li class:hit={p.hit}>
					<span class="who">
						<span class="name">{p.web_name}</span>
						{#if p.is_captain}<span class="c" title="Captain">C</span>{/if}
						<span class="meta">{p.team_short} · {p.pos} · {p.minutes}'</span>
					</span>
					<span class="track" aria-hidden="true">
						<span
							class="fill"
							style="width: {Math.min(100, (p.defcon / (p.threshold || 1)) * 100)}%"
						></span>
					</span>
					<span class="num">
						{p.defcon}/{p.threshold}
						{#if p.hit}<span class="ok">✓ 2 pts</span>{/if}
					</span>
				</li>
			{/each}
		</ul>
		<p class="note">{data?.meta.note}</p>
	</section>
{/if}

<style>
	.dcl {
		border: 1px solid var(--track);
		background: var(--panel);
		margin-bottom: 16px;
	}
	.bar {
		background: var(--cream);
		color: var(--ink);
		font-size: 11.5px;
		text-transform: uppercase;
		letter-spacing: 0.16em;
		padding: 6px 10px;
	}
	ul {
		list-style: none;
		margin: 0;
		padding: 8px 10px;
		display: grid;
		gap: 6px;
	}
	li {
		display: grid;
		grid-template-columns: minmax(0, 1fr) 90px auto;
		gap: 10px;
		align-items: center;
		font-size: 13px;
	}
	.who {
		display: flex;
		gap: 6px;
		align-items: baseline;
		min-width: 0;
	}
	.name {
		color: var(--cream);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.c {
		color: var(--ink);
		background: var(--amber);
		font-size: 10px;
		padding: 0 4px;
		font-weight: 700;
	}
	.meta {
		color: var(--faint);
		font-size: 11px;
		white-space: nowrap;
	}
	.track {
		height: 6px;
		background: var(--track);
		display: block;
	}
	.fill {
		height: 100%;
		background: var(--amber);
		display: block;
	}
	li.hit .fill {
		background: var(--green);
	}
	.num {
		font-variant-numeric: tabular-nums;
		color: var(--muted);
		white-space: nowrap;
	}
	.ok {
		color: var(--green);
		margin-left: 6px;
	}
	.note {
		color: var(--faint);
		font-size: 11px;
		margin: 0;
		padding: 0 10px 10px;
	}
	@media (max-width: 520px) {
		li {
			grid-template-columns: minmax(0, 1fr) 56px auto;
		}
	}
</style>
