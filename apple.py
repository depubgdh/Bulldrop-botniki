"""Apple of Fortune — demo, faqat virtual coin.

10 qator, har qatorda 5 ta olma. O‘yinchi har qatorda bitta olmani tanlaydi: «chirigan» (qurtli) bo‘lsa — o‘yin tugaydi,
aks holda keyingi qatorga o‘tadi va koeffitsiyent oshadi. Istalgan payt yutuqni olish mumkin.
Har qatorda chirigan olmalar soni: BAD = [1,1,1,1,2,2,2,3,3,4] (oxirgi qatorda 5 tadan faqat 1 ta yaxshi).
Koeffitsiyent = RTP / (shu qatorgacha omon qolish ehtimoli). RTP=0.99 bo‘lganda oxirgi qator ×349.68 beradi.
Chirigan olmalar joyi o‘yin boshida SERVERDA tanlanadi va o‘yin tugamaguncha mijozga yuborilmaydi.
"""
import json
import random
import re

import db

MIN_BET = 500
ROWS = 10
COLS = 5
BAD = [1, 1, 1, 1, 2, 2, 2, 3, 3, 4]
RTP = 0.99
REQUEST_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


class AppleError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def table() -> list:
    out, p = [], 1.0
    for b in BAD:
        p *= (COLS - b) / COLS
        out.append(round(RTP / p + 1e-9, 2))
    return out


def multiplier(k: int) -> float:
    return table()[k - 1] if k > 0 else 1.0


_OK = False


def _ensure() -> None:
    global _OK
    if _OK:
        return
    with db.connect() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS apple_games (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id TEXT NOT NULL UNIQUE,
                user_id INTEGER NOT NULL,
                bet INTEGER NOT NULL,
                plan TEXT NOT NULL,
                steps INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'active',
                payout INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        con.execute("CREATE INDEX IF NOT EXISTS idx_apple_user ON apple_games(user_id, status)")
    _OK = True


def _balance(con, user_id: int) -> int:
    row = con.execute("SELECT coins FROM users WHERE user_id=?", (user_id,)).fetchone()
    return int(row["coins"]) if row else 0


def _view(row, lost_row: bool = False) -> dict:
    plan = json.loads(row["plan"])
    k = row["steps"]
    visible = k + (1 if lost_row else 0)
    out = {
        "id": row["id"], "bet": row["bet"], "steps": k, "status": row["status"], "payout": row["payout"],
        "mult": multiplier(k), "next_mult": multiplier(k + 1) if k < ROWS else None,
        "cash": int(row["bet"] * multiplier(k)) if k else 0,
        "picks": [r["jump"] for r in plan[:visible]],
        "rows": plan[:visible] if row["status"] != "active" else [],
    }
    if row["status"] != "active":
        out["plan"] = plan
    return out


def _active(con, user_id: int):
    return con.execute("SELECT * FROM apple_games WHERE user_id=? AND status='active' ORDER BY id DESC LIMIT 1",
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
    _ensure()
    con = db.connect()
    try:
        con.execute("INSERT OR IGNORE INTO users(user_id) VALUES (?)", (user_id,))
        con.commit()
        row = _active(con, user_id)
        balance = _balance(con, user_id)
    finally:
        con.close()
    return {"balance": balance, "min_bet": MIN_BET, "max_bet": balance, "rows": ROWS, "cols": COLS,
            "bad": BAD, "table": table(), "game": _view(row) if row else None}


def start(user_id: int, bet, request_id) -> dict:
    _ensure()
    try:
        bet = int(bet)
    except (TypeError, ValueError):
        raise AppleError("bad_request")
    if not REQUEST_RE.match(str(request_id or "")):
        raise AppleError("bad_request")
    if bet < MIN_BET:
        raise AppleError("bad_bet")

    def run(con):
        old = con.execute("SELECT * FROM apple_games WHERE request_id=?", (request_id,)).fetchone()
        if old:
            if old["user_id"] != user_id:
                raise AppleError("bad_request")
            return {"game": _view(old), "balance": _balance(con, user_id), "replayed": True}
        if _active(con, user_id):
            raise AppleError("active")
        con.execute("INSERT OR IGNORE INTO users(user_id) VALUES (?)", (user_id,))
        balance = _balance(con, user_id)
        if balance < bet:
            raise AppleError("no_funds")
        con.execute("UPDATE users SET coins = coins - ? WHERE user_id=?", (bet, user_id))
        rnd = random.SystemRandom()
        plan = [{"bad": sorted(rnd.sample(range(COLS), b)), "jump": None} for b in BAD]
        cur = con.execute("INSERT INTO apple_games(request_id, user_id, bet, plan) VALUES (?,?,?,?)",
                          (request_id, user_id, bet, json.dumps(plan)))
        row = con.execute("SELECT * FROM apple_games WHERE id=?", (cur.lastrowid,)).fetchone()
        return {"game": _view(row), "balance": balance - bet, "replayed": False}

    return _tx(run)


def _win(con, row):
    payout = int(row["bet"] * multiplier(row["steps"]))
    con.execute("UPDATE apple_games SET status='won', payout=? WHERE id=?", (payout, row["id"]))
    con.execute("UPDATE users SET coins = coins + ? WHERE user_id=?", (payout, row["user_id"]))
    return con.execute("SELECT * FROM apple_games WHERE id=?", (row["id"],)).fetchone()


def step(user_id: int, col) -> dict:
    _ensure()
    try:
        col = int(col)
    except (TypeError, ValueError):
        raise AppleError("bad_request")
    if not 0 <= col < COLS:
        raise AppleError("bad_request")

    def run(con):
        row = _active(con, user_id)
        if not row:
            raise AppleError("no_game")
        plan = json.loads(row["plan"])
        cur = plan[row["steps"]]
        cur["jump"] = col
        plan_json = json.dumps(plan)
        if col in cur["bad"]:
            con.execute("UPDATE apple_games SET status='lost', payout=0, plan=? WHERE id=?", (plan_json, row["id"]))
            row = con.execute("SELECT * FROM apple_games WHERE id=?", (row["id"],)).fetchone()
            return {"game": _view(row, lost_row=True), "balance": _balance(con, user_id), "hit": True}
        con.execute("UPDATE apple_games SET steps=steps+1, plan=? WHERE id=?", (plan_json, row["id"]))
        row = con.execute("SELECT * FROM apple_games WHERE id=?", (row["id"],)).fetchone()
        if row["steps"] == ROWS:
            row = _win(con, row)
        return {"game": _view(row), "balance": _balance(con, user_id), "hit": False}

    return _tx(run)


def cashout(user_id: int) -> dict:
    _ensure()

    def run(con):
        row = _active(con, user_id)
        if not row:
            raise AppleError("no_game")
        if row["steps"] < 1:
            raise AppleError("nothing_opened")
        row = _win(con, row)
        return {"game": _view(row), "balance": _balance(con, user_id)}

    return _tx(run)
