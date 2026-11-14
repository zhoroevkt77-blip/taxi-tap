"""Кийинки заказ (цепочка): айдоочу сапарда, жаңы заказ алат. python tests/sim_chain.py → tests/shots/chain/*.png"""
import json, os, subprocess, sys, time, tempfile
TMP = tempfile.mkdtemp()
os.environ.update(SQLITE_PATH=os.path.join(TMP, "s.db"), DATA_DIR=TMP, DATABASE_URL="", SERVICE_AREA="off",
                  WEB_DEV_LOGIN="1", PORT="8772", ADMIN_PHONES="0700900900", COMMISSION_PCT="10", OSRM_URL="")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import core, flow
from playwright.sync_api import sync_playwright
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "shots", "chain"); os.makedirs(OUT, exist_ok=True)
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
    for i, (im, lab) in enumerate([(ra, "🧳 2-ЖҮРГҮНЧҮ (жаңы заказ)"), (db, "🚗 АЙДООЧУ")]):
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
URL = "http://127.0.0.1:8772"
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
        dv.goto(URL + "/driver"); dv.fill("#nm", "Бакыт"); dv.fill("#ph", "0700 555 001"); dv.check("#agree"); dv.click("#go")
        dv.wait_for_timeout(1500); core.driver_location(DRV, *DSTART, live_period=3600)
        dv.click("#on"); dv.wait_for_timeout(800)
        import addrbook
        addrbook.save("Автовокзал (Автобекет)", "bus", B[0], B[1], area="Текебаев көчөсү 2")
        # 1-жүргүнчү (фондо): заказ → айдоочу алды → сапар башталды
        P1 = core.phone_uid("0555 333 001"); core.ensure_user(P1, "Нурлан"); core.set_user(P1, phone=P1[3:])
        q = core.quote(A1[0], A1[1], B1[0], B1[1]); rid1 = core.create_ride(P1, q, A1[0], A1[1], B1[0], B1[1])
        for _ in range(20):
            if core.get_ride(rid1)["offered_to"] == DRV: break
            time.sleep(0.5)
        flow.driver_accept(DRV, rid1); flow.driver_step(DRV, rid1); flow.driver_step(DRV, rid1)
        r.add_init_script("""(() => { const pos = () => ({coords:{latitude:%f, longitude:%f, accuracy:12}, timestamp:Date.now()});
          navigator.geolocation.getCurrentPosition = (ok) => setTimeout(() => ok(pos()), 200);
          navigator.geolocation.watchPosition = (ok) => { setTimeout(() => ok(pos()), 300); return 1; };
          navigator.geolocation.clearWatch = () => {}; })();""" % A)
        r.goto(URL + "/"); r.fill("#nm", "Айгүл"); r.fill("#ph", "0555 111 222"); r.check("#agree"); r.click("#go"); r.wait_for_timeout(1800)
        move(dc, A1, B1, 0.3)
        frame(r, dv, 1, "Айдоочу 1-жүргүнчүнү алып баратат", "Сапарда · аягына чейин дагы алыс — жаңы заказ берилбейт", 2500)
        move(dc, A1, B1, 0.75)
        frame(r, dv, 2, "Сапардын аягына 2 км калды", "Эми айдоочу «кийинки заказ» алууга даяр", 2000)
        r.click("#hSearch"); r.wait_for_timeout(600)
        rc.set_geolocation({"latitude": A[0], "longitude": A[1]}); r.evaluate("S.gps.state='wait'; locate(true)")
        r.wait_for_function("S.gps.state === 'ok'", timeout=15000); r.evaluate("viewStepA()"); r.wait_for_timeout(500)
        r.click("#aHere"); r.click("#bType"); r.wait_for_timeout(400); r.type("#qt", "авто", delay=80)
        r.wait_for_timeout(1000); r.click("#list .res >> nth=0"); r.wait_for_timeout(1500)
        frame(r, dv, 3, "2-жүргүнчү такси чакырат", "Ал 1-жүргүнчү түшө турган жерден 200 м алыстыкта", 600)
        r.click("#order")
        frame(r, dv, 4, "Айдоочуга «Кийинки заказ» келди", "«Азыркы сапардан кийин» · бош айдоочу жок болгондуктан ага", 3500)
        kb = dv.locator("#knob").bounding_box(); tr = dv.locator("#acc").bounding_box()
        dv.mouse.move(kb["x"] + 20, kb["y"] + 20); dv.mouse.down()
        for i in range(1, 11): dv.mouse.move(kb["x"] + 20 + (tr["width"] - 60) * i / 10, kb["y"] + 20)
        dv.mouse.up()
        frame(r, dv, 5, "Айдоочу кабыл алды", "2-жүргүнчүгө: «Айдоочу азыркы сапарын бүтүрүп келет»", 2800)
        move(dc, A1, B1, 1.0)
        dv.click("#step")
        frame(r, dv, 6, "1-сапар бүттү", "Айдоочу 1-жүргүнчүдөн акча алат · 2-заказ кезекте", 2500)
        if dv.locator("#ok").count():
            dv.click("#ok"); dv.wait_for_timeout(1200)
        frame(r, dv, 7, "Дароо 2-жүргүнчүгө жөнөйт", "Бош жүрбөйт — 200 м гана · жүргүнчүгө убакыт көрүнөт", 2500)
        move(dc, B1, A, 1.0)
        dv.click("#step")
        frame(r, dv, 8, "Айдоочу «Келдим» басты", "2-жүргүнчүнүн сапары кадимкидей уланат", 2500)
        br.close()
    print("R1", core.get_ride(rid1)["status"], "D", dict(core.get_driver(DRV))["busy_ride"])
finally:
    srv.terminate()
