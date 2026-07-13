<script lang="ts">
	// #73: "malli tekee töitä" -progressiivinen paljastus lataustilaan.
	// Askeleet kuvaavat putken OIKEAT vaiheet (ei keksittyä "scanning news"
	// -teatteria) ja etenevät ajastimella; viimeinen askel jää aktiiviseksi
	// kunnes vastaus saapuu ja komponentti unmountataan. Ei keinotekoista
	// viivettä - nopea vastaus vain ohittaa loput askeleet.
	interface Props {
		steps: string[];
	}
	let { steps }: Props = $props();
	let idx = $state(0);

	$effect(() => {
		idx = 0;
		const timer = setInterval(() => {
			if (idx < steps.length - 1) {
				idx += 1;
			} else {
				clearInterval(timer);
			}
		}, 450);
		return () => clearInterval(timer);
	});
</script>

<div class="working" role="status" aria-live="polite">
	{#each steps as s, i (s)}
		<div class="step" class:done={i < idx} class:active={i === idx}>
			<span class="marker" aria-hidden="true">{i < idx ? '✓' : ''}</span>
			<span>{s}</span>
		</div>
	{/each}
</div>

<style>
	.working {
		margin: var(--s-4) 0;
		display: flex;
		flex-direction: column;
		gap: var(--s-2);
	}
	.step {
		display: flex;
		align-items: center;
		gap: var(--s-2);
		font-size: 14px;
		color: var(--muted, #575170);
		opacity: 0.45;
		transition: opacity 0.2s ease;
	}
	.step.active {
		opacity: 1;
		color: var(--text, inherit);
		font-weight: 600;
	}
	.step.done {
		opacity: 0.8;
	}
	.marker {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 18px;
		height: 18px;
		border-radius: 50%;
		border: 2px solid currentColor;
		font-size: 11px;
		flex: none;
	}
	.step.active .marker {
		border-color: var(--positive, #00c2ad);
		animation: pulse 1s ease-in-out infinite;
	}
	.step.done .marker {
		border-color: var(--positive, #00c2ad);
		color: var(--positive, #00c2ad);
	}
	@keyframes pulse {
		0%,
		100% {
			transform: scale(1);
		}
		50% {
			transform: scale(1.15);
		}
	}
</style>
