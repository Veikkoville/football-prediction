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
import { authHeaders } from './api';

export type FantasyTool =
	| 'rate_team'
	| 'rate_team_draft'
	| 'model_squad'
	| 'price_watch'
	| 'plan'
	| 'captain'
	| 'differentials'
	| 'compare'
	| 'value'
	| 'xg_leaders'
	| 'defcon_leaders'
	| 'defcon_gw'
	| 'chip_ev'
	| 'plan_chains'
	| 'league'
	| 'h2h'
	| 'edge'
	| 'xp_csv';

export type Pos = 'GKP' | 'DEF' | 'MID' | 'FWD';

/* ---------- rate-team ---------- */

/** #123: yhden GW:n xp + vastustajat (DGW = useampi, blank = []). */
export interface RatedPlayerGw {
	gw: number;
	opponents: { opp: string; venue: 'H' | 'A' }[];
	xp: number;
}

export interface RatedPlayer {
	id: number;
	web_name: string;
	team_short: string;
	pos: Pos;
	price: number;
	xp_per_gw: number;
	xp_horizon_total: number;
	/** #122/#123: optional — vanha deployattu backend ei lähetä. */
	gameweeks?: RatedPlayerGw[];
	in_xi: boolean;
	is_captain: boolean;
	/** 15.8: FPL:n saatavuuslippu. null = ei liputettu, EI "100 % varma". */
	chance_next?: number | null;
	news?: string | null;
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
	/** #121: in-pelaajan planner-kentät optional (vanha backend → ei Applya). */
	in: TransferPlayer & {
		xp_per_gw?: number;
		xp_horizon_total?: number;
		gameweeks?: RatedPlayerGw[];
	};
	pos: Pos;
	delta_xp_horizon: number;
	delta_cost: number;
}

/** #63: backendin eksplisiittinen hold/transfer-kanta (hit-tietoinen netto
 * vs kynnys). Optional kaikissa vastauksissa - vanha API voi puuttua. */
export interface HoldVerdict {
	verdict: 'hold' | 'transfer';
	best_move_gain_xp: number | null;
	horizon_gws: number;
	threshold_xp: number;
	hit_applied_xp?: number;
	transfers_planned?: number;
	message: string;
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
		/** 26.7: walk-forward-backtestin tiiviste, jotta rating on falsifioituva. */
		projection_accuracy?: {
			meta?: { season?: string; gate_passed?: boolean; method?: string };
			played: {
				n_gws: number;
				mae_xp: number;
				mae_baseline: number;
				rho_xp: number;
				rho_baseline: number;
			};
			known_bias?: { signed_bias_xp?: number; note?: string };
		} | null;
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
		/** 26.7: sama luku 0-100 kokonaislukuna (luettavampi otsikkoluku). */
		rating?: number;
		rating_max?: number;
		/** true jos XI ylittaa parhaan budjettijoukkueen (ennen: leikattiin 100:aan). */
		beats_benchmark?: boolean;
		/** 28.7: onko vertailukohta TODISTETUSTI optimi (eksakti haku onnistui).
		 *  false = klubikatto sitoi ja jouduttiin paikallishakuun → copy ei saa
		 *  sanoa "best possible". Puuttuu vanhalta APIlta → kohdellaan tosina. */
		optimal_proven?: boolean;
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
		hold_verdict?: HoldVerdict;
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
	hold_verdict?: HoldVerdict;
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
	/* #71: positio-sisäiset persentiilit + delta (model − crowd).
	   Optionaalisia kunnes backend-deploy on livenä (fallback-safe). */
	model_pct?: number;
	crowd_pct?: number;
	model_vs_crowd_delta?: number;
}

export interface ModelVsCrowd {
	note: string;
	model_backs: DifferentialPlayer[];
	crowd_backs: DifferentialPlayer[];
}

