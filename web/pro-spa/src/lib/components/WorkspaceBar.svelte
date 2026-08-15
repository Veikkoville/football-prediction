<script lang="ts">
	/**
	 * WorkspaceBar — pysyva GW- ja deadline-rivi (15.8.2026).
	 *
	 * MIKSI (kilpailija-analyysi, Villen paatos). FPL Roguen ylareunassa juoksee
	 * pysyva "PLANNING WORKSPACE · Gameweek 1 · DEADLINE Fri 21 Aug, 20:30 EEST".
	 * Meilla countdown oli VAIN landingilla, ja SPA:n oma "This week" -paneeli
	 * lupaa "what to do before the deadline" kertomatta milloin se deadline on.
	 * Mitattu selaimella 15.8: koko nakymassa ei ollut yhtaan kellonaikaa.
	 *
	 * Toinen puoli on tuoreusleima. Rogue nayttaa "FPL data checked 18:09", ja
	 * se on luottamussignaali jota emme antaneet lainkaan: sivuilla lukee
	 * "Updated 15 Aug" mutta ei kellonaikaa, joten kayttaja ei voi tietaa onko
	 * luku tuntia vai vuorokautta vanha.
	 *
	 * 🔴 AIKA RENDEROIDAAN SELAIMEN VYOHYKKEELLA, EI PALVELIMEN. Deadline tulee
	 * UTC:na. Jos naytettaisiin UTC ilman merkintaa, suomalainen lukija olisi
	 * kolme tuntia myohassa. `toLocaleString` ilman timeZone-parametria kayttaa
	 * kayttajan omaa vyohyketta, ja vyohykkeen lyhenne naytetaan mukana jottei
	 * lukijan tarvitse arvata kumpaa kelloa rivi tarkoittaa.
	 *
	 * Palkki ei renderoi mitaan ennen kuin data on: tyhja kuori jossa lukee
	 * "Deadline —" olisi huonompi kuin ei palkkia lainkaan, koska se nayttaisi
	 * rikkinaiselta juuri silla rivilla jonka tarkoitus on olla luotettava.
	 */
	import { onMount } from 'svelte';
	import { fetchFantasy } from '$lib/api';

	let gw = $state<number | null>(null);
	let deadline = $state<Date | null>(null);
	let checked = $state<Date | null>(null);

	onMount(async () => {
		try {
			const d = await fetchFantasy();
			const m = d?.meta ?? {};
			gw = typeof m.next_gameweek === 'number' ? m.next_gameweek : null;
			if (m.deadline_utc) {
				const t = new Date(m.deadline_utc);
				if (!isNaN(t.getTime())) deadline = t;
			}
			if (m.generated_at) {
				// generated_at tulee ilman vyohyketta ("2026-08-15T09:31:04").
				// Se on UTC, ja ilman Z:aa selain tulkitsisi sen PAIKALLISEKSI
				// ajaksi -> leima nayttaisi kolme tuntia liian tuoreelta.
				const raw = /[Z+]|-\d\d:\d\d$/.test(m.generated_at)
					? m.generated_at
					: `${m.generated_at}Z`;
				const t = new Date(raw);
				if (!isNaN(t.getTime())) checked = t;
			}
		} catch {
			// Palkki on lisatietoa, ei nakyma. Verkkovirhe ei saa nayttaa
			// mitaan, eika varsinkaan kaataa sivua.
		}
	});

	/** 🔴 KIELI on-GB, VYOHYKE kayttajan. `undefined`-locale kaytti selaimen
	 *  kielta, ja suomalaisella koneella rivi renderoitui "pe 21.8. klo 20.30"
	 *  — suomea englanninkielisessa tuotteessa. Mitattu lokaalisti 15.8.
	 *  Vyohyketta EI lukita: kellonajan pitaa olla kayttajan omaa aikaa,
	 *  muuten deadline on kolme tuntia vaarassa kohdassa. */
	const LOC = 'en-GB';

	const dl = $derived(
		deadline
			? deadline.toLocaleString(LOC, {
					weekday: 'short',
					day: 'numeric',
					month: 'short',
					hour: '2-digit',
					minute: '2-digit'
				})
			: null
	);
	/** Vyohykkeen lyhenne erikseen: toLocaleString ei anna sita samalla
	 *  kutsulla ilman etta koko muotoilu muuttuu. */
	const tz = $derived(
		deadline
			? (new Intl.DateTimeFormat(LOC, { timeZoneName: 'short' })
					.formatToParts(deadline)
					.find((p) => p.type === 'timeZoneName')?.value ?? '')
			: ''
	);
	const chk = $derived(
		checked
			? checked.toLocaleTimeString(LOC, { hour: '2-digit', minute: '2-digit' })
			: null
	);
	const mennyt = $derived(!!deadline && deadline.getTime() < Date.now());
</script>

{#if gw !== null || dl}
	<div class="wsbar">
		<span class="grp">
			{#if gw !== null}<b>Gameweek {gw}</b>{/if}
			{#if dl}
				<span class="lbl">{mennyt ? 'Deadline passed' : 'Deadline'}</span>
				<span class="val">{dl}{tz ? ` ${tz}` : ''}</span>
			{/if}
		</span>
		{#if chk}
			<span class="chk">Data checked {chk}</span>
		{/if}
	</div>
{/if}

<style>
	.wsbar {
		display: flex;
		flex-wrap: wrap;
		align-items: baseline;
		justify-content: space-between;
		gap: 6px 14px;
		padding: 7px 14px;
		border-bottom: 1px solid var(--line, #2a2724);
		background: var(--panel, #131110);
		font-size: 12px;
		letter-spacing: 0.04em;
	}
	.grp {
		display: flex;
		flex-wrap: wrap;
		align-items: baseline;
		gap: 6px 12px;
	}
	.wsbar b {
		color: var(--cream, #f3f2f2);
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.1em;
	}
	.lbl {
		color: var(--muted, #a8a29a);
		text-transform: uppercase;
		letter-spacing: 0.1em;
	}
	.val {
		color: var(--amber, #f5c542);
		font-weight: 600;
	}
	.chk {
		color: var(--faint, #7b756d);
	}
</style>
