import json, os, subprocess, sys, time, tempfile
TMP = tempfile.mkdtemp()
os.environ.update(SQLITE_PATH=os.path.join(TMP, "s.db"), DATA_DIR=TMP, DATABASE_URL="", SERVICE_AREA="off",
                  WEB_DEV_LOGIN="1", PORT="8774", ADMIN_PHONES="0700900900", OSRM_URL="", COMMISSION_PCT="10")
sys.path.insert(0, "/home/claude/taxi-tap")
import core, parks
from playwright.sync_api import sync_playwright
from PIL import Image, ImageDraw, ImageFont
STUB = open("/home/claude/taxi-tap/tests/leaflet_stub.js").read()
core.init_db()
# маалымат: парк, 3 айдоочу, сапарлар
pid = parks.save("Нур-Такси", "0700 777 001", share=30, ref_bonus=20, promo="NUR50", promo_amount=50)
def mkdrv(ph, name, model, plate, lat, lon, online):
    uid = core.phone_uid(ph); core.ensure_user(uid, name); core.set_user(uid, name=name, phone=uid[3:])
    core.query("INSERT INTO drivers (uid, status, car_model, car_color, car_plate, balance, rating, online, lat, lon, loc_at, live_until) VALUES (?, 'active', ?, 'Ак', ?, 1000, 4.9, ?, ?, ?, ?, ?)",
               (uid, model, plate, 1 if online else 0, lat, lon, core.now(), core.now() + 3600))
    parks.attach_driver(ph, pid); return uid
D = [mkdrv("0700 000 201", "Бакыт", "Toyota Camry", "04 101 ABC", 41.038, 72.747, True),
     mkdrv("0700 000 202", "Нурлан", "Honda Fit", "04 202 KGZ", 41.040, 72.750, True),
     mkdrv("0700 000 203", "Азамат", "Daewoo Nexia", "04 303 BKR", 41.036, 72.744, False)]
for i in range(9):
    u = core.phone_uid("0555 400 %03d" % i); core.ensure_user(u, "Ж%d" % i)
    if i < 5: parks.set_ref(u, "NUR50")
    q = core.quote(41.0377, 72.7470, 41.03 + i * 0.001, 72.756)
    rid = core.create_ride(u, q, 41.0377, 72.7470, 41.03 + i * 0.001, 72.756)
    d = D[i % 3]; core.offer(rid, d); core.accept(rid, d)
    for _ in range(3): core.advance(rid, d)
parks.add_payout(pid, 30, "апта 03.11–09.11")
def route(r):
    u = r.request.url
    if u.endswith("leaflet.js"): return r.fulfill(body=STUB, content_type="application/javascript")
    if u.endswith("leaflet.css"): return r.fulfill(body="", content_type="text/css")
    return r.continue_()
srv = subprocess.Popen([sys.executable, "web.py"], cwd="/home/claude/taxi-tap", env=os.environ.copy(), stdout=subprocess.DEVNULL); time.sleep(1.5)
URL = "http://127.0.0.1:8774"; shots = []
F = ImageFont.truetype("/usr/share/fonts/opentype/inter/Inter-Black.otf", 21); FM = ImageFont.truetype("/usr/share/fonts/opentype/inter/Inter-Medium.otf", 18)
def frame(pg, t, s, full=False):
    path = "/tmp/pk_%02d.png" % (len(shots) + 1); pg.screenshot(path=path, full_page=full)
    im = Image.open(path).convert("RGB"); w, h = im.size
    if full: im = im.crop((0, 0, w, min(h, 1688 * 2)))
    im = im.resize((390, int(im.size[1] * 390 / w)))
    c = Image.new("RGB", (430, im.size[1] + 110), "#fafafa"); d = ImageDraw.Draw(c)
    d.rounded_rectangle([20, 14, 64, 58], 12, fill="#ffc61a"); d.text((42, 36), str(len(shots) + 1), font=F, fill="#16161a", anchor="mm")
    d.text((76, 12), t, font=F, fill="#1b1b20"); d.text((76, 50), s, font=FM, fill="#5f5f6a")
    c.paste(im, (20, 96)); shots.append(c)
try:
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
        def ctx(): x = b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2); pg = x.new_page(); pg.route("**/*", route); pg.on("pageerror", lambda e: print("JS:", e)); return pg
        a = ctx(); a.set_viewport_size({"width": 390, "height": 844})
        a.goto(URL + "/admin"); a.fill("#ph", "0700 900 900"); a.click("#go"); a.wait_for_timeout(1500)
        a.click("nav button[data-t='parks']"); a.wait_for_timeout(1200)
        frame(a, "Админ: «Парктар» бөлүмү", "Парк, ээсинин номери, үлүш %, бонус, промокод")
        a.evaluate("window.scrollTo(0, 99999)"); a.wait_for_timeout(300)
        frame(a, "Админ: жаңы парк / айдоочуну кошуу", "Айдоочуну номери менен паркка байлоо")
        k = ctx(); k.goto(URL + "/"); k.fill("#nm", "Нур"); k.fill("#ph", "0700 777 001"); k.check("#agree"); k.click("#go"); k.wait_for_timeout(1200)
        k.goto(URL + "/park"); k.wait_for_timeout(2000)
        frame(k, "Парктын кабинети", "Калдык, сапарлар, жүгүртүү, үлүш, жаңы жүргүнчүлөр")
        k.click("[data-p='today']"); k.wait_for_timeout(300)
        k.evaluate("document.querySelector('.card').scrollIntoView()"); k.wait_for_timeout(300)
        frame(k, "Парктын айдоочулары", "Ким линияда, бүгүн/жумалык сапар, рейтинг ⚡")
        k.evaluate("document.querySelectorAll('.card')[1].scrollIntoView()"); k.wait_for_timeout(500)
        frame(k, "Жүргүнчүлөрдү тартуу: QR + код", "Ар бир жаңы жүргүнчү үчүн паркка бонус")
        k.evaluate("window.print=()=>{}"); k.click("#print"); k.emulate_media(media="print"); k.wait_for_timeout(400)
        frame(k, "Унаага жабыштырчу стикер", "Басып чыгарып, ар бир таксиге жабыштырат")
        k.emulate_media(media="screen")
        k.evaluate("document.querySelectorAll('.card')[2].scrollIntoView()"); k.wait_for_timeout(300)
        frame(k, "Төлөмдөр жана шарттар", "Админ «Төлөдүм» басканда бул жерге түшөт")
        r = ctx(); r.goto(URL + "/p/NUR50"); r.wait_for_timeout(800)
        r.fill("#nm", "Айпери"); r.fill("#ph", "0555 123 456"); r.check("#agree"); r.click("#go"); r.wait_for_timeout(1800)
        frame(r, "Жүргүнчү QR'ды сканерледи", "Кирди — NUR50 коду өзү сакталды, паркка эсептелди")
        print("ref:", core.get_user(core.phone_uid("0555 123 456")).get("park_ref"), "promoPre:", r.evaluate("localStorage.getItem('promoPre')"))
        b.close()
finally:
    srv.terminate()
for i, c in enumerate(shots, 1): c.save("/tmp/pkf_%02d.png" % i)
print(len(shots))