export interface DifferentialsResponse {
	meta: { max_ownership: number; pos: string | null; horizon_gw?: number; [key: string]: unknown };
	players: DifferentialPlayer[];
	model_vs_crowd?: ModelVsCrowd;
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
	/* 6.8 compare-V2: pelipaikkarelevantit raakastatit. Optionaaliset —
	 * vanha deployattu backend ei lähetä → rivit jäävät pois, ei kaadu. */
	xg90_prev?: number;
	xa90_prev?: number;
	prev_season?: string | null;
	defcon_hit_rate_pct?: number | null;
	defcon_dc_per_game?: number | null;
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
		// Edge-sprint kohta 1: Bearer-token kaikkiin fantasy-kutsuihin
		// kirjautuneena (premium-maskit eivät osu maksajaan).
		const headers = await authHeaders();
		r = await fetch(`${API_BASE}${path}`, { headers });
	} catch {
		throw new Error('Could not reach the GoalIQ API. Please check your connection and try again.');
	}
	if (!r.ok) {
		const detail = (await r.json().catch(() => null))?.detail;
		const err = new Error(
			typeof detail === 'string' && detail
				? detail
				: `Request failed (${r.status}). Please try again shortly.`
		) as Error & { code?: string; status?: number };
		// 28.7: koneluettava syy talteen. Ilman tätä kutsuja joutuisi
		// vertaamaan virheviestin merkkijonoa, joka rikkoutuu heti kun copya
		// muutetaan. Backend lähettää koodin headerissa, jotta `detail` pysyy
		// merkkijonona eivätkä jo julkaistut klientit riko.
		err.code = r.headers.get('X-GoalIQ-Error-Code') ?? undefined;
		err.status = r.status;
		throw err;
	}
	const data = (await r.json()) as T;
	// Onnistunut haku = työkalu käytetty (ei PII: entry-ID ei mene eventtiin)
	capture('fantasy_tools_used', { tool });
	return data;
}

export function fetchRateTeam(entry: number): Promise<RateTeamResponse> {
	return getTool(`/api/fantasy/rate-team?entry=${entry}`, 'rate_team');
}

/** P1 (23.7): esikausi-draft ilman entry-ID:tä — FPL julkaisee picksit vasta
 * GW-deadlinen jälkeen, joten ennen GW1:tä runko annetaan 15 element-ID:nä
 * (backendin players=-moodi; kapteenin valitsee malli, paras GW-xP). */
export function fetchRateTeamManual(playerIds: number[]): Promise<RateTeamResponse> {
	return getTool(`/api/fantasy/rate-team?players=${playerIds.join(',')}`, 'rate_team_draft');
}

/** 1.8: mallin vapaa optimirunko (sama free_optimum kuin rate-benchmark ja
 * fit checker -> luvut eivät voi eriytyä). Joukkue 2 -vertailuslotin
 * "beat the model" -esitäyttöön. */
export interface ModelSquadResponse {
	meta: {
		generated_at?: string;
		horizon_gw?: number;
		next_gameweek?: number;
		xi_xp_horizon: number;
		optimal_proven: boolean;
	};
	players: { id: number; web_name: string; team_short: string; pos: string }[];
}

export function fetchModelSquad(): Promise<ModelSquadResponse> {
	return getTool('/api/fantasy/model-squad', 'model_squad');
}

export function fetchPriceWatch(): Promise<PriceWatchResponse> {
	return getTool('/api/fantasy/price-watch', 'price_watch');
}

export function fetchPlan(entry: number, horizon: number, ft: number): Promise<PlanResponse> {
	return getTool(`/api/fantasy/plan?entry=${entry}&horizon=${horizon}&ft=${ft}`, 'plan');
}

/** PI-16b (28.7): esikausi-draft plannerille — sama kaava kuin
 * fetchRateTeamManual. Backend on tukenut players-moodia koko ajan. */
export function fetchPlanDraft(
	playerIds: number[],
	horizon: number,
	ft: number
): Promise<PlanResponse> {
	return getTool(
		`/api/fantasy/plan?players=${playerIds.join(',')}&horizon=${horizon}&ft=${ft}`,
		'plan'
	);
}

