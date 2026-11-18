"""Bull paper.io — COIN rejimi va majburiy reklama (demo, faqat virtual coin).

Qoidalar (doimiylarni shu fayl tepasidan o'zgartirish mumkin):
  • Har coinli o'yinga kirish: STAKE (1000) coin. Raqiblar — 8 ta bot; ularning coini yo'q va ularga hech narsa to'lanmaydi.
  • G'olib bo'lsangiz: stavkangiz qaytadi + har bir raqibning stavkasidan WIN_TAKE (30%) ni olasiz (8 ta raqib hisobida).
  • Yutqazsangiz: stavkangizning LOSE_REFUND (20%) qismi qaytariladi.
  • Tekin rejimda coin harakatlanmaydi.
  • Reklama: admin qo'shgan videolar (havola bilan); mijoz har 3 o'limdan keyin bittasini ko'rsatadi.

O'yin mijozda (brauzerda) hisoblanadi, shuning uchun natija serverda faqat «ishonarlimi» deb tekshiriladi.
Haqiqiy pul yo'q — demo."""
import json
import random
import time

import db

STAKE = 1000
WIN_TAKE = 30          # foiz: g'olib har bir yutqazgandan oladi
LOSE_REFUND = 20       # foiz: yutqazganga qaytariladi
MIN_PLAY_SECS = 20     # bundan tez tugagan o'yin natijasi qabul qilinmaydi (yutqazgan deb hisoblanadi)
STALE_SECS = 15 * 60   # tugatilmagan o'yin shu vaqtdan keyin yutqazilgan hisoblanadi
BOT_NAMES = ["Zebra", "Kobra", "Burgut", "Qoplon", "Tulpor", "Sherxon", "Mirzo", "Laylo"]
N_BOTS = len(BOT_NAMES)


class PioError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


_OK = False


def _ensure() -> None:
    global _OK
    if _OK:
        return
    with db.connect() as con:
        con.execute("""CREATE TABLE IF NOT EXISTS pio_ads (
            id INTEGER PRIMARY KEY AUTOINCREMENT, video TEXT NOT NULL DEFAULT '', link TEXT NOT NULL DEFAULT '',
            active INTEGER NOT NULL DEFAULT 1, views INTEGER NOT NULL DEFAULT 0)""")
        con.execute("""CREATE TABLE IF NOT EXISTS pio_games (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, stake INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'active', delta INTEGER NOT NULL DEFAULT 0,
            started_at REAL NOT NULL, finished_at REAL)""")
    _OK = True


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


def _balance(con, user_id) -> int:
    row = con.execute("SELECT coins FROM users WHERE user_id=?", (user_id,)).fetchone()
    return int(row["coins"]) if row else 0


def rules() -> dict:
    return {"stake": STAKE, "win_take": WIN_TAKE, "lose_refund": LOSE_REFUND}


