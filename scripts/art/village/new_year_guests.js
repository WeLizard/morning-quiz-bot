// New Year guests for the village (owner's request 2026-11-19): Дед Мороз, Снегурочка, and the comic pair for the
// «Битва с Сантой» mini-game idea — Санта and his horned companion Крампус.
// People are drawn like the player (player.js) and Агата (host-residents.js): front view, feet at (0,0), ~1.1 CSS px per
// unit in the village. Values are kept far apart (white trims on saturated coats, dark eyes, bright accents) so the
// figures read for a player with weak eyesight at game scale. Дед Мороз wears the blue-and-silver shuba so he never
// reads as Санта in red at a glance — the two meet in the mini-game.
const P = (s, pts, fill) => s.poly(pts.map(([x, y]) => ({x, y})), fill);
const SH = '#41623530';
const SKIN = '#f3d3b0', CHEEK = '#ef9f95', EYE = '#2f3338', SNOWWHITE = '#f6f7fa', GOLD = '#e7c56c';

function flake(s, x, y, r, col, w = .5) {
  for (let k = 0; k < 3; k++) {
    const a = k * Math.PI / 3 + Math.PI / 6;
    s.line(x - r * Math.cos(a), y - r * Math.sin(a), x + r * Math.cos(a), y + r * Math.sin(a), col, w);
  }
}

// ---------- Дед Мороз ------------------------------------------------------------------------------------------------
const DM = {coat: '#3d68b0', coatShade: '#2f5594', trim: SNOWWHITE, staff: '#cfd8e3', crystal: '#a9dcf2', boot: '#b8423a'};

export function dedMoroz(s) {
  s.ellipse(1, .6, 11.5, 3, SH);
  // staff behind the right hand, crystal star on top
  s.line(10, -1, 10, -45, DM.staff, 1.7); s.line(10.5, -2, 10.5, -44, '#a7b4c4', .5);
  P(s, [[10, -51.2], [12.2, -47.4], [10, -43.6], [7.8, -47.4]], DM.crystal);
  P(s, [[10, -51.2], [12.2, -47.4], [10, -47.4]], '#dff3fb');
  flake(s, 10, -47.4, 3.4, '#ffffff', .45);
  // valenki under the hem
  s.ellipse(-3.4, -1.1, 3.1, 1.6, DM.boot); s.ellipse(3.6, -1.1, 3.1, 1.6, DM.boot);
  // back arm
  s.line(-6, -30, -9.2, -20.4, DM.coatShade, 3.8); s.ellipse(-9.4, -19.6, 2.1, 2.3, SNOWWHITE);
  s.ellipse(-8.9, -21.8, 2.3, 1.1, DM.trim);
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
  // front arm holds the staff
  s.line(6.2, -30, 9.6, -25.4, DM.coat, 3.8); s.ellipse(9.2, -26.4, 2.3, 1.1, DM.trim);
  s.ellipse(10, -24.4, 2.1, 2.3, SNOWWHITE);
  // face, white brows, mustache
  s.ellipse(0, -37, 4.5, 4.3, SKIN);
  s.ellipse(-2.7, -35.6, 1.3, .8, CHEEK); s.ellipse(2.7, -35.6, 1.3, .8, CHEEK);
  s.ellipse(-1.7, -37.7, .7, .8, EYE); s.ellipse(1.8, -37.7, .7, .8, EYE);
  s.ellipse(-1.5, -37.9, .22, .22, '#fff'); s.ellipse(2, -37.9, .22, .22, '#fff');
  s.line(-3.2, -39.4, -.7, -39.1, SNOWWHITE, 1.1); s.line(.8, -39.1, 3.3, -39.4, SNOWWHITE, 1.1);
  s.ellipse(0, -35.8, 1.2, 1, '#e8a08c');
  s.ellipse(-1.8, -34.3, 2.3, 1.1, SNOWWHITE); s.ellipse(1.8, -34.3, 2.3, 1.1, SNOWWHITE);
  // round boyar hat with a fur band
  s.ellipse(0, -42.6, 5.3, 3.8, DM.coat);
  flake(s, 0, -43.2, 1.3, '#cfe3f5', .5);
  s.ellipse(0, -40.4, 6.2, 2.1, DM.trim);
}

// ---------- Снегурочка -----------------------------------------------------------------------------------------------
const SG = {coat: '#5d9fd3', coatShade: '#4a88bd', trim: SNOWWHITE, hair: '#e6c06a', hairShade: '#c99f48', boot: '#7b8ea8',
  crown: '#e8eef6', gem: '#2f6fb3'};

