'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {runInNewContext} = require('node:vm');
const source = fs.readFileSync(path.resolve(__dirname, '../../web/mini_client/night-case-ui.js'), 'utf8');
const api = require('../../web/mini_client/night-case-ui.js');

test('immutable manifest requires the server pointer, exact canonical hash and known safe files', async () => {
    const crypto = require('node:crypto');
    const hash = value => crypto.createHash('sha256').update(JSON.stringify(sort(value))).digest('hex');
    const sort = value => Array.isArray(value) ? value.map(sort) : value && typeof value === 'object' ? Object.fromEntries(Object.keys(value).sort().map(key => [key, sort(value[key])])) : value;
    const manifest = {schema: 'nc-assets/2', world: 'manor_lake', files: {'assets/library_day.webp': 'a'.repeat(64), 'assets/library_night.webp': 'b'.repeat(64)}, assets: {
        manor_loc_library: {url: 'assets/library_day.webp', alt: 'Библиотека', variants: {night: 'assets/library_night.webp', day: 'https://foreign.invalid/image.webp'}},
        unsafe: {url: 'assets/unknown.webp'}, traversal: {url: '../secret.webp'}, query: {url: 'assets/library_day.webp?secret'},
    }};
    const digest = hash(manifest), binding = {manifest_sha256: digest, manifest_url: `/app/night/packs/${digest}/assets.json`};
    const parsed = await api.verifiedManifest(manifest, 'manor_lake', binding);
    assert.equal(parsed.size, 1);
    assert.equal(parsed.get('manor_loc_library').variants.night, `/app/night/packs/${digest}/assets/library_night.webp`);
    assert.equal(parsed.get('manor_loc_library').variants.day, undefined);
    assert.equal((await api.verifiedManifest({...manifest, world: 'changed'}, 'manor_lake', binding)).size, 0);
    assert.equal(api.assetManifest(manifest, 'another_world', binding).size, 0);
    for (const pointer of ['/app/night/worlds/manor_lake/assets.json', binding.manifest_url + '?q=1', binding.manifest_url.replace('/packs/', '/packs/%2e%2e/'), 'https://else.invalid/assets.json']) {
        assert.equal(api.artPointer({...binding, manifest_url: pointer}), null);
    }
    const unsafeFile = {...manifest, files: {'assets/%2fsecret.webp': 'a'.repeat(64)}};
    assert.equal(api.assetManifest(unsafeFile, 'manor_lake', binding).size, 0);
});

test('an uncertain write retries the identical command instead of generating another action', async () => {
    const calls = []; let fail = true;
    const outbox = api.createOutbox(async (url, body) => { calls.push({url, body: structuredClone(body)}); if (fail) { const error = new Error(); error.network = true; throw error; } return {receipt: {accepted: true}}; });
    const original = {command_id: 'stable-command', kind: 'act', params: {action_id: 'inspect'}};
    await assert.rejects(outbox.send('/commands', original));
    original.params.action_id = 'changed-after-send';
    assert.equal(outbox.pending.body.params.action_id, 'inspect');
    await assert.rejects(outbox.send('/commands', {command_id: 'new-command'}), /pending_write/);
    fail = false; await outbox.retry();
    assert.deepEqual(calls[0], calls[1]); assert.equal(outbox.pending, null);
});

test('a definitive conflict closes the attempt and never silently rebuilds fences', async () => {
    const outbox = api.createOutbox(async () => { const error = new Error(); error.status = 409; throw error; });
    await assert.rejects(outbox.send('/commands', {command_id: 'original'}));
    assert.equal(outbox.pending, null);
    const view = {public: {clock: {window_idx: 3, window_seq: 9, timer_seq: 'PRIVATE'}}, self: {actor_seq: 7, account_id: 'PRIVATE'}};
    assert.deepEqual(api.envelope(view, 'seen', {}, 'stable-command'), {command_id: 'stable-command', kind: 'seen', params: {}, window_idx: 3, window_seq: 9, actor_seq: 7});
    const selected = api.playerView({...view, sealed: 'PRIVATE', self: {...view.self, unknown_private: 'PRIVATE', receipts: [{result_ref: 'PRIVATE'}]}});
    assert.equal(selected.self.unknown_private, undefined);
    assert.equal(selected.self.receipts, undefined);
    assert.equal(selected.sealed, undefined);
});

