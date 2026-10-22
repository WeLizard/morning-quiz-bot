// «Масленица» (FARM_FESTIVALS_DESIGN.md §9.2 №2): the village's festival layer, vector only (fest_kit.js).
//   vf-decor  — the last snow in patches (fest_snow.js), the ice slide, the straw effigy of Winter, the «Проводы Зимы» stage with its flags, blini and a samovar on the
//               market stalls, bright flag garlands between the plaza lamps, chimney smoke (under the night tint);
//   vf-day    — warm light in the windows;
//   vf-night  — windows, stage lanterns, the samovar, garland glow above the night tint.
// Every piece takes a free place found on this render (kit.place), the stage first: on free ground, in view, over no house,
// lamp or other piece, clear of the village buttons.
import {festKit} from './fest_kit.js';
import {snowCover} from './fest_snow.js';

const FLAGS = ['#d9553f', '#e8c25a', '#8fae86', '#7fa3c4', '#e7a8b5', '#f4ede0'];
const WOOD = '#b48f66', WOOD_D = '#8a6c4c', ICE = '#d6eaf0', STRAW = '#d9b25e', BLIN = '#e8b65a';

export function maslenitsa(V) {
  // V as fest_newyear (roofs for the houses' silhouettes, stalls:[[x0,y0,x1,y1]], walk, clear, ground)
  const K = festKit(V, 'maslenitsa'), {B, c, s, pt, quad, problems} = K;
  const [px0, py0, px1, py1] = V.plaza, mid = [(px0 + px1) / 2, (py0 + py1) / 2];
  const around = [px0 - 4, py0 - 4, px1 + 4, py1 + 4];
  const glows = [];
  const pieces = [];   // [depth, draw]: drawn back to front, like the farm sorts its objects

  // ---------- the straw effigy of Winter on the plaza: pole and crossbar, straw arms, a red dress, a kerchief, ribbons ----------
  const eff = K.place({w: .7, d: .7, h: 82, near: mid, area: around, what: 'effigy'});
  if (eff) {
    const ex = eff[0] + .35, ey = eff[1] + .35, q = z => pt(ex, ey, z);
    pieces.push([ex + ey + .35, () => {
      const g = q(0); s.shadow(g.x, g.y, 18, 7);
      for (const [dx, dy, r] of [[-7, -2, 7], [6, -1, 7], [0, 2, 8]]) s.ellipse(g.x + dx, g.y + dy - 2, r, 3.4, STRAW);              // straw at the foot
      for (const [a, b] of [[-9, 4], [8, 3], [-3, -6]]) s.line(g.x + a, g.y - 1, g.x + b, g.y - 6, '#a8714a', 2.2);               // logs
      B.L(s, ex, ey, 0, ex, ey, 78, '#8a6c4c', 2.6);
      const L = pt(ex - .32, ey + .02, 54), R = pt(ex + .32, ey - .02, 54);
      s.line(L.x, L.y, R.x, R.y, '#8a6c4c', 2.2);
      for (const [p, sx] of [[L, -1], [R, 1]]) for (let k = 0; k < 5; k++) s.line(p.x, p.y, p.x + sx * (5 + k), p.y + 3 + k * 1.6, STRAW, 1.3);   // straw hands
      const t = q(56), b = q(20);
      s.poly([{x: t.x - 7, y: t.y}, {x: t.x + 7, y: t.y}, {x: b.x + 14, y: b.y}, {x: b.x - 14, y: b.y}], '#d9553f');               // dress
      s.poly([{x: t.x - 7, y: t.y}, {x: t.x, y: t.y}, {x: b.x, y: b.y}, {x: b.x - 14, y: b.y}], '#e2705c');
      for (const [dx, dz] of [[-6, 26], [4, 30], [-2, 38], [7, 42], [-8, 34], [1, 47], [9, 25]]) s.ellipse(b.x + dx, q(dz).y, 1.3, 1.1, '#f4ede0');
      s.poly([{x: t.x - 4, y: q(46).y}, {x: t.x + 4, y: q(46).y}, {x: b.x + 6, y: q(22).y}, {x: b.x - 6, y: q(22).y}], '#e8c25a');   // apron
      for (let k = 0; k < 7; k++) s.line(b.x - 12 + k * 4, b.y, b.x - 13 + k * 4.2, b.y + 6, STRAW, 1.4);                          // straw under the hem
      const h = q(64); s.ellipse(h.x, h.y, 6.4, 6.8, '#e3c27a');
      s.poly([{x: h.x - 8, y: h.y + 2}, {x: h.x - 6, y: h.y - 6}, {x: h.x, y: h.y - 9}, {x: h.x + 6, y: h.y - 6}, {x: h.x + 8, y: h.y + 2}, {x: h.x + 3, y: h.y - 2},
        {x: h.x - 3, y: h.y - 2}], '#f4ede0');                                                                                  // kerchief
      s.poly([{x: h.x - 2, y: h.y + 5}, {x: h.x + 2, y: h.y + 5}, {x: h.x + 5, y: h.y + 11}, {x: h.x - 1, y: h.y + 8}], '#f4ede0');
      for (const [dx, dy] of [[-4, -4], [3, -5], [0, -7], [-6, 0], [6, 0]]) s.ellipse(h.x + dx, h.y + dy, 1, 1, '#d9553f');
      for (const [p, sx, cols] of [[L, -1, ['#d9553f', '#7fa3c4']], [R, 1, ['#e8c25a', '#8fae86']]]) cols.forEach((col, k) => {   // ribbons
        c.beginPath(); c.moveTo(p.x, p.y); c.quadraticCurveTo(p.x + sx * (6 + k * 4), p.y + 6, p.x + sx * (4 + k * 7), p.y + 16 + k * 3); c.strokeStyle = col; c.lineWidth = 1.4; c.stroke() });
    }]);
  }

  // ---------- the «Проводы Зимы» stage: boards, a painted backdrop (spring sun over melting snow), curtains, flags ----------
  const stg = K.place({w: 2.4, d: 1.75, h: 62, near: [mid[0] + 2, mid[1] + 2], area: [px0 - 7, py0 - 7, px1 + 7, py1 + 7], what: 'stage'});
  if (stg) {
    const [x, y] = stg, x1 = x + 2.4, y1 = y + 1.4;
    pieces.push([x1 + y1 + .35, () => {
      B.shadowAt(s, x, y, x1, y1, 50, 18);
      for (const [a, b] of [[x + .1, y + .1], [x1 - .1, y + .1]]) B.L(s, a, b, 9, a, b, 58, WOOD_D, 2.2);
      B.fullBox(s, WOOD, x, y, x1, y1, 0, 9, '#c9a57a'); B.boards(s, 'y', y1, x, x1, 0, 9, 6, 'rgba(80,55,30,.25)');
      quad([[x + .12, y + .12, 9], [x1 - .12, y + .12, 9], [x1 - .12, y + .12, 54], [x + .12, y + .12, 54]], '#bcd6e4');                // backdrop
      quad([[x + .12, y + .12, 9], [x1 - .12, y + .12, 9], [x1 - .12, y + .12, 20], [x + .12, y + .12, 16]], '#f1f5f6');                 // melting snow
      quad([[x + .7, y + .12, 9], [x + 1.5, y + .12, 9], [x + 1.4, y + .12, 13], [x + .9, y + .12, 14]], '#9cc08a');                       // first grass
      const sun = pt(x + 1.2, y + .12, 36);
      for (let k = 0; k < 12; k++) { const a = k * Math.PI / 6; s.line(sun.x + Math.cos(a) * 9, sun.y + Math.sin(a) * 9, sun.x + Math.cos(a) * 14, sun.y + Math.sin(a) * 14, '#e8a83a', 2) }
      s.ellipse(sun.x, sun.y, 8.4, 8.4, '#f0c95a'); s.ellipse(sun.x - 2, sun.y - 2, 3, 3, '#f8e3a0');
      for (const [a, b] of [[x + .1, y1 - .1], [x1 - .1, y1 - .1]]) B.L(s, a, b, 9, a, b, 58, WOOD_D, 2.2);
      B.L(s, x + .1, y1 - .1, 58, x1 - .1, y1 - .1, 58, WOOD_D, 2.4); B.L(s, x1 - .1, y + .1, 58, x1 - .1, y1 - .1, 58, WOOD_D, 2.4);
      for (const [a, b] of [[x + .1, x + .32], [x1 - .32, x1 - .1]]) {                                                              // red curtains
        quad([[a, y1 - .1, 58], [b, y1 - .1, 58], [b, y1 - .1, 44], [a + (b - a) * .3, y1 - .1, 10], [a, y1 - .1, 10]], '#c9604f');
        quad([[a + (b - a) * .45, y1 - .1, 58], [a + (b - a) * .6, y1 - .1, 58], [a + (b - a) * .5, y1 - .1, 20], [a + (b - a) * .35, y1 - .1, 20]], '#a94c3e') }
      for (let k = 0; k < 9; k++) { const a = pt(x + .1 + (x1 - x - .2) * (k / 9), y1 - .1, 58), b = pt(x + .1 + (x1 - x - .2) * ((k + 1) / 9), y1 - .1, 58);
        s.poly([a, b, {x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 + 9}], FLAGS[k % FLAGS.length]) }                           // bunting
      B.fullBox(s, WOOD, x + .9, y1, x + 1.5, y1 + .18, 0, 6, '#c9a57a'); B.fullBox(s, WOOD, x + .9, y1 + .18, x + 1.5, y1 + .35, 0, 3, '#c9a57a');   // steps
      for (const [a, b] of [[x + .1, y1 - .1], [x1 - .1, y1 - .1]]) { const l = pt(a, b, 58); s.ellipse(l.x, l.y + 4, 2.6, 3.2, '#f0c95a'); glows.push([a, b, 54, 20]) }
    }]);
  }

  // ---------- the ice slide: a tower with a ladder, the iced ramp falling towards +x, a run of ice on the ground ----------
  const slide = K.place({w: 3.9, d: .8, h: 58, near: [px1 + 1, mid[1]], area: [px0 - 14, py0 - 14, px1 + 14, py1 + 14], margin: .45, button: 150, what: 'ice slide'});
  if (slide) {
    const [x0, y0] = slide, x = x0 + .5, y = y0;   // tower x..x+.7, ladder at x-.5..x
    pieces.push([x + 3.4 + y + .8, () => {
      quad([[x + 2.6, y + .15, .4], [x + 3.4, y + .15, .4], [x + 3.4, y + .65, .4], [x + 2.6, y + .65, .4]], '#dcedf2');   // the run of ice
      quad([[x + 2.6, y + .36, .5], [x + 3.4, y + .36, .5], [x + 3.4, y + .44, .5], [x + 2.6, y + .44, .5]], '#f4fafc');
      for (const b of [y + .25, y + .55]) B.L(s, x - .45, b, 0, x, b, 30, WOOD_D, 1.6);                                          // ladder
      for (let k = 1; k < 6; k++) { const f = k / 6; B.L(s, x - .45 * (1 - f), y + .25, 30 * f, x - .45 * (1 - f), y + .55, 30 * f, WOOD, 1.4) }   // rungs
      for (const [a, b] of [[x + .05, y + .1], [x + .65, y + .1], [x + .05, y + .7], [x + .65, y + .7]]) B.L(s, a, b, 0, a, b, 28, WOOD_D, 2.2);
      B.fullBox(s, WOOD, x, y + .05, x + .7, y + .75, 27, 30, '#c9a57a');
      for (const [a, b] of [[x + .05, y + .1], [x + .05, y + .7], [x + .65, y + .1]]) B.L(s, a, b, 30, a, b, 40, WOOD_D, 1.6);
      B.L(s, x + .05, y + .1, 40, x + .65, y + .1, 40, WOOD_D, 1.6); B.L(s, x + .05, y + .1, 40, x + .05, y + .7, 40, WOOD_D, 1.6);
      for (const [a, z] of [[x + 1.3, 20], [x + 1.95, 11]]) { B.L(s, a, y + .2, 0, a, y + .2, z, WOOD_D, 1.8); B.L(s, a, y + .6, 0, a, y + .6, z, WOOD_D, 1.8) }
      quad([[x + .7, y + .15, 30], [x + 2.6, y + .15, 1.5], [x + 2.6, y + .65, 1.5], [x + .7, y + .65, 30]], ICE);                     // iced ramp
      quad([[x + .7, y + .38, 30.3], [x + 2.6, y + .38, 1.8], [x + 2.6, y + .44, 1.8], [x + .7, y + .44, 30.3]], '#f4fafc');
      quad([[x + .7, y + .65, 30], [x + 2.6, y + .65, 1.5], [x + 2.6, y + .65, -1.5], [x + .7, y + .65, 25]], WOOD);                     // side board
      quad([[x + .7, y + .65, 33], [x + 2.6, y + .65, 4.5], [x + 2.6, y + .65, 1.5], [x + .7, y + .65, 30]], '#c9a57a');
      B.L(s, x + .65, y + .7, 30, x + .65, y + .7, 40, WOOD_D, 1.6); B.L(s, x + .05, y + .7, 40, x + .65, y + .7, 40, WOOD_D, 1.6);
      B.L(s, x + .1, y + .12, 30, x + .1, y + .12, 58, WOOD_D, 1.4);                                                             // flag on the tower
      const f = pt(x + .1, y + .12, 57); s.poly([f, {x: f.x + 13, y: f.y + 3}, {x: f.x, y: f.y + 7}], '#d9553f');
      const l = pt(x + .1, y + .12, 44); s.line(l.x, l.y - 3, l.x + 4, l.y - 3, WOOD_D, 1); s.ellipse(l.x + 4, l.y + 1, 2.2, 3, '#f0c95a');   // a lantern on the pole
      glows.push([x + .2, y + .12, 42, 16]);
    }]);
  }

  // ---------- blini on the market stalls: stacks with jam and sour cream on the counters, a samovar on the first stall ----------
  // (on the counters, where the stalls show their goods: the ground in front of the stalls is the player's way to the market)
  (V.stalls || []).forEach(([sx, sy], k) => {
    pieces.push([sx + sy + 2.4 + .01, () => {
      [[.3, '#c9473a'], [.72, '#f4ede0'], [1.14, '#c9473a']].forEach(([dx, top], i) => {
        const p = pt(sx + dx, sy + .68, 11);
        if (k === 0 && i === 1) { B.cyl(s, sx + dx, sy + .68, .08, 11, 13, '#a8714a'); B.cyl(s, sx + dx, sy + .68, .07, 13, 22, '#d9a650', '#e8bf6a');
          B.cyl(s, sx + dx, sy + .68, .025, 22, 26, '#a8714a', '#6f5640'); glows.push([sx + dx, sy + .68, 18, 12]); return }
        for (let n = 0; n < 4; n++) { s.ellipse(p.x, p.y - n * 1.3, 5.4, 2.8, '#c98a3a'); s.ellipse(p.x, p.y - n * 1.3 - .5, 5, 2.5, BLIN) }
        s.ellipse(p.x + .4, p.y - 5.6, 2.2, 1.2, top);
      });
    }]);
  });

  c.group('vf-decor');
  // March: the last snow in patches on the grass, wide thaw by the walls and under the trees, the roads already bare
  const snow = snowCover(V, K, {cover: .5, thaw: 1, under: .8});
  // bright flag garlands between the plaza lamps (behind everything placed on the ground)
  const strings = K.lampPairs(3).map(([a, b]) => K.garland(a, b, (p, q, i) => s.poly([p, q, {x: (p.x + q.x) / 2 + 1, y: (p.y + q.y) / 2 + 8}], FLAGS[i % FLAGS.length]), '#8a6c4c', 12));
  pieces.sort((a, b) => a[0] - b[0]).forEach(([, draw]) => draw());
  K.smoke();
  c.end();

  c.group('vf-day');
  K.windowsDay();
  c.end();
  c.group('vf-night');
  K.windowsNight();
  for (const [x, y, z, r] of glows) K.glow(x, y, z, r);
  for (const pts of strings) for (const p of pts.filter((_, i) => i % 2)) { s.ellipse(p.x, p.y + 2, 5, 4, 'rgba(255,214,130,.22)'); s.ellipse(p.x, p.y + 1, 1.3, 1.3, '#ffe7a0') }
  c.end();
  return {svg: K.wrap(), problems, snow};
}
