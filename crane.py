"""Qurilish (Crane / Shamolli minora) — demo, faqat virtual coin.

Kran uy blokini tebratib turadi, siz «Qurish» ni bosasiz — blok tushadi. Qavatlar cheklanmagan: har qavatda koeffitsiyent
+0.1 ga oshadi (1-qavat x1.1, 2-qavat x1.2 ... 50-qavat x6.0). Shamol har qavatda boshqacha (tezligi va yo'nalishi tasodifiy).

Natija har qavat uchun serverda SystemRandom bilan, shu qavat boshlanishida tanlanadi va bazaga yoziladi; tugamaguncha
mijozga yuborilmaydi. p_k = M_(k-1)/M_k (M_0 = RTP) bo'lgani uchun istalgan qavatda yutuqni olganda kutiladigan qaytim doim RTP.
Bosish vaqti natijaga ta'sir qilmaydi (animatsiya faqat ko'rinish uchun).
"""
import json
import random
import re

import db

MIN_BET = 500
RTP = 0.92
MAX_FLOORS = 1000          # texnik chegara (amalda yetib bo'lmaydi); o'yinchi uchun qavatlar cheklanmagan
REQUEST_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


class CraneError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def multiplier(k: int) -> float:
    """k-qavat koeffitsiyenti: 1-qavat x1.1, 2-qavat x1.2 ... 50-qavat x6.0 (har qavatga +0.1)."""
    return round(1 + k / 10, 1) if k > 0 else 1.0


def payout_for(bet: int, k: int) -> int:
    return bet * (10 + k) // 10 if k > 0 else 0


def success_prob(k: int) -> float:
    """k-qavatni muvaffaqiyatli qurish ehtimoli: p_k = M_(k-1) / M_k (M_0 = RTP) — qavatda to'xtab olganda qaytim doim RTP."""
    prev = RTP if k == 1 else multiplier(k - 1)
    return prev / multiplier(k)


def base_wind(k: int) -> float:
    """Qavat balandlashgan sari shamol kuchayadi (o'rtacha)."""
    return round(1.2 + min(k, 45) * 0.17, 1)


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


def _spec(k: int, prev_dir: int = 0) -> dict:
    """k-qavat (1 dan) uchun: ok (blok joyiga tushadimi), off (tushish joyi, faqat animatsiya), speed/dir (shamol).
    Har qavatda shamol tezligi ham, yo'nalishi ham tasodifiy — natija serverda SystemRandom bilan tanlanadi."""
    rnd = random.SystemRandom()
    ok = rnd.random() < success_prob(k)
    # shamol ko'pincha oldingi qavatdagiga qarama-qarshi tomonga o'tadi (lekin har doim emas)
    direction = (-prev_dir if rnd.random() < 0.75 else prev_dir) if prev_dir else rnd.choice([-1, 1])
    if ok:
        off = round(rnd.uniform(-0.55, 0.55), 3)
    else:
        off = round(direction * rnd.uniform(0.85, 1.0), 3)
    speed = round(max(0.4, rnd.uniform(0.35, 1.45) * base_wind(k)), 1)
    return {"ok": ok, "off": off, "speed": speed, "dir": direction}


def _view(row) -> dict:
    plan = json.loads(row["plan"])
    k = row["floors"]
    return {
        "id": row["id"], "bet": row["bet"], "floors": k, "status": row["status"], "payout": row["payout"],
        "mult": multiplier(k), "next_mult": multiplier(k + 1),
        "cash": payout_for(row["bet"], k),
        "landed": [plan[i]["off"] for i in range(min(k, len(plan)))],
        # faqat tushgan qavatlar va hozirgi qavat shamoli ma'lum; natija (ok) tugamaguncha yuborilmaydi
        "winds": [{"speed": p["speed"], "dir": p["dir"]} for p in plan[:k + 1]],
    }


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
        "balance": balance, "min_bet": MIN_BET, "max_bet": balance, "rows": None,
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
                          (request_id, user_id, bet, json.dumps([_spec(1)])))
        row = con.execute("SELECT * FROM crane_games WHERE id=?", (cur.lastrowid,)).fetchone()
        return {"game": _view(row), "balance": balance - bet, "replayed": False}

    return _tx(run)


def _win(con, row) -> object:
    payout = payout_for(row["bet"], row["floors"])
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
        if k + 1 < MAX_FLOORS:
            plan.append(_spec(k + 2, cur["dir"]))
        con.execute("UPDATE crane_games SET floors=floors+1, plan=? WHERE id=?", (json.dumps(plan), row["id"]))
        row = con.execute("SELECT * FROM crane_games WHERE id=?", (row["id"],)).fetchone()
        if row["floors"] >= MAX_FLOORS:
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
