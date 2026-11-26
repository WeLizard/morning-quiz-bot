/* Preview of the out-of-play portrait states (MQB-012, owner question B7): normal, removed, and three «killed» effects. */
(function () {
'use strict';
const PACK = '/app/night/packs/701d7ecb7ab415b04dc05b095391a8f644ccfc6560d2c17c49956db5d9c1facd/assets/';
const STATES = [
    ['', 'Обычный', 'в игре'],
    ['ncase-out', 'Отстранён', 'затемнён, как решено'],
    ['ncase-dead', 'Убит · А «Пепел»', 'серый, полупрозрачный, траурная лента', 'ash'],
    ['ncase-dead', 'Убит · Б «Вуаль»', 'холодная дымка медленно плывёт', 'veil'],
    ['ncase-dead', 'Убит · В «Свеча»', 'края выгорают, тёплое мерцание', 'candle'],
];
// The world's palette, as the case client sets it from pack.json (subset of PALETTE_VARS in mock.js).
const VARS = {page: '--nc-page', page_rgb: '--nc-page-rgb', surface: '--nc-surface', surface_2: '--nc-surface-2', line: '--nc-line', edge: '--nc-edge',
    accent_soft: '--nc-edge-soft', text: '--nc-text', muted: '--nc-muted', accent: '--nc-accent', accent_text: '--nc-accent-text', tint: '--nc-tint', indep: '--nc-indep'};
fetch('/app/night/worlds/manor_lake/pack.json').then(r => r.json()).then(pack => {
    for (const [key, name] of Object.entries(VARS)) if (typeof pack.palette[key] === 'string') document.documentElement.style.setProperty(name, pack.palette[key]);
}).catch(() => {});
const heroes = ['butler', 'housekeeper', 'lawyer', 'maid', 'gardener'];
const cards = document.getElementById('cards'), faces = document.getElementById('faces');
const el = (tag, cls, text) => { const node = document.createElement(tag); if (cls) node.className = cls; if (text) node.textContent = text; return node; };
STATES.slice(1).forEach(([cls, title, sub, death], i) => {
    const fig = el('figure');
    const card = el('div', 'ncase-hero'), pic = el('span', `pic ${cls}`.trim());
    if (death) pic.dataset.death = death;
    const img = el('img'); img.src = `${PACK}character_${heroes[i]}.webp`; img.alt = ''; pic.append(img);
    const cap = el('span', 'cap'); cap.append(el('span', 'nm', title), el('span', 'sub', sub));
    card.append(pic, cap); fig.append(card); cards.append(fig);
});
STATES.forEach(([cls, title, , death], i) => {
    const wrap = el('span', `ncase-faceframe ${cls}`.trim()); if (death) wrap.dataset.death = death;
    const img = el('img', 'ncase-face lg'); img.src = `${PACK}character_${heroes[i % heroes.length]}.webp`; img.alt = title; wrap.append(img);
    const fig = el('figure', 'ncase-person'); fig.append(wrap, el('span', 'nm', title)); faces.append(fig);
});
})();
