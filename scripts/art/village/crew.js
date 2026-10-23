// The building crew of the village (FARM_VILLAGE_CONSTRUCTION.md §6.4): Krot the foreman with a blueprint, Pooh the bear
// with a hammer, Kaya the cat with a shovel. Drawn with the farm's FarmScene methods (ellipse / line / poly, like player.js)
// and recorded as SVG: they are a live DOM layer over the site while the residents work. The moving part of each figure is
// one group the game animates with CSS (transform only, none under reduced motion):
//   bc-plan  (Krot's blueprint, nods),  bc-hammer (Pooh's arm with the hammer, swings),  bc-shovel (Kaya's shovel, digs).
// Units: farm px, feet at 0,0. viewBox -18 -50 36 54 (the player's scale).
import {FarmScene} from '/static/scene.js';
import {SvgCtx} from './svg_ctx.js';

const SH = '#41623530';

function krot(s, c) {
  s.ellipse(1.5, .6, 9, 2.8, SH);
  s.ellipse(-3, -1.2, 3.2, 1.8, '#4f4540'); s.ellipse(3, -1.2, 3.2, 1.8, '#4f4540');                  // feet
  s.ellipse(0, -11, 7.6, 9.4, '#6f6259');                                                          // body
  s.poly([{x: -5.6, y: -15}, {x: 5.6, y: -15}, {x: 6.4, y: -5}, {x: -6.4, y: -5}], '#e8a83a');      // work vest
  s.line(-5.6, -11, 5.6, -11, '#f4ede0', 1.4);                                                     // reflective stripe
  s.ellipse(0, -24, 6.4, 6, '#6f6259');                                                            // head
  s.ellipse(4.6, -22.6, 2.8, 2, '#e7a8b5'); s.ellipse(6.8, -22.4, 1.1, 1, '#c97a8a');             // snout
  s.ellipse(1.6, -25.2, .8, .7, '#2f3338');                                                        // eye (small: a mole)
  s.poly([{x: -6.6, y: -27}, {x: 6.6, y: -27}, {x: 5.4, y: -31.6}, {x: 0, y: -33.4}, {x: -5.4, y: -31.6}], '#f0c95a');   // hard hat
  s.line(-7.6, -27, 7.8, -27, '#d9a650', 1.6);
  s.line(-5.6, -16, -8.6, -9, '#6f6259', 2.6);                                                     // back arm
  c.group('bc-plan');                                                                              // the blueprint in the front hand
  s.line(5.4, -16, 9.6, -13.6, '#6f6259', 2.6);
  s.poly([{x: 7.4, y: -21}, {x: 15.6, y: -18.6}, {x: 14.8, y: -9.6}, {x: 6.6, y: -12}], '#9fc0d4');
  s.poly([{x: 9.4, y: -13.6}, {x: 9.4, y: -16.8}, {x: 11.2, y: -18.6}, {x: 13, y: -16}, {x: 13, y: -12.8}], null, '#f4f7f8');
  s.ellipse(15.2, -14, 1.2, 4.6, '#b9d2e0');
  c.end();
}

