// «Битва с Сантой» (docs/tasks/FARM_SANTA_BATTLE.md): the battle scene, the fighters' poses and the hit effects.
// One SVG per theme, viewBox 0 0 1000 600 = the screen: the village square by the New Year tree seen from the side,
// Дед Мороз and Снегурочка on the left facing right, Санта and Крампус on the right (the game mirrors them to face left).
// The quarrel is Дед Мороз's with Санта; the player fights on Дед Мороз's side (owner's decisions 2026-11-19), drawn as
// a grown-up farmer with a moustache in winter clothes.
// Fighters and effects are drawings in <defs> at figure units (feet at 0,0); the game places them with
// <use href="#sb-<who>-<pose>" transform="translate(x y) scale(±SCALE SCALE)"> at the anchors in data-anchors.
// Farm palette and primitives (makeS/SvgCtx, as the ballista and pie scenes). No raster, no filters, no inline styles.
import {makeS} from '../village/common.js';
import {SvgCtx} from '../village/svg_ctx.js';
import {dedMoroz, snegurochka, santa, krampus, eyes, POSES} from '../village/new_year_guests.js';

export const SCALE = 4;
// feet of each fighter in scene px; solo = the only enemy of battles 1 and 2
export const ANCHORS = {snegurochka: [130, 448], ded_moroz: [250, 494], player: [376, 540],
  krampus: [660, 528], santa: [812, 480], solo: [740, 506]};

// ---------- the player: a farmer with a moustache ----------------------------------------------------------------------
// Profile facing right like the village figure, but grown-up: ushanka, quilted vatnik, scarf, felt boots, a big moustache.
const FM = {skin: '#f0c9a4', cheek: '#e9a58f', nose: '#e39a84', eye: '#2f3338', hair: '#7a4a2e', tache: '#6b3f26',
  coat: '#4f6e4a', coatShade: '#435f40', quilt: '#3d5739', trousers: '#4a5a72', boot: '#8a8f96', bootSole: '#5c6168',
  hat: '#7a5a3c', hatSeam: '#6a4c32', fur: '#e3cfa8', furShade: '#cdb58a', scarf: '#c9473f', stripe: '#f3e3d3',
  mitten: '#c9473f', button: '#2b3a29', mouth: '#8a3b34', shadow: '#41623530'};
// legs: [backFootX, frontFootX, backLift, frontLift]; back/front: hand positions; bob: body lift
const FARMER_POSE = {
  stand: {legs: [-3, 3, 0, 0], back: [-8.2, -16.4], front: [8.4, -16.6], bob: 0, mood: 'normal'},
  attack: {legs: [-5.6, 5.8, 1.6, 0], back: [-9, -20], front: [11.8, -35.4], bob: .8, mood: 'fierce', ball: true},
  hurt: {legs: [-4, 2.2, 0, 1.2], back: [-8.6, -30.6], front: [6.8, -33.6], bob: 0, mood: 'hurt'},
  win: {legs: [-2.8, 2.8, 1.4, 1.4], back: [-12.4, -39], front: [12.6, -39.6], bob: 2.6, mood: 'happy'},
  down: {legs: [-3, 3, 0, 0], back: [-10.6, -14], front: [10.8, -14], bob: 0, mood: 'dizzy'},
};

