// Сорока-коробейница (FARM_VILLAGE_MINIGAMES.md §2): the travelling peddler's cart and the magpie herself.
// Both are live layers of the game, shown only during her visit (html[data-merchant], README «Сорока»):
//   cart   — world-scale vector layer (village-merchant.svg): vm-base under the night tint, vm-night (lantern glow) above it;
//   figure — fixed-size DOM figure like the player's (frames vm-stand / vm-call), readable on a phone.
// Drawn with the farm's own primitives (B = scene_buildings.js, s = FarmScene methods) into the SVG recorder.
import {FarmScene} from '/static/scene.js';
import {SvgCtx} from './svg_ctx.js';

const MAGPIE = {body: '#454b57', belly: '#f1eee6', wing: '#5f7f9a', wingLight: '#7e9db5', patch: '#eef0ee', tail: '#4f6b78',
  tailLight: '#6f8f9a', leg: '#5a5148', beak: '#5a5148', eye: '#1f2328', scarf: '#d98a7a', scarfDark: '#c47565', dot: '#f6e7d8',
  bead: '#e2b04a', shadow: '#41623530'};
const DYES = [['#5f6c94', '#7f8cb4'], ['#b8574c', '#d07a6e'], ['#e2b04a', '#efc96e']];   // indigo, madder, saffron

const scene = c => { const s = Object.create(FarmScene.prototype); s.c = c; s.time = 0; s.motion = false; s.inStatic = true; s.shadowLevel = 0; return s };

