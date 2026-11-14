"""Таксопарктар: парк өз айдоочуларын жана жүргүнчүлөрүн алып келет, комиссиядан үлүш алат.

Парктын кирешеси:
  • парктын айдоочулары төлөгөн комиссиянын share %ы;
  • парк тарткан (промокод/QR) ар бир жаңы жүргүнчүнүн биринчи бүткөн сапары үчүн ref_bonus сом.
Админ төлөп бергенин park_payouts'ка жазат → калдык = тапкан − төлөнгөн.
"""
import time

import core

REF_DAYS = 30          # жүргүнчү ушул мөөнөттө парктын коду менен биринчи сапарын бүтүрсө — бонус


def norm_code(c):
    return core.promo_norm(c or "")


def get(pid):
    return core.query("SELECT * FROM parks WHERE id=?", (pid,), "one") if pid else None


def by_owner(uid):
    return core.query("SELECT * FROM parks WHERE owner_uid=? AND active=1", (uid,), "one") if uid else None


def by_code(code):
    code = norm_code((code or "").split("-")[0])
    if not code:
        return None
    return (core.query("SELECT * FROM parks WHERE code=? AND active=1", (code,), "one")
            or core.query("SELECT * FROM parks WHERE promo=? AND active=1", (code,), "one"))


_LAT = dict(zip("абвгдеёжзийклмнңоөпрстуүфхцчшщыэюя",
                ["A","B","V","G","D","E","E","J","Z","I","I","K","L","M","N","N","O","O","P","R","S","T","U","U","F","H","C","CH","SH","SH","Y","E","YU","YA"]))


def ensure_code(p):
    """Ар бир паркка автоматтык QR коду: аттын 3 тамгасы + id (мисалы DRV12)."""
    if not p or p.get("code"):
        return p
    lat = "".join(_LAT.get(ch, ch.upper() if ch.isascii() and ch.isalpha() else "") for ch in (p["name"] or "").lower())
    cons = "".join(c for c in lat if c not in "AEIOUY") or lat
    base = (cons[:3] or "TAP") + str(p["id"])
    code, n = base, 1
    while core.query("SELECT id FROM parks WHERE (code=? OR promo=?) AND id<>?", (code, code, p["id"]), "one"):
        n += 1; code = base + str(n)
    core.query("UPDATE parks SET code=? WHERE id=?", (code, p["id"]))
    p = dict(p); p["code"] = code
    return p


def drv_tag(uid):
    """Айдоочунун QR'ы үчүн кыска белги (парктын коду + «-» + ушул)."""
    import zlib
    n, s, al = zlib.crc32(uid.encode()), "", "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
    for _ in range(4):
        s += al[n % len(al)]; n //= len(al)
    return s


def driver_by_tag(pid, tag):
    tag = (tag or "").upper()
    for d in _drivers(pid):
        if drv_tag(d["uid"]) == tag:
            return d["uid"]
    return None


def scan(raw):
    """/p/<КОД>[-<айдоочу>] ачылды: сканерди эсептейт. Кайтарат: (парк, айдоочу uid) же (None, None)."""
    code, _, tag = (raw or "").strip().upper().partition("-")
    p = by_code(code)
    if not p:
        return None, None
    core.query("UPDATE parks SET scans=COALESCE(scans,0)+1 WHERE id=?", (p["id"],))
    du = driver_by_tag(p["id"], tag) if tag else None
    if du:
        core.query("UPDATE drivers SET qr_scans=COALESCE(qr_scans,0)+1 WHERE uid=?", (du,))
    return p, du


def all_parks():
    return core.query("SELECT * FROM parks ORDER BY id", (), "all")


MONTH = 30.44 * 86400


def share_until(p):
    """Негизги үлүш ушул убакытка чейин (түзүлгөндөн share_months ай), андан кийин share_after."""
    m = p.get("share_months")
    if m is None or int(m) <= 0:
        return None          # мөөнөтсүз
    return (p.get("created_at") or core.now()) + int(m) * MONTH


def share_now(p):
    u = share_until(p)
    if u is not None and core.now() >= u and p.get("share_after") is not None:
        return float(p["share_after"])
    return float(p.get("share") or 0)


