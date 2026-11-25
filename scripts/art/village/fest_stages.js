// Village preparation stages («Праздник 1/4 … 4/4», the seasonal village fund): the plaza's decor drawn into the world,
// vector only (fest_kit.js), instead of the flat CSS strips that crossed the plaza on the screen axis.
// The game shows the groups by the stage (style.css .village-stage[data-stage], app.js syncVillageStage):
//   vs-flags     stage ≥ 1 «Флажки к празднику»  — two garlands of pennants from the clock tower to the plaza's side lamps;
//   vs-flowers   stage ≥ 2 «Цветы к празднику»   — baskets of tulips hung on the lamps round the plaza;
//   vs-lights    stage 3   «Площадь готова»      — bulbs along the bunting;
//   vs-balloons  stage 3                          — a bunch of balloons tied to a stake by the town hall;
//   vs-glow      stage 3, above the night tint    — the bulbs lit.
// The calendar festivals (fest_<id>.js) also hang garlands on the plaza lamps; both may show at once.
import {festKit} from './fest_kit.js';

const FLAGS = ['#d9694f', '#f2cf5c', '#6fa6c9', '#8fae86'];        // the bunting colours players already know from the strips
const TULIPS = ['#d9553f', '#e8c25a', '#e7a8b5', '#f4ede0', '#c3b0de', '#e8955a'], STEM = '#6f9a5f', LEAF = '#86b071';   // as fest_flowers.js
const BALLOONS = ['#e87d8a', '#f2cf5c', '#6fa6c9', '#8fae86', '#c3b0de'];

