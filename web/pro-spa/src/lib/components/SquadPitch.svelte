<script lang="ts">
	/**
	 * SquadPitch (13.8) — on-page-pitch model squadille (/spl, myöhemmin FPL).
	 * Sama visuaalinen kieli kuin sharePitchCard-jakokortissa (teal-raidat,
	 * TeamKit-siluetit), mutta DOM-renderöinti: skaalautuu, ei canvasia.
	 * Presentationaalinen: saa valmiiksi värjätyt pelaajat (sama muoto kuin
	 * PitchCardPlayer), ei hae mitään itse.
	 *
	 * Yksikkömerkintä on kentän SISÄLLÄ lukujen vieressä — yksikkö kaukana
	 * luvusta on sama vikaluokka josta Δ vs crowd luettiin pisteinä (11.8).
	 */
	import TeamKit from './TeamKit.svelte';
	import type { PitchCardPlayer } from '$lib/shareCard';

	let {
		rows,
		bench = [],
		unitNote = 'xP per GW'
	}: {
		/** XI positioriveinä (GKP ylhäällä → FWD alhaalla) */
		rows: PitchCardPlayer[][];
		bench?: PitchCardPlayer[];
		unitNote?: string;
	} = $props();
</script>

<div class="pitch">
	<span class="unit">{unitNote}</span>
	{#each rows as row}
		<div class="row">
			{#each row as p}
				<div class="slot">
					<TeamKit color={p.color} textColor={p.textColor} label={p.team} size={54} />
					<span class="name">{p.name}</span>
					<span class="xp">{p.xp}</span>
				</div>
			{/each}
		</div>
	{/each}
</div>
{#if bench.length > 0}
	<div class="bench">
		<span class="bench-label">Bench</span>
		<div class="bench-row">
			{#each bench as p}
				<div class="slot small">
					<TeamKit color={p.color} textColor={p.textColor} label={p.team} size={40} />
					<span class="name">{p.name}</span>
					<span class="xp">{p.xp}</span>
				</div>
			{/each}
		</div>
	</div>
{/if}

<style>
	.pitch {
		position: relative;
		display: flex;
		flex-direction: column;
		justify-content: space-around;
		min-height: 430px;
		padding: 26px 8px 18px;
		border: 1px solid rgba(46, 214, 194, 0.45);
		border-radius: 12px;
		background:
			radial-gradient(140px 70px at 50% 100%, rgba(46, 214, 194, 0.12) 0 68px, transparent 70px),
			repeating-linear-gradient(
				to bottom,
				rgba(46, 214, 194, 0.1) 0 54px,
				rgba(46, 214, 194, 0.16) 54px 108px
			);
	}
	/* Ylälaidan maalialue vihjeenä puolikkaasta kentästä (sama kaava kuin kortissa) */
	.pitch::before {
		content: '';
		position: absolute;
		top: 0;
		left: 50%;
		transform: translateX(-50%);
		width: min(320px, 60%);
		height: 56px;
		border: 1px solid rgba(46, 214, 194, 0.35);
		border-top: none;
		pointer-events: none;
	}
	.unit {
		position: absolute;
		top: 8px;
		right: 12px;
		font-size: 0.72rem;
		letter-spacing: 0.04em;
		color: rgba(46, 214, 194, 0.85);
	}
	.row {
		display: flex;
		justify-content: space-evenly;
		align-items: flex-start;
		gap: 4px;
	}
	.slot {
		display: flex;
		flex-direction: column;
		align-items: center;
		min-width: 0;
		flex: 1 1 0;
		text-align: center;
	}
	.slot .name {
		font-weight: 700;
		font-size: 0.82rem;
		max-width: 100%;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.slot .xp {
		font-size: 0.78rem;
		opacity: 0.7;
	}
	.slot.small .name {
		font-size: 0.74rem;
		font-weight: 600;
	}
	.slot.small .xp {
		font-size: 0.72rem;
	}
	.bench {
		margin-top: 10px;
	}
	.bench-label {
		display: block;
		font-size: 0.72rem;
		letter-spacing: 0.06em;
		text-transform: uppercase;
		opacity: 0.6;
		margin-bottom: 6px;
	}
	.bench-row {
		display: flex;
		justify-content: center;
		gap: 8px;
	}
	.bench-row .slot {
		max-width: 160px;
	}
	@media (max-width: 560px) {
		.pitch {
			min-height: 360px;
		}
		.slot .name {
			font-size: 0.72rem;
		}
	}
</style>
