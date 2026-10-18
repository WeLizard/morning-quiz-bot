const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

// app.js awaits enter() at top level and renders immediately; any top-level
// const/let declared below that line is still in its TDZ during the first render.
test('farm app.js declares no top-level const/let after the boot await', () => {
  const lines = fs.readFileSync(path.join(__dirname, '../../qw_farm/static/app.js'), 'utf8').split('\n');
  const boot = lines.findIndex(line => /^try\{S\.config=await request\(/.test(line));
  assert.ok(boot > 0, 'boot line not found');
  const late = lines.slice(boot + 1)
    .map((line, i) => [boot + i + 2, line])
    .filter(([, line]) => /^(const|let)\s/.test(line));
  assert.deepEqual(late.map(([n, line]) => `${n}: ${line.slice(0, 60)}`), []);
});

test('village presence state is initialized before the first boot render', () => {
  const source = fs.readFileSync(path.join(__dirname, '../../qw_farm/static/app.js'), 'utf8');
  const state = source.indexOf('let villageSession=null');
  const boot = source.indexOf("try{S.config=await request(API+'/config')");
  const reset = source.indexOf('function resetVillageView()');
  assert.ok(state > 0 && state < reset && reset < boot,
    'presence state must exist before boot can call resetVillageView');
});
