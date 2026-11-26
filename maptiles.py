"""2ГИС растрдык картасы — жүргүнчүнүн барагы үчүн гана.

Плиткалар биздин сервер аркылуу өтөт (/tiles/2gis/z/x/y.png): ачкыч браузерге чыкпайт жана
ар бир плитка саналат. Айлык лимит (DGIS_MAP_LIMIT) бүтсө, карта өзү бекер OSM'ге өтөт.
"""
import os
import threading
import time
import urllib.request

import core

KEY = (os.environ.get("DGIS_MAP_KEY") or "").strip()
LIMIT = int(os.environ.get("DGIS_MAP_LIMIT") or 25000)      # демо-ачкыч 30 000; сатып алгандан кийин көбөйтүңүз
WARN = (0.8, 1.0)
URL = "https://tile%d.maps.2gis.com/v2/tiles/online_hd/%d/%d/%d.png?key=%s"
OSM = "https://tile.openstreetmap.org/%d/%d/%d.png"
_lock = threading.Lock()
_st = {"pending": 0, "flushed": 0.0, "errors": 0, "last_error": None, "blocked": None}


def _month():
    return time.strftime("%Y-%m", time.gmtime(core.now() + core.TZ))


def _saved():
    st = core.get_setting("dgis_tiles") or {}
    if st.get("m") != _month():
        st = {"m": _month(), "n": 0, "warned": 0}
    return st


def used():
    return int(_saved().get("n", 0)) + _st["pending"]


def provider():
    if not KEY or _st["blocked"] == _month():
        return "osm"
    return "2gis" if used() < LIMIT else "osm"


def flush(force=False):
    """Эсептегичти базага жазат (20 секундда бир). Лимиттин 80%/100% жеткенде админге кабар (бир жолудан)."""
    with _lock:
        if not _st["pending"] or (not force and core.now() - _st["flushed"] < 20):
            return None
        n, _st["pending"] = _st["pending"], 0
        _st["flushed"] = core.now()
    st = _saved()
    st["n"] = int(st.get("n", 0)) + n
    alert = None
    for i, w in enumerate(WARN, 1):
        if st["n"] >= LIMIT * w and st.get("warned", 0) < i:
            st["warned"] = i
            alert = {"used": st["n"], "limit": LIMIT, "pct": int(w * 100)}
    core.set_setting("dgis_tiles", st)
    return alert


def fetch(z, x, y):
    """(body, content_type, redirect_url). Лимит бүтсө же ката болсо — OSM'ге жөнөтөбүз."""
    if not (0 <= z <= 19 and 0 <= x < 2 ** z and 0 <= y < 2 ** z):
        return None, None, None
    if provider() != "2gis":
        return None, None, OSM % (z, x, y)
    try:
        req = urllib.request.Request(URL % ((x + y) % 5, z, x, y, KEY), headers={"User-Agent": "TaxiTAP/1.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            body, ct = r.read(), r.headers.get("Content-Type") or "image/png"
        with _lock:
            _st["pending"] += 1
        return body, ct, None
    except Exception as e:                         # noqa: BLE001
        _st["errors"] += 1
        _st["last_error"] = str(e)[:200]
        if "403" in str(e) or "429" in str(e):     # ачкыч/лимит бүттү → ушул ай бою OSM
            _st["blocked"] = _month()
        return None, None, OSM % (z, x, y)


def status():
    return {"on": bool(KEY), "provider": provider(), "used": used(), "limit": LIMIT,
            "errors": _st["errors"], "last_error": _st["last_error"], "blocked": _st["blocked"] == _month()}
