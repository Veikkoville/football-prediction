/** Auth + subscription-tila (Svelte 5 runes -store).
 *
 * Sessio elää supabase-js:n localStorage-persistenssissä (selviää
 * sivulatauksista, toisin kuin Streamlitin session_state). Premium-totuus:
 * web_subscriptions (oma rivi, RLS) TAI profiles.is_premium (mobiilitilaaja,
 * #7 cross-platform) — sama logiikka kuin Streamlitin auth.subscription().
 */
import { supabase } from './supabase';
import { capture, identifyUser, resetAnalytics } from './analytics';
import { invalidateProfileRow } from './profileRow';
import { storedRef } from './billing';
import { clearDraft } from './draft';

export interface GiqUser {
	id: string;
	email: string;
}

export interface GiqSub {
	status: string;
	plan: string;
	current_period_end: string | null;
}

// P1-UX 6.8: viimeisin tunnettu sub-tila localStorageen ja optimistinen
// render heti bootissa — sub-rivihaku Supabasesta on kylmällä yhteydellä
// sekuntien RTT, ja tulos on lähes aina sama kuin edellisellä käynnillä.
// Taustahaku (refreshSubscription) korjaa jos tila muuttui. Stale-premium
// ei vuoda mitään: palvelin gateaa premium-datan access-tokenilla joka
// tapauksessa, UI-lukot ovat vain esitystapa.
const SUB_CACHE_KEY = 'giq:sub:v1';

// ---------------------------------------------------------------------------
// GW1-GW3 ILMAINEN IKKUNA (Villen paatos 16.8.2026)
//
// Ikkuna paattyy GW4:n deadlineen 12.9.2026 12:30 UTC (luettu FPL:n
// bootstrapista 16.8). Sama paivamaara elaa backendissa (api/premium.py) ja
// mobiilissa (lib/freePremiumWindow.ts).
//
// 🔴 Kaksi asiaa joita EI saa muuttaa:
//
// 1. Ikkuna ei kirjoita mitaan. Se ei aseta profiles.is_premiumia eika
//    luo web_subscriptions-rivia. 14.8:n arvio mittasi etta lipun
//    kaantaminen tekisi kayttajasta PYSYVAN premiumin: purkaminen on 100 %
//    webhook-riippuvaista, eika ilmaisikkunasta synny webhookia.
// 2. Ikkunan synteettinen sub EI saa paatya localStorage-cacheen. Cache
//    elaa ikkunan yli, joten cachetettu synteettinen tilaus nayttaisi
//    premiumia viela ikkunan sulkeuduttua. writeSubCache saa siksi nahda
//    VAIN todellisen tilauksen; ikkuna lisataan vasta muistiin.
export const FREE_PREMIUM_UNTIL = '2026-09-12T12:30:00Z';
const FREE_PREMIUM_UNTIL_MS = Date.parse(FREE_PREMIUM_UNTIL);

export function freePremiumWindowActive(now: Date = new Date()): boolean {
	if (Number.isNaN(FREE_PREMIUM_UNTIL_MS)) return false;
	return now.getTime() < FREE_PREMIUM_UNTIL_MS;
}

/** Ikkunan aikainen entitlement. `plan` on oma arvonsa, jotta UI voi kertoa
 *  rehellisesti mista oikeus tulee eika vaita ostettua tilausta. */
export function freeWindowSub(): GiqSub {
	return { status: 'active', plan: 'gw1-3-free', current_period_end: FREE_PREMIUM_UNTIL };
}

/** Todellinen tilaus voittaa; ikkuna taydentaa vain jos tilausta ei ole. */
function withFreeWindow(sub: GiqSub | null | undefined): GiqSub | null | undefined {
	if (sub) return sub;
	return freePremiumWindowActive() ? freeWindowSub() : sub;
}

function readSubCache(userId: string): GiqSub | null | undefined {
	try {
		const raw = localStorage.getItem(SUB_CACHE_KEY);
		if (!raw) return undefined;
		const parsed = JSON.parse(raw) as { userId?: string; sub?: GiqSub | null };
		// Cache on user-avaimellinen: toisen käyttäjän tila ei saa vuotaa
		// jaetulla koneella käyttäjävaihdoksessa.
		if (parsed.userId !== userId) return undefined;
		return parsed.sub === undefined ? undefined : parsed.sub;
	} catch {
		return undefined;
	}
}

