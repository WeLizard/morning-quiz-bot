'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');

const root=path.resolve(__dirname,'../..');
const physics=fs.readFileSync(path.join(root,'qw_farm/static/ballista-physics.js'),'utf8').replace(/export /g,'');
const budget=fs.readFileSync(path.join(root,'qw_farm/static/construction.js'),'utf8').match(/export function cashBonusText\([^]*?\n\}/)[0].replace('export ','');
const client=budget+'\n'+fs.readFileSync(path.join(root,'qw_farm/static/ballista-game.js'),'utf8').replace(/^import .*;\r?\n/gm,'').replace(/export /g,'');
const context={Number,Array,Object,Math,Boolean,String,Set,Map,Promise};
vm.createContext(context);
vm.runInContext(`${physics}\n${client}\nglobalThis.api={trajectory,shotResult,replay,ballistaLogValid,ballistaResultText};`,context);
const api=context.api;
const fixtures=JSON.parse(fs.readFileSync(path.join(root,'tests/fixtures/farm_ballista.json'),'utf8'));

test('JS replay agrees with server fixture for all five throws',()=>{
 for(const fixture of fixtures){
  const result=api.replay(fixture.plan,fixture.log);
  assert.deepEqual({score:result.score,hits:result.hits,durations:[...result.durations]},
    {score:fixture.score,hits:fixture.hits,durations:fixture.durations},fixture.seed);
  assert.equal(api.ballistaLogValid(fixture.plan,fixture.log),true);
 }
});

test('negative wind and roof bounce use Python integer floor semantics',()=>{
 const roof={left:0,right:1100,y:360};
 const path=api.trajectory(51000,460,-2,roof);
 assert.deepEqual([...path[0]],[60,500]);
 assert.ok(path.some(([x,y])=>x>=0&&x<=1100&&y===360));
 const target={x:430,y:250,radius:36,wind:-2,roof:{left:420,right:560,y:360}};
 assert.equal(api.shotResult(target,31000,900).hit,true);
});

test('retry log rejects incomplete ordering, invalid range and duplicates',()=>{
 const {plan,log}=fixtures[0];
 assert.equal(api.ballistaLogValid(plan,log.slice(0,3)),true);
 assert.equal(api.ballistaLogValid(plan,[...log,log[0]]),false);
 assert.equal(api.ballistaLogValid(plan,[[15000,200,0]]),false);
 assert.equal(api.ballistaLogValid(plan,[[75001,200,250]]),false);
 assert.equal(api.ballistaLogValid(plan,[log[0],[31000,900,700]]),false);
});

test('result copy reflects practice and server paid reward',()=>{
 assert.match(api.ballistaResultText({hits:4,stars:2,score:812,practice:true,reward:0}),/Тренировка/);
 assert.match(api.ballistaResultText({hits:5,stars:3,score:994,practice:false,reward:12,reward_kind:'vigour'}),/бодрости/);
});
