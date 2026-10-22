/* Original procedural building artwork for the isometric farm.
   Every building is assembled from the same few solids (box, gable/hip roof, octagonal tower, cylinder)
   so roofs always sit exactly on the wall box. Pure view code: no authority over game state.
   Tile space: x runs right-down, y runs left-down, z is height in pixels. The two visible wall faces
   are the plane y=Y1 (left, lit) and the plane x=X1 (right, shaded). */
const TW=36, TH=18, PI=Math.PI;
const px=(x,y)=>(x-y)*TW, py=(x,y,z)=>(x+y)*TH-z;
const SH=new Map();
export function sh(hex,f){const k=hex+f;let v=SH.get(k);if(v)return v;const n=parseInt(hex.slice(1),16),m=a=>Math.max(0,Math.min(255,Math.round(a*(1+f))));v=`rgb(${m(n>>16)},${m(n>>8&255)},${m(n&255)})`;SH.set(k,v);return v}

/* ---------- drawing primitives (tile coordinates, no per-point objects) ---------- */
function Q(s,fill,pts,stroke,lw){const c=s.c;c.beginPath();for(let i=0;i<pts.length;i+=3){const X=(pts[i]-pts[i+1])*TW,Y=(pts[i]+pts[i+1])*TH-pts[i+2];if(i)c.lineTo(X,Y);else c.moveTo(X,Y)}c.closePath();if(fill){c.fillStyle=fill;c.fill()}if(stroke){c.strokeStyle=stroke;c.lineWidth=lw||1;c.lineJoin='round';c.stroke()}}
function L(s,x1,y1,z1,x2,y2,z2,col,w){const c=s.c;c.beginPath();c.moveTo(px(x1,y1),py(x1,y1,z1));c.lineTo(px(x2,y2),py(x2,y2,z2));c.strokeStyle=col;c.lineWidth=w||1;c.lineCap='round';c.stroke()}
function E(s,x,y,z,rx,ry,col){s.ellipse(px(x,y),py(x,y,z),rx,ry,col)}
const wallY=(s,f,Y,xa,xb,za,zta,ztb)=>Q(s,f,[xa,Y,za,xb,Y,za,xb,Y,ztb,xa,Y,zta]);
const wallX=(s,f,X,ya,yb,za,zta,ztb)=>Q(s,f,[X,ya,za,X,yb,za,X,yb,ztb,X,ya,zta]);
const top=(s,f,x0,y0,x1,y1,z,st)=>Q(s,f,[x0,y0,z,x1,y0,z,x1,y1,z,x0,y1,z],st,1);
function box(s,col,x0,y0,x1,y1,za,zb){wallY(s,col,y1,x0,x1,za,zb,zb);wallX(s,sh(col,-.16),x1,y0,y1,za,zb,zb)}
function fullBox(s,col,x0,y0,x1,y1,za,zb,topCol){box(s,col,x0,y0,x1,y1,za,zb);top(s,topCol||sh(col,.12),x0,y0,x1,y1,zb)}
function courses(s,p,n,col){for(let k=1;k<n;k++){const f=k/n;L(s,p[0]+(p[9]-p[0])*f,p[1]+(p[10]-p[1])*f,p[2]+(p[11]-p[2])*f,p[3]+(p[6]-p[3])*f,p[4]+(p[7]-p[4])*f,p[5]+(p[8]-p[5])*f,col,.9)}}
function ground(s,x0,y0,x1,y1,col){Q(s,col,[x0,y0,0,x1,y0,0,x1,y1,0,x0,y1,0])}
function shadowAt(s,x0,y0,x1,y1,rx=52,ry=21){s.shadow(px((x0+x1)/2,(y0+y1)/2),py((x0+x1)/2,(y0+y1)/2,0),rx,ry)}

/* windows / doors painted on a wall plane. xc/yc = centre along the wall, z = bottom */
function winY(s,Y,xc,z,w,h,glass='#abc9c7',frame='#f3ead2'){const m=.025;Q(s,frame,[xc-w/2-m,Y,z-2,xc+w/2+m,Y,z-2,xc+w/2+m,Y,z+h+2,xc-w/2-m,Y,z+h+2]);Q(s,glass,[xc-w/2,Y,z,xc+w/2,Y,z,xc+w/2,Y,z+h,xc-w/2,Y,z+h]);L(s,xc,Y,z,xc,Y,z+h,frame,1);L(s,xc-w/2,Y,z+h/2,xc+w/2,Y,z+h/2,frame,1)}
function winX(s,X,yc,z,w,h,glass='#9fbebc',frame='#eadfc4'){const m=.025;Q(s,frame,[X,yc-w/2-m,z-2,X,yc+w/2+m,z-2,X,yc+w/2+m,z+h+2,X,yc-w/2-m,z+h+2]);Q(s,glass,[X,yc-w/2,z,X,yc+w/2,z,X,yc+w/2,z+h,X,yc-w/2,z+h]);L(s,X,yc,z,X,yc,z+h,frame,1);L(s,X,yc-w/2,z+h/2,X,yc+w/2,z+h/2,frame,1)}
function doorY(s,Y,xc,w,h,fill='#8f7556',frame='#efe5cb',arch=false){const a=xc-w/2,b=xc+w/2,m=.03;if(arch){Q(s,frame,[a-m,Y,0,b+m,Y,0,b+m,Y,h-3,xc,Y,h+4,a-m,Y,h-3]);Q(s,fill,[a,Y,0,b,Y,0,b,Y,h-4,xc,Y,h+2,a,Y,h-4])}else{Q(s,frame,[a-m,Y,0,b+m,Y,0,b+m,Y,h+2,a-m,Y,h+2]);Q(s,fill,[a,Y,0,b,Y,0,b,Y,h,a,Y,h])}L(s,xc,Y,1,xc,Y,h-1,sh(fill,-.18),1);E(s,xc+w*.28,Y,h*.45,1.3,1.3,'#e8d9a8')}
function doorX(s,X,yc,w,h,fill='#7f6a4d',frame='#e5d9bb',arch=false){const a=yc-w/2,b=yc+w/2,m=.03;if(arch){Q(s,frame,[X,a-m,0,X,b+m,0,X,b+m,h-3,X,yc,h+4,X,a-m,h-3]);Q(s,fill,[X,a,0,X,b,0,X,b,h-4,X,yc,h+2,X,a,h-4])}else{Q(s,frame,[X,a-m,0,X,b+m,0,X,b+m,h+2,X,a-m,h+2]);Q(s,fill,[X,a,0,X,b,0,X,b,h,X,a,h])}L(s,X,yc,1,X,yc,h-1,sh(fill,-.2),1);E(s,X,yc+w*.28,h*.45,1.3,1.3,'#d9c999')}
function plinth(s,col,x0,y0,x1,y1,h=4){wallY(s,col,y1,x0,x1,0,h,h);wallX(s,sh(col,-.14),x1,y0,y1,0,h,h)}
function corners(s,x0,y0,x1,y1,z,col){L(s,x0,y1,0,x0,y1,z,col,2);L(s,x1,y1,0,x1,y1,z,col,2);L(s,x1,y0,0,x1,y0,z,sh(col,-.15),2)}
function boards(s,plane,at,a,b,z0,z1,step,col){for(let z=z0+step;z<z1;z+=step){if(plane==='y')L(s,a,at,z,b,at,z,col,.8);else L(s,at,a,z,at,b,z,col,.8)}}

/* ---------- roofs ---------- */
const GABLE=[[0,0],[.5,1],[1,0]];
const GAMBREL=[[0,0],[.18,.56],[.5,1],[.82,.56],[1,0]];
function riseAt(prof,t){for(let i=0;i<prof.length-1;i++){const a=prof[i],b=prof[i+1];if(t<=b[0]+1e-9){return a[1]+(b[1]-a[1])*((t-a[0])/(b[0]-a[0]||1))}}return 0}
/* wall-coloured gable end (closed triangle/pentagon) in the visible end plane */
function gableWall(s,axis,g){const {x0,y0,x1,y1,zE,prof,R,ov,col}=g,a0=(axis==='y'?x0:y0),a1=(axis==='y'?x1:y1),W=a1-a0,span=W+2*ov,t0=ov/span,t1=1-t0;
  const pts=[];const push=(a,z)=>{if(axis==='y')pts.push(a,y1,z);else pts.push(x1,a,z)};
  push(a0,zE);push(a0,zE+riseAt(prof,t0)*R);for(const [t,r] of prof){if(t>t0+1e-6&&t<t1-1e-6)push(a0-ov+span*t,zE+r*R)}push(a1,zE+riseAt(prof,t1)*R);push(a1,zE);
  Q(s,axis==='y'?col:sh(col,-.16),pts)}
function gableRoof(s,axis,g){const {x0,y0,x1,y1,zE,prof,R,ov,roof}=g,a0=(axis==='y'?x0:y0)-ov,a1=(axis==='y'?x1:y1)+ov,b0=(axis==='y'?y0:x0)-ov,b1=(axis==='y'?y1:x1)+ov;
  let ridgeA=a0,rm=-1;
  for(let i=0;i<prof.length-1;i++){const ta=prof[i][0],tb=prof[i+1][0],za=zE+prof[i][1]*R,zb=zE+prof[i+1][1]*R,aa=a0+(a1-a0)*ta,ab=a0+(a1-a0)*tb,back=ta+tb<1;
    const f=(axis==='y'?(back?.07:-.1):(back?-.06:.1))+(i%2?.03:0);
    const p=axis==='y'?[aa,b0,za,aa,b1,za,ab,b1,zb,ab,b0,zb]:[b0,aa,za,b1,aa,za,b1,ab,zb,b0,ab,zb];
    Q(s,sh(roof,f),p);courses(s,p,g.courses||3,sh(roof,f-.11));}
  for(const [t,r] of prof){if(r*R>rm){rm=r*R;ridgeA=a0+(a1-a0)*t}}
  const zr=zE+rm;
  // ridge cap, eaves and the visible rake trim
  if(axis==='y'){L(s,ridgeA,b0,zr,ridgeA,b1,zr,sh(roof,.24),2.4);L(s,a1,b0,zE,a1,b1,zE,sh(roof,-.24),2.2);
    for(let i=0;i<prof.length-1;i++)L(s,a0+(a1-a0)*prof[i][0],b1,zE+prof[i][1]*R,a0+(a1-a0)*prof[i+1][0],b1,zE+prof[i+1][1]*R,g.trim||sh(roof,.3),2.2)}
  else{L(s,b0,ridgeA,zr,b1,ridgeA,zr,sh(roof,.24),2.4);L(s,b0,a1,zE,b1,a1,zE,sh(roof,-.24),2.2);
    for(let i=0;i<prof.length-1;i++)L(s,b1,a0+(a1-a0)*prof[i][0],zE+prof[i][1]*R,b1,a0+(a1-a0)*prof[i+1][0],zE+prof[i+1][1]*R,g.trim||sh(roof,.3),2.2)}
}
/* hip / pyramid roof */
function hipRoof(s,x0,y0,x1,y1,zE,rise,col,ov,topFlat=0){const A=x0-ov,B=x1+ov,C=y0-ov,D=y1+ov,W=B-A,H=D-C,xm=(A+B)/2,ym=(C+D)/2,z=zE+rise,i=Math.min(W,H)/2-topFlat;
  if(W>=H){const r1=A+i,r2=B-i;
    let p=[A,C,zE,B,C,zE,r2,ym,z,r1,ym,z];Q(s,sh(col,-.04),p);courses(s,p,3,sh(col,-.15));
    p=[A,D,zE,A,C,zE,r1,ym,z,r1,ym,z];Q(s,sh(col,.06),p);
    p=[B,C,zE,B,D,zE,r2,ym,z,r2,ym,z];Q(s,sh(col,-.1),p);courses(s,p,3,sh(col,-.2));
    p=[A,D,zE,B,D,zE,r2,ym,z,r1,ym,z];Q(s,sh(col,.1),p);courses(s,p,3,sh(col,-.1));
    L(s,r1,ym,z,r2,ym,z,sh(col,.25),2.2);L(s,A,D,zE,r1,ym,z,sh(col,.2),1.4);L(s,B,D,zE,r2,ym,z,sh(col,-.05),1.4);L(s,A,D,zE,B,D,zE,sh(col,-.26),2.2);L(s,B,C,zE,B,D,zE,sh(col,-.3),2)}
  else{const r1=C+i,r2=D-i;
    let p=[A,C,zE,A,D,zE,xm,r2,z,xm,r1,z];Q(s,sh(col,.06),p);courses(s,p,3,sh(col,-.12));
    p=[A,C,zE,B,C,zE,xm,r1,z,xm,r1,z];Q(s,sh(col,-.04),p);
    p=[B,C,zE,B,D,zE,xm,r2,z,xm,r1,z];Q(s,sh(col,-.1),p);courses(s,p,3,sh(col,-.2));
    p=[A,D,zE,B,D,zE,xm,r2,z,xm,r2,z];Q(s,sh(col,.1),p);
    L(s,xm,r1,z,xm,r2,z,sh(col,.25),2.2);L(s,A,D,zE,xm,r2,z,sh(col,.2),1.4);L(s,B,D,zE,xm,r2,z,sh(col,-.05),1.4);L(s,A,D,zE,B,D,zE,sh(col,-.26),2.2);L(s,B,C,zE,B,D,zE,sh(col,-.3),2)}
}
/* shed roof falling towards +y (dir 'y') or +x (dir 'x'); high edge at the back */
function shedRoof(s,x0,y0,x1,y1,zLow,zHigh,col,ov,dir='y'){const A=x0-ov,B=x1+ov,C=y0-ov,D=y1+ov;let p;
  if(dir==='y'){p=[A,D,zLow,B,D,zLow,B,C,zHigh,A,C,zHigh];Q(s,sh(col,.06),p);courses(s,p,4,sh(col,-.14));L(s,A,D,zLow,B,D,zLow,sh(col,-.28),2.4);L(s,B,D,zLow,B,C,zHigh,sh(col,.28),2)}
  else{p=[B,C,zLow,B,D,zLow,A,D,zHigh,A,C,zHigh];Q(s,sh(col,-.06),p);courses(s,p,4,sh(col,-.2));L(s,B,C,zLow,B,D,zLow,sh(col,-.3),2.4);L(s,B,D,zLow,A,D,zHigh,sh(col,.25),2)}}

function shedBox(s,col,x0,y0,x1,y1,zb,zLow,zHigh){wallY(s,col,y1,x0,x1,zb,zLow,zLow);wallX(s,sh(col,-.16),x1,y0,y1,zb,zHigh,zLow)}

/* ---------- octagonal solids ---------- */
const T={cx:0,cy:0,r0:1,r1:1,z0:0,z1:1,n:8,rot:PI/8};
function octBody(s,col,bands){const n=T.n,st=2*PI/n,dr=T.r1-T.r0;
  for(let k=0;k<n;k++){const a=T.rot+k*st,b=a+st,m=a+st/2,cm=Math.cos(m),sm=Math.sin(m);if(cm+sm<-.02)continue;
    const ca=Math.cos(a),sa=Math.sin(a),cb=Math.cos(b),sb=Math.sin(b);
    Q(s,sh(col,.13*sm-.17*cm),[T.cx+T.r0*ca,T.cy+T.r0*sa,T.z0,T.cx+T.r0*cb,T.cy+T.r0*sb,T.z0,T.cx+T.r1*cb,T.cy+T.r1*sb,T.z1,T.cx+T.r1*ca,T.cy+T.r1*sa,T.z1]);
    if(bands)for(const z of bands){const f=(z-T.z0)/(T.z1-T.z0),r=T.r0+dr*f;L(s,T.cx+r*ca,T.cy+r*sa,z,T.cx+r*cb,T.cy+r*sb,z,sh(col,-.22),1.1)}}}
function octTop(s,col,r,z){const pts=[];for(let k=0;k<T.n;k++){const a=T.rot+k*2*PI/T.n;pts.push(T.cx+r*Math.cos(a),T.cy+r*Math.sin(a),z)}Q(s,col,pts)}
function cone(s,col,r,z0,zA,rings=2,n=T.n){const st=2*PI/n,cx=T.cx,cy=T.cy;
  for(let k=0;k<n;k++){const a=T.rot+k*st,b=a+st,m=a+st/2,cm=Math.cos(m),sm=Math.sin(m);if(cm+sm<-.02)continue;
    const f=.12*sm-.16*cm;Q(s,sh(col,f),[cx+r*Math.cos(a),cy+r*Math.sin(a),z0,cx+r*Math.cos(b),cy+r*Math.sin(b),z0,cx,cy,zA]);
    for(let j=1;j<=rings;j++){const q=j/(rings+1),rr=r*(1-q),zz=z0+(zA-z0)*q;L(s,cx+rr*Math.cos(a),cy+rr*Math.sin(a),zz,cx+rr*Math.cos(b),cy+rr*Math.sin(b),zz,sh(col,f-.12),.9)}
    L(s,cx+r*Math.cos(a),cy+r*Math.sin(a),z0,cx,cy,zA,sh(col,f+.12),1)}}
function facePt(phi,sa,z){const f=(z-T.z0)/(T.z1-T.z0),r=T.r0+(T.r1-T.r0)*f,ap=r*Math.cos(PI/T.n),hw=r*Math.sin(PI/T.n);fx=T.cx+Math.cos(phi)*ap-Math.sin(phi)*hw*sa;fy=T.cy+Math.sin(phi)*ap+Math.cos(phi)*hw*sa}
let fx=0,fy=0;
function faceQuad(s,phi,sa,sb,za,zb,fill,stroke){facePt(phi,sa,za);const ax=fx,ay=fy;facePt(phi,sb,za);const bx=fx,by=fy;facePt(phi,sb,zb);const cx=fx,cy=fy;facePt(phi,sa,zb);Q(s,fill,[ax,ay,za,bx,by,za,cx,cy,zb,fx,fy,zb],stroke,1)}

/* ---------- cylinders and small props ---------- */
function cyl(s,cx,cy,r,z0,z1,col,topCol){const c=s.c,X=px(cx,cy),Y0=py(cx,cy,z0),Y1=py(cx,cy,z1),rx=r*TW*1.4142,ry=r*TH*1.4142;
  c.beginPath();c.moveTo(X-rx,Y1);c.lineTo(X-rx,Y0);c.ellipse(X,Y0,rx,ry,0,PI,0,true);c.lineTo(X+rx,Y1);c.ellipse(X,Y1,rx,ry,0,0,PI,true);c.closePath();c.fillStyle=col;c.fill();
  c.beginPath();c.moveTo(X+rx*.35,Y1+ry*.94);c.lineTo(X+rx,Y1);c.lineTo(X+rx,Y0);c.ellipse(X,Y0,rx,ry,0,0,Math.acos(.35),false);c.closePath();c.fillStyle='rgba(60,50,30,.13)';c.fill();
  if(topCol){c.beginPath();c.ellipse(X,Y1,rx,ry,0,0,PI*2);c.fillStyle=topCol;c.fill()}}
function barrel(s,x,y,r=.17,h=14,col='#b79163'){cyl(s,x,y,r,0,h,col,sh(col,.18));const X=px(x,y),rx=r*TW*1.4142,ry=r*TH*1.4142;for(const z of [h*.28,h*.72]){s.c.beginPath();s.c.ellipse(X,py(x,y,z),rx,ry,0,0,PI);s.c.strokeStyle=sh(col,-.3);s.c.lineWidth=1.2;s.c.stroke()}}
function crate(s,x,y,sz=.3,h=11,col='#c9a672'){fullBox(s,col,x-sz/2,y-sz/2,x+sz/2,y+sz/2,0,h,sh(col,.15));boards(s,'y',y+sz/2,x-sz/2,x+sz/2,0,h,h/2.2,sh(col,-.3))}
function bale(s,x,y,sz=.32,h=11){fullBox(s,'#dcc67c',x-sz/2,y-sz/2,x+sz/2,y+sz/2,0,h,'#ead58c');for(const z of [h*.33,h*.66])L(s,x-sz/2,y+sz/2,z,x+sz/2,y+sz/2,z,'#b8a35e',.9);L(s,x+sz/2,y-sz/2,h*.5,x+sz/2,y+sz/2,h*.5,'#a8944f',.9)}
function sack(s,x,y,col='#e6dcc0'){E(s,x,y,0,8,4,'rgba(60,70,40,.12)');s.ellipse(px(x,y),py(x,y,6),6.5,7.5,col);s.ellipse(px(x,y)-1,py(x,y,6)-1,4,5,sh(col,.1));s.line(px(x,y)-3,py(x,y,13),px(x,y)+3,py(x,y,13),sh(col,-.25),1.5)}
function smoke(s,x,y,z,on=true,k=1){if(!on)return;for(let i=0;i<3;i++){const f=(s.time*.2+i*.34)%1;s.ellipse(px(x,y)+Math.sin(s.time*.8+i*2)*2*f+f*4,py(x,y,z)-f*34*k,4*k+f*8*k,3*k+f*6*k,`rgba(248,246,232,${(.42*(1-f)).toFixed(3)})`)}}
function chimney(s,x,y,za,zb,col='#a8826a',w=.11){fullBox(s,col,x-w,y-w,x+w,y+w,za,zb,sh(col,.18));top(s,'#4f4a40',x-w*.6,y-w*.6,x+w*.6,y+w*.6,zb)}
function flowerPot(s,x,y){const X=px(x,y),Y=py(x,y,0);s.poly([{x:X-4,y:Y-6},{x:X+4,y:Y-6},{x:X+3,y:Y+1},{x:X-3,y:Y+1}],'#b88f69');s.ellipse(X,Y-8,6,4.5,'#86a56f');s.ellipse(X-2,Y-10,2,2,'#d6a8b0');s.ellipse(X+2,Y-9,1.6,1.6,'#efd9a0')}
function rail(s,x1,y1,x2,y2,h,col,mesh){const len=Math.hypot(x2-x1,y2-y1),n=Math.max(1,Math.round(len/.42));
  for(const z of [h,h*.5])L(s,x1,y1,z,x2,y2,z,col,2);
  if(mesh)for(let k=1;k<n*3;k++){const f=k/(n*3);L(s,x1+(x2-x1)*f,y1+(y2-y1)*f,2,x1+(x2-x1)*f,y1+(y2-y1)*f,h-1,mesh,.7)}
  for(let k=0;k<=n;k++){const f=k/n,x=x1+(x2-x1)*f,y=y1+(y2-y1)*f;L(s,x,y,0,x,y,h+2,sh(col,-.08),2.6)}}
