# -*- coding: utf-8 -*-
"""
Такси ТАП! — "бир мээ".

Платформага көз каранды эмес: Telegram, кийин WhatsApp, тиркеме — баары
ушул функцияларды чакырат. Ар бир функция жөнөтүлө турган билдирүүлөрдүн
тизмесин (Out) кайтарат; аларды "ооз" (bot.py, whatsapp.py) өз тилине
которуп жөнөтөт.

Колдонуучу `uid` менен аныкталат: 'tg:123456', кийин 'wa:996555...'.

Out (dict):
    {"to": uid, "text": str,
     "buttons": [[(label, data), ...], ...],    # билдирүүнүн астындагы баскычтар
     "keyboard": [[{"text":..., "contact"|"location": True}, ...]],  # ылдыйкы меню
     "remove_kb": bool,
     "location": (lat, lon),                    # картадагы чекит
     "photo": file_id}
"""

import os

import core
from strings import L, T

ADMINS = ["tg:" + x.strip() for x in (os.environ.get("ADMIN_IDS") or "").split(",") if x.strip()]


# ==================== Out жардамчылары ====================

def msg(to, text, buttons=None, keyboard=None, remove_kb=False):
    o = {"to": to, "text": text}
    if buttons:
        o["buttons"] = buttons
    if keyboard:
        o["keyboard"] = keyboard
    if remove_kb:
        o["remove_kb"] = True
    return o


def loc(to, lat, lon):
    return {"to": to, "location": (lat, lon)}


def lang_of(uid):
    u = core.get_user(uid)
    return (u or {}).get("lang") or "ky"


def _is(text, key):
    """Баскычтын жазуусу кайсы тилде болсо да таанылат."""
    return text in T[key]


def money(price, lang):
    return "%d сом" % price if price else L("price_meter", lang)


# ==================== Меню ====================

def menu(uid, text=None):
    lang = lang_of(uid)
    d = core.get_driver(uid)
    drv = "btn_driver_panel" if d and d["status"] in ("active", "pending") else "btn_become_driver"
    kb = [[{"text": L("btn_order", lang)}],
          [{"text": L(drv, lang)}],
          [{"text": L("btn_help", lang)}, {"text": L("btn_lang", lang)}]]
    return [msg(uid, text or L("welcome", lang), keyboard=kb)]


def ask_lang(uid):
    return [msg(uid, L("choose_lang"), buttons=[[("Кыргызча", "lang:ky"), ("Русский", "lang:ru")]])]


def on_start(uid, name=""):
    new = core.get_user(uid) is None
    core.ensure_user(uid, name)
    core.set_state(uid, {})
    return ask_lang(uid) if new else menu(uid)


def _back_kb(lang):
    return [[{"text": L("btn_cancel", lang)}]]


# ==================== Заказ (жүргүнчү) ====================

def start_order(uid):
    lang = lang_of(uid)
    if core.active_ride_of(uid):
        return [msg(uid, L("have_active", lang))]
    u = core.get_user(uid)
    if not u.get("phone"):
        core.set_state(uid, {"s": "phone", "after": "order"})
        return [msg(uid, L("ask_phone", lang),
                    keyboard=[[{"text": L("btn_share_phone", lang), "contact": True}],
                              [{"text": L("btn_cancel", lang)}]])]
    core.set_state(uid, {"s": "pickup"})
    return [msg(uid, L("ask_pickup", lang),
                keyboard=[[{"text": L("btn_share_loc", lang), "location": True}],
                          [{"text": L("btn_cancel", lang)}]])]


def _show_quote(uid, st):
    lang = lang_of(uid)
    q = core.quote(st["p"][0], st["p"][1], *(st.get("d") or (None, None)))
    if not q["city"]:
        core.set_state(uid, {})
        return menu(uid, L("no_city", lang))
    surge = L("surge", lang, k=q["surge"]) if q["surge"] > 1 else ""
    if q["price"]:
        text = L("quote", lang, city=q["city"], km=q["dist_km"], price=q["price"], surge=surge)
    else:
        t = q["tariff"]
        text = L("quote_open", lang, city=q["city"], base=int(t["base"]),
                 per_km=int(t["per_km"]), min=int(t["min_price"]), surge=surge)
    st["s"] = "confirm"
    core.set_state(uid, st)
    return [msg(uid, text, buttons=[[(L("btn_confirm", lang), "ord:ok"), (L("btn_no", lang), "ord:no")]])]


