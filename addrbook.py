"""
Такси ТАП! — даректер китепчеси (көчөлөр, айылдар, белгилүү жерлер).

Жүргүнчү «Кайдан / Кайда» деп жазганда сунуштар ушул тизмеден чыгат,
ошондуктан баа ар дайым так (тандалган жердин координаты бар).

Тизме эки жолдон толот:
  1) OpenStreetMap (Overpass) — аймактагы аталышы бар көчөлөр, айылдар, жайлар;
  2) админ — «Даректер» бөлүмүнөн колу менен кошот / оңдойт / жашырат.
"""
import json
import math
import re
import threading
import time
import urllib.parse
import urllib.request

import core

OVERPASS = ["https://overpass-api.de/api/interpreter",
            "https://overpass.kumi.systems/api/interpreter"]

KINDS = {          # түрү: (белги, аталышы)
    "street": ("🛣", "Көчө"), "village": ("🏘", "Айыл / кичи район"), "market": ("🛒", "Базар"),
    "school": ("🏫", "Мектеп / окуу жай"), "health": ("🏥", "Оорукана / дарыкана"),
    "mosque": ("🕌", "Мечит"), "food": ("🍽", "Кафе / ашкана"), "shop": ("🏪", "Дүкөн"),
    "bank": ("🏦", "Банк"), "fuel": ("⛽", "Май куюучу жай"), "gov": ("🏛", "Мекеме"),
    "bus": ("🚌", "Бекет / автовокзал"), "poi": ("📍", "Башка жер"),
}

_cache = {"rows": None}
_lock = threading.Lock()
import_state = {"running": False, "last": None, "added": 0, "error": None}

_STOP = {"улица", "ул", "көчөсү", "көчөсу", "көчө", "кочосу", "кочо", "переулок", "пер", "проспект", "пр",
         "микрорайон", "мкр", "айылы", "айыл", "село", "с", "кичи", "район", "тупик", "проезд"}


def norm(s):
    """Издөө үчүн: кичине тамга, ө→о, ү→у, ң→н, ё→е, тыныш белгилер жок."""
    s = (s or "").lower().replace("ё", "е").replace("ө", "о").replace("ү", "у").replace("ң", "н")
    s = re.sub(r"[^\w\s]", " ", s)
    return " ".join(w for w in s.split() if w not in _STOP)


def pretty(name):
    """«Юбилейная улица» → «Юбилейная көчөсү», «улица Ленина» → «Ленина көчөсү»."""
    n = (name or "").strip()
    m = re.match(r"^(?:улица|ул\.)\s+(.+)$", n, re.I)
    if m:
        return m.group(1) + " көчөсү"
    m = re.match(r"^(.+?)\s+(?:улица|ул\.?)$", n, re.I)
    if m:
        return m.group(1) + " көчөсү"
    m = re.match(r"^(.+?)\s+переулок$", n, re.I)
    if m:
        return m.group(1) + " тыкыры"
    return n


# ==================== Сактоо ====================

def _rows():
    with _lock:
        if _cache["rows"] is None:
            _cache["rows"] = core.query("SELECT * FROM addresses WHERE hidden=0 AND "
                                        "(status IS NULL OR status='ok')", (), "all")
            for r in _cache["rows"]:
                r["_n"] = norm(r["name"] + " " + (r.get("aliases") or "")).split()
                r["_a"] = set(norm(r.get("area") or "").split())
        return _cache["rows"]


def _reset():
    with _lock:
        _cache["rows"] = None


def count():
    r = core.query("SELECT COUNT(*) AS n, SUM(CASE WHEN source='admin' THEN 1 ELSE 0 END) AS a, "
                   "SUM(hidden) AS h, SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END) AS p, "
                   "SUM(CASE WHEN approx=1 AND hidden=0 THEN 1 ELSE 0 END) AS x FROM addresses", (), "one")
    return {"total": r["n"] or 0, "admin": r["a"] or 0, "hidden": r["h"] or 0,
            "pending": r["p"] or 0, "approx": r["x"] or 0}


