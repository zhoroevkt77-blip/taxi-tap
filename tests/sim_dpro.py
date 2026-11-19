"""Айдоочунун жаңы экрандары: заказ көп жер, фотоконтроль, киреше, заказ чиптери, сапар баскычтары."""
import json, os, subprocess, sys, time, tempfile
TMP = tempfile.mkdtemp()
os.environ.update(SQLITE_PATH=os.path.join(TMP, "s.db"), DATA_DIR=TMP, DATABASE_URL="", SERVICE_AREA="off",
                  WEB_DEV_LOGIN="1", PORT="8797", ADMIN_PHONES="0700555001", COMMISSION_PCT="10", OSRM_URL="")
sys.path.insert(0, "/home/claude/taxi-tap")
import core, flow, addrbook
from playwright.sync_api import sync_playwright
from PIL import Image, ImageDraw, ImageFont
STUB = open("/home/claude/taxi-tap/tests/leaflet_stub.js").read()
A, DS = (41.0377, 72.7470), (41.0430, 72.7400)
core.init_db()
DRV = core.phone_uid("0700555001"); core.ensure_user(DRV, "Кайрат"); core.set_user(DRV, phone=DRV[3:])
flow.register_driver(DRV, "Кайрат", "Хюндай Солярис", "Асфальт", "04KG338APG", {"license": "x", "techpass": "x", "car": "x"})
flow.admin_driver(DRV, "approve"); core.add_tx(DRV, 993, "topup")
addrbook.save("Автовокзал", "bus", 41.0300, 72.7560)
t = core.now()
for i in range(7):
    core.query("INSERT INTO rides (passenger, status, p_lat, p_lon, created_at) VALUES ('tg:9', 'completed', 41.0301, 72.7561, ?)", (t - 120,))
for i, pr in enumerate((80, 120, 150, 95, 210, 70, 130, 110, 90)):
    core.query("INSERT INTO rides (passenger, driver, status, price, completed_at, created_at) VALUES ('tg:8', ?, 'completed', ?, ?, ?)", (DRV, pr, t - 600 * (i + 1), t - 600 * (i + 1) - 900))
    core.add_tx(DRV, -pr * 0.1, "commission")
core.add_tx(DRV, 50, "promo")
day = time.strftime("%Y-%m-%d", time.gmtime(t + core.TZ))
core.query("INSERT INTO driver_online (uid, day, sec) VALUES (?, ?, ?)", (DRV, day, 6 * 3600 + 1200))
def route(r):
    u = r.request.url
    if u.endswith("leaflet.js"): return r.fulfill(body=STUB, content_type="application/javascript")
    if u.endswith("leaflet.css"): return r.fulfill(body="", content_type="text/css")
    if "tile" in u or "arcgis" in u or "nominatim" in u: return r.abort()
    return r.continue_()
srv = subprocess.Popen([sys.executable, "web.py"], cwd="/home/claude/taxi-tap", env=os.environ.copy(), stdout=subprocess.DEVNULL); time.sleep(1.8)
URL = "http://127.0.0.1:8797"
F = ImageFont.truetype("/usr/share/fonts/opentype/inter/Inter-SemiBold.otf", 22); FM = ImageFont.truetype("/usr/share/fonts/opentype/inter/Inter-Medium.otf", 17)
shots = []
def frame(k, title, sub, wait=500, sel=None):
    k.wait_for_timeout(wait)
    if sel: k.evaluate("document.querySelector(%r)&&document.querySelector(%r).scrollIntoView({block:'center'})" % (sel, sel)); k.wait_for_timeout(300)
    k.screenshot(path="/tmp/dp.png"); im = Image.open("/tmp/dp.png").convert("RGB"); im = im.resize((390, int(im.size[1] * 390 / im.size[0])))
    c = Image.new("RGB", (430, im.size[1] + 96), "#fafafa"); d = ImageDraw.Draw(c)
    d.rounded_rectangle([20, 14, 64, 58], 12, fill="#ffc61a"); d.text((42, 36), str(len(shots) + 1), font=F, fill="#16161a", anchor="mm")
    d.text((76, 12), title, font=F, fill="#1b1b20"); d.text((76, 46), sub, font=FM, fill="#5f5f6a"); c.paste(im, (20, 86)); shots.append(c)
