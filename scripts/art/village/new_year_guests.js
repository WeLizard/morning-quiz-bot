// New Year guests for the village (owner's request 2026-11-19): Дед Мороз, Снегурочка, and the comic pair for the
// «Битва с Сантой» mini-game (docs/tasks/FARM_SANTA_BATTLE.md) — Санта and his horned companion Крампус.
// People are drawn like the player (player.js) and Агата (host-residents.js): front view, feet at (0,0), ~1.1 CSS px per
// unit in the village. Values are kept far apart (white trims on saturated coats, dark eyes, bright accents) so the
// figures read for a player with weak eyesight at game scale. Дед Мороз wears the blue-and-silver shuba so he never
// reads as Санта in red at a glance — the two meet in the mini-game.
//
// Every guest takes a pose name; 'stand' is the village figure. The battle poses (scripts/art/village_games/
// santa_battle.js) move the hands, what the hands hold and the face; leaning, the jump and the snowdrift are added there.
const P = (s, pts, fill) => s.poly(pts.map(([x, y]) => ({x, y})), fill);
const SH = '#41623530';
const SKIN = '#f3d3b0', CHEEK = '#ef9f95', EYE = '#2f3338', SNOWWHITE = '#f6f7fa', GOLD = '#e7c56c', MOUTH = '#8a3b34';

export const POSES = ['stand', 'attack', 'hurt', 'win', 'down'];

function flake(s, x, y, r, col, w = .5) {
  for (let k = 0; k < 3; k++) {
    const a = k * Math.PI / 3 + Math.PI / 6;
    s.line(x - r * Math.cos(a), y - r * Math.sin(a), x + r * Math.cos(a), y + r * Math.sin(a), col, w);
  }
}

function arm(s, sx, sy, hx, hy, sleeve, w, hand, hr = 2.1) {
  s.line(sx, sy, hx, hy, sleeve, w);
  s.ellipse(hx, hy, hr, hr * 1.08, hand);
}

// eyes by mood: normal (dark with a glint), fierce (normal + brows down to the nose), happy (^ ^), hurt (> <), dizzy (x x)
export function eyes(s, pts, mood, {r = .7, col = EYE, brow = col, browY = -1.5} = {}) {
  pts.forEach(([x, y], i) => {
    const m = i ? -1 : 1;           // the left eye's inner side is +x
    if (mood === 'happy') { s.line(x - .9, y + .3, x, y - .6, col, .6); s.line(x, y - .6, x + .9, y + .3, col, .6); return; }
    if (mood === 'hurt') { s.line(x - .8 * m, y - .7, x + .6 * m, y, col, .6); s.line(x + .6 * m, y, x - .8 * m, y + .7, col, .6); return; }
    if (mood === 'dizzy') { s.line(x - .7, y - .7, x + .7, y + .7, col, .55); s.line(x - .7, y + .7, x + .7, y - .7, col, .55); return; }
    s.ellipse(x, y, r, r * 1.15, col); s.ellipse(x + .2, y - .25, r * .3, r * .3, '#fff');
    if (mood === 'fierce') s.line(x - 1.1 * m, y + browY - .5, x + 1 * m, y + browY + .3, brow, .7);
  });
}

// ---------- Дед Мороз ------------------------------------------------------------------------------------------------
const DM = {coat: '#3d68b0', coatShade: '#2f5594', trim: SNOWWHITE, staff: '#cfd8e3', crystal: '#a9dcf2', boot: '#b8423a'};
// hands: back, front; staff: lean of the staff in the front hand (radians, + = top forward)
const DM_POSE = {
  stand: {back: [-9.4, -19.6], front: [10, -24.4], staff: 0, mood: 'normal'},
  attack: {back: [-8.6, -25], front: [12.4, -31], staff: .75, mood: 'fierce'},
  hurt: {back: [-10.4, -28], front: [11, -29], staff: -.25, mood: 'hurt'},
  win: {back: [-10, -37], front: [9.6, -41], staff: 0, mood: 'happy'},
  down: {back: [-11, -13], front: [11.6, -13], staff: 1.25, mood: 'dizzy'},
};

