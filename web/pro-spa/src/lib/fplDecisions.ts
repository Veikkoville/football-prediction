/**
 * FM-silmukan päätöskirjaus (web). Mobiilin `lib/fplDecisions.ts` -vastine.
 *
 * Määrittely: goaliq-app/cos-reports/team-manager-fm-loop-maarittely-2026-07-27.md
 * Palvelinpuoli: `fpl_decisions` + `log_fpl_decision()` (migraatio 20260727220000).
 *
 * Säännöt ovat TÄSMÄLLEEN samat kuin mobiilissa, tarkoituksella: silmukan
 * lopputulos ei saa riippua siitä kummalla laitteella päätös kirjattiin.
 * Jos muutat toista, muuta molemmat.
 */

import { supabase } from './supabase';

export type DecisionKind = 'transfer' | 'captain' | 'chip' | 'lineup';

export interface DecisionInput {
	gw: number;
	kind: DecisionKind;
	modelChoice: Record<string, unknown>;
	userChoice: Record<string, unknown>;
	/** GW:n virallinen deadline (FPL-datasta). */
	deadlineUtc: string;
}

export type LogResult =
	| { ok: true; lockedAt: string }
	| { ok: false; reason: 'locked' | 'auth' | 'network'; message: string };

export interface StoredDecision {
	gw: number;
	kind: DecisionKind;
	model_choice: Record<string, unknown>;
	user_choice: Record<string, unknown>;
	followed: boolean;
	deadline_utc: string;
	locked_at: string;
	/** Beat the model V1 (29.7): backend-graderin tulos. NULL = ei vielä
	 *  gradattu. Optionaaliset: vanha skeema ei palauta kenttiä. */
	graded_at?: string | null;
	model_points?: number | null;
	user_points?: number | null;
	grade_note?: string | null;
}

/** Tuloskortin kausisumma gradatuista päätöksistä. delta > 0 = käyttäjä
 *  edellä. Vain rivit joissa MOLEMMAT puolet gradattiin — gradaamattomia ei
 *  arvata nollaksi vaan ne raportoidaan erikseen. SAMA logiikka kuin mobiilin
 *  lib/fplDecisions.ts:ssä: silmukan lopputulos ei saa riippua pinnasta. */
export interface SeasonScore {
	gradedCount: number;
	ungradableCount: number;
	userTotal: number;
	modelTotal: number;
	delta: number;
}

/** V2 GW-debrief: viimeisin kierros jolta on molemmin puolin gradattuja
 *  rivejä. delta > 0 = käyttäjä voitti kierroksen. SAMA logiikka kuin
 *  mobiilissa — UI kääntää lauseen deltasta, logiikka ei keksi narratiivia. */
export interface GwDebrief {
	gw: number;
	rows: StoredDecision[];
	userTotal: number;
	modelTotal: number;
	delta: number;
}

export function latestDebrief(rows: StoredDecision[]): GwDebrief | null {
	const graded = rows.filter(
		(r) =>
			r.graded_at != null &&
			typeof r.model_points === 'number' &&
			typeof r.user_points === 'number'
	);
	if (graded.length === 0) return null;
	const gw = Math.max(...graded.map((r) => r.gw));
	const gwRows = graded.filter((r) => r.gw === gw);
	let user = 0;
	let model = 0;
	for (const r of gwRows) {
		user += r.user_points as number;
		model += r.model_points as number;
	}
	return {
		gw,
		rows: gwRows,
		userTotal: Math.round(user * 10) / 10,
		modelTotal: Math.round(model * 10) / 10,
		delta: Math.round((user - model) * 10) / 10
	};
}

export function seasonScore(rows: StoredDecision[]): SeasonScore {
	let user = 0;
	let model = 0;
	let graded = 0;
	let ungradable = 0;
	for (const r of rows) {
		if (r.graded_at == null || r.grade_note === 'kind_not_graded') continue;
		if (typeof r.model_points !== 'number') continue;
		if (typeof r.user_points !== 'number') {
			ungradable += 1;
			continue;
		}
		user += r.user_points;
		model += r.model_points;
		graded += 1;
	}
	return {
		gradedCount: graded,
		ungradableCount: ungradable,
		userTotal: Math.round(user * 10) / 10,
		modelTotal: Math.round(model * 10) / 10,
		delta: Math.round((user - model) * 10) / 10
	};
}

export function didFollowModel(
	modelChoice: Record<string, unknown>,
	userChoice: Record<string, unknown>
): boolean {
	try {
		return JSON.stringify(modelChoice) === JSON.stringify(userChoice);
	} catch {
		return false;
	}
}

/** Kirjaa päätös. Palauttaa aina rakenteisen tuloksen — ei koskaan heitä.
 *
 *  `reason:'locked'` on ODOTETTU lopputulos eikä virhe: se on koko mekanismin
 *  tarkoitus. UI kertoo sen rauhallisesti. */
