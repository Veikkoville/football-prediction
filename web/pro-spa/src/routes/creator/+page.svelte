<script lang="ts">
	/** CREATOR-VIEW (16.8.2026).
	 *
	 * 🔴 MIKSI TAMA SIVU ON OLEMASSA. Wolfy kysyi 16.8: "how would i know if
	 * someone has come from me or not? Will it show on my account?" Vastaus
	 * oli EI. Kolmelle luojalle oli luvattu 30 % ja annettu linkki, muttei
	 * mitaan tapaa nahda tuloksia - attribuutio eli Stripen tilausmetadatassa
	 * ja Villen selaimessa.
	 *
	 * 🔴 KAKSI ASIAA JOITA TAMA SIVU EI SAA TEHDA:
	 *
	 * 1. Nayttaa nollaa silloin kun lukua ei saatu luettua. `null` on
	 *    "emme saaneet luettua", `0` on "kukaan ei tullut linkistasi". Luoja
	 *    lopettaa linkin jakamisen jalkimmaisen perusteella.
	 * 2. Antaa `signupsin` nayttaa klikkimittarilta. Se on ALARAJA: ref
	 *    luetaan selaimesta rekisteroitymishetkella, joten X:n webviewissa
	 *    klikannut ja Chromessa rekisteroitynyt ei nay tassa lainkaan, eika
	 *    mobiiliapissa ole reittia refille ollenkaan. Rajoite on sivulla
	 *    itsellaan, ei alaviitteessa.
	 */
	import { onMount } from 'svelte';
	import {
		fetchCreatorReport,
		NotACreatorError,
		CreatorSignInRequiredError,
		type CreatorReport
	} from '$lib/api';
	import { auth } from '$lib/auth.svelte';
	import LoginBox from '$lib/components/LoginBox.svelte';

	let report = $state<CreatorReport | null>(null);
	let view = $state<'loading' | 'ready' | 'signin' | 'not-creator' | 'error'>('loading');
	let message = $state('');
	let copied = $state(false);

	// Linkkivalitsin: luojat linkittavat siihen sivuun joka lukee parhaiten,
	// eivat SPA:han. ref-bridge.js kantaa refin hubista tanne, joten kaikki
	// nama toimivat - mutta vain jos ref on URLissa. Siksi sivu antaa valmiit
	// URLit eika pyyda luojaa rakentamaan niita itse.
	const TARGETS = [
		{ label: 'Free FPL tools', url: 'https://goaliq.app/fpl' },
		{ label: 'Front page', url: 'https://goaliq.app/' },
		{ label: "The model's own squad", url: 'https://goaliq.app/fpl/model-xi' },
		{ label: 'Match predictions and record', url: 'https://goaliq.app/predictions' },
		{ label: 'Premium tools (this site)', url: 'https://pro.goaliq.app/' }
	];
	let target = $state(TARGETS[0].url);

	const shareLink = $derived(
		report ? `${target}${target.includes('?') ? '&' : '?'}ref=${report.code}` : ''
	);

	const windowEnds = $derived(
		report
			? new Date(report.free_window.ends_utc).toLocaleString(undefined, {
					dateStyle: 'medium',
					timeStyle: 'short'
				})
			: ''
	);

	const checkedAt = $derived(
		report ? new Date(report.generated_at).toLocaleTimeString(undefined, { timeStyle: 'short' }) : ''
	);

	async function load() {
		view = 'loading';
		try {
			report = await fetchCreatorReport();
			view = 'ready';
		} catch (e) {
			report = null;
			if (e instanceof CreatorSignInRequiredError) {
				view = 'signin';
			} else if (e instanceof NotACreatorError) {
				view = 'not-creator';
				message = e.message;
			} else {
				view = 'error';
				message = e instanceof Error ? e.message : String(e);
			}
		}
	}

	async function copyLink() {
		try {
			await navigator.clipboard.writeText(shareLink);
			copied = true;
			setTimeout(() => (copied = false), 2000);
		} catch {
			// Clipboard voi olla estetty. Linkki on nakyvissa tekstina, joten
			// kopiointi on oikotie eika ainoa reitti.
			copied = false;
		}
	}

	onMount(load);

	// Kirjautuminen tapahtuu talla sivulla (LoginBox), joten haku on ajettava
	// uudelleen kun sessio ilmestyy. Ilman tata luoja kirjautuu ja jaa
	// tuijottamaan samaa kirjautumislomaketta.
	let lastUserId = $state<string | null>(null);
	$effect(() => {
		const id = auth.user?.id ?? null;
		if (id !== lastUserId) {
			lastUserId = id;
			if (id) void load();
			else if (view === 'ready' || view === 'not-creator') view = 'signin';
		}
	});