function yardFence(s,xa,xb,yBack,yFront,col='#b79f72',h=10,mesh=null){rail(s,xa,yBack,xa,yFront,h,col,mesh);rail(s,xa,yFront,xb,yFront,h,col,mesh);rail(s,xb,yBack,xb,yFront,h,col,mesh)}
function awning(s,xa,xb,Y,z,out,drop,c1,c2,n=6){for(let i=0;i<n;i++){const a=xa+(xb-xa)*i/n,b=xa+(xb-xa)*(i+1)/n;Q(s,i%2?c2:c1,[a,Y,z,b,Y,z,b,Y+out,z-drop,a,Y+out,z-drop])}L(s,xa,Y+out,z-drop,xb,Y+out,z-drop,sh(c1,-.25),1.4)}

/* ---------- generic walled body ---------- */
function body(s,g){const {x0,y0,x1,y1,H,col}=g;
  shadowAt(s,x0,y0,x1,y1);
  box(s,col,x0,y0,x1,y1,0,H);
  if(g.base)plinth(s,g.base,x0,y0,x1,y1,g.baseH||4);
  if(g.corner)corners(s,x0,y0,x1,y1,H,g.corner);
  if(g.prof){g.zE=H;gableWall(s,g.axis,g)}
}
function roofOf(s,g){gableRoof(s,g.axis,g)}
function gparams(g,d){for(const k in d)if(g[k]===undefined)g[k]=d[k];return g}

/* ---------- buildings ---------- */
function house(s,o){
  const g=gparams({x0:o.x+.14,y0:o.y+.14,x1:o.x+o.w-.14,y1:o.y+o.h-.2,H:32,col:'#e8d9ae',roof:'#7c9d83',axis:'y',prof:GABLE,R:26,ov:.12,base:'#bdb398',corner:'#f6eed6',trim:'#d9e6d8'},{});
  ground(s,o.x+.02,o.y+.02,o.x+o.w-.02,o.y+o.h-.02,'rgba(205,190,150,.35)');
  body(s,g);const xm=(g.x0+g.x1)/2;
  // gable wall (left): ground-floor window and a round attic window
  winY(s,g.y1,xm-.34,10,.3,12);winY(s,g.y1,xm+.34,10,.3,12);
  E(s,xm,g.y1,g.H+11,5,5,'#f3ead2');E(s,xm,g.y1,g.H+11,3.6,3.6,'#a9c7c6');
  // long wall (right): door under a little porch roof and two windows
  const yd=(g.y0+g.y1)/2+.04;doorX(s,g.x1,yd,.34,21);winX(s,g.x1,g.y0+.38,11,.3,12);winX(s,g.x1,g.y1-.3,11,.28,12);
  Q(s,'#8aa98f',[g.x1,yd-.28,27,g.x1,yd+.28,27,g.x1+.24,yd+.28,23,g.x1+.24,yd-.28,23]);L(s,g.x1+.24,yd-.28,23,g.x1+.24,yd+.28,23,'#5f806a',1.6);
  L(s,g.x1+.22,yd+.26,0,g.x1+.22,yd+.26,23,'#cdb98f',1.8);L(s,g.x1+.22,yd-.26,0,g.x1+.22,yd-.26,23,'#cdb98f',1.8);
  roofOf(s,g);
  chimney(s,xm+.06,g.y0+.5,g.H+10,g.H+R_(g)+8);smoke(s,xm+.06,g.y0+.5,g.H+R_(g)+8,true,.9);
  flowerPot(s,g.x1+.3,g.y1-.05);flowerPot(s,g.x0-.02,g.y1+.2);
  const entry=s.projectStage('flower_entry');
  if(entry>=1){
   for(let k=0;k<3;k++)E(s,g.x1+.23+k*.1,yd,0,4.5,2.4,'#e5d7b6');
   for(const side of [-1,1]){
    const fy=yd+side*.43;E(s,g.x1+.24,fy,3,7,3,'#a87851');
    for(let k=0;k<3;k++){const yy=fy+(k-1)*.08;L(s,g.x1+.24,yy,6,g.x1+.24,yy,13,'#698b5f',1.2);E(s,g.x1+.24,yy,14,2.5,2.2,k%2?'#e6ba6e':'#d88b9d')}
   }
  }
  if(entry>=2){
   const ax=g.x1+.31,left=yd-.37,right=yd+.37;
   for(const fy of [left,right])L(s,ax,fy,0,ax,fy,34,'#7b955e',3);
   L(s,ax,left,34,ax,right,34,'#7b955e',3);
   for(let k=0;k<7;k++){const fy=left+(right-left)*k/6;E(s,ax,fy,35+(k%2)*3,3.2,3.1,k%3?'#e5b5bf':'#f2d788')}
   for(const fy of [left,right])for(const z of [12,21,29])E(s,ax,fy,z,2.5,2,'#b5c887');
  }
  return g.H+R_(g)+12}
function R_(g){return g.R}

function barn(s,o){
  const g=gparams({x0:o.x+.14,y0:o.y+.12,x1:o.x+o.w-.14,y1:o.y+o.h-.52,H:30,col:'#c18b70',roof:'#85685a',axis:'y',prof:GAMBREL,R:30,ov:.12,base:'#8f7766',trim:'#f2e8d2',courses:3},{});
  ground(s,o.x+.02,o.y+.02,o.x+o.w-.02,o.y+o.h-.02,'rgba(205,185,135,.4)');
  body(s,g);const xm=(g.x0+g.x1)/2,Y=g.y1;
  // white corner trim and plank lines
  boards(s,'y',Y,g.x0,g.x1,0,g.H,6,'rgba(120,70,50,.22)');boards(s,'x',g.x1,g.y0,g.y1,0,g.H,6,'rgba(90,50,40,.2)');
  L(s,g.x0,Y,0,g.x0,Y,g.H,'#f2e8d2',2.4);L(s,g.x1,Y,0,g.x1,Y,g.H,'#f2e8d2',2.4);
  // big sliding doors with X braces
  Q(s,'#f2e8d2',[xm-.5,Y,0,xm+.5,Y,0,xm+.5,Y,25,xm-.5,Y,25]);Q(s,'#a6624c',[xm-.46,Y,0,xm,Y,0,xm,Y,23,xm-.46,Y,23]);Q(s,'#9b5a46',[xm,Y,0,xm+.46,Y,0,xm+.46,Y,23,xm,Y,23]);
  L(s,xm-.46,Y,0,xm,Y,23,'#f2e8d2',1.4);L(s,xm-.46,Y,23,xm,Y,0,'#f2e8d2',1.4);L(s,xm,Y,0,xm+.46,Y,23,'#f2e8d2',1.4);L(s,xm,Y,23,xm+.46,Y,0,'#f2e8d2',1.4);
  // hay loft opening with straw
  Q(s,'#f2e8d2',[xm-.27,Y,g.H+3,xm+.27,Y,g.H+3,xm+.27,Y,g.H+17,xm-.27,Y,g.H+17]);Q(s,'#5e4a40',[xm-.23,Y,g.H+5,xm+.23,Y,g.H+5,xm+.23,Y,g.H+15,xm-.23,Y,g.H+15]);
  for(let i=0;i<4;i++)E(s,xm-.15+i*.1,Y,g.H+5+(i%2),3.4,2.2,'#e0c978');
  L(s,xm,Y,g.H+20,xm,Y+.3,g.H+20,'#6d5645',2);L(s,xm,Y+.3,g.H+20,xm,Y+.3,g.H+13,'#6d5645',1);
  // right wall windows
  winX(s,g.x1,g.y0+.5,14,.24,11,'#8b7b6e','#f2e8d2');winX(s,g.x1,g.y1-.45,14,.24,11,'#8b7b6e','#f2e8d2');
  roofOf(s,g);
  // weathervane
  const wx=xm,wy=g.y0+.3,wz=g.H+g.R;L(s,wx,wy,wz,wx,wy,wz+11,'#7d7466',1.6);L(s,wx-.1,wy,wz+10,wx+.12,wy,wz+10,'#c9a85f',2);
  // yard props
  bale(s,g.x0+.28,g.y1+.28,.34,11);bale(s,g.x0+.28,g.y1+.28,.3,11);crate(s,g.x0+.75,g.y1+.3,.3,10);crate(s,g.x0+.75,g.y1+.3,.26,10);barrel(s,g.x1-.2,g.y1+.26);
  return g.H+g.R+14}

function mill(s,o){
  const cx=o.x+o.w/2,cy=o.y+o.h/2-.05,work=o.jobs?.length>0;
  ground(s,o.x+.02,o.y+.02,o.x+o.w-.02,o.y+o.h-.02,'rgba(215,205,170,.4)');
  s.shadow(px(cx,cy)+8,py(cx,cy,0)+2,56,22);
  T.cx=cx;T.cy=cy;T.n=8;T.rot=PI/8;
  T.r0=.95;T.r1=.86;T.z0=0;T.z1=8;octBody(s,'#bdb298');octTop(s,'#cfc6aa',.86,8);
  T.r0=.78;T.r1=.52;T.z0=8;T.z1=60;octBody(s,'#e6dab8',[24,40]);
  // door, step and windows
  faceQuad(s,PI/4,-.42,.42,8,26,'#8f7656','#ece1c4');
  facePt(PI/4,0,17);L(s,fx,fy,8,fx,fy,26,'#6e5a3f',1);
  faceQuad(s,PI/4,-.5,.5,8,10,'#cbbf9f');
  faceQuad(s,PI/4,-.26,.26,38,50,'#a7c4c1','#ece1c4');
  faceQuad(s,0,-.3,.3,28,38,'#99b9b6','#ddd0b0');
  faceQuad(s,PI/2,-.3,.3,28,38,'#a7c4c1','#ece1c4');
  // balcony ring, cap and finial
  octTop(s,'#9b7f5c',.64,60);octTop(s,'#b49670',.6,61);
  const zc=60;cone(s,'#a98160',.7,zc,86,2);
  E(s,cx,cy,86,1.8,1.8,'#7a6046');L(s,cx,cy,86,cx,cy,94,'#7a6046',1.6);
  // axle and sails: hub sits on the cap, facing the viewer, plane parallel to the screen
  const hx=cx+.34,hy=cy+.34,hz=70;L(s,cx+.1,cy+.1,hz,hx,hy,hz,'#7a6046',5);
  const c=s.c;c.save();c.translate(px(hx,hy),py(hx,hy,hz));c.rotate(s.time*(work?.9:.2)+.45);
  for(let i=0;i<4;i++){c.rotate(PI/2);
    c.beginPath();c.moveTo(-1.4,6);c.lineTo(1.4,6);c.lineTo(1.4,-46);c.lineTo(-1.4,-46);c.closePath();c.fillStyle='#8a7452';c.fill();
    c.beginPath();c.moveTo(2,-11);c.lineTo(13,-12);c.lineTo(13,-43);c.lineTo(2,-44);c.closePath();c.fillStyle='#f1e8c8';c.fill();c.strokeStyle='#9d8b64';c.lineWidth=1;c.stroke();
    c.beginPath();for(let y=-17;y>-43;y-=6){c.moveTo(2,y);c.lineTo(13,y-.3)}c.moveTo(7.5,-11.5);c.lineTo(7.5,-43.5);c.strokeStyle='#bba97f';c.lineWidth=.8;c.stroke();
    c.beginPath();c.moveTo(2,-44);c.lineTo(13,-43);c.moveTo(1.4,-46);c.lineTo(13.5,-46);c.strokeStyle='#8a7452';c.lineWidth=1.6;c.stroke()}
  s.ellipse(0,0,5.2,5.2,'#8a7452');s.ellipse(0,0,2.6,2.6,'#d9ccac');c.restore();
  sack(s,cx+.66,cy+.62);sack(s,cx+.84,cy+.5);sack(s,cx+.54,cy+.8,'#dccfb0');
  return 100}

function coop(s,o){
  const yF=o.y+o.h-.12,yB=o.y+o.h-.55;
  const g=gparams({x0:o.x+.6,y0:o.y+.12,x1:o.x+o.w-.16,y1:yB,H:20,col:'#dcbc8b',roof:'#c0836a',axis:'y',prof:GABLE,R:18,ov:.1,base:'#a98b62',corner:'#f1e1bd',trim:'#e7b79c'},{});
  ground(s,o.x+.02,o.y+.02,o.x+o.w-.02,o.y+o.h-.02,'rgba(222,205,150,.45)');
  const xm=(g.x0+g.x1)/2;
  // nesting box on the left side (added before the body so it hides behind the wall)
  fullBox(s,'#cfae7b',g.x0-.3,g.y0+.35,g.x0,g.y0+.85,0,13,'#dcbc8b');
  body(s,g);
  boards(s,'y',g.y1,g.x0,g.x1,0,g.H,5,'rgba(110,80,40,.22)');boards(s,'x',g.x1,g.y0,g.y1,0,g.H,5,'rgba(90,60,30,.2)');
  // pop-hole with a ramp
  E(s,xm,g.y1,8,6,6.5,'#5b4a3a');L(s,xm,g.y1,2,xm,g.y1+.38,0,'#9b7a4e',5);for(let k=1;k<4;k++)L(s,xm-.04,g.y1+.38*(k/4.2),2*(1-k/4),xm+.04,g.y1+.38*(k/4.2),2*(1-k/4),'#6e5636',1);
  winX(s,g.x1,(g.y0+g.y1)/2,8,.3,.3*0+9,'#9fbab5','#f1e1bd');
  roofOf(s,g);
  // run: low wire fence and a feeder
  yardFence(s,o.x+.14,o.x+o.w-.12,yB,yF,'#b09564',9,'rgba(120,110,80,.5)');
  E(s,o.x+1.45,yF-.2,0,6,3,'#8e7650');
  return 44}

function cowshed(s,o){
  const g=gparams({x0:o.x+.14,y0:o.y+.12,x1:o.x+o.w-.14,y1:o.y+o.h-.55,H:24,col:'#cfa283',roof:'#9b6f5b',axis:'x',prof:GABLE,R:22,ov:.12,base:'#8f7766',corner:'#f0e2c4',trim:'#e8cdb0'},{});
  ground(s,o.x+.02,o.y+.02,o.x+o.w-.02,o.y+o.h-.02,'rgba(210,195,140,.45)');
  body(s,g);const Y=g.y1;
  // open stall front, dark interior, posts and hay
  Q(s,'#5e4a3c',[g.x0+.2,Y,0,g.x1-.2,Y,0,g.x1-.2,Y,19,g.x0+.2,Y,19]);
  for(let i=0;i<=4;i++){const x=g.x0+.2+(g.x1-g.x0-.4)*i/4;L(s,x,Y,0,x,Y,20,'#e5d3b0',2.6)}L(s,g.x0+.2,Y,19,g.x1-.2,Y,19,'#e5d3b0',2.6);
  for(let i=0;i<5;i++)E(s,g.x0+.4+i*.3,Y,2.5,5,2.5,'#dcc47c');
  // gable wall (right) with hay vent
  gableWall(s,'x',g);boards(s,'x',g.x1,g.y0,g.y1,0,g.H,5,'rgba(90,50,40,.18)');
  Q(s,'#5e4a3c',[g.x1,(g.y0+g.y1)/2-.2,g.H+4,g.x1,(g.y0+g.y1)/2+.2,g.H+4,g.x1,(g.y0+g.y1)/2+.2,g.H+12,g.x1,(g.y0+g.y1)/2-.2,g.H+12],'#f0e2c4',1.4);
  roofOf(s,g);
  // ventilator cupola with a little roof
  const vx=(g.x0+g.x1)/2,vy=(g.y0+g.y1)/2,zr=g.H+g.R;fullBox(s,'#e8cdb0',vx-.12,vy-.12,vx+.12,vy+.12,zr-3,zr+9,'#e8cdb0');hipRoof(s,vx-.12,vy-.12,vx+.12,vy+.12,zr+9,8,'#7d5a4b',.06);
  yardFence(s,o.x+.14,o.x+o.w-.12,Y,o.y+o.h-.1,'#b79f72',11);
  // water trough and milk can
  fullBox(s,'#9d8a68',g.x1-.5,g.y1+.2,g.x1-.15,g.y1+.42,0,7,'#9ec1c3');
  cyl(s,g.x1-.62,g.y1+.38,.1,0,11,'#cfd6d0','#e6ebe6');
  return g.H+g.R+18}

function sheepfold(s,o){
  const cx=o.x+o.w/2,cy=o.y+.82;
  ground(s,o.x+.02,o.y+.02,o.x+o.w-.02,o.y+o.h-.02,'rgba(215,205,150,.45)');
  s.shadow(px(cx,cy)+6,py(cx,cy,0)+2,48,19);
  // trellis with a vine along the back
  for(let k=0;k<5;k++){const x=o.x+.2+k*.32;L(s,x,o.y+.1,0,x,o.y+.1,18,'#8a6a45',1.4)}L(s,o.x+.2,o.y+.1,18,o.x+1.48,o.y+.1,18,'#8a6a45',1.2);
  for(let k=0;k<9;k++)E(s,o.x+.22+k*.16,o.y+.1,10+(k%3)*3,2.6,2.2,k%2?'#79a85f':'#6f9a55');
  T.cx=cx;T.cy=cy;T.n=8;T.rot=PI/8;
  T.r0=.74;T.r1=.74;T.z0=0;T.z1=30;octBody(s,'#ded4b5',[15]);
  faceQuad(s,PI/4,-.34,.34,0,19,'#6d5a48','#f0e7cd');faceQuad(s,0,-.22,.22,12,22,'#9fb9b6','#f0e7cd');
  octTop(s,'#c7bc9b',.74,30);
  cone(s,'#d3bf7e',.92,29,58,4);
  // straw tufts hanging from the eave
  for(let k=0;k<8;k++){const a=T.rot+(k+.5)*PI/4;if(Math.cos(a)+Math.sin(a)<0)continue;E(s,cx+Math.cos(a)*.9,cy+Math.sin(a)*.9,27,3.5,2.6,'#c1ad6a')}
  L(s,cx,cy,58,cx,cy,65,'#8f7b50',1.6);
  yardFence(s,o.x+.14,o.x+o.w-.12,o.y+1.45,o.y+o.h-.1,'#b79f72',10);
  // hay rack
  fullBox(s,'#9d8458',o.x+1.45,o.y+1.55,o.x+1.8,o.y+1.75,0,6,'#dcc77c');
  return 70}

function apiary(s,o){
  const g=gparams({x0:o.x+1.1,y0:o.y+.14,x1:o.x+o.w-.16,y1:o.y+.95,H:20,col:'#e0c57f'},{});
  ground(s,o.x+.02,o.y+.02,o.x+o.w-.02,o.y+o.h-.02,'rgba(190,210,140,.5)');
  shadowAt(s,g.x0,g.y0,g.x1,g.y1,40,16);
  shedBox(s,g.col,g.x0,g.y0,g.x1,g.y1,0,g.H,g.H+10);plinth(s,'#a98f57',g.x0,g.y0,g.x1,g.y1,3);
  boards(s,'y',g.y1,g.x0,g.x1,0,g.H,4,'rgba(110,85,40,.25)');boards(s,'x',g.x1,g.y0,g.y1,0,g.H,4,'rgba(90,65,30,.22)');
  doorY(s,g.y1,(g.x0+g.x1)/2,.3,15,'#8f7545','#f6ecc8');
  shedRoof(s,g.x0,g.y0,g.x1,g.y1,g.H,g.H+10,'#a9884f',.1,'y');
  // honey sign
  L(s,g.x1+.14,g.y1+.1,0,g.x1+.14,g.y1+.1,26,'#8f7545',2);Q(s,'#f4e3a6',[g.x1+.14,g.y1-.1,25,g.x1+.14,g.y1+.3,25,g.x1+.14,g.y1+.3,16,g.x1+.14,g.y1-.1,16],'#b69753',1);E(s,g.x1+.14,g.y1+.1,20.5,3.6,3.6,'#d9a54c');
  // flower rows and three painted hives on stands
  for(let i=0;i<6;i++){const x=o.x+.3+i*.28;L(s,x,o.y+1.55,0,x,o.y+1.55,6,'#7ea06a',1);E(s,x,o.y+1.55,8,2.4,2.4,i%2?'#d89aa7':'#e9d28a')}
  const hv=[['#cfe0d1',o.x+.45,o.y+.55],['#efd9a0',o.x+.45,o.y+1.05],['#d9c3d8',o.x+.82,o.y+.85]];
  for(const [c,x,y] of hv){for(const [dx,dy] of [[-.08,-.08],[.08,.08]])L(s,x+dx,y+dy,0,x+dx,y+dy,5,'#8f7545',1.8);fullBox(s,c,x-.13,y-.13,x+.13,y+.13,5,11,sh(c,.1));fullBox(s,sh(c,-.06),x-.13,y-.13,x+.13,y+.13,11,17,sh(c,.1));hipRoof(s,x-.13,y-.13,x+.13,y+.13,17,6,'#a9884f',.04);E(s,x,y+.13,8,1.2,1.2,'#5b4a35')}
  const bx=.5*Math.sin(s.time*1.7);E(s,o.x+.7+bx*.3,o.y+1.1,24+Math.cos(s.time*2)*4,1.6,1.1,'#8a7a50');
  yardFence(s,o.x+.14,o.x+o.w-.12,o.y+1.4,o.y+o.h-.1,'#efe6cc',8);
  return 40}

