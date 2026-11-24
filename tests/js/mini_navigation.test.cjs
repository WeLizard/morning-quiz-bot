// Navigation unit tests: a small DOM double, no browser or Telegram requests.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {join} = require('node:path');
const {runInNewContext, createContext, runInContext} = require('node:vm');

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
    getAttribute(key) { return this.attrs[key]; }
    focus() { if (this.ownerDocument) this.ownerDocument.activeElement = this; }
    setSelectionRange(start, end) { this.selectionStart = start; this.selectionEnd = end; }
    removeAttribute(key) { delete this.attrs[key]; }
    addEventListener(event, callback) { this.events[event] = callback; }
    insertBefore(node, reference) { const index = this.children.indexOf(reference); this.children.splice(index < 0 ? this.children.length : index, 0, node); }
    click() {
        // HTMLElement.click() does not dispatch activation for disabled buttons.
        if (this.disabled) return;
        return (this.events.click || this.onclick)?.({currentTarget: this, preventDefault() {}});
    }
    querySelectorAll(selector) {
        const all = this.children.flatMap(child => [child, ...child.querySelectorAll('*')]);
        return all.filter(n => selector.split(',').some(s => { s = s.trim(); return s === '*' || s === n.tag || (s.startsWith('.') && n.className.split(' ').includes(s.slice(1))) || (s === '[data-deadline]' && n.dataset.deadline !== undefined); }));
    }
    querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
    scrollIntoView() {}
}
const flush = () => new Promise(resolve => setImmediate(resolve));
const source = file => readFileSync(join(__dirname, '../../web/mini_client', file), 'utf8');
const addressModule = (() => { const scope = {}; runInNewContext(source('address.js'), {globalThis: scope}); return scope.QWAddress; })();
const GAME_MODES = [
    ['classic', 'Классический квиз', 'available'], ['photo', 'Фото-загадки', 'available'],
    ['night', 'Ночной город', 'development'], ['atlas', 'Атлас маленьких чудес', 'available'],
    ['farm', 'Весёлый фермер', 'coming_soon'],
].map(([id, title, status]) => ({id, title, status, interfaces: [], capabilities: []}));
const openGuestProfile = async app => { await app.tab('profile').click(); await flush(); await flush(); };
const findButton = (root, label) => {
    const found = root.querySelectorAll('button').find(n => n.textContent === label || n.textContent.startsWith(label));
    assert.ok(found, `Missing button: ${label}`); return found;
};
const openGuestSettings = async app => { await openGuestProfile(app); await findButton(app.content, 'Настройки').click(); await flush(); await flush(); };
async function application(runtime = true, startParam = '', {overrides = {}, manualTimers = false, guestMode = false, savedGuest = false,
    farmEnabled = false, locationSearch = '', sessionValues = {}, miniCookie = false, autoLogin = true,
    historyThrows = false, replaceAvailable = true, initData = '', offline = true, assignFailures = 0, locationHash = '', nightCaseEnabled = false} = {}) {
    const ids = Object.fromEntries(['content', 'navigation', 'feedback', 'environment'].map(id => [id, new Element('div')]));
    for (const page of ['home', 'chats', 'rating', 'profile']) { const b = new Element('button'); b.dataset.page = page; ids.navigation.append(b); }
    // Shell core double: records what app.js asks of QW (back target, mode, menu account) without a real DOM.
    const qw = {rootBack: null, items: [], account: null, configs: [], mode: 'hub',
        prefs: {timezone: null, get() { return {contrast: false, timezone: this.timezone}; }, applyAccount(profile) { if (Object.hasOwn(profile || {}, 'timezone')) this.timezone = profile.timezone; },
            setContrast() {}, formatDate(value, locales, options = {}) { return new Date(value).toLocaleString(locales, {...options, timeZone: this.timezone || 'UTC'}); },
            timezonePicker({zones, selected, label, searchLabel, allowAuto}) {
                const node = new Element('div'), title = new Element('span'), search = new Element('input'), input = new Element('select');
                node.className = 'field'; title.textContent = label; search.attrs['aria-label'] = searchLabel; input.attrs['aria-label'] = label;
                const choices = [...zones]; if (allowAuto) choices.unshift(''); input.children = choices.map(value => { const option = new Element('option'); option.value = value; option.textContent = value || 'Автоматически (по устройству)'; return option; });
                input.value = selected || ''; node.append(title, search, input); return {node, input, search};
            }},
        nav: {setRoot(handler, options) { qw.rootBack = handler; qw.rootOptions = options; }},
        header: {mountBack() {}, mountGear() {}}, configure(options) { qw.configs.push(options); if (options.mode) qw.mode = options.mode; qw.onHome = options.onHome; }};
    qw.menu = {register(items, title) { qw.items = items; qw.menuTitle = title; }, setAccount(value) { qw.account = value; }};
    const brand = new Element('a'), mounts = [], ratingCalls = [], timers = [], ui = {prefs: {theme: 'system', haptics: true}, canFullscreen: true,
        configure(back, settings) { this.settings = settings; }, back: () => qw.rootBack ? qw.rootBack() : qw.mode === 'game' ? qw.onHome?.() : undefined, selection() {},
        openBot(username, action) { this.openedBot = [username, action]; return Boolean(username); },
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
        '/api/mini/config': {runtime_enabled: runtime, offline, bot_username: 'morning_quiz_bot', game_modes: farmEnabled ? GAME_MODES.map(m => m.id === 'farm' ? {...m, status: 'development'} : m) : GAME_MODES}, '/api/dev/info': {demo: true},
        '/api/guest/start': {account_id: '00000000-0000-4000-8000-000000000001', display_name: 'Гость', authentication: 'guest', capabilities: ['guest-profile']},
        '/api/guest/me': {account_id: '00000000-0000-4000-8000-000000000001', display_name: 'Гость', authentication: 'guest', capabilities: ['guest-profile']},
        '/api/guest/resume': {account_id: '00000000-0000-4000-8000-000000000001', display_name: 'Гость', authentication: 'guest', capabilities: ['guest-profile']},
        '/api/guest/logout': null, '/api/account/logout': null,
        '/api/account/sessions?identity=guest': {sessions: [], telegram_sessions: 0, has_password: false, login: null, telegram_linked: false, can_reset_password: false},
        '/api/account/sessions?identity=telegram': {sessions: [], telegram_sessions: 0, has_password: false, login: null, telegram_linked: true, can_reset_password: false},
        '/api/account/timezones': {timezones: ['UTC', 'Asia/Tokyo', 'America/Argentina/Buenos_Aires']},
        '/api/guest/rooms': {items: []},
        '/api/dev/session': {access_token: 'unit-test'}, '/api/mini/session': {access_token: 'unit-test'}, '/api/mini/session/resume': {access_token: 'unit-test'}, '/api/mini/me': {user_id: '42', account_id: 'telegram-account', display_name: 'Игрок', score: 12, answered_count: 3},
        '/api/mini/progress': {best_streak: 2, correct_including_photo: 2, current_streak: 1, achievements: [], legacy_achievements: []},
        '/api/mini/chats?limit=50': {items: [{chat_id: '42', title: 'Личная игра', type: 'private'}], has_more: false},
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
    let authCookie = false; const requests = [], assigned = [], replaced = [], replacedNavigation = [], windowEvents = new Map();
    const document = {getElementById: id => ids[id], createElement: tag => { const element = new Element(tag); element.ownerDocument = document; return element; }, querySelector: () => brand};
    const storage = new Map(Object.entries(sessionValues));
    const currentLocation = {search: locationSearch, hash: locationHash, pathname: '/app', href: 'https://qw.example/app' + locationSearch + locationHash};
    const navigationLocation = {assign(path) {
        if (assignFailures-- > 0) throw new Error('WebView navigation blocked');
        assigned.push(path);
    }};
    if (replaceAvailable) navigationLocation.replace = path => replacedNavigation.push(path);
    const sandbox = createContext({
        window: {addEventListener: (event, handler) => windowEvents.set(event, handler), QWAddress: addressModule, QW: qw, QuizTelegram: ui, QuizRating: {async render(context) { ratingCalls.push(context); }}, QuizPlay: {stop() {}, async mount(options) { mounts.push(options); }, roomApi: (roomId, request, extra) => ({kind: 'room', roomId, request, extra})}, Telegram: {WebApp: {BackButton: {hide() {}, show() {}}, initData, initDataUnsafe: {start_param: startParam}}}, location: navigationLocation},
        location: currentLocation, URL, URLSearchParams,
        history: {state: null, replaceState(state, title, path) {
            if (historyThrows) throw new Error('WebView history blocked');
            replaced.push(path);
            const url = new URL(path, 'https://qw.example');
            currentLocation.search = url.search; currentLocation.href = url.href;
        }},
        sessionStorage: {getItem: key => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, String(value)), removeItem: key => storage.delete(key)},
        localStorage: {getItem: key => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, String(value)), removeItem: key => storage.delete(key)},
        document,
        fetch: async (path, options = {}) => { requests.push({path, options}); assert.ok(path in fixtures || path in overrides || `${path}:${options.method || 'GET'}` in overrides, path);
            if (path === '/api/dev/session') authCookie = true;
            if (path === '/api/mini/me' && !authCookie && !miniCookie) return {ok: false, status: 401, json: async () => ({detail: 'Нет сессии'})};
            const candidate = overrides[`${path}:${options.method || 'GET'}`] || overrides[path];
            const override = typeof candidate === 'function' ? await candidate(options) : candidate;
            if (override) {
                if (path === '/api/mini/session/resume' && override.status < 400) authCookie = true;
                return {ok: override.status < 400, status: override.status, json: async () => override.body ?? {detail: 'Отказ'}};
            }
            if (path === '/api/mini/session/resume' && !('/api/mini/session/resume' in overrides) && !('/api/mini/session/resume:POST' in overrides))
                return {ok: false, status: 404, json: async () => ({detail: 'Профиль Telegram ещё не создан.'})};
            if (path === '/api/mini/session/resume' && options.method === 'POST') authCookie = true;
            if (path === '/api/mini/session' && options.method === 'POST') authCookie = true;
            if (path === '/api/guest/me' && !savedGuest) return {ok: false, status: 401, json: async () => ({detail: 'Нет гостевой сессии'})};
            if (path === '/api/guest/logout' || path === '/api/account/logout') return {ok: true, status: 204};
            return {ok: true, status: 200, json: async () => fixtures[path]}; },
        AbortController, crypto: {randomUUID: (() => { let id = 0; return () => `00000000-0000-4000-8000-${String(++id).padStart(12, '0')}`; })()},
        setTimeout: schedule, clearTimeout: cancel, queueMicrotask, Intl, console,
    });
    // index.html loads night-city-ui.js before app.js; both share window.
    runInContext(source('night-city-ui.js'), sandbox);
    const nightCaseMounts = [];
    if (nightCaseEnabled) sandbox.window.NightCase = {close() {}, open(options) { nightCaseMounts.push(options); }};
    runInContext(source('app.js'), sandbox);
    await flush();
    if (autoLogin && !guestMode && !savedGuest && !miniCookie && ids.content.querySelectorAll('button').some(n => n.textContent === 'Войти как dev-игрок')) {
        await findButton(ids.content, 'Войти как dev-игрок').click(); await flush();
    }
    const tab = page => ids.navigation.children.find(n => n.dataset.page === page);
    return {...ids, ui, qw, mounts, ratingCalls, tab, timers, requests, assigned, replaced, replacedNavigation, storage, currentLocation, document, windowEvents, nightCaseMounts};
}

const guestPhotoBase = '/api/guest/rooms/room-test/photo';
const guestPhotoSetup = {question_count: 3, open_seconds: 60, hints_enabled: true, available_questions: 1, can_start: true};
const guestPhotoGame = () => ({game_id: 'photo-game', revision: 1, status: 'active', correct: 0, score: '0',
    question: {round_id: 'photo-round', question_number: 1, question_count: 3, ends_at: 2000000000,
        mask: '□□□□', hint_level: 0, image_url: guestPhotoBase + '/current/image?game_id=photo-game&round_id=photo-round'}});
const guestPhotoOverrides = extra => ({
    '/api/mini/config': {status: 200, body: {room_photo_enabled: true}},
    '/api/guest/rooms': {status: 200, body: {items: [{...guestRoom, role: 'owner'}]}},
    '/api/guest/rooms/room-test/invites': {status: 200, body: {items: []}},
    [guestPhotoBase + '/setup']: {status: 200, body: guestPhotoSetup},
    ...extra,
});

test('standalone room Photo starts with explicit group policy and uses exact guest command scope', async () => {
    let current = null;
    const app = await application(true, '', {savedGuest: true, manualTimers: true, overrides: guestPhotoOverrides({
        [guestPhotoBase + '/current']: () => ({status: 200, body: {current, occupied: false}}),
        [guestPhotoBase + '/start:POST']: () => { current = guestPhotoGame(); return {status: 200, body: current}; },
        [guestPhotoBase + '/answer:POST']: () => { current = {...current, revision: 2, question: {...current.question, feedback: 'wrong'}}; return {status: 200, body: current}; },
        [guestPhotoBase + '/stop:POST']: () => { current = {...current, revision: 3, status: 'stopped', question: null}; return {status: 200, body: current}; },
    })});
    await findButton(app.content, 'Открыть фото-загадки').click();
    await findButton(app.content, 'Начать фото-серию').click();
    const input = app.content.querySelector('input'); input.value = 'Ответ'; input.events.input();
    await findButton(app.content, 'Ответить').click();
    assert.match(app.content.textContent, /Пока мимо/);
    await findButton(app.content, 'Остановить фото-серию').click();
    assert.match(app.content.textContent, /Серия завершена/);
    const writes = app.requests.filter(r => r.path.startsWith(guestPhotoBase) && r.options.method === 'POST');
    assert.deepEqual(writes.map(r => JSON.parse(r.options.body)), [
        {question_count: 3, open_seconds: 60, hints_enabled: true, answer_policy: 'group_private_deadline'},
        {game_id: 'photo-game', round_id: 'photo-round', answer: 'Ответ'},
        {game_id: 'photo-game', expected_revision: 2},
    ]);
    assert.ok(writes.every(r => r.options.headers['Idempotency-Key'] && r.options.headers['X-Guest-CSRF'] === '1'));
    assert.ok(!app.requests.some(r => r.path.includes('/api/mini/photo')));
    await app.ui.back();
});

test('standalone Photo keeps draft and focus across hints, retries media, and releases resources over five mounts', async () => {
    let current = guestPhotoGame();
    const app = await application(true, '', {savedGuest: true, manualTimers: true, overrides: guestPhotoOverrides({
        [guestPhotoBase + '/current']: () => ({status: 200, body: {current, occupied: false}}),
    })});
    const baselineTimers = app.timers.length, baselineListeners = app.windowEvents.size;
    for (let i = 0; i < 5; i++) {
        await findButton(app.content, 'Открыть фото-загадки').click();
        let input = app.content.querySelector('input'); input.value = 'Черновик'; input.events.input(); input.focus(); input.setSelectionRange(2, 4);
        const firstInput = input;
        await app.timers.find(t => t.delay === 3000).callback();
        assert.equal(app.content.querySelector('input'), firstInput);
        current = {...current, revision: current.revision + 1, question: {...current.question, mask: 'С□□□'}};
        await app.timers.find(t => t.delay === 3000).callback();
        input = app.content.querySelector('input');
        assert.equal(input.value, 'Черновик'); assert.equal(app.document.activeElement, input);
        assert.deepEqual([input.selectionStart, input.selectionEnd], [2, 4]);
        const image = app.content.querySelector('img'); image.events.error();
        assert.match(app.content.textContent, /Фото не загрузилось/);
        const requests = app.requests.length;
        await findButton(app.content, 'Повторить загрузку фото').click();
        assert.match(image.src, /&retry=1$/); assert.equal(app.requests.length, requests);
        image.events.load();
        const lateTimer = app.timers.find(t => t.delay === 3000);
        await app.ui.back(); await flush();
        app.windowEvents.get('pagehide')(); app.windowEvents.get('pagehide')();
        assert.equal(app.timers.length, baselineTimers); assert.equal(app.windowEvents.size, baselineListeners);
        const after = app.requests.length; await lateTimer.callback(); await flush();
        assert.equal(app.requests.length, after);
    }
});

test('standalone Photo retries catalog and uncertain commands without duplicating polls', async () => {
    let catalogs = 0, answers = 0, current = guestPhotoGame();
    let release;
    const app = await application(true, '', {savedGuest: true, manualTimers: true, overrides: guestPhotoOverrides({
        [guestPhotoBase + '/setup']: () => ({status: ++catalogs === 1 ? 503 : 200, body: guestPhotoSetup}),
        [guestPhotoBase + '/current']: () => release ? new Promise(resolve => { release.resolve = () => resolve({status: 200, body: {current}}); }) : ({status: 200, body: {current}}),
        [guestPhotoBase + '/answer:POST']: () => ({status: ++answers === 1 ? 503 : 200, body: current}),
    })});
    await findButton(app.content, 'Открыть фото-загадки').click();
    assert.ok(findButton(app.content, 'Повторить каталог'));
    await findButton(app.content, 'Повторить каталог').click();
    assert.equal(catalogs, 2); assert.equal(app.timers.filter(t => t.delay === 3000).length, 1);
    // Double activation of the same retry refresh waits for one request.
    release = {};
    const timer = app.timers.find(t => t.delay === 3000), before = app.requests.length;
    const first = timer.callback(), second = timer.callback(); await flush();
    assert.equal(app.requests.length, before + 1);
    release.resolve(); release = null; await Promise.all([first, second]);
    assert.equal(app.timers.filter(t => t.delay === 3000).length, 1);
    let input = app.content.querySelector('input'); input.value = 'Сова'; input.events.input();
    await findButton(app.content, 'Ответить').click();
    assert.equal(app.timers.filter(t => t.delay === 3000).length, 0);
    await app.ui.back();
    await flush();
    await findButton(app.content, 'Открыть фото-загадки').click();
    await findButton(app.content, 'Повторить команду').click();
    const writes = app.requests.filter(r => r.path === guestPhotoBase + '/answer');
    assert.equal(writes[0].options.body, writes[1].options.body);
    assert.equal(writes[0].options.headers['Idempotency-Key'], writes[1].options.headers['Idempotency-Key']);
    await app.ui.back();
});

test('standalone Photo cancels pending reads on navigation and ignores late completion', async () => {
    let pending = 0, cancelled = 0, reading = false;
    const app = await application(true, '', {savedGuest: true, manualTimers: true, overrides: guestPhotoOverrides({
        [guestPhotoBase + '/current']: options => reading ? new Promise((resolve, reject) => {
            pending++;
            options.signal.addEventListener('abort', () => { pending--; cancelled++; const error = new Error('cancelled'); error.name = 'AbortError'; reject(error); }, {once: true});
        }) : ({status: 200, body: {current: guestPhotoGame()}}),
    })});
    for (let i = 0; i < 5; i++) {
        reading = false; await findButton(app.content, 'Открыть фото-загадки').click();
        reading = true; const refresh = app.timers.find(t => t.delay === 3000).callback(); await flush();
        assert.equal(pending, 1);
        await app.ui.back(); await refresh; await flush();
        assert.equal(pending, 0); assert.equal(app.timers.length, 0);
        assert.match(app.content.textContent, /Твои комнаты/);
    }
    assert.equal(cancelled, 5);
});

test('standalone Photo hides occupied personal series and continues own game with starts disabled', async () => {
    let data = {current: null, occupied: true};
    const app = await application(true, '', {savedGuest: true, manualTimers: true, overrides: guestPhotoOverrides({
        '/api/mini/config': {status: 200, body: {room_photo_enabled: false}},
        '/api/guest/rooms': {status: 200, body: {items: [guestRoom]}},
        [guestPhotoBase + '/current']: () => ({status: 200, body: data}),
    })});
    await findButton(app.content, 'Открыть фото-загадки').click();
    assert.match(app.content.textContent, /занята другим игроком/);
    assert.equal(app.content.querySelectorAll('img,input').length, 0);
    assert.ok(!app.content.querySelectorAll('button').some(b => /Начать|Ответить|Остановить/.test(b.textContent)));
    data = {current: guestPhotoGame(), occupied: false};
    await app.timers.find(t => t.delay === 3000).callback();
    assert.ok(findButton(app.content, 'Ответить'));
    assert.ok(!app.content.querySelectorAll('button').some(b => b.textContent === 'Начать фото-серию'));
    await app.ui.back();
});

const guestRoom = {id: 'room-test', title: 'Компания', role: 'member'};

test('room member confirms leave, can cancel, and sends the displayed membership version', async () => {
    const room = {...guestRoom, membership_version: '2026-10-09T12:00:00.123456+00:00'};
    let left = false;
    const app = await application(true, '', {savedGuest: true, manualTimers: true, overrides: {
        '/api/guest/rooms': () => ({status: 200, body: {items: left ? [] : [room]}}),
        '/api/guest/rooms/room-test/leave:POST': () => { left = true; return {status: 200, body: {left: true}}; },
    }});
    await findButton(app.content, 'Выйти из комнаты').click();
    assert.match(app.content.textContent, /действующее приглашение/);
    await findButton(app.content, 'Остаться').click();
    assert.equal(app.requests.filter(r => r.path.endsWith('/leave')).length, 0);
    await findButton(app.content, 'Выйти из комнаты').click();
    await findButton(app.content, 'Подтвердить выход').click(); await flush();
    const write = app.requests.find(r => r.path.endsWith('/leave'));
    assert.deepEqual(JSON.parse(write.options.body), {membership_version: room.membership_version});
    assert.equal(write.options.headers['X-Guest-CSRF'], '1');
    assert.match(app.content.textContent, /Комнат пока нет/);
});

