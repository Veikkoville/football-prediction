// SPA-moodi (QUEUE #14 lukittu arkkitehtuuri): ei SSR:ää, kaikki data
// haetaan selaimessa (auth elää selaimessa, API on julkinen FastAPI).
export const ssr = false;
export const prerender = false;
export const csr = true;
