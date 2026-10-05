// Navigation unit tests: a small DOM double, no browser or Telegram requests.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {join} = require('node:path');
const {runInNewContext} = require('node:vm');

class Element {
    constructor(tag) { this.tag = tag; this.children = []; this.dataset = {}; this.attrs = {}; this.events = {}; this.className = ''; this.text = '';
        this.classList = {add: (...names) => { this.className += ' ' + names.join(' '); }, toggle: (name, enabled) => { this.className = this.className.split(' ').filter(n => n !== name).concat(enabled ? [name] : []).join(' '); }};
    }
    set textContent(value) { this.text = String(value); this.children = []; }
    get textContent() { return this.text + this.children.map(n => n.textContent).join(''); }
    get childElementCount() { return this.children.length; }
    append(...nodes) { this.children.push(...nodes); }
    replaceChildren(...nodes) { this.text = ''; this.children = nodes; }
    setAttribute(key, value) { this.attrs[key] = value; }
    removeAttribute(key) { delete this.attrs[key]; }
    addEventListener(event, callback) { this.events[event] = callback; }
    click() { return (this.events.click || this.onclick)?.({currentTarget: this, preventDefault() {}}); }
    querySelectorAll(selector) {
        const all = this.children.flatMap(child => [child, ...child.querySelectorAll('*')]);
        return all.filter(n => selector.split(',').some(s => { s = s.trim(); return s === '*' || s === n.tag || (s.startsWith('.') && n.className.split(' ').includes(s.slice(1))) || (s === '[data-deadline]' && n.dataset.deadline !== undefined); }));
    }
    querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
    scrollIntoView() {}
}
const flush = () => new Promise(resolve => setImmediate(resolve));
const source = file => readFileSync(join(__dirname, '../../web/mini_client', file), 'utf8');
const findButton = (root, label) => {
    const found = root.querySelectorAll('button').find(n => n.textContent === label || n.textContent.startsWith(label));
    assert.ok(found, `Missing button: ${label}`); return found;
};
async function application(runtime = true, startParam = '', {overrides = {}, manualTimers = false} = {}) {
    const ids = Object.fromEntries(['content', 'navigation', 'feedback', 'environment'].map(id => [id, new Element('div')]));
    for (const page of ['home', 'chats', 'rating', 'profile']) { const b = new Element('button'); b.dataset.page = page; ids.navigation.append(b); }
    const brand = new Element('a'), mounts = [], timers = [], ui = {prefs: {theme: 'system', haptics: true}, canFullscreen: true,
        configure(back, settings) { this.back = back; this.settings = settings; }, selection() {},
        setTheme(value) { this.prefs.theme = value; }, toggleHaptics() { return this.prefs.haptics = !this.prefs.haptics; }, fullscreen() {}};
    // Управляемые таймеры нужны там, где проверяется продление сессии: иначе
    // ждать десять минут, а настоящий таймер вдобавок держит event loop.
    const schedule = manualTimers
        ? (callback, delay) => { const handle = {callback, delay, unref() {}}; timers.push(handle); return handle; }
        : setTimeout;
    const cancel = manualTimers
        ? handle => { const index = timers.indexOf(handle); if (index >= 0) timers.splice(index, 1); }
        : clearTimeout;
    const fixtures = {
        '/api/mini/config': {runtime_enabled: runtime, offline: true}, '/api/dev/info': {demo: true},
        '/api/dev/session': {access_token: 'unit-test'}, '/api/mini/me': {user_id: '42', display_name: 'Игрок', score: 12, answered_count: 3},
        '/api/mini/progress': {best_streak: 2, correct_including_photo: 2, current_streak: 1, achievements: [], legacy_achievements: []},
        '/api/mini/chats?limit=50': {items: [{chat_id: '42', title: 'Личная игра', type: 'private'}], has_more: false}, '/api/mini/runtime': {connected: true, messages: []},
        '/api/mini/alchemy': {discovered: 12, chapters: 3, achievements: 2, points_total: 24, rank: 2, total_players: 5,
            points_today: 6, daily_limit: 30, remaining_today: 24, daily_goal: {target: 10, progress: 6, done: false}},
        '/api/mini/alchemy/leaderboard?limit=20': {items: [{rank: 1, display_name: 'Игрок', discovered: 12, is_me: true}]},
        '/api/mini/achievements': {summary: {earned: 1, available: 2, chat_achievements: 1, streak_achievements: 1},
            chats: [{chat_id: '42', title: 'Личная игра', earned: 1, available: 1,
                items: [{kind: 'chat', threshold: 25, title: '25 очков', earned: true, awarded_at: null, message: 'Молодец'}]}],
            streak: {best: 3, earned: 1, available: 1,
                items: [{kind: 'streak', threshold: 3, title: '3 подряд', earned: true, awarded_at: null, message: 'Серия'}]}},
        '/api/mini/history': {games: [], answers: [], chats: [{chat_id: '42', title: 'Личная игра', answered: 3, correct: 2, score: '12.000', last_answer_at: null}]},
        '/api/mini/categories': {items: ['История', 'Наука']},
        '/api/mini/chats/42/games': {items: []},
        '/api/mini/chats/42/details': {settings_revision: 3, can_edit: true,
            me: {score: '12.000', answered: 3, correct: 2, accuracy: 66.7, streak: 1, best_streak: 2,
                rank: 2, members: 4, achievements_earned: 1, achievements_available: 2,
                first_answer_at: null, last_answer_at: null},
            classic: {questions: 7, seconds: 45, interval: 12, announce: false, announce_delay: 4, category_mode: 'all', categories: [], random_categories: 3},
            daily: {enabled: false, times_msk: [], timezone: 'Europe/Moscow', num_questions: 10, interval_seconds: 60, poll_open_seconds: 600, categories_mode: 'random', specific_categories: [], num_random_categories: 3},
            wisdom: {enabled: false, time: '09:00'}, auto_delete: true},
    };
    runInNewContext(source('app.js'), {
        window: {QuizTelegram: ui, QuizGame: {stop() {}, async mount(options) { mounts.push(options); }}, Telegram: {WebApp: {BackButton: {hide() {}, show() {}}, initDataUnsafe: {start_param: startParam}}}},
        document: {getElementById: id => ids[id], createElement: tag => new Element(tag), querySelector: () => brand},
        fetch: async path => { assert.ok(path in fixtures || path in overrides, path);
            const override = overrides[path];
            if (override) return {ok: override.status < 400, status: override.status, json: async () => override.body ?? {detail: 'Отказ'}};
            return {ok: true, status: 200, json: async () => fixtures[path]}; },
        AbortController, setTimeout: schedule, clearTimeout: cancel, queueMicrotask, Intl, console,
    });
    await flush(); await findButton(ids.content, 'Войти как dev-игрок').click(); await flush();
    const tab = page => ids.navigation.children.find(n => n.dataset.page === page);
    return {...ids, ui, mounts, tab, timers};
}

