'use strict';
// Automatic client error reports (QW.errors): capture, noise filter, dedup, rate limits, sanitising, breadcrumbs, toast.
// Runs tests/ui/ui_check.py errors in a real browser (Playwright); skipped when Python Playwright or a Chromium-family browser is missing.
const test = require('node:test');
const assert = require('node:assert/strict');
const {spawnSync} = require('node:child_process');
const path = require('node:path');

const root = path.resolve(__dirname, '..', '..');
const script = path.join(root, 'tests', 'ui', 'ui_check.py');

test('automatic error reports: capture, filters, limits, sanitising, breadcrumbs and the soft toast', t => {
    for (const python of process.platform === 'win32' ? ['python', 'py'] : ['python3', 'python']) {
        const result = spawnSync(python, [script, 'errors'], {cwd: root, encoding: 'utf8', timeout: 240000, env: {...process.env, PYTHONUTF8: '1'}});
        if (result.error?.code === 'ENOENT') continue;
        const output = (result.stdout || '') + (result.stderr || '');
        if (/^SKIP:/m.test(output)) { t.skip(output.trim()); return; }
        assert.equal(result.status, 0, output);
        return;
    }
    t.skip('python is not available');
});
