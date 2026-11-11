#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Такси ТАП! — жалпы өзөк: база, гео, баа.

ТАП!тын core.py үлгүсү менен:
  DATABASE_URL коюлса  -> Postgres (Railway)
  Коюлбаса             -> SQLite, taxi.db файлы (жергиликтүү сыноо)

Код өзгөрбөй эле экөөндө тең иштейт.
"""

import base64
import json
import math
import os
import secrets
import sqlite3
import threading
import time

BASE = os.path.dirname(os.path.abspath(__file__))

# Туруктуу диск (документтер, чектер). Railway'де Volume тиркелет.
DATA_DIR = (os.environ.get("DATA_DIR") or os.environ.get("RAILWAY_VOLUME_MOUNT_PATH")
            or os.path.join(BASE, "data"))
UPLOADS = os.path.join(DATA_DIR, "uploads")
SITE_URL = (os.environ.get("SITE_URL") or "").rstrip("/")
PAY_INFO = os.environ.get("PAY_INFO") or "MBank: +996 ___ ___ ___ (аты-жөнү)"

ADMIN_IDS = ["tg:" + x.strip() for x in (os.environ.get("ADMIN_IDS") or "").split(",") if x.strip()]
ADMIN_PHONES = [x.strip() for x in (os.environ.get("ADMIN_PHONES") or "").split(",") if x.strip()]

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
TRAFFIC_FACTOR = _env_num("TRAFFIC_FACTOR", 1.3)   # OSRM убактысы бош жол үчүн — шаарда көбүрөөк
OSRM_URL = (os.environ.get("OSRM_URL") or "https://router.project-osrm.org").rstrip("/")

# Радиус издөө убактысына жараша кеңейет: (секунд, км)
# Сыноо үчүн гана: бир номер өзүнүн заказын айдоочу катары ала алат.
# Чыныгы иште 0 болушу керек (жалган сапар, рейтинг топтоонун алдын алат).
TEST_SELF_ORDER = os.environ.get("TEST_SELF_ORDER") == "1"

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
    "Манас": (40.9333, 73.0017),          # мурунку Жалал-Абад шаары (2025-ж. сентябрь)
    "Баткен": (40.0629, 70.8194),
    "Балыкчы": (42.4600, 76.1870),
    "Кара-Балта": (42.8142, 73.8481),
    "Базар-Коргон": (41.0377, 72.7470),
}

# Шаарга жараша демейки тариф (админ панелинен өзгөрөт).
# Базар-Коргон — Яндекс Go «Эконом», 2026-11-10:
#   2,5 км / 9 мүн → 64 с · 2,6 км / 11 мүн → 82 с · 6 км / 12 мүн → 118 с
# Ушул тариф менен: 60 · 70 · 110 с (Яндекстен 6–15% арзан).
CITY_TARIFFS = {
    "Базар-Коргон": {"base": 10, "per_km": 13, "per_min": 2, "min_price": 60},
}
CITY_RADIUS_KM = 40


# ==================== База ====================
# Ар бир агым өз туташуусун сактайт; үзүлүп калса, кайра ачылат.

_local = threading.local()


def _new_conn():
    if IS_PG:
        import psycopg2
        return psycopg2.connect(DATABASE_URL, sslmode=os.environ.get("PGSSLMODE", "prefer"))
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
        uid TEXT PRIMARY KEY,           -- 'ph:+996555123456' — номер = аккаунт
        name TEXT, phone TEXT,
        lang TEXT DEFAULT 'ky',
        tg_uid TEXT,                    -- номерди ырастаган Telegram ('tg:123')
        notify INTEGER DEFAULT 1,       -- Telegram'га билдирүү жиберилсинби
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
        doc_license TEXT, doc_techpass TEXT, doc_car TEXT,   -- сүрөт файлдары
        reject_note TEXT,
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
        claimed REAL,                   -- айдоочу жазган сумма (чек боюнча)
        ride_id INTEGER, proof TEXT, approved_by TEXT, at REAL)""",
    """CREATE TABLE IF NOT EXISTS ratings (
        ride_id INTEGER PRIMARY KEY, stars INTEGER, at REAL)""",
    """CREATE TABLE IF NOT EXISTS tariffs (
        city TEXT PRIMARY KEY, base REAL, per_km REAL, per_min REAL, min_price REAL)""",
    """CREATE TABLE IF NOT EXISTS web_sessions (
        token TEXT PRIMARY KEY,         -- браузердеги cookie
        uid TEXT,                       -- ырасталгандан кийин: 'ph:+996...'
        phone TEXT, name TEXT,
        kind TEXT DEFAULT 'rider',      -- rider | driver | admin
        verified INTEGER DEFAULT 0,
        created_at REAL)""",
    """CREATE TABLE IF NOT EXISTS promos (
        code TEXT PRIMARY KEY, amount REAL, first_only INTEGER DEFAULT 1,
        max_uses INTEGER DEFAULT 0,      -- 0 = чексиз
        expires TEXT, active INTEGER DEFAULT 1, created_at REAL)""",
    """CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY, value TEXT)""",
    f"""CREATE TABLE IF NOT EXISTS messages (
        id {_PK}, ride_id INTEGER, sender TEXT, text TEXT, at REAL)""",
    """CREATE TABLE IF NOT EXISTS passenger_ratings (
        ride_id INTEGER PRIMARY KEY, stars INTEGER, at REAL)""",
    "CREATE INDEX IF NOT EXISTS idx_msg_ride ON messages(ride_id)",
    f"""CREATE TABLE IF NOT EXISTS addresses (
        id {_PK}, name TEXT, kind TEXT, lat REAL, lon REAL, aliases TEXT, area TEXT,
        source TEXT, hidden INTEGER DEFAULT 0, osm_key TEXT, created_at REAL)""",
    "CREATE INDEX IF NOT EXISTS idx_rides_status ON rides(status)",
    "CREATE INDEX IF NOT EXISTS idx_tx_kind ON balance_tx(kind, at)",
    "CREATE INDEX IF NOT EXISTS idx_drivers_online ON drivers(online, status)",
]


# Эски базага жаңы тилкелер (таблица мурун түзүлгөн болсо)
NEW_COLUMNS = {
    "addresses": {"approx": "INTEGER DEFAULT 0",        # жери болжолдуу (аты гана белгилүү)
                  "status": "TEXT DEFAULT 'ok'",        # ok | pending (жүргүнчү/айдоочу сунуштаган)
                  "votes": "INTEGER DEFAULT 0", "suggested_by": "TEXT"},
    "users": {"tg_uid": "TEXT", "notify": "INTEGER DEFAULT 1", "terms_at": "REAL",
              "places": "TEXT",                              # {"home": {...}, "work": {...}}
              "p_rating": "REAL", "p_rated": "INTEGER DEFAULT 0"},   # айдоочулар берген баа
    "web_sessions": {"agreed": "INTEGER DEFAULT 0"},
    "drivers": {"doc_license": "TEXT", "doc_techpass": "TEXT", "doc_car": "TEXT",
                "reject_note": "TEXT",
                "classes": "TEXT",                 # 'econom,delivery,comfort,minivan'
                "next_ride": "INTEGER",            # сапар бүтө электе алган кийинки заказ
                "home_lat": "REAL", "home_lon": "REAL", "home_on": "INTEGER DEFAULT 0",
                "home_day": "TEXT", "home_uses": "INTEGER DEFAULT 0",
                "out_since": "REAL",
                "activity": "INTEGER DEFAULT 100"},   # активдүүлүк 0..100 (Яндекс Pro'догудай)              # аймактан сыртка чыккан убакыт
    "balance_tx": {"claimed": "REAL"},
    "rides": {"note": "TEXT", "source": "TEXT",   # source: web | phone (диспетчер)
              "promo": "TEXT", "discount": "REAL DEFAULT 0",
              "scheduled_at": "REAL",                      # алдын ала заказ
              "cls": "TEXT",                               # econom | comfort | minivan | delivery
              "other_name": "TEXT", "other_phone": "TEXT", # башка адамга / жеткирүүдө алуучу
              "p_addr": "TEXT", "d_addr": "TEXT",
              "wait_fee": "REAL DEFAULT 0",                # акылуу күтүү
              "share_tok": "TEXT"},                        # сапарды бөлүшүү шилтемеси
}


