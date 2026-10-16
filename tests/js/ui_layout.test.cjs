'use strict';
// Browser checks of docs/design/UI_RULES.md via tests/ui/ui_check.py (Playwright).
// Skips when Python Playwright or a Chromium-family browser is missing.
// Real screens: set QW_UI_BASE_URL (for example http://127.0.0.1:4187) to scan a running app for glued buttons.
const test = require('node:test');
const assert = require('node:assert/strict');
const {spawnSync} = require('node:child_process');
const path = require('node:path');

const root = path.resolve(__dirname, '..', '..');
const script = path.join(root, 'tests', 'ui', 'ui_check.py');

function run(...args) {
    for (const python of process.platform === 'win32' ? ['python', 'py'] : ['python3', 'python']) {
        const result = spawnSync(python, [script, ...args], {cwd: root, encoding: 'utf8', timeout: 240000, env: {...process.env, PYTHONUTF8: '1'}});
        if (result.error?.code === 'ENOENT') continue;
        return result;
    }
    return null;
}

function check(t, ...args) {
    const result = run(...args);
    if (!result) { t.skip('python is not available'); return; }
    const output = (result.stdout || '') + (result.stderr || '');
    if (/^SKIP:/m.test(output)) { t.skip(output.trim()); return; }
    assert.equal(result.status, 0, output);
}

test('shell navigation, BackButton, ⚙ menu and safe-area work with and without Telegram', t => check(t, 'nav'));
test('button-gap scanner catches glued buttons and allows .qw-btn-group', t => check(t, 'gaps-selftest'));
test('real screens have no glued buttons and keep 44px taps (QW_UI_BASE_URL)', t => {
    if (!process.env.QW_UI_BASE_URL) { t.skip('set QW_UI_BASE_URL to a running app'); return; }
    check(t, 'gaps', '--base', process.env.QW_UI_BASE_URL);
});