test('home restores the heading and keeps global settings inside profile', async () => {
    const app = await application();
    assert.equal(app.content.querySelector('h1').textContent, 'Ну что, сыграем?');
    assert.doesNotMatch(app.content.textContent, /Настройки и расписание|Есть минутка|Темы квиза/);
    findButton(app.content, 'Играть в квиз').click(); await flush();
    assert.equal(app.mounts.at(-1).command, '/quiz');
    assert.equal(app.mounts.at(-1).settings, false);
    app.tab('profile').click(); await flush();
    assert.equal(app.content.querySelectorAll('select').length, 0);
    assert.doesNotMatch(app.content.textContent, /Тактильный отклик|Выйти/);
    findButton(app.content, 'Настройки').click(); await flush();
    assert.equal(app.content.querySelector('h1').textContent, 'Настройки');
    assert.equal(app.tab('profile').attrs['aria-current'], 'page');
    const theme = app.content.querySelectorAll('select').find(node => node.value === 'system'); theme.value = 'light'; theme.events.change();
    assert.equal(app.ui.prefs.theme, 'light');
    const haptics = findButton(app.content, 'Тактильный отклик'); haptics.click();
    assert.equal(haptics.attrs['aria-pressed'], 'false');
    assert.ok(app.content.querySelectorAll('input').length > 10);
    assert.doesNotMatch(app.content.textContent, /Расписание.*Темы квиза/);
    assert.equal(app.mounts.length, 1);
    app.ui.back(); await flush(); assert.equal(app.content.querySelector('h1').textContent, 'Игрок');
    app.tab('home').click(); await flush(); app.ui.settings(); await flush();
    assert.equal(app.content.querySelector('h1').textContent, 'Настройки');
    assert.match(app.content.textContent, /Темы обычного квиза/);
});