export function snegurochka(s) {
  s.ellipse(1, .6, 9, 2.6, SH);
  s.ellipse(-2.6, -1, 2.4, 1.3, SG.boot); s.ellipse(2.9, -1, 2.4, 1.3, SG.boot);
  // hair behind the shoulders
  s.ellipse(0, -32.6, 5, 4.8, SG.hair);
  // back arm
  s.line(-4.8, -24.8, -7, -16.4, SG.coatShade, 2.9); s.ellipse(-7.1, -15.8, 1.7, 1.9, SNOWWHITE);
  // long coat with white hem and front band, white collar
  s.ellipse(0, -24.6, 5.4, 3.6, SG.coat);
  P(s, [[-5.2, -25.4], [5.2, -25.4], [8.2, -2.2], [-8.2, -2.2]], SG.coat);
  P(s, [[-8.4, -4.6], [8.4, -4.6], [8.7, -1.8], [-8.7, -1.8]], SG.trim);
  P(s, [[-1.2, -23], [1.2, -23], [1.7, -2], [-1.7, -2]], SG.trim);
  for (const [x, y] of [[-4.6, -10], [4.8, -13.4], [-5.4, -18.4], [5.4, -7.4]]) flake(s, x, y, 1.2, '#ffffff', .5);
  s.ellipse(0, -26.8, 4.2, 1.7, SG.trim);
  // front arm holds a snowflake up
  s.line(4.8, -24.8, 7.2, -19.6, SG.coat, 2.9); s.ellipse(7.4, -19, 1.7, 1.9, SNOWWHITE);
  flake(s, 9.6, -21.6, 2.2, '#2f6fb3', .7);
  // face
  s.ellipse(0, -31.6, 4.1, 4.3, SKIN);
  P(s, [[-4.3, -33.2], [-2.4, -35.6], [2.6, -35.6], [4.3, -33.2], [1, -34.4]], SG.hair);                   // fringe
  s.ellipse(-2.4, -30.3, 1.2, .75, CHEEK); s.ellipse(2.4, -30.3, 1.2, .75, CHEEK);
  s.ellipse(-1.5, -32, .65, .8, EYE); s.ellipse(1.6, -32, .65, .8, EYE);
  s.ellipse(-1.3, -32.2, .2, .2, '#fff'); s.ellipse(1.8, -32.2, .2, .2, '#fff');
  s.line(-.8, -29.2, .1, -28.8, '#b8584f', .6); s.line(.1, -28.8, 1, -29.2, '#b8584f', .6);
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

export function santa(s) {
  s.ellipse(0, .6, 12, 3, SH);
  // sack over the back shoulder
  s.ellipse(-8.4, -17.6, 6.2, 7.6, SA.sack); s.ellipse(-9.6, -15.6, 3.4, 4.6, SA.sackShade);
  P(s, [[-10.4, -26.4], [-7, -26.8], [-6.8, -23.4], [-10.6, -23.2]], '#3f7a54');                   // a gift peeking out
  s.line(-8.7, -26.6, -8.7, -23.3, GOLD, .7);
  s.line(-11, -24.2, -6, -24.6, SA.sackShade, 1.2);
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
  // back arm holds the sack's neck
  s.line(-5.6, -20.4, -8.4, -24.8, SA.coatShade, 3.4); s.ellipse(-7.8, -23.4, 2.2, 1.1, SA.trim);
  s.ellipse(-8.6, -25.4, 1.9, 2, SA.belt);
  // beard, face, mustache
  s.ellipse(0, -23.4, 5.6, 4.6, SNOWWHITE);
  P(s, [[-5.4, -23.6], [5.4, -23.6], [3.2, -18.6], [0, -16.8], [-3.2, -18.6]], SNOWWHITE);
  s.ellipse(0, -28, 4.4, 4.1, SKIN);
  s.ellipse(-2.7, -26.6, 1.3, .8, CHEEK); s.ellipse(2.7, -26.6, 1.3, .8, CHEEK);
  s.ellipse(-1.6, -28.8, .7, .8, EYE); s.ellipse(1.7, -28.8, .7, .8, EYE);
  s.ellipse(-1.4, -29, .22, .22, '#fff'); s.ellipse(1.9, -29, .22, .22, '#fff');
  s.line(-3, -30.4, -.8, -30.6, SNOWWHITE, 1); s.line(.8, -30.6, 3, -30.4, SNOWWHITE, 1);
  s.ellipse(0, -27, 1.2, 1, '#e8a08c');
  s.ellipse(-1.7, -25.4, 2.2, 1.1, SNOWWHITE); s.ellipse(1.7, -25.4, 2.2, 1.1, SNOWWHITE);
  // front arm waves
  s.line(5.8, -20.4, 9.8, -25.4, SA.coat, 3.4); s.ellipse(9.2, -24.4, 2.2, 1.1, SA.trim);
  s.ellipse(10.2, -26.4, 1.9, 2, SA.belt);
  // floppy hat, tip and pompom over to the left
  P(s, [[-4.8, -31.2], [4.8, -31.2], [3.4, -36.4], [-.6, -39], [-5.2, -37.4], [-8.4, -34.6], [-5.6, -34.4]], SA.coat);
  s.ellipse(-8.6, -34.2, 1.9, 1.9, SA.trim);
  s.ellipse(0, -31.2, 5.7, 1.8, SA.trim);
}

// ---------- Крампус --------------------------------------------------------------------------------------------------
// Santa's horned companion from the Alpine tales, drawn comic, not scary: big round yellow eyes, a long tongue, a birch
// switch tied with a red ribbon, a bell on a chain belt.
const KR = {fur: '#5d4337', furDark: '#433026', belly: '#87644f', horn: '#ddcfae', hornLine: '#b49f74', eye: '#f2c94c',
  tongue: '#e0534a', hoof: '#25272b', twig: '#efe7d4', twigDot: '#3a3a3a'};

export function krampus(s) {
  s.ellipse(1, .6, 10, 2.8, SH);
  // birch switch (a bundle of thin brown rods) held up in the back hand
  for (let k = 0; k < 6; k++) {
    const tx = -15 + k * 1.5, ty = -33.6 + Math.abs(k - 2.5) * .9;
    s.line(-9.4 + k * .16, -15, tx, ty, k % 2 ? '#7a5a3c' : '#94704b', .7);
  }
  s.line(-12, -29.6, -13.2, -31, '#94704b', .5); s.line(-9.6, -30.4, -8.6, -32.2, '#7a5a3c', .5);
  // goat legs with hooves
  s.line(-3, -9, -3.6, -2.6, KR.furDark, 3.4); s.line(3, -9, 3.6, -2.6, KR.furDark, 3.4);
  P(s, [[-5.6, -2.8], [-1.6, -2.8], [-1.4, 0], [-5.8, 0]], KR.hoof); P(s, [[1.6, -2.8], [5.6, -2.8], [5.8, 0], [1.4, 0]], KR.hoof);
  s.line(-3.6, -2.6, -3.6, 0, '#4a4d52', .5); s.line(3.6, -2.6, 3.6, 0, '#4a4d52', .5);
  // back arm
  s.line(-5.4, -20.4, -9.2, -15.4, KR.fur, 3.2); s.ellipse(-9.6, -14.8, 2, 2, KR.furDark);
  s.ellipse(-9.8, -17.6, 1.2, .8, '#c9473f'); s.line(-10.4, -17.4, -11.6, -15.8, '#c9473f', .6);
  // shaggy body, lighter belly, fur fringe at the bottom
  s.ellipse(0, -15.4, 7.2, 8.6, KR.fur);
  s.ellipse(.6, -14.4, 4, 5.4, KR.belly);
  for (let k = 0; k < 6; k++) P(s, [[-6.6 + k * 2.4, -9], [-4.4 + k * 2.4, -9], [-5.6 + k * 2.4, -6.4]], KR.fur);
  // chain belt with a gold bell
  for (let k = 0; k < 7; k++) { const x = -6 + k * 2; s.ellipse(x, -11.4 + Math.abs(x) * .08, .95, .75, '#a3a9b1'); s.ellipse(x, -11.4 + Math.abs(x) * .08, .4, .3, KR.furDark); }
  s.ellipse(2.4, -9, 1.6, 1.7, GOLD); s.ellipse(2.4, -7.6, .5, .5, '#9a7a2a');
  // front arm, claws
  s.line(5.4, -20.4, 9.6, -17, KR.fur, 3.2); s.ellipse(10, -16.6, 2, 2, KR.furDark);
  s.line(10.8, -15.4, 11.6, -14.2, KR.horn, .5); s.line(9.6, -15, 10, -13.6, KR.horn, .5);
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
  s.ellipse(-1.8, -28.2, .7, .9, EYE); s.ellipse(2.4, -28.2, .7, .9, EYE);
  s.ellipse(-1.6, -28.6, .22, .22, '#fff'); s.ellipse(2.6, -28.6, .22, .22, '#fff');
  s.line(-3.6, -30.6, -1, -30, KR.furDark, .9); s.line(1, -30, 3.6, -30.6, KR.furDark, .9);
  s.ellipse(0, -25.8, 1, .7, KR.furDark);
  s.ellipse(.2, -23.6, 2, 1.1, '#2a1a16');
  P(s, [[-1.2, -24.4], [-.7, -24.4], [-.95, -23.4]], '#fff'); P(s, [[.9, -24.4], [1.4, -24.4], [1.15, -23.4]], '#fff');
  P(s, [[-.6, -23.4], [1.4, -23.4], [2.2, -20.4], [1.8, -18], [.6, -17.4], [.8, -19.8], [-.2, -21.6]], KR.tongue);
}
