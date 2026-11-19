// Festival characters (FARM_FESTIVALS_DESIGN.md §9.2): figures the calendar needs and the game has no art for yet.
//   Посиделки (20–30.11): «Соня дремлет на крыльце в шарфе» (§9.2 №11) and the mascot «Снеговик в шарфе» (fest_posid_snowman);
//   Новый год (20.12–14.01, Рождество 7.01 inside it): the mascot «Снегирь» (fest_ny_bullfinch, «ходит за игроком по деревне»)
//   and «Ёж разносит новогодние открытки» (§9.2 №1).
// Drawn like the approved E28 residents: FarmScene's own ellipse / line / poly recorded as SVG (svg_ctx.js), feet at (0,0),
// residents' scale (a resident is ~32 units tall, shown at 40×60 CSS px). Mascots follow the player like player.js: frames
// are <g class="…-stand|…-hop"> in one SVG, facing right; the game mirrors them for walking left.
// Palette: the farm's fabrics (rose #c9747c, cream #f3e3d3, sage #8fae6f, mustard #e7c56c) and the residents' fur colours.
// Values are kept apart on purpose (dark cap and eyes, saturated breast and scarf on light snow) so the figures read for a
// player with weak eyesight at game scale.
import {FarmScene} from '/static/scene.js';
import {SvgCtx} from './svg_ctx.js';
import {hedgehog} from './host-residents.js';

const SH = '#41623530';
const P = (s, pts, fill) => s.poly(pts.map(([x, y]) => ({x, y})), fill);

// ---------- «Снеговик в шарфе» — Посиделки mascot -------------------------------------------------------------------
const SNOW = {lit: '#fbfcfe', shade: '#d3dce8', coal: '#2f3338', carrot: '#e98a3a', twig: '#8a6a4a',
  scarf: '#c9747c', stripe: '#f3e3d3', hat: '#8fae6f', band: '#e7c56c', pom: '#f3e3d3'};

function ball(s, x, y, rx, ry) {          // a snowball: shaded body, lit upper left (light comes from the farm's upper left)
  s.ellipse(x, y, rx, ry, SNOW.shade);
  s.ellipse(x - rx * .16, y - ry * .14, rx * .86, ry * .84, SNOW.lit);
}

function snowman(s, hop = 0) {
  const y = -hop;
  s.ellipse(1, .6, hop ? 7.4 : 8.8, hop ? 2.1 : 2.6, SH);
  ball(s, 0, y - 7.2, 8.4, 7.2);
  // twig arms behind the middle ball
  s.line(-5, y - 18.6, -11, y - 23.4, SNOW.twig, 1.3); s.line(-9, y - 21.8, -10.6, y - 25.6, SNOW.twig, 1);
  s.line(5, y - 18.4, 10.8, hop ? y - 23.6 : y - 14.4, SNOW.twig, 1.3);
  s.line(9, hop ? y - 22 : y - 15.6, 11.4, hop ? y - 21.2 : y - 17.6, SNOW.twig, 1);
  ball(s, 0, y - 17.8, 6.4, 5.6);
  s.ellipse(0, y - 19.4, .85, .85, SNOW.coal); s.ellipse(0, y - 16.2, .85, .85, SNOW.coal);
  ball(s, 0, y - 26.8, 5.1, 4.8);
  // face: coal eyes with a glint, carrot nose pointing right, a smile of coal dots
  s.ellipse(-1.7, y - 28, .8, .9, SNOW.coal); s.ellipse(1.9, y - 28, .8, .9, SNOW.coal);
  s.ellipse(-1.5, y - 28.3, .25, .25, '#fff'); s.ellipse(2.1, y - 28.3, .25, .25, '#fff');
  P(s, [[.4, y - 26.9], [6.4, y - 25.9], [.4, y - 25.3]], SNOW.carrot);
  for (const [dx, dy] of [[-2.2, -24.4], [-1, -23.8], [.3, -23.6], [1.6, -23.9]]) s.ellipse(dx, y + dy, .42, .42, SNOW.coal);
  // knitted scarf round the neck, one tail hanging over the middle ball, stripes and a fringe
  P(s, [[-5.3, y - 23.1], [5.3, y - 23.1], [5.9, y - 20.6], [-5.9, y - 20.6]], SNOW.scarf);
  s.line(-4.8, y - 21.9, 4.8, y - 21.9, SNOW.stripe, .8);
  P(s, [[1.6, y - 21.4], [4.5, y - 21.4], [hop ? 6.4 : 5.4, y - 13.4], [hop ? 3.4 : 2.5, y - 13.6]], SNOW.scarf);
  s.line(hop ? 2.4 : 2.0, y - 18.6, hop ? 4.9 : 4.9, y - 18.5, SNOW.stripe, .9);
  s.line(hop ? 2.9 : 2.3, y - 16.2, hop ? 5.6 : 5.2, y - 16.1, SNOW.stripe, .9);
  for (let k = 0; k < 4; k++) s.line((hop ? 3.6 : 2.7) + k * .8, y - 13.5, (hop ? 3.7 : 2.8) + k * .8, y - 12.1, SNOW.scarf, .55);
  // knitted hat with a pompom (Посиделки: «неделя тёплых носков»)
  s.ellipse(0, y - 31.6, 4.4, 3.2, SNOW.hat);
  s.line(-2.4, y - 33.4, -2.4, y - 30.6, '#7c9a5d', .6); s.line(0, y - 34.4, 0, y - 30.6, '#7c9a5d', .6); s.line(2.4, y - 33.4, 2.4, y - 30.6, '#7c9a5d', .6);
  P(s, [[-5, y - 31], [5, y - 31], [5.2, y - 29.2], [-5.2, y - 29.2]], SNOW.band);
  s.ellipse(0, y - 35.2, 1.9, 1.9, SNOW.pom);
}

