"""Айдоочунун бетинин скриншоттору (тармаксыз)."""
import json, os, subprocess, sys, time, tempfile
DB = tempfile.mktemp(suffix=".db")
os.environ.update(SQLITE_PATH=DB, DATABASE_URL="", WEB_DEV_LOGIN="1", PORT="8766",
                  BOT_USERNAME="TaksiTapBot", COMMISSION_PCT="10")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import core
from playwright.sync_api import sync_playwright

core.init_db()
D = "tg:31"
core.ensure_user(D, "Бакыт"); core.set_user(D, phone="+996700123451")
core.add_driver(D, "Toyota Camry", "Ак", "01 123 ABC")
core.set_driver(D, status="active", rating=4.92, rides_done=318)
core.add_tx(D, 500, "topup")
P = "ph:+996555111222"
core.ensure_user(P, "Айгүл"); core.set_user(P, phone="+996555111222")

srv = subprocess.Popen([sys.executable, "web.py"], env=os.environ.copy())
time.sleep(1.5)
HERE = os.path.dirname(os.path.abspath(__file__))
STUB = open(os.path.join(HERE, "leaflet_stub.js")).read()
POS = {"latitude": 42.4935, "longitude": 78.3990}

def route(r):
    u = r.request.url
    if u.endswith("leaflet.js"): return r.fulfill(body=STUB, content_type="application/javascript")
    if u.endswith("leaflet.css"): return r.fulfill(body="", content_type="text/css")
    return r.continue_()

def shot(page, name, wait=900):
    page.wait_for_timeout(wait); page.screenshot(path=os.path.join(HERE, "shots", name + ".png"))

with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox", "--autoplay-policy=no-user-gesture-required"])
    ctx = b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2,
                        geolocation=POS, permissions=["geolocation"], is_mobile=True, has_touch=True)
    page = ctx.new_page(); page.route("**/*", route)
    page.on("pageerror", lambda e: print("JS:", e))
    page.on("dialog", lambda d: d.accept())
    page.goto("http://127.0.0.1:8766/driver"); shot(page, "d1_login")
    page.fill("#ph", "0700 123 451"); page.click("#go"); shot(page, "d2_offline", 2000)
    page.click("#on"); shot(page, "d3_online", 2000)
    # жүргүнчү заказ берет
    q = core.quote(42.4907, 78.3936, 42.4700, 78.4100)
    rid = core.create_ride(P, q, 42.4907, 78.3936, 42.4700, 78.4100)
    for _ in range(20):
        if core.get_ride(rid)["offered_to"]: break
        time.sleep(0.5)
    shot(page, "d4_offer", 4500)
    page.click("#acc"); shot(page, "d5_toPassenger", 1800)
    page.click("#step"); shot(page, "d6_arrived", 1800)
    page.click("#step"); shot(page, "d7_trip", 1800)
    page.click("#step"); shot(page, "d8_done", 1500)
    page.click("#ok"); page.wait_for_timeout(800)
    page.click("#off"); page.wait_for_timeout(1200)
    page.click("#hist"); shot(page, "d9_history", 1500)
    b.close()
srv.terminate()
d = core.get_driver(D)
print("balance:", d["balance"], "rides_done:", d["rides_done"], "ride:", core.get_ride(rid)["status"])
os.remove(DB)
