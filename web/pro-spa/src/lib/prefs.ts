/** Watchlist (V3) + kauden tavoite (V4), cross-device. Mobiilin
 * lib/fplPrefs.ts -vastine — sama synkkakaava kuin draftilla: lokaali on
 * totuus kirjautumattomalle, kirjautuneella uudempi aikaleima voittaa.
 * Palvelinpuoli: profiles.fpl_prefs + set_fpl_prefs() (20260730001500). */
import { supabase } from './supabase';
import { fetchOwnProfileRow, invalidateProfileRow } from './profileRow';

const KEY = 'goaliq.fplPrefs';
const TS_KEY = 'goaliq.fplPrefs.updatedAt';

export const WATCHLIST_FREE_LIMIT = 3;
export const WATCHLIST_MAX = 50;

export interface SeasonObjective {
	kind: 'overall_rank';
	value: number;
}

export interface FplPrefs {
	watchlist: number[];
	objective: SeasonObjective | null;
}

export const EMPTY_PREFS: FplPrefs = { watchlist: [], objective: null };

function sanitize(raw: unknown): FplPrefs {
	const out: FplPrefs = { watchlist: [], objective: null };
	if (raw == null || typeof raw !== 'object') return out;
	const o = raw as { watchlist?: unknown; objective?: unknown };
	if (Array.isArray(o.watchlist)) {
		out.watchlist = o.watchlist
			.filter((v): v is number => typeof v === 'number' && Number.isInteger(v) && v > 0)
			.slice(0, WATCHLIST_MAX);
	}
	const obj = o.objective as { kind?: unknown; value?: unknown } | null;
	if (
		obj != null &&
		typeof obj === 'object' &&
		obj.kind === 'overall_rank' &&
		typeof obj.value === 'number' &&
		Number.isInteger(obj.value) &&
		obj.value > 0
	) {
		out.objective = { kind: 'overall_rank', value: obj.value };
	}
	return out;
}

export function loadPrefs(): FplPrefs {
	try {
		const raw = localStorage.getItem(KEY);
		return raw ? sanitize(JSON.parse(raw)) : { ...EMPTY_PREFS };
	} catch {
		return { ...EMPTY_PREFS };
	}
}

export function savePrefs(prefs: FplPrefs, stamp = new Date().toISOString()): void {
	try {
		localStorage.setItem(KEY, JSON.stringify(prefs));
		localStorage.setItem(TS_KEY, stamp);
	} catch {
		/* fail-safe */
	}
}

interface RemotePrefs extends FplPrefs {
	updated_at: string;
}

async function fetchRemotePrefs(): Promise<RemotePrefs | null> {
	try {
		const { data: sess } = await supabase.auth.getSession();
		if (!sess.session) return null;
		// Perf 31.7: jaettu boot-select (profileRow), sama parsinta alla.
		const row = await fetchOwnProfileRow(sess.session.user.id);
		if (!row) return null;
		const raw = row.fpl_prefs;
		if (!raw || typeof raw !== 'object') return null;
		const updated = (raw as { updated_at?: unknown }).updated_at;
		if (typeof updated !== 'string') return null;
		return { ...sanitize(raw), updated_at: updated };
	} catch {
		return null;
	}
}

export async function pushRemotePrefs(prefs: FplPrefs): Promise<boolean> {
	try {
		const { data: sess } = await supabase.auth.getSession();
		if (!sess.session) return false;
		const { error } = await supabase.rpc('set_fpl_prefs', {
			prefs: { watchlist: prefs.watchlist, objective: prefs.objective }
		});
		if (!error) invalidateProfileRow(); // cache-rivissä on nyt vanha fpl_prefs
		return !error;
	} catch {
		return false;
	}
}

let pushTimer: ReturnType<typeof setTimeout> | null = null;
export function pushRemotePrefsSoon(prefs: FplPrefs, delayMs = 1500): void {
	if (pushTimer) clearTimeout(pushTimer);
	pushTimer = setTimeout(() => {
		pushTimer = null;
		void pushRemotePrefs(prefs);
	}, delayMs);
}

/** Palauttaa prefsit JOS kutsujan pitää korvata nykyinen tila. */
export async function syncPrefs(): Promise<FplPrefs | null> {
	const remote = await fetchRemotePrefs();
	const local = loadPrefs();
	const localTs = ((): string | null => {
		try {
			return localStorage.getItem(TS_KEY);
		} catch {
			return null;
		}
	})();
	const hasLocal = local.watchlist.length > 0 || local.objective != null;

	if (!remote) {
		if (hasLocal) void pushRemotePrefs(local);
		return null;
	}
	if (!hasLocal) {
		savePrefs(remote, remote.updated_at);
		return remote;
	}
	const remoteNewer = !localTs || Date.parse(remote.updated_at) > Date.parse(localTs);
	if (remoteNewer) {
		savePrefs(remote, remote.updated_at);
		return remote;
	}
	void pushRemotePrefs(local);
	return null;
}