// ---------- «Снегирь» — Новый год mascot ----------------------------------------------------------------------------
const FINCH = {back: '#7d8796', wing: '#2f3338', bar: '#f3efe8', breast: '#e0524a', belly: '#f3efe8', cap: '#262a2f',
  leg: '#5a4a42', beak: '#262a2f'};

function bullfinch(s, hop = 0) {
  // a round, chubby finch: the head barely parts from the body; black cap and wings, grey back, red cheek and breast
  const y = -hop;
  s.ellipse(.5, .5, hop ? 4.6 : 5.6, hop ? 1.4 : 1.7, SH);
  if (hop) { s.line(-.8, y - 2.6, -1.6, y - 1, FINCH.leg, .9); s.line(1.2, y - 2.6, .9, y - .8, FINCH.leg, .9); }
  else { s.line(-.8, y - 2.6, -1.1, 0, FINCH.leg, .9); s.line(1.2, y - 2.6, 1.4, 0, FINCH.leg, .9);
    s.line(-2.1, 0, -.1, 0, FINCH.leg, .7); s.line(.5, 0, 2.5, 0, FINCH.leg, .7); }
  P(s, [[-5.4, y - 6.6], [-10.6, y - (hop ? 9.4 : 8.2)], [-10.2, y - (hop ? 6.6 : 5.4)], [-5, y - 4.4]], FINCH.wing);   // tail
  s.ellipse(-4.4, y - 5.2, 2.2, 1.6, FINCH.belly);                                                                       // white rump
  s.ellipse(-.6, y - 7.4, 6, 5.4, FINCH.back);                                                                           // grey back
  s.ellipse(1.6, y - 6.2, 5, 4.6, FINCH.breast);                                                                         // red breast
  s.ellipse(.2, y - 3.2, 3.4, 1.6, FINCH.belly);
  // wing: one black oval along the back with the white bar; lifted and opened in the hop
  if (hop) { s.ellipse(-2.8, y - 10.6, 4.6, 2.2, FINCH.wing); s.line(-6, y - 10.4, .4, y - 11.6, FINCH.bar, 1); }
  else { s.ellipse(-2.2, y - 7.6, 4.6, 2.6, FINCH.wing); s.line(-5.6, y - 8.2, .8, y - 8.6, FINCH.bar, 1.1); }
  // head: red cheek, black cap down to the beak, short thick beak, a small eye with a light ring and glint
  s.ellipse(3.6, y - 10.8, 3.8, 3.5, FINCH.breast);
  s.ellipse(3.2, y - 12.4, 3.9, 2.4, FINCH.cap);
  s.ellipse(6.2, y - 11, 1.6, 1.5, FINCH.cap);
  P(s, [[7.2, y - 11.9], [9.4, y - 11], [7.2, y - 10.1]], FINCH.beak);
  s.ellipse(5, y - 11.8, .85, .85, '#5c636c'); s.ellipse(5, y - 11.8, .6, .6, '#141618'); s.ellipse(5.2, y - 12, .2, .2, '#fff');
}