/** HUOM (PI-16b-tarkistus 28.7): SPA EI kutsu tätä. Webin CaptainRanker
 * johtaa top-10:n suoraan xP-taulukosta, joten se ei tarvitse joukkuetta
 * eikä siis kärsi esikauden 404:sta. Jätetty datakerrokseen mobiilin
 * pariteetin vuoksi; jos tämä otetaan käyttöön, käytä
 * runWithSquadFallback-kaavaa kuten TransferPlanner. */
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

/* ---------- #127: value + GK rotation pairs (#114-web-pariteetti) ---------- */

export interface ValuePlayer {
	id: number;
	web_name: string;
	team_short: string;
	pos: Pos | '?';
	price: number;
	owned_pct: number;
	xp_horizon_total: number;
	value: number;
	fixture_swing: number;
	swing_label: 'steady' | 'moderate' | 'swingy';
	/** 5.8: vauhti ja minuutit erikseen. `xp_per_90` on null kun odotettuja
	 *  minuutteja on liian vähän jotta vauhti tarkoittaisi mitään — null ei ole
	 *  sama asia kuin 0, ja UI:n on näytettävä ne eri tavalla. Defensiiviset:
	 *  vanha payload ei tuo kumpaakaan. */
	xmins?: number | null;
	xp_per_90?: number | null;
}

export interface GkPair {
	avg_best_cs_pct: number;
	combined_price: number;
	gk_a: { id: number; web_name: string; team_short: string; price: number };
	gk_b: { id: number; web_name: string; team_short: string; price: number };
	gw_split: { gw: number; team_short: string; cs_pct: number }[];
}

export interface ValueResponse {
	meta: {
		available: boolean;
		season: string | null;
		gw: number | null;
		horizon_gw: number | null;
		generated_at: string | null;
		note: string;
	};
	players: ValuePlayer[];
	gk: {
		meta: { available: boolean; gw?: number | null; horizon_gw?: number | null; note: string };
		pairs: GkPair[];
	};
}

/** 4.8: top_n 20 -> 50. Backend on tukenut 1-100 alusta asti (api/main.py
 *  `top_n: int = Query(default=20, ge=1, le=100)`); 20 oli klientin oletus
 *  eika rajoite. 50 rivilla pelipaikkasuodatin antaa jokaiselle positiolle
 *  mielekkaan listan (20 rivista GKP-suodatin tuotti 1-2 rivia). */
export function fetchValue(): Promise<ValueResponse> {
	return getTool('/api/fantasy/value?top_n=50', 'value');
}

/* ---------- #124/#125: xG leaders + DefCon tracker ---------- */

/** Jaettu meta: basis kertoo REHELLISESTI minkä kauden datasta rivit ovat
 * (esikausi = 25/26 + pakollinen basis_label; otoskoko per rivi). */
export interface LeadersMeta {
	/** Pelien maara ikkunassa TAI 'season' (koko basis-kausi, 30.7 #7). */
	window: number | 'season';
	basis_season: string | null;
	is_prev_season_basis?: boolean;
	basis_label: string | null;
	generated_at: string | null;
	note?: string;
}

export interface XgLeaderRow {
	id: number;
	web_name: string;
	team_short: string;
	pos: Pos;
	price: number;
	owned_pct: number | null;
	games: number;
	basis: string | null;
	xg_total: number;
	xg_per_game: number;
	xa_total: number;
	xa_per_game: number;
	xgi_per_game: number;
	/** 26.7: minuutit ikkunassa (per 90 + minuuttikynnys). */
	mins?: number;
	/** 26.7: kausitotaalit koko kauden nakymaa varten. */
	season?: {
		mins: number;
		starts: number;
		xg: number;
		xa: number;
		xgi: number;
	} | null;
}

export interface XgLeadersResponse {
	meta: LeadersMeta;
	players: XgLeaderRow[];
}

