// Settings workflow with a DOM double; no browser, Telegram or external calls.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {join} = require('node:path');
const {runInNewContext} = require('node:vm');

class Element {
    constructor(tag) { this.tag = tag; this.children = []; this.events = {}; this.attrs = {}; this.text = ''; this.value = ''; }
    set textContent(value) { this.text = String(value); this.children = []; }
    get textContent() { return this.text + this.children.map(n => n.textContent).join(''); }
    set innerHTML(value) { throw new Error('Unsafe HTML assignment'); }
    get isConnected() { return this.root || Boolean(this.parent?.isConnected); }
    append(...nodes) { nodes.forEach(n => { n.parent = this; this.children.push(n); }); }
    appendChild(node) { this.append(node); return node; }
    prepend(...nodes) { nodes.forEach(n => { n.parent = this; }); this.children.unshift(...nodes); }
    replaceChildren(...nodes) { this.children.forEach(n => { n.parent = null; }); this.children = []; this.text = ''; this.append(...nodes); }
    setAttribute(key, value) { this.attrs[key] = value; }
    addEventListener(event, callback) { (this.events[event] ||= []).push(callback); }
    querySelectorAll(selector) {
        const nodes = this.children.flatMap(n => [n, ...n.querySelectorAll('*')]);
        return nodes.filter(n => selector === '*' || selector === n.tag || (selector === 'button[type="submit"]' && n.tag === 'button' && n.type === 'submit'));
    }
    querySelector(selector) { return this.querySelectorAll(selector)[0]; }
    async emit(event) { for (const action of this.events[event] || []) await action({currentTarget: this, preventDefault() {}}); }
    async click() { if (!this.disabled) await this.emit('click'); }
    showModal() {}
    close() { return this.emit('close'); }
    remove() { if (this.parent) this.parent.children = this.parent.children.filter(n => n !== this); this.parent = null; }
}
const button = (root, label) => { const result = root.querySelectorAll('button').find(n => n.textContent === label); assert.ok(result, label); return result; };
const input = (root, label) => { const group = root.querySelectorAll('label').find(n => n.textContent.startsWith(label)); assert.ok(group, label); return group.children.at(-1); };
const change = async (node, value, event = 'input') => { if (node.type === 'checkbox') node.checked = value; else node.value = value; await node.emit(event); };

async function app({status = 'uncertain', outcomes = [], hasMore = false} = {}) {
    const body = new Element('body'); body.root = true;
    const settings = new Element('section'); body.append(settings);
    const requests = [], posts = [], alerts = [];
    const record = {id: 'item-1', kind: '<img src=x onerror=alert(1)>', status, version: 2, chat_id: '-100', user_id: null, attempts: 1, has_error: true};
    const code = readFileSync(join(__dirname, '../../web/static/js/postgres-admin.js'), 'utf8');
    // Execute production helpers and complete Settings function without unrelated startup.
    const source = code.slice(0, code.indexOf('    function renderDelivery(')) + '\nconst post = (path, data) => api(path, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(data)}); window.loadSettings = systemSettings; })();';
    const window = {};
    runInNewContext(source, {
        window, document: {body, getElementById: id => id === 'settings' ? settings : null, createElement: tag => new Element(tag), createElementNS: (_, tag) => new Element(tag)},
        URLSearchParams, Intl, crypto: {randomUUID: (() => { let i = 0; return () => `00000000-0000-4000-8000-${String(++i).padStart(12, '0')}`; })()},
        alert: message => alerts.push(message),
        fetch: async (path, options = {}) => {
            requests.push(path);
            let value;
            if (options.method === 'POST') {
                posts.push({path, body: options.body});
                const outcome = outcomes.shift();
                if (outcome === 'network') throw new Error('Offline');
                if (outcome === 'conflict') return {ok: false, status: 409, json: async () => ({detail: 'Conflict'})};
                record.status = 'resolved'; record.version = 3; value = {status: 'resolved'};
            } else if (path.startsWith('/api/notifications?')) {
                const query = new URLSearchParams(path.split('?')[1]);
                value = {items: [{...record, status: query.get('status')}], has_more: hasMore};
            } else if (path === '/api/notifications/item-1') value = record;
            else value = {'/api/control/maintenance': {maintenance_mode: false}, '/api/dev-backups': {items: []}, '/api/chats': [], '/api/dev-broadcasts': {items: []}}[path];
            assert.notEqual(value, undefined, path);
            return {ok: true, status: 200, json: async () => value};
        },
    });
    await window.loadSettings();
    if (status !== 'uncertain') await change(input(settings, 'Статус уведомлений'), status, 'change');
    const open = async () => { await button(settings, status === 'uncertain' ? 'Проверить и закрыть' : 'Просмотреть').click(); return body.querySelector('dialog'); };
    return {body, settings, posts, requests, alerts, open};
}

