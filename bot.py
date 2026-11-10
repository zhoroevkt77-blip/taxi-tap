#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Такси ТАП! — Telegram «оозу».

Бүт логика flow.py'да ("бир мээ"), бул файл Telegram менен сүйлөшөт гана:
жаңыртууларды алат, flow'го берет, кайткан Out'торду жөнөтөт.

Токен: TELEGRAM_BOT_TOKEN чөйрө өзгөрмөсү, же token.txt файлы.
Иштетүү: python bot.py
"""

import json
import os
import ssl
import threading
import time
import traceback
import urllib.parse
import urllib.request

import core
import dispatch
import flow

TOKEN_FILE = os.path.join(core.BASE, "token.txt")
TICK_SEC = 2

_ctx = ssl.create_default_context()
API = None
_send_lock = threading.Lock()


def read_token():
    t = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    if t:
        return t
    if os.path.exists(TOKEN_FILE):
        t = open(TOKEN_FILE, encoding="utf-8").read().strip()
        if t:
            return t
    raise SystemExit("\nТокен табылган жок!\n"
                     "Railway'де: Variables ичине TELEGRAM_BOT_TOKEN кош.\n"
                     "Жергиликтүү: echo -n \"ТОКЕН\" > token.txt\n")


def api(method, **params):
    data = urllib.parse.urlencode(
        {k: (json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v)
         for k, v in params.items() if v is not None}).encode()
    req = urllib.request.Request(API + method, data=data)
    try:
        with urllib.request.urlopen(req, timeout=70, context=_ctx) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        print("  API катасы:", method, e, flush=True)
        return {"ok": False}


# ==================== Out → Telegram ====================

def _markup(o):
    if o.get("buttons"):
        return {"inline_keyboard": [[{"text": t, "callback_data": d} for t, d in row]
                                    for row in o["buttons"]]}
    if o.get("keyboard"):
        rows = [[{"text": b["text"],
                  **({"request_contact": True} if b.get("contact") else {}),
                  **({"request_location": True} if b.get("location") else {})}
                 for b in row] for row in o["keyboard"]]
        return {"keyboard": rows, "resize_keyboard": True}
    if o.get("remove_kb"):
        return {"remove_keyboard": True}
    return None


def deliver(outs):
    with _send_lock:
        for o in outs or []:
            to = o.get("to") or ""
            if not to.startswith("tg:"):
                continue          # башка ооздун билдирүүсү (мис. WhatsApp)
            chat = to[3:]
            if o.get("location"):
                lat, lon = o["location"]
                api("sendLocation", chat_id=chat, latitude=lat, longitude=lon)
            elif o.get("photo"):
                api("sendPhoto", chat_id=chat, photo=o["photo"], caption=o.get("text", ""),
                    parse_mode="HTML", reply_markup=_markup(o))
            else:
                api("sendMessage", chat_id=chat, text=o["text"], parse_mode="HTML",
                    disable_web_page_preview=True, reply_markup=_markup(o))


# ==================== Telegram → flow ====================

def _name(u):
    return " ".join(x for x in (u.get("first_name"), u.get("last_name")) if x)


def handle_update(up):
    if "callback_query" in up:
        cb = up["callback_query"]
        api("answerCallbackQuery", callback_query_id=cb["id"])
        uid = "tg:%d" % cb["from"]["id"]
        return flow.on_button(uid, cb.get("data") or "", _name(cb["from"]))

    edited = "edited_message" in up
    m = up.get("message") or up.get("edited_message")
    if not m or m.get("chat", {}).get("type") != "private":
        return []
    uid = "tg:%d" % m["from"]["id"]
    name = _name(m["from"])

    if "location" in m:
        L = m["location"]
        return flow.on_location(uid, L["latitude"], L["longitude"],
                                live_period=L.get("live_period"), date=m.get("date"),
                                edited=edited)
    if edited:
        return []
    if "contact" in m:
        c = m["contact"]
        if c.get("user_id") != m["from"]["id"]:
            return flow.on_text(uid, "", name)      # башка бирөөнүн номери кабыл алынбайт
        return flow.on_contact(uid, c.get("phone_number") or "", name)
    if "photo" in m:
        return flow.on_photo(uid, m["photo"][-1]["file_id"])
    return flow.on_text(uid, m.get("text") or "", name)


def dispatch_worker():
    while True:
        try:
            deliver(dispatch.tick())
        except Exception:
            traceback.print_exc()
        time.sleep(TICK_SEC)


def main():
    global API
    API = "https://api.telegram.org/bot%s/" % read_token()
    core.init_db()

    me = {}
    for i in range(6):
        me = api("getMe")
        if me.get("ok"):
            break
        time.sleep(5)
    print("\n  Такси ТАП! иштеп жатат: @%s" % (me.get("result") or {}).get("username", "?"),
          flush=True)
    print("  База: %s" % ("Postgres" if core.IS_PG else "SQLite"), flush=True)
    print("  Админдер: %s" % (", ".join(flow.ADMINS) or "жок (ADMIN_IDS кой)"), flush=True)

    threading.Thread(target=dispatch_worker, daemon=True).start()

    offset = 0
    while True:
        r = api("getUpdates", offset=offset, timeout=50,
                allowed_updates=["message", "edited_message", "callback_query"])
        if not r.get("ok"):
            time.sleep(3)
            continue
        for up in r.get("result", []):
            offset = up["update_id"] + 1
            try:
                deliver(handle_update(up))
            except Exception:
                traceback.print_exc()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n  Бот токтотулду.\n")