export function dedMoroz(s, pose = 'stand') {
  const q = DM_POSE[pose], [fx, fy] = q.front, ux = Math.sin(q.staff), uy = -Math.cos(q.staff);
  s.ellipse(1, .6, 11.5, 3, SH);
  // staff through the front hand (drawn first: the mitten holds it), crystal star on top
  const tx = fx + ux * 20.6, ty = fy + uy * 20.6;
  s.line(fx - ux * 23.4, fy - uy * 23.4, tx, ty, DM.staff, 1.7);
  s.line(fx - ux * 22.4 + .5, fy - uy * 22.4, tx + .5, ty, '#a7b4c4', .5);
  const cx = tx + ux * 2.4, cy = ty + uy * 2.4;
  P(s, [[cx, cy - 3.8], [cx + 2.2, cy], [cx, cy + 3.8], [cx - 2.2, cy]], DM.crystal);
  P(s, [[cx, cy - 3.8], [cx + 2.2, cy], [cx, cy]], '#dff3fb');
  flake(s, cx, cy, 3.4, '#ffffff', .45);
  // valenki under the hem
  s.ellipse(-3.4, -1.1, 3.1, 1.6, DM.boot); s.ellipse(3.6, -1.1, 3.1, 1.6, DM.boot);
  arm(s, -6, -30, ...q.back, DM.coatShade, 3.8, SNOWWHITE);
  // shuba to the floor: shoulders, flared body, white hem and front band, gold sash, silver snowflakes
  s.ellipse(0, -30.6, 7.2, 4.6, DM.coat);
  P(s, [[-6.8, -31.4], [6.8, -31.4], [10.4, -2.2], [-10.4, -2.2]], DM.coat);
  P(s, [[-10.6, -5], [10.6, -5], [10.9, -1.8], [-10.9, -1.8]], DM.trim);
  P(s, [[-1.5, -27], [1.5, -27], [2.1, -2], [-2.1, -2]], DM.trim);
  s.line(-7.4, -19.6, 7.4, -19.6, GOLD, 1.5);
  s.line(3.2, -19.4, 3.8, -14.4, GOLD, .9); s.line(4.4, -19.4, 5.2, -14.8, GOLD, .9);
  for (const [x, y] of [[-6, -13], [5.8, -9.4], [-6.8, -7.6], [6.6, -24.4], [-4.8, -25.2]]) flake(s, x, y, 1.4, '#cfe3f5', .55);
  // beard falls over the shuba down to the sash
  s.ellipse(0, -31, 5.8, 4.8, SNOWWHITE);
  P(s, [[-5.6, -31.6], [5.6, -31.6], [4.2, -24.4], [0, -19.8], [-4.2, -24.4]], SNOWWHITE);
  s.line(-2, -28, -1.4, -23, '#dfe3ea', .5); s.line(1.8, -28, 1.4, -23, '#dfe3ea', .5);
  arm(s, 6.2, -30, fx, fy, DM.coat, 3.8, SNOWWHITE);
  // face, white brows, mustache
  s.ellipse(0, -37, 4.5, 4.3, SKIN);
  s.ellipse(-2.7, -35.6, 1.3, .8, CHEEK); s.ellipse(2.7, -35.6, 1.3, .8, CHEEK);
  eyes(s, [[-1.7, -37.7], [1.8, -37.7]], q.mood);
  if (q.mood === 'fierce') { s.line(-3.2, -39.8, -.7, -38.7, SNOWWHITE, 1.1); s.line(.8, -38.7, 3.3, -39.8, SNOWWHITE, 1.1); }
  else { s.line(-3.2, -39.4, -.7, -39.1, SNOWWHITE, 1.1); s.line(.8, -39.1, 3.3, -39.4, SNOWWHITE, 1.1); }
  s.ellipse(0, -35.8, 1.2, 1, '#e8a08c');
  if (q.mood === 'happy' || q.mood === 'hurt') s.ellipse(0, -33, 1.4, q.mood === 'happy' ? 1 : 1.2, MOUTH);   // open mouth under the mustache
  s.ellipse(-1.8, -34.3, 2.3, 1.1, SNOWWHITE); s.ellipse(1.8, -34.3, 2.3, 1.1, SNOWWHITE);
  // round boyar hat with a fur band
  s.ellipse(0, -42.6, 5.3, 3.8, DM.coat);
  flake(s, 0, -43.2, 1.3, '#cfe3f5', .5);
  s.ellipse(0, -40.4, 6.2, 2.1, DM.trim);
}

