/* Night Case mockups («Хозяин исчез из запертой библиотеки»): the weekly case screens drawn with the case's own art.
   Static markup on the real kit (qw-tokens, qw-shell, night-city.css, night-case.css) + mock.css (the proposed new parts).
   Follows docs/tasks/night_city/NIGHT_CITY_MENU_DESIGN.md (2026-11-21): root, worlds, case card, gathering by heroes,
   the hero first with the player as a plate, side from the truth variant, one shared feed per world.
   ?s=<screen id> shows one screen, ?c=1 the contrast mode; no ?s — the list. Case text is the case's own;
   player names, look names and vote counts are examples. */
(function () {
'use strict';
const PACK = '/app/night/packs/701d7ecb7ab415b04dc05b095391a8f644ccfc6560d2c17c49956db5d9c1facd/assets/';
const WORLDS = '/app/night/worlds/';
const WORLD = `${WORLDS}manor_lake/`;
const SHELL = '/app/night/shell/';
const SEALED = '/app/night/sealed/';
const SPRITE = `${SHELL}icons.svg`;
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
/* The player plate (§3.4): the player's name, «ты», or «ведёт игра» for a hero nobody plays. */
const plate = who => who === 'ты' ? '<span class="ncase-tag me">ты</span>' : who === 'игра' ? '<span class="ncase-tag game">ведёт игра</span>' : `<span class="ncase-tag">${esc(who)}</span>`;

/* ---------- the case (content/night_city/manor_lake.case.json) ---------- */
const HEROES = [
    {id: 'housekeeper', title: 'Экономка', looks: [['', 55], ['f62', 62]]},
    {id: 'lawyer', title: 'Адвокат', looks: [['', 47], ['m58', 58]]},
    {id: 'doctor', title: 'Домашний врач', looks: [['', 35], ['f61', 61]]},
    {id: 'butler', title: 'Дворецкий', looks: [['', 58], ['m40', 40]]},
    {id: 'maid', title: 'Горничная', looks: [['', 20], ['f24', 24]]},
    {id: 'gardener', title: 'Садовник', looks: [['', 35], ['m63', 63]]},
    {id: 'cook', title: 'Повар', looks: [['', 60], ['f45', 45]]},
    {id: 'companion', title: 'Компаньонка', looks: [['', 35], ['f58', 58]]},
    {id: 'niece_artist', title: 'Племянница-художница', looks: [['', 25], ['f25b', 25]]},
    {id: 'nephew_gambler', title: 'Племянник-игрок', looks: [['', 25], ['m25b', 25]]},
    {id: 'daughter', title: 'Дочь от первого брака', looks: [['', 35], ['f35b', 35]]},
    {id: 'investigator', title: 'Следователь из города', looks: [['', 30], ['m44', 44]]},
];
/* Characters people never play: the game leads them always (§3.3). */
const NEVER = [['owner', 'Владелец усадьбы'], ['hunter', 'Старый друг-охотник'], ['watchman', 'Сторож'], ['chauffeur', 'Шофёр'],
    ['governess', 'Гувернантка'], ['granddaughter', 'Внучка-студентка'], ['priest', 'Сельский священник'], ['photographer', 'Фотограф-гость']];
const PLACES = {main_hall: 'Главный зал', library: 'Библиотека', kitchen_wing: 'Кухонное крыло', winter_garden: 'Зимний сад',
    cellar: 'Погреб', boathouse: 'Лодочный домик', servants_quarters: 'Комнаты прислуги', tower_room: 'Бельведер'};
/* Seats of the example table: player per hero (examples, not people). */
const TABLE = {gardener: {name: 'ты', me: true}, housekeeper: {name: 'Вера'}, lawyer: {name: 'Олег'}, maid: {name: 'Кира'},
    nephew_gambler: {name: 'Лёша'}, investigator: {name: 'Саша', look: 'm44'}};
const years = n => `${n} ${n % 10 === 1 && n % 100 !== 11 ? 'год' : [2, 3, 4].includes(n % 10) && ![12, 13, 14].includes(n % 100) ? 'года' : 'лет'}`;

/* ---------- frame ---------- */
function header({eyebrow, title, back = true, clock = null}) {
    return `<header class="nc-bar">${back ? `<button class="qw-icon-btn qw-back" type="button" aria-label="Назад"><svg viewBox="0 0 24 24"><use href="${SPRITE}#nc-i-back"/></svg></button>` : ''}
<div class="nc-title"><small>${eyebrow}</small><h1>${title}</h1></div>
${clock ? `<span class="nc-clock" title="${esc(clock.title)}">${ic(clock.icon)}${clock.text}</span>` : ''}
<button class="qw-icon-btn qw-gear" type="button" aria-label="Меню"><svg viewBox="0 0 24 24"><use href="${SPRITE}#nc-i-gear"/></svg></button></header>`;
}
/* Inside the case (§3.5): «Беседа» and the shared part of «Хроника» are one feed; the personal part lives in «Досье». */
const TABS = [['place', 'house', 'Место'], ['feed', 'talk', 'Гостиная'], ['board', 'lens', 'Улики'], ['self', 'seal', 'Досье']];
function tabs(current, badges = {}) {
    return `<nav class="ncase-nav" aria-label="Разделы дела">${TABS.map(([key, icon, label]) =>
        `<button type="button" ${key === current ? 'aria-current="page"' : ''}>${ic(icon)}<span>${label}</span>${badges[key] ? `<b class="ncase-badge" aria-label="новых: ${badges[key]}">${badges[key]}</b>` : ''}</button>`).join('')}</nav>`;
}
const CASE_CLOCK = {icon: 'hourglass', text: '5 ч 40 м', title: 'До конца окна 5'};
const caseHeader = where => header({eyebrow: 'Окно 5 из 14 · день 3, вечер', title: where, clock: CASE_CLOCK});
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
/* «Экономка» + plate: the hero first, the player beside (§3.4). */
const who = (title, player) => `<span class="ncase-who"><span class="nm">${title}</span>${plate(player)}</span>`;

/* ---------- 01 root «Ночной город» (§3.1) ---------- */
function root() {
    return `${header({eyebrow: 'QuizzyWizzy', title: 'Ночной город', back: false})}
<main class="nc-main has-dock">
${hero({img: `${SHELL}shell_entry_portrait.webp`, pos: '50% 45%', cls: 'nc-span', eyebrow: 'Детективы на неделю', title: 'Ночной город',
        text: 'Детективные истории в разных мирах: от усадьбы 1930-х до неонового 2089-го. Компания берёт дело и неделю живёт в нём: заходи, когда удобно, игра сама напишет, что случилось.'})}
<div class="nc-col">
${card(`${head('story', 'Твои дела', '1')}
<div class="ncase-mycase">
<span class="art"><img class="cover" src="${WORLD}back_case.webp" alt="">${faceImg('gardener', '', 'ncase-face sm')}</span>
<div><strong>Хозяин исчез</strong><span class="nc-muted">Садовник · Пятничный стол</span>
<span class="ncase-news">${ic('moon')}Вечер, окно 5 · 2 новых события, тебе записка</span></div></div>
<div class="qw-btn-stack">${btn('Вернуться в дело')}</div>`)}
${card(`${head('key', 'Войти по приглашению')}
<div class="nc-join"><input class="nc-field" placeholder="Код или ссылка" aria-label="Код или ссылка">${btn('Войти')}</div>`)}
</div>
<div class="nc-col">
${card(`${head('people', 'Открытые сборы', '1')}
<ul class="nc-list ncase-rows"><li><img class="thumb" src="${WORLD}thumb.webp" alt=""><div><span class="ttl">Северный клуб</span><span class="meta">Хозяин исчез · свободно 7 мест</span></div>${btn('Смотреть', 'compact')}</li></ul>`)}
${card(`${head('table', 'Твои компании', '2')}
<ul class="nc-list ncase-rows">
<li><img class="thumb" src="${WORLD}thumb.webp" alt=""><div><span class="ttl">Пятничный стол</span><span class="meta">6 человек · идёт дело, окно 5</span></div>${btn('Открыть', 'compact')}</li>
<li><img class="thumb" src="${WORLDS}night_express/thumb.webp" alt=""><div><span class="ttl">Дачники</span><span class="meta">4 человека · свободна</span></div>${btn('Открыть', 'compact')}</li>
</ul>`)}
</div>
</main>
${dock('', btn('Новое дело', 'primary'))}`;
}

/* ---------- 02 new case → worlds (§3.2) ---------- */
const WORLD_LIST = [['manor_lake', 'Усадьба у озера', '1930-е, зима', 'детектив «запертый дом»', 1], ['night_express', 'Ночной экспресс', '1936', 'шпионский детектив в поезде'],
    ['black_bay', 'Чёрная бухта', '1920-е', 'мистика в рыбацком городке'], ['neon_city', 'Неон-Сити', '2089', 'неонуар с сатирой'],
    ['newsprint_city', 'Газетный город', '1950-е'], ['palace_masks', 'Дворец масок', '1890-е'], ['polar_star', 'Полярная звезда', '1912'],
    ['circus', 'Цирк «Балаган»', '1900-е'], ['campus', 'Кампус', 'наши дни'], ['sand_city', 'Песчаный город', '1920-е, пустыня'],
    ['prohibition', 'Сухой закон', '1929'], ['deep_choir', 'Глубинный хор', '1930-е', '', 0, 16], ['dead_air', 'Мёртвый эфир', 'конец 1990-х', '', 0, 16],
    ['velvet_circle', 'Бархатный круг', 'наши дни', '', 0, 18], ['eternal_hotel', 'Отель «Вечный»', '1970-е', '', 0, 18]];
function worlds() {
    return `${header({eyebrow: 'Ночной город · новое дело', title: 'Выбери мир'})}
<main class="nc-main has-dock">
${card(`<p class="nc-lead">Миры между собой не связаны: своё место, эпоха и правила о мистике. В каждом — свои дела на неделю.</p>
<div class="nc-worlds ncase-worlds">${WORLD_LIST.map(([id, title, era, genre = '', cases = 0, age = 0]) =>
        `<button class="nc-world${cases ? '' : ' soon'}" type="button" ${id === 'manor_lake' ? 'aria-pressed="true"' : ''}>
<img src="${WORLDS}${id}/thumb.webp" alt="">${age ? `<span class="w-tag">${age}+</span>` : ''}${id === 'manor_lake' ? tick() : ''}
<span class="w-copy"><span class="w-name">${title}</span><span class="w-era">${genre ? `${era} · ${genre}` : era}</span>
<span class="w-cases">${cases ? `${cases} дело` : 'дела пишутся'}</span></span></button>`).join('')}</div>`, 'nc-span')}
</main>
${dock('', btn('Дальше: Усадьба у озера', 'primary'))}`;
}

/* ---------- 03 the case of the world (§3.2) ---------- */
function caseCard() {
    return `${header({eyebrow: 'Усадьба у озера · дело', title: 'Хозяин исчез'})}
<main class="nc-main has-dock">
${hero({img: `${WORLD}scene_cover.webp`, cls: 'tall', eyebrow: 'Усадьба у озера · 1930-е', title: 'Хозяин исчез из запертой библиотеки',
        text: 'Декабрь 1930-х. Усадьбу у замёрзшего озера отрезала метель. Телефон не работает, генератор даёт перебои. Мистики нет.',
        extra: `<div class="ncase-facts"><span class="nc-tag">${ic('people')}3–12 игроков</span><span class="nc-tag">${ic('calendar')}неделя: утро и вечер</span></div>`})}
<div class="nc-col">
${card(`${head('people', 'Действующие лица', '12')}
<p class="nc-muted">Каждый выбирает себе персонажа. Кого не взяли, ведёт игра. Кто в Тени, решит правда дела при старте.</p>
<ul class="ncase-castgrid">${HEROES.map(h => `<li>${faceImg(h.id, '')}<span class="nm">${h.title}</span></li>`).join('')}</ul>
<div class="ncase-never"><span class="faces">${NEVER.slice(0, 5).map(([id]) => faceImg(id, '', 'ncase-face xs')).join('')}</span><span class="nc-muted">И ещё 8 — их всегда ведёт игра: хозяин, сторож, шофёр…</span></div>`)}
${card(`${head('story', 'Как идёт дело')}
<ol class="ncase-how">
<li><img src="${place('library', 'evening')}" alt=""><div><strong>Ходи по усадьбе</strong><span>Восемь мест, утро, день, вечер и ночь. Переход и осмотр тратят действия окна.</span></div></li>
<li><img src="${item('s1_06_tagged_key')}" alt="" class="obj"><div><strong>Находи улики</strong><span>Находки видишь только ты, пока не опубликуешь их на доске дела.</span></div></li>
<li><img src="${WORLD}scene_vote.webp" alt=""><div><strong>Докажи на слушании</strong><span>В конце недели каждый называет, кто вывел и скрывал хозяина, и прикладывает улики.</span></div></li>
</ol>`)}
</div>
</main>
${dock('', btn('Собрать компанию', 'primary'))}`;
}

/* ---------- 04 gathering: seats are heroes (§3.3) ---------- */
function heroCard(h) {
    const seat = TABLE[h.id];
    const look = seat?.look ? h.looks.find(row => row[0] === seat.look) : h.looks[0];
    const taken = seat && !seat.me;
    const ages = [...new Set(h.looks.map(row => row[1]))];
    const meta = seat ? years(look[1]) : `${ages.length > 1 ? `${ages[0]} или ${years(ages[1])}` : years(ages[0])} · ${h.looks.length} персонажа`;
    return `<button class="ncase-hero ${seat?.me ? 'mine' : taken ? 'taken' : ''}" type="button" ${seat?.me ? 'aria-pressed="true"' : ''} ${taken ? 'disabled' : ''}>
<span class="pic"><img src="${face(h.id, look[0])}" alt="">${seat ? `<span class="ncase-plate">${esc(seat.name)}</span>` : ''}${seat?.me ? tick() : ''}</span>
<span class="cap"><span class="nm">${h.title}</span><span class="sub">${meta}</span></span></button>`;
}
function lobby() {
    return `${header({eyebrow: 'Сбор · Пятничный стол', title: 'Хозяин исчез'})}
<main class="nc-main has-dock">
${hero({img: `${WORLD}scene_lobby_evening.webp`, cls: 'short nc-span', eyebrow: 'Сбор открыт · за столом 6', title: 'Готовы 2 из 6',
        text: 'Выбери персонажа или садись на любое свободное место. Начать можно с трёх игроков: невзятых персонажей поведёт игра.',
        extra: '<div class="nc-track" aria-hidden="true"><i class="ready"></i><i class="ready"></i><i class="in"></i><i class="in"></i><i class="in"></i><i class="in"></i></div>'})}
${card(`${head('people', 'Места за столом', 'свободно 6')}
<div class="ncase-heroes">${HEROES.map(heroCard).join('')}</div>
<div class="ncase-anyseat"><img src="${WORLD}back_role.webp" alt=""><div><strong>Любое свободное место</strong><span class="nc-muted">Персонажа выберет игра при старте.</span></div>${btn('Сесть', 'compact')}</div>
<div class="ncase-never"><span class="faces">${NEVER.map(([id]) => faceImg(id, '', 'ncase-face xs')).join('')}</span><span class="nc-muted">Этих восьмерых всегда ведёт игра: хозяин усадьбы, охотник, сторож, шофёр и другие.</span></div>`, 'nc-span')}
<div class="nc-col">
${card(`${head('talk', 'Обсуждение', '2')}
<div class="nc-chat">
<div class="nc-msg">${faceImg('housekeeper', '', 'ncase-face xs')}<div class="bub">${who('Экономка', 'Вера')}<p>Беру экономку. Кто за адвоката?</p></div></div>
<div class="nc-msg">${faceImg('lawyer', '', 'ncase-face xs')}<div class="bub">${who('Адвокат', 'Олег')}<p>Я. Стартуем сегодня вечером?</p></div></div>
</div>
<div class="nc-join"><input class="nc-field" placeholder="Сообщение" aria-label="Сообщение">${btn('Отправить')}</div>`)}
${card(`${head('vial', 'Ведущий партии')}
<div class="qw-btn-group ncase-narrator" role="group" aria-label="Кто ведёт партию"><button type="button" aria-pressed="true">У админа</button><button type="button" aria-pressed="false">Свой ключ</button><button type="button" aria-pressed="false">Авторский</button></div>
<p class="nc-muted">Партия начнётся на авторском тексте, администратор получит запрос. Одобрит — сцены и ответы персонажей будет писать ИИ.</p>`)}
</div>
<div class="nc-col">
${card(`${head('envelope', 'Пригласить')}
<div class="nc-code">${ic('key')}<span>S57S-XWEH</span><button class="qw-icon-btn" type="button" aria-label="Скопировать код">${ic('papers')}</button></div>
<div class="qw-btn-stack">${btn(`${ic('share')}Поделиться ссылкой`)}</div>
<div class="nc-toggle"><div><strong>Открытый сбор</strong><span>Чужие игроки увидят стол в «Открытых сборах» и смогут сесть на свободное место.</span></div><button type="button" aria-label="Открытый сбор"><span class="qw-switch" data-on="false"></span></button></div>`)}
${card(`${head('calendar', 'Окна дела')}
<p class="nc-lead">Утро в 9:00, вечер в 19:00 по Москве.</p>
<p class="nc-muted">Пояс взят с твоего устройства. Неделя — 14 окон.</p>
<div class="qw-btn-row ncase-left">${btn('Изменить пояс', 'text compact')}</div>`)}
</div>
</main>
${dock('Ты — Садовник, 35 лет · готов · ты хозяин стола', btn('Снять готовность') + btn('Начать дело', 'primary'))}`;
}

/* ---------- 05 choose the character of a seat (owner: «персонаж», not «облик») ---------- */
function pick() {
    const looks = [['', 'Пётр Ильич', 60, 'он'], ['f45', 'Агафья', 45, 'она']];
    return `${header({eyebrow: 'Сбор · Пятничный стол', title: 'Повар: кого играешь'})}
<main class="nc-main has-dock">
${card(`<span class="nc-eyebrow">Место «Повар» · 2 персонажа</span><h2 class="nc-h3">Кого ты играешь?</h2>
<p class="nc-muted">Роль в деле одна, персонажи разные: своё имя, возраст, портрет и обращение. Командует кухней как генерал.</p>
<div class="ncase-looks">${looks.map(([look, name, age, he], i) => `<button class="ncase-look" type="button" ${i === 0 ? 'aria-pressed="true"' : ''}>
<span class="pic"><img src="${face('cook', look)}" alt="">${i === 0 ? tick() : ''}</span><span class="cap"><span class="nm">${name}, ${age}</span><span class="sub">${he} · повар</span></span></button>`).join('')}</div>`, 'nc-span')}
</main>
${dock('', btn('Любой из двух') + btn('Сесть: Пётр Ильич', 'primary'))}`;
}

/* ---------- 06 the role, first open: the side comes from the truth variant (П4) ---------- */
function role() {
    return `${header({eyebrow: 'Дело началось · окно 1', title: 'Твоя роль'})}
<main class="nc-main has-dock ncase-reveal">
<div class="ncase-rolewrap nc-span">
<figure class="ncase-rolecard">
<span class="face"><img src="${face('gardener')}" alt="Портрет: Садовник"></span>
<img class="frame" src="${WORLD}frame_hero.webp" alt="">
<figcaption><span class="eyebrow">Видишь только ты</span><strong>Садовник</strong><span class="side"><img src="${WORLD}emblem_investigation.webp" alt="">Знак Следствия</span></figcaption>
</figure>
<div class="ncase-role-copy">
${card(`${head('scales', 'Твоя сторона — следствие')}<p class="nc-lead">Найти, кто вывел и скрывал хозяина, и доказать это на слушании.</p>
<p class="nc-muted">Кто в Тени, игра решила при старте. Это может быть кто угодно за столом — или никто из игроков.</p>`)}
${card(`${head('seal', 'Твоя тайна')}<p class="nc-lead">В кадке зимнего сада ты закопал чужой предмет: велели спрятать и забыть.</p>`)}
${card(`${head('laurel', 'Твоя цель')}<p class="nc-lead">Дождаться конца метели и незаметно выкопать.</p>
<p class="nc-muted">Засчитывается, если после оттепели ты сам выкопаешь предмет раньше, чем кто-то опубликует карточку о тайнике.</p>`)}
</div></div>
</main>
${dock('Досье всегда открыто во вкладке «Досье»', btn('Понятно, в усадьбу', 'primary'))}`;
}

/* ---------- 07 place: the main screen ---------- */
function actTile(img, label, {pressed = false, obj = true, sub = ''} = {}) {
    return `<button class="ncase-act" type="button" ${pressed ? 'aria-pressed="true"' : ''}><img class="${obj ? 'obj' : 'face'}" src="${img}" alt=""><span><span class="nm">${label}</span>${sub ? `<span class="sub">${sub}</span>` : ''}</span>${pressed ? tick() : ''}</button>`;
}
function placeTile(id, time, people) {
    return `<button class="ncase-go" type="button"><img src="${place(id, time)}" alt=""><span class="cap"><span class="nm">${PLACES[id]}</span>${people ? `<span class="sub">${people}</span>` : ''}</span></button>`;
}
function person(id, look, title, player) {
    return `<li class="ncase-person${player === 'игра' ? ' npc' : ''}">${faceImg(id, look)}<span class="nm">${title}</span>${plate(player)}</li>`;
}
function ap(left, total) {
    return `<span class="ncase-ap" aria-label="Действий осталось: ${left} из ${total}">${Array.from({length: total}, (_, i) => `<i class="${i < left ? 'on' : ''}"></i>`).join('')}<b>${left} из ${total} действий</b></span>`;
}
function placeScreen() {
    return `${caseHeader('Главный зал')}
${tabs('place', {feed: 3, board: 2})}
<main class="nc-main has-dock">
${hero({img: place('main_hall', 'evening'), cls: 'nc-span ncase-place', eyebrow: 'Вечер · ты здесь', title: 'Главный зал',
        text: 'Двусветный зал с камином, портретами предков и длинным обеденным столом. Здесь собираются все и произносятся самые неудобные фразы.',
        extra: `<div class="ncase-hero-row">${ap(3, 4)}<span class="ncase-narr">${ic('vial')}Ведущий: ИИ</span></div>`})}
<div class="nc-col">
${card(`<div class="ncase-event"><img src="${scene('ev_blizzard')}" alt="Метель над озером"><div><span class="nc-eyebrow">Сейчас в усадьбе</span>
<p>Метель закрыла дорогу к лодочному на три окна.</p></div></div>`)}
${card(`${head('people', 'Кто рядом', '3')}
<ul class="ncase-people">${person('butler', '', 'Дворецкий', 'игра')}${person('housekeeper', '', 'Экономка', 'Вера')}${person('lawyer', '', 'Адвокат', 'Олег')}</ul>`)}
${card(`${head('door', 'Куда пойти', '1 действие')}
<div class="ncase-map">${placeTile('library', 'evening', '')}${placeTile('kitchen_wing', 'evening', '2 человека')}${placeTile('winter_garden', 'evening', '')}${placeTile('servants_quarters', 'evening', '1 человек')}${placeTile('tower_room', 'evening', '')}</div>`)}
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
${card(`${head('talk', 'Поговорить', '1 действие')}
<div class="ncase-acts">
${actTile(face('butler'), 'Дворецкий', {obj: false, sub: 'ведёт игра'})}
${actTile(item('s2_03_sealed_envelope'), 'Записка', {sub: 'Экономке или Адвокату'})}
${actTile(item('s2_01_paper_fragment'), 'Слова дворецкого', {sub: 'записанная версия'})}
</div>`)}
${card(`${head('hourglass', 'Окно')}<p class="nc-muted">Сделал всё, что хотел? Заверши окно: когда завершат все, следующее откроется раньше.</p>
<div class="qw-btn-stack">${btn('Завершить окно')}</div>`)}
</div>
</main>
${dock('Осмотреть: Ключ сервисной панели · 1 из 3 действий', btn('Отмена') + btn('Осмотреть', 'primary'))}`;
}

/* ---------- 08 talking to a character the game leads (П2) ---------- */
function talk() {
    return `${caseHeader('Разговор')}
${tabs('place', {feed: 3, board: 2})}
<main class="nc-main has-dock">
${card(`<div class="ncase-npc"><img class="portrait" src="${face('butler')}" alt="Портрет: Дворецкий"><div>
<span class="nc-eyebrow">Главный зал · вечер</span>${who('Дворецкий', 'игра')}
<p class="nc-muted">Высокий, седые виски, перчатки безупречны. Появляется бесшумно. «Извольте», «будет исполнено».</p></div></div>`, 'nc-span')}
<div class="nc-col">
${card(`<div class="nc-chat">
<div class="nc-msg mine"><div class="bub"><p>Что вы можете рассказать об этой ночи?</p></div></div>
<div class="nc-msg">${faceImg('butler', '', 'ncase-face xs')}<div class="bub ncase-npc-say"><span class="who">Дворецкий</span><p>Он поправил перчатку и ответил не сразу. «Письмо было не мне. Я положил его обратно. Почти».</p></div></div>
<span class="nc-sys">${ic('papers')}В твои находки: «Слова дворецкого» — утверждение</span>
</div>`)}
</div>
<div class="nc-col">
${card(`${head('talk', 'Расспросить', '1 действие')}
<div class="ncase-acts one">
${actTile(face('butler'), 'Выслушать дворецкого', {obj: false, sub: 'выслушан · больше добавить нечего'})}
</div>
<p class="nc-muted">Ответ складывается из текста дела. Если подключён ведущий-ИИ, он пишет реплику голосом персонажа, но не выдаёт больше, чем знает персонаж.</p>`)}
</div>
</main>
${dock('Разговор стоил 1 действие · осталось 2 из 4', btn('К месту', 'primary'))}`;
}

/* ---------- 09 the shared feed of the world: «Гостиная у камина» (§4) ---------- */
function track() {
    const days = Array.from({length: 7}, (_, d) => `<span class="day${d === 2 ? ' now' : ''}"><i class="${d <= 2 ? 'done' : ''}"></i><i class="${d < 2 ? 'done' : ''}${d === 2 ? ' cur' : ''}"></i><b>${d + 1}</b></span>`).join('');
    return `<div class="ncase-track" aria-label="Окно 5 из 14">${days}</div>`;
}
function say(id, look, title, player, text) {
    return `<div class="nc-msg">${faceImg(id, look, 'ncase-face xs')}<div class="bub">${who(title, player)}<p>${text}</p></div></div>`;
}
function feed() {
    return `${caseHeader('Гостиная у камина')}
${tabs('feed', {board: 2})}
<main class="nc-main has-dock ncase-chatmain">
${card(`${head('calendar', 'Неделя дела', 'день 3 из 7')}${track()}`, 'nc-span ncase-week')}
${card(`<div class="nc-chat ncase-feed">
<article class="ncase-report"><img src="${scene('ev_scarf')}" alt="Зимний сад, на кресле шарф"><div><span class="nc-eyebrow">Дворецкий докладывает · итог окна 4</span>
<p>В зимнем саду найден забытый шарф. Принадлежность нужно проверить.</p></div></article>
<article class="ncase-pub"><img src="${item('s7_03_scarf')}" alt=""><div>${who('Горничная', 'Кира')}<span class="nc-muted">публикует улику</span><strong>Шарф врача</strong></div></article>
<span class="nc-sys">${ic('moon')}Открылось окно 5 · вечер</span>
${say('housekeeper', '', 'Экономка', 'Вера', 'Ключ оставался изнутри, планку снимали при всех. Я сама держала лампу.')}
${say('nephew_gambler', '', 'Племянник-игрок', 'Лёша', 'Старина просто ушёл по льду, бросьте. Следы же видели.')}
${say('investigator', 'm44', 'Следователь из города', 'Саша', 'Следы видели. Чьи они — не проверяли. Прошу не спешить.')}
<div class="nc-msg mine"><div class="bub">${who('Садовник', 'ты')}<p>В зале на конторке лежит запасной ключ с биркой. Кто его туда положил?</p></div></div>
<article class="ncase-hearing-note"><span class="faces">${faceImg('lawyer', '', 'ncase-face sm')}${ic('scales')}${faceImg('housekeeper', '', 'ncase-face sm')}</span>
<div><strong>Адвокат обвиняет Экономку</strong><span class="nc-muted">Идёт слушание · до конца окна</span></div>${btn('К слушанию', 'compact')}</article>
</div>`, 'nc-span')}
</main>
<div class="nc-dock ncase-compose"><div><p class="nc-dock-hint">Гостиную видят все за столом · осталось 4 реплики в этом окне</p>
<div class="nc-compose"><textarea class="nc-field" rows="1" placeholder="Реплика за столом"></textarea>${btn('Сказать', 'primary')}</div></div></div>`;
}

/* ---------- 10 board ---------- */
function evidence(pic, title, {kind = 'proof', by = '', text = '', action = ''} = {}) {
    return `<figure class="nc-evidence ncase-evi">
<span class="nc-evidence-art"><span class="nc-evidence-plate"><img class="pic" src="${item(pic)}" alt=""></span><img class="frame" src="${WORLD}frame_evidence.webp" alt=""></span>
<figcaption><span class="nc-evidence-kind ${kind}">${kind === 'proof' ? 'Доказательство' : 'Утверждение'}</span><strong>${title}</strong>
${by ? `<span class="meta">${by}</span>` : ''}${text ? `<p>${text}</p>` : ''}${action}</figcaption></figure>`;
}
function board() {
    return `${caseHeader('Улики')}
${tabs('board', {feed: 3})}
<main class="nc-main">
<div class="nc-col">
${card(`${head('lens', 'Доска дела', '4 записи')}
<p class="nc-muted">Для обвинения нужны опубликованные доказательства. Слова и версии остаются утверждениями.</p>
${evidence('s1_05_door_lock', 'Осмотр библиотеки', {by: 'Экономка · Вера · окно 2', text: 'Ключ оставался изнутри; планку сняли при домашних. Окно заперто, снег под ним нетронут.'})}
${evidence('s2_06_ledger_page', 'Журнал ключей', {by: 'Адвокат · Олег · окно 3', text: 'Старый журнал фиксирует выдачи сервисных ключей; рядом расписка адвоката.'})}
${evidence('s7_03_scarf', 'Шарф врача', {by: 'Горничная · Кира · окно 4', text: 'Квитанция починки подтверждает, чей это шарф. Это не след хозяина.'})}
${evidence('s3_06_bootprint', 'Хозяин ушёл по льду', {kind: 'claim', by: 'Версия: Племянник-игрок · Лёша', text: 'Следы к дороге — значит, он сам ушёл через озеро.'})}`)}
</div>
<div class="nc-col">
${card(`${head('papers', 'Твои находки', 'видишь только ты')}
${evidence('s1_06_tagged_key', 'Ключ сервисной панели', {by: 'Главный зал · окно 5', text: 'На запасном ключе бирка старой мастерской: сервисная панель библиотеки.',
        action: `<div class="qw-btn-row ncase-left">${btn('Опубликовать', 'compact')}</div>`})}
${evidence('c1_06_hunting_horn', 'Узел на роге', {by: 'Главный зал · окно 3', text: 'На шнурке охотничьего рога свежий двойной узел.',
        action: `<div class="qw-btn-row ncase-left">${btn('Опубликовать', 'compact')}</div>`})}`)}
${card(`${head('scales', 'Обвинение')}<p class="nc-muted">Хватает доказательств против кого-то? Предъяви обвинение: стол решит на слушании, поддержать его или нет.</p>
<div class="qw-btn-stack">${btn('Предъявить обвинение')}</div>`)}
${card(`${head('story', 'Добавить версию')}<textarea class="nc-field ncase-draft" rows="3" placeholder="Например: ключ панели выдавали по журналу — сверить с распиской"></textarea>
<div class="qw-btn-row ncase-left">${btn('Опубликовать версию')}</div>`)}
</div>
</main>`;
}

/* ---------- 11 dossier: the role, notes (whispers) and own events ---------- */
function chron(img, when, text, {obj = false} = {}) {
    return `<li><img class="${obj ? 'obj' : ''}" src="${img}" alt=""><div><span class="when">${when}</span><p>${text}</p></div></li>`;
}
function dossier() {
    return `${caseHeader('Досье')}
${tabs('self', {feed: 3, board: 2})}
<main class="nc-main">
<div class="nc-col">
${card(`<div class="ncase-me">${faceImg('gardener', '', 'ncase-face lg')}<div><span class="nc-eyebrow">Видишь только ты</span><strong>Садовник, 35 лет</strong>
<span class="ncase-side"><img src="${WORLD}emblem_investigation.webp" alt="">Знак Следствия</span></div></div>
<p class="nc-muted">Крепкий: кепка, рабочая куртка, перчатки. Пахнет землёй даже в декабре. Говорит мало: «Оно конечно», «ну, как сказать».</p>`)}
${card(`${head('laurel', 'Цель')}<p class="nc-lead">Дождаться конца метели и незаметно выкопать.</p>
<div class="ncase-steps"><span class="on">${ic('check')}Метель идёт</span><span>${ic('hourglass')}Оттепель</span><span>${ic('key')}Выкопать</span></div>`)}
${card(`${head('seal', 'Тайна')}<div class="ncase-secret"><img src="${place('winter_garden', 'night')}" alt="Зимний сад ночью"><p>В кадке зимнего сада ты закопал чужой предмет: велели спрятать и забыть.</p></div>`)}
</div>
<div class="nc-col">
${card(`${head('envelope', 'Записки', '1 новая')}
<article class="ncase-note"><div class="from">${faceImg('housekeeper', '', 'ncase-face xs')}${who('от Экономки', 'Вера')}<span class="nc-muted">окно 5</span></div>
<p>Ключ с биркой я видела у адвоката позавчера. Пока молчи.</p></article>
<p class="nc-muted">Записку видишь только ты. Ответить можно, если вы в одном месте.</p>`)}
${card(`${head('calendar', 'Твои события')}
<ul class="ncase-chron">
${chron(item('s1_06_tagged_key'), 'Окно 5', 'Находка: «Ключ сервисной панели».', {obj: true})}
${chron(place('servants_quarters', 'day'), 'Окно 4', 'Ты перешёл в комнаты прислуги.')}
${chron(item('c1_06_hunting_horn'), 'Окно 3', 'Находка: «Узел на роге».', {obj: true})}
</ul>`)}
</div>
</main>`;
}

/* ---------- 12 a hearing during the week: support or object ---------- */
function hearing() {
    return `${header({eyebrow: 'Окно 5 · слушание', title: 'Хозяин исчез', clock: {icon: 'scales', text: '5 ч 40 м', title: 'До закрытия слушания'}})}
<main class="nc-main has-dock">
${hero({img: `${WORLD}scene_vote.webp`, pos: '50% 58%', cls: 'short nc-span', eyebrow: 'Слушание · окно 5', title: 'Адвокат обвиняет Экономку',
        text: 'Поддержи обвинение или возрази. Голос тайный; итог объявят, когда слушание закроется.'})}
<div class="nc-col">
${card(`<div class="ncase-accuse"><figure>${faceImg('lawyer', '', 'ncase-face lg')}<figcaption>${who('Адвокат', 'Олег')}<span class="nc-muted">обвиняет</span></figcaption></figure>
${ic('scales', 'mid')}<figure>${faceImg('housekeeper', '', 'ncase-face lg')}<figcaption>${who('Экономка', 'Вера')}<span class="nc-muted">обвиняемая</span></figcaption></figure></div>
<p class="nc-lead">«Сервисный ключ выдавала она. Журнал и бирка сходятся».</p>`)}
</div>
<div class="nc-col">
${card(`${head('lens', 'Приложенные улики', '2')}
${evidence('s2_06_ledger_page', 'Журнал ключей', {by: 'доказательство · окно 3'})}
${evidence('s1_06_tagged_key', 'Ключ сервисной панели', {by: 'доказательство · окно 5'})}`)}
</div>
</main>
${dock('Сдали голос 3 из 6 · кто как голосовал, не видно', btn('Возражаю') + btn('Поддержать'))}`;
}

/* ---------- 13 final hearing ---------- */
const SUSPECTS = [['lawyer', 'Адвокат', 'Олег'], ['housekeeper', 'Экономка', 'Вера'], ['butler', 'Дворецкий', 'игра'], ['hunter', 'Охотник', 'игра'],
    ['watchman', 'Сторож', 'игра'], ['nephew_gambler', 'Племянник', 'Лёша'], ['maid', 'Горничная', 'Кира'], ['owner', 'Хозяин сам', 'игра']];
function finalHearing() {
    return `${header({eyebrow: 'Окно 14 · итоговое слушание', title: 'Хозяин исчез', clock: {icon: 'scales', text: '2 ч 10 м', title: 'До закрытия слушания'}})}
<main class="nc-main has-dock">
${hero({img: `${WORLD}scene_vote.webp`, pos: '50% 58%', cls: 'short nc-span', eyebrow: 'Итоговое слушание · сдали 4 из 6', title: 'Кто вывел и скрывал хозяина?',
        text: 'Если хозяин всё сделал сам, без помощников, назови его самого. Голос можно изменить, пока слушание не закрылось.'})}
${card(`${head('people', 'Твой выбор')}
<div class="ncase-suspects">${SUSPECTS.map(([id, title, player], i) => `<button class="ncase-suspect" type="button" ${i === 0 ? 'aria-pressed="true"' : ''}>
<span class="pic"><img src="${face(id)}" alt="">${i === 0 ? tick() : ''}</span><span class="nm">${title}</span>${plate(player)}</button>`).join('')}</div>`)}
${card(`${head('lens', 'Приложи улики', 'выбрано 2 из 5')}
<p class="nc-muted">Сервер проверит, хватает ли доказательств. Утверждения ключами не считаются.</p>
<div class="ncase-cites">
${[['s2_06_ledger_page', 'Журнал ключей', 'Олег', true], ['s1_06_tagged_key', 'Ключ сервисной панели', 'ты', true], ['s1_05_door_lock', 'Осмотр библиотеки', 'Вера', false],
        ['s7_03_scarf', 'Шарф врача', 'Кира', false], ['s3_06_bootprint', 'Хозяин ушёл по льду', 'Лёша', false, 'claim']].map(([pic, title, by, on, kind]) =>
        `<button class="ncase-cite${kind === 'claim' ? ' claim' : ''}" type="button" ${on ? 'aria-pressed="true"' : ''} ${kind === 'claim' ? 'disabled' : ''}>
<img src="${item(pic)}" alt=""><span><span class="nm">${title}</span><span class="sub">${kind === 'claim' ? 'утверждение · не считается' : `доказательство · ${by}`}</span></span><span class="box">${on ? tick() : ''}</span></button>`).join('')}
</div>`)}
</main>
${dock('Голос тайный до закрытия · его можно изменить', btn('Воздержаться') + btn('Отдать голос: Адвокат', 'primary'))}`;
}

/* ---------- 14 final: the reveal, hero first (§3.4) ---------- */
function castRow(id, look, title, player, side, part, result) {
    const emb = {shadow: ['emblem_shadow', 'Тень'], investigation: ['emblem_investigation', 'Следствие'], independent: ['emblem_independent', 'Сам за себя']}[side];
    return `<li>${faceImg(id, look)}<div>${who(title, player)}<span class="sub">${part}</span></div>
<span class="ncase-fac ${side}"><img src="${WORLD}${emb[0]}.webp" alt="">${emb[1]}</span>${result}</li>`;
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
<span class="nc-muted">После оттепели ты выкопал предмет раньше, чем о тайнике узнали. Следствие победило.</span></div></div>`)}
${card(`${head('scales', 'Итоговое слушание')}<p class="nc-lead">Стол назвал Адвоката: 4 голоса из 6.</p>
<p class="nc-muted">Решили три доказательства: копия черновика, журнал ключей и записка у подпорки.</p>`)}
</div>
<div class="nc-col">
${card(`${head('people', 'Кто был кем', 'роли открыты')}
<ul class="ncase-cast">
${castRow('lawyer', '', 'Адвокат', 'Олег', 'shadow', 'виновный', no)}
${castRow('housekeeper', '', 'Экономка', 'Вера', 'shadow', 'сообщница Тени', no)}
${castRow('gardener', '', 'Садовник', 'ты', 'investigation', 'следствие', ok)}
${castRow('investigator', 'm44', 'Следователь из города', 'Саша', 'investigation', 'следствие', ok)}
${castRow('maid', '', 'Горничная', 'Кира', 'investigation', 'следствие', ok)}
${castRow('nephew_gambler', '', 'Племянник-игрок', 'Лёша', 'independent', 'свой интерес', no)}
</ul>`)}
</div>
</main>
${dock('', btn('Выйти') + btn('Новое дело', 'primary'))}`;
}

/* ---------- states of the case: new pictures ----------
   Objects for these screens come as one transparent 3x3 sheet in the manor style (owner's batch, 2026-11-21).
   NEW_ART lists the files that exist (mock/art/<key>.webp); a missing one is drawn as a dashed slot that says
   what goes there, or as a stand-in item of the pack. */
const NEW_ART = {clock: 1, phone: 1, bell: 1, drawer: 1, versions: 1, salver: 1, chair: 1, pen: 1, candle: 1};
const NEW_ART_NOTE = {phone: 'телефон с оборванным шнуром', chair: 'пустой стул, отодвинутый от стола', clock: 'остановившиеся каминные часы',
    bell: 'настольный звонок', drawer: 'ящик архивной картотеки', salver: 'письмо на серебряном подносе', versions: 'две редакции завещания',
    pen: 'перо над раскрытым блокнотом', candle: 'догоревшая свеча'};
function obj(key, {stand = null, cls = 'obj'} = {}) {
    if (NEW_ART[key]) return `<img class="${cls}" src="/mock/art/${key}.webp" alt="">`;
    if (stand) return `<img class="${cls}" src="${item(stand)}" alt="">`;
    return `<span class="${cls} ncase-slot" role="img" aria-label="Место для картинки: ${NEW_ART_NOTE[key]}">${ic('papers')}<span>${NEW_ART_NOTE[key]}</span></span>`;
}
function heroObj({img, pos = '50% 40%', eyebrow, title, text, cls = '', key, stand = null}) {
    return `<section class="nc-hero ncase-objhero ${cls}" style="--img:url('${img}');--pos:${pos}">${obj(key, {stand, cls: 'ncase-hero-obj'})}<div class="copy">
<span class="nc-eyebrow">${eyebrow}</span><h2>${title}</h2>${text ? `<p>${text}</p>` : ''}</div></section>`;
}
const alertBox = (icon, title, text, tone = '') => `<div class="nc-alert ${tone}" role="status">${ic(icon)}<div><strong>${title}</strong>${text ? `<p>${text}</p>` : ''}</div></div>`;
const can = (on, text) => `<li class="${on ? 'on' : 'off'}">${ic(on ? 'check' : 'lock')}<span>${text}</span></li>`;

/* ---------- 15 removed by a wrong accusation (status «ghost» in the rules; no mysticism in this world) ---------- */
function removed() {
    return `${header({eyebrow: 'Окно 6 · отстранён', title: 'Хозяин исчез', clock: {icon: 'hourglass', text: '3 ч 15 м', title: 'До конца окна 6'}})}
${tabs('place', {feed: 2})}
<main class="nc-main has-dock">
<section class="nc-hero ncase-out nc-span" style="--img:url('${place('main_hall', 'night')}');--pos:50% 40%"><img class="ncase-out-face" src="${face('gardener')}" alt="Портрет: Садовник, приглушённый">
<div class="copy"><span class="nc-eyebrow">Слушание закрыто · окно 6</span><h2>Стол отстранил Садовника</h2>
<p>Обвинение поддержали, но ты не виновен. Ходить, говорить и голосовать ты больше не можешь. Дело ты видишь до развязки.</p></div></section>
<div class="nc-col">
${card(`${head('eye', 'Что тебе осталось')}
<ul class="ncase-can">${can(true, 'Одно действие за окно — ниже')}${can(true, 'Читать Гостиную у камина')}${can(true, 'Смотреть доску улик')}${can(true, 'Своё досье и находки')}${can(true, 'Переписка отстранённых')}${can(true, 'Развязка и итог дела')}
${can(false, 'Ходить, говорить, обвинять, голосовать')}</ul>`)}
${card(`${head('share', 'Раз в окно', '1 из 1')}
<p class="nc-muted">Выбери одно. Что можно передать, заранее решает дело; ты отдаёшь только то, что знал твой персонаж.</p>
<div class="ncase-acts">
${actTile(item('s1_06_tagged_key'), 'Воспоминание на доску', {pressed: true, sub: 'увидят все'})}
${actTile(item('s2_03_sealed_envelope'), 'Записка живому', {sub: 'одному игроку'})}
${actTile('/mock/art/candle.webp', 'Знак в месте', {sub: 'найдут при осмотре'})}
${actTile(item('s2_04_telegram_strip'), 'Да или нет', {sub: 'ответ на вопрос'})}
</div>
<p class="ncase-mocknote">Сейчас в игре есть только «Воспоминание на доску». Остальные три — из дизайна недели (§3.2), ещё не сделаны. В «Усадьбе» воспоминаний для передачи пока нет ни у одного персонажа.</p>
${evidence('s1_06_tagged_key', 'Ключ сервисной панели', {by: 'твоя находка · окно 5 · пример', text: 'На запасном ключе бирка старой мастерской: сервисная панель библиотеки.'})}`)}
</div>
<div class="nc-col">
${card(`${head('talk', 'Отстранённые')}
<div class="nc-chat">
<span class="nc-sys">${ic('eye')}Садовник теперь наблюдает за делом</span>
<div class="ncase-free ncase-empty">${obj('chair')}<p class="nc-muted">Пока здесь только ты. Сюда пишут те, кого стол отстранил; за столом этого не видят.</p></div>
</div>
<div class="nc-compose"><textarea class="nc-field" rows="1" placeholder="Реплика отстранённым"></textarea>${btn('Сказать')}</div>`)}
</div>
</main>
${dock('Воспоминание на доску: Ключ сервисной панели', btn('Отмена') + btn('Поделиться', 'primary'))}`;
}

/* ---------- 16 the table stopped: six windows in a row nobody came ---------- */
function frozen() {
    const seats = [['gardener', 'Садовник', 'ты'], ['housekeeper', 'Экономка', 'Вера'], ['lawyer', 'Адвокат', 'Олег'], ['maid', 'Горничная', 'Кира'],
        ['nephew_gambler', 'Племянник-игрок', 'Лёша'], ['investigator', 'Следователь', 'Саша', 'm44']];
    return `${header({eyebrow: 'Окно 9 из 14 · стол стоит', title: 'Хозяин исчез', clock: {icon: 'hourglass', text: 'стоит', title: 'Окна остановлены'}})}
<main class="nc-main has-dock">
${heroObj({img: `${WORLD}scene_lobby_evening.webp`, pos: '50% 55%', cls: 'tall nc-span', key: 'clock',
        eyebrow: 'Стол ждёт возвращения', title: 'Окна остановились',
        text: 'Шесть окон подряд никто не заходил. Всё сохранено: места, находки, записки. Окно 9 откроется, когда кто-нибудь вернётся.'})}
<div class="nc-col">
${card(`${head('calendar', 'Что будет дальше')}
<div class="ncase-free">${obj('bell')}<p class="nc-muted">Стол не потерял ничего. Чтобы продолжить, хватит одного человека.</p></div>
<ol class="ncase-next"><li>Первый, кто нажмёт «Я здесь», откроет окно 9. Действия за это не тратятся.</li>
<li>Окно продлится не меньше 30 минут.</li>
<li>Остальные успеют вернуться в этом же окне. Кто не вернётся, того персонажа со временем поведёт игра.</li></ol>`)}
</div>
<div class="nc-col">
${card(`${head('people', 'За столом', '6 мест')}
<ul class="ncase-people">${seats.map(([id, title, player, look]) => `<li class="ncase-person away">${faceImg(id, look || '')}<span class="nm">${title}</span>${plate(player)}</li>`).join('')}</ul>`)}
</div>
</main>
${dock('Первый вернувшийся открывает окно 9', btn('Я здесь', 'primary'))}`;
}

/* ---------- 17 the answer did not come back: the same request is repeated, never applied twice ---------- */
function netLost() {
    return `${caseHeader('Главный зал')}
${tabs('place', {feed: 3, board: 2})}
<div class="nc-net" role="status">${ic('alert')}<span>Запрос ещё не подтверждён сервером</span>${btn('Повторить', 'compact')}</div>
<main class="nc-main has-dock">
${alertBox('alert', 'Нет связи', 'Повтори тот же запрос — действие не применится дважды.', 'warn')}
${hero({img: place('main_hall', 'evening'), cls: 'short nc-span ncase-place', eyebrow: 'Вечер · ты здесь', title: 'Главный зал',
        extra: `<div class="ncase-hero-row">${ap(3, 4)}</div>`})}
<div class="nc-col">
${card(`${head('lens', 'Осмотреть', '1 действие')}
<div class="ncase-acts">${actTile(item('s1_06_tagged_key'), 'Ключ сервисной панели', {pressed: true, sub: 'ответ не дошёл'})}${actTile(item('s1_05_door_lock'), 'Осмотр библиотеки')}</div>`)}
</div>
<div class="nc-col">
${card(`${head('papers', 'Что сохранено')}
<p class="nc-muted">Всё, что сервер уже подтвердил, сохранено. Действие спишется только один раз, даже если нажать «Повторить» несколько раз.</p>`)}
</div>
</main>
${dock('Осмотреть: Ключ сервисной панели — ответ не дошёл', btn('Отмена') + btn('Повторить', 'primary'))}`;
}

/* ---------- 18 the case does not open at all ---------- */
function netDown() {
    return `${header({eyebrow: 'Ночной город', title: 'Нет связи'})}
<main class="nc-main has-dock">
${heroObj({img: place('main_hall', 'night'), pos: '50% 40%', cls: 'tall nc-span', key: 'phone',
        eyebrow: 'Нет связи со столом', title: 'Линия молчит',
        text: 'Не удалось открыть дело. Проверь связь и открой Ночной город снова.'})}
<div class="nc-col">
${card(`${head('papers', 'Что сохранено')}
<p class="nc-muted">Твои ходы, которые сервер подтвердил, сохранены. Неподтверждённый запрос можно повторить: дважды он не применится.</p>`)}
</div>
</main>
${dock('', btn('В главное меню') + btn('Повторить', 'primary'))}`;
}

/* ---------- 19 the ⚙ menu (QW.menu, UI_RULES §5): account, the game block (up to 6), the core block ---------- */
const mi = (icon, label, {hint = '', value = '', sw = null, danger = false} = {}) =>
    `<button class="qw-menu-item${danger ? ' qw-danger' : ''}" type="button" ${sw !== null ? `role="switch" aria-checked="${sw}"` : ''}><svg viewBox="0 0 24 24"><use href="${SPRITE}#nc-i-${icon}"/></svg>
<span class="qw-grow">${label}${hint ? `<small>${hint}</small>` : ''}</span>${sw !== null ? `<span class="qw-switch" data-on="${sw}"></span>` : value ? `<span class="qw-value">${value}</span>` : ''}</button>`;
function menuScreen() {
    return `${caseHeader('Главный зал')}
${tabs('place', {feed: 3, board: 2})}
<main class="nc-main">
${hero({img: place('main_hall', 'evening'), cls: 'nc-span ncase-place', eyebrow: 'Вечер · ты здесь', title: 'Главный зал',
        text: 'Двусветный зал с камином, портретами предков и длинным обеденным столом.'})}
</main>
<div class="qw-menu-scrim qw-open"></div>
<div class="qw-menu qw-open ncase-menu" role="dialog" aria-label="Меню"><div class="qw-menu-handle"></div>
<button class="qw-menu-item qw-menu-account" type="button"><span class="qw-avatar">С</span><span class="qw-grow">Твой профиль<small>Профиль и настройки</small></span><svg viewBox="0 0 24 24"><use href="${SPRITE}#nc-i-back"/></svg></button>
<div class="qw-menu-section">Ночной город</div>
${mi('story', 'Правила дела')}
${mi('vial', 'Ведущий партии', {value: 'ИИ'})}
${mi('music', 'Музыка', {sw: false})}
${mi('eye', 'Контрастный режим', {sw: false})}
${mi('repeat', 'Обновить связь')}
${mi('door', 'Покинуть дело', {hint: 'Твоего персонажа дальше поведёт игра', danger: true})}
<div class="qw-menu-section">QuizzyWizzy</div>
${mi('home', 'Главное меню')}
${mi('full', 'Во весь экран')}
${mi('bug', 'Сообщить о проблеме')}
</div>`;
}

/* ---------- 20 a free action in own words (with the AI narrator): the narrator maps it to an existing choice ---------- */
function freeAction() {
    return `${caseHeader('Главный зал')}
${tabs('place', {feed: 3, board: 2})}
<main class="nc-main has-dock">
${hero({img: place('main_hall', 'evening'), cls: 'short nc-span ncase-place', eyebrow: 'Вечер · ты здесь', title: 'Главный зал',
        extra: `<div class="ncase-hero-row">${ap(3, 4)}<span class="ncase-narr">${ic('vial')}Ведущий: ИИ</span></div>`})}
<div class="nc-col">
${card(`${head('story', 'Своими словами')}
<div class="ncase-free">${obj('pen', {stand: 's5_05_notebook'})}<p class="nc-muted">Опиши, что хочешь сделать. Ведущий подберёт подходящее действие из доступных. Пока ты не подтвердишь, ничего не тратится.</p></div>
<textarea class="nc-field ncase-draft" rows="3" aria-label="Что ты хочешь сделать?">Посмотреть, нет ли на подоконнике в библиотеке следов воска</textarea>
<div class="qw-btn-row ncase-left">${btn('Предложить действие')}</div>`)}
</div>
<div class="nc-col">
${card(`${head('vial', 'Ведущий понял так')}
<div class="ncase-acts one">${actTile(item('s1_05_door_lock'), 'Осмотр библиотеки', {pressed: true, sub: '1 действие'})}</div>
<p class="nc-muted">Если ведущий не поймёт, он скажет: «Уточни действие: выбери одну из доступных кнопок. Пока ничего не потрачено».</p>`)}
</div>
</main>
${dock('Предложенное действие: Осмотр библиотеки · 1 из 3 действий', btn('Отмена') + btn('Подтвердить', 'primary'))}`;
}

/* ---------- 21 archive requests: paid now, the answer comes in the next window ---------- */
function archive() {
    return `${caseHeader('Главный зал')}
${tabs('place', {feed: 3, board: 2})}
<main class="nc-main has-dock">
${heroObj({img: place('main_hall', 'evening'), cls: 'short nc-span', key: 'drawer', stand: 's2_06_ledger_page',
        eyebrow: 'Архивный фонд усадьбы', title: 'Запросить копию',
        text: 'Копии привезли в усадьбу заранее, телефон для этого не нужен. Ответ придёт в следующем окне — в хронику и досье.'})}
<div class="nc-col">
${card(`${head('papers', 'Запросить в архиве', '1 действие')}
<div class="ncase-acts">
${actTile(item('s2_06_ledger_page'), 'Копия реестра завещаний', {pressed: true})}
${actTile(item('s2_07_ticket'), 'Копия журнала приглашений')}
</div>
<p class="nc-muted">Каждую копию можно запросить один раз за дело.</p>`)}
${card(`${head('hourglass', 'Запросы', '2')}
<ul class="ncase-chron">
${chron(item('s2_02_folded_letter'), 'В пути · ответ в окне 6', 'Копия переписки хозяина', {obj: true})}
${chron(item('s5_05_notebook'), 'Получено · окно 5', 'Копия журнала обходов', {obj: true})}
</ul>`)}
</div>
<div class="nc-col">
${card(`${head('envelope', 'Ответ архива', 'окно 5')}
<p class="nc-lead">Получена копия из заранее доставленного в усадьбу архивного фонда; телефонная линия для этого не требуется.</p>
${evidence('s5_05_notebook', 'Лист обхода', {by: 'архив · окно 5 · видишь только ты', text: 'Копия расписания обходов содержит два прохода сторожа к лодочному и контрольный оттиск его подбитой подошвы.',
        action: `<div class="qw-btn-row ncase-left">${btn('Опубликовать', 'compact')}</div>`})}`)}
</div>
</main>
${dock('Запросить: Копия реестра завещаний · 1 из 3 действий', btn('Отмена') + btn('Запросить', 'primary'))}`;
}

/* ---------- 22 versions: documents of one paper side by side, public theories in the archive ---------- */
function theory(title, body, state, links) {
    const archived = state === 'archived';
    return `<article class="ncase-theory${archived ? ' archived' : ''}"><div class="top"><strong>${title}</strong><span class="nc-tag">${archived ? 'в архиве' : 'активная'}</span></div>
<p class="nc-muted">${body}</p>${links.map(([pic, name, rel]) => `<span class="ncase-link ${rel}"><img src="${item(pic)}" alt="">${rel === 'supports' ? 'подтверждает' : 'противоречит'}: ${name}</span>`).join('')}
<div class="qw-btn-row ncase-left">${btn(archived ? 'Вернуть версию' : 'В архив', 'compact')}</div></article>`;
}
function versions() {
    return `${caseHeader('Улики')}
${tabs('board', {feed: 3})}
<main class="nc-main">
<div class="nc-col">
${card(`${head('papers', 'Редакции завещания', 'видишь только ты')}
<div class="ncase-revs">${obj('versions', {stand: 'c1_01_rolled_will'})}
<ul><li><b>Редакция 1</b> Копия черновика</li><li><b>Редакция 2</b> Официальная папка</li></ul></div>
<p class="nc-muted">Обе бумаги у тебя. Сравнить их можно действием в месте, где лежат оригиналы, — это обычный осмотр за 1 действие.</p>`)}
</div>
<div class="nc-col">
${card(`${head('story', 'Версии стола', '3')}
<p class="nc-muted">Версия — общая догадка, не улика. Связь с уликой видна, когда улику опубликовали. Архив не значит «опровергнута»: версию можно вернуть.</p>
${theory('Уход через озеро', 'Проверим версию ухода из усадьбы.', 'archived', [['s3_06_bootprint', 'Следы на льду', 'contradicts']])}
${theory('Укрытие внутри дома', 'Проверим служебный маршрут и двери.', 'active', [])}
${theory('Добровольная проверка', 'Проверим документы о намерениях.', 'active', [])}
<span class="nc-sys">${ic('repeat')}Вера: версия «Уход через озеро» отправлена в архив</span>`)}
</div>
</main>`;
}

/* ---------- 23 a letter is offered: the butler returns a closed letter (the viewer here plays the daughter) ---------- */
function letter() {
    return `${header({eyebrow: 'Окно 7 из 14 · день 4, утро', title: 'Библиотека', clock: {icon: 'hourglass', text: '4 ч 05 м', title: 'До конца окна 7'}})}
${tabs('place', {feed: 1})}
<main class="nc-main has-dock">
${hero({img: place('library', 'morning'), cls: 'short nc-span ncase-place', eyebrow: 'Утро · ты здесь', title: 'Библиотека',
        extra: `<div class="ncase-hero-row">${ap(4, 4)}</div>`})}
<div class="nc-col">
${card(`${head('envelope', 'Письмо', '0 действий')}
<div class="ncase-letter">${obj('salver', {stand: 's2_03_sealed_envelope'})}
<div class="from">${faceImg('butler', '', 'ncase-face sm')}${who('Дворецкий', 'игра')}</div>
<p class="nc-lead">Дворецкий оставил тебе закрытое письмо. Принять или отказаться?</p></div>
<p class="nc-muted">Что в письме, узнаешь, только если примешь. Откажешься — письмо останется лежать, и больше его не предложат.</p>`, '')}
</div>
<div class="nc-col">
${card(`<div class="ncase-me">${faceImg('daughter', '', 'ncase-face lg')}<div><span class="nc-eyebrow">Ты в этом деле</span><strong>Дочь от первого брака</strong>
<span class="nc-muted">Пример экрана другого игрока: письмо адресовано Дочери.</span></div></div>`)}
</div>
</main>
${dock('Решение только твоё · действий не тратит', btn('Отклонить письмо') + btn('Принять письмо', 'primary'))}`;
}

const SCREENS = [
    ['01_root', '1 Ночной город', root, null],
    ['02_worlds', '2 Новое дело · миры', worlds, null],
    ['03_case', '3 Дело мира', caseCard, 'scene_cover'],
    ['04_lobby', '4 Сбор', lobby, 'scene_lobby_evening'],
    ['05_pick', '5 Выбор персонажа', pick, 'scene_lobby_evening'],
    ['06_role', '6 Твоя роль', role, 'scene_title'],
    ['07_place', '7 Место', placeScreen, null],
    ['08_talk', '8 Разговор', talk, null],
    ['09_feed', '9 Гостиная у камина', feed, null],
    ['10_board', '10 Улики', board, null],
    ['11_dossier', '11 Досье', dossier, null],
    ['12_hearing', '12 Слушание', hearing, 'scene_vote'],
    ['13_final_hearing', '13 Итоговое слушание', finalHearing, 'scene_vote'],
    ['14_final', '14 Дело закрыто', finale, 'scene_finale'],
    ['15_removed', '15 Отстранён', removed, null],
    ['16_frozen', '16 Стол на паузе', frozen, 'scene_lobby_evening'],
    ['17_net_lost', '17 Ответ не дошёл', netLost, null],
    ['18_net_down', '18 Дело не открылось', netDown, null],
    ['19_menu', '19 Меню ⚙', menuScreen, null],
    ['20_free', '20 Своими словами', freeAction, null],
    ['21_archive', '21 Запрос в архив', archive, null],
    ['22_versions', '22 Архив версий', versions, null],
    ['23_letter', '23 Письмо', letter, null],
];

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
    const content = document.getElementById('content');
    if (!screen) {
        content.innerHTML = `${header({eyebrow: 'Макеты · 2026-11-21', title: 'Дело недели', back: false})}<main class="nc-main"><section class="nc-card nc-span"><ul class="nc-list">${SCREENS.map(([sid, label]) =>
            `<li><a class="ttl" href="?s=${sid}">${label}</a> · <a href="?s=${sid}&c=1">контраст</a></li>`).join('')}</ul></section></main>`;
    } else {
        const [, , render, page] = screen;
        const backdrop = page ? `${WORLD}${page}.webp` : id === '01_root' || id === '02_worlds' ? `${SHELL}shell_entry_portrait.webp` : place('main_hall', 'evening');
        document.documentElement.style.setProperty('--page-img', `url('${backdrop}')`);
        content.innerHTML = render();
    }
    await Promise.all([...document.images].map(img => img.decode().catch(() => null)));
    await document.fonts.ready;
    document.documentElement.dataset.ready = '1';
}
main();
})();