test('room owner has no leave action, and blocked or uncertain member leave remains retryable', async () => {
    const owner = await application(true, '', {savedGuest: true, manualTimers: true, overrides: {
        '/api/guest/rooms': {status: 200, body: {items: [{...guestRoom, role: 'owner'}]}},
        '/api/guest/rooms/room-test/invites': {status: 200, body: {items: []}},
    }});
    assert.ok(!owner.content.querySelectorAll('button').some(b => b.textContent === 'Выйти из комнаты'));
    const room = {...guestRoom, membership_version: 'version-before-rejoin'};
    let attempt = 0;
    const app = await application(true, '', {savedGuest: true, manualTimers: true, overrides: {
        '/api/guest/rooms': {status: 200, body: {items: [room]}},
        '/api/guest/rooms/room-test/leave:POST': () => ({status: ++attempt === 1 ? 503 : 409,
            body: {detail: attempt === 1 ? 'Ответ потерян' : 'Участие изменилось'}}),
    }});
    await findButton(app.content, 'Выйти из комнаты').click();
    await findButton(app.content, 'Подтвердить выход').click();
    assert.match(app.feedback.textContent, /Ответ потерян/);
    await findButton(app.content, 'Подтвердить выход').click();
    assert.match(app.feedback.textContent, /Участие изменилось/);
    const writes = app.requests.filter(r => r.path.endsWith('/leave'));
    assert.equal(writes[0].options.body, writes[1].options.body);
    assert.ok(findButton(app.content, 'Открыть Ночной город'));
    await findButton(app.content, 'Обновить комнаты').click(); await flush();
    assert.equal(app.feedback.textContent, '');
    assert.ok(findButton(app.content, 'Выйти из комнаты'));
});
test('standalone Classic starts, answers, finishes and releases its poll timer on room navigation', async () => {
    const base = '/api/guest/rooms/room-test/classic';
    let current = null;
    const game = {game_id: 'game-room', revision: 1, status: 'active', game: {current: 1, total: 1},
        question: {round_id: 'round-room', question: 'Сколько?', options: ['Два', 'Три'], ends_at: '2030-01-01T00:00:00Z', answered: false, closed: false}, scores: []};
    const app = await application(true, '', {savedGuest: true, manualTimers: true, overrides: {
        '/api/mini/config': {status: 200, body: {offline: false, room_classic_enabled: true}},
        '/api/guest/rooms': {status: 200, body: {items: [{...guestRoom, role: 'owner'}]}},
        '/api/guest/rooms/room-test/invites': {status: 200, body: {items: []}},
        [base + '/current']: () => ({status: 200, body: {current}}),
        [base + '/start:POST']: () => { current = game; return {status: 200, body: current}; },
        [base + '/answer:POST']: () => { current = {...game, question: {...game.question, answered: true, is_correct: true, correct_option: 0, points: '1'}}; return {status: 200, body: current}; },
    }});
    await findButton(app.content, 'Открыть классический квиз').click();
    assert.equal(app.timers.filter(t => t.delay === 3000).length, 1);
    await findButton(app.content, 'Начать квиз').click();
    await findButton(app.content, 'Два').click();
    assert.match(app.content.textContent, /Верно! Очки: 1/);
    assert.ok(findButton(app.content, 'Два').disabled);
    const writes = app.requests.filter(r => r.path.startsWith(base) && r.options.method === 'POST');
    assert.deepEqual(writes.map(r => JSON.parse(r.options.body)), [
        {count: 5, open_seconds: 30, interval_seconds: 0}, {game_id: 'game-room', round_id: 'round-room', selected_option: 0}]);
    assert.ok(writes.every(r => r.options.headers['Idempotency-Key'] && r.options.headers['X-Guest-CSRF'] === '1'));
    for (let i = 0; i < 5; i++) {
        const timer = app.timers.find(t => t.delay === 3000);
        await app.ui.back(); await flush();
        assert.equal(app.timers.filter(t => t.delay === 3000).length, 0);
        const before = app.requests.length; await timer.callback(); await flush();
        assert.equal(app.requests.length, before);
        await findButton(app.content, 'Открыть классический квиз').click();
        assert.equal(app.timers.filter(t => t.delay === 3000).length, 1);
    }
    current = {...current, status: 'finished', scores: [{name: 'Друг', score: '1'}]};
    await app.timers.find(t => t.delay === 3000).callback(); await flush();
    assert.match(app.content.textContent, /Викторина завершена|Друг: 1/);
    assert.equal(app.timers.filter(t => t.delay === 3000).length, 1);
    current = {...game, game_id: 'rematch', question: {...game.question, question: 'Новая партия'}};
    await app.timers.find(t => t.delay === 3000).callback(); await flush();
    assert.match(app.content.textContent, /Новая партия/);
});

test('standalone Classic preserves uncertain commands across navigation and keeps existing games playable with start flag off', async () => {
    const base = '/api/guest/rooms/room-test/classic'; let attempts = 0;
    const game = {game_id: 'g', revision: 1, status: 'active', game: {current: 1, total: 1}, question: {round_id: 'r', question: 'Вопрос', options: ['Ответ', 'Другой'], ends_at: '2030-01-01T00:00:00Z'}, scores: []};
    const app = await application(true, '', {savedGuest: true, manualTimers: true, overrides: {
        '/api/guest/rooms': {status: 200, body: {items: [guestRoom]}},
        [base + '/current']: {status: 200, body: {current: game}},
        [base + '/answer:POST']: () => ({status: ++attempts === 1 ? 503 : 200, body: game}),
    }});
    await findButton(app.content, 'Открыть классический квиз').click();
    await findButton(app.content, 'Ответ').click();
    assert.ok(findButton(app.content, 'Повторить команду'));
    assert.equal(app.timers.filter(t => t.delay === 3000).length, 0);
    await app.ui.back(); await flush();
    await findButton(app.content, 'Открыть классический квиз').click();
    await findButton(app.content, 'Повторить команду').click();
    const writes = app.requests.filter(r => r.path === base + '/answer');
    assert.equal(writes[0].options.body, writes[1].options.body);
    assert.equal(writes[0].options.headers['Idempotency-Key'], writes[1].options.headers['Idempotency-Key']);
    assert.ok(!app.content.querySelectorAll('button').some(b => b.textContent === 'Начать квиз'));
    assert.ok(!app.requests.some(r => r.path.includes('/api/mini/classic')));
});

test('standalone Classic keeps the accepted answer feedback when current advances immediately', async () => {
    const base = '/api/guest/rooms/room-test/classic';
    const one = {game_id: 'g', revision: 1, status: 'active', game: {current: 1, total: 2},
        question: {round_id: 'r1', question: 'Первый вопрос', options: ['Верный', 'Нет'], ends_at: '2030-01-01T00:00:00Z'}, scores: []};
    let current = one;
    const app = await application(true, '', {savedGuest: true, manualTimers: true, overrides: {
        '/api/mini/config': {status: 200, body: {guest_enabled: true, private_test: true}},
        '/api/guest/rooms': {status: 200, body: {items: [guestRoom]}},
        [base + '/current']: () => ({status: 200, body: {current}}),
        [base + '/answer:POST']: () => {
            current = {...one, game: {current: 2, total: 2}, question: {...one.question, round_id: 'r2', question: 'Второй вопрос'}};
            return {status: 200, body: {...current, accepted_answer: {...one.question, answered: true, is_correct: true, correct_option: 0, points: '1.3', explanation: 'Пояснение первого'}}};
        },
    }});
    await findButton(app.content, 'Открыть классический квиз').click();
    await findButton(app.content, 'Верный').click();
    assert.match(app.content.textContent, /Второй вопрос/);
    assert.match(app.content.textContent, /Твой ответ на предыдущий вопрос|Верно! Очки: 1.3|Пояснение первого/);
    assert.ok(!app.requests.some(r => r.path.includes('/api/mini/classic')));
});

test('standalone Classic displays the final submitted answer after game completion', async () => {
    const base = '/api/guest/rooms/room-test/classic';
    const accepted = {round_id: 'final', question: 'Последний вопрос', options: ['Верный', 'Нет'],
        ends_at: '2020-01-01T00:00:00Z', answered: true, is_correct: true, correct_option: 0, points: '1', explanation: 'Последнее пояснение'};
    const app = await application(true, '', {savedGuest: true, manualTimers: true, overrides: {
        '/api/guest/rooms': {status: 200, body: {items: [guestRoom]}},
        [base + '/current']: {status: 200, body: {current: {game_id: 'g', revision: 2, status: 'finished', game: {current: 1, total: 1}, question: accepted, scores: []}}},
    }});
    await findButton(app.content, 'Открыть классический квиз').click();
    for (const text of ['Викторина завершена', 'Последний вопрос', 'Верно! Очки: 1', 'Последнее пояснение']) assert.ok(app.content.textContent.includes(text), text);
});
// «Ночной город» (night-city-ui.js): one entry for Telegram and browser, rooms, invitations and links, the short
// mafia test game as a thin layer over the kit. Room routes carry the channel explicitly (?identity=).
const ncModule = () => { const scope = {window: {}, document: {}, URL}; runInNewContext(source('night-city-ui.js'), scope); return scope.window.NightCity; };
const ncRoomId = 'room-test';
const NCB = `/api/guest/rooms/${ncRoomId}`;
const ncq = (path, identity = 'guest') => `${path}?identity=${identity}`;
const ncRoom = (extra = {}) => ({id: ncRoomId, title: 'Пятничный стол', role: 'owner', membership_version: 'v1', open: false, ...extra});
const ncPlayers = () => [
    {name: 'Гость', seat: 'p1', portrait: 1, ready: false, is_me: true, alive: true},
    {name: 'Марина', seat: 'p2', portrait: 2, ready: true, is_me: false, alive: true},
    {name: 'Лёша', seat: 'p3', portrait: 3, ready: true, is_me: false, alive: true},
    {name: 'Вера', seat: 'p4', portrait: 4, ready: true, is_me: false, alive: true},
];
const ncLobby = (extra = {}) => ({status: 'lobby', revision: 4, phase_revision: 2, server_now: 1000, joined: true, is_host: true, can_start: true,
    min_players: 4, ready_count: 3, start_requires_all_ready: false, portrait_count: 12, players: ncPlayers(), waiting: [], is_waiting: false, ...extra});
const ncOverrides = (lobby, extra = {}, room = ncRoom()) => ({
    [ncq('/api/guest/rooms')]: {status: 200, body: {items: [room]}},
    [ncq('/api/guest/rooms/open')]: {status: 404, body: {detail: 'Комната не найдена.'}},
    [ncq(`${NCB}/mafia/lobby`)]: {status: 200, body: {lobby}},
    [ncq(`${NCB}/mafia/discussion`)]: {status: 200, body: {items: [], enabled: true}},
    ...extra,
});
const ncWrites = (app, suffix) => app.requests.filter(r => r.path === ncq(`${NCB}/mafia${suffix}`) && r.options.method === 'POST');
async function ncEntry(app) { await findButton(app.content, 'Открыть дело').click(); await flush(); await flush(); }
async function ncTable(app) { await ncEntry(app); await findButton(app.content, 'Открыть').click(); await flush(); await flush(); await flush(); }

test('Case enabled opens the weekly case with no Mafia prototype entry, even when the server allows it', async () => {
    const overrides = ncOverrides(ncLobby(), {
        '/api/night-case/bootstrap?identity=guest': {status: 200, body: {enabled: true, capabilities: {legacy_mafia: true}}},
    });
    const app = await application(true, '', {savedGuest: true, manualTimers: true, nightCaseEnabled: true, overrides});
    await ncEntry(app);
    assert.equal(app.nightCaseMounts.length, 1);
    assert.equal(app.nightCaseMounts[0].openLegacy, undefined);
    assert.ok(!app.requests.some(row => row.path.includes('/mafia/')));
});

test('Night City entry is one screen for Telegram and the browser: company, invitation, rooms, open tables, Telegram group', async () => {
    const app = await application(true, '', {savedGuest: true, manualTimers: true, overrides: ncOverrides(ncLobby())});
    await ncEntry(app);
    assert.equal(app.qw.mode, 'game');
    assert.equal(app.content.dataset.page, 'night');
    for (const text of ['Город засыпает', 'Войти по приглашению', 'Твои комнаты', 'Пятничный стол', 'Играть в Telegram-группе'])
        assert.ok(app.content.textContent.includes(text), text);
    assert.ok(findButton(app.content, 'Собрать компанию'));
    assert.doesNotMatch(app.content.textContent, /групповой чат|только черновик|Открытые столы/, 'no dead end; open tables hide while the route is absent');
    assert.ok(app.requests.some(r => r.path === ncq('/api/guest/rooms')));
    assert.ok(!app.requests.some(r => r.path.includes('/api/mini/mafia')));
    assert.equal(app.content.querySelectorAll('.nc-bar').length, 1);
});

test('open tables list seats, waits and full tables; sitting down needs no code', async () => {
    const tables = [
        {room_id: 'open-1', title: 'Поздний рейс', host_name: 'Гоша', seated: 3, waiting: 0, needs_from: 4, capacity: 12, status: 'gathering', joined: false},
        {room_id: 'open-2', title: 'Тихий переулок', host_name: 'Кира', seated: 8, waiting: 1, needs_from: 4, capacity: 12, status: 'playing', joined: false},
        {room_id: 'open-3', title: 'Большая игра', host_name: 'Олег', seated: 12, waiting: 0, needs_from: 4, capacity: 12, status: 'full', joined: false},
    ];
    const joined = {id: 'open-1', title: 'Поздний рейс', role: 'member', membership_version: 'v2', open: true};
    const app = await application(true, '', {savedGuest: true, manualTimers: true, overrides: {
        ...ncOverrides(ncLobby()),
        [ncq('/api/guest/rooms/open')]: {status: 200, body: {items: tables}},
        [ncq('/api/guest/rooms/open-1/join-open')]: {status: 200, body: {room: joined, joined: true, seat: 'seated', lobby: ncLobby({is_host: false})}},
        [ncq('/api/guest/rooms/open-1/mafia/lobby')]: {status: 200, body: {lobby: ncLobby({is_host: false})}},
        [ncq('/api/guest/rooms/open-1/mafia/discussion')]: {status: 200, body: {items: [], enabled: true}},
    }});
    await ncEntry(app);
    assert.match(app.content.textContent, /Открытые столы/);
    assert.match(app.content.textContent, /хозяин Гоша · сидит 3 · нужно от 4/);
    assert.match(app.content.textContent, /мест нет/);
    assert.ok(findButton(app.content, 'Ждать следующую'));
    await findButton(app.content, 'Сесть за стол').click(); await flush(); await flush();
    const post = app.requests.find(r => r.path === ncq('/api/guest/rooms/open-1/join-open'));
    assert.deepEqual(JSON.parse(post.options.body), {});
    assert.ok(post.options.headers['Idempotency-Key'] && post.options.headers['X-Guest-CSRF'] === '1');
    assert.match(app.content.textContent, /Поздний рейс/);
    assert.ok(app.requests.some(r => r.path === ncq('/api/guest/rooms/open-1/mafia/lobby')));
});

test('«Собрать компанию» creates the room and the owner\'s table with idempotent empty commands', async () => {
    let lobby = null;
    const app = await application(true, '', {savedGuest: true, manualTimers: true, overrides: {
        ...ncOverrides(null),
        [ncq('/api/guest/rooms')]: {status: 200, body: {items: []}},
        [ncq('/api/guest/rooms') + ':POST']: {status: 200, body: ncRoom()},
        [ncq(`${NCB}/mafia/lobby`)]: () => ({status: 200, body: {lobby}}),
        [ncq(`${NCB}/mafia/lobby`) + ':POST']: () => { lobby = ncLobby(); return {status: 200, body: {lobby}}; },
    }});
    await ncEntry(app);
    await findButton(app.content, 'Собрать компанию').click(); await flush(); await flush(); await flush();
    const create = app.requests.find(r => r.path === ncq('/api/guest/rooms') && r.options.method === 'POST');
    assert.equal(JSON.parse(create.options.body).title, 'Ночной город');
    assert.match(JSON.parse(create.options.body).request_id, /^00000000-/);
    const table = ncWrites(app, '/lobby')[0];
    assert.deepEqual(JSON.parse(table.options.body), {});
    assert.ok(table.options.headers['Idempotency-Key'] && table.options.headers['X-Guest-CSRF'] === '1');
    assert.ok(findButton(app.content, 'Начать ночь'));
    assert.equal(typeof app.qw.rootBack, 'function', 'inside a room back leads to the Night City entry');
});

test('lobby readiness and start go through the room scope with the server revision', async () => {
    const app = await application(true, '', {savedGuest: true, manualTimers: true, overrides: ncOverrides(ncLobby(), {
        [ncq(`${NCB}/mafia/lobby/ready`) + ':POST']: {status: 200, body: {lobby: ncLobby()}},
        [ncq(`${NCB}/mafia/lobby/start`) + ':POST']: {status: 200, body: {lobby: ncLobby()}},
    })});
    await ncTable(app);
    assert.match(app.content.textContent, /Готовы 3 из 4/);
    await findButton(app.content, 'Отметить готовность').click(); await flush();
    await findButton(app.content, 'Начать ночь').click(); await flush();
    assert.deepEqual(ncWrites(app, '/lobby/ready').map(r => JSON.parse(r.options.body)), [{ready: true, expected_revision: 4}]);
    assert.deepEqual(ncWrites(app, '/lobby/start').map(r => JSON.parse(r.options.body)), [{expected_revision: 4}]);
    for (const r of [...ncWrites(app, '/lobby/ready'), ...ncWrites(app, '/lobby/start')]) {
        assert.equal(r.options.headers['X-Guest-CSRF'], '1'); assert.match(r.options.headers['Idempotency-Key'], /^[A-Za-z0-9._:-]{8,64}$/);
    }
    assert.ok(!app.requests.some(r => r.path.includes('/api/mini/mafia')));
});

test('the host removes a player or a waiting guest only after confirming', async () => {
    const lobby = ncLobby({waiting: [{name: 'Олег', ref: 'w1', is_me: false}]});
    const app = await application(true, '', {savedGuest: true, manualTimers: true, overrides: ncOverrides(lobby, {
        [ncq(`${NCB}/mafia/lobby/remove`) + ':POST']: {status: 200, body: {lobby}},
    })});
    await ncTable(app);
    assert.match(app.content.textContent, /Олег.*ждёт следующую партию/);
    const removeButtons = () => app.content.querySelectorAll('button').filter(b => b.textContent === 'Убрать');
    assert.equal(removeButtons().length, 4, 'three seated players and one waiting guest, never the host');
    await removeButtons()[0].click(); await flush();
    assert.match(app.content.textContent, /Убрать Марина из-за стола\?/);
    await findButton(app.content, 'Оставить').click(); await flush();
    assert.equal(ncWrites(app, '/lobby/remove').length, 0);
    await removeButtons().at(-1).click(); await flush();
    const confirm = app.content.querySelectorAll('.nc-alert')[0].querySelectorAll('button').find(b => b.textContent === 'Убрать');
    await confirm.click(); await flush();
    assert.deepEqual(JSON.parse(ncWrites(app, '/lobby/remove')[0].options.body), {target: 'w1', expected_revision: 4});
    const member = await application(true, '', {savedGuest: true, manualTimers: true, overrides: ncOverrides(ncLobby({is_host: false}), {}, ncRoom({role: 'member'}))});
    await ncTable(member);
    assert.equal(member.content.querySelectorAll('button').filter(b => b.textContent === 'Убрать').length, 0);
});

test('a player picks a free portrait; portraits taken by others are disabled', async () => {
    const app = await application(true, '', {savedGuest: true, manualTimers: true, overrides: ncOverrides(ncLobby(), {
        [ncq(`${NCB}/mafia/lobby/portrait`) + ':POST']: {status: 200, body: {lobby: ncLobby()}},
    })});
    await ncTable(app);
    await findButton(app.content, 'Портрет').click(); await flush();
    const portraits = app.content.querySelectorAll('.nc-portrait');
    assert.equal(portraits.length, 12);
    assert.equal(portraits[0].attrs['aria-pressed'], 'true');
    assert.deepEqual(portraits.filter(b => b.disabled).map(b => b.attrs['aria-label']), ['Портрет 2: занят', 'Портрет 3: занят', 'Портрет 4: занят']);
    await portraits[4].click(); await flush();
    assert.deepEqual(JSON.parse(ncWrites(app, '/lobby/portrait')[0].options.body), {expected_revision: 4, portrait: 5});
    await findButton(app.content, 'Готово').click(); await flush();
    assert.ok(findButton(app.content, 'Начать ночь'));
});

test('the owner opens the room to the public list; the switch reports until when it stays listed', async () => {
    const until = '2026-10-29T18:30:00+00:00';
    const app = await application(true, '', {savedGuest: true, manualTimers: true, overrides: ncOverrides(ncLobby(), {
        [ncq(`${NCB}/open`) + ':POST']: {status: 200, body: ncRoom({open: true, open_expires_at: until})},
    })});
    await ncTable(app);
    const toggle = () => app.content.querySelectorAll('button').find(b => b.attrs.role === 'switch');
    assert.equal(toggle().attrs['aria-checked'], 'false');
    await toggle().click(); await flush();
    const post = app.requests.find(r => r.path === ncq(`${NCB}/open`));
    assert.deepEqual(JSON.parse(post.options.body), {open: true});
    assert.equal(toggle().attrs['aria-checked'], 'true');
    assert.match(app.content.textContent, /Без активности уйдёт из списка в \d\d:\d\d/);
});

test('during a game a room member waits for the next one and can leave the queue', async () => {
    for (const waiting of [false, true]) {
        const lobby = ncLobby({status: 'night', round: 1, joined: false, is_host: false, is_waiting: waiting, history: [{type: 'started', round: 1}],
            players: ncPlayers().slice(1), waiting: waiting ? [{name: 'Гость', ref: 'w1', is_me: true}] : []});
        const app = await application(true, '', {savedGuest: true, manualTimers: true, overrides: ncOverrides(lobby, {
            [ncq(`${NCB}/mafia/lobby/${waiting ? 'unseat' : 'wait'}`) + ':POST']: {status: 200, body: {lobby}},
        }, ncRoom({role: 'member'}))});
        await ncTable(app);
        assert.ok(!app.requests.some(r => r.path === ncq(`${NCB}/mafia/role`)), 'a queued player never asks for a role');
        assert.match(app.content.textContent, waiting ? /Ты в очереди/ : /Партия уже идёт/);
        await findButton(app.content, waiting ? 'Не ждать' : 'Ждать следующую').click(); await flush();
        assert.deepEqual(JSON.parse(ncWrites(app, waiting ? '/lobby/unseat' : '/lobby/wait')[0].options.body), {});
    }
});

test('an eliminated player reads the discussion without a composer (can_post)', async () => {
    const lobby = ncLobby({status: 'day', round: 2, history: [{type: 'started', round: 1}, {type: 'night_result', round: 1, eliminated: 'p1', eliminated_name: 'Гость'}],
        players: ncPlayers().map(p => (p.is_me ? {...p, alive: false} : p))});
    const app = await application(true, '', {savedGuest: true, manualTimers: true, overrides: ncOverrides(lobby, {
        [ncq(`${NCB}/mafia/discussion`)]: {status: 200, body: {enabled: true, can_post: false, items: [{id: 1, author: 'Марина', is_me: false, message: 'Кто это был?'}]}},
        [ncq(`${NCB}/mafia/role`)]: {status: 200, body: {phase: 'day', round: 2, role: 'doctor', title: 'Доктор', alive: false, seat: 'p1'}},
    })});
    await ncTable(app);
    assert.match(app.content.textContent, /Смотришь партию/);
    assert.match(app.content.textContent, /Кто это был\?/);
    assert.equal(app.content.querySelector('textarea'), null);
    assert.match(app.content.textContent, /Выбывшие читают обсуждение, но не пишут/);
});

