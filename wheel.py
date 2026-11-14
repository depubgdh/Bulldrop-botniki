"""G‘ildirak (demo). Faqat virtual coin: pul yechib bo‘lmaydi, pul kiritib bo‘lmaydi.

G‘ildirak SERVERDA to‘xtovsiz aylanadi: har 18 soniyada bitta raund — 11 soniya tikish, 7 soniya aylanish.
Hech kim o‘ynamasa ham raundlar davom etadi. Har raundning natijasi serverda tanlanadi va bazaga yoziladi.
Tikish: 1x / 2x / 5x / 10x dan birini tanlaysiz; g‘ildirak shu sektorga tushsa, qaytim = tikish + tikish × koeffitsiyent.
Foydalanuvchi internetni o‘chirsa ham tikish va yutuq yo‘qolmaydi: raund tugagach yutuq avtomatik hisoblanadi."""
import json
import random
import re
import time
from datetime import datetime, timedelta, timezone

import db

MIN_BET = 1
MAX_BET = 1000
AUTO_OPTIONS = (1, 5, 10, 25)
CYCLE = 18          # soniya: bitta raund
SPIN = 7            # soniya: aylanish
BET_WINDOW = CYCLE - SPIN   # soniya: tikish ochiq
HISTORY = 14
DAILY_TZ = timezone(timedelta(hours=5))  # Toshkent vaqti: kun 00:00 da yangilanadi
REQUEST_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")

# Sektor turlari: kalit -> (yorliq, koeffitsiyent). Qaytim = tikish + tikish * koeffitsiyent.
SECTOR_TYPES = {
    "x1": ("1x", 1),
    "x2": ("2x", 2),
    "x5": ("5x", 5),
    "x10": ("10x", 10),
}
# 40 ta sektor: 1x — 19, 2x — 13, 5x — 6, 10x — 2. Tushish ehtimoli = sektorlar ulushi.
# Taxminiy qaytim: 1x ≈ 95%, 2x ≈ 97%, 5x ≈ 90%, 10x ≈ 55%.
_BASE = ["x1"] * 19 + ["x2"] * 13 + ["x5"] * 6 + ["x10"] * 2
SECTORS = _BASE[:]
random.Random(11).shuffle(SECTORS)  # doimiy tartib: g‘ildirak har safar bir xil ko‘rinadi
SEG_DEG = 360.0 / len(SECTORS)

# Testlar vaqtni almashtirishi uchun
now_fn = time.time


class WheelError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def locked_types() -> set:
    try:
        return {t for t in json.loads(db.get_setting("wheel_locked") or "[]") if t in SECTOR_TYPES}
    except (TypeError, ValueError):
        return set()


def set_locked_types(types) -> None:
    types = sorted(t for t in types if t in SECTOR_TYPES)
    db.set_setting("wheel_locked", json.dumps(types) if types else None)


def daily_amount() -> int:
    try:
        return max(0, int(db.get_setting("wheel_daily") or 0))
    except (TypeError, ValueError):
        return 0


def set_daily_amount(amount: int) -> None:
    db.set_setting("wheel_daily", str(max(0, int(amount))) if amount > 0 else None)


_SCHEMA_OK = False


