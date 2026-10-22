// The «Ферма» gate over the road out of the village, in the style of the farm's own name sign (FarmScene.welcomeSign):
// dark posts with pointed caps, a crossbeam, grass tufts, a hanging lantern — painted into the background — and the
// board itself, drawn by FarmScene.signBoard in the arch plane but recorded as SVG, because the board is the DOM button
// (hover outline, tap target). One geometry feeds both, so the button sits exactly on the painted chains.
// Units: village world units (viewBox 2400x1800). Plane coordinates (u along the arch, h up) -> world:
// x = NEAR.x + u, y = NEAR.y - u/2 - h (the arch spans the road across it, iso axis 1:-0.5 like the original arch).
import {FarmScene} from '/static/scene.js';
import {SvgCtx} from './svg_ctx.js';

export const NEAR = [1154.6, 1513.6], SPAN = 91.1;     // post feet of the original arch (far foot 1245.7, 1467.9)
const POST_H = 74, BEAM_H = 70, ARCH = 10, BOARD_TOP = 61, BOARD_H = 26, TEXT = 'Ферма', FONT_PX = 16;
const FAMILY = 'system-ui,-apple-system,"Segoe UI",Roboto,sans-serif';
const K = BOARD_H / 26;                                 // world units per farm px: the board is the farm board's height
const W = (u, h) => ({x: NEAR[0] + u, y: NEAR[1] - u / 2 - h});
const archH = u => BEAM_H + ARCH * 4 * (u / SPAN) * (1 - u / SPAN);   // the beam rises gently between the posts

// Board size from the lettering (measured once with the same font), so it reads on a phone (~11 css px at 1600 px world).
function layout() {
  const c = document.createElement('canvas').getContext('2d');
  c.font = `700 ${FONT_PX}px "Segoe UI",sans-serif`;
  const tw = Math.ceil(c.measureText(TEXT).width), arrow = 8, gap = 4, pad = 6;
  const bw = tw + gap + arrow + 2 * pad, left = (SPAN - bw) / 2;
  return {tw, arrow, gap, pad, bw, left};
}

function boardInto(ctx, L, night) {
  const s = Object.create(FarmScene.prototype);
  s.c = ctx;
  ctx.save();
  ctx.transform(1, -.5, 0, 1, NEAR[0], NEAR[1]);       // arch plane, local y = -h
  ctx.transform(K, 0, 0, K, L.left, -BOARD_TOP);       // farm px inside the board
  const bw = L.bw / K, bh = BOARD_H / K;
  s.signBoard({x: bw / 2}, 0, 0, bw, bh, [], night);   // the farm's board: bevelled plank, nails, light and dark edges
  // lettering with the farm sign's recipe (light emboss, then ink), larger so it reads at village scale
  const fx = L.pad / K + L.tw / K / 2, fy = bh / 2 + FONT_PX / K * .36;
  ctx.font = `700 ${FONT_PX / K}px ${FAMILY}`; ctx.textAlign = 'center';
  ctx.fillStyle = '#fff0c6'; ctx.fillText(TEXT, fx + .6, fy + .8, L.tw / K);
  const ink = night ? '#2f2617' : '#4d3c27';
  ctx.fillStyle = ink; ctx.fillText(TEXT, fx, fy, L.tw / K);
  // small arrow: down-right in the board plane = along the road out of the village, towards the farm
  const ax = (L.pad + L.tw + L.gap) / K, ay = bh / 2 - L.arrow / K / 2, a = L.arrow / K;
  ctx.strokeStyle = ink; ctx.lineWidth = 1.7; ctx.lineCap = 'round'; ctx.lineJoin = 'round';
  ctx.beginPath(); ctx.moveTo(ax, ay); ctx.lineTo(ax + a, ay + a); ctx.stroke();
  ctx.beginPath(); ctx.moveTo(ax + a * .35, ay + a); ctx.lineTo(ax + a, ay + a); ctx.lineTo(ax + a, ay + a * .35); ctx.stroke();
  ctx.restore();
}

