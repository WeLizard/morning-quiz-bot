/* Night Case mockups («Хозяин исчез из запертой библиотеки»): the weekly case screens drawn with the case's own art.
   Static markup on the real kit (qw-tokens, qw-shell, night-city.css, night-case.css) + mock.css (the proposed new parts).
   ?s=<screen id> shows one screen, ?c=1 the contrast mode; no ?s — the list. Text is the case's own; player names are examples. */
(function () {
'use strict';
const PACK = '/app/night/packs/701d7ecb7ab415b04dc05b095391a8f644ccfc6560d2c17c49956db5d9c1facd/assets/';
const WORLD = '/app/night/worlds/manor_lake/';
const SEALED = '/app/night/sealed/';
const SPRITE = '/app/night/shell/icons.svg';
const PALETTE_VARS = {page: '--nc-page', page_rgb: '--nc-page-rgb', surface: '--nc-surface', surface_2: '--nc-surface-2', line: '--nc-line',
    edge: '--nc-edge', accent_soft: '--nc-edge-soft', rule: '--nc-rule', text: '--nc-text', muted: '--nc-muted', accent: '--nc-accent',
    accent_hi: '--nc-accent-hi', accent_lo: '--nc-accent-lo', accent_ink: '--nc-accent-ink', accent_text: '--nc-accent-text',
    tint: '--nc-tint', btn: '--nc-btn', btn_text: '--nc-btn-text', field: '--nc-field', field_line: '--nc-field-line', plate: '--nc-plate',
    shadow: '--nc-shadow', investigation: '--nc-invest', independent: '--nc-indep'};
const CONTRAST_VARS = {line: '--nc-line-hc', edge: '--nc-edge-hc', muted: '--nc-muted-hc', accent_text: '--nc-accent-text-hc',
    shadow: '--nc-shadow-hc', investigation: '--nc-invest-hc'};

const face = (id, look) => `${PACK}character_${id}${look ? '__' + look : ''}.webp`;
const place = (id, time) => `${PACK}location_${id}_${time}.webp`;
const item = name => `${PACK}item_i_${name}.webp`;
const scene = id => `${PACK}scene_${id}.webp`;
const esc = value => String(value).replace(/[&<>"]/g, ch => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[ch]));
const ic = (name, cls = '') => `<span class="ic ${cls}" aria-hidden="true"><svg viewBox="0 0 24 24"><use href="${SPRITE}#nc-i-${name}"/></svg></span>`;
const tick = () => `<span class="tick" aria-hidden="true"><svg viewBox="0 0 24 24"><use href="${SPRITE}#nc-i-check"/></svg></span>`;

/* ---------- the case (content/night_city/manor_lake.case.json) ---------- */
const HEROES = [
    {id: 'housekeeper', title: 'Экономка', looks: [['', 55, 'f'], ['f62', 62, 'f']]},
    {id: 'lawyer', title: 'Адвокат', looks: [['', 47, 'm'], ['m58', 58, 'm']]},
    {id: 'doctor', title: 'Домашний врач', looks: [['', 35, 'm'], ['f61', 61, 'f']]},
    {id: 'butler', title: 'Дворецкий', looks: [['', 58, 'm'], ['m40', 40, 'm']]},
    {id: 'maid', title: 'Горничная', looks: [['', 20, 'f'], ['f24', 24, 'f']]},
    {id: 'gardener', title: 'Садовник', looks: [['', 35, 'm'], ['m63', 63, 'm']]},
    {id: 'cook', title: 'Повар', looks: [['', 60, 'm'], ['f45', 45, 'f']]},
    {id: 'companion', title: 'Компаньонка', looks: [['', 35, 'f'], ['f58', 58, 'f']]},
    {id: 'niece_artist', title: 'Племянница-художница', looks: [['', 25, 'f'], ['f25b', 25, 'f']]},
    {id: 'nephew_gambler', title: 'Племянник-игрок', looks: [['', 25, 'm'], ['m25b', 25, 'm']]},
    {id: 'daughter', title: 'Дочь от первого брака', looks: [['', 35, 'f'], ['f35b', 35, 'f']]},
    {id: 'investigator', title: 'Следователь из города', looks: [['', 30, 'f'], ['m44', 44, 'm']]},
];
const PLACES = {main_hall: 'Главный зал', library: 'Библиотека', kitchen_wing: 'Кухонное крыло', winter_garden: 'Зимний сад',
    cellar: 'Погреб', boathouse: 'Лодочный домик', servants_quarters: 'Комнаты прислуги', tower_room: 'Бельведер'};
/* Seats of the example table: player name per hero (examples, not people). */
const TABLE = {gardener: {name: 'Ты', me: true}, housekeeper: {name: 'Вера'}, lawyer: {name: 'Олег'}, maid: {name: 'Кира'},
    nephew_gambler: {name: 'Лёша'}, investigator: {name: 'Саша', look: 'm44'}};
const years = n => `${n} ${n % 10 === 1 && n % 100 !== 11 ? 'год' : [2, 3, 4].includes(n % 10) && ![12, 13, 14].includes(n % 100) ? 'года' : 'лет'}`;

/* ---------- frame ---------- */
function header({eyebrow, title, back = true, clock = null}) {
    return `<header class="nc-bar">${back ? `<button class="qw-icon-btn qw-back" type="button" aria-label="Назад"><svg viewBox="0 0 24 24"><use href="${SPRITE}#nc-i-back"/></svg></button>` : ''}
<div class="nc-title"><small>${eyebrow}</small><h1>${title}</h1></div>
${clock ? `<span class="nc-clock" title="${esc(clock.title)}">${ic(clock.icon)}${clock.text}</span>` : ''}
<button class="qw-icon-btn qw-gear" type="button" aria-label="Меню"><svg viewBox="0 0 24 24"><use href="${SPRITE}#nc-i-gear"/></svg></button></header>`;
}
const TABS = [['place', 'house', 'Место'], ['self', 'seal', 'Досье'], ['board', 'lens', 'Улики'], ['chat', 'talk', 'Беседа'], ['history', 'calendar', 'Хроника']];
function tabs(current, badges = {}) {
    return `<nav class="ncase-nav" aria-label="Разделы дела">${TABS.map(([key, icon, label]) =>
        `<button type="button" ${key === current ? 'aria-current="page"' : ''}>${ic(icon)}<span>${label}</span>${badges[key] ? `<b class="ncase-badge" aria-label="новых: ${badges[key]}">${badges[key]}</b>` : ''}</button>`).join('')}</nav>`;
}
const CASE_CLOCK = {icon: 'hourglass', text: '5 ч 40 м', title: 'До конца окна 5'};
const caseHeader = (where) => header({eyebrow: 'Окно 5 из 14 · день 3', title: where, clock: CASE_CLOCK});
function dock(hint, buttons) {
    return `<div class="nc-dock"><div>${hint ? `<p class="nc-dock-hint">${hint}</p>` : ''}<div class="qw-btn-row">${buttons}</div></div></div>`;
}
const btn = (label, kind = '', extra = '') => `<button class="qw-btn ${kind}" type="button" ${extra}>${label}</button>`;
const card = (body, cls = '') => `<section class="nc-card ${cls}">${body}</section>`;
const head = (icon, title, count = '') => `<div class="nc-head">${ic(icon)}<h2 class="nc-h3">${title}</h2>${count ? `<span class="nc-count">${count}</span>` : ''}</div>`;
function hero({img, pos = '50% 40%', eyebrow, title, text, cls = '', extra = ''}) {
    return `<section class="nc-hero ${cls}" style="--img:url('${img}');--pos:${pos}"><div class="copy">
<span class="nc-eyebrow">${eyebrow}</span><h2>${title}</h2>${text ? `<p>${text}</p>` : ''}${extra}</div></section>`;
}
const faceImg = (id, look, cls = 'ncase-face') => `<img class="${cls}" src="${face(id, look)}" alt="">`;

/* ---------- 01 the case of the week ---------- */
function entry() {
    return `${header({eyebrow: 'Ночной город', title: 'Пятничный стол', back: true})}
<main class="nc-main has-dock">
${hero({img: `${WORLD}scene_cover.webp`, cls: 'tall', eyebrow: 'Дело недели · Усадьба у озера', title: 'Хозяин исчез из запертой библиотеки',
        text: 'Декабрь 1930-х. Усадьбу у замёрзшего озера отрезала метель. Телефон не работает, генератор даёт перебои. Мистики нет.',
        extra: `<div class="ncase-facts"><span class="nc-tag">${ic('calendar')}7 дней · 14 окон</span><span class="nc-tag">${ic('people')}3–12 игроков</span><span class="nc-tag">${ic('eye')}без мистики</span></div>`})}
<div class="nc-col">
${card(`<div class="ncase-case">
<img class="ncase-case-back" src="${WORLD}back_case.webp" alt="Рубашка дела: усадьба у озера">
<div><span class="nc-eyebrow">Сбор открыт</span><strong>Пятничный стол</strong>
<span class="nc-muted">За столом 6 из 12. Невзятых героев ведёт игра.</span>
<div class="ncase-faces">${['housekeeper', 'lawyer', 'maid', 'nephew_gambler', 'investigator'].map(id => faceImg(id, TABLE[id].look || '', 'ncase-face sm')).join('')}<span class="ncase-more">+1</span></div></div></div>`)}
${card(`${head('story', 'Как идёт дело')}
<ol class="ncase-how">
<li><img src="${place('library', 'evening')}" alt=""><div><strong>Ходи по усадьбе</strong><span>Восемь мест, у каждого утро, день, вечер и ночь. Переход и осмотр тратят действия окна.</span></div></li>
<li><img src="${item('s1_06_tagged_key')}" alt="" class="obj"><div><strong>Находи улики</strong><span>Находки видишь только ты, пока не опубликуешь их на доске дела.</span></div></li>
<li><img src="${WORLD}scene_vote.webp" alt=""><div><strong>Докажи на слушании</strong><span>В конце недели каждый называет, кто вывел и скрывал хозяина, и прикладывает улики.</span></div></li>
</ol>`)}
</div>
</main>
${dock('Твоё место за столом сохранится, пока идёт сбор', btn('Пригласить') + btn('К столу', 'primary'))}`;
}

/* ---------- 02 gathering: choose a hero ---------- */
function heroCard(h, {picked = false} = {}) {
    const seat = TABLE[h.id];
    const look = seat?.look ? h.looks.find(row => row[0] === seat.look) : h.looks[0];
    const taken = seat && !seat.me;
    const state = seat?.me ? 'mine' : taken ? 'taken' : '';
    const ages = h.looks.map(row => row[1]);
    const meta = seat ? years(look[1]) : `${[...new Set(ages)].map(years).join(' или ')}`;
    return `<button class="ncase-hero ${state}" type="button" ${seat?.me || picked ? 'aria-pressed="true"' : ''} ${taken ? 'disabled' : ''}>
<span class="pic"><img src="${face(h.id, look[0])}" alt="">${seat ? `<span class="ncase-plate">${seat.me ? 'ты' : esc(seat.name)}</span>` : ''}${seat?.me ? tick() : ''}</span>
<span class="cap"><span class="nm">${h.title}</span><span class="sub">${meta}${!seat && h.looks.length > 1 ? ' · 2 облика' : ''}</span></span></button>`;
}
function lobby() {
    return `${header({eyebrow: 'Сбор игроков · Пятничный стол', title: 'Хозяин исчез'})}
<main class="nc-main has-dock">
${hero({img: `${WORLD}scene_lobby_evening.webp`, cls: 'short nc-span', eyebrow: 'За столом 6 из 12', title: 'Выбери, кем войдёшь в усадьбу',
        text: 'Невзятых героев ведёт игра. Кто скрывает правду, решает только правда дела — не выбор героя.'})}
${card(`${head('people', 'Герои дела', 'свободно 6')}
<div class="ncase-heroes">${HEROES.map(h => heroCard(h)).join('')}</div>
<div class="ncase-anyseat"><img src="${WORLD}back_role.webp" alt=""><div><strong>Любое свободное место</strong><span class="nc-muted">Героя выберет игра при старте.</span></div>${btn('Сесть', 'compact')}</div>`, 'nc-span')}
</main>
${dock('Ты — Садовник, 35 лет · ещё не готов', btn('Встать') + btn('Я готов', 'primary'))}`;
}
function looks() {
    const cook = HEROES.find(h => h.id === 'cook');
    return `${header({eyebrow: 'Сбор игроков · Пятничный стол', title: 'Облик героя'})}
<main class="nc-main has-dock">
${card(`<span class="nc-eyebrow">Повар</span><h2 class="nc-h3">Каким будет этот герой?</h2>
<p class="nc-muted">Полный, седой, улыбчивый; белый фартук поверх жилета. Командует кухней как генерал. Облик меняет портрет, возраст и обращение — не роль в деле.</p>
<div class="ncase-looks">${cook.looks.map(([look, age, g], i) => `<button class="ncase-look" type="button" ${i === 0 ? 'aria-pressed="true"' : ''}>
<span class="pic"><img src="${face('cook', look)}" alt="">${i === 0 ? tick() : ''}</span><span class="cap"><span class="nm">${g === 'f' ? 'Она' : 'Он'}, ${years(age)}</span><span class="sub">${g === 'f' ? 'обращаться «она»' : 'обращаться «он»'}</span></span></button>`).join('')}</div>`, 'nc-span')}
</main>
${dock('', btn('Любой облик') + btn('Сесть: Повар, 60 лет', 'primary'))}`;
}

/* ---------- 03 the role, first open ---------- */
function role() {
    return `${header({eyebrow: 'Дело началось · окно 1', title: 'Твоя роль'})}
<main class="nc-main has-dock ncase-reveal">
<div class="ncase-rolewrap nc-span">
<figure class="ncase-rolecard">
<span class="face"><img src="${face('gardener')}" alt="Портрет: Садовник"></span>
<img class="frame" src="${WORLD}frame_hero.webp" alt="">
<figcaption><span class="eyebrow">Видишь только ты</span><strong>Садовник</strong><span class="side"><img src="${WORLD}emblem_shadow.webp" alt="">Знак Тени</span></figcaption>
</figure>
<div class="ncase-role-copy">
${card(`${head('seal', 'Твоя тайна')}<p class="nc-lead">В кадке зимнего сада ты закопал чужой предмет: велели спрятать и забыть.</p>
<p class="nc-muted">Знак Тени: тебе есть что скрывать от остальных.</p>`)}
${card(`${head('laurel', 'Твоя цель')}<p class="nc-lead">Дождаться конца метели и незаметно выкопать.</p>
<p class="nc-muted">Засчитывается, если после оттепели ты сам выкопаешь предмет раньше, чем кто-то опубликует карточку о тайнике.</p>`)}
</div></div>
</main>
${dock('Досье всегда открыто во вкладке «Досье»', btn('Понятно, в усадьбу', 'primary'))}`;
}

/* ---------- 04 place: the main screen ---------- */
function actTile(img, label, {pressed = false, obj = true, sub = ''} = {}) {
    return `<button class="ncase-act" type="button" ${pressed ? 'aria-pressed="true"' : ''}><img class="${obj ? 'obj' : 'face'}" src="${img}" alt=""><span><span class="nm">${label}</span>${sub ? `<span class="sub">${sub}</span>` : ''}</span>${pressed ? tick() : ''}</button>`;
}
function placeTile(id, time, who) {
    return `<button class="ncase-go" type="button"><img src="${place(id, time)}" alt=""><span class="cap"><span class="nm">${PLACES[id]}</span>${who ? `<span class="sub">${who}</span>` : ''}</span></button>`;
}
function person(id, look, name, sub, {npc = false} = {}) {
    return `<li class="ncase-person${npc ? ' npc' : ''}">${faceImg(id, look)}<span class="nm">${name}</span><span class="sub">${sub}</span></li>`;
}
function ap(left, total) {
    return `<span class="ncase-ap" aria-label="Действий осталось: ${left} из ${total}">${Array.from({length: total}, (_, i) => `<i class="${i < left ? 'on' : ''}"></i>`).join('')}<b>${left} из ${total} действий</b></span>`;
}
function placeScreen() {
    return `${caseHeader('Главный зал')}
${tabs('place', {board: 2, chat: 3})}
<main class="nc-main has-dock">
${hero({img: place('main_hall', 'evening'), cls: 'nc-span ncase-place', eyebrow: 'Вечер · ты здесь', title: 'Главный зал',
        text: 'Двусветный зал с камином, портретами предков и длинным обеденным столом. Здесь собираются все и произносятся самые неудобные фразы.',
        extra: ap(3, 4)})}
<div class="nc-col">
${card(`<div class="ncase-event"><img src="${scene('ev_blizzard')}" alt="Метель над озером"><div><span class="nc-eyebrow">Сейчас в усадьбе</span>
<p>Метель закрыла дорогу к лодочному на три окна.</p></div></div>`)}
${card(`${head('people', 'Кто рядом', '3')}
<ul class="ncase-people">${person('butler', '', 'Дворецкий', 'собеседник', {npc: true})}${person('housekeeper', '', 'Экономка', 'Вера')}${person('lawyer', '', 'Адвокат', 'Олег')}</ul>`)}
${card(`${head('door', 'Куда пойти', '1 действие')}
<div class="ncase-map">${placeTile('library', 'evening', '')}${placeTile('kitchen_wing', 'evening', '2 героя')}${placeTile('winter_garden', 'evening', '')}${placeTile('servants_quarters', 'evening', '1 герой')}${placeTile('tower_room', 'evening', '')}</div>`)}
</div>
<div class="nc-col">
${card(`${head('lens', 'Осмотреть', '1 действие')}
<div class="ncase-acts">
${actTile(item('s1_05_door_lock'), 'Осмотр библиотеки')}
${actTile(item('s1_06_tagged_key'), 'Ключ сервисной панели', {pressed: true})}
${actTile(item('s2_06_ledger_page'), 'Регистрационная копия')}
${actTile(item('c1_06_hunting_horn'), 'Узел на роге')}
${actTile(item('s2_02_folded_letter'), 'Образец руки хозяина')}
${actTile(item('s1_08_locked_box'), 'Место домашней кассы')}
</div>`)}
${card(`${head('talk', 'Поговорить и прочитать', '1 действие')}
<div class="ncase-acts">
${actTile(face('butler'), 'Дворецкий', {obj: false, sub: 'собеседник'})}
${actTile(item('s2_01_paper_fragment'), 'Слова дворецкого', {sub: 'записанная версия'})}
${actTile(item('s5_04_magnifier'), 'Уход по льду', {sub: 'записанная версия'})}
</div>`)}
</div>
</main>
${dock('Осмотреть: Ключ сервисной панели · 1 из 3 действий', btn('Отмена') + btn('Осмотреть', 'primary'))}`;
}

/* ---------- 05 dossier tab ---------- */
function dossier() {
    return `${caseHeader('Досье')}
${tabs('self', {board: 2, chat: 3})}
<main class="nc-main">
<div class="nc-col">
${card(`<div class="ncase-me">${faceImg('gardener', '', 'ncase-face lg')}<div><span class="nc-eyebrow">Видишь только ты</span><strong>Садовник, 35 лет</strong>
<span class="ncase-side"><img src="${WORLD}emblem_shadow.webp" alt="">Знак Тени</span></div></div>
<p class="nc-muted">Крепкий, лет тридцати пяти: кепка, рабочая куртка, перчатки. Пахнет землёй даже в декабре. Говорит мало: «Оно конечно», «ну, как сказать».</p>`)}
${card(`${head('laurel', 'Цель')}<p class="nc-lead">Дождаться конца метели и незаметно выкопать.</p>
<div class="ncase-steps"><span class="on">${ic('check')}Метель идёт</span><span>${ic('hourglass')}Оттепель</span><span>${ic('key')}Выкопать</span></div>
<p class="nc-muted">Засчитывается, если после оттепели ты сам выкопаешь предмет раньше, чем кто-то опубликует карточку о тайнике.</p>`)}
</div>
<div class="nc-col">
${card(`${head('seal', 'Тайна')}<div class="ncase-secret"><img src="${place('winter_garden', 'night')}" alt="Зимний сад ночью"><p>В кадке зимнего сада ты закопал чужой предмет: велели спрятать и забыть.</p></div>`)}
${card(`${head('papers', 'Твои находки', '3')}
<div class="ncase-shelf">${[['s1_06_tagged_key', 'Ключ сервисной панели'], ['s3_06_bootprint', 'Следы на льду'], ['s7_03_scarf', 'Шарф врача']].map(([pic, label]) =>
        `<figure class="ncase-mini"><span class="nc-evidence-art"><span class="nc-evidence-plate"><img class="pic" src="${item(pic)}" alt=""></span><img class="frame" src="${WORLD}frame_evidence.webp" alt=""></span><figcaption>${label}</figcaption></figure>`).join('')}</div>`)}
</div>
</main>`;
}

/* ---------- 06 board ---------- */
function evidence(pic, title, {kind = 'proof', by = '', text = '', action = ''} = {}) {
    return `<figure class="nc-evidence ncase-evi">
<span class="nc-evidence-art"><span class="nc-evidence-plate"><img class="pic" src="${item(pic)}" alt=""></span><img class="frame" src="${WORLD}frame_evidence.webp" alt=""></span>
<figcaption><span class="nc-evidence-kind ${kind}">${kind === 'proof' ? 'Доказательство' : 'Утверждение'}</span><strong>${title}</strong>
${by ? `<span class="meta">${by}</span>` : ''}${text ? `<p>${text}</p>` : ''}${action}</figcaption></figure>`;
}
function board() {
    return `${caseHeader('Улики')}
${tabs('board', {chat: 3})}
<main class="nc-main">
<div class="nc-col">
${card(`${head('lens', 'Доска дела', '4 записи')}
<p class="nc-muted">Для обвинения нужны опубликованные доказательства. Слова и версии игроков остаются утверждениями.</p>
${evidence('s1_05_door_lock', 'Осмотр библиотеки', {by: 'Опубликовала Вера · окно 2', text: 'Ключ оставался изнутри; планку сняли при домашних. Окно заперто, снег под ним нетронут.'})}
${evidence('s2_06_ledger_page', 'Журнал ключей', {by: 'Опубликовал Олег · окно 3', text: 'Старый журнал фиксирует выдачи сервисных ключей; рядом расписка адвоката.'})}
${evidence('s7_03_scarf', 'Шарф врача', {by: 'Опубликовала Кира · окно 4', text: 'Квитанция починки подтверждает, чей это шарф. Это не след хозяина.'})}
${evidence('s3_06_bootprint', 'Хозяин ушёл по льду', {kind: 'claim', by: 'Версия Лёши · окно 4', text: 'Следы к дороге — значит, он сам ушёл через озеро.'})}`)}
</div>
<div class="nc-col">
${card(`${head('papers', 'Твои находки', 'видишь только ты')}
${evidence('s1_06_tagged_key', 'Ключ сервисной панели', {by: 'Главный зал · окно 5', text: 'На запасном ключе бирка старой мастерской: сервисная панель библиотеки.',
        action: `<div class="qw-btn-row ncase-evi-act">${btn('Опубликовать', 'compact')}</div>`})}
${evidence('c1_06_hunting_horn', 'Узел на роге', {by: 'Главный зал · окно 3', text: 'На шнурке охотничьего рога свежий двойной узел.',
        action: `<div class="qw-btn-row ncase-evi-act">${btn('Опубликовать', 'compact')}</div>`})}`)}
${card(`${head('story', 'Добавить версию')}<textarea class="nc-field ncase-draft" rows="3" placeholder="Например: ключ панели выдавали по журналу — сверить с распиской"></textarea>
<div class="qw-btn-row">${btn('Опубликовать версию')}</div>`)}
</div>
</main>`;
}

/* ---------- 07 chat ---------- */
function msg(id, look, who, text, {mine = false} = {}) {
    if (mine) return `<div class="nc-msg mine"><div class="bub"><p>${text}</p></div></div>`;
    return `<div class="nc-msg">${faceImg(id, look, 'ncase-face xs')}<div class="bub"><span class="who">${who}</span><p>${text}</p></div></div>`;
}
function chat() {
    return `${caseHeader('Беседа')}
${tabs('chat', {board: 2})}
<main class="nc-main has-dock ncase-chatmain">
<div class="nc-span ncase-channels qw-btn-group" role="group" aria-label="Беседа">
<button type="button" aria-pressed="true">${ic('people')}Площадь</button>
<button type="button" aria-pressed="false">${ic('lock')}Приватно · 1 действие</button>
</div>
${card(`<div class="nc-chat">
<span class="nc-sys">${ic('hourglass')}Открылось окно 5 · вечер</span>
${msg('housekeeper', '', 'Вера · Экономка', 'Ключ оставался изнутри, планку снимали при всех. Я сама держала лампу.')}
${msg('nephew_gambler', '', 'Лёша · Племянник-игрок', 'Старина просто ушёл по льду, бросьте. Следы же видели.')}
${msg('investigator', 'm44', 'Саша · Следователь из города', 'Следы видели. Чьи они — не проверяли. Прошу не спешить.')}
${msg('', '', '', 'В главном зале на конторке лежит запасной ключ с биркой. Кто его туда положил?', {mine: true})}
${msg('lawyer', '', 'Олег · Адвокат', 'Если позволите, ключи — дело экономки. Журнал у неё.')}
</div>`, 'nc-span')}
</main>
<div class="nc-dock ncase-compose"><div><p class="nc-dock-hint">Площадь видят все за столом · осталось 4 сообщения в этом окне</p>
<div class="nc-compose"><textarea class="nc-field" rows="1" placeholder="Сообщение"></textarea>${btn('Отправить', 'primary')}</div></div></div>`;
}

/* ---------- 08 chronicle ---------- */
function track() {
    const days = Array.from({length: 7}, (_, d) => `<span class="day${d === 2 ? ' now' : ''}"><i class="${d < 2 ? 'done' : d === 2 ? 'done' : ''}"></i><i class="${d < 2 ? 'done' : ''}${d === 2 ? ' cur' : ''}"></i><b>${d + 1}</b></span>`).join('');
    return `<div class="ncase-track" aria-label="Окно 5 из 14">${days}</div>`;
}
function chron(img, when, text, {obj = false} = {}) {
    return `<li><img class="${obj ? 'obj' : ''}" src="${img}" alt=""><div><span class="when">${when}</span><p>${text}</p></div></li>`;
}
function history() {
    return `${caseHeader('Хроника')}
${tabs('history', {board: 2, chat: 3})}
<main class="nc-main">
${card(`${head('calendar', 'Неделя дела', 'день 3 из 7')}${track()}<p class="nc-muted">Два окна в день: утром и вечером. Итоговое слушание — в окне 14.</p>`, 'nc-span')}
<div class="nc-col">
${card(`${head('house', 'Общий ход дела')}
<ul class="ncase-chron">
${chron(scene('ev_scarf'), 'Окно 4', 'В зимнем саду найден забытый шарф. Принадлежность нужно проверить.')}
${chron(scene('ev_generator'), 'Окно 3', 'Генератор заглох: лестница в башню временно закрыта.')}
${chron(scene('ev_blizzard'), 'Окно 2', 'Метель закрыла дорогу к лодочному на три окна.')}
${chron(`${WORLD}scene_title.webp`, 'Окно 1', 'Утром дверь библиотеки открыли при домашних. Хозяина нет.')}
</ul>`)}
</div>
<div class="nc-col">
${card(`${head('seal', 'Твои события')}
<ul class="ncase-chron">
${chron(item('s1_06_tagged_key'), 'Окно 5', 'Находка: «Ключ сервисной панели».', {obj: true})}
${chron(place('servants_quarters', 'day'), 'Окно 4', 'Ты перешёл в комнаты прислуги.')}
${chron(item('c1_06_hunting_horn'), 'Окно 3', 'Находка: «Узел на роге».', {obj: true})}
</ul>`)}
</div>
</main>`;
}

/* ---------- 09 final hearing ---------- */
const SUSPECTS = [['lawyer', '', 'Адвокат', 'Олег'], ['housekeeper', '', 'Экономка', 'Вера'], ['butler', '', 'Дворецкий', 'игра'], ['hunter', '', 'Охотник', 'игра'],
    ['watchman', '', 'Сторож', 'игра'], ['nephew_gambler', '', 'Племянник', 'Лёша'], ['maid', '', 'Горничная', 'Кира'], ['owner', '', 'Хозяин сам', 'без помощников']];
function hearing() {
    return `${header({eyebrow: 'Окно 14 · итоговое слушание', title: 'Хозяин исчез', clock: {icon: 'scales', text: '2 ч 10 м', title: 'До закрытия слушания'}})}
<main class="nc-main has-dock">
${hero({img: `${WORLD}scene_vote.webp`, pos: '50% 58%', cls: 'short nc-span', eyebrow: 'Итоговое слушание · сдали 4 из 6', title: 'Кто вывел и скрывал хозяина?',
        text: 'Если хозяин всё сделал сам, без помощников, назови его самого. Голос можно изменить, пока слушание не закрылось.'})}
${card(`${head('people', 'Твой выбор')}
<div class="ncase-suspects">${SUSPECTS.map(([id, look, title, who], i) => `<button class="ncase-suspect" type="button" ${i === 0 ? 'aria-pressed="true"' : ''}>
<span class="pic"><img src="${face(id, look)}" alt="">${i === 0 ? tick() : ''}</span><span class="nm">${title}</span><span class="sub">${who}</span></button>`).join('')}</div>`)}
${card(`${head('lens', 'Приложи улики', 'выбрано 2 из 5')}
<p class="nc-muted">Сервер проверит, хватает ли доказательств. Утверждения ключами не считаются.</p>
<div class="ncase-cites">
${[['s2_06_ledger_page', 'Журнал ключей', 'Олег', true], ['s1_06_tagged_key', 'Ключ сервисной панели', 'ты', true], ['s1_05_door_lock', 'Осмотр библиотеки', 'Вера', false],
        ['s7_03_scarf', 'Шарф врача', 'Кира', false], ['s3_06_bootprint', 'Хозяин ушёл по льду', 'версия Лёши', false, 'claim']].map(([pic, title, by, on, kind]) =>
        `<button class="ncase-cite${kind === 'claim' ? ' claim' : ''}" type="button" ${on ? 'aria-pressed="true"' : ''} ${kind === 'claim' ? 'disabled' : ''}>
<img src="${item(pic)}" alt=""><span><span class="nm">${title}</span><span class="sub">${kind === 'claim' ? 'утверждение · не считается' : `доказательство · ${by}`}</span></span><span class="box">${on ? tick() : ''}</span></button>`).join('')}
</div>`)}
</main>
${dock('Голос тайный до закрытия · его можно изменить', btn('Воздержаться') + btn('Отдать голос: Адвокат', 'primary'))}`;
}

/* ---------- 10 final ---------- */
function castRow(id, look, player, title, faction, result) {
    const emb = {shadow: ['emblem_shadow', 'Тень'], investigation: ['emblem_investigation', 'Следствие'], independent: ['emblem_independent', 'Сам за себя']}[faction];
    return `<li>${faceImg(id, look)}<div><span class="nm">${title}</span><span class="sub">${player}</span></div>
<span class="ncase-fac ${faction}"><img src="${WORLD}${emb[0]}.webp" alt="">${emb[1]}</span>${result}</li>`;
}
function finale() {
    const ok = `<span class="nc-tag ok">${ic('check')}цель</span>`, no = '<span class="nc-tag">не вышло</span>';
    return `${header({eyebrow: 'Дело закрыто · 7 дней', title: 'Хозяин исчез'})}
<main class="nc-main has-dock">
${hero({img: `${SEALED}f648a983a622cb099f3bd70623d2d2a39dbbda139ad5dfedf4102d05f295ff15.webp`, pos: '50% 45%', cls: 'tall nc-span',
        eyebrow: 'Исчезновение объяснено', title: 'Хозяин жив. Дом услышал правду',
        text: 'Адвокат организовал удержание хозяина, экономка помогла. Реестровые копии пережили судьбу оригинала.'})}
<div class="nc-col">
${card(`<div class="ncase-me">${faceImg('gardener', '', 'ncase-face lg')}<div><span class="nc-eyebrow">Твой итог</span><strong>Садовник · цель выполнена</strong>
<span class="nc-muted">После оттепели ты выкопал предмет раньше, чем о тайнике узнали.</span></div></div>`)}
${card(`${head('scales', 'Итоговое слушание')}<p class="nc-lead">Стол назвал Адвоката: 4 голоса из 6.</p>
<p class="nc-muted">Решили три доказательства: копия черновика, журнал ключей и записка у подпорки.</p>`)}
</div>
<div class="nc-col">
${card(`${head('people', 'Кто был кем', 'роли открыты')}
<ul class="ncase-cast">
${castRow('lawyer', '', 'Олег', 'Адвокат', 'shadow', no)}
${castRow('housekeeper', '', 'Вера', 'Экономка', 'investigation', no)}
${castRow('gardener', '', 'ты', 'Садовник', 'shadow', ok)}
${castRow('investigator', 'm44', 'Саша', 'Следователь из города', 'investigation', ok)}
${castRow('maid', '', 'Кира', 'Горничная', 'investigation', ok)}
${castRow('nephew_gambler', '', 'Лёша', 'Племянник-игрок', 'independent', no)}
</ul>`)}
</div>
</main>
${dock('', btn('Выйти') + btn('Новое дело', 'primary'))}`;
}

const SCREENS = [
    ['01_case', '1 Дело недели', entry, 'scene_cover'],
    ['02a_lobby', '2a Сбор · выбор героя', lobby, 'scene_lobby_evening'],
    ['02b_look', '2b Облик героя', looks, 'scene_lobby_evening'],
    ['03_role', '3 Твоя роль', role, 'scene_title'],
    ['04_place', '4 Место · Главный зал', placeScreen, null],
    ['05_dossier', '5 Досье', dossier, null],
    ['06_board', '6 Улики', board, null],
    ['07_chat', '7 Беседа', chat, null],
    ['08_history', '8 Хроника', history, null],
    ['09_hearing', '9 Итоговое слушание', hearing, 'scene_vote'],
    ['10_final', '10 Дело закрыто', finale, 'scene_finale'],
];
window.NC_SCREENS = SCREENS.map(([id, label]) => ({id, label}));

async function applyPalette(contrast) {
    const pack = await (await fetch(`${WORLD}pack.json`)).json();
    const style = document.documentElement.style;
    for (const [key, name] of Object.entries(PALETTE_VARS)) if (typeof pack.palette[key] === 'string') style.setProperty(name, pack.palette[key]);
    for (const [key, name] of Object.entries(CONTRAST_VARS)) if (typeof pack.palette.contrast?.[key] === 'string') style.setProperty(name, pack.palette.contrast[key]);
    if (contrast) document.documentElement.setAttribute('data-qw-contrast', '1');
}
async function main() {
    const query = new URLSearchParams(location.search);
    await applyPalette(query.get('c') === '1');
    const id = query.get('s');
    const screen = SCREENS.find(row => row[0] === id);
    const root = document.getElementById('content');
    if (!screen) {
        root.innerHTML = `${header({eyebrow: 'Макеты · 2026-11-21', title: 'Дело недели', back: false})}<main class="nc-main"><section class="nc-card nc-span"><ul class="nc-list">${SCREENS.map(([sid, label]) =>
            `<li><a class="ttl" href="?s=${sid}">${label}</a> · <a href="?s=${sid}&c=1">контраст</a></li>`).join('')}</ul></section></main>`;
    } else {
        const [, , render, page] = screen;
        document.documentElement.style.setProperty('--page-img', `url('${page ? `${WORLD}${page}.webp` : place('main_hall', 'evening')}')`);
        root.innerHTML = render();
    }
    await Promise.all([...document.images].map(img => img.decode().catch(() => null)));
    await document.fonts.ready;
    document.documentElement.dataset.ready = '1';
}
main();
})();
