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
import { accessToken } from './auth.svelte';

/** Edge-sprint kohta 1 (KRIITTINEN): Supabase-access_token Bearer-headeriin
 * kaikkiin goaliq-api-fantasy-kutsuihin kirjautuneena. Backend verifioi
 * tokenin Supabasen /auth/v1/user-endpointilla → premium-payload säilyy kun
 * PREMIUM_ENFORCE käännetään päälle. Fail-safe: token-virhe → header pois
 * (backend palauttaa silloin free-tason datan, ei kaadu). */
export async function authHeaders(): Promise<Record<string, string>> {
	try {
		const t = await accessToken();
		return t ? { Authorization: `Bearer ${t}` } : {};
	} catch {
		return {};
	}
}

export interface FantasyFixture {
	gw: number;
	opponent_short: string;
	/** #148: koko vastustajanimi tooltippiin — defensiivinen (voi puuttua). */
	opponent?: string;
	venue: string;
	fdr: number;
	cs_pct?: number;
	/** Edge-sprint (contract-data 2b): def_fdr = alias fdr:lle, att_fdr =
	 * hyökkäyssuunnan vaikeus (1 helpoin - 5 vaikein). Defensiivisiä. */
	def_fdr?: number;
	att_fdr?: number;
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
	/** Edge-sprint (contract-data 1): kaikki defensiivisiä (vanha payload ei tuo). */
	owned_pct?: number;
	/** Minuuttijakauma 0..1: p_start + p_cameo + p_bench = 1. */
	p_start?: number;
	p_cameo?: number;
	p_bench?: number;
	/** Erikoistilanne-ottajajärjestys bootstrapista (1 = ykkösottaja, null = ei listalla). */
	set_pieces?: { pens: number | null; corners: number | null; fk: number | null };
	/** Odotettu bonus per ottelu. KARKEA PROXY (per-90-historiavauhti x
	 * minuuttiosuus), EI BPS-simulaatio — copy ei saa väittää muuta. */
	e_bonus?: number;
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
	const headers = await authHeaders();
	const r = await fetch(`${API_BASE}${path}`, { headers });
	if (!r.ok) throw new Error(`${path} -> HTTP ${r.status}`);
	return r.json() as Promise<T>;
}

let fantasyP: Promise<FantasyResponse> | null = null;
let xpP: Promise<XpResponse> | null = null;
/** true = cachetettu xp-haku lähti Bearer-headerilla. Jos ensimmäinen haku
 * tehtiin kirjautumattomana (PremiumPreview-teaser) ja käyttäjä kirjautuu,
 * maskattu vastaus EI saa jäädä premium-näkymän dataksi → refetch tokenilla. */
let xpAuthed = false;
let accuracyP: Promise<AccuracyResponse> | null = null;

export function fetchFantasy(): Promise<FantasyResponse> {
	fantasyP ??= getJson<FantasyResponse>('/api/fantasy');
	return fantasyP;
}

export async function fetchXp(): Promise<XpResponse> {
	const headers = await authHeaders();
	const hasToken = 'Authorization' in headers;
	if (xpP && (xpAuthed || !hasToken)) return xpP;
	xpAuthed = hasToken;
	xpP = fetch(`${API_BASE}/api/fantasy/xp`, { headers }).then((r) => {
		if (!r.ok) throw new Error(`/api/fantasy/xp -> HTTP ${r.status}`);
		return r.json() as Promise<XpResponse>;
	});
	return xpP;
}

export function fetchAccuracy(): Promise<AccuracyResponse> {
	accuracyP ??= getJson<AccuracyResponse>('/api/accuracy').catch(() => ({}));
	return accuracyP;
}

/** #155 Fit checker: yksi rungon pelaaja (hinta miljoonina). */
export interface FitPlayer {
	id: number;
	web_name: string;
	team_short: string;
	pos: 'GKP' | 'DEF' | 'MID' | 'FWD';
	price: number;
	xp_horizon_total: number;
	xp_per_gw: number;
}

export interface FitResponse {
	meta: {
		horizon_gw: number;
		next_gameweek: number | null;
		generated_at: string | null;
		budget_cap: number;
		squad_cost: number;
		bank: number;
	};
	locked: FitPlayer[];
	xi: FitPlayer[];
	bench: FitPlayer[];
	totals: { xi_xp_horizon: number; optimal_xp_horizon: number; delta_xp: number };
	message: string;
}

/** #155: lukitse 1-3 pakkopelaajaa → paras laillinen runko + delta vs vapaa
 * optimi. Ei entry-ID:tä (toimii go-live-hetkellä). Ei cachea (no-store). */
export function fetchFit(lockedIds: number[]): Promise<FitResponse> {
	return getJson<FitResponse>(`/api/fantasy/fit?locked=${lockedIds.join(',')}`);
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