function pooh(s, c) {
  s.ellipse(1.5, .6, 10, 3, SH);
  s.ellipse(-3.4, -1.4, 3.6, 2.2, '#8a5f3a'); s.ellipse(3.4, -1.4, 3.6, 2.2, '#8a5f3a');
  s.ellipse(0, -12, 9, 10.4, '#b5814f');                                                           // body
  s.ellipse(0, -10, 5.6, 6.6, '#e3c08a');                                                          // belly
  s.poly([{x: -7.4, y: -9}, {x: 7.4, y: -9}, {x: 7.8, y: -6.6}, {x: -7.8, y: -6.6}], '#7fa3c4');    // tool belt
  s.ellipse(-3, -7.8, 1.4, 1.8, '#9c9e9a');
  s.ellipse(-4.4, -31.4, 2.6, 2.6, '#b5814f'); s.ellipse(4.4, -31.4, 2.6, 2.6, '#b5814f');          // ears
  s.ellipse(0, -26, 7, 6.6, '#b5814f');                                                            // head
  s.ellipse(1.8, -23.6, 3.4, 2.6, '#e3c08a'); s.ellipse(2.4, -24.6, 1.2, .9, '#3d2f26');           // muzzle, nose
  s.ellipse(-1.6, -27.4, .8, .9, '#2f3338'); s.ellipse(3.6, -27.6, .8, .9, '#2f3338');
  s.line(-7, -17, -9.4, -10, '#b5814f', 3.4);                                                      // back arm
  c.group('bc-hammer');                                                                            // the arm with the hammer
  s.line(6.6, -17, 10.6, -22, '#b5814f', 3.4);
  s.line(10.6, -22, 12, -30, '#8a6c4c', 1.6); s.poly([{x: 9, y: -31.6}, {x: 15.4, y: -29.4}, {x: 15, y: -27}, {x: 8.6, y: -29.2}], '#7f8a86');
  c.end();
}

function kaya(s, c) {
  s.ellipse(1.5, .6, 8.6, 2.8, SH);
  s.ellipse(-2.6, -1.2, 2.8, 1.8, '#8d8a84'); s.ellipse(2.6, -1.2, 2.8, 1.8, '#8d8a84');
  s.line(-4.6, -6, -10.6, -14, '#a9a7a0', 2.4); s.line(-10.6, -14, -9, -19, '#a9a7a0', 2.4);         // tail
  s.ellipse(0, -11, 6.4, 8.6, '#a9a7a0');                                                          // body
  s.poly([{x: -5, y: -16}, {x: 5, y: -16}, {x: 5.8, y: -4.6}, {x: -5.8, y: -4.6}], '#8fae6f');       // apron
  s.ellipse(0, -23.4, 6, 5.6, '#a9a7a0');                                                          // head
  s.poly([{x: -5.4, y: -26}, {x: -4.4, y: -32}, {x: -1.4, y: -27.6}], '#a9a7a0'); s.poly([{x: 5.4, y: -26}, {x: 4.4, y: -32}, {x: 1.4, y: -27.6}], '#a9a7a0');
  s.poly([{x: -4.6, y: -26.4}, {x: -4.2, y: -30.2}, {x: -2.4, y: -27.6}], '#e7a8b5');
  s.line(-3, -27, -1.4, -25.6, '#7c7a74', 1); s.line(0, -28, 0, -26, '#7c7a74', 1);                 // tabby stripes
  s.ellipse(-2, -23.6, .8, 1, '#3d4a3f'); s.ellipse(2.2, -23.6, .8, 1, '#3d4a3f'); s.ellipse(.2, -21.6, .9, .6, '#e7a8b5');
  c.group('bc-shovel');                                                                            // the shovel in both hands
  s.line(-4.6, -16, 3, -10, '#a9a7a0', 2.4); s.line(4.6, -15, 6, -10.6, '#a9a7a0', 2.4);
  s.line(1, -20, 9, -1, '#8a6c4c', 1.8); s.poly([{x: 6.6, y: -2.6}, {x: 11.4, y: -4.4}, {x: 12.4, y: 1.4}, {x: 8.6, y: 2.6}], '#8f949c');
  c.end();
}

export function crewSvgs() {
  const out = {};
  for (const [name, draw] of [['krot', krot], ['pooh', pooh], ['kaya', kaya]]) {
    const c = new SvgCtx('bc' + name[0]), s = Object.create(FarmScene.prototype);
    s.c = c; s.time = 0; s.motion = false; s.inStatic = true; s.shadowLevel = 0;
    draw(s, c);
    out[name] = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="-18 -50 36 54" class="bc-art" aria-hidden="true" focusable="false">${c.svg()}</svg>`;
  }
  return out;
}
