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
	/** 27.7 HORISONTTI: puuttuu kaukoriveiltä (tier="far") RAKENTEELLISESTI.
	 *  GW30:n CS-% heinäkuun arvioista olisi tarkkuuslupaus jota malli ei voi
	 *  pitää. Älä oleta tätä olevan — se on kontrakti, ei unohdus. */
	cs_pct?: number;
	/** 27.7: near = mallin täysi ulostulo, far = pelkkä kalenterin vaikeus.
	 *  Eksplisiittinen kenttä eikä gw-vertailusta johdettu, jottei
	 *  rehellisyyssääntöä lasketa uudelleen kahdessa paikassa.
	 *  Defensiivinen: vanha payload ei tuo kenttää → kohdellaan near-rivinä. */
	tier?: 'near' | 'far';
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

/** Edge-sprint addendum: edellisen kauden per-90-vauhdit (julkista historiaa).
 * Avainnimet eivät ole vielä lukossa → avoin kartta, UI poimii tuntemansa. */
export interface LastSeasonPer90 {
	[key: string]: number | null | undefined;
}

/** Edge-sprint addendum: edellisen kauden julkaistu historia. FREE-dataa
 * (historia on julkista) — ei premium-gatea.
 *
 * Muoto ei ole vielä kontraktissa (contract-data.md:ssä ei ole addendum 2:ta):
 * lähdeartefakti data/fpl_prev_baselines_2526.json käyttää nimiä
 * {total_points, acc:{mins, xg, xa, saves, bonus, n60}}, kun taas suunniteltu
 * payload-muoto on litteä {minutes, starts, goals, assists, xg, xa, cs,
 * points, per90}. Tyyppi hyväksyy molemmat: UI lukee kenttä kerrallaan
 * aliaksineen ja jättää puuttuvat renderöimättä. */
export interface LastSeason {
	/** Kausileima jos payload tuo sen (esim. '2025/26'). */
	season?: string;
	/** Valmiit per-90-vauhdit. Puuttuessa UI laskee ne minuuteista. */
	per90?: LastSeasonPer90 | null;
	/** Vaihtoehtoinen sijainti kertymille (prev-baselines-artefaktin muoto). */
	acc?: Record<string, unknown> | null;
	[key: string]: unknown;
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
	/** UX-palaute-erä 25.7 (contract-data.md luku 5): FPL:n VIRALLISET
	 * saatavuus/kurinpitokentät bootstrapista — faktaa, EI mallin estimaattia.
	 * Kaikki defensiivisiä (vanha payload ei tuo).
	 * status: a=available, d=doubtful, i=injured, s=suspended,
	 * u=unavailable, n=not available. */
	status?: string;
	/** FPL:n virallinen news-teksti (max ~140 merkkiä; '' = ei lippuja). */
	news?: string;
	/** FPL:n chance_of_playing_next_round (0-100 tai null). */
	chance_next?: number | null;
	/** Bootstrapin yellow_cards. HUOM: pre-seasonissa FPL:n bootstrap kantaa
	 * vielä EDELLISEN kauden lukemia (tunnistus:
	 * meta.data_coverage.baseline_mode === 'prev_season_archive'). */
	yellows?: number;
	/** Hinta miljoonina (bootstrapin now_cost / 10). */
	price?: number;
	/** Edge-sprint addendum: edellisen kauden historia. Puuttuu / null =
	 * osiota ei renderöidä lainkaan. */
	last_season?: LastSeason | null;
	/** false = pelaaja EI ole mukana projektiossa (esim. i/u/n-status tai
	 * muuten poissuljettu) → xP on merkityksetön, kortti piilottaa sen.
	 * Puuttuu vanhasta payloadista → tulkitaan mukana olevaksi. */
	in_projection?: boolean;
	/** 'unavailable' = FPL:n saatavuuslippu, 'below_min_xp' = alle
	 * xP-kynnyksen. Vain excluded[]-riveillä. */
	excluded_reason?: string;
}

/** Player card / haku: rivi voi olla projektiosta TAI excluded[]-listasta.
 * Poissuljetuilla riveillä ei ole mallilukuja lainkaan (ei xmins, xP eikä
 * gameweeks), joten ne ovat tässä tyypissä valinnaisia — UI:n on vartioitava
 * ne ennen käyttöä. XpPlayer on sellaisenaan tämän alityyppi. */
export type CardPlayer = Omit<
	XpPlayer,
	'xmins' | 'xp_per_gw' | 'xp_horizon_total' | 'gameweeks'
> &
	Partial<Pick<XpPlayer, 'xmins' | 'xp_per_gw' | 'xp_horizon_total' | 'gameweeks'>>;