function writeSubCache(userId: string, sub: GiqSub | null): void {
	try {
		localStorage.setItem(SUB_CACHE_KEY, JSON.stringify({ userId, sub }));
	} catch {
		/* private mode / quota: cache on vain optimointi */
	}
}

function clearSubCache(): void {
	try {
		localStorage.removeItem(SUB_CACHE_KEY);
	} catch {
		/* noop */
	}
}

// 'unknown' = alkutila ennen kuin getSession on ratkennut (ei väläytetä
// login-formia kirjautuneelle); sub 'loading' vastaavasti.
export const auth = $state({
	user: null as GiqUser | null,
	sessionResolved: false,
	sub: undefined as GiqSub | null | undefined,
	subLoading: false,
	// #150b: tultiinko reset-linkistä → UI avaa salasanan asetuksen (muuten
	// SPA-landing on mykkä). Hash luetaan moduulin latauksessa ENNEN kuin
	// supabase-client kuluttaa sen; PASSWORD_RECOVERY-event on varapolku.
	passwordRecovery:
		typeof window !== 'undefined' && window.location.hash.includes('type=recovery')
});

export async function initAuth(): Promise<void> {
	const { data } = await supabase.auth.getSession();
	applySession(data.session?.user ?? null);
	auth.sessionResolved = true;
	supabase.auth.onAuthStateChange((event, session) => {
		if (event === 'PASSWORD_RECOVERY') auth.passwordRecovery = true;
		applySession(session?.user ?? null);
	});
}

function applySession(u: { id: string; email?: string | null } | null): void {
	const prevId = auth.user?.id;
	auth.user = u ? { id: u.id, email: u.email ?? '' } : null;
	// Uloskirjautuminen pudottaa jaetun profiilirivin heti (hygienia jaetulla
	// koneella). Käyttäjävaihdos EI tarvitse invalidointia: cache on
	// user-avaimellinen, ja boot-polulla (undefined → user) invalidointi
	// aiheutti tuplahaun (draft ehti aloittaa ennen applySessionia).
	if (!u && prevId) {
		invalidateProfileRow();
		clearSubCache();
	}
	if (u && u.id !== prevId) {
		identifyUser(u.id, u.email);
		// P1-UX 6.8: cache-osuma renderöi entitlementin heti (premium-lohkot
		// auki / paywall ilman "Checking subscription…" -odotusta); verkkohaku
		// ajaa silti aina ja korjaa taustalla jos tila muuttui.
		auth.sub = withFreeWindow(readSubCache(u.id));
		void refreshSubscription();
	}
	if (!u) {
		auth.sub = undefined;
		auth.passwordRecovery = false;
	}
}

export async function signIn(email: string, password: string): Promise<string | null> {
	const { error } = await supabase.auth.signInWithPassword({ email, password });
	return error ? error.message : null;
}

export async function signUp(email: string, password: string): Promise<string | null> {
	// 🔴 Ref kiinnitetaan TILIIN, ei pelkastaan selaimeen (Villen havainto
	// 16.8: "kaikkihan avaa sen x:sta suoraan").
	//
	// X avaa linkit omassa sisaisessa selaimessaan, jonka muisti on eri kuin
	// Safarin tai Chromen. Pelkka localStorage tarkoitti etta luojan katsoja
	// klikkaa linkkia X:ssa, ref tallentuu siihen webviewiin, ja nelja
	// viikkoa myohemmin han maksaa oikealla selaimella - jolloin yhteys on
	// poikki. Selaimen muisti on vaara paikka nelja viikkoa kestavalle
	// attribuutiolle.
	//
	// Tili on oikea paikka, ja ajoitus osuu: GW1-GW3 ikkunan koko tarkoitus
	// on saada ihminen luomaan tili SAMASSA sessiossa jossa han klikkaa.
	// `options.data` kirjoittaa Supabasen `raw_user_meta_data`an, joten
	// uutta saraketta eika tuotantomigraatiota ei tarvita.
	const ref = storedRef();
	const { data, error } = await supabase.auth.signUp({
		email,
		password,
		...(ref ? { options: { data: { ref } } } : {})
	});
	if (error) return error.message;
	// 🔴 Uusi tili aloittaa TYHJÄNÄ. Ilman tätä `syncDraft` työntää selaimeen
	// jääneen kokeilun tuoreelle tilille, koska tilillä ei ole vielä omaa
	// draftia — ja viikkosilmukka alkaa neuvoa kapteenia joukkueeseen jota
	// käyttäjä ei ole valinnut. Havaittu 16.8 oikealla rekisteröitymisellä.
	clearDraft();
	if (data.user) capture('signup_completed', ref ? { ref } : undefined, 'signup');
	return null;
}

