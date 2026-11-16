"""Bulldrop Signal — coin evaziga beriladigan TASODIFIY tavsiya.

Muhim: bu haqiqiy o'yin natijasini bashorat qilmaydi va hech narsani kafolatlamaydi. Tavsiya serverda
tasodifiy hosil qilinadi; shu sababli har bir natijada ogohlantirish matni qaytariladi.
Narx va yoqilgan/o'chirilgan holat admin tomonidan sozlanadi (settings: signal_price_<o'yin>, signal_on_<o'yin>).
"""
import json
import random
import re

import db

_rng = random.SystemRandom()
DEFAULT_PRICE = 1000
GAMES = {
    "crash": "Crash",
    "saper": "Saper",
    "ladder": "Narvon",
    "tower": "Minora",
}
NOTE = "Tasodifiy tavsiya: haqiqiy natijani bashorat qilmaydi va yutuqni kafolatlamaydi."
REF_RE = re.compile(r"^[A-Za-z0-9_\-#. ]{1,32}$")
_SCHEMA_OK = False


class SignalError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def _ensure_schema():
    global _SCHEMA_OK
    if _SCHEMA_OK:
        return
    with db.connect() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS signal_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                game TEXT NOT NULL,
                game_ref TEXT NOT NULL DEFAULT '',
                price INTEGER NOT NULL,
                payload TEXT NOT NULL,
                result TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        con.execute("CREATE INDEX IF NOT EXISTS idx_signal_user ON signal_log(user_id, id)")
    _SCHEMA_OK = True


def price_of(game: str) -> int:
    try:
        v = int(db.get_setting(f"signal_price_{game}", DEFAULT_PRICE))
    except (TypeError, ValueError):
        v = DEFAULT_PRICE
    return max(0, v)


def is_on(game: str) -> bool:
    return db.get_setting(f"signal_on_{game}", "1") != "0"


def config() -> list:
    return [{"game": g, "title": t, "price": price_of(g), "on": is_on(g)} for g, t in GAMES.items()]


def set_config(game: str, price=None, on=None) -> None:
    if game not in GAMES:
        raise SignalError("bad_game")
    if price is not None:
        price = int(price)
        if price < 0 or price > 10_000_000:
            raise SignalError("bad_price")
        db.set_setting(f"signal_price_{game}", price)
    if on is not None:
        db.set_setting(f"signal_on_{game}", "1" if on else "0")


def make_payload(game: str) -> dict:
    if game == "crash":
        u = _rng.random()
        value = round(max(1.1, min(25.0, 0.97 / (1 - u))), 2)
        return {"kind": "crash", "cashout": value}
    if game == "saper":
        cells = sorted(_rng.sample(range(25), 5))
        return {"kind": "saper", "cells": cells}
    if game == "ladder":
        return {"kind": "ladder", "lane": _rng.randrange(20) + 1}
    if game == "tower":
        return {"kind": "tower", "rows": [_rng.choice(["L", "R"]) for _ in range(8)]}
    raise SignalError("bad_game")


def _view(row) -> dict:
    return {
        "id": row["id"], "game": row["game"], "title": GAMES.get(row["game"], row["game"]),
        "ref": row["game_ref"], "price": row["price"], "payload": json.loads(row["payload"]),
        "result": row["result"], "at": row["created_at"],
    }


def state_for(user_id: int) -> dict:
    _ensure_schema()
    with db.connect() as con:
        rows = con.execute("SELECT * FROM signal_log WHERE user_id=? ORDER BY id DESC LIMIT 30", (user_id,)).fetchall()
        wins = con.execute("SELECT COUNT(*) c FROM signal_log WHERE user_id=? AND result='win'", (user_id,)).fetchone()["c"]
        loses = con.execute("SELECT COUNT(*) c FROM signal_log WHERE user_id=? AND result='lose'", (user_id,)).fetchone()["c"]
    return {
        "games": config(), "history": [_view(r) for r in rows], "note": NOTE,
        "marked": {"win": wins, "lose": loses},
    }


def buy(user_id: int, game: str, ref: str) -> dict:
    """Coin ayirib, signal yaratadi (bitta tranzaksiyada)."""
    _ensure_schema()
    if game not in GAMES:
        raise SignalError("bad_game")
    if not is_on(game):
        raise SignalError("off")
    ref = (ref or "").strip()
    if not REF_RE.match(ref):
        raise SignalError("bad_ref")
    price = price_of(game)
    payload = make_payload(game)
    con = db.connect()
    try:
        con.execute("BEGIN IMMEDIATE")
        con.execute("INSERT OR IGNORE INTO users(user_id) VALUES (?)", (user_id,))
        coins = int(con.execute("SELECT coins FROM users WHERE user_id=?", (user_id,)).fetchone()["coins"])
        if coins < price:
            con.rollback()
            raise SignalError("no_funds")
        con.execute("UPDATE users SET coins = coins - ? WHERE user_id=?", (price, user_id))
        cur = con.execute(
            "INSERT INTO signal_log(user_id, game, game_ref, price, payload) VALUES (?, ?, ?, ?, ?)",
            (user_id, game, ref, price, json.dumps(payload)))
        row = con.execute("SELECT * FROM signal_log WHERE id=?", (cur.lastrowid,)).fetchone()
        con.commit()
        return {"signal": _view(row), "coins": coins - price, "note": NOTE}
    except SignalError:
        raise
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def mark(user_id: int, signal_id: int, result: str) -> None:
    """Foydalanuvchi o'zi belgilaydi (tashqi o'yin natijasini tizim tekshira olmaydi)."""
    _ensure_schema()
    if result not in ("win", "lose", ""):
        raise SignalError("bad_result")
    with db.connect() as con:
        cur = con.execute("UPDATE signal_log SET result=? WHERE id=? AND user_id=?", (result, int(signal_id), user_id))
        if cur.rowcount == 0:
            raise SignalError("not_found")


def admin_stats() -> dict:
    _ensure_schema()
    with db.connect() as con:
        out = {}
        for g in GAMES:
            r = con.execute(
                "SELECT COUNT(*) n, COALESCE(SUM(price),0) coins, "
                "SUM(result='win') w, SUM(result='lose') l FROM signal_log WHERE game=?", (g,)).fetchone()
            out[g] = {"count": r["n"], "coins": r["coins"], "win": r["w"] or 0, "lose": r["l"] or 0}
    return out
