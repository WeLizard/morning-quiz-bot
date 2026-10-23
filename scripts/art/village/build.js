// Construction art of the village (docs/tasks/FARM_VILLAGE_CONSTRUCTION.md §6): the stages of every construction site and the
// stalls of the market rows, vector, drawn with the farm's own primitives (scene_buildings.js via B) into the recording context
// (svg_ctx.js). The background (village.js) keeps only the level ground of the sites and the empty stall places.
//   site-<id>-<stage>  stage: soon (sign and marking), pit (pit, spoil heaps, shovels, barrow), frame (timber frame and
//                      scaffolding), done (the finished building); site-<id>-done-night: its lit windows (above the night tint)
//   stall-<id>-<state> state: closed (shutters, rolled awning) | open (awning, goods); stall-<id>-open-night: its lantern
// Each piece is one <symbol> with its own viewBox in world units (2400×1800), so the game places it by that box.
// crew: where the foreman Krot and two residents stand while a site is worked on (world units, foot points).
import {FarmScene} from '/static/scene.js';
import {SvgCtx} from './svg_ctx.js';

const WOOD = '#b48f66', WOOD_D = '#8a6c4c', WOOD_L = '#c9a57a', SOIL = '#8a6a4a', SOIL_D = '#6f553b', SOIL_L = '#a8865f';
const STONE = '#b9b3a0', STONE_L = '#cfc9b6', ROPE = '#e9e1cc', RIBBON = '#d96f5e';

// owners of the stalls: [id, awning colour, awning stripe, board colour] (FARM_VILLAGE_CONSTRUCTION.md §5.1)
export const STALL_OWNERS = [
  ['magpie', '#3f5a6e', '#f4ede0', '#2f3a44'],    // Сорока, «Заезжие товары»: black-white-teal of the magpie
  ['igor', '#8fae6f', '#f1dc8a', '#6f8f54'],      // Суслик Игорь, семенной ларёк
  ['sonya', '#c97a8a', '#f4ede0', '#a85d6c'],     // Кошка Соня, ткацкая лавка
  ['agata', '#7b5a8a', '#e8c25a', '#5f4570'],     // Агата, лавка прошлых праздников
  ['post', '#5f7f9a', '#e9e1cc', '#d9553f'],      // Почтальон Ёж, почтовое окно
  ['player', '#c9a672', '#f4ede0', '#8a6c4c'],    // лавка игрока
];