function farmer(s, pose = 'stand') {
  const q = FARMER_POSE[pose], [bx, fx, bl, fl] = q.legs, y = -q.bob;
  const poly = (pts, col) => s.poly(pts.map(([a, b]) => ({x: a, y: b})), col);
  const leg = (hx, footX, lift) => {
    s.line(hx, y - 12, footX, -2 - lift, FM.trousers, 4.4);
    s.ellipse(footX + .6, -1.6 - lift, 3.2, 2.2, FM.boot); s.ellipse(footX + .8, -.4 - lift, 3.4, 1, FM.bootSole);
  };
  const hand = ([hx, hy], sleeve) => { s.line(sleeve === FM.coat ? 5 : -5, y - 27, hx, y + hy, sleeve, 3.8); s.ellipse(hx, y + hy, 2.1, 2.1, FM.mitten); };
  s.ellipse(1.5, .6, 10.5, 3, FM.shadow);
  // back leg and arm, then the vatnik, then the near leg and arm
  leg(-2, bx, bl); hand(q.back, FM.coatShade);
  s.ellipse(0, y - 20.6, 7.6, 9.4, FM.coat);
  poly([[-7.2, y - 14], [7.2, y - 14], [7.8, y - 10.4], [-7.8, y - 10.4]], FM.coat);
  for (const k of [-24.6, -20.6, -16.6, -12.6]) s.line(-6.6, y + k, 6.8, y + k, FM.quilt, .55);      // quilting
  s.line(1.4, y - 29, 1.8, y - 10.6, FM.quilt, .7);
  for (const k of [-25, -20.4, -15.8]) s.ellipse(2.8, y + k, .7, .7, FM.button);
  leg(2, fx, fl);
  // scarf: a band round the neck and a tail flying back
  poly([[-4.8, y - 31], [4.8, y - 31], [5.2, y - 28], [-5.2, y - 28]], FM.scarf);
  s.line(-4.4, y - 29.5, 4.4, y - 29.5, FM.stripe, .8);
  poly([[-3.6, y - 29.6], [-1.2, y - 29.6], [-8, y - 22.4], [-9.8, y - 24.2]], FM.scarf);
  s.line(-6, y - 26, -4.4, y - 27.6, FM.stripe, .8);
  hand(q.front, FM.coat);
  if (q.ball) {
    const [hx, hy] = q.front;
    s.ellipse(hx + 1.8, y + hy - 2.2, 2.6, 2.6, '#c5d3e3'); s.ellipse(hx + 1.4, y + hy - 2.6, 2.2, 2.2, '#fbfcfe');
  }
  // head in profile facing right: hair at the back, ear, a big nose and a bushy moustache
  const hy = y - 35.6;
  s.ellipse(.8, hy, 5.4, 5.8, FM.skin);
  s.ellipse(-3.4, hy + .6, 2.4, 3.6, FM.hair);
  s.ellipse(-1.2, hy + .6, 1.3, 1.7, FM.cheek);
  s.ellipse(6.2, hy + .8, 1.9, 1.6, FM.nose);
  s.ellipse(3.6, hy + 2.2, 1.4, .9, FM.cheek);
  eyes(s, [[3.6, hy - .9]], q.mood, {r: .8, col: FM.eye, brow: FM.hair, browY: -1.6});
  if (q.mood === 'normal') s.line(2.4, hy - 2.7, 4.8, hy - 2.9, FM.hair, .8);
  if (q.mood === 'happy' || q.mood === 'hurt') s.ellipse(4.6, hy + 4.4, 1.2, q.mood === 'happy' ? .9 : 1, FM.mouth);
  s.ellipse(5, hy + 2.8, 3, 1.3, FM.tache); s.ellipse(2.8, hy + 3.2, 2.2, 1.1, FM.tache);
  s.ellipse(1.2, hy + 3.8, 1, .7, FM.tache);                                              // the moustache's curled end
  // ushanka: crown, fur band, the flap over the ear at the back
  s.ellipse(.4, hy - 6, 6.4, 3.8, FM.hat);
  s.line(.4, hy - 9.6, .6, hy - 5, FM.hatSeam, .5);
  s.ellipse(-3.8, hy - .8, 2.2, 3.4, FM.fur); s.ellipse(-3.6, hy + .8, 1.6, 1.6, FM.furShade);
  s.ellipse(.8, hy - 3.8, 7, 1.8, FM.fur);
}

// ---------- the player, the other look: a slim farmer woman (address form «она», owner's decision 2026-11-19) -----------
// The same moves and hand positions as the farmer: a fitted green coat with fur trim and a red sash, a red shawl with
// little flowers tied under the chin, a braid at the back, felt boots and red mittens.
const FW = {skin: '#f5d6b6', cheek: '#f0a99a', nose: '#efc09e', eye: '#2f3338', lash: '#2f3338', lips: '#c0605a',
  hair: '#9a5a36', hairShade: '#7e4529', coat: '#3f7a64', coatShade: '#346a56', fur: '#f1e4cc', furShade: '#ddcdb0',
  shawl: '#c9473f', shawlShade: '#a93a33', flower: '#f6e7c8', flowerHeart: '#f2c94c', boot: '#8a8f96', bootSole: '#5c6168',
  mitten: '#c9473f', shadow: '#41623530'};

