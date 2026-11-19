/* Лесоруб Степан, карточка «Делянка» и сцена мини-игры «Валка» (docs/tasks/FARM_LUMBERJACK.md §7).
   Farm-style painters: the same flat ellipse / line / poly primitives, palette and light (from the top left) as
   scene.js treeSprite, scene_expansion.js helpers and the player's figure (scripts/art/village/player.js).
   Used by app.js (the plot card), trip_game.js (the felling stage) and scene_expansion.js (Stepan among the helpers).
   Rendering has no authority over rewards: the client passes the state it already simulates from the server plan.

   Two kinds of painters:
   - figure / bust / spruce / stump / logs / card — only ellipse, line, poly, quadratic curves, save/restore,
     translate/scale/rotate and linear gradients, so the generator records them into SVG (icons.svg, the card);
   - drawFellScene — canvas only (clip, arcs, alpha), the live mini-game stage. */

const TAU = Math.PI * 2;
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const lerp = (a, b, k) => a + (b - a) * k;
const rnd = i => { const n = Math.sin(i * 127.1 + 311.7) * 43758.5453; return n - Math.floor(n); };

/* ---------------------------------------------------------------- palette */
export const LJ_PAL = {
  skin: '#f0c9a4', skinShade: '#e3b28c', cheek: '#e9a68e', eye: '#3d4a3f', nose: '#e6b08e',
  beard: '#9a6440', beardLight: '#b37c55', beardDark: '#7a4f33',
  cap: '#d9a648', capBand: '#c48f36', capRib: '#a9792b', capLight: '#e9c06a',
  shirt: '#c75b4e', shirtDark: '#4f3a3b', shirtLight: '#d97a68',
  jeans: '#5f7d9c', jeansDark: '#4f6a86', strap: '#6b4a33', clip: '#e2cf91',
  glove: '#c99a62', boot: '#9a6a3e', bootTop: '#86592f', sole: '#5a4030',
  saw: '#e0873a', sawShade: '#c46f2a', sawDark: '#4d5450', sawGrip: '#3f4542', bar: '#b4bcb8', barEdge: '#7f8a88',
  chain: '#5c6461', sheath: '#4f6b78', sheathLight: '#6f8f9a',
  wood: '#e8c78f', woodRing: '#cfa76d', woodCore: '#d9b277', bark: '#8a6c4c', barkDark: '#6f553b', barkLight: '#a3825d',
  chip: '#f0dcae', chipDark: '#d9b97f',
  needle: '#456d54', needleMid: '#557d5f', needleLight: '#6c9670', trunk: '#8a6c4c',
  shadow: '#41623530'
};
// The player in two looks — the palettes and heads of scripts/art/village/player_looks.js, so «Пилю сам» shows the same
// person as the village: the farmer with a moustache ('farmer') or the farmer woman ('farmer_f', address form «она»).
export const FARMER_PAL = {
  skin: '#f3d3b0', skinShade: '#e6c29e', ear: '#e6b896', cheek: '#efb4a0', nose: '#ecb48f', eye: '#3d4a3f', hair: '#8a5a3a',
  tache: '#6b3f26', shirt: '#efdcb4', overall: '#7fa3c4', bib: '#8fb2cf', strap: '#6d90b0', boot: '#6f5a46', hat: '#ecd283',
  brim: '#e3c56f', brimShade: '#cfae58', band: '#c98a5a', glove: '#c99a62'
};
// the farmer woman works in rose dungarees over her blouse (the colour of her village sarafan)
export const FARMER_F_PAL = {
  skin: '#f5d6b6', nose: '#efc09e', cheek: '#f0a99a', eye: '#3d4a3f', lips: '#c0605a', hair: '#9a5a36', hairShade: '#7e4529',
  shirt: '#f6ead0', overall: '#cf6f6a', bib: '#dc827c', strap: '#b85b57', boot: '#7a5a44', hat: '#ecd283', brim: '#e3c56f',
  brimShade: '#cfae58', ribbon: '#cf6f6a', petal: '#ffffff', heart: '#f2c94c', glove: '#c99a62'
};

/* ---------------------------------------------------------------- primitives (same as FarmScene.poly/ellipse/line) */
export function painter(g) {
  return {
    c: g,
    ellipse(x, y, rx, ry, col) { g.beginPath(); g.ellipse(x, y, rx, ry, 0, 0, TAU); g.fillStyle = col; g.fill(); },
    line(x1, y1, x2, y2, col, w = 1) { g.beginPath(); g.moveTo(x1, y1); g.lineTo(x2, y2); g.strokeStyle = col; g.lineWidth = w; g.lineCap = 'round'; g.stroke(); },
    poly(pts, fill, stroke = null, w = 1) {
      g.beginPath(); pts.forEach((p, i) => i ? g.lineTo(p.x, p.y) : g.moveTo(p.x, p.y)); g.closePath();
      if (fill) { g.fillStyle = fill; g.fill(); } if (stroke) { g.strokeStyle = stroke; g.lineWidth = w; g.lineJoin = 'round'; g.stroke(); }
    },
    // flat point list [x0,y0,x1,y1,...]
    pf(a, fill, stroke = null, w = 1) { const pts = []; for (let i = 0; i < a.length; i += 2) pts.push({x: a[i], y: a[i + 1]}); this.poly(pts, fill, stroke, w); },
  };
}
const asPainter = g => (g && g.ellipse && g.c) ? g : painter(g);

// Lines of a plaid inside an ellipse: vertical and horizontal chords, so the check pattern never leaves the shirt.
function plaidEllipse(p, cx, cy, rx, ry, xs, ys, col, w) {
  for (const k of xs) { if (Math.abs(k) >= rx * .96) continue; const hh = ry * Math.sqrt(1 - (k / rx) ** 2) * .9; p.line(cx + k, cy - hh, cx + k, cy + hh, col, w); }
  for (const k of ys) { if (Math.abs(k) >= ry * .96) continue; const hw = rx * Math.sqrt(1 - (k / ry) ** 2) * .9; p.line(cx - hw, cy + k, cx + hw, cy + k, col, w); }
}
// A sleeve: two segments, with dark check bands across them and a cuff.
function sleeve(p, pts, w, L, cuff = true) {
  for (let i = 0; i + 1 < pts.length; i++) p.line(pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1], L.shirt, w);
  for (let i = 0; i + 1 < pts.length; i++) {
    const [ax, ay] = pts[i], [bx, by] = pts[i + 1], dx = bx - ax, dy = by - ay, n = Math.hypot(dx, dy) || 1, nx = -dy / n * w * .42, ny = dx / n * w * .42;
    for (const k of [.38, .78]) { const x = ax + dx * k, y = ay + dy * k; p.line(x - nx, y - ny, x + nx, y + ny, L.shirtDark, w * .3); }
  }
  if (cuff) { const [ax, ay] = pts[pts.length - 2], [bx, by] = pts[pts.length - 1], k = .86; p.ellipse(ax + (bx - ax) * k, ay + (by - ay) * k, w * .5, w * .5, L.shirtDark); }
}

/* ---------------------------------------------------------------- chainsaw (local: body centre at 0,0, bar towards +x) */
// opt: {len: bar length, sheath: bar cover on (carrying), run: chain moving (time in ms), grey: stalled, noBar: body only}
export function chainsaw(g, opt = {}) {
  const p = asPainter(g), P = LJ_PAL, len = opt.len ?? 17, grey = !!opt.grey;
  const body = grey ? '#b9a48e' : P.saw, shade = grey ? '#a08f7c' : P.sawShade;
  if (!opt.noBar) sawBar(p, opt);
  // body: engine housing, dark top cover, rear handle loop and the top handle
  p.pf([-6.4, -3.6, 4.6, -4.4, 6.6, -1.6, 6.4, 3.6, -5.6, 4, -7, 1.2], body);
  p.pf([-5.6, 1.4, 6.4, 1, 6.4, 3.6, -5.6, 4], shade);
  p.pf([-4.2, -3.8, 3.8, -4.4, 3.2, -6.4, -3, -6], P.sawDark);
  p.line(-6.4, -1, -10.4, -.6, P.sawGrip, 2); p.line(-10.4, -.6, -10, 3.2, P.sawGrip, 2); p.line(-10, 3.2, -6, 3.4, P.sawGrip, 2);   // rear handle
  p.line(-3.6, -6.2, -2.4, -9.6, P.sawGrip, 1.8); p.line(-2.4, -9.6, 3.8, -9.4, P.sawGrip, 1.8); p.line(3.8, -9.4, 5.2, -4.8, P.sawGrip, 1.8);   // top handle
  p.ellipse(-1.6, -.2, 1.6, 1.4, grey ? '#9a8c7c' : '#f2c27a');   // starter cap
  p.line(5.6, -5.6, 7.4, -8.6, P.sawGrip, 1.4);                    // chain brake lever
  void len;
}
function sawBar(p, opt = {}) {
  const P = LJ_PAL, len = opt.len ?? 17, x0 = 5.8, x1 = x0 + len;
  if (opt.sheath) {
    p.line(x0, .4, x1, .4, P.sheath, 4.6); p.line(x0 + 1, -.8, x1 - 1, -.8, P.sheathLight, 1);
    for (let x = x0 + 3; x < x1 - 1; x += 3.4) p.ellipse(x, 1.6, .5, .5, '#e9e2c8');
    return;
  }
  p.line(x0, .4, x1, .4, P.barEdge, 4); p.line(x0, .1, x1 - .4, .1, P.bar, 2.6);
  p.ellipse(x1, .4, 2.1, 2.1, P.barEdge); p.ellipse(x1 - .2, .2, 1.2, 1.2, P.bar);
  // chain teeth along the top and bottom edges; a running chain shifts them
  const sh = opt.run ? ((opt.run / 40) % 2.4) : 0;
  for (let x = x0 + .8 + sh; x < x1 - .6; x += 2.4) { p.line(x, -1.7, x + .9, -1.7, P.chain, .9); p.line(x + 1.2, 2.5, x + 2.1, 2.5, P.chain, .9); }
}

