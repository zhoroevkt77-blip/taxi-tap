import os, subprocess, sys, time, tempfile
TMP = tempfile.mkdtemp()
os.environ.update(SQLITE_PATH=os.path.join(TMP, "s.db"), DATA_DIR=TMP, DATABASE_URL="", SERVICE_AREA="off",
                  WEB_DEV_LOGIN="1", PORT="8775", ADMIN_PHONES="0700900900", OSRM_URL="", COMMISSION_PCT="10")
sys.path.insert(0, "/home/claude/taxi-tap")
import core, parks
from playwright.sync_api import sync_playwright
from PIL import Image, ImageDraw, ImageFont
STUB = open("/home/claude/taxi-tap/tests/leaflet_stub.js").read() + r"""
(function(){const _m=L.map,_k=L.marker,_g=L.layerGroup;
L.map=(id,o)=>{if(typeof id!=="string"){id.id=id.id||"pmap";id=id.id}const m=_m(id);m.invalidateSize=()=>m;const fb=m.fitBounds.bind(m);
 m.fitBounds=p=>{const la=p.map(x=>x[0]),lo=p.map(x=>x[1]);fb({a:[Math.max(...la),Math.max(...lo)],b:[Math.min(...la),Math.min(...lo)]});m.z=13;m.draw();};return m};
L.marker=(p,o)=>{const k=_k(p,o);k.bindPopup=function(h){this._pop=h;return this};k.openPopup=function(){const d=document.createElement("div");
 d.style.cssText="position:absolute;transform:translate(-50%,-100%);background:#fff;border-radius:12px;padding:9px 12px;font-size:13px;line-height:1.45;box-shadow:0 3px 14px rgba(0,0,0,.25);white-space:nowrap;z-index:5";
 d.innerHTML=this._pop;const [x,y]=this.m.xy(this.p);d.style.left=x+"px";d.style.top=(y-12)+"px";this.m.ov.appendChild(d);return this};return k};
L.layerGroup=()=>{const g=_g();g.eachLayer=f=>g.items.forEach(f);return g};})();
"""
core.init_db()
pid = parks.save("Нур-Такси", "0700 777 001", share=30, ref_bonus=20)
def mkdrv(ph, name, model, color, plate, lat, lon, online, seen=0):
    uid = core.phone_uid(ph); core.ensure_user(uid, name); core.set_user(uid, name=name, phone=uid[3:])
    core.query("INSERT INTO drivers (uid, status, car_model, car_color, car_plate, balance, rating, online, lat, lon, loc_at, live_until) VALUES (?, 'active', ?, ?, ?, 1000, 4.9, ?, ?, ?, ?, ?)",
               (uid, model, color, plate, 1 if online else 0, lat, lon, core.now() - seen, core.now() + 3600 if online else 0))
    parks.attach_driver(ph, pid); return uid
D = [mkdrv("0700 000 201", "Бакыт", "Toyota Camry", "Ак", "04 101 ABC", 41.040, 72.745, True),
     mkdrv("0700 000 202", "Нурлан", "Honda Fit", "Кара", "04 202 KGZ", 41.032, 72.758, True),
     mkdrv("0700 000 203", "Азамат", "Daewoo Nexia", "Боз", "04 303 BKR", 41.045, 72.760, True),
     mkdrv("0700 000 204", "Эрлан", "Toyota Prius", "Ак", "04 404 ABD", 41.028, 72.738, False, 7200),
     mkdrv("0700 000 205", "Талант", "Lexus RX", "Кара", "04 505 TAL", 41.051, 72.740, False, 4 * 86400)]
t0 = core.now()
for i in range(22):
    d = D[[0, 0, 0, 1, 1, 2, 0, 1, 3, 0, 2, 1, 0, 3, 0, 1, 2, 0, 1, 0, 2, 1][i]]
    core.query("INSERT INTO rides (passenger, driver, status, price, completed_at, p_addr, d_addr, created_at) VALUES ('tg:1', ?, 'completed', ?, ?, 'Базар-Коргон, борбор', ?, ?)",
               (d, [80, 120, 150, 95, 210, 70][i % 6], t0 - (i % 7) * 86400 - 1800 * (i % 3) - 600, ["Казарман", "Манас ш.", "Жалал-Абад", "Сузак"][i % 4], t0 - 86400 * 8))
    core.query("INSERT INTO balance_tx (driver, amount, kind, status, at) VALUES (?, ?, 'commission', 'done', ?)", (d, -12, t0 - (i % 7) * 86400 - 600))
# азыр заказдагы
u = core.phone_uid("0555 499 000"); core.ensure_user(u, "Ж")
q = core.quote(41.0377, 72.7470, 41.10, 72.80)
rid = core.create_ride(u, q, 41.0377, 72.7470, 41.10, 72.80, p_addr="Базар-Коргон", d_addr="Казарман")
core.offer(rid, D[2]); core.accept(rid, D[2])
for d, a, m in ((D[0], 9, 1), (D[1], 6, 3), (D[2], 4, 1), (D[3], 2, 4)):
    for _ in range(a): core.log_offer({"id": 1, "city": "x"}, d, "accept")
    for _ in range(m): core.log_offer({"id": 1, "city": "x"}, d, "miss")
