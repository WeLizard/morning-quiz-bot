'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');

const root=path.resolve(__dirname,'../..');
const source=fs.readFileSync(path.join(root,'qw_farm/static/santa-battle-engine.js'),'utf8').replace(/export /g,'');
const context={Math,Number,Array,Object,String,Boolean,Error};
vm.createContext(context);
vm.runInContext(`${source}\nglobalThis.api={newState,act,actor,legal,replay,stars,BATTLES,HEROES};`,context);
const api=context.api;
const fixtures=JSON.parse(fs.readFileSync(path.join(root,'tests/fixtures/farm_santa_battle.json'),'utf8'));
const plain=value=>JSON.parse(JSON.stringify(value));
const clone=value=>JSON.parse(JSON.stringify(value));

test('JS engine produces the Python events, state and result for every fixture',()=>{
 assert.equal(fixtures.length,9);
 for(const fixture of fixtures){
  const state=api.newState(fixture.plan);
  const events=fixture.log.map(entry=>plain(api.act(fixture.plan,state,clone(entry))));
  assert.deepEqual(events,fixture.events,fixture.seed);
  assert.deepEqual(plain(state),fixture.state,fixture.seed);
  assert.deepEqual(plain(api.replay(fixture.plan,clone(fixture.log))),fixture.result,fixture.seed);
 }
});

test('the hero order and the legal moves match the Python rules',()=>{
 const plan=fixtures[0].plan;
 const state=api.newState(plan);
 assert.equal(api.actor(state),'player');
 const moves=Object.fromEntries(api.legal(state).map(([a,t])=>[a,plain(t)]));
 assert.deepEqual(moves.snowball,['krampus']);
 assert.deepEqual(moves.wall,[]);
 assert.deepEqual(moves.pie,['player','ded_moroz','snegurochka']);
 assert.equal(moves.staff,undefined);
});

test('illegal entries and logs are refused like on the server',()=>{
 const plan=fixtures[0].plan;
 const bad=[
  [['ded_moroz','staff','krampus',null],'actor'],
  [['player','staff','krampus',null],'action'],
  [['player','wall','krampus',null],'target'],
  [['player','wall',null,100],'press'],
  [['player','snowball','krampus',1201],'press'],
  [['player','snowball','krampus',true],'press'],
  [['player','snowball','krampus',1.5],'press'],
  [['player','snowball','krampus'],'entry'],
 ];
 for(const [entry,why] of bad)assert.throws(()=>api.act(plan,api.newState(plan),entry),{message:why});
 assert.throws(()=>api.replay(plan,[]),{message:'log'});
 assert.throws(()=>api.replay(plan,[['player','snowball','krampus',null]]),{message:'unfinished'});
 const done=api.newState(plan);
 done.hp.krampus=5;
 api.act(plan,done,['player','snowball','krampus',null]);
 assert.equal(done.outcome,'win');
 assert.equal(api.stars(done),3);
 assert.throws(()=>api.act(plan,done,['player','snowball','krampus',null]),{message:'over'});
});
