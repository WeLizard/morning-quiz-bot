// Preview sheet of Сорока's foreign crops on beds (the farm's own FarmScene.plant), next to the plain crop of the same family,
// at the growth stages the farm draws: sprout, sapling, growing, ripe. Day and night (the farm's night: dark tint, contact shadows).
//   python scripts/art/village/harness.py crops_sheet.js "{}" <out dir>   -> day.png, night.png
import {FarmScene} from '/static/scene.js';

const ROWS = [['exo_fire_pepper', 'pepper'], ['exo_blue_corn', 'corn'], ['exo_moon_pumpkin', 'pumpkin'],
  ['exo_honey_melon', 'melon'], ['exo_stripe_melon', 'watermelon'], ['exo_pearl_rice', 'rice']];
const STAGES = [.3, .5, .72, 1];

function sheet(night) {
  const k = 3, cw = 64, rh = 70, cols = STAGES.length * 2 + 1, cv = document.createElement('canvas');
  cv.width = cols * cw * k; cv.height = (ROWS.length * rh + 20) * k;
  const s = Object.create(FarmScene.prototype), c = cv.getContext('2d');
  Object.assign(s, {c, time: 0, motion: false, scale: 1, lighting: {darkness: night ? .8 : 0}, catalog: {crops: {}}, inStatic: false});
  c.fillStyle = night ? '#2b3a4a' : '#c1d5a3'; c.fillRect(0, 0, cv.width, cv.height);
  c.scale(k, k);
  ROWS.forEach(([exo, plain], r) => {
    [...STAGES.map(f => [exo, f]), null, ...STAGES.map(f => [plain, f])].forEach((cell, i) => {
      if (!cell) return;
      const x = i * cw + cw / 2, y = r * rh + 52;
      c.beginPath(); c.ellipse(x, y + 2, 22, 9, 0, 0, Math.PI * 2); c.fillStyle = night ? '#4a3f36' : '#b39572'; c.fill();
      c.beginPath(); c.ellipse(x, y + 1, 18, 6.5, 0, 0, Math.PI * 2); c.fillStyle = night ? '#57493c' : '#c4a47e'; c.fill();
      s.plant(x, y, cell[0], cell[1], 0);
    });
  });
  if (night) { c.setTransform(1, 0, 0, 1, 0, 0); c.fillStyle = 'rgba(22,33,90,.35)'; c.fillRect(0, 0, cv.width, cv.height) }
  return cv.toDataURL('image/png');
}
export async function render() { return {day: sheet(false), night: sheet(true)} }