export function villageStages(V) {
  const K = festKit(V, 'stages'), {B, c, s, pt, problems} = K;
  const [px0, py0, px1, py1] = V.plaza;

  // ---------- stage 1: bunting from the clock tower down to the plaza's side lamps ----------
  // The plaza floor and its edges are ways (the player's walk runs round the plaza, the streets open into it, the stalls fill
  // the left front edge), so no string is strung across them: the two garlands fan out from the tower's eave corners over the
  // back half of the plaza and end on the lamps at its left and right corners, high above the stalls and the gazebo.
  // A point of this layer is covered only by an object it stands behind on both axes (K.hidden orders by x+y, too coarse
  // by the plaza edge), and a house only by its real silhouette with the roof, not by its box 80 px tall.
  const shape = o => (K.houses.find(hs => hs.fp[0] > o.r[0] - .01 && hs.fp[2] < o.r[2] + .01 && hs.fp[1] > o.r[1] - .01 && hs.fp[3] < o.r[3] + .01) || {}).hull
    || K.hull([[o.r[0], o.r[1]], [o.r[2], o.r[1]], [o.r[2], o.r[3]], [o.r[0], o.r[3]]].flatMap(([x, y]) =>
      // a wide object that is not a house (the tea pavilion) has a pointed roof: its silhouette narrows to the top
      o.r[2] - o.r[0] > 1.5 && o.r[3] - o.r[1] > 1.5 ? [pt(x, y, 0), pt(x, y, o.h * .45), pt((o.r[0] + o.r[2]) / 2, (o.r[1] + o.r[3]) / 2, o.h)] : [pt(x, y, 0), pt(x, y, o.h)]));
  const behind = (x, y, z, q = pt(x, y, z)) => V.tall.some(o => x < o.r[2] && y < o.r[3] && K.inHull(shape(o), q));
  const tower = (V.roofs || []).map(([kind, a]) => a).filter(a => a && a[4] > 80 && a[0] >= px0 && a[1] >= py0 && a[0] < (px0 + px1) / 2 && a[1] < (py0 + py1) / 2)[0];
  const lampNear = (x, y) => (V.lamps || []).filter(([lx, ly]) => Math.hypot(lx - x, ly - y) < 1.6).sort((p, q) => Math.hypot(p[0] - x, p[1] - y) - Math.hypot(q[0] - x, q[1] - y))[0];
  // a string point over an object's footprint passes above it (the anchors are chosen so); elsewhere it is covered by what
  // stands in front of it on both axes
  const over = (x, y) => V.tall.some(o => x >= o.r[0] && y >= o.r[1] && x <= o.r[2] && y <= o.r[3]);
  const bulbs = [], LAMP_Z = 44;
  c.group('vs-flags');
  let pennant = 0;
  // one sagging span a → b ([x, y, z] tiles and farm px) with pennants under it
  const span = ([ax, ay, az], [bx, by, bz]) => {
    const A = pt(ax, ay, az), Bp = pt(bx, by, bz), L = Math.hypot(Bp.x - A.x, Bp.y - A.y), sag = L * .07;
    const at = t => ({x: A.x + (Bp.x - A.x) * t, y: A.y + (Bp.y - A.y) * t + 4 * sag * t * (1 - t)});
    const hid = [];   // the pennants hang 8 px under the string
    for (let t = .04; t < .97; t += .04) { const x = ax + (bx - ax) * t, y = ay + (by - ay) * t, q = at(t); if (!over(x, y) && behind(x, y, 0, {x: q.x, y: q.y + 8})) hid.push(t.toFixed(2)) }
    if (hid.length) problems.push(`stages: the tower garland ${[ax, ay].map(v => v.toFixed(1))}→${[bx, by].map(v => v.toFixed(1))} is hidden at t=${hid.join(',')}`);
    c.beginPath(); c.moveTo(A.x, A.y); c.quadraticCurveTo((A.x + Bp.x) / 2, (A.y + Bp.y) / 2 + 2 * sag, Bp.x, Bp.y);
    c.strokeStyle = '#7a5a3e'; c.lineWidth = .9; c.stroke();
    const n = Math.round(L / 13);
    for (let i = 1; i < n; i++) {
      const p = at((i - .32) / n), q = at((i + .32) / n), col = FLAGS[pennant++ % FLAGS.length], tip = {x: (p.x + q.x) / 2, y: (p.y + q.y) / 2 + 9};
      s.poly([p, q, tip], col); s.poly([p, {x: (p.x + q.x) / 2, y: (p.y + q.y) / 2}, tip], 'rgba(255,255,255,.18)');
      if (i % 2) bulbs.push(at((i + .5) / n));   // a bulb between every other pair of pennants
    }
  };
  if (!tower) problems.push('stages: the clock tower roof is not found');
  else {
    const [x0, y0, x1, y1, zE, , , ov] = tower, e = ov + .02;
    // the tower's left eave corner → the lamp at the plaza's left corner, the right one → the lamp at the right corner.
    // On screen the right string runs over the tea pavilion's roof; it was approved that way.
    for (const [from, to] of [[[x0 - e, y1 + e], [px0 + 1.6, py1 + .6]], [[x1 + e, y0 - e], [px1 + .6, py0 + 1.6]]]) {
      const lamp = lampNear(...to);
      if (!lamp) { problems.push(`stages: no lamp by ${to}`); continue }
      span([from[0], from[1], zE - 2], [lamp[0], lamp[1], LAMP_Z]);
    }
  }
  if (bulbs.length < 12) problems.push(`stages: only ${bulbs.length} bulbs on the tower garlands`);
  c.end();

  // ---------- stage 2: baskets of tulips hung on the lamps round the plaza ----------
  // The plaza floor is taken (the walk round it, stalls, benches, the well), so the flowers go up on the lamp posts: a bracket
  // under the head (z 44, the festivals' garlands hang from there), the basket below it, on the side facing the viewer.
  const lamps = (V.lamps || []).filter(([x, y]) => x > px0 - 1.6 && x < px1 + 1.6 && y > py0 - 1.6 && y < py1 + 1.6
    && [24, 34].every(z => !behind(x + .25, y + .25, z)));
  if (lamps.length < 3) problems.push(`stages: only ${lamps.length} plaza lamps for the flower baskets`);
  c.group('vs-flowers');
  lamps.forEach(([x, y], k) => {
    const arm = pt(x, y, 35), end = pt(x + .28, y + .28, 35), hang = {x: end.x, y: end.y + 5};
    s.line(arm.x, arm.y, end.x, end.y, '#3f4a3e', 1.4);   // bracket
    s.line(end.x, end.y, hang.x, hang.y, '#5b5246', .7);   // chain
    // trailing leaves under the basket, the basket, the tulips over its rim
    for (const [dx, len] of [[-4.5, 7], [0, 9], [4.5, 6]]) s.line(hang.x + dx, hang.y + 5, hang.x + dx * 1.2, hang.y + 5 + len, LEAF, 1.6);
    s.poly([{x: hang.x - 7, y: hang.y + 1}, {x: hang.x + 7, y: hang.y + 1}, {x: hang.x + 5, y: hang.y + 7}, {x: hang.x - 5, y: hang.y + 7}], '#a7814f');
    s.line(hang.x - 7, hang.y + 1, hang.x + 7, hang.y + 1, '#7a5a3e', 1.2);
    for (let i = 0; i < 5; i++) { const fx = hang.x - 5.5 + i * 2.75, fy = hang.y - 1.5 - (i % 2) * 1.6;
      s.line(fx, fy + 3, fx, hang.y + 1, STEM, .8); s.ellipse(fx, fy, 1.7, 2.1, TULIPS[(i + k * 2) % TULIPS.length]) }
  });
  c.end();

  // ---------- stage 3: bulbs on the strings, balloons by the hall ----------
  c.group('vs-lights');
  for (const b of bulbs) { s.ellipse(b.x, b.y + 1.8, 1.5, 1.8, '#f6dc8f'); s.ellipse(b.x - .4, b.y + 1.3, .5, .6, '#fffbe6') }
  c.end();

  const stake = K.place({w: .3, d: .3, h: 66, near: [19.4, 19.4], area: V.plaza, cover: .12, what: 'balloon stake'});
  c.group('vs-balloons');
  if (stake) {
    const [x, y] = [stake[0] + .15, stake[1] + .15];
    B.cyl(s, x, y, .05, 0, 12, '#8a6c4c', '#6f5640');
    const knot = pt(x, y, 12);
    // five balloons in a loose bunch: offsets on screen (px), back ones first
    const bunch = [[-9, -50, 0], [8, -53, 1], [0, -60, 2], [-13, -40, 3], [11, -42, 4]];
    for (const [dx, dy, k] of bunch) {
      const b = {x: knot.x + dx, y: knot.y + dy};
      c.beginPath(); c.moveTo(knot.x, knot.y); c.quadraticCurveTo(knot.x + dx * .3, knot.y + dy * .55, b.x, b.y + 8);
      c.strokeStyle = '#8a7a66'; c.lineWidth = .7; c.stroke();
    }
    for (const [dx, dy, k] of bunch) {
      const b = {x: knot.x + dx, y: knot.y + dy}, col = BALLOONS[k];
      s.poly([{x: b.x - 1.4, y: b.y + 8.8}, {x: b.x + 1.4, y: b.y + 8.8}, {x: b.x, y: b.y + 6.6}], col);
      s.ellipse(b.x, b.y, 6.4, 7.8, col);
      s.ellipse(b.x - 2.2, b.y - 2.8, 1.6, 2.4, 'rgba(255,255,255,.45)');
    }
  } else problems.push('stages: no place for the balloon stake');
  c.end();

  c.group('vs-glow');
  for (const b of bulbs) { s.ellipse(b.x, b.y + 1.8, 5, 4.4, 'rgba(255,214,130,.28)'); s.ellipse(b.x, b.y + 1.8, 1.5, 1.8, '#ffe7a0') }
  c.end();

  return {svg: K.wrap(), problems};
}
