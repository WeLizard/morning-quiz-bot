const {test}=require('node:test');
const assert=require('node:assert/strict');
const path=require('node:path');
const {pathToFileURL}=require('node:url');
const load=()=>import(pathToFileURL(path.join(__dirname,'../../qw_farm/static/village_bulletin.js')).href);

test('missing sources and unimplemented events do not become news',async()=>{
 const {entries}=await load();
 assert.deepEqual(entries(null,0),[]);
 assert.deepEqual(entries({merchant_view:{active:false},festival:{past:[{name:'Старый праздник'}]},village_build:{projects:[{id:'future',name:'Трактир',status:'soon'}]}},0),[]);
});

test('bulletin reads only the supplied farm projection, including a visited farm',async()=>{
 const {entries}=await load(),now=1700000000;
 const me={id:25,merchant_view:{active:false,next_at:now+86400},festival:{current:{name:'Осенняя ярмарка',phase:'fair',host:'Агата'}},village_build:{projects:[
  {id:'stalls',name:'Торговые ряды',status:'collecting',stage:1,need:{wood:10},got:{wood:4}},
  {id:'tavern',name:'Трактир',status:'working',stage:0,work_until:now+3600},
  {id:'greenhouse',name:'Оранжерея',status:'done'},
 ]}};
 const before=JSON.stringify(me),news=entries(me,now);
 assert.deepEqual(news.map(n=>n.id),['merchant','festival','build:stalls','build:tavern','build:greenhouse']);
 assert.match(news[0].text,/Приедет через/);
 assert.match(news[1].text,/Осенняя ярмарка/);
 assert.match(news[2].text,/каркас · 40%/);
 assert.match(news[3].text,/котлован · готово через 1 ч/);
 assert.match(news[4].text,/готово/);
 assert.equal(JSON.stringify(me),before);
 assert.equal(news.some(n=>/Кая|Зверушка/.test(n.source)),false);
});

test('current merchant and upcoming festival use server schedule',async()=>{
 const {entries}=await load(),now=1700000000;
 const news=entries({merchant_view:{active:true,closes_at:now+7200},festival:{upcoming:{soon:true,name:'Масленица',starts_at:now+86400}}},now);
 assert.match(news[0].text,/Сорока на площади\. Уезжает через 2 ч/);
 assert.match(news[1].text,/Скоро: Масленица/);
 assert.equal(entries({festival:{upcoming:{soon:false,name:'Масленица',starts_at:now+86400}}},now).length,0);
 const unfinished=entries({festival:{current:{name:'Спасы',phase:'fair'},fair:{todo:true}}},now);
 assert.match(unfinished[0].text,/Спасы/);assert.doesNotMatch(unfinished[0].text,/задания|открыты/);
});

test('renderer is read only and preserves news as text nodes',async()=>{
 const {renderBulletin}=await load();
 const node=(tag,text,cls)=>({tag,text,cls,children:[],dataset:{},append(...n){this.children.push(...n);},setAttribute(k,v){this[k]=v;},classList:{add(){}}});
 const h={el:node,card:(title,source)=>node('section',`${title} ${source}`,'card'),note:(text,p)=>p.append(node('p',text,'note'))};
 const p=node('main');renderBulletin(p,{village_build:{projects:[{id:'x',name:'<script>test</script>',status:'done'}]}},0,h);
 const list=p.children[1];assert.equal(list['aria-label'],'Деревенские вести');
 assert.match(list.children[0].text,/<script>test<\/script>/);
 assert.equal(list.children[0].children[0].tag,'p');
 assert.equal(JSON.stringify(p).includes('button'),false);
 const empty=node('main');renderBulletin(empty,null,0,h);assert.match(empty.children[1].children[0].text,/Свежих вестей пока нет/);
});
