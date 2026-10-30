// «Пирог до небес»: the fair scene and its sky by height. Farm palette and primitives (makeS/SvgCtx, as Pukh's ballista).
// One SVG per theme, viewBox 0 0 1000 600 = the screen. Screen layers: sky, stars, sun, Earth. World layers (moved by the
// camera, y up = negative): clouds, the fair, scaffolds, tower, crane. The game (qw_farm/static/pie-game.js) only places
// these drawings: <use> of the scaffold tiers and height plates, tower layers in the corzh palette, transforms.
// The corzh itself is korzhMarkup from pie-game.js: one recipe for the hanging corzh, tower layers and cut pieces.
// Geometry contract (must match GEOM in pie-game.js): plate top 470, layer 30, rail 220 at height 0 (rail = 220 - 30·h),
// hanging corzh top = rail + 100, scaffold tiers 30 high from the ground 520 at x 24 and 896 (80 wide).
import {makeS} from '../village/common.js';
import {SvgCtx} from '../village/svg_ctx.js';
import {korzhMarkup} from '/static/pie-game.js';

const KORZH = {
 day: {sponge: '#d9a35f', sponge2: '#e3b16e', glaze: '#fbf1dc', jam: '#d98a6a', berry: '#c0544a', edge: '#8f5a2c', edgeContrast: '#3f230b'},
 night: {sponge: '#c18c55', sponge2: '#cb9861', glaze: '#ece0c4', jam: '#c27a5e', berry: '#b0534a', edge: '#6e4524', edgeContrast: '#2b1806'},
};
// Sky colours by height in layers: [height, top, middle, bottom]. Fair → clouds → upper sky → space.
const SKY = {
 day: [[0, '#cfe3d4', '#e6ecd3', '#f6edcc'], [10, '#a8cfe2', '#c8e2e8', '#e8f0e0'], [20, '#5d86b4', '#8db3d2', '#c6dde6'],
  [30, '#24366a', '#3c5a8c', '#7095bd'], [40, '#0c122c', '#141d40', '#22305c']],
 night: [[0, '#25394a', '#3d5459', '#637668'], [10, '#1f3249', '#2b425a', '#4a6273'], [20, '#152240', '#1f3354', '#3a5476'],
  [30, '#0b1430', '#142142', '#263c64'], [40, '#070a1a', '#0b1128', '#121c3a']],
};
const STARS = {day: [[0, 0], [22, 0], [30, .85], [38, 1]], night: [[0, .7], [20, .8], [30, 1]]};
// Screen y of the top of the Earth limb by height: hidden under the fair, rising as a curved horizon, a planet below in space.
const EARTH = [[0, 760], [18, 720], [24, 560], [32, 452], [44, 404]];

function rng(seed) { let s = seed >>> 0; return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 4294967296); }

