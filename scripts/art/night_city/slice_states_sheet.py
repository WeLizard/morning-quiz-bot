"""Cut a 3x3 transparent sheet of Night Case state objects into nine cutouts.

Usage: python slice_states_sheet.py <sheet.png> <out_dir> [<webp_dir>]

The nine cells, row by row, are the case-state objects of the mockup screens 15-23
(docs/design/mockups/night-case/): stopped clock (table paused), cut phone (no connection),
service bell (return to a paused table), card drawer (archive request), two versions (version
archive), letter on a salver (letter offer), empty chair (removed player), pen and notebook (free
action), candle stub (participation ended). Every world draws them in its own style
(docs/tasks/night_city/CODEX_ART_QUEUE.md, item 7.3); the names stay the same so the client can
pick them by key.

Alpha is normalised (<=7 -> 0, >=240 -> 255). 8-connected components (alpha >= 128, >= 300 px)
go to the cell that holds their centre of mass; the bbox plus a 3 px fringe is centred on a square
canvas at 90 % and saved as 1024 px PNG i_states_NN_<name>.png. With <webp_dir> a 400 px webp
<key>.webp is written too (the mockups use them). Exit code 1 means an empty cell.
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

KEYS = ['clock', 'phone', 'bell', 'drawer', 'versions', 'salver', 'chair', 'pen', 'candle']
FILES = ['stopped_clock', 'cut_phone', 'service_bell', 'card_drawer', 'two_versions', 'letter_salver',
         'empty_chair', 'pen_notebook', 'candle_stub']


def main(src: Path, out_src: Path, out_web: Path | None) -> int:
    im = Image.open(src).convert('RGBA')
    a = np.array(im)
    alpha = a[..., 3].copy()
    alpha[alpha <= 7] = 0
    alpha[alpha >= 240] = 255
    a[..., 3] = alpha
    w, h = im.size
    cw, ch = w // 3, h // 3
    labels, n = ndimage.label(alpha >= 128, structure=np.ones((3, 3)))  # type: ignore[misc]
    sizes = ndimage.sum(np.ones_like(alpha), labels, range(1, n + 1))
    centres = ndimage.center_of_mass(np.ones_like(alpha), labels, range(1, n + 1))
    out_src.mkdir(parents=True, exist_ok=True)
    if out_web:
        out_web.mkdir(parents=True, exist_ok=True)
    bad = 0
    for k, (key, fname) in enumerate(zip(KEYS, FILES)):
        r, c = divmod(k, 3)
        x0, y0 = c * cw, r * ch
        ids = [i for i in range(1, n + 1) if sizes[i - 1] >= 300
               and x0 <= centres[i - 1][1] < x0 + cw and y0 <= centres[i - 1][0] < y0 + ch]
        if not ids:
            print(f'{k + 1} {key:8s} EMPTY CELL')
            bad += 1
            continue
        mask = np.isin(labels, ids)
        ys, xs = np.nonzero(mask)
        outside = (xs < x0) | (xs >= x0 + cw) | (ys < y0) | (ys >= y0 + ch)
        bx0, bx1, by0, by1 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
        crop = a[by0:by1, bx0:bx1].copy()
        keep = ndimage.binary_dilation(mask[by0:by1, bx0:bx1], iterations=3)
        crop[..., 3] = np.where(keep, crop[..., 3], 0)
        obj = Image.fromarray(crop)
        side = int(max(obj.size) / 0.9)
        canvas = Image.new('RGBA', (side, side), (0, 0, 0, 0))
        canvas.paste(obj, ((side - obj.width) // 2, (side - obj.height) // 2), obj)
        canvas.resize((1024, 1024), Image.Resampling.LANCZOS).save(out_src / f'i_states_{k + 1:02d}_{fname}.png')
        if out_web:
            canvas.resize((400, 400), Image.Resampling.LANCZOS).save(out_web / f'{key}.webp', quality=86, method=6)
        # an object may poke across its cell border; it is still cut whole, the count is for the eye
        print(f'{k + 1} {key:8s} comps={len(ids)} bbox={bx1 - bx0}x{by1 - by0} spills_outside_cell={int(outside.sum())}')
    return 1 if bad else 0


if __name__ == '__main__':
    if len(sys.argv) not in (3, 4):
        sys.exit(__doc__)
    sys.exit(main(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]) if len(sys.argv) == 4 else None))