// ---------- Снегурочка -----------------------------------------------------------------------------------------------
const SG = {coat: '#5d9fd3', coatShade: '#4a88bd', trim: SNOWWHITE, hair: '#e6c06a', hairShade: '#c99f48', boot: '#7b8ea8',
  crown: '#e8eef6', gem: '#2f6fb3'};
// flake: where the snowflake is relative to the front hand, and its size (null = none)
const SG_POSE = {
  stand: {back: [-7.1, -15.8], front: [7.4, -19], flake: [2.2, -2.6, 2.2], mood: 'normal'},
  attack: {back: [-7.4, -21], front: [10.6, -26.4], flake: [4, -1.6, 3.2], mood: 'fierce'},
  hurt: {back: [-6.6, -28.6], front: [7.2, -28.8], flake: null, mood: 'hurt'},
  win: {back: [-7.8, -33.6], front: [8.2, -34], flake: [.4, -3.4, 2.4], mood: 'happy'},
  down: {back: [-8.6, -12], front: [9, -12], flake: null, mood: 'dizzy'},
};

export function snegurochka(s, pose = 'stand') {
  const q = SG_POSE[pose];
  s.ellipse(1, .6, 9, 2.6, SH);
  s.ellipse(-2.6, -1, 2.4, 1.3, SG.boot); s.ellipse(2.9, -1, 2.4, 1.3, SG.boot);
  s.ellipse(0, -32.6, 5, 4.8, SG.hair);                                                              // hair behind the shoulders
  arm(s, -4.8, -24.8, ...q.back, SG.coatShade, 2.9, SNOWWHITE, 1.7);
  // long coat with white hem and front band, white collar
  s.ellipse(0, -24.6, 5.4, 3.6, SG.coat);
  P(s, [[-5.2, -25.4], [5.2, -25.4], [8.2, -2.2], [-8.2, -2.2]], SG.coat);
  P(s, [[-8.4, -4.6], [8.4, -4.6], [8.7, -1.8], [-8.7, -1.8]], SG.trim);
  P(s, [[-1.2, -23], [1.2, -23], [1.7, -2], [-1.7, -2]], SG.trim);
  for (const [x, y] of [[-4.6, -10], [4.8, -13.4], [-5.4, -18.4], [5.4, -7.4]]) flake(s, x, y, 1.2, '#ffffff', .5);
  s.ellipse(0, -26.8, 4.2, 1.7, SG.trim);
  arm(s, 4.8, -24.8, ...q.front, SG.coat, 2.9, SNOWWHITE, 1.7);
  if (q.flake) flake(s, q.front[0] + q.flake[0], q.front[1] + q.flake[1], q.flake[2], '#2f6fb3', .7);
  // face
  s.ellipse(0, -31.6, 4.1, 4.3, SKIN);
  P(s, [[-4.3, -33.2], [-2.4, -35.6], [2.6, -35.6], [4.3, -33.2], [1, -34.4]], SG.hair);                   // fringe
  s.ellipse(-2.4, -30.3, 1.2, .75, CHEEK); s.ellipse(2.4, -30.3, 1.2, .75, CHEEK);
  eyes(s, [[-1.5, -32], [1.6, -32]], q.mood, {r: .65, brow: SG.hairShade, browY: -1.3});
  if (q.mood === 'happy') s.ellipse(.1, -29, 1.2, .8, '#b8584f');
  else if (q.mood === 'hurt' || q.mood === 'dizzy') s.ellipse(.1, -28.9, .6, .7, '#b8584f');
  else { s.line(-.8, -29.2, .1, -28.8, '#b8584f', .6); s.line(.1, -28.8, 1, -29.2, '#b8584f', .6); }
  // braid over the front shoulder down to the waist, blue ribbon at the tip
  for (let k = 0; k < 6; k++) s.ellipse(4 + k * .25, -28.4 + k * 2.3, 1.5, 1.35, k % 2 ? SG.hairShade : SG.hair);
  s.ellipse(5.6, -14.3, 1.3, .8, SG.gem); s.line(5.3, -14, 4.8, -12, SG.gem, .7); s.line(5.9, -14, 6.6, -12.2, SG.gem, .7);
  // kokoshnik: silver-white crest with a blue gem and white fur edge
  P(s, [[-4.8, -34.6], [-4, -38.8], [-1.8, -41.2], [0, -41.8], [1.8, -41.2], [4, -38.8], [4.8, -34.6]], SG.crown);
  s.ellipse(0, -38.4, 1.1, 1.4, SG.gem); s.ellipse(-2.6, -37.2, .6, .7, SG.gem); s.ellipse(2.6, -37.2, .6, .7, SG.gem);
  s.line(-4.8, -34.8, 4.8, -34.8, '#ffffff', 1.1);
}