function goatshed(s,o){
  const g=gparams({x0:o.x+.14,y0:o.y+.12,x1:o.x+o.w-.14,y1:o.y+o.h-.55,H:22,col:'#cba883',roof:'#85a06c',axis:'x',prof:GABLE,R:17,ov:.12,base:'#8f7a5d',corner:'#efe0bd',trim:'#a8bd8c',courses:4},{});
  ground(s,o.x+.02,o.y+.02,o.x+o.w-.02,o.y+o.h-.02,'rgba(210,200,145,.45)');
  body(s,g);const Y=g.y1;boards(s,'y',Y,g.x0,g.x1,0,g.H,5,'rgba(100,70,40,.2)');
  doorY(s,Y,g.x0+.6,.36,16,'#8c6f4f','#efe0bd');winY(s,Y,g.x0+1.25,8,.3,10,'#9db9b4','#efe0bd');
  gableWall(s,'x',g);boards(s,'x',g.x1,g.y0,g.y1,0,g.H,5,'rgba(90,60,40,.18)');
  winX(s,g.x1,(g.y0+g.y1)/2,g.H+3,.24,8,'#7c6a58','#efe0bd');
  roofOf(s,g);
  // turf tufts
  for(let i=0;i<5;i++)E(s,g.x0+.2+i*.32,(g.y0+g.y1)/2+.2,g.H+g.R*.8+(i%2)*3,4,2.4,'#98b27a');
  // climbing rocks and a ramp (goats climb everything)
  fullBox(s,'#b8b5a6',g.x1-.65,g.y1+.2,g.x1-.3,g.y1+.45,0,8,'#cbc8b9');fullBox(s,'#aeab9d',g.x1-.5,g.y1+.25,g.x1-.3,g.y1+.45,8,15,'#c3c0b2');
  yardFence(s,o.x+.14,o.x+o.w-.12,Y,o.y+o.h-.1,'#b79f72',11);
  return g.H+g.R+8}

function rabbit(s,o){
  const x0=o.x+.16,x1=o.x+o.w-.16,y0=o.y+.2,y1=o.y+.85;
  ground(s,o.x+.02,o.y+.02,o.x+o.w-.02,o.y+o.h-.02,'rgba(200,215,150,.45)');
  shadowAt(s,x0,y0,x1,y1,46,16);
  for(const [x,y] of [[x0+.05,y1-.05],[x1-.05,y1-.05],[x1-.05,y0+.05],[x0+.05,y0+.05]])L(s,x,y,0,x,y,9,'#8a7355',3);
  shedBox(s,'#dcc7b3',x0,y0,x1,y1,9,24,31);
  // three compartments with wire fronts
  const n=3,w=(x1-x0)/n;
  for(let i=0;i<n;i++){const a=x0+i*w+.06,b=x0+(i+1)*w-.06;Q(s,'#5f5146',[a,y1,11,b,y1,11,b,y1,21,a,y1,21],'#f1e6d4',1.2);for(let k=1;k<5;k++)L(s,a+(b-a)*k/5,y1,11,a+(b-a)*k/5,y1,21,'rgba(235,225,205,.55)',.7);L(s,a,y1,16,b,y1,16,'rgba(235,225,205,.5)',.7)}
  for(let i=1;i<n;i++)L(s,x0+i*w,y1,9,x0+i*w,y1,24,'#f1e6d4',2);
  winX(s,x1,(y0+y1)/2,12,.34,8,'#8a7c70','#f1e6d4');
  shedRoof(s,x0,y0,x1,y1,24,31,'#9d7b6a',.1,'y');
  // carrot crate, bottle and run
  fullBox(s,'#c9a672',x0+.1,y1+.3,x0+.45,y1+.55,0,8,'#d7a15a');E(s,x0+.2,y1+.4,10,3,3,'#e69a52');E(s,x0+.32,y1+.44,10,3,3,'#e69a52');
  yardFence(s,o.x+.14,o.x+o.w-.12,y1+.18,o.y+o.h-.1,'#c3ad82',9,'rgba(120,110,80,.4)');
  return 40}

function alpaca(s,o){
  const x0=o.x+.2,x1=o.x+o.w-.2,y0=o.y+.15,y1=o.y+o.h-.6;
  ground(s,o.x+.02,o.y+.02,o.x+o.w-.02,o.y+o.h-.02,'rgba(222,208,150,.5)');
  ground(s,x0,y0,x1,y1,'rgba(215,190,125,.7)');
  shadowAt(s,x0,y0,x1,y1,52,20);
  // open shelter: back half-wall, hay rack, posts and a big hip roof
  wallX(s,'#c8a584',x0,y0,y1,0,14,14);wallY(s,'#d6b595',y0,x0,x1,0,14,14);
  fullBox(s,'#9d8458',x0+.25,y0+.1,x1-.25,y0+.3,0,9,'#dcc77c');
  for(const [x,y] of [[x0,y0],[x1,y0],[x0,y1],[x1,y1]])L(s,x,y,0,x,y,34,'#8f6a4e',3.4);
  hipRoof(s,x0,y0,x1,y1,34,24,'#a6735a',.2,.15);
  // hanging sign and feed trough
  L(s,x1-.3,y1+.05,34,x1-.3,y1+.05,26,'#6e553d',1);Q(s,'#f0e2c0',[x1-.5,y1+.06,26,x1-.1,y1+.06,26,x1-.1,y1+.06,17,x1-.5,y1+.06,17],'#8f6a4e',1);E(s,x1-.3,y1+.06,21.5,3,3,'#c58f7b');
  fullBox(s,'#9d8a68',x0+.2,y1+.15,x0+.65,y1+.34,0,7,'#d9c27d');
  yardFence(s,o.x+.14,o.x+o.w-.12,y1+.1,o.y+o.h-.08,'#b79f72',12);
  return 62}

function goose(s,o){
  const g=gparams({x0:o.x+.3,y0:o.y+.14,x1:o.x+o.w-.3,y1:o.y+o.h-.6,H:22,col:'#ebe8da',roof:'#8aa1ad',axis:'y',prof:GABLE,R:22,ov:.12,base:'#b9b8a8',corner:'#cfd6d9',trim:'#d4dde2'},{});
  ground(s,o.x+.02,o.y+.02,o.x+o.w-.02,o.y+o.h-.02,'rgba(205,215,160,.45)');
  // little puddle pond in the yard
  s.ellipse(px(o.x+1.45,o.y+1.55),py(o.x+1.45,o.y+1.55,0),30,12,'#b9cfa8');s.ellipse(px(o.x+1.43,o.y+1.54),py(o.x+1.43,o.y+1.54,0),26,10,'#8fbdb8');s.ellipse(px(o.x+1.41,o.y+1.52),py(o.x+1.41,o.y+1.52,0),19,7,'#7aaeb0');s.line(px(o.x+1.3,o.y+1.5)-6,py(o.x+1.3,o.y+1.5,0)-2,px(o.x+1.3,o.y+1.5)+3,py(o.x+1.3,o.y+1.5,0)-2,'#d6ebe6aa',1.2);
  body(s,g);const xm=(g.x0+g.x1)/2;
  doorY(s,g.y1,xm,.32,17,'#7e97a1','#ffffff',true);E(s,xm,g.y1,22,3,3,'#f6f6ee');
  winX(s,g.x1,(g.y0+g.y1)/2,10,.3,10,'#9fbfc5','#ffffff');
  roofOf(s,g);
  // heart-free little feather sign on the roof edge
  s.line(px(g.x1+.05,g.y1+.05),py(g.x1+.05,g.y1+.05,0),px(g.x1+.05,g.y1+.05),py(g.x1+.05,g.y1+.05,16),'#9b8a6c',2);E(s,g.x1+.05,g.y1+.05,19,5,3,'#f4f4ea');
  yardFence(s,o.x+.14,o.x+o.w-.12,g.y1,o.y+o.h-.1,'#e4e0cc',9);
  return 52}

function tea(s,o){
  const cx=o.x+o.w/2,cy=o.y+o.h/2-.1,work=o.jobs?.length>0;
  ground(s,o.x+.02,o.y+.02,o.x+o.w-.02,o.y+o.h-.02,'rgba(205,215,165,.4)');
  s.shadow(px(cx,cy)+6,py(cx,cy,0)+2,56,22);
  T.cx=cx;T.cy=cy;T.n=8;T.rot=PI/8;
  T.r0=.9;T.r1=.9;T.z0=0;T.z1=5;octBody(s,'#d8c9a4');octTop(s,'#e8dcb8',.9,5);
  // back posts, table, front posts
  for(let k=0;k<8;k++){const a=k*PI/4;if(Math.cos(a)+Math.sin(a)<-.1)post2(s,cx,cy,.8,a)}
  fullBox(s,'#c8a77a',cx-.22,cy-.18,cx+.22,cy+.18,5,17,'#e0c898');E(s,cx,cy,19,5,2.6,'#f1e7d0');s.ellipse(px(cx,cy)-2,py(cx,cy,23),4.4,3.6,'#a9bfb5');s.ellipse(px(cx,cy)+3,py(cx,cy,22),2.5,2.4,'#a9bfb5');
  smoke(s,cx,cy,25,work,.7);
  for(let k=0;k<8;k++){const a=k*PI/4;if(Math.cos(a)+Math.sin(a)>=-.1)post2(s,cx,cy,.8,a)}
  // low railing on the visible side
  for(let k=0;k<8;k++){const a=k*PI/4,b=a+PI/4;if(Math.cos(a+PI/8)+Math.sin(a+PI/8)<.4)continue;if(Math.abs(Math.cos(a+PI/8)-Math.sin(a+PI/8))<.01&&false)continue;L(s,cx+.8*Math.cos(a),cy+.8*Math.sin(a),13,cx+.8*Math.cos(b),cy+.8*Math.sin(b),13,'#c9a577',1.8)}
  // two-tier roof with an upturned finial
  cone(s,'#8fa89c',1.15,36,58,2);cone(s,'#86a094',.62,46,66,1);
  L(s,cx,cy,66,cx,cy,74,'#9b7f5c',1.8);E(s,cx,cy,75,2.2,2.2,'#d8bf7a');
  // lantern
  L(s,cx+.3,cy+.3,36,cx+.3,cy+.3,30,'#7f6a4d',1);E(s,cx+.3,cy+.3,27,3.2,4,'#efd9a0');
  return 92}
function post2(s,cx,cy,r,a){const x=cx+r*Math.cos(a),y=cy+r*Math.sin(a);L(s,x,y,5,x,y,36,'#b9916b',3.2)}

function garage(s,o){
  const g={x0:o.x+.14,y0:o.y+.14,x1:o.x+o.w-.14,y1:o.y+o.h-.5,H:27,col:'#c4c7bb'};
  ground(s,o.x+.02,o.y+.02,o.x+o.w-.02,o.y+o.h-.02,'rgba(190,195,175,.5)');
  shadowAt(s,g.x0,g.y0,g.x1,g.y1);
  box(s,g.col,g.x0,g.y0,g.x1,g.y1,0,g.H);plinth(s,'#9aa097',g.x0,g.y0,g.x1,g.y1,4);
  const Y=g.y1,xm=(g.x0+g.x1)/2;
  // roller door with slats
  Q(s,'#f0eee2',[xm-.62,Y,0,xm+.62,Y,0,xm+.62,Y,21,xm-.62,Y,21]);Q(s,'#8fa6a4',[xm-.57,Y,0,xm+.57,Y,0,xm+.57,Y,19,xm-.57,Y,19]);
  for(let z=3;z<19;z+=3)L(s,xm-.57,Y,z,xm+.57,Y,z,'#788e8c',1);
  winX(s,g.x1,(g.y0+g.y1)/2,13,.4,8,'#a1bdbf','#eceadc');
  // flat roof with a parapet and corrugation
  const z=g.H;top(s,'#7f8e8e',g.x0-.06,g.y0-.06,g.x1+.06,g.y1+.06,z+3,'#a3b0ae');
  for(let i=1;i<9;i++){const x=g.x0-.06+(g.x1-g.x0+.12)*i/9;L(s,x,g.y0-.06,z+3,x,g.y1+.06,z+3,'rgba(60,80,80,.25)',.9)}
  wallY(s,'#a4aeab',g.y1+.06,g.x0-.06,g.x1+.06,z,z+3,z+3);wallX(s,'#8e9997',g.x1+.06,g.y0-.06,g.y1+.06,z,z+3,z+3);
  // sign with a wrench, vent pipe
  Q(s,'#f0e5c0',[xm-.3,Y+.02,z+4,xm+.3,Y+.02,z+4,xm+.3,Y+.02,z+13,xm-.3,Y+.02,z+13],'#8c8571',1);s.line(px(xm-.1,Y),py(xm-.1,Y,z+6),px(xm+.1,Y),py(xm+.1,Y,z+11),'#6f7f7d',2.2);E(s,xm+.12,Y,z+11.5,2.6,2.6,'#6f7f7d');
  chimney(s,g.x0+.3,g.y0+.35,z+3,z+16,'#8d8f86',.07);
  // props: tyres, oil drum, tool box
  for(const [x,y,h] of [[g.x1-.2,Y+.28,0],[g.x1-.2,Y+.28,5]]){cyl(s,x,y,.14,h,h+5,'#4d5a56','#5f6c68')}
  barrel(s,g.x0+.2,Y+.28,.15,14,'#8fa6a4');fullBox(s,'#c7684f',g.x0+.55,Y+.2,g.x0+.85,Y+.38,0,7,'#d98168');
  return z+24}

function bakery(s,o){
  const g=gparams({x0:o.x+.14,y0:o.y+.14,x1:o.x+o.w-.14,y1:o.y+o.h-.3,H:37,col:'#ebd0a7',roof:'#b9724f',base:'#bfa27e',corner:'#fbf1db'},{});
  ground(s,o.x+.02,o.y+.02,o.x+o.w-.02,o.y+o.h-.02,'rgba(215,190,150,.4)');
  shadowAt(s,g.x0,g.y0,g.x1,g.y1);
  box(s,g.col,g.x0,g.y0,g.x1,g.y1,0,g.H);plinth(s,g.base,g.x0,g.y0,g.x1,g.y1,4);corners(s,g.x0,g.y0,g.x1,g.y1,g.H,g.corner);
  const Y=g.y1,xm=(g.x0+g.x1)/2;
  // shop window with striped awning and a counter
  winY(s,Y,xm-.45,9,.62,15,'#b9d1cf','#fbf1db');winY(s,Y,xm+.5,9,.4,15,'#b9d1cf','#fbf1db');
  awning(s,xm-.8,xm+.8,Y,31,.3,8,'#f4ece0','#c97c5c');
  doorX(s,g.x1,(g.y0+g.y1)/2,.34,21,'#9a6f4f','#fbf1db');winX(s,g.x1,g.y0+.4,12,.3,12,'#b9d1cf','#fbf1db');
  // sign: bread loaf on a bracket
  L(s,g.x1+.02,g.y1-.2,34,g.x1+.2,g.y1-.2,34,'#7c6048',1.6);s.ellipse(px(g.x1+.2,g.y1-.2),py(g.x1+.2,g.y1-.2,27),9,5.4,'#e0b062');s.ellipse(px(g.x1+.2,g.y1-.2)-1,py(g.x1+.2,g.y1-.2,28),6,3.2,'#ecc784');
  hipRoof(s,g.x0,g.y0,g.x1,g.y1,g.H,17,g.roof,.1);
  chimney(s,g.x0+.5,g.y0+.5,g.H+8,g.H+28,'#a9715a',.09);smoke(s,g.x0+.5,g.y0+.5,g.H+28,o.jobs?.length>0,1.1);
  // crates of loaves and a barrel
  crate(s,g.x0+.15,Y+.2,.3,9,'#c9a672');crate(s,g.x0+.15,Y+.2,.26,9,'#d4b180');E(s,g.x0+.1,Y+.2,19,4,2.4,'#dba85d');
  barrel(s,g.x1-.15,Y+.2,.14,12,'#b79163');
  return g.H+34}

function feedmill(s,o){
  const g={x0:o.x+.14,y0:o.y+.16,x1:o.x+o.w-.6,y1:o.y+o.h-.4,H:30,col:'#bfc89c'};
  ground(s,o.x+.02,o.y+.02,o.x+o.w-.02,o.y+o.h-.02,'rgba(195,205,150,.45)');
  shadowAt(s,o.x,o.y,o.x+o.w,o.y+o.h,56,21);
  shedBox(s,g.col,g.x0,g.y0,g.x1,g.y1,0,g.H,g.H+14);plinth(s,'#8f9a77',g.x0,g.y0,g.x1,g.y1,4);
  boards(s,'y',g.y1,g.x0,g.x1,4,g.H,5,'rgba(70,90,50,.2)');boards(s,'x',g.x1,g.y0,g.y1,4,g.H,5,'rgba(60,80,45,.18)');
  const Y=g.y1;doorY(s,Y,g.x0+.5,.5,18,'#7b8d6c','#eef0d6');winY(s,Y,g.x1-.4,10,.3,10,'#a9c6bd','#eef0d6');
  Q(s,'#e9efd0',[g.x0+.18,Y,g.H-8,g.x0+.82,Y,g.H-8,g.x0+.82,Y,g.H-1,g.x0+.18,Y,g.H-1]);
  shedRoof(s,g.x0,g.y0,g.x1,g.y1,g.H,g.H+14,'#6f8c6a',.1,'y');
  // silo with a dome, chute into the roof
  const sx=o.x+o.w-.5,sy=o.y+.82;
  s.shadow(px(sx,sy)+4,py(sx,sy,0)+2,26,10);
  cyl(s,sx,sy,.42,0,64,'#d3d8c0','#e3e8d2');
  for(const z of [14,28,42,56])s.c.beginPath(),s.c.ellipse(px(sx,sy),py(sx,sy,z),.42*TW*1.4142,.42*TH*1.4142,0,0,PI),s.c.strokeStyle='rgba(90,100,70,.35)',s.c.lineWidth=1,s.c.stroke();
  {const c=s.c,X=px(sx,sy),Y=py(sx,sy,64),rx=.42*TW*1.4142,ry=.42*TH*1.4142;c.beginPath();c.moveTo(X-rx,Y);c.quadraticCurveTo(X-rx,Y-30,X,Y-30);c.quadraticCurveTo(X+rx,Y-30,X+rx,Y);c.ellipse(X,Y,rx,ry,0,0,PI,false);c.closePath();c.fillStyle='#8aa584';c.fill();
   c.beginPath();c.moveTo(X+rx*.3,Y-24);c.quadraticCurveTo(X+rx,Y-24,X+rx,Y);c.ellipse(X,Y,rx,ry,0,0,Math.acos(.3),true);c.closePath();c.fillStyle='rgba(50,70,50,.2)';c.fill();E(s,sx,sy,92,2,2,'#6f8a6a')}
  // grain sacks on a pallet and a cart wheel
  fullBox(s,'#b79163',g.x0+.1,Y+.18,g.x0+.8,Y+.5,0,3,'#c9a672');sack(s,g.x0+.3,Y+.34,'#eadfbf');sack(s,g.x0+.55,Y+.34,'#e0e3c4');
  return 90}

function kitchen(s,o){
  const x0=o.x+.2,x1=o.x+o.w-.2,y0=o.y+.2,y1=o.y+o.h-.2;
  ground(s,o.x+.02,o.y+.02,o.x+o.w-.02,o.y+o.h-.02,'rgba(220,205,160,.4)');
  shadowAt(s,x0,y0,x1,y1,52,20);
  top(s,'#d4b98a',x0,y0,x1,y1,3);wallY(s,'#bfa371',y1,x0,x1,0,3,3);wallX(s,'#a98e5f',x1,y0,y1,0,3,3);
  for(let i=1;i<6;i++){const x=x0+(x1-x0)*i/6;L(s,x,y0,3,x,y1,3,'rgba(100,80,50,.25)',.9)}
  // back walls (half height) with shelves
  wallX(s,'#d9c29b',x0,y0,y1,3,14,14);wallY(s,'#e6d2ad',y0,x0,x1,3,14,14);
  for(let i=0;i<3;i++){const x=x0+.3+i*.45;E(s,x,y0+.02,20,5,3,'#a9bfb5');E(s,x,y0+.02,26,4,3,'#d9a587')}
  // stove with chimney pipe and a pot
  fullBox(s,'#6e7571',x0+.3,y0+.3,x0+.85,y0+.8,3,18,'#4f5754');E(s,x0+.55,y0+.55,21,8,4,'#3c4442');s.ellipse(px(x0+.55,y0+.55),py(x0+.55,y0+.55,24),6,3.5,'#b5663f');
  L(s,x0+.8,y0+.35,18,x0+.8,y0+.35,76,'#54595a',4);smoke(s,x0+.8,y0+.35,76,true,1);
  // table with food
  fullBox(s,'#c8a77a',x1-.9,y0+.5,x1-.35,y0+1.1,3,16,'#e0c898');E(s,x1-.7,y0+.8,18,4,2.4,'#d9d2c0');E(s,x1-.55,y0+.9,18,3,2,'#c97c5c');
  // posts, beam, lanterns
  for(const [x,y] of [[x0,y0],[x1,y0],[x0,y1],[x1,y1]])L(s,x,y,3,x,y,44,'#9d7b58',3.4);
  hipRoof(s,x0,y0,x1,y1,44,20,'#bd9a68',.12,.2);
  for(let k=0;k<6;k++){const f=(k+.5)/6;L(s,x0+(x1-x0)*f,y1+.06,33,x0+(x1-x0)*f,y1+.06,26,'rgba(150,100,70,.0)',1)}
  // hanging garlands under the front eave
  const c=s.c;c.beginPath();c.moveTo(px(x0,y1),py(x0,y1,42));c.quadraticCurveTo(px((x0+x1)/2,y1),py((x0+x1)/2,y1,30),px(x1,y1),py(x1,y1,42));c.strokeStyle='#a9bf8a';c.lineWidth=1.6;c.stroke();
  for(let i=1;i<6;i++){const f=i/6,x=x0+(x1-x0)*f,zz=41-10*Math.sin(f*PI);E(s,x,y1,zz,2.2,2.2,i%2?'#d89a8c':'#e9d28a')}
  return 84}