def init_db():
    """Таблицаларды түзөт. Кайра-кайра чакырса коопсуз."""
    for sql in SCHEMA:
        query(sql)
    for table, cols in NEW_COLUMNS.items():
        for col, typ in cols.items():
            try:
                query("ALTER TABLE %s ADD COLUMN %s %s" % (table, col, typ))
            except Exception:
                pass                      # тилке мурунтан бар
    os.makedirs(UPLOADS, exist_ok=True)


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


def is_admin(uid):
    u = get_user(uid) or {}
    return bool(u) and (u.get("tg_uid") in ADMIN_IDS
                        or (u.get("phone") or "") in [phone_uid(p)[3:] for p in ADMIN_PHONES
                                                      if phone_uid(p)])


def tg_of(uid):
    """Билдирүү кайда барат: Telegram чаты (же None)."""
    if uid.startswith("tg:"):
        return uid
    u = get_user(uid) or {}
    return u.get("tg_uid") if u.get("notify", 1) else None


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
    if AREA_ON and not in_area(lat, lon):
        cur = query("SELECT out_since FROM drivers WHERE uid=?", (uid,), "one")
        fields["out_since"] = (cur and cur["out_since"]) or t
    else:
        fields["out_since"] = None
    if live_period:
        fields["live_until"] = (msg_date or t) + live_period
    set_driver(uid, **fields)


def is_available(d, t=None):
    t = t or now()
    if not d or d["status"] != "active" or not d["online"] or d["busy_ride"]:
        return False
    if d["lat"] is None or (d["balance"] or 0) < min_balance():
        return False
    live = (d["live_until"] or 0) > t
    fresh = t - (d["loc_at"] or 0) < LOC_TTL_SEC
    return live or fresh


OUT_MAX_SEC = float(os.environ.get("OUT_MAX_MIN") or 60) * 60   # аймактан сыртта ушунча турса — өзү линиядан чыгат


def auto_offline_out():
    """Аймактан сыртта OUT_MAX_SEC'тен ашык линияда турган (сапарсыз) айдоочуларды офлайн кылат."""
    if not AREA_ON:
        return []
    rows = query("SELECT uid FROM drivers WHERE online=1 AND busy_ride IS NULL AND out_since IS NOT NULL "
                 "AND out_since<?", (now() - OUT_MAX_SEC,), "all")
    for d in rows:
        set_driver(d["uid"], online=0, live_until=None, out_since=None)
    return [d["uid"] for d in rows]


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


def request_topup(driver, claimed, proof):
    """Айдоочу чектин сүрөтүн жүктөдү → админ текшерет."""
    return query("INSERT INTO balance_tx (driver, amount, kind, status, claimed, proof, at) "
                 "VALUES (?, 0, 'topup', 'pending', ?, ?, ?)",
                 (driver, claimed, proof, now()), "id")


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


# ==================== Иштөө аймагы ====================
# Сервис бир аймакта гана иштейт (демейки: Базар-Коргон району).
# Чеги OpenStreetMap'тен бир жолу жүктөлүп, DATA_DIR'ге сакталат.
# Жүктөлбөсө — болжолдуу төрт бурчтук (AREA_BBOX). SERVICE_AREA=off → бүт өлкө.

AREA_ON = (os.environ.get("SERVICE_AREA") or "on").lower() not in ("off", "0", "")
AREA_CITY = os.environ.get("AREA_CITY") or "Базар-Коргон"
AREA_NAME = os.environ.get("AREA_NAME") or "Базар-Коргон району"
AREA_QUERY = os.environ.get("AREA_QUERY") or "Базар-Коргонский район"
# түштүк, батыш, түндүк, чыгыш
AREA_BBOX = [float(x) for x in (os.environ.get("AREA_BBOX") or "40.96,72.45,41.60,73.25").split(",")]
_area = {"geojson": None, "source": "bbox", "units": []}   # units: [{"name", "city", "gj", "approx"}]


def _bbox_geojson(b):
    s_, w, n, e = b
    return {"type": "Polygon", "coordinates": [[[w, s_], [e, s_], [e, n], [w, n], [w, s_]]]}


def _rings(gj):
    """GeoJSON → тышкы шакекчелердин тизмеси [[lon, lat], ...]."""
    if not gj:
        return []
    if gj["type"] == "Polygon":
        return [gj["coordinates"][0]]
    if gj["type"] == "MultiPolygon":
        return [poly[0] for poly in gj["coordinates"]]
    return []


def _in_ring(lat, lon, ring):
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / ((yj - yi) or 1e-12) + xi:
            inside = not inside
        j = i
    return inside


def area_geojson():
    return _area["geojson"] or _bbox_geojson(AREA_BBOX)


def in_area(lat, lon):
    if not AREA_ON:
        return True
    return any(_in_ring(lat, lon, r) for r in _rings(area_geojson()))


def unit_city(name):
    """«Базар-Коргон району» / «Базар-Коргон шаары» → «Базар-Коргон» (тариф ушул ат менен)."""
    for suf in (" району", " шаары", " облусу"):
        if name.endswith(suf):
            return name[: -len(suf)]
    return name


def area_gen():
    """Илик жөндөмө: «Базар-Коргон районунун», «Манас шаарынын», же «иштөө аймагынын»."""
    if not AREA_ON:
        return "иштөө аймагынын"
    names = [u["name"] for u in _area["units"]] or [AREA_NAME]
    if len(names) != 1:
        return "иштөө аймагынын"
    n = names[0]
    if n.endswith(" району"):
        return n[:-7] + " районунун"
    if n.endswith(" шаары"):
        return n[:-6] + " шаарынын"
    return n + " аймагынын"


# ---------- Аймакты тизмеден тандоо (облус → район/шаар), чектер OpenStreetMap'тен ----------
GEO_KG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "geo_kg.json")
TOWN_RADIUS_KM = 5.0


def geo_kg():
    with open(GEO_KG_PATH, encoding="utf-8") as f:
        return json.load(f)


def geo_find(name, ob=None):
    """Тизмеден район/шаарды табат: {"name", "ru", "ob", "ob_ru", "kind"}."""
    for o in geo_kg():
        if ob and o["name"] != ob:
            continue
        for u in o["units"]:
            if u["name"] == name:
                return {"name": u["name"], "ru": u["ru"], "ob": o["name"], "ob_ru": o.get("ru", ""), "kind": u["kind"]}
            for t in u.get("towns") or []:
                if t["name"] == name:
                    return {"name": t["name"], "ru": t["ru"], "ob": o["name"], "ob_ru": o.get("ru", ""), "kind": "town"}
    return None


def _circle(lat, lon, km, n=32):
    import math
    pts = []
    for i in range(n + 1):
        a = 2 * math.pi * i / n
        pts.append([round(lon + km / (111.32 * math.cos(math.radians(lat))) * math.cos(a), 6),
                    round(lat + km / 110.57 * math.sin(a), 6)])
    return {"type": "Polygon", "coordinates": [pts]}


def _sel_path():
    return os.path.join(DATA_DIR, "area_sel.json")


def _unit_cache(u):
    return os.path.join(DATA_DIR, "area_%s.json" % "".join(c for c in (u["ru"] + u["ob"]) if c.isalnum()))