class Node {
    constructor(tag) { this.tagName = tag; this.children = []; this.attrs = {}; this.events = {}; this.dataset = {}; this.value = ''; this._text = ''; this.className = ''; this.classList = {add() {}, remove() {}}; }
    set textContent(value) { this._text = String(value); this.children = []; }
    get textContent() { return this._text + this.children.map(x => typeof x === 'string' ? x : x.textContent).join(' '); }
    set innerHTML(value) { throw new Error('HTML parsing is forbidden'); }
    append(...nodes) { this.children.push(...nodes.filter(x => x != null)); }
    prepend(...nodes) { this.children.unshift(...nodes); }
    replaceChildren(...nodes) { this.children = nodes; this._text = ''; }
    setAttribute(key, value) { this.attrs[key] = String(value); }
    addEventListener(kind, fn) { this.events[kind] = fn; }
    click() { return this.events.click?.(); }
}
const find = (node, predicate) => predicate(node) ? node : node.children.map(x => x instanceof Node ? find(x, predicate) : null).find(Boolean);
const settle = async () => { for (let i = 0; i < 5; i++) await new Promise(resolve => setImmediate(resolve)); };

const VIEWER = '70a7918e-00ad-40da-9ad8-136a4b2bbc0a';
function controller(view, requestHook, options = {}) {
    const calls = [], nodes = [], intervals = new Set(); let next = 0;
    const make = (tag, cls, text) => { const node = new Node(tag); node.className = cls || ''; if (text != null) node.textContent = text; nodes.push(node); return node; };
    const wrap = (cls, children) => { const node = make('section', cls); node.append(...children.flat(Infinity)); return node; };
    const kit = {
        button(label, click, opts) { const node = make('button', 'qw-btn ' + opts.kind, label); node.addEventListener('click', click); return node; },
        panel(opts, ...children) { return wrap('nc-card', [make('h2', '', opts.title), ...children]); },
        row(...items) { return wrap('qw-btn-row', items); }, stack(...items) { return wrap('qw-btn-stack', items); },
        scene(opts) { return wrap('nc-hero', [make('h2', '', opts.title), make('p', '', opts.text || ''), ...(opts.body || [])]); },
        alert(opts) { return make('p', '', opts.title); }, netBanner(opts) { return make('p', '', opts.text); },
        roleBadge(opts) { return make('strong', '', opts.title); }, secret(value) { return make('p', '', value); },
        header() { return {node: make('header'), set() {}}; }, timer() { return {clock: make('span'), stop() {}}; },
        loadShell() {}, useWorld() {}, seats(rows) { return wrap('seats', rows.map(row => make('span', '', row.name))); },
    };
    const win = {NightCity: {kit, parseLaunch: () => null}, QW: {configure() {}, menu: {register() {}}, nav: options.nav || {push() {}, pop() {}}}, crypto: {randomUUID: () => `request-${++next}`, subtle: require('node:crypto').webcrypto.subtle} };
    const host = new Node('div');
    const listeners = new Map();
    const doc = {createElement: make, documentElement: new Node('html'), hidden: false,
        addEventListener(kind, listener, {signal} = {}) { listeners.set(kind, listener); signal?.addEventListener('abort', () => listeners.delete(kind)); }};
    runInNewContext(source, {window: win, document: doc, AbortController, setTimeout, clearTimeout, TextEncoder,
        setInterval(fn) { intervals.add(fn); return fn; }, clearInterval(fn) { intervals.delete(fn); }});
    const request = async (url, init) => {
        calls.push({url, body: init.body, expectedViewer: init.expectedViewer, signal: init.signal});
        if (requestHook) { const answer = await requestHook(url, init); if (answer !== undefined) return answer; }
        if (url === '/api/guest/rooms/room') return {id: 'room', title: 'Комната', role: 'owner'};
        if (url.includes('/current')) return {game_id: 'game'};
        if (url.includes('/view')) return view;
        if (url.includes('/history?')) return {items: [], next_cursor: null};
        if (url.endsWith('/intent')) return {kind: 'proposal', proposal: {proposal_id: 'saved-proposal', cost: 1}};
        if (url.endsWith('/confirm')) return {receipt: {accepted: true}};
        throw new Error('Unexpected request: ' + url);
    };
    const handle = win.NightCase.open({host, target: {roomId: 'room'}, bootstrap: {enabled: true, cases: [], viewer_account_id: VIEWER}, identity: 'guest', request, isCurrent: () => true, ...options});
    return {host, handle, calls, nodes, intervals, doc, listeners};
}

