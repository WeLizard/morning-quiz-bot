// The scene object `s` for the village painter: a still FarmScene, so tile, treeSprite, perimeterLantern, shadow, poly,
// ellipse and line are the farm's own methods (qw_farm/static/scene.js), with motion off and a fixed clock.
// B = qw_farm/static/scene_buildings.js with its internals exported and window/smoke/sail recorders (see harness.py).
import {FarmScene} from '/static/scene.js';
import * as B from '/static/scene_buildings.js';

export {B};
export const TW = 36, TH = 18;
export const P = (x, y, z = 0) => ({x: (x - y) * TW, y: (x + y) * TH - z});

export function makeS(ctx) {
  const s = Object.create(FarmScene.prototype);
  // inStatic + shadowLevel 0 = the farm's daylight static layer (contact shadows #41623517, lantern glass unlit).
  Object.assign(s, {c: ctx, time: 0, motion: false, inStatic: true, shadowLevel: 0, lighting: null,
    farm: {id: 'village', size: 12, level: 1, objects: [], home_projects: {entries: {}}},
    // recorders filled by the patched building code: windows (night lights) and chimney tops (live smoke layer)
    win: [], smk: []});
  s.lantern = p => s.perimeterLantern(p);
  return s;
}
