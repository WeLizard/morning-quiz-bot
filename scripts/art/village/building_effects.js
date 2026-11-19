// Review-only construction benefits. Existing farm primitives and the village's
// generated coordinate system; never installed by build_village.py.
import {B, P, makeS} from './common.js';
import {SvgCtx} from './svg_ctx.js';
import {render as village} from './village.js';

const WOOD='#b48f66', DARK='#8a6c4c', LIGHT='#c9a57a', CREAM='#f4ede0', GOLD='#e8c25a';

export function buildingEffects(layout){
  const {matrix,sites}=layout, pieces={}, placements={};
  const world=(x,y,z=0)=>{const p=P(x,y,z);return [matrix[0]*p.x+matrix[4],matrix[3]*p.y+matrix[5]];};
  function piece(id,foot,height,site,gate,draw){
    const c=new SvgCtx(id.replace(/[^a-z]/g,'')),s=makeS(c);
    draw(s);
    const [x0,y0,x1,y1]=foot;
    const corners=[[x0,y0],[x1,y0],[x1,y1],[x0,y1]].flatMap(([x,y])=>[world(x,y),world(x,y,height)]);
    const xs=corners.map(p=>p[0]),ys=corners.map(p=>p[1]);
    const box=[Math.floor(Math.min(...xs)-12),Math.floor(Math.min(...ys)-12),
      Math.ceil(Math.max(...xs)-Math.min(...xs)+24),Math.ceil(Math.max(...ys)-Math.min(...ys)+24)];
    const body=`<g transform="matrix(${matrix.join(' ')})">${c.svg()}</g>`;
    pieces[id]={box,body};
    placements[id]={site,gate,box,footprint:foot,height,anchor:world((x0+x1)/2,y1),
      rendering:'world-vector-live-layer',interactive:false};
  }
  // A shield and a wheat ear, mapped onto the same vertical face as its support.
  // The neutral farm emblem is reused on the bench and flag. Player names and
  // favorite dishes are runtime text/icons, never baked into shared art.
  function crest(s,point,width=12,height=16){
    const q=(u,v)=>point((u-.5)*width,(v-.5)*height);
    s.poly([q(0,0),q(1,0),q(.94,.65),q(.5,1),q(.06,.65)],'#6f8f54',DARK,1);
    s.poly([q(.14,.12),q(.86,.12),q(.81,.61),q(.5,.85),q(.19,.61)],null,GOLD,.7);
    const a=q(.5,.73),b=q(.5,.27);s.line(a.x,a.y,b.x,b.y,GOLD,1);
    for(const [v,left] of [[.35,true],[.43,false],[.51,true],[.59,false]]){
      s.poly([q(.5,v+.06),q(left?.27:.73,v-.08),q(left?.31:.69,v+.05)],GOLD);
    }
  }
  const [tx,ty,tx1,ty1]=sites.tavern;
  const bench=[tx+.9,ty1+.08,tx+1.9,ty1+.49];
  piece('tavern-honor-bench',bench,25,'tavern','honor.tavern.visible',s=>{
    const [x,y,x1,y1]=bench;
    B.shadowAt(s,x,y,x1,y1,26,9);
    for(const a of [x+.15,x1-.15])for(const b of [y+.07,y1-.07])
      B.fullBox(s,DARK,a-.035,b-.035,a+.035,b+.035,0,9,WOOD);
    B.fullBox(s,WOOD,x,y,x1,y1,8,11,LIGHT);
    for(const b of [y+.13,y+.27])B.L(s,x+.02,b,11,x1-.02,b,11,DARK,.7);
    for(const a of [x+.1,x1-.1])B.L(s,a,y+.035,8,a,y+.035,24,DARK,2.2);
    B.Q(s,LIGHT,[x,y,15,x1,y,15,x1,y,23,x,y,23]);
    B.L(s,x,y,19,x1,y,19,DARK,.65);
    for(const a of [x+.08,x1-.08]){
      B.L(s,a,y+.02,15,a,y1-.02,15,WOOD,2.6);
      B.L(s,a,y1-.02,10,a,y1-.02,15,DARK,1.6);
    }
    const mid=(x+x1)/2;
    crest(s,(u,v)=>P(mid+u/36,y+.025,20-v),11,15);
  });
  const menu=[tx1-.15,ty1-.9,tx1+.2,ty1-.44];
  piece('tavern-favorite-menu',menu,27,'tavern','honor.tavern.visible',s=>{
    const [x,y,x1,y1]=menu;
    B.shadowAt(s,x,y,x1,y1,11,5);
    for(const a of [x,x1]){
      B.L(s,a,y,0,a,y+.15,25,DARK,1.7);
      B.L(s,a,y1,0,a,y+.15,25,DARK,1.7);
    }
    B.Q(s,LIGHT,[x-.04,y+.16,8,x1+.04,y+.16,8,x1+.04,y+.16,26,x-.04,y+.16,26]);
    B.Q(s,'#3f5c4c',[x,y+.17,10,x1,y+.17,10,x1,y+.17,24,x,y+.17,24]);
    const p=P((x+x1)/2,y+.18,17);
    s.ellipse(p.x,p.y,4.1,2.5,CREAM);s.ellipse(p.x,p.y,2.8,1.5,'#b4c8b0');
    const a=P(x+.04,y+.18,12),b=P(x1-.04,y+.18,12);s.line(a.x,a.y,b.x,b.y,CREAM,.7);
  });
  const icon=world((menu[0]+menu[2])/2,menu[1]+.18,17);
  placements['tavern-favorite-menu'].favoriteIcon=[icon[0]-4,icon[1]-4,8,8];
  const [fx,fy,fx1,fy1]=sites.fairground;
  // The existing stage stays intact. The small awards blocks sit ON its 7px
  // platform, below the existing curtain, and do not block either tent.
  const podium=[fx+.44,fy+.57,fx+1.18,fy+.98];
  piece('fairground-kaya-podium',podium,18,'fairground','fairground.open && festival.active',s=>{
    const [x,y,x1,y1]=podium,w=(x1-x)/3;
    for(const [i,h,col] of [[0,11,'#c9a57a'],[1,16,'#e8c25a'],[2,9.5,'#b48f66']]){
      const a=x+i*w+.012,b=x+(i+1)*w-.012;
      B.fullBox(s,col,a,y,b,y1,7,h,CREAM);
      const p=P((a+b)/2,y1+.006,(7+h)/2);
      s.ellipse(p.x,p.y,1.6,1.8,i===1?'#9a7238':'#8a6c4c');
    }
  });
  const flag=[fx+.26,fy+.27,fx+1.2,fy+.39];
  piece('fairground-honor-flag',flag,64,'fairground','honor.fairground.visible && festival.active',s=>{
    const x=fx+.31,y=fy+.31;
    // Pole is bolted to the stage, not a loose floating pennant.
    B.L(s,x,y,7,x,y,62,DARK,2.2);
    B.fullBox(s,DARK,x-.05,y-.05,x+.05,y+.05,7,10,LIGHT);
    const top=P(x,y,63);s.ellipse(top.x,top.y,2,2,GOLD);
    const q=(u,v)=>P(x+u,y+.02,59-v);
    s.poly([q(.04,0),q(.86,2),q(.79,10),q(.87,19),q(.04,17)],'#7fa3c4',DARK,.8);
    s.poly([q(.05,.8),q(.84,2.8),q(.82,4),q(.05,2)],CREAM);
    const p=P(x+.44,y+.026,49.5);
    crest(s,(u,v)=>({x:p.x+u,y:p.y+u*.5+v}),10,12);
  });
  // Two actual selling counters use the two EXISTING tents as their covers.
  // No new SKU, second canopy, extra purchase limit, or second stage.
  function counter(id,rect,colour,sonya){
    piece(id,rect,18,'fairground','fairground.open && festival.active',s=>{
      const [x,y,x1,y1]=rect;
      for(const a of [x+.06,x1-.06])for(const b of [y+.04,y1-.04]){
        const foot=P(a,b);s.ellipse(foot.x,foot.y,2,.8,'#41623517');
        B.L(s,a,b,0,a,b,10,DARK,1.7);
      }
      B.fullBox(s,WOOD,x,y,x1,y1,8,11,LIGHT);
      B.Q(s,colour,[x+.02,y1+.007,10.5,x1-.02,y1+.007,10.5,x1-.02,y1+.007,3,x+.02,y1+.007,3]);
      B.L(s,x+.02,y1+.015,4,x1-.02,y1+.015,4,CREAM,.8);
      for(const [u,col] of [[.22,sonya?'#c97a8a':'#d9553f'],[.62,sonya?'#7fa3c4':'#e8c25a']]){
        const p=P(x+(x1-x)*u,y+.13,11);
        if(sonya){
          for(let n=0;n<3;n++)s.poly([{x:p.x-3.2,y:p.y-n*1.6},{x:p.x+3.2,y:p.y+1.5-n*1.6},
            {x:p.x+3.2,y:p.y+.2-n*1.6},{x:p.x-3.2,y:p.y-1.3-n*1.6}],n%2?CREAM:col);
        }else{
          s.ellipse(p.x,p.y-2,2.6,2.8,col);s.ellipse(p.x-.7,p.y-2.8,.7,.7,CREAM);
        }
      }
    });
  }
  // Compact serving table beside the red tent's entrance. This 18-world-pixel
  // leftward move clears the foreground crown without placing a table on a roof.
  const agataShift=18/(36*matrix[0]);
  counter('fairground-extra-stall-agata',[fx1-.5-agataShift,fy+1.05,fx1-.2-agataShift,fy+1.25],'#7b5a8a',false);
  counter('fairground-extra-stall-sonya',[fx+.73,fy1-.66,fx+1.4,fy1-.32],'#c97a8a',true);
  const symbols=Object.entries(pieces).map(([id,p])=>`<symbol id="${id}" viewBox="${p.box.join(' ')}">${p.body}</symbol>`).join('');
  return {pieces,placements,sprite:`<svg xmlns="http://www.w3.org/2000/svg" aria-hidden="true">${symbols}</svg>`,
    files:Object.fromEntries(Object.entries(pieces).map(([id,p])=>[id,`<svg xmlns="http://www.w3.org/2000/svg" viewBox="${p.box.join(' ')}">${p.body}</svg>`]))};
}

