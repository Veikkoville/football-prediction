/**
 * #9a Share as image (31.7.2026, Wolfyn idean tuoteversio, Villen suunta:
 * "sivuilta saisi suoraan tollaisen jaettua").
 *
 * Client-side canvas-render teletext-jakokortista. Layout ja mitat 1:1
 * goaliq-appin outputs/gen_fpl_xp_list.py:n kanssa (sama kortti jonka
 * viikkopostaus käyttää) — kuva ja sivusto kertovat saman tarinan samassa
 * muodossa. IBM Plex Mono on jo sivulla (Google Fonts), wordmark-PNG
 * static/brand/-kansiossa.
 *
 * Premium-gate on KUTSUJAN vastuulla: kortti on premium-datan johdannainen,
 * nappia ei renderöidä freelle.
 */

export interface CardRow {
	rank: number;
	name: string;
	/** pos-tagi heti nimen vieressä (Wolfyn layout-palaute) */
	tag: string;
	team: string;
	/** P/FK-tyyliset amber-badget nimen perään */
	badges?: string[];
	/** keskisarake (fixture / price), oikeaan reunaan tasattu */
	mid?: string;
	/** oikean laidan arvo (xP / xG / hit rate) */
	value: string;
}

export interface CardSpec {
	title: string;
	subtitle: string;
	midLabel?: string;
	valueLabel: string;
	rows: CardRow[];
	fileName: string;
}

const W = 1080;
const MX = 60;
const ROW_TOP = 404;
const ROW_H = 80;
const FOOT_H = 146;

const INK = '#0b0a09';
const INK2 = '#141311';
const AMBER = '#f5c542';
const CREAM = '#f3f2f2';
const MUTED = '#a8a29a';
const LINE = 'rgba(243,242,242,0.13)';
const TAG_LINE = 'rgba(243,242,242,0.33)';

const FONT = '"IBM Plex Mono", ui-monospace, monospace';
const bold = (px: number) => `700 ${px}px ${FONT}`;
const med = (px: number) => `500 ${px}px ${FONT}`;

let wordmarkP: Promise<HTMLImageElement | null> | null = null;
function loadWordmark(): Promise<HTMLImageElement | null> {
	wordmarkP ??= new Promise((resolve) => {
		const img = new Image();
		img.onload = () => resolve(img);
		// Fallback piirretään tekstinä — kortti ei saa kaatua asset-puutteeseen.
		img.onerror = () => resolve(null);
		img.src = '/brand/goaliq-wordmark-teletext.png';
	});
	return wordmarkP;
}

/** Kutista fonttia kunnes teksti mahtuu — sama kaava kuin Python-versiossa. */
function shrink(
	ctx: CanvasRenderingContext2D,
	text: string,
	px: number,
	maxW: number,
	minPx: number,
	weight: (px: number) => string
): number {
	ctx.font = weight(px);
	while (ctx.measureText(text).width > maxW && px > minPx) {
		px -= 2;
		ctx.font = weight(px);
	}
	return px;
}

