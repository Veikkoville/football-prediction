<script lang="ts">
	/**
	 * TeamPitchManager (#113) — web-pariteetti mobiilin #106-pitchille +
	 * #112-managerille: XI tintattuina kitteinä positiorivein + penkki,
	 * ja premiumille READ-ONLY what-if-editointi (formation-vaihto,
	 * penkki↔XI-vaihdot, kapteeni/vara, LIVE GW-xP kapteeni ×2, optimal).
	 * Sama /api/fantasy-data (RatedPlayer[]), sama free/premium-gate kuin
	 * mobiilissa (perus-pitch free, editointi premium, source fantasy_manager).
	 * Pitch-tausta = teal-tint (#108-paletti, ei uutta nurmiväriä).
	 */
	import { capture } from '$lib/analytics';
	import type { RatedPlayer } from '$lib/fantasyTools';
	import { teamColorByShort } from '$lib/teamColors';
	import TeamKit from './TeamKit.svelte';

	let {
		players,
		premium = false,
		onUpgrade
	}: { players: RatedPlayer[]; premium?: boolean; onUpgrade?: () => void } = $props();

	/** Validit FPL-muodostelmat [DEF, MID, FWD] (GK aina 1, yht. 11). */
	const FORMATIONS: readonly (readonly [number, number, number])[] = [
		[3, 4, 3],
		[3, 5, 2],
		[4, 4, 2],
		[4, 3, 3],
		[4, 5, 1],
		[5, 4, 1],
		[5, 3, 2]
	];
	const POS_ORDER = ['GKP', 'DEF', 'MID', 'FWD'] as const;

	let xiIds = $state<number[]>([]);
	let captainId = $state<number | null>(null);
	let viceId = $state<number | null>(null);
	let selectedId = $state<number | null>(null);

	// Uusi rate-ajo → resetoi what-if backendin XI:hin/kapteeniin.
	$effect(() => {
		xiIds = players.filter((p) => p.in_xi).map((p) => p.id);
		captainId = players.find((p) => p.is_captain)?.id ?? null;
		viceId = null;
		selectedId = null;
	});

	// Free näkee staattisen pitchin + lukon → paywall_shown kerran (#85-oppi).
	$effect(() => {
		if (!premium && players.length > 0) {
			capture('paywall_shown', { source: 'fantasy_manager' }, 'paywall_shown_fantasy_manager');
		}
	});

	const byId = $derived(new Map(players.map((p) => [p.id, p])));
	const xi = $derived(
		xiIds.map((id) => byId.get(id)).filter((p): p is RatedPlayer => !!p)
	);
	const bench = $derived(players.filter((p) => !xiIds.includes(p.id)));
	const rows = $derived(
		POS_ORDER.map((pos) => xi.filter((p) => p.pos === pos)).filter((r) => r.length > 0)
	);
	const counts = $derived.by(() => {
		const c: Record<string, number> = { GKP: 0, DEF: 0, MID: 0, FWD: 0 };
		for (const p of xi) c[p.pos] = (c[p.pos] ?? 0) + 1;
		return c;
	});
	const effCaptain = $derived(
		captainId != null && xiIds.includes(captainId) ? captainId : null
	);
	const effVice = $derived(
		viceId != null && xiIds.includes(viceId) && viceId !== effCaptain ? viceId : null
	);
	const gwXp = $derived(
		xi.reduce((s, p) => s + p.xp_per_gw, 0) +
			(effCaptain != null ? (byId.get(effCaptain)?.xp_per_gw ?? 0) : 0)
	);
	const selectedInXi = $derived(selectedId != null && xiIds.includes(selectedId));

	/** FPL-säännöt: 11 pelaajaa, 1 MV, DEF 3–5, MID 2–5, FWD 1–3. */
	function isValidXi(xs: RatedPlayer[]): boolean {
		if (xs.length !== 11) return false;
		const c: Record<string, number> = { GKP: 0, DEF: 0, MID: 0, FWD: 0 };
		for (const p of xs) c[p.pos] = (c[p.pos] ?? 0) + 1;
		return (
			c.GKP === 1 && c.DEF >= 3 && c.DEF <= 5 && c.MID >= 2 && c.MID <= 5 && c.FWD >= 1 && c.FWD <= 3
		);
	}

	function bestXiForFormation(f: readonly [number, number, number]): number[] | null {
		const pick = (pos: string, n: number) => {
			const xs = players
				.filter((p) => p.pos === pos)
				.sort((a, b) => b.xp_per_gw - a.xp_per_gw)
				.slice(0, n);
			return xs.length === n ? xs : null;
		};
		const gk = pick('GKP', 1);
		const d = pick('DEF', f[0]);
		const m = pick('MID', f[1]);
		const fw = pick('FWD', f[2]);
		if (!gk || !d || !m || !fw) return null;
		return [...gk, ...d, ...m, ...fw].map((p) => p.id);
	}

	/** XI:stä poistuva kapteeni → vara perii → muuten korkein xP. */
	function fixLeadership(nextXi: number[]) {
		let c = captainId != null && nextXi.includes(captainId) ? captainId : null;
		let v = viceId != null && nextXi.includes(viceId) ? viceId : null;
		if (c == null) {
			c =
				v ??
				nextXi
					.map((id) => byId.get(id)!)
					.sort((a, b) => b.xp_per_gw - a.xp_per_gw)[0]?.id ??
				null;
		}
		if (v === c) v = null;
		captainId = c;
		viceId = v;
	}

	function trySwap(aId: number, bId: number): boolean {
		const inA = xiIds.includes(aId);
		const inB = xiIds.includes(bId);
		if (inA === inB) return false;
		const leaving = inA ? aId : bId;
		const entering = inA ? bId : aId;
		const next = xiIds.map((id) => (id === leaving ? entering : id));
		const nextPlayers = next.map((id) => byId.get(id)).filter((p): p is RatedPlayer => !!p);
		if (!isValidXi(nextPlayers)) return false;
		xiIds = next;
		fixLeadership(next);
		return true;
	}

	function onPlayerClick(id: number) {
		if (!premium) return;
		if (selectedId == null) {
			selectedId = id;
			return;
		}
		if (selectedId === id) {
			selectedId = null;
			return;
		}
		if (trySwap(selectedId, id)) selectedId = null;
		else selectedId = id;
	}

	function applyFormation(f: readonly [number, number, number]) {
		const ids = bestXiForFormation(f);
		if (!ids) return;
		xiIds = ids;
		fixLeadership(ids);
		selectedId = null;
	}

	function applyOptimal() {
		let best: { ids: number[]; xp: number } | null = null;
		for (const f of FORMATIONS) {
			const ids = bestXiForFormation(f);
			if (!ids) continue;
			const ps = ids.map((id) => byId.get(id)!);
			const cap = Math.max(...ps.map((p) => p.xp_per_gw));
			const xp = ps.reduce((s, p) => s + p.xp_per_gw, 0) + cap;
			if (!best || xp > best.xp) best = { ids, xp };
		}
		if (!best) return;
		xiIds = best.ids;
		const top = best.ids
			.map((id) => byId.get(id)!)
			.sort((a, b) => b.xp_per_gw - a.xp_per_gw)[0];
		captainId = top?.id ?? null;
		viceId = null;
		selectedId = null;
	}

	function unlock() {
		capture('upgrade_tapped', { source: 'fantasy_manager' });
		onUpgrade?.();
	}
