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
    const win = {NightCity: {kit, parseLaunch: () => null}, QW: {configure() {}, menu: {register() {}}, nav: {push() {}, pop() {}}}, crypto: {randomUUID: () => `request-${++next}`} };
    const host = new Node('div');
    const listeners = new Map();
    const doc = {createElement: make, documentElement: new Node('html'), hidden: false,
        addEventListener(kind, listener, {signal} = {}) { listeners.set(kind, listener); signal?.addEventListener('abort', () => listeners.delete(kind)); }};
    runInNewContext(source, {window: win, document: doc, AbortController, setTimeout, clearTimeout,
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

test('Case default entry exposes classic mode only with the server capability and a live callback', async () => {
    let opened = 0;
    const fixture = controller(view(), url => url === '/api/guest/rooms' ? {items: []} : undefined,
        {target: null, bootstrap: {enabled: true, viewer_account_id: VIEWER, capabilities: {legacy_mafia: true}}, openLegacy: () => opened++});
    await settle();
    const classic = find(fixture.host, node => node.tagName === 'button' && node.textContent === 'Классическая Мафия');
    assert.ok(classic); await classic.click(); assert.equal(opened, 1);
    fixture.handle.close(); await classic.click(); assert.equal(opened, 1);
    assert.equal(fixture.intervals.size, 0);
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
    });
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
