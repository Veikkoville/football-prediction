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
import { fetchOwnProfileRow, invalidateProfileRow } from './profileRow';

export const DRAFT_LS_KEY = 'goaliq.fplDraftPicks';
/** Lokaalin tallennuksen aikaleima — synkan konfliktinratkaisu vertaa tähän. */
export const DRAFT_TS_KEY = 'goaliq.fplDraftPicks.updatedAt';

export interface RemoteDraft {
	ids: number[];
	updated_at: string;
	captain_id?: number | null;
	vice_id?: number | null;
}

/** Kapteeni/vice (29.7, skeema 20260729233000). Oma avain jotta vanha
 *  ids-muoto ei muutu; sama kaava kuin mobiilin lib/fplDraft.ts:ssä. */
export const CAP_LS_KEY = 'goaliq.fplDraftCaptaincy';

export interface Captaincy {
	captain_id: number | null;
	vice_id: number | null;
}

export function loadCaptaincy(): Captaincy {
	try {
		const raw = localStorage.getItem(CAP_LS_KEY);
		if (!raw) return { captain_id: null, vice_id: null };
		const p: unknown = JSON.parse(raw);
		const num = (v: unknown) =>
			typeof v === 'number' && Number.isInteger(v) && v > 0 ? v : null;
		const o = p as { captain_id?: unknown; vice_id?: unknown };
		return { captain_id: num(o?.captain_id), vice_id: num(o?.vice_id) };
	} catch {
		return { captain_id: null, vice_id: null };
	}
}

export function saveCaptaincy(c: Captaincy): void {
	try {
		localStorage.setItem(CAP_LS_KEY, JSON.stringify(c));
	} catch {
		/* fail-safe */
	}
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

/**
 * Tyhjentää selaimeen jääneen draftin.
 *
 * 🔴 Villen havainto 16.8: uusi tili näytti valmiin joukkueen jota käyttäjä ei
 * ollut koskaan valinnut (halvin laillinen 15, Fit checkerin muotoinen XI +
 * penkki). Syy on `syncDraft`issa: tilillä ei ole draftia → lokaali työnnetään
 * sinne. Selaimeen jäänyt kokeilu muuttui siis rekisteröityessä "sinun
 * joukkueeksesi" ja seurasi tiliä puhelimeen asti.
 *
 * Tyhjä tili on ainoa puolustettava aloitustila: viikkosilmukka neuvoo
 * kapteenia ja siirtoja, ja neuvo joukkueesta jota kukaan ei ole valinnut on
 * pahempi kuin ei neuvoa lainkaan.
 */
export const DRAFT_CLEARED_EVENT = 'goaliq:draft-cleared';

export function clearDraft(): void {
	try {
		localStorage.removeItem(DRAFT_LS_KEY);
		localStorage.removeItem(DRAFT_TS_KEY);
		localStorage.removeItem(CAP_LS_KEY);
	} catch {
		/* fail-safe */
	}
	// 🔴 Pelkka storagen tyhjennys EI riita, ja tama on mitattu: Ville loi
	// uuden tilin korjauksen jalkeen ja sai yha saman joukkueen. Draft
	// hydratoidaan KERRAN sivulatauksella, joten `picks` jaa komponentin
	// muistiin senkin jalkeen kun storage on tyhja - ja persistointi-efekti
	// kirjoittaa ne sielta takaisin seka localStorageen etta tilille.
	// Tyhjennys on siis kaksiosainen: levy ja nakyma.
	try {
		window.dispatchEvent(new CustomEvent(DRAFT_CLEARED_EVENT));
	} catch {
		/* fail-safe (SSR / ei window) */
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
		// Perf 31.7: jaettu boot-select (profileRow) korvasi oman
		// yhden sarakkeen kyselyn — sama fail-safe-parsinta alla.
		const row = await fetchOwnProfileRow(sess.session.user.id);
		if (!row) return null;
		const raw = row.fpl_draft;
		if (!raw || typeof raw !== 'object') return null;
		const obj = raw as {
			ids?: unknown;
			updated_at?: unknown;
			captain_id?: unknown;
			vice_id?: unknown;
		};
		if (!isIdList(obj.ids) || typeof obj.updated_at !== 'string') return null;
		const num = (v: unknown) =>
			typeof v === 'number' && Number.isInteger(v) && v > 0 ? v : null;
		return {
			ids: obj.ids,
			updated_at: obj.updated_at,
			captain_id: num(obj.captain_id),
			vice_id: num(obj.vice_id)
		};
	} catch {
		// Vanha skeema (sarake puuttuu) tai verkkovirhe → synkka on no-op,
		// lokaali draft toimii ennallaan.
		return null;
	}
}

/** Kirjoita draft tilille. Palauttaa false jos ei kirjautunut / virhe.
 *
 *  Kapteeni/vice lähetetään VAIN jos pelaaja on ids-listassa — kanta hylkäisi
 *  muuten koko draftin (fpl_draft_is_valid), ja vanhentunut kapteeni ei saa
 *  estää joukkueen tallennusta. */
export async function pushRemoteDraft(ids: number[], captaincy?: Captaincy): Promise<boolean> {
	try {
		const { data: sess } = await supabase.auth.getSession();
		if (!sess.session) return false;
		const draft: Record<string, unknown> = { ids };
		const cap = captaincy?.captain_id;
		const vice = captaincy?.vice_id;
		if (cap != null && ids.includes(cap)) draft.captain_id = cap;
		if (vice != null && ids.includes(vice) && vice !== cap) draft.vice_id = vice;
		const { error } = await supabase.rpc('set_fpl_draft', { draft });
		if (!error) invalidateProfileRow(); // cache-rivissä on nyt vanha fpl_draft
		return !error;
	} catch {
		return false;
	}
}

let pushTimer: ReturnType<typeof setTimeout> | null = null;
/** Debounced push — pick-muutoksia tulee useita peräkkäin (raahaus, apply). */
export function pushRemoteDraftSoon(ids: number[], captaincy?: Captaincy, delayMs = 1500): void {
	if (pushTimer) clearTimeout(pushTimer);
	pushTimer = setTimeout(() => {
		pushTimer = null;
		void pushRemoteDraft(ids, captaincy);
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
	const localCap = loadCaptaincy();

	if (!remote) {
		// Tilillä ei ole draftia → nosta lokaali sinne (jos sellainen on).
		if (localIds && localIds.length > 0) void pushRemoteDraft(localIds, localCap);
		return null;
	}
	if (!localIds || localIds.length === 0) {
		saveDraftIds(remote.ids, remote.updated_at);
		saveCaptaincy({ captain_id: remote.captain_id ?? null, vice_id: remote.vice_id ?? null });
		return remote.ids;
	}
	// Ilman lokaalia leimaa (ennen 26.7. tallennettu draft) tili voittaa vain
	// jos listat eroavat — muuten turha uudelleenrenderöinti.
	const remoteNewer = !localTs || Date.parse(remote.updated_at) > Date.parse(localTs);
	if (remoteNewer) {
		saveCaptaincy({ captain_id: remote.captain_id ?? null, vice_id: remote.vice_id ?? null });
		if (remote.ids.join(',') === localIds.join(',')) return null;
		saveDraftIds(remote.ids, remote.updated_at);
		return remote.ids;
	}
	if (remote.ids.join(',') !== localIds.join(',')) void pushRemoteDraft(localIds, localCap);
	return null;
}
