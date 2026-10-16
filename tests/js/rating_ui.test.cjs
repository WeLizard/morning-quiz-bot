// rating-ui.js: one account rating for guests and Telegram players. DOM double, no browser.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {join} = require('node:path');
const {runInNewContext} = require('node:vm');

class Element {
    constructor(tag) { this.tag = tag; this.children = []; this.attrs = {}; this.events = {}; this.className = ''; this.text = ''; this.dataset = {}; this.hidden = false; this.value = ''; }
    set textContent(value) { this.text = String(value); this.children = []; }
    get textContent() { return this.text + this.children.map(n => n.textContent).join(''); }
    append(...nodes) { this.children.push(...nodes); }
    replaceChildren(...nodes) { this.text = ''; this.children = nodes; }
    setAttribute(key, value) { this.attrs[key] = value; }
    addEventListener(event, callback) { this.events[event] = callback; }
    click() { if (this.disabled) return; return this.events.click?.({currentTarget: this}); }
    all() { return this.children.flatMap(child => [child, ...child.all()]); }
}
const flush = () => new Promise(resolve => setImmediate(resolve));
const el = (tag, text, cls) => { const node = new Element(tag); if (text !== undefined) node.textContent = text; if (cls) node.className = cls; return node; };
const button = (label, action, cls = '') => { const node = el('button', label, cls); node.events.click = action; return node; };
const note = (parent, text, cls = 'muted') => parent.append(el('p', text, cls));
const segmented = (options, current, onPick, label) => {
    const group = el('div', undefined, 'qw-btn-group'); group.setAttribute('aria-label', label);
    group.append(...options.map(([value, text]) => { const node = el('button', text); node.dataset.value = value; node.events.click = () => onPick(value); return node; }));
    return group;
};
const format = value => String(Number(value));
const code = readFileSync(join(__dirname, '../../web/mini_client/rating-ui.js'), 'utf8');

function load(responses) {
    const requests = [];
    const window = {};
    runInNewContext(code, {
        window, AbortController, URLSearchParams, setTimeout, clearTimeout, console,
        fetch: async (path, options = {}) => {
            requests.push({path, options});
            const key = options.method === 'POST' ? `${path.split('?')[0]}:POST` : path.split('?')[0];
            const body = typeof responses[key] === 'function' ? responses[key](path) : responses[key];
            return {ok: true, status: 200, json: async () => body};
        },
    });
    return {QuizRating: window.QuizRating, requests};
}
const page = (items, me, extra = {}) => ({scope: 'global', period: 'all', game: 'all', items, me, has_more: false,
    options: {rooms: [], chats: [], telegram: false}, ...extra});
const row = (rank, name, score, me = false) => ({rank, display_name: name, score, is_me: me});
const labels = (root, tag = 'button') => root.all().filter(n => n.tag === tag).map(n => n.textContent);

async function show(responses, overrides = {}) {
    const {QuizRating, requests} = load(responses), content = el('div'), errors = [], profile = [];
    await QuizRating.render({content, el, button, note, segmented, format, identity: 'guest', isCurrent: () => true,
        onError: error => errors.push(error.message), onProfile: () => profile.push(1), ...overrides});
    await flush();
    return {content, requests, errors, profile};
}

test('rows show only the nickname, the score and «ты»; nothing else reaches the page', async () => {
    const view = await show({'/api/account/rating': page([row(1, 'Аня', '12'), row(2, 'Ник', '9', true), row(3, 'Боря', '4')],
        {rank: 2, score: '9', listed: true, hidden: false, needs_nickname: false})});
    const text = view.content.textContent;
    assert.match(text, /Аня/); assert.match(text, /Ник · ты/); assert.match(text, /Ты — №2 · 9/);
    assert.equal(view.requests[0].path.includes('identity=guest'), true);
    assert.doesNotMatch(text, /account_id|user_id|@\w/);
    assert.deepEqual(labels(view.content).filter(label => /Комната|Чат/.test(label)), [], 'no room or chat slice without options');
});

test('a guest without a nickname sees the place and a step to choose a nickname', async () => {
    const view = await show({'/api/account/rating': page([row(1, 'Аня', '12')], {rank: 4, score: '3', listed: false, hidden: false, needs_nickname: true})});
    assert.match(view.content.textContent, /Ты — №4 · 3/);
    assert.match(view.content.textContent, /пока ты не выберешь ник/);
    await view.content.all().find(n => n.tag === 'button' && n.textContent === 'Выбрать ник').click();
    assert.equal(view.profile.length, 1);
});

