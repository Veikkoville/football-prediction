<script lang="ts">
	import '$lib/theme.css';
	import { onMount } from 'svelte';
	import { initAnalytics, capture } from '$lib/analytics';
	import { initAuth } from '$lib/auth.svelte';
	import { captureRef } from '$lib/billing';
	import WorkspaceBar from '$lib/components/WorkspaceBar.svelte';

	let { children } = $props();

	onMount(() => {
		// 2.8 PERF: app.html:n boot-runko pois heti kun oikea sisältö on DOM:issa.
		document.getElementById('boot')?.remove();
		// 16.8: luojan ref talteen ENNEN mitään muuta. Se on poimittava heti
		// laskeutumisella, koska GW1-GW3 ilmaisikkunan aikana käyttäjä
		// rekisteröityy nyt ja maksaa vasta neljä viikkoa myöhemmin - siihen
		// asti tämä on ainoa jäljellä oleva yhteys luojaan.
		captureRef(window.location.search);
		initAnalytics();
		// Web-funnel (#12-pariteetti): sivulataus kerran per lataus.
		// 2.8.2026: src/srcp = landingin CTA-lahdetagi (ks. staattisten sivujen
		// CTA-snippet). goaliq.app on cookieless persistence:'memory' -tilassa,
		// joten distinct_id ei jatku domainien yli eika landing->pro-siirtymaa
		// voinut aiemmin laskea lainkaan. Nama propit antavat saapumisasteen
		// per CTA-paikka ilman evastetta. Puuttuvat kun kayttaja tuli suoraan.
		const q = new URLSearchParams(location.search);
		const src = q.get('src');
		const srcPage = q.get('srcp');
		const props: Record<string, string> = {};
		if (src) props.src = src;
		if (srcPage) props.src_page = srcPage;
		capture(
			'pro_page_viewed',
			Object.keys(props).length ? props : undefined,
			'page_viewed'
		);
		void initAuth();
	});
</script>

<!-- Tyotilapalkki ENNEN sisaltoa ja layoutissa eika sivulla: deadline on
     yhta relevantti jokaisella reitilla, ja sivukohtainen sijoitus olisi
     tarkoittanut etta uusi reitti unohtaa sen hiljaa. -->
<WorkspaceBar />

{@render children()}
