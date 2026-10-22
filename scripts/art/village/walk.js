// Walk graph of the village: where the player may go. Built from the same plan the scene is painted from
// (road / lane / plaza rectangles in tile space, the bridge deck) and checked against what stands on the ground
// (claimed footprints of buildings and props, trees, fences, water). Output is in village world units (2400x1800).
// Format: README.md, «Граф проходимости».

const EPS = 1e-6, STEP = 2, REACH = 1.6, SAMPLE = .1;

export function buildWalk(V) {
  // V: {toWorld(x,y) -> [X,Y], toTile(X,Y) -> [x,y], roads, lanes, plaza, bridges, occupied:[{r:[x0,y0,x1,y1],tag}],
  //     trees:[[x,y,k]], fences:[[x1,y1,x2,y2]], inWater(x,y), targets:{name:[X,Y]}}
  const inR = (x, y, r, m = 0) => x > r[0] - m && x < r[2] + m && y > r[1] - m && y < r[3] + m;
  const onBridge = (x, y) => V.bridges.some(r => inR(x, y, r, .05));
  const segDist = (px, py, [x1, y1, x2, y2]) => {
    const dx = x2 - x1, dy = y2 - y1, t = Math.max(0, Math.min(1, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy || 1)));
    return Math.hypot(px - x1 - t * dx, py - y1 - t * dy);
  };
  const solid = V.occupied.filter(o => o.tag !== 'spot' && o.tag !== 'tree');
  const why = (x, y) => {
    for (const o of solid) if (inR(x, y, o.r, .12)) return o.tag || 'object';
    for (const [tx, ty, k] of V.trees) if (Math.hypot(x - tx, y - ty) < .3 * (k || 1)) return 'tree';
    for (const f of V.fences) if (segDist(x, y, f) < .15) return 'fence';
    if (V.inWater(x, y) && !onBridge(x, y)) return 'water';
    return null;
  };
  const free = (x, y) => !why(x, y);
  const clear = (a, b) => {
    const n = Math.max(1, Math.ceil(Math.hypot(b[0] - a[0], b[1] - a[1]) / SAMPLE));
    for (let i = 0; i <= n; i++) if (!free(a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n)) return false;
    return true;
  };
  const inView = (x, y) => { const [X, Y] = V.toWorld(x, y); return X >= 8 && X <= 2392 && Y >= 8 && Y <= 1792 };
  // free-ground raster (CELL tiles) over the visible world, for routes across the grass to doors and signs
  const CELL = .25, corners = [[0, 0], [2400, 0], [0, 1800], [2400, 1800]].map(([X, Y]) => V.toTile(X, Y));
  const gx0 = Math.floor(Math.min(...corners.map(c => c[0]))), gy0 = Math.floor(Math.min(...corners.map(c => c[1])));
  const GW = Math.ceil((Math.max(...corners.map(c => c[0])) - gx0) / CELL) + 1, GH = Math.ceil((Math.max(...corners.map(c => c[1])) - gy0) / CELL) + 1;
  const cellPt = c => [gx0 + (c % GW) * CELL, gy0 + Math.floor(c / GW) * CELL];
  const cellOf = (x, y) => Math.round((y - gy0) / CELL) * GW + Math.round((x - gx0) / CELL);
  const blocked = new Uint8Array(GW * GH);
  const mark = (x0, y0, x1, y1, test) => {
    for (let cy = Math.max(0, Math.floor((y0 - gy0) / CELL)); cy <= Math.min(GH - 1, Math.ceil((y1 - gy0) / CELL)); cy++)
      for (let cx = Math.max(0, Math.floor((x0 - gx0) / CELL)); cx <= Math.min(GW - 1, Math.ceil((x1 - gx0) / CELL)); cx++) {
        const c = cy * GW + cx, [x, y] = cellPt(c); if (!blocked[c] && test(x, y)) blocked[c] = 1;
      }
  };
  for (const o of solid) mark(o.r[0] - .3, o.r[1] - .3, o.r[2] + .3, o.r[3] + .3, (x, y) => inR(x, y, o.r, .12 + CELL));
  for (const [tx, ty, k] of V.trees) { const r = .3 * (k || 1) + CELL; mark(tx - r, ty - r, tx + r, ty + r, (x, y) => Math.hypot(x - tx, y - ty) < r) }
  for (const f of V.fences) mark(Math.min(f[0], f[2]) - .4, Math.min(f[1], f[3]) - .4, Math.max(f[0], f[2]) + .4, Math.max(f[1], f[3]) + .4, (x, y) => segDist(x, y, f) < .15 + CELL);
  for (let c = 0; c < GW * GH; c++) { const [x, y] = cellPt(c); if (!blocked[c] && (!inView(x, y) || V.inWater(x, y) && !onBridge(x, y))) blocked[c] = 1 }
  // silhouettes: ground a tall object hides on screen (behind a house). The player is drawn over the art, so a route there
  // would look like walking over the roof; grass routes avoid it (roads keep their course).
  const hull = pts => { pts = [...pts].sort((p, q) => p.x - q.x || p.y - q.y); const cr = (o, a, b) => (a.x - o.x) * (b.y - o.y) - (a.y - o.y) * (b.x - o.x);
    const lo = [], up = []; for (const p of pts) { while (lo.length > 1 && cr(lo[lo.length - 2], lo[lo.length - 1], p) <= 0) lo.pop(); lo.push(p) }
    for (const p of [...pts].reverse()) { while (up.length > 1 && cr(up[up.length - 2], up[up.length - 1], p) <= 0) up.pop(); up.push(p) }
    return lo.slice(0, -1).concat(up.slice(0, -1)) };
  const inHull = (h, p) => h.every((a, i) => { const b = h[(i + 1) % h.length]; return (b.x - a.x) * (p.y - a.y) - (b.y - a.y) * (p.x - a.x) >= 0 });
  for (const o of solid) if (o.h >= 20) {
    const [x0, y0, x1, y1] = o.r, base = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]];
    const H = hull(base.flatMap(([x, y]) => [V.toScreen(x, y, 0), V.toScreen(x, y, o.h)]));
    // candidates: ground behind the object (smaller x + y), within the screen height it covers
    const reach = o.h / 18 + 1;
    mark(x0 - reach, y0 - reach, x1, y1, (x, y) => inHull(H, V.toScreen(x, y, 0)));
  }
  const gridClear = (a, b) => { const n = Math.max(1, Math.ceil(Math.hypot(b[0] - a[0], b[1] - a[1]) / (CELL / 2)));
    for (let i = 1; i < n; i++) if (blocked[cellOf(a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n)]) return false; return true };
  // breadth-first route over free cells from `from` to the first cell `goal(x, y)` accepts; returned straightened
  const route = (from, goal) => {
    const start = cellOf(...from), prev = new Int32Array(GW * GH).fill(-2), q = [start];
    if (start < 0 || start >= GW * GH) return null;
    prev[start] = -1;
    for (let k = 0; k < q.length; k++) {
      const c = q[k], [x, y] = cellPt(c);
      if (k && goal(x, y)) { const path = []; for (let i = c; i >= 0; i = prev[i]) path.push(cellPt(i)); path.reverse(); path[0] = from; return pull(path) }
      const cx = c % GW, cy = Math.floor(c / GW);
      for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1], [1, 1], [1, -1], [-1, 1], [-1, -1]]) {
        const nx = cx + dx, ny = cy + dy, n = ny * GW + nx;
        if (nx < 0 || ny < 0 || nx >= GW || ny >= GH || prev[n] !== -2 || blocked[n]) continue;
        prev[n] = c; q.push(n);
      }
    }
    return null;
  };
  // string pulling: keep only the corners the straight segments need (each segment checked exactly)
  const pull = path => {
    const out = [path[0]];
    for (let i = 0; i < path.length - 1;) {
      let j = path.length - 1;
      while (j > i + 1 && !(clear(path[i], path[j]) && gridClear(path[i], path[j]))) j--;
      out.push(path[j]); i = j;
    }
    return out;
  };

  // 1. centre lines: roads and lanes along their long side, a 1.5-tile grid over the plaza
  const lines = [];
  const along = r => (r[2] - r[0]) >= (r[3] - r[1]) ? {h: true, c: (r[1] + r[3]) / 2, a: r[0], b: r[2]} : {h: false, c: (r[0] + r[2]) / 2, a: r[1], b: r[3]};
  for (const r of [...V.roads, ...V.lanes]) lines.push(along(r));
  const [p0, , p1] = V.plaza, grid = [];
  for (let v = p0 + .75; v < p1; v += 1.5) grid.push(v);
  for (const v of grid) { lines.push({h: true, c: v, a: grid[0], b: grid[grid.length - 1]}); lines.push({h: false, c: v, a: grid[0], b: grid[grid.length - 1]}) }
  const pt = (L, t) => L.h ? [t, L.c] : [L.c, t];
  // 2. dangling ends run on to the nearest crossing line within reach (a lane meets the road's centre, a road meets the plaza grid)
  for (const L of lines) for (const end of ['a', 'b']) {
    const dir = end === 'a' ? -1 : 1, t0 = L[end];
    let best = null;
    for (const M of lines) if (M.h !== L.h && M.a - EPS <= L.c && L.c <= M.b + EPS) {
      const d = (M.c - t0) * dir;
      if (d > -EPS && d <= REACH && (!best || d < best)) best = d;
    }
    if (best) L[end] = t0 + dir * best;
  }
  // 3. break points: ends, crossings and every STEP tiles; nodes keyed by position
  const nodes = [], key = new Map(), edges = new Set();
  const node = (x, y) => { const k = `${x.toFixed(3)},${y.toFixed(3)}`; if (!key.has(k)) { key.set(k, nodes.length); nodes.push([x, y]) } return key.get(k) };
  const edge = (i, j) => { if (i !== j) edges.add(i < j ? `${i},${j}` : `${j},${i}`) };
  let dropped = 0;
  for (const L of lines) {
    const ts = new Set([L.a, L.b]);
    for (let t = Math.ceil(L.a / STEP) * STEP; t < L.b; t += STEP) ts.add(t);
    for (const M of lines) if (M.h !== L.h && M.a - EPS <= L.c && L.c <= M.b + EPS && M.c > L.a - EPS && M.c < L.b + EPS) ts.add(M.c);
    const sorted = [...ts].sort((p, q) => p - q);
    for (let i = 0; i + 1 < sorted.length; i++) {
      const a = pt(L, sorted[i]), b = pt(L, sorted[i + 1]);
      if (!inView(...a) || !inView(...b)) continue;
      if (clear(a, b)) edge(node(...a), node(...b)); else dropped++;
    }
  }
  // 4. adjacency helpers
  const adj = () => { const m = nodes.map(() => []); for (const e of edges) { const [i, j] = e.split(',').map(Number); m[i].push(j); m[j].push(i) } return m };
  const comps = () => {
    const m = adj(), seen = new Array(nodes.length).fill(-1), out = [];
    for (let s = 0; s < nodes.length; s++) if (seen[s] < 0 && m[s].length) {
      const c = [s]; seen[s] = out.length;
      for (let k = 0; k < c.length; k++) for (const n of m[c[k]]) if (seen[n] < 0) { seen[n] = out.length; c.push(n) }
      out.push(c);
    }
    return out.sort((p, q) => q.length - p.length);
  };
  // link a point to the network: split the nearest edge whose straight connector is clear
  const splitTo = (p, maxD = 6, only = null) => {
    const cand = [];
    for (const e of edges) {
      const [i, j] = e.split(',').map(Number), [ax, ay] = nodes[i], [bx, by] = nodes[j], dx = bx - ax, dy = by - ay;
      if (only && !only.has(i)) continue;
      const t = Math.max(0, Math.min(1, ((p[0] - ax) * dx + (p[1] - ay) * dy) / (dx * dx + dy * dy)));
      const q = [ax + t * dx, ay + t * dy];
      cand.push([Math.hypot(q[0] - p[0], q[1] - p[1]), e, t, q]);
    }
    cand.sort((u, v) => u[0] - v[0] || (u[1] < v[1] ? -1 : 1));
    for (const [d, e, t, q] of cand) {
      if (d > maxD) break;
      if (!clear(p, q)) continue;
      const [i, j] = e.split(',').map(Number);
      if (t < .02) return i;
      if (t > .98) return j;
      const k = node(...q); edges.delete(e); edge(i, k); edge(k, j); return k;
    }
    return -1;
  };
  // 5. join stray pieces (an isolated lane) to the main network across the grass, by the shortest clear link
  const problems = [];
  for (let guard = 0; guard < 20; guard++) {
    const cs = comps();
    if (cs.length < 2) break;
    const main = new Set(cs[0]), other = cs[1];
    let best = null;
    for (const i of other) for (const j of main) {
      const d = Math.hypot(nodes[i][0] - nodes[j][0], nodes[i][1] - nodes[j][1]);
      if (d < 8 && (!best || d < best[0]) && clear(nodes[i], nodes[j])) best = [d, i, j];
    }
    if (best) { edge(best[1], best[2]); continue }
    // no straight link: route across the grass from the piece to the main network
    const nearMain = (x, y) => [...edges].some(e => { const [i, j] = e.split(',').map(Number); return main.has(i) && segDist(x, y, [...nodes[i], ...nodes[j]]) < .3 });
    const path = route(nodes[other[0]], nearMain);
    if (!path) { problems.push(`walk: piece of ${other.length} nodes cannot be joined`); for (const i of other) for (const e of [...edges]) if (e.split(',').map(Number).includes(i)) edges.delete(e); continue }
    let last = other[0];
    for (const p of path.slice(1, -1)) { const k = node(...p); edge(last, k); last = k }
    const k = splitTo(path[path.length - 1], .6, main); if (k < 0) { problems.push('walk: join failed'); break } edge(last, k);
  }
  // 6. approach points: each interactive target gets a node at the nearest free spot, linked to the network
  const anchors = {};
  for (const [name, [X, Y]] of Object.entries(V.targets)) {
    let p = V.toTile(X, Y);
    if (!free(...p)) {   // target drawn on an object (a door, a sign): step out to the nearest free ground
      let best = null;
      for (let r = .2; r <= 3 && !best; r += .2) for (let a = 0; a < 16; a++) {
        const q = [p[0] + r * Math.cos(a * Math.PI / 8), p[1] + r * Math.sin(a * Math.PI / 8)];
        if (free(...q) && (!best || Math.hypot(q[0] - p[0], q[1] - p[1]) < best[0])) best = [r, q];
      }
      if (!best) { problems.push(`walk: no free ground near ${name}`); continue }
      p = best[1];
    }
    const a = node(...p);
    let k = splitTo(p);
    if (k < 0) {   // no straight connector: route around houses and fences across the grass
      const near = (x, y) => [...edges].some(e => { const [i, j] = e.split(',').map(Number); return segDist(x, y, [...nodes[i], ...nodes[j]]) < .3 });
      const path = route(p, near);
      if (!path) { problems.push(`walk: ${name} cannot reach a path`); continue }
      let last = a;
      for (const q of path.slice(1, -1)) { const n = node(...q); edge(last, n); last = n }
      k = splitTo(path[path.length - 1], .6); if (k < 0) { problems.push(`walk: ${name} cannot reach a path`); continue }
      edge(last, k); anchors[name] = a; continue;
    }
    edge(a, k); anchors[name] = a;
  }
  // 7. compact: drop nodes that only continue a straight line, renumber by position, world units
  const keep = new Set(Object.values(anchors));
  for (let changed = true; changed;) {
    changed = false;
    const m = adj();
    for (let i = 0; i < nodes.length; i++) {
      if (keep.has(i) || m[i].length !== 2) continue;
      const [a, b] = m[i], [ax, ay] = nodes[a], [bx, by] = nodes[b], [x, y] = nodes[i];
      if (Math.abs((bx - ax) * (y - ay) - (by - ay) * (x - ax)) > 1e-6) continue;
      if (Math.hypot(bx - ax, by - ay) > 6) continue;   // keep edges short enough for a smooth nearest-point snap
      edges.delete(a < i ? `${a},${i}` : `${i},${a}`); edges.delete(b < i ? `${b},${i}` : `${i},${b}`); edge(a, b); changed = true; break;
    }
  }
  const used = [...new Set([...edges].flatMap(e => e.split(',').map(Number)))];
  const world = i => V.toWorld(...nodes[i]).map(v => Math.round(v));
  used.sort((i, j) => world(i)[1] - world(j)[1] || world(i)[0] - world(j)[0] || i - j);
  const idx = new Map(used.map((i, k) => [i, k]));
  const E = [...edges].map(e => e.split(',').map(n => idx.get(Number(n)))).map(([i, j]) => i < j ? [i, j] : [j, i]).sort((u, v) => u[0] - v[0] || u[1] - v[1]);
  const A = Object.fromEntries(Object.entries(anchors).sort(([p], [q]) => p < q ? -1 : 1).map(([n, i]) => [n, idx.get(i)]));
  // walkable ground for taps: road, lane, plaza and bridge rectangles clipped to the part on screen, as world quads
  const span = (r) => { // clip the long side to where its centre line is on screen
    const L = along(r), ts = []; for (let t = L.a; t <= L.b; t += .25) if (inView(...pt(L, t))) ts.push(t);
    if (!ts.length) return null; const a = Math.max(L.a, ts[0] - .5), b = Math.min(L.b, ts[ts.length - 1] + .5);
    return L.h ? [a, r[1], b, r[3]] : [r[0], a, r[2], b];
  };
  const quad = r => [[r[0], r[1]], [r[2], r[1]], [r[2], r[3]], [r[0], r[3]]].flatMap(([x, y]) => V.toWorld(x, y).map(v => Math.round(v)));
  const areas = [...V.roads, ...V.lanes, V.plaza, ...V.bridges].map(r => r === V.plaza || V.bridges.includes(r) ? r : span(r)).filter(Boolean).map(quad);
  return {
    nodes: used.flatMap(world), edges: E.flat(), anchors: A, areas, problems, dropped,
    // tile-space copy for the independent obstacle test (not shipped to the game)
    debug: {nodes: used.map(i => nodes[i].map(v => +v.toFixed(4))), edges: E},
  };
}
