# -*- coding: utf-8 -*-
"""
Такси ТАП! — тейлөө: камдык көчүрмө (backup) жана ката кабарлары.

- Күн сайын ~03:00дө (Бишкек) бардык таблицалар JSON.gz болуп /data/backups'ка
  сакталат (акыркы 14ү) жана админдерге Telegram'га файл болуп жиберилет —
  ошондо Railway'ге бир нерсе болсо да көчүрмө сизде калат.
- Ката чыкса админдерге кыска кабар (бир эле ката 10 мүнөттө бир жолу).

Калыбына келтирүү: python restore.py <файл.json.gz>
"""

import gzip
import json
import os
import threading
import time
import traceback

import core

BACKUP_DIR = os.path.join(core.DATA_DIR, "backups")
KEEP = 14
BACKUP_HOUR = 3                      # Бишкек убактысы
# web_sessions — кирүү токендери, көчүрмөгө кирбейт (коопсуздук)
TABLES = ["users", "drivers", "rides", "ride_events", "balance_tx", "ratings",
          "tariffs", "settings"]

# bot.py коёт: send_text(tg_uid, text), send_file(tg_uid, path, caption)
send_text = None
send_file = None

_last_err = {}
_lock = threading.Lock()


def _admins():
    try:
        return core.admins()
    except Exception:
        return list(core.ADMIN_IDS)


def notify_admins(text):
    if not send_text:
        return
    for a in _admins():
        try:
            send_text(a, text)
        except Exception:
            pass


def report_error(where, exc=None):
    """Катаны логго жазат жана админге билдирет (бир эле ката 10 мүнөттө бир жолу)."""
    tb = traceback.format_exc()
    print("  КАТА [%s]\n%s" % (where, tb), flush=True)
    last = tb.strip().splitlines()[-1] if tb.strip() else str(exc)
    key = (where, last[:120])
    with _lock:
        if time.time() - _last_err.get(key, 0) < 600:
            return
        _last_err[key] = time.time()
    notify_admins("⚠️ <b>Такси ТАП! ката</b>\nКайда: %s\n<code>%s</code>"
                  % (where, last[:300].replace("<", "&lt;")))


# ==================== Камдык көчүрмө ====================

def backup():
    """Бардык таблицаларды бир файлга. Файлдын жолун кайтарат."""
    data = {"created_at": core.now(), "tables": {}}
    for t in TABLES:
        try:
            data["tables"][t] = core.query("SELECT * FROM %s" % t, (), "all")
        except Exception as e:
            data["tables"][t] = {"error": str(e)}
    os.makedirs(BACKUP_DIR, exist_ok=True)
    name = time.strftime("taxi-tap-%Y%m%d-%H%M.json.gz", time.gmtime(core.now() + core.TZ))
    path = os.path.join(BACKUP_DIR, name)
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, default=str)
    files = sorted(x for x in os.listdir(BACKUP_DIR) if x.endswith(".json.gz"))
    for old in files[:-KEEP]:
        try:
            os.remove(os.path.join(BACKUP_DIR, old))
        except OSError:
            pass
    return path


def backup_and_send():
    path = backup()
    st = core.admin_overview()["stats"]
    rows = sum(len(v) for v in json.load(gzip.open(path, "rt", encoding="utf-8"))["tables"].values()
               if isinstance(v, list))
    caption = ("💾 Камдык көчүрмө: %s\n%d жазуу · онлайн айдоочу: %d"
               % (os.path.basename(path), rows, st["online"]))
    if send_file:
        for a in _admins():
            try:
                send_file(a, path, caption)
            except Exception:
                report_error("backup жөнөтүү")
    return path


def backup_worker():
    """Күнүнө бир жолу, BACKUP_HOUR'дан кийин."""
    time.sleep(60)
    while True:
        try:
            lt = time.gmtime(core.now() + core.TZ)
            today = time.strftime("%Y-%m-%d", lt)
            if lt.tm_hour >= BACKUP_HOUR and core.get_setting("last_backup_day") != today:
                backup_and_send()
                core.set_setting("last_backup_day", today)
        except Exception:
            report_error("backup")
        time.sleep(600)


def restore(path):
    """Көчүрмөнү БОШ базага кайтарат (бар маалыматтын үстүнө жазбайт)."""
    data = json.load(gzip.open(path, "rt", encoding="utf-8"))
    core.init_db()
    for t in TABLES:
        rows = data["tables"].get(t)
        if not isinstance(rows, list) or not rows:
            continue
        if core.query("SELECT COUNT(*) AS n FROM %s" % t, (), "one")["n"]:
            print("  %s: бош эмес — өткөрүлдү" % t)
            continue
        cols = list(rows[0].keys())
        sql = "INSERT INTO %s (%s) VALUES (%s)" % (t, ", ".join(cols), ", ".join("?" * len(cols)))
        for r in rows:
            core.query(sql, tuple(r[c] for c in cols))
        print("  %s: %d жазуу" % (t, len(rows)))
    if core.IS_PG:          # SERIAL эсептегичтерин жаңылоо
        for t in ("rides", "ride_events", "balance_tx"):
            core.query("SELECT setval(pg_get_serial_sequence('%s','id'), "
                       "COALESCE((SELECT MAX(id) FROM %s), 1))" % (t, t), (), "one")
