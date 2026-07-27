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
		return { ok: true, lockedAt: String(data) };
	} catch (e) {
		return { ok: false, reason: 'network', message: (e as Error)?.message ?? 'unknown' };
	}
}

export async function loadDecisions(gw?: number): Promise<StoredDecision[]> {
	try {
		let q = supabase
			.from('fpl_decisions')
			.select('gw,kind,model_choice,user_choice,followed,deadline_utc,locked_at')
			.order('gw', { ascending: false });
		if (gw != null) q = q.eq('gw', gw);
		const { data, error } = await q;
		if (error || !data) return [];
		return data as StoredDecision[];
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