test('Case entry is the game root: no Mafia, no single-case hero, companies and invitation', async () => {
    let opened = 0;
    const fixture = controller(view(), url => url === '/api/guest/rooms' ? {items: []} : undefined,
        {target: null, bootstrap: {enabled: true, viewer_account_id: VIEWER, capabilities: {legacy_mafia: true}}, openLegacy: () => opened++});
    await settle();
    const textOf = node => [node.textContent || '', ...(node.children || []).map(textOf)].join(' ');
    const all = textOf(fixture.host);
    assert.ok(!find(fixture.host, node => node.tagName === 'button' && node.textContent === 'Классическая Мафия'));
    assert.doesNotMatch(all, /Хозяин исчез|Твои комнаты/);
    for (const label of ['Твои компании', 'Новая компания', 'Войти по приглашению']) assert.match(all, new RegExp(label));
    assert.equal(opened, 0);
    fixture.handle.close();
    assert.equal(fixture.intervals.size, 0);
});

test('a company is one step below the root: Back returns to the company list', async () => {
    const stack = [];
    const nav = {push(entry) { if (!stack.some(item => item.id === entry.id)) stack.push(entry); }, pop(id) { const i = stack.findIndex(item => item.id === id); if (i >= 0) stack.splice(i); }};
    const fixture = controller(view(), url => url === '/api/guest/rooms' ? {items: [{id: 'room', title: 'Пятничная компания'}]} : undefined, {nav});
    await settle();
    assert.deepEqual(stack.map(item => item.id), ['night-case-room']);
    assert.equal(stack[0].onBack(), true);
    await settle();
    assert.deepEqual(stack.map(item => item.id), []);
    assert.ok(fixture.calls.some(call => call.url === '/api/guest/rooms'));
    assert.ok(find(fixture.host, node => node.tagName === 'button' && node.textContent === 'Пятничная компания'));
    fixture.handle.close();
});

function view() {
    return {game_id: 'game', mode: 'night_case', server_now: '2026-11-16T10:00:00Z', runtime_status: 'running',
        public: {clock: {window_idx: 1, window_seq: 1, phase: 'investigation'}, locations: [{id: 'library', name: 'Библиотека', body: {text: 'Пахнет старой бумагой.'}}], players: [], npcs: [], board: []},
        self: {actor_seq: 0, status: 'active', location: 'library', character_id: 'lawyer', ap: 3, role: {title: 'Адвокат'}, goal: {body: {text: 'Личная цель'}, criteria: {text: 'Проверяемый критерий'}}, observations: [], secrets: [], unknown_private_payload: 'NEVER_RENDER_THIS'},
        menu: [{kind: 'choice', label: 'Осмотреть стол', quote: {kind: 'act', params: {action_id: 'inspect_desk'}, selection_id: 'server-selection', cost: 1}}]};
}

test('the live controller uses server actions, confirms a saved proposal and never renders unknown private fields', async () => {
    const fixture = controller(view()); await settle();
    assert.match(fixture.host.textContent, /Библиотека/);
    assert.doesNotMatch(fixture.host.textContent, /NEVER_RENDER_THIS/);
    const action = find(fixture.host, node => node.tagName === 'button' && node.textContent.includes('Осмотреть стол'));
    assert.ok(action); await action.click(); await settle();
    const proposal = fixture.calls.find(row => row.url.endsWith('/intent'));
    assert.equal(proposal.body.selection_id, 'server-selection');
    assert.equal(fixture.calls.filter(row => row.url.endsWith('/commands')).length, 0);
    const confirm = find(fixture.host, node => node.tagName === 'button' && node.textContent === 'Подтвердить');
    assert.ok(confirm); await confirm.click(); await settle();
    assert.deepEqual({...fixture.calls.find(row => row.url.endsWith('/confirm')).body}, {proposal_id: 'saved-proposal'});
    fixture.handle.close(); assert.equal(fixture.intervals.size, 0);
});

