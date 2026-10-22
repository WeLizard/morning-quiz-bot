// «Посиделки» (20–30.11, FARM_FESTIVALS_DESIGN.md §9, №11): the village's festival layer, vector only.
// Drawn with the farm's own primitives (scene_buildings.js via B, FarmScene methods via s) into the SVG recorder,
// anchored to what the scene exported: chimney tops, windows, fences, bridge rails, benches, plaza lamps, residents' doors,
// the town hall. Three groups the game shows by CSS (style.css, html[data-festival=posidelki][data-festival-decor=on]):
//   vf-decor  — plaids, yarn baskets, the samovar, knitted-flag garlands, chimney smoke (under the night tint);
//   vf-day    — warm light in the windows by day («свет в окнах раньше вечера»);
//   vf-night  — windows, samovar and garland glow above the night tint.
import {FarmScene} from '/static/scene.js';
import {SvgCtx} from './svg_ctx.js';

// farm palette: muted reds, sage, mustard and cream of the farm's roofs, awnings and fabrics
const PLAIDS = [['#c97a6a', '#efe0c4', '#9b5a4c'], ['#8fae86', '#f1e6cc', '#6f8f68'], ['#d9b25e', '#f4e8c8', '#b08a3c']];
const FLAGS = ['#c97a6a', '#d9b25e', '#8fae86', '#c3b0de', '#e7a8b5', '#7fa3c4'];
const YARN = ['#c97a6a', '#e7a8b5', '#8fae86', '#d9b25e', '#7fa3c4', '#c3b0de'];

