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

function bridge({token = 'x'.repeat(32), guestId = null, local = {}, session = {}, response = {}, status = 200, fail = false} = {}) {
    const localStore = storage(local);
    const sessionStore = storage(session);
    const calls = [];
    const reloads = {count: 0};
    const banners = [];
    const listeners = {};
    const applied = [];
    const sandbox = {
        window: {
            MQB_ALCHEMY_GUEST_ID: guestId,
            Alchemia: {applyRemoteState: remote => { applied.push(remote); return {added: Array.isArray(remote.discovered) ? remote.discovered.length : 0}; }},
        },
        localStorage: localStore,
        sessionStorage: sessionStore,
        location: {hash: '', reload: () => { reloads.count += 1; }},
        crypto: {randomUUID: () => 'command-0001'},
        document: {
            hidden: false,
            createElement: () => ({style: {}, remove() {}, set textContent(value) { banners.push(value); }, get textContent() { return banners[banners.length - 1]; }}),
            body: {append() {}},
        },
        fetch: async (url, options) => {
            if (url === '/api/mini/me') return {ok: Boolean(token), status: token ? 200 : 401, json: async () => ({})};
            calls.push({url, options});
            if (fail) throw new Error('сеть недоступна');
            return {ok: status >= 200 && status < 300, status, json: async () => response};
        },
        addEventListener: (event, callback) => { listeners[event] = callback; },
        requestAnimationFrame: callback => callback(),
        setInterval: () => 0,
        setTimeout: () => 0,
    };
    runInNewContext(source, sandbox);
    const environment = {listeners, calls, reloads, banners, localStore, sessionStore, token, applied,
        // Игра «не умеет» вливать чужой прогресс — проверяем запасной путь моста.
        set declineRemote(value) { sandbox.window.Alchemia.applyRemoteState = () => ({added: 0}); },
        get declineRemote() { return false; },
        window: sandbox.window};
    return environment;
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
    assert.equal(env.calls[0].options.headers.Authorization, undefined);
    assert.equal(env.calls[0].options.headers['X-Mini-CSRF'], '1');
    const body = JSON.parse(env.calls[0].options.body);
    assert.deepEqual(body.discovered, ['water', 'earth', 'fire', 'air', 'steam']);
    assert.deepEqual(body.crafted, ['air+water']);
    assert.equal(body.attempts, 7);
    const stored = JSON.parse(env.localStore.getItem('alchemia.atlas'));
    assert.equal(stored.discovered.length, 8, 'серверные открытия должны попасть в сохранение');
    assert.equal(env.applied.length, 1, 'прогресс вливается в живую игру, а не только в localStorage');
    assert.equal(env.reloads.count, 0, 'перезагружать страницу не нужно, если игра приняла прогресс');
    assert.match(env.banners.join(' '), /\+8 очков/);
});

