/** UX-palaute-erä (25.7): jaettu draft-storage.
 *
 * Sama localStorage-avain jota RateTeam-draft on käyttänyt 24.7 alkaen
 * (draft-persist) — nyt myös Fit checkerin "Save as draft" kirjoittaa tähän
 * ja RateTeam hydratoi siitä. Tallennetaan VAIN pelaaja-ID:t; oliot
 * resolvoidaan aina tuoreesta xP-poolista (hinnat eivät jäädy, poistuneet
 * putoavat pois). Fail-safe: storage-virhe ei koskaan kaada työkaluja.
 */
export const DRAFT_LS_KEY = 'goaliq.fplDraftPicks';

export function loadDraftIds(): number[] | null {
	try {
		const raw = localStorage.getItem(DRAFT_LS_KEY);
		if (!raw) return null;
		const parsed: unknown = JSON.parse(raw);
		if (Array.isArray(parsed) && parsed.every((v) => typeof v === 'number')) {
			return parsed as number[];
		}
	} catch {
		/* fail-safe */
	}
	return null;
}

/** Palauttaa true jos tallennus onnistui (false = storage estetty/täynnä). */
export function saveDraftIds(ids: number[]): boolean {
	try {
		localStorage.setItem(DRAFT_LS_KEY, JSON.stringify(ids));
		return true;
	} catch {
		return false;
	}
}
