"""Жүргүнчүнүн жолу: катталуудан баалоого чейин. python tests/sim_rider.py → tests/shots/rider/*.png"""
import json, os, subprocess, sys, time, tempfile
TMP = tempfile.mkdtemp()
os.environ.update(SQLITE_PATH=os.path.join(TMP, "s.db"), DATA_DIR=TMP, DATABASE_URL="", SERVICE_AREA="off",
                  WEB_DEV_LOGIN="1", PORT="8773", ADMIN_PHONES="0700900900", COMMISSION_PCT="10", OSRM_URL="")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import core, flow
from playwright.sync_api import sync_playwright
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "shots", "rider"); os.makedirs(OUT, exist_ok=True)
for f in os.listdir(OUT): os.remove(os.path.join(OUT, f))
STUB = open(os.path.join(HERE, "leaflet_stub.js")).read()
A = (41.0377, 72.7470)              # жүргүнчү
B = (41.0300, 72.7560)              # бара турган жер
DSTART = (41.0430, 72.7400)         # айдоочу
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


N = [0]
def frame(rp, dp, step, title, sub, wait=900):
    rp.wait_for_timeout(wait)
    a, b = os.path.join(TMP, "r.png"), os.path.join(TMP, "d.png")
    rp.screenshot(path=a); dp.screenshot(path=b)
    W = 400; ra, db = Image.open(a).resize((W, 866)), Image.open(b).resize((W, 866))
    c = Image.new("RGB", (W * 2 + 60, 866 + 190), "#fafafa"); d = ImageDraw.Draw(c)
    d.rounded_rectangle([20, 18, 20 + 56, 18 + 56], 16, fill="#ffc61a")
    import re as _re
    title = _re.sub(r"[^\w\s«»—,.!?:/()+-]", "", title).strip()
    d.text((48, 46), str(N[0] + 1), font=F_B, fill="#16161a", anchor="mm")
    d.text((92, 16), title, font=F_B, fill="#1b1b20")
    d.text((92, 62), sub, font=F_M, fill="#5f5f6a")
    for i, (im, lab) in enumerate([(ra, "🧳 ЖҮРГҮНЧҮ"), (db, "🚗 АЙДООЧУ")]):
        x = 20 + i * (W + 20)
        d.text((x + 6, 112), lab.split(" ", 1)[1], font=F_S, fill="#9a7400")
        m = Image.new("L", im.size, 0); ImageDraw.Draw(m).rounded_rectangle([0, 0, W, 866], 28, fill=255)
        c.paste(im, (x, 150), m)
    N[0] += 1
    c.save(os.path.join(OUT, "%02d.png" % N[0]))
    print(N[0], title)


def move(ctx, a, b, k):
    p = (a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k)
    ctx.set_geolocation({"latitude": p[0], "longitude": p[1]})
    core.driver_location(DRV, p[0], p[1], live_period=3600)
    return p