// ---------- Санта ----------------------------------------------------------------------------------------------------
const SA = {coat: '#d23a32', coatShade: '#b52f29', trim: SNOWWHITE, belt: '#2b2e33', boot: '#2b2e33', sack: '#a9875b',
  sackShade: '#8d6e45'};
// the back hand keeps the sack's neck; 'hide' = Santa ducked into his sack («В мешок!»)
const SA_POSE = {
  stand: {back: [-8.6, -25.4], front: [10.2, -26.4], mood: 'normal'},
  attack: {back: [-8.6, -25.4], front: [12.6, -21], mood: 'happy', coal: true},
  hurt: {back: [-8.6, -25.4], front: [7.6, -31.6], mood: 'hurt'},
  win: {back: [-8.6, -25.4], front: [9.4, -33], mood: 'happy'},
  down: {back: [-10.4, -11], front: [11.4, -11], mood: 'dizzy'},
};

function santaSack(s, x, y, k = 1) {
  s.ellipse(x, y, 6.2 * k, 7.6 * k, SA.sack); s.ellipse(x - 1.2 * k, y + 2 * k, 3.4 * k, 4.6 * k, SA.sackShade);
  P(s, [[x - 2 * k, y - 8.8 * k], [x + 1.4 * k, y - 9.2 * k], [x + 1.6 * k, y - 5.8 * k], [x - 2.2 * k, y - 5.6 * k]], '#3f7a54');   // a gift peeking out
  s.line(x - .3 * k, y - 9 * k, x - .3 * k, y - 5.7 * k, GOLD, .7);
  s.line(x - 2.6 * k, y - 6.6 * k, x + 2.4 * k, y - 7 * k, SA.sackShade, 1.2);
}

function santaHat(s, y) {
  P(s, [[-4.8, y], [4.8, y], [3.4, y - 5.2], [-.6, y - 7.8], [-5.2, y - 6.2], [-8.4, y - 3.4], [-5.6, y - 3.2]], SA.coat);
  s.ellipse(-8.6, y - 3, 1.9, 1.9, SA.trim);
  s.ellipse(0, y, 5.7, 1.8, SA.trim);
}

