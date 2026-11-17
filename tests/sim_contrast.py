# Караңгы режимде окулбай калган жазууларды табуу + сүрөт
import os, subprocess, sys, time, tempfile, json
TMP = tempfile.mkdtemp()
os.environ.update(SQLITE_PATH=os.path.join(TMP, "s.db"), DATA_DIR=TMP, DATABASE_URL="", SERVICE_AREA="off", WEB_DEV_LOGIN="1", PORT="8787", OSRM_URL="")
sys.path.insert(0, "/home/claude/taxi-tap")
import core
from playwright.sync_api import sync_playwright
STUB = open("/home/claude/taxi-tap/tests/leaflet_stub.js").read()
OUT = sys.argv[1] if len(sys.argv) > 1 else "/tmp/cx"
core.init_db()
def route(r):
    u = r.request.url
    if u.endswith("leaflet.js"): return r.fulfill(body=STUB, content_type="application/javascript")
    if u.endswith("leaflet.css"): return r.fulfill(body="", content_type="text/css")
    if "tile" in u or "arcgis" in u: return r.abort()
    return r.continue_()
SCAN = r"""(()=>{
 const lum=c=>{const m=c.match(/[\d.]+/g);if(!m)return null;const a=m.length>3?+m[3]:1;const f=v=>{v/=255;return v<=.03928?v/12.92:Math.pow((v+.055)/1.055,2.4)};return {L:.2126*f(+m[0])+.7152*f(+m[1])+.0722*f(+m[2]),a}};
 const bgOf=e=>{for(let x=e;x;x=x.parentElement){const c=getComputedStyle(x);if(c.backgroundImage&&c.backgroundImage!=='none'&&/gradient/.test(c.backgroundImage)){const m=c.backgroundImage.match(/rgba?\([^)]+\)/);if(m)return m[0]}
   const b=lum(c.backgroundColor);if(b&&b.a>.5)return c.backgroundColor}return 'rgb(18,19,23)'};
 const out=[];document.querySelectorAll('body *').forEach(e=>{
  const t=[...e.childNodes].filter(n=>n.nodeType===3&&n.textContent.trim()).map(n=>n.textContent.trim()).join(' ');if(!t)return;
  const r=e.getBoundingClientRect();if(r.width<4||r.height<4||r.bottom<0||r.top>innerHeight)return;
  const c=getComputedStyle(e);if(c.visibility==='hidden'||+c.opacity<.2)return;
  const f=lum(c.color),b=lum(bgOf(e));if(!f||!b)return;const hi=Math.max(f.L,b.L),lo=Math.min(f.L,b.L),cr=(hi+.05)/(lo+.05);
  if(cr<3)out.push(cr.toFixed(1)+' '+e.tagName.toLowerCase()+(e.id?'#'+e.id:'')+(typeof e.className==='string'&&e.className?'.'+e.className.trim().split(/\s+/).join('.'):'')+' «'+t.slice(0,30)+'»')});
 return [...new Set(out)]})()"""
srv = subprocess.Popen([sys.executable, "web.py"], cwd="/home/claude/taxi-tap", env=os.environ.copy(), stdout=subprocess.DEVNULL); time.sleep(1.5)
res = {}
def scan(k, name):
    k.evaluate("document.documentElement.classList.add('uidark','mapnight')"); k.wait_for_timeout(900)
    k.screenshot(path="%s_%s.png" % (OUT, name)); res[name] = k.evaluate(SCAN)
try:
    with sync_playwright() as p:
        br = p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
        ctx = br.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True, color_scheme="dark")
        k = ctx.new_page(); k.route("**/*", route); k.on("pageerror", lambda e: print("JS:", e))
        k.goto("http://127.0.0.1:8787/"); k.fill("#nm", "Кайрат"); k.fill("#ph", "0227 155 603"); k.check("#agree"); k.click("#go"); k.wait_for_timeout(1500)
        uid = core.phone_uid("0227 155 603")
        core.set_place(uid, "home", 41.04, 72.75, "Сайдуллаева Т. улица"); core.set_place(uid, "work", 41.03, 72.76, "Абдираимов")
        core.query("INSERT INTO rides (passenger, status, price, d_lat, d_lon, d_addr, p_addr, created_at, completed_at) VALUES (?, 'completed', 80, 41.05, 72.74, 'Курманбека улица', 'Манас', ?, ?)", (uid, core.now() - 3600, core.now() - 3000))
        k.goto("http://127.0.0.1:8787/"); k.wait_for_timeout(2000)
        k.evaluate("PLACES=null"); k.evaluate("api('/api/places').then(p=>{PLACES=p;S.near={classes:['econom'],free:0};viewIdle()})"); k.wait_for_timeout(1200)
        scan(k, "home")
        k.evaluate("viewStepA()"); k.wait_for_timeout(800); scan(k, "stepA")
        k.evaluate("viewStepB && viewStepB()"); k.wait_for_timeout(900); scan(k, "stepB")
        k.evaluate("viewCabinet()"); k.wait_for_timeout(1000); scan(k, "cab")
        k.click("#qH"); k.wait_for_timeout(900); k.evaluate("document.querySelector('#cabMore').scrollIntoView()"); scan(k, "hist")
        k.click("#qA"); k.wait_for_timeout(700); k.evaluate("document.querySelector('#cabMore').scrollIntoView()"); scan(k, "addr")
        k.click("#qS"); k.wait_for_timeout(700); k.evaluate("document.querySelector('#cabMore').scrollIntoView()"); scan(k, "set")
        d = br.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True, color_scheme="dark").new_page(); d.route("**/*", route); d.on("pageerror", lambda e: print("JS:", e))
        du = core.phone_uid("0700 555 777"); core.ensure_user(du, "Бакыт"); core.set_user(du, name="Бакыт", phone=du[3:])
        core.query("INSERT INTO drivers (uid, status, car_model, car_color, car_plate, balance, rating) VALUES (?, 'active', 'Toyota Camry', 'Ак', '04 101 ABC', 500, 4.9)", (du,))
        d.goto("http://127.0.0.1:8787/driver"); d.fill("#nm", "Бакыт"); d.fill("#ph", "0700 555 777"); d.check("#agree"); d.click("#go"); d.wait_for_timeout(2000)
        scan(d, "drv")
        for v in ("viewEarn", "viewCab", "viewCabinet", "viewTrips", "viewHelp"):
            if d.evaluate("typeof %s==='function'" % v):
                d.evaluate("%s()" % v); d.wait_for_timeout(900); scan(d, "drv_" + v)
        br.close()
finally:
    srv.terminate()
for k_, v in res.items():
    print("==", k_, len(v)); [print("   ", x) for x in v[:25]]
