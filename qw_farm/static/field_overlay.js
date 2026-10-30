/* Field overlay: the live three-operation field screen.
 * Pure server rules live in tractor_game.js; this module only draws and drives the DOM.
 * The visual language is the approved standalone mockup, adapted to live widths and runs.
 */
import {
  gameCfg, Run, growthPermille, yieldQty, quality, conditionQuality, finalConditionQuality, runLeftSec, sprayBonus, timeKeep,
  timeLimits, autoSeconds, maxPath, stepAnchor, stepAnchorOrient, QRULE_TIMED
} from './tractor_game.js?v=20261030b';

const SPEEDS = [
  { id: 'calm', label: 'спокойно', ms: 450 },
  { id: 'normal', label: 'обычно', ms: 320 },
  { id: 'fast', label: 'быстро', ms: 180 }
];
const SPEED_KEY = 'qw-farm.fieldSpeed';
function loadSpeed() {
  try {
    const i = SPEEDS.findIndex(x => x.id === localStorage.getItem(SPEED_KEY));
    return i >= 0 ? i : 1;
  } catch { return 1; }
}
function saveSpeed(i) { try { localStorage.setItem(SPEED_KEY, SPEEDS[i].id); } catch {} }

const KEYS = { ArrowUp: 'U', KeyW: 'U', ArrowDown: 'D', KeyS: 'D', ArrowLeft: 'L', KeyA: 'L', ArrowRight: 'R', KeyD: 'R' };
const TITLES = { cultivate: 'Культивация', sow: 'Посев', harvest: 'Уборка', spray: 'Опрыскивание' };
const HELP = {
  cultivate: 'Сорняки весят втрое: чистая культивация ускоряет рост урожая. Камни не в счёт. Удары по камням и краю портят машину.',
  sow: 'Сей только по светлым полосам, между ними пустой столбец. Повторный проход снижает урожай.',
  harvest: 'Бункер не бесконечный. Когда он полон, вези зерно к грузовику на верхнем краю поля.',
  spray: 'Ветер сносит распыл. У цистерны наверху бак наполняется сам, удержание кнопки ускоряет заправку втрое.'
};
const SUPPLY_FRAC = 0.625;
const BAR_H = 1;

let W = 8;
let H = 8;
let BAR = 2;
let state = null;
let view = null;