test('period and game segments reload the same core with the chosen filters', async () => {
    const view = await show({'/api/account/rating': page([row(1, 'Аня', '2')], {rank: 1, score: '2', listed: true, hidden: false, needs_nickname: false})});
    await view.content.all().find(n => n.tag === 'button' && n.textContent === 'Неделя').click(); await flush();
    await view.content.all().find(n => n.tag === 'button' && n.textContent === 'Фото').click(); await flush();
    const last = new URLSearchParams(view.requests.at(-1).path.split('?')[1]);
    assert.equal(last.get('period'), 'week'); assert.equal(last.get('game'), 'photo'); assert.equal(last.get('scope'), 'global');
});

test('hiding from the rating posts once with both CSRF headers and reloads', async () => {
    let hidden = false;
    const view = await show({
        '/api/account/rating': () => page([row(1, 'Аня', '2')], {rank: 1, score: '2', listed: !hidden, hidden, needs_nickname: false}),
        '/api/account/rating-visibility:POST': () => { hidden = true; return {hidden: true}; },
    });
    await view.content.all().find(n => n.tag === 'button' && n.textContent === 'Не показывать меня в рейтинге').click(); await flush(); await flush();
    const post = view.requests.find(item => item.options.method === 'POST');
    assert.equal(post.path, '/api/account/rating-visibility?identity=guest');
    assert.equal(post.options.headers['X-Guest-CSRF'], '1'); assert.equal(post.options.headers['X-Mini-CSRF'], '1');
    assert.deepEqual(JSON.parse(post.options.body), {hidden: true});
    assert.match(view.content.textContent, /Тебя не видно в рейтинге/);
    assert.ok(labels(view.content).includes('Показывать меня'));
});

test('rooms and chats appear as slices only when the player has them', async () => {
    const options = {rooms: [{room_id: 'r1', title: 'Компания'}], chats: [{chat_id: -5, title: 'Чат друзей'}], telegram: true};
    const view = await show({'/api/account/rating': page([], {rank: null, score: '0', listed: true, hidden: false, needs_nickname: false}, {options})});
    assert.ok(labels(view.content).includes('Комната')); assert.ok(labels(view.content).includes('Чат'));
    assert.match(view.content.textContent, /Пока нет результатов/);
    await view.content.all().find(n => n.tag === 'button' && n.textContent === 'Комната').click(); await flush();
    const query = new URLSearchParams(view.requests.at(-1).path.split('?')[1]);
    assert.equal(query.get('scope'), 'room'); assert.equal(query.get('room_id'), 'r1');
});

test('errors go to the host callback and a stale render is ignored', async () => {
    const failing = load({'/api/account/rating': () => { throw new Error('boom'); }});
    const content = el('div'), errors = [];
    await failing.QuizRating.render({content, el, button, note, segmented, format, identity: '', isCurrent: () => true,
        onError: error => errors.push(error.message), onProfile() {}}).catch(error => errors.push(error.message));
    assert.equal(errors.length > 0, true);
    const stale = await show({'/api/account/rating': page([row(1, 'Аня', '2')], null)}, {isCurrent: () => false});
    assert.doesNotMatch(stale.content.textContent, /Аня/);
});

test('the host can open one chat slice directly (a chat\'s own Rating tab)', async () => {
    const {QuizRating, requests} = load({'/api/account/rating': page([row(1, 'Аня', '7')], {rank: 1, score: '7', listed: true, hidden: false, needs_nickname: false}, {
        scope: 'chat', options: {rooms: [], chats: [{chat_id: -5, title: 'Чат друзей'}], telegram: true}})});
    QuizRating.prefer({scope: 'chat', chatId: -5});
    const content = el('div');
    await QuizRating.render({content, el, button, note, segmented, format, identity: 'telegram', isCurrent: () => true, onError() {}, onProfile() {}});
    await flush();
    const first = new URLSearchParams(requests[0].path.split('?')[1]);
    assert.equal(first.get('scope'), 'chat'); assert.equal(first.get('chat_id'), '-5');
    assert.ok(content.all().some(n => n.tag === 'button' && n.textContent === 'Чат'));
});
