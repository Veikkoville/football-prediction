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

/** WHY-THIS-PICK -selitys. `drivers` voi olla tyhja: se on lisatieto, ei
 *  lauseen ehto. */
export interface XpWhy {
	sentence: string;
	drivers: string[];
	source: 'model' | 'template' | string;
}

export interface XpPlayer {
	id: number;
	web_name: string;
	team: string;
	team_short: string;
	pos: 'GKP' | 'DEF' | 'MID' | 'FWD';
	xmins: number;
	xp_per_gw: number;
	/** 5.8: pistevauhti 90 pelattua minuuttia kohden. `null` kun odotettuja
	 *  minuutteja on liian vahan jotta vauhti tarkoittaisi mitaan (ei 0).
	 *  Serve-timessa johdettu, defensiivinen: vanha payload ei tuo. */
	xp_per_90?: number | null;
	xp_horizon_total: number;
	gameweeks: XpGameweek[];
	components?: XpComponents;
	components_gw?: number;
	/** WHY-THIS-PICK (14.8): yhden lauseen selitys projektiolle.
	 *  PREMIUM-ONLY JA VAIN FPL — backend liittaa taman vain maskaamattomaan
	 *  vastaukseen (`api/main.py:3115`). `source: 'template'` ei ole vika vaan
	 *  tarkka mutta tylsa lause; UI renderoi molemmat lahteet samalla tavalla,
	 *  koska valikoiva piilottaminen tekisi provenienssilupauksesta valikoivan.
	 *  Defensiivinen: vanha payload ei tuo kenttaa. */
	why?: XpWhy;
	/** #33f: probabilistinen minuuttimalli (start-% 0-100) — defensiivinen. */
	predicted_starts?: number;
	minutes_confidence?: 'low' | 'med' | 'high';
	/** #143: estimaatin datapohja — defensiivinen (vanha payload ei tuo). */
	data_basis?: 'pl_history' | 'limited_history' | 'no_history';
	/** 4.8: mistä aloitus-tn TULEE kun se ei ole puhtaasti mallin laskema.
	 *  Payload on tuonut `override`-arvon 27.7. lähtien mutta UI ei näyttänyt
	 *  sitä missään — käsin nostettu projektio jota ei merkitä on täsmälleen
	 *  se asia joka syö "todennettava malli" -lupauksen. Defensiivinen. */
	minutes_source?: 'override' | 'price_prior' | 'price_blend';
	minutes_override_reason?: string;
	/** #147: koko nimi VAIN hakua varten — defensiivinen (vanha payload ei tuo). */
	full_name?: string;
	/** 16.8: minuuttipriori nojaa katkenneeseen kauteen (alle 1500 min viime
	 *  kaudella). KUVAILEVA: kertoo että arvio nojaa lyhyeen otokseen, EI
	 *  kumpaan suuntaan luku on väärässä. Kenttä on rivillä VAIN kun lippu on
	 *  päällä; defensiivinen, vanha payload ei tuo. */
	minutes_basis_flag?: 'short_season';
	/** 10.8: joukkueen luottamuslippu. Kenttä on rivillä VAIN kun joukkue on
	 *  liputettu (nousija tai poikkeuksellinen kausivaihtuvuus) — pelkkä
	 *  vaihtuvuusluku kuuluu työkalutaulukoihin, ei jokaisen rivin viereen.
	 *  KUVAILEVA: kertoo että luokitus nojaa heikompaan tietoon, EI kumpaan
	 *  suuntaan projektio liikkuu (kalibrointi kaatui 9.8: hyökkäys R² 0,000,
	 *  puolustus väärä merkki). Defensiivinen: vanha payload ei tuo. */
	team_flag?: 'promoted' | 'high_turnover';
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

/** Kevyt valitsinrivi (14.8). Vain julkista FPL-bootstrap-tietoa — EI
 *  yhtään mallin lukua. Muoto on tarkoituksella `SearchItem`-yhteensopiva. */
export interface XpPoolPlayer {
	id: number;
	web_name: string;
	team_short: string;
	pos: 'GKP' | 'DEF' | 'MID' | 'FWD';
	price?: number;
	/** Vain täysillä riveillä (haku koko nimellä). Kevyt rivi ei tuo. */
	full_name?: string;
}

export interface XpResponse {
	meta: XpMeta;
	players: XpPlayer[];
	/** 14.8: koko pelaajalista draft-valitsimelle. Maskattu teaser antaa
	 *  free-käyttäjälle 10 riviä joissa oli 0 maalivahtia, jolloin drafti ei
	 *  ollut täytettävissä lainkaan. Defensiivinen: vanha payload ei tuo. */
	pool?: XpPoolPlayer[];
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
		/** FPL:n virallinen GW-deadline ISO-muodossa. Tyypitetty 15.8, kun
		 *  tyotilapalkki alkoi kayttaa sita: se oli ennen vain
		 *  index-signaturen alla, eli tsc ei olisi huomannut kirjoitusvirhetta
		 *  kentan nimessa. */
		deadline_utc?: string | null;
		/** Milloin projektiodata rakennettiin. Nayttetaan tuoreusleimana. */
		generated_at?: string | null;
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

/** Draft-/lukitusvalitsimen pooli: täydet rivit ensin, sitten kevyet rivit
 *  niille joita täysissä ei ole (14.8).
 *
 *  MIKSI YHDISTETÄÄN eikä korvata: täydet rivit kantavat `full_name`-haun,
 *  joten pelkkä kevyen listan käyttö veisi koko nimellä hakemisen myös
 *  premium-käyttäjältä. Yhdistäminen antaa free-käyttäjälle täytettävän
 *  valitsimen ilman että premium-pinta menettää mitään.
 *
 *  Fallback `players` on tarkoituksellinen: jos backend ei vielä tuo poolia
 *  (vanha deploy), käytös on tasan entinen eikä valitsin kaadu. */
export function draftPool(d: XpResponse): XpPoolPlayer[] {
	const rows: XpPoolPlayer[] = [...(d.players ?? [])];
	const seen = new Set(rows.map((p) => p.id));
	for (const p of d.pool ?? []) {
		if (!seen.has(p.id)) rows.push(p);
	}
	return rows;
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
// SPL (RSL Fantasy, 7.8): sama payload-skeema kuin FPL, league=spl-avaimella.
// Oma /spl-reitti hakee nämä — FPL-polut ja -cachet eivät muutu.
// data_basis on SPL:ssä 'spl_history' | 'no_history' (tyyppiunioni alla ei
// kata sitä; SPL-sivu lukee kentän löyhästi eikä FPL-koodi näe SPL-rivejä).
// ---------------------------------------------------------------------------
let splFantasyP: Promise<FantasyResponse> | null = null;
let splXpP: Promise<XpResponse> | null = null;
let splXpAuthed = false;

export function fetchSplFantasy(): Promise<FantasyResponse> {
	splFantasyP ??= getJson<FantasyResponse>('/api/fantasy?league=spl&horizon=all');
	return splFantasyP;
}

export async function fetchSplXp(): Promise<XpResponse> {
	const headers = await authHeaders();
	const hasToken = 'Authorization' in headers;
	if (splXpP && (splXpAuthed || !hasToken)) return splXpP;
	splXpAuthed = hasToken;
	splXpP = fetch(`${API_BASE}/api/fantasy/xp?league=spl`, { headers }).then((r) => {
		if (!r.ok) throw new Error(`/api/fantasy/xp?league=spl -> HTTP ${r.status}`);
		return r.json() as Promise<XpResponse>;
	});
	return splXpP;
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
	/** 9.8.2026: luokitukset sovitetaan TULOKSIIN eivätkä näe siirtoikkunaa.
	 *  Suoraa korjausta yritettiin ja se ei validoitunut, joten mallia ei
	 *  säädetä — kerromme milloin luku nojaa vanhentuneeseen tietoon.
	 *  Kuvaileva, EI ennustava: älä esitä tätä vaikutusarviona. */
	data_confidence?: Record<string, TeamConfidence>;
	[key: string]: unknown;
}

export interface TeamConfidence {
	team: string;
	minutes_churn_pct: number | null;
	flag: string | null;
	note: string | null;
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
	totals: {
		xi_xp_horizon: number;
		optimal_xp_horizon: number;
		delta_xp: number;
		/** 29.7: onko vertailukohta todistettu optimi. Vanha deployattu API ei
		    palauta kenttaa -> undefined = "ei tietoa", portti reagoi vain falseen. */
		optimal_proven?: boolean;
	};
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

/** DefCon-live (2.8): oman kokoonpanon kertymä kesken kierroksen. */
export interface DefconLivePlayer {
	id: number;
	web_name: string;
	team_short: string | null;
	pos: string;
	squad_position: number | null;
	is_captain: boolean;
	minutes: number;
	defcon: number;
	/** null = maalivahti, ei DefConia */
	threshold: number | null;
	hit: boolean;
	remaining: number | null;
	eligible: boolean;
}

export interface DefconLiveResponse {
	meta: {
		/** false = esikausi tai kierrosten väli. Silloin EI renderöidä mitään. */
		available: boolean;
		gw: number | null;
		generated_at: string | null;
		thresholds: Record<string, number>;
		note: string;
	};
	players: DefconLivePlayer[];
}

export async function fetchDefconLive(entry: number): Promise<DefconLiveResponse> {
	return getJson<DefconLiveResponse>(`/api/fantasy/defcon-live?entry=${entry}`);
}

// ---------------------------------------------------------------------------
// Beat the Model V2 — Season race (13.8). Mallin lukittu rivi vs oma kausi.
// Luvut tulevat backendin gradaamasta immutable-lokista; klientti EI laske
// pisteitä (V1-tuloskortin linjaus — sama kaava kahdessa klientissä olisi
// tasan se rakenne josta 28.7 syntyi kaksi eri lukua mallin joukkueesta).
// ---------------------------------------------------------------------------
export interface ModelRaceAutosub {
	out: number;
	in: number;
	pos: number;
}

export interface ModelRaceGameweek {
	gw: number;
	model_points: number;
	fpl_average: number | null;
	/** null = kierrosta ei ole omassa historiassa (EI nolla — ks. backend). */
	your_points: number | null;
	diff: number | null;
	cumulative_diff: number | null;
	/** Premium-erittely; puuttuu kokonaan ilman premiumia. */
	model_captain_id?: number | null;
	model_captain_reason?: string;
	model_captain_points?: number;
	model_bench_points?: number;
	model_autosubs?: ModelRaceAutosub[];
	your_bench_points?: number;
	your_transfer_cost?: number;
}

export interface ModelRaceResponse {
	meta: {
		/** false = ensimmäistä gradausta ei ole vielä → näytä selite, älä lukuja. */
		available: boolean;
		graded_gws: number;
		compared_gws?: number;
		masked: boolean;
		model_plays_chips: boolean;
		note: string | null;
	};
	totals: { model: number; you: number | null; diff: number | null };
	gameweeks: ModelRaceGameweek[];
}

export async function fetchModelRace(entry?: number | null): Promise<ModelRaceResponse> {
	const q = entry != null ? `?entry=${entry}` : '';
	return getJson<ModelRaceResponse>(`/api/fantasy/model-race${q}`);
}

// ---------------------------------------------------------------------------
// MINI-LEAGUE-RIVAL — "Catch your rival" (13.8). Free = ero + P(catch),
// premium = differentiaalit + asemakohtainen suositus. Todennäköisyys tulee
// samasta koneistosta kuin /h2h; klientti ei laske mitään.
// ---------------------------------------------------------------------------
export type RivalStance = 'chase_steady' | 'chase_variance' | 'protect' | 'level';

export interface RivalDifferential {
	id: number;
	web_name: string;
	team_short: string;
	price: number;
	owned_pct: number;
	xp_horizon: number;
	/** Varianssikontribuutio: kuinka paljon pelaaja voi kääntää eroa. */
	swing: number;
	rival_owns: boolean;
}

export interface RivalResponse {
	meta: {
		gameweeks_left: number;
		method: string;
		masked: boolean;
		variance_mode_below: number;
		gw: number;
		generated_at: string | null;
		disclaimer: string;
	};
	gap: number;
	behind: boolean;
	p_catch: number;
	stance: RivalStance;
	/** Premium; puuttuu kokonaan ilman (backend maskaa). */
	differentials?: RivalDifferential[];
	you: { entry: number; team_name: string | null; xi_xp: number; players_matched: number };
	rival: { entry: number; team_name: string | null; xi_xp: number; players_matched: number };
}

// ---------------------------------------------------------------------------
// CREATOR-VIEW (16.8): luojan omat luvut omalla tokenilla. Wolfy kysyi
// "Will it show on my account?" ja vastaus oli EI. Backend rajaa vastauksen
// KUTSUJAN omaan koodiin (`raw_user_meta_data.creator_code`), joten tama
// klientti ei valitse mita se katsoo eika voi valita.
// ---------------------------------------------------------------------------

/** 🔴 `signups` ja `stamped` ovat `null` kun lukua EI SAATU LUETTUA. Se ei
 *  ole nolla: nolla on vaite "kukaan ei tullut linkistasi". Alaa renderoi
 *  nullia nollana missaan. */
export interface CreatorReport {
	code: string;
	signups: number | null;
	stamped: number | null;
	statuses: Record<string, number> | null;
	sources_ok: { supabase: boolean; stripe: boolean };
	commission_pct: number;
	free_window: { active: boolean; ends_utc: string };
	caveat: string;
	generated_at: string;
}

/** Kirjautunut, mutta tilia ei ole kytketty yhteenkaan koodiin. Oma luokkansa
 *  siksi etta se on ohje eika virhe: 403 on tassa normaali tila jokaiselle
 *  muulle kayttajalle kuin kolmelle luojalle. */
export class NotACreatorError extends Error {
	notCreator = true;
}

/** Ei kirjautunut (tai token vanhentunut). */
export class CreatorSignInRequiredError extends Error {
	signInRequired = true;
}

export async function fetchCreatorReport(): Promise<CreatorReport> {
	const headers = await authHeaders();
	if (!('Authorization' in headers)) throw new CreatorSignInRequiredError('sign in');
	const r = await fetch(`${API_BASE}/api/creator/report`, {
		headers,
		// Luvut ovat pieni luottamuksellinen taulukko jota luoja paivittaa
		// odottaessaan liiketta. Cachetettu vastaus nayttaisi pysahtyneelta.
		cache: 'no-store'
	});
	if (r.status === 401) throw new CreatorSignInRequiredError('sign in');
	if (r.status === 403) {
		const detail = (await r.json().catch(() => null))?.detail;
		throw new NotACreatorError(typeof detail === 'string' ? detail : 'not a creator account');
	}
	if (!r.ok) throw new Error(`/api/creator/report -> HTTP ${r.status}`);
	return r.json() as Promise<CreatorReport>;
}

export async function fetchRival(
	entry: number,
	rival: number,
	leagueId: number
): Promise<RivalResponse> {
	return getJson<RivalResponse>(
		`/api/fantasy/rival?entry=${entry}&rival=${rival}&league_id=${leagueId}`
	);
}