test('deep link opens the requested page and falls back on unknown parameters', async () => {
    const achievements = await application(true, 'achievements');
    assert.equal(achievements.content.querySelector('h1').textContent, 'Достижения');
    const history = await application(true, 'history');
    assert.equal(history.content.querySelector('h1').textContent, 'История');
    const fallback = await application(true, 'не-страница');
    assert.equal(fallback.content.querySelector('h1').textContent, 'Ну что, сыграем?');
});

test('deep link to a chat shows personal statistics and reports a lost chat', async () => {
    const app = await application(true, 'chat_n42');
    assert.match(app.content.textContent, /Твоя статистика в этом чате/);
    assert.match(app.content.textContent, /Достижения чата: 1 из 2/);
    assert.match(app.content.textContent, /место 2 из 4/);
    const lost = await application(true, 'chat_n999');
    assert.match(lost.content.textContent, /Чат из ссылки недоступен/);
});

test('expired session sends the player back to login and keeps working after it', async () => {
    const app = await application(true, '', {manualTimers: true,
        overrides: {'/api/mini/session/renew': {status: 401, body: {detail: 'Сессия завершена'}}}});
    const renewal = app.timers.find(timer => timer.delay === 600000);
    assert.ok(renewal, 'продление сессии должно быть запланировано заранее');
    assert.equal(app.content.querySelector('h1').textContent, 'Ну что, сыграем?');   // до истечения — рабочий экран
    await renewal.callback(); await flush(); await flush();
    assert.match(app.content.textContent, /Сессия истекла/);
    assert.ok(findButton(app.content, 'Войти как dev-игрок'), 'нужен вход заново');
});

test('expired session returns to login while a server error keeps the session', async () => {
    const expired = await application(true, '', {overrides: {'/api/mini/progress': {status: 401, body: {detail: 'Сессия завершена'}}}});
    assert.ok(findButton(expired.content, 'Войти как dev-игрок'), '401 возвращает ко входу');
    assert.doesNotMatch(expired.content.textContent, /Повторить/);
    const working = await application();
    assert.equal(working.content.querySelector('h1').textContent, 'Ну что, сыграем?');   // контроль: без подмены вход не теряется
    const broken = await application(true, '', {overrides: {'/api/mini/chats?limit=50': {status: 500, body: {detail: 'База недоступна'}}}});
    assert.ok(findButton(broken.content, 'Повторить'), '500 оставляет сессию и предлагает повтор');
    assert.doesNotMatch(broken.content.textContent, /Войти как dev-игрок/);
});

test('read-only preview keeps appearance settings without enabling game writes', async () => {
    const app = await application(false); app.ui.settings(); await flush();
    assert.match(app.content.textContent, /через чатового бота/);
    assert.equal(app.content.querySelectorAll('select').length, 2);
    assert.equal(app.mounts.length, 0);
    assert.ok(!app.content.querySelectorAll('button').some(n => n.textContent === 'Параметры и расписание'));
});

for (const settings of [false, true]) test(`shared menu uses the correct hierarchy (settings=${settings})`, async () => {
    const host = new Element('main'), window = {}; let returned = false;
    runInNewContext(source('game-ui.js'), {window, document: {createElement: tag => new Element(tag)},
        setTimeout: () => 1, clearTimeout() {}, setInterval: () => 1, clearInterval() {}, URL, console});
    await window.QuizGame.mount({host, settings, selection() {}, onHome() { returned = true; },
        request: async () => ({connected: true, server_time: 0, requests: [], photo_round: null, messages: [{id: 1, text: 'Меню', buttons: [
            [{text: 'Настройки', data: 'nav:settings'}], [{text: 'Главное меню', data: 'nav:home'}],
        ]}, {id: 2, text: 'Меню расписания', buttons: [[{text: 'Время запуска', data: 'admcfg_daily_manage_times'}]]}]})});
    assert.equal(host.querySelector('h1').textContent, settings ? 'Игра и расписание' : 'Твоя игра');
    const keyboard = host.querySelector('.game-keyboard');
    assert.doesNotMatch(keyboard.textContent, /Настройки/);
    assert.equal(keyboard.childElementCount, 1);
    findButton(keyboard, 'Главное меню').click(); assert.equal(returned, true);
    assert.equal(host.querySelector('.game-tools').childElementCount, settings ? 0 : 3);
    assert.equal(host.textContent.includes('Время запуска'), settings);
    window.QuizGame.stop();
});