function dairy(s,o){
  const g=gparams({x0:o.x+.14,y0:o.y+.14,x1:o.x+o.w-.14,y1:o.y+o.h-.35,H:28,col:'#bfd3c6',roof:'#6f9c8e',axis:'y',prof:GABLE,R:24,ov:.12,base:'#92a899',corner:'#f4f1e2',trim:'#d9ebe3'},{});
  ground(s,o.x+.02,o.y+.02,o.x+o.w-.02,o.y+o.h-.02,'rgba(195,215,185,.4)');
  body(s,g);const xm=(g.x0+g.x1)/2;
  // cheese wheel emblem on the gable
  E(s,xm,g.y1,g.H+9,7,7,'#f4ecd2');E(s,xm,g.y1,g.H+9,5.6,5.6,'#e6c75e');Q(s,'#f4ecd2',[xm,g.y1,g.H+9,xm+.1,g.y1,g.H+14,xm+.2,g.y1,g.H+9]);E(s,xm-.1,g.y1,g.H+8,1,1,'#b99a3c');
  winY(s,g.y1,xm-.5,9,.3,12,'#abc9c7','#f4f1e2');winY(s,g.y1,xm+.5,9,.3,12,'#abc9c7','#f4f1e2');
  doorX(s,g.x1,(g.y0+g.y1)/2+.05,.36,21,'#7a9a98','#f4f1e2');
  const yd=(g.y0+g.y1)/2+.05;
  for(let i=0;i<4;i++){const a=yd-.34+i*.17,b=a+.17;Q(s,i%2?'#f4f1e2':'#7fa9b9',[g.x1,a,27,g.x1,b,27,g.x1+.25,b,22,g.x1+.25,a,22])}
  winX(s,g.x1,g.y0+.4,12,.3,11,'#abc9c7','#f4f1e2');
  roofOf(s,g);
  chimney(s,xm+.05,g.y0+.55,g.H+10,g.H+g.R+6,'#9aa89c',.09);smoke(s,xm+.05,g.y0+.55,g.H+g.R+6,o.jobs?.length>0,.9);
  // milk cans and cheese wheels outside
  for(let i=0;i<2;i++){const x=g.x1-.18,y=g.y1+.2+i*.0,cx=x-i*.3;cyl(s,cx,y,.1,0,13,'#d5dad5','#e8ece7');cyl(s,cx,y,.075,13,17,'#c3cbc5','#d9dfd9')}
  for(let i=0;i<3;i++)cyl(s,g.x0+.3,g.y1+.3,.16,i*5,i*5+5,'#e6c75e','#f1dd8a');
  return g.H+g.R+14}

function loom(s,o){
  const g=gparams({x0:o.x+.14,y0:o.y+.12,x1:o.x+o.w-.14,y1:o.y+o.h-.45,H:28,col:'#cdc2cb',roof:'#8a8795',axis:'x',prof:GABLE,R:22,ov:.12,base:'#9a8f98',corner:'#6f6470',trim:'#a9a6b5',courses:4},{});
  ground(s,o.x+.02,o.y+.02,o.x+o.w-.02,o.y+o.h-.02,'rgba(210,195,205,.4)');
  body(s,g);const Y=g.y1;
  // half-timber framing on both visible walls
  const tim='#6f6470';for(let i=0;i<=4;i++){const x=g.x0+(g.x1-g.x0)*i/4;L(s,x,Y,0,x,Y,g.H,tim,1.8)}L(s,g.x0,Y,g.H*.55,g.x1,Y,g.H*.55,tim,1.8);
  for(let i=0;i<4;i++){const a=g.x0+(g.x1-g.x0)*i/4,b=g.x0+(g.x1-g.x0)*(i+1)/4;L(s,i%2?b:a,Y,0,i%2?a:b,Y,g.H*.55,tim,1.2)}
  for(let i=0;i<=3;i++){const y=g.y0+(g.y1-g.y0)*i/3;L(s,g.x1,y,0,g.x1,y,g.H,tim,1.8)}L(s,g.x1,g.y0,g.H*.55,g.x1,g.y1,g.H*.55,tim,1.8);
  // big workshop window showing warp threads, small door
  const xw=g.x0+(g.x1-g.x0)*.375;Q(s,'#f4ecdd',[xw-.34,Y,6,xw+.34,Y,6,xw+.34,Y,g.H*.55-2,xw-.34,Y,g.H*.55-2]);Q(s,'#8f8195',[xw-.3,Y,8,xw+.3,Y,8,xw+.3,Y,g.H*.55-4,xw-.3,Y,g.H*.55-4]);
  for(let i=0;i<7;i++){const x=xw-.27+i*.09;L(s,x,Y,9,x,Y,g.H*.55-5,['#e6a7b0','#a9c8bd','#e9d28a','#a6b7dc'][i%4],1)}
  doorY(s,Y,g.x0+(g.x1-g.x0)*.78,.32,18,'#7a6a7a','#f4ecdd');
  gableWall(s,'x',g);for(let i=0;i<=3;i++){const y=g.y0+(g.y1-g.y0)*i/3;L(s,g.x1,y,g.H,g.x1,y,g.H+riseAt(GABLE,i/3)*g.R,tim,1.4)}
  winX(s,g.x1,(g.y0+g.y1)/2,g.H+3,.26,9,'#a9bfd0','#f4ecdd');
  roofOf(s,g);
  // dormer on the front slope
  const dx=g.x0+.7,dy=(g.y0+g.y1)/2+.28;fullBox(s,'#cdc2cb',dx-.16,dy-.1,dx+.16,dy+.1,g.H+9,g.H+21,'#cdc2cb');winY(s,dy+.1,dx,g.H+11,.2,7,'#a9bfd0','#f4ecdd');hipRoof(s,dx-.16,dy-.1,dx+.16,dy+.1,g.H+21,7,'#6f6a7d',.05);
  // dyed cloth drying on a line + spinning wheel
  L(s,g.x0,Y+.36,0,g.x0,Y+.36,26,'#8f7a5d',2);L(s,g.x1-.25,Y+.36,0,g.x1-.25,Y+.36,26,'#8f7a5d',2);L(s,g.x0,Y+.36,25,g.x1-.25,Y+.36,25,'#8f7a5d',1.2);
  const cl=['#e6a7b0','#a9c8bd','#e9d28a','#a6b7dc','#d9b5d4'];for(let i=0;i<5;i++){const a=g.x0+.1+i*.28;Q(s,cl[i],[a,Y+.36,25,a+.2,Y+.36,25,a+.2,Y+.36,10+(i%2)*3,a,Y+.36,12])}
  const wx=g.x1-.12,wy=g.y1+.3;s.c.beginPath();s.c.ellipse(px(wx,wy),py(wx,wy,9),8,8,0,0,PI*2);s.c.strokeStyle='#8f7a5d';s.c.lineWidth=1.6;s.c.stroke();for(let k=0;k<4;k++){const a=k*PI/4+(s.time||0)*.3,X=px(wx,wy),Yc=py(wx,wy,9);s.line(X-Math.cos(a)*8,Yc-Math.sin(a)*8,X+Math.cos(a)*8,Yc+Math.sin(a)*8,'#a89573',.8)}
  return g.H+g.R+14}

/* ---------- r4 livestock buildings ---------- */
function pigsty(s,o){
  const x0=o.x+.16,x1=o.x+o.w-.16,y0=o.y+.12,y1=o.y+.9;
  ground(s,o.x+.02,o.y+.02,o.x+o.w-.02,o.y+o.h-.02,'rgba(220,205,160,.45)');
  // mud wallow in the yard
  s.ellipse(px(o.x+1.35,o.y+1.55),py(o.x+1.35,o.y+1.55,0),27,10,'#bfa58a');s.ellipse(px(o.x+1.3,o.y+1.53),py(o.x+1.3,o.y+1.53,0),20,7,'#a98d73');
  shadowAt(s,x0,y0,x1,y1,46,17);
  shedBox(s,'#e6c6b8',x0,y0,x1,y1,0,17,25);plinth(s,'#a98b7d',x0,y0,x1,y1,4);
  boards(s,'y',y1,x0,x1,0,17,4,'rgba(120,70,60,.22)');boards(s,'x',x1,y0,y1,0,17,4,'rgba(100,60,50,.2)');
  doorY(s,y1,x0+.55,.42,13,'#6e5a4c','#f6e6d8',true);
  // painted heart above the door
  E(s,x0+.45,y1,15,2.6,2.6,'#d98d96');E(s,x0+.65,y1,15,2.6,2.6,'#d98d96');Q(s,'#d98d96',[x0+.37,y1,14,x0+.73,y1,14,x0+.55,y1,8]);
  winX(s,x1,(y0+y1)/2,8,.3,8,'#9db7b3','#f6e6d8');
  shedRoof(s,x0,y0,x1,y1,17,25,'#bb8472',.1,'y');
  // feeding trough and a bucket
  fullBox(s,'#9d8a68',o.x+1.55,y1+.18,o.x+1.88,y1+.5,0,6,'#dcc18d');
  cyl(s,x0+1.0,y1+.34,.1,0,9,'#aab6b0','#cdd6d1');
  yardFence(s,o.x+.14,o.x+o.w-.12,y1+.1,o.y+o.h-.1,'#c4a78d',9);
  return 42}

function turkeyYard(s,o){
  const g=gparams({x0:o.x+.3,y0:o.y+.14,x1:o.x+o.w-.2,y1:o.y+.92,H:16,col:'#dcb68b',roof:'#bf7d4c',axis:'y',prof:GAMBREL,R:22,ov:.12,base:'#a07f5b',corner:'#f4e4c4',trim:'#e1b48a'},{});
  ground(s,o.x+.02,o.y+.02,o.x+o.w-.02,o.y+o.h-.02,'rgba(215,198,140,.45)');
  body(s,g);const xm=(g.x0+g.x1)/2;
  boards(s,'y',g.y1,g.x0,g.x1,0,g.H,4,'rgba(110,70,40,.2)');
  doorY(s,g.y1,xm,.34,13,'#7a5c42','#f4e4c4',true);
  winX(s,g.x1,(g.y0+g.y1)/2,8,.3,8,'#9fb9b5','#f4e4c4');
  roofOf(s,g);
  // round loft window high on the gable
  E(s,xm,g.y1+.02,g.H+10,5.5,5.5,'#f4e4c4');E(s,xm,g.y1+.02,g.H+10,3.8,3.8,'#7a5c42');
  // perch rails in the yard with a pumpkin and a hay bale
  for(const x of [o.x+.55,o.x+1.45]){L(s,x,o.y+1.3,0,x,o.y+1.3,16,'#8f6f4d',2.6)}
  L(s,o.x+.5,o.y+1.3,16,o.x+1.5,o.y+1.3,16,'#a98355',2.6);
  bale(s,o.x+1.62,o.y+1.62,.3,10);E(s,o.x+.55,o.y+1.7,5,6,4.5,'#df9a58');L(s,o.x+.55,o.y+1.7,10,o.x+.55,o.y+1.7,13,'#7d9a5f',1.6);
  yardFence(s,o.x+.14,o.x+o.w-.12,g.y1,o.y+o.h-.1,'#b79f72',9);
  return g.H+g.R+14}

function quailHouse(s,o){
  const x0=o.x+.28,x1=o.x+o.w-.18,y0=o.y+.2,y1=o.y+.88;
  ground(s,o.x+.02,o.y+.02,o.x+o.w-.02,o.y+o.h-.02,'rgba(205,215,155,.45)');
  shadowAt(s,x0,y0,x1,y1,46,16);
  for(const [x,y] of [[x0+.05,y1-.05],[x1-.05,y1-.05],[x1-.05,y0+.05],[x0+.05,y0+.05]])L(s,x,y,0,x,y,10,'#8a7355',3);
  // two tiers of wire cages
  for(const [z0,z1,col,wire] of [[10,24,'#e1d3b6','#f6efdb'],[24,38,'#d8c6a5','#f6efdb']]){
    fullBox(s,col,x0,y0,x1,y1,z0,z1,sh(col,.1));
    const n=4,w=(x1-x0)/n;
    for(let i=0;i<n;i++){const a=x0+i*w+.05,b=x0+(i+1)*w-.05;Q(s,'#5f5146',[a,y1,z0+2,b,y1,z0+2,b,y1,z1-2,a,y1,z1-2],wire,1.1);for(let k=1;k<4;k++)L(s,a+(b-a)*k/4,y1,z0+2,a+(b-a)*k/4,y1,z1-2,'rgba(235,225,205,.5)',.6)}
    winX(s,x1,(y0+y1)/2,z0+3,.34,8,'#8c7f72','#f6efdb');
  }
  shedRoof(s,x0,y0,x1,y1,38,45,'#8fae86',.1,'y');
  // seed dish with speckled eggs
  fullBox(s,'#c9a672',x0+.1,y1+.3,x0+.5,y1+.58,0,7,'#d9b57b');E(s,x0+.2,y1+.44,8,3,2.4,'#e4d8c0');E(s,x0+.34,y1+.46,8,3,2.4,'#dccfb4');E(s,x0+.3,y1+.4,8.8,1,1,'#8d7a5c');
  yardFence(s,o.x+.14,o.x+o.w-.12,y1+.15,o.y+o.h-.1,'#c3ad82',9,'rgba(120,110,80,.4)');
  return 56}

function peacockAviary(s,o){
  const x0=o.x+.22,x1=o.x+o.w-.22,y0=o.y+.18,y1=o.y+o.h-.55;
  ground(s,o.x+.02,o.y+.02,o.x+o.w-.02,o.y+o.h-.02,'rgba(190,215,200,.5)');
  ground(s,x0,y0,x1,y1,'rgba(205,210,175,.7)');
  shadowAt(s,x0,y0,x1,y1,54,21);
  // lattice back walls and a perch
  wallX(s,'rgba(170,205,200,.55)',x0,y0,y1,0,32,32);wallY(s,'rgba(190,220,214,.5)',y0,x0,x1,0,32,32);
  for(let k=0;k<=8;k++){const f=k/8;L(s,x0,y0+(y1-y0)*f,0,x0,y0+(y1-y0)*Math.min(1,f+.25),32,'rgba(255,255,255,.55)',.8);L(s,x0+(x1-x0)*f,y0,0,x0+(x1-x0)*Math.min(1,f+.25),y0,32,'rgba(255,255,255,.55)',.8)}
  plinth(s,'#9fb3ad',x0,y0,x1,y1,4);
  L(s,x0+.3,y0+.35,16,x1-.3,y0+.35,16,'#9b7c58',2.4);
  for(const [x,y] of [[x0,y0],[x1,y0],[x0,y1],[x1,y1]])L(s,x,y,0,x,y,34,'#f2ead2',3.4);
  hipRoof(s,x0,y0,x1,y1,34,26,'#6fa69e',.18,.15);
  const cx=(x0+x1)/2,cy=(y0+y1)/2;L(s,cx,cy,60,cx,cy,70,'#d9b95f',1.6);E(s,cx,cy,71,2.6,2.6,'#d9b95f');
  // teal feather medallion on the front beam
  E(s,cx,y1+.02,28,4.6,3.4,'#4f8f8d');E(s,cx,y1+.02,28,2.2,1.8,'#d8c070');
  yardFence(s,o.x+.14,o.x+o.w-.12,y1+.1,o.y+o.h-.08,'#e6e1cc',10);
  return 76}

function angoraPen(s,o){
  const x0=o.x+.2,x1=o.x+o.w-.2,y0=o.y+.15,y1=o.y+.95;
  ground(s,o.x+.02,o.y+.02,o.x+o.w-.02,o.y+o.h-.02,'rgba(215,205,165,.5)');
  shadowAt(s,x0,y0,x1,y1,50,19);
  // lean-to wool shed: tall back wall, lilac sloped roof, open front
  shedBox(s,'#d7c1ca',x0,y0,x1,y1,0,30,20);plinth(s,'#9d8896',x0,y0,x1,y1,4);
  Q(s,'#5b4a52',[x0+.2,y1,0,x1-.2,y1,0,x1-.2,y1,18,x0+.2,y1,18]);
  for(const x of [x0+.2,(x0+x1)/2,x1-.2])L(s,x,y1,0,x,y1,20,'#f1e5d8',2.6);L(s,x0+.2,y1,19,x1-.2,y1,19,'#f1e5d8',2.6);
  shedRoof(s,x0,y0,x1,y1,30,20,'#a68bb0',.12,'y');
  // yarn-drying rack in the yard with hanging skeins
  const ry=o.y+1.45;for(const x of [o.x+.45,o.x+1.45])L(s,x,ry,0,x,ry,26,'#8f7352',2.6);L(s,o.x+.4,ry,26,o.x+1.5,ry,26,'#a98a63',2.6);
  [['#d9a7bb',.62],['#a9c6d6',.84],['#e4d2a0',1.06],['#b9a5d4',1.28]].forEach(([c,dx],i)=>{const x=o.x+dx;const sw=Math.sin(s.time*1.4+i)*.8;L(s,x,ry,26,x,ry,15,c,4);E(s,x+sw*.02,ry,13,2.6,3,sh(c,-.1))});
  bale(s,o.x+1.62,o.y+1.7,.3,10);
  yardFence(s,o.x+.14,o.x+o.w-.12,y1+.2,o.y+o.h-.08,'#c8b4a0',10);
  return 52}

function swanLake(s,o){
  const cx=o.x+1.0,cy=o.y+1.2;
  ground(s,o.x+.02,o.y+.02,o.x+o.w-.02,o.y+o.h-.02,'rgba(200,215,170,.5)');
  const X=px(cx,cy),Y=py(cx,cy,0);
  s.ellipse(X+3,Y+5,70,34,'#c9d6bb');s.ellipse(X,Y,64,30,'#a8c8c4');s.ellipse(X-3,Y-3,54,24,'#b6d3cf');
  for(let i=0;i<3;i++){const f=((s.time*.12)+i*.33)%1;s.c.beginPath();s.c.ellipse(X-14+i*12,Y+2+i*3,10+f*26,4+f*10,0,0,PI*2);s.c.strokeStyle=`rgba(236,246,238,${.55*(1-f)})`;s.c.lineWidth=1.3;s.c.stroke()}
  s.ellipse(X+34,Y-8,7,3,'#86b38a');s.ellipse(X-30,Y+8,6,2.6,'#93bb94');s.ellipse(X+22,Y+14,5,2.2,'#86b38a');
  // pier with a lantern post
  fullBox(s,'#b99a6a',o.x+1.55,o.y+.25,o.x+1.85,o.y+1.05,0,5,'#cfb07e');
  for(const y of [.4,.62,.84])L(s,o.x+1.55,o.y+y,5,o.x+1.85,o.y+y,5,'rgba(90,65,35,.35)',.8);
  L(s,o.x+1.8,o.y+.3,5,o.x+1.8,o.y+.3,30,'#8f7352',2);E(s,o.x+1.8,o.y+.3,32,3.4,3.8,'#f3e3a8');
  // reeds and a little nesting house on stilts
  for(let i=0;i<6;i++){const x=o.x+.12+i*.07,y=o.y+1.62+((i%2)?.07:0),bend=Math.sin(s.time*1.3+i)*1.5;L(s,x,y,0,x+bend*.02,y,22+(i%3)*4,'#7ea06a',1.4);if(i%2)E(s,x+bend*.02,y,26,1.5,3.6,'#8d6e4e')}
  const nx=o.x+.5,ny=o.y+.45;for(const [dx,dy] of [[-.12,-.12],[.12,.12]])L(s,nx+dx,ny+dy,0,nx+dx,ny+dy,10,'#8a7355',2);
  fullBox(s,'#efe8d8',nx-.18,ny-.18,nx+.18,ny+.18,10,22,'#efe8d8');hipRoof(s,nx-.18,ny-.18,nx+.18,ny+.18,22,10,'#8fb2c0',.06);E(s,nx,ny+.18,15,2.6,3.6,'#5b4a52');
  return 44}

