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

import addrbook
import core
import flow
import ops

STATIC = os.path.join(core.BASE, "static")
DEV_LOGIN = os.environ.get("WEB_DEV_LOGIN") == "1"
BOT_USERNAME = (os.environ.get("BOT_USERNAME") or "").lstrip("@")
COOKIE = "tt"
MAX_BODY = 9 * 1024 * 1024          # 3 документ (браузерде кичирейтилген)
PAGES = {"/": "rider.html", "/index.html": "rider.html",
         "/driver": "driver.html", "/driver/": "driver.html",
         "/admin": "admin.html", "/admin/": "admin.html", "/terms": "terms.html"}
SITE_URL = (os.environ.get("SITE_URL") or "").rstrip("/")

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

def _wait(r):
    w = core.wait_config()
    return {"arrived_at": r.get("arrived_at"), "free_min": w["free_min"], "per_min": w["per_min"],
            "fee": r.get("wait_fee") or (core.wait_fee_for(r) if r["status"] == "arrived" else 0),
            "now": core.now()}


def _msgs(r, me):
    return [{"id": m["id"], "me": m["sender"] == me, "text": m["text"], "at": m["at"]}
            for m in core.messages(r["id"])]


def ride_view(r):
    """Сапар жүргүнчүнүн көзү менен."""
    if not r:
        return None
    v = {k: r[k] for k in ("id", "status", "city", "price", "dist_km", "surge",
                           "p_lat", "p_lon", "d_lat", "d_lon", "cancel_by")}
    v["cls"] = r.get("cls") or "econom"
    v["p_addr"], v["d_addr"] = r.get("p_addr"), r.get("d_addr")
    v["other_name"], v["other_phone"] = r.get("other_name"), r.get("other_phone")
    v["wait"] = _wait(r)
    if r["status"] in ("accepted", "arrived", "in_trip"):
        v["msgs"] = _msgs(r, r["passenger"])
    v["rated"] = core.rated(r["id"])
    v["scheduled_at"] = r.get("scheduled_at")
    v["discount"] = r.get("discount") or 0
    v["pay"] = max(0, (r["price"] or 0) - v["discount"]) if r["price"] else None
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
                km = flow.eta_km(d, r)
                v["driver"]["eta_min"] = max(1, round(km / core.AVG_SPEED_KMH * 60))
                v["chained"] = bool(d.get("busy_ride") and d["busy_ride"] != r["id"])
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
          "balance": int(d.get("balance") or 0), "min_balance": core.min_balance(),
          "tariff": core.finance_mode_text(), "pct_now": core.commission_pct(),
          "finance": core.driver_finance(uid) if d else None,
          "rating": d.get("rating"), "rides_done": d.get("rides_done"),
          "activity": d.get("activity") if d and d.get("activity") is not None else 100,
          "today": core.driver_today(uid) if d else {"rides": 0, "earned": 0},
          "offer": None, "ride": None, "next": None, "pay_info": core.PAY_INFO,
          "classes": sorted(core.driver_classes(d)) if d else [],
          "class_names": {c: x["name"] for c, x in core.class_config().items()},
          "home": {"set": d.get("home_lat") is not None, "on": bool(d.get("home_on")),
                   "left": core.home_uses_left(d) if d else 0,
                   "p": [d["home_lat"], d["home_lon"]] if d.get("home_lat") is not None else None},
          "in_area": (core.in_area(d["lat"], d["lon"]) if d and d.get("lat") is not None and core.AREA_ON else None),
          "area_name": core.AREA_CITY if core.AREA_ON else "", "area_gen": core.area_gen(),
          "bot": BOT_USERNAME,
          "notify": bool(u.get("notify", 1)), "tg": bool(u.get("tg_uid")),
          "pending_topup": bool(d and core.query(
              "SELECT id FROM balance_tx WHERE driver=? AND status='pending'", (uid,), "one"))}
    o = core.offer_for(uid) if d else None
    if o and d.get("lat") is not None:
        pu = core.get_user(o["passenger"]) or {}
        st["offer"] = {"id": o["id"], "price": o["price"], "dist_km": o["dist_km"],
                       "to_pickup_km": round(flow.eta_km(d, o) / core.ROAD_FACTOR, 1),
                       "has_dest": o["d_lat"] is not None, "note": o.get("note"),
                       "discount": o.get("discount") or 0, "cls": o.get("cls") or "econom",
                       "chained": bool(d.get("busy_ride")),
                       "p_addr": o.get("p_addr"), "d_addr": o.get("d_addr"),
                       "p_rating": pu.get("p_rating") if (pu.get("p_rated") or 0) >= 3 else None,
                       "left": max(0, int(core.OFFER_SEC - (t - (o["offered_at"] or t)))),
                       "total": int(core.OFFER_SEC)}
    if d.get("busy_ride"):
        r = core.get_ride(d["busy_ride"])
        if r and r["status"] in ("accepted", "arrived", "in_trip"):
            st["ride"] = _driver_ride(r)
    if d.get("next_ride"):
        r = core.get_ride(d["next_ride"])
        if r and r["status"] == "accepted":
            st["next"] = _driver_ride(r)
    return st


