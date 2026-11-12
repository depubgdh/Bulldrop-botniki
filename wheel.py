"""G‘ildirak o'yini. Faqat virtual coin bilan: pul yechib bo‘lmaydi, pul kiritib bo‘lmaydi.

Natija SERVERDA tanlanadi va BIR tranzaksiyada bazaga yoziladi (tikish yechiladi, yutuq qaytariladi).
Mijoz internetni yo‘qotsa ham natija yo‘qolmaydi: /api/wheel/state oxirgi o‘yinni qaytaradi.
Bir xil request_id ikki marta hisoblanmaydi (qayta yuborish xavfsiz)."""
import json
import random
import re
from datetime import datetime, timedelta, timezone

import db

MIN_BET = 1
MAX_BET = 1000
AUTO_OPTIONS = (1, 5, 10, 25)
BET_PRESETS = (1, 5, 10, 50)
DAILY_TZ = timezone(timedelta(hours=5))  # Toshkent vaqti: kun 00:00 da yangilanadi
REQUEST_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")

# Sektor turlari: kalit -> (yorliq, koeffitsiyent). Koeffitsiyent -1 = yutqazish.
# Qaytim = tikish + tikish * koeffitsiyent. Yutqazishda 0.
SECTOR_TYPES = {
    "lose": ("❌ Yutqazish", -1),
    "x0": ("1x", 0),
    "x2": ("2x", 2),
    "x5": ("5x", 5),
    "x10": ("10x", 10),
}
# 40 ta sektor (og‘irlik): yutqazish 24, 1x 12, 2x 2, 5x 1, 10x 1. Taxminiy qaytim ~87%.
_BASE = ["lose"] * 24 + ["x0"] * 12 + ["x2"] * 2 + ["x5"] + ["x10"]
SECTORS = _BASE[:]
random.Random(7).shuffle(SECTORS)  # doimiy tartib: g‘ildirak har safar bir xil ko‘rinadi


class WheelError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def locked_types() -> set:
    try:
        return set(json.loads(db.get_setting("wheel_locked") or "[]"))
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


def _today() -> str:
    return datetime.now(DAILY_TZ).date().isoformat()


def _pool() -> list:
    locked = locked_types()
    return [i for i, kind in enumerate(SECTORS) if kind not in locked]


def _spin_json(row) -> dict:
    results = [int(x) for x in row["results"].split(",") if x != ""]
    return {
        "request_id": row["request_id"],
        "bet": row["bet"],
        "count": row["count"],
        "results": results,
        "total_bet": row["total_bet"],
        "total_payout": row["total_payout"],
        "net": row["total_payout"] - row["total_bet"],
    }


def play(user_id: int, bet, count, request_id: str) -> dict:
    """Bir yoki bir nechta o‘yin. Hammasi bitta tranzaksiyada."""
    try:
        bet, count = int(bet), int(count)
    except (TypeError, ValueError):
        raise WheelError("bad_request")
    if not (MIN_BET <= bet <= MAX_BET):
        raise WheelError("bad_bet")
    if count not in AUTO_OPTIONS:
        raise WheelError("bad_count")
    if not REQUEST_RE.match(str(request_id or "")):
        raise WheelError("bad_request")

    con = db.connect()
    try:
        con.execute("BEGIN IMMEDIATE")
        existing = con.execute("SELECT * FROM wheel_spins WHERE request_id=?", (request_id,)).fetchone()
        if existing:
            if existing["user_id"] != user_id:
                raise WheelError("bad_request")
            con.commit()
            return {**_spin_json(existing), "replayed": True, "balance": _balance(con, user_id)}

        con.execute("INSERT OR IGNORE INTO users(user_id) VALUES (?)", (user_id,))
        balance = _balance(con, user_id)
        pool = _pool()
        if not pool:
            raise WheelError("no_sectors")

        results, total_bet, total_payout = [], 0, 0
        for _ in range(count):
            if balance < bet:
                break
            idx = random.choice(pool)
            coef = SECTOR_TYPES[SECTORS[idx]][1]
            payout = 0 if coef < 0 else bet + bet * coef
            balance += payout - bet
            total_bet += bet
            total_payout += payout
            results.append(idx)
        if not results:
            raise WheelError("no_funds")

        con.execute("UPDATE users SET coins=? WHERE user_id=?", (balance, user_id))
        con.execute(
            "INSERT INTO wheel_spins(request_id, user_id, bet, count, results, total_bet, total_payout) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (request_id, user_id, bet, len(results), ",".join(map(str, results)), total_bet, total_payout),
        )
        con.commit()
        row = con.execute("SELECT * FROM wheel_spins WHERE request_id=?", (request_id,)).fetchone()
        return {**_spin_json(row), "replayed": False, "balance": balance}
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def _balance(con, user_id) -> int:
    row = con.execute("SELECT coins FROM users WHERE user_id=?", (user_id,)).fetchone()
    return int(row["coins"]) if row else 0


def claim_daily(user_id: int) -> dict:
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
    today = _today()
    con = db.connect()
    try:
        con.execute("INSERT OR IGNORE INTO users(user_id) VALUES (?)", (user_id,))
        con.commit()
        row = con.execute("SELECT coins, last_daily FROM users WHERE user_id=?", (user_id,)).fetchone()
        last = con.execute("SELECT * FROM wheel_spins WHERE user_id=? ORDER BY id DESC LIMIT 1", (user_id,)).fetchone()
    finally:
        con.close()
    locked = locked_types()
    amount = daily_amount()
    return {
        "balance": int(row["coins"]),
        "min_bet": MIN_BET,
        "max_bet": MAX_BET,
        "bet_presets": list(BET_PRESETS),
        "auto_options": list(AUTO_OPTIONS),
        "sectors": [
            {"type": kind, "label": SECTOR_TYPES[kind][0], "coef": SECTOR_TYPES[kind][1], "locked": kind in locked}
            for kind in SECTORS
        ],
        "daily": {"amount": amount, "available": amount > 0 and row["last_daily"] != today},
        "last": _spin_json(last) if last else None,
    }
