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
            _cache["rows"] = core.query("SELECT * FROM addresses WHERE hidden=0", (), "all")
            for r in _cache["rows"]:
                r["_n"] = norm(r["name"] + " " + (r.get("aliases") or "")).split()
        return _cache["rows"]


def _reset():
    with _lock:
        _cache["rows"] = None


def count():
    r = core.query("SELECT COUNT(*) AS n, SUM(CASE WHEN source='admin' THEN 1 ELSE 0 END) AS a, "
                   "SUM(hidden) AS h FROM addresses", (), "one")
    return {"total": r["n"] or 0, "admin": r["a"] or 0, "hidden": r["h"] or 0}


def save(name, kind, lat, lon, aliases="", area="", aid=None, source="admin"):
    name = (name or "").strip()[:80]
    if not name or kind not in KINDS or lat is None or lon is None:
        return None
    if core.AREA_ON and not core.in_area(lat, lon):
        return None
    aliases = ", ".join(a.strip() for a in (aliases or "").split(",") if a.strip())[:200]
    area = (area or "").strip()[:60]
    if aid:
        core.query("UPDATE addresses SET name=?, kind=?, lat=?, lon=?, aliases=?, area=?, source='admin' WHERE id=?",
                   (name, kind, lat, lon, aliases, area, aid))
    else:
        aid = core.query("INSERT INTO addresses (name, kind, lat, lon, aliases, area, source, hidden, osm_key, created_at) "
                         "VALUES (?, ?, ?, ?, ?, ?, ?, 0, NULL, ?)",
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
            "hidden": bool(r.get("hidden"))}


# ==================== Издөө ====================

def search(q, near=None, limit=8):
    toks = norm(q).split()
    if not toks:
        return []
    scored = []
    for r in _rows():
        words = r["_n"]
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


def admin_list(q="", limit=300):
    if q:
        rows = core.query("SELECT * FROM addresses ORDER BY id DESC", (), "all")
        n = norm(q)
        rows = [r for r in rows if n in norm(r["name"] + " " + (r.get("aliases") or "") + " " + (r.get("area") or ""))]
    else:
        rows = core.query("SELECT * FROM addresses ORDER BY source='admin' DESC, id DESC LIMIT ?", (limit,), "all")
    return [view(r) for r in rows[:limit]]


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
        core.query("INSERT INTO addresses (name, kind, lat, lon, aliases, area, source, hidden, osm_key, created_at) "
                   "VALUES (?, ?, ?, ?, '', ?, 'osm', 0, ?, ?)",
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
    """Тизме бош болсо — бир жолу OSM'ден жүктөйт (фондо)."""
    if core.AREA_ON and not count()["total"]:
        time.sleep(5)                       # аймактын чеги жүктөлсүн
        import_osm()
