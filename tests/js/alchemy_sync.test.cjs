// Тесты моста «Алхимия ↔ квиз»: без браузера, без сети — только подделки окружения.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {join} = require('node:path');
const {runInNewContext} = require('node:vm');

const source = readFileSync(join(__dirname, '../../minigames/alchemia-1.0/sync.js'), 'utf8');
const flush = () => new Promise(resolve => setImmediate(resolve));

function storage(initial = {}) {
    const data = new Map(Object.entries(initial));
    return {
        getItem: key => (data.has(key) ? data.get(key) : null),
        setItem: (key, value) => { data.set(key, String(value)); },
        removeItem: key => { data.delete(key); },
        dump: () => Object.fromEntries(data),
    };
}

function bridge({token = 'x'.repeat(32), local = {}, session = {}, response = {}, fail = false} = {}) {
    const localStore = storage(local);
    const sessionStore = storage(session);
    const calls = [];
    const reloads = {count: 0};
    const banners = [];
    const listeners = {};
    const sandbox = {
        localStorage: localStore,
        sessionStorage: sessionStore,
        location: {hash: token ? `#t=${token}` : '', reload: () => { reloads.count += 1; }},
        document: {
            hidden: false,
            createElement: () => ({style: {}, remove() {}, set textContent(value) { banners.push(value); }, get textContent() { return banners[banners.length - 1]; }}),
            body: {append() {}},
        },
        fetch: async (url, options) => {
            calls.push({url, options});
            if (fail) throw new Error('сеть недоступна');
            return {ok: true, status: 200, json: async () => response};
        },
        addEventListener: (event, callback) => { listeners[event] = callback; },
        requestAnimationFrame: callback => callback(),
        setInterval: () => 0,
        setTimeout: () => 0,
    };
    runInNewContext(source, sandbox);
    return {listeners, calls, reloads, banners, localStore, sessionStore, token};
}

const save = (discovered, extra = {}) => JSON.stringify({
    format: 'alchemia', version: 2, discovered, recipeKeys: ['air+water'], tried: ['air+water'], attempts: 7, ...extra,
});

test('отправляет сводку и подставляет серверный прогресс', async () => {
    const env = bridge({
        local: {'alchemia.atlas': save(['water', 'earth', 'fire', 'air', 'steam'])},
        response: {awarded: 8, points_total: 24, discovered: ['water', 'earth', 'fire', 'air', 'steam', 'mud', 'sand', 'dust']},
    });
    env.listeners.load();
    await flush();
    assert.equal(env.calls.length, 1);
    assert.equal(env.calls[0].url, '/api/mini/alchemy/sync');
    assert.equal(env.calls[0].options.method, 'POST');
    assert.equal(env.calls[0].options.headers.Authorization, `Bearer ${env.token}`);
    const body = JSON.parse(env.calls[0].options.body);
    assert.deepEqual(body.discovered, ['water', 'earth', 'fire', 'air', 'steam']);
    assert.deepEqual(body.crafted, ['air+water']);
    assert.equal(body.attempts, 7);
    const stored = JSON.parse(env.localStore.getItem('alchemia.atlas'));
    assert.equal(stored.discovered.length, 8, 'серверные открытия должны попасть в сохранение');
    assert.equal(env.reloads.count, 1, 'страница перезагружается один раз, чтобы движок подхватил прогресс');
    assert.match(env.banners.join(' '), /\+8 очков/);
});

test('без токена сессии ничего не отправляет', async () => {
    const env = bridge({token: '', local: {'alchemia.atlas': save(['water'])}});
    env.listeners.load();
    await flush();
    assert.equal(env.calls.length, 0);
    assert.equal(env.reloads.count, 0);
});

test('читает самый первый формат сохранения (список id)', async () => {
    const env = bridge({local: {elementAlchemyDiscovered: JSON.stringify(['water', 'earth', 'air'])}, response: {discovered: []}});
    env.listeners.load();
    await flush();
    assert.equal(env.calls.length, 1);
    assert.deepEqual(JSON.parse(env.calls[0].options.body).discovered, ['water', 'earth', 'air']);
});

test('обрыв сети не ломает игру и не перезагружает страницу', async () => {
    const env = bridge({local: {'alchemia.atlas': save(['water'])}, fail: true});
    env.listeners.load();
    await flush();
    assert.equal(env.calls.length, 1);
    assert.equal(env.reloads.count, 0);
});

test('повторная подстановка в одной сессии не перезагружает страницу второй раз', async () => {
    const env = bridge({
        local: {'alchemia.atlas': save(['water'])},
        session: {'mqb-alchemy-restored': '1'},
        response: {discovered: ['water', 'earth', 'fire']},
    });
    env.listeners.load();
    await flush();
    assert.equal(env.reloads.count, 0, 'второй перезагрузки в той же сессии быть не должно');
    const stored = JSON.parse(env.localStore.getItem('alchemia.atlas'));
    assert.deepEqual(stored.discovered, ['water', 'earth', 'fire'], 'прогресс всё равно дописывается');
});

test('на новом устройстве создаёт сохранение из серверного прогресса', async () => {
    // Игра ещё ни разу не сохранялась: раньше мост в этом случае молчал, и игрок
    // видел пустой атлас на втором устройстве.
    const env = bridge({local: {}, response: {awarded: 0, points_total: 24, discovered: ['water', 'earth', 'fire']}});
    env.listeners.load();
    await flush();
    const stored = JSON.parse(env.localStore.getItem('alchemia.atlas'));
    assert.equal(stored.format, 'alchemia');
    assert.deepEqual(stored.discovered, ['water', 'earth', 'fire']);
    assert.equal(env.reloads.count, 1, 'страница перезагружается, чтобы движок прочитал сохранение');
});

test('берёт токен из localStorage, если его нет в sessionStorage', async () => {
    const env = bridge({
        token: '',
        local: {'mqb-mini-token': 'y'.repeat(32), 'alchemia.atlas': save(['water'])},
        response: {discovered: []},
    });
    env.listeners.load();
    await flush();
    assert.equal(env.calls.length, 1);
    assert.equal(env.calls[0].options.headers.Authorization, `Bearer ${'y'.repeat(32)}`);
});