export interface XpMeta {
	available: boolean;
	next_gameweek?: number;
	horizon_gw?: number;
	/** #143-katvealueraportti; baseline_mode === 'prev_season_archive'
	 * = pre-season (mm. yellows on vielä edellisen kauden lukema). */
	data_coverage?: { baseline_mode?: string; [key: string]: unknown };
	[key: string]: unknown;
}

export interface XpResponse {
	meta: XpMeta;
	players: XpPlayer[];
	/** Edge-sprint addendum 2: FPL-listatut pelaajat jotka EIVÄT ole
	 * projektiossa (saatavuuslippu i/s/u/n tai xP alle kynnyksen). Erillinen
	 * lista players[]:n rinnalla → rankkauslistat eivät näe näitä, mutta haku
	 * löytää heidät. Defensiivinen: vanha payload ei tuo kenttää. */
	excluded?: CardPlayer[];
}

export interface FantasyResponse {
	meta: {
		available: boolean;
		/** Montako GW:tä TÄSSÄ vastauksessa on (ei mitä tiedostossa olisi). */
		horizon_gw?: number;
		/** Montako olisi saatavilla kauden loppuun. */
		horizon_max?: number;
		/** near/far-raja DATASSA eikä kovakoodattuna: jos raja muuttuu,
		 *  molemmat pinnat seuraavat itsestään. */
		near_horizon_gw?: number;
		/** Pakollinen label kaukoriveille — näytetään sellaisenaan. */
		far_basis_label?: string;
		next_gameweek?: number | null;
		[key: string]: unknown;
	};
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

/** 27.7: koko kausi haetaan KERRAN, ja GW-välivalitsin aggregoi klientissä.
 *
 *  Miksi ei per-väli-kutsua: välin raahaaminen on jatkuva ele. Jos jokainen
 *  muutos olisi API-kutsu, se tuntuisi rikkinäiseltä ja kuormittaisi Renderiä
 *  turhaan. Koko kausi on ~149 kB (ticker ei kasva horisontin mukana), joten
 *  yksi haku riittää.
 *
 *  Oletusnäkymä on silti lähihorisontti — laajennus on työkalu jonka käyttäjä
 *  ottaa käyttöön, ei seinä johon hän törmää. */
export function fetchFantasy(): Promise<FantasyResponse> {
	fantasyP ??= getJson<FantasyResponse>('/api/fantasy?horizon=all');
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

// ---------------------------------------------------------------------------
// Ottelu-ennuste (28.7). Mitattu ennen tätä: /api/predict, /api/teams ja
// /api/leagues olivat mobiilissa mutta EIVÄT lainkaan webissä, vaikka
// goaliq.app:n 181 staattista ennustesivua ovat suurin indeksoitu pintamme
// eikä niistä ollut mihinkään konvertoida. Backend oli valmis ja julkinen.
// ---------------------------------------------------------------------------

export interface LeaguesResponse {
	top5_xg_leagues: string[];
	other_leagues: string[];
	uefa_tournaments: string[];
	[key: string]: unknown;
}

export interface TeamsResponse {
	leagues: string[];
	teams: string[];
	n_matches?: number;
}

export interface PredictScore {
	score: string;
	probability: number;
}

export interface PredictResponse {
	home_team: string;
	away_team: string;
	expected_goals_home: number;
	expected_goals_away: number;
	p_home_win: number;
	p_draw: number;
	p_away_win: number;
	fair_odds_home?: number;
	fair_odds_draw?: number;
	fair_odds_away?: number;
	p_over_2_5?: number;
	p_under_2_5?: number;
	p_btts_yes?: number;
	p_btts_no?: number;
	top_scores: PredictScore[];
	[key: string]: unknown;
}

let leaguesP: Promise<LeaguesResponse> | null = null;
export function fetchLeagues(): Promise<LeaguesResponse> {
	leaguesP ??= getJson<LeaguesResponse>('/api/leagues');
	return leaguesP;
}

/** Joukkuelista per liiga. Cachetetaan liigakohtaisesti: valitsimen vaihto on
 *  jatkuva ele eikä sen kuulu maksaa uutta hakua joka kerta. */
const teamsCache = new Map<string, Promise<TeamsResponse>>();
export function fetchTeams(league: string): Promise<TeamsResponse> {
	const key = league;
	if (!teamsCache.has(key)) {
		teamsCache.set(
			key,
			getJson<TeamsResponse>(`/api/teams?leagues=${encodeURIComponent(league)}`)
		);
	}
	return teamsCache.get(key)!;
}

/** Ottelu-ennuste. `top_n` seuraa premium-tilaa samalla tavalla kuin mobiilissa
 *  (free 5, premium 10) — pariteetti on tässä sääntö, ei mieltymys. */
export async function predictMatch(
	league: string,
	home: string,
	away: string,
	topN: number
): Promise<PredictResponse> {
	const headers = await authHeaders();
	const r = await fetch(`${API_BASE}/api/predict`, {
		method: 'POST',
		headers: { ...headers, 'Content-Type': 'application/json' },
		body: JSON.stringify({
			home_team: home,
			away_team: away,
			leagues: [league],
			top_n: topN
		})
	});
	if (!r.ok) {
		const detail = (await r.json().catch(() => null))?.detail;
		throw new Error(
			typeof detail === 'string' && detail
				? detail
				: `Prediction failed (${r.status}). Please try again shortly.`
		);
	}
	return r.json() as Promise<PredictResponse>;
}

export interface StandingsRow {
	position: number;
	team_name: string;
	team_short_name?: string | null;
	team_crest?: string | null;
	played_games: number;
	won: number;
	draw: number;
	lost: number;
	goals_for: number;
	goals_against: number;
	goal_difference: number;
	points: number;
}

export interface StandingsResponse {
	league: string;
	season: string;
	rows: StandingsRow[];
}

export interface FixtureRow {
	date: string;
	datetime: string;
	home_team: string;
	away_team: string;
	home_team_short_name?: string | null;
	away_team_short_name?: string | null;
	matchday?: number | null;
}

export interface FixturesResponse {
	league: string;
	days: number;
	fixtures: FixtureRow[];
}

export function fetchStandings(league: string, season: string): Promise<StandingsResponse> {
	return getJson<StandingsResponse>(
		`/api/standings?league=${encodeURIComponent(league)}&season=${encodeURIComponent(season)}`
	);
}

/** Heitetään `unsupported`-lippu 404:lle, jotta UI voi sanoa TOTUUDEN.
 *  Kaikilla liigoilla ei ole otteluohjelmasyötettä lainkaan (esim. League One,
 *  Veikkausliiga), ja "please try again shortly" on niille suora valhe:
 *  odottaminen ei auta koskaan. */
export class LeagueUnsupportedError extends Error {
	unsupported = true;
}

export async function fetchFixtures(league: string, days: number): Promise<FixturesResponse> {
	const headers = await authHeaders();
	const path = `/api/fixtures?league=${encodeURIComponent(league)}&days=${days}`;
	const r = await fetch(`${API_BASE}${path}`, { headers });
	if (r.status === 404 || r.status === 403) {
		throw new LeagueUnsupportedError('no fixture feed for this league');
	}
	if (!r.ok) throw new Error(`${path} -> HTTP ${r.status}`);
	return r.json() as Promise<FixturesResponse>;
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

// Defensiivinen: projektiosta poissuljetulla rivillä gameweeks voi puuttua.
export function gwXp(p: XpPlayer, gw: number | undefined): number {
	if (gw == null) return 0;
	return p.gameweeks?.find((g) => g.gw === gw)?.xp ?? 0;
}

export function gwOpponents(p: XpPlayer, gw: number | undefined): string {
	if (gw == null) return '';
	const g = p.gameweeks?.find((x) => x.gw === gw);
	if (!g || g.opponents.length === 0) return 'Blank';
	return g.opponents.map((o) => `${o.opp} (${o.venue})`).join(', ');
}

/** Per-pelaajan DefCon-erittely (Villen pyynto 25.7). FREE: FPL:n omaa
 * otteludataa. cbi/tkl/rec puuttuvat vanhemmista snapshoteista -> optionaalisia. */
export interface DefconGame {
	round: number | null;
	opp: string;
	venue: string;
	minutes: number;
	dc: number;
	hit: boolean;
	cbi?: number;
	tkl?: number;
	rec?: number;
}
export interface DefconPlayerResponse {
	meta: {
		window: number;
		threshold: number | null;
		points_per_hit: number;
		counts_recoveries: boolean;
		components_available: boolean;
		basis_label?: string | null;
		is_prev_season_basis?: boolean | null;
		rule_note: string;
	};
	player: { id: number; web_name: string; team_short: string; pos: string };
	games: DefconGame[];
	totals: {
		games: number;
		hits: number;
		hit_rate_pct: number;
		dc_per_game: number;
		defcon_points: number;
		cbi_per_game?: number;
		tkl_per_game?: number;
		rec_per_game?: number;
	};
}

export async function fetchPlayerDefcon(
	id: number,
	window = 10
): Promise<DefconPlayerResponse> {
	return getJson<DefconPlayerResponse>(`/api/fantasy/defcon/${id}?window=${window}`);
}