export function pieScene(night = false) {
 const c = new SvgCtx('pie'), s = makeS(c), theme = night ? 'night' : 'day', k = KORZH[theme];
 const p = night ? {
  hill: '#6a875e', hillFar: '#77926c', ground: '#65824f', grass: '#78945f', path: '#a39a76',
  wood: '#a68c62', woodDark: '#86704f', woodLight: '#bda57e', rope: '#5f5040', stone: '#7d8273', stoneDark: '#666b5e',
  cream: '#e8d9b1', crust: '#cbb07e', crustLight: '#e0c898', berry: '#b56a5f', gold: '#e8d08a', tent: '#8f8a70', tentStripe: '#b57a6c',
  leaf: '#5d7a55', leafDark: '#4f6a49', lit: '#f2df9f', glow: '#f2df9f', plate: '#556f62', plateRim: '#c9b98f', cloth: '#d9cba4',
  cloud: '#55697e', cloudTop: '#70849a', cloudFront: '#61758a', cirrus: '#4a5f7e', star: '#f4efd2',
  sun: '#eee6bf', sunDot: '#d6d4b3', ocean: '#1d3653', land: '#2c4a3f', landLight: '#35574a', earthCloud: '#5f7590', atmo: '#5c88bc', city: '#f2df9f',
 } : {
  hill: '#a3c587', hillFar: '#bcd3a1', ground: '#8fba73', grass: '#a3c587', path: '#dcca98',
  wood: '#b88a5b', woodDark: '#9a7049', woodLight: '#d0aa7c', rope: '#6d5a43', stone: '#c4c6a8', stoneDark: '#a8aa8e',
  cream: '#f3ead2', crust: '#e7c78f', crustLight: '#f0d7a6', berry: '#c96a5a', gold: '#d9a64d', tent: '#e8d9ae', tentStripe: '#c98d7a',
  leaf: '#7c9d83', leafDark: '#6b8d73', lit: '#f9e3a1', glow: '#f9e3a1', plate: '#6f8f6b', plateRim: '#e6dcc0', cloth: '#f3ead2',
  cloud: '#f4efdc', cloudTop: '#fbf8ee', cloudFront: '#f7f3e6', cirrus: '#e9eef0', star: '#f8f4dc',
  sun: '#f9e3a1', sunDot: '#f9e3a1', ocean: '#5b8fb0', land: '#8fb07a', landLight: '#a3c587', earthCloud: '#f1f4ef', atmo: '#bfe0f2', city: '#f9e3a1',
 };
 const poly = (pts, col) => s.poly(pts.map(([x, y]) => ({x, y})), col);
 const rect = (x, y, w, h, col) => poly([[x, y], [x + w, y], [x + w, y + h], [x, y + h]], col);
 const raw = svg => c.out.push(svg);
 const path = (d, col, extra = '') => raw(`<path d="${d}" fill="${col}"${extra}/>`);
 const line = (x1, y1, x2, y2, col, w = 2) => s.line(x1, y1, x2, y2, col, w);
 const dot = (x, y, rx, ry, col) => s.ellipse(x, y, rx, ry, col);
 const rrect = (x, y, w, h, r, col, extra = '') => raw(`<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="${r}" fill="${col}"${extra}/>`);
 const group = (id, fn, attrs = '') => { raw(`<g id="pie-${id}"${attrs}>`); fn(); raw('</g>'); };
 // A drawing into <defs>: the game places it with <use href="#id">.
 const def = (id, fn) => { const saved = c.out; c.out = []; fn(); const inner = c.out.join(''); c.out = saved; c.defs.push({id, svg: () => `<g id="${id}">${inner}</g>`}); };
 const cloud = (x, y, q, col = p.cloud, top = p.cloudTop) => {
  dot(x, y, 46 * q, 13 * q, col); dot(x - 16 * q, y - 7 * q, 22 * q, 17 * q, col); dot(x + 15 * q, y - 11 * q, 25 * q, 21 * q, col);
  dot(x + 34 * q, y - 2 * q, 16 * q, 11 * q, col); dot(x + 12 * q, y - 15 * q, 15 * q, 12 * q, top); dot(x - 18 * q, y - 10 * q, 11 * q, 9 * q, top);
 };

 // ---- defs: corzh, scaffold tiers, height plate, sky gradient, Earth clip.
 def('pie-korzh', () => raw(korzhMarkup(k, -280, 0, 560, 0, false)));
 const tier = (brace, deck) => () => {
  rect(4, 0, 8, 30, p.wood); rect(68, 0, 8, 30, p.wood); rect(6, 0, 2, 30, p.woodLight); rect(70, 0, 2, 30, p.woodLight);
  if (brace === 'a') line(12, 5, 68, 29, p.woodDark, 4); else line(68, 5, 12, 29, p.woodDark, 4);
  if (deck) { rect(-8, -3, 96, 9, p.wood); rect(-8, -3, 96, 3, p.woodLight); for (const x of [16, 40, 64]) rect(x, -1, 1.5, 7, p.woodDark); }
  else rect(0, 0, 80, 5, p.woodLight);
  dot(8, 2, 2.2, 2.2, p.woodDark); dot(72, 2, 2.2, 2.2, p.woodDark);
 };
 def('pie-tier-a', tier('a', false)); def('pie-tier-b', tier('b', false)); def('pie-tier-deck', tier('a', true));
 def('pie-plate', () => {
  line(0, -30, 0, -14, p.rope, 2); rrect(-30, -16, 60, 32, 6, p.woodDark); rrect(-27, -13, 54, 26, 4, p.cream); dot(0, -10, 2, 2, p.woodDark);
 });
 c.defs.push({id: 'pie-skyg', svg: () => `<linearGradient id="pie-skyg" gradientUnits="userSpaceOnUse" x1="0" y1="0" x2="0" y2="600">` +
  SKY[theme][0].slice(1).map((col, i) => `<stop id="pie-sky-${i}" offset="${[0, .55, 1][i]}" stop-color="${col}"/>`).join('') + '</linearGradient>'});
 c.defs.push({id: 'pie-earth-clip', svg: () => `<clipPath id="pie-earth-clip" clipPathUnits="userSpaceOnUse"><circle cx="500" cy="1500" r="1500"/></clipPath>`});
 c.defs.push({id: 'pie-scaffold-clip', svg: () => `<clipPath id="pie-scaffold-clip" clipPathUnits="userSpaceOnUse"><rect id="pie-scaffold-cliprect" x="0" y="224" width="1000" height="6000"/></clipPath>`});

 // ---- screen layers
 group('sky', () => rrect(0, 0, 1000, 600, 0, 'url(#pie-skyg)'));
 group('stars', () => {
  const r = rng(night ? 71 : 37);
  for (let i = 0; i < 70; i++) { const x = r() * 1000, y = r() * 600, q = .9 + r() * 1.6; dot(+x.toFixed(1), +y.toFixed(1), q, q, p.star); }
  for (const [x, y] of [[120, 80], [690, 150], [420, 40], [930, 300], [260, 330]]) {
   poly([[x, y - 9], [x + 2, y - 2], [x + 9, y], [x + 2, y + 2], [x, y + 9], [x - 2, y + 2], [x - 9, y], [x - 2, y - 2]], p.star);
  }
 }, ` opacity="${STARS[theme][0][1]}"`);
 group('sun', () => {
  if (night) { dot(818, 92, 30, 30, p.sun); dot(806, 86, 7, 7, p.sunDot); dot(826, 102, 5, 5, p.sunDot); }
  else { dot(822, 92, 52, 52, '#fbecc0'); dot(822, 92, 39, 39, p.sun); }
 });
 // The Earth: drawn with its limb at y=0; the game moves it down/up by height. Atmosphere rings, ocean, land, clouds.
 group('earth', () => {
  for (const [dr, op] of [[64, .18], [38, .3], [16, .55]]) raw(`<circle cx="500" cy="1500" r="${1500 + dr}" fill="${p.atmo}" fill-opacity="${op}"/>`);
  raw(`<circle cx="500" cy="1500" r="1500" fill="${p.ocean}"/>`);
  raw('<g clip-path="url(#pie-earth-clip)">');
  path('M-40 40Q60 -6 170 18Q250 34 300 70Q330 120 250 150Q160 170 90 140Q10 120 -40 150Z', p.land);
  path('M120 60Q170 40 220 62Q240 90 200 104Q150 110 120 90Z', p.landLight);
  path('M560 6Q660 -10 760 14Q860 36 900 80Q930 130 860 160Q790 186 720 150Q690 110 620 104Q540 96 530 56Q530 20 560 6Z', p.land);
  path('M640 40Q700 30 760 50Q780 74 740 86Q690 92 650 72Z', p.landLight);
  path('M380 120Q430 104 470 130Q480 160 430 170Q390 168 380 150Z', p.land);
  for (const [x, y, rx, ry] of [[90, 30, 70, 9], [330, 46, 90, 10], [500, 90, 60, 8], [780, 112, 80, 9], [960, 40, 70, 9], [250, 120, 50, 7], [640, 150, 70, 8]]) {
   dot(x, y, rx, ry, p.earthCloud); dot(x - rx * .3, y - ry * .6, rx * .4, ry * .8, p.earthCloud);
  }
  if (night) for (const [x, y] of [[60, 70], [110, 92], [180, 66], [210, 112], [600, 40], [650, 66], [700, 110], [760, 96], [820, 120], [860, 70], [420, 140], [150, 130]])
   { dot(x, y, 3, 2, p.city); dot(x + 6, y + 3, 2, 1.5, p.city); }
  raw('</g>');
 }, ' transform="translate(0 760)"');

 // ---- world layers: the game sets translate(0 camera)
 raw('<g id="pie-world">');
 group('clouds', () => {
  // Small clouds of the fair sky, then the cloud band (tower heights ≈ 12–27 layers), then thin high streaks.
  for (const [x, y, q] of [[160, 118, .8], [390, 74, .62], [930, 210, .5]]) cloud(x, y, q);
  for (const [x, y, q] of [[620, 40, 1.3], [90, -20, 1.6], [860, -70, 1.9], [330, -110, 1.5], [560, -170, 2.2], [150, -220, 2],
   [900, -240, 1.6], [420, -290, 1.9], [700, -330, 1.4], [70, -360, 1.3], [270, -410, 1.1], [820, -430, 1]]) cloud(x, y, q);
  // High thin streaks below the space zone (tower ≈ 28–31 layers); world clouds stay under the tower top in space.
  for (const [x, y, w] of [[220, -380, 140], [760, -420, 170], [470, -455, 120], [90, -470, 110]]) {
   raw(`<g fill="${p.cirrus}" fill-opacity=".75">`);
   dot(x, y, w, 4, p.cirrus); dot(x + w * .35, y - 6, w * .5, 3, p.cirrus); dot(x - w * .4, y + 5, w * .45, 3, p.cirrus);
   raw('</g>');
  }
 });
 group('ground', () => {
  path('M0 360Q150 300 300 318Q430 332 540 300Q680 262 820 300Q910 322 1000 350V600H0Z', p.hillFar);
  path('M0 430Q160 386 300 398Q450 412 560 386Q700 356 830 390Q920 410 1000 432V600H0Z', p.hill);
  // Two trees frame the square behind the scaffolds.
  rect(58, 340, 14, 150, p.woodDark); dot(64, 312, 56, 52, p.leaf); dot(36, 340, 30, 27, p.leafDark); dot(96, 342, 28, 25, p.leaf);
  rect(930, 330, 14, 160, p.woodDark); dot(936, 300, 58, 54, p.leaf); dot(964, 330, 30, 28, p.leafDark); dot(904, 334, 28, 26, p.leaf);
  path('M0 500Q240 470 500 482Q760 494 1000 478V600H0Z', p.ground);
  // Agata's striped tent on the left.
  rect(150, 352, 200, 100, p.tent);
  poly([[176, 452], [176, 384], [250, 346], [324, 384], [324, 452]], night ? '#4d4a3d' : '#6e6a58');
  poly([[164, 452], [164, 378], [250, 334], [336, 378], [336, 452], [324, 452], [324, 386], [250, 348], [176, 386], [176, 452]], p.cream);
  // Striped roof: six wedges from the peak, a scalloped hem.
  for (let i = 0; i < 6; i++) poly([[250, 270], [130 + i * 40, 362], [170 + i * 40, 362]], i % 2 ? p.tent : p.tentStripe);
  for (let i = 0; i < 6; i++) dot(150 + i * 40, 362, 20, 8, i % 2 ? p.tent : p.tentStripe);
  line(250, 270, 250, 238, p.woodDark, 4); poly([[250, 238], [274, 246], [250, 254]], p.berry);
  // Pie stall on the right.
  rect(700, 360, 170, 96, p.wood); rect(706, 366, 158, 62, p.woodDark);
  for (const y of [384, 410]) line(710, y, 860, y, p.cream, 3);
  for (const [x, y] of [[736, 382], [778, 382], [820, 382], [756, 408], [804, 408]]) { dot(x, y, 13, 7, p.crust); dot(x, y - 3, 9, 4, p.crustLight); }
  poly([[688, 360], [716, 312], [854, 312], [882, 360]], p.tentStripe);
  for (let i = 0; i < 5; i++) { const x = 712 + i * 34; poly([[x, 312], [x + 17, 312], [x + 8.5, 292], [x, 312]], p.cream); }
  line(700, 360, 700, 476, p.woodDark, 4); line(870, 360, 870, 476, p.woodDark, 4);
  // Bunting from the tent to the stall, behind the tower.
  path('M250 268Q520 330 785 310', 'none', ` stroke="${p.cream}" stroke-width="2"`);
  for (let i = 0; i < 8; i++) {
   const t = (i + .5) / 8, x = (1 - t) * (1 - t) * 250 + 2 * (1 - t) * t * 520 + t * t * 785, y = (1 - t) * (1 - t) * 268 + 2 * (1 - t) * t * 330 + t * t * 310;
   poly([[x - 13, y - 1], [x + 13, y - 1], [x, y + 26]], i % 3 === 0 ? p.berry : i % 3 === 1 ? p.gold : p.leaf);
  }
  for (const [x, y] of [[160, 430], [860, 352]]) {
   line(x, y, x, y + 14, p.woodDark, 2); if (night) dot(x, y + 22, 17, 19, p.glow + '40'); dot(x, y + 22, 8, 10, night ? p.lit : p.cream);
  }
  path('M0 556Q180 526 360 528T720 518Q860 514 1000 530V600H0Z', p.grass);
  path('M150 530Q360 512 520 518T880 512L894 528Q700 536 540 534T170 552Z', p.path);
  // Stone footings of the scaffolds.
  for (const x of [16, 888]) { rect(x, 516, 96, 14, p.stoneDark); rect(x + 4, 514, 88, 6, p.stone); }
  // The long fair table with a cloth and the cake stand the tower stands on (plate top y=470).
  rect(120, 504, 760, 18, p.wood); rect(120, 504, 760, 5, p.woodLight);
  rect(134, 522, 732, 50, p.cloth);
  for (let i = 0; i < 10; i++) dot(170 + i * 73, 572, 37, 9, p.cloth);
  line(150, 522, 150, 590, p.woodDark, 10); line(850, 522, 850, 590, p.woodDark, 10);
  dot(500, 503, 64, 6, p.plate); rect(490, 474, 20, 30, p.plate);
  dot(500, 478, 300, 11, p.plate); dot(500, 472, 296, 9, p.plateRim);
 });
 // Scaffolds: tiers are <use> of #pie-tier-*; the first ten (height 0) are drawn here, the game adds one per layer.
 raw('<g id="pie-scaffold" clip-path="url(#pie-scaffold-clip)">');
 for (const [id, x] of [['l', 24], ['r', 896]]) {
  raw(`<g id="pie-scaffold-${id}">`);
  for (let j = 0; j < 10; j++) raw(`<use href="#${(j + 1) % 5 === 0 ? 'pie-tier-deck' : j % 2 ? 'pie-tier-b' : 'pie-tier-a'}" x="${x}" y="${520 - 30 * (j + 1)}"/>`);
  raw('</g>');
 }
 group('marks', () => {}, ` data-ink="${night ? '#2b2116' : '#4a3520'}"`);
 raw('</g>');
 group('clouds-front', () => {
  for (const [x, y, q] of [[30, -130, 1.2], [975, -270, 1.4], [20, -380, 1], [985, -60, .9]]) cloud(x, y, q, p.cloudFront, p.cloudTop);
 });
 group('tower', () => {}, Object.entries(k).map(([key, v]) => ` data-${key.replace(/[A-Z]/g, m => '-' + m.toLowerCase())}="${v}"`).join(''));
 group('cuts', () => {});
 group('falling', () => raw('<use href="#pie-korzh"/>'), ' display="none"');
 // Gantry crane: beam on the scaffold tops, winch hut, pennant; the trolley (x = 500 here) carries the hoist and corzh.
 group('crane', () => {
  rect(8, 220, 984, 18, p.wood); rect(8, 220, 984, 5, p.woodLight); rect(8, 235, 984, 3, p.woodDark);
  for (const x of [8, 984]) rect(x, 216, 8, 26, p.woodDark);
  for (let x = 120; x < 900; x += 80) dot(x, 229, 2, 2, p.woodDark);
  rect(900, 176, 70, 44, p.cream); poly([[894, 180], [935, 150], [976, 180]], p.tentStripe); rect(926, 192, 18, 28, p.woodDark);
  dot(912, 204, 9, 9, p.woodDark); dot(912, 204, 4, 4, p.woodLight);
  line(38, 220, 38, 156, p.woodDark, 4); poly([[38, 158], [74, 168], [38, 180]], p.berry);
  raw('<g id="pie-trolley">');
  rect(468, 198, 64, 17, p.woodDark); rect(468, 198, 64, 5, p.woodLight); rect(474, 203, 52, 9, p.wood);
  dot(482, 216, 6, 6, p.rope); dot(518, 216, 6, 6, p.rope); dot(482, 216, 2, 2, p.woodLight); dot(518, 216, 2, 2, p.woodLight);
  line(500, 214, 500, 284, p.rope, 3);
  raw(`<circle cx="500" cy="291" r="7" fill="none" stroke="${p.rope}" stroke-width="3"/>`);
  raw('<g id="pie-layer">');
  line(495, 296, 330, 321, p.rope, 2.5); line(505, 296, 670, 321, p.rope, 2.5);
  raw('<use href="#pie-korzh" x="500" y="320"/>');
  raw('</g></g>');
 });
 group('front', () => {
  path('M0 584Q250 566 500 574T1000 566V600H0Z', p.grass);
  for (const [x, y] of [[180, 594], [330, 588], [654, 590], [799, 596], [963, 590]]) { line(x, y, x - 4, y - 10, p.ground, 2); line(x, y, x + 5, y - 8, p.ground, 2); }
  dot(214, 578, 7, 3, p.stone); dot(690, 582, 7, 3, p.stone);
 });
 raw('</g>');
 const data = ` data-sky='${JSON.stringify(SKY[theme])}' data-stars='${JSON.stringify(STARS[theme])}' data-earth='${JSON.stringify(EARTH)}'`;
 return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 600" role="img" aria-label="Пирог до небес: ярмарка, леса с краном и башня из коржей" data-theme="${theme}"${data}><title>Пирог до небес · сцена</title>${c.svg()}</svg>`;
}

export function render({night = false} = {}) { return {svg: pieScene(night)}; }