export function buildArt(V) {
  // V: {B, P, matrix, sites:{id:[x0,y0,x1,y1]}, slots:[[x0,y0,x1,y1]] (tiles)}
  const {B, P} = V, [ma, , , md, me, mf] = V.matrix;
  const toWorld = (x, y, z = 0) => { const p = P(x, y, z); return [ma * p.x + me, md * p.y + mf] };
  const pieces = {};
  // a recording scene for one piece; box = tile footprint and height (farm px) the piece may reach, for its viewBox
  const piece = (id, [x0, y0, x1, y1], h, draw, margin = 14) => {
    const c = new SvgCtx(id.replace(/[^a-z]/g, '').slice(0, 6)), s = Object.create(FarmScene.prototype);
    Object.assign(s, {c, time: 0, motion: false, inStatic: true, shadowLevel: 0, win: []});
    draw(s, c);
    const pts = [];
    for (const [x, y] of [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]) for (const z of [0, h]) pts.push(toWorld(x, y, z));
    const xs = pts.map(p => p[0]), ys = pts.map(p => p[1]);
    const box = [Math.floor(Math.min(...xs) - margin), Math.floor(Math.min(...ys) - margin)];
    box.push(Math.ceil(Math.max(...xs) + margin) - box[0], Math.ceil(Math.max(...ys) + margin * .5) - box[1]);
    const body = `<g transform="matrix(${V.matrix.map(v => +v.toFixed(4)).join(' ')})">${c.svg()}</g>`;
    pieces[id] = {box, body, windows: s.win};
    return s;
  };
  // the warm windows of a finished building, recorded by winX/winY while it was drawn (like the night lights of the village)
  const night = (id, extra = [], panes = []) => {
    const c = new SvgCtx(id.slice(0, 6) + 'n'), s = Object.create(FarmScene.prototype);
    Object.assign(s, {c, time: 0, motion: false, inStatic: true, shadowLevel: 0});
    for (const [kind, X, Y, w, h] of pieces[id].windows) {
      const ax = (kind === 'a' ? 18 : -18) * w, ay = 9 * w, hh = h / 2, g = 3;
      s.poly([{x: X - ax - g, y: Y - ay - hh - g}, {x: X + ax + g, y: Y + ay - hh - g}, {x: X + ax + g, y: Y + ay + hh + g}, {x: X - ax - g, y: Y - ay + hh + g}], 'rgba(255,200,95,.22)');
      s.poly([{x: X - ax, y: Y - ay - hh}, {x: X + ax, y: Y + ay - hh}, {x: X + ax, y: Y + ay + hh}, {x: X - ax, y: Y - ay + hh}], 'rgba(255,226,160,.88)');
    }
    for (const q of panes) B.Q(s, 'rgba(255,214,140,.38)', q);   // lit glass
    for (const [x, y, z, r] of extra) { const p = P(x, y, z); s.ellipse(p.x, p.y, r, r * .66, 'rgba(255,200,95,.24)'); s.ellipse(p.x, p.y, r * .45, r * .3, 'rgba(255,226,160,.5)') }
    pieces[id + '-night'] = {box: pieces[id].box, body: `<g transform="matrix(${V.matrix.map(v => +v.toFixed(4)).join(' ')})">${c.svg()}</g>`};
  };

  // ---------------- pieces every stage reuses ----------------
  const peg = (s, x, y, h = 12) => { B.L(s, x, y, 0, x, y, h, WOOD_D, 1.6); const q = P(x, y, h - 1); s.poly([q, {x: q.x + 7, y: q.y + 2}, {x: q.x, y: q.y + 4}], RIBBON) };
  const string = (s, pts, z = 3) => { for (let i = 0; i < pts.length; i++) { const [a, b] = pts[i], [c2, d] = pts[(i + 1) % pts.length]; B.L(s, a, b, z, c2, d, z, ROPE, 1) } };
  const planks = (s, x, y, n = 2, w = 1, d = .35) => { for (let i = 0; i < n; i++) B.fullBox(s, i % 2 ? WOOD_L : '#c9a672', x + i * .05, y + i * .05, x + w + i * .05, y + d + i * .05, i * 4, i * 4 + 4, i % 2 ? '#e3c595' : '#dbb987') };
  const stones = (s, x, y) => { B.fullBox(s, STONE, x, y, x + .5, y + .45, 0, 7, STONE_L); B.fullBox(s, STONE, x + .1, y + .05, x + .4, y + .35, 7, 12, '#d8d2c0') };
  // the sign of a site: two posts and a board with a pinned blueprint (no words: the game writes the caption on top)
  const sign = (s, x, y) => {
    for (const d of [-.22, .22]) B.L(s, x, y + d, 0, x, y + d, 30, '#7a6046', 2);
    const a = P(x, y - .3, 40), b = P(x, y + .3, 40), c2 = P(x, y + .3, 22), d = P(x, y - .3, 22);
    s.poly([a, b, c2, d], '#efe2c2', '#a88a62', 1.4);
    const k = (u, v) => ({x: a.x + (b.x - a.x) * u + (d.x - a.x) * v, y: a.y + (b.y - a.y) * u + (d.y - a.y) * v});
    s.poly([k(.12, .14), k(.88, .14), k(.88, .86), k(.12, .86)], '#9fc0d4');
    s.poly([k(.3, .72), k(.3, .45), k(.5, .28), k(.7, .45), k(.7, .72)], null, '#f4f7f8', 1.2);   // a little house drawn on the blueprint
    s.line(k(.45, .72).x, k(.45, .72).y, k(.45, .55).x, k(.45, .55).y, '#f4f7f8', 1);
  };
  const shovel = (s, x, y, lean = 1) => { const a = P(x, y, 2), b = P(x, y, 26); s.line(a.x, a.y, b.x + 5 * lean, b.y, WOOD_D, 1.8); s.poly([{x: a.x - 3, y: a.y + 1}, {x: a.x + 3, y: a.y + 1}, {x: a.x + 2, y: a.y + 7}, {x: a.x - 2, y: a.y + 7}], '#8f949c');
    s.line(b.x + 5 * lean - 3, b.y, b.x + 5 * lean + 3, b.y, WOOD_D, 1.8) };
  const barrow = (s, x, y) => { B.Q(s, '#7f8a86', [x - .3, y - .18, 6, x + .3, y - .18, 9, x + .3, y + .18, 9, x - .3, y + .18, 6]); B.fullBox(s, '#6f7a76', x - .28, y - .16, x + .28, y + .16, 2, 8, SOIL);
    const w = P(x + .34, y, 3); s.ellipse(w.x, w.y, 3.6, 3.6, '#3d4a3f'); s.ellipse(w.x, w.y, 1.4, 1.4, '#a8a6a0'); B.L(s, x - .3, y - .1, 6, x - .6, y - .12, 10, WOOD_D, 1.6); B.L(s, x - .3, y + .1, 6, x - .6, y + .08, 10, WOOD_D, 1.6) };
  const heap = (s, x, y, r = 16) => { const p = P(x, y); s.ellipse(p.x + 2, p.y + 1, r, r * .45, 'rgba(70,55,35,.18)'); s.ellipse(p.x, p.y - 3, r * .9, r * .5, SOIL); s.ellipse(p.x - r * .2, p.y - 6, r * .55, r * .32, SOIL_L) };
  // a pit dug in the footprint (inset by m): the far walls show the depth, the floor is darker
  const pit = (s, x0, y0, x1, y1, depth = 9) => {
    B.Q(s, SOIL_D, [x0, y0, -depth, x1, y0, -depth, x1, y1, -depth, x0, y1, -depth]);
    B.Q(s, '#7e6146', [x0, y0, 0, x1, y0, 0, x1, y0, -depth, x0, y0, -depth]);   // far wall along x
    B.Q(s, '#735842', [x0, y0, 0, x0, y1, 0, x0, y1, -depth, x0, y0, -depth]);   // far wall along y
    B.L(s, x0, y1, 0, x1, y1, 0, SOIL_L, 1.6); B.L(s, x1, y0, 0, x1, y1, 0, SOIL_L, 1.6);
  };
  // a timber frame with a gable of rafters, scaffold along the front (x side), a ladder
  const frame = (s, x0, y0, x1, y1, H, axis = 'y', R = 22) => {
    B.fullBox(s, STONE, x0 - .04, y0 - .04, x1 + .04, y1 + .04, 0, 4, STONE_L);
    const posts = [];
    for (let i = 0; i <= 3; i++) { const t = i / 3; posts.push([x0 + (x1 - x0) * t, y0], [x0 + (x1 - x0) * t, y1]) }
    for (let i = 1; i < 3; i++) { const t = i / 3; posts.push([x0, y0 + (y1 - y0) * t], [x1, y0 + (y1 - y0) * t]) }
    const back = posts.filter(([x, y]) => x + y < (x0 + x1) / 2 + (y0 + y1) / 2 + .01), front = posts.filter(p => !back.includes(p));
    const beam = z => { B.L(s, x0, y0, z, x1, y0, z, WOOD, 2.2); B.L(s, x0, y0, z, x0, y1, z, WOOD, 2.2); B.L(s, x0, y1, z, x1, y1, z, WOOD_L, 2.4); B.L(s, x1, y0, z, x1, y1, z, WOOD_L, 2.4) };
    for (const [x, y] of back) B.L(s, x, y, 4, x, y, H, WOOD_D, 2.4);
    beam(H * .5); beam(H);
    // rafters: gables along the axis
    const m = axis === 'y' ? (x0 + x1) / 2 : (y0 + y1) / 2, n = 4;
    for (let i = 0; i <= n; i++) {
      const t = i / n;
      if (axis === 'y') { const y = y0 + (y1 - y0) * t; B.L(s, x0, y, H, m, y, H + R, '#a98058', 2); B.L(s, x1, y, H, m, y, H + R, WOOD_L, 2) }
      else { const x = x0 + (x1 - x0) * t; B.L(s, x, y0, H, x, m, H + R, '#a98058', 2); B.L(s, x, y1, H, x, m, H + R, WOOD_L, 2) }
    }
    if (axis === 'y') B.L(s, m, y0, H + R, m, y1, H + R, WOOD_D, 2.4); else B.L(s, x0, m, H + R, x1, m, H + R, WOOD_D, 2.4);
    for (const [x, y] of front) B.L(s, x, y, 4, x, y, H, WOOD_D, 2.4);
    for (let i = 0; i < 3; i++) { const t = (i + .5) / 3; B.L(s, x0 + (x1 - x0) * (t - .16), y1, 4, x0 + (x1 - x0) * (t + .16), y1, H * .5, '#a98058', 1.6) }   // braces
    // scaffold along the front x side: poles, two decks of planks, a ladder
    const sx = x1 + .32;
    for (let i = 0; i <= 2; i++) { const y = y0 + (y1 - y0) * i / 2; B.L(s, sx, y, 0, sx, y, H + 6, '#9c8a6a', 1.6) }
    for (const z of [H * .45, H * .9]) { B.Q(s, '#d8b886', [x1 + .06, y0, z, sx + .06, y0, z, sx + .06, y1, z, x1 + .06, y1, z]); B.L(s, sx + .06, y0, z, sx + .06, y1, z, WOOD_D, 1.2) }
    const la = [sx + .3, y1 - .4];
    B.L(s, la[0], la[1] - .1, 0, sx + .04, la[1] - .1, H * .45, WOOD_D, 1.4); B.L(s, la[0], la[1] + .1, 0, sx + .04, la[1] + .1, H * .45, WOOD_D, 1.4);
    for (let k = 1; k < 5; k++) { const f = k / 5, x = la[0] + (sx + .04 - la[0]) * f; B.L(s, x, la[1] - .1, H * .45 * f, x, la[1] + .1, H * .45 * f, WOOD, 1.2) }
  };

  // ---------------- the finished buildings ----------------
  const tavern = (s, [x0, y0, x1, y1]) => {
    B.ground(s, x0, y0, x1, y1, 'rgba(205,185,140,.4)');
    const g = B.gparams({x0: x0 + .25, y0: y0 + .25, x1: x1 - .5, y1: y1 - .3, H: 40, col: '#c98f5a', roof: '#a5533f', axis: 'y', prof: B.GABLE, R: 30, ov: .14, base: STONE,
      corner: '#a8713f', trim: '#e9d2a8'}, {});
    B.body(s, g); const xm = (g.x0 + g.x1) / 2;
    for (let z = 5; z < g.H; z += 5) { B.L(s, g.x0, g.y1, z, g.x1, g.y1, z, 'rgba(90,55,25,.35)', .9); B.L(s, g.x1, g.y0, z, g.x1, g.y1, z, 'rgba(90,55,25,.35)', .9) }   // logs
    B.winY(s, g.y1, xm - .45, 8, .32, 12); B.winY(s, g.y1, xm + .45, 8, .32, 12); B.winY(s, g.y1, xm, 25, .36, 11);
    const yd = (g.y0 + g.y1) / 2;
    B.doorX(s, g.x1, yd, .4, 22, '#7a5236', '#e9d2a8', true); B.winX(s, g.x1, g.y0 + .35, 9, .3, 12); B.winX(s, g.x1, g.y1 - .35, 9, .3, 12);
    B.winX(s, g.x1, g.y0 + .5, 26, .3, 10); B.winX(s, g.x1, g.y1 - .5, 26, .3, 10);
    // porch roof over the door, the sign with a mug on a bracket
    B.Q(s, '#b5644c', [g.x1, yd - .5, 30, g.x1, yd + .5, 30, g.x1 + .42, yd + .5, 24, g.x1 + .42, yd - .5, 24]); B.L(s, g.x1 + .42, yd - .5, 24, g.x1 + .42, yd + .5, 24, '#8a4636', 1.6);
    for (const d of [-.46, .46]) B.L(s, g.x1 + .4, yd + d, 0, g.x1 + .4, yd + d, 24, WOOD_D, 2);
    B.roofOf(s, g);
    B.chimney(s, xm + .1, g.y0 + .45, g.H + 12, g.H + 38, '#9a6a4e', .12);
    B.L(s, g.x1, g.y1 - .1, 30, g.x1 + .5, g.y1 - .1, 30, WOOD_D, 1.6);
    const sg = P(g.x1 + .42, g.y1 - .1, 22); s.poly([{x: sg.x - 9, y: sg.y - 4}, {x: sg.x + 9, y: sg.y + 5}, {x: sg.x + 9, y: sg.y + 15}, {x: sg.x - 9, y: sg.y + 6}], '#efe2c2', '#8a6c4c', 1.2);
    s.poly([{x: sg.x - 3, y: sg.y + 1}, {x: sg.x + 3, y: sg.y + 4}, {x: sg.x + 3, y: sg.y + 11}, {x: sg.x - 3, y: sg.y + 8}], '#d9a650'); s.ellipse(sg.x + 4.6, sg.y + 6.6, 2.2, 2.6, 'none');
    s.line(sg.x + 3, sg.y + 5, sg.x + 6, sg.y + 6.4, '#d9a650', 1.4); s.line(sg.x + 6, sg.y + 6.4, sg.x + 5.6, sg.y + 9.6, '#d9a650', 1.4); s.line(sg.x + 5.6, sg.y + 9.6, sg.x + 3, sg.y + 9, '#d9a650', 1.4);
    s.ellipse(sg.x, sg.y + 1.4, 3.4, 1.6, '#f6f0e0');                                                                           // foam
    // barrels, a bench and a table by the porch
    B.barrel(s, x1 - .2, y0 + .45, .16, 13, '#a8784c'); B.barrel(s, x1 - .2, y0 + .85, .16, 13, '#b98a5c');
    B.fullBox(s, WOOD, x1 - .3, y1 - .4, x1 - .08, y1 - .12, 6, 8, WOOD_L); B.flowerPot(s, g.x0 - .05, g.y1 + .15);
  };
  const greenhouse = (s, [x0, y0, x1, y1]) => {
    B.ground(s, x0, y0, x1, y1, 'rgba(190,175,135,.38)');
    const a = x0 + .25, b = y0 + .25, c2 = x1 - .3, d = y1 - .3, H = 22, R = 18, xm = (a + c2) / 2;
    B.shadowAt(s, a, b, c2, d, 56, 22);
    B.fullBox(s, '#b7735a', a, b, c2, d, 0, 5, '#c98a6a');                                                                  // brick plinth
    const glass = 'rgba(190,225,230,.55)', frameC = '#f4f1e6';
    B.Q(s, 'rgba(170,205,210,.5)', [a, b, 5, c2, b, 5, c2, b, H, a, b, H]); B.Q(s, 'rgba(160,198,205,.5)', [a, b, 5, a, d, 5, a, d, H, a, b, H]);
    // plants inside, seen through the glass
    for (let i = 0; i < 4; i++) for (let j = 0; j < 2; j++) { const p = P(a + .35 + i * (c2 - a - .5) / 3, b + .45 + j * (d - b - .7), 6); s.ellipse(p.x, p.y - 4, 7, 5, j ? '#7da073' : '#8fbb7c'); s.ellipse(p.x - 2, p.y - 7, 3, 2.4, i % 2 ? '#e7a8b5' : '#e8c25a') }
    B.Q(s, glass, [a, d, 5, c2, d, 5, c2, d, H, a, d, H]); B.Q(s, 'rgba(200,232,236,.5)', [c2, b, 5, c2, d, 5, c2, d, H, c2, b, H]);
    for (let i = 0; i <= 4; i++) { const x = a + (c2 - a) * i / 4; B.L(s, x, d, 5, x, d, H, frameC, 1.4) }
    for (let i = 0; i <= 3; i++) { const y = b + (d - b) * i / 3; B.L(s, c2, y, 5, c2, y, H, frameC, 1.4) }
    B.L(s, a, d, H, c2, d, H, frameC, 1.6); B.L(s, c2, b, H, c2, d, H, frameC, 1.6); B.L(s, a, d, 13, c2, d, 13, frameC, 1); B.L(s, c2, b, 13, c2, d, 13, frameC, 1);
    // glass gable roof along y, ridge with a vent
    B.Q(s, 'rgba(200,228,232,.6)', [a, b, H, xm, b, H + R, xm, d, H + R, a, d, H]); B.Q(s, 'rgba(220,240,242,.62)', [c2, b, H, xm, b, H + R, xm, d, H + R, c2, d, H]);
    for (let i = 0; i <= 3; i++) { const y = b + (d - b) * i / 3; B.L(s, c2, y, H, xm, y, H + R, frameC, 1.3); B.L(s, a, y, H, xm, y, H + R, 'rgba(244,241,230,.7)', 1) }
    B.L(s, xm, b, H + R, xm, d, H + R, frameC, 2); B.Q(s, '#c9d8d8', [xm - .1, b + .5, H + R + 1, xm + .1, b + .5, H + R + 1, xm + .1, b + 1.1, H + R + 4, xm - .1, b + 1.1, H + R + 4]);
    B.doorX(s, c2, (b + d) / 2, .36, 16, 'rgba(180,215,220,.75)', frameC);
    B.planter(s, a + .1, d + .08, 1, ['#e7a8b5', '#e8c25a', '#d9553f']); B.flowerPot(s, c2 + .22, d - .1);
  };
  const fairground = (s, [x0, y0, x1, y1]) => {
    B.ground(s, x0, y0, x1, y1, 'rgba(220,205,160,.42)');
    // two striped tents and a small stage, bunting between the poles
    const tent = (x, y, r, H, c1, c2) => {
      B.shadowAt(s, x - r, y - r, x + r, y + r, 34 * r / .5, 14 * r / .5);
      const n = 10, base = [];
      for (let i = 0; i < n; i++) { const a = i / n * Math.PI * 2; base.push([x + Math.cos(a) * r, y + Math.sin(a) * r]) }
      for (let i = 0; i < n; i++) { const [ax, ay] = base[i], [bx, by] = base[(i + 1) % n]; if (Math.sin((i + .5) / n * Math.PI * 2) + Math.cos((i + .5) / n * Math.PI * 2) < -.2) continue;
        B.Q(s, i % 2 ? c2 : c1, [ax, ay, 0, bx, by, 0, bx, by, H * .45, ax, ay, H * .45]) }
      for (let i = 0; i < n; i++) { const [ax, ay] = base[i], [bx, by] = base[(i + 1) % n]; if (Math.sin((i + .5) / n * Math.PI * 2) + Math.cos((i + .5) / n * Math.PI * 2) < -.6) continue;
        B.Q(s, i % 2 ? c1 : c2, [ax, ay, H * .45, bx, by, H * .45, x, y, H, x, y, H]) }
      const ent = P(x + r * .7, y + r * .7, 0); s.poly([{x: ent.x - 5, y: ent.y}, {x: ent.x + 5, y: ent.y - 3}, {x: ent.x + 3, y: ent.y - 15}, {x: ent.x - 2, y: ent.y - 15}], '#5a3f2e');
      B.L(s, x, y, H, x, y, H + 10, WOOD_D, 1.4); const f = P(x, y, H + 9); s.poly([f, {x: f.x + 9, y: f.y + 2}, {x: f.x, y: f.y + 5}], c1);
    };
    const st = [x0 + .3, y0 + .3, x0 + 1.3, y0 + 1.1];
    B.fullBox(s, WOOD, st[0], st[1], st[2], st[3], 0, 7, WOOD_L); B.boards(s, 'y', st[3], st[0], st[2], 0, 7, 3.5, 'rgba(80,55,30,.25)');
    B.L(s, st[0], st[1], 7, st[0], st[1], 34, WOOD_D, 2); B.L(s, st[2], st[1], 7, st[2], st[1], 34, WOOD_D, 2); B.Q(s, '#c9604f', [st[0], st[1] + .02, 34, st[2], st[1] + .02, 34, st[2], st[1] + .02, 22, st[0], st[1] + .02, 22]);
    tent(x1 - .7, y0 + .75, .55, 46, '#d9553f', '#f4ede0'); tent(x0 + .9, y1 - .6, .5, 40, '#7fa3c4', '#f4ede0');
    const posts = [[x0 + .15, y1 - .1], [x1 - .15, y1 - .1], [x1 - .1, y0 + .15]];
    for (const [x, y] of posts) B.L(s, x, y, 0, x, y, 36, WOOD_D, 1.8);
    const flags = ['#d9553f', '#e8c25a', '#8fae86', '#7fa3c4', '#e7a8b5'];
    for (let k = 0; k < posts.length - 1; k++) { const [ax, ay] = posts[k], [bx, by] = posts[k + 1], n = 8;
      for (let i = 0; i < n; i++) { const p = P(ax + (bx - ax) * i / n, ay + (by - ay) * i / n, 35 - 6 * Math.sin(Math.PI * i / n)), q = P(ax + (bx - ax) * (i + .6) / n, ay + (by - ay) * (i + .6) / n, 35 - 6 * Math.sin(Math.PI * (i + .6) / n));
        s.poly([p, q, {x: (p.x + q.x) / 2, y: (p.y + q.y) / 2 + 7}], flags[(i + k) % flags.length]) } }
    B.crate(s, x1 - .3, y1 - .3); B.barrel(s, x1 - .6, y1 - .25, .14, 11);
  };
  // the market rows when built: an arch with a board at the west end and a string of flags along the back of the stalls
  const rowsDone = (s, slots) => {
    const [ax0, ay0] = slots[0], ay1 = slots[0][3], xb = ax0 - .25;
    B.L(s, xb, ay0 - .05, 0, xb, ay0 - .05, 46, WOOD_D, 2.6); B.L(s, xb, ay1 + .05, 0, xb, ay1 + .05, 46, WOOD_D, 2.6);
    B.L(s, xb, ay0 - .15, 46, xb, ay1 + .15, 46, WOOD, 3);
    const a = P(xb, ay0 + .1, 52), b = P(xb, ay1 - .1, 52), c2 = P(xb, ay1 - .1, 40), d = P(xb, ay0 + .1, 40);
    s.poly([a, b, c2, d], '#efe2c2', '#8a6c4c', 1.4);
    const k = (u, v) => ({x: a.x + (b.x - a.x) * u + (d.x - a.x) * v, y: a.y + (b.y - a.y) * u + (d.y - a.y) * v});
    for (let i = 0; i < 3; i++) s.poly([k(.16 + i * .24, .78), k(.16 + i * .24, .4), k(.28 + i * .24, .2), k(.4 + i * .24, .4), k(.4 + i * .24, .78)], ['#d9553f', '#8fae6f', '#7fa3c4'][i]);   // three little awnings
    const flags = ['#d9553f', '#e8c25a', '#8fae86', '#7fa3c4', '#e7a8b5', '#c3b0de'];
    const back = slots.map(([x0, y0, x1]) => [[x0 + .06, y0 + .06], [x1 - .06, y0 + .06]]).flat();
    for (let i = 0; i < back.length - 1; i++) { const [px0, py0] = back[i], [px1, py1] = back[i + 1], n = 4;
      for (let j = 0; j < n; j++) { const p = P(px0 + (px1 - px0) * j / n, py0, 40 - 3 * Math.sin(Math.PI * j / n)), q = P(px0 + (px1 - px0) * (j + .6) / n, py0, 40 - 3 * Math.sin(Math.PI * (j + .6) / n));
        s.poly([p, q, {x: (p.x + q.x) / 2, y: (p.y + q.y) / 2 + 6}], flags[(i * n + j) % flags.length]) } }
    for (let i = 0; i < back.length; i += 2) { const [x, y] = back[i]; B.L(s, x, y, 30, x, y, 41, WOOD_D, 1.6) }
  };

  // ---------------- the sites: four stages each ----------------
  const DONE = {tavern, greenhouse, fairground};
  const crew = {};
  for (const [id, fp] of Object.entries(V.sites)) {
    const [x0, y0, x1, y1] = fp, H = id === 'greenhouse' ? 24 : 36, tall = id === 'tavern' ? 92 : id === 'greenhouse' ? 50 : 62;
    const out = [x0 - .7, y0 - .5, x1 + .9, y1 + .7];   // the stages reach a little past the plot (stakes, heaps, scaffold, sign)
    piece(`site-${id}-soon`, out, 46, s => {
      const m = [[x0 - .15, y0 - .15], [x1 + .15, y0 - .15], [x1 + .15, y1 + .15], [x0 - .15, y1 + .15]];
      string(s, m); for (const [x, y] of m) peg(s, x, y);
      planks(s, x0 + .3, y1 - .9, 2); stones(s, x1 - 1, y1 - .8); sign(s, x1 + .45, (y0 + y1) / 2);
    });
    piece(`site-${id}-pit`, out, 40, s => {
      pit(s, x0 + .25, y0 + .25, x1 - .25, y1 - .25);
      heap(s, x0 - .25, y0 + .9, 18); heap(s, x0 + .9, y0 - .25, 16); heap(s, x1 + .45, y1 - .3, 14);
      shovel(s, x0 - .2, y0 + 1.15); shovel(s, x1 + .5, y1 - .1, -1); barrow(s, x1 + .45, y0 + .55);
      planks(s, x0 + .2, y1 + .2, 2, .9, .3); sign(s, x1 + .55, (y0 + y1) / 2 + .55);
    });
    piece(`site-${id}-frame`, out, H + 30, s => {
      frame(s, x0 + .3, y0 + .3, x1 - .45, y1 - .3, H, 'y', id === 'greenhouse' ? 16 : 24);
      planks(s, x0 - .45, y1 - .5, 3, .9, .3); heap(s, x0 - .3, y0 + .5, 12);
    });
    piece(`site-${id}-done`, [x0, y0, x1, y1], tall, s => DONE[id](s, fp));
    const gh = () => { const a = x0 + .25, b = y0 + .25, c2 = x1 - .3, d = y1 - .3, H = 22, R = 18, xm = (a + c2) / 2;
      return [[a, d, 5, c2, d, 5, c2, d, H, a, d, H], [c2, b, 5, c2, d, 5, c2, d, H, c2, b, H], [c2, b, H, xm, b, H + R, xm, d, H + R, c2, d, H]] };
    night(`site-${id}-done`, id === 'fairground' ? [[x1 - .7, y0 + .75, 30, 24], [x0 + .9, y1 - .6, 26, 22]] : [], id === 'greenhouse' ? gh() : []);
    // the crew: Krot by the sign with the blueprint, two residents at the work (foot points, world units)
    crew[id] = [toWorld(x1 + .55, (y0 + y1) / 2 + .3), toWorld(x0 + .5, y1 + .3), toWorld(x1 + .1, y0 + .35)].map(p => p.map(Math.round));
  }

  // the market rows as a site: marking, post holes, frames of the six stalls; when built, the arch and the flags
  const slots = V.slots, rx0 = slots[0][0], ry0 = slots[0][1], rx1 = slots[slots.length - 1][2], ry1 = slots[0][3];
  const rowsOut = [rx0 - .8, ry0 - .4, rx1 + .5, ry1 + .6];
  piece('site-stalls-soon', rowsOut, 46, s => {
    for (const [x0, y0, x1, y1] of slots) { const m = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]; string(s, m, 6); peg(s, x1, y1, 10) }
    sign(s, rx0 - .45, (ry0 + ry1) / 2); planks(s, rx1 - 1.2, ry1 + .15, 2, 1, .3);
  });
  piece('site-stalls-pit', rowsOut, 40, s => {
    for (const [x0, y0, x1, y1] of slots) { for (const [a, b] of [[x0 + .06, y0 + .06], [x1 - .06, y0 + .06], [x0 + .06, y1 - .06], [x1 - .06, y1 - .06]]) { const p = P(a, b); s.ellipse(p.x, p.y, 5, 2.6, SOIL_D); s.ellipse(p.x + 1, p.y + .6, 3, 1.4, '#4f3d2b') }
      heap(s, (x0 + x1) / 2, y1 + .25, 10) }
    shovel(s, rx0 - .3, ry1 + .1); barrow(s, rx1 + .2, ry0 + .4); sign(s, rx0 - .45, (ry0 + ry1) / 2);
  });
  piece('site-stalls-frame', rowsOut, 50, s => {
    for (const [x0, y0, x1, y1] of slots) {
      for (const [a, b, h] of [[x0 + .06, y0 + .06, 30], [x1 - .06, y0 + .06, 30], [x0 + .06, y1 - .06, 26], [x1 - .06, y1 - .06, 26]]) B.L(s, a, b, 0, a, b, h, WOOD_D, 2.2);
      B.L(s, x0 + .06, y0 + .06, 30, x1 - .06, y0 + .06, 30, WOOD, 2); B.L(s, x0 + .06, y1 - .06, 26, x1 - .06, y1 - .06, 26, WOOD_L, 2);
      B.L(s, x0 + .06, y0 + .06, 30, x0 + .06, y1 - .06, 26, WOOD, 2); B.L(s, x1 - .06, y0 + .06, 30, x1 - .06, y1 - .06, 26, WOOD_L, 2);
      B.fullBox(s, '#c9a672', x0, y0 + .35, x1, y0 + .55, 0, 11, '#d8b886');   // the counter half built
    }
    planks(s, rx0 - .7, ry1 - .2, 3, .8, .28);
  });
  piece('site-stalls-done', rowsOut, 56, s => rowsDone(s, slots));
  pieces['site-stalls-done-night'] = {box: pieces['site-stalls-done'].box, body: ''};
  crew.stalls = [toWorld(rx0 - .5, ry1 + .1), toWorld(slots[2][0] + .7, ry1 + .45), toWorld(slots[4][0] + .7, ry1 + .45)].map(p => p.map(Math.round));

  // ---------------- the stalls of the rows: one per place, closed and open ----------------
  const stalls = {};
  STALL_OWNERS.forEach(([id, c1, c2, board], i) => {
    const [x, y, x1, y1] = slots[i];
    const counter = (s, front = '#c9a672') => { B.fullBox(s, front, x, y + .35, x1, y1, 0, 11, '#d8b886'); B.boards(s, 'y', y1, x, x1, 0, 11, 4, 'rgba(80,55,30,.25)') };
    const backPosts = s => { B.shadowAt(s, x, y, x1, y1, 40, 16); for (const [a, b] of [[x + .06, y + .06], [x1 - .06, y + .06]]) B.L(s, a, b, 0, a, b, 30, WOOD_D, 2.2) };
    const frontPosts = s => { for (const [a, b] of [[x + .06, y1 - .06], [x1 - .06, y1 - .06]]) B.L(s, a, b, 11, a, b, 26, WOOD_D, 2.2) };
    // the board on the back posts with the owner's emblem (no words: names come with the sheet)
    const boardSign = s => { const a = P(x + .3, y + .06, 44), b = P(x1 - .3, y + .06, 44), c3 = P(x1 - .3, y + .06, 34), d = P(x + .3, y + .06, 34);
      B.L(s, x + .3, y + .06, 30, x + .3, y + .06, 34, WOOD_D, 1.4); B.L(s, x1 - .3, y + .06, 30, x1 - .3, y + .06, 34, WOOD_D, 1.4);
      s.poly([a, b, c3, d], board, sh(board, -.3), 1.2); return {x: (a.x + c3.x) / 2, y: (a.y + c3.y) / 2} };
    const emblem = (s, q) => {
      if (id === 'magpie') { s.ellipse(q.x, q.y, 4.2, 2.6, '#f4ede0'); s.ellipse(q.x + 3, q.y - 1.6, 2, 1.8, '#1f2328'); s.poly([{x: q.x - 3, y: q.y}, {x: q.x - 9, y: q.y + 2}, {x: q.x - 3, y: q.y + 1.6}], '#1f2328'); s.ellipse(q.x + .5, q.y - .4, 2, 1, '#5f9aa8') }
      else if (id === 'igor') { s.line(q.x, q.y + 3, q.x, q.y - 2, '#f1dc8a', 1.4); s.ellipse(q.x - 2.6, q.y - 2, 2.6, 1.4, '#f1dc8a'); s.ellipse(q.x + 2.6, q.y - 3, 2.6, 1.4, '#f1dc8a') }
      else if (id === 'sonya') { s.poly([{x: q.x - 3, y: q.y - 3}, {x: q.x + 3, y: q.y - 3}, {x: q.x + 2, y: q.y}, {x: q.x + 3, y: q.y + 3}, {x: q.x - 3, y: q.y + 3}, {x: q.x - 2, y: q.y}], '#f4ede0'); s.line(q.x - 2, q.y - 1, q.x + 2, q.y - 1, '#c97a8a', 1); s.line(q.x - 2, q.y + 1, q.x + 2, q.y + 1, '#c97a8a', 1) }
      else if (id === 'agata') s.poly(Array.from({length: 10}, (_, k) => { const a = -Math.PI / 2 + k * Math.PI / 5, r = k % 2 ? 1.6 : 4; return {x: q.x + Math.cos(a) * r, y: q.y + Math.sin(a) * r} }), '#e8c25a');
      else if (id === 'post') { s.poly([{x: q.x - 4.4, y: q.y - 2.8}, {x: q.x + 4.4, y: q.y - 2.8}, {x: q.x + 4.4, y: q.y + 2.8}, {x: q.x - 4.4, y: q.y + 2.8}], '#f4ede0'); s.poly([{x: q.x - 4.4, y: q.y - 2.8}, {x: q.x, y: q.y + .6}, {x: q.x + 4.4, y: q.y - 2.8}], null, '#5f7f9a', 1) }
      else { s.ellipse(q.x, q.y, 3.6, 3.6, '#e8c25a'); s.ellipse(q.x, q.y, 2.2, 2.2, '#d9a650') }
    };
    // goods on the counter, by owner
    const goods = s => {
      const at = (u, z = 11) => P(x + .25 + u * (x1 - x - .5), y + .78, z);
      if (id === 'magpie') { for (const [u, col] of [[0, '#7fa3c4'], [.5, '#e8c25a'], [1, '#c3b0de']]) { const q = at(u); s.poly([{x: q.x - 3, y: q.y}, {x: q.x + 3, y: q.y}, {x: q.x + 3, y: q.y - 7}, {x: q.x - 3, y: q.y - 7}], col); s.ellipse(q.x, q.y - 7.5, 3, 1.4, '#f4ede0') }
        const q = at(.25); s.ellipse(q.x, q.y - 2, 4.4, 1.8, '#f1e6c9'); s.ellipse(q.x - 4, q.y - 2, 1.4, 1.8, '#e3d3ac') }
      else if (id === 'igor') { for (const [u, col] of [[0, '#e6dcc0'], [.45, '#e3d3ac'], [.9, '#d9c08c']]) { const q = at(u); s.ellipse(q.x, q.y - 4, 5, 5.4, col); s.ellipse(q.x, q.y - 8.6, 3.6, 1.4, '#c9a240') }
        for (const u of [.22, .7]) { const q = at(u); s.poly([{x: q.x - 2.4, y: q.y}, {x: q.x + 2.4, y: q.y}, {x: q.x + 2, y: q.y - 4}, {x: q.x - 2, y: q.y - 4}], '#c97a5a'); s.ellipse(q.x, q.y - 6, 2.6, 2, '#8fbb7c') } }
      else if (id === 'sonya') { for (const [u, cols] of [[0, ['#c97a8a', '#f4ede0', '#8fae86']], [.55, ['#7fa3c4', '#e8c25a', '#c3b0de']]]) { const q = at(u); cols.forEach((col, k) => s.poly([{x: q.x - 6, y: q.y - k * 2.4}, {x: q.x + 6, y: q.y + 3 - k * 2.4}, {x: q.x + 6, y: q.y + 1 - k * 2.4}, {x: q.x - 6, y: q.y - 2 - k * 2.4}], col)) }
        for (const [u, col] of [[.32, '#e7a8b5'], [.95, '#8fae86']]) { const q = at(u); s.ellipse(q.x, q.y - 3, 3, 3, col); s.line(q.x - 2, q.y - 4, q.x + 2, q.y - 2, '#ffffff88', .8) }
        for (const [u, col] of [[.15, '#c97a8a'], [.6, '#7fa3c4']]) { const t = P(x + .2 + u * (x1 - x - .3), y1 - .06, 26); s.poly([{x: t.x - 2, y: t.y}, {x: t.x + 2, y: t.y + 1}, {x: t.x + 1.4, y: t.y + 12}, {x: t.x - 2.4, y: t.y + 10}], col) } }   // scarves on the beam
      else if (id === 'agata') { for (const [u, col] of [[0, '#d9553f'], [.5, '#e8c25a'], [1, '#7fa3c4']]) { const q = at(u); s.ellipse(q.x, q.y - 3.4, 3.4, 3.4, col); s.ellipse(q.x - 1, q.y - 4.4, 1, 1, '#ffffff99') }
        const q = at(.75); s.poly([{x: q.x, y: q.y - 12}, {x: q.x - 4, y: q.y}, {x: q.x + 4, y: q.y}], '#6f9a5f');
        for (let k = 0; k < 5; k++) { const t = P(x + .15 + k * (x1 - x - .3) / 4, y1 - .06, 25 - 2 * Math.sin(Math.PI * k / 4)); s.ellipse(t.x, t.y + 2, 1.6, 2, ['#d9553f', '#e8c25a', '#8fae86', '#7fa3c4', '#e7a8b5'][k]) } }
      else if (id === 'post') { const q = at(.2); for (let k = 0; k < 3; k++) s.poly([{x: q.x - 5, y: q.y - k * 1.6}, {x: q.x + 5, y: q.y + 2.4 - k * 1.6}, {x: q.x + 5, y: q.y + .8 - k * 1.6}, {x: q.x - 5, y: q.y - 1.6 - k * 1.6}], k % 2 ? '#e9e1cc' : '#f4ede0');
        const m = at(.85, 0); B.fullBox(s, '#d9553f', x1 - .35, y + .75, x1 - .12, y + .95, 0, 18, '#c9473a'); s.line(m.x - 2, m.y - 14, m.x + 2, m.y - 12, '#f4ede0', 1);
        const w = P(x + .5, y + .07, 22); for (const [dx, dy, col] of [[-6, -4, '#f4ede0'], [0, -2, '#efe2c2'], [6, 0, '#f4ede0']]) s.poly([{x: w.x + dx - 3, y: w.y + dy - 4}, {x: w.x + dx + 3, y: w.y + dy - 1}, {x: w.x + dx + 3, y: w.y + dy + 5}, {x: w.x + dx - 3, y: w.y + dy + 2}], col) }   // «Вестник» sheets
      else { for (const [u, col, top] of [[0, '#c9a672', '#d9553f'], [.5, '#b98d5d', '#e8c25a'], [1, '#c9a672', '#8fbf5f']]) { const q = at(u, 0); B.crate(s, x + .25 + u * (x1 - x - .5), y + .7, .26, 9, col); s.ellipse(q.x, q.y - 10, 4, 2, top) } }
    };
    piece(`stall-${id}-open`, [x - .2, y - .1, x1 + .2, y1 + .3], 50, s => {
      backPosts(s); emblem(s, boardSign(s)); counter(s); goods(s); frontPosts(s);
      B.awning(s, x - .06, x1 + .06, y, 32, .72, 6, c2, c1, 6);
      const lt = P(x1 - .1, y1 - .06, 26); s.line(lt.x, lt.y, lt.x, lt.y + 2, WOOD_D, 1); s.ellipse(lt.x, lt.y + 4.6, 2.2, 2.8, '#f0c95a'); s.ellipse(lt.x, lt.y + 2, 2, .8, '#5a4a3a');
    });
    piece(`stall-${id}-closed`, [x - .2, y - .1, x1 + .2, y1 + .3], 50, s => {
      backPosts(s); emblem(s, boardSign(s)); counter(s, '#b9945f'); frontPosts(s);
      // shutters closed over the opening between the counter and the beam, the awning rolled up under the beam
      for (let k = 0; k < 6; k++) { const a = x + .06 + (x1 - x - .12) * k / 6, b = x + .06 + (x1 - x - .12) * (k + 1) / 6;
        B.Q(s, k % 2 ? '#a98058' : '#b48f66', [a, y1 - .06, 11, b, y1 - .06, 11, b, y1 - .06, 26, a, y1 - .06, 26]) }
      B.L(s, x + .06, y1 - .06, 18.5, x1 - .06, y1 - .06, 18.5, WOOD_D, 1.6);
      const lk = P((x + x1) / 2, y1 - .06, 18.5); s.ellipse(lk.x, lk.y, 1.8, 1.8, '#c9a240');
      for (const t of [.2, .5, .8]) { const a = P(x - .06 + (x1 - x + .12) * t, y + .03, 31); s.ellipse(a.x, a.y, 5.6, 2.2, t === .5 ? c2 : c1) }   // the rolled awning
      B.L(s, x - .06, y + .03, 31, x1 + .06, y + .03, 31, sh(c1, -.2), 3.2);
    });
    const lantern = [x1 - .1, y1 - .06, 21, 14];
    pieces[`stall-${id}-open-night`] = {box: pieces[`stall-${id}-open`].box, body: ''};
    { const c = new SvgCtx('sl' + i + 'n'), s = Object.create(FarmScene.prototype); Object.assign(s, {c});
      const p = P(lantern[0], lantern[1], lantern[2]); s.ellipse(p.x, p.y, lantern[3], lantern[3] * .7, 'rgba(255,200,95,.24)'); s.ellipse(p.x, p.y, 2, 2.6, '#ffe7a0');
      pieces[`stall-${id}-open-night`].body = `<g transform="matrix(${V.matrix.map(v => +v.toFixed(4)).join(' ')})">${c.svg()}</g>` }
    // the lantern hangs on the front post in both views
    stalls[id] = {slot: i};
  });

  // the sprite of the game and the boxes the game places the pieces by
  const symbols = Object.entries(pieces).map(([id, p]) => `<symbol id="${id}" viewBox="${p.box.join(' ')}">${p.body}</symbol>`).join('');
  const sprite = `<svg xmlns="http://www.w3.org/2000/svg" aria-hidden="true" focusable="false">${symbols}</svg>`;
  const files = Object.fromEntries(Object.entries(pieces).map(([id, p]) => [id, `<svg xmlns="http://www.w3.org/2000/svg" viewBox="${p.box.join(' ')}">${p.body}</svg>`]));
  const boxes = Object.fromEntries(Object.entries(pieces).filter(([id]) => !id.endsWith('-night')).map(([id, p]) => [id, p.box]));
  return {sprite, files, boxes, crew, stalls: STALL_OWNERS.map(([id], i) => ({id, slot: slots[i]}))};
}

// shade a #rrggbb colour lighter (+) or darker (−)
function sh(hex, k) {
  const n = parseInt(hex.slice(1), 16), ch = [n >> 16, (n >> 8) & 255, n & 255].map(v => Math.max(0, Math.min(255, Math.round(k > 0 ? v + (255 - v) * k : v * (1 + k)))));
  return '#' + ch.map(v => v.toString(16).padStart(2, '0')).join('');
}