export interface DefconLeaderRow {
	id: number;
	web_name: string;
	team_short: string;
	pos: 'DEF' | 'MID' | 'FWD';
	price: number;
	owned_pct: number | null;
	games: number;
	basis: string | null;
	threshold: number;
	dc_per_game: number;
	/** #226-DC: kausibasiksella nimittaja on startit (sama kuin FPL:n omissa
	 * luvuissa), ei pelatut ottelut. `hit_rate_basis` kertoo kummasta. */
	hit_rate_pct: number;
	hit_rate_basis?: 'starts' | 'games';
	starts?: number;
	defcon_points_window: number;
	hits: number;
	/** Positio vaihtui kausien valilla -> kynnys eri kuin basis-kaudella.
	 * `hit_rate_basis_pos_pct` on sama luku basis-position kynnyksella. */
	pos_changed?: boolean;
	basis_pos?: 'DEF' | 'MID' | 'FWD';
	hit_rate_basis_pos_pct?: number | null;
}

export interface DefconLeadersResponse {
	meta: LeadersMeta & {
		thresholds?: Record<string, number>;
		points_per_hit?: number;
		rule_note?: string;
		hit_rate_denominator?: 'starts' | 'games';
		pool_min_starts?: number;
		hit_rate_note?: string;
	};
	players: DefconLeaderRow[];
}

/** #137: window = pelien lukumäärä (3-10). Vanha backend ignoroi → oletusikkuna. */
export function fetchXgLeaders(window = 5): Promise<XgLeadersResponse> {
	// 26.7: xG vapautettu ilmaiseksi ja klientilla on joukkue-/sijaintisuodattimet
	// → haetaan koko aineisto, muuten suodattimet toimisivat vain top-100:aan.
	// Naytto rajataan komponentissa (renderointi on hidas osa, ei fetch).
	return getTool(`/api/fantasy/xg-leaders?window=${window}&top_n=1000`, 'xg_leaders');
}

/** basis='season' (30.7, #7): koko basis-kauden ranking per-GW-matriisin
 *  kausisummista — window ohitetaan. top_n nostettu 400:aan molemmissa
 *  basiksissa (lista oli kovakoodattu top 20; matriisissa on 373 pelaajaa).
 *  Naytto rajataan komponentissa kuten xG-listassa. */
export function fetchDefconLeaders(
	window = 5,
	basis: 'recent' | 'season' = 'recent'
): Promise<DefconLeadersResponse> {
	const q = basis === 'season' ? 'basis=season&top_n=400' : `window=${window}&top_n=400`;
	return getTool(`/api/fantasy/defcon-leaders?${q}`, 'defcon_leaders');
}

/* ---------- Per-GW DefCon -matriisi (30.7) ---------- */

/** Kompakti rivi: [gw, opp, venue, minutes, dc] (payload-kuri, ~240 kB). */
/** [gw, opp, venue, minutes, dc, start] — start (0/1) lisattiin #226-DC:ssa
 * kuudenneksi, jotta vanhat indeksit 0-4 pysyvat voimassa. */
export type DefconGwRow = [number, string, string, number, number, number?];

export interface DefconGwPlayer {
	id: number;
	code: number;
	web_name: string;
	team_short: string;
	pos: 'DEF' | 'MID' | 'FWD';
	price: number;
	owned_pct: number | null;
	threshold: number;
	games: number;
	/** Startit = hit_raten nimittaja (#226-DC). Puuttuu vanhasta payloadista. */
	starts?: number;
	hits: number;
	start_hits?: number;
	hit_rate: number;
	/** Vanha, pelattuihin otteluihin perustuva luku — lapinakyvyys, ei copyyn. */
	hit_rate_games?: number;
	pos_changed?: boolean;
	basis_pos?: 'DEF' | 'MID' | 'FWD';
	hit_rate_basis_pos?: number;
	dc_points: number;
	basis: string | null;
	per_gw: DefconGwRow[];
}

export interface DefconGwResponse {
	meta: {
		basis_season: string;
		basis_label: string;
		thresholds: Record<string, number>;
		/** Mitattu vastustajaefekti (28.7): nayta suoraan, ala myy kontekstia
		 * signaalina jota oma mittaus ei loyda. */
		opponent_effect?: { correlation: number; note: string };
		hit_rate_denominator?: 'starts' | 'games';
		season_rounds?: number;
		pool_min_starts?: number;
		pool_rule?: string;
		n_players: number;
	};
	players: DefconGwPlayer[];
}