def save(name, owner_phone, share=80, ref_bonus=10, promo=None, promo_amount=50, pid=None, active=True,
         share_months=6, share_after=50):
    """Паркты түзөт же өзгөртөт. Ээси телефон менен (сайтка ошол номер менен кирет)."""
    name = (name or "").strip()[:60]
    owner = core.phone_uid(owner_phone)
    try:
        share_months, share_after = int(share_months or 0), float(share_after if share_after is not None else 50)
    except (TypeError, ValueError):
        return None
    if not name or not owner or not (0 <= float(share) <= 100) or not (0 <= float(ref_bonus) <= 1000) \
            or not (0 <= share_months <= 120) or not (0 <= share_after <= 100):
        return None
    promo = norm_code(promo) or None
    if promo:
        other = by_code(promo)
        if other and other["id"] != pid:
            return None
        if not core.save_promo(promo, float(promo_amount or 50), first_only=True):
            return None
    core.ensure_user(owner, "")
    phone = owner[3:]
    if pid and get(pid):
        core.query("UPDATE parks SET name=?, owner_uid=?, phone=?, share=?, ref_bonus=?, promo=?, active=?, "
                   "share_months=?, share_after=? WHERE id=?",
                   (name, owner, phone, float(share), float(ref_bonus), promo, 1 if active else 0,
                    share_months, share_after, pid))
        return pid
    return core.query("INSERT INTO parks (name, owner_uid, phone, share, ref_bonus, promo, active, created_at, "
                      "share_months, share_after) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?)",
                      (name, owner, phone, float(share), float(ref_bonus), promo, core.now(),
                       share_months, share_after), "id")


def attach_driver(phone, pid, by_park=None):
    """Айдоочуну паркка кошот (pid=None — парктан чыгарат).
    Парк ээси өзү кошсо (by_park): айдоочу башка паркта болбошу керек."""
    uid = core.phone_uid(phone) if phone and not str(phone).startswith("ph:") else phone
    d = core.get_driver(uid) if uid else None
    if not d:
        return "no_driver"
    if by_park is not None:
        if pid is not None and d.get("park_id") and d["park_id"] != by_park:
            return "other_park"
        if pid is None and d.get("park_id") != by_park:
            return "not_yours"
    core.set_driver(uid, park_id=pid)
    return "ok"


def set_ref(uid, code):
    """Жүргүнчү парктын коду/QR аркылуу келди. Бир гана жолу жана сапары жок болсо эсептелет.
    Код «КОД-АЙДООЧУ» болсо — QR'ын сканерлеткен айдоочу да белгиленет."""
    code = (code or "").strip().upper()
    p = by_code(code)
    tag = code.partition("-")[2]
    u = core.get_user(uid)
    if not p or not u or u.get("park_ref"):
        return False
    done = core.query("SELECT COUNT(*) AS n FROM rides WHERE passenger=? AND status='completed'", (uid,), "one")["n"]
    if done:
        return False
    du = driver_by_tag(p["id"], tag) if tag else None
    core.set_user(uid, park_ref=p["id"], park_ref_at=core.now(), park_ref_drv=du)
    return True


def qr_stats(pid, driver=None):
    """QR воронкасы: сканерленди → катталды → биринчи сапарын бүтүрдү (бардык убакта)."""
    if driver:
        scans = (core.get_driver(driver) or {}).get("qr_scans") or 0
        rows = core.query("SELECT uid FROM users WHERE park_ref=? AND park_ref_drv=?", (pid, driver), "all")
    else:
        scans = (get(pid) or {}).get("scans") or 0
        rows = core.query("SELECT uid FROM users WHERE park_ref=?", (pid,), "all")
    rides = 0
    for u in rows:
        if core.query("SELECT 1 AS x FROM rides WHERE passenger=? AND status='completed' LIMIT 1", (u["uid"],), "one"):
            rides += 1
    return {"scans": int(scans), "joined": len(rows), "rode": rides}


def _drivers(pid):
    return core.query("SELECT * FROM drivers WHERE park_id=?", (pid,), "all")