function player() {
    const window = {}, document = {createElement: tag => new Element(tag)};
    runInNewContext(source('play-ui.js'), {window, document, setTimeout: () => 1, clearTimeout() {}, setInterval: () => 1, clearInterval() {}, URL, Intl, crypto: require('node:crypto').webcrypto});
    return window.QuizPlay;
}
function round() {
    return {connected: true, server_time: Date.now() / 1000, requests: [], photo_round: null,
        games: [{key: 'safe-key', kind: 'classic', status: 'active', current: 1, total: 2, started_at: 100, points: '0', correct: 0, poll_ids: ['p1']}],
        messages: [{id: 1, at: 20, text: 'OLD BOT TRANSCRIPT'}, {id: 2, at: 101, text: '', buttons: [], poll: {id: 'p1', question: '2 * 2?', options: ['4', '5'], ends_at: Date.now() / 1000 + 60, closed: false}}]};
}

test('player presents one current question, not a transcript; one tap submits once', async () => {
    const ui = player(), host = new Element('main'), data = round(), sent = [];
    const request = async (path, options) => {
        if (options) { const action = JSON.parse(options.body); sent.push(action); data.requests = [{id: action.request_id, status: 'done'}]; data.messages[1].feedback = {correct: true, selected: 0, answer: 0, points: '1', explanation: 'Two pairs.'}; }
        return data;
    };
    await ui.mount({host, request, selection() {}, onHome() {}, onReplay() {}, onProfile() {}});
    assert.doesNotMatch(host.textContent, /OLD BOT TRANSCRIPT|Главное меню|Остановить фото/);
    assert.equal(host.querySelector('h1').textContent, '2 * 2?');
    assert.equal(host.querySelectorAll('.play-option').length, 2);
    host.querySelectorAll('.play-option')[0].click(); await flush();
    assert.equal(sent.length, 1); assert.equal(sent[0].type, 'vote'); assert.equal(sent[0].value, 0);
    assert.match(host.textContent, /Есть! Именно так.|Two pairs/);
    assert.equal(host.querySelectorAll('.play-option').every(b => b.disabled), true);
    ui.stop();
});

test('shared classic endpoint wins over the Telegram transcript and answers directly', async () => {
    const ui = player(), host = new Element('main'), data = round(), answers = [];
    let shared = {phase: 'active', game: {current: 1, total: 2}, question: {
        poll_id: 'shared-poll', question: 'Категория: Космос\nКто ведёт квиз?',
        options: ['Луна', 'Сова'], ends_at: new Date(Date.now() + 60000).toISOString(),
        answered: false, selected_option: null, closed: false,
    }};
    const request = async (path, options) => {
        if (path === '/api/mini/runtime') return data;
        if (path.includes('/classic/') && path.endsWith('/sync')) return shared;
        if (path.includes('/photo/') && path.endsWith('/current')) return null;
        if (path.includes('/classic/') && path.endsWith('/answer')) {
            answers.push(JSON.parse(options.body));
            shared = {...shared, question: {...shared.question, answered: true, selected_option: 1,
                correct_option: 1, is_correct: true, points: '1', explanation: 'Наш Филиныч.'}};
            return {applied: true, question: shared.question, points: '1'};
        }
        throw new Error('Unexpected path ' + path);
    };
    await ui.mount({host, request, chatId: '-1001', selection() {}, onHome() {}, onReplay() {}, onProfile() {}});
    assert.equal(host.querySelector('h1').textContent, 'Кто ведёт квиз?');
    assert.doesNotMatch(host.textContent, /2 \* 2\?|OLD BOT TRANSCRIPT/);
    host.querySelectorAll('.play-option')[1].click(); await flush(); await flush();
    assert.equal(answers.length, 1);
    assert.equal(answers[0].poll_id, 'shared-poll');
    assert.equal(answers[0].selected_option, 1);
    assert.match(answers[0].command_id, /^[0-9a-f-]{36}$/);
    assert.match(host.textContent, /Есть! Именно так.|Наш Филиныч/);
    ui.stop();
});

test('native model distinguishes setup, active round, result and ignores earlier menus', () => {
    const ui = player(), data = round();
    data.messages.unshift({id: 3, at: 10, text: 'OLD SETTINGS', buttons: [[{text: 'Start', data: 'qcfg_start'}]]});
    assert.equal(ui.model(data).phase, 'question');
    data.games[0].status = 'completed'; assert.equal(ui.model(data).phase, 'result');
    data.messages.push({id: 4, at: 200, text: 'Настройка викторины', buttons: [[{text: 'Start', data: 'qcfg_start'}]]});
    assert.equal(ui.model(data).phase, 'setup');
    assert.equal(ui.model({...data, games: [], messages: []}).phase, 'idle');
});