// ---------- «Соня дремлет на крыльце в шарфе» — Посиделки ------------------------------------------------------------
const SONYA = {fur: '#a9afbb', furShade: '#8e95a3', light: '#f4f4f4', pink: '#e0c4c9', dress: '#8a94b5',
  scarf: '#c9747c', stripe: '#f3e3d3', wood: '#b18c60', woodDark: '#8d6a44', eye: '#3b3a36', z: '#5f7fa6'};

function sonyaDozing(s) {
  // a low porch bench, front view like the residents
  s.ellipse(1, .6, 12.5, 2.6, SH);
  s.line(-9.6, -6, -9.6, 0, SONYA.woodDark, 1.6); s.line(9.6, -6, 9.6, 0, SONYA.woodDark, 1.6);
  P(s, [[-11.4, -7.6], [11.4, -7.6], [11.4, -5.4], [-11.4, -5.4]], SONYA.wood);
  s.line(-11.2, -7.5, 11.2, -7.5, '#c9a578', .7);
  // tail curling down the bench
  s.line(-5.2, -8.6, -10.4, -10.4, SONYA.fur, 2.5); s.line(-10.4, -10.4, -11.2, -14.6, SONYA.fur, 2.5);
  // legs over the edge, feet dangling
  s.line(-2.6, -8, -2.8, -2.4, SONYA.fur, 2.6); s.line(2.6, -8, 2.9, -2.4, SONYA.fur, 2.6);
  s.ellipse(-2.9, -1.6, 2.7, 1.6, SONYA.furShade); s.ellipse(3.1, -1.6, 2.7, 1.6, SONYA.furShade);
  // body seated: dress, arms round the knitting, then the long scarf wound round and falling over the arm to the bench
  s.ellipse(0, -13.4, 6.6, 7.4, SONYA.fur);
  P(s, [[-5.6, -17], [5.6, -17], [6.6, -7.6], [-6.6, -7.6]], SONYA.dress);
  s.ellipse(2.2, -9.6, 3.1, 2.7, SONYA.pink);                                                // yarn ball on the lap
  s.line(.4, -10.6, 4, -8.4, '#a85d6c', .6); s.line(.8, -11.6, 4.8, -9.6, '#a85d6c', .6);
  s.line(3.4, -11.4, 6.8, -15.4, '#d7c9a6', .9); s.line(4.4, -11, 8.2, -13.6, '#d7c9a6', .9);  // two needles stuck in it
  s.ellipse(6.9, -15.5, .6, .6, '#e7c56c'); s.ellipse(8.3, -13.7, .6, .6, '#e7c56c');
  s.line(-4.6, -16.2, -1.4, -10.6, SONYA.fur, 2.3); s.line(4.6, -16.2, 4.4, -11.2, SONYA.fur, 2.3);
  s.ellipse(-1, -10.2, 1.4, 1.1, SONYA.fur); s.ellipse(4.4, -10.6, 1.4, 1.1, SONYA.fur);
  P(s, [[-6, -20.4], [6, -20.4], [6.8, -16.8], [0, -14.8], [-6.8, -16.8]], SONYA.scarf);
  s.line(-5, -18.4, 5, -18.4, SONYA.stripe, .9);
  P(s, [[-6.2, -17.6], [-3.4, -17.6], [-4.4, -5.8], [-7.4, -6]], SONYA.scarf);
  s.line(-6.4, -13.4, -3.8, -13.3, SONYA.stripe, 1); s.line(-6.9, -9.6, -4.1, -9.5, SONYA.stripe, 1);
  for (let k = 0; k < 4; k++) s.line(-7.1 + k * .9, -6, -7.2 + k * .9, -4.5, SONYA.scarf, .55);
  // head tilted onto the scarf: ears, closed eyes as arcs, white muzzle
  const hx = 1.6, hy = -25.4;
  s.ellipse(hx, hy, 6, 5.5, SONYA.fur);
  P(s, [[hx - 5.6, hy - 1.4], [hx - 5.4, hy - 7.6], [hx - 1.6, hy - 3.6]], SONYA.fur);
  P(s, [[hx + 5, hy - 3], [hx + 6.4, hy - 8.6], [hx + 1.8, hy - 4.4]], SONYA.fur);
  P(s, [[hx - 4.8, hy - 2], [hx - 4.7, hy - 6], [hx - 2.6, hy - 3.6]], SONYA.pink);
  P(s, [[hx + 4.5, hy - 3.4], [hx + 5.6, hy - 7.2], [hx + 2.6, hy - 4.4]], SONYA.pink);
  s.ellipse(hx + .2, hy + 2.6, 3.2, 2, SONYA.light);
  s.line(hx - 3.2, hy - .2, hx - 2.1, hy + .5, SONYA.eye, .8); s.line(hx - 2.1, hy + .5, hx - 1, hy - .1, SONYA.eye, .8);
  s.line(hx + 1.3, hy - .3, hx + 2.4, hy + .4, SONYA.eye, .8); s.line(hx + 2.4, hy + .4, hx + 3.5, hy - .2, SONYA.eye, .8);
  s.ellipse(hx + .3, hy + 1.8, .8, .5, '#d98f8a');
  // «z z» drawn as strokes (no font): it reads as sleep at game scale
  const z = (x, y, k) => { s.line(x, y, x + 2.4 * k, y, SONYA.z, 1 * k); s.line(x + 2.4 * k, y, x, y + 2.4 * k, SONYA.z, 1 * k); s.line(x, y + 2.4 * k, x + 2.4 * k, y + 2.4 * k, SONYA.z, 1 * k); };
  z(hx + 6.4, hy - 9.6, 1); z(hx + 10, hy - 14.2, .8);
}

