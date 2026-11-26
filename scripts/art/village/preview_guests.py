"""Preview of the village guests (guests.js) for the owner's approval.

    python scripts/art/village/preview_guests.py

Writes into .local/village-generator/guests-preview/: a sheet with every guest ×5 next to two residents for scale, day and
night, and a row at game scale (1.11 CSS px per drawing unit, as the residents on a phone), each beside the emoji it
replaces. Checks two identical runs and that no figure carries raster or style. Nothing is written into qw_farm/static.
"""
from __future__ import annotations

import html
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import ROOT  # noqa: E402

HERE = Path(__file__).resolve().parent
OUT = ROOT / ".local" / "village-generator" / "guests-preview"
UNIT = 40 / 36   # resident figures in the game: 1.11 CSS px per drawing unit

# id -> (name, emoji now shown in the game); the order of app.js VILLAGE_VISITORS, then VILLAGE_EGGS
NAMES = {'bogatyr': ('Богатырь', '🛡️'), 'trader': ('Странствующий торговец', '🧳'), 'fisher': ('Рыбак Сом', '🎣'),
         'forester': ('Лесник Бор', '🌲'), 'teller': ('Сказитель', '📜'), 'crafter': ('Плотник Тёс', '🔨'),
         'traveler': ('Путница Веся', '🎒'), 'egg_dymok': ('Ёж Дымок', '🦔'), 'egg_shustrik': ('Мышь Шустрик', '🐭'),
         'egg_pushok': ('Барсук Пушок', '🦡'), 'egg_boryan': ('Лис Борян', '🦊'), 'egg_belyana': ('Сова Беляна', '🦉'),
         'egg_kroshka': ('Божья коровка Крошка', '🐞'), 'egg_sharik': ('Лягух Шарик', '🐸'),
         'egg_filya': ('Паучок Филя', '🕷️'), 'egg_makro': ('Бобёр Макро', '🦫')}
SCALE_REF = ['Агата', 'Филиныч']


def render() -> tuple[dict, dict]:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'probe.js').write_text(
        "import {guestSvgs} from '/shared/guests.js';import {residentSvgs} from '/shared/residents.js';"
        "export function render(){return {guests:guestSvgs(),residents:residentSvgs()};}", encoding='utf-8')
    previous = harness.GEN
    try:
        harness.GEN = OUT
        a = harness.run('probe.js', {}, mounts={'/shared/': HERE})
        b = harness.run('probe.js', {}, mounts={'/shared/': HERE})
    finally:
        harness.GEN = previous
    assert a == b, 'guest generation must be deterministic'
    assert set(a['guests']) == set(NAMES), set(a['guests']) ^ set(NAMES)
    for gid, svg in a['guests'].items():
        doc = ET.fromstring(svg)
        assert not doc.findall('.//{http://www.w3.org/2000/svg}image'), gid
        assert 'style=' not in svg and '<style' not in svg, gid
        (OUT / f'{gid}.svg').write_text(svg, encoding='utf-8')
    return a['guests'], a['residents']


def sheet(guests: dict, residents: dict, night: bool) -> str:
    bg, ink, ground = ('#26352e', '#e8e4d8', '#33463c') if night else ('#e9efd8', '#3b3a36', '#d9e4c0')
    big = 5
    cells = [f'<figure class="ref"><div class="fig" style="width:{36 * big}px;height:{54 * big}px">{residents[n]}</div>'
             f'<figcaption>{html.escape(n)}<br><small>житель, для масштаба</small></figcaption></figure>' for n in SCALE_REF]
    cells += [f'<figure><div class="fig" style="width:{36 * big}px;height:{54 * big}px">{guests[g]}</div>'
              f'<figcaption>{html.escape(name)}<br><small>сейчас: {emoji}</small></figcaption></figure>'
              for g, (name, emoji) in NAMES.items()]
    small = ''.join(f'<span class="small"><span class="emoji">{emoji}</span>'
                    f'<span class="fig" style="width:{36 * UNIT:.1f}px;height:{54 * UNIT:.1f}px">{guests[g]}</span></span>'
                    for g, (_, emoji) in NAMES.items())
    small += ''.join(f'<span class="small"><span class="fig" style="width:{36 * UNIT:.1f}px;height:{54 * UNIT:.1f}px">'
                     f'{residents[n]}</span></span>' for n in SCALE_REF)
    return f'''<!doctype html><meta charset="utf-8"><style>
body{{margin:0;padding:18px 22px;background:{bg};color:{ink};font:14px/1.25 system-ui,sans-serif}}
h1{{font-size:18px;margin:0 0 10px}} h2{{font-size:14px;margin:16px 0 6px;opacity:.8}}
.grid{{display:grid;grid-template-columns:repeat(9,{36 * big}px);gap:8px 14px}}
figure{{margin:0;text-align:center}} figure.ref{{opacity:.85}}
.fig{{display:inline-block;background:radial-gradient(ellipse 60% 9% at 50% 92%,{ground},transparent)}} .fig svg{{width:100%;height:100%}}
figcaption{{font-size:13px}} small{{opacity:.7}}
.row{{display:flex;gap:18px;align-items:flex-end;padding:10px 14px;background:{ground};border-radius:12px}}
.small{{display:inline-flex;align-items:flex-end;gap:2px}} .emoji{{font-size:20px;opacity:.6}}
</style><h1>Гости деревни — {"ночь" if night else "день"}</h1><div class="grid">{"".join(cells)}</div>
<h2>В масштабе игры (телефон): слева эмодзи, которое сейчас стоит вместо фигурки; в конце — жители</h2><div class="row">{small}</div>'''


def main() -> None:
    guests, residents = render()
    for night in (False, True):
        path = OUT / f'guests-{"night" if night else "day"}.png'
        harness.screenshot(sheet(guests, residents, night), path, (1720, 790))
        print(path)


if __name__ == '__main__':
    main()