/* ---------------------------------------------------------------- people */
// Joints of a pose, facing right, feet at 0,0, units = farm px (the player's scale, Stepan is a bigger man).
const POSES = {
  stand: {feet: [[-3.4, 0], [3.6, 0]], knees: [[-2.8, -8.4], [3, -8.4]], hips: [[-2.4, -16], [2.4, -16]], torso: [0, -23.6], lean: 0, head: [1.2, -37]},
  point: {feet: [[-3.8, 0], [4.2, 0]], knees: [[-3, -8.4], [3.6, -8.4]], hips: [[-2.4, -16], [2.4, -16]], torso: [0, -23.6], lean: 0, head: [1.4, -37]},
  carry: {feet: [[-3.6, 0], [3.8, 0]], knees: [[-3, -8.4], [3.4, -8.4]], hips: [[-2.4, -16], [2.4, -16]], torso: [0, -23.6], lean: 0, head: [1.2, -37]},
  saw: {feet: [[-7, 0], [8, 0]], knees: [[-5.4, -8], [8.6, -9]], hips: [[-1.6, -14.6], [2.4, -14.6]], torso: [2, -22.4], lean: .18, head: [6.4, -34.6]},
};
export const FIGURE_BOX = {x: -24, y: -56, w: 64, h: 60};          // covers every pose with the saw (stand: bar behind the head)
export const SAW_POSE = {tip: {x: 35.6, y: -12.6}, body: {x: 13, y: -13}};   // where the bar of the «saw» pose is (figure units)

function legs(p, J, L, farmer, slim = false) {
  const col = farmer ? L.overall : L.jeans, w = slim ? .82 : 1;
  for (let i = 0; i < 2; i++) {
    const [hx, hy] = J.hips[i], [kx, ky] = J.knees[i], [fx, fy] = J.feet[i];
    p.line(hx, hy, kx, ky, col, 4.8 * w); p.line(kx, ky, fx, fy - 2.2, col, 4.6 * w);
    if (farmer) { p.ellipse(fx + .6, fy - 1.1, 3.2, 1.9, L.boot); continue; }
    p.ellipse(fx + .3, fy - 3, 2.7, 1.6, LJ_PAL.bootTop);
    p.ellipse(fx + 1, fy - 1.3, 3.6, 2, LJ_PAL.boot); p.line(fx - 2.2, fy - .1, fx + 4.2, fy - .1, LJ_PAL.sole, 1.3);
    p.line(fx - .4, fy - 3.4, fx + 1.4, fy - 2.6, '#e9d9b0', .6);
  }
}
function stepanTorso(p, J) {
  const L = LJ_PAL, [tx, ty] = J.torso;
  p.ellipse(tx, ty, 8.6, 8.8, L.shirt);
  plaidEllipse(p, tx, ty, 8.6, 8.8, [-5.2, -1.6, 2, 5.6], [-5.2, -1, 3.2], L.shirtDark, 1.5);
  plaidEllipse(p, tx, ty, 8.6, 8.8, [-3.4, 3.8], [], L.shirtLight, .6);
  p.ellipse(tx, ty + 8.2, 7.4, 4.4, L.jeans);                       // shirt tucked into jeans
  p.line(tx - 6.6, ty + 5.2, tx + 6.6, ty + 5.2, L.sole, 1.3);       // belt
  // suspenders with brass clips
  p.line(tx - 3.6, ty - 7.6, tx - 3.4, ty + 5.4, L.strap, 1.7); p.line(tx + 3.8, ty - 7.6, tx + 4.2, ty + 5.4, L.strap, 1.7);
  p.ellipse(tx - 3.4, ty + 5.2, .9, .9, L.clip); p.ellipse(tx + 4.2, ty + 5.2, .9, .9, L.clip);
}
function stepanHead(p, J) {
  const L = LJ_PAL, [x, y] = J.head;
  p.ellipse(x - .4, y + 6.4, 3.4, 2.6, L.skinShade);                // neck
  p.ellipse(x - 4.6, y - .6, 2.8, 3.4, L.beard);                    // hair at the nape
  p.ellipse(x, y, 6.4, 7, L.skin);
  p.ellipse(x - 3.8, y + .6, 1.5, 2.1, L.skinShade);                // ear
  p.ellipse(x + 1.6, y + 4.8, 5.4, 3.8, L.beard);                   // beard on the jaw, the face stays open
  p.ellipse(x + 3, y + 6.6, 3.6, 3.2, L.beard);
  p.ellipse(x - .6, y + 3.6, 2.2, 2.2, L.beard);                    // sideburn
  p.ellipse(x + 1.2, y + 4.8, 2.4, 1.4, L.beardLight);
  p.ellipse(x + 4.4, y + 2.6, 2.6, 1.1, L.beardDark);               // moustache
  p.ellipse(x + 5.6, y + .9, 1.6, 1.4, L.nose);
  p.ellipse(x + 3, y + 1.4, 1.5, 1, L.cheek);
  p.ellipse(x + 3.6, y - 1, .9, 1.15, L.eye);                       // kind eye and a raised brow
  p.line(x + 2.4, y - 3, x + 5, y - 2.8, L.beardDark, 1);
  // knitted watch cap: crown, rolled band with ribs
  p.ellipse(x - .4, y - 6.6, 6.9, 4.6, L.cap);
  p.ellipse(x - 2.4, y - 8.4, 2.6, 1.3, L.capLight);
  p.pf([x - 7.2, y - 6.6, x + 6.6, y - 6.8, x + 6.6, y - 3.8, x - 6.8, y - 3.6], L.capBand);
  for (const dx of [-5, -2.4, .2, 2.8, 5.2]) p.line(x + dx, y - 6.2, x + dx, y - 4.2, L.capRib, .7);
}
function farmerTorso(p, J) {
  const L = FARMER_PAL, [tx, ty] = J.torso;
  // grown-up overalls of the village figure: broad shoulders, a straight bib, no belly
  p.ellipse(tx, ty - 2.2, 6.6, 5.4, L.shirt);
  p.pf([tx - 5.6, ty - 1.4, tx + 5.6, ty - 1.4, tx + 6, ty + 7, tx + 4, ty + 9.4, tx - 4, ty + 9.4, tx - 6, ty + 7], L.overall);
  p.pf([tx - 4.2, ty - 4.4, tx + 4.2, ty - 4.4, tx + 4.6, ty + 3.6, tx - 4.6, ty + 3.6], L.bib);
  p.line(tx - 3.4, ty - 4.2, tx - 4.6, ty - 7, L.strap, 1.4); p.line(tx + 3.4, ty - 4.2, tx + 4.6, ty - 7, L.strap, 1.4);
  p.ellipse(tx - 2.6, ty - 3.2, .8, .8, '#e8d9a8'); p.ellipse(tx + 2.6, ty - 3.2, .8, .8, '#e8d9a8');
  p.line(tx - 5.8, ty + 4, tx + 5.8, ty + 4, L.strap, .9);
}
function farmerHead(p, J) {
  // the village head of player_looks.js (centre .6 there): neck, hair, sideburn, ear, nose, eye, brow, the moustache, the hat
  const L = FARMER_PAL, x = J.head[0] - .6, y = J.head[1];
  p.ellipse(x + .4, y + 5.6, 2, 1.8, L.skinShade);
  p.ellipse(x + .6, y, 5.2, 5.6, L.skin);
  p.ellipse(x - 3, y - 1, 2.6, 3.4, L.hair); p.ellipse(x - 1.6, y + 2.2, 1.2, 1.8, L.hair);
  p.ellipse(x - .4, y + .4, 1.1, 1.5, L.ear);
  p.pf([x + 5.2, y - 1.4, x + 7.4, y + 1.4, x + 5.6, y + 2], L.nose);
  p.ellipse(x + 3.4, y - 1.2, .8, 1.05, L.eye); p.ellipse(x + 3.6, y - 1.5, .25, .25, '#fff');
  p.line(x + 2.2, y - 3.2, x + 4.6, y - 3.3, L.hair, .9);
  p.ellipse(x + 2.4, y + 1.2, 1.1, .7, L.cheek);
  p.ellipse(x + 5.2, y + 2.6, 2.3, 1.05, L.tache); p.ellipse(x + 3.2, y + 2.8, 1.9, 1, L.tache);
  p.ellipse(x + 6.9, y + 3.2, .9, .8, L.tache); p.ellipse(x + 1.6, y + 3.3, .9, .75, L.tache);
  p.ellipse(x + .6, y - 4, 9.8, 2.5, L.brimShade); p.ellipse(x + .6, y - 4.6, 9.8, 2.9, L.brim);
  p.ellipse(x + .6, y - 5.4, 5, 1.4, L.band); p.ellipse(x + .6, y - 7.8, 5.2, 3.8, L.hat); p.ellipse(x - 1.2, y - 8.6, 2, 1.1, '#f4e2a4');
}
function farmerWomanTorso(p, J) {
  const L = FARMER_F_PAL, [tx, ty] = J.torso;
  p.ellipse(tx, ty - 1.6, 5.6, 5.4, L.shirt);                                       // blouse: narrower shoulders
  p.pf([tx - 4.4, ty + 1.6, tx + 4.4, ty + 1.6, tx + 5.6, ty + 8.6, tx - 5.6, ty + 8.6], L.overall);
  p.pf([tx - 3.4, ty - 4, tx + 3.4, ty - 4, tx + 3.8, ty + 2.4, tx - 3.8, ty + 2.4], L.bib);
  p.line(tx - 3.8, ty + 2, tx + 3.8, ty + 2, L.strap, 1.1);                          // waist
  p.line(tx - 2.8, ty - 3.8, tx - 3.6, ty - 6.8, L.strap, 1.2); p.line(tx + 2.8, ty - 3.8, tx + 3.6, ty - 6.8, L.strap, 1.2);
  p.ellipse(tx + 4.2, ty - 4.2, 2, 1.8, L.shirt);                                    // puffed sleeve
}
function farmerWomanHead(p, J) {
  // the village head of player_looks.js (centre .8 there): braid, neck, hair, fringe, nose, lashes, lips, hat with a daisy
  const L = FARMER_F_PAL, x = J.head[0] - .8, y = J.head[1];
  for (let k = 0; k < 6; k++) p.ellipse(x - 4 - k * .3, y + 2.6 + k * 2.1, 1.4, 1.25, k % 2 ? L.hairShade : L.hair);
  p.ellipse(x - 5.9, y + 15.2, 1.5, .9, L.ribbon);
  p.ellipse(x + .4, y + 5.6, 1.4, 1.6, L.skin);
  p.ellipse(x + .8, y, 4.9, 5.3, L.skin);
  p.ellipse(x - 2.6, y - .6, 3.4, 4.1, L.hair);
  p.pf([x - 1.2, y - 5.1, x + 4.2, y - 4.9, x + 5.4, y - 3, x + 2.6, y - 3.6, x + .6, y - 2.8], L.hair);
  p.pf([x + 5.4, y - .4, x + 6.5, y + 1.3, x + 5.4, y + 1.6], L.nose);
  p.ellipse(x + 2.8, y + 1.6, 1.2, .75, L.cheek);
  p.ellipse(x + 3.5, y - .8, .78, 1.02, L.eye); p.ellipse(x + 3.7, y - 1.1, .24, .24, '#fff');
  p.line(x + 4, y - 1.7, x + 5, y - 2.4, L.eye, .5); p.line(x + 3.4, y - 1.9, x + 3.9, y - 2.8, L.eye, .5);
  p.ellipse(x + 4.6, y + 3, .85, .48, L.lips);
  p.ellipse(x + .8, y - 4.4, 9.2, 2.3, L.brimShade); p.ellipse(x + .8, y - 5, 9.2, 2.7, L.brim);
  p.ellipse(x + .8, y - 5.8, 4.8, 1.3, L.ribbon); p.ellipse(x + .8, y - 8.1, 5, 3.6, L.hat); p.ellipse(x - 1, y - 8.9, 1.9, 1.05, '#f4e2a4');
  p.line(x - 3.8, y - 5.4, x - 6.4, y - 2.4, L.ribbon, 1); p.line(x - 3.4, y - 5.4, x - 5.2, y - 1.6, L.ribbon, 1);
  for (let k = 0; k < 6; k++) { const a = k * Math.PI / 3; p.ellipse(x + 4.1 + Math.cos(a) * 1.15, y - 6.4 + Math.sin(a) * 1.15, .78, .78, L.petal); }
  p.ellipse(x + 4.1, y - 6.4, .72, .72, L.heart);
}
function hand(p, x, y, col) { p.ellipse(x, y, 2.2, 2.1, col); }