/* ---------- r5 production workshops ---------- */
function oilPress(s,o){
  const g=gparams({x0:o.x+.16,y0:o.y+.12,x1:o.x+o.w-.6,y1:o.y+1.0,H:24,col:'#e5d5a0',roof:'#a8693f',axis:'y',prof:GABLE,R:22,ov:.12,base:'#a39069',corner:'#7a5a38',trim:'#f1e6c0',courses:4},{});
  const work=o.jobs?.length>0;
  ground(s,o.x+.02,o.y+.02,o.x+o.w-.02,o.y+o.h-.02,'rgba(220,200,130,.42)');
  body(s,g);const Y=g.y1,xm=(g.x0+g.x1)/2;
  boards(s,'y',Y,g.x0,g.x1,4,g.H,4.5,'rgba(110,80,40,.2)');boards(s,'x',g.x1,g.y0,g.y1,4,g.H,4.5,'rgba(90,65,30,.2)');
  doorY(s,Y,g.x0+.45,.38,17,'#7b5a38','#f1e6c0',true);winY(s,Y,g.x1-.4,9,.28,10,'#a9c6bd','#f1e6c0');
  winX(s,g.x1,(g.y0+g.y1)/2,9,.3,10,'#a9c6bd','#f1e6c0');
  // oil drop emblem on the gable
  E(s,xm,Y,g.H+7,6,6,'#f3e6b5');E(s,xm,Y,g.H+6,4.6,5,'#e3b73d');Q(s,'#e3b73d',[xm-.07,Y,g.H+8,xm,Y,g.H+16,xm+.07,Y,g.H+8]);E(s,xm-.03,Y,g.H+8,1.1,1.5,'#fbf0b8');
  roofOf(s,g);
  // wooden screw press beside the shed
  const qx=o.x+1.62,qy=o.y+.55,sz=26+(work?Math.sin(s.time*2.2)*3.2:0);
  fullBox(s,'#9d7b52',qx-.22,qy-.22,qx+.22,qy+.22,0,5,'#c9a672');
  for(const dx of [-.18,.18])L(s,qx+dx,qy+.19,5,qx+dx,qy+.19,40,'#7a5a38',3.4);
  L(s,qx-.2,qy+.19,38,qx+.2,qy+.19,38,'#6b4c2d',4.4);
  L(s,qx,qy+.19,sz,qx,qy+.19,38,'#a9a08a',2.6);L(s,qx-.15,qy+.19,sz,qx+.15,qy+.19,sz,'#8a6a45',3.4);
  L(s,qx-.3,qy+.19,43,qx+.3,qy+.19,36,'#7a5a38',2.4);E(s,qx+.3,qy+.19,36,2.2,2.2,'#6b4c2d');
  // butter churn and oil barrels at the door
  const cxh=g.x0+1.0,cy=Y+.24;
  cyl(s,cxh,cy,.13,0,22,'#c9a672','#e3c892');for(const z of [5,12,19])s.c.beginPath(),s.c.ellipse(px(cxh,cy),py(cxh,cy,z),.13*TW*1.4142,.13*TH*1.4142,0,0,PI),s.c.strokeStyle='#6b4c2d',s.c.lineWidth=1.3,s.c.stroke();
  const pz=30+(work?Math.sin(s.time*3.4)*4:0);L(s,cxh,cy,22,cxh,cy,pz+8,'#8a6a45',2);E(s,cxh,cy,pz+8,3,2,'#6b4c2d');
  barrel(s,g.x0+.18,Y+.26,.15,14,'#a8793f');E(s,g.x0+.18,Y+.26,14,3.4,1.9,'#e3b73d');
  s.ellipse(px(g.x0+.5,Y+.4),py(g.x0+.5,Y+.4,5),4.6,5.6,'#d9a73b');s.ellipse(px(g.x0+.5,Y+.4)-1,py(g.x0+.5,Y+.4,8),1.8,2.6,'#f3dc86');
  // sunflowers by the fence
  for(let k=0;k<3;k++){const sx=o.x+.22+k*.24,sy=o.y+1.84-(k%2)*.08;L(s,sx,sy,0,sx,sy,17+k*2,'#6f9a55',1.6);E(s,sx,sy,19+k*2,4.8,4.8,'#f0b93a');E(s,sx,sy,19+k*2,2.4,2.4,'#6b4a2b')}
  return g.H+g.R+10}

function juicery(s,o){
  const cx=o.x+.82,cy=o.y+.82,work=o.jobs?.length>0;
  ground(s,o.x+.02,o.y+.02,o.x+o.w-.02,o.y+o.h-.02,'rgba(205,190,215,.42)');
  s.shadow(px(cx,cy)+6,py(cx,cy,0)+2,48,19);
  T.cx=cx;T.cy=cy;T.n=8;T.rot=PI/8;
  T.r0=.7;T.r1=.64;T.z0=0;T.z1=6;octBody(s,'#9c8aa8');octTop(s,'#b4a3be',.64,6);
  T.r0=.6;T.r1=.52;T.z0=6;T.z1=38;octBody(s,'#e2d6e6',[16,28]);
  faceQuad(s,PI/4,-.4,.4,6,25,'#7e5f93','#f3ebf4');faceQuad(s,0,-.3,.3,18,30,'#aac2cf','#f3ebf4');faceQuad(s,PI/2,-.3,.3,18,30,'#b6cad6','#f3ebf4');
  octTop(s,'#8a6b9e',.62,38);
  cone(s,'#7b5f9a',.7,38,64,2);
  // grape bunch finial
  L(s,cx,cy,64,cx,cy,70,'#5f4a76',1.6);for(const [dx,dz,r] of [[-2.6,71,3],[2.6,71,3],[0,67,3],[0,74,2.6]])s.ellipse(px(cx,cy)+dx,py(cx,cy,dz),r,r,'#6a4f89');
  // wooden vat with juice and a copper kettle
  const vx=o.x+1.55,vy=o.y+1.45;
  cyl(s,vx,vy,.34,0,17,'#a8793f','#5f3a64');for(const z of [5,12])s.c.beginPath(),s.c.ellipse(px(vx,vy),py(vx,vy,z),.34*TW*1.4142,.34*TH*1.4142,0,0,PI),s.c.strokeStyle='#5f4026',s.c.lineWidth=1.4,s.c.stroke();
  E(s,vx-.04,vy,17,9,4,'#8c5e94');E(s,vx-.1,vy-.04,18,3,1.4,'#c8a4d0');
  const kx=o.x+.45,ky=o.y+1.55;
  fullBox(s,'#7d6a5a',kx-.2,ky-.12,kx+.2,ky+.12,0,6,'#9c8878');
  cyl(s,kx,ky,.17,6,20,'#c9814f','#e5a273');E(s,kx,ky,20,6.4,3,'#d9945f');
  smoke(s,kx,ky,22,work,.8);
  // crates of grapes
  crate(s,o.x+1.1,o.y+1.7,.3,9,'#c9a672');for(const [dx,dy] of [[-.08,0],[.06,.02],[0,-.06]])E(s,o.x+1.1+dx,o.y+1.7+dy,11,3.4,3.4,'#7b5f9a');
  return 76}

function cannery(s,o){
  const x0=o.x+.14,x1=o.x+o.w-.5,y0=o.y+.12,y1=o.y+1.05,H=26;
  ground(s,o.x+.02,o.y+.02,o.x+o.w-.02,o.y+o.h-.02,'rgba(205,185,170,.42)');
  shadowAt(s,x0,y0,x1,y1,54,20);
  shedBox(s,'#c98f74',x0,y0,x1,y1,0,H,H+6);plinth(s,'#8a6a5a',x0,y0,x1,y1,4);
  // brick courses
  boards(s,'y',y1,x0,x1,4,H,3.2,'rgba(90,50,35,.22)');boards(s,'x',x1,y0,y1,4,H,3.2,'rgba(70,40,30,.2)');
  // wide window with shelves of jars
  const Y=y1,wa=x0+.14,wb=x0+.86;Q(s,'#f1e6d4',[wa-.03,Y,8,wb+.03,Y,8,wb+.03,Y,H-4,wa-.03,Y,H-4]);Q(s,'#7e5a4b',[wa,Y,10,wb,Y,10,wb,Y,H-6,wa,Y,H-6]);
  for(let k=0;k<6;k++){const jx=wa+.06+k*.115;for(const [jz,col] of [[11,['#d9553f','#8b5a4c','#a98b64'][k%3]],[19,['#99b87f','#d9a73b','#8190b8'][k%3]]]){Q(s,col,[jx,Y,jz,jx+.08,Y,jz,jx+.08,Y,jz+5,jx,Y,jz+5]);Q(s,'#e6d9c0',[jx,Y,jz+5,jx+.08,Y,jz+5,jx+.08,Y,jz+6.4,jx,Y,jz+6.4])}}
  L(s,wa,Y,17.5,wb,Y,17.5,'#f1e6d4',1.4);
  doorY(s,Y,x1-.42,.4,18,'#5f7a7c','#f1e6d4');
  winX(s,x1,(y0+y1)/2,9,.34,11,'#a9c6bd','#f1e6d4');
  shedRoof(s,x0,y0,x1,y1,H+6,H+16,'#6f8c8f',.1,'y');
  // tall brick chimney
  chimney(s,x0+.32,y0+.3,H+8,H+46,'#b87c64',.13);smoke(s,x0+.32,y0+.3,H+46,o.jobs?.length>0,1.3);
  // steel retort tank with pipes
  const tx=o.x+1.55,ty=o.y+1.5;
  s.shadow(px(tx,ty)+3,py(tx,ty,0)+2,24,9);
  cyl(s,tx,ty,.32,0,28,'#aeb9bd','#c8d1d4');for(const z of [7,14,21])s.c.beginPath(),s.c.ellipse(px(tx,ty),py(tx,ty,z),.32*TW*1.4142,.32*TH*1.4142,0,0,PI),s.c.strokeStyle='rgba(60,75,80,.4)',s.c.lineWidth=1.2,s.c.stroke();
  E(s,tx,ty,28,8,3.6,'#97a4a8');L(s,tx,ty,28,tx,ty,36,'#6e7c80',2.4);E(s,tx,ty,37,3.4,3.4,'#d9553f');
  L(s,tx-.3,ty,14,x1+.08,y1-.1,14,'#6e7c80',2.6);
  // cases of jars
  crate(s,o.x+.5,o.y+1.58,.34,9,'#c9a672');crate(s,o.x+.88,o.y+1.64,.3,9,'#d4b180');
  for(const [dx,col] of [[.42,'#d9553f'],[.52,'#99b87f'],[.58,'#8b5a4c']])E(s,o.x+dx,o.y+1.58,12,2.6,3.6,col);
  return H+50}

function smokehouse(s,o){
  const g=gparams({x0:o.x+.3,y0:o.y+.14,x1:o.x+o.w-.45,y1:o.y+.98,H:32,col:'#8c6a4a',roof:'#4d4038',axis:'y',prof:GABLE,R:26,ov:.12,base:'#5f4a38',corner:'#3f3226',trim:'#6e5238',courses:4},{});
  const work=o.jobs?.length>0;
  ground(s,o.x+.02,o.y+.02,o.x+o.w-.02,o.y+o.h-.02,'rgba(190,170,130,.45)');
  body(s,g);const Y=g.y1,xm=(g.x0+g.x1)/2;
  // vertical planks
  for(let k=1;k<9;k++){const x=g.x0+(g.x1-g.x0)*k/9;L(s,x,Y,4,x,Y,g.H,'rgba(40,28,16,.32)',1)}
  for(let k=1;k<4;k++){const y=g.y0+(g.y1-g.y0)*k/4;L(s,g.x1,y,4,g.x1,y,g.H,'rgba(30,20,10,.3)',1)}
  // open door with glowing embers and hanging cheese rounds
  Q(s,'#2f2218',[xm-.2,Y,0,xm+.2,Y,0,xm+.2,Y,24,xm-.2,Y,24]);Q(s,'#c9612f',[xm-.17,Y,1,xm+.17,Y,1,xm+.17,Y,5,xm-.17,Y,5]);
  Q(s,'#e8a24a',[xm-.1,Y,1,xm+.1,Y,1,xm+.1,Y,3,xm-.1,Y,3]);
  for(const [dx,dz,col] of [[-.08,19,'#d6a85a'],[.09,17,'#c99a57'],[-.02,12,'#b9854f']]){L(s,xm+dx,Y,24,xm+dx,Y,dz+3,'#1d140c',.9);E(s,xm+dx,Y,dz,2.6,2.6,col)}
  L(s,xm-.22,Y,25,xm+.22,Y,25,'#6e5238',2.6);
  winX(s,g.x1,(g.y0+g.y1)/2,15,.26,9,'#3d3026','#6e5238');
  roofOf(s,g);
  // smoke vent on the ridge and tall flue
  fullBox(s,'#3f3226',xm-.12,(g.y0+g.y1)/2-.12,xm+.12,(g.y0+g.y1)/2+.12,g.H+g.R-3,g.H+g.R+6,'#2f2218');hipRoof(s,xm-.14,(g.y0+g.y1)/2-.14,xm+.14,(g.y0+g.y1)/2+.14,g.H+g.R+6,6,'#4d4038',.06);
  smoke(s,xm,(g.y0+g.y1)/2,g.H+g.R+12,true,work?1.7:.8);
  // firewood stack on the side
  const lx=g.x1+.1;for(let r=0;r<3;r++)for(let k=0;k<(r===2?3:4);k++){const y=g.y0+.18+k*.15+(r===2?.07:0),z=3+r*5.4;E(s,lx,y,z,2.9,2.9,k%2?'#b58a56':'#a07646');E(s,lx,y,z,1.2,1.2,'#d9b886')}
  // axe in a stump
  cyl(s,g.x1+.38,g.y1-.1,.11,0,7,'#8a6a45','#c9a672');L(s,g.x1+.38,g.y1-.1,7,g.x1+.38,g.y1-.1,22,'#6b4c2d',2);Q(s,'#aeb9bd',[g.x1+.32,g.y1-.1,22,g.x1+.46,g.y1-.1,22,g.x1+.46,g.y1-.1,17,g.x1+.32,g.y1-.1,15]);
  return g.H+g.R+30}

function tailor(s,o){
  const g=gparams({x0:o.x+.14,y0:o.y+.12,x1:o.x+o.w-.5,y1:o.y+1.0,H:32,col:'#b9cadd',roof:'#5e7399',axis:'y',prof:GABLE,R:20,ov:.12,base:'#8696ae',corner:'#f4f1e6',trim:'#d9e2ee',courses:3},{});
  ground(s,o.x+.02,o.y+.02,o.x+o.w-.02,o.y+o.h-.02,'rgba(185,200,225,.4)');
  body(s,g);const Y=g.y1,xm=(g.x0+g.x1)/2;
  // two tall arched windows with curtains, a door
  for(const dx of [-.26,.26]){const x=xm+dx;winY(s,Y,x,12,.3,17,'#c3d6e6','#f4f1e6');Q(s,'#e6a7b0',[x-.15,Y,29,x-.02,Y,29,x-.05,Y,15,x-.15,Y,17]);Q(s,'#e6a7b0',[x+.02,Y,29,x+.15,Y,29,x+.15,Y,17,x+.05,Y,15])}
  doorX(s,g.x1,(g.y0+g.y1)/2,.34,20,'#6f7fa8','#f4f1e6');winX(s,g.x1,g.y0+.35,13,.28,13,'#c3d6e6','#f4f1e6');
  // button-shaped emblem on the gable
  E(s,xm,Y,g.H+8,7,7,'#f4f1e6');E(s,xm,Y,g.H+8,5.4,5.4,'#e6a7b0');for(const [dx,dz] of [[-1.7,-1.7],[1.7,-1.7],[-1.7,1.7],[1.7,1.7]])s.ellipse(px(xm,Y)+dx,py(xm,Y,g.H+8)+dz,.9,.9,'#7a4f5a');
  roofOf(s,g);
  // giant spool on the roof ridge
  const rx=xm,ry=(g.y0+g.y1)/2;cyl(s,rx,ry,.1,g.H+g.R-2,g.H+g.R+2,'#c9a672','#e3c892');cyl(s,rx,ry,.075,g.H+g.R+2,g.H+g.R+9,'#d9667a','#e68c9c');cyl(s,rx,ry,.1,g.H+g.R+9,g.H+g.R+11,'#c9a672','#e3c892');
  // dress form and bolts of cloth outside
  const mx=o.x+1.58,my=o.y+1.45;
  L(s,mx,my,0,mx,my,18,'#8a6a45',2.4);L(s,mx-.14,my,0,mx+.14,my,0,'#8a6a45',3);
  s.poly([{x:px(mx,my)-5,y:py(mx,my,38)},{x:px(mx,my)+5,y:py(mx,my,38)},{x:px(mx,my)+8,y:py(mx,my,28)},{x:px(mx,my)+5,y:py(mx,my,17)},{x:px(mx,my)-5,y:py(mx,my,17)},{x:px(mx,my)-8,y:py(mx,my,28)}],'#e6a7b0');
  s.ellipse(px(mx,my),py(mx,my,41),2.6,3.2,'#d9c9b6');s.line(px(mx,my)-6,py(mx,my,29),px(mx,my)+6,py(mx,my,29),'#f4ecdd',1.4);
  const cl=['#8190b8','#e6a7b0','#e9d28a','#a9c8bd'];for(let k=0;k<4;k++)cyl(s,o.x+.3+k*.17,o.y+1.6+(k%2)*.07,.08,0,16-(k%2)*3,cl[k],sh(cl[k],.2));
  fullBox(s,'#c9a672',o.x+.2,o.y+1.55,o.x+1.0,o.y+1.9,0,2,'#d4b180');
  return g.H+g.R+24}

function confectionery(s,o){
  const g=gparams({x0:o.x+.14,y0:o.y+.14,x1:o.x+o.w-.5,y1:o.y+1.02,H:30,col:'#f1cdd3',roof:'#c76f86',base:'#c9a0a8',corner:'#fdf5ee'},{});
  const work=o.jobs?.length>0;
  ground(s,o.x+.02,o.y+.02,o.x+o.w-.02,o.y+o.h-.02,'rgba(240,200,210,.42)');
  shadowAt(s,g.x0,g.y0,g.x1,g.y1,52,20);
  box(s,g.col,g.x0,g.y0,g.x1,g.y1,0,g.H);plinth(s,g.base,g.x0,g.y0,g.x1,g.y1,4);corners(s,g.x0,g.y0,g.x1,g.y1,g.H,g.corner);
  const Y=g.y1,xm=(g.x0+g.x1)/2;
  // display window with a shelf of cakes
  Q(s,'#fdf5ee',[xm-.5,Y,7,xm+.5,Y,7,xm+.5,Y,22,xm-.5,Y,22]);Q(s,'#e9d9e0',[xm-.46,Y,9,xm+.46,Y,9,xm+.46,Y,21,xm-.46,Y,21]);
  L(s,xm-.46,Y,15,xm+.46,Y,15,'#fdf5ee',1.6);
  for(let k=0;k<4;k++){const x=xm-.36+k*.24;E(s,x,Y,17.6,4.2,2.4,['#8a6244','#e4c26b','#b4506a','#7b5f9a'][k]);E(s,x,Y,20,2.4,1.6,'#fdf5ee');E(s,x,Y,10.6,4.2,2.4,['#e9a7b4','#f3d27a','#d98d96','#a9c8bd'][k])}
  // candy-striped scalloped awning
  awning(s,xm-.7,xm+.7,Y,29,.3,8,'#fdf5ee','#e07b94',8);
  doorX(s,g.x1,(g.y0+g.y1)/2,.34,21,'#b4506a','#fdf5ee');winX(s,g.x1,g.y0+.4,12,.3,12,'#c9dfe0','#fdf5ee');
  hipRoof(s,g.x0,g.y0,g.x1,g.y1,g.H,15,g.roof,.1);
  // giant cupcake on the roof
  const rx=xm,ry=(g.y0+g.y1)/2,X=px(rx,ry),Z=py(rx,ry,g.H+14);
  s.poly([{x:X-8,y:Z-4},{x:X+8,y:Z-4},{x:X+6,y:Z+6},{x:X-6,y:Z+6}],'#e9a7b4');s.line(X-3,Z-3,X-2.5,Z+6,'#c9808f',1);s.line(X+3,Z-3,X+2.5,Z+6,'#c9808f',1);
  s.ellipse(X,Z-6,9.4,5.4,'#fdf5ee');s.ellipse(X,Z-11,6.4,4.6,'#fbe3ea');s.ellipse(X,Z-15,3.6,3,'#fdf5ee');s.ellipse(X,Z-19,2.4,2.4,'#d5586f');
  if(work){const f=(s.time*.6)%1;s.ellipse(X+10+Math.sin(s.time*3)*2,Z-8-f*14,1.6,1.6,`rgba(255,240,170,${1-f})`)}
  // chimney with sugary smoke, lollipop sign and a tiered cake stand
  chimney(s,g.x1-.3,g.y0+.3,g.H+8,g.H+26,'#c9808f',.1);smoke(s,g.x1-.3,g.y0+.3,g.H+26,work,1);
  L(s,g.x1+.06,Y-.25,0,g.x1+.06,Y-.25,36,'#fdf5ee',2.2);const lx=px(g.x1+.06,Y-.25),lz=py(g.x1+.06,Y-.25,40);s.ellipse(lx,lz,7,7,'#e07b94');s.ellipse(lx,lz,4.4,4.4,'#fdf5ee');s.ellipse(lx,lz,2,2,'#e07b94');
  const sx=g.x0+.2,sy=Y+.3;cyl(s,sx,sy,.16,0,3,'#fdf5ee','#fdf5ee');L(s,sx,sy,3,sx,sy,12,'#c9a0a8',2);cyl(s,sx,sy,.2,12,15,'#fdf5ee','#fdf5ee');E(s,sx,sy,18,4.4,2.6,'#8a6244');E(s,sx,sy,21,3,1.8,'#fbe3ea');E(s,sx,sy,24,1.4,1.4,'#d5586f');
  return g.H+15+26}

function generic(s,o){
  const g=gparams({x0:o.x+.14,y0:o.y+.14,x1:o.x+o.w-.14,y1:o.y+o.h-.3,H:28,col:'#d1bfa0',roof:'#9a987b',axis:'y',prof:GABLE,R:20,ov:.12,base:'#a69c84',corner:'#efe3c6',trim:'#c8c8aa'},{});
  body(s,g);const xm=(g.x0+g.x1)/2;doorY(s,g.y1,xm,.34,19);winX(s,g.x1,(g.y0+g.y1)/2,11,.3,12);roofOf(s,g);return g.H+g.R+10}

