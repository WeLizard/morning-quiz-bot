// «Новый год» (20.12–14.01, FARM_FESTIVALS_DESIGN.md §9.2 №1): the village's festival layer, vector only (fest_kit.js).
// Snow on the roofs the farm drew (recorded roofs, replayed in snow colours) with icicles, lights along the ridges, the big fir
// on the plaza with lights, baubles and empty hooks for the named toys (fest_ny_toy), a snowman by the well with a bullfinch,
// plaids on the plaza benches, warm windows and chimney smoke. vf-night: windows, ridge lights, fir lights and star above the tint.
import {festKit} from './fest_kit.js';
import {snowCover} from './fest_snow.js';

const BULBS = ['#e8c25a', '#d9553f', '#7fa3c4', '#8fae86', '#e7a8b5'];
const SNOW = '#eef2f4';

export function newYear(V) {
  // V as fest_posidelki plus chimneys3d:[[x,y,za,zb,col,w]], roofs:[['gable',axis,g] | ['hip',[x0,y0,x1,y1,zE,rise,col,ov,top]]], wells:[[x,y]]; V.tall includes trees
  const K = festKit(V, 'new_year'), {B, c, s, pt, hidden, problems} = K;
  // ---------- the roofs as the farm drew them: footprint, eaves, ridge, sample points for the occlusion checks ----------
  const roofs = V.roofs.map(([kind, a, g]) => {
    if (kind === 'gable') {
      const {x0, y0, x1, y1, zE, prof, R, ov} = g, axis = a;
      let rt = .5, rm = -1; for (const [t, r] of prof) if (r * R > rm) { rm = r * R; rt = t }
      const A0 = (axis === 'y' ? x0 : y0) - ov, A1 = (axis === 'y' ? x1 : y1) + ov, B0 = (axis === 'y' ? y0 : x0) - ov, B1 = (axis === 'y' ? y1 : x1) + ov;
      const ridge = A0 + (A1 - A0) * rt, at = (u, v) => axis === 'y' ? [u, v] : [v, u];
      return {kind, axis, g, fp: [x0, y0, x1, y1], zE, top: zE + rm,
        samples: [[...at(A0, B0), zE], [...at(A1, B0), zE], [...at(A0, B1), zE], [...at(A1, B1), zE], [...at(ridge, B0), zE + rm], [...at(ridge, B1), zE + rm]],
        ridge: [at(ridge, B0 + .1), at(ridge, B1 - .1), zE + rm], eaves: [[at(A1, B0 + .05), at(A1, B1 - .05), zE]]};
    }
    const [x0, y0, x1, y1, zE, rise, col, ov, flat] = a, xm = (x0 + x1) / 2, ym = (y0 + y1) / 2, W = x1 - x0 + 2 * ov, H = y1 - y0 + 2 * ov, i = Math.min(W, H) / 2 - flat;
    return {kind, args: a, fp: [x0, y0, x1, y1], zE, top: zE + rise,
      ridge: Math.abs(W - H) < .3 ? null : W > H ? [[x0 - ov + i, ym], [x1 + ov - i, ym], zE + rise] : [[xm, y0 - ov + i], [xm, y1 + ov - i], zE + rise],
      samples: [[x0 - ov, y0 - ov, zE], [x1 + ov, y0 - ov, zE], [x0 - ov, y1 + ov, zE], [x1 + ov, y1 + ov, zE], [xm, ym, zE + rise]],
      eaves: [[[x1 + ov, y0 - ov + .05], [x1 + ov, y1 + ov - .05], zE], [[x0 - ov + .05, y1 + ov], [x1 + ov - .05, y1 + ov], zE]]};
  });
  // occluders of a roof: the other buildings as their real silhouettes (walls from the ground up to the eaves, the roof over
  // them), trees, and tall things that are not buildings (the claims of buildings are wider than the houses, so they do not count)
  const own = (r, [x0, y0, x1, y1]) => { const cx = (r.fp[0] + r.fp[2]) / 2, cy = (r.fp[1] + r.fp[3]) / 2; return cx > x0 && cx < x1 && cy > y0 && cy < y1 };
  for (const r of roofs) { const [x0, y0, x1, y1] = r.fp;
    r.hull = K.hull([...r.samples.map(([x, y, z]) => pt(x, y, z)), ...[[x0, y0], [x1, y0], [x1, y1], [x0, y1]].map(([x, y]) => pt(x, y, 0))]) }
  const building = t => roofs.some(r => own(r, t));
  // drawn after the roof's building (the farm sorts by the front corner) and over the point on screen
  const coveredBy = (r, x, y, z) => { const q = pt(x, y, z);
    return roofs.find(o => o !== r && !own(r, o.fp) && !own(o, r.fp) && o.fp[2] + o.fp[3] > r.fp[2] + r.fp[3] && K.inHull(o.hull, q)) };
  // houses in front are cut out of the snow (clip), trees and other tall things in front leave the roof bare
  const clean = roofs.filter(r => {
    r.cut = new Set();
    for (const [x, y, z] of r.samples) {
      const skip = t => building(t) || t[2] + t[3] <= r.fp[2] + r.fp[3];
      if (hidden(x, y, z, skip)) return false;
      const o = coveredBy(r, x, y, z); if (o) r.cut.add(o);
    }
    return true;
  });
  if (clean.length < 6) problems.push(`new_year: only ${clean.length} roofs can take snow`);

  c.group('vf-decor');
  // snow on the ground (fest_snow.js): diamonds of snow on the bare grass, trodden paths, thaw by the walls and under trees,
  // drifts by the roads, caps on the crowns
  const snow = snowCover(V, K, {cover: 1, thaw: 0, under: .45, trodden: .38, drifts: .3, caps: true});
  // snow caps: the same roof, a little smaller, in snow; icicles under the front eave
  for (const r of clean) {
    if (r.cut.size) c.groupClipOut([...r.cut].map(o => o.hull));
    if (r.kind === 'gable') B.gableRoof(s, r.axis, {...r.g, roof: SNOW, trim: '#ffffff', courses: 1, ov: r.g.ov * .55, zE: r.g.zE + 1.2});
    else { const [x0, y0, x1, y1, zE, rise, , ov, top] = r.args; B.hipRoof(s, x0, y0, x1, y1, zE + 1.2, rise, SNOW, ov * .55, top) }
    for (const [[ax, ay], [bx, by], z] of r.eaves) { const n = Math.max(3, Math.round(Math.hypot(bx - ax, by - ay) / .22));
      for (let i = 0; i <= n; i++) { const q = pt(ax + (bx - ax) * i / n, ay + (by - ay) * i / n, z), l = 2.5 + (i * 7 % 5);
        s.poly([{x: q.x - 1.3, y: q.y}, {x: q.x + 1.3, y: q.y}, {x: q.x, y: q.y + l}], '#f6fafc') } }
    // chimneys stand on the snow: drawn again over it, with a cap
    for (const [x, y, za, zb, col, w] of V.chimneys3d) if (x > r.fp[0] - .05 && x < r.fp[2] + .05 && y > r.fp[1] - .05 && y < r.fp[3] + .05) {
      B.chimney(s, x, y, za, zb, col, w); B.top(s, SNOW, x - w * 1.1, y - w * 1.1, x + w * 1.1, y + w * 1.1, zb + 1.2) }
    if (r.cut.size) c.end();
  }
  // ridge lights (day: coloured bulbs; night: the glow group below)
  const ridgeBulbs = [];
  for (const r of clean) for (const [[ax, ay], [bx, by], z] of r.eaves) {   // a string of lights along the eaves
    const n = Math.max(3, Math.round(Math.hypot(bx - ax, by - ay) / .4));
    for (let i = 0; i <= n; i++) { const q = pt(ax + (bx - ax) * i / n, ay + (by - ay) * i / n, z - 1.5); if ([...r.cut].some(o => K.inHull(o.hull, q))) continue;
      ridgeBulbs.push([q, BULBS[(i + 2) % BULBS.length]]); s.ellipse(q.x, q.y, 1.2, 1.2, BULBS[(i + 2) % BULBS.length]) }
  }
  for (const r of clean.filter(r => r.ridge)) {
    const [[ax, ay], [bx, by], z] = r.ridge, n = Math.max(3, Math.round(Math.hypot(bx - ax, by - ay) / .3));
    for (let i = 0; i <= n; i++) { const q = pt(ax + (bx - ax) * i / n, ay + (by - ay) * i / n, z + 2); if ([...r.cut].some(o => K.inHull(o.hull, q))) continue; ridgeBulbs.push([q, BULBS[i % BULBS.length]]); s.ellipse(q.x, q.y, 1.3, 1.3, BULBS[i % BULBS.length]) }
  }
  // the big fir on or by the plaza: the free spot nearest the plaza's middle that nothing hides, up to its star
  const [px0, py0, px1, py1] = V.plaza, mid = [(px0 + px1) / 2, (py0 + py1) / 2];
  const cands = [];
  for (let x = px0 - 1.5; x <= px1 + 1.5; x += .25) for (let y = py0 - 1.5; y <= py1 + 1.5; y += .25) {   // on the plaza or right by it
    if (V.ground && !V.ground(x, y)) continue;
    let ok = true; for (let a = 0; a < 8 && ok; a++) if (!V.free(x + Math.cos(a * Math.PI / 4) * .75, y + Math.sin(a * Math.PI / 4) * .75)) ok = false;
    if (!ok || !V.free(x, y)) continue;
    if ([0, 40, 80, 120, 150].some(z => hidden(x, y, z))) continue;
    // the fir may stand before a wide house but must not hide much of any building behind it (the town hall's tower with
    // its door and clock), nor a village button
    const fir = K.hull([...Array.from({length: 8}, (_, a) => pt(x + Math.cos(a * Math.PI / 4) * .7, y + Math.sin(a * Math.PI / 4) * .7, 0)), pt(x, y, 156)]);
    const over = roofs.some(r => r.fp[2] + r.fp[3] < x + y && K.covers(fir, r.hull) > .2);
    if (over) continue;
    if (V.clear && !V.clear(x, y, 70, 80)) continue;
    if (K.onPath(x - .3, y - .3, .6, .6, 0)) continue;   // the player's paths do not cross the tub
    cands.push([Math.hypot(x - mid[0], y - mid[1]), x, y]);
  }
  cands.sort((a, b) => a[0] - b[0] || a[1] - b[1] || a[2] - b[2]);
  if (!cands.length) problems.push('new_year: no free place for the fir');
  const [, fx, fy] = cands[0] || [0, mid[0], mid[1]], base = pt(fx, fy);
  s.shadow(base.x, base.y, 34, 13);
  B.cyl(s, fx, fy, .24, 0, 10, '#c98a5a', '#a8714a');                                            // tub
  B.L(s, fx - .17, fy + .17, 4, fx + .17, fy + .17, 4, '#8a5a3a', 1.2);
  s.line(base.x, base.y - 10, base.x, base.y - 22, '#8a6c4c', 5);
  // four tiers, each a skirt with a scalloped hem: lit left half, shaded right half, snow tufts along the hem
  const tierPts = [];
  for (const [b, w, t] of [[-22, 44, -66], [-50, 36, -94], [-76, 28, -118], [-100, 20, -140]]) {
    const hem = [], n = Math.round(w / 6);
    for (let i = 0; i <= n; i++) { const u = i / n, x = base.x - w + 2 * w * u, d = 6 * Math.sin(Math.PI * u);   // the hem bows towards the viewer
      hem.push({x, y: base.y + b + d}); if (i < n) hem.push({x: x + w / n, y: base.y + b + d + 3.2}) }
    const mid = hem.findIndex(p => p.x >= base.x);
    s.poly([{x: base.x, y: base.y + t}, ...hem.slice(0, mid + 1)], '#7da073');
    s.poly([{x: base.x, y: base.y + t}, ...hem.slice(mid)], '#64895f');
    s.poly([{x: base.x, y: base.y + t}, {x: base.x - w * .45, y: base.y + b + 1}, {x: base.x - w * .2, y: base.y + b + 3}], '#8db27f');   // light streak
    hem.forEach((p, i) => { if (i % 4 === 0 && i < hem.length - 1 && p.x < base.x + w * .3) s.ellipse(p.x + w / n * .5, p.y - 1, w / n * .5, 1.5, '#eef3f4') });
    tierPts.push([b, w, t]);
  }
  // baubles, empty hooks for named toys, a garland of lights in a spiral
  const BAUBLE = ['#d9553f', '#e8c25a', '#7fa3c4', '#e7a8b5', '#f4ede0'], lights = [], hooks = [];   // hooks: empty loops for the named toys
  tierPts.forEach(([b, w], k) => {
    for (let i = -2; i <= 2; i++) { const x = base.x + i * w * .32, y = base.y + b - 8 - Math.abs(i) * 2; if ((i + k) % 2 === 0) { s.ellipse(x, y + 4, 3.2, 3.2, BAUBLE[(i + k + 4) % 5]); s.ellipse(x - 1, y + 3, 1, 1, '#ffffff99') }
      else { hooks.push([x, y + 4]); s.line(x, y, x, y + 2, '#d9a650', .8); s.ellipse(x, y + 4, 2.2, 2.2, 'none'); c.beginPath(); c.ellipse(x, y + 4, 2.2, 2.2, 0, 0, Math.PI * 2); c.strokeStyle = '#d9a650'; c.lineWidth = .9; c.stroke() } }
    for (let i = 0; i < 7; i++) { const t = i / 6, x = base.x - w * .8 + w * 1.6 * t, y = base.y + b - 4 - 8 * t; lights.push([x, y, BULBS[(i + k) % BULBS.length]]); s.ellipse(x, y, 1.4, 1.4, BULBS[(i + k) % BULBS.length]) }
  });
  const star = {x: base.x, y: base.y - 146};
  const firHull = K.hull([...tierPts.flatMap(([b, w]) => [{x: base.x - w, y: base.y + b}, {x: base.x + w, y: base.y + b}]), {x: base.x, y: base.y + 6}, {x: star.x, y: star.y - 8}]);
  const notBehindFir = ([, X, Y]) => !K.inHull(firHull, {x: X, y: Y});
  s.poly(Array.from({length: 10}, (_, i) => { const a = -Math.PI / 2 + i * Math.PI / 5, r = i % 2 ? 3.4 : 8; return {x: star.x + Math.cos(a) * r, y: star.y + Math.sin(a) * r} }), '#f0c95a');
  // presents under the fir
  for (const [dx, dy, col, rib] of [[.42, -.05, '#d9553f', '#f4ede0'], [.36, .4, '#7fa3c4', '#e8c25a'], [.05, .48, '#8fae86', '#d9553f']]) {
    if (!V.free(fx + dx, fy + dy) || [0, 7].some(z => hidden(fx + dx, fy + dy, z)) || K.onPath(fx + dx - .12, fy + dy - .12, .24, .24, 0)) continue;
    B.fullBox(s, col, fx + dx - .12, fy + dy - .12, fx + dx + .12, fy + dy + .12, 0, 7, col); B.L(s, fx + dx, fy + dy + .12, 0, fx + dx, fy + dy + .12, 7, rib, 1.4) }
  // the snowman by the well, and a bullfinch on his broom
  const well = V.wells.find(([x, y]) => x > px0 && x < px1 && y > py0 && y < py1) || V.wells[0];
  const around = Array.from({length: 12}, (_, i) => [well[0] + Math.cos(i * Math.PI / 6) * 1.05, well[1] + Math.sin(i * Math.PI / 6) * 1.05])
    .sort((a, b) => (b[0] + b[1]) - (a[0] + a[1]) || a[0] - b[0]);
  const sm = around.find(([x, y]) => V.free(x, y) && !hidden(x, y, 40) && Math.hypot(x - fx, y - fy) > 1.4);
  if (!sm) problems.push('new_year: no place for the snowman');
  else {
    const q = pt(...sm); s.shadow(q.x, q.y, 12, 5);
    s.ellipse(q.x, q.y - 7, 10, 8.5, '#f4f7f8'); s.ellipse(q.x - 2, q.y - 9, 4, 3, '#ffffff');
    s.ellipse(q.x, q.y - 21, 7.5, 6.5, '#f4f7f8'); s.ellipse(q.x, q.y - 32, 5.6, 5.2, '#f4f7f8');
    s.line(q.x - 5, q.y - 27, q.x + 5, q.y - 25, '#d9553f', 3); s.line(q.x + 3, q.y - 26, q.x + 5, q.y - 18, '#d9553f', 2.6);     // scarf
    s.poly([{x: q.x + 1, y: q.y - 33}, {x: q.x + 9, y: q.y - 31.6}, {x: q.x + 1, y: q.y - 30.6}], '#e8955a');            // carrot
    s.ellipse(q.x - 1.6, q.y - 34.6, .9, .9, '#3d4a3f'); s.ellipse(q.x + 1.8, q.y - 34.6, .9, .9, '#3d4a3f');
    s.poly([{x: q.x - 6, y: q.y - 37}, {x: q.x + 6, y: q.y - 37}, {x: q.x + 4.6, y: q.y - 44}, {x: q.x - 4.6, y: q.y - 44}], '#7fa3c4');   // bucket hat
    s.line(q.x - 7, q.y - 21, q.x - 15, q.y - 30, '#8a6c4c', 1.8); s.line(q.x + 7, q.y - 21, q.x + 15, q.y - 27, '#8a6c4c', 1.8);
    for (const dy of [-18, -14, -10]) s.ellipse(q.x, q.y + dy, 1, 1, '#3d4a3f');
    // bullfinch: grey back, rose breast, black cap, on the right twig
    const b = {x: q.x + 15, y: q.y - 30};
    s.ellipse(b.x, b.y, 3.6, 3, '#8f949c'); s.ellipse(b.x + 1, b.y + .8, 2.8, 2.2, '#d9655a'); s.ellipse(b.x + 2.4, b.y - 2.4, 2, 1.9, '#2f3338');
    s.poly([{x: b.x + 4, y: b.y - 2.6}, {x: b.x + 5.8, y: b.y - 2}, {x: b.x + 4, y: b.y - 1.4}], '#3d4a3f'); s.poly([{x: b.x - 3, y: b.y}, {x: b.x - 6.6, y: b.y + 1.6}, {x: b.x - 3, y: b.y + 1.6}], '#2f3338');
  }
  // plaids on the plaza benches by the fir
  V.benches.slice(0, 2).forEach((bn, k) => K.benchPlaid(bn, [['#c97a6a', '#efe0c4', '#9b5a4c'], ['#7fa3c4', '#eef2f4', '#5f7f9a']][k]));
  K.smoke();
  c.end();

  c.group('vf-day');
  K.windowsDay(notBehindFir);
  c.end();
  c.group('vf-night');
  K.windowsNight(notBehindFir);
  for (const [q, col] of ridgeBulbs) { s.ellipse(q.x, q.y, 3.4, 3.4, 'rgba(255,214,130,.3)'); s.ellipse(q.x, q.y, 1.4, 1.4, col) }
  for (const [x, y, col] of lights) { s.ellipse(x, y, 3.6, 3.6, 'rgba(255,214,130,.32)'); s.ellipse(x, y, 1.5, 1.5, col) }
  s.ellipse(star.x, star.y, 16, 14, 'rgba(255,214,130,.3)');
  s.poly(Array.from({length: 10}, (_, i) => { const a = -Math.PI / 2 + i * Math.PI / 5, r = i % 2 ? 3.4 : 8; return {x: star.x + Math.cos(a) * r, y: star.y + Math.sin(a) * r} }), '#ffe7a0');
  c.end();
  // world units (2400x1800) for the client: where the fir stands and where a named toy (fest_ny_toy) can hang
  const [ma, , , md, me, mf] = V.matrix, W = ([x, y]) => [Math.round(ma * x + me), Math.round(md * y + mf)];
  return {svg: K.wrap(), problems, fir: W([base.x, base.y]), hooks: hooks.map(W), snow};
}
