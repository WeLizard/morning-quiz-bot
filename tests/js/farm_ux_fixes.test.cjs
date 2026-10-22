const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const stat=path.join(__dirname,'../../qw_farm/static');
const css=fs.readFileSync(path.join(stat,'style.css'),'utf8');
const app=fs.readFileSync(path.join(stat,'app.js'),'utf8');

test('swimming duck has no leg lines, the land duck keeps them',async()=>{
 const {smallAnimal}=await import('../../qw_farm/static/scene_expansion.js');
 const noop=()=>{},ctx=new Proxy({},{get:(t,k)=>k in t?t[k]:noop,set:(t,k,v)=>(t[k]=v,true)});
 const run=id=>{const lines=[],s={c:ctx,time:0,shadow(){},ellipse(){},poly(){},line(...a){lines.push(a)}};smallAnimal(s,0,0,id);return lines};
 assert.equal(run('duck').length,2,'a walking duck stands on two legs');
 const swim=run('duck_swim');
 assert.ok(swim.every(l=>l[4]!=='#bd965a'),'no leg-coloured line');
 assert.ok(swim.every(l=>l[1]<=3&&l[3]<=3),'nothing hangs below the waterline');
});
test('the pond and the lake draw the duck as swimming',()=>{
 const scene=fs.readFileSync(path.join(stat,'scene.js'),'utf8'),exp=fs.readFileSync(path.join(stat,'scene_expansion.js'),'utf8');
 assert.doesNotMatch(scene+exp,/smallAnimal\([^)]*'duck'\)|sprite\('duck'/);
 assert.match(scene,/sprite\('duck_swim'/);assert.match(exp,/smallAnimal\(s,p\.x,p\.y,'duck_swim'\)/);
});
test('mill tap box follows the drawn silhouette and no longer steals from neighbours',async()=>{
 const {FarmScene,MILL_HIT}=await import('../../qw_farm/static/scene.js');
 assert.ok(MILL_HIT.top<=110&&MILL_HIT.hw<=43,'not larger than tower + sail tips');
 const mill={id:'m',type:'mill',x:3,y:0,w:2,h:2},house={id:'h',type:'house',x:0,y:0,w:3,h:3};
 const scene=Object.create(FarmScene.prototype);
 Object.assign(scene,{farm:{id:'f',size:12,objects:[house,mill],is_owner:false},sortedObjects:()=>({list:[house,mill]}),grid:()=>12,projectStage:()=>0});
 const P=(x,y)=>({x:(x-y)*36,y:(x+y)*18}),c=P(4,1);
 const at=(dx,dy)=>{scene.world=()=>({x:c.x+dx,y:c.y+dy});scene.cell=()=>({x:-9,y:-9});return scene.pick(0,0)?.id};
 assert.equal(at(0,-100),'m','sail tips still open the mill');
 assert.notEqual(at(0,-125),'m');assert.notEqual(at(0,-110),'m');
 assert.notEqual(at(42,-60),'m','beside the tower is not the mill');
});
test('village residents get a 64px touch target that follows the wandering figure',()=>{
 assert.match(css,/\.village-npc::after[^{]*\{[^}]*inset:-8px/);
 assert.match(css,/\.village-walker\{pointer-events:auto/);
 const m=css.match(/\.village-npc,\.village-townhall\{[^}]*?;width:(\d+)px/);assert.ok(Number(m[1])+16>=64);
 // neighbouring residents' 64px rings do not overlap at the smallest world size (1600x1200)
 const spots=JSON.parse(app.match(/const VILLAGE_SPOTS=(\{[^}]*\})/)[1].replace(/'/g,'"'));
 const pts=Object.entries(spots).map(([n,[x,y]])=>({n,x:x*16,y:y*12}));
 for(let i=0;i<pts.length;i++)for(let j=i+1;j<pts.length;j++){const a=pts[i],b=pts[j];assert.ok(Math.abs(a.x-b.x)>=64||Math.abs(a.y-b.y)>=64,`${a.n}/${b.n} hit rings overlap`);}
});
test('exit sign is a real button: one board on the posts, farm-style highlight, no hover jump, 44px target',()=>{
 assert.match(app,/gate\.innerHTML=VILLAGE_GATE_SIGN/);
 // the global button:hover lift must not replace the centring transform (the board used to jump off its posts)
 assert.match(css,/\.village-gate:hover:not\(:disabled\),\.village-gate:active\{transform:translate\(-50%,-50%\)/);
 // hover, keyboard focus and press reuse the farm scene's object highlight token
 assert.match(css,/--farm-lit:brightness\(1\.12\) drop-shadow\(0 0 1px #fffbd0\) drop-shadow\(0 0 2px #fff2a0\)/);
 assert.match(css,/\.village-gate:hover \.vg-sign\{filter:var\(--farm-lit\)\}/);
 // keyboard focus: a real 2px ring that follows the board, in a dark green by day and warm yellow by night
 assert.match(css,/\.village-gate:focus-visible \.vg-sign\{filter:brightness\(1\.12\) var\(--farm-focus-ring\)\}/);
 const ring=c=>new RegExp(`--farm-focus-ring:drop-shadow\\(2px 0 0 ${c}\\) drop-shadow\\(-2px 0 0 ${c}\\) drop-shadow\\(0 2px 0 ${c}\\) drop-shadow\\(0 -2px 0 ${c}\\)`);
 assert.match(css,ring('#2f5d1e'));assert.match(css,/:root\[data-farm-theme=night\]\{--farm-focus-ring:/);assert.match(css,ring('#f2d57a'));
 // residents keep a 3px outline ring, recoloured for the night theme
 assert.match(css,/\.village-npc:focus-visible,[^{]*\{outline:3px solid #79975b;outline-offset:2px\}/);
 assert.match(css,/:root\[data-farm-theme=night\] :is\(\.village-npc,\.village-townhall\):focus-visible\{outline-color:#f2d57a\}/);
 // the board of the generated gate (scripts/art/village/gate.js): the farm's own name-sign board in the arch plane, day + night
 const sign=app.match(/const VILLAGE_GATE_SIGN='([\s\S]*?)';\r?\n/)[1];
 assert.match(sign,/^<svg class="vg-sign"/);assert.match(sign,/<g class="vg-day">[\s\S]*>Ферма<\/text>[\s\S]*<g class="vg-night">[\s\S]*>Ферма<\/text>/);
 assert.match(sign,/matrix\(1 -0\.5 0 1 /,'board lies in the gate plane (iso axis 1:-0.5)');
 assert.match(sign,/stop-color="#f1dfb2"/,'farm sign board gradient');assert.match(css,/:root\[data-farm-theme=night\] \.vg-night\{display:inline\}/);
 // only the board itself takes taps: the button ignores the pointer, the board-shaped .vg-hit catches it
 assert.equal((sign.match(/class="vg-hit"/g)||[]).length,1);assert.match(css,/\.village-gate\{[^}]*pointer-events:none/);assert.match(css,/\.village-gate \.vg-hit\{pointer-events:visiblePainted\}/);
 assert.match(css,/\.village-gate:active \.vg-sign\{filter:var\(--farm-lit-pressed\)\}/);
 const b=app.match(/VILLAGE_GATE_BOARD=\[([\d.]+),([\d.]+),([\d.]+),([\d.]+)\]/).map(Number);
 assert.ok(b[3]/100*1600>=44&&b[4]/100*1200>=44&&b[3]/100*1600<=120,'tap box is at least 44px at the smallest world (1600x1200)');
 // the arch is part of the generated background: one raster, no overlay patches or lettering in the asset
 const svg=fs.readFileSync(path.join(stat,'village.svg'),'utf8');
 assert.equal((svg.match(/<image /g)||[]).length,1,'no second raster layer');assert.doesNotMatch(svg,/<text|farm-exit-ground|exit-gate/,'no overlay on the background');
});
test('caravan card keeps the last payout / refund strip until the next caravan',()=>{
 assert.match(app,/const lc=m\.last_caravan;if\(lc\)c\.append\(caravanResult\(lc\)\)/);
 const f=app.slice(app.indexOf('function caravanResult('),app.indexOf('function caravanCard('));
 assert.match(f,/caravan-result \$\{lc\.ok\?'is-ok':'is-refund'\}/);
 assert.match(f,/icon\('coin'\)|gain\('coin'/);assert.match(f,/fmt\(lc\.coins\)/);assert.match(f,/fmt\(lc\.refund\)/);
 assert.match(f,/Ничего не погружено, ничего не потеряно/);
 assert.match(css,/\.caravan-result\.is-refund\{/);assert.match(css,/:root\[data-farm-theme=night\] \.caravan-result\{/);
});
test('farm header: one 10px rhythm around the 36px gear plate, map tools and zoom on the same right edge',()=>{
 const tail=css.slice(css.indexOf('/* ===== Header rhythm'));
 assert.match(tail,/html \.compact,html \.compact \.topbar,html \.compact\.immersive \.topbar\{--bar:56px\}/);
 assert.match(tail,/--hdr-x:calc\(\(var\(--bar\) - 44px\) \/ 2\)/);
 assert.match(tail,/padding-left:calc\(var\(--hdr-x\) \+ var\(--qw-safe-left\)\);padding-right:calc\(var\(--hdr-x\) \+ var\(--qw-safe-right\)\)/);
 // the gear keeps a 44px box (shell rule) and paints a 36px plate inset by 4px
 assert.match(css,/\.header-actions \.qw-icon-btn[^{]*\{flex:0 0 44px;width:44px;min-width:44px;height:44px;min-height:44px\}/);
 assert.match(tail,/\.qw-gear::before\{content:'';position:absolute;inset:4px/);
 assert.match(tail,/html \.map-tools,html \.compact \.map-tools\{right:calc\(\(var\(--bar\) - 36px\) \/ 2\)\}/);
 assert.match(tail,/html \.scene-dock\{--dock-inline:calc\(\(var\(--bar\) - 36px\) \/ 2\)\}/);
 assert.match(tail,/\.map-controls>button\{[^}]*width:44px;height:44px/);
});
test('river-mill wheel stands in the wall plane, turns away from the flume and pauses off-screen',()=>{
 assert.match(app,/const layer=\(dx,body\)=>`<g transform="matrix\(\.894,-\.447,0,1,/);
 assert.match(css,/\.vfx-wheel \.vw-rot\{animation:vfx-spin-ccw/);assert.match(css,/@keyframes vfx-spin-ccw\{from\{rotate:0deg\}to\{rotate:-360deg\}\}/);
 assert.match(app,/el\('i',null,'vfx-wheel va'\)/);
 assert.match(css,/:root\[data-farm-theme=night\] \.vfx-wheel \.vw-all\{filter:url\(#vw-night\)\}/);
});

