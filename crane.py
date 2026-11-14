"""Qurilish (Crane / Shamolli minora) — demo, faqat virtual coin.

Kran uy blokini tebratib turadi, siz «Qurish» ni bosasiz — blok tushadi. 12 qavat. Har qavatda shamol kuchayadi:
shamol kuchli bo‘lgan sari blok joyiga tushmay, minora yiqilish ehtimoli oshadi, lekin koeffitsiyent ham oshadi.

Natija: har bir qavatning muvaffaqiyat ehtimoli p_k serverda belgilanadi va butun o‘yin rejasi (qaysi qavatda
minora yiqilishi) o‘yin boshida SERVERDA SystemRandom bilan tanlanadi, bazaga yoziladi va tugamaguncha mijozga
yuborilmaydi. Bosish vaqti natijaga ta’sir qilmaydi (animatsiya faqat ko‘rinish uchun).

Koeffitsiyentlar M_k jadvaldan olinadi, ehtimolliklar p_k = M_(k-1) / M_k (M_0 = RTP) shunday hisoblanadiki,
istalgan qavatda yutuqni olganda kutiladigan qaytim doim RTP (95%) ga teng bo‘ladi.
"""
import json
import random
import re

import db

MIN_BET = 500
ROWS = 12
RTP = 0.95
REQUEST_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")

# 1..12-qavat koeffitsiyentlari (1.1, 1.2, 1.3 … 40)
MULTS = [1.10, 1.20, 1.30, 1.50, 1.80, 2.25, 2.95, 4.00, 5.80, 9.30, 16.50, 40.00]


class CraneError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def success_prob(k: int) -> float:
    """k — 1..ROWS: shu qavatni muvaffaqiyatli qurish ehtimoli."""
    prev = RTP if k == 1 else MULTS[k - 2]
    return prev / MULTS[k - 1]


def multiplier(k: int) -> float:
    return MULTS[k - 1] if k > 0 else 1.0


def base_wind(k: int) -> float:
    """k — 1..ROWS: shamol tezligi (m/s). Qavat balandlashgan sari shamol kuchayadi (0.9 … 9.2)."""
    return round(0.9 + (k - 1) * 0.75, 1)


_SCHEMA_OK = False


