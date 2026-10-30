"""Лесоруб Степан, карточка «Делянка», мини-игра «Валка» — review build (docs/tasks/FARM_LUMBERJACK.md §7, step 3).

python scripts/art/lumberjack/build.py            # vector assets + previews -> .local/lumberjack-art/ (F:)
python scripts/art/lumberjack/build.py --icons    # also add/refresh the four symbols in qw_farm/static/icons.svg

Nothing else in qw_farm/static is written: the mini-game client (step 4) imports qw_farm/static/lumberjack_art.js itself.
Left side of every comparison = the farm's own art (its functions, icons, cards and the real fishing mini-game of trip_game.js);
right side = the new art. The mini-game frames are the fg-overlay screen of trip_game.js (same classes and style.css) with the
canvas painted by drawFellScene from a real plan of qw_farm.trip_games.make_fell_plan.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'village'))
import harness  # noqa: E402

harness.GEN = HERE.parent
ROOT = harness.ROOT.resolve()
sys.path.insert(0, str(ROOT))
from qw_farm import trip_games as TG  # noqa: E402

SIZES = [(375, 812), (390, 844), (1280, 800)]
SHELL = ROOT / 'web' / 'shell'
ICON_IDS = ('helper_lumberjack', 'avatar_lumberjack', 'logging_plot', 'chainsaw')
MSK = timezone(timedelta(hours=3))


# ---------------------------------------------------------------- one browser for all screenshots
class Shots:
    def __init__(self, mounts):
        harness._env_browsers()
        from playwright.sync_api import sync_playwright
        self.pw = sync_playwright().start()
        self.browser = self.pw.chromium.launch(executable_path=harness._chromium(), args=['--disable-gpu', '--force-color-profile=srgb'])
        self.mounts = {'/static/': harness.STATIC, '/app/shell/': SHELL, **mounts}

    def shot(self, html, path, size, full=False, wait_ms=700):
        page = self.browser.new_page(viewport={'width': size[0], 'height': size[1]}, device_scale_factor=1)
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('console', lambda m: errors.append(m.text) if m.type == 'error' else None)

        def handle(route):
            url = route.request.url[len(harness.ORIGIN):].split('?')[0]
            if url == '/index.html':
                return route.fulfill(body=html, content_type='text/html')
            prefix = next((m for m in self.mounts if url.startswith(m)), None)
            p = Path(self.mounts[prefix]) / url[len(prefix):] if prefix else None
            if p is None or not p.is_file():
                return route.fulfill(status=404, body='')
            return route.fulfill(body=p.read_bytes(), content_type=harness.TYPES.get(p.suffix, 'application/octet-stream'))

        page.route(harness.ORIGIN + '/**', handle)
        page.goto(harness.ORIGIN + '/index.html')
        page.wait_for_load_state('networkidle')
        page.evaluate('() => Promise.all([...document.images].map(i => i.decode().catch(() => null)))')
        page.wait_for_timeout(wait_ms)
        page.screenshot(path=str(path), full_page=full)
        page.close()
        bad = [e for e in errors if 'favicon' not in e and '404' not in e]
        if bad:
            raise RuntimeError(f'{path.name}: page errors:\n' + '\n'.join(bad))

    def close(self):
        self.browser.close(); self.pw.stop()


# ---------------------------------------------------------------- the «Валка» screen mockup (fg-overlay of trip_game.js)
EXTRA_CSS = '''
/* proposed for the client (step 4): states of the hold button. The ":root .fg-controls" prefix is needed: at night
   ":root[data-farm-theme=night] :is(.primary,.fg-act.primary,.pill-row button.active)" (0,4,1) and in the contrast mode
   ":root[data-qw-contrast='1'] :is(.primary,.pill-row button.active)" (0,3,1) repaint every .primary — today they also
   swallow fishing's .tg-hot at night and in the contrast mode. */
:root .fg-controls .tg-big.tg-hot{background:#c9632f;border-color:#a44d22;color:#fff}
:root .fg-controls .tg-big.tg-ready{background:#2f7a43;border-color:#1f5a32;color:#fff}
:root .fg-controls .tg-big.tg-stalled{background:#c9c2b2;border-color:#8f8a80;color:#2f2a22}
:root[data-farm-theme=night] .fg-controls .tg-big.tg-hot{background:#c9632f;border-color:#a44d22;color:#fff}
:root[data-farm-theme=night] .fg-controls .tg-big.tg-ready{background:#8fd39a;border-color:#8fd39a;color:#10231a}
:root[data-farm-theme=night] .fg-controls .tg-big.tg-stalled{background:#4a4a42;border-color:#8f8a80;color:#f2edc4}
:root[data-qw-contrast="1"] .fg-controls .tg-big.tg-hot{background:#a3461c;border-color:var(--ink);color:#fff}
:root[data-qw-contrast="1"] .fg-controls .tg-big.tg-ready{background:#1f5a32;border-color:var(--ink);color:#fff}
:root[data-qw-contrast="1"] .fg-controls .tg-big.tg-stalled{background:#e4ded0;border-color:var(--ink);color:#10231a}
:root[data-qw-contrast="1"][data-farm-theme=night] .fg-controls .tg-big.tg-ready{background:#8fd39a;color:#10231a}
:root[data-qw-contrast="1"][data-farm-theme=night] .fg-controls .tg-big.tg-stalled{background:#4a4a42;color:#ffffff}
.fg-canvas{filter:var(--qw-scene-filter,none)}
.lj-trees{list-style:none;margin:8px 0;padding:0;display:flex;flex-direction:column;gap:3px;font-weight:650;font-size:14px;text-align:left}
.lj-trees li.bad{color:#9a4b2a}:root[data-farm-theme=night] .lj-trees li.bad{color:#ffb7a0}
.lj-sum{display:flex;align-items:center;gap:12px;justify-content:center;margin:6px 0}.lj-sum svg{width:56px;height:56px}
.lj-big{font-size:28px;font-weight:850}
'''

BUTTON = {
    'aim': ('Наметить подпил', ''), 'cut': ('Пилю — держи', 'tg-hold'), 'pinch': ('Отпусти — зажим!', 'tg-hold tg-hot'),
    'stall': ('Дорезать — держи', 'tg-stalled'), 'ready': ('Отпусти — дерево пойдёт!', 'tg-hold tg-ready'),
    'fall': ('Дерево падает…', ''), 'fallen': ('Следующее дерево…', ''), 'crooked': ('Следующее дерево…', ''), 'summary': ('…', ''),
}
STATUS = {
    'aim': ('Метка бежит по дуге. Жми, когда она в жёлтом просвете.', False),
    'cut': ('Пила режет. Цепь греется — отпускай, чтобы остыла.', False),
    'pinch': ('Ствол зажал пилу: цепь греется вчетверо быстрее.', True),
    'stall': ('Пила заглохла: держи — дорежем медленно, оценка за пропил ниже.', True),
    'ready': ('Пропил дошёл до зелёной отметки — отпускай, дерево пойдёт.', False),
    'fall': ('Дерево пошло в просвет!', False), 'fallen': ('Ровно в просвет.', False),
    'crooked': ('Подпил вне просвета: дерево легло криво, задело соседку.', True), 'summary': ('', False),
}
HELP = ('Жми, когда метка в просвете между соседними елями — туда ляжет дерево. Потом держи «Пилить»: цепь греется, '
        'в зажиме — сильнее; перегреешь — пила заглохнет. Отпусти после зелёной отметки — дерево пойдёт.')


def fell_states(plan):
    t1, t2 = plan['trees'][1], plan['trees'][2]
    gap = {'center': t1['gap_center'], 'width': t1['gap_width']}
    # the pinch windows of the plan as cut positions if the saw were held all along (prog += CUT_RATE per 50 ms tick)
    pin = [min(1000, (p // TG.TICK) * TG.CUT_RATE * 1000 // t1['girth']) for p in t1['pinches']]
    aim_in = t1['gap_center'] + 30
    base = {'gap': gap, 'index': 1, 'total': 5, 'pinches': pin, 'aim': aim_in, 'felled': [{'crooked': False}]}
    v_ok = {'text': 'Легло ровно! · 930', 'tone': 'good'}
    gap2 = {'center': t2['gap_center'], 'width': t2['gap_width']}
    miss = t2['gap_center'] - t2['gap_width'] - 120 if t2['gap_center'] > 500 else t2['gap_center'] + t2['gap_width'] + 120
    return {
        'aim': {**base, 'phase': 'aim', 'aim': (t1['gap_center'] - t1['gap_width'] + 40), 't': 900},
        'cut': {**base, 'phase': 'cut', 'cut': 460, 'heat': 420, 'holding': True, 't': 1310},
        'pinch': {**base, 'phase': 'cut', 'cut': 610, 'heat': 860, 'holding': True, 'pinch': True, 't': 1310},
        'stall': {**base, 'phase': 'cut', 'cut': 700, 'heat': 1000, 'holding': True, 'stalled': True, 't': 2400},
        'ready': {**base, 'phase': 'cut', 'cut': 830, 'heat': 520, 'holding': True, 't': 1710},
        'fall': {**base, 'phase': 'fall', 'fallMs': 820},
        'fallen': {**base, 'phase': 'tree_result', 'fallMs': 1250, 'felled': [{'crooked': False}, {'crooked': False}], 'verdict': v_ok},
        'crooked': {**base, 'gap': gap2, 'index': 2, 'phase': 'tree_result', 'aim': miss, 'crooked': True, 'fallMs': 1400,
                    'felled': [{'crooked': False}, {'crooked': False}, {'crooked': True}], 'verdict': {'text': 'Легло криво · 380', 'tone': 'bad'}},
        'summary': {**base, 'index': 4, 'phase': 'over', 'aim': gap['center'], 'fallMs': 2000,
                    'felled': [{'crooked': False}, {'crooked': False}, {'crooked': True}, {'crooked': False}, {'crooked': False}]},
    }


def html_attrs(night, hc):
    return (' data-farm-theme="night"' if night else '') + (' data-qw-contrast="1"' if hc else '')


def fell_page(state_name, st, night, hc, card_svg, saw_symbol):
    label, cls = BUTTON[state_name]
    status, bad = STATUS[state_name]
    st = {**st, 'night': night, 'contrast': hc}
    forecast = 'Бонус до ×1,6 к древесине' if state_name == 'aim' else 'Прогноз: ×1,5 древесины'
    summary = ''
    if state_name == 'summary':
        summary = f'''<div class="fg-result" role="dialog" aria-label="Итог делянки"><h2>Делянка готова</h2>
<div class="lj-sum"><svg viewBox="0 0 40 40" aria-hidden="true"><use href="/files/icons-preview.svg#wood"/></svg><div><div class="lj-big">15 древесины</div><div class="fg-compare">база 10 · ×1,5 за ручную работу</div></div></div>
<ol class="lj-trees"><li>1. Легло ровно · 930</li><li>2. Легло ровно · 880</li><li class="bad">3. Легло криво · 380</li><li>4. Легло, пила глохла · 610</li><li>5. Легло ровно · 960</li></ol>
<p class="fg-proud">Оценка 752 из 1000 — Степан доволен.</p><div class="qw-btn-stack"><button class="primary wide qw-btn" type="button">Забрать древесину</button></div></div>'''
    disabled = ' disabled' if state_name in ('fall', 'fallen', 'crooked', 'summary') else ''
    return f'''<!doctype html><html lang="ru"{html_attrs(night, hc)}><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="stylesheet" href="/app/shell/qw-tokens.css"><link rel="stylesheet" href="/app/shell/qw-shell.css"><link rel="stylesheet" href="/static/style.css">
<style>{EXTRA_CSS}</style><body class="fg-open">
<div class="fg-overlay tg-overlay" role="dialog" aria-modal="true" aria-label="Валка: Делянка">
<div class="fg-top"><strong>Валка: Делянка</strong><span class="fg-timer">Осталось 13:42</span><button class="fg-close" type="button" aria-label="Закрыть игру">×</button></div>
<div class="fg-stage tg-live"><canvas class="fg-canvas" tabindex="0"></canvas>{summary}</div>
<div class="fg-hud"><div class="fg-forecast">{forecast}</div><div class="fg-stat">Дерево {min(5, st['index'] + 1)} из 5 · свалено: {len(st.get('felled', []))}</div>
<p class="fg-help">{HELP}</p><div class="fg-status{' bad' if bad else ''}" role="status">{status}</div></div>
<div class="fg-controls tg-controls"><button class="fg-act primary tg-big {cls}" type="button"{disabled}>{label}</button><button class="fg-act" type="button">Без игры</button></div>
</div>
<script type="module">
import {{drawFellScene}} from '/static/lumberjack_art.js';
const st = {json.dumps(st, ensure_ascii=False)};
const cv = document.querySelector('.fg-canvas'), r = cv.parentElement.getBoundingClientRect(), dpr = window.devicePixelRatio || 1;
cv.width = Math.round(r.width * dpr); cv.height = Math.round(r.height * dpr);
const g = cv.getContext('2d'); g.setTransform(dpr, 0, 0, dpr, 0, 0);
drawFellScene(g, r.width, r.height, st);
</script></html>'''


def fish_page(plan, rules, now, night, hc):
    data = json.dumps({'plan': plan, 'rules': rules, 'now': now})
    return f'''<!doctype html><html lang="ru"{html_attrs(night, hc)}><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="stylesheet" href="/app/shell/qw-tokens.css"><link rel="stylesheet" href="/app/shell/qw-shell.css"><link rel="stylesheet" href="/static/style.css">
<style>.fg-canvas{{filter:var(--qw-scene-filter,none)}}</style><body>
<script type="module">
import {{openTripGame}} from '/static/trip_game.js';
const S = {data};
const trip = {{id: 't1', route: 'pond_bank', outputs: {{crucian: 3}}, game: {{kind: 'fish', state: 'open', plan: S.plan, expires_at: S.now + 822}}}};
openTripGame({{trip, route: {{name: 'Тихий пруд'}}, rules: S.rules, serverNow: () => S.now, itemName: id => ({{crucian: 'Карась'}}[id] || id),
  timeText: s => s + ' с', inventory: {{}}, journal: {{}}, onFinish: async () => true, tripNow: () => trip, onClose() {{}}}});
document.querySelector('.tg-intro .primary').click();
</script></html>'''


# ---------------------------------------------------------------- comparison sheets: farm on the left, new on the right
def fit(svg, k):
    """Same px per farm unit for every figure: height from the viewBox."""
    vb = re.search(r'viewBox="([-\d. ]+)"', svg)[1].split()
    return svg.replace('<svg ', f'<svg style="height:{float(vb[3]) * k:.0f}px;width:auto" ', 1)


def sheet(res, w, night, hc, fish_png, fell_pngs, icons_href, forest_card):
    ink, bg, panel = ('#eee8cc', '#1f3027', '#26392f') if night else ('#294633', '#f3f1e5', '#fbfaf3')
    narrow = w < 700
    card_d = res['card_night' if night else 'card_day']['svg']
    k = 1.25 if narrow else 2.6
    farm = {'player': fit(res['farm']['player'], k), 'crew': {n: fit(v, k) for n, v in res['farm']['crew'].items()}}
    fig = {n: fit(v, k) for n, v in res['figure']['one'].items()}
    farmer_saw = fit(res['figure']['farmerSaw'], k)
    use = lambda i, s=48: f'<svg width="{s}" height="{s}"><use href="{icons_href}#{i}"/></svg>'
    shots = ''.join(f'<figure><img src="frames/{n}" alt=""><figcaption>{cap}</figcaption></figure>' for n, cap in fell_pngs)
    mode = ('ночь' if night else 'день') + (' · контрастный режим' if hc else '')
    return f'''<!doctype html><html lang="ru"{html_attrs(night, hc)}><meta charset="utf-8"><title>Лесоруб Степан · превью</title>
<style>*{{box-sizing:border-box}}body{{margin:0;padding:{12 if narrow else 24}px;background:{bg};color:{ink};font:15px/1.45 system-ui,"Segoe UI",sans-serif}}
h1{{font-size:{20 if narrow else 26}px;margin:0 0 4px}}h2{{font-size:{16 if narrow else 19}px;margin:22px 0 8px}}h3{{font-size:13px;margin:0 0 6px;opacity:.85;text-transform:uppercase;letter-spacing:.05em}}
p{{margin:0 0 10px}}.pair{{display:grid;grid-template-columns:1fr 1fr;gap:{8 if narrow else 18}px}}.box{{background:{panel};border-radius:14px;padding:{6 if narrow else 12}px;overflow:hidden}}
.box img{{width:100%;display:block;border-radius:10px}}.row{{display:flex;flex-wrap:wrap;gap:{4 if narrow else 10}px;align-items:flex-end}}.row svg{{flex:none}}
.fig svg{{flex:none}}.card{{position:relative;width:100%;max-width:320px;border-radius:12px;overflow:hidden;border:1px solid #91a078}}.card svg{{display:block;width:100%;height:auto}}
.chip{{position:relative;width:104px;height:44px;border-radius:9px;overflow:hidden;border:1px solid #fff9e5;flex:none}}.chip svg{{width:100%;height:100%;display:block}}
.chip span{{position:absolute;left:4px;bottom:3px;padding:2px 4px;border-radius:7px;background:#fff9e8e8;color:#315744;font-size:12px;font-weight:750}}
.shots{{display:grid;grid-template-columns:repeat({2 if narrow else 4},1fr);gap:8px}}figure{{margin:0}}figure img{{width:100%;border-radius:10px;display:block;border:1px solid #91a07866}}figcaption{{font-size:12px;margin-top:3px}}
.note{{font-size:13px;opacity:.85}}</style>
<h1>Лесоруб Степан · «Делянка» · «Валка»</h1><p>{mode}. Превью для владельца: к игре не подключено. Слева — то, что уже рисует ферма, справа — новое.</p>
<h2>Персонажи</h2><div class="pair"><div class="box"><h3>Ферма</h3><img src="reference-{'night' if night else 'day'}.png" alt="">
<div class="row fig">{farm['player']}{farm['crew']['pooh']}{farm['crew']['krot']}</div></div>
<div class="box"><h3>Новое · Степан</h3><div class="row fig">{fig['stand']}{fig['point']}{fig['carry']}{fig['saw']}{farmer_saw}</div>
<p class="note">Стоит (пила в чехле на плече) · показывает · несёт пилу · пилит · фермер в мини-игре.</p></div></div>
<h2>Значки и портрет</h2><div class="pair"><div class="box"><h3>Ферма</h3><div class="row">{use('helper_hedgehog')}{use('helper_squirrel')}{use('avatar_hedgehog')}{use('avatar_magpie')}{use('wood', 40)}{use('forest', 40)}{use('avatar_hedgehog', 96)}</div></div>
<div class="box"><h3>Новое</h3><div class="row">{use('helper_lumberjack')}{use('helper_lumberjack', 35)}{use('avatar_lumberjack')}{use('avatar_lumberjack', 35)}{use('logging_plot', 40)}{use('chainsaw', 40)}{use('avatar_lumberjack', 96)}</div>
<p class="note">helper_lumberjack · avatar_lumberjack (портрет найма) · logging_plot · chainsaw</p></div></div>
<h2>Карточка</h2><div class="pair"><div class="box"><h3>Ферма · «Лес»</h3><div class="card">{forest_card}</div><div class="row" style="margin-top:8px"><div class="chip">{forest_card}<span>Лес</span></div></div></div>
<div class="box"><h3>Новое · «Делянка»</h3><div class="card">{card_d}</div><div class="row" style="margin-top:8px"><div class="chip">{card_d}<span>Делянка</span></div></div></div></div>
<h2>Мини-игра</h2><div class="pair"><div class="box"><h3>Ферма · «Рыбалка» (trip_game.js)</h3><img src="frames/{fish_png}" alt=""></div>
<div class="box"><h3>Новое · «Валка»</h3><img src="frames/{fell_pngs[0][0]}" alt=""></div></div>
<h2>«Валка» по шагам</h2><div class="shots">{shots}</div>
<p class="note">Кнопка «Пилить» — нижняя, во всю ширину, высота ≥ 64 px (класс tg-big рыбалки). Числа и тексты — образец; исход считает сервер по журналу.</p></html>'''


CAPS = [('aim', 'Прицел: метка на дуге, жёлтый просвет'), ('cut', 'Пропил: держи, цепь греется'), ('pinch', 'Зажим — отпусти'),
        ('stall', 'Пила заглохла'), ('ready', 'Пропил у отметки — отпусти'), ('fall', 'Дерево падает'), ('fallen', 'Легло ровно'),
        ('crooked', 'Легло криво'), ('summary', 'Итог делянки ×1,5')]


def install_icons(symbols):
    path = harness.STATIC / 'icons.svg'
    src = path.read_text(encoding='utf-8')
    for sid in ICON_IDS:
        sym = symbols[sid]
        pat = re.compile(r'<symbol id="%s".*?</symbol>' % re.escape(sid), re.S)
        if pat.search(src):
            src = pat.sub(lambda m: sym, src, count=1)
        else:
            i = src.rindex('</defs>')
            src = src[:i] + sym + '\n' + src[i:]
    ET.fromstring(src)
    path.write_text(src, encoding='utf-8')
    return hashlib.sha256(src.encode()).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', type=Path, default=ROOT / '.local' / 'lumberjack-art')
    ap.add_argument('--icons', action='store_true', help='add/refresh the symbols in qw_farm/static/icons.svg')
    ap.add_argument('--quick', action='store_true', help='390×844 only')
    args = ap.parse_args()
    out = args.out.resolve()
    if os.name == 'nt' and out.drive.upper() != 'F:':
        raise SystemExit('Preview output must be on F:')
    (out / 'frames').mkdir(parents=True, exist_ok=True)
    (out / 'svg').mkdir(exist_ok=True)

    first = harness.run('lumberjack/build.js', {})
    second = harness.run('lumberjack/build.js', {})
    if first != second:
        raise RuntimeError('generator output is not deterministic')
    res = first
    vectors = {**{f'symbol-{k}.svg': v for k, v in res['symbols'].items()},
               'card-day.svg': res['card_day']['svg'], 'card-night.svg': res['card_night']['svg'],
               'card-day-inner.svg': res['card_day']['inner'], 'card-night-inner.svg': res['card_night']['inner'],
               'stepan.svg': res['figure']['sprite'], **{f'stepan-{k}.svg': v for k, v in res['figure']['one'].items()},
               'farmer-saw.svg': res['figure']['farmerSaw']}
    manifest = {'status': 'preview_only_owner_review_required', 'runtime_installed': False, 'vectors': {}, 'frames': []}
    for name, svg in vectors.items():
        doc = svg if svg.startswith('<svg') else f'<svg xmlns="http://www.w3.org/2000/svg">{svg}</svg>'
        if name.startswith('symbol-'):
            doc = f'<svg xmlns="http://www.w3.org/2000/svg"><defs>{svg}</defs></svg>'
        root = ET.fromstring(doc)
        assert not root.findall('.//{http://www.w3.org/2000/svg}image') and 'data:image' not in svg and '<filter' not in svg, name
        (out / 'svg' / name).write_text(svg, encoding='utf-8')
        manifest['vectors'][name] = {'bytes': len(svg.encode()), 'sha256': hashlib.sha256(svg.encode()).hexdigest()}
    (out / 'reference-day.png').write_bytes(res['reference_day'])
    (out / 'reference-night.png').write_bytes(res['reference_night'])
    # a private icons sprite for the sheets: the live icons.svg plus the new symbols (so the sheet works before --icons)
    icons = (harness.STATIC / 'icons.svg').read_text(encoding='utf-8')
    for sid in ICON_IDS:
        icons = re.sub(r'<symbol id="%s".*?</symbol>' % sid, '', icons, flags=re.S)
    i = icons.rindex('</defs>')
    (out / 'icons-preview.svg').write_text(icons[:i] + ''.join(res['symbols'][s] for s in ICON_IDS) + icons[i:], encoding='utf-8')
    if args.icons:
        manifest['icons_svg_sha256'] = install_icons(res['symbols'])
        manifest['icons_installed'] = list(ICON_IDS)

    app = (harness.STATIC / 'app.js').read_text(encoding='utf-8')
    m = re.search(r"const FOREST_CARD_ART='([^']+)';", app)
    forest = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 160 68"><defs><linearGradient id="fsk" x2="0" y2="1"><stop stop-color="#dcebd1"/>'
              '<stop offset="1" stop-color="#f3eacb"/></linearGradient></defs><rect width="160" height="68" fill="url(#fsk)"/>' + m[1] + '</svg>')

    plan = TG.make_fell_plan('lumberjack-preview')
    states = fell_states(plan)
    rules = TG.public_rules()
    noon = int(datetime(2026, 10, 29, 13, 0, tzinfo=MSK).timestamp())
    late = int(datetime(2026, 10, 29, 23, 0, tzinfo=MSK).timestamp())
    saw_sym = res['symbols']['chainsaw'].replace('<symbol id="chainsaw" viewBox="0 0 40 40">', '').replace('</symbol>', '')
    shots = Shots({'/frames/': out / 'frames', '/files/': out})
    try:
        sizes = [(390, 844)] if args.quick else SIZES
        for w, h in sizes:
            for night in (False, True):
                for hc in (False, True):
                    tag = f'{w}x{h}-' + ('night' if night else 'day') + ('-hc' if hc else '')
                    fish_plan = TG.make_fish_plan('lumberjack-preview', 'pond_bank', late if night else noon)
                    fish_name = f'fish-{tag}.png'
                    shots.shot(fish_page(fish_plan, rules, late if night else noon, night, hc), out / 'frames' / fish_name, (w, h), wait_ms=900)
                    fells = []
                    for key, cap in CAPS:
                        name = f'fell-{key}-{tag}.png'
                        shots.shot(fell_page(key, states[key], night, hc, None, saw_sym), out / 'frames' / name, (w, h), wait_ms=150)
                        fells.append((name, cap)); manifest['frames'].append(name)
                    html = sheet(res, w, night, hc, fish_name, fells, '/files/icons-preview.svg', forest)
                    (out / f'compare-{tag}.html').write_text(html.replace('/files/', '').replace('src="frames/', 'src="frames/'), encoding='utf-8')
                    shots.shot(html.replace('src="reference-', 'src="/files/reference-').replace('src="frames/', 'src="/frames/'),
                               out / f'compare-{tag}.png', (w, h), full=True, wait_ms=200)
                    manifest['frames'].append(f'compare-{tag}.png')
    finally:
        shots.close()
    manifest['plan'] = {'seed': 'lumberjack-preview', 'tree1': plan['trees'][1], 'tree2': plan['trees'][2]}
    (out / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(out)


if __name__ == '__main__':
    main()
