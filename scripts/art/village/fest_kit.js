// Shared tools of the village festival layers (fest_<id>.js): the recorder and scene object, occlusion against tall objects,
// and the pieces several festivals hang the same way — plaids over rails and benches, garlands between plaza lamps,
// window light by day and at night, chimney smoke. Units: tile coordinates of the scene, farm px heights (see village.js).
import {FarmScene} from '/static/scene.js';
import {SvgCtx} from './svg_ctx.js';

export function festKit(V, name) {
  const {B, P} = V, c = new SvgCtx('vf'), s = Object.create(FarmScene.prototype);
  s.c = c; s.time = 0; s.motion = false; s.inStatic = true; s.shadowLevel = 0;
  const problems = [];
  const pt = (x, y, z = 0) => P(x, y, z);
  const quad = (pts, fill) => s.poly(pts.map(([x, y, z]) => pt(x, y, z)), fill);
  // occlusion: a point of the layer (tile x, y, height z) is hidden when a taller object standing in front of it covers it
  // on screen. The layer is drawn over the art, so such points must not get decor.
  const hull = pts => { pts = [...pts].sort((p, q) => p.x - q.x || p.y - q.y); const cr = (o, a, b) => (a.x - o.x) * (b.y - o.y) - (a.y - o.y) * (b.x - o.x);
    const lo = [], up = []; for (const p of pts) { while (lo.length > 1 && cr(lo[lo.length - 2], lo[lo.length - 1], p) <= 0) lo.pop(); lo.push(p) }
    for (const p of [...pts].reverse()) { while (up.length > 1 && cr(up[up.length - 2], up[up.length - 1], p) <= 0) up.pop(); up.push(p) }
    return lo.slice(0, -1).concat(up.slice(0, -1)) };
  const tall = V.tall.map(({r: [x0, y0, x1, y1], h}) => ({r: [x0, y0, x1, y1], front: x1 + y1, h: hull([[x0, y0], [x1, y0], [x1, y1], [x0, y1]].flatMap(([x, y]) => [pt(x, y, 0), pt(x, y, h)]))}));
  const inHull = (h, p) => h.every((a, i) => { const b = h[(i + 1) % h.length]; return (b.x - a.x) * (p.y - a.y) - (b.y - a.y) * (p.x - a.x) >= 0 });
  // skip(r): leave an object out (a roof's own building)
  const hidden = (x, y, z, skip) => { const q = pt(x, y, z); return tall.some(o => o.front > x + y + .05 && !(skip && skip(o.r)) && inHull(o.h, q)) };
  const visible = (x, y, z, what) => { if (hidden(x, y, z)) { problems.push(`${name}: ${what} hidden behind a building`); return false } return true };

  // houses as their screen silhouettes (walls from the ground, the recorded roof over them): what a decor must not hide
  const houses = (V.roofs || []).map(([kind, a, g]) => {
    const [x0, y0, x1, y1, zE, top, ov] = kind === 'gable' ? [g.x0, g.y0, g.x1, g.y1, g.zE, g.zE + Math.max(...g.prof.map(p => p[1])) * g.R, g.ov] : [a[0], a[1], a[2], a[3], a[4], a[4] + a[5], a[7]];
    const ring = [[x0 - ov, y0 - ov], [x1 + ov, y0 - ov], [x1 + ov, y1 + ov], [x0 - ov, y1 + ov]];
    return {fp: [x0, y0, x1, y1], hull: hull([...ring.flatMap(([x, y]) => [pt(x, y, 0), pt(x, y, zE)]), pt((x0 + x1) / 2, (y0 + y1) / 2, top)])};
  });
  // share of polygon b's area that polygon a covers on screen (grid samples)
  const covers = (a, b) => { const xs = b.map(p => p.x), ys = b.map(p => p.y); let n = 0, k = 0;
    for (let X = Math.min(...xs); X <= Math.max(...xs); X += 3) for (let Y = Math.min(...ys); Y <= Math.max(...ys); Y += 3) {
      const q = {x: X, y: Y}; if (!inHull(b, q)) continue; n++; if (inHull(a, q)) k++ }
    return n ? k / n : 0 };
  // a free place for a decor box w×d (tiles) h px tall inside `area`, nearest to `near`: on free ground, not under anything
  // taller in front, hiding at most `cover` of a house behind it, clear of the village buttons; taken for the next decor
  // the walk graph against a decor footprint (x, y, w×d tiles, m tiles around it): the player's figure must not walk through it
  // (the figure is a DOM layer over the whole village, so passing behind a decor is drawn like passing behind a house)
  const onPath = (x, y, w, d, m = .1) => (V.walk || []).some(([ax, ay, bx, by]) => { const n = Math.ceil(Math.hypot(bx - ax, by - ay) / .1);
    for (let i = 0; i <= n; i++) { const qx = ax + (bx - ax) * i / n, qy = ay + (by - ay) * i / n; if (qx > x - m && qx < x + w + m && qy > y - m && qy < y + d + m) return true }
    return false });
  const taken = [], sils = [], small = tall.filter(o => !houses.some(hs => hs.fp[0] > o.r[0] - .01 && hs.fp[2] < o.r[2] + .01 && hs.fp[1] > o.r[1] - .01 && hs.fp[3] < o.r[3] + .01));
  const place = ({w, d, h, near, area = V.plaza, cover = .2, button = 80, margin = .1, path = .1, what}) => {
    const cands = [];
    for (let x = area[0]; x <= area[2] - w; x += .25) for (let y = area[1]; y <= area[3] - d; y += .25) {
      let ok = !taken.some(([a, b, c2, d2]) => x < c2 + margin && x + w > a - margin && y < d2 + margin && y + d > b - margin);
      for (let u = 0; u <= 1 && ok; u += .25) for (let v = 0; v <= 1 && ok; v += .25) { const px = x - margin + (w + 2 * margin) * u, py = y - margin + (d + 2 * margin) * v;
        if (!V.free(px, py) || V.ground && !V.ground(px, py)) ok = false }
      if (!ok) continue;
      const corners = [[x, y], [x + w, y], [x + w, y + d], [x, y + d]];
      let seen = true;   // the whole box in view: footprint samples at the foot, the middle and the top
      for (let u = 0; u <= 1 && seen; u += .25) for (let v = 0; v <= 1 && seen; v += .5) if ([0, h / 2, h].some(z => hidden(x + w * u, y + d * v, z))) seen = false;
      if (!seen) continue;
      const sil = hull(corners.flatMap(([cx, cy]) => [pt(cx, cy, 0), pt(cx, cy, h)]));
      if (houses.some(o => o.fp[2] + o.fp[3] < x + w + y + d && covers(sil, o.hull) > cover)) continue;
      if (small.some(o => o.front < x + w + y + d && covers(sil, o.h) > cover)) continue;   // stalls, wells, the gazebo behind it
      if (sils.some(o => covers(sil, o) > .02 || covers(o, sil) > .02)) continue;
      if (onPath(x, y, w, d, path)) continue;                  // nor over another decor of the layer
      if ((V.lamps || []).some(([lx, ly]) => [8, 24, 40, 46].some(z => inHull(sil, pt(lx, ly, z))))) continue;   // nor over a lamp post
      if (V.clear && !V.clear(x + w / 2, y + d / 2, h / 2, button)) continue;
      if ((V.avoid || []).some(([a0, b0, a1, b1]) => sil.some(p => p.x > a0) && sil.some(p => p.x < a1) && sil.some(p => p.y > b0) && sil.some(p => p.y < b1))) continue;   // DOM plates (farm px)
      cands.push([Math.hypot(x + w / 2 - near[0], y + d / 2 - near[1]), x, y]);
    }
    cands.sort((a, b) => a[0] - b[0] || a[1] - b[1] || a[2] - b[2]);
    if (!cands.length) { problems.push(`${name}: no place for the ${what}`); return null }
    const [, x, y] = cands[0]; taken.push([x, y, x + w, y + d]);
    sils.push(hull([[x, y], [x + w, y], [x + w, y + d], [x, y + d]].flatMap(([cx, cy]) => [pt(cx, cy, 0), pt(cx, cy, h)]))); return [x, y];
  };
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
  // a plaid laid on a plaza bench (axis x or y), hanging down its front
  const benchPlaid = ([x, y, axis], [base, light, dark]) => {
    if (axis === 'x') { quad([[x - .22, y - .12, 8.6], [x + .1, y - .12, 8.6], [x + .1, y + .12, 8.6], [x - .22, y + .12, 8.6]], base);
      quad([[x - .22, y + .12, 8.6], [x + .1, y + .12, 8.6], [x + .1, y + .12, 3], [x - .22, y + .12, 3]], dark);
      quad([[x - .08, y - .12, 8.7], [x - .03, y - .12, 8.7], [x - .03, y + .12, 3], [x - .08, y + .12, 3]], light) }
    else { quad([[x - .12, y - .2, 8.6], [x + .12, y - .2, 8.6], [x + .12, y + .12, 8.6], [x - .12, y + .12, 8.6]], base);
      quad([[x + .12, y - .2, 8.6], [x + .12, y + .12, 8.6], [x + .12, y + .12, 3], [x + .12, y - .2, 3]], dark);
      quad([[x - .12, y - .05, 8.7], [x + .12, y - .05, 8.7], [x + .12, y - .01, 3], [x + .12, y - .01, 8.7]], light) }
  };
  // a garland between two lamp heads (z 44) sagging a little; pennant(p, q, i) draws one piece between the string points p and q
  const garland = (a, b, pennant, string = '#8a6c4c', step = 15) => {
    const A = pt(a[0], a[1], 44), Bp = pt(b[0], b[1], 44), L = Math.hypot(Bp.x - A.x, Bp.y - A.y), sag = L * .1;
    const at = t => ({x: A.x + (Bp.x - A.x) * t, y: A.y + (Bp.y - A.y) * t + 4 * sag * t * (1 - t)});
    c.beginPath(); c.moveTo(A.x, A.y); c.quadraticCurveTo((A.x + Bp.x) / 2, (A.y + Bp.y) / 2 + 2 * sag, Bp.x, Bp.y);
    c.strokeStyle = string; c.lineWidth = 1; c.stroke();
    const n = Math.max(4, Math.round(L / step)), out = [];
    for (let i = 1; i < n; i++) { const p = at(i / n), q = at(i / n + .4 / n); pennant(p, q, i); out.push(p) }
    return out;
  };
  // pairs of lamps by the plaza, 4–11 tiles apart, whose garland nothing stands in front of; the longest `max` without a shared lamp
  const lampPairs = max => {
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
    for (const [, a, b] of pairs) { if (chosen.length >= max || used.has(a) || used.has(b)) continue; chosen.push([a, b]); used.add(a); used.add(b) }
    if (!chosen.length) problems.push(`${name}: no clear place for a garland`);
    return chosen;
  };
  // the two garden fences nearest the plaza (by the residents' houses, not the field fences), straight along x, in view
  const gardenFences = n => {
    const [cx, cy] = [(V.plaza[0] + V.plaza[2]) / 2, (V.plaza[1] + V.plaza[3]) / 2];
    return V.fences.filter(f => Math.abs(f[1] - f[3]) < .01 && Math.abs(f[2] - f[0]) >= 1.6 && !hidden((f[0] + f[2]) / 2, f[1], 6))
      .sort((a, b) => Math.hypot((a[0] + a[2]) / 2 - cx, a[1] - cy) - Math.hypot((b[0] + b[2]) / 2 - cx, b[1] - cy)).slice(0, n);
  };
  // cosy smoke: three soft puffs over every chimney (the game animates vf-s1..3 rising, unless motion is reduced)
  const smoke = () => {
    for (let i = 1; i <= 3; i++) {
      c.group(`vf-smoke vf-s${i}`);
      for (const [x, y] of V.chimneys) s.ellipse(x + i * 1.5, y - 6 - i * 9, 3 + i * 1.6, 2.4 + i * 1.2, 'rgba(250,246,234,.5)');
      c.end();
    }
  };
  const glass = ([kind, X, Y, w, h], grow = 0) => {   // the glass parallelogram of a window in its wall plane
    const ax = (kind === 'a' ? 18 : -18) * w, ay = 9 * w, hh = h / 2 + grow;
    return [{x: X - ax - grow, y: Y - ay - hh}, {x: X + ax + grow, y: Y + ay - hh}, {x: X + ax + grow, y: Y + ay + hh}, {x: X - ax - grow, y: Y - ay + hh}];
  };
  // keep(w): leave out windows the layer's own decor stands in front of
  const windowsDay = (keep = () => true) => { for (const w of V.windows.filter(keep)) s.poly(glass(w), 'rgba(255,214,130,.5)') };
  const windowsNight = (keep = () => true) => { for (const w of V.windows.filter(keep)) { s.poly(glass(w, 3), 'rgba(255,200,95,.22)'); s.poly(glass(w), 'rgba(255,226,160,.85)') } };
  // a soft glow above the night tint
  const glow = (x, y, z, r = 22) => { const q = pt(x, y, z); s.ellipse(q.x, q.y, r, r * .64, 'rgba(255,200,95,.22)'); s.ellipse(q.x, q.y, r * .4, r * .32, 'rgba(255,220,140,.35)') };
  const wrap = () => {
    const m = V.matrix.map(v => +v.toFixed(4)).join(' ');
    return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 2400 1800" class="vf-art" aria-hidden="true" focusable="false">` +
      `<g transform="matrix(${m})">${c.svg()}</g></svg>`;
  };
  return {B, P, c, s, pt, quad, hull, inHull, hidden, visible, houses, covers, place, taken, onPath, problems, plaid, benchPlaid, garland, lampPairs, gardenFences, smoke, glass,
    windowsDay, windowsNight, glow, wrap};
}