test('server text stays plain text, controller closes its polling and makes no audio or persistent cache', async () => {
    const data = view(); data.public.locations[0].body.text = '<img src=x onerror=steal()>Не HTML';
    const fixture = controller(data); await settle();
    assert.match(fixture.host.textContent, /<img src=x onerror=steal\(\)>Не HTML/);
    assert.equal(fixture.nodes.some(node => node.tagName === 'img'), false);
    fixture.handle.close(); assert.equal(fixture.intervals.size, 0);
    for (const forbidden of ['innerHTML', 'localStorage', 'sessionStorage', 'Audio(', '.music.', 'dangerouslySetInnerHTML']) assert.equal(source.includes(forbidden), false, forbidden);
});

test('only terminal own-seat DTO enables selection and scopes subsequent view and history reads', async () => {
    const data = view();
    const original = 'b20cf8f1-d53a-4cfe-84d7-a018e32cded9';
    data.history_seats = [{original_account_id: original, display_name: 'Первый игрок', role_title: 'Адвокат'},
        {original_account_id: 'second-own-seat', display_name: 'Второй игрок', role_title: 'Экономка'}];
    let fixture = controller(data); await settle();
    assert.equal(find(fixture.host, node => node.attrs?.['aria-label'] === 'Твои завершённые роли'), undefined);
    fixture.handle.close();
    data.runtime_status = 'finished'; data.menu = [];
    fixture = controller(data); await settle();
    await find(fixture.host, node => node.tagName === 'button' && node.textContent === 'Хроника').click(); await settle();
    const selection = find(fixture.host, node => node.attrs?.['aria-label'] === 'Твои завершённые роли');
    assert.ok(selection); selection.value = original;
    await selection.events.change(); await settle();
    assert.ok(fixture.calls.some(call => call.url === `/api/night-case/games/game/view?original_account_id=${original}`));
    const histories = fixture.calls.filter(call => call.url.includes('/history?')).slice(-2);
    assert.equal(histories.length, 2);
    assert.ok(histories.every(call => call.url.includes(`original_account_id=${original}`) && !call.url.includes('cursor=')));
    fixture.handle.close();
});

test('lost view access clears private canaries, aborts requests and stops the controller while 503 preserves the same viewer', async () => {
    for (const status of [401, 403, 404, 503]) {
        let armed = false;
        const data = view(); data.self.role.bio = {text: 'OLD_ACTOR_PRIVATE_CANARY'};
        const fixture = controller(data, async url => {
            if (armed && url.includes('/view')) { const error = new Error(); error.status = status; throw error; }
        });
        await settle();
        await find(fixture.host, node => node.tagName === 'button' && node.textContent === 'Досье').click();
        assert.match(fixture.host.textContent, /OLD_ACTOR_PRIVATE_CANARY/);
        armed = true; await fixture.handle.refresh(); await settle();
        if (status === 503) {
            assert.match(fixture.host.textContent, /OLD_ACTOR_PRIVATE_CANARY/);
            assert.equal(fixture.intervals.size, 1);
            assert.equal(fixture.calls.at(-1).signal.aborted, false);
        } else {
            assert.doesNotMatch(fixture.host.textContent, /OLD_ACTOR_PRIVATE_CANARY/);
            assert.match(fixture.host.textContent, /Открой дело заново/);
            assert.equal(fixture.intervals.size, 0);
            assert.ok(fixture.calls.every(call => call.signal.aborted));
            const count = fixture.calls.length; await fixture.handle.refresh();
            assert.equal(fixture.calls.length, count);
        }
        fixture.handle.close();
    }
});

