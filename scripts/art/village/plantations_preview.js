// Wave 1 review artwork only. Shared farm geometry; no runtime registration.
import {makeS, B, P} from './common.js';
import {SvgCtx} from './svg_ctx.js';
import {fieldsCard} from './fields_card.js';

// The shared recorder predates rotated plant leaves. Keep this correction local.
class PreviewCtx extends SvgCtx {
  rotate(a){this.transform(Math.cos(a),Math.sin(a),-Math.sin(a),Math.cos(a),0,0)}
  ellipse(x,y,rx,ry,rot=0,a0=0,a1=Math.PI*2,ccw=false){
    if(!rot)return super.ellipse(x,y,rx,ry,0,a0,a1,ccw);
    const p=a=>[x+rx*Math.cos(a)*Math.cos(rot)-ry*Math.sin(a)*Math.sin(rot),y+rx*Math.cos(a)*Math.sin(rot)+ry*Math.sin(a)*Math.cos(rot)];
    const a=p(0),b=p(Math.PI),deg=rot*180/Math.PI,n=v=>+v.toFixed(3);
    this.d+=`M${a.map(n).join(' ')}A${n(rx)} ${n(ry)} ${n(deg)} 1 0 ${b.map(n).join(' ')}A${n(rx)} ${n(ry)} ${n(deg)} 1 0 ${a.map(n).join(' ')}Z`;
  }
  arc(x,y,r,a,b,ccw=false){this.ellipse(x,y,r,r,0,a,b,ccw)}
  rect(x,y,w,h){this.moveTo(x,y);this.lineTo(x+w,y);this.lineTo(x+w,y+h);this.lineTo(x,y+h);this.closePath()}
  fillRect(x,y,w,h){this.beginPath();this.rect(x,y,w,h);this.fill()}
}
const C={grass:'#bfd39e',grass2:'#c6d9a9',soil:'#b39572',earth:'#a58965',wood:'#a68b60',leaf:'#79a85f',deep:'#608750',light:'#a9c77b',grape:'#7b5f9a',snow:'#e9eee7',snowShade:'#c5d5d2'};
const poly=(s,p,col)=>s.poly(p.map(([x,y])=>({x,y})),col);
function art(name,w,h,draw){const c=new PreviewCtx(name),s=makeS(c);s.scale=1;s.catalog={crops:{}};draw(s,c);return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${w} ${h}" role="img" aria-label="${name}"><title>${name}</title>${c.svg()}</svg>`}
function at(s,x,y,k,draw){s.c.save();s.c.translate(x,y);s.c.scale(k,k);draw();s.c.restore()}
function leaf(s,x,y,a,len,w,col=C.leaf){s.leaf(x,y,a,len,w,col)}
function bunch(s,x,y,k=1,ripe=true){
  for(const [dx,dy,r] of [[-3,0,2.7],[3,0,2.7],[-4,4,2.7],[1.7,4.5,2.9],[-1,8.4,2.5],[0,12,1.8]])s.ellipse(x+dx*k,y+dy*k,r*k,r*k,ripe?C.grape:C.light);
  s.ellipse(x-3.6*k,y-.7*k,.8*k,.8*k,ripe?'#baa1cb':'#d8e7a7');
}
function shoot(s,x,y,k=1){
  s.line(x,y,x,y-11*k,C.deep,1.1*k);
  leaf(s,x,y-3*k,-2.6,9*k,2.7*k,'#c2d792');leaf(s,x,y-5*k,-.62,9*k,2.7*k,'#b0d17e');leaf(s,x,y-7*k,-1.48,6*k,1.5*k,'#e0e7ae');
}
function vine(s,x,y,stage){
  const young=stage==='young',winter=stage==='winter';
  s.shadow(x,y,9,3);s.line(x,y,x+1,y-(young?11:23),'#8f7556',young?1.5:2.5);
  if(winter){
    s.line(x,y-16,x-11,y-24,'#8f7556',1.9);s.line(x,y-18,x+12,y-26,'#8f7556',1.9);
    s.line(x-9,y-22,x-11,y-29,'#8f7556',1.2);s.line(x+8,y-23,x+9,y-30,'#8f7556',1.2);
    s.ellipse(x,y,11,3,C.snow);s.line(x-10,y-25,x-3,y-20,C.snow,2.2);return;
  }
  if(young){leaf(s,x,y-8,-2.6,9,3);leaf(s,x+1,y-11,-.4,9,3,'#91b86c');return}
  s.line(x,y-22,x-12,y-25,'#8f7556',1.3);s.line(x,y-22,x+13,y-24,'#8f7556',1.3);
  for(const [dx,dy,a] of [[-12,-25,-2.7],[-7,-25,-1.6],[0,-24,-2.2],[3,-25,-.7],[11,-24,-.4]])leaf(s,x+dx,y+dy,a,11,4,dx<0?'#82ab65':C.leaf);
  bunch(s,x-6,y-20,.63,stage==='ripe');bunch(s,x+7,y-19,.6,stage==='ripe');
}
function teaBush(s,x,y,stage){
  const young=stage==='young';s.shadow(x,y,young?7:15,young?2:4);
  s.line(x,y,x,y-(young?6:11),'#8f7556',1.8);
  if(young){leaf(s,x,y-5,-2.6,9,3);leaf(s,x,y-7,-.5,9,3,'#91b86c');return}
  s.ellipse(x,y-9,15,8,C.deep);s.ellipse(x-6,y-13,9,6,'#79a35e');s.ellipse(x+6,y-13,9,6,'#719b58');
  for(const dx of [-9,-3,4,10])leaf(s,x+dx,y-10-(dx%3),-1.9,9,2.8,dx<0?'#8fb46b':'#7fa860');
  if(stage==='ripe'){shoot(s,x-6,y-15,.64);shoot(s,x+6,y-14,.64)}
}
function hectareDraw(s,kind,stage){
  const winter=stage==='winter';
  B.ground(s,-.25,-.25,8.25,8.25,winter?C.snowShade:'#b7c794');
  // Eight raised earth strips, eight individual bushes per strip. No decorative extras.
  for(let row=0;row<8;row++){
    B.ground(s,.1,row+.14,7.9,row+.86,winter?C.snow:C.soil);
    B.L(s,.1,row+.86,0,7.9,row+.86,0,winter?'#b9cbc6':C.earth,1.1);
  }
  const empty=kind==='empty',spriteId=`plant-${kind}-${stage}`;
  if(!empty){
    const glyph=new PreviewCtx(spriteId),gs=makeS(glyph);
    (kind==='vineyard'?vine:teaBush)(gs,0,0,stage);
    s.c.defs.push({id:spriteId,svg:()=>`<g id="${spriteId}">${glyph.svg()}</g>`});
  }
  // Back-to-front rows: trellis wires precede the supported plants of that row.
  for(let row=0;row<8&&!empty;row++){
    if(kind==='vineyard'){
      for(const z of [15,27])B.L(s,.12,row+.5,z,7.88,row+.5,z,'#a99e7d',.8);
      for(const x of [.12,4,7.88])B.L(s,x,row+.5,0,x,row+.5,31,C.wood,2);
    }
    for(let col=0;col<8;col++){
      const p=P(col+.5,row+.5);s.c.group(`plant row-${row} column-${col}`);
      s.c.out.push(`<use href="#${spriteId}" x="${p.x}" y="${p.y}"${s.c.tr()}/>`);s.c.end();
    }
  }
  // Front stone boundary remains on the ground plane.
  B.L(s,-.25,8.25,0,8.25,8.25,0,winter?'#b8c9c4':'#cfc49b',3);
  B.L(s,8.25,-.25,0,8.25,8.25,0,winter?'#a5bdb8':'#b9ae88',3);
}
function hectare(kind,stage){return art(`${kind}-${stage}`,640,370,(s)=>at(s,320,35,1,()=>hectareDraw(s,kind,stage)))}

// Preview uses the runtime renderer, including catalogue/placement thumbnails.
function factoryDraw(s,x=0,y=0){B.drawBuilding(s,{type:'tea_factory',x,y,w:2,h:2,level:1,jobs:[]})}
function factory(){return art('Чайная фабрика · L32',380,300,(s)=>at(s,174,100,2.25,()=>factoryDraw(s)))}

function farm(newFactory=false){return art(newFactory?'Ферма с чайной фабрикой':'Действующие рисунки фермы',640,400,(s)=>{
  poly(s,[[0,0],[640,0],[640,400],[0,400]],'#dce8c9');
  at(s,310,68,.93,()=>{
    for(let y=0;y<8;y++)for(let x=0;x<8;x++)s.tile(x,y,(x+y)%2?C.grass:C.grass2);
    B.ground(s,0,3.1,8,3.75,'#d6c69f');B.ground(s,3.2,0,3.85,8,'#d6c69f');
    B.drawBuilding(s,{type:'house',x:0,y:0,w:3,h:3,jobs:[]});
    B.drawBuilding(s,{type:'barn',x:4,y:0,w:3,h:3,jobs:[]});
    for(let y=4;y<7;y++)for(let x=0;x<3;x++){s.tile(x,y,C.soil,C.earth);for(let j=0;j<2;j++)for(let i=0;i<2;i++){const p=P(x+.25+i*.45,y+.2+j*.4);s.plant(p.x,p.y,'wheat',1,0)}}
    if(newFactory)factoryDraw(s,4.2,4.2);else B.drawBuilding(s,{type:'teahouse',x:4.2,y:4.2,w:3,h:3,jobs:[]});
    B.rail(s,0,8,3,8,9,'#b79f72');B.rail(s,4,8,8,8,9,'#b79f72');
  });
})}

function card(){return art('Плантации · карточка 160×68',160,68,(s)=>{
  poly(s,[[0,0],[160,0],[160,68],[0,68]],'#dce8c9');s.ellipse(134,12,8,8,'#f7d579');
  poly(s,[[0,31],[40,23],[90,28],[132,20],[160,27],[160,68],[0,68]],'#a9c597');
  poly(s,[[0,46],[65,26],[160,43],[160,68],[0,68]],'#c4c78f');
  for(let i=0;i<4;i++){
    const x=12+i*32;s.line(x-15,69,x+35,35,'#a98965',6);
    for(let j=0;j<3;j++){const xx=x-8+j*15,yy=62-j*10;at(s,xx,yy,.38,()=>i<2?vine(s,0,0,'ripe'):teaBush(s,0,0,'ripe'))}
  }
  s.line(3,36,74,22,'#ab9672',1.1);for(const x of [8,30,52,74])s.line(x,35-(x-3)*.2,x,29-(x-3)*.2,'#a68b60',1.5);
})}

function icon(id){return art(id,64,64,(s)=>{
  if(id==='tea_leaf'){shoot(s,31,51,2.3);return}
  if(id==='wine_zero'){
    poly(s,[[25,8],[38,8],[38,23],[44,30],[44,56],[20,56],[20,30],[25,23]],'#79917b');
    poly(s,[[25,28],[39,28],[40,54],[23,54],[23,32]],'#8c759e');
    poly(s,[[25,8],[38,8],[38,16],[25,16]],'#b59a68');
    poly(s,[[23,34],[41,34],[41,49],[23,49]],'#f3e8c6');
    s.c.fillStyle='#6b527f';s.c.font='700 11px system-ui';s.c.textAlign='center';s.c.fillText('0 %',32,45);s.line(24,27,24,53,'#b6c9ad',1.6);return;
  }
  if(id==='raisin'){
    poly(s,[[10,28],[51,28],[48,53],[15,53]],'#c7a679');s.ellipse(31,28,21,9,'#e4cd9e');
    for(const [x,y,a] of [[20,26,-.3],[31,24,.3],[41,29,-.5],[25,32,.6],[34,33,-.4],[18,32,.2],[43,24,.6]]){s.c.beginPath();s.c.ellipse(x,y,4,2.7,a,0,Math.PI*2);s.c.fillStyle='#866351';s.c.fill();s.line(x-1,y-1,x+1,y+1,'#ba9370',.8)}
    s.line(15,41,48,41,'#ae8c60',1);return;
  }
  const green=id==='green_tea';
  poly(s,[[14,19],[23,9],[44,9],[50,19],[48,55],[15,55]],green?'#a9b780':'#ae8a6c');
  poly(s,[[14,19],[23,9],[24,55],[15,55]],green?'#91a369':'#95765d');
  poly(s,[[23,9],[44,9],[50,19],[22,19]],'#d9c59a');s.line(23,12,43,12,'#aa9270',1);
  poly(s,[[25,27],[44,27],[44,46],[25,46]],'#f3e9ce');
  leaf(s,31,42,-1.25,13,4,green?'#739750':'#6e5847');leaf(s,33,39,-2.7,8,2.7,green?'#9ab76c':'#99744e');
})}

export async function render(){
  if(!B.BUILDING_TYPES.includes('tea_factory'))throw new Error('Runtime tea_factory renderer is missing');
  const assets={card:card(),fields:fieldsCard().svg,reference:farm(false),context:farm(true),factory:factory()};
  for(const kind of ['vineyard','tea_garden'])for(const stage of ['young','adult','ripe'])assets[`${kind}-${stage}`]=hectare(kind,stage);
  assets['vineyard-winter']=hectare('vineyard','winter');
  assets['plantation-empty']=hectare('empty','empty');
  for(const id of ['tea_leaf','green_tea','black_tea','wine_zero','raisin'])assets[id]=icon(id);
  const bounds={};
  const probe=document.createElement('div');probe.style.cssText='position:absolute;left:-10000px;top:0';document.body.append(probe);
  for(const [name,svg] of Object.entries(assets)){
    probe.innerHTML=svg;const node=probe.firstElementChild,b=node.getBBox(),v=node.viewBox.baseVal;
    bounds[name]={x:b.x,y:b.y,width:b.width,height:b.height,viewBox:[v.x,v.y,v.width,v.height],intentional_edge_clip:name==='fields'||name==='card'};
    if(!bounds[name].intentional_edge_clip&&(b.x<-.01||b.y<-.01||b.x+b.width>v.width+.01||b.y+b.height>v.height+.01))throw new Error(`Artwork exceeds viewBox: ${name}`);
  }
  probe.remove();
  const cv=document.createElement('canvas');cv.width=380;cv.height=300;
  const native=makeS(cv.getContext('2d'));at(native,174,100,2.25,()=>factoryDraw(native));
  const thumb=native.thumb({type:'tea_factory',w:2,h:2});
  if(!thumb||thumb.width<40||thumb.height<30)throw new Error('Runtime tea_factory thumbnail is blank');
  return {assets,bounds,native_factory:cv.toDataURL('image/png'),native_thumbnail:thumb.toDataURL('image/png'),
    geometry:{tile:[36,18],rows:8,columns:8,plants_per_hectare:64,factory_footprint:[2,2],factory_drawn_ground:[2,2.8*2/3],factory_local_scale:2/3,factory_wall:[.18,.18,2.55,1.85],roof_eave_z:39,roof_rise:25,card:[160,68]}};
}
