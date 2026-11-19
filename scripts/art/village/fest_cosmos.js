// «День космонавтики» (10.04–13.04, FARM_FESTIVALS_DESIGN.md §9.2 №13): the village's festival layer, vector only (fest_kit.js).
//   vf-decor — Крот's rocket from a barrel by his garage (hoops, rivets, a tin nose cone, fins, a porthole, a ladder), star tiles
//              along the lanes to it, night-blue pennants with yellow stars between the plaza lamps, and the constellation map:
//              a night-blue banner on two poles on the plaza with the Big Dipper drawn in pale stars;
//   vf-night — above the night tint: the map's stars and lines glow, the pennant stars glint, a warm light in the porthole.
import {festKit} from './fest_kit.js';

const NIGHT = '#3e5578', NIGHT_DARK = '#2c3e5c', NIGHT_LIGHT = '#5a759c', STAR = '#e8c25a', STAR_PALE = '#fff3b0';
const WOOD = '#b48f66', WOOD_SHADE = '#a07c55', WOOD_DARK = '#7a5a3e', STEEL = '#9aa1a8', STEEL_LIGHT = '#c9ced4', RED = '#d9553f', RED_SHADE = '#b8432f';
const GLASS = '#d6e8ee', INK = '#3f3428';
const GARAGE = [29.6, 12.3, 3, 3];   // Крот's garage, his workshop (village.js compose block)
// the Big Dipper on the banner: (u along the banner 0..1, v down from its top 0..1); the handle first, then the bowl
const DIPPER = [[.08, .3], [.24, .36], [.38, .5], [.52, .52], [.56, .82], [.8, .84], [.86, .5]];

