/** PI-16b (28.7): jaettu "entry ensin, draft varalle" -polku joukkuepohjaisille
 * FPL-työkaluille.
 *
 * Tausta: FPL julkaisee kokoonpanot vasta GW1-deadlinen jälkeen, joten
 * `?entry=`-polku palauttaa 404:n KOKO esikauden ajan. Rate my team sai 28.7.
 * ohjauksen draft-rateriin, mutta planner ja siirtoketjut jäivät umpikujaan:
 * sama 404 näkyi punaisena virheenä, vaikka käyttäjä ei ollut tehnyt mitään
 * väärin ja toimiva polku samaan työhön oli olemassa (tallennettu 15:n draft).
 *
 * Backend on osannut `players=`-moodin koko ajan. Vika oli klientissä, ja
 * siksi tämä on yhdessä paikassa: jokainen työkalu joka tarvitsee joukkueen
 * saa saman fallbackin ja saman selitteen, eivätkä ne voi ajautua eroon.
 */
import { loadDraftIds } from './draft';

export type SquadBasis = 'entry' | 'draft';

export interface SquadRun<T> {
	data: T;
	basedOn: SquadBasis;
}

/** Heitetään kun FPL ei ole julkaissut kokoonpanoja EIKÄ draftia ole tallessa.
 * Ei ole virhe vaan kalenterin tila + puuttuva syöte, joten UI näyttää sen
 * ohjeena eikä punaisena virhelaatikkona. */
export class NoSquadInputError extends Error {
	constructor() {
		super(
			'FPL has not published any squads yet. They open up after the GW1 ' +
				'deadline. Until then, draft your 15 in Rate my team and this tool ' +
				'runs on that draft.'
		);
		this.name = 'NoSquadInputError';
	}
}

function isPicksNotPublished(err: unknown): boolean {
	return (err as { code?: string })?.code === 'picks_not_published';
}

/** 15 = FPL:n laillinen runko. Vajaa draft ei kelpaa syötteeksi (backend
 * hylkäisi sen 400:lla), joten se luetaan "ei draftia" -tilaksi. */
export function savedDraft15(): number[] | null {
	const ids = loadDraftIds();
	return ids && ids.length === 15 ? ids : null;
}

/**
 * Aja `viaEntry`; jos FPL ei ole vielä julkaissut kokoonpanoja, aja sama työ
 * tallennetulla draftilla. Muut virheet nousevat sellaisinaan läpi, koska
 * niissä fallback ei ole oikea vastaus (väärä ID, 503, verkko).
 */
export async function runWithSquadFallback<T>(
	entry: number,
	viaEntry: (entry: number) => Promise<T>,
	viaDraft: (playerIds: number[]) => Promise<T>
): Promise<SquadRun<T>> {
	try {
		return { data: await viaEntry(entry), basedOn: 'entry' };
	} catch (err) {
		if (!isPicksNotPublished(err)) throw err;
		const ids = savedDraft15();
		if (!ids) throw new NoSquadInputError();
		return { data: await viaDraft(ids), basedOn: 'draft' };
	}
}