export function fetchDefconGw(): Promise<DefconGwResponse> {
	return getTool('/api/fantasy/defcon-gw', 'defcon_gw');
}

/** Price watch- ja compare-luottamus samalle kolmiportaiselle asteikolle
 * kuin XpTable #33f (high=teal, med=neutraali, low=himmennetty). */
export function confBand(confidence: number): 'low' | 'med' | 'high' {
	if (confidence >= 0.85) return 'high';
	if (confidence >= 0.5) return 'med';
	return 'low';
}

/* ---------- Edge-sprint (contract-api 25.7): chip-EV ---------- */

export interface ChipWindow {
	gw: number;
	wc_ev: number;
	bb_ev: number;
	tc_ev: number;
	fh_ev: number;
	/** 'player_xp' (6 GW:n horisontti) | 'team_approx_cs_fdr' (GW7+). */
	basis: string;
}

export interface ChipBest {
	gw: number;
	ev: number;
	basis: string;
}

export interface ChipEvResponse {
	meta: {
		entry: number | null;
		mode: string;
		horizon_gws?: number[];
		generated_at?: string;
		notes?: string[];
		disclaimer?: string;
		[key: string]: unknown;
	};
	windows: ChipWindow[];
	/** Maskattuna {} (premium-teaser) — komponentti käsittelee puuttuvat avaimet. */
	best: Partial<Record<'wc' | 'bb' | 'tc' | 'fh', ChipBest>>;
}

/** entry valinnainen: annettuna käyttäjän runko, ilman mallin optimi-XI. */
export function fetchChipEv(entry?: number | null): Promise<ChipEvResponse> {
	const q = entry != null ? `?entry=${entry}` : '';
	return getTool(`/api/fantasy/chip-ev${q}`, 'chip_ev');
}

/* ---------- Edge-sprint: plan-chains (solver-light) ---------- */

export interface ChainMovePlayer {
	id: number;
	web_name: string;
	team_short: string;
	pos: Pos;
}

export interface ChainMove {
	out: ChainMovePlayer;
	in: ChainMovePlayer;
	gain_xp_remaining: number;
	hit: number;
}

export interface ChainGw {
	gw: number;
	moves: ChainMove[];
	roll_transfer: boolean;
	captain: { id: number; web_name: string; gw_xp: number };
	gw_xp: number;
	free_transfers_left: number;
	bank: number;
}

export interface ChainPlan {
	total_xp: number;
	net_ev_vs_hold: number;
	hits_taken: number;
	gws: ChainGw[];
	rationale: string;
}

export interface PlanChainsResponse {
	meta: {
		entry: number;
		start_gw: number;
		horizon: number;
		ft_assumed: number;
		beam_width?: number;
		generated_at?: string;
		timeout_degraded?: boolean;
		heuristic?: string;
		note?: string;
		[key: string]: unknown;
	};
	baseline_xp_no_transfers: number;
	plans: ChainPlan[];
}

export function fetchPlanChains(entry: number, horizon: number): Promise<PlanChainsResponse> {
	return getTool(`/api/fantasy/plan-chains?entry=${entry}&horizon=${horizon}`, 'plan_chains');
}

/** PI-16b (28.7): siirtoketjut tallennetulla draftilla, kun FPL ei ole vielä
 * julkaissut kokoonpanoja. */
export function fetchPlanChainsDraft(
	playerIds: number[],
	horizon: number
): Promise<PlanChainsResponse> {
	return getTool(
		`/api/fantasy/plan-chains?players=${playerIds.join(',')}&horizon=${horizon}`,
		'plan_chains'
	);
}

/* ---------- Edge-sprint: mini-league + H2H ---------- */

export interface LeagueRow {
	rank: number;
	last_rank: number;
	entry: number;
	entry_name: string;
	player_name: string;
	total: number;
	event_total: number;
}

