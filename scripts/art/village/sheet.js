// Contact sheet of every farm building type at scale 1 — a reference when placing or matching village buildings.
//   python scripts/art/village/harness.py sheet.js "{}" <out dir>   -> sheet.png
import {B, makeS} from './common.js';

export async function render({w = 2, h = 2, cols = 8} = {}) {
  const types = B.BUILDING_TYPES || Object.keys(B.TYPES), cw = 260, ch = 230, rows = Math.ceil(types.length / cols);
  const cv = document.createElement('canvas'); cv.width = cols * cw; cv.height = rows * ch;
  const c = cv.getContext('2d'), s = makeS(c);
  c.fillStyle = '#c1d5a3'; c.fillRect(0, 0, cv.width, cv.height);
  types.forEach((type, i) => {
    c.save(); c.translate((i % cols) * cw + cw / 2, Math.floor(i / cols) * ch + 150 - (w + h) * 9);
    B.drawBuilding(s, {id: type, type, x: 0, y: 0, w, h, level: 1, jobs: []});
    c.restore();
  });
  return {sheet: cv.toDataURL('image/png'), types};
}
