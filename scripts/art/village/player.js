// The player's figure in the village: a small farmer in a straw hat and pastel overalls, drawn with the farm's own
// FarmScene methods (ellipse / line / poly, like the farm helpers in scene_expansion.js) and recorded as SVG
// (svg_ctx.js), because the figure is a live DOM layer that walks over the art.
// Three frames — standing and two steps — face right; the game mirrors them for walking left.
// Units: farm px, feet at 0,0. viewBox -17 -48 34 52.
import {FarmScene} from '/static/scene.js';
import {SvgCtx} from './svg_ctx.js';

const C = {skin: '#f3d3b0', cheek: '#efb4a0', eye: '#3d4a3f', hair: '#a8724a', shirt: '#efdcb4', overall: '#7fa3c4',
  bib: '#8fb2cf', strap: '#6d90b0', boot: '#6f5a46', hat: '#ecd283', brim: '#e3c56f', brimShade: '#cfae58', band: '#c98a5a',
  shadow: '#41623530'};

// pose: legs [backFootX, frontFootX, backLift, frontLift], arms [backHandX, frontHandX], bob (body lift)
const POSES = {
  stand: {legs: [-2.8, 2.8, 0, 0], arms: [-6.6, 6.6], bob: 0},
  stepA: {legs: [-5.2, 5.6, 1.6, 0], arms: [-3.4, 8.4], bob: .8},
  stepB: {legs: [-1.2, 1.6, 0, 1.2], arms: [-8.2, 4.2], bob: 0},
};

function figure(s, pose) {
  const {legs: [bx, fx, bl, fl], arms: [ba, fa], bob} = POSES[pose], y = -bob;
  s.ellipse(1.5, .6, 9.5, 3, C.shadow);                                   // contact shadow (lighter than the farm's, it sits on art)
  // back leg and arm first (farther from the viewer), then the body, then the near leg and arm
  s.line(-1.6, y - 9, bx, -1.4 - bl, C.overall, 4.2); s.ellipse(bx + .4, -1 - bl, 2.9, 1.7, C.boot);
  s.line(-4.6, y - 18.5, ba, y - 11.5, C.shirt, 3.3); s.ellipse(ba, y - 11, 1.9, 1.9, C.skin);
  s.ellipse(0, y - 17, 6.8, 6.6, C.shirt);                                // shirt
  s.ellipse(0, y - 12.2, 7.4, 6.8, C.overall);                            // overalls
  s.poly([{x: -4.4, y: y - 19.6}, {x: 4.4, y: y - 19.6}, {x: 4.8, y: y - 12}, {x: -4.8, y: y - 12}], C.bib);
  s.line(-3.6, y - 19.4, -4.6, y - 22, C.strap, 1.4); s.line(3.6, y - 19.4, 4.6, y - 22, C.strap, 1.4);
  s.ellipse(-2.6, y - 18.2, .8, .8, '#e8d9a8'); s.ellipse(2.6, y - 18.2, .8, .8, '#e8d9a8');   // buttons
  s.line(1.6, y - 9, fx, -1.4 - fl, C.overall, 4.2); s.ellipse(fx + .6, -1 - fl, 2.9, 1.7, C.boot);
  s.line(4.6, y - 18.5, fa, y - 11.5, C.shirt, 3.3); s.ellipse(fa, y - 11, 1.9, 1.9, C.skin);
  // head facing right: hair at the back, cheek and eye in front
  s.ellipse(.6, y - 27, 6.6, 6.6, C.skin);
  s.ellipse(-3.8, y - 28.6, 3.2, 3.4, C.hair);
  s.ellipse(3.9, y - 25.4, 1.7, 1.1, C.cheek);
  s.ellipse(3.3, y - 27.8, .9, 1.15, C.eye);
  // straw hat: shaded underside, brim, crown, band
  s.ellipse(.6, y - 31, 10.6, 2.6, C.brimShade);
  s.ellipse(.6, y - 31.6, 10.6, 3, C.brim);
  s.ellipse(.6, y - 32.4, 5.6, 1.5, C.band);                              // band at the crown's foot
  s.ellipse(.6, y - 35, 5.8, 4, C.hat);
  s.ellipse(-1.2, y - 35.8, 2.2, 1.2, '#f4e2a4');                          // light on the crown
}

export function playerSvg() {
  const parts = Object.keys(POSES).map(pose => {
    const c = new SvgCtx(`vp${pose}`), s = Object.create(FarmScene.prototype);
    s.c = c; figure(s, pose);
    return `<g class="vp-${pose}">${c.svg()}</g>`;
  });
  return `<svg class="vp-art" viewBox="-17 -48 34 52" aria-hidden="true" focusable="false">${parts.join('')}</svg>`;
}