// Background part. `s` draws on the world canvas; ctx is its context (any transform, restored on exit).
export function paintGate(s, ctx, scale) {
  const L = layout();
  ctx.save(); ctx.setTransform(scale, 0, 0, scale, 0, 0);
  const foot = [W(0, 0), W(SPAN, 0)];
  // grass tufts and a flower at the post feet (as at the farm sign)
  for (const [k, p] of foot.entries()) {
    s.ellipse(p.x + 3, p.y + 1, 7, 2.6, '#86a96a');
    for (let i = 0; i < 3; i++) s.line(p.x + 3 + (i - 1) * 3, p.y + 1, p.x + 3 + (i - 1) * 4, p.y - 4 - i % 2 * 2, '#6f9a5c', 1.2);
    if (k) { s.line(p.x + 8, p.y + 1, p.x + 8, p.y - 5, '#7ea468', 1); s.ellipse(p.x + 8, p.y - 6, 2, 1.7, '#e7a8b5') }
  }
  // posts: the farm sign posts, a little stouter for an arch over a road
  for (const p of foot) {
    const top = p.y - POST_H;
    s.line(p.x, p.y + 1, p.x, top + 3, '#5f4630', 5.4); s.line(p.x - 1, p.y, p.x - 1, top + 3, '#8c6c4a', 2.6);
    s.ellipse(p.x, p.y + 1, 4.6, 2, '#7a6246');
    s.poly([{x: p.x - 5, y: top + 3}, {x: p.x, y: top - 3.5}, {x: p.x + 5, y: top + 3}], '#6b5036', '#4e3a27', .8);
  }
  // arched crossbeam in the arch plane (light upper edge), and a straight bracket past the far post for the lantern
  const arch = (dh, col, w) => {ctx.beginPath(); for (let u = -3; u <= SPAN + 3; u += 2) {const p = W(u, archH(u) + dh); u > -3 ? ctx.lineTo(p.x, p.y) : ctx.moveTo(p.x, p.y)}
    ctx.strokeStyle = col; ctx.lineWidth = w; ctx.lineCap = 'round'; ctx.lineJoin = 'round'; ctx.stroke()};
  arch(0, '#5f4630', 4.2); arch(1.3, '#8c6c4a', 1.3);
  const k0 = W(SPAN, BEAM_H - 1), k1 = W(SPAN + 12, BEAM_H - 1);
  s.line(k0.x, k0.y, k1.x, k1.y, '#5f4630', 2.2);
  // two short chains from the beam to the board's top corners (the board itself is the game's button)
  for (const u of [L.left + 7, L.left + L.bw - 7]) {
    const a = W(u, archH(u) - 1.5), b = W(u, BOARD_TOP);
    s.line(a.x, a.y, b.x, b.y, '#4e3a27', 1.1); s.ellipse(a.x, a.y + 1, 1.3, 1.3, '#4e3a27');
  }
  // lantern hanging from the beam end, like the one on the farm's name sign
  const lu = SPAN + 10, h0 = W(lu, BEAM_H - 1), lt = W(lu, BEAM_H - 7);
  s.line(h0.x, h0.y, lt.x, lt.y, '#4e3a27', 1);
  const ly = lt.y + 6, lx = lt.x;
  s.poly([{x: lx - 4, y: ly - 6}, {x: lx + 4, y: ly - 6}, {x: lx + 3.5, y: ly + 4}, {x: lx - 3.5, y: ly + 4}], '#d9c58c', '#4e3a27', 1);
  s.poly([{x: lx - 5.5, y: ly - 6}, {x: lx, y: ly - 10}, {x: lx + 5.5, y: ly - 6}], '#4e3a27');
  ctx.restore();
  return {lantern: [Math.round(lx), Math.round(ly - 1)], posts: foot.map(p => [p.x, p.y])};
}

// The button art: day and night boards in one SVG (CSS shows one), plus the transparent hit shape = the board,
// padded so the tap target stays >= 44 css px at the smallest world (1600 px wide). Returns the SVG and its box in %.
export function boardSvg() {
  const L = layout(), padHit = 4;
  const day = new SvgCtx('vgd'), night = new SvgCtx('vgn');
  boardInto(day, L, false); boardInto(night, L, true);
  const corners = [[L.left - padHit, BOARD_TOP + padHit], [L.left + L.bw + padHit, BOARD_TOP + padHit],
    [L.left + L.bw + padHit, BOARD_TOP - BOARD_H - padHit], [L.left - padHit, BOARD_TOP - BOARD_H - padHit]].map(([u, h]) => W(u, h));
  const xs = corners.map(p => p.x), ys = corners.map(p => p.y), x0 = Math.floor(Math.min(...xs)), y0 = Math.floor(Math.min(...ys));
  const x1 = Math.ceil(Math.max(...xs)), y1 = Math.ceil(Math.max(...ys));
  const hit = 'M' + corners.map(p => `${+p.x.toFixed(2)} ${+p.y.toFixed(2)}`).join('L') + 'Z';
  const svg = `<svg class="vg-sign" viewBox="${x0} ${y0} ${x1 - x0} ${y1 - y0}" aria-hidden="true" focusable="false">` +
    `<g class="vg-day">${day.svg()}</g><g class="vg-night">${night.svg()}</g>` +
    `<path class="vg-hit" d="${hit}" fill="transparent"/></svg>`;
  return {svg, box: [x0, y0, x1 - x0, y1 - y0], pct: [+(x0 / 24).toFixed(3), +(y0 / 18).toFixed(3), +((x1 - x0) / 24).toFixed(3), +((y1 - y0) / 18).toFixed(3)]};
}
