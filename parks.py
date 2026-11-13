"""Таксопарктар: парк өз айдоочуларын жана жүргүнчүлөрүн алып келет, комиссиядан үлүш алат.

Парктын кирешеси:
  • парктын айдоочулары төлөгөн комиссиянын share %ы;
  • парк тарткан (промокод/QR) ар бир жаңы жүргүнчүнүн биринчи бүткөн сапары үчүн ref_bonus сом.
Админ төлөп бергенин park_payouts'ка жазат → калдык = тапкан − төлөнгөн.
"""
import core

REF_DAYS = 30          # жүргүнчү ушул мөөнөттө парктын коду менен биринчи сапарын бүтүрсө — бонус


def norm_code(c):
    return core.promo_norm(c or "")


def get(pid):
    return core.query("SELECT * FROM parks WHERE id=?", (pid,), "one") if pid else None


def by_owner(uid):
    return core.query("SELECT * FROM parks WHERE owner_uid=? AND active=1", (uid,), "one") if uid else None


def by_code(code):
    code = norm_code(code)
    return core.query("SELECT * FROM parks WHERE promo=? AND active=1", (code,), "one") if code else None


def all_parks():
    return core.query("SELECT * FROM parks ORDER BY id", (), "all")


def save(name, owner_phone, share=30, ref_bonus=20, promo=None, promo_amount=50, pid=None, active=True):
    """Паркты түзөт же өзгөртөт. Ээси телефон менен (сайтка ошол номер менен кирет)."""
    name = (name or "").strip()[:60]
    owner = core.phone_uid(owner_phone)
    if not name or not owner or not (0 <= float(share) <= 100) or not (0 <= float(ref_bonus) <= 1000):
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
        core.query("UPDATE parks SET name=?, owner_uid=?, phone=?, share=?, ref_bonus=?, promo=?, active=? WHERE id=?",
                   (name, owner, phone, float(share), float(ref_bonus), promo, 1 if active else 0, pid))
        return pid
    return core.query("INSERT INTO parks (name, owner_uid, phone, share, ref_bonus, promo, active, created_at) "
                      "VALUES (?, ?, ?, ?, ?, ?, 1, ?)",
                      (name, owner, phone, float(share), float(ref_bonus), promo, core.now()), "id")


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
    """Жүргүнчү парктын коду/QR аркылуу келди. Бир гана жолу жана сапары жок болсо эсептелет."""
    p = by_code(code)
    u = core.get_user(uid)
    if not p or not u or u.get("park_ref"):
        return False
    done = core.query("SELECT COUNT(*) AS n FROM rides WHERE passenger=? AND status='completed'", (uid,), "one")["n"]
    if done:
        return False
    core.set_user(uid, park_ref=p["id"], park_ref_at=core.now())
    return True


def _drivers(pid):
    return core.query("SELECT * FROM drivers WHERE park_id=?", (pid,), "all")


def _sum_commission(uids, since):
    if not uids:
        return 0.0
    qs = ",".join("?" * len(uids))
    r = core.query("SELECT COALESCE(SUM(-amount),0) AS s FROM balance_tx WHERE kind='commission' AND status='done' "
                   "AND at>=? AND driver IN (%s)" % qs, (since,) + tuple(uids), "one")
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
        fee = _sum_commission(uids, since)
        refs, refs_active = _refs(pid, since)
        share = round(fee * (p["share"] or 0) / 100.0)
        bonus = round(refs_active * (p["ref_bonus"] or 0))
        out[k] = {"rides": n, "gross": gross, "fee": round(fee), "share": share,
                  "refs": refs, "refs_active": refs_active, "bonus": bonus, "earned": share + bonus}
    paid = core.query("SELECT COALESCE(SUM(amount),0) AS s FROM park_payouts WHERE park_id=?", (pid,), "one")["s"] or 0
    return {"periods": out, "paid": round(paid), "balance": round(out["all"]["earned"] - paid),
            "drivers_total": len(ds), "drivers_online": sum(1 for d in ds if d.get("online"))}


def driver_rows(pid):
    per = core.period_starts()
    rows = []
    for d in _drivers(pid):
        u = core.get_user(d["uid"]) or {}
        n, gross = _rides([d["uid"]], per["week"])
        t, _ = _rides([d["uid"]], per["today"])
        rows.append({"uid": d["uid"], "name": u.get("name") or "", "phone": u.get("phone") or "",
                     "car": "%s %s" % (d.get("car_color") or "", d.get("car_model") or ""), "plate": d.get("car_plate") or "",
                     "status": d.get("status"), "online": bool(d.get("online")), "busy": bool(d.get("busy_ride")),
                     "rating": d.get("rating"), "activity": d.get("activity") if d.get("activity") is not None else 100,
                     "balance": round(d.get("balance") or 0), "today": t, "week_rides": n, "week_gross": gross})
    rows.sort(key=lambda r: (not r["online"], -r["week_rides"]))
    return rows


def payouts(pid):
    return core.query("SELECT amount, note, at FROM park_payouts WHERE park_id=? ORDER BY at DESC LIMIT 30", (pid,), "all")


def add_payout(pid, amount, note=""):
    if not get(pid) or not (0 < float(amount) <= 10_000_000):
        return False
    core.query("INSERT INTO park_payouts (park_id, amount, note, at) VALUES (?, ?, ?, ?)",
               (pid, float(amount), (note or "")[:120], core.now()))
    return True


def state(pid):
    p = get(pid)
    if not p:
        return None
    return {"park": {k: p[k] for k in ("id", "name", "phone", "share", "ref_bonus", "promo")},
            "stats": stats(pid), "drivers": driver_rows(pid), "payouts": payouts(pid),
            "commission_pct": core.commission_pct()}


def admin_list():
    out = []
    for p in all_parks():
        s = stats(p["id"])
        out.append({"id": p["id"], "name": p["name"], "phone": p["phone"], "share": p["share"],
                    "ref_bonus": p["ref_bonus"], "promo": p["promo"], "active": bool(p["active"]),
                    "drivers": s["drivers_total"], "online": s["drivers_online"],
                    "month": s["periods"]["month"], "balance": s["balance"], "paid": s["paid"]})
    return out


def park_name_of_driver(uid):
    d = core.get_driver(uid) or {}
    p = get(d.get("park_id"))
    return p["name"] if p and p["active"] else None
