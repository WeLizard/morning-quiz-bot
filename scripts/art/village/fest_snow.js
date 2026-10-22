// Snow on the village ground for the winter festival layers (fest_newyear.js, fest_maslenitsa.js), vector, on a grid of
// diamonds: every tile is cut into n×n small diamonds, and a diamond takes snow when the ground there is bare in this
// render (V.bare: nothing painted over the ground tile — no house, tree, fence, field, water), a bluish one where only a
// shadow lies. Diamonds next to anything stay bare (thaw by the walls), and so does a ring under every tree; paths, lanes and the plaza get a thin
// trodden snow instead. Drifts of the same snow lie along the roads, trees, firs and bushes wear snow caps.
// The snow fades out under the world's edge shade like the art under it (V.edge). Night: the tint above it makes it blue.

const SNOW = '#f2f5f7', SHADE = '#dfe7ec', LIGHT = '#fbfcfd';

// deterministic value noise over the tile grid (cells of `size` tiles), 0..1
const h2 = (x, y, seed) => { const n = Math.sin(x * 127.1 + y * 311.7 + seed * 74.7) * 43758.5453; return n - Math.floor(n) };
const noise = (x, y, size, seed) => {
  const gx = x / size, gy = y / size, x0 = Math.floor(gx), y0 = Math.floor(gy), fx = gx - x0, fy = gy - y0, sm = t => t * t * (3 - 2 * t);
  const a = h2(x0, y0, seed), b = h2(x0 + 1, y0, seed), c = h2(x0, y0 + 1, seed), d = h2(x0 + 1, y0 + 1, seed), u = sm(fx), v = sm(fy);
  return a + (b - a) * u + (c - a) * v + (a - b - c + d) * u * v;
};

