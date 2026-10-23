'use strict';
// Сорока-коробейница in the village (art from scripts/art/village/merchant.js): cart layer, figure, anchor, goods icons.
// Showing her by schedule belongs to the merchant mechanic (html[data-merchant]); this checks the art side only.
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('fs'),path=require('path');
const stat=path.join(__dirname,'../../qw_farm/static');
const app=fs.readFileSync(path.join(stat,'app.js'),'utf8'),css=fs.readFileSync(path.join(stat,'style.css'),'utf8');
const api=fs.readFileSync(path.join(__dirname,'../../qw_farm/api.py'),'utf8'),icons=fs.readFileSync(path.join(stat,'icons.svg'),'utf8');
const cart=fs.readFileSync(path.join(stat,'village-merchant.svg'),'utf8');

test('cart layer: vector only, CSP-safe, base under the night tint and a lantern glow above it',()=>{
 assert.match(cart,/^<svg [^>]*viewBox="0 0 2400 1800"/);
 assert.doesNotMatch(cart,/<image|data:|<style|style=|<script|href=/i);
 for(const g of ['vm-base','vm-night'])assert.match(cart,new RegExp(`<g class="${g}">`));
 assert.match(api,/'village-merchant\.svg'/);
});
test('magpie figure and anchor: hidden until html[data-merchant], standing at the generated spot, approach in the walk graph',()=>{
 const M=eval('('+app.slice(app.indexOf('const VILLAGE_MERCHANT=')+'const VILLAGE_MERCHANT='.length,app.indexOf("'};",app.indexOf('const VILLAGE_MERCHANT='))+2)+')');
 assert.equal(M.asset,'village-merchant.svg');assert.equal(M.cart.length,4);assert.equal(M.foot.length,2);
 for(const f of ['vm-stand','vm-call'])assert.match(M.figure,new RegExp(`<g class="${f}">`));
 const W=eval('('+app.slice(app.indexOf('const VILLAGE_WALK=')+'const VILLAGE_WALK='.length,app.indexOf(';\n',app.indexOf('const VILLAGE_WALK=')))+')');
 assert.ok(Number.isInteger(W.a.merchant),'approach node for the peddler');
 assert.match(css,/\.village-merchant,\.village-merchant-figure\{display:none\}/);
 assert.match(css,/:root\[data-merchant\] \.village-merchant,:root\[data-merchant\] \.village-merchant-figure\{display:block\}/);
 assert.match(css,/prefers-reduced-motion:no-preference\)\{\s*\.village-merchant-figure \.vm-figure-art\{animation:vm-sway/);
 assert.match(app,/world\.append\(villageMerchantLayer\('base'\),villageFestLayer\('base'\),villageContrastLayer\(\),villageBuildLayer\('base'\),sun,villageFx\(\),night,villageFestLayer\('glow'\),villageBuildLayer\('glow'\),villageMerchantLayer\('glow'\),villageMerchantFigure\(\),/);
 assert.match(app,/const on=!!globalThis\.document\?\.documentElement\?\.dataset\?\.merchant/,'nothing is fetched outside her visit');
});
test('goods icons of the peddler exist in the sprite',()=>{
 for(const id of ['dye_indigo','dye_madder','dye_saffron','merchant_scroll','merchant_seeds','merchant_graft','merchant_voucher','avatar_magpie'])
  assert.match(icons,new RegExp(`<symbol id="${id}" viewBox="0 0 (48 48|40 40)">`));
});