test('profile change on a write clears pending actions without retry or repinning to a different viewer', async () => {
    const data = view(); data.public.locations[0].body.text = 'OLD_ACTOR_PRIVATE_CANARY';
    const fixture = controller(data, async url => {
        if (url.endsWith('/intent')) { const error = new Error(); error.status = 409; error.code = 'profile_changed'; throw error; }
    });
    await settle(); assert.match(fixture.host.textContent, /OLD_ACTOR_PRIVATE_CANARY/);
    await find(fixture.host, node => node.tagName === 'button' && node.textContent.includes('Осмотреть стол')).click(); await settle();
    assert.doesNotMatch(fixture.host.textContent, /OLD_ACTOR_PRIVATE_CANARY|Подтвердить|Повторить/);
    assert.equal(fixture.intervals.size, 0);
    assert.equal(fixture.calls.filter(call => call.url.endsWith('/intent')).length, 1);
    assert.ok(fixture.calls.every(call => call.expectedViewer === VIEWER));
    await fixture.handle.refresh(); assert.equal(fixture.calls.filter(call => call.url.endsWith('/intent')).length, 1);
    fixture.handle.close();
});

test('a late own-history response cannot restore private DOM after the profile fence closes', async () => {
    let release, armed = false;
    const fixture = controller(view(), async url => {
        if (url.includes('/history?')) return new Promise(resolve => { release = resolve; });
        if (armed && url.includes('/view')) { const error = new Error(); error.status = 409; error.code = 'profile_changed'; throw error; }
    });
    await settle();
    const pending = find(fixture.host, node => node.tagName === 'button' && node.textContent === 'Хроника').click(); await settle();
    armed = true; await fixture.handle.refresh();
    release({items: [{event_id: 'old-private', text: 'LATE_PRIVATE_CANARY'}], next_cursor: 'old-cursor'});
    await pending; await settle();
    assert.match(fixture.host.textContent, /Открой дело заново/);
    assert.doesNotMatch(fixture.host.textContent, /LATE_PRIVATE_CANARY/);
    assert.equal(fixture.intervals.size, 0);
    fixture.handle.close();
});

test('profile change is detected while an old private form keeps focus', async () => {
    let changed = false;
    const data = view(); data.self.role.bio = {text: 'OLD_ACTOR_PRIVATE_CANARY'};
    const fixture = controller(data, async url => {
        if (changed && (url.includes('/view') || url === '/api/night-case/bootstrap')) {
            const error = new Error(); error.status = 409; error.code = 'profile_changed'; throw error;
        }
    });
    await settle();
    await find(fixture.host, node => node.tagName === 'button' && node.textContent === 'Досье').click();
    assert.match(fixture.host.textContent, /OLD_ACTOR_PRIVATE_CANARY/);
    fixture.doc.activeElement = {tagName: 'INPUT'};
    changed = true;
    for (const poll of [...fixture.intervals]) poll();
    await settle();
    assert.doesNotMatch(fixture.host.textContent, /OLD_ACTOR_PRIVATE_CANARY/);
    assert.equal(fixture.intervals.size, 0);
    fixture.handle.close();
});

test('focused same-view probes preserve exact draft nodes on success and 503 but still detect ACL loss on resume', async () => {
    let status = 200;
    const fixture = controller(view(), async url => {
        if (url.includes('/view') && status !== 200) { const error = new Error(); error.status = status; throw error; }
    }, {bootstrap: {enabled: true, cases: [], viewer_account_id: VIEWER, capabilities: {free_intent: true}}});
    await settle();
    const input = find(fixture.host, node => node.attrs?.['aria-label'] === 'Что ты хочешь сделать?');
    input.value = 'UNSENT_PRIVATE_DRAFT'; fixture.doc.activeElement = {tagName: 'TEXTAREA'};
    for (const next of [200, 503]) {
        status = next;
        for (const poll of [...fixture.intervals]) poll(); await settle();
        assert.equal(find(fixture.host, node => node.attrs?.['aria-label'] === 'Что ты хочешь сделать?'), input);
        assert.equal(input.value, 'UNSENT_PRIVATE_DRAFT');
        assert.equal(fixture.intervals.size, 1);
    }
    status = 404;
    fixture.listeners.get('visibilitychange')(); await settle();
    assert.match(fixture.host.textContent, /Открой дело заново/);
    assert.equal(fixture.intervals.size, 0); assert.equal(fixture.listeners.size, 0);
    fixture.handle.close();
});

