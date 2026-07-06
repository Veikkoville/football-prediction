<script lang="ts">
	import '$lib/theme.css';
	import { onMount } from 'svelte';
	import { initAnalytics, capture } from '$lib/analytics';
	import { initAuth } from '$lib/auth.svelte';

	let { children } = $props();

	onMount(() => {
		initAnalytics();
		// Web-funnel (#12-pariteetti): sivulataus kerran per lataus
		capture('pro_page_viewed', undefined, 'page_viewed');
		void initAuth();
	});
</script>

{@render children()}
