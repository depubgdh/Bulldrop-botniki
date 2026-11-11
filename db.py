import sqlite3
import random
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
        con.execute("""
            CREATE TABLE IF NOT EXISTS cases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                price INTEGER NOT NULL DEFAULT 0,
                description TEXT,
                image_url TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS case_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                price INTEGER NOT NULL DEFAULT 0,
                image_url TEXT,
                probability REAL NOT NULL DEFAULT 0,
                rarity TEXT NOT NULL DEFAULT 'common',
                is_active INTEGER NOT NULL DEFAULT 1,
                FOREIGN KEY(case_id) REFERENCES cases(id) ON DELETE CASCADE
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


def add_case(name, price, description="", image_url=""):
    with connect() as con:
        cur = con.execute(
            "INSERT INTO cases(name, price, description, image_url) VALUES (?, ?, ?, ?)",
            (name, int(price), description or "", image_url or "")
        )
        return cur.lastrowid


def get_cases():
    with connect() as con:
        return con.execute(
            "SELECT * FROM cases WHERE is_active = 1 ORDER BY price ASC"
        ).fetchall()


def get_case(case_id):
    with connect() as con:
        return con.execute("SELECT * FROM cases WHERE id=? AND is_active=1", (case_id,)).fetchone()


def add_case_item(case_id, name, price, image_url="", probability=0.0, rarity="common"):
    with connect() as con:
        con.execute(
            "INSERT INTO case_items(case_id, name, price, image_url, probability, rarity) VALUES (?, ?, ?, ?, ?, ?)",
            (int(case_id), name, int(price), image_url or "", float(probability), rarity or "common")
        )


def get_case_items(case_id):
    with connect() as con:
        return con.execute(
            "SELECT * FROM case_items WHERE case_id=? AND is_active=1 ORDER BY probability ASC",
            (int(case_id),),
        ).fetchall()


def pick_case_item(case_id):
    items = get_case_items(case_id)
    if not items:
        return None
    total = sum(float(item["probability"]) for item in items)
    if total <= 0:
        return items[0]
    roll = random.random() * total
    running = 0.0
    for item in items:
        running += float(item["probability"])
        if roll <= running:
            return item
    return items[-1]