export async function logDecision(input: DecisionInput): Promise<LogResult> {
	try {
		const followed = didFollowModel(input.modelChoice, input.userChoice);
		const { data, error } = await supabase.rpc('log_fpl_decision', {
			p_gw: input.gw,
			p_kind: input.kind,
			p_model_choice: input.modelChoice,
			p_user_choice: input.userChoice,
			p_followed: followed,
			p_deadline_utc: input.deadlineUtc
		});
		if (error) {
			const msg = error.message || '';
			if (/locked|deadline/i.test(msg)) return { ok: false, reason: 'locked', message: msg };
			if (/not authenticated|JWT|auth/i.test(msg))
				return { ok: false, reason: 'auth', message: msg };
			return { ok: false, reason: 'network', message: msg };
		}
		invalidateDecisions(); // uusi rivi kannassa → cache ei saa tarjoilla vanhaa listaa
		return { ok: true, lockedAt: String(data) };
	} catch (e) {
		return { ok: false, reason: 'network', message: (e as Error)?.message ?? 'unknown' };
	}
}

/** Perf 31.7: boot haki saman taulun kahdesti (BeatTheModel ilman gw:tä +
 *  WeeklyActions gw-suodattimella). Nyt yksi jaettu koko listan haku
 *  (single-flight + lyhyt TTL) ja gw-suodatus klientissä — rivejä on max
 *  muutama per GW, joten koko lista on aina pieni. Invalidointi:
 *  logDecision-onnistuminen + käyttäjävaihdos (cache on user-avaimellinen). */
const DECISIONS_TTL_MS = 60_000;
let decCacheUser: string | null = null;
let decCacheAt = 0;
let decCachePromise: Promise<StoredDecision[]> | null = null;

export function invalidateDecisions(): void {
	decCacheUser = null;
	decCachePromise = null;
}

async function fetchAllDecisions(): Promise<StoredDecision[]> {
	const { data, error } = await supabase
		.from('fpl_decisions')
		.select(
			'gw,kind,model_choice,user_choice,followed,deadline_utc,locked_at,' +
				'graded_at,model_points,user_points,grade_note'
		)
		.order('gw', { ascending: false });
	if (error || !data) return [];
	return data as unknown as StoredDecision[];
}

export async function loadDecisions(gw?: number): Promise<StoredDecision[]> {
	try {
		const { data: sess } = await supabase.auth.getSession();
		const uid = sess.session?.user.id ?? null;
		if (!uid) return []; // RLS palauttaisi tyhjän — säästetään roundtrip
		const stale = Date.now() - decCacheAt > DECISIONS_TTL_MS;
		if (!decCachePromise || decCacheUser !== uid || stale) {
			decCacheUser = uid;
			decCacheAt = Date.now();
			decCachePromise = fetchAllDecisions();
		}
		const rows = await decCachePromise;
		return gw != null ? rows.filter((r) => r.gw === gw) : rows;
	} catch {
		return [];
	}
}

/** Klientin ennakkotarkistus VAIN UI:ta varten — kanta on totuus. */
export function isOpenForLogging(deadlineUtc: string | null | undefined): boolean {
	if (!deadlineUtc) return false;
	const t = Date.parse(deadlineUtc);
	return Number.isFinite(t) && Date.now() < t;
}

/** V2 päätöspäiväkirjan what-if -rivi: mitä poikkeaminen mallista maksoi
 *  tai tuotti. delta = user - model, eli > 0 = OMA kutsusi voitti.
 *
 *  EI UUTTA LASKENTAA: luvut ovat samat graderin kirjoittamat pisteet joita
 *  tuloskortti summaa. Tämä on esitys, ei toinen totuus.
 *
 *  SAMA logiikka kuin mobiilin lib/fplDecisions.ts:ssä — silmukan lopputulos
 *  ei saa riippua pinnasta (kuten seasonScore ja latestDebrief). */
export interface WhatIfRow {
	gw: number;
	kind: DecisionKind;
	delta: number;
	/** Valmis lause ilman etumerkkiä; UI lisää pisteet ja värin. */
	text: string;
}

function choiceName(c: Record<string, unknown>): string | null {
	const name = c?.name;
	if (typeof name === 'string' && name) return name;
	const out = c?.out;
	const inn = c?.in;
	if (typeof out === 'string' && typeof inn === 'string') return `${out} → ${inn}`;
	return null;
}

/** Gradatut päätökset joissa POIKETTIIN mallista, uusin ensin.
 *
 *  Vain poikkeamat: jos seurasit mallia, vastakohtaa ei ole olemassa eikä
 *  what-if-lausetta voi muodostaa rehellisesti.
 *
 *  Järjestys on kierros laskevasti EIKÄ |delta| laskevasti: suurin ensin
 *  olisi kertomuksen kalastelua, ja sama kortti näyttäisi eri tarinan sen
 *  mukaan kumpi suunta sattuu olemaan isompi. */
export function whatIfRows(rows: StoredDecision[], limit = 5): WhatIfRow[] {
	const out: WhatIfRow[] = [];
	for (const r of rows) {
		if (r.graded_at == null) continue;
		if (typeof r.model_points !== 'number' || typeof r.user_points !== 'number') continue;
		if (r.followed) continue;
		const modelName = choiceName(r.model_choice);
		const userName = choiceName(r.user_choice);
		const delta = Math.round((r.user_points - r.model_points) * 10) / 10;
		let text: string;
		if (r.kind === 'captain') {
			text =
				userName && modelName
					? `captained ${userName} over ${modelName}`
					: modelName
						? `picked a different captain to ${modelName}`
						: 'picked a different captain';
		} else {
			text = modelName ? `skipped ${modelName}` : 'made a different move';
		}
		out.push({ gw: r.gw, kind: r.kind, delta, text });
	}
	out.sort((a, b) => b.gw - a.gw);
	return out.slice(0, limit);
}
