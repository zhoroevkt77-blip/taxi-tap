# Админ: шаардын чегин оңдоо (Манас) — скриншоттор
import os, subprocess, sys, time, tempfile, json
TMP = tempfile.mkdtemp()
os.environ.update(SQLITE_PATH=os.path.join(TMP, "s.db"), DATA_DIR=TMP, DATABASE_URL="", SERVICE_AREA="on",
                  WEB_DEV_LOGIN="1", PORT="8807", OSRM_URL="", ADMIN_PHONES="0700900900")
sys.path.insert(0, "/home/claude/taxi-tap")
import core
from playwright.sync_api import sync_playwright
from PIL import Image, ImageDraw, ImageFont
import math
def blob(lat, lon, rk, n=36, wob=0.18, seed=1):
    pts = []
    for i in range(n):
        a = 2 * math.pi * i / n; r = rk * (1 + wob * math.sin(3 * a + seed) + wob * 0.6 * math.cos(5 * a))
        pts.append([round(lon + r / (111 * math.cos(math.radians(lat))) * math.cos(a), 5), round(lat + r / 111 * math.sin(a), 5)])
    pts.append(pts[0]); return pts
manas = blob(40.933, 73.0, 4.2, seed=2)
suzak = {"type": "Polygon", "coordinates": [blob(40.85, 73.0, 22, wob=.1, seed=5), manas]}
for name, gj in (("Сузак району", suzak), ("Манас шаары", {"type": "Polygon", "coordinates": [manas]})):
    u = core.geo_find(name, "Жалал-Абад облусу")
    json.dump({"gj": gj, "approx": False}, open(core._unit_cache(u), "w"))
json.dump([{"name": "Сузак району", "ob": "Жалал-Абад облусу"}, {"name": "Манас шаары", "ob": "Жалал-Абад облусу"}], open(core._sel_path(), "w"), ensure_ascii=False)
core.init_db()
STUB = open("/home/claude/taxi-tap/tests/leaflet_stub.js").read() + r"""
(function(){const _m=L.map,_k=L.marker,_p=L.polygon;
const bb=pts=>{const la=pts.map(p=>p[0]),lo=pts.map(p=>p[1]);const b={a:[Math.max(...la),Math.max(...lo)],b:[Math.min(...la),Math.min(...lo)]};
 b.getNorth=()=>b.a[0];b.getSouth=()=>b.b[0];b.getEast=()=>b.a[1];b.getWest=()=>b.b[1];b.getCenter=()=>({lat:(b.a[0]+b.b[0])/2,lng:(b.a[1]+b.b[1])/2});
 b.lat=b.getCenter().lat;b.lng=b.getCenter().lng;return b};
L.latLngBounds=a=>bb(a);
L.map=(id,o)=>{const m=_m(typeof id==="string"?id:(id.id=id.id||"amap",id.id));m.el.style.position="relative";m.doubleClickZoom={disable(){},enable(){}};
 m.fitBounds=(b)=>{const sp=Math.max(b.a[0]-b.b[0],(b.a[1]-b.b[1])*0.75);m.c=[(b.a[0]+b.b[0])/2,(b.a[1]+b.b[1])/2];m.z=Math.max(8,Math.min(16,Math.round(Math.log2(0.9*360/ (sp*1.6)))));m.draw();return m};
 m.invalidateSize=()=>m;m.getContainer=()=>m.el;return m};
L.marker=(p,o)=>{const k=_k(p,o);k.hs={};k.on=function(e,f){(this.hs[e]=this.hs[e]||[]).push(f);if(this.el&&e==="click")this.el.onclick=()=>f({});return this};
 const add=k.addTo.bind(k);k.addTo=function(g){add(g);this.el.style.cursor="pointer";if(this.hs.click)this.el.onclick=()=>this.hs.click.forEach(f=>f({}));return this};
 k.bindTooltip=function(){return this};return k};
L.polygon=(ps,o)=>{const p=_p(ps,Object.assign({},o,o&&o.fill===false?{fillOpacity:0}:{}));p.bindTooltip=function(){return this};p.getBounds=()=>bb(ps);return p};
const _g=L.layerGroup;L.layerGroup=()=>{const g=_g();const add=g.addTo.bind(g);g.addTo=function(x){if(x.items){x.items.push(this);this.m=x.m;this.m.layers.push(this);this.items.forEach(i=>i.addTo(this));return this}return add(x)};
 g.remove=function(){this.clearLayers()};return g};
L.circleMarker=(p,o)=>({addTo(){return this},bindTooltip(){return this}});
L.geoJSON=(gj,o)=>{const st=(o&&o.style)||{};const g=L.layerGroup();const rings=gj.type==="Polygon"?gj.coordinates:gj.coordinates.flat();
 const all=[];rings.forEach((r,i)=>{const ps=r.map(([lo,la])=>[la,lo]);all.push(...ps);g.items.push(L.polygon(ps,Object.assign({},st,i?{fillOpacity:0}:{},st.fill===false?{fillOpacity:0}:{})))});
 const add=g.addTo.bind(g);g.addTo=function(x){this.m=x.m||x;if(x.items)x.items.push(this);this.items.forEach(i=>i.addTo(x.items?x:this.m));return this};
 g.bindTooltip=function(){return this};g.getBounds=()=>bb(all);g.remove=function(){this.items.forEach(i=>i.remove())};return g};})();
"""
def route(r):
    u = r.request.url
    if u.endswith("leaflet.js"): return r.fulfill(body=STUB, content_type="application/javascript")
    if u.endswith("leaflet.css"): return r.fulfill(body="", content_type="text/css")
    if "tile" in u or "arcgis" in u: return r.abort()
    return r.continue_()