def _fetch_unit_poly(u):
    """OSM'ден чек. Табылбаса (кичи шаар — чекит гана) → 5 км тегерек. Кайтарат: (gj, approx)."""
    import urllib.parse
    import urllib.request
    import time as _t
    qs = [u["ru"] + (", " + u["ob_ru"] if u.get("ob_ru") else ""), u["ru"], u["name"]]
    point = None
    for q in qs:
        url = ("https://nominatim.openstreetmap.org/search?format=json&polygon_geojson=1"
               "&polygon_threshold=0.001&countrycodes=kg&limit=5&q=" + urllib.parse.quote(q))
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "TaksiTAP/1.0 (taxi service)"})
            with urllib.request.urlopen(req, timeout=15) as r:
                res = json.loads(r.read().decode())
        except Exception as e:
            print("  Аймак: %s — жүктөлбөдү (%s)" % (u["name"], e), flush=True)
            res = []
        for x in res:
            gj = x.get("geojson") or {}
            if x.get("osm_type") == "relation" and gj.get("type") in ("Polygon", "MultiPolygon"):
                return gj, False
            if point is None and x.get("lat"):
                point = (float(x["lat"]), float(x["lon"]))
        _t.sleep(1.1)                                   # Nominatim: секундуна 1 суроо
    if point:
        return _circle(point[0], point[1], TOWN_RADIUS_KM), True
    return None, False


def _apply_units(units):
    """units: [{"name","gj","approx"}] → жалпы чек, аты, борбордук шаар, bbox."""
    global AREA_NAME, AREA_CITY, AREA_BBOX
    polys = []
    for u in units:
        gj = u["gj"]
        polys += [gj["coordinates"]] if gj["type"] == "Polygon" else list(gj["coordinates"])
    _area.update(units=[dict(name=u["name"], city=unit_city(u["name"]), gj=u["gj"], approx=u.get("approx"))
                        for u in units],
                 geojson={"type": "MultiPolygon", "coordinates": polys}, source="list")
    AREA_NAME = ", ".join(u["name"] for u in units)
    AREA_CITY = unit_city(units[0]["name"])
    pts = [p for r in _rings(_area["geojson"]) for p in r]
    AREA_BBOX = [min(p[1] for p in pts), min(p[0] for p in pts), max(p[1] for p in pts), max(p[0] for p in pts)]


def set_area_units(names):
    """Админ тизмеден тандады: [{"name", "ob"}, ...]. Ката болсо {"error", "name"}."""
    if not names or len(names) > 12:
        return {"error": "bad_count"}
    units = []
    for n in names:
        u = geo_find(n.get("name"), n.get("ob"))
        if not u:
            return {"error": "unknown", "name": n.get("name")}
        try:
            with open(_unit_cache(u), encoding="utf-8") as f:
                c = json.load(f)
            gj, approx = c["gj"], c.get("approx")
        except (OSError, ValueError, KeyError):
            gj, approx = _fetch_unit_poly(u)
            if not gj:
                return {"error": "not_found", "name": u["name"]}
            os.makedirs(DATA_DIR, exist_ok=True)
            with open(_unit_cache(u), "w", encoding="utf-8") as f:
                json.dump({"gj": gj, "approx": approx}, f)
        units.append(dict(u, gj=gj, approx=approx))
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(_sel_path(), "w", encoding="utf-8") as f:
        json.dump([{"name": u["name"], "ob": u["ob"]} for u in units], f, ensure_ascii=False)
    try:
        os.remove(_custom_path())                       # тизмеден тандалды — колго тартылган чек өчөт
    except OSError:
        pass
    _apply_units(units)
    return {"ok": True, "units": [{"name": u["name"], "approx": u["approx"]} for u in units]}


def area_selection():
    try:
        with open(_sel_path(), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        u = geo_find(AREA_NAME)
        return [{"name": u["name"], "ob": u["ob"]}] if u else []


def area_info():
    gj = area_geojson()
    pts = [p for r in _rings(gj) for p in r]
    lons, lats = [p[0] for p in pts], [p[1] for p in pts]
    return {"on": AREA_ON, "name": AREA_NAME, "city": AREA_CITY,
            "center": list(CITIES.get(AREA_CITY) or ((min(lats) + max(lats)) / 2,
                                                     (min(lons) + max(lons)) / 2)),
            "bbox": [min(lats), min(lons), max(lats), max(lons)],
            "geojson": gj, "source": _area["source"], "gen": area_gen(),
            "units": [{"name": u["name"], "approx": u.get("approx")} for u in _area["units"]],
            "selection": area_selection()}


def _custom_path():
    return os.path.join(DATA_DIR, "area_custom.json")


def set_custom_area(points):
    """
    Админ картага тарткан чек: [[lat, lon], ...] (кеминде 3 чекит).
    OSM чегинин ордуна колдонулат; reset_area() менен OSM'ге кайтат.
    """
    pts = []
    for p in points or []:
        try:
            lat, lon = float(p[0]), float(p[1])
        except (TypeError, ValueError, IndexError):
            return False
        if not (39 <= lat <= 44 and 69 <= lon <= 81):      # Кыргызстандын чеги
            return False
        pts.append([round(lon, 6), round(lat, 6)])
    if len(pts) < 3 or len(pts) > 500:
        return False
    if pts[0] != pts[-1]:
        pts.append(pts[0])
    gj = {"type": "Polygon", "coordinates": [pts]}
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(_custom_path(), "w", encoding="utf-8") as f:
        json.dump(gj, f)
    _area.update(geojson=gj, source="custom")
    return True


def reset_area():
    try:
        os.remove(_custom_path())
    except OSError:
        pass
    _area.update(geojson=None, source="bbox", units=[])
    load_area(fetch=False)


def load_area(fetch=True):
    """Аймактын чеги: админ тарткан → сакталган OSM → OpenStreetMap'тен жүктөө."""
    if not AREA_ON:
        return
    try:
        with open(_custom_path(), encoding="utf-8") as f:
            _area.update(geojson=json.load(f), source="custom")
            return
    except (OSError, ValueError):
        pass
    try:                                                # тизмеден тандалган райондор/шаарлар
        with open(_sel_path(), encoding="utf-8") as f:
            sel = json.load(f)
        if sel:
            if fetch:
                r = set_area_units(sel)
                if r.get("ok"):
                    print("  Аймак: %s (тизмеден)" % AREA_NAME, flush=True)
                    return
            else:
                units = []
                for n in sel:
                    u = geo_find(n["name"], n.get("ob"))
                    with open(_unit_cache(u), encoding="utf-8") as f:
                        c = json.load(f)
                    units.append(dict(u, gj=c["gj"], approx=c.get("approx")))
                _apply_units(units)
                return
    except (OSError, ValueError, KeyError, TypeError):
        pass
    path = os.path.join(DATA_DIR, "area_%s.json" % "".join(c for c in AREA_QUERY if c.isalnum()))
    try:
        with open(path, encoding="utf-8") as f:
            _area.update(geojson=json.load(f), source="osm")
            return
    except (OSError, ValueError):
        pass
    if not fetch:
        return
    import urllib.parse
    import urllib.request
    url = ("https://nominatim.openstreetmap.org/search?format=json&polygon_geojson=1"
           "&polygon_threshold=0.001&countrycodes=kg&limit=5&q=" + urllib.parse.quote(AREA_QUERY))
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "TaksiTAP/1.0 (taxi service)"})
        with urllib.request.urlopen(req, timeout=15) as r:
            res = json.loads(r.read().decode())
        for x in res:
            gj = x.get("geojson") or {}
            if x.get("osm_type") == "relation" and gj.get("type") in ("Polygon", "MultiPolygon"):
                os.makedirs(DATA_DIR, exist_ok=True)
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(gj, f)
                _area.update(geojson=gj, source="osm")
                print("  Аймак: %s (OpenStreetMap)" % x.get("display_name", "")[:60], flush=True)
                return
        print("  Аймак: OSM'де табылган жок — болжолдуу чек колдонулат", flush=True)
    except Exception as e:
        print("  Аймак: жүктөлбөдү (%s) — болжолдуу чек" % e, flush=True)


def city_of(lat, lon):
    if AREA_ON:
        for u in _area["units"]:
            if any(_in_ring(lat, lon, r) for r in _rings(u["gj"])):
                return u["city"]
        return AREA_CITY if in_area(lat, lon) else None
    best, best_d = None, CITY_RADIUS_KM
    for name, (clat, clon) in CITIES.items():
        d = haversine_km(lat, lon, clat, clon)
        if d < best_d:
            best, best_d = name, d
    return best