/**
 * A full figure: Stepan (look 'stepan'), the farmer ('farmer') or the farmer woman ('farmer_f'), feet at (x, y), facing
 * right (dir 1) or left (-1).
 * pose: 'stand' — saw on the shoulder, bar in its cover; 'point' — shows the way with the near arm (opt.pointAngle,
 * radians in the figure's own space, 0 = forward, negative = up); 'carry' — saw held low at the side;
 * 'saw' — sawing, both hands on the saw, bar forward (SAW_POSE.tip). opt: {scale, t (ms), run, grey, bar: false
 * to leave the bar out (the scene draws it clipped at the trunk), shadow: false}.
 */
export function drawFigure(g, x, y, look = 'stepan', pose = 'stand', opt = {}) {
  const p = asPainter(g), c = p.c, J = POSES[pose] || POSES.stand, woman = look === 'farmer_f', farmer = look === 'farmer' || woman;
  const L = woman ? FARMER_F_PAL : farmer ? FARMER_PAL : LJ_PAL, sc = opt.scale ?? 1, dir = opt.dir ?? 1, glove = L.glove;
  c.save(); c.translate(x, y); c.scale(sc * dir, sc);
  if (opt.shadow !== false) p.ellipse(1.5, .6, 11.5, 3.2, LJ_PAL.shadow);
  const torso = () => woman ? farmerWomanTorso(p, J) : farmer ? farmerTorso(p, J) : stepanTorso(p, J);
  const head = () => woman ? farmerWomanHead(p, J) : farmer ? farmerHead(p, J) : stepanHead(p, J);
  const arm = pts => farmer ? (pts.forEach((q, i) => i && p.line(pts[i - 1][0], pts[i - 1][1], q[0], q[1], L.shirt, 3.6))) : sleeve(p, pts, 4.2, LJ_PAL);
  const [tx, ty] = J.torso, sB = [tx - 5.6, ty - 5.4], sF = [tx + 5.2, ty - 5.6];
  if (pose === 'stand') {
    // the saw on the near shoulder: engine in front held by the hand, bar in its cover going back and down behind the body
    const carry = () => { c.translate(tx + 14.6, ty - 6.6); c.scale(-.84, .84); c.rotate(.36); };
    legs(p, J, L, farmer, woman);
    c.save(); carry(); sawBar(p, {len: 27, sheath: true}); c.restore();
    arm([sB, [sB[0] - 2.4, sB[1] + 7], [sB[0] - 1.6, sB[1] + 13.4]]); hand(p, sB[0] - 1.6, sB[1] + 13.6, glove);
    torso(); head();
    c.save(); carry(); chainsaw(p, {noBar: true}); c.restore();
    arm([sF, [sF[0] + 4.4, sF[1] + 4.6], [sF[0] + 8.2, sF[1] + .6]]); hand(p, sF[0] + 8.2, sF[1] + .4, glove);
  } else if (pose === 'point') {
    legs(p, J, L, farmer, woman);
    arm([sB, [sB[0] - 1.8, sB[1] + 7], [sB[0] - .8, sB[1] + 13.2]]); hand(p, sB[0] - .8, sB[1] + 13.4, glove);
    torso(); head();
    const a = opt.pointAngle ?? -.7, e = [sF[0] + Math.cos(a) * 6.4, sF[1] + Math.sin(a) * 6.4], h = [sF[0] + Math.cos(a) * 12.6, sF[1] + Math.sin(a) * 12.6];
    arm([sF, e, h]); hand(p, h[0], h[1], glove);
    p.line(h[0], h[1], h[0] + Math.cos(a) * 3.4, h[1] + Math.sin(a) * 3.4, glove, 1.6);          // the pointing finger
  } else if (pose === 'carry') {
    legs(p, J, L, farmer, woman);
    arm([sB, [sB[0] - 2, sB[1] + 7], [sB[0] - 1.2, sB[1] + 13.4]]); hand(p, sB[0] - 1.2, sB[1] + 13.6, glove);
    torso(); head();
    c.save(); c.translate(sF[0] + 3.4, sF[1] + 18.6); c.rotate(.18); chainsaw(p, {len: 15, grey: opt.grey}); c.restore();
    arm([sF, [sF[0] + 1.6, sF[1] + 6.4], [sF[0] + 2.6, sF[1] + 10.2]]); hand(p, sF[0] + 2.6, sF[1] + 10.4, glove);
  } else {   // saw
    legs(p, J, L, farmer, woman);
    torso(); head();
    const shake = opt.run && !opt.grey ? Math.sin(opt.run / 16) * .45 : 0;
    c.save(); c.translate(SAW_POSE.body.x, SAW_POSE.body.y + shake);
    if (opt.bar !== false) sawBar(p, {len: 20, run: opt.grey ? 0 : opt.run});
    chainsaw(p, {noBar: true, grey: opt.grey}); c.restore();
    arm([sB, [sB[0] + 4.4, sB[1] + 6.6], [SAW_POSE.body.x - 9.6, SAW_POSE.body.y + 1.6 + shake]]); hand(p, SAW_POSE.body.x - 9.6, SAW_POSE.body.y + 1.6 + shake, glove);
    arm([sF, [sF[0] + 5.6, sF[1] + 2.4], [SAW_POSE.body.x + .4, SAW_POSE.body.y - 9.6 + shake]]); hand(p, SAW_POSE.body.x + .4, SAW_POSE.body.y - 9.4 + shake, glove);
  }
  c.restore();
}

/* ---------------------------------------------------------------- busts: guide icon and hire portrait */
// Shoulders cut by a circle (the avatar frame) or left open (the 48×48 helper icon, clipped by its viewBox).
function shoulderRegion(cx, cy, rx, ry, circle) {
  const top = [], bot = [];
  for (let i = 0; i <= 40; i++) {
    const x = cx - rx + 2 * rx * i / 40, e = 1 - ((x - cx) / rx) ** 2; if (e <= 0) continue;
    let y0 = cy - ry * Math.sqrt(e), y1 = cy + ry * Math.sqrt(e);
    if (circle) { const d = circle.r * circle.r - (x - circle.x) ** 2; if (d <= 0) continue; y1 = Math.min(y1, circle.y + Math.sqrt(d) - .2); }
    if (y1 > y0) { top.push([x, y0]); bot.push([x, y1]); }
  }
  return {top, bot, pts: [...top, ...[...bot].reverse()].map(([x, y]) => ({x, y}))};
}
/**
 * Stepan from the chest up. box: 'icon' (48×48, the guide icon helper_lumberjack) or 'avatar' (40×40 in a circle,
 * the hire-card portrait avatar_lumberjack). Units are those of the box.
 */