const key = (x, y) => y * W + x;
const xy = (k) => [k % W, Math.floor(k / W)];
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const reduced = () => {
  try { return !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches; } catch { return false; }
};
const hash = (x, y, s) => {
  const n = Math.sin(x * 127.1 + y * 311.7 + s * 74.7) * 43758.5453123;
  return n - Math.floor(n);
};
const rrect = (g, x, y, w, h, r) => {
  const rr = Math.min(r, Math.abs(w) / 2, Math.abs(h) / 2);
  g.beginPath();
  if (g.roundRect) g.roundRect(x, y, w, h, rr);
  else {
    g.moveTo(x + rr, y);
    g.arcTo(x + w, y, x + w, y + h, rr);
    g.arcTo(x + w, y + h, x, y + h, rr);
    g.arcTo(x, y + h, x, y, rr);
    g.arcTo(x, y, x + w, y, rr);
    g.closePath();
  }
};
const isSowLaneCell = (x) => x % (BAR + 1) < BAR;
const footSize = (orient) => orient === 'v' ? { w: 1, h: BAR } : { w: BAR, h: BAR_H };
const pctText = (permille) => (permille / 10).toFixed(1).replace('.', ',') + '%';
const roundPct = (permille) => Math.round(permille / 10) + '%';
const mmss = (seconds) => {
  seconds = Math.max(0, Math.ceil(seconds));
  return String(Math.floor(seconds / 60)).padStart(2, '0') + ':' + String(seconds % 60).padStart(2, '0');
};
function node(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined) n.textContent = text;
  return n;
}
function btn(text, cls, fn) {
  const b = node('button', cls, text);
  b.type = 'button';
  if (fn) b.onclick = fn;
  return b;
}


  const PALETTE = {
    day: {
      stage: '#c9d6b8', stage2: '#dbe5cd', stageTuft: '#a9c093', stageFlower: '#f6f0df',
      soil: '#b39572', soilAlt: '#ab8c69', soilLight: '#c0a27c', furrow: '#9a7d5c', seam: 'rgba(154,125,92,.34)',
      wild: '#9fbc83', wildAlt: '#94b37a', wildTuft: '#7ea05b', wildFlower: '#f6f0df',
      weed: '#6f9f5a', weedLight: '#8fb86a',
      ripe: '#d8bf6a', ripeAlt: '#cdb35f', ripeLight: '#ecd88a', ripeStalk: '#a98a3f', stubble: '#cdbd91',
      rockTile: '#a99c83', rock: '#9c9e8e', rockLight: '#cfd1c0', rockDark: '#7d806e', rockMoss: '#86ad70',
      lane: 'rgba(246,239,210,.32)', laneLine: 'rgba(246,239,210,.8)', path: '#a88a66',
      machine: { cultivate: '#b9724f', sow: '#86a97c', harvest: '#d6b66a', spray: '#6f9a8f' },
      crop: '#9fbe82', cropAlt: '#a3c27a', sprayed: '#76945f', sprayedAlt: '#7c9b68', sprayDew: '#8db5b1',
      machineDark: '#5b6658', steel: '#818775', cream: '#e0dfbd', glass: '#8db5b1', hub: '#d6d1ab', beacon: '#e8a33a',
      dust: '#d6c19c', shadow: 'rgba(87,105,91,.22)', headlight: '#ffe5a1', glow: 'rgba(255,213,128,.22)',
      road: '#dbd3ae', roadLine: '#c5ba93', roadEdge: '#b8a885', truck: '#e7cd82', truckDark: '#7c6a4d', grain: '#d8bf6a',
      barnRoof: '#b9724f', barnRoofLight: '#c98a63', barnRoofDark: '#9e5f40', barnWall: '#efe3c4', barnTrim: '#f6f0df',
      silo: '#c9bea2', siloRoof: '#7c9d83', fenceRail: '#b79f72', fencePost: '#8a6c4c',
      tree1: '#7ea05b', tree2: '#8fae7a', tree3: '#a3c27a', treeTrunk: '#a98763', fruit: '#d5735f',
      hay: '#e0c97c', hayDark: '#c9a86a', hayLight: '#f0dda0',
      signPost: '#8a6c4c', signFace: '#f2e5b7', signInk: '#4f5f4e',
      blocked: '#b9724f', hatch: 'rgba(120,106,84,.36)'
    },
    night: {
      stage: '#22352a', stage2: '#2a3d2f', stageTuft: '#3f5b45', stageFlower: '#d8c98f',
      soil: '#6f5a44', soilAlt: '#66523d', soilLight: '#7d664d', furrow: '#4a3828', seam: 'rgba(30,22,15,.4)',
      wild: '#4b6540', wildAlt: '#435c3a', wildTuft: '#7fa06b', wildFlower: '#d8c98f',
      weed: '#8fb07a', weedLight: '#a9c794',
      ripe: '#b99a55', ripeAlt: '#ad8f4f', ripeLight: '#d8bd78', ripeStalk: '#8a6f38', stubble: '#7a6e52',
      rockTile: '#5d5a4c', rock: '#7f8275', rockLight: '#a9ab9a', rockDark: '#5d6055', rockMoss: '#6f9a5a',
      lane: 'rgba(216,201,143,.18)', laneLine: 'rgba(216,201,143,.55)', path: '#5a4a38',
      machine: { cultivate: '#d08a67', sow: '#9fbd8f', harvest: '#e3bd72', spray: '#8fb5a8' },
      crop: '#5b7a52', cropAlt: '#5f7e56', sprayed: '#3f5a46', sprayedAlt: '#46624c', sprayDew: '#7fb0ac',
      machineDark: '#1f2b22', steel: '#8b978c', cream: '#f1e6c8', glass: '#7fb0ac', hub: '#b9ad93', beacon: '#f0c36a',
      dust: '#8f7d65', shadow: 'rgba(0,0,0,.4)', headlight: '#ffdf9c', glow: 'rgba(255,213,128,.2)',
      road: '#4e4334', roadLine: '#b9a77c', roadEdge: '#3f382d', truck: '#b9a78a', truckDark: '#3f382d', grain: '#b99b55',
      barnRoof: '#8a4e3a', barnRoofLight: '#a55f47', barnRoofDark: '#6e3b2c', barnWall: '#b9ad93', barnTrim: '#e9dcbb',
      silo: '#8f8772', siloRoof: '#56705e', fenceRail: '#7b5f42', fencePost: '#5d4733',
      tree1: '#57764a', tree2: '#6f8f5c', tree3: '#86a46f', treeTrunk: '#7b5f42', fruit: '#b45a4a',
      hay: '#b99b55', hayDark: '#9b7e45', hayLight: '#d8bd78',
      signPost: '#5d4733', signFace: '#d8c98f', signInk: '#2a2418',
      blocked: '#d08a67', hatch: 'rgba(216,201,143,.25)'
    }
  };



  function wobblyRect(g, x, y, w, h) {
    const step = Math.max(10, w / 18);
    g.beginPath();
    for (let i = 0; i <= w; i += step) {
      const px = x + i;
      const py = y + Math.sin((i + 7) * 0.07) * 1.1;
      if (i === 0) g.moveTo(px, py); else g.lineTo(px, py);
    }
    for (let i = 0; i <= h; i += step) {
      const px = x + w + Math.cos((i + 11) * 0.07) * 1.1;
      const py = y + i;
      g.lineTo(px, py);
    }
    for (let i = w; i >= 0; i -= step) {
      const px = x + i;
      const py = y + h + Math.sin((i + 3) * 0.07) * 1.1;
      g.lineTo(px, py);
    }
    for (let i = h; i >= 0; i -= step) {
      const px = x + Math.cos((i + 5) * 0.07) * 1.1;
      const py = y + i;
      g.lineTo(px, py);
    }
    g.closePath();
  }

  const TAU = Math.PI * 2;
  const rgba = (hex, a) => {
    const n = parseInt(hex.slice(1), 16);
    return 'rgba(' + ((n >> 16) & 255) + ',' + ((n >> 8) & 255) + ',' + (n & 255) + ',' + a + ')';
  };

  function drawWild(g, x, y, cell, p, seed) {
    g.strokeStyle = p.wildTuft;
    g.lineWidth = Math.max(1, cell * 0.035);
    g.lineCap = 'round';
    for (let i = 0; i < 4; i++) {
      const bx = x + cell * (0.14 + hash(seed + i, 3, 4) * 0.72);
      const by = y + cell * (0.82 + hash(seed + i, 8, 5) * 0.07);
      const h = cell * (0.15 + hash(seed + i, 7, 6) * 0.17);
      g.beginPath();
      g.moveTo(bx, by);
      g.quadraticCurveTo(bx - cell * 0.04, by - h * 0.6, bx + (hash(seed + i, 2, 7) - 0.5) * cell * 0.12, by - h);
      g.stroke();
    }
    if (hash(seed, 5, 5) > 0.78) {
      g.fillStyle = p.wildFlower;
      g.globalAlpha = 0.8;
      g.beginPath();
      g.arc(x + cell * 0.3, y + cell * 0.34, Math.max(1, cell * 0.025), 0, TAU);
      g.arc(x + cell * 0.67, y + cell * 0.6, Math.max(1, cell * 0.02), 0, TAU);
      g.fill();
      g.globalAlpha = 1;
    }
  }

  function drawFurrows(g, x, y, cell, p, seed) {
    g.strokeStyle = p.furrow;
    g.globalAlpha = 0.42;
    g.lineWidth = Math.max(1, cell * 0.032);
    for (let i = 1; i <= 3; i++) {
      const fx = x + cell * (i / 4 + (hash(seed, i, 2) - 0.5) * 0.035);
      g.beginPath();
      g.moveTo(fx, y + cell * 0.14);
      g.lineTo(fx + cell * 0.012, y + cell * 0.86);
      g.stroke();
    }
    g.globalAlpha = 1;
    g.fillStyle = p.soilLight;
    g.globalAlpha = 0.55;
    for (let i = 0; i < 3; i++) {
      const px = x + cell * (0.16 + hash(seed + i, 5, 3) * 0.68);
      const py = y + cell * (0.2 + hash(seed + i, 9, 4) * 0.6);
      g.beginPath();
      g.ellipse(px, py, cell * 0.035, cell * 0.016, 0, 0, TAU);
      g.fill();
    }
    g.globalAlpha = 1;
  }

  function drawSprout(g, x, y, cell, p, plant) {
    const px = x + cell * plant.x;
    const py = y + cell * (0.72 + (plant.y - 0.18) * 0.2);
    const s = cell * 0.09 * plant.s;
    g.strokeStyle = p.weed;
    g.lineWidth = Math.max(1, cell * 0.022);
    g.lineCap = 'round';
    g.beginPath();
    g.moveTo(px, py + s * 0.5);
    g.lineTo(px + plant.lean * s * 0.4, py - s * 0.35);
    g.stroke();
    g.fillStyle = p.weedLight;
    g.beginPath();
    g.ellipse(px - s * 0.55, py - s * 0.2, s * 0.72, s * 0.36, -0.55, 0, TAU);
    g.ellipse(px + s * 0.55, py - s * 0.34, s * 0.68, s * 0.34, 0.5, 0, TAU);
    g.fill();
  }

  function drawRipe(g, x, y, cell, p, plant) {
    const px = x + cell * plant.x;
    const py = y + cell * 0.82;
    const h = cell * (0.28 + plant.s * 0.18);
    g.strokeStyle = p.ripeStalk;
    g.lineWidth = Math.max(1, cell * 0.024);
    g.lineCap = 'round';
    g.beginPath();
    g.moveTo(px, py);
    g.quadraticCurveTo(px + plant.lean * cell * 0.03, py - h * 0.6, px + plant.lean * cell * 0.07, py - h);
    g.stroke();
    g.fillStyle = p.ripe;
    for (let i = 0; i < 3; i++) {
      g.beginPath();
      g.ellipse(px + plant.lean * cell * 0.07 + (i - 1) * cell * 0.052, py - h - cell * 0.01, cell * 0.045, cell * 0.075, (i - 1) * 0.5, 0, TAU);
      g.fill();
    }
    g.fillStyle = p.ripeLight;
    g.beginPath();
    g.ellipse(px + plant.lean * cell * 0.07 - cell * 0.02, py - h - cell * 0.05, cell * 0.026, cell * 0.042, -0.2, 0, TAU);
    g.fill();
  }

  function drawStubble(g, x, y, cell, p, seed) {
    g.strokeStyle = p.stubble;
    g.globalAlpha = 0.85;
    g.lineWidth = Math.max(1, cell * 0.03);
    g.lineCap = 'round';
    for (let i = 0; i < 4; i++) {
      const px = x + cell * (0.16 + hash(seed + i, 2, 8) * 0.68);
      const py = y + cell * (0.8 + hash(seed + i, 4, 9) * 0.06);
      g.beginPath();
      g.moveTo(px, py);
      g.lineTo(px + (hash(seed + i, 1, 2) - 0.5) * cell * 0.07, py - cell * (0.1 + hash(seed + i, 6, 3) * 0.09));
      g.stroke();
    }
    g.globalAlpha = 1;
  }

  function drawSprayFilm(g, x, y, cell, p) {
    g.fillStyle = rgba(p.sprayDew, 0.18);
    g.fillRect(x + 1, y + 1, cell - 2, cell - 2);
    g.fillStyle = rgba(p.sprayDew, 0.82);
    for (let i = 0; i < 4; i++) {
      g.beginPath();
      g.ellipse(x + cell * (0.18 + hash(x, y, i + 3) * 0.64), y + cell * (0.18 + hash(x, y, i + 7) * 0.64), cell * 0.018, cell * 0.028, 0, 0, TAU);
      g.fill();
    }
    g.strokeStyle = rgba(p.sprayDew, 0.32);
    g.lineWidth = 1;
    g.beginPath();
    g.moveTo(x + cell * 0.18, y + cell * 0.84);
    g.lineTo(x + cell * 0.82, y + cell * 0.84);
    g.stroke();
  }

  function drawWeed(g, x, y, cell, p, seed) {
    g.fillStyle = p.shadow;
    g.globalAlpha = 0.35;
    g.beginPath();
    g.ellipse(x + cell * 0.48, y + cell * 0.8, cell * 0.2, cell * 0.05, 0, 0, TAU);
    g.fill();
    g.globalAlpha = 1;
    for (let i = 0; i < 3; i++) {
      const bx = x + cell * (0.3 + hash(seed + i, 2, 5) * 0.4);
      const by = y + cell * 0.78;
      const h = cell * (0.2 + hash(seed + i, 6, 7) * 0.14);
      g.strokeStyle = p.weed;
      g.lineWidth = Math.max(1.2, cell * 0.035);
      g.lineCap = 'round';
      g.beginPath();
      g.moveTo(bx, by);
      g.quadraticCurveTo(bx - cell * 0.05, by - h * 0.55, bx + (hash(seed + i, 8, 1) - 0.5) * cell * 0.1, by - h);
      g.stroke();
      g.fillStyle = p.weedLight;
      g.beginPath();
      g.ellipse(bx - cell * 0.055, by - h * 0.52, cell * 0.06, cell * 0.032, -0.5, 0, TAU);
      g.ellipse(bx + cell * 0.06, by - h * 0.68, cell * 0.055, cell * 0.03, 0.5, 0, TAU);
      g.fill();
    }
  }

  function drawMaterialEdge(g, x, y, cell, a, b, edge) {
    const band = cell * 0.16;
    const waves = 3;
    const amp = cell * 0.12;
    if (edge === 'right') {
      const ex = x + cell;
      g.fillStyle = a;
      g.fillRect(ex - band, y, band * 2, cell);
      g.beginPath();
      g.moveTo(ex, y);
      const step = cell / waves;
      for (let i = 0; i < waves; i++) {
        const dir = i % 2 === 0 ? 1 : -1;
        const curve = amp * (0.82 + hash(x, y, i + 1) * 0.36);
        g.quadraticCurveTo(ex + dir * curve, y + step * (i + 0.5), ex, y + step * (i + 1));
      }
      g.lineTo(ex + band, y + cell);
      g.lineTo(ex + band, y);
      g.closePath();
      g.fillStyle = b;
      g.fill();
    } else {
      const ey = y + cell;
      g.fillStyle = a;
      g.fillRect(x, ey - band, cell, band * 2);
      g.beginPath();
      g.moveTo(x, ey);
      const step = cell / waves;
      for (let i = 0; i < waves; i++) {
        const dir = i % 2 === 0 ? 1 : -1;
        const curve = amp * (0.82 + hash(x, y, i + 11) * 0.36);
        g.quadraticCurveTo(x + step * (i + 0.5), ey + dir * curve, x + step * (i + 1), ey);
      }
      g.lineTo(x + cell, ey + band);
      g.lineTo(x, ey + band);
      g.closePath();
      g.fillStyle = b;
      g.fill();
    }
  }

  function drawRock(g, x, y, cell, p, seed, kind) {
    const cx = x + cell * (0.5 + (hash(seed, 1, 2) - 0.5) * 0.12);
    const cy = y + cell * (0.54 + (hash(seed, 2, 3) - 0.5) * 0.08);
    const r = cell * 0.25;
    g.fillStyle = p.shadow;
    g.globalAlpha = 0.34;
    g.beginPath();
    g.ellipse(cx + cell * 0.03, cy + cell * 0.07, r * 1.05, r * 0.38, 0, 0, TAU);
    g.fill();
    g.globalAlpha = 1;
    if (kind === 'wild' || kind === 'unreachable') {
      g.strokeStyle = p.wildTuft;
      g.globalAlpha = 0.45;
      g.lineWidth = Math.max(1, cell * 0.02);
      g.lineCap = 'round';
      for (let i = 0; i < 2; i++) {
        const bx = cx + (i ? 1 : -1) * r * 1.15;
        const by = cy + r * 0.42;
        g.beginPath();
        g.moveTo(bx, by);
        g.quadraticCurveTo(bx - cell * 0.025, by - cell * 0.04, bx + (i ? 1 : -1) * cell * 0.03, by - cell * 0.075);
        g.stroke();
      }
      g.globalAlpha = 1;
    }
    g.fillStyle = p.rockDark;
    g.beginPath();
    g.ellipse(cx, cy, r * 1.05, r * 0.72, -0.12, 0, TAU);
    g.fill();
    g.fillStyle = p.rock;
    g.beginPath();
    g.ellipse(cx, cy - r * 0.13, r, r * 0.62, -0.1, 0, TAU);
    g.fill();
    g.fillStyle = p.rockLight;
    g.beginPath();
    g.ellipse(cx - r * 0.3, cy - r * 0.33, r * 0.46, r * 0.24, -0.25, 0, TAU);
    g.fill();
    g.fillStyle = p.rockMoss;
    g.globalAlpha = 0.8;
    g.beginPath();
    g.ellipse(cx + r * 0.46, cy - r * 0.08, r * 0.2, r * 0.11, 0.3, 0, TAU);
    g.fill();
    g.globalAlpha = 1;
    g.strokeStyle = p.rockDark;
    g.globalAlpha = 0.4;
    g.lineWidth = Math.max(1, cell * 0.018);
    g.beginPath();
    g.arc(cx, cy, r * 0.7, 0.4, 2.1);
    g.stroke();
    g.globalAlpha = 1;
    g.fillStyle = p.rockLight;
    g.globalAlpha = 0.7;
    g.beginPath();
    g.ellipse(cx - r * 1.05, cy + r * 0.42, r * 0.2, r * 0.12, 0.4, 0, TAU);
    g.fill();
    g.globalAlpha = 1;
  }

  function drawHatch(g, x, y, cell, p) {
    g.save();
    g.beginPath();
    g.rect(x + cell * 0.08, y + cell * 0.08, cell * 0.84, cell * 0.84);
    g.clip();
    g.strokeStyle = p.hatch;
    g.lineWidth = Math.max(1, cell * 0.028);
    for (let i = -cell; i < cell * 2; i += Math.max(5, cell * 0.17)) {
      g.beginPath();
      g.moveTo(x + i, y + cell);
      g.lineTo(x + i + cell, y);
      g.stroke();
    }
    g.restore();
  }

  function drawFenceEdge(g, x1, y1, x2, y2, cell, p) {
    g.strokeStyle = p.shadow;
    g.globalAlpha = 0.35;
    g.lineWidth = Math.max(2, cell * 0.05);
    g.beginPath();
    g.moveTo(x1 + 2, y1 + 4);
    g.lineTo(x2 + 2, y2 + 4);
    g.stroke();
    g.globalAlpha = 1;
    g.strokeStyle = p.fenceRail;
    g.lineWidth = Math.max(2, cell * 0.055);
    g.lineCap = 'round';
    g.beginPath();
    g.moveTo(x1, y1);
    g.lineTo(x2, y2);
    g.stroke();
    g.strokeStyle = rgba(p.cream, 0.35);
    g.lineWidth = 1;
    g.beginPath();
    g.moveTo(x1, y1 - 1);
    g.lineTo(x2, y2 - 1);
    g.stroke();
    const len = Math.hypot(x2 - x1, y2 - y1);
    const n = Math.max(2, Math.round(len / Math.max(12, cell * 0.85)));
    for (let i = 0; i <= n; i++) {
      const t = i / n;
      const px = x1 + (x2 - x1) * t;
      const py = y1 + (y2 - y1) * t;
      g.fillStyle = p.fencePost;
      rrect(g, px - cell * 0.035, py - cell * 0.075, cell * 0.07, cell * 0.15, 2);
      g.fill();
      g.fillStyle = rgba(p.cream, 0.6);
      g.beginPath();
      g.arc(px, py - cell * 0.06, Math.max(1, cell * 0.018), 0, TAU);
      g.fill();
    }
  }

  function drawFence(g, f, cell, p, near) {
    if (!near) {
      drawFenceEdge(g, f.x - 2, f.y - 2, f.x + f.w + 2, f.y - 2, cell, p);
      drawFenceEdge(g, f.x - 2, f.y - 2, f.x - 2, f.y + f.h + 2, cell, p);
    } else {
      drawFenceEdge(g, f.x - 2, f.y + f.h + 2, f.x + f.w + 2, f.y + f.h + 2, cell, p);
      drawFenceEdge(g, f.x + f.w + 2, f.y - 2, f.x + f.w + 2, f.y + f.h + 2, cell, p);
    }
  }

  function drawBarn(g, f, cell, p) {
    const w = Math.min(f.w * 0.34, cell * 3.2);
    const h = w * 0.62;
    const x = f.x - cell * 0.12;
    const y = f.y - Math.max(36, h * 0.82);
    g.fillStyle = rgba('#1f2b22', 0.16);
    rrect(g, x + 4, y + 6, w, h, 5);
    g.fill();
    g.fillStyle = p.barnRoof;
    rrect(g, x, y, w, h, 5);
    g.fill();
    g.fillStyle = p.barnRoofLight;
    rrect(g, x + 2, y + 2, w - 4, h * 0.45, 4);
    g.fill();
    g.fillStyle = p.barnRoofDark;
    rrect(g, x + 2, y + h * 0.5, w - 4, h * 0.45, 4);
    g.fill();
    g.strokeStyle = p.barnTrim;
    g.lineWidth = 2;
    g.beginPath();
    g.moveTo(x + 4, y + h * 0.5);
    g.lineTo(x + w - 4, y + h * 0.5);
    g.stroke();
    g.lineWidth = 1.2;
    rrect(g, x + 1, y + 1, w - 2, h - 2, 4);
    g.stroke();
    g.fillStyle = p.barnWall;
    rrect(g, x + w * 0.43, y + h * 0.36, w * 0.14, h * 0.28, 2);
    g.fill();
    g.fillStyle = p.barnRoofDark;
    g.fillRect(x + w * 0.44, y + h * 0.44, w * 0.12, h * 0.04);
    g.fillStyle = p.barnWall;
    rrect(g, x + w * 0.78, y - h * 0.1, w * 0.08, h * 0.2, 1);
    g.fill();
    g.fillStyle = p.barnRoofDark;
    g.fillRect(x + w * 0.77, y - h * 0.12, w * 0.1, h * 0.04);
    const sx = x + w + cell * 0.38;
    const sy = y + h * 0.72;
    const sr = cell * 0.42;
    g.fillStyle = rgba('#1f2b22', 0.14);
    g.beginPath();
    g.ellipse(sx + 2, sy + 4, sr, sr * 0.42, 0, 0, TAU);
    g.fill();
    g.fillStyle = p.silo;
    g.beginPath();
    g.ellipse(sx, sy, sr, sr * 0.52, 0, 0, TAU);
    g.fill();
    g.fillStyle = p.siloRoof;
    g.beginPath();
    g.ellipse(sx, sy - sr * 0.16, sr * 0.86, sr * 0.38, 0, 0, TAU);
    g.fill();
    g.strokeStyle = p.barnTrim;
    g.globalAlpha = 0.7;
    g.lineWidth = 1;
    g.beginPath();
    g.ellipse(sx, sy + sr * 0.06, sr * 0.78, sr * 0.3, 0, 0, TAU);
    g.stroke();
    g.globalAlpha = 1;
  }

  function drawTree(g, cx, cy, r, p) {
    g.fillStyle = p.shadow;
    g.globalAlpha = 0.6;
    g.beginPath();
    g.ellipse(cx + r * 0.25, cy + r * 0.35, r * 0.95, r * 0.4, 0, 0, TAU);
    g.fill();
    g.globalAlpha = 1;
    g.fillStyle = p.treeTrunk;
    g.beginPath();
    g.ellipse(cx, cy, r * 0.17, r * 0.13, 0, 0, TAU);
    g.fill();
    g.fillStyle = p.tree1;
    g.beginPath();
    g.ellipse(cx - r * 0.34, cy - r * 0.08, r * 0.62, r * 0.56, 0, 0, TAU);
    g.fill();
    g.fillStyle = p.tree2;
    g.beginPath();
    g.ellipse(cx + r * 0.35, cy - r * 0.04, r * 0.58, r * 0.52, 0, 0, TAU);
    g.fill();
    g.fillStyle = p.tree3;
    g.beginPath();
    g.ellipse(cx, cy - r * 0.28, r * 0.55, r * 0.5, 0, 0, TAU);
    g.fill();
    g.fillStyle = rgba(p.cream, 0.25);
    g.beginPath();
    g.ellipse(cx - r * 0.25, cy - r * 0.4, r * 0.3, r * 0.22, 0, 0, TAU);
    g.fill();
    g.fillStyle = p.fruit;
    for (const [dx, dy] of [[-0.4, -0.1], [0.38, -0.2], [0.02, 0.28]]) {
      g.beginPath();
      g.arc(cx + r * dx, cy + r * dy, Math.max(1.2, r * 0.055), 0, TAU);
      g.fill();
    }
  }

  function drawHay(g, cx, cy, r, p) {
    g.fillStyle = p.shadow;
    g.globalAlpha = 0.55;
    g.beginPath();
    g.ellipse(cx + r * 0.2, cy + r * 0.3, r * 1.02, r * 0.4, 0, 0, TAU);
    g.fill();
    g.globalAlpha = 1;
    g.fillStyle = p.hay;
    g.beginPath();
    g.ellipse(cx, cy, r, r * 0.62, 0, 0, TAU);
    g.fill();
    g.strokeStyle = p.hayDark;
    g.lineWidth = Math.max(1, r * 0.08);
    g.beginPath();
    for (let i = 0; i < 24; i++) {
      const a = i / 23 * TAU;
      const rr = r * (0.16 + i / 30);
      const px = cx + Math.cos(a) * rr;
      const py = cy + Math.sin(a) * rr * 0.62;
      if (i === 0) g.moveTo(px, py); else g.lineTo(px, py);
    }
    g.stroke();
    g.fillStyle = p.hayLight;
    g.beginPath();
    g.ellipse(cx - r * 0.25, cy - r * 0.25, r * 0.32, r * 0.14, -0.2, 0, TAU);
    g.fill();
  }

  function drawRoad(g, f, cell, p) {
    const y = f.y - view.roadH - 2;
    const h = view.roadH;
    g.fillStyle = p.road;
    rrect(g, f.x - 10, y, f.w + 20, h, h * 0.24);
    g.fill();
    g.strokeStyle = p.roadEdge;
    g.globalAlpha = 0.45;
    g.lineWidth = 1;
    rrect(g, f.x - 10, y + 1, f.w + 20, h - 2, h * 0.24);
    g.stroke();
    g.globalAlpha = 1;
    g.strokeStyle = p.roadLine;
    g.globalAlpha = 0.55;
    g.lineWidth = Math.max(1, cell * 0.028);
    g.setLineDash([cell * 0.22, cell * 0.2]);
    g.beginPath();
    g.moveTo(f.x - 4, y + h * 0.55);
    g.lineTo(f.x + f.w + 4, y + h * 0.55);
    g.stroke();
    g.setLineDash([]);
    g.globalAlpha = 1;
  }

  function drawWaterTank(g, f, cell, p) {
    const y = f.y - view.roadH - 2;
    const h = view.roadH;
    const w = cell * 1.95;
    const th = h * 0.62;
    const x = clamp(f.x + f.w * 0.62 - w / 2, f.x + 4, f.x + f.w - w - 4);
    const ty = y + (h - th) / 2;
    g.fillStyle = p.shadow;
    g.globalAlpha = 0.65;
    rrect(g, x + 3, ty + 4, w, th, th / 2);
    g.fill();
    g.globalAlpha = 1;
    g.fillStyle = p.machine.spray;
    g.strokeStyle = p.machineDark;
    g.lineWidth = Math.max(1, cell * 0.03);
    rrect(g, x, ty, w, th, th / 2);
    g.fill();
    g.stroke();
    g.fillStyle = p.cream;
    rrect(g, x + w * 0.14, ty + th * 0.36, w * 0.6, th * 0.1, 3);
    g.fill();
    g.fillStyle = p.sprayDew;
    rrect(g, x + w * 0.24, ty + th * 0.52, w * 0.44, th * 0.07, 3);
    g.fill();
    g.strokeStyle = p.machineDark;
    g.globalAlpha = 0.55;
    g.lineWidth = Math.max(1, cell * 0.024);
    g.beginPath();
    g.moveTo(x + w * 0.2, ty + th * 0.24);
    g.lineTo(x + w * 0.7, ty + th * 0.24);
    g.stroke();
    g.globalAlpha = 1;
    g.fillStyle = p.cream;
    rrect(g, x + w * 0.78, ty + th * 0.18, w * 0.12, th * 0.12, 2);
    g.fill();
    // hose reel at the rear
    const rx = x + w * 0.1;
    const ry = ty + th * 0.5;
    g.fillStyle = p.cream;
    g.beginPath();
    g.arc(rx, ry, th * 0.28, 0, TAU);
    g.fill();
    g.strokeStyle = p.machineDark;
    g.lineWidth = Math.max(1, cell * 0.024);
    g.beginPath();
    for (let i = 0; i < 16; i++) {
      const a = i / 16 * TAU * 2.4;
      const rr = th * (0.06 + i / 16 * 0.2);
      const px = rx + Math.cos(a) * rr;
      const py = ry + Math.sin(a) * rr;
      if (i === 0) g.moveTo(px, py); else g.lineTo(px, py);
    }
    g.stroke();
    g.strokeStyle = p.sprayDew;
    g.lineWidth = Math.max(1.2, cell * 0.035);
    g.beginPath();
    g.moveTo(rx, ry + th * 0.28);
    g.quadraticCurveTo(rx + w * 0.08, ty + th * 0.86, rx + w * 0.22, ty + th * 0.82);
    g.stroke();
    // ladder
    g.strokeStyle = p.cream;
    g.lineWidth = Math.max(1, cell * 0.025);
    for (let i = 0; i < 3; i++) {
      g.beginPath();
      g.moveTo(x + w * 0.4, ty + th * 0.1 + i * th * 0.09);
      g.lineTo(x + w * 0.5, ty + th * 0.1 + i * th * 0.09);
      g.stroke();
    }
    g.fillStyle = p.machineDark;
    for (const wx of [0.28, 0.78]) {
      g.beginPath();
      g.arc(x + w * wx, ty + th * 0.98, Math.max(2, cell * 0.055), 0, TAU);
      g.fill();
    }
    g.fillStyle = p.hub;
    for (const wx of [0.28, 0.78]) {
      g.beginPath();
      g.arc(x + w * wx, ty + th * 0.98, Math.max(0.8, cell * 0.022), 0, TAU);
      g.fill();
    }
    if (state.theme === 'night') {
      g.fillStyle = p.headlight;
      g.globalAlpha = 0.9;
      g.beginPath();
      g.arc(x + w * 0.92, ty + th * 0.42, Math.max(1.5, cell * 0.04), 0, TAU);
      g.fill();
      g.globalAlpha = 1;
    }
  }

  function drawTruck(g, f, cell, p) {
    const y = f.y - view.roadH - 2;
    const h = view.roadH;
    const cx = truckPos();
    const w = cell * 2.2;
    const th = h * 0.92;
    const x = clamp(cx - w / 2, f.x - 4, f.x + f.w - w + 4);
    const ty = y + (h - th) / 2;
    g.fillStyle = p.shadow;
    g.globalAlpha = 0.7;
    rrect(g, x + 3, ty + 4, w, th, 4);
    g.fill();
    g.globalAlpha = 1;
    // hopper / grain body
    g.fillStyle = p.truck;
    g.strokeStyle = p.machineDark;
    g.lineWidth = Math.max(1, cell * 0.03);
    rrect(g, x, ty, w * 0.76, th, 4);
    g.fill();
    g.stroke();
    g.fillStyle = p.grain;
    rrect(g, x + w * 0.06, ty + th * 0.16, w * 0.64, th * 0.6, 3);
    g.fill();
    g.fillStyle = p.ripeLight;
    for (let i = 0; i < 4; i++) {
      g.beginPath();
      g.ellipse(x + w * (0.15 + i * 0.14), ty + th * 0.28, w * 0.07, th * 0.1, 0.2, 0, TAU);
      g.fill();
    }
    g.strokeStyle = p.machineDark;
    g.globalAlpha = 0.45;
    g.lineWidth = Math.max(1, cell * 0.02);
    g.beginPath();
    g.moveTo(x + w * 0.08, ty + th * 0.42);
    g.lineTo(x + w * 0.68, ty + th * 0.42);
    g.stroke();
    g.globalAlpha = 1;
    g.fillStyle = p.cream;
    rrect(g, x + w * 0.06, ty + th * 0.04, w * 0.64, th * 0.1, 2);
    g.fill();
    // cab
    g.fillStyle = p.machine.cultivate;
    g.strokeStyle = p.machineDark;
    g.lineWidth = Math.max(1, cell * 0.03);
    rrect(g, x + w * 0.76, ty + th * 0.2, w * 0.21, th * 0.52, 3);
    g.fill();
    g.stroke();
    g.fillStyle = p.glass;
    rrect(g, x + w * 0.81, ty + th * 0.27, w * 0.11, th * 0.17, 2);
    g.fill();
    // auger to the side
    g.strokeStyle = p.machineDark;
    g.lineWidth = Math.max(2, cell * 0.08);
    g.lineCap = 'round';
    g.beginPath();
    g.moveTo(x + w * 0.65, ty + th * 0.3);
    g.lineTo(x + w * 1.02, ty + th * 0.06);
    g.lineTo(x + w * 1.08, ty + th * 0.24);
    g.stroke();
    g.strokeStyle = p.cream;
    g.lineWidth = Math.max(1, cell * 0.045);
    g.beginPath();
    g.moveTo(x + w * 0.65, ty + th * 0.3);
    g.lineTo(x + w * 1.02, ty + th * 0.06);
    g.stroke();
    g.fillStyle = p.machineDark;
    g.beginPath();
    g.arc(x + w * 1.08, ty + th * 0.24, Math.max(1.2, cell * 0.035), 0, TAU);
    g.fill();
    g.fillStyle = p.ripeLight;
    for (let i = 0; i < 3; i++) {
      g.beginPath();
      g.arc(x + w * 1.06 + i * cell * 0.035, ty + th * 0.3 + i * cell * 0.02, Math.max(1, cell * 0.02), 0, TAU);
      g.fill();
    }
    // wheels
    g.fillStyle = p.machineDark;
    for (const wx of [0.19, 0.48, 0.86]) {
      g.beginPath();
      g.arc(x + w * wx, ty + th * 0.96, Math.max(2, cell * 0.07), 0, TAU);
      g.fill();
    }
    g.fillStyle = p.hub;
    for (const wx of [0.19, 0.48, 0.86]) {
      g.beginPath();
      g.arc(x + w * wx, ty + th * 0.96, Math.max(0.8, cell * 0.026), 0, TAU);
      g.fill();
    }
    if (state.theme === 'night') {
      g.fillStyle = p.headlight;
      g.globalAlpha = 0.9;
      g.beginPath();
      g.arc(x + w * 0.93, ty + th * 0.38, Math.max(1.5, cell * 0.04), 0, TAU);
      g.fill();
      g.globalAlpha = 1;
    }
  }

  function drawTanker(g, f, cell, p) {
    const y = f.y - view.roadH - 2;
    const h = view.roadH;
    const cx = truckPos();
    const w = cell * 2.2;
    const th = h * 0.92;
    const x = clamp(cx - w / 2, f.x - 4, f.x + f.w - w + 4);
    const ty = y + (h - th) / 2;
    g.fillStyle = p.shadow;
    g.globalAlpha = 0.7;
    rrect(g, x + 3, ty + 4, w, th, 4);
    g.fill();
    g.globalAlpha = 1;
    g.fillStyle = p.machine.spray;
    g.strokeStyle = p.machineDark;
    g.lineWidth = Math.max(1, cell * 0.03);
    rrect(g, x, ty + th * 0.08, w * 0.74, th * 0.78, th * 0.32);
    g.fill();
    g.stroke();
    g.fillStyle = rgba(p.cream, 0.35);
    rrect(g, x + w * 0.07, ty + th * 0.2, w * 0.52, th * 0.16, th * 0.08);
    g.fill();
    g.strokeStyle = rgba(p.machineDark, 0.5);
    g.lineWidth = Math.max(1, cell * 0.02);
    for (let i = 0; i < 3; i++) {
      const rx = x + w * (0.18 + i * 0.16);
      g.beginPath();
      g.moveTo(rx, ty + th * 0.22);
      g.lineTo(rx, ty + th * 0.7);
      g.stroke();
    }
    g.fillStyle = p.cream;
    rrect(g, x + w * 0.05, ty + th * 0.1, w * 0.64, th * 0.08, 2);
    g.fill();
    g.fillStyle = p.machine.spray;
    g.strokeStyle = p.machineDark;
    g.lineWidth = Math.max(1, cell * 0.03);
    rrect(g, x + w * 0.72, ty + th * 0.18, w * 0.24, th * 0.54, 3);
    g.fill();
    g.stroke();
    g.fillStyle = p.glass;
    rrect(g, x + w * 0.77, ty + th * 0.25, w * 0.13, th * 0.18, 2);
    g.fill();
    g.strokeStyle = p.machineDark;
    g.lineWidth = Math.max(1.4, cell * 0.035);
    g.beginPath();
    g.moveTo(x + w * 0.78, ty + th * 0.52);
    g.quadraticCurveTo(x + w * 0.9, ty + th * 0.78, x + w * 1.02, ty + th * 0.9);
    g.stroke();
    g.fillStyle = p.cream;
    g.beginPath();
    g.arc(x + w * 0.74, ty + th * 0.74, Math.max(2, cell * 0.07), 0, TAU);
    g.fill();
    g.strokeStyle = p.sprayDew;
    g.lineWidth = Math.max(1, cell * 0.025);
    g.beginPath();
    g.arc(x + w * 0.74, ty + th * 0.74, Math.max(1, cell * 0.035), 0, TAU);
    g.stroke();
    g.fillStyle = p.machineDark;
    for (const wx of [0.19, 0.48, 0.86]) {
      g.beginPath();
      g.arc(x + w * wx, ty + th * 0.94, Math.max(2, cell * 0.07), 0, TAU);
      g.fill();
    }
    g.fillStyle = p.hub;
    for (const wx of [0.19, 0.48, 0.86]) {
      g.beginPath();
      g.arc(x + w * wx, ty + th * 0.94, Math.max(0.8, cell * 0.026), 0, TAU);
      g.fill();
    }
    if (state.theme === 'night') {
      g.fillStyle = p.headlight;
      g.globalAlpha = 0.9;
      g.beginPath();
      g.arc(x + w * 0.95, ty + th * 0.34, Math.max(1.5, cell * 0.04), 0, TAU);
      g.fill();
      g.globalAlpha = 1;
    }
  }

  function quadPoint(a, c, b, t) {
    const u = 1 - t;
    return {
      x: u * u * a.x + 2 * u * t * c.x + t * t * b.x,
      y: u * u * a.y + 2 * u * t * c.y + t * t * b.y
    };
  }

  function drawTransferRig(g, f, cell, p, now, mcx, mcy) {
    if (state.auto || state.done) return;
    if (!inSupplyZone() || !transferNeeds()) return;
    const harvest = state.mode === 'harvest';
    const out = supplyOutlet();
    const bodyOffset = harvest ? cell * 0.36 : -cell * 0.36;
    const attach = {
      x: mcx - Math.sin(state.angle) * bodyOffset,
      y: mcy + Math.cos(state.angle) * bodyOffset
    };
    const from = harvest ? attach : out;
    const to = harvest ? out : attach;
    const ctrl = {
      x: (from.x + to.x) / 2 + (harvest ? cell * 0.55 : -cell * 0.3),
      y: (from.y + to.y) / 2 - cell * 0.16
    };
    const accent = harvest ? p.ripeLight : p.sprayDew;
    g.save();
    g.lineCap = 'round';
    g.strokeStyle = p.shadow;
    g.globalAlpha = 0.6;
    g.lineWidth = Math.max(4, cell * 0.15);
    g.beginPath();
    g.moveTo(from.x + 1, from.y + 3);
    g.quadraticCurveTo(ctrl.x + 1, ctrl.y + 3, to.x + 1, to.y + 3);
    g.stroke();
    g.globalAlpha = 1;

    g.strokeStyle = p.machineDark;
    g.lineWidth = Math.max(4, cell * 0.115);
    g.beginPath();
    g.moveTo(from.x, from.y);
    g.quadraticCurveTo(ctrl.x, ctrl.y, to.x, to.y);
    g.stroke();
    g.strokeStyle = rgba(p.cream, 0.55);
    g.lineWidth = Math.max(1, cell * 0.028);
    g.beginPath();
    g.moveTo(from.x, from.y - cell * 0.025);
    g.quadraticCurveTo(ctrl.x, ctrl.y - cell * 0.025, to.x, to.y - cell * 0.025);
    g.stroke();

    if (state.transferActive) {
      g.strokeStyle = accent;
      g.globalAlpha = 0.92;
      g.lineWidth = Math.max(1.8, cell * 0.042);
      g.setLineDash([cell * 0.07, cell * 0.15]);
      g.lineDashOffset = reduced() ? 0 : -now / 22;
      g.beginPath();
      g.moveTo(from.x, from.y);
      g.quadraticCurveTo(ctrl.x, ctrl.y, to.x, to.y);
      g.stroke();
      g.setLineDash([]);
      g.globalAlpha = 1;
      const speed = state.transferHold ? 2.4 : 1.15;
      for (let i = 0; i < 5; i++) {
        const t = ((now / 1000) * speed + i / 5) % 1;
        const pt = quadPoint(from, ctrl, to, t);
        g.fillStyle = accent;
        g.beginPath();
        if (harvest) g.arc(pt.x, pt.y, Math.max(1.5, cell * 0.034), 0, TAU);
        else g.ellipse(pt.x, pt.y, Math.max(1.4, cell * 0.03), Math.max(2.2, cell * 0.052), -0.3, 0, TAU);
        g.fill();
      }
    }

    for (const pt of [from, to]) {
      g.fillStyle = p.cream;
      g.strokeStyle = p.machineDark;
      g.lineWidth = Math.max(1, cell * 0.026);
      g.beginPath();
      g.arc(pt.x, pt.y, Math.max(2.4, cell * 0.07), 0, TAU);
      g.fill();
      g.stroke();
      g.fillStyle = accent;
      g.beginPath();
      g.arc(pt.x, pt.y, Math.max(1, cell * 0.026), 0, TAU);
      g.fill();
    }
    if (state.transferActive) {
      const pulse = reduced() ? 0.6 : 0.35 + 0.35 * Math.sin(now / 190);
      g.strokeStyle = rgba(accent, 0.4 + pulse * 0.5);
      g.lineWidth = Math.max(1.2, cell * 0.035);
      g.beginPath();
      g.arc(to.x, to.y, Math.max(4, cell * 0.12) + pulse * cell * 0.02, 0, TAU);
      g.stroke();
    }
    g.restore();
  }

  function drawTransferBadge(g, f, cell, p, now) {
    if (state.auto || state.done) return;
    if (!inSupplyZone() || !transferNeeds()) return;
    const fp = footSize(state.orient);
    const mcx = f.x + (state.disp.x + fp.w / 2) * cell;
    const mcy = f.y + (state.disp.y + fp.h / 2) * cell;
    const r = Math.max(10, cell * 0.31);
    let side = 1;
    let bx = f.x + (state.disp.x - 0.47) * cell;
    if (bx - r < f.x + r * 0.35) {
      bx = f.x + (state.disp.x + fp.w + 0.47) * cell;
      side = -1;
    }
    const by = mcy;
    const frac = state.mode === 'harvest' ? clamp(state.load / state.cap, 0, 1) : clamp(state.load / state.tankCap, 0, 1);
    const accent = state.mode === 'harvest' ? p.ripe : p.sprayDew;
    g.save();
    g.fillStyle = p.shadow;
    g.globalAlpha = 0.35;
    g.beginPath();
    g.arc(bx + 1, by + 2, r + 1, 0, TAU);
    g.fill();
    g.globalAlpha = 1;
    g.fillStyle = rgba(p.cream, 0.95);
    g.strokeStyle = p.machineDark;
    g.lineWidth = Math.max(1, cell * 0.026);
    g.beginPath();
    g.moveTo(bx + side * r * 0.5, by - r * 0.36);
    g.lineTo(bx + side * (r + cell * 0.14), by);
    g.lineTo(bx + side * r * 0.5, by + r * 0.36);
    g.closePath();
    g.fill();
    g.stroke();
    g.beginPath();
    g.arc(bx, by, r, 0, TAU);
    g.fill();
    g.stroke();
    g.strokeStyle = rgba(p.machineDark, 0.16);
    g.lineWidth = Math.max(2, cell * 0.055);
    g.beginPath();
    g.arc(bx, by, r * 0.72, 0, TAU);
    g.stroke();
    if (frac > 0.002) {
      g.strokeStyle = accent;
      g.lineCap = 'round';
      g.lineWidth = Math.max(2, cell * 0.055);
      g.beginPath();
      g.arc(bx, by, r * 0.72, -Math.PI / 2, -Math.PI / 2 + frac * TAU);
      g.stroke();
    }
    g.fillStyle = p.machineDark;
    g.font = '700 ' + Math.max(8, Math.round(cell * 0.19)) + 'px ui-monospace, SFMono-Regular, Menlo, monospace';
    g.textAlign = 'center';
    g.textBaseline = 'middle';
    g.fillText(String(state.mode === 'harvest' ? Math.ceil(state.load - 0.001) : Math.floor(state.load + 0.001)), bx, by + 0.5);
    if (state.transferActive) {
      const pulse = reduced() ? 0.5 : 0.5 + 0.5 * Math.sin(now / 180);
      g.strokeStyle = rgba(accent, 0.35 + pulse * 0.45);
      g.lineWidth = Math.max(1, cell * 0.028);
      g.beginPath();
      g.arc(bx, by, r + Math.max(2, cell * 0.07) + pulse * cell * 0.025, 0, TAU);
      g.stroke();
    }
    g.restore();
  }

  function drawTransferFlash(g, cell, p, now, mcx, mcy) {
    const t = (now - state.transferFlashAt) / 520;
    if (!state.transferFlashAt || t < 0 || t > 1) return;
    const accent = state.mode === 'harvest' ? p.ripeLight : p.sprayDew;
    g.save();
    g.strokeStyle = accent;
    g.globalAlpha = (1 - t) * 0.6;
    g.lineWidth = Math.max(1.5, cell * 0.05) * (1 - t * 0.4);
    g.beginPath();
    g.arc(mcx, mcy, cell * (0.55 + t * 0.9), 0, TAU);
    g.stroke();
    g.strokeStyle = p.cream;
    g.globalAlpha = (1 - t) * 0.28;
    g.lineWidth = Math.max(1, cell * 0.03);
    g.beginPath();
    g.arc(mcx, mcy, cell * (0.35 + t * 0.7), 0, TAU);
    g.stroke();
    g.restore();
  }

  function drawCultivatorTool(g, cx, impCY, impW, impH, cell, p, dark) {
    g.fillStyle = p.steel;
    g.strokeStyle = dark;
    g.lineWidth = Math.max(1, cell * 0.03);
    rrect(g, cx - impW / 2, impCY - impH * 0.5, impW, impH * 0.52, 3);
    g.fill();
    g.stroke();
    g.strokeStyle = dark;
    g.lineWidth = Math.max(1.2, cell * 0.04);
    for (let i = -2.5; i <= 2.5; i++) {
      const tx = cx + i * impW / 6;
      g.beginPath();
      g.moveTo(tx, impCY + impH * 0.04);
      g.quadraticCurveTo(tx - cell * 0.035, impCY + impH * 0.34, tx, impCY + impH * 0.62);
      g.stroke();
    }
    g.fillStyle = p.cream;
    g.strokeStyle = dark;
    g.lineWidth = Math.max(1, cell * 0.025);
    rrect(g, cx - impW * 0.42, impCY + impH * 0.42, impW * 0.84, impH * 0.28, impH * 0.14);
    g.fill();
    g.stroke();
    g.strokeStyle = p.steel;
    g.lineWidth = Math.max(1, cell * 0.02);
    g.beginPath();
    g.moveTo(cx - impW * 0.36, impCY + impH * 0.56);
    g.lineTo(cx + impW * 0.36, impCY + impH * 0.56);
    g.stroke();
  }

  function drawSeederTool(g, cx, impCY, impW, impH, cell, p, dark) {
    g.fillStyle = p.machine.sow;
    g.strokeStyle = dark;
    g.lineWidth = Math.max(1, cell * 0.03);
    rrect(g, cx - impW / 2, impCY - impH * 0.5, impW, impH * 0.42, 3);
    g.fill();
    g.stroke();
    g.strokeStyle = dark;
    g.lineWidth = Math.max(1, cell * 0.032);
    for (let i = -2; i <= 2; i++) {
      const tx = cx + i * impW * 0.14;
      g.beginPath();
      g.moveTo(tx, impCY - impH * 0.14);
      g.lineTo(tx, impCY + impH * 0.48);
      g.stroke();
      g.fillStyle = p.ripe;
      g.beginPath();
      g.arc(tx, impCY + impH * 0.56, Math.max(1, cell * 0.022), 0, TAU);
      g.fill();
    }
    g.strokeStyle = dark;
    g.lineWidth = Math.max(1.2, cell * 0.05);
    for (const side of [-1, 1]) {
      const mx = cx + side * impW * 0.57;
      g.beginPath();
      g.moveTo(cx + side * impW * 0.4, impCY - impH * 0.14);
      g.lineTo(mx, impCY - impH * 0.42);
      g.stroke();
      g.fillStyle = p.cream;
      g.beginPath();
      g.arc(mx, impCY - impH * 0.44, cell * 0.075, 0, TAU);
      g.fill();
      g.fillStyle = p.machineDark;
      g.beginPath();
      g.arc(mx, impCY - impH * 0.44, cell * 0.026, 0, TAU);
      g.fill();
    }
  }

  function drawCombineHeader(g, cx, impCY, impW, impH, cell, p, dark, front) {
    g.save();
    if (front) { g.translate(cx, impCY); g.scale(1, -1); g.translate(-cx, -impCY); }
    g.fillStyle = p.steel;
    g.strokeStyle = dark;
    g.lineWidth = Math.max(1, cell * 0.03);
    rrect(g, cx - impW / 2, impCY - impH * 0.35, impW, impH * 0.9, 3);
    g.fill();
    g.stroke();
    g.fillStyle = p.cream;
    g.strokeStyle = dark;
    g.lineWidth = Math.max(1, cell * 0.025);
    rrect(g, cx - impW * 0.43, impCY - impH * 0.62, impW * 0.86, impH * 0.48, impH * 0.22);
    g.fill();
    g.stroke();
    g.strokeStyle = dark;
    g.globalAlpha = 0.7;
    g.lineWidth = Math.max(1, cell * 0.022);
    for (let i = -2; i <= 2; i++) {
      const bx = cx + i * impW * 0.15;
      g.beginPath();
      g.moveTo(bx, impCY - impH * 0.54);
      g.lineTo(bx + cell * 0.03, impCY - impH * 0.2);
      g.stroke();
    }
    g.globalAlpha = 1;
    g.fillStyle = p.machineDark;
    g.fillRect(cx - impW * 0.45, impCY + impH * 0.42, impW * 0.9, Math.max(1.5, cell * 0.035));
    g.fillStyle = p.glass;
    for (const side of [-1, 1]) {
      g.beginPath();
      g.arc(cx + side * impW * 0.45, impCY - impH * 0.38, Math.max(1.5, cell * 0.04), 0, TAU);
      g.fill();
    }
    g.restore();
  }

  function drawSprayerBoom(g, cx, impCY, impW, impH, cell, p, dark) {
    g.fillStyle = p.machine.spray;
    g.strokeStyle = dark;
    g.lineWidth = Math.max(1, cell * 0.03);
    rrect(g, cx - impW / 2, impCY - impH * 0.18, impW, impH * 0.42, 3);
    g.fill();
    g.stroke();
    for (let i = -2; i <= 2; i++) {
      const nx = cx + i * impW * 0.18;
      g.fillStyle = dark;
      g.beginPath();
      g.arc(nx, impCY + impH * 0.26, Math.max(1, cell * 0.022), 0, TAU);
      g.fill();
      g.fillStyle = p.sprayDew;
      g.beginPath();
      g.ellipse(nx, impCY + impH * 0.52, Math.max(1, cell * 0.018), Math.max(1.5, cell * 0.032), 0, 0, TAU);
      g.fill();
    }
    g.fillStyle = rgba(p.sprayDew, 0.14);
    g.beginPath();
    g.moveTo(cx - impW * 0.46, impCY + impH * 0.38);
    g.lineTo(cx + impW * 0.46, impCY + impH * 0.38);
    g.lineTo(cx + impW * 0.56, impCY + impH * 1.02);
    g.lineTo(cx - impW * 0.56, impCY + impH * 1.02);
    g.closePath();
    g.fill();
  }

  function drawMachine(g, cx, cy, cell, mode, opts) {
    opts = opts || {};
    const p = PALETTE[state.theme];
    const color = p.machine[mode];
    const dark = p.machineDark;
    const cream = p.cream;
    const glass = p.glass;
    const hub = p.hub;
    const bodyW = cell * (mode === 'cultivate' ? 0.78 : mode === 'sow' ? 0.88 : mode === 'spray' ? 0.86 : 1.0);
    const bodyH = cell * (mode === 'cultivate' ? 1.0 : mode === 'sow' ? 1.12 : mode === 'spray' ? 1.08 : 1.26);
    const bodyOffset = mode === 'harvest' ? cell * 0.36 : -cell * 0.36;
    const bodyCY = cy + bodyOffset;
    const impW = cell * Math.max(1, BAR - (mode === 'harvest' ? 0.04 : 0.1));
    const impH = cell * (mode === 'harvest' ? 0.42 : mode === 'spray' ? 0.26 : 0.32);
    const impCY = cy;
    const tilt = opts.tilt || 0;
    const angle = opts.angle || 0;
    const implAngle = opts.implAngle || 0;

    g.fillStyle = p.shadow;
    g.beginPath();
    g.ellipse(cx + cell * 0.04, cy + cell * 0.1, cell * 1.02, cell * 0.32, 0, 0, TAU);
    g.fill();

    g.save();
    g.translate(cx, cy);
    g.rotate(implAngle + tilt);
    g.translate(-cx, -cy);
    if (mode === 'cultivate') drawCultivatorTool(g, cx, impCY, impW, impH, cell, p, dark);
    else if (mode === 'sow') drawSeederTool(g, cx, impCY, impW, impH, cell, p, dark);
    else if (mode === 'spray') drawSprayerBoom(g, cx, impCY, impW, impH, cell, p, dark);
    else drawCombineHeader(g, cx, impCY, impW, impH, cell, p, dark, true);
    g.restore();

    g.save();
    g.translate(cx, cy);
    g.rotate(angle + tilt);
    g.translate(-cx, -cy);
    g.strokeStyle = dark;
    g.lineWidth = Math.max(1.5, cell * 0.07);
    g.beginPath();
    g.moveTo(cx, mode === 'harvest' ? bodyCY - bodyH * 0.4 : bodyCY + bodyH * 0.4);
    g.lineTo(cx, impCY);
    g.stroke();

    const wheelR = cell * (mode === 'harvest' ? 0.16 : 0.14);
    for (const side of [-1, 1]) {
      for (const [dy, rr] of [[-0.3, 0.88], [0.3, mode === 'harvest' ? 1.18 : 1]]) {
        const wx = cx + side * bodyW * 0.58;
        const wy = bodyCY + bodyH * dy;
        g.fillStyle = dark;
        g.beginPath();
        g.ellipse(wx, wy, wheelR * 0.92, wheelR * 1.12 * rr, 0, 0, TAU);
        g.fill();
        g.fillStyle = hub;
        g.beginPath();
        g.ellipse(wx, wy, wheelR * 0.38, wheelR * 0.46 * rr, 0, 0, TAU);
        g.fill();
        g.fillStyle = dark;
        g.globalAlpha = 0.55;
        g.beginPath();
        g.ellipse(wx, wy, wheelR * 0.12, wheelR * 0.16 * rr, 0, 0, TAU);
        g.fill();
        g.globalAlpha = 1;
      }
    }

    g.fillStyle = color;
    g.strokeStyle = dark;
    g.lineWidth = Math.max(1.2, cell * 0.035);
    rrect(g, cx - bodyW / 2, bodyCY - bodyH / 2, bodyW, bodyH, bodyW * 0.26);
    g.fill();
    g.stroke();

    g.fillStyle = rgba(cream, 0.14);
    rrect(g, cx - bodyW * 0.38, bodyCY - bodyH * 0.43, bodyW * 0.76, bodyH * 0.24, bodyW * 0.13);
    g.fill();

    g.fillStyle = rgba(cream, 0.34);
    g.strokeStyle = dark;
    g.lineWidth = Math.max(1, cell * 0.024);
    rrect(g, cx - bodyW * 0.4, bodyCY - bodyH * 0.47, bodyW * 0.8, bodyH * 0.16, bodyW * 0.1);
    g.fill();
    g.stroke();
    g.strokeStyle = dark;
    g.globalAlpha = 0.3;
    g.lineWidth = Math.max(1, cell * 0.022);
    for (let i = -1; i <= 1; i++) {
      g.beginPath();
      g.moveTo(cx + i * bodyW * 0.16, bodyCY - bodyH * 0.43);
      g.lineTo(cx + i * bodyW * 0.16, bodyCY - bodyH * 0.33);
      g.stroke();
    }
    g.globalAlpha = 1;
    g.fillStyle = p.headlight;
    g.globalAlpha = state.theme === 'night' ? 0.95 : 0.75;
    g.beginPath();
    g.arc(cx - bodyW * 0.3, bodyCY - bodyH * 0.46, Math.max(1.2, cell * 0.03), 0, TAU);
    g.arc(cx + bodyW * 0.3, bodyCY - bodyH * 0.46, Math.max(1.2, cell * 0.03), 0, TAU);
    g.fill();
    g.globalAlpha = 1;

    if (mode === 'sow') {
      g.fillStyle = cream;
      g.strokeStyle = dark;
      g.lineWidth = Math.max(1.1, cell * 0.03);
      rrect(g, cx - bodyW * 0.34, bodyCY + bodyH * 0.02, bodyW * 0.68, bodyH * 0.36, bodyW * 0.12);
      g.fill();
      g.stroke();
      g.strokeStyle = p.machineDark;
      g.globalAlpha = 0.45;
      g.lineWidth = Math.max(1, cell * 0.022);
      g.beginPath();
      g.moveTo(cx - bodyW * 0.26, bodyCY + bodyH * 0.12);
      g.lineTo(cx + bodyW * 0.26, bodyCY + bodyH * 0.12);
      g.stroke();
      g.globalAlpha = 1;
      g.fillStyle = p.glass;
      rrect(g, cx - bodyW * 0.07, bodyCY + bodyH * 0.2, bodyW * 0.14, bodyH * 0.09, 2);
      g.fill();
      g.fillStyle = p.ripe;
      for (let i = -1; i <= 1; i++) {
        g.beginPath();
        g.arc(cx + i * bodyW * 0.15, bodyCY + bodyH * 0.29, Math.max(1, cell * 0.02), 0, TAU);
        g.fill();
      }
    } else if (mode === 'harvest') {
      g.fillStyle = cream;
      g.strokeStyle = dark;
      g.lineWidth = Math.max(1.1, cell * 0.03);
      rrect(g, cx - bodyW * 0.34, bodyCY + bodyH * 0.02, bodyW * 0.68, bodyH * 0.4, bodyW * 0.12);
      g.fill();
      g.stroke();
      g.strokeStyle = p.machineDark;
      g.globalAlpha = 0.45;
      g.lineWidth = Math.max(1, cell * 0.022);
      g.beginPath();
      g.moveTo(cx - bodyW * 0.24, bodyCY + bodyH * 0.16);
      g.lineTo(cx + bodyW * 0.24, bodyCY + bodyH * 0.16);
      g.stroke();
      g.globalAlpha = 1;
      g.fillStyle = p.ripe;
      g.beginPath();
      g.ellipse(cx + bodyW * 0.03, bodyCY + bodyH * 0.12, bodyW * 0.14, bodyH * 0.07, 0, 0, TAU);
      g.fill();
      g.strokeStyle = dark;
      g.lineWidth = Math.max(1.5, cell * 0.07);
      g.beginPath();
      g.moveTo(cx + bodyW * 0.18, bodyCY + bodyH * 0.18);
      g.lineTo(cx + bodyW * 0.92, bodyCY + bodyH * 0.04);
      g.lineTo(cx + bodyW * 1.0, bodyCY - bodyH * 0.02);
      g.stroke();
      g.strokeStyle = cream;
      g.lineWidth = Math.max(1, cell * 0.04);
      g.beginPath();
      g.moveTo(cx + bodyW * 0.18, bodyCY + bodyH * 0.18);
      g.lineTo(cx + bodyW * 0.92, bodyCY + bodyH * 0.04);
      g.stroke();
      g.fillStyle = cream;
      g.beginPath();
      g.arc(cx + bodyW * 1.0, bodyCY - bodyH * 0.02, cell * 0.06, 0, TAU);
      g.fill();
      g.fillStyle = p.machineDark;
      g.beginPath();
      g.arc(cx + bodyW * 1.0, bodyCY - bodyH * 0.02, cell * 0.022, 0, TAU);
      g.fill();
    } else if (mode === 'spray') {
      g.fillStyle = cream;
      g.strokeStyle = dark;
      g.lineWidth = Math.max(1.1, cell * 0.03);
      rrect(g, cx - bodyW * 0.35, bodyCY + bodyH * 0.01, bodyW * 0.7, bodyH * 0.38, bodyW * 0.14);
      g.fill();
      g.stroke();
      g.fillStyle = glass;
      rrect(g, cx - bodyW * 0.26, bodyCY + bodyH * 0.1, bodyW * 0.52, bodyH * 0.1, 3);
      g.fill();
      g.strokeStyle = p.machineDark;
      g.globalAlpha = 0.4;
      g.lineWidth = Math.max(1, cell * 0.02);
      g.beginPath();
      g.moveTo(cx - bodyW * 0.28, bodyCY + bodyH * 0.25);
      g.lineTo(cx + bodyW * 0.28, bodyCY + bodyH * 0.25);
      g.stroke();
      g.globalAlpha = 1;
      g.strokeStyle = dark;
      g.lineWidth = Math.max(1.2, cell * 0.035);
      g.beginPath();
      g.moveTo(cx + bodyW * 0.3, bodyCY + bodyH * 0.28);
      g.quadraticCurveTo(cx + bodyW * 0.45, bodyCY + bodyH * 0.36, cx + bodyW * 0.42, bodyCY + bodyH * 0.46);
      g.stroke();
      g.fillStyle = p.machineDark;
      g.beginPath();
      g.arc(cx + bodyW * 0.42, bodyCY + bodyH * 0.48, Math.max(1, cell * 0.025), 0, TAU);
      g.fill();
    }

    const cabW = bodyW * (mode === 'cultivate' ? 0.56 : mode === 'sow' ? 0.54 : 0.52);
    const cabH = bodyH * 0.34;
    const cabY = bodyCY - bodyH * (mode === 'harvest' ? 0.2 : mode === 'sow' ? 0.18 : 0.12);
    g.fillStyle = cream;
    g.strokeStyle = dark;
    g.lineWidth = Math.max(1.1, cell * 0.028);
    rrect(g, cx - cabW / 2, cabY - cabH / 2, cabW, cabH, cabW * 0.16);
    g.fill();
    g.stroke();
    g.fillStyle = glass;
    rrect(g, cx - cabW * 0.4, cabY - cabH * 0.42, cabW * 0.8, cabH * 0.3, 2);
    g.fill();
    g.strokeStyle = dark;
    g.globalAlpha = 0.4;
    g.lineWidth = 1;
    g.beginPath();
    g.moveTo(cx, cabY - cabH * 0.42);
    g.lineTo(cx, cabY - cabH * 0.1);
    g.stroke();
    g.globalAlpha = 1;
    g.fillStyle = p.beacon;
    g.beginPath();
    g.arc(cx + cabW * 0.28, cabY - cabH * 0.56, Math.max(1, cell * 0.03), 0, TAU);
    g.fill();
    g.fillStyle = cream;
    g.globalAlpha = 0.8;
    g.beginPath();
    g.arc(cx + cabW * 0.28, cabY - cabH * 0.56, Math.max(0.5, cell * 0.012), 0, TAU);
    g.fill();
    g.globalAlpha = 1;

    if (state.theme === 'night' && !opts.thumb) {
      const glow = g.createRadialGradient(cx, bodyCY - bodyH * 0.5, 0, cx, bodyCY - bodyH * 0.5, cell * 1.7);
      glow.addColorStop(0, p.glow);
      glow.addColorStop(1, 'rgba(255,213,128,0)');
      g.fillStyle = glow;
      g.beginPath();
      g.arc(cx, bodyCY - bodyH * 0.5, cell * 1.7, 0, TAU);
      g.fill();
    }
    g.restore();
  }



  function drawStonePatchTexture(g, cx, cy, r, cell, kind, p, seed, dx, dy, diag) {
    if (diag || kind === 'unreachable') return;
    const jitter = (i) => (hash(seed, i, 5) - 0.5) * r * 0.9;
    if (kind === 'soil' || kind === 'path') {
      g.strokeStyle = p.furrow;
      g.globalAlpha = 0.4;
      g.lineWidth = Math.max(1, cell * 0.026);
      for (let i = 0; i < 2; i++) {
        const px = cx + jitter(i);
        const py = cy + jitter(i + 4);
        g.beginPath();
        g.moveTo(px - r * 0.32, py - r * 0.24);
        g.lineTo(px + r * 0.32, py + r * 0.18);
        g.stroke();
      }
      g.globalAlpha = 1;
    } else if (kind === 'stubble') {
      g.strokeStyle = p.stubble;
      g.globalAlpha = 0.8;
      g.lineWidth = Math.max(1, cell * 0.026);
      g.lineCap = 'round';
      for (let i = 0; i < 2; i++) {
        const px = cx + jitter(i);
        const py = cy + jitter(i + 4);
        g.beginPath();
        g.moveTo(px, py + r * 0.18);
        g.lineTo(px + (hash(seed, i, 9) - 0.5) * r * 0.5, py - r * 0.24);
        g.stroke();
      }
      g.globalAlpha = 1;
    } else if (kind === 'wild') {
      g.strokeStyle = p.wildTuft;
      g.globalAlpha = 0.55;
      g.lineWidth = Math.max(1, cell * 0.022);
      g.lineCap = 'round';
      for (let i = 0; i < 2; i++) {
        const px = cx + jitter(i);
        const py = cy + jitter(i + 4);
        g.beginPath();
        g.moveTo(px, py + r * 0.24);
        g.quadraticCurveTo(px - r * 0.2, py, px + (hash(seed, i, 7) - 0.5) * r * 0.5, py - r * 0.26);
        g.stroke();
      }
      g.globalAlpha = 1;
    } else if (kind === 'crop' || kind === 'sprayed') {
      g.strokeStyle = p.weed;
      g.lineWidth = Math.max(1, cell * 0.02);
      g.lineCap = 'round';
      g.fillStyle = p.weedLight;
      for (let i = 0; i < 2; i++) {
        const px = cx + jitter(i);
        const py = cy + jitter(i + 4);
        g.beginPath();
        g.moveTo(px, py + r * 0.2);
        g.lineTo(px, py - r * 0.16);
        g.stroke();
        g.beginPath();
        g.ellipse(px - r * 0.16, py - r * 0.12, r * 0.22, r * 0.1, -0.5, 0, TAU);
        g.ellipse(px + r * 0.16, py - r * 0.16, r * 0.22, r * 0.1, 0.5, 0, TAU);
        g.fill();
      }
      if (kind === 'sprayed') {
        g.fillStyle = p.sprayDew;
        g.beginPath();
        g.arc(cx, cy, Math.max(1, cell * 0.02), 0, TAU);
        g.fill();
      }
    } else if (kind === 'ripe') {
      g.strokeStyle = p.ripeStalk;
      g.lineWidth = Math.max(1, cell * 0.022);
      g.lineCap = 'round';
      for (let i = 0; i < 2; i++) {
        const px = cx + jitter(i);
        const py = cy + jitter(i + 4);
        g.beginPath();
        g.moveTo(px, py + r * 0.22);
        g.lineTo(px, py - r * 0.18);
        g.stroke();
        g.fillStyle = p.ripe;
        g.beginPath();
        g.ellipse(px, py - r * 0.22, r * 0.12, r * 0.18, 0, 0, TAU);
        g.fill();
      }
    }
  }

  function drawStoneGround(g, x0, y0, cell, neighbors, p, seed) {
    g.save();
    rrect(g, x0 + 1, y0 + 1, cell - 2, cell - 2, Math.max(2, cell * 0.08));
    g.clip();
    const draw = (n, diag) => {
      const offset = diag ? 0.6 : 0.66;
      const r = cell * (diag ? 0.3 : 0.36);
      const cx = x0 + cell / 2 + n.dx * cell * offset;
      const cy = y0 + cell / 2 + n.dy * cell * offset;
      g.fillStyle = n.m.color;
      g.beginPath();
      g.ellipse(cx, cy, r, r * 0.9, 0, 0, TAU);
      g.fill();
      g.save();
      g.beginPath();
      g.ellipse(cx, cy, r, r * 0.9, 0, 0, TAU);
      g.clip();
      drawStonePatchTexture(g, cx, cy, r, cell, n.m.kind, p, seed + n.dx * 3 + n.dy, n.dx, n.dy, diag);
      g.restore();
    };
    const sides = neighbors.filter((n) => n.dx === 0 || n.dy === 0);
    const diags = neighbors.filter((n) => n.dx !== 0 && n.dy !== 0);
    for (const n of sides) draw(n, false);
    for (const n of diags) draw(n, true);
    g.restore();
  }

  function drawField(g, f, cell, p, now) {
    const mode = state.mode;
    const baseColors = new Array(W * H).fill(null);
    const baseKinds = new Array(W * H).fill(null);
    const stoneKinds = new Array(W * H).fill(null);
    const matAt = (x, y) => {
      if (x < 0 || x >= W || y < 0 || y >= H) return null;
      const kk = key(x, y);
      if (state.rocks.has(kk)) return null;
      const alt = (x + y) % 2 === 0;
      if (state.unreachable.has(kk)) return { color: mode === 'cultivate' ? p.wildAlt : mode === 'sow' ? p.soilAlt : p.ripeAlt, kind: 'unreachable' };
      if (mode === 'spray') {
        if (state.worked.has(kk)) return { color: alt ? p.sprayedAlt : p.sprayed, kind: 'sprayed' };
        return { color: alt ? p.cropAlt : p.crop, kind: 'crop' };
      }
      if (state.worked.has(kk)) return { color: mode === 'harvest' ? p.stubble : (alt ? p.soilAlt : p.soil), kind: mode === 'harvest' ? 'stubble' : 'soil' };
      if (mode === 'cultivate') return { color: alt ? p.wildAlt : p.wild, kind: 'wild' };
      if (mode === 'sow') return { color: isSowLaneCell(x) ? (alt ? p.soilAlt : p.soil) : p.path, kind: isSowLaneCell(x) ? 'soil' : 'path' };
      return { color: alt ? p.ripeAlt : p.ripe, kind: 'ripe' };
    };
    g.save();
    rrect(g, f.x, f.y, f.w, f.h, Math.max(3, cell * 0.08));
    g.clip();

    for (let y = 0; y < H; y++) {
      for (let x = 0; x < W; x++) {
        const k = key(x, y);
        const x0 = f.x + x * cell;
        const y0 = f.y + y * cell;
        const rock = state.rocks.has(k);
        const worked = state.worked.has(k);
        const unreachable = state.unreachable.has(k);
        const mat = rock ? null : matAt(x, y);
        let base = mat ? mat.color : null;
        let kind = mat ? mat.kind : null;
        let rockNeighbors = [];
        if (rock) {
          for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1], [1, 1], [-1, 1], [1, -1], [-1, -1]]) {
            const m = matAt(x + dx, y + dy);
            if (m) rockNeighbors.push({ dx, dy, m });
          }
          if (rockNeighbors.length) {
            const kinds = new Map();
            for (const n of rockNeighbors) kinds.set(n.m.kind, (kinds.get(n.m.kind) || 0) + 1);
            let bestKind = rockNeighbors[0].m.kind;
            let bestN = 0;
            for (const [kk, n] of kinds) if (n > bestN) { bestN = n; bestKind = kk; }
            const colors = new Map();
            for (const n of rockNeighbors) if (n.m.kind === bestKind) colors.set(n.m.color, (colors.get(n.m.color) || 0) + 1);
            let bestColor = null;
            let bn = 0;
            for (const [cc, n] of colors) if (n > bn) { bn = n; bestColor = cc; }
            base = bestColor;
            kind = bestKind;
          } else {
            base = mode === 'cultivate' ? p.wild : mode === 'sow' ? p.soil : p.ripe;
            kind = mode === 'cultivate' ? 'wild' : mode === 'sow' ? 'soil' : 'ripe';
          }
        }
        if (base) {
          baseColors[k] = base;
          baseKinds[k] = kind;
          g.fillStyle = base;
          g.fillRect(x0 - 0.5, y0 - 0.5, cell + 1, cell + 1);
        }
        if (rock) {
          stoneKinds[k] = kind;
          drawStoneGround(g, x0, y0, cell, rockNeighbors, p, k);
        } else if (unreachable) {
          drawHatch(g, x0, y0, cell, p);
        } else if (mode === 'spray') {
          g.strokeStyle = rgba(p.furrow, 0.2);
          g.lineWidth = Math.max(1, cell * 0.024);
          for (let i = 1; i <= 2; i++) {
            const fx = x0 + cell * (i / 3);
            g.beginPath();
            g.moveTo(fx, y0 + cell * 0.12);
            g.lineTo(fx, y0 + cell * 0.88);
            g.stroke();
          }
        } else if (worked) {
          if (mode === 'harvest') drawStubble(g, x0, y0, cell, p, k);
          else drawFurrows(g, x0, y0, cell, p, k);
        } else if (mode === 'sow') {
          if (isSowLaneCell(x)) {
            g.strokeStyle = p.furrow;
            g.globalAlpha = 0.32;
            g.lineWidth = Math.max(1, cell * 0.026);
            for (let i = 1; i <= 3; i++) {
              const fx = x0 + cell * (i / 4);
              g.beginPath();
              g.moveTo(fx, y0 + cell * 0.14);
              g.lineTo(fx, y0 + cell * 0.86);
              g.stroke();
            }
            g.globalAlpha = 1;
          } else {
            g.strokeStyle = rgba(p.furrow, 0.32);
            g.lineWidth = Math.max(1, cell * 0.03);
            g.beginPath();
            g.moveTo(x0 + cell * 0.12, y0 + cell * 0.38);
            g.lineTo(x0 + cell * 0.12, y0 + cell * 0.94);
            g.moveTo(x0 + cell * 0.8, y0 + cell * 0.38);
            g.lineTo(x0 + cell * 0.8, y0 + cell * 0.94);
            g.stroke();
          }
        }
      }
    }

    for (let y = 0; y < H; y++) {
      for (let x = 0; x < W; x++) {
        const k = key(x, y);
        const x0 = f.x + x * cell;
        const y0 = f.y + y * cell;
        g.strokeStyle = p.seam;
        g.lineWidth = 1;
        g.beginPath();
        if (x + 1 < W) {
          g.moveTo(x0 + cell, y0);
          g.lineTo(x0 + cell, y0 + cell);
        }
        if (y + 1 < H) {
          g.moveTo(x0, y0 + cell);
          g.lineTo(x0 + cell, y0 + cell);
        }
        g.stroke();
      }
    }

    for (let y = 0; y < H; y++) {
      for (let x = 0; x < W; x++) {
        const k = key(x, y);
        const a = baseColors[k];
        if (!a) continue;
        const x0 = f.x + x * cell;
        const y0 = f.y + y * cell;
        if (x + 1 < W) {
          const kr = key(x + 1, y);
          const b = baseColors[kr];
          if (b && !state.rocks.has(k) && !state.rocks.has(kr) && baseKinds[kr] !== baseKinds[k]) drawMaterialEdge(g, x0, y0, cell, a, b, 'right');
        }
        if (y + 1 < H) {
          const kb = key(x, y + 1);
          const b = baseColors[kb];
          if (b && !state.rocks.has(k) && !state.rocks.has(kb) && baseKinds[kb] !== baseKinds[k]) drawMaterialEdge(g, x0, y0, cell, a, b, 'bottom');
        }
      }
    }

    if (mode === 'sow') {
      g.fillStyle = p.lane;
      g.strokeStyle = p.laneLine;
      g.lineWidth = Math.max(1, cell * 0.032);
      g.setLineDash([cell * 0.18, cell * 0.15]);
      for (let lane = 0; lane < W; lane += BAR + 1) {
        const lx = f.x + lane * cell;
        const lw = BAR * cell;
        g.fillRect(lx, f.y, lw, f.h);
        g.strokeRect(lx + 1, f.y + 1, lw - 2, f.h - 2);
      }
      g.setLineDash([]);
    }

    for (let y = 0; y < H; y++) {
      for (let x = 0; x < W; x++) {
        const k = key(x, y);
        const x0 = f.x + x * cell;
        const y0 = f.y + y * cell;
        if (state.rocks.has(k) || state.unreachable.has(k)) continue;
        const worked = state.worked.has(k);
        const pat = state.patterns[k];
        if (mode === 'cultivate') {
          if (!worked) {
            drawWild(g, x0, y0, cell, p, k);
            if (state.weeds.has(k)) drawWeed(g, x0, y0, cell, p, k);
          }
        } else if (mode === 'sow') {
          if (worked) {
            for (let i = 0; i < 3; i++) drawSprout(g, x0, y0, cell, p, pat.plants[i]);
            if (state.doubles.has(k)) {
              g.strokeStyle = rgba(p.blocked, 0.75);
              g.lineWidth = Math.max(1.2, cell * 0.032);
              g.setLineDash([cell * 0.08, cell * 0.06]);
              rrect(g, x0 + cell * 0.12, y0 + cell * 0.12, cell * 0.76, cell * 0.76, cell * 0.08);
              g.stroke();
              g.setLineDash([]);
            }
          }
        } else if (mode === 'spray') {
          for (let i = 0; i < 3; i++) drawSprout(g, x0, y0, cell, p, pat.plants[i]);
          if (worked) drawSprayFilm(g, x0, y0, cell, p);
          if (state.doubles.has(k)) {
            g.strokeStyle = rgba(p.sprayDew, 0.8);
            g.lineWidth = Math.max(1.2, cell * 0.03);
            g.setLineDash([cell * 0.08, cell * 0.06]);
            rrect(g, x0 + cell * 0.12, y0 + cell * 0.12, cell * 0.76, cell * 0.76, cell * 0.08);
            g.stroke();
            g.setLineDash([]);
          }
        } else {
          if (!worked) {
            for (let i = 0; i < 4; i++) drawRipe(g, x0, y0, cell, p, pat.plants[i]);
          } else if (state.lost.has(k)) {
            g.strokeStyle = p.blocked;
            g.lineWidth = Math.max(1.5, cell * 0.045);
            g.globalAlpha = 0.85;
            g.beginPath();
            g.moveTo(x0 + cell * 0.28, y0 + cell * 0.28);
            g.lineTo(x0 + cell * 0.72, y0 + cell * 0.72);
            g.moveTo(x0 + cell * 0.72, y0 + cell * 0.28);
            g.lineTo(x0 + cell * 0.28, y0 + cell * 0.72);
            g.stroke();
            g.globalAlpha = 1;
          }
        }
        const t = state.recent.get(k);
        if (t && now - t < 650) {
          g.fillStyle = p.cream;
          g.globalAlpha = (1 - (now - t) / 650) * 0.16;
          g.fillRect(x0, y0, cell, cell);
          g.globalAlpha = 1;
        }
      }
    }

    for (let y = 0; y < H; y++) {
      for (let x = 0; x < W; x++) {
        const k = key(x, y);
        if (state.rocks.has(k)) drawRock(g, f.x + x * cell, f.y + y * cell, cell, p, k, stoneKinds[k]);
      }
    }

    g.restore();
  }

  function drawScenery(g, f, cell, p) {
    g.fillStyle = p.stageTuft;
    g.globalAlpha = 0.55;
    for (let i = 0; i < 14; i++) {
      const tx = hash(i, 1, 2) * view.w;
      const ty = hash(i, 3, 4) * view.h;
      if (tx > f.x - 12 && tx < f.x + f.w + 12 && ty > f.y - 12 && ty < f.y + f.h + 12) continue;
      g.beginPath();
      g.ellipse(tx, ty, 7 + hash(i, 4, 5) * 14, 2.5 + hash(i, 6, 7) * 4, 0, 0, TAU);
      g.fill();
    }
    g.globalAlpha = 0.7;
    g.fillStyle = p.stageFlower;
    for (let i = 0; i < 5; i++) {
      const tx = hash(i, 11, 2) * view.w;
      const ty = hash(i, 13, 4) * view.h;
      if (tx > f.x - 6 && tx < f.x + f.w + 6 && ty > f.y - 6 && ty < f.y + f.h + 6) continue;
      g.beginPath();
      g.arc(tx, ty, Math.max(1.2, cell * 0.035), 0, TAU);
      g.fill();
    }
    g.globalAlpha = 1;
  }



  function drawMinimap(g, p, cell) {
    if (state.ha <= 1) return;
    const f = view.field;
    const mw = 28;
    const mapH = clamp(mw * (H / W), 48, 96);
    const mh = mapH + 12;
    const x = view.w - mw - 22;
    const y = 16;
    g.fillStyle = rgba(p.cream, 0.9);
    rrect(g, x, y, mw, mh, 5);
    g.fill();
    g.strokeStyle = p.machineDark;
    g.globalAlpha = 0.45;
    g.lineWidth = 1;
    rrect(g, x + 0.5, y + 0.5, mw - 1, mh - 1, 5);
    g.stroke();
    g.globalAlpha = 1;
    const mx = x + 6;
    const my = y + 6;
    const mw2 = mw - 12;
    const mh2 = mh - 12;
    g.fillStyle = p.soil;
    g.fillRect(mx, my, mw2, mh2);
    const camTop = state.cam / cell;
    const visRows = view.h / cell;
    const vy = my + clamp(camTop / H, 0, 1) * mh2;
    const vh = Math.min(mh2 - (vy - my), Math.max(3, (visRows / H) * mh2));
    g.fillStyle = rgba(p.cream, 0.18);
    g.fillRect(mx, my, mw2, mh2);
    g.strokeStyle = p.cream;
    g.lineWidth = 1.5;
    g.strokeRect(mx, vy, mw2, vh);
    g.fillStyle = p.rock;
    for (const k of state.rocks) {
      const [rx, ry] = xy(k);
      g.beginPath();
      g.arc(mx + ((rx + 0.5) / W) * mw2, my + ((ry + 0.5) / H) * mh2, 1.2, 0, TAU);
      g.fill();
    }
    g.fillStyle = p.machine[state.mode];
    const mf = footSize(state.orient);
    const px = mx + ((state.disp.x + mf.w / 2) / W) * mw2;
    const py = my + ((state.disp.y + mf.h / 2) / H) * mh2;
    g.beginPath();
    g.arc(px, py, 2.2, 0, TAU);
    g.fill();
    g.strokeStyle = p.machineDark;
    g.lineWidth = 1;
    g.stroke();
    if (state.mode === 'harvest' || state.mode === 'spray') {
      const sx = mx + SUPPLY_FRAC * mw2;
      g.fillStyle = state.mode === 'harvest' ? p.truck : p.machine.spray;
      g.strokeStyle = p.machineDark;
      g.lineWidth = 1;
      rrect(g, sx - 3.5, my - 1, 7, 3, 1.5);
      g.fill();
      g.stroke();
    }
    g.fillStyle = p.machineDark;
    g.font = '700 8px ' + 'ui-monospace, SFMono-Regular, Menlo, monospace';
    g.textAlign = 'center';
    g.fillText(state.ha + ' га', x + mw / 2, y + mh - 4);
  }



