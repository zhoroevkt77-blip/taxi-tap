import os, subprocess, sys, time, tempfile
TMP = tempfile.mkdtemp()
os.environ.update(SQLITE_PATH=os.path.join(TMP, "s.db"), DATA_DIR=TMP, DATABASE_URL="", SERVICE_AREA="off",
                  WEB_DEV_LOGIN="1", PORT="8781", OSRM_URL="")
sys.path.insert(0, "/home/claude/taxi-tap")
import core
from playwright.sync_api import sync_playwright
STUB = open("/home/claude/taxi-tap/tests/leaflet_stub.js").read()
core.init_db()
def route(r):
    u = r.request.url
    if u.endswith("leaflet.js"): return r.fulfill(body=STUB, content_type="application/javascript")
    if u.endswith("leaflet.css"): return r.fulfill(body="", content_type="text/css")
    if "tile" in u or "arcgis" in u: return r.abort()
    return r.continue_()
srv = subprocess.Popen([sys.executable, "web.py"], cwd="/home/claude/taxi-tap", env=os.environ.copy(), stdout=subprocess.DEVNULL); time.sleep(1.5)
try:
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
        k = b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True).new_page()
        k.route("**/*", route); k.on("pageerror", lambda e: print("JS:", e))
        k.goto("http://127.0.0.1:8781/"); k.fill("#nm", "Кайрат"); k.fill("#ph", "0227 155 603"); k.check("#agree"); k.click("#go")
        k.wait_for_timeout(1800); k.evaluate("viewCabinet()"); k.wait_for_timeout(1200)
        k.screenshot(path="/tmp/cab1.png")
        k.evaluate("document.querySelector('#home').scrollTop=400"); k.wait_for_timeout(400); k.screenshot(path="/tmp/cab2.png")
        b.close()
finally:
    srv.terminate()
