/** Jaettu profiles-rivin boot-luku (web-perf-audit 31.7 kohta 3).
 *
 * Boot teki kolme rinnakkaista yhden sarakkeen selectiä samaan omaan riviin
 * (fpl_draft / fpl_entry_id / fpl_prefs) — nyt ensimmäinen kutsuja laukaisee
 * yhden select('*'):n ja muut jakavat saman promisen. `select('*')` siksi,
 * ettei moduuli kytkeydy sarakenimiin: puuttuva sarake ei kaada koko hakua
 * (kutsujien fail-safe-polut hoitavat undefined-kentän kuten ennenkin).
 *
 * TÄRKEÄ RAJAUS: premium-totuus (auth.refreshSubscription: web_subscriptions
 * + profiles.is_premium) EI kulje tämän cachen kautta — maksajan näkymä ei
 * saa koskaan riippua stalesta rivistä (#51-F2).
 *
 * Staleness-kuri: jokainen oman rivin KIRJOITUS (set_fpl_draft,
 * set_fpl_entry_id, set_fpl_prefs) kutsuu invalidateProfileRow() onnistuessaan,
 * samoin kirjautumisen käyttäjävaihdos — seuraava lukija hakee tuoreen rivin.
 */
import { supabase } from './supabase';

let cacheUser: string | null = null;
let rowPromise: Promise<Record<string, unknown> | null> | null = null;

export function fetchOwnProfileRow(userId: string): Promise<Record<string, unknown> | null> {
	if (rowPromise && cacheUser === userId) return rowPromise;
	cacheUser = userId;
	rowPromise = (async () => {
		try {
			const { data, error } = await supabase
				.from('profiles')
				.select('*')
				.eq('id', userId)
				.limit(1);
			if (error || !data || data.length === 0) return null;
			return data[0] as Record<string, unknown>;
		} catch {
			return null; // fail-safe: kutsujat degradoituvat kuten omissa poluissaan
		}
	})();
	return rowPromise;
}

export function invalidateProfileRow(): void {
	cacheUser = null;
	rowPromise = null;
}
