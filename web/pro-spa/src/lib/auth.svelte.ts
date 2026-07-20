/** Auth + subscription-tila (Svelte 5 runes -store).
 *
 * Sessio elää supabase-js:n localStorage-persistenssissä (selviää
 * sivulatauksista, toisin kuin Streamlitin session_state). Premium-totuus:
 * web_subscriptions (oma rivi, RLS) TAI profiles.is_premium (mobiilitilaaja,
 * #7 cross-platform) — sama logiikka kuin Streamlitin auth.subscription().
 */
import { supabase } from './supabase';
import { capture, identifyUser, resetAnalytics } from './analytics';

export interface GiqUser {
	id: string;
	email: string;
}

export interface GiqSub {
	status: string;
	plan: string;
	current_period_end: string | null;
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
	if (u && u.id !== prevId) {
		identifyUser(u.id, u.email);
		auth.sub = undefined;
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
	const { data, error } = await supabase.auth.signUp({ email, password });
	if (error) return error.message;
	if (data.user) capture('signup_completed', undefined, 'signup');
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
	auth.user = null;
	auth.sub = undefined;
}

export async function refreshSubscription(): Promise<void> {
	const user = auth.user;
	if (!user) return;
	auth.subLoading = true;
	try {
		const { data: rows } = await supabase
			.from('web_subscriptions')
			.select('status, plan, current_period_end')
			.eq('user_id', user.id)
			.eq('status', 'active')
			.order('current_period_end', { ascending: false })
			.limit(1);
		if (rows && rows.length > 0) {
			auth.sub = rows[0] as GiqSub;
			return;
		}
		// Cross-platform (#7): mobiilitilaajan profiles.is_premium honoroituu
		const { data: prof } = await supabase
			.from('profiles')
			.select('is_premium')
			.eq('id', user.id)
			.limit(1);
		auth.sub =
			prof && prof.length > 0 && prof[0].is_premium
				? { status: 'active', plan: 'app', current_period_end: null }
				: null;
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
