#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Такси ТАП! — сайт «оозу» (жүргүнчүнүн бети + JSON API).

Тышкы китепкана талап кылынбайт: стандарттык http.server.
bot.py ичинде өзүнчө агым катары иштейт (бир процесс, бир база,
бир dispatch). Жергиликтүү сыноо үчүн өзүнчө да иштейт:

    WEB_DEV_LOGIN=1 python web.py     # Telegram'сыз, номер ырастоосуз

Railway: PORT өзгөрмөсүн өзү берет; Networking → Generate Domain.
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

# Жүргүнчүгө ачык маалымат гана: айдоочунун балансы, uid ж.б. чыкпайт.
PUBLIC_STATUS = ("searching", "accepted", "arrived", "in_trip", "completed", "cancelled")


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


def ride_view(r):
    """Сапар жүргүнчүнүн көзү менен."""
    if not r:
        return None
    v = {k: r[k] for k in ("id", "status", "city", "price", "dist_km", "surge",
                           "p_lat", "p_lon", "d_lat", "d_lon", "cancel_by")}
    v["rated"] = core.rated(r["id"])
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


class H(BaseHTTPRequestHandler):
    server_version = "TaxiTap"

    def log_message(self, *a):
        pass

    # ---------- жардамчылар ----------

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

    def _file(self, path):
        if not os.path.isfile(path):
            return self._json({"error": "not_found"}, 404)
        data = open(path, "rb").read()
        self.send_response(200)
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype.endswith(("javascript", "json")):
            ctype += "; charset=utf-8"
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0 or n > 20000:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode() or "{}")
        except ValueError:
            return {}

    def _token(self):
        c = SimpleCookie(self.headers.get("Cookie") or "")
        return c[COOKIE].value if COOKIE in c else None

    def _uid(self):
        s = core.web_session(self._token())
        return s["uid"] if s and s["verified"] else None

    # ---------- маршруттар ----------

    def do_GET(self):
        try:
            u = urlparse(self.path)
            if u.path in ("/", "/index.html"):
                return self._file(os.path.join(STATIC, "rider.html"))
            if u.path.startswith("/static/"):
                name = os.path.basename(u.path)
                return self._file(os.path.join(STATIC, name))
            if u.path == "/health":
                return self._json({"ok": True})
            if u.path == "/api/config":
                return self._json({"dev": DEV_LOGIN, "bot": BOT_USERNAME,
                                   "cities": core.CITIES})
            if u.path == "/api/me":
                s = core.web_session(self._token())
                if not s:
                    return self._json({"auth": False})
                if not s["verified"]:
                    return self._json({"auth": False, "pending": True,
                                       "link": self._tg_link(s["token"])})
                user = core.get_user(s["uid"]) or {}
                return self._json({"auth": True, "name": user.get("name"),
                                   "phone": user.get("phone")})
            if u.path == "/api/ride":
                uid = self._uid()
                if not uid:
                    return self._json({"error": "auth"}, 401)
                return self._json({"ride": ride_view(core.last_ride_of(uid))})
            if u.path == "/api/near":
                q = parse_qs(u.query)
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
                return self._json({"drivers": pts, "eta_min": eta,
                                   "city": core.city_of(*p)})
            return self._json({"error": "not_found"}, 404)
        except Exception:
            traceback.print_exc()
            return self._json({"error": "server"}, 500)

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
            if path == "/api/quote":
                p, d = _point(b.get("p")), _point(b.get("d"))
                if not p:
                    return self._json({"error": "bad_point"}, 400)
                q = core.quote(p[0], p[1], *(d or (None, None)))
                if not q["city"]:
                    return self._json({"error": "no_city"})
                t = q["tariff"]
                return self._json({"city": q["city"], "price": q["price"],
                                   "dist_km": q["dist_km"], "surge": q["surge"],
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
                deliver(flow.passenger_cancel(uid, r["id"]))
                return self._json({"ride": ride_view(core.get_ride(r["id"]))})
            if path == "/api/rate":
                rid, stars = int(b.get("id") or 0), int(b.get("stars") or 0)
                ok = core.rate(rid, uid, max(1, min(5, stars)))
                return self._json({"ok": ok})
            return self._json({"error": "not_found"}, 404)
        except Exception:
            traceback.print_exc()
            return self._json({"error": "server"}, 500)

    def _tg_link(self, tok):
        return "https://t.me/%s?start=web_%s" % (BOT_USERNAME, tok) if BOT_USERNAME else None

    def _login(self, b):
        phone = str(b.get("phone") or "")[:20]
        name = str(b.get("name") or "").strip()[:40]
        if not core.phone_uid(phone):
            return self._json({"error": "bad_phone"}, 400)
        tok = core.web_session_new(phone, name)
        if DEV_LOGIN:
            core.web_session_verify(tok)
            return self._json({"auth": True}, cookie=tok)
        return self._json({"auth": False, "pending": True, "link": self._tg_link(tok)},
                          cookie=tok)


# Out'тор: Telegram'дагы колдонуучуларга bot.py жөнөтөт. Сайттагы жүргүнчү
# абалын /api/ride аркылуу өзү окуйт, ошондуктан 'ph:' билдирүүлөрү ташталат.
deliver = lambda outs: None   # noqa: E731  — bot.py өзүнүкүн коёт


def start(port=None):
    port = int(port or os.environ.get("PORT") or 8000)
    srv = ThreadingHTTPServer(("0.0.0.0", port), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    print("  Сайт: http://0.0.0.0:%d%s" % (port, "  (DEV кирүү)" if DEV_LOGIN else ""),
          flush=True)
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
