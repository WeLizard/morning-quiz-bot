"""Render the Night Case mockups into frames + overview sheets and run the layout checks.

    python docs/design/mockups/night-case/shoot.py [frames_dir]

Needs Playwright (Chromium, Edge or Chrome) and Pillow. Frames go to frames_dir (default F:/Temp/mqb-nc-mock/frames);
the overview sheets (webp) and checks.json are written next to this file.
Checks: taps >= 44 px, >= 8 px between neighbouring buttons outside .qw-btn-group/nav, no horizontal overflow,
no text under 12 px, clipped text, text contrast >= 4.5 on solid plates (text over art is skipped).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import serve  # noqa: E402

SCREENS = ['01_root', '02_worlds', '03_case', '04_lobby', '05_pick', '06_role', '07_place', '08_talk', '09_feed', '10_board', '11_dossier', '12_hearing', '13_final_hearing', '14_final']
LABELS = {'01_root': '1 Ночной город', '02_worlds': '2 Новое дело · миры', '03_case': '3 Дело мира', '04_lobby': '4 Сбор',
          '05_pick': '5 Выбор персонажа', '06_role': '6 Твоя роль', '07_place': '7 Место', '08_talk': '8 Разговор',
          '09_feed': '9 Гостиная у камина', '10_board': '10 Улики', '11_dossier': '11 Досье', '12_hearing': '12 Слушание',
          '13_final_hearing': '13 Итоговое слушание', '14_final': '14 Дело закрыто'}
VIEWPORTS = {
    'tg390': dict(w=390, h=700, q='', full=True),
    'web360': dict(w=360, h=780, q='', full=False),
    'pc1280': dict(w=1280, h=800, q='', full=True),
    'tab768': dict(w=768, h=1024, q='', full=False),
    'contrast390': dict(w=390, h=700, q='&c=1', full=True),
    'contrast1280': dict(w=1280, h=800, q='&c=1', full=False),
}

CHECK_JS = r"""
() => {
  const issues = [];
  const vis = el => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const btns = [...document.querySelectorAll('button')].filter(vis);
  for (const b of btns) { const r = b.getBoundingClientRect();
    if (r.height < 43.5 || r.width < 43.5) issues.push(`small-tap ${Math.round(r.width)}x${Math.round(r.height)} "${b.textContent.trim().slice(0,30)}"`); }
  const grouped = b => b.closest('.qw-btn-group, nav, [role=tablist], [data-qw-group]');
  const drawn = btns.filter(b => !grouped(b));
  const layer = b => b.closest('.nc-dock') ? 'dock' : b.closest('.nc-bar') ? 'bar' : 'page';
  for (let i = 0; i < drawn.length; i++) for (let j = i + 1; j < drawn.length; j++) {
    const a = drawn[i].getBoundingClientRect(), c = drawn[j].getBoundingClientRect();
    const dx = Math.max(c.left - a.right, a.left - c.right), dy = Math.max(c.top - a.bottom, a.top - c.bottom);
    const gap = Math.max(dx, dy);
    if (gap < 7.5 && layer(drawn[i]) === layer(drawn[j]) && !(drawn[i].contains(drawn[j]) || drawn[j].contains(drawn[i])))
      issues.push(`gap ${gap.toFixed(1)} "${drawn[i].textContent.trim().slice(0,18)}" / "${drawn[j].textContent.trim().slice(0,18)}"`);
  }
  if (document.documentElement.scrollWidth > innerWidth + 1) issues.push(`h-overflow ${document.documentElement.scrollWidth}`);
  const parse = c => { const m = c.match(/[\d.]+/g); return m ? m.map(Number) : [0,0,0,0]; };
  const lum = ([r,g,b]) => { const f = v => { v /= 255; return v <= .03928 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4; }; return .2126*f(r)+.7152*f(g)+.0722*f(b); };
  const bgOf = el => { for (let e = el; e; e = e.parentElement) { const s = getComputedStyle(e);
      if (s.backgroundImage && s.backgroundImage !== 'none' && !e.matches('body,html')) {
        if (s.backgroundImage.includes('url(')) return {img: true};
        const stops = s.backgroundImage.match(/rgba?\([^)]*\)|#[0-9a-f]{3,8}/gi) || []; if (stops.length) { const p = parse(stops.at(-1)); if ((p[3] ?? 1) > .85) return {rgb: p.slice(0,3)}; return {img: true}; } }
      const p = parse(s.backgroundColor); if (p.length === 3 || (p[3] ?? 1) > .9) return {rgb: p.slice(0,3)};
      if (e.matches('.nc-hero, .ncase-go, .ncase-rolecard, .pic')) return {img: true}; }
    return {rgb: [11,12,15]}; };
  const seen = new Set(); const worst = [];
  for (const el of document.querySelectorAll('body *')) {
    if (!vis(el) || el.closest('svg')) continue;
    const own = [...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim()); if (!own) continue;
    const s = getComputedStyle(el); const fs = parseFloat(s.fontSize);
    if (fs < 11.5) issues.push(`tiny-font ${fs}px "${el.textContent.trim().slice(0,24)}"`);
    if ((el.scrollWidth > el.clientWidth + 1) && s.textOverflow !== 'ellipsis' && s.overflow !== 'visible' && !el.matches('textarea')) issues.push(`clipped "${el.textContent.trim().slice(0,24)}"`);
    const bg = bgOf(el); if (bg.img) continue;
    let alpha = 1; for (let e = el; e; e = e.parentElement) alpha *= parseFloat(getComputedStyle(e).opacity);
    if (alpha < .9 || el.closest(':disabled')) continue;
    const fg = parse(s.color); const L1 = lum(fg.slice(0,3)), L2 = lum(bg.rgb);
    const ratio = (Math.max(L1,L2) + .05) / (Math.min(L1,L2) + .05);
    if (ratio < 4.5) { const key = el.className + el.textContent.trim().slice(0,20); if (!seen.has(key)) { seen.add(key); worst.push(`contrast ${ratio.toFixed(2)} "${el.textContent.trim().slice(0,28)}"`); } }
  }
  const broken = [...document.images].filter(i => !i.naturalWidth).map(i => `broken-img ${i.getAttribute('src').split('/').pop()}`);
  return issues.concat(worst, broken);
}
"""


def launch(p):
    for options in ({}, {'channel': 'msedge'}, {'channel': 'chrome'}):
        try:
            return p.chromium.launch(**options)
        except Exception:
            continue
    sys.exit('no browser')


def font(size):
    for name in ('segoeuib.ttf', 'arialbd.ttf'):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def sheet(frames, folder, out, cols, scale, title, max_h=None):
    files = [frames / folder / f'{s}.png' for s in SCREENS if (frames / folder / f'{s}.png').exists()]
    if not files:
        return
    ims = []
    for f in files:
        im = Image.open(f).convert('RGB')
        if max_h and im.height > max_h:
            im = im.crop((0, 0, im.width, max_h))
        ims.append(im.resize((int(im.width * scale), int(im.height * scale)), Image.Resampling.LANCZOS))
    w = max(i.width for i in ims)
    pad, lab = 24, 34
    rows = [ims[k:k + cols] for k in range(0, len(ims), cols)]
    heights = [max(i.height for i in row) for row in rows]
    sh = Image.new('RGB', (pad + cols * (w + pad), 70 + sum(h + lab + pad for h in heights)), (24, 26, 30))
    d = ImageDraw.Draw(sh)
    d.text((pad, 20), title, fill=(242, 194, 122), font=font(26))
    y = 70
    for r, row in enumerate(rows):
        for c, im in enumerate(row):
            x = pad + c * (w + pad)
            d.text((x, y + 4), LABELS[files[r * cols + c].stem], fill=(240, 234, 224), font=font(18))
            sh.paste(im, (x, y + lab))
            d.rectangle([x - 1, y + lab - 1, x + im.width, y + lab + im.height], outline=(70, 74, 82))
        y += heights[r] + lab + pad
    sh.save(out, quality=82, method=6)
    print('sheet', out.name, sh.size, f'{out.stat().st_size // 1024} KB')


def main(frames: Path):
    server = serve.start()
    base = f'http://127.0.0.1:{server.server_port}/mock/index.html'
    report = {}
    with sync_playwright() as p:
        browser = launch(p)
        for vp, cfg in VIEWPORTS.items():
            ctx = browser.new_context(viewport={"width": int(cfg["w"]), "height": int(cfg["h"])}, device_scale_factor=1)
            page = ctx.new_page()
            (frames / vp).mkdir(parents=True, exist_ok=True)
            if cfg['full']:
                (frames / f'{vp}-full').mkdir(parents=True, exist_ok=True)
            for s in SCREENS:
                page.goto(f'{base}?s={s}{cfg["q"]}')
                page.wait_for_function("document.documentElement.dataset.ready === '1'", timeout=20000)
                page.wait_for_timeout(150)
                page.screenshot(path=str(frames / vp / f'{s}.png'))
                issues = page.evaluate(CHECK_JS)
                if issues:
                    report[f'{vp}/{s}'] = issues
                if cfg['full']:
                    # The full-page frame shows the dock where it ends up after scrolling to the end.
                    page.add_style_tag(content='.nc-dock{position:static!important}.nc-main.has-dock{padding-bottom:var(--qw-s-4)!important}'
                                               '.nc-bar,.ncase-nav{position:relative!important;top:auto!important}')
                    page.screenshot(path=str(frames / f'{vp}-full' / f'{s}.png'), full_page=True)
            ctx.close()
        browser.close()
    server.shutdown()
    (HERE / 'checks.json').write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')
    for k, v in report.items():
        print(k)
        for i in v[:14]:
            print('   ', i)
    print('checks:', 'clean' if not report else f'{len(report)} frames with issues')
    sheet(frames, 'tg390-full', HERE / 'overview_phone_390.webp', 6, .62, 'Дело недели · телефон 390 (вся страница, панель внизу — в конце)', max_h=2300)
    sheet(frames, 'tg390', HERE / 'overview_phone_390_screen.webp', 6, .62, 'Дело недели · телефон 390 (первый экран, как в Telegram)')
    sheet(frames, 'pc1280', HERE / 'overview_pc_1280.webp', 3, .5, 'Дело недели · ПК 1280 (первый экран)')
    sheet(frames, 'contrast390', HERE / 'overview_contrast_390.webp', 6, .62, 'Дело недели · контрастный режим, телефон 390')


if __name__ == '__main__':
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path('F:/Temp/mqb-nc-mock/frames'))
