// «Весенние цветы» (FARM_FESTIVALS_DESIGN.md §9.2 №3): the village's festival layer, vector only (fest_kit.js).
//   vf-decor  — round tulip beds on and by the plaza, planters of tulips by the house doors, ribbon bows on the garden fences,
//               spring garlands of flowers between the plaza lamps, chimney smoke (under the night tint);
//   vf-day    — warm light in the windows;
//   vf-night  — windows and the paper lanterns of the garlands above the night tint.
import {festKit} from './fest_kit.js';

const TULIPS = ['#d9553f', '#e8c25a', '#e7a8b5', '#f4ede0', '#c3b0de', '#e8955a'];
const RIBBONS = ['#e7a8b5', '#8fae86', '#c3b0de', '#e8c25a', '#7fa3c4'];
const STEM = '#6f9a5f', LEAF = '#86b071';

export function springFlowers(V) {
  // V as fest_newyear plus doors:[['y',Y,xc,w] | ['x',X,yc,w]] (recorded doorY/doorX)
  const K = festKit(V, 'spring_flowers'), {B, c, s, pt, hidden, problems} = K;
  const [px0, py0, px1, py1] = V.plaza, mid = [(px0 + px1) / 2, (py0 + py1) / 2];
  const pieces = [];   // [depth, draw], back to front

  // a tulip at tile (x, y): stem, one leaf, a cup of three petals; k picks the colour
  const tulip = (x, y, z0, k, tall = 7) => {
    const g = pt(x, y, z0), h = {x: g.x, y: g.y - tall};
    s.line(g.x, g.y, h.x, h.y, STEM, 1);
    s.poly([{x: g.x, y: g.y - 1}, {x: g.x + (k % 2 ? 3 : -3), y: g.y - 4.5}, {x: g.x, y: g.y - 3.4}], LEAF);
    const col = TULIPS[k % TULIPS.length];
    s.poly([{x: h.x - 2.2, y: h.y - 3.6}, {x: h.x - 1.1, y: h.y - 1.8}, {x: h.x, y: h.y - 3.8}, {x: h.x + 1.1, y: h.y - 1.8}, {x: h.x + 2.2, y: h.y - 3.6},
      {x: h.x + 1.8, y: h.y}, {x: h.x - 1.8, y: h.y}], col);
    s.poly([{x: h.x - 1.8, y: h.y}, {x: h.x - 2.2, y: h.y - 3.6}, {x: h.x - 1.1, y: h.y - 1.8}, {x: h.x - .4, y: h.y}], 'rgba(255,255,255,.28)');
  };

  // ---------- round tulip beds: a stone rim, dark soil, rings of tulips of mixed colours ----------
  const around = [px0 - 5, py0 - 5, px1 + 5, py1 + 5];
  for (let k = 0; k < 3; k++) {
    const at = K.place({w: 1.1, d: 1.1, h: 14, near: [mid[0] + [0, -2.5, 2.5][k], mid[1] + [2.5, 3.5, 1][k]], area: around, what: `flowerbed ${k + 1}`});
    if (!at) continue;
    const cx = at[0] + .55, cy = at[1] + .55;
    pieces.push([cx + cy + .55, () => {
      const g = pt(cx, cy, 0);
      s.ellipse(g.x, g.y + 1.5, 36, 18, '#cdbf9f'); s.ellipse(g.x, g.y, 34, 16.5, '#e2d7bd'); s.ellipse(g.x, g.y + .6, 29, 13.8, '#7a5a3e');
      const pts = [];
      for (const [r, n] of [[.36, 12], [.2, 7], [0, 1]]) for (let i = 0; i < n; i++) { const a = i / n * Math.PI * 2 + r * 3; pts.push([cx + Math.cos(a) * r, cy + Math.sin(a) * r, i + n + k]) }
      pts.sort((a, b) => (a[0] + a[1]) - (b[0] + b[1])).forEach(([x, y, i]) => tulip(x, y, 0, i, 7 + (i % 3)));
    }]);
  }

  // ---------- planters of tulips by the doors (both sides of every door the village shows) ----------
  let planters = 0;
  for (const [axis, W, cc, w] of V.doors || []) {
    for (const side of [-1, 1]) {
      const [x, y] = axis === 'y' ? [cc + side * (w / 2 + .2), W + .13] : [W + .13, cc + side * (w / 2 + .2)];
      const own = ([a, b, c2, d]) => x > a && x < c2 && y > b && y < d;   // the house's own claim stands around its door
      if (hidden(x, y, 0, own) || hidden(x, y, 12, own) || V.ground && !V.ground(x, y)) continue;
      planters++;
      pieces.push([x + y + .2, () => {
        const [a0, b0, a1, b1] = axis === 'y' ? [x - .14, y - .08, x + .14, y + .08] : [x - .08, y - .14, x + .08, y + .14];
        B.fullBox(s, '#b48f66', a0, b0, a1, b1, 0, 5, '#7a5a3e');
        [[-.07, 0], [0, .02], [.07, 0]].forEach(([u, v], i) => tulip(axis === 'y' ? x + u : x + v, axis === 'y' ? y + v : y + u, 5, i + Math.round(x * 3 + y)));
      }]);
    }
  }
  if (planters < 6) problems.push(`spring_flowers: only ${planters} door planters in view`);

  // ---------- ribbon bows on the garden fences by the plaza: a bow and two tails on every post ----------
  for (const [i, [x1, y1, x2, y2]] of K.gardenFences(4).entries()) {
    const n = Math.max(1, Math.round(Math.hypot(x2 - x1, y2 - y1) / 1.2));
    for (let j = 0; j <= n; j++) {
      const x = x1 + (x2 - x1) * j / n, y = y1 + (y2 - y1) * j / n;
      if (hidden(x, y, 10)) continue;
      pieces.push([x + y + .01, () => {
        const p = pt(x, y, 9), col = RIBBONS[(i + j) % RIBBONS.length];
        s.poly([p, {x: p.x - 5, y: p.y - 3}, {x: p.x - 5, y: p.y + 2.4}], col); s.poly([p, {x: p.x + 5, y: p.y - 3}, {x: p.x + 5, y: p.y + 2.4}], col);
        s.line(p.x, p.y, p.x - 2, p.y + 8, col, 1.2); s.line(p.x, p.y, p.x + 2.4, p.y + 7, col, 1.2); s.ellipse(p.x, p.y, 1.3, 1.3, '#ffffff99');
      }]);
    }
  }

  c.group('vf-decor');
  // spring garlands between the plaza lamps: a green string with leaves, flowers and a paper lantern every few flowers
  const lanterns = [];
  K.lampPairs(3).forEach(([a, b]) => K.garland(a, b, (p, q, i) => {
    if (i % 4 === 2) { s.line(p.x, p.y, p.x, p.y + 3, '#8a6c4c', .8); s.ellipse(p.x, p.y + 6, 3, 3.6, ['#f4ede0', '#e7a8b5', '#e8c25a'][i % 3]); lanterns.push(p); return }
    s.poly([p, {x: p.x + 4, y: p.y + 2}, {x: p.x + 1, y: p.y + 4}], LEAF);
    const col = TULIPS[i % TULIPS.length];
    for (let k = 0; k < 5; k++) { const a = k * Math.PI * 2 / 5; s.ellipse(p.x + Math.cos(a) * 2, p.y + 2 + Math.sin(a) * 2, 1.7, 1.7, col) }
    s.ellipse(p.x, p.y + 2, 1.1, 1.1, '#e8c25a');
  }, STEM, 10));
  pieces.sort((a, b) => a[0] - b[0]).forEach(([, draw]) => draw());
  K.smoke();
  c.end();

  c.group('vf-day');
  K.windowsDay();
  c.end();
  c.group('vf-night');
  K.windowsNight();
  for (const p of lanterns) { s.ellipse(p.x, p.y + 6, 9, 8, 'rgba(255,214,130,.25)'); s.ellipse(p.x, p.y + 6, 2.6, 3.2, '#ffe7a0') }
  c.end();
  return {svg: K.wrap(), problems};
}