test('a displayed proposal remains intact on a safe probe and purges on profile change', async () => {
    let changed = false;
    const fixture = controller(view(), async url => {
        if (changed && url.includes('/view')) { const error = new Error(); error.status = 409; error.code = 'profile_changed'; throw error; }
    });
    await settle();
    await find(fixture.host, node => node.tagName === 'button' && node.textContent.includes('Осмотреть стол')).click(); await settle();
    const confirm = find(fixture.host, node => node.tagName === 'button' && node.textContent === 'Подтвердить');
    for (const poll of [...fixture.intervals]) poll(); await settle();
    assert.equal(find(fixture.host, node => node.tagName === 'button' && node.textContent === 'Подтвердить'), confirm);
    changed = true; for (const poll of [...fixture.intervals]) poll(); await settle();
    assert.match(fixture.host.textContent, /Открой дело заново/);
    assert.doesNotMatch(fixture.host.textContent, /Подтвердить/);
    assert.equal(fixture.intervals.size, 0);
    fixture.handle.close();
});

test('busy outbox does not suppress access probes and late write completion cannot revive a closed profile', async () => {
    for (const status of [409, 503]) {
        let release, pending = false;
        const fixture = controller(view(), async url => {
            if (url.endsWith('/intent')) { pending = true; return new Promise(resolve => { release = resolve; }); }
            if (pending && url.includes('/view')) { const error = new Error(); error.status = status; error.code = status === 409 ? 'profile_changed' : 'runtime_delayed'; throw error; }
        });
        await settle();
        const write = find(fixture.host, node => node.tagName === 'button' && node.textContent.includes('Осмотреть стол')).click(); await settle();
        for (const poll of [...fixture.intervals]) poll(); await settle();
        release({kind: 'proposal', proposal: {proposal_id: 'late-proposal', cost: 1}});
        await write; await settle();
        if (status === 409) {
            assert.match(fixture.host.textContent, /Открой дело заново/);
            assert.doesNotMatch(fixture.host.textContent, /Подтвердить/);
            assert.equal(fixture.intervals.size, 0);
        } else {
            assert.match(fixture.host.textContent, /Подтвердить/);
            assert.equal(fixture.intervals.size, 1);
        }
        fixture.handle.close();
    }
});

test('an overlapping normal view uses one cheap identity probe and rejects its late private completion after invalidation', async () => {
    let armed = false, release;
    const fixture = controller(view(), async url => {
        if (armed && url.includes('/view')) return new Promise(resolve => { release = resolve; });
        if (url === '/api/night-case/bootstrap') { const error = new Error(); error.status = 409; error.code = 'profile_changed'; throw error; }
    });
    await settle(); armed = true;
    const read = fixture.handle.refresh(); await settle();
    for (const poll of [...fixture.intervals]) poll(); await settle();
    const stale = view(); stale.public.locations[0].body.text = 'LATE_PRIVATE_CANARY'; release(stale);
    await read; await settle();
    assert.equal(fixture.calls.filter(call => call.url.includes('/view')).length, 2);
    assert.equal(fixture.calls.filter(call => call.url === '/api/night-case/bootstrap').length, 1);
    assert.doesNotMatch(fixture.host.textContent, /LATE_PRIVATE_CANARY/);
    assert.match(fixture.host.textContent, /Открой дело заново/);
    assert.equal(fixture.intervals.size, 0);
    fixture.handle.close();
});

const button = (host, label) => find(host, node => node.tagName === 'button' && node.textContent === label);
const choice = (kind, label, params = {}, cost = 0) => ({kind: 'choice', label, quote: {kind, params, selection_id: `sel-${kind}-${label}`, cost}});

test('zero-cost bookkeeping confirms without a cost dialog and the window bar follows every tab', async () => {
    const state = view();
    state.public.players = [{account_id: VIEWER, character_id: 'lawyer', name: 'Вера', status: 'active', finished_window: false},
        {account_id: 'other', character_id: 'maid', name: 'Нина', status: 'active', finished_window: false}];
    state.self.account_id = VIEWER;
    state.menu.push(choice('finish_window', 'Завершить окно'));
    let finished = false;
    const fixture = controller(state, url => {
        if (url.endsWith('/confirm')) { finished = true; return {receipt: {accepted: true}}; }
        if (url.includes('/view') && finished) return {...state, self: {...state.self, finished_window: true}, menu: state.menu.slice(0, 1)};
    });
    await settle();
    await button(fixture.host, 'Улики').click(); await settle();
    const finish = button(fixture.host, 'Завершить окно');
    assert.ok(finish, 'finish is offered outside the place tab');
    await finish.click(); await settle();
    assert.ok(fixture.calls.some(row => row.url.endsWith('/confirm')), 'confirmed without a second press');
    assert.equal(button(fixture.host, 'Подтвердить'), undefined);
    assert.match(fixture.host.textContent, /Ты завершил окно/);
    assert.match(fixture.host.textContent, /Ждём остальных/);
    fixture.handle.close();
});