export function drawBust(g, box = 'icon') {
  const p = asPainter(g), c = p.c, L = LJ_PAL, av = box === 'avatar';
  const k = av ? .8 : 1, X = v => (av ? 19.4 : 24) + (v - 24) * k, Y = v => (av ? 21.4 : 24) + (v - 24) * k;   // icon layout, scaled into the avatar
  const circle = av ? {x: 20, y: 20, r: 18.4} : null;
  if (av) p.ellipse(20, 20, 19, 19, '#e7ead9');
  const saw = () => { c.translate(X(av ? 36.4 : 39.4), Y(av ? 37.6 : 36.4)); c.scale(k * (av ? .7 : .92), k * (av ? .7 : .92)); c.rotate(-1.3); c.scale(1, -1); };
  // chainsaw upright on the near shoulder: bar in its cover rises on the right, the handles face away from the head
  c.save(); saw(); sawBar(p, {len: av ? 12 : 16, sheath: true}); c.restore();
  // shoulders in a red-and-black check
  const sh = shoulderRegion(X(24), Y(47.4), 17.5 * k, 13.6 * k, circle);
  p.poly(sh.pts, L.shirt);
  const vAt = xx => { let i = 0; while (i < sh.top.length - 1 && sh.top[i][0] < xx) i++; return [sh.top[i], sh.bot[i]]; };
  const hAt = yy => { const xs = sh.top.filter(([, ty], i) => ty < yy - .4 && sh.bot[i][1] > yy + .4).map(([x]) => x); return xs.length ? [xs[0], xs[xs.length - 1]] : null; };
  for (const dx of [-12.6, -7, -1.6, 3.8, 9.2, 14.4]) { const [a, b] = vAt(X(24 + dx)); if (b[1] - a[1] > 1.2) p.line(a[0], a[1] + .9, a[0], b[1] - .9, L.shirtDark, 1.8 * k); }
  for (const yy of [39.2, 44.4]) { const r = hAt(Y(yy)); if (r) p.line(r[0] + .9, Y(yy), r[1] - .9, Y(yy), L.shirtDark, 1.5 * k); }
  for (const dx of [-9.6, 6.6]) { const [a, b] = vAt(X(24 + dx)); if (b[1] - a[1] > 1.2) p.line(a[0], a[1] + .9, a[0], b[1] - .9, L.shirtLight, .6 * k); }
  for (const dx of [-7.6, 7.6]) { const [a, b] = vAt(X(24 + dx)); p.line(a[0], Math.max(a[1], Y(35.4)) + .4, a[0], b[1] - .6, L.strap, 2.2 * k); }   // suspenders
  // head: a friendly face under the cap, the beard on the jaw
  const hx = X(24), hy = Y(22.2), s = k;
  p.ellipse(hx, hy + 9.4 * s, 4.6 * s, 3.4 * s, L.skinShade);
  p.ellipse(hx - 8.4 * s, hy + 1 * s, 1.9 * s, 2.7 * s, L.skinShade); p.ellipse(hx + 8.4 * s, hy + 1 * s, 1.9 * s, 2.7 * s, L.skinShade);   // ears
  p.ellipse(hx, hy, 8.6 * s, 9.4 * s, L.skin);
  p.ellipse(hx, hy + 7 * s, 8 * s, 5.4 * s, L.beard);
  p.ellipse(hx, hy + 9.8 * s, 5.6 * s, 4.2 * s, L.beard);
  p.ellipse(hx - 7 * s, hy + 3.6 * s, 2 * s, 3.4 * s, L.beard); p.ellipse(hx + 7 * s, hy + 3.6 * s, 2 * s, 3.4 * s, L.beard);   // sideburns
  p.ellipse(hx - 2.8 * s, hy + 6.8 * s, 2.6 * s, 1.6 * s, L.beardLight);
  p.ellipse(hx - 2.6 * s, hy + 4.2 * s, 3.2 * s, 1.4 * s, L.beardDark); p.ellipse(hx + 2.6 * s, hy + 4.2 * s, 3.2 * s, 1.4 * s, L.beardDark);   // moustache
  p.ellipse(hx, hy + 6.4 * s, 2.2 * s, 1 * s, '#c97a6a');           // smile
  p.ellipse(hx, hy + 2.2 * s, 2 * s, 1.7 * s, L.nose);
  p.ellipse(hx - 4.8 * s, hy + 2 * s, 1.8 * s, 1.1 * s, L.cheek); p.ellipse(hx + 4.8 * s, hy + 2 * s, 1.8 * s, 1.1 * s, L.cheek);
  p.ellipse(hx - 3.4 * s, hy - .6 * s, 1.1 * s, 1.35 * s, L.eye); p.ellipse(hx + 3.4 * s, hy - .6 * s, 1.1 * s, 1.35 * s, L.eye);
  p.ellipse(hx - 3.1 * s, hy - 1 * s, .35 * s, .35 * s, '#ffffff'); p.ellipse(hx + 3.7 * s, hy - 1 * s, .35 * s, .35 * s, '#ffffff');
  p.line(hx - 5 * s, hy - 3.2 * s, hx - 2 * s, hy - 3.6 * s, L.beardDark, 1.2 * s); p.line(hx + 2 * s, hy - 3.6 * s, hx + 5 * s, hy - 3.2 * s, L.beardDark, 1.2 * s);
  // watch cap
  p.ellipse(hx, hy - 9 * s, 8.8 * s, 6.2 * s, L.cap);
  p.ellipse(hx - 3.4 * s, hy - 12 * s, 3.2 * s, 1.6 * s, L.capLight);
  p.pf([hx - 9.6 * s, hy - 9.4 * s, hx + 9.6 * s, hy - 9.4 * s, hx + 9.4 * s, hy - 5.2 * s, hx - 9.4 * s, hy - 5.2 * s], L.capBand);
  for (let i = -3; i <= 3; i++) p.line(hx + i * 2.6 * s, hy - 8.8 * s, hx + i * 2.6 * s, hy - 5.8 * s, L.capRib, .8 * s);
  // the saw's engine on the shoulder, in front of the shirt
  c.save(); saw(); chainsaw(p, {noBar: true}); c.restore();
}

/* ---------------------------------------------------------------- forest: spruce, stump, logs */
export const SPRUCE = {
  day: {dark: '#456d54', mid: '#557d5f', light: '#6c9670', tip: '#7fa67b', trunk: '#8a6c4c'},
  far: {dark: '#7d9f82', mid: '#86a88a', light: '#93b394', tip: '#9dbb9b', trunk: '#9a8a6c'},
  night: {dark: '#2d4a3d', mid: '#365647', light: '#44665a', tip: '#4f7262', trunk: '#5f4f3e'},
};
/**
 * A spruce in the farm style: tiers of drooping triangles, the light side on the left (like treeSprite's highlights).
 * (x, y) = foot of the trunk, h = height. o: {col: SPRUCE.*, tiers, trunk: trunk width, flat: one colour, bare: stem
 * height without tiers (the falling tree keeps its lower trunk bare), lean}
 */
export function drawSpruce(g, x, y, h, o = {}) {
  const p = asPainter(g), C = o.col || SPRUCE.day, n = o.tiers || 5, tw = o.trunk ?? h * .055, bare = o.bare ?? .14;
  p.line(x, y, x, y - h * .5, C.trunk, tw);
  if (o.trunk && o.trunk > 6) { p.line(x - tw * .22, y - 2, x - tw * .22, y - h * bare, '#a3825d', tw * .28); }
  const span = 1 - bare - .02;
  for (let i = 0; i < n; i++) {
    const f = i / n, yb = y - h * (bare + span * f * .92), yt = yb - h * span * (1.55 / (n + 1.2)) - h * .02,
      wd = h * .29 * (1 - f * .74), droop = h * .024;
    const pts = [x, yt, x + wd * .5, lerp(yt, yb, .55), x + wd, yb + droop * .4, x + wd * .62, yb - droop * .6, x + wd * .3, yb + droop * .2,
      x, yb - droop * .5, x - wd * .3, yb + droop * .2, x - wd * .62, yb - droop * .6, x - wd, yb + droop * .4, x - wd * .5, lerp(yt, yb, .55)];
    p.pf(pts, o.flat || (i % 2 ? C.mid : C.dark));
    if (!o.flat) p.pf([x, yt, x - wd * .5, lerp(yt, yb, .55), x - wd, yb + droop * .4, x - wd * .62, yb - droop * .6, x - wd * .3, yb + droop * .2, x - wd * .06, yb - droop * .2], C.light);
  }
  const top = y - h;
  p.pf([x, top - h * .02, x + h * .03, top + h * .1, x - h * .03, top + h * .1], o.flat || C.tip);
}
/** A stump: (x, y) = middle of its foot, r = radius, hh = height. Bark side, roots, light cut with growth rings. */
export function drawStump(g, x, y, r, hh, night = false) {
  const p = asPainter(g), P = LJ_PAL, ry = r * .42;
  const bark = night ? '#5f4f3e' : P.bark, barkD = night ? '#4c3f32' : P.barkDark, top = night ? '#b8a07a' : P.wood, ring = night ? '#a08a66' : P.woodRing;
  p.ellipse(x + r * .3, y + ry * .4, r * 1.35, ry * 1.1, P.shadow);
  for (const d of [-1, 1]) p.pf([x + d * r * .7, y - hh * .3, x + d * r * 1.35, y + ry * .5, x + d * r * .5, y + ry * .7], barkD);
  p.pf([x - r, y - hh, x + r, y - hh, x + r, y, x - r, y], bark);
  p.ellipse(x, y, r, ry, bark);
  p.pf([x - r * .7, y - hh, x - r * .35, y - hh, x - r * .35, y + ry * .6, x - r * .7, y + ry * .5], night ? '#6c5a46' : P.barkLight);
  p.ellipse(x, y - hh, r, ry, barkD);
  p.ellipse(x, y - hh - .3, r * .86, ry * .84, top);
  p.ellipse(x, y - hh - .3, r * .6, ry * .58, ring); p.ellipse(x, y - hh - .3, r * .5, ry * .48, top);
  p.ellipse(x + r * .05, y - hh - .3, r * .2, ry * .2, ring);
}
/** A log lying across the view: (x0..x1, y = its axis), radius r; the cut end on the right. */
export function drawLogSide(g, x0, x1, y, r, night = false) {
  const p = asPainter(g), P = LJ_PAL;
  p.ellipse(x0, y, r * .5, r, night ? '#4c3f32' : P.barkDark);
  p.pf([x0, y - r, x1, y - r, x1, y + r, x0, y + r], night ? '#5f4f3e' : P.bark);
  p.line(x0 + 1, y - r * .45, x1 - 1, y - r * .45, night ? '#6c5a46' : P.barkLight, r * .35);
  for (let x = x0 + r; x < x1 - r * .6; x += r * 1.7) p.line(x, y + r * .25, x + r * .7, y + r * .3, night ? '#4c3f32' : P.barkDark, .8);
  p.ellipse(x1, y, r * .52, r, night ? '#b8a07a' : P.wood); p.ellipse(x1, y, r * .32, r * .62, night ? '#a08a66' : P.woodRing); p.ellipse(x1, y, r * .24, r * .48, night ? '#b8a07a' : P.wood);
}
/** A log seen end-on (stack front): centre (x, y), radius r; a bit of bark length goes back to the upper right. */
export function drawLogEnd(g, x, y, r, night = false) {
  const p = asPainter(g), P = LJ_PAL, d = r * .5;
  p.pf([x - r * .7, y - r * .7, x - r * .7 + d, y - r * .7 - d * .6, x + r + d, y - d * .6, x + r * .7, y + r * .7], night ? '#4c3f32' : P.barkDark);
  p.ellipse(x, y, r, r, night ? '#5f4f3e' : P.bark);
  p.ellipse(x, y, r * .84, r * .84, night ? '#b8a07a' : P.wood);
  p.ellipse(x, y, r * .56, r * .56, night ? '#a08a66' : P.woodRing); p.ellipse(x, y, r * .46, r * .46, night ? '#b8a07a' : P.wood);
  p.ellipse(x + r * .04, y + r * .02, r * .14, r * .14, night ? '#a08a66' : P.woodRing);
  p.line(x - r * .5, y - r * .58, x - r * .1, y - r * .76, '#fff3d855', r * .12);
}
/** A woodpile seen from the end: n logs in a pyramid, bottom row centred on (x, y). */
export function drawLogPile(g, x, y, r, n, night = false) {
  const rows = []; let left = n, w = 1; while (left > 0) { rows.unshift(Math.min(left, w)); left -= w; w++; }
  // rows: widest at the bottom
  rows.sort((a, b) => b - a);
  rows.forEach((cnt, i) => { for (let j = 0; j < cnt; j++) drawLogEnd(g, x + (j - (cnt - 1) / 2) * r * 2.02, y - i * r * 1.74, r, night); });
}

