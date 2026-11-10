"""Админ панелинин скриншоттору (тармаксыз)."""
import os, subprocess, sys, time, tempfile
DB = tempfile.mktemp(suffix=".db")
os.environ.update(SQLITE_PATH=DB, DATABASE_URL="", WEB_DEV_LOGIN="1", PORT="8767",
                  ADMIN_IDS="900", COMMISSION_PCT="10")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import core, flow, dispatch
from playwright.sync_api import sync_playwright

core.init_db()
core.ensure_user("tg:900", "Каке"); core.set_user("tg:900", phone="+996700900900")
DR = [("tg:41", "Бакыт", "Ак Toyota Camry", "01 123 ABC", (42.4935, 78.3990)),
      ("tg:42", "Асан", "Боз Honda Fit", "01 777 KGA", (42.4860, 78.3850)),
      ("tg:43", "Үсөн", "Кара Lexus RX", "08 555 BBB", (42.4990, 78.4060)),
      ("tg:44", "Нурбек", "Ак Hyundai Sonata", "02 404 AKA", (42.4820, 78.4020)),
      ("tg:45", "Эрмек", "Көк Toyota Prius", "01 909 TAP", (42.4950, 78.3800))]
for uid, name, car, plate, pos in DR:
    core.ensure_user(uid, name); core.set_user(uid, phone="+99670055500" + uid[-1])
    color, model = car.split(" ", 1)
    core.add_driver(uid, model, color, plate); core.set_driver(uid, status="active", rating=4.8, rides_done=120)
    core.add_tx(uid, 600, "topup"); core.driver_location(uid, *pos, live_period=3600)
core.ensure_user("tg:46", "Талант"); core.set_user("tg:46", phone="+996700555046")
core.add_driver("tg:46", "Mercedes E-class", "Кара", "01 001 AAA")
# бүгүн бүткөн сапарлар
for i, (p, n) in enumerate([("+996555000001", "Айгүл"), ("+996555000002", "Мирлан"), ("+996555000003", "Жаңыл")]):
    uid = "ph:" + p; core.ensure_user(uid, n); core.set_user(uid, phone=p)
    q = core.quote(42.4907, 78.3936, 42.4700 + i * 0.01, 78.4100)
    rid = core.create_ride(uid, q, 42.4907, 78.3936, 42.4700 + i * 0.01, 78.4100)
    d = DR[i][0]; core.offer(rid, d); core.accept(rid, d)
    for _ in range(3): core.advance(rid, d)
    core.rate(rid, uid, 5)
# азыркы заказдар
for p, n, pos in (("+996555000004", "Бакыт", (42.4890, 78.3960)), ("+996555000005", "Самара", (42.4970, 78.3900))):
    uid = "ph:" + p; core.ensure_user(uid, n); core.set_user(uid, phone=p)
    q = core.quote(*pos, 42.475, 78.41); core.create_ride(uid, q, *pos, 42.475, 78.41)
r = core.searching_rides()[0]; core.offer(r["id"], "tg:44"); core.accept(r["id"], "tg:44")
core.add_tx("tg:42", 0, "topup", status="pending", proof="FILE")
for uid, name in (("tg:44", "Нурбек"),): pass

srv = subprocess.Popen([sys.executable, "web.py"], env=os.environ.copy())
time.sleep(1.5)
HERE = os.path.dirname(os.path.abspath(__file__))
STUB = open(os.path.join(HERE, "leaflet_stub.js")).read()
def route(r):
    u = r.request.url
    if u.endswith("leaflet.js"): return r.fulfill(body=STUB, content_type="application/javascript")
    if u.endswith("leaflet.css"): return r.fulfill(body="", content_type="text/css")
    return r.continue_()
def shot(page, name, wait=1200, full=False):
    page.wait_for_timeout(wait); page.screenshot(path=os.path.join(HERE, "shots", name + ".png"), full_page=full)

with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
    ctx = b.new_context(viewport={"width": 1100, "height": 860}, device_scale_factor=1)
    page = ctx.new_page(); page.route("**/*", route)
    page.on("pageerror", lambda e: print("JS:", e)); page.on("dialog", lambda d: d.accept("500"))
    page.goto("http://127.0.0.1:8767/admin"); page.fill("#ph", "0700 900 900"); page.click("#go")
    shot(page, "a1_map", 2500, True)
    page.click("nav button[data-t='drivers']"); shot(page, "a2_drivers", 1500, True)
    page.click("nav button[data-t='topups']"); shot(page, "a3_topups", 1500, True)
    page.click("nav button[data-t='rides']"); shot(page, "a4_rides", 1500, True)
    page.click("nav button[data-t='tariffs']"); shot(page, "a5_tariffs", 1500, True)
    # аракеттер иштейби
    page.click("nav button[data-t='drivers']"); page.wait_for_timeout(1000)
    page.click("[data-a='approve']"); page.wait_for_timeout(800)
    page.click("nav button[data-t='topups']"); page.wait_for_timeout(800)
    page.fill("#am" + str(core.query("SELECT id FROM balance_tx WHERE status='pending'", (), "one")["id"]), "300")
    page.click("[data-ok]"); page.wait_for_timeout(800)
    page.click("nav button[data-t='tariffs']"); page.wait_for_timeout(800)
    page.fill("#t2base", "70"); page.click("[data-i='2']"); page.wait_for_timeout(800)
    mob = b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True)
    mp = mob.new_page(); mp.route("**/*", route)
    mp.goto("http://127.0.0.1:8767/admin"); mp.fill("#ph", "0700 900 900"); mp.click("#go"); shot(mp, "a6_mobile", 2500)
    b.close()
srv.terminate()
print("Талант:", core.get_driver("tg:46")["status"], "| Асан баланс:", core.get_driver("tg:42")["balance"],
      "| Каракол тариф:", core.get_tariff("Каракол")["base"])
os.remove(DB)