def save(name, kind, lat, lon, aliases="", area="", aid=None, source="admin"):
    name = (name or "").strip()[:80]
    if not name or kind not in KINDS or lat is None or lon is None:
        return None
    if core.AREA_ON and not core.in_area(lat, lon):
        return None
    aliases = ", ".join(a.strip() for a in (aliases or "").split(",") if a.strip())[:200]
    area = (area or "").strip()[:60]
    if aid:
        core.query("UPDATE addresses SET name=?, kind=?, lat=?, lon=?, aliases=?, area=?, source='admin', "
                   "approx=0, status='ok' WHERE id=?", (name, kind, lat, lon, aliases, area, aid))
    else:
        aid = core.query("INSERT INTO addresses (name, kind, lat, lon, aliases, area, source, hidden, osm_key, created_at, "
                         "approx, status, votes) VALUES (?, ?, ?, ?, ?, ?, ?, 0, NULL, ?, 0, 'ok', 0)",
                         (name, kind, lat, lon, aliases, area, source, core.now()), "id")
    _reset()
    return aid


def set_hidden(aid, hidden):
    core.query("UPDATE addresses SET hidden=? WHERE id=?", (1 if hidden else 0, aid))
    _reset()


def delete(aid):
    core.query("DELETE FROM addresses WHERE id=?", (aid,))
    _reset()


def view(r):
    ico = KINDS.get(r["kind"], KINDS["poi"])[0]
    return {"id": r["id"], "name": r["name"], "kind": r["kind"], "icon": ico, "area": r.get("area") or "",
            "lat": r["lat"], "lon": r["lon"], "aliases": r.get("aliases") or "", "source": r.get("source"),
            "hidden": bool(r.get("hidden")), "approx": bool(r.get("approx")),
            "pending": r.get("status") == "pending", "votes": r.get("votes") or 0}


# ==================== Издөө ====================

def search(q, near=None, limit=8):
    toks = norm(q).split()
    if not toks:
        return []
    scored = []
    for r in _rows():
        words = r["_n"]
        # «Базар-Коргон №1 мектеп»: «базар» деп жазганда шаардын аты эсептелбейт (базардын өзү чыксын)
        if r["_a"] and not r["_a"] <= set(toks):
            rest = [w for w in words if w not in r["_a"]]
            words = rest or words
        ok, score = True, 0
        for t in toks:
            if any(w == t for w in words):
                score += 3
            elif any(w.startswith(t) for w in words):
                score += 2
            elif len(t) >= 3 and any(t in w for w in words):
                score += 1
            else:
                ok = False
                break
        if not ok:
            continue
        if words and words[0].startswith(toks[0]):
            score += 2
        if r["kind"] != "street":
            score += 0.5
        dist = core.haversine_km(near[0], near[1], r["lat"], r["lon"]) if near else 0
        scored.append((-score, dist, r))
    scored.sort(key=lambda x: (x[0], x[1]))
    return [view(r) for _, _, r in scored[:limit]]


def admin_list(q="", limit=300, only=None):
    rows = core.query("SELECT * FROM addresses ORDER BY id DESC", (), "all")
    if only == "pending":
        rows = [r for r in rows if r.get("status") == "pending"]
    elif only == "approx":
        rows = [r for r in rows if r.get("approx") and not r.get("hidden")]
    if q:
        n = norm(q)
        rows = [r for r in rows if n in norm(r["name"] + " " + (r.get("aliases") or "") + " " + (r.get("area") or ""))]
    rows.sort(key=lambda r: (r.get("status") != "pending", r.get("source") != "admin"))
    return [view(r) for r in rows[:limit]]


# ==================== Жүргүнчүлөр / айдоочулар сунуштаган даректер ====================
VOTES_OK = 3          # ушунча «добуш» чогулса — тизмеге өзү кошулат (айдоочу = 2, жүргүнчү = 1)


