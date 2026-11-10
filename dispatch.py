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
from flow import lang_of, menu, money, msg
from strings import L


def radius_for(age):
    for limit, km in core.RADIUS_STEPS:
        if age < limit:
            return km
    return core.RADIUS_STEPS[-1][1]


def candidates(ride, radius_km):
    tried = set(json.loads(ride["tried"] or "[]"))
    out = []
    for d in core.online_drivers():
        if d["uid"] in tried or d["uid"] == ride["passenger"]:
            continue
        dist = core.haversine_km(ride["p_lat"], ride["p_lon"], d["lat"], d["lon"])
        if dist <= radius_km:
            out.append((dist, -(d["rating"] or 5.0), d))
    out.sort(key=lambda x: (round(x[0], 1), x[1]))
    return [(dist, d) for dist, _, d in out]


def _offered_elsewhere(driver_uid, ride_id):
    """Бир айдоочуга бир эле учурда бир гана сунуш."""
    r = core.query("SELECT id FROM rides WHERE status='searching' AND offered_to=? AND id<>?",
                   (driver_uid, ride_id), "one")
    return r is not None


def tick():
    out = []
    t = core.now()
    for r in core.searching_rides():
        rid = r["id"]
        # мурунку сунуштун мөөнөтү өттүбү
        if r["offered_to"]:
            if t - (r["offered_at"] or 0) < core.OFFER_SEC:
                continue
            out.append(msg(r["offered_to"], L("offer_expired", lang_of(r["offered_to"]))))
            core.mark_tried(rid, r["offered_to"])
            r = core.get_ride(rid)
            if r["status"] != "searching":
                continue

        age = t - (r["created_at"] or t)
        if age > core.SEARCH_MAX_SEC:
            if core.cancel(rid, "system", allowed=("searching",)):
                out += menu(r["passenger"], L("no_driver", lang_of(r["passenger"])))
            continue

        for dist, d in candidates(r, radius_for(age)):
            if _offered_elsewhere(d["uid"], rid):
                continue
            core.offer(rid, d["uid"])
            dl = lang_of(d["uid"])
            dest = (L("dest_unknown", dl) if r["d_lat"] is None
                    else "%s км" % (r["dist_km"] or "?"))
            out.append(msg(d["uid"],
                           L("offer", dl, dist=round(dist, 1), price=money(r["price"], dl),
                             dest=dest, sec=int(core.OFFER_SEC)),
                           buttons=[[(L("btn_accept", dl), "acc:%d" % rid),
                                     (L("btn_decline", dl), "dec:%d" % rid)]]))
            break
    return out
