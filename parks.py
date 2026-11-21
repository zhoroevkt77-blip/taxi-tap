"""Таксопарктар: парк өз айдоочуларын жана жүргүнчүлөрүн алып келет, комиссиядан үлүш алат.

Парктын кирешеси:
  • парктын айдоочулары төлөгөн комиссиянын share %ы;
  • парк тарткан (промокод/QR) ар бир жаңы жүргүнчүнүн биринчи бүткөн сапары үчүн ref_bonus сом.
Админ төлөп бергенин park_payouts'ка жазат → калдык = тапкан − төлөнгөн.
"""
import calendar
import json
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


def _sum_commission(uids, since, until=None, kind="commission"):
    if not uids:
        return 0.0
    qs = ",".join("?" * len(uids))
    r = core.query("SELECT COALESCE(SUM(-amount),0) AS s FROM balance_tx WHERE kind=? AND status='done' "
                   "AND at>=? AND at<? AND driver IN (%s)" % qs,
                   (kind, since, until if until is not None else 1e12) + tuple(uids), "one")
    return float(r["s"] or 0)


def _rides(uids, since, until=None):
    if not uids:
        return 0, 0
    qs = ",".join("?" * len(uids))
    r = core.query("SELECT COUNT(*) AS n, COALESCE(SUM(price),0) AS s FROM rides WHERE status='completed' "
                   "AND completed_at>=? AND completed_at<? AND driver IN (%s)" % qs,
                   (since, until if until is not None else 1e12) + tuple(uids), "one")
    return int(r["n"]), int(r["s"] or 0)


def _refs(pid, since=0, until=None):
    """Парк тарткан жүргүнчүлөр: баары жана биринчи сапарын бүтүргөндөрү (бонус)."""
    rows = core.query("SELECT uid, park_ref_at FROM users WHERE park_ref=?", (pid,), "all")
    end = until if until is not None else 1e12
    total, active = 0, 0
    for u in rows:
        ra = u["park_ref_at"] or 0
        if since <= ra < end:
            total += 1
        first = core.query("SELECT MIN(completed_at) AS t FROM rides WHERE passenger=? AND status='completed'",
                           (u["uid"],), "one")["t"]
        if first and first <= ra + REF_DAYS * 86400 and since <= first < end:
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


# ==================== Айлык акт салыштыруу ====================
ACT_ANSWER_DAYS = 10


def month_bounds(period):
    """«2026-10» → (башы, аягы) Бишкек убактысы менен, unix."""
    y, m = int(period[:4]), int(period[5:7])
    a = calendar.timegm((y, m, 1, 0, 0, 0)) - core.TZ
    y2, m2 = (y + 1, 1) if m == 12 else (y, m + 1)
    return a, calendar.timegm((y2, m2, 1, 0, 0, 0)) - core.TZ


def prev_period(at=None):
    lt = time.gmtime((at if at is not None else core.now()) + core.TZ)
    y, m = (lt.tm_year - 1, 12) if lt.tm_mon == 1 else (lt.tm_year, lt.tm_mon - 1)
    return "%04d-%02d" % (y, m)


def _earned(p, uids, a, b):
    """[a, b) аралыгында паркка тиешелүү: үлүш (мөөнөткө бөлүнүп) + бонус."""
    n, gross = _rides(uids, a, b)
    until = share_until(p)
    s1, s2 = float(p["share"] or 0), float(p.get("share_after") if p.get("share_after") is not None else p["share"] or 0)
    if until is None:
        f1, f2 = _sum_commission(uids, a, b), 0.0
    else:
        f1 = _sum_commission(uids, a, min(b, until)) if a < until else 0.0
        f2 = _sum_commission(uids, max(a, until), b) if b > until else 0.0
    share = round(f1 * s1 / 100.0 + f2 * s2 / 100.0)
    _, active = _refs(p["id"], a, b)
    bonus = round(active * float(p["ref_bonus"] or 0))
    parts = [x for x in (({"rate": s1, "fee": round(f1)} if f1 or until is None or a < until else None),
                         ({"rate": s2, "fee": round(f2)} if f2 or (until is not None and b > until) else None)) if x]
    return {"rides": n, "gross": gross, "fee": round(f1 + f2), "share": share, "parts": parts,
            "bonus_n": active, "bonus_rate": float(p["ref_bonus"] or 0), "bonus": bonus, "due": share + bonus}


