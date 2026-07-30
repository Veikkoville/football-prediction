import adapter from '@sveltejs/adapter-static';
import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

export default defineConfig({
	plugins: [
		sveltekit({
			compilerOptions: {
				// Force runes mode for the project, except for libraries. Can be removed in svelte 6.
				runes: ({ filename }) =>
					filename.split(/[/\\]/).includes('node_modules') ? undefined : true
			},

			// Staattinen export Cloudflare Pagesille (QUEUE #14 lukittu
			// arkkitehtuuri): prerender + SPA-fallback, ei palvelinruntimea.
			adapter: adapter({ fallback: 'index.html' }),

			// 30.7.2026 P0-insidentti: deploy-ikkunassa chunk-URL sai origin-
			// fallbackin (index.html) ja zone-edge cachetti sen IMMUTABLE-
			// headerilla → polku jäi pysyvästi rikki (musta sivu). appDir-
			// vaihto uudelleennimeää KAIKKI asset-polut → jokainen myrkytetty
			// edge-merkintä ohitetaan kerralla. Ei muuteta takaisin '_app':iin
			// ilman zone-purgea. Juurisyyn jatkotoimi: deploy-verify VAIN
			// pages.dev-deployment-URL:sta kunnes propagaatio valmis (ks.
			// muisti pro-spa-wrangler-deploy).
			appDir: '_app2'
		})
	]
});
