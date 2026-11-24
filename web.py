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
import re
import mimetypes
import os
import threading
import time
import traceback
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, unquote, urlparse

import addrbook
import maptiles
import parks
import core
import flow
import ops

STATIC = os.path.join(core.BASE, "static")
BUILD_VER = (os.environ.get("RAILWAY_GIT_COMMIT_SHA") or os.environ.get("RAILWAY_DEPLOYMENT_ID") or str(int(time.time())))[:12]
DEV_LOGIN = os.environ.get("WEB_DEV_LOGIN") == "1"
BOT_USERNAME = (os.environ.get("BOT_USERNAME") or "").lstrip("@")
COOKIE = "tt"
MAX_BODY = 9 * 1024 * 1024          # 3 документ (браузерде кичирейтилген)
PAGES = {"/": "rider.html", "/index.html": "rider.html",
         "/driver": "driver.html", "/driver/": "driver.html",
         "/admin": "admin.html", "/admin/": "admin.html", "/terms": "terms.html",
         "/park": "park.html", "/park/": "park.html"}
SITE_URL = (os.environ.get("SITE_URL") or "").rstrip("/")

# Out'торду жеткирүүчү: bot.py өзүнүкүн коёт (Telegram). Сайт өзү абалды окуйт.
deliver = lambda outs: None   # noqa: E731