def suggest(name, lat, lon, by, weight=1, kind="poi"):
    """Жаңы жер сунушу. Ошол эле ат жакын жерде бар болсо — добуш кошулат."""
    name = (name or "").strip()[:80]
    if len(name) < 2 or lat is None or (core.AREA_ON and not core.in_area(lat, lon)):
        return None
    if kind not in KINDS:
        kind = "poi"
    n = norm(name)
    for r in core.query("SELECT * FROM addresses", (), "all"):
        if norm(r["name"]) != n or core.haversine_km(lat, lon, r["lat"], r["lon"]) > 0.3:
            continue
        if r.get("status") == "pending":
            if by and by == r.get("suggested_by"):
                return r["id"]                       # бир эле адам эки жолу добуш бербейт
            v = (r.get("votes") or 0) + weight
            core.query("UPDATE addresses SET votes=?, status=? WHERE id=?",
                       (v, "ok" if v >= VOTES_OK else "pending", r["id"]))
            _reset()
        return r["id"]
    # аты бар, жери болжолдуу жазуу болсо — ошону тактайбыз
    for r in core.query("SELECT * FROM addresses WHERE approx=1", (), "all"):
        if norm(r["name"]) == n or n in norm(r.get("aliases") or "").split():
            core.query("UPDATE addresses SET lat=?, lon=?, approx=0 WHERE id=?", (lat, lon, r["id"]))
            _reset()
            return r["id"]
    aid = core.query("INSERT INTO addresses (name, kind, lat, lon, aliases, area, source, hidden, osm_key, created_at, "
                     "approx, status, votes, suggested_by) VALUES (?, ?, ?, ?, '', '', 'user', 0, NULL, ?, 0, ?, ?, ?)",
                     (name, kind, lat, lon, core.now(), "ok" if weight >= VOTES_OK else "pending", weight, by), "id")
    _reset()
    return aid


def approve(aid):
    core.query("UPDATE addresses SET status='ok' WHERE id=?", (aid,))
    _reset()


# ==================== Интернеттен чогултулган аттар (addr_seed.py) ====================

def seed_web():
    import addr_seed as S
    have = {r["osm_key"] for r in core.query("SELECT osm_key FROM addresses WHERE osm_key LIKE ?", ("web/%",), "all")}
    names = {norm(r["name"]) for r in core.query("SELECT name FROM addresses", (), "all")}
    added = 0
    rows = [(n, "street", al) for n, al in S.STREETS] + list(S.PLACES)
    for name, kind, al in rows:
        key = "web/" + norm(name)
        if key in have or norm(name) in names:
            continue
        core.query("INSERT INTO addresses (name, kind, lat, lon, aliases, area, source, hidden, osm_key, created_at, "
                   "approx, status, votes) VALUES (?, ?, ?, ?, ?, ?, 'web', 0, ?, ?, 1, 'ok', 0)",
                   (name, kind, S.CENTER[0], S.CENTER[1], al, S.TOWN, key, core.now()))
        added += 1
    _reset()
    return added


# ==================== OpenStreetMap'тен жүктөө ====================

def _kind_of(t):
    a, s = t.get("amenity", ""), t.get("shop", "")
    if t.get("highway"):
        return "street"
    if t.get("place"):
        return "village"
    if a == "marketplace" or s == "mall":
        return "market"
    if a in ("school", "college", "university", "kindergarten"):
        return "school"
    if a in ("hospital", "clinic", "doctors", "pharmacy", "dentist") or t.get("healthcare"):
        return "health"
    if a == "place_of_worship":
        return "mosque"
    if a in ("cafe", "restaurant", "fast_food"):
        return "food"
    if a in ("bank", "atm"):
        return "bank"
    if a == "fuel":
        return "fuel"
    if a in ("townhall", "police", "post_office", "courthouse") or t.get("office") == "government":
        return "gov"
    if a == "bus_station" or t.get("highway") == "bus_stop":
        return "bus"
    if s:
        return "shop"
    return "poi"


def _name(t):
    return (t.get("name:ky") or t.get("name") or t.get("name:ru") or "").strip()