def confirm_order(uid):
    lang = lang_of(uid)
    st = core.get_state(uid)
    if st.get("s") != "confirm":
        return menu(uid)
    if core.active_ride_of(uid):
        return [msg(uid, L("have_active", lang))]
    d = st.get("d") or (None, None)
    q = core.quote(st["p"][0], st["p"][1], d[0], d[1])
    rid = core.create_ride(uid, q, st["p"][0], st["p"][1], d[0], d[1])
    core.set_state(uid, {})
    return [msg(uid, L("searching", lang), remove_kb=True),
            msg(uid, "№%d" % rid, buttons=[[(L("btn_pcancel", lang), "pcx:%d" % rid)]])]


def passenger_cancel(uid, rid):
    lang = lang_of(uid)
    r = core.get_ride(rid)
    if not r or r["passenger"] != uid:
        return []
    old = core.cancel(rid, uid)
    if not old:
        return [msg(uid, L("cant_cancel", lang))]
    out = menu(uid, L("p_cancelled", lang))
    if old["driver"]:
        out.append(msg(old["driver"], L("d_cancelled_by_p", lang_of(old["driver"]))))
    if old["offered_to"]:
        out.append(msg(old["offered_to"], L("offer_expired", lang_of(old["offered_to"]))))
    return out


def rate(uid, rid, stars):
    if core.rate(rid, uid, stars):
        return menu(uid, L("thanks_rate", lang_of(uid)))
    return []


# ==================== Айдоочу ====================

def become_driver(uid):
    lang = lang_of(uid)
    u = core.get_user(uid)
    if not u.get("phone"):
        core.set_state(uid, {"s": "phone", "after": "driver"})
        return [msg(uid, L("ask_phone", lang),
                    keyboard=[[{"text": L("btn_share_phone", lang), "contact": True}],
                              [{"text": L("btn_cancel", lang)}]])]
    core.set_state(uid, {"s": "car_model"})
    return [msg(uid, L("ask_car_model", lang), keyboard=_back_kb(lang))]


def driver_panel(uid):
    lang = lang_of(uid)
    d = core.get_driver(uid)
    if not d:
        return become_driver(uid)
    if d["status"] == "pending":
        status = L("st_pending", lang)
    elif d["status"] == "blocked":
        status = L("st_blocked", lang)
    else:
        status = L("st_online" if core.is_available(d) or d["busy_ride"] else "st_offline", lang)
    text = L("panel", lang, status=status, balance=int(d["balance"] or 0),
             rating=d["rating"], done=d["rides_done"], howto=L("howto_online", lang))
    if (d["balance"] or 0) < core.MIN_BALANCE:
        text += "\n\n" + L("low_balance", lang)
    kb = [[{"text": L("btn_offline", lang)}], [{"text": L("btn_topup", lang)}],
          [{"text": L("btn_cancel", lang)}]]
    return [msg(uid, text, keyboard=kb)]


def _car_step(uid, st, text):
    lang = lang_of(uid)
    nxt = {"car_model": ("car_color", "ask_car_color"),
           "car_color": ("car_plate", "ask_car_plate")}
    st[st["s"]] = text.strip()[:60]
    if st["s"] in nxt:
        st["s"], ask = nxt[st["s"]]
        core.set_state(uid, st)
        return [msg(uid, L(ask, lang), keyboard=_back_kb(lang))]
    core.add_driver(uid, st["car_model"], st["car_color"], st["car_plate"])
    core.set_state(uid, {})
    u = core.get_user(uid)
    out = menu(uid, L("driver_pending", lang))
    card = ("🆕 <b>Жаңы айдоочу</b>\n%s · %s\n🚗 %s %s, <b>%s</b>"
            % (u.get("name") or "", u.get("phone") or "", st["car_color"], st["car_model"],
               st["car_plate"]))
    for a in ADMINS:
        out.append(msg(a, card, buttons=[[("✅ Ырастоо", "adm:ok:" + uid),
                                          ("❌ Баш тартуу", "adm:no:" + uid)]]))
    return out


