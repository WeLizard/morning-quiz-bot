'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {join} = require('node:path');
const {runInNewContext} = require('node:vm');

// Exercise the owning app entry with both controllers present. No game rules,
// server state, Telegram SDK or audio are substituted into the routing decision.
function entry({authenticated = false, enabled = true} = {}) {
    const text = readFileSync(join(__dirname, '../../web/mini_client/app.js'), 'utf8');
    const start = text.indexOf('    async function openNightCity(');
    const end = text.indexOf('    // Chat page:', start);
    assert.ok(start >= 0 && end > start);
    const calls = [], requests = [], nodes = [];
    const content = {dataset: {}, replaceChildren(...children) { nodes.splice(0, nodes.length, ...children); }, append(...children) { nodes.push(...children); }};
    const node = (label, children = []) => ({label, children});
    const scope = {content, nav: {}, feedback: {}, generation: 0, tg: null, gm() {}, document: {documentElement: {classList: {add() {}}}},
        state: {authenticated, chats: [{chat_id: '-123', type: 'supergroup', title: 'Старый стол'}]},
        stopRoomClassic() {}, consumeNightLaunch() {}, shell() {}, navigate() {}, guestHome() {}, saveContrast() {},
        note(host, label) { host.append({label}); },
        el(tag, label, cls) { return {tag, label, cls, children: [], append(...children) { this.children.push(...children); }}; },
        button(label, click, kind) { return {label, click, kind}; },
        guestRequest: async url => { requests.push(url); return {enabled, viewer_account_id: 'viewer', capabilities: {legacy_mafia: true}, cases: []}; },
        window: {QuizPlay: {stop() {}}, NightCity: {close() {}, kit: {
            header: () => ({node: node('header'), set() {}}), loadShell() {}, useWorld() {},
            panel: (options, ...children) => node(options.title, children), note: text => node(text),
            stack: (...children) => node('', children), button: (label, click) => ({label, click}),
        }, open(options) { calls.push({mode: 'legacy_mafia', options}); }},
            NightCase: {close() { calls.push({closed: 'night_case'}); }, open(options) { calls.push({mode: 'night_case', options}); }}},
    };
    runInNewContext(text.slice(start, end) + '\nthis.open = openNightCity;', scope);
    return {...scope, calls, requests, nodes};
}
function buttons(nodes) { return nodes.flatMap(node => [node, ...buttons(node.children || [])]).filter(node => node.click); }

test('enabled Case preserves direct Telegram legacy table target without a Case bootstrap', async () => {
    const app = entry({authenticated: true});
    await app.open({chatId: '-123'});
    assert.equal(app.calls.length, 2);
    assert.equal(app.calls[0].closed, 'night_case');
    assert.equal(app.calls[1].mode, 'legacy_mafia');
    assert.equal(app.calls[1].options.target.chatId, '-123');
    assert.equal(app.requests.length, 0);
});

test('main entry defaults to Case and exposes an explicit classic entry callback', async () => {
    const app = entry(); await app.open();
    assert.equal(app.calls[0].mode, 'night_case');
    assert.equal(typeof app.calls[0].options.openLegacy, 'function');
    await app.calls[0].options.openLegacy();
    assert.equal(app.calls.at(-1).mode, 'legacy_mafia');
    assert.equal(app.calls.at(-1).options.target.mode, 'legacy_mafia');
    assert.equal(app.calls.at(-2).closed, 'night_case');
});

for (const target of [{roomId: 'old-room'}, {room: {id: 'old-room'}}, {code: 'old-invite'}]) {
    test('ambiguous Room target requires an explicit mode before either controller joins: ' + JSON.stringify(target), async () => {
        const app = entry(); await app.open(target);
        assert.ok(!app.calls.some(call => call.mode));
        const classic = buttons(app.nodes).find(node => node.label === 'Классическая Мафия');
        assert.ok(classic); await classic.click();
        assert.equal(app.calls.at(-1).mode, 'legacy_mafia');
        assert.equal(JSON.stringify(app.calls.at(-1).options.target), JSON.stringify({...target, mode: 'legacy_mafia'}));
    });
}

test('explicit Case room target bypasses the mode choice', async () => {
    const app = entry(); await app.open({roomId: 'case-room', mode: 'night_case'});
    assert.equal(app.calls[0].mode, 'night_case');
    assert.equal(app.calls[0].options.target.roomId, 'case-room');
});

test('short room deep link keeps short-code semantics when classic mode is chosen', async () => {
    const app = entry(); await app.open({code: 'ABCDEFGH'});
    const classic = buttons(app.nodes).find(node => node.label === 'Классическая Мафия');
    assert.ok(classic); await classic.click();
    assert.equal(app.calls.at(-1).mode, 'legacy_mafia');
    assert.equal(app.calls.at(-1).options.target.short, 'ABCDEFGH');
    assert.equal(app.calls.at(-1).options.target.code, undefined);
});

test('legacy normalization preserves long tokens and applies to explicit classic routing', async () => {
    const long = 'A'.repeat(43), app = entry();
    await app.open({code: long, mode: 'legacy_mafia'});
    assert.equal(app.calls.at(-1).options.target.code, long);
    assert.equal(app.calls.at(-1).options.target.short, undefined);
    for (const code of ['abcdefgh', 'ABCD-EFGH']) {
        await app.open({code, mode: 'legacy_mafia'});
        assert.equal(app.calls.at(-1).options.target.short, code);
        assert.equal(app.calls.at(-1).options.target.code, undefined);
        assert.equal(app.calls.at(-2).closed, 'night_case');
    }
});

test('Case choice retains eight-symbol code for its own short_code branch', async () => {
    const app = entry(); await app.open({code: 'ABCDEFGH'});
    assert.ok(!app.calls.some(call => call.mode));
    await buttons(app.nodes).find(node => node.label === 'Недельное расследование').click();
    assert.equal(app.calls.at(-1).mode, 'night_case');
    assert.equal(app.calls.at(-1).options.target.code, 'ABCDEFGH');
});