function farmerWoman(s, pose = 'stand') {
  const q = FARMER_POSE[pose], [bx, fx, bl, fl] = q.legs, y = -q.bob;
  const poly = (pts, col) => s.poly(pts.map(([a, b]) => ({x: a, y: b})), col);
  const leg = (hx, footX, lift) => {
    s.line(hx, y - 7, footX * .8, -2 - lift, FW.boot, 3);
    s.ellipse(footX * .8 + .6, -1.5 - lift, 2.6, 1.8, FW.boot); s.ellipse(footX * .8 + .8, -.4 - lift, 2.8, .85, FW.bootSole);
  };
  const hand = ([hx, hy], sleeve) => {
    s.line(sleeve === FW.coat ? 4.4 : -4.4, y - 25.4, hx, y + hy, sleeve, 3.2);
    s.ellipse(hx - (hx > 0 ? 1 : -1) * 1.6, y + hy + .8, 1.6, 1.1, FW.fur);          // fur cuff
    s.ellipse(hx, y + hy, 1.9, 1.9, FW.mitten);
  };
  const hy = y - 33.4;
  s.ellipse(1.2, .6, 9.4, 2.8, FW.shadow);
  // the braid comes out under the shawl at the back and hangs down to the waist
  for (let k = 0; k < 6; k++) s.ellipse(-4.6 - k * .25, hy + 6.2 + k * 2.1, 1.35, 1.2, k % 2 ? FW.hairShade : FW.hair);
  s.ellipse(-6, hy + 18.6, 1.4, .85, FW.shawl);
  leg(-1.4, bx, bl); hand(q.back, FW.coatShade);
  // the coat: a fitted bodice, a red sash at a slim waist, a skirt flaring to a fur hem, a fur band down the front
  s.ellipse(0, y - 21.8, 5.4, 5.6, FW.coat);
  poly([[-4.2, y - 17.4], [4.4, y - 17.4], [8.4, y - 5.2], [-8, y - 5.2]], FW.coat);
  poly([[-7.5, y - 7.6], [7.9, y - 7.6], [8.6, y - 4.6], [-8.2, y - 4.6]], FW.fur);
  poly([[1, y - 26], [2.4, y - 26], [3.5, y - 7.6], [1.9, y - 7.6]], FW.fur);
  s.line(-4.2, y - 17.2, 4.4, y - 17.2, FW.shawl, 1.6);
  s.line(-3.6, y - 17, -6.2, y - 13.6, FW.shawl, 1.1); s.line(-3.2, y - 17, -5, y - 12.8, FW.shawlShade, 1.1);   // sash ends
  for (const [x, yy] of [[-3.8, -13], [5, -11.6], [-1.6, -21.4]]) s.ellipse(x, y + yy, .7, .7, FW.coatShade);    // little pattern
  leg(1.4, fx, fl);
  hand(q.front, FW.coat);
  if (q.ball) {
    const [hx, hy2] = q.front;
    s.ellipse(hx + 1.8, y + hy2 - 2.2, 2.6, 2.6, '#c5d3e3'); s.ellipse(hx + 1.4, y + hy2 - 2.6, 2.2, 2.2, '#fbfcfe');
  }
  // the shawl: over the head and down the back, the face framed by it, tied under the chin
  poly([[-5.6, hy + 1.4], [-.6, hy + 4.8], [-6.6, y - 20.4], [-8, y - 21.6]], FW.shawl);
  s.ellipse(-.2, hy - .8, 6, 6.4, FW.shawl);
  for (const [x, yy] of [[-3.6, -3.4], [-1, -5.6], [-4.4, .6], [-6.4, 6.4], [-3.4, 4]]) {          // little flowers
    s.ellipse(x, hy + yy, .95, .95, FW.flower); s.ellipse(x, hy + yy, .4, .4, FW.flowerHeart);
  }
  s.ellipse(1.6, hy + .6, 4.3, 4.7, FW.skin);                              // the face inside the shawl
  poly([[-1, hy - 3.2], [3.6, hy - 3.6], [4.8, hy - 2], [2, hy - 2.4]], FW.hair);   // a fringe peeking out
  poly([[5.6, hy - .2], [6.8, hy + 1.4], [5.6, hy + 1.8]], FW.nose);
  s.ellipse(3, hy + 1.8, 1.2, .75, FW.cheek);
  eyes(s, [[3.8, hy - .6]], q.mood, {r: .75, col: FW.eye, brow: FW.hair, browY: -1.4});
  if (q.mood === 'normal' || q.mood === 'fierce') {
    s.line(4.3, hy - 1.5, 5.3, hy - 2.3, FW.lash, .5); s.line(3.7, hy - 1.7, 4.2, hy - 2.7, FW.lash, .5);
  }
  if (q.mood === 'happy') s.ellipse(4.8, hy + 3.2, 1.1, .8, FW.lips);
  else if (q.mood === 'hurt' || q.mood === 'dizzy') s.ellipse(4.8, hy + 3.2, .6, .7, FW.lips);
  else s.ellipse(4.8, hy + 3.1, .85, .45, FW.lips);
  s.line(-2.4, hy - 4.6, 3.2, hy - 4.8, FW.shawlShade, .8);               // the shawl's edge over the brow
  s.ellipse(2, hy + 5.6, 1.6, 1.2, FW.shawlShade);                         // the knot under the chin and its two ends
  s.line(2, hy + 6, 3.6, hy + 8.6, FW.shawl, 1.3); s.line(1.6, hy + 6, .8, hy + 8.8, FW.shawl, 1.3);
}

