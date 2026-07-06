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
	subLoading: false
});

export async function initAuth(): Promise<void> {
	const { data } = await supabase.auth.getSession();
	applySession(data.session?.user ?? null);
	auth.sessionResolved = true;
	supabase.auth.onAuthStateChange((_event, session) => {
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
	if (!u) auth.sub = undefined;
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
		auth.sub = null;
	} finally {
		auth.subLoading = false;
	}
}

export async function accessToken(): Promise<string | null> {
	const { data } = await supabase.auth.getSession();
	return data.session?.access_token ?? null;
}
