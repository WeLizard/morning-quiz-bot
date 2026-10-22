const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');

async function scene(overrides={}){
 const {FarmScene}=await import('../../qw_farm/static/scene.js');
 const s=Object.create(FarmScene.prototype);Object.assign(s,{motion:true,time:100,dirty:false,...overrides});
 return {s,FarmScene};
}

test('feeding swans starts a short ramp: out to the shore, nibble, back, then the hook clears itself',async()=>{
 const {s}=await scene();const {SWAN_FEED_SECONDS}=await import('../../qw_farm/static/scene.js');
 assert.equal(s.swanFeedState(100),null,'no feeding, no override');
 s.feedSwans();assert.equal(s.swanFeedAt,100);assert.equal(s.dirty,true);
 assert.equal(s.swanFeedState(100).w,0);
 const mid=s.swanFeedState(101);assert.ok(mid.w>0&&mid.w<1&&!mid.eating);
 const eat=s.swanFeedState(103.5);assert.equal(eat.w,1);assert.equal(eat.eating,true);
 const back=s.swanFeedState(100+SWAN_FEED_SECONDS-1);assert.ok(back.w>0&&back.w<1&&!back.eating);
 assert.equal(s.swanFeedState(100+SWAN_FEED_SECONDS),null);assert.equal(s.swanFeedAt,null);
});

test('reduced motion ignores the feeding reaction and the shore stays beside the lake',async()=>{
 const {s}=await scene({motion:false});s.feedSwans();assert.equal(s.swanFeedAt,undefined);assert.equal(s.swanFeedState(100),null);
 const shore=s.swanShore({x:10,y:20});assert.ok(Number.isFinite(shore.x)&&Number.isFinite(shore.gx)&&[1,-1].includes(shore.dir));
});

test('the swans come to the real bank: inside the outline, near its edge, on the farm side, clear of the pier bay',async()=>{
 const {s}=await scene();const p=s.pondCenter.call({grid:()=>8}),{rx,ry}=s.lakeSize();
 const shore=s.swanShore(p);
 for(const [x,y,lo,hi,out] of [[shore.x,shore.y,.7,.9,1.36],[shore.gx,shore.gy,.82,.98,1.15]]){
  const dx=(x-p.x)/rx,dy=(y-p.y)/ry;assert.ok(s.inLake(dx,dy),'on the water');
  const edge=s.inLake(dx*out,dy*out);assert.equal(edge,false,'the bank is close');
  const m=Math.hypot(dx,dy);assert.ok(m>lo*.6&&m<hi,'radius '+m);
 }
 assert.ok(shore.gx>p.x+rx*.5&&Math.abs(shore.gy-p.y)<ry*.5,'right bank, not the pier bay above');
 assert.equal(shore.dir,1,'facing the bank');
});

test('fed state comes from the server projection (survives a reload), not from the animation',async()=>{
 const {s}=await scene({serverOffset:0});
 s.farm={swans:{next_at:Date.now()/1000+600,left:2,unlocked:true}};assert.equal(s.swansFed(),true);
 s.farm={swans:{next_at:Date.now()/1000-1,left:2,unlocked:true}};assert.equal(s.swansFed(),false);
 s.farm={};assert.equal(s.swansFed(),false);
 const eat=s.swanFeedState.call(Object.assign(Object.create(Object.getPrototypeOf(s)),{swanFeedAt:0}),4);
 assert.ok(eat.eating&&eat.eaten>0&&eat.eaten<1);
});

test('the swan card has its own icon in the farm sprite sheet',()=>{
 const app=fs.readFileSync(path.join(__dirname,'../../qw_farm/static/app.js'),'utf8');
 assert.match(app,/card\('Лебеди',[^;]*'swan'\)/);
 const icons=fs.readFileSync(path.join(__dirname,'../../qw_farm/static/icons.svg'),'utf8');
 for(const id of ['swan','golden_crucian','tench','catfish'])assert.match(icons,new RegExp(`<symbol id="${id}" viewBox="0 0 48 48">`));
 assert.doesNotMatch(icons,/data:image/);
});

test('the lake panel wires feed_swans through the server command and shows server numbers only',()=>{
 const app=fs.readFileSync(path.join(__dirname,'../../qw_farm/static/app.js'),'utf8');
 assert.match(app,/function renderSwans\(p\)/);
 assert.match(app,/renderSwans\(p\);\s*renderTrips\(p,'fishing'\)/);
 assert.match(app,/command\('feed_swans'\)\.then\(ok=>\{if\(ok\)scene\.feedSwans/);
 assert.match(app,/due\(S\.me\?\.swans\?\.next_at\)/);
 assert.doesNotMatch(app,/feed_swans',\{[^}]/,'the client sends no numbers');
});

test('after Moscow midnight the lake card recounts the daily limit without a new projection',async()=>{
 const {swansLeft}=await import('../../qw_farm/static/scene_map.js');
 const day=20000,at=(d,h)=>d*86400-10800+h*3600;
 const w={day,left:0,daily_limit:3};
 assert.equal(swansLeft(w,at(day,23)),0,'same Moscow day: the server number stands');
 assert.equal(swansLeft(w,at(day+1,0)+1),3,'next Moscow day: the full limit');
 assert.equal(swansLeft({day,left:1,daily_limit:3},at(day+1,1)),3);
 assert.equal(swansLeft({left:2,daily_limit:3},at(day+1,1)),2,'an old projection without a day keeps the server number');
 const app=fs.readFileSync(path.join(__dirname,'../../qw_farm/static/app.js'),'utf8');
 assert.match(app,/swansLeft\(w,t\)<=0/);
 assert.match(app,/\$\{swansLeft\(w,now\(\)\)\} из/);
});
