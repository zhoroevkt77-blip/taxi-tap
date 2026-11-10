#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Такси ТАП! — негизги процесс: сайт + dispatch + Telegram бот.

Бот эки гана иш кылат:
  1. Номер ырастоо: сайт → t.me/<бот>?start=web_<токен> → «Номеримди жөнөтүү»
  2. Билдирүүлөр: жаңы заказ, айдоочу келди, арыз ырасталды… (шилтеме менен)

Бардык башка иш сайтта. Токен жок болсо да сайт иштей берет (билдирүүсүз).
Иштетүү: python bot.py
"""

import json
import os
import ssl
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request

import core
import dispatch
import web
from strings import L

TOKEN_FILE = os.path.join(core.BASE, "token.txt")
TICK_SEC = 2

_ctx = ssl.create_default_context()
API = None
_pending = {}            # Telegram чаты → сайттын кирүү токени (номер күтүлүүдө)
_lock = threading.Lock()


def read_token():
    t = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    if not t and os.path.exists(TOKEN_FILE):
        t = open(TOKEN_FILE, encoding="utf-8").read().strip()
    return t or None


def api(method, **params):
    if not API:
        return {"ok": False}
    data = urllib.parse.urlencode(
        {k: (json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v)
         for k, v in params.items() if v is not None}).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(API + method, data=data),
                                    timeout=70, context=_ctx) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            desc = json.loads(e.read().decode()).get("description")
        except Exception:
            desc = ""
        print("  API катасы:", method, e.code, desc, flush=True)
        return {"ok": False, "code": e.code, "description": desc}
    except Exception as e:
        print("  API катасы:", method, e, flush=True)
        return {"ok": False}


def site(path="/"):
    return (core.SITE_URL or "") + path


def send(chat, text, kb=None):
    return api("sendMessage", chat_id=chat, text=text, parse_mode="HTML",
               disable_web_page_preview=True, reply_markup=kb)


def open_kb(path, lang="ky"):
    if not core.SITE_URL.startswith("https://"):
        return None                       # Telegram http шилтеме баскычын кабыл албайт
    return {"inline_keyboard": [[{"text": L("btn_open", lang), "url": site(path)}]]}


# ==================== Билдирүүлөрдү жеткирүү ====================

def deliver(outs):
    """flow/dispatch'тен келген Out'тор → Telegram (номер менен байланышкан чатка)."""
    with _lock:
        for o in outs or []:
            to = core.tg_of(o.get("to") or "")
            if to and to.startswith("tg:"):
                send(to[3:], o["text"], open_kb(o.get("path") or "/"))


# ==================== Telegram → ====================

def _user_by_tg(tg):
    return core.query("SELECT * FROM users WHERE tg_uid=? LIMIT 1", (tg,), "one")


def notify_kb(u):
    if not u:
        return None
    on = u.get("notify", 1)
    return {"inline_keyboard": [[{"text": L("btn_notify_off" if on else "btn_notify_on"),
                                  "callback_data": "notify:%d" % (0 if on else 1)}]]}


def handle_update(up):
    if "callback_query" in up:
        cb = up["callback_query"]
        tg = "tg:%d" % cb["from"]["id"]
        u = _user_by_tg(tg)
        if u and (cb.get("data") or "").startswith("notify:"):
            on = cb["data"].endswith("1")
            core.set_user(u["uid"], notify=1 if on else 0)
            api("answerCallbackQuery", callback_query_id=cb["id"],
                text=L("notify_on" if on else "notify_off"))
            api("editMessageReplyMarkup", chat_id=cb["message"]["chat"]["id"],
                message_id=cb["message"]["message_id"], reply_markup=notify_kb(_user_by_tg(tg)))
        else:
            api("answerCallbackQuery", callback_query_id=cb["id"])
        return

    m = up.get("message")
    if not m or m.get("chat", {}).get("type") != "private":
        return
    chat, tg = m["chat"]["id"], "tg:%d" % m["from"]["id"]
    text = (m.get("text") or "").strip()

    if text.startswith("/start web_"):
        _pending[chat] = text.split("web_", 1)[1].strip()
        send(chat, L("ask_phone"), {"keyboard": [[{"text": L("btn_share_phone"),
                                                   "request_contact": True}]],
                                    "resize_keyboard": True, "one_time_keyboard": True})
        return

    if "contact" in m:
        c = m["contact"]
        if c.get("user_id") != m["from"]["id"]:
            send(chat, L("foreign_contact"))
            return
        tok = _pending.pop(chat, None)
        if not tok:
            send(chat, L("welcome", site=site("/")), {"remove_keyboard": True})
            return
        s = core.web_session(tok)
        uid = core.web_session_verify(tok, c.get("phone_number") or "", tg)
        if uid:
            send(chat, L("web_ok"), {"remove_keyboard": True})
            send(chat, L("notify_on"), notify_kb(core.get_user(uid)))
        elif s and s.get("kind") == "admin":
            send(chat, L("not_admin"), {"remove_keyboard": True})
        else:
            send(chat, L("web_bad"), {"remove_keyboard": True})
        return

    # /start жана башка нерселер: сайттын дареги + билдирүү жөндөөсү
    send(chat, L("welcome", site=site("/")), notify_kb(_user_by_tg(tg)) or {"remove_keyboard": True})


# ==================== Иштетүү ====================

def dispatch_worker():
    while True:
        try:
            deliver(dispatch.tick())
        except Exception:
            traceback.print_exc()
        time.sleep(TICK_SEC)


def main():
    global API
    core.init_db()
    token = read_token()
    if token:
        API = "https://api.telegram.org/bot%s/" % token
        me = {}
        for _ in range(6):
            me = api("getMe")
            if me.get("ok"):
                break
            time.sleep(5)
        api("deleteWebhook")            # webhook турса getUpdates 409 берет
        uname = (me.get("result") or {}).get("username", "")
        if uname and not web.BOT_USERNAME:
            web.BOT_USERNAME = uname
        print("\n  Бот: @%s" % (uname or "?"), flush=True)
    else:
        print("\n  Бот: токен жок — билдирүүлөр жиберилбейт", flush=True)
    print("  База: %s · Файлдар: %s" % ("Postgres" if core.IS_PG else "SQLite", core.UPLOADS),
          flush=True)
    print("  Админдер: %s" % (", ".join(core.ADMIN_IDS + core.ADMIN_PHONES) or "жок"), flush=True)
    if not core.SITE_URL:
        print("  ⚠️  SITE_URL коюлган жок — билдирүүлөрдө шилтеме болбойт", flush=True)

    web.deliver = deliver
    web.start()
    threading.Thread(target=dispatch_worker, daemon=True).start()

    if not API:
        while True:
            time.sleep(3600)
    offset = 0
    while True:
        r = api("getUpdates", offset=offset, timeout=50,
                allowed_updates=["message", "callback_query"])
        if not r.get("ok"):
            # 409: бул токен менен башка жерде да бот иштеп жатат
            time.sleep(10 if r.get("code") == 409 else 3)
            continue
        for up in r.get("result", []):
            offset = up["update_id"] + 1
            try:
                handle_update(up)
            except Exception:
                traceback.print_exc()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n  Токтотулду.\n")