/* ---------------------------------------------------------------- the «Делянка» card, 160×68 */
/** The forest-screen card of the route: spruce wood, fresh stumps, a woodpile and Stepan's saw on a stump. */
export function drawPlotCard(g, {night = false} = {}) {
  const p = asPainter(g), c = p.c, S = night ? SPRUCE.night : SPRUCE.day, F = night ? {dark: '#334f45', mid: '#3a574b', light: '#42604f', tip: '#4a6a59', trunk: '#4f4436'} : SPRUCE.far;
  const sky = c.createLinearGradient(0, 0, 0, 68); sky.addColorStop(0, night ? '#2b3a55' : '#dcebd1'); sky.addColorStop(1, night ? '#4a5a6c' : '#f3eacb');
  p.pf([0, 0, 160, 0, 160, 68, 0, 68], sky);
  if (night) {
    p.ellipse(128, 13, 7.5, 7.5, '#ecd88d'); p.ellipse(131.4, 11, 6.4, 6.4, '#2f3f59');
    for (const [sx, sy] of [[18, 8], [44, 14], [70, 6], [96, 12], [148, 24], [110, 4]]) p.ellipse(sx, sy, .9, .9, '#f6e3a0');
  } else p.ellipse(126, 14, 9, 9, '#f7d579cc');
  p.pf([0, 40, 30, 22, 58, 36, 92, 18, 130, 34, 160, 24, 160, 68, 0, 68], night ? '#33493f' : '#94b58b');
  // far row of spruces, then the near edge of the wood
  for (const [x, hh] of [[6, 26], [17, 30], [27, 24], [38, 33], [50, 27], [118, 26], [130, 31], [142, 25], [153, 32]]) drawSpruce(p, x, 44, hh, {col: F, tiers: 4});
  p.pf([0, 52, 40, 44, 84, 46, 124, 43, 160, 48, 160, 68, 0, 68], night ? '#3d5a45' : '#a9c597');   // the clearing
  p.pf([46, 60, 66, 50, 104, 50, 128, 62, 96, 66, 60, 66], night ? '#4a6650' : '#bfd3a1');           // the cleared strip
  for (const [x, hh] of [[4, 50], [152, 46], [138, 34]]) drawSpruce(p, x, 62, hh, {col: S, tiers: 5});
  // sawdust and chips round the stumps
  for (let i = 0; i < 14; i++) { const x = 30 + rnd(i) * 70, y = 54 + rnd(i + 30) * 11; p.ellipse(x, y, 1.1 + rnd(i + 7) * .8, .6, night ? '#a99a78' : LJ_PAL.chip); }
  drawStump(p, 36, 60, 6, 4.4, night); drawStump(p, 64, 53, 4.4, 3.2, night); drawStump(p, 92, 61, 5.2, 3.8, night);
  // Stepan's saw resting on the near stump, bar in its cover
  c.save(); c.translate(37.4, 53.8); c.scale(.62, .62); c.rotate(-.1); sawBar(p, {len: 15, sheath: true}); chainsaw(p, {noBar: true}); c.restore();
  // the woodpile: logs end-on, with two stakes holding it
  p.line(102.6, 64, 102.6, 41, night ? '#5f4f3e' : LJ_PAL.barkDark, 1.8); p.line(133.6, 64, 133.6, 41, night ? '#5f4f3e' : LJ_PAL.barkDark, 1.8);
  drawLogPile(p, 118, 60.5, 4.2, 10, night);
  if (night) {   // a lantern on the stake, like the farm's lanterns at night
    for (const [r, a] of [[11, '#f6e3a01e'], [7, '#f6e3a033'], [4.4, '#f6e3a066']]) p.ellipse(134, 40, r, r * .9, a);
    p.line(133.6, 41, 133.6, 38, '#3b3a36', 1); p.pf([131.8, 38.4, 135.6, 38.4, 135.2, 43, 132.2, 43], '#f3d27a'); p.pf([131.4, 37.4, 136, 37.4, 135.6, 38.6, 131.8, 38.6], '#3b3a36');
  }
}

/* ---------------------------------------------------------------- the «Валка» scene (canvas) */
// Mirrors of the server rules the picture depends on (qw_farm/trip_games.py): dead zone, hinge, fall time.
export const FELL_RULES = {dead: 50, hinge_pct: 80, fall_ms: 1200};
export const FELL_ANIM = {
  fall_ms: 1000,        // from the hinge giving way to the crown touching the ground (ease-in, like gravity)
  bounce_ms: 200,       // the trunk rebounds a little and settles (fall + bounce = FALL_MS of the server)
  dust_ms: 900,         // needles and dust at the landing spot
  result_ms: 1600,      // the per-tree verdict stays before the next tree slides in
  max_angle: 1.22,      // mark range on the arc: ±70° around the vertical
};
const SKY = {day: ['#cfe4e4', '#ecf2dd'], night: ['#1d2c44', '#33475e']};
/** Arc parameter (radians from the vertical, negative = left) of a mark/gap position 0..1000 of the plan. */
export const fellTheta = pos => (clamp(pos, 0, 1000) - 500) / 500 * FELL_ANIM.max_angle;
/** Fall progress 0..1 of the animation clock (ms since the hinge gave way), with the settle bounce after 1. */
export function fallProgress(ms) {
  if (ms <= 0) return 0;
  if (ms < FELL_ANIM.fall_ms) { const k = ms / FELL_ANIM.fall_ms; return k * k * (1.4 - .4 * k); }
  const b = Math.min(1, (ms - FELL_ANIM.fall_ms) / FELL_ANIM.bounce_ms); return 1 - Math.sin(b * Math.PI) * .045 * (1 - b);
}
/** Stage geometry in CSS px (the client uses it to place DOM bubbles, if any). */
export function fellLayout(w, h) {
  const wide = w > h * 1.15, hy = Math.round(h * (wide ? .3 : .34)), base = {x: w / 2, y: Math.round(h * .86)};
  const L = Math.min(h * (wide ? .72 : .64), base.y - 40), tw = Math.max(14, L * .1);
  const arc = {cx: base.x, cy: base.y, rx: Math.min(w * .44, L * .98), ry: L + Math.min(26, h * .05)};
  const ground = {rx: L * .95, ry: (base.y - hy) * .62};          // the ground ellipse of a lying tree: full length sideways
  const fs = L * (wide ? .27 : .23) / 48;                         // people: bigger on a wide stage, where the tree is short
  return {w, h, wide, hy, base, L, tw, cutY: base.y - tw * .55, arc, ground, fs};
}
const arcPt = (G, th, f = 1) => ({x: G.arc.cx + G.arc.rx * Math.sin(th) * f, y: G.arc.cy - G.arc.ry * Math.cos(th) * f});
// Where a tree aimed at arc angle th lies: the ground angle is wider than the arc one, so a felled spruce always reads as
// lying (diagonal or sideways, its crown may leave the phone screen) and never as a shorter tree standing behind.
export const landAngle = th => clamp(th * 1.5, -1.45, 1.45);
const groundPt = (G, th, f = 1) => { const a = landAngle(th); return {x: G.base.x + G.ground.rx * Math.sin(a) * f, y: G.base.y - G.ground.ry * Math.cos(a) * f}; };
const inPoly = (pts, x, y) => { let ins = false; for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) { const a = pts[i], b = pts[j]; if ((a.y > y) !== (b.y > y) && x < (b.x - a.x) * (y - a.y) / (b.y - a.y) + a.x) ins = !ins; } return ins; };
function rr(g, x, y, w, h, r) { g.beginPath(); if (g.roundRect) g.roundRect(x, y, w, h, r); else g.rect(x, y, w, h); }
function pill(g, text, x, y, o) {
  const {night, contrast, tone} = o, size = o.size || 17;
  g.font = `750 ${size}px system-ui,"Segoe UI",sans-serif`; g.textAlign = 'center'; g.textBaseline = 'middle';
  const tw = g.measureText(text).width + 22, hh = size + 13;
  const bg = tone === 'bad' ? (night ? '#5a2f22' : '#fbe3d6') : tone === 'good' ? (night ? '#244a33' : '#e2f2cf') : (night ? '#1d2c44' : '#fffef6');
  g.fillStyle = contrast ? bg : bg + 'ee'; rr(g, x - tw / 2, y - hh / 2, tw, hh, hh / 2); g.fill();
  if (contrast) { g.lineWidth = 2; g.strokeStyle = night ? '#ffffff' : '#10231a'; g.stroke(); }
  g.fillStyle = tone === 'bad' ? (night ? '#ffd2bf' : '#8a2f14') : tone === 'good' ? (night ? '#d9f2c9' : '#1f5a32') : (night ? '#f2edc4' : '#26402d');
  g.fillText(text, x, y + 1);
}

