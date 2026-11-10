"""Толук сапардын симуляциясы: жүргүнчү | айдоочу экрандары кадам-кадам → tests/sim/*.png + sim.mp4"""
import json, os, subprocess, sys, time, tempfile, shutil
TMP = tempfile.mkdtemp()
os.environ.update(SQLITE_PATH=os.path.join(TMP, "s.db"), DATA_DIR=TMP, DATABASE_URL="", SERVICE_AREA="off",
                  WEB_DEV_LOGIN="1", PORT="8772", ADMIN_PHONES="0700900900", COMMISSION_PCT="10", OSRM_URL="")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import core, flow
from playwright.sync_api import sync_playwright
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "sim"); shutil.rmtree(OUT, ignore_errors=True); os.makedirs(OUT)
STUB = open(os.path.join(HERE, "leaflet_stub.js")).read()
A = (42.4907, 78.3936); B = (42.4760, 78.4080); D0 = (42.4990, 78.4030)
core.init_db()
DRV = core.phone_uid("0700555001")
core.ensure_user(DRV, "Бакыт"); core.set_user(DRV, phone=DRV[3:])
flow.register_driver(DRV, "Бакыт", "Hyundai Solaris", "Ак", "04 338 APG", {"license": "x", "techpass": "x", "car": "x"})
flow.admin_driver(DRV, "approve"); core.add_tx(DRV, 1000, "topup")
core.driver_location(DRV, *D0, live_period=3600)
REV = {"address": {"road": "Ленин көчөсү", "house_number": "12"}}
FONT = ImageFont.truetype("/usr/share/fonts/opentype/inter/Inter-Black.otf", 44)
FONT2 = ImageFont.truetype("/usr/share/fonts/opentype/inter/Inter-Medium.otf", 30)


def route(r):
    u = r.request.url
    if u.endswith("leaflet.js"): return r.fulfill(body=STUB, content_type="application/javascript")
    if u.endswith("leaflet.css"): return r.fulfill(body="", content_type="text/css")
    if "nominatim" in u or "photon" in u: return r.fulfill(body=json.dumps(REV), content_type="application/json")
    return r.continue_()


N = [0]