def get_tariff(city):
    row = query("SELECT * FROM tariffs WHERE city=?", (city or "",), "one")
    return row or dict(CITY_TARIFFS.get(city) or DEFAULT_TARIFF, city=city)


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
    """Тез баалоо (маршрутсуз): түз сызык × коэффициент. ETA жана радиус үчүн."""
    return haversine_km(lat1, lon1, lat2, lon2) * ROAD_FACTOR


_ROUTES = {}
_ROUTES_LOCK = threading.Lock()


def route(lat1, lon1, lat2, lon2):
    """
    Жол боюнча маршрут (OSRM): {"km", "min", "coords": [[lat, lon], ...], "real": bool}.
    OSRM жооп бербесе — түз сызык (real=False), сервис токтобойт.
    """
    key = tuple(round(x, 4) for x in (lat1, lon1, lat2, lon2))
    with _ROUTES_LOCK:
        hit = _ROUTES.get(key)
    if hit:
        return hit
    out = None
    if OSRM_URL:
        import urllib.request
        url = "%s/route/v1/driving/%.6f,%.6f;%.6f,%.6f?overview=full&geometries=geojson" % (
            OSRM_URL, lon1, lat1, lon2, lat2)
        try:
            with urllib.request.urlopen(url, timeout=4) as r:
                j = json.loads(r.read().decode())
            rt = j["routes"][0]
            pts = [[c[1], c[0]] for c in rt["geometry"]["coordinates"]]
            step = max(1, len(pts) // 400)              # картага 400 чекит жетиштүү
            pts = pts[::step] + ([pts[-1]] if (len(pts) - 1) % step else [])
            out = {"km": round(rt["distance"] / 1000.0, 2),
                   "min": round(rt["duration"] / 60.0 * TRAFFIC_FACTOR, 1),
                   "coords": pts, "real": True}
        except Exception as e:
            print("  OSRM:", e, flush=True)
    if not out:
        km = road_km(lat1, lon1, lat2, lon2)
        out = {"km": round(km, 2), "min": round(km / AVG_SPEED_KMH * 60, 1),
               "coords": [[lat1, lon1], [lat2, lon2]], "real": False}
    with _ROUTES_LOCK:
        if len(_ROUTES) > 2000:
            _ROUTES.clear()
        if out["real"]:
            _ROUTES[key] = out
    return out


def price_of(t, km, minutes, k=1.0):
    """Баа = max(минимум, отуруу + км×a + мүн×b) × k, жакынкы 10 сомго тегеректелет."""
    raw = (t["base"] + t["per_km"] * km + t["per_min"] * minutes) * k
    return int(max(t["min_price"] * k, math.floor(raw / 10.0 + 0.5) * 10))


def quote(p_lat, p_lon, d_lat=None, d_lon=None, cls="econom"):
    """Маршрут → баа (price_of). Баа заказ берилгенде белгиленет, жолдо өзгөрбөйт.
    prices — ар бир класстын баасы (класстын коэффициенти × тариф)."""
    city = city_of(p_lat, p_lon)
    t = get_tariff(city)
    k = surge_k(city)
    cfg = class_config()
    if cls not in cfg or not cfg[cls]["on"]:
        cls = next(c for c in cfg if cfg[c]["on"])
    base = {"city": city, "dist_km": None, "price": None, "surge": k, "tariff": t, "cls": cls,
            "prices": {c: None for c in cfg if cfg[c]["on"]}}
    if d_lat is not None and city and not in_area(d_lat, d_lon):
        # шаар аралык каттамдар — бизде жок (аларды башка айдоочулар иштейт)
        return dict(base, dest_out=True)
    if d_lat is None:
        return base
    rt = route(p_lat, p_lon, d_lat, d_lon)
    km, minutes = rt["km"], rt["min"]
    prices = {c: price_of(t, km, minutes, k * cfg[c]["k"]) for c in cfg if cfg[c]["on"]}
    return dict(base, dist_km=round(km, 1), minutes=round(minutes), price=prices[cls],
                prices=prices, route=rt)


# ==================== Класстар ====================
# Коэффициент тарифке көбөйтүлөт. Админ «Тарифтер» бөлүмүнөн өзгөртөт.
CLASSES = {
    "econom": {"name": "Эконом", "k": 1.0, "on": True},
    "comfort": {"name": "Комфорт", "k": 1.3, "on": False},    # айдоочулары чыкканда күйгүзүлөт
    "minivan": {"name": "Минивэн", "k": 1.5, "on": False},
    "delivery": {"name": "Жеткирүү", "k": 1.0, "on": True},
}
DEFAULT_DRIVER_CLASSES = ("econom", "delivery")


def class_config():
    saved = get_setting("classes") or {}
    out = {}
    for c, d in CLASSES.items():
        x = dict(d)
        x.update({k: v for k, v in (saved.get(c) or {}).items() if k in ("k", "on")})
        out[c] = x
    if not any(x["on"] for x in out.values()):
        out["econom"]["on"] = True             # баары өчсө — заказ бербей калбасын
    return out


def set_class_config(rows):
    clean = {}
    for c, x in (rows or {}).items():
        if c not in CLASSES:
            return False
        try:
            k = float(x.get("k", CLASSES[c]["k"]))
        except (TypeError, ValueError):
            return False
        if not 0.5 <= k <= 5:
            return False
        clean[c] = {"k": k, "on": bool(x.get("on", True))}
    if not any(x["on"] for x in clean.values()) and len(clean) == len(CLASSES):
        return False                           # жок дегенде бир класс күйүк болушу керек
    set_setting("classes", clean)
    return True


def driver_classes(d):
    raw = (d or {}).get("classes")
    return set(raw.split(",")) if raw else set(DEFAULT_DRIVER_CLASSES)


def can_take(d, cls):
    """Комфорт / минивэн айдоочусу эконом заказды да ала алат."""
    have = driver_classes(d)
    cls = cls or "econom"
    return cls in have or (cls == "econom" and bool(have & {"comfort", "minivan"}))


# ==================== Акылуу күтүү ====================

def wait_config():
    w = get_setting("wait") or {}
    return {"free_min": float(w.get("free_min", 3)), "per_min": float(w.get("per_min", 3))}


def set_wait_config(free_min, per_min):
    if free_min is None or per_min is None or not (0 <= free_min <= 30 and 0 <= per_min <= 100):
        return False
    set_setting("wait", {"free_min": free_min, "per_min": per_min})
    return True


def wait_fee_for(r, at=None):
    """Айдоочу келгенден кийин акысыз мүнөттөр, андан ары ар бир баштал мүнөт акылуу."""
    if not r.get("arrived_at"):
        return 0
    w = wait_config()
    over = (at or now()) - r["arrived_at"] - w["free_min"] * 60
    return int(math.ceil(over / 60.0) * w["per_min"]) if over > 0 else 0


# ==================== Сапар ====================
# searching → accepted → arrived → in_trip → completed
#                                            ↘ cancelled (каалаган кадамда)

def create_ride(passenger, q, p_lat, p_lon, d_lat=None, d_lon=None, note=None, source="web",
                promo=None, discount=0, scheduled_at=None, other_name=None, other_phone=None,
                p_addr=None, d_addr=None):
    status = "scheduled" if scheduled_at else "searching"
    rid = query("INSERT INTO rides (passenger, city, p_lat, p_lon, d_lat, d_lon, dist_km, "
                "price, surge, status, created_at, note, source, promo, discount, scheduled_at, "
                "cls, other_name, other_phone, p_addr, d_addr) VALUES "
                "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (passenger, q["city"], p_lat, p_lon, d_lat, d_lon, q["dist_km"],
                 q["price"], q["surge"], status, now(), note, source, promo,
                 discount or 0, scheduled_at, q.get("cls") or "econom", other_name, other_phone,
                 p_addr, d_addr), "id")
    log_event(rid, status, passenger)
    return rid


def get_ride(rid):
    return query("SELECT * FROM rides WHERE id=?", (rid,), "one")


def active_ride_of(uid):
    return query("SELECT * FROM rides WHERE (passenger=? OR driver=?) AND status IN "
                 "('scheduled','searching','accepted','arrived','in_trip') ORDER BY id DESC LIMIT 1",
                 (uid, uid), "one")