/* ---- art helpers shared with the copied mockup drawing block ---- */
let activeGame = null;

function buildPatterns() {
  state.patterns = new Array(W * H);
  for (let y = 0; y < H; y++) {
    for (let x = 0; x < W; x++) {
      const plants = [];
      for (let i = 0; i < 4; i++) {
        plants.push({
          x: 0.12 + hash(x, y, i * 3 + 2) * 0.76,
          y: 0.18 + hash(x + 4, y + 1, i * 5 + 1) * 0.7,
          s: 0.7 + hash(x + 2, y + 7, i * 7 + 3) * 0.55,
          lean: (hash(x + 9, y + 3, i * 11 + 5) - 0.5) * 0.6
        });
      }
      state.patterns[key(x, y)] = {
        alt: hash(x, y, 1),
        plants,
        clods: [hash(x + 3, y + 2, 9), hash(x + 5, y + 8, 13)]
      };
    }
  }
}

function supplyCenterX() {
  if (!activeGame) return 0;
  if (activeGame.fixedTruck) return view.field.x + view.field.w * SUPPLY_FRAC;
  return view.field.x + (state.disp.x + BAR / 2) * view.cell;
}
function truckPos() { return supplyCenterX(); }
function inSupplyZone() { return !!activeGame && (state.mode === 'harvest' || state.mode === 'spray') && activeGame.R.canUnload(); }
function transferNeeds() { return !!activeGame && activeGame.R.transferNeeds(); }
function supplyOutlet() {
  const f = view.field, cell = view.cell, h = view.roadH;
  const y = f.y - h - 2;
  if (state.mode === 'harvest') {
    const w = cell * 2.2, th = h * 0.92;
    const x = clamp(supplyCenterX() - w / 2, f.x - 4, f.x + f.w - w + 4);
    const ty = y + (h - th) / 2;
    return { x: x + w * 1.08, y: ty + th * 0.24 };
  }
  const w = cell * 1.95, th = h * 0.62;
  const x = clamp(supplyCenterX() - w / 2, f.x + 4, f.x + f.w - w - 4);
  const ty = y + (h - th) / 2;
  return { x: x + w * 0.32, y: ty + th * 0.82 };
}

