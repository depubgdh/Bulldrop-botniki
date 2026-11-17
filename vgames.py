"""Virtual (arkada) o'yinlar: eng yaxshi natijalar jadvali.
Bu o'yinlar coin bermaydi va coin olmaydi — faqat o'yin va reyting. (Natija mijozdan keladi, shuning uchun
unga mukofot bog'lanmagan.) Yangi o'yin qo'shish: VGAMES ga qator qo'shing (20 tagacha)."""
import db

VGAMES = {
    "paperio": "Bull paper.io",
}
MAX_VGAMES = 20
MAX_SCORE = 1000  # paperio: xarita ulushi, promille (0..1000)
_OK = False


def _ensure():
    global _OK
    if _OK:
        return
    with db.connect() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS vgame_scores (
                user_id INTEGER NOT NULL,
                game TEXT NOT NULL,
                best INTEGER NOT NULL DEFAULT 0,
                plays INTEGER NOT NULL DEFAULT 0,
                name TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, game)
            )
        """)
    _OK = True


def submit(user_id: int, name: str, game: str, score: int) -> dict:
    _ensure()
    if game not in VGAMES:
        raise ValueError("bad_game")
    score = max(0, min(MAX_SCORE, int(score)))
    name = (name or "Bull")[:24]
    with db.connect() as con:
        con.execute(
            "INSERT INTO vgame_scores(user_id, game, best, plays, name) VALUES (?, ?, ?, 1, ?) "
            "ON CONFLICT(user_id, game) DO UPDATE SET best=MAX(best, excluded.best), plays=plays+1, "
            "name=excluded.name, updated_at=CURRENT_TIMESTAMP",
            (user_id, game, score, name))
        return dict(con.execute("SELECT best, plays FROM vgame_scores WHERE user_id=? AND game=?", (user_id, game)).fetchone())


def top(game: str, user_id: int, limit: int = 10) -> dict:
    _ensure()
    if game not in VGAMES:
        raise ValueError("bad_game")
    with db.connect() as con:
        rows = con.execute(
            "SELECT user_id, name, best FROM vgame_scores WHERE game=? AND best>0 ORDER BY best DESC, updated_at ASC LIMIT ?",
            (game, int(limit))).fetchall()
        mine = con.execute("SELECT best, plays FROM vgame_scores WHERE user_id=? AND game=?", (user_id, game)).fetchone()
    return {
        "top": [{"name": r["name"], "best": r["best"], "me": r["user_id"] == user_id} for r in rows],
        "mine": dict(mine) if mine else {"best": 0, "plays": 0},
    }
