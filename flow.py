# -*- coding: utf-8 -*-
"""
Такси ТАП! — аракеттер жана билдирүүлөр ("бир мээ").

Бардык иш сайтта жасалат. Бул модуль аракеттерди аткарат жана кимге эмне
деп билдирүү керек экенин кайтарат. Билдирүүнү "ооз" жеткирет: азыр
Telegram (bot.py), кийин push же WhatsApp.

Out (dict):  {"to": uid, "text": str, "path": "/driver"}
    to   — 'ph:+996...' (аккаунт) же 'tg:123' (түз Telegram, мис. админ)
    path — сайттын кайсы бети ачылсын (билдирүүнүн астындагы баскыч)
"""

import core
from strings import L


def note(to, key, path="/", **kw):
    u = core.get_user(to) if not to.startswith("tg:") else None
    lang = (u or {}).get("lang") or "ky"
    return {"to": to, "text": L(key, lang, **kw), "path": path}


def money(price, lang="ky"):
    return "%d сом" % price if price else L("price_meter", lang)


# ==================== Айдоочу ====================

def driver_accept(uid, rid):
    if not core.accept(rid, uid):
        return None                           # башка айдоочу алды / мөөнөт өттү
    r, d = core.get_ride(rid), core.get_driver(uid)
    eta = ""
    if d["lat"] is not None:
        km = core.road_km(d["lat"], d["lon"], r["p_lat"], r["p_lon"])
        eta = L("eta", m=max(1, round(km / core.AVG_SPEED_KMH * 60)))
    return [note(r["passenger"], "p_found", "/", car="%s %s" % (d["car_color"], d["car_model"]),
                 plate=d["car_plate"], eta=eta)]


def driver_decline(uid, rid):
    r = core.get_ride(rid)
    if r and r["offered_to"] == uid:
        core.mark_tried(rid, uid)
    return []


def driver_step(uid, rid):
    new = core.advance(rid, uid)
    if not new:
        return None
    p = core.get_ride(rid)["passenger"]
    if new == "arrived":
        return [note(p, "p_arrived")]
    if new == "completed":
        return [note(p, "p_completed")]
    return []


def driver_cancel(uid, rid):
    r = core.get_ride(rid)
    if not r or r["driver"] != uid:
        return None
    old = core.cancel(rid, uid, allowed=("accepted", "arrived"))
    return [note(old["passenger"], "p_driver_cancel")] if old else None


def register_driver(uid, name, model, color, plate, docs):
    core.register_driver(uid, name, model, color, plate, docs)
    return [note(a, "a_new_driver", "/admin", name=name, car="%s %s, %s" % (color, model, plate))
            for a in core.admins()]


def request_topup(uid, claimed, proof):
    core.request_topup(uid, claimed, proof)
    u = core.get_user(uid) or {}
    return [note(a, "a_new_topup", "/admin", name=u.get("name") or u.get("phone"),
                 amount=int(claimed)) for a in core.admins()]


# ==================== Жүргүнчү ====================

def passenger_cancel(uid, rid):
    r = core.get_ride(rid)
    if not r or r["passenger"] != uid:
        return None
    old = core.cancel(rid, uid)
    if not old:
        return None
    who = old["driver"] or old["offered_to"]
    return [note(who, "d_passenger_cancel", "/driver")] if who else []


# ==================== Админ ====================

def admin_driver(target, action, reason=""):
    if action == "approve":
        core.set_driver(target, status="active", reject_note=None)
        return [note(target, "d_approved", "/driver")]
    if action == "reject":
        core.set_driver(target, status="rejected", reject_note=reason or None)
        return [note(target, "d_rejected", "/driver", note=(" Себеби: " + reason) if reason else "")]
    if action == "block":
        core.set_driver(target, status="blocked", online=0)
        return [note(target, "d_blocked", "/driver")]
    if action == "unblock":
        core.set_driver(target, status="active")
        return [note(target, "d_approved", "/driver")]
    return []


def admin_topup(admin, tx_id, amount=None):
    if amount:
        tx = core.approve_tx(tx_id, amount, admin)
        return [note(tx["driver"], "d_topup_ok", "/driver", amount=int(amount))] if tx else None
    tx = core.reject_tx(tx_id, admin)
    return [note(tx["driver"], "d_topup_no", "/driver")] if tx else None


def admin_cancel(rid):
    r = core.cancel(rid, "admin", allowed=("searching", "accepted", "arrived", "in_trip"))
    if not r:
        return None
    outs = [note(r["passenger"], "p_admin_cancel")]
    for who in {r["driver"], r["offered_to"]} - {None}:
        outs.append(note(who, "d_admin_cancel", "/driver", id=r["id"]))
    return outs
