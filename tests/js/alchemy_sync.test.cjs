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

const catalogRevision = 'a'.repeat(64);
function bridge({token = 'x'.repeat(32), guestId = null, local = {}, session = {}, response = {}, status = 200, fail = false, request = null, profileRequest = null, protocol = 'https:', uuid = 'command-0001'} = {}) {
    const localStore = storage(local);
    const sessionStore = storage(session);
    const calls = [];
    const reloads = {count: 0};
    const banners = [];
    const listeners = {};
    const applied = [];
    const statuses = [];
    const intervals = [];
    let profileCalls = 0;
    const sandbox = {
        window: {
            MQB_ALCHEMY_GUEST_ID: guestId,
            Alchemia: {catalogRevision, setServerStatus: value => statuses.push(value), applyRemoteState: remote => { applied.push(remote); return {added: Array.isArray(remote.discovered) ? remote.discovered.length : 0}; }},
        },
        localStorage: localStore,
        sessionStorage: sessionStore,
        location: {hash: '', protocol, reload: () => { reloads.count += 1; }},
        crypto: {randomUUID: () => uuid},
        document: {
            hidden: false,
            createElement: () => ({style: {}, remove() {}, set textContent(value) { banners.push(value); }, get textContent() { return banners[banners.length - 1]; }}),
            body: {append() {}},
        },
        fetch: async (url, options) => {
            if (url === '/api/mini/me') {
                profileCalls += 1;
                if (profileRequest) return profileRequest(profileCalls);
                return {ok: Boolean(token), status: token ? 200 : 401, json: async () => ({user_id: '42'})};
            }
            calls.push({url, options});
            if (request) return request(url, options, calls.length);
            if (fail) throw new Error('сеть недоступна');
            return {ok: status >= 200 && status < 300, status, json: async () => response};
        },
        addEventListener: (event, callback) => { listeners[event] = callback; },
        requestAnimationFrame: callback => callback(),
        setInterval: callback => { intervals.push(callback); return 0; },
        setTimeout: () => 0,
    };
    runInNewContext(source, sandbox);
    const environment = {listeners, calls, reloads, banners, localStore, sessionStore, token, applied, statuses, intervals,
        set hidden(value) { sandbox.document.hidden = value; },
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
    assert.equal(env.calls[0].options.headers['X-Mini-User'], '42');
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
    assert.equal(env.calls[0].options.headers['X-Mini-User'], '42');
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
    const env = bridge({guestId, status: 409, response: {code: 'profile_changed'}, local: {[`alchemia.atlas.guest.${guestId}`]: save(['water'])}});
    env.listeners.load();
    await flush();
    assert.equal(env.calls[0].options.headers['X-Guest-Account'], guestId);
    env.hidden = true;
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
    env.hidden = true;
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

const projection = (extra = {}) => ({discovered: [], crafted: [], attempts: 0,
    catalog_revision: catalogRevision, claims: [], expedition_points: 0, claim_receipts: [],
    verified_discovered: ['water', 'earth', 'fire', 'air'], verified_crafted: [], ...extra});
const reply = (data, status = 200) => ({ok: status >= 200 && status < 300, status, json: async () => data});
const claimReply = command => projection({command_id: command.command_id, stage_id: command.stage_id,
    claims: [command.stage_id], expedition_points: 5, awarded_expedition_points: 5,
    reward: {points: 5}, claim_receipts: [{command_id: command.command_id, stage_id: command.stage_id}]});

test('восстанавливает только печати и очки на чистом устройстве', async () => {
    const env = bridge({response: projection({claims: ['origins-1'], expedition_points: 5})});
    env.listeners.load();
    await flush();
    const restored = JSON.parse(env.localStore.getItem('alchemia.atlas'));
    assert.deepEqual(restored.claims, [], 'локальные печати не подменяются серверными');
    assert.deepEqual(restored.serverClaims, ['origins-1']);
    assert.equal(restored.expeditionPoints, 5);
    assert.equal(env.applied.length, 1, 'claims-only projection применяется к живой игре');
    assert.deepEqual(env.applied[0].claims, ['origins-1']);
});

test('старые локальные печати не отправляются как доказательство награды', async () => {
    const env = bridge({local: {'alchemia.atlas': save(['water'], {claims: ['origins-1'], serverClaims: ['fake']})},
        response: projection()});
    env.listeners.load();
    await flush();
    const sent = JSON.parse(env.calls[0].options.body);
    assert.equal(sent.claims, undefined);
    assert.equal(sent.serverClaims, undefined);
    assert.deepEqual(JSON.parse(env.localStore.getItem('alchemia.atlas')).claims, ['origins-1']);
    assert.deepEqual(env.applied[0].claims, []);
});

test('гость подтверждает craft через свой серверный аккаунт без рейтинговой награды', async () => {
    const guestId = '11111111-1111-4111-8111-111111111111';
    const env = bridge({guestId, response: projection({verified: true, awarded: 0, verified_discovered: ['steam']})});
    await env.window.MQBAlchemySync.verifyCraft('water', 'fire');
    assert.equal(env.calls[0].url, '/api/guest/alchemy/craft');
    assert.equal(env.calls[0].options.headers['X-Guest-Account'], guestId);
    assert.equal(env.calls[0].options.headers['X-Guest-CSRF'], '1');
    assert.deepEqual(env.applied[0].verified_discovered, ['steam']);
    assert.equal(env.banners.length, 0);
});

test('неизвестный результат claim повторяется с тем же command_id после перезагрузки', async () => {
    const first = bridge({request: async () => { throw new Error('response lost'); }});
    const failed = await first.window.MQBAlchemySync.claimStage('origins-1');
    assert.equal(failed.ok, false);
    assert.equal(first.window.MQBAlchemySync.hasPendingClaim('origins-1'), true);
    const firstBody = JSON.parse(first.calls[0].options.body);
    assert.equal(first.calls[0].options.headers['X-Mini-User'], '42');
    assert.deepEqual(firstBody, {command_id: 'command-0001', stage_id: 'origins-1', catalog_revision: catalogRevision});
    assert.equal(first.banners.length, 0, 'нет ложного подтверждения сохранения на сервере');
    const second = bridge({uuid: 'command-0002', local: first.localStore.dump(), request: async (url, options) => reply(claimReply(JSON.parse(options.body)))});
    const retried = await second.window.MQBAlchemySync.claimStage('origins-1');
    assert.equal(retried.ok, true);
    assert.equal(second.calls[0].options.body, first.calls[0].options.body);
    assert.equal(second.window.MQBAlchemySync.hasPendingClaim('origins-1'), false);
    assert.equal(JSON.parse(second.localStore.getItem('alchemia.atlas')).expeditionPoints, 5);
});

test('двойное нажатие claim отправляет одну команду', async () => {
    const env = bridge({request: async (url, options) => reply(claimReply(JSON.parse(options.body)))});
    const first = env.window.MQBAlchemySync.claimStage('origins-1');
    const second = env.window.MQBAlchemySync.claimStage('origins-1');
    assert.equal(first, second);
    assert.equal((await first).ok, true);
    assert.equal(env.calls.length, 1);
});

test('401 не выдаёт печать и сохраняет pending команду', async () => {
    const env = bridge({status: 401});
    assert.equal((await env.window.MQBAlchemySync.claimStage('origins-1')).ok, false);
    assert.equal(env.window.MQBAlchemySync.hasPendingClaim('origins-1'), true);
    assert.equal(env.applied.length, 0);
    assert.equal(env.statuses.at(-1), 'unauthorized');
    assert.doesNotMatch(env.banners.join(' '), /Подтверждено сервером|Печать получена/);
});

test('5xx и некорректный ответ сохраняют тот же command_id для безопасного повтора', async () => {
    let turn = 0;
    const env = bridge({request: async () => ++turn === 1 ? reply({}, 503) : reply(projection({claims: ['origins-1']}))});
    assert.equal((await env.window.MQBAlchemySync.claimStage('origins-1')).ok, false);
    assert.equal((await env.window.MQBAlchemySync.claimStage('origins-1')).ok, false);
    assert.equal(env.calls[0].options.body, env.calls[1].options.body);
    assert.equal(env.window.MQBAlchemySync.hasPendingClaim('origins-1'), true);
    assert.equal(env.applied.length, 0);
});

test('расхождение каталога гостя не выдаёт печать и не притворяется сменой аккаунта', async () => {
    const env = bridge({guestId: '11111111-1111-4111-8111-111111111111', status: 409, response: {code: 'catalog_changed'}});
    assert.equal((await env.window.MQBAlchemySync.claimStage('origins-1')).ok, false);
    assert.equal(env.window.MQBAlchemySync.hasPendingClaim('origins-1'), false);
    assert.equal(env.statuses.at(-1), 'catalog-mismatch');
    assert.equal(env.applied.length, 0);
});

test('claims-only восстановление работает через запасную перезагрузку', async () => {
    const env = bridge({response: projection({claims: ['origins-1'], expedition_points: 5})});
    env.declineRemote = true;
    env.listeners.load();
    await flush();
    assert.equal(env.reloads.count, 1);
    assert.deepEqual(JSON.parse(env.localStore.getItem('alchemia.atlas')).serverClaims, ['origins-1']);
});

test('после временного обрыва первой проверки сессии периодический sync восстанавливается', async () => {
    const env = bridge({profileRequest: async count => {
        if (count === 1) throw new Error('offline');
        return reply({user_id: '42'});
    }, response: projection()});
    await env.listeners.load();
    assert.equal(env.calls.length, 0);
    assert.equal(env.statuses.at(-1), 'offline');
    await env.intervals[0]();
    assert.equal(env.calls.length, 1);
    assert.equal(env.applied.length, 1);
});

test('истёкшая Mini сессия не переключает награды в локальный режим', async () => {
    const env = bridge({profileRequest: async count => count === 1 ? reply({user_id: '42'}) : reply({}, 401),
        request: async (url, options, count) => count === 1 ? reply(projection()) : reply({}, 401)});
    await env.listeners.load();
    await env.intervals[0]();
    await env.intervals[0]();
    assert.equal(env.statuses.at(-1), 'unauthorized');
    assert.equal(env.calls.length, 2);
});

test('смена Mini пользователя после 401 изолирует старую вкладку и не импортирует старый прогресс', async () => {
    const env = bridge({profileRequest: async count => reply({user_id: count === 1 ? '42' : '43'}),
        request: async (url, options, count) => count === 1
            ? reply(projection({claims: ['origins-1'], expedition_points: 5})) : reply({}, 401)});
    await env.listeners.load();
    await env.intervals[0]();
    await env.intervals[0]();
    assert.equal(env.statuses.at(-1), 'profile-changed');
    assert.equal(env.calls.length, 2, 'данные первого пользователя не отправляются под новой cookie');
    assert.equal((await env.window.MQBAlchemySync.claimStage('origins-2')).ok, false);
    await env.window.MQBAlchemySync.verifyCraft('water', 'fire');
    assert.equal(env.calls.length, 2);
    assert.match(env.banners.join(' '), /Профиль изменился/);
});

test('profile_changed guest claim инвалидирует вкладку, сохраняя pending команду прежнего аккаунта', async () => {
    const env = bridge({guestId: '11111111-1111-4111-8111-111111111111', status: 409,
        response: {code: 'profile_changed'}});
    assert.equal((await env.window.MQBAlchemySync.claimStage('origins-1')).ok, false);
    assert.equal(env.statuses.at(-1), 'profile-changed');
    assert.equal(env.window.MQBAlchemySync.hasPendingClaim('origins-1'), true);
    assert.equal((await env.window.MQBAlchemySync.claimStage('origins-1')).ok, false);
    assert.equal(env.calls.length, 1);
});

test('автономный file HTML остаётся локальным при недоступном API', async () => {
    const env = bridge({protocol: 'file:', profileRequest: async () => { throw new Error('no API'); }});
    await env.listeners.load();
    assert.equal(env.statuses.at(-1), 'local');
    assert.equal(env.calls.length, 0);
});

test('прямая смена cookie A на B отклоняется expected user fence до слияния проекции', async () => {
    let actor = '42';
    const env = bridge({request: async (url, options) => {
        if (options.headers['X-Mini-User'] !== actor) return reply({code: 'profile_changed'}, 409);
        return reply(projection({claims: ['origins-1'], expedition_points: 5}));
    }});
    await env.listeners.load();
    assert.equal(env.applied.length, 1);
    actor = '43';
    await env.intervals[0]();
    assert.equal(env.calls[1].options.headers['X-Mini-User'], '42');
    assert.equal(env.applied.length, 1, 'проекция B не сливается в состояние A');
    assert.equal(env.statuses.at(-1), 'profile-changed');
    await env.window.MQBAlchemySync.verifyCraft('water', 'fire');
    assert.equal((await env.window.MQBAlchemySync.claimStage('origins-2')).ok, false);
    await env.intervals[0]();
    assert.equal(env.calls.length, 2, 'старая вкладка больше не отправляет команды');
});

test('запоздалый успех после инвалидирования сессии не возвращает печати старого аккаунта', async () => {
    let finish;
    const env = bridge({request: async (url, options) => {
        const command = JSON.parse(options.body);
        if (command.stage_id === 'origins-1') return new Promise(resolve => { finish = () => resolve(reply(claimReply(command))); });
        return reply({code: 'profile_changed'}, 409);
    }});
    const older = env.window.MQBAlchemySync.claimStage('origins-1');
    await flush();
    assert.equal((await env.window.MQBAlchemySync.claimStage('origins-2')).ok, false);
    finish();
    assert.equal((await older).ok, false);
    assert.equal(env.statuses.at(-1), 'profile-changed');
    assert.equal(env.applied.length, 0);
    assert.equal(env.window.MQBAlchemySync.hasPendingClaim('origins-1'), true);
});