def _e(s):
    return str(s if s is not None else "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def act_html(a):
    """Акт салыштыруу — басып чыгаруу / PDF катары сактоо үчүн бет."""
    d = a["data"]
    fm = lambda v: "{:,}".format(int(round(v or 0))).replace(",", " ")    # noqa: E731
    dt = lambda t: time.strftime("%d.%m.%Y", time.gmtime((t or 0) + core.TZ))    # noqa: E731
    st = {"sent": "Жооп күтүлүүдө", "ok": "✅ Парк ырастады " + (dt(a.get("answered_at")) if a.get("answered_at") else ""),
          "dispute": "❗ Парктын пикири: " + _e(a.get("comment") or "")}[a["status"]]
    parts = "".join("<tr><td>Парктын үлүшү: %s сом комиссиядан %g%%</td><td>%s</td></tr>" % (fm(x["fee"]), x["rate"], fm(x["fee"] * x["rate"] / 100))
                    for x in d.get("parts") or [])
    pays = "".join("<tr><td>%s · %s</td><td>−%s</td></tr>" % (dt(x["at"]), _e(x["note"]), fm(x["amount"])) for x in d["payouts"]) \
        or "<tr><td>Төлөм болгон жок</td><td>0</td></tr>"
    drv = "".join("<tr><td>%s</td><td>%s</td><td>%d</td><td>%s</td><td>%s</td></tr>" % (_e(x["name"]), _e(x["plate"]), x["rides"], fm(x["gross"]), fm(x["fee"]))
                  for x in d["drivers"]) or "<tr><td colspan=5>Сапар болгон жок</td></tr>"
    a_, b_ = parks.month_bounds(d["period"])
    owe = ("Такси ТАП! паркка карыз" if d["closing"] > 0 else "Парк Такси ТАП!'ка карыз" if d["closing"] < 0 else "Карыз жок")
    return f"""<!DOCTYPE html><html lang="ky"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Акт № {a['id']} · {_e(d['park'])} · {parks.period_label(d['period'])}</title>
<style>body{{font:14px/1.45 system-ui,Arial,sans-serif;color:#16161a;max-width:760px;margin:0 auto;padding:18px}}
h1{{font-size:20px;margin:0 0 4px}}h2{{font-size:15px;margin:22px 0 6px}}.mu{{color:#666}}
table{{width:100%;border-collapse:collapse}}td,th{{border-bottom:1px solid #ddd;padding:6px 4px;text-align:left}}td:last-child,th:last-child{{text-align:right}}
.tot td{{font-weight:800;background:#fff4d6}}.st{{display:inline-block;padding:4px 10px;border-radius:8px;background:#f2f2f4;margin-top:6px}}
.sig{{display:flex;gap:30px;margin-top:34px}}.sig div{{flex:1}}.sig p{{border-top:1px solid #333;padding-top:4px;margin-top:46px}}
.pr{{position:fixed;right:14px;bottom:14px;padding:12px 18px;border:0;border-radius:12px;background:#ffc21a;font-weight:800;font-size:15px}}
@media print{{.pr{{display:none}}body{{padding:0}}}}</style></head><body>
<h1>Акт салыштыруу № {a['id']}</h1>
<div class="mu">{parks.period_label(d['period'])} · {dt(a_)} – {dt(b_ - 1)} · түзүлгөн {dt(d.get('made_at'))}</div>
<p><b>1-тарап:</b> Такси ТАП! · taxi-tap<br><b>2-тарап:</b> «{_e(d['park'])}» таксопаркы · {_e(d['park_phone'])}</p>
<div class="st">{st}</div>
<h2>Эсеп</h2><table>
<tr><td>Ай башындагы калдык</td><td>{fm(d['opening'])}</td></tr>
<tr><td>Парктын айдоочулары бүтүргөн сапарлар</td><td>{d['rides']}</td></tr>
<tr><td>Айдоочулар тапкан акча</td><td>{fm(d['gross'])}</td></tr>
<tr><td>Такси ТАП! алган комиссия</td><td>{fm(d['fee'])}</td></tr>
{parts}
<tr><td>Жаңы жүргүнчү бонусу: {d['bonus_n']} × {fm(d['bonus_rate'])}</td><td>{fm(d['bonus'])}</td></tr>
<tr><td><b>Паркка тиешелүү акча (ай ичинде)</b></td><td><b>{fm(d['due'])}</b></td></tr>
{pays}
<tr class="tot"><td>Ай аягындагы калдык — {owe}</td><td>{fm(abs(d['closing']))}</td></tr></table>
<p class="mu">Бардык суммалар сом менен.</p>
<h2>Тиркеме: айдоочулар боюнча</h2><table><tr><th>Айдоочу</th><th>Номер</th><th>Сапар</th><th>Тапкан</th><th>Комиссия</th></tr>{drv}</table>
<div class="sig"><div><b>Такси ТАП!</b><p>Кол / мөөр</p></div><div><b>«{_e(d['park'])}»</b><p>Кол / мөөр</p></div></div>
<button class="pr" onclick="print()">🖨 Басып чыгаруу / PDF</button></body></html>"""


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


def _stops(raw):
    """[[lat, lon, "дарек"], ...] → эң көп 3, туура чекиттер гана."""
    out = []
    for x in (raw if isinstance(raw, list) else [])[:core.MAX_STOPS]:
        if isinstance(x, dict):
            x = (x.get("p") or [None, None]) + [x.get("addr")]
        pt = _point(x[:2]) if isinstance(x, (list, tuple)) and len(x) >= 2 else None
        if pt:
            out.append([pt[0], pt[1], _txt(x[2] if len(x) > 2 else "", 80) or ""])
    return out


def ride_view(r):
    """Сапар жүргүнчүнүн көзү менен."""
    if not r:
        return None
    v = {k: r[k] for k in ("id", "status", "city", "price", "dist_km", "surge",
                           "p_lat", "p_lon", "d_lat", "d_lon", "cancel_by")}
    v["del_size"] = _dsz(r)
    v["cls"] = r.get("cls") or "econom"
    v["stops"], v["stop_i"] = core.ride_stops(r), int(r.get("stop_i") or 0)
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
    v["cancel_reason"] = r.get("cancel_reason")
    v["requeued"] = r.get("requeued") or 0
    if r["status"] in ("accepted", "arrived") and r.get("accept_km") and r["driver"]:
        dd = core.get_driver(r["driver"]) or {}
        if dd.get("lat") is not None:
            left = core.haversine_km(dd["lat"], dd["lon"], r["p_lat"], r["p_lon"]) * core.ROAD_K
            v["came_km"] = round(max(0.0, r["accept_km"] - left), 1) if r["status"] == "accepted" else round(r["accept_km"], 1)
    if r["status"] == "searching":
        v["search_sec"] = int(core.now() - (r["created_at"] or core.now()))
        v["search_max"] = int(core.SEARCH_MAX_SEC)
    if r["driver"] and r["status"] in ("accepted", "arrived", "in_trip", "completed"):
        d = core.get_driver(r["driver"]) or {}
        du = core.get_user(r["driver"]) or {}
        v["driver"] = {"name": du.get("name") or "", "phone": du.get("phone") or "",
                       "park": parks.park_name_of_driver(r["driver"]),
                       "rating": d.get("rating"), "car": d.get("car_model"),
                       "color": d.get("car_color"), "plate": d.get("car_plate")}
        if r["status"] != "completed" and d.get("lat") is not None:
            v["driver"]["pos"] = [d["lat"], d["lon"]]
            if r["status"] == "accepted":
                km = flow.eta_km(d, r)
                v["driver"]["eta_min"] = max(1, round(km / core.AVG_SPEED_KMH * 60))
                v["chained"] = bool(d.get("busy_ride") and d["busy_ride"] != r["id"])
    return v


def _driver_qr(uid, d):
    """Парктын айдоочусуна өзүнүн QR'ы: /p/<парктын коду>-<айдоочунун белгиси>."""
    p = parks.ensure_code(parks.get(d.get("park_id"))) if d.get("park_id") else None
    if not p or not p.get("active"):
        return None
    code = p["code"] + "-" + parks.drv_tag(uid)
    return {"code": code, "link": (SITE_URL or "") + "/p/" + code, "park": p["name"],
            "stats": parks.qr_stats(p["id"], driver=uid)}


def driver_state(uid, seen=False):
    """Айдоочунун бети бардык абалын ушул бир суроо менен алат."""
    d = core.get_driver(uid) or {}
    u = core.get_user(uid) or {}
    t = core.now()
    st = {"name": u.get("name"), "phone": u.get("phone"), "status": d.get("status"),
          "reject_note": d.get("reject_note"),
          "lic_until": d.get("lic_until"), "lic_left": core.lic_days_left(d),
          "goal": int(d.get("goal") or 0) or 1000, "car_year": d.get("car_year"),
          "qr": _driver_qr(uid, d),
          "car_model": d.get("car_model"), "car_color": d.get("car_color"),
          "car_plate": d.get("car_plate"), "park": parks.park_name_of_driver(uid) if d else None, "park_self": bool((parks.get(d["park_id"]) or {}).get("self_approve")) if d and d.get("park_id") else False, "blocked_by": (d or {}).get("blocked_by") or "",
          "online": bool(d and (core.is_available(d) or d.get("busy_ride"))),
          "balance": int(d.get("balance") or 0), "min_balance": core.min_balance(),
          "tariff": core.finance_mode_text(), "pct_now": core.commission_pct(), "tax_pct": core.finance_config()["tax_pct"], "ins_pct": core.finance_config()["ins_pct"],
          "finance": core.driver_finance(uid) if d else None,
          "rating": d.get("rating"), "rides_done": d.get("rides_done"),
          "activity": d.get("activity") if d and d.get("activity") is not None else 100,
          "today": core.driver_today(uid) if d else {"rides": 0, "earned": 0},
          "photo": core.photo_state(d) if d else None,
          "offer": None, "ride": None, "next": None, "pay_info": core.PAY_INFO,
          "classes": sorted(core.driver_classes(d)) if d else [],
          "class_names": {c: x["name"] for c, x in core.class_config().items()},
          "home": {"set": d.get("home_lat") is not None, "on": bool(d.get("home_on")),
                   "left": core.home_uses_left(d) if d else 0,
                   "p": [d["home_lat"], d["home_lon"]] if d.get("home_lat") is not None else None},
          "in_area": (core.in_area_buf(d["lat"], d["lon"]) if d and d.get("lat") is not None and core.AREA_ON else None),
          "area_free": bool((d or {}).get("area_free")), "out_since": (d or {}).get("out_since"), "out_max": core.OUT_MAX_SEC,
          "near": core.area_entry(d["lat"], d["lon"])
                  if d and d.get("lat") is not None and core.AREA_ON and not core.in_area_buf(d["lat"], d["lon"]) else None,
          "area_name": core.AREA_CITY if core.AREA_ON else "", "area_gen": core.area_gen(), "area_title": core.area_title(), "area_label": core.area_label(),
          "bot": BOT_USERNAME,
          "notify": bool(u.get("notify", 1)), "tg": bool(u.get("tg_uid")),
          "pending_topup": bool(d and core.query(
              "SELECT id FROM balance_tx WHERE driver=? AND status='pending'", (uid,), "one"))}
    o = core.offer_for(uid) if d else None
    if o and seen:
        core.offer_seen(o["id"], uid)
        o = core.get_ride(o["id"]) or o
    if o and d.get("lat") is not None:
        pu = core.get_user(o["passenger"]) or {}
        st["offer"] = {"id": o["id"], "price": o["price"], "dist_km": o["dist_km"],
                       "to_pickup_km": round(flow.eta_km(d, o) / core.ROAD_FACTOR, 1),
                       "has_dest": o["d_lat"] is not None, "note": o.get("note"),
                       "discount": o.get("discount") or 0, "cls": o.get("cls") or "econom",
                       "del_size": _dsz(o),
                       "chained": bool(d.get("busy_ride")),
                       "p_addr": o.get("p_addr"), "d_addr": o.get("d_addr"),
                       "stops": len(core.ride_stops(o)),
                       "p": [o["p_lat"], o["p_lon"]] if o.get("p_lat") is not None else None,
                       "d": [o["d_lat"], o["d_lon"]] if o.get("d_lat") is not None else None,
                       "surge": round(float(o.get("surge") or 1.0), 2),
                       "p_rating": pu.get("p_rating") if (pu.get("p_rated") or 0) >= 3 else None,
                       "left": max(0, int(core.offer_deadline(o) - t)),
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


DISP_GET = {"client", "phone_rides", "disp_drivers"}        # диспетчерге уруксат берилген админ-суроолор
DISP_POST = {"order", "quote", "cancel"}


def _dsz(r):
    """Жеткирүүнүн өлчөмү айдоочу үчүн: {"ic","name","lim"} же None."""
    x = r.get("del_size") and next((y for y in core.del_sizes(True) if y["id"] == r["del_size"]), None)
    return {"ic": x["ic"], "name": x["name"], "lim": x["lim"]} if x else None


def _driver_ride(r):
    p = core.get_user(r["passenger"]) or {}
    v = {"id": r["id"], "status": r["status"], "price": r["price"],
         "dist_km": r["dist_km"], "passenger": p.get("name") or "",
         "phone": p.get("phone") or "", "p": [r["p_lat"], r["p_lon"]],
         "note": r.get("note"), "discount": r.get("discount") or 0,
         "cls": r.get("cls") or "econom", "p_addr": r.get("p_addr"), "d_addr": r.get("d_addr"),
         "del_size": _dsz(r),
         "other_name": r.get("other_name"), "other_phone": r.get("other_phone"),
         "p_rating": p.get("p_rating") if (p.get("p_rated") or 0) >= 3 else None,
         "wait": _wait(r), "msgs": _msgs(r, r["driver"]),
         "stops": core.ride_stops(r), "stop_i": int(r.get("stop_i") or 0),
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

    def _html(self, html, code=200):
        body = html.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

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
            if u.path in ("/disp", "/disp/"):         # диспетчер — «ТАП Башкаруу» тиркемесинин ичинде (бир тиркеме)
                self.send_response(302); self.send_header("Location", "/admin?disp=1"); self.send_header("Content-Length", "0")
                self.end_headers(); return
            if u.path in PAGES:
                return self._file(os.path.join(STATIC, PAGES[u.path]))
            if u.path.startswith("/t/"):
                return self._file(os.path.join(STATIC, "track.html"))
            if u.path.startswith("/p/"):           # парктын QR'ы → башкы бет + код
                raw = unquote(u.path[3:])[:30]
                p, _du = parks.scan(raw)
                loc = "/"
                if p:
                    loc = "/?ref=" + quote(raw.upper()) + ("&promo=" + quote(p["promo"]) if p.get("promo") else "")
                self.send_response(302)
                self.send_header("Location", loc)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if u.path == "/api/track":
                r = core.ride_by_share((q.get("t") or [""])[0])
                if not r:
                    return self._json({"error": "not_found"}, 404)
                return self._json(track_view(r))
            if u.path == "/sw.js":          # service worker бүт сайтка иштеши үчүн тамырда
                return self._file(os.path.join(STATIC, "sw.js"))
            if u.path.startswith("/static/"):
                return self._file(os.path.join(STATIC, os.path.basename(u.path)))
            if u.path.startswith("/av/"):          # профилдин сүрөтү (аты кокус, тизмеленбейт)
                return self._file(core.upload_path(u.path[4:]), private=True)
            if u.path == "/health":
                return self._json({"ok": True})
            if u.path == "/api/me":
                return self._me()
            if u.path == "/api/ver":
                return self._json({"v": BUILD_VER})
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
            m2 = re.match(r"^/tiles/2gis/(\d+)/(\d+)/(\d+)\.png$", u.path)
            if m2:
                body, ct, red = maptiles.fetch(*map(int, m2.groups()))
                if red:
                    self.send_response(302); self.send_header("Location", red); self.send_header("Cache-Control", "no-store")
                    self.end_headers(); return
                if not body:
                    return self._json({"error": "bad_tile"}, 404)
                self.send_response(200); self.send_header("Content-Type", ct); self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "public, max-age=86400"); self.end_headers(); self.wfile.write(body); return
            if u.path == "/api/mapcfg":
                return self._json({"p": maptiles.provider()})
            if u.path == "/api/park_name":           # каттоодо парктын кодун текшерүү
                pk = parks.by_code((q.get("code") or [""])[0])
                return self._json({"name": pk["name"], "self": bool(pk.get("self_approve"))} if pk else {"error": "not_found"},
                                  200 if pk else 404)
            if u.path == "/api/voice":
                return self._json(core.voice_state((q.get("set") or ["1"])[0]))
            mv = re.match(r"^/voice/(?:(\d)/)?(\w+)\.wav$", u.path)
            if mv:
                body = core.voice_clip(mv.group(2), mv.group(1) or 1)
                if not body:
                    return self._json({"error": "not_found"}, 404)
                self.send_response(200); self.send_header("Content-Type", "audio/wav"); self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "public, max-age=31536000, immutable"); self.end_headers(); self.wfile.write(body); return
            uid = self._uid()
            if not uid:
                return self._json({"error": "auth"}, 401)
            if u.path == "/api/ride":
                return self._json({"ride": ride_view(core.last_ride_of(uid))})
            if u.path == "/api/park/state":
                p = parks.by_owner(uid) or (parks.get(int((q.get("id") or ["0"])[0] or 0)) if core.is_admin(uid) else None)
                if not p:
                    return self._json({"error": "not_park"}, 403)
                st = parks.state(p["id"])
                st["site"] = SITE_URL
                return self._json(st)
            if u.path == "/api/park/acts":
                p = parks.by_owner(uid) or (parks.get(int((q.get("id") or ["0"])[0] or 0)) if core.is_admin(uid) else None)
                if not p:
                    return self._json({"error": "not_park"}, 403)
                return self._json({"acts": parks.acts(p["id"])})
            if u.path == "/api/park/file":
                p = parks.by_owner(uid) or (parks.get(int((q.get("id") or ["0"])[0] or 0)) if core.is_admin(uid) else None)
                fn = parks.driver_file(p["id"], (q.get("uid") or [""])[0], (q.get("k") or [""])[0]) if p else None
                if not fn:
                    return self._json({"error": "not_found"}, 404)
                return self._file(core.upload_path(fn), private=True)
            if u.path in ("/api/park/drivers", "/api/park/driver", "/api/park/map", "/park/stats.csv"):
                p = parks.by_owner(uid) or (parks.get(int((q.get("id") or ["0"])[0] or 0)) if core.is_admin(uid) else None)
                if not p:
                    return self._json({"error": "not_park"}, 403)
                per = (q.get("period") or ["week"])[0]
                if u.path == "/api/park/drivers":
                    return self._json(parks.driver_stats(p["id"], per))
                if u.path == "/api/park/map":
                    return self._json(parks.map_state(p["id"]))
                if u.path == "/api/park/driver":
                    d = parks.driver_detail(p["id"], (q.get("uid") or [""])[0])
                    return self._json(d if d else {"error": "not_found"}, 200 if d else 404)
                body = parks.stats_csv(p["id"], per).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/csv; charset=utf-8")
                self.send_header("Content-Disposition", 'attachment; filename="taxitap-%s-%s.csv"' % (p["id"], per))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if u.path.startswith("/act/"):                  # басып чыгаруучу акт (PDF катары сактаса болот)
                try:
                    a = parks.act_get(int(u.path[5:]))
                except ValueError:
                    a = None
                pk = parks.get(a["park_id"]) if a else None
                if not a or not (core.is_admin(uid) or (pk and pk.get("owner_uid") == uid)):
                    return self._json({"error": "not_found"}, 404)
                return self._html(act_html(a))
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
                vis = (q.get("vis") or ["0"])[0] == "1"
                if vis:
                    core.driver_seen(uid)
                return self._json(driver_state(uid, seen=vis))
            if u.path == "/api/d/history":
                return self._json({"rides": core.driver_history(uid)})
            if u.path == "/api/d/trip":
                try:
                    rid = int((q.get("id") or ["0"])[0])
                except ValueError:
                    rid = 0
                t = core.driver_trip(uid, rid)
                return self._json(t if t else {"error": "not_found"}, 200 if t else 404)
            if u.path == "/api/d/praise":
                return self._json(core.driver_praise(uid))
            if u.path == "/api/d/daily":
                return self._json({"days": core.driver_daily(uid)})
            if u.path == "/api/d/peers":
                if not core.get_driver(uid):
                    return self._json({"error": "auth"}, 401)
                return self._json({"peers": core.peers(uid), "km": core.PEER_KM})
            if u.path == "/api/d/hot":
                d = core.get_driver(uid)
                if not d:
                    return self._json({"error": "auth"}, 401)
                return self._json({"hot": core.hot_spot(d.get("lat"), d.get("lon"))})
            if u.path == "/api/d/heat":
                if not core.get_driver(uid):
                    return self._json({"error": "auth"}, 401)
                d = core.get_driver(uid)
                cells = [dict(zip(("lat", "lon"), core.hex_center(*key)), k=v["k"], n=v["n"])
                         for key, v in core.surge_cells().items()]
                here = core.cell_k(d.get("lat"), d.get("lon")) if d.get("lat") is not None else 1.0
                city = core.surge_k(core.city_of(d["lat"], d["lon"])) if d.get("lat") is not None else 1.0
                return self._json({"cells": cells, "r": core.HEX, "k_here": max(here, city),
                                   "k_max": max([c["k"] for c in cells] + [city])})
            if u.path.startswith("/api/a/"):
                if not core.is_admin(uid) and not (core.is_disp(uid) and u.path[7:] in DISP_GET):
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
                           "admin": core.is_admin(s["uid"]), "disp": core.is_disp(s["uid"]), "uid": s["uid"] if core.is_disp(s["uid"]) else None,
                           "admin_n": core.admin_todo() if core.is_admin(s["uid"]) else 0,
                           "inbox_n": core.inbox_unread(s["uid"]) if core.is_admin(s["uid"]) else 0,
                           "notify": bool(u.get("notify", 1)), "tg": bool(u.get("tg_uid")),
                           "avatar": core.avatar_url(u), "bot": BOT_USERNAME,
                           "park": (parks.by_owner(s["uid"]) or {}).get("name"), "ask_role": core.ask_role(s["uid"])})

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
            if path == "/api/jslog":             # телефондогу JS каталары → Railway логу (оңдоо үчүн)
                print("JSLOG", (self._uid() or "-")[:20], str(b.get("m") or "")[:400].replace("\n", " "), flush=True)
                return self._json({"ok": True})
            uid = self._uid()
            if not uid:
                return self._json({"error": "auth"}, 401)
            if path == "/api/role":                  # жаңы адам: «Жүргүнчү катары / Айдоочу катары»
                return self._json({"ok": core.set_signup_as(uid, b.get("as"))})
            if path == "/api/notify":
                core.set_user(uid, notify=1 if b.get("on") else 0)
                return self._json({"ok": True})
            if path.startswith("/api/d/"):
                return self._driver_post(uid, path[7:], b)
            if path.startswith("/api/a/"):
                if not core.is_admin(uid) and not (core.is_disp(uid) and path[7:] in DISP_POST):
                    return self._json({"error": "auth"}, 401)
                if not core.is_admin(uid) and path[7:] == "cancel":       # диспетчер телефон заказын гана жокко чыгарат
                    rr = core.get_ride(int(b.get("id") or 0))
                    if not rr or rr.get("source") != "phone":
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
            stops = _stops(b.get("stops"))
            q = core.quote(p[0], p[1], *(d or (None, None)), stops=stops)
            if not q["city"]:
                return self._json({"error": "no_city"})
            if q.get("dest_out"):
                return self._json({"error": "dest_out"})
            t = q["tariff"]
            cfg = core.class_config()
            if d:
                core.log_quote(uid, q["city"], q["price"])
            pc = core.passenger_cancels(uid)
            return self._json({"city": q["city"], "price": q["price"], "dist_km": q["dist_km"],
                               "minutes": q.get("minutes"), "surge": q["surge"], "fixed": q.get("fixed"),
                               "del_sizes": core.del_sizes(),
                               "peak": q.get("peak"), "route": (q.get("route") or {}).get("coords"),
                               "far_fee": q.get("far_fee"), "far_km": q.get("far_km"),
                               "stops": q.get("stops") or 0, "stop_fee": core.stop_fee(),
                               "cancels": pc if pc >= core.P_CANCEL_WEEK else 0,
                               "dbg": {"city": q["city"], "base": t.get("base"), "per_km": t.get("per_km"), "per_min": t.get("per_min"),
                                       "min": t.get("min_price"), "inc_km": t.get("inc_km"), "inc_min": t.get("inc_min"),
                                       "saved": bool(core.query("SELECT city FROM tariffs WHERE city=?", (q["city"],), "one")),
                                       "surge": q.get("surge"), "auto": q.get("auto"), "fixed": q.get("fixed")} if core.is_admin(uid) else None,
                               "classes": [{"id": c, "name": cfg[c]["name"], "price": pr,
                                            "min": int(t["min_price"] * cfg[c]["k"])}
                                           for c, pr in q["prices"].items()]
                                          + [{"id": c, "name": cfg[c]["name"], "off": True,
                                              "price": int(round((q["price"] or 0) * cfg[c]["k"] / 10.0) * 10) or None,
                                              "min": int(t["min_price"] * cfg[c]["k"])}
                                             for c in ("comfort",) if c in cfg and not cfg[c]["on"]],
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
            stops = _stops(b.get("stops"))
            q = core.quote(p[0], p[1], *(d or (None, None)), cls=b.get("cls") or "econom", stops=stops)
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
                parks.set_ref(uid, promo)
            at = _num(b.get("at"))
            if at is not None and not (core.now() + core.SCHEDULE_MIN - 120 <= at <= core.now() + core.SCHEDULE_MAX):
                return self._json({"error": "bad_time"}, 400)
            dsz = None
            if (b.get("cls") or "") == "delivery":            # жеткирүү: өлчөмгө жараша кошумча
                dsz = core.del_size(_txt(b.get("size"), 4) or "s") or core.del_size("s")
                if dsz and dsz["fee"]:
                    q = dict(q, price=int(q["price"] or 0) + dsz["fee"])
            core.mark_quote_ordered(uid)
            rid = core.create_ride(uid, q, p[0], p[1], *(d or (None, None)), promo=promo, discount=disc,
                                   scheduled_at=at, note=_txt(b.get("note"), 200) or None,
                                   other_name=other_name, other_phone=other_phone,
                                   p_addr=_txt(b.get("p_addr"), 80) or None,
                                   d_addr=_txt(b.get("d_addr"), 80) or None if d else None,
                                   stops=[{"p": [x[0], x[1]], "addr": x[2]} for x in stops] if stops and q.get("stops") else None,
                                   del_size=dsz and dsz["id"])
            return self._json({"ride": ride_view(core.get_ride(rid))})
        if path == "/api/cancel":
            r = core.active_ride_of(uid)
            if not r or r["passenger"] != uid:
                return self._json({"error": "no_ride"}, 404)
            outs = flow.passenger_cancel(uid, r["id"], _txt(b.get("reason"), 20) or None)
            if outs is None:
                return self._json({"error": "cant_cancel"}, 409)
            deliver(outs)
            return self._json({"ride": ride_view(core.get_ride(r["id"]))})
        if path == "/api/ref":
            return self._json({"ok": parks.set_ref(uid, _txt(b.get("code"), 20))})
        if path.startswith("/api/park/"):
            p = parks.by_owner(uid)
            if not p:
                return self._json({"error": "not_park"}, 403)
            act = path[10:]
            if act == "add_driver":
                return self._json({"result": parks.attach_driver(_txt(b.get("phone"), 20), p["id"], by_park=p["id"])})
            if act == "driver_action":
                res, outs = parks.driver_action(p["id"], _txt(b.get("uid"), 40), _txt(b.get("action"), 20), _txt(b.get("reason"), 200))
                deliver(outs)
                return self._json({"result": res, "apps": parks.applications(p["id"])}, 200 if res == "ok" else 400)
            if act == "remove_driver":
                return self._json({"result": parks.attach_driver(_txt(b.get("uid"), 40), None, by_park=p["id"])})
            if act == "act":
                ok_ = parks.act_answer(p["id"], int(b.get("id") or 0), b.get("ok") is True, _txt(b.get("comment"), 500))
                if ok_:
                    a = parks.act_get(int(b.get("id")))
                    ans = "✅ Макул" if b.get("ok") is True else "❗ Пикир: " + (a.get("comment") or "")
                    deliver([flow.note(x, "a_park_act", "/admin", park=p["name"], month=parks.period_label(a["period"]),
                                       answer=ans) for x in core.admins()])
                return self._json({"ok": ok_, "acts": [dict(x, label=parks.period_label(x["period"])) for x in parks.acts(p["id"])]},
                                  200 if ok_ else 400)
            return self._json({"error": "not_found"}, 404)
        if path == "/api/avatar":
            img = b.get("img")
            name = core.set_avatar(uid, img if isinstance(img, str) and img else None)
            if name is None:
                return self._json({"error": "bad_image"}, 400)
            return self._json({"ok": True, "avatar": ("/av/" + name) if name else None})
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
        if action == "stop_done":                      # «✓ Токтоочу жерге келдим»
            i = core.stop_done(_num(b.get("id")) or 0, uid)
            if i is None:
                return self._json({"error": "no_ride"}, 409)
            return self._json({"ok": True, "stop_i": i})
        if action == "register":
            if d and d["status"] in ("active", "blocked"):
                return self._json({"error": "already"}, 409)
            name, model = _txt(b.get("name"), 40), _txt(b.get("model"), 40)
            color, plate = _txt(b.get("color"), 20), _txt(b.get("plate"), 15).upper()
            if not (name and model and color and plate):
                return self._json({"error": "fields"}, 400)
            plate = core.norm_plate(plate)
            if not plate:
                return self._json({"error": "plate"}, 400)
            docs = {}
            for k in ("license", "techpass", "car", "selfie"):
                docs[k] = core.save_upload(b.get(k)) if b.get(k) else (d or {}).get("doc_" + k)
                if not docs[k]:
                    return self._json({"error": "doc_" + k}, 400)
            lu = _txt(b.get("lic_until"), 10) or (d or {}).get("lic_until")
            left = core.lic_days_left({"lic_until": lu})
            if left is None:
                return self._json({"error": "lic_date"}, 400)
            if left < 0:
                return self._json({"error": "lic_expired"}, 400)
            docs["lic_until"] = lu
            pk = parks.by_code(_txt(b.get("park"), 20)) if b.get("park") else None
            if b.get("park") and not pk:
                return self._json({"error": "park_code"}, 400)
            deliver(flow.register_driver(uid, name, model, color, plate, docs, park=pk))
            return self._json(driver_state(uid))
        if not d or d["status"] != "active":
            return self._json({"error": "not_active"}, 403)
        if action == "carphoto":
            files = {}
            for s in core.PHOTO_SIDES:
                f = core.save_upload(b.get(s)) if b.get(s) else None
                if not f:
                    return self._json({"error": "photo_" + s}, 400)
                files[s] = f
            core.set_car_photos(uid, files)
            u = core.get_user(uid) or {}
            deliver([flow.note(a, "a_car_photo", "/admin", name=u.get("name") or u.get("phone")) for a in core.admins()])
            return self._json(driver_state(uid))
        if action == "license":
            lu = _txt(b.get("lic_until"), 10)
            left = core.lic_days_left({"lic_until": lu})
            if left is None:
                return self._json({"error": "lic_date"}, 400)
            if left < 0:
                return self._json({"error": "lic_expired"}, 400)
            photo = core.save_upload(b.get("license")) if b.get("license") else None
            if not photo:
                return self._json({"error": "doc_license"}, 400)
            core.set_driver(uid, doc_license=photo, lic_until=lu)
            u = core.get_user(uid) or {}
            deliver([flow.note(a, "a_lic_update", "/admin", name=u.get("name") or u.get("phone"), date=lu)
                     for a in core.admins()])
            return self._json(driver_state(uid))
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
                left = core.lic_days_left(d)
                if left is not None and left < 0:
                    return self._json({"error": "lic_expired"}, 403)
                p = _point(b.get("p"))
                if not p:
                    return self._json({"error": "need_location"}, 400)
                acc = _num(b.get("acc"))
                if core.AREA_ON and not d.get("area_free"):
                    if acc and acc > 500:
                        return self._json({"error": "gps_acc", "acc": round(acc)}, 400)
                    if not core.in_area_buf(p[0], p[1]):          # аймактан сыртта линияга чыгууга болбойт
                        e = core.area_entry(p[0], p[1]) or {}
                        return self._json({"error": "out_area", "km": e.get("km"), "to": e.get("p"), "name": e.get("name")}, 403)
                core.driver_location(uid, p[0], p[1], live_period=60)
            else:
                if d["busy_ride"] or d.get("next_ride"):
                    return self._json({"error": "busy"}, 409)     # заказ аткарылып жатат
                core.set_driver(uid, online=0, live_until=None)
            return self._json(driver_state(uid))
        if action == "car_year":
            y = int(_num(b.get("year")) or 0)
            if not 1980 <= y <= 2030:
                return self._json({"error": "year"}, 400)
            core.set_driver(uid, car_year=y)
            return self._json(driver_state(uid))
        if action == "diag":                       # телефондун текшерүүлөрү (GPS, үн, батарея…) — админ/парк көрсүн
            core.set_diag_dev(uid, b.get("items"))
            return self._json({"ok": True})
        if action == "goal":
            g = int(_num(b.get("goal")) or 0)
            if not 100 <= g <= 50000:
                return self._json({"error": "goal"}, 400)
            core.set_driver(uid, goal=g)
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
        outs = handlers[action](uid, rid, _txt(b.get("reason"), 20) or None) if action == "cancel" else handlers[action](uid, rid)
        st = driver_state(uid)
        if outs is None:
            st["error"] = "too_late" if action == "accept" else "not_allowed"
        deliver(outs or [])
        return self._json(st)

    # ---------- админ ----------

    def _admin_get(self, action, q):
        per = (q.get("per") or ["month"])[0]
        per = per if per in ("today", "week", "month", "all") else "month"
        if action == "drv_fin":
            return self._json(core.drivers_fin(per))
        if action == "drv_fin.csv":
            body = core.drivers_fin_csv(per).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/csv; charset=utf-8")
            self.send_header("Content-Disposition", 'attachment; filename="taxitap-aydoochular-%s.csv"' % per)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if action == "overview":
            return self._json(core.admin_overview())
        if action == "parks":
            return self._json({"parks": parks.admin_list(), "pay_time": parks.pay_time()})
        if action == "park_acts":
            return self._json({"acts": parks.acts(limit=60)})
        if action == "far_pickup":
            return self._json(core.far_cfg())
        if action == "cancels":
            return self._json(dict(core.cancel_stats(), p_reasons=core.P_REASONS, d_reasons=core.D_REASONS))
        if action == "autoprice":
            cities = sorted({u.get("city") for u in core._area.get("units", []) if u.get("city")} | set((core.get_setting("auto_k") or {}).keys()))
            return self._json({"cfg": core.auto_cfg(), "k": {c: core.auto_k(c) for c in cities},
                               "metrics": {c: core.auto_metrics(c) for c in cities},
                               "traffic": core.get_setting("traffic_model") or {}, "hist": (core.get_setting("auto_hist") or [])[-5:],
                               "min_quotes": core.AUTO_MIN_QUOTES, "min_offers": core.AUTO_MIN_OFFERS})
        if action == "area_units":
            return self._json({"units": core.area_units_gj(), "zones": core.tariff_zones()})
        if action == "fixed_routes":
            return self._json({"items": core.fixed_routes(), "r": core.FIXED_R_KM})
        if action == "client":
            cu = core.phone_uid((q.get("phone") or [""])[0][:20])
            return self._json(core.client_card(cu) if cu else {"error": "bad_phone"})
        if action == "phone_rides":
            return self._json({"rides": core.phone_rides()})
        if action == "inbox":               # Кабинеттеги «🔔 Билдирүүлөр»: ачканда окулду деп белгиленет
            me = self._uid()
            items = core.inbox(me)
            core.inbox_seen(me)
            return self._json({"items": items})
        if action == "disps":
            return self._json({"disps": core.dispatchers()})
        if action == "disp_drivers":         # диспетчердин картасы үчүн: линиядагы айдоочулар
            t = core.now()
            return self._json({"drivers": [{"lat": d["lat"], "lon": d["lon"], "busy": bool(d.get("busy_ride")), "name": d.get("name") or ""}
                                           for d in core.admin_drivers() if d.get("online") and d.get("lat") is not None
                                           and (d.get("loc_at") or 0) > t - 600]})
        if action == "addr":
            return self._json({"items": addrbook.admin_list((q.get("q") or [""])[0][:60],
                                                            only=(q.get("only") or [""])[0] or None),
                               "count": addrbook.count(), "import": addrbook.import_state,
                               "maptiles": maptiles.status(), "dgis": dict(addrbook.dgis_state, on=bool(addrbook.DGIS_KEY), budget=core.get_setting("dgis_budget"),
                                            day_max=addrbook.DGIS_DAY_MAX),
                               "kinds": {k: {"icon": v[0], "name": v[1]} for k, v in addrbook.KINDS.items()}})
        if action == "drivers":
            t = core.now()
            rows = core.admin_drivers()
            for d in rows:
                d["is_online"] = bool(d["busy_ride"]) or core.is_available(d, t)
                d["diag"] = core.diag_brief(d, {"tg_uid": d.get("tg_uid")})
                d.pop("diag_dev", None); d.pop("tg_uid", None)
            return self._json({"drivers": rows})
        if action == "rides":
            return self._json({"rides": core.admin_rides()})
        if action == "lost":
            return self._json({"lost": core.lost_orders(int((q.get("days") or ["7"])[0]))})
        if action == "promos":
            return self._json({"promos": core.list_promos()})
        if action == "tariffs":
            return self._json({"tariffs": core.all_tariffs(), "classes": core.class_config(), "del_sizes": core.del_sizes(True),
                               "wait": core.wait_config(), "activity_km": core.activity_km(),
                               "peak": core.peak_config(), "yx": core.get_setting("yx") or {"rows": [], "pct": 11}})
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
        if action == "park":
            pid = parks.save(_txt(b.get("name"), 60), _txt(b.get("phone"), 20), b.get("share") or 0, b.get("ref_bonus") or 0,
                             _txt(b.get("promo"), 20), b.get("promo_amount") or 50, pid=int(b.get("id") or 0) or None,
                             active=b.get("active", True) is not False,
                             share_months=b.get("share_months", 6), share_after=b.get("share_after", 50))
            return self._json({"id": pid} if pid else {"error": "bad"}, 200 if pid else 400)
        if action == "driver_area_free":
            t = _txt(b.get("uid"), 40)
            if not core.get_driver(t):
                return self._json({"error": "not_found"}, 404)
            core.set_driver(t, area_free=1 if b.get("on") is True else 0, out_since=None)
            return self._json({"ok": True})
        if action == "park_self_approve":
            ok = parks.set_self_approve(int(b.get("id") or 0), b.get("on") is True)
            return self._json({"ok": ok}, 200 if ok else 400)
        if action == "park_driver":
            pid = int(b.get("park_id") or 0) or None
            return self._json({"result": parks.attach_driver(_txt(b.get("phone"), 20), pid)})
        if action == "fixed_routes":
            ok = core.set_fixed_routes(b.get("items"))
            return self._json({"ok": ok, "items": core.fixed_routes()}, 200 if ok else 400)
        if action == "park_pay_time":
            ok = parks.set_pay_time(_txt(b.get("from"), 5), _txt(b.get("to"), 5))
            return self._json({"ok": ok, "pay_time": parks.pay_time()}, 200 if ok else 400)
        if action == "autoprice":
            ok = core.set_auto_cfg(b.get("on") is not False, b.get("kmin"), b.get("kmax"))
            return self._json({"ok": ok, "cfg": core.auto_cfg()}, 200 if ok else 400)
        if action == "far_pickup":
            ok = core.set_far_cfg(b.get("on") is not False, b.get("free_km"), b.get("per_km"), b.get("max"))
            return self._json(dict(core.far_cfg(), ok=ok), 200 if ok else 400)
        if action == "autoprice_run":
            model = core.build_traffic_model()
            return self._json({"ok": True, "rows": core.auto_tune(force=True), "traffic": model})
        if action == "park_act":                         # акт түзүү / кайра эсептөө
            pk = parks.get(int(b.get("park_id") or 0))
            per = _txt(b.get("period"), 7) or parks.prev_period()
            if not pk or not re.fullmatch(r"20\d\d-(0[1-9]|1[0-2])", per):
                return self._json({"error": "bad"}, 400)
            aid, new = parks.act_make(pk["id"], per, force=True)
            if new and pk.get("owner_uid") and b.get("notify", True):
                a = parks.act_get(aid)["data"]
                deliver([flow.note(pk["owner_uid"], "park_act", "/park", park=pk["name"], month=parks.period_label(per),
                                   due=a["due"], paid=a["paid"], closing=a["closing"], days=parks.ACT_ANSWER_DAYS)])
            return self._json({"ok": True, "id": aid, "acts": parks.acts()})
        if action == "park_payout":
            pk = parks.get(int(b.get("park_id") or 0))
            amt = float(b.get("amount") or 0)
            wk = _txt(b.get("note"), 120) or ("апта " + parks.week_label())
            ok = parks.add_payout(int(b.get("park_id") or 0), amt, wk)
            if ok and pk and pk.get("owner_uid"):
                deliver([flow.note(pk["owner_uid"], "park_paid", "/park", park=pk["name"], amount=int(round(amt)), week=wk)])
            return self._json({"ok": ok}, 200 if ok else 400)
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
            inc = [_num(b.get(k)) if b.get(k) not in (None, "") else 0 for k in ("inc_km", "inc_min")]
            known = set(core.CITIES) | {t["city"] for t in core.all_tariffs()}
            if city not in known or any(v is None or v < 0 for v in vals + inc) or inc[0] > 20 or inc[1] > 60:
                return self._json({"error": "bad"}, 400)
            core.set_tariff(city, *vals, inc_km=inc[0], inc_min=inc[1])
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
        if action == "del_sizes":
            if not core.set_del_sizes(b.get("sizes")):
                return self._json({"error": "bad"}, 400)
            return self._json({"del_sizes": core.del_sizes(True)})
        if action == "classes":
            if not core.set_class_config(b.get("classes")):
                return self._json({"error": "bad"}, 400)
            return self._json({"classes": core.class_config()})
        if action == "peak":
            ok = core.set_peak(b.get("ranges"), b.get("k"))
            return self._json({"ok": ok, "peak": core.peak_config()}, 200 if ok else 400)
        if action == "yx_rows":                       # Яндекс менен салыштыруу: сапарлар
            rows = []
            for x in (b.get("rows") or [])[:30]:
                km, mi, pr = _num(x.get("km")), _num(x.get("min")), _num(x.get("price"))
                if None in (km, mi, pr) or not (0 < km < 200 and 0 < mi < 300 and 0 < pr < 20000):
                    return self._json({"error": "bad"}, 400)
                rows.append({"city": _txt(x.get("city"), 60), "km": km, "min": mi, "price": pr})
            pct = _num(b.get("pct"))
            core.set_setting("yx", {"rows": rows, "pct": pct if pct is not None and 0 <= pct <= 50 else 11})
            return self._json({"ok": True})
        if action == "activity_km":
            if not core.set_activity_km(_num(b.get("km"))):
                return self._json({"error": "bad"}, 400)
            return self._json({"activity_km": core.activity_km()})
        if action == "wait":
            if not core.set_wait_config(_num(b.get("free_min")), _num(b.get("per_min"))):
                return self._json({"error": "bad"}, 400)
            return self._json({"wait": core.wait_config()})
        if action == "car_photo_review":
            ruid = _txt(b.get("uid"), 40)
            ok = bool(b.get("ok"))
            if not core.review_car_photos(ruid, ok, _txt(b.get("note"), 200)):
                return self._json({"error": "not_pending"}, 400)
            deliver([flow.note(ruid, "d_car_photo_ok" if ok else "d_car_photo_bad", "/driver", note=_txt(b.get("note"), 200) or "—")])
            return self._json({"ok": True})
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
            q = core.quote(p[0], p[1], *(d or (None, None)), cls=b.get("cls") or "econom")
            if not q["city"]:
                return self._json({"error": "no_city"}, 400)
            if q.get("dest_out"):
                return self._json({"error": "dest_out"}, 400)
            u = core.ensure_user(uid, name)
            core.set_user(uid, phone=uid[3:], **({"name": name} if name and not u.get("name") else {}))
            rid = core.create_ride(uid, q, p[0], p[1], *(d or (None, None)), note=note or None,
                                   source="phone", p_addr=_txt(b.get("p_addr"), 80) or None,
                                   d_addr=_txt(b.get("d_addr"), 80) or None)
            core.query("UPDATE rides SET disp_by=? WHERE id=?", (admin, rid))        # ким берди
            return self._json({"ride": ride_view(core.get_ride(rid))})
        if action == "disp_set":              # админ: диспетчер кошуу / алып салуу
            if not core.is_admin(admin):
                return self._json({"error": "auth"}, 401)
            uid = core.set_disp(_txt(b.get("phone"), 20), bool(b.get("on", True)), _txt(b.get("name"), 40) or None)
            if not uid:
                return self._json({"error": "bad_phone"}, 400)
            if b.get("on", True) and core.tg_of(uid):          # ботко туташкан болсо — шилтемени өзү жөнөтөт
                deliver([flow.note(uid, "disp_added", "/disp")])
            return self._json({"disps": core.dispatchers()})
        if action == "quote":
            p, d = _point(b.get("p")), _point(b.get("d"))
            if not p:
                return self._json({"error": "bad_point"}, 400)
            q = core.quote(p[0], p[1], *(d or (None, None)), cls=b.get("cls") or "econom")
            cfg = core.class_config()
            return self._json({"city": q["city"], "price": q["price"], "dist_km": q["dist_km"],
                               "dest_out": bool(q.get("dest_out")), "fixed": q.get("fixed"), "surge": q["surge"],
                               "classes": [{"id": c, "name": cfg[c]["name"], "price": pr} for c, pr in q["prices"].items()]})
        if action == "finance":
            pct, mb = _num(b.get("percent")), _num(b.get("min_balance") or 0)
            fu = _txt(b.get("free_until"), 10) or None
            tx, ins, sf = _num(b.get("tax_pct")), _num(b.get("ins_pct")), _num(b.get("stop_fee"))
            if pct is None or mb is None or not core.set_finance_config(pct, fu, mb, tx, ins, sf):
                return self._json({"error": "bad"}, 400)
            return self._json(core.admin_finance())
        if action == "area_title":
            core.set_setting("area_title", _txt(b.get("title"), 60).strip())
            return self._json(core.area_info())
        if action == "area_sel":
            r = core.set_area_units(b.get("units") or [])
            if r.get("error"):
                return self._json(r, 400)
            return self._json(dict(core.area_info(), result=r))
        if action == "voice_save":
            ok = core.voice_save(_txt(b.get("key"), 20), b.get("b64"), b.get("set") or 1)
            return self._json(dict(core.voice_state(b.get("set") or 1), ok=ok), 200 if ok else 400)
        if action == "voice_del":
            ok = core.voice_delete(_txt(b.get("key"), 20), b.get("set") or 1)
            return self._json(dict(core.voice_state(b.get("set") or 1), ok=ok), 200 if ok else 400)
        if action == "voice_text":
            ok = core.voice_set_text(_txt(b.get("key"), 20), b.get("text") or "", b.get("set") or 1)
            return self._json(dict(core.voice_state(b.get("set") or 1), ok=ok), 200 if ok else 400)
        if action == "voice_add":
            k = core.voice_custom_add(b.get("text") or "", _txt(b.get("ev") or "", 20))
            return self._json(dict(core.voice_state(b.get("set") or 1), ok=bool(k), key=k), 200 if k else 400)
        if action == "voice_tpl":
            ok = core.voice_set_tpl(_txt(b.get("kind"), 20), b.get("toks") if isinstance(b.get("toks"), list) else [])
            return self._json(dict(core.voice_state(b.get("set") or 1), ok=ok), 200 if ok else 400)
        if action == "voice_ev":
            ok = core.voice_custom_edit(_txt(b.get("key"), 20), _txt(b.get("ev") or "", 20))
            return self._json(dict(core.voice_state(b.get("set") or 1), ok=ok), 200 if ok else 400)
        if action == "voice_rm":
            ok = core.voice_custom_del(_txt(b.get("key"), 20))
            return self._json(dict(core.voice_state(b.get("set") or 1), ok=ok), 200 if ok else 400)
        if action == "voice_name":
            ok = core.voice_set_name(b.get("set"), _txt(b.get("name"), 30))
            return self._json(dict(core.voice_state(b.get("set") or 1), ok=ok), 200 if ok else 400)
        if action == "unit_border_restore":
            ok = core.restore_unit_border(_txt(b.get("name"), 80), int(b.get("idx") or 0))
            return self._json({"ok": ok}, 200 if ok else 400)
        if action == "border_places":
            return self._json({"places": core.border_places(b.get("points") or [])})
        if action == "unit_border":
            ok = core.set_unit_border(_txt(b.get("name"), 80), b.get("points"), bool(b.get("reset")))
            return self._json({"ok": ok, "units": core.area_units_gj()}, 200 if ok else 400)
        if action == "tariff_zone":
            ok = core.set_tariff_zone(_txt(b.get("city"), 60), b.get("points"), int(b.get("id") or 0) or None,
                                      delete=b.get("delete") is True)
            return self._json({"ok": ok, "zones": core.tariff_zones()}, 200 if ok else 400)
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
    try:
        core.voice_migrate_thanks()
    except Exception as e:
        print("voice migrate:", e, flush=True)
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
