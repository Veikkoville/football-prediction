/**
 * SPA:n liigalista — YKSI totuus Predictille, Fixturesille ja Standingsille.
 *
 * 8.8: Fixtures ja Standings dumppasivat `/api/leagues`:n sellaisenaan, joka
 * listaa MALLIN tukemat liigat (Veikkausliiga, Allsvenskan, Eliteserien, …).
 * Otteluohjelma ja sarjataulukko tulevat kuitenkin football-data.orgista,
 * jonka kattavuus on eri: valikko tarjosi liigoja joille vastaus on aina 404
 * ja jätti pois Brasileirãon, joka toimii — ja on ainoa liiga jossa on
 * otteluita kesken eurooppalaisen kauden tauon. Predict korjattiin 28.7.
 * omalla kuratoidulla listalla, mutta kaksi muuta jäi. Siksi lista asuu nyt
 * täällä eikä komponentissa.
 *
 * Lähde: backendin FIXTURE_STANDINGS_CODES (src/data/football_data_org.py)
 * leikattuna niihin joilla toimii MYÖS /api/predict — koodit siinä muodossa
 * jonka backend hyväksyy (Top-5:stä -FD-suffiksilla PL:ää lukuun ottamatta,
 * jonka malli on Understat-pohjainen). Sama joukko kuin mobiilin
 * `lib/leagues.ts`:ssä.
 */

export interface SpaLeague {
	code: string;
	label: string;
	/**
	 * Kalenterivuosikausi (BSA). Standings vaatii oman kausikoodin ('26'):
	 * eurooppalainen '2526' osuisi eri kauteen, ei virheeseen — hiljainen
	 * väärä taulukko on pahempi kuin 404.
	 */
	calendarYear?: boolean;
	/** Turnaus: ei liigataulukkoa (pariteetti mobiilin StandingsScreenin kanssa). */
	tournament?: boolean;
}

export const LEAGUES: SpaLeague[] = [
	{ code: 'ENG-Premier League', label: 'Premier League' },
	{ code: 'ESP-La Liga-FD', label: 'La Liga' },
	{ code: 'GER-Bundesliga-FD', label: 'Bundesliga' },
	{ code: 'ITA-Serie A-FD', label: 'Serie A' },
	{ code: 'FRA-Ligue 1-FD', label: 'Ligue 1' },
	{ code: 'ENG-Championship', label: 'Championship' },
	{ code: 'NED-Eredivisie', label: 'Eredivisie' },
	{ code: 'POR-Primeira Liga', label: 'Primeira Liga' },
	{ code: 'BRA-Serie A', label: 'Brasileirao', calendarYear: true },
	{ code: 'INT-Champions League', label: 'Champions League', tournament: true }
];

/** Otteluohjelma: kaikki, turnaukset mukaan lukien. */
export const FIXTURE_LEAGUES = LEAGUES;

/** Sarjataulukko: vain sarjat. */
export const STANDINGS_LEAGUES = LEAGUES.filter((l) => !l.tournament);

export function findLeague(code: string): SpaLeague | undefined {
	return LEAGUES.find((l) => l.code === code);
}

/**
 * Eurooppalainen kausikoodi kalenterista (elo–touko), sama sääntö kuin
 * mobiilin lib/season.ts:ssä ja backendin config.current_season():ssa.
 */
export function currentSeasonCode(now = new Date()): string {
	const y = now.getUTCFullYear() % 100;
	const start = now.getUTCMonth() + 1 >= 8 ? y : y - 1;
	return `${String(start).padStart(2, '0')}${String(start + 1).padStart(2, '0')}`;
}

export interface SeasonChoice {
	value: string;
	label: string;
}

/** Kausivalikko liigan mukaan: kuluva + kolme edellistä. */
export function seasonChoices(code: string, now = new Date()): SeasonChoice[] {
	const y = now.getUTCFullYear() % 100;
	if (findLeague(code)?.calendarYear) {
		return [0, 1, 2, 3].map((i) => ({
			value: String(y - i).padStart(2, '0'),
			label: String(2000 + y - i)
		}));
	}
	const start = now.getUTCMonth() + 1 >= 8 ? y : y - 1;
	return [0, 1, 2, 3].map((i) => {
		const s = start - i;
		return {
			value: `${String(s).padStart(2, '0')}${String(s + 1).padStart(2, '0')}`,
			label: `${2000 + s}/${String(s + 1).padStart(2, '0')}`
		};
	});
}

/** Liigan oletuskausi = kausivalikon tuorein rivi. */
export function defaultSeason(code: string, now = new Date()): string {
	return seasonChoices(code, now)[0].value;
}
