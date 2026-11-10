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

import html

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
        km = eta_km(d, r)
        eta = L("eta", m=max(1, round(km / core.AVG_SPEED_KMH * 60)))
    return [note(r["passenger"], "p_found", "/", car="%s %s" % (d["car_color"], d["car_model"]),
                 plate=d["car_plate"], eta=eta)]


def eta_km(d, r):
    """Айдоочудан жүргүнчүгө. Кийинки заказ болсо — азыркы сапардын аягы аркылуу."""
    if d.get("busy_ride") and d["busy_ride"] != r["id"]:
        cur = core.get_ride(d["busy_ride"])
        if cur and cur["d_lat"] is not None:
            return core.road_km(d["lat"], d["lon"], cur["d_lat"], cur["d_lon"]) + \
                core.road_km(cur["d_lat"], cur["d_lon"], r["p_lat"], r["p_lon"])
    return core.road_km(d["lat"], d["lon"], r["p_lat"], r["p_lon"])


def send_message(uid, rid, text):
    """Чат: жүргүнчү ↔ айдоочу, сапар активдүү болгондо гана."""
    r = core.get_ride(rid)
    if not r or uid not in (r["passenger"], r["driver"]) or \
            r["status"] not in ("accepted", "arrived", "in_trip"):
        return None
    if not core.add_message(rid, uid, text):
        return None
    to = r["driver"] if uid == r["passenger"] else r["passenger"]
    who = "Айдоочу" if uid == r["driver"] else ((core.get_user(uid) or {}).get("name") or "Жүргүнчү")
    return [note(to, "chat_msg", "/driver" if to == r["driver"] else "/", who=html.escape(who),
                 text=html.escape((text or "").strip()[:120]))]


def driver_sos(uid, p):
    """Айдоочу 🆘 басты: бардык админдерге шашылыш кабар + жери + сапары."""
    d = core.get_driver(uid) or {}
    u = core.get_user(uid) or {}
    r = core.get_ride(d["busy_ride"]) if d.get("busy_ride") else None
    where = ("https://maps.google.com/?q=%.6f,%.6f" % (p[0], p[1])) if p else "белгисиз"
    ride = (" · сапар №%d, жүргүнчү %s" % (r["id"], (core.get_user(r["passenger"]) or {}).get("phone") or "")) if r else ""
    if r:
        core.log_event(r["id"], "sos", uid)
    return [note(a, "a_sos", "/admin", name=u.get("name") or "", phone=u.get("phone") or "",
                 car="%s %s, %s" % (d.get("car_color") or "", d.get("car_model") or "", d.get("car_plate") or ""),
                 where=where, ride=ride) for a in core.admins()]


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
        out = [note(p, "p_completed")]
        d = core.get_driver(uid)
        if core.commission_pct() > 0 and (d["balance"] or 0) < core.min_balance():
            out.append(note(uid, "d_low_balance", "/driver", balance=int(d["balance"] or 0)))
        return out
    return []


def driver_cancel(uid, rid):
    r = core.get_ride(rid)
    if not r or r["driver"] != uid:
        return None
    old = core.cancel(rid, uid, allowed=("accepted", "arrived"))
    if old:
        core.add_activity(uid, core.ACT_CANCEL)
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
