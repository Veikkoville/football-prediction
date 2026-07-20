/** Datakerros: LIVE-API:n luku (sama julkinen backend kuin mobiili + Streamlit).
 *
 * - /api/fantasy     — Phase 0: CS% + FDR (free)
 * - /api/fantasy/xp  — Phase 1: xP per pelaaja/GW + komponentit (premium-näkymä)
 * - /api/accuracy    — julkinen track record (proof-elementti)
 *
 * Moduulitason promise-cache: data päivittyy viikkotasolla → yksi haku per
 * sivulataus riittää (Streamlitin ttl=900 vastine).
 */
import { API_BASE } from './config';

export interface FantasyFixture {
	gw: number;
	opponent_short: string;
	/** #148: koko vastustajanimi tooltippiin — defensiivinen (voi puuttua). */
	opponent?: string;
	venue: string;
	fdr: number;
	cs_pct?: number;
}

export interface FantasyTeam {
	name: string;
	next_avg_cs_pct: number;
	next_avg_fdr: number;
	fixtures: FantasyFixture[];
}

export interface XpOpponent {
	opp: string;
	venue: string;
}

export interface XpGameweek {
	gw: number;
	opponents: XpOpponent[];
	xp: number;
}

export interface XpComponents {
	[key: string]: number;
}

export interface XpPlayer {
	id: number;
	web_name: string;
	team: string;
	team_short: string;
	pos: 'GKP' | 'DEF' | 'MID' | 'FWD';
	xmins: number;
	xp_per_gw: number;
	xp_horizon_total: number;
	gameweeks: XpGameweek[];
	components?: XpComponents;
	components_gw?: number;
	/** #33f: probabilistinen minuuttimalli (start-% 0-100) — defensiivinen. */
	predicted_starts?: number;
	minutes_confidence?: 'low' | 'med' | 'high';
	/** #143: estimaatin datapohja — defensiivinen (vanha payload ei tuo). */
	data_basis?: 'pl_history' | 'limited_history' | 'no_history';
	/** #147: koko nimi VAIN hakua varten — defensiivinen (vanha payload ei tuo). */
	full_name?: string;
}

export interface XpMeta {
	available: boolean;
	next_gameweek?: number;
	horizon_gw?: number;
	[key: string]: unknown;
}

export interface XpResponse {
	meta: XpMeta;
	players: XpPlayer[];
}

export interface FantasyResponse {
	meta: { available: boolean; horizon_gw?: number; [key: string]: unknown };
	teams: FantasyTeam[];
}

export interface AccuracyResponse {
	all_time?: { n?: number; pct_1x2?: number };
	[key: string]: unknown;
}

async function getJson<T>(path: string): Promise<T> {
	const r = await fetch(`${API_BASE}${path}`);
	if (!r.ok) throw new Error(`${path} -> HTTP ${r.status}`);
	return r.json() as Promise<T>;
}

let fantasyP: Promise<FantasyResponse> | null = null;
let xpP: Promise<XpResponse> | null = null;
let accuracyP: Promise<AccuracyResponse> | null = null;

export function fetchFantasy(): Promise<FantasyResponse> {
	fantasyP ??= getJson<FantasyResponse>('/api/fantasy');
	return fantasyP;
}

export function fetchXp(): Promise<XpResponse> {
	xpP ??= getJson<XpResponse>('/api/fantasy/xp');
	return xpP;
}

export function fetchAccuracy(): Promise<AccuracyResponse> {
	accuracyP ??= getJson<AccuracyResponse>('/api/accuracy').catch(() => ({}));
	return accuracyP;
}

export function gwXp(p: XpPlayer, gw: number | undefined): number {
	if (gw == null) return 0;
	return p.gameweeks.find((g) => g.gw === gw)?.xp ?? 0;
}

export function gwOpponents(p: XpPlayer, gw: number | undefined): string {
	if (gw == null) return '';
	const g = p.gameweeks.find((x) => x.gw === gw);
	if (!g || g.opponents.length === 0) return 'Blank';
	return g.opponents.map((o) => `${o.opp} (${o.venue})`).join(', ');
}