// ---------- the cart (tile coordinates of the scene) ----------
export function merchantCart(V) {
  // V: {B, P, matrix, box:[x0,y0,x1,y1]}
  const {B, P} = V, [x0, y0, x1, y1] = V.box, c = new SvgCtx('vm'), s = scene(c);
  const wheel = (xc, Y, zc, r) => {   // a wheel standing in the plane y = Y (the cart's near long side)
    const ring = (rr, dz = 0) => Array.from({length: 20}, (_, i) => { const a = i / 20 * Math.PI * 2; return P(xc + rr / 40 * Math.cos(a), Y, zc + dz + rr * Math.sin(a)) });
    s.poly(ring(r), '#7e6044'); s.poly(ring(r - 1.6), '#b48f66'); s.poly(ring(r - 2.6), '#9c7d58');
    for (let i = 0; i < 6; i++) { const a = i / 6 * Math.PI, p = P(xc + (r - 2) / 40 * Math.cos(a), Y, zc + (r - 2) * Math.sin(a)), q = P(xc - (r - 2) / 40 * Math.cos(a), Y, zc - (r - 2) * Math.sin(a)); s.line(p.x, p.y, q.x, q.y, '#c9a672', 1.2) }
    const h = P(xc, Y, zc); s.ellipse(h.x, h.y, 2, 2, '#6f5640');
  };
  c.group('vm-base');
  B.shadowAt(s, x0, y0, x1, y1, 46, 18);
  for (const yy of [y0 + .22, y1 - .22]) B.L(s, x0, yy, 12, x0 - .75, yy, 1, '#9c7d58', 2.2);           // shafts resting on the ground
  B.L(s, x0 - .7, y0 + .22, 2, x0 - .7, y1 - .22, 2, '#8a6c4c', 1.8);
  // the box: painted planks with a folk-flower band, posts and a striped canopy in the magpie's slate-blue and cream
  B.fullBox(s, '#c9a672', x0, y0, x1, y1, 8, 22, '#d8b886');
  B.boards(s, 'y', y1, x0, x1, 8, 22, 4, 'rgba(80,55,30,.25)'); B.boards(s, 'x', x1, y0, y1, 8, 22, 4, 'rgba(70,45,25,.28)');
  B.Q(s, '#e8d6b0', [x0 + .05, y1 + .005, 13, x1 - .05, y1 + .005, 13, x1 - .05, y1 + .005, 18, x0 + .05, y1 + .005, 18]);
  for (let i = 0; i < 6; i++) { const p = P(x0 + .16 + i * (x1 - x0 - .3) / 5, y1 + .01, 15.5); s.ellipse(p.x, p.y, 2.2, 2, ['#d98a7a', '#e2b04a', '#8fae86'][i % 3]); s.ellipse(p.x, p.y, .8, .8, '#f6efe0') }
  for (const [a, b] of [[x0 + .06, y0 + .06], [x1 - .06, y0 + .06]]) B.L(s, a, b, 22, a, b, 50, '#8a6c4c', 2.2);
  // goods on the box: little boxes with ribbons, paper bundles, seed packets, jars of dye (indigo, madder, saffron)
  B.fullBox(s, '#a9c6d6', x0 + .14, y0 + .18, x0 + .44, y0 + .46, 22, 29, '#c3d9e4'); B.L(s, x0 + .29, y0 + .46, 22, x0 + .29, y0 + .46, 29, '#d98a7a', 1.2);
  B.fullBox(s, '#d9a7bb', x0 + .5, y0 + .2, x0 + .74, y0 + .42, 22, 27, '#e7c3d1'); B.L(s, x0 + .62, y0 + .42, 22, x0 + .62, y0 + .42, 27, '#f6efe0', 1.2);
  B.fullBox(s, '#e8c9a0', x0 + .2, y0 + .22, x0 + .4, y0 + .4, 29, 33, '#f1dcb8');
  const bundle = (x, y, col) => { const p = P(x, y, 25); s.ellipse(p.x, p.y, 6, 4.2, col); s.ellipse(p.x - 1.4, p.y - 1.2, 2.6, 1.6, '#ffffff4d'); s.line(p.x - 5, p.y, p.x + 5, p.y, '#9c7d58', .9); s.line(p.x, p.y - 4, p.x, p.y + 4, '#9c7d58', .9) };
  bundle(x0 + .9, y0 + .3, '#e6dcc0'); bundle(x0 + .78, y0 + .62, '#d6c7a8');
  for (const [k, [col, top]] of DYES.entries()) B.cyl(s, x1 - .2 - (k % 2) * .18, y0 + .24 + k * .2, .07, 22, 29, col, top);
  for (let i = 0; i < 4; i++) {   // seed packets standing along the front edge, each with a coloured seed picture
    const xa = x0 + .12 + i * .2, xb = xa + .15, Y = y1 - .1;
    B.Q(s, '#f1e6c9', [xa, Y, 22, xb, Y, 22, xb, Y, 31, xa, Y, 31]);
    const p = P((xa + xb) / 2, Y, 26.5); s.ellipse(p.x, p.y, 2.3, 2.3, ['#d35a45', '#8fae86', '#e2b04a', '#a98fc6'][i]);
  }
  for (const [a, b] of [[x0 + .06, y1 - .06], [x1 - .06, y1 - .06]]) B.L(s, a, b, 22, a, b, 44, '#9c7d58', 2.2);
  B.awning(s, x0 - .08, x1 + .08, y0, 50, 1.02, 8, '#f4ece0', MAGPIE.wing, 6);
  // magpie pennant on the back post and a lantern hanging from the front-right post
  const fp = P(x1 - .06, y0 + .06, 50); s.line(fp.x, fp.y, fp.x, fp.y - 12, '#8a6c4c', 1.4);
  s.poly([{x: fp.x, y: fp.y - 12}, {x: fp.x + 12, y: fp.y - 9}, {x: fp.x, y: fp.y - 6}], MAGPIE.body); s.poly([{x: fp.x, y: fp.y - 9.6}, {x: fp.x + 8, y: fp.y - 8.6}, {x: fp.x, y: fp.y - 7.6}], MAGPIE.patch);
  const lp = P(x1 + .02, y1 - .06, 41), lx = lp.x + 6, ly = lp.y + 4;
  s.line(lp.x, lp.y, lx, lp.y, '#5f4630', 1.4); s.line(lx, lp.y, lx, ly - 4, '#4e3a27', .9);
  s.poly([{x: lx - 3, y: ly - 4}, {x: lx + 3, y: ly - 4}, {x: lx + 2.6, y: ly + 3}, {x: lx - 2.6, y: ly + 3}], '#d9c58c');
  s.poly([{x: lx - 4, y: ly - 4}, {x: lx, y: ly - 7}, {x: lx + 4, y: ly - 4}], '#4e3a27');
  // near wheels last: they stand in front of the box side
  wheel(x0 + .3, y1 + .04, 8, 8); wheel(x1 - .3, y1 + .04, 8, 8);
  c.end();
  c.group('vm-night');                                                     // the lantern lit, above the night tint
  s.ellipse(lx, ly, 16, 12, 'rgba(255,200,95,.25)'); s.ellipse(lx, ly, 6, 5, 'rgba(255,226,160,.5)');
  s.poly([{x: lx - 3, y: ly - 4}, {x: lx + 3, y: ly - 4}, {x: lx + 2.6, y: ly + 3}, {x: lx - 2.6, y: ly + 3}], '#ffe7a0');
  c.end();
  const m = V.matrix.map(v => +v.toFixed(4)).join(' ');
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 2400 1800" class="vm-art" aria-hidden="true" focusable="false"><g transform="matrix(${m})">${c.svg()}</g></svg>`;
}

