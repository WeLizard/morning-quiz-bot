// «День смеха» (31.03–02.04, FARM_FESTIVALS_DESIGN.md §9.2 №4): the village's festival layer, vector only (fest_kit.js).
//   vf-decor — the mixed-up signs on posts by the doors (the post office's envelope at the mill, the mill's sheaf at the post
//              office, Агата's loaf at Крот's garage and his wrench at the bakery), harlequin pennants between the plaza lamps, geese in party
//              cones by the pond, the scarecrow in Филиныч's round glasses, confetti on the plaza.
// Nothing glows: the joke is a daytime one, so there is no vf-day / vf-night light of its own.
import {festKit} from './fest_kit.js';

const FLAGS = ['#d9553f', '#e8c25a', '#7fa3c4', '#8fae86', '#c3b0de', '#e7a8b5'];
const CONFETTI = ['#d9553f', '#e8c25a', '#7fa3c4', '#8fae86', '#c3b0de', '#e7a8b5', '#f4ede0'];
const INK = '#3f3428', WOOD = '#b48f66', WOOD_DARK = '#7a5a3e';

// the buildings whose signs swap (village.js compose block), and what each one shows today: the other's trade
const SWAPS = [
  {who: 'mill', box: [7.6, 2.6, 2.8, 2.8], shows: 'envelope'},     // «Почта» on the mill
  {who: 'post', box: [12.4, 26.4, 3, 3], shows: 'sheaf'},          // the mill's sheaf on the post office (Ёж)
  {who: 'bakery', box: [21.6, 10.7, 3, 3], shows: 'wrench'},       // Крот's wrench on Агата's bakery
  {who: 'garage', box: [29.6, 12.3, 3, 3], shows: 'loaf'},         // Агата's loaf on Крот's garage
];

