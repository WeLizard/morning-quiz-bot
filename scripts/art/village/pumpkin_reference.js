// A style reference rendered only for the review sheet. All objects come from the farm.
import {makeS,B} from './common.js';
export function render(){
  const cv=document.createElement('canvas');cv.width=640;cv.height=480;
  const c=cv.getContext('2d'),s=makeS(c);c.fillStyle='#c1d5a3';c.fillRect(0,0,640,480);
  c.translate(300,96);c.scale(1.5,1.5);
  for(let y=0;y<7;y++)for(let x=0;x<7;x++)s.tile(x,y,(x+y)%2?'#bfd39e':'#c6d9a9');
  B.drawBuilding(s,{id:'house',type:'house',x:0,y:0,w:2,h:2,level:1,jobs:[]});
  for(let y=2;y<5;y++)for(let x=2;x<5;x++){
    s.tile(x,y,'#b39572','#a58965');s.plant((x-y)*36,(x+y+1)*18-2,'pumpkin',1,0);
  }
  s.decor({type:'scarecrow',x:5,y:3},{x:72,y:144});
  return {reference:cv.toDataURL('image/png')};
}