def _paid(pid, a, b):
    return core.query("SELECT amount, note, at FROM park_payouts WHERE park_id=? AND at>=? AND at<? ORDER BY at",
                      (pid, a, b), "all")


def act_compute(pid, period):
    p = get(pid)
    a, b = month_bounds(period)
    uids = [d["uid"] for d in _drivers(pid)]
    before = _earned(p, uids, 0, a)["due"] - sum(x["amount"] for x in _paid(pid, 0, a))
    m = _earned(p, uids, a, b)
    pays = _paid(pid, a, b)
    paid = round(sum(x["amount"] for x in pays))
    drivers = []
    for d in _drivers(pid):
        n, g = _rides([d["uid"]], a, b)
        if n:
            u = core.get_user(d["uid"]) or {}
            drivers.append({"name": u.get("name") or "", "plate": d.get("car_plate") or "", "rides": n, "gross": g,
                            "fee": round(_sum_commission([d["uid"]], a, b))})
    drivers.sort(key=lambda x: -x["gross"])
    return dict(m, period=period, park=p["name"], park_phone=p.get("phone") or "", opening=round(before),
                payouts=[{"amount": round(x["amount"]), "note": x["note"] or "", "at": x["at"]} for x in pays],
                paid=paid, closing=round(before) + m["due"] - paid, drivers=drivers, made_at=core.now())


def act_get(aid):
    r = core.query("SELECT * FROM park_acts WHERE id=?", (aid,), "one")
    if r:
        r["data"] = json.loads(r["data"] or "{}")
    return r


def acts(pid=None, limit=24):
    q = "SELECT a.*, p.name AS park FROM park_acts a LEFT JOIN parks p ON p.id=a.park_id"
    rows = core.query(q + (" WHERE a.park_id=?" if pid else "") + " ORDER BY a.period DESC, a.id DESC LIMIT ?",
                      ((pid, limit) if pid else (limit,)), "all")
    for r in rows:
        r["data"] = json.loads(r["data"] or "{}")
    return rows


def act_make(pid, period, force=False):
    """Акт түзөт (же ырастала элек болсо кайра эсептейт). Кайтарат: (act_id, жаңыбы)."""
    old = core.query("SELECT id, status FROM park_acts WHERE park_id=? AND period=?", (pid, period), "one")
    if old and (not force or old["status"] == "ok"):
        return old["id"], False
    data = json.dumps(act_compute(pid, period), ensure_ascii=False)
    if old:
        core.query("UPDATE park_acts SET data=?, status='sent', comment=NULL, answered_at=NULL, reminded=0, created_at=? "
                   "WHERE id=?", (data, core.now(), old["id"]))
        return old["id"], True
    return core.query("INSERT INTO park_acts (park_id, period, data, status, created_at) VALUES (?, ?, ?, 'sent', ?)",
                      (pid, period, data, core.now()), "id"), True


def act_answer(pid, aid, ok, comment=""):
    a = act_get(aid)
    if not a or a["park_id"] != pid or a["status"] == "ok":
        return False
    core.query("UPDATE park_acts SET status=?, comment=?, answered_at=? WHERE id=?",
               ("ok" if ok else "dispute", None if ok else (comment or "")[:500], core.now(), aid))
    return True


def monthly_acts():
    """Айдын 1-күнү 09:00дөн тартып: мурунку ай үчүн акттар. Кайтарат: [(park, act_id)]."""
    lt = time.gmtime(core.now() + core.TZ)
    if lt.tm_mday != 1 or lt.tm_hour < 9:
        return []
    period = prev_period()
    if core.get_setting("park_act_month") == period:
        return []
    core.set_setting("park_act_month", period)
    _, end = month_bounds(period)
    out = []
    for p in all_parks():
        if p["active"] and (p["created_at"] or 0) < end:
            aid, new = act_make(p["id"], period)
            if new:
                out.append((p, aid))
    return out


