# -*- coding: utf-8 -*-
"""
Такси ТАП! сыноолору. Иштетүү: python -m unittest discover tests
"""
import base64
import http.cookiejar
import json
import os
import shutil
import sys
import tempfile
import unittest
import urllib.request

_tmp = tempfile.mkdtemp()
os.environ.update(SQLITE_PATH=os.path.join(_tmp, "t.db"), DATA_DIR=_tmp, DATABASE_URL="",
                  ADMIN_IDS="900", ADMIN_PHONES="0700 111 000", COMMISSION_PCT="10",
                  WEB_DEV_LOGIN="1", SITE_URL="https://taxi.example.kg", SERVICE_AREA="off")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import bot       # noqa: E402
import core      # noqa: E402
import dispatch  # noqa: E402
import flow      # noqa: E402
import web       # noqa: E402
import ops       # noqa: E402

KARAKOL = (42.4907, 78.3936)
NEAR = (42.4950, 78.3990)       # ~0.6 км
FAR = (42.5300, 78.4500)        # ~6 км
DEST = (42.4700, 78.4100)
PNG = "data:image/png;base64," + base64.b64encode(
    bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000"
                  "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082")).decode()


def make_driver(phone, name, pos=None, balance=0):
    uid = core.phone_uid(phone)
    core.ensure_user(uid, name)
    core.set_user(uid, phone=uid[3:])
    flow.register_driver(uid, name, "Camry", "Ак", "01 123 ABC",
                         {"license": "a.jpg", "techpass": "b.jpg", "car": "c.jpg"})
    flow.admin_driver(uid, "approve")
    if balance:
        core.add_tx(uid, balance, "topup")
    if pos:
        core.driver_location(uid, *pos, live_period=3600)
    return uid


def rider(phone, name="Жүргүнчү"):
    uid = core.phone_uid(phone)
    core.ensure_user(uid, name)
    core.set_user(uid, phone=uid[3:])
    return uid


def order(uid, p=KARAKOL, d=DEST):
    q = core.quote(p[0], p[1], *(d or (None, None)))
    return core.create_ride(uid, q, p[0], p[1], *(d or (None, None)))


def offline_all():
    core.query("UPDATE drivers SET online=0, live_until=NULL, busy_ride=NULL")
    core.query("UPDATE rides SET status='cancelled' WHERE status IN "
               "('searching','accepted','arrived','in_trip')")


