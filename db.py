import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).with_name("bulldrop.sqlite3")

def connect():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    with connect() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                phone TEXT,
                accepted_terms INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS saper_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                game_id TEXT NOT NULL,
                green_cells TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)

def get_user(user_id):
    with connect() as con:
        return con.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()

def save_user(user_id, username=None, phone=None, accepted_terms=None):
    old = get_user(user_id)
    values = {
        "username": username if username is not None else (old["username"] if old else None),
        "phone": phone if phone is not None else (old["phone"] if old else None),
        "accepted_terms": accepted_terms if accepted_terms is not None else (old["accepted_terms"] if old else 0),
    }
    with connect() as con:
        con.execute("""
            INSERT INTO users(user_id, username, phone, accepted_terms)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username=excluded.username,
                phone=excluded.phone,
                accepted_terms=excluded.accepted_terms
        """, (user_id, values["username"], values["phone"], values["accepted_terms"]))

def add_saper_result(user_id, game_id, green_cells):
    with connect() as con:
        con.execute(
            "INSERT INTO saper_history(user_id, game_id, green_cells) VALUES (?, ?, ?)",
            (user_id, game_id, ",".join(map(str, green_cells)))
        )