def _sum_commission(uids, since, until=None):
    if not uids:
        return 0.0
    qs = ",".join("?" * len(uids))
    r = core.query("SELECT COALESCE(SUM(-amount),0) AS s FROM balance_tx WHERE kind='commission' AND status='done' "
                   "AND at>=? AND at<? AND driver IN (%s)" % qs,
                   (since, until if until is not None else 1e12) + tuple(uids), "one")
    return float(r["s"] or 0)


def _rides(uids, since):
    if not uids:
        return 0, 0
    qs = ",".join("?" * len(uids))
    r = core.query("SELECT COUNT(*) AS n, COALESCE(SUM(price),0) AS s FROM rides WHERE status='completed' "
                   "AND completed_at>=? AND driver IN (%s)" % qs, (since,) + tuple(uids), "one")
    return int(r["n"]), int(r["s"] or 0)


def _refs(pid, since=0):
    """Парк тарткан жүргүнчүлөр: баары жана биринчи сапарын бүтүргөндөрү (бонус)."""
    rows = core.query("SELECT uid, park_ref_at FROM users WHERE park_ref=?", (pid,), "all")
    total, active = 0, 0
    for u in rows:
        if (u["park_ref_at"] or 0) < since:
            continue
        total += 1
        first = core.query("SELECT MIN(completed_at) AS t FROM rides WHERE passenger=? AND status='completed'",
                           (u["uid"],), "one")["t"]
        if first and first <= (u["park_ref_at"] or 0) + REF_DAYS * 86400 and first >= since:
            active += 1
    return total, active


def stats(pid):
    p = get(pid)
    if not p:
        return None
    ds = _drivers(pid)
    uids = [d["uid"] for d in ds]
    per = core.period_starts()
    out = {}
    for k, since in (("today", per["today"]), ("week", per["week"]), ("month", per["month"]), ("all", 0)):
        n, gross = _rides(uids, since)
        until = share_until(p)
        if until is None:
            fee = _sum_commission(uids, since)
            share = round(fee * (p["share"] or 0) / 100.0)
        else:   # мөөнөткө чейинки комиссия — негизги үлүш, кийинкиси — share_after
            f1 = _sum_commission(uids, since, until)
            f2 = _sum_commission(uids, max(since, until))
            fee = f1 + f2
            share = round(f1 * (p["share"] or 0) / 100.0 + f2 * (p["share_after"] or 0) / 100.0)
        refs, refs_active = _refs(pid, since)
        bonus = round(refs_active * (p["ref_bonus"] or 0))
        out[k] = {"rides": n, "gross": gross, "fee": round(fee), "share": share,
                  "refs": refs, "refs_active": refs_active, "bonus": bonus, "earned": share + bonus}
    paid = core.query("SELECT COALESCE(SUM(amount),0) AS s FROM park_payouts WHERE park_id=?", (pid,), "one")["s"] or 0
    # Апталык төлөм: дүйшөмбүгө чейин (өткөн апталарда) тапканы төлөнөт, ушул аптаныкы — кийинки дүйшөмбүдө
    due = max(0, round(out["all"]["earned"] - out["week"]["earned"] - paid))
    return {"periods": out, "paid": round(paid), "balance": round(out["all"]["earned"] - paid),
            "due": due, "this_week": out["week"]["earned"], "next_pay": per["week"] + 7 * 86400,
            "pay_time": pay_time(), "this_monday": per["week"],
            "paid_this_week": core.query("SELECT MAX(at) AS t FROM park_payouts WHERE park_id=? AND at>=?",
                                         (pid, per["week"]), "one")["t"],
            "drivers_total": len(ds), "drivers_online": sum(1 for d in ds if d.get("online"))}


def driver_rows(pid):
    per = core.period_starts()
    rows = []
    for d in _drivers(pid):
        u = core.get_user(d["uid"]) or {}
        n, gross = _rides([d["uid"]], per["week"])
        t, _ = _rides([d["uid"]], per["today"])
        rows.append({"uid": d["uid"], "name": u.get("name") or "", "phone": u.get("phone") or "",
                     "car": core.car_text(d.get("car_color"), d.get("car_model")), "plate": d.get("car_plate") or "",
                     "status": d.get("status"), "online": bool(d.get("online")), "busy": bool(d.get("busy_ride")),
                     "rating": d.get("rating"), "activity": d.get("activity") if d.get("activity") is not None else 100,
                     "balance": round(d.get("balance") or 0), "today": t, "week_rides": n, "week_gross": gross})
    rows.sort(key=lambda r: (not r["online"], -r["week_rides"]))
    return rows


