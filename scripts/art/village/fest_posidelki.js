// «Посиделки» (20–30.11, FARM_FESTIVALS_DESIGN.md §9, №11): the village's festival layer, vector only.
// Drawn with the farm's own primitives (scene_buildings.js via B, FarmScene methods via s) into the SVG recorder,
// anchored to what the scene exported: chimney tops, windows, fences, bridge rails, benches, plaza lamps, residents' doors,
// the town hall. Three groups the game shows by CSS (style.css, html[data-festival=posidelki][data-festival-decor=on]):
//   vf-decor  — plaids, yarn baskets, the samovar, knitted-flag garlands, chimney smoke (under the night tint);
//   vf-day    — warm light in the windows by day («свет в окнах раньше вечера»);
//   vf-night  — windows, samovar and garland glow above the night tint.
import {festKit} from './fest_kit.js';

// farm palette: muted reds, sage, mustard and cream of the farm's roofs, awnings and fabrics
const PLAIDS = [['#c97a6a', '#efe0c4', '#9b5a4c'], ['#8fae86', '#f1e6cc', '#6f8f68'], ['#d9b25e', '#f4e8c8', '#b08a3c']];
const FLAGS = ['#c97a6a', '#d9b25e', '#8fae86', '#c3b0de', '#e7a8b5', '#7fa3c4'];
const YARN = ['#c97a6a', '#e7a8b5', '#8fae86', '#d9b25e', '#7fa3c4', '#c3b0de'];

