#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Такси ТАП! — жалпы өзөк: база, гео, баа.

ТАП!тын core.py үлгүсү менен:
  DATABASE_URL коюлса  -> Postgres (Railway)
  Коюлбаса             -> SQLite, taxi.db файлы (жергиликтүү сыноо)

Код өзгөрбөй эле экөөндө тең иштейт.
"""

import json
import math
import os
import sqlite3
import threading
import time

BASE = os.path.dirname(os.path.abspath(__file__))

DATABASE_URL = (os.environ.get("DATABASE_URL") or "").strip()
IS_PG = DATABASE_URL.startswith(("postgres://", "postgresql://"))
SQLITE_PATH = os.environ.get("SQLITE_PATH") or os.path.join(BASE, "taxi.db")


def _env_num(name, default):
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return float(default)


# ==================== Жөндөөлөр ====================
# Баары Railway → Variables аркылуу өзгөрөт, код тийбейт.

COMMISSION_PCT = _env_num("COMMISSION_PCT", 0)     # пилотто 0 = бекер
MIN_BALANCE = _env_num("MIN_BALANCE", 0)           # мындан аз болсо заказ келбейт
OFFER_SEC = _env_num("OFFER_SEC", 15)              # айдоочуга сунуштун мөөнөтү
SEARCH_MAX_SEC = _env_num("SEARCH_MAX_SEC", 180)   # андан кийин издөө токтойт
LOC_TTL_SEC = _env_num("LOC_TTL_SEC", 600)         # координат ушунча эскирсе — офлайн
ROAD_FACTOR = _env_num("ROAD_FACTOR", 1.3)         # түз сызык → жол аралыгы
AVG_SPEED_KMH = _env_num("AVG_SPEED_KMH", 25)

# Радиус издөө убактысына жараша кеңейет: (секунд, км)
RADIUS_STEPS = [(60, 3.0), (120, 5.0), (10 ** 9, 8.0)]

# Мисал тарифтер — /tarif буйругу менен ар шаарга өзүнчө коюлат.
DEFAULT_TARIFF = {
    "base": _env_num("TARIFF_BASE", 60),
    "per_km": _env_num("TARIFF_KM", 18),
    "per_min": _env_num("TARIFF_MIN", 3),
    "min_price": _env_num("TARIFF_MINPRICE", 100),
}

# Шаарлардын борбору (lat, lon). Жүргүнчүнүн чекити эң жакынына
# 40 км ичинде болсо, ошол шаарга жазылат.
CITIES = {
    "Бишкек": (42.8746, 74.5698),
    "Ош": (40.5283, 72.7985),
    "Каракол": (42.4907, 78.3936),
    "Токмок": (42.8417, 75.2911),
    "Нарын": (41.4287, 75.9911),
    "Талас": (42.5228, 72.2427),
    "Жалал-Абад": (40.9333, 73.0017),
    "Баткен": (40.0629, 70.8194),
    "Балыкчы": (42.4600, 76.1870),
    "Кара-Балта": (42.8142, 73.8481),
}
CITY_RADIUS_KM = 40


# ==================== База ====================
# Ар бир агым өз туташуусун сактайт; үзүлүп калса, кайра ачылат.

_local = threading.local()


def _new_conn():
    if IS_PG:
        import psycopg2
        return psycopg2.connect(DATABASE_URL, sslmode=os.environ.get("PGSSLMODE", "require"))
    conn = sqlite3.connect(SQLITE_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _connect():
    conn = getattr(_local, "conn", None)
    if conn is not None and not getattr(conn, "closed", 0):
        return conn
    conn = _new_conn()
    _local.conn = conn
    return conn


def _drop():
    conn = getattr(_local, "conn", None)
    _local.conn = None
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass


def _broken(e):
    if type(e).__name__ in ("InterfaceError", "AdminShutdown"):
        return True
    t = str(e).lower()
    return any(w in t for w in ("closed", "ssl", "terminat", "connection",
                                "server", "timeout", "broken pipe"))


def _ph(sql):
    """SQLite '?' -> Postgres '%s'."""
    return sql.replace("?", "%s") if IS_PG else sql


def _query_once(sql, params=(), fetch=None):
    """
    fetch: None, "one", "all", "id" (жаңы id), "count" (өзгөргөн саптар)
    """
    conn = _connect()
    try:
        if IS_PG:
            import psycopg2.extras
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        else:
            cur = conn.cursor()
        if fetch == "id":
            cur.execute(_ph(sql + (" RETURNING id" if IS_PG else "")), params)
            new_id = cur.fetchone()["id"] if IS_PG else cur.lastrowid
            conn.commit()
            return new_id
        cur.execute(_ph(sql), params)
        if fetch == "one":
            row = cur.fetchone()
            out = dict(row) if row else None
        elif fetch == "all":
            out = [dict(r) for r in cur.fetchall()]
        elif fetch == "count":
            out = cur.rowcount
        else:
            out = None
        conn.commit()
        return out
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise


def query(sql, params=(), fetch=None):
    """Суроо. Туташуу үзүлсө, бир жолу кайра аракет кылат."""
    try:
        return _query_once(sql, params, fetch)
    except Exception as e:
        if not _broken(e):
            raise
        _drop()
        return _query_once(sql, params, fetch)


_PK = "SERIAL PRIMARY KEY" if IS_PG else "INTEGER PRIMARY KEY AUTOINCREMENT"

SCHEMA = [
    """CREATE TABLE IF NOT EXISTS users (
        uid TEXT PRIMARY KEY,           -- 'tg:123', кийин 'wa:996...'
        name TEXT, phone TEXT,
        lang TEXT DEFAULT 'ky',
        role TEXT DEFAULT 'passenger',  -- passenger | driver
        state TEXT DEFAULT '{}',        -- сүйлөшүүнүн абалы (JSON)
        created_at REAL)""",
    """CREATE TABLE IF NOT EXISTS drivers (
        uid TEXT PRIMARY KEY,
        car_model TEXT, car_color TEXT, car_plate TEXT,
        status TEXT DEFAULT 'pending',  -- pending | active | blocked
        rating REAL DEFAULT 5.0, rated INTEGER DEFAULT 0,
        rides_done INTEGER DEFAULT 0,
        balance REAL DEFAULT 0,
        online INTEGER DEFAULT 0,
        lat REAL, lon REAL, loc_at REAL, live_until REAL,
        busy_ride INTEGER,
        created_at REAL)""",
    f"""CREATE TABLE IF NOT EXISTS rides (
        id {_PK},
        passenger TEXT NOT NULL, driver TEXT,
        city TEXT,
        p_lat REAL, p_lon REAL, d_lat REAL, d_lon REAL,
        dist_km REAL, price REAL, surge REAL DEFAULT 1.0,
        status TEXT NOT NULL DEFAULT 'searching',
        offered_to TEXT, offered_at REAL, tried TEXT DEFAULT '[]',
        cancel_by TEXT,
        created_at REAL, accepted_at REAL, arrived_at REAL,
        started_at REAL, completed_at REAL)""",
    f"""CREATE TABLE IF NOT EXISTS ride_events (
        id {_PK}, ride_id INTEGER, status TEXT, actor TEXT, at REAL)""",
    f"""CREATE TABLE IF NOT EXISTS balance_tx (
        id {_PK}, driver TEXT, amount REAL,
        kind TEXT,                      -- topup | commission
        status TEXT DEFAULT 'done',     -- pending | done | rejected
        ride_id INTEGER, proof TEXT, approved_by TEXT, at REAL)""",
    """CREATE TABLE IF NOT EXISTS ratings (
        ride_id INTEGER PRIMARY KEY, stars INTEGER, at REAL)""",
    """CREATE TABLE IF NOT EXISTS tariffs (
        city TEXT PRIMARY KEY, base REAL, per_km REAL, per_min REAL, min_price REAL)""",
    """CREATE TABLE IF NOT EXISTS web_sessions (
        token TEXT PRIMARY KEY,         -- браузердеги cookie
        uid TEXT,                       -- ырасталгандан кийин: 'ph:+996...'
        phone TEXT, name TEXT,
        verified INTEGER DEFAULT 0,
        created_at REAL)""",
    "CREATE INDEX IF NOT EXISTS idx_rides_status ON rides(status)",
    "CREATE INDEX IF NOT EXISTS idx_drivers_online ON drivers(online, status)",
]


def init_db():
    """Таблицаларды түзөт. Кайра-кайра чакырса коопсуз."""
    for sql in SCHEMA:
        query(sql)


def now():
    return time.time()


# ==================== Колдонуучу ====================

def get_user(uid):
    return query("SELECT * FROM users WHERE uid=?", (uid,), "one")


def ensure_user(uid, name=""):
    u = get_user(uid)
    if u:
        return u
    query("INSERT INTO users (uid, name, created_at) VALUES (?, ?, ?)", (uid, name, now()))
    return get_user(uid)


def set_user(uid, **fields):
    if not fields:
        return
    cols = ", ".join("%s=?" % k for k in fields)
    query("UPDATE users SET %s WHERE uid=?" % cols, tuple(fields.values()) + (uid,))


def get_state(uid):
    u = get_user(uid)
    try:
        return json.loads((u or {}).get("state") or "{}")
    except ValueError:
        return {}


def set_state(uid, st):
    set_user(uid, state=json.dumps(st, ensure_ascii=False))


# ==================== Айдоочу ====================

def get_driver(uid):
    return query("SELECT * FROM drivers WHERE uid=?", (uid,), "one")


def add_driver(uid, model, color, plate):
    if get_driver(uid):
        query("UPDATE drivers SET car_model=?, car_color=?, car_plate=?, status='pending' "
              "WHERE uid=?", (model, color, plate, uid))
    else:
        query("INSERT INTO drivers (uid, car_model, car_color, car_plate, created_at) "
              "VALUES (?, ?, ?, ?, ?)", (uid, model, color, plate, now()))


def set_driver(uid, **fields):
    cols = ", ".join("%s=?" % k for k in fields)
    query("UPDATE drivers SET %s WHERE uid=?" % cols, tuple(fields.values()) + (uid,))


def driver_location(uid, lat, lon, live_period=None, msg_date=None):
    """
    Telegram live location: ар жаңыртуу ушул жерге келет.
    Айдоочу турган жерде турса, Telegram жаңыртуу жибербейт —
    ошондуктан онлайнды live_until (бөлүшүү мөөнөтү) боюнча эсептейбиз.
    """
    t = now()
    fields = {"lat": lat, "lon": lon, "loc_at": t, "online": 1}
    if live_period:
        fields["live_until"] = (msg_date or t) + live_period
    set_driver(uid, **fields)


def is_available(d, t=None):
    t = t or now()
    if not d or d["status"] != "active" or not d["online"] or d["busy_ride"]:
        return False
    if d["lat"] is None or (d["balance"] or 0) < MIN_BALANCE:
        return False
    live = (d["live_until"] or 0) > t
    fresh = t - (d["loc_at"] or 0) < LOC_TTL_SEC
    return live or fresh


def online_drivers(city=None):
    rows = query("SELECT * FROM drivers WHERE online=1 AND status='active'", (), "all")
    t = now()
    out = [d for d in rows if is_available(d, t)]
    if city:
        out = [d for d in out if city_of(d["lat"], d["lon"]) == city]
    return out


def add_tx(driver, amount, kind, status="done", ride_id=None, proof=None):
    tx = query("INSERT INTO balance_tx (driver, amount, kind, status, ride_id, proof, at) "
               "VALUES (?, ?, ?, ?, ?, ?, ?)",
               (driver, amount, kind, status, ride_id, proof, now()), "id")
    if status == "done":
        query("UPDATE drivers SET balance=balance+? WHERE uid=?", (amount, driver))
    return tx


def approve_tx(tx_id, amount, admin):
    """Скриншот текшерилди → баланска кошулат. Эки жолу кошулбайт."""
    n = query("UPDATE balance_tx SET status='done', amount=?, approved_by=? "
              "WHERE id=? AND status='pending'", (amount, admin, tx_id), "count")
    if not n:
        return None
    tx = query("SELECT * FROM balance_tx WHERE id=?", (tx_id,), "one")
    query("UPDATE drivers SET balance=balance+? WHERE uid=?", (amount, tx["driver"]))
    return tx


def reject_tx(tx_id, admin):
    n = query("UPDATE balance_tx SET status='rejected', approved_by=? "
              "WHERE id=? AND status='pending'", (admin, tx_id), "count")
    return query("SELECT * FROM balance_tx WHERE id=?", (tx_id,), "one") if n else None


# ==================== Гео жана баа ====================

def haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def city_of(lat, lon):
    best, best_d = None, CITY_RADIUS_KM
    for name, (clat, clon) in CITIES.items():
        d = haversine_km(lat, lon, clat, clon)
        if d < best_d:
            best, best_d = name, d
    return best


def get_tariff(city):
    row = query("SELECT * FROM tariffs WHERE city=?", (city or "",), "one")
    return row or dict(DEFAULT_TARIFF, city=city)


def set_tariff(city, base, per_km, per_min, min_price):
    query("DELETE FROM tariffs WHERE city=?", (city,))
    query("INSERT INTO tariffs (city, base, per_km, per_min, min_price) VALUES (?, ?, ?, ?, ?)",
          (city, base, per_km, per_min, min_price))


def surge_k(city):
    """Заказ көп, айдоочу аз болсо баа 1.5 эсеге чейин көтөрүлөт."""
    waiting = query("SELECT COUNT(*) AS n FROM rides WHERE status='searching' AND city=?",
                    (city or "",), "one")["n"]
    drivers = len(online_drivers(city)) or 1
    ratio = (waiting + 1) / drivers
    return 1.0 if ratio <= 1 else round(min(1.5, 1 + 0.25 * (ratio - 1)), 2)


def road_km(lat1, lon1, lat2, lon2):
    """Азырынча түз сызык × коэффициент. Кийин OSRM/2GIS маршруту коюлат."""
    return haversine_km(lat1, lon1, lat2, lon2) * ROAD_FACTOR


def quote(p_lat, p_lon, d_lat=None, d_lon=None):
    """Баа = max(минимум, отуруу + км×a + мүн×b) × k, 10 сомго тегеректелет."""
    city = city_of(p_lat, p_lon)
    t = get_tariff(city)
    k = surge_k(city)
    if d_lat is None:
        return {"city": city, "dist_km": None, "price": None, "surge": k, "tariff": t}
    km = road_km(p_lat, p_lon, d_lat, d_lon)
    minutes = km / AVG_SPEED_KMH * 60
    raw = max(t["min_price"], t["base"] + t["per_km"] * km + t["per_min"] * minutes) * k
    return {"city": city, "dist_km": round(km, 1), "price": int(math.ceil(raw / 10.0) * 10),
            "surge": k, "tariff": t}


# ==================== Сапар ====================
# searching → accepted → arrived → in_trip → completed
#                                            ↘ cancelled (каалаган кадамда)

def create_ride(passenger, q, p_lat, p_lon, d_lat=None, d_lon=None):
    rid = query("INSERT INTO rides (passenger, city, p_lat, p_lon, d_lat, d_lon, dist_km, "
                "price, surge, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, "
                "'searching', ?)",
                (passenger, q["city"], p_lat, p_lon, d_lat, d_lon, q["dist_km"],
                 q["price"], q["surge"], now()), "id")
    log_event(rid, "searching", passenger)
    return rid


def get_ride(rid):
    return query("SELECT * FROM rides WHERE id=?", (rid,), "one")


def active_ride_of(uid):
    return query("SELECT * FROM rides WHERE (passenger=? OR driver=?) AND status IN "
                 "('searching','accepted','arrived','in_trip') ORDER BY id DESC LIMIT 1",
                 (uid, uid), "one")


def log_event(rid, status, actor):
    query("INSERT INTO ride_events (ride_id, status, actor, at) VALUES (?, ?, ?, ?)",
          (rid, status, actor, now()))


def offer(rid, driver):
    query("UPDATE rides SET offered_to=?, offered_at=? WHERE id=? AND status='searching'",
          (driver, now(), rid))


def mark_tried(rid, driver):
    r = get_ride(rid)
    tried = json.loads(r["tried"] or "[]")
    if driver not in tried:
        tried.append(driver)
    query("UPDATE rides SET tried=?, offered_to=NULL, offered_at=NULL WHERE id=? "
          "AND offered_to=?", (json.dumps(tried), rid, driver))


def accept(rid, driver):
    """
    Атомдук: эки айдоочу бир заказды ала албайт.
    UPDATE ... WHERE status='searching' AND offered_to=? — бир гана жолу өтөт.
    """
    n = query("UPDATE rides SET driver=?, status='accepted', accepted_at=?, offered_to=NULL "
              "WHERE id=? AND status='searching' AND offered_to=?",
              (driver, now(), rid, driver), "count")
    if not n:
        return False
    set_driver(driver, busy_ride=rid)
    log_event(rid, "accepted", driver)
    return True


_NEXT = {"accepted": ("arrived", "arrived_at"),
         "arrived": ("in_trip", "started_at"),
         "in_trip": ("completed", "completed_at")}


def advance(rid, driver):
    """Айдоочунун кийинки кадамы. Жаңы абалды кайтарат же None."""
    r = get_ride(rid)
    if not r or r["driver"] != driver or r["status"] not in _NEXT:
        return None
    new, col = _NEXT[r["status"]]
    n = query("UPDATE rides SET status=?, %s=? WHERE id=? AND status=?" % col,
              (new, now(), rid, r["status"]), "count")
    if not n:
        return None
    log_event(rid, new, driver)
    if new == "completed":
        _finish(rid, driver)
    return new


def _finish(rid, driver):
    r = get_ride(rid)
    query("UPDATE drivers SET busy_ride=NULL, rides_done=rides_done+1 WHERE uid=?", (driver,))
    if COMMISSION_PCT > 0 and r["price"]:
        add_tx(driver, -round(r["price"] * COMMISSION_PCT / 100.0, 2), "commission", ride_id=rid)


def cancel(rid, by, allowed=("searching", "accepted", "arrived")):
    r = get_ride(rid)
    if not r or r["status"] not in allowed:
        return None
    n = query("UPDATE rides SET status='cancelled', cancel_by=? WHERE id=? AND status=?",
              (by, rid, r["status"]), "count")
    if not n:
        return None
    if r["driver"]:
        set_driver(r["driver"], busy_ride=None)
    log_event(rid, "cancelled", by)
    return r


def rate(rid, passenger, stars):
    r = get_ride(rid)
    if not r or r["passenger"] != passenger or r["status"] != "completed":
        return False
    if query("SELECT ride_id FROM ratings WHERE ride_id=?", (rid,), "one"):
        return False
    query("INSERT INTO ratings (ride_id, stars, at) VALUES (?, ?, ?)", (rid, stars, now()))
    d = get_driver(r["driver"])
    n = (d["rated"] or 0) + 1
    avg = ((d["rating"] or 5.0) * (n - 1) + stars) / n
    set_driver(r["driver"], rating=round(avg, 2), rated=n)
    return True


def searching_rides():
    return query("SELECT * FROM rides WHERE status='searching' ORDER BY id", (), "all")


# ==================== Сайт: кирүү ====================
# SMS акчалуу, ошондуктан номер Telegram бот аркылуу ырасталат:
# сайт токен берет → t.me/<бот>?start=web_<токен> → бот номерди сурайт →
# номер дал келсе, сессия ырасталат.

def phone_uid(phone):
    d = "".join(c for c in phone or "" if c.isdigit())
    if d.startswith("0") and len(d) == 10:
        d = "996" + d[1:]
    if len(d) == 9:
        d = "996" + d
    return "ph:+" + d if len(d) >= 11 else None


def web_session_new(phone, name):
    import secrets
    tok = secrets.token_urlsafe(18)
    query("INSERT INTO web_sessions (token, phone, name, created_at) VALUES (?, ?, ?, ?)",
          (tok, phone, name, now()))
    return tok


def web_session(tok):
    if not tok:
        return None
    return query("SELECT * FROM web_sessions WHERE token=?", (tok,), "one")


def web_session_verify(tok, phone_seen=None):
    """Номер дал келсе, сессияны ырастайт жана колдонуучуну түзөт."""
    s = web_session(tok)
    if not s:
        return None
    uid = phone_uid(s["phone"])
    if not uid:
        return None
    if phone_seen is not None and phone_uid(phone_seen) != uid:
        return None
    ensure_user(uid, s["name"] or "")
    set_user(uid, phone=uid[3:], name=s["name"] or "")
    query("UPDATE web_sessions SET verified=1, uid=? WHERE token=?", (uid, tok))
    return uid


def last_ride_of(uid, within_sec=900):
    """Активдүү сапар, же жакында бүткөнү (баалоо үчүн)."""
    r = active_ride_of(uid)
    if r:
        return r
    return query("SELECT * FROM rides WHERE passenger=? AND status IN ('completed','cancelled') "
                 "AND created_at>? ORDER BY id DESC LIMIT 1", (uid, now() - within_sec), "one")


def rated(rid):
    return query("SELECT ride_id FROM ratings WHERE ride_id=?", (rid,), "one") is not None
