#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Такси ТАП! — сайт: жүргүнчү (/), айдоочу (/driver), админ (/admin) + JSON API.

Аккаунт = телефон номери ('ph:+996...'). Номер Telegram бот аркылуу бир жолу
ырасталат; андан кийин бардык иш ушул сайтта.

Тышкы китепкана талап кылынбайт: стандарттык http.server.
bot.py ичинде агым катары иштейт. Жергиликтүү сыноо (Telegram'сыз):

    WEB_DEV_LOGIN=1 ADMIN_PHONES=0700123456 python web.py
"""

import json
import mimetypes
import os
import threading
import time
import traceback
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import core
import flow

STATIC = os.path.join(core.BASE, "static")
DEV_LOGIN = os.environ.get("WEB_DEV_LOGIN") == "1"
BOT_USERNAME = (os.environ.get("BOT_USERNAME") or "").lstrip("@")
COOKIE = "tt"
MAX_BODY = 9 * 1024 * 1024          # 3 документ (браузерде кичирейтилген)
PAGES = {"/": "rider.html", "/index.html": "rider.html",
         "/driver": "driver.html", "/driver/": "driver.html",
         "/admin": "admin.html", "/admin/": "admin.html"}

# Out'торду жеткирүүчү: bot.py өзүнүкүн коёт (Telegram). Сайт өзү абалды окуйт.
deliver = lambda outs: None   # noqa: E731


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _point(v):
    if not isinstance(v, (list, tuple)) or len(v) != 2:
        return None
    lat, lon = _num(v[0]), _num(v[1])
    if lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return lat, lon


def _txt(v, n=60):
    return str(v or "").strip()[:n]


# ==================== Көрүнүштөр ====================

def ride_view(r):
    """Сапар жүргүнчүнүн көзү менен."""
    if not r:
        return None
    v = {k: r[k] for k in ("id", "status", "city", "price", "dist_km", "surge",
                           "p_lat", "p_lon", "d_lat", "d_lon", "cancel_by")}
    v["rated"] = core.rated(r["id"])
    v["cancel_by_me"] = r["cancel_by"] == r["passenger"]
    if r["status"] == "searching":
        v["search_sec"] = int(core.now() - (r["created_at"] or core.now()))
        v["search_max"] = int(core.SEARCH_MAX_SEC)
    if r["driver"] and r["status"] in ("accepted", "arrived", "in_trip", "completed"):
        d = core.get_driver(r["driver"]) or {}
        du = core.get_user(r["driver"]) or {}
        v["driver"] = {"name": du.get("name") or "", "phone": du.get("phone") or "",
                       "rating": d.get("rating"), "car": d.get("car_model"),
                       "color": d.get("car_color"), "plate": d.get("car_plate")}
        if r["status"] != "completed" and d.get("lat") is not None:
            v["driver"]["pos"] = [d["lat"], d["lon"]]
            if r["status"] == "accepted":
                km = core.road_km(d["lat"], d["lon"], r["p_lat"], r["p_lon"])
                v["driver"]["eta_min"] = max(1, round(km / core.AVG_SPEED_KMH * 60))
    return v


def driver_state(uid):
    """Айдоочунун бети бардык абалын ушул бир суроо менен алат."""
    d = core.get_driver(uid) or {}
    u = core.get_user(uid) or {}
    t = core.now()
    st = {"name": u.get("name"), "phone": u.get("phone"), "status": d.get("status"),
          "reject_note": d.get("reject_note"),
          "car_model": d.get("car_model"), "car_color": d.get("car_color"),
          "car_plate": d.get("car_plate"),
          "online": bool(d and (core.is_available(d) or d.get("busy_ride"))),
          "balance": int(d.get("balance") or 0), "min_balance": core.MIN_BALANCE,
          "rating": d.get("rating"), "rides_done": d.get("rides_done"),
          "today": core.driver_today(uid) if d else {"rides": 0, "earned": 0},
          "offer": None, "ride": None, "pay_info": core.PAY_INFO,
          "notify": bool(u.get("notify", 1)), "tg": bool(u.get("tg_uid")),
          "pending_topup": bool(d and core.query(
              "SELECT id FROM balance_tx WHERE driver=? AND status='pending'", (uid,), "one"))}
    o = core.offer_for(uid) if d else None
    if o and d.get("lat") is not None:
        st["offer"] = {"id": o["id"], "price": o["price"], "dist_km": o["dist_km"],
                       "to_pickup_km": round(core.haversine_km(d["lat"], d["lon"],
                                                               o["p_lat"], o["p_lon"]), 1),
                       "has_dest": o["d_lat"] is not None,
                       "left": max(0, int(core.OFFER_SEC - (t - (o["offered_at"] or t)))),
                       "total": int(core.OFFER_SEC)}
    if d.get("busy_ride"):
        r = core.get_ride(d["busy_ride"])
        if r and r["status"] in ("accepted", "arrived", "in_trip"):
            p = core.get_user(r["passenger"]) or {}
            st["ride"] = {"id": r["id"], "status": r["status"], "price": r["price"],
                          "dist_km": r["dist_km"], "passenger": p.get("name") or "",
                          "phone": p.get("phone") or "", "p": [r["p_lat"], r["p_lon"]],
                          "d": [r["d_lat"], r["d_lon"]] if r["d_lat"] is not None else None}
    return st


# ==================== HTTP ====================

class H(BaseHTTPRequestHandler):
    server_version = "TaxiTap"

    def log_message(self, *a):
        pass

    def _json(self, obj, code=200, cookie=None):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        if cookie is not None:
            self.send_header("Set-Cookie", "%s=%s; Path=/; Max-Age=%d; HttpOnly; SameSite=Lax"
                             % (COOKIE, cookie, 31536000 if cookie else 0))
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path, private=False):
        if not path or not os.path.isfile(path):
            return self._json({"error": "not_found"}, 404)
        data = open(path, "rb").read()
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype.endswith(("javascript", "json")):
            ctype += "; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "private, max-age=3600" if private else "no-cache")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0 or n > MAX_BODY:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode() or "{}")
        except ValueError:
            return {}

    def _session(self):
        c = SimpleCookie(self.headers.get("Cookie") or "")
        return core.web_session(c[COOKIE].value if COOKIE in c else None)

    def _uid(self):
        s = self._session()
        return s["uid"] if s and s["verified"] else None

    def _tg_link(self, tok):
        return "https://t.me/%s?start=web_%s" % (BOT_USERNAME, tok) if BOT_USERNAME else None

    # ---------- GET ----------

    def do_GET(self):
        try:
            u = urlparse(self.path)
            q = parse_qs(u.query)
            if u.path in PAGES:
                return self._file(os.path.join(STATIC, PAGES[u.path]))
            if u.path.startswith("/static/"):
                return self._file(os.path.join(STATIC, os.path.basename(u.path)))
            if u.path == "/health":
                return self._json({"ok": True})
            if u.path == "/api/me":
                return self._me()
            if u.path == "/api/near":
                return self._near(q)
            uid = self._uid()
            if not uid:
                return self._json({"error": "auth"}, 401)
            if u.path == "/api/ride":
                return self._json({"ride": ride_view(core.last_ride_of(uid))})
            if u.path == "/api/d/state":
                return self._json(driver_state(uid))
            if u.path == "/api/d/history":
                return self._json({"rides": core.driver_history(uid)})
            if u.path.startswith("/api/a/"):
                if not core.is_admin(uid):
                    return self._json({"error": "auth"}, 401)
                return self._admin_get(u.path[7:], q)
            return self._json({"error": "not_found"}, 404)
        except Exception:
            traceback.print_exc()
            return self._json({"error": "server"}, 500)

    def _me(self):
        s = self._session()
        if not s:
            return self._json({"auth": False, "bot": BOT_USERNAME})
        if not s["verified"]:
            return self._json({"auth": False, "pending": True, "link": self._tg_link(s["token"])})
        u = core.get_user(s["uid"]) or {}
        d = core.get_driver(s["uid"])
        return self._json({"auth": True, "name": u.get("name"), "phone": u.get("phone"),
                           "driver": d["status"] if d else None,
                           "admin": core.is_admin(s["uid"]),
                           "notify": bool(u.get("notify", 1)), "tg": bool(u.get("tg_uid")),
                           "bot": BOT_USERNAME})

    def _near(self, q):
        p = _point([(q.get("lat") or [None])[0], (q.get("lon") or [None])[0]])
        if not p:
            return self._json({"error": "bad_point"}, 400)
        pts, best = [], None
        for d in core.online_drivers():
            km = core.haversine_km(p[0], p[1], d["lat"], d["lon"])
            if km <= 5:
                pts.append([round(d["lat"], 4), round(d["lon"], 4)])
                best = km if best is None else min(best, km)
        eta = None if best is None else max(1, round(best * core.ROAD_FACTOR
                                                     / core.AVG_SPEED_KMH * 60))
        return self._json({"drivers": pts, "eta_min": eta, "city": core.city_of(*p)})

    # ---------- POST ----------

    def do_POST(self):
        try:
            path = urlparse(self.path).path
            b = self._body()
            if path == "/api/login":
                return self._login(b)
            if path == "/api/logout":
                return self._json({"ok": True}, cookie="")
            uid = self._uid()
            if not uid:
                return self._json({"error": "auth"}, 401)
            if path == "/api/notify":
                core.set_user(uid, notify=1 if b.get("on") else 0)
                return self._json({"ok": True})
            if path.startswith("/api/d/"):
                return self._driver_post(uid, path[7:], b)
            if path.startswith("/api/a/"):
                if not core.is_admin(uid):
                    return self._json({"error": "auth"}, 401)
                return self._admin_post(uid, path[7:], b)
            return self._rider_post(uid, path, b)
        except Exception:
            traceback.print_exc()
            return self._json({"error": "server"}, 500)

    def _login(self, b):
        phone, name = _txt(b.get("phone"), 20), _txt(b.get("name"), 40)
        kind = b.get("kind") if b.get("kind") in ("rider", "driver", "admin") else "rider"
        if not core.phone_uid(phone):
            return self._json({"error": "bad_phone"}, 400)
        tok = core.web_session_new(phone, name, kind)
        if DEV_LOGIN:
            if not core.web_session_verify(tok):
                return self._json({"error": "not_admin"}, 403)
            return self._json({"auth": True}, cookie=tok)
        return self._json({"auth": False, "pending": True, "link": self._tg_link(tok)},
                          cookie=tok)

    def _rider_post(self, uid, path, b):
        if path == "/api/quote":
            p, d = _point(b.get("p")), _point(b.get("d"))
            if not p:
                return self._json({"error": "bad_point"}, 400)
            q = core.quote(p[0], p[1], *(d or (None, None)))
            if not q["city"]:
                return self._json({"error": "no_city"})
            t = q["tariff"]
            return self._json({"city": q["city"], "price": q["price"], "dist_km": q["dist_km"],
                               "surge": q["surge"],
                               "tariff": {k: t[k] for k in ("base", "per_km", "min_price")}})
        if path == "/api/order":
            p, d = _point(b.get("p")), _point(b.get("d"))
            if not p:
                return self._json({"error": "bad_point"}, 400)
            if core.active_ride_of(uid):
                return self._json({"error": "have_active"}, 409)
            q = core.quote(p[0], p[1], *(d or (None, None)))
            if not q["city"]:
                return self._json({"error": "no_city"}, 400)
            rid = core.create_ride(uid, q, p[0], p[1], *(d or (None, None)))
            return self._json({"ride": ride_view(core.get_ride(rid))})
        if path == "/api/cancel":
            r = core.active_ride_of(uid)
            if not r or r["passenger"] != uid:
                return self._json({"error": "no_ride"}, 404)
            outs = flow.passenger_cancel(uid, r["id"])
            if outs is None:
                return self._json({"error": "cant_cancel"}, 409)
            deliver(outs)
            return self._json({"ride": ride_view(core.get_ride(r["id"]))})
        if path == "/api/rate":
            rid, stars = int(b.get("id") or 0), int(b.get("stars") or 0)
            return self._json({"ok": core.rate(rid, uid, max(1, min(5, stars)))})
        return self._json({"error": "not_found"}, 404)

    # ---------- айдоочу ----------

    def _driver_post(self, uid, action, b):
        d = core.get_driver(uid)
        if action == "register":
            if d and d["status"] in ("active", "blocked"):
                return self._json({"error": "already"}, 409)
            name, model = _txt(b.get("name"), 40), _txt(b.get("model"), 40)
            color, plate = _txt(b.get("color"), 20), _txt(b.get("plate"), 15).upper()
            if not (name and model and color and plate):
                return self._json({"error": "fields"}, 400)
            docs = {}
            for k in ("license", "techpass", "car"):
                docs[k] = core.save_upload(b.get(k)) if b.get(k) else (d or {}).get("doc_" + k)
                if not docs[k]:
                    return self._json({"error": "doc_" + k}, 400)
            deliver(flow.register_driver(uid, name, model, color, plate, docs))
            return self._json(driver_state(uid))
        if not d or d["status"] != "active":
            return self._json({"error": "not_active"}, 403)
        if action == "topup":
            amount = _num(b.get("amount"))
            if not amount or amount <= 0 or amount > 100000:
                return self._json({"error": "amount"}, 400)
            proof = core.save_upload(b.get("proof"))
            if not proof:
                return self._json({"error": "proof"}, 400)
            deliver(flow.request_topup(uid, amount, proof))
            return self._json(driver_state(uid))
        if action == "location":
            p = _point(b.get("p"))
            if not p:
                return self._json({"error": "bad_point"}, 400)
            if d["online"] or d["busy_ride"]:
                # Сайт ар 5 сек жиберет; 60 сек жаңыртуу келбесе — офлайн.
                core.driver_location(uid, p[0], p[1], live_period=60)
            return self._json({"ok": True})
        if action == "online":
            if b.get("on"):
                p = _point(b.get("p"))
                if not p:
                    return self._json({"error": "need_location"}, 400)
                core.driver_location(uid, p[0], p[1], live_period=60)
            else:
                core.set_driver(uid, online=0, live_until=None)
            return self._json(driver_state(uid))
        handlers = {"accept": flow.driver_accept, "decline": flow.driver_decline,
                    "step": flow.driver_step, "cancel": flow.driver_cancel}
        rid = int(b.get("id") or 0)
        if action not in handlers or not rid:
            return self._json({"error": "not_found"}, 404)
        outs = handlers[action](uid, rid)
        st = driver_state(uid)
        if outs is None:
            st["error"] = "too_late" if action == "accept" else "not_allowed"
        deliver(outs or [])
        return self._json(st)

    # ---------- админ ----------

    def _admin_get(self, action, q):
        if action == "overview":
            return self._json(core.admin_overview())
        if action == "drivers":
            t = core.now()
            rows = core.admin_drivers()
            for d in rows:
                d["is_online"] = bool(d["busy_ride"]) or core.is_available(d, t)
            return self._json({"drivers": rows})
        if action == "rides":
            return self._json({"rides": core.admin_rides()})
        if action == "tariffs":
            return self._json({"tariffs": core.all_tariffs()})
        if action == "file":
            return self._file(core.upload_path((q.get("n") or [""])[0]), private=True)
        return self._json({"error": "not_found"}, 404)

    def _admin_post(self, admin, action, b):
        if action == "driver":
            target = _txt(b.get("uid"), 40)
            if not core.get_driver(target):
                return self._json({"error": "no_driver"}, 404)
            deliver(flow.admin_driver(target, b.get("action"), _txt(b.get("reason"), 200)))
            return self._json({"ok": True})
        if action == "topup":
            amount = None if b.get("reject") else _num(b.get("amount"))
            if not b.get("reject") and not (amount and amount > 0):
                return self._json({"error": "bad_amount"}, 400)
            outs = flow.admin_topup(admin, int(b.get("id") or 0), amount)
            if outs is None:
                return self._json({"error": "done_before"}, 409)
            deliver(outs)
            return self._json({"ok": True})
        if action == "balance":
            target, amount = _txt(b.get("uid"), 40), _num(b.get("amount"))
            if not core.get_driver(target) or not amount:
                return self._json({"error": "bad"}, 400)
            core.add_tx(target, amount, "manual")
            return self._json({"ok": True, "balance": core.get_driver(target)["balance"]})
        if action == "tariff":
            city = _txt(b.get("city"))
            vals = [_num(b.get(k)) for k in ("base", "per_km", "per_min", "min_price")]
            if city not in core.CITIES or any(v is None or v < 0 for v in vals):
                return self._json({"error": "bad"}, 400)
            core.set_tariff(city, *vals)
            return self._json({"ok": True})
        if action == "cancel":
            outs = flow.admin_cancel(int(b.get("id") or 0))
            if outs is None:
                return self._json({"error": "no_ride"}, 404)
            deliver(outs)
            return self._json({"ok": True})
        return self._json({"error": "not_found"}, 404)


def start(port=None):
    port = int(port or os.environ.get("PORT") or 8000)
    srv = ThreadingHTTPServer(("0.0.0.0", port), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    print("  Сайт: http://0.0.0.0:%d%s" % (port, "  (DEV кирүү)" if DEV_LOGIN else ""), flush=True)
    return srv


if __name__ == "__main__":
    import dispatch
    core.init_db()
    start()
    while True:                     # Telegram'сыз режим: dispatch ушул жерде
        try:
            dispatch.tick()
        except Exception:
            traceback.print_exc()
        time.sleep(2)
