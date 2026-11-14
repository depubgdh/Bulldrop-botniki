"""Saper (Mines) — demo, faqat virtual coin.

5×5 maydon. Rejim: 3 yoki 4 ta mina. Minalar o‘yin boshlanganda SERVERDA tanlanadi va bazaga yoziladi;
o‘yin tugamaguncha mijozga yuborilmaydi. Katak ochilgan sari koeffitsiyent oshadi, istalgan payt yutuqni olish mumkin.
Internet uzilsa ham o‘yin bazada saqlanadi — qayta kirganda davom ettiriladi.
"""
import json
import math
import random
import re

import db

MIN_BET = 1
MAX_BET = 1000
CELLS = 25
MODES = (3, 4)
RTP = 0.95
REQUEST_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


class MinesError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


# Admin bergan jadval (qolganlari xuddi shu formula bilan hisoblangan: 0.95 × C(25,k) / C(25−m,k)).
GIVEN = {
    3: {1: 1.08, 2: 1.23, 3: 1.42, 4: 1.64, 5: 1.92, 6: 2.25, 7: 2.68, 8: 3.21, 9: 3.90, 10: 4.80,
        11: 6.00, 12: 7.64, 13: 9.93},
    4: {8: 5.05, 9: 6.60, 10: 8.80, 11: 12.01, 12: 16.81, 13: 24.28, 14: 36.42, 15: 57.23, 16: 95.38,
        17: 171.68, 18: 343.36, 19: 801.17, 20: 2403.50, 21: 12017.50},
}


def _formula(mines: int, k: int) -> float:
    return round(RTP * math.comb(CELLS, k) / math.comb(CELLS - mines, k) + 1e-9, 2)


def multiplier(mines: int, k: int) -> float:
    if k <= 0:
        return 1.0
    return GIVEN.get(mines, {}).get(k) or _formula(mines, k)


def table(mines: int) -> list:
    return [multiplier(mines, k) for k in range(1, CELLS - mines + 1)]


_SCHEMA_OK = False


def _ensure_schema() -> None:
    global _SCHEMA_OK
    if _SCHEMA_OK:
        return
    with db.connect() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS mines_games (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id TEXT NOT NULL UNIQUE,
                user_id INTEGER NOT NULL,
                bet INTEGER NOT NULL,
                mines INTEGER NOT NULL,
                mine_cells TEXT NOT NULL,
                opened TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT 'active',
                payout INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        con.execute("CREATE INDEX IF NOT EXISTS idx_mines_user ON mines_games(user_id, status)")
    _SCHEMA_OK = True


def _balance(con, user_id: int) -> int:
    row = con.execute("SELECT coins FROM users WHERE user_id=?", (user_id,)).fetchone()
    return int(row["coins"]) if row else 0


def _view(row, reveal: bool = False) -> dict:
    opened = json.loads(row["opened"])
    k = len(opened)
    out = {
        "id": row["id"], "bet": row["bet"], "mines": row["mines"], "opened": opened, "status": row["status"],
        "mult": multiplier(row["mines"], k), "payout": row["payout"],
        "next_mult": multiplier(row["mines"], k + 1) if k < CELLS - row["mines"] else None,
        "cash": int(row["bet"] * multiplier(row["mines"], k)) if k else 0,
    }
    if reveal or row["status"] != "active":
        out["mine_cells"] = json.loads(row["mine_cells"])
    return out


def _active(con, user_id: int):
    return con.execute("SELECT * FROM mines_games WHERE user_id=? AND status='active' ORDER BY id DESC LIMIT 1",
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
        "balance": balance, "min_bet": MIN_BET, "max_bet": MAX_BET, "modes": list(MODES),
        "tables": {str(m): table(m) for m in MODES},
        "game": _view(row) if row else None,
    }


def start(user_id: int, bet, mines, request_id) -> dict:
    _ensure_schema()
    try:
        bet, mines = int(bet), int(mines)
    except (TypeError, ValueError):
        raise MinesError("bad_request")
    if mines not in MODES or not REQUEST_RE.match(str(request_id or "")):
        raise MinesError("bad_request")
    if not (MIN_BET <= bet <= MAX_BET):
        raise MinesError("bad_bet")

    def run(con):
        old = con.execute("SELECT * FROM mines_games WHERE request_id=?", (request_id,)).fetchone()
        if old:
            if old["user_id"] != user_id:
                raise MinesError("bad_request")
            return {"game": _view(old), "balance": _balance(con, user_id), "replayed": True}
        if _active(con, user_id):
            raise MinesError("active")
        con.execute("INSERT OR IGNORE INTO users(user_id) VALUES (?)", (user_id,))
        balance = _balance(con, user_id)
        if balance < bet:
            raise MinesError("no_funds")
        con.execute("UPDATE users SET coins = coins - ? WHERE user_id=?", (bet, user_id))
        cells = sorted(random.SystemRandom().sample(range(CELLS), mines))
        cur = con.execute("INSERT INTO mines_games(request_id, user_id, bet, mines, mine_cells) VALUES (?,?,?,?,?)",
                          (request_id, user_id, bet, mines, json.dumps(cells)))
        row = con.execute("SELECT * FROM mines_games WHERE id=?", (cur.lastrowid,)).fetchone()
        return {"game": _view(row), "balance": balance - bet, "replayed": False}

    return _tx(run)


def _finish_win(con, row, opened) -> dict:
    payout = int(row["bet"] * multiplier(row["mines"], len(opened)))
    con.execute("UPDATE mines_games SET status='won', payout=?, opened=? WHERE id=?",
                (payout, json.dumps(opened), row["id"]))
    con.execute("UPDATE users SET coins = coins + ? WHERE user_id=?", (payout, row["user_id"]))
    return con.execute("SELECT * FROM mines_games WHERE id=?", (row["id"],)).fetchone()


def open_cell(user_id: int, cell) -> dict:
    _ensure_schema()
    try:
        cell = int(cell)
    except (TypeError, ValueError):
        raise MinesError("bad_request")
    if not (0 <= cell < CELLS):
        raise MinesError("bad_request")

    def run(con):
        row = _active(con, user_id)
        if not row:
            raise MinesError("no_game")
        opened = json.loads(row["opened"])
        if cell in opened:
            return {"game": _view(row), "balance": _balance(con, user_id), "hit": False}
        if cell in json.loads(row["mine_cells"]):
            con.execute("UPDATE mines_games SET status='lost', payout=0 WHERE id=?", (row["id"],))
            row = con.execute("SELECT * FROM mines_games WHERE id=?", (row["id"],)).fetchone()
            return {"game": _view(row), "balance": _balance(con, user_id), "hit": True, "cell": cell}
        opened.append(cell)
        if len(opened) == CELLS - row["mines"]:
            row = _finish_win(con, row, opened)
        else:
            con.execute("UPDATE mines_games SET opened=? WHERE id=?", (json.dumps(opened), row["id"]))
            row = con.execute("SELECT * FROM mines_games WHERE id=?", (row["id"],)).fetchone()
        return {"game": _view(row), "balance": _balance(con, user_id), "hit": False, "cell": cell}

    return _tx(run)


def cashout(user_id: int) -> dict:
    _ensure_schema()

    def run(con):
        row = _active(con, user_id)
        if not row:
            raise MinesError("no_game")
        opened = json.loads(row["opened"])
        if not opened:
            raise MinesError("nothing_opened")
        row = _finish_win(con, row, opened)
        return {"game": _view(row), "balance": _balance(con, user_id)}

    return _tx(run)