/** #101: kirjautumislinkki mailiin — guest-checkout-ostajan (ei salasanaa)
 * ja salasanansa unohtaneen sisäänpääsy. shouldCreateUser=false: linkki vain
 * olemassa oleville tileille (ei bottisignup-pintaa). */
export async function sendMagicLink(email: string): Promise<string | null> {
	const { error } = await supabase.auth.signInWithOtp({
		email,
		options: { shouldCreateUser: false, emailRedirectTo: window.location.origin }
	});
	return error ? error.message : null;
}

/** #150: salasanan reset-linkki mailiin (account-valikko). Linkki tuo takaisin
 * tähän SPA:han recovery-sessiolla → uusi salasana asetetaan SetPasswordilla
 * (#101-kaava). Supabase ei paljasta onko email olemassa. */
export async function sendPasswordReset(email: string): Promise<string | null> {
	const { error } = await supabase.auth.resetPasswordForEmail(email, {
		redirectTo: window.location.origin
	});
	return error ? error.message : null;
}

/** #101: salasanan asetus magic-linkillä kirjautuneelle (guest-checkout-tili
 * syntyy ilman salasanaa; mobiili-app kirjautuu email+salasanalla). */
export async function setPassword(password: string): Promise<string | null> {
	const { error } = await supabase.auth.updateUser({ password });
	return error ? error.message : null;
}

export async function signOut(): Promise<void> {
	await supabase.auth.signOut();
	resetAnalytics();
	// Eksplisiittinen clear: SIGNED_OUT-eventin applySession voi ajaa ennen
	// kuin auth.user on nollattu tässä → prevId-ehto ei ole luotettava polku.
	clearSubCache();
	auth.user = null;
	auth.sub = undefined;
}

export async function refreshSubscription(): Promise<void> {
	const user = auth.user;
	if (!user) return;
	auth.subLoading = true;
	try {
		// 26.7 PERF: nämä kaksi olivat SARJASSA (web_subscriptions → profiles),
		// ja mobiilitilaaja osuu AINA molempiin → kaksi peräkkäistä RTT:tä ennen
		// kuin premium-näkymä edes alkaa. Rinnakkain: hinta = yksi ylimääräinen
		// kevyt profiles-kysely web-tilaajalle, hyöty = yksi RTT pois kaikilta.
		const [{ data: rows }, { data: prof }] = await Promise.all([
			supabase
				.from('web_subscriptions')
				.select('status, plan, current_period_end')
				.eq('user_id', user.id)
				.eq('status', 'active')
				.order('current_period_end', { ascending: false })
				.limit(1),
			// Cross-platform (#7): mobiilitilaajan profiles.is_premium honoroituu
			supabase.from('profiles').select('is_premium').eq('id', user.id).limit(1)
		]);
		const realSub: GiqSub | null =
			rows && rows.length > 0
				? (rows[0] as GiqSub)
				: prof && prof.length > 0 && prof[0].is_premium
					? { status: 'active', plan: 'app', current_period_end: null }
					: null;
		// Vain onnistunut haku päivittää cachen — virhepolku ei saa jäädyttää
		// väärää tilaa levylle (#51-F2-periaate ulottuu cacheen).
		// 16.8: cacheen VAIN todellinen tilaus. Ikkunan synteettinen sub elaisi
		// cachessa ikkunan yli ja nayttaisi premiumia viela sen sulkeuduttua.
		writeSubCache(user.id, realSub);
		auth.sub = withFreeWindow(realSub);
	} catch {
		// #51-F2: transientti verkko/Supabase-virhe EI saa nollata premium-tilaa
		// (maksaja näkisi hetkellisen väärän paywallin, Hub 2,0 -tähden
		// #1-valitus). Pidetään edellinen tunnettu tila virheen yli.
	} finally {
		auth.subLoading = false;
	}
}

export async function accessToken(): Promise<string | null> {
	const { data } = await supabase.auth.getSession();
	return data.session?.access_token ?? null;
}
