const {test} = require('node:test');
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {join} = require('node:path');
const {runInNewContext} = require('node:vm');

const root = join(__dirname, '../../minigames/alchemia-1.0');
const DATA = JSON.parse(readFileSync(join(root, 'data.json'), 'utf8'));
const game = readFileSync(join(root, 'game.js'), 'utf8');
const journey = readFileSync(join(root, 'journey.js'), 'utf8');
const revision = 'a'.repeat(64);
const first = DATA.campaigns[0], stage = first.stages[0];
const json = value => JSON.parse(JSON.stringify(value));

function engine() {
    const rendered = [], notices = [], nodes = new Map();
    const env = {
        DATA, E: new Map(DATA.elements.map(e => [e.id, e])), R: new Map(DATA.recipes.map(r => [r.key, r])),
        W: new Map(DATA.worlds.map(w => [w.id, w])), BASE: ['water', 'earth', 'fire', 'air'],
        CATALOG_REVISION: revision, MAX_TOKENS: 36, HISTORY_LIMIT: 160,
        matchMedia: () => ({matches: false}), uid: () => 'token',
        clamp: (n, a, b) => Math.max(a, Math.min(Math.max(a, b), n)),
        finite: (n, fallback = 0) => typeof n === 'number' && Number.isFinite(n) ? n : fallback,
        pairKey: (a, b) => [a, b].sort().join('+'),
        window: {}, document: {}, listen() {}, persist() {}, updateAchievements() {}, renderAll() {}, playSound() {},
        newThisSession: new Set(), modalPage: null, modalContext: null,
        hint: null, showHint() {}, currentChapter: () => DATA.chapters[0],
        serverJourney: {status: 'connecting', claims: [], points: 0, verifiedDiscovered: [], verifiedCrafted: []},
        $: id => { if (!nodes.has(id)) nodes.set(id, {}); return nodes.get(id); },
        icon: id => id, art: id => id, name: id => id, escapeHTML: value => value,
        openModal: (...args) => rendered.push(args), showToast: (...args) => notices.push(args),
    };
    runInNewContext(game.slice(game.indexOf('function freshState()'), game.indexOf('let storageOK=')), env);
    env.state = env.freshState();
    env.found = new Set(DATA.elements.map(e => e.id));
    env.knownRecipes = new Set(DATA.recipes.map(r => r.key));
    runInNewContext(journey, env);
    runInNewContext(game.slice(game.indexOf('function findHint(target='), game.indexOf('function showHint(')), env);
    runInNewContext(game.slice(game.indexOf('function applyRemoteState(remote)'), game.indexOf('Object.defineProperty(window,\'Alchemia\'')), env);
    return {env, rendered, notices};
}

test('старые локальные печати валидируются отдельно и не открывают серверные этапы', () => {
    const {env} = engine();
    env.state = env.cleanSave({format: 'alchemia', version: 2,
        discovered: DATA.elements.map(e => e.id), recipeKeys: DATA.recipes.map(r => r.key),
        claims: first.stages.map(s => s.id)});
    assert.deepEqual(json(env.state.claims), first.stages.map(s => s.id));
    assert.equal(env.campaignCurrent(first).id, stage.id);
    assert.equal(env.stageEligible(stage), false);
    assert.equal(env.rewardPoints(), 0);
    env.serverJourney.status = 'ready';
    assert.equal(env.stageEligible(stage), false, 'локальная коллекция не подтверждает серверные ингредиенты');
});

test('сохранение только серверных печатей проходит cleanSave без локальных рецептов', () => {
    const {env} = engine();
    const loaded = env.cleanSave({format: 'alchemia', version: 2, discovered: [], claims: [],
        serverClaims: [stage.id], expeditionPoints: stage.reward.points, catalogRevision: revision});
    assert.deepEqual(json(loaded.serverClaims), [stage.id]);
    assert.equal(loaded.expeditionPoints, stage.reward.points);
    env.state = loaded;
    assert.deepEqual(json(env.journeyClaims()), [], 'импортированный cache не становится live подтверждением');
});

test('claims-only ответ обновляет живую игру и сохраняет локальные старые печати', () => {
    const {env} = engine();
    env.state.claims = [first.stages[1].id];
    const result = env.applyRemoteState({claims: [stage.id], expedition_points: stage.reward.points,
        catalog_revision: revision, verified_discovered: [], verified_crafted: [], claim_receipts: []});
    assert.equal(result.accepted, true);
    assert.equal(result.claimsChanged, true);
    assert.deepEqual(json(env.journeyClaims()), [stage.id]);
    assert.deepEqual(json(env.state.claims), [first.stages[1].id]);
    assert.equal(env.rewardPoints(), stage.reward.points);
    assert.equal(env.campaignCurrent(first).id, first.stages[1].id);
});