function legendFor(op, unreachable) {
  const items = op === 'sow' ? [['lane', 'полоса'], ['rock', 'камень'], ['sprout', 'всходы']]
    : op === 'harvest' ? [['ripe', 'спелое'], ['stubble', 'скошено'], ['lost', 'потеряно']]
    : op === 'spray' ? [['crop', 'не обработано'], ['sprayed', 'обработано'], ['rock', 'камень']]
    : [['weed', 'сорняк'], ['rock', 'камень'], ['tilled', 'вспахано']];
  if (unreachable) items.push(['unreachable', 'не в счёт']);
  return items;
}

function paintLegend(container, op, unreachable) {
  container.innerHTML = '';
  for (const [kind, label] of legendFor(op, unreachable)) {
    const item = node('span', 'qwfr-legend-item');
    item.append(node('i', 'qwfr-sw qwfr-sw-' + kind), node('span', '', label));
    container.append(item);
  }
}

function machineAngle(op) { return op === 'harvest' ? 0 : Math.PI; }
const FACE_ANGLE = { U: 0, R: Math.PI / 2, D: Math.PI, L: -Math.PI / 2 };
function facingAngle(dir) { return FACE_ANGLE[dir] === undefined ? Math.PI : FACE_ANGLE[dir]; }
function shortestTarget(current, target) {
  while (target - current > Math.PI) target -= Math.PI * 2;
  while (target - current < -Math.PI) target += Math.PI * 2;
  return target;
}