def parse_overpass(data):
    """Overpass JSON → [{name, kind, lat, lon, area, key}]. Бир аттуу көчөнүн бөлүктөрү
    жакын болсо бириктирилет; ар башка айылдардагы бир аттуу көчөлөр өзүнчө калат."""
    els = data.get("elements") or []
    villages = []
    for e in els:
        t = e.get("tags") or {}
        if t.get("place") and _name(t):
            lat, lon = e.get("lat") or (e.get("center") or {}).get("lat"), e.get("lon") or (e.get("center") or {}).get("lon")
            if lat is not None:
                villages.append((_name(t), lat, lon))

    def area_of(lat, lon):
        best, bd = "", 99
        for n, a, b in villages:
            d = core.haversine_km(lat, lon, a, b)
            if d < bd:
                best, bd = n, d
        return best if bd < 4 else ""

    groups, out = {}, []
    for e in els:
        t = e.get("tags") or {}
        name = _name(t)
        if not name:
            continue
        c = e.get("center") or {}
        lat, lon = e.get("lat", c.get("lat")), e.get("lon", c.get("lon"))
        if lat is None or lon is None:
            continue
        if core.AREA_ON and not core.in_area(lat, lon):
            continue
        kind = _kind_of(t)
        if kind == "street":
            key = norm(name)
            g = None
            for gg in groups.setdefault(key, []):
                if core.haversine_km(lat, lon, gg["lat"], gg["lon"]) < 1.5:
                    g = gg
                    break
            if g:
                g["n"] += 1
                g["lat"] += (lat - g["lat"]) / g["n"]
                g["lon"] += (lon - g["lon"]) / g["n"]
            else:
                groups[key].append({"name": pretty(name), "kind": "street", "lat": lat, "lon": lon, "n": 1})
        else:
            out.append({"name": name, "kind": kind, "lat": lat, "lon": lon,
                        "key": "%s/%s" % (e.get("type", "n")[0], e.get("id"))})
    for key, gs in groups.items():
        for g in gs:
            out.append({"name": g["name"], "kind": "street", "lat": g["lat"], "lon": g["lon"],
                        "key": "s/%s/%.3f/%.3f" % (key, g["lat"], g["lon"])})
    for x in out:
        x["area"] = area_of(x["lat"], x["lon"]) if x["kind"] != "village" else ""
    return out


def _overpass_query():
    b = core.AREA_BBOX            # [s, w, n, e]
    bb = "%f,%f,%f,%f" % (b[0], b[1], b[2], b[3])
    return ("[out:json][timeout:90];("
            'way["highway"]["name"](%(bb)s);'
            'node["place"~"city|town|village|hamlet|suburb|neighbourhood|quarter|isolated_dwelling"]["name"](%(bb)s);'
            'nwr["amenity"]["name"](%(bb)s);nwr["shop"]["name"](%(bb)s);nwr["healthcare"]["name"](%(bb)s);'
            'nwr["office"]["name"](%(bb)s);nwr["tourism"]["name"](%(bb)s);nwr["leisure"]["name"](%(bb)s);'
            'nwr["building"]["name"](%(bb)s);node["highway"="bus_stop"]["name"](%(bb)s);'
            ");out center tags;") % {"bb": bb}


def merge(items):
    """Жаңы OSM жазууларын кошот. Админ оңдогон / жашырган жазууларга тийбейт."""
    have = {r["osm_key"] for r in core.query("SELECT osm_key FROM addresses WHERE osm_key IS NOT NULL", (), "all")}
    added = 0
    for x in items:
        if x["key"] in have:
            continue
        core.query("INSERT INTO addresses (name, kind, lat, lon, aliases, area, source, hidden, osm_key, created_at, "
                   "approx, status, votes) VALUES (?, ?, ?, ?, '', ?, 'osm', 0, ?, ?, 0, 'ok', 0)",
                   (x["name"][:80], x["kind"], x["lat"], x["lon"], x["area"][:60], x["key"], core.now()))
        have.add(x["key"])
        added += 1
    _reset()
    return added


def import_osm():
    if import_state["running"]:
        return
    import_state.update(running=True, error=None)
    try:
        body = urllib.parse.urlencode({"data": _overpass_query()}).encode()
        data, err = None, None
        for url in OVERPASS:
            try:
                req = urllib.request.Request(url, data=body, headers={"User-Agent": "TaksiTAP/1.0 (taxi service)"})
                with urllib.request.urlopen(req, timeout=120) as r:
                    data = json.loads(r.read().decode())
                break
            except Exception as e:
                err = e
        if data is None:
            raise RuntimeError(err)
        n = merge(parse_overpass(data))
        import_state.update(added=n, last=core.now())
        print("  Даректер: OSM'ден %d жаңы жазуу кошулду" % n, flush=True)
    except Exception as e:
        import_state["error"] = str(e)[:200]
        print("  Даректер: OSM'ден жүктөлбөдү (%s)" % e, flush=True)
    finally:
        import_state["running"] = False


