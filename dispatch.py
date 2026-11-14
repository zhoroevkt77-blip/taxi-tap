# -*- coding: utf-8 -*-
"""
Такси ТАП! — буйрук бөлүштүрүү (dispatch).

Заказ бардык айдоочуга эмес, жакындан алыска карай бир-бирден сунушталат:

  1. Радиус: 0–60 сек → 3 км, 60–120 сек → 5 км, андан кийин → 8 км
  2. Эң жакын бош айдоочуга OFFER_SEC (15) секунд сунуш
  3. Жооп жок же «Жок» → кийинкисине
  4. SEARCH_MAX_SEC (180) секунддан кийин издөө токтойт

tick() ар 2 секундда чакырылат; жөнөтүлө турган Out тизмесин кайтарат.
"""

import json

import core
import parks
from flow import money, note


def radius_for(age):
    for limit, km in core.RADIUS_STEPS:
        if age < limit:
            return km
    return core.RADIUS_STEPS[-1][1]


def candidates(ride, radius_km):
    """
    Бош айдоочулар + сапары бүтүүгө жакын айдоочулар (кийинки заказ).
    Класс (Комфорт, Минивэн, Жеткирүү) жана «Үйгө карай» режими эске алынат.
    """
    tried = set(json.loads(ride["tried"] or "[]"))
    out = []

    def ok(d):
        return not (d["uid"] in tried or (d["uid"] == ride["passenger"] and not core.TEST_SELF_ORDER)) \
            and core.can_take(d, ride.get("cls")) and core.toward_home(d, ride)

    for d in core.online_drivers():
        if core.AREA_ON and not core.in_area(d["lat"], d["lon"]):
            continue                    # иштөө аймагынан сырткары — заказ берилбейт
        if not ok(d):
            continue
        dist = core.haversine_km(ride["p_lat"], ride["p_lon"], d["lat"], d["lon"])
        if dist <= radius_km:
            out.append((dist, -(d["rating"] or 5.0), d))
    for d, cur in core.chain_drivers():
        end_km = core.haversine_km(cur["d_lat"], cur["d_lon"], ride["p_lat"], ride["p_lon"])
        if end_km > core.CHAIN_KM or not ok(d):
            continue
        # айдоочу адегенде азыркы жүргүнчүнү жеткирет: жол узунураак + бош айдоочу артык
        dist = core.haversine_km(d["lat"], d["lon"], cur["d_lat"], cur["d_lon"]) + end_km + 0.5
        if dist <= radius_km:
            out.append((dist, -(d["rating"] or 5.0), d))
    # Активдүүлүгү төмөн айдоочу «алысыраак» эсептелет: 100 → 0 км, 0 → +0.8 км
    out.sort(key=lambda x: (round(x[0] + (100 - (x[2].get("activity") if x[2].get("activity") is not None else 100)) * 0.008, 1), x[1]))
    return [(dist, d) for dist, _, d in out]


def _offered_elsewhere(driver_uid, ride_id):
    """Бир айдоочуга бир эле учурда бир гана сунуш."""
    r = core.query("SELECT id FROM rides WHERE status='searching' AND offered_to=? AND id<>?",
                   (driver_uid, ride_id), "one")
    return r is not None


def tick():
    """
    Ар 2 секундда. Telegram билдирүүлөрүн (Out) кайтарат — заказдын өзү
    айдоочунун сайтында /api/d/state аркылуу көрүнөт.
    """
    out = [note(r["passenger"], "p_scheduled_go") for r in core.activate_scheduled()]
    out += [note(uid, "d_auto_off", "/driver", area=core.area_gen()) for uid in core.auto_offline_out()]
    pw = parks.weekly_reminder()
    if pw:
        rows = "\n".join("• %s — %d сом" % (n, d) for n, d in pw)
        out += [note(a, "a_park_week", "/admin", rows=rows) for a in core.admins()]
    for uid, kind, days, date in core.lic_daily():
        out.append(note(uid, "d_lic_" + kind, "/driver", days=days, date=date))
    t = core.now()
    for r in core.searching_rides():
        rid = r["id"]
        if r["offered_to"]:
            if t - (r["offered_at"] or 0) < core.OFFER_SEC:
                continue
            core.mark_tried(rid, r["offered_to"])      # жооп бербеди → кийинкиси
            r = core.get_ride(rid)
            if r["status"] != "searching":
                continue

        age = t - (r["created_at"] or t)
        if age > core.SEARCH_MAX_SEC:
            if core.cancel(rid, "system", allowed=("searching",)):
                out.append(note(r["passenger"], "p_no_driver"))
            continue

        for dist, d in candidates(r, radius_for(age)):
            if _offered_elsewhere(d["uid"], rid):
                continue
            core.offer(rid, d["uid"])
            out.append(note(d["uid"], "d_offer", "/driver", price=money(r["price"]),
                            km=round(dist, 1), sec=int(core.OFFER_SEC)))
            break
    return out
