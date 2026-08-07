/** /spl-prerender (7.8): poista app.html-templaten FPL-otsikko ja -kuvaus
 * prerenderoidusta build/spl.html:stä.
 *
 * Miksi: app.html:n <title> + meta description ovat SPA-fallbackin (kaikki
 * muut reitit) ainoa raaka-HTML-metadata eikä niitä voi poistaa sieltä —
 * mutta prerenderoidulla /spl:llä svelte:head TUO OMANSA, jolloin sivulle
 * jää kaksi titleä ja crawler poimii ensimmäisen (väärän, FPL:n).
 * SvelteKit ei dedupaa template-headia vastaan, joten siivous tehdään
 * tässä. og:*-tagit jätetään templatesta ennalleen (fallback-reittien
 * some-kortit riippuvat niistä; /spl:n oma og-kortti = jatkotyö).
 *
 * Portit (gate-substring-osuma on sokea -muistin mukaisesti): jokainen
 * poisto LASKETAAN ja lopputila varmistetaan — väärä määrä = exit 1, ei
 * hiljaista puolikorjausta. */
import { readFileSync, writeFileSync } from 'node:fs';

const PATH = new URL('../build/spl.html', import.meta.url);
const TEMPLATE_TITLE = '<title>GoalIQ Premium | FPL tools</title>';
const TEMPLATE_DESC_RE =
	/<meta\s+name="description"\s+content="FPL tools from a real match model:[^"]*"\s*\/>/;

let html = readFileSync(PATH, 'utf8');

const fail = (msg) => {
	console.error(`fix-spl-head: ${msg}`);
	process.exit(1);
};

const titleCount = (html.match(/<title>/g) ?? []).length;
if (titleCount !== 2) fail(`odotettiin 2 <title>-tagia ennen siivousta, oli ${titleCount}`);
if (!html.includes(TEMPLATE_TITLE)) fail('template-titleä ei löytynyt merkkijonona');
html = html.replace(TEMPLATE_TITLE, '');

if (!TEMPLATE_DESC_RE.test(html)) fail('template-descriptionia ei löytynyt');
html = html.replace(TEMPLATE_DESC_RE, '');

const after = {
	titles: (html.match(/<title>/g) ?? []).length,
	descs: (html.match(/name="description"/g) ?? []).length
};
if (after.titles !== 1) fail(`siivouksen jälkeen ${after.titles} titleä, odotettiin 1`);
if (after.descs !== 1) fail(`siivouksen jälkeen ${after.descs} descriptionia, odotettiin 1`);
if (!html.includes('<title>Saudi Pro League fantasy tools | GoalIQ</title>'))
	fail('jäljelle jäänyt title ei ole SPL-sivun oma');

writeFileSync(PATH, html);
console.log('fix-spl-head: OK (1 title, 1 description, SPL-otsikko voitti)');
