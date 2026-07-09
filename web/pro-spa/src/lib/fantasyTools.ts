/** FPL-työkalujen datakerros (QUEUE #46) - rate-my-team, price watch,
 * transfer planner, captain picker, differentials ja player compare.
 *
 * Sama julkinen backend kuin muu SPA (config.API_BASE). Virheet tulevat
 * backendiltä muodossa {detail: "..."} (4xx/503) - toFriendlyError nostaa
 * detail-tekstin Error.messageksi, jonka komponentit näyttävät inlinenä.
 *
 * Analytiikka: jokainen onnistunut haku capturaa 'fantasy_tools_used'
 * {tool} (ei PII:tä - entry-ID EI mene eventtiin).
 */
import { API_BASE } from './config';
import { capture } from './analytics';

export type FantasyTool =
	| 'rate_team'
	| 'price_watch'
	| 'plan'
	| 'captain'
	| 'differentials'
	| 'compare';

export type Pos = 'GKP' | 'DEF' | 'MID' | 'FWD';

/* ---------- rate-team ---------- */

export interface RatedPlayer {
	id: number;
	web_name: string;
	team_short: string;
	pos: Pos;
	price: number;
	xp_per_gw: number;
	xp_horizon_total: number;
	in_xi: boolean;
	is_captain: boolean;
}

export interface CaptainPick {
	id: number;
	web_name: string;
	team_short: string;
	gw_xp: number;
}

export interface TransferPlayer {
	id: number;
	web_name: string;
	team_short: string;
	price: number;
}

export interface TransferSuggestion {
	out: TransferPlayer;
	in: TransferPlayer;
	pos: Pos;
	delta_xp_horizon: number;
	delta_cost: number;
}

export interface RateTeamResponse {
	meta: {
		mode: string;
		gw: number;
		picks_gw?: number | null;
		horizon_gw?: number;
		note?: string;
		/** #50: backendin uusi semantiikka ('optimal_team'), defensiivinen */
		rating_method?: string;
		[key: string]: unknown;
	};
	team: {
		players: RatedPlayer[];
		missing_ids: number[];
		bank: number;
	};
	rating: {
		team_xp_gw: number;
		team_xp_horizon: number;
		team_xp_horizon_no_captain: number;
		/** #50: uusi semantiikka = % parhaasta mahdollisesta budjettitiimistä
		 * (backend clampaa <=100; UI clampaa silti defensiivisesti) */
		percentile: number;
		strongest_line: string;
		weakest_line: string;
		/** #50: uudet additiiviset kentät, voivat puuttua vanhasta API:sta */
		optimal_team_xp?: number;
		gap_to_optimal_xp?: number;
	};
	captain: {
		pick: CaptainPick;
		alternative: CaptainPick | null;
	};
	transfers: {
		suggestions: TransferSuggestion[];
		hold: boolean;
		note?: string;
	};
}

/* ---------- price watch ---------- */

export interface PriceMove {
	id: number;
	web_name: string;
	now_cost: number;
	status: string; // rising_soon | rising_watch | falling_soon | falling_watch | stable
	confidence: number; // 0-1
	progress_pct: number;
	net_event: number;
	already_changed_today: boolean;
}

export interface PriceWatchResponse {
	meta: {
		available: boolean;
		generated_at: string | null;
		disclaimer: string;
		note?: string;
		[key: string]: unknown;
	};
	risers: PriceMove[];
	fallers: PriceMove[];
}

/* ---------- transfer planner ---------- */

export interface PlanTransfer {
	out: { id: number; web_name: string; team_short: string };
	in: { id: number; web_name: string; team_short: string };
	pos: Pos;
	gain_xp_remaining: number;
	hit: number;
}

export interface PlanGw {
	gw: number;
	transfers: PlanTransfer[];
	roll_transfer: boolean;
	captain: { id: number; web_name: string; gw_xp: number };
	gw_xp: number;
	free_transfers_left: number;
	bank: number;
}

