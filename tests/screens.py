"""Жүргүнчүнүн бетинин скриншоттору (тармаксыз: Leaflet жана Nominatim жасалма)."""
import json, os, subprocess, sys, time, tempfile
DB = tempfile.mktemp(suffix=".db")
os.environ.update(SQLITE_PATH=DB, DATABASE_URL="", WEB_DEV_LOGIN="1", PORT="8765")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import core, flow, dispatch
from playwright.sync_api import sync_playwright

core.init_db()
for uid, name, pos in (("tg:21", "Бакыт", (42.4935, 78.3990)), ("tg:22", "Асан", (42.4880, 78.3870)),
                       ("tg:23", "Үсөн", (42.4975, 78.4010))):
    core.ensure_user(uid, name); core.set_user(uid, phone="+99670012345" + uid[-1])
    core.add_driver(uid, "Toyota Camry", "Ак", "01 123 ABC"); core.set_driver(uid, status="active", rating=4.9)
    core.driver_location(uid, *pos, live_period=3600)

srv = subprocess.Popen([sys.executable, "web.py"], env=os.environ.copy())
time.sleep(1.5)
HERE = os.path.dirname(os.path.abspath(__file__))
STUB = open(os.path.join(HERE, "leaflet_stub.js")).read()
REV = {"address": {"road": "Абдрахманов көчөсү", "house_number": "128"}}
SRCH = [{"lat": "42.4700", "lon": "78.4100", "display_name": "Борбордук базар, Торекулов көчөсү, Каракол"},
        {"lat": "42.4790", "lon": "78.3950", "display_name": "Базар-Коргон аялдамасы, Каракол"}]
KARAKOL = {"latitude": 42.4907, "longitude": 78.3936}

def route(r):
    u = r.request.url
    if u.endswith("leaflet.js"): return r.fulfill(body=STUB, content_type="application/javascript")
    if u.endswith("leaflet.css"): return r.fulfill(body="", content_type="text/css")
    if "nominatim" in u and "/reverse" in u: return r.fulfill(body=json.dumps(REV), content_type="application/json")
    if "nominatim" in u: return r.fulfill(body=json.dumps(SRCH), content_type="application/json")
    return r.continue_()

def shot(page, name, wait=900):
    page.wait_for_timeout(wait); page.screenshot(path=os.path.join(HERE, "shots", name + ".png"))

with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
    ctx = b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2,
                        geolocation=KARAKOL, permissions=["geolocation"], is_mobile=True, has_touch=True)
    page = ctx.new_page(); page.route("**/*", route)
    page.on("pageerror", lambda e: print("JS:", e))
    page.goto("http://127.0.0.1:8765/"); shot(page, "1_login")
    page.fill("#nm", "Айгүл"); page.fill("#ph", "0555 111 222"); page.click("#go")
    shot(page, "2_home", 2000)
    page.click("#where"); page.fill("#q", "базар"); shot(page, "3_search", 1500)
    page.click(".res[data-i='0']"); shot(page, "4_quote", 1500)
    page.click("#order"); page.wait_for_timeout(500)
    rid = core.active_ride_of("ph:+996555111222")["id"]
    core.query("UPDATE rides SET created_at=? WHERE id=?", (core.now() - 25, rid))
    shot(page, "5_search", 2500)
    for _ in range(20):
        r = core.get_ride(rid)
        if r["offered_to"]: break
        time.sleep(0.5)
    drv = core.get_ride(rid)["offered_to"]
    flow.driver_accept(drv, rid); shot(page, "6_found", 2600)
    core.driver_location(drv, 42.4912, 78.3945, live_period=3600)
    flow.driver_step(drv, rid); shot(page, "7_arrived", 2600)
    flow.driver_step(drv, rid); flow.driver_step(drv, rid); shot(page, "8_done", 2600)
    page.click("#stars span[data-n='5']"); shot(page, "9_rated", 800)
    b.close()
srv.terminate(); os.remove(DB)
print("rating:", core.get_driver(drv) if False else "ok")