def frame(rp, dp, title, sub=""):
    rp.wait_for_timeout(300); dp.wait_for_timeout(300)
    a, b = os.path.join(TMP, "a.png"), os.path.join(TMP, "b.png")
    rp.screenshot(path=a); dp.screenshot(path=b)
    ia, ib = Image.open(a).convert("RGB"), Image.open(b).convert("RGB")
    W, H, top, gap = ia.width * 2 + 60, ia.height + 230, 200, 60
    c = Image.new("RGB", (W, H), (250, 250, 250)); d = ImageDraw.Draw(c)
    N[0] += 1
    d.rounded_rectangle([30, 28, 120, 118], radius=24, fill=(255, 198, 26))
    d.text((75, 73), str(N[0]), font=FONT, fill=(22, 22, 26), anchor="mm")
    d.text((145, 40), title, font=FONT, fill=(22, 22, 26))
    d.text((145, 100), sub, font=FONT2, fill=(110, 110, 120))
    d.text((ia.width // 2 + 20, top - 34), "🧳 ЖҮРГҮНЧҮ", font=FONT2, fill=(154, 116, 0), anchor="mm")
    d.text((ia.width + gap + ia.width // 2 - 10, top - 34), "🚗 АЙДООЧУ", font=FONT2, fill=(154, 116, 0), anchor="mm")
    c.paste(ia, (20, top)); c.paste(ib, (ia.width + gap - 20, top))
    c.save(os.path.join(OUT, "%02d.png" % N[0]))
    print(N[0], title)


def move(frm, to, steps, rp, dp, every=None):
    for i in range(1, steps + 1):
        t = i / steps
        core.driver_location(DRV, frm[0] + (to[0] - frm[0]) * t, frm[1] + (to[1] - frm[1]) * t, live_period=3600)
        rp.wait_for_timeout(1300)
        if every and i in every:
            every[i]()


srv = subprocess.Popen([sys.executable, "web.py"], env=os.environ.copy(), stdout=subprocess.DEVNULL); time.sleep(1.5)
URL = "http://127.0.0.1:8772"
try:
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
        phone = dict(viewport={"width": 390, "height": 800}, device_scale_factor=2, is_mobile=True, has_touch=True,
                     permissions=["geolocation"])

        def page_for(pos):
            pg = b.new_context(**phone, geolocation={"latitude": pos[0], "longitude": pos[1]}).new_page()
            pg.route("**/*", route); pg.on("dialog", lambda x: x.accept())
            pg.on("pageerror", lambda e: print("JS:", e))
            return pg

        d = page_for(D0)
        d.goto(URL + "/driver"); d.fill("#nm", "Бакыт"); d.fill("#ph", "0700 555 001"); d.check("#agree"); d.click("#go")
        d.wait_for_timeout(1500)
        r = page_for(A)
        r.goto(URL + "/"); r.fill("#nm", "Айгүл"); r.fill("#ph", "0555 111 222"); r.check("#agree"); r.click("#go")
        r.wait_for_timeout(1800)
        frame(r, d, "Баштоо", "Жүргүнчү сайтты ачты · айдоочу линияда, заказ күтүп турат")
        uid = core.phone_uid("0555 111 222")
        core.set_place(uid, "work", B[0], B[1], "Иш")
        r.goto(URL + "/"); r.wait_for_timeout(1800)
        r.click("[data-k=work]"); r.wait_for_timeout(1500)
        frame(r, d, "Баа көрүнөт", "Жүргүнчү «Иш» дарегин тандады — баа алдын ала белгилүү")
        r.click("#order"); r.wait_for_timeout(600)
        d.wait_for_timeout(2600)
        frame(r, d, "Заказ айдоочуга келди", "Эң жакын айдоочуга 15 секундга сунуш · үн менен кабар")
        d.click("#acc"); r.wait_for_timeout(2600)
        frame(r, d, "Айдоочу кабыл алды", "Жүргүнчү унааны, номерин жана канча мүнөттө келерин көрөт")
        mid = ((D0[0] + A[0]) / 2, (D0[1] + A[1]) / 2)
        move(D0, mid, 3, r, d); r.wait_for_timeout(1500)
        frame(r, d, "Айдоочу жолдо", "Унаа картада жылып баратат, ETA жаңыланат")
        r.click("#chat"); r.click("#qk button >> nth=3"); r.wait_for_timeout(500)
        d.wait_for_timeout(2500)
        frame(r, d, "Чат", "Жүргүнчү жазды — айдоочуда билдирүү белгиси чыкты")
        r.click("#back")
        move(mid, A, 3, r, d)
        d.click("#step"); r.wait_for_timeout(2600)
        frame(r, d, "Айдоочу келди", "«Келдим» — 3 мүнөт акысыз күтүү башталды")
        d.click("#step"); r.wait_for_timeout(2600)
        frame(r, d, "Сапар башталды", "Жүргүнчү отурду · айдоочу навигатор менен Б чекитке")
        m2 = ((A[0] + B[0]) / 2, (A[1] + B[1]) / 2)
        move(A, m2, 3, r, d); r.wait_for_timeout(1500)
        frame(r, d, "Жолдо", "Жүргүнчүнүн жакындары «Бөлүшүү» шилтемеси аркылуу көрө алат")
        move(m2, B, 3, r, d)
        d.click("#step"); r.wait_for_timeout(2800)
        frame(r, d, "Б чекитине жетти", "Жүргүнчү акчаны берет · сайттан 10% комиссия кармалды")
        r.click("#stars span >> nth=4"); d.click("#stars span >> nth=4"); r.wait_for_timeout(800)
        d.click("#ok"); d.wait_for_timeout(1500)
        frame(r, d, "Баалоо жана кийинки заказ", "Экөө бири-бирин баалады · айдоочу кайра линияда")
        b.close()
    rd = core.query("SELECT * FROM rides ORDER BY id DESC LIMIT 1", (), "one")
    print("RIDE", rd["status"], rd["price"], "balance", core.get_driver(DRV)["balance"])
finally:
    srv.terminate()