def go_offline(uid):
    if core.get_driver(uid):
        core.set_driver(uid, online=0, live_until=None)
    return [msg(uid, L("went_offline", lang_of(uid)))]


def driver_location(uid, lat, lon, live_period=None, date=None):
    d = core.get_driver(uid)
    if not d or d["status"] != "active":
        return []
    was = core.is_available(d)
    core.driver_location(uid, lat, lon, live_period, date)
    if not was and core.is_available(core.get_driver(uid)):
        return [msg(uid, L("went_online", lang_of(uid)))]
    return []


def driver_accept(uid, rid):
    lang = lang_of(uid)
    if not core.accept(rid, uid):
        return [msg(uid, L("offer_taken", lang))]
    r = core.get_ride(rid)
    p = core.get_user(r["passenger"])
    d = core.get_driver(uid)
    du = core.get_user(uid)
    plang = lang_of(r["passenger"])
    btns = [[(L("btn_arrived", lang), "arr:%d" % rid)], [(L("btn_dcancel", lang), "dcx:%d" % rid)]]
    out = [msg(uid, L("d_accepted", lang, name=p.get("name") or "", phone=p.get("phone") or "",
                      price=money(r["price"], lang)), buttons=btns),
           loc(uid, r["p_lat"], r["p_lon"])]
    if r["d_lat"] is not None:
        out += [msg(uid, L("d_dest", lang)), loc(uid, r["d_lat"], r["d_lon"])]
    out.append(msg(r["passenger"], L("found", plang, name=du.get("name") or "",
                                     rating=d["rating"], color=d["car_color"],
                                     model=d["car_model"], plate=d["car_plate"],
                                     phone=du.get("phone") or ""),
                   buttons=[[(L("btn_pcancel", plang), "pcx:%d" % rid)]]))
    if d["lat"] is not None:
        out.append(loc(r["passenger"], d["lat"], d["lon"]))
    return out


def driver_decline(uid, rid):
    r = core.get_ride(rid)
    if r and r["offered_to"] == uid:
        core.mark_tried(rid, uid)
    return [msg(uid, "👌")]


def driver_step(uid, rid):
    lang = lang_of(uid)
    new = core.advance(rid, uid)
    if not new:
        return []
    r = core.get_ride(rid)
    plang = lang_of(r["passenger"])
    if new == "arrived":
        return [msg(uid, L("d_arrived", lang), buttons=[[(L("btn_start", lang), "go:%d" % rid)],
                                                        [(L("btn_dcancel", lang), "dcx:%d" % rid)]]),
                msg(r["passenger"], L("arrived", plang))]
    if new == "in_trip":
        return [msg(uid, L("d_started", lang), buttons=[[(L("btn_finish", lang), "fin:%d" % rid)]]),
                msg(r["passenger"], L("started", plang), remove_kb=True)]
    # completed
    d = core.get_driver(uid)
    fee = ""
    if core.COMMISSION_PCT > 0 and r["price"]:
        fee = L("d_fee", lang, fee=round(r["price"] * core.COMMISSION_PCT / 100.0, 2),
                balance=int(d["balance"]))
    stars = [[("⭐" * n, "rate:%d:%d" % (rid, n)) for n in (1, 2, 3)],
             [("⭐" * n, "rate:%d:%d" % (rid, n)) for n in (4, 5)]]
    return [msg(uid, L("d_completed", lang, fee=fee)),
            msg(r["passenger"], L("completed", plang, price=money(r["price"], plang)), buttons=stars)]


def driver_cancel(uid, rid):
    r = core.get_ride(rid)
    if not r or r["driver"] != uid:
        return []
    old = core.cancel(rid, uid, allowed=("accepted", "arrived"))
    if not old:
        return []
    plang = lang_of(old["passenger"])
    return [msg(uid, L("d_cancelled", lang_of(uid))),
            msg(old["passenger"], L("p_cancelled_by_driver", plang))] + menu(old["passenger"], "🚕")


# ==================== Баланс ====================

