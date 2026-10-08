// Navigation unit tests: a small DOM double, no browser or Telegram requests.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {join} = require('node:path');
const {runInNewContext} = require('node:vm');

class Element {
    constructor(tag) { this.tag = tag; this.children = []; this.dataset = {}; this.attrs = {}; this.events = {}; this.className = ''; this.text = '';
        // Карточки главной выставляют object-position через style — заглушка должна это выдерживать.
        this.style = {};
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
    insertBefore(node, reference) { const index = this.children.indexOf(reference); this.children.splice(index < 0 ? this.children.length : index, 0, node); }
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
const GAME_MODES = [
    ['classic', 'Классический квиз', 'available'], ['photo', 'Фото-загадки', 'available'],
    ['night', 'Ночной город', 'development'], ['atlas', 'Атлас маленьких чудес', 'available'],
    ['farm', 'Весёлый фермер', 'coming_soon'],
].map(([id, title, status]) => ({id, title, status, interfaces: [], capabilities: []}));
const findButton = (root, label) => {
    const found = root.querySelectorAll('button').find(n => n.textContent === label || n.textContent.startsWith(label));
    assert.ok(found, `Missing button: ${label}`); return found;
};
async function application(runtime = true, startParam = '', {overrides = {}, manualTimers = false, guestMode = false, savedGuest = false} = {}) {
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
        '/api/mini/config': {runtime_enabled: runtime, offline: true, game_modes: GAME_MODES}, '/api/dev/info': {demo: true},
        '/api/guest/start': {account_id: '00000000-0000-4000-8000-000000000001', display_name: 'Гость', authentication: 'guest', capabilities: ['guest-profile']},
        '/api/guest/me': {account_id: '00000000-0000-4000-8000-000000000001', display_name: 'Гость', authentication: 'guest', capabilities: ['guest-profile']},
        '/api/guest/logout': null,
        '/api/guest/rooms': {items: []},
        '/api/dev/session': {access_token: 'unit-test'}, '/api/mini/me': {user_id: '42', display_name: 'Игрок', score: 12, answered_count: 3},
        '/api/mini/progress': {best_streak: 2, correct_including_photo: 2, current_streak: 1, achievements: [], legacy_achievements: []},
        '/api/mini/chats?limit=50': {items: [{chat_id: '42', title: 'Личная игра', type: 'private'}], has_more: false}, '/api/mini/runtime': {connected: true, messages: []},
        '/api/mini/alchemy': {discovered: 12, chapters: 3, achievements: 2, points_total: 24, rank: 2, total_players: 5,
            points_today: 6, daily_limit: 30, remaining_today: 24, daily_goal: {target: 10, progress: 6, done: false, streak: 3}},
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
    let authCookie = false; const requests = [];
    runInNewContext(source('app.js'), {
        window: {QuizTelegram: ui, QuizGame: {stop() {}, async mount(options) { mounts.push(options); }}, Telegram: {WebApp: {BackButton: {hide() {}, show() {}}, initDataUnsafe: {start_param: startParam}}}},
        document: {getElementById: id => ids[id], createElement: tag => new Element(tag), querySelector: () => brand},
        fetch: async (path, options = {}) => { requests.push({path, options}); assert.ok(path in fixtures || path in overrides || `${path}:${options.method || 'GET'}` in overrides, path);
            if (path === '/api/dev/session') authCookie = true;
            if (path === '/api/mini/me' && !authCookie) return {ok: false, status: 401, json: async () => ({detail: 'Нет сессии'})};
            const candidate = overrides[`${path}:${options.method || 'GET'}`] || overrides[path];
            const override = typeof candidate === 'function' ? await candidate(options) : candidate;
            if (override) return {ok: override.status < 400, status: override.status, json: async () => override.body ?? {detail: 'Отказ'}};
            if (path === '/api/guest/me' && !savedGuest) return {ok: false, status: 401, json: async () => ({detail: 'Нет гостевой сессии'})};
            if (path === '/api/guest/logout') return {ok: true, status: 204};
            return {ok: true, status: 200, json: async () => fixtures[path]}; },
        AbortController, crypto: {randomUUID: (() => { let id = 0; return () => `00000000-0000-4000-8000-${String(++id).padStart(12, '0')}`; })()},
        setTimeout: schedule, clearTimeout: cancel, queueMicrotask, Intl, console,
    });
    await flush();
    if (!guestMode && !savedGuest) { await findButton(ids.content, 'Войти как dev-игрок').click(); await flush(); }
    const tab = page => ids.navigation.children.find(n => n.dataset.page === page);
    return {...ids, ui, mounts, tab, timers, requests};
}

const guestRoom = {id: 'room-test', title: 'Компания', role: 'member'};
const guestMafiaBase = '/api/guest/rooms/room-test/mafia';
const guestLobby = () => ({revision: 4, phase_revision: 2, status: 'lobby', players: [{name: 'Гость', is_me: true, ready: false, alive: true}], joined: true, is_host: true, can_start: true});
const guestMafiaOverrides = (lobby, extra = {}) => ({
    '/api/guest/rooms': {status: 200, body: {items: [guestRoom]}},
    [guestMafiaBase + '/lobby']: {status: 200, body: {lobby}},
    [guestMafiaBase + '/discussion']: {status: 200, body: {items: [], enabled: true}},
    ...extra,
});

test('standalone Mafia reuses the table and sends guest readiness and start without Telegram identity', async () => {
    const app = await application(true, '', {savedGuest: true, manualTimers: true, overrides: guestMafiaOverrides(guestLobby(), {
        [guestMafiaBase + '/lobby/ready:POST']: {status: 200, body: {lobby: guestLobby()}},
        [guestMafiaBase + '/lobby/start:POST']: {status: 200, body: {lobby: guestLobby()}},
    })});
    await findButton(app.content, 'Открыть Ночной город').click();
    assert.match(app.content.textContent, /Ночной город|Стол игроков/);
    assert.doesNotMatch(app.content.textContent, /Состав дела|Telegram-группе/);
    await findButton(app.content, 'Я готов').click();
    await findButton(app.content, 'Начать ночь').click();
    const writes = app.requests.filter(r => r.path.startsWith(guestMafiaBase) && r.options.method === 'POST');
    assert.deepEqual(writes.map(r => JSON.parse(r.options.body)), [{ready: true, expected_revision: 4}, {expected_revision: 4}]);
    for (const {options} of writes) { assert.equal(options.headers['X-Guest-CSRF'], '1'); assert.ok(options.headers['Idempotency-Key']); }
    assert.ok(!app.requests.some(r => r.path.includes('/api/mini/mafia')));
});

test('standalone Mafia creates or joins with an empty command and limits creation to room owner', async () => {
    for (const owner of [true, false]) {
        const lobby = owner ? null : {...guestLobby(), joined: false};
        const suffix = owner ? '/lobby' : '/lobby/join';
        const app = await application(true, '', {savedGuest: true, manualTimers: true, overrides: guestMafiaOverrides(lobby, {
            '/api/guest/rooms': {status: 200, body: {items: [{...guestRoom, role: owner ? 'owner' : 'member'}]}},
            '/api/guest/rooms/room-test/invites': {status: 200, body: {items: []}},
            [guestMafiaBase + suffix + ':POST']: {status: 200, body: {lobby: guestLobby()}},
        })});
        await findButton(app.content, 'Открыть Ночной город').click();
        await findButton(app.content, owner ? 'Создать лобби' : 'Сесть за стол').click();
        assert.deepEqual(JSON.parse(app.requests.find(r => r.path === guestMafiaBase + suffix && r.options.method === 'POST').options.body), {});
    }
});

test('standalone Mafia sends private targets, votes, phase advancement and restart through guest scope', async () => {
    for (const [phase, label, suffix] of [['night', 'Цель', '/action'], ['voting', 'Цель', '/vote'], ['day', 'Открыть голосование', '/advance'], ['finished', 'Собрать реванш', '/restart']]) {
        const lobby = {...guestLobby(), status: phase, can_advance: true};
        const app = await application(true, '', {savedGuest: true, manualTimers: true, overrides: guestMafiaOverrides(lobby, {
            [guestMafiaBase + '/role']: {status: 200, body: {phase, role: 'mafia', title: 'Мафия', round: 1, alive: true, targets: [{name: 'Цель', seat: 'p2'}]}},
            [guestMafiaBase + suffix + ':POST']: {status: 200, body: {lobby}},
        })});
        await findButton(app.content, 'Открыть Ночной город').click();
        await findButton(app.content, label).click();
        const body = JSON.parse(app.requests.find(r => r.path === guestMafiaBase + suffix && r.options.method === 'POST').options.body);
        assert.deepEqual(body, ['night', 'voting'].includes(phase) ? {target: 'p2', expected_revision: 2} : {expected_revision: 4});
    }
});

test('standalone Mafia preserves an uncertain discussion command across retry and room navigation', async () => {
    let attempts = 0;
    const app = await application(true, '', {savedGuest: true, manualTimers: true, overrides: guestMafiaOverrides(guestLobby(), {
        [guestMafiaBase + '/discussion:POST']: () => { if (++attempts === 1) throw new TypeError('network'); return {status: attempts === 2 ? 503 : 200, body: {}}; },
    })});
    await findButton(app.content, 'Открыть Ночной город').click();
    app.content.querySelector('textarea').value = 'Привет';
    await findButton(app.content, 'Отправить').click();
    assert.ok(findButton(app.feedback, 'Проверить / повторить'));
    await findButton(app.content, 'К комнатам').click(); await flush();
    await findButton(app.content, 'Открыть Ночной город').click();
    await findButton(app.feedback, 'Проверить / повторить').click();
    await findButton(app.feedback, 'Проверить / повторить').click();
    const sent = app.requests.filter(r => r.path === guestMafiaBase + '/discussion' && r.options.method === 'POST');
    assert.equal(sent.length, 3);
    assert.equal(sent[0].options.headers['Idempotency-Key'], sent[1].options.headers['Idempotency-Key']);
    assert.equal(sent[0].options.headers['Idempotency-Key'], sent[2].options.headers['Idempotency-Key']);
    assert.equal(sent[0].options.body, sent[1].options.body);
});

test('standalone Mafia ignores a late role response after returning to rooms', async () => {
    let release, started;
    const waiting = new Promise(resolve => { started = resolve; });
    const app = await application(true, '', {savedGuest: true, manualTimers: true, overrides: guestMafiaOverrides({...guestLobby(), status: 'night'}, {
        [guestMafiaBase + '/role']: () => { started(); return new Promise(resolve => { release = resolve; }); },
    })});
    const opening = findButton(app.content, 'Открыть Ночной город').click();
    await waiting;
    await findButton(app.content, 'К комнатам').click(); await flush();
    release({status: 200, body: {phase: 'night', title: 'Секретная роль', role: 'citizen', alive: true}});
    await opening;
    assert.match(app.content.textContent, /Твои комнаты/);
    assert.doesNotMatch(app.content.textContent, /Секретная роль|Полный ход дела/);
});

test('standalone Mafia polling preserves discussion drafts and stops after leaving the room', async () => {
    const app = await application(true, '', {savedGuest: true, manualTimers: true, overrides: guestMafiaOverrides(guestLobby())});
    await findButton(app.content, 'Открыть Ночной город').click();
    const before = app.requests.length;
    const poll = app.timers.find(t => t.delay === 5000);
    assert.ok(poll);
    app.content.querySelector('textarea').value = 'Пишу сообщение';
    poll.callback(); await flush();
    assert.equal(app.requests.length, before);
    assert.equal(app.content.querySelector('textarea').value, 'Пишу сообщение');
    app.content.querySelector('textarea').value = '';
    app.timers.filter(t => t.delay === 5000).at(-1).callback(); await flush();
    assert.ok(app.requests.length > before);
    const nextPoll = app.timers.filter(t => t.delay === 5000).at(-1);
    await findButton(app.content, 'К комнатам').click(); await flush();
    const after = app.requests.length;
    nextPoll.callback(); await flush();
    assert.equal(app.requests.length, after);
});

test('guest starts in a browser, resumes and logs out without a Telegram session', async () => {
    const fresh = await application(true, '', {guestMode: true});
    assert.ok(findButton(fresh.content, 'Продолжить как гость'));
    await findButton(fresh.content, 'Продолжить как гость').click(); await flush();
    assert.match(fresh.content.textContent, /Гостевой профиль/);
    assert.ok(findButton(fresh.content, 'Открыть Алхимию'));
    assert.ok(findButton(fresh.content, 'Создать комнату'));
    assert.doesNotMatch(fresh.content.textContent, /Твои чаты|Гонка за знаниями/);
    const resumed = await application(true, '', {savedGuest: true});
    assert.match(resumed.content.textContent, /Гостевой профиль/);
    await findButton(resumed.content, 'Выйти и потерять доступ к гостю').click(); await flush();
    assert.ok(findButton(resumed.content, 'Продолжить как гость'));
});

test('guest creates an account-owned room with retry-stable id and guest CSRF', async () => {
    const app = await application(true, '', {guestMode: true, overrides: {
        '/api/guest/rooms:POST': {status: 200, body: {id: '00000000-0000-4000-8000-000000000001', title: 'Компания', kind: 'standalone'}},
    }});
    await findButton(app.content, 'Продолжить как гость').click(); await flush();
    const title = app.content.querySelector('input'); title.value = 'Компания';
    await findButton(app.content, 'Создать комнату').click(); await flush(); await flush();
    const post = app.requests.find(item => item.path === '/api/guest/rooms' && item.options.method === 'POST');
    assert.ok(post);
    assert.equal(post.options.headers['X-Guest-CSRF'], '1');
    assert.equal(JSON.parse(post.options.body).request_id, '00000000-0000-4000-8000-000000000001');
    assert.equal(JSON.parse(post.options.body).title, 'Компания');
});

test('guest room owner creates and revokes invite codes; guest can join by pasted code', async () => {
    const roomId = '00000000-0000-4000-8000-000000000099';
    const inviteId = '00000000-0000-4000-8000-000000000088';
    const inviteCode = 'A'.repeat(43);
    const app = await application(true, '', {guestMode: true, overrides: {
        '/api/guest/rooms': {status: 200, body: {items: [{id: roomId, title: 'Компания', role: 'owner'}]}},
        [`/api/guest/rooms/${roomId}/invites`]: {status: 200, body: {items: [{
            id: inviteId, expires_at: '2099-10-09T12:00:00+00:00', max_uses: 2, uses: 0, revoked: false,
        }]}},
        [`/api/guest/rooms/${roomId}/invites:POST`]: {status: 200, body: {
            id: inviteId, invite_code: inviteCode, expires_at: '2026-10-09T12:00:00+00:00', max_uses: 2,
        }},
        [`/api/guest/rooms/${roomId}/invites/${inviteId}:DELETE`]: {status: 204},
        '/api/guest/rooms/join:POST': {status: 200, body: {id: roomId, title: 'Компания', joined: true}},
    }});
    await findButton(app.content, 'Продолжить как гость').click(); await flush(); await flush();
    await findButton(app.content, 'Создать код').click(); await flush(); await flush();
    const createdCode = app.content.querySelectorAll('input').find(node => node.attrs['aria-label'] === 'Одноразово показанный код приглашения');
    assert.equal(createdCode?.value, inviteCode);
    const create = app.requests.find(item => item.path === `/api/guest/rooms/${roomId}/invites` && item.options.method === 'POST');
    assert.ok(create);
    assert.equal(create.options.headers['X-Guest-CSRF'], '1');
    assert.deepEqual(JSON.parse(create.options.body), {expires_in_seconds: 86400, max_uses: 5});
    const list = app.requests.filter(item => item.path === `/api/guest/rooms/${roomId}/invites` && item.options.method === 'GET');
    assert.ok(list.length);
    assert.ok(list.every(item => !item.path.includes(inviteCode)));
    await findButton(app.content, 'Отозвать').click(); await flush(); await flush();
    assert.ok(app.requests.some(item => item.path === `/api/guest/rooms/${roomId}/invites/${inviteId}` && item.options.method === 'DELETE'));

    const codeInput = app.content.querySelectorAll('input').find(node => node.attrs['aria-label'] === 'Код приглашения в комнату');
    assert.ok(codeInput);
    codeInput.value = inviteCode;
    await findButton(app.content, 'Присоединиться').click(); await flush(); await flush();
    const join = app.requests.find(item => item.path === '/api/guest/rooms/join' && item.options.method === 'POST');
    assert.ok(join);
    assert.equal(join.options.headers['X-Guest-CSRF'], '1');
    assert.deepEqual(JSON.parse(join.options.body), {invite_code: inviteCode});
});

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

test('home game cards are driven by the canonical five-mode catalog; Farmer is non-launchable', async () => {
    const app = await application();
    const cards = app.content.querySelectorAll('.game-mode-card');
    assert.equal(cards.length, 5);
    assert.deepEqual(cards.map(card => card.dataset.gameMode), ['classic', 'photo', 'night', 'atlas', 'farm']);
    assert.match(cards[0].className, /palette-green.*image-left/);
    assert.match(cards[1].className, /palette-green.*image-right/);
    assert.match(cards[2].className, /palette-brown.*image-left/);
    assert.match(cards[3].className, /palette-brown.*image-right/);
    assert.match(app.content.textContent, /Атлас маленьких чудес/);
    assert.equal(cards[4].dataset.modeStatus, 'coming_soon');
    assert.match(cards[4].textContent, /Скоро/);
    assert.equal(cards[4].querySelectorAll('button').length, 0);
});

test('home offers resume from the authenticated shared-game projection', async () => {
    const app = await application(true, '', {overrides: {
        '/api/mini/chats/42/games': {status: 200, body: {items: [{kind: 'classic', phase: 'active', question_number: 2, question_count: 5}]}},
    }});
    assert.ok(findButton(app.content, 'Вернуться в текущую игру'));
});

test('native help opens without starting QuizGame or reading the Telegram transcript', async () => {
    const app = await application(false);
    await findButton(app.content, 'Как играть').click(); await flush();
    assert.equal(app.content.querySelector('h1').textContent, 'Как играть');
    assert.ok(findButton(app.content, 'Открыть классический квиз'));
    assert.ok(findButton(app.content, 'Открыть фото-загадки'));
    assert.ok(findButton(app.content, 'Настройки'));
    assert.equal(app.mounts.length, 0);
    await findButton(app.content, 'Настройки').click(); await flush();
    assert.equal(app.content.querySelector('h1').textContent, 'Настройки');
    assert.doesNotMatch(app.content.textContent, /Открыть настройки в боте/);
    assert.equal(app.mounts.length, 0);
});

test('Mafia discussion renders messages as text and sends an idempotent player command', async () => {
    const chat = '-880000000044';
    const app = await application(true, '', {overrides: {
        '/api/mini/chats?limit=50': {status: 200, body: {items: [{chat_id: chat, title: 'Дело', type: 'supergroup'}], has_more: false}},
        '/api/mini/mafia/draft': {status: 200, body: {title: 'Ночной город', revision: 0, players: 4,
            roles: [{id: 'mafia', title: 'Мафия', count: 1}, {id: 'citizen', title: 'Мирные', count: 3}]}},
        [`/api/mini/mafia/chats/${chat}/lobby`]: {status: 200, body: {lobby: {status: 'lobby', revision: 1,
            players: [{name: '<Игрок>', is_me: true, ready: false}], joined: true, can_start: false, history: []}}},
        [`/api/mini/mafia/chats/${chat}/discussion`]: {status: 200, body: {enabled: true, items: [
            {id: 1, author: '<Игрок>', is_me: true, message: '<script>не HTML</script>', created_at: null},
        ]}},
        [`/api/mini/mafia/chats/${chat}/discussion:POST`]: {status: 200, body: {id: 2, accepted: true}},
    }});
    await findButton(app.content, 'Открыть дело').click(); await flush();
    assert.match(app.content.textContent, /<script>не HTML<\/script>/);
    const input = app.content.querySelector('textarea'); assert.ok(input);
    input.value = 'Голосуем после обсуждения';
    await findButton(app.content, 'Отправить').click(); await flush(); await flush();
    const post = app.requests.find(item => item.path === `/api/mini/mafia/chats/${chat}/discussion` && item.options.method === 'POST');
    assert.ok(post);
    assert.match(post.options.headers['Idempotency-Key'], /^[A-Za-z0-9._:-]{8,64}$/);
    assert.equal(JSON.parse(post.options.body).message, input.value);
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
    assert.match(app.content.textContent, /изменение игровых параметров.*preview отключено/i);
    assert.doesNotMatch(app.content.textContent, /Открыть настройки в боте/);
    assert.equal(app.content.querySelectorAll('select').length, 1);
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
        if (path.includes('/classic/') && path.endsWith('/sync')) return shared;
        if (path.includes('/photo/') && path.endsWith('/sync')) return null;
        if (path.includes('/classic/') && path.endsWith('/answer')) {
            answers.push(JSON.parse(options.body));
            shared = {...shared, question: {...shared.question, answered: true, selected_option: 1,
                correct_option: 1, is_correct: true, points: '1', explanation: 'Наш Филиныч.'}};
            return {applied: true, question: shared.question, points: '1'};
        }
        assert.notEqual(path, '/api/mini/runtime', 'native Classic/Photo gameplay must not load the synthetic Telegram transcript');
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

test('classic preparation loads stored settings and starts directly without runtime transcript', async () => {
    const ui = player(), host = new Element('main'), calls = [];
    let shared = null;
    const request = async (path, options = {}) => {
        calls.push(path);
        if (path === '/api/mini/chats/42/details') return {classic: {
            questions: 7, seconds: 45, interval: 12, category_mode: 'specific', categories: ['История'],
        }};
        if (path === '/api/mini/classic/chats/42/sync') {
            if (!shared) throw Object.assign(new Error('Нет активного раунда'), {status: 404});
            return shared;
        }
        if (path === '/api/mini/classic/chats/42/start') {
            shared = {status: 'active', revision: 1, game: {current: 1, total: 7}, question: {
                poll_id: 'new-poll', question: 'Первый вопрос?', options: ['Да', 'Нет'],
                ends_at: new Date(Date.now() + 60000).toISOString(), answered: false, closed: false,
            }};
            return shared;
        }
        assert.notEqual(path, '/api/mini/runtime', 'Classic setup/start must not use the synthetic Telegram transcript');
        throw new Error('Unexpected path ' + path);
    };
    await ui.mount({host, request, chatId: '42', command: '/quiz', selection() {}, onHome() {}, onReplay() {}, onProfile() {}, onSettings() {}});
    assert.match(host.textContent, /7 вопросов.*45 секунд.*Пауза 12 секунд.*Темы: История/);
    assert.ok(findButton(host, 'Настройки квиза'));
    findButton(host, 'Начать игру').click(); await flush(); await flush();
    assert.equal(calls.includes('/api/mini/runtime'), false);
    assert.equal(calls.includes('/api/mini/classic/chats/42/start'), true);
    assert.equal(host.querySelector('h1').textContent, 'Первый вопрос?');
    ui.stop();
});

test('photo preparation uses the backend setup projection and starts without runtime transcript', async () => {
    const ui = player(), host = new Element('main'), calls = [];
    let started = false;
    const game = {status: 'active', revision: 1, score: 0, game: {current: 1, total: 2}, question: {
        round_id: 'photo-round', question_number: 1, question_count: 2,
        ends_at: new Date(Date.now() + 60000).toISOString(), image_url: '/image', mask: '□ □', closed: false,
    }};
    const request = async (path, options = {}) => {
        calls.push(path);
        if (path === '/api/mini/photo/chats/42/setup') return {
            question_count: 2, open_seconds: 75, hints_enabled: false, available_questions: 8, can_start: true,
        };
        if (path === '/api/mini/photo/chats/42/sync') {
            if (!started) throw Object.assign(new Error('Нет активной серии'), {status: 404});
            return game;
        }
        if (path === '/api/mini/photo/chats/42/start') {
            started = true;
            const payload = JSON.parse(options.body);
            assert.equal(payload.question_count, 2); assert.equal(payload.open_seconds, 75); assert.equal(payload.hints_enabled, false);
            return game;
        }
        assert.notEqual(path, '/api/mini/runtime', 'Photo setup/start must not use the synthetic Telegram transcript');
        throw new Error('Unexpected path ' + path);
    };
    await ui.mount({host, request, chatId: '42', command: '/photo_quiz', selection() {}, onHome() {}, onReplay() {}, onProfile() {}, onSettings() {}, media: async () => new Blob()});
    assert.match(host.textContent, /2 картинки.*75 секунд на картинку.*Без подсказок.*Доступно загадок: 8/);
    findButton(host, 'Начать фото-серию').click(); await flush(); await flush();
    assert.equal(calls.includes('/api/mini/runtime'), false);
    assert.equal(calls.includes('/api/mini/photo/chats/42/start'), true);
    assert.equal(host.querySelector('h1').textContent, 'Что скрывается\nна картинке?');
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
