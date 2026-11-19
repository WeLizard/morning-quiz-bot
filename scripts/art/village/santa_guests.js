// «Битва с Сантой» guests in the village (docs/tasks/FARM_SANTA_BATTLE.md §2): while the New Year lasts Дед Мороз and
// Снегурочка stand by the swan pond with the guests Санта and Крампус; a touch walks the player there and opens the battle.
// A separate live button like Jack (pumpkin_jack.js), never part of the map raster. The figures are new_year_guests.js
// 'stand' poses, one figure unit = one world unit (the player's figure is 60 CSS px tall at the 2400 px village width).
import {FarmScene} from '/static/scene.js';
import {SvgCtx} from './svg_ctx.js';
import {dedMoroz, snegurochka, santa, krampus} from './new_year_guests.js';

export const GUESTS_BOX = [-72, -60, 144, 66];   // figure units; the group's feet line is y=0, its middle x=0
// back row first: the outer figures stand a step behind, Дед Мороз and Санта face each other in front
const LINEUP = [[snegurochka, -48, -2], [krampus, 49, -2], [dedMoroz, -20, 1], [santa, 21, 1]];

export function guestsSvg() {
  const c = new SvgCtx('nyg'), s = Object.create(FarmScene.prototype);
  s.c = c; s.time = 0; s.motion = false; s.inStatic = true; s.shadowLevel = 0;
  // trodden snow under the group so it reads as one place on the square, not four stickers
  s.ellipse(0, 1, 66, 5.5, '#dfe7ee'); s.ellipse(0, .6, 60, 4.2, '#eef3f6');
  for (const [draw, x, y] of LINEUP) { c.save(); c.translate(x, y); draw(s, 'stand'); c.restore(); }
  return `<svg xmlns="http://www.w3.org/2000/svg" class="ny-guests-art" viewBox="${GUESTS_BOX.join(' ')}" aria-hidden="true" focusable="false">${c.svg()}</svg>`;
}

// Where the group stands: the snowy meadow by the swan pond south of the square (owner's choice 2026-11-19 out of the
// clean spots; the square by the fir is full of stalls, benches and tap targets). POND is the tile the search starts from;
// the nearest spot that passes every check wins, so a changed map moves the group a little instead of breaking it.
export const POND = [27.55, 28.75];

export function placeGuests(K, V, fir, scale = 1) {
  // 1.6×0.8 tiles: the feet of the four
  const foot = 1.6;
  // No part of the picture may lie under a tap target of the village: buttons are fixed CSS px (up to 62×44) and the
  // village is 1600 CSS px wide at its smallest, 1.5 world units per px, so every sample point of the box keeps BUTTON_R
  // world units from every button centre.
  const BUTTON_R = 56, [a0, , , d0] = V.matrix;
  const clearOfButtons = (cx, cy) => {
    const p0 = V.P(cx, cy), p1 = V.P(cx + 1, cy - 1), perTile = a0 * (p1.x - p0.x);   // (1,-1) runs across the screen
    for (let sx = GUESTS_BOX[0]; sx <= GUESTS_BOX[0] + GUESTS_BOX[2] + .1; sx += GUESTS_BOX[2] / 6)
      for (const sy of [0, -30, -60]) { const t = sx * scale / perTile; if (!V.clear(cx + t, cy - t, -sy * scale / d0, BUTTON_R)) return false }
    return true;
  };
  const cands = [];
  for (let x = POND[0] - 4; x <= POND[0] + 4; x += .25) for (let y = POND[1] - 4; y <= POND[1] + 4; y += .25) cands.push([Math.hypot(x + foot / 2 - POND[0], y + foot / 4 - POND[1]), x, y]);
  cands.sort((p, q) => p[0] - q[0] || p[1] - q[1] || p[2] - q[2]);
  let at = null;
  for (const [, x, y] of cands) {
    if (!clearOfButtons(x + foot / 2, y + foot / 4)) continue;
    const n = K.problems.length;
    at = K.place({w: foot, d: foot / 2, h: 64 * scale, near: POND, area: [x, y, x + foot + .001, y + foot / 2 + .001], button: 0, cover: .25, margin: .05, path: .1, what: 'New Year guests'});
    K.problems.splice(n);
    if (at) break;
  }
  if (!at) { K.problems.push('new_year: no place for the guests by the pond'); return null; }
  const tile = [at[0] + foot / 2, at[1] + foot / 4], p = V.P(...tile), [a, , , d, e, f] = V.matrix;
  const world = ([x, y]) => [a * x + e, d * y + f].map(v => +v.toFixed(2));
  const anchor = world([p.x, p.y]);
  const box = [anchor[0] + GUESTS_BOX[0] * scale, anchor[1] + GUESTS_BOX[1] * scale, GUESTS_BOX[2] * scale, GUESTS_BOX[3] * scale].map(v => +v.toFixed(2));
  const approaches = [];
  for (const [index, [ax, ay, bx, by]] of (V.walk || []).entries()) {
    const dx = bx - ax, dy = by - ay, t = Math.max(0, Math.min(1, ((tile[0] - ax) * dx + (tile[1] - ay) * dy) / (dx * dx + dy * dy || 1)));
    const q = [ax + t * dx, ay + t * dy];
    let clear = true;
    for (let u = .35; u <= 1; u += .1) if (!V.free(tile[0] + (q[0] - tile[0]) * u, tile[1] + (q[1] - tile[1]) * u)) { clear = false; break; }
    if (clear) approaches.push({index, t, tile: q, distance: Math.hypot(q[0] - tile[0], q[1] - tile[1])});
  }
  approaches.sort((x, y) => x.distance - y.distance || x.index - y.index);
  const near = approaches[0], qp = near && V.P(...near.tile);
  if (!near) K.problems.push('new_year: the guests have no clear graph approach');
  return {svg: guestsSvg(), anchor, box, scale, tile: tile.map(v => +v.toFixed(4)), footprint: [...at, at[0] + foot, at[1] + foot / 2],
    approach: near ? {world: world([qp.x, qp.y]), tile: near.tile.map(v => +v.toFixed(4)), edge_index: near.index} : null,
    viewBox: GUESTS_BOX, position_contract: 'world units 2400x1800; separate live button; feet line at local y=0',
    visibility: 'new_year festival only (village_games.santa_battle.available)'};
}

export function render() { return {svg: guestsSvg(), viewBox: GUESTS_BOX}; }