/* ---------- r9 workshops: creamery (молокозавод), sausage shop (колбасный цех) and the cattle barn (хлев) ---------- */
function creamery(s,o){
  const g=gparams({x0:o.x+.14,y0:o.y+.14,x1:o.x+o.w-.5,y1:o.y+1.02,H:30,col:'#e4eef0',roof:'#6f9db0',base:'#a9bcc2',corner:'#fdfcf3'},{});
  const work=o.jobs?.length>0;
  ground(s,o.x+.02,o.y+.02,o.x+o.w-.02,o.y+o.h-.02,'rgba(200,225,230,.42)');
  shadowAt(s,g.x0,g.y0,g.x1,g.y1,52,20);
  box(s,g.col,g.x0,g.y0,g.x1,g.y1,0,g.H);plinth(s,g.base,g.x0,g.y0,g.x1,g.y1,4);corners(s,g.x0,g.y0,g.x1,g.y1,g.H,g.corner);
  const Y=g.y1,xm=(g.x0+g.x1)/2;
  // horizontal blue band, a big arched window with milk bottles and a counter door
  Q(s,'#8fb7c6',[g.x0,Y,g.H-8,g.x1,Y,g.H-8,g.x1,Y,g.H-3,g.x0,Y,g.H-3]);Q(s,'#8fb7c6',[g.x1,g.y0,g.H-8,g.x1,g.y1,g.H-8,g.x1,g.y1,g.H-3,g.x1,g.y0,g.H-3]);
  Q(s,'#fdfcf3',[xm-.5,Y,6,xm+.5,Y,6,xm+.5,Y,21,xm-.5,Y,21]);Q(s,'#cfe3e6',[xm-.46,Y,8,xm+.46,Y,8,xm+.46,Y,20,xm-.46,Y,20]);
  L(s,xm-.46,Y,13.5,xm+.46,Y,13.5,'#fdfcf3',1.6);
  for(let k=0;k<5;k++){const x=xm-.36+k*.18;E(s,x,Y,16.6,2.4,3.2,'#fdfcf3');E(s,x,Y,19.4,1.3,1.3,'#6f9db0');E(s,x,Y,10.4,2.4,3.2,k%2?'#f3e2ea':'#fdfcf3')}
  awning(s,xm-.66,xm+.66,Y,27,.28,7,'#fdfcf3','#6f9db0',8);
  doorX(s,g.x1,(g.y0+g.y1)/2,.34,21,'#6f9db0','#fdfcf3');winX(s,g.x1,g.y0+.4,12,.3,12,'#c9dfe0','#fdfcf3');
  hipRoof(s,g.x0,g.y0,g.x1,g.y1,g.H,15,g.roof,.1);
  // a giant milk bottle on the roof
  const rx=xm,ry=(g.y0+g.y1)/2,X=px(rx,ry),Z=py(rx,ry,g.H+13);
  s.poly([{x:X-8,y:Z+3},{x:X+8,y:Z+3},{x:X+8,y:Z-8},{x:X+4,y:Z-14},{x:X+4,y:Z-19},{x:X-4,y:Z-19},{x:X-4,y:Z-14},{x:X-8,y:Z-8}],'#fdfcf3','#b9cdd3',1);
  s.poly([{x:X-8,y:Z+3},{x:X+8,y:Z+3},{x:X+8,y:Z-4},{x:X-8,y:Z-4}],'#e9f2f4');s.ellipse(X,Z-21,5,2.6,'#6f9db0');
  if(work){const f=(s.time*.6)%1;s.ellipse(X+10+Math.sin(s.time*3)*2,Z-6-f*14,1.6,1.6,`rgba(255,255,255,${1-f})`)}
  // steaming pasteurizer tank with a chimney, milk cans and a pallet by the wall
  cyl(s,g.x1+.14,g.y0+.3,.2,0,26,'#c9d2d4','#e8eef0');L(s,g.x1+.14,g.y0+.3,26,g.x1+.14,g.y0+.3,32,'#8f9a9d',2);smoke(s,g.x1+.14,g.y0+.3,32,work,.9);
  for(let k=0;k<3;k++){const cx=g.x0+.2+k*.2;cyl(s,cx,Y+.3,.09,0,9,'#cfd6d0','#eef3ef');L(s,cx,Y+.3,9,cx,Y+.3,11,'#6f9db0',2)}
  fullBox(s,'#c9a672',g.x0+.75,Y+.22,g.x0+1.1,Y+.5,0,3,'#d9b886');
  return g.H+15+30}

function sausageShop(s,o){
  const g=gparams({x0:o.x+.14,y0:o.y+.14,x1:o.x+o.w-.5,y1:o.y+1.02,H:30,col:'#d99a86',roof:'#7a3f38',axis:'y',prof:GABLE,R:22,ov:.12,base:'#9a6254',corner:'#f6e3cf',trim:'#c07763',courses:4},{});
  const work=o.jobs?.length>0;
  ground(s,o.x+.02,o.y+.02,o.x+o.w-.02,o.y+o.h-.02,'rgba(225,185,165,.4)');
  body(s,g);const Y=g.y1,xm=(g.x0+g.x1)/2;
  // brick courses
  for(let z=6;z<g.H;z+=4)L(s,g.x0,Y,z,g.x1,Y,z,'rgba(110,50,40,.22)',.9);
  for(let z=6;z<g.H;z+=4)L(s,g.x1,g.y0,z,g.x1,g.y1,z,'rgba(90,40,30,.2)',.9);
  // shop window with hanging sausage garlands and a striped awning
  Q(s,'#f6e3cf',[xm-.52,Y,6,xm+.52,Y,6,xm+.52,Y,22,xm-.52,Y,22]);Q(s,'#5a3a32',[xm-.47,Y,8,xm+.47,Y,8,xm+.47,Y,21,xm-.47,Y,21]);
  L(s,xm-.45,Y,20,xm+.45,Y,20,'#c9a672',1.4);
  for(let k=0;k<6;k++){const x=xm-.4+k*.16;L(s,x,Y,20,x,Y,16,'#c9a672',.8);E(s,x,Y,14.4,2,4.4,k%2?'#c9726a':'#e19a8c');E(s,x,Y,11,2,2.6,k%2?'#e19a8c':'#c9726a')}
  awning(s,xm-.68,xm+.68,Y,28,.28,7,'#f6e3cf','#b24f45',8);
  doorX(s,g.x1,(g.y0+g.y1)/2,.34,21,'#6e3b33','#f6e3cf');winX(s,g.x1,g.y0+.4,12,.3,12,'#d7c2a8','#f6e3cf');
  // sign with a little sausage ring
  L(s,g.x0+.1,Y+.02,26,g.x0+.1,Y+.02,38,'#4f4638',2);Q(s,'#f6e3cf',[g.x0+.1,Y+.04,38,g.x0+.5,Y+.04,38,g.x0+.5,Y+.04,28,g.x0+.1,Y+.04,28]);
  E(s,g.x0+.3,Y+.05,33,5,3.6,'#c9726a');E(s,g.x0+.3,Y+.05,33,2.6,1.8,'#f6e3cf');
  roofOf(s,g);
  // smoking chimney, a little wood stack
  chimney(s,g.x1-.3,g.y0+.3,g.H+6,g.H+34,'#8a5a4a',.12);smoke(s,g.x1-.3,g.y0+.3,g.H+34,work,1.5);
  const lx=g.x1+.1;for(let r=0;r<2;r++)for(let k=0;k<3;k++){const y=g.y0+.2+k*.16,z=3+r*5.4;E(s,lx,y,z,2.9,2.9,k%2?'#b58a56':'#a07646');E(s,lx,y,z,1.2,1.2,'#d9b886')}
  return g.H+g.R+34}

function cattleBarn(s,o){
  const g=gparams({x0:o.x+.18,y0:o.y+.12,x1:o.x+o.w-.18,y1:o.y+o.h-.55,H:22,col:'#b8574a',roof:'#6e5a52',axis:'x',prof:GAMBREL,R:26,ov:.12,base:'#8a4b42',corner:'#f6e8d4',trim:'#f1e3cb'},{});
  ground(s,o.x+.02,o.y+.02,o.x+o.w-.02,o.y+o.h-.02,'rgba(205,190,140,.45)');
  body(s,g);const Y=g.y1;
  boards(s,'y',Y,g.x0,g.x1,0,g.H,4,'rgba(90,30,24,.22)');
  // big double door with white cross braces, hayloft hatch above
  const xm=(g.x0+g.x1)/2;Q(s,'#f6e8d4',[xm-.42,Y,0,xm+.42,Y,0,xm+.42,Y,18,xm-.42,Y,18]);Q(s,'#8f3f36',[xm-.37,Y,1,xm+.37,Y,1,xm+.37,Y,17,xm-.37,Y,17]);
  L(s,xm,Y,1,xm,Y,17,'#f6e8d4',1.6);L(s,xm-.37,Y,1,xm,Y,17,'#f6e8d4',1.3);L(s,xm+.37,Y,1,xm,Y,17,'#f6e8d4',1.3);
  gableWall(s,'x',g);
  winX(s,g.x1,(g.y0+g.y1)/2,9,.3,8,'#d9c9a8','#f6e8d4');
  roofOf(s,g);
  const vx=(g.x0+g.x1)/2,vy=(g.y0+g.y1)/2,zr=g.H+g.R;fullBox(s,'#f1e3cb',vx-.1,vy-.1,vx+.1,vy+.1,zr-3,zr+7,'#f1e3cb');hipRoof(s,vx-.1,vy-.1,vx+.1,vy+.1,zr+7,7,'#6e5a52',.06);
  yardFence(s,o.x+.14,o.x+o.w-.12,Y,o.y+o.h-.1,'#b79f72',11);
  // feed trough, hay bale and a salt lick
  fullBox(s,'#9d8a68',g.x1-.5,g.y1+.2,g.x1-.15,g.y1+.42,0,7,'#dcc47c');
  bale(s,g.x0+.25,g.y1+.4,.3,10);
  cyl(s,g.x0+.8,g.y1+.45,.08,0,6,'#e9e4d8','#f6f2e8');
  return g.H+g.R+18}

/* Late workshops share carpentry, but have their own equipment and shop signs. */
function lateWorkshop(s,o){
 const soap=o.type==='soapery',noodle=o.type==='noodle_shop';
 const g=gparams({x0:o.x+.12,y0:o.y+.12,x1:o.x+1.7,y1:o.y+1.25,H:32,col:soap?'#ded7e5':noodle?'#ead4ab':'#e2c5b7',roof:soap?'#8b82a3':noodle?'#b88e5a':'#a7686e',base:'#b5aa8c',corner:'#f8eed7',axis:'y',prof:GABLE,R:19,ov:.12},{});
 shadowAt(s,g.x0,g.y0,g.x1,g.y1);body(s,g);doorY(s,g.y1,g.x0+.32,.34,23);winY(s,g.y1,g.x1-.4,12,.46,13);winX(s,g.x1,o.y+.58,11,.5,14);roofOf(s,g);
 const x=o.x+.98,y=o.y+1.66;
 fullBox(s,'#ab8b64',x-.52,y-.1,x+.56,y+.12,0,11,'#e3c69a');
 if(soap){for(let k=0;k<4;k++){fullBox(s,k%2?'#b0bf91':'#c0abc9',x-.42+k*.23,y-.02,x-.23+k*.23,y+.09,11,16);E(s,x-.32+k*.23,y+.1,14,2,1,'#f5eee0')}for(let k=0;k<3;k++){L(s,g.x1,o.y+.68,20+k*3,g.x1,o.y+.68,35+k*2,'#8ba275',1);E(s,g.x1,o.y+.68,35+k*2,2.5,4,'#ac9dbd')}}
 else if(noodle){for(let dx of [-.44,.44])L(s,x+dx,y,12,x+dx,y,34,'#97734e',2);L(s,x-.44,y,34,x+.44,y,34,'#97734e',2);for(let k=0;k<8;k++)L(s,x-.36+k*.1,y,32,x-.36+k*.1,y,16+(k%3),'#f2d998',1.5);E(s,g.x1,o.y+.68,31,8,6,'#f2dda6');L(s,g.x1,o.y+.5,26,g.x1,o.y+.88,35,'#936c49',1.8)}
 else{for(let k=0;k<3;k++){fullBox(s,['#9f5368','#c59158','#9ba866'][k],x-.4+k*.3,y-.04,x-.19+k*.3,y+.09,11,23);fullBox(s,'#ede3c7',x-.36+k*.3,y-.01,x-.23+k*.3,y+.06,23,27);E(s,x-.3+k*.3,y+.1,18,3,3,'#eddbad')}chimney(s,o.x+.38,o.y+.4,43,66,'#ba9678',.1);smoke(s,o.x+.38,o.y+.4,66,!!o.jobs?.length,.6)}
 return 76;
}
function lateAnimalHouse(s,o){
 const silk=o.type==='silk_house',yak=o.type==='yak_pen',pheasant=o.type==='pheasantry';
 const g=gparams({x0:o.x+.16,y0:o.y+.14,x1:o.x+1.76,y1:o.y+.96,H:yak?30:25,col:silk?'#e0d9bf':yak?'#c1af96':pheasant?'#d5c39f':'#dbbd92',roof:silk?'#93aa87':yak?'#7d8d87':pheasant?'#929e76':'#ba906b',base:'#afa38a',corner:'#eee5cb',axis:'y',prof:GABLE,R:yak?25:18,ov:.13},{});
 ground(s,o.x+.04,o.y+.04,o.x+1.96,o.y+1.94,'#bbc79c');shadowAt(s,g.x0,g.y0,g.x1,g.y1);body(s,g);doorY(s,g.y1,o.x+.84,.62,23,'#75684e');winX(s,g.x1,o.y+.54,11,.3,10);roofOf(s,g);
 for(let k=0;k<5;k++){const x=o.x+.16+k*.42;L(s,x,o.y+1.82,0,x,o.y+1.82,pheasant?29:16,'#b09a72',2)}
 for(let z of [7,14])L(s,o.x+.16,o.y+1.82,z,o.x+1.84,o.y+1.82,z,'#c4ad81',2);
 if(pheasant){for(let k=0;k<9;k++)L(s,o.x+.16+k*.21,o.y+1.82,15,o.x+.16+k*.21,o.y+1.82,36,'#9da98d',.6);L(s,o.x+.16,o.y+1.82,36,o.x+1.84,o.y+1.82,36,'#a9af8d',1.3)}
 if(silk){fullBox(s,'#aa9569',o.x+1.22,o.y+1.18,o.x+1.7,o.y+1.56,0,10,'#9fb17b');for(let k=0;k<5;k++)E(s,o.x+1.3+(k%2)*.2,o.y+1.24+Math.floor(k/2)*.1,12,3,2,'#f4ebd0');L(s,o.x+.4,o.y+1.35,0,o.x+.4,o.y+1.35,25,'#8b8863',2);E(s,o.x+.4,o.y+1.35,23,10,7,'#8ea76c')}
 if(yak){for(let k=0;k<3;k++)E(s,o.x+1.45,o.y+1.35,4+k*3,9-k,4,'#b5b4a3');fullBox(s,'#c7aa70',o.x+.25,o.y+1.1,o.x+.65,o.y+1.4,0,10,'#d8c486')}
 if(!silk&&!yak&&!pheasant){E(s,o.x+1.5,o.y+1.38,1,12,5,'#b69c6f');for(let k=0;k<3;k++)E(s,o.x+1.44+k*.08,o.y+1.38,5,3.4,4.5,'#f1e6c9')}
 return 68;
}
/* «Бодрильня» (energy_shop): warm brick-and-plaster workshop, copper brewing tank on the roof, cans of farm energy drinks at the door. */
function energyShop(s,o){
  const g=gparams({x0:o.x+.14,y0:o.y+.14,x1:o.x+o.w-.36,y1:o.y+o.h-.62,H:30,col:'#e6caa1',roof:'#6f978a',base:'#b8735a',baseH:9,corner:'#f7ecd2',axis:'y',prof:GABLE,R:20,ov:.12,trim:'#d8e6dc'},{});
  ground(s,o.x+.02,o.y+.02,o.x+o.w-.02,o.y+o.h-.02,'rgba(214,190,150,.42)');
  shadowAt(s,g.x0,g.y0,g.x1,g.y1);body(s,g);
  const Y=g.y1,xm=(g.x0+g.x1)/2;
  boards(s,'y',Y,g.x0,g.x1,1,8,3,'rgba(120,60,40,.22)');boards(s,'x',g.x1,g.y0,g.y1,1,8,3,'rgba(100,50,35,.22)');
  doorY(s,Y,g.x0+.38,.36,21,'#7f9a6c','#f7ecd2');winY(s,Y,xm+.32,10,.5,12,'#b9d1cf','#f7ecd2');winX(s,g.x1,(g.y0+g.y1)/2,11,.42,12,'#a9c4c2','#ece0c4');
  awning(s,xm-.02,g.x1-.06,Y,27,.26,7,'#f3ead6','#8fb276',4);
  // sign above the door: green leaf with a honey-coloured lightning bolt
  const sx=g.x0+.38;Q(s,'#f3e6c4',[sx-.26,Y+.01,24,sx+.26,Y+.01,24,sx+.26,Y+.01,33,sx-.26,Y+.01,33]);
  E(s,sx,Y+.02,28.5,6,3.4,'#86ad70');Q(s,'#e8b54a',[sx+.03,Y+.03,32,sx-.08,Y+.03,28,sx,Y+.03,28.5,sx-.04,Y+.03,25,sx+.08,Y+.03,29.4,sx,Y+.03,29]);
  roofOf(s,g);
  // copper brewing tank on the roof with a pressure gauge and a pipe down the shaded wall
  const tx=xm-.05,ty=g.y0+.48,tz=g.H+12;
  cyl(s,tx,ty,.2,tz,tz+16,'#c98c5a','#e0ad7c');E(s,tx,ty,tz+19,3,2,'#a8714a');L(s,tx,ty,tz+16,tx,ty,tz+21,'#8a5a3a',1.6);
  L(s,tx+.12,ty+.12,tz+8,g.x1+.04,ty+.12,tz+2,'#a8714a',2.4);L(s,g.x1+.04,ty+.12,tz+2,g.x1+.04,ty+.12,4,'#a8714a',2.4);
  E(s,tx+.14,ty+.14,tz+10,2.3,2.3,'#f3ead6');L(s,tx+.14,ty+.14,tz+10,tx+.17,ty+.14,tz+11.4,'#6b4a33',.8);
  smoke(s,tx,ty,tz+21,!!o.jobs?.length,.7);
  // yard: a crate of cans (berry, honey, forest), a keg with a hose, a stack of crates
  const cx=g.x0+.5,cy=o.y+o.h-.3;
  fullBox(s,'#c9a672',cx-.3,cy-.16,cx+.3,cy+.16,0,7,'#d8b886');boards(s,'y',cy+.16,cx-.3,cx+.3,0,7,3.5,'rgba(80,55,30,.3)');
  ['#c25a6a','#e3b04a','#7fa36a','#e3b04a','#c25a6a'].forEach((c,k)=>{const ux=cx-.22+k*.11;cyl(s,ux,cy,.045,7,12,c,'#f1ead8')});
  const kx=g.x1+.18,ky=cy-.02;barrel(s,kx,ky,.15,13,'#b98b5c');
  s.line(px(kx,ky)-2,py(kx,ky,13),px(g.x1+.04,ty+.12)+3,py(g.x1+.04,ty+.12,6),'#5f6b5e',1.6);
  fullBox(s,'#b48f63',kx+.12,ky-.42,kx+.42,ky-.14,0,8,'#c9a57a');fullBox(s,'#c9a672',kx+.15,ky-.4,kx+.39,ky-.16,8,15,'#d8b886');
  return g.H+g.R+30}
/* ---------- textile workshops: spinnery (Прядильня) and weavery (Ткацкая) ---------- */
/* A wheel standing in a plane parallel to the lit wall (x–z): centre (x,y,z), radius r in tiles, spokes at angle turn. */
function wheelXZ(s,x,y,z,r,turn,rim,spoke){const c=s.c,X=px(x,y),Y=py(x,y,z),K=34,pt=a=>[X+Math.cos(a)*r*TW,Y+Math.cos(a)*r*TH-Math.sin(a)*r*K];
  c.beginPath();for(let k=0;k<8;k++){const [u,v]=pt(turn+k*PI/4);c.moveTo(X,Y);c.lineTo(u,v)}c.strokeStyle=spoke;c.lineWidth=1.1;c.lineCap='round';c.stroke();
  c.beginPath();for(let k=0;k<=28;k++){const [u,v]=pt(k*PI/14);if(k)c.lineTo(u,v);else c.moveTo(u,v)}c.closePath();
  c.strokeStyle=rim;c.lineWidth=3;c.lineJoin='round';c.stroke();c.strokeStyle=sh(rim,.32);c.lineWidth=1;c.stroke();
  s.ellipse(X,Y,2.6,2.6,sh(rim,-.12));s.ellipse(X-.5,Y-.5,1.1,1.1,sh(rim,.4));return pt}
