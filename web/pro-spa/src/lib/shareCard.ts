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

import { teamColorByShort } from './teamColors';

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

/* ---------- #9a jatko (31.7): pitch-jakokortti (rate my team / draft) ---------- */

export interface PitchCardPlayer {
	name: string;
	team: string;
	color: string;
	textColor: string;
	xp: string;
	badge?: 'C' | 'V';
}

export interface PitchCardSpec {
	title: string;
	subtitle: string;
	/** XI positioriveinä (GKP → FWD), sama järjestys kuin pitchillä */
	rows: PitchCardPlayer[][];
	bench: PitchCardPlayer[];
	fileName: string;
}

// Sama neutraali jersey-siluetti kuin TeamKit/Leaders (IP-turva: ei oikeita
// kittikuvioita). Path2D syö SVG-polun sellaisenaan, viewBox 100x100.
const JERSEY =
	'M 33 15 L 43 9 C 46 15 54 15 57 9 L 67 15 L 84 27 L 76 42 L 67 36 ' +
	'L 67 86 Q 67 90 63 90 L 37 90 Q 33 90 33 86 L 33 36 L 24 42 L 16 27 Z';
const SLEEVE_L = 'M 33 15 L 16 27 L 24 42 L 33 36 Z';
const SLEEVE_R = 'M 67 15 L 84 27 L 76 42 L 67 36 Z';

function darkenHex(hex: string, f = 0.7): string {
	const m = /^#?([0-9a-f]{6})$/i.exec(hex.trim());
	if (!m) return hex;
	const n = parseInt(m[1], 16);
	const p = [16, 8, 0].map((s) => Math.max(0, Math.round(((n >> s) & 0xff) * f)));
	return `#${p.map((v) => v.toString(16).padStart(2, '0')).join('')}`;
}

function drawKit(
	ctx: CanvasRenderingContext2D,
	// Rakenteellinen tyyppi (ei PitchCardPlayer): pelaajakortti kayttaa samaa
	// paitaa mutta sille ei ole xp:ta eika badgea.
	p: { color: string; textColor: string; team: string },
	x: number,
	y: number,
	size: number
) {
	ctx.save();
	ctx.translate(x, y);
	ctx.scale(size / 100, size / 100);
	ctx.fillStyle = p.color;
	ctx.fill(new Path2D(JERSEY));
	ctx.fillStyle = darkenHex(p.color);
	ctx.fill(new Path2D(SLEEVE_L));
	ctx.fill(new Path2D(SLEEVE_R));
	ctx.strokeStyle = 'rgba(243,242,242,0.35)';
	ctx.lineWidth = 3;
	ctx.lineJoin = 'round';
	ctx.stroke(new Path2D(JERSEY));
	ctx.fillStyle = p.textColor;
	ctx.font = `800 17px ${FONT}`;
	ctx.textBaseline = 'alphabetic';
	const tw = ctx.measureText(p.team).width;
	ctx.fillText(p.team, 50 - tw / 2, 62);
	ctx.restore();
	ctx.textBaseline = 'top';
}