def payouts(pid):
    return core.query("SELECT amount, note, at FROM park_payouts WHERE park_id=? ORDER BY at DESC LIMIT 30", (pid,), "all")


def week_label(at=None):
    """Өткөн аптанын аралыгы: «03.11–09.11»."""
    ws = core.period_starts()["week"] if at is None else at
    a, b = ws - 7 * 86400 + core.TZ, ws - 86400 + core.TZ
    return time.strftime("%d.%m", time.gmtime(a)) + "–" + time.strftime("%d.%m", time.gmtime(b))


def add_payout(pid, amount, note=""):
    if not get(pid) or not (0 < float(amount) <= 10_000_000):
        return False
    core.query("INSERT INTO park_payouts (park_id, amount, note, at) VALUES (?, ?, ?, ?)",
               (pid, float(amount), (note or "")[:120], core.now()))
    return True


def pay_time():
    """Төлөм убактысы (Бишкек убактысы): {"from": "10:00", "to": "18:00"}."""
    t = core.get_setting("park_pay_time") or {}
    return {"from": t.get("from") or "10:00", "to": t.get("to") or "18:00"}


def set_pay_time(a, b):
    import re
    ok = lambda x: bool(re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", x or ""))
    if not (ok(a) and ok(b)) or a >= b:
        return False
    core.set_setting("park_pay_time", {"from": a, "to": b})
    return True


def _hm(s):
    h, m = s.split(":")
    return int(h) * 3600 + int(m) * 60


def weekly_reminder():
    """Дүйшөмбү күнү бир жолу: төлөнө турган парктардын тизмеси (админге)."""
    per = core.period_starts()
    since = core.now() - per["week"]
    if since < _hm(pay_time()["from"]) or since > 2 * 86400:   # дүйшөмбү, төлөм саатынан баштап
        return []
    key = str(int(per["week"]))
    if core.get_setting("park_pay_week") == key:
        return []
    core.set_setting("park_pay_week", key)
    rows = []
    for p in all_parks():
        if not p["active"]:
            continue
        d = stats(p["id"])["due"]
        if d > 0:
            rows.append((p["name"], d))
    return rows


def state(pid):
    p = ensure_code(get(pid))
    if not p:
        return None
    promo = core.query("SELECT amount FROM promos WHERE code=? AND active=1", (p["promo"],), "one") if p.get("promo") else None
    return {"park": dict({k: p[k] for k in ("id", "name", "phone", "share", "ref_bonus", "promo", "code",
                                            "share_months", "share_after")},
                         promo_amount=int(promo["amount"]) if promo else 0,
                         share_until=share_until(p), share_now=share_now(p)),
            "qr": qr_stats(pid), "area": core.area_label(),
            "stats": stats(pid), "drivers": driver_rows(pid), "payouts": payouts(pid),
            "commission_pct": core.commission_pct()}


def admin_list():
    out = []
    for p in all_parks():
        s = stats(p["id"])
        out.append({"id": p["id"], "name": p["name"], "phone": p["phone"], "share": p["share"],
                    "share_months": p.get("share_months"), "share_after": p.get("share_after"),
                    "share_until": share_until(p), "share_now": share_now(p),
                    "ref_bonus": p["ref_bonus"], "promo": p["promo"], "active": bool(p["active"]),
                    "drivers": s["drivers_total"], "online": s["drivers_online"],
                    "month": s["periods"]["month"], "balance": s["balance"], "paid": s["paid"],
                    "due": s["due"], "this_week": s["this_week"], "week": week_label()})
    return out


def park_name_of_driver(uid):
    d = core.get_driver(uid) or {}
    p = get(d.get("park_id"))
    return p["name"] if p and p["active"] else None