def ensure_seeded():
    """Тизме бош болсо — бир жолу OSM'ден жүктөйт (фондо), анан интернеттен чогултулган аттар."""
    if not core.AREA_ON:
        dgis_selftest()
        return
    if not count()["total"]:
        time.sleep(5)                       # аймактын чеги жүктөлсүн
        import_osm()
    n = seed_web()
    dgis_selftest()
    if n:
        print("  Даректер: интернеттен чогултулган %d ат кошулду (жери болжолдуу)" % n, flush=True)


# ==================== 2ГИС (кошумча издөө, DGIS_KEY болсо) ====================
# Өз тизмебизде аз натыйжа болсо гана 2ГИСтен сурайт. Натыйжалар базага сакталбайт
# (2ГИСтин маалыматы лицензиялуу) — эстутумда бир саатка гана кэштелет.
import os as _os

DGIS_KEY = (_os.environ.get("DGIS_KEY") or "").strip()
DGIS_URL = "https://catalog.api.2gis.com/3.0/items"
_dgis_cache = {}
dgis_state = {"ok": None, "calls": 0, "errors": 0, "last_error": None}
# Акысыз ачкыч: айына 1000 суроо. Күнүнө ушундан ашпайбыз; лимит бүтсө — ай аягына чейин сурабайбыз
# (дарек OSM/өз тизмебизден чыгат).
DGIS_DAY_MAX = int(_os.environ.get("DGIS_DAY_MAX") or 30)


def _dgis_allow():
    if not DGIS_KEY:
        return False
    lt = time.gmtime(core.now() + core.TZ)
    month, day = time.strftime("%Y-%m", lt), time.strftime("%Y-%m-%d", lt)
    st = core.get_setting("dgis_budget") or {}
    if st.get("blocked") == month:
        return False
    if st.get("day") != day:
        st = {"day": day, "n": 0, "blocked": st.get("blocked")}
    if st["n"] >= DGIS_DAY_MAX:
        return False
    st["n"] += 1
    core.set_setting("dgis_budget", st)
    return True


def _dgis_fail(e):
    """403/429 = лимит бүттү → ушул ай бою токтотобуз."""
    s = str(e)
    if "403" in s or "429" in s or "limit" in s.lower():
        st = core.get_setting("dgis_budget") or {}
        st["blocked"] = time.strftime("%Y-%m", time.gmtime(core.now() + core.TZ))
        core.set_setting("dgis_budget", st)


def _dgis_parse(data):
    out = []
    for it in ((data or {}).get("result") or {}).get("items") or []:
        p = it.get("point") or {}
        lat, lon = p.get("lat"), p.get("lon")
        if lat is None or lon is None:
            continue
        if core.AREA_ON and not core.in_area(lat, lon):
            continue
        name = it.get("name") or it.get("address_name") or it.get("full_name") or ""
        sub = it.get("address_name") if it.get("address_name") and it.get("address_name") != name else ""
        if not sub:
            full = it.get("full_name") or ""
            sub = ", ".join(x.strip() for x in full.split(",")[:-1][-2:]) if "," in full else ""
        out.append({"id": None, "name": name, "kind": "poi", "icon": "📍", "area": (sub + " · 2ГИС").strip(" ·"),
                    "lat": lat, "lon": lon, "aliases": "", "source": "2gis", "approx": False})
    return out


def dgis_search(q, near=None, limit=6):
    if not DGIS_KEY or len((q or "").strip()) < 3:
        return []
    key = (norm(q), round(near[0], 2) if near else 0, round(near[1], 2) if near else 0)
    hit = _dgis_cache.get(key)
    if hit and hit[0] > time.time():
        return hit[1]
    if not _dgis_allow():
        return []
    c = near or ((core.AREA_BBOX[0] + core.AREA_BBOX[2]) / 2, (core.AREA_BBOX[1] + core.AREA_BBOX[3]) / 2)
    params = {"q": q, "key": DGIS_KEY, "location": "%f,%f" % (c[1], c[0]), "radius": 40000,
              "fields": "items.point,items.address_name,items.full_name", "page_size": 10, "locale": "ru_KG"}
    try:
        dgis_state["calls"] += 1
        req = urllib.request.Request(DGIS_URL + "?" + urllib.parse.urlencode(params),
                                     headers={"User-Agent": "TaksiTAP/1.0"})
        with urllib.request.urlopen(req, timeout=6) as r:
            data = json.loads(r.read().decode())
        code = ((data.get("meta") or {}).get("code"))
        if code not in (200, 404, None):
            raise RuntimeError("meta %s: %s" % (code, (data.get("meta") or {}).get("error")))
        res = _dgis_parse(data)[:limit]
        dgis_state["ok"] = True
    except Exception as e:
        dgis_state.update(ok=False, last_error=str(e)[:200])
        dgis_state["errors"] += 1
        _dgis_fail(e)
        res = []
    if len(_dgis_cache) > 2000:
        _dgis_cache.clear()
    _dgis_cache[key] = (time.time() + 3600, res)
    return res