def ask_topup(uid):
    if not core.get_driver(uid):
        return [msg(uid, L("not_driver", lang_of(uid)))]
    core.set_state(uid, {"s": "topup"})
    return [msg(uid, L("ask_topup", lang_of(uid)), keyboard=_back_kb(lang_of(uid)))]


def topup_photo(uid, file_id):
    tx = core.add_tx(uid, 0, "topup", status="pending", proof=file_id)
    core.set_state(uid, {})
    u = core.get_user(uid)
    out = menu(uid, L("topup_sent", lang_of(uid)))
    amounts = [[("%d" % a, "top:%d:%d" % (tx, a)) for a in (200, 500, 1000)],
               [("%d" % a, "top:%d:%d" % (tx, a)) for a in (2000, 5000)],
               [("❌ Жок", "topno:%d" % tx)]]
    for a in ADMINS:
        out.append({"to": a, "photo": file_id,
                    "text": "💰 Толуктоо #%d\n%s · %s\nСумманы тандаңыз:"
                            % (tx, u.get("name") or "", u.get("phone") or ""),
                    "buttons": amounts})
    return out


# ==================== Админ ====================

def admin_button(uid, data):
    if uid not in ADMINS:
        return []
    parts = data.split(":")
    if parts[0] == "adm":
        target = ":".join(parts[2:])
        ok = parts[1] == "ok"
        core.set_driver(target, status="active" if ok else "blocked")
        if ok:
            core.set_user(target, role="driver")
        tl = lang_of(target)
        note = (L("driver_approved", tl, howto=L("howto_online", tl)) if ok
                else L("driver_rejected", tl))
        return [msg(uid, "✅" if ok else "❌")] + menu(target, note)
    if parts[0] == "top":
        tx = core.approve_tx(int(parts[1]), float(parts[2]), uid)
        if not tx:
            return [msg(uid, "Бул чек мурун каралган.")]
        return [msg(uid, "✅ +%s сом" % parts[2]),
                msg(tx["driver"], L("topup_ok", lang_of(tx["driver"]), amount=parts[2]))]
    if parts[0] == "topno":
        tx = core.reject_tx(int(parts[1]), uid)
        if not tx:
            return []
        return [msg(uid, "❌"), msg(tx["driver"], L("topup_no", lang_of(tx["driver"])))]
    return []


def admin_command(uid, text):
    if uid not in ADMINS:
        return None
    p = text.split()
    if p[0] == "/tarif":
        # /tarif Каракол 60 18 3 100
        if len(p) != 6:
            return [msg(uid, "Колдонуу: /tarif <шаар> <отуруу> <км> <мүн> <минимум>\n"
                             "Мис: /tarif Каракол 60 18 3 100")]
        try:
            vals = [float(x) for x in p[2:]]
        except ValueError:
            return [msg(uid, "Сандар туура эмес.")]
        core.set_tariff(p[1], *vals)
        return [msg(uid, "✅ %s тарифи сакталды." % p[1])]
    if p[0] == "/stat":
        rows = core.query("SELECT status, COUNT(*) AS n FROM rides GROUP BY status", (), "all")
        on = len(core.online_drivers())
        lines = ["%s: %d" % (r["status"], r["n"]) for r in rows] or ["сапар жок"]
        return [msg(uid, "📊 Онлайн айдоочу: %d\n" % on + "\n".join(lines))]
    if p[0] == "/pending":
        rows = core.query("SELECT d.*, u.name, u.phone FROM drivers d JOIN users u ON u.uid=d.uid "
                          "WHERE d.status='pending'", (), "all")
        if not rows:
            return [msg(uid, "Күтүп жаткан айдоочу жок.")]
        return [msg(uid, "%s · %s\n🚗 %s %s, %s" % (r["name"], r["phone"], r["car_color"],
                                                   r["car_model"], r["car_plate"]),
                    buttons=[[("✅", "adm:ok:" + r["uid"]), ("❌", "adm:no:" + r["uid"])]])
                for r in rows]
    return None


def web_login_start(uid, name, tok):
    """Сайттан келген колдонуучу: номерин ырастайт."""
    core.ensure_user(uid, name)
    lang = lang_of(uid)
    if not core.web_session(tok):
        return menu(uid, L("web_bad", lang))
    core.set_state(uid, {"s": "phone", "after": "web:" + tok})
    return [msg(uid, L("web_confirm", lang),
                keyboard=[[{"text": L("btn_share_phone", lang), "contact": True}],
                          [{"text": L("btn_cancel", lang)}]])]


