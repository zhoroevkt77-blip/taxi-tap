"""Жаңы функциялардын скриншоттору: python tests/screens2.py → tests/shots/f*.png"""
import json, os, subprocess, sys, time, tempfile
TMP = tempfile.mkdtemp()
os.environ.update(SQLITE_PATH=os.path.join(TMP, "s.db"), DATA_DIR=TMP, DATABASE_URL="", SERVICE_AREA="off",
                  WEB_DEV_LOGIN="1", PORT="8771", ADMIN_PHONES="0700900900", COMMISSION_PCT="10", OSRM_URL="")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import core, flow
from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
SHOTS = os.path.join(HERE, "shots"); os.makedirs(SHOTS, exist_ok=True)
STUB = open(os.path.join(HERE, "leaflet_stub.js")).read()
core.init_db()
DRV = core.phone_uid("0700555001")
core.ensure_user(DRV, "Бакыт"); core.set_user(DRV, phone=DRV[3:])
flow.register_driver(DRV, "Бакыт", "Toyota Camry", "Ак", "01 123 ABC", {"license": "x", "techpass": "x", "car": "x"})
flow.admin_driver(DRV, "approve"); core.add_tx(DRV, 600, "topup")
core.set_driver(DRV, classes="econom,comfort,delivery")
core.set_class_config({"comfort": {"k": 1.3, "on": True}})
core.driver_location(DRV, 42.4950, 78.3990, live_period=3600)

REV = {"address": {"road": "Абдрахманов көчөсү", "house_number": "128"}}


def route(r):
    u = r.request.url
    if u.endswith("leaflet.js"): return r.fulfill(body=STUB, content_type="application/javascript")
    if u.endswith("leaflet.css"): return r.fulfill(body="", content_type="text/css")
    if "nominatim" in u or "photon" in u: return r.fulfill(body=json.dumps(REV), content_type="application/json")
    return r.continue_()


def shot(page, name, wait=1000, full=False):
    page.wait_for_timeout(wait); page.screenshot(path=os.path.join(SHOTS, name + ".png"), full_page=full)


srv = subprocess.Popen([sys.executable, "web.py"], env=os.environ.copy()); time.sleep(1.5)
URL = "http://127.0.0.1:8771"
try:
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
        phone = dict(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True,
                     geolocation={"latitude": 42.4907, "longitude": 78.3936}, permissions=["geolocation"])

        def page_for(kw):
            pg = b.new_context(**kw).new_page(); pg.route("**/*", route)
            pg.on("pageerror", lambda e: print("JS:", e)); pg.on("dialog", lambda d: d.accept())
            return pg

        r = page_for(phone)
        r.goto(URL + "/"); r.fill("#nm", "Айгүл"); r.fill("#ph", "0555 111 222"); r.check("#agree"); r.click("#go")
        r.wait_for_timeout(1500)
        rid_uid = core.phone_uid("0555 111 222")
        core.set_place(rid_uid, "work", 42.47, 78.41, "Иш")
        r.click("[data-k=home]"); r.wait_for_timeout(500); r.click("#ok"); r.wait_for_timeout(1200)
        shot(r, "f1_places", 800)
        r.click("[data-k=work]"); r.wait_for_timeout(1500)
        r.click("[data-c=comfort]"); r.click("#otherOpen"); r.fill("#oNm", "Апам"); r.fill("#oPh", "0777 123 456")
        r.click("#noteOpen"); r.click("#qn button >> nth=1")
        shot(r, "f2_quote", 600, True)
        r.click("[data-c=delivery]"); shot(r, "f3_delivery", 500)
        r.click("[data-c=comfort]"); r.wait_for_timeout(300)
        r.click("#order"); r.wait_for_timeout(500)

        d = page_for(dict(phone, geolocation={"latitude": 42.4950, "longitude": 78.3990}))
        d.goto(URL + "/driver"); d.fill("#nm", "Бакыт"); d.fill("#ph", "0700 555 001"); d.check("#agree"); d.click("#go")
        d.wait_for_timeout(3500)
        shot(d, "f4_offer", 200)
        d.click("#acc"); d.wait_for_timeout(1500); d.click("#step"); d.wait_for_timeout(1000)
        rid = core.active_ride_of(DRV)["id"]
        core.query("UPDATE rides SET arrived_at=? WHERE id=?", (core.now() - 250, rid))
        r.wait_for_timeout(2500)
        shot(r, "f5_rider_wait", 1500)
        r.click("#chat"); r.click("#qk button >> nth=1"); shot(r, "f6_rider_chat", 1200)
        d.wait_for_timeout(2500); shot(d, "f7_driver_ride", 300, True)
        d.click("#chat"); d.click("#qk button >> nth=0"); shot(d, "f8_driver_chat", 1200)
        d.click("#back"); d.wait_for_timeout(500)
        tok = core.share_token(rid)
        t = page_for(phone); t.goto(URL + "/t/" + tok); shot(t, "f9_track", 2000)
        d.click("#step"); d.wait_for_timeout(1500); d.click("#step"); d.wait_for_timeout(1200)
        shot(d, "f10_done", 300)
        d.click("#stars span >> nth=3"); d.click("#ok"); d.wait_for_timeout(1200)
        shot(d, "f11_home", 300, True)
        a = page_for(dict(viewport={"width": 1100, "height": 900}))
        a.goto(URL + "/admin"); a.fill("#ph", "0700 900 900"); a.click("#go"); a.wait_for_timeout(1500)
        a.click("nav button[data-t='tariffs']"); shot(a, "f12_admin_tariffs", 1200, True)
        a.click("nav button[data-t='drivers']"); shot(a, "f13_admin_drivers", 1200)
        b.close()
    print("ride", core.get_ride(rid)["status"], "wait", core.get_ride(rid)["wait_fee"], "p_rating", core.get_user(rid_uid)["p_rating"])
finally:
    srv.terminate()