def _ensure_schema() -> None:
    global _SCHEMA_OK
    if _SCHEMA_OK:
        return
    with db.connect() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS crane_games (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id TEXT NOT NULL UNIQUE,
                user_id INTEGER NOT NULL,
                bet INTEGER NOT NULL,
                plan TEXT NOT NULL,
                floors INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'active',
                payout INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        con.execute("CREATE INDEX IF NOT EXISTS idx_crane_user ON crane_games(user_id, status)")
    _SCHEMA_OK = True


def _balance(con, user_id: int) -> int:
    row = con.execute("SELECT coins FROM users WHERE user_id=?", (user_id,)).fetchone()
    return int(row["coins"]) if row else 0


def _make_plan() -> list:
    """Har qavat uchun: ok (blok joyiga tushadimi), off (-1..1: tushish joyi, faqat animatsiya uchun),
    speed/dir (shamol, hammaga ko‘rinadi)."""
    rnd = random.SystemRandom()
    plan = []
    for k in range(1, ROWS + 1):
        ok = rnd.random() < success_prob(k)
        direction = rnd.choice([-1, 1])
        if ok:
            off = round(rnd.uniform(-0.55, 0.55), 3)
        else:
            off = round(direction * rnd.uniform(0.85, 1.0), 3)
        speed = round(max(0.3, base_wind(k) + rnd.uniform(-0.3, 0.3)), 1)
        plan.append({"ok": ok, "off": off, "speed": speed, "dir": direction})
    return plan


def _view(row) -> dict:
    plan = json.loads(row["plan"])
    k = row["floors"]
    s = row["status"]
    out = {
        "id": row["id"], "bet": row["bet"], "floors": k, "status": s, "payout": row["payout"],
        "mult": multiplier(k),
        "next_mult": multiplier(k + 1) if k < ROWS else None,
        "cash": int(row["bet"] * multiplier(k)) if k else 0,
        "landed": [plan[i]["off"] for i in range(k)],
        # shamol hamma qavat uchun ma‘lum; natija (ok/off) faqat tushgan qavatlar uchun
        "winds": [{"speed": p["speed"], "dir": p["dir"]} for p in plan],
    }
    return out


def _active(con, user_id: int):
    return con.execute("SELECT * FROM crane_games WHERE user_id=? AND status='active' ORDER BY id DESC LIMIT 1",
                       (user_id,)).fetchone()


def _tx(fn):
    con = db.connect()
    try:
        con.execute("BEGIN IMMEDIATE")
        res = fn(con)
        con.commit()
        return res
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def state_for(user_id: int) -> dict:
    _ensure_schema()
    con = db.connect()
    try:
        con.execute("INSERT OR IGNORE INTO users(user_id) VALUES (?)", (user_id,))
        con.commit()
        row = _active(con, user_id)
        balance = _balance(con, user_id)
    finally:
        con.close()
    return {
        "balance": balance, "min_bet": MIN_BET, "max_bet": balance, "rows": ROWS,
        "mults": MULTS, "base_winds": [base_wind(k) for k in range(1, ROWS + 1)],
        "game": _view(row) if row else None,
    }


def start(user_id: int, bet, request_id) -> dict:
    _ensure_schema()
    try:
        bet = int(bet)
    except (TypeError, ValueError):
        raise CraneError("bad_request")
    if not REQUEST_RE.match(str(request_id or "")):
        raise CraneError("bad_request")
    if bet < MIN_BET:
        raise CraneError("bad_bet")

    def run(con):
        old = con.execute("SELECT * FROM crane_games WHERE request_id=?", (request_id,)).fetchone()
        if old:
            if old["user_id"] != user_id:
                raise CraneError("bad_request")
            return {"game": _view(old), "balance": _balance(con, user_id), "replayed": True}
        if _active(con, user_id):
            raise CraneError("active")
        con.execute("INSERT OR IGNORE INTO users(user_id) VALUES (?)", (user_id,))
        balance = _balance(con, user_id)
        if balance < bet:
            raise CraneError("no_funds")
        con.execute("UPDATE users SET coins = coins - ? WHERE user_id=?", (bet, user_id))
        cur = con.execute("INSERT INTO crane_games(request_id, user_id, bet, plan) VALUES (?,?,?,?)",
                          (request_id, user_id, bet, json.dumps(_make_plan())))
        row = con.execute("SELECT * FROM crane_games WHERE id=?", (cur.lastrowid,)).fetchone()
        return {"game": _view(row), "balance": balance - bet, "replayed": False}

    return _tx(run)


def _win(con, row) -> object:
    payout = int(row["bet"] * multiplier(row["floors"]))
    con.execute("UPDATE crane_games SET status='won', payout=? WHERE id=?", (payout, row["id"]))
    con.execute("UPDATE users SET coins = coins + ? WHERE user_id=?", (payout, row["user_id"]))
    return con.execute("SELECT * FROM crane_games WHERE id=?", (row["id"],)).fetchone()


def drop(user_id: int) -> dict:
    """Blokni tushiradi. hit=True — minora yiqildi (o‘yin tugadi, tikish yo‘qoladi)."""
    _ensure_schema()

    def run(con):
        row = _active(con, user_id)
        if not row:
            raise CraneError("no_game")
        plan = json.loads(row["plan"])
        k = row["floors"]
        cur = plan[k]
        if not cur["ok"]:
            con.execute("UPDATE crane_games SET status='lost', payout=0 WHERE id=?", (row["id"],))
            row = con.execute("SELECT * FROM crane_games WHERE id=?", (row["id"],)).fetchone()
            return {"game": _view(row), "balance": _balance(con, user_id), "hit": True,
                    "floor": k, "off": cur["off"], "dir": cur["dir"]}
        con.execute("UPDATE crane_games SET floors=floors+1 WHERE id=?", (row["id"],))
        row = con.execute("SELECT * FROM crane_games WHERE id=?", (row["id"],)).fetchone()
        if row["floors"] == ROWS:
            row = _win(con, row)
        return {"game": _view(row), "balance": _balance(con, user_id), "hit": False,
                "floor": k, "off": cur["off"], "dir": cur["dir"]}

    return _tx(run)


def cashout(user_id: int) -> dict:
    _ensure_schema()

    def run(con):
        row = _active(con, user_id)
        if not row:
            raise CraneError("no_game")
        if row["floors"] < 1:
            raise CraneError("nothing_opened")
        row = _win(con, row)
        return {"game": _view(row), "balance": _balance(con, user_id)}

    return _tx(run)