export function posidelki(V) {
  // V: {B, P(x,y,z), matrix:[a,b,c,d,e,f] farm px -> world units, windows:[[kind,px,py,w,h]], chimneys:[[px,py]],
  //     fences:[[x1,y1,x2,y2]], bridges:[[x0,y0,x1,y1]], benches:[[x,y,axis]], lamps:[[x,y]], spots:{name:[x,y]}, free(x,y)}
  const K = festKit(V, 'posidelki'), {B, c, s, pt, quad, hidden, visible, problems, plaid} = K;

  // ---------- decor: under the night tint ----------
  c.group('vf-decor');
  // two plaids on fences by the houses, one on the bridge rail, two on plaza benches
  // the two garden fences nearest the plaza (by the residents' houses, not the field fences), straight along x, in view
  const fences = K.gardenFences(2);
  if (fences.length < 2) problems.push('posidelki: fewer than two fences for plaids');
  fences.forEach((f, k) => { const a = Math.min(f[0], f[2]), L = Math.abs(f[2] - f[0]), w = Math.min(.85, L * .45);
    plaid(a + (L - w) / 2, f[1], a + (L + w) / 2, f[1], 11, 9 - k, PLAIDS[k]) });
  const br = V.bridges[0];
  if (br && visible(br[0] + 2, br[3] - .05, 16, 'bridge plaid')) plaid(br[0] + 1.6, br[3] - .05, br[0] + 2.4, br[3] - .05, 21, 9, PLAIDS[2]); else problems.push('posidelki: no bridge');
  for (const [k, b] of V.benches.slice(0, 2).entries()) K.benchPlaid(b, PLAIDS[(k + 1) % 3]);
  // yarn baskets with knitting by three residents' doors
  const basket = (x, y, k) => {
    if (!V.free(x, y)) problems.push(`posidelki: basket on an object at ${x},${y}`);
    visible(x, y, 6, 'basket');
    B.cyl(s, x, y, .2, 0, 7, '#b48f66', '#8a6c4c');
    for (let z = 2; z < 7; z += 2.5) B.L(s, x - .14, y + .14, z, x + .14, y + .14, z, '#9c7a54', .8);
    const balls = [[-.07, -.04], [.08, .02], [0, .1]];
    balls.forEach(([dx, dy], i) => { const p = pt(x + dx, y + dy, 9); s.ellipse(p.x, p.y, 3.4, 3.2, YARN[(k * 2 + i) % YARN.length]); s.line(p.x - 2, p.y - 1, p.x + 1.6, p.y + 1, '#ffffff55', .7) });
    const a = pt(x + .05, y, 10), b = pt(x + .2, y - .1, 22); s.line(a.x, a.y, b.x, b.y, '#a8826a', 1.1); s.line(a.x + 2, a.y, b.x + 3, b.y + 1, '#a8826a', 1.1);
    s.ellipse(b.x, b.y, 1, 1, '#d9b25e'); s.ellipse(b.x + 3, b.y + 1, 1, 1, '#d9b25e');
  };
  // beside the door, on the first free and visible side
  const sides = [[.55, .35], [.6, -.3], [.45, .55], [-.5, .35], [-.2, -.7], [.6, 0]];
  // Соня (the host of the week) first, then the first two more doors where a basket is seen
  let placed = 0;
  for (const who of ['Кошка Соня', 'Агата', 'Филиныч', 'Почтальон Ёж', 'Кошка Кая', 'Механик Крот']) {
    const sp = V.spots[who]; if (!sp || placed >= 3) continue;
    const at = sides.map(([dx, dy]) => [sp[0] + dx, sp[1] + dy]).find(([x, y]) => V.free(x, y) && !hidden(x, y, 6));
    if (at) basket(...at, placed++); else if (who === 'Кошка Соня') problems.push(`posidelki: no visible place for Sonya's basket`);
  }
  if (placed < 3) problems.push('posidelki: fewer than three yarn baskets');
  // the samovar on a small table in front of the town hall tower, with cups and a plate of bubliki
  const [tx, ty] = V.samovar;
  if (!V.free(tx, ty)) problems.push('posidelki: samovar table on an object');
  visible(tx, ty, 20, 'samovar');
  B.shadowAt(s, tx - .32, ty - .22, tx + .32, ty + .22, 26, 10);
  for (const [dx, dy] of [[-.26, -.16], [.26, -.16], [-.26, .16], [.26, .16]]) B.L(s, tx + dx, ty + dy, 0, tx + dx, ty + dy, 9, '#8a6c4c', 1.6);
  B.fullBox(s, '#b48f66', tx - .32, ty - .22, tx + .32, ty + .22, 9, 11, '#e8d9b8');
  B.Q(s, '#d97c6a', [tx - .32, ty + .22, 11, tx + .32, ty + .22, 11, tx + .32, ty + .22, 7, tx - .32, ty + .22, 7]);   // tablecloth edge
  B.cyl(s, tx - .06, ty - .04, .16, 11, 13, '#a8714a');
  B.cyl(s, tx - .06, ty - .04, .14, 13, 25, '#d9a650', '#e8bf6a');                        // brass body
  B.L(s, tx + .08, ty + .1, 17, tx + .16, ty + .17, 16, '#8a5a3a', 1.6);                   // tap
  B.cyl(s, tx - .06, ty - .04, .05, 25, 32, '#a8714a', '#6f5640');                          // chimney pipe
  B.cyl(s, tx - .06, ty - .04, .09, 25, 30, '#f1e6cc', '#e7a8b5');                          // teapot on top
  for (const [dx, dy] of [[.18, -.12], [.2, .08]]) B.cyl(s, tx + dx, ty + dy, .045, 11, 14, '#f4ede0', '#c98a5a');
  const plate = pt(tx - .2, ty + .1, 11.4); s.ellipse(plate.x, plate.y, 6, 2.6, '#f4ede0');
  for (const [dx, dy] of [[-2, -1], [2, -.5], [0, -2.4]]) { s.ellipse(plate.x + dx, plate.y + dy, 2.4, 1.4, '#c98a4a'); s.ellipse(plate.x + dx, plate.y + dy, 1, .6, '#f4ede0') }
  // knitted-flag garlands between the plaza's front lamps (front edges only: nothing stands in front of them)
  const knitted = k => (p, q, i) => {
    s.poly([p, q, {x: (p.x + q.x) / 2, y: (p.y + q.y) / 2 + 10}], FLAGS[(i + k * 2) % FLAGS.length]);
    s.line(p.x + 1, p.y + 2.5, q.x - 1, q.y + 2.5, '#ffffff4d', .8); s.line(p.x + 2.4, p.y + 5.3, q.x - 2.4, q.y + 5.3, '#ffffff4d', .8);   // knit rows
  };
  K.lampPairs(2).forEach(([a, b], k) => K.garland(a, b, knitted(k)));
  K.smoke();
  c.end();

  // ---------- windows: warm by day, lit at night ----------
  c.group('vf-day');
  K.windowsDay();
  c.end();
  c.group('vf-night');
  K.windowsNight();
  const sv = pt(tx - .06, ty - .04, 20); s.ellipse(sv.x, sv.y, 22, 14, 'rgba(255,200,95,.22)'); s.ellipse(sv.x, sv.y, 9, 7, 'rgba(255,220,140,.35)');
  c.end();

  const svg = K.wrap();
  return {svg, problems};
}