def acts_late():
    """Жооп бербеген акттар (10 күндөн ашык) — бир жолу эскертүү."""
    rows = core.query("SELECT a.id, a.park_id, a.period FROM park_acts a WHERE a.status='sent' AND a.reminded=0 "
                      "AND a.created_at<?", (core.now() - ACT_ANSWER_DAYS * 86400,), "all")
    for r in rows:
        core.query("UPDATE park_acts SET reminded=1 WHERE id=?", (r["id"],))
    return rows


MONTHS = ["январь", "февраль", "март", "апрель", "май", "июнь", "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь"]


def period_label(period):
    return "%s %s" % (MONTHS[int(period[5:7]) - 1].capitalize(), period[:4])


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


# ==================== Айдоочулардын статистикасы жана картасы ====================
PERIODS = ("today", "week", "month", "all")


def _since(period):
    return 0 if period == "all" else core.period_starts()[period]


def _offers(uid, since):
    rows = core.query("SELECT result, COUNT(*) AS n FROM offer_log WHERE driver=? AND at>=? GROUP BY result", (uid, since), "all")
    o = {r["result"]: int(r["n"]) for r in rows}
    return o.get("accept", 0), o.get("accept", 0) + o.get("miss", 0)


def _dcancels(uid, since):
    return int(core.query("SELECT COUNT(*) AS n FROM ride_events WHERE actor=? AND status LIKE ? AND status<>'drv_cancel:noshow' "
                          "AND at>=?", (uid, "drv_cancel:" + chr(37), since), "one")["n"])