def _ensure_schema() -> None:
    """Eski bazada (db.py yangilanmagan bo'lsa ham) kerakli jadval/ustunlar bo'lishini ta'minlaydi."""
    global _SCHEMA_OK
    if _SCHEMA_OK:
        return
    with db.connect() as con:
        cols = [r["name"] for r in con.execute("PRAGMA table_info(users)")]
        if cols:
            for name, ddl in (("coins", "INTEGER NOT NULL DEFAULT 0"), ("opens", "INTEGER NOT NULL DEFAULT 0"),
                              ("last_daily", "TEXT")):
                if name not in cols:
                    con.execute(f"ALTER TABLE users ADD COLUMN {name} {ddl}")
        con.execute("""CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)""")
        con.execute("""
            CREATE TABLE IF NOT EXISTS wheel_rounds (
                round INTEGER PRIMARY KEY,
                seg INTEGER NOT NULL,
                kind TEXT NOT NULL,
                jitter REAL NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS wheel_bets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id TEXT NOT NULL UNIQUE,
                round INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                kind TEXT NOT NULL,
                amount INTEGER NOT NULL,
                payout INTEGER NOT NULL DEFAULT 0,
                settled INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        con.execute("CREATE INDEX IF NOT EXISTS idx_wbets_user ON wheel_bets(user_id, id)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_wbets_round ON wheel_bets(round, settled)")
    _SCHEMA_OK = True


def _today() -> str:
    return datetime.now(DAILY_TZ).date().isoformat()


# ------------------------------------------------------------------ raundlar

def _clock():
    t = now_fn()
    r = int(t // CYCLE)
    elapsed = t - r * CYCLE
    return t, r, elapsed


def rest_deg(row) -> float:
    """Raund tugagach g‘ildirakning to‘xtash burchagi (daraja, 0..360): tanlangan sektor ko‘rsatkich ostida."""
    center = row["seg"] * SEG_DEG + SEG_DEG / 2
    return (-center + row["jitter"] * SEG_DEG) % 360.0


def _ensure_round(con, r: int):
    row = con.execute("SELECT * FROM wheel_rounds WHERE round=?", (r,)).fetchone()
    if row:
        return row
    locked = locked_types()
    kinds = [k for k in SECTOR_TYPES if k not in locked] or list(SECTOR_TYPES)
    pool = [i for i, k in enumerate(SECTORS) if k in kinds]
    seg = random.SystemRandom().choice(pool)
    jitter = random.SystemRandom().uniform(-0.36, 0.36)
    con.execute("INSERT OR IGNORE INTO wheel_rounds(round, seg, kind, jitter) VALUES (?, ?, ?, ?)",
                (r, seg, SECTORS[seg], jitter))
    return con.execute("SELECT * FROM wheel_rounds WHERE round=?", (r,)).fetchone()


def _settle(con, user_id=None) -> int:
    """Tugagan raundlar bo‘yicha tikishlarni hisoblaydi va yutuqni qaytaradi. Chaqiruvchi tranzaksiyani boshqaradi."""
    _, current, _ = _clock()
    if user_id is None:
        rows = con.execute("SELECT * FROM wheel_bets WHERE settled=0 AND round<?", (current,)).fetchall()
    else:
        rows = con.execute("SELECT * FROM wheel_bets WHERE settled=0 AND round<? AND user_id=?",
                           (current, user_id)).fetchall()
    for bet in rows:
        rnd = _ensure_round(con, bet["round"])
        payout = 0
        if rnd["kind"] == bet["kind"]:
            payout = bet["amount"] + bet["amount"] * SECTOR_TYPES[bet["kind"]][1]
        con.execute("UPDATE wheel_bets SET payout=?, settled=1 WHERE id=?", (payout, bet["id"]))
        if payout:
            con.execute("UPDATE users SET coins = coins + ? WHERE user_id=?", (payout, bet["user_id"]))
    return len(rows)


def settle(user_id=None) -> int:
    _ensure_schema()
    con = db.connect()
    try:
        con.execute("BEGIN IMMEDIATE")
        n = _settle(con, user_id)
        con.commit()
        return n
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


_ticks = 0


def tick() -> None:
    """Fon vazifasi: hech kim kirmasa ham raund natijasi yoziladi va tikishlar hisoblanadi."""
    global _ticks
    _ensure_schema()
    _, r, elapsed = _clock()
    con = db.connect()
    try:
        con.execute("BEGIN IMMEDIATE")
        if elapsed >= BET_WINDOW:
            _ensure_round(con, r)
        _settle(con, None)
        _ticks += 1
        if _ticks % 900 == 1:  # ~har 30 daqiqada eski raundlarni tozalash (baza o‘smasligi uchun)
            con.execute("DELETE FROM wheel_rounds WHERE round < ? AND round NOT IN "
                        "(SELECT round FROM wheel_bets WHERE settled=0)", (r - 1000,))
            con.execute("DELETE FROM wheel_bets WHERE settled=1 AND round < ?", (r - 20000,))
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


async def tick_loop() -> None:
    import asyncio
    import logging
    while True:
        try:
            await asyncio.to_thread(tick)
        except asyncio.CancelledError:
            raise
        except Exception:
            logging.exception("G‘ildirak fon vazifasi xatosi")
        await asyncio.sleep(2)


# ------------------------------------------------------------------ tikish

def place_bet(user_id: int, kind, amount, request_id, round_no=None) -> dict:
    _ensure_schema()
    if kind not in SECTOR_TYPES:
        raise WheelError("bad_request")
    try:
        amount = int(amount)
    except (TypeError, ValueError):
        raise WheelError("bad_request")
    if not (MIN_BET <= amount <= MAX_BET):
        raise WheelError("bad_bet")
    if not REQUEST_RE.match(str(request_id or "")):
        raise WheelError("bad_request")
    if kind in locked_types():
        raise WheelError("locked")

    con = db.connect()
    try:
        con.execute("BEGIN IMMEDIATE")
        existing = con.execute("SELECT * FROM wheel_bets WHERE request_id=?", (request_id,)).fetchone()
        if existing:
            if existing["user_id"] != user_id:
                raise WheelError("bad_request")
            con.commit()
            return {"round": existing["round"], "kind": existing["kind"], "amount": existing["amount"],
                    "replayed": True, "balance": _balance(con, user_id)}
        _, r, elapsed = _clock()
        if elapsed >= BET_WINDOW or (round_no is not None and int(round_no) != r):
            raise WheelError("closed")
        con.execute("INSERT OR IGNORE INTO users(user_id) VALUES (?)", (user_id,))
        balance = _balance(con, user_id)
        if balance < amount:
            raise WheelError("no_funds")
        con.execute("UPDATE users SET coins = coins - ? WHERE user_id=?", (amount, user_id))
        con.execute("INSERT INTO wheel_bets(request_id, round, user_id, kind, amount) VALUES (?, ?, ?, ?, ?)",
                    (request_id, r, user_id, kind, amount))
        con.commit()
        return {"round": r, "kind": kind, "amount": amount, "replayed": False, "balance": balance - amount}
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def _balance(con, user_id) -> int:
    row = con.execute("SELECT coins FROM users WHERE user_id=?", (user_id,)).fetchone()
    return int(row["coins"]) if row else 0


def claim_daily(user_id: int) -> dict:
    _ensure_schema()
    amount = daily_amount()
    if amount <= 0:
        raise WheelError("no_daily")
    today = _today()
    con = db.connect()
    try:
        con.execute("BEGIN IMMEDIATE")
        con.execute("INSERT OR IGNORE INTO users(user_id) VALUES (?)", (user_id,))
        row = con.execute("SELECT last_daily FROM users WHERE user_id=?", (user_id,)).fetchone()
        if row["last_daily"] == today:
            raise WheelError("claimed")
        con.execute("UPDATE users SET coins = coins + ?, last_daily=? WHERE user_id=?", (amount, today, user_id))
        balance = _balance(con, user_id)
        con.commit()
        return {"amount": amount, "balance": balance}
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()



def state_for(user_id: int) -> dict:
    _ensure_schema()
    settle(user_id)
    t, r, elapsed = _clock()
    today = _today()
    con = db.connect()
    try:
        con.execute("BEGIN IMMEDIATE")
        con.execute("INSERT OR IGNORE INTO users(user_id) VALUES (?)", (user_id,))
        if elapsed >= BET_WINDOW:
            current = _ensure_round(con, r)
        else:
            current = None
        con.commit()
        row = con.execute("SELECT coins, last_daily FROM users WHERE user_id=?", (user_id,)).fetchone()
        prev = con.execute("SELECT * FROM wheel_rounds WHERE round<? ORDER BY round DESC LIMIT 1", (r,)).fetchone()
        hist = con.execute("SELECT round, kind FROM wheel_rounds WHERE round<? ORDER BY round DESC LIMIT ?",
                           (r, HISTORY)).fetchall()
        agg = con.execute("SELECT COUNT(DISTINCT user_id) AS n, COALESCE(SUM(amount),0) AS s FROM wheel_bets WHERE round=?",
                          (r,)).fetchone()
        mine = con.execute("SELECT kind, SUM(amount) AS s FROM wheel_bets WHERE round=? AND user_id=? GROUP BY kind",
                           (r, user_id)).fetchall()
        per_kind = con.execute("SELECT kind, SUM(amount) AS s FROM wheel_bets WHERE round=? GROUP BY kind", (r,)).fetchall()
        recent = con.execute(
            "SELECT b.round, b.kind, b.amount, b.payout, b.settled, w.kind AS result "
            "FROM wheel_bets b LEFT JOIN wheel_rounds w ON w.round=b.round "
            "WHERE b.user_id=? ORDER BY b.id DESC LIMIT 10", (user_id,)).fetchall()
    finally:
        con.close()
    locked = locked_types()
    amount = daily_amount()
    return {
        "server_ms": int(t * 1000),
        "cycle": CYCLE, "spin": SPIN, "bet_window": BET_WINDOW,
        "round": r,
        "elapsed": elapsed,
        "balance": int(row["coins"]),
        "min_bet": MIN_BET, "max_bet": MAX_BET, "auto_options": list(AUTO_OPTIONS),
        "sectors": [{"type": k, "label": SECTOR_TYPES[k][0], "coef": SECTOR_TYPES[k][1]} for k in SECTORS],
        "types": [{"type": k, "label": v[0], "coef": v[1], "locked": k in locked} for k, v in SECTOR_TYPES.items()],
        "from_deg": rest_deg(prev) if prev else 0.0,
        "result": ({"seg": current["seg"], "kind": current["kind"], "deg": rest_deg(current)} if current else None),
        "history": [h["kind"] for h in hist],
        "players": int(agg["n"]), "total": int(agg["s"]),
        "pool": {p["kind"]: int(p["s"]) for p in per_kind},
        "mine": {m["kind"]: int(m["s"]) for m in mine},
        "recent": [
            {"round": b["round"], "kind": b["kind"], "amount": b["amount"], "payout": b["payout"],
             "settled": bool(b["settled"]), "result": b["result"]} for b in recent
        ],
        "daily": {"amount": amount, "available": amount > 0 and row["last_daily"] != today},
    }