// ---------- pose wrapper: lean, jump, snowdrift ----------------------------------------------------------------------
const DRAW = {player: farmer, player_f: farmerWoman, ded_moroz: dedMoroz, snegurochka, santa, krampus};
const HEAD = {player: -46, player_f: -44, ded_moroz: -46, snegurochka: -40, santa: -38, krampus: -40};   // top of the head (for dizzy stars)

function star(s, x, y, r, col, points = 5) {
  const pts = [];
  for (let k = 0; k < points * 2; k++) {
    const a = -Math.PI / 2 + k * Math.PI / points, rr = k % 2 ? r * .45 : r;
    pts.push({x: x + Math.cos(a) * rr, y: y + Math.sin(a) * rr});
  }
  s.poly(pts, col);
}

function drawPose(c, s, who, pose, snow) {
  const lean = {attack: .1, hurt: -.15}[pose] || 0, sink = pose === 'down' ? 6 : 0, lift = pose === 'win' ? -3 : 0;
  c.save();
  c.translate(pose === 'attack' ? 1.5 : pose === 'hurt' ? -1.5 : 0, sink + lift);
  if (lean) c.transform(Math.cos(lean), Math.sin(lean), -Math.sin(lean), Math.cos(lean), 0, 0);
  DRAW[who](s, pose);
  c.restore();
  if (pose === 'down') {
    // sat down in a snowdrift up to the waist, stars round the head
    s.ellipse(0, 1.6, 16.4, 9.4, snow.shade); s.ellipse(-1.2, -.6, 14.6, 8.6, snow.lit);
    s.ellipse(-8.4, -6.4, 5.6, 3.6, snow.lit); s.ellipse(7.6, -5.6, 6.4, 3.8, snow.lit); s.ellipse(1.6, -7.4, 5, 2.8, snow.lit);
    s.ellipse(-4, -5.2, 3, 1, snow.shade);
    const hy = HEAD[who] + 9 - 3;
    star(s, -7, hy, 2.2, '#f2c94c'); star(s, 1, hy - 3, 1.8, '#f2c94c'); star(s, 8, hy + .4, 2, '#f2c94c');
  }
  if (pose === 'win') for (const [x, y, r] of [[-11, HEAD[who] + 4, 1.6], [11, HEAD[who] + 2, 2], [0, HEAD[who] - 4, 1.4]]) star(s, x, y, r, '#f2c94c', 4);
}

