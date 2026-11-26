// UI_RULES §4/§6: the on-screen ‹ of the shared shell (web/shell/qw-shell.js) on nested screens. Outside Telegram it is the
// only Back; inside Telegram the BackButton in Telegram's header does the job, except in fullscreen on a phone, where Telegram
// shows only «Закрыть» (Android, 2026-11-26): there ‹ is drawn too, and it hides again when fullscreen ends.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {runInNewContext} = require('node:vm');
const shellSource = fs.readFileSync(path.resolve(__dirname, '../../web/shell/qw-shell.js'), 'utf8');

class Node {
    constructor(tag) { this.tagName = tag; this.children = []; this.attrs = {}; this.events = {}; this.dataset = {}; this.style = {setProperty() {}}; this.innerHTML = ''; this.hidden = false;
        const set = new Set(); this.classList = {add: c => set.add(c), remove: c => set.delete(c), toggle: (c, on) => (on ?? !set.has(c)) ? set.add(c) : set.delete(c), contains: c => set.has(c)}; }
    append(...nodes) { this.children.push(...nodes); }
    prepend(...nodes) { this.children.unshift(...nodes); }
    setAttribute(key, value) { this.attrs[key] = String(value); }
    removeAttribute(key) { delete this.attrs[key]; }
    addEventListener(kind, fn) { this.events[kind] = fn; }
    querySelector() { return null; }
    querySelectorAll() { return []; }
}

function shell(telegram) {
    const root = new Node('html');
    const document = {documentElement: root, head: new Node('head'), body: new Node('body'), createElement: tag => new Node(tag),
        querySelector() { return null; }, querySelectorAll() { return []; }, addEventListener() {}, removeEventListener() {}};
    const events = {}, back = {visible: false};
    const win = {document, addEventListener() {}};
    if (telegram) win.Telegram = {WebApp: {initData: 'query_id=1', version: '8.0', themeParams: {}, colorScheme: 'light', ...telegram,
        isVersionAtLeast: v => Number(v) <= 8, ready() {}, expand() {}, disableVerticalSwipes() {}, setHeaderColor() {}, setBackgroundColor() {}, setBottomBarColor() {},
        BackButton: {show() { back.visible = true; }, hide() { back.visible = false; }, onClick() {}}, SettingsButton: {show() {}, onClick() {}},
        onEvent: (name, fn) => { events[name] = fn; }, requestFullscreen() {}}};
    runInNewContext(shellSource, {window: win, document, localStorage: {getItem() { return null; }, setItem() {}},
        sessionStorage: {getItem() { return null; }}, location: {search: '', hash: '', pathname: '/app/night'}, history: {pushState() {}, replaceState() {}, back() {}, state: null},
        addEventListener() {}, matchMedia() { return {matches: false, addEventListener() {}}; }, getComputedStyle() { return {getPropertyValue() { return ''; }}; },
        setTimeout, clearTimeout, requestAnimationFrame: fn => fn(), Intl, Promise});
    const QW = win.QW;
    if (telegram) QW.boot({history: false});
    const bar = new Node('div'), button = QW.header.mountBack(bar);
    return {QW, button, back, webApp: win.Telegram?.WebApp, events};
}

test('in a browser ‹ shows on nested screens only', () => {
    const {QW, button} = shell(null);
    assert.equal(button.hidden, true, 'no ‹ on the root');
    QW.nav.push({id: 'sheet'});
    assert.equal(button.hidden, false);
    QW.nav.pop('sheet');
    assert.equal(button.hidden, true);
});

test('in Telegram outside fullscreen the BackButton is the only Back', () => {
    for (const platform of ['android', 'ios', 'tdesktop']) {
        const {QW, button, back} = shell({platform, isFullscreen: false});
        QW.nav.push({id: 'sheet'});
        assert.equal(back.visible, true, `${platform}: Telegram BackButton on a nested screen`);
        assert.equal(button.hidden, true, `${platform}: no second Back next to Telegram's`);
    }
});

test('in Telegram fullscreen on a phone ‹ is drawn too, and hides when fullscreen ends', () => {
    for (const platform of ['android', 'ios']) {
        const {QW, button, webApp, events} = shell({platform, isFullscreen: true});
        assert.equal(button.hidden, true, `${platform}: still no ‹ on the root`);
        QW.nav.push({id: 'sheet'});
        assert.equal(button.hidden, false, `${platform}: Telegram shows only «Закрыть» in fullscreen`);
        webApp.isFullscreen = false; events.fullscreenChanged();
        assert.equal(button.hidden, true, `${platform}: Telegram's header with «Назад» is back`);
        webApp.isFullscreen = true; events.fullscreenChanged();
        assert.equal(button.hidden, false);
    }
    const desktop = shell({platform: 'tdesktop', isFullscreen: true});
    desktop.QW.nav.push({id: 'sheet'});
    assert.equal(desktop.button.hidden, true, 'desktop Telegram keeps its own Back');
});