class Ride(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        core.init_db()

    def setUp(self):
        offline_all()

    def test_full_ride(self):
        d1 = make_driver("0700 000 001", "Асан", NEAR, 1000)
        make_driver("0700 000 002", "Үсөн", FAR)
        p = rider("0555 000 001", "Айгүл")
        rid = order(p)
        out = dispatch.tick()
        self.assertEqual(core.get_ride(rid)["offered_to"], d1)          # эң жакыны
        self.assertEqual([o["to"] for o in out], [d1])
        self.assertEqual(out[0]["path"], "/driver")
        self.assertIsNone(flow.driver_accept(core.phone_uid("0700 000 002"), rid))  # сунуш ага эмес
        out = flow.driver_accept(d1, rid)
        self.assertEqual(out[0]["to"], p)
        self.assertIn("01 123 ABC", out[0]["text"])
        self.assertIn("Айдоочу келди", flow.driver_step(d1, rid)[0]["text"])
        self.assertEqual(flow.driver_step(d1, rid), [])                 # сапар башталды
        self.assertIn("бүттү", flow.driver_step(d1, rid)[0]["text"])
        price = core.get_ride(rid)["price"]
        self.assertEqual(core.get_driver(d1)["balance"], 1000 - int(price * 0.1 + 0.5))
        self.assertTrue(core.rate(rid, p, 4))
        self.assertFalse(core.rate(rid, p, 1))
        self.assertEqual(core.get_driver(d1)["rating"], 4.0)

    def test_timeout_moves_to_next(self):
        a = make_driver("0700 000 011", "А", NEAR)
        b = make_driver("0700 000 012", "Б", (42.4920, 78.3950))
        rid = order(rider("0555 000 011"), d=None)
        dispatch.tick()
        first = core.get_ride(rid)["offered_to"]
        self.assertIn(first, (a, b))
        core.query("UPDATE rides SET offered_at=? WHERE id=?", (core.now() - 60, rid))
        dispatch.tick()
        self.assertEqual(core.get_ride(rid)["offered_to"], b if first == a else a)

    def test_no_driver(self):
        p = rider("0555 000 021")
        rid = order(p, p=(40.5283, 72.7985))
        core.query("UPDATE rides SET created_at=? WHERE id=?", (core.now() - 999, rid))
        out = dispatch.tick()
        self.assertEqual(core.get_ride(rid)["status"], "cancelled")
        self.assertEqual(out[0]["to"], p)

    def test_self_order_only_in_test_mode(self):
        d = make_driver("0700 000 051", "Өзү", NEAR)
        rid = order(d)
        dispatch.tick()
        self.assertIsNone(core.get_ride(rid)["offered_to"])
        core.TEST_SELF_ORDER = True
        try:
            dispatch.tick()
            self.assertEqual(core.get_ride(rid)["offered_to"], d)
        finally:
            core.TEST_SELF_ORDER = False

    def test_cancel_notifies_driver(self):
        d = make_driver("0700 000 031", "В", NEAR)
        p = rider("0555 000 031")
        rid = order(p)
        dispatch.tick()
        out = flow.passenger_cancel(p, rid)
        self.assertEqual(out[0]["to"], d)

    def test_bazar_korgon(self):
        self.assertEqual(core.city_of(41.0400, 72.7500), "Базар-Коргон")
        q = core.quote(41.0400, 72.7500, 41.0250, 72.7350)
        self.assertEqual(q["tariff"]["base"], 10)
        self.assertTrue(60 <= q["price"] <= 150)
        # Яндекс: 64 · 82 · 118 сом → биздики арзаныраак
        t = core.get_tariff("Базар-Коргон")
        self.assertEqual([core.price_of(t, 2.5, 9), core.price_of(t, 2.6, 11), core.price_of(t, 6, 12)],
                         [60, 70, 110])

    def test_quote(self):
        q = core.quote(*KARAKOL, *DEST)
        self.assertEqual(q["city"], "Каракол")
        self.assertEqual(q["price"] % 10, 0)
        self.assertIsNone(core.quote(41.0, 78.0)["city"])


class Area(unittest.TestCase):
    def setUp(self):
        core.AREA_ON = True
        core._area.update(geojson=None, source="bbox")

    def tearDown(self):
        core.AREA_ON = False

    def test_bbox_fallback(self):
        self.assertTrue(core.in_area(41.0377, 72.7470))           # Базар-Коргон
        self.assertTrue(core.in_area(41.33, 72.94))                # Арстанбап
        self.assertFalse(core.in_area(40.5283, 72.7985))           # Ош
        self.assertFalse(core.in_area(42.8746, 74.5698))           # Бишкек
        self.assertEqual(core.city_of(41.04, 72.75), "Базар-Коргон")
        self.assertIsNone(core.quote(42.8746, 74.5698, 42.88, 74.58)["city"])

    def test_polygon(self):
        core._area["geojson"] = {"type": "MultiPolygon", "coordinates": [
            [[[72.6, 41.0], [72.9, 41.0], [72.9, 41.1], [72.6, 41.1], [72.6, 41.0]]]]}
        self.assertTrue(core.in_area(41.05, 72.75))
        self.assertFalse(core.in_area(41.2, 72.75))
        info = core.area_info()
        self.assertEqual(info["bbox"], [41.0, 72.6, 41.1, 72.9])
        self.assertEqual(info["center"], list(core.CITIES["Базар-Коргон"]))
        self.assertEqual([t["city"] for t in core.all_tariffs()], ["Базар-Коргон"])
        self.assertIn("Манас", core.CITIES)
        self.assertNotIn("Жалал-Абад", core.CITIES)


class CustomArea(unittest.TestCase):
    def setUp(self):
        core.AREA_ON = True
        core._area.update(geojson=None, source="bbox")

    def tearDown(self):
        core.reset_area()
        core.AREA_ON = False

    def test_draw_and_reset(self):
        self.assertFalse(core.set_custom_area([[41.0, 72.7], [41.1, 72.8]]))        # 2 чекит аз
        self.assertFalse(core.set_custom_area([[55.0, 37.0], [55.1, 37.1], [55.2, 37.0]]))  # Москва
        self.assertTrue(core.set_custom_area([[41.10, 72.65], [41.10, 72.85], [40.98, 72.85], [40.98, 72.65]]))
        self.assertEqual(core.area_info()["source"], "custom")
        self.assertTrue(core.in_area(41.04, 72.75))
        self.assertFalse(core.in_area(41.33, 72.94))                                # Арстанбап сыртта
        core._area.update(geojson=None)
        core.load_area(fetch=False)                                                 # файлдан окуйт
        self.assertEqual(core.area_info()["source"], "custom")
        core.reset_area()
        self.assertNotEqual(core.area_info()["source"], "custom")


class Finance(unittest.TestCase):
    def setUp(self):
        core.init_db()
        offline_all()

    def tearDown(self):
        core.query("DELETE FROM settings")
        core._settings_cache.clear()

    def test_free_until_then_percent(self):
        self.assertFalse(core.set_finance_config(50))                     # 30%дан ашык болбойт
        self.assertFalse(core.set_finance_config(5, "31.12.2026"))         # туура эмес күн
        self.assertTrue(core.set_finance_config(5, "2099-01-01"))
        self.assertEqual(core.commission_pct(), 0)
        self.assertIn("Бекер", core.finance_mode_text())
        core.set_finance_config(5, "2020-01-01")                          # мөөнөт өткөн
        self.assertEqual(core.commission_pct(), 5)
        self.assertEqual(core.finance_mode_text(), "Ар бир сапардан 5%")

    def test_income_and_cabinet(self):
        core.set_finance_config(7)
        d = make_driver("0700 000 061", "Каржы", NEAR, 1000)
        rid = order(rider("0555 000 061"))
        dispatch.tick()
        flow.driver_accept(d, rid)
        for _ in range(3):
            flow.driver_step(d, rid)
        price = core.get_ride(rid)["price"]
        me = core.driver_finance(d)
        self.assertEqual(me["today"]["rides"], 1)
        self.assertEqual(me["month"]["gross"], int(price))
        self.assertEqual(me["today"]["fee"], int(price * 0.07 + 0.5))
        a = core.admin_finance()
        self.assertGreaterEqual(a["totals"]["today"]["commission"], int(price * 0.07 + 0.5))
        self.assertEqual(len(a["months"]), 6)
        self.assertIn(d, [x["uid"] for x in a["drivers"]])

    def test_low_balance_notice(self):
        core.set_finance_config(10, None, 50)
        d = make_driver("0700 000 062", "Аз", NEAR, 55)
        rid = order(rider("0555 000 062"))
        dispatch.tick()
        flow.driver_accept(d, rid)
        flow.driver_step(d, rid); flow.driver_step(d, rid)
        out = flow.driver_step(d, rid)
        self.assertIn(d, [o["to"] for o in out])                          # «баланс аз» кабары
        self.assertFalse(core.is_available(core.get_driver(d)))


class Ops(unittest.TestCase):
    def test_backup_restore(self):
        core.init_db()
        make_driver("0700 000 081", "Көчүрмө", NEAR, 300)
        path = ops.backup()
        self.assertTrue(path.endswith(".json.gz"))
        import gzip as _gz
        data = json.load(_gz.open(path, "rt", encoding="utf-8"))
        self.assertNotIn("web_sessions", data["tables"])                      # токендер кирбейт
        self.assertTrue(any(d["uid"] == "ph:+996700000081" for d in data["tables"]["drivers"]))
        # бош базага кайтаруу
        old = core.SQLITE_PATH
        core.SQLITE_PATH = os.path.join(_tmp, "restore.db"); core._drop()
        try:
            ops.restore(path)
            self.assertEqual(core.get_driver("ph:+996700000081")["balance"], 300)
        finally:
            core._drop(); core.SQLITE_PATH = old

    def test_error_alert_rate_limited(self):
        sent = []
        ops.send_text = lambda tg, text: sent.append((tg, text))
        try:
            for _ in range(3):
                try:
                    1 / 0
                except ZeroDivisionError:
                    ops.report_error("сыноо")
            self.assertEqual(len(sent), len(core.admins()))                    # бир жолу гана
            self.assertIn("ZeroDivisionError", sent[0][1])
        finally:
            ops.send_text = None


class DestOut(unittest.TestCase):
    def test_intercity_refused(self):
        core.init_db()
        old = core.AREA_ON
        core.AREA_ON = True
        try:
            core.set_custom_area([[41.10, 72.65], [41.10, 72.85], [40.95, 72.85], [40.95, 72.65]])
            bk = (41.0377, 72.7470)
            self.assertTrue(core.quote(*bk, 40.5283, 72.7985).get("dest_out"))   # Ош
            q = core.quote(*bk, 41.03, 72.74)
            self.assertFalse(q.get("dest_out")); self.assertTrue(q["price"])
        finally:
            core.reset_area(); core.AREA_ON = old

class Promo(unittest.TestCase):
    def setUp(self):
        core.init_db(); offline_all()
        core.query("DELETE FROM promos")

    def test_first_ride_discount_paid_to_driver(self):
        self.assertFalse(core.save_promo("AB", 50))                        # кыска
        self.assertTrue(core.save_promo("тап50", 50, first_only=True, max_uses=2, expires="2099-01-01"))
        p = rider("0555 000 091")
        self.assertEqual(core.check_promo("ТАП50", p, 150), (50.0, None))
        self.assertEqual(core.check_promo("tap50", p, 150)[1], "Мындай промокод жок")
        self.assertEqual(core.check_promo("ТАП50", p, 40)[0], 30)           # кеминде 10 сом төлөйт
        d = make_driver("0700 000 091", "Промо", NEAR, 0)
        q = core.quote(*KARAKOL, *DEST)
        rid = core.create_ride(p, q, *KARAKOL, *DEST, promo="ТАП50", discount=50)
        self.assertEqual(core.check_promo("ТАП50", p)[1], "Бул промокодду колдонуп койгонсуз")
        dispatch.tick(); flow.driver_accept(d, rid)
        for _ in range(3):
            flow.driver_step(d, rid)
        fee = int(q["price"] * 0.10 + 0.5)                                    # COMMISSION_PCT=10
        self.assertEqual(core.get_driver(d)["balance"], 50 - fee)            # +50 промо, −комиссия
        self.assertEqual(web.ride_view(core.get_ride(rid))["pay"], q["price"] - 50)
        p2 = rider("0555 000 092")
        self.assertIsNone(core.check_promo("ТАП50", p2)[1])
        p3 = rider("0555 000 093")
        core.create_ride(p2, q, *KARAKOL, *DEST, promo="ТАП50", discount=50)
        self.assertEqual(core.check_promo("ТАП50", p3)[1], "Промокоддун саны бүттү")
        self.assertEqual(core.check_promo("ТАП50", p, 150)[1], "Бул промокодду колдонуп койгонсуз")
        self.assertEqual(core.list_promos()[0]["spent"], 50)


class Scheduled(unittest.TestCase):
    def setUp(self):
        core.init_db(); offline_all()

    def test_scheduled_then_activates(self):
        p = rider("0555 000 081")
        d = make_driver("0700 000 081", "Алдын", NEAR, 0)
        q = core.quote(*KARAKOL, *DEST)
        rid = core.create_ride(p, q, *KARAKOL, *DEST, scheduled_at=core.now() + 3600)
        self.assertEqual(core.get_ride(rid)["status"], "scheduled")
        self.assertEqual(core.active_ride_of(p)["id"], rid)
        dispatch.tick()
        self.assertEqual(core.get_ride(rid)["status"], "scheduled")       # азырынча эрте
        core.query("UPDATE rides SET scheduled_at=? WHERE id=?", (core.now() + 300, rid))
        out = dispatch.tick()
        self.assertEqual(core.get_ride(rid)["status"], "searching")
        self.assertTrue(any(o["to"] == p for o in out))
        self.assertEqual(core.get_ride(rid)["offered_to"], d)

    def test_cancel_scheduled_and_lost(self):
        p = rider("0555 000 082")
        q = core.quote(*KARAKOL, *DEST)
        rid = core.create_ride(p, q, *KARAKOL, *DEST, scheduled_at=core.now() + 7200)
        self.assertTrue(core.cancel(rid, "passenger"))
        self.assertEqual(core.get_ride(rid)["status"], "cancelled")
        rid2 = core.create_ride(p, q, *KARAKOL, *DEST)
        core.query("UPDATE rides SET status='cancelled', cancel_by='system' WHERE id=?", (rid2,))
        self.assertIn(rid2, [x["id"] for x in core.lost_orders(7)])
        self.assertNotIn(rid, [x["id"] for x in core.lost_orders(7)])


class Accounts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        core.init_db()

    def test_phone_uid(self):
        self.assertEqual(core.phone_uid("0555 111 222"), "ph:+996555111222")
        self.assertEqual(core.phone_uid("+996 555 111 222"), "ph:+996555111222")
        self.assertIsNone(core.phone_uid("123"))

    def test_verify_links_telegram(self):
        tok = core.web_session_new("0700 999 888", "Жаңыл")
        self.assertIsNone(core.web_session_verify(tok, "+996700000000", "tg:5"))
        uid = core.web_session_verify(tok, "996700999888", "tg:5")
        self.assertEqual(uid, "ph:+996700999888")
        self.assertEqual(core.tg_of(uid), "tg:5")
        core.set_user(uid, notify=0)
        self.assertIsNone(core.tg_of(uid))

    def test_admin_gate(self):
        tok = core.web_session_new("0700 222 333", "", "admin")
        self.assertIsNone(core.web_session_verify(tok, None, "tg:6"))      # админ эмес
        tok = core.web_session_new("0700 222 333", "", "admin")
        self.assertEqual(core.web_session_verify(tok, None, "tg:900"), "ph:+996700222333")  # ADMIN_IDS
        tok = core.web_session_new("0700 111 000", "", "admin")
        self.assertTrue(core.is_admin(core.web_session_verify(tok)))        # ADMIN_PHONES

    def test_topup_once(self):
        d = make_driver("0700 000 041", "Г")
        before = core.get_driver(d)["balance"]
        outs = flow.request_topup(d, 500, "x.jpg")
        self.assertTrue(all(o["path"] == "/admin" for o in outs))
        tx = core.query("SELECT id FROM balance_tx WHERE driver=? AND status='pending'", (d,), "one")["id"]
        self.assertEqual(flow.admin_topup("ph:+996700111000", tx, 500)[0]["to"], d)
        self.assertIsNone(flow.admin_topup("ph:+996700111000", tx, 500))
        self.assertEqual(core.get_driver(d)["balance"], before + 500)

    def test_upload_safe(self):
        name = core.save_upload(PNG)
        self.assertTrue(core.upload_path(name))
        self.assertIsNone(core.upload_path("../t.db"))
        self.assertIsNone(core.save_upload("data:text/html;base64,PGI+"))


class Bot(unittest.TestCase):
    def setUp(self):
        core.init_db()
        self.sent = []
        bot.API = "x"
        bot.api = lambda m, **p: self.sent.append((m, p)) or {"ok": True}

    def test_verify_and_notify(self):
        tok = core.web_session_new("0555 777 000", "Бакыт")
        bot.handle_update({"message": {"chat": {"id": 70, "type": "private"}, "from": {"id": 70},
                                       "text": "/start web_" + tok}})
        self.assertTrue(self.sent[-1][1]["reply_markup"]["keyboard"][0][0]["request_contact"])
        bot.handle_update({"message": {"chat": {"id": 70, "type": "private"}, "from": {"id": 70},
                                       "contact": {"user_id": 70, "phone_number": "996555777000"}}})
        self.assertIn("ырасталды", self.sent[-2][1]["text"])
        uid = "ph:+996555777000"
        self.assertEqual(core.get_user(uid)["tg_uid"], "tg:70")
        self.sent.clear()
        bot.deliver([{"to": uid, "text": "салам", "path": "/"}])
        self.assertEqual(self.sent[0][1]["chat_id"], "70")
        self.assertEqual(self.sent[0][1]["reply_markup"]["inline_keyboard"][0][0]["url"],
                         "https://taxi.example.kg/")
        bot.handle_update({"callback_query": {"id": "c", "from": {"id": 70}, "data": "notify:0",
                                              "message": {"chat": {"id": 70}, "message_id": 1}}})
        self.sent.clear()
        bot.deliver([{"to": uid, "text": "салам"}])
        self.assertEqual(self.sent, [])

    def test_foreign_contact_rejected(self):
        tok = core.web_session_new("0555 777 111", "")
        bot.handle_update({"message": {"chat": {"id": 71, "type": "private"}, "from": {"id": 71},
                                       "text": "/start web_" + tok}})
        bot.handle_update({"message": {"chat": {"id": 71, "type": "private"}, "from": {"id": 71},
                                       "contact": {"user_id": 99, "phone_number": "996555777111"}}})
        self.assertFalse(core.web_session(tok)["verified"])


class Http(unittest.TestCase):
    """Сайттын API'си чыныгы HTTP аркылуу: каттоо → ырастоо → линия → заказ."""

    @classmethod
    def setUpClass(cls):
        core.init_db()
        offline_all()
        cls.srv = web.start(0)
        cls.base = "http://127.0.0.1:%d" % cls.srv.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def client(self):
        op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

        def call(path, body=None):
            req = urllib.request.Request(self.base + path, data=None if body is None else
                                         json.dumps(body).encode(),
                                         headers={"Content-Type": "application/json"})
            try:
                return json.loads(op.open(req).read())
            except urllib.error.HTTPError as e:
                return json.loads(e.read())
        call.raw = lambda path: op.open(self.base + path)
        return call

    def test_driver_journey(self):
        offline_all()
        drv, adm, pas = self.client(), self.client(), self.client()
        self.assertEqual(drv("/api/login", {"phone": "0700 444 555", "kind": "driver"})["error"], "terms")
        self.assertTrue(drv("/api/login", {"phone": "0700 444 555", "name": "Нурбек", "kind": "driver", "agree": True})["auth"])
        self.assertTrue(core.get_user("ph:+996700444555")["terms_at"])
        st = drv("/api/d/state")
        self.assertIsNone(st["status"])
        self.assertEqual(drv("/api/d/register", {"name": "Нурбек", "model": "Fit", "color": "Боз",
                                                 "plate": "01 777 kga", "license": PNG})["error"], "doc_techpass")
        st = drv("/api/d/register", {"name": "Нурбек", "model": "Fit", "color": "Боз", "plate": "01 777 kga",
                                     "license": PNG, "techpass": PNG, "car": PNG})
        self.assertEqual(st["status"], "pending")
        self.assertEqual(drv("/api/d/online", {"on": True, "p": list(NEAR)})["error"], "not_active")
        # админ
        self.assertEqual(adm("/api/login", {"phone": "0700 123 123", "kind": "admin"})["error"], "not_admin")
        self.assertTrue(adm("/api/login", {"phone": "0700 111 000", "kind": "admin"})["auth"])
        ov = adm("/api/a/overview")
        pend = [d for d in ov["pending_drivers"] if d["name"] == "Нурбек"][0]
        ds = [d for d in adm("/api/a/drivers")["drivers"] if d["uid"] == pend["uid"]][0]
        with self.assertRaises(urllib.error.HTTPError):                    # кирбеген адам көрбөйт
            urllib.request.urlopen(self.base + "/api/a/file?n=" + ds["doc_license"])
        self.assertEqual(adm.raw("/api/a/file?n=" + ds["doc_license"]).headers["Content-Type"],
                         "image/png")
        self.assertEqual(drv("/api/a/overview")["error"], "auth")          # айдоочу админ эмес
        adm("/api/a/driver", {"uid": pend["uid"], "action": "approve"})
        # аймак: админ тартат, айдоочу тарта албайт
        pts = [[41.10, 72.65], [41.10, 72.85], [40.98, 72.85], [40.98, 72.65]]
        self.assertEqual(drv("/api/a/area", {"points": pts})["error"], "auth")
        self.assertEqual(adm("/api/a/area", {"points": pts})["source"], "custom")
        self.assertEqual(adm("/api/a/area", {"points": pts[:2]})["error"], "bad_points")
        adm("/api/a/area", {"reset": True})
        # диспетчер: телефон заказ
        r = adm("/api/a/order", {"phone": "0555 999 000", "name": "Чалган эже", "note": "базардын жанында",
                                 "p": list(KARAKOL)})
        self.assertEqual(r["ride"]["status"], "searching")
        self.assertEqual(adm("/api/a/order", {"phone": "0555 999 000", "p": list(KARAKOL)})["error"], "have_active")
        self.assertEqual(drv("/api/a/order", {"phone": "0555 999 001", "p": list(KARAKOL)})["error"], "auth")
        ov = adm("/api/a/overview")
        self.assertTrue(any(x["source"] == "phone" and x["note"] == "базардын жанында" for x in ov["rides"]))
        dispatch.tick()
        st = drv("/api/d/state")
        if st["offer"]:
            self.assertEqual(st["offer"]["note"], "базардын жанында")
        adm("/api/a/cancel", {"id": r["ride"]["id"]})
        # каржы: админ гана өзгөртөт
        self.assertEqual(drv("/api/a/finance", {"percent": 1})["error"], "auth")
        self.assertEqual(adm("/api/a/finance", {"percent": 5, "free_until": "2099-01-01"})["pct_now"], 0)
        self.assertIn("Бекер", drv("/api/d/state")["tariff"])
        adm("/api/a/finance", {"percent": 10})
        # линия, заказ
        self.assertTrue(drv("/api/d/online", {"on": True, "p": list(NEAR)})["online"])
        pas("/api/login", {"phone": "0555 444 555", "name": "Айгүл", "agree": True})
        self.assertEqual(pas("/api/order", {"p": list(KARAKOL), "d": list(DEST)})["ride"]["status"], "searching")
        dispatch.tick()
        st = drv("/api/d/state")
        self.assertTrue(st["offer"])
        st = drv("/api/d/accept", {"id": st["offer"]["id"]})
        self.assertEqual(st["ride"]["status"], "accepted")
        self.assertEqual(pas("/api/ride")["ride"]["driver"]["plate"], "01 777 KGA")
        for _ in range(3):
            st = drv("/api/d/step", {"id": st["ride"]["id"]})
        self.assertIsNone(st["ride"])
        self.assertEqual(st["today"]["rides"], 1)
        # толуктоо
        st = drv("/api/d/topup", {"amount": 300, "proof": PNG})
        self.assertTrue(st["pending_topup"])
        tx = adm("/api/a/overview")["pending_topups"][0]
        self.assertEqual(tx["claimed"], 300)
        adm("/api/a/topup", {"id": tx["id"], "amount": 300})
        self.assertFalse(drv("/api/d/state")["pending_topup"])


if __name__ == "__main__":
    try:
        unittest.main()
    finally:
        shutil.rmtree(_tmp, ignore_errors=True)


class Routing(unittest.TestCase):
    def test_osrm_parsed_and_cached(self):
        calls = []

        class R:
            def __init__(self, b): self.b = b
            def read(self): return self.b
            def __enter__(self): return self
            def __exit__(self, *a): pass
        body = json.dumps({"routes": [{"distance": 4200, "duration": 600,
                                       "geometry": {"coordinates": [[78.39, 42.49], [78.40, 42.48], [78.41, 42.47]]}}]}).encode()
        orig = urllib.request.urlopen
        urllib.request.urlopen = lambda url, timeout=0: calls.append(url) or R(body)
        try:
            rt = core.route(42.49, 78.39, 42.47, 78.41)
            core.route(42.49, 78.39, 42.47, 78.41)
        finally:
            urllib.request.urlopen = orig
        self.assertTrue(rt["real"])
        self.assertEqual(rt["km"], 4.2)
        self.assertEqual(rt["min"], round(10 * core.TRAFFIC_FACTOR, 1))
        self.assertEqual(rt["coords"][0], [42.49, 78.39])
        self.assertEqual(len(calls), 1)                      # экинчиси кэштен

    def test_fallback_without_network(self):
        orig = urllib.request.urlopen

        def boom(*a, **k):
            raise OSError("no network")
        urllib.request.urlopen = boom
        try:
            rt = core.route(42.40, 78.30, 42.41, 78.31)
        finally:
            urllib.request.urlopen = orig
        self.assertFalse(rt["real"])
        self.assertEqual(len(rt["coords"]), 2)
        q = core.quote(42.40, 78.30, 42.41, 78.31)
        self.assertIn("minutes", q)