// opts: {cover: share of the grass under snow (1 = all), thaw: bare rim (small diamonds) around anything, under: ring
// (tiles) under trees, trodden: opacity of the snow on paths (0 = none), drifts, caps: snow on tree crowns and bushes}
export function snowCover(V, K, opts) {
  const {c, s, pt, hidden} = K, n = 3, cover = opts.cover ?? 1, thaw = opts.thaw ?? 1, under = opts.under ?? .55;
  const near = (V.trees || []).map(([x, y, k]) => [x, y, under * Math.max(.8, k)]);
  // the small diamonds: u, v on the n-times finer grid; bare when five points inside are bare ground
  const cells = new Map(), key = (u, v) => u * 100000 + v;
  // the class of a small diamond: 0 bare ground, 1 in a shadow, 2 something stands there (the worst of five points inside)
  const cellAt = (u, v) => {
    const k = key(u, v); if (cells.has(k)) return cells.get(k);
    const x = u / n, y = v / n, d = 1 / n;
    const cl = Math.max(...[[.5, .5], [.2, .2], [.8, .2], [.2, .8], [.8, .8]].map(([a, b]) => V.bare(x + a * d, y + b * d)));
    cells.set(k, cl); return cl;
  };
  const runs = {snow: [], shade: [], trodden: []};   // [v, u0, u1, fade bucket]
  for (let v = -60 * n; v < 110 * n; v++) {
    let cur = null;
    const flush = () => { if (cur) { runs[cur.kind].push([v, cur.u0, cur.u1, cur.fade]); cur = null } };
    for (let u = -60 * n; u < 110 * n; u++) {
      const x = (u + .5) / n, y = (v + .5) / n, e = V.edge(x, y);
      let kind = null;
      const cl = e > 0 ? cellAt(u, v) : 2;
      if (cl < 2) {
        const g = V.kind(x, y);
        if (g !== 'grass') kind = opts.trodden && cl === 0 ? 'trodden' : null;
        else {
          let rim = true;
          for (let du = -thaw; du <= thaw && rim; du++) for (let dv = -thaw; dv <= thaw && rim; dv++) if (cellAt(u + du, v + dv) === 2) rim = false;
          const tree = near.some(([tx, ty, r]) => Math.hypot(x - tx, y - ty) < r);
          const patch = cover >= 1 || noise(x, y, 3.2, 1) * .7 + noise(x, y, 1.1, 2) * .3 < cover;
          if (rim && !tree && patch) kind = cl ? 'shade' : 'snow';
        }
      }
      const fade = e >= 1 ? 3 : Math.floor(e * 3);
      if (cur && (cur.kind !== kind || cur.fade !== fade)) flush();
      if (kind) { if (cur) cur.u1 = u + 1; else cur = {kind, u0: u, u1: u + 1, fade} }
    }
    flush();
  }
  // the cells of one look (snow, shade or trodden; one edge-fade bucket) as outlines on the diamond grid: every cell edge
  // with no cell of the same look behind it, chained into loops (counter-clockwise in u, v, so holes come out reversed and
  // the default nonzero fill keeps them empty), points on straight runs dropped
  const strips = (list, fill) => {
    for (let f = 0; f <= 3; f++) {
      const set = new Set();
      for (const [v, u0, u1, ff] of list) if (ff === f) for (let u = u0; u < u1; u++) set.add(key(u, v));
      if (!set.size) continue;
      const out = new Map(), vk = (u, v) => `${u},${v}`, edge = (a, b) => { const k = vk(...a); (out.get(k) || out.set(k, []).get(k)).push(b) };
      for (const k of set) {
        const u = Math.round(k / 100000), v = k - u * 100000, has = (du, dv) => set.has(key(u + du, v + dv));
        if (!has(0, -1)) edge([u, v], [u + 1, v]);
        if (!has(1, 0)) edge([u + 1, v], [u + 1, v + 1]);
        if (!has(0, 1)) edge([u + 1, v + 1], [u, v + 1]);
        if (!has(-1, 0)) edge([u, v + 1], [u, v]);
      }
      c.beginPath();
      for (const start of [...out.keys()].sort()) {
        while ((out.get(start) || []).length) {
          const loop = [start.split(',').map(Number)];
          let at = start;
          for (;;) { const nx = out.get(at).pop(); at = vk(...nx); if (at === start) break; loop.push(nx) }
          const pts = loop.filter((p, i) => { const a = loop[(i + loop.length - 1) % loop.length], b = loop[(i + 1) % loop.length];
            return (p[0] - a[0]) * (b[1] - p[1]) !== (p[1] - a[1]) * (b[0] - p[0]) });
          pts.forEach(([u, v], i) => { const q = pt(u / n, v / n); i ? c.lineTo(q.x, q.y) : c.moveTo(q.x, q.y) }); c.closePath();
        }
      }
      c.fillStyle = fill(f); c.fill();
    }
  };
  const alpha = (a, f) => +(a * [.25, .5, .78, 1][f]).toFixed(2);
  strips(runs.snow, f => f === 3 ? SNOW : `rgba(242,245,247,${alpha(1, f)})`);
  strips(runs.shade, f => f === 3 ? SHADE : `rgba(223,231,236,${alpha(1, f)})`);   // snow in the shadows of houses and trees
  if (opts.trodden) strips(runs.trodden, f => `rgba(244,246,247,${alpha(opts.trodden, f)})`);
  const snowSet = new Set([...runs.snow, ...runs.shade].flatMap(([v, u0, u1]) => Array.from({length: u1 - u0}, (_, i) => key(u0 + i, v))));
  const snowAt = (x, y) => snowSet.has(key(Math.floor(x * n), Math.floor(y * n)));

  // drifts along the roads: grass tiles beside a road, snow all around, an elongated mound along the road
  let drifts = 0;
  if (opts.drifts) for (let x = -20; x < 70; x++) for (let y = -20; y < 70; y++) {
    if (V.kind(x + .5, y + .5) !== 'grass' || h2(x, y, 9) > opts.drifts) continue;
    const side = [[1, 0], [-1, 0], [0, 1], [0, -1]].find(([dx, dy]) => V.kind(x + .5 + dx, y + .5 + dy) === 'road');
    if (!side) continue;
    const cx = x + .5 - side[0] * .12, cy = y + .5 - side[1] * .12;   // on the grass, a little back from the road
    let ok = true; for (let a = -.3; a <= .3 && ok; a += .15) for (let b = -.3; b <= .3 && ok; b += .15) if (!snowAt(cx + a, cy + b)) ok = false;
    if (!ok) continue;
    // the mound lies along the road: a road along y runs down-left on screen (-26.6°), along x down-right (+26.6°)
    const p = pt(cx, cy), a = (side[0] ? -1 : 1) * Math.atan(.5), w = 11 + h2(x, y, 4) * 7;
    c.save(); c.translate(p.x, p.y); c.transform(Math.cos(a), Math.sin(a), -Math.sin(a), Math.cos(a), 0, 0);
    s.ellipse(1.5, 1.6, w, 4.6, SHADE); s.ellipse(0, 0, w * .92, 4.2, SNOW); s.ellipse(-w * .25, -1.2, w * .45, 1.8, LIGHT);
    c.restore(); drifts++;
  }

  // snow caps on tree crowns, firs and bushes that nothing stands in front of; one path per colour (thousands of trees)
  let caps = 0;
  if (opts.caps) {
    const shapes = {[SHADE]: [], [SNOW]: []}, r1 = Math.round;
    const blob = (col, x, y, rx, ry) => shapes[col].push(() => c.ellipse(r1(x), r1(y), r1(rx), r1(ry)));
    const poly = (col, pts) => shapes[col].push(() => { pts.forEach((q, i) => i ? c.lineTo(r1(q.x), r1(q.y)) : c.moveTo(r1(q.x), r1(q.y))); c.closePath() });
    const own = (x, y) => r => x > r[0] && x < r[2] && y > r[1] && y < r[3];
    for (const [x, y, k, pine] of V.trees || []) {
      if (hidden(x, y, 60 * k, own(x, y)) || hidden(x, y, 90 * k, own(x, y))) continue;
      const p = pt(x, y), at = (dx, dy) => ({x: p.x + dx * k, y: p.y + dy * k});   // crown px, scaled like the tree
      if (pine) {   // snow along each tier's hem (the V the farm's fir tiers end in), deeper on the lit side, and on the tip
        for (const [, w, b] of [[-62, 20, -12], [-78, 16, -32], [-92, 12, -50]])
          poly(SNOW, [at(-w, b), at(0, b + 3), at(w * .85, b + .5), at(w * .55, b - 1.6), at(0, b - .2), at(-w * .6, b - 3.6)]);
        poly(SNOW, [at(0, -92), at(-4, -83), at(2.6, -84)]);
      }
      else { const a = at(6, -55), b = at(-5, -60); blob(SHADE, a.x, a.y, 10 * k, 4.4 * k); blob(SNOW, b.x, b.y, 13 * k, 6 * k) }
      caps++;
    }
    for (const [x, y] of V.bushes || []) {
      if (hidden(x, y, 10)) continue;
      const p = pt(x, y); blob(SNOW, p.x - 1, p.y - 11.6, 5, 2.4); blob(SNOW, p.x + 4, p.y - 8.6, 4.4, 2); blob(SNOW, p.x - 5.6, p.y - 7.6, 3.8, 1.8);
      caps++;
    }
    for (const col of [SHADE, SNOW]) { c.beginPath(); shapes[col].forEach(f => f()); c.fillStyle = col; c.fill() }
  }
  return {snow: runs.snow.length + runs.shade.length, trodden: runs.trodden.length, drifts, caps};
}