async function crownOverlaps(effects,build,trees){
  const layout=build.layout;
  const cv=document.createElement('canvas');cv.width=2400;cv.height=1800;
  const ctx=cv.getContext('2d'),s=makeS(ctx);ctx.setTransform(...layout.matrix);
  for(const [x,y,k,pine] of trees){
    if(!pine){s.treeSprite(x,y,k,false);continue;}
    // Exact pine crown/trunk geometry from village.js, without ground shadow.
    const p=P(x,y);ctx.save();ctx.translate(p.x,p.y);ctx.scale(k,k);
    s.line(0,0,0,-14,'#9e8a60',4);
    for(const [t,w,b] of [[-62,20,-12],[-78,16,-32],[-92,12,-50]]){
      s.poly([{x:0,y:t},{x:-w,y:b},{x:0,y:b+3}],'#7da073');
      s.poly([{x:0,y:t},{x:w,y:b},{x:0,y:b+3}],'#71976d');
    }
    ctx.restore();
  }
  const treePixels=ctx.getImageData(0,0,2400,1800).data,overlaps={};
  // Existing completed building layers already hide some background crowns.
  // Compare with the crowns actually visible before these new pieces appear.
  ctx.setTransform(1,0,0,1,0,0);ctx.clearRect(0,0,2400,1800);
  for(const id of ['site-tavern-done','site-fairground-done']){
    const body=build.files[id].split('>').slice(1).join('>').replace(/<\/svg>\s*$/,'');
    const image=new Image();image.src=URL.createObjectURL(new Blob([
      `<svg xmlns="http://www.w3.org/2000/svg" width="2400" height="1800" viewBox="0 0 2400 1800">${body}</svg>`],{type:'image/svg+xml'}));
    await image.decode();ctx.drawImage(image,0,0);URL.revokeObjectURL(image.src);
  }
  const oldPixels=ctx.getImageData(0,0,2400,1800).data;
  for(let i=3;i<treePixels.length;i+=4)if(oldPixels[i]>=254)treePixels[i]=0;
  for(const [id,p] of Object.entries(effects.pieces)){
    const image=new Image(),svg=`<svg xmlns="http://www.w3.org/2000/svg" width="2400" height="1800" viewBox="0 0 2400 1800">${p.body}</svg>`;
    image.src=URL.createObjectURL(new Blob([svg],{type:'image/svg+xml'}));await image.decode();
    ctx.setTransform(1,0,0,1,0,0);ctx.clearRect(0,0,2400,1800);ctx.drawImage(image,0,0);URL.revokeObjectURL(image.src);
    const pixels=ctx.getImageData(0,0,2400,1800).data;let hits=0;
    for(let i=3;i<pixels.length;i+=4)if(pixels[i]>20&&treePixels[i]>20)hits++;
    overlaps[id]=hits;
  }
  return overlaps;
}

export async function render(args={}){
  if(args.layout)return {effects:buildingEffects(args.layout)};
  const base=await village({pumpkinPreview:true});
  const effects=buildingEffects(base.meta.build.layout);
  const tree_overlaps=await crownOverlaps(effects,base.meta.build,base.meta.tree_crowns);
  return {world:base.world,build:base.meta.build,walk:base.meta.walk,effects,tree_overlaps};
}