day = time.strftime("%Y-%m-%d", time.gmtime(core.now() + core.TZ))
for d, h in ((D[0], 7.5), (D[1], 5.2), (D[2], 3.1), (D[3], 1.4)):
    core.query("INSERT INTO driver_online (uid, day, sec) VALUES (?, ?, ?)", (d, day, h * 3600))
def route(r):
    u = r.request.url
    if u.endswith("leaflet.js"): return r.fulfill(body=STUB, content_type="application/javascript")
    if u.endswith("leaflet.css"): return r.fulfill(body="", content_type="text/css")
    if "tile.openstreetmap" in u: return r.abort()
    return r.continue_()
srv = subprocess.Popen([sys.executable, "web.py"], cwd="/home/claude/taxi-tap", env=os.environ.copy(), stdout=subprocess.DEVNULL); time.sleep(1.5)
URL = "http://127.0.0.1:8775"; shots = []
F = ImageFont.truetype("/usr/share/fonts/opentype/inter/Inter-Black.otf", 21); FM = ImageFont.truetype("/usr/share/fonts/opentype/inter/Inter-Medium.otf", 18)
def frame(pg, t, s):
    path = "/tmp/ps_%02d.png" % (len(shots) + 1); pg.screenshot(path=path)
    im = Image.open(path).convert("RGB"); w, h = im.size
    im = im.resize((390, int(h * 390 / w)))
    c = Image.new("RGB", (430, im.size[1] + 110), "#fafafa"); d = ImageDraw.Draw(c)
    d.rounded_rectangle([20, 14, 64, 58], 12, fill="#ffc61a"); d.text((42, 36), str(len(shots) + 1), font=F, fill="#16161a", anchor="mm")
    d.text((76, 12), t, font=F, fill="#1b1b20"); d.text((76, 50), s, font=FM, fill="#5f5f6a")
    c.paste(im, (20, 96)); shots.append(c)
try:
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
        x = b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2); k = x.new_page(); k.route("**/*", route)
        k.on("pageerror", lambda e: print("JS:", e))
        k.goto(URL + "/"); k.fill("#nm", "Нур"); k.fill("#ph", "0700 777 001"); k.check("#agree"); k.click("#go"); k.wait_for_timeout(1200)
        k.goto(URL + "/park"); k.wait_for_timeout(2200)
        k.evaluate("document.querySelector('#drvSlot').scrollIntoView()"); k.wait_for_timeout(400)
        frame(k, "📊 Статистика · Жума", "Сапар, тапкан, линияда, алган % · 🏆 💤")
        k.click("[data-dp='today']"); k.wait_for_timeout(700); k.click("[data-ds='online']"); k.wait_for_timeout(300)
        k.evaluate("document.querySelector('#drvSlot').scrollIntoView()"); k.wait_for_timeout(300)
        frame(k, "Бүгүн · «линияда» боюнча иреттелди", "Ким канча саат иштеди")
        k.evaluate("document.querySelector('#drvSlot').scrollIntoView({block:'end'})"); k.wait_for_timeout(300)
        frame(k, "Excel'ге жүктөө", "Бир баскыч — бардык айдоочулар таблицада")
        k.click("[data-dp='week']"); k.wait_for_timeout(700)
        k.click("[data-du='%s']" % D[0]); k.wait_for_timeout(800)
        frame(k, "Айдоочуну басканда", "7 күндүк график, мактоолор, акыркы сапарлар, 📞")
        k.click("[data-close]"); k.wait_for_timeout(200)
        k.click("[data-dt='map']"); k.wait_for_timeout(1200)
        k.evaluate("document.querySelector('#drvSlot').scrollIntoView()"); k.wait_for_timeout(300)
        frame(k, "🗺 Карта", "🟢 бош · 🟡 заказда · ⚪ эс алууда")
        k.click("[data-mf='busy']"); k.wait_for_timeout(400)
        k.click("[data-mu='%s']" % D[2]); k.wait_for_timeout(800)
        frame(k, "🟡 Заказдагыны басканда", "Кайда бара жатат, бүгүн канча, 📞 чалуу")
        k.click("[data-mf='busy']"); k.wait_for_timeout(200); k.click("[data-mf='off']"); k.wait_for_timeout(500)
        k.evaluate("document.querySelector('#mList').scrollIntoView({block:'end'})"); k.wait_for_timeout(300)
        frame(k, "⚪ Эс алуудагылар", "Акыркы жери болжолдуу + качан көрүнгөнү")
        print(open("/dev/null").read() or "csv:", x.request.get(URL + "/park/stats.csv?period=week").text()[:300])
        b.close()
finally:
    srv.terminate()
for i, c in enumerate(shots, 1): c.save("/tmp/psf_%02d.png" % i)
print(len(shots))
