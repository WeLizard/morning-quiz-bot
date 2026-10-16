'use strict';
// Static checks of docs/design/UI_RULES.md: shared shell is wired everywhere, minimum font sizes,
// no duplicate exits, account settings live only in the profile.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '..', '..');
const read = file => fs.readFileSync(path.join(root, file), 'utf8');
const exists = file => fs.existsSync(path.join(root, file));

const PAGES = ['web/mini_client/index.html', 'qw_farm/static/index.html', 'minigames/alchemia-1.0/shell.html'];
const STYLES = ['web/shell/qw-tokens.css', 'web/shell/qw-shell.css', 'web/mini_client/styles.css',
    'qw_farm/static/style.css', 'minigames/alchemia-1.0/style.css'];
const SCRIPTS = ['web/mini_client/app.js', 'web/mini_client/play-ui.js', 'qw_farm/static/app.js'];

test('every page loads the shared tokens and shell', () => {
    for (const page of PAGES) {
        const html = read(page);
        for (const asset of ['/app/shell/qw-tokens.css', '/app/shell/qw-shell.css', '/app/shell/qw-shell.js']) {
            assert.ok(html.includes(asset), `${page} must include ${asset}`);
        }
    }
});

// UI_RULES §7: a page never waits for another host. The Telegram SDK is a pinned local copy that qw-shell.js
// loads asynchronously, and only for Telegram launches; telegram.org may be unreachable on a player's network.
test('pages have no external <script src>, <link href> or Telegram SDK tag', () => {
    for (const page of [...PAGES, 'web/mini_client/alchemy.html']) {
        const html = read(page);
        const external = [...html.matchAll(/<(?:script|link)\b[^>]*\b(?:src|href)\s*=\s*["']((?:https?:)?\/\/[^"']+)/gi)].map(match => match[1]);
        assert.deepEqual(external, [], `${page} loads ${external.join(', ')}`);
        assert.ok(!/telegram-web-app\.js/.test(html), `${page}: the SDK is loaded by qw-shell.js, not by a tag`);
    }
});

test('the pinned Telegram SDK is vendored with its provenance and is loaded only by the shell', () => {
    const sdk = read('web/shell/vendor/telegram-web-app.js');
    assert.match(sdk.slice(0, 600), /Source: https:\/\/telegram\.org\/js\/telegram-web-app\.js, Last-Modified [^\n]+\n[^\n]*fetched \d{4}-\d{2}-\d{2}/);
    assert.ok(!/<script|importScripts|createElement\(['"]script/.test(sdk), 'SDK must not pull further scripts');
    const shell = read('web/shell/qw-shell.js');
    assert.ok(shell.includes("'/app/shell/vendor/telegram-web-app.js'") && shell.includes('telegramReady'));
    assert.ok(!/https:\/\/telegram\.org\/js/.test(shell.replace(/\/\*[\s\S]*?\*\//g, '')), 'shell code must not reference telegram.org');
});

test('the built Alchemy keeps the shell links', () => {
    const html = read('web/mini_client/alchemy.html');
    assert.ok(html.includes('/app/shell/qw-shell.js') && html.includes('/app/shell/qw-tokens.css'));
});

test('no text smaller than 12px in shell and game styles', () => {
    for (const file of STYLES) {
        const css = read(file);
        for (const match of css.matchAll(/font-size\s*:\s*([0-9.]+)px/g)) {
            assert.ok(Number(match[1]) >= 12, `${file}: font-size ${match[1]}px < 12px`);
        }
        for (const match of css.matchAll(/font\s*:[^;}]*?\b([0-9.]+)px\s*\//g)) {
            assert.ok(Number(match[1]) >= 12, `${file}: font shorthand ${match[1]}px < 12px`);
        }
    }
});

test('games have no private Telegram bridge or hard-coded safe-area', () => {
    assert.ok(!exists('qw_farm/static/telegram.js'), 'qw_farm/static/telegram.js is replaced by /app/shell/qw-shell.js');
    for (const file of ['qw_farm/static/style.css', 'qw_farm/static/app.js', 'minigames/alchemia-1.0/style.css']) {
        const text = read(file);
        assert.ok(!/--tg-safe-top|--app-height/.test(text), `${file}: use --qw-safe-* and --qw-vh`);
    }
    // Alchemy also runs standalone (serve.py): env() is allowed only as the fallback of the shell token.
    const alchemy = read('minigames/alchemia-1.0/style.css').replace(/var\(--qw-safe-(top|right|bottom|left)\s*,\s*env\(safe-area-inset-\1\s*,\s*0px\)\)/g, '');
    assert.ok(!/env\(safe-area-inset/.test(alchemy), 'Alchemy uses --qw-safe-* (env() only as its fallback)');
});

test('no duplicate exits on game screens: one way to the main menu is ⚙ → «Главное меню»', () => {
    for (const file of SCRIPTS) {
        const text = read(file);
        for (const label of ['К играм', 'К комнатам', 'На главную QuizzyWizzy', 'В профиль QuizzyWizzy']) {
            assert.ok(!text.includes(`'${label}'`) && !text.includes(`"${label}"`) && !text.includes(`>${label}<`), `${file} still renders «${label}»`);
        }
    }
});

test('account settings (form of address) live only in the profile, not inside games', () => {
    assert.ok(!read('qw_farm/static/app.js').includes('Как к тебе обращаться'), 'farm must not render the address form');
    assert.ok(read('web/mini_client/app.js').includes('addressSection'), 'profile keeps the address form');
});

test('farm header has the core ⚙ instead of ⛶ and ☷', () => {
    const html = read('qw_farm/static/index.html');
    assert.ok(!/id="fullscreen"|id="toggle-ui"/.test(html), 'fullscreen and panel toggles moved into the ⚙ menu');
    assert.ok(read('qw_farm/static/app.js').includes('QW.header.mountGear') || read('qw_farm/static/app.js').includes('QW?.header.mountGear'));
});

test('UI rules are referenced for both agents', () => {
    for (const file of ['AGENTS.md', 'CLAUDE.md']) assert.ok(read(file).includes('docs/design/UI_RULES.md'), `${file} must point at UI_RULES.md`);
});
