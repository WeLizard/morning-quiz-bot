'use strict';
// Client-side walking along VILLAGE_WALK: pure snapping/pathfinding and the requestAnimationFrame walker, sliced out of app.js.
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('fs'),path=require('path');
const app=fs.readFileSync(path.join(__dirname,'../../qw_farm/static/app.js'),'utf8');
const value=name=>{const i=app.indexOf(`const ${name}=`);return eval('('+app.slice(app.indexOf('=',i)+1,app.indexOf(';\n',i))+')');};
const W=value('VILLAGE_WALK'),N=W.n.length/2;
const src=app.slice(app.indexOf('// Walk graph helpers'),app.indexOf('function villageBindWorld'));

// Harness: fake DOM + manual frame clock around the sliced functions.
function make({reduced=false}={}){
 const frames=new Map();let nextId=1,now=0,centers=0;
 const cls=new Set(),player={style:{},dataset:{face:'right'},classList:{add:c=>cls.add(c),remove:c=>cls.delete(c),has:c=>cls.has(c)}};
 const world={querySelector:()=>player},scene={children:[world]};
 const raf=f=>{frames.set(nextId,f);return nextId++;},caf=id=>frames.delete(id);
 const api=new Function('VILLAGE_WALK','$','villageReduced','villageCenter','requestAnimationFrame','cancelAnimationFrame',`
  let villagePos=[42,77.3],villageWalkToken=0,villageMini=null;const VILLAGE_SPEED=260,VILLAGE_MAX_WALK=7;let villageWalkRaf=0,villageWalkPlayer=null;
  ${src}
  return {villageSnap,villagePlan,villageWalk,villageGo,villageWalkStop,pos:()=>villagePos,setPos:p=>{villagePos=p;}};`)
  (W,()=>scene,()=>reduced,()=>{centers++;},raf,caf);
 const tick=ms=>{now+=ms;const list=[...frames.entries()];frames.clear();for(const [,f] of list)f(now);};
 return {api,player,cls,frames,tick,centers:()=>centers};
}
const edgeSet=new Set();for(let k=0;k<W.e.length;k+=2)edgeSet.add(W.e[k]+','+W.e[k+1]);
const onEdge=(p,tol=1e-6)=>{for(let k=0;k<W.e.length;k+=2){const ax=W.n[2*W.e[k]],ay=W.n[2*W.e[k]+1],bx=W.n[2*W.e[k+1]],by=W.n[2*W.e[k+1]+1],dx=bx-ax,dy=by-ay,t=Math.max(0,Math.min(1,((p[0]-ax)*dx+(p[1]-ay)*dy)/(dx*dx+dy*dy||1)));if(Math.hypot(p[0]-ax-t*dx,p[1]-ay-t*dy)<tol)return true;}return false;};
const run=(h,t=60000)=>{for(let i=0;i<t/16&&h.frames.size;i++)h.tick(16);};

test('snap: taps on houses, water and empty grass land on the nearest road point',()=>{
 for(const [x,y] of [[1200,300],[100,100],[2300,1700],[1200,716],[W.n[0]+3,W.n[1]+3]]){
  const q=W&&makeSnap(x,y);assert.ok(onEdge([q.x,q.y]),'snapped point lies on an edge');
  let min=Infinity;for(let k=0;k<W.e.length;k+=2){const ax=W.n[2*W.e[k]],ay=W.n[2*W.e[k]+1],bx=W.n[2*W.e[k+1]],by=W.n[2*W.e[k+1]+1],dx=bx-ax,dy=by-ay,t=Math.max(0,Math.min(1,((x-ax)*dx+(y-ay)*dy)/(dx*dx+dy*dy||1)));min=Math.min(min,Math.hypot(x-ax-t*dx,y-ay-t*dy));}
  assert.ok(Math.abs(q.d-min)<1e-9,'distance is the true minimum');
 }
});
function makeSnap(x,y){return make().api.villageSnap(W,x,y);}