// ---------- «Ёж разносит новогодние открытки» — Новый год -------------------------------------------------------------
// The approved postman (host-residents.js) with a striped scarf, a satchel full of cards and one card held out.
function hedgehogNewYear(s, c) {
  hedgehog(s, c);
  P(s, [[-4.4, -19.4], [5.8, -19.4], [6.4, -16.8], [-4.8, -16.8]], '#c9473f');                  // scarf over the collar
  s.line(-3.6, -18.1, 5.4, -18.1, '#f6efe2', .9);
  P(s, [[3.6, -17.4], [6, -17.4], [6.9, -11.6], [4.4, -11.8]], '#c9473f');
  s.line(4, -15.2, 6.3, -15.1, '#f6efe2', .9); s.line(4.3, -13.1, 6.6, -13, '#f6efe2', .9);
  // two cards standing up out of the satchel (red, green, each with a white snowflake) and one held out
  const card = (pts, col) => {
    P(s, pts, col);
    const cx = pts.reduce((a, p) => a + p[0], 0) / 4, cy = pts.reduce((a, p) => a + p[1], 0) / 4, r = 1.1;
    for (let k = 0; k < 3; k++) { const a = k * Math.PI / 3; s.line(cx - r * Math.cos(a), cy - r * Math.sin(a), cx + r * Math.cos(a), cy + r * Math.sin(a), '#fff', .5); }
  };
  card([[-7, -16.4], [-3.9, -17.2], [-3.4, -12.4], [-6.6, -12.4]], '#3f7a54');
  card([[-4.6, -17.6], [-1.4, -17], [-1.6, -12.4], [-4.6, -12.4]], '#c9473f');
  card([[6, -15], [10.6, -15.6], [10.8, -11.8], [6.2, -11.4]], '#c9473f');
  s.ellipse(7.4, -10.6, 1.6, 1.8, '#e3c9a3');
  // snow on the cap's crown
  s.ellipse(.4, -32, 4.6, 1.3, '#fbfcfe');
}

// ---------- export ---------------------------------------------------------------------------------------------------
function svgOf(prefix, viewBox, cls, frames) {
  const parts = frames.map(([name, draw]) => {
    const c = new SvgCtx(`${prefix}${name}`), s = Object.create(FarmScene.prototype);
    s.c = c; s.time = 0; s.motion = false; s.inStatic = true; s.shadowLevel = 0;
    draw(s, c);
    return frames.length > 1 ? `<g class="${cls}-${name}">${c.svg()}</g>` : c.svg();
  });
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="${viewBox}" class="${cls}" aria-hidden="true" focusable="false">${parts.join('')}</svg>`;
}

export function festCharacterSvgs() {
  return {
    // mascots: two frames (stand, hop), like the player's figure
    'mascot-fest_posid_snowman': svgOf('fcsm', '-14 -40 28 44', 'fc-snowman', [['stand', s => snowman(s, 0)], ['hop', s => snowman(s, 2.4)]]),
    'mascot-fest_ny_bullfinch': svgOf('fcbf', '-12 -18 24 20', 'fc-bullfinch', [['stand', s => bullfinch(s, 0)], ['hop', s => bullfinch(s, 2.2)]]),
    // festive poses of residents: same viewBox as the residents, the bench pose is wider
    'resident-sonya-posidelki': svgOf('fcso', '-18 -50 36 54', 'bc-art', [['', sonyaDozing]]),
    'resident-hedgehog-new_year': svgOf('fche', '-18 -50 36 54', 'bc-art', [['', hedgehogNewYear]]),
  };
}

export function render() { return festCharacterSvgs(); }
