// Скриншот үчүн гана: тармак жок чөйрөдө Leaflet'тин ордуна жөнөкөй карта.
(function(){
const R=6378137, T=256;
function px(lat,lng,z){const s=T*Math.pow(2,z);const x=(lng+180)/360*s;const sn=Math.sin(lat*Math.PI/180);
 const y=(0.5-Math.log((1+sn)/(1-sn))/(4*Math.PI))*s;return[x,y];}
function ll(x,y,z){const s=T*Math.pow(2,z);const lng=x/s*360-180;const n=Math.PI-2*Math.PI*y/s;
 return[180/Math.PI*Math.atan(0.5*(Math.exp(n)-Math.exp(-n))),lng];}
function Map(id){this.el=document.getElementById(id);this.el.style.background="#EDEAE2";this.el.style.overflow="hidden";
 this.c=[0,0];this.z=15;this.h={};this.layers=[];
 this.bg=document.createElementNS("http://www.w3.org/2000/svg","svg");this.bg.setAttribute("style","position:absolute;inset:0;width:100%;height:100%");
 this.el.appendChild(this.bg);this.ov=document.createElement("div");this.ov.style.cssText="position:absolute;inset:0";this.el.appendChild(this.ov);}
Map.prototype={setView(c,z){this.c=[c[0],c[1]];if(z)this.z=z;this.draw();this.fire("movestart");setTimeout(()=>this.fire("moveend"),10);return this},
 getCenter(){return{lat:this.c[0],lng:this.c[1]}},getZoom(){return this.z},on(e,f){(this.h[e]=this.h[e]||[]).push(f);return this},
 fire(e){(this.h[e]||[]).forEach(f=>f())},
 fitBounds(b){const a=b.a,c=b.b;this.c=[(a[0]+c[0])/2+(a[0]-c[0])*0.0-0.006,(a[1]+c[1])/2];this.z=14;this.draw();},
 xy(p){const w=this.el.clientWidth,h=this.el.clientHeight;const o=px(this.c[0],this.c[1],this.z),q=px(p[0],p[1],this.z);return[q[0]-o[0]+w/2,q[1]-o[1]+h/2]},
 draw(){const w=this.el.clientWidth,h=this.el.clientHeight;let s="";
  const o=px(this.c[0],this.c[1],this.z);const step=110;
  for(let i=-2;i<w/step+3;i++){const x=i*step-(o[0]%step);s+=`<rect x="${x}" y="0" width="${i%3?10:16}" height="${h}" fill="#fff"/>`}
  for(let j=-2;j<h/step+3;j++){const y=j*step-(o[1]%step);s+=`<rect x="0" y="${y}" width="${w}" height="${j%2?10:16}" fill="#fff"/>`}
  for(let i=-1;i<w/step+2;i++)for(let j=-1;j<h/step+2;j++){if((i*7+j*3)%5===0){const x=i*step-(o[0]%step)+26,y=j*step-(o[1]%step)+26;s+=`<rect x="${x}" y="${y}" width="70" height="70" rx="6" fill="#D6E8CF"/>`}}
  s+=`<path d="M${-50} ${h*0.72} C ${w*0.3} ${h*0.6}, ${w*0.6} ${h*0.85}, ${w+50} ${h*0.7}" stroke="#B9D7EE" stroke-width="18" fill="none"/>`;
  this.bg.innerHTML=s;this.layers.forEach(l=>l._draw&&l._draw());}};
function Group(){this.items=[]}
Group.prototype={addTo(m){this.m=m;m.layers.push(this);this.items.forEach(i=>i.addTo(m));return this},clearLayers(){this.items.forEach(i=>i.remove());this.items=[]},getLayers(){return this.items},_draw(){}};
function Marker(p,o){this.p=p;this.o=o}
Marker.prototype={addTo(g){if(g instanceof Group){g.items.push(this);this.m=g.m;}else this.m=g;
 this.el=document.createElement("div");this.el.style.cssText="position:absolute";this.el.innerHTML=this.o.icon.html;this.m.ov.appendChild(this.el);
 this.m.layers.push(this);this._draw();return this},setLatLng(p){this.p=p;this._draw()},remove(){this.el&&this.el.remove()},
 _draw(){if(!this.el)return;const [x,y]=this.m.xy(this.p);this.el.style.left=(x-15)+"px";this.el.style.top=(y-15)+"px"}};
function Line(pts,o){this.pts=pts;this.o=o}
Line.prototype={addTo(g){g.items.push(this);this.m=g.m;this.el=document.createElementNS("http://www.w3.org/2000/svg","svg");
 this.el.setAttribute("style","position:absolute;inset:0;width:100%;height:100%;pointer-events:none");this.m.ov.prepend(this.el);this.m.layers.push(this);this._draw();return this},
 remove(){this.el&&this.el.remove()},_draw(){if(!this.el)return;const d=this.pts.map((p,i)=>(i?"L":"M")+this.m.xy(p).join(" ")).join(" ");
 this.el.innerHTML=`<path d="${d}" stroke="${this.o.color}" stroke-width="${this.o.weight}" stroke-dasharray="${this.o.dashArray||""}" fill="none" stroke-linecap="round"/>`}};
window.L={map:id=>new Map(id),tileLayer:()=>({addTo(){}}),layerGroup:()=>new Group(),marker:(p,o)=>new Marker(p,o),
 divIcon:o=>o,polyline:(p,o)=>new Line(p,o),latLngBounds:a=>({a:a[0],b:a[1]})};
})();
