// «Лесоруб Степан»: vector assets recorded from qw_farm/static/lumberjack_art.js (the same painters the mini-game uses)
// into SVG, plus the farm's own renders for the «ферма слева — новое справа» comparison.
// Run through build.py (harness of scripts/art/village: headless Chromium, modules served from the working tree).
import * as A from '/static/lumberjack_art.js';
import {SvgCtx} from '/gen/village/svg_ctx.js';
import {playerSvg} from '/gen/village/player.js';
import {crewSvgs} from '/gen/village/crew.js';
import {makeS, B} from '/gen/village/common.js';
import {smallAnimal} from '/static/scene_expansion.js';

// The recorder of the village generator plus rotate (the saw on the shoulder is turned).
class Ctx extends SvgCtx {
  rotate(a) { const c = Math.cos(a), s = Math.sin(a); this.transform(c, s, -s, c, 0, 0); }
}
const rec = (prefix, draw) => { const c = new Ctx(prefix); draw(c); return c.svg(); };
const symbol = (id, vb, inner) => `<symbol id="${id}" viewBox="${vb}">${inner}</symbol>`;

// route icon «Делянка», 40×40: a fresh stump with Stepan's saw, a spruce behind, two logs
function routeIcon(c) {
  const p = A.painter(c);
  A.drawSpruce(p, 11, 31, 27, {tiers: 4});
  A.drawLogSide(p, 22, 35, 33.4, 2.6); A.drawLogSide(p, 24, 37, 28.6, 2.4);
  A.drawStump(p, 18, 35, 6.6, 5.4);
  c.save(); c.translate(17.2, 26.6); c.scale(.62, .62); c.rotate(-.12); A.chainsaw(p, {len: 13, sheath: true}); c.restore();
}
// chainsaw icon, 40×40 (button / tag), bar in its cover
function sawIcon(c) {
  const p = A.painter(c);
  c.save(); c.translate(13, 25); c.scale(1.05, 1.05); c.rotate(-.5); A.chainsaw(p, {len: 19, sheath: true}); c.restore();
}

function figureSvg() {
  const poses = ['stand', 'point', 'carry', 'saw'], b = A.FIGURE_BOX;
  const groups = poses.map(ps => `<g class="lj-${ps}">${rec('lj' + ps[0] + ps[1], c => A.drawFigure(c, 0, 0, 'stepan', ps, {pointAngle: -.75}))}</g>`);
  const one = Object.fromEntries(poses.map(ps => [ps, `<svg xmlns="http://www.w3.org/2000/svg" viewBox="${b.x} ${b.y} ${b.w} ${b.h}" role="img" aria-label="Лесоруб Степан">${rec('l1' + ps[0] + ps[1], c => A.drawFigure(c, 0, 0, 'stepan', ps, {pointAngle: -.75}))}</svg>`]));
  const farmerSaw = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="${b.x} ${b.y} ${b.w} ${b.h}" role="img" aria-label="Фермер с пилой">${rec('lfs', c => A.drawFigure(c, 0, 0, 'farmer', 'saw', {}))}</svg>`;
  return {sprite: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="${b.x} ${b.y} ${b.w} ${b.h}" class="lj-art" aria-hidden="true" focusable="false">${groups.join('')}</svg>`, one, farmerSaw};
}

function cardSvg(night) {
  const inner = rec(night ? 'lpn' : 'lpd', c => A.drawPlotCard(c, {night}));
  return {inner, svg: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 160 68" role="img" aria-label="Делянка"><title>Делянка</title>${inner}</svg>`};
}

// Left side: what the farm already draws — tiles, trees, a barn, geese and a rabbit, at the farm's own scale.
function farmReference(night) {
  const cv = document.createElement('canvas'); cv.width = 720; cv.height = 400;
  const c = cv.getContext('2d'), s = makeS(c);
  c.fillStyle = '#c1d5a3'; c.fillRect(0, 0, 720, 400);
  c.save(); c.translate(330, 70); c.scale(1.3, 1.3);
  for (let y = 0; y < 6; y++) for (let x = 0; x < 6; x++) s.tile(x, y, (x + y) % 2 ? '#bfd39e' : '#c6d9a9');
  B.drawBuilding(s, {id: 'barn', type: 'barn', x: 0, y: 0, w: 2, h: 2, level: 1, jobs: []});
  for (const [x, y, k] of [[4.6, .4, 1], [5.4, 1.6, .9], [-.6, 3.4, 1.1], [-1, 4.6, .85], [5.2, 4.6, 1]]) s.treeSprite(x, y, k);
  smallAnimal(s, 40, 150, 'goose'); smallAnimal(s, 90, 160, 'rabbit');
  c.restore();
  if (night) { c.fillStyle = '#0e1828a0'; c.fillRect(0, 0, 720, 400); }
  return cv.toDataURL('image/png');
}

export async function render() {
  const symbols = {
    helper_lumberjack: symbol('helper_lumberjack', '0 0 48 48', rec('hlj', c => A.drawBust(c, 'icon'))),
    avatar_lumberjack: symbol('avatar_lumberjack', '0 0 40 40', rec('alj', c => A.drawBust(c, 'avatar'))),
    logging_plot: symbol('logging_plot', '0 0 40 40', rec('rlp', routeIcon)),
    chainsaw: symbol('chainsaw', '0 0 40 40', rec('csw', sawIcon)),
  };
  const crew = crewSvgs();
  return {symbols, card_day: cardSvg(false), card_night: cardSvg(true), figure: figureSvg(), farm: {player: playerSvg(), crew},
    reference_day: farmReference(false), reference_night: farmReference(true), figure_box: A.FIGURE_BOX};
}
