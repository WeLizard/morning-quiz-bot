const {test}=require('node:test');const assert=require('node:assert/strict');const fs=require('node:fs');const path=require('node:path');const vm=require('node:vm');
// scene_map.js is an ES module of pure helpers (plus the DOM Minimap class, not instantiated here).
const source=fs.readFileSync(path.join(__dirname,'../../qw_farm/static/scene_map.js'),'utf8').replace(/export (const|function|class) /g,'$1 ');
const names='TW TH iso CATEGORIES CATEGORY_COLOR viewRect overlaps objectBounds panToCenter clampWorldPoint categoryOf readyInfo listObjects countByCategory miniTransform miniToWorld'.split(' ');
const ctx={WeakMap,Set,Object,Math};vm.createContext(ctx);vm.runInContext(source+`\nglobalThis.api={${names.join(',')}};`,ctx);
const m=ctx.api;const A=a=>Array.from(a);
const catalog={buildings:{mill:{},coop:{},bench:{decor:true},duckpond:{}},animals:{chicken:{building:'coop'},duck:{building:'duckpond'}}};
const plot=(x,y,crop)=>({id:`p${x}_${y}`,type:'plot',x,y,w:1,h:1,crop});
const build=(type,x,y,extra={})=>({id:`${type}${x}_${y}`,type,x,y,w:2,h:2,jobs:[],animal:null,animal_job:null,...extra});