export async function renderCard(spec: CardSpec): Promise<Blob> {
	// Fontit varmasti ladattuina ennen mittauksia (muuten measureText valehtelee).
	await Promise.all([
		document.fonts.load(bold(60)),
		document.fonts.load(bold(36)),
		document.fonts.load(med(24))
	]).catch(() => undefined);
	const wm = await loadWordmark();

	const n = spec.rows.length;
	const H = ROW_TOP + n * ROW_H + FOOT_H;
	const canvas = document.createElement('canvas');
	canvas.width = W;
	canvas.height = H;
	const ctx = canvas.getContext('2d');
	if (!ctx) throw new Error('canvas 2d context unavailable');
	ctx.textBaseline = 'top';

	// INK-gradientti kuten feature graphicissa
	const g = ctx.createLinearGradient(0, 0, 0, H);
	g.addColorStop(0, INK);
	g.addColorStop(1, INK2);
	ctx.fillStyle = g;
	ctx.fillRect(0, 0, W, H);

	// Wordmark ylareunaan keskelle + amber-viiva (brandin tunniste)
	if (wm) {
		const wmH = 84;
		const wmW = Math.round((wm.width * wmH) / wm.height);
		ctx.drawImage(wm, (W - wmW) / 2, 64, wmW, wmH);
	} else {
		ctx.font = bold(56);
		const gw = ctx.measureText('GOAL').width;
		const box = 76;
		const total = gw + 14 + box;
		const x0 = (W - total) / 2;
		ctx.fillStyle = CREAM;
		ctx.fillText('GOAL', x0, 72);
		ctx.fillStyle = AMBER;
		ctx.fillRect(x0 + gw + 14, 64, box, box);
		ctx.fillStyle = INK;
		ctx.font = bold(40);
		ctx.fillText('IQ', x0 + gw + 14 + (box - ctx.measureText('IQ').width) / 2, 82);
	}
	ctx.fillStyle = AMBER;
	ctx.beginPath();
	ctx.roundRect((W - 120) / 2, 176, 120, 6, 3);
	ctx.fill();

	// Otsikko + alaotsikko
	ctx.font = bold(60);
	ctx.fillStyle = CREAM;
	ctx.fillText(spec.title, (W - ctx.measureText(spec.title).width) / 2, 226);
	ctx.font = med(22);
	ctx.fillStyle = MUTED;
	ctx.fillText(spec.subtitle, (W - ctx.measureText(spec.subtitle).width) / 2, 306);

	// Sarakeotsikot
	const fxRight = W - MX - 180;
	ctx.font = med(19);
	ctx.fillText('PLAYER', MX + 76, ROW_TOP - 34);
	if (spec.midLabel) {
		ctx.fillText(spec.midLabel, fxRight - ctx.measureText(spec.midLabel).width, ROW_TOP - 34);
	}
	ctx.fillText(spec.valueLabel, W - MX - ctx.measureText(spec.valueLabel).width, ROW_TOP - 34);

	for (let i = 0; i < n; i++) {
		const r = spec.rows[i];
		const y = ROW_TOP + i * ROW_H;
		const cy = y + ROW_H / 2;
		const first = i === 0;

		// Rivikehys: karkirivi amber-kehyksella, muut ohuella viivalla
		ctx.strokeStyle = first ? AMBER : LINE;
		ctx.lineWidth = first ? 2 : 1;
		ctx.strokeRect(MX - 12, y + 4, W - 2 * (MX - 12), ROW_H - 8);

		// rank oikeaan reunaan tasattuna
		ctx.font = bold(28);
		ctx.fillStyle = first ? AMBER : MUTED;
		const rk = String(r.rank);
		ctx.fillText(rk, MX + 34 - ctx.measureText(rk).width, cy - 16);

		// nimi + pos-tagi + joukkue + badget
		let x = MX + 76;
		const nPx = shrink(ctx, r.name, 32, 330, 20, bold);
		ctx.font = bold(nPx);
		ctx.fillStyle = CREAM;
		ctx.fillText(r.name, x, cy - nPx * 0.62);
		x += ctx.measureText(r.name).width + 16;

		ctx.font = bold(17);
		const pw = ctx.measureText(r.tag).width + 16;
		ctx.strokeStyle = TAG_LINE;
		ctx.lineWidth = 1;
		ctx.strokeRect(x, cy - 15, pw, 30);
		ctx.fillText(r.tag, x + 8, cy - 10);
		x += pw + 12;

		ctx.font = med(20);
		ctx.fillStyle = MUTED;
		ctx.fillText(r.team, x, cy - 10);
		x += ctx.measureText(r.team).width + 12;

		for (const b of r.badges ?? []) {
			ctx.font = bold(17);
			const bw = ctx.measureText(b).width + 14;
			ctx.strokeStyle = AMBER;
			ctx.strokeRect(x, cy - 14, bw, 28);
			ctx.fillStyle = AMBER;
			ctx.fillText(b, x + 7, cy - 9);
			x += bw + 8;
		}

		// keskisarake (fixture / price) oikealle tasattuna
		if (r.mid) {
			const fPx = shrink(ctx, r.mid, 24, 190, 14, med);
			ctx.font = med(fPx);
			ctx.fillStyle = MUTED;
			ctx.fillText(r.mid, fxRight - ctx.measureText(r.mid).width, cy - fPx * 0.55);
		}

		// arvo oikeaan laitaan
		ctx.font = bold(36);
		ctx.fillStyle = first ? AMBER : CREAM;
		ctx.fillText(r.value, W - MX - ctx.measureText(r.value).width, cy - 36 * 0.58);
	}

	// Footer + amber-alaraita (brandin tunniste)
	ctx.font = med(20);
	ctx.fillStyle = MUTED;
	ctx.fillText('logged before kickoff, graded in public', MX, H - 88);
	ctx.font = bold(20);
	ctx.fillStyle = AMBER;
	ctx.fillText('@goaliqapp', W - MX - ctx.measureText('@goaliqapp').width, H - 88);
	ctx.font = med(17);
	ctx.fillStyle = MUTED;
	ctx.fillText('model projections, not betting advice', MX, H - 54);
	ctx.fillStyle = AMBER;
	ctx.fillRect(0, H - 8, W, 8);

	return new Promise<Blob>((resolve, reject) => {
		canvas.toBlob((b) => (b ? resolve(b) : reject(new Error('canvas toBlob failed'))), 'image/png');
	});
}

export type ShareOutcome = 'shared' | 'downloaded' | 'aborted';

/** navigator.share tiedostolla + PNG-latausfallback. */
export async function shareCard(spec: CardSpec): Promise<ShareOutcome> {
	const blob = await renderCard(spec);
	const file = new File([blob], spec.fileName, { type: 'image/png' });
	if (typeof navigator.canShare === 'function' && navigator.canShare({ files: [file] })) {
		try {
			await navigator.share({ files: [file] });
			return 'shared';
		} catch (e) {
			// Käyttäjä perui share-arkin — ei fallback-latausta perumisen päälle.
			if (e instanceof DOMException && e.name === 'AbortError') return 'aborted';
		}
	}
	const url = URL.createObjectURL(blob);
	const a = document.createElement('a');
	a.href = url;
	a.download = spec.fileName;
	a.click();
	URL.revokeObjectURL(url);
	return 'downloaded';
}