export function santa(s, pose = 'stand') {
  if (pose === 'hide') return santaHiding(s);
  const q = SA_POSE[pose];
  s.ellipse(0, .6, 12, 3, SH);
  if (pose === 'down') santaSack(s, -12.4, -6.4, .85);          // dropped beside him
  else santaSack(s, -8.4, -17.6);                               // over the back shoulder
  // legs and boots
  s.line(-3, -8, -3.2, -2.4, SA.coatShade, 3.4); s.line(3, -8, 3.3, -2.4, SA.coatShade, 3.4);
  s.ellipse(-3.6, -1.2, 3.3, 1.6, SA.boot); s.ellipse(3.9, -1.2, 3.3, 1.6, SA.boot);
  // round belly, hem trim, belt with a gold buckle, front trim
  s.ellipse(0, -14.6, 8.6, 8.6, SA.coat);
  s.ellipse(0, -7.2, 7.4, 2, SA.trim);
  P(s, [[-8.4, -15], [8.4, -15], [8.4, -12.4], [-8.4, -12.4]], SA.belt);
  P(s, [[-2, -15.6], [2, -15.6], [2, -11.8], [-2, -11.8]], GOLD);
  P(s, [[-.9, -14.6], [.9, -14.6], [.9, -12.8], [-.9, -12.8]], SA.belt);
  s.line(0, -22.6, 0, -15.6, SA.trim, 1.7); s.line(0, -12, 0, -8.4, SA.trim, 1.7);
  arm(s, -5.6, -20.4, ...q.back, SA.coatShade, 3.4, SA.belt, 1.9);
  // beard, face, mustache
  s.ellipse(0, -23.4, 5.6, 4.6, SNOWWHITE);
  P(s, [[-5.4, -23.6], [5.4, -23.6], [3.2, -18.6], [0, -16.8], [-3.2, -18.6]], SNOWWHITE);
  s.ellipse(0, -28, 4.4, 4.1, SKIN);
  s.ellipse(-2.7, -26.6, 1.3, .8, CHEEK); s.ellipse(2.7, -26.6, 1.3, .8, CHEEK);
  eyes(s, [[-1.6, -28.8], [1.7, -28.8]], q.mood);
  s.line(-3, -30.4, -.8, -30.6, SNOWWHITE, 1); s.line(.8, -30.6, 3, -30.4, SNOWWHITE, 1);
  s.ellipse(0, -27, 1.2, 1, '#e8a08c');
  if (q.mood === 'happy' || q.mood === 'hurt') s.ellipse(0, -24.1, 1.6, q.mood === 'happy' ? 1.3 : 1, MOUTH);   // «хо-хо-хо!»
  s.ellipse(-1.7, -25.4, 2.2, 1.1, SNOWWHITE); s.ellipse(1.7, -25.4, 2.2, 1.1, SNOWWHITE);
  // front arm: waves, throws a lump of coal, holds his hat
  arm(s, 5.8, -20.4, ...q.front, SA.coat, 3.4, SA.belt, 1.9);
  if (q.coal) s.ellipse(q.front[0] + 1.6, q.front[1] - 1.6, 1.8, 1.6, '#3a3d42');
  santaHat(s, -31.2);
}

// «В мешок!»: only the hat, the eyes and the mittens show over the sack's edge
function santaHiding(s) {
  s.ellipse(0, .6, 11, 3, SH);
  s.ellipse(0, -9.6, 10.4, 10, SA.sack); s.ellipse(-2.4, -6.4, 5.6, 6, SA.sackShade);
  s.ellipse(0, -18.4, 8.6, 2.6, SA.sackShade);
  s.ellipse(0, -19.6, 4.6, 3.4, SKIN);
  eyes(s, [[-1.6, -20.2], [1.7, -20.2]], 'normal');
  s.line(-3, -21.8, -.8, -22, SNOWWHITE, 1); s.line(.8, -22, 3, -21.8, SNOWWHITE, 1);
  s.ellipse(-6.2, -18.6, 1.9, 2, SA.belt); s.ellipse(6.4, -18.6, 1.9, 2, SA.belt);
  santaHat(s, -22.4);
  s.line(-9, -12.4, 9, -12.4, '#c9a678', .8);
}