# ==================== Кириш чекиттери (ооздор чакырат) ====================

def on_text(uid, text, name=""):
    text = (text or "").strip()
    if text.startswith("/start web_"):
        return web_login_start(uid, name, text.split("web_", 1)[1].strip())
    if text.startswith("/start"):
        return on_start(uid, name)
    core.ensure_user(uid, name)
    lang = lang_of(uid)
    if text.startswith("/"):
        out = admin_command(uid, text)
        if out is not None:
            return out
    if _is(text, "btn_cancel"):
        core.set_state(uid, {})
        return menu(uid)
    if _is(text, "btn_order"):
        return start_order(uid)
    if _is(text, "btn_become_driver"):
        return become_driver(uid)
    if _is(text, "btn_driver_panel"):
        return driver_panel(uid)
    if _is(text, "btn_offline"):
        return go_offline(uid)
    if _is(text, "btn_topup"):
        return ask_topup(uid)
    if _is(text, "btn_help") or text == "/help":
        return [msg(uid, L("help", lang))]
    if _is(text, "btn_lang"):
        return ask_lang(uid)
    st = core.get_state(uid)
    if st.get("s") in ("car_model", "car_color", "car_plate") and text:
        return _car_step(uid, st, text)
    if st.get("s") in ("pickup", "dest"):
        return [msg(uid, L("need_location", lang))]
    return menu(uid, L("unknown", lang))


def on_contact(uid, phone, name=""):
    core.ensure_user(uid, name)
    core.set_user(uid, phone=phone if phone.startswith("+") else "+" + phone)
    after = core.get_state(uid).get("after") or ""
    core.set_state(uid, {})
    if after.startswith("web:"):
        ok = core.web_session_verify(after[4:], phone)
        lang = lang_of(uid)
        return menu(uid, L("web_ok" if ok else "web_bad", lang))
    if after == "driver":
        return become_driver(uid)
    return start_order(uid)


def on_location(uid, lat, lon, live_period=None, date=None, edited=False):
    """
    Жүргүнчү заказ берип жатса — бул анын чекити.
    Айдоочунун live location'у (же жаңыртуусу) — анын жайгашкан жери.
    """
    core.ensure_user(uid)
    st = core.get_state(uid)
    if live_period or edited or st.get("s") not in ("pickup", "dest"):
        return driver_location(uid, lat, lon, live_period, date)
    if st["s"] == "pickup":
        st.update(s="dest", p=[lat, lon])
        core.set_state(uid, st)
        lang = lang_of(uid)
        return [msg(uid, L("ask_dest", lang), keyboard=_back_kb(lang),
                    buttons=[[(L("btn_skip_dest", lang), "skipdest")]])]
    st["d"] = [lat, lon]
    return _show_quote(uid, st)


def on_photo(uid, file_id):
    if core.get_state(uid).get("s") == "topup":
        return topup_photo(uid, file_id)
    return []


def on_button(uid, data, name=""):
    core.ensure_user(uid, name)
    head, _, arg = data.partition(":")
    if head == "lang":
        core.set_user(uid, lang="ru" if arg == "ru" else "ky")
        return menu(uid)
    if head == "ord":
        if arg == "ok":
            return confirm_order(uid)
        core.set_state(uid, {})
        return menu(uid)
    if head == "skipdest":
        st = core.get_state(uid)
        if st.get("s") == "dest":
            return _show_quote(uid, st)
        return []
    if head in ("adm", "top", "topno"):
        return admin_button(uid, data)
    if head == "rate":
        rid, stars = arg.split(":")
        return rate(uid, int(rid), max(1, min(5, int(stars))))
    if not arg.isdigit():
        return []
    rid = int(arg)
    return {
        "pcx": passenger_cancel, "acc": driver_accept, "dec": driver_decline,
        "arr": driver_step, "go": driver_step, "fin": driver_step, "dcx": driver_cancel,
    }.get(head, lambda u, r: [])(uid, rid)
