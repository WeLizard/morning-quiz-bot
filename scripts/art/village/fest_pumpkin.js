// «Тыквенная ночь»: village decoration only (FARM_FESTIVALS_DESIGN §9.2 №10).
// Uses the farm's pumpkin crop geometry, scarecrow and drawing primitives. No new raster or filters.
import {festKit} from './fest_kit.js';
import {placeJack} from './pumpkin_jack.js';

export function pumpkinNight(V) {
  const K=festKit(V,'pumpkin_night'),{c,s,pt}=K, pieces=[], lanterns=[], placements=[];
  const poly=(pts,col)=>s.poly(pts.map(([x,y])=>({x,y})),col);
  // Coordinates local to the original FarmScene.plant pumpkin, with a carved friendly grimace.
  const face=(col)=>{
    poly([[-4.8,-5.9],[-1.2,-5.1],[-3.6,-8]],col);
    poly([[1.3,-5.1],[4.9,-6],[3.5,-8]],col);
    poly([[-4.5,-3.6],[-2.2,-2.6],[-1.1,-3.7],[.3,-2.3],[2,-3.2],[4.5,-4.1],[3,-1.5],[.2,-.6],[-2.8,-1.5]],col);
  };
  const pumpkin=(x,y,scale=2.2,carved=true)=>{
    const p=pt(x,y),base={x:p.x,y:p.y-2*scale};
    c.save();c.translate(base.x,base.y);c.scale(scale,scale);
    // Harvested fruit: the exact ellipse palette/geometry from FarmScene.plant's pumpkin
    // branch, without the generic tall living-plant stem drawn before that branch.
    s.ellipse(-3,-5,8,3,'#789757');s.ellipse(0,-4,7,6,'#d68e45');
    s.ellipse(-2,-4,3,6,'#e5a451');s.line(0,-10,1,-13,'#6d8750',1.6);
    if(carved)face('#68492f');
    c.restore();
    if(carved)lanterns.push({...base,scale,ground:true});
    placements.push({kind:'pumpkin',tile:[x,y],world:[V.matrix[0]*p.x+V.matrix[4],V.matrix[3]*p.y+V.matrix[5]],scale});
  };
  // Separate small groups make the holiday readable at the village's phone zoom.
  const [a,b,d,e]=V.plaza, pond=V.pond;
  const groups=[
    {near:[a+1,b+2],area:[a-3,b-3,d+3,e+3]},
    {near:[d-1,b+3],area:[a-3,b-3,d+3,e+3]},
    {near:[pond.x-2,pond.y+2],area:[pond.x-5,pond.y-4,pond.x+5,pond.y+5]},
    {near:[pond.x+2,pond.y+1],area:[pond.x-5,pond.y-4,pond.x+5,pond.y+5]},
  ];
  for(const [i,g] of groups.entries()){
    const at=K.place({w:i<2?.65:.95,d:i<2?.65:.8,h:34,button:50,cover:.2,...g,what:`pumpkin group ${i+1}`});
    if(!at)continue;
    const [x,y]=at;
    pieces.push([x+y+1.3,()=>{
      // One readable lantern on the crowded plaza; three ground-level fruits by the pond.
      pumpkin(x+.32,y+.32,i<2?2:2.4);
      if(i>=2){pumpkin(x+.70,y+.28,1.5,false);pumpkin(x+.25,y+.66,1.9);}
    }]);
  }
  // A single old farm scarecrow by the pond; its stake, shirt and hat are the farm's actual art.
  const old=K.place({w:.9,d:.8,h:65,near:[pond.x-3,pond.y+2],area:[pond.x-6,pond.y-4,pond.x+5,pond.y+5],button:65,cover:.06,what:'old scarecrow'});
  if(old){const [x,y]=[old[0]+.45,old[1]+.4];pieces.push([x+y+.7,()=>{
    const p=pt(x,y);c.save();c.translate(p.x,p.y);c.scale(1.2,1.2);
    s.decor({type:'scarecrow',x,y},{x:0,y:0});
    s.line(-3,-37,-1,-35,'#68492f',1);s.line(2,-37,4,-35,'#68492f',1);
    s.line(-3,-32,3,-32,'#68492f',.8);c.restore();
    placements.push({kind:'scarecrow',tile:[x,y]});
  }]);}
  c.group('vf-decor');
  // Cobwebs fixed to visible fence posts and rails, in their own isometric plane.
  for(const [x0,y0,x1,y1] of K.gardenFences(3)){
    const len=Math.hypot(x1-x0,y1-y0),ux=(x1-x0)/len,uy=(y1-y0)/len;
    const at=(u,z)=>pt(x0+ux*u,y0+uy*u,z),top=at(.08,13),end=Math.min(.9,len);
    if([0,.5,1].some(t=>K.hidden(x0+ux*end*t,y0+uy*end*t,7)))continue;
    for(const [u,z] of [[end,13],[end*.7,4],[0,1]]){
      const q=at(u,z);s.line(top.x,top.y,q.x,q.y,'#ede6d2',.85);
    }
    for(const t of [.35,.65,1]){
      const aa=at(end*t,13),bb=at(end*.7*t,13-9*t),dd=at(.08*(1-t),13-12*t);
      c.beginPath();c.moveTo(aa.x,aa.y);c.quadraticCurveTo(top.x+(bb.x-top.x)*.65,top.y+(bb.y-top.y)*.65,bb.x,bb.y);
      c.quadraticCurveTo(top.x+(dd.x-top.x)*.6,top.y+(dd.y-top.y)*.6,dd.x,dd.y);c.strokeStyle='#ede6d2';c.lineWidth=.75;c.stroke();
    }
  }
  // Paper bat ornaments hang from the existing plaza lamp posts, not in midair.
  K.lampPairs(2).forEach(([aa,bb])=>K.garland(aa,bb,(p,q,i)=>{
    s.line(p.x,p.y,p.x,p.y+4,'#8a6c4c',.8);
    if(i%3===0){
      const x=p.x,y=p.y+7;
      poly([[x-8,y-4],[x-4,y-2],[x-2,y+1],[x-1,y-3],[x,y-1],[x+1,y-3],[x+2,y+1],[x+4,y-2],[x+8,y-4],[x+6,y+3],[x+3,y+2],[x,y+5],[x-3,y+2],[x-6,y+3]],'#68492f');
    }else{
      const x=p.x,y=p.y+13,scale=1.35;
      s.line(x,p.y+4,x,y-7,'#8a6c4c',.8);
      s.ellipse(x,y,9.5,8.1,'#d68e45');s.ellipse(x-2.7,y,4,8.1,'#e5a451');
      s.line(x,y-8,x+1,y-11,'#6d8750',1.6);
      c.save();c.translate(x,y+4*scale);c.scale(scale,scale);face('#68492f');c.restore();
      lanterns.push({x,y:y+4*scale,scale});
    }
  },'#8a6c4c',26));
  pieces.sort((aa,bb)=>aa[0]-bb[0]).forEach(([,draw])=>draw());
  c.end();
  c.group('vf-day');c.end();
  c.group('vf-night');
  // Patches of low mist over the pond water, clipped away from all foreground silhouettes.
  c.groupClipOut(K.houses.map(h=>h.hull));
  for(const [dx,dy,rx] of [[-.6,-.4,51],[.6,.2,66],[-.5,.7,43]]){
    const p=pt(pond.x+dx,pond.y+dy,2);
    c.beginPath();c.moveTo(p.x-rx,p.y+3);
    c.bezierCurveTo(p.x-rx*.6,p.y-8,p.x-rx*.2,p.y-5,p.x+rx*.12,p.y-7);
    c.bezierCurveTo(p.x+rx*.65,p.y-12,p.x+rx*.7,p.y-1,p.x+rx,p.y-3);
    c.bezierCurveTo(p.x+rx*.5,p.y+7,p.x-rx*.5,p.y+5,p.x-rx,p.y+3);
    c.closePath();c.fillStyle='rgba(219,229,215,.09)';c.fill();
  }
  c.end();
  for(const p of lanterns){
    s.ellipse(p.x,p.y-4*p.scale,13*p.scale,10*p.scale,'rgba(255,200,95,.06)');
    if(p.ground)s.ellipse(p.x,p.y,11*p.scale,3*p.scale,'rgba(255,200,95,.09)');
    c.save();c.translate(p.x,p.y);c.scale(p.scale,p.scale);face('#ffe7a0');c.restore();
  }
  c.end();
  const jack=placeJack(K,V);
  return {svg:K.wrap(),problems:K.problems,placements,jack};
}
