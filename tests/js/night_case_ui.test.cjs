'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {runInNewContext} = require('node:vm');
const source = fs.readFileSync(path.resolve(__dirname, '../../web/mini_client/night-case-ui.js'), 'utf8');
const api = require('../../web/mini_client/night-case-ui.js');
const shellSource = fs.readFileSync(path.resolve(__dirname, '../../web/shell/qw-shell.js'), 'utf8');

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

const {Node, find, settle, shellPrefs, controller, VIEWER} = require('./night_case_harness.cjs');

test('shared shell timezone is account-scoped, formats personal dates and stays out of device preferences', () => {
    const shell = shellPrefs(), prefs = shell.prefs;
    prefs.applyAccount({timezone: 'Asia/Tokyo'});
    assert.equal(prefs.resolvedTimezone(), 'Asia/Tokyo');
    assert.equal(prefs.formatDate('2026-11-24T10:00:00Z', 'en', {hour: '2-digit', minute: '2-digit', hourCycle: 'h23'}), '19:00');
    shell.QW.configure({identity: 'guest'});
    prefs.applyAccount({timezone: 'America/Argentina/Buenos_Aires'});
    shell.QW.configure({identity: 'telegram'});
    assert.equal(prefs.resolvedTimezone(), prefs.deviceTimezone(), 'switching profiles clears the previous account zone');
    prefs.applyAccount({timezone: 'Asia/Tokyo'});
    prefs.setTheme('dark');
    assert.deepEqual(JSON.parse(shell.saved.value), {haptics: true, theme: 'dark', contrast: false});
});


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

test('new case defaults to the device IANA zone, filters all supplied zones and falls back to UTC', async () => {
    const zones = ['UTC', 'Europe/Berlin', 'Asia/Tokyo', 'America/New_York'];
    const bootstrap = {enabled: true, viewer_account_id: VIEWER, cases: [{id: 'manor_lake_missing', version: 1, title: 'Усадьба', timezones: zones}]};
    const deviceIntl = {DateTimeFormat: function (_locale, options = {}) { if (options.timeZone === 'Pacific/Unknown') throw new RangeError('bad IANA zone'); return {resolvedOptions: () => ({timeZone: 'Asia/Tokyo'})}; }};
    let fixture = controller(view(), url => url.endsWith('/night-case/current') ? {game_id: null} : undefined,
        {target: {roomId: 'room'}, bootstrap, Intl: deviceIntl});
    await settle();
    let zone = find(fixture.host, node => node.attrs?.['aria-label'] === 'Часовой пояс окон');
    let search = find(fixture.host, node => node.attrs?.['aria-label'] === 'Найти часовой пояс окон');
    assert.ok(zone); assert.ok(search); assert.equal(zone.value, 'Asia/Tokyo', JSON.stringify({device: fixture.zoneApi.deviceTimezone(), resolved: fixture.zoneApi.resolvedTimezone(), values: zone.children.map(option => option.value)}));
    assert.deepEqual(zone.children.map(option => option.value), ['America/New_York', 'Asia/Tokyo', 'Europe/Berlin', 'UTC']);
    find(fixture.host, node => node.attrs?.['aria-label'] === 'Дело').value = 'manor_lake_missing:1';
    search.value = 'America/New_York'; await search.events.input();
    assert.deepEqual(zone.children.map(option => option.value), ['Asia/Tokyo', 'America/New_York']);
    zone.value = 'America/New_York'; await zone.events.change();
    await find(fixture.host, node => node.tagName === 'button' && node.textContent === 'Создать стол').click(); await settle();
    const create = fixture.calls.find(call => call.url.endsWith('/lobby'));
    assert.ok(create, JSON.stringify(fixture.calls.map(call => call.url)));
    assert.equal(create.body.params.timezone, 'America/New_York');
    fixture.handle.close();

    fixture = controller(view(), url => url.endsWith('/night-case/current') ? {game_id: null} : undefined, {target: {roomId: 'room'}, bootstrap,
        Intl: {DateTimeFormat: function (_locale, options = {}) { if (options.timeZone === 'Pacific/Unknown') throw new RangeError('bad IANA zone'); return {resolvedOptions: () => ({timeZone: 'Pacific/Unknown'})}; }}});
    await settle();
    zone = find(fixture.host, node => node.attrs?.['aria-label'] === 'Часовой пояс окон');
    assert.equal(zone.value, 'UTC');
    fixture.handle.close();

    const savedBootstrap = {...bootstrap, account_timezone: 'America/New_York'};
    fixture = controller(view(), url => url.endsWith('/night-case/current') ? {game_id: null} : undefined,
        {target: {roomId: 'room'}, bootstrap: savedBootstrap, Intl: deviceIntl});
    await settle();
    zone = find(fixture.host, node => node.attrs?.['aria-label'] === 'Часовой пояс окон');
    assert.equal(zone.value, 'America/New_York', 'the stored account zone beats the device zone');
    fixture.handle.close();

    fixture = controller(view(), url => url.endsWith('/night-case/current') ? {game_id: null} : undefined,
        {target: {roomId: 'room'}, bootstrap: {...bootstrap, account_timezone: null}, Intl: deviceIntl});
    fixture.zoneApi.setTimezone('America/New_York');
    await settle();
    zone = find(fixture.host, node => node.attrs?.['aria-label'] === 'Часовой пояс окон');
    assert.equal(zone.value, 'Asia/Tokyo', 'explicit automatic mode uses this device, not a stale shell account zone');
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
    const mine = find(fixture.host, node => String(node.className).split(' ').includes('mine'));
    assert.ok(mine, 'own line is on the right');
    assert.match(mine.textContent, /ты/);
    assert.match(mine.textContent, /Привет/);
    fixture.handle.close();
});