test('native preparation and results have their own surface without Telegram service copy', async () => {
    const ui = player(), host = new Element('main'), data = round();
    data.games = []; data.messages = [{id: 4, at: 200, text: 'RAW TELEGRAM CONFIGURATION', buttons: [[{text: '🔢 Вопросы: 5', data: 'qcfg_num_menu'}, {text: 'Start', data: 'qcfg_start'}]]}];
    await ui.mount({host, request: async () => data, selection() {}, onHome() {}});
    assert.match(host.textContent, /Проверим интуицию\?|Начать игру/);
    assert.doesNotMatch(host.textContent, /RAW TELEGRAM CONFIGURATION/);
    assert.equal(host.querySelector('details').children[0].textContent, 'Параметры этого раунда'); ui.stop();
    const complete = round(); complete.games[0] = {...complete.games[0], status: 'completed', points: '2.5', correct: 2};
    let replay;
    host.replaceChildren(); await ui.mount({host, request: async () => complete, selection() {}, onHome() {}, onReplay: command => { replay = command; }, onProfile() {}});
    assert.match(host.textContent, /2,5|2 правильных из 2|100%/);
    findButton(host, 'Сыграть ещё').click(); assert.equal(replay, '/quiz'); ui.stop();
});

test('photo uses an image, current hint and text input; old hints are not repeated', async () => {
    const ui = player(), host = new Element('main'), data = round();
    data.games = [{key: 'photo-safe', kind: 'photo', status: 'active', current: 1, total: 3, started_at: 100, phase: 'active', poll_ids: [], correct: 0, points: '0', question_started_at: new Date().toISOString(), time_limit: 60}];
    data.photo_round = 'photo-safe:1'; data.messages = [{id: 1, at: 101, text: 'Подсказка OLD_HINT'}, {id: 2, at: 110, media: '/photo', text: 'Слово: с _ _ а', buttons: []}, {id: 3, at: 111, text: 'Подсказка: птица'}];
    await ui.mount({host, request: async () => data, media: async () => new Blob(['image']), selection() {}, onHome() {}});
    assert.equal(host.querySelectorAll('.play-photo').length, 1); assert.equal(host.querySelectorAll('input').length, 1);
    assert.match(host.textContent, /с _ _ а|Подсказка: птица/); assert.doesNotMatch(host.textContent, /OLD_HINT|Отправьте ответ в чат/); ui.stop();
});

test('photo prefers the protected shared image projection over Telegram media', async () => {
    const ui = player(), host = new Element('main'), data = round(), loaded = [];
    data.photo_round = 'photo-safe:1'; data.games = [{key: 'photo-safe', kind: 'photo', status: 'active', current: 1, total: 2, started_at: 100, points: '0', correct: 0}];
    const photo = {phase: 'active', score: '0', correct: 0, question: {question_number: 1,
        question_count: 2, ends_at: new Date(Date.now() + 60000).toISOString(), closed: false,
        mask: 'С⬜⬜⬜', image_url: '/api/mini/photo/chats/-1001/current/image'}};
    await ui.mount({host, chatId: '-1001', request: async path => {
        if (path === '/api/mini/runtime') return data;
        if (path.includes('/photo/')) return photo;
        return null;
    }, media: async path => { loaded.push(path); return new Blob(['shared-image']); }, selection() {}, onHome() {}});
    await flush();
    assert.equal(host.querySelectorAll('.play-photo').length, 1);
    assert.equal(host.querySelectorAll('input').length, 1);
    assert.match(host.textContent, /С⬜⬜⬜|общей игровой сессии/);
    assert.deepEqual(loaded, ['/api/mini/photo/chats/-1001/current/image']);
    ui.stop();
});

test('an ambiguous send retries the same request id rather than another answer', async () => {
    const ui = player(), host = new Element('main'), data = round(), sent = [];
    await ui.mount({host, selection() {}, onHome() {}, request: async (path, options) => {
        if (options) { const action = JSON.parse(options.body); sent.push(action); if (sent.length === 1) throw new Error('Offline'); data.requests = [{id: action.request_id, status: 'done'}]; }
        return data;
    }});
    host.querySelectorAll('.play-option')[0].click(); await flush();
    findButton(host, 'Проверить отправку').click(); await flush();
    assert.equal(sent.length, 2); assert.equal(sent[0].request_id, sent[1].request_id); ui.stop();
});
