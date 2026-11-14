# -*- coding: utf-8 -*-
"""
Такси ТАП! — кароолчу (watchdog). Өзүнчө Railway кызматы болуп иштейт.

Ар мүнөт сайттын /health дарегин текшерет. 3 жолу катары менен жооп бербесе
(~3 мүнөт, жаңыртуу учурундагы кыска үзгүлтүккө кабар келбесин үчүн) — админдерге
Telegram'га «🔴 сайт токтоду» деп жазат. Кайра иштесе — «🟢 кайра иштеп жатат».

Керектүү өзгөрмөлөр (негизги кызматтан шилтеме менен): TELEGRAM_BOT_TOKEN,
SITE_URL, DATABASE_URL (админдердин Telegram'ын табуу үчүн), ADMIN_PHONES/ADMIN_IDS.
"""

import json
import os
import time
import urllib.parse
import urllib.request

TOKEN = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
SITE = (os.environ.get("SITE_URL") or "").rstrip("/")
EVERY = int(os.environ.get("WATCH_EVERY") or 60)       # секунд
FAILS = int(os.environ.get("WATCH_FAILS") or 3)        # канча жолу катары менен
TZ = 6 * 3600

_chats = []


def hm(t):
    return time.strftime("%H:%M", time.gmtime(t + TZ))


def admin_chats():
    """Админдердин Telegram ID'лери. База жеткиликсиз болсо — мурунку тизме калат."""
    global _chats
    try:
        import core
        ids = [a[3:] for a in core.admins() if a.startswith("tg:")]
        if ids:
            _chats = ids
    except Exception as e:                                   # база иштебей калса да кабар кетсин
        print("  admins: %s" % e, flush=True)
    return _chats


def tg(text):
    for chat in admin_chats():
        try:
            data = urllib.parse.urlencode({"chat_id": chat, "text": text, "parse_mode": "HTML"}).encode()
            urllib.request.urlopen("https://api.telegram.org/bot%s/sendMessage" % TOKEN, data=data, timeout=15).read()
        except Exception as e:
            print("  tg: %s" % e, flush=True)


def check():
    try:
        with urllib.request.urlopen(SITE + "/health", timeout=15) as r:
            return r.status == 200 and json.loads(r.read().decode() or "{}").get("ok") is True
    except Exception:
        return False


def main():
    if not (TOKEN and SITE):
        print("  Кароолчу: TELEGRAM_BOT_TOKEN же SITE_URL жок — токтоду", flush=True)
        return
    print("  Кароолчу: %s/health ар %d сек (%d жолу катары менен → кабар)" % (SITE, EVERY, FAILS), flush=True)
    admin_chats()
    bad, down_since, alerted = 0, None, False
    while True:
        ok = check()
        now = time.time()
        if ok:
            if alerted:
                mins = max(1, round((now - down_since) / 60))
                tg("🟢 <b>Такси ТАП! кайра иштеп жатат</b>\nСайт %d мүнөт жооп бербей турду (%s – %s)." % (mins, hm(down_since), hm(now)))
            bad, down_since, alerted = 0, None, False
        else:
            bad += 1
            down_since = down_since or now
            print("  /health жооп жок (%d)" % bad, flush=True)
            if bad >= FAILS and not alerted:
                tg("🔴 <b>Такси ТАП! сайты жооп бербей жатат</b>\n%s'дан бери (%d мүнөт). Railway'ди текшериңиз: "
                   "акыркы деплой, логдор.\n%s" % (hm(down_since), max(1, round((now - down_since) / 60)), SITE))
                alerted = True
        time.sleep(EVERY)


if __name__ == "__main__":
    main()