// ---------- effects (figure units; the game scales them like the fighters) -------------------------------------------
function effects(s, p) {
  const fx = {};
  fx.snowball = () => { s.ellipse(.4, .4, 3.2, 3.2, '#c5d3e3'); s.ellipse(0, 0, 3, 3, '#fbfcfe'); s.ellipse(-1, -1, 1, .8, '#ffffff'); };
  fx.hit = () => { star(s, 0, 0, 7, '#f2c94c', 8); star(s, 0, 0, 4, '#fff6cf', 8); };
  fx.blizzard = () => {
    for (const [r, a0, w] of [[11, 0, 1.6], [7.6, 1.2, 1.3], [4.4, 2.6, 1.1]]) {
      const pts = Array.from({length: 9}, (_, k) => [Math.cos(a0 + k * .55) * r * (1 + k * .04), Math.sin(a0 + k * .55) * r * .6 * (1 + k * .04)]);
      for (let k = 1; k < pts.length; k++) s.line(pts[k - 1][0], pts[k - 1][1], pts[k][0], pts[k][1], k % 2 ? '#e8f1fa' : '#ffffff', w);
    }
    for (const [x, y] of [[-12, -6], [10, -8], [13, 5], [-9, 8], [2, -11], [-2, 10]]) flakeFx(s, x, y, 1.8, '#ffffff');
  };
  fx.icestar = () => { star(s, 0, 0, 6, '#2f6fb3', 6); star(s, 0, 0, 4.4, '#a9dcf2', 6); s.ellipse(-1, -1.2, 1.2, .9, '#ffffff'); };
  fx.coal = () => {
    s.ellipse(0, 0, 4.4, 3.8, '#e58a4a80');
    s.poly([[-2.6, -1.4], [-.8, -2.8], [2, -2.4], [3, .2], [1.6, 2.4], [-1.6, 2.4], [-3, .6]].map(([x, y]) => ({x, y})), '#2f3135');
    s.ellipse(.8, -1, .8, .5, '#e8763d');
  };
  fx.candy = () => {
    const pts = [[-2.4, 7], [-2.4, -1], [-2, -3.6], [0, -5.2], [2.2, -4.4], [3, -2.2]];
    for (let k = 1; k < pts.length; k++) s.line(pts[k - 1][0], pts[k - 1][1], pts[k][0], pts[k][1], '#ffffff', 2.4);
    for (let k = 1; k < pts.length; k++) {
      const [x0, y0] = pts[k - 1], [x1, y1] = pts[k], mx = (x0 + x1) / 2, my = (y0 + y1) / 2;
      s.line(mx - (x1 - x0) * .18, my - (y1 - y0) * .18, mx + (x1 - x0) * .18, my + (y1 - y0) * .18, '#d23a32', 2.4);
    }
  };
  fx.gift = () => {
    s.poly([[-4, -3], [4, -3], [4, 4], [-4, 4]].map(([x, y]) => ({x, y})), '#d23a32');
    s.line(0, -3, 0, 4, '#e7c56c', 1.4); s.line(-4, .4, 4, .4, '#e7c56c', 1.4);
    s.ellipse(-1.6, -4.2, 1.8, 1.1, '#e7c56c'); s.ellipse(1.6, -4.2, 1.8, 1.1, '#e7c56c');
  };
  fx.chain = () => {
    for (let k = 0; k < 5; k++) {
      const x = -8 + k * 4, y = (k % 2) * 1.2;
      s.ellipse(x, y, 2.4, 1.5, '#8e959e'); s.ellipse(x, y, 1.3, .6, '#e9edf2');
    }
  };
  fx.switch = () => { for (const [y, w] of [[-4, 1.3], [0, 1.6], [4, 1.3]]) s.line(-9, y + 2, 8, y - 2, '#7a5a3c', w); star(s, 9, -2, 3.2, '#f2c94c', 4); };
  fx.notes = () => {
    for (const [x, y, k] of [[-7, 2, 1], [0, -3, 1.2], [7, 1, 1]]) {
      s.ellipse(x, y, 1.8 * k, 1.3 * k, '#2f6fb3'); s.line(x + 1.6 * k, y, x + 1.6 * k, y - 6 * k, '#2f6fb3', .7);
      s.line(x + 1.6 * k, y - 6 * k, x + 3.4 * k, y - 4.6 * k, '#2f6fb3', .9);
    }
  };
  fx.heal = () => {
    s.poly([[-1.6, -5], [1.6, -5], [1.6, -1.6], [5, -1.6], [5, 1.6], [1.6, 1.6], [1.6, 5], [-1.6, 5], [-1.6, 1.6], [-5, 1.6], [-5, -1.6], [-1.6, -1.6]].map(([x, y]) => ({x, y})), '#2f8a52');
    s.poly([[-.8, -4.2], [.8, -4.2], [.8, -.8], [4.2, -.8], [4.2, .8], [.8, .8], [.8, 4.2], [-.8, 4.2], [-.8, .8], [-4.2, .8], [-4.2, -.8], [-.8, -.8]].map(([x, y]) => ({x, y})), '#7fd39a');
  };
  fx.wall = () => {
    for (let row = 0; row < 3; row++) for (let k = 0; k < 4 - (row % 2); k++) {
      const x = -9 + k * 6 + (row % 2) * 3, y = -row * 4.4;
      s.poly([[x, y - 4], [x + 5.6, y - 4], [x + 5.6, y], [x, y]].map(([a, b]) => ({x: a, y: b})), '#c5d3e3');
      s.poly([[x + .3, y - 3.8], [x + 5.3, y - 3.8], [x + 5.3, y - 1], [x + .3, y - 1]].map(([a, b]) => ({x: a, y: b})), '#fbfcfe');
    }
  };
  fx.freeze = () => {
    s.poly([[-11, -46], [11, -46], [13, 2], [-13, 2]].map(([x, y]) => ({x, y})), '#a9dcf26e');
    s.line(-8, -40, -4, -44, '#ffffff', 1.2); s.line(-9, -34, -2, -42, '#ffffff', .8); s.line(9, -10, 11, -16, '#ffffff', 1);
    for (const [x, y] of [[-12, -46], [12, -46], [-13, 2], [13, 2]]) s.ellipse(x, y, 1, 1, '#ffffff');
  };
  fx.rage = () => {
    for (const [x, y, r] of [[-6, -2, 3.4], [-2, -6, 4.2], [4, -4, 3.6], [7, -9, 2.6]]) s.ellipse(x, y, r, r * .8, '#e0534a9c');
    for (const a of [0, Math.PI / 2, Math.PI, Math.PI * 1.5]) s.line(9 + Math.cos(a) * 1.2, -14 + Math.sin(a) * 1.2, 9 + Math.cos(a) * 3, -14 + Math.sin(a) * 3, '#c9302a', 1);
  };
  fx.sleigh = () => {
    // a reindeer with a red nose pulling a small red sleigh with presents (facing left: it flies across from the right)
    const deer = (x) => {
      s.line(x - 3, -9, x - 4, -1, p.deer, 1.6); s.line(x + 3, -9, x + 4, -1, p.deer, 1.6);
      s.ellipse(x, -11, 6, 3.6, p.deer); s.ellipse(x - 6.2, -15.6, 2.6, 2.2, p.deer); s.line(x - 4.8, -13.4, x - 3.4, -11.4, p.deer, 2.2);
      s.ellipse(x - 8.6, -15, 1.1, 1.1, '#e0534a'); s.ellipse(x - 6.4, -16.2, .4, .45, '#2f3338');
      s.line(x - 5.6, -17.6, x - 4.4, -22, '#c9a678', .8); s.line(x - 4.9, -20, x - 3, -21.2, '#c9a678', .7); s.line(x - 6.8, -17.6, x - 8.2, -21.4, '#c9a678', .8);
      s.ellipse(x + 5.8, -12, 1.4, 1.2, '#f3ead2');
    };
    deer(-22); deer(-6);
    s.line(-16, -11, 8, -8, '#7a5a3c', .6);
    s.poly([[8, -12], [22, -12], [24, -4], [8, -4]].map(([x, y]) => ({x, y})), '#c9302a');
    s.line(6, -2, 25, -2, '#e7c56c', 1); s.line(6, -2, 5, -5, '#e7c56c', 1);
    s.poly([[11, -17], [16, -17], [16, -12], [11, -12]].map(([x, y]) => ({x, y})), '#3f7a54'); s.line(13.5, -17, 13.5, -12, '#e7c56c', .7);
    s.poly([[16.5, -15], [20.5, -15], [20.5, -12], [16.5, -12]].map(([x, y]) => ({x, y})), '#2f6fb3');
  };
  return fx;
}

