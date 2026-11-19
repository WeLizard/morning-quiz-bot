// The player's two looks in the village (owner's decision 2026-11-19): a grown-up farmer with a moustache and a pleasant
// slim farmer woman, chosen by the account's address form (MQB-011: 'f' → the farmer woman, otherwise the farmer).
// Preview only: player.js (the figure the game shows now) stays as it is until the owner approves these drawings.
// Same frame contract as player.js — stand / stepA / stepB facing right, feet at 0,0, viewBox -17 -48 34 52 — and the same
// FarmScene primitives (ellipse / line / poly), recorded as SVG (svg_ctx.js).
import {FarmScene} from '/static/scene.js';
import {SvgCtx} from './svg_ctx.js';

// pose: legs [backFootX, frontFootX, backLift, frontLift], arms [backHandX, frontHandX], bob (body lift), sway (skirt hem)
export const POSES = {
  stand: {legs: [-2.8, 2.8, 0, 0], arms: [-6.6, 6.6], bob: 0, sway: 0},
  stepA: {legs: [-5.2, 5.6, 1.6, 0], arms: [-3.4, 8.4], bob: .8, sway: .9},
  stepB: {legs: [-1.2, 1.6, 0, 1.2], arms: [-8.2, 4.2], bob: 0, sway: -.7},
};

const polyOf = s => (pts, col) => s.poly(pts.map(([a, b]) => ({x: a, y: b})), col);

// ---------- the farmer: grown-up proportions (long legs, straight torso, a smaller head), a nose and a bushy moustache --
export const FARMER = {skin: '#f3d3b0', skinShade: '#e6c29e', ear: '#e6b896', cheek: '#efb4a0', nose: '#ecb48f',
  eye: '#3d4a3f', hair: '#8a5a3a', tache: '#6b3f26', shirt: '#efdcb4', overall: '#7fa3c4', bib: '#8fb2cf', strap: '#6d90b0',
  boot: '#6f5a46', hat: '#ecd283', brim: '#e3c56f', brimShade: '#cfae58', band: '#c98a5a', shadow: '#41623530'};

export function farmerFigure(s, pose) {
  const C = FARMER, {legs: [bx, fx, bl, fl], arms: [ba, fa], bob} = POSES[pose], y = -bob, poly = polyOf(s);
  s.ellipse(1.5, .6, 9.5, 3, C.shadow);
  // back leg and arm, then the body, then the near leg and arm
  s.line(-1.8, y - 12, bx, -1.6 - bl, C.overall, 4); s.ellipse(bx + .5, -1.1 - bl, 3.1, 1.7, C.boot);
  s.line(-4.4, y - 23.4, ba * .95, y - 14.4, C.shirt, 3.1); s.ellipse(ba * .95, y - 13.9, 1.8, 1.8, C.skin);
  s.ellipse(0, y - 21.6, 6.2, 4.4, C.shirt);                               // shoulders
  poly([[-5.4, y - 21], [5.4, y - 21], [5.8, y - 12.6], [3.8, y - 10.4], [-3.8, y - 10.4], [-5.8, y - 12.6]], C.overall);
  poly([[-4, y - 24], [4, y - 24], [4.4, y - 16], [-4.4, y - 16]], C.bib);
  s.line(-3.2, y - 23.8, -4.4, y - 26.2, C.strap, 1.3); s.line(3.2, y - 23.8, 4.4, y - 26.2, C.strap, 1.3);
  s.ellipse(-2.5, y - 22.8, .75, .75, '#e8d9a8'); s.ellipse(2.5, y - 22.8, .75, .75, '#e8d9a8');
  s.line(-3.6, y - 19.6, 3.6, y - 19.6, C.strap, .6);                       // the bib pocket's seam
  s.line(-5.6, y - 15.6, 5.6, y - 15.6, C.strap, .9);                       // waist seam
  s.line(1.8, y - 12, fx, -1.6 - fl, C.overall, 4); s.ellipse(fx + .7, -1.1 - fl, 3.1, 1.7, C.boot);
  s.line(4.4, y - 23.4, fa * .95, y - 14.4, C.shirt, 3.1); s.ellipse(fa * .95, y - 13.9, 1.8, 1.8, C.skin);
  // head in profile facing right: neck, hair at the back, sideburn, ear, a straight nose, an eye under a brow, the moustache
  const hy = y - 31.2;
  s.ellipse(.4, y - 25.6, 2, 1.8, C.skinShade);
  s.ellipse(.6, hy, 5.2, 5.6, C.skin);
  s.ellipse(-3, hy - 1, 2.6, 3.4, C.hair);
  s.ellipse(-1.6, hy + 2.2, 1.2, 1.8, C.hair);
  s.ellipse(-.4, hy + .4, 1.1, 1.5, C.ear);
  poly([[5.2, hy - 1.4], [7.4, hy + 1.4], [5.6, hy + 2]], C.nose);
  s.ellipse(3.4, hy - 1.2, .8, 1.05, C.eye); s.ellipse(3.6, hy - 1.5, .25, .25, '#fff');
  s.line(2.2, hy - 3.2, 4.6, hy - 3.3, C.hair, .9);
  s.ellipse(2.4, hy + 1.2, 1.1, .7, C.cheek);
  // a bushy moustache: two lobes under the nose, the tips curling down
  s.ellipse(5.2, hy + 2.6, 2.3, 1.05, C.tache); s.ellipse(3.2, hy + 2.8, 1.9, 1, C.tache);
  s.ellipse(6.9, hy + 3.2, .9, .8, C.tache); s.ellipse(1.6, hy + 3.3, .9, .75, C.tache);
  // straw hat: shaded underside, brim, band, crown
  s.ellipse(.6, hy - 4, 9.8, 2.5, C.brimShade);
  s.ellipse(.6, hy - 4.6, 9.8, 2.9, C.brim);
  s.ellipse(.6, hy - 5.4, 5, 1.4, C.band);
  s.ellipse(.6, hy - 7.8, 5.2, 3.8, C.hat);
  s.ellipse(-1.2, hy - 8.6, 2, 1.1, '#f4e2a4');
}