export function posidelki(V) {
  // V: {B, P(x,y,z), matrix:[a,b,c,d,e,f] farm px -> world units, windows:[[kind,px,py,w,h]], chimneys:[[px,py]],
  //     fences:[[x1,y1,x2,y2]], bridges:[[x0,y0,x1,y1]], benches:[[x,y,axis]], lamps:[[x,y]], spots:{name:[x,y]}, free(x,y)}
  const {B, P} = V, c = new SvgCtx('vf'), s = Object.create(FarmScene.prototype);
  s.c = c; s.time = 0; s.motion = false; s.inStatic = true; s.shadowLevel = 0;
  const problems = [];
  const pt = (x, y, z = 0) => P(x, y, z);
  // occlusion: a point of the layer (tile x, y, height z) is hidden when a taller object standing in front of it covers it
  // on screen. The layer is drawn over the art, so such points must not get decor.
  const hull = pts => { pts = [...pts].sort((p, q) => p.x - q.x || p.y - q.y); const cr = (o, a, b) => (a.x - o.x) * (b.y - o.y) - (a.y - o.y) * (b.x - o.x);
    const lo = [], up = []; for (const p of pts) { while (lo.length > 1 && cr(lo[lo.length - 2], lo[lo.length - 1], p) <= 0) lo.pop(); lo.push(p) }
    for (const p of [...pts].reverse()) { while (up.length > 1 && cr(up[up.length - 2], up[up.length - 1], p) <= 0) up.pop(); up.push(p) }
    return lo.slice(0, -1).concat(up.slice(0, -1)) };
  const tall = V.tall.map(({r: [x0, y0, x1, y1], h}) => ({front: x1 + y1, h: hull([[x0, y0], [x1, y0], [x1, y1], [x0, y1]].flatMap(([x, y]) => [pt(x, y, 0), pt(x, y, h)]))}));
  const inHull = (h, p) => h.every((a, i) => { const b = h[(i + 1) % h.length]; return (b.x - a.x) * (p.y - a.y) - (b.y - a.y) * (p.x - a.x) >= 0 });
  const hidden = (x, y, z) => { const q = pt(x, y, z); return tall.some(o => o.front > x + y + .05 && inHull(o.h, q)) };
  const visible = (x, y, z, what) => { if (hidden(x, y, z)) { problems.push(`posidelki: ${what} hidden behind a building`); return false } return true };
  const quad = (pts, fill) => s.poly(pts.map(([x, y, z]) => pt(x, y, z)), fill);

  // ---------- decor: under the night tint ----------
  c.group('vf-decor');
  // plaid hanging over a rail in the plane of a fence segment (a..b along it), top at z, with stripes and a fringe
  const plaid = (ax, ay, bx, by, z, drop, [base, light, dark], flip = false) => {
    const L = Math.hypot(bx - ax, by - ay), ux = (bx - ax) / L, uy = (by - ay) / L, nx = -uy * .06 * (flip ? -1 : 1), ny = ux * .06 * (flip ? -1 : 1);
    const at = (u, zz, o = 0) => [ax + ux * u + nx * o, ay + uy * u + ny * o, zz];
    quad([at(0, z, -1), at(L, z, -1), at(L, z), at(0, z)], dark);                     // fold over the rail
    quad([at(0, z), at(L, z), at(L, z - drop), at(0, z - drop)], base);                // the hanging cloth
    for (const f of [.28, .7]) quad([at(L * f - .03, z), at(L * f + .03, z), at(L * f + .03, z - drop), at(L * f - .03, z - drop)], light);
    for (const f of [.35, .72]) quad([at(0, z - drop * f + .9), at(L, z - drop * f + .9), at(L, z - drop * f - .9), at(0, z - drop * f - .9)], light);
    for (let u = .04; u < L; u += .09) { const p = pt(...at(u, z - drop)); s.line(p.x, p.y, p.x, p.y + 2.6, dark, .9) }
  };
  // two plaids on fences by the houses, one on the bridge rail, two on plaza benches
  // the two garden fences nearest the plaza (by the residents' houses, not the field fences), straight along x, in view
  const [cx, cy] = [(V.plaza[0] + V.plaza[2]) / 2, (V.plaza[1] + V.plaza[3]) / 2];
  const fences = V.fences.filter(f => Math.abs(f[1] - f[3]) < .01 && Math.abs(f[2] - f[0]) >= 1.6 && !hidden((f[0] + f[2]) / 2, f[1], 6))
    .sort((a, b) => Math.hypot((a[0] + a[2]) / 2 - cx, a[1] - cy) - Math.hypot((b[0] + b[2]) / 2 - cx, b[1] - cy)).slice(0, 2);
  if (fences.length < 2) problems.push('posidelki: fewer than two fences for plaids');
  fences.forEach((f, k) => { const a = Math.min(f[0], f[2]), L = Math.abs(f[2] - f[0]), w = Math.min(.85, L * .45);
    plaid(a + (L - w) / 2, f[1], a + (L + w) / 2, f[1], 11, 9 - k, PLAIDS[k]) });
  const br = V.bridges[0];
  if (br && visible(br[0] + 2, br[3] - .05, 16, 'bridge plaid')) plaid(br[0] + 1.6, br[3] - .05, br[0] + 2.4, br[3] - .05, 21, 9, PLAIDS[2]); else problems.push('posidelki: no bridge');
  for (const [k, [x, y, axis]] of V.benches.slice(0, 2).entries()) {
    const [base, light, dark] = PLAIDS[(k + 1) % 3];
    if (axis === 'x') { quad([[x - .22, y - .12, 8.6], [x + .1, y - .12, 8.6], [x + .1, y + .12, 8.6], [x - .22, y + .12, 8.6]], base);
      quad([[x - .22, y + .12, 8.6], [x + .1, y + .12, 8.6], [x + .1, y + .12, 3], [x - .22, y + .12, 3]], dark);
      quad([[x - .08, y - .12, 8.7], [x - .03, y - .12, 8.7], [x - .03, y + .12, 3], [x - .08, y + .12, 3]], light) }
    else { quad([[x - .12, y - .2, 8.6], [x + .12, y - .2, 8.6], [x + .12, y + .12, 8.6], [x - .12, y + .12, 8.6]], base);
      quad([[x + .12, y - .2, 8.6], [x + .12, y + .12, 8.6], [x + .12, y + .12, 3], [x + .12, y - .2, 3]], dark);
      quad([[x - .12, y - .05, 8.7], [x + .12, y - .05, 8.7], [x + .12, y - .01, 3], [x + .12, y - .01, 8.7]], light) }
  }
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
  const garland = (a, b, k) => {
    const A = pt(a[0], a[1], 44), Bp = pt(b[0], b[1], 44), L = Math.hypot(Bp.x - A.x, Bp.y - A.y), sag = L * .1;
    const at = t => ({x: A.x + (Bp.x - A.x) * t, y: A.y + (Bp.y - A.y) * t + 4 * sag * t * (1 - t)});
    c.beginPath(); c.moveTo(A.x, A.y); c.quadraticCurveTo((A.x + Bp.x) / 2, (A.y + Bp.y) / 2 + 2 * sag, Bp.x, Bp.y);
    c.strokeStyle = '#8a6c4c'; c.lineWidth = 1; c.stroke();
    const n = Math.max(4, Math.round(L / 15));
    for (let i = 1; i < n; i++) {
      const p = at(i / n), q = at(i / n + .4 / n), col = FLAGS[(i + k * 2) % FLAGS.length];
      s.poly([p, q, {x: (p.x + q.x) / 2, y: (p.y + q.y) / 2 + 10}], col);
      s.line(p.x + 1, p.y + 2.5, q.x - 1, q.y + 2.5, '#ffffff4d', .8); s.line(p.x + 2.4, p.y + 5.3, q.x - 2.4, q.y + 5.3, '#ffffff4d', .8);   // knit rows
    }
  };
  // pairs of lamps by the plaza, 4–11 tiles apart, whose garland nothing stands in front of; the longest two without a shared lamp
  const near = V.lamps.filter(([x, y]) => x > V.plaza[0] - 3 && x < V.plaza[2] + 3 && y > V.plaza[1] - 3 && y < V.plaza[3] + 3);
  const pairs = [];
  for (let i = 0; i < near.length; i++) for (let j = i + 1; j < near.length; j++) {
    const [a, b] = [near[i], near[j]], d = Math.hypot(a[0] - b[0], a[1] - b[1]);
    if (d < 4 || d > 11) continue;
    let ok = true;
    for (let t = .02; t < 1 && ok; t += .04) { const x = a[0] + (b[0] - a[0]) * t, y = a[1] + (b[1] - a[1]) * t; if (hidden(x, y, 44 - 30 * t * (1 - t))) ok = false }
    if (ok) pairs.push([d, a, b]);
  }
  pairs.sort((p, q) => q[0] - p[0] || p[1][0] - q[1][0] || p[1][1] - q[1][1]);
  const used = new Set(), chosen = [];
  for (const [, a, b] of pairs) { if (chosen.length >= 2 || used.has(a) || used.has(b)) continue; chosen.push([a, b]); used.add(a); used.add(b) }
  if (!chosen.length) problems.push('posidelki: no clear place for a garland');
  chosen.forEach(([a, b], k) => garland(a, b, k));
  // cosy smoke: three soft puffs over every chimney (the game animates vf-s1..3 rising, unless motion is reduced)
  for (let i = 1; i <= 3; i++) {
    c.group(`vf-smoke vf-s${i}`);
    for (const [x, y] of V.chimneys) s.ellipse(x + i * 1.5, y - 6 - i * 9, 3 + i * 1.6, 2.4 + i * 1.2, 'rgba(250,246,234,.5)');
    c.end();
  }
  c.end();

  // ---------- windows: warm by day, lit at night ----------
  const glass = ([kind, X, Y, w, h], grow = 0) => {   // the glass parallelogram of a window in its wall plane
    const ax = (kind === 'a' ? 18 : -18) * w, ay = 9 * w, hh = h / 2 + grow;
    return [{x: X - ax - grow, y: Y - ay - hh}, {x: X + ax + grow, y: Y + ay - hh}, {x: X + ax + grow, y: Y + ay + hh}, {x: X - ax - grow, y: Y - ay + hh}];
  };
  c.group('vf-day');
  for (const w of V.windows) s.poly(glass(w), 'rgba(255,214,130,.5)');
  c.end();
  c.group('vf-night');
  for (const w of V.windows) { s.poly(glass(w, 3), 'rgba(255,200,95,.22)'); s.poly(glass(w), 'rgba(255,226,160,.85)') }
  const sv = pt(tx - .06, ty - .04, 20); s.ellipse(sv.x, sv.y, 22, 14, 'rgba(255,200,95,.22)'); s.ellipse(sv.x, sv.y, 9, 7, 'rgba(255,220,140,.35)');
  c.end();

  const m = V.matrix.map(v => +v.toFixed(4)).join(' ');
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 2400 1800" class="vf-art" aria-hidden="true" focusable="false">` +
    `<g transform="matrix(${m})">${c.svg()}</g></svg>`;
  return {svg, problems};
}