/** A tree of the scene drawn in a frame where its cut point is (0,0) and «up» is −y (used upright and falling). */
function sceneTree(p, G, col, k) {
  const above = G.L - (G.base.y - G.cutY);
  drawSpruce(p, 0, 0, above, {col, tiers: 6, trunk: G.tw * .92, bare: .13});
  // the upper side of the notch stays on the trunk: a pale wedge face when lying
  if (k > 0) p.ellipse(0, 0, G.tw * .46, G.tw * .16, LJ_PAL.woodCore);
  const ry = -above * .1;                                           // forester's mark: this tree goes
  p.pf([-G.tw * .47, ry - G.tw * .2, G.tw * .47, ry - G.tw * .2, G.tw * .47, ry + G.tw * .2, -G.tw * .47, ry + G.tw * .2], '#e8893a');
  p.line(-G.tw * .3, ry - G.tw * .1, -G.tw * .3, ry + G.tw * .12, '#f2b06a', G.tw * .12);
}

/**
 * Paint the whole «Валка» stage. g — 2D context already scaled to CSS px; w, h — CSS px.
 * st: {
 *   t: ms clock (animation), calm: reduced motion, night, contrast,
 *   index: current tree 0..4, total: 5, felled: [{crooked}] for trees already down (log pile),
 *   gap: {center, width} 0..1000 (plan: gap_center, gap_width), phase: 'intro'|'aim'|'cut'|'fall'|'tree_result'|'over',
 *   (gap.width = the plan's half width, as in qw_farm/trip_games.py)
 *   aim: 0..1000 mark position (live in 'aim', the chosen one afterwards),
 *   cut: 0..1000, heat: 0..1000, holding, pinch (now), stalled, pinches: [0..1000 cut fractions of the plan],
 *   fallMs: ms since the hinge gave way ('fall', 'tree_result'), crooked: aimed outside the gap,
 *   verdict: {text, tone: 'good'|'bad'} ('tree_result')
 * }
 */