// ---------- the farmer woman: slim, a blouse and a sarafan, a braid down the back, a straw hat with a ribbon and a daisy --
export const FARMER_WOMAN = {skin: '#f5d6b6', nose: '#efc09e', cheek: '#f0a99a', eye: '#3d4a3f', lash: '#3d4a3f',
  lips: '#c0605a', hair: '#9a5a36', hairShade: '#7e4529', blouse: '#f6ead0', sarafan: '#cf6f6a', sarafanShade: '#b85b57',
  hem: '#f2c3a4', stocking: '#5e6f86', boot: '#7a5a44', hat: '#ecd283', brim: '#e3c56f', brimShade: '#cfae58',
  ribbon: '#cf6f6a', petal: '#ffffff', heart: '#f2c94c', shadow: '#41623530'};

export function farmerWomanFigure(s, pose) {
  const C = FARMER_WOMAN, {legs: [bx, fx, bl, fl], arms: [ba, fa], bob, sway} = POSES[pose], y = -bob, poly = polyOf(s);
  s.ellipse(1.2, .6, 8.2, 2.7, C.shadow);
  // the braid hangs down the back behind everything, a ribbon at its tip
  const hy = y - 31.4;
  for (let k = 0; k < 7; k++) s.ellipse(-4 - k * .3 - sway * k * .12, hy + 2.6 + k * 2.1, 1.4, 1.25, k % 2 ? C.hairShade : C.hair);
  s.ellipse(-6.1 - sway * .8, hy + 17.4, 1.5, .9, C.ribbon);
  // slim legs in dark stockings under a knee-length skirt, small boots
  s.line(-1.1, y - 9, bx * .85, -1.4 - bl, C.stocking, 2.6); s.ellipse(bx * .85 + .5, -1 - bl, 2.5, 1.4, C.boot);
  s.line(-3.6, y - 22.4, ba * .9, y - 14.8, C.blouse, 2.4); s.ellipse(ba * .9, y - 14.4, 1.5, 1.5, C.skin);
  // the sarafan: a narrow bodice, a belt at a slim waist, a skirt flaring to a light hem
  s.ellipse(0, y - 21.4, 4.2, 3.4, C.blouse);
  poly([[-3, y - 23.4], [3.2, y - 23.4], [3.4, y - 16.6], [-3.2, y - 16.6]], C.sarafan);
  poly([[-3.4, y - 16.8], [3.5, y - 16.8], [6.8 + sway, y - 7.6], [-6.6 + sway, y - 7.6]], C.sarafan);
  poly([[-6.1 + sway, y - 9.6], [6.3 + sway, y - 9.6], [6.8 + sway, y - 7.6], [-6.6 + sway, y - 7.6]], C.hem);
  s.line(-2, y - 16.2, -3 + sway * .6, y - 10.4, C.sarafanShade, .7);
  s.line(2, y - 16.2, 3 + sway * .6, y - 10.4, C.sarafanShade, .7);
  s.line(-3.3, y - 16.7, 3.4, y - 16.7, C.sarafanShade, 1.2);              // belt
  s.line(-2.3, y - 23.2, -2.6, y - 25.2, C.sarafan, 1); s.line(2.5, y - 23.2, 2.8, y - 25.2, C.sarafan, 1);
  s.line(1.1, y - 9, fx * .85, -1.4 - fl, C.stocking, 2.6); s.ellipse(fx * .85 + .6, -1 - fl, 2.5, 1.4, C.boot);
  s.ellipse(3.4, y - 22.8, 1.8, 1.6, C.blouse);                            // puffed sleeve of the near arm
  s.line(3.8, y - 22.4, fa * .9, y - 14.8, C.blouse, 2.4); s.ellipse(fa * .9, y - 14.4, 1.5, 1.5, C.skin);
  // head: a little smaller than the farmer's, hair over the ear, lashes, rosy cheek and lips
  s.ellipse(.4, y - 25.8, 1.4, 1.6, C.skin);
  s.ellipse(.8, hy, 4.9, 5.3, C.skin);
  s.ellipse(-2.6, hy - .6, 3.4, 4.1, C.hair);
  poly([[-1.2, hy - 5.1], [4.2, hy - 4.9], [5.4, hy - 3], [2.6, hy - 3.6], [.6, hy - 2.8]], C.hair);
  poly([[5.4, hy - .4], [6.5, hy + 1.3], [5.4, hy + 1.6]], C.nose);
  s.ellipse(2.8, hy + 1.6, 1.2, .75, C.cheek);
  s.ellipse(3.5, hy - .8, .78, 1.02, C.eye); s.ellipse(3.7, hy - 1.1, .24, .24, '#fff');
  s.line(4, hy - 1.7, 5, hy - 2.4, C.lash, .5); s.line(3.4, hy - 1.9, 3.9, hy - 2.8, C.lash, .5);
  s.ellipse(4.6, hy + 3, .85, .48, C.lips);
  // straw hat, a ribbon band and a daisy on the side
  s.ellipse(.8, hy - 4.4, 9.2, 2.3, C.brimShade);
  s.ellipse(.8, hy - 5, 9.2, 2.7, C.brim);
  s.ellipse(.8, hy - 5.8, 4.8, 1.3, C.ribbon);
  s.ellipse(.8, hy - 8.1, 5, 3.6, C.hat);
  s.ellipse(-1, hy - 8.9, 1.9, 1.05, '#f4e2a4');
  s.line(-3.8, hy - 5.4, -6.4 - sway * .6, hy - 2.4, C.ribbon, 1);
  s.line(-3.4, hy - 5.4, -5.2 - sway * .6, hy - 1.6, C.ribbon, 1);
  for (let k = 0; k < 6; k++) {
    const a = k * Math.PI / 3;
    s.ellipse(4.1 + Math.cos(a) * 1.15, hy - 6.4 + Math.sin(a) * 1.15, .78, .78, C.petal);
  }
  s.ellipse(4.1, hy - 6.4, .72, .72, C.heart);
}

export const LOOKS = {m: farmerFigure, f: farmerWomanFigure};

// The account's address form ('m' | 'f' | 'n') → the look; the neutral form keeps the farmer.
export const lookOf = form => form === 'f' ? 'f' : 'm';

export function playerLookSvg(look = 'm') {
  const draw = LOOKS[look];
  const parts = Object.keys(POSES).map(pose => {
    const c = new SvgCtx(`vp${look}${pose}`), s = Object.create(FarmScene.prototype);
    s.c = c; draw(s, pose);
    return `<g class="vp-${pose}">${c.svg()}</g>`;
  });
  return `<svg class="vp-art" viewBox="-17 -48 34 52" aria-hidden="true" focusable="false">${parts.join('')}</svg>`;
}

// harness entry (preview_player_looks.py)
export function render() {
  return {m: playerLookSvg('m'), f: playerLookSvg('f')};
}
