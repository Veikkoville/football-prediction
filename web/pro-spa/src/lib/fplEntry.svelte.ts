/** #66 VAIHE 2: FPL entry-ID:n tili-taso persistointi (cross-device).
 *
 * Kirjautuneena entry-ID luetaan profiles.fpl_entry_id:sta (esitäyttö +
 * automaattinen rate-team-ajo, sama UX-kaava kuin mobiilin #64) ja
 * tallennetaan ONNISTUNEESTA rate/plan-hausta security definer -RPC:llä
 * `set_fpl_entry_id` (kirjoittaa vain oman rivin fpl_entry_id:n — ei
 * UPDATE-policya profiles-tauluun, is_premium-polku koskematon).
 *
 * Uloskirjautuneena EI persistointia (tietoinen rajaus: tili-taso on
 * cross-device-arvo; localStorage-fallback skipattu promptin luvalla).
 *
 * Fail-safe: profiililuku/-kirjoitusvirhe (esim. migraatio ei vielä ajettu)
 * EI kaada työkaluja — manuaalisyöttö toimii kuten ennen. Deploy-järjestys
 * on siksi vapaa.
 *
 * Kenttä on JAETTU RateTeamin ja TransferPlannerin kesken (yksi entry-ID
 * koko työkalusetille, kuten mobiilissa).
 */
import { supabase } from './supabase';
import { auth } from './auth.svelte';

const VALID = /^\d{1,10}$/;

export const fplEntry = $state({
	/** Jaettu kenttäarvo (RateTeam + TransferPlanner bindaavat tähän). */
	entry: '',
	/** Profiiliin tallennettu ID (null = ei tallessa). */
	savedEntry: null as string | null,
	/** "Remember my team" — oletus PÄÄLLÄ (kuten mobiilissa). */
	remember: true,
	/** Minkä user-id:n profiili on jo luettu (kerran per kirjautuminen). */
	loadedForUser: null as string | null,
	/** true = tallennettu ID luettu → RateTeam ajaa itsensä kerran. */
	autoRunPending: false
});

/** Lataa kirjautuneen käyttäjän tallennettu entry-ID (kerran per user). */
export async function loadProfileEntry(): Promise<void> {
	const user = auth.user;
	if (!user || fplEntry.loadedForUser === user.id) return;
	fplEntry.loadedForUser = user.id;
	try {
		const { data, error } = await supabase
			.from('profiles')
			.select('fpl_entry_id')
			.eq('id', user.id)
			.limit(1);
		if (error) return; // fail-safe (esim. sarake puuttuu ennen migraatiota)
		const v = data?.[0]?.fpl_entry_id;
		if (v != null && VALID.test(String(v))) {
			fplEntry.savedEntry = String(v);
			if (!fplEntry.entry) fplEntry.entry = String(v);
			fplEntry.autoRunPending = true;
		}
	} catch {
		// fail-safe: ei kaada työkaluja
	}
}

/** Tallenna onnistuneesta rate/plan-hausta (kirjautuneena + remember). */
export async function persistEntry(id: number): Promise<void> {
	if (!auth.user || !fplEntry.remember) return;
	try {
		const { error } = await supabase.rpc('set_fpl_entry_id', { entry: id });
		if (!error) fplEntry.savedEntry = String(id);
	} catch {
		// fail-safe
	}
}

/** Remember-toggle: pois → tyhjennä profiilista; päälle → tallenna validi. */
export async function toggleRemember(): Promise<void> {
	fplEntry.remember = !fplEntry.remember;
	if (!auth.user) return;
	try {
		if (!fplEntry.remember) {
			const { error } = await supabase.rpc('set_fpl_entry_id', { entry: null });
			if (!error) fplEntry.savedEntry = null;
		} else if (VALID.test(fplEntry.entry.trim())) {
			await persistEntry(Number(fplEntry.entry.trim()));
		}
	} catch {
		// fail-safe
	}
}

/** Forget saved team: tyhjennä profiilista + kentästä. */
export async function forgetEntry(): Promise<void> {
	fplEntry.entry = '';
	fplEntry.autoRunPending = false;
	if (!auth.user) {
		fplEntry.savedEntry = null;
		return;
	}
	try {
		const { error } = await supabase.rpc('set_fpl_entry_id', { entry: null });
		if (!error) fplEntry.savedEntry = null;
	} catch {
		fplEntry.savedEntry = null; // UI-tila nollataan silti (fail-safe)
	}
}
