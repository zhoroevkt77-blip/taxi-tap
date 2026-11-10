# -*- coding: utf-8 -*-
"""
Толук сценарий: жүргүнчү заказ берет, айдоочу алат, сапар бүтөт.
Иштетүү: python -m unittest discover tests
"""
import os
import sys
import tempfile
import unittest

_db = tempfile.mktemp(suffix=".db")
os.environ.update(SQLITE_PATH=_db, ADMIN_IDS="900", COMMISSION_PCT="10", DATABASE_URL="")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core      # noqa: E402
import dispatch  # noqa: E402
import flow      # noqa: E402

KARAKOL = (42.4907, 78.3936)
NEAR = (42.4950, 78.3990)       # ~0.6 км
FAR = (42.5300, 78.4500)        # ~6 км
DEST = (42.4700, 78.4100)

P, D1, D2, ADMIN = "tg:1", "tg:2", "tg:3", "tg:900"


def texts(outs, to=None):
    return [o.get("text", "") for o in outs if to is None or o["to"] == to]


def btn(outs, to, prefix):
    for o in outs:
        if o["to"] == to:
            for row in o.get("buttons") or []:
                for _, data in row:
                    if data.startswith(prefix):
                        return data
    return None


class Flow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        core.init_db()

    def _driver(self, uid, name, pos):
        flow.on_start(uid, name)
        flow.on_button(uid, "lang:ky")
        flow.on_text(uid, "🚗 Айдоочу болуу")
        flow.on_contact(uid, "996700000%s" % uid[-1])
        flow.on_text(uid, "Toyota Camry")
        flow.on_text(uid, "ак")
        out = flow.on_text(uid, "01 123 ABC")
        data = btn(out, ADMIN, "adm:ok:")
        self.assertEqual(data, "adm:ok:" + uid)
        flow.on_button(ADMIN, data)
        self.assertEqual(core.get_driver(uid)["status"], "active")
        out = flow.on_location(uid, *pos, live_period=28800, date=core.now())
        self.assertIn("онлайн", texts(out, uid)[0])

    def test_full_ride(self):
        flow.on_start(ADMIN, "Админ")
        self._driver(D1, "Асан", NEAR)
        self._driver(D2, "Үсөн", FAR)
        core.add_tx(D1, 1000, "topup")

        # жүргүнчү
        self.assertIn("Тилди", texts(flow.on_start(P, "Айгүл"))[0])
        flow.on_button(P, "lang:ky")
        flow.on_text(P, "🚕 Такси чакыруу")
        out = flow.on_contact(P, "996555111222")
        self.assertIn("Кайдан", texts(out)[0])
        flow.on_location(P, *KARAKOL)
        out = flow.on_location(P, *DEST)
        self.assertIn("Каракол", texts(out)[0])
        self.assertIn("сом", texts(out)[0])
        out = flow.on_button(P, "ord:ok")
        rid = core.active_ride_of(P)["id"]

        # dispatch: эң жакын айдоочу (Асан) биринчи алат, Үсөн 5 км'ден ары
        out = dispatch.tick()
        self.assertEqual(btn(out, D1, "acc:"), "acc:%d" % rid)
        self.assertIsNone(btn(out, D2, "acc:"))

        # экинчи айдоочу ала албайт (сунуш ага эмес)
        self.assertFalse(core.accept(rid, D2))

        out = flow.on_button(D1, "acc:%d" % rid)
        self.assertIn("Айдоочу табылды", "".join(texts(out, P)))
        self.assertTrue(any(o.get("location") for o in out if o["to"] == D1))
        self.assertEqual(core.get_driver(D1)["busy_ride"], rid)

        flow.on_button(D1, "arr:%d" % rid)
        flow.on_button(D1, "go:%d" % rid)
        out = flow.on_button(D1, "fin:%d" % rid)
        self.assertEqual(core.get_ride(rid)["status"], "completed")
        price = core.get_ride(rid)["price"]
        self.assertAlmostEqual(core.get_driver(D1)["balance"], 1000 - price * 0.10, places=2)
        self.assertIsNone(core.get_driver(D1)["busy_ride"])

        out = flow.on_button(P, "rate:%d:4" % rid)
        self.assertEqual(core.get_driver(D1)["rating"], 4.0)
        self.assertEqual(flow.on_button(P, "rate:%d:1" % rid), [])   # экинчи жолу болбойт

    def test_timeout_then_next_driver(self):
        u = "tg:5"
        flow.on_start(u, "Бакыт")
        core.set_user(u, phone="+996555000005")
        flow.on_text(u, "🚕 Такси чакыруу")
        flow.on_location(u, *KARAKOL)
        flow.on_button(u, "skipdest")
        flow.on_button(u, "ord:ok")
        rid = core.active_ride_of(u)["id"]
        # эки айдоочуну тең жакын, бош кылып коёбуз
        for d, pos in ((D1, NEAR), (D2, (42.4920, 78.3950))):
            core.set_driver(d, busy_ride=None, balance=500)
            core.driver_location(d, *pos, live_period=3600)
        first = core.get_ride(rid)
        out = dispatch.tick()
        offered = core.get_ride(rid)["offered_to"]
        self.assertIn(offered, (D1, D2))
        # мөөнөт өттү
        core.query("UPDATE rides SET offered_at=? WHERE id=?", (core.now() - 60, rid))
        out = dispatch.tick()
        self.assertIn("убактысы өттү", "".join(texts(out, offered)))
        other = D2 if offered == D1 else D1
        self.assertEqual(core.get_ride(rid)["offered_to"], other)
        # жүргүнчү жокко чыгарат
        out = flow.on_button(u, "pcx:%d" % rid)
        self.assertEqual(core.get_ride(rid)["status"], "cancelled")
        self.assertIsNotNone(first)

    def test_no_driver_after_max(self):
        u = "tg:6"
        flow.on_start(u, "Нурлан")
        core.set_user(u, phone="+996555000006")
        flow.on_text(u, "🚕 Такси чакыруу")
        flow.on_location(u, 40.5283, 72.7985)   # Ош — айдоочу жок
        flow.on_button(u, "skipdest")
        flow.on_button(u, "ord:ok")
        rid = core.active_ride_of(u)["id"]
        core.query("UPDATE rides SET created_at=? WHERE id=?", (core.now() - 999, rid))
        out = dispatch.tick()
        self.assertIn("табылган жок", "".join(texts(out, u)))
        self.assertEqual(core.get_ride(rid)["status"], "cancelled")

    def test_outside_city(self):
        u = "tg:7"
        flow.on_start(u, "Т")
        core.set_user(u, phone="+996555000007")
        flow.on_text(u, "🚕 Такси чакыруу")
        flow.on_location(u, 41.0, 78.0)
        out = flow.on_button(u, "skipdest")
        self.assertIn("иштебейт", texts(out)[0])

    def test_topup(self):
        core.set_state(D2, {})
        flow.on_text(D2, "➕ Балансты толуктоо")
        out = flow.on_photo(D2, "FILEID")
        data = btn(out, ADMIN, "top:")
        before = core.get_driver(D2)["balance"]
        tx = data.split(":")[1]
        flow.on_button(ADMIN, "top:%s:500" % tx)
        flow.on_button(ADMIN, "top:%s:500" % tx)            # экинчи жолу кошулбайт
        self.assertEqual(core.get_driver(D2)["balance"], before + 500)

    def test_quote(self):
        q = core.quote(*KARAKOL, *DEST)
        self.assertEqual(q["city"], "Каракол")
        self.assertGreaterEqual(q["price"], 100)
        self.assertEqual(q["price"] % 10, 0)


