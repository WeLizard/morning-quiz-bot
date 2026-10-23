// «Контрастный режим» for the village (docs/design/UI_RULES.md §16, E3): the dark path edge of the farm (scene_buildings.js
// drawRoad, #3a2610 2.4 px) drawn as a vector layer over the village art, only where a road or the plaza meets ground that is not
// path. The background picture is not touched. The edge is left out where anything stands on either side of it (a house,
// a fence, a tree, water, a cart: V.bare = 2) and where a taller object in front hides it on screen (festKit occlusion).
// Output: <svg viewBox="0 0 2400 1800"> with one <path> of straight segments, like the festival layers (village-fest-*.svg).
import {festKit} from './fest_kit.js';

const EDGE = '#3a2610', WIDTH = 2.4, STEP = 4;   // a tile edge is checked in quarters

export function contrastPaths(V) {
  const K = festKit(V, 'contrast_paths'), {c, pt, hidden, problems} = K;
  const path = (x, y) => { const k = V.kind(x + .5, y + .5); return k === 'road' || k === 'plaza' };
  const runs = [];
  // tiles of the village square and the roads leading out of it (village.js ROADS reach -30..80)
  for (let x = -32; x < 82; x++) for (let y = -32; y < 82; y++) {
    if (!path(x, y)) continue;
    for (const [dx, dy, ax, ay, bx, by] of [[0, -1, 0, 0, 1, 0], [1, 0, 1, 0, 1, 1], [0, 1, 1, 1, 0, 1], [-1, 0, 0, 1, 0, 0]]) {
      if (path(x + dx, y + dy)) continue;
      let run = null;
      for (let i = 0; i < STEP; i++) {
        const t0 = i / STEP, t1 = (i + 1) / STEP, tm = (t0 + t1) / 2;
        const mx = x + ax + (bx - ax) * tm, my = y + ay + (by - ay) * tm;
        const ok = V.edge(mx, my) > .02 && !hidden(mx, my, 0) &&
          V.bare(mx + dx * .14, my + dy * .14) !== 2 && V.bare(mx - dx * .14, my - dy * .14) !== 2;
        if (!ok) { run = null; continue }
        const a = [x + ax + (bx - ax) * t0, y + ay + (by - ay) * t0], b = [x + ax + (bx - ax) * t1, y + ay + (by - ay) * t1];
        if (run) run[1] = b; else { run = [a, b]; runs.push(run) }
      }
    }
  }
  if (!runs.length) problems.push('contrast_paths: no visible path edge');
  for (const [[ax, ay], [bx, by]] of runs) { const p = pt(ax, ay), q = pt(bx, by); K.s.line(p.x, p.y, q.x, q.y, EDGE, WIDTH) }
  return {svg: K.wrap(), problems, segments: runs.length};
}