test('leaving: a seat in an unstarted table, or the room itself; during a game the hero drops out of the case', async () => {
    const seated = await application(true, '', {savedGuest: true, manualTimers: true, overrides: ncOverrides(ncLobby({is_host: false}), {
        [ncq(`${NCB}/mafia/lobby/unseat`) + ':POST']: {status: 200, body: {lobby: ncLobby({is_host: false, joined: false})}},
    }, ncRoom({role: 'member'}))});
    await ncTable(seated);
    assert.deepEqual(Array.from(seated.qw.items, item => item.id), ['nc-rules', 'nc-contrast', 'nc-music', 'nc-music-volume', 'nc-unseat', 'nc-leave']);
    seated.qw.items.find(item => item.id === 'nc-unseat').onSelect(); await flush();
    assert.match(seated.content.textContent, /Место освободится/);
    await findButton(seated.content, 'Покинуть стол').click(); await flush();
    assert.deepEqual(JSON.parse(ncWrites(seated, '/lobby/unseat')[0].options.body), {});
    const lobby = ncLobby({status: 'day', round: 1, is_host: false, history: [{type: 'started', round: 1}]});
    const playing = await application(true, '', {savedGuest: true, manualTimers: true, overrides: ncOverrides(lobby, {
        [ncq(`${NCB}/mafia/role`)]: {status: 200, body: {phase: 'day', round: 1, role: 'citizen', title: 'Мирный', alive: true, seat: 'p1'}},
        [ncq(`${NCB}/leave`) + ':POST']: {status: 200, body: {left: true}},
    }, ncRoom({role: 'member'}))});
    await ncTable(playing);
    assert.ok(!playing.qw.items.some(item => item.id === 'nc-unseat'));
    playing.qw.items.find(item => item.id === 'nc-leave').onSelect(); await flush();
    assert.match(playing.content.textContent, /твой герой выбудет из дела/);
    await findButton(playing.content, 'Остаться').click(); await flush();
    assert.doesNotMatch(playing.content.textContent, /выбудет из дела/);
    playing.qw.items.find(item => item.id === 'nc-leave').onSelect(); await flush();
    await findButton(playing.content, 'Покинуть комнату').click(); await flush(); await flush();
    const leave = playing.requests.find(r => r.path === ncq(`${NCB}/leave`));
    assert.deepEqual(JSON.parse(leave.options.body), {membership_version: 'v1'});
    assert.match(playing.content.textContent, /Твои комнаты/);
    const owner = await application(true, '', {savedGuest: true, manualTimers: true, overrides: ncOverrides(ncLobby())});
    await ncTable(owner);
    assert.ok(!owner.qw.items.some(item => ['nc-leave', 'nc-unseat'].includes(item.id)), 'the owner never leaves own room');
});

test('the portrait choice follows the server count, up to the 17 portraits of the kit', async () => {
    const app = await application(true, '', {savedGuest: true, manualTimers: true, overrides: ncOverrides(ncLobby({portrait_count: 17}))});
    await ncTable(app);
    await findButton(app.content, 'Портрет').click(); await flush();
    assert.equal(app.content.querySelectorAll('.nc-portrait').length, 17);
    assert.equal(ncModule().kit.PORTRAITS, 17);
});