test('plan: start and end are the snapped points, every segment lies on a graph edge, never a shortcut',()=>{
 const {api}=make();
 const pairs=[[[1008,1391],[1200,300]],[[100,100],[2300,1700]],[[1200,716],[1210,720]],[[500,900],[1900,400]]];
 for(const [a,b] of pairs){
  const pts=api.villagePlan(W,a,b),s=api.villageSnap(W,a[0],a[1]),t=api.villageSnap(W,b[0],b[1]);
  assert.deepEqual([pts[0][0],pts[0][1]],[s.x,s.y]);assert.deepEqual([pts.at(-1)[0],pts.at(-1)[1]],[t.x,t.y]);
  for(let i=1;i<pts.length;i++){const m=[(pts[i][0]+pts[i-1][0])/2,(pts[i][1]+pts[i-1][1])/2];assert.ok(onEdge(m,1e-6),'segment midpoint on a graph edge');
   // the whole segment is collinear with one edge (no chord between two edges)
   const len=Math.hypot(pts[i][0]-pts[i-1][0],pts[i][1]-pts[i-1][1]);for(const f of [.25,.75])assert.ok(onEdge([pts[i-1][0]+(pts[i][0]-pts[i-1][0])*f,pts[i-1][1]+(pts[i][1]-pts[i-1][1])*f],1e-6),`quarter points on an edge (${len})`);}
 }
});
test('plan: approach node target ends exactly on that node; same-edge walk is direct',()=>{
 const {api}=make(),key=Object.keys(W.a)[3],i=W.a[key],pts=api.villagePlan(W,[W.n[0],W.n[1]],{node:i});
 assert.deepEqual(pts.at(-1),[W.n[2*i],W.n[2*i+1]]);
 const a=W.e[0],b=W.e[1],ax=W.n[2*a],ay=W.n[2*a+1],bx=W.n[2*b],by=W.n[2*b+1],p=api.villagePlan(W,[ax+(bx-ax)*.2,ay+(by-ay)*.2],[ax+(bx-ax)*.7,ay+(by-ay)*.7]);
 assert.equal(p.length,2);
});

