import os, subprocess, sys, time, tempfile
TMP = tempfile.mkdtemp()
os.environ.update(SQLITE_PATH=os.path.join(TMP, "s.db"), DATA_DIR=TMP, DATABASE_URL="", SERVICE_AREA="off", WEB_DEV_LOGIN="1", PORT="8783", OSRM_URL="")
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
F = ImageFont.truetype("/usr/share/fonts/opentype/inter/Inter-Black.otf", 21); FM = ImageFont.truetype("/usr/share/fonts/opentype/inter/Inter-Medium.otf", 17)
shots = []
def frame(k, t, s):
    k.screenshot(path="/tmp/g.png"); im = Image.open("/tmp/g.png").convert("RGB"); im = im.resize((390, int(im.size[1] * 390 / im.size[0])))
    c = Image.new("RGB", (430, im.size[1] + 100), "#fafafa"); d = ImageDraw.Draw(c)
    d.rounded_rectangle([20, 14, 64, 58], 12, fill="#ffc61a"); d.text((42, 36), str(len(shots) + 1), font=F, fill="#16161a", anchor="mm")
    d.text((76, 12), t, font=F, fill="#1b1b20"); d.text((76, 48), s, font=FM, fill="#5f5f6a"); c.paste(im, (20, 90)); shots.append(c)
IPH = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
try:
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
        for n, ua in enumerate((None, IPH)):
            kw = dict(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True)
            if ua: kw["user_agent"] = ua
            k = b.new_context(**kw).new_page(); k.route("**/*", route); k.on("pageerror", lambda e: print("JS:", e))
            k.goto("http://127.0.0.1:8783/"); k.fill("#nm", "Кайрат"); k.fill("#ph", "0227 15560%d" % n); k.check("#agree"); k.click("#go")
            k.wait_for_timeout(1500); k.evaluate("viewStepA()"); k.wait_for_timeout(1500)
            if ua is None:
                k.evaluate("S.gps.state='off';gpsPaint()"); k.wait_for_timeout(300)
                frame(k, "Android: GPS өчүк", "Кантип күйгүзүү — 3 кадам")
                k.evaluate("S.gps.state='denied';gpsPaint()"); k.wait_for_timeout(300)
                frame(k, "Android: уруксат жок", "Браузерде уруксатты кайра берүү")
                k.click("#gpsRetry"); k.wait_for_timeout(200)
                k.evaluate("S.gps={state:'ok',acc:18,at:Date.now(),ll:[41.04,72.75]};S.fromAddr='Осмонов Бекмат көчөсү';gpsPaint()")
                frame(k, "«Кайра аракет» → GPS табылды", "Карта жоголот, кадимки абал")
            else:
                k.evaluate("S.gps.state='off';gpsPaint()"); k.wait_for_timeout(300)
                frame(k, "iPhone: GPS өчүк", "iPhone'дун жөндөөлөрү боюнча кадамдар")
        b.close()
finally:
    srv.terminate()
W = sum(c.size[0] for c in shots); H = max(c.size[1] for c in shots)
out = Image.new("RGB", (W, H), "#fafafa"); x = 0
for c in shots: out.paste(c, (x, 0)); x += c.size[0]
out.save("/tmp/gps_sim.png"); print(len(shots))
