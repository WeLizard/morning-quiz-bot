const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../../qw_farm/static/app.js'),'utf8');

const projectMissingSource=source.slice(source.indexOf('function projectMissing'),source.indexOf('function projectHasAll'));
function projectNeeds(entry,catalogNeeds){
 const context={entry,projectStage:()=>({needs:catalogNeeds})};vm.createContext(context);
 vm.runInContext(`${projectMissingSource}\nglobalThis.result=projectMissing('lake_pier',entry)`,context);
 return JSON.parse(JSON.stringify(context.result));
}

test('the v1 reserved pier keeps its wheat and flour requirements until release or delivery',()=>{
 assert.deepEqual(projectNeeds({stage:0,reserved:{wheat:2},legacy_needs:{wheat:6,flour:2}},{wood:6}),{wheat:6,flour:2});
 assert.deepEqual(projectNeeds({stage:0,reserved:{}},{wood:6}),{wood:6});
 assert.deepEqual(projectNeeds({stage:1,reserved:{},legacy_needs:{wheat:6,flour:2}},{wood:4}),{wood:4});
});

test('the barn materials card and progress summary share the legacy-aware requirements',()=>{
 const barnStart=source.indexOf('function renderProjectBarnShelf('),barnEnd=source.indexOf('\nfunction renderOrders(',barnStart);
 const barn=source.slice(barnStart,barnEnd),summaryStart=source.indexOf('function projectStageSummary('),summaryEnd=source.indexOf('\nfunction renderProjectHouse(',summaryStart);
 const summary=source.slice(summaryStart,summaryEnd);
 assert.match(barn,/needs=projectMissing\(id,entry\)/);
 assert.doesNotMatch(barn,/stage\?\.needs/);
 assert.match(summary,/needs=projectMissing\(project,entry\)/);
 assert.match(source,/Отложи нужное на складе/);
 assert.doesNotMatch(source,/Отложи урожай для строительства дома|Урожай для проектов отправляется мастерам/);
});

test('wood route stays catalog-driven and the wood item has an SVG icon',()=>{
 const forestStart=source.indexOf('function renderForest('),forestEnd=source.indexOf('\nfunction renderLake(',forestStart);
 const tripsStart=source.indexOf('function renderTrips('),tripsEnd=source.indexOf('\nfunction renderSecrets(',tripsStart);
 const icons=fs.readFileSync(path.join(__dirname,'../../qw_farm/static/icons.svg'),'utf8');
 assert.match(source.slice(forestStart,forestEnd),/renderTrips\(p,'forest'\)/);
 assert.match(source.slice(tripsStart,tripsEnd),/Object\.values\(S\.catalog\.routes\)\.filter\(r=>routeCategory\(r\)===category\)/);
 assert.match(icons,/<symbol id="wood"/);
 assert.match(source,/Рыбачить можно прямо с берега[\s\S]*Причал строится у Филиныча/);
});