def _driver_ride(r):
    p = core.get_user(r["passenger"]) or {}
    v = {"id": r["id"], "status": r["status"], "price": r["price"],
         "dist_km": r["dist_km"], "passenger": p.get("name") or "",
         "phone": p.get("phone") or "", "p": [r["p_lat"], r["p_lon"]],
         "note": r.get("note"), "discount": r.get("discount") or 0,
         "cls": r.get("cls") or "econom", "p_addr": r.get("p_addr"), "d_addr": r.get("d_addr"),
         "other_name": r.get("other_name"), "other_phone": r.get("other_phone"),
         "p_rating": p.get("p_rating") if (p.get("p_rated") or 0) >= 3 else None,
         "wait": _wait(r), "msgs": _msgs(r, r["driver"]),
         "d": [r["d_lat"], r["d_lon"]] if r["d_lat"] is not None else None}
    return v


def track_view(r):
    """Бөлүшүлгөн шилтеме: телефон номерлери жок, жалпы маалымат гана."""
    v = {"status": r["status"], "p": [r["p_lat"], r["p_lon"]],
         "d": [r["d_lat"], r["d_lon"]] if r["d_lat"] is not None else None,
         "p_addr": r.get("p_addr"), "d_addr": r.get("d_addr")}
    if r["driver"] and r["status"] in ("accepted", "arrived", "in_trip"):
        d = core.get_driver(r["driver"]) or {}
        du = core.get_user(r["driver"]) or {}
        v["driver"] = {"name": (du.get("name") or "").split(" ")[0], "car": d.get("car_model"),
                       "color": d.get("car_color"), "plate": d.get("car_plate")}
        if d.get("lat") is not None:
            v["driver"]["pos"] = [d["lat"], d["lon"]]
    return v


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
        self.send_header("Cache-Control", "private, max-age=3600" if private else
                         "public, max-age=604800" if path.endswith((".webp", ".png", ".jpg")) else "no-cache")
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
            if u.path.startswith("/t/"):
                return self._file(os.path.join(STATIC, "track.html"))
            if u.path == "/api/track":
                r = core.ride_by_share((q.get("t") or [""])[0])
                if not r:
                    return self._json({"error": "not_found"}, 404)
                return self._json(track_view(r))
            if u.path == "/sw.js":          # service worker бүт сайтка иштеши үчүн тамырда
                return self._file(os.path.join(STATIC, "sw.js"))
            if u.path.startswith("/static/"):
                return self._file(os.path.join(STATIC, os.path.basename(u.path)))
            if u.path == "/health":
                return self._json({"ok": True})
            if u.path == "/api/me":
                return self._me()
            if u.path == "/api/area":
                return self._json(core.area_info())
            if u.path == "/api/near":
                return self._near(q)
            if u.path == "/api/rev":
                p = _point([(q.get("lat") or [""])[0], (q.get("lon") or [""])[0]])
                if not p:
                    return self._json({"error": "bad_point"}, 400)
                return self._json(addrbook.reverse(p[0], p[1]))
            if u.path == "/api/route":
                if not self._uid():
                    return self._json({"error": "auth"}, 401)
                a = _point((q.get("a") or [""])[0].split(","))
                z = _point((q.get("b") or [""])[0].split(","))
                if not a or not z:
                    return self._json({"error": "bad_point"}, 400)
                if core.haversine_km(a[0], a[1], z[0], z[1]) > 600:
                    return self._json({"error": "too_far"}, 400)
                rt = core.route(a[0], a[1], z[0], z[1])
                return self._json({"coords": rt["coords"], "km": rt["km"],
                                   "min": round(rt["min"]), "real": rt["real"]})
            uid = self._uid()
            if not uid:
                return self._json({"error": "auth"}, 401)
            if u.path == "/api/ride":
                return self._json({"ride": ride_view(core.last_ride_of(uid))})
            if u.path == "/api/places":
                pl = core.get_places(uid)
                pl["popular"] = addrbook.popular()
                return self._json(pl)
            if u.path == "/api/history":
                return self._json({"rides": core.passenger_history(uid)})
            if u.path == "/api/addr":
                near = _point([(q.get("lat") or [""])[0], (q.get("lon") or [""])[0]])
                return self._json({"items": addrbook.search_all((q.get("q") or [""])[0][:60], near)})
            if u.path == "/api/d/state":
                return self._json(driver_state(uid))
            if u.path == "/api/d/history":
                return self._json({"rides": core.driver_history(uid)})
            if u.path == "/api/d/praise":
                return self._json(core.driver_praise(uid))
            if u.path == "/api/d/daily":
                return self._json({"days": core.driver_daily(uid)})
            if u.path == "/api/d/heat":
                if not core.get_driver(uid):
                    return self._json({"error": "auth"}, 401)
                return self._json({"cells": core.demand_heat()})
            if u.path.startswith("/api/a/"):
                if not core.is_admin(uid):
                    return self._json({"error": "auth"}, 401)
                return self._admin_get(u.path[7:], q)
            return self._json({"error": "not_found"}, 404)
        except Exception:
            ops.report_error("сайт " + self.path.split("?")[0])
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
        cls = [c for c, x in core.class_config().items() if x["on"]]
        return self._json({"drivers": pts, "eta_min": eta, "city": core.city_of(*p), "classes": cls})

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
            ops.report_error("сайт " + self.path.split("?")[0])
            return self._json({"error": "server"}, 500)

    def _login(self, b):
        phone, name = _txt(b.get("phone"), 20), _txt(b.get("name"), 40)
        kind = b.get("kind") if b.get("kind") in ("rider", "driver", "admin") else "rider"
        if not core.phone_uid(phone):
            return self._json({"error": "bad_phone"}, 400)
        if kind != "admin" and not b.get("agree"):
            return self._json({"error": "terms"}, 400)
        tok = core.web_session_new(phone, name, kind, bool(b.get("agree")))
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
            if q.get("dest_out"):
                return self._json({"error": "dest_out"})
            t = q["tariff"]
            cfg = core.class_config()
            return self._json({"city": q["city"], "price": q["price"], "dist_km": q["dist_km"],
                               "minutes": q.get("minutes"), "surge": q["surge"],
                               "route": (q.get("route") or {}).get("coords"),
                               "classes": [{"id": c, "name": cfg[c]["name"], "price": pr,
                                            "min": int(t["min_price"] * cfg[c]["k"])}
                                           for c, pr in q["prices"].items()],
                               "wait": core.wait_config(),
                               "tariff": {k: t[k] for k in ("base", "per_km", "min_price")}})
        if path == "/api/promo":
            p, d = _point(b.get("p")), _point(b.get("d"))
            price = core.quote(p[0], p[1], *(d or (None, None)), cls=b.get("cls") or "econom")["price"] if p else None
            amount, err = core.check_promo(b.get("code"), uid, price)
            return self._json({"discount": amount, "error": err, "code": core.promo_norm(b.get("code"))})
        if path == "/api/order":
            p, d = _point(b.get("p")), _point(b.get("d"))
            if not p:
                return self._json({"error": "bad_point"}, 400)
            if not d:
                return self._json({"error": "need_dest"}, 400)     # баа алдын ала белгилүү болушу керек
            if core.active_ride_of(uid):
                return self._json({"error": "have_active"}, 409)
            q = core.quote(p[0], p[1], *(d or (None, None)), cls=b.get("cls") or "econom")
            if not q["city"]:
                return self._json({"error": "no_city"}, 400)
            if q.get("dest_out"):
                return self._json({"error": "dest_out"}, 400)
            other_name, other_phone = _txt(b.get("other_name"), 40) or None, None
            if b.get("other_phone"):
                ou = core.phone_uid(_txt(b.get("other_phone"), 20))
                if not ou:
                    return self._json({"error": "bad_other_phone"}, 400)
                other_phone = ou[3:]
            promo, disc = None, 0
            if b.get("promo"):
                disc, err = core.check_promo(b.get("promo"), uid, q["price"])
                if err:
                    return self._json({"error": "promo", "message": err}, 400)
                promo = core.promo_norm(b.get("promo"))
            at = _num(b.get("at"))
            if at is not None and not (core.now() + core.SCHEDULE_MIN - 120 <= at <= core.now() + core.SCHEDULE_MAX):
                return self._json({"error": "bad_time"}, 400)
            rid = core.create_ride(uid, q, p[0], p[1], *(d or (None, None)), promo=promo, discount=disc,
                                   scheduled_at=at, note=_txt(b.get("note"), 200) or None,
                                   other_name=other_name, other_phone=other_phone,
                                   p_addr=_txt(b.get("p_addr"), 80) or None,
                                   d_addr=_txt(b.get("d_addr"), 80) or None if d else None)
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
        if path == "/api/place":
            p = _point(b.get("p")) if b.get("p") else None
            ok = core.set_place(uid, b.get("kind"), *(p or (None, None)), name=_txt(b.get("name"), 80))
            return self._json(core.get_places(uid) if ok else {"error": "bad"}, 200 if ok else 400)
        if path == "/api/addr_suggest":
            p = _point(b.get("p"))
            aid = addrbook.suggest(_txt(b.get("name"), 80), *(p or (None, None)), by=uid, weight=1)
            return self._json({"id": aid} if aid else {"error": "bad"}, 200 if aid else 400)
        if path == "/api/msg":
            r = core.active_ride_of(uid)
            outs = flow.send_message(uid, r["id"], _txt(b.get("text"), core.MSG_MAX)) if r else None
            if outs is None:
                return self._json({"error": "cant"}, 409)
            deliver(outs)
            return self._json({"ride": ride_view(core.get_ride(r["id"]))})
        if path == "/api/share":
            r = core.active_ride_of(uid)
            if not r or r["passenger"] != uid:
                return self._json({"error": "no_ride"}, 404)
            tok = core.share_token(r["id"])
            base = SITE_URL or ("https://" + (self.headers.get("Host") or ""))
            return self._json({"url": "%s/t/%s" % (base, tok)})
        if path == "/api/rate":
            rid, stars = int(b.get("id") or 0), int(b.get("stars") or 0)
            tags = b.get("tags") if isinstance(b.get("tags"), list) else None
            car = b.get("car_ok")
            return self._json({"ok": core.rate(rid, uid, max(1, min(5, stars)), tags=tags,
                                               comment=b.get("comment") if isinstance(b.get("comment"), str) else None,
                                               car_ok=None if car is None else bool(car))})
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
        if action == "sos":
            p = _point(b.get("p"))
            deliver(flow.driver_sos(uid, p))
            return self._json({"ok": True})
        if action == "msg":
            outs = flow.send_message(uid, int(b.get("id") or 0), _txt(b.get("text"), core.MSG_MAX))
            if outs is None:
                return self._json({"error": "cant"}, 409)
            deliver(outs)
            return self._json(driver_state(uid))
        if action == "rate":
            stars = max(1, min(5, int(b.get("stars") or 0)))
            return self._json({"ok": core.rate_passenger(int(b.get("id") or 0), uid, stars)})
        if action == "addr_suggest":
            p = _point(b.get("p"))
            aid = addrbook.suggest(_txt(b.get("name"), 80), *(p or (None, None)), by=uid, weight=2,
                                   kind=b.get("kind") or "poi")
            return self._json({"id": aid} if aid else {"error": "bad"}, 200 if aid else 400)
        if action == "home_set":
            p = _point(b.get("p"))
            if not p:
                return self._json({"error": "bad_point"}, 400)
            core.set_driver(uid, home_lat=p[0], home_lon=p[1])
            return self._json(driver_state(uid))
        if action == "home":
            if not core.set_home_mode(uid, bool(b.get("on"))):
                return self._json(dict(driver_state(uid), error="home_limit"))
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
        if action == "addr":
            return self._json({"items": addrbook.admin_list((q.get("q") or [""])[0][:60],
                                                            only=(q.get("only") or [""])[0] or None),
                               "count": addrbook.count(), "import": addrbook.import_state,
                               "dgis": dict(addrbook.dgis_state, on=bool(addrbook.DGIS_KEY)),
                               "kinds": {k: {"icon": v[0], "name": v[1]} for k, v in addrbook.KINDS.items()}})
        if action == "drivers":
            t = core.now()
            rows = core.admin_drivers()
            for d in rows:
                d["is_online"] = bool(d["busy_ride"]) or core.is_available(d, t)
            return self._json({"drivers": rows})
        if action == "rides":
            return self._json({"rides": core.admin_rides()})
        if action == "lost":
            return self._json({"lost": core.lost_orders(int((q.get("days") or ["7"])[0]))})
        if action == "promos":
            return self._json({"promos": core.list_promos()})
        if action == "tariffs":
            return self._json({"tariffs": core.all_tariffs(), "classes": core.class_config(),
                               "wait": core.wait_config()})
        if action == "finance":
            return self._json(core.admin_finance())
        if action == "backup":
            path = ops.backup()
            data = open(path, "rb").read()
            self.send_response(200)
            self.send_header("Content-Type", "application/gzip")
            self.send_header("Content-Disposition", 'attachment; filename="%s"' % os.path.basename(path))
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return None
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
        if action == "addr":
            p = _point(b.get("p"))
            aid = addrbook.save(_txt(b.get("name"), 80), b.get("kind") or "poi", *(p or (None, None)),
                                aliases=_txt(b.get("aliases"), 200), area=_txt(b.get("area"), 60),
                                aid=int(b.get("id") or 0) or None)
            return self._json({"id": aid} if aid else {"error": "bad"}, 200 if aid else 400)
        if action == "addr_approve":
            addrbook.approve(int(b.get("id") or 0))
            return self._json({"ok": True})
        if action == "addr_hide":
            addrbook.set_hidden(int(b.get("id") or 0), bool(b.get("hidden")))
            return self._json({"ok": True})
        if action == "addr_delete":
            addrbook.delete(int(b.get("id") or 0))
            return self._json({"ok": True})
        if action == "addr_import":
            threading.Thread(target=addrbook.import_osm, daemon=True).start()
            return self._json({"ok": True})
        if action == "classes":
            if not core.set_class_config(b.get("classes")):
                return self._json({"error": "bad"}, 400)
            return self._json({"classes": core.class_config()})
        if action == "wait":
            if not core.set_wait_config(_num(b.get("free_min")), _num(b.get("per_min"))):
                return self._json({"error": "bad"}, 400)
            return self._json({"wait": core.wait_config()})
        if action == "driver_classes":
            target = _txt(b.get("uid"), 40)
            cl = [c for c in (b.get("classes") or []) if c in core.CLASSES]
            if not core.get_driver(target) or not cl:
                return self._json({"error": "bad"}, 400)
            core.set_driver(target, classes=",".join(cl))
            return self._json({"ok": True})
        if action == "promo":
            ok = core.save_promo(_txt(b.get("code"), 20), _num(b.get("amount")) or 0,
                                 bool(b.get("first_only")), int(_num(b.get("max_uses")) or 0),
                                 _txt(b.get("expires"), 10) or None, b.get("active", True) is not False)
            if not ok:
                return self._json({"error": "bad"}, 400)
            return self._json({"promos": core.list_promos()})
        if action == "order":
            # Диспетчер: телефон аркылуу келген заказ
            phone, name, note = _txt(b.get("phone"), 20), _txt(b.get("name"), 40), _txt(b.get("note"), 200)
            uid = core.phone_uid(phone)
            p, d = _point(b.get("p")), _point(b.get("d"))
            if not uid:
                return self._json({"error": "bad_phone"}, 400)
            if not p:
                return self._json({"error": "bad_point"}, 400)
            if not d:
                return self._json({"error": "need_dest"}, 400)
            if core.active_ride_of(uid):
                return self._json({"error": "have_active"}, 409)
            q = core.quote(p[0], p[1], *(d or (None, None)))
            if not q["city"]:
                return self._json({"error": "no_city"}, 400)
            if q.get("dest_out"):
                return self._json({"error": "dest_out"}, 400)
            u = core.ensure_user(uid, name)
            core.set_user(uid, phone=uid[3:], **({"name": name} if name and not u.get("name") else {}))
            rid = core.create_ride(uid, q, p[0], p[1], *(d or (None, None)), note=note or None,
                                   source="phone")
            return self._json({"ride": ride_view(core.get_ride(rid))})
        if action == "quote":
            p, d = _point(b.get("p")), _point(b.get("d"))
            if not p:
                return self._json({"error": "bad_point"}, 400)
            q = core.quote(p[0], p[1], *(d or (None, None)))
            return self._json({"city": q["city"], "price": q["price"], "dist_km": q["dist_km"],
                               "dest_out": bool(q.get("dest_out"))})
        if action == "finance":
            pct, mb = _num(b.get("percent")), _num(b.get("min_balance") or 0)
            fu = _txt(b.get("free_until"), 10) or None
            if pct is None or mb is None or not core.set_finance_config(pct, fu, mb):
                return self._json({"error": "bad"}, 400)
            return self._json(core.admin_finance())
        if action == "area_sel":
            r = core.set_area_units(b.get("units") or [])
            if r.get("error"):
                return self._json(r, 400)
            return self._json(dict(core.area_info(), result=r))
        if action == "area":
            if b.get("reset"):
                core.reset_area()
                threading.Thread(target=core.load_area, daemon=True).start()
                return self._json(core.area_info())
            if not core.set_custom_area(b.get("points")):
                return self._json({"error": "bad_points"}, 400)
            return self._json(core.area_info())
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
    threading.Thread(target=core.load_area, daemon=True).start()
    threading.Thread(target=addrbook.ensure_seeded, daemon=True).start()
    start()
    while True:                     # Telegram'сыз режим: dispatch ушул жерде
        try:
            dispatch.tick()
        except Exception:
            traceback.print_exc()
        time.sleep(2)