try:
    with sync_playwright() as p:
        br = p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
        ph = dict(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True, permissions=["geolocation"], color_scheme="light")
        dc = br.new_context(**ph, geolocation={"latitude": DS[0], "longitude": DS[1]}); dv = dc.new_page()
        dv.route("**/*", route); dv.on("pageerror", lambda e: print("JS:", e)); dv.on("dialog", lambda x: x.accept())
        dv.add_init_script("try{localStorage.mapTheme='light'}catch(e){}")
        dv.goto(URL + "/driver"); dv.fill("#nm", "Кайрат"); dv.fill("#ph", "0700 555 001"); dv.check("#agree"); dv.click("#go"); dv.wait_for_timeout(1800)
        core.driver_location(DRV, *DS, live_period=3600)
        dv.reload(); dv.wait_for_timeout(2200)
        dv.evaluate("SHEET&&SHEET.expand&&SHEET.expand()")
        frame(dv, "Башкы экран", "🔥 Заказ көп жер · 📷 Фотоконтроль карточкалары", 800, "#hot")
        dv.click("#earn"); 
        frame(dv, "Максат чипин басканда — Киреше", "Бүгүн / Жума / Ай · тегерек · чиптер", 900, "#ePer")
        dv.click("[data-ep='week']"); frame(dv, "«Жума» тандалды", "Максат ×7, бөлүнүшү чиптер менен", 300, "#ePer")
        dv.click("[data-k='cab']") if dv.locator("[data-k='cab']").count() else None
        dv.evaluate("viewCabinet()"); dv.wait_for_timeout(600)
        dv.click("#phCard"); frame(dv, "Фотоконтроль", "4 тарап: алды, арты, сол, оң — камера менен", 700)
        dv.evaluate("viewHome()"); dv.wait_for_timeout(300)
        dv.evaluate("viewHome()"); dv.wait_for_timeout(400); dv.evaluate("goOnline(null)"); dv.wait_for_timeout(1500)
        u = core.phone_uid("0555111222"); core.ensure_user(u, "Айгүл"); core.set_user(u, phone=u[3:])
        q = core.quote(A[0], A[1], 41.0300, 72.7560)
        rid = core.create_ride(u, q, A[0], A[1], 41.0300, 72.7560, p_addr="Ленин көчөсү, 15", d_addr="Автовокзал")
        flow.dispatch_ride(rid) if hasattr(flow, "dispatch_ride") else None
        import dispatch; dispatch.tick() if hasattr(dispatch, "tick") else None
        dv.wait_for_timeout(3500)
        frame(dv, "Жаңы заказ — сары чиптер", "📍 км · ⏱ мүн · 💵 баа · ⭐ рейтинг, «сүрүп алуу» калды", 300)
        kb = dv.locator("#knob").bounding_box(); tr = dv.locator("#acc").bounding_box()
        dv.mouse.move(kb["x"] + 20, kb["y"] + 20); dv.mouse.down()
        for i in range(1, 11): dv.mouse.move(kb["x"] + 20 + (tr["width"] - 60) * i / 10, kb["y"] + 20)
        dv.mouse.up(); dv.wait_for_timeout(2000)
        dv.evaluate("SHEET&&SHEET.expand&&SHEET.expand()")
        frame(dv, "Сапар — тегерек баскычтар", "Чалуу · Чат · Навигатор · Жардам + «Келдим»", 600, ".rbtns")
        br.close()
finally:
    srv.terminate()
W = sum(c.size[0] for c in shots); H = max(c.size[1] for c in shots)
out = Image.new("RGB", (W, H), "#fafafa"); x = 0
for c in shots: out.paste(c, (x, 0)); x += c.size[0]
out.save("/tmp/dpro_sim.png"); print(len(shots))