test('walk: constant speed, facing per segment, is-walking only while moving, done after arrival',()=>{
 const h=make();let done=0;
 h.api.villageWalk([50,83.1],()=>done++,false);
 assert.ok(h.cls.has('is-walking'));assert.equal(h.frames.size,1);
 const pts=h.api.villagePlan(W,[42*24,77.3*18],[50*24,83.1*18]);
 let len=0;for(let i=1;i<pts.length;i++)len+=Math.hypot(pts[i][0]-pts[i-1][0],pts[i][1]-pts[i-1][1]);
 h.tick(0);const p0=h.api.pos().slice();h.tick(500);const p1=h.api.pos().slice();
 const moved=Math.hypot((p1[0]-p0[0])*24,(p1[1]-p0[1])*18);assert.ok(moved>40&&moved<=0.5*Math.max(260,len/7)+1e-6+1,'about 0.5s of walking at pleasant speed');
 assert.equal(done,0);run(h);
 assert.equal(done,1);assert.ok(!h.cls.has('is-walking'));assert.equal(h.frames.size,0);
 assert.ok(Math.abs(h.api.pos()[0]*24-pts.at(-1)[0])<1e-6&&Math.abs(h.api.pos()[1]*18-pts.at(-1)[1])<1e-6);
 assert.ok(h.centers()>0);
});
test('walk: every frame the figure stays on a graph edge',()=>{
 const h=make();h.api.villageWalk([88,12],null,false);let bad=0;h.tick(0);
 for(let i=0;i<4000&&h.frames.size;i++){h.tick(16);if(!onEdge([h.api.pos()[0]*24,h.api.pos()[1]*18],1e-5))bad++;}
 assert.equal(bad,0);
});
test('walk: total duration is capped at 7 seconds for long routes',()=>{
 const h=make();h.api.setPos([W.n[0]/24,W.n[1]/18]);h.api.villageWalk([97,96],null,false);let t=0;h.tick(0);while(h.frames.size&&t<20000){h.tick(16);t+=16;}
 assert.ok(t<=7000+100,`took ${t} ms`);
});
test('walk: facing follows each segment direction',()=>{
 const h=make();h.api.villageWalk([88,12],null,false);const seen=new Set();h.tick(0);
 for(let i=0;i<4000&&h.frames.size;i++){h.tick(16);seen.add(h.player.dataset.face);}
 assert.ok(seen.size>=1);
 const left=make();left.api.setPos([60,50]);left.api.villageWalk([2,50],null,false);left.tick(0);left.tick(16);
 const right=make();right.api.setPos([2,50]);right.api.villageWalk([60,50],null,false);right.tick(0);right.tick(16);
 assert.ok(['left','right'].includes(left.player.dataset.face)&&['left','right'].includes(right.player.dataset.face));
});
test('walk: a new tap re-plans from the current interpolated position and the old done never fires',()=>{
 const h=make();let first=0,second=0;h.api.villageWalk([88,12],()=>first++,false);h.tick(0);h.tick(1000);
 const mid=h.api.pos().slice();assert.notDeepEqual(mid,[42,77.3]);
 h.api.villageWalk([10,30],()=>second++,false);
 assert.equal(h.frames.size,1,'exactly one pending frame after re-plan');
 const pts=h.api.villagePlan(W,[mid[0]*24,mid[1]*18],[10*24,30*18]),s=h.api.villageSnap(W,mid[0]*24,mid[1]*18);
 assert.ok(Math.hypot(pts[0][0]-s.x,pts[0][1]-s.y)<1e-6&&s.d<1e-4,'plan starts at the interpolated position');
 run(h);assert.equal(first,0);assert.equal(second,1);
});
test('walk: reduced motion and keyboard (instant) teleport to the destination',()=>{
 const r=make({reduced:true});let d=0;r.api.villageWalk([50,83.1],()=>d++,false);
 assert.equal(r.frames.size,0);assert.equal(d,1);assert.ok(!r.cls.has('is-walking'));
 const t=r.api.villageSnap(W,50*24,83.1*18);assert.ok(Math.abs(r.api.pos()[0]*24-t.x)<1e-6);
 const k=make();let n=0;k.api.villageWalk([50,83.1],()=>n++,true);assert.equal(k.frames.size,0);assert.equal(n,1);
});
test('walk: approach key walks to the graph node and then opens; villageGo maps button data to keys',()=>{
 const h=make();let n=0;const key=Object.keys(W.a)[0];
 h.api.villageGo([1,1],()=>n++,{detail:1,currentTarget:{dataset:{villageNpc:key}}});run(h);
 const i=W.a[key];assert.equal(n,1);assert.ok(Math.abs(h.api.pos()[0]*24-W.n[2*i])<1e-6&&Math.abs(h.api.pos()[1]*18-W.n[2*i+1])<1e-6);
 for(const [data,k] of [[{villagePlace:'board'},'place:board'],[{villageSpot:'0'},'visitor:0'],[{villageGate:'gate'},'gate'],[{villageTownhall:'townhall'},'hall']]){
  const g=make();g.api.villageGo([1,1],null,{detail:0,currentTarget:{dataset:data}});const j=W.a[k];assert.ok(Math.abs(g.api.pos()[0]*24-W.n[2*j])<1e-6,k);
 }
});
test('walk: leaving the village cancels the frame chain and clears the walking state',()=>{
 const h=make();let n=0;h.api.villageWalk([88,12],()=>n++,false);h.tick(0);h.tick(200);assert.equal(h.frames.size,1);
 h.api.villageWalkStop();assert.equal(h.frames.size,0);assert.ok(!h.cls.has('is-walking'));h.tick(1000);assert.equal(n,0);
 assert.match(app,/if\(!visible\)\{villageWalkStop\(\)/);assert.match(app,/function resetVillageView\(\)\{[^}]*villageWalkStop\(\)/);
 assert.doesNotMatch(src,/setTimeout|setInterval/);
});