def _settle(con, game, areas, quit_) -> dict:
    """areas — 9 ta son: [siz, bot1..bot8] (promille). Faqat sizning hisobingiz o'zgaradi (botlarga coin to'lanmaydi)."""
    now = time.time()
    uid = game["user_id"]
    ok = (not quit_) and (now - game["started_at"]) >= MIN_PLAY_SECS and areas is not None
    winner = 0
    if ok:
        best = max(areas)
        winner = areas.index(best)                       # 0 = siz, 1..8 = botlar
        if winner == 0 and areas.count(best) > 1:        # teng bo'lsa — botga
            winner = areas.index(best, 1)
    else:
        winner = random.randint(1, N_BOTS)
    stake = game["stake"]
    pay = stake + (stake * WIN_TAKE // 100) * N_BOTS if winner == 0 else stake * LOSE_REFUND // 100
    con.execute("UPDATE users SET coins = coins + ? WHERE user_id=?", (pay, uid))
    delta = pay - stake
    con.execute("UPDATE pio_games SET status=?, delta=?, finished_at=? WHERE id=?",
                ("won" if winner == 0 else "lost", delta, now, game["id"]))
    name = "Siz" if winner == 0 else BOT_NAMES[winner - 1]
    return {"won": winner == 0, "winner": winner, "winner_name": name, "delta": delta,
            "balance": _balance(con, uid), "accepted": bool(ok)}


def _expire(con, user_id) -> None:
    for g in con.execute("SELECT * FROM pio_games WHERE user_id=? AND status='active'", (user_id,)).fetchall():
        if time.time() - g["started_at"] > STALE_SECS:
            _settle(con, g, None, True)


def lobby(user_id: int) -> dict:
    _ensure()

    def run(con):
        con.execute("INSERT OR IGNORE INTO users(user_id) VALUES (?)", (user_id,))
        _expire(con, user_id)
        active = con.execute("SELECT id FROM pio_games WHERE user_id=? AND status='active'", (user_id,)).fetchone()
        return dict(rules(), balance=_balance(con, user_id), active=bool(active), names=BOT_NAMES)

    return _tx(run)


def start(user_id: int) -> dict:
    _ensure()

    def run(con):
        con.execute("INSERT OR IGNORE INTO users(user_id) VALUES (?)", (user_id,))
        _expire(con, user_id)
        old = con.execute("SELECT * FROM pio_games WHERE user_id=? AND status='active'", (user_id,)).fetchone()
        if old:                                           # eski tugamagan o'yin — yutqazilgan deb yopiladi
            _settle(con, old, None, True)
        if _balance(con, user_id) < STAKE:
            raise PioError("no_funds")
        con.execute("UPDATE users SET coins = coins - ? WHERE user_id=?", (STAKE, user_id))
        cur = con.execute("INSERT INTO pio_games(user_id, stake, started_at) VALUES (?,?,?)",
                          (user_id, STAKE, time.time()))
        return dict(rules(), game_id=cur.lastrowid, balance=_balance(con, user_id))

    return _tx(run)


def finish(user_id: int, game_id, areas, quit_=False) -> dict:
    _ensure()
    try:
        game_id = int(game_id)
    except (TypeError, ValueError):
        raise PioError("bad_request")
    clean = None
    if not quit_:
        if not isinstance(areas, list) or len(areas) != N_BOTS + 1:
            raise PioError("bad_request")
        try:
            clean = [int(a) for a in areas]
        except (TypeError, ValueError):
            raise PioError("bad_request")
        if any(a < 0 or a > 1000 for a in clean) or sum(clean) > 1000:
            raise PioError("bad_request")

    def run(con):
        g = con.execute("SELECT * FROM pio_games WHERE id=? AND user_id=?", (game_id, user_id)).fetchone()
        if not g or g["status"] != "active":
            raise PioError("no_game")
        return _settle(con, g, clean, bool(quit_))

    return _tx(run)


# ------------------------------------------------------------------ Reklama videolari

def ads_all() -> list:
    _ensure()
    with db.connect() as con:
        return [dict(r) for r in con.execute("SELECT * FROM pio_ads ORDER BY id DESC")]


def ad_pick():
    """Tasodifiy faol reklama (videosi bor)."""
    _ensure()
    with db.connect() as con:
        rows = con.execute("SELECT * FROM pio_ads WHERE active=1 AND video<>''").fetchall()
        if not rows:
            return None
        r = random.choice(rows)
        con.execute("UPDATE pio_ads SET views = views + 1 WHERE id=?", (r["id"],))
        return dict(r)


def ad_save(ad_id, video, link, active) -> int:
    _ensure()
    keep_video = video is None and bool(ad_id)
    video = (video or "").strip()[:500]
    link = (link or "").strip()[:500]
    if link and not link.lower().startswith(("https://", "http://", "tg://")):
        raise PioError("bad_request")
    if video and not video.lower().startswith(("https://", "http://", "tg:")):
        raise PioError("bad_request")
    with db.connect() as con:
        if ad_id:
            if keep_video:
                con.execute("UPDATE pio_ads SET link=?, active=? WHERE id=?", (link, 1 if active else 0, ad_id))
            else:
                con.execute("UPDATE pio_ads SET video=?, link=?, active=? WHERE id=?", (video, link, 1 if active else 0, ad_id))
            return int(ad_id)
        cur = con.execute("INSERT INTO pio_ads(video, link, active) VALUES (?,?,?)", (video, link, 1 if active else 0))
        return cur.lastrowid


def ad_set_video(ad_id, ref) -> bool:
    _ensure()
    with db.connect() as con:
        return con.execute("UPDATE pio_ads SET video=? WHERE id=?", (ref, ad_id)).rowcount > 0


def ad_delete(ad_id) -> None:
    _ensure()
    with db.connect() as con:
        con.execute("DELETE FROM pio_ads WHERE id=?", (ad_id,))