_osm_cache = {}


def osm_search(q, near=None, limit=6):
    """Камдык: OpenStreetMap (Nominatim) — 2ГИС лимити бүтсө же табылбаса. Аймактын ичинде гана."""
    q = (q or "").strip()
    if len(q) < 3:
        return []
    key = norm(q)
    hit = _osm_cache.get(key)
    if hit and hit[0] > time.time():
        return hit[1]
    b = core.AREA_BBOX            # [lat1, lon1, lat2, lon2]
    params = {"q": q, "format": "jsonv2", "limit": 10, "accept-language": "ky,ru", "bounded": 1,
              "viewbox": "%f,%f,%f,%f" % (b[1], b[2], b[3], b[0]), "countrycodes": "kg"}
    res = []
    try:
        req = urllib.request.Request("https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(params),
                                     headers={"User-Agent": "TaksiTAP/1.0 (taxi-tap.kg)"})
        with urllib.request.urlopen(req, timeout=6) as r:
            data = json.loads(r.read().decode())
        seen = set()
        for it in data or []:
            lat, lon = float(it["lat"]), float(it["lon"])
            if core.AREA_ON and not core.in_area(lat, lon):
                continue
            parts = [x.strip() for x in (it.get("display_name") or "").split(",")]
            name = it.get("name") or (parts[0] if parts else q)
            area = next((x for x in parts[1:] if x and not x.isdigit()), "")
            k = norm(name) + "|" + norm(area)
            if k in seen:
                continue
            seen.add(k)
            st = it.get("category") == "highway" or it.get("type") in ("residential", "tertiary", "secondary", "primary", "unclassified", "living_street")
            res.append({"id": None, "name": pretty(name) if st else name, "kind": "street" if st else "poi", "icon": "📍",
                        "area": area, "lat": lat, "lon": lon, "aliases": "", "source": "osm", "approx": False})
    except Exception as e:
        print("osm search:", e, flush=True)
    if near:
        res.sort(key=lambda x: core.haversine_km(near[0], near[1], x["lat"], x["lon"]))
    res = res[:limit]
    if len(_osm_cache) > 2000:
        _osm_cache.clear()
    _osm_cache[key] = (time.time() + 6 * 3600, res)
    return res


def search_all(q, near=None, limit=8):
    """Адегенде өз тизмебиз; аз болсо — 2ГИС; ал да аз болсо — OpenStreetMap (кайталанганы чыкпайт)."""
    own = search(q, near, limit)
    if len(own) >= 3:
        return own
    names = {norm(x["name"]) for x in own}
    extra = [x for x in (dgis_search(q, near) if DGIS_KEY else []) if norm(x["name"]) not in names]
    out = own + extra
    if len(out) < 3:
        names |= {norm(x["name"]) for x in extra}
        out += [x for x in osm_search(q, near) if norm(x["name"]) not in names]
    return out[:limit + 3]


def dgis_selftest():
    if DGIS_KEY and _os.environ.get("DGIS_SELFTEST") == "1":        # ар деплойдо лимит жебесин
        r = dgis_search("Базар-Коргон", (41.0417, 72.7472))
        try:
            print("  2ГИС дарек (тест): %s" % ((_dgis_reverse(41.0399, 72.7466) or [None])[0] or "табылган жок — " + str(dgis_state["last_error"])), flush=True)
        except Exception as e:
            print("  2ГИС дарек: ката", e, flush=True)
        print("  2ГИС: %s (%d натыйжа)%s" % ("ачкыч иштейт" if dgis_state["ok"] else "иштебей жатат", len(r),
                                            "" if dgis_state["ok"] else " — " + str(dgis_state["last_error"])), flush=True)


