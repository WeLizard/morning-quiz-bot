// The village guests' figures (scripts/art/village/guests.js) are inlined into app.js as VILLAGE_VISITOR_FIGURES.
// They must be the generator's output, cover every guest and easter egg, and stay vector without style attributes (CSP).
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const root=path.join(__dirname,'../..');
const source=fs.readFileSync(process.env.FARM_APP_JS||path.join(root,'qw_farm/static/app.js'),'utf8');
const literal=(name,end)=>{const i=source.indexOf(`const ${name}=`)+`const ${name}=`.length;return vm.runInNewContext('('+source.slice(i,source.indexOf(end,i)+end.length-1)+')');};
const figures=literal('VILLAGE_VISITOR_FIGURES','};');
const ids=[...literal('VILLAGE_VISITORS','];'),...literal('VILLAGE_EGGS','];')].map(v=>v[0]);

test('every guest and easter egg has its figure',()=>{
 assert.ok(ids.length>=14);
 for(const id of [...ids,'bogatyr'])assert.ok(figures[id],`no figure for ${id}`);
});

test('figures are vector, without style or raster, in the resident box',()=>{
 for(const [id,svg] of Object.entries(figures)){
  assert.match(svg,/^<svg [^>]*viewBox="-18 -50 36 54"/,id);
  assert.doesNotMatch(svg,/style=|<style|<image|<script/,id);
 }
});

test('the inlined figures are the generator output',{skip:!fs.existsSync(path.join(root,'.local/village-generator/out/guest-figures.json'))&&'generator output not built'},()=>{
 const built=JSON.parse(fs.readFileSync(path.join(root,'.local/village-generator/out/guest-figures.json'),'utf8'));
 assert.deepEqual(JSON.parse(JSON.stringify(figures)),built);   // figures come from another vm realm
});

test('visitor buttons and the guest sheet use the figure',()=>{
 assert.match(source,/const fig=VILLAGE_VISITOR_FIGURES\[id\];if\(fig\)\{b\.dataset\.figure='1';walker\.innerHTML=fig;\}/);
 assert.match(source,/const fig=VILLAGE_VISITOR_FIGURES\[v\[0\]\][\s\S]{0,200}village-guest-portrait/);
});
