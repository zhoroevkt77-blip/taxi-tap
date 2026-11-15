import json, os, subprocess, sys, time, tempfile
TMP = tempfile.mkdtemp()
os.environ.update(SQLITE_PATH=os.path.join(TMP, "s.db"), DATA_DIR=TMP, DATABASE_URL="", SERVICE_AREA="off",
                  WEB_DEV_LOGIN="1", PORT="8775", ADMIN_PHONES="0700900900", OSRM_URL="", COMMISSION_PCT="5")
sys.path.insert(0, "/home/claude/taxi-tap")
import core, parks
from playwright.sync_api import sync_playwright
from PIL import Image, ImageDraw, ImageFont
STUB = open("/home/claude/taxi-tap/tests/leaflet_stub.js").read()
core.init_db()
# маалымат: парк, 3 айдоочу, сапарлар
pid = parks.save("Драйв Базар-Коргон", "0700 777 001", share=80, ref_bonus=10, promo="NUR50", promo_amount=50)
core.query("UPDATE parks SET created_at=? WHERE id=?", (core.now() - 60 * 86400, pid))
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
a0, b0 = parks.month_bounds("2026-10")
for i, r in enumerate(core.query("SELECT id FROM rides", (), "all")):
    core.query("UPDATE rides SET completed_at=? WHERE id=?", (a0 + (i + 1) * 3 * 86400, r["id"]))
for i, t in enumerate(core.query("SELECT id FROM balance_tx WHERE kind='commission'", (), "all")):
    core.query("UPDATE balance_tx SET at=? WHERE id=?", (a0 + (i + 1) * 3 * 86400, t["id"]))
for k, (amt, day) in enumerate(((10, 6), (8, 13), (9, 20))):
    core.query("INSERT INTO park_payouts (park_id, amount, note, at) VALUES (?, ?, ?, ?)", (pid, amt, "апта", a0 + day * 86400 + 11 * 3600))
AID, _ = parks.act_make(pid, "2026-10")
print(parks.act_get(AID)["data"])
def route(r):
    u = r.request.url
    if u.endswith("leaflet.js"): return r.fulfill(body=STUB, content_type="application/javascript")
    if u.endswith("leaflet.css"): return r.fulfill(body="", content_type="text/css")
    return r.continue_()
srv = subprocess.Popen([sys.executable, "web.py"], cwd="/home/claude/taxi-tap", env=os.environ.copy(), stdout=subprocess.DEVNULL); time.sleep(1.5)
URL = "http://127.0.0.1:8775"; shots = []
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
        k = ctx(); k.goto(URL + "/"); k.fill("#nm", "Нур"); k.fill("#ph", "0700 777 001"); k.check("#agree"); k.click("#go"); k.wait_for_timeout(1200)
        k.goto(URL + "/park"); k.wait_for_timeout(2000)
        k.evaluate("[...document.querySelectorAll('.card')].find(c => c.textContent.includes('Акт салыштыруу')).scrollIntoView()"); k.wait_for_timeout(300)
        frame(k, "Парк кабинети: Акт салыштыруу", "Ай сайын 1-күнү түшөт · Telegram'га кабар")
        k.evaluate("document.querySelector('.adis').open = true"); k.fill("textarea", "2 сапар эсептелбей калган"); k.wait_for_timeout(200)
        frame(k, "«Пикирим бар» — эмнеси туура эмес", "Жазып жөнөтөт → админге кабар кетет")
        k.goto(URL + "/act/%d" % AID); k.wait_for_timeout(800)
        frame(k, "Акт (ачуу / PDF)", "Басып чыгарып, кол коюп, мөөр басса болот", full=True)
        k.goto(URL + "/park"); k.wait_for_timeout(1500); k.on("dialog", lambda d: d.accept())
        k.evaluate("[...document.querySelectorAll('.card')].find(c => c.textContent.includes('Акт салыштыруу')).scrollIntoView()")
        k.click("[data-aok]"); k.wait_for_timeout(1200)
        k.evaluate("[...document.querySelectorAll('.card')].find(c => c.textContent.includes('Акт салыштыруу')).scrollIntoView()"); k.wait_for_timeout(300)
        frame(k, "«Макулмун» басылды", "Ырасталган ай жабылат, өзгөрбөйт")
        a = ctx(); a.goto(URL + "/admin"); a.fill("#ph", "0700 900 900"); a.click("#go"); a.wait_for_timeout(1500)
        a.click("nav button[data-t='parks']"); a.wait_for_timeout(1500)
        a.evaluate("[...document.querySelectorAll('.panel h3')].find(h => h.textContent.includes('Акт')).scrollIntoView()"); a.wait_for_timeout(300)
        frame(a, "Админ: бардык акттар", "Статус, калдык · кол менен түзүү / кайра эсептөө")
        b.close()
finally:
    srv.terminate()
W = sum(c.size[0] for c in shots); H = max(c.size[1] for c in shots)
out = Image.new("RGB", (W, H), "#fafafa"); x = 0
for c in shots: out.paste(c, (x, 0)); x += c.size[0]
out.save("/tmp/acts_sim.png"); print(len(shots))