test('подтверждает новый рецепт отдельной серверной командой', async () => {
    const env = bridge({response: {verified: true, awarded: 2, points_total: 2}});
    await env.window.MQBAlchemySync.verifyCraft('water', 'fire');
    assert.equal(env.calls.length, 1);
    assert.equal(env.calls[0].url, '/api/mini/alchemy/craft');
    assert.equal(env.calls[0].options.method, 'POST');
    assert.equal(env.calls[0].options.headers.Authorization, undefined);
    assert.equal(env.calls[0].options.headers['X-Mini-CSRF'], '1');
    assert.deepEqual(JSON.parse(env.calls[0].options.body), {
        command_id: 'command-0001', ingredient_a: 'water', ingredient_b: 'fire',
    });
    assert.match(env.banners.join(' '), /Подтверждено сервером/);
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

test('новое устройство: серверный прогресс вливается в живую игру', async () => {
    // Именно эта ситуация была у живого игрока: на сервере 143 открытия, на
    // устройстве игра стартовала с четырьмя базовыми — и затирала серверные.
    const env = bridge({
        local: {'alchemia.atlas': save(['water', 'earth', 'fire', 'air'])},
        response: {awarded: 0, points_total: 286, discovered: ['water', 'earth', 'fire', 'air', 'steam', 'mud', 'sand']},
    });
    env.listeners.load();
    await flush();
    assert.equal(env.applied.length, 1, 'состояние должно уйти в живую игру');
    assert.deepEqual(env.applied[0].discovered, ['water', 'earth', 'fire', 'air', 'steam', 'mud', 'sand']);
    assert.equal(env.reloads.count, 0, 'игрока не выкидываем перезагрузкой');
});

test('если игра не принимает прогресс — работает запасной путь с перезагрузкой', async () => {
    const env = bridge({
        local: {'alchemia.atlas': save(['water'])},
        response: {discovered: ['water', 'earth', 'fire']},
    });
    // Игра еще не умеет вливать чужой прогресс (старая версия страницы): мост
    // обязан дописать сохранение и один раз перезагрузить страницу.
    env.declineRemote = true;
    env.listeners.load();
    await flush();
    const stored = JSON.parse(env.localStore.getItem('alchemia.atlas'));
    assert.deepEqual(stored.discovered, ['water', 'earth', 'fire'], 'запасной путь пишет в сохранение');
    assert.equal(env.reloads.count, 1, 'и один раз перезагружает страницу');
});

test('на новом устройстве создаёт сохранение из серверного прогресса', async () => {
    // Игра ещё ни разу не сохранялась: раньше мост в этом случае молчал, и игрок
    // видел пустой атлас на втором устройстве.
    const env = bridge({local: {}, response: {awarded: 0, points_total: 24, discovered: ['water', 'earth', 'fire']}});
    env.declineRemote = true;                      // проверяем именно запись сохранения
    env.listeners.load();
    await flush();
    const stored = JSON.parse(env.localStore.getItem('alchemia.atlas'));
    assert.equal(stored.format, 'alchemia');
    assert.deepEqual(stored.discovered, ['water', 'earth', 'fire']);
    assert.equal(env.reloads.count, 1, 'страница перезагружается, чтобы движок прочитал сохранение');
});

test('не читает токены из браузерного хранилища и использует HttpOnly cookie', async () => {
    const env = bridge({
        local: {'mqb-mini-token': 'y'.repeat(32), 'alchemia.atlas': save(['water'])},
        response: {discovered: []},
    });
    env.listeners.load();
    await flush();
    assert.equal(env.calls.length, 1);
    assert.equal(env.calls[0].options.headers.Authorization, undefined);
    assert.equal(env.calls[0].options.headers['X-Mini-CSRF'], '1');
});

test('гость использует отдельное сохранение и не отправляет оставшийся Telegram token', async () => {
    const guestId = '11111111-1111-4111-8111-111111111111';
    const scoped = `alchemia.atlas.guest.${guestId}`;
    const env = bridge({guestId, local: {
        'mqb-mini-token': 'y'.repeat(32),
        'alchemia.atlas': save(['water', 'secret-from-telegram']),
        [scoped]: save(['water', 'earth', 'fire', 'air', 'steam']),
    }, response: {awarded: 0, discovered: ['water', 'earth', 'fire', 'air', 'steam', 'mud']}});
    env.listeners.load();
    await flush();
    assert.equal(env.calls[0].url, '/api/guest/alchemy/sync');
    assert.equal(env.calls[0].options.headers.Authorization, undefined);
    assert.equal(env.calls[0].options.headers['X-Guest-CSRF'], '1');
    assert.equal(env.calls[0].options.headers['X-Guest-Account'], guestId);
    assert.deepEqual(JSON.parse(env.calls[0].options.body).discovered, ['water', 'earth', 'fire', 'air', 'steam']);
    assert.deepEqual(JSON.parse(env.localStore.getItem('alchemia.atlas')).discovered,
        ['water', 'secret-from-telegram']);
    assert.deepEqual(JSON.parse(env.localStore.getItem(scoped)).discovered,
        ['water', 'earth', 'fire', 'air', 'steam', 'mud']);
});

test('старая гостевая вкладка прекращает sync после смены cookie', async () => {
    const guestId = '11111111-1111-4111-8111-111111111111';
    const env = bridge({guestId, status: 409, local: {[`alchemia.atlas.guest.${guestId}`]: save(['water'])}});
    env.listeners.load();
    await flush();
    assert.equal(env.calls[0].options.headers['X-Guest-Account'], guestId);
    env.listeners.visibilitychange();
    await flush();
    assert.equal(env.calls.length, 1);
    assert.match(env.banners.join(' '), /Гостевой профиль изменился/);
});

test('истёкшая гостевая сессия сообщает о локальном сохранении', async () => {
    const guestId = '11111111-1111-4111-8111-111111111111';
    const env = bridge({guestId, status: 401});
    env.listeners.load();
    await flush();
    env.listeners.visibilitychange();
    await flush();
    assert.equal(env.calls.length, 1);
    assert.match(env.banners.join(' '), /Доступ к гостевому профилю потерян/);
});

test('гость восстанавливает рецепты и число опытов при тех же открытиях', async () => {
    const guestId = '11111111-1111-4111-8111-111111111111';
    const key = `alchemia.atlas.guest.${guestId}`;
    const env = bridge({guestId, local: {[key]: save(['water', 'earth', 'fire', 'air'], {recipeKeys: [], attempts: 0})},
        response: {discovered: ['water', 'earth', 'fire', 'air'], crafted: ['air+water'], attempts: 17, awarded: 0}});
    env.listeners.load();
    await flush();
    const restored = JSON.parse(env.localStore.getItem(key));
    assert.deepEqual(restored.recipeKeys, ['air+water']);
    assert.equal(restored.attempts, 17);
    assert.deepEqual(env.applied[0].recipeKeys, ['air+water']);
    assert.equal(env.applied[0].attempts, 17);
});

test('второй гость не загружает сохранение первого', async () => {
    const first = '11111111-1111-4111-8111-111111111111';
    const second = '22222222-2222-4222-8222-222222222222';
    const env = bridge({token: '', guestId: second, local: {
        [`alchemia.atlas.guest.${first}`]: save(['water', 'steam']),
        'alchemia.atlas': save(['water', 'earth', 'steam']),
    }, response: {awarded: 0, discovered: ['water', 'earth', 'fire', 'air']}});
    env.listeners.load();
    await flush();
    assert.deepEqual(JSON.parse(env.calls[0].options.body).discovered, []);
    assert.equal(env.localStore.getItem(`alchemia.atlas.guest.${first}`), save(['water', 'steam']));
});