if __name__ == "__main__":
    unittest.main()


class Web(unittest.TestCase):
    def test_phone_uid(self):
        self.assertEqual(core.phone_uid("0555 111 222"), "ph:+996555111222")
        self.assertEqual(core.phone_uid("+996 555 111 222"), "ph:+996555111222")
        self.assertIsNone(core.phone_uid("123"))

    def test_session_verify_needs_same_phone(self):
        core.init_db()
        tok = core.web_session_new("0700 999 888", "Жаңыл")
        self.assertIsNone(core.web_session_verify(tok, "+996700000000"))
        self.assertEqual(core.web_session_verify(tok, "996700999888"), "ph:+996700999888")
        self.assertTrue(core.web_session(tok)["verified"])

    def test_telegram_confirms_web_login(self):
        tok = core.web_session_new("0700 111 333", "Мирлан")
        out = flow.on_text("tg:77", "/start web_" + tok, "Мирлан")
        self.assertTrue(any(b.get("contact") for o in out for r in o.get("keyboard", []) for b in r))
        out = flow.on_contact("tg:77", "996700111333")
        self.assertIn("ырасталды", out[0]["text"])
        self.assertEqual(core.web_session(tok)["uid"], "ph:+996700111333")


class DriverWeb(unittest.TestCase):
    def test_driver_login_and_state(self):
        import web
        core.init_db()
        core.ensure_user("tg:88", "Эрлан"); core.set_user("tg:88", phone="+996700888888")
        core.add_driver("tg:88", "Honda Fit", "Көк", "08 888 KG")
        core.set_driver("tg:88", status="active")
        self.assertEqual(core.driver_by_phone("0700 888 888"), "tg:88")
        self.assertIsNone(core.driver_by_phone("0700 000 001"))
        tok = core.web_session_new("0700 888 888", "", "driver")
        self.assertEqual(core.web_session_verify(tok, "996700888888"), "tg:88")
        core.driver_location("tg:88", *NEAR, live_period=60)
        st = web.driver_state("tg:88")
        self.assertTrue(st["online"])
        self.assertIsNone(st["offer"])
        self.assertEqual(st["today"]["rides"], 0)