function flakeFx(s, x, y, r, col) {
  for (let k = 0; k < 3; k++) {
    const a = k * Math.PI / 3 + Math.PI / 6;
    s.line(x - r * Math.cos(a), y - r * Math.sin(a), x + r * Math.cos(a), y + r * Math.sin(a), col, .55);
  }
}

// ---------- the scene ------------------------------------------------------------------------------------------------
const PALETTE = {
  day: {sky: ['#a9c8e3', '#cfe0ec', '#ecf1ef'], hill: '#dfe8f0', hillShade: '#ccd8e4', snow: '#f4f7fa', snowShade: '#d5dfea',
    plaza: '#e6edf3', tread: '#d9e2ec', houses: ['#c9bfdc', '#b3c8de', '#e3d6bb', '#d6b9a8'], roofs: ['#7d72a3', '#5b78a2', '#a8694f', '#8a5a6a'],
    win: '#f2e6c4', winFrame: '#8d7d6a', door: '#8a6a4e', tree: '#3f7a54', treeShade: '#336a48', trunk: '#7a5a3c', pole: '#4f5a55',
    lamp: '#f2e6c4', glow: '#00000000', starfield: 0, flake: '#ffffff', moon: '#f9e7a8', fence: '#a6845e'},
  night: {sky: ['#0f1938', '#1d2c56', '#3a4d78'], hill: '#5d6f92', hillShade: '#4e5f82', snow: '#b6c4db', snowShade: '#8e9db9',
    plaza: '#a8b7cf', tread: '#9aaac4', houses: ['#5f5a7c', '#52667f', '#7a705e', '#71606a'], roofs: ['#3e3a5a', '#33435e', '#5a3b30', '#4a3442'],
    win: '#ffd877', winFrame: '#4a4036', door: '#4a3a2c', tree: '#2a5a3e', treeShade: '#214a33', trunk: '#4e3a28', pole: '#2e3533',
    lamp: '#ffd877', glow: '#ffd87726', starfield: 1, flake: '#e9eef8', moon: '#f4ecc8', fence: '#6a5540'},
};