test('view rectangle maps the screen into world pixels and respects a margin',()=>{
 const v=m.viewRect(800,600,{x:400,y:100},2);
 assert.deepEqual({...v},{x0:-200,y0:-50,x1:200,y1:250});
 const w=m.viewRect(800,600,{x:400,y:100},2,40);
 assert.equal(w.x0,-220);assert.equal(w.y1,270);
});
test('overlap test is strict and symmetric (touching edges are off screen)',()=>{
 const a={x0:0,y0:0,x1:10,y1:10};
 assert.equal(m.overlaps(a,{x0:5,y0:5,x1:20,y1:20}),true);
 assert.equal(m.overlaps(a,{x0:10,y0:0,x1:20,y1:10}),false);
 assert.equal(m.overlaps({x0:11,y0:0,x1:20,y1:10},a),false);
});
test('culling keeps everything a screen shows and drops far objects',()=>{
 const view=m.viewRect(400,400,{x:200,y:200},1); // world x -200..200, y -200..200
 const near=build('mill',0,0),far=build('mill',18,0),farPlot=plot(0,19);
 assert.equal(m.overlaps(m.objectBounds(near),view),true);
 assert.equal(m.overlaps(m.objectBounds(far),view),false);
 assert.equal(m.overlaps(m.objectBounds(farPlot),view),false);
 // A tall building whose roof reaches into view from below the bottom edge is still kept.
 const b=m.objectBounds(build('mill',10,10));
 assert.ok(b.y1-b.y0>=250,'bounds include the roof and the ready bubble');
 // Bounds always contain the footprint centre of the object.
 for(const o of [plot(3,7),build('coop',5,5)]){const c=m.iso(o.x+o.w/2,o.y+o.h/2),bb=m.objectBounds(o);assert.ok(c.x>bb.x0&&c.x<bb.x1&&c.y>bb.y0&&c.y<bb.y1)}
});
test('panToCenter really centres a world point and clampWorldPoint keeps it on the land',()=>{
 const base={x:300,y:120},scale=1.5,wx=-210,wy=400,pan=m.panToCenter(600,500,base,scale,wx,wy);
 assert.equal(base.x+pan.x+wx*scale,300);assert.equal(base.y+pan.y+wy*scale,250);
 assert.deepEqual({...m.clampWorldPoint(20,99999,-5)},{x:720,y:0});
 assert.deepEqual({...m.clampWorldPoint(20,-99999,99999)},{x:-720,y:720});
});
test('panToCenter can aim above a bottom sheet (cy) and defaults to the viewport middle',()=>{
 const base={x:200,y:140},scale=.9,wx=100,wy=300,withSheet=m.panToCenter(400,800,base,scale,wx,wy,250);
 assert.equal(base.y+withSheet.y+wy*scale,250);assert.equal(base.x+withSheet.x+wx*scale,200);
 assert.deepEqual({...m.panToCenter(400,800,base,scale,wx,wy)},{...m.panToCenter(400,800,base,scale,wx,wy,400)});
});
test('categories: plots, animal houses (even empty), workshops, decor, house and barn',()=>{
 assert.equal(m.categoryOf(plot(0,0),catalog),'plots');
 assert.equal(m.categoryOf(build('coop',0,0),catalog),'animals');
 assert.equal(m.categoryOf(build('duckpond',0,0),catalog),'animals');
 assert.equal(m.categoryOf(build('mill',0,0),catalog),'workshops');
 assert.equal(m.categoryOf({...build('bench',0,0),w:1,h:1},catalog),'decor');
 assert.equal(m.categoryOf(build('house',0,0),catalog),'other');
 assert.equal(m.categoryOf(build('barn',0,0),catalog),'other');
 assert.equal(m.categoryOf(build('mill',0,0),null),'workshops');
});
test('ready state: crops, workshop queues and animals',()=>{
 const t=1000;
 assert.equal(m.readyInfo(plot(0,0,null),t,catalog).state,'idle');
 assert.equal(m.readyInfo(plot(0,0,{ready_at:999}),t,catalog).state,'ready');
 assert.deepEqual({...m.readyInfo(plot(0,0,{ready_at:1500}),t,catalog)},{state:'busy',at:1500});
 assert.equal(m.readyInfo(build('mill',0,0,{jobs:[{ready_at:2000},{ready_at:900}]}),t,catalog).state,'ready');
 assert.deepEqual({...m.readyInfo(build('mill',0,0,{jobs:[{ready_at:2000},{ready_at:1700}]}),t,catalog)},{state:'busy',at:1700});
 assert.equal(m.readyInfo(build('coop',0,0,{animal:'chicken',animal_job:{ready_at:1000}}),t,catalog).state,'ready');
 assert.equal(m.readyInfo(build('coop',0,0,{animal:'chicken'}),t,catalog).state,'idle');
 assert.equal(m.readyInfo(build('bench',0,0),t,catalog).state,'none');
 assert.equal(m.readyInfo(build('house',0,0),t,catalog).state,'none');
});
test('find list filters by category, supports only-ready and puts ready first',()=>{
 const t=1000,objs=[plot(5,5,{ready_at:2000}),plot(1,1,{ready_at:500}),plot(9,2,null),build('mill',4,4,{jobs:[{ready_at:100}]}),build('coop',6,0,{animal:'chicken'}),{...build('bench',2,2),w:1,h:1},build('house',0,0)];
 const all=m.listObjects(objs,catalog,t);
 assert.equal(all.length,7);assert.equal(all[0].info.state,'ready');assert.equal(all[1].info.state,'ready');
 assert.deepEqual(A(all.slice(0,2).map(r=>r.o.id).sort()),['mill4_4','p1_1']);
 assert.deepEqual(A(m.listObjects(objs,catalog,t,{category:'plots'}).map(r=>r.o.id)),['p1_1','p9_2','p5_5']);
 assert.deepEqual(A(m.listObjects(objs,catalog,t,{category:'plots',onlyReady:true}).map(r=>r.o.id)),['p1_1']);
 assert.equal(m.listObjects(objs,catalog,t,{category:'animals'}).length,1);
 assert.equal(m.listObjects(objs,catalog,t,{category:'decor'}).length,1);
 assert.equal(m.listObjects(objs,catalog,t,{onlyReady:true}).length,2);
 const c=m.countByCategory(objs,catalog,t);
 assert.deepEqual({...c.all},{n:7,ready:2});assert.deepEqual({...c.plots},{n:3,ready:1});assert.deepEqual({...c.workshops},{n:1,ready:1});assert.deepEqual({...c.other},{n:1,ready:0});
 assert.equal(m.listObjects(null,catalog,t).length,0);
});
test('mini-map transform is uniform, fits the land and round-trips a tap to the world',()=>{
 for(const G of [12,20,32]){
  const T=m.miniTransform(G,172,92),corners=[m.iso(0,0),m.iso(G,0),m.iso(G,G),m.iso(0,G)];
  for(const p of corners){const x=T.ox+p.x*T.k,y=T.oy+p.y*T.k;assert.ok(x>=0&&x<=172&&y>=0&&y<=92,`corner inside for G=${G}`)}
  const w=m.miniToWorld(T,T.ox+123*T.k,T.oy+456*T.k);assert.ok(Math.abs(w.x-123)<1e-9&&Math.abs(w.y-456)<1e-9);
 }
});
test('a tap on the mini-map centres the camera on that world point',()=>{
 const G=20,T=m.miniTransform(G,172,92),px=T.ox+0*T.k,py=T.oy+(G*18)*T.k; // middle of the land
 const q=m.miniToWorld(T,px,py),c=m.clampWorldPoint(G,q.x,q.y),pan=m.panToCenter(400,800,{x:200,y:140},.5,c.x,c.y);
 assert.ok(Math.abs(200+pan.x+c.x*.5-200)<1e-9);assert.ok(Math.abs(140+pan.y+c.y*.5-400)<1e-9);
});