# ==================== Тескери геокод: чекит → так дарек ====================
# 1) 2ГИС: көчө + үй номери; 2) өз тизмебизден жакын белгилүү жер («… жанында»).
_rev_cache = {}
LANDMARK_M = 150


def nearest_landmark(lat, lon, max_m=LANDMARK_M):
    best, bd = None, max_m / 1000.0
    for r in _rows():
        if r["kind"] == "street" or r.get("approx") or r["lat"] is None:
            continue
        d = core.haversine_km(lat, lon, r["lat"], r["lon"])
        if d < bd:
            best, bd = r, d
    return best["name"] if best else None


def _dgis_geo(params):
    dgis_state["calls"] += 1
    req = urllib.request.Request(DGIS_URL + "/geocode?" + urllib.parse.urlencode(params),
                                 headers={"User-Agent": "TaksiTAP/1.0"})
    with urllib.request.urlopen(req, timeout=5) as r:
        return ((json.loads(r.read().decode()) or {}).get("result") or {}).get("items") or []


def _bld_name(it):
    a = it.get("address_name") or ""
    if a:
        parts = [x.strip() for x in a.split(",")]
        return pretty(parts[0]) + " " + parts[1] if len(parts) >= 2 else pretty(a)
    return it.get("name") or None


def _dgis_reverse(lat, lon):
    """Үйдүн номери менен дарек: адегенде имарат (үй), табылбаса — жакын 40 м ичиндеги эң жакын имарат, акыры көчө.
    Натыйжа: (дарек, "building"|"street") же None."""
    if not _dgis_allow():
        return None
    base = {"lat": "%.6f" % lat, "lon": "%.6f" % lon, "key": DGIS_KEY,
            "fields": "items.point,items.address_name,items.full_name,items.address", "locale": "ru_KG"}
    try:
        # Бир гана суроо (лимитти үнөмдөйбүз): 40 м ичиндеги үйлөр жана көчөлөр → эң жакын номерлүү үй, болбосо көчө
        items = _dgis_geo(dict(base, type="building,street", radius=40, page_size=10))
        best, street = None, None
        for it in items:
            if it.get("type") == "street" and it.get("name") and not street:
                street = pretty(it["name"])
            p = it.get("point") or {}
            if it.get("type") == "building" and it.get("address_name") and p.get("lat") is not None:
                d = core.haversine_km(lat, lon, p["lat"], p["lon"])
                if best is None or d < best[0]:
                    best = (d, _bld_name(it))
        if best:
            return (best[1], "building")
        return (street, "street") if street else None
    except Exception as e:
        dgis_state["errors"] += 1
        dgis_state["last_error"] = "rev: " + str(e)[:150]
        _dgis_fail(e)
        return None


_HNUM = re.compile(r"\s\d+[\w/-]*$")


def has_num(a):
    return bool(a and _HNUM.search(a.strip()))


def osm_house(lat, lon, radius=45):
    """Камдык: OpenStreetMap'тен эң жакын номерлүү үй (Overpass). 2ГИС лимити бүтсө же номер бербесе."""
    q = ('[out:json][timeout:6];(way(around:%d,%.6f,%.6f)["addr:housenumber"];'
         'node(around:%d,%.6f,%.6f)["addr:housenumber"];);out tags center 15;' % (radius, lat, lon, radius, lat, lon))
    for url in ("https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter"):
        try:
            req = urllib.request.Request(url, data=urllib.parse.urlencode({"data": q}).encode(),
                                         headers={"User-Agent": "TaksiTAP/1.0 (taxi-tap.kg)"})
            with urllib.request.urlopen(req, timeout=7) as r:
                els = json.loads(r.read().decode()).get("elements") or []
            best = None
            for e in els:
                t = e.get("tags") or {}
                c = e.get("center") or e
                if c.get("lat") is None or not t.get("addr:housenumber"):
                    continue
                d = core.haversine_km(lat, lon, c["lat"], c["lon"])
                if best is None or d < best[0]:
                    best = (d, t)
            if not best:
                return None
            t = best[1]
            street = t.get("addr:street") or t.get("addr:place") or ""
            return (pretty(street) + " " if street else "") + t["addr:housenumber"]
        except Exception as e:
            dgis_state["osm_err"] = str(e)[:120]
            continue
    return None


