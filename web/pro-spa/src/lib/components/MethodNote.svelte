<script lang="ts">
	import type { Snippet } from 'svelte';

	// Metodologia-läpinäkyvyys (#22): avattava "how it works" -selite.
	// <details> = natiivi a11y (näppäimistö/ruudunlukija) ilman JS-tilaa.
	let { summary, children }: { summary: string; children: Snippet } = $props();
</script>

<details class="method">
	<summary><span class="i" aria-hidden="true">i</span>{summary}</summary>
	<div class="body">
		{@render children()}
	</div>
</details>

<style>
	.method {
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: var(--radius);
		margin: 0 0 var(--s-4);
		font-size: var(--step--1);
	}
	summary {
		cursor: pointer;
		padding: var(--s-3) var(--s-4);
		color: var(--text-muted);
		font-weight: 700;
		list-style: none;
		display: flex;
		align-items: center;
		gap: var(--s-2);
		min-height: 44px;
	}
	summary::-webkit-details-marker {
		display: none;
	}
	summary:hover {
		color: var(--text);
	}
	.method[open] summary {
		color: var(--text);
		border-bottom: 1px solid var(--border);
	}
	.i {
		flex: none;
		width: 18px;
		height: 18px;
		border-radius: 50%;
		border: 1.5px solid var(--giq-teal);
		color: var(--giq-teal);
		font-style: italic;
		font-weight: 700;
		font-size: 12px;
		line-height: 1;
		display: inline-flex;
		align-items: center;
		justify-content: center;
	}
	.body {
		padding: var(--s-3) var(--s-4) var(--s-4);
		color: var(--text-muted);
	}
	.body :global(p) {
		margin: 0 0 var(--s-2);
	}
	.body :global(p:last-child) {
		margin-bottom: 0;
	}
	.body :global(strong) {
		color: var(--text);
	}
</style>