export interface PlanResponse {
	meta: {
		start_gw: number;
		horizon: number;
		heuristic: string;
		note?: string;
		[key: string]: unknown;
	};
	plan: PlanGw[];
	totals: {
		plan_xp: number;
		baseline_xp_no_transfers: number;
		net_gain: number;
		hits_taken: number;
	};
	missing_ids?: number[];
}

/* ---------- captain picker ---------- */

export interface CaptainCandidate {
	id: number;
	web_name: string;
	team_short: string;
	gw_xp: number;
	gap_to_top?: number;
	owned_pct: number | null;
}

export interface CaptainResponse {
	meta: { gw: number; [key: string]: unknown };
	top3: CaptainCandidate[];
	differential: CaptainCandidate | null;
}

/* ---------- differentials ---------- */

export interface DifferentialPlayer {
	id: number;
	web_name: string;
	team_short: string;
	pos: Pos;
	price: number;
	owned_pct: number;
	xp_per_gw: number;
	xp_horizon_total: number;
}

export interface DifferentialsResponse {
	meta: { max_ownership: number; pos: string | null; horizon_gw?: number; [key: string]: unknown };
	players: DifferentialPlayer[];
}

/* ---------- compare ---------- */

export interface ComparePlayer {
	id: number;
	web_name: string;
	team_short: string;
	pos: Pos;
	price: number;
	owned_pct: number | null;
	xmins: number | null;
	predicted_starts: number | null;
	minutes_confidence: 'low' | 'med' | 'high' | null;
	xp_per_gw: number;
	xp_horizon_total: number;
	components: Record<string, number> | null;
	components_gw: number | null;
}

export interface CompareResponse {
	meta: { horizon_gw?: number; [key: string]: unknown };
	players: ComparePlayer[];
	verdict: {
		pick: { id: number; web_name: string };
		margin_xp_horizon: number;
		text: string;
	};
}

/* ---------- fetch helper ---------- */

async function getTool<T>(path: string, tool: FantasyTool): Promise<T> {
	let r: Response;
	try {
		r = await fetch(`${API_BASE}${path}`);
	} catch {
		throw new Error('Could not reach the GoalIQ API. Please check your connection and try again.');
	}
	if (!r.ok) {
		const detail = (await r.json().catch(() => null))?.detail;
		throw new Error(
			typeof detail === 'string' && detail
				? detail
				: `Request failed (${r.status}). Please try again shortly.`
		);
	}
	const data = (await r.json()) as T;
	// Onnistunut haku = työkalu käytetty (ei PII: entry-ID ei mene eventtiin)
	capture('fantasy_tools_used', { tool });
	return data;
}

export function fetchRateTeam(entry: number): Promise<RateTeamResponse> {
	return getTool(`/api/fantasy/rate-team?entry=${entry}`, 'rate_team');
}

export function fetchPriceWatch(): Promise<PriceWatchResponse> {
	return getTool('/api/fantasy/price-watch', 'price_watch');
}

export function fetchPlan(entry: number, horizon: number, ft: number): Promise<PlanResponse> {
	return getTool(`/api/fantasy/plan?entry=${entry}&horizon=${horizon}&ft=${ft}`, 'plan');
}

export function fetchCaptain(entry: number): Promise<CaptainResponse> {
	return getTool(`/api/fantasy/captain?entry=${entry}`, 'captain');
}

export function fetchDifferentials(
	maxOwnership: number,
	pos: Pos | null
): Promise<DifferentialsResponse> {
	const posQ = pos ? `&pos=${pos}` : '';
	return getTool(`/api/fantasy/differentials?max_ownership=${maxOwnership}${posQ}`, 'differentials');
}

export function fetchComparePlayers(ids: number[]): Promise<CompareResponse> {
	return getTool(`/api/fantasy/compare?players=${ids.join(',')}`, 'compare');
}

/** Price watch- ja compare-luottamus samalle kolmiportaiselle asteikolle
 * kuin XpTable #33f (high=teal, med=neutraali, low=himmennetty). */
export function confBand(confidence: number): 'low' | 'med' | 'high' {
	if (confidence >= 0.85) return 'high';
	if (confidence >= 0.5) return 'med';
	return 'low';
}
