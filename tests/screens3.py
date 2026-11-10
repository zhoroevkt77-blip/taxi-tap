"""Даректер: жүргүнчүнүн «Кайдан/Кайда» жана админдин «Даректер» бөлүмү → tests/shots/a*.png"""
import json, os, subprocess, sys, time, tempfile
TMP = tempfile.mkdtemp()
os.environ.update(SQLITE_PATH=os.path.join(TMP, "s.db"), DATA_DIR=TMP, DATABASE_URL="", SERVICE_AREA="off",
                  WEB_DEV_LOGIN="1", PORT="8773", ADMIN_PHONES="0700900900", OSRM_URL="")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import core, addrbook
from playwright.sync_api import sync_playwright
HERE = os.path.dirname(os.path.abspath(__file__)); SHOTS = os.path.join(HERE, "shots")
STUB = open(os.path.join(HERE, "leaflet_stub.js")).read()
core.init_db()
for n, k, a, b, ar in [("Борбордук базар", "market", 41.0380, 72.7480, "Базар-Коргон"), ("Базар-Коргон №1 мектеп", "school", 41.0390, 72.7450, "Базар-Коргон"),
                      ("Базар-Коргон райондук оорукана", "health", 41.0350, 72.7500, "Базар-Коргон"), ("Дамбылжанов көчөсү", "street", 41.0360, 72.7520, "Базар-Коргон"),
                      ("Юбилейная көчөсү", "street", 41.0420, 72.7460, "Базар-Коргон"), ("Бешик-Жон", "village", 41.0500, 72.7800, ""),
                      ("Автовокзал", "bus", 41.0330, 72.7440, "Базар-Коргон")]:
    addrbook.save(n, k, a, b, area=ar, source="osm")
REV = {"address": {"road": "Айтматов көчөсү", "house_number": "50"}}
def route(r):
    u = r.request.url
    if u.endswith("leaflet.js"): return r.fulfill(body=STUB, content_type="application/javascript")
    if u.endswith("leaflet.css"): return r.fulfill(body="", content_type="text/css")
    if "nominatim" in u: return r.fulfill(body=json.dumps(REV), content_type="application/json")
    return r.continue_()
srv = subprocess.Popen([sys.executable, "web.py"], env=os.environ.copy(), stdout=subprocess.DEVNULL); time.sleep(1.5)
URL = "http://127.0.0.1:8773"
try:
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
        ctx = b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True,
                            geolocation={"latitude": 41.0377, "longitude": 72.7470}, permissions=["geolocation"])
        r = ctx.new_page(); r.route("**/*", route); r.on("pageerror", lambda e: print("JS:", e))
        r.goto(URL + "/"); r.fill("#nm", "Айгүл"); r.fill("#ph", "0555 111 222"); r.check("#agree"); r.click("#go"); r.wait_for_timeout(1800)
        r.screenshot(path=os.path.join(SHOTS, "a1_idle.png"))
        r.click("#where"); r.wait_for_timeout(300); r.type("#qt", "баз", delay=60); r.wait_for_timeout(900)
        r.screenshot(path=os.path.join(SHOTS, "a2_to.png"))
        r.click("#qf"); r.wait_for_timeout(200); r.type("#qf", "мект", delay=60); r.wait_for_timeout(900)
        r.screenshot(path=os.path.join(SHOTS, "a3_from.png"))
        r.click("#list .res >> nth=0"); r.wait_for_timeout(500); r.fill("#qt", ""); r.type("#qt", "дамб", delay=60); r.wait_for_timeout(900)
        r.click("#list .res >> nth=0"); r.wait_for_timeout(1500); r.fill("#hnT", "15")
        r.screenshot(path=os.path.join(SHOTS, "a4_quote.png"))
        a = b.new_context(viewport={"width": 1100, "height": 1000}).new_page(); a.route("**/*", route); a.on("pageerror", lambda e: print("JS:", e))
        a.goto(URL + "/admin"); a.fill("#ph", "0700 900 900"); a.click("#go"); a.wait_for_timeout(1500)
        a.click("nav button[data-t='addr']"); a.wait_for_timeout(1000); a.click("#dNew"); a.wait_for_timeout(800)
        a.fill("#dN", "Нурбек той-кана"); a.select_option("#dK", "food"); a.fill("#dAl", "нурбек, той кана")
        a.click("#dmap", position={"x": 300, "y": 150}); a.wait_for_timeout(400)
        a.screenshot(path=os.path.join(SHOTS, "a5_admin.png"), full_page=True)
        a.click("#dSave"); a.wait_for_timeout(1000)
        print("saved:", [x["name"] for x in addrbook.search("той")])
        b.close()
finally:
    srv.terminate()