// ---------- Крампус --------------------------------------------------------------------------------------------------
// Santa's horned companion from the Alpine tales, drawn comic, not scary: big round yellow eyes, a long tongue, a birch
// switch tied with a red ribbon, a bell on a chain belt.
const KR = {fur: '#5d4337', furDark: '#433026', belly: '#87644f', horn: '#ddcfae', hornLine: '#b49f74', eye: '#f2c94c',
  tongue: '#e0534a', hoof: '#25272b'};
// sw: direction of the birch rods from the back hand; null = the switch dropped on the snow
const KR_POSE = {
  stand: {back: [-9.6, -14.8], front: [10, -16.6], sw: [-.28, -1], mood: 'normal'},
  attack: {back: [-3, -31], front: [11, -22.6], sw: [.75, -.65], mood: 'fierce'},
  hurt: {back: [-10.2, -24.6], front: [10.6, -24.4], sw: [-.45, -1], mood: 'hurt'},
  win: {back: [-9.4, -31.4], front: [10.2, -31.4], sw: [-.2, -1], mood: 'happy'},
  down: {back: [-10.8, -12], front: [11.2, -12], sw: null, mood: 'dizzy'},
};

function birchSwitch(s, hx, hy, dx, dy) {
  const n = Math.hypot(dx, dy), ux = dx / n, uy = dy / n, px = -uy, py = ux, L = 18.6;
  for (let k = 0; k < 6; k++) {
    const len = L - Math.abs(k - 2.5) * .9, sp = (k - 2.5) * 1.5;
    s.line(hx + px * (k - 2.5) * .16, hy + py * (k - 2.5) * .16, hx + ux * len + px * sp, hy + uy * len + py * sp, k % 2 ? '#7a5a3c' : '#94704b', .7);
  }
  s.line(hx + ux * 14 - px * 2.2, hy + uy * 14 - py * 2.2, hx + ux * 15.2 - px * 3.6, hy + uy * 15.2 - py * 3.6, '#94704b', .5);
  s.ellipse(hx + ux * 2.6, hy + uy * 2.6, 1.2, .8, '#c9473f');
  s.line(hx + ux * 2.4, hy + uy * 2.4, hx + ux * 2.4 - px * 2, hy + uy * 2.4 - py * 2, '#c9473f', .6);
}

