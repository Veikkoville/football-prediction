/**
 * Joukkueiden primary-värit lyhytkoodilla (#113) — web-vastine mobiilin
 * lib/teamMeta.ts:lle (generoitu siitä 17.7, sama lähde: klubien primary-
 * värit = julkista tietoa, ei lisensointia). Tuntematon lyhenne →
 * deterministinen hash-väri (sama konventio kuin mobiilissa, ei kaatumista).
 */

export interface TeamColor {
	color: string;
	textColor: string;
}

const BY_SHORT: Record<string, [string, string]> = {
	ARS: ['#EF0107', '#FFFFFF'],
	AVL: ['#670E36', '#FFFFFF'],
	BOU: ['#DA291C', '#FFFFFF'],
	BRE: ['#E30613', '#FFFFFF'],
	BHA: ['#0057B8', '#FFFFFF'],
	BUR: ['#6C1D45', '#FFFFFF'],
	CHE: ['#034694', '#FFFFFF'],
	CRY: ['#1B458F', '#FFFFFF'],
	EVE: ['#003399', '#FFFFFF'],
	FUL: ['#000000', '#FFFFFF'],
	IPS: ['#4172B5', '#FFFFFF'],
	LEE: ['#FFCD00', '#1D428A'],
	LEI: ['#003090', '#FFFFFF'],
	LIV: ['#C8102E', '#FFFFFF'],
	MCI: ['#6CABDD', '#FFFFFF'],
	MUN: ['#DA291C', '#FFFFFF'],
	NEW: ['#241F20', '#FFFFFF'],
	NFO: ['#DD0000', '#FFFFFF'],
	SHU: ['#EE2737', '#FFFFFF'],
	SOU: ['#D71920', '#FFFFFF'],
	SUN: ['#EB172B', '#FFFFFF'],
	TOT: ['#132257', '#FFFFFF'],
	WHU: ['#7A263A', '#FFFFFF'],
	WOL: ['#FDB913', '#231F20'],
	RMA: ['#00529F', '#FFFFFF'],
	BAR: ['#A50044', '#FFFFFF'],
	ATM: ['#CB3524', '#FFFFFF'],
	ATH: ['#EE2523', '#FFFFFF'],
	RSO: ['#143C8B', '#FFFFFF'],
	BET: ['#0BB363', '#FFFFFF'],
	VIL: ['#FFE667', '#005187'],
	VAL: ['#F1A41C', '#FFFFFF'],
	SEV: ['#D6011F', '#FFFFFF'],
	CEL: ['#8AC4EB', '#FFFFFF'],
	OSA: ['#AB1F2E', '#FFFFFF'],
	RAY: ['#C0202E', '#FFFFFF'],
	MAL: ['#C81618', '#FFFFFF'],
	GET: ['#005CA9', '#FFFFFF'],
	ESP: ['#0070B8', '#FFFFFF'],
	ALA: ['#0A4998', '#FFFFFF'],
	GIR: ['#CD2230', '#FFFFFF'],
	LPA: ['#FFE301', '#003DA5'],
	LEG: ['#005397', '#FFFFFF'],
	VLD: ['#5B1F66', '#FFFFFF'],
	LEV: ['#0079B8', '#FFFFFF'],
	ELC: ['#048741', '#FFFFFF'],
	OVI: ['#005CA9', '#FFFFFF'],
	BAY: ['#DC052D', '#FFFFFF'],
	BVB: ['#FDE100', '#000000'],
	RBL: ['#DD0741', '#FFFFFF'],
	SGE: ['#E1000F', '#FFFFFF'],
	WOB: ['#65B32E', '#FFFFFF'],
	VFB: ['#E32219', '#FFFFFF'],
	SCF: ['#5B5B5F', '#FFFFFF'],
	FCA: ['#BA3733', '#FFFFFF'],
	FCH: ['#E2231A', '#FFFFFF'],
	TSG: ['#1961B5', '#FFFFFF'],
	SVW: ['#1D9053', '#FFFFFF'],
	BMG: ['#000000', '#FFFFFF'],
	FCU: ['#E40115', '#FFFFFF'],
	KOE: ['#ED1C24', '#FFFFFF'],
	HSV: ['#0F4F9C', '#FFFFFF'],
	STP: ['#65462E', '#FFFFFF'],
	KSV: ['#005A9E', '#FFFFFF'],
	BOC: ['#005CA9', '#FFFFFF'],
	SVD: ['#1C4E9C', '#FFFFFF'],
	JUV: ['#000000', '#FFFFFF'],
	INT: ['#0E6CB1', '#FFFFFF'],
	MIL: ['#FB090B', '#FFFFFF'],
	NAP: ['#0098D7', '#FFFFFF'],
	ROM: ['#8E1F2F', '#FFFFFF'],
	LAZ: ['#87CEEB', '#FFFFFF'],
	FIO: ['#592A8A', '#FFFFFF'],
	ATA: ['#1E1E1E', '#FFFFFF'],
	BOL: ['#8A1538', '#FFFFFF'],
	TOR: ['#7A1F2B', '#FFFFFF'],
	UDI: ['#000000', '#FFFFFF'],
	GEN: ['#C8102E', '#FFFFFF'],
	VER: ['#FFE600', '#1565C0'],
	MZA: ['#DA291C', '#FFFFFF'],
	CAG: ['#A8123A', '#FFFFFF'],
	COM: ['#0066B3', '#FFFFFF'],
	EMP: ['#0073C2', '#FFFFFF'],
	LEC: ['#FFD700', '#A8123A'],
	PAR: ['#FCE100', '#1F4FA0'],
	VEN: ['#F39200', '#000000'],
	SAS: ['#118B3A', '#FFFFFF'],
	CRE: ['#A8123A', '#FFFFFF'],
	PIS: ['#003DA5', '#FFFFFF'],
	PSG: ['#004170', '#FFFFFF'],
	ASM: ['#D8011D', '#FFFFFF'],
	NIC: ['#A8123A', '#FFFFFF'],
	REN: ['#E2231A', '#000000'],
	LEN: ['#EFB810', '#A8123A'],
	LIL: ['#E0152B', '#FFFFFF'],
	BRT: ['#E0152B', '#FFFFFF'],
	NTS: ['#F8C300', '#1F4FA0'],
	RMS: ['#E0152B', '#FFFFFF'],
	TFC: ['#5B2F8A', '#FFFFFF'],
	MTP: ['#1B4DA0', '#FF6600'],
	STR: ['#0066CC', '#FFFFFF'],
	ANG: ['#000000', '#FFFFFF'],
	AUX: ['#005CA9', '#FFFFFF'],
	ASE: ['#118B3A', '#FFFFFF'],
	HAC: ['#5BB2E1', '#FFFFFF'],
	MTZ: ['#A8123A', '#FFFFFF'],
	PFC: ['#005CA9', '#FFFFFF'],
	LOR: ['#F18E00', '#000000']
};

/** Deterministinen tumma fallback-väri (peili mobiilin hashColor-konventiosta). */
function hashColor(name: string): string {
	let h = 0;
	for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) & 0xffffff;
	const hue = h % 360;
	return `hsl(${hue}, 45%, 32%)`;
}

export function teamColorByShort(short: string): TeamColor {
	const hit = BY_SHORT[short?.toUpperCase?.() ?? ''];
	if (hit) return { color: hit[0], textColor: hit[1] };
	return { color: hashColor(short || '?'), textColor: '#FFFFFF' };
}