test('the confirm dialog leaves at once and shows sending while the server answers', async () => {
    let release;
    const fixture = controller(view(), url => url.endsWith('/confirm') ? new Promise(resolve => { release = () => resolve({receipt: {accepted: true}}); }) : undefined);
    await settle();
    await find(fixture.host, node => node.tagName === 'button' && node.textContent.includes('Осмотреть стол')).click(); await settle();
    button(fixture.host, 'Подтвердить').click(); await settle();
    assert.match(fixture.host.textContent, /Отправляем…/);
    assert.equal(button(fixture.host, 'Подтвердить'), undefined, 'no second confirm while sending');
    release(); await settle();
    assert.doesNotMatch(fixture.host.textContent, /Отправляем…|Стоимость:/);
    fixture.handle.close();
});

test('publish buttons name the evidence, a second publication is one card and own chat lines are marked', async () => {
    const state = view();
    state.self.account_id = VIEWER;
    state.public.players = [{account_id: VIEWER, character_id: 'lawyer', name: 'Вера', status: 'active'}, {account_id: 'other', character_id: 'maid', name: 'Нина', status: 'active'}];
    const note = {observation_id: 'note', kind: 'proof', title: 'Записка у камина', body: {text: 'Текст записки'}};
    state.self.observations = [note, {observation_id: 'ash', kind: 'proof', title: 'Черновик', body: {text: 'лежит в библиотеке'}}];
    state.self.personal = {lost_observations: ['ash']};
    state.public.board = [{id: 'b1', owner_account_id: 'other', kind: 'proof', observation_id: 'note', observation: note}, {id: 'b2', owner_account_id: 'third', kind: 'proof', observation_id: 'note', observation: note}];
    state.menu.push(choice('pin', 'Опубликовать улику', {observation_id: 'note'}), choice('pin', 'Опубликовать улику', {observation_id: 'ash'}));
    const fixture = controller(state, url => url.includes('/history?stream=messages') ? {items: [{id: 'm1', sender_account_id: VIEWER, channel: 'square', text: 'Привет'}], next_cursor: null} : undefined);
    await settle();
    await button(fixture.host, 'Улики').click(); await settle();
    assert.ok(button(fixture.host, 'Подтвердить от себя: Записка у камина'));
    assert.ok(button(fixture.host, 'Опубликовать: Черновик'));
    assert.equal(button(fixture.host, 'Опубликовать улику'), undefined);
    assert.equal(fixture.host.textContent.split('Текст записки').length - 1, 2, 'one board card plus the own find');
    assert.match(fixture.host.textContent, /Оригинала больше нет/);
    await button(fixture.host, 'Беседа').click(); await settle();
    assert.match(fixture.host.textContent, /Вера \(ты\)/);
    fixture.handle.close();
});

test('after the final the place shows no actions and no free intent box without a host', async () => {
    const state = view();
    state.public.final = {code: 'solved', at: '2026-11-20T10:00:00Z'};
    state.self.postmortem = {ending: {text: 'Финал'}, goal_results: []};
    const fixture = controller(state); await settle();
    assert.doesNotMatch(fixture.host.textContent, /Осталось действий|Предложить действие|Осмотреть стол/);
    assert.match(fixture.host.textContent, /Дело завершено/);
    fixture.handle.close();
});