export function krampus(s, pose = 'stand') {
  const q = KR_POSE[pose];
  s.ellipse(1, .6, 10, 2.8, SH);
  if (q.sw) birchSwitch(s, ...q.back, ...q.sw);
  else birchSwitch(s, -9, -1.2, -1, -.08);
  // goat legs with hooves
  s.line(-3, -9, -3.6, -2.6, KR.furDark, 3.4); s.line(3, -9, 3.6, -2.6, KR.furDark, 3.4);
  P(s, [[-5.6, -2.8], [-1.6, -2.8], [-1.4, 0], [-5.8, 0]], KR.hoof); P(s, [[1.6, -2.8], [5.6, -2.8], [5.8, 0], [1.4, 0]], KR.hoof);
  s.line(-3.6, -2.6, -3.6, 0, '#4a4d52', .5); s.line(3.6, -2.6, 3.6, 0, '#4a4d52', .5);
  arm(s, -5.4, -20.4, ...q.back, KR.fur, 3.2, KR.furDark, 2);
  // shaggy body, lighter belly, fur fringe at the bottom
  s.ellipse(0, -15.4, 7.2, 8.6, KR.fur);
  s.ellipse(.6, -14.4, 4, 5.4, KR.belly);
  for (let k = 0; k < 6; k++) P(s, [[-6.6 + k * 2.4, -9], [-4.4 + k * 2.4, -9], [-5.6 + k * 2.4, -6.4]], KR.fur);
  // chain belt with a gold bell
  for (let k = 0; k < 7; k++) { const x = -6 + k * 2; s.ellipse(x, -11.4 + Math.abs(x) * .08, .95, .75, '#a3a9b1'); s.ellipse(x, -11.4 + Math.abs(x) * .08, .4, .3, KR.furDark); }
  s.ellipse(2.4, -9, 1.6, 1.7, GOLD); s.ellipse(2.4, -7.6, .5, .5, '#9a7a2a');
  // front arm, claws
  const [fx, fy] = q.front;
  arm(s, 5.4, -20.4, fx, fy, KR.fur, 3.2, KR.furDark, 2);
  s.line(fx + .8, fy + 1.2, fx + 1.6, fy + 2.4, KR.horn, .5); s.line(fx - .4, fy + 1.6, fx, fy + 3, KR.horn, .5);
  // horns: thick goat crescents going out to the sides and curling up, with ridges across
  const horn = (m) => {
    P(s, [[-1.2, -30.6], [-5, -31], [-8.6, -32.8], [-10.8, -36], [-10.6, -40.6], [-9.4, -37.4], [-7.4, -35.4], [-4.4, -34.2], [-.8, -33.6]].map(([x, y]) => [x * m, y]), KR.horn);
    for (const [x1, y1, x2, y2] of [[-3.4, -31, -3.2, -34], [-5.8, -31.6, -5.4, -34.6], [-8, -32.6, -7.4, -35.4], [-9.8, -34.6, -8.8, -36.4]])
      s.line(x1 * m, y1, x2 * m, y2, KR.hornLine, .55);
  };
  horn(1); horn(-1);
  // goat ears
  P(s, [[-4.6, -29.4], [-9.4, -29.6], [-4.4, -27]], KR.fur); P(s, [[4.6, -29.4], [9.4, -29.6], [4.4, -27]], KR.fur);
  P(s, [[-5, -29], [-8.2, -29.3], [-4.8, -27.8]], '#c98d84'); P(s, [[5, -29], [8.2, -29.3], [4.8, -27.8]], '#c98d84');
  // head, tufts, muzzle, big yellow eyes, open mouth with a long tongue
  s.ellipse(0, -27.4, 5.4, 5, KR.fur);
  P(s, [[-3.4, -31.6], [-1.6, -33.8], [-.6, -31.8], [.8, -34], [1.6, -31.8], [3.4, -32.6], [3, -30.6], [-3, -30.6]], KR.furDark);
  s.ellipse(0, -24.6, 3.6, 2.6, KR.belly);
  s.ellipse(-2.1, -28.4, 1.6, 1.7, KR.eye); s.ellipse(2.1, -28.4, 1.6, 1.7, KR.eye);
  if (q.mood === 'normal' || q.mood === 'fierce') {
    s.ellipse(-1.8, -28.2, .7, .9, EYE); s.ellipse(2.4, -28.2, .7, .9, EYE);
    s.ellipse(-1.6, -28.6, .22, .22, '#fff'); s.ellipse(2.6, -28.6, .22, .22, '#fff');
  } else eyes(s, [[-2.1, -28.3], [2.1, -28.3]], q.mood, {col: '#2a1a16'});
  if (q.mood === 'fierce') { s.line(-3.8, -31, -.8, -29.4, KR.furDark, 1.1); s.line(.8, -29.4, 3.8, -31, KR.furDark, 1.1); }
  else { s.line(-3.6, -30.6, -1, -30, KR.furDark, .9); s.line(1, -30, 3.6, -30.6, KR.furDark, .9); }
  s.ellipse(0, -25.8, 1, .7, KR.furDark);
  s.ellipse(.2, -23.6, 2, 1.1, '#2a1a16');
  P(s, [[-1.2, -24.4], [-.7, -24.4], [-.95, -23.4]], '#fff'); P(s, [[.9, -24.4], [1.4, -24.4], [1.15, -23.4]], '#fff');
  P(s, [[-.6, -23.4], [1.4, -23.4], [2.2, -20.4], [1.8, -18], [.6, -17.4], [.8, -19.8], [-.2, -21.6]], KR.tongue);
}