// ---------- the magpie (farm px, feet at 0,0, facing right; viewBox -20 -50 40 54) ----------
function magpie(s, pose) {
  const C = MAGPIE, call = pose === 'call';
  s.ellipse(1, .6, 10, 3, C.shadow);
  // long tail behind, legs
  s.poly([{x: -3.6, y: -16}, {x: -12.4, y: -9.4}, {x: -15.6, y: -7.6}, {x: -14.4, y: -5.6}, {x: -10.6, y: -6.6}, {x: -1.6, y: -10.6}], C.tail);   // wedge tail
  s.poly([{x: -4.6, y: -14.4}, {x: -13.4, y: -8.4}, {x: -14.6, y: -7.2}, {x: -11, y: -7.8}, {x: -3.4, y: -12.2}], C.tailLight);
  s.line(-1.6, -8, -2.2, -1.2, C.leg, 1.6); s.line(2.2, -8, 2.8, -1.2, C.leg, 1.6);
  s.ellipse(-1.6, -.9, 2.2, 1, C.leg); s.ellipse(3.4, -.9, 2.2, 1, C.leg);
  // body, white belly, bead necklace (she loves what shines)
  s.ellipse(0, -16, 8, 10, C.body);
  s.ellipse(2.4, -14.5, 5, 7.4, C.belly);
  for (let i = 0; i < 6; i++) { const a = Math.PI * (.15 + i * .14); s.ellipse(1 + Math.cos(a) * 5.4, -22.4 + Math.sin(a) * 2.2, .9, .9, C.bead) }
  // wing: folded, or raised to call buyers, a shiny trinket held up
  if (call) {
    s.poly([{x: -1.6, y: -21}, {x: -5, y: -30}, {x: -8.4, y: -35}, {x: -10.6, y: -34.4}, {x: -12.6, y: -31.4}, {x: -12.8, y: -27.6},
      {x: -11.2, y: -24.4}, {x: -7.6, y: -19.4}], C.wing);                                                    // raised wing, feather tips
    s.poly([{x: -4.4, y: -24.4}, {x: -7.4, y: -31}, {x: -9.8, y: -29.6}, {x: -7.4, y: -23}], C.patch);
    for (const [a, b] of [[-10.6, -34.4], [-12.6, -31.4], [-12.8, -27.6]]) s.line(a + 1.8, b + 1.6, a, b, C.wingLight, 1);
    s.ellipse(-9.5, -35.5, 2.3, 2.3, C.bead); s.ellipse(-10.1, -36.2, .8, .8, '#fff3c9');
  } else {
    s.ellipse(-3, -16.5, 5, 8.6, C.wing); s.ellipse(-3.4, -19, 2.6, 3.8, C.patch); s.ellipse(-4, -11, 3, 2.6, C.wingLight);
  }
  // head in a coral headscarf with white dots, knot under the beak
  s.ellipse(1.2, -29, 6.2, 6, C.body);
  s.poly([{x: -4.6, y: -31}, {x: -7.6, y: -23.4}, {x: -2.4, y: -25.4}], C.scarfDark);
  s.ellipse(.6, -31.8, 6.8, 4.4, C.scarf);
  for (const [dx, dy] of [[-3, -32.6], [0, -34], [3.2, -33], [-1.6, -30.2], [2, -30.6]]) s.ellipse(dx, dy, .75, .75, C.dot);
  s.ellipse(4.6, -24.8, 1.8, 1.4, C.scarfDark); s.ellipse(6.2, -24, 1.4, 1.1, C.scarf);
  s.ellipse(3.6, -28.6, 1.8, 1.8, '#f6f3ea'); s.ellipse(4, -28.6, .95, 1.05, C.eye);
  if (call) {   // beak open: «Тр-р-р, налетай!»
    s.poly([{x: 6.6, y: -29.4}, {x: 11, y: -29.6}, {x: 6.8, y: -27.8}], C.beak);
    s.poly([{x: 6.6, y: -27.2}, {x: 10, y: -25.6}, {x: 6.4, y: -26.2}], C.beak);
    for (const [a, b, l] of [[12.6, -31, 3], [13.4, -28, 3.4], [12.6, -25, 3]]) s.line(a, b, a + l, b - (b + 28) * .35, '#c9b48e', 1);
  } else s.poly([{x: 6.6, y: -29.2}, {x: 10.6, y: -28}, {x: 6.6, y: -26.8}], C.beak);
}

export function magpieSvg() {
  const parts = ['stand', 'call'].map(pose => { const c = new SvgCtx(`vm${pose}`); magpie(scene(c), pose); return `<g class="vm-${pose}">${c.svg()}</g>` });
  return `<svg class="vm-figure-art" viewBox="-20 -50 40 54" aria-hidden="true" focusable="false">${parts.join('')}</svg>`;
}
