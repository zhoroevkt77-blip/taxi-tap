"""Айдоочунун картасында жакын жердеги линиядагы таксилер. python tests/sim_peers.py → tests/shots/peers/*.png"""
import json, os, subprocess, sys, time, tempfile
TMP = tempfile.mkdtemp()
os.environ.update(SQLITE_PATH=os.path.join(TMP, "s.db"), DATA_DIR=TMP, DATABASE_URL="", SERVICE_AREA="off",
                  WEB_DEV_LOGIN="1", PORT="8771", ADMIN_PHONES="0700900900", COMMISSION_PCT="10", OSRM_URL="")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import core, flow
from playwright.sync_api import sync_playwright
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "shots", "stripes"); os.makedirs(OUT, exist_ok=True)
for f in os.listdir(OUT): os.remove(os.path.join(OUT, f))
STUB = open(os.path.join(HERE, "leaflet_stub.js")).read()
A1 = (41.0430, 72.7400)             # 1-жүргүнчү
B1 = (41.0377, 72.7470)             # 1-жүргүнчүнүн бара турган жери
A = (41.0362, 72.7488)              # 2-жүргүнчү (B1ден ~200 м)
B = (41.0300, 72.7560)              # 2-жүргүнчүнүн бара турган жери
DSTART = A1
core.init_db()
DRV = core.phone_uid("0700555001")
core.ensure_user(DRV, "Бакыт"); core.set_user(DRV, phone=DRV[3:])
flow.register_driver(DRV, "Бакыт", "Hyundai Solaris", "Ак", "04 338 APG", {"license": "x", "techpass": "x", "car": "x"})
flow.admin_driver(DRV, "approve"); core.add_tx(DRV, 1000, "topup")

REV = {"address": {"road": "Айтматов көчөсү", "house_number": "50"}}
F_B = ImageFont.truetype("/usr/share/fonts/opentype/inter/Inter-Black.otf", 34)
F_M = ImageFont.truetype("/usr/share/fonts/opentype/inter/Inter-Medium.otf", 24)
F_S = ImageFont.truetype("/usr/share/fonts/opentype/inter/Inter-ExtraBold.otf", 22)


def route(r):
    u = r.request.url
    if u.endswith("leaflet.js"): return r.fulfill(body=STUB, content_type="application/javascript")
    if u.endswith("leaflet.css"): return r.fulfill(body="", content_type="text/css")
    if "nominatim" in u or "photon" in u: return r.fulfill(body=json.dumps(REV), content_type="application/json")
    return r.continue_()


PEERS = [(41.0452, 72.7425, 0), (41.0410, 72.7372, 0), (41.0398, 72.7441, 1), (41.0468, 72.7368, 0),
         (41.0421, 72.7463, 1), (41.0445, 72.7352, 0), (41.0700, 72.7900, 0)]   # акыркысы 3 кмден алыс
for i, (la, lo, busy) in enumerate(PEERS):
    u = core.phone_uid("07005550%02d" % (10 + i)); core.ensure_user(u, "Д%d" % i); core.set_user(u, phone=u[3:])
    flow.register_driver(u, "Д%d" % i, "Toyota", "Ак", "01 1%02d AAA" % i, {"license": "x", "techpass": "x", "car": "x"})
    flow.admin_driver(u, "approve"); core.add_tx(u, 500, "topup")
    core.driver_location(u, la, lo, live_period=3600); core.set_driver(u, online=1, busy_ride=(999 + i) if busy else None)


V = {"A — Оң бурчта, машинадагыдай": ".sheet::before,.rboxc::before{left:auto!important;width:34%!important;height:260px!important;background:url(/static/v_a.webp) right 0 top -40px/100% auto no-repeat!important}",
     "B — Үстүңкү четте узун полоса": ".sheet::before,.rboxc::before{left:0!important;right:0!important;width:100%!important;height:70px!important;background:url(/static/v_b.webp) left 0 top 0/100% auto no-repeat!important}",
     "C — A + B бирге": ".sheet::before,.rboxc::before{left:0!important;width:100%!important;height:260px!important;background:url(/static/v_a.webp) right 0 top -40px/34% auto no-repeat,url(/static/v_b.webp) left 0 top 0/100% auto no-repeat!important}",
     "D — Мурунку ийри полоса": ".sheet::before,.rboxc::before{left:auto!important;width:34%!important;height:260px!important;background:url(/static/v_old.webp) right 0 top -40px/100% auto no-repeat!important}"}
srv = subprocess.Popen([sys.executable, "web.py"], env=os.environ.copy(), stdout=subprocess.DEVNULL); time.sleep(1.5)
URL = "http://127.0.0.1:8771"
shots = []
try:
    with sync_playwright() as p:
        br = p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
        ph = dict(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True, permissions=["geolocation"])
        dc = br.new_context(**ph, geolocation={"latitude": DSTART[0], "longitude": DSTART[1]})
        rc = br.new_context(**ph, geolocation={"latitude": DSTART[0], "longitude": DSTART[1]})
        dv, r = dc.new_page(), rc.new_page()
        for pg in (dv, r): pg.route("**/*", route)
        dv.goto(URL + "/driver"); dv.fill("#nm", "Кайрат"); dv.fill("#ph", "0700 555 001"); dv.check("#agree"); dv.click("#go")
        dv.wait_for_timeout(1500); dv.evaluate("goOffline && goOffline()"); dv.wait_for_timeout(800)
        r.goto(URL + "/"); r.fill("#nm", "Айгүл"); r.fill("#ph", "0555 111 222"); r.check("#agree"); r.click("#go"); r.wait_for_timeout(1500)
        for i, (name, css) in enumerate(V.items()):
            for pg in (dv, r):
                pg.evaluate("css => { let s = document.getElementById('vcss'); if (!s) { s = document.createElement('style'); s.id = 'vcss'; document.head.appendChild(s); } s.textContent = css; }", css)
            dv.wait_for_timeout(700)
            a, b = os.path.join(TMP, "d%d.png" % i), os.path.join(TMP, "r%d.png" % i)
            dv.screenshot(path=a); r.screenshot(path=b); shots.append((name, a, b))
        br.close()
finally:
    srv.terminate()
W = 520
c = Image.new("RGB", (2 * (W + 30) + 20, 2 * 720 + 40), "#f2f2f4"); d = ImageDraw.Draw(c)
for i, (name, a, b) in enumerate(shots):
    x, y = 20 + (i % 2) * (W + 30), 20 + (i // 2) * 720
    d.text((x, y), name, font=F_S, fill="#1b1b20")
    im = Image.open(a); im = im.crop((0, 380, 780, 1380)).resize((W, 667))
    m = Image.new("L", im.size, 0); ImageDraw.Draw(m).rounded_rectangle([0, 0, W, 667], 22, fill=255)
    c.paste(im, (x, y + 46), m)
c.save(os.path.join(OUT, "variants.png")); print("ok")