export interface LeagueResponse {
	meta: { league_id: number; page: number; [key: string]: unknown };
	league: { id: number; name: string; created?: string };
	standings: LeagueRow[];
	has_next: boolean;
}

export function fetchLeague(leagueId: number): Promise<LeagueResponse> {
	return getTool(`/api/fantasy/league/${leagueId}`, 'league');
}

export interface H2hEntry {
	entry: number;
	team_name: string;
	xi_xp: number;
	players_matched: number;
	missing_ids: number[];
}

export interface H2hResponse {
	meta: { gw: number; method?: string; disclaimer?: string; [key: string]: unknown };
	entry_a: H2hEntry;
	entry_b: H2hEntry;
	p_a: number;
	p_draw_band: number;
	p_b: number;
}

export function fetchH2h(entryA: number, entryB: number): Promise<H2hResponse> {
	return getTool(`/api/fantasy/h2h?entry_a=${entryA}&entry_b=${entryB}`, 'h2h');
}

/* ---------- Edge-sprint: edge-mode (protect/climb) ---------- */

export type EdgeMode = 'protect' | 'climb';

export interface EdgeCaptainRow {
	id: number;
	web_name: string;
	team_short: string;
	pos: Pos;
	gw_xp: number;
	owned_pct: number;
	score: number;
	rationale: string;
}

export interface EdgePlayerRow {
	id: number;
	web_name: string;
	team_short: string;
	pos?: Pos;
	owned_pct: number;
	price?: number;
	xp_horizon_total?: number;
	rationale: string;
}

export interface EdgeResponse {
	meta: {
		entry: number;
		mode: EdgeMode;
		gw: number;
		overall_rank: number | null;
		formula?: string;
		disclaimer?: string;
		[key: string]: unknown;
	};
	captain_top5: EdgeCaptainRow[];
	differentials: EdgePlayerRow[];
	template_risks: EdgePlayerRow[];
}

export function fetchEdge(entry: number, mode: EdgeMode): Promise<EdgeResponse> {
	return getTool(`/api/fantasy/edge?entry=${entry}&mode=${mode}`, 'edge');
}

/* ---------- Edge-sprint: CSV-lataus (premium) ---------- */

/** Hakee xP-projektiot CSV:nä Bearer-headerilla ja käynnistää selainlatauksen.
 * Palauttaa null onnistuessa, virheviestin epäonnistuessa (inline-banneriin).
 *
 * eu=true → ';'-erotin ja pilkkudesimaalit. MIKSI: fi/eu-locale-Excel tulkitsee
 * pisteellisen desimaalin (1.10) päivämääräksi ja näyttää '####'. Oletus jää
 * pilkkuerottimeen, joka on oikea UK/US-Excelille, Sheetsille ja pandasille. */
export async function downloadXpCsv(eu = false): Promise<string | null> {
	try {
		const headers = await authHeaders();
		const q = eu ? '?sep=%3B' : '';
		const r = await fetch(`${API_BASE}/api/fantasy/xp.csv${q}`, { headers });
		if (!r.ok) {
			const detail = (await r.json().catch(() => null))?.detail;
			return typeof detail === 'string' && detail
				? detail
				: `Download failed (${r.status}). Please try again shortly.`;
		}
		const blob = await r.blob();
		// filename Content-Dispositionista jos saatavilla, muuten oletus
		const cd = r.headers.get('Content-Disposition') ?? '';
		const m = cd.match(/filename="([^"]+)"/);
		let name = m?.[1] ?? 'goaliq_xp.csv';
		if (eu) name = name.replace(/\.csv$/, '_eu.csv');
		const url = URL.createObjectURL(blob);
		const a = document.createElement('a');
		a.href = url;
		a.download = name;
		document.body.appendChild(a);
		a.click();
		a.remove();
		URL.revokeObjectURL(url);
		capture('xp_csv_downloaded', { source: 'pro_spa' });
		return null;
	} catch {
		return 'Could not reach the GoalIQ API. Please check your connection and try again.';
	}
}