# Алдын ала заказ: убактысынан SCHEDULE_LEAD мүнөт мурун издөө башталат.
SCHEDULE_LEAD = 10 * 60
SCHEDULE_MIN, SCHEDULE_MAX = 20 * 60, 3 * 86400


def activate_scheduled():
    """Убактысы жеткен алдын ала заказдарды издөөгө чыгарат. Ошол заказдарды кайтарат."""
    out = []
    for r in query("SELECT * FROM rides WHERE status='scheduled' AND scheduled_at<=?",
                   (now() + SCHEDULE_LEAD,), "all"):
        n = query("UPDATE rides SET status='searching', created_at=? WHERE id=? AND status='scheduled'",
                  (now(), r["id"]), "count")
        if n:
            log_event(r["id"], "searching", "system")
            out.append(r)
    return out


def lost_orders(days=7):
    """Айдоочу табылбай калган заказдар — кайсы жерде айдоочу жетишпейт."""
    return query("SELECT id, p_lat, p_lon, created_at FROM rides WHERE status='cancelled' "
                 "AND cancel_by='system' AND created_at>=? ORDER BY id DESC LIMIT 500",
                 (now() - days * 86400,), "all")


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
    n = query("UPDATE rides SET tried=?, offered_to=NULL, offered_at=NULL WHERE id=? "
              "AND offered_to=?", (json.dumps(tried), rid, driver), "count")
    if n:
        add_activity(driver, ACT_SKIP)             # сунуштан баш тартты / жооп бербеди


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
    d = get_driver(driver)
    if d.get("busy_ride") and d["busy_ride"] != rid:
        set_driver(driver, next_ride=rid)        # азыркы сапарды бүтүрүп барат
    else:
        set_driver(driver, busy_ride=rid)
    log_event(rid, "accepted", driver)
    add_activity(driver, ACT_ACCEPT)
    return True


_NEXT = {"accepted": ("arrived", "arrived_at"),
         "arrived": ("in_trip", "started_at"),
         "in_trip": ("completed", "completed_at")}


def advance(rid, driver):
    """Айдоочунун кийинки кадамы. Жаңы абалды кайтарат же None."""
    r = get_ride(rid)
    if not r or r["driver"] != driver or r["status"] not in _NEXT:
        return None
    if (get_driver(driver) or {}).get("busy_ride") != rid:
        return None                              # кийинки заказ — азыркы бүтө элек
    new, col = _NEXT[r["status"]]
    if new == "in_trip":
        fee = wait_fee_for(r)
        if fee:
            query("UPDATE rides SET wait_fee=?, price=CASE WHEN price IS NULL THEN NULL "
                  "ELSE price+? END WHERE id=?", (fee, fee, rid))
    n = query("UPDATE rides SET status=?, %s=? WHERE id=? AND status=?" % col,
              (new, now(), rid, r["status"]), "count")
    if not n:
        return None
    log_event(rid, new, driver)
    if new == "completed":
        _finish(rid, driver)
    return new


# ==================== Активдүүлүк ====================
ACT_ACCEPT, ACT_DONE, ACT_SKIP, ACT_CANCEL = 1, 1, -3, -10


def add_activity(uid, delta):
    query("UPDATE drivers SET activity=MAX(0, MIN(100, COALESCE(activity,100)+?)) WHERE uid=?" if not IS_PG else
          "UPDATE drivers SET activity=GREATEST(0, LEAST(100, COALESCE(activity,100)+?)) WHERE uid=?", (delta, uid))


def _finish(rid, driver):
    add_activity(driver, ACT_DONE)
    r = get_ride(rid)
    d = get_driver(driver) or {}
    query("UPDATE drivers SET busy_ride=next_ride, next_ride=NULL, rides_done=rides_done+1 WHERE uid=?",
          (driver,))
    if d.get("home_on") and r["d_lat"] is not None and d.get("home_lat") is not None and \
            haversine_km(r["d_lat"], r["d_lon"], d["home_lat"], d["home_lon"]) < 1.5:
        set_driver(driver, home_on=0)            # үйгө жетти — режим өчөт
    if r.get("discount"):
        # промокод: жүргүнчү азыраак төлөдү — айырманы платформа айдоочуга кайтарат
        add_tx(driver, r["discount"], "promo", ride_id=rid)
    pct = commission_pct()
    if pct > 0 and r["price"]:
        fee = math.floor(r["price"] * pct / 100.0 + 0.5)        # бүтүн сомго
        if fee > 0:
            add_tx(driver, -fee, "commission", ride_id=rid)


def cancel(rid, by, allowed=("scheduled", "searching", "accepted", "arrived")):
    r = get_ride(rid)
    if not r or r["status"] not in allowed:
        return None
    n = query("UPDATE rides SET status='cancelled', cancel_by=? WHERE id=? AND status=?",
              (by, rid, r["status"]), "count")
    if not n:
        return None
    if r["driver"]:
        d = get_driver(r["driver"]) or {}
        if d.get("next_ride") == rid:
            set_driver(r["driver"], next_ride=None)
        elif d.get("busy_ride") == rid:
            set_driver(r["driver"], busy_ride=d.get("next_ride"), next_ride=None)
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


def rate_passenger(rid, driver, stars):
    r = get_ride(rid)
    if not r or r["driver"] != driver or r["status"] != "completed":
        return False
    if query("SELECT ride_id FROM passenger_ratings WHERE ride_id=?", (rid,), "one"):
        return False
    query("INSERT INTO passenger_ratings (ride_id, stars, at) VALUES (?, ?, ?)", (rid, stars, now()))
    u = get_user(r["passenger"]) or {}
    n = (u.get("p_rated") or 0) + 1
    avg = ((u.get("p_rating") or 5.0) * (n - 1) + stars) / n
    set_user(r["passenger"], p_rating=round(avg, 2), p_rated=n)
    return True


# ==================== Сакталган даректер ====================

def get_places(uid):
    u = get_user(uid) or {}
    try:
        saved = json.loads(u.get("places") or "{}")
    except ValueError:
        saved = {}
    recent, seen = [], set()
    for r in query("SELECT d_lat, d_lon, d_addr FROM rides WHERE passenger=? AND d_lat IS NOT NULL "
                   "AND d_addr IS NOT NULL AND status='completed' ORDER BY id DESC LIMIT 30", (uid,), "all"):
        k = (round(r["d_lat"], 3), round(r["d_lon"], 3))
        if k in seen:
            continue
        seen.add(k)
        recent.append({"name": r["d_addr"], "lat": r["d_lat"], "lon": r["d_lon"]})
        if len(recent) >= 4:
            break
    return {"home": saved.get("home"), "work": saved.get("work"), "recent": recent}


def set_place(uid, kind, lat=None, lon=None, name=""):
    if kind not in ("home", "work"):
        return False
    u = get_user(uid) or {}
    try:
        saved = json.loads(u.get("places") or "{}")
    except ValueError:
        saved = {}
    if lat is None:
        saved.pop(kind, None)
    else:
        saved[kind] = {"lat": lat, "lon": lon, "name": (name or "")[:80]}
    set_user(uid, places=json.dumps(saved, ensure_ascii=False))
    return True


# ==================== Чат ====================

MSG_MAX = 300


def add_message(rid, sender, text):
    text = (text or "").strip()[:MSG_MAX]
    if not text:
        return False
    if query("SELECT COUNT(*) AS n FROM messages WHERE ride_id=?", (rid,), "one")["n"] >= 100:
        return False
    query("INSERT INTO messages (ride_id, sender, text, at) VALUES (?, ?, ?, ?)", (rid, sender, text, now()))
    return True


def messages(rid):
    return query("SELECT id, sender, text, at FROM messages WHERE ride_id=? ORDER BY id", (rid,), "all")


# ==================== Сапарды бөлүшүү ====================

def share_token(rid):
    r = get_ride(rid)
    if not r:
        return None
    if r.get("share_tok"):
        return r["share_tok"]
    tok = secrets.token_urlsafe(10)
    query("UPDATE rides SET share_tok=? WHERE id=?", (tok, rid))
    return tok