test('shared scenes come from the verified pack, the played finale only from its sealed address', async () => {
    const crypto = require('node:crypto');
    const sort = value => Array.isArray(value) ? value.map(sort) : value && typeof value === 'object' ? Object.fromEntries(Object.keys(value).sort().map(key => [key, sort(value[key])])) : value;
    const manifest = {schema: 'nc-assets/2', world: 'manor_lake', files: {'assets/scene_ev_blizzard.webp': 'a'.repeat(64)}, assets: {
        manor_scene_ev_blizzard: {url: 'assets/scene_ev_blizzard.webp', alt: 'Метель'},
    }};
    const sealedUrl = `/app/night/sealed/${'c'.repeat(64)}.webp`;
    const digest = crypto.createHash('sha256').update(JSON.stringify(sort(manifest))).digest('hex');
    const pointer = `/app/night/packs/${digest}/assets.json`;
    const state = view();
    Object.assign(state.public, {world: 'manor_lake', art: {manifest_sha256: digest, manifest_url: pointer}, clock: {window_idx: 2, window_seq: 1, phase: 'investigation'}, chronicle: [
        {event_id: 'evt_window', kind: 'window', window_idx: 2, payload: {window_idx: 2}},
        {event_id: 'evt_scene', kind: 'scene', window_idx: 2, payload: {content_event_id: 'ev_blizzard', body: {text: 'Метель отрезала лодочный сарай.'}}, art: {asset_id: 'manor_scene_ev_blizzard', alt: 'Метель над озером'}},
        {event_id: 'evt_secret', kind: 'observation_granted', window_idx: 2, payload: {observation_id: 'SECRET_CANARY'}},
    ]});
    assert.deepEqual(JSON.parse(JSON.stringify(api.playerView(state).public.scenes)), [{event_id: 'evt_scene', window_idx: 2, body: {text: 'Метель отрезала лодочный сарай.'}, art: {asset_id: 'manor_scene_ev_blizzard', alt: 'Метель над озером'}}]);
    const images = host => { const found = []; const walk = node => { if (node.tagName === 'img') found.push(node); for (const child of node.children || []) if (child && child.children) walk(child); }; walk(host); return found; };
    const hook = url => url === pointer ? manifest : undefined;
    const live = controller(state, hook); await settle();
    assert.match(live.host.textContent, /Сейчас в усадьбе/);
    assert.match(live.host.textContent, /Метель отрезала лодочный сарай/);
    assert.doesNotMatch(live.host.textContent, /SECRET_CANARY/);
    const scene = images(live.host).find(node => node.className === 'ncase-scene-art');
    assert.equal(scene.src, `/app/night/packs/${digest}/assets/scene_ev_blizzard.webp`);
    assert.equal(scene.alt, 'Метель над озером');
    live.handle.close();

    const over = view();
    Object.assign(over.public, {world: 'manor_lake', art: {manifest_sha256: digest, manifest_url: pointer}, final: {code: 'unresolved', at: '2026-11-20T10:00:00Z'}});
    over.self.postmortem = {ending: {text: 'Финал'}, variant_final_text: {text: 'Разгадка'}, variant_art: {asset_id: 'manor_scene_variant_b', alt: 'След по льду', url: sealedUrl}, goal_results: []};
    const done = controller(over, hook); await settle();
    const finale = images(done.host).find(node => node.className === 'ncase-scene-art');
    assert.equal(finale.src, sealedUrl);
    assert.equal(finale.alt, 'След по льду');
    done.handle.close();

    const unknown = view();
    Object.assign(unknown.public, {world: 'manor_lake', art: {manifest_sha256: digest, manifest_url: pointer}});
    unknown.public.final = {code: 'unresolved', at: '2026-11-20T10:00:00Z'};
    // No sealed address, a pack id or a foreign address: no finale picture.
    for (const art of [{asset_id: 'manor_scene_ev_blizzard', alt: 'Из пака'}, {asset_id: 'manor_scene_variant_c', alt: 'x', url: 'https://example.com/a.webp'},
                       {asset_id: 'manor_scene_variant_c', alt: 'x', url: `/app/night/packs/${digest}/assets/scene_ev_blizzard.webp`}]) {
        unknown.self.postmortem = {ending: {text: 'Финал'}, variant_art: art, goal_results: []};
        const missing = controller(unknown, hook); await settle();
        assert.equal(images(missing.host).filter(node => node.className === 'ncase-scene-art').length, 0);
        missing.handle.close();
    }
});