export function cosmonautics(V) {
  const K = festKit(V, 'cosmonautics'), {c, s, pt, quad, hidden, problems} = K;
  const pieces = [];   // [depth, draw], back to front
  const star5 = (x, y, r, fill, flat = 0) => {   // a five-point star at screen (x, y); flat > 0 squashes it onto the ground
    const pts = [];
    for (let i = 0; i < 10; i++) { const a = -Math.PI / 2 + i * Math.PI / 5, rr = i % 2 ? r * .45 : r; pts.push({x: x + rr * Math.cos(a), y: y + rr * Math.sin(a) * (1 - flat)}) }
    s.poly(pts, fill);
  };

  // ---------- Крот's rocket from a barrel, by the garage door ----------
  const [gx0, gy0, gw, gh] = GARAGE;
  const spot = K.place({w: .8, d: .8, h: 86, near: [gx0 + gw / 2 + .6, gy0 + gh + .9], area: [gx0 - 3.5, gy0 - 3.5, gx0 + gw + 4, gy0 + gh + 4],
    button: 40, cover: .45, margin: .05, path: .05, what: 'rocket'});
  let porthole = null;
  if (spot) {
    const [x, y] = [spot[0] + .4, spot[1] + .4], g = pt(x, y), RS = 1.3;
    porthole = {x: g.x, y: g.y - 22 * RS, r: RS};
    pieces.push([x + y + .45, () => {
      c.save(); c.translate(g.x, g.y); c.scale(RS, RS); const X = 0, Y = 0;
      s.shadow(X + 3, Y, 18, 6);
      s.poly([{x: X - 10, y: Y - 16}, {x: X - 20, y: Y + 1}, {x: X - 9, y: Y - 1}], RED);                // fins
      s.poly([{x: X + 10, y: Y - 16}, {x: X + 20, y: Y + 1}, {x: X + 9, y: Y - 1}], RED_SHADE);
      s.ellipse(X, Y - 2, 11, 4.2, WOOD_DARK);                                                         // the barrel: bottom rim
      const side = (k) => [0, .25, .5, .75, 1].map(t => ({x: X + k * (11 + 2 * Math.sin(Math.PI * t)), y: Y - 2 - 34 * t}));
      s.poly([...side(-1), ...side(1).reverse()], WOOD);
      s.poly([{x: X + 4, y: Y - 2}, ...side(1), {x: X + 4, y: Y - 36}], WOOD_SHADE);
      for (const dx of [-6, 0, 6]) s.line(X + dx, Y - 35, X + dx, Y - 2, WOOD_DARK, .7);
      for (const hy of [Y - 7, Y - 30]) {                                                               // hoops with rivets
        c.beginPath(); c.ellipse(X, hy, 12.6, 4.4, 0, 0, Math.PI); c.strokeStyle = STEEL; c.lineWidth = 2.4; c.stroke();
        for (const a of [.35, 1.1, 2, 2.8]) s.ellipse(X + Math.cos(a) * 12.6, hy + Math.sin(a) * 4.4, .8, .8, INK);
      }
      s.ellipse(X, Y - 22, 5, 5, STEEL); s.ellipse(X, Y - 22, 3.4, 3.4, GLASS);                        // the porthole
      s.line(X - 1.8, Y - 23, X + .2, Y - 24.6, '#ffffff', 1);
      s.ellipse(X, Y - 36, 11, 4, STEEL);                                                               // the tin nose cone
      s.poly([{x: X - 11, y: Y - 36}, {x: X, y: Y - 62}, {x: X + 11, y: Y - 36}], STEEL_LIGHT);
      s.poly([{x: X, y: Y - 62}, {x: X + 11, y: Y - 36}, {x: X + 3, y: Y - 35}], STEEL);
      s.poly([{x: X - 4.6, y: Y - 51}, {x: X, y: Y - 62}, {x: X + 4.6, y: Y - 51}], RED);
      s.line(X + 21, Y + 1, X + 10, Y - 33, WOOD_DARK, 1.4); s.line(X + 25, Y - 1, X + 14, Y - 34, WOOD_DARK, 1.4);   // the ladder
      for (let i = 1; i < 6; i++) { const t = i / 6; s.line(X + 21 - 11 * t, Y + 1 - 34 * t, X + 25 - 11 * t, Y - 1 - 33 * t, WOOD_DARK, 1.2) }
      c.restore();
    }]);
  }

  // ---------- star tiles on the stepping-stone lanes that leave the plaza: a star on each of the nearest stones ----------
  const [px0, py0, px1, py1] = V.plaza, toPlaza = (x, y) => Math.hypot(Math.max(px0 - x, 0, x - px1), Math.max(py0 - y, 0, y - py1));
  const stones = [];
  for (let tx = Math.floor(px0 - 8); tx <= px1 + 8; tx++) for (let ty = Math.floor(py0 - 8); ty <= py1 + 8; ty++) {
    const x = tx + .5, y = ty + .5;
    if (V.kind(x, y) !== 'lane' || !V.free(x, y) || hidden(x, y, 0)) continue;
    stones.push([toPlaza(x, y), x, y]);
  }
  stones.sort((a, b) => a[0] - b[0] || a[1] - b[1] || a[2] - b[2]);
  for (const [, x, y] of stones.slice(0, 16))
    pieces.push([x + y - .5, () => { const p = pt(x, y); star5(p.x, p.y + 1, 9, '#c9a23e', .5); star5(p.x, p.y, 8, STAR, .5) }]);
  if (stones.length < 6) problems.push(`cosmonautics: only ${stones.length} lane stones for the star tiles`);

  // ---------- the constellation map: a night-blue banner on two poles on the plaza ----------
  const BW = 1.5;
  const map = K.place({w: BW, d: .3, h: 62, near: [(px0 + px1) / 2 + 2, (py0 + py1) / 2 + 2], area: [px0 - 2, py0 - 2, px1 + 2, py1 + 2],
    button: 46, cover: .12, margin: .05, path: .05, what: 'constellation map'});
  let mapStars = [];
  if (map) {
    const [x, y] = [map[0], map[1] + .15], at = (u, v) => pt(x + .08 + (BW - .16) * u, y, 58 - 26 * v);
    mapStars = DIPPER.map(([u, v]) => at(u, v));
    pieces.push([x + BW + y, () => {
      for (const u of [0, 1]) { const b = pt(x + .08 + (BW - .16) * u, y), t = pt(x + .08 + (BW - .16) * u, y, 62); s.line(b.x, b.y, t.x, t.y, WOOD_DARK, 2.2) }
      const sh = pt(x + BW / 2, y); s.shadow(sh.x, sh.y, 26, 4);
      quad([[x + .08, y, 59], [x + BW - .08, y, 59], [x + BW - .08, y, 31], [x + .08, y, 31]], NIGHT);
      quad([[x + .08, y, 59], [x + BW - .08, y, 59], [x + BW - .08, y, 56.4], [x + .08, y, 56.4]], NIGHT_DARK);
      for (let i = 0; i < 4; i++) { const u0 = i / 4, u1 = (i + 1) / 4, a = at(u0, 1), b = at((u0 + u1) / 2, 1), d = at(u1, 1);   // a scalloped hem
        s.poly([a, {x: b.x, y: b.y + 4}, d], NIGHT) }
      for (let i = 0; i < mapStars.length - 1; i++) s.line(mapStars[i].x, mapStars[i].y, mapStars[i + 1].x, mapStars[i + 1].y, NIGHT_LIGHT, .9);
      s.line(mapStars[3].x, mapStars[3].y, mapStars[6].x, mapStars[6].y, NIGHT_LIGHT, .9);
      mapStars.forEach((q, i) => star5(q.x, q.y, i > 2 ? 3 : 2.6, i > 2 ? STAR : STAR_PALE));
      for (const [u, v] of [[.2, .7], [.66, .2], [.95, .9], [.42, .16]]) { const q = at(u, v); s.ellipse(q.x, q.y, .8, .8, STAR_PALE) }
    }]);
  }

  c.group('vf-decor');
  // night-blue pennants with a yellow star between the plaza lamps
  const glints = [];
  K.lampPairs(2).forEach(([a, b], k) => K.garland(a, b, (p, q, i) => {
    const m = {x: (p.x + q.x) / 2, y: (p.y + q.y) / 2};
    s.poly([{x: m.x - 5, y: m.y - .8}, {x: m.x + 5, y: m.y + .8}, {x: m.x, y: m.y + 13}], (i + k) % 2 ? NIGHT : NIGHT_LIGHT);
    star5(m.x, m.y + 4.4, 3.2, STAR); glints.push({x: m.x, y: m.y + 4.4});
  }, '#8a6c4c', 14));
  pieces.sort((p, q) => p[0] - q[0]).forEach(([, draw]) => draw());
  c.end();

  c.group('vf-night');
  if (porthole) { s.ellipse(porthole.x, porthole.y, 10 * porthole.r, 8 * porthole.r, 'rgba(255,214,130,.28)'); s.ellipse(porthole.x, porthole.y, 3.2 * porthole.r, 3.2 * porthole.r, '#ffe7a0') }
  for (let i = 0; i < mapStars.length - 1; i++) s.line(mapStars[i].x, mapStars[i].y, mapStars[i + 1].x, mapStars[i + 1].y, 'rgba(255,243,176,.55)', 1);
  if (mapStars.length) s.line(mapStars[3].x, mapStars[3].y, mapStars[6].x, mapStars[6].y, 'rgba(255,243,176,.55)', 1);
  for (const q of mapStars) { s.ellipse(q.x, q.y, 7, 7, 'rgba(255,243,176,.22)'); star5(q.x, q.y, 3.2, STAR_PALE) }
  for (const q of glints) { s.ellipse(q.x, q.y, 5.6, 5.6, 'rgba(255,214,130,.25)'); star5(q.x, q.y, 3.2, '#ffe7a0') }
  c.end();

  return {svg: K.wrap(), problems};
}