def ride_by_share(tok):
    if not tok or len(tok) > 40:
        return None
    return query("SELECT * FROM rides WHERE share_tok=?", (tok,), "one")


# ==================== Үйгө карай ====================
HOME_USES_PER_DAY = 2


def _today_str():
    return time.strftime("%Y-%m-%d", time.gmtime(now() + 6 * 3600))


def home_uses_left(d):
    used = (d.get("home_uses") or 0) if d.get("home_day") == _today_str() else 0
    return max(0, HOME_USES_PER_DAY - used)


def set_home_mode(uid, on):
    d = get_driver(uid) or {}
    if not on:
        set_driver(uid, home_on=0)
        return True
    if d.get("home_lat") is None or home_uses_left(d) <= 0:
        return False
    used = (d.get("home_uses") or 0) if d.get("home_day") == _today_str() else 0
    set_driver(uid, home_on=1, home_day=_today_str(), home_uses=used + 1)
    return True


def toward_home(d, ride):
    """Бара турган жер айдоочунун үйүнө азыркы жеринен кеминде 1 км жакын болсо — ылайык."""
    if not d.get("home_on"):
        return True
    if ride["d_lat"] is None or d.get("home_lat") is None or d.get("lat") is None:
        return False
    now_km = haversine_km(d["lat"], d["lon"], d["home_lat"], d["home_lon"])
    after_km = haversine_km(ride["d_lat"], ride["d_lon"], d["home_lat"], d["home_lon"])
    return after_km <= now_km - 1.0


# ==================== Кийинки заказ (сапар бүтө электе) ====================
CHAIN_KM = 1.5            # азыркы сапардын аягынан жаңы заказга чейин


def chain_drivers():
    """Сапарда жүргөн, кийинки заказы жок, сапары бүтүүгө жакын айдоочулар:
    [(driver, ride)] — ride: азыркы сапар (бара турган жери белгилүү)."""
    out = []
    t = now()
    for d in query("SELECT * FROM drivers WHERE online=1 AND status='active' AND busy_ride IS NOT NULL "
                   "AND next_ride IS NULL", (), "all"):
        if d["lat"] is None or (d["balance"] or 0) < min_balance():
            continue
        if not ((d["live_until"] or 0) > t or t - (d["loc_at"] or 0) < LOC_TTL_SEC):
            continue
        r = get_ride(d["busy_ride"])
        if not r or r["status"] != "in_trip" or r["d_lat"] is None:
            continue
        if haversine_km(d["lat"], d["lon"], r["d_lat"], r["d_lon"]) > 2.0:
            continue                             # аягына дагы алыс
        out.append((d, r))
    return out


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


def web_session_new(phone, name, kind="rider", agreed=False):
    tok = secrets.token_urlsafe(18)
    query("INSERT INTO web_sessions (token, phone, name, kind, created_at, agreed) VALUES (?, ?, ?, ?, ?, ?)",
          (tok, phone, name, kind, now(), 1 if agreed else 0))
    return tok


def web_session(tok):
    if not tok:
        return None
    return query("SELECT * FROM web_sessions WHERE token=?", (tok,), "one")


def web_session_verify(tok, phone_seen=None, tg_uid=None):
    """
    Номер дал келсе, сессияны ырастайт. Аккаунт = номер ('ph:+996...').
    tg_uid — ырастаган Telegram аккаунту: ага кийин билдирүүлөр барат.
    Админ сессиясы админ болбосо ырасталбайт.
    """
    s = web_session(tok)
    if not s:
        return None
    uid = phone_uid(s["phone"])
    if not uid:
        return None
    if phone_seen is not None and phone_uid(phone_seen) != uid:
        return None
    u = ensure_user(uid, s["name"] or "")
    fields = {"phone": uid[3:]}
    if s["name"] and not u.get("name"):
        fields["name"] = s["name"]
    if tg_uid:
        fields["tg_uid"] = tg_uid
    if s.get("agreed") and not u.get("terms_at"):
        fields["terms_at"] = now()               # шарттарга макулдук берилген убакыт
    set_user(uid, **fields)
    if s.get("kind") == "admin" and not is_admin(uid):
        return None
    query("UPDATE web_sessions SET verified=1, uid=? WHERE token=?", (uid, tok))
    return uid


def admins():
    """Билдирүү алуучу админдер (Telegram)."""
    out = list(ADMIN_IDS)
    for p in ADMIN_PHONES:
        t = tg_of(phone_uid(p) or "")
        if t and t not in out:
            out.append(t)
    return out


# ==================== Файлдар ====================

MAX_UPLOAD = 4 * 1024 * 1024


def save_upload(data_url):
    """'data:image/jpeg;base64,...' → файлдын аты. Сүрөт браузерде кичирейтилет."""
    if not isinstance(data_url, str) or not data_url.startswith("data:image/"):
        return None
    head, _, b64 = data_url.partition(",")
    ext = "png" if "png" in head else "webp" if "webp" in head else "jpg"
    try:
        raw = base64.b64decode(b64, validate=True)
    except ValueError:
        return None
    if not raw or len(raw) > MAX_UPLOAD:
        return None
    name = "%d_%s.%s" % (int(now()), secrets.token_hex(8), ext)
    os.makedirs(UPLOADS, exist_ok=True)
    with open(os.path.join(UPLOADS, name), "wb") as f:
        f.write(raw)
    return name


def upload_path(name):
    """Коопсуз жол: папкадан чыгып кетпейт."""
    name = os.path.basename(name or "")
    p = os.path.join(UPLOADS, name)
    return p if name and os.path.isfile(p) else None


def register_driver(uid, name, model, color, plate, docs):
    """Сайттан айдоочу болуу арызы. docs: {'license','techpass','car'} → файл аттары."""
    if name:
        set_user(uid, name=name)
    fields = dict(car_model=model, car_color=color, car_plate=plate, status="pending",
                  reject_note=None, doc_license=docs.get("license"),
                  doc_techpass=docs.get("techpass"), doc_car=docs.get("car"))
    if get_driver(uid):
        set_driver(uid, **fields)
    else:
        query("INSERT INTO drivers (uid, created_at) VALUES (?, ?)", (uid, now()))
        set_driver(uid, **fields)


def last_ride_of(uid, within_sec=900):
    """Активдүү сапар, же жакында бүткөнү (баалоо үчүн)."""
    r = active_ride_of(uid)
    if r:
        return r
    return query("SELECT * FROM rides WHERE passenger=? AND status IN ('completed','cancelled') "
                 "AND created_at>? ORDER BY id DESC LIMIT 1", (uid, now() - within_sec), "one")


def rated(rid):
    return query("SELECT ride_id FROM ratings WHERE ride_id=?", (rid,), "one") is not None


# ==================== Айдоочунун сайты ====================

def day_start(tz_hours=6):
    """Бишкек убактысы боюнча бүгүнкү күндүн башы."""
    t = now()
    return t - ((t + tz_hours * 3600) % 86400)


def driver_today(uid):
    r = query("SELECT COUNT(*) AS n, COALESCE(SUM(price), 0) AS s FROM rides "
              "WHERE driver=? AND status='completed' AND completed_at>=?",
              (uid, day_start()), "one")
    return {"rides": r["n"], "earned": int(r["s"] or 0)}


