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
	/** Nimisarakkeen otsikko — oletus PLAYER; joukkuetason lista (CS) antaa
	 *  TEAM (6.8 laiteverify-pariteetti: PLAYER joukkuelistan päällä näytti
	 *  virheeltä; sama korjaus mobiilissa). */
	nameLabel?: string;
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
	ctx.fillText(spec.nameLabel ?? 'PLAYER', MX + 76, ROW_TOP - 34);
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
	ctx.fillText('projections from the GoalIQ match model', MX, H - 88);
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
	/**
	 * Pelaajien alla olevien lukujen yksikkö (esim. "xP per GW"). Renderöidään
	 * kentän yläreunaan lukujen viereen — EI footeriin: yksikkö kaukana
	 * luvusta on sama vikaluokka josta Δ vs crowd luettiin pisteinä (11.8).
	 */
	unitNote?: string;
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

/** WCAG-suhteellinen luminanssi. */
function relLum(hex: string): number {
	const m = /^#?([0-9a-f]{6})$/i.exec(hex.trim());
	if (!m) return 0;
	const n = parseInt(m[1], 16);
	const c = [16, 8, 0].map((s) => {
		const v = ((n >> s) & 0xff) / 255;
		return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
	});
	return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
}

function contrast(a: string, b: string): number {
	const [x, y] = [relLum(a), relLum(b)].sort((p, q) => q - p);
	return (x + 0.05) / (y + 0.05);
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
	if (spec.unitNote) {
		// Yksikkö kentän sisään yläkulmaan, samaan näkymään lukujen kanssa.
		ctx.font = med(17);
		ctx.fillStyle = 'rgba(46,214,194,0.85)';
		ctx.fillText(
			spec.unitNote,
			PX + PW - inset - 12 - ctx.measureText(spec.unitNote).width,
			PY + inset + 10
		);
	}
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
	ctx.fillText('projections from the GoalIQ match model', MX, H - 88);
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

/* ---------- 6.8: vertailukortti (Rowanin palaute: "share a clean
 * comparison card" — creator leikkasi vertailuja Snipping Toolilla).
 * Sama kortti mobiilissa (FantasyCompareShareCard). Ei pelaajakuvia
 * (Getty/PL-kuvaoikeudet) — kitit joukkueväreissä kuten pitch-kortissa. */

export interface CompareCardPlayer {
	name: string;
	/** lyhytkoodi paitaan, esim. "ARS" */
	team: string;
	color: string;
	textColor: string;
	pos: string;
}

export interface CompareCardStat {
	label: string;
	values: string[];
	/** rivin "paras" sarake amberilla; null = neutraali rivi (esim. hinta) */
	bestIndex?: number | null;
}

export interface CompareCardSpec {
	title: string;
	subtitle: string;
	players: CompareCardPlayer[];
	stats: CompareCardStat[];
	/** mallin suora kanta (backend-generoitu EN-verdikti) */
	verdict?: string;
	fileName: string;
}

function wrapLines(
	ctx: CanvasRenderingContext2D,
	text: string,
	font: string,
	maxW: number
): string[] {
	ctx.font = font;
	const words = text.split(/\s+/);
	const lines: string[] = [];
	let cur = '';
	for (const w of words) {
		const cand = cur ? `${cur} ${w}` : w;
		if (ctx.measureText(cand).width <= maxW || !cur) cur = cand;
		else {
			lines.push(cur);
			cur = w;
		}
	}
	if (cur) lines.push(cur);
	return lines;
}

export async function renderCompareCard(spec: CompareCardSpec): Promise<Blob> {
	await Promise.all([
		document.fonts.load(bold(60)),
		document.fonts.load(bold(30)),
		document.fonts.load(med(20))
	]).catch(() => undefined);
	const wm = await loadWordmark();

	const n = Math.max(1, spec.players.length);
	const HEAD_TOP = 356;
	const HEAD_H = 190;
	const ROW_H2 = 64;
	const statsTop = HEAD_TOP + HEAD_H;
	const verdictTop = statsTop + spec.stats.length * ROW_H2 + 28;

	// Verdiktin korkeus lasketaan rivityksestä ennen canvasin mitoitusta.
	const probe = document.createElement('canvas').getContext('2d');
	const verdictLines = spec.verdict && probe
		? wrapLines(probe, spec.verdict, med(22), W - 2 * MX - 48)
		: [];
	const verdictH = verdictLines.length > 0 ? 62 + verdictLines.length * 30 : 0;
	const H = verdictTop + verdictH + FOOT_H;

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

	// Pelaajasarakkeet: label-kaista vasemmalla, loput jaetaan tasan
	const LABEL_W = 250;
	const colW = (W - 2 * MX - LABEL_W) / n;
	const colX = (i: number) => MX + LABEL_W + colW * i + colW / 2;
	const KIT = 84;
	for (let i = 0; i < n; i++) {
		const p = spec.players[i];
		const cx = colX(i);
		drawKit(ctx, p, cx - KIT / 2, HEAD_TOP, KIT);
		const nPx = shrink(ctx, p.name, 26, colW - 16, 16, bold);
		ctx.font = bold(nPx);
		ctx.fillStyle = CREAM;
		ctx.fillText(p.name, cx - ctx.measureText(p.name).width / 2, HEAD_TOP + KIT + 16);
		ctx.font = med(18);
		ctx.fillStyle = MUTED;
		ctx.fillText(p.pos, cx - ctx.measureText(p.pos).width / 2, HEAD_TOP + KIT + 52);
	}

	// Statirivit: hiusviiva ylle, label vasemmalle, arvot sarakkeisiin
	for (let r = 0; r < spec.stats.length; r++) {
		const s = spec.stats[r];
		const y = statsTop + r * ROW_H2;
		ctx.strokeStyle = LINE;
		ctx.lineWidth = 1;
		ctx.beginPath();
		ctx.moveTo(MX, y);
		ctx.lineTo(W - MX, y);
		ctx.stroke();
		ctx.font = med(19);
		ctx.fillStyle = MUTED;
		ctx.fillText(s.label, MX, y + ROW_H2 / 2 - 10);
		for (let i = 0; i < n; i++) {
			const v = s.values[i] ?? '';
			ctx.font = bold(30);
			ctx.fillStyle = s.bestIndex === i ? AMBER : CREAM;
			ctx.fillText(v, colX(i) - ctx.measureText(v).width / 2, y + ROW_H2 / 2 - 16);
		}
	}

	// Verdikti: amber-kehys + "THE MODEL SAYS" — kortti on kannanotto,
	// ei pelkkä taulukko.
	if (verdictLines.length > 0) {
		ctx.strokeStyle = AMBER;
		ctx.lineWidth = 2;
		ctx.strokeRect(MX, verdictTop, W - 2 * MX, verdictH - 14);
		ctx.font = bold(18);
		ctx.fillStyle = AMBER;
		ctx.fillText('THE MODEL SAYS', MX + 24, verdictTop + 18);
		ctx.font = med(22);
		ctx.fillStyle = CREAM;
		for (let i = 0; i < verdictLines.length; i++) {
			ctx.fillText(verdictLines[i], MX + 24, verdictTop + 50 + i * 30);
		}
	}

	ctx.font = med(20);
	ctx.fillStyle = MUTED;
	ctx.fillText('projections from the GoalIQ match model', MX, H - 88);
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

export async function shareCompareCard(spec: CompareCardSpec): Promise<ShareOutcome> {
	const blob = await renderCompareCard(spec);
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
	/** DefCon-rivi omanaan. EI note-riville: se on eri ikkuna kuin "viime kausi"
	 *  (viimeiset N ottelua) ja se on puolustajilla kortin erottava luku - eika
	 *  erottavaa lukua panna disclaimerin peraan pikkutekstiin. */
	defconLine?: string;
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
	const yDefcon = h;
	if (spec.defconLine) h += 50;
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

	// Nauhan tekstivari EI ole suoraan kit.textColor. Se on paidan oma variPari
	// (esim. MCI = valkoinen taivaansinisella), joka toimii pienessa paidassa
	// mutta antaa nauhalla kontrastin 2,5:1 - nimi on kortin isoin teksti eika
	// se saa olla luettavuuden rajalla. Flippaus vain kun kontrasti alittaa
	// WCAG:n ison tekstin rajan 3:1, jotta esim. ARS (valkoinen punaisella,
	// 4,5:1) sailyy klubin omana ilmeena.
	const INK_ON_BAND = '#111111';
	const onBand = contrast(kit.textColor, kit.color) >= 3 ? kit.textColor : INK_ON_BAND;
	const onBandMuted =
		relLum(onBand) < 0.5 ? 'rgba(0,0,0,0.66)' : 'rgba(255,255,255,0.76)';

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

	if (spec.defconLine) {
		const dPx = shrink(ctx, spec.defconLine, 24, W - 2 * MX, 15, med);
		ctx.font = med(dPx);
		ctx.fillStyle = CREAM;
		ctx.fillText(spec.defconLine, MX, yDefcon + 14);
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
	ctx.fillText('projections from the GoalIQ match model', MX, H - 88);
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

/* ---------- 16.8: roast-kortti (Villen tilaus) ----------
 *
 * "laitetaas tohon roast my teamiin jakokortti missa joku aiheeseen
 * liittyva hassunhauska kuva sekä toi teksti"
 *
 * 🔴 KUVA PIIRRETAAN ITSE. Meemi tai valokuva olisi tekijanoikeusongelma
 * kortissa jonka koko tarkoitus on levita muiden ihmisten feedeihin, ja se
 * riski on meidan eika jakajan. Liekki ja naama ovat canvas-primitiiveja
 * brandin vareissa, joten kortti on jaettavissa ilman lisenssikysymysta.
 *
 * Kuva seuraa roastin tasoa (`roastTier`), ei omaa logiikkaansa: sama
 * joukkue ei saa tekstia "annoyingly competent" ja kuvaa jossa se palaa.
 */

export interface RoastCardSpec {
	/** 'singed' | 'toasted' | 'cremated' */
	tier: string;
	score: number;
	headline: string;
	lines: string[];
	fileName: string;
}

/** Yksi liekki. Bezier-parit, ei kuvatiedostoa. */
function drawFlame(ctx: CanvasRenderingContext2D, x: number, y: number, h: number) {
	const w = h * 0.62;
	ctx.beginPath();
	ctx.moveTo(x, y);
	ctx.bezierCurveTo(x + w * 0.55, y - h * 0.34, x + w * 0.2, y - h * 0.66, x + w * 0.3, y - h);
	ctx.bezierCurveTo(x + w * 0.02, y - h * 0.78, x - w * 0.34, y - h * 0.72, x - w * 0.28, y - h * 0.3);
	ctx.bezierCurveTo(x - w * 0.5, y - h * 0.36, x - w * 0.5, y - h * 0.1, x, y);
	ctx.closePath();
	const g = ctx.createLinearGradient(x, y, x, y - h);
	g.addColorStop(0, '#ff8a5c');
	g.addColorStop(1, '#f5c542');
	ctx.fillStyle = g;
	ctx.fill();
	// Sisaliekki: pelkka yksivarinen liekki luki logolta, ei kuvalta.
	ctx.beginPath();
	ctx.moveTo(x, y);
	ctx.bezierCurveTo(x + w * 0.2, y - h * 0.22, x + w * 0.06, y - h * 0.4, x + w * 0.1, y - h * 0.55);
	ctx.bezierCurveTo(x - w * 0.12, y - h * 0.42, x - w * 0.2, y - h * 0.2, x, y);
	ctx.closePath();
	ctx.fillStyle = INK;
	ctx.globalAlpha = 0.35;
	ctx.fill();
	ctx.globalAlpha = 1;
}

/** Naama joka reagoi. Ilme vaihtuu tason mukaan, ei satunnaisesti. */
function drawFace(ctx: CanvasRenderingContext2D, cx: number, cy: number, r: number, tier: string) {
	ctx.beginPath();
	ctx.arc(cx, cy, r, 0, Math.PI * 2);
	ctx.fillStyle = AMBER;
	ctx.fill();

	ctx.fillStyle = INK;
	const ex = r * 0.36;
	const ey = cy - r * 0.18;
	if (tier === 'cremated') {
		// Isot ymmyrkaiset silmat + auki oleva suu.
		for (const s of [-1, 1]) {
			ctx.beginPath();
			ctx.arc(cx + s * ex, ey, r * 0.15, 0, Math.PI * 2);
			ctx.fill();
		}
		ctx.beginPath();
		ctx.ellipse(cx, cy + r * 0.34, r * 0.26, r * 0.32, 0, 0, Math.PI * 2);
		ctx.fill();
	} else if (tier === 'toasted') {
		// Sirristetyt silmat + vino suu.
		ctx.lineWidth = r * 0.11;
		ctx.strokeStyle = INK;
		ctx.lineCap = 'round';
		for (const s of [-1, 1]) {
			ctx.beginPath();
			ctx.moveTo(cx + s * ex - r * 0.14, ey);
			ctx.lineTo(cx + s * ex + r * 0.14, ey + s * r * 0.07);
			ctx.stroke();
		}
		ctx.beginPath();
		ctx.moveTo(cx - r * 0.3, cy + r * 0.42);
		ctx.quadraticCurveTo(cx, cy + r * 0.26, cx + r * 0.32, cy + r * 0.46);
		ctx.stroke();
	} else {
		// Tyytyvainen: pienet silmat, leve hymy.
		for (const s of [-1, 1]) {
			ctx.beginPath();
			ctx.arc(cx + s * ex, ey, r * 0.11, 0, Math.PI * 2);
			ctx.fill();
		}
		ctx.lineWidth = r * 0.11;
		ctx.strokeStyle = INK;
		ctx.lineCap = 'round';
		ctx.beginPath();
		ctx.arc(cx, cy + r * 0.1, r * 0.42, 0.2 * Math.PI, 0.8 * Math.PI);
		ctx.stroke();
	}
}

export async function renderRoastCard(spec: RoastCardSpec): Promise<Blob> {
	await Promise.all([
		document.fonts.load(bold(60)),
		document.fonts.load(bold(30)),
		document.fonts.load(med(28))
	]);

	const probe = document.createElement('canvas').getContext('2d')!;
	const maxW = W - 2 * MX;
	// Kolme riviä riittää: neljäs vie kortin puhelimen esikatselussa niin
	// pieneksi ettei sitä lue kukaan.
	const body = spec.lines.slice(0, 3);
	const wrapped = body.map((l) => wrapLines(probe, l, med(28), maxW));
	const bodyH = wrapped.reduce((n, ls) => n + ls.length * 40 + 26, 0);

	const ART_H = 300;
	const HEAD_H = 250;
	const H = HEAD_H + ART_H + bodyH + FOOT_H;

	const canvas = document.createElement('canvas');
	canvas.width = W;
	canvas.height = H;
	const ctx = canvas.getContext('2d')!;
	ctx.textBaseline = 'top';

	ctx.fillStyle = INK;
	ctx.fillRect(0, 0, W, H);
	ctx.fillStyle = INK2;
	ctx.fillRect(0, HEAD_H, W, ART_H);

	ctx.font = bold(30);
	ctx.fillStyle = AMBER;
	ctx.fillText('ROAST MY TEAM', MX, 56);
	ctx.font = bold(72);
	ctx.fillStyle = CREAM;
	ctx.fillText(spec.headline, MX, 108);
	ctx.font = med(28);
	ctx.fillStyle = MUTED;
	ctx.fillText(`${spec.score}/100 by the model`, MX, 196);

	// Ryhma keskitetaan LASKEMALLA sen leveys. Ensimmainen versio kiinnitti
	// naaman ja liekit prosenttiosuuksiin (0.34 / 0.58), jolloin yhden
	// liekin kortissa oikea kolmannes oli tyhja ja kolmen liekin kortissa
	// ryhma valui oikealle. Sama kortti eri tasoilla nayttaa nyt samalta.
	const cy = HEAD_H + ART_H / 2;
	const R = 96;
	const flames = spec.tier === 'cremated' ? 3 : spec.tier === 'toasted' ? 2 : 1;
	const FLAME_STEP = 118;
	const FLAME_W = 120;
	const GAP = 64;
	const groupW = R * 2 + GAP + (flames - 1) * FLAME_STEP + FLAME_W;
	const left = (W - groupW) / 2;
	drawFace(ctx, left + R, cy, R, spec.tier);
	for (let i = 0; i < flames; i++) {
		const h = 150 + i * 34;
		drawFlame(ctx, left + R * 2 + GAP + FLAME_W / 2 + i * FLAME_STEP, cy + 110, h);
	}

	ctx.fillStyle = LINE;
	ctx.fillRect(MX, HEAD_H + ART_H, W - 2 * MX, 2);

	let y = HEAD_H + ART_H + 34;
	ctx.font = med(28);
	for (const ls of wrapped) {
		ctx.fillStyle = CREAM;
		for (const line of ls) {
			ctx.fillText(line, MX, y);
			y += 40;
		}
		y += 26;
	}

	ctx.font = med(20);
	ctx.fillStyle = MUTED;
	ctx.fillText('roasted by the GoalIQ match model', MX, H - 88);
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

export async function shareRoastCard(spec: RoastCardSpec): Promise<ShareOutcome> {
	const blob = await renderRoastCard(spec);
	return deliver(blob, spec.fileName);
}
