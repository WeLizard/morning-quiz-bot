'use strict';
// Shared harness of the Night Case client tests: a tiny DOM, the shell's prefs and a live controller
// of web/mini_client/night-case-ui.js run in a vm with a stub NightCity kit and a scripted request().
const fs = require('node:fs');
const path = require('node:path');
const {runInNewContext} = require('node:vm');
const source = fs.readFileSync(path.resolve(__dirname, '../../web/mini_client/night-case-ui.js'), 'utf8');
const shellSource = fs.readFileSync(path.resolve(__dirname, '../../web/shell/qw-shell.js'), 'utf8');

class Node {
    constructor(tag) { this.tagName = tag; this.children = []; this.attrs = {}; this.events = {}; this.dataset = {}; this.value = ''; this._text = ''; this.className = ''; this.classList = {add() {}, remove() {}};
        this.style = {props: {}, setProperty(key, value) { this.props[key] = value; }}; }
    set textContent(value) { this._text = String(value); this.children = []; }
    get textContent() { return this._text + this.children.map(x => typeof x === 'string' ? x : x.textContent).join(' '); }
    set innerHTML(value) { throw new Error('HTML parsing is forbidden'); }
    append(...nodes) { this.children.push(...nodes.filter(x => x != null)); }
    prepend(...nodes) { this.children.unshift(...nodes); }
    replaceChildren(...nodes) { this.children = nodes; this._text = ''; }
    setAttribute(key, value) { this.attrs[key] = String(value); }
    removeAttribute(key) { delete this.attrs[key]; }
    addEventListener(kind, fn) { this.events[kind] = fn; }
    click() { return this.events.click?.(); }
}
const find = (node, predicate) => predicate(node) ? node : node.children.map(x => x instanceof Node ? find(x, predicate) : null).find(Boolean);
const settle = async () => { for (let i = 0; i < 5; i++) await new Promise(resolve => setImmediate(resolve)); };
// WebCrypto digest resolves from the thread pool, so a cold first call could outlast settle() (a flaky scene test,
// 2026-11-26). The same SHA-256 computed in place resolves at once.
const subtle = {async digest(_algorithm, bytes) { const hash = require('node:crypto').createHash('sha256').update(Buffer.from(bytes)).digest(); return hash.buffer.slice(hash.byteOffset, hash.byteOffset + hash.length); }};

function shellPrefs(IntlImpl = Intl, saved = {}) {
    const root = new Node('html'); root.style = {setProperty() {}};
    root.classList = {toggle() {}, add() {}, remove() {}};
    const document = {documentElement: root, head: new Node('head'), body: new Node('body'),
        createElement(tag) { return new Node(tag); }, querySelector() { return null; }, querySelectorAll() { return []; },
        addEventListener() {}, removeEventListener() {}};
    const win = {document, addEventListener() {}};
    runInNewContext(shellSource, {window: win, document, Intl: IntlImpl, localStorage: {getItem() { return null; }, setItem(_key, value) { saved.value = value; }},
        sessionStorage: {getItem() { return null; }}, location: {search: '', hash: '', pathname: '/app'},
        addEventListener() {}, matchMedia() { return {matches: false, addEventListener() {}}; },
        getComputedStyle() { return {getPropertyValue() { return ''; }}; }, setTimeout, clearTimeout});
    return {prefs: win.QW.prefs, QW: win.QW, saved};
}

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
    const zoneApi = shellPrefs(options.Intl || Intl).prefs;
    const win = {NightCity: {kit, parseLaunch: () => null}, QW: {prefs: zoneApi, configure() {}, menu: {register() {}}, nav: options.nav || {push() {}, pop() {}}}, crypto: {randomUUID: () => `request-${++next}`, subtle} };
    const host = new Node('div');
    const listeners = new Map();
    const doc = {createElement: make, documentElement: new Node('html'), hidden: false,
        addEventListener(kind, listener, {signal} = {}) { listeners.set(kind, listener); signal?.addEventListener('abort', () => listeners.delete(kind)); }};
    runInNewContext(source, {window: win, document: doc, AbortController, setTimeout, clearTimeout, TextEncoder, Intl: options.Intl || Intl,
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
    return {host, handle, calls, nodes, intervals, doc, listeners, zoneApi};
}

module.exports = {Node, find, settle, shellPrefs, controller, VIEWER, source};