def driver_daily(uid, days=7):
    """Акыркы 7 күн: ар күнү канча сапар, канча сом, сапарда өткөн убакыт (мүн)."""
    t0 = day_start() - (days - 1) * 86400
    rows = query("SELECT price, completed_at, accepted_at FROM rides WHERE driver=? AND status='completed' "
                 "AND completed_at>=?", (uid, t0), "all")
    out = [{"day": t0 + i * 86400, "rides": 0, "earned": 0, "min": 0} for i in range(days)]
    for r in rows:
        i = int((r["completed_at"] - t0) // 86400)
        if 0 <= i < days:
            out[i]["rides"] += 1
            out[i]["earned"] += int(r["price"] or 0)
            if r["accepted_at"]:
                out[i]["min"] += max(0, (r["completed_at"] - r["accepted_at"]) / 60.0)
    for o in out:
        o["min"] = round(o["min"])
    return out


HEAT_CELL = 0.004          # ~400 м


def demand_heat(minutes=120):
    """Акыркы 2 саатта заказ көп болгон жерлер (айдоочуга «кайда барсам болот» картасы)."""
    rows = query("SELECT p_lat, p_lon, status, cancel_by FROM rides WHERE created_at>? AND p_lat IS NOT NULL",
                 (now() - minutes * 60,), "all")
    cells = {}
    for r in rows:
        k = (round(r["p_lat"] / HEAT_CELL), round(r["p_lon"] / HEAT_CELL))
        c = cells.setdefault(k, {"n": 0, "lost": 0})
        c["n"] += 1
        if r["status"] == "cancelled" and r["cancel_by"] == "system":
            c["lost"] += 1                         # айдоочу табылбай калган — талап бар
    return [{"lat": k[0] * HEAT_CELL, "lon": k[1] * HEAT_CELL, "n": v["n"], "lost": v["lost"]}
            for k, v in cells.items()]


def passenger_history(uid, limit=20):
    return query("SELECT id, status, price, discount, wait_fee, dist_km, p_addr, d_addr, cls, created_at, completed_at "
                 "FROM rides WHERE passenger=? ORDER BY id DESC LIMIT ?", (uid, limit), "all")


def driver_history(uid, limit=20):
    return query("SELECT id, status, price, dist_km, created_at, completed_at FROM rides "
                 "WHERE driver=? ORDER BY id DESC LIMIT ?", (uid, limit), "all")


def offer_for(uid):
    return query("SELECT * FROM rides WHERE status='searching' AND offered_to=? LIMIT 1",
                 (uid,), "one")


# ==================== Админ панели ====================

def _is_out(d):
    return bool(AREA_ON and d["lat"] is not None and not in_area(d["lat"], d["lon"]))


def admin_overview():
    t0 = day_start()
    drivers = query("SELECT d.*, u.name, u.phone FROM drivers d LEFT JOIN users u ON u.uid=d.uid",
                    (), "all")
    online = [d for d in drivers if is_available(d) or d["busy_ride"]]
    rides = query("SELECT r.*, u.name AS p_name, u.phone AS p_phone FROM rides r "
                  "LEFT JOIN users u ON u.uid=r.passenger WHERE r.status IN "
                  "('scheduled','searching','accepted','arrived','in_trip') ORDER BY r.id DESC", (), "all")
    today = query("SELECT COUNT(*) AS n, COALESCE(SUM(price),0) AS s FROM rides "
                  "WHERE status='completed' AND completed_at>=?", (t0,), "one")
    lost = query("SELECT COUNT(*) AS n FROM rides WHERE status='cancelled' AND cancel_by='system' "
                 "AND created_at>=?", (t0,), "one")
    fee = query("SELECT COALESCE(SUM(-amount),0) AS s FROM balance_tx WHERE kind='commission' "
                "AND at>=?", (t0,), "one")
    pend_tx = query("SELECT t.*, u.name, u.phone FROM balance_tx t LEFT JOIN users u ON "
                    "u.uid=t.driver WHERE t.status='pending' ORDER BY t.id", (), "all")
    return {
        "stats": {"online": sum(1 for d in online if not _is_out(d)), "busy": sum(1 for d in online if d["busy_ride"]),
                  "online_out": sum(1 for d in online if _is_out(d)),
                  "active": len(rides), "searching": sum(1 for r in rides if r["status"] == "searching"),
                  "done_today": today["n"], "gross_today": int(today["s"] or 0),
                  "fee_today": round(fee["s"] or 0), "lost_today": lost["n"]},
        "drivers": [{"uid": d["uid"], "name": d["name"], "pos": [d["lat"], d["lon"]],
                     "busy": bool(d["busy_ride"]), "plate": d["car_plate"]}
                    for d in online if d["lat"] is not None],
        "rides": [{"id": r["id"], "status": r["status"], "p": [r["p_lat"], r["p_lon"]],
                   "d": [r["d_lat"], r["d_lon"]] if r["d_lat"] is not None else None,
                   "price": r["price"], "city": r["city"], "passenger": r["p_name"],
                   "note": r.get("note"), "source": r.get("source") or "web",
                   "scheduled_at": r.get("scheduled_at"), "cls": r.get("cls") or "econom",
                   "other": " ".join(x for x in (r.get("other_name"), r.get("other_phone")) if x),
                   "phone": r["p_phone"], "driver": r["driver"],
                   "age": int(now() - (r["created_at"] or now()))} for r in rides],
        "pending_drivers": [{"uid": d["uid"], "name": d["name"], "phone": d["phone"],
                             "car": "%s %s" % (d["car_color"] or "", d["car_model"] or ""),
                             "plate": d["car_plate"]} for d in drivers if d["status"] == "pending"],
        "pending_topups": [{"id": t["id"], "uid": t["driver"], "name": t["name"],
                            "phone": t["phone"], "at": t["at"], "claimed": t["claimed"],
                            "proof": t["proof"]} for t in pend_tx],
    }


def admin_drivers():
    return query("SELECT d.uid, d.status, d.balance, d.rating, d.rides_done, d.car_model, "
                 "d.car_color, d.car_plate, d.online, d.busy_ride, d.loc_at, d.live_until, d.lat, d.lon, "
                 "d.doc_license, d.doc_techpass, d.doc_car, d.reject_note, d.created_at, d.classes, "
                 "u.name, u.phone FROM drivers d LEFT JOIN users u ON u.uid=d.uid "
                 "ORDER BY d.status='pending' DESC, d.rides_done DESC", (), "all")


def admin_rides(limit=60):
    return query("SELECT r.id, r.status, r.city, r.price, r.dist_km, r.created_at, r.cancel_by, "
                 "r.driver, p.name AS p_name, p.phone AS p_phone, du.name AS d_name "
                 "FROM rides r LEFT JOIN users p ON p.uid=r.passenger "
                 "LEFT JOIN users du ON du.uid=r.driver ORDER BY r.id DESC LIMIT ?",
                 (limit,), "all")


def all_tariffs():
    """Аймак күйүк болсо — ошол шаардын тарифи гана (башкалары колдонулбайт)."""
    saved = {t["city"]: t for t in query("SELECT * FROM tariffs", (), "all")}
    cities = (list(dict.fromkeys(u["city"] for u in _area["units"])) or [AREA_CITY]) if AREA_ON else list(CITIES)
    return [dict(saved.get(c) or dict(CITY_TARIFFS.get(c) or DEFAULT_TARIFF, city=c),
                 saved=c in saved) for c in cities]


# ==================== Жөндөөлөр (админ панелинен) ====================

_settings_cache = {}


def get_setting(key, default=None):
    """5 секунд кэш: dispatch ар 2 секундда ар бир айдоочу үчүн сурайт."""
    hit = _settings_cache.get(key)
    if hit and hit[0] > now():
        return hit[1] if hit[1] is not None else default
    row = query("SELECT value FROM settings WHERE key=?", (key,), "one")
    try:
        val = json.loads(row["value"]) if row else None
    except ValueError:
        val = None
    _settings_cache[key] = (now() + 5, val)
    return val if val is not None else default


def set_setting(key, value):
    _settings_cache.pop(key, None)
    query("DELETE FROM settings WHERE key=?", (key,))
    query("INSERT INTO settings (key, value) VALUES (?, ?)", (key, json.dumps(value, ensure_ascii=False)))


# ==================== Каржы ====================
# Комиссия: пайыз (percent) + бекер мезгил (free_until, Бишкек убактысы менен күн).
# free_until өткөндө бекер мезгил өзү бүтүп, пайыз иштей баштайт.

TZ = 6 * 3600   # Бишкек UTC+6


def finance_config():
    c = get_setting("finance") or {}
    return {"percent": float(c.get("percent", COMMISSION_PCT)),
            "free_until": c.get("free_until") or None,          # "2027-01-01"
            "min_balance": float(c.get("min_balance", MIN_BALANCE))}


def set_finance_config(percent, free_until=None, min_balance=0):
    if not (0 <= percent <= 30) or not (-100000 <= min_balance <= 100000):
        return False
    if free_until:
        try:
            time.strptime(free_until, "%Y-%m-%d")
        except ValueError:
            return False
    set_setting("finance", {"percent": round(percent, 2), "free_until": free_until or None,
                            "min_balance": min_balance})
    return True


def _date_ts(d):
    """'2027-01-01' → ошол күндүн башы (Бишкек), unix убакыт."""
    import calendar
    return calendar.timegm(time.strptime(d, "%Y-%m-%d")) - TZ


def free_active(cfg=None):
    cfg = cfg or finance_config()
    return bool(cfg["free_until"]) and now() < _date_ts(cfg["free_until"])


def commission_pct():
    cfg = finance_config()
    return 0.0 if free_active(cfg) else cfg["percent"]


def min_balance():
    return finance_config()["min_balance"]


def finance_mode_text():
    cfg = finance_config()
    if free_active(cfg):
        return "Бекер — %s чейин, андан кийин %g%%" % (cfg["free_until"], cfg["percent"])
    if cfg["percent"] <= 0:
        return "Бекер (комиссия жок)"
    return "Ар бир сапардан %g%%" % cfg["percent"]


def period_starts():
    """Бишкек убактысы менен: бүгүн, ушул жума (дүйшөмбүдөн), ушул ай."""
    t = now() + TZ
    lt = time.gmtime(t)
    day = t - (t % 86400)
    week = day - lt.tm_wday * 86400
    month = day - (lt.tm_mday - 1) * 86400
    return {"today": day - TZ, "week": week - TZ, "month": month - TZ}


def _ride_sum(since, driver=None):
    q = "SELECT COUNT(*) AS n, COALESCE(SUM(price),0) AS s FROM rides WHERE status='completed' AND completed_at>=?"
    args = [since]
    if driver:
        q += " AND driver=?"
        args.append(driver)
    r = query(q, tuple(args), "one")
    return int(r["n"]), float(r["s"] or 0)


def _tx_sum(kind, since, driver=None):
    q = "SELECT COALESCE(SUM(amount),0) AS s FROM balance_tx WHERE kind=? AND status='done' AND at>=?"
    args = [kind, since]
    if driver:
        q += " AND driver=?"
        args.append(driver)
    return float(query(q, tuple(args), "one")["s"] or 0)


def driver_finance(uid):
    """Айдоочунун кабинети: бүгүн / жума / ай — сапар, жүгүртүү, комиссия, колунда калганы."""
    out = {}
    for k, since in period_starts().items():
        n, gross = _ride_sum(since, uid)
        fee = -_tx_sum("commission", since, uid)
        out[k] = {"rides": n, "gross": int(gross), "fee": round(fee), "net": int(gross - fee)}
    return out


def admin_finance():
    ps = period_starts()
    totals = {}
    for k, since in ps.items():
        n, gross = _ride_sum(since)
        totals[k] = {"rides": n, "gross": int(gross),
                     "commission": round(-_tx_sum("commission", since)),
                     "topups": round(_tx_sum("topup", since))}
    # акыркы 6 ай (Бишкек убактысы менен)
    months = []
    lt = time.gmtime(now() + TZ)
    y, m = lt.tm_year, lt.tm_mon
    for _ in range(6):
        import calendar
        start = calendar.timegm((y, m, 1, 0, 0, 0)) - TZ
        ny, nm = (y + (m == 12), m % 12 + 1)
        end = calendar.timegm((ny, nm, 1, 0, 0, 0)) - TZ
        r = query("SELECT COUNT(*) AS n, COALESCE(SUM(price),0) AS s FROM rides WHERE status='completed' "
                  "AND completed_at>=? AND completed_at<?", (start, end), "one")
        c = query("SELECT COALESCE(SUM(-amount),0) AS s FROM balance_tx WHERE kind='commission' "
                  "AND status='done' AND at>=? AND at<?", (start, end), "one")
        months.append({"month": "%d-%02d" % (y, m), "rides": int(r["n"]), "gross": int(r["s"] or 0),
                       "commission": round(c["s"] or 0)})
        y, m = (y - (m == 1), (m - 2) % 12 + 1)
    months.reverse()
    drivers = []
    for d in query("SELECT d.uid, d.balance, d.status, u.name, u.phone FROM drivers d "
                   "LEFT JOIN users u ON u.uid=d.uid WHERE d.status IN ('active','blocked')", (), "all"):
        n, gross = _ride_sum(ps["month"], d["uid"])
        drivers.append({"uid": d["uid"], "name": d["name"], "phone": d["phone"], "status": d["status"],
                        "balance": round(d["balance"] or 0), "rides": n, "gross": int(gross),
                        "commission": round(-_tx_sum("commission", ps["month"], d["uid"]))})
    drivers.sort(key=lambda x: (-x["gross"], x["name"] or ""))
    return {"config": finance_config(), "mode": finance_mode_text(), "pct_now": commission_pct(),
            "totals": totals, "months": months, "drivers": drivers, "promos": list_promos()}


# ==================== Промокоддор ====================
# Жүргүнчүгө арзандатуу (сом). Айдоочу толук бааны алат: айырма анын балансына
# сапар бүткөндө кошулат (balance_tx kind='promo') — чыгым платформага.

def promo_norm(code):
    return "".join(c for c in (code or "").upper() if c.isalnum())[:20]


def check_promo(code, uid, price=None):
    """(арзандатуу_сом, None) же (0, 'себеби')."""
    code = promo_norm(code)
    p = query("SELECT * FROM promos WHERE code=?", (code,), "one") if code else None
    if not p or not p["active"]:
        return 0, "Мындай промокод жок"
    if p["expires"] and now() >= _date_ts(p["expires"]) + 86400:
        return 0, "Промокоддун мөөнөтү бүткөн"
    if query("SELECT id FROM rides WHERE promo=? AND passenger=? AND status<>'cancelled'",
             (code, uid), "one"):
        return 0, "Бул промокодду колдонуп койгонсуз"
    if p["max_uses"] and promo_uses(code) >= p["max_uses"]:
        return 0, "Промокоддун саны бүттү"
    if p["first_only"] and query("SELECT id FROM rides WHERE passenger=? AND status='completed'",
                                 (uid,), "one"):
        return 0, "Промокод биринчи сапар үчүн гана"
    amount = float(p["amount"])
    if price:
        amount = min(amount, max(0, price - 10))      # кеминде 10 сом төлөйт
    return amount, None


def promo_uses(code):
    return query("SELECT COUNT(*) AS n FROM rides WHERE promo=? AND status<>'cancelled'",
                 (code,), "one")["n"]


def list_promos():
    rows = query("SELECT * FROM promos ORDER BY created_at DESC", (), "all")
    for p in rows:
        p["uses"] = promo_uses(p["code"])
        p["spent"] = round(query("SELECT COALESCE(SUM(amount),0) AS s FROM balance_tx t JOIN rides r "
                                 "ON r.id=t.ride_id WHERE t.kind='promo' AND r.promo=?",
                                 (p["code"],), "one")["s"] or 0)
    return rows


def save_promo(code, amount, first_only=True, max_uses=0, expires=None, active=True):
    code = promo_norm(code)
    if len(code) < 3 or not (0 < amount <= 5000) or not (0 <= max_uses <= 100000):
        return False
    if expires:
        try:
            time.strptime(expires, "%Y-%m-%d")
        except ValueError:
            return False
    if query("SELECT code FROM promos WHERE code=?", (code,), "one"):
        query("UPDATE promos SET amount=?, first_only=?, max_uses=?, expires=?, active=? WHERE code=?",
              (amount, 1 if first_only else 0, max_uses, expires or None, 1 if active else 0, code))
    else:
        query("INSERT INTO promos (code, amount, first_only, max_uses, expires, active, created_at) "
              "VALUES (?, ?, ?, ?, ?, ?, ?)",
              (code, amount, 1 if first_only else 0, max_uses, expires or None, 1 if active else 0, now()))
    return True