srv = subprocess.Popen([sys.executable, "web.py"], cwd="/home/claude/taxi-tap", env=os.environ.copy(), stdout=subprocess.DEVNULL); time.sleep(2)
F = ImageFont.truetype("/usr/share/fonts/opentype/inter/Inter-Black.otf", 21); FM = ImageFont.truetype("/usr/share/fonts/opentype/inter/Inter-Medium.otf", 17)
shots = []
def frame(k, t, s, sel=None):
    if sel: k.evaluate("document.querySelector(%r).scrollIntoView({block:'start'})" % sel); k.wait_for_timeout(300)
    k.screenshot(path="/tmp/b.png"); im = Image.open("/tmp/b.png").convert("RGB"); im = im.resize((390, int(im.size[1] * 390 / im.size[0])))
    c = Image.new("RGB", (430, im.size[1] + 100), "#fafafa"); d = ImageDraw.Draw(c)
    d.rounded_rectangle([20, 14, 64, 58], 12, fill="#ffc61a"); d.text((42, 36), str(len(shots) + 1), font=F, fill="#16161a", anchor="mm")
    d.text((76, 12), t, font=F, fill="#1b1b20"); d.text((76, 48), s, font=FM, fill="#5f5f6a"); c.paste(im, (20, 90)); shots.append(c)