def driver_stats(pid, period="week"):
    p = get(pid)
    if period not in PERIODS:
        period = "week"
    since = _since(period)
    rate = float(share_now(p) or 0) / 100.0
    rows = []
    t = core.now()
    for d in _drivers(pid):
        u = core.get_user(d["uid"]) or {}
        n, gross = _rides([d["uid"]], since)
        acc, tot = _offers(d["uid"], since)
        fee = _sum_commission([d["uid"]], since)
        last = core.query("SELECT MAX(completed_at) AS t FROM rides WHERE driver=? AND status='completed'", (d["uid"],), "one")["t"]
        seen = max(last or 0, d.get("loc_at") or 0)
        rows.append({"uid": d["uid"], "name": u.get("name") or "", "phone": u.get("phone") or "", "plate": d.get("car_plate") or "",
                     "car": core.car_text(d.get("car_color"), d.get("car_model")),
                     "online": bool(d.get("online")), "busy": bool(d.get("busy_ride")),
                     "rides": n, "gross": round(gross), "online_sec": round(core.online_sec(d["uid"], since)),
                     "accepted": acc, "offers": tot, "cancels": _dcancels(d["uid"], since), "share": round(fee * rate),
                     "fee": round(fee), "tax": round(_sum_commission([d["uid"]], since, kind="tax")),
                     "ins": round(_sum_commission([d["uid"]], since, kind="ins")),
                     "rating": d.get("rating"), "activity": d.get("activity") if d.get("activity") is not None else 100,
                     "idle_days": int((t - seen) // 86400) if seen else None, "diag": core.diag_brief(d, u)})
    rows.sort(key=lambda r: (-r["gross"], -r["rides"]))
    if rows and rows[0]["gross"] > 0:
        rows[0]["best"] = True
    return {"period": period, "rows": rows,
            "total": {"rides": sum(r["rides"] for r in rows), "gross": sum(r["gross"] for r in rows),
                      "share": sum(r["share"] for r in rows), "online_sec": sum(r["online_sec"] for r in rows)}}


def driver_detail(pid, uid):
    d = core.get_driver(uid)
    if not d or d.get("park_id") != pid:
        return None
    t = core.period_starts()["today"]
    days = []
    for i in range(6, -1, -1):
        a = t - i * 86400
        n, g = _rides([uid], a, a + 86400)
        days.append({"day": time.strftime("%d.%m", time.gmtime(a + core.TZ)), "wd": time.gmtime(a + core.TZ).tm_wday,
                     "rides": n, "gross": round(g)})
    rec = core.query("SELECT completed_at AS at, p_addr, d_addr, price FROM rides WHERE driver=? AND status='completed' "
                     "ORDER BY completed_at DESC LIMIT 10", (uid,), "all")
    u = core.get_user(uid) or {}
    praise = []
    try:
        praise = [{"t": a, "n": b} for a, b in core.driver_praise(uid)["good"][:5]]
    except Exception:
        pass
    return {"uid": uid, "name": u.get("name") or "", "phone": u.get("phone") or "", "plate": d.get("car_plate") or "", "status": d.get("status"),
            "diag": core.diag_brief(d, u),
            "car": core.car_text(d.get("car_color"), d.get("car_model")), "rating": d.get("rating"),
            "activity": d.get("activity") if d.get("activity") is not None else 100, "days": days,
            "recent": [{"at": r["at"], "from": r["p_addr"] or "", "to": r["d_addr"] or "", "price": round(r["price"] or 0)} for r in rec],
            "praise": praise}


def map_state(pid):
    """Парктын айдоочулары картада. Жүргүнчүнүн аты/телефону жок; эс алуудагынын жери болжолдуу (~1 км)."""
    t = core.now()
    today = core.period_starts()["today"]
    out = []
    for d in _drivers(pid):
        if d.get("lat") is None:
            continue
        u = core.get_user(d["uid"]) or {}
        live = bool(d.get("online")) and ((d.get("live_until") or 0) > t or t - (d.get("loc_at") or 0) < core.LOC_TTL_SEC)
        st = "busy" if live and d.get("busy_ride") else "free" if live else "off"
        lat, lon = (d["lat"], d["lon"]) if st != "off" else (round(d["lat"], 2), round(d["lon"], 2))
        trip = None
        if st == "busy":
            r = core.get_ride(d["busy_ride"]) or {}
            short = lambda s: (s or "").split(",")[0][:40]    # noqa: E731
            trip = {"status": r.get("status"), "from": short(r.get("p_addr")), "to": short(r.get("d_addr"))}
        n, g = _rides([d["uid"]], today)
        out.append({"uid": d["uid"], "name": u.get("name") or "", "phone": u.get("phone") or "", "plate": d.get("car_plate") or "",
                    "car": core.car_text(d.get("car_color"), d.get("car_model")), "lat": lat, "lon": lon, "st": st,
                    "seen": d.get("loc_at"), "trip": trip, "today": n, "today_gross": round(g)})
    return {"drivers": out, "now": t,
            "count": {k: sum(1 for x in out if x["st"] == k) for k in ("free", "busy", "off")}}


def stats_csv(pid, period):
    s = driver_stats(pid, period)
    lines = ["Айдоочу;Телефон;Номер;Сапар;Жалпы иштеген;Комиссия;Киреше салыгы;Камсыздандыруу төгүмү;Таза киреше;"
             "Линияда (саат);Алган заказ;Сунуш;Жокко чыгаруу;Паркка тиешелүү"]
    for r in s["rows"]:
        clean = r["gross"] - r.get("fee", 0) - r.get("tax", 0) - r.get("ins", 0)
        lines.append(";".join(str(x) for x in (r["name"], r["phone"], r["plate"], r["rides"], r["gross"],
                                                r.get("fee", 0), r.get("tax", 0), r.get("ins", 0), clean,
                                                round(r["online_sec"] / 3600.0, 1), r["accepted"], r["offers"], r["cancels"], r["share"])))
    return "\ufeff" + "\n".join(lines) + "\n"


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
            "acts": [dict(a, label=period_label(a["period"])) for a in acts(pid, 12)],
            "commission_pct": core.commission_pct(),
            "self_approve": bool(p.get("self_approve")), "apps": applications(pid)}


def admin_list():
    out = []
    for p in all_parks():
        s = stats(p["id"])
        out.append({"id": p["id"], "name": p["name"], "phone": p["phone"], "share": p["share"],
                    "share_months": p.get("share_months"), "share_after": p.get("share_after"),
                    "share_until": share_until(p), "share_now": share_now(p),
                    "ref_bonus": p["ref_bonus"], "promo": p["promo"], "active": bool(p["active"]),
                    "self_approve": bool(p.get("self_approve")), "pending": len(applications(p["id"])["pending"]),
                    "drivers": s["drivers_total"], "online": s["drivers_online"],
                    "month": s["periods"]["month"], "balance": s["balance"], "paid": s["paid"],
                    "due": s["due"], "this_week": s["this_week"], "week": week_label()})
    return out


def park_name_of_driver(uid):
    d = core.get_driver(uid) or {}
    p = get(d.get("park_id"))
    return p["name"] if p and p["active"] else None


# ==================== Парк өз айдоочуларын тастыктайт ====================
def set_self_approve(pid, on):
    if not get(pid):
        return False
    core.query("UPDATE parks SET self_approve=? WHERE id=?", (1 if on else 0, pid))
    return True


DOC_KEYS = ("doc_selfie", "doc_license", "doc_techpass", "doc_car")


def applications(pid):
    """Парктын айдоочулары: арыз берген, бөгөттөлгөн жана фотоконтролу текшерүүнү күткөндөр."""
    out = {"pending": [], "blocked": [], "photos": []}
    for d in _drivers(pid):
        u = core.get_user(d["uid"]) or {}
        row = {"uid": d["uid"], "name": u.get("name") or "", "phone": u.get("phone") or "",
               "car": core.car_text(d.get("car_color"), d.get("car_model")), "plate": d.get("car_plate") or "",
               "lic_until": d.get("lic_until") or "", "at": d.get("created_at"),
               "docs": [k for k in DOC_KEYS if d.get(k)], "blocked_by": d.get("blocked_by") or "",
               "reject_note": d.get("reject_note") or ""}
        if d.get("status") == "pending":
            out["pending"].append(row)
        elif d.get("status") == "blocked":
            row["can_unblock"] = (d.get("blocked_by") or "") == "park:%d" % pid
            out["blocked"].append(row)
        if d.get("status") == "active" and d.get("photo_status") == "pending" and d.get("photos"):
            try:
                ph = json.loads(d["photos"]) or {}
            except ValueError:
                ph = {}
            out["photos"].append(dict(row, sides=[k for k in ("front", "back", "left", "right") if ph.get(k)]))
    out["pending"].sort(key=lambda r: -(r["at"] or 0))
    return out


def driver_file(pid, uid, key):
    """Парк ээси өз айдоочусунун документин гана көрө алат."""
    d = core.get_driver(uid)
    if not d or d.get("park_id") != pid:
        return None
    if key in DOC_KEYS:
        return d.get(key)
    if key.startswith("photo_"):
        try:
            return (json.loads(d.get("photos") or "{}") or {}).get(key[6:])
        except ValueError:
            return None
    return None


def driver_action(pid, uid, action, reason=""):
    """Парк ээсинин аракети. Тастыктоо/четке кагуу — админ уруксат берсе гана."""
    p = get(pid)
    d = core.get_driver(uid)
    if not p or not d or d.get("park_id") != pid:
        return "not_yours", []
    me = "park:%d" % pid
    st = d.get("status")
    if action in ("approve", "reject"):
        if not p.get("self_approve"):
            return "no_right", []
        if st != "pending":
            return "bad_status", []
        if action == "reject" and not (reason or "").strip():
            return "reason", []
        import flow
        return "ok", flow.admin_driver(uid, action, (reason or "").strip()[:200], by=me)
    if action == "block":
        if st != "active":
            return "bad_status", []
        import flow
        return "ok", flow.admin_driver(uid, "block", by=me)
    if action == "unblock":
        if st != "blocked" or (d.get("blocked_by") or "") != me:
            return "no_right", []
        import flow
        return "ok", flow.admin_driver(uid, "unblock", by=me)
    if action in ("photo_ok", "photo_no"):
        if not p.get("self_approve"):
            return "no_right", []
        ok = core.review_car_photos(uid, action == "photo_ok", reason or "")
        if not ok:
            return "bad_status", []
        import flow
        return "ok", [flow.note(uid, "d_car_photo_ok" if action == "photo_ok" else "d_car_photo_bad", "/driver", note=reason or "—")]
    return "bad", []