test('запоздалый sync не отзывает печать из более нового claim ответа', () => {
    const {env} = engine();
    env.applyRemoteState({claims: [stage.id], expedition_points: stage.reward.points,
        catalog_revision: revision, verified_discovered: stage.goals, verified_crafted: []});
    env.applyRemoteState({claims: [], expedition_points: 0, catalog_revision: revision,
        verified_discovered: [], verified_crafted: []});
    assert.deepEqual(json(env.journeyClaims()), [stage.id]);
    assert.equal(env.rewardPoints(), stage.reward.points);
    assert.deepEqual(json(env.serverJourney.verifiedDiscovered), stage.goals);
});

test('локальная автономная игра продолжает получать локальные печати', async () => {
    const {env, rendered} = engine();
    env.serverJourney.status = 'local';
    await env.claimStage(stage.id);
    assert.deepEqual(json(env.state.claims), [stage.id]);
    assert.equal(env.rewardPoints(), stage.reward.points);
    assert.equal(rendered.at(-1)[1], 'Локальная печать получена');
});

test('offline или 401 claim не рисует печать и очки', async () => {
    const {env, rendered, notices} = engine();
    env.serverJourney.status = 'ready';
    env.serverJourney.verifiedDiscovered = DATA.elements.map(e => e.id);
    env.serverJourney.verifiedCrafted = DATA.recipes.map(r => r.key);
    env.window.MQBAlchemySync = {hasPendingClaim: () => false, claimStage: async () => ({ok: false, message: 'Сессия истекла'})};
    await env.claimStage(stage.id);
    assert.deepEqual(json(env.state.claims), []);
    assert.deepEqual(json(env.journeyClaims()), []);
    assert.equal(env.rewardPoints(), 0);
    assert.equal(rendered.length, 0);
    assert.equal(notices.at(-1)[0], 'Печать не подтверждена');
});

test('серверный успех отображает награду из ответа и не добавляет локальную печать', async () => {
    const {env, rendered} = engine();
    env.serverJourney.status = 'ready';
    env.serverJourney.verifiedDiscovered = DATA.elements.map(e => e.id);
    env.serverJourney.verifiedCrafted = DATA.recipes.map(r => r.key);
    env.window.MQBAlchemySync = {hasPendingClaim: () => false, claimStage: async () => {
        env.applyRemoteState({claims: [stage.id], expedition_points: stage.reward.points,
            catalog_revision: revision, verified_discovered: stage.goals, verified_crafted: []});
        return {ok: true, data: {awarded_expedition_points: 0}};
    }};
    await env.claimStage(stage.id);
    assert.deepEqual(json(env.state.claims), []);
    assert.equal(rendered.at(-1)[1], 'Печать подтверждена сервером');
    assert.match(rendered.at(-1)[2], /\+0 очков/, 'повтор не изображает новую награду из локального каталога');
});

test('несовпадение revision блокирует новое начисление', () => {
    const {env} = engine();
    env.applyRemoteState({claims: [], expedition_points: 0, catalog_revision: 'b'.repeat(64),
        verified_discovered: DATA.elements.map(e => e.id), verified_crafted: DATA.recipes.map(r => r.key)});
    assert.equal(env.serverJourney.status, 'catalog-mismatch');
    assert.equal(env.stageEligible(stage), false);
});

test('смена профиля инвалидирует все live печати и ингредиенты прежнего аккаунта', () => {
    const {env} = engine();
    env.applyRemoteState({claims: [stage.id], expedition_points: stage.reward.points, catalog_revision: revision,
        verified_discovered: stage.goals, verified_crafted: ['fire+water']});
    env.setServerStatus('profile-changed');
    assert.deepEqual(json(env.journeyClaims()), []);
    assert.deepEqual(json(env.serverJourney.verifiedDiscovered), []);
    assert.deepEqual(json(env.serverJourney.verifiedCrafted), []);
    assert.equal(env.rewardPoints(), 0);
    assert.equal(env.stageEligible(stage), false);
    assert.deepEqual(json(env.state.serverClaims), [stage.id], 'локальный cache прежнего аккаунта не стирается');
});

test('подсказка импортированной полной коллекции строит путь от verified базы', () => {
    const {env} = engine();
    env.serverJourney.status = 'ready';
    env.serverJourney.verifiedDiscovered = [...env.BASE];
    env.investigateCampaign(first.id);
    assert.ok(env.hint, 'полная local коллекция не замыкает подсказку обратно в тот же экран');
    assert.equal(env.hint.verified, true);
    assert.equal(env.hint.alternative, true, 'старый локальный результат можно получить заново');
    assert.ok(env.BASE.includes(env.hint.recipe.a));
    assert.ok(env.BASE.includes(env.hint.recipe.b));
    assert.ok(!env.BASE.includes(env.hint.recipe.result));
});