try:
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox", "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream", "--autoplay-policy=no-user-gesture-required"])
        cx = b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True, permissions=["microphone"])
        k = cx.new_page()
        k.route("**/*", route); k.on("pageerror", lambda e: print("JS:", e)); k.on("dialog", lambda d: d.accept())
        k.goto("http://127.0.0.1:8807/"); k.fill("#nm", "Кайрат"); k.fill("#ph", "0700 900 900"); k.check("#agree"); k.click("#go"); k.wait_for_timeout(1500)
        k.goto("http://127.0.0.1:8807/admin"); k.wait_for_timeout(1500); k.click("nav [data-t=voice]"); k.wait_for_timeout(800)
        frame(k, "Админ → 🎙 Үн", "28 сөз, 0 жазылды", None)
        k.click("#vAll"); k.wait_for_timeout(500)
        def rec():
            k.click("#vMic"); k.wait_for_timeout(1800); k.click("#vMic"); k.wait_for_timeout(1200)
        k.click("#vMic"); k.wait_for_timeout(900)
        frame(k, "Жазылып жатат", "«Жаңы заказ» — кайра басса токтойт", None)
        k.wait_for_timeout(900); k.click("#vMic"); k.wait_for_timeout(1200)
        print("st:", k.inner_text("#vSt"))
        frame(k, "Даяр — угуп, сактайсыз", "Тынчтык кесилди, катуулук теңделди", None)
        for _ in range(7):
            k.click("#vSave"); k.wait_for_timeout(900); rec()
        k.click("#vSave"); k.wait_for_timeout(900); k.click("#vCx"); k.wait_for_timeout(300)
        k.evaluate("window.scrollTo(0,0)")
        frame(k, "8 сөз жазылды", "Калганын ушинтип катары менен", None)
        print(k.evaluate("fetch('/api/voice').then(r=>r.json()).then(v=>v.have)"))
        # айдоочу
        d = cx.new_page(); d.route("**/*", route); d.on("pageerror", lambda e: print("DJS:", e))
        d.goto("http://127.0.0.1:8807/driver"); d.wait_for_timeout(1500); d.evaluate("voiceLoad()"); d.wait_for_timeout(1500)
        print("vbuf:", d.evaluate("Object.keys(VBUF)"))
        print("kyNum:", d.evaluate("[kyNum(80),kyNum(250),kyNum(1500),kyKm(1.2),kyKm(3)].map(a=>a.map(k=>VLBL[k]).join(' '))"))
        d.evaluate("""window.PLAYED=[];const _c=AudioContext.prototype.createBufferSource;AudioContext.prototype.createBufferSource=function(){const s=_c.call(this);const st=s.start.bind(s);s.start=function(){const k=Object.keys(VBUF).find(x=>VBUF[x].b===s.buffer);PLAYED.push(k);st()};return s};
          window.TTS=[];speechSynthesis.speak=u=>{TTS.push(u.text);setTimeout(()=>u.onend&&u.onend(),100)};0""")
        d.evaluate("speak(['new_order',...kyNum(80),'som',...kyKm(1.2)])"); d.wait_for_timeout(6000)
        print("played:", d.evaluate("PLAYED"), "tts:", d.evaluate("TTS"))
        d.evaluate("""window.SP=[];window.speak=(t)=>SP.push(t.join('+'));window.beep=()=>{};0""")
        d.evaluate("""(()=>{const base={min_balance:0,balance:100};
          voiceEvents(Object.assign({},base,{ride:{id:5,status:'accepted'}}),Object.assign({},base,{ride:null}));
          voiceEvents(Object.assign({},base,{offer:{id:7}}),Object.assign({},base,{}));
          voiceEvents(Object.assign({},base,{offer:{id:8}}),Object.assign({},base,{ride:{id:8,status:'accepted'}}));
          voiceEvents(base,Object.assign({},base,{ride:{id:9,status:'arrived',wait:{arrived_at:0,now:301}}}));
          VE.low=false;voiceEvents(base,{min_balance:50,balance:10});
          D={ride:{id:11,status:'accepted',p:[41,72.9]}};myPos=[41.0005,72.9005];nearCheck();})()""")
        print("driver events:", d.evaluate("SP"))
        rp = cx.new_page(); rp.route("**/*", route); rp.goto("http://127.0.0.1:8807/"); rp.wait_for_timeout(1500)
        rp.evaluate("""window.SP=[];window.speak=(t)=>SP.push(t.join('+'));S.mode='ride';
          riderVoice({id:1,status:'searching'},{id:1,status:'accepted'});riderVoice({id:1,status:'accepted'},{id:1,status:'arrived'});
          riderVoice({id:1,status:'arrived'},{id:1,status:'in_trip',msgs:[{me:false,text:'x'}]});0""")
        print("rider events:", rp.evaluate("SP"))
        b.close()
finally:
    srv.terminate()
W = sum(c.size[0] for c in shots); H = max(c.size[1] for c in shots)
out = Image.new("RGB", (W, H), "#fafafa"); x = 0
for c in shots: out.paste(c, (x, 0)); x += c.size[0]
out.save("/tmp/voice_real.png"); print(len(shots))