export function openFieldGame(opts) {
  const field = opts.field, run = opts.run;
  if (!field || !run || run.status !== 'open' || !TITLES[run.op]) {
    return { close() {}, requestClose() { return true; } };
  }
  const baseCfg = gameCfg(opts.cfg);
  const fullEconomy = Number.isInteger(run.rules) && run.rules >= 3;
  const cfg = fullEconomy
    ? { ...baseCfg, qBase: baseCfg.qBaseFull, qSpan: baseCfg.qSpanFull, qAuto: baseCfg.qAutoFull }
    : baseCfg;
  const R = new Run(field, run, cfg);
  const op = run.op;
  W = R.W;
  H = R.H;
  BAR = run.width;
  const width = run.width;
  const ha = field.ha || Math.round(H / W);
  const limit = maxPath(field, run, cfg);
  const autoSec = autoSeconds(ha, width, run.speed || opts.speed || 1, cfg);
  const openedAt = performance.now();
  const timed = run.qrule === QRULE_TIMED;
  const lim = timeLimits(ha, width, cfg);
  const elapsedNow = () => Number.isFinite(run.started_at) && typeof opts.serverNow === 'function'
    ? Math.max(0, Math.floor(opts.serverNow() - run.started_at))
    : Math.floor((performance.now() - openedAt) / 1000);
  const qNow = (score, elapsed = elapsedNow()) => {
    const base = quality(score, cfg);
    const q = R.fullRules ? finalConditionQuality(base, R.condition, cfg) : base;
    if (!timed) return q;
    const bonus = q - cfg.qAuto;
    return bonus <= 0 ? q : cfg.qAuto + Math.floor(bonus * timeKeep(elapsed, ha, width, cfg) / 1000);
  };
  /* The deadline follows the SERVER clock: performance.now() stops while a WebView is suspended, so a local deadline would outlive the run. */
  const leftSec = () => runLeftSec(run, opts.serverNow, cfg.runTtl - (performance.now() - openedAt) / 1000);
  const elapsedMs = () => Number.isFinite(run.started_at) && typeof opts.serverNow === 'function'
    ? Math.max(0, (opts.serverNow() - run.started_at) * 1000)
    : performance.now() - openedAt;
  const prev = document.activeElement;
  const inerted = [];
  const farmTheme = document.documentElement.dataset.farmTheme === 'night' ? 'night' : 'day';
  const fixedTruck = !!run.unload_zone;
  const transfer = { active: false, hold: false, progress: 0, lastSync: 0, startLoad: 0, emitted: 0 };
  const game = { R, cfg, op, width, ha, fixedTruck, transfer };
  activeGame = game;

  let closed = false;
  let sending = false;
  let raf = 0;
  let last = 0;
  let lastStep = -1e9;
  let lastMoveAt = 0;
  let lastHitAt = -1e9;
  let padDir = null;
  let held = [];
  let routeQ = [];
  let routeTarget = null;
  let swipe = null;
  let speedIdx = loadSpeed();
  let done = false;
  let confirming = false;
  let expired = false;
  let warned = false;
  let shownLeft = -1;
  let status = '';
  let statusBad = false;
  let statusTimer = 0;
  let srTimer = 0;
  let boostTimer = 0;
  let submitTimer = 0;
  let submitResolve = null;
  let sentElapsed = 0;
  let disp = { x: R.x, y: R.y };
  let particles = [];
  let cam = null;

  const root = node('div', 'field-game');
  root.dataset.theme = farmTheme;
  root.setAttribute('role', 'dialog');
  root.setAttribute('aria-modal', 'true');
  root.setAttribute('aria-label', `${TITLES[op]}, поле ${ha} га`);
  const title = TITLES[op];
  root.innerHTML = `
    <div class="qwfr-layout">
      <section class="qwfr-screen">
        <header class="qwfr-screen-top">
          <button class="qwfr-icon field-close" type="button" aria-label="Закрыть игру">×</button>
          <div class="qwfr-screen-title">
            <span class="qwfr-eyebrow">Поле ${ha} га · ширина ${width}</span>
            <strong>${title}</strong>
          </div>
          <span class="qwfr-timer" id="fwTimer" aria-label="Осталось на заход">…</span>
          <button class="qwfr-btn field-auto" id="fwAuto" type="button">Авто · ${pctText(cfg.qAuto)}</button>
        </header>
        <div class="qwfr-field" id="fwStage">
          <canvas id="fwCanvas" tabindex="0" aria-label="${title}: поле 8 на ${H}. Стрелки, WASD или свайп — ехать."></canvas>
          <div class="field-legend" id="fwMobileLegend" aria-label="Обозначения на поле"></div>
        </div>
        <div class="qwfr-console">
          <div class="qwfr-readout">
            <div class="qwfr-metric main"><span>Качество</span><strong id="fwQuality">—</strong><small>прогноз</small></div>
            <div class="qwfr-metric"><span>Охват</span><strong id="fwCoverage">0%</strong><div class="qwfr-bar"><i id="fwCoverageBar"></i></div></div>
            <div class="qwfr-metric extra"><span id="fwExtraLabel">Сорняки</span><strong id="fwExtraVal">0</strong><small id="fwExtraSub">чисто</small><div class="qwfr-bar" id="fwExtraBarWrap" hidden><i id="fwExtraBar"></i></div></div>
          </div>
          <div class="qwfr-status">
            <div class="qwfr-condition" id="fwBonusRow">
              <span>Бонус</span>
              <div class="qwfr-condbar"><i id="fwBonusBar"></i></div>
              <strong id="fwBonusPct">100%</strong>
              <small id="fwBonusSub">в срок</small>
            </div>
            <div class="qwfr-condition" id="fwDamageRow" hidden>
              <span>Состояние</span>
              <div class="qwfr-condbar"><i id="fwCondBar"></i></div>
              <strong id="fwCondPct">100%</strong>
              <small id="fwCondSub">без ремонта</small>
            </div>
          </div>
          <div class="qwfr-actions">
            <button class="qwfr-btn" id="fwUndo" type="button">Шаг назад</button>
            <button class="qwfr-btn field-speed" type="button" aria-label="Темп машины"><span>Темп</span><small id="fwSpeedVal"></small></button>
            <button class="qwfr-btn primary" id="fwFinish" type="button">Закончить</button>
          </div>
          <div class="qwfr-controls">
            <div class="qwfr-dpad" role="group" aria-label="Управление машиной">
              <button type="button" data-dir="U" aria-label="Вверх">▲</button>
              <button type="button" data-dir="T" id="fwTurn" class="qwfr-turn" aria-label="Развернуть орудие" hidden><span class="qwfr-turn-glyph" aria-hidden="true">↻</span><span class="qwfr-turn-sub" aria-hidden="true">2↔1</span></button>
              <button type="button" data-dir="L" aria-label="Влево">◀</button>
              <button type="button" data-dir="D" aria-label="Вниз">▼</button>
              <button type="button" data-dir="R" aria-label="Вправо">▶</button>
            </div>
            <div class="qwfr-side">
              <p class="qwfr-hint" id="fwHint"></p>
              <button class="qwfr-btn" id="fwUnload" type="button" hidden>Выгрузить</button>
            </div>
          </div>
        </div>
        <div class="qwfr-result" id="fwResult" hidden></div>
        <div class="qwfr-sr" id="fwLive" role="status" aria-live="polite" aria-atomic="true"></div>
      </section>
      <aside class="qwfr-journal" aria-label="Техника и обозначения">
        <div class="qwfr-journal-head"><span class="qwfr-kicker">Техника · 01—04</span><span class="qwfr-mono">ширина ${width}</span></div>
        <div class="qwfr-machines" id="fwMachines"></div>
        <div class="qwfr-note"><span class="qwfr-kicker">Подсказка</span><p id="fwNote"></p></div>
        <div class="qwfr-legend" id="fwLegend" aria-label="Обозначения на поле"></div>
        <div class="qwfr-facts"><span class="qwfr-kicker">Поле</span><dl>
          <div><dt>Размер</dt><dd>${ha} га · 8 × ${H}</dd></div>
          <div><dt>Орудие</dt><dd>${width} кл.</dd></div>
          ${op === 'harvest' ? `<div><dt>Бункер</dt><dd>${R.cap}</dd></div>` : ''}
          ${op === 'spray' ? `<div><dt>Бак</dt><dd>${Math.floor(R.tank / 2)} л</dd></div>` : ''}
          <div><dt>Камни</dt><dd>${R.rocks.size} · не в счёт</dd></div>
        </dl></div>
        <div class="qwfr-cycle" aria-hidden="true">
          <span class="${op === 'cultivate' ? 'is-now' : ''}">01 культивация</span><i>→</i>
          <span class="${op === 'sow' ? 'is-now' : ''}">02 посев</span><i>→</i>
          <span>03 рост</span><i>→</i>
          <span class="${op === 'spray' ? 'is-now' : ''}">04 обработка</span><i>→</i>
          <span class="${op === 'harvest' ? 'is-now' : ''}">05 уборка</span>
        </div>
      </aside>
    </div>`;
  document.body.append(root);
  document.body.classList.add('field-open');
  for (const el of [...document.body.children]) {
    if (el !== root && !el.inert) { el.inert = true; inerted.push(el); }
  }

  const screen = root.querySelector('.qwfr-screen');
  const eyebrow = root.querySelector('.qwfr-screen-top .qwfr-eyebrow');
  const stage = root.querySelector('#fwStage');
  const canvas = root.querySelector('#fwCanvas');
  const timer = root.querySelector('#fwTimer');
  const qualityEl = root.querySelector('#fwQuality');
  const coverageEl = root.querySelector('#fwCoverage');
  const coverageBar = root.querySelector('#fwCoverageBar');
  const extraLabel = root.querySelector('#fwExtraLabel');
  const extraVal = root.querySelector('#fwExtraVal');
  const extraSub = root.querySelector('#fwExtraSub');
  const extraBarWrap = root.querySelector('#fwExtraBarWrap');
  const extraBar = root.querySelector('#fwExtraBar');
  const bonusRow = root.querySelector('#fwBonusRow');
  const bonusBar = root.querySelector('#fwBonusBar');
  const bonusPct = root.querySelector('#fwBonusPct');
  const bonusSub = root.querySelector('#fwBonusSub');
  const damageRow = root.querySelector('#fwDamageRow');
  const condBar = root.querySelector('#fwCondBar');
  const condPct = root.querySelector('#fwCondPct');
  const condSub = root.querySelector('#fwCondSub');
  const hintEl = root.querySelector('#fwHint');
  const live = root.querySelector('#fwLive');
  const turnBtn = root.querySelector('#fwTurn');
  const unloadBtn = root.querySelector('#fwUnload');
  const undoBtn = root.querySelector('#fwUndo');
  const autoBtn = root.querySelector('#fwAuto');
  const finishBtn = root.querySelector('#fwFinish');
  const speedBtn = root.querySelector('.field-speed');
  const speedVal = root.querySelector('#fwSpeedVal');
  const closeBtn = root.querySelector('.field-close');
  const result = root.querySelector('#fwResult');
  const machinesEl = root.querySelector('#fwMachines');
  const noteEl = root.querySelector('#fwNote');
  const legendEl = root.querySelector('#fwLegend');
  const mobileLegend = root.querySelector('#fwMobileLegend');

  noteEl.textContent = HELP[op];
  const unreachableLegend = W * H > R.cells.size + R.rocks.size;
  paintLegend(legendEl, op, unreachableLegend);
  paintLegend(mobileLegend, op, unreachableLegend);
  const machineDefs = [
    ['cultivate', 'Культиватор', 'Сошники и каток'],
    ['sow', 'Сеялка', 'Сошники и маркеры'],
    ['harvest', 'Комбайн', 'Жатка и бункер'],
    ['spray', 'Опрыскиватель', 'Штанга и бак']
  ];
  for (let i = 0; i < machineDefs.length; i++) {
    const [mode, name, desc] = machineDefs[i];
    const card = node('div', 'qwfr-machine' + (mode === op ? ' is-active' : ''));
    card.setAttribute('role', 'listitem');
    if (mode === op) card.setAttribute('aria-current', 'true');
    const art = node('span', 'qwfr-machine-art');
    const thumb = node('canvas');
    thumb.dataset.thumb = mode;
    thumb.setAttribute('aria-hidden', 'true');
    art.append(thumb);
    const copy = node('span', 'qwfr-machine-copy');
    copy.append(node('span', 'qwfr-machine-index', String(i + 1).padStart(2, '0')));
    copy.append(node('strong', '', name));
    copy.append(node('small', '', desc));
    if (mode === op) copy.append(node('span', 'qwfr-machine-tag', 'в поле'));
    card.append(art, copy);
    machinesEl.append(card);
  }

  state = {
    mode: op,
    theme: farmTheme,
    ha,
    cap: R.cap,
    load: 0,
    rocks: new Set(R.rocks),
    weeds: new Set(R.weeds),
    worked: new Set(),
    doubles: new Set(),
    lost: new Set(),
    unreachable: new Set(),
    patterns: [],
    recent: new Map(),
    disp: { x: R.x, y: R.y },
    x: R.x,
    y: R.y,
    dir: 'D',
    facing: 'D',
    orient: R.orient || 'h',
    angle: R.turnRules ? facingAngle('D') : machineAngle(op),
    angleTarget: R.turnRules ? facingAngle('D') : machineAngle(op),
    cam: null,
    auto: false,
    done: false,
    tankCap: 0,
    condition: 100,
    hits: 0,
    repair: 0,
    transferActive: false,
    transferHold: false,
    transferFlashAt: 0
  };
  for (let c = 0; c < W * H; c++) {
    if (!R.cells.has(c) && !state.rocks.has(c)) state.unreachable.add(c);
  }
  buildPatterns();
  syncArt();

  /* ---- formatting / status ---- */
  function say(text, bad = false) {
    status = text;
    statusBad = bad;
    clearTimeout(statusTimer);
    statusTimer = setTimeout(() => {
      status = '';
      statusBad = false;
      sync();
    }, 4200);
    if (hintEl) {
      hintEl.textContent = text;
      hintEl.classList.toggle('is-bad', bad);
    }
  }
  function announce(text) {
    clearTimeout(srTimer);
    srTimer = setTimeout(() => {
      srTimer = 0;
      if (!closed) live.textContent = text;
    }, 900);
  }
  function displayLoad() {
    if (!transfer.active) return R.load;
    if (op === 'spray') return clamp(transfer.startLoad + (R.tank - transfer.startLoad) * transfer.progress, 0, R.tank);
    return clamp(transfer.startLoad * (1 - transfer.progress), 0, R.cap);
  }

  /* ---- art state ---- */
  function syncArt() {
    state.mode = op;
    state.theme = farmTheme;
    state.ha = ha;
    state.cap = R.cap;
    state.tankCap = R.tank || 0;
    state.condition = R.condition;
    state.hits = R.hits;
    state.repair = R.repair;
    state.load = displayLoad();
    state.worked = new Set(op === 'sow' ? R.sown : op === 'spray' ? R.sprayed : R.last.keys());
    state.doubles = new Set(op === 'spray' ? R.sprayDoubled : R.doubled);
    state.lost = new Set(R.lost);
    state.x = R.x;
    state.y = R.y;
    state.orient = R.orient || 'h';
    if (R.turnRules) {
      const lastDir = [...R.path].reverse().find(ch => 'UDLRudlr'.includes(ch));
      if (lastDir) state.facing = lastDir.toUpperCase();
      state.angleTarget = shortestTarget(state.angle, facingAngle(state.facing));
    } else {
      state.angle = state.angleTarget = machineAngle(op);
    }
    state.auto = false;
    state.done = done;
    state.transferActive = transfer.active;
    state.transferHold = transfer.hold;
  }

  /* ---- layout ---- */
  function layoutCanvas() {
    const r = stage.getBoundingClientRect();
    if (!r.width || !r.height) return;
    const dpr = Math.min(2, window.devicePixelRatio || 1, Math.sqrt(4e6 / (r.width * r.height)));
    const pw = Math.round(r.width * dpr), ph = Math.round(r.height * dpr);
    if (canvas.width !== pw) canvas.width = pw;
    if (canvas.height !== ph) canvas.height = ph;
    // E24: the field takes the whole width (the road runs 10 px past the fence), the barn roof and the road
    // above it scale with the cell, the block is centred in the stage. The legend sits in the band under the
    // field only when it costs no cell size and the field does not scroll under it; otherwise it hides.
    const side = clamp(r.width * 0.03, 12, 18);
    const air = 6;
    const rows = Math.min(H, 8);
    const barnK = Math.min(W * 0.34, 3.2) * 0.62 * 0.82;            // drawBarn: roof height above the fence, in cells
    const rise = c => Math.max(36, c * barnK);
    const cellW = Math.max(14, (r.width - side * 2) / W);
    const cellH = below => {
      const c = (r.height - air - below) / (rows + barnK);
      return Math.max(14, c * barnK >= 36 ? c : (r.height - air - below - 36) / rows);
    };
    stage.classList.remove('is-tight');
    const legendH = mobileLegend && mobileLegend.offsetParent ? (mobileLegend.offsetHeight || 0) : 0;
    const withLegend = legendH ? legendH + 8 : air + 2;
    const tight = !!legendH && (H > 8 || cellH(withLegend) < cellW - 0.5);
    stage.classList.toggle('is-tight', tight);
    const below = tight || !legendH ? air + 2 : withLegend;
    const cell = H <= 8 ? Math.min(cellW, cellH(below)) : cellW;
    const fieldW = cell * W;
    const fieldH = cell * H;
    const fieldX = (r.width - fieldW) / 2;
    const top = rise(cell);
    const spare = H <= 8 ? Math.max(0, r.height - air - below - top - fieldH) : 0;
    const fieldY = air + top + spare / 2;
    const roadH = clamp(cell * 0.55, 18, 28);
    const camMax = Math.max(0, fieldY + fieldH - (r.height - below));
    view = {
      w: r.width,
      h: r.height,
      dpr,
      field: { x: fieldX, y: fieldY, w: fieldW, h: fieldH, size: fieldW },
      cell,
      roadH,
      camMax
    };
    cam = null;
    state.cam = null;
  }

  function paintThumb(c) {
    const mode = c.dataset.thumb;
    const r = c.getBoundingClientRect();
    if (!r.width || !r.height) return;
    const dpr = Math.min(2.5, window.devicePixelRatio || 1);
    const w = Math.round(r.width * dpr), h = Math.round(r.height * dpr);
    if (c.width !== w || c.height !== h) { c.width = w; c.height = h; }
    const g = c.getContext('2d');
    if (!g) return;
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, r.width, r.height);
    const cell = Math.min(r.width * 0.27, r.height * 0.45);
    drawMachine(g, r.width / 2, r.height * 0.56, cell, mode, {
      angle: mode === 'harvest' ? 0 : Math.PI,
      implAngle: 0,
      tilt: 0
    });
  }
  function paintThumbs() { root.querySelectorAll('[data-thumb]').forEach(paintThumb); }

  /* ---- HUD ---- */
  function hintText() {
    if (done) return 'Работа закрыта.';
    if (sending) return 'Отправляем работу…';
    if (R.fullRules && R.condition <= 0) return 'Машина сломалась: заезд закроется автопилотом.';
    if (R.fullRules && R.condition < 70) return 'Машина повреждена: удары бьют по качеству и требуют ремонта.';
    if (op === 'harvest' || op === 'spray') {
      const refill = op === 'spray';
      if (transfer.active) return transfer.hold
        ? 'Перекачка ×3 — держи до конца.'
        : (refill ? 'Заправка идёт сама. Держи «Заправить» — быстрее.' : 'Выгрузка идёт сама. Держи «Выгрузить» — быстрее.');
      if (refill) {
        if (R.load >= R.tank) return 'Бак полон — работай по полю.';
        if (R.canUnload() && R.load < R.tank) return 'Цистерна рядом: бак наполнится сам.';
        if (R.y === 0 && R.load < R.tank) return 'Выровняйся под шлангом цистерны.';
        if (R.load <= 0) return 'Бак пуст — вернись к цистерне наверху.';
        return R.wind ? 'Ветер сносит распыл ' + (R.wind > 0 ? '→' : '←') + '. Следи за баком.' : 'Ветер стих. Следи за баком.';
      }
      if (R.load >= R.cap && !R.canUnload()) return 'Бункер полон — вези к грузовику наверху.';
      if (R.canUnload() && R.load > 0) return 'Грузовик рядом: выгрузка начнётся сама.';
      if (R.y === 0 && R.load > 0) return 'Выровняйся под шлангом грузовика.';
      return 'Убирай полосами. Следи за бункером.';
    }
    if (op === 'sow') {
      const lane = R.turnRules
        ? R._footCells(R.x, R.y, R.orient).some(c => R.sowable.has(c))
        : R.x % (width + 1) === 0;
      return lane ? 'Сей по светлым полосам. Камни не в счёт.' : 'Это не полоса посева.';
    }
    if (R.turnRules && R.orient === 'v') return 'Орудие развернуто: ширина 1. ↻ — обратно.';
    return 'Сорняки весят втрое. Камни не в счёт.';
  }
  function sync() {
    const narrow = window.innerWidth <= 340;
    eyebrow.textContent = narrow ? `${ha} га · ширина ${width}` : `Поле ${ha} га · ширина ${width}`;
    const q = qNow(R.score());
    qualityEl.textContent = pctText(q);
    const cov = R.coverage();
    coverageEl.textContent = roundPct(cov);
    coverageBar.style.width = clamp(cov / 10, 0, 100).toFixed(1) + '%';

    if (op === 'cultivate') {
      let left = 0;
      for (const c of R.weeds) if (!R.last.has(c)) left++;
      extraLabel.textContent = 'Сорняки';
      extraVal.textContent = String(left);
      extraSub.textContent = R.weeds.size ? 'из ' + R.weeds.size : 'чисто';
      extraVal.classList.remove('is-full');
      extraBarWrap.hidden = true;
    } else if (op === 'sow') {
      extraLabel.textContent = 'Повторы';
      extraVal.textContent = String(R.doubles);
      extraSub.textContent = R.doubles ? 'лишних' : 'чисто';
      extraVal.classList.remove('is-full');
      extraBarWrap.hidden = true;
    } else if (op === 'spray') {
      const load = displayLoad();
      const litres = Math.ceil(load / 2 - 0.001);
      const capL = Math.floor(R.tank / 2);
      const full = load >= R.tank - 0.001;
      const empty = load <= 0.001;
      extraLabel.textContent = 'Бак';
      extraVal.textContent = litres + '/' + capL;
      extraSub.textContent = transfer.active ? 'заправка' : full ? 'полон' : empty ? 'пуст' : 'литров';
      extraVal.classList.toggle('is-full', full);
      extraBarWrap.hidden = false;
      extraBar.style.width = clamp(load / Math.max(1, R.tank) * 100, 0, 100).toFixed(1) + '%';
    } else {
      const load = displayLoad();
      const full = load >= R.cap - 0.001;
      const empty = load <= 0.001;
      extraLabel.textContent = 'Бункер';
      extraVal.textContent = Math.ceil(load - 0.001) + '/' + R.cap;
      extraSub.textContent = transfer.active ? 'выгрузка' : full ? 'полон' : empty ? 'пуст' : 'клеток';
      extraVal.classList.toggle('is-full', full);
      extraBarWrap.hidden = false;
      extraBar.style.width = clamp(load / Math.max(1, R.cap) * 100, 0, 100).toFixed(1) + '%';
    }

    if (timed) {
      bonusRow.hidden = false;
      const keep = timeKeep(elapsedNow(), ha, width, cfg);
      bonusBar.style.width = clamp(keep / 10, 0, 100).toFixed(1) + '%';
      bonusPct.textContent = Math.round(keep / 10) + '%';
      bonusSub.textContent = keep >= 1000 ? 'в срок' : keep <= 0 ? 'сгорел' : 'тает';
      bonusRow.classList.toggle('is-melt', keep < 1000);
    } else {
      bonusRow.hidden = true;
    }

    if (R.fullRules) {
      damageRow.hidden = false;
      condBar.style.width = clamp(R.condition, 0, 100).toFixed(0) + '%';
      condPct.textContent = R.condition + '%';
      condSub.textContent = R.repair ? 'ремонт ' + R.repair : 'без ремонта';
      damageRow.classList.toggle('is-damaged', R.condition < 100);
    } else {
      damageRow.hidden = true;
    }

    const busy = sending || done || confirming;
    const tr = transfer.active;
    unloadBtn.hidden = op !== 'harvest' && op !== 'spray';
    if (op === 'harvest' || op === 'spray') {
      const refill = op === 'spray';
      const need = refill ? R.load < R.tank : R.load > 0;
      const can = R.canUnload() && need && !busy;
      unloadBtn.disabled = !can && !tr;
      unloadBtn.classList.toggle('is-hot', can && !tr);
      unloadBtn.classList.toggle('has-hold', can || tr);
      unloadBtn.classList.toggle('is-boosting', tr && transfer.hold);
      unloadBtn.textContent = refill ? (narrow ? 'Залить' : 'Заправить') : (narrow ? 'Выгруз.' : 'Выгрузить');
      unloadBtn.title = tr
        ? 'Удерживай для ускорения ×3'
        : !R.canUnload()
          ? (refill ? 'Подъедь к цистерне на верхнем краю' : 'Подъедь к грузовику на верхнем краю')
          : !need
            ? (refill ? 'Бак полон' : 'Бункер пуст')
            : 'Держи, чтобы ускорить перегрузку ×3';
      unloadBtn.setAttribute('aria-label', tr
        ? (refill ? 'Заправка идёт. Удерживай для ускорения втрое' : 'Выгрузка идёт. Удерживай для ускорения втрое')
        : (refill ? 'Заправить бак. Удерживай для ускорения втрое' : 'Выгрузить. Удерживай для ускорения втрое'));
    }
    undoBtn.disabled = busy || tr || !R.path.length;
    autoBtn.disabled = busy || tr;
    finishBtn.disabled = busy || tr || !R.path.length;
    undoBtn.textContent = narrow ? 'Отмена' : 'Шаг назад';
    undoBtn.title = 'Отменить последний ход';
    autoBtn.textContent = narrow ? 'Авто' : 'Авто · ' + pctText(cfg.qAuto);
    finishBtn.textContent = narrow ? 'Готово' : 'Закончить';
    finishBtn.title = 'Закончить работу';
    const autoAt = opts.timeText ? opts.timeText(autoSec) : autoSec + ' с';
    autoBtn.title = `Автопилот: качество ${pctText(cfg.qAuto)}, готово через ${autoAt}`;
    autoBtn.setAttribute('aria-label', autoBtn.title);
    speedBtn.disabled = busy || tr;
    speedBtn.title = 'Темп: ' + SPEEDS[speedIdx].label;
    if (speedVal) speedVal.textContent = SPEEDS[speedIdx].label;
    speedBtn.setAttribute('aria-label', 'Темп машины: ' + SPEEDS[speedIdx].label + '. Нажми, чтобы сменить.');
    root.querySelectorAll('.qwfr-dpad button').forEach(b => { b.disabled = sending || done || confirming; });
    turnBtn.hidden = !R.turnRules || width < 2;
    turnBtn.disabled = busy || tr || !R.canTurn();
    turnBtn.title = !R.canTurn() ? 'Здесь не развернуться' : (R.orient === 'h' ? 'Развернуть орудие: ширина ' + width + ' → 1' : 'Вернуть широкий проход: ширина 1 → ' + width);
    turnBtn.setAttribute('aria-label', turnBtn.title);
    turnBtn.querySelector('.qwfr-turn-sub').textContent = width + '↔1';
    if (hintEl) {
      hintEl.textContent = status || hintText();
      hintEl.classList.toggle('is-bad', statusBad);
    }
  }

  /* ---- transfer ---- */
  function startTransfer(hold) {
    if ((op !== 'harvest' && op !== 'spray') || sending || done || confirming || transfer.active) return;
    const refill = op === 'spray';
    if (!R.canUnload()) {
      say(refill ? 'Цистерна ждёт у верхнего края поля.' : (R.y !== 0 ? 'Грузовик ждёт у верхнего края поля.' : 'Подъедь ближе к грузовику.'), true);
      return;
    }
    if (!R.transferNeeds()) { say(refill ? 'Бак полон.' : 'Бункер пуст.', true); return; }
    if (R.path.length >= limit) { say(`Длина маршрута ограничена: ${limit} ходов. Заверши работу.`, true); return; }
    if (limit - R.path.length < R.transferSteps()) {
      say(refill ? 'В маршруте мало места: бак заправится не полностью.' : 'В маршруте мало места: выгрузится только часть.', true);
    }
    transfer.active = true;
    transfer.hold = !!hold;
    transfer.progress = 0;
    transfer.lastSync = 0;
    transfer.startLoad = R.load;
    transfer.emitted = 0;
    state.transferActive = true;
    state.transferHold = transfer.hold;
    state.load = displayLoad();
    status = '';
    syncArt();
    sync();
    announce(refill ? 'Заправка пошла' : 'Выгрузка пошла');
  }
  function stopTransfer(cancelled) {
    if (!transfer.active) return;
    const refill = op === 'spray';
    transfer.active = false;
    transfer.hold = false;
    transfer.progress = 0;
    transfer.emitted = 0;
    state.transferActive = false;
    state.transferHold = false;
    state.load = R.load;
    if (cancelled) say(refill ? 'Заправка прервана.' : 'Выгрузка прервана.', true);
    syncArt();
    sync();
  }
  function finishTransfer(now) {
    const refill = op === 'spray';
    transfer.active = false;
    transfer.hold = false;
    transfer.progress = 0;
    transfer.emitted = 0;
    state.transferActive = false;
    state.transferHold = false;
    state.transferFlashAt = now;
    state.load = R.load;
    spawnBurst(refill);
    say(refill ? 'Бак заправлен.' : 'Бункер выгружен.');
    syncArt();
    sync();
    announce(refill ? 'Бак заправлен' : 'Бункер выгружен');
  }
  function updateTransfer(dt, now) {
    if (!transfer.active) return;
    if (sending || done || confirming || !R.canUnload()) { stopTransfer(true); return; }
    if (!R.transferNeeds()) { finishTransfer(now); return; }
    const refill = op === 'spray';
    const rate = transfer.hold ? 3 : 1;
    transfer.progress = Math.min(1, transfer.progress + dt / 2.4 * rate);
    state.load = displayLoad();
    state.transferHold = transfer.hold;
    state.transferActive = true;
    const chunks = cfg.tankChunks || 4;
    const due = Math.min(chunks, Math.floor(transfer.progress * chunks + 1e-9));
    while (transfer.emitted < due && R.transferNeeds()) {
      if (R.path.length >= limit) {
        stopTransfer(false);
        say(`Длина маршрута ограничена: ${limit} ходов. Заверши работу.`, true);
        return;
      }
      if (!R.push('X')) {
        stopTransfer(true);
        say(refill ? 'Не удалось заправить. Попробуй ещё раз.' : 'Не удалось выгрузить. Попробуй ещё раз.', true);
        return;
      }
      transfer.emitted++;
    }
    if (transfer.progress >= 1) { finishTransfer(now); return; }
    if (now - transfer.lastSync > 90) {
      transfer.lastSync = now;
      syncArt();
      sync();
    }
  }
  function maybeAutoTransfer(now) {
    if ((op !== 'harvest' && op !== 'spray') || transfer.active || sending || done || confirming) return;
    if (!R.canUnload() || !R.transferNeeds()) return;
    if (limit - R.path.length < R.transferSteps()) return;
    if (padDir || held.length || routeQ.length) return;
    if (now - lastMoveAt < 260) return;
    startTransfer(false);
  }

  /* ---- particles ---- */
  function spawnDust(dir) {
    if (reduced()) return;
    const cx = view.field.x + (R.x + BAR / 2) * view.cell;
    const cy = view.field.y + (R.y + 0.5) * view.cell;
    let vx = 0, vy = 0;
    if (dir === 'U') vy = 18; else if (dir === 'D') vy = -18; else if (dir === 'L') vx = 18; else vx = -18;
    for (let i = 0; i < 4; i++) {
      particles.push({
        x: cx + (Math.random() - 0.5) * BAR * view.cell * 0.8,
        y: cy + (Math.random() - 0.5) * view.cell * 0.4,
        vx: vx + (Math.random() - 0.5) * 12,
        vy: vy + (Math.random() - 0.5) * 12,
        life: 0.5, max: 0.5, size: 2 + Math.random() * 2.4,
        color: PALETTE[state.theme].dust, gravity: 0
      });
    }
  }
  function spawnBurst(refill) {
    if (reduced()) return;
    const o = supplyOutlet();
    const p = PALETTE[state.theme];
    for (let i = 0; i < 14; i++) {
      particles.push({
        x: o.x + (Math.random() - 0.5) * view.cell * 0.5,
        y: o.y + (Math.random() - 0.5) * 5,
        vx: (Math.random() - 0.5) * 28,
        vy: -8 - Math.random() * 22,
        life: 0.65, max: 0.65, size: 1.5 + Math.random() * 2.8,
        color: refill ? p.sprayDew : p.grain, gravity: 90
      });
    }
  }
  function updateParticles(dt) {
    for (const p of particles) {
      p.life -= dt;
      p.x += p.vx * dt;
      p.y += p.vy * dt;
      p.vy += (p.gravity || 0) * dt;
    }
    particles = particles.filter(p => p.life > 0);
  }
  function drawParticles(g) {
    for (const p of particles) {
      g.fillStyle = p.color;
      g.globalAlpha = Math.max(0, p.life / p.max) * 0.85;
      g.beginPath();
      g.arc(p.x, p.y, p.size, 0, TAU);
      g.fill();
    }
    g.globalAlpha = 1;
  }

  /* ---- rendering ---- */
  function drawDock(g, f, cell, p, now) {
    if ((op !== 'harvest' && op !== 'spray') || !fixedTruck) return;
    const cx = f.x + f.w * SUPPLY_FRAC;
    const half = (cfg.unloadHalf / 100) * cell;
    const zone = R.canUnload();
    const top = f.y + cell * 0.05;
    const accent = op === 'spray' ? p.sprayDew : p.ripeLight;
    g.save();
    g.lineCap = 'round';
    g.strokeStyle = p.cream;
    g.globalAlpha = zone ? 0.9 : 0.3;
    g.lineWidth = Math.max(1.1, cell * 0.032);
    g.beginPath();
    g.moveTo(cx - half, top + cell * 0.18);
    g.lineTo(cx - half, top);
    g.lineTo(cx + half, top);
    g.lineTo(cx + half, top + cell * 0.18);
    g.stroke();
    g.strokeStyle = accent;
    g.globalAlpha = zone ? 0.75 : 0.28;
    g.lineWidth = Math.max(1.4, cell * 0.04);
    g.setLineDash([cell * 0.09, cell * 0.08]);
    g.beginPath();
    g.moveTo(cx - half * 0.82, top + cell * 0.025);
    g.lineTo(cx + half * 0.82, top + cell * 0.025);
    g.stroke();
    g.setLineDash([]);
    g.globalAlpha = 1;
    g.fillStyle = p.cream;
    g.strokeStyle = p.machineDark;
    g.lineWidth = Math.max(1, cell * 0.024);
    g.beginPath();
    g.arc(cx, top + cell * 0.11, Math.max(2.2, cell * 0.065), 0, TAU);
    g.fill();
    g.stroke();
    g.fillStyle = accent;
    g.beginPath();
    g.arc(cx, top + cell * 0.11, Math.max(0.9, cell * 0.025), 0, TAU);
    g.fill();
    g.restore();
  }
  function drawFootprint(g, f, cell, p) {
    const fp = footSize(state.orient);
    const x = f.x + disp.x * cell;
    const y = f.y + disp.y * cell;
    g.save();
    g.fillStyle = rgba(p.cream, 0.07);
    rrect(g, x + 2, y + 2, fp.w * cell - 4, fp.h * cell - 4, Math.max(3, cell * 0.1));
    g.fill();
    g.strokeStyle = rgba(p.cream, 0.5);
    g.lineWidth = Math.max(1, cell * 0.03);
    g.setLineDash([cell * 0.1, cell * 0.1]);
    rrect(g, x + 2, y + 2, fp.w * cell - 4, fp.h * cell - 4, Math.max(3, cell * 0.1));
    g.stroke();
    g.setLineDash([]);
    g.restore();
  }
  function drawNextSwath(g, f, cell, p) {
    if (done || sending || transfer.active) return;
    const fp = footSize(state.orient);
    const next = R.turnRules
      ? stepAnchorOrient(R.x, R.y, state.dir, W, H, BAR, new Set(R.rocks), state.orient)
      : stepAnchor(R.x, R.y, state.dir, W, H, BAR, new Set(R.rocks));
    if (!next) return;
    const [nx, ny] = next;
    const x = f.x + nx * cell;
    const y = f.y + ny * cell;
    const w = fp.w * cell;
    const h = fp.h * cell;
    g.save();
    g.fillStyle = rgba(p.ripe, 0.18);
    rrect(g, x + cell * 0.04, y + cell * 0.04, w - cell * 0.08, h - cell * 0.08, Math.max(2, cell * 0.08));
    g.fill();
    g.strokeStyle = p.ripe;
    g.lineWidth = Math.max(1.3, cell * 0.032);
    g.setLineDash([cell * 0.16, cell * 0.12]);
    rrect(g, x + cell * 0.04, y + cell * 0.04, w - cell * 0.08, h - cell * 0.08, Math.max(2, cell * 0.08));
    g.stroke();
    g.setLineDash([]);
    const sx = f.x + (R.x + fp.w / 2) * cell;
    const sy = f.y + (R.y + fp.h / 2) * cell;
    const ex = x + w / 2;
    const ey = y + h / 2;
    const dx = ex - sx, dy = ey - sy, len = Math.hypot(dx, dy);
    if (len > 1) {
      const ux = dx / len, uy = dy / len;
      const ax = sx + ux * cell * 0.42, ay = sy + uy * cell * 0.42;
      const bx = ex - ux * cell * 0.18, by = ey - uy * cell * 0.18;
      g.strokeStyle = p.machineDark;
      g.lineWidth = Math.max(1.4, cell * 0.038);
      g.beginPath();
      g.moveTo(ax, ay);
      g.lineTo(bx, by);
      g.stroke();
      const h = cell * 0.15;
      g.fillStyle = p.machineDark;
      g.beginPath();
      g.moveTo(bx, by);
      g.lineTo(bx - ux * h - uy * h * 0.6, by - uy * h + ux * h * 0.6);
      g.lineTo(bx - ux * h + uy * h * 0.6, by - uy * h - ux * h * 0.6);
      g.closePath();
      g.fill();
    }
    g.restore();
  }
  function render(now) {
    if (!view || !state || !view.cell) return;
    const f = view.field;
    const cell = view.cell;
    const p = PALETTE[state.theme];
    const dpr = view.dpr;
    const g = canvas.getContext('2d');
    if (!g) return;
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, view.w, view.h);
    const bg = g.createLinearGradient(0, 0, 0, view.h);
    bg.addColorStop(0, p.stage2);
    bg.addColorStop(1, p.stage);
    g.fillStyle = bg;
    g.fillRect(0, 0, view.w, view.h);

    const fp = footSize(state.orient);
    const wantCam = clamp(f.y + (disp.y + fp.h / 2) * cell - view.h / 2, 0, view.camMax || 0);
    if (cam === null) cam = wantCam;
    else cam += (wantCam - cam) * (reduced() ? 1 : 0.16);
    cam = clamp(cam, 0, view.camMax || 0);
    state.cam = cam;

    g.save();
    g.translate(0, -cam);
    drawScenery(g, f, cell, p);
    drawRoad(g, f, cell, p);
    drawBarn(g, f, cell, p);
    if (op === 'harvest') drawTruck(g, f, cell, p);
    else if (op === 'spray') drawTanker(g, f, cell, p);
    g.fillStyle = rgba('#1f2b22', 0.12);
    rrect(g, f.x + 1, f.y + 5, f.w, f.h, Math.max(3, cell * 0.08));
    g.fill();
    drawFence(g, f, cell, p, false);
    drawField(g, f, cell, p, now);
    drawDock(g, f, cell, p, now);
    drawFootprint(g, f, cell, p);
    drawNextSwath(g, f, cell, p);
    drawParticles(g);
    const mcx = f.x + (disp.x + fp.w / 2) * cell;
    const mcy = f.y + (disp.y + fp.h / 2) * cell;
    drawMachine(g, mcx, mcy, cell, op, {
      tilt: 0,
      angle: state.angle,
      implAngle: state.orient === 'v' ? Math.PI / 2 : 0
    });
    if (op === 'harvest' || op === 'spray') {
      drawTransferRig(g, f, cell, p, now, mcx, mcy);
      drawTransferBadge(g, f, cell, p, now);
      drawTransferFlash(g, cell, p, now, mcx, mcy);
    }
    g.restore();
    drawMinimap(g, p, cell);
  }

  /* ---- movement / undo ---- */
  function bump() {
    stage.classList.remove('is-bumped');
    void stage.offsetWidth;
    stage.classList.add('is-bumped');
    setTimeout(() => stage.classList.remove('is-bumped'), 240);
    try { navigator.vibrate?.(15); } catch {}
    say('Туда не проехать.', true);
  }
  function turn() {
    if (sending || done || confirming || transfer.active) return;
    if (!R.turnRules || R.width < 2) return;
    if (!R.canTurn()) {
      bump();
      say('Здесь не развернуться.', true);
      return;
    }
    if (R.path.length >= limit) {
      say(`Длина маршрута ограничена: ${limit} ходов. Заверши работу.`, true);
      return;
    }
    if (!R.push('T')) { bump(); return; }
    lastMoveAt = performance.now();
    state.orient = R.orient;
    status = '';
    statusBad = false;
    syncArt();
    sync();
    announce(R.orient === 'v' ? 'Орудие развернуто: ширина 1' : 'Орудие снова шириной ' + R.width);
  }
  /* fresh = a new key press / pad press / swipe segment. Auto-repeat of a held direction (frame loop, route queue) never hits an obstacle again. */
  function move(dir, fresh = false) {
    if (sending || done || confirming) return false;
    if (transfer.active) stopTransfer(true);
    if (R.path.length >= limit) {
      if (fresh) say(`Длина маршрута ограничена: ${limit} ходов. Заверши работу.`, true);
      return false;
    }
    const ok = R.push(dir);
    if (!ok) {
      const now = performance.now();
      state.dir = dir;
      state.facing = dir;
      if (R.turnRules) state.angleTarget = shortestTarget(state.angle, facingAngle(dir));
      if (!fresh) return false;
      if (R.fullRules && now - lastHitAt > 450 && R.push(dir.toLowerCase())) {
        lastHitAt = now;
        bump();
        if (R.condition <= 0) {
          say('Машина сломалась — заезд закроется автопилотом.', true);
          syncArt();
          sync();
          setTimeout(() => {
            if (closed || done || sending) return;
            if (transfer.active) stopTransfer(false);
            submit(R.path);
          }, 420);
          return false;
        }
        say(`Удар: состояние ${R.condition}% · ремонт ${R.repair}`, true);
        syncArt();
        sync();
        return false;
      }
      bump();
      return false;
    }
    state.dir = dir;
    state.x = R.x;
    state.y = R.y;
    state.facing = dir;
    if (R.turnRules) state.angleTarget = shortestTarget(state.angle, facingAngle(dir));
    lastMoveAt = performance.now();
    const stamp = lastMoveAt;
    const rf = footSize(R.orient);
    for (let dy = 0; dy < rf.h; dy++) for (let dx = 0; dx < rf.w; dx++) state.recent.set(key(R.x + dx, R.y + dy), stamp);
    status = '';
    statusBad = false;
    spawnDust(dir);
    syncArt();
    sync();
    return true;
  }
  function undo() {
    if (sending || done || confirming || transfer.active || !R.path.length) return;
    R.undo();
    state.recent.clear();
    status = '';
    statusBad = false;
    syncArt();
    sync();
  }
  function planRoute(cellX, cellY) {
    if (sending || done || confirming) return;
    if (transfer.active) stopTransfer(true);
    const fp = footSize(R.orient);
    const tx = Math.min(cellX, W - fp.w), ty = Math.min(cellY, H - fp.h);
    if (cellX < 0 || cellX >= W || cellY < 0 || cellY >= H || (tx === R.x && ty === R.y)) return;
    const keyOf = (x, y) => y * W + x;
    const prev = new Map([[keyOf(R.x, R.y), null]]);
    const todo = [[R.x, R.y]];
    for (let i = 0; i < todo.length && !prev.has(keyOf(tx, ty)); i++) {
      const [x, y] = todo[i];
      for (const ch of 'UDLR') {
        const n = R.turnRules ? stepAnchorOrient(x, y, ch, W, H, BAR, R.rocks, R.orient) : stepAnchor(x, y, ch, W, H, BAR, R.rocks);
        if (n && !prev.has(keyOf(n[0], n[1]))) {
          prev.set(keyOf(n[0], n[1]), [keyOf(x, y), ch]);
          todo.push(n);
        }
      }
    }
    if (!prev.has(keyOf(tx, ty))) { say('Туда не добраться.', true); return; }
    const chars = [];
    for (let k = keyOf(tx, ty); prev.get(k); k = prev.get(k)[0]) chars.push(prev.get(k)[1]);
    chars.reverse();
    if (R.path.length + chars.length > limit) { say(`Маршрут не поместится в лимит ${limit} ходов.`, true); return; }
    routeQ = chars;
    routeTarget = [tx, ty];
    status = '';
    statusBad = false;
    sync();
  }

  /* ---- submission / result ---- */
  async function submit(path) {
    if (sending || done || confirming || transfer.active) return;
    if (path !== null && !R.path.length) return;
    sending = true;
    routeQ = [];
    routeTarget = null;
    padDir = null;
    status = '';
    statusBad = false;
    sync();
    if (path !== null) {
      const need = (cfg.stepCs / 100 * path.length + 2) * 1000 - elapsedMs();
      if (need > 0) {
        say(`Сдаём работу… ещё ${Math.ceil(need / 1000)} с`);
        await new Promise(resolve => {
          submitResolve = resolve;
          submitTimer = setTimeout(() => { submitTimer = 0; submitResolve = null; resolve(); }, need);
        });
      }
    }
    if (closed || done) return;
    sentElapsed = elapsedNow();
    let ok = false;
    try { ok = await opts.onFinish(path); } catch { ok = false; }
    sending = false;
    if (closed || done) return;
    if (!ok) {
      const f = opts.fieldNow?.();
      if (leftSec() <= 1.5 || (f && (!f.run || f.run.id !== run.id || f.run.status !== 'open'))) {
        if (leftSec() <= 1.5) { expire(); return; }
        done = true;
        sync();
        showNote('Заход уже закрыт', 'Эта работа уже закончена или закрыта на сервере. Закрой игру и обнови раздел «Поля».');
        return;
      }
      say('Не получилось отправить работу. Попробуй ещё раз или выбери автопилот.', true);
      sync();
      return;
    }
    done = true;
    sync();
    showResult(path);
  }

  function resultPaper() {
    const paper = node('div', 'qwfr-paper');
    return paper;
  }
  function resultRow(dt, dd) {
    const row = node('div');
    row.append(node('dt', '', dt), node('dd', '', dd));
    return row;
  }
  function showNote(head, text) {
    const paper = resultPaper();
    paper.append(node('span', 'qwfr-stamp', 'ПОЛЕ'));
    paper.append(node('h2', '', head), node('p', 'field-result-note', text));
    const actions = node('div', 'qwfr-result-actions');
    const ok = btn('Закрыть', 'qwfr-btn primary', () => finishClose());
    actions.append(ok);
    paper.append(actions);
    result.className = 'qwfr-result field-confirm';
    result.innerHTML = '';
    result.append(paper);
    result.hidden = false;
    ok.focus({ preventScroll: true });
  }
  function showResult(path) {
    const f = opts.fieldNow?.();
    const exact = f && !f.run && Number.isInteger(f.last_q) ? f.last_q : null;
    const score = R.score();
    const broken = R.fullRules && R.condition <= 0;
    const q = broken ? cfg.qAuto : path === null ? cfg.qAuto : (exact ?? qNow(score, sentElapsed));
    const baseForTime = R.fullRules ? finalConditionQuality(quality(score, cfg), R.condition, cfg) : quality(score, cfg);
    const lostTime = path !== null && !broken && timed && q < baseForTime;
    const paper = resultPaper();
    paper.append(node('span', 'qwfr-stamp', 'ПРИНЯТО'));
    paper.append(node('span', 'qwfr-eyebrow', `Поле ${ha} га · ${farmTheme === 'night' ? 'ночь' : 'утро'}`));
    paper.append(node('span', 'qwfr-result-method', broken ? 'поломка · ' + pctText(cfg.qAuto) : path === null ? 'автопилот · ' + pctText(cfg.qAuto) : 'вручную'));
    paper.append(node('h2', '', path === null ? 'Автопилот взялся за работу' : 'Работа принята'));
    const list = node('dl', 'qwfr-result-list');
    list.append(resultRow('Качество', pctText(q)));
    if (R.fullRules) {
      const stars = broken ? 0 : path === null ? (q >= 950 ? 1 : 0)
        : q >= 1150 && R.hits === 0 ? 3 : q >= 1050 && R.hits <= 1 ? 2 : q >= 950 ? 1 : 0;
      list.append(resultRow('Оценка', '★'.repeat(stars) + '☆'.repeat(3 - stars)));
    }
    if (path === null) {
      list.append(resultRow('Поле', `${ha} га`));
      list.append(resultRow('Готово через', opts.timeText ? opts.timeText(autoSec) : autoSec + ' с'));
      if (op === 'spray') {
        const bonus = sprayBonus(cfg.qAuto, cfg);
        list.append(resultRow('Прибавка', '+' + ((bonus - 1000) / 10).toFixed(1).replace('.', ',') + '% к урожаю'));
      }
    } else {
      list.append(resultRow('Охват', roundPct(R.coverage())));
      if (op === 'cultivate') {
        const growth = growthPermille(q);
        const diff = Math.abs(1000 - growth) / 10;
        const value = diff < 0.05 ? '0%' : (growth <= 1000 ? '−' : '+') + diff.toFixed(1).replace('.', ',') + '%';
        list.append(resultRow('Время роста', value));
      } else if (op === 'sow') {
        list.append(resultRow('Урожай', '×' + (q / 1000).toFixed(2).replace('.', ',')));
      } else if (op === 'spray') {
        const bonus = sprayBonus(q, cfg);
        list.append(resultRow('Прибавка', '+' + ((bonus - 1000) / 10).toFixed(1).replace('.', ',') + '% к урожаю'));
      } else {
        const crop = opts.cropSnapshot;
        const spray = crop ? sprayBonus(crop.q_spray, cfg) : 1000;
        const qty = crop ? yieldQty(crop.base, crop.q_sow, q, spray) : 0;
        list.append(resultRow('Сбор', crop ? `${opts.itemName?.(crop.id) || crop.id} ×${qty}` : `${qty} шт.`));
        if (crop && crop.q_spray) list.append(resultRow('Обработка', '+' + ((spray - 1000) / 10).toFixed(1).replace('.', ',') + '%'));
      }
      if (op === 'harvest' && R.lost.size) list.append(resultRow('Потери', `${R.lost.size} клеток`));
      if (R.fullRules && (R.hits || R.condition < 100)) list.append(resultRow('Повреждения', `${R.hits} · ремонт ${R.repair}`));
      if (R.rocks.size) list.append(resultRow('Камни', `${R.rocks.size} · не в счёт`));
      list.append(resultRow('Автопилот', pctText(cfg.qAuto)));
      const advantage = q - cfg.qAuto;
      list.append(resultRow('Выгода', `${advantage >= 0 ? '+' : '−'}${Math.abs(advantage / 10).toFixed(1).replace('.', ',')}%`));
      const minutes = Math.max(1, Math.round(sentElapsed / 60));
      list.append(resultRow('Время', `${minutes} мин`));
    }
    paper.append(list);
    if (path === null) {
      paper.append(node('p', 'field-result-note', `Качество ${pctText(cfg.qAuto)}. Поле доделается само за ${opts.timeText ? opts.timeText(autoSec) : autoSec + ' с'}.`));
    } else if (exact === null) {
      paper.append(node('p', 'field-result-note', 'Число ориентировочное: точное качество посчитает сервер.'));
    }
    if (broken) paper.append(node('p', 'field-result-note', 'Машина сломалась: остаток заезда закрыт автопилотом, ремонт уже в результате.'));
    if (lostTime) paper.append(node('p', 'field-result-note', `Время съело часть бонуса. В срок (до ${mmss(lim.full)}) было бы ${pctText(baseForTime)}.`));
    if (path !== null && !broken && q >= cfg.qAuto && !lostTime) paper.append(node('p', 'field-result-note', 'Своими руками — бонус к автопилоту сохранён.'));
    const actions = node('div', 'qwfr-result-actions');
    const ok = btn('Готово', 'qwfr-btn primary', () => finishClose());
    actions.append(ok);
    paper.append(actions);
    result.className = 'qwfr-result';
    result.innerHTML = '';
    result.append(paper);
    result.hidden = false;
    announce(path === null ? 'Автопилот взялся за работу' : 'Работа принята');
    setTimeout(() => { try { ok.focus({ preventScroll: true }); } catch {} }, 50);
  }
  function expire() {
    if (closed || done || expired) return;
    expired = true;
    done = true;
    sending = false;
    padDir = null;
    held = [];
    routeQ = [];
    if (submitTimer) clearTimeout(submitTimer);
    submitTimer = 0;
    const resolve = submitResolve;
    submitResolve = null;
    resolve?.();
    stopTransfer(false);
    sync();
    showNote('Время вышло', `Срок заезда истёк. Поле доделает автопилот с качеством ${pctText(cfg.qAuto)} — закрой игру и загляни в раздел «Поля».`);
  }

  /* ---- close / navigation ---- */
  function requestClose() {
    if (closed) return;
    if (done || !R.path.length) { finishClose(); return; }
    if (confirming) return;
    if (transfer.active) stopTransfer(false);
    confirming = true;
    padDir = null;
    held = [];
    routeQ = [];
    routeTarget = null;
    const paper = resultPaper();
    paper.append(node('h2', '', 'Выйти из игры?'));
    paper.append(node('p', 'field-result-note', 'Проложенный маршрут пропадёт. Заход останется открытым до конца срока — потом поле доделает автопилот.'));
    const actions = node('div', 'qwfr-result-actions');
    const stay = btn('Продолжить', 'qwfr-btn primary', () => cancelClose());
    const leave = btn('Выйти', 'qwfr-btn is-danger', () => finishClose());
    actions.append(stay, leave);
    paper.append(actions);
    result.className = 'qwfr-result field-confirm';
    result.innerHTML = '';
    result.append(paper);
    result.hidden = false;
    stay.focus({ preventScroll: true });
  }
  /* Autopilot is never one tap away: manual work pays much better, an accidental tap would eat it. */
  function confirmAuto() {
    if (closed || sending || done || confirming || transfer.active) return;
    confirming = true;
    padDir = null;
    held = [];
    routeQ = [];
    routeTarget = null;
    const paper = resultPaper();
    paper.append(node('h2', '', 'Отдать поле автопилоту?'));
    paper.append(node('p', 'field-result-note', `Качество будет ${pctText(cfg.qAuto)}, ручной бонус потеряется. Поле доделается само за ${opts.timeText ? opts.timeText(autoSec) : autoSec + ' с'}.`));
    const actions = node('div', 'qwfr-result-actions');
    const stay = btn('Нет, поведу сам', 'qwfr-btn primary', () => cancelClose());
    const go = btn('Да, автопилот', 'qwfr-btn is-danger', () => {
      cancelClose();
      submit(null);
    });
    stay.id = 'fwAutoNo';
    go.id = 'fwAutoYes';
    actions.append(stay, go);
    paper.append(actions);
    result.className = 'qwfr-result field-confirm';
    result.innerHTML = '';
    result.append(paper);
    result.hidden = false;
    sync();
    stay.focus({ preventScroll: true });
  }
  function cancelClose() {
    if (!confirming) return;
    confirming = false;
    result.hidden = true;
    result.innerHTML = '';
    sync();
    canvas.focus({ preventScroll: true });
  }
  function backClose() {
    if (closed) return true;
    if (confirming) { cancelClose(); return false; }
    requestClose();
    return closed;
  }
  function finishClose() {
    if (closed) return;
    closed = true;
    cancelAnimationFrame(raf);
    raf = 0;
    if (submitTimer) clearTimeout(submitTimer);
    submitTimer = 0;
    const resolve = submitResolve;
    submitResolve = null;
    resolve?.();
    clearTimeout(statusTimer);
    clearTimeout(srTimer);
    clearTimeout(boostTimer);
    statusTimer = srTimer = boostTimer = 0;
    for (const el of inerted) el.inert = false;
    inerted.length = 0;
    window.removeEventListener('keydown', onKey, true);
    window.removeEventListener('keyup', onKeyUp, true);
    window.removeEventListener('resize', layoutAndPaint);
    window.removeEventListener('blur', onBlur);
    resizeObs?.disconnect();
    canvas.width = 0;
    canvas.height = 0;
    root.remove();
    document.body.classList.remove('field-open');
    activeGame = null;
    state = null;
    try { prev?.focus?.(); } catch {}
    opts.onClose?.();
  }

  /* ---- input ---- */
  function trapTab(e) {
    const scope = !result.hidden ? result : root;
    const items = [...scope.querySelectorAll('button:not(:disabled),canvas')].filter(el => !el.hidden && el.offsetParent !== null);
    if (!items.length) return;
    const i = items.indexOf(document.activeElement);
    const n = e.shiftKey ? (i <= 0 ? items.length - 1 : i - 1) : (i < 0 || i >= items.length - 1 ? 0 : i + 1);
    e.preventDefault();
    e.stopPropagation();
    items[n].focus();
  }
  function onKey(e) {
    if (closed || e.ctrlKey || e.metaKey || e.altKey) return;
    if (e.code === 'Tab') { trapTab(e); return; }
    if (e.code === 'Escape') {
      e.preventDefault();
      e.stopPropagation();
      if (confirming) cancelClose();
      else if (result.hidden) requestClose();
      else finishClose();
      return;
    }
    if (confirming || done) return;
    if (KEYS[e.code]) {
      e.preventDefault();
      e.stopPropagation();
      if (!e.repeat) {
        const dir = KEYS[e.code];
        const i = held.indexOf(dir);
        if (i >= 0) held.splice(i, 1);
        held.push(dir);
        move(dir, true);
        lastStep = performance.now();
      }
      return;
    }
    if (e.code === 'KeyX' && (op === 'harvest' || op === 'spray')) {
      e.preventDefault();
      e.stopPropagation();
      if (e.repeat) return;
      if (transfer.active) { transfer.hold = true; state.transferHold = true; sync(); }
      else startTransfer(true);
      return;
    }
    if (e.code === 'KeyQ') {
      e.preventDefault();
      e.stopPropagation();
      if (!e.repeat) turn();
      return;
    }
    if (e.code === 'Backspace' || e.code === 'KeyZ') {
      e.preventDefault();
      e.stopPropagation();
      if (!e.repeat) undo();
    }
  }
  function onKeyUp(e) {
    if (KEYS[e.code]) {
      const i = held.indexOf(KEYS[e.code]);
      if (i >= 0) held.splice(i, 1);
    }
    if (e.code === 'KeyX' && transfer.active) {
      transfer.hold = false;
      state.transferHold = false;
      sync();
    }
  }
  function onBlur() {
    held = [];
    padDir = null;
    transfer.hold = false;
    state.transferHold = false;
  }
  window.addEventListener('keydown', onKey, true);
  window.addEventListener('keyup', onKeyUp, true);
  window.addEventListener('blur', onBlur);
  window.addEventListener('resize', layoutAndPaint);

  root.querySelectorAll('.qwfr-dpad button').forEach(b => {
    const dir = b.dataset.dir;
    if (dir === 'T') {
      b.addEventListener('click', turn);
      return;
    }
    b.addEventListener('pointerdown', e => {
      if (sending || done || confirming) return;
      e.preventDefault();
      if (transfer.active) stopTransfer(true);
      padDir = dir;
      move(dir, true);
      lastStep = performance.now();
      try { b.setPointerCapture(e.pointerId); } catch {}
    });
    const stop = () => { if (padDir === dir) padDir = null; };
    b.addEventListener('pointerup', stop);
    b.addEventListener('pointercancel', stop);
    b.addEventListener('lostpointercapture', stop);
    b.addEventListener('click', e => { if (e.detail === 0 && !done && !confirming) move(dir, true); });
  });

  canvas.addEventListener('pointerdown', e => {
    if (sending || done || confirming) return;
    swipe = { x: e.clientX, y: e.clientY, moved: false };
    try { canvas.setPointerCapture(e.pointerId); } catch {}
    try { canvas.focus({ preventScroll: true }); } catch {}
  });
  canvas.addEventListener('pointermove', e => {
    if (!swipe) return;
    const dx = e.clientX - swipe.x;
    const dy = e.clientY - swipe.y;
    if (Math.max(Math.abs(dx), Math.abs(dy)) >= 22) {
      const dir = Math.abs(dx) > Math.abs(dy) ? (dx > 0 ? 'R' : 'L') : (dy > 0 ? 'D' : 'U');
      swipe.x = e.clientX;
      swipe.y = e.clientY;
      swipe.moved = true;
      const again = swipe.blockedDir === dir;
      if (!move(dir, !again)) swipe.blockedDir = dir; else swipe.blockedDir = null;
      lastStep = performance.now();
    }
  });
  const endSwipe = e => {
    if (swipe && !swipe.moved && !sending && !done && !confirming && e?.type === 'pointerup') {
      const r = canvas.getBoundingClientRect();
      planRoute(
        Math.floor((e.clientX - r.left - view.field.x) / view.cell),
        Math.floor((e.clientY - r.top) / view.cell + cam)
      );
    }
    swipe = null;
  };
  canvas.addEventListener('pointerup', endSwipe);
  canvas.addEventListener('pointercancel', endSwipe);

  closeBtn.addEventListener('click', requestClose);
  speedBtn.addEventListener('click', () => {
    if (sending || done || confirming || transfer.active) return;
    speedIdx = (speedIdx + 1) % SPEEDS.length;
    saveSpeed(speedIdx);
    sync();
    announce('Темп: ' + SPEEDS[speedIdx].label);
  });
  undoBtn.addEventListener('click', undo);
  autoBtn.addEventListener('click', confirmAuto);
  finishBtn.addEventListener('click', () => submit(R.path));
  unloadBtn.addEventListener('pointerdown', e => {
    if (unloadBtn.disabled && !transfer.active) return;
    e.preventDefault();
    clearTimeout(boostTimer);
    if (transfer.active) {
      transfer.hold = true;
      state.transferHold = true;
      sync();
    } else {
      startTransfer(true);
    }
    try { unloadBtn.setPointerCapture(e.pointerId); } catch {}
  });
  const stopBoost = () => {
    clearTimeout(boostTimer);
    if (!transfer.active) return;
    transfer.hold = false;
    state.transferHold = false;
    sync();
  };
  unloadBtn.addEventListener('pointerup', stopBoost);
  unloadBtn.addEventListener('pointercancel', stopBoost);
  unloadBtn.addEventListener('lostpointercapture', stopBoost);
  unloadBtn.addEventListener('click', e => {
    if (e.detail !== 0 || unloadBtn.disabled) return;
    clearTimeout(boostTimer);
    if (!transfer.active) startTransfer(true);
    else { transfer.hold = true; state.transferHold = true; sync(); }
    boostTimer = setTimeout(() => {
      boostTimer = 0;
      if (transfer.active) {
        transfer.hold = false;
        state.transferHold = false;
        sync();
      }
    }, 1100);
  });

  function layoutAndPaint() {
    layoutCanvas();
    paintThumbs();
    if (!closed) render(performance.now());
  }
  const resizeObs = typeof ResizeObserver === 'function'
    ? new ResizeObserver(() => { if (!closed) layoutAndPaint(); })
    : null;
  resizeObs?.observe(stage);
  root.querySelectorAll('[data-thumb]').forEach(c => resizeObs?.observe(c));

  /* ---- main loop ---- */
  function updateTimer(now) {
    const left = Math.max(0, leftSec());
    const shown = Math.ceil(left);
    if (shown !== shownLeft) {
      shownLeft = shown;
      timer.textContent = mmss(left);
      timer.setAttribute('aria-label', `Осталось на заход ${mmss(left)}`);
      timer.classList.toggle('is-warn', left <= 60 && !done);
      if (timed) sync();
      if (!warned && left <= 60 && left > 0 && !done) {
        warned = true;
        say('Осталась минута: заверши работу, иначе поле доделает автопилот.', true);
        announce('Осталась минута');
      }
    }
    if (left <= 0 && !done && !expired) expire();
  }
  function frame(now) {
    if (closed) return;
    const dt = Math.min(0.05, (now - (last || now)) / 1000);
    last = now;
    updateTimer(now);
    if (!done && !confirming) {
      updateTransfer(dt, now);
      maybeAutoTransfer(now);
      if (!transfer.active && now - lastStep >= SPEEDS[speedIdx].ms) {
        const d = padDir || held[held.length - 1] || (routeQ.length ? routeQ[0] : null);
        if (d) {
          const ok = move(d);
          if (ok) {
            lastStep = now;
            if (routeQ[0] === d) routeQ.shift();
            if (!routeQ.length) routeTarget = null;
          } else {
            routeQ = [];
            routeTarget = null;
          }
        }
      }
    }
    const ease = reduced() ? 1 : 1 - Math.exp(-dt * 11);
    const turnEase = reduced() ? 1 : 1 - Math.exp(-dt * 11);
    state.angle += (state.angleTarget - state.angle) * turnEase;
    if (Math.abs(state.angleTarget - state.angle) < 0.001) state.angle = state.angleTarget;
    disp.x += (R.x - disp.x) * ease;
    disp.y += (R.y - disp.y) * ease;
    state.disp = disp;
    state.load = displayLoad();
    state.cap = R.cap;
    state.transferActive = transfer.active;
    state.transferHold = transfer.hold;
    state.done = done;
    updateParticles(dt);
    render(now);
    raf = requestAnimationFrame(frame);
  }

  layoutCanvas();
  paintThumbs();
  sync();
  render(performance.now());
  raf = requestAnimationFrame(frame);
  canvas.focus({ preventScroll: true });
  return { close: finishClose, requestClose: backClose };
}
