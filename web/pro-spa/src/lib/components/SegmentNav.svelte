<script lang="ts" module>
	// #48: jaettu segmenttinavigaatio FPL-työkaluille (free + pro pinnat).
	export type Segment = { id: string; label: string };
</script>

<script lang="ts">
	import { onMount } from 'svelte';
	import { replaceState } from '$app/navigation';

	let {
		segments,
		active = $bindable(),
		label = 'FPL tools'
	}: { segments: Segment[]; active: string; label?: string } = $props();

	// Halpa deep-link: #tools=<segmentti>. Luetaan kerran mountissa; kirjoitus
	// replaceState:lla ($app/navigation) → ei taistele SvelteKit-routerin
	// kanssa eikä kasvata selaimen historiaa.
	onMount(() => {
		const m = window.location.hash.match(/^#tools=([\w-]+)$/);
		if (m && segments.some((s) => s.id === m[1])) active = m[1];
	});

	let tabEls: HTMLButtonElement[] = [];

	function select(id: string) {
		active = id;
		try {
			replaceState(`#tools=${id}`, {});
		} catch {
			// Router ei vielä valmis (esim. testiympäristö): segmentti vaihtuu silti.
		}
	}

	function onKeydown(e: KeyboardEvent, i: number) {
		const last = segments.length - 1;
		let next: number | null = null;
		if (e.key === 'ArrowRight' || e.key === 'ArrowDown') next = i === last ? 0 : i + 1;
		else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') next = i === 0 ? last : i - 1;
		else if (e.key === 'Home') next = 0;
		else if (e.key === 'End') next = last;
		if (next == null) return;
		e.preventDefault();
		select(segments[next].id);
		tabEls[next]?.focus();
	}
</script>

<div class="seg-nav" role="tablist" aria-label={label}>
	{#each segments as s, i (s.id)}
		<button
			bind:this={tabEls[i]}
			id="seg-{s.id}"
			type="button"
			role="tab"
			aria-selected={active === s.id}
			aria-controls="panel-{s.id}"
			tabindex={active === s.id ? 0 : -1}
			class:active={active === s.id}
			onclick={() => select(s.id)}
			onkeydown={(e) => onKeydown(e, i)}
		>
			{s.label}
		</button>
	{/each}
</div>

<style>
	.seg-nav {
		display: flex;
		flex-wrap: wrap;
		gap: var(--s-2);
		margin: var(--s-4) 0 var(--s-6);
	}
	.seg-nav button {
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: 999px;
		color: var(--text-muted);
		font-size: var(--step--1);
		font-weight: 700;
		padding: 0.5em 1.2em;
		min-height: 44px;
	}
	.seg-nav button:hover {
		color: var(--text);
		border-color: var(--text-muted);
	}
	.seg-nav button.active {
		background: var(--accent);
		border-color: var(--accent);
		color: var(--accent-contrast);
	}
	.seg-nav button.active:hover {
		background: var(--giq-magenta-deep);
		border-color: var(--giq-magenta-deep);
	}
</style>