export async function renderPitchCard(spec: PitchCardSpec): Promise<Blob> {
	await Promise.all([
		document.fonts.load(bold(60)),
		document.fonts.load(bold(22)),
		document.fonts.load(med(18))
	]).catch(() => undefined);
	const wm = await loadWordmark();

	const H = 1350;
	const canvas = document.createElement('canvas');
	canvas.width = W;
	canvas.height = H;
	const ctx = canvas.getContext('2d');
	if (!ctx) throw new Error('canvas 2d context unavailable');
	ctx.textBaseline = 'top';

	const g = ctx.createLinearGradient(0, 0, 0, H);
	g.addColorStop(0, INK);
	g.addColorStop(1, INK2);
	ctx.fillStyle = g;
	ctx.fillRect(0, 0, W, H);

	if (wm) {
		const wmH = 84;
		const wmW = Math.round((wm.width * wmH) / wm.height);
		ctx.drawImage(wm, (W - wmW) / 2, 64, wmW, wmH);
	}
	ctx.fillStyle = AMBER;
	ctx.beginPath();
	ctx.roundRect((W - 120) / 2, 176, 120, 6, 3);
	ctx.fill();
	ctx.font = bold(60);
	ctx.fillStyle = CREAM;
	ctx.fillText(spec.title, (W - ctx.measureText(spec.title).width) / 2, 226);
	ctx.font = med(22);
	ctx.fillStyle = MUTED;
	ctx.fillText(spec.subtitle, (W - ctx.measureText(spec.subtitle).width) / 2, 306);

	// Kenttä: tumma teal-nurmi raidoilla + viivat (sama teal-token kuin appissa)
	const PX = MX;
	const PY = 356;
	const PW = W - 2 * MX;
	const PH = 704;
	ctx.save();
	ctx.beginPath();
	ctx.roundRect(PX, PY, PW, PH, 14);
	ctx.clip();
	const stripeH = PH / 8;
	for (let i = 0; i < 8; i++) {
		ctx.fillStyle = i % 2 === 0 ? 'rgba(46,214,194,0.10)' : 'rgba(46,214,194,0.16)';
		ctx.fillRect(PX, PY + i * stripeH, PW, stripeH);
	}
	ctx.strokeStyle = 'rgba(46,214,194,0.45)';
	ctx.lineWidth = 2;
	const inset = 14;
	ctx.strokeRect(PX + inset, PY + inset, PW - 2 * inset, PH - 2 * inset);
	// PUOLIKAS kenttä (31.7, Villen tarkennus; OfficialFPL/FFScout-kaava):
	// maali + boksit + D ylhäällä, alareuna = keskiviiva keskiympyränkaarineen
	// → FWD-rivi istuu keskiviivan tuntumaan.
	const cxm = PX + PW / 2;
	const boxW = 400;
	const boxH = 96;
	ctx.strokeRect(cxm - boxW / 2, PY + inset, boxW, boxH);
	ctx.strokeRect(cxm - 110, PY + inset, 220, 40);
	ctx.beginPath();
	ctx.arc(cxm, PY + inset + boxH, 70, 0, Math.PI);
	ctx.stroke();
	ctx.beginPath();
	ctx.arc(cxm, PY + PH - inset, 88, Math.PI, 2 * Math.PI);
	ctx.stroke();
	ctx.restore();

	// XI-rivit
	const KIT = 84;
	const nRows = spec.rows.length || 1;
	const rowH = PH / nRows;
	for (let r = 0; r < spec.rows.length; r++) {
		const row = spec.rows[r];
		const cy = PY + rowH * r + rowH / 2;
		const cellW = PW / row.length;
		for (let i = 0; i < row.length; i++) {
			const p = row[i];
			const cx = PX + cellW * i + cellW / 2;
			const kx = cx - KIT / 2;
			const ky = cy - 62;
			drawKit(ctx, p, kx, ky, KIT);
			if (p.badge) {
				// C = amber-rengas, V = himmeä (korttipaletti: ei magentaa)
				const bx = kx + KIT - 4;
				const by = ky + 2;
				ctx.beginPath();
				ctx.arc(bx, by, 13, 0, Math.PI * 2);
				ctx.fillStyle = INK;
				ctx.fill();
				ctx.strokeStyle = p.badge === 'C' ? AMBER : MUTED;
				ctx.lineWidth = 2;
				ctx.stroke();
				ctx.font = bold(14);
				ctx.fillStyle = p.badge === 'C' ? AMBER : CREAM;
				ctx.fillText(p.badge, bx - ctx.measureText(p.badge).width / 2, by - 8);
			}
			const nPx = shrink(ctx, p.name, 22, cellW - 12, 14, bold);
			ctx.font = bold(nPx);
			ctx.fillStyle = CREAM;
			ctx.fillText(p.name, cx - ctx.measureText(p.name).width / 2, cy + 28);
			ctx.font = med(18);
			ctx.fillStyle = MUTED;
			ctx.fillText(p.xp, cx - ctx.measureText(p.xp).width / 2, cy + 56);
		}
	}

	// Penkki
	if (spec.bench.length > 0) {
		ctx.font = med(19);
		ctx.fillStyle = MUTED;
		ctx.fillText('BENCH', MX, 1082);
		const BK = 64;
		const cellW = Math.min(200, (W - 2 * MX) / spec.bench.length);
		const total = cellW * spec.bench.length;
		const x0 = (W - total) / 2;
		for (let i = 0; i < spec.bench.length; i++) {
			const p = spec.bench[i];
			const cx = x0 + cellW * i + cellW / 2;
			drawKit(ctx, p, cx - BK / 2, 1112, BK);
			const nPx = shrink(ctx, p.name, 18, cellW - 10, 12, bold);
			ctx.font = bold(nPx);
			ctx.fillStyle = CREAM;
			ctx.fillText(p.name, cx - ctx.measureText(p.name).width / 2, 1184);
			ctx.font = med(16);
			ctx.fillStyle = MUTED;
			ctx.fillText(p.xp, cx - ctx.measureText(p.xp).width / 2, 1208);
		}
	}

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

export async function sharePitchCard(spec: PitchCardSpec): Promise<ShareOutcome> {
	const blob = await renderPitchCard(spec);
	return deliver(blob, spec.fileName);
}

/* ---------- 4.8: yhden pelaajan kortti (player card) ---------- */

export interface PlayerCardCell {
	label: string;
	value: string;
}

export interface PlayerCardSpec {
	name: string;
	/** pos-tagi (GKP/DEF/MID/FWD) */
	tag: string;
	/** lyhytkoodi paitaan ja klubivariin, esim. "ARS" */
	team: string;
	/** koko nimi klubinauhaan, esim. "Arsenal" */
	teamName: string;
	/** hinta + omistus yhdella rivilla nimen alla */
	meta: string;
	/** FPL:n VIRALLINEN saatavuustila. Jatetaan pois kun pelaaja on
	 *  normaalisti kaytettavissa - "Available" olisi kohinaa. */
	statusLine?: string;
	/** Kortin karkiluku: iso amber-arvo + selittava teksti. */
	hero?: { value: string; label: string };
	/** Premium-rivi (xP). Kutsuja jattaa pois freelta. */
	modelLine?: string;
	/** Tuotantorivi. title kantaa katteen (kausi + sarja + per 90 vai totaali)
	 *  - ilman sita luvut vaittaisivat olevansa jotain muuta kuin ovat. */
	production?: { title: string; cells: PlayerCardCell[]; totals?: string };
	note?: string;
	fileName: string;
}

/** Yhden pelaajan kortti. Erillinen renderCardista, koska se on listakortti
 *  (rank/name/mid/value) eivatka pelaajan faktat ole rivimuotoista dataa.
 *
 *  1. versio oli neljan ison laatikon ruudukko ja Ville hylkasi sen ("ei oo
 *  hyva tollanen kortti") - se oli geneerinen dashboard ilman pelaajan
 *  identiteettia, ja puolet kortista oli tyhjaa. Tama versio nojaa klubin
 *  variin ja paitaan (sama lahde kuin pitch-kortissa) ja kertoo mallin
 *  nakemyksen + oikeat tuotantoluvut.
 *
 *  PREMIUM-GATE ON KUTSUJAN VASTUULLA. Toisin kuin muut kortit tama EI ole
 *  puhtaasti premium-datan johdannainen: pelaajakortin data on paaosin
 *  julkista (FPL-status, hinta, omistus, aloitustodennakoisyys, DefCon,
 *  viime kausi), ja 2.8. paatettiin etta juuri free-datan jakaminen ON
 *  jakelusilmukka. Kutsuja jattaa modelLine-rivin pois freelta. */
export async function renderPlayerCard(spec: PlayerCardSpec): Promise<Blob> {
	await Promise.all([
		document.fonts.load(bold(64)),
		document.fonts.load(bold(30)),
		document.fonts.load(med(20))
	]).catch(() => undefined);
	const wm = await loadWordmark();

	const BAND_TOP = 128;
	const BAND_H = 172;

	// Korkeus lasketaan lohko kerrallaan, jotta puuttuva lohko ei jata aukkoa
	// (1. version vika: kiintea ruudukko + iso tyhja alue alalaidassa).
	let h = BAND_TOP + BAND_H + 26;
	const yStatus = h;
	if (spec.statusLine) h += 50;
	const yHero = h;
	if (spec.hero) h += 128;
	const yModel = h;
	if (spec.modelLine) h += 58;
	const yProd = h;
	if (spec.production) h += 40 + 92 + (spec.production.totals ? 40 : 0);
	const yNote = h;
	if (spec.note) h += 44;
	const H = h + FOOT_H;

	const canvas = document.createElement('canvas');
	canvas.width = W;
	canvas.height = H;
	const ctx = canvas.getContext('2d');
	if (!ctx) throw new Error('canvas 2d context unavailable');
	ctx.textBaseline = 'top';

	const g = ctx.createLinearGradient(0, 0, 0, H);
	g.addColorStop(0, INK);
	g.addColorStop(1, INK2);
	ctx.fillStyle = g;
	ctx.fillRect(0, 0, W, H);

	// Wordmark (pienempi kuin listakortissa: klubinauha kantaa ylaosan)
	if (wm) {
		const wmH = 56;
		const wmW = Math.round((wm.width * wmH) / wm.height);
		ctx.drawImage(wm, (W - wmW) / 2, 44, wmW, wmH);
	} else {
		ctx.font = bold(38);
		const gw = ctx.measureText('GOAL').width;
		const box = 52;
		const x0 = (W - (gw + 12 + box)) / 2;
		ctx.fillStyle = CREAM;
		ctx.fillText('GOAL', x0, 50);
		ctx.fillStyle = AMBER;
		ctx.fillRect(x0 + gw + 12, 44, box, box);
		ctx.fillStyle = INK;
		ctx.font = bold(28);
		ctx.fillText('IQ', x0 + gw + 12 + (box - ctx.measureText('IQ').width) / 2, 56);
	}

	// --- Klubinauha: pelaajan identiteetti ---
	const kit = teamColorByShort(spec.team);
	ctx.fillStyle = kit.color;
	ctx.fillRect(0, BAND_TOP, W, BAND_H);
	// Amber-viiva nauhan alle sitoo klubivarin brandiin
	ctx.fillStyle = AMBER;
	ctx.fillRect(0, BAND_TOP + BAND_H, W, 5);

	const onBand = kit.textColor;
	const onBandMuted =
		onBand === '#000000' ? 'rgba(0,0,0,0.66)' : 'rgba(255,255,255,0.76)';

	const KIT_S = 108;
	drawKit(ctx, { color: kit.color, textColor: onBand, team: spec.team },
		MX, BAND_TOP + (BAND_H - KIT_S) / 2, KIT_S);

	const tx = MX + KIT_S + 34;
	const availW = W - tx - MX;
	const nPx = shrink(ctx, spec.name, 62, availW, 30, bold);
	ctx.font = bold(nPx);
	ctx.fillStyle = onBand;
	ctx.fillText(spec.name, tx, BAND_TOP + 40);

	// Meta-rivi: pos-tagi + hinta/omistus
	const my = BAND_TOP + 40 + nPx + 16;
	ctx.font = bold(19);
	const tagW = ctx.measureText(spec.tag).width + 18;
	ctx.strokeStyle = onBandMuted;
	ctx.lineWidth = 1;
	ctx.strokeRect(tx, my - 3, tagW, 30);
	ctx.fillStyle = onBand;
	ctx.fillText(spec.tag, tx + 9, my + 3);
	ctx.font = med(21);
	ctx.fillStyle = onBandMuted;
	ctx.fillText(spec.meta, tx + tagW + 16, my + 4);

	// Klubin nimi nauhan oikeaan laitaan haaleana (identiteetti, ei kohina)
	ctx.font = bold(21);
	const tnW = ctx.measureText(spec.teamName.toUpperCase()).width;
	ctx.fillStyle = onBandMuted;
	ctx.fillText(spec.teamName.toUpperCase(), W - MX - tnW, BAND_TOP + 22);

	// --- Virallinen status (vain kun on kerrottavaa) ---
	if (spec.statusLine) {
		const sPx = shrink(ctx, spec.statusLine, 23, W - 2 * MX, 15, med);
		ctx.font = med(sPx);
		ctx.fillStyle = AMBER;
		ctx.fillText(spec.statusLine, MX, yStatus + 10);
	}

	// --- Karkiluku ---
	if (spec.hero) {
		ctx.font = bold(76);
		ctx.fillStyle = AMBER;
		ctx.fillText(spec.hero.value, MX, yHero + 16);
		const vw = ctx.measureText(spec.hero.value).width;
		const lPx = shrink(ctx, spec.hero.label, 26, W - MX * 2 - vw - 26, 15, med);
		ctx.font = med(lPx);
		ctx.fillStyle = CREAM;
		ctx.fillText(spec.hero.label, MX + vw + 26, yHero + 16 + 76 - lPx - 10);
	}

	// --- Malliluku (premium) ---
	if (spec.modelLine) {
		const mPx = shrink(ctx, spec.modelLine, 27, W - 2 * MX, 16, bold);
		ctx.font = bold(mPx);
		ctx.fillStyle = CREAM;
		ctx.fillText(spec.modelLine, MX, yModel + 12);
	}

	// --- Tuotantorivi ---
	if (spec.production) {
		const pr = spec.production;
		ctx.strokeStyle = LINE;
		ctx.lineWidth = 1;
		ctx.beginPath();
		ctx.moveTo(MX, yProd + 8);
		ctx.lineTo(W - MX, yProd + 8);
		ctx.stroke();

		ctx.font = med(19);
		ctx.fillStyle = MUTED;
		ctx.fillText(pr.title.toUpperCase(), MX, yProd + 24);

		const cy = yProd + 40 + 16;
		// KIINTEA slot-leveys, EI (leveys / solujen maara). Jalkimmainen levitti
		// kaksi solua koko kortin leveydelle ja nakyi rikkinaisena ruudukkona
		// (nakyi vasta kuvaa katsomalla). Nyt solut pakkautuvat vasemmalta.
		const SLOT = 240;
		pr.cells.forEach((c, i) => {
			const cx = MX + i * SLOT;
			ctx.font = bold(38);
			ctx.fillStyle = CREAM;
			ctx.fillText(c.value, cx, cy);
			ctx.font = med(18);
			ctx.fillStyle = MUTED;
			ctx.fillText(c.label.toUpperCase(), cx, cy + 46);
		});

		if (pr.totals) {
			const tPx = shrink(ctx, pr.totals, 20, W - 2 * MX, 13, med);
			ctx.font = med(tPx);
			ctx.fillStyle = MUTED;
			ctx.fillText(pr.totals, MX, yProd + 40 + 92 - 8);
		}
	}

	if (spec.note) {
		const nfPx = shrink(ctx, spec.note, 18, W - 2 * MX, 12, med);
		ctx.font = med(nfPx);
		ctx.fillStyle = MUTED;
		ctx.fillText(spec.note, MX, yNote + 12);
	}

	// Footer identtinen listakortin kanssa
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

export async function sharePlayerCard(spec: PlayerCardSpec): Promise<ShareOutcome> {
	const blob = await renderPlayerCard(spec);
	return deliver(blob, spec.fileName);
}

export type ShareOutcome = 'shared' | 'downloaded' | 'aborted';

/** Share-arkki vain mobiilissa (31.7, Villen havainto): Windowsin share-arkissa
 * ei ole X-kohdetta eikä tallennusta — pöytäkoneella suora PNG-lataus on
 * ainoa toimiva polku. Mobiilissa arkki taas on juuri se "suoraan X:ään" -flow.
 * SSR-turvallinen (navigator-guard). */
export function canShareToApps(): boolean {
	return (
		typeof navigator !== 'undefined' &&
		typeof navigator.canShare === 'function' &&
		/Android|iPhone|iPad|iPod/i.test(navigator.userAgent)
	);
}

/** Mobiili: navigator.share tiedostolla. Desktop + kaikki virhepolut: PNG-lataus. */
async function deliver(blob: Blob, fileName: string): Promise<ShareOutcome> {
	const file = new File([blob], fileName, { type: 'image/png' });
	if (canShareToApps() && navigator.canShare({ files: [file] })) {
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
	a.download = fileName;
	a.click();
	URL.revokeObjectURL(url);
	return 'downloaded';
}

export async function shareCard(spec: CardSpec): Promise<ShareOutcome> {
	const blob = await renderCard(spec);
	return deliver(blob, spec.fileName);
}