srv = subprocess.Popen([sys.executable, "web.py"], env=os.environ.copy(), stdout=subprocess.DEVNULL); time.sleep(1.5)
URL = "http://127.0.0.1:8773"
try:
    with sync_playwright() as p:
        br = p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
        ph = dict(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True,
                  permissions=["geolocation"])
        rc = br.new_context(**ph, geolocation={"latitude": A[0], "longitude": A[1]})
        dc = br.new_context(**ph, geolocation={"latitude": DSTART[0], "longitude": DSTART[1]})
        r, dv = rc.new_page(), dc.new_page()
        for pg in (r, dv):
            pg.route("**/*", route); pg.on("pageerror", lambda e: print("JS:", e)); pg.on("dialog", lambda x: x.accept())
        # кирүү
        dv.goto(URL + "/driver"); dv.fill("#nm", "Бакыт"); dv.fill("#ph", "0700 555 001"); dv.check("#agree"); dv.click("#go")
        dv.wait_for_timeout(1500); core.driver_location(DRV, *DSTART, live_period=3600)
        dv.click("#on"); dv.wait_for_timeout(800)
        import addrbook
        addrbook.save("Автовокзал (Автобекет)", "bus", B[0], B[1], area="Текебаев көчөсү 2")
        addrbook.save("Борбордук базар", "market", 41.0412, 72.7501, area="Ленин көчөсү")
        addrbook.save("Райондук оорукана", "health", 41.0350, 72.7390)
        r.add_init_script("""(() => { const pos = () => ({coords:{latitude:%f, longitude:%f, accuracy:12}, timestamp:Date.now()});
          navigator.geolocation.getCurrentPosition = (ok) => setTimeout(() => ok(pos()), 200);
          navigator.geolocation.watchPosition = (ok) => { setTimeout(() => ok(pos()), 300); return 1; };
          navigator.geolocation.clearWatch = () => {}; })();""" % A)
        r.goto(URL + "/"); r.wait_for_timeout(1200)
        frame(r, dv, 1, "Жүргүнчү сайтты биринчи жолу ачты", "Катталуу: аты жана телефон номери · айдоочу линияда күтүп турат", 600)
        r.type("#nm", "Айгүл", delay=90); r.type("#ph", "0555 111 222", delay=60); r.check("#agree")
        frame(r, dv, 1, "Аты, номери жазылды", "Колдонуу шарттарына макул болуп, «Кирүү» басат", 500)
        r.click("#go"); r.wait_for_timeout(1800)
        frame(r, dv, 1, "Telegram аркылуу ырасталды — кирди", "Номер Telegram боту аркылуу бир басуу менен ырасталат", 600)
        r.click("#hSearch")
        frame(r, dv, 2, "1-кадам: «Сизди кайдан алып кетсин?»", "Үч чоң баскыч: Азыр турган жеримден (GPS) · Картадан · Жазып", 900)
        rc.set_geolocation({"latitude": A[0], "longitude": A[1]}); r.evaluate("S.gps.state='wait'; locate(true)")
        r.wait_for_function("S.gps.state === 'ok'", timeout=15000); r.evaluate("viewStepA()"); r.wait_for_timeout(500)
        r.click("#aHere")
        frame(r, dv, 2, "2-кадам: «Кайда барасыз?»", "Үй, иш, акыркы, көп барылчу жерлер — же жазып/картадан", 900)
        r.click("#bType"); r.wait_for_timeout(400)
        r.type("#qt", "авто", delay=120)
        frame(r, dv, 3, "«авто» деп жазды", "Даректер жазып жатканда эле чыгат, жанында жол убактысы", 1200)
        r.click("#list .res >> nth=0")
        frame(r, dv, 4, "Б точка тандалды — баа чыкты", "Эми гана карта: маршрут, класстар, баа · «✓ Б точка тандалды»", 1500)
        r.click("#order")
        frame(r, dv, 3, "Заказ жакынкы айдоочуга кетти", "Айдоочуга 15 секунддук сунуш келди", 3500)
        kb = dv.locator("#knob").bounding_box(); tr = dv.locator("#acc").bounding_box()
        dv.mouse.move(kb["x"] + 20, kb["y"] + 20); dv.mouse.down()
        for i in range(1, 11): dv.mouse.move(kb["x"] + 20 + (tr["width"] - 60) * i / 10, kb["y"] + 20)
        dv.mouse.up()
        frame(r, dv, 4, "Айдоочу заказды кабыл алды", "Жүргүнчүгө айдоочу, унаа жана номер көрүндү", 2500)
        for k in (0.35, 0.7):
            move(dc, DSTART, A, k)
        frame(r, dv, 5, "Айдоочу жүргүнчүгө келе жатат", "Картада унаа жылып, келүү убактысы азаят", 3000)
        dv.click("#navGo")
        frame(r, dv, "5б", "Айдоочу навигаторду тандайт", "Яндекс Навигатор / 2ГИС / Google — бир жолу тандалат, эстеп калат", 800)
        dv.click("#ovlX")
        move(dc, DSTART, A, 1.0)
        dv.click("#step")
        rid = core.active_ride_of(DRV)["id"]
        frame(r, dv, 6, "Айдоочу «Келдим» басты", "Акысыз күтүү (3 мүн) башталды — эки тарапта тең таймер", 2500)
        r.click("#chat"); r.click("#qk button >> nth=0")
        dv.wait_for_timeout(2500)
        frame(r, dv, 7, "Жүргүнчү чатка жазды", "Номер алмашпай эле байланыш · айдоочуга кабар келди", 1200)
        r.click("#back"); dv.wait_for_timeout(500)
        dv.click("#step")
        frame(r, dv, 8, "Сапар башталды", "Айдоочу «Сапарды баштоо» басты — Б чекитке карай", 2500)
        for k in (0.4, 0.8):
            move(dc, A, B, k)
        frame(r, dv, 9, "Жолдо", "Жүргүнчү унааны картада көрүп, сапарды бөлүшө алат", 3000)
        move(dc, A, B, 1.0)
        dv.click("#step")
        frame(r, dv, 10, "Б чекитке жетти — сапар бүттү", "«Келдиңиз» · баасы жана төлөм ыкмасы көрүнөт", 2500)
        r.evaluate("document.querySelector('#dq') && document.querySelector('#dq').scrollIntoView({block:'center'})")
        frame(r, dv, 10, "Төлөм: накталай айдоочуга", "Жүргүнчү айдоочуга акчасын берет · айдоочу «Акча алдым» деп бүтүрдү", 900)
        r.evaluate("document.querySelector('#stars').scrollIntoView({block:'center'})")
        r.click("#stars span >> nth=4"); dv.click("#stars span >> nth=4")
        r.click("#tags [data-k] >> nth=2"); r.click("#tags [data-k] >> nth=4"); r.click("#carq [data-c='1']")
        frame(r, dv, 11, "Айдоочуну баалады: ★★★★★", "Мактоолор + унаанын абалы · пикир жашыруун калат", 800)
        dv.click("#ok"); dv.wait_for_timeout(1200)
        frame(r, dv, 12, "Айдоочу кайра линияда", "Бүгүнкү сапар, киреше, баланс жана ⚡ активдүүлүк жаңыланды", 800)
        r.click("#again"); r.wait_for_timeout(1500)
        frame(r, dv, 13, "«Даяр» — жүргүнчү башкы бетке кайтты", "Автовокзал «акыркы жерлерге» кошулду — кийинки жолу бир басуу", 800)
        br.close()
    ride = core.get_ride(rid); d = core.get_driver(DRV)
    print("RIDE", ride["status"], ride["price"], "balance", d["balance"])
finally:
    srv.terminate()