</script>

{#if players.length > 0}
	<div class="pitch-block">
		{#if premium}
			<p class="label">Formation</p>
			<div class="chips">
				{#each FORMATIONS as f (f.join('-'))}
					<button
						type="button"
						class="chip"
						class:on={counts.DEF === f[0] && counts.MID === f[1] && counts.FWD === f[2]}
						onclick={() => applyFormation(f)}
					>
						{f.join('-')}
					</button>
				{/each}
				<button type="button" class="chip" onclick={applyOptimal}>Optimal lineup</button>
			</div>
			<div class="xp-row">
				<span class="label" style="margin:0">Projected GW xP <span class="muted">(captain doubled)</span></span>
				<span class="xp-val">{gwXp.toFixed(1)}</span>
			</div>
		{/if}

		<p class="label">Starting XI</p>
		<div class="pitch">
			{#each rows as row, i (i)}
				<div class="row">
					{#each row as p (p.id)}
						<button
							type="button"
							class="player"
							class:selected={premium && selectedId === p.id}
							disabled={!premium}
							onclick={() => onPlayerClick(p.id)}
						>
							<span class="kitwrap">
								<TeamKit {...teamColorByShort(p.team_short)} label={p.team_short} size={44} />
								{#if effCaptain === p.id}<span class="badge">C</span>{/if}
								{#if effCaptain !== p.id && effVice === p.id}<span class="badge vice">V</span>{/if}
							</span>
							<span class="pname">{p.web_name}</span>
							<span class="pxp">{p.xp_per_gw.toFixed(1)}</span>
						</button>
					{/each}
				</div>
			{/each}
		</div>

		{#if bench.length > 0}
			<p class="label" style="margin-top: var(--s-3)">Bench</p>
			<div class="benchrow">
				{#each bench as p (p.id)}
					<button
						type="button"
						class="player compact"
						class:selected={premium && selectedId === p.id}
						disabled={!premium}
						onclick={() => onPlayerClick(p.id)}
					>
						<span class="kitwrap">
							<TeamKit {...teamColorByShort(p.team_short)} label={p.team_short} size={34} />
						</span>
						<span class="pname">{p.web_name}</span>
						<span class="pxp">{p.xp_per_gw.toFixed(1)}</span>
					</button>
				{/each}
			</div>
		{/if}

		{#if premium}
			<p class="muted hint">
				{selectedId == null
					? 'Click a player to select them.'
					: 'Click another player to swap bench and XI, or use the buttons below.'}
			</p>
			{#if selectedInXi}
				<div class="actions">
					<button
						type="button"
						class="action"
						onclick={() => {
							captainId = selectedId;
							if (viceId === selectedId) viceId = null;
							selectedId = null;
						}}>Make captain</button
					>
					<button
						type="button"
						class="action"
						onclick={() => {
							if (captainId === selectedId) captainId = null;
							viceId = selectedId;
							selectedId = null;
						}}>Make vice</button
					>
				</div>
			{/if}
			<p class="muted hint">
				Plan your lineup here, then apply it in the official FPL app. GoalIQ never changes your
				real team.
			</p>
		{:else}
			<button type="button" class="lockrow" onclick={unlock}>
				<span aria-hidden="true">🔒</span>
				Lineup editing (formations, swaps, captain) is Premium
				<span class="cta">Unlock with Premium</span>
			</button>
		{/if}
	</div>
{/if}

<style>
	.pitch-block {
		max-width: 680px;
		margin-top: var(--s-4);
	}
	.label {
		margin: 0 0 var(--s-1);
		font-size: var(--step--1);
		font-weight: 700;
		color: var(--text-muted);
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}
	.chips {
		display: flex;
		flex-wrap: wrap;
		gap: var(--s-2);
		margin-bottom: var(--s-3);
	}
	.chip {
		border: 1px solid var(--border);
		border-radius: 999px;
		background: var(--surface);
		color: var(--text-muted);
		font-weight: 700;
		font-size: var(--step--1);
		padding: 6px 12px;
		cursor: pointer;
	}
	.chip.on {
		background: var(--giq-magenta);
		border-color: var(--giq-magenta);
		color: #fff;
	}
	.xp-row {
		display: flex;
		align-items: baseline;
		justify-content: space-between;
		gap: var(--s-3);
		background: var(--giq-paper, #f6f4ff);
		border-radius: var(--radius);
		padding: var(--s-2) var(--s-3);
		margin-bottom: var(--s-3);
	}
	.xp-val {
		color: var(--giq-magenta-deep);
		font-size: var(--step-2);
		font-weight: 800;
		font-variant-numeric: tabular-nums;
	}
	/* Pitch-tausta = teal-tint (#108: kanoninen token, ei uutta nurmiväriä) */
	.pitch {
		background: rgba(0, 194, 173, 0.08);
		border: 1px solid var(--border);
		border-radius: 14px;
		padding: var(--s-2) var(--s-1);
	}
	.row {
		display: flex;
		justify-content: space-evenly;
		margin: var(--s-2) 0;
	}
	.player {
		display: grid;
		justify-items: center;
		gap: 1px;
		width: 68px;
		background: none;
		border: 2px solid transparent;
		border-radius: 10px;
		padding: 2px;
		cursor: pointer;
		color: var(--text);
	}
	.player:disabled {
		cursor: default;
	}
	.player.selected {
		border-color: var(--giq-magenta);
	}
	.kitwrap {
		position: relative;
		display: inline-block;
	}
	.badge {
		position: absolute;
		top: -3px;
		right: -5px;
		width: 15px;
		height: 15px;
		border-radius: 8px;
		background: var(--giq-magenta);
		color: #fff;
		font-size: 9px;
		font-weight: 800;
		display: flex;
		align-items: center;
		justify-content: center;
	}
	.badge.vice {
		background: var(--text-muted);
	}
	.pname {
		font-size: 10px;
		font-weight: 600;
		max-width: 66px;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.pxp {
		font-size: 10px;
		color: var(--text-muted);
		font-variant-numeric: tabular-nums;
	}
	.benchrow {
		display: flex;
		flex-wrap: wrap;
		gap: var(--s-1);
	}
	.hint {
		margin: var(--s-2) 0 0;
		font-size: var(--step--1);
	}
	.actions {
		display: flex;
		gap: var(--s-2);
		margin-top: var(--s-2);
	}
	.action {
		background: var(--surface);
		border: 1px solid rgba(255, 46, 126, 0.35);
		border-radius: 8px;
		color: var(--giq-magenta);
		font-weight: 700;
		font-size: var(--step--1);
		padding: 8px 14px;
		cursor: pointer;
	}
	.lockrow {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--s-2);
		width: 100%;
		margin-top: var(--s-3);
		background: rgba(255, 46, 126, 0.1);
		border: 1px solid rgba(255, 46, 126, 0.35);
		border-radius: var(--radius);
		padding: var(--s-2) var(--s-3);
		color: var(--text);
		font-weight: 600;
		font-size: var(--step--1);
		cursor: pointer;
		text-align: left;
	}
	.cta {
		margin-left: auto;
		color: var(--positive);
		font-weight: 700;
	}
</style>