export function drawFellScene(g, w, h, st = {}) {
  const G = fellLayout(w, h), p = painter(g), night = !!st.night, hc = !!st.contrast, t = st.calm ? 0 : (st.t || 0);
  const phase = st.phase || 'aim', gap = st.gap || {center: 620, width: 180};
  const gL = fellTheta(gap.center - gap.width), gR = fellTheta(gap.center + gap.width), aimTh = fellTheta(st.aim ?? 500);
  const dL = fellTheta(gap.center - FELL_RULES.dead), dR = fellTheta(gap.center + FELL_RULES.dead);
  const fellTh = phase === 'aim' || phase === 'intro' ? aimTh : fellTheta(st.aim ?? gap.center);
  const side = fellTh >= 0 ? 1 : -1;                                  // the notch and the fall side
  const k = phase === 'fall' || phase === 'tree_result' || phase === 'over' ? fallProgress(st.fallMs ?? 0) : 0;
  const S = SPRUCE.day;
  // ---- sky, far forest, clearing
  const sk = SKY[night ? 'night' : 'day'], sg = g.createLinearGradient(0, 0, 0, G.hy); sg.addColorStop(0, sk[0]); sg.addColorStop(1, sk[1]);
  g.fillStyle = sg; g.fillRect(0, 0, w, G.hy + 2);
  if (night) { g.fillStyle = '#ecd88d'; g.beginPath(); g.arc(w * .82, G.hy * .32, 14, 0, TAU); g.fill(); g.fillStyle = sk[0]; g.beginPath(); g.arc(w * .82 + 6, G.hy * .32 - 4, 12, 0, TAU); g.fill();
    g.fillStyle = '#f6e3a0'; for (let i = 0; i < 16; i++) { g.beginPath(); g.arc((i * 97) % w, (i * 37) % (G.hy * .6) + 6, 1.1, 0, TAU); g.fill(); } }
  else { g.fillStyle = '#f5c862'; g.beginPath(); g.arc(w * .82, G.hy * .3, Math.min(17, G.hy * .2), 0, TAU); g.fill(); }
  g.fillStyle = '#a9c48d'; g.beginPath(); g.moveTo(0, G.hy + 6); for (let x = 0; x <= w; x += w / 10) g.lineTo(x, G.hy - 6 + Math.sin(x * .03) * 5); g.lineTo(w, G.hy + 8); g.closePath(); g.fill();
  const far = SPRUCE.far;
  const nFar = Math.max(9, Math.round(w / 34));
  for (let i = 0; i < nFar; i++) { const x = (i + .5) * w / nFar + (rnd(i) - .5) * 16; drawSpruce(p, x, G.hy + 6, G.L * (.2 + rnd(i + 9) * .09), {col: far, tiers: 4}); }
  const gr = g.createLinearGradient(0, G.hy, 0, h); gr.addColorStop(0, '#b5cf96'); gr.addColorStop(1, '#a3c584');
  g.fillStyle = gr; g.fillRect(0, G.hy + 4, w, h - G.hy);
  // the corridor: lighter cleared ground between the neighbours, where the tree should lie
  const corridor = [{x: G.base.x, y: G.base.y}]; for (let i = 0; i <= 16; i++) corridor.push(groundPt(G, lerp(gL, gR, i / 16), 1.08));
  g.beginPath(); corridor.forEach((q, i) => i ? g.lineTo(q.x, q.y) : g.moveTo(q.x, q.y)); g.closePath();
  g.fillStyle = '#cfe0a8'; g.fill();
  if (hc) { g.setLineDash([7, 5]); g.lineWidth = 2; g.strokeStyle = night ? '#ffd34d' : '#3a2610'; g.stroke(); g.setLineDash([]); }
  // old stumps of the clearing
  for (const [fx, fy, r] of [[-.36, .14, .05], [.36, .2, .045], [-.14, .5, .035], [.2, .56, .03], [-.42, .52, .03], [.44, .6, .03]]) {
    const q = {x: G.base.x + fx * w, y: G.base.y - fy * (G.base.y - G.hy)}; if (inPoly(corridor, q.x, q.y) || Math.abs(q.x - G.base.x) < G.tw * 1.4) continue;
    drawStump(p, q.x, q.y, G.L * r, G.L * r * .7);
  }
  // ---- neighbours: the two that bound the gap, and more beyond them
  const trees = [];
  const addTree = (th, f, hk) => { const q = groundPt(G, th, f), d = .55 + .45 * (q.y - G.hy) / (G.base.y - G.hy); trees.push({th, x: q.x, y: q.y, hh: G.L * d * hk}); };
  addTree(gL - .1, .62, .74); addTree(gR + .1, .62, .7);           // the two that bound the gap, half way along the fall
  addTree(gL - .55, .9, .64); addTree(gR + .55, .9, .62);
  const hitN = st.crooked && (phase === 'tree_result' || (phase === 'fall' && k > .92)) ? trees.reduce((b, tr) => !b || Math.abs(tr.th - fellTh) < Math.abs(b.th - fellTh) ? tr : b, null) : null;
  trees.sort((a, b) => a.y - b.y);
  const drawNeighbour = tr => {
    if (tr === hitN && !st.calm) { const sw = Math.sin(((st.fallMs || 0) - FELL_ANIM.fall_ms) / 70) * Math.max(0, 1 - ((st.fallMs || 0) - FELL_ANIM.fall_ms) / 1200) * .06; g.save(); g.translate(tr.x, tr.y); g.rotate(sw); drawSpruce(p, 0, 0, tr.hh, {col: S, tiers: 5}); g.restore(); }
    else drawSpruce(p, tr.x, tr.y, tr.hh, {col: S, tiers: 5});
  };
  // pile of the logs already felled: the near corner on the fall side (safe from the next tree)
  const pile = {x: G.base.x + side * Math.min(w * .34, G.L * .62), y: Math.min(h - 50, G.base.y + h * .05)};
  const behind = trees.filter(tr => tr.y < G.base.y - 4), front = trees.filter(tr => tr.y >= G.base.y - 4);
  behind.forEach(drawNeighbour);
  // ---- the target tree: stump with notch and kerf, then the upper part (upright or falling)
  const B = {x: G.base.x, y: G.cutY}, tw = G.tw, stumpH = G.base.y - G.cutY;
  // sawdust heap on the back-cut side grows with the cut
  const dust = clamp((st.cut || 0) / 1000, 0, 1) + (k > 0 ? 1 : 0);
  if (dust > 0) { const dx = G.base.x - side * tw * .9; p.ellipse(dx, G.base.y + 1, tw * (.5 + .5 * Math.min(1, dust)), tw * .16 * Math.min(1, dust + .3), LJ_PAL.chip); }
  drawStump(p, G.base.x, G.base.y, tw / 2, stumpH);
  const notchD = tw * .34, notchH = tw * .42;
  const fallDir = (() => { const q = groundPt(G, fellTh), dx = q.x - B.x, dy = q.y - B.y; return {gx: dx, gy: dy}; })();
  const above = G.L - stumpH;
  const drawTarget = () => {
    const beta = k * Math.PI / 2, ax = Math.sin(beta) * fallDir.gx / above, ay = -Math.cos(beta) + Math.sin(beta) * fallDir.gy / above;
    const an = Math.hypot(ax, ay) || 1, ws = 1 - .42 * Math.sin(beta), nx = -ay / an * ws, ny = ax / an * ws;
    if (k > 0) {   // the tree's shadow on the ground grows under it as it comes down: it reads as lying, not standing
      const sb = Math.sin(beta), tx2 = B.x + fallDir.gx * sb, ty2 = B.y + fallDir.gy * sb, dx = tx2 - B.x, dy = ty2 - B.y, dn = Math.hypot(dx, dy) || 1, ox = -dy / dn, oy = dx / dn, wd = tw * (.3 + 1.1 * sb);
      g.fillStyle = '#41623526'; g.beginPath(); g.moveTo(B.x + ox * tw * .5, B.y + oy * tw * .5 + 3);
      g.lineTo(lerp(B.x, tx2, .35) + ox * wd, lerp(B.y, ty2, .35) + oy * wd + 3); g.lineTo(tx2, ty2 + 3); g.lineTo(lerp(B.x, tx2, .35) - ox * wd, lerp(B.y, ty2, .35) - oy * wd + 3);
      g.lineTo(B.x - ox * tw * .5, B.y - oy * tw * .5 + 3); g.closePath(); g.fill();
    }
    g.save(); g.transform(nx, ny, -ax, -ay, B.x, B.y);
    sceneTree(p, G, S, k);
    if (k === 0) {   // the notch (face cut) on the fall side and the back cut from the other side
      const ex = side * tw / 2;
      p.pf([ex, -notchH, ex - side * notchD, 0, ex, 1], '#5a4636');
      p.pf([ex, -notchH * .8, ex - side * notchD * .82, -.6, ex, -.4], LJ_PAL.wood);
      const kl = clamp((st.cut || 0) / 1000, 0, 1) * tw * .96;
      if (kl > 0) { g.lineCap = 'butt'; p.line(-side * tw / 2, -2.4, -side * tw / 2 + side * kl, -2.4, st.pinch ? '#2b1d12' : '#3b2a1c', hc ? 3 : 2.2); }
    }
    g.restore();
  };
  if (k === 0) drawTarget();
  // ---- the people: the farmer (player) at the back cut, Stepan aside showing the way
  const me = st.look === 'f' ? 'farmer_f' : 'farmer';   // the player's look by the address form (trip_game passes it)
  const fs = G.fs, cutting = phase === 'cut', run = cutting && st.holding && !st.stalled ? (st.t || 1) : 0;
  const kerf = clamp((st.cut || 0) / 1000, 0, 1) * tw * .96, kerfEnd = G.base.x - side * tw / 2 + side * kerf;
  const sawX = kerfEnd - side * SAW_POSE.tip.x * fs, sawY = B.y - 2.4 - SAW_POSE.tip.y * fs;
  const retreat = k > 0 || phase === 'tree_result' || phase === 'over' ? 1 : 0;
  const stepan = {x: G.base.x - side * Math.min(w * .4, G.L * .72), y: G.base.y - h * .085};
  stepan.x = clamp(stepan.x, w * .1, w * .9);
  const aimPt = arcPt(G, phase === 'aim' ? (gL + gR) / 2 : fellTh), pa = Math.atan2(aimPt.y - (stepan.y - 30 * fs), (aimPt.x - stepan.x) * side);
  drawFigure(p, stepan.x, stepan.y, 'stepan', phase === 'over' ? 'stand' : 'point', {scale: fs * .92, dir: side, pointAngle: clamp(pa, -1.45, -.15)});
  if (phase === 'aim' || phase === 'intro' || cutting) {
    const grey = !!st.stalled;
    drawFigure(p, sawX, sawY, me, 'saw', {scale: fs, dir: side, run, grey, bar: false});
    // the bar: visible only outside the trunk
    g.save(); g.beginPath(); if (side > 0) g.rect(0, 0, G.base.x - tw / 2, h); else g.rect(G.base.x + tw / 2, 0, w, h); g.clip();
    g.save(); g.translate(sawX, sawY); g.scale(fs * side, fs); g.translate(SAW_POSE.body.x, SAW_POSE.body.y + (run ? Math.sin(run / 16) * .45 : 0)); sawBar(p, {len: 20, run: grey ? 0 : run}); g.restore();
    g.restore();
    // chips fly back from the kerf while the chain runs
    if (run && phase === 'cut') {
      const ex = G.base.x - side * tw / 2, ey = B.y - 2;
      for (let i = 0; i < 22; i++) {
        const ph = ((t / 520) + i / 22) % 1, r = rnd(i), sp = .55 + r * .6, x = ex - side * (6 + 70 * ph * sp), y = ey - 22 * ph * rnd(i + 5) + 64 * ph * ph;
        g.globalAlpha = 1 - ph * .7; p.ellipse(x, y, 1.3 + r * 1.6, .8 + r * .6, i % 3 ? LJ_PAL.chip : LJ_PAL.chipDark); g.globalAlpha = 1;
      }
    }
    if (grey && !st.calm) for (let i = 0; i < 3; i++) { const ph = ((t / 1400) + i / 3) % 1, bx = sawX - side * 4 * fs, by = sawY - 22 * fs; g.globalAlpha = .55 * (1 - ph); p.ellipse(bx - side * ph * 10, by - ph * 34, 4 + ph * 7, 3 + ph * 5, '#c9cfc9'); g.globalAlpha = 1; }
  } else {
    drawFigure(p, sawX - side * (G.L * .08) * retreat, Math.min(h - 40, sawY + h * .05), me, 'carry', {scale: fs, dir: side});
  }
  if (k > 0) drawTarget();
  front.forEach(drawNeighbour);
  drawLogPile(p, pile.x, pile.y, Math.max(6, G.L * .028), (st.felled || []).length);
  // landing: needles and dust where the crown touched
  if (k >= .98 && (st.fallMs || 0) < FELL_ANIM.fall_ms + FELL_ANIM.dust_ms && !st.calm) {
    const ph = ((st.fallMs || 0) - FELL_ANIM.fall_ms) / FELL_ANIM.dust_ms, q = {x: B.x + fallDir.gx * .7, y: B.y + fallDir.gy * .7};
    for (let i = 0; i < 10; i++) { const a = rnd(i) * TAU, r = 8 + ph * 40 * (.5 + rnd(i + 3)); g.globalAlpha = Math.max(0, .8 - ph); p.ellipse(q.x + Math.cos(a) * r, q.y + Math.sin(a) * r * .35 - ph * 8, 2.6 + ph * 3.4, 1.6 + ph * 1.8, i % 2 ? '#7fa36f' : '#d8ccb0'); g.globalAlpha = 1; }
  }
  // ---- night: the farm's darkness, a lantern by Stepan, then the readable UI on top
  if (night) {
    const dim = hc ? .5 : 1, cx = (G.base.x + stepan.x) / 2, cyy = G.base.y - G.L * .22;
    const og = g.createRadialGradient(cx, cyy, G.L * .12, cx, cyy, Math.max(w, h) * .8);
    og.addColorStop(0, `rgba(14,24,40,${.34 * dim})`); og.addColorStop(.55, `rgba(14,24,40,${.56 * dim})`); og.addColorStop(1, `rgba(14,24,40,${.7 * dim})`);
    g.fillStyle = og; g.fillRect(0, 0, w, h);
    const lx = stepan.x + side * 18 * fs, ly = stepan.y - 2;
    const rg = g.createRadialGradient(lx, ly - 30 * fs, 0, lx, ly - 30 * fs, 120 * fs); rg.addColorStop(0, '#f6e3a04d'); rg.addColorStop(1, '#f6e3a000');
    g.fillStyle = rg; g.fillRect(lx - 130 * fs, ly - 150 * fs, 260 * fs, 260 * fs);
    p.line(lx, ly, lx, ly - 34 * fs, '#5f4630', 2.4 * fs); p.line(lx, ly - 34 * fs, lx + side * 6 * fs, ly - 34 * fs, '#5f4630', 1.6 * fs);
    p.pf([lx + side * 4 * fs, ly - 33 * fs, lx + side * 8 * fs, ly - 33 * fs, lx + side * 8.6 * fs, ly - 26 * fs, lx + side * 3.4 * fs, ly - 26 * fs], '#f3d27a');
  }
  const ink = night ? '#f2edc4' : '#26402d', strong = night ? '#ffffff' : '#10231a';
  // ---- the direction arc and the mark
  if (phase === 'aim' || phase === 'intro') {
    const track = (a, b, col, wd) => { g.beginPath(); for (let i = 0; i <= 30; i++) { const q = arcPt(G, lerp(a, b, i / 30)); i ? g.lineTo(q.x, q.y) : g.moveTo(q.x, q.y); } g.strokeStyle = col; g.lineWidth = wd; g.lineCap = 'round'; g.stroke(); };
    const A = FELL_ANIM.max_angle;
    track(-A, A, hc ? strong : (night ? '#1d2c44cc' : '#fffef6d0'), 14);
    track(-A, A, night ? '#6f8a78' : '#7e9c7a', 8);
    track(gL, gR, hc ? strong : night ? '#2b3a2a' : '#2b5a3a', 13); track(gL, gR, night ? '#f6e3a0' : '#f7e7a6', 9);
    track(dL, dR, night ? '#ffd34d' : '#e2b04a', 9);                         // the perfect notch: ±50 around the centre
    for (const tr of trees.slice(0).filter(tr => Math.abs(tr.th) <= A + .02)) {   // little spruces on the blocked parts of the arc
      const q = arcPt(G, tr.th), s = 7; g.fillStyle = night ? '#2d4a3d' : '#456d54'; g.beginPath(); g.moveTo(q.x, q.y - s - 3); g.lineTo(q.x + s, q.y + 4); g.lineTo(q.x - s, q.y + 4); g.closePath(); g.fill();
      if (hc) { g.lineWidth = 1.5; g.strokeStyle = night ? '#ffffff' : '#10231a'; g.stroke(); }
    }
    const best = arcPt(G, fellTheta(gap.center)); g.fillStyle = night ? '#2b3a2a' : '#2b5a3a'; g.beginPath(); g.arc(best.x, best.y, 2.6, 0, TAU); g.fill();
    const gc = arcPt(G, (gL + gR) / 2, 1.14); pill(g, 'Просвет', gc.x, clamp(gc.y, 16, h), {night, contrast: hc, size: 13});
    // fall preview: a dashed line on the ground from the trunk to where the tree will lie
    const gq = groundPt(G, aimTh), inGap = aimTh >= gL && aimTh <= gR;
    g.setLineDash([8, 7]); g.lineWidth = hc ? 3 : 2.4; g.strokeStyle = inGap ? (night ? '#f6e3a0' : '#2f6f4b') : (night ? '#ffb7a0' : '#a4502e'); g.beginPath(); g.moveTo(G.base.x, G.cutY - 4); g.lineTo(gq.x, gq.y); g.stroke(); g.setLineDash([]);
    // the mark: a pointer on the arc aimed at the tree
    const m = arcPt(G, aimTh), dx = G.base.x - m.x, dy = G.base.y - m.y, dn = Math.hypot(dx, dy), ux = dx / dn, uy = dy / dn;
    g.beginPath(); g.moveTo(m.x + ux * 11, m.y + uy * 11); g.lineTo(m.x - ux * 9 - uy * 10, m.y - uy * 9 + ux * 10); g.lineTo(m.x - ux * 9 + uy * 10, m.y - uy * 9 - ux * 10); g.closePath();
    g.fillStyle = '#ffffff'; g.fill(); g.lineWidth = hc ? 3 : 2; g.strokeStyle = night ? '#1d2c44' : '#26402d'; g.stroke();
    if (phase === 'intro') pill(g, 'Приготовься…', w / 2, G.hy * .62, {night, contrast: hc});
  }
  // ---- heat and cut gauges (only while sawing)
  if (cutting) {
    const bw = Math.min(420, w - 28), x = (w - bw) / 2, y = 8, ph = 76;
    g.fillStyle = night ? (hc ? '#1d2c44' : '#1d2c44e6') : (hc ? '#ffffff' : '#fffef6e6'); rr(g, x - 10, y, bw + 20, ph, 14); g.fill();
    if (hc) { g.lineWidth = 2; g.strokeStyle = strong; g.stroke(); }
    const heat = clamp(st.heat || 0, 0, 1000), hot = heat >= 800 && !st.stalled;
    g.font = '750 13px system-ui,"Segoe UI",sans-serif'; g.textBaseline = 'middle'; g.fillStyle = ink; g.textAlign = 'left';
    g.fillText('Нагрев цепи', x, y + 13); g.textAlign = 'right';
    g.fillStyle = st.stalled ? (night ? '#ffb7a0' : '#9a4b2a') : hot ? (night ? '#ffb7a0' : '#a4502e') : ink;
    g.fillText(st.stalled ? 'заглохла' : st.pinch ? 'зажим — отпусти!' : hot ? 'горячо — отпусти!' : st.holding ? 'пилит' : 'остывает', x + bw, y + 13);
    const by = y + 26, bh = 14;
    for (const [a, b, col] of [[0, 600, '#7fb36a'], [600, 850, '#e0b850'], [850, 1000, '#d9805c']]) { g.fillStyle = st.stalled ? '#c9c4b8' : col; g.fillRect(x + bw * a / 1000, by, bw * (b - a) / 1000, bh); }
    if (st.stalled) { g.save(); rr(g, x, by, bw, bh, 5); g.clip(); g.strokeStyle = '#8f8a80'; g.lineWidth = 3; for (let sx = x - bh; sx < x + bw; sx += 10) { g.beginPath(); g.moveTo(sx, by + bh); g.lineTo(sx + bh, by); g.stroke(); } g.restore(); }
    g.strokeStyle = strong; g.lineWidth = hc ? 2 : 1.5; rr(g, x, by, bw, bh, 5); g.stroke();
    const nx = x + bw * heat / 1000; g.fillStyle = strong; g.beginPath(); g.moveTo(nx, by - 1); g.lineTo(nx - 6, by - 8); g.lineTo(nx + 6, by - 8); g.closePath(); g.fill(); g.fillRect(nx - 1.5, by - 1, 3, bh + 3);
    // cut progress with the pinch marks of the plan
    const cy = y + 57, ch = 8, cut = clamp(st.cut || 0, 0, 1000);
    g.fillStyle = ink; g.font = '650 12px system-ui,"Segoe UI",sans-serif'; g.textAlign = 'left'; g.fillText(`Пропил ${Math.round(cut / 10)} %`, x, cy + 4);
    const ready = cut >= FELL_RULES.hinge_pct * 10;
    const cx0 = x + 96, cw = bw - 96; g.fillStyle = night ? '#ffffff22' : '#00000018'; rr(g, cx0, cy, cw, ch, 4); g.fill();
    const hz = FELL_RULES.hinge_pct * 10;                                // let go between the hinge and the cut-through
    g.fillStyle = night ? '#4f8a5a' : '#b9dca0'; g.fillRect(cx0 + cw * hz / 1000, cy, cw * (1000 - hz) / 1000 - 3, ch);
    g.fillStyle = night ? '#e8c78f' : '#a47544'; rr(g, cx0, cy, cw * cut / 1000, ch, 4); g.fill();
    g.fillStyle = strong; g.fillRect(cx0 + cw * hz / 1000 - 1, cy - 3, 2, ch + 6); g.fillStyle = '#d9805c'; g.fillRect(cx0 + cw - 3, cy - 2, 3, ch + 4);
    for (const pm of st.pinches || []) { const px = cx0 + cw * pm / 1000; g.fillStyle = strong; g.beginPath(); g.moveTo(px, cy - 1); g.lineTo(px - 4, cy - 6); g.lineTo(px + 4, cy - 6); g.closePath(); g.fill(); }
    if (hc) { g.strokeStyle = strong; g.lineWidth = 1.5; rr(g, cx0, cy, cw, ch, 4); g.stroke(); }
    // pinch: the kerf squeezes the bar — arrows on the trunk and a bubble
    if (st.pinch) {
      const ex = G.base.x - side * tw / 2 + side * kerf * .5, ey = B.y - 2.4;
      g.fillStyle = night ? '#ffd2bf' : '#a4502e';
      for (const d of [-1, 1]) { g.beginPath(); g.moveTo(ex, ey + d * 4); g.lineTo(ex - 6, ey + d * 13); g.lineTo(ex + 6, ey + d * 13); g.closePath(); g.fill(); }
      pill(g, 'Зажало пилу — отпусти!', w / 2, Math.max(y + ph + 26, G.cutY - G.L * .42), {night, contrast: hc, tone: 'bad', size: 16});
    } else if (st.stalled) pill(g, 'Пила заглохла — дорезай медленно', w / 2, Math.max(y + ph + 26, G.cutY - G.L * .42), {night, contrast: hc, tone: 'bad', size: 16});
    else if (ready && st.holding) pill(g, 'Отпусти — дерево пойдёт!', w / 2, Math.max(y + ph + 26, G.cutY - G.L * .42), {night, contrast: hc, tone: 'good', size: 16});
    else if (hot && st.holding) pill(g, 'Цепь горячая — отпусти', w / 2, Math.max(y + ph + 26, G.cutY - G.L * .42), {night, contrast: hc, tone: 'bad', size: 16});
  }
  if (phase === 'tree_result' && st.verdict) pill(g, st.verdict.text, w / 2, Math.max(30, G.hy * .55), {night, contrast: hc, tone: st.verdict.tone, size: 18});
  // trees of the plot: five spruce badges at the bottom edge (done ✓ / crooked ~ / current / waiting)
  const total = st.total || 5, felled = st.felled || [], bs = 22, gapB = 8, bx0 = 12, by0 = h - bs - 8;
  for (let i = 0; i < total; i++) {
    const x = bx0 + i * (bs + gapB), f = felled[i], cur = i === (st.index || 0) && phase !== 'over';
    g.fillStyle = night ? (hc ? '#16281f' : '#16281fd0') : (hc ? '#ffffff' : '#fffef6d8'); rr(g, x, by0, bs, bs, 7); g.fill();
    g.lineWidth = cur ? 3 : (hc ? 2 : 1.2); g.strokeStyle = cur ? (night ? '#ffd34d' : '#2f6f4b') : (hc ? strong : (night ? '#8fb59a' : '#b9c4a6')); g.stroke();
    g.fillStyle = f ? (night ? '#6c9670' : '#456d54') : (night ? '#55705f' : '#a9b9a0');
    g.beginPath(); g.moveTo(x + bs / 2, by0 + 4); g.lineTo(x + bs - 6, by0 + bs - 6); g.lineTo(x + 6, by0 + bs - 6); g.closePath(); g.fill();
    if (f) { g.font = '800 12px system-ui,sans-serif'; g.textAlign = 'center'; g.textBaseline = 'middle'; g.fillStyle = f.crooked ? (night ? '#ffb7a0' : '#a4502e') : (night ? '#d9f2c9' : '#1f5a32'); g.fillText(f.crooked ? '~' : '✓', x + bs - 5, by0 + 6); }
  }
}

/**
 * Per-tree verdict from the server-rule result of one tree (fell_tree: {acc, cut, points, result, stalled}).
 * 12+, no injuries: the worst outcomes are «легло криво», «пила заглохла», «перепил».
 */
export function fellVerdict(r) {
  const pts = r.points ?? Math.floor((4 * (r.acc || 0) + 6 * (r.cut || 0)) / 10);
  if (r.result === 'idle') return {text: 'Без пропила — дорежет Степан', tone: 'bad', crooked: true, score: pts};
  if (r.result === 'timeout') return {text: `Не допилено — дорежет Степан · ${pts}`, tone: 'bad', crooked: true, score: pts};
  if (r.result === 'cut_through') return {text: `Перепил: легло раньше · ${pts}`, tone: 'bad', crooked: (r.acc || 0) <= 0, score: pts};
  if ((r.acc || 0) <= 0) return {text: `Легло криво · ${pts}`, tone: 'bad', crooked: true, score: pts};
  if (r.stalled) return {text: `Легло, пила глохла · ${pts}`, tone: 'good', crooked: false, score: pts};
  return {text: (r.acc >= 800 && r.cut >= 800 ? 'Легло ровно! · ' : 'Легло · ') + pts, tone: 'good', crooked: false, score: pts};
}
