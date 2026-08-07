/** /spl-prerender (SEO, 7.8): tämä reitti on ainoa jonka crawlerin PITÄÄ
 * nähdä sisältöineen pro-originista — muu sovellus pysyy SPA:na (QUEUE #14
 * lukittu arkkitehtuuri, ssr=false juurilayoutissa). Reittikohtainen
 * override tuottaa build/spl.html:n, jonka Pages tarjoilee /spl:ään
 * fallback-index.html:n sijaan: otsikko, lede, disclaimer ja FAQ ovat
 * HTML:ssä ilman JS-ajoa. Data ($effect-fetchit) latautuu edelleen vain
 * selaimessa — prerender näyttää rehelliset tyhjät tilat, ei valelukuja.
 *
 * SSR-turvallisuus tarkistettu 7.8: +layout.svelte koskee selain-APIen
 * (document/localStorage) vain onMountissa, auth.svelte.ts lukee
 * localStoragea vain funktioissa ja window-guardilla, supabase-client
 * toimii Nodessa. */
export const prerender = true;
export const ssr = true;