export function battleScene(night = false) {
  const theme = night ? 'night' : 'day', p = PALETTE[theme];
  const c = new SvgCtx('sb'), s = makeS(c);
  const poly = (pts, col) => s.poly(pts.map(([x, y]) => ({x, y})), col);
  const rect = (x, y, w, h, col) => poly([[x, y], [x + w, y], [x + w, y + h], [x, y + h]], col);
  const raw = svg => c.out.push(svg);
  const group = (id, fn) => { raw(`<g id="sb-${id}">`); fn(); raw('</g>'); };
  const def = (id, fn) => { const saved = c.out; c.out = []; fn(); const inner = c.out.join(''); c.out = saved; c.defs.push({id, svg: () => `<g id="${id}">${inner}</g>`}); };

  // fighters and effects into <defs>
  const snow = {lit: p.snow, shade: p.snowShade};
  for (const who of Object.keys(DRAW)) {
    for (const pose of POSES) def(`sb-${who}-${pose}`, () => drawPose(c, s, who, pose, snow));
  }
  def('sb-santa-hide', () => santa(s, 'hide'));
  const fx = effects(s, {deer: night ? '#8a6a4e' : '#9a7652'});
  for (const [name, draw] of Object.entries(fx)) def(`sb-fx-${name}`, draw);
  c.defs.push({id: 'sb-skyg', svg: () => `<linearGradient id="sb-skyg" gradientUnits="userSpaceOnUse" x1="0" y1="0" x2="0" y2="360">` +
    p.sky.map((col, i) => `<stop offset="${[0, .55, 1][i]}" stop-color="${col}"/>`).join('') + '</linearGradient>'});

  group('sky', () => {
    raw('<rect x="0" y="0" width="1000" height="600" fill="url(#sb-skyg)"/>');
    if (p.starfield) {
      let r = 7;
      const rnd = () => ((r = (r * 1664525 + 1013904223) >>> 0) / 4294967296);
      for (let k = 0; k < 46; k++) s.ellipse(rnd() * 1000, rnd() * 230, .9 + rnd() * 1.2, .9 + rnd() * 1.2, '#f4efd2');
      s.ellipse(860, 70, 26, 26, p.moon); s.ellipse(870, 64, 22, 22, p.sky[0]);
    } else { s.ellipse(150, 70, 30, 30, '#fbf2cf'); s.ellipse(150, 70, 22, 22, '#fff8e0'); }
  });
  group('back', () => {
    // snowy hills
    s.ellipse(180, 330, 300, 70, p.hillShade); s.ellipse(820, 336, 320, 76, p.hill); s.ellipse(520, 342, 260, 52, p.hill);
    // a row of houses with snow on the roofs (the village, lit at night)
    const house = (x, w, h, i) => {
      const base = 346;
      rect(x, base - h, w, h, p.houses[i]);
      poly([[x - 10, base - h + 2], [x + w / 2, base - h - w * .42], [x + w + 10, base - h + 2]], p.roofs[i]);
      poly([[x - 6, base - h - 6], [x + w / 2, base - h - w * .42 - 2], [x + w + 6, base - h - 6], [x + w / 2, base - h - w * .42 + 9]], p.snow);
      rect(x + w * .66, base - h - w * .42 + 6, 10, 26, p.roofs[i]); rect(x + w * .66 - 2, base - h - w * .42 + 2, 14, 6, p.snow);
      for (const wx of [x + w * .18, x + w * .58]) { rect(wx - 2, base - h * .72 - 2, 20, 24, p.winFrame); rect(wx, base - h * .72, 16, 20, p.win); }
      rect(x + w * .4, base - 26, 14, 26, p.door);
      if (night) for (const wx of [x + w * .18, x + w * .58]) s.ellipse(wx + 8, base - h * .72 + 10, 18, 16, p.glow);
    };
    house(28, 110, 78, 0); house(178, 96, 66, 1); house(708, 104, 72, 2); house(858, 116, 82, 3);
    // fence between the houses and the square
    for (let x = 6; x < 1000; x += 26) { rect(x, 318, 6, 30, p.fence); poly([[x, 318], [x + 3, 313], [x + 6, 318]], p.fence); }
    rect(0, 326, 1000, 4, p.fence); rect(0, 338, 1000, 4, p.fence);
    // the New Year tree in the middle of the square: snowy tiers, garland, balls, a star
    const tx = 500, base = 352;
    rect(tx - 12, base - 26, 24, 26, p.trunk);
    // tiers from the bottom up: [apex y, bottom y, half width]
    for (const [k, [apex, yb, half]] of [[196, 330, 148], [150, 274, 120], [110, 216, 92], [74, 156, 62]].entries()) {
      poly([[tx, apex], [tx + half, yb], [tx - half, yb]], k % 2 ? p.treeShade : p.tree);
      poly([[tx - half, yb], [tx - half * .55, yb - 10], [tx - half * .2, yb - 4], [tx + half * .2, yb - 9], [tx + half * .6, yb - 4], [tx + half, yb], [tx + half * .5, yb + 3], [tx - half * .5, yb + 3]], p.snow);
    }
    const balls = ['#d9473f', '#e7c56c', '#3f73c4', '#f6f7fa'];
    let n = 0;
    for (const [y0, w0] of [[140, 46], [196, 74], [252, 100], [308, 128]]) {
      for (let k = -2; k <= 2; k++) {
        const x = tx + k * w0 / 2.6, y = y0 + Math.abs(k) * -4 + 8;
        if (night) s.ellipse(x, y, 9, 9, '#ffe08a40');
        s.ellipse(x, y, 5.4, 5.4, balls[n++ % 4]); s.ellipse(x - 1.6, y - 1.6, 1.4, 1.4, '#ffffff');
      }
      for (let k = -4; k < 4; k++) {
        const x0 = tx + k * w0 / 5.2, x1 = tx + (k + 1) * w0 / 5.2;
        s.line(x0, y0 - 8 + Math.abs(k) * 1.6, x1, y0 - 8 + Math.abs(k + 1) * 1.6, night ? '#ffe08a' : '#e7c56c', 1.6);
      }
    }
    const sy = 70;
    if (night) s.ellipse(tx, sy, 30, 30, '#ffe08a55');
    star(s, tx, sy, 17, '#c99a2e'); star(s, tx, sy, 13.5, '#f2c94c');
    // lanterns at the ends of the square
    for (const lx of [74, 926]) {
      s.line(lx, 420, lx, 300, p.pole, 5); rect(lx - 10, 284, 20, 22, p.pole); rect(lx - 7, 287, 14, 16, p.lamp);
      poly([[lx - 13, 285], [lx, 272], [lx + 13, 285]], p.pole); poly([[lx - 11, 280], [lx, 270], [lx + 11, 280]], p.snow);
      if (night) s.ellipse(lx, 296, 46, 40, p.glow);
    }
  });
  group('ground', () => {
    rect(0, 346, 1000, 254, p.plaza);
    for (const [x, w] of [[60, 140], [300, 120], [560, 160], [860, 150]]) s.ellipse(x, 350, w, 14, p.snow);
    s.ellipse(500, 512, 440, 76, p.tread);
    s.ellipse(500, 512, 380, 58, p.plaza);
    s.ellipse(500, 512, 300, 40, p.tread);
    // footprints across the square
    for (let k = 0; k < 9; k++) { const x = 420 + k * 22, y = 470 + (k % 2) * 8; s.ellipse(x, y, 4, 2.2, p.snowShade); }
  });
  group('front', () => {
    s.ellipse(40, 606, 150, 40, p.snowShade); s.ellipse(30, 604, 136, 34, p.snow);
    s.ellipse(970, 606, 160, 44, p.snowShade); s.ellipse(978, 604, 146, 38, p.snow);
    // falling snow
    let r = 11;
    const rnd = () => ((r = (r * 1103515245 + 12345) >>> 0) / 4294967296);
    for (let k = 0; k < 70; k++) s.ellipse(rnd() * 1000, rnd() * 600, 1.4 + rnd() * 1.6, 1.4 + rnd() * 1.6, p.flake);
  });
  group('stage', () => {});           // the game puts the fighters and effects here
  const anchors = JSON.stringify(ANCHORS);
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 600" role="img" aria-label="Битва с Сантой: площадь у новогодней ёлки" data-theme="${theme}" data-scale="${SCALE}" data-anchors='${anchors}'><title>Битва с Сантой · площадь у ёлки</title>${c.svg()}</svg>`;
}

export function render({night = false} = {}) { return {svg: battleScene(night), poses: POSES, fighters: Object.keys(DRAW), anchors: ANCHORS, scale: SCALE}; }
