"""
Сайттын скриншоттору (тармаксыз: Leaflet жана Nominatim жасалма).
Иштетүү: python tests/screens.py  → tests/shots/*.png
"""
import json, os, subprocess, sys, time, tempfile
TMP = tempfile.mkdtemp()
os.environ.update(SQLITE_PATH=os.path.join(TMP, "s.db"), DATA_DIR=TMP, DATABASE_URL="",
                  WEB_DEV_LOGIN="1", PORT="8770", ADMIN_PHONES="0700900900", COMMISSION_PCT="10",
                  PAY_INFO="MBank: +996 700 900 900 (Каке Ж.)")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import core, dispatch, flow
from PIL import Image, ImageDraw
from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
SHOTS = os.path.join(HERE, "shots"); os.makedirs(SHOTS, exist_ok=True)
STUB = open(os.path.join(HERE, "leaflet_stub.js")).read()


def fake_doc(name, color, label):
    im = Image.new("RGB", (900, 580), color); d = ImageDraw.Draw(im)
    d.rectangle((40, 40, 300, 360), fill="#D9D4C7"); d.rectangle((40, 420, 860, 540), fill="#FFFFFF")
    for y in range(80, 380, 50): d.rectangle((340, y, 820, y + 22), fill="#FFFFFF")
    d.text((350, 460), label, fill="#152741")
    p = os.path.join(TMP, name); im.save(p, "JPEG"); return p


DOCS = [fake_doc("lic.jpg", "#B9D7EE", "KG DRIVER LICENSE"), fake_doc("tp.jpg", "#E3D9B8", "TECH PASSPORT"),
        fake_doc("car.jpg", "#C9D6C0", "CAR"), fake_doc("chek.jpg", "#FFFFFF", "MBANK 500 som")]

core.init_db()
# фон: онлайн айдоочулар, бүгүнкү сапарлар
for i, (n, pos) in enumerate([("Бакыт", (42.4935, 78.3990)), ("Асан", (42.4860, 78.3850)), ("Үсөн", (42.4990, 78.4060))]):
    uid = core.phone_uid("070055500%d" % i); core.ensure_user(uid, n); core.set_user(uid, phone=uid[3:])
    flow.register_driver(uid, n, "Toyota Camry", "Ак", "01 12%d ABC" % i, {"license": "x", "techpass": "x", "car": "x"})
    flow.admin_driver(uid, "approve"); core.add_tx(uid, 600, "topup"); core.driver_location(uid, *pos, live_period=3600)

REV = {"address": {"road": "Абдрахманов көчөсү", "house_number": "128"}}
SRCH = [{"lat": "42.4700", "lon": "78.4100", "display_name": "Борбордук базар, Торекулов көчөсү, Каракол"}]


def route(r):
    u = r.request.url
    if u.endswith("leaflet.js"): return r.fulfill(body=STUB, content_type="application/javascript")
    if u.endswith("leaflet.css"): return r.fulfill(body="", content_type="text/css")
    if "nominatim" in u: return r.fulfill(body=json.dumps(REV if "/reverse" in u else SRCH), content_type="application/json")
    return r.continue_()


def shot(page, name, wait=1000, full=False):
    page.wait_for_timeout(wait); page.screenshot(path=os.path.join(SHOTS, name + ".png"), full_page=full)


srv = subprocess.Popen([sys.executable, "web.py"], env=os.environ.copy()); time.sleep(1.5)
URL = "http://127.0.0.1:8770"
with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
    phone = dict(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True,
                 geolocation={"latitude": 42.4935, "longitude": 78.3990}, permissions=["geolocation"])

    def page_for(ctx_kw):
        pg = b.new_context(**ctx_kw).new_page(); pg.route("**/*", route)
        pg.on("pageerror", lambda e: print("JS:", e)); pg.on("dialog", lambda d: d.accept("Техпаспорттун сүрөтү бүдөмүк"))
        return pg

    # --- жаңы айдоочу каттоодон өтөт ---
    d = page_for(phone)
    d.goto(URL + "/driver"); d.fill("#nm", "Нурбек"); d.fill("#ph", "0700 444 555"); d.click("#go")
    d.wait_for_timeout(1500)
    d.fill("#rm", "Honda Fit"); d.fill("#rc", "Боз"); d.fill("#rp", "01 777 KGA")
    for sel, f in (("#dl", DOCS[0]), ("#dt", DOCS[1]), ("#dc", DOCS[2])):
        d.set_input_files(sel + " input", f)
    shot(d, "v1_register", 1500, True)
    d.click("#send"); shot(d, "v2_pending", 1500)

    # --- админ: арыз жана документтер ---
    a = page_for(dict(viewport={"width": 1100, "height": 820}))
    a.goto(URL + "/admin"); a.fill("#ph", "0700 900 900"); a.click("#go"); a.wait_for_timeout(1500)
    a.click("nav button[data-t='drivers']"); shot(a, "v3_admin_pending", 1500)
    a.click("[data-a='approve']"); a.wait_for_timeout(800)

    # --- айдоочу ырасталды → линия → толуктоо ---
    shot(d, "v4_approved", 2600)
    d.click("#top"); d.fill("#am", "500"); d.set_input_files("#pf input", DOCS[3]); shot(d, "v5_topup", 1200, True)
    d.click("#send"); shot(d, "v6_topup_sent", 1500)

    a.click("nav button[data-t='topups']"); shot(a, "v7_admin_topup", 1500)
    a.click("[data-ok]"); a.wait_for_timeout(800)

    # --- жүргүнчүнүн менюсу ---
    r = page_for(phone)
    r.goto(URL + "/"); r.fill("#nm", "Айгүл"); r.fill("#ph", "0555 111 222"); r.click("#go"); r.wait_for_timeout(1500)
    r.click("#menuBtn"); shot(r, "v8_rider_menu", 1200)
    b.close()
srv.terminate()
uid = core.phone_uid("0700 444 555")
print("Нурбек:", core.get_driver(uid)["status"], "баланс", core.get_driver(uid)["balance"])