def reverse(lat, lon):
    """{"addr": "Эн-Сай көчөсү 12", "near": "Стадион"} — бири же экөө тең None болушу мүмкүн.
    Үйдүн номери: 2ГИС → (номер жок болсо) OpenStreetMap'тин жакынкы номерлүү үйү → көчө гана."""
    key = (round(lat / 0.00012), round(lon / 0.00012))        # ~12 м тор (үйдүн номери так болсун)
    hit = _rev_cache.get(key)
    if hit and hit[0] > time.time():
        return hit[1]
    dg = _dgis_reverse(lat, lon)
    addr, bld = (dg[0], dg[1] == "building") if dg else (None, False)
    if not bld:
        h = osm_house(lat, lon)
        if h and h != addr and (not addr or not h[0].isdigit()):
            addr = h if not h[0].isdigit() else ((addr or "") + " " + h).strip()
        elif h and addr:
            addr = addr + " " + h
    res = {"addr": addr, "near": nearest_landmark(lat, lon)}
    if len(_rev_cache) > 20000:
        _rev_cache.clear()
    # номери бар — 1 күн; номерсиз — 10 мүнөт гана (лимит кайра ачылса, номер чыксын)
    _rev_cache[key] = (time.time() + (86400 if bld or (addr and addr != (dg or [None])[0]) else 600), res)
    return res


def dgis_status():
    """Админ үчүн: 2ГИС азыр иштейби, бүгүн канча суроо, ай бою токтотулганбы."""
    st = core.get_setting("dgis_budget") or {}
    month = time.strftime("%Y-%m", time.gmtime(core.now() + core.TZ))
    return {"on": bool(DGIS_KEY), "used": st.get("n", 0), "max": DGIS_DAY_MAX, "blocked": st.get("blocked") == month,
            "last_error": dgis_state.get("last_error"), "ok": dgis_state.get("ok")}


def dgis_unblock():
    st = core.get_setting("dgis_budget") or {}
    st.pop("blocked", None)
    core.set_setting("dgis_budget", st)


# ==================== Көп барылчу жерлер (Б точка үчүн даяр тизме) ====================
_POP_KINDS = ("market", "bus", "health", "gov", "mosque", "shop")
_pop_cache = {"t": 0, "v": []}


def popular(limit=6):
    if _pop_cache["t"] > time.time():
        return _pop_cache["v"]
    out, seen = [], set()
    # 1) Жүргүнчүлөр акыркы 30 күндө көп барган жерлер
    try:
        rows = core.query("SELECT d_addr, AVG(d_lat) AS lat, AVG(d_lon) AS lon, COUNT(*) AS n FROM rides "
                          "WHERE status='completed' AND d_addr IS NOT NULL AND d_lat IS NOT NULL AND created_at>? "
                          "GROUP BY d_addr ORDER BY n DESC LIMIT 10", (core.now() - 30 * 86400,), "all")
    except Exception:
        rows = []
    for r in rows:
        if (r["n"] or 0) < 3:
            continue
        k = norm(r["d_addr"])
        if k in seen:
            continue
        seen.add(k)
        out.append({"icon": "🔥", "name": r["d_addr"], "area": "Көп барышат", "lat": r["lat"], "lon": r["lon"]})
    # 2) Белгилүү жайлар (жери так болгондору гана)
    pois = [r for r in _rows() if r["kind"] in _POP_KINDS and not r.get("approx") and r["lat"] is not None]
    pois.sort(key=lambda r: (_POP_KINDS.index(r["kind"]), -(r.get("votes") or 0), r["name"]))
    used_kind = {}
    for r in pois:
        if len(out) >= limit:
            break
        if used_kind.get(r["kind"], 0) >= 2 or norm(r["name"]) in seen:
            continue
        used_kind[r["kind"]] = used_kind.get(r["kind"], 0) + 1
        seen.add(norm(r["name"]))
        out.append({"icon": KINDS[r["kind"]][0], "name": r["name"], "area": r.get("area") or KINDS[r["kind"]][1],
                    "lat": r["lat"], "lon": r["lon"]})
    _pop_cache.update(t=time.time() + 600, v=out[:limit])
    return out[:limit]
