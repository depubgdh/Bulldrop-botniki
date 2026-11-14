"""Narvon (Ladder) — demo, faqat virtual coin.

12 pog‘ona, har pog‘onada 19 ta katak va 3 yoki 4 ta tosh. Har qadamda qahramon tasodifiy katakka sakraydi:
toshga tushsa — o‘yin tugaydi, aks holda yuqoriga chiqadi va koeffitsiyent oshadi. Istalgan payt yutuqni olish mumkin.
Barcha toshlar va sakrash joylari o‘yin boshida SERVERDA tanlanadi va qadam bosilgunga qadar yuborilmaydi.
"""
import json
import random
import re

import db

MIN_BET = 500
ROWS = 12
COLS = 19
MODES = (3, 4)
RTP = 0.944
REQUEST_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")

# Aniq ma‘lum koeffitsiyentlar (3 tosh); qolganlari xuddi shu ehtimollik bo‘yicha davom ettiriladi.
GIVEN = {3: {1: 1.12, 2: 1.33, 3: 1.60}}


class LadderError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def table(stones: int) -> list:
    p = (COLS - stones) / COLS
    out = []
    given = GIVEN.get(stones, {})
    for k in range(1, ROWS + 1):
        if k in given:
            m = given[k]
        elif out and given:
            m = round(out[-1] / p + 1e-9, 2)
        else:
            m = round(RTP / (p ** k) + 1e-9, 2)
        out.append(m)
    return out


def multiplier(stones: int, k: int) -> float:
    return table(stones)[k - 1] if k > 0 else 1.0


_SCHEMA_OK = False


def _ensure_schema() -> None:
    global _SCHEMA_OK
    if _SCHEMA_OK:
        return
    with db.connect() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS ladder_games (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id TEXT NOT NULL UNIQUE,
                user_id INTEGER NOT NULL,
                bet INTEGER NOT NULL,
                stones INTEGER NOT NULL,
                plan TEXT NOT NULL,
                steps INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'active',
                payout INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        con.execute("CREATE INDEX IF NOT EXISTS idx_ladder_user ON ladder_games(user_id, status)")
    _SCHEMA_OK = True


def _balance(con, user_id: int) -> int:
    row = con.execute("SELECT coins FROM users WHERE user_id=?", (user_id,)).fetchone()
    return int(row["coins"]) if row else 0


def _view(row, lost_row: bool = False) -> dict:
    plan = json.loads(row["plan"])
    k = row["steps"]
    s = row["stones"]
    visible = k + (1 if lost_row else 0)
    out = {
        "id": row["id"], "bet": row["bet"], "stones": s, "steps": k, "status": row["status"], "payout": row["payout"],
        "mult": multiplier(s, k), "next_mult": multiplier(s, k + 1) if k < ROWS else None,
        "cash": int(row["bet"] * multiplier(s, k)) if k else 0,
        "rows": plan[:visible],
    }
    if row["status"] != "active":
        out["plan"] = plan
    return out


def _active(con, user_id: int):
    return con.execute("SELECT * FROM ladder_games WHERE user_id=? AND status='active' ORDER BY id DESC LIMIT 1",
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
    return {"balance": balance, "min_bet": MIN_BET, "max_bet": balance, "rows": ROWS, "cols": COLS,
            "modes": list(MODES), "tables": {str(m): table(m) for m in MODES},
            "game": _view(row) if row else None}


def start(user_id: int, bet, stones, request_id) -> dict:
    _ensure_schema()
    try:
        bet, stones = int(bet), int(stones)
    except (TypeError, ValueError):
        raise LadderError("bad_request")
    if stones not in MODES or not REQUEST_RE.match(str(request_id or "")):
        raise LadderError("bad_request")
    if bet < MIN_BET:
        raise LadderError("bad_bet")

    def run(con):
        old = con.execute("SELECT * FROM ladder_games WHERE request_id=?", (request_id,)).fetchone()
        if old:
            if old["user_id"] != user_id:
                raise LadderError("bad_request")
            return {"game": _view(old), "balance": _balance(con, user_id), "replayed": True}
        if _active(con, user_id):
            raise LadderError("active")
        con.execute("INSERT OR IGNORE INTO users(user_id) VALUES (?)", (user_id,))
        balance = _balance(con, user_id)
        if balance < bet:
            raise LadderError("no_funds")
        con.execute("UPDATE users SET coins = coins - ? WHERE user_id=?", (bet, user_id))
        rnd = random.SystemRandom()
        plan = [{"stones": sorted(rnd.sample(range(COLS), stones)), "jump": rnd.randrange(COLS)} for _ in range(ROWS)]
        cur = con.execute("INSERT INTO ladder_games(request_id, user_id, bet, stones, plan) VALUES (?,?,?,?,?)",
                          (request_id, user_id, bet, stones, json.dumps(plan)))
        row = con.execute("SELECT * FROM ladder_games WHERE id=?", (cur.lastrowid,)).fetchone()
        return {"game": _view(row), "balance": balance - bet, "replayed": False}

    return _tx(run)


def _win(con, row) -> object:
    payout = int(row["bet"] * multiplier(row["stones"], row["steps"]))
    con.execute("UPDATE ladder_games SET status='won', payout=? WHERE id=?", (payout, row["id"]))
    con.execute("UPDATE users SET coins = coins + ? WHERE user_id=?", (payout, row["user_id"]))
    return con.execute("SELECT * FROM ladder_games WHERE id=?", (row["id"],)).fetchone()


def step(user_id: int) -> dict:
    _ensure_schema()

    def run(con):
        row = _active(con, user_id)
        if not row:
            raise LadderError("no_game")
        plan = json.loads(row["plan"])
        k = row["steps"]
        cur = plan[k]
        if cur["jump"] in cur["stones"]:
            con.execute("UPDATE ladder_games SET status='lost', payout=0 WHERE id=?", (row["id"],))
            row = con.execute("SELECT * FROM ladder_games WHERE id=?", (row["id"],)).fetchone()
            return {"game": _view(row, lost_row=True), "balance": _balance(con, user_id), "hit": True}
        con.execute("UPDATE ladder_games SET steps=steps+1 WHERE id=?", (row["id"],))
        row = con.execute("SELECT * FROM ladder_games WHERE id=?", (row["id"],)).fetchone()
        if row["steps"] == ROWS:
            row = _win(con, row)
        return {"game": _view(row), "balance": _balance(con, user_id), "hit": False}

    return _tx(run)


def cashout(user_id: int) -> dict:
    _ensure_schema()

    def run(con):
        row = _active(con, user_id)
        if not row:
            raise LadderError("no_game")
        if row["steps"] < 1:
            raise LadderError("nothing_opened")
        row = _win(con, row)
        return {"game": _view(row), "balance": _balance(con, user_id)}

    return _tx(run)
