/** UX-palaute-erä (25.7): jaettu draft-storage.
 *
 * Sama localStorage-avain jota RateTeam-draft on käyttänyt 24.7 alkaen
 * (draft-persist) — nyt myös Fit checkerin "Save as draft" kirjoittaa tähän
 * ja RateTeam hydratoi siitä. Tallennetaan VAIN pelaaja-ID:t; oliot
 * resolvoidaan aina tuoreesta xP-poolista (hinnat eivät jäädy, poistuneet
 * putoavat pois). Fail-safe: storage-virhe ei koskaan kaada työkaluja.
 *
 * 26.7 (Villen pyyntö): draft synkataan tilin kautta, jotta webissä ja apissa
 * on SAMA joukkue. Kanoninen muoto on litteä ID-lista molemmilla alustoilla —
 * mobiilin positiokartta johdetaan poolista, koska pelaajan `pos` tulee sieltä
 * joka tapauksessa. Palvelinpuoli: profiles.fpl_draft + set_fpl_draft()-RPC
 * (migraatio 20260726210000, sama security-definer-kaava kuin fpl_entry_id).
 *
 * Kirjautumaton käyttö EI muutu: localStorage on yhä ainoa totuus, ja landing
 * saa pitää "no sign-in needed" -lupauksensa.
 */
import { supabase } from './supabase';

export const DRAFT_LS_KEY = 'goaliq.fplDraftPicks';
/** Lokaalin tallennuksen aikaleima — synkan konfliktinratkaisu vertaa tähän. */
export const DRAFT_TS_KEY = 'goaliq.fplDraftPicks.updatedAt';

export interface RemoteDraft {
	ids: number[];
	updated_at: string;
}

function isIdList(v: unknown): v is number[] {
	return (
		Array.isArray(v) &&
		v.length <= 15 &&
		v.every((x) => typeof x === 'number' && Number.isInteger(x) && x > 0)
	);
}

export function loadDraftIds(): number[] | null {
	try {
		const raw = localStorage.getItem(DRAFT_LS_KEY);
		if (!raw) return null;
		const parsed: unknown = JSON.parse(raw);
		if (isIdList(parsed)) return parsed;
	} catch {
		/* fail-safe */
	}
	return null;
}

/** Lokaalin draftin aikaleima ISO-muodossa (null = ei koskaan tallennettu). */
export function loadDraftUpdatedAt(): string | null {
	try {
		return localStorage.getItem(DRAFT_TS_KEY);
	} catch {
		return null;
	}
}

/** Palauttaa true jos tallennus onnistui (false = storage estetty/täynnä). */
export function saveDraftIds(ids: number[], stamp = new Date().toISOString()): boolean {
	try {
		localStorage.setItem(DRAFT_LS_KEY, JSON.stringify(ids));
		localStorage.setItem(DRAFT_TS_KEY, stamp);
		return true;
	} catch {
		return false;
	}
}

/** Tilin draft, tai null jos kirjautumaton / ei tallennettu / virhe. */
export async function fetchRemoteDraft(): Promise<RemoteDraft | null> {
	try {
		const { data: sess } = await supabase.auth.getSession();
		if (!sess.session) return null;
		const { data, error } = await supabase
			.from('profiles')
			.select('fpl_draft')
			.eq('id', sess.session.user.id)
			.limit(1);
		if (error || !data || data.length === 0) return null;
		const raw = (data[0] as { fpl_draft?: unknown }).fpl_draft;
		if (!raw || typeof raw !== 'object') return null;
		const obj = raw as { ids?: unknown; updated_at?: unknown };
		if (!isIdList(obj.ids) || typeof obj.updated_at !== 'string') return null;
		return { ids: obj.ids, updated_at: obj.updated_at };
	} catch {
		// Vanha skeema (sarake puuttuu) tai verkkovirhe → synkka on no-op,
		// lokaali draft toimii ennallaan.
		return null;
	}
}

/** Kirjoita draft tilille. Palauttaa false jos ei kirjautunut / virhe. */
export async function pushRemoteDraft(ids: number[]): Promise<boolean> {
	try {
		const { data: sess } = await supabase.auth.getSession();
		if (!sess.session) return false;
		const { error } = await supabase.rpc('set_fpl_draft', { draft: { ids } });
		return !error;
	} catch {
		return false;
	}
}

let pushTimer: ReturnType<typeof setTimeout> | null = null;
/** Debounced push — pick-muutoksia tulee useita peräkkäin (raahaus, apply). */
export function pushRemoteDraftSoon(ids: number[], delayMs = 1500): void {
	if (pushTimer) clearTimeout(pushTimer);
	pushTimer = setTimeout(() => {
		pushTimer = null;
		void pushRemoteDraft(ids);
	}, delayMs);
}

/** Synkkaa lokaalin ja tilin draftin. Uudempi aikaleima voittaa.
 *
 * Palauttaa ID-listan JOS kutsujan pitää korvata nykyinen draft (tili oli
 * edellä), muuten null. Aikaleima tulee molemmissa suunnissa palvelimelta
 * kirjoitushetkellä, joten laitteiden kellopoikkeama ei ratkaise voittajaa
 * kuin lokaalin oman tallennuksen osalta.
 */
export async function syncDraft(): Promise<number[] | null> {
	const remote = await fetchRemoteDraft();
	const localIds = loadDraftIds();
	const localTs = loadDraftUpdatedAt();

	if (!remote) {
		// Tilillä ei ole draftia → nosta lokaali sinne (jos sellainen on).
		if (localIds && localIds.length > 0) void pushRemoteDraft(localIds);
		return null;
	}
	if (!localIds || localIds.length === 0) {
		saveDraftIds(remote.ids, remote.updated_at);
		return remote.ids;
	}
	// Ilman lokaalia leimaa (ennen 26.7. tallennettu draft) tili voittaa vain
	// jos listat eroavat — muuten turha uudelleenrenderöinti.
	const remoteNewer = !localTs || Date.parse(remote.updated_at) > Date.parse(localTs);
	if (remoteNewer) {
		if (remote.ids.join(',') === localIds.join(',')) return null;
		saveDraftIds(remote.ids, remote.updated_at);
		return remote.ids;
	}
	if (remote.ids.join(',') !== localIds.join(',')) void pushRemoteDraft(localIds);
	return null;
}