/* Saxony spinning wheel: the wheel at (x,y), bench and flyer towards -x. turn = wheel angle (0 = at rest). */
function spinningWheel(s,x,y,turn,yarn){const wood='#9a7550',d=sh(wood,-.2),r=.23,zc=14,fx=x-.44;
  L(s,fx+.02,y-.07,0,fx+.06,y-.04,10,d,2);L(s,x+.12,y-.05,0,x+.08,y-.03,6,d,2);
  // treadle on the ground and the footman rod up to the crank
  L(s,x-.02,y+.08,1,x-.3,y+.08,2.5,sh(wood,-.08),3);
  const cx=Math.cos(turn)*2.2,cz=Math.sin(turn)*2.2;s.line(px(x,y)+cx,py(x,y,zc)-cz,px(x-.08,y+.08),py(x-.08,y+.08,2),'#7b5d3f',1.1);
  const pt=wheelXZ(s,x,y,zc,r,turn,'#8a6745','#b8956a');
  // uprights, sloping bench and front legs
  L(s,x+.03,y+.05,6,x,y+.05,zc,wood,2.2);L(s,x+.12,y,6,fx,y,10,wood,3.4);L(s,x+.12,y,6.6,fx,y,10.6,sh(wood,.22),1);
  L(s,fx+.02,y+.07,0,fx+.06,y+.04,10,wood,2.2);L(s,x+.12,y+.06,0,x+.08,y+.03,6,wood,2.2);
  // maidens with the flyer and a full bobbin
  L(s,fx-.06,y,10,fx-.06,y,21,wood,1.8);L(s,fx+.12,y,10,fx+.12,y,21,wood,1.8);
  L(s,fx-.04,y,18,fx+.08,y,18,yarn,5.2);L(s,fx-.03,y,19.2,fx+.07,y,19.2,sh(yarn,.25),1.4);
  E(s,fx+.1,y,18,1.8,2.4,sh(wood,-.05));
  // drive band from the rim to the whorl
  const [a1,b1]=pt(PI*.62),[a2,b2]=pt(PI*1.38),W={x:px(fx+.1,y),y:py(fx+.1,y,18)};
  s.line(a1,b1,W.x,W.y-2,'#efe3c6',.8);s.line(a2,b2,W.x,W.y+2,'#efe3c6',.8);
  E(s,fx-.07,y,22,1.4,1.4,sh(wood,.15))}
/* Round willow basket; fill 'wool' = fleece, otherwise a list of yarn ball colours. */
function woolBasket(s,x,y,r,fill){cyl(s,x,y,r,0,8,'#c09868','#8f6c45');const X=px(x,y),rx=r*TW*1.4142,ry=r*TH*1.4142,c=s.c;
  for(const z of [2.7,5.4]){c.beginPath();c.ellipse(X,py(x,y,z),rx,ry,0,0,PI);c.strokeStyle='rgba(110,78,42,.45)';c.lineWidth=1;c.stroke()}
  const Y=py(x,y,8);
  if(fill==='wool'){for(const [dx,dy,a,b] of [[-.42,.05,.42,.36],[.38,0,.44,.38],[0,-.3,.5,.4],[-.08,.15,.46,.34]])s.ellipse(X+dx*rx,Y+dy*ry-2,a*rx,b*rx,'#f3eee2');s.ellipse(X-.12*rx,Y-.4*ry-3,.3*rx,.22*rx,'#fffaf0')}
  else fill.forEach((col,i)=>{const dx=(i-(fill.length-1)/2)*rx*.55,dy=(i%2?-.9:.3);s.ellipse(X+dx,Y+dy-2.4,3.4,3.2,col);s.line(X+dx-2.4,Y+dy-3.6,X+dx+2,Y+dy-1.2,sh(col,.25),.8)});
  c.beginPath();c.ellipse(X,Y,rx,ry,0,0,PI);c.strokeStyle='#b08a5c';c.lineWidth=1.6;c.stroke()}
/* Cloth roll lying along x: from x to x+len, axis at height z, radius r (tiles); the +x end shows the wound spiral. */
function clothRoll(s,x,y,z,len,r,col,band){const K=34,cap=(xx,rr,f)=>{const X=px(xx,y),Y=py(xx,y,z),c=s.c;c.beginPath();for(let k=0;k<16;k++){const a=k*PI/8;const u=X-Math.cos(a)*rr*TW,v=Y+Math.cos(a)*rr*TH-Math.sin(a)*rr*K;if(k)c.lineTo(u,v);else c.moveTo(u,v)}c.closePath();c.fillStyle=f;c.fill()};
  const n=Math.max(3,Math.round(len/.04));for(let i=0;i<n;i++)cap(x+len*i/n,r,i<n*.5?sh(col,-.06):col);
  const at=(xx,a)=>[px(xx,y)-Math.cos(a)*r*TW,py(xx,y,z)+Math.cos(a)*r*TH-Math.sin(a)*r*K];
  for(const a of [.55,1.45]){const [u1,v1]=at(x+.02,a),[u2,v2]=at(x+len-.02,a);s.line(u1,v1,u2,v2,band,1.5)}
  {const [u1,v1]=at(x+.02,2.3),[u2,v2]=at(x+len-.02,2.3);s.line(u1,v1,u2,v2,sh(col,.2),1)}
  cap(x+len,r,sh(col,.14));cap(x+len,r*.62,sh(col,-.04));cap(x+len,r*.26,sh(col,.2))}

function spinnery(s,o){
  const work=o.jobs?.length>0,t=s.time||0,x0=o.x+.18,y0=o.y+.14,x1=o.x+1.42,yw=o.y+.54,y1=o.y+1.02,H=30,col='#efe1c6',wood='#9a7550';
  const g=gparams({x0,y0,x1,y1,H,zE:H,col,roof:'#c7b07c',axis:'y',prof:GABLE,R:22,ov:.12,trim:'#e3d29e',courses:5},{});
  const xm=(x0+x1)/2;
  ground(s,o.x+.02,o.y+.02,o.x+o.w-.02,o.y+o.h-.02,'rgba(222,208,168,.42)');
  shadowAt(s,x0,y0,x1,y1);
  // a closed cottage at the back, an open porch under the front gable
  box(s,col,x0,y0,x1,yw,0,H);plinth(s,'#b9a888',x0,y0,x1,yw,5);corners(s,x0,y0,x1,yw,H,'#b89670');
  doorX(s,x1,(y0+yw)/2,.26,20,'#8b6f52','#f6ecd6',true);
  top(s,'#d3b689',x0,yw,x1,y1,3);wallY(s,'#ae9068',y1,x0,x1,0,3,3);wallX(s,'#97795a',x1,yw,y1,0,3,3);
  for(let k=1;k<6;k++){const x=x0+(x1-x0)*k/6;L(s,x,yw,3,x,y1,3,'rgba(110,80,45,.22)',.8)}
  // inside the porch: a basket of fleece and the spinning wheel (turns while a job runs)
  woolBasket(s,x0+.15,o.y+.8,.11,'wool');
  spinningWheel(s,o.x+1.04,o.y+.86,work?t*2.6:.35,'#f1e9da');
  // a low rail on the open side, posts, the front beam and the gable with a yarn-ball sign
  rail(s,x1-.02,yw+.04,x1-.02,y1-.06,9,wood);
  for(const x of [x0+.04,x1-.04])L(s,x,y1-.03,3,x,y1-.03,H,wood,3.2);
  L(s,x0,y1,H,x1,y1,H,sh(wood,-.08),3);
  // skeins drying on the front beam
  [['#e8c9a0',.1],['#d9a7bb',.2],['#a9c6d6',.3],['#f3eee2',.4]].forEach(([c,dx],i)=>{const x=x0+dx+.02,sw=Math.sin(t*1.3+i)*.8;L(s,x,y1,H-1,x+sw*.01,y1,H-10,c,3.4);E(s,x+sw*.01,y1,H-11,1.9,2.1,sh(c,-.12))});
  gableWall(s,'y',g);
  for(let k=1;k<5;k++){const x=x0+(x1-x0)*k/5,h=riseAt(GABLE,(x-x0+g.ov)/(x1-x0+2*g.ov))*g.R;L(s,x,y1,H+1,x,y1,H+h-1,'rgba(150,120,80,.25)',1)}
  E(s,xm,y1,H+9,6.4,6.4,'#f6ecd6');E(s,xm,y1,H+9,4.8,4.8,'#d9a7bb');s.line(px(xm,y1)-4,py(xm,y1,H+10),px(xm,y1)+3,py(xm,y1,H+7),'#f3dde5',1);s.line(px(xm,y1)-3,py(xm,y1,H+12),px(xm,y1)+4,py(xm,y1,H+9),'#f3dde5',1);
  roofOf(s,g);
  // straw tufts along the visible eave
  for(let y=y0-g.ov+.05;y<y1+g.ov;y+=.1)E(s,x1+g.ov,y,H-.5,2.7,1.8,(Math.round(y*7)%2)?'#b49a62':'#c2a96d');
  // porch lamp on a bracket at the front corner post (warm halo at night)
  const lx=x0+.04,ly=y1+.16;L(s,x0+.04,y1-.03,H-3,lx,ly,H-3,'#5b4a38',1.6);L(s,lx,ly,H-3,lx,ly,H-5,'#5b4a38',1);fullBox(s,'#5b4a38',lx-.04,ly-.04,lx+.04,ly+.04,H-11,H-5,'#7a6a4e');
  Q(s,'#fff1b8',[lx-.03,ly+.042,H-10,lx+.03,ly+.042,H-10,lx+.03,ly+.042,H-6,lx-.03,ly+.042,H-6]);
  s.lanternLights?.push({x:px(lx,ly),y:py(lx,ly,H-8)+43});
  // fluff drifting off the wheel while it spins
  if(work&&s.motion!==false)for(let i=0;i<2;i++){const f=(t*.35+i*.5)%1,X=px(o.x+.62,o.y+.86)+f*10,Y=py(o.x+.62,o.y+.86,22)-f*16;s.ellipse(X,Y,1.6,1.3,`rgba(255,252,240,${(.85*(1-f)).toFixed(3)})`)}
  // a basket of yarn balls in the yard
  woolBasket(s,o.x+1.22,o.y+1.56,.12,['#d9a7bb','#a9c6d6','#e8c9a0']);
  return H+g.R+14}

function weavery(s,o){
  const work=o.jobs?.length>0,t=s.time||0;
  const g=gparams({x0:o.x+.14,y0:o.y+.14,x1:o.x+1.5,y1:o.y+1.0,H:34,col:'#ece2cb',roof:'#a8705d',axis:'y',prof:GABLE,R:22,ov:.12,base:'#b98c74',baseH:6,corner:'#f8f1df',trim:'#e5c4b3',courses:4},{});
  ground(s,o.x+.02,o.y+.02,o.x+o.w-.02,o.y+o.h-.02,'rgba(218,204,176,.42)');
  body(s,g);const Y=g.y1,xm=(g.x0+g.x1)/2;
  boards(s,'y',Y,g.x0,g.x1,0,6,2,'rgba(110,60,40,.25)');boards(s,'x',g.x1,g.y0,g.y1,0,6,2,'rgba(90,50,35,.22)');
  // big workshop window with the loom inside
  const wa=xm-.46,wb=xm+.46,z0=9,z1=30;
  Q(s,'#f8f1df',[wa-.04,Y,z0-2,wb+.04,Y,z0-2,wb+.04,Y,z1+2,wa-.04,Y,z1+2]);
  Q(s,'#5f5459',[wa,Y,z0,wb,Y,z0,wb,Y,z1,wa,Y,z1]);Q(s,'#6d6066',[wa,Y,z1-7,wb,Y,z1-7,wb,Y,z1,wa,Y,z1]);
  const la=wa+.1,lb=wb-.1,hz=z0+13+(work?Math.sin(t*4.2)*1.6:0);
  L(s,la,Y,z0,la,Y,z1-1,'#b08a5e',2.4);L(s,lb,Y,z0,lb,Y,z1-1,'#b08a5e',2.4);L(s,la-.03,Y,z1-3,lb+.03,Y,z1-3,'#c9a272',2.6);
  const warp=['#f1e6cf','#e6a7b0','#f1e6cf','#a9c8bd','#f1e6cf','#e9d28a','#f1e6cf','#a6b7dc','#f1e6cf'];
  for(let i=0;i<warp.length;i++){const x=la+.05+(lb-la-.1)*i/(warp.length-1);L(s,x,Y,z1-3,x,Y,hz+.5,warp[i],.9);L(s,x,Y,hz-.5,x,Y,z0+7,warp[i],.9)}
  L(s,la,Y,hz,lb,Y,hz,'#d8b57f',2);
  Q(s,'#c98f8f',[la+.03,Y,z0+1.5,lb-.03,Y,z0+1.5,lb-.03,Y,z0+7,la+.03,Y,z0+7]);
  for(const z of [z0+3.2,z0+5.4])L(s,la+.03,Y,z,lb-.03,Y,z,'#f1d6d0',1);
  for(let i=1;i<4;i++){const x=la+(lb-la)*i/4;L(s,x,Y,z0+1.5,x,Y,z0+7,'#a86f6f',.9)}
  L(s,la,Y,z0+7.5,lb,Y,z0+7.5,'#9a774f',2.2);
  const sx=work?xm+Math.sin(t*2.4)*(lb-la)*.42:la+.12;E(s,sx,Y,hz-2.6,3.6,1.5,'#8a5a3a');E(s,sx-.01,Y,hz-2.2,1.6,.6,'#c99a6a');
  // glazing bars and a soft reflection over the glass, a wooden sill
  for(const f of [1/3,2/3]){const x=wa+(wb-wa)*f;L(s,x,Y,z0,x,Y,z1,'rgba(248,241,223,.75)',1.2)}L(s,wa,Y,z1-7,wb,Y,z1-7,'rgba(248,241,223,.75)',1.2);
  Q(s,'rgba(255,255,255,.1)',[wa+.08,Y,z1,wa+.3,Y,z1,wa+.12,Y,z0,wa,Y,z0,wa,Y,z0+6]);
  Q(s,'#c9a672',[wa-.07,Y,z0-2,wb+.07,Y,z0-2,wb+.07,Y+.07,z0-3.5,wa-.07,Y+.07,z0-3.5]);
  // round attic window on the gable
  E(s,xm,Y,g.H+9,5.6,5.6,'#f8f1df');E(s,xm,Y,g.H+9,4.1,4.1,'#a9c4c8');s.line(px(xm,Y)-4,py(xm,Y,g.H+9),px(xm,Y)+4,py(xm,Y,g.H+9),'#f8f1df',1);
  // right wall: door under a little canopy and a window
  const yd=g.y1-.28;doorX(s,g.x1,yd,.32,21,'#7f9c98','#f8f1df');
  winX(s,g.x1,g.y0+.33,14,.26,12,'#b4cfc9','#f8f1df');winX(s,g.x1,yd,g.H-8,.22,6,'#b4cfc9','#f8f1df');
  roofOf(s,g);
  Q(s,'#b88373',[g.x1,yd-.25,27,g.x1,yd+.25,27,g.x1+.22,yd+.25,23,g.x1+.22,yd-.25,23]);L(s,g.x1+.22,yd-.25,23,g.x1+.22,yd+.25,23,'#8a5b4c',1.6);
  // sign: a checked cloth swatch on a bracket at the front corner
  L(s,g.x0+.02,Y,30,g.x0+.02,Y+.26,30,'#5f4a38',1.6);
  {const X=px(g.x0+.02,Y+.22),Z=py(g.x0+.02,Y+.22,29);s.line(X,Z,X,Z+2,'#5f4a38',1);s.poly([{x:X-5,y:Z+2},{x:X+5,y:Z+2},{x:X+5,y:Z+12},{x:X-5,y:Z+12}],'#e9d6b0');
   for(const k of [0,1,2])s.line(X-5,Z+4+k*3.4,X+5,Z+4+k*3.4,'#c98f8f',1.3);for(const k of [0,1,2])s.line(X-3.4+k*3.4,Z+2,X-3.4+k*3.4,Z+12,'rgba(130,110,160,.7)',1.1)}
  // weathervane with a shuttle on the front end of the ridge
  {const vx=xm,vy=g.y1-.12,vz=g.H+g.R;L(s,vx,vy,vz,vx,vy,vz+11,'#6f6658',1.4);const X=px(vx,vy),Z=py(vx,vy,vz+10);s.poly([{x:X-8,y:Z},{x:X-3,y:Z-2},{x:X+3,y:Z-2},{x:X+8,y:Z},{x:X+3,y:Z+2},{x:X-3,y:Z+2}],'#c9a272');s.ellipse(X,Z,2.2,1,'#7a5236')}
  // the night shift: lit window while the loom works
  if(work)s.lanternLights?.push({x:px(xm,Y),y:py(xm,Y,(z0+z1)/2)+43});
  // cloth rolls on a pallet by the shaded wall
  const rx=o.x+1.55,ry=o.y+1.02;
  fullBox(s,'#b08f63',rx,ry-.02,rx+.4,ry+.32,0,3,'#c9a672');
  clothRoll(s,rx+.02,ry+.06,6.2,.36,.085,'#a9a3b8','#cfcadb');clothRoll(s,rx+.02,ry+.24,6.2,.36,.085,'#c98f8f','#f1d6d0');
  clothRoll(s,rx+.02,ry+.15,11.6,.36,.085,'#e8dfe9','#fbf7fb');
  return g.H+g.R+16}
/* ---------- fruit orchard (docs/tasks/FARM_ORCHARD.md): dryer (Сушильня), cellar (Погребок «Ноль градусов»), birdhouse ---------- */
/* Open timber drying shed: lattice back walls, mesh trays of fruit, garlands of apple rings under the eave, a sun on the gable and a
   little wind fan on the ridge that turns while a batch dries (still with reduced motion). A lamp under the eave lights the night shift. */
function dryer(s,o){
  const work=o.jobs?.length>0,t=s.time||0,mo=s.motion!==false,wood='#a37d55',x0=o.x+.2,x1=o.x+1.5,y0=o.y+.18,y1=o.y+1.02,H=28;
  const g=gparams({x0,y0,x1,y1,H,zE:H,col:'#dcc394',roof:'#a8735a',axis:'y',prof:GABLE,R:18,ov:.13,trim:'#e6cfa4',courses:4},{});
  ground(s,o.x+.02,o.y+.02,o.x+o.w-.02,o.y+o.h-.02,'rgba(222,200,150,.42)');
  shadowAt(s,x0,y0,x1,y1,50,19);
  top(s,'#cdb083',x0,y0,x1,y1,2);wallY(s,'#a98a60',y1,x0,x1,0,2,2);wallX(s,'#94764f',x1,y0,y1,0,2,2);
  for(let k=1;k<6;k++){const x=x0+(x1-x0)*k/6;L(s,x,y0,2,x,y1,2,'rgba(110,80,45,.22)',.8)}
  // lattice of slats on the two back walls: air passes through
  for(let k=0;k<=9;k++){const x=x0+(x1-x0)*k/9;L(s,x,y0,2,x,y0,H,'rgba(150,112,72,.62)',1.3)}
  for(let k=0;k<=6;k++){const y=y0+(y1-y0)*k/6;L(s,x0,y,2,x0,y,H,'rgba(128,96,62,.58)',1.3)}
  for(const z of [11,20]){L(s,x0,y0,z,x1,y0,z,'rgba(150,112,72,.7)',1.1);L(s,x0,y0,z,x0,y1,z,'rgba(128,96,62,.66)',1.1)}
  L(s,x0,y0,2,x0,y0,H,wood,3);
  // the rack: back legs, three mesh trays (apricot halves, apple rings, plums and cherries), front legs
  const rx0=x0+.16,rx1=x1-.2,ry0=y0+.22,ry1=y0+.58;
  for(const x of [rx0,rx1])L(s,x,ry0,2,x,ry0,25,sh(wood,-.12),1.6);
  const trays=[[7,['#e8963a','#f2b45a']],[14,['#ecd9a6','#e2c88e']],[21,['#5a3f6a','#8f1c32']]];
  for(const [z,cols] of trays){
    top(s,'#d9c59a',rx0,ry0,rx1,ry1,z);wallY(s,'#b39a6c',ry1,rx0,rx1,z-1.4,z,z);wallX(s,'#9c8460',rx1,ry0,ry1,z-1.4,z,z);
    for(let k=1;k<8;k++){const x=rx0+(rx1-rx0)*k/8;L(s,x,ry0,z,x,ry1,z,'rgba(120,92,58,.35)',.6)}
    for(let k=1;k<3;k++){const y=ry0+(ry1-ry0)*k/3;L(s,rx0,y,z,rx1,y,z,'rgba(120,92,58,.35)',.6)}
    for(let i=0;i<6;i++)for(let j=0;j<2;j++){const x=rx0+.1+i*(rx1-rx0-.18)/5,y=ry0+.1+j*.17,col=cols[(i+j)%2];
      E(s,x,y,z+1,2.5,1.4,col);if(col==='#ecd9a6'||col==='#e2c88e')E(s,x,y,z+1.2,.9,.5,'#b9965e');else E(s,x-.02,y,z+1.6,.9,.45,sh(col,.3))}
  }
  for(const x of [rx0,rx1])L(s,x,ry1,2,x,ry1,25,wood,1.8);
  // front posts and beams
  for(const [x,y] of [[x1,y0],[x0,y1],[x1,y1]])L(s,x,y,2,x,y,H,wood,3.2);
  L(s,x0,y1,H,x1,y1,H,sh(wood,-.08),3);L(s,x1,y0,H,x1,y1,H,sh(wood,-.16),3);
  // garlands of dried slices on strings: apple rings, one of apricot halves; they swing while the fan blows
  for(let i=0;i<5;i++){const x=x0+.2+i*.26,sw=work&&mo?Math.sin(t*1.6+i*1.3)*.018:0,apr=i===2;
    L(s,x,y1,H-.5,x+sw,y1,H-15,'#e8dcc0',.7);
    for(let k=0;k<4;k++){const z=H-4-k*3.4,dx=sw*(k+1)/4;E(s,x+dx,y1,z,2.4,2,apr?'#e8963a':'#f1e2b8');E(s,x+dx,y1,z,apr?1.2:1.1,apr?1:.9,apr?'#f4bf6a':'#d6bd88')}}
  // gable with boards and a painted sun
  gableWall(s,'y',g);const xm=(x0+x1)/2;
  for(let k=1;k<6;k++){const x=x0+(x1-x0)*k/6,h=riseAt(GABLE,(x-x0+g.ov)/(x1-x0+2*g.ov))*g.R;L(s,x,y1,H+1,x,y1,H+h-1,'rgba(150,115,70,.3)',1)}
  for(let k=0;k<8;k++){const a=k*PI/4,X=px(xm,y1),Z=py(xm,y1,H+8);s.line(X+Math.cos(a)*5.6,Z+Math.sin(a)*5.6,X+Math.cos(a)*8,Z+Math.sin(a)*8,'#e3a94a',1.4)}
  E(s,xm,y1,H+8,4.6,4.6,'#efc35a');E(s,xm-.03,y1,H+9,1.6,1.4,'#f8e09a');
  roofOf(s,g);
  // wind fan on the front end of the ridge
  {const fx=xm,fy=y1+.05,fz=H+g.R;L(s,fx,fy,fz-1,fx,fy,fz+9,'#6f5a44',1.6);const X=px(fx,fy),Z=py(fx,fy,fz+9),c=s.c,turn=work&&mo?t*4:.35;
   c.save();c.translate(X,Z);c.rotate(turn);for(let k=0;k<4;k++){c.rotate(PI/2);s.poly([{x:1,y:-1.4},{x:8,y:-2.6},{x:8.6,y:.6},{x:1,y:1.2}],k%2?'#e9dcc0':'#c9a26a')}c.restore();s.ellipse(X,Z,1.7,1.7,'#5d4b38')}
  // lamp under the eave at the front corner (lit while a batch dries)
  const lx=x0+.05,ly=y1+.14;L(s,x0,y1,H-3,lx,ly,H-3,'#5b4a38',1.4);L(s,lx,ly,H-3,lx,ly,H-6,'#5b4a38',1);fullBox(s,'#5b4a38',lx-.035,ly-.035,lx+.035,ly+.035,H-12,H-6,'#7a6a4e');
  Q(s,work?'#fff1b8':'#e9dcae',[lx-.028,ly+.037,H-11,lx+.028,ly+.037,H-11,lx+.028,ly+.037,H-7,lx-.028,ly+.037,H-7]);
  if(work)s.lanternLights?.push({x:px(lx,ly),y:py(lx,ly,H-9)+43});
  // yard: a basket of apples and a crate of apricots
  const bx=o.x+.48,by=o.y+1.5;cyl(s,bx,by,.14,0,7,'#c09868','#8f6c45');for(const [dx,dz,c] of [[-4,9,'#d9534f'],[2,10,'#e06a50'],[5,8.6,'#c94a44'],[-1,11.6,'#d9534f']])s.ellipse(px(bx,by)+dx,py(bx,by,dz),2.8,2.6,c);
  crate(s,o.x+1.2,o.y+1.56,.28,8,'#c9a672');for(const [dx,dy] of [[-.06,-.04],[.06,0],[0,.06]])E(s,o.x+1.2+dx,o.y+1.56+dy,10,2.8,2.6,'#f0a64a');
  return H+g.R+16}