</script>

<svelte:head>
	<title>Creator dashboard | GoalIQ</title>
	<meta name="robots" content="noindex" />
</svelte:head>

<div class="shell">
	<header>
		<h1>Creator dashboard</h1>
		<p class="muted">
			Your own numbers for your own code. Nobody else can see them here and you cannot see
			anyone else's.
		</p>
	</header>

	{#if view === 'loading'}
		<p class="muted">Loading your numbers...</p>
	{:else if view === 'signin'}
		<div class="card">
			<p>
				Sign in with the account you told us about. If you have not made one yet, create it
				with the same email you applied with and we will link your code to it.
			</p>
			<LoginBox />
		</div>
	{:else if view === 'not-creator'}
		<div class="card">
			<h2>This account has no creator code</h2>
			<p>{message}</p>
			<p class="muted">
				Signed in as {auth.user?.email}. If that is the wrong account, sign out and use the
				one you applied with. The terms and the application form are on the
				<a href="https://goaliq.app/creators">creator program page</a>.
			</p>
		</div>
	{:else if view === 'error'}
		<div class="banner error">Could not load your numbers: {message}</div>
		<p><button class="secondary" onclick={load}>Try again</button></p>
	{:else if report}
		<p class="code-line">
			Your code: <strong>{report.code}</strong> &middot; {report.commission_pct}% of what your
			readers pay &middot; checked {checkedAt}
		</p>

		{#if report.free_window.active}
			<div class="banner window">
				Premium is free for everyone until {windowEnds}, so nobody is paying yet and paid
				subscriptions cannot move before then. Sign-ups are the only number that can change
				this month.
			</div>
		{/if}

		<div class="numbers">
			<div class="card num">
				<span class="label">Accounts tagged with your code</span>
				{#if report.signups === null}
					<b class="unknown">not available</b>
					<span class="muted">
						We could not read this just now. It is not zero, we simply did not get an
						answer. Reload in a minute.
					</span>
				{:else}
					<b>{report.signups}</b>
					<span class="muted">
						This is a floor, not a count of your clicks. The tag is read from the browser
						the link was opened in, so someone who opens it in the X app and signs up in
						Chrome is not in this number, and the mobile app does not carry it at all.
						The real figure is higher than this.
					</span>
				{/if}
			</div>

			<div class="card num">
				<span class="label">Paid subscriptions credited to you</span>
				{#if report.stamped === null}
					<b class="unknown">not available</b>
					<span class="muted">
						We could not read this just now. It is not zero. Reload in a minute.
					</span>
				{:else}
					<b>{report.stamped}</b>
					<span class="muted">
						This is the number commission is calculated from. It counts subscriptions
						carrying your code, whether the reader used the code at checkout or arrived
						through your link and paid full price later.
					</span>
				{/if}
			</div>
		</div>

		{#if report.statuses && Object.keys(report.statuses).length > 0}
			<div class="card">
				<h2>Those subscriptions by status</h2>
				<div class="table-wrap">
					<table>
						<thead><tr><th>Status</th><th>Count</th></tr></thead>
						<tbody>
							{#each Object.entries(report.statuses) as [status, n] (status)}
								<tr><td>{status}</td><td>{n}</td></tr>
							{/each}
						</tbody>
					</table>
				</div>
				<p class="muted">
					Commission follows completed payments. A refunded or charged back subscription
					does not stand, so a cancelled row here is not automatically money.
				</p>
			</div>
		{/if}

		<div class="card">
			<h2>Your link</h2>
			<p class="muted">
				Any GoalIQ page works. Pick the one that reads best for your audience and the tag
				travels with the reader from there into the tools.
			</p>
			<div class="picker">
				<label for="target">Page</label>
				<select id="target" bind:value={target}>
					{#each TARGETS as t (t.url)}
						<option value={t.url}>{t.label}</option>
					{/each}
				</select>
			</div>
			<p class="link"><code>{shareLink}</code></p>
			<p>
				<button class="primary" onclick={copyLink}>{copied ? 'Copied' : 'Copy link'}</button>
			</p>
			<p class="muted">
				Your discount code <strong>{report.code}</strong> is a second, separate way in: a
				reader who types it at checkout is credited to you even if they never touched your
				link. Say it is an affiliate link, whatever your platform calls it.
			</p>
		</div>

		<div class="card limits">
			<h2>What this page cannot see</h2>
			<ul>
				<li>
					<strong>Clicks.</strong> We do not track them. The first thing we can see is an
					account being created.
				</li>
				<li>
					<strong>A reader who switches browser.</strong> Opened in one, signed up in
					another, and the two are not connected. That reader is missing from the sign-up
					number even though your code brought them.
				</li>
				<li>
					<strong>App Store and Google Play.</strong> Those purchases do not go through our
					checkout, so we cannot see where they came from. Send people to the site.
				</li>
				<li>
					<strong>Who they are.</strong> By design. You get totals, never emails or names.
				</li>
			</ul>
			<p class="muted">
				If you think someone is missing, tell us and we will check it by hand. The
				<a href="https://goaliq.app/creators">full terms</a> cover payouts: commission builds
				up from your first referral and the first payouts go out at gameweek 19, against your
				invoice.
			</p>
		</div>

		<p><button class="secondary" onclick={load}>Refresh</button></p>
	{/if}
</div>

<style>
	.shell {
		max-width: 860px;
		margin: 0 auto;
		padding: var(--s-4);
	}
	header {
		margin-bottom: var(--s-6);
	}
	.code-line {
		margin: 0 0 var(--s-4);
	}
	.banner.window {
		background: rgba(245, 197, 66, 0.1);
		border: 1px solid rgba(245, 197, 66, 0.42);
		color: var(--text);
		margin-bottom: var(--s-4);
	}
	.numbers {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
		gap: var(--s-4);
		margin-bottom: var(--s-4);
	}
	.num {
		display: flex;
		flex-direction: column;
		gap: var(--s-2);
	}
	.num .label {
		font-size: var(--step--1);
		color: var(--text-muted);
	}
	.num b {
		font-size: var(--step-3);
		line-height: 1;
		color: var(--accent);
	}
	/* Tuntematon luku EI saa nayttaa mittarilta: eri vari, eri koko, sanat
	   eika numero. */
	.num b.unknown {
		font-size: var(--step-1);
		color: var(--text-muted);
	}
	.card {
		margin-bottom: var(--s-4);
	}
	.card h2 {
		margin-top: 0;
	}
	.picker {
		display: flex;
		align-items: center;
		gap: var(--s-2);
		flex-wrap: wrap;
		margin-bottom: var(--s-3);
	}
	.link code {
		display: block;
		overflow-wrap: anywhere;
		background: var(--surface-2);
		border: 1px solid var(--border);
		padding: var(--s-2) var(--s-3);
	}
	.limits ul {
		margin: 0 0 var(--s-3);
		padding-left: 1.2em;
	}
	.limits li {
		margin-bottom: var(--s-2);
	}
</style>
