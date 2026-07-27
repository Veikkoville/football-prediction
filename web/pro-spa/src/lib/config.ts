/** GoalIQ Pro SPA — julkiset konfiguraatioarvot.
 *
 * KAIKKI arvot tässä ovat selainturvallisia (anon key + PostHog-token on
 * suunniteltu selaimessa eläviksi; mobiiliappi shippaa samat). Salaisuudet
 * (Stripe secret, Supabase service key) elävät VAIN backendissä —
 * checkout kulkee POST /api/web/checkout -endpointin kautta.
 *
 * Buildissa ylikirjoitettavissa Vite-enveillä (VITE_*).
 */
/** 27.7: oma domain jaetun `*.onrender.com`-alidomainin tilalle.
 *
 * DNA:n nimipalvelu palautti NXDOMAINin koko `onrender.com`-vyöhykkeelle →
 * SPA:n data-haut JA `POST /api/web/checkout` kaatuivat operaattorin
 * käyttäjillä. Kirjautuminen toimi (Supabase resolvoituu normaalisti), joten
 * premium-asiakas näki tyhjän tuotteen virhebannerilla — ja checkout oli poikki.
 *
 * `api.goaliq.app` on Cloudflaren proxyn takana, joten klientti ei koskaan
 * resolvoi `onrender.com`ia. Proxy (oranssi pilvi) on pakollinen: DNS-only-CNAME
 * seuraisi CNAME-ketjua estettyyn vyöhykkeeseen eikä korjaisi mitään. */
export const API_BASE =
	import.meta.env.VITE_API_BASE ?? 'https://api.goaliq.app';

export const SUPABASE_URL =
	import.meta.env.VITE_SUPABASE_URL ?? 'https://bhcgommvjlhqcktrbtxf.supabase.co';

export const SUPABASE_ANON_KEY =
	import.meta.env.VITE_SUPABASE_ANON_KEY ??
	'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImJoY2dvbW12amxocWNrdHJidHhmIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzgxNDg3MTcsImV4cCI6MjA5MzcyNDcxN30.0_3Yf84Lu34W9HIaWv7or9p7Yko9fofNT5MDmmo-1WU';

// PostHog-projekti 427890, US Cloud (sama kuin mobiili + #12 server-side)
export const POSTHOG_KEY =
	import.meta.env.VITE_POSTHOG_KEY ?? 'phc_ASmq5P9R5goGTDxze3GkXHJqU6RsvMCNqunSVBMgGkn7';
export const POSTHOG_HOST =
	import.meta.env.VITE_POSTHOG_HOST ?? 'https://us.i.posthog.com';

export const DISCLAIMER =
	'GoalIQ model expected points: a model prediction, not betting advice, ' +
	'and not a gambling service.';