/* Earth mound with a stone portal and an arched door, a vent pipe that puffs fizz while a batch matures, a «0°» thermometer by the
   door (zero degrees, zero percent) and «0%» kegs at the entrance. A lamp by the door lights the night shift. */
function cellar(s,o){
  const work=o.jobs?.length>0,t=s.time||0,mo=s.motion!==false,c=s.c;
  ground(s,o.x+.02,o.y+.02,o.x+o.w-.02,o.y+o.h-.02,'rgba(190,205,160,.42)');
  const mx=o.x+.98,my=o.y+.6,X=px(mx,my),Y=py(mx,my,0);
  s.shadow(X+2,Y+4,58,21);
  s.ellipse(X,Y+1,57,23,'#829f69');
  c.save();c.beginPath();c.ellipse(X,Y-13,53,37,0,0,PI*2);c.clip();
  s.ellipse(X,Y-13,53,37,'#8fae73');s.ellipse(X+24,Y-4,40,34,'#7f9d66');s.ellipse(X-12,Y-27,38,24,'#97b47a');s.ellipse(X-16,Y-33,26,15,'#9fbc82');s.ellipse(X-20,Y-38,13,6,'#a9c58b');
  c.restore();
  // stones at the foot and grass on the top
  for(const [dx,dy,r] of [[-50,4,4],[-42,10,3.4],[-30,14,4.2],[34,13,3.6],[46,7,4],[52,0,3]])s.ellipse(X+dx,Y+dy,r,r*.6,'#b9b29d');
  for(const [dx,dy] of [[-30,-34],[-12,-44],[4,-46],[20,-38],[34,-26],[-38,-18]])for(let k=-1;k<=1;k++)s.line(X+dx+k*1.6,Y+dy,X+dx+k*2.4,Y+dy-4-(k?0:1.5),'#6f9256',1);
  for(const [dx,dy,col] of [[-24,-38,'#f3e3a0'],[12,-44,'#e7a8b5'],[28,-31,'#f3e3a0']]){s.line(X+dx,Y+dy,X+dx,Y+dy-4,'#6f9256',.9);s.ellipse(X+dx,Y+dy-5,1.8,1.5,col)}
  // vent pipe on the top: tin with a little hat, fizz bubbles while a drink matures
  const vx=o.x+1.24,vy=o.y+.34;cyl(s,vx,vy,.05,36,53,'#9aa3a6','#b9c1c3');
  {const V=px(vx,vy),Z=py(vx,vy,55);s.poly([{x:V-6.5,y:Z+1.5},{x:V,y:Z-3.5},{x:V+6.5,y:Z+1.5}],'#7d878a');s.ellipse(V,Z+1.5,6.5,1.6,'#6b7477');
   const n=work?(mo?4:2):0;for(let i=0;i<n;i++){const f=mo?(t*.45+i*.25)%1:.3+i*.35,bx=V+(mo?Math.sin(t*2.2+i*1.7)*3:i*4-2),by=Z-5-f*24,r=1.1+f*1.5;
    c.save();c.globalAlpha=(1-f)*.9;c.beginPath();c.ellipse(bx,by,r,r,0,0,PI*2);c.strokeStyle='#f6fbff';c.lineWidth=.9;c.stroke();s.ellipse(bx-r*.35,by-r*.35,r*.3,r*.3,'#ffffff');c.restore()}}
  // stone portal in the front of the mound: a wide arched wall with turf on top, the door between the level-2 flower boxes
  const Yf=o.y+1.04,xm=o.x+.68,xa=xm-.44,xb=xm+.42,h=25,stone='#d3c8ac';
  wallX(s,sh(stone,-.22),xb,Yf-.14,Yf,0,h-2,h-2);
  Q(s,stone,[xa,Yf,0,xb,Yf,0,xb,Yf,h-2,xm+.28,Yf,h+3,xm,Yf,h+5,xm-.28,Yf,h+3,xa,Yf,h-2]);
  for(const [a,b,z] of [[xa,xm-.17,6.5],[xm+.17,xb,6.5],[xa,xm-.17,13.5],[xm+.17,xb,13.5],[xa,xm-.17,20],[xm+.17,xb,20]])L(s,a,Yf,z,b,Yf,z,'rgba(120,108,84,.3)',.9);
  for(const [x,z0,z1] of [[xa+.12,0,6.5],[xb-.14,0,6.5],[xa+.06,6.5,13.5],[xb-.08,6.5,13.5],[xa+.16,13.5,20],[xb-.18,13.5,20]])L(s,x,Yf,z0,x,Yf,z1,'rgba(120,108,84,.28)',.9);
  Q(s,'#bfb293',[xm-.19,Yf,0,xm+.19,Yf,0,xm+.19,Yf,15,xm,Yf,21,xm-.19,Yf,15]);
  doorY(s,Yf,xm,.28,16,'#7a5638','#bfb293',true);
  for(const z of [4.5,11])L(s,xm-.13,Yf,z,xm+.13,Yf,z,'#4f3d2b',1.3);
  E(s,xm+.08,Yf,8.5,1.2,1.2,'#d9c999');
  // turf along the top of the wall
  {const zt=x=>{const d=Math.abs(x-xm);return d<.28?h+5-2*d/.28:h+3-5*(d-.28)/(xb-xm-.28)},xs=[xa-.03,xa+.2,xm-.28,xm-.12,xm,xm+.12,xm+.28,xb-.2,xb+.03],top=[],bot=[];
   for(const x of xs){const z=zt(Math.min(xb,Math.max(xa,x)));top.push(x,Yf+.02,z+3.2);bot.unshift(x,Yf+.02,z-1.6)}Q(s,'#8fae73',[...top,...bot]);
   for(let k=1;k<xs.length-1;k+=2){const x=xs[k];L(s,x,Yf+.02,zt(x)+3,x-.02,Yf+.02,zt(x)+6,'#7a9a5e',1);L(s,x+.03,Yf+.02,zt(x)+3,x+.05,Yf+.02,zt(x)+5.5,'#7a9a5e',1)}
   for(let k=0;k<xs.length;k+=2)E(s,xs[k],Yf+.03,zt(Math.min(xb,Math.max(xa,xs[k])))-1.4,2.6,1.4,'#9cba80')}
  // «0%» board under the arch top
  Q(s,'#ead8a8',[xm-.14,Yf+.01,19,xm+.14,Yf+.01,19,xm+.14,Yf+.01,24.5,xm-.14,Yf+.01,24.5]);
  {const B=px(xm,Yf+.01),Z=py(xm,Yf+.01,21.75);c.save();c.font='700 6.4px "Segoe UI",sans-serif';c.textAlign='center';c.textBaseline='middle';c.fillStyle='#5a4127';c.fillText('0%',B,Z+.4);c.restore()}
  // thermometer dial at zero, right of the door
  {const tx=xm+.3,T=px(tx,Yf),Z=py(tx,Yf,14);s.ellipse(T,Z,4.6,4.6,'#7d6a52');s.ellipse(T,Z,3.6,3.6,'#f7f1e2');for(const a of [-2.4,-1.57,-.74])s.line(T+Math.cos(a)*2.6,Z+Math.sin(a)*2.6,T+Math.cos(a)*3.3,Z+Math.sin(a)*3.3,'#7d6a52',.6);s.line(T,Z,T,Z-2.9,'#c9443a',.9);s.ellipse(T,Z,.8,.8,'#c9443a')}
  // lamp left of the door
  const lx=xm-.3,ly=Yf+.04;L(s,lx,Yf,18,lx,ly+.08,18,'#4f3d2b',1.2);fullBox(s,'#4f3d2b',lx-.03,ly+.05,lx+.03,ly+.11,12.5,18,'#6a5840');
  Q(s,work?'#fff1b8':'#e9dcae',[lx-.024,ly+.112,13.1,lx+.024,ly+.112,13.1,lx+.024,ly+.112,16.8,lx-.024,ly+.112,16.8]);
  if(work)s.lanternLights?.push({x:px(lx,ly+.08),y:py(lx,ly+.08,15)+43});
  // «0%» kegs at the entrance and a crate of corked bottles
  const keg=(x,y,r,hh,col)=>{barrel(s,x,y,r,hh,col);const K=px(x,y)+r*TW*.35,Z=py(x+r*.7,y+r*.7,hh*.52);s.poly([{x:K-4.6,y:Z-2.6},{x:K+4.6,y:Z-2.6},{x:K+4.6,y:Z+3},{x:K-4.6,y:Z+3}],'#f4ead2');
    c.save();c.font='700 5px "Segoe UI",sans-serif';c.textAlign='center';c.textBaseline='middle';c.fillStyle='#8a4a32';c.fillText('0%',K,Z+.3);c.restore()};
  keg(o.x+1.62,o.y+1.02,.13,11,'#b48a5c');keg(o.x+1.38,o.y+1.36,.15,13,'#a87a4c');
  crate(s,o.x+.4,o.y+1.56,.28,7,'#c9a672');for(const [dx,col] of [[-.07,'#7a1a2c'],[0,'#e6c25a'],[.07,'#5a3a7a']]){const x=o.x+.4+dx,y=o.y+1.56;L(s,x,y,7,x,y,14,col,3);L(s,x,y,14,x,y,16.5,'#c9a672',1.6)}
  return 68}

/* Birdhouse (decor 1x1): a pole with a little gabled house, a perch by the round hole and a starling that sits on the ridge and now
   and then peeks out of the hole (it stays on the ridge with reduced motion). Its trees get the starling of FARM_ORCHARD.md 2.5. */
export function drawBirdhouse(s,o){
  const cx=o.x+.5,cy=o.y+.5,t=s.time||0,mo=s.motion!==false,a=.14,z0=36,z1=50,wood='#d6b98a';
  s.shadow(px(cx,cy),py(cx,cy,0),11,4.5);
  for(const [dx,dy,hh] of [[-.12,.08,6],[.1,.1,5],[0,.16,7],[.14,-.04,4],[-.06,-.1,5]])L(s,cx+dx,cy+dy,0,cx+dx*1.25,cy+dy*1.25,hh,'#7ea468',1.1);
  E(s,cx+.15,cy+.13,6.5,1.9,1.6,'#e7a8b5');E(s,cx-.13,cy+.1,7,1.6,1.4,'#f3e3a0');
  L(s,cx,cy,0,cx,cy,z0+2,'#8b7756',3.4);L(s,cx-.015,cy+.015,1,cx-.015,cy+.015,z0,'#a8916a',1);
  L(s,cx,cy,z0-7,cx,cy+.09,z0,'#7a6849',1.4);
  box(s,wood,cx-a,cy-a,cx+a,cy+a,z0,z1);
  const g={x0:cx-a,y0:cy-a,x1:cx+a,y1:cy+a,zE:z1,prof:GABLE,R:9,ov:.05,roof:'#a8705a',col:wood,courses:2};
  gableWall(s,'y',g);
  E(s,cx,cy+a,z0+8.5,2.5,2.7,'#4a3a2a');L(s,cx,cy+a,z0+3.6,cx,cy+a+.09,z0+3.6,'#7a6849',1.4);
  L(s,cx-a+.02,cy+a,z0+.5,cx+a-.02,cy+a,z0+.5,sh(wood,-.25),1);
  gableRoof(s,'y',g);
  const peek=mo&&((t*.11+o.x*.37+o.y*.21)%1)>.62,bird='#3f4352';
  if(peek){const X=px(cx,cy+a),Z=py(cx,cy+a,z0+8.5);s.ellipse(X,Z,2,2,'#454a5a');s.poly([{x:X+1.6,y:Z-.6},{x:X+4.4,y:Z+.2},{x:X+1.6,y:Z+.9}],'#e2b84a');s.ellipse(X+.5,Z-.7,.45,.45,'#f3f1e8')}
  else{const X=px(cx,cy+a)+1,Z=py(cx,cy+a,z1+g.R)-1,bob=mo?Math.max(0,Math.sin(t*2.1+o.x))*1:0;
    s.ellipse(X,Z-2.6,3.6,2.6,bird);s.poly([{x:X-2.6,y:Z-3.4},{x:X-7,y:Z-1.6},{x:X-2.6,y:Z-1.6}],'#363a48');
    s.ellipse(X+2.8,Z-5-bob*.4,2.1,2,'#454a5a');s.poly([{x:X+4.4,y:Z-5.6-bob*.4},{x:X+7.2,y:Z-4.8-bob*.2},{x:X+4.4,y:Z-4.3-bob*.4}],'#e2b84a');
    for(const [dx,dy] of [[-1,-3],[1,-2],[-.4,-1.8]])s.ellipse(X+dx,Z+dy,.4,.4,'#cfd3dc');s.ellipse(X+3.3,Z-5.4-bob*.4,.45,.45,'#f3f1e8')}
}
const TYPES={house,barn,mill,coop,cowshed,sheepfold,apiary,goatshed,rabbit_hutch:rabbit,alpaca_pen:alpaca,goose_house:goose,pigsty,turkey_yard:turkeyYard,quail_house:quailHouse,peacock_aviary:peacockAviary,angora_pen:angoraPen,swan_lake:swanLake,teahouse:tea,garage,bakery,feedmill,kitchen,dairy,loom,spinnery,weavery,oil_press:oilPress,juicery,cannery,smokehouse,tailor,confectionery,creamery,sausage_shop:sausageShop,cattle_barn:cattleBarn,syrupery:lateWorkshop,soapery:lateWorkshop,noodle_shop:lateWorkshop,ostrich_farm:lateAnimalHouse,silk_house:lateAnimalHouse,yak_pen:lateAnimalHouse,pheasantry:lateAnimalHouse,energy_shop:energyShop,dryer,cellar};
/* ---------- r6 building upgrades (view only; the level comes from the server object) ----------
   level 2: flower boxes, a lantern post with a hanging sign. level 3: adds a lean-to annex with its own chimney and a
   waving flag on the roof. Both levels get a small gold badge. Buildings without a level (older saves) are level 1. */
const upLevel=o=>Math.max(1,Math.min(3,Number.isInteger(o.level)?o.level:1));
export function drawBadge(s,o){const lv=upLevel(o);if(lv<2)return;const x=px(o.x+o.w-.12,o.y+o.h-.12),y=py(o.x+o.w-.12,o.y+o.h-.12,0),c=s.c;
  s.ellipse(x+1,y+2,10,6,'rgba(60,50,20,.25)');s.ellipse(x,y-8,9.5,9.5,lv>2?'#d9a53b':'#c9b27a');s.ellipse(x,y-8,7.4,7.4,lv>2?'#f3d37a':'#efe3b6');
  c.save();c.font='bold 11px sans-serif';c.textAlign='center';c.textBaseline='middle';c.fillStyle='#6b4c1d';c.fillText(String(lv),x,y-7.5);c.restore()}
function planter(s,x,y,w,flowers){fullBox(s,'#b98d5d',x,y,x+w,y+.14,0,6,'#8a6a45');boards(s,'y',y+.14,x,x+w,0,6,3,'rgba(60,40,20,.3)');
  const n=Math.max(3,Math.round(w/.09));for(let k=0;k<n;k++){const fx=x+.04+(w-.08)*k/(n-1),col=flowers[k%flowers.length];L(s,fx,y+.07,6,fx,y+.07,9+(k%2)*2,'#6f9a55',1.2);E(s,fx,y+.07,10+(k%2)*2,2.3,2.3,col)}}
export function drawUpgrade(s,o,top){const lv=upLevel(o);if(lv<2)return top;const work=(o.jobs&&o.jobs.length>0)||!!o.animal_job;
  // level 2: flower boxes along the front, lantern post with a sign
  planter(s,o.x+.2,o.y+1.1,.4,['#e56d8b','#f3c64a','#fdf5ee']);planter(s,o.x+1.0,o.y+1.1,.4,['#fdf5ee','#a98bd0','#e56d8b']);
  const lx=o.x+.08,ly=o.y+1.62;
  L(s,lx,ly,0,lx,ly,34,'#4f4638',2.4);L(s,lx,ly,34,lx+.26,ly,34,'#4f4638',1.8);
  Q(s,'#e9d6a4',[lx+.12,ly,33,lx+.4,ly,33,lx+.4,ly,25,lx+.12,ly,25]);Q(s,'#b4506a',[lx+.15,ly,30,lx+.37,ly,30,lx+.37,ly,28,lx+.15,ly,28]);
  fullBox(s,'#4f4638',lx-.05,ly-.05,lx+.05,ly+.05,34,40,'#7a6a4e');Q(s,'#fff1b8',[lx-.04,ly+.052,35,lx+.04,ly+.052,35,lx+.04,ly+.052,39,lx-.04,ly+.052,39]);
  s.ellipse(px(lx,ly),py(lx,ly,37),9,9,work?'rgba(255,224,130,.4)':'rgba(255,224,130,.2)');
  let h=top;
  if(lv>=3){
    // lean-to annex on the shaded side with a small chimney
    const ax=o.x+1.56,ay=o.y+.22;
    shedBox(s,'#cdb48a',ax,ay,ax+.42,ay+.62,0,14,18);boards(s,'x',ax+.42,ay,ay+.62,2,14,3,'rgba(80,55,30,.25)');
    winX(s,ax+.42,ay+.31,5,.2,6,'#a9c6bd','#f1e6d4');
    shedRoof(s,ax,ay,ax+.42,ay+.62,18,24,'#8a6a4a',.06,'y');
    chimney(s,ax+.2,ay+.18,20,36,'#a8826a',.08);smoke(s,ax+.2,ay+.18,36,work,.9);
    // flagpole in the yard
    const fx=o.x+1.82,fy=o.y+1.3,z0=0,z1=60;
    E(s,fx,fy,0,6,3,'rgba(60,70,40,.2)');fullBox(s,'#b9b2a0',fx-.07,fy-.07,fx+.07,fy+.07,0,4,'#d4cdbb');
    L(s,fx,fy,4,fx,fy,z1,'#5b4a38',2);E(s,fx,fy,z1+1,2,2,'#d9a53b');
    const wv=s.motion===false?0:Math.sin(s.time*3)*2,X=px(fx,fy),Y=py(fx,fy,z1-1);
    s.poly([{x:X,y:Y},{x:X+17,y:Y+3+wv},{x:X+13,y:Y+7+wv*.6},{x:X+17,y:Y+11+wv*.3},{x:X,y:Y+11}],'#d9553f');
    s.poly([{x:X,y:Y},{x:X+17,y:Y+3+wv},{x:X+13,y:Y+7+wv*.6},{x:X,y:Y+6}],'#e9806a');
    h=Math.max(h,z1+4);
  }
  drawBadge(s,o);return h}

/* Draws the building and returns its approximate top height in screen pixels (used to place bubbles). */
export function drawBuilding(s,o,p){s.c.save();s.c.translate(0,0);const h=(TYPES[o.type]||generic)(s,o);s.c.restore();return h}
export const BUILDING_TYPES=Object.keys(TYPES);

/* Same earth surface as the permanent farm roads; full tiles join without seams. */
export function drawRoad(s,o){
 s.tile(o.x,o.y,'#dbd3ae');
 const p={x:px(o.x+.4,o.y+.5),y:py(o.x+.4,o.y+.5,0)};
 s.ellipse(p.x,p.y,3,1,'#c5ba934c');
}
