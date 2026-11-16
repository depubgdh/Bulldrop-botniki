"""Minora (Tower) — demo, faqat virtual coin.

8 qavat, har qavatda 2 ta katak: biri xavfsiz, biri tuzoq. Pastdan yuqoriga qarab katak tanlanadi.
Tuzoqlar o‘yin boshida SERVERDA tanlanadi va tugamaguncha mijozga yuborilmaydi.
Yutuq = tikish × 1.84 × 2^(qavat−1); istalgan payt yutuqni olish mumkin.
"""
import json
import random
import re

import db

MIN_BET = 500
ROWS = 8
BASE = 1.84
REQUEST_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


class TowerError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def multiplier(k: int) -> float:
    return round(BASE * (2 ** (k - 1)), 2) if k > 0 else 0.0


def payout_for(bet: int, k: int) -> int:
    return int(bet * BASE * (2 ** (k - 1))) if k > 0 else 0


_SCHEMA_OK = False


def _ensure_schema() -> None:
    global _SCHEMA_OK
    if _SCHEMA_OK:
        return
    with db.connect() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS tower_games (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id TEXT NOT NULL UNIQUE,
                user_id INTEGER NOT NULL,
                bet INTEGER NOT NULL,
                traps TEXT NOT NULL,
                picks TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT 'active',
                payout INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        con.execute("CREATE INDEX IF NOT EXISTS idx_tower_user ON tower_games(user_id, status)")
    _SCHEMA_OK = True


def _balance(con, user_id: int) -> int:
    row = con.execute("SELECT coins FROM users WHERE user_id=?", (user_id,)).fetchone()
    return int(row["coins"]) if row else 0


def _view(row) -> dict:
    picks = json.loads(row["picks"])
    k = len(picks)
    out = {
        "id": row["id"], "bet": row["bet"], "picks": picks, "status": row["status"], "payout": row["payout"],
        "cash": payout_for(row["bet"], k),
        "rows": [payout_for(row["bet"], i + 1) for i in range(ROWS)],
    }
    if row["status"] != "active":
        out["traps"] = json.loads(row["traps"])
    return out


def _active(con, user_id: int):
    return con.execute("SELECT * FROM tower_games WHERE user_id=? AND status='active' ORDER BY id DESC LIMIT 1",
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
    return {"balance": balance, "min_bet": MIN_BET, "max_bet": balance, "rows": ROWS,
            "mults": [multiplier(i + 1) for i in range(ROWS)], "game": _view(row) if row else None}


def start(user_id: int, bet, request_id) -> dict:
    _ensure_schema()
    try:
        bet = int(bet)
    except (TypeError, ValueError):
        raise TowerError("bad_request")
    if not REQUEST_RE.match(str(request_id or "")):
        raise TowerError("bad_request")
    if bet < MIN_BET:
        raise TowerError("bad_bet")

    def run(con):
        old = con.execute("SELECT * FROM tower_games WHERE request_id=?", (request_id,)).fetchone()
        if old:
            if old["user_id"] != user_id:
                raise TowerError("bad_request")
            return {"game": _view(old), "balance": _balance(con, user_id), "replayed": True}
        if _active(con, user_id):
            raise TowerError("active")
        con.execute("INSERT OR IGNORE INTO users(user_id) VALUES (?)", (user_id,))
        balance = _balance(con, user_id)
        if balance < bet:
            raise TowerError("no_funds")
        con.execute("UPDATE users SET coins = coins - ? WHERE user_id=?", (bet, user_id))
        rnd = random.SystemRandom()
        traps = [rnd.randint(0, 1) for _ in range(ROWS)]
        cur = con.execute("INSERT INTO tower_games(request_id, user_id, bet, traps) VALUES (?,?,?,?)",
                          (request_id, user_id, bet, json.dumps(traps)))
        row = con.execute("SELECT * FROM tower_games WHERE id=?", (cur.lastrowid,)).fetchone()
        return {"game": _view(row), "balance": balance - bet, "replayed": False}

    return _tx(run)


def _win(con, row, picks) -> object:
    payout = payout_for(row["bet"], len(picks))
    con.execute("UPDATE tower_games SET status='won', payout=?, picks=? WHERE id=?",
                (payout, json.dumps(picks), row["id"]))
    con.execute("UPDATE users SET coins = coins + ? WHERE user_id=?", (payout, row["user_id"]))
    return con.execute("SELECT * FROM tower_games WHERE id=?", (row["id"],)).fetchone()


def pick(user_id: int, col) -> dict:
    _ensure_schema()
    try:
        col = int(col)
    except (TypeError, ValueError):
        raise TowerError("bad_request")
    if col not in (0, 1):
        raise TowerError("bad_request")

    def run(con):
        row = _active(con, user_id)
        if not row:
            raise TowerError("no_game")
        picks = json.loads(row["picks"])
        traps = json.loads(row["traps"])
        level = len(picks)
        if traps[level] == col:
            con.execute("UPDATE tower_games SET status='lost', payout=0 WHERE id=?", (row["id"],))
            row = con.execute("SELECT * FROM tower_games WHERE id=?", (row["id"],)).fetchone()
            return {"game": _view(row), "balance": _balance(con, user_id), "hit": True, "col": col, "level": level}
        picks.append(col)
        if len(picks) == ROWS:
            row = _win(con, row, picks)
        else:
            con.execute("UPDATE tower_games SET picks=? WHERE id=?", (json.dumps(picks), row["id"]))
            row = con.execute("SELECT * FROM tower_games WHERE id=?", (row["id"],)).fetchone()
        return {"game": _view(row), "balance": _balance(con, user_id), "hit": False, "col": col, "level": level}

    return _tx(run)


def cashout(user_id: int) -> dict:
    _ensure_schema()

    def run(con):
        row = _active(con, user_id)
        if not row:
            raise TowerError("no_game")
        picks = json.loads(row["picks"])
        if not picks:
            raise TowerError("nothing_opened")
        row = _win(con, row, picks)
        return {"game": _view(row), "balance": _balance(con, user_id)}

    return _tx(run)