test('after the final the place shows no actions and no free intent box without a host', async () => {
    const state = view();
    state.public.final = {code: 'solved', at: '2026-11-20T10:00:00Z'};
    state.self.postmortem = {ending: {text: 'Финал'}, goal_results: [{account_id: VIEWER, met: true}, {account_id: 'other', met: false}],
        reward_facts: [{account_id: VIEWER, faction_won: true}],
        cast: [{character_id: 'lawyer', account_id: VIEWER, controller: 'player', faction: 'investigation', part: null},
            {character_id: 'maid', account_id: 'other', controller: 'player', faction: 'shadow', part: 'accomplice'},
            {character_id: 'owner', account_id: null, controller: 'npc', faction: 'shadow', part: 'culprit'},
            {character_id: 'cook', account_id: 'third', controller: 'player', faction: 'shadow', part: null}]};
    state.public.players = [{account_id: VIEWER, character_id: 'lawyer', name: 'Вера', status: 'active'}, {account_id: 'other', character_id: 'maid', name: 'Нина', status: 'active'}];
    state.public.looks = {lawyer: {title: 'Адвокат'}, maid: {title: 'Горничная'}, owner: {title: 'Хозяин'}};
    state.self.account_id = VIEWER; // the server always sends the viewer's account with the own view
    const fixture = controller(state); await settle();
    assert.doesNotMatch(fixture.host.textContent, /Осталось действий|Предложить действие|Осмотреть стол/);
    const all = fixture.host.textContent;
    assert.match(all, /Дело закрыто/);
    assert.match(all, /Адвокат · цель выполнена/);
    assert.match(all, /Твоя сторона победила/);
    assert.match(all, /Кто был кем/);
    assert.match(all, /Горничная.*Нина.*сообщник Тени.*Тень.*не вышло/s);
    assert.match(all, /Хозяин.*ведёт игра.*виновный/s);
    assert.match(all, /на стороне Тени/, 'a shadow hero by the case, not by the variant');
    assert.ok(button(fixture.host, 'Новое дело'), 'the room owner can start the next case from the finale');
    await button(fixture.host, 'Улики').click(); await settle();
    assert.ok(button(fixture.host, 'К итогу'), 'other tabs point to the finale instead of repeating it');
    assert.equal(button(fixture.host, 'Новое дело'), undefined, 'the finale tab alone offers the next case');
    assert.doesNotMatch(fixture.host.textContent, /Кто был кем/);
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

/* AI narrator access (NIGHT_CASE_AI_ACCESS §7): the host's choice before the start. */
function lobbyView() {
    return {game_id: 'game', mode: 'night_case', server_now: '2026-11-16T10:00:00Z', runtime_status: 'lobby',
        lobby: {lobby_revision: 4, seats: [{seat: '1', name: 'Хозяин', ready: true}], self_seat: '1', can_start: true, case: {title: 'Дело'}, self: {address_form: 'n'}},
        public: {clock: {window_idx: 0, window_seq: 0}}, self: null};
}
const plain = value => JSON.parse(JSON.stringify(value));
const AI_BOOT = {enabled: true, cases: [], viewer_account_id: VIEWER, capabilities: {ai_narrator: true}};
const byText = (host, text) => find(host, node => node.tagName === 'button' && node.textContent.trim() === text);
const byLabel = (host, label) => find(host, node => ['input', 'select'].includes(node.tagName) && node.attrs['aria-label'] === label);

test('the host picks the narrator in the lobby: admin request is the default start option', async () => {
    const status = {status: 'authored', model_label: null, mode: 'authored', epoch: 2, can_configure: true, staged_credential_id: null};
    const fixture = controller(lobbyView(), url => url.endsWith('/ai') ? status : url.endsWith('/start') ? {receipt: {accepted: true}} : undefined, {bootstrap: AI_BOOT});
    await settle();
    const group = find(fixture.host, node => node.attrs?.['aria-label'] === 'Кто ведёт партию');
    assert.ok(group, 'narrator choice is shown to the host');
    assert.equal(byText(fixture.host, 'У админа').attrs['aria-pressed'], 'true');
    byText(fixture.host, 'Начать дело').click(); await settle();
    const start = fixture.calls.find(call => call.url.endsWith('/start'));
    assert.deepEqual(plain(start.body.params), {ai: {mode: 'admin', expected_epoch: 2, staged_credential_id: null}});
    fixture.handle.close();
});

test('own key: sent once to the byok route, cleared from the form, then the start names the staged key', async () => {
    let status = {status: 'authored', model_label: null, mode: 'authored', epoch: 0, can_configure: true, staged_credential_id: null};
    const presets = {items: [{id: 'openai', preset_version: 1, required_fields: [], optional_fields: ['project_id'], models: [], manual_model_id: true}], byok_ready: true, reason: null};
    const fixture = controller(lobbyView(), url => {
        if (url === '/api/night-case/ai/presets') return presets;
        if (url.endsWith('/ai/byok')) { status = {...status, mode: 'byok', credential_configured: true, staged_credential_id: 'staged-1', expires_at: '2026-11-16T11:00:00Z'}; return {result: {staged_credential_id: 'staged-1'}}; }
        if (url.endsWith('/ai')) return status;
        if (url.endsWith('/start')) return {receipt: {accepted: true}};
        return undefined;
    }, {bootstrap: AI_BOOT});
    await settle();
    byText(fixture.host, 'Свой ключ').click(); await settle();
    byText(fixture.host, 'Начать дело').click(); await settle();
    assert.equal(fixture.calls.filter(call => call.url.endsWith('/start')).length, 0, 'no start without a staged key');
    byLabel(fixture.host, 'Модель (ID у провайдера)').value = 'model-x';
    const secret = byLabel(fixture.host, 'Ключ API');
    assert.equal(secret.type, 'password'); assert.equal(secret.autocomplete, 'new-password');
    secret.value = 'BYOK_SECRET_CANARY';
    byText(fixture.host, 'Подключить ключ').click(); await settle();
    const sent = fixture.calls.filter(call => call.url.endsWith('/ai/byok'));
    assert.equal(sent.length, 1);
    assert.deepEqual(plain({...sent[0].body, client_request_id: 'id'}), {expected_epoch: 0, client_request_id: 'id', settings: {preset: 'openai', model_id: 'model-x'}, secret: 'BYOK_SECRET_CANARY'});
    assert.equal(secret.value, '', 'the key does not stay in the form');
    byText(fixture.host, 'Начать дело').click(); await settle();
    const start = fixture.calls.find(call => call.url.endsWith('/start'));
    assert.deepEqual(plain(start.body.params), {ai: {mode: 'byok', expected_epoch: 0, staged_credential_id: 'staged-1'}});
    assert.equal(fixture.calls.filter(call => JSON.stringify(call.body || '').includes('BYOK_SECRET_CANARY')).length, 1);
    fixture.handle.close();
});

test('without the narrator capability the lobby has no AI choice and the start carries no options', async () => {
    const fixture = controller(lobbyView(), url => url.endsWith('/start') ? {receipt: {accepted: true}} : undefined);
    await settle();
    assert.equal(find(fixture.host, node => node.attrs?.['aria-label'] === 'Кто ведёт партию'), undefined);
    byText(fixture.host, 'Начать дело').click(); await settle();
    assert.deepEqual(plain(fixture.calls.find(call => call.url.endsWith('/start')).body.params), {});
    assert.equal(fixture.calls.some(call => call.url.includes('/ai')), false);
    fixture.handle.close();
});

test('a running game shows the narrator status to everyone, controls only to the starter', async () => {
    const running = view();
    const fixture = controller(running, url => url.endsWith('/ai') ? {status: 'pending', model_label: null} : undefined, {bootstrap: AI_BOOT});
    await settle();
    assert.match(fixture.host.textContent, /Ведущий: авторский текст, ждём ответа администратора/);
    fixture.handle.close();
});

const pick = (kind, label, params, id) => ({kind: 'choice', label, quote: {kind, params, selection_id: id, cost: 0}});
function removedView() {
    const state = view();
    state.self.account_id = VIEWER; state.self.status = 'ghost'; state.self.ap = 0;
    state.public.players = [{account_id: VIEWER, character_id: 'lawyer', name: 'Вера', status: 'ghost'},
        {account_id: 'other', character_id: 'maid', name: 'Нина', status: 'active'}, {account_id: 'third', character_id: 'cook', name: 'Олег', status: 'active'}];
    state.self.observations = [{observation_id: 'ledger', kind: 'proof', title: 'Книга ключей', body: {text: 'Запись о ключе'}}];
    state.public.chronicle = [{event_id: 'h1', kind: 'hearing', window_idx: 4, payload: {hearing_id: 'h', stage: 'closed', resolution: 'wrong', suspect: 'lawyer', resolve_window: 4}}];
    state.public.modules = {ghost_testimony: {questions: [{question_event_id: 'q1', asker_character: 'maid', ghost_character: 'lawyer', text: 'Ключ был у дворецкого?', window_idx: 4, answer_by: 5, answer: null, status: 'open'}]}};
    state.menu = [pick('ghost_share', 'На доску', {observation_id: 'ledger'}, 'share'),
        pick('ghost_whisper', 'Передать лично', {observation_id: 'ledger', recipient: 'maid'}, 'to-maid'),
        pick('ghost_whisper', 'Передать лично', {observation_id: 'ledger', recipient: 'cook'}, 'to-cook'),
        pick('testimony_answer', 'Ответить «да»', {question_event_id: 'q1', answer: 'yes'}, 'q1-yes'),
        pick('testimony_answer', 'Ответить «нет»', {question_event_id: 'q1', answer: 'no'}, 'q1-no')];
    return state;
}

test('a removed player has one action per window: a memory to the board or to one chosen player, or a yes/no answer', async () => {
    const fixture = controller(removedView()); await settle();
    const all = fixture.host.textContent;
    assert.match(all, /Ты отстранён от расследования/);
    assert.doesNotMatch(all, /[Пп]ризрак/, 'a case without mysticism never speaks of ghosts');
    assert.doesNotMatch(all, /Осталось действий/, 'a removed player has one action, not action points');
    assert.match(all, /Ключ был у дворецкого\?/);
    assert.match(all, /Слушание в окне 4: стол поддержал обвинение, но ты не виновен/, 'the removed player sees why');
    assert.match(all, /Площадь ты по-прежнему читаешь/, 'the square stays readable');
    assert.equal(find(fixture.host, node => node.tagName === 'button' && node.textContent.includes('Осмотреть стол')), undefined);
    const to = byLabel(fixture.host, 'Кому передать лично'); to.value = 'cook'; to.events.change();
    await button(fixture.host, 'Улики').click(); await settle();
    await button(fixture.host, 'Место').click(); await settle();
    assert.notEqual(byLabel(fixture.host, 'Кому передать лично'), to, 'the screen was rebuilt');
    assert.equal(byLabel(fixture.host, 'Кому передать лично').value, 'cook', 'the chosen recipient survives a re-render');
    await button(fixture.host, 'Передать лично').click(); await settle();
    assert.equal(fixture.calls.find(row => row.url.endsWith('/intent')).body.selection_id, 'to-cook');
    assert.match(fixture.host.textContent, /единственное действие в этом окне/);
    assert.doesNotMatch(fixture.host.textContent, /Стоимость:/);
    await button(fixture.host, 'Подтвердить').click(); await settle();
    await button(fixture.host, 'Да').click(); await settle();
    assert.equal(fixture.calls.filter(row => row.url.endsWith('/intent')).at(-1).body.selection_id, 'q1-yes');
    fixture.handle.close();
});

test('a living player asks a removed one from the board for 1 action; a case with mysticism speaks of ghosts and signs', async () => {
    const state = removedView();
    state.self = {...state.self, account_id: 'other', character_id: 'maid', status: 'active', ap: 2, observations: []};
    state.menu = [{kind: 'form', entry_id: 'testimony_ask', label: 'testimony_ask', command_kind: 'testimony_ask', cost: 1, subject_ids: ['lawyer'], board_ids: [], hearing_id: null}];
    state.public.modules.ghost_visions = {signs: [{event_id: 'e9', sign_id: 'cold', character_id: 'lawyer', location: 'library', window_idx: 4, body: {text: 'В библиотеке гаснет свеча.'}}]};
    const fixture = controller(state, url => url.endsWith('/quote') ? {} : url.endsWith('/commands') ? {receipt: {accepted: true}} : undefined);
    await settle();
    await button(fixture.host, 'Улики').click(); await settle();
    const all = fixture.host.textContent;
    assert.match(all, /Вопросы призракам/);
    assert.match(all, /Библиотека: В библиотеке гаснет свеча\./);
    assert.match(all, /слова, а не доказательство/);
    find(fixture.host, node => node.tagName === 'textarea' && node.attrs['aria-label'] === 'Вопрос, на который можно ответить «да» или «нет»').value = '  Вы видели свет в окне?  ';
    await button(fixture.host, 'Спросить · 1 ОД').click(); await settle();
    const sent = fixture.calls.find(row => row.url.endsWith('/commands'));
    assert.equal(sent.body.kind, 'testimony_ask');
    assert.deepEqual({...sent.body.params}, {ghost: 'lawyer', text: 'Вы видели свет в окне?'});
    await button(fixture.host, 'Беседа').click(); await settle();
    assert.match(fixture.host.textContent, /Призраки разговаривают отдельно/);
    fixture.handle.close();
});

/* Live run of 2026-11-21 against the mockups: findings 1, 8 and 9. */
test('a frozen table offers «Я здесь» once, in its own notice', async () => {
    const state = view();
    state.public.clock.phase = 'frozen';
    state.menu.push({kind: 'choice', label: 'Я здесь', quote: {kind: 'seen', params: {}, selection_id: 'seen-selection', cost: 0}});
    const fixture = controller(state); await settle();
    assert.match(fixture.host.textContent, /Стол ждёт возвращения/);
    assert.equal((fixture.host.textContent.match(/Я здесь/g) || []).length, 1);
    fixture.handle.close();
});

test('an unconfirmed write shows one banner with retry and no second error alert', async () => {
    const fixture = controller(view(), url => { if (url.endsWith('/intent')) { const error = new Error('offline'); error.network = true; throw error; } });
    await settle();
    await byText(fixture.host, 'Осмотреть стол').click(); await settle();
    assert.match(fixture.host.textContent, /Запрос ещё не подтверждён сервером/);
    assert.doesNotMatch(fixture.host.textContent, /Нет связи/);
    fixture.handle.close();
});

test('a lobby seat stored as a service id is shown as a numbered player', async () => {
    const state = lobbyView();
    state.lobby.seats.push({seat: 'seat02', name: 'seat02', ready: false});
    const fixture = controller(state, undefined, {bootstrap: AI_BOOT}); await settle();
    assert.match(fixture.host.textContent, /Игрок 2/);
    assert.doesNotMatch(fixture.host.textContent, /seat02/);
    fixture.handle.close();
});

test('people nearby come by portrait with the player plate; a hero removed by the table is darkened', async () => {
    const crypto = require('node:crypto');
    const sort = value => Array.isArray(value) ? value.map(sort) : value && typeof value === 'object' ? Object.fromEntries(Object.keys(value).sort().map(key => [key, sort(value[key])])) : value;
    const manifest = {schema: 'nc-assets/2', world: 'manor_lake', files: {'assets/character_cook.webp': 'a'.repeat(64), 'assets/character_maid.webp': 'b'.repeat(64)}, assets: {
        manor_char_cook: {url: 'assets/character_cook.webp', alt: 'Повар'}, manor_char_maid: {url: 'assets/character_maid.webp', alt: 'Горничная'}}};
    const digest = crypto.createHash('sha256').update(JSON.stringify(sort(manifest))).digest('hex'), pointer = `/app/night/packs/${digest}/assets.json`;
    const state = view();
    Object.assign(state.public, {world: 'manor_lake', art: {manifest_sha256: digest, manifest_url: pointer},
        players: [{account_id: 'other', character_id: 'maid', name: 'Нина', status: 'ghost'}],
        looks: {cook: {id: 'base', title: 'Повар', art: {asset_id: 'manor_char_cook'}}, maid: {id: 'base', title: 'Горничная', art: {asset_id: 'manor_char_maid'}}}});
    state.self.nearby = [{character_id: 'cook', name: 'Пётр Ильич', controller: 'npc'}, {character_id: 'maid', name: 'Нина', controller: 'player'}];
    const live = controller(state, url => url === pointer ? manifest : undefined); await settle();
    const people = find(live.host, node => node.className === 'ncase-people');
    assert.ok(people, 'the people nearby are a list of portraits');
    assert.match(people.textContent, /Повар/); assert.match(people.textContent, /ведёт игра/); assert.match(people.textContent, /Нина/);
    const darkened = find(people, node => /ncase-out/.test(node.className));
    assert.equal(darkened?.children[0]?.src, `/app/night/packs/${digest}/assets/character_maid.webp`);
    live.handle.close();
});

/* MQB-012 screens 12–13: hearings by portrait; claims are shown but cannot be cited. */
test('a hearing shows accuser and suspect by portrait; the final vote picks a hero tile and cites proofs only', async () => {
    const state = view();
    state.public.players = [{account_id: VIEWER, character_id: 'lawyer', name: 'Вера', status: 'active'}, {account_id: 'other', character_id: 'maid', name: 'Нина', status: 'active'}];
    state.public.looks = {lawyer: {title: 'Адвокат'}, maid: {title: 'Горничная'}, butler: {title: 'Дворецкий'}};
    state.public.board = [{id: 'b1', owner_account_id: 'other', kind: 'proof', observation_id: 'note', observation: {observation_id: 'note', kind: 'proof', title: 'Журнал ключей', body: {text: 'Выдачи ключей'}}},
        {id: 'b2', owner_account_id: VIEWER, kind: 'claim', observation_id: null, text: 'Хозяин ушёл по льду'}];
    state.public.hearing = {id: 'h1', accuser: 'other', suspect: 'butler', resolve_window: 4, initial_citations: ['b1']};
    state.public.clock.phase = 'final_hearing';
    state.menu = [{kind: 'form', entry_id: 'vote', label: 'vote', command_kind: 'vote', cost: 0, subject_ids: [], board_ids: ['b1', 'b2'], hearing_id: 'h1'},
        {kind: 'form', entry_id: 'final_vote', label: 'final_vote', command_kind: 'final_vote', cost: 0, subject_ids: ['maid', 'butler'], board_ids: ['b1', 'b2'], hearing_id: null}];
    const fixture = controller(state, url => url.endsWith('/quote') ? {} : url.endsWith('/commands') ? {receipt: {accepted: true}} : undefined);
    await settle();
    await button(fixture.host, 'Улики').click(); await settle();
    const accuse = find(fixture.host, node => String(node.className).split(' ').includes('ncase-accuse'));
    assert.ok(accuse, 'who accuses whom');
    assert.match(accuse.textContent, /Горничная.*Нина.*обвиняет.*Дворецкий.*ведёт игра.*под подозрением/s);
    const cites = (host) => { const rows = []; (function walk(node) { if (String(node.className).split(' ').includes('ncase-cite')) rows.push(node); node.children?.forEach?.(child => child.children && walk(child)); })(host); return rows; };
    assert.equal(cites(fixture.host).filter(row => row.disabled).length, 2, 'the claim row is disabled in both forms');
    const tile = find(fixture.host, node => node.attrs?.['aria-label'] === 'Выбрать: Дворецкий');
    assert.ok(tile); tile.click();
    assert.equal(tile.attrs['aria-pressed'], 'true');
    const proofRows = cites(fixture.host).filter(row => !row.disabled);
    proofRows[proofRows.length - 1].click();
    await button(fixture.host, 'Отдать голос').click(); await settle();
    const sent = fixture.calls.find(row => row.url.endsWith('/commands'));
    assert.equal(sent.body.kind, 'final_vote');
    assert.deepEqual({...sent.body.params, citations: [...sent.body.params.citations]}, {citations: ['b1'], suspect: 'butler'});
    fixture.handle.close();
});

test('the accused sees the charge and can only object (finding 3)', async () => {
    const state = view();
    state.public.players = [{account_id: VIEWER, character_id: 'lawyer', name: 'Вера', status: 'active'}, {account_id: 'other', character_id: 'maid', name: 'Нина', status: 'active'}];
    state.public.hearing = {id: 'h1', accuser: 'other', suspect: 'lawyer', resolve_window: 4, initial_citations: []};
    state.menu = [{kind: 'form', entry_id: 'vote', label: 'vote', command_kind: 'vote', cost: 0, subject_ids: [], board_ids: [], hearing_id: 'h1'}];
    const fixture = controller(state); await settle();
    await button(fixture.host, 'Улики').click(); await settle();
    assert.match(fixture.host.textContent, /Обвиняют тебя/);
    assert.ok(button(fixture.host, 'Возражаю'));
    assert.equal(button(fixture.host, 'Поддержать'), undefined);
    fixture.handle.close();
});

test('the chronicle declines by the character (owner B1): the hero in the case form, the own verb by the own hero', async () => {
    const state = view();
    state.self.account_id = VIEWER;
    state.self.role = {title: 'Экономка', gender: 'f'};
    state.public.players = [{account_id: VIEWER, character_id: 'housekeeper', name: 'Петя', status: 'active'}];
    state.public.looks = {housekeeper: {title: 'Экономка', gender: 'f', title_forms: {acc: 'Экономку', dat: 'Экономке', gen: 'Экономки'}},
        butler: {title: 'Дворецкий', gender: 'm', title_forms: {acc: 'Дворецкого', dat: 'Дворецкому', gen: 'Дворецкого'}}};
    const items = [{event_id: 'e1', kind: 'hearing', window_idx: 3, payload: {stage: 'opened', suspect: 'housekeeper'}},
        {event_id: 'e2', kind: 'ghost_whispered', window_idx: 4, payload: {recipient_character: 'butler', observation_id: 'x'}}];
    const fixture = controller(state, url => url.includes('/history?') ? {items, next_cursor: null} : undefined); await settle();
    await button(fixture.host, 'Хроника').click(); await settle();
    const all = fixture.host.textContent;
    assert.match(all, /Открыто слушание: обвиняют Экономку\./);
    assert.match(all, /Ты передала Дворецкому лично/);
    assert.doesNotMatch(all, /Петя\./, 'the player name is not used as the hero');
    fixture.handle.close();
});

test('the ⚙ menu has glyphs and switches music through the account preference, not the player (mockup 19)', async () => {
    const fixture = controller(view(), url => url.startsWith('/api/account/game-preferences') ? {account_id: VIEWER, game_preferences: {music: false}} : undefined);
    let on = true;
    fixture.kit.musicOn = () => on;
    await settle();
    const ids = fixture.menu.items.map(item => item.id);
    assert.ok(ids.includes('night-case-rules') && ids.includes('night-case-contrast') && ids.includes('night-case-refresh'));
    assert.ok(fixture.menu.items.every(item => item.icon), 'every game item has a glyph');
    const music = fixture.menu.items.find(item => item.id === 'night-case-music');
    assert.ok(music, 'the music switch is in the menu once the kit can say whether music is on');
    assert.equal(music.toggle(), true);
    await music.onSelect(); await settle();
    const saved = fixture.calls.find(row => row.url.startsWith('/api/account/game-preferences'));
    assert.deepEqual(JSON.parse(JSON.stringify(saved.body)), {account_id: VIEWER, game_preferences: {music: false}});
    assert.equal(fixture.zoneApi.get().gamePreferences.music, false);
    fixture.handle.close();
});

/* Mockup screens 4–5: the free-seating lobby draws seats as hero portraits and a hero with several characters opens its own pick. */
function openLobbyFixture() {
    const crypto = require('node:crypto');
    const sort = value => Array.isArray(value) ? value.map(sort) : value && typeof value === 'object' ? Object.fromEntries(Object.keys(value).sort().map(key => [key, sort(value[key])])) : value;
    const ids = ['housekeeper', 'housekeeper__f62', 'investigator', 'host'];
    const manifest = {schema: 'nc-assets/2', world: 'manor_lake', files: Object.fromEntries(ids.map((name, i) => [`assets/character_${name}.webp`, String(i + 1).repeat(64)])),
        assets: Object.fromEntries(ids.map(name => [`manor_char_${name}`, {url: `assets/character_${name}.webp`, alt: name}]))};
    const digest = crypto.createHash('sha256').update(JSON.stringify(sort(manifest))).digest('hex'), pointer = `/app/night/packs/${digest}/assets.json`;
    const state = {game_id: 'game', mode: 'night_case', server_now: '2026-11-26T10:00:00Z', runtime_status: 'ok',
        public: {world: 'manor_lake', style_pack: null, art: {manifest_sha256: digest, manifest_url: pointer}},
        lobby: {lobby_revision: 7, seating: 'open', case: {title: 'Усадьба'}, timezone: 'Europe/Moscow', windows: {slots: ['09:00', '19:00'], count: 14},
            allowed_counts: [3, 4, 5, 6, 7, 8, 9, 10, 11, 12], can_start: false, self_seat: '1', self: {name: 'Вера', address_form: 'f', ready: false},
            seats: [{seat: '1', name: 'Вера', ready: false, character_id: null, look_id: null}, {seat: '2', name: 'Нина', ready: true, character_id: 'investigator', look_id: null}],
            heroes: [{id: 'housekeeper', title: 'Экономка', multiple: true, looks: [
                {id: 'base', gender: 'f', age: 47, title: 'Экономка', name: 'Агата Карловна Линд', art: {asset_id: 'manor_char_housekeeper', alt: 'Портрет: Экономка'}, public: {text: 'Ключи от всего дома носит на поясе.'}},
                {id: 'f62', gender: 'f', age: 62, title: 'Экономка', name: 'Марфа Савельевна Тюрина', art: {asset_id: 'manor_char_housekeeper__f62', alt: 'Портрет: Экономка'}}]},
                {id: 'investigator', title: 'Следователь', multiple: false, looks: [{id: 'base', gender: 'm', age: 40, title: 'Следователь', name: 'Карл Ээрола', art: {asset_id: 'manor_char_investigator'}}]}],
            npc_heroes: [{id: 'host', title: 'Хозяин усадьбы', art: {asset_id: 'manor_char_host'}}, {id: 'hunter', title: 'Охотник', art: null}]}};
    return {state, manifest, pointer};
}
const nodesOf = (host, test) => { const out = []; const walk = node => { if (node instanceof Node) { if (test(node)) out.push(node); node.children.forEach(walk); } }; walk(host); return out; };
const heroCards = host => nodesOf(host, node => /^ncase-hero\b/.test(node.className));

test('the lobby seats are hero portraits with the player plate, the ready bar and who the game always plays (mockup 4)', async () => {
    const {state, manifest, pointer} = openLobbyFixture();
    const fixture = controller(state, url => url === pointer ? manifest : undefined); await settle();
    const text = fixture.host.textContent;
    assert.match(text, /Сбор открыт · за столом 2/);
    assert.match(text, /Готовы 1 из 2/);
    assert.equal(find(fixture.host, node => node.className === 'nc-track')?.dataset.ready, '1');
    const [housekeeper, investigator] = heroCards(fixture.host);
    assert.match(housekeeper.textContent, /Экономка/);
    assert.match(housekeeper.textContent, /47 или 62 года · 2 персонажа/);
    assert.match(find(housekeeper, node => node.tagName === 'img').src, /character_housekeeper\.webp$/);
    assert.equal(housekeeper.disabled, false);
    // A seat another player took carries their plate and is closed.
    assert.equal(investigator.className, 'ncase-hero taken');
    assert.equal(investigator.disabled, true);
    assert.match(find(investigator, node => node.className === 'ncase-plate').textContent, /Нина/);
    assert.match(investigator.textContent, /Карл Ээрола, 40 лет/);
    assert.match(text, /Любое свободное место/);
    assert.match(text, /Здесь: ты\./);
    assert.match(text, /Этих двоих всегда ведёт игра: хозяин усадьбы и охотник\./);
    assert.match(text, /Утро в 09:00, вечер в 19:00 по поясу Europe\/Moscow/);
    assert.match(text, /Неделя — 14 окон/);
    const dock = find(fixture.host, node => node.className === 'nc-dock');
    assert.match(dock.textContent, /Ты на любом свободном месте · ещё не готова · ты хозяин стола/);
    assert.ok(find(dock, node => node.tagName === 'button' && node.textContent === 'Начать дело'));
    assert.doesNotMatch(text, /облик/i);
    fixture.handle.close();
});

test('a hero with two characters opens the pick: two portraits, «Любой из двух» and «Сесть: имя» (mockup 5)', async () => {
    const {state, manifest, pointer} = openLobbyFixture(), stack = [];
    const nav = {push(entry) { stack.push(entry); }, pop(id) { const at = stack.findIndex(entry => entry.id === id); if (at >= 0) stack.splice(at, 1); }};
    const fixture = controller(state, url => url === pointer ? manifest : url.endsWith('/seat') ? {receipt: {accepted: true}} : undefined, {nav}); await settle();
    await heroCards(fixture.host)[0].click(); await settle();
    const text = fixture.host.textContent;
    assert.match(text, /Место «Экономка» · 2 персонажа/);
    assert.match(text, /Кого ты играешь\?/);
    assert.match(text, /Ключи от всего дома носит на поясе\./);
    assert.ok(stack.some(entry => entry.id === 'night-case-pick'));
    const looks = nodesOf(fixture.host, node => node.className === 'ncase-look');
    assert.equal(looks.length, 2);
    assert.match(looks[1].textContent, /Марфа Савельевна Тюрина, 62/);
    assert.match(looks[1].textContent, /она · экономка/);
    assert.equal(looks[0].attrs['aria-pressed'], 'true');
    assert.ok(find(fixture.host, node => node.tagName === 'button' && node.textContent === 'Любой из двух'));
    await looks[1].click(); await settle();
    const sit = find(fixture.host, node => node.tagName === 'button' && node.textContent === 'Сесть: Марфа Савельевна Тюрина');
    assert.ok(sit);
    await sit.click(); await settle();
    const seat = fixture.calls.find(call => call.url.endsWith('/seat'));
    assert.deepEqual(JSON.parse(JSON.stringify(seat.body.params)), {character_id: 'housekeeper', look_id: 'f62'});
    assert.equal(seat.body.expected_lobby_revision, 7);
    assert.ok(!stack.some(entry => entry.id === 'night-case-pick'));
    assert.doesNotMatch(text, /облик/i);
    fixture.handle.close();
});

test('the ready toggle in the dock sends the name and address typed in the lobby', async () => {
    const {state, manifest, pointer} = openLobbyFixture();
    const fixture = controller(state, url => url === pointer ? manifest : url.endsWith('/ready') ? {receipt: {accepted: true}} : undefined); await settle();
    find(fixture.host, node => node.attrs?.['aria-label'] === 'Имя в этой партии').value = 'Вера К.';
    await find(fixture.host, node => node.tagName === 'button' && node.textContent === 'Я готова').click(); await settle();
    const ready = fixture.calls.find(call => call.url.endsWith('/ready'));
    assert.deepEqual(JSON.parse(JSON.stringify(ready.body.params)), {name: 'Вера К.', address_form: 'f', ready: true});
    fixture.handle.close();
});

test('the lobby talk shows the hero and the player plate, sends a line and keeps the draft for players only (mockup 4)', async () => {
    const {state, manifest, pointer} = openLobbyFixture();
    state.lobby.chat = [
        {id: 'm1', name: 'Нина', character_id: 'investigator', look_id: null, text: 'Беру следователя. Стартуем вечером?', at: '2026-11-26T09:58:00Z', mine: false},
        {id: 'm2', name: 'Вера', character_id: null, look_id: null, text: 'Да, в семь.', at: '2026-11-26T09:59:00Z', mine: true}];
    const fixture = controller(state, url => url === pointer ? manifest : url.endsWith('/lobby-chat') ? {message: {id: 'm3'}, chat: []} : undefined); await settle();
    const card = find(fixture.host, node => node.className === 'nc-card' && /Обсуждение/.test(node.textContent));
    assert.ok(card);
    const lines = nodesOf(card, node => /^nc-msg\b/.test(node.className));
    assert.equal(lines.length, 2);
    assert.match(lines[0].textContent, /Следователь\s+Нина\s+Беру следователя/);
    assert.match(find(lines[0], node => node.tagName === 'img').src, /character_investigator\.webp$/);
    assert.equal(lines[1].className, 'nc-msg mine');
    assert.match(lines[1].textContent, /Любое место\s+ты\s+Да, в семь\./);
    const input = find(card, node => node.attrs?.['aria-label'] === 'Сообщение в обсуждении');
    input.value = '  Я за экономку  '; await input.events.input();
    await input.events.keydown({key: 'Enter'}); await settle();
    const sent = fixture.calls.find(call => call.url.endsWith('/lobby-chat'));
    assert.ok(sent, 'Enter sends the line');
    assert.equal(sent.body.text, 'Я за экономку');
    assert.match(sent.body.command_id, /^request-/);
    assert.equal(sent.url, '/api/night-case/games/game/lobby-chat');
    fixture.handle.close();
});

test('a company member who has not joined reads the lobby talk but has no field to write', async () => {
    const {state, manifest, pointer} = openLobbyFixture();
    state.lobby.self_seat = null; state.lobby.self = null;
    state.lobby.chat = [{id: 'm1', name: 'Нина', character_id: 'investigator', look_id: null, text: 'Ждём ещё одного.', at: '2026-11-26T09:58:00Z', mine: false}];
    const fixture = controller(state, url => url === pointer ? manifest : undefined); await settle();
    assert.match(fixture.host.textContent, /Ждём ещё одного\./);
    assert.match(fixture.host.textContent, /Писать могут игроки за столом\./);
    assert.equal(find(fixture.host, node => node.attrs?.['aria-label'] === 'Сообщение в обсуждении'), undefined);
    fixture.handle.close();
});
