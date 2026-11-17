import os, subprocess, sys, time, tempfile
TMP = tempfile.mkdtemp()
os.environ.update(SQLITE_PATH=os.path.join(TMP, "s.db"), DATA_DIR=TMP, DATABASE_URL="", SERVICE_AREA="off", WEB_DEV_LOGIN="1", PORT="8785", OSRM_URL="")
sys.path.insert(0, "/home/claude/taxi-tap")
import core
from playwright.sync_api import sync_playwright
from PIL import Image, ImageDraw, ImageFont
STUB = open("/home/claude/taxi-tap/tests/leaflet_stub.js").read()
core.init_db()
def route(r):
    u = r.request.url
    if u.endswith("leaflet.js"): return r.fulfill(body=STUB, content_type="application/javascript")
    if u.endswith("leaflet.css"): return r.fulfill(body="", content_type="text/css")
    if "tile" in u or "arcgis" in u: return r.abort()
    return r.continue_()
srv = subprocess.Popen([sys.executable, "web.py"], cwd="/home/claude/taxi-tap", env=os.environ.copy(), stdout=subprocess.DEVNULL); time.sleep(1.5)
F = ImageFont.truetype("/usr/share/fonts/opentype/inter/Inter-Black.otf", 22)
pairs = []
DARK = "document.documentElement.classList.add('uidark','mapnight')"
LIGHT = "document.documentElement.classList.remove('uidark','mapnight')"
def shot(k):
    k.screenshot(path="/tmp/d.png"); im = Image.open("/tmp/d.png").convert("RGB"); return im.resize((360, int(im.size[1] * 360 / im.size[0])))
def pair(k, title):
    k.evaluate(LIGHT); k.wait_for_timeout(250); a = shot(k)
    k.evaluate(DARK); k.wait_for_timeout(900); b = shot(k)
    pairs.append((title, a, b))
    print(title, k.evaluate("""(()=>{const o=new Set();document.querySelectorAll('body *').forEach(e=>{const c=getComputedStyle(e);const r=e.getBoundingClientRect();
      if(r.width>20&&r.height>14&&r.bottom>0&&r.top<844&&c.visibility!=='hidden'&&c.display!=='none'&&/rgb\(25[0-5], 25[0-5], 2[45]\d/.test(c.backgroundColor+' '+c.backgroundImage))o.add(e.tagName.toLowerCase()+(e.id?'#'+e.id:'')+(e.className&&typeof e.className==='string'?'.'+e.className.trim().split(/\s+/).join('.'):''))});return [...o].join(' | ')})()"""))
try:
    with sync_playwright() as p:
        br = p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
        k = br.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True).new_page()
        k.route("**/*", route); k.on("pageerror", lambda e: print("JS:", e))
        k.goto("http://127.0.0.1:8785/"); k.fill("#nm", "Кайрат"); k.fill("#ph", "0227 155 601"); k.check("#agree"); k.click("#go"); k.wait_for_timeout(1500)
        k.wait_for_timeout(300)
        pair(k, "Башкы бет")
        k.evaluate("viewStepA()"); k.wait_for_timeout(800); k.evaluate("S.gps={state:'ok',acc:18,at:Date.now(),ll:[41.04,72.75]};S.fromAddr='Осмонов Бекмат көчөсү';gpsPaint();$('#fromTxt').textContent=S.fromAddr")
        pair(k, "Заказ: А точка")
        k.evaluate("viewCabinet()"); k.wait_for_timeout(1000)
        pair(k, "Кабинет")
        d = br.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True).new_page()
        d.route("**/*", route); d.on("pageerror", lambda e: print("JS:", e))
        uid = core.phone_uid("0700 555 777"); core.ensure_user(uid, "Бакыт"); core.set_user(uid, name="Бакыт", phone=uid[3:])
        core.query("INSERT INTO drivers (uid, status, car_model, car_color, car_plate, balance, rating) VALUES (?, 'active', 'Toyota Camry', 'Ак', '04 101 ABC', 500, 4.9)", (uid,))
        d.goto("http://127.0.0.1:8785/driver"); d.fill("#nm", "Бакыт"); d.fill("#ph", "0700 555 777"); d.check("#agree"); d.click("#go"); d.wait_for_timeout(2000)
        d.wait_for_timeout(300)
        pair(d, "Айдоочу")
        br.close()
finally:
    srv.terminate()
W = 360 * 2 + 30; cols = []
for t, a, b in pairs:
    h = max(a.size[1], b.size[1]); c = Image.new("RGB", (W, h + 56), "#fafafa"); dr = ImageDraw.Draw(c)
    dr.text((10, 14), t + "  ·  ☀️ / 🌙", font=F, fill="#16161a"); c.paste(a, (0, 56)); c.paste(b, (390, 56)); cols.append(c)
out = Image.new("RGB", (W * 2 + 40, (cols[0].size[1]) * 2 + 20), "#fafafa")
for i, c in enumerate(cols): out.paste(c, ((i % 2) * (W + 40), (i // 2) * (c.size[1] + 20)))
out.save("/tmp/dark_sim.png"); print(len(pairs))