export function aprilFools(V) {
  const K = festKit(V, 'april_fools'), {c, s, pt, quad, hidden, problems} = K;
  const pieces = [];   // [depth, draw], back to front

  // ---------- the mixed-up signs: a crooked board on a post in front of each building, showing the other trade ----------
  // (a board on the wall itself is a few px at the village scale; a signpost by the door reads on a phone)
  const plate = ({box: [bx, by, bw, bh], shows, who}) => {
    const at = K.place({w: .4, d: .4, h: 50, near: [bx + bw / 2, by + bh + .5], area: [bx - 2.5, by - 2.5, bx + bw + 2.8, by + bh + 2.8],
      button: 46, cover: .35, margin: .05, path: .05, what: `${who} sign`});
    if (!at) return;
    const [x, y] = [at[0] + .2, at[1] + .2], tilt = who === 'mill' || who === 'garage' ? .1 : -.1;
    pieces.push([x + y + .2, () => {
      const g = pt(x, y), m = pt(x, y, 40);
      s.shadow(g.x, g.y, 6, 2.4); s.line(g.x, g.y, g.x, m.y + 6, WOOD_DARK, 2.4);
      // the recorder has no rotate: tilt the board's points by hand around its centre
      const cs = Math.cos(tilt), sn = Math.sin(tilt), r = (u, v) => ({x: m.x + u * cs - v * sn, y: m.y + u * sn + v * cs});
      const poly = (pts, fill) => s.poly(pts.map(([u, v]) => r(u, v)), fill);
      const line = (u0, v0, u1, v1, col, w) => { const a = r(u0, v0), b = r(u1, v1); s.line(a.x, a.y, b.x, b.y, col, w) };
      const dot = (u, v, rx, ry, fill) => { const q = r(u, v); s.ellipse(q.x, q.y, rx, ry, fill) };
      poly([[-17, -12], [17, -12], [17, 12], [-17, 12]], WOOD_DARK);
      poly([[-15.4, -10.4], [15.4, -10.4], [15.4, 10.4], [-15.4, 10.4]], WOOD);
      for (const du of [-13, 13]) dot(du, 0, 1.1, 1.1, INK);
      if (shows === 'envelope') {
        poly([[-9, -6.4], [9, -6.4], [9, 6.4], [-9, 6.4]], '#ffffff');
        line(-9, -6.4, 0, 1, '#4f7396', 1.6); line(0, 1, 9, -6.4, '#4f7396', 1.6);
      } else if (shows === 'sheaf') {
        for (const d of [-4.4, 0, 4.4]) { line(0, 8, d * 1.3, -4, '#c9a23e', 1.6); dot(d * 1.3, -6, 1.9, 3.4, '#e8c25a') }
        poly([[-3.4, 1.4], [3.4, 1.4], [3.4, 3.6], [-3.4, 3.6]], '#d9553f');
      } else if (shows === 'wrench') {
        line(-7, 5, 5, -4, '#9aa1a8', 3.4); dot(6.4, -5.2, 4, 4, '#9aa1a8'); dot(7.6, -6.4, 1.8, 1.8, WOOD);
        dot(-7.4, 5.4, 3, 3, '#9aa1a8'); dot(-7.4, 5.4, 1.2, 1.2, WOOD);
      } else {   // loaf
        dot(0, 1.4, 11, 6.4, '#b8783e'); dot(0, 0, 9.6, 4.8, '#e0a964');
        for (const d of [-4.4, 0, 4.4]) line(d - 1.6, -3, d + 1.6, 2.4, '#a8713a', 1.3);
      }
    }]);
  };
  for (const w of SWAPS) plate(w);

  // ---------- geese in party cones by the pond (FarmScene.goose, its head at x+11, y-25) ----------
  const pond = V.pond, hat = (x, y, k) => {   // a party cone on a goose head; (x, y) the brim, tilted a little
    const col = FLAGS[k % FLAGS.length], st = FLAGS[(k + 1) % FLAGS.length], h = 11, w = 7, t = (k % 2 ? 1 : -1) * 2;
    s.poly([{x: x - w / 2, y}, {x: x + t, y: y - h}, {x: x + w / 2, y}], col);
    s.poly([{x: x - w * .34 + t * .28, y: y - h * .28}, {x: x + w * .34 + t * .28, y: y - h * .28}, {x: x + w * .25 + t * .46, y: y - h * .48}, {x: x - w * .25 + t * .46, y: y - h * .48}], st);
    s.ellipse(x + t, y - h, 1.6, 1.6, '#f4ede0');
  };
  let geese = 0;
  for (const [k, near] of [[pond.x - 3.4, pond.y - 1.2], [pond.x - 3.2, pond.y + 1.6], [pond.x + .4, pond.y + 3.2]].entries()) {
    const at = K.place({w: .7, d: .5, h: 40, near, area: [pond.x - 6, pond.y - 4, pond.x + 5, pond.y + 5], button: 50, cover: .15, what: `goose ${k + 1}`});
    if (!at) continue;
    geese++;
    const [x, y] = [at[0] + .35, at[1] + .25];
    pieces.push([x + y + .25, () => {
      const p = pt(x, y), flip = k === 1 ? -1 : 1;
      c.save(); c.translate(p.x, p.y); c.scale(flip, 1); s.goose(0, 0, 0); hat(11, -28.4, k); c.restore();
    }]);
  }
  if (geese < 2) problems.push('april_fools: fewer than two geese by the pond');

  // ---------- the scarecrow in Филиныч's glasses: near his house if there is room, else the nearest free lawn ----------
  const crow = K.place({w: .9, d: .8, h: 65, near: [11.6, 20.2], area: [3, 14, 20, 36], button: 55, cover: .2, what: 'scarecrow'});
  if (crow) {
    const [x, y] = [crow[0] + .45, crow[1] + .4];
    pieces.push([x + y + .7, () => {
      const p = pt(x, y); c.save(); c.translate(p.x, p.y); c.scale(1.2, 1.2);
      s.decor({type: 'scarecrow', x, y}, {x: 0, y: 0});
      // round glasses of Филиныч over the eyes and a red bow tie
      for (const dx of [-2.6, 2.6]) { s.ellipse(dx, -36, 2.4, 2.4, 'rgba(255,255,255,.55)'); c.beginPath(); c.ellipse(dx, -36, 2.4, 2.4, 0, 0, Math.PI * 2); c.strokeStyle = INK; c.lineWidth = .9; c.stroke() }
      s.line(-.4, -36.4, .4, -36.4, INK, .8);
      s.poly([{x: 0, y: -30}, {x: -3.6, y: -32}, {x: -3.6, y: -28}], '#d9553f'); s.poly([{x: 0, y: -30}, {x: 3.6, y: -32}, {x: 3.6, y: -28}], '#d9553f');
      c.restore();
    }]);
  }

  // ---------- confetti on the plaza: small paper squares, where nothing stands and no house hides them ----------
  const [px0, py0, px1, py1] = V.plaza, bits = [];
  let r = 7;
  const rnd = () => (r = (r * 16807) % 2147483647) / 2147483647;
  for (let i = 0; i < 600 && bits.length < 170; i++) {
    const x = px0 + rnd() * (px1 - px0), y = py0 + rnd() * (py1 - py0), k = Math.floor(rnd() * CONFETTI.length), a = rnd() * Math.PI;
    if (!V.free(x, y) || hidden(x, y, 0)) continue;
    bits.push([x, y, k, a]);
  }
  if (bits.length < 80) problems.push(`april_fools: only ${bits.length} confetti bits on the plaza`);

  c.group('vf-decor');
  for (const [x, y, k, a] of bits) { const p = pt(x, y), dx = Math.cos(a) * 3, dy = Math.sin(a) * 1.5;
    s.poly([{x: p.x - dx, y: p.y - dy}, {x: p.x + dy * 1.4, y: p.y - dx * .5}, {x: p.x + dx, y: p.y + dy}, {x: p.x - dy * 1.4, y: p.y + dx * .5}], CONFETTI[k]) }
  // harlequin pennants: diamonds of two alternating colours between the plaza lamps
  K.lampPairs(2).forEach(([a, b], k) => K.garland(a, b, (p, q, i) => {
    const m = {x: (p.x + q.x) / 2, y: (p.y + q.y) / 2};
    s.poly([{x: m.x, y: m.y - 1}, {x: m.x + 3.4, y: m.y + 4.6}, {x: m.x, y: m.y + 10}, {x: m.x - 3.4, y: m.y + 4.6}], FLAGS[(i + k * 3) % FLAGS.length]);
    s.ellipse(m.x, m.y + 11.4, 1.1, 1.1, '#f4ede0');
  }, '#8a6c4c', 12));
  pieces.sort((p, q) => p[0] - q[0]).forEach(([, draw]) => draw());
  c.end();

  return {svg: K.wrap(), problems};
}