test('the host invites with a short code and a link; members see no invitation', async () => {
    const invite = {id: 'inv-1', invite_code: 'B'.repeat(43), short_code: 'K7Q4-MD2X', expires_at: '2099-10-09T12:00:00+00:00', max_uses: 10,
        web_url: 'https://qw.example/app#room=' + 'B'.repeat(43), telegram_url: null, startapp_param: 'room_' + 'B'.repeat(43)};
    const owner = await application(true, '', {savedGuest: true, manualTimers: true, overrides: ncOverrides(ncLobby(), {
        [ncq(`${NCB}/invites`) + ':POST']: {status: 200, body: invite}})});
    await ncTable(owner);
    assert.ok(owner.qw.items.some(item => item.id === 'nc-invite'));
    await findButton(owner.content, 'Создать приглашение').click(); await flush();
    const post = owner.requests.find(r => r.path === ncq(`${NCB}/invites`) && r.options.method === 'POST');
    assert.deepEqual(JSON.parse(post.options.body), {expires_in_seconds: 86400, max_uses: 10});
    assert.match(owner.content.textContent, /K7Q4-MD2X/);
    assert.doesNotMatch(owner.content.textContent, /BBBBBBBB/, 'the ticket shows the short code; the long token stays in the link');
    await findButton(owner.content, 'Поделиться ссылкой').click(); await flush();
    assert.match(owner.content.textContent, /app#room=B{43}/, 'without share and clipboard the link is shown to copy by hand');
    const member = await application(true, '', {savedGuest: true, manualTimers: true, overrides: ncOverrides(ncLobby({is_host: false}), {}, ncRoom({role: 'member'}))});
    await ncTable(member);
    assert.doesNotMatch(member.content.textContent, /Пригласить|Создать приглашение/);
    assert.ok(!member.qw.items.some(item => item.id === 'nc-invite'));
    assert.ok(member.qw.items.some(item => item.id === 'nc-leave' && item.danger));
});

test('invitation parsing: link token, short code, room_ and roomid_ start parameters', () => {
    const nc = ncModule();
    const token = 'C'.repeat(43), uuid = '0d5c3a9e-1111-4222-8333-444455556666';
    assert.deepEqual({...nc.parseInvite(`https://qw.example/app?room=${token}`)}, {code: token});
    assert.deepEqual({...nc.parseInvite(`https://qw.example/app#room=${token}`)}, {code: token}, 'the fragment form is the one the server hands out');
    assert.equal(nc.parseInvite('https://qw.example/app#room=не код'), null);
    assert.deepEqual({...nc.parseInvite(`https://t.me/quiz_bot/play?startapp=room_${token}`)}, {code: token});
    assert.deepEqual({...nc.parseInvite(`room_${token}`)}, {code: token});
    assert.deepEqual({...nc.parseInvite(' k7q4-md2x ')}, {short: 'k7q4-md2x'});
    assert.deepEqual({...nc.parseInvite(token)}, {code: token});
    assert.deepEqual({...nc.parseLaunch(`roomid_${uuid}`)}, {roomId: uuid});
    assert.equal(nc.parseInvite('не код!'), null);
    assert.equal(nc.parseLaunch('roomid_not-a-uuid'), null);
});

test('joining by a pasted link sits at the table; a typed short code goes as short_code', async () => {
    const token = 'C'.repeat(43);
    let lobby = ncLobby({joined: false, is_host: false, players: ncPlayers().slice(1)});
    const app = await application(true, '', {savedGuest: true, manualTimers: true, overrides: ncOverrides(lobby, {
        [ncq('/api/guest/rooms') + ':POST']: {status: 500},
        [ncq('/api/guest/rooms/join') + ':POST']: {status: 200, body: {...ncRoom({role: 'member'}), joined: true}},
        [ncq(`${NCB}/mafia/lobby`)]: () => ({status: 200, body: {lobby}}),
        [ncq(`${NCB}/mafia/lobby/join`) + ':POST']: () => { lobby = ncLobby({is_host: false}); return {status: 200, body: {lobby}}; },
    }, ncRoom({role: 'member'}))});
    await ncEntry(app);
    const field = app.content.querySelectorAll('input').find(n => n.attrs['aria-label'] === 'Код или ссылка приглашения');
    field.value = `https://qw.example/app?room=${token}`;
    await findButton(app.content, 'Войти').click(); await flush(); await flush(); await flush();
    const joins = app.requests.filter(r => r.path === ncq('/api/guest/rooms/join'));
    assert.deepEqual(JSON.parse(joins[0].options.body), {invite_code: token});
    assert.deepEqual(JSON.parse(ncWrites(app, '/lobby/join')[0].options.body), {});
    assert.ok(findButton(app.content, 'Отметить готовность'));
    await app.ui.back(); await flush(); await flush();
    const again = app.content.querySelectorAll('input').find(n => n.attrs['aria-label'] === 'Код или ссылка приглашения');
    again.value = 'k7q4-md2x';
    await findButton(app.content, 'Войти').click(); await flush(); await flush();
    assert.deepEqual(JSON.parse(app.requests.filter(r => r.path === ncq('/api/guest/rooms/join')).at(-1).options.body), {short_code: 'k7q4-md2x'});
});

test('a dead invitation link shows the expired screen; a mistyped code stays a note on the entry', async () => {
    const app = await application(true, '', {savedGuest: true, manualTimers: true, overrides: ncOverrides(ncLobby(), {
        [ncq('/api/guest/rooms/join') + ':POST']: options => (JSON.parse(options.body).short_code
            ? {status: 404, body: {detail: 'Код не подходит. Проверь буквы и цифры.', reason: 'unknown', code: 'invite_unknown'}}
            : {status: 410, body: {detail: 'Срок приглашения истёк.', reason: 'expired', room_title: 'Пятничный стол', code: 'invite_expired'}}),
    })});
    await ncEntry(app);
    const field = () => app.content.querySelectorAll('input').find(n => n.attrs['aria-label'] === 'Код или ссылка приглашения');
    field().value = 'ABCD-EFGH';
    await findButton(app.content, 'Войти').click(); await flush(); await flush();
    assert.match(app.content.textContent, /Код не подходит/);
    assert.match(app.content.textContent, /Твои комнаты/);
    field().value = 'room_' + 'E'.repeat(43);
    await findButton(app.content, 'Войти').click(); await flush(); await flush();
    assert.match(app.content.textContent, /Ссылка больше не работает/);
    assert.match(app.content.textContent, /Срок приглашения в «Пятничный стол» истёк/);
    assert.ok(findButton(app.content, 'Собрать компанию'));
});

test('room links: room_ joins after sign-in and is used once, roomid_ opens by id, ?room= leaves the URL; none goes to the farm', async () => {
    const token = 'F'.repeat(43), uuid = '0d5c3a9e-1111-4222-8333-444455556666';
    const joinOverrides = {...ncOverrides(ncLobby({is_host: false}), {}, ncRoom({role: 'member'})),
        [ncq('/api/guest/rooms/join') + ':POST']: {status: 200, body: {...ncRoom({role: 'member'}), joined: true}}};
    const first = await application(true, 'room_' + token, {savedGuest: true, manualTimers: true, farmEnabled: true, overrides: joinOverrides});
    await flush(); await flush();
    assert.deepEqual(JSON.parse(first.requests.find(r => r.path === ncq('/api/guest/rooms/join')).options.body), {invite_code: token});
    assert.equal(first.content.dataset.page, 'night');
    assert.equal(first.storage.get('qw-night.launch-consumed'), token);
    assert.equal(first.assigned.length, 0, 'a room code never opens the farm');
    const reload = await application(true, 'room_' + token, {savedGuest: true, manualTimers: true, overrides: joinOverrides,
        sessionValues: {'qw-night.launch-consumed': token}});
    assert.ok(!reload.requests.some(r => r.path === ncq('/api/guest/rooms/join')), 'Telegram keeps start_param on reload: used once');
    assert.equal(reload.content.dataset.page, 'guest');
    const byId = await application(true, 'roomid_' + uuid, {savedGuest: true, manualTimers: true, overrides: {
        ...ncOverrides(ncLobby()), [ncq(`/api/guest/rooms/${uuid}`)]: {status: 200, body: ncRoom({id: uuid})},
        [ncq(`/api/guest/rooms/${uuid}/mafia/lobby`)]: {status: 200, body: {lobby: ncLobby()}},
        [ncq(`/api/guest/rooms/${uuid}/mafia/discussion`)]: {status: 200, body: {items: [], enabled: true}}}});
    await flush(); await flush();
    assert.ok(byId.requests.some(r => r.path === ncq(`/api/guest/rooms/${uuid}`)));
    assert.ok(!byId.requests.some(r => r.path === ncq('/api/guest/rooms/join')));
    const browser = await application(true, '', {savedGuest: true, manualTimers: true, farmEnabled: true, locationSearch: '?room=' + token, overrides: joinOverrides});
    await flush(); await flush();
    assert.ok(browser.requests.some(r => r.path === ncq('/api/guest/rooms/join')));
    assert.ok(browser.replaced.some(path => path === '/app'), 'the invitation leaves the address bar');
    assert.equal(browser.assigned.length, 0);
    const fragment = await application(true, '', {savedGuest: true, manualTimers: true, farmEnabled: true, locationHash: '#room=' + token, overrides: joinOverrides});
    await flush(); await flush();
    assert.deepEqual(JSON.parse(fragment.requests.find(r => r.path === ncq('/api/guest/rooms/join')).options.body), {invite_code: token});
    assert.ok(fragment.replaced.some(path => path === '/app'), 'the fragment is cleared once it is used');
    assert.equal(fragment.assigned.length, 0, 'a fragment room code never opens the farm');
});

test('night: the role card turns face up, then the target is chosen in two steps', async () => {
    const lobby = ncLobby({status: 'night', round: 1, ends_at: 1090, history: [{type: 'started', round: 1}], can_advance: false});
    const app = await application(true, '', {savedGuest: true, manualTimers: true, overrides: ncOverrides(lobby, {
        [ncq(`${NCB}/mafia/role`)]: {status: 200, body: {phase: 'night', round: 1, role: 'mafia', title: 'Мафия', alive: true, seat: 'p1', acted: false,
            phase_revision: 2, targets: [{name: 'Цель', seat: 'p2'}, {name: 'Вера', seat: 'p4'}], teammates: [{seat: 'p3', name: 'Лёша'}]}},
        [ncq(`${NCB}/mafia/action`) + ':POST']: {status: 200, body: {}},
    })});
    await ncTable(app);
    assert.match(app.content.textContent, /Роль увидишь только ты/);
    await findButton(app.content, 'Открыть свою роль').click(); await flush();
    assert.match(app.content.textContent, /Мафия/);
    assert.match(app.content.textContent, /Напарники: Лёша/);
    assert.equal(app.content.querySelectorAll('.nc-clock-text')[0]?.textContent, '1:30', 'the clock counts from server_now');
    await findButton(app.content, 'Понятно, к ночи').click(); await flush();
    const confirmEmpty = findButton(app.content, 'Выбери цель');
    assert.equal(confirmEmpty.disabled, true);
    await findButton(app.content, 'Цель').click(); await flush();
    assert.equal(findButton(app.content, 'Цель').attrs['aria-pressed'], 'true');
    assert.equal(ncWrites(app, '/action').length, 0, 'picking alone sends nothing');
    await findButton(app.content, 'Выбрать: Цель').click(); await flush();
    assert.deepEqual(JSON.parse(ncWrites(app, '/action')[0].options.body), {target: 'p2', expected_revision: 2});
});

test('vote, host advance and rematch use the shared command routes', async () => {
    const role = phase => ({phase, round: 2, role: 'citizen', title: 'Мирный', alive: true, seat: 'p1', voted: false, phase_revision: 2,
        targets: [{name: 'Цель', seat: 'p2'}]});
    for (const [phase, label, suffix, body] of [
        ['voting', 'Голосовать против: Цель', '/vote', {target: 'p2', expected_revision: 2}],
        ['day', 'Открыть голосование сейчас', '/advance', {expected_revision: 4}],
        ['finished', 'Сыграть ещё', '/restart', {expected_revision: 4}]]) {
        const lobby = ncLobby({status: phase, round: 2, can_advance: true, winner: phase === 'finished' ? 'citizens' : null, history: [{type: 'started', round: 1}],
            players: ncPlayers().map(p => ({...p, role: phase === 'finished' ? 'citizen' : undefined, voted: phase === 'voting' ? false : undefined}))});
        const app = await application(true, '', {savedGuest: true, manualTimers: true, overrides: ncOverrides(lobby, {
            [ncq(`${NCB}/mafia/role`)]: {status: 200, body: role(phase)},
            [ncq(`${NCB}/mafia${suffix}`) + ':POST']: {status: 200, body: {lobby}},
        })});
        await ncTable(app);
        if (phase === 'voting') { await findButton(app.content, 'Цель').click(); await flush(); }
        await findButton(app.content, label).click(); await flush();
        assert.deepEqual(JSON.parse(ncWrites(app, suffix)[0].options.body), body, phase);
        if (phase === 'finished') assert.match(app.content.textContent, /Кто был кем/);
    }
});

test('a lost discussion command is retried with the same key until the server answers; the draft survives', async () => {
    let attempts = 0;
    const lobby = ncLobby({status: 'day', round: 1, history: [{type: 'started', round: 1}, {type: 'night_result', round: 1, eliminated: 'p4', eliminated_name: 'Вера'}]});
    const app = await application(true, '', {savedGuest: true, manualTimers: true, overrides: ncOverrides(lobby, {
        [ncq(`${NCB}/mafia/role`)]: {status: 200, body: {phase: 'day', round: 1, role: 'citizen', title: 'Мирный', alive: true, seat: 'p1'}},
        [ncq(`${NCB}/mafia/discussion`) + ':POST']: () => { if (++attempts === 1) throw new TypeError('network'); return {status: attempts === 2 ? 503 : 200, body: {id: 3, accepted: true}}; },
    })});
    await ncTable(app);
    assert.match(app.content.textContent, /Вера выбывает/);
    const box = app.content.querySelector('textarea');
    box.value = 'Привет, город'; box.events.input();
    await findButton(app.content, 'Отправить').click(); await flush();
    assert.match(app.content.textContent, /Нет связи/);
    assert.equal(app.content.querySelector('textarea').value, 'Привет, город', 'the draft is kept on the redrawn screen');
    for (let i = 0; i < 2; i++) { await app.timers.filter(t => t.delay === 3000).at(-1).callback(); await flush(); }
    const sent = app.requests.filter(r => r.path === ncq(`${NCB}/mafia/discussion`) && r.options.method === 'POST');
    assert.equal(sent.length, 3);
    assert.ok(sent.every(r => r.options.headers['Idempotency-Key'] === sent[0].options.headers['Idempotency-Key'] && r.options.body === sent[0].options.body));
    assert.doesNotMatch(app.content.textContent, /Нет связи/);
    assert.equal(app.content.querySelector('textarea').value, '', 'an accepted message clears the draft');
});

test('a late role answer after leaving the table never reaches the screen', async () => {
    let release, started;
    const waiting = new Promise(resolve => { started = resolve; });
    const app = await application(true, '', {savedGuest: true, manualTimers: true, overrides: ncOverrides(ncLobby({status: 'night', round: 2, history: []}), {
        [ncq(`${NCB}/mafia/role`)]: () => { started(); return new Promise(resolve => { release = resolve; }); },
    })});
    await ncEntry(app);
    const opening = findButton(app.content, 'Открыть').click();
    await waiting;
    await app.ui.back(); await flush();
    release({status: 200, body: {phase: 'night', round: 2, title: 'Секретная роль', role: 'detective', alive: true, seat: 'p1', targets: []}});
    await opening; await flush();
    assert.match(app.content.textContent, /Твои комнаты/);
    assert.doesNotMatch(app.content.textContent, /детектив|Кого проверить/);
});

test('polling redraws without losing the draft and stops after leaving the game', async () => {
    let revision = 4;
    const app = await application(true, '', {savedGuest: true, manualTimers: true, overrides: ncOverrides(null, {
        [ncq(`${NCB}/mafia/lobby`)]: () => ({status: 200, body: {lobby: ncLobby({revision})}}),
    })});
    await ncTable(app);
    const box = app.content.querySelector('textarea');
    box.value = 'Пишу сообщение'; box.events.input();
    revision = 5;
    await app.timers.filter(t => t.delay === 4000).at(-1).callback(); await flush();
    assert.notEqual(app.content.querySelector('textarea'), box, 'the screen was redrawn');
    assert.equal(app.content.querySelector('textarea').value, 'Пишу сообщение');
    const poll = app.timers.filter(t => t.delay === 4000).at(-1);
    await app.ui.back(); await flush();     // room → Night City entry
    await app.ui.back(); await flush();     // entry (game root) → main menu
    assert.equal(app.qw.mode, 'hub');
    const before = app.requests.length;
    await poll.callback(); await flush();
    assert.equal(app.requests.length, before);
});

test('Telegram: the group table is a secondary path; messages stay text and commands carry the Mini App CSRF', async () => {
    const chat = '-880000000044', base = `/api/mini/mafia/chats/${chat}`;
    const app = await application(true, '', {overrides: {
        '/api/mini/chats?limit=50': {status: 200, body: {items: [{chat_id: chat, title: 'Дело', type: 'supergroup', mafia: {status: 'playing', seated: 5, joined: true}}], has_more: false}},
        [ncq('/api/guest/rooms', 'telegram')]: {status: 200, body: {items: []}},
        [ncq('/api/guest/rooms/open', 'telegram')]: {status: 200, body: {items: []}},
        [`${base}/lobby`]: {status: 200, body: {lobby: ncLobby({is_host: false, players: [{name: '<Игрок>', seat: 'p1', portrait: 1, is_me: true, ready: false, alive: true}]})}},
        [`${base}/discussion`]: {status: 200, body: {enabled: true, items: [{id: 1, author: '<Игрок>', is_me: false, message: '<script>не HTML</script>', created_at: null}]}},
        [`${base}/discussion:POST`]: {status: 200, body: {id: 2, accepted: true}},
    }});
    await ncEntry(app);
    assert.match(app.content.textContent, /Играть в Telegram-группе/);
    assert.match(app.content.textContent, /Открытых столов сейчас нет/);
    assert.match(app.content.textContent, /за столом 5 · ты за столом/);
    assert.match(app.content.textContent, /идёт партия/);
    await findButton(app.content, 'Вернуться').click(); await flush(); await flush();
    assert.match(app.content.textContent, /<script>не HTML<\/script>/);
    const box = app.content.querySelector('textarea');
    box.value = 'Голосуем после обсуждения'; box.events.input();
    await findButton(app.content, 'Отправить').click(); await flush(); await flush();
    const post = app.requests.find(r => r.path === `${base}/discussion` && r.options.method === 'POST');
    assert.equal(post.options.headers['X-Mini-CSRF'], '1');
    assert.match(post.options.headers['Idempotency-Key'], /^[A-Za-z0-9._:-]{8,64}$/);
    assert.equal(JSON.parse(post.options.body).message, 'Голосуем после обсуждения');
    assert.ok(!app.requests.some(r => r.path.startsWith(`${base}/`) && r.path.includes('identity=')));
});

test('Night City runs in game mode: no hub chrome, back leads to the main menu, hub mode comes back', async () => {
    const app = await application(true, '', {overrides: {
        [ncq('/api/guest/rooms', 'telegram')]: {status: 200, body: {items: []}},
        [ncq('/api/guest/rooms/open', 'telegram')]: {status: 404, body: {detail: 'нет'}},
    }});
    await ncEntry(app);
    assert.equal(app.qw.mode, 'game');
    assert.equal(app.qw.rootBack, null, 'game root: BackButton and ⚙ lead to the main menu via onHome');
    assert.equal(typeof app.qw.onHome, 'function');
    assert.equal(app.content.querySelector('h1').textContent, 'Ночной город');
    assert.match(app.content.textContent, /Ночной город · Дело 01/);
    assert.equal(app.content.querySelectorAll('button').some(b => /К играм|К комнатам/.test(b.textContent)), false);
    assert.ok(app.qw.items.some(item => item.id === 'nc-rules') && app.qw.items.some(item => item.id === 'nc-contrast'));
    await app.ui.back(); await flush(); await flush();
    assert.equal(app.qw.mode, 'hub', 'the main menu is a hub screen');
    assert.equal(app.content.dataset.page, 'home');
});

test('guest starts in a browser, resumes and logs out without a Telegram session', async () => {
    const fresh = await application(true, '', {guestMode: true});
    assert.ok(findButton(fresh.content, 'Продолжить как гость'));
    await findButton(fresh.content, 'Продолжить как гость').click(); await flush();
    assert.equal(fresh.navigation.hidden, false);
    assert.ok(findButton(fresh.content, 'Открыть атлас'));
    assert.ok(findButton(fresh.content, 'Создать комнату'));
    assert.doesNotMatch(fresh.content.textContent, /Твои чаты|Гонка за знаниями/);
    const resumed = await application(true, '', {savedGuest: true});
    assert.equal(resumed.navigation.hidden, false);
    assert.doesNotMatch(resumed.content.textContent, /Гостевой профиль/);
    await openGuestSettings(resumed);
    assert.match(resumed.content.textContent, /Гостевой профиль/);
    await findButton(resumed.content, 'Выйти и потерять доступ к гостю').click(); await flush();
    assert.ok(findButton(resumed.content, 'Продолжить как гость'));
});

test('guest gets the same four-tab bar: games and profile are separate, no duplicates', async () => {
    const app = await application(true, '', {savedGuest: true});
    assert.equal(app.navigation.hidden, false);
    assert.equal(app.tab('home').attrs['aria-current'], 'page');
    assert.ok(findButton(app.content, 'Создать комнату'));
    assert.doesNotMatch(app.content.textContent, /Вход и устройства|Сохранить имя|Выйти и потерять доступ/);
    await openGuestProfile(app);
    assert.equal(app.content.dataset.page, 'guest-profile');
    assert.equal(app.navigation.hidden, false);
    assert.equal(app.tab('profile').attrs['aria-current'], 'page');
    assert.equal(app.tab('home').attrs['aria-current'], undefined);
    assert.equal(app.qw.rootOptions.onScreen, false);
    // The profile tab is only the player card with a way into «Настройки», like for a Telegram player.
    assert.equal(app.content.querySelector('h1').textContent, 'Гость');
    assert.doesNotMatch(app.content.textContent, /Вход и устройства|Сохранить имя|Выйти и потерять доступ|Как к тебе обращаться/);
    await findButton(app.content, 'Настройки').click(); await flush(); await flush();
    assert.equal(app.content.dataset.page, 'guest-settings');
    assert.equal(app.content.querySelector('h1').textContent, 'Настройки');
    assert.equal(app.tab('profile').attrs['aria-current'], 'page');
    assert.equal(app.qw.rootOptions.onScreen, true);
    assert.ok(findButton(app.content, 'Сохранить имя'));
    assert.ok(findButton(app.content, 'Выйти и потерять доступ к гостю'));
    assert.match(app.content.textContent, /Вход и устройства/);
    assert.doesNotMatch(app.content.textContent, /Создать комнату|Классический квиз/);
    app.ui.back(); await flush();
    assert.equal(app.content.dataset.page, 'guest-profile', 'back from the settings returns to the profile card');
    await app.tab('home').click(); await flush();
    assert.equal(app.content.dataset.page, 'guest');
    assert.equal(app.tab('home').attrs['aria-current'], 'page');
    assert.ok(findButton(app.content, 'Открыть атлас'));
    assert.equal(app.qw.rootBack, null);
});

test('account timezone setting saves any IANA zone with its account fence and guest CSRF', async () => {
    const accountId = '00000000-0000-4000-8000-000000000001';
    const app = await application(true, '', {savedGuest: true, overrides: {
        '/api/account/timezone?identity=guest:POST': options => ({status: 200, body: {account_id: accountId, timezone: 'America/Argentina/Buenos_Aires'}}),
    }});
    await openGuestSettings(app); await flush();
    assert.match(app.content.textContent, /Часовой пояс аккаунта/);
    const selector = app.content.querySelectorAll('select').find(node => node.attrs['aria-label'] === 'Часовой пояс аккаунта');
    assert.ok(selector);
    selector.value = 'America/Argentina/Buenos_Aires';
    await findButton(app.content, 'Сохранить часовой пояс').click(); await flush();
    const saved = app.requests.find(row => row.path === '/api/account/timezone?identity=guest');
    assert.ok(saved);
    assert.equal(saved.options.headers['X-Guest-CSRF'], '1');
    assert.deepEqual(JSON.parse(saved.options.body), {timezone: 'America/Argentina/Buenos_Aires', account_id: accountId});
    assert.equal(app.qw.prefs.timezone, 'America/Argentina/Buenos_Aires');
});

test('guest Chats show a Telegram stub whose button opens the linking flow', async () => {
    const app = await application(true, '', {savedGuest: true, initData: 'signed-link', offline: false, autoLogin: false});
    await app.tab('chats').click(); await flush();
    assert.equal(app.content.dataset.page, 'guest-stub');
    assert.equal(app.tab('chats').attrs['aria-current'], 'page');
    assert.equal(app.qw.rootOptions.onScreen, false);
    assert.match(app.content.textContent, /Чаты и рейтинг чатов появятся, когда ты свяжешь Telegram с профилем/);
    assert.equal(app.navigation.hidden, false);
    await findButton(app.content, 'Связать Telegram').click(); await flush();
    assert.equal(app.content.dataset.page, 'guest-settings');
    assert.equal(app.tab('profile').attrs['aria-current'], 'page');
    assert.ok(findButton(app.content, 'Связать с Telegram'));
    assert.equal(app.requests.filter(r => r.path.startsWith('/api/mini/chats') || r.path.includes('leaderboard')).length, 0);
});

test('guest Rating is the real account rating, not a Telegram stub', async () => {
    const app = await application(true, '', {savedGuest: true, initData: 'signed-link', offline: false, autoLogin: false});
    await app.tab('rating').click(); await flush();
    assert.equal(app.content.dataset.page, 'rating');
    assert.equal(app.tab('rating').attrs['aria-current'], 'page');
    assert.equal(app.qw.rootOptions.onScreen, false);
    assert.equal(app.ratingCalls.length, 1);
    const call = app.ratingCalls[0];
    assert.equal(call.identity, 'guest');
    assert.equal(call.content, app.content);
    assert.equal(call.isCurrent(), true);
    // The "choose a nickname" step leads to the guest profile.
    await call.onProfile(); await flush(); await flush();
    assert.equal(app.content.dataset.page, 'guest-profile');
    assert.equal(app.ratingCalls.length, 1);
});

test('guest already linked to Telegram is offered Telegram sign-in instead of linking', async () => {
    const profile = {account_id: 'account-a', display_name: 'Алиса', login: 'alice', telegram_user_id: 99, authentication: 'guest'};
    const app = await application(true, '', {savedGuest: true, overrides: {
        '/api/guest/me': {status: 200, body: profile}, '/api/guest/resume:POST': {status: 200, body: profile}}});
    await app.tab('chats').click(); await flush();
    assert.match(app.content.textContent, /Профиль связан с Telegram/);
    assert.equal(app.content.querySelectorAll('button').some(b => b.textContent === 'Связать Telegram'), false);
    await findButton(app.content, 'Войти через Telegram').click(); await flush();
    assert.equal(app.content.dataset.page, 'login');
    assert.equal(app.storage.get('mqb-auth-choice'), 'telegram');
});

test('guest creates an account-owned room with retry-stable id and guest CSRF', async () => {
    const app = await application(true, '', {guestMode: true, overrides: {
        '/api/guest/rooms:POST': {status: 200, body: {id: '00000000-0000-4000-8000-000000000001', title: 'Компания', kind: 'standalone'}},
    }});
    await findButton(app.content, 'Продолжить как гость').click(); await flush();
    const title = app.content.querySelectorAll('input').find(input => input.getAttribute('aria-label') === 'Название комнаты');
    assert.ok(title); title.value = 'Компания';
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
    // Account only: the theme is a segmented control, no game or schedule settings here.
    assert.equal(app.content.querySelectorAll('select').length, 1, 'profile settings contain the searchable account timezone');
    assert.match(app.content.textContent, /Как к тебе обращаться/);
    assert.doesNotMatch(app.content.textContent, /Игра и расписание|Темы обычного квиза|Развернуть на весь экран/);
    const group = app.content.querySelectorAll('.qw-btn-group').find(node => node.attrs['aria-label'] === 'Тема оформления');
    findButton(group, 'Светлая').click();
    assert.equal(app.ui.prefs.theme, 'light');
    assert.equal(findButton(group, 'Светлая').attrs['aria-checked'], 'true');
    const haptics = findButton(app.content, 'Тактильный отклик'); haptics.click();
    assert.equal(haptics.attrs['aria-pressed'], 'false');
    assert.equal(app.mounts.length, 1);
    app.ui.back(); await flush(); assert.equal(app.content.querySelector('h1').textContent, 'Игрок', 'settings go back to the profile, not home');
    // Game settings: the chat page, segment «Настройки» (admin form).
    app.tab('chats').click(); await flush();
    await findButton(app.content, 'Открыть игры и расписание').click(); await flush();
    await findButton(app.content, 'Настройки').click(); await flush();
    assert.match(app.content.textContent, /Темы обычного квиза/);
    assert.ok(app.content.querySelectorAll('input').length > 10);
    app.tab('home').click(); await flush(); app.ui.settings(); await flush();
    assert.equal(app.content.querySelector('h1').textContent, 'Настройки');
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

test('enabled Farm card uses its own illustration and the same game-card layout', async () => {
    const app = await application(true, '', {farmEnabled: true});
    const card = app.content.querySelectorAll('.game-mode-card')[4];
    assert.equal(card.dataset.modeStatus, 'development');
    assert.match(card.className, /palette-green.*image-left/);
    assert.equal(card.querySelector('img').src, '/app/farm-card-v2.webp');
    await findButton(card, 'На свою ферму').click();
    assert.equal(app.assigned[0], '/app/farm?identity=telegram');
});

test('Farm invitation launches once and a persistent Telegram start_param does not loop', async () => {
    const invite = '11111111-2222-4333-8444-555555555555';
    const first = await application(true, `farm_${invite}`, {farmEnabled: true});
    assert.equal(first.assigned[0], `/app/farm?identity=telegram&invite=${invite}`);
    assert.equal(first.storage.get('qw-farm.launch-consumed'), invite);
    const again = await application(true, `farm_${invite}`, {
        farmEnabled: true, sessionValues: Object.fromEntries(first.storage),
    });
    assert.equal(again.assigned.length, 0);
});

test('one-use Farm link keeps its token through Telegram login and launches once', async () => {
    const token = 'A'.repeat(43);
    const first = await application(true, `farm_${token}`, {farmEnabled: true});
    assert.equal(first.assigned[0], `/app/farm?identity=telegram&invite=${token}`);
    assert.equal(first.storage.get('qw-farm.launch-consumed'), token);
    const again = await application(true, `farm_${token}`, {
        farmEnabled: true, sessionValues: Object.fromEntries(first.storage),
    });
    assert.equal(again.assigned.length, 0);
});

test('a fresh Farm invite URL can launch even after an earlier invite was consumed', async () => {
    const invite = '11111111-2222-4333-8444-555555555555';
    const app = await application(true, '', {farmEnabled: true, locationSearch: `?invite=${invite}`,
        sessionValues: {'qw-farm.launch-consumed': invite}});
    assert.equal(app.assigned[0], `/app/farm?identity=telegram&invite=${invite}`);
});

test('fresh Farm invite asks which account to use when both cookies are valid', async () => {
    const invite = '11111111-2222-4333-8444-555555555555';
    for (const identity of ['guest', 'telegram']) {
        const app = await application(true, '', {farmEnabled: true, locationSearch: `?invite=${invite}`,
            savedGuest: true, miniCookie: true, autoLogin: false});
        assert.match(app.content.textContent, /С какой фермы войти/);
        assert.equal(app.assigned.length, 0);
        assert.equal(app.requests.filter(r => r.path === '/api/guest/resume').length, 0);
        await findButton(app.content, identity === 'guest' ? 'Гостевой профиль' : 'Telegram ·').click();
        await flush();
        assert.equal(app.assigned[0], `/app/farm?identity=${identity}&invite=${invite}`);
        assert.equal(app.storage.get('mqb-auth-choice'), identity);
    }
});

test('fresh Farm invite uses the only valid cookie, including Telegram without initData', async () => {
    const invite = '11111111-2222-4333-8444-555555555555';
    const telegram = await application(true, '', {farmEnabled: true, locationSearch: `?invite=${invite}`,
        miniCookie: true, autoLogin: false});
    assert.equal(telegram.assigned[0], `/app/farm?identity=telegram&invite=${invite}`);
    const guest = await application(true, '', {farmEnabled: true, locationSearch: `?invite=${invite}`,
        savedGuest: true, autoLogin: false});
    assert.equal(guest.assigned[0], `/app/farm?identity=guest&invite=${invite}`);
});

test('Farm invite with guest cookie and fresh Telegram initData waits for either explicit choice', async () => {
    const invite = '11111111-2222-4333-8444-555555555555';
    const initData = 'auth_date=123&user=%7B%22id%22%3A99%7D&hash=signed-test-data';
    for (const identity of ['guest', 'telegram']) {
        const app = await application(true, `farm_${invite}`, {farmEnabled: true, savedGuest: true,
            autoLogin: false, initData, offline: false, overrides: {
                '/api/mini/session/resume:POST': {status: 200, body: {}},
            }});
        assert.match(app.content.textContent, /С какой фермы войти/);
        assert.equal(app.assigned.length, 0);
        assert.equal(app.requests.filter(r => r.path === '/api/mini/session').length, 0);
        assert.equal(app.storage.get('qw-farm.incoming'), invite);
        await findButton(app.content, identity === 'guest' ? 'Гостевой профиль' : 'Telegram ·').click();
        await flush();
        assert.deepEqual(app.assigned, [`/app/farm?identity=${identity}&invite=${invite}`]);
        assert.equal(app.storage.get('mqb-auth-choice'), identity);
        const logins = app.requests.filter(r => r.path === '/api/mini/session' && r.options.method === 'POST');
        assert.equal(logins.length, 0);
        if (identity === 'telegram') {
            const resumed = app.requests.find(r => r.path === '/api/mini/session/resume');
            assert.deepEqual(JSON.parse(resumed.options.body), {init_data: initData});
            assert.equal(resumed.options.headers['X-Mini-CSRF'], '1');
        }
        assert.equal(app.requests.filter(r => r.path === '/api/guest/resume').length, identity === 'guest' ? 1 : 0);
        assert.equal(app.requests.filter(r => /merge|link|\/api\/dev\/session/.test(r.path)).length, 0);
        const back = await application(true, `farm_${invite}`, {farmEnabled: true, savedGuest: true,
            miniCookie: identity === 'telegram', autoLogin: false, initData, offline: false,
            sessionValues: Object.fromEntries(app.storage)});
        assert.equal(back.assigned.length, 0);
        assert.doesNotMatch(back.content.textContent, /С какой фермы войти/);
    }
});

test('first Telegram WebView shows one start action and an existing account login', async () => {
    const initData = 'signed-first-open';
    const profile = {account_id: 'account-a', display_name: 'Алиса', login: 'alice', authentication: 'guest'};
    const app = await application(true, '', {initData, offline: false, autoLogin: false, overrides: {
        '/api/account/login:POST': {status: 200, body: profile},
    }});
    assert.ok(findButton(app.content, 'Начать играть'));
    assert.ok(findButton(app.content, 'Уже есть профиль? Войти'));
    assert.equal(app.content.querySelectorAll('button').length, 2);
    assert.equal(app.requests.filter(r => r.path === '/api/mini/session').length, 0);
    await findButton(app.content, 'Уже есть профиль? Войти').click();
    assert.ok(findButton(app.content, 'Войти по логину'));
    await findButton(app.content, 'Войти по логину').click();
    const form = app.content.querySelector('form');
    const [login, password] = form.querySelectorAll('input');
    login.value = 'alice'; password.value = 'secret-password';
    await form.events.submit({preventDefault() {}}); await flush();
    assert.equal(app.content.dataset.page, 'guest');
    assert.equal(app.storage.get('mqb-auth-choice'), 'guest');
    assert.deepEqual(JSON.parse(app.requests.find(r => r.path === '/api/account/login').options.body),
        {login: 'alice', password: 'secret-password'});
    assert.equal(app.requests.filter(r => r.path === '/api/mini/session').length, 0);
});

test('known Telegram identity resumes automatically without provisioning', async () => {
    const app = await application(true, '', {initData: 'signed-return', offline: false, autoLogin: false,
        overrides: {'/api/mini/session/resume:POST': {status: 200, body: {}}}});
    assert.equal(app.content.dataset.page, 'home');
    assert.equal(app.requests.filter(r => r.path === '/api/mini/session/resume').length, 1);
    assert.equal(app.requests.filter(r => r.path === '/api/mini/session').length, 0);
});

test('unknown Telegram identity provisions only after Start is pressed', async () => {
    const app = await application(true, '', {initData: 'signed-new', offline: false, autoLogin: false});
    assert.equal(app.content.dataset.page, 'first-start');
    assert.equal(app.requests.filter(r => r.path === '/api/mini/session').length, 0);
    await findButton(app.content, 'Начать играть').click(); await flush();
    assert.equal(app.content.dataset.page, 'home');
    assert.equal(app.requests.filter(r => r.path === '/api/mini/session').length, 1);
});

test('guest probe failure keeps Telegram first start closed and allows retry', async () => {
    let calls = 0;
    const app = await application(true, '', {initData: 'signed-new', offline: false, autoLogin: false,
        overrides: {'/api/guest/me': () => ++calls === 1
            ? {status: 503, body: {detail: 'Сервис недоступен'}} : {status: 401, body: {detail: 'Нет сессии'}}}});
    assert.ok(findButton(app.content, 'Повторить'));
    assert.equal(app.requests.filter(r => r.path === '/api/mini/session').length, 0);
    await findButton(app.content, 'Повторить').click(); await flush();
    assert.equal(app.content.dataset.page, 'first-start');
    assert.equal(app.requests.filter(r => r.path === '/api/mini/session').length, 0);
    assert.equal(app.requests.filter(r => r.path === '/api/guest/resume').length, 0);
});

test('explicit Telegram logout suppresses automatic resume on reload', async () => {
    const first = await application(true, '', {miniCookie: true, initData: 'signed-return', offline: false, autoLogin: false});
    first.ui.settings(); await flush();
    await findButton(first.content, 'Выйти').click(); await flush();
    assert.equal(first.storage.get('mqb-telegram-logged-out'), '1');
    const reopened = await application(true, '', {initData: 'signed-return', offline: false, autoLogin: false,
        sessionValues: Object.fromEntries(first.storage), overrides: {
            '/api/mini/session/resume:POST': {status: 200, body: {}},
        }});
    assert.equal(reopened.content.dataset.page, 'login');
    assert.equal(reopened.requests.filter(r => r.path === '/api/mini/session/resume').length, 0);
    await findButton(reopened.content, 'Продолжить через Telegram').click(); await flush();
    assert.equal(reopened.storage.has('mqb-telegram-logged-out'), false);
    assert.equal(reopened.content.dataset.page, 'home');
});

test('Telegram logout suppresses a remaining guest cookie in ordinary and Farm bootstrap', async () => {
    const first = await application(true, '', {savedGuest: true, miniCookie: true, initData: 'signed-return',
        offline: false, autoLogin: false, sessionValues: {'mqb-auth-choice': 'telegram'}});
    assert.equal(first.content.dataset.page, 'home');
    first.ui.settings(); await flush();
    await findButton(first.content, 'Выйти').click(); await flush();
    const values = Object.fromEntries(first.storage);
    const ordinary = await application(true, '', {savedGuest: true, initData: 'signed-return',
        offline: false, autoLogin: false, sessionValues: values});
    assert.equal(ordinary.content.dataset.page, 'login');
    assert.equal(ordinary.requests.filter(r => r.path === '/api/guest/resume').length, 0);
    const invite = '11111111-2222-4333-8444-555555555555';
    const farm = await application(true, '', {farmEnabled: true, savedGuest: true, initData: 'signed-return',
        offline: false, autoLogin: false, locationSearch: `?invite=${invite}`, sessionValues: values});
    assert.equal(farm.content.dataset.page, 'login');
    assert.equal(farm.assigned.length, 0);
    assert.equal(farm.requests.filter(r => r.path === '/api/guest/resume').length, 0);
});

test('linked account logout suppresses an existing Telegram cookie in ordinary and Farm bootstrap', async () => {
    const profile = {account_id: 'account-a', display_name: 'Алиса', login: 'alice',
        telegram_user_id: 99, authentication: 'guest'};
    const first = await application(true, '', {savedGuest: true, miniCookie: true, initData: 'signed-return', offline: false,
        autoLogin: false, overrides: {'/api/guest/me': {status: 200, body: profile},
            '/api/guest/resume:POST': {status: 200, body: profile}}});
    await openGuestSettings(first);
    await findButton(first.content, 'Выйти').click(); await flush();
    assert.equal(first.storage.get('mqb-telegram-logged-out'), '1');
    const reopened = await application(true, '', {miniCookie: true, initData: 'signed-return', offline: false, autoLogin: false,
        sessionValues: Object.fromEntries(first.storage), overrides: {
            '/api/mini/session/resume:POST': {status: 200, body: {}},
        }});
    assert.equal(reopened.content.dataset.page, 'login');
    assert.equal(reopened.requests.filter(r => r.path === '/api/mini/session/resume').length, 0);
    assert.equal(reopened.requests.filter(r => r.path === '/api/mini/me').length, 0);
    const invite = '11111111-2222-4333-8444-555555555555';
    const farm = await application(true, '', {farmEnabled: true, miniCookie: true, initData: 'signed-return',
        offline: false, autoLogin: false, locationSearch: `?invite=${invite}`,
        sessionValues: Object.fromEntries(first.storage)});
    assert.equal(farm.content.dataset.page, 'login');
    assert.equal(farm.assigned.length, 0);
    assert.equal(farm.requests.filter(r => r.path === '/api/mini/me').length, 0);
});

test('Farm invitation skips profile chooser when both cookies point to one account', async () => {
    const invite = '11111111-2222-4333-8444-555555555555';
    const app = await application(true, '', {farmEnabled: true, savedGuest: true, miniCookie: true,
        autoLogin: false, locationSearch: `?invite=${invite}`, overrides: {
            '/api/mini/me': {status: 200, body: {account_id: '00000000-0000-4000-8000-000000000001'}},
        }});
    assert.equal(app.assigned[0], `/app/farm?identity=guest&invite=${invite}`);
    assert.doesNotMatch(app.content.textContent, /С какой фермы войти/);
});

test('Telegram link requires preview and checkbox, then keeps the guest account', async () => {
    const profile = {account_id: 'account-a', display_name: 'Алиса', login: 'alice', authentication: 'guest'};
    const preview = {account_id: 'account-a', display_name: 'Алиса', telegram_user_id: 99,
        telegram_display_name: 'Alice TG', already_linked: false};
    const app = await application(true, '', {savedGuest: true, initData: 'signed-link', offline: false,
        autoLogin: false, overrides: {
            '/api/guest/me': {status: 200, body: profile},
            '/api/guest/resume:POST': {status: 200, body: profile},
            '/api/account/telegram-link/preview:POST': {status: 200, body: preview},
            '/api/account/telegram-link/confirm:POST': {status: 200, body: {profile: {...profile, telegram_user_id: 99}}},
        }});
    assert.equal(app.content.dataset.page, 'guest');
    assert.equal(app.requests.filter(r => r.path === '/api/mini/session').length, 0);
    await openGuestSettings(app);
    await findButton(app.content, 'Связать с Telegram').click();
    assert.match(app.content.textContent, /Алиса.*Alice TG.*99/);
    const confirm = findButton(app.content, 'Подтвердить связь');
    const consent = app.content.querySelector('input[type="checkbox"]') ||
        app.content.querySelectorAll('input').find(input => input.type === 'checkbox');
    assert.ok(consent); assert.equal(confirm.disabled, true);
    await confirm.click();
    assert.equal(app.requests.filter(r => r.path === '/api/account/telegram-link/confirm').length, 0);
    consent.checked = true; consent.events.change();
    assert.equal(confirm.disabled, false);
    await confirm.click();
    const writes = app.requests.filter(r => r.path.startsWith('/api/account/telegram-link/'));
    assert.deepEqual(writes.map(r => r.path), ['/api/account/telegram-link/preview', '/api/account/telegram-link/confirm']);
    assert.ok(writes.every(r => r.options.headers['X-Guest-CSRF'] === '1'));
    assert.deepEqual(JSON.parse(writes[1].options.body), {init_data: 'signed-link', confirm: true,
        account_id: 'account-a', telegram_user_id: 99});
    assert.match(app.content.textContent, /Telegram связан.*том же профиле/);
    assert.equal(app.content.dataset.page, 'guest-settings');
    assert.equal(app.requests.filter(r => r.path === '/api/mini/session').length, 0);
});

test('Telegram link conflict leaves current guest account usable without confirmation', async () => {
    const profile = {account_id: 'account-a', display_name: 'Алиса', login: 'alice', authentication: 'guest'};
    const app = await application(true, '', {savedGuest: true, initData: 'signed-link', offline: false,
        autoLogin: false, overrides: {
            '/api/guest/me': {status: 200, body: profile},
            '/api/guest/resume:POST': {status: 200, body: profile},
            '/api/account/telegram-link/preview:POST': {status: 409, body: {detail: 'Telegram уже связан с другим профилем'}},
        }});
    await openGuestSettings(app);
    const link = findButton(app.content, 'Связать с Telegram');
    await link.click();
    assert.match(app.content.textContent, /Telegram уже связан с другим профилем/);
    assert.equal(link.disabled, false);
    assert.equal(app.content.querySelectorAll('button').some(b => b.textContent === 'Подтвердить связь'), false);
    assert.equal(app.content.dataset.page, 'guest-settings');
    assert.equal(app.requests.filter(r => r.path === '/api/account/telegram-link/confirm').length, 0);
});

test('returning to Telegram WebView resumes the chosen guest without silent Telegram provisioning', async () => {
    const profile = {account_id: 'account-a', display_name: 'Алиса', login: 'alice',
        telegram_user_id: 99, authentication: 'guest'};
    const app = await application(true, '', {savedGuest: true, initData: 'signed-return', offline: false,
        autoLogin: false, sessionValues: {'mqb-auth-choice': 'guest'}, overrides: {
            '/api/guest/me': {status: 200, body: profile},
            '/api/guest/resume:POST': {status: 200, body: profile},
        }});
    assert.equal(app.content.dataset.page, 'guest');
    await openGuestSettings(app);
    assert.ok(findButton(app.content, 'Проверить связь с Telegram'));
    assert.equal(app.requests.filter(r => r.path === '/api/mini/session').length, 0);
    assert.equal(app.requests.filter(r => r.path.startsWith('/api/account/telegram-link/')).length, 0);
    assert.equal(app.storage.get('mqb-auth-choice'), 'guest');
});

test('failed Telegram resume preserves Farm invite and retries without provisioning', async () => {
    const invite = '11111111-2222-4333-8444-555555555555';
    let attempts = 0;
    const app = await application(true, '', {farmEnabled: true, savedGuest: true, autoLogin: false,
        locationSearch: `?invite=${invite}`, initData: 'signed-test-init-data', offline: false, overrides: {
            '/api/mini/session/resume:POST': () => ++attempts === 1
                ? {status: 503, body: {detail: 'Сервис недоступен'}} : {status: 200, body: {}},
        }});
    assert.ok(findButton(app.content, 'Повторить'));
    assert.equal(app.assigned.length, 0);
    assert.equal(app.storage.get('qw-farm.incoming'), invite);
    assert.equal(app.storage.has('qw-farm.launch-consumed'), false);
    assert.equal(app.requests.filter(r => r.path === '/api/mini/session').length, 0);
    await findButton(app.content, 'Повторить').click(); await flush();
    assert.match(app.content.textContent, /С какой фермы войти/);
    assert.equal(attempts, 2);
});

test('fresh Farm invite with no cookies offers login, and probe failure offers retry', async () => {
    const invite = '11111111-2222-4333-8444-555555555555';
    const empty = await application(true, '', {farmEnabled: true, locationSearch: `?invite=${invite}`, autoLogin: false});
    assert.ok(findButton(empty.content, 'Войти как dev-игрок'));
    assert.equal(empty.assigned.length, 0);
    let calls = 0;
    const failed = await application(true, '', {farmEnabled: true, locationSearch: `?invite=${invite}`,
        savedGuest: true, miniCookie: true, autoLogin: false, overrides: {
            '/api/guest/me': () => ++calls === 1 ? {status: 503, body: {detail: 'Сервис недоступен'}} : {status: 200, body: {authentication: 'guest'}},
        }});
    assert.ok(findButton(failed.content, 'Повторить'));
    assert.equal(failed.assigned.length, 0);
    await findButton(failed.content, 'Повторить').click(); await flush();
    assert.match(failed.content.textContent, /С какой фермы войти/);
});

test('explicit invite bypasses consumed guard; ordinary return keeps it', async () => {
    const invite = '11111111-2222-4333-8444-555555555555';
    const values = {'qw-farm.launch-consumed': invite};
    const explicit = await application(true, '', {farmEnabled: true, locationSearch: `?invite=${invite}`,
        savedGuest: true, miniCookie: true, autoLogin: false, sessionValues: values});
    assert.match(explicit.content.textContent, /С какой фермы войти/);
    const ordinary = await application(true, `farm_${invite}`, {farmEnabled: true,
        savedGuest: true, miniCookie: true, autoLogin: false, sessionValues: values});
    assert.equal(ordinary.assigned.length, 0);
    assert.doesNotMatch(ordinary.content.textContent, /С какой фермы войти/);
});

test('Farm launch cleans invite query from /app history before Back, while a new explicit link still opens', async () => {
    const invite = '11111111-2222-4333-8444-555555555555';
    for (const query of [`invite=${invite}`, `startapp=farm_${invite}`, `tgWebAppStartParam=farm_${invite}`]) {
        const first = await application(true, '', {farmEnabled: true, locationSearch: `?keep=1&${query}`,
            miniCookie: true, autoLogin: false});
        assert.equal(first.assigned[0], `/app/farm?identity=telegram&invite=${invite}`);
        assert.deepEqual(first.replaced, ['/app?keep=1']);
        const back = await application(true, '', {farmEnabled: true, locationSearch: first.currentLocation.search,
            miniCookie: true, autoLogin: false, sessionValues: Object.fromEntries(first.storage)});
        assert.equal(back.assigned.length, 0);
        const newLink = await application(true, '', {farmEnabled: true, locationSearch: `?invite=${invite}`,
            miniCookie: true, autoLogin: false, sessionValues: Object.fromEntries(back.storage)});
        assert.equal(newLink.assigned[0], `/app/farm?identity=telegram&invite=${invite}`);
    }
});

test('failed Farm assign retains invitation and retries navigation without another login', async () => {
    const invite = '11111111-2222-4333-8444-555555555555';
    for (const identity of ['guest', 'telegram']) {
        const app = await application(true, '', {farmEnabled: true, savedGuest: true, autoLogin: false,
            locationSearch: `?keep=1&invite=${invite}`, initData: 'signed-test-init-data', offline: false,
            assignFailures: 1, sessionValues: {'qw-farm.launch-consumed': invite}, overrides: {
                '/api/mini/session/resume:POST': {status: 200, body: {}},
            }});
        await findButton(app.content, identity === 'guest' ? 'Гостевой профиль' : 'Telegram ·').click(); await flush();
        assert.match(app.content.textContent, /Не удалось открыть ферму/);
        assert.equal(app.assigned.length, 0);
        assert.equal(app.storage.get('qw-farm.incoming'), invite);
        assert.equal(app.storage.has('qw-farm.launch-consumed'), false);
        assert.equal(app.currentLocation.search, `?keep=1&invite=${invite}`);
        const postCount = app.requests.filter(r => r.options.method === 'POST').length;
        await findButton(app.content, 'Повторить').click(); await flush();
        assert.deepEqual(app.assigned, [`/app/farm?identity=${identity}&invite=${invite}`]);
        assert.equal(app.storage.get('qw-farm.launch-consumed'), invite);
        assert.equal(app.currentLocation.search, '?keep=1');
        assert.equal(app.requests.filter(r => r.options.method === 'POST').length, postCount);
    }
});

test('blocked WebView history uses replace navigation after explicit account choice', async () => {
    const invite = '11111111-2222-4333-8444-555555555555';
    const app = await application(true, '', {farmEnabled: true, locationSearch: `?invite=${invite}`,
        savedGuest: true, miniCookie: true, autoLogin: false, historyThrows: true});
    assert.match(app.content.textContent, /С какой фермы войти/);
    assert.equal(app.requests.filter(r => r.path === '/api/guest/resume').length, 0);
    assert.equal(app.replacedNavigation.length, 0);
    await findButton(app.content, 'Гостевой профиль').click(); await flush();
    assert.deepEqual(app.replacedNavigation, [`/app/farm?identity=guest&invite=${invite}`]);
    assert.equal(app.assigned.length, 0);
    assert.equal(app.storage.get('mqb-auth-choice'), 'guest');
});

test('blocked WebView history without replace stays on /app and does not consume invite', async () => {
    const invite = '11111111-2222-4333-8444-555555555555';
    const app = await application(true, '', {farmEnabled: true, locationSearch: `?invite=${invite}`,
        miniCookie: true, autoLogin: false, historyThrows: true, replaceAvailable: false});
    assert.match(app.content.textContent, /Не удалось открыть ферму/);
    assert.equal(app.assigned.length, 0);
    assert.equal(app.replacedNavigation.length, 0);
    assert.equal(app.storage.get('qw-farm.launch-consumed'), undefined);
});

test('quiz and photo stay disabled without a selected chat and never enter the transcript bridge', async () => {
    const app = await application(true, '', {overrides: {
        '/api/mini/chats?limit=50': {status: 200, body: {items: [], has_more: false}},
    }});
    const cards = app.content.querySelectorAll('.game-mode-card');
    assert.equal(cards.length, 5);
    assert.equal(cards[0].querySelector('button').disabled, true);
    assert.equal(cards[1].querySelector('button').disabled, true);
    assert.match(app.content.textContent, /запусти \/start|Запусти \/start/);

    // The DOM double mirrors browser activation: disabled buttons do not dispatch clicks.
    await findButton(cards[0], 'Играть в квиз').click(); await flush();
    await findButton(cards[1], 'Угадывать фото').click(); await flush();
    assert.match(app.content.textContent, /запусти \/start|Запусти \/start/);
    assert.equal(app.mounts.length, 0);
    assert.equal(app.requests.some(item => item.path.startsWith('/api/mini/runtime')), false);
    await findButton(app.content, 'Открыть бота').click();
    assert.deepEqual(app.ui.openedBot, ['morning_quiz_bot', 'home']);

    await app.tab('chats').click(); await flush();
    assert.match(app.content.textContent, /добавь его в группу/);
    assert.equal(app.requests.some(item => item.path.startsWith('/api/mini/runtime')), false);
});

test('home offers resume from the authenticated shared-game projection', async () => {
    const app = await application(true, '', {overrides: {
        '/api/mini/chats/42/games': {status: 200, body: {items: [{kind: 'classic', phase: 'active', question_number: 2, question_count: 5}]}},
    }});
    assert.ok(findButton(app.content, 'Вернуться в текущую игру'));
});

test('home stays usable when the selected chat is gone for the bot', async () => {
    for (const status of [410, 404, 503]) {
        const app = await application(true, '', {overrides: {
            '/api/mini/chats/42/games': {status, body: {detail: 'Чат больше недоступен боту'}},
        }});
        assert.equal(app.content.querySelector('h1').textContent, 'Ну что, сыграем?', `status ${status}`);
        assert.doesNotMatch(app.content.textContent, /Повторить|больше недоступен/);
        assert.equal(app.content.querySelectorAll('.game-mode-card').length, 5);
    }
});

test('native help opens without starting a game or reading bot messages', async () => {
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
    assert.match(app.content.textContent, /Разделы чата|Играть/);
    await findButton(app.content, 'Статистика').click(); await flush();
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
    assert.match(app.content.textContent, /Внешний вид/);
    assert.equal(app.mounts.length, 0);
    app.ui.back(); await flush();
    app.tab('chats').click(); await flush();
    await findButton(app.content, 'Открыть игры и расписание').click(); await flush();
    await findButton(app.content, 'Настройки').click(); await flush();
    assert.match(app.content.textContent, /изменение игровых параметров.*preview отключено/i);
    assert.doesNotMatch(app.content.textContent, /Открыть настройки в боте/);
    assert.equal(app.content.querySelectorAll('select').length, 0);
    assert.ok(!app.content.querySelectorAll('button').some(n => n.textContent === 'Параметры и расписание'));
});

// The ⚙ menu double records the page items play-ui registers; hidden() is evaluated like the core does on render.
function player() {
    const menu = {items: [], title: null, visible: () => Array.from(menu.items, item => item).filter(item => !item.hidden?.()).map(item => item.label)};
    const window = {QW: {menu: {register(items, title) { menu.items = items; if (title != null) menu.title = title; }}}}, document = {createElement: tag => new Element(tag)};
    runInNewContext(source('play-ui.js'), {window, document, setTimeout: () => 1, clearTimeout() {}, setInterval: () => 1, clearInterval() {}, URL, Intl, crypto: require('node:crypto').webcrypto});
    window.QuizPlay.menu = menu;
    return window.QuizPlay;
}

test('group Photo accepts own answer, waits privately, and polls the next question with settled solvers', async () => {
    const ui = player(), host = new Element('main');
    let view = {...guestPhotoGame(), answer_policy: 'group_private_deadline', game: {total: 3}};
    const api = {
        kind: 'chat', setup: async () => guestPhotoSetup, current: async () => view,
        answer: async (kind, params) => {
            assert.equal(params.questionId, 'photo-round');
            view = {...view, question: {...view.question, answered: true, attempts: 1, feedback: 'correct'}};
            return {...view, verdict: 'correct'};
        }, imageUrl: q => q.image_url,
    };
    const options = {host, api, command: '/photo_quiz', media: async () => { throw new Error('skip'); }, selection() {}, onHome() {}, onReplay() {}, onProfile() {}};
    await ui.mount(options);
    const input = host.querySelector('input'); input.value = 'Сова'; input.events.input();
    host.querySelector('form').onsubmit({preventDefault() {}}); await flush(); await flush();
    assert.match(host.textContent, /Ответ принят, ждём завершения раунда/);
    assert.equal(host.querySelectorAll('form').length, 0, 'success does not offer repeat answers');
    assert.doesNotMatch(host.textContent, /Верно ответили|Твои очки|Следующая картинка уже здесь/);
    view = {...view, question: {...view.question, round_id: 'next-round', answered: false, feedback: null},
        last_result: {answer: 'Сова', correct: true, points: 16, own_points: 7, own_correct: true, solvers: [{account_id: 'a', name: 'Аня', points: 7}, {account_id: 'b', name: 'Борис', points: 9}]}};
    await ui.mount(options);
    assert.match(host.textContent, /Верно ответили: Аня · 7, Борис · 9/);
    assert.match(host.textContent, /Твои очки: 7/);
    assert.doesNotMatch(host.textContent, /Твои очки: 16/);
    assert.ok(host.querySelector('form'), 'new question accepts a new private answer');
    ui.stop();
});

test('group Photo final screen uses the viewer totals and never aggregate wins as personal success', async () => {
    const ui = player(), host = new Element('main');
    let view = {...guestPhotoGame(), answer_policy: 'group_private_deadline', game: {total: 1}, own_score: '0', own_correct: 0};
    const api = {kind: 'chat', setup: async () => guestPhotoSetup, current: async () => view,
        imageUrl: q => q.image_url, answer: async () => {
            view = {...view, status: 'finished', question: null, score: '17', correct: 2, own_score: '8', own_correct: 1,
                last_result: {answer: 'Сова', points: 17, own_points: 8, own_correct: true, solvers: [{name: 'Аня', points: 8}, {name: 'Борис', points: 9}]}};
            return view;
        }};
    await ui.mount({host, api, command: '/photo_quiz', media: async () => { throw new Error('skip'); },
        selection() {}, onHome() {}, onReplay() {}, onProfile() {}});
    const input = host.querySelector('input'); input.value = 'Сова'; input.events.input();
    host.querySelector('form').onsubmit({preventDefault() {}}); await flush(); await flush();
    assert.match(host.textContent, /1 правильных из 1/);
    assert.doesNotMatch(host.textContent, /2 правильных из 1|Твои очки: 17/);
    assert.match(host.querySelector('.result-score').textContent, /^8баллов за серию$/);
    assert.match(host.textContent, /Твои очки: 8/);
    ui.stop();
});

test('Telegram room Photo image and retry explicitly select the Telegram identity with dual cookies', async () => {
    const app = await application(true, '', {manualTimers: true, overrides: {
        '/api/guest/rooms?identity=telegram': {status: 200, body: {items: [{...guestRoom, role: 'member'}]}},
        [guestPhotoBase + '/setup?identity=telegram']: {status: 200, body: guestPhotoSetup},
        [guestPhotoBase + '/current?identity=telegram']: {status: 200, body: {current: {...guestPhotoGame(), answer_policy: 'group_private_deadline'}, occupied: false}},
    }});
    assert.ok(!app.content.querySelectorAll('button').some(b => /друзьями/.test(b.textContent)), 'friends rooms are not a loose button on the home list');
    const photoCard = app.content.querySelectorAll('article').find(n => n.dataset.gameMode === 'photo');
    await findButton(photoCard, 'Угадывать фото').click(); await flush();
    assert.equal(app.mounts.at(-1).command, '/photo_quiz');
    await app.mounts.at(-1).onFriends(); await flush();
    assert.equal(app.navigation.hidden, false);
    assert.equal(app.tab('home').getAttribute('aria-current'), 'page');
    await findButton(app.content, 'Открыть фото-загадки').click();
    assert.equal(app.navigation.hidden, false);
    assert.equal(app.tab('home').getAttribute('aria-current'), 'page');
    const image = app.content.querySelector('img');
    const original = new URL(image.src, 'https://qw.example');
    assert.equal(original.searchParams.get('identity'), 'telegram');
    assert.equal(original.searchParams.get('game_id'), 'photo-game');
    assert.equal(original.searchParams.get('round_id'), 'photo-round');
    image.events.error(); await findButton(app.content, 'Повторить загрузку фото').click();
    const retry = new URL(image.src, 'https://qw.example');
    assert.equal(retry.searchParams.get('identity'), 'telegram');
    assert.equal(retry.searchParams.get('retry'), '1');
    assert.equal(retry.searchParams.get('game_id'), 'photo-game');
    assert.equal(retry.searchParams.get('round_id'), 'photo-round');
    await app.ui.back();
});

test('group Photo stale deep link requires explicit transition before answering the current round', async () => {
    const ui = player(), host = new Element('main');
    const view = {...guestPhotoGame(), answer_policy: 'group_private_deadline', game: {total: 3}};
    await ui.mount({host, api: {kind: 'chat', setup: async () => guestPhotoSetup, current: async () => view, imageUrl: q => q.image_url},
        command: '/photo_quiz', photoTarget: {roundId: 'old-round'}, media: async () => { throw new Error('skip'); },
        selection() {}, onHome() {}, onReplay() {}, onProfile() {}});
    assert.match(host.textContent, /Раунд из ссылки уже завершён/);
    assert.equal(host.querySelectorAll('form').length, 0);
    await findButton(host, 'Открыть текущий раунд').click();
    assert.ok(host.querySelector('form'));
    ui.stop();
});

test('group Photo participant room view shows own waiting and reveals solvers only after settlement', async () => {
    let current = {...guestPhotoGame(), answer_policy: 'group_private_deadline', question: {...guestPhotoGame().question, answered: true, attempts: 2}};
    const app = await application(true, '', {savedGuest: true, manualTimers: true, overrides: guestPhotoOverrides({
        '/api/guest/rooms': {status: 200, body: {items: [{...guestRoom, role: 'member'}]}},
        [guestPhotoBase + '/current']: () => ({status: 200, body: {current, occupied: false}}),
    })});
    await findButton(app.content, 'Открыть фото-загадки').click();
    assert.equal(app.navigation.hidden, false);
    assert.equal(app.tab('home').getAttribute('aria-current'), 'page');
    assert.match(app.content.textContent, /Ответ принят, ждём завершения раунда/);
    assert.equal(findButton(app.content, 'Ответить').disabled, true);
    assert.ok(!app.content.querySelectorAll('button').some(b => /Начать|Остановить/.test(b.textContent)));
    assert.doesNotMatch(app.content.textContent, /Верно ответили/);
    current = {...current, score: '17', correct: 2, own_score: '8', own_correct: 1,
        last_result: {answer: 'Сова', correct: true, points: 17, own_points: 8, own_correct: true, solvers: [{name: 'Аня', points: 8}, {name: 'Борис', points: 9}]},
        question: {...current.question, round_id: 'round-2', answered: false}};
    await app.timers.find(t => t.delay === 3000).callback();
    assert.match(app.content.textContent, /Верно ответили: Аня · 8, Борис · 9/);
    assert.match(app.content.textContent, /Верно: 1\. Очки этой серии: 8/);
    assert.match(app.content.textContent, /8 твоих очков/);
    assert.doesNotMatch(app.content.textContent, /17 твоих очков|Верно: 2\. Очки этой серии/);
    assert.equal(findButton(app.content, 'Ответить').disabled, false);
    await app.ui.back();
});

test('Photo launch preserves a group not in the historical chat list and passes the exact round to play', async () => {
    const roundId = 'a'.repeat(32), app = await application(true, `photo_n100123_${roundId}`);
    assert.equal(app.mounts.length, 1);
    assert.equal(app.mounts[0].chatId, '-100123');
    assert.equal(app.mounts[0].command, '/photo_quiz');
    assert.equal(app.mounts[0].photoTarget.roundId, roundId);
});
test('Classic gameplay reads and answers through shared application API only', async () => {
    const ui = player(), host = new Element('main'), answers = [];
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
        throw new Error('Unexpected path ' + path);
    };
    await ui.mount({host, request, chatId: '-1001', selection() {}, onHome() {}, onReplay() {}, onProfile() {}});
    assert.equal(host.querySelector('h1').textContent, 'Кто ведёт квиз?');
    assert.doesNotMatch(host.textContent, /Telegram|transcript/i);
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
    assert.equal(host.querySelectorAll('button').some(b => b.textContent === 'Настройки квиза'), false, 'the page has no inline settings button');
    assert.deepEqual(ui.menu.visible(), ['Настройки квиза']);
    assert.equal(ui.menu.title, 'Классический квиз');
    findButton(host, 'Начать игру').click(); await flush(); await flush();
    assert.equal(calls.includes('/api/mini/runtime'), false);
    assert.equal(calls.includes('/api/mini/classic/chats/42/start'), true);
    assert.equal(host.querySelector('h1').textContent, 'Первый вопрос?');
    ui.stop();
});

test('quiz round exit lives in the ⚙ menu: danger item, in-page confirmation, cleared on leaving', async () => {
    const ui = player(), host = new Element('main'), calls = [];
    let shared = null;
    const request = async (path, options = {}) => {
        calls.push(path);
        if (path === '/api/mini/chats/42/details') return {classic: {questions: 7, seconds: 45, interval: 12, category_mode: 'all', categories: []}};
        if (path === '/api/mini/classic/chats/42/sync') { if (!shared) throw Object.assign(new Error('Нет активного раунда'), {status: 404}); return shared; }
        if (path === '/api/mini/classic/chats/42/start') {
            shared = {status: 'active', revision: 1, game: {current: 1, total: 7}, question: {poll_id: 'p1', question: 'Первый вопрос?', options: ['Да', 'Нет'],
                ends_at: new Date(Date.now() + 60000).toISOString(), answered: false, closed: false}};
            return shared;
        }
        if (path === '/api/mini/classic/chats/42/stop') { shared = {...shared, status: 'stopped', question: null, revision: 2}; return shared; }
        throw new Error('Unexpected path ' + path);
    };
    await ui.mount({host, request, chatId: '42', command: '/quiz', selection() {}, onHome() {}, onReplay() {}, onProfile() {}, onSettings() {}});
    assert.equal(ui.menu.visible().includes('Завершить раунд'), false, 'nothing to stop before the round starts');
    findButton(host, 'Начать игру').click(); await flush(); await flush();
    assert.equal(host.querySelectorAll('button').some(b => b.textContent === 'К играм'), false, 'no «К играм» button on the page');
    assert.equal(host.textContent.includes('Завершить раунд'), false, 'the stop action is not inline');
    assert.equal(ui.menu.visible().includes('Завершить раунд'), true);
    assert.equal(ui.menu.visible().includes('Настройки квиза'), false, 'quiz settings are only for the setup screen');
    const stop = Array.from(ui.menu.items).find(item => item.label === 'Завершить раунд');
    assert.equal(stop.danger, true);
    stop.onSelect();
    assert.match(host.textContent, /Завершить раунд\?/);
    assert.equal(calls.includes('/api/mini/classic/chats/42/stop'), false, 'asks first');
    findButton(host, 'Отмена').click();
    assert.equal(calls.includes('/api/mini/classic/chats/42/stop'), false);
    stop.onSelect(); findButton(host, 'Да, завершить').click(); await flush(); await flush();
    assert.equal(calls.includes('/api/mini/classic/chats/42/stop'), true);
    ui.stop();
    assert.equal(ui.menu.items.length, 0, 'leaving the page clears the page items');
});

test('hub back targets: parent screen, not always home; guests get a back target too', async () => {
    const app = await application();
    assert.equal(app.qw.rootBack, null, 'home is the root');
    assert.equal(app.qw.mode, 'hub');
    app.tab('profile').click(); await flush();
    findButton(app.content, 'Настройки').click(); await flush();
    assert.equal(app.content.dataset.page, 'settings');
    await app.ui.back(); await flush();
    assert.equal(app.content.dataset.page, 'profile', 'settings → profile');
    await app.ui.back(); await flush();
    assert.equal(app.content.dataset.page, 'home', 'profile → home');
    app.tab('chats').click(); await flush();
    await findButton(app.content, 'Открыть игры и расписание').click(); await flush();
    assert.equal(app.content.dataset.page, 'chat');
    await app.ui.back(); await flush();
    assert.equal(app.content.dataset.page, 'chats', 'chat → chats');
    app.tab('profile').click(); await flush();
    await findButton(app.content, 'История игр и ответов').click(); await flush();
    assert.equal(app.content.dataset.page, 'history');
    await app.ui.back(); await flush();
    assert.equal(app.content.dataset.page, 'profile', 'history → profile');
    app.tab('home').click(); await flush();
    findButton(app.content, 'Играть в квиз').click(); await flush();
    assert.equal(app.content.dataset.page, 'play');
    await app.ui.back(); await flush();
    assert.equal(app.content.dataset.page, 'home', 'play → home');
    assert.equal(app.qw.account.name, 'Игрок', 'the ⚙ menu shows the signed-in account');

    const guest = await application(true, '', {savedGuest: true});
    assert.equal(guest.content.dataset.page, 'guest');
    assert.equal(guest.qw.rootBack, null, 'the guest home is the root');
    assert.equal(guest.qw.account.name, 'Гость');
    assert.equal(guest.qw.account.subtitle, 'Гостевой профиль');
});

test('guest classic screen goes back to the guest home, without a «К комнатам» button', async () => {
    const app = await application(true, '', {savedGuest: true, overrides: {
        '/api/mini/config': {status: 200, body: {room_classic_enabled: true, room_photo_enabled: true, runtime_enabled: true}},
        '/api/guest/rooms': {status: 200, body: {items: [{...guestRoom, role: 'owner'}]}},
        '/api/guest/rooms/room-test/invites': {status: 200, body: {items: []}},
        '/api/guest/rooms/room-test/classic/current': {status: 200, body: {current: null}},
    }});
    await findButton(app.content, 'Открыть классический квиз').click(); await flush(); await flush();
    assert.equal(app.content.querySelectorAll('button').some(b => /К комнатам|К играм/.test(b.textContent)), false);
    assert.equal(typeof app.qw.rootBack, 'function');
    await app.ui.back(); await flush(); await flush();
    assert.equal(app.content.dataset.page, 'guest');
    assert.equal(app.qw.rootBack, null);
});

test('/app#settings opens Profile → Settings after login and consumes the hash', async () => {
    const app = await application(true, '', {locationHash: '#settings'});
    assert.equal(app.content.dataset.page, 'settings');
    assert.equal(app.tab('profile').attrs['aria-current'], 'page');
    assert.ok(app.replaced.some(path => !path.includes('#')), 'the hash is removed from the address');
    const plain = await application();
    assert.equal(plain.content.dataset.page, 'home');
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
    let friends = 0;
    await ui.mount({host, request, chatId: '42', command: '/photo_quiz', selection() {}, onHome() {}, onReplay() {}, onProfile() {}, onSettings() {}, onFriends() { friends += 1; }, media: async () => new Blob()});
    assert.match(host.textContent, /2 картинки.*75 секунд на картинку.*Без подсказок.*Записей в каталоге: 8/);
    const group = host.querySelectorAll('div').find(n => n.children.includes(findButton(host, 'Начать фото-серию')));
    assert.match(group.className, /qw-btn-stack/);
    assert.deepEqual(group.children.map(b => b.textContent), ['Начать фото-серию', 'Играть с друзьями'], 'rooms with friends sit inside the mode, under the main action');
    findButton(host, 'Играть с друзьями').click(); assert.equal(friends, 1);
    findButton(host, 'Начать фото-серию').click(); await flush(); await flush();
    assert.equal(calls.includes('/api/mini/runtime'), false);
    assert.equal(calls.includes('/api/mini/photo/chats/42/start'), true);
    assert.equal(host.querySelector('h1').textContent, 'Что скрывается\nна картинке?');
    ui.stop();
});

test('Photo gameplay loads the next round image through its own protected URL', async () => {
    const ui = player(), host = new Element('main'), loaded = [];
    let photo = {status: 'active', revision: 1, phase: 'active', score: '0', correct: 0, game: {current: 1, total: 2}, question: {
        question_number: 1, question_count: 2, round_id: 'photo-round', ends_at: new Date(Date.now() + 60000).toISOString(), closed: false,
        mask: 'С⬜⬜⬜', image_url: '/api/mini/photo/chats/-1001/current/image?round_id=photo-round', feedback: 'wrong',
    }};
    await ui.mount({host, command: '/photo_quiz', chatId: '-1001', request: async path => {
        if (path.endsWith('/setup')) return {question_count: 2, open_seconds: 60, hints_enabled: true, available_questions: 2, can_start: true};
        if (path.endsWith('/sync')) return photo;
        if (path.endsWith('/answer')) {
            photo = {status: 'active', revision: 2, phase: 'active', score: '5', correct: 1, game: {current: 2, total: 2}, question: {
                question_number: 2, question_count: 2, round_id: 'next-round', ends_at: new Date(Date.now() + 60000).toISOString(), closed: false,
                mask: 'К⬜⬜', image_url: '/api/mini/photo/chats/-1001/current/image?round_id=next-round', feedback: null,
            }};
            return photo;
        }
        throw new Error('Unexpected path ' + path);
    }, media: async path => { loaded.push(path); return new Blob(['shared-image']); }, selection() {}, onHome() {}});
    await flush();
    assert.equal(host.querySelectorAll('.play-photo').length, 1);
    assert.equal(host.querySelectorAll('input').length, 1);
    assert.match(host.textContent, /С⬜⬜⬜|общей игровой сессии/);
    assert.deepEqual(loaded, ['/api/mini/photo/chats/-1001/current/image?round_id=photo-round']);
    host.querySelector('input').value = 'сова';
    host.querySelector('form').onsubmit({preventDefault() {}});
    await flush(); await flush();
    assert.deepEqual(loaded, [
        '/api/mini/photo/chats/-1001/current/image?round_id=photo-round',
        '/api/mini/photo/chats/-1001/current/image?round_id=next-round',
    ]);
    ui.stop();
});

test('photo mask wraps one cell per answer letter and keeps revealed letters and separators in place', async () => {
    const ui = player(), host = new Element('main'), maskText = `С□ □□-Р${'□'.repeat(65)}`;
    await ui.mount({host, command: '/photo_quiz', chatId: '-1001', request: async path => {
        if (path.endsWith('/setup')) return {question_count: 1, open_seconds: 60, hints_enabled: true, available_questions: 1, can_start: true};
        if (path.endsWith('/sync')) return {status: 'active', revision: 1, phase: 'active', score: '0', correct: 0, game: {current: 1, total: 1}, question: {
            question_number: 1, question_count: 1, round_id: 'long-mask-round', ends_at: new Date(Date.now() + 60000).toISOString(), closed: false,
            mask: maskText, image_url: '/api/mini/photo/chats/-1001/current/image?round_id=long-mask-round',
        }};
        throw new Error('Unexpected path ' + path);
    }, media: async () => new Blob(['shared-image']), selection() {}, onHome() {}});
    await flush();
    const mask = host.querySelector('.photo-mask');
    assert.equal(mask.getAttribute('role'), 'group');
    assert.equal(mask.children.length, Array.from(maskText).length, 'one rendered item keeps each source position');
    assert.equal(mask.querySelectorAll('.photo-mask-cell').length, 70, 'every answer letter retains one square');
    const cells = mask.querySelectorAll('.photo-mask-cell');
    assert.equal(cells.filter(cell => cell.className.includes('is-hidden')).length, 68);
    assert.equal(cells.filter(cell => cell.className.includes('is-revealed')).length, 2, 'hint letters are shown in their own cells');
    assert.equal(cells[0].textContent, 'С');
    assert.equal(cells[1].getAttribute('aria-label'), 'Неизвестная буква');
    assert.equal(mask.querySelectorAll('.photo-mask-punctuation').length, 1, 'the hyphen remains in sequence without becoming a letter cell');
    assert.equal(mask.querySelectorAll('.photo-mask-space').length, 1, 'word spacing remains in sequence without becoming a letter cell');
    ui.stop();
});

for (const failure of ['network', 'gateway']) test(`an ambiguous ${failure} answer retries with the same idempotency key`, async () => {
    const ui = player(), host = new Element('main'), sent = [];
    let question = {poll_id: 'poll-1', question: 'Категория: Наука\nВопрос?', options: ['Да', 'Нет'],
        ends_at: new Date(Date.now() + 60000).toISOString(), answered: false, selected_option: null, closed: false};
    let first = true;
    await ui.mount({host, chatId: '42', command: '/quiz', selection() {}, onHome() {}, request: async (path, options = {}) => {
        if (path.endsWith('/details')) return {classic: {questions: 1, seconds: 30, interval: 0, category_mode: 'all', categories: []}};
        if (path.endsWith('/sync')) return {phase: 'active', game: {current: 1, total: 1}, question};
        if (path.endsWith('/answer')) {
            const payload = JSON.parse(options.body); sent.push(payload);
            if (first) { first = false; const error = new Error('Ответ неясен'); if (failure === 'gateway') error.status = 502; throw error; }
            question = {...question, answered: true, selected_option: 0, correct_option: 0, is_correct: true, points: '1'};
            return {question};
        }
        throw new Error('Unexpected path ' + path);
    }});
    host.querySelectorAll('.play-option')[0].click(); await flush();
    findButton(host, 'Проверить отправку').click(); await flush(); await flush();
    assert.equal(sent.length, 2); assert.equal(sent[0].command_id, sent[1].command_id);
    assert.match(host.textContent, /Есть! Именно так/); ui.stop();
});

const ALL_GAME_TITLES = ['Классический квиз', 'Фото-загадки', 'Ночной город', 'Атлас маленьких чудес', 'Весёлый фермер'];
test('guest home shows every HOME_GAME_CARDS game, disabled as "Скоро" when its flag is off', async () => {
    const off = await application(true, '', {savedGuest: true});
    const titles = off.content.querySelectorAll('h2').map(n => n.textContent);
    for (const title of ALL_GAME_TITLES) assert.ok(titles.includes(title), `guest home lacks ${title}`);
    const card = id => off.content.querySelectorAll('article').find(n => n.dataset.gameMode === id);
    assert.ok(findButton(card('classic'), 'Скоро').disabled);
    assert.ok(findButton(card('photo'), 'Скоро').disabled);
    assert.ok(findButton(card('night'), 'Открыть дело'));
    assert.ok(findButton(card('atlas'), 'Открыть атлас'));
    const on = await application(true, '', {savedGuest: true, overrides: {
        '/api/mini/config': {status: 200, body: {offline: false, room_classic_enabled: true, room_photo_enabled: true}}}});
    assert.ok(!findButton(on.content.querySelectorAll('article').find(n => n.dataset.gameMode === 'classic'), 'Играть в квиз').disabled);
    assert.ok(!findButton(on.content.querySelectorAll('article').find(n => n.dataset.gameMode === 'photo'), 'Угадывать фото').disabled);
});

test('guest Classic card creates the personal room once and mounts the full play screen with roomApi', async () => {
    let rooms = [];
    const app = await application(true, '', {savedGuest: true, manualTimers: true, overrides: {
        '/api/mini/config': {status: 200, body: {offline: false, room_classic_enabled: true}},
        '/api/guest/rooms': () => ({status: 200, body: {items: rooms}}),
        '/api/guest/rooms:POST': () => { rooms = [{id: 'room-solo', title: 'Моя игра', role: 'owner'}]; return {status: 201, body: rooms[0]}; },
        '/api/guest/rooms/room-solo/classic/start:POST': {status: 200, body: {}},
    }});
    const card = app.content.querySelectorAll('article').find(n => n.dataset.gameMode === 'classic');
    await findButton(card, 'Играть в квиз').click(); await flush();
    const created = app.requests.filter(r => r.path === '/api/guest/rooms' && r.options.method === 'POST');
    assert.equal(created.length, 1); assert.equal(JSON.parse(created[0].options.body).title, 'Моя игра');
    assert.equal(app.mounts.length, 1);
    const mount = app.mounts[0];
    assert.equal(mount.command, '/quiz'); assert.equal(mount.api.kind, 'room'); assert.equal(mount.api.roomId, 'room-solo');
    assert.equal(mount.api.extra.accountId, '00000000-0000-4000-8000-000000000001');
    assert.equal(mount.chatId, undefined);
    // The room request wrapper goes through guestRequest: CSRF header on writes, caller headers kept.
    await mount.request('/api/guest/rooms/room-solo/classic/start', {method: 'POST', headers: {'Idempotency-Key': 'k-12345678'}, body: '{}'});
    const write = app.requests.find(r => r.path === '/api/guest/rooms/room-solo/classic/start');
    assert.equal(write.options.headers['X-Guest-CSRF'], '1'); assert.equal(write.options.headers['Idempotency-Key'], 'k-12345678');
});

test('guest Photo card reuses the existing personal room and mounts the photo play screen', async () => {
    const app = await application(true, '', {savedGuest: true, manualTimers: true, overrides: guestPhotoOverrides({
        '/api/mini/config': {status: 200, body: {offline: false, room_photo_enabled: true}},
        '/api/guest/rooms': {status: 200, body: {items: [{id: 'room-test', title: 'Моя игра', role: 'owner'}]}},
    })});
    const card = app.content.querySelectorAll('article').find(n => n.dataset.gameMode === 'photo');
    await findButton(card, 'Угадывать фото').click(); await flush();
    assert.ok(!app.requests.some(r => r.path === '/api/guest/rooms' && r.options.method === 'POST'));
    assert.equal(app.mounts.length, 1);
    assert.equal(app.mounts[0].command, '/photo_quiz'); assert.equal(app.mounts[0].api.roomId, 'room-test');
});

// ---- Stage 1: QuizPlay adapters (chatApi / roomApi) ----
const roomClassicView = (extra = {}) => ({game_id: 'g1', revision: 1, status: 'active', game: {current: 1, total: 2},
    question: {round_id: 'r1', question: 'Кто ведёт квиз?', options: ['Луна', 'Сова'], ends_at: new Date(Date.now() + 60000).toISOString(),
        answered: false, selected_option: null, closed: false}, scores: [{account_id: 'acc-1', name: 'Гость', score: '0'}], ...extra});
function recorder(handler) {
    const calls = [];
    const request = async (path, options = {}) => { calls.push({path, options}); return handler(path, options, calls.length); };
    return {calls, request};
}
const noop = {selection() {}, onHome() {}, onReplay() {}, onProfile() {}};
const roomClassicSetup = () => ({questions: 10, seconds: 30, interval: 30, category_mode: 'all', categories: [], random_categories: 3, available_categories: ['Космос', 'Музыка', 'Кино'], limits: {questions: [1, 50], seconds: [5, 600], interval: [0, 600], random_categories: [1, 10]}});

test('roomApi classic: setup defaults, GET current unwraps current, commands use Idempotency-Key and game_id', async () => {
    const rec = recorder(path => path.endsWith('/current') ? {current: roomClassicView()} : path.endsWith('/classic/setup') ? roomClassicSetup() : {ok: true});
    const room = player().roomApi('room 1', rec.request, {accountId: 'acc-1'});
    assert.deepEqual(await room.setup('classic'), roomClassicSetup());
    assert.equal(rec.calls[0].path, '/api/guest/rooms/room%201/classic/setup'); assert.equal(rec.calls[0].options.method, undefined);
    assert.equal((await room.current('classic')).game_id, 'g1');
    assert.equal(rec.calls[1].path, '/api/guest/rooms/room%201/classic/current'); assert.equal(rec.calls[1].options.method, undefined);
    rec.calls.splice(0, 2);
    await room.start('classic', {count: 5, open_seconds: 30, interval_seconds: 0}, 'id-start-1');
    await room.answer('classic', {gameId: 'g1', questionId: 'r1', internal: true, selectedOption: 1}, 'id-answer-1');
    await room.stop('classic', {gameId: 'g1', revision: 3}, 'id-stop-1');
    const [start, answer, stop] = rec.calls.slice(0, 3);
    assert.equal(start.path, '/api/guest/rooms/room%201/classic/start'); assert.equal(start.options.headers['Idempotency-Key'], 'id-start-1');
    assert.deepEqual(JSON.parse(start.options.body), {count: 5, open_seconds: 30, interval_seconds: 0});
    await room.start('classic', {count: 3, open_seconds: 20, interval_seconds: 5, category_mode: 'specific', categories: ['Космос'], random_categories: 3}, 'id-start-2');
    assert.deepEqual(JSON.parse(rec.calls.at(-1).options.body), {count: 3, open_seconds: 20, interval_seconds: 5, category_mode: 'specific', categories: ['Космос'], random_categories: 3});
    assert.deepEqual(JSON.parse(answer.options.body), {game_id: 'g1', round_id: 'r1', selected_option: 1});
    assert.equal(answer.options.headers['Idempotency-Key'], 'id-answer-1');
    assert.deepEqual(JSON.parse(stop.options.body), {game_id: 'g1', expected_revision: 3});
    assert.ok([start, answer, stop].every(c => !('command_id' in JSON.parse(c.options.body))));
});

test('roomApi photo: current handles occupied and 404, bodies carry game_id', async () => {
    let reply = {current: null, occupied: true};
    const rec = recorder(path => { if (path.endsWith('/current') && reply === 404) throw Object.assign(new Error('нет'), {status: 404}); return reply; });
    const room = player().roomApi('r', rec.request);
    assert.equal((await room.current('photo')).occupied, true);
    reply = 404; assert.equal(await room.current('photo'), null);
    reply = {current: {game_id: 'p1'}, occupied: false}; assert.equal((await room.current('photo')).game_id, 'p1');
    reply = {ok: 1};
    await room.start('photo', {question_count: 3, open_seconds: 60, hints_enabled: true}, 'id-photo-start');
    await room.answer('photo', {gameId: 'p1', questionId: 'pr', answer: 'слово'}, 'id-photo-answer');
    const [start, answer] = rec.calls.slice(-2);
    assert.deepEqual(JSON.parse(start.options.body), {question_count: 3, open_seconds: 60, hints_enabled: true, answer_policy: 'personal'});
    assert.deepEqual(JSON.parse(answer.options.body), {game_id: 'p1', round_id: 'pr', answer: 'слово'});
    assert.equal(answer.options.headers['Idempotency-Key'], 'id-photo-answer');
});

test('chatApi keeps the exact Telegram wire format: command_id in body, POST /sync, 404 becomes null', async () => {
    const rec = recorder(path => { if (path.endsWith('/sync') && path.includes('/photo/')) throw Object.assign(new Error('нет'), {status: 404}); return {classic: {questions: 7}}; });
    const chat = player().chatApi('42', rec.request);
    assert.deepEqual(await chat.setup('classic'), {questions: 7});
    assert.equal(rec.calls[0].path, '/api/mini/chats/42/details');
    assert.equal(await chat.current('photo'), null);
    await chat.current('classic');
    assert.deepEqual([rec.calls[2].path, rec.calls[2].options.method], ['/api/mini/classic/chats/42/sync', 'POST']);
    await chat.start('classic', {count: 9}, 'cmd-1');
    await chat.answer('classic', {questionId: 'p', internal: false, selectedOption: 1}, 'cmd-2');
    await chat.answer('classic', {questionId: 'r', internal: true, selectedOption: 0}, 'cmd-3');
    await chat.start('photo', {question_count: 3, open_seconds: 60, hints_enabled: false}, 'cmd-4');
    await chat.answer('photo', {questionId: 'pr', answer: 'x'}, 'cmd-5');
    await chat.stop('photo', {revision: 4}, 'cmd-6');
    const bodies = rec.calls.slice(3).map(c => c.options.body);
    assert.deepEqual(bodies, [
        '{"command_id":"cmd-1"}', '{"selected_option":1,"poll_id":"p","command_id":"cmd-2"}',
        '{"selected_option":0,"round_id":"r","command_id":"cmd-3"}',
        '{"question_count":3,"open_seconds":60,"hints_enabled":false,"command_id":"cmd-4"}',
        '{"round_id":"pr","answer":"x","command_id":"cmd-5"}', '{"expected_revision":4,"command_id":"cmd-6"}']);
    assert.ok(rec.calls.slice(3).every(c => !c.options.headers['Idempotency-Key'] && c.options.headers['Content-Type'] === 'application/json'));
});

test('QuizPlay with a fake roomApi: setup, start, answer; a retried answer reuses the Idempotency-Key', async () => {
    const ui = player(), host = new Element('main'), sent = [];
    let game = null, failNext = true;
    const request = async (path, options = {}) => {
        if (path.endsWith('/classic/current')) return {current: game};
        if (path.endsWith('/classic/setup')) return roomClassicSetup();
        if (path.endsWith('/classic/start')) { sent.push(options); game = roomClassicView(); return game; }
        if (path.endsWith('/classic/answer')) {
            sent.push(options);
            if (failNext) { failNext = false; throw new Error('Сервис временно недоступен'); }   // no status: outcome unknown
            game = roomClassicView({question: {...game.question, answered: true, selected_option: 1, correct_option: 1, is_correct: true, points: '1'},
                scores: [{account_id: 'acc-1', name: 'Гость', score: '1'}]});
            return game;
        }
        throw new Error('Unexpected ' + path);
    };
    await ui.mount({host, request, api: ui.roomApi('room-1', request, {accountId: 'acc-1'}), command: '/quiz', ...noop});
    assert.match(host.textContent, /Вопросов в раунде/); assert.match(host.textContent, /Секунд на ответ/);
    for (const name of ['Космос', 'Музыка', 'Кино']) assert.match(host.textContent, new RegExp(name));
    assert.doesNotMatch(host.textContent, /настроек выбранного чата/);
    assert.equal(host.querySelectorAll('button').some(b => b.textContent === 'Настройки квиза'), false);
    assert.deepEqual(ui.menu.visible(), [], 'room games have no quiz settings item');
    findButton(host, 'Начать игру').click(); await flush(); await flush();
    assert.deepEqual(JSON.parse(sent[0].body), {count: 10, open_seconds: 30, interval_seconds: 30, category_mode: 'all', categories: [], random_categories: 3});
    assert.equal(host.querySelector('h1').textContent, 'Кто ведёт квиз?');
    host.querySelectorAll('.play-option')[1].click(); await flush(); await flush();
    assert.match(host.textContent, /Сервис временно недоступен/);
    findButton(host, 'Проверить отправку').click(); await flush(); await flush(); await flush();
    const answers = sent.filter(o => o.body.includes('selected_option'));
    assert.equal(answers.length, 2);
    assert.equal(answers[0].headers['Idempotency-Key'], answers[1].headers['Idempotency-Key']);
    assert.match(answers[0].headers['Idempotency-Key'], /^[0-9a-f-]{36}$/);
    assert.deepEqual(JSON.parse(answers[1].body), {game_id: 'g1', round_id: 'r1', selected_option: 1});
    assert.match(host.textContent, /Есть! Именно так/);
    assert.match(host.textContent, /Гость: 1/);
    ui.stop();
});

test('QuizPlay roomApi: setup lets the owner pick themes and start sends them', async () => {
    const ui = player(), host = new Element('main'), sent = [];
    const request = async (path, options = {}) => {
        if (path.endsWith('/classic/current')) throw Object.assign(new Error('нет'), {status: 404});
        if (path.endsWith('/classic/setup')) return roomClassicSetup();
        if (path.endsWith('/classic/start')) { sent.push(JSON.parse(options.body)); return roomClassicView(); }
        throw new Error('Unexpected ' + path);
    };
    await ui.mount({host, request, api: ui.roomApi('r', request, {accountId: 'acc-1'}), command: '/quiz', ...noop});
    const mode = host.querySelectorAll('select')[0];
    mode.value = 'specific'; mode.events.change({});
    const boxes = host.querySelectorAll('input').filter(n => n.type === 'checkbox');
    assert.equal(boxes.length, 3);
    boxes[1].checked = true; boxes[1].events.change({});
    findButton(host, 'Начать игру').click(); await flush(); await flush();
    assert.deepEqual(sent[0], {count: 10, open_seconds: 30, interval_seconds: 30, category_mode: 'specific', categories: ['Музыка'], random_categories: 3});
    ui.stop();
});

test('QuizPlay roomApi: a game finished before opening shows setup; one finished while open shows its result, play again returns to setup', async () => {
    const ui = player(), first = new Element('main'), second = new Element('main'), third = new Element('main');
    let game = null;
    const finished = () => roomClassicView({status: 'finished', question: null, scores: [{account_id: 'acc-1', name: 'Гость', score: '4'}]});
    const request = async (path, options = {}) => {
        if (path.endsWith('/classic/setup')) return roomClassicSetup();
        if (path.endsWith('/classic/answer')) { game = finished(); return game; }
        if (path.endsWith('/classic/current')) { if (!game) throw Object.assign(new Error('нет'), {status: 404}); return {current: game}; }
        throw new Error('Unexpected ' + path);
    };
    const api = ui.roomApi('r', request, {accountId: 'acc-1'});
    await ui.mount({host: first, request, api, command: '/quiz', ...noop});
    assert.ok(findButton(first, 'Начать игру'));
    game = finished();
    await ui.mount({host: second, request, api, command: '/quiz', ...noop});
    assert.ok(findButton(second, 'Начать игру')); assert.doesNotMatch(second.textContent, /ПАРТИЯ ЗАВЕРШЕНА/);
    game = roomClassicView();
    await ui.mount({host: third, request, api, command: '/quiz', ...noop});
    third.querySelectorAll('.play-option')[0].click(); await flush(); await flush(); await flush();
    assert.match(third.textContent, /ПАРТИЯ ЗАВЕРШЕНА/); assert.match(third.textContent, /Гость: 4/);
    findButton(third, 'Сыграть ещё').click(); await flush();
    assert.ok(findButton(third, 'Начать игру'));
    ui.stop();
});

test('QuizPlay photo through roomApi: occupied series blocks start; numeric ends_at gives a countdown', async () => {
    const ui = player(), host = new Element('main'), next = new Element('main');
    let reply = {current: null, occupied: true};
    const request = async path => {
        if (path.endsWith('/photo/setup')) return {question_count: 3, open_seconds: 60, hints_enabled: true, available_questions: 5, can_start: true};
        if (path.endsWith('/photo/current')) return reply;
        throw new Error('Unexpected ' + path);
    };
    const api = ui.roomApi('r', request);
    await ui.mount({host, request, api, command: '/photo_quiz', ...noop});
    assert.match(host.textContent, /занята другим игроком/);
    assert.equal(findButton(host, 'Начать фото-серию').getAttribute('disabled'), '');
    reply = {current: {game_id: 'p1', revision: 1, status: 'active', score: '0', correct: 0, game: {current: 1, total: 3},
        question: {round_id: 'pr', question_number: 1, question_count: 3, ends_at: Date.now() / 1000 + 50, closed: false, mask: '□□□',
            image_url: '/api/guest/rooms/r/photo/current/image?game_id=p1&round_id=pr'}}, occupied: false};
    await ui.mount({host: next, request, api, command: '/photo_quiz', media: async () => { throw new Error('skip'); }, ...noop});
    assert.ok(Number.isFinite(Number(next.querySelector('[data-deadline]').dataset.deadline)));
    reply = {current: {game_id: 'p0', revision: 3, status: 'finished', score: '2', correct: 1, game: {current: 3, total: 3}, question: null}, occupied: false};
    const reopened = new Element('main');
    await ui.mount({host: reopened, request, api, command: '/photo_quiz', ...noop});
    assert.ok(findButton(reopened, 'Начать фото-серию')); assert.doesNotMatch(reopened.textContent, /ФОТО-СЕРИЯ ЗАВЕРШЕНА/);
    ui.stop();
});

// ---- Form of address (он / она / не указывать): one Account setting, three touch targets ----
test('QWAddress.g picks the wording per form and falls back to neutral for unknown values', () => {
    const g = addressModule.g;
    assert.equal(g('m', 'собрал', 'собрала', 'собрано'), 'собрал');
    assert.equal(g('f', 'собрал', 'собрала', 'собрано'), 'собрала');
    assert.equal(g('n', 'собрал', 'собрала', 'собрано'), 'собрано');
    for (const unknown of [undefined, null, '', 'x', 'М']) assert.equal(g(unknown, 'собрал', 'собрала', 'собрано'), 'собрано');
});

test('guest first entry offers the form of address once; a choice is saved on the Account and the card disappears', async () => {
    const saved = [];
    const app = await application(true, '', {savedGuest: true, overrides: {
        '/api/account/address-form?identity=guest:POST': options => {
            saved.push(JSON.parse(options.body));
            return {status: 200, body: {account_id: '00000000-0000-4000-8000-000000000001', address_form: 'f', address_form_chosen: true}};
        }}});
    const prompt = app.content.querySelectorAll('section').find(n => n.className.includes('address-card') && /Как к тебе обращаться\?/.test(n.textContent));
    assert.ok(prompt, 'the skippable first-entry step is shown');
    const radios = prompt.querySelectorAll('button');
    assert.deepEqual(radios.map(n => n.textContent), ['Он', 'Она', 'Не указывать']);
    assert.ok(radios.every(n => n.attrs['aria-pressed'] === 'false'));
    await findButton(prompt, 'Она').click(); await flush();
    assert.deepEqual(saved, [{address_form: 'f'}]);
    assert.equal(prompt.hidden, true);
    const request = app.requests.find(r => r.path === '/api/account/address-form?identity=guest');
    assert.equal(request.options.headers['X-Guest-CSRF'], '1');
});

const addressCard = app => app.content.querySelectorAll('section').find(n => n.className.includes('address-card'));
const pressed = node => node.querySelectorAll('button').filter(n => n.attrs['aria-pressed'] === 'true').map(n => n.textContent);

test('an already chosen form skips the first-entry card and shows a collapsed example in guest settings', async () => {
    const examples = {m: 'Ты собрал урожай', f: 'Ты собрала урожай', n: 'Урожай собран'};
    for (const [form, example] of Object.entries(examples)) {
        const chosen = {account_id: '00000000-0000-4000-8000-000000000001', display_name: 'Игрок', authentication: 'guest',
            capabilities: ['guest-profile'], address_form: form, address_form_chosen: true};
        const app = await application(true, '', {savedGuest: true, overrides: {
            '/api/guest/me': {status: 200, body: chosen}, '/api/guest/resume:POST': {status: 200, body: chosen}}});
        assert.doesNotMatch(app.content.textContent, /Как к тебе обращаться\?/, 'the onboarding card is gone');
        await openGuestSettings(app);
        const cards = app.content.querySelectorAll('section').filter(n => n.className.includes('address-card'));
        assert.equal(cards.length, 1);
        assert.match(cards[0].textContent, /Так игры будут к тебе обращаться/);
        assert.match(cards[0].textContent, new RegExp(example));
        assert.deepEqual(cards[0].querySelectorAll('button').map(n => n.textContent), ['Исправить'], 'the choice is collapsed');
        const snip = cards[0].querySelectorAll('span').find(n => n.textContent === '✂️');
        assert.ok(snip && snip.attrs['aria-hidden'] === 'true' && snip.attrs.title === undefined && !snip.events.click, 'the scissors are a quiet, inert detail');
    }
});

test('«Исправить» opens the choice with the current form marked, a pick is saved and the card collapses again', async () => {
    const chosen = {account_id: '00000000-0000-4000-8000-000000000001', display_name: 'Игрок', authentication: 'guest',
        capabilities: ['guest-profile'], address_form: 'm', address_form_chosen: true};
    const sent = [];
    const app = await application(true, '', {savedGuest: true, overrides: {
        '/api/guest/me': {status: 200, body: chosen}, '/api/guest/resume:POST': {status: 200, body: chosen},
        '/api/account/address-form?identity=guest:POST': options => {
            const body = JSON.parse(options.body); sent.push(body);
            return {status: 200, body: {account_id: chosen.account_id, address_form: body.address_form, address_form_chosen: true}};
        }}});
    await openGuestSettings(app);
    const card = addressCard(app);
    await findButton(card, 'Исправить').click();
    const group = card.querySelectorAll('.qw-btn-group')[0];
    assert.ok(group, 'the three options form a .qw-btn-group');
    assert.deepEqual(group.querySelectorAll('button').map(n => n.textContent), ['Он', 'Она', 'Не указывать']);
    assert.deepEqual(pressed(group), ['Он']);
    assert.equal(sent.length, 0);
    await findButton(group, 'Она').click(); await flush();
    assert.deepEqual(sent, [{address_form: 'f'}]);
    assert.equal(card.querySelectorAll('.qw-btn-group').length, 0, 'collapsed again');
    assert.match(card.textContent, /Ты собрала урожай/);
    assert.deepEqual(card.querySelectorAll('button').map(n => n.textContent), ['Исправить']);
});

test('without a made choice the guest settings open the choice at once, with no «Исправить»', async () => {
    const app = await application(true, '', {savedGuest: true});
    await openGuestSettings(app);
    const card = addressCard(app);
    assert.deepEqual(card.querySelectorAll('button').map(n => n.textContent), ['Он', 'Она', 'Не указывать']);
    assert.deepEqual(pressed(card), []);
});

test('Telegram profile asks for the form at home and changes it in settings through the same endpoint', async () => {
    const sent = [];
    const app = await application(true, '', {overrides: {
        '/api/account/address-form?identity=telegram:POST': options => {
            const body = JSON.parse(options.body); sent.push([body, options.headers['X-Mini-CSRF'], options.headers['X-Guest-CSRF']]);
            return {status: 200, body: {account_id: 'telegram-account', address_form: body.address_form, address_form_chosen: true}};
        }}});
    const prompt = app.content.querySelectorAll('section').find(n => /Как к тебе обращаться\?/.test(n.textContent));
    assert.ok(prompt);
    await findButton(prompt, 'Не указывать').click(); await flush();
    app.tab('profile').click(); await flush();
    findButton(app.content, 'Настройки').click(); await flush();
    const section = addressCard(app);
    assert.match(section.textContent, /Урожай собран/);
    await findButton(section, 'Исправить').click();
    assert.deepEqual(pressed(section), ['Не указывать']);
    await findButton(section, 'Она').click(); await flush();
    assert.deepEqual(sent.map(item => item[0]), [{address_form: 'n'}, {address_form: 'f'}]);
    assert.ok(sent.every(item => item[1] === '1' && item[2] === '1'));
    assert.match(section.textContent, /Ты собрала урожай/);
    assert.deepEqual(section.querySelectorAll('button').map(n => n.textContent), ['Исправить']);
});

test('the account lives in «Настройки» for a guest and no screen sends a player only to Telegram', async () => {
    const app = await application(true, '', {savedGuest: true, initData: 'signed', offline: false, autoLogin: false});
    await openGuestSettings(app);
    for (const part of [/Вход и устройства/, /Сохранить профиль/, /Как к тебе обращаться/, /Связать с Telegram/])
        assert.match(app.content.textContent, part);
    assert.ok(findButton(app.content, 'Выйти и потерять доступ к гостю'));
    // An expired session offers the in-browser ways in, with Telegram as one option.
    const expired = await application(true, '', {manualTimers: true,
        overrides: {'/api/mini/session/renew': {status: 401, body: {detail: 'Сессия завершена'}}}});
    await expired.timers.find(timer => timer.delay === 600000).callback(); await flush(); await flush();
    assert.match(expired.content.textContent, /Сессия истекла\. Войди снова/);
    assert.doesNotMatch(expired.content.textContent, /Mini App из Telegram/);
    assert.ok(findButton(expired.content, 'Продолжить как гость'));
    assert.ok(findButton(expired.content, 'Войти по логину'));
    assert.ok(findButton(expired.content, 'Создать аккаунт'));
});

test('player-facing profile text follows the chosen form and stays neutral by default', async () => {
    const cases = [['m', /Ты вошёл как «ira»/], ['f', /Ты вошла как «ira»/], ['n', /Вход выполнен как «ira»/], [undefined, /Вход выполнен как «ira»/]];
    for (const [form, expected] of cases) {
        const profile = {account_id: '00000000-0000-4000-8000-000000000001', display_name: 'Игрок', authentication: 'guest',
            login: 'ira', capabilities: ['guest-profile'], ...(form ? {address_form: form, address_form_chosen: true} : {})};
        const app = await application(true, '', {savedGuest: true, overrides: {
            '/api/guest/me': {status: 200, body: profile}, '/api/guest/resume:POST': {status: 200, body: profile}}});
        await openGuestSettings(app);
        assert.match(app.content.textContent, expected, `form ${form}`);
        assert.doesNotMatch(app.content.textContent, /\(а\)|вошёл\(а\)/);
    }
});

// ---- Сквозной аккаунт: вход через Telegram в браузере, слияние профилей, устройства ----
const LOGIN = '/api/account/telegram-login';
const tgProfile = {account_id: 'account-tg', display_name: 'Алиса', login: null, authentication: 'guest', telegram_user_id: 99};
const mergePreview = {current: {account_id: 'account-a', display_name: 'Браузерный', login: 'bob',
    alchemy: {discovered: 7, points_total: '31'}, farm: {exists: true, level: 3, coins: 120}, rooms_owned: 1, rooms_member: 2, games: 4},
    telegram: {account_id: 'account-t', display_name: 'Телеграмный', login: 'tg_name',
        alchemy: {discovered: 2, points_total: '5'}, farm: {exists: false}, rooms_owned: 0, rooms_member: 0, games: 1},
    rules: ['Открытия и предметы объединяются.'], lost_login: 'tg_name',
    lost_login_if_current_main: 'tg_name', lost_login_if_telegram_main: 'bob'};
const loginApp = (overrides = {}, extra = {}) => application(true, '', {manualTimers: true, offline: false, autoLogin: false,
    sessionValues: {'mqb-telegram-logged-out': '1'}, overrides: {
        [LOGIN + '/start:POST']: {status: 200, body: {request_id: 'r1', link: 'https://t.me/morning_quiz_bot?start=login_abc', expires_at: '2030-01-01T00:00:00+00:00'}},
        ...overrides}, ...extra});
const pollOnce = async app => { await app.timers.find(t => t.delay === 3000).callback(); await flush(); };

test('browser login offers Telegram sign-in only outside Telegram', async () => {
    const outside = await loginApp();
    assert.equal(outside.content.dataset.page, 'login');
    assert.ok(findButton(outside.content, 'Войти через Telegram'));
    const inside = await application(true, '', {initData: 'signed', offline: false, autoLogin: false, sessionValues: {'mqb-telegram-logged-out': '1'}});
    assert.equal(inside.content.dataset.page, 'login');
    assert.equal(inside.content.querySelectorAll('button').some(b => b.textContent === 'Войти через Telegram'), false);
});

test('Telegram browser login: start, poll until approved, complete and land in the guest home', async () => {
    let polls = 0;
    const app = await loginApp({
        [LOGIN + '/status']: () => ({status: 200, body: {status: ++polls < 2 ? 'pending' : 'approved', expires_at: 'x'}}),
        [LOGIN + '/complete:POST']: {status: 200, body: {result: 'logged_in', account_id: 'account-tg', profile: tgProfile}},
    });
    await findButton(app.content, 'Войти через Telegram').click();
    assert.match(app.content.textContent, /Открой Telegram и нажми «Войти»/);
    assert.match(app.content.textContent, /Ждём подтверждения/);
    const link = app.content.querySelector('a');
    assert.equal(link.href, 'https://t.me/morning_quiz_bot?start=login_abc');
    assert.equal(link.target, '_blank'); assert.match(link.rel, /noopener/);
    await pollOnce(app);
    assert.equal(app.content.dataset.page, 'login');
    await pollOnce(app);
    assert.equal(app.content.dataset.page, 'guest');
    assert.equal(app.requests.filter(r => r.path === LOGIN + '/status').length, 2);
    const complete = app.requests.find(r => r.path === LOGIN + '/complete');
    assert.deepEqual(JSON.parse(complete.options.body), {mode: 'auto'});
    assert.equal(complete.options.headers['X-Guest-CSRF'], '1');
    assert.equal(app.requests.find(r => r.path === LOGIN + '/start').options.headers['X-Guest-CSRF'], '1');
    assert.equal(app.storage.get('mqb-auth-choice'), 'guest');
    assert.equal(app.storage.has('mqb-telegram-logged-out'), false);
    assert.match(app.feedback.textContent, /Telegram/);
});

test('Telegram browser login stops polling on cancel and on leaving the page', async () => {
    const app = await loginApp({[LOGIN + '/status']: {status: 200, body: {status: 'pending', expires_at: 'x'}}});
    await findButton(app.content, 'Войти через Telegram').click();
    await pollOnce(app);
    const pending = app.timers.filter(t => t.delay === 3000).at(-1);
    await findButton(app.content, 'Отмена').click();
    assert.equal(app.timers.includes(pending), false);
    await findButton(app.content, 'Войти через Telegram').click();
    await pollOnce(app);
    await findButton(app.content, 'Продолжить как гость').click(); await flush();
    const polls = app.requests.filter(r => r.path === LOGIN + '/status').length;
    for (const timer of app.timers.filter(t => t.delay === 3000)) await timer.callback();
    assert.equal(app.requests.filter(r => r.path === LOGIN + '/status').length, polls);
});

test('Telegram browser login reports an expired request and offers a restart', async () => {
    const app = await loginApp({[LOGIN + '/status']: {status: 200, body: {status: 'expired', expires_at: 'x'}}});
    await findButton(app.content, 'Войти через Telegram').click();
    await pollOnce(app);
    assert.match(app.content.textContent, /Время на подтверждение вышло/);
    findButton(app.content, 'Начать заново');
});

test('merge_required from Telegram login opens the merge screen and posts the chosen main profile', async () => {
    const app = await loginApp({
        [LOGIN + '/status']: {status: 200, body: {status: 'approved', expires_at: 'x'}},
        [LOGIN + '/complete:POST']: {status: 200, body: {result: 'merge_required', account_id: 'account-a', telegram_account_id: 'account-t', preview: mergePreview}},
        [LOGIN + '/merge:POST']: {status: 200, body: {result: 'merged', account_id: 'account-t', lost_login: 'bob', profile: tgProfile}},
    });
    await findButton(app.content, 'Войти через Telegram').click();
    await pollOnce(app);
    assert.equal(app.content.dataset.page, 'merge');
    const text = app.content.textContent;
    for (const part of [/Этот профиль/, /Профиль Telegram/, /Браузерный/, /Телеграмный/, /7 открытий, 31 очко(?!в)/, /уровень 3/, /Фермы пока нет/, /Открытия и предметы объединяются/]) assert.match(text, part);
    // F7: before a choice both cases are explained; the warning then follows the chosen main profile.
    assert.match(text, /если главным станет этот профиль — «tg_name», если профиль Telegram — «bob»/);
    const submit = findButton(app.content, 'Объединить');
    assert.equal(submit.disabled, true);
    await submit.click();
    assert.equal(app.requests.filter(r => r.path === LOGIN + '/merge').length, 0);
    findButton(app.content, 'Главный — этот профиль').click();
    assert.match(app.content.textContent, /Вход по логину «tg_name» перестанет работать/);
    assert.doesNotMatch(app.content.textContent, /Вход по логину «bob» перестанет работать/);
    findButton(app.content, 'Главный — профиль Telegram').click();
    assert.match(app.content.textContent, /Вход по логину «bob» перестанет работать/);
    assert.doesNotMatch(app.content.textContent, /Вход по логину «tg_name» перестанет работать/);
    assert.equal(submit.disabled, false);
    await submit.click(); await flush();
    const merge = app.requests.find(r => r.path === LOGIN + '/merge');
    assert.deepEqual(JSON.parse(merge.options.body), {main: 'telegram', account_id: 'account-a', telegram_account_id: 'account-t'});
    assert.equal(merge.options.headers['X-Guest-CSRF'], '1');
    assert.equal(app.content.dataset.page, 'guest');
    assert.match(app.feedback.textContent, /Профили объединены/);
    assert.match(app.feedback.textContent, /«bob»/);
});

test('merge screen can be cancelled without sending a merge request', async () => {
    const app = await loginApp({
        [LOGIN + '/status']: {status: 200, body: {status: 'approved', expires_at: 'x'}},
        [LOGIN + '/complete:POST']: {status: 200, body: {result: 'merge_required', account_id: 'account-a', telegram_account_id: 'account-t', preview: mergePreview}},
    });
    await findButton(app.content, 'Войти через Telegram').click();
    await pollOnce(app);
    await findButton(app.content, 'Отмена').click();
    assert.equal(app.content.dataset.page, 'login');
    assert.equal(app.requests.filter(r => r.path === LOGIN + '/merge').length, 0);
});

test('Mini App link preview with merge_required opens the merge screen and confirms with initData', async () => {
    const profile = {account_id: 'account-a', display_name: 'Алиса', login: 'alice', authentication: 'guest'};
    const app = await application(true, '', {savedGuest: true, initData: 'signed-link', offline: false, autoLogin: false, overrides: {
        '/api/guest/me': {status: 200, body: profile}, '/api/guest/resume:POST': {status: 200, body: profile},
        '/api/account/telegram-link/preview:POST': {status: 200, body: {merge_required: true, auto: true, account_id: 'account-a',
            telegram_account_id: 'account-t', preview: mergePreview, already_linked: false}},
        '/api/account/telegram-link/merge:POST': {status: 200, body: {result: 'merged', account_id: 'account-a', lost_login: null, profile: {...profile, telegram_user_id: 99}}},
    }});
    await openGuestSettings(app);
    await findButton(app.content, 'Связать с Telegram').click();
    assert.equal(app.content.dataset.page, 'merge');
    assert.equal(app.content.querySelectorAll('button').some(b => b.textContent.startsWith('Главный')), false);
    await findButton(app.content, 'Объединить профили').click(); await flush();
    const merge = app.requests.find(r => r.path === '/api/account/telegram-link/merge');
    assert.deepEqual(JSON.parse(merge.options.body), {init_data: 'signed-link', main: 'current', account_id: 'account-a', telegram_account_id: 'account-t'});
    assert.equal(merge.options.headers['X-Guest-CSRF'], '1');
    assert.equal(app.content.dataset.page, 'guest');
    assert.match(app.feedback.textContent, /Профили объединены/);
});

test('telegram_other_linked offers switching to the Telegram profile through mode=switch', async () => {
    const modes = [];
    const app = await loginApp({
        [LOGIN + '/status']: {status: 200, body: {status: 'approved', expires_at: 'x'}},
        [LOGIN + '/complete:POST']: options => {
            const mode = JSON.parse(options.body).mode; modes.push(mode);
            return mode === 'auto' ? {status: 409, body: {detail: 'К этому профилю уже привязан другой Telegram.', code: 'telegram_other_linked'}}
                : {status: 200, body: {result: 'logged_in', account_id: 'account-tg', profile: tgProfile}};
        },
    });
    await findButton(app.content, 'Войти через Telegram').click();
    await pollOnce(app);
    assert.match(app.content.textContent, /уже привязан другой Telegram/);
    findButton(app.content, 'Отмена');
    await findButton(app.content, 'Войти в профиль этого Telegram').click(); await flush();
    assert.deepEqual(modes, ['auto', 'switch']);
    assert.equal(app.content.dataset.page, 'guest');
});

test('used or expired Telegram login on complete shows the error and restarts', async () => {
    const app = await loginApp({
        [LOGIN + '/status']: {status: 200, body: {status: 'approved', expires_at: 'x'}},
        [LOGIN + '/complete:POST']: {status: 410, body: {detail: 'Запрос входа устарел.', code: 'login_expired'}},
    });
    await findButton(app.content, 'Войти через Telegram').click();
    await pollOnce(app);
    assert.match(app.content.textContent, /Запрос входа устарел/);
    await findButton(app.content, 'Начать заново').click();
    assert.equal(app.requests.filter(r => r.path === LOGIN + '/start').length, 2);
});

test('guest home outside Telegram offers linking through the same flow', async () => {
    const profile = {account_id: 'account-a', display_name: 'Алиса', login: 'alice', authentication: 'guest'};
    const app = await application(true, '', {savedGuest: true, manualTimers: true, offline: false, autoLogin: false, overrides: {
        '/api/guest/me': {status: 200, body: profile}, '/api/guest/resume:POST': {status: 200, body: profile},
        [LOGIN + '/start:POST']: {status: 200, body: {request_id: 'r', link: 'https://t.me/morning_quiz_bot?start=login_z', expires_at: 'x'}},
        [LOGIN + '/status']: {status: 200, body: {status: 'approved', expires_at: 'x'}},
        [LOGIN + '/complete:POST']: {status: 200, body: {result: 'linked', account_id: 'account-a', profile: {...profile, telegram_user_id: 99}}},
    }});
    await openGuestSettings(app);
    await findButton(app.content, 'Связать с Telegram').click();
    await pollOnce(app);
    assert.equal(app.content.dataset.page, 'guest');
    assert.match(app.feedback.textContent, /Telegram связан/);
    assert.equal(app.content.querySelectorAll('button').some(b => b.textContent === 'Связать с Telegram'), false);
});

const deviceSessions = [
    {id: 'aaaaaaaaaaaaaaaa', created_at: '2030-01-02T10:00:00+00:00', expires_at: '2030-02-02T10:00:00+00:00', created_via: 'password', user_agent: 'Chrome на Windows', current: true},
    {id: 'bbbbbbbbbbbbbbbb', created_at: '2030-01-01T10:00:00+00:00', expires_at: '2030-02-01T10:00:00+00:00', created_via: 'telegram', user_agent: 'Safari на iPhone', current: false},
];
const guestDevicesApp = (overrides, profileExtra = {}) => {
    const profile = {account_id: 'account-a', display_name: 'Алиса', login: 'alice', authentication: 'guest', ...profileExtra};
    return application(true, '', {savedGuest: true, offline: false, autoLogin: false, overrides: {
        '/api/guest/me': {status: 200, body: profile}, '/api/guest/resume:POST': {status: 200, body: profile}, ...overrides}})
        .then(async app => { await openGuestSettings(app); return app; });
};
const inputNamed = (root, name) => root.querySelectorAll('input').find(n => n.name === name);

test('devices section lists logins, revokes one device and all other devices', async () => {
    let sessions = deviceSessions;
    const app = await guestDevicesApp({
        '/api/account/sessions?identity=guest': () => ({status: 200, body: {sessions, telegram_sessions: 2, has_password: true, login: 'alice', telegram_linked: true, can_reset_password: true}}),
        '/api/account/sessions/revoke?identity=guest:POST': () => { sessions = [deviceSessions[0]]; return {status: 200, body: {revoked: 1}}; },
        '/api/account/sessions/revoke-others?identity=guest:POST': {status: 200, body: {revoked: 0}},
    });
    const rows = app.content.querySelectorAll('.device-row');
    assert.equal(rows.length, 2);
    assert.match(rows[0].textContent, /Chrome на Windows.*Логин.*это устройство/);
    assert.match(rows[1].textContent, /Safari на iPhone.*Telegram/);
    assert.equal(rows[0].querySelectorAll('button').length, 0);
    assert.match(app.content.textContent, /Активных входов через Telegram: 2/);
    assert.match(app.content.textContent, /пароль\? Если Telegram связан с профилем/);
    assert.doesNotMatch(app.content.textContent, /пока недоступен/);
    await findButton(app.content, 'Выйти на других устройствах').click();
    await rows[1].querySelectorAll('button')[0].click(); await flush();
    const revoke = app.requests.find(r => r.path === '/api/account/sessions/revoke?identity=guest');
    assert.deepEqual(JSON.parse(revoke.options.body), {id: 'bbbbbbbbbbbbbbbb'});
    assert.equal(revoke.options.headers['X-Guest-CSRF'], '1');
    assert.equal(app.requests.filter(r => r.path === '/api/account/sessions/revoke-others?identity=guest').length, 1);
    assert.equal(app.content.querySelectorAll('.device-row').length, 1);
    assert.equal(app.content.querySelectorAll('button').some(b => b.textContent === 'Выйти на других устройствах'), false);
});

test('devices section without a password offers the credentials form and shows server errors', async () => {
    let status = 409;
    const app = await guestDevicesApp({
        '/api/account/sessions?identity=guest': {status: 200, body: {sessions: [deviceSessions[0]], telegram_sessions: 0, has_password: false, login: null, telegram_linked: true, can_reset_password: false}},
        '/api/account/credentials?identity=guest:POST': () => status === 409 ? {status: 409, body: {detail: 'Логин уже занят'}}
            : {status: 200, body: {login: 'newbie'}},
    }, {login: null, telegram_user_id: '42'});
    assert.match(app.content.textContent, /Логин и пароль для входа в браузере/);
    assert.match(app.content.textContent, /Профиль · Telegram/);
    assert.doesNotMatch(app.content.textContent, /Сохранить профиль: задать логин и пароль/);
    const credentials = app.content.querySelectorAll('.account-form').find(f => inputNamed(f, 'username'));
    inputNamed(credentials, 'username').value = 'newbie'; inputNamed(credentials, 'password').value = 'longenough1';
    await credentials.events.submit({preventDefault() {}}); await flush();
    assert.match(credentials.textContent, /Логин уже занят/);
    status = 200;
    await credentials.events.submit({preventDefault() {}}); await flush();
    const posts = app.requests.filter(r => r.path === '/api/account/credentials?identity=guest');
    assert.equal(posts.length, 2);
    assert.deepEqual(JSON.parse(posts[1].options.body), {login: 'newbie', password: 'longenough1'});
    assert.equal(posts[1].options.headers['X-Guest-CSRF'], '1');
    assert.match(app.feedback.textContent, /сохранены/);
});

test('unsaved guest gets one login form: the keep card, not a second one under devices', async () => {
    const app = await guestDevicesApp({
        '/api/account/sessions?identity=guest': {status: 200, body: {sessions: [deviceSessions[0]], telegram_sessions: 0, has_password: false, login: null, telegram_linked: false, can_reset_password: false}},
    }, {login: null});
    assert.match(app.content.textContent, /Гостевой профиль/);
    assert.match(app.content.textContent, /Сохранить профиль: задать логин и пароль/);
    assert.doesNotMatch(app.content.textContent, /Логин и пароль для входа в браузере/);
});

test('password change omits an empty current password and shows current_password errors', async () => {
    let reply = {status: 401, body: {detail: 'Нужен текущий пароль', code: 'current_password_required'}};
    const app = await guestDevicesApp({
        '/api/account/sessions?identity=guest': {status: 200, body: {sessions: [deviceSessions[0]], telegram_sessions: 0, has_password: true, login: 'alice', telegram_linked: true, can_reset_password: true}},
        '/api/account/password?identity=guest:POST': () => reply,
    });
    assert.match(app.content.textContent, /в последние 15 минут, текущий пароль можно не вводить/);
    const change = app.content.querySelectorAll('.account-form').find(f => inputNamed(f, 'new_password'));
    inputNamed(change, 'new_password').value = 'brand-new-pass';
    await change.events.submit({preventDefault() {}}); await flush();
    assert.match(change.textContent, /Нужен текущий пароль/);
    inputNamed(change, 'current_password').value = 'old-pass-123';
    reply = {status: 200, body: {changed: true}};
    await change.events.submit({preventDefault() {}}); await flush();
    const posts = app.requests.filter(r => r.path === '/api/account/password?identity=guest');
    assert.deepEqual(JSON.parse(posts[0].options.body), {new_password: 'brand-new-pass'});
    assert.deepEqual(JSON.parse(posts[1].options.body), {new_password: 'brand-new-pass', current_password: 'old-pass-123'});
    assert.match(app.feedback.textContent, /Пароль изменён/);
    assert.equal(app.content.dataset.page, 'guest-settings');
});

test('Telegram profile page shows the devices section with identity=telegram', async () => {
    const app = await application(true, '', {overrides: {
        '/api/account/sessions?identity=telegram': {status: 200, body: {sessions: [{...deviceSessions[1], current: true}], telegram_sessions: 1, has_password: false, login: null, telegram_linked: true, can_reset_password: false}},
    }});
    await app.tab('profile').click(); await flush();
    assert.doesNotMatch(app.content.textContent, /Вход и устройства/, 'devices moved to Profile → Settings');
    await findButton(app.content, 'Настройки').click(); await flush();
    assert.match(app.content.textContent, /Вход и устройства/);
    assert.match(app.content.textContent, /Активных входов через Telegram: 1/);
    assert.match(app.content.textContent, /Safari на iPhone/);
    assert.ok(app.requests.some(r => r.path === '/api/account/sessions?identity=telegram'));
    const credentials = app.content.querySelectorAll('.account-form').find(f => inputNamed(f, 'username'));
    inputNamed(credentials, 'username').value = 'tguser'; inputNamed(credentials, 'password').value = 'longenough1';
    await credentials.events.submit({preventDefault() {}}); await flush();
    const post = app.requests.find(r => r.path === '/api/account/credentials?identity=telegram');
    assert.deepEqual(JSON.parse(post.options.body), {login: 'tguser', password: 'longenough1'});
    assert.equal(post.options.headers['X-Mini-CSRF'], '1');
});

test('link_required asks before attaching Telegram to the open profile; confirm sends mode=link', async () => {
    const modes = [];
    const app = await loginApp({
        [LOGIN + '/status']: {status: 200, body: {status: 'approved', expires_at: 'x'}},
        [LOGIN + '/complete:POST']: options => {
            const mode = JSON.parse(options.body).mode; modes.push(mode);
            return mode === 'auto'
                ? {status: 200, body: {result: 'link_required', account_id: 'account-a', display_name: 'Браузерный',
                    telegram_user_id: '99', telegram_display_name: 'Алиса TG', profile: tgProfile}}
                : {status: 200, body: {result: 'linked', account_id: 'account-a', profile: tgProfile}};
        },
    });
    await findButton(app.content, 'Войти через Telegram').click();
    await pollOnce(app);
    assert.match(app.content.textContent, /Связать профиль «Браузерный» с Telegram «Алиса TG»\?/);
    assert.equal(app.content.dataset.page, 'login');   // nothing is entered before the player agrees
    assert.deepEqual(modes, ['auto']);
    await findButton(app.content, 'Связать').click(); await flush();
    assert.deepEqual(modes, ['auto', 'link']);
    assert.equal(app.content.dataset.page, 'guest');
    assert.match(app.feedback.textContent, /Telegram связан с профилем/);
});

test('link_required can be cancelled without a second complete request', async () => {
    const app = await loginApp({
        [LOGIN + '/status']: {status: 200, body: {status: 'approved', expires_at: 'x'}},
        [LOGIN + '/complete:POST']: {status: 200, body: {result: 'link_required', account_id: 'account-a', display_name: 'Браузерный',
            telegram_user_id: '99', telegram_display_name: 'Алиса TG', profile: tgProfile}},
    });
    await findButton(app.content, 'Войти через Telegram').click();
    await pollOnce(app);
    await findButton(app.content, 'Отмена').click(); await flush();
    assert.equal(app.requests.filter(r => r.path === LOGIN + '/complete').length, 1);
    findButton(app.content, 'Войти через Telegram');
    assert.equal(app.content.dataset.page, 'login');
});

test('merge_required with auto shows one button and posts main=current', async () => {
    const app = await loginApp({
        [LOGIN + '/status']: {status: 200, body: {status: 'approved', expires_at: 'x'}},
        [LOGIN + '/complete:POST']: {status: 200, body: {result: 'merge_required', auto: true, account_id: 'account-a', telegram_account_id: 'account-t',
            preview: {...mergePreview, lost_login: null, lost_login_if_current_main: null, lost_login_if_telegram_main: null}}},
        [LOGIN + '/merge:POST']: {status: 200, body: {result: 'merged', account_id: 'account-t', lost_login: null, profile: tgProfile}},
    });
    await findButton(app.content, 'Войти через Telegram').click();
    await pollOnce(app);
    assert.equal(app.content.dataset.page, 'merge');
    assert.equal(app.content.querySelectorAll('button').some(b => b.textContent.startsWith('Главный')), false);
    assert.doesNotMatch(app.content.textContent, /перестанет работать/);
    await findButton(app.content, 'Объединить профили').click(); await flush();
    assert.equal(JSON.parse(app.requests.find(r => r.path === LOGIN + '/merge').options.body).main, 'current');
    assert.equal(app.content.dataset.page, 'guest');
});

test('Telegram login polls every 3 s for the first minute and every 5 s afterwards', async () => {
    const app = await loginApp({[LOGIN + '/status']: {status: 200, body: {status: 'pending', expires_at: 'x'}}});
    await findButton(app.content, 'Войти через Telegram').click();
    const delays = [];
    for (let index = 0; index < 22; index++) {
        const timer = app.timers.filter(t => t.delay === 3000 || t.delay === 5000).at(-1);
        delays.push(timer.delay);
        app.timers.splice(app.timers.indexOf(timer), 1);
        await timer.callback(); await flush();
    }
    assert.deepEqual(delays.slice(0, 20), Array(20).fill(3000));
    assert.deepEqual(delays.slice(20), [5000, 5000]);
});

test('an 18+ open table asks one question first; «Назад» enters nothing, «Мне есть 18» joins with age_ok and is remembered; 16+ asks nothing', async () => {
    const table = (id, extra) => ({room_id: id, title: 'Стол ' + id, host_name: 'Гоша', seated: 3, waiting: 0, needs_from: 4, capacity: 12, status: 'gathering', joined: false, ...extra});
    const tables = [table('adult-1', {world: 'dead_air', world_age: 18}), table('teen-1', {world: 'deep_choir', world_age: 16})];
    const joined = id => ({id, title: 'Стол ' + id, role: 'member', membership_version: 'v2', open: true});
    const overrides = {...ncOverrides(ncLobby()), [ncq('/api/guest/rooms/open')]: {status: 200, body: {items: tables}}};
    for (const id of ['adult-1', 'teen-1']) Object.assign(overrides, {
        [ncq(`/api/guest/rooms/${id}/join-open`)]: {status: 200, body: {room: joined(id), joined: true, seat: 'seated', lobby: ncLobby({is_host: false})}},
        [ncq(`/api/guest/rooms/${id}/mafia/lobby`)]: {status: 200, body: {lobby: ncLobby({is_host: false})}},
        [ncq(`/api/guest/rooms/${id}/mafia/discussion`)]: {status: 200, body: {items: [], enabled: true}},
    });
    const app = await application(true, '', {savedGuest: true, manualTimers: true, overrides});
    await ncEntry(app);
    const joins = id => app.requests.filter(r => r.path === ncq(`/api/guest/rooms/${id}/join-open`) && r.options.method === 'POST');
    const sit = async index => { await app.content.querySelectorAll('button').filter(b => b.textContent.startsWith('Сесть за стол'))[index].click(); await flush(); await flush(); };

    await sit(0);
    assert.match(app.content.textContent, /В этом сюжете есть сцены для взрослых\. Тебе есть 18\?/);
    assert.equal(joins('adult-1').length, 0, 'nothing is sent before the answer');
    assert.ok(findButton(app.content, 'Мне есть 18')); assert.ok(findButton(app.content, 'Назад'));
    await findButton(app.content, 'Назад').click(); await flush();
    assert.equal(joins('adult-1').length, 0, '«Назад» enters nothing');
    assert.match(app.content.textContent, /Открытые столы/, 'back to the list');
    assert.equal(app.storage.get('nc-age18-ok'), undefined);

    await sit(0);
    await findButton(app.content, 'Мне есть 18').click(); await flush(); await flush(); await flush();
    assert.deepEqual(JSON.parse(joins('adult-1')[0].options.body), {age_ok: true});
    assert.equal(app.storage.get('nc-age18-ok'), '1', 'remembered on this device');

    // A device that already answered: no question, age_ok goes with the join.
    const again = await application(true, '', {savedGuest: true, manualTimers: true, sessionValues: {'nc-age18-ok': '1'}, overrides});
    await ncEntry(again);
    await again.content.querySelectorAll('button').filter(b => b.textContent.startsWith('Сесть за стол'))[0].click(); await flush(); await flush();
    assert.doesNotMatch(again.content.textContent, /Тебе есть 18\?/, 'not asked again');
    const second = again.requests.filter(r => r.path === ncq('/api/guest/rooms/adult-1/join-open') && r.options.method === 'POST');
    assert.deepEqual(JSON.parse(second[0].options.body), {age_ok: true});
});

test('16+ tables ask nothing and send no age_ok', async () => {
    const tables = [{room_id: 'teen-1', title: 'Хор', host_name: 'Гоша', seated: 3, waiting: 0, needs_from: 4, capacity: 12, status: 'gathering', joined: false, world: 'deep_choir', world_age: 16}];
    const app = await application(true, '', {savedGuest: true, manualTimers: true, overrides: {
        ...ncOverrides(ncLobby()), [ncq('/api/guest/rooms/open')]: {status: 200, body: {items: tables}},
        [ncq('/api/guest/rooms/teen-1/join-open')]: {status: 200, body: {room: {id: 'teen-1', title: 'Хор', role: 'member', membership_version: 'v2'}, joined: true, seat: 'seated', lobby: ncLobby({is_host: false})}},
        [ncq('/api/guest/rooms/teen-1/mafia/lobby')]: {status: 200, body: {lobby: ncLobby({is_host: false})}},
        [ncq('/api/guest/rooms/teen-1/mafia/discussion')]: {status: 200, body: {items: [], enabled: true}},
    }});
    await ncEntry(app);
    await findButton(app.content, 'Сесть за стол').click(); await flush(); await flush();
    const post = app.requests.find(r => r.path === ncq('/api/guest/rooms/teen-1/join-open') && r.options.method === 'POST');
    assert.deepEqual(JSON.parse(post.options.body), {});
    assert.doesNotMatch(app.content.textContent, /Тебе есть 18/);
});