async function fill(form, decision) {
    await change(input(form, 'Решение после проверки'), decision, 'change');
    await change(input(form, 'Причина решения'), 'Проверила историю');
    await change(input(form, 'Способ проверки'), 'Ручная проверка');
    await change(input(form, 'Подтверждаю выбранное'), true);
}

test('explicit decision, required confirmation and text-only untrusted projection', async () => {
    const ui = await app(); const dialog = await ui.open(), form = dialog.querySelector('form');
    assert.equal(input(form, 'Решение после проверки').value, '');
    assert.equal(dialog.textContent.includes('<img src=x onerror=alert(1)>'), true);
    assert.equal(dialog.querySelectorAll('img').length, 0);
    await form.emit('submit'); assert.equal(ui.posts.length, 0);
    await fill(form, 'closed_without_resend');
    assert.equal(button(form, 'Закрыть без повторной отправки').type, 'submit');
    await form.emit('submit'); assert.equal(ui.posts.length, 1);
    const payload = JSON.parse(ui.posts[0].body);
    assert.equal(payload.decision, 'closed_without_resend'); assert.equal(payload.expected_version, 2);
    assert.equal('actor' in payload, false); assert.equal('operator_id' in payload, false);
});

test('network retry preserves exact action/body; edits allocate new action; conflict keeps version', async () => {
    const ui = await app({outcomes: ['network', 'network', 'conflict', 'network']});
    const dialog = await ui.open(), form = dialog.querySelector('form');
    await fill(form, 'closed_without_resend');
    await form.emit('submit'); await form.emit('submit');
    assert.equal(ui.posts[0].body, ui.posts[1].body);
    await change(input(form, 'Причина решения'), 'Изменённое решение');
    await form.emit('submit');
    assert.notEqual(JSON.parse(ui.posts[2].body).action_id, JSON.parse(ui.posts[1].body).action_id);
    assert.ok(form.textContent.includes('Данные уже изменились'));
    assert.equal(ui.requests.filter(path => path === '/api/notifications/item-1').length, 1);
    await form.emit('submit'); assert.equal(ui.posts[2].body, ui.posts[3].body);
    assert.equal(JSON.parse(ui.posts[3].body).expected_version, 2);
});

test('confirmed delivery requires chat/message; sending and resolved are read-only', async () => {
    const ui = await app(), dialog = await ui.open(), form = dialog.querySelector('form');
    await fill(form, 'confirmed_delivered');
    await form.emit('submit'); assert.equal(ui.posts.length, 0);
    await change(input(form, 'Chat ID'), '-100'); await change(input(form, 'Message ID'), '42');
    await form.emit('submit');
    const payload = JSON.parse(ui.posts[0].body);
    assert.equal(payload.chat_id, -100); assert.equal(payload.message_id, 42);
    for (const status of ['sending', 'resolved']) {
        const readonly = await app({status}); const view = await readonly.open();
        assert.equal(view.querySelectorAll('input').length, 0);
        assert.ok(view.textContent.includes('только для чтения'));
        await view.querySelector('form').emit('submit'); assert.equal(readonly.posts.length, 0);
    }
});

test('bounded pagination and status switch reset offset', async () => {
    const ui = await app({hasMore: true});
    await button(ui.settings, 'Следующие уведомления').click();
    assert.ok(ui.requests.includes('/api/notifications?status=uncertain&limit=25&offset=25'));
    await change(input(ui.settings, 'Статус уведомлений'), 'sending', 'change');
    assert.ok(ui.requests.includes('/api/notifications?status=sending&limit=25&offset=0'));
});